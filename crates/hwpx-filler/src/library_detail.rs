//! Pure selected-library pairing card and read-only field rows.

use crate::home_state::JobRow;
use crate::job::Job;
use crate::mapping_state::{library_rows, profile_source_vocabulary, row_projection};
use chrono::{NaiveDateTime, Timelike};
use serde_json::{Map, Value, json};

const DETAIL_ROW_LIMIT: usize = 8;
const UNBOUND_FIRST_ROW_REASON: &str = "데이터를 연결해야 첫 행을 채울 수 있습니다.";

/// A completed first-row read. `None` at the call site means the read is pending.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FirstRowRead {
    pub state: String,
    pub reason: String,
    pub record: Map<String, Value>,
    pub headers: Vec<String>,
    pub record_count: usize,
}

#[derive(PartialEq, Eq)]
struct PairingInput {
    row: JobRow,
    job: Job,
    template_name: String,
    data_name: String,
    first_row: Option<FirstRowRead>,
    minute: NaiveDateTime,
}

/// Reuse the selected detail while all of its observed inputs remain unchanged.
#[derive(Default)]
pub struct PairingCache {
    entry: Option<(PairingInput, Value)>,
}
impl PairingCache {
    pub fn get(
        &mut self,
        row: &JobRow,
        job: &Job,
        template_name: &str,
        data_name: &str,
        first_row: Option<&FirstRowRead>,
        now: NaiveDateTime,
    ) -> Result<&Value, String> {
        let input = PairingInput {
            row: row.clone(),
            job: job.clone(),
            template_name: template_name.into(),
            data_name: data_name.into(),
            first_row: first_row.cloned(),
            minute: now
                .with_second(0)
                .and_then(|time| time.with_nanosecond(0))
                .expect("valid minute"),
        };
        if self
            .entry
            .as_ref()
            .is_none_or(|(previous, _)| previous != &input)
        {
            let value = pairing_detail(row, job, template_name, data_name, first_row, now)?;
            self.entry = Some((input, value));
        }
        Ok(&self.entry.as_ref().expect("computed pairing").1)
    }
}

pub fn primary_action(row: &JobRow) -> Value {
    if !row.template_linked {
        json!({"target":"editor", "label":"템플릿 연결하기",
            "hint":"템플릿을 연결해야 문서를 만들 수 있습니다."})
    } else if !["hwpx", "txt"].contains(&row.media.as_str()) {
        json!({"target":"editor", "label":"작업 편집에서 확인",
            "hint":"지원하지 않는 작업 방식입니다."})
    } else {
        json!({"target":"job", "label":"문서 만들기에서 사용", "hint":""})
    }
}

/// Caller supplies live display names and a captured first-row result from the host.
pub fn pairing_detail(
    row: &JobRow,
    job: &Job,
    template_name: &str,
    data_name: &str,
    first_row: Option<&FirstRowRead>,
    now: NaiveDateTime,
) -> Result<Value, String> {
    let structure = row.structure.as_ref();
    let readable = structure.is_some_and(|item| item.readable);
    let fields = structure.map_or(&[][..], |item| item.template_fields.as_slice());
    let unbound = structure.map_or(0, |item| item.template_only.len());
    let stale = structure.map_or(&[][..], |item| item.mapping_only.as_slice());
    let card = json!({
        "template_name": if job.template_path.is_empty() { "" } else { template_name },
        "template_bound": row.template_linked,
        "template_missing": row.template_missing,
        "data_name": data_name,
        "counted": readable,
        "template_field_count": fields.len(),
        "mapped_count": fields.len().saturating_sub(unbound),
        "unbound_count": unbound,
        "stale_count": stale.len(),
    });
    if !row.template_linked || row.template_missing {
        return Ok(
            json!({"card":card, "rows":[], "more_fields":[], "stale_fields":[],
            "rows_basis":"", "first_row":null}),
        );
    }
    let (state, reason, record_count, record) = if !job.has_data_binding() {
        ("error", UNBOUND_FIRST_ROW_REASON, 0, None)
    } else if let Some(read) = first_row {
        if !["ready", "error"].contains(&read.state.as_str()) {
            return Err(format!("알 수 없는 첫 행 상태: {}", read.state));
        }
        (
            read.state.as_str(),
            read.reason.as_str(),
            read.record_count,
            Some(&read.record),
        )
    } else {
        ("pending", "", 0, None)
    };
    let source_fields = first_row
        .filter(|read| !read.headers.is_empty())
        .map_or_else(
            || profile_source_vocabulary(&job.mapping),
            |read| read.headers.clone(),
        );
    let rows = library_rows(readable.then_some(fields), &job.mapping);
    let more_fields = rows
        .iter()
        .skip(DETAIL_ROW_LIMIT)
        .map(|item| item.template_field.clone())
        .collect::<Vec<_>>();
    let blank = Map::new();
    let record = record.unwrap_or(&blank);
    let shown = rows
        .iter()
        .take(DETAIL_ROW_LIMIT)
        .enumerate()
        .map(|(index, item)| {
            row_projection(
                item,
                record,
                index,
                &source_fields,
                record_count > 0,
                Some(now),
                state,
            )
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(json!({
        "card": card, "rows": shown, "more_fields": more_fields,
        "rows_basis": if readable { "template" } else { "profile" },
        "stale_fields": stale,
        "first_row": {"state":state, "reason":reason, "record_count":record_count},
    }))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::pairing_detail;
    use crate::home_state::{CompileState, JobRow, RowObservation};
    use crate::job::Job;
    use crate::mapping::{FieldMapping, MappingProfile};
    use chrono::NaiveDate;
    use serde_json::Map;

    #[test]
    fn current_template_fields_and_stale_mappings_stay_separate() {
        let job = Job {
            name: "계약".into(),
            template_path: "C:/계약.hwpx".into(),
            mapping: MappingProfile::new(
                "",
                vec![
                    FieldMapping::new("계약명", "사업명", "text", "", "", None).unwrap(),
                    FieldMapping::new("옛 필드", "오래된 열", "text", "", "", None).unwrap(),
                ],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        };
        let row = JobRow::from_job(
            &job,
            RowObservation {
                compile: Some(CompileState::Compiled),
                template_fields: Some(Ok(vec!["계약명".into(), "새 필드".into()])),
                ..RowObservation::default()
            },
        );
        let now = NaiveDate::from_ymd_opt(2026, 11, 5)
            .unwrap()
            .and_hms_opt(12, 0, 0)
            .unwrap();
        let detail = pairing_detail(&row, &job, "계약", "", None, now).unwrap();
        assert_eq!(detail["card"]["unbound_count"], 1);
        assert_eq!(detail["card"]["stale_count"], 1);
        assert_eq!(detail["rows"][0]["template_field"], "계약명");
        assert_eq!(detail["rows"][1]["template_field"], "새 필드");
        assert_eq!(detail["rows"][1]["row_state"], "needs_source");
        assert_eq!(detail["stale_fields"], serde_json::json!(["옛 필드"]));
        assert_eq!(detail["first_row"]["state"], "error");
        assert_detail_read_states(&job, now);
        assert_detail_field_sets(&job, now);
        assert_pairing_cache_inputs(&job, now);
    }

    fn assert_pairing_cache_inputs(job: &Job, now: chrono::NaiveDateTime) {
        use super::{FirstRowRead, PairingCache};
        use serde_json::json;
        let mut job = job.clone();
        job.data_path = "C:/계약.csv".into();
        let mut row = JobRow::from_job(
            &job,
            RowObservation {
                compile: Some(CompileState::Compiled),
                template_fields: Some(Ok(vec!["계약명".into()])),
                ..RowObservation::default()
            },
        );
        let mut cache = PairingCache::default();
        let address = cache.get(&row, &job, "계약", "데이터", None, now).unwrap()["rows"][0]["template_field"].as_str().unwrap().as_ptr();
        let within_minute = now + chrono::Duration::seconds(30);
        assert_eq!(
            cache
                .get(&row, &job, "계약", "데이터", None, within_minute)
                .unwrap()["rows"][0]["template_field"]
                .as_str()
                .unwrap()
                .as_ptr(),
            address
        );
        let tomorrow = now + chrono::Duration::days(1);
        assert_ne!(
            cache
                .get(&row, &job, "계약", "데이터", None, tomorrow)
                .unwrap()["rows"][0]["template_field"]
                .as_str()
                .unwrap()
                .as_ptr(),
            address
        );
        let renamed = cache
            .get(&row, &job, "새 템플릿", "새 데이터", None, tomorrow)
            .unwrap();
        assert_eq!(renamed["card"]["template_name"], "새 템플릿");
        assert_eq!(renamed["card"]["data_name"], "새 데이터");
        let mut read = FirstRowRead {
            state: "ready".into(),
            reason: String::new(),
            record: json!({"사업명":"처음"}).as_object().unwrap().clone(),
            headers: vec!["사업명".into()],
            record_count: 1,
        };
        assert_eq!(
            cache
                .get(&row, &job, "계약", "데이터", Some(&read), now)
                .unwrap()["rows"][0]["preview"],
            "처음"
        );
        read.record
            .insert("사업명".into(), json!("같은 건수의 새 값"));
        assert_eq!(
            cache
                .get(&row, &job, "계약", "데이터", Some(&read), now)
                .unwrap()["rows"][0]["preview"],
            "같은 건수의 새 값"
        );
        job.mapping.mappings[0] =
            FieldMapping::new("계약명", "다른 열", "text", "", "", None).unwrap();
        assert_eq!(
            cache
                .get(&row, &job, "계약", "데이터", Some(&read), now)
                .unwrap()["rows"][0]["source"],
            "다른 열"
        );
        row.structure
            .as_mut()
            .unwrap()
            .template_fields
            .push("추가".into());
        assert_eq!(
            cache
                .get(&row, &job, "계약", "데이터", Some(&read), now)
                .unwrap()["rows"]
                .as_array()
                .unwrap()
                .len(),
            2
        );
        read.state = "unknown".into();
        assert!(
            cache
                .get(&row, &job, "계약", "데이터", Some(&read), now)
                .is_err()
        );
        read.state = "error".into();
        read.reason = "read failure".into();
        assert_eq!(
            cache
                .get(&row, &job, "계약", "데이터", Some(&read), now)
                .unwrap()["first_row"]["reason"],
            "read failure"
        );
    }

    fn assert_detail_read_states(job: &Job, now: chrono::NaiveDateTime) {
        use super::{FirstRowRead, primary_action};
        use serde_json::json;
        let mut job = job.clone();
        job.data_path = "C:/계약.csv".into();
        let observed = RowObservation {
            compile: Some(CompileState::Compiled),
            template_fields: Some(Ok(vec!["계약명".into(), "새 필드".into()])),
            ..RowObservation::default()
        };
        let row = JobRow::from_job(&job, observed.clone());
        let detail = |row: &JobRow, job: &Job, read: Option<&FirstRowRead>| {
            pairing_detail(row, job, "계약", "계약 데이터", read, now).unwrap()
        };
        let pending = detail(&row, &job, None);
        assert_eq!(
            pending["first_row"],
            json!({"state":"pending","reason":"","record_count":0})
        );
        assert_eq!(pending["rows"][0]["preview"], "—");
        assert_eq!(pending["card"]["template_name"], "계약");
        assert_eq!(pending["card"]["data_name"], "계약 데이터");
        let mut read = FirstRowRead {
            state: "ready".into(),
            reason: String::new(),
            record: json!({"사업명":"청사 교체"}).as_object().unwrap().clone(),
            headers: vec!["사업명".into()],
            record_count: 2,
        };
        let ready = detail(&row, &job, Some(&read));
        assert_eq!(
            ready["first_row"],
            json!({"state":"ready","reason":"","record_count":2})
        );
        assert_eq!(ready["rows"][0]["preview"], "청사 교체");
        assert_eq!(ready["rows"][0]["preview_kind"], "value");
        assert_eq!(ready["rows"][0]["source_label"], "사업명");
        assert_eq!(ready["rows"][0]["display_label"], "원문");
        read.state = "error".into();
        read.reason = "파일을 읽을 수 없습니다".into();
        read.record.clear();
        read.record_count = 0;
        let failed = detail(&row, &job, Some(&read));
        assert_eq!(failed["first_row"]["reason"], read.reason);
        assert_eq!(failed["rows"][0]["preview_kind"], "error");
        assert!(
            !row.health_causes()
                .iter()
                .any(|(_, reason)| reason == &read.reason)
        );
        read.state = "unknown".into();
        assert!(pairing_detail(&row, &job, "계약", "", Some(&read), now).is_err());
        job.data_path.clear();
        assert_eq!(
            detail(&row, &job, None)["first_row"]["reason"],
            super::UNBOUND_FIRST_ROW_REASON
        );
        for path in ["C:/계약.hwpx", "C:/기안.txt", "C:/미상.doc", ""] {
            job.template_path = path.into();
            let row = JobRow::from_job(&job, observed.clone());
            assert_eq!(
                primary_action(&row)["target"],
                if path.ends_with("hwpx") || path.ends_with("txt") {
                    "job"
                } else {
                    "editor"
                }
            );
            let ranked = crate::work_candidates::rank_available(
                std::slice::from_ref(&job),
                &["사업명".into(), "오래된 열".into()],
            );
            assert_eq!(!ranked.is_empty(), primary_action(&row)["target"] == "job");
            assert!(
                crate::work_candidates::rank_available(
                    std::slice::from_ref(&job),
                    &["다른열".into()]
                )
                .is_empty()
            );
        }
        let unlinked = JobRow::from_job(&job, RowObservation::default());
        let absent = detail(&unlinked, &job, None);
        assert_eq!(absent["card"]["template_name"], "");
        assert_eq!(absent["card"]["template_bound"], false);
        assert_eq!(absent["rows"], json!([]));
        assert_eq!(absent["first_row"], serde_json::Value::Null);
        job.template_path = "C:/lost.hwpx".into();
        let missing = JobRow::from_job(
            &job,
            RowObservation {
                template_missing: true,
                ..RowObservation::default()
            },
        );
        let absent = detail(&missing, &job, None);
        assert_eq!(absent["card"]["template_missing"], true);
        assert_eq!(absent["rows"], json!([]));
        assert_eq!(absent["first_row"], serde_json::Value::Null);
        assert_eq!(primary_action(&missing)["target"], "job");
    }

    fn assert_detail_field_sets(job: &Job, now: chrono::NaiveDateTime) {
        use serde_json::json;
        let mut job = job.clone();
        for media in ["hwpx", "txt"] {
            job.template_path = format!("C:/계약.{media}");
            for readable in [true, false] {
                let fields = if readable {
                    Ok(vec!["계약명".into(), "새 필드".into()])
                } else {
                    Err("read failure".into())
                };
                let row = JobRow::from_job(
                    &job,
                    RowObservation {
                        compile: readable.then_some(CompileState::Compiled),
                        template_fields: Some(fields),
                        txt_readable: readable,
                        ..RowObservation::default()
                    },
                );
                let detail = pairing_detail(&row, &job, "계약", "", None, now).unwrap();
                assert_eq!(detail["card"]["counted"], readable);
                assert_eq!(
                    detail["rows_basis"],
                    if readable { "template" } else { "profile" }
                );
                let names = detail["rows"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|row| row["template_field"].as_str().unwrap())
                    .collect::<Vec<_>>();
                assert_eq!(
                    names,
                    if readable {
                        ["계약명", "새 필드"]
                    } else {
                        ["계약명", "옛 필드"]
                    }
                );
                assert_eq!(
                    detail["card"]["template_field_count"],
                    if readable { 2 } else { 0 }
                );
                assert_eq!(detail["card"]["mapped_count"], if readable { 1 } else { 0 });
                assert_eq!(
                    detail["card"]["unbound_count"],
                    if readable { 1 } else { 0 }
                );
                assert_eq!(detail["card"]["stale_count"], if readable { 1 } else { 0 });
                assert_eq!(
                    detail["stale_fields"],
                    if readable {
                        json!(["옛 필드"])
                    } else {
                        json!([])
                    }
                );
            }
        }
        let fields = (1..=12).map(|i| format!("필드{i}")).collect::<Vec<_>>();
        let row = JobRow::from_job(
            &job,
            RowObservation {
                template_fields: Some(Ok(fields.clone())),
                ..RowObservation::default()
            },
        );
        let detail = pairing_detail(&row, &job, "계약", "", None, now).unwrap();
        assert_eq!(detail["rows"].as_array().unwrap().len(), 8);
        assert_eq!(detail["more_fields"], json!(fields[8..]));
        assert_eq!(detail["card"]["template_field_count"], 12);
    }
}
