//! Mutable editor mapping rows; projection continues to use `mapping_state`.

mod binding;
mod preview;
mod profile;
mod suggestion;

use crate::data_contract::binding_fingerprint;
use crate::data_contract_check::ContractVerdict;
use crate::mapping::{FieldMapping, MappingProfile, SUGGEST_THRESHOLD, suggest_mappings};
use crate::mapping_state::RowState;
use crate::schema::{FieldSpec, TemplateSchema, infer_type};
use crate::schema_drift::similarity;
use crate::text_render::python_repr;
use crate::text_slice::TextSlice;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EditorMappingError(pub String);
impl fmt::Display for EditorMappingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for EditorMappingError {}
fn fail(text: impl Into<String>) -> EditorMappingError {
    EditorMappingError(text.into())
}
fn default_type(spec: Option<&FieldSpec>, _name: &str) -> String {
    match spec.map(|spec| spec.inferred_type.as_str()).unwrap_or("") {
        "date" => "date",
        "amount" => "amount",
        _ => "text",
    }
    .into()
}

#[derive(Clone, Debug)]
pub struct EditorRow {
    pub spec: Option<FieldSpec>,
    pub template_field: String,
    pub source: String,
    pub field_type: String,
    pub constant: String,
    pub fmt: String,
    pub slice: Option<TextSlice>,
    pub confirmed: bool,
    pub touched: bool,
    pub auto_confirmed_exact: bool,
    pub manual_unconfirmed: bool,
    pub suggestion_score: f64,
    pub contract_verdict: Option<ContractVerdict>,
}
impl EditorRow {
    fn empty(name: &str, spec: Option<FieldSpec>) -> Self {
        Self {
            spec: spec.clone(),
            template_field: name.into(),
            source: String::new(),
            field_type: default_type(spec.as_ref(), name),
            constant: String::new(),
            fmt: String::new(),
            slice: None,
            confirmed: false,
            touched: false,
            auto_confirmed_exact: false,
            manual_unconfirmed: false,
            suggestion_score: 0.0,
            contract_verdict: None,
        }
    }
    fn from_mapping(mapping: &FieldMapping, spec: Option<FieldSpec>) -> Self {
        Self {
            spec,
            template_field: mapping.template_field.clone(),
            source: mapping.source.clone(),
            field_type: mapping.field_type.clone(),
            constant: mapping.constant.clone(),
            fmt: mapping.fmt.clone(),
            slice: mapping.slice.clone(),
            confirmed: true,
            touched: true,
            auto_confirmed_exact: false,
            manual_unconfirmed: false,
            suggestion_score: 0.0,
            contract_verdict: None,
        }
    }
    pub fn projection_row(&self) -> RowState {
        RowState {
            template_field: self.template_field.clone(),
            source: self.source.clone(),
            field_type: self.field_type.clone(),
            constant: self.constant.clone(),
            fmt: self.fmt.clone(),
            slice: self.slice.clone(),
            confirmed: self.confirmed,
            touched: self.touched,
            suggestion_score: self.suggestion_score,
            auto_confirmed_exact: self.auto_confirmed_exact,
        }
    }
    pub fn to_mapping(&self) -> Result<FieldMapping, EditorMappingError> {
        FieldMapping::new(
            &self.template_field,
            &self.source,
            &self.field_type,
            &self.constant,
            &self.fmt,
            self.slice.clone(),
        )
        .map_err(|error| fail(error.to_string()))
    }
    pub fn has_content(&self) -> bool {
        matches!(self.field_type.as_str(), "const" | "today") || !self.source.is_empty()
    }
    pub fn is_system_owned(&self) -> bool {
        !self.confirmed && !self.touched
    }
    pub fn is_declared_empty(&self) -> bool {
        self.field_type == "const" && self.constant.is_empty()
    }
    pub fn slice_enabled(&self) -> bool {
        ["text", "date", "amount"].contains(&self.field_type.as_str()) && !self.source.is_empty()
    }
    pub fn reset_to_system(&mut self) {
        self.source.clear();
        self.constant.clear();
        self.fmt.clear();
        self.slice = None;
        self.field_type = default_type(self.spec.as_ref(), &self.template_field);
        self.confirmed = false;
        self.touched = false;
        self.auto_confirmed_exact = false;
        self.manual_unconfirmed = false;
        self.suggestion_score = 0.0;
    }
    fn mark_edited(&mut self) {
        self.confirmed = false;
        self.touched = true;
        self.auto_confirmed_exact = false;
    }
    fn current_verdict(&self) -> Option<&ContractVerdict> {
        let verdict = self.contract_verdict.as_ref()?;
        let mapping = self.to_mapping().ok()?;
        (verdict.binding == binding_fingerprint(&mapping)).then_some(verdict)
    }
    pub fn contract_state_label(&self) -> &'static str {
        if self.confirmed && self.current_verdict().is_some_and(|verdict| verdict.passed) {
            "자동확정 · 꾸러미 조건 일치"
        } else {
            ""
        }
    }
    pub fn contract_reason(&self) -> &str {
        if self.confirmed {
            ""
        } else {
            self.current_verdict()
                .filter(|verdict| !verdict.passed)
                .map_or("", |verdict| verdict.reason.as_str())
        }
    }
    pub fn status(&self) -> &'static str {
        if self.confirmed {
            "confirmed"
        } else if !self.has_content() {
            "needs_source"
        } else if self.is_system_owned() {
            "suggested"
        } else {
            "edited"
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct EditorMappingModel {
    pub rows: Vec<EditorRow>,
    pub source_fields: Vec<String>,
    pub aliases: HashMap<String, String>,
}
impl EditorMappingModel {
    pub fn from_field_names(
        names: &[String],
        sources: &[String],
        aliases: &HashMap<String, String>,
        col_kinds: &HashMap<String, String>,
    ) -> Self {
        let available: HashSet<_> = sources.iter().collect();
        let rows = names
            .iter()
            .map(|name| {
                let mut row = EditorRow::empty(name, None);
                row.field_type = match infer_type(name) {
                    "date" => "date",
                    "amount" => "amount",
                    _ => "text",
                }
                .into();
                if available.contains(name) {
                    row.source = name.clone();
                    row.suggestion_score = 1.0;
                    row.confirmed = true;
                    row.auto_confirmed_exact = true;
                    if let Some(kind) = col_kinds.get(name).filter(|kind| !kind.is_empty()) {
                        row.field_type = match kind.as_str() {
                            "date" => "date",
                            "amount" => "amount",
                            _ => "text",
                        }
                        .into();
                    }
                }
                row
            })
            .collect();
        Self {
            rows,
            source_fields: sources.to_vec(),
            aliases: aliases.clone(),
        }
    }
    pub fn from_suggestions(
        schema: &TemplateSchema,
        sources: &[String],
        aliases: &HashMap<String, String>,
    ) -> Self {
        let names = schema.field_names();
        let drafts: HashMap<_, _> = suggest_mappings(&names, sources, aliases, SUGGEST_THRESHOLD)
            .into_iter()
            .map(|item| (item.template_field.clone(), item))
            .collect();
        let rows = schema
            .fields
            .iter()
            .map(|spec| {
                let mut row = EditorRow::empty(&spec.name, Some(spec.clone()));
                if let Some(draft) = drafts.get(&spec.name) {
                    row.source = draft.source.clone();
                    let exact = row.template_field == row.source;
                    row.suggestion_score = if exact {
                        1.0
                    } else {
                        similarity(
                            &row.template_field,
                            aliases.get(&row.source).unwrap_or(&row.source),
                        )
                    };
                    row.confirmed = exact;
                    row.auto_confirmed_exact = exact;
                }
                row
            })
            .collect();
        Self {
            rows,
            source_fields: sources.to_vec(),
            aliases: aliases.clone(),
        }
    }
    pub fn from_profile(profile: &MappingProfile) -> Self {
        let mut seen = HashSet::new();
        let sources = profile
            .mappings
            .iter()
            .filter(|item| !item.source.is_empty() && seen.insert(item.source.clone()))
            .map(|item| item.source.clone())
            .collect();
        Self {
            rows: profile
                .mappings
                .iter()
                .map(|mapping| EditorRow::from_mapping(mapping, None))
                .collect(),
            source_fields: sources,
            aliases: HashMap::new(),
        }
    }
    fn row_mut(&mut self, index: usize) -> Result<&mut EditorRow, EditorMappingError> {
        self.rows
            .get_mut(index)
            .ok_or_else(|| fail("매핑 행이 없습니다."))
    }
    pub fn index_of(&self, name: &str) -> Result<usize, EditorMappingError> {
        self.rows
            .iter()
            .position(|row| row.template_field == name)
            .ok_or_else(|| {
                fail(format!(
                    "매핑에 없는 토큰: {}",
                    python_repr(&Value::String(name.into()))
                ))
            })
    }
    pub fn is_complete(&self) -> bool {
        !self.rows.is_empty() && self.rows.iter().all(|row| row.confirmed)
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::{Map, json};

    fn strings(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| (*value).into()).collect()
    }

    fn schema(fields: &[(&str, &str)]) -> TemplateSchema {
        TemplateSchema {
            fields: fields
                .iter()
                .map(|(name, kind)| FieldSpec {
                    name: (*name).into(),
                    inferred_type: (*kind).into(),
                    occurrences: 1,
                    in_table: false,
                    context: String::new(),
                })
                .collect(),
            ..Default::default()
        }
    }

    fn suggested(fields: &[(&str, &str)], sources: &[&str]) -> EditorMappingModel {
        EditorMappingModel::from_suggestions(&schema(fields), &strings(sources), &HashMap::new())
    }

    fn nara_model() -> EditorMappingModel {
        let labels = crate::nara::default_field_labels();
        EditorMappingModel::from_suggestions(
            &schema(&[
                ("입찰공고번호", "number"),
                ("공고명", "text"),
                ("추정가격", "amount"),
                ("개찰일시", "date"),
                ("존재하지않는들판xyz", "text"),
            ]),
            &labels.keys().cloned().collect::<Vec<_>>(),
            &labels.into_iter().collect(),
        )
    }

    fn names(profile: &MappingProfile) -> Vec<&str> {
        profile
            .mappings
            .iter()
            .map(|row| row.template_field.as_str())
            .collect()
    }

    #[test]
    fn suggestions_require_confirmation_and_keep_explicit_empty_declarations() {
        let mut model = nara_model();
        assert_eq!(
            model
                .rows
                .iter()
                .map(|row| (
                    row.template_field.as_str(),
                    row.source.as_str(),
                    row.field_type.as_str()
                ))
                .collect::<Vec<_>>(),
            [
                ("입찰공고번호", "bidNtceNo", "text"),
                ("공고명", "bidNtceNm", "text"),
                ("추정가격", "presmptPrce", "amount"),
                ("개찰일시", "opengDate", "date"),
                ("존재하지않는들판xyz", "", "text"),
            ]
        );
        assert!(
            model.rows[..4]
                .iter()
                .all(|row| row.suggestion_score > 0.6 && !row.confirmed)
        );
        assert_eq!(model.rows[4].suggestion_score, 0.0);
        let fixture: Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/nara_std_response.json"
        ))
        .unwrap();
        let record = fixture["response"]["body"]["items"][0].as_object().unwrap();
        let rendered = model.preview(record, None).unwrap();
        assert_eq!(rendered["입찰공고번호"], "R26BK01561738");
        assert_eq!(rendered["추정가격"], "65,454,545원");
        assert_eq!(rendered["존재하지않는들판xyz"], "");
        assert_eq!(model.rows[0].status(), "suggested");
        assert_eq!(model.rows[4].status(), "needs_source");
        assert!(!model.is_complete() && !model.emits_any_value());
        model.set_source(1, "bidNtceNm").unwrap();
        assert_eq!(model.rows[1].status(), "edited");
        assert_eq!(model.counts(), (3, 2, 0, 0));
        assert_eq!(model.confirm_suggested(), 3);
        assert_eq!(model.confirm_suggested(), 0);
        assert!(!model.is_complete());
        assert_eq!(model.rows[0].status(), "confirmed");
        model.set_confirmed(1, true).unwrap();
        assert!(!model.is_complete());
        model.set_display(4, "const", "").unwrap();
        assert!(model.set_confirmed(4, true).unwrap());
        assert_eq!(model.counts(), (0, 0, 1, 5));
        assert!(model.is_complete() && model.emits_any_value());
        assert_eq!(model.declared_empty_fields(), ["존재하지않는들판xyz"]);
        let saved = model.to_profile("p").unwrap();
        assert_eq!(saved.name, "p");
        assert_eq!(saved.cover_fields().len(), 5);
        assert_eq!(saved.template_fields().len(), 4);
        assert_eq!(saved.declared_empty_fields(), ["존재하지않는들판xyz"]);
        let undo = model.unconfirm_all();
        assert!(!model.is_complete() && !model.emits_any_value());
        assert!(model.rows.iter().all(|row| !row.confirmed && row.touched));
        assert_eq!(model.restore_confirmed(&undo), 5);
        assert!(model.is_complete());
        assert!(!EditorMappingModel::default().is_complete());

        let exact = EditorMappingModel::from_suggestions(
            &schema(&[("공고명", "text"), ("계약 금액", "amount")]),
            &strings(&["bidNtceNm", "공고명", "계약금액"]),
            &HashMap::from([
                ("bidNtceNm".into(), "공고명".into()),
                ("공고명".into(), "다른 이름".into()),
            ]),
        );
        assert_eq!(exact.rows[0].source, "공고명");
        assert!(exact.rows[0].confirmed && exact.rows[0].auto_confirmed_exact);
        assert_eq!(exact.rows[1].source, "계약금액");
        assert!(!exact.rows[1].confirmed && !exact.rows[1].auto_confirmed_exact);
        let projection = crate::mapping_state::row_projection(
            &exact.rows[0].projection_row(),
            &Map::new(),
            0,
            &exact.source_fields,
            true,
            None,
            "ready",
        )
        .unwrap();
        assert_eq!(projection["state_label"], "자동확정 · 이름 일치");
        assert_eq!(projection["preview"], "〘미입력·공고명〙");
        assert_eq!(projection["preview_kind"], "missing");

        let mut empty = suggested(&[("비고", "text")], &[]);
        empty.set_manual(0, "").unwrap();
        empty.set_confirmed(0, true).unwrap();
        assert!(empty.is_complete() && empty.emits_any_value());
        assert!(empty.to_profile("").unwrap().template_fields().is_empty());
        assert_eq!(
            empty
                .to_profile("")
                .unwrap()
                .apply(&Map::new(), None)
                .unwrap()["비고"],
            ""
        );
        for inferred in ["date", "amount", "text", "number", "phone", ""] {
            assert_ne!(
                suggested(&[("작성일", inferred)], &[]).rows[0].field_type,
                "today"
            );
        }
    }

    #[test]
    fn source_changes_preserve_manual_ownership_and_demote_without_silent_rebinding() {
        let mut model = suggested(&[("계약금액", "amount")], &["계약_금액"]);
        assert_eq!(model.rows[0].source, "계약_금액");
        assert!(
            model
                .apply_active_sources(&strings(&["계약금액", "계약_금액"]), None)
                .unwrap()
                .is_empty()
        );
        assert!(model.rows[0].confirmed && model.rows[0].auto_confirmed_exact);
        model.set_manual(0, "X").unwrap();
        assert_eq!(
            model
                .apply_active_sources(&strings(&["계약_금액"]), None)
                .unwrap(),
            ["계약금액"]
        );
        assert!(
            model.rows[0].source.is_empty()
                && model.rows[0].constant.is_empty()
                && !model.rows[0].touched
        );
        assert_eq!(model.rows[0].field_type, "amount");
        model
            .apply_active_sources(&strings(&["계약_금액"]), None)
            .unwrap();
        assert_eq!(model.rows[0].source, "계약_금액");
        assert!(model.rows[0].to_mapping().unwrap().constant.is_empty());

        let mut model = suggested(&[("품명", "text"), ("규격", "text")], &["품명", "규격"]);
        model.set_source(0, "없는열").unwrap();
        model.set_source(1, "규격").unwrap();
        model.revert_to_auto(1).unwrap();
        model.resuggest_row(1, &strings(&["품명", "규격"])).unwrap();
        assert_eq!(model.rows[0].source, "없는열");
        assert!(model.rows[0].touched && model.rows[1].confirmed);
        assert_eq!(
            model
                .apply_active_sources(&strings(&["품명"]), Some(&strings(&["품명", "규격"])))
                .unwrap(),
            ["규격"]
        );
        assert_eq!(model.rows[0].source, "없는열");

        let mut model = suggested(&[("품명", "text")], &["품명"]);
        assert!(model.rows[0].confirmed && !model.rows[0].touched);
        model.set_confirmed(0, false).unwrap();
        model
            .apply_active_sources(&strings(&["품명"]), None)
            .unwrap();
        model.resuggest_row(0, &strings(&["품명"])).unwrap();
        assert!(!model.rows[0].confirmed && model.rows[0].manual_unconfirmed);
        assert_eq!(names(&model.carry_profile("").unwrap()), ["품명"]);
        assert_eq!(model.apply_active_sources(&[], None).unwrap(), ["품명"]);
        model
            .apply_active_sources(&strings(&["품명"]), None)
            .unwrap();
        assert!(!model.rows[0].confirmed);
        model.revert_to_auto(0).unwrap();
        model.resuggest_row(0, &strings(&["품명"])).unwrap();
        assert!(model.rows[0].confirmed && model.rows[0].auto_confirmed_exact);
        model.set_display(0, "text", "").unwrap();
        assert!(!model.rows[0].confirmed && !model.rows[0].auto_confirmed_exact);
        model.set_display(0, "const", "").unwrap();
        model.set_confirmed(0, true).unwrap();
        model.set_confirmed(0, false).unwrap();
        model
            .apply_active_sources(&strings(&["품명"]), None)
            .unwrap();
        assert!(model.rows[0].source.is_empty() && model.rows[0].is_declared_empty());
        assert_eq!(model.confirm_suggested(), 0);

        let mut carried = suggested(
            &[("품명", "text"), ("수량", "number"), ("규격", "text")],
            &["품명", "수량", "규격"],
        );
        carried.set_source(1, "수량").unwrap();
        carried.set_confirmed(0, true).unwrap();
        assert_eq!(names(&carried.carry_profile("").unwrap()), ["품명", "수량"]);
        carried.set_source(1, "").unwrap();
        carried.set_display(2, "const", "").unwrap();
        carried.set_confirmed(2, true).unwrap();
        assert_eq!(names(&carried.carry_profile("").unwrap()), ["품명", "규격"]);
        assert!(carried.carry_profile("").unwrap().mappings[1].is_declared_empty());

        let mut confirmed = nara_model();
        confirmed.confirm_suggested();
        let active = confirmed
            .source_fields
            .iter()
            .filter(|name| *name != "bidNtceNo")
            .cloned()
            .collect::<Vec<_>>();
        assert_eq!(
            confirmed.apply_active_sources(&active, None).unwrap(),
            ["입찰공고번호"]
        );
        assert!(confirmed.rows[0].is_system_owned() && confirmed.rows[0].source.is_empty());
        assert!(confirmed.rows[1..4].iter().all(|row| row.confirmed));
        let undo = carried.unconfirm_all();
        assert!(carried.rows.iter().all(|row| !row.auto_confirmed_exact));
        carried.restore_confirmed(&undo);
    }

    #[test]
    fn binding_and_display_transitions_keep_slices_only_on_column_values() {
        let mut model = suggested(&[("금액", "amount")], &["금액"]);
        model.set_display(0, "const", "").unwrap();
        model.set_const(0, "일금").unwrap();
        model.set_source(0, "amount").unwrap();
        assert_eq!(model.rows[0].field_type, "amount");
        assert!(model.rows[0].constant.is_empty());
        model.set_display(0, "today", "kor").unwrap();
        assert!(model.rows[0].source.is_empty());
        model.set_source(0, "amount").unwrap();
        assert_eq!(model.rows[0].field_type, "amount");
        assert!(model.rows[0].fmt.is_empty());
        let slice = json!({"mode":"split","delimiter":"원","index":1});
        model.set_confirmed(0, true).unwrap();
        model.set_slice(0, Some(&slice)).unwrap();
        assert!(!model.rows[0].confirmed && model.rows[0].touched);
        model.set_display(0, "amount", "").unwrap();
        assert_eq!(model.rows[0].slice.as_ref().unwrap().to_dict(), slice);
        assert_eq!(
            model.rows[0]
                .to_mapping()
                .unwrap()
                .value_for(
                    json!({"amount":"170,309,180원 (VAT 포함)"})
                        .as_object()
                        .unwrap(),
                    None
                )
                .unwrap(),
            "170,309,180원"
        );
        let before = model.rows[0].to_mapping().unwrap();
        assert!(
            model
                .set_slice(0, Some(&json!({"mode":"split","delimiter":"","index":1})))
                .is_err()
        );
        assert_eq!(model.rows[0].to_mapping().unwrap(), before);
        assert!(model.set_display(0, "blank", "").is_err());
        assert_eq!(model.rows[0].to_mapping().unwrap(), before);
        for transition in 0..7 {
            let mut changed = model.clone();
            match transition {
                0 => changed.set_display(0, "const", "").unwrap(),
                1 => changed.set_display(0, "today", "").unwrap(),
                2 => changed.set_manual(0, "직접").unwrap(),
                3 => changed.bind_column(0, "다른열", "amount").unwrap(),
                4 => changed.unbind(0).unwrap(),
                5 => changed.revert_to_auto(0).unwrap(),
                _ => changed.freeze_to_const(0, "굳힘").unwrap(),
            }
            assert!(changed.rows[0].slice.is_none(), "{transition}");
            changed.rows[0].to_mapping().unwrap();
        }
        model.set_manual(0, "").unwrap();
        assert_eq!(model.rows[0].source, "amount");
        assert!(model.rows[0].has_content() && model.rows[0].is_declared_empty());
        assert!(model.set_slice(0, Some(&slice)).is_err());
        model.set_slice(0, None).unwrap();
        assert!(model.revert_binding(0, "amount").unwrap());
        assert_eq!(model.rows[0].field_type, "amount");
        model.unbind(0).unwrap();
        assert!(!model.rows[0].slice_enabled());
        assert!(model.set_slice(0, Some(&slice)).is_err());
        model.set_manual(0, "값").unwrap();
        assert!(!model.revert_binding(0, "").unwrap());
        model.bind_column(0, "다른열", "amount").unwrap();
        assert!(model.rows[0].constant.is_empty());
        model.unbind(0).unwrap();
        assert!(model.rows[0].is_system_owned() && model.rows[0].source.is_empty());
    }

    #[test]
    fn profiles_roundtrip_confirmation_formats_and_live_preview_values() {
        let profile = MappingProfile::from_dict(&json!({"name":"저장", "mappings":[
            {"template_field":"명","source":"name","type":"text"},
            {"template_field":"비고","type":"const","const":""},
            {"template_field":"금액","source":"amount","type":"amount","fmt":"{:,}","slice":{"mode":"split","delimiter":"원","index":1}},
        ]})).unwrap();
        let profile = MappingProfile::from_dict(
            &serde_json::from_str::<Value>(&serde_json::to_string(&profile.to_dict()).unwrap())
                .unwrap(),
        )
        .unwrap();
        let restored = EditorMappingModel::from_profile(&profile);
        assert_eq!(restored.source_fields, ["name", "amount"]);
        assert!(restored.is_complete() && restored.rows[1].is_declared_empty());
        assert_eq!(restored.rows[2].fmt, "{:,}");
        assert!(restored.rows[2].slice.is_some());
        let mut fresh = suggested(
            &[("명", "text"), ("비고", "text"), ("금액", "amount")],
            &["name"],
        );
        assert_eq!(fresh.apply_profile(&profile, true, true), 2);
        assert!(!fresh.rows[2].confirmed && fresh.rows[2].source == "amount");
        assert!(!fresh.is_complete());
        assert_eq!(fresh.apply_profile(&profile, false, true), 3);
        assert!(fresh.is_complete());
        assert_eq!(fresh.to_profile("저장").unwrap(), profile);
        let record = json!({"name":"통학차량","amount":"21326800원 (VAT 포함)"});
        assert_eq!(
            json!(fresh.preview(record.as_object().unwrap(), None).unwrap()),
            json!({"명":"통학차량","비고":"","금액":"21,326,800"})
        );
        fresh.set_manual(0, "김민수").unwrap();
        assert_eq!(
            fresh
                .live_profile("")
                .unwrap()
                .apply(record.as_object().unwrap(), None)
                .unwrap()["명"],
            "김민수"
        );
        assert!(
            !fresh
                .to_profile("")
                .unwrap()
                .cover_fields()
                .contains(&"명".into())
        );
        fresh.set_manual(0, "").unwrap();
        assert_eq!(
            fresh
                .live_profile("")
                .unwrap()
                .apply(record.as_object().unwrap(), None)
                .unwrap()["명"],
            ""
        );
        fresh.set_confirmed(0, true).unwrap();
        assert_eq!(fresh.declared_empty_fields(), ["명", "비고"]);
        fresh.set_manual(0, "다시").unwrap();
        assert_eq!(fresh.declared_empty_fields(), ["비고"]);

        let mut model = EditorMappingModel::from_profile(
            &MappingProfile::from_dict(&json!({"mappings":[
                {"template_field":"작성일","type":"today","fmt":"kor"},
                {"template_field":"금액","source":"amount","type":"amount"},
                {"template_field":"개찰","source":"time","type":"date","fmt":"%H:%M"},
                {"template_field":"계약일","source":"date","type":"date","fmt":"%Y-%m-%d"},
                {"template_field":"연락처","source":"tel","type":"text","fmt":"phone"},
            ]}))
            .unwrap(),
        );
        let now = chrono::NaiveDate::from_ymd_opt(2026, 6, 15)
            .unwrap()
            .and_hms_opt(18, 4, 0)
            .unwrap();
        let record =
            json!({"amount":"21326800","time":"18:00","date":"2026-6-5","tel":"01012345678"});
        assert_eq!(
            json!(
                model
                    .preview(record.as_object().unwrap(), Some(now))
                    .unwrap()
            ),
            json!({"작성일":"2026년 6월 15일 18:04","금액":"21,326,800원","개찰":"18:00","계약일":"2026-06-05","연락처":"010-1234-5678"})
        );
        assert_eq!(
            model
                .preview_counts(record.as_object().unwrap(), Some(now))
                .unwrap(),
            (5, 0, 0)
        );
        assert!(
            model
                .preview_empties(record.as_object().unwrap(), Some(now))
                .unwrap()
                .is_empty()
        );
        assert_eq!(
            model.name_token_values(record.as_object().unwrap(), Some(now)),
            model
                .preview(record.as_object().unwrap(), Some(now))
                .unwrap()
        );
        model.set_display(1, "amount", "{:,}").unwrap();
        assert!(!model.rows[1].confirmed);
        assert_eq!(
            model
                .preview(record.as_object().unwrap(), Some(now))
                .unwrap()["금액"],
            "21,326,800"
        );
        let mut partition = suggested(
            &[
                ("공고명", "text"),
                ("추정가격", "text"),
                ("여백", "text"),
                ("비고", "text"),
            ],
            &[],
        );
        partition.set_source(0, "bidNtceNm").unwrap();
        partition.set_source(1, "presmptPrce").unwrap();
        let record = json!({"bidNtceNm":"테스트 공고"});
        assert_eq!(
            partition
                .preview_counts(record.as_object().unwrap(), None)
                .unwrap(),
            (1, 1, 2)
        );
        assert_eq!(
            partition
                .preview_empties(record.as_object().unwrap(), None)
                .unwrap(),
            ["추정가격"]
        );
        assert_eq!(
            partition
                .preview(record.as_object().unwrap(), None)
                .unwrap()["여백"],
            ""
        );
        assert_eq!(
            partition
                .name_token_values(record.as_object().unwrap(), None)
                .len(),
            2
        );
        assert_eq!(partition.live_profile("").unwrap().mappings.len(), 2);
        assert!(model.rows[0].has_content() && !model.rows[0].is_declared_empty());
        assert_eq!(
            model
                .to_profile("")
                .unwrap()
                .apply(record.as_object().unwrap(), Some(now))
                .unwrap()["작성일"],
            "2026년 6월 15일 18:04"
        );
    }

    #[test]
    fn token_names_bind_exact_columns_and_offer_unused_approximate_choices() {
        let mut model = EditorMappingModel::from_field_names(
            &strings(&["계약명", "계약금액", "완료일자", "착수일"]),
            &strings(&["계약명", "계약금액", "착수예정일", "비고"]),
            &HashMap::new(),
            &HashMap::from([
                ("계약명".into(), "text".into()),
                ("계약금액".into(), "amount".into()),
            ]),
        );
        assert!(
            model.rows[..2]
                .iter()
                .all(|row| row.confirmed && row.auto_confirmed_exact)
        );
        assert_eq!(
            model
                .rows
                .iter()
                .map(|row| row.field_type.as_str())
                .collect::<Vec<_>>(),
            ["text", "amount", "date", "text"]
        );
        assert!(
            model.rows[2..]
                .iter()
                .all(|row| row.source.is_empty() && !row.confirmed)
        );
        assert_eq!(model.suggestions().get("착수일").unwrap(), "착수예정일");
        assert_eq!(model.unused_source_fields(), ["착수예정일", "비고"]);
        model
            .bind_column(model.index_of("착수일").unwrap(), "착수예정일", "date")
            .unwrap();
        assert!(
            !model
                .suggestions()
                .values()
                .any(|name| name == "착수예정일")
        );
        assert_eq!(model.unused_source_fields(), ["비고"]);
        for index in 0..2 {
            model.set_manual(index, "직접 입력").unwrap();
            model.set_confirmed(index, true).unwrap();
            model.set_const(index, "수정").unwrap();
            assert!(!model.rows[index].confirmed);
        }
        assert_eq!(model.counts().2, 2);
    }
}
