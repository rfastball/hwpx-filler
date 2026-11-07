//! HWPX authoring preview through the same native materialization path as delivery.

use crate::execution_contract_set::{PLAN_APPLY_FIELD_BINDING, PLAN_REMOVE_OPTION};
use crate::hwpx_authoring_analysis::{fields, region_location};
use crate::hwpx_product_inspection::inspect_slot_regions;
use crate::hwpx_qualification::inspect_hwpx_qualification;
use crate::hwpx_structure_ops::remove_slot_option;
use crate::materialization_runner::{MaterializationOutcome, materialize_authoring_trial};
use crate::txt_authoring::trial_document_values;
use hwpx_core::package::{HwpxPackage, PackageLimits};
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AuthoringTrialError(pub String);
impl fmt::Display for AuthoringTrialError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for AuthoringTrialError {}
fn fail(detail: impl Into<String>) -> AuthoringTrialError {
    AuthoringTrialError(detail.into())
}
#[derive(Clone, Debug, PartialEq)]
pub struct HwpxTrial {
    pub bytes: Vec<u8>,
    pub excluded: Vec<Value>,
    pub occurrences: Vec<Value>,
    pub report: Value,
}
fn field_names(fields: &[Value]) -> Vec<String> {
    fields
        .iter()
        .filter_map(|row| row["name"].as_str().map(str::to_owned))
        .collect()
}
fn logical_values(
    names: &[String],
    values: &Map<String, Value>,
) -> (HashMap<String, String>, Vec<String>) {
    let (logical, empty) = trial_document_values(names, values);
    (
        logical
            .into_iter()
            .filter_map(|(key, value)| value.as_str().map(|text| (key, text.to_owned())))
            .collect(),
        empty,
    )
}
fn provenance(
    source_fields: &[Value],
    output_fields: &[Value],
    values: &Map<String, Value>,
) -> Vec<Value> {
    let sources: HashMap<(String, String), &Value> = source_fields
        .iter()
        .flat_map(|field| field["occurrences"].as_array().into_iter().flatten())
        .filter_map(|occurrence| {
            Some((
                (
                    occurrence["entry"].as_str()?.to_owned(),
                    occurrence["pairing_id"].as_str()?.to_owned(),
                ),
                occurrence,
            ))
        })
        .collect();
    let (output_values, _) = logical_values(&field_names(output_fields), values);
    let mut rows = Vec::new();
    for field in output_fields {
        let name = field["name"].as_str().unwrap_or("");
        for occurrence in field["occurrences"].as_array().into_iter().flatten() {
            let key = (
                occurrence["entry"].as_str().unwrap_or("").to_owned(),
                occurrence["pairing_id"].as_str().unwrap_or("").to_owned(),
            );
            rows.push(json!({
                "name": name,
                "value": output_values.get(name),
                "source": sources.get(&key).copied().unwrap_or(occurrence),
                "output": occurrence,
            }));
        }
    }
    rows
}

/// Options the trial leaves out, each with why; every optioned slot needs a choice
/// and every chosen slot must exist.
fn excluded_options(
    snapshot: &crate::hwpx_product_inspection::SlotSnapshot,
    selected: &HashMap<String, String>,
) -> Result<Vec<Value>, AuthoringTrialError> {
    let mut excluded = Vec::new();
    let mut known_slots = HashSet::new();
    for slot in &snapshot.slots {
        known_slots.insert(slot.id.as_str());
        let choice = selected.get(&slot.id).map(String::as_str);
        let chosen = slot
            .options
            .iter()
            .find(|option| Some(option.id.as_str()) == choice);
        if !slot.options.is_empty() && chosen.is_none() {
            return Err(fail(format!(
                "'{}' 항목의 시험 선택을 지정하세요.",
                slot.id
            )));
        }
        for option in &slot.options {
            if Some(option.id.as_str()) == choice {
                continue;
            }
            let selected_option = chosen.expect("nonempty options checked above");
            let chosen_label = selected_option
                .label
                .as_deref()
                .unwrap_or(&selected_option.id);
            let removed_label = option.label.as_deref().unwrap_or(&option.id);
            let region = snapshot
                .option_regions
                .get(&(slot.id.clone(), option.id.clone()));
            excluded.push(json!({
                "slot_id": slot.id,
                "option_id": option.id,
                "selected_option_id": choice,
                "label": removed_label,
                "reason": format!("현재 시험에서 '{chosen_label}'을 골라 '{removed_label}'은 제외되었습니다."),
                "source": region_location(region),
            }));
        }
    }
    if selected
        .keys()
        .any(|slot| !known_slots.contains(slot.as_str()))
    {
        return Err(fail("존재하지 않는 항목 선택이 있습니다."));
    }
    Ok(excluded)
}

/// The materialization plan: remove the excluded options, then bind every field,
/// with the occurrence count each field must keep.
fn trial_plan(excluded: &[Value], selected_fields: &[Value]) -> (Vec<Value>, Vec<Value>) {
    let mut operations: Vec<Value> = excluded
        .iter()
        .map(|item| {
            json!({"op":PLAN_REMOVE_OPTION,"slot_id":item["slot_id"],"option_id":item["option_id"]})
        })
        .collect();
    operations.extend(
        selected_fields
            .iter()
            .map(|field| json!({"op":PLAN_APPLY_FIELD_BINDING,"field_id":field["name"]})),
    );
    let requirements: Vec<Value> = selected_fields
        .iter()
        .map(|field| {
            json!({"field_id":field["name"],"expected_active_occurrence_count":field["count"]})
        })
        .collect();
    (operations, requirements)
}

pub fn trial_hwpx(
    package: &HwpxPackage,
    values: &Map<String, Value>,
    selected: &HashMap<String, String>,
) -> Result<HwpxTrial, AuthoringTrialError> {
    let source_bytes = package
        .to_bytes()
        .map_err(|error| fail(error.to_string()))?;
    let source_fields = fields(package).map_err(|error| fail(error.to_string()))?;
    let snapshot = inspect_slot_regions(package).map_err(|error| fail(error.to_string()))?;
    if !snapshot.diagnostics.is_empty() {
        return Err(fail("문서 구조 오류를 수정한 뒤 결과를 시험하세요."));
    }
    let excluded = excluded_options(&snapshot, selected)?;
    let mut chosen = HwpxPackage::from_bytes(&source_bytes, PackageLimits::default())
        .map_err(|error| fail(error.to_string()))?;
    for item in excluded.iter().rev() {
        remove_slot_option(
            &mut chosen,
            item["slot_id"].as_str().unwrap_or(""),
            item["option_id"].as_str().unwrap_or(""),
        )
        .map_err(|error| fail(error.to_string()))?;
    }
    let selected_fields = fields(&chosen).map_err(|error| fail(error.to_string()))?;
    let (logical, empty_fields) = logical_values(&field_names(&selected_fields), values);
    let qualification =
        inspect_hwpx_qualification(&source_bytes).map_err(|error| fail(error.to_string()))?;
    let structure = qualification
        .execution_structure
        .ok_or_else(|| fail("문서 구조 오류를 수정한 뒤 결과를 시험하세요."))?;
    let (operations, requirements) = trial_plan(&excluded, &selected_fields);
    let materialized = materialize_authoring_trial(
        &source_bytes,
        &structure,
        &operations,
        &requirements,
        &logical,
    )
    .map_err(|error| fail(error.to_string()))?;
    let materialized = match materialized {
        MaterializationOutcome::Materialized(materialized) => materialized,
        MaterializationOutcome::Failure(
            crate::materialization_conformance::ConformanceResult::Failure { detail, .. },
        ) => return Err(fail(format!("결과 시험 검증에 실패했습니다: {detail}"))),
        MaterializationOutcome::Failure(_) => unreachable!(),
    };
    let output = HwpxPackage::from_bytes(&materialized.output_bytes, PackageLimits::default())
        .map_err(|error| fail(error.to_string()))?;
    let output_fields = fields(&output).map_err(|error| fail(error.to_string()))?;
    Ok(HwpxTrial {
        occurrences: provenance(&source_fields, &output_fields, values),
        bytes: materialized.output_bytes,
        excluded,
        report: json!({"missing_fields":[],"empty_fields":empty_fields}),
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::hwpx_authoring_availability::available_commands_hwpx;
    use crate::hwpx_authoring_fields::create_field;
    use hwpx_core::package::{MIMETYPE_NAME, MIMETYPE_VALUE, PackageEntry};
    use hwpx_core::xml_view::XmlView;

    #[test]
    fn trial_fills_a_field_without_mutating_the_source_package() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{}'><hp:p><hp:run><hp:ctrl><hp:fieldBegin id='1' name='이름'/></hp:ctrl></hp:run><hp:run><hp:t>OLD</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl></hp:run></hp:p></hs:sec>",
            hwpx_core::text_model::HP_NS
        );
        let package = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: MIMETYPE_NAME.into(),
                    data: MIMETYPE_VALUE.into(),
                    stored: true,
                },
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: xml.into_bytes(),
                    stored: false,
                },
            ],
        };
        let before = package.clone();
        let result = trial_hwpx(
            &package,
            &Map::from_iter([("이름".into(), json!("새 값"))]),
            &HashMap::new(),
        )
        .unwrap();
        assert_eq!(package, before);
        assert_eq!(result.report["empty_fields"], json!([]));
        let output = HwpxPackage::from_bytes(&result.bytes, PackageLimits::default()).unwrap();
        let text = String::from_utf8(output.entries[1].data.clone()).unwrap();
        assert!(text.contains("새 값"));
        assert_eq!(result.occurrences[0]["name"], "이름");
    }

    #[test]
    fn adjacent_field_creation_keeps_content_and_trial_values_separate() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{}'><hp:p><hp:run charPrIDRef='7'><hp:t>앞 원문 전화 팩스 뒤</hp:t></hp:run></hp:p></hs:sec>",
            hwpx_core::text_model::HP_NS
        );
        let mut package = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: MIMETYPE_NAME.into(),
                    data: MIMETYPE_VALUE.into(),
                    stored: true,
                },
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: xml.into_bytes(),
                    stored: false,
                },
            ],
        };
        let original = package.clone();
        for (start, end, name, captured) in [
            (2, 4, "내용", "원문"),
            (5, 7, "전화", "전화"),
            (8, 10, "팩스", "팩스"),
            (0, 2, "머리", "앞 "),
        ] {
            let command = json!({"entry":"Contents/section0.xml",
                "paragraph":0,"start":start,"end":end,"name":name});
            let verdict = available_commands_hwpx(&package, &command, None)
                .unwrap()
                .into_iter()
                .find(|row| row["type"] == "create_field")
                .unwrap();
            assert_eq!(verdict["enabled"], true);
            assert_eq!(create_field(&mut package, &command).unwrap(), captured);
        }
        let before_overlap = package.clone();
        for (start, end) in [(2, 3), (1, 5), (3, 3)] {
            assert!(
                create_field(
                    &mut package,
                    &json!({"entry":"Contents/section0.xml","paragraph":0,
                        "start":start,"end":end,"name":"겹침"})
                )
                .is_err()
            );
            assert_eq!(package, before_overlap);
        }
        let output = trial_hwpx(
            &package,
            &Map::from_iter([
                ("머리".into(), json!("첫 ")),
                ("내용".into(), json!("새값")),
                ("전화".into(), json!("02-123")),
                ("팩스".into(), json!("02-456")),
            ]),
            &HashMap::new(),
        )
        .unwrap();
        assert_eq!(output.report["missing_fields"], json!([]));
        assert_eq!(output.occurrences.len(), 4);
        let rendered = HwpxPackage::from_bytes(&output.bytes, PackageLimits::default()).unwrap();
        let view = XmlView::parse(&rendered.entries[1].data).unwrap();
        let text = view
            .descendants(view.root())
            .unwrap()
            .into_iter()
            .filter(|id| {
                let name = &view.node(*id).unwrap().name;
                name.namespace == hwpx_core::text_model::HP_NS && name.local == "t"
            })
            .map(|id| view.direct_text(id).unwrap())
            .collect::<String>();
        assert_eq!(text, "첫 새값 02-123 02-456 뒤");
        assert_ne!(original, package);
        assert_eq!(package, before_overlap);
    }
}
