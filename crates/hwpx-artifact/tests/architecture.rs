//! Repository boundaries that survive the Python implementation's retirement.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use syn::visit::{self, Visit};
use syn::{Attribute, GenericArgument, ItemMod, ItemUse, Meta, PathArguments, Type, UseTree};

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn is_test(attrs: &[Attribute]) -> bool {
    attrs.iter().any(|attr| {
        attr.path().is_ident("cfg")
            && matches!(&attr.meta, Meta::List(list) if list.tokens.to_string() == "test")
    })
}

fn use_bindings(
    tree: &UseTree,
    prefix: &str,
    aliases: &mut BTreeMap<String, String>,
    imported: &mut Vec<String>,
) {
    match tree {
        UseTree::Path(part) => use_bindings(
            &part.tree,
            &format!("{prefix}{}::", part.ident),
            aliases,
            imported,
        ),
        UseTree::Name(part) => {
            let name = part.ident.to_string();
            if name == "self" {
                let full = prefix.trim_end_matches("::").to_owned();
                if let Some(binding) = full.rsplit("::").next() {
                    aliases.insert(binding.to_owned(), full.clone());
                }
                imported.push(full);
            } else {
                let full = format!("{prefix}{name}");
                aliases.insert(name, full.clone());
                imported.push(full);
            }
        }
        UseTree::Rename(part) => {
            let full = format!("{prefix}{}", part.ident);
            aliases.insert(part.rename.to_string(), full.clone());
            imported.push(full);
        }
        UseTree::Group(group) => {
            for item in &group.items {
                use_bindings(item, prefix, aliases, imported);
            }
        }
        UseTree::Glob(_) => {
            let full = prefix.trim_end_matches("::").to_owned();
            aliases.insert(format!("{prefix}*"), full.clone());
            imported.push(full);
        }
    }
}

#[derive(Default)]
struct Imports {
    aliases: BTreeMap<String, String>,
    imported: Vec<String>,
}

impl<'ast> Visit<'ast> for Imports {
    fn visit_item_mod(&mut self, node: &'ast ItemMod) {
        if !is_test(&node.attrs) {
            visit::visit_item_mod(self, node);
        }
    }

    fn visit_item_use(&mut self, node: &'ast ItemUse) {
        if !is_test(&node.attrs) {
            use_bindings(&node.tree, "", &mut self.aliases, &mut self.imported);
        }
    }

    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        if !is_test(&node.attrs) {
            visit::visit_item_fn(self, node);
        }
    }
}

fn forbidden(path: &str) -> bool {
    let mut parts = path.split("::");
    match parts.next() {
        Some("hwpx_filler" | "hwpx_desktop" | "hwpx_artifact" | "tauri" | "windows_sys") => true,
        Some("std") => match parts.next() {
            Some("fs" | "env" | "time" | "thread" | "process" | "net" | "path") => true,
            Some("io") => matches!(
                parts.next(),
                Some("stdin" | "stdout" | "stderr" | "Stdin" | "Stdout" | "Stderr")
            ),
            Some("print" | "println" | "eprint" | "eprintln" | "dbg") => true,
            _ => false,
        },
        _ => false,
    }
}

struct CorePaths<'a> {
    aliases: &'a BTreeMap<String, String>,
    violations: Vec<String>,
}

impl<'ast> Visit<'ast> for CorePaths<'_> {
    fn visit_item_mod(&mut self, node: &'ast ItemMod) {
        if !is_test(&node.attrs) {
            visit::visit_item_mod(self, node);
        }
    }

    fn visit_path(&mut self, node: &'ast syn::Path) {
        let names = node
            .segments
            .iter()
            .map(|segment| segment.ident.to_string())
            .collect::<Vec<_>>();
        if let Some(first) = names.first() {
            let resolved = self
                .aliases
                .get(first)
                .cloned()
                .unwrap_or_else(|| first.clone());
            let full = std::iter::once(resolved)
                .chain(names.iter().skip(1).cloned())
                .collect::<Vec<_>>()
                .join("::");
            if forbidden(&full) {
                self.violations.push(full);
            }
        }
        visit::visit_path(self, node);
    }

    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        if !is_test(&node.attrs) {
            visit::visit_item_fn(self, node);
        }
    }

    fn visit_item_extern_crate(&mut self, node: &'ast syn::ItemExternCrate) {
        if forbidden(&node.ident.to_string()) {
            self.violations.push(node.ident.to_string());
        }
    }

    fn visit_macro(&mut self, node: &'ast syn::Macro) {
        if let Some(name) = node.path.segments.last().map(|part| part.ident.to_string())
            && matches!(
                name.as_str(),
                "print" | "println" | "eprint" | "eprintln" | "dbg"
            )
        {
            self.violations.push(format!("{name}!"));
        }
        visit::visit_macro(self, node);
    }
}

fn core_violations(source: &str) -> Vec<String> {
    let syntax = syn::parse_file(source).expect("Rust source parses");
    let mut imports = Imports::default();
    imports.visit_file(&syntax);
    let mut paths = CorePaths {
        aliases: &imports.aliases,
        violations: Vec::new(),
    };
    paths.visit_file(&syntax);
    for imported in &imports.imported {
        if forbidden(imported) {
            paths.violations.push(imported.clone());
        }
    }
    paths.violations.sort();
    paths.violations.dedup();
    paths.violations
}

#[test]
fn core_source_has_no_product_dependency_or_environment_effect() {
    let directory = root().join("crates/hwpx-core/src");
    let mut pending = vec![directory];
    let mut violations = Vec::new();
    while let Some(dir) = pending.pop() {
        for entry in std::fs::read_dir(dir).expect("core source directory") {
            let path = entry.expect("directory entry").path();
            if path.is_dir() {
                pending.push(path);
            } else if path.extension().is_some_and(|extension| extension == "rs") {
                let source = std::fs::read_to_string(&path).expect("core source");
                for edge in core_violations(&source) {
                    violations.push(format!("{}: {edge}", path.display()));
                }
            }
        }
    }
    assert!(violations.is_empty(), "{}", violations.join("\n"));
}

#[test]
fn aliases_nested_imports_and_test_code_are_distinguished() {
    let source = r#"
        use std::{fs as files, collections::HashMap};
        use hwpx_filler::job as product;
        fn read() { files::read("x"); product::run(); let _ = HashMap::<u8, u8>::new(); }
        #[cfg(test)] mod tests { use std::fs; fn read() { fs::read("x"); } }
    "#;
    assert_eq!(
        core_violations(source),
        [
            "hwpx_filler::job",
            "hwpx_filler::job::run",
            "std::fs",
            "std::fs::read"
        ]
    );
    assert!(
        core_violations("#[cfg(test)] mod tests { use std::fs; fn read() { fs::read(\"x\"); } }")
            .is_empty()
    );
    assert_eq!(
        core_violations(
            "use std::io::{Cursor, stdin as input}; fn read() { input(); let _ = Cursor::new([]); }"
        ),
        ["std::io::stdin"]
    );
    assert_eq!(
        core_violations("fn render() { println!(\"x\"); dbg!(1); let _ = format!(\"{}\", 1); }"),
        ["dbg!", "println!"]
    );
}

fn dependency_names(manifest: &toml::Value, names: &mut Vec<String>) {
    let Some(table) = manifest.as_table() else {
        return;
    };
    for (key, value) in table {
        if matches!(
            key.as_str(),
            "dependencies" | "dev-dependencies" | "build-dependencies"
        ) {
            if let Some(dependencies) = value.as_table() {
                for (alias, specification) in dependencies {
                    names.push(
                        specification
                            .get("package")
                            .and_then(toml::Value::as_str)
                            .unwrap_or(alias)
                            .to_owned(),
                    );
                }
            }
        } else {
            dependency_names(value, names);
        }
    }
}

#[test]
fn cargo_dependencies_point_inward() {
    // 퇴역한 module ring 지도의 「안쪽은 host(창·OS 셸)를 모른다」를 crate 의존으로 잇는다.
    const HOST: [&str; 6] = [
        "tauri",
        "tauri-build",
        "wry",
        "webview2-com",
        "windows",
        "windows-sys",
    ];
    let core_forbidden = [
        &["hwpx-filler", "hwpx-desktop", "hwpx-artifact"][..],
        &HOST[..],
    ]
    .concat();
    let filler_forbidden = [&["hwpx-desktop", "hwpx-artifact"][..], &HOST[..]].concat();
    for (source, forbidden) in [
        ("hwpx-core", core_forbidden.as_slice()),
        ("hwpx-filler", filler_forbidden.as_slice()),
    ] {
        let file = root().join(format!("crates/{source}/Cargo.toml"));
        let document: toml::Value =
            toml::from_str(&std::fs::read_to_string(file).expect("crate manifest"))
                .expect("valid crate manifest");
        let mut dependencies = Vec::new();
        dependency_names(&document, &mut dependencies);
        for blocked in forbidden {
            assert!(
                !dependencies.iter().any(|name| name == blocked),
                "{source} -> {blocked}"
            );
        }
    }
}

fn rust_sources(directory: &Path) -> Vec<PathBuf> {
    let mut pending = vec![directory.to_path_buf()];
    let mut sources = Vec::new();
    while let Some(dir) = pending.pop() {
        for entry in std::fs::read_dir(dir).expect("Rust source directory") {
            let path = entry.expect("Rust source entry").path();
            if path.is_dir() {
                pending.push(path);
            } else if path.extension().is_some_and(|extension| extension == "rs") {
                sources.push(path);
            }
        }
    }
    sources.sort();
    sources
}

struct ProfileUses<'a> {
    aliases: &'a BTreeMap<String, String>,
    sites: Vec<&'static str>,
}

impl<'ast> Visit<'ast> for ProfileUses<'_> {
    fn visit_item_mod(&mut self, node: &'ast ItemMod) {
        if !is_test(&node.attrs) {
            visit::visit_item_mod(self, node);
        }
    }

    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        if !is_test(&node.attrs) {
            visit::visit_item_fn(self, node);
        }
    }

    fn visit_expr_call(&mut self, node: &'ast syn::ExprCall) {
        if let syn::Expr::Path(function) = node.func.as_ref() {
            let head = function.path.segments.first().unwrap().ident.to_string();
            let resolved = self.aliases.get(&head).map(String::as_str).unwrap_or(&head);
            if resolved.rsplit("::").next() == Some("build_manifest")
                || function.path.segments.last().unwrap().ident == "build_manifest"
            {
                self.sites.push("build_manifest");
            }
        }
        visit::visit_expr_call(self, node);
    }

    fn visit_expr_struct(&mut self, node: &'ast syn::ExprStruct) {
        match node
            .path
            .segments
            .last()
            .unwrap()
            .ident
            .to_string()
            .as_str()
        {
            "ManifestInput" => self.sites.push("ManifestInput"),
            "QualificationProfileManifest" => self.sites.push("QualificationProfileManifest"),
            _ => {}
        }
        visit::visit_expr_struct(self, node);
    }
}

fn profile_uses(source: &str) -> Vec<&'static str> {
    let syntax = syn::parse_file(source).expect("Rust source parses");
    let mut imports = Imports::default();
    imports.visit_file(&syntax);
    let mut uses = ProfileUses {
        aliases: &imports.aliases,
        sites: Vec::new(),
    };
    uses.visit_file(&syntax);
    uses.sites.sort();
    uses.sites
}

#[test]
fn shipping_profiles_have_only_the_two_media_construction_sites() {
    let mut actual = Vec::new();
    for package in ["hwpx-filler", "hwpx-desktop"] {
        for path in rust_sources(&root().join(format!("crates/{package}/src"))) {
            let relative = path
                .strip_prefix(root())
                .unwrap()
                .to_string_lossy()
                .replace('\\', "/");
            for site in profile_uses(&std::fs::read_to_string(path).unwrap()) {
                actual.push(format!("{relative}:{site}"));
            }
        }
    }
    actual.sort();
    let mut expected = [
        "crates/hwpx-filler/src/execution_structure.rs:QualificationProfileManifest",
        "crates/hwpx-filler/src/qualification_evidence.rs:QualificationProfileManifest",
        "crates/hwpx-filler/src/qualification_evidence.rs:QualificationProfileManifest",
        "crates/hwpx-filler/src/template_qualification.rs:ManifestInput",
        "crates/hwpx-filler/src/template_qualification.rs:build_manifest",
        "crates/hwpx-filler/src/text_template_inspection.rs:ManifestInput",
        "crates/hwpx-filler/src/text_template_inspection.rs:build_manifest",
    ]
    .map(str::to_owned)
    .to_vec();
    expected.sort();
    assert_eq!(
        actual, expected,
        "shipping Qualification Profile construction changed"
    );
    assert_eq!(
        profile_uses(
            "use crate::qualification_evidence::build_manifest as hidden; fn extra() { hidden(input); }"
        ),
        ["build_manifest"],
        "an aliased new constructor must be caught"
    );
    assert_eq!(
        profile_uses("fn extra() { let _ = QualificationProfileManifest { id: 1 }; }"),
        ["QualificationProfileManifest"]
    );
}

fn durable_vec_fields(source: &str, name: &str) -> Vec<String> {
    let syntax = syn::parse_file(source).expect("durable aggregate source parses");
    let aggregate = syntax
        .items
        .iter()
        .find_map(|item| match item {
            syn::Item::Struct(value) if value.ident == name => Some(value),
            _ => None,
        })
        .expect("named durable aggregate exists");
    let mut found = Vec::new();
    for field in aggregate.fields.iter() {
        let Type::Path(ty) = &field.ty else { continue };
        let Some(vector) = ty.path.segments.last() else {
            continue;
        };
        if vector.ident != "Vec" {
            continue;
        }
        let PathArguments::AngleBracketed(args) = &vector.arguments else {
            continue;
        };
        let Some(GenericArgument::Type(Type::Path(element))) = args.args.first() else {
            continue;
        };
        found.push(format!(
            "{}:{}",
            field.ident.as_ref().unwrap(),
            element.path.segments.last().unwrap().ident
        ));
    }
    found.sort();
    found
}

#[test]
fn durable_aggregate_record_collections_are_an_exact_inventory() {
    for (file, aggregate, expected) in [
        (
            "stored_work_configuration.rs",
            "StoredWorkConfiguration",
            &["processed_requests:IdempotencyRecord"][..],
        ),
        (
            "work_slot_configuration.rs",
            "WorkSlotConfigurationAggregate",
            &["configurations:WorkSlotConfigurationDraft"][..],
        ),
        (
            "work_template_state.rs",
            "WorkTemplateStateAggregate",
            &[
                "applications:WorkTemplateApplication",
                "preparations:TemplateChangePreparation",
                "prepared_changes:PreparedTemplateChange",
            ][..],
        ),
    ] {
        let source =
            std::fs::read_to_string(root().join("crates/hwpx-filler/src").join(file)).unwrap();
        assert_eq!(
            durable_vec_fields(&source, aggregate),
            expected,
            "{file}:{aggregate}"
        );
    }
    let extra = "struct StoredWorkConfiguration { processed_requests: Vec<IdempotencyRecord>, hidden: Vec<NewRecord> }";
    assert_eq!(
        durable_vec_fields(extra, "StoredWorkConfiguration"),
        ["hidden:NewRecord", "processed_requests:IdempotencyRecord"]
    );
}

struct PortUses<'a> {
    aliases: &'a BTreeMap<String, String>,
    symbols: &'a [&'a str],
    found: BTreeSet<String>,
}

impl PortUses<'_> {
    fn record(&mut self, name: &str) {
        if self.symbols.contains(&name) {
            self.found.insert(name.to_owned());
        }
    }
}

impl<'ast> Visit<'ast> for PortUses<'_> {
    fn visit_item_mod(&mut self, node: &'ast ItemMod) {
        if !is_test(&node.attrs) {
            visit::visit_item_mod(self, node);
        }
    }

    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        if !is_test(&node.attrs) {
            self.record(&node.sig.ident.to_string());
            visit::visit_item_fn(self, node);
        }
    }

    fn visit_path(&mut self, node: &'ast syn::Path) {
        let head = node.segments.first().unwrap().ident.to_string();
        let resolved = self.aliases.get(&head).map(String::as_str).unwrap_or(&head);
        let name = if node.segments.len() == 1 {
            resolved.rsplit("::").next().unwrap().to_owned()
        } else {
            node.segments.last().unwrap().ident.to_string()
        };
        self.record(&name);
        visit::visit_path(self, node);
    }

    fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
        self.record(&node.method.to_string());
        visit::visit_expr_method_call(self, node);
    }
}

fn guarded_port_uses(source: &str, symbols: &[&str]) -> BTreeSet<String> {
    let syntax = syn::parse_file(source).expect("Rust source parses");
    let mut imports = Imports::default();
    imports.visit_file(&syntax);
    let mut uses = PortUses {
        aliases: &imports.aliases,
        symbols,
        found: BTreeSet::new(),
    };
    for imported in &imports.imported {
        uses.record(imported.rsplit("::").next().unwrap());
    }
    uses.visit_file(&syntax);
    uses.found
}

fn port_owners(symbols: &[&str]) -> BTreeSet<String> {
    let mut found = BTreeSet::new();
    for package in ["hwpx-filler", "hwpx-desktop"] {
        for path in rust_sources(&root().join(format!("crates/{package}/src"))) {
            let source = std::fs::read_to_string(&path).unwrap();
            if !guarded_port_uses(&source, symbols).is_empty() {
                found.insert(
                    path.strip_prefix(root())
                        .unwrap()
                        .to_string_lossy()
                        .replace('\\', "/"),
                );
            }
        }
    }
    found
}

#[test]
fn materialization_and_txt_render_ports_have_exact_production_owners() {
    let materialization = [
        "apply_execution_plan_in_memory",
        "verify_structure_bytes_consistency",
        "verify_materialization_postconditions",
        "apply_txt_execution_plan_in_memory",
        "verify_txt_structure_bytes_consistency",
        "verify_txt_materialization_postconditions",
    ];
    assert_eq!(
        port_owners(&materialization),
        BTreeSet::from([
            "crates/hwpx-filler/src/materialization_conformance.rs".into(),
            "crates/hwpx-filler/src/materialization_runner.rs".into(),
            "crates/hwpx-filler/src/text_authoring_trial.rs".into(),
            "crates/hwpx-filler/src/text_materialization_conformance.rs".into(),
        ])
    );
    let rendering = [
        "render_segments",
        "render_record",
        "render_card",
        "card_text",
        "align_segments",
    ];
    assert_eq!(
        port_owners(&rendering),
        BTreeSet::from([
            "crates/hwpx-desktop/src/bin/hwpxfiller.rs".into(),
            "crates/hwpx-desktop/src/editor_intake.rs".into(),
            "crates/hwpx-desktop/src/workbench_controller.rs".into(),
            "crates/hwpx-filler/src/text_authoring_trial.rs".into(),
            "crates/hwpx-filler/src/text_materialization_conformance.rs".into(),
            "crates/hwpx-filler/src/text_render.rs".into(),
            "crates/hwpx-filler/src/txt_card.rs".into(),
            "crates/hwpx-filler/src/txt_card_edit.rs".into(),
        ])
    );
    assert_eq!(
        guarded_port_uses(
            "use crate::materialization_conformance::apply_execution_plan_in_memory as hidden; fn escape() { hidden(); }",
            &materialization,
        ),
        BTreeSet::from(["apply_execution_plan_in_memory".into()])
    );
    assert_eq!(
        guarded_port_uses(
            "fn escape() { crate::text_render::render_record(); }",
            &rendering,
        ),
        BTreeSet::from(["render_record".into()])
    );
}
