//! Snapshot facts the editor projection reads beside the session state.

use super::*;
use hwpx_filler::dataset_reference::DatasetReference;

impl EditorController {
    pub(super) fn template_live(&self, path: &str) -> Result<bool, GraphError> {
        let paths = discover_paths(&self.templates.path())?;
        let mut found = false;
        for candidate in paths {
            candidate.to_str().ok_or_else(|| {
                std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "template path is not Unicode",
                )
            })?;
            if candidate == Path::new(path) && !template_media(path).is_empty() {
                found = true;
            }
        }
        Ok(found)
    }
    pub(super) fn template_name(&self, path: &str) -> String {
        if path.is_empty() {
            String::new()
        } else {
            template_display_name(&self.templates.path(), path)
        }
    }
    pub(super) fn registered_data(
        &self,
        state: &EditorSessionState,
    ) -> Result<Option<(String, String)>, GraphError> {
        if state.data_path.is_empty() {
            return Ok(None);
        }
        let identity = if state.data_kind == "pclm" {
            pclm_identity(&state.data_path, &state.data_sheet)
        } else {
            excel_identity(&state.data_path, Some(&state.data_sheet))
        };
        Ok(self
            .datasets
            .find_identity_raw(&identity)
            .ok()
            .flatten()
            .map(|(key, item)| (key, item.name)))
    }
    pub(super) fn data_sheet_tabs(
        &self,
        state: &EditorSessionState,
        registered: Option<&(String, String)>,
    ) -> Vec<Value> {
        let key = sheet_tab_key(state, registered);
        if key.is_empty() || state.data_path.is_empty() {
            return Vec::new();
        }
        let item = match self.datasets.load(key) {
            Ok(item) => item,
            Err(PoolError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
                return Vec::new();
            }
            Err(error) => {
                return vec![json!({"key":key,"sheet":state.data_sheet,"active":true,
                "selectable":false,"reason":format!("⚠ 손상된 등록 데이터: {key}.dataset.json — {error}"),"damaged":true})];
            }
        };
        let path = registered_item_path(&item);
        if !registered_item_matches(state, &item, path) {
            return Vec::new();
        }
        let Ok(sheets) = reference_sheets(&item) else {
            return Vec::new();
        };
        let Ok(row) =
            DatasetPoolRow::from_item(key, &item, !path.is_empty() && !Path::new(path).exists())
        else {
            return Vec::new();
        };
        let reason = row.select_block_reason();
        sheets
            .into_iter()
            .filter(|sheet| !sheet.is_empty())
            .map(|sheet| {
                json!({
                    "key":key,"active":sheet==state.data_sheet,"sheet":sheet,
                    "selectable":reason.is_empty(),"reason":reason
                })
            })
            .collect()
    }
    pub(super) fn data_name(
        &self,
        state: &EditorSessionState,
        registered: Option<&(String, String)>,
    ) -> String {
        if state.data_path.is_empty() {
            return String::new();
        }
        registered.map(|pair| pair.1.clone()).unwrap_or_else(|| {
            Path::new(&state.data_path)
                .file_stem()
                .and_then(|name| name.to_str())
                .unwrap_or("")
                .into()
        })
    }
    pub(super) fn facts(
        &self,
        state: &EditorSessionState,
    ) -> Result<EditorSnapshotFacts, GraphError> {
        let registered = self.registered_data(state)?;
        let data_name = self.data_name(state, registered.as_ref());
        let data_row = if state.data_path.is_empty() || registered.is_some() {
            Value::Null
        } else {
            hwpx_filler::job_presentation::session_data_row(
                &data_name,
                &state.data_kind,
                &state.data_path,
                &state.data_sheet,
                state.data_header_row,
                state.records.len(),
            )
        };
        let template_key = Path::new(&state.template_path)
            .strip_prefix(self.templates.path())
            .ok()
            .map(|path| path.to_string_lossy().replace('\\', "/"))
            .unwrap_or_default();
        let output_folder =
            if state.template_path.is_empty() || template_media(&state.template_path) == "txt" {
                Value::Null
            } else {
                let remembered = self
                    .output_directory
                    .as_ref()
                    .map_or(Ok(String::new()), |read| read())?;
                let folder = hwpx_filler::output_folder_default::resolve_output_folder(
                    &remembered,
                    !remembered.is_empty() && Path::new(&remembered).is_dir(),
                    &state.template_path,
                );
                json!({"directory":folder.directory,"source":folder.source,
                "source_label":folder.source_label(),"notice":folder.notice})
            };
        Ok(EditorSnapshotFacts {
            template_name: self.template_name(&state.template_path),
            template_key,
            template_live: !state.template_path.is_empty()
                && self.template_live(&state.template_path)?,
            data_name,
            data_key: registered
                .as_ref()
                .map_or_else(String::new, |pair| pair.0.clone()),
            data_row,
            data_sheet_tabs: self.data_sheet_tabs(state, registered.as_ref()),
            output_folder,
            now: (self.clock)(),
        })
    }
}

/// The session's own pool key wins; otherwise the identity lookup's key names the tabs.
fn sheet_tab_key<'a>(
    state: &'a EditorSessionState,
    registered: Option<&'a (String, String)>,
) -> &'a str {
    if state.data_pool_key.is_empty() {
        registered.map_or("", |pair| pair.0.as_str())
    } else {
        &state.data_pool_key
    }
}

fn registered_item_path(item: &DatasetReference) -> &str {
    item.opts
        .get(if item.kind == "pclm" { "db" } else { "path" })
        .and_then(Value::as_str)
        .unwrap_or("")
}

/// A registration offers tabs only while it still names the session's kind and workbook.
fn registered_item_matches(
    state: &EditorSessionState,
    item: &DatasetReference,
    path: &str,
) -> bool {
    item.kind
        == (if state.data_kind.is_empty() {
            "excel"
        } else {
            &state.data_kind
        })
        && excel_identity(path, None) == excel_identity(&state.data_path, None)
}
