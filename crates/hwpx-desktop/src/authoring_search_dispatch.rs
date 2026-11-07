//! Search projections for the authoring screen.

use super::*;

impl AuthoringController {
    pub(super) fn action_search(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session(payload, true)?;
        let query = payload
            .get("query")
            .and_then(Value::as_str)
            .ok_or("검색 조건이 올바르지 않습니다.")?;
        let kind = match payload
            .get("kind")
            .and_then(Value::as_str)
            .unwrap_or("text")
        {
            "body" => "text",
            kind => kind,
        };
        if !matches!(kind, "text" | "field" | "structure" | "all") {
            return Err(fail("검색 조건이 올바르지 않습니다."));
        }
        if query.is_empty() {
            return Ok(json!({"hits":[],"summary":null}));
        }
        if session.media == "hwpx" {
            return Ok(search_result(search_native_hits(session, query, kind)?));
        }
        let mut hits = Vec::new();
        if matches!(kind, "field" | "all") {
            hits.extend(search_txt_fields(session, query));
        }
        if matches!(kind, "structure" | "all") {
            hits.extend(search_txt_structure(session, query));
        }
        if matches!(kind, "text" | "all") {
            hits.extend(search_txt_text(session, query)?);
        }
        Ok(search_result(hits))
    }
}

fn search_native_hits(
    session: &AuthoringSession,
    query: &str,
    kind: &str,
) -> Result<Vec<Value>, GraphError> {
    let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
    let kinds: Vec<&str> = if kind == "all" {
        vec!["text", "field", "structure"]
    } else {
        vec![kind]
    };
    let mut hits = Vec::new();
    for kind in kinds {
        hits.extend(
            search_hwpx(&package, query, kind)?["hits"]
                .as_array()
                .cloned()
                .unwrap_or_default(),
        );
    }
    Ok(hits)
}

fn search_txt_fields(session: &AuthoringSession, query: &str) -> Vec<Value> {
    let lower = python_casefold(query);
    let mut hits = Vec::new();
    for field in session.analysis["fields"].as_array().into_iter().flatten() {
        if field["name"]
            .as_str()
            .is_some_and(|name| python_casefold(name).contains(&lower))
        {
            for occurrence in field["occurrences"].as_array().into_iter().flatten() {
                let mut row = occurrence.clone();
                row["kind"] = json!("field");
                row["label"] = field["name"].clone();
                hits.push(row);
            }
        }
    }
    hits
}

fn search_txt_structure(session: &AuthoringSession, query: &str) -> Vec<Value> {
    let lower = python_casefold(query);
    let mut hits = Vec::new();
    for slot in session.analysis["slots"].as_array().into_iter().flatten() {
        for (kind, item) in std::iter::once(("slot", slot)).chain(
            slot["options"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|option| ("option", option)),
        ) {
            if !["id", "label"].iter().any(|key| {
                item[*key]
                    .as_str()
                    .is_some_and(|value| python_casefold(value).contains(&lower))
            }) {
                continue;
            }
            let location = &item["location"];
            let mut row = json!({"kind":kind,"label":item["label"].as_str()
                .or_else(||item["id"].as_str()).unwrap_or(""),"line":location["begin_marker_line"]});
            row["slot_id"] = slot["id"].clone();
            if kind == "option" {
                row["option_id"] = item["id"].clone();
            }
            for key in ["start", "end"] {
                if let Some(value) = location.get(key) {
                    row[key] = value.clone();
                }
            }
            hits.push(row);
        }
    }
    hits
}

fn search_txt_text(session: &AuthoringSession, query: &str) -> Result<Vec<Value>, GraphError> {
    let source = std::str::from_utf8(&session.content)?;
    let mut hits = Vec::new();
    let mut seen = HashSet::new();
    for (begin, finish) in literal_ignorecase_ranges(source, query)? {
        let start = source[..begin].chars().count();
        let end = source[..finish].chars().count();
        let context = txt_authoring::text_hit_context(source, start, end);
        let line = source[..begin].bytes().filter(|ch| *ch == b'\n').count();
        if !seen.insert((line, context.clone())) {
            continue;
        }
        hits.push(
            json!({"kind":"text","start":source[..begin].encode_utf16().count(),
            "end":source[..finish].encode_utf16().count(),"context":context}),
        );
    }
    Ok(hits)
}
