//! Data-row proposal state and immutable authoring view.

use crate::field_induction::{ParagraphText, found_columns, transform};
use crate::field_induction_grading::{KIND_HELD, KIND_PROPOSAL, REASON_BAD_NAME, note_same_value};
use crate::field_induction_proposal::{Group, field_name, propose};
use crate::text_render::python_str;
use serde_json::{Map, Value, json};
use std::fmt;

const ROW_LIMIT: usize = 500;
const ROW_SHOWN: usize = 20;
const ROWS_NOTE: &str = "앞 500행만 맞춰 봅니다.";
const NO_PROPOSAL_LEFT: &str = "남은 제안이 없습니다.";
const INVALID_SELECTION: &str = "고른 위치가 올바르지 않습니다.";
const NOT_SAME_VALUE: &str = "이 값과 같은 열 가운데서 고르세요.";

#[derive(Clone, Debug, Default)]
pub struct LoadedRows {
    pub name: String,
    pub columns: Vec<String>,
    pub rows: Vec<Vec<(String, Option<String>)>>,
    pub truncated: bool,
    pub error: String,
}
#[derive(Clone, Debug, Default)]
pub struct FieldProposalState {
    pub pool_key: String,
    pub sheet: Option<String>,
    pub row: Option<usize>,
    pub loaded: Option<LoadedRows>,
    pub dismissed: Vec<(String, String)>,
    pub picks: Vec<(String, String)>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldProposalError(pub String);
impl fmt::Display for FieldProposalError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for FieldProposalError {}

pub fn normalize_rows(name: &str, records: &[Map<String, Value>]) -> LoadedRows {
    let mut columns = Vec::new();
    let mut rows = Vec::new();
    for record in records.iter().take(ROW_LIMIT) {
        let mut row = Vec::new();
        for (key, value) in record {
            if !columns.contains(key) {
                columns.push(key.clone());
            }
            row.push((key.clone(), (!value.is_null()).then(|| python_str(value))));
        }
        rows.push(row);
    }
    LoadedRows {
        name: name.into(),
        columns,
        rows,
        truncated: records.len() > ROW_LIMIT,
        error: String::new(),
    }
}
fn rows_view(counts: &[usize], chosen: usize) -> Vec<Value> {
    let best = (0..counts.len())
        .max_by_key(|index| (counts[*index], std::cmp::Reverse(*index)))
        .unwrap_or(0);
    let mut order: Vec<_> = (0..counts.len()).collect();
    order.sort_by_key(|index| (std::cmp::Reverse(counts[*index]), *index));
    order.truncate(ROW_SHOWN);
    order.push(chosen - 1);
    order.sort_unstable();
    order.dedup();
    order
        .into_iter()
        .map(|index| {
            json!({"index":index+1,"label":format!("{}행",index+1),
        "hint":if index==best{format!("찾은 값이 가장 많은 행 · {}개",counts[index])}
            else{format!("찾은 값 {}개",counts[index])}})
        })
        .collect()
}
pub fn empty_view(
    state_name: &str,
    revision: u64,
    datasets: &[Value],
    error: &str,
    state: Option<&FieldProposalState>,
) -> Value {
    let data=state.filter(|state|!state.pool_key.is_empty()).map(|state|json!({
        "pool_key":state.pool_key,"name":state.loaded.as_ref().map_or("",|loaded|loaded.name.as_str()),
        "sheet":state.sheet,"row":null,"rows":[],"rows_truncated":false,"rows_note":""}));
    json!({"state":state_name,"error":error,"revision":revision,"datasets":datasets,"data":data,
        "counts":{"proposal":0,"held":0},"groups":[],"missing":[]})
}
fn group_view(group: &Group, locate: &impl Fn(usize, usize, usize) -> Value, row: usize) -> Value {
    let spots: Vec<_> = group
        .spots
        .iter()
        .map(|spot| {
            let mut view = Map::new();
            view.insert("id".into(), json!(spot.id));
            if let Some(place) = locate(spot.paragraph, spot.start, spot.end).as_object() {
                view.extend(place.clone());
            }
            view.insert("text".into(), json!(spot.text));
            view.insert("where".into(), json!(spot.where_label));
            Value::Object(view)
        })
        .collect();
    let only_label = if group.kind == KIND_PROPOSAL {
        (spots.len() >= 2).then_some("이 자리만")
    } else if group.kind == KIND_HELD && !spots.is_empty() && group.reason != REASON_BAD_NAME {
        let cell = group
            .only
            .as_ref()
            .and_then(|id| spots.iter().find(|spot| spot["id"] == *id))
            .is_some_and(|spot| spot.get("cell_path").is_some());
        Some(if cell {
            "표 칸 1곳만 필드로"
        } else {
            "이 자리만 필드로"
        })
    } else {
        None
    };
    let columns: Vec<_> = group
        .others
        .iter()
        .map(|other| json!({"name":other,"note":note_same_value(other)}))
        .collect();
    json!({"id":group.id,"kind":group.kind,"name":group.name,"column":group.column,
        "columns":columns,"value":group.value,"raw":group.raw,
        "binding":transform(group.transform).map(|spec|spec.binding()),"reason":group.reason,"note":group.note,
        "source_text":format!("{row}행 ‘{}’ 열과 같은 값입니다.",group.column),
        "links_note":if group.links_existing{"같은 이름 필드에 자리를 더합니다."}else{""},
        "only":group.only,"only_label":only_label,"links_existing":group.links_existing,
        "count_text":group.count_text,"spots":spots})
}
pub fn proposal_view(
    state: &mut FieldProposalState,
    revision: u64,
    paragraphs: &[ParagraphText],
    locate: &impl Fn(usize, usize, usize) -> Value,
    existing: &[String],
    datasets: &[Value],
) -> Value {
    let Some(loaded) = state.loaded.as_ref() else {
        return empty_view("needs_data", revision, datasets, "", Some(state));
    };
    if !loaded.error.is_empty() || loaded.rows.is_empty() {
        return empty_view("failed", revision, datasets, &loaded.error, Some(state));
    }
    let counts: Vec<_> = loaded
        .rows
        .iter()
        .map(|row| found_columns(paragraphs, row))
        .collect();
    let chosen = state
        .row
        .filter(|row| *row >= 1 && *row <= counts.len())
        .unwrap_or_else(|| {
            (0..counts.len())
                .max_by_key(|index| (counts[*index], std::cmp::Reverse(*index)))
                .unwrap_or(0)
                + 1
        });
    state.row = Some(chosen);
    let result = propose(
        paragraphs,
        &loaded.rows[chosen - 1],
        &loaded.columns,
        existing,
        &state.dismissed,
        &state.picks,
    );
    let groups: Vec<_> = result
        .groups
        .iter()
        .map(|group| group_view(group, locate, chosen))
        .collect();
    let missing: Vec<_> = result
        .missing
        .iter()
        .map(|item| json!({"column":item.column,"reason":item.reason}))
        .collect();
    json!({"state":"ready","error":"","revision":revision,"datasets":datasets,
        "data":{"pool_key":state.pool_key,"name":loaded.name,"sheet":state.sheet,"row":chosen,
            "rows":rows_view(&counts,chosen),"rows_truncated":loaded.truncated,
            "rows_note":if loaded.truncated{ROWS_NOTE}else{""}},
        "counts":{"proposal":result.count(KIND_PROPOSAL),"held":result.count(KIND_HELD)},
        "groups":groups,"missing":missing})
}
fn site(spot: &Value) -> Map<String, Value> {
    ["entry", "paragraph", "cell_path", "start", "end"]
        .into_iter()
        .filter_map(|key| spot.get(key).map(|value| (key.into(), value.clone())))
        .collect()
}
pub fn group_command(group: &Value, spot_id: Option<&Value>) -> Result<Value, FieldProposalError> {
    if field_name(group["column"].as_str().unwrap_or("")).is_none() {
        return Err(FieldProposalError(REASON_BAD_NAME.into()));
    }
    let spots: Vec<_> = group["spots"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|spot| spot_id.is_none_or(|id| spot.get("id") == Some(id)))
        .collect();
    let Some(first) = spots.first() else {
        return Err(FieldProposalError(INVALID_SELECTION.into()));
    };
    let mut command = site(first);
    command.insert("type".into(), json!("create_field"));
    command.insert("name".into(), group["name"].clone());
    if spots.len() > 1 {
        command.insert(
            "ranges".into(),
            json!(spots.iter().map(|spot| site(spot)).collect::<Vec<_>>()),
        );
    }
    Ok(Value::Object(command))
}
pub fn all_command(view: &Value) -> Result<(Value, Vec<Value>), FieldProposalError> {
    let groups: Vec<_> = view["groups"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|group| {
            group["kind"] == KIND_PROPOSAL
                && group["spots"]
                    .as_array()
                    .is_some_and(|spots| !spots.is_empty())
        })
        .cloned()
        .collect();
    if groups.is_empty() {
        return Err(FieldProposalError(NO_PROPOSAL_LEFT.into()));
    }
    let fields: Vec<_> = groups
        .iter()
        .map(|group| {
            json!({"name":group["name"],
        "ranges":group["spots"].as_array().into_iter().flatten().map(site).collect::<Vec<_>>()})
        })
        .collect();
    Ok((json!({"type":"create_fields","fields":fields}), groups))
}
pub fn pick_column(
    state: &mut FieldProposalState,
    group: &Value,
    column: &Value,
) -> Result<(), FieldProposalError> {
    let allowed = group["column"]
        .as_str()
        .is_some_and(|name| column.as_str() == Some(name))
        || group["columns"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|item| item.get("name") == Some(column));
    let Some(column) = column.as_str().filter(|_| allowed) else {
        return Err(FieldProposalError(NOT_SAME_VALUE.into()));
    };
    let key = group["id"].as_str().unwrap_or("");
    if let Some((_, picked)) = state.picks.iter_mut().find(|(id, _)| id == key) {
        *picked = column.into()
    } else {
        state.picks.push((key.into(), column.into()));
    }
    Ok(())
}
pub fn drafts(groups: &[Value]) -> (Map<String, Value>, Map<String, Value>) {
    let mut bindings = Map::new();
    let mut values = Map::new();
    for group in groups {
        let Some(name) = group["name"].as_str() else {
            continue;
        };
        bindings.insert(
            name.into(),
            json!({"source":group["column"],"type":group["binding"]["type"],
            "fmt":group["binding"]["fmt"]}),
        );
        values.insert(name.into(), group["raw"].clone());
    }
    (bindings, values)
}
pub fn toast_one(name: &str) -> String {
    format!("‘{name}’ 필드를 만들고 연결 초안에 열과 표시형을 넣었습니다.")
}
pub fn toast_many(count: usize) -> String {
    format!("필드 {count}개를 만들고 연결 초안에 열과 표시형을 넣었습니다.")
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::data_excel::ExcelDataSource;
    use crate::data_source::DataSource;
    use crate::field_induction_proposal::Spot;
    use crate::field_induction_proposal::propose;
    use crate::field_proposal_reading::read_hwpx;
    use crate::fields::{FieldDocument, field_xml_names, try_fill_simple_batch};
    use crate::mapping::{FieldMapping, MappingProfile};
    use crate::schema::{extract_schema, infer_type};
    use hwpx_core::package::{HwpxPackage, PackageLimits};
    use quick_xml::{Reader, Writer, events::Event};
    use std::collections::{HashMap, HashSet};
    use std::path::{Path, PathBuf};

    fn strip_field_controls(xml: &[u8]) -> Vec<u8> {
        let mut reader = Reader::from_reader(xml);
        let mut writer = Writer::new(Vec::new());
        loop {
            match reader.read_event().unwrap() {
                Event::Start(start) if start.local_name().as_ref() == "ctrl" => {
                    let mut buffered = vec![Event::Start(start.into_owned())];
                    let mut depth = 1;
                    let mut field_child = false;
                    let mut other_child = false;
                    while depth > 0 {
                        let event = reader.read_event().unwrap();
                        match &event {
                            Event::Start(child) | Event::Empty(child) if depth == 1 => {
                                if ["fieldBegin", "fieldEnd"].contains(&child.local_name().as_ref())
                                {
                                    field_child = true;
                                } else {
                                    other_child = true;
                                }
                            }
                            Event::Eof => panic!("unterminated control"),
                            _ => {}
                        }
                        match &event {
                            Event::Start(_) => depth += 1,
                            Event::End(_) => depth -= 1,
                            _ => {}
                        }
                        buffered.push(event.into_owned());
                    }
                    if !field_child || other_child {
                        for event in buffered {
                            writer.write_event(event).unwrap();
                        }
                    }
                }
                Event::Eof => break,
                event => writer.write_event(event.into_owned()).unwrap(),
            }
        }
        writer.into_inner()
    }

    fn recall_case(
        template: &Path,
        data: &Path,
        sheet: &str,
    ) -> (Vec<String>, Vec<String>, Vec<String>) {
        let raw = std::fs::read(template).unwrap();
        let package = HwpxPackage::from_bytes(&raw, PackageLimits::default()).unwrap();
        let source = [
            ("게시일", "게시일시"),
            ("낙찰자결정방법", "낙찰방법"),
            ("담당자 전화번호", "담당자전화"),
            ("대표계약업체", "계약상대자"),
        ];
        let constants = [
            ("계약담당자", "홍길동"),
            ("계약담당 전화번호", "042-000-0000"),
            ("계약담당 팩스번호", "0505-000-0000"),
        ];
        let mappings = extract_schema(&package)
            .unwrap()
            .fields
            .iter()
            .map(|field| {
                let name = field.name.as_str();
                if let Some((_, value)) = constants.iter().find(|(field, _)| field == &name) {
                    return FieldMapping::new(name, "", "const", *value, "", None).unwrap();
                }
                let kind = if name == "게시일" {
                    "date"
                } else {
                    infer_type(name)
                };
                let kind = if ["date", "amount"].contains(&kind) {
                    kind
                } else {
                    "text"
                };
                let fmt = if kind == "date" {
                    if ["게시일", "게시일시"].contains(&name) {
                        "ym"
                    } else {
                        "datetime"
                    }
                } else {
                    ""
                };
                let column = source
                    .iter()
                    .find(|(field, _)| field == &name)
                    .map_or(name, |(_, column)| *column);
                FieldMapping::new(name, column, kind, "", fmt, None).unwrap()
            })
            .collect();
        let profile = MappingProfile::new("", mappings, Map::new()).unwrap();
        let mut data = ExcelDataSource::new(data, Some(sheet.into()), 1).unwrap();
        let columns = data.fields().unwrap();
        let record = data
            .records()
            .unwrap()
            .into_iter()
            .next()
            .unwrap_or_else(|| {
                panic!(
                    "no rows from {} sheet {sheet}; columns {columns:?}",
                    data.path.display()
                )
            });
        let record_map = record
            .iter()
            .map(|(key, value)| (key.clone(), Value::String(value.clone())))
            .collect();
        let values = profile.apply(&record_map, None).unwrap();
        let mut filled = package;
        let requests = values
            .iter()
            .map(|(name, value)| (name.clone(), value.as_str().unwrap().to_owned()))
            .collect::<Vec<_>>();
        let batched = try_fill_simple_batch(&mut filled, &requests);
        if !batched {
            for entry in field_xml_names(&filled).unwrap() {
                let mut document = FieldDocument::new(&mut filled, &entry).unwrap();
                for (name, value) in &values {
                    document.set_field(name, value.as_str().unwrap()).unwrap();
                }
            }
        }
        let (truth, _) = read_hwpx(&filled).unwrap();
        let mut plain = filled.clone();
        for entry in &mut plain.entries {
            if entry.name.starts_with("Contents/") && entry.name.ends_with(".xml") {
                entry.data = strip_field_controls(&entry.data);
            }
        }
        let (paragraphs, _) = read_hwpx(&plain).unwrap();
        assert_eq!(
            paragraphs.iter().map(|item| &item.text).collect::<Vec<_>>(),
            truth.iter().map(|item| &item.text).collect::<Vec<_>>()
        );
        let mut gold = Vec::new();
        let mut positions = HashMap::new();
        for (paragraph, item) in truth.iter().enumerate() {
            for &(start, end) in &item.field_spans {
                let text = item
                    .text
                    .chars()
                    .skip(start)
                    .take(end - start)
                    .collect::<String>();
                positions.insert((paragraph, start, end), text.clone());
                gold.push(((paragraph, start, end), text));
            }
        }
        let row = record
            .iter()
            .map(|(name, value)| (name.clone(), Some(value.clone())))
            .collect::<Vec<_>>();
        let result = propose(&paragraphs, &row, &columns, &[], &[], &[]);
        let mut found = HashSet::new();
        let mut false_positive = Vec::new();
        for group in result
            .groups
            .iter()
            .filter(|group| group.kind == "proposal")
        {
            for spot in &group.spots {
                let key = [
                    (spot.paragraph, spot.start, spot.end),
                    (spot.paragraph, spot.start, spot.end + 1),
                ]
                .into_iter()
                .find(|key| {
                    positions.get(key).is_some_and(|text| {
                        text == &spot.text || text == &format!("{}원", spot.text)
                    })
                });
                if let Some(key) = key {
                    found.insert(key);
                } else {
                    false_positive.push(spot.text.clone());
                }
            }
        }
        let missed = gold
            .iter()
            .filter(|(key, _)| !found.contains(key))
            .map(|(_, text)| text.clone())
            .collect();
        (
            gold.into_iter().map(|(_, text)| text).collect(),
            missed,
            false_positive,
        )
    }

    #[test]
    fn filled_hwpx_plaintext_recalls_data_field_sites() {
        let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let tutorial = repo.join("examples/tutorial");
        let scenario = repo.join("tests/corpus/scenario");
        let (gold, missed, false_positive) = recall_case(
            &tutorial.join("물품 구매입찰 공고.hwpx"),
            &tutorial.join("공고목록.xlsx"),
            "공고",
        );
        assert_eq!(gold.len(), 39);
        assert_eq!(missed, ["홍길동", "042-000-0000", "0505-000-0000"]);
        assert_eq!(false_positive, ["86.245"]);
        let (gold, mut missed, false_positive) = recall_case(
            &scenario.join("templates/입찰공고서.hwpx"),
            &scenario.join("data/조달_한글.xlsx"),
            "Sheet",
        );
        missed.sort();
        assert_eq!(gold.len(), 25);
        assert_eq!(missed, ["", "", "17:00", "2026. 7. 21."]);
        assert!(false_positive.is_empty());
        let (gold, missed, false_positive) = recall_case(
            &repo.join("tests/corpus/real/bid_notice_limited_under100m.hwpx"),
            &scenario.join("data/조달_한글.xlsx"),
            "Sheet",
        );
        assert_eq!(gold.len(), 27);
        assert_eq!(missed, ["", "", "", "", ""]);
        assert!(false_positive.is_empty());
    }

    #[test]
    fn held_spot_without_recommended_id_still_has_single_spot_action() {
        let group = Group {
            id: "g_회사".into(),
            kind: KIND_HELD,
            name: "회사".into(),
            column: "회사".into(),
            others: Vec::new(),
            value: "한국상사".into(),
            raw: "한국상사".into(),
            transform: "identity",
            reason: "여러 자리".into(),
            note: String::new(),
            only: None,
            links_existing: false,
            count_text: "1곳".into(),
            spots: vec![Spot {
                id: "s0_0".into(),
                paragraph: 0,
                start: 0,
                end: 4,
                text: "한국상사".into(),
                where_label: String::new(),
            }],
        };
        let view = group_view(&group, &|_, _, _| json!({"start":0,"end":4}), 1);
        assert_eq!(view["only_label"], "이 자리만 필드로");
    }

    #[test]
    fn row_limit_and_explicit_spot_selection_preserve_proposal_state() {
        let records = (0..501)
            .map(|index| Map::from_iter([("번호".into(), json!(index))]))
            .collect::<Vec<_>>();
        let loaded = normalize_rows("큰 목록", &records);
        assert_eq!(loaded.rows.len(), 500);
        assert!(loaded.truncated);
        let state = FieldProposalState {
            pool_key: "k".into(),
            loaded: Some(loaded),
            ..Default::default()
        };
        assert_eq!(
            empty_view("failed", 4, &[], "실패", Some(&state))["data"],
            json!({"pool_key":"k","name":"큰 목록","sheet":null,"row":null,
                "rows":[],"rows_truncated":false,"rows_note":""})
        );
        let group = json!({"kind":"proposal","column":"이름","name":"이름",
            "spots":[{"id":"s0","start":0,"end":2},
                     {"id":"s1","start":4,"end":6}]});
        assert_eq!(
            group_command(&group, Some(&json!("s1"))).unwrap(),
            json!({"type":"create_field","name":"이름","start":4,"end":6})
        );
        assert!(group_command(&group, Some(&json!("missing"))).is_err());
        let all = all_command(&json!({"groups":[group]})).unwrap();
        assert_eq!(all.0["fields"][0]["ranges"].as_array().unwrap().len(), 2);
        assert_eq!(all.1.len(), 1);
        assert!(all_command(&json!({"groups":[]})).is_err());
        assert!(group_command(&json!({"column":"{{}}","spots":[{"id":"s0"}]}), None).is_err());
    }
}
