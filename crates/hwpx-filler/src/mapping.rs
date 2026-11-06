//! Pure product mapping profile and legacy source-value transformation.

use crate::field_binding::render_runtime_date;
use crate::format_engine::{self, RenderOutcome};
use crate::schema_drift::similarity;
use crate::structure_scan::python_trim;
use crate::text_render::python_repr;
use crate::text_slice::TextSlice;
use chrono::{Local, NaiveDateTime};
use serde_json::{Map, Value};
use std::collections::HashMap;
use std::fmt;

pub const TYPES: [&str; 5] = ["text", "date", "amount", "const", "today"];
pub const SOURCE_CARRIER_TYPES: [&str; 3] = ["text", "date", "amount"];
pub const SUGGEST_THRESHOLD: f64 = 0.7;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MappingError(pub String);
impl fmt::Display for MappingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for MappingError {}
fn fail(message: impl Into<String>) -> MappingError {
    MappingError(message.into())
}
fn repr(value: &str) -> String {
    python_repr(&Value::String(value.into()))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceValueOutcome {
    pub text: String,
    pub sliced: String,
    pub slice_missed: bool,
    pub readable: bool,
}

pub fn source_value_outcome(
    kind: &str,
    value: &str,
    fmt: &str,
    text_slice: Option<&TextSlice>,
) -> SourceValueOutcome {
    let stripped = python_trim(value);
    let (sliced, missed) = text_slice.map_or_else(
        || (stripped.into(), false),
        |slice| {
            let outcome = slice.evaluate(stripped);
            (outcome.text, outcome.missed)
        },
    );
    let RenderOutcome { text, readable } = format_engine::render_outcome(kind, fmt, &sliced);
    SourceValueOutcome {
        text,
        sliced,
        slice_missed: missed,
        readable,
    }
}

pub fn apply_transform(
    kind: &str,
    value: &str,
    constant: &str,
    fmt: &str,
    now: Option<NaiveDateTime>,
    text_slice: Option<&TextSlice>,
) -> Result<String, MappingError> {
    match kind {
        "const" => Ok(constant.into()),
        "today" => render_runtime_date(fmt, now.unwrap_or_else(|| Local::now().naive_local()))
            .map_err(|err| fail(err.message)),
        "text" | "date" | "amount" => Ok(source_value_outcome(kind, value, fmt, text_slice).text),
        _ => Err(fail(format!(
            "지원하지 않는 유형: {} (지원: ('text', 'date', 'amount', 'const', 'today'))",
            repr(kind)
        ))),
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldMapping {
    pub template_field: String,
    pub source: String,
    pub field_type: String,
    pub constant: String,
    pub fmt: String,
    pub slice: Option<TextSlice>,
}
impl FieldMapping {
    pub fn new(
        template_field: impl Into<String>,
        source: impl Into<String>,
        field_type: impl Into<String>,
        constant: impl Into<String>,
        fmt: impl Into<String>,
        slice: Option<TextSlice>,
    ) -> Result<Self, MappingError> {
        let result = Self {
            template_field: template_field.into(),
            source: source.into(),
            field_type: field_type.into(),
            constant: constant.into(),
            fmt: fmt.into(),
            slice,
        };
        result.validate()?;
        Ok(result)
    }
    pub fn validate(&self) -> Result<(), MappingError> {
        if self.slice.is_some() && ["const", "today"].contains(&self.field_type.as_str()) {
            return Err(fail(format!(
                "{} 유형에는 가공을 둘 수 없다: {}",
                repr(&self.field_type),
                repr(&self.template_field)
            )));
        }
        Ok(())
    }
    pub fn is_declared_empty(&self) -> bool {
        self.field_type == "const" && self.constant.is_empty()
    }
    pub fn value_for(
        &self,
        record: &Map<String, Value>,
        now: Option<NaiveDateTime>,
    ) -> Result<String, MappingError> {
        let value = record
            .get(&self.source)
            .map_or_else(String::new, |value| match value {
                Value::String(value) => value.clone(),
                value => python_repr(value),
            });
        apply_transform(
            &self.field_type,
            &value,
            &self.constant,
            &self.fmt,
            now,
            self.slice.as_ref(),
        )
    }
    pub fn to_dict(&self) -> Value {
        let mut out = Map::new();
        out.insert(
            "template_field".into(),
            Value::String(self.template_field.clone()),
        );
        out.insert("source".into(), Value::String(self.source.clone()));
        out.insert("type".into(), Value::String(self.field_type.clone()));
        out.insert("const".into(), Value::String(self.constant.clone()));
        out.insert("fmt".into(), Value::String(self.fmt.clone()));
        if let Some(slice) = &self.slice {
            out.insert("slice".into(), slice.to_dict());
        }
        Value::Object(out)
    }
    pub fn from_dict(value: &Value) -> Result<Self, MappingError> {
        let data = value
            .as_object()
            .ok_or_else(|| fail("mapping 은 사전이어야 합니다"))?;
        let required = data
            .get("template_field")
            .ok_or_else(|| fail("'template_field'"))?;
        let template_field = required
            .as_str()
            .ok_or_else(|| fail("template_field 는 문자열이어야 합니다"))?;
        let field_type = match data.get("type") {
            None => "text",
            Some(Value::String(value)) => value.as_str(),
            Some(value) => {
                return Err(fail(format!(
                    "지원하지 않는 유형: {} (지원: ('text', 'date', 'amount', 'const', 'today'))",
                    python_repr(value)
                )));
            }
        };
        if field_type == "blank" {
            return Self::new(template_field, "", "const", "", "", None);
        }
        if !TYPES.contains(&field_type) {
            return Err(fail(format!(
                "지원하지 않는 유형: {} (지원: ('text', 'date', 'amount', 'const', 'today'))",
                repr(field_type)
            )));
        }
        let string = |key: &str| match data.get(key) {
            None => Ok(""),
            Some(Value::String(value)) => Ok(value.as_str()),
            Some(_) => Err(fail(format!("{key} 는 문자열이어야 합니다"))),
        };
        let slice = data
            .get("slice")
            .filter(|value| !value.is_null())
            .map(TextSlice::from_dict)
            .transpose()
            .map_err(|err| fail(err.0))?;
        Self::new(
            template_field,
            string("source")?,
            field_type,
            string("const")?,
            string("fmt")?,
            slice,
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MappingProfile {
    pub name: String,
    pub mappings: Vec<FieldMapping>,
    pub provenance: Map<String, Value>,
}
impl MappingProfile {
    pub fn new(
        name: impl Into<String>,
        mappings: Vec<FieldMapping>,
        provenance: Map<String, Value>,
    ) -> Result<Self, MappingError> {
        for value in provenance.values() {
            if !value.is_string() {
                return Err(fail("'provenance' 의 키·값은 모두 문자열이어야 합니다"));
            }
        }
        Ok(Self {
            name: name.into(),
            mappings,
            provenance,
        })
    }
    pub fn template_fields(&self) -> Vec<String> {
        self.mappings
            .iter()
            .filter(|m| !m.is_declared_empty())
            .map(|m| m.template_field.clone())
            .collect()
    }
    pub fn mapped_fields(&self) -> Vec<String> {
        ordered_unique(self.template_fields())
    }
    pub fn declared_empty_fields(&self) -> Vec<String> {
        ordered_unique(
            self.mappings
                .iter()
                .filter(|m| m.is_declared_empty())
                .map(|m| m.template_field.clone())
                .collect(),
        )
    }
    pub fn cover_fields(&self) -> Vec<String> {
        ordered_unique(
            self.mappings
                .iter()
                .map(|m| m.template_field.clone())
                .collect(),
        )
    }
    pub fn coverage_set(&self) -> std::collections::HashSet<String> {
        self.cover_fields().into_iter().collect()
    }
    pub fn coverage_conflicts(&self) -> Vec<String> {
        let mut counts = HashMap::new();
        for mapping in &self.mappings {
            *counts.entry(&mapping.template_field).or_insert(0usize) += 1;
        }
        self.cover_fields()
            .into_iter()
            .filter(|field| counts.get(field).is_some_and(|count| *count > 1))
            .collect()
    }
    pub fn apply(
        &self,
        record: &Map<String, Value>,
        now: Option<NaiveDateTime>,
    ) -> Result<Map<String, Value>, MappingError> {
        let mut out = Map::new();
        for mapping in &self.mappings {
            out.insert(
                mapping.template_field.clone(),
                Value::String(mapping.value_for(record, now)?),
            );
        }
        Ok(out)
    }
    pub fn apply_all(
        &self,
        records: &[Map<String, Value>],
        now: Option<NaiveDateTime>,
    ) -> Result<Vec<Map<String, Value>>, MappingError> {
        records
            .iter()
            .map(|record| self.apply(record, now))
            .collect()
    }
    pub fn to_dict(&self) -> Value {
        let mut out = Map::new();
        out.insert("name".into(), Value::String(self.name.clone()));
        out.insert(
            "mappings".into(),
            Value::Array(self.mappings.iter().map(FieldMapping::to_dict).collect()),
        );
        out.insert("provenance".into(), Value::Object(self.provenance.clone()));
        Value::Object(out)
    }
    pub fn from_dict(value: &Value) -> Result<Self, MappingError> {
        let data = value
            .as_object()
            .ok_or_else(|| fail("profile 은 사전이어야 합니다"))?;
        let provenance = match data.get("provenance") {
            None => Map::new(),
            Some(Value::Object(data)) => data.clone(),
            Some(Value::Null) => {
                return Err(fail("'provenance' 는 사전이어야 하는데 NoneType 입니다"));
            }
            Some(Value::Array(_)) => {
                return Err(fail("'provenance' 는 사전이어야 하는데 list 입니다"));
            }
            Some(Value::String(_)) => {
                return Err(fail("'provenance' 는 사전이어야 하는데 str 입니다"));
            }
            Some(Value::Bool(_)) => {
                return Err(fail("'provenance' 는 사전이어야 하는데 bool 입니다"));
            }
            Some(Value::Number(number)) => {
                let kind = if number.to_string().contains(['.', 'e', 'E']) {
                    "float"
                } else {
                    "int"
                };
                return Err(fail(format!(
                    "'provenance' 는 사전이어야 하는데 {kind} 입니다"
                )));
            }
        };
        let mappings = match data.get("mappings") {
            None => Vec::new(),
            Some(Value::Array(items)) => items
                .iter()
                .map(FieldMapping::from_dict)
                .collect::<Result<_, _>>()?,
            Some(_) => return Err(fail("mappings 는 목록이어야 합니다")),
        };
        Self::new(
            data.get("name").and_then(Value::as_str).unwrap_or(""),
            mappings,
            provenance,
        )
    }
}

fn ordered_unique(values: Vec<String>) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    values
        .into_iter()
        .filter(|value| seen.insert(value.clone()))
        .collect()
}

pub fn suggest_mappings(
    template_fields: &[String],
    source_keys: &[String],
    aliases: &HashMap<String, String>,
    threshold: f64,
) -> Vec<FieldMapping> {
    let mut suggestions = Vec::new();
    for field in template_fields {
        if source_keys.iter().any(|key| key == field) {
            suggestions
                .push(FieldMapping::new(field, field, "text", "", "", None).expect("known type"));
            continue;
        }
        let mut best: Option<&String> = None;
        let mut score = 0.0;
        for key in source_keys {
            let current = similarity(field, aliases.get(key).unwrap_or(key));
            if current > score {
                best = Some(key);
                score = current;
            }
        }
        if score >= threshold
            && let Some(best) = best
        {
            suggestions
                .push(FieldMapping::new(field, best, "text", "", "", None).expect("known type"));
        }
    }
    suggestions
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use chrono::NaiveDate;
    use serde_json::json;

    #[test]
    fn profile_contract_and_legacy_blank() {
        let legacy = FieldMapping::from_dict(&json!({
            "template_field": "비고", "type": "blank", "source": "잔재", "fmt": "phone"
        }))
        .unwrap();
        assert_eq!(
            legacy.to_dict(),
            json!({
                "template_field": "비고", "source": "", "type": "const", "const": "", "fmt": ""
            })
        );
        let today = FieldMapping::new("작성일", "", "today", "", "%Y-%m-%d %H:%M", None).unwrap();
        let title = FieldMapping::new("공고명", "name", "text", "", "", None).unwrap();
        let profile =
            MappingProfile::new("p", vec![title.clone(), legacy, today, title], Map::new())
                .unwrap();
        assert_eq!(
            profile.template_fields(),
            vec!["공고명", "작성일", "공고명"]
        );
        assert_eq!(profile.mapped_fields(), vec!["공고명", "작성일"]);
        assert_eq!(profile.declared_empty_fields(), vec!["비고"]);
        assert_eq!(profile.coverage_conflicts(), vec!["공고명"]);
        let mut record = Map::new();
        record.insert("name".into(), json!("입찰"));
        let now = NaiveDate::from_ymd_opt(2026, 6, 15)
            .unwrap()
            .and_hms_opt(18, 4, 0)
            .unwrap();
        let applied = profile.apply(&record, Some(now)).unwrap();
        assert_eq!(applied.get("공고명"), Some(&json!("입찰")));
        assert_eq!(applied.get("비고"), Some(&json!("")));
        assert_eq!(applied.get("작성일"), Some(&json!("2026-06-15 18:04")));
        let batch = profile
            .apply_all(&[record.clone(), record.clone()], Some(now))
            .unwrap();
        assert_eq!(batch[0]["작성일"], batch[1]["작성일"]);
        assert_eq!(batch[0]["작성일"], "2026-06-15 18:04");
        assert_eq!(
            apply_transform("date", "2026-07-22", "", "", Some(now), None).unwrap(),
            "2026. 7. 22."
        );
        assert_eq!(
            apply_transform("date", "1400", "", "%H:%M", Some(now), None).unwrap(),
            "14:00"
        );
        assert_eq!(
            apply_transform("amount", "21326800", "", "", Some(now), None).unwrap(),
            "21,326,800원"
        );
        assert_eq!(
            apply_transform("amount", "미정", "", "", Some(now), None).unwrap(),
            "미정"
        );
        assert_eq!(
            apply_transform("const", "무시", "", "", Some(now), None).unwrap(),
            ""
        );
        assert_eq!(
            apply_transform("today", "2001-01-01", "무시", "kor", Some(now), None).unwrap(),
            "2026년 6월 15일 18:04"
        );
        assert!(!SOURCE_CARRIER_TYPES.contains(&"today"));
        assert!(apply_transform("blank", "x", "", "", Some(now), None).is_err());
        assert_eq!(
            MappingProfile::from_dict(&profile.to_dict())
                .unwrap()
                .to_dict(),
            profile.to_dict()
        );
        assert!(FieldMapping::from_dict(&json!({"template_field":"x", "type":"amonut"})).is_err());
        assert!(MappingProfile::from_dict(&json!({"provenance":{"template":5}})).is_err());
        assert!(FieldMapping::from_dict(&json!({"template_field":"x", "type":null})).is_err());
        assert!(MappingProfile::from_dict(&json!({"mappings":{"template_field":"x"}})).is_err());
        let missing_type =
            FieldMapping::from_dict(&json!({"template_field":"비고", "source":""})).unwrap();
        assert_eq!(missing_type.field_type, "text");
        assert!(!missing_type.is_declared_empty());
        let with_provenance = MappingProfile::new(
            "p",
            vec![missing_type],
            serde_json::from_value(
                json!({"template":"공고서.hwpx", "authored_at":"2026-07-17T10:00:00"}),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(
            MappingProfile::from_dict(&with_provenance.to_dict())
                .unwrap()
                .provenance,
            with_provenance.provenance
        );
    }

    #[test]
    fn suggestion_prefers_exact_source_over_alias() {
        let aliases = HashMap::from([("bidNtceNm".into(), "공고명".into())]);
        let suggested = suggest_mappings(
            &["공고명".into()],
            &["bidNtceNm".into(), "공고명".into()],
            &aliases,
            SUGGEST_THRESHOLD,
        );
        assert_eq!(suggested[0].source, "공고명");
        assert!(
            suggest_mappings(
                &["계약보증금".into()],
                &["계약금액".into()],
                &HashMap::new(),
                SUGGEST_THRESHOLD
            )
            .is_empty()
        );
    }

    #[test]
    fn suggestion_threshold_separates_risky_names_from_notation_variants() {
        use crate::schema_drift::similarity;

        let risky = [
            ("계약보증금", "계약금액", 2.0 / 3.0),
            ("입찰보증금", "입찰금액", 2.0 / 3.0),
            ("공고명", "공고일", 2.0 / 3.0),
            ("선금액", "잔금액", 2.0 / 3.0),
            ("계약상대자", "계약담당자", 0.6),
            ("납품기한", "납품장소", 0.5),
            ("계약일자", "계약금액", 0.5),
        ];
        let legitimate = [
            ("공고 번호", "공고번호", 1.0),
            ("계약 상대자", "계약상대자", 1.0),
            ("  계약금액  ", "계약금액", 1.0),
            ("\t수요기관\n", "수요기관", 1.0),
            ("계약_금액", "계약금액", 8.0 / 9.0),
            ("공고_번호", "공고번호", 8.0 / 9.0),
            ("추정가격(원)", "추정가격", 8.0 / 11.0),
            ("계약금액(원)", "계약금액", 8.0 / 11.0),
            ("납품기한(일)", "납품기한", 8.0 / 11.0),
            ("추정가격[원]", "추정가격", 8.0 / 11.0),
            ("계약금액 (원)", "계약금액", 8.0 / 11.0),
            ("계약보증금(원)", "계약보증금", 10.0 / 13.0),
        ];
        assert_eq!(SUGGEST_THRESHOLD, 0.7);
        for (field, source, expected) in risky {
            assert!((similarity(field, source) - expected).abs() < 1e-12);
            assert!(similarity(field, source) < SUGGEST_THRESHOLD);
            assert!(
                suggest_mappings(
                    &[field.into()],
                    &[source.into()],
                    &HashMap::new(),
                    SUGGEST_THRESHOLD
                )
                .is_empty()
            );
        }
        for (field, source, expected) in legitimate {
            assert!((similarity(field, source) - expected).abs() < 1e-12);
            assert!(similarity(field, source) >= SUGGEST_THRESHOLD);
            let suggestion = suggest_mappings(
                &[field.into()],
                &[source.into()],
                &HashMap::new(),
                SUGGEST_THRESHOLD,
            );
            assert_eq!(suggestion.len(), 1);
            assert_eq!(
                (&*suggestion[0].template_field, &*suggestion[0].source),
                (field, source)
            );
        }
        assert_eq!(
            suggest_mappings(
                &["계약보증금".into()],
                &["계약금액".into()],
                &HashMap::new(),
                0.6
            )[0]
            .source,
            "계약금액"
        );
        assert!(
            suggest_mappings(
                &["계약상대자".into()],
                &["계약상대자(업체명)".into()],
                &HashMap::new(),
                SUGGEST_THRESHOLD
            )
            .is_empty()
        );
    }

    #[test]
    fn nara_aliases_and_record_values_keep_source_ownership() {
        let aliases: HashMap<_, _> = crate::nara::default_field_labels().into_iter().collect();
        let source_keys: Vec<_> = aliases.keys().cloned().collect();
        let requested = ["입찰공고번호", "공고명", "추정가격", "입찰개시일자"];
        let suggestions = suggest_mappings(
            &requested.map(str::to_owned),
            &source_keys,
            &aliases,
            SUGGEST_THRESHOLD,
        );
        let found: HashMap<_, _> = suggestions
            .into_iter()
            .map(|m| (m.template_field, m.source))
            .collect();
        assert_eq!(found["입찰공고번호"], "bidNtceNo");
        assert_eq!(found["공고명"], "bidNtceNm");
        assert_eq!(found["추정가격"], "presmptPrce");
        assert_eq!(found["입찰개시일자"], "bidBeginDate");
        assert!(
            suggest_mappings(
                &["공고명".into()],
                &["bidNtceNm".into()],
                &HashMap::new(),
                SUGGEST_THRESHOLD
            )
            .is_empty()
        );

        let envelope: Value = serde_json::from_slice(include_bytes!(
            "../../../tests/fixtures/nara_std_response.json"
        ))
        .unwrap();
        let record = envelope
            .pointer("/response/body/items/0")
            .unwrap()
            .as_object()
            .unwrap();
        let profile = MappingProfile::new(
            "나라장터",
            vec![
                FieldMapping::new("입찰공고번호", "bidNtceNo", "text", "", "", None).unwrap(),
                FieldMapping::new("계약방법", "cntrctCnclsMthdNm", "text", "", "", None).unwrap(),
                FieldMapping::new("추정가격", "presmptPrce", "amount", "", "", None).unwrap(),
                FieldMapping::new("개찰일", "opengDate", "date", "", "", None).unwrap(),
                FieldMapping::new("개찰시각", "opengTm", "date", "", "%H:%M", None).unwrap(),
            ],
            Map::new(),
        )
        .unwrap();
        assert_eq!(
            profile.apply(record, None).unwrap(),
            json!({
                "입찰공고번호": "R26BK01561738", "계약방법": "제한경쟁", "추정가격": "65,454,545원",
                "개찰일": "2026. 6. 15.", "개찰시각": "18:00"
            })
            .as_object()
            .unwrap()
            .clone()
        );
    }
}
