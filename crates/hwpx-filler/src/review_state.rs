//! Nonblocking result-review facts for one Job and the selected blank field set.

use crate::job::{Job, rules_fingerprints, sorted_json};
use crate::output_name::pattern_field_tokens;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::collections::HashSet;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReviewRequirement {
    pub risk_class: &'static str,
    pub changed_targets: Vec<String>,
    pub changed_fields: Vec<String>,
    pub evidence_policy: &'static str,
    pub first_run: bool,
    pub unknown_baseline: bool,
    pub structure_changed: bool,
    pub rules_key: String,
    pub selection_bound: bool,
}
impl ReviewRequirement {
    pub fn required(&self) -> bool {
        !self.risk_class.is_empty()
    }
    pub fn payload(&self) -> Value {
        json!({
            "required": self.required(), "risk": self.risk_class,
            "targets": self.changed_targets, "first_run": self.first_run,
            "unknown_baseline": self.unknown_baseline,
            "structure_changed": self.structure_changed,
        })
    }
}

pub fn rules_key(fingerprints: &Map<String, Value>) -> String {
    let bytes = Sha256::digest(sorted_json(&Value::Object(fingerprints.clone())).as_bytes());
    bytes[..8]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn evidence_policy(risk: &str) -> &'static str {
    match risk {
        "filename_set" => "name_set_summary",
        "semantic_binding" => "value_scope_summary",
        "presentation" => "formatted_value",
        "blank_set" => "blank_scope_summary",
        _ => "",
    }
}
fn target_label(key: &str) -> String {
    if key == "template" {
        return "템플릿".into();
    }
    if key == "filename" {
        return "파일 이름 규칙".into();
    }
    let rest = key.strip_prefix("field:").unwrap_or(key);
    let (name, axis) = rest.rsplit_once(':').unwrap_or((rest, ""));
    let label = match axis {
        "source" => "연결",
        "format" => "표시형",
        other => other,
    };
    format!("{name}({label})")
}
fn changed_rule_keys(now: &Map<String, Value>, previous: &Map<String, Value>) -> Vec<String> {
    let mut seen = HashSet::new();
    now.keys()
        .chain(previous.keys())
        .filter(|key| now.get(*key) != previous.get(*key) && seen.insert((*key).clone()))
        .cloned()
        .collect()
}

fn rule_risk(changed: &[String], pattern: &str) -> &'static str {
    let name_fields = pattern_field_tokens(pattern)
        .into_iter()
        .collect::<HashSet<_>>();
    let touches_name = changed.iter().any(|key| {
        key.strip_prefix("field:")
            .and_then(|rest| rest.rsplit_once(':'))
            .is_some_and(|(field, _)| name_fields.contains(field))
    });
    if changed.iter().any(|key| key == "filename") || touches_name {
        "filename_set"
    } else if changed.iter().any(|key| key.ends_with(":source")) {
        "semantic_binding"
    } else if changed.iter().any(|key| key.ends_with(":format")) {
        "presentation"
    } else {
        ""
    }
}

fn changed_field_names(ordered: &[String]) -> Vec<String> {
    let mut fields = Vec::new();
    let mut seen = HashSet::new();
    for key in ordered {
        if let Some((field, _)) = key
            .strip_prefix("field:")
            .and_then(|rest| rest.rsplit_once(':'))
            && seen.insert(field)
        {
            fields.push(field.into());
        }
    }
    fields
}

pub fn review_requirement(job: &Job, blank_fields: &[String]) -> ReviewRequirement {
    let now = rules_fingerprints(job);
    let changed = changed_rule_keys(&now, &job.reviewed_rules);
    let risk = rule_risk(&changed, &job.filename_pattern);
    let mut requirement = ReviewRequirement {
        rules_key: rules_key(&now),
        structure_changed: changed.iter().any(|key| key == "template"),
        ..ReviewRequirement::default()
    };
    if risk.is_empty() {
        if !blank_fields.is_empty() {
            requirement.risk_class = "blank_set";
            requirement.changed_targets = blank_fields.to_vec();
            requirement.changed_fields = blank_fields.to_vec();
            requirement.evidence_policy = evidence_policy("blank_set");
            requirement.selection_bound = true;
        }
        return requirement;
    }
    requirement.risk_class = risk;
    requirement.changed_targets = changed.iter().map(|key| target_label(key)).collect();
    requirement.changed_fields = changed_field_names(&changed);
    requirement.evidence_policy = evidence_policy(risk);
    requirement.first_run = job.reviewed_rules.is_empty() && job.last_run_at.is_empty();
    requirement.unknown_baseline = job.reviewed_rules.is_empty() && !requirement.first_run;
    requirement.selection_bound = risk != "presentation" || !blank_fields.is_empty();
    requirement
}
pub fn review_notice_text(requirement: &ReviewRequirement) -> String {
    if !requirement.required() || requirement.first_run || requirement.risk_class == "blank_set" {
        return String::new();
    }
    if requirement.unknown_baseline {
        return "마지막 실행에 쓴 규칙을 확인할 수 없습니다. 결과 문서를 열어 확인하세요.".into();
    }
    format!(
        "마지막 실행 이후 바뀐 규칙이 있습니다: {}. 결과 문서를 열어 확인하세요.",
        requirement.changed_targets.join(", ")
    )
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::job::{decode_job, encode_job};
    use crate::mapping::{FieldMapping, MappingProfile};

    fn job() -> Job {
        Job {
            name: "공고".into(),
            template_path: "T.hwpx".into(),
            filename_pattern: "{{공고명}}.hwpx".into(),
            mapping: MappingProfile::new(
                "",
                vec![
                    FieldMapping::new("공고명", "bidNtceNm", "text", "", "", None).unwrap(),
                    FieldMapping::new("금액", "presmptPrce", "amount", "", "", None).unwrap(),
                ],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        }
    }

    #[test]
    fn review_baseline_keeps_target_order_risk_precedence_and_nonblocking_notices() {
        let mut base = job();
        let first = review_requirement(&base, &[]);
        assert!(first.required() && first.first_run && !first.unknown_baseline);
        assert_eq!(first.risk_class, "filename_set");
        assert_eq!(first.evidence_policy, "name_set_summary");
        assert_eq!(first.rules_key, "82d249853f6a40aa");
        assert_eq!(review_notice_text(&first), "");
        base.last_run_at = "2026-08-01T09:00:00".into();
        let unknown = review_requirement(&base, &[]);
        assert!(unknown.unknown_baseline && !unknown.first_run);
        assert_eq!(
            review_notice_text(&unknown),
            "마지막 실행에 쓴 규칙을 확인할 수 없습니다. 결과 문서를 열어 확인하세요."
        );
        base.reviewed_rules = rules_fingerprints(&base);
        let quiet = review_requirement(&base, &[]);
        assert!(!quiet.required());
        assert_eq!(review_notice_text(&quiet), "");

        for case in [
            "format",
            "source",
            "removed",
            "filename",
            "template",
            "template_source",
            "ordered_formats",
            "metadata",
            "filename_source",
            "filename_format",
        ] {
            let mut changed = base.clone();
            let (risk, policy, targets, structure, selection) = match case {
                "format" => {
                    changed.mapping.mappings[1].fmt = "천단위".into();
                    (
                        "presentation",
                        "formatted_value",
                        vec!["금액(표시형)"],
                        false,
                        false,
                    )
                }
                "source" => {
                    changed.mapping.mappings[1].source = "다른열".into();
                    (
                        "semantic_binding",
                        "value_scope_summary",
                        vec!["금액(연결)"],
                        false,
                        true,
                    )
                }
                "removed" => {
                    changed.mapping.mappings.pop();
                    (
                        "semantic_binding",
                        "value_scope_summary",
                        vec!["금액(연결)", "금액(표시형)"],
                        false,
                        true,
                    )
                }
                "filename" => {
                    changed.filename_pattern = "{{금액}}.hwpx".into();
                    changed.mapping.mappings[0].source = "다른열".into();
                    (
                        "filename_set",
                        "name_set_summary",
                        vec!["파일 이름 규칙", "공고명(연결)"],
                        false,
                        true,
                    )
                }
                "template" => {
                    changed.template_path = "다른.hwpx".into();
                    ("", "", vec![], true, false)
                }
                "template_source" => {
                    changed.template_path = "다른.hwpx".into();
                    changed.mapping.mappings[1].source = "다른열".into();
                    (
                        "semantic_binding",
                        "value_scope_summary",
                        vec!["템플릿", "금액(연결)"],
                        true,
                        true,
                    )
                }
                "ordered_formats" => {
                    changed.mapping.mappings[0].fmt = "x".into();
                    changed.mapping.mappings[1].fmt = "y".into();
                    (
                        "filename_set",
                        "name_set_summary",
                        vec!["공고명(표시형)", "금액(표시형)"],
                        false,
                        true,
                    )
                }
                "metadata" => {
                    changed.group = "가".into();
                    changed.favorited_at = "2026-07-27T00:00:00".into();
                    changed.tags.insert("축".into(), json!("값"));
                    ("", "", vec![], false, false)
                }
                "filename_source" => {
                    changed.mapping.mappings[0].source = "다른열".into();
                    (
                        "filename_set",
                        "name_set_summary",
                        vec!["공고명(연결)"],
                        false,
                        true,
                    )
                }
                _ => {
                    changed.mapping.mappings[0].fmt = "x".into();
                    (
                        "filename_set",
                        "name_set_summary",
                        vec!["공고명(표시형)"],
                        false,
                        true,
                    )
                }
            };
            let requirement = review_requirement(&changed, &[]);
            assert_eq!(
                (
                    requirement.risk_class,
                    requirement.evidence_policy,
                    requirement.structure_changed,
                    requirement.selection_bound
                ),
                (risk, policy, structure, selection),
                "{case}"
            );
            assert_eq!(requirement.changed_targets, targets, "{case}");
            let reloaded = decode_job(&encode_job(&changed, "").unwrap()).unwrap();
            assert_eq!(review_requirement(&reloaded, &[]), requirement, "{case}");
            assert_eq!(reloaded.reviewed_rules, base.reviewed_rules);
            let notice = review_notice_text(&requirement);
            if risk.is_empty() {
                assert!(notice.is_empty());
            } else {
                assert_eq!(
                    notice,
                    format!(
                        "마지막 실행 이후 바뀐 규칙이 있습니다: {}. 결과 문서를 열어 확인하세요.",
                        targets.join(", ")
                    )
                );
            }
        }

        let blanks = vec!["담당자".into(), "개찰장소".into()];
        let requirement = review_requirement(&base, &blanks);
        assert_eq!(requirement.risk_class, "blank_set");
        assert_eq!(requirement.evidence_policy, "blank_scope_summary");
        assert_eq!(requirement.changed_targets, blanks);
        assert_eq!(requirement.changed_fields, blanks);
        assert!(requirement.selection_bound);
        assert_eq!(review_notice_text(&requirement), "");
        base.template_path = "다른.hwpx".into();
        let requirement = review_requirement(&base, &blanks);
        assert!(requirement.structure_changed && requirement.selection_bound);
        assert_eq!(requirement.risk_class, "blank_set");
        base.mapping.mappings[1].fmt = "천단위".into();
        assert!(!review_requirement(&base, &[]).selection_bound);
        assert!(review_requirement(&base, &blanks).selection_bound);
        assert_eq!(
            review_requirement(&base, &blanks).risk_class,
            "presentation"
        );
        let previous_key = review_requirement(&base, &[]).rules_key;
        base.mapping.mappings[1].fmt = "다른표시형".into();
        assert_ne!(review_requirement(&base, &[]).rules_key, previous_key);
    }

    #[test]
    fn changed_source_outranks_format_and_blank_notice_stays_nonblocking() {
        let mut job = Job {
            filename_pattern: "고정.hwpx".into(),
            mapping: MappingProfile::new(
                "",
                vec![FieldMapping::new("금액", "old", "text", "", "", None).unwrap()],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        };
        job.reviewed_rules = rules_fingerprints(&job);
        let quiet = review_requirement(&job, &[]);
        assert!(!quiet.required());
        assert_eq!(review_notice_text(&quiet), "");
        let blank = review_requirement(&job, &["금액".into()]);
        assert_eq!(blank.risk_class, "blank_set");
        assert_eq!(review_notice_text(&blank), "");
        job.mapping.mappings[0].source = "new".into();
        job.mapping.mappings[0].fmt = "천단위".into();
        let changed = review_requirement(&job, &[]);
        assert_eq!(changed.risk_class, "semantic_binding");
        assert_eq!(changed.changed_targets, ["금액(연결)", "금액(표시형)"]);
        assert_eq!(changed.changed_fields, ["금액"]);
        assert_eq!(changed.rules_key.len(), 16);
    }
}
