//! Search, target location, and syntax projections for authoring.

use super::*;

impl AuthoringController {
    pub(super) fn locate_target(
        &self,
        session: &AuthoringSession,
        target: &Value,
        selection: &Value,
    ) -> Result<Value, GraphError> {
        let kind = target["kind"].as_str().unwrap_or("");
        let parts = match kind {
            "field" | "occurrence" => field_target(session, target, selection, kind),
            "slot" | "option" => region_target(session, target, kind),
            _ => None,
        };
        let Some((selected, matched, location, slot_id, option_id, name)) = parts else {
            return Ok(invalid_locate());
        };
        let commands = if session.media == "txt" {
            txt_authoring::available_target_commands(
                std::str::from_utf8(&session.content)?,
                kind,
                name.as_deref(),
            )?
        } else {
            let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
            available_target_commands_hwpx(&package, kind, name.as_deref())?
        };
        let span = target_span(session, kind, &location);
        let (owner_slot, owner_option) = if matches!(kind, "field" | "occurrence") {
            (slot_id.as_deref(), option_id.as_deref())
        } else if kind == "option" {
            (slot_id.as_deref(), None)
        } else {
            (None, None)
        };
        Ok(json!({"selected":selected,"matches":[matched],
            "context":{"slot_id":slot_id,"option_id":option_id,
                "reason":if slot_id.is_some(){""}else{"고른 위치가 교체 묶음 안에 없습니다."},
                "location_label":context_label(session,owner_slot,owner_option,&span)},
            "commands":commands}))
    }
    pub(super) fn locate_selection(
        &self,
        session: &mut AuthoringSession,
        selection: &Value,
    ) -> Result<Value, GraphError> {
        let Some(range) = SelectionRange::new(session, selection)? else {
            return Ok(invalid_locate());
        };
        let native = range.native;
        let mut matches = selection_field_matches(session, &range);
        let (slot_matches, mut owners, choices) = selection_region_matches(session, &range);
        matches.extend(slot_matches);
        let slot_id = if owners.len() == 1 {
            owners.pop()
        } else {
            None
        };
        let option_id =
            if choices.len() == 1 && choices[0].0 == slot_id.clone().unwrap_or(Value::Null) {
                Some(choices[0].1.clone())
            } else {
                None
            };
        let span = selection_span(session, &range)?;
        let found = selected_context(session, selection, &range)?;
        let existing: Vec<_> = session.analysis["fields"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|field| field["name"].as_str().map(str::to_owned))
            .collect();
        let suggested = found.as_ref().and_then(|(before, focus)| {
            txt_authoring::suggest_field_name(before, focus, &existing)
        });
        let commands = if native {
            let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
            available_commands_hwpx(
                &package,
                selection,
                Some(&json!({"slot_id":slot_id,"option_id":option_id})),
            )?
        } else {
            txt_authoring::available_commands(
                std::str::from_utf8(&session.content)?,
                selection,
                Some(&json!({"slot_id":slot_id,"option_id":option_id})),
            )
        };
        Ok(
            json!({"matches":matches,"context":{"slot_id":slot_id,"option_id":option_id,
            "reason":if slot_id.is_some(){""}else{"고른 위치가 교체 묶음 안에 없습니다."},
            "location_label":context_label(session,slot_id.as_ref().and_then(Value::as_str),
                option_id.as_ref().and_then(Value::as_str),&span),
            "selected_text":found.as_ref().map(|item|&item.1),"name_suggestion":suggested},
            "commands":commands,"problems_here":projection::problems_here(session,selection)?}),
        )
    }
    pub(super) fn dispatch_location(
        &self,
        state: &mut AuthoringState,
        action: &str,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        match action {
            "commands" => self.action_commands(state, payload),
            "search" => self.action_search(state, payload),
            "same_text" => self.action_same_text(state, payload),
            "syntax" => self.action_syntax(state, payload),
            "locate" => self.action_locate(state, payload),
            _ => unreachable!(),
        }
    }
    fn action_commands(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session(payload, true)?;
        let selection = payload
            .get("selection")
            .filter(|value| value.is_object())
            .ok_or("고른 위치가 올바르지 않습니다.")?;
        let context = payload.get("context").filter(|value| value.is_object());
        let commands = if session.media == "txt" {
            txt_authoring::available_commands(
                std::str::from_utf8(&session.content)?,
                selection,
                context,
            )
        } else {
            let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
            available_commands_hwpx(&package, selection, context)?
        };
        Ok(json!({"commands":commands}))
    }
    fn action_same_text(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session(payload, true)?;
        let Some(selection) = clean_selection(payload.get("selection"))? else {
            return Ok(search_result(Vec::new()));
        };
        let mut hits = if session.media == "txt" {
            txt_authoring::same_text_sites(std::str::from_utf8(&session.content)?, &selection)
        } else {
            let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
            same_text_hwpx(&package, &selection)?
        };
        for hit in &mut hits {
            let position = if session.media == "txt" {
                hit.as_object_mut().and_then(|map| map.remove("line"))
            } else {
                hit.as_object_mut().and_then(|map| map.remove("anchor"))
            };
            let position = position.unwrap_or(Value::Null);
            hit["kind"] = json!("text");
            hit["location_label"] = location_label(
                &session.media,
                &if session.media == "txt" {
                    json!({"begin_marker_line":position,"end_marker_line":position})
                } else {
                    json!({"start_paragraph":position,"end_paragraph":position})
                },
            )
            .map_or(Value::Null, Value::String);
        }
        Ok(search_result(hits))
    }
    fn action_syntax(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session(payload, false)?;
        if session.media == "txt" {
            return Ok(
                json!({"sections":[{"entry":"","text":std::str::from_utf8(&session.content)?}],"note":null}),
            );
        }
        let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
        Ok(syntax_view_hwpx(&package)?)
    }
    fn action_locate(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        let selection = payload
            .get("selection")
            .filter(|value| value.is_object())
            .ok_or("고른 위치가 올바르지 않습니다.")?;
        if let Some(target) = payload.get("target").filter(|value| !value.is_null()) {
            if !target.is_object() {
                return Err(fail("액션 입력이 올바르지 않습니다."));
            }
            let mut result = self.locate_target(session, target, selection)?;
            result["problems_here"] = json!([]);
            Ok(result)
        } else {
            self.locate_selection(session, selection)
        }
    }
}

fn target_span(session: &AuthoringSession, kind: &str, location: &Value) -> Value {
    if kind == "field" {
        Value::Null
    } else if kind == "occurrence" && session.media == "txt" {
        json!({"begin_marker_line":location["line"],"end_marker_line":location["line"]})
    } else if kind == "occurrence" {
        json!({"start_paragraph":location["anchor_paragraph"],"end_paragraph":location["anchor_paragraph"]})
    } else {
        location.clone()
    }
}

type TargetParts = (
    Value,
    Value,
    Value,
    Option<String>,
    Option<String>,
    Option<String>,
);

fn field_target(
    session: &AuthoringSession,
    target: &Value,
    selection: &Value,
    kind: &str,
) -> Option<TargetParts> {
    Some({
        let name = target["name"].as_str()?;
        let field = session.analysis["fields"]
            .as_array()
            .into_iter()
            .flatten()
            .find(|item| item["name"] == name)?;
        let occurrences = field["occurrences"].as_array().cloned().unwrap_or_default();
        let location = if kind == "field" {
            occurrences.first().cloned().unwrap_or(Value::Null)
        } else {
            const KEYS: [&str; 7] = [
                "entry",
                "occurrence",
                "pairing_id",
                "paragraph",
                "cell_path",
                "start",
                "end",
            ];
            let found: Vec<_> = occurrences
                .iter()
                .filter(|item| {
                    KEYS.iter().any(|key| item.get(*key).is_some())
                        && KEYS.iter().all(|key| {
                            item.get(*key)
                                .is_none_or(|value| selection.get(*key) == Some(value))
                        })
                })
                .collect();
            if found.len() != 1 {
                return None;
            }
            found[0].clone()
        };
        let mut selected = if kind == "field" {
            field.clone()
        } else {
            location.clone()
        };
        selected["kind"] = json!("field");
        if kind == "occurrence" {
            selected["name"] = json!(name);
        }
        let (slot_id, option_id) = if kind == "occurrence" && session.media == "txt" {
            (
                location["slot_id"].as_str().map(str::to_owned),
                location["option_id"].as_str().map(str::to_owned),
            )
        } else {
            (None, None)
        };
        (
            selected,
            json!({"kind":"field","name":name,"location":location,"source":location}),
            location,
            slot_id,
            option_id,
            Some(name.into()),
        )
    })
}

fn region_target(session: &AuthoringSession, target: &Value, kind: &str) -> Option<TargetParts> {
    Some({
        let slot = session.analysis["slots"]
            .as_array()
            .into_iter()
            .flatten()
            .find(|item| item.get("id") == target.get("slot_id"))?;
        let option = if kind == "option" {
            slot["options"]
                .as_array()
                .into_iter()
                .flatten()
                .find(|item| item.get("id") == target.get("option_id"))
        } else {
            None
        };
        if kind == "option" && option.is_none() {
            return None;
        }
        let item = option.unwrap_or(slot);
        let location = item.get("location").cloned().unwrap_or(Value::Null);
        let mut selected = item.clone();
        if let (Some(map), Some(place)) = (selected.as_object_mut(), location.as_object()) {
            map.extend(place.clone());
        }
        selected["kind"] = json!(kind);
        selected["slot_id"] = slot["id"].clone();
        if let Some(option) = option {
            selected["option_id"] = option["id"].clone();
        }
        let slot_id = slot["id"].as_str().map(str::to_owned);
        let option_id = option.and_then(|item| item["id"].as_str().map(str::to_owned));
        let mut matched = json!({"kind":kind,"slot_id":slot["id"],"label":item["label"].as_str()
                    .filter(|value|!value.is_empty()).or_else(||item["id"].as_str()).unwrap_or(""),"location":location});
        if option.is_some() {
            matched["option_id"] = item["id"].clone();
        }
        (selected, matched, location, slot_id, option_id, None)
    })
}

struct SelectionRange<'a> {
    native: bool,
    start: u64,
    end: u64,
    entry: Option<&'a str>,
    first: Option<u64>,
    last: Option<u64>,
    cell_path: Option<&'a Value>,
}

impl<'a> SelectionRange<'a> {
    fn new(session: &AuthoringSession, selection: &'a Value) -> Result<Option<Self>, GraphError> {
        let (Some(start), Some(end)) = (selection["start"].as_u64(), selection["end"].as_u64())
        else {
            return Ok(None);
        };
        let native = session.media == "hwpx";
        let entry = selection["entry"].as_str();
        let first = selection
            .get("start_paragraph")
            .or_else(|| selection.get("paragraph"))
            .and_then(Value::as_u64);
        let last = selection
            .get("end_paragraph")
            .and_then(Value::as_u64)
            .or(first);
        if native && !valid_native_selection(session, entry, first, last)? {
            return Ok(None);
        }
        if (!native || first == last) && end < start {
            return Ok(None);
        }
        let cell_path = selection.get("cell_path");
        if cell_path.is_some() && clean_selection(Some(selection)).is_err() {
            return Ok(None);
        }
        Ok(Some(Self {
            native,
            start,
            end,
            entry,
            first,
            last,
            cell_path,
        }))
    }

    fn hit(&self, place: &Value) -> bool {
        if !place.is_object() {
            return false;
        }
        if self.native {
            self.hit_hwpx(place)
        } else {
            self.hit_txt(place)
        }
    }

    fn hit_hwpx(&self, place: &Value) -> bool {
        if self.cell_path.is_some() || place["entry"].as_str() != self.entry {
            return false;
        }
        let (Some(low), Some(high)) = (
            place["start_paragraph"].as_u64(),
            place["end_paragraph"].as_u64(),
        ) else {
            return false;
        };
        low <= self.last.unwrap_or(0) && self.first.unwrap_or(0) <= high
    }

    fn hit_txt(&self, place: &Value) -> bool {
        let (Some(low), Some(high)) = (place["start"].as_u64(), place["end"].as_u64()) else {
            return false;
        };
        if self.start == self.end {
            low <= self.start && self.start <= high
        } else {
            low < self.end && self.start < high
        }
    }

    fn contains(&self, place: &Value) -> bool {
        if !self.hit(place) {
            return false;
        }
        if self.native {
            place["start_paragraph"]
                .as_u64()
                .is_some_and(|low| low <= self.first.unwrap_or(0))
                && place["end_paragraph"]
                    .as_u64()
                    .is_some_and(|high| self.last.unwrap_or(0) <= high)
        } else {
            place["start"].as_u64().is_some_and(|low| low <= self.start)
                && place["end"].as_u64().is_some_and(|high| self.end <= high)
        }
    }
}

fn valid_native_selection(
    session: &AuthoringSession,
    entry: Option<&str>,
    first: Option<u64>,
    last: Option<u64>,
) -> Result<bool, GraphError> {
    let (Some(entry), Some(first), Some(last)) = (entry, first, last) else {
        return Ok(false);
    };
    if last < first {
        return Ok(false);
    }
    let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
    Ok(section_entries(&package)?.iter().any(|name| name == entry))
}

fn selection_field_matches(session: &AuthoringSession, range: &SelectionRange<'_>) -> Vec<Value> {
    let mut matches = Vec::new();
    for field in session.analysis["fields"].as_array().into_iter().flatten() {
        for occurrence in field["occurrences"].as_array().into_iter().flatten() {
            if let Some(approximate) = field_occurrence_hit(range, occurrence) {
                let mut row = json!({"kind":"field","name":field["name"],"location":occurrence,"source":occurrence});
                if approximate {
                    row["approximate"] = json!(true);
                }
                matches.push(row);
            }
        }
    }
    matches
}

fn field_occurrence_hit(range: &SelectionRange<'_>, occurrence: &Value) -> Option<bool> {
    if !range.native {
        return range.hit(occurrence).then_some(false);
    }
    let paragraph = occurrence["paragraph"].as_u64()?;
    let first = range.first.unwrap_or(0);
    let last = range.last.unwrap_or(0);
    if occurrence["entry"].as_str() != range.entry
        || occurrence.get("cell_path") != range.cell_path
        || !(first <= paragraph && paragraph <= last)
    {
        return None;
    }
    let low = occurrence["start"].as_u64();
    let high = occurrence["end"].as_u64();
    if let (Some(low), Some(high)) = (low, high)
        && !field_span_overlaps(range, paragraph, low, high)
    {
        return None;
    }
    Some(low.is_none() || high.is_none())
}

fn field_span_overlaps(range: &SelectionRange<'_>, paragraph: u64, low: u64, high: u64) -> bool {
    let first = range.first.unwrap_or(0);
    let last = range.last.unwrap_or(0);
    if first < paragraph && paragraph < last {
        return true;
    }
    if first == last && first == paragraph {
        return same_paragraph_overlap(range, low, high);
    }
    if paragraph == first && first < last {
        return range.start <= high;
    }
    paragraph == last && last > first && low <= range.end
}

fn same_paragraph_overlap(range: &SelectionRange<'_>, low: u64, high: u64) -> bool {
    if range.start == range.end {
        low <= range.start && range.start <= high
    } else {
        low < range.end && range.start < high
    }
}

fn selection_region_matches(
    session: &AuthoringSession,
    range: &SelectionRange<'_>,
) -> (Vec<Value>, Vec<Value>, Vec<(Value, Value)>) {
    let hit = |place: &Value| range.hit(place);
    let contains = |place: &Value| range.contains(place);
    let mut matches = Vec::new();
    let mut owners = Vec::new();
    let mut choices = Vec::new();
    for slot in session.analysis["slots"].as_array().into_iter().flatten() {
        let location = &slot["location"];
        if hit(location) {
            matches.push(json!({"kind":"slot","slot_id":slot["id"],
                "label":slot["label"].as_str().filter(|value|!value.is_empty())
                    .or_else(||slot["id"].as_str()).unwrap_or(""),"location":location}));
        }
        if contains(location) {
            owners.push(slot["id"].clone());
        }
        for option in slot["options"].as_array().into_iter().flatten() {
            let location = &option["location"];
            if hit(location) {
                matches.push(json!({"kind":"option","slot_id":slot["id"],
                    "option_id":option["id"],"label":option["label"].as_str().filter(|value|!value.is_empty())
                        .or_else(||option["id"].as_str()).unwrap_or(""),"location":location}));
            }
            if contains(location) {
                choices.push((slot["id"].clone(), option["id"].clone()));
            }
        }
    }
    (matches, owners, choices)
}

fn selection_span(
    session: &AuthoringSession,
    range: &SelectionRange<'_>,
) -> Result<Value, GraphError> {
    let (native, cell_path, first, last, start, end) = (
        range.native,
        range.cell_path,
        range.first,
        range.last,
        range.start,
        range.end,
    );
    let span = if native {
        let anchor = cell_path
            .and_then(|value| value.as_array())
            .and_then(|steps| steps.first())
            .and_then(|step| step["parent_paragraph"].as_u64());
        if let Some(anchor) = anchor {
            json!({"start_paragraph":anchor,"end_paragraph":anchor})
        } else {
            json!({"start_paragraph":first,"end_paragraph":last})
        }
    } else {
        let text = std::str::from_utf8(&session.content)?;
        if let (Some(low), Some(high)) = (utf16_index(text, start), utf16_index(text, end)) {
            let last = if high > low && text.chars().nth(high - 1) == Some('\n') {
                high - 1
            } else {
                high
            };
            json!({"begin_marker_line":text.chars().take(low).filter(|ch|*ch=='\n').count(),
                    "end_marker_line":text.chars().take(last).filter(|ch|*ch=='\n').count()})
        } else {
            Value::Null
        }
    };
    Ok(span)
}

fn selected_context(
    session: &AuthoringSession,
    selection: &Value,
    range: &SelectionRange<'_>,
) -> Result<Option<(String, String)>, GraphError> {
    let (native, start, end) = (range.native, range.start, range.end);
    let found = if native {
        let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
        hwpx_filler::hwpx_authoring_search::selected_context_hwpx(&package, selection)?
    } else {
        let text = std::str::from_utf8(&session.content)?;
        match (utf16_index(text, start), utf16_index(text, end)) {
            (Some(low), Some(high)) if high > low => {
                let before = text_chars(text, 0, low);
                let line = before.rsplit('\n').next().unwrap_or("").to_owned();
                Some((line, text_chars(text, low, high)))
            }
            _ => None,
        }
    };
    Ok(found)
}
