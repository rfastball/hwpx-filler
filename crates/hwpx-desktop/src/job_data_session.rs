//! Atomic mounted data observation for the Job screen.

use crate::dataset_registry::{DatasetPoolRegistry, PoolError};
use hwpx_filler::data_excel::ambiguous_sheet_error;
use hwpx_filler::data_factory::{
    binding_for_reference, requires_nara_key, source_for_binding, source_for_path,
    source_from_pool_item,
};
use hwpx_filler::data_source::{DataSource, Record};
use hwpx_filler::dataset_reference::{excel_identity, pclm_identity, reference_for_sheet};
use hwpx_filler::filter_primitives::sniff_column_kinds;
use hwpx_filler::filter_state::FilterModel;
use hwpx_filler::record_range::RecordRangeDraft;
use hwpx_filler::selection_state::{SelectionError, SelectionModel};
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::path::Path;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MountedData {
    pub records: Vec<Record>,
    pub fields: Vec<String>,
    pub selection: SelectionModel,
    pub filter: Option<FilterModel>,
    pub range_draft: Option<RecordRangeDraft>,
    pub hidden_columns: HashSet<String>,
    pub label: String,
    pub source_kind: String,
    pub path: String,
    pub sheet: String,
    pub header_row: u64,
    pub kind: String,
    pub pool_key: String,
    pub preset_key: String,
    pub data_key: String,
    pub last_filter: Option<StashedFilter>,
    pub snapshot_generation: u64,
    pub zone_epoch: u64,
    pub view_order: String,
    pub notice_text: String,
    pub notice_level: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StashedFilter {
    pub source_key: String,
    pub state: Value,
    pub summary: String,
}
impl Default for MountedData {
    fn default() -> Self {
        Self {
            records: vec![],
            fields: vec![],
            selection: SelectionModel::new(0, false),
            filter: None,
            range_draft: None,
            hidden_columns: HashSet::new(),
            label: String::new(),
            source_kind: String::new(),
            path: String::new(),
            sheet: String::new(),
            header_row: 0,
            kind: String::new(),
            pool_key: String::new(),
            preset_key: String::new(),
            data_key: String::new(),
            last_filter: None,
            snapshot_generation: 0,
            zone_epoch: 0,
            view_order: "sourceDesc".into(),
            notice_text: String::new(),
            notice_level: String::new(),
        }
    }
}
#[derive(Debug)]
pub struct JobDataError(pub String);
impl fmt::Display for JobDataError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for JobDataError {}
pub(crate) fn fail(text: impl Into<String>) -> JobDataError {
    JobDataError(text.into())
}
fn file_source_key(path: &str, sheet: &str) -> String {
    let normalized = excel_identity(path, None);
    let path = normalized
        .split_once('\u{001f}')
        .map_or(normalized.as_str(), |(path, _)| path);
    if sheet.is_empty() {
        format!("file:{path}")
    } else {
        format!("file:{path}::{sheet}")
    }
}

pub struct MountDescriptor {
    pub label: String,
    pub source_kind: String,
    pub path: String,
    pub sheet: String,
    pub header_row: u64,
    pub kind: String,
    pub pool_key: String,
    pub data_key: String,
}
impl MountedData {
    /// A read failure leaves the prior mount and selections untouched.
    pub fn mount(
        &mut self,
        source: &mut dyn DataSource,
        descriptor: MountDescriptor,
        registry: Option<&DatasetPoolRegistry>,
    ) -> Result<(), JobDataError> {
        let fields = source.fields().map_err(|e| fail(e.0))?;
        let records = source.records().map_err(|e| fail(e.0))?;
        if records.is_empty() {
            return Err(fail("데이터에 행이 없습니다."));
        }
        let filter = FilterModel::new(
            records[0].keys().cloned().collect(),
            sniff_column_kinds(&records, &HashMap::new()),
        );
        let next_generation = self
            .snapshot_generation
            .checked_add(1)
            .ok_or_else(|| fail("snapshot_generation 넘침"))?;
        let next_epoch = self
            .zone_epoch
            .checked_add(1)
            .ok_or_else(|| fail("zone_epoch 넘침"))?;
        let last_filter = if let Some(filter) = self
            .filter
            .as_ref()
            .filter(|filter| filter.is_active() && !self.data_key.is_empty())
        {
            Some(StashedFilter {
                source_key: self.data_key.clone(),
                state: filter.export_state(),
                summary: filter
                    .view(&self.records)
                    .map_err(|error| fail(error.message))?
                    .describe(),
            })
        } else {
            self.last_filter.clone()
        };
        let mut prepared = Self {
            selection: SelectionModel::new(records.len(), false),
            filter: Some(filter),
            range_draft: None,
            hidden_columns: HashSet::new(),
            records,
            fields,
            label: descriptor.label,
            source_kind: descriptor.source_kind,
            path: descriptor.path,
            sheet: descriptor.sheet,
            header_row: descriptor.header_row,
            kind: descriptor.kind,
            pool_key: descriptor.pool_key,
            preset_key: String::new(),
            data_key: descriptor.data_key,
            last_filter,
            snapshot_generation: next_generation,
            zone_epoch: next_epoch,
            view_order: "sourceDesc".into(),
            notice_text: String::new(),
            notice_level: String::new(),
        };
        if let Some(registry) = registry {
            prepared.seed_presets(registry)?;
        }
        *self = prepared;
        Ok(())
    }
    pub fn mount_file_registered(
        &mut self,
        registry: &DatasetPoolRegistry,
        path: &Path,
        sheet: Option<&str>,
        header_row: usize,
    ) -> Result<(), JobDataError> {
        let mut source = source_for_path(path, sheet, header_row.max(1)).map_err(|e| {
            if path.exists() {
                fail(e.0)
            } else {
                fail(format!("{}: {}", e.0, path.display()))
            }
        })?;
        self.mount(
            source.as_mut(),
            MountDescriptor {
                label: path
                    .file_name()
                    .map(|item| item.to_string_lossy().into())
                    .unwrap_or_default(),
                source_kind: "file".into(),
                path: path.to_string_lossy().into(),
                sheet: sheet.unwrap_or("").into(),
                header_row: header_row as u64,
                kind: String::new(),
                pool_key: String::new(),
                data_key: file_source_key(&path.to_string_lossy(), sheet.unwrap_or("")),
            },
            Some(registry),
        )
        .map_err(|error| {
            let path_text = path.to_string_lossy();
            if !path.exists() && !error.0.contains(path_text.as_ref()) {
                fail(format!("{}: {}", error.0, path.display()))
            } else {
                error
            }
        })
    }
    pub fn mount_binding(
        &mut self,
        registry: &DatasetPoolRegistry,
        path: &str,
        sheet: &str,
        header_row: u64,
        kind: &str,
    ) -> Result<(), JobDataError> {
        let row = usize::try_from(header_row).map_err(|_| fail("머리글 행 범위가 너무 큽니다."))?;
        let mut source = source_for_binding(path, sheet, Some(row), kind).map_err(|error| {
            if Path::new(path).exists() {
                fail(error.0)
            } else {
                fail(format!("{}: {path}", error.0))
            }
        })?;
        let name = Path::new(path)
            .file_name()
            .map(|name| name.to_string_lossy().into_owned())
            .unwrap_or_else(|| path.into());
        let label = if kind == "pclm" && !sheet.is_empty() {
            format!("{name} · {sheet}")
        } else {
            name
        };
        let data_key = if kind == "pclm" {
            format!("pclm:{}", pclm_identity(path, sheet))
        } else {
            file_source_key(path, sheet)
        };
        self.mount(
            source.as_mut(),
            MountDescriptor {
                label,
                source_kind: if kind == "pclm" { "pclm" } else { "file" }.into(),
                path: path.into(),
                sheet: sheet.into(),
                header_row,
                kind: kind.into(),
                pool_key: String::new(),
                data_key,
            },
            Some(registry),
        )
        .map_err(|error| {
            if !Path::new(path).exists() && !error.0.contains(path) {
                fail(format!("{}: {path}", error.0))
            } else {
                error
            }
        })
    }
    pub fn mount_pool(
        &mut self,
        registry: &DatasetPoolRegistry,
        key: &str,
        sheet: Option<&str>,
    ) -> Result<(), JobDataError> {
        let item = registry.load(key).map_err(|error| match error {
            PoolError::Io(io_error) if io_error.kind() == std::io::ErrorKind::NotFound => {
                fail("등록 데이터를 찾을 수 없습니다(이미 삭제된 항목).")
            }
            PoolError::Codec(_) | PoolError::Invalid(_) => {
                fail("등록 데이터를 찾을 수 없습니다(이미 삭제된 항목).")
            }
            other => fail(other.to_string()),
        })?;
        if requires_nara_key(&item) {
            return Err(fail(
                "나라장터 소스는 현재 웹에서 지원되지 않습니다. 파일 또는 엑셀 참조 등록 데이터를 사용하세요.",
            ));
        }
        if item.kind == "excel"
            && item
                .opts
                .get("sheet")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("")
                .is_empty()
        {
            let path = item
                .opts
                .get("path")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("");
            if let Some(error) = ambiguous_sheet_error(
                Path::new(path),
                &format!(
                    "등록 데이터 '{}' 에 시트가 지정되지 않았습니다. ",
                    item.name
                ),
            ) {
                return Err(fail(error));
            }
        }
        let selected = reference_for_sheet(&item, sheet).map_err(|e| fail(e.0))?;
        let opts = serde_json::to_string(&item.opts).map_err(|error| fail(error.to_string()))?;
        let data_key = format!("pool:{key}:{}:{opts}", item.kind);
        let mut source = source_from_pool_item(&selected).map_err(|e| fail(e.0))?;
        let (path, active_sheet, header_row, kind) = binding_for_reference(&selected);
        self.mount(
            source.as_mut(),
            MountDescriptor {
                label: selected.name,
                source_kind: "pool".into(),
                path,
                sheet: active_sheet,
                header_row,
                kind,
                pool_key: key.into(),
                data_key,
            },
            Some(registry),
        )
    }
    /// Resolve the durable preset owner from the mounted source identity and seed definitions.
    /// Invalid or removed slots lose their preset home; other I/O errors remain visible.
    /// Only an actual pool mount is visible to the authoring proposal port.
    pub fn current_pool_source(&self) -> Option<(String, Option<String>)> {
        (!self.pool_key.is_empty()).then(|| {
            (
                self.pool_key.clone(),
                (!self.sheet.is_empty()).then(|| self.sheet.clone()),
            )
        })
    }
    /// The handoff uses the reference captured with these rows, never a fresh pool lookup.
    pub fn new_work_handoff(&self) -> (Value, String) {
        if self.source_kind.is_empty() {
            return (json!({}), "데이터를 먼저 고르세요.".into());
        }
        if self.path.is_empty() {
            return (
                json!({}),
                format!(
                    "'{}' 은 파일 참조가 아니어서 새 작업의 데이터로 열 수 없습니다. 엑셀·CSV 데이터를 고른 뒤 시작하세요.",
                    self.label
                ),
            );
        }
        (
            json!({
                "path": self.path,
                "sheet": self.sheet,
                "header_row": self.header_row,
                "kind": self.kind,
            }),
            String::new(),
        )
    }
    pub fn data_target(&self) -> Value {
        json!({
            "path": self.path,
            "sheet": self.sheet,
            "origin": self.source_kind,
            "kind": self.kind,
        })
    }
    pub fn set_all(&mut self) -> Result<usize, JobDataError> {
        let visible = {
            let filter = self.zone_filter()?;
            if filter.is_active() {
                Some(
                    filter
                        .visible_indices(&self.records)
                        .map_err(|error| fail(error.message))?,
                )
            } else {
                None
            }
        };
        let selected = self.zone_selection_mut();
        let before = selected.selected_count();
        if let Some(visible) = visible {
            for index in visible {
                selected
                    .toggle(index as isize, Some(true))
                    .map_err(|error| fail(error.0))?;
            }
        } else {
            selected.set_all();
        }
        Ok(selected.selected_count() - before)
    }
    pub fn set_none(&mut self) {
        self.zone_selection_mut().set_none();
    }
    pub fn hide_column(&mut self, column: &str) -> Result<(), JobDataError> {
        if !self
            .zone_filter()?
            .columns()
            .iter()
            .any(|name| name == column)
        {
            return Err(fail(format!(
                "숨길 수 없는 열입니다: {}",
                hwpx_filler::text_render::python_repr(&Value::String(column.into()))
            )));
        }
        if self.range_draft.is_some() {
            return Err(fail(
                "펼친 화면은 전체 열을 보여줍니다 — 열 숨기기는 인라인 표에서 하세요.",
            ));
        }
        self.hidden_columns.insert(column.into());
        Ok(())
    }
    pub fn unhide_columns(&mut self) {
        self.hidden_columns.clear();
    }
    pub fn visible_hidden_columns(&self) -> HashSet<String> {
        if self.range_draft.is_some() {
            HashSet::new()
        } else {
            self.hidden_columns.clone()
        }
    }
    pub fn selected_indices(&self) -> Vec<usize> {
        let mut indices = self.selection.selected_indices();
        if self.view_order == "sourceDesc" {
            indices.reverse();
        }
        indices
    }
    pub fn selected_records(&self) -> Vec<&Record> {
        self.selected_indices()
            .into_iter()
            .map(|index| &self.records[index])
            .collect()
    }
    /// Reports manual selection that neither the current filter nor a completed run explains.
    /// The committed range owns this guard even while a range draft is open.
    pub fn selection_guard(
        &self,
        settled: &HashSet<usize>,
        visible: Option<&HashSet<usize>>,
    ) -> Result<Value, JobDataError> {
        let selected = self
            .selection
            .selected_indices()
            .into_iter()
            .collect::<HashSet<_>>();
        let filter_active = self.filter.as_ref().is_some_and(FilterModel::is_active);
        let mut filter_parts = 0;
        if let Some(filter) = self.filter.as_ref().filter(|_| filter_active) {
            for column in filter.columns() {
                if filter
                    .has_condition(&column)
                    .map_err(|error| fail(error.message))?
                {
                    filter_parts += 1;
                }
            }
            filter_parts += usize::from(!filter.search_text().is_empty());
            filter_parts += filter
                .active_preset_groups()
                .map_err(|error| fail(error.message))?
                .len();
        }
        let (mut armed, mut in_def, mut extra) = (false, 0, 0);
        if !selected.is_empty() && selected != *settled && selected.len() != self.records.len() {
            if let Some(filter) = self.filter.as_ref().filter(|_| filter_active) {
                let computed;
                let matching = match visible {
                    Some(indices) => indices,
                    None => {
                        computed = filter
                            .visible_indices(&self.records)
                            .map_err(|error| fail(error.message))?
                            .into_iter()
                            .collect::<HashSet<_>>();
                        &computed
                    }
                };
                armed = selected != *matching;
                in_def = selected.intersection(matching).count();
                extra = selected.difference(matching).count();
            } else {
                armed = true;
            }
        }
        Ok(json!({
            "armed": armed,
            "sel_count": selected.len(),
            "in_def": in_def,
            "extra": extra,
            "filter_active": filter_active,
            "filter_parts": filter_parts,
        }))
    }
    pub fn toggle(&mut self, index: isize, value: Option<bool>) -> Result<(), SelectionError> {
        self.zone_selection_mut().toggle(index, value)
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_filler::data_source::{DataSourceError, InlineDataSource};
    use hwpx_filler::dataset_reference::{DatasetReference, FilterPreset};

    struct Failed;
    impl DataSource for Failed {
        fn fields(&mut self) -> Result<Vec<String>, DataSourceError> {
            Err(DataSourceError("read failed".into()))
        }
        fn records(&mut self) -> Result<Vec<Record>, DataSourceError> {
            panic!("must not read rows after field failure")
        }
    }
    #[test]
    fn successful_mount_replaces_snapshot_and_failed_mount_preserves_it() {
        let mut session = MountedData::default();
        let mut first = Record::new();
        first.insert("name".into(), "first".into());
        let mut second = Record::new();
        second.insert("name".into(), "second".into());
        let mut source = InlineDataSource::new(vec![first, second]);
        let descriptor = MountDescriptor {
            label: "Registered".into(),
            source_kind: "pool".into(),
            path: "data.xlsx".into(),
            sheet: "Sheet1".into(),
            header_row: 1,
            kind: String::new(),
            pool_key: "slot".into(),
            data_key: "slot".into(),
        };
        session.mount(&mut source, descriptor, None).unwrap();
        assert_eq!(
            session.current_pool_source(),
            Some(("slot".into(), Some("Sheet1".into())))
        );
        assert_eq!(
            session.new_work_handoff(),
            (
                json!({"path":"data.xlsx","sheet":"Sheet1","header_row":1,"kind":""}),
                String::new()
            )
        );
        assert_eq!(
            session.data_target(),
            json!({"path":"data.xlsx","sheet":"Sheet1","origin":"pool","kind":""})
        );
        let projected = session
            .zone_sections(&[], |index| json!({"index":index}))
            .unwrap();
        assert_eq!(projected.visible, vec![1, 0]);
        assert_eq!(projected.table["visible_count"], 2);
        assert_eq!(projected.filter["definition"], "");
        assert_eq!(
            session.filter_panel("name").unwrap()["options"],
            json!(["first", "second"])
        );
        assert_eq!(
            session
                .set_filter_range("name", Some(&json!({"op":"ge","operand":"1"})), None, None)
                .unwrap()["ok"],
            false
        );
        assert_eq!(
            session
                .count_filter_state(&json!({"search":"first"}))
                .unwrap()["count"],
            1
        );
        session.set_filter_text("name", "first").unwrap();
        assert_eq!(session.filter_view().unwrap().0, vec![0]);
        assert_eq!(
            session.filter_panel("name").unwrap()["options"],
            json!(["first"])
        );
        session.set_filter_values("name", Some(vec![])).unwrap();
        assert_eq!(session.filter_panel("name").unwrap()["checked"], json!([]));
        assert_eq!(
            session.filter_panel("name").unwrap()["options"],
            json!(["first"])
        );
        assert!(session.filter_view().unwrap().0.is_empty());
        session.set_filter_values("name", None).unwrap();
        assert_eq!(session.filter_view().unwrap().0, vec![0]);
        session.clear_filter_column("name").unwrap();
        session.toggle(0, Some(true)).unwrap();
        session.toggle(1, Some(true)).unwrap();
        assert_eq!(session.selected_indices(), vec![1, 0]);
        let snapshot = session.clone();
        assert!(
            session
                .mount(
                    &mut Failed,
                    MountDescriptor {
                        label: "broken".into(),
                        source_kind: String::new(),
                        path: String::new(),
                        sheet: String::new(),
                        header_row: 0,
                        kind: String::new(),
                        pool_key: String::new(),
                        data_key: String::new(),
                    },
                    None,
                )
                .is_err()
        );
        assert_eq!(session, snapshot);
        let mut empty = InlineDataSource::new(vec![]);
        let error = session
            .mount(
                &mut empty,
                MountDescriptor {
                    label: "empty".into(),
                    source_kind: "file".into(),
                    path: "empty.csv".into(),
                    sheet: String::new(),
                    header_row: 0,
                    kind: String::new(),
                    pool_key: String::new(),
                    data_key: "empty.csv".into(),
                },
                None,
            )
            .unwrap_err();
        assert_eq!(error.to_string(), "데이터에 행이 없습니다.");
        assert_eq!(session, snapshot);
        let directory = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .join(format!("hwpx-job-data-{}", uuid::Uuid::new_v4().simple()));
        std::fs::create_dir(&directory).unwrap();
        let registry = DatasetPoolRegistry::new(directory.clone()).unwrap();
        assert_eq!(
            session
                .mount_pool(&registry, "removed", None)
                .unwrap_err()
                .to_string(),
            "등록 데이터를 찾을 수 없습니다(이미 삭제된 항목)."
        );
        assert_eq!(session, snapshot);
        let mut reference = DatasetReference::new(
            "Saved",
            "excel",
            json!({"path":"data.xlsx","sheet":"Sheet1"})
                .as_object()
                .unwrap()
                .clone(),
        )
        .unwrap();
        reference.filters.push(FilterPreset {
            name: "first rows".into(),
            state: json!({"search":"first"}).as_object().unwrap().clone(),
        });
        let key = registry.add(&reference).unwrap();
        session.pool_key = key.clone();
        session.seed_presets(&registry).unwrap();
        assert_eq!(session.preset_key, key);
        assert_eq!(
            session.filter.as_ref().unwrap().presets()[0]["name"],
            "first rows"
        );
        assert_eq!(
            session
                .create_filter_preset(&registry, "second rows", &json!({"search":"second"}), false,)
                .unwrap(),
            "second rows"
        );
        assert_eq!(registry.load(&key).unwrap().filters.len(), 2);
        assert_registered_mount_preserves_session_on_preset_failure(&session, &directory);
        session.filter.as_mut().unwrap().clear();
        let durable_filter = session.filter.clone();
        std::fs::remove_dir_all(directory).unwrap();
        assert!(
            session
                .delete_filter_preset(&registry, "second rows")
                .is_err()
        );
        assert_eq!(session.filter, durable_filter);
        session.open_range_draft().unwrap();
        assert!(session.is_stale_edit("toggle_record", &json!({"epoch":session.zone_epoch - 1})));
        assert!(!session.is_stale_edit("toggle_record", &json!({"epoch":session.zone_epoch})));
        assert!(!session.is_stale_edit("filter_panel", &json!({"epoch":0})));
        session.toggle(1, Some(false)).unwrap();
        session.zone_filter_mut().unwrap().set_search("first");
        session.set_view_order("sourceAsc").unwrap();
        assert_eq!(session.selected_indices(), vec![1, 0]);
        assert_eq!(session.zone_indices(), vec![0]);
        assert_eq!(session.filter_view().unwrap().0, vec![0]);
        assert_eq!(session.range_draft_payload()["dirty"], true);
        session.cancel_range_draft();
        assert_eq!(session.selected_indices(), vec![1, 0]);
        assert_eq!(session.filter.as_ref().unwrap().search_text(), "");
        session.open_range_draft().unwrap();
        session.toggle(1, Some(false)).unwrap();
        session.zone_filter_mut().unwrap().set_search("first");
        session.set_view_order("sourceAsc").unwrap();
        session.apply_range_draft().unwrap();
        assert_eq!(session.selected_indices(), vec![0]);
        assert_eq!(session.filter.as_ref().unwrap().search_text(), "first");
        assert_eq!(session.view_order, "sourceAsc");
        let guard = session.selection_guard(&HashSet::new(), None).unwrap();
        assert_eq!(
            guard,
            json!({"armed":false,"sel_count":1,"in_def":1,"extra":0,"filter_active":true,"filter_parts":1})
        );
        session.filter.as_mut().unwrap().clear();
        assert_eq!(
            session.selection_guard(&HashSet::new(), None).unwrap()["armed"],
            true
        );
        assert_eq!(
            session.selection_guard(&HashSet::from([0]), None).unwrap()["armed"],
            false
        );
        session.set_filter_search("first").unwrap();
        let mut same_source_row = Record::new();
        same_source_row.insert("name".into(), "first".into());
        session
            .mount(
                &mut InlineDataSource::new(vec![same_source_row]),
                MountDescriptor {
                    label: "Registered".into(),
                    source_kind: "pool".into(),
                    path: "data.xlsx".into(),
                    sheet: "Sheet1".into(),
                    header_row: 1,
                    kind: String::new(),
                    pool_key: "slot".into(),
                    data_key: "slot".into(),
                },
                None,
            )
            .unwrap();
        assert!(session.reapply_available());
        assert_eq!(session.reapply_filter().unwrap()["ok"], true);
        assert_eq!(session.filter.as_ref().unwrap().search_text(), "first");
        assert_eq!(session.selection.selected_count(), 0);
    }

    fn assert_registered_mount_preserves_session_on_preset_failure(
        previous: &MountedData,
        directory: &Path,
    ) {
        let csv = directory.join("new.csv");
        std::fs::write(&csv, "name\nthird\nfourth\n").unwrap();
        let registry_root = directory.join("unreadable-registry");
        let registry = DatasetPoolRegistry::new(registry_root.clone()).unwrap();
        std::fs::write(&registry_root, b"not a directory").unwrap();
        for binding in [false, true] {
            let mut session = previous.clone();
            let result = if binding {
                session.mount_binding(&registry, csv.to_str().unwrap(), "", 0, "")
            } else {
                session.mount_file_registered(&registry, &csv, None, 0)
            };
            assert!(result.is_err(), "unreadable saved filters must be reported");
            assert_eq!(
                &session, previous,
                "reading rows must not commit before restoring saved filters"
            );
        }
        std::fs::remove_file(&registry_root).unwrap();
        std::fs::create_dir(&registry_root).unwrap();
        let mut reference = DatasetReference::new(
            "New data",
            "excel",
            json!({"path":csv,"sheet":""}).as_object().unwrap().clone(),
        )
        .unwrap();
        reference.filters.push(FilterPreset {
            name: "third".into(),
            state: json!({"search":"third"}).as_object().unwrap().clone(),
        });
        let key = registry.add(&reference).unwrap();
        for route in ["file", "binding", "pool"] {
            let mut session = previous.clone();
            match route {
                "file" => session.mount_file_registered(&registry, &csv, None, 0),
                "binding" => session.mount_binding(&registry, csv.to_str().unwrap(), "", 0, ""),
                _ => session.mount_pool(&registry, &key, None),
            }
            .unwrap();
            assert_eq!(session.records[0]["name"], "third");
            assert_eq!(
                session.snapshot_generation,
                previous.snapshot_generation + 1
            );
            assert_eq!(session.zone_epoch, previous.zone_epoch + 1);
            assert_eq!(session.selection.selected_count(), 0);
            assert_eq!(
                session.filter.as_ref().unwrap().presets()[0]["name"],
                "third"
            );
            assert_eq!(session.preset_key, key);
        }
    }
}
