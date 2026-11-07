//! Read-only authoring tab projections: outline, problems, trial state.

use super::{
    AuthoringSession, GraphError, digest, location_label, projected_problems, python_json_sorted,
    section_entries,
};
use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_filler::hwpx_authoring_search::stray_token_problems;
use hwpx_filler::template_authoring::authoring_lint;
use serde_json::{Value, json};
use std::collections::HashMap;

fn sections(session: &AuthoringSession) -> Result<HashMap<String, usize>, GraphError> {
    if session.media != "hwpx" {
        return Ok(HashMap::new());
    }
    let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
    Ok(section_entries(&package)?
        .into_iter()
        .enumerate()
        .map(|(at, name)| (name, at))
        .collect())
}
fn position(media: &str, location: &Value, rank: &HashMap<String, usize>) -> Option<(usize, u64)> {
    if !location.is_object() {
        return None;
    }
    if media == "hwpx" {
        let first = location["cell_path"]
            .as_array()
            .and_then(|steps| steps.first())
            .and_then(|step| step["parent_paragraph"].as_u64())
            .or_else(|| location["start_paragraph"].as_u64())
            .or_else(|| location["paragraph"].as_u64())?;
        let entry = location["entry"]
            .as_str()
            .and_then(|name| rank.get(name).copied())
            .unwrap_or(rank.len());
        Some((entry, first))
    } else {
        Some((0, location["start"].as_u64()?))
    }
}
fn inside(location: &Value, entry: &Value, paragraph: u64) -> bool {
    location["entry"] == *entry
        && location["start_paragraph"]
            .as_u64()
            .is_some_and(|lo| lo <= paragraph)
        && location["end_paragraph"]
            .as_u64()
            .is_some_and(|hi| paragraph <= hi)
}

enum OrderTarget {
    Slot(usize),
    Option(usize, usize),
    Occurrence(usize, usize),
}
pub(super) fn outline(session: &AuthoringSession) -> Result<Value, GraphError> {
    let mut analysis = session.analysis.clone();
    let rank = sections(session)?;
    if session.media == "hwpx" {
        annotate_field_owners(&mut analysis);
    }
    label_regions(&mut analysis, &session.media);
    order_outline(&mut analysis, &session.media, &rank);
    Ok(analysis)
}

fn annotate_field_owners(analysis: &mut Value) {
    let slots = analysis["slots"].as_array().cloned().unwrap_or_default();
    for field in analysis["fields"].as_array_mut().into_iter().flatten() {
        for occurrence in field["occurrences"].as_array_mut().into_iter().flatten() {
            let (owner, choice) = occurrence["anchor_paragraph"]
                .as_u64()
                .map_or((None, None), |anchor| {
                    field_owner(&slots, occurrence, anchor)
                });
            occurrence["slot_id"] = json!(owner);
            occurrence["option_id"] = json!(choice);
        }
    }
}

fn field_owner(
    slots: &[Value],
    occurrence: &Value,
    anchor: u64,
) -> (Option<String>, Option<String>) {
    let owners: Vec<_> = slots
        .iter()
        .filter(|slot| inside(&slot["location"], &occurrence["entry"], anchor))
        .collect();
    if owners.len() != 1 {
        return (None, None);
    }
    let options: Vec<_> = owners[0]["options"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|option| inside(&option["location"], &occurrence["entry"], anchor))
        .collect();
    (
        owners[0]["id"].as_str().map(str::to_owned),
        if options.len() == 1 {
            options[0]["id"].as_str().map(str::to_owned)
        } else {
            None
        },
    )
}

fn label_regions(analysis: &mut Value, media: &str) {
    if let Some(slots) = analysis["slots"].as_array_mut() {
        for slot in slots {
            slot["location_label"] =
                location_label(media, &slot["location"]).map_or(Value::Null, Value::String);
            if let Some(options) = slot["options"].as_array_mut() {
                for option in options {
                    option["location_label"] = location_label(media, &option["location"])
                        .map_or(Value::Null, Value::String);
                }
            }
        }
    }
}

fn order_outline(analysis: &mut Value, media: &str, rank: &HashMap<String, usize>) {
    let mut order = Vec::new();
    let mut sequence = 0usize;
    let mut add = |location: &Value, rank_kind: usize, extra: u64, target: OrderTarget| {
        let place = position(media, location, rank);
        order.push((
            place.is_none() as usize,
            place.unwrap_or((0, 0)).0,
            place.unwrap_or((0, 0)).1,
            rank_kind,
            extra,
            sequence,
            target,
        ));
        sequence += 1;
    };
    for (slot_at, slot) in analysis["slots"]
        .as_array()
        .into_iter()
        .flatten()
        .enumerate()
    {
        add(&slot["location"], 0, 0, OrderTarget::Slot(slot_at));
        for (option_at, option) in slot["options"].as_array().into_iter().flatten().enumerate() {
            add(
                &option["location"],
                1,
                0,
                OrderTarget::Option(slot_at, option_at),
            );
        }
    }
    for (field_at, field) in analysis["fields"]
        .as_array()
        .into_iter()
        .flatten()
        .enumerate()
    {
        for (occurrence_at, occurrence) in field["occurrences"]
            .as_array()
            .into_iter()
            .flatten()
            .enumerate()
        {
            let (location, extra) = occurrence_position(media, occurrence);
            add(
                &location,
                2,
                extra,
                OrderTarget::Occurrence(field_at, occurrence_at),
            );
        }
    }
    order.sort_by_key(|row| (row.0, row.1, row.2, row.3, row.4, row.5));
    for (ordinal, (_, _, _, _, _, _, target)) in order.into_iter().enumerate() {
        match target {
            OrderTarget::Slot(si) => analysis["slots"][si]["order"] = json!(ordinal),
            OrderTarget::Option(si, oi) => {
                analysis["slots"][si]["options"][oi]["order"] = json!(ordinal)
            }
            OrderTarget::Occurrence(fi, oi) => {
                analysis["fields"][fi]["occurrences"][oi]["order"] = json!(ordinal)
            }
        }
    }
}

fn occurrence_position(media: &str, occurrence: &Value) -> (Value, u64) {
    if media != "hwpx" {
        return (occurrence.clone(), 0);
    }
    let location = if occurrence["anchor_paragraph"].as_u64().is_some() {
        json!({"entry":occurrence["entry"],"start_paragraph":occurrence["anchor_paragraph"]})
    } else {
        Value::Null
    };
    (location, occurrence["occurrence"].as_u64().unwrap_or(0))
}

pub(super) fn problems(session: &AuthoringSession) -> Result<Vec<Value>, GraphError> {
    let mut found = session.analysis["diagnostics"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    found.extend(authoring_lint(&session.media, &session.analysis));
    if session.media == "hwpx" {
        let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
        found.extend(stray_token_problems(&package)?);
    }
    let rank = if found.iter().any(|item| item["location"].is_object()) {
        sections(session)?
    } else {
        HashMap::new()
    };
    let mut rows: Vec<_> = found.into_iter().enumerate().collect();
    rows.sort_by_key(|(index, item)| {
        let place = position(&session.media, &item["location"], &rank);
        let start = if session.media == "hwpx" {
            item["location"]["start"].as_i64()
        } else {
            None
        };
        (
            place.is_none() as usize,
            place.unwrap_or((0, 0)).0,
            place.unwrap_or((0, 0)).1,
            start.unwrap_or(-1),
            *index,
        )
    });
    let mut ordered: Vec<Value> = rows.into_iter().map(|(_, item)| item).collect();
    if session.rhwp_editable == Some(false) {
        ordered.push(json!({"severity":"warning","category":"compatibility",
            "message":"이 요소는 표시할 수 있지만 변경 후 보존을 확인할 수 없습니다. 원본을 유지한 채 확인하세요.",
            "target":null,"location":null,"actions":[]}));
        for item in &session.rhwp_diagnostics {
            ordered.push(json!({"severity":"warning","category":"compatibility",
                "message":item["message"].as_str().unwrap_or(""),"target":item["entry"],
                "location":null,"actions":[]}));
        }
    }
    Ok(ordered)
}

pub(super) fn trial_missing(analysis: &Value, session: &AuthoringSession) -> Value {
    let mut fields: Vec<_> = analysis["fields"]
        .as_array()
        .into_iter()
        .flatten()
        .enumerate()
        .collect();
    fields.sort_by_key(|(index, field)| {
        let first = field["occurrences"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|row| row["order"].as_u64())
            .min();
        (first.is_none(), first.unwrap_or(0), *index)
    });
    let missing: Vec<_> = fields
        .into_iter()
        .filter_map(|(_, field)| {
            let name = field["name"].as_str()?;
            session
                .values
                .get(name)
                .is_none_or(Value::is_null)
                .then(|| name.to_owned())
        })
        .collect();
    let mut slots: Vec<_> = analysis["slots"]
        .as_array()
        .into_iter()
        .flatten()
        .enumerate()
        .collect();
    slots.sort_by_key(|(index, slot)| {
        (
            slot["order"].as_u64().is_none(),
            slot["order"].as_u64().unwrap_or(0),
            *index,
        )
    });
    let choices: Vec<_> = slots
        .into_iter()
        .filter_map(|(_, slot)| {
            let options = slot["options"].as_array()?;
            if options.is_empty() {
                return None;
            }
            let id = slot["id"].as_str()?;
            (!options
                .iter()
                .any(|option| session.selected.get(id) == option.get("id")))
            .then(|| id.to_owned())
        })
        .collect();
    json!({"fields":missing,"slots":choices})
}

pub(super) fn trial_coverage(session: &AuthoringSession) -> Vec<Value> {
    let fingerprint = trial_input_fingerprint(session);
    let mut rows = Vec::new();
    for slot in session.analysis["slots"].as_array().into_iter().flatten() {
        for option in slot["options"].as_array().into_iter().flatten() {
            let (Some(slot_id), Some(option_id)) = (slot["id"].as_str(), option["id"].as_str())
            else {
                continue;
            };
            let evidence = session
                .trial_coverage_evidence
                .get(&(slot_id.to_owned(), option_id.to_owned()));
            let state = match evidence {
                None => "untried",
                Some((revision, stored))
                    if *revision == session.revision && *stored == fingerprint =>
                {
                    "current"
                }
                Some(_) => "stale",
            };
            rows.push(json!({"slot_id":slot_id,"option_id":option_id,"state":state}));
        }
    }
    rows
}

pub(super) fn trial_input_fingerprint(session: &AuthoringSession) -> String {
    digest(
        python_json_sorted(&json!({"values":session.values,"selected":session.selected}))
            .as_bytes(),
    )
}

pub(super) fn readiness(session: &AuthoringSession, problems: &[Value]) -> Value {
    let structure = session.analysis["diagnostics"]
        .as_array()
        .into_iter()
        .flatten()
        .any(|item| item["severity"] == "error");
    let errors = problems
        .iter()
        .filter(|item| item["severity"] == "error")
        .count();
    let warnings = problems
        .iter()
        .filter(|item| item["severity"] == "warning")
        .count();
    json!({"state":if structure{"draft"}else{"ready"},"errors":errors,"warnings":warnings,
        "message":if structure{Some(format!("사용 전에 구조 오류 {errors}개를 확인하세요."))}else{None}})
}

pub(super) fn problems_here(
    session: &mut AuthoringSession,
    selection: &Value,
) -> Result<Vec<usize>, GraphError> {
    let (Some(start), Some(end)) = (selection["start"].as_u64(), selection["end"].as_u64()) else {
        return Ok(Vec::new());
    };
    let problems = projected_problems(session)?;
    let text = if session.media == "txt" {
        Some(std::str::from_utf8(&session.content)?)
    } else {
        None
    };
    let found = problems
        .into_iter()
        .enumerate()
        .filter_map(|(index, problem)| {
            let location = problem.get("location")?.as_object()?;
            let hit = text.map_or_else(
                || problem_hit_hwpx(selection, location, start, end),
                |text| problem_hit_txt(text, location, start, end),
            );
            hit.then_some(index)
        })
        .collect();
    Ok(found)
}

fn problem_hit_txt(
    text: &str,
    location: &serde_json::Map<String, Value>,
    start: u64,
    end: u64,
) -> bool {
    let (Some(low), Some(high)) = (
        location.get("start").and_then(Value::as_u64),
        location.get("end").and_then(Value::as_u64),
    ) else {
        return false;
    };
    if start != end {
        return low < end && start < high;
    }
    if low <= start && start < high {
        return true;
    }
    if start != high || high <= low {
        return false;
    }
    super::utf16_index(text, high).is_some_and(|at| {
        at > 0
            && text
                .chars()
                .nth(at - 1)
                .is_some_and(|ch| ch != '\r' && ch != '\n')
    })
}

fn problem_hit_hwpx(
    selection: &Value,
    location: &serde_json::Map<String, Value>,
    start: u64,
    end: u64,
) -> bool {
    let first = selection
        .get("start_paragraph")
        .or_else(|| selection.get("paragraph"))
        .and_then(Value::as_u64);
    let last = selection
        .get("end_paragraph")
        .and_then(Value::as_u64)
        .or(first);
    let (Some(entry), Some(first), Some(last)) = (selection["entry"].as_str(), first, last) else {
        return false;
    };
    if last < first
        || location.get("entry").and_then(Value::as_str) != Some(entry)
        || location.get("cell_path") != selection.get("cell_path")
    {
        return false;
    }
    let Some((low_p, high_p)) = problem_paragraph_bounds(location) else {
        return false;
    };
    if !(low_p <= last && first <= high_p) {
        return false;
    }
    if first != last || low_p != high_p {
        return true;
    }
    problem_character_overlap(location, start, end)
}

fn problem_paragraph_bounds(location: &serde_json::Map<String, Value>) -> Option<(u64, u64)> {
    let low = location
        .get("start_paragraph")
        .or_else(|| location.get("paragraph"))?
        .as_u64()?;
    let high = location
        .get("end_paragraph")
        .and_then(Value::as_u64)
        .unwrap_or(low);
    Some((low, high))
}

fn problem_character_overlap(
    location: &serde_json::Map<String, Value>,
    start: u64,
    end: u64,
) -> bool {
    match (
        location.get("start").and_then(Value::as_u64),
        location.get("end").and_then(Value::as_u64),
    ) {
        (Some(low), Some(high)) if start == end => low <= start && start <= high,
        (Some(low), Some(high)) => low < end && start < high,
        _ => true,
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn outline_trial_and_caret_problem_share_observed_positions() {
        let analysis = json!({
            "slots":[{"id":"s","label":"S","location":{"start":0,"end":4,"begin_marker_line":0,"end_marker_line":0},
                "options":[{"id":"a","label":"A","location":{"start":0,"end":4,"begin_marker_line":0,"end_marker_line":0}}]}],
            "fields":[{"name":"F","occurrences":[{"start":1,"end":2}]}],
            "diagnostics":[{"severity":"warning","category":"structure","message":"위치 확인","location":{"start":0,"end":3}}]
        });
        let mut session =
            AuthoringSession::new("one".into(), "txt".into(), b"ABC\n".to_vec(), analysis);
        let outline = outline(&session).expect("TXT outline");
        assert_eq!(outline["slots"][0]["order"], 0);
        assert_eq!(outline["slots"][0]["options"][0]["order"], 1);
        assert_eq!(outline["fields"][0]["occurrences"][0]["order"], 2);
        assert_eq!(
            trial_missing(&outline, &session),
            json!({"fields":["F"],"slots":["s"]})
        );
        assert_eq!(
            problems_here(&mut session, &json!({"start":3,"end":3})).unwrap(),
            vec![0]
        );
        assert!(
            problems_here(&mut session, &json!({"start":4,"end":4}))
                .unwrap()
                .is_empty()
        );
        session.replace_content(
            b"ABCDE\n".to_vec(),
            json!({"slots":[],"fields":[],"diagnostics":[
                {"severity":"warning","category":"structure","message":"새 위치",
                    "location":{"start":4,"end":5}}
            ]}),
        );
        assert!(
            problems_here(&mut session, &json!({"start":3,"end":3}))
                .unwrap()
                .is_empty()
        );
        assert_eq!(
            problems_here(&mut session, &json!({"start":4,"end":4})).unwrap(),
            vec![0]
        );
    }

    #[test]
    fn near_duplicate_warning_precedes_structure_error_and_clears_after_relink() {
        let text = "{{공고명}} {{공고 명}}\n{{#항목 a}}\n본문\n";
        let mut session = AuthoringSession::new(
            "one".into(),
            "txt".into(),
            text.as_bytes().to_vec(),
            hwpx_filler::txt_authoring::analyze(text),
        );
        let found = problems(&session).unwrap();
        assert_eq!(found.len(), 2);
        assert_eq!(
            (found[0]["category"].as_str(), found[0]["severity"].as_str()),
            (Some("authoring"), Some("warning"))
        );
        assert_eq!(
            (found[1]["category"].as_str(), found[1]["severity"].as_str()),
            (Some("structure"), Some("error"))
        );
        assert_eq!(found[0]["target"], "공고 명");
        let command = &found[0]["actions"][1]["command"];
        assert_eq!(command["type"], "relink_field");
        assert_eq!(command["name"], "공고명");
        assert_eq!(readiness(&session, &found)["state"], "draft");
        assert_eq!(
            problems_here(&mut session, &json!({"start":12,"end":12})).unwrap(),
            vec![0]
        );
        let (changed, impact) = hwpx_filler::txt_authoring::apply(text, command).unwrap();
        assert_eq!(impact["before"], "{{공고 명}}");
        assert_eq!(impact["after"], "{{공고명}}");
        session.replace_content(
            changed.as_bytes().to_vec(),
            hwpx_filler::txt_authoring::analyze(&changed),
        );
        assert!(
            problems(&session)
                .unwrap()
                .iter()
                .all(|problem| problem["category"] != "authoring")
        );
    }
}
