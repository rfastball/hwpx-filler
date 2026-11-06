//! Shared authoring codecs, selections, location labels, and impact helpers.

use super::*;

pub(super) fn fail(message: impl Into<String>) -> GraphError {
    message.into().into()
}
pub(super) fn digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
pub(super) fn truthy(value: &Value) -> bool {
    match value {
        Value::Null | Value::Bool(false) => false,
        Value::String(text) => !text.is_empty(),
        Value::Array(items) => !items.is_empty(),
        Value::Object(items) => !items.is_empty(),
        Value::Number(number) => number.as_f64() != Some(0.0),
        Value::Bool(true) => true,
    }
}
pub(super) fn python_json_sorted(value: &Value) -> String {
    match value {
        Value::Array(values) => format!(
            "[{}]",
            values
                .iter()
                .map(python_json_sorted)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::Object(values) => {
            let mut keys: Vec<_> = values.keys().collect();
            keys.sort();
            format!(
                "{{{}}}",
                keys.into_iter()
                    .map(|key| format!(
                        "{}: {}",
                        serde_json::to_string(key).expect("JSON key"),
                        python_json_sorted(&values[key])
                    ))
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        }
        _ => serde_json::to_string(value).expect("JSON scalar"),
    }
}
pub(super) fn schema_key(analysis: &Value) -> String {
    let mut fields: Vec<_> = analysis["fields"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|field| field["name"].as_str())
        .collect();
    fields.sort();
    let mut slots: Vec<Value> = analysis["slots"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|slot| {
            let mut options: Vec<_> = slot["options"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|option| option["id"].as_str())
                .collect();
            options.sort();
            json!([slot["id"].as_str().unwrap_or(""), options])
        })
        .collect();
    slots.sort_by(|left, right| {
        left[0]
            .as_str()
            .cmp(&right[0].as_str())
            .then_with(|| left[1].to_string().cmp(&right[1].to_string()))
    });
    digest(python_json_sorted(&json!({"fields":fields,"slots":slots})).as_bytes())
}
pub(super) fn validate_cases(cases: &[Value]) -> Result<(), GraphError> {
    let mut names = HashSet::new();
    for case in cases {
        let name = case
            .get("name")
            .and_then(Value::as_str)
            .ok_or("시험 케이스 이름이 올바르지 않습니다.")?;
        let name = hwpx_filler::structure_scan::python_trim(name);
        if name.is_empty() || !names.insert(name) {
            return Err(fail("시험 케이스 이름이 비었거나 중복되었습니다."));
        }
        if !case.get("values").is_some_and(Value::is_object)
            || !case.get("selected").is_some_and(Value::is_object)
        {
            return Err(fail("시험 케이스 입력이 올바르지 않습니다."));
        }
    }
    Ok(())
}
pub(super) fn clean_selection(value: Option<&Value>) -> Result<Option<Value>, GraphError> {
    let Some(value) = value
        .filter(|value| !value.is_null() && value.as_object().is_none_or(|map| !map.is_empty()))
    else {
        return Ok(None);
    };
    let object = value.as_object().ok_or("고른 위치가 올바르지 않습니다.")?;
    if !valid_selection_shape(object) {
        return Err(fail("고른 위치가 올바르지 않습니다."));
    }
    Ok(Some(value.clone()))
}
fn valid_selection_shape(object: &Map<String, Value>) -> bool {
    const INTS: [&str; 5] = [
        "start",
        "end",
        "paragraph",
        "start_paragraph",
        "end_paragraph",
    ];
    object
        .keys()
        .all(|key| INTS.contains(&key.as_str()) || matches!(key.as_str(), "entry" | "cell_path"))
        && INTS.iter().all(|key| {
            object
                .get(*key)
                .is_none_or(|value| value.as_u64().is_some())
        })
        && object.get("entry").is_none_or(Value::is_string)
        && object.contains_key("start")
        && object.contains_key("end")
        && valid_cell_path(object.get("cell_path"))
}
fn valid_cell_path(path: Option<&Value>) -> bool {
    let Some(path) = path else { return true };
    path.as_array().is_some_and(|steps| {
        steps.iter().all(|step| {
            step.as_object().is_some_and(|item| {
                item.len() == 4
                    && ["parent_paragraph", "control", "cell", "paragraph"]
                        .iter()
                        .all(|key| item.get(*key).and_then(Value::as_u64).is_some())
            })
        })
    })
}
pub(super) fn selection_in(
    media: &str,
    content: &[u8],
    selection: &Value,
) -> Result<bool, GraphError> {
    if media == "txt" {
        let text = std::str::from_utf8(content)?;
        let limit = text.encode_utf16().count() as u64;
        return Ok(selection["start"].as_u64().is_some_and(|start| {
            selection["end"]
                .as_u64()
                .is_some_and(|end| start <= end && end <= limit)
        }) && selection.get("entry").is_none());
    }
    let package = HwpxPackage::from_bytes(content, PackageLimits::default())?;
    let entries = section_entries(&package)?;
    Ok(selection["entry"]
        .as_str()
        .is_some_and(|entry| entries.iter().any(|name| name == entry))
        && selection
            .get("start_paragraph")
            .or_else(|| selection.get("paragraph"))
            .and_then(Value::as_u64)
            .is_some())
}
pub(super) fn media(path: &Path) -> Result<&'static str, GraphError> {
    match path
        .extension()
        .and_then(|part| part.to_str())
        .unwrap_or("")
        .to_ascii_lowercase()
        .as_str()
    {
        "hwpx" => Ok("hwpx"),
        "txt" => Ok("txt"),
        _ => Err(fail("HWPX 또는 TXT 파일만 열 수 있습니다.")),
    }
}
pub(super) fn normalized_text(raw: &[u8]) -> Result<(Vec<u8>, String), GraphError> {
    let text = std::str::from_utf8(raw)?;
    let eol = if text.contains("\r\n") {
        "\r\n"
    } else if text.contains('\r') {
        "\r"
    } else {
        "\n"
    };
    Ok((
        text.replace("\r\n", "\n").replace('\r', "\n").into_bytes(),
        eol.into(),
    ))
}
pub(super) fn analyze(media: &str, content: &[u8]) -> Result<Value, GraphError> {
    if media == "txt" {
        let text = std::str::from_utf8(content)?;
        let mut analysis = txt_authoring::analyze(text);
        analysis["source_text"] = json!(text);
        return Ok(analysis);
    }
    let package = HwpxPackage::from_bytes(content, PackageLimits::default())?;
    Ok(analyze_hwpx(&package)?)
}
pub(super) fn projected_problems(session: &mut AuthoringSession) -> Result<Vec<Value>, GraphError> {
    if let Some((revision, problems)) = &session.cached_problems
        && *revision == session.revision
    {
        return Ok(problems.clone());
    }
    let problems = projection::problems(session)?;
    session.cached_problems = Some((session.revision, problems.clone()));
    Ok(problems)
}
pub(super) fn unwire(media: &str, wire: &Value) -> Result<Vec<u8>, GraphError> {
    let value = wire.as_str().ok_or("문서 내용은 문자열이어야 합니다.")?;
    if media == "txt" {
        Ok(value.replace("\r\n", "\n").replace('\r', "\n").into_bytes())
    } else {
        Ok(STANDARD.decode(value)?)
    }
}
pub(super) fn wire(media: &str, content: &[u8]) -> Result<String, GraphError> {
    if media == "txt" {
        Ok(std::str::from_utf8(content)?.to_owned())
    } else {
        Ok(STANDARD.encode(content))
    }
}
pub(super) fn on_disk(
    session: &AuthoringSession,
    content: Option<&[u8]>,
) -> Result<Vec<u8>, GraphError> {
    let bytes = content.unwrap_or(&session.content);
    if session.media != "txt" || session.eol == "\n" {
        return Ok(bytes.to_vec());
    }
    Ok(std::str::from_utf8(bytes)?
        .replace('\n', &session.eol)
        .into_bytes())
}
pub(super) fn search_result(hits: Vec<Value>) -> Value {
    let text = hits.iter().filter(|hit| hit["kind"] == "text").count();
    let fields = hits.iter().filter(|hit| hit["kind"] == "field").count();
    let structure = hits
        .iter()
        .filter(|hit| hit["kind"] == "slot" || hit["kind"] == "option")
        .count();
    json!({"summary":format!("총 {}건 · 본문 {text} · 필드 {fields} · 항목·선택 {structure}",hits.len()),
        "hits":hits})
}
pub(super) fn location_label(media: &str, location: &Value) -> Option<String> {
    let (first, last) = if media == "hwpx" {
        ("start_paragraph", "end_paragraph")
    } else {
        ("begin_marker_line", "end_marker_line")
    };
    let start = location.get(first)?.as_u64()?;
    let end = location.get(last)?.as_u64()?;
    if end < start {
        return None;
    }
    Some(if media == "hwpx" {
        if start == end {
            format!("문단 {}", start + 1)
        } else {
            format!("문단 {}–{}", start + 1, end + 1)
        }
    } else if start == end {
        format!("{}행", start + 1)
    } else {
        format!("{}–{}행", start + 1, end + 1)
    })
}
pub(super) fn structure_delta(before: &Value, after: &Value, renamed: Vec<Value>) -> Value {
    fn names(analysis: &Value, key: &str) -> BTreeSet<String> {
        analysis[key]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|item| item["id"].as_str().map(str::to_owned))
            .collect()
    }
    fn options(analysis: &Value) -> BTreeSet<(String, String)> {
        analysis["slots"]
            .as_array()
            .into_iter()
            .flatten()
            .flat_map(|slot| {
                let id = slot["id"].as_str().unwrap_or("").to_owned();
                slot["options"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(move |option| {
                        option["id"]
                            .as_str()
                            .map(|choice| (id.clone(), choice.to_owned()))
                    })
            })
            .collect()
    }
    let before_slots = names(before, "slots");
    let after_slots = names(after, "slots");
    let before_options = options(before);
    let after_options = options(after);
    json!({"added_slots":after_slots.difference(&before_slots).collect::<Vec<_>>(),
        "removed_slots":before_slots.difference(&after_slots).collect::<Vec<_>>(),
        "added_options":after_options.difference(&before_options).map(|(slot,option)|json!([slot,option])).collect::<Vec<_>>(),
        "removed_options":before_options.difference(&after_options).map(|(slot,option)|json!([slot,option])).collect::<Vec<_>>(),
        "renamed":renamed})
}
pub(super) fn renamed(command: &Value) -> Vec<Value> {
    match command["type"].as_str().unwrap_or("") {
        "rename_slot" if command.get("id").is_some() && command["id"] != command["slot_id"] => {
            vec![json!({"kind":"slot","from":command["slot_id"],"to":command["id"]})]
        }
        "rename_option" if command.get("id").is_some() && command["id"] != command["option_id"] => {
            vec![json!({"kind":"option","slot_id":command["slot_id"],
                "from":command["option_id"],"to":command["id"]})]
        }
        _ => Vec::new(),
    }
}
pub(super) fn invalid_locate() -> Value {
    json!({"matches":[],"context":{"slot_id":null,"option_id":null,
        "reason":"고른 위치가 유효하지 않습니다."},
        "commands":txt_authoring::available_commands("",&json!({}),None)})
}
pub(super) fn utf16_index(text: &str, offset: u64) -> Option<usize> {
    let mut position = 0u64;
    for (index, ch) in text.chars().enumerate() {
        if position == offset {
            return Some(index);
        }
        position += ch.len_utf16() as u64;
        if position > offset {
            return None;
        }
    }
    (position == offset).then(|| text.chars().count())
}
pub(super) fn text_chars(text: &str, start: usize, end: usize) -> String {
    text.chars().skip(start).take(end - start).collect()
}
pub(super) fn context_label(
    session: &AuthoringSession,
    slot_id: Option<&str>,
    option_id: Option<&str>,
    span: &Value,
) -> Option<String> {
    let mut names = Vec::new();
    if let Some(slot) = session.analysis["slots"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|item| item["id"].as_str() == slot_id)
    {
        names.push(
            slot["label"]
                .as_str()
                .filter(|value| !value.is_empty())
                .or_else(|| slot["id"].as_str())
                .unwrap_or("")
                .to_owned(),
        );
        if let Some(option) = slot["options"]
            .as_array()
            .into_iter()
            .flatten()
            .find(|item| item["id"].as_str() == option_id)
        {
            names.push(
                option["label"]
                    .as_str()
                    .filter(|value| !value.is_empty())
                    .or_else(|| option["id"].as_str())
                    .unwrap_or("")
                    .to_owned(),
            );
        }
    }
    let mut parts = Vec::new();
    if !names.is_empty() {
        parts.push(names.join(" / "));
    }
    if let Some(where_label) = location_label(&session.media, span) {
        parts.push(where_label);
    }
    (!parts.is_empty()).then(|| parts.join(" · "))
}
pub(super) fn section_entries(package: &HwpxPackage) -> Result<Vec<String>, GraphError> {
    let manifest = package
        .entries
        .iter()
        .find(|entry| entry.name == "Contents/content.hpf");
    match manifest {
        Some(manifest) => ordered_section_entries(package, &manifest.data),
        None => fallback_section_entries(package),
    }
}
fn fallback_section_entries(package: &HwpxPackage) -> Result<Vec<String>, GraphError> {
    let sections: Vec<_> = package
        .content_xml_names()
        .into_iter()
        .filter(|name| {
            name.rsplit('/')
                .next()
                .unwrap_or("")
                .to_ascii_lowercase()
                .starts_with("section")
        })
        .map(str::to_owned)
        .collect();
    if sections.len() == 1 {
        Ok(sections)
    } else {
        Err(fail("HWPX 본문 차례를 확인할 수 없습니다."))
    }
}
fn ordered_section_entries(
    package: &HwpxPackage,
    manifest: &[u8],
) -> Result<Vec<String>, GraphError> {
    let view = XmlView::parse(manifest)?;
    let nodes = view
        .descendants(view.root())
        .ok_or("HWPX 본문 차례를 확인할 수 없습니다.")?;
    let mut items = HashMap::new();
    for id in &nodes {
        if view.node(*id).is_some_and(|node| node.name.local == "item")
            && let Some(key) = view.attr(*id, "id")
        {
            items.insert(key.to_owned(), view.attr(*id, "href").map(str::to_owned));
        }
    }
    let mut ordered = Vec::new();
    for id in nodes {
        if view
            .node(id)
            .is_none_or(|node| node.name.local != "itemref")
        {
            continue;
        }
        let href = view
            .attr(id, "idref")
            .and_then(|key| items.get(key))
            .and_then(Option::as_ref)
            .filter(|href| !href.is_empty())
            .ok_or("HWPX 본문 차례에 없는 항목입니다.")?;
        if let Some(entry) = resolved_section_entry(package, href)? {
            ordered.push(entry);
        }
    }
    if ordered.is_empty() || ordered.iter().collect::<HashSet<_>>().len() != ordered.len() {
        return Err(fail("HWPX 본문 차례가 비었거나 중복되었습니다."));
    }
    Ok(ordered)
}
fn resolved_section_entry(package: &HwpxPackage, href: &str) -> Result<Option<String>, GraphError> {
    let base = href.rsplit('/').next().unwrap_or("").to_ascii_lowercase();
    if !base.starts_with("section") || !base.ends_with(".xml") {
        return Ok(None);
    }
    let entry = if package.entries.iter().any(|item| item.name == href) {
        href.to_owned()
    } else {
        format!("Contents/{href}")
    };
    if !package.entries.iter().any(|item| item.name == entry) {
        return Err(fail("HWPX 본문 차례가 없는 파일을 가리킵니다."));
    }
    Ok(Some(entry))
}
