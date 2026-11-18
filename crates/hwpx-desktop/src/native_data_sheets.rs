//! `load_data_sheet` host verb: one chosen sheet mounts directly, several chosen sheets are
//! checked, registered as one pool entry, and mounted on the calling screen.

use super::{HostCall, NativeMethods};
use crate::workspace_runtime::RuntimeResources;
use crate::workspace_switch::ScreenController;
use hwpx_filler::data_source::DataSource;
use hwpx_filler::dataset_reference::DatasetReference;
use serde_json::{Value, json};
use std::path::Path;

type PoolMember = (String, DatasetReference);

const SCREEN_OR_FILE: &str = "데이터를 가져올 화면과 파일을 확인하세요.";

impl NativeMethods {
    pub(super) fn load_data_sheet(
        &self,
        resources: &RuntimeResources,
        call: &HostCall<'_>,
    ) -> Result<Value, String> {
        let screen = call.string(0)?;
        let path = call.string(1)?;
        if let Some(sheets) = call.args.get(2).and_then(Value::as_array) {
            let selected = self.register_data_sheets(
                resources,
                screen,
                Path::new(path),
                sheets,
                call.args.get(3),
            );
            return Ok(selected.unwrap_or_else(|error| json!(format!("ERROR: {error}"))));
        }
        if call.args.get(3).is_some_and(|value| !value.is_null()) {
            return Ok(json!("ERROR: 데이터를 가져올 화면과 파일을 확인하세요."));
        }
        let sheet = call.string(2)?;
        let selected = (|| -> Result<Value, String> {
            let names = hwpx_filler::data_excel::sheet_overview(Path::new(path))
                .map_err(|e| e.to_string())?;
            if !names.iter().any(|(name, _, _)| name == sheet) {
                return Err(format!(
                    "'{sheet}' 시트를 찾을 수 없습니다. 시트를 다시 선택하세요."
                ));
            }
            self.mount_data(resources, screen, Path::new(path), Some(sheet))
        })();
        Ok(selected.unwrap_or_else(|error| json!(format!("ERROR: {error}"))))
    }

    fn register_data_sheets(
        &self,
        resources: &RuntimeResources,
        screen: &str,
        path: &Path,
        sheets: &[Value],
        confirmation: Option<&Value>,
    ) -> Result<Value, String> {
        let basis = validate_sheet_request(screen, path, sheets, confirmation)?;
        let selected = requested_sheets(path, sheets)?;
        let path_text = path.to_string_lossy();
        let same = resources
            .datasets
            .find_identity(&path_text, selected.first().map(String::as_str))
            .map_err(|e| e.to_string())?;
        let mut rows = Vec::new();
        for name in &selected {
            let checked = check_sheet(path, name, same.as_ref());
            rows.push(json!({"name":name,"error":checked.err().unwrap_or_default()}));
        }
        let errors = sheet_errors(&rows);
        if !errors.is_empty() {
            return Ok(json!({"sheets":rows,"mount":null,"error":errors.join("\n")}));
        }
        let request = register_request(path, &path_text, &selected, same.as_ref(), basis);
        let registered = resources
            .pool
            .dispatch("register_excel", &request)
            .map_err(|e| e.to_string())?;
        if registered["needs_confirm"] == true {
            let mut response = json!({"sheets":[],"mount":null,"error":""});
            response
                .as_object_mut()
                .unwrap()
                .extend(registered.as_object().cloned().unwrap_or_default());
            return Ok(response);
        }
        if registered["ok"] != true {
            return Ok(json!({"sheets":rows,"mount":null,"error":registered["error"]}));
        }
        let (key, item) = resources
            .datasets
            .find_identity(&path_text, Some(&selected[0]))
            .map_err(|e| e.to_string())?
            .ok_or("등록 데이터를 찾을 수 없습니다. 다시 가져오세요.")?;
        for row in &mut rows {
            row["key"] = json!(key);
        }
        match self.mount_registered(resources, screen, path, &selected[0], &key, &item) {
            Ok(mount) => Ok(json!({"sheets":rows,"mount":mount,"error":""})),
            Err(error) => Ok(json!({"sheets":rows,"mount":null,"error":error})),
        }
    }

    /// Activates the just-registered pool entry on `screen` and describes the mount.
    fn mount_registered(
        &self,
        resources: &RuntimeResources,
        screen: &str,
        path: &Path,
        sheet: &str,
        key: &str,
        item: &DatasetReference,
    ) -> Result<Value, String> {
        match screen {
            "job" => resources
                .job
                .load_pool(key, Some(sheet))
                .map_err(|e| e.to_string())?,
            _ => {
                let result = resources
                    .editor
                    .dispatch("use_pool_data", &json!({"key":key}))
                    .map_err(|e| e.to_string())?;
                if result["ok"] != true {
                    return Err(result["error"]
                        .as_str()
                        .unwrap_or("등록 데이터를 활성화하지 못했습니다.")
                        .to_owned());
                }
            }
        }
        let mut descriptor = self.mount_data_descriptor(resources, screen, path, sheet)?;
        descriptor["label"] = json!(format!("등록 데이터: {}", item.name));
        Ok(descriptor)
    }

    fn mount_data_descriptor(
        &self,
        resources: &RuntimeResources,
        screen: &str,
        path: &Path,
        sheet: &str,
    ) -> Result<Value, String> {
        let rows = if screen == "job" {
            resources
                .job
                .data()
                .map_err(|e| e.to_string())?
                .records
                .len()
        } else {
            let mut source = hwpx_filler::data_factory::source_for_path(path, Some(sheet), 1)
                .map_err(|e| e.to_string())?;
            source.records().map_err(|e| e.to_string())?.len()
        };
        Ok(
            json!({"label":format!("파일: {}",path.file_name().unwrap_or_default().to_string_lossy()),
            "path":path.to_string_lossy(),"sheet":sheet,"rows":rows}),
        )
    }
}

/// Refuses an unknown screen, an empty path, a malformed confirmation, or an empty sheet
/// choice, in that order; returns the confirmed basis when one was supplied.
fn validate_sheet_request<'a>(
    screen: &str,
    path: &Path,
    sheets: &[Value],
    confirmation: Option<&'a Value>,
) -> Result<Option<&'a str>, String> {
    if !matches!(screen, "job" | "editor") || path.as_os_str().is_empty() {
        return Err(SCREEN_OR_FILE.into());
    }
    let basis = match confirmation {
        None | Some(Value::Null) => None,
        Some(Value::Object(map)) if map.len() == 1 => map.get("basis").and_then(Value::as_str),
        _ => return Err(SCREEN_OR_FILE.into()),
    };
    if confirmation.is_some_and(|value| !value.is_null()) && basis.is_none() {
        return Err(SCREEN_OR_FILE.into());
    }
    if sheets.is_empty()
        || sheets
            .iter()
            .any(|name| name.as_str().is_none_or(str::is_empty))
    {
        return Err("가져올 시트를 선택하세요.".into());
    }
    Ok(basis)
}

/// The requested sheets in workbook order; any name the workbook lacks is refused.
fn requested_sheets(path: &Path, sheets: &[Value]) -> Result<Vec<String>, String> {
    let names = hwpx_filler::data_excel::sheet_overview(path)
        .map_err(|e| e.to_string())?
        .into_iter()
        .map(|(name, _, _)| name)
        .collect::<Vec<_>>();
    let requested = sheets.iter().filter_map(Value::as_str).collect::<Vec<_>>();
    if requested
        .iter()
        .any(|name| !names.iter().any(|known| known == name))
    {
        return Err("시트를 찾을 수 없습니다. 파일을 다시 선택하세요.".into());
    }
    Ok(names
        .into_iter()
        .filter(|name| requested.contains(&name.as_str()))
        .collect())
}

/// Opens `name` the way the existing pool entry would (its reference when it already
/// covers the sheet, else its header row), or as a fresh file when nothing is registered.
fn sheet_source(
    path: &Path,
    name: &str,
    same: Option<&PoolMember>,
) -> Result<Box<dyn DataSource>, String> {
    let Some((_, item)) = same else {
        return hwpx_filler::data_factory::source_for_path(path, Some(name), 1)
            .map_err(|e| e.to_string());
    };
    if hwpx_filler::dataset_reference::reference_sheets(item)
        .map_err(|e| e.to_string())?
        .iter()
        .any(|sheet| sheet == name)
    {
        let reference = hwpx_filler::dataset_reference::reference_for_sheet(item, Some(name))
            .map_err(|e| e.to_string())?;
        return crate::nara_source::source_from_pool_reference_live(&reference)
            .map_err(|e| e.to_string());
    }
    hwpx_filler::data_factory::source_for_path(
        path,
        Some(name),
        item.opts
            .get("header_row")
            .and_then(Value::as_u64)
            .unwrap_or(1) as usize,
    )
    .map_err(|e| e.to_string())
}

/// One sheet must have rows, and an existing pool entry must not block selection.
fn check_sheet(path: &Path, name: &str, same: Option<&PoolMember>) -> Result<(), String> {
    let mut source = sheet_source(path, name, same)?;
    if source.records().map_err(|e| e.to_string())?.is_empty() {
        return Err("데이터에 행이 없습니다.".into());
    }
    if let Some((key, item)) = same {
        let row = hwpx_filler::dataset_pool::DatasetPoolRow::from_item(key, item, false)
            .map_err(|e| e.to_string())?;
        let reason = row.select_block_reason();
        if !reason.is_empty() {
            return Err(reason);
        }
    }
    Ok(())
}

fn sheet_errors(rows: &[Value]) -> Vec<String> {
    rows.iter()
        .filter_map(|row| {
            let error = row["error"].as_str().filter(|error| !error.is_empty())?;
            Some(format!("{}: {error}", row["name"].as_str().unwrap_or("")))
        })
        .collect()
}

fn register_request(
    path: &Path,
    path_text: &str,
    selected: &[String],
    same: Option<&PoolMember>,
    basis: Option<&str>,
) -> Value {
    let name = same.map_or_else(
        || {
            path.file_stem()
                .unwrap_or_default()
                .to_string_lossy()
                .into_owned()
        },
        |(_, item)| item.name.clone(),
    );
    let mut request = json!({"name":name,"path":path_text,"sheet":selected[0],"sheets":selected});
    if let Some(basis) = basis {
        request["confirm"] = json!(true);
        request["basis"] = json!(basis);
    }
    request
}
