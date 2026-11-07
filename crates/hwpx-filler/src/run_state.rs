//! One immutable HWPX run diagnosis. The host supplies freshly read template fields.

use crate::data_source::{DataSource, Record};
use crate::dataset_reference::DatasetReference;
use crate::home_state::StructureDrift;
use crate::job::Job;
use crate::nara_acquire::AcquireResult;
use crate::output_name::pattern_field_tokens;
use crate::output_name_audit::{OutputNameAudit, audit_output_names};
use crate::run_request::RunRequest;
use crate::validation::ValidationReport;
use chrono::NaiveDateTime;
use serde_json::{Map, Value};
use std::collections::HashSet;

/// Frozen acquisition boundary: Nara resolves once to a keyless snapshot; file adapters stay live.
pub fn resolve_pool_source(
    item: &DatasetReference,
    source_factory: impl FnOnce(&DatasetReference) -> Result<Box<dyn DataSource>, String>,
    acquire_nara: impl FnOnce(&DatasetReference) -> Result<AcquireResult, String>,
) -> Result<(Box<dyn DataSource>, Vec<Record>), String> {
    if item.kind == "nara" {
        let result = acquire_nara(item)?;
        if !result.ok {
            return Err(format!("나라장터 데이터 취득 실패: {}", result.error));
        }
        return Ok((Box::new(result.as_datasource()), result.records));
    }
    let mut source = source_factory(item)?;
    let records = source.records().map_err(|error| error.to_string())?;
    Ok((source, records))
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PreflightResult {
    pub missing_columns: Vec<String>,
    pub empty_valued: Vec<String>,
    pub level: String,
    pub text: String,
    pub notices: Vec<String>,
}
impl PreflightResult {
    pub fn issues(&self) -> Vec<String> {
        let mut seen = HashSet::new();
        self.missing_columns
            .iter()
            .chain(&self.empty_valued)
            .filter(|item| seen.insert((*item).as_str()))
            .cloned()
            .collect()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldState {
    pub name: String,
    pub state: &'static str,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RunStatus {
    pub preflight: PreflightResult,
    pub field_states: Vec<FieldState>,
    pub audit: OutputNameAudit,
    pub drift: Option<StructureDrift>,
    pub unresolved_name_tokens: Vec<String>,
}

pub struct RunRefreshInput<'a> {
    pub job: &'a Job,
    pub records: &'a [Record],
    pub selected_indices: &'a [usize],
    pub data_mounted: bool,
    pub out_dir: &'a str,
    pub now: NaiveDateTime,
    pub template_fields: Result<Vec<String>, String>,
    pub mapped: Option<&'a [Map<String, Value>]>,
    pub review_notice: Option<&'a str>,
}

/// Mirrors the RunViewModel refresh boundary while leaving file IO and review policy to callers.
pub fn refresh_run(input: RunRefreshInput<'_>) -> Result<RunStatus, String> {
    let RunRefreshInput {
        job,
        records,
        selected_indices,
        data_mounted,
        out_dir,
        now,
        template_fields,
        mapped,
        review_notice,
    } = input;
    if !data_mounted {
        return Ok(RunStatus::default());
    }
    let request = RunRequest {
        job,
        records,
        selected_indices,
    };
    let source = request.source_report().map_err(|error| error.0)?;
    let output = request.output_report(Some(now)).map_err(|error| error.0)?;
    let drift = StructureDrift::from_fields(job, template_fields);
    let unresolved_name_tokens = unresolved_name_tokens(job);
    let audit = if selected_indices.is_empty() {
        OutputNameAudit::default()
    } else if let Some(mapped) = mapped {
        audit_output_names(&job.filename_pattern, mapped, out_dir, Some(now), None)
    } else {
        let mapped = request
            .mapped_records("", Some(now))
            .map_err(|error| error.0)?;
        audit_output_names(&job.filename_pattern, &mapped, out_dir, Some(now), None)
    };
    let preflight = preflight(
        &source,
        &output,
        &drift,
        !unresolved_name_tokens.is_empty(),
        audit.too_long.len(),
        review_notice,
    );
    let drift_names = drift
        .template_only
        .iter()
        .chain(&drift.mapping_only)
        .chain(&drift.conflicting)
        .map(String::as_str)
        .collect::<HashSet<_>>();
    let missing_names = output
        .empty_valued
        .iter()
        .map(String::as_str)
        .collect::<HashSet<_>>();
    let mut seen = HashSet::new();
    let field_states = job
        .mapping
        .cover_fields()
        .iter()
        .chain(&drift.template_only)
        .filter(|name| seen.insert((*name).clone()))
        .map(|name| FieldState {
            name: name.clone(),
            state: if drift_names.contains(name.as_str()) {
                "drift"
            } else if missing_names.contains(name.as_str()) {
                "missing"
            } else {
                "filled"
            },
        })
        .collect();
    Ok(RunStatus {
        preflight,
        field_states,
        audit,
        drift: Some(drift),
        unresolved_name_tokens,
    })
}

pub fn unresolved_name_tokens(job: &Job) -> Vec<String> {
    let mut resolved = job
        .mapping
        .cover_fields()
        .into_iter()
        .collect::<HashSet<_>>();
    for field in job.mapping.declared_empty_fields() {
        resolved.remove(&field);
    }
    pattern_field_tokens(&job.filename_pattern)
        .into_iter()
        .filter(|field| !resolved.contains(field))
        .collect()
}

fn preflight_level(
    source: &ValidationReport,
    output: &ValidationReport,
    drift: &StructureDrift,
    name_unresolved: bool,
    long_paths: usize,
) -> &'static str {
    if !source.missing_columns.is_empty() || drift.has_drift() || name_unresolved {
        "danger"
    } else if !output.empty_valued.is_empty() || long_paths > 0 {
        "warn"
    } else {
        "ok"
    }
}

pub fn preflight(
    source: &ValidationReport,
    output: &ValidationReport,
    drift: &StructureDrift,
    name_unresolved: bool,
    long_paths: usize,
    review_notice: Option<&str>,
) -> PreflightResult {
    let mut parts = Vec::new();
    if !source.missing_columns.is_empty() {
        parts.push(format!(
            "[치명] 데이터에 없는 항목입니다(빈 값 생성됨): {}",
            source.missing_columns.join(", ")
        ));
    }
    if drift.has_drift() {
        parts.push("[치명] 템플릿 구조가 확정 매핑과 다릅니다.".into());
    }
    if name_unresolved {
        parts.push("[치명] 파일명 패턴에 해소되지 않는 토큰이 있습니다.".into());
    }
    if !output.empty_valued.is_empty() {
        parts.push(format!(
            "[경고] 빈 값 필드: {}",
            output.empty_valued.join(", ")
        ));
    }
    if long_paths > 0 {
        parts.push(format!("[경고] 저장 경로가 너무 길어 저장에 실패할 수 있는 문서 {long_paths}건. 저장 폴더를 더 짧은 곳으로 바꾸거나 파일 이름 규칙을 줄이면 확실합니다."));
    }
    let notices = review_notice
        .filter(|notice| !notice.is_empty())
        .map(|notice| vec![format!("[알림] {notice}")])
        .unwrap_or_default();
    parts.extend(notices.iter().cloned());
    PreflightResult {
        missing_columns: source.missing_columns.clone(),
        empty_valued: output.empty_valued.clone(),
        level: preflight_level(source, output, drift, name_unresolved, long_paths).into(),
        text: if parts.is_empty() {
            "사전검증 통과(치명 누락 없음). 아래 빈 값 목록을 확인하세요.".into()
        } else {
            parts.join("\n")
        },
        notices,
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::mapping::{FieldMapping, MappingProfile};
    use serde_json::{Map, json};

    fn job() -> Job {
        Job {
            filename_pattern: "doc-{{공고명}}".into(),
            mapping: MappingProfile::from_dict(&json!({"mappings":[
                {"template_field":"공고명", "source":"bidNtceNm"},
                {"template_field":"추정가격", "source":"presmptPrce"}
            ]}))
            .unwrap(),
            ..Job::default()
        }
    }

    fn input<'a>(
        job: &'a Job,
        records: &'a [Record],
        selected: &'a [usize],
    ) -> RunRefreshInput<'a> {
        RunRefreshInput {
            job,
            records,
            selected_indices: selected,
            data_mounted: true,
            out_dir: "C:/out",
            now: chrono::NaiveDate::from_ymd_opt(2026, 1, 2)
                .unwrap()
                .and_hms_opt(3, 4, 5)
                .unwrap(),
            template_fields: Ok(vec!["공고명".into(), "추정가격".into()]),
            mapped: None,
            review_notice: None,
        }
    }

    #[test]
    fn diagnosis_keeps_missing_values_declarations_and_fresh_structure_errors_distinct() {
        let mut job = job();
        let records = vec![
            Record::from([
                ("bidNtceNm".into(), "가".into()),
                ("presmptPrce".into(), "".into()),
            ]),
            Record::from([
                ("bidNtceNm".into(), "나".into()),
                ("presmptPrce".into(), "2000".into()),
            ]),
        ];
        let status = refresh_run(input(&job, &records, &[0, 1])).unwrap();
        assert_eq!(status.preflight.level, "warn");
        assert_eq!(status.preflight.empty_valued, ["추정가격"]);
        assert!(status.preflight.missing_columns.is_empty());
        assert_eq!(
            status.field_states,
            [
                FieldState {
                    name: "공고명".into(),
                    state: "filled"
                },
                FieldState {
                    name: "추정가격".into(),
                    state: "missing"
                }
            ]
        );
        let mut missing_data = input(&job, &[], &[0]);
        missing_data.data_mounted = false;
        missing_data.template_fields = Err("손상".into());
        assert_eq!(refresh_run(missing_data).unwrap(), RunStatus::default());
        let full = refresh_run(input(&job, &records, &[1])).unwrap();
        assert!(full.preflight.empty_valued.is_empty());
        assert_eq!(full.preflight.level, "ok");
        let no_selection = refresh_run(input(&job, &records, &[])).unwrap();
        assert!(
            no_selection.audit.names.is_empty() && no_selection.preflight.empty_valued.is_empty()
        );
        job.mapping.mappings[1] = FieldMapping::new("추정가격", "", "const", "", "", None).unwrap();
        let declared = refresh_run(input(&job, &records, &[0])).unwrap();
        assert!(
            declared
                .field_states
                .iter()
                .all(|field| field.state == "filled")
        );
        assert!(declared.preflight.empty_valued.is_empty());
        for (fields, name) in [
            (
                Ok(vec!["공고명".into(), "추정가격".into(), "신규필드".into()]),
                "신규필드",
            ),
            (Ok(vec!["공고명".into()]), "추정가격"),
        ] {
            let mut request = input(&job, &records, &[0]);
            request.template_fields = fields;
            let changed = refresh_run(request).unwrap();
            assert_eq!(
                changed
                    .field_states
                    .iter()
                    .find(|field| field.name == name)
                    .unwrap()
                    .state,
                "drift"
            );
            assert_eq!(changed.preflight.level, "danger");
            assert!(
                changed.preflight.text.contains("구조") && !changed.preflight.text.contains("통과")
            );
        }
        let mut damaged = input(&job, &records, &[0]);
        damaged.template_fields = Err("not a zip".into());
        let damaged = refresh_run(damaged).unwrap();
        assert_eq!(damaged.preflight.level, "danger");
        assert_eq!(damaged.drift.unwrap().read_error, "not a zip");
    }

    #[test]
    fn filename_audit_and_nonblocking_notices_share_the_captured_run_inputs() {
        use crate::job::rules_fingerprints;
        use crate::review_state::{review_notice_text, review_requirement};
        let mut job = job();
        let records = vec![Record::from([
            ("bidNtceNm".into(), "가".into()),
            ("presmptPrce".into(), "2000".into()),
        ])];
        let first = review_notice_text(&review_requirement(&job, &[]));
        let mut request = input(&job, &records, &[0]);
        request.review_notice = Some(&first);
        let status = refresh_run(request).unwrap();
        assert_eq!(status.preflight.level, "ok");
        assert!(status.preflight.notices.is_empty());
        job.reviewed_rules = rules_fingerprints(&job);
        job.mapping.mappings[0].source = "presmptPrce".into();
        let changed = review_notice_text(&review_requirement(&job, &[]));
        let mut request = input(&job, &records, &[0]);
        request.review_notice = Some(&changed);
        let status = refresh_run(request).unwrap();
        assert_eq!(status.preflight.level, "ok");
        assert_eq!(
            status.preflight.notices,
            [
                "[알림] 마지막 실행 이후 바뀐 규칙이 있습니다: 공고명(연결). 결과 문서를 열어 확인하세요."
            ]
        );
        job.reviewed_rules = rules_fingerprints(&job);
        let blank = review_notice_text(&review_requirement(&job, &["추정가격".into()]));
        assert_eq!(blank, "");
        job.filename_pattern = "doc-{{ID}}".into();
        let status = refresh_run(input(&job, &records, &[0])).unwrap();
        assert_eq!(status.unresolved_name_tokens, ["ID"]);
        assert_eq!(status.preflight.level, "danger");
        assert!(status.preflight.text.contains("파일명"));
        job.mapping.mappings[1] = FieldMapping::new("추정가격", "", "const", "", "", None).unwrap();
        job.filename_pattern = "doc-{{추정가격}}".into();
        assert_eq!(unresolved_name_tokens(&job), ["추정가격"]);
        for pattern in [
            "doc-{{공고명}}",
            "doc-{{date}}-{{seq:001}}",
            crate::job::DEFAULT_FILENAME_PATTERN,
        ] {
            job.filename_pattern = pattern.into();
            let status = refresh_run(input(&job, &records, &[0])).unwrap();
            assert!(status.unresolved_name_tokens.is_empty());
            assert!(!status.preflight.text.contains("파일명 패턴"));
        }
        job.filename_pattern = "doc-{{date:HHmmSS}}".into();
        assert_eq!(
            refresh_run(input(&job, &records, &[0]))
                .unwrap()
                .audit
                .names,
            ["doc-030405.hwpx"]
        );
        job.filename_pattern = "doc-{{공고명}}".into();
        let mapped = [json!({"공고명":"표시 이름"}).as_object().unwrap().clone()];
        let mut request = input(&job, &records, &[0]);
        request.mapped = Some(&mapped);
        assert_eq!(
            refresh_run(request).unwrap().audit.names,
            ["doc-표시 이름.hwpx"]
        );
        job.filename_pattern = "{{공고명".into();
        let audit = refresh_run(input(&job, &records, &[0])).unwrap().audit;
        assert!(!audit.refusal_code.is_empty() && audit.names.is_empty());
        job.filename_pattern = "{{공고명}}".to_owned() + &"가".repeat(250);
        let status = refresh_run(input(&job, &records, &[0])).unwrap();
        if cfg!(windows) {
            assert_eq!(status.audit.too_long, [0]);
            assert_eq!(status.preflight.level, "warn");
            assert!(
                status
                    .preflight
                    .text
                    .contains("저장에 실패할 수 있는 문서 1건")
            );
        } else {
            assert!(status.audit.too_long.is_empty());
            assert!(!status.preflight.text.contains("저장에 실패할 수 있는"));
        }
    }

    #[test]
    fn run_diagnosis_keeps_fatal_warning_and_notice_in_order() {
        let job = Job {
            filename_pattern: "{{A}}".into(),
            mapping: MappingProfile::new(
                "",
                vec![FieldMapping::new("A", "source", "text", "", "", None).unwrap()],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        };
        let records = vec![[("source".into(), " ".into())].into_iter().collect()];
        let now = chrono::NaiveDate::from_ymd_opt(2026, 11, 5)
            .unwrap()
            .and_hms_opt(10, 30, 0)
            .unwrap();
        let status = refresh_run(RunRefreshInput {
            job: &job,
            records: &records,
            selected_indices: &[0],
            data_mounted: true,
            out_dir: "",
            now,
            template_fields: Ok(vec!["A".into(), "NEW".into()]),
            mapped: None,
            review_notice: Some("검토 사실"),
        })
        .unwrap();
        assert_eq!(status.preflight.level, "danger");
        assert_eq!(status.preflight.empty_valued, ["A"]);
        assert_eq!(status.preflight.notices, ["[알림] 검토 사실"]);
        assert_eq!(status.field_states[0].state, "missing");
        assert_eq!(
            status.field_states[1],
            FieldState {
                name: "NEW".into(),
                state: "drift"
            }
        );
        assert!(
            status
                .preflight
                .text
                .starts_with("[치명] 템플릿 구조가 확정 매핑과 다릅니다.\n[경고] 빈 값 필드: A")
        );
        assert!(status.preflight.text.ends_with("[알림] 검토 사실"));
        assert_eq!(status.preflight.issues(), ["A"]);
    }
}
