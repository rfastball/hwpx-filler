//! One evaluated data-zone view supplies filter, table, and selection-guard facts.

use crate::job_data_session::{JobDataError, MountedData};
use hwpx_filler::filter_primitives::{KIND_AMOUNT, KIND_DATE, KIND_TEXT, cell_text};
use hwpx_filler::filter_state::FilterModel;
use hwpx_filler::jamo::jamo_find;
use hwpx_filler::structure_scan::python_trim;
use serde_json::{Value, json};
use std::collections::HashSet;

const BUILDER_VALUE_CAP: usize = 50;
const PRESET_NO_HOME: &str = "필터는 등록 데이터에만 저장할 수 있습니다.";

fn kind_label(kind: &str) -> &'static str {
    match kind {
        KIND_TEXT => "텍스트",
        KIND_AMOUNT => "금액",
        KIND_DATE => "날짜",
        _ => "",
    }
}
fn error(error: impl ToString) -> JobDataError {
    JobDataError(error.to_string())
}
fn empty_filter() -> Value {
    json!({"active":false,"reapply_available":false,"reapply_hint":"","search":"",
        "chips":[],"definition":"","branches":[],"columns":[],"adhoc_active":false,
        "presets":[],"preset_groups":[],
        "builder":{"columns":[],"total":0,"adhoc":null,"can_create":false,"reason":""}})
}
fn empty_table() -> Value {
    json!({"columns":[],"rows":[],"visible_count":0,"hidden_selected":[],"hidden_columns":[]})
}

pub struct DataZoneProjection {
    pub filter: Value,
    pub table: Value,
    pub visible: Vec<usize>,
    pub filter_visible: HashSet<usize>,
}

impl MountedData {
    fn preset_rows(&self, filter: &FilterModel) -> Result<(Vec<Value>, Vec<Value>), JobDataError> {
        let active = filter.active_presets().into_iter().collect::<HashSet<_>>();
        let states = filter
            .presets()
            .into_iter()
            .filter_map(|item| {
                Some((
                    item.get("name")?.as_str()?.to_owned(),
                    item.get("state")?.clone(),
                ))
            })
            .collect::<std::collections::HashMap<_, _>>();
        let mut rows = Vec::new();
        let mut groups = Vec::new();
        for names in filter.preset_groups().map_err(error)? {
            let first = names.first().ok_or_else(|| error("빈 필터 그룹"))?;
            let key = filter.dimension_key(first).map_err(error)?;
            let label = filter.dimension_label(first).map_err(error)?;
            groups.push(json!({"key":key,"label":label,"names":names}));
            for name in names {
                let (usable, reason) = filter.preset_status(&name);
                let description = if usable {
                    filter
                        .preset_description(&name, &self.records)
                        .map_err(error)?
                } else {
                    String::new()
                };
                rows.push(json!({
                    "name":name,"active":active.contains(&name),"usable":usable,
                    "reason":reason,"dimension":key,"dimension_label":label,
                    "description":description,"state":states.get(&name),
                }));
            }
        }
        Ok((rows, groups))
    }
    fn builder_source(&self, filter: &FilterModel) -> Result<Value, JobDataError> {
        let hidden = self.visible_hidden_columns();
        let mut columns = Vec::new();
        for column in filter.columns() {
            let kind = filter.kind(&column).map_err(error)?;
            let mut values = Vec::new();
            if kind == KIND_TEXT {
                let mut seen = HashSet::new();
                let mut has_empty = false;
                for record in &self.records {
                    let value = cell_text(record, &column);
                    if value.is_empty() {
                        has_empty = true;
                    } else if seen.insert(value.to_owned()) {
                        values.push(value.to_owned());
                    }
                }
                if has_empty {
                    values.push(String::new());
                }
            }
            let more = values.len().saturating_sub(BUILDER_VALUE_CAP);
            values.truncate(BUILDER_VALUE_CAP);
            columns.push(json!({
                "name":column,"kind":kind,"label":kind_label(kind),
                "hidden":hidden.contains(&column),"values":values,"more":more,
            }));
        }
        Ok(json!({
            "columns":columns,"total":self.records.len(),
            "adhoc":filter.has_adhoc().then(|| filter.adhoc_state()),
            "can_create":!self.preset_key.is_empty(),
            "reason":if self.preset_key.is_empty() {PRESET_NO_HOME} else {""},
        }))
    }
    /// Builder column search uses the same Jamo matcher as the global filter search.
    pub fn list_filter_columns(&self, query: &str) -> Result<Value, JobDataError> {
        let filter = self.zone_filter()?;
        let query = python_trim(query);
        let hidden = self.visible_hidden_columns();
        let all = filter.columns();
        let ordered = all
            .iter()
            .filter(|name| !hidden.contains(*name))
            .chain(all.iter().filter(|name| hidden.contains(*name)));
        let mut columns = Vec::new();
        for column in ordered {
            let found = if query.is_empty() {
                Some((0, 0))
            } else {
                jamo_find(column, query)
            };
            let Some((start, end)) = found else { continue };
            let chars = column.chars().collect::<Vec<_>>();
            let segments = [
                (chars[..start].iter().collect::<String>(), false),
                (chars[start..end].iter().collect::<String>(), true),
                (chars[end..].iter().collect::<String>(), false),
            ]
            .into_iter()
            .filter(|(text, _)| !text.is_empty())
            .collect::<Vec<_>>();
            let kind = filter.kind(column).map_err(error)?;
            columns.push(json!({"name":column,"kind":kind,"label":kind_label(kind),
                "hidden":hidden.contains(column),"segments":segments}));
        }
        Ok(json!({"ok":true,"columns":columns}))
    }
    /// `lead_for` is called only for visible rows and selected rows outside the filter.
    pub fn zone_sections(
        &self,
        indices: &[usize],
        mut lead_for: impl FnMut(usize) -> Value,
    ) -> Result<DataZoneProjection, JobDataError> {
        if self.filter.is_none() && self.range_draft.is_none() {
            return Ok(DataZoneProjection {
                filter: empty_filter(),
                table: empty_table(),
                visible: Vec::new(),
                filter_visible: HashSet::new(),
            });
        }
        let filter = self.zone_filter()?;
        let view = filter.view(&self.records).map_err(error)?;
        let filter_visible = view
            .visible_indices()
            .map_err(error)?
            .into_iter()
            .collect::<HashSet<_>>();
        let mut visible = if self
            .range_draft
            .as_ref()
            .is_some_and(|draft| draft.selected_only)
        {
            self.range_draft
                .as_ref()
                .expect("checked draft")
                .range
                .selection
                .selected_indices()
        } else {
            filter_visible.iter().copied().collect::<Vec<_>>()
        };
        visible.sort_unstable();
        if self
            .range_draft
            .as_ref()
            .map_or(&self.view_order, |draft| &draft.range.view_order)
            == "sourceDesc"
        {
            visible.reverse();
        }
        let hidden = self.visible_hidden_columns();
        let columns = filter.columns();
        let (presets, preset_groups) = self.preset_rows(filter)?;
        let mut table_rows = Vec::new();
        for &index in &visible {
            let mut row = lead_for(index)
                .as_object()
                .cloned()
                .ok_or_else(|| error("행 표시 소재는 객체여야 합니다."))?;
            let cells = columns
                .iter()
                .map(|column| {
                    view.segments(column, cell_text(&self.records[index], column))
                        .map_err(error)
                })
                .collect::<Result<Vec<_>, _>>()?;
            row.insert("cells".into(), json!(cells));
            table_rows.push(Value::Object(row));
        }
        let chips = view
            .adhoc_chips()
            .into_iter()
            .map(|chip| json!({"column":chip.column,"text":chip.text}))
            .collect::<Vec<_>>();
        let mut column_rows = Vec::new();
        let mut table_columns = Vec::new();
        for column in &columns {
            let kind = filter.kind(column).map_err(error)?;
            let constraints = filter.column_constraints(column).map_err(error)?;
            column_rows.push(json!({"name":column,"kind":kind,
                "active":filter.has_condition(column).map_err(error)?,
                "filtered":!constraints.is_empty(),"constraints":constraints}));
            table_columns
                .push(json!({"name":column,"kind":kind,"visible":!hidden.contains(column)}));
        }
        let filter_snap = json!({
            "active":filter.is_active(),"reapply_available":self.reapply_available(),
            "reapply_hint":if self.reapply_available() {self.last_filter.as_ref().map_or("", |item| item.summary.as_str())} else {""},
            "search":filter.search_text(),"chips":chips,"definition":view.describe(),
            "adhoc_active":filter.has_adhoc(),"presets":presets,"preset_groups":preset_groups,
            "builder":self.builder_source(filter)?,"branches":view.branches,
            "columns":column_rows,
        });
        let mut hidden_selected = Vec::new();
        let visible_set = visible.iter().copied().collect::<HashSet<_>>();
        for &index in indices {
            if !visible_set.contains(&index) {
                hidden_selected.push(lead_for(index));
            }
        }
        let table_snap = json!({
            "columns":table_columns,"hidden_columns":columns.iter().filter(|name| hidden.contains(*name)).collect::<Vec<_>>(),
            "rows":table_rows,"visible_count":visible.len(),"hidden_selected":hidden_selected,
        });
        Ok(DataZoneProjection {
            filter: filter_snap,
            table: table_snap,
            visible,
            filter_visible,
        })
    }
}
