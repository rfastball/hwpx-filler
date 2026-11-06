//! Syntax based Rust complexity measurements for the repository budget gate.
//! Input: {"root":"...","files":["crates/.../src/lib.rs"]} on stdin.

use std::collections::BTreeMap;
use std::io::Read;
use std::path::Path;

use proc_macro2::{TokenStream, TokenTree};
use serde::{Deserialize, Serialize};
use syn::visit::{self, Visit};
use syn::{BinOp, Expr, Item, Meta, Pat, Stmt};

#[derive(Deserialize)]
struct Request {
    root: String,
    files: Vec<String>,
}

#[derive(Serialize)]
struct Unit {
    path: String,
    qual: String,
    kind: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    tier: Option<&'static str>,
    metrics: BTreeMap<&'static str, usize>,
    detail: Vec<serde_json::Value>,
}

fn unit(path: &str, qual: String, kind: &'static str, metric: &'static str, value: usize) -> Unit {
    Unit {
        path: path.to_owned(),
        qual,
        kind,
        tier: None,
        metrics: BTreeMap::from([(metric, value)]),
        detail: Vec::new(),
    }
}

fn is_test_mod(node: &syn::ItemMod) -> bool {
    node.attrs.iter().any(|attr| {
        if !attr.path().is_ident("cfg") {
            return false;
        }
        matches!(&attr.meta, Meta::List(list) if list.tokens.to_string() == "test")
    })
}

fn macro_control(stream: TokenStream) -> (usize, usize) {
    let mut statements = 0;
    let mut branches = 0;
    let mut previous = None;
    for token in stream {
        match token {
            TokenTree::Group(group) => {
                let (inner_statements, inner_branches) = macro_control(group.stream());
                statements += inner_statements;
                branches += inner_branches;
                previous = None;
            }
            TokenTree::Ident(ident) => {
                if matches!(
                    ident.to_string().as_str(),
                    "if" | "for" | "while" | "loop" | "match"
                ) {
                    statements += 1;
                    branches += 1;
                }
                previous = None;
            }
            TokenTree::Punct(punct) => {
                let character = punct.as_char();
                if previous == Some(character) && matches!(character, '&' | '|') {
                    branches += 1;
                    previous = None;
                } else {
                    previous = Some(character);
                }
            }
            TokenTree::Literal(_) => previous = None,
        }
    }
    (statements, branches)
}

#[derive(Default)]
struct ModuleCount {
    statements: usize,
    include_tests: bool,
}

impl<'ast> Visit<'ast> for ModuleCount {
    fn visit_macro(&mut self, node: &'ast syn::Macro) {
        self.statements += macro_control(node.tokens.clone()).0;
    }

    fn visit_item(&mut self, node: &'ast Item) {
        if !self.include_tests && matches!(node, Item::Mod(module) if is_test_mod(module)) {
            return;
        }
        self.statements += 1;
        visit::visit_item(self, node);
    }

    fn visit_impl_item(&mut self, node: &'ast syn::ImplItem) {
        self.statements += 1;
        visit::visit_impl_item(self, node);
    }

    fn visit_trait_item(&mut self, node: &'ast syn::TraitItem) {
        self.statements += 1;
        visit::visit_trait_item(self, node);
    }

    fn visit_stmt(&mut self, node: &'ast Stmt) {
        if !matches!(node, Stmt::Item(_)) {
            self.statements += 1;
        }
        visit::visit_stmt(self, node);
    }
}

#[derive(Default)]
struct FunctionCount {
    statements: usize,
    branches: usize,
}

impl<'ast> Visit<'ast> for FunctionCount {
    fn visit_macro(&mut self, node: &'ast syn::Macro) {
        let (statements, branches) = macro_control(node.tokens.clone());
        self.statements += statements;
        self.branches += branches;
    }

    fn visit_local(&mut self, node: &'ast syn::Local) {
        if node
            .init
            .as_ref()
            .is_some_and(|init| init.diverge.is_some())
        {
            self.branches += 1;
        }
        visit::visit_local(self, node);
    }

    fn visit_stmt(&mut self, node: &'ast Stmt) {
        self.statements += 1;
        if matches!(node, Stmt::Item(Item::Fn(_) | Item::Mod(_))) {
            return;
        }
        visit::visit_stmt(self, node);
    }

    fn visit_expr(&mut self, node: &'ast Expr) {
        self.branches += match node {
            Expr::If(_) | Expr::ForLoop(_) | Expr::While(_) | Expr::Loop(_) => 1,
            Expr::Match(value) => value
                .arms
                .iter()
                .filter(|arm| !matches!(&arm.pat, Pat::Wild(_)) || arm.guard.is_some())
                .count(),
            Expr::Binary(value) if matches!(value.op, BinOp::And(_) | BinOp::Or(_)) => 1,
            _ => 0,
        };
        visit::visit_expr(self, node);
    }
}

struct Collector<'a> {
    path: &'a str,
    prefix: String,
    units: Vec<Unit>,
    methods: BTreeMap<(String, bool), usize>,
    test_mode: bool,
}

impl Collector<'_> {
    fn function(&mut self, name: &str, block: &syn::Block) {
        let mut count = FunctionCount::default();
        count.visit_block(block);
        let qual = format!("{}{}", self.prefix, name);
        let mut entry = unit(
            self.path,
            qual,
            "function",
            "function_complexity",
            1 + count.branches,
        );
        if self.test_mode {
            entry.tier = Some("test");
        }
        entry
            .metrics
            .insert("function_statements", count.statements);
        self.units.push(entry);
    }

    fn nested(&mut self, name: &str, visit: impl FnOnce(&mut Self)) {
        let next = format!("{}{name}.", self.prefix);
        let prior = std::mem::replace(&mut self.prefix, next);
        visit(self);
        self.prefix = prior;
    }
}

impl<'ast> Visit<'ast> for Collector<'_> {
    fn visit_item_mod(&mut self, node: &'ast syn::ItemMod) {
        if is_test_mod(node) && !self.test_mode {
            let mut module = ModuleCount {
                include_tests: true,
                ..ModuleCount::default()
            };
            module.visit_item_mod(node);
            let mut entry = unit(
                self.path,
                format!("{}{}", self.prefix, node.ident),
                "module",
                "module_statements",
                module.statements,
            );
            entry.tier = Some("test");
            self.units.push(entry);
            self.test_mode = true;
            self.nested(&node.ident.to_string(), |this| {
                visit::visit_item_mod(this, node)
            });
            self.test_mode = false;
            return;
        }
        self.nested(&node.ident.to_string(), |this| {
            visit::visit_item_mod(this, node)
        });
    }

    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        let name = node.sig.ident.to_string();
        self.function(&name, &node.block);
        self.nested(&name, |this| visit::visit_item_fn(this, node));
    }

    fn visit_item_impl(&mut self, node: &'ast syn::ItemImpl) {
        let type_name = match &*node.self_ty {
            syn::Type::Path(path) => path.path.segments.last().map(|seg| seg.ident.to_string()),
            _ => None,
        }
        .unwrap_or_else(|| "<impl>".to_owned());
        let qual = format!("{}{}", self.prefix, type_name);
        *self.methods.entry((qual, self.test_mode)).or_default() += node
            .items
            .iter()
            .filter(|item| matches!(item, syn::ImplItem::Fn(_)))
            .count();
        self.nested(&type_name, |this| visit::visit_item_impl(this, node));
    }

    fn visit_impl_item_fn(&mut self, node: &'ast syn::ImplItemFn) {
        let name = node.sig.ident.to_string();
        self.function(&name, &node.block);
        self.nested(&name, |this| visit::visit_impl_item_fn(this, node));
    }

    fn visit_item_trait(&mut self, node: &'ast syn::ItemTrait) {
        let name = node.ident.to_string();
        let qual = format!("{}{}", self.prefix, name);
        *self.methods.entry((qual, self.test_mode)).or_default() += node
            .items
            .iter()
            .filter(|item| matches!(item, syn::TraitItem::Fn(_)))
            .count();
        self.nested(&name, |this| visit::visit_item_trait(this, node));
    }

    fn visit_trait_item_fn(&mut self, node: &'ast syn::TraitItemFn) {
        let name = node.sig.ident.to_string();
        if let Some(block) = &node.default {
            self.function(&name, block);
        }
        self.nested(&name, |this| visit::visit_trait_item_fn(this, node));
    }
}

fn measure_source(path: &str, source: &str) -> Result<Vec<Unit>, String> {
    let syntax =
        syn::parse_file(source).map_err(|error| format!("{path}: parse failed: {error}"))?;
    let mut module = ModuleCount::default();
    module.visit_file(&syntax);
    let mut collector = Collector {
        path,
        prefix: String::new(),
        units: vec![unit(
            path,
            String::new(),
            "module",
            "module_statements",
            module.statements,
        )],
        methods: BTreeMap::new(),
        test_mode: false,
    };
    collector.visit_file(&syntax);
    for ((qual, test_mode), count) in collector.methods {
        let mut entry = unit(path, qual, "class", "class_methods", count);
        if test_mode {
            entry.tier = Some("test");
        }
        collector.units.push(entry);
    }
    Ok(collector.units)
}

fn measure(root: &Path, path: &str) -> Result<Vec<Unit>, String> {
    let source = std::fs::read_to_string(root.join(path))
        .map_err(|error| format!("{path}: read failed: {error}"))?;
    measure_source(path, &source)
}

fn run() -> Result<(), String> {
    let mut input = String::new();
    std::io::stdin()
        .read_to_string(&mut input)
        .map_err(|error| error.to_string())?;
    let request: Request = serde_json::from_str(&input).map_err(|error| error.to_string())?;
    let root = Path::new(&request.root);
    let mut units = Vec::new();
    for path in &request.files {
        if !path.starts_with("crates/") || !path.ends_with(".rs") || path.contains("..") {
            return Err(format!("invalid Rust source path: {path}"));
        }
        units.extend(measure(root, path)?);
    }
    println!(
        "{}",
        serde_json::to_string(&units).map_err(|error| error.to_string())?
    );
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("Rust complexity measurement failed: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::measure_source;

    #[test]
    fn measures_rust_syntax_and_separates_inline_test_bodies() {
        let source = r#"
            fn f(x: bool) -> i32 {
                let y = 0;
                if x && true { return 1; }
                match y { 0 => 2, _ => 3 }
            }
            struct Boxed;
            impl Boxed {
                fn pick(&self) -> bool {
                    let Some(x) = Some(1) else { return false; };
                    x > 0
                }
            }
            #[cfg(test)] mod tests {
                fn huge() { if true { if true { if true {} } } }
            }
        "#;
        let units = measure_source("crates/example/src/lib.rs", source).unwrap();
        let lookup = |qual: &str, metric: &str| {
            units
                .iter()
                .find(|unit| unit.qual == qual)
                .and_then(|unit| unit.metrics.get(metric))
                .copied()
        };
        assert_eq!(lookup("f", "function_complexity"), Some(4));
        assert_eq!(lookup("f", "function_statements"), Some(4));
        assert_eq!(lookup("Boxed.pick", "function_complexity"), Some(2));
        assert_eq!(lookup("Boxed", "class_methods"), Some(1));
        assert_eq!(lookup("", "module_statements"), Some(11));
        let inline = units.iter().find(|unit| unit.qual == "tests.huge").unwrap();
        assert_eq!(inline.tier, Some("test"));
        assert_eq!(inline.metrics["function_complexity"], 4);
        assert_eq!(
            units.iter().find(|unit| unit.qual == "tests").unwrap().tier,
            Some("test")
        );
    }

    #[test]
    fn nested_names_and_macro_control_flow_are_measured() {
        assert!(measure_source("crates/example/src/lib.rs", "fn (").is_err());
        let source = r#"
            fn outer_a() {
                fn inner() {}
                let _ = serde_json::json!({"value": if true && false { 1 } else { 2 }});
            }
            fn outer_b() {
                fn inner() { if true {} }
            }
        "#;
        let units = measure_source("crates/example/src/lib.rs", source).unwrap();
        assert!(units.iter().any(|unit| unit.qual == "outer_a.inner"));
        assert!(units.iter().any(|unit| unit.qual == "outer_b.inner"));
        let outer = units.iter().find(|unit| unit.qual == "outer_a").unwrap();
        assert_eq!(outer.metrics["function_complexity"], 3);
        assert_eq!(outer.metrics["function_statements"], 3);
        let nested = units
            .iter()
            .find(|unit| unit.qual == "outer_b.inner")
            .unwrap();
        assert_eq!(nested.metrics["function_complexity"], 2);
    }
}
