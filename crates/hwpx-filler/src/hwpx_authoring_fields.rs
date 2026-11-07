//! Product field commands over the private native XML edit kernel.

use crate::authoring::compile_document;
use crate::fields::{FieldDocument, FillNoteKind, is_fill_target_field_type, normalize_field_id};
use crate::hwpx_authoring_analysis::fields as analysis_fields;
use crate::hwpx_authoring_reading::{
    CellStep, body_hit_context, field_marks, field_range_refusal, is_hp, paragraph_pieces,
    paragraph_sites, selected_paragraph,
};
use crate::hwpx_authoring_search::index;
use crate::structure_scan::python_trim;
use hwpx_core::native_admission::EntryFieldScan;
use hwpx_core::native_authoring::{
    CreateFieldEdit, FieldElementChange, FieldOccurrenceEdit, change_field_occurrences,
    create_field_ranges,
};
use hwpx_core::package::HwpxPackage;
use hwpx_core::xml_view::{NodeId, XmlView};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AuthoringFieldError(pub String, pub Option<Value>);
impl AuthoringFieldError {
    fn plain(message: String) -> Self {
        Self(message, None)
    }
    fn invalid_name(field: &str, message: &str) -> Self {
        Self(
            message.into(),
            Some(json!({"code":"invalid_name","field":field,"message":message})),
        )
    }
    fn name_conflict(name: &str, count: u64) -> Self {
        let message =
            format!("‘{name}’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요.");
        Self(
            message.clone(),
            Some(
                json!({"code":"name_conflict","name":name,"existing_count":count,"message":message}),
            ),
        )
    }
    pub fn to_dict(&self) -> Option<&Value> {
        self.1.as_ref()
    }
}
impl fmt::Display for AuthoringFieldError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for AuthoringFieldError {}

const INVALID_SELECTION: &str = "고른 위치가 올바르지 않습니다.";
const FIELD_OVERLAP: &str = "고른 범위에 기존 필드가 포함되어 있습니다.";
const INVALID_FIELD_NAME: &str =
    "필드 이름을 확인하세요. 비어 있거나 문법 기호가 포함되어 있습니다.";
const FIX_STALE: &str =
    "이 문제의 자동 수정이 더는 적용되지 않습니다. 문제 목록을 다시 확인하세요.";

pub fn compile_token(
    package: &mut HwpxPackage,
    command: &Value,
) -> Result<String, AuthoringFieldError> {
    let (Some(entry), Some(path), Some(start), Some(name)) = (
        command.get("entry").and_then(Value::as_str),
        command.get("paragraph_path").and_then(Value::as_str),
        command.get("token_start").and_then(Value::as_i64),
        command
            .get("name")
            .and_then(Value::as_str)
            .and_then(normalize_field_id),
    ) else {
        return Err(AuthoringFieldError::plain(FIX_STALE.into()));
    };
    let mut candidate = package.clone();
    let report = compile_document(&mut candidate, Some((entry, path, start as isize)))
        .map_err(|error| AuthoringFieldError::plain(error.to_string()))?;
    if report.compiled.len() != 1 || normalize_field_id(&report.compiled[0]) != Some(name.clone()) {
        return Err(AuthoringFieldError::plain(FIX_STALE.into()));
    }
    *package = candidate;
    Ok(format!("{{{{{}}}}}", report.compiled[0]))
}

pub fn field_site_contexts(
    package: &HwpxPackage,
    command: &Value,
) -> Result<Vec<String>, AuthoringFieldError> {
    let mut positions = Vec::new();
    for site in ranges(command)? {
        let entry = site.get("entry").and_then(Value::as_str).ok_or_else(|| {
            AuthoringFieldError::plain("HWPX 문서 영역을 찾을 수 없습니다.".into())
        })?;
        let source = package
            .entries
            .iter()
            .find(|item| item.name == entry)
            .ok_or_else(|| {
                AuthoringFieldError::plain("HWPX 문서 영역을 찾을 수 없습니다.".into())
            })?;
        let view = XmlView::parse(&source.data)
            .map_err(|error| AuthoringFieldError::plain(error.to_string()))?;
        let paragraph = site_paragraph(&view, site)?;
        let start = index(site.get("start")).ok_or_else(|| {
            AuthoringFieldError::plain("문단 안의 정확한 문자 범위를 고르세요.".into())
        })?;
        let end = index(site.get("end")).ok_or_else(|| {
            AuthoringFieldError::plain("문단 안의 정확한 문자 범위를 고르세요.".into())
        })?;
        if site
            .get("end_paragraph")
            .is_some_and(|value| value != site.get("paragraph").unwrap_or(&Value::Null))
        {
            return Err(AuthoringFieldError::plain(
                "여러 문단에 걸친 필드는 HWPX 누름틀 경계로 만들 수 없습니다.".into(),
            ));
        }
        let scan = view.field_occurrences(entry);
        let marks = field_marks(&scan);
        let pieces = paragraph_pieces(&view, paragraph, &marks);
        let order = view
            .descendants(view.root())
            .unwrap()
            .into_iter()
            .filter(|id| is_hp(&view, *id, "p"))
            .position(|id| id == paragraph)
            .unwrap_or(usize::MAX);
        positions.push((
            entry.to_owned(),
            order,
            start,
            body_hit_context(&pieces, start, end),
        ));
    }
    positions.sort_by(|a, b| (&a.0, a.1, a.2).cmp(&(&b.0, b.1, b.2)));
    Ok(positions.into_iter().map(|item| item.3).collect())
}

#[derive(Clone)]
struct Planned {
    entry: String,
    path: String,
    start: usize,
    end: usize,
    name: String,
    selected: String,
}

fn field_name(raw: Option<&Value>) -> Result<String, AuthoringFieldError> {
    let name = raw
        .and_then(Value::as_str)
        .and_then(normalize_field_id)
        .ok_or_else(|| AuthoringFieldError::invalid_name("name", INVALID_FIELD_NAME))?;
    if name.contains("{{") || name.contains("}}") || name.starts_with(['#', '/']) {
        return Err(AuthoringFieldError::invalid_name(
            "name",
            INVALID_FIELD_NAME,
        ));
    }
    Ok(name)
}

fn path_steps(value: Option<&Value>) -> Option<Vec<CellStep>> {
    let array = value?.as_array()?;
    array
        .iter()
        .map(|step| {
            let map = step.as_object()?;
            if map.len() != 4 {
                return None;
            }
            Some(CellStep {
                parent_paragraph: index(map.get("parent_paragraph"))?,
                control: index(map.get("control"))?,
                cell: index(map.get("cell"))?,
                paragraph: index(map.get("paragraph"))?,
            })
        })
        .collect()
}

fn site_paragraph(view: &XmlView, site: &Value) -> Result<NodeId, AuthoringFieldError> {
    if let Some(path) = site.get("paragraph_path").and_then(Value::as_str) {
        let found: Vec<_> = view
            .descendants(view.root())
            .unwrap()
            .into_iter()
            .filter(|id| is_hp(view, *id, "p") && view.path(*id).as_deref() == Some(path))
            .collect();
        if found.len() != 1 {
            return Err(AuthoringFieldError::plain(
                "고른 문단의 위치를 확정할 수 없습니다.".into(),
            ));
        }
        return Ok(found[0]);
    }
    let paragraph = index(site.get("paragraph"))
        .ok_or_else(|| AuthoringFieldError::plain("고른 문단이 문서 영역 밖에 있습니다.".into()))?;
    let path = path_steps(site.get("cell_path"));
    if site.get("cell_path").is_some_and(Value::is_array) && path.is_none() {
        return Err(AuthoringFieldError::plain(
            "고른 문단의 위치를 확정할 수 없습니다.".into(),
        ));
    }
    selected_paragraph(view, paragraph, path.as_deref())
        .map_err(|message| AuthoringFieldError::plain(message.into()))
}

fn planned_site(
    package: &HwpxPackage,
    views: &mut HashMap<String, XmlView>,
    site: &Value,
    name: &str,
) -> Result<Planned, AuthoringFieldError> {
    let entry = site
        .get("entry")
        .and_then(Value::as_str)
        .ok_or_else(|| AuthoringFieldError::plain("HWPX 문서 영역을 찾을 수 없습니다.".into()))?;
    let source = package
        .entries
        .iter()
        .find(|item| item.name == entry)
        .ok_or_else(|| AuthoringFieldError::plain("HWPX 문서 영역을 찾을 수 없습니다.".into()))?;
    if [site.get("start"), site.get("end")]
        .into_iter()
        .flatten()
        .any(|value| value.as_i64().is_some_and(|number| number < 0))
    {
        return Err(AuthoringFieldError::plain(
            "고른 문자 범위가 문단 밖에 있습니다.".into(),
        ));
    }
    let (start, end) = (index(site.get("start")), index(site.get("end")));
    let (Some(start), Some(end)) = (start, end) else {
        return Err(AuthoringFieldError::plain(
            "문단 안의 정확한 문자 범위를 고르세요.".into(),
        ));
    };
    if !views.contains_key(entry) {
        let view = XmlView::parse(&source.data)
            .map_err(|error| AuthoringFieldError::plain(error.to_string()))?;
        views.insert(entry.into(), view);
    }
    let view = views.get(entry).unwrap();
    let paragraph = site_paragraph(view, site)?;
    if site.get("end_paragraph") != site.get("paragraph") && site.get("end_paragraph").is_some() {
        return Err(AuthoringFieldError::plain(
            "여러 문단에 걸친 필드는 HWPX 누름틀 경계로 만들 수 없습니다.".into(),
        ));
    }
    let scan = view.field_occurrences(entry);
    let sites = paragraph_sites(view, paragraph, &scan);
    if let Some(reason) = field_range_refusal(view, paragraph, &scan, &sites, start, end) {
        return Err(AuthoringFieldError::plain(reason.into()));
    }
    let selected: String = sites.text.chars().skip(start).take(end - start).collect();
    Ok(Planned {
        entry: entry.into(),
        path: view.path(paragraph).unwrap(),
        start,
        end,
        name: name.into(),
        selected,
    })
}

fn ranges(command: &Value) -> Result<Vec<&Value>, AuthoringFieldError> {
    match command.get("ranges") {
        None | Some(Value::Null) => Ok(vec![command]),
        Some(Value::Array(items)) if items.iter().all(Value::is_object) => {
            Ok(items.iter().collect())
        }
        _ => Err(AuthoringFieldError::plain(INVALID_SELECTION.into())),
    }
}

fn validate_overlap(planned: &[Planned]) -> Result<(), AuthoringFieldError> {
    for (index, item) in planned.iter().enumerate() {
        for other in &planned[index + 1..] {
            if item.entry == other.entry
                && item.path == other.path
                && ((item.start < other.end && other.start < item.end)
                    || (item.start, item.end) == (other.start, other.end))
            {
                return Err(AuthoringFieldError::plain(FIELD_OVERLAP.into()));
            }
        }
    }
    Ok(())
}

fn commit(package: &mut HwpxPackage, planned: &[Planned]) -> Result<(), AuthoringFieldError> {
    let mut candidates = Vec::new();
    let mut entries = Vec::new();
    for item in planned {
        if !entries.contains(&item.entry) {
            entries.push(item.entry.clone());
        }
    }
    for entry in entries {
        let selected: Vec<_> = planned.iter().filter(|item| item.entry == entry).collect();
        if selected.is_empty() {
            continue;
        }
        let source = package
            .entries
            .iter()
            .find(|item| item.name == entry)
            .unwrap();
        let edits: Vec<_> = selected
            .iter()
            .map(|item| CreateFieldEdit {
                paragraph_path: &item.path,
                start: item.start,
                end: item.end,
                name: &item.name,
            })
            .collect();
        let bytes = create_field_ranges(&source.data, &edits)
            .map_err(|error| AuthoringFieldError::plain(error.to_string()))?;
        candidates.push((entry, bytes));
    }
    for (entry, bytes) in candidates {
        package
            .entries
            .iter_mut()
            .find(|item| item.name == entry)
            .unwrap()
            .data = bytes;
    }
    Ok(())
}

pub fn create_field(
    package: &mut HwpxPackage,
    command: &Value,
) -> Result<String, AuthoringFieldError> {
    let mut views = HashMap::new();
    let name = field_name(command.get("name"))?;
    let primary = planned_site(package, &mut views, command, &name)?;
    let mut planned = Vec::new();
    for site in ranges(command)? {
        let item = planned_site(package, &mut views, site, &name)?;
        if item.selected != primary.selected {
            return Err(AuthoringFieldError::plain(INVALID_SELECTION.into()));
        }
        planned.push(item);
    }
    if !planned.iter().any(|item| {
        item.entry == primary.entry
            && item.path == primary.path
            && item.start == primary.start
            && item.end == primary.end
    }) {
        return Err(AuthoringFieldError::plain(INVALID_SELECTION.into()));
    }
    validate_overlap(&planned)?;
    commit(package, &planned)?;
    Ok(primary.selected)
}

pub fn create_fields(
    package: &mut HwpxPackage,
    fields: &[Value],
) -> Result<usize, AuthoringFieldError> {
    if fields.iter().any(|item| !item.is_object()) {
        return Err(AuthoringFieldError::plain(INVALID_SELECTION.into()));
    }
    let mut views = HashMap::new();
    let mut planned = Vec::new();
    for item in fields {
        let name = field_name(item.get("name"))?;
        let sites = ranges(item)?;
        if sites.is_empty() {
            return Err(AuthoringFieldError::plain(INVALID_SELECTION.into()));
        }
        let mut group = Vec::new();
        for site in sites {
            group.push(planned_site(package, &mut views, site, &name)?);
        }
        let captured = &group[0].selected;
        if group.iter().any(|item| &item.selected != captured) {
            return Err(AuthoringFieldError::plain(INVALID_SELECTION.into()));
        }
        validate_overlap(&group)?;
        planned.extend(group);
    }
    validate_overlap(&planned)?;
    commit(package, &planned)?;
    Ok(planned.len())
}

fn ordinal(value: Option<&Value>) -> Option<usize> {
    match value? {
        Value::Bool(value) => Some(usize::from(*value)),
        other => index(Some(other)),
    }
}

pub fn change_field(
    package: &mut HwpxPackage,
    command: &Value,
) -> Result<usize, AuthoringFieldError> {
    let action = command.get("type").and_then(Value::as_str).unwrap_or("");
    if !matches!(action, "rename_field" | "relink_field" | "unset_field") {
        return Err(AuthoringFieldError::plain(format!(
            "지원하지 않는 필드 명령입니다: {action}"
        )));
    }
    let whole = action == "unset_field" && command.get("occurrences").is_some_and(Value::is_array);
    let old = if action == "rename_field" || whole {
        Some(field_name(command.get("old_name"))?)
    } else {
        None
    };
    let new = if matches!(action, "rename_field" | "relink_field") {
        Some(field_name(command.get("name"))?)
    } else {
        None
    };
    if action == "rename_field" && new != old {
        let taken = analysis_fields(package)
            .map_err(|error| AuthoringFieldError::plain(error.to_string()))?
            .into_iter()
            .find(|item| item["name"] == new.as_deref().unwrap_or(""))
            .map(|item| item["count"].as_u64().unwrap_or(0))
            .unwrap_or(0);
        if taken > 0 {
            return Err(AuthoringFieldError::name_conflict(
                new.as_deref().unwrap(),
                taken,
            ));
        }
    }
    let replacement = if action == "unset_field" {
        Some(command.get("text").and_then(Value::as_str).ok_or_else(|| {
            AuthoringFieldError::plain("의미를 해제한 뒤 남길 본문을 입력하세요.".into())
        })?)
    } else {
        None
    };
    let mut candidates = Vec::new();
    let mut count = 0;
    for entry in package.content_xml_names() {
        let source = package
            .entries
            .iter()
            .find(|item| item.name == entry)
            .unwrap();
        let view = XmlView::parse(&source.data)
            .map_err(|error| AuthoringFieldError::plain(error.to_string()))?;
        let scan = view.field_occurrences(entry);
        let applies = action == "rename_field"
            || whole
            || command.get("entry").and_then(Value::as_str) == Some(entry);
        if applies && !scan.pairing_usable() {
            return Err(pairing_error(&scan));
        }
        let mut selected = Vec::new();
        if action == "rename_field" || whole {
            for (at, field) in scan.fields.iter().enumerate() {
                if is_fill_target_field_type(field.field_type.as_deref())
                    && field.raw_name.as_deref().and_then(normalize_field_id) == old
                {
                    selected.push(at);
                }
            }
        } else if command.get("entry").and_then(Value::as_str) == Some(entry) {
            let at = ordinal(command.get("occurrence")).ok_or_else(|| {
                AuthoringFieldError::plain("필드 사용 위치가 올바르지 않습니다.".into())
            })?;
            let field = scan.fields.get(at).ok_or_else(|| {
                AuthoringFieldError::plain("필드 사용 위치를 찾을 수 없습니다.".into())
            })?;
            if let Some(expected) = command.get("pairing_id").filter(|value| !value.is_null())
                && expected.as_str() != view.attr(field.begin, "id")
            {
                return Err(AuthoringFieldError::plain(
                    "고른 필드 사용 위치가 바뀌었습니다. 다시 고르세요.".into(),
                ));
            }
            if !is_fill_target_field_type(field.field_type.as_deref()) {
                return Err(AuthoringFieldError::plain(
                    "고른 요소는 채울 수 있는 필드가 아닙니다.".into(),
                ));
            }
            selected.push(at);
        }
        if selected.is_empty() {
            continue;
        }
        let edits: Vec<_> = selected
            .iter()
            .map(|at| FieldOccurrenceEdit {
                ordinal: *at,
                pairing_id: view.attr(scan.fields[*at].begin, "id"),
                change: if action == "unset_field" {
                    FieldElementChange::Unset(replacement.unwrap())
                } else {
                    FieldElementChange::Rename(new.as_deref().unwrap())
                },
            })
            .collect();
        let bytes = change_field_occurrences(&source.data, &edits)
            .map_err(|error| AuthoringFieldError::plain(error.to_string()))?;
        candidates.push((entry.to_owned(), bytes));
        count += selected.len();
    }
    if count == 0 {
        return Err(AuthoringFieldError::plain(
            "필드를 찾을 수 없습니다.".into(),
        ));
    }
    for (entry, bytes) in candidates {
        package
            .entries
            .iter_mut()
            .find(|item| item.name == entry)
            .unwrap()
            .data = bytes;
    }
    Ok(count)
}

fn filled_value(value: &str, name: &str) -> bool {
    let text = python_trim(value);
    if text.is_empty() {
        return false;
    }
    !(text.starts_with("{{")
        && text.ends_with("}}")
        && normalize_field_id(text).as_deref() == Some(name))
}

fn pairing_error(scan: &EntryFieldScan) -> AuthoringFieldError {
    AuthoringFieldError::plain(
        scan.diagnostics
            .iter()
            .map(|item| {
                format!(
                    "{}: {} at element {}{}",
                    item.entry,
                    item.kind.as_str(),
                    item.order,
                    if item.detail.is_empty() {
                        String::new()
                    } else {
                        format!(" ({})", item.detail)
                    }
                )
            })
            .collect::<Vec<_>>()
            .join("; "),
    )
}

pub fn revert_template(package: &mut HwpxPackage) -> Result<usize, AuthoringFieldError> {
    let mut candidates = Vec::new();
    let mut count = 0;
    for entry in package.content_xml_names() {
        let source = package
            .entries
            .iter()
            .find(|item| item.name == entry)
            .unwrap();
        let mut candidate = HwpxPackage {
            entries: vec![source.clone()],
        };
        let observed = XmlView::parse(&source.data)
            .map_err(|error| AuthoringFieldError::plain(error.to_string()))?
            .field_occurrences(entry);
        if !observed.pairing_usable() {
            return Err(pairing_error(&observed));
        }
        let mut document = FieldDocument::new(&mut candidate, entry)
            .map_err(|error| AuthoringFieldError::plain(error.to_string()))?;
        let filled: Vec<_> = document
            .field_values()
            .map_err(|error| AuthoringFieldError::plain(error.to_string()))?
            .into_iter()
            .filter(|(name, value)| filled_value(value, name))
            .collect();
        let mut seen = Vec::new();
        for (name, _) in &filled {
            if seen.contains(name) {
                continue;
            }
            seen.push(name.clone());
            if !document
                .set_field(name, &format!("{{{{{name}}}}}"))
                .map_err(|error| AuthoringFieldError::plain(error.to_string()))?
            {
                return Err(AuthoringFieldError::plain(
                    "이 필드에는 복합 요소가 있어 내용 보존을 확인할 수 없습니다.".into(),
                ));
            }
        }
        if document
            .notes()
            .iter()
            .any(|note| note.kind == FillNoteKind::OccurrenceUnfillable)
        {
            return Err(AuthoringFieldError::plain(
                "이 필드에는 복합 요소가 있어 내용 보존을 확인할 수 없습니다.".into(),
            ));
        }
        let modified = document.modified();
        drop(document);
        count += filled.len();
        if modified {
            candidates.push((entry.to_owned(), candidate.entries.remove(0).data));
        }
    }
    if count == 0 {
        return Err(AuthoringFieldError::plain(
            "되돌릴 필드 값이 없습니다.".into(),
        ));
    }
    for (entry, bytes) in candidates {
        package
            .entries
            .iter_mut()
            .find(|item| item.name == entry)
            .unwrap()
            .data = bytes;
    }
    Ok(count)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::authoring::scan_tokens;
    use hwpx_core::package::PackageEntry;
    use hwpx_core::text_model::HP_NS;

    #[test]
    fn stale_compile_token_name_refuses_without_mutating_the_package() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>앞 {{{{이름}}}} 뒤</hp:t></hp:run></hp:p></hs:sec>"
        );
        let mut package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let site = scan_tokens(&package).unwrap().remove(0);
        let command = serde_json::json!({"type":"compile_token","entry":site.entry,
            "paragraph_path":site.paragraph_path,"token_start":site.start,"name":"다른이름"});
        let original = package.clone();
        assert_eq!(
            compile_token(&mut package, &command).unwrap_err().0,
            FIX_STALE
        );
        assert_eq!(package, original);
        let mut accepted = command;
        accepted["name"] = serde_json::json!("이름");
        assert_eq!(compile_token(&mut package, &accepted).unwrap(), "{{이름}}");
        let converted = package.clone();
        assert_eq!(
            compile_token(&mut package, &accepted).unwrap_err().0,
            FIX_STALE
        );
        assert_eq!(package, converted);
    }

    #[test]
    fn multi_entry_field_creation_commits_together_or_keeps_original() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p></hs:sec>"
        );
        let original = HwpxPackage {
            entries: (0..2)
                .map(|index| PackageEntry {
                    name: format!("Contents/section{index}.xml"),
                    data: xml.as_bytes().to_vec(),
                    stored: false,
                })
                .collect(),
        };
        let site = |index: usize, start: usize, end: usize| {
            serde_json::json!({
                "entry": format!("Contents/section{index}.xml"), "paragraph": 0, "start": start, "end": end
            })
        };
        let mut failed = original.clone();
        let bad = serde_json::json!({"type": "create_field", "name": "고객", "entry": "Contents/section0.xml", "paragraph": 0, "start": 0, "end": 2,
            "ranges": [site(0, 0, 2), site(1, 20, 21)]});
        assert!(create_field(&mut failed, &bad).is_err());
        assert_eq!(failed, original);
        let negative = serde_json::json!({"name": "고객", "entry": "Contents/section0.xml", "paragraph": 0, "start": -1, "end": 1});
        assert_eq!(
            create_field(&mut failed, &negative).unwrap_err().0,
            "고른 문자 범위가 문단 밖에 있습니다."
        );
        assert_eq!(create_fields(&mut failed, &[]).unwrap(), 0);
        assert_eq!(failed, original);
        let invalid = create_field(&mut failed, &serde_json::json!({"name": "", "entry": "Contents/section0.xml", "paragraph": 0, "start": 0, "end": 1})).unwrap_err();
        assert_eq!(
            invalid.to_dict(),
            Some(
                &serde_json::json!({"code":"invalid_name","field":"name","message":INVALID_FIELD_NAME})
            )
        );
        assert_eq!(failed, original);
        let mut made = original.clone();
        let good = serde_json::json!({"type": "create_field", "name": "고객", "entry": "Contents/section0.xml", "paragraph": 0, "start": 0, "end": 2,
            "ranges": [site(0, 0, 2), site(1, 0, 2)]});
        assert_eq!(create_field(&mut made, &good).unwrap(), "본문");
        for entry in &made.entries {
            let view = XmlView::parse(&entry.data).unwrap();
            let scan = view.field_occurrences(&entry.name);
            assert!(scan.pairing_usable());
            assert_eq!(scan.fields.len(), 1);
            assert_eq!(scan.fields[0].raw_name.as_deref(), Some("고객"));
            assert_eq!(scan.fields[0].value.text, "본문");
        }
        assert_eq!(
            change_field(
                &mut made,
                &serde_json::json!({"type": "rename_field", "old_name": "고객", "name": "의뢰인"})
            )
            .unwrap(),
            2
        );
        let renamed = made.clone();
        let conflict = change_field(
            &mut made,
            &serde_json::json!({"type":"rename_field","old_name":"없는","name":"의뢰인"}),
        )
        .unwrap_err();
        assert_eq!(
            conflict.to_dict(),
            Some(
                &serde_json::json!({"code":"name_conflict","name":"의뢰인","existing_count":2,"message":"‘의뢰인’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요."})
            )
        );
        assert_eq!(made, renamed);
        assert!(change_field(&mut made, &serde_json::json!({"type": "unset_field", "entry": "Contents/section0.xml", "occurrence": 0, "pairing_id": "stale", "text": "원문"})).is_err());
        assert_eq!(made, renamed);
        assert_eq!(change_field(&mut made, &serde_json::json!({"type": "unset_field", "entry": "Contents/section0.xml", "occurrence": 0, "text": "원문"})).unwrap(), 1);
        let first = XmlView::parse(&made.entries[0].data).unwrap();
        let second = XmlView::parse(&made.entries[1].data).unwrap();
        assert!(
            first
                .field_occurrences("Contents/section0.xml")
                .fields
                .is_empty()
        );
        assert_eq!(
            second.field_occurrences("Contents/section1.xml").fields[0]
                .raw_name
                .as_deref(),
            Some("의뢰인")
        );
        assert_eq!(revert_template(&mut made).unwrap(), 1);
        let reverted = XmlView::parse(&made.entries[1].data).unwrap();
        assert_eq!(
            reverted.field_occurrences("Contents/section1.xml").fields[0]
                .value
                .text,
            "{{의뢰인}}"
        );
        let stable = made.clone();
        assert_eq!(
            revert_template(&mut made).unwrap_err().0,
            "되돌릴 필드 값이 없습니다."
        );
        assert_eq!(made, stable);
        let mut malformed = made.clone();
        malformed.entries[0].data = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:ctrl><hp:fieldBegin id='1' name='고아'/></hp:ctrl></hp:run></hp:p></hs:sec>"
        )
        .into_bytes();
        let before = malformed.clone();
        assert_eq!(
            revert_template(&mut malformed).unwrap_err().0,
            "Contents/section0.xml: unmatched-begin at element 4"
        );
        assert_eq!(malformed, before);
    }
}
