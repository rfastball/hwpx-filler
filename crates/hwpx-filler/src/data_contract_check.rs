//! Observe sender data without values, then judge receiver bindings against that evidence.

use crate::data_contract::{DataContract, DataContractError, FieldContract, binding_fingerprint};
use crate::format_engine::parse_dt;
use crate::mapping::{FieldMapping, MappingProfile, SOURCE_CARRIER_TYPES, source_value_outcome};
use crate::structure_scan::python_trim;
use crate::text_render::python_repr;
use crate::text_slice::{
    TEXT_SLICE_AFTER, TEXT_SLICE_BEFORE, TEXT_SLICE_BETWEEN, TEXT_SLICE_SPLIT, TextSlice,
};
use regex::Regex;
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::sync::LazyLock;

pub const REASON_BINDING_CHANGED: &str = "꾸러미와 연결이 다름";
pub const REASON_COLUMN_MISSING: &str = "데이터에 없음";
pub const REASON_ALL_BLANK: &str = "값이 모두 비어 있음";
pub const REASON_SHAPE_CHANGED: &str = "값 모양이 다름";
static NUMBER_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?u)[-+]?\d[\d,]*(\.\d+)?[\s\u{001C}-\u{001F}]*원?").expect("static number shape")
});

pub fn value_shape(text: &str) -> &'static str {
    if NUMBER_RE
        .find(text)
        .is_some_and(|match_| match_.start() == 0 && match_.end() == text.len())
    {
        "number"
    } else if parse_dt(text).is_some() {
        "date"
    } else {
        "text"
    }
}
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BindingObservation {
    pub rows: u64,
    pub blanks: u64,
    pub slice_misses: u64,
    pub format_failures: u64,
    pub shapes: HashSet<String>,
    pub lengths: Vec<usize>,
}
impl BindingObservation {
    pub fn failures(&self) -> u64 {
        self.slice_misses + self.format_failures
    }
    pub fn filled(&self) -> u64 {
        self.rows - self.blanks
    }
    pub fn shape(&self) -> &'static str {
        match self.shapes.len() {
            0 => "empty",
            1 => match self.shapes.iter().next().expect("one shape").as_str() {
                "number" => "number",
                "date" => "date",
                _ => "text",
            },
            _ => "text",
        }
    }
    pub fn length(&self) -> Option<(u64, u64)> {
        let low = *self.lengths.iter().min()? as u64;
        let high = *self.lengths.iter().max()? as u64;
        Some((low, high))
    }
    pub fn count(&mut self, mapping: &FieldMapping, raw: Option<&Value>) {
        self.rows += 1;
        let text = match raw {
            None | Some(Value::Null) => String::new(),
            Some(Value::String(text)) => text.clone(),
            Some(value) => python_repr(value),
        };
        if python_trim(&text).is_empty() {
            self.blanks += 1;
            return;
        }
        let outcome = source_value_outcome(
            &mapping.field_type,
            &text,
            &mapping.fmt,
            mapping.slice.as_ref(),
        );
        if outcome.slice_missed {
            self.slice_misses += 1;
        } else if python_trim(&outcome.sliced).is_empty() {
            self.blanks += 1;
        } else if !outcome.readable {
            self.format_failures += 1;
        } else {
            self.shapes.insert(value_shape(&outcome.sliced).into());
            self.lengths.push(outcome.sliced.chars().count());
        }
    }
}
pub fn observe_binding(
    mapping: &FieldMapping,
    records: &[Map<String, Value>],
) -> BindingObservation {
    let mut seen = BindingObservation::default();
    for record in records {
        seen.count(mapping, record.get(&mapping.source));
    }
    seen
}
pub fn contract_target(mapping: &FieldMapping) -> bool {
    SOURCE_CARRIER_TYPES.contains(&mapping.field_type.as_str()) && !mapping.source.is_empty()
}
pub fn profile_data_contract(
    profile: &MappingProfile,
    records: &[Map<String, Value>],
) -> Result<DataContract, DataContractError> {
    let fields = profile
        .mappings
        .iter()
        .filter(|mapping| contract_target(mapping))
        .map(|mapping| {
            let seen = observe_binding(mapping, records);
            FieldContract {
                field: mapping.template_field.clone(),
                column: mapping.source.clone(),
                binding: binding_fingerprint(mapping),
                rows: seen.rows,
                blanks: seen.blanks,
                failures: seen.failures(),
                shape: seen.shape().into(),
                length: seen.length(),
            }
        })
        .collect();
    let contract = DataContract { fields };
    contract.validate()?;
    Ok(contract)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ContractVerdict {
    pub binding: String,
    pub passed: bool,
    pub reason: String,
}
fn verdict(binding: String, passed: bool, reason: &str) -> ContractVerdict {
    ContractVerdict {
        binding,
        passed,
        reason: reason.into(),
    }
}
fn slice_miss_reason(spec: Option<&TextSlice>, count: u64) -> String {
    let Some(spec) = spec else {
        return String::new();
    };
    match spec.mode.as_str() {
        TEXT_SLICE_BEFORE | TEXT_SLICE_AFTER => format!(
            "기준 글자 ‘{}’가 없는 행 {count}",
            spec.delimiter.as_deref().unwrap_or("")
        ),
        TEXT_SLICE_BETWEEN => format!(
            "기준 글자 ‘{}’·‘{}’가 없는 행 {count}",
            spec.open.as_deref().unwrap_or(""),
            spec.close.as_deref().unwrap_or("")
        ),
        TEXT_SLICE_SPLIT => format!(
            "‘{}’로 나눈 조각이 모자란 행 {count}",
            spec.delimiter.as_deref().unwrap_or("")
        ),
        _ => format!("글자 범위를 벗어난 행 {count}"),
    }
}
fn failure_reason(mapping: &FieldMapping, seen: &BindingObservation) -> String {
    let mut parts = Vec::new();
    if seen.slice_misses > 0 {
        parts.push(slice_miss_reason(mapping.slice.as_ref(), seen.slice_misses));
    }
    if seen.format_failures > 0 {
        let reason = match mapping.field_type.as_str() {
            "date" => "날짜로 읽히지 않는 값",
            "amount" => "금액으로 읽히지 않는 값",
            _ => "표시형에 맞지 않는 값",
        };
        parts.push(format!("{reason} {}행", seen.format_failures));
    }
    parts.join(" · ")
}
fn worse_than(seen: &BindingObservation, entry: &FieldContract) -> bool {
    if seen.failures() == 0 {
        return false;
    }
    if entry.filled() == 0 {
        return true;
    }
    u128::from(seen.failures()) * u128::from(entry.filled())
        > u128::from(entry.failures) * u128::from(seen.filled())
}
pub fn judge_binding(
    entry: &FieldContract,
    mapping: &FieldMapping,
    columns: &[String],
    records: &[Map<String, Value>],
) -> ContractVerdict {
    let binding = binding_fingerprint(mapping);
    if binding != entry.binding {
        return verdict(binding, false, REASON_BINDING_CHANGED);
    }
    if !columns.contains(&mapping.source) {
        return verdict(binding, false, REASON_COLUMN_MISSING);
    }
    let seen = observe_binding(mapping, records);
    if worse_than(&seen, entry) {
        return verdict(binding, false, &failure_reason(mapping, &seen));
    }
    if seen.shape() != entry.shape {
        return verdict(
            binding,
            false,
            if seen.shape() == "empty" {
                REASON_ALL_BLANK
            } else {
                REASON_SHAPE_CHANGED
            },
        );
    }
    verdict(binding, true, "")
}
pub fn judge_fixed_binding(
    mapping: &FieldMapping,
    saved: Option<&FieldMapping>,
) -> ContractVerdict {
    let binding = binding_fingerprint(mapping);
    if saved.is_none_or(|saved| binding_fingerprint(saved) != binding) {
        verdict(binding, false, REASON_BINDING_CHANGED)
    } else {
        verdict(binding, true, "")
    }
}
pub fn judge_job_binding(
    contract: &DataContract,
    saved: &MappingProfile,
    mapping: &FieldMapping,
    columns: &[String],
    records: &[Map<String, Value>],
) -> Option<ContractVerdict> {
    if !contract_target(mapping) {
        let saved = saved
            .mappings
            .iter()
            .rev()
            .find(|saved| saved.template_field == mapping.template_field);
        return Some(judge_fixed_binding(mapping, saved));
    }
    contract
        .entry_for(&mapping.template_field)
        .map(|entry| judge_binding(entry, mapping, columns, records))
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct JobContractFit {
    pub passed: bool,
    pub failures: Vec<(String, String)>,
}
pub fn judge_job_contract(
    contract: &DataContract,
    profile: &MappingProfile,
    columns: &[String],
    records: &[Map<String, Value>],
) -> JobContractFit {
    if !profile.mappings.iter().any(contract_target) {
        return JobContractFit {
            passed: false,
            failures: Vec::new(),
        };
    }
    let failures = profile
        .mappings
        .iter()
        .filter_map(|mapping| {
            let verdict = judge_job_binding(contract, profile, mapping, columns, records);
            let reason = match verdict {
                None => REASON_BINDING_CHANGED,
                Some(ref verdict) if !verdict.passed => verdict.reason.as_str(),
                _ => return None,
            };
            Some((mapping.template_field.clone(), reason.into()))
        })
        .collect::<Vec<_>>();
    JobContractFit {
        passed: failures.is_empty(),
        failures,
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    fn record(value: Value) -> Map<String, Value> {
        value.as_object().unwrap().clone()
    }

    #[test]
    fn changed_binding_or_worse_failure_rate_refuses_auto_confirmation() {
        let mapping = FieldMapping::new("금액", "열", "amount", "", "", None).unwrap();
        let profile = MappingProfile::new("", vec![mapping.clone()], Map::new()).unwrap();
        let sender = vec![serde_json::from_str::<Map<String, Value>>(r#"{"열":"100"}"#).unwrap()];
        let contract = profile_data_contract(&profile, &sender).unwrap();
        let receiver =
            vec![serde_json::from_str::<Map<String, Value>>(r#"{"열":"협의"}"#).unwrap()];
        let cols = vec!["열".into()];
        assert_eq!(
            judge_job_contract(&contract, &profile, &cols, &receiver).failures[0].1,
            "금액으로 읽히지 않는 값 1행"
        );
        let mut changed = mapping;
        changed.source = "다른열".into();
        assert_eq!(
            judge_binding(&contract.fields[0], &changed, &cols, &receiver).reason,
            REASON_BINDING_CHANGED
        );
        assert_eq!(value_shape("12\u{001c}원"), "number");
        assert_eq!(value_shape("²"), "text");
        let fixed = MappingProfile::new(
            "",
            vec![FieldMapping::new("기관", "", "const", "가", "", None).unwrap()],
            Map::new(),
        )
        .unwrap();
        let fit = judge_job_contract(
            &DataContract { fields: Vec::new() },
            &fixed,
            &cols,
            &receiver,
        );
        assert!(!fit.passed && fit.failures.is_empty());
    }

    #[test]
    fn sender_contract_has_no_values_and_receiver_judgment_preserves_failure_reasons() {
        let title = FieldMapping::new("건명", "공고명", "text", "", "", None).unwrap();
        let amount = FieldMapping::new("금액", "추정가격", "amount", "", "", None).unwrap();
        let date = FieldMapping::new("계약일", "계약일자", "date", "", "", None).unwrap();
        let notice = FieldMapping::new(
            "공고번호",
            "입찰공고번호",
            "text",
            "",
            "",
            Some(
                TextSlice::from_dict(&json!({"mode":"before","delimiter":"-","on_missing":"keep"}))
                    .unwrap(),
            ),
        )
        .unwrap();
        let fixed = FieldMapping::new("작성자", "", "const", "홍길동", "", None).unwrap();
        let today = FieldMapping::new("작성일", "", "today", "", "", None).unwrap();
        let profile = MappingProfile::new(
            "",
            vec![
                title.clone(),
                amount.clone(),
                date.clone(),
                notice.clone(),
                fixed.clone(),
                today.clone(),
            ],
            Map::new(),
        )
        .unwrap();
        let sender = [
            json!({"공고명":"전산장비 구매","추정가격":"24750000","계약일자":"2026-06-15","입찰공고번호":"R26BK09017075-000"}),
            json!({"공고명":"사무용품","추정가격":"1,200,000원","계약일자":"2026.7.1","입찰공고번호":"R26BK09017076-000"}),
            json!({"공고명":"  ","추정가격":"","계약일자":"","입찰공고번호":""}),
        ].into_iter().map(record).collect::<Vec<_>>();
        let contract = profile_data_contract(&profile, &sender).unwrap();
        assert_eq!(
            contract
                .fields
                .iter()
                .map(|entry| entry.field.as_str())
                .collect::<Vec<_>>(),
            ["건명", "금액", "계약일", "공고번호"]
        );
        assert_eq!(
            (
                contract.fields[0].rows,
                contract.fields[0].blanks,
                contract.fields[0].shape.as_str(),
                contract.fields[0].length
            ),
            (3, 1, "text", Some((4, 7)))
        );
        assert_eq!(contract.entry_for("금액").unwrap().shape, "number");
        assert_eq!(contract.entry_for("계약일").unwrap().shape, "date");
        assert!(contract.entry_for("작성자").is_none() && contract.entry_for("작성일").is_none());
        let serialized = crate::data_contract::encode_data_contract(&contract)
            .unwrap()
            .to_string();
        for private in ["전산장비 구매", "24750000", "R26BK09017075", "홍길동"] {
            assert!(!serialized.contains(private), "{private}");
        }
        let received = [
            json!({"공고명":"청소용역","추정가격":"5,000,000","계약일자":"2026-09-01","입찰공고번호":"R26BK1-001"}),
            json!({"공고명":"","추정가격":"700000원","계약일자":"2026/10/2","입찰공고번호":"R26BK2-002"}),
        ].into_iter().map(record).collect::<Vec<_>>();
        let columns = vec![
            "공고명".into(),
            "추정가격".into(),
            "계약일자".into(),
            "입찰공고번호".into(),
        ];
        for mapping in [&title, &amount, &date, &notice] {
            let entry = contract.entry_for(&mapping.template_field).unwrap();
            let verdict = judge_binding(entry, mapping, &columns, &received);
            assert!(
                verdict.passed,
                "{}: {}",
                mapping.template_field, verdict.reason
            );
            assert_eq!(verdict.binding, binding_fingerprint(mapping));
        }
        let bad_date = [received[0].clone(), record(json!({"계약일자":"추후 협의"}))];
        assert_eq!(
            judge_binding(
                contract.entry_for("계약일").unwrap(),
                &date,
                &columns,
                &bad_date
            )
            .reason,
            "날짜로 읽히지 않는 값 1행"
        );
        let bad_notice = [
            record(json!({"입찰공고번호":"R26BK0901"})),
            record(json!({"입찰공고번호":"R26BK0902"})),
        ];
        assert_eq!(
            judge_binding(
                contract.entry_for("공고번호").unwrap(),
                &notice,
                &columns,
                &bad_notice
            )
            .reason,
            "기준 글자 ‘-’가 없는 행 2"
        );
        assert_eq!(
            judge_binding(
                contract.entry_for("계약일").unwrap(),
                &date,
                &columns[..2],
                &received
            )
            .reason,
            REASON_COLUMN_MISSING
        );
        let mut edited = date.clone();
        edited.fmt = "kor".into();
        assert_eq!(
            judge_binding(
                contract.entry_for("계약일").unwrap(),
                &edited,
                &columns,
                &received
            )
            .reason,
            REASON_BINDING_CHANGED
        );
        assert!(judge_fixed_binding(&fixed, Some(&fixed)).passed);
        assert!(!judge_fixed_binding(&fixed, None).passed);
        let mut changed = fixed.clone();
        changed.constant = "김철수".into();
        assert_eq!(
            judge_fixed_binding(&changed, Some(&fixed)).reason,
            REASON_BINDING_CHANGED
        );
        assert!(
            judge_job_binding(&contract, &profile, &title, &columns, &received)
                .unwrap()
                .passed
        );
        let extra = FieldMapping::new("비고", "공고명", "text", "", "", None).unwrap();
        assert!(judge_job_binding(&contract, &profile, &extra, &columns, &received).is_none());
        assert!(
            judge_job_binding(&contract, &profile, &today, &columns, &received)
                .unwrap()
                .passed
        );
        for (value, shape) in [
            ("24750000", "number"),
            ("-1,200.5원", "number"),
            ("2026-06-15", "date"),
            ("2026.7.1", "date"),
            ("2026년 6월 15일", "text"),
            ("R26BK0901", "text"),
        ] {
            assert_eq!(value_shape(value), shape, "{value}");
        }
    }

    #[test]
    fn blank_slice_miss_and_sender_failure_rate_have_distinct_contract_meanings() {
        let date = FieldMapping::new("날짜", "d", "date", "", "", None).unwrap();
        let observed = observe_binding(
            &date,
            &[
                record(json!({"d":""})),
                record(json!({"d":"   "})),
                record(json!({"d":null})),
                record(json!({"d":"미정"})),
                record(json!({"d":"2026-01-02"})),
            ],
        );
        assert_eq!(
            (
                observed.rows,
                observed.blanks,
                observed.format_failures,
                observed.slice_misses
            ),
            (5, 3, 1, 0)
        );
        let slice =
            TextSlice::from_dict(&json!({"mode":"before","delimiter":"-","on_missing":"empty"}))
                .unwrap();
        let sliced = FieldMapping::new("번호", "n", "text", "", "", Some(slice)).unwrap();
        let seen = observe_binding(
            &sliced,
            &[
                record(json!({"n":"A-1"})),
                record(json!({"n":"B2"})),
                record(json!({"n":"-tail"})),
            ],
        );
        assert_eq!(
            (seen.slice_misses, seen.blanks, seen.shape()),
            (1, 1, "text")
        );
        let profile = MappingProfile::new("", vec![date.clone()], Map::new()).unwrap();
        let sender = [
            record(json!({"d":"2026-01-01"})),
            record(json!({"d":"미정"})),
        ];
        let entry = &profile_data_contract(&profile, &sender).unwrap().fields[0];
        let columns = ["d".into()];
        let same = [
            record(json!({"d":"2026-02-02"})),
            record(json!({"d":"추후"})),
        ];
        assert!(judge_binding(entry, &date, &columns, &same).passed);
        let worse = [
            same[0].clone(),
            same[1].clone(),
            record(json!({"d":"미상"})),
        ];
        assert_eq!(
            judge_binding(entry, &date, &columns, &worse).reason,
            "날짜로 읽히지 않는 값 2행"
        );
        let blank_entry = &profile_data_contract(&profile, &[record(json!({"d":""}))])
            .unwrap()
            .fields[0];
        assert_eq!(
            (blank_entry.shape.as_str(), blank_entry.length),
            ("empty", None)
        );
        assert!(judge_binding(blank_entry, &date, &columns, &[record(json!({"d":""}))]).passed);
        assert!(
            !judge_binding(blank_entry, &date, &columns, &[record(json!({"d":"미정"}))]).passed
        );
        let code = FieldMapping::new("담당", "code", "text", "", "", None).unwrap();
        let code_profile = MappingProfile::new("", vec![code.clone()], Map::new()).unwrap();
        let code_entry = &profile_data_contract(
            &code_profile,
            &[
                record(json!({"code":"1001"})),
                record(json!({"code":"1002"})),
            ],
        )
        .unwrap()
        .fields[0];
        assert_eq!(
            judge_binding(
                code_entry,
                &code,
                &["code".into()],
                &[record(json!({"code":"A-1"}))]
            )
            .reason,
            REASON_SHAPE_CHANGED
        );
        assert_eq!(
            judge_binding(
                code_entry,
                &code,
                &["code".into()],
                &[record(json!({"code":""}))]
            )
            .reason,
            REASON_ALL_BLANK
        );
    }
}
