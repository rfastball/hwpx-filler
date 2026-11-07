//! Extract production Rust string literals for the UI copy census.
//! Input: {"root":"...","files":["crates/.../src/lib.rs"]} on stdin.

use std::io::Read;
use std::path::Path;

use proc_macro2::{TokenStream, TokenTree};
use serde::{Deserialize, Serialize};
use syn::visit::{self, Visit};
use syn::{Attribute, ItemFn, ItemMod, LitStr, Macro, Meta};

#[derive(Deserialize)]
struct Request {
    root: String,
    files: Vec<String>,
}

#[derive(Serialize)]
struct Literal {
    file: String,
    text: String,
}

struct Collector<'a> {
    file: &'a str,
    values: Vec<Literal>,
}

impl Collector<'_> {
    fn record(&mut self, value: &LitStr, is_format: bool) {
        self.values.push(Literal {
            file: self.file.to_owned(),
            text: if is_format {
                normalize_format(&value.value())
            } else {
                value.value()
            },
        });
    }

    fn macro_literals(&mut self, stream: TokenStream, first_is_format: bool) {
        let tokens: Vec<_> = stream.into_iter().collect();
        let mut index = 0;
        while index < tokens.len() {
            if let Some(group) = nested_format(&tokens[index..]) {
                self.macro_literals(group.stream(), true);
                index += 3;
                continue;
            }
            match &tokens[index] {
                TokenTree::Literal(literal) => {
                    if let Ok(value) = syn::parse_str::<LitStr>(&literal.to_string()) {
                        self.record(&value, first_is_format && index == 0);
                    }
                }
                TokenTree::Group(group) => self.macro_literals(group.stream(), false),
                TokenTree::Ident(_) | TokenTree::Punct(_) => {}
            }
            index += 1;
        }
    }
}

fn nested_format(tokens: &[TokenTree]) -> Option<&proc_macro2::Group> {
    let [
        TokenTree::Ident(name),
        TokenTree::Punct(bang),
        TokenTree::Group(group),
        ..,
    ] = tokens
    else {
        return None;
    };
    (format_macro(&name.to_string()) && bang.as_char() == '!').then_some(group)
}

fn format_macro(name: &str) -> bool {
    matches!(
        name,
        "format" | "format_args" | "print" | "println" | "eprint" | "eprintln" | "panic"
    )
}

fn test_only(attrs: &[Attribute]) -> bool {
    attrs.iter().any(|attr| {
        attr.path()
            .segments
            .last()
            .is_some_and(|segment| segment.ident == "test")
            || (attr.path().is_ident("cfg")
                && matches!(&attr.meta, Meta::List(list) if list.tokens.to_string() == "test"))
    })
}

fn normalize_format(source: &str) -> String {
    let mut chars = source.chars().peekable();
    let mut result = String::new();
    while let Some(ch) = chars.next() {
        match (ch, chars.peek()) {
            ('{', Some('{')) => {
                chars.next();
                result.push('{');
            }
            ('}', Some('}')) => {
                chars.next();
                result.push('}');
            }
            ('{', _) => {
                let mut depth = 1;
                for part in chars.by_ref() {
                    if part == '{' {
                        depth += 1;
                    } else if part == '}' {
                        depth -= 1;
                        if depth == 0 {
                            break;
                        }
                    }
                }
                result.push_str("{}");
            }
            _ => result.push(ch),
        }
    }
    result
}

impl<'ast> Visit<'ast> for Collector<'_> {
    fn visit_attribute(&mut self, node: &'ast Attribute) {
        if !node.path().is_ident("doc") {
            visit::visit_attribute(self, node);
        }
    }

    fn visit_item_mod(&mut self, node: &'ast ItemMod) {
        if !test_only(&node.attrs) {
            visit::visit_item_mod(self, node);
        }
    }

    fn visit_item_fn(&mut self, node: &'ast ItemFn) {
        if !test_only(&node.attrs) {
            visit::visit_item_fn(self, node);
        }
    }

    fn visit_lit_str(&mut self, node: &'ast LitStr) {
        self.record(node, false);
    }

    fn visit_macro(&mut self, node: &'ast Macro) {
        let format = node
            .path
            .segments
            .last()
            .is_some_and(|segment| format_macro(&segment.ident.to_string()));
        self.macro_literals(node.tokens.clone(), format);
    }
}

#[cfg(test)]
mod tests {
    use super::{Collector, normalize_format};
    use syn::visit::Visit;

    #[test]
    fn format_placeholders_match_legacy_census_without_changing_literal_braces() {
        assert_eq!(
            normalize_format("저장 {error} / {value:?} / {{필드}}"),
            "저장 {} / {} / {필드}"
        );
        let source = syn::parse_file(
            r#"
            /// 문서 주석입니다.
            const COPY: &str = "리터럴 {name}입니다.";
            fn message() { json!({"message": Some(format!("구조 오류 {errors}개입니다.")),
                "body": format_args!("{{필드}} {}입니다.", "값")}); }
            #[cfg(test)] mod tests { const FIXTURE: &str = "검사 전용입니다."; }
            #[cfg(test)] fn fixture() { println!("검사 전용입니다."); }
            #[test] fn inline_test() { println!("검사 전용입니다."); }
            fn report() { eprintln!("저장 실패: {error:?}입니다.");
                println!("{{필드}} {name}입니다.");
                json!({"value": std::format!("상태 {state}입니다.")}); }
        "#,
        )
        .unwrap();
        let mut collector = Collector {
            file: "copy.rs",
            values: Vec::new(),
        };
        collector.visit_file(&source);
        assert_eq!(
            collector
                .values
                .iter()
                .map(|row| row.text.as_str())
                .collect::<Vec<_>>(),
            [
                "리터럴 {name}입니다.",
                "message",
                "구조 오류 {}개입니다.",
                "body",
                "{필드} {}입니다.",
                "값",
                "저장 실패: {}입니다.",
                "{필드} {}입니다.",
                "value",
                "상태 {}입니다."
            ]
        );
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input)?;
    let request: Request = serde_json::from_str(&input)?;
    let mut rows = Vec::new();
    for file in request.files {
        let source = std::fs::read_to_string(Path::new(&request.root).join(&file))?;
        let parsed = syn::parse_file(&source)?;
        let mut collector = Collector {
            file: &file,
            values: Vec::new(),
        };
        collector.visit_file(&parsed);
        rows.extend(collector.values);
    }
    println!("{}", serde_json::to_string(&rows)?);
    Ok(())
}
