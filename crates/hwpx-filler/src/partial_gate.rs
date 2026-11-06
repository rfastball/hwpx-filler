//! Explicit acknowledgement of leftover values never clears unfinished structure.

use crate::authoring::scan_tokens;
use crate::home_state::CompileState;
use crate::schema::TemplateSchema;
use crate::template_library_state::TemplateStatus;
use hwpx_core::package::HwpxPackage;
use serde_json::{Value, json};
use std::collections::HashSet;

#[derive(Clone, Debug)]
pub struct PartialGate {
    pub status: TemplateStatus,
    pub unmet_tokens: Vec<String>,
    acknowledged: HashSet<String>,
}

impl PartialGate {
    pub fn inspect(package: &HwpxPackage, schema: &TemplateSchema) -> Result<Self, String> {
        let status = TemplateStatus::inspect(package)?;
        if !matches!(status.state, CompileState::Partial { .. }) {
            return Ok(Self {
                status,
                unmet_tokens: Vec::new(),
                acknowledged: HashSet::new(),
            });
        }
        let sites = scan_tokens(package).map_err(|error| error.to_string())?;
        let mut seen = HashSet::new();
        let unmet_tokens = sites
            .iter()
            .map(|site| {
                if site.name.is_empty() {
                    "(이름 없는 토큰)"
                } else {
                    &site.name
                }
            })
            .chain(schema.stray_tokens.iter().map(String::as_str))
            .filter(|name| !name.is_empty() && seen.insert((*name).to_owned()))
            .map(str::to_owned)
            .collect();
        Ok(Self {
            status,
            unmet_tokens,
            acknowledged: HashSet::new(),
        })
    }

    pub fn needs_gate(&self) -> bool {
        matches!(self.status.state, CompileState::Partial { .. })
    }

    pub fn acknowledge(&mut self, confirmed: &[String]) {
        self.acknowledged = confirmed.iter().cloned().collect();
    }

    pub fn is_acked(&self) -> bool {
        !self.unmet_tokens.is_empty()
            && self.acknowledged == self.unmet_tokens.iter().cloned().collect()
    }

    pub fn can_proceed(&self) -> bool {
        !matches!(self.status.state, CompileState::Raw)
            && self.status.structure_marker_n == 0
            && (!self.needs_gate() || self.is_acked())
    }

    pub fn snapshot(&self) -> Value {
        let acked = self.is_acked();
        let names = self.unmet_tokens.join(", ");
        let message = if self.status.structure_marker_n > 0 {
            "미변환 구간 표기가 남아 있어 진행할 수 없습니다. 누름틀 변환으로 구조를 먼저 완성하세요.".into()
        } else if acked {
            format!(
                "확인함: 아래 {}개 토큰은 비우고 진행합니다({names})",
                self.unmet_tokens.len()
            )
        } else {
            format!(
                "진행 차단: 값이 채워지지 않는 토큰 {}개가 남아 있습니다({names}). [여기서 누름틀 변환]으로 누름틀로 바꾸거나, 비움을 확정하세요.",
                self.unmet_tokens.len()
            )
        };
        json!({"message":message,"unmet":self.unmet_tokens,"acked":acked})
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::authoring::compile_document;
    use crate::schema::extract_schema;
    use hwpx_core::package::PackageEntry;

    fn package(body: &str) -> HwpxPackage {
        HwpxPackage { entries: vec![PackageEntry {
            name: "Contents/section0.xml".into(), stored: false,
            data: format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{}'>{body}</hs:sec>", hwpx_core::text_model::HP_NS).into_bytes(),
        }] }
    }

    fn gate(package: &HwpxPackage) -> PartialGate {
        PartialGate::inspect(package, &extract_schema(package).unwrap()).unwrap()
    }

    fn append(package: &mut HwpxPackage, text: &str) {
        let xml = String::from_utf8(package.entries[0].data.clone()).unwrap();
        package.entries[0].data = xml
            .replace(
                "</hs:sec>",
                &format!("<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p></hs:sec>"),
            )
            .into_bytes();
    }

    #[test]
    fn acknowledgement_requires_the_current_complete_nonempty_name_set() {
        let mut gate = PartialGate {
            status: TemplateStatus {
                state: CompileState::Partial { remaining: 2 },
                field_n: 1,
                compilable_n: 2,
                skipped_n: 0,
                stray_n: 0,
                structure_marker_n: 0,
            },
            unmet_tokens: vec!["계약명".into(), "미결".into()],
            acknowledged: HashSet::new(),
        };
        for names in [vec![], vec!["계약명"], vec!["엉뚱한이름", "계약명"]] {
            gate.acknowledge(&names.into_iter().map(str::to_owned).collect::<Vec<_>>());
            assert!(!gate.can_proceed() && !gate.is_acked());
        }
        gate.acknowledge(&["미결".into(), "계약명".into(), "계약명".into()]);
        assert!(gate.can_proceed());
        assert_eq!(
            gate.snapshot(),
            json!({"message":"확인함: 아래 2개 토큰은 비우고 진행합니다(계약명, 미결)", "unmet":["계약명","미결"], "acked":true})
        );
        gate.unmet_tokens.push("새 토큰".into());
        assert!(!gate.can_proceed() && !gate.is_acked());
        gate.unmet_tokens.clear();
        gate.acknowledge(&[]);
        assert!(!gate.can_proceed());
        gate.status.state = CompileState::Raw;
        assert!(!gate.can_proceed());
        gate.status.state = CompileState::Compiled;
        assert!(gate.can_proceed() && !gate.needs_gate());
    }

    #[test]
    fn package_gate_separates_compilable_stray_and_structural_leftovers() {
        let raw = package("<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>");
        assert!(!gate(&raw).can_proceed());
        let mut compiled = raw.clone();
        compile_document(&mut compiled, None).unwrap();
        assert!(gate(&compiled).can_proceed() && !gate(&compiled).needs_gate());
        for (text, name) in [
            ("{{미컴파일필드}}", "미컴파일필드"),
            ("{{   }}", "(이름 없는 토큰)"),
        ] {
            let mut partial = compiled.clone();
            append(&mut partial, text);
            let before = partial.clone();
            let mut observed = gate(&partial);
            assert_eq!(partial, before);
            assert!(observed.needs_gate() && !observed.can_proceed());
            assert_eq!(observed.unmet_tokens, [name]);
            assert!(
                observed.snapshot()["message"]
                    .as_str()
                    .unwrap()
                    .contains(name)
            );
            observed.acknowledge(&observed.unmet_tokens.clone());
            assert!(observed.can_proceed());
            if name == "미컴파일필드" {
                assert!(compile_document(&mut partial, None).unwrap().modified);
                let repaired = gate(&partial);
                assert!(repaired.can_proceed() && !repaired.needs_gate());
                assert_eq!(repaired.status.compilable_n, 0);
            }
        }
        for value in ["정보시스템 구축", "{{미결}}"] {
            let populated = package(&format!(
                r#"<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="계약명"/></hp:ctrl></hp:run><hp:run><hp:t>{value}</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>"#
            ));
            let mut observed = gate(&populated);
            if value == "{{미결}}" {
                assert!(!observed.can_proceed());
                assert_eq!(observed.unmet_tokens, ["미결"]);
                observed.acknowledge(&observed.unmet_tokens.clone());
            }
            assert!(observed.can_proceed());
        }
        for token in ["", "{{미컴파일필드}}"] {
            let mut structural = compiled.clone();
            append(&mut structural, "{{#항목 특약}}");
            append(&mut structural, token);
            append(&mut structural, "{{/항목}}");
            let mut observed = gate(&structural);
            assert!(observed.needs_gate() && observed.status.structure_marker_n > 0);
            assert_eq!(observed.unmet_tokens.len(), usize::from(!token.is_empty()));
            observed.acknowledge(&observed.unmet_tokens.clone());
            assert_eq!(observed.is_acked(), !token.is_empty());
            assert!(!observed.can_proceed());
            assert_eq!(
                observed.snapshot()["message"],
                "미변환 구간 표기가 남아 있어 진행할 수 없습니다. 누름틀 변환으로 구조를 먼저 완성하세요."
            );
        }
    }
}
