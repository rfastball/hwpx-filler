//! Structured template schema, including field context and plaintext token residue.

use crate::authoring::{TokenSite, scan_tokens};
use crate::fields::{field_values, field_xml_names, normalize_field_id, python_whitespace};
use hwpx_core::package::HwpxPackage;
use hwpx_core::text_extract::{extract_document, iter_paragraph_texts};
use hwpx_core::xml_view::XmlView;
use hwpx_core::{Content, NodeId};
use regex::Regex;
use serde::Serialize;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::error::Error;
use std::fmt;
use std::sync::LazyLock;

static TOKEN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\{\{([^{}]+)\}\}").unwrap());

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SchemaError(pub String);
impl fmt::Display for SchemaError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl Error for SchemaError {}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct FieldSpec {
    pub name: String,
    pub inferred_type: String,
    pub occurrences: usize,
    pub in_table: bool,
    pub context: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct TableRegion {
    pub field_names: Vec<String>,
    pub rows: usize,
    pub cols: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct TemplateSchema {
    pub fields: Vec<FieldSpec>,
    pub table_regions: Vec<TableRegion>,
    pub stray_tokens: Vec<String>,
    pub unhandled: BTreeMap<String, usize>,
    #[serde(skip)]
    pub stray_sites: Vec<TokenSite>,
}

impl TemplateSchema {
    pub fn field_names(&self) -> Vec<String> {
        self.fields.iter().map(|field| field.name.clone()).collect()
    }
}

pub fn infer_type(name: &str) -> &'static str {
    for (kind, keywords) in [
        (
            "date",
            &[
                "일시",
                "일자",
                "날짜",
                "기한",
                "기간",
                "기일",
                "연월일",
                "년월일",
            ][..],
        ),
        (
            "amount",
            &[
                "금액",
                "가액",
                "예산",
                "가격",
                "단가",
                "비용",
                "요금",
                "대금",
                "원가",
                "공사비",
            ][..],
        ),
        ("phone", &["전화", "연락처", "팩스", "휴대폰", "핸드폰"][..]),
        (
            "number",
            &["번호", "수량", "개수", "차수", "횟수", "건수", "인원"][..],
        ),
    ] {
        if keywords.iter().any(|keyword| name.contains(keyword)) {
            return kind;
        }
    }
    "text"
}

fn fail(message: impl Into<String>) -> SchemaError {
    SchemaError(message.into())
}

fn elements(view: &XmlView, id: NodeId) -> Vec<NodeId> {
    view.node(id)
        .expect("view node")
        .children
        .iter()
        .filter_map(|item| match item {
            Content::Element(child) => Some(*child),
            _ => None,
        })
        .collect()
}

fn local(view: &XmlView, id: NodeId) -> &str {
    &view.node(id).expect("view node").name.local
}

fn context_text(view: &XmlView, paragraph: NodeId) -> String {
    let mut text = String::new();
    for run in elements(view, paragraph) {
        if local(view, run) != "run" {
            continue;
        }
        for child in elements(view, run) {
            match local(view, child) {
                "t" => {
                    if let Some(inline) = view.inline_text(child) {
                        text.push_str(&inline.text);
                    }
                }
                "tab" => text.push('\t'),
                "lineBreak" => text.push('\n'),
                _ => {}
            }
        }
    }
    text.trim_matches(python_whitespace)
        .chars()
        .take(120)
        .collect()
}

#[derive(Clone)]
struct Occurrence {
    name: String,
    context: String,
    table: Option<usize>,
}

fn walk_entry(
    view: &XmlView,
    by_paragraph: &HashMap<NodeId, Vec<String>>,
) -> (Vec<Occurrence>, Vec<TableRegion>) {
    fn walk(
        view: &XmlView,
        id: NodeId,
        table: Option<usize>,
        by_paragraph: &HashMap<NodeId, Vec<String>>,
        occurrences: &mut Vec<Occurrence>,
        regions: &mut Vec<TableRegion>,
    ) {
        if local(view, id) == "p" {
            let label = context_text(view, id);
            if let Some(names) = by_paragraph.get(&id) {
                for name in names {
                    occurrences.push(Occurrence {
                        name: name.clone(),
                        context: label.clone(),
                        table,
                    });
                    if let Some(table) = table
                        && !regions[table].field_names.contains(name)
                    {
                        regions[table].field_names.push(name.clone());
                    }
                }
            }
        }
        let mut current = table;
        if local(view, id) == "tbl" {
            let rows: Vec<_> = elements(view, id)
                .into_iter()
                .filter(|child| local(view, *child) == "tr")
                .collect();
            let cols = rows
                .iter()
                .map(|row| {
                    elements(view, *row)
                        .into_iter()
                        .filter(|child| local(view, *child) == "tc")
                        .count()
                })
                .max()
                .unwrap_or(0);
            current = Some(regions.len());
            regions.push(TableRegion {
                field_names: Vec::new(),
                rows: rows.len(),
                cols,
            });
        }
        for child in elements(view, id) {
            walk(view, child, current, by_paragraph, occurrences, regions);
        }
    }
    let mut occurrences = Vec::new();
    let mut regions = Vec::new();
    walk(
        view,
        view.root(),
        None,
        by_paragraph,
        &mut occurrences,
        &mut regions,
    );
    (
        occurrences,
        regions
            .into_iter()
            .filter(|region| !region.field_names.is_empty())
            .collect(),
    )
}

fn sigil(raw: &str) -> bool {
    raw.trim_start_matches(python_whitespace)
        .chars()
        .next()
        .is_some_and(|ch| matches!(ch, '#' | '/'))
}

fn token_matches(text: &str) -> impl Iterator<Item = (String, String)> + '_ {
    TOKEN.captures_iter(text).filter_map(|matched| {
        let inner = matched.get(1)?.as_str();
        (!sigil(inner)).then(|| {
            (
                matched.get(0).unwrap().as_str().to_owned(),
                inner.to_owned(),
            )
        })
    })
}

fn bump(counts: &mut HashMap<String, usize>, name: &str) {
    *counts.entry(name.to_owned()).or_default() += 1;
}

fn consume(counts: &mut HashMap<String, usize>, name: &str) -> bool {
    let Some(count) = counts.get_mut(name) else {
        return false;
    };
    if *count == 0 {
        return false;
    }
    *count -= 1;
    true
}

fn append_stray(
    raw: &str,
    include_real: bool,
    real_names: &HashSet<String>,
    seen: &mut HashSet<String>,
    result: &mut Vec<String>,
) {
    if let Some(token) = normalize_field_id(raw)
        && (include_real || !real_names.contains(&token))
        && seen.insert(token.clone())
    {
        result.push(token);
    }
}

fn paragraph_fields(
    view: &XmlView,
    entry: &str,
) -> Result<HashMap<NodeId, Vec<String>>, SchemaError> {
    let observed = view.field_occurrences(entry);
    if !observed.pairing_usable() {
        return Err(fail(format!(
            "unusable field pairing in {entry}: {:?}",
            observed.diagnostics
        )));
    }
    let mut by_paragraph = HashMap::<NodeId, Vec<String>>::new();
    for occurrence in observed.fields {
        if let Some(name) = occurrence.raw_name.as_deref().and_then(normalize_field_id) {
            by_paragraph
                .entry(occurrence.paragraph)
                .or_default()
                .push(name);
        }
    }
    Ok(by_paragraph)
}

fn merge_occurrence(
    fields: &mut Vec<FieldSpec>,
    index: &mut HashMap<String, usize>,
    occurrence: Occurrence,
) {
    let at = *index.entry(occurrence.name.clone()).or_insert_with(|| {
        let at = fields.len();
        fields.push(FieldSpec {
            inferred_type: infer_type(&occurrence.name).into(),
            name: occurrence.name.clone(),
            occurrences: 0,
            in_table: false,
            context: String::new(),
        });
        at
    });
    let spec = &mut fields[at];
    spec.occurrences += 1;
    spec.in_table |= occurrence.table.is_some();
    if spec.context.is_empty() && !occurrence.context.is_empty() {
        spec.context = occurrence.context;
    }
}

fn field_inventory(package: &HwpxPackage) -> Result<TemplateSchema, SchemaError> {
    let names = field_xml_names(package).map_err(|error| fail(error.to_string()))?;
    let mut fields = Vec::<FieldSpec>::new();
    let mut field_index = HashMap::<String, usize>::new();
    let mut table_regions = Vec::new();
    for entry in &names {
        let source = package
            .entries
            .iter()
            .find(|item| item.name == *entry)
            .ok_or_else(|| fail(format!("missing content XML entry: {entry}")))?;
        let view = XmlView::parse(&source.data).map_err(|error| fail(error.to_string()))?;
        let by_paragraph = paragraph_fields(&view, entry)?;
        let (occurrences, regions) = walk_entry(&view, &by_paragraph);
        for occurrence in occurrences {
            merge_occurrence(&mut fields, &mut field_index, occurrence);
        }
        table_regions.extend(regions);
    }

    Ok(TemplateSchema {
        fields,
        table_regions,
        ..TemplateSchema::default()
    })
}

#[derive(Default)]
struct FieldTokens {
    all: HashMap<String, usize>,
    strays: HashMap<String, usize>,
    stray_order: Vec<String>,
}

fn field_token_counts(package: &HwpxPackage) -> Result<FieldTokens, SchemaError> {
    let mut counts = FieldTokens::default();
    // The ordinary-value ledger excludes product-denied automatic fields.
    for (field_id, value) in field_values(package).map_err(|error| fail(error.to_string()))? {
        let wrapped = value.trim_matches(python_whitespace);
        let self_placeholder = wrapped.starts_with("{{")
            && wrapped.ends_with("}}")
            && normalize_field_id(wrapped).as_deref() == Some(&field_id);
        for (whole, _) in token_matches(&value) {
            if let Some(token) = normalize_field_id(&whole) {
                bump(&mut counts.all, &token);
                if !self_placeholder {
                    if !counts.strays.contains_key(&token) {
                        counts.stray_order.push(token.clone());
                    }
                    bump(&mut counts.strays, &token);
                }
            }
        }
    }
    Ok(counts)
}

fn append_paragraph_strays<'a>(
    texts: impl IntoIterator<Item = &'a str>,
    outside: &mut HashMap<String, usize>,
    fields: &mut FieldTokens,
    real_names: &HashSet<String>,
    seen: &mut HashSet<String>,
    tokens: &mut Vec<String>,
) {
    for text in texts {
        for (whole, _) in token_matches(text) {
            let Some(token) = normalize_field_id(&whole) else {
                continue;
            };
            if consume(outside, &token) {
                continue;
            }
            if !consume(&mut fields.all, &token) || consume(&mut fields.strays, &token) {
                append_stray(&token, true, real_names, seen, tokens);
            }
        }
    }
    for token in &fields.stray_order {
        if fields.strays.get(token).is_some_and(|count| *count > 0) {
            append_stray(token, true, real_names, seen, tokens);
        }
    }
}

pub fn extract_schema(package: &HwpxPackage) -> Result<TemplateSchema, SchemaError> {
    let mut schema = field_inventory(package)?;
    let document = extract_document(package, None).map_err(|error| fail(error.to_string()))?;
    let sites = scan_tokens(package).map_err(|error| fail(error.to_string()))?;
    let real_names: HashSet<_> = schema.field_names().into_iter().collect();
    let mut stray_seen = HashSet::new();
    let mut outside_tokens = HashMap::new();
    for site in &sites {
        if let Some(token) = normalize_field_id(&site.name)
            && !site.name.starts_with("{{")
        {
            bump(&mut outside_tokens, &token);
            append_stray(
                &token,
                false,
                &real_names,
                &mut stray_seen,
                &mut schema.stray_tokens,
            );
        }
    }
    let mut field_tokens = field_token_counts(package)?;
    append_paragraph_strays(
        iter_paragraph_texts(&document),
        &mut outside_tokens,
        &mut field_tokens,
        &real_names,
        &mut stray_seen,
        &mut schema.stray_tokens,
    );
    schema.stray_sites = sites
        .into_iter()
        .filter(|site| {
            site.compilable
                && normalize_field_id(&site.name).is_some_and(|token| stray_seen.contains(&token))
        })
        .collect();
    schema.unhandled = document.unhandled;
    Ok(schema)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_core::package::{MIMETYPE_NAME, MIMETYPE_VALUE, PackageEntry};

    fn sample(body: &str) -> HwpxPackage {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph'>{body}</hs:sec>"
        );
        HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: MIMETYPE_NAME.into(),
                    data: MIMETYPE_VALUE.to_vec(),
                    stored: true,
                },
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: xml.into_bytes(),
                    stored: false,
                },
            ],
        }
    }

    fn field(name: &str, kind: &str, value: &str) -> String {
        format!(
            "<hp:run><hp:ctrl><hp:fieldBegin name='{name}' type='{kind}'/></hp:ctrl></hp:run><hp:run><hp:t>{value}</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>"
        )
    }

    #[test]
    fn schema_keeps_empty_fields_table_context_and_public_json_order() {
        for (name, expected) in [
            ("납품기한", "date"),
            ("입찰개시일시", "date"),
            ("하자담보기간", "date"),
            ("사업예산", "amount"),
            ("추정가격", "amount"),
            ("수량", "number"),
            ("입찰공고번호", "number"),
            ("담당자 전화번호", "phone"),
            ("수요기관", "text"),
        ] {
            assert_eq!(infer_type(name), expected, "{name}");
        }
        let body = format!(
            "<hp:p><hp:run><hp:t>예산: </hp:t></hp:run>{}</hp:p><hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>담당: </hp:t></hp:run>{}</hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>",
            field("사업예산", "CLICK_HERE", ""),
            field("담당자 전화번호", "CLICK_HERE", "")
        );
        let schema = extract_schema(&sample(&body)).unwrap();
        assert_eq!(schema.field_names(), ["사업예산", "담당자 전화번호"]);
        assert_eq!(
            schema.fields[0],
            FieldSpec {
                name: "사업예산".into(),
                inferred_type: "amount".into(),
                occurrences: 1,
                in_table: false,
                context: "예산:".into()
            }
        );
        assert_eq!(schema.fields[1].inferred_type, "phone");
        assert!(schema.fields[1].in_table);
        assert_eq!(schema.fields[1].context, "담당:");
        assert_eq!(
            schema.table_regions,
            [TableRegion {
                field_names: vec!["담당자 전화번호".into()],
                rows: 1,
                cols: 1
            }]
        );
        let json = serde_json::to_string_pretty(&schema).unwrap();
        let positions: Vec<_> = [
            "\"fields\"",
            "\"table_regions\"",
            "\"stray_tokens\"",
            "\"unhandled\"",
        ]
        .iter()
        .map(|key| json.find(key).unwrap())
        .collect();
        assert!(positions.windows(2).all(|pair| pair[0] < pair[1]));
        assert!(!json.contains("stray_sites"));
    }

    #[test]
    fn schema_minimal_xml_preserves_counts_nested_tables_and_textbox_tokens() {
        let fixture: serde_json::Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/schema_extraction.json"
        ))
        .unwrap();
        for case in fixture["cases"].as_array().unwrap() {
            let mut package = sample("");
            package.entries[1].data = case["xml"].as_str().unwrap().as_bytes().to_vec();
            let before = package.clone();
            let schema = extract_schema(&package).unwrap();
            assert_eq!(
                serde_json::to_value(schema).unwrap(),
                case["expected"],
                "{}",
                case["name"]
            );
            assert_eq!(package, before);
        }
    }

    #[test]
    fn real_notice_schema_matches_required_fields_types_and_table_regions() {
        let fixture: serde_json::Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/schema_extraction.json"
        ))
        .unwrap();
        let package = HwpxPackage::from_bytes(
            include_bytes!("../../../tests/corpus/real/bid_notice_limited_under100m.hwpx"),
            hwpx_core::package::PackageLimits::default(),
        )
        .unwrap();
        let schema = extract_schema(&package).unwrap();
        assert_eq!(
            serde_json::to_value(&schema).unwrap(),
            fixture["corpus"]["expected"]
        );
        assert_eq!(
            schema.field_names().into_iter().collect::<HashSet<_>>(),
            crate::fields::required_fields(&package)
                .unwrap()
                .into_iter()
                .collect()
        );
        assert!(
            crate::lint::lint_template(&package, None, crate::lint::DEFAULT_SIMILARITY_THRESHOLD,)
                .unwrap()
                .findings
                .is_empty()
        );
    }

    #[test]
    fn schema_stray_sites_exclude_self_placeholder_and_include_named_hyperlink() {
        let body = format!(
            "<hp:p><hp:run><hp:t>미치환 {{{{누락}}}} </hp:t></hp:run>{}{}</hp:p>",
            field("사업예산", "CLICK_HERE", "{{사업예산}}"),
            field("링크", "HYPERLINK", "URL")
        );
        let schema = extract_schema(&sample(&body)).unwrap();
        assert_eq!(schema.field_names(), ["사업예산", "링크"]);
        assert_eq!(schema.stray_tokens, ["누락"]);
        assert_eq!(schema.stray_sites.len(), 1);
        assert_eq!(schema.stray_sites[0].name, "누락");
        assert!(schema.stray_sites[0].compilable);
        assert_eq!(schema.unhandled, BTreeMap::new());
    }
}
