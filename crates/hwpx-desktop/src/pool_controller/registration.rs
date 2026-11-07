//! Excel/pclm registration and relink: refuse, ask to confirm, then run the confirmed command.
//!
//! Updating an existing registration shares one flow for both kinds: an unchanged request
//! re-pins it under the current basis, a changed one first returns the confirmation text,
//! and only a confirmed request runs the relabel with the basis the user saw.

use super::{PoolController, confirmed, missing_message};
use crate::dataset_registry::{ExcelRelink, PoolError};
use crate::workspace_switch::GraphError;
use hwpx_filler::dataset_pool::{bound_state, confirm_basis};
use hwpx_filler::dataset_reference::{
    DatasetReference, excel_reference_opts, pclm_identity, reference_sheets, resolve_pclm_db,
};
use serde_json::{Map, Value, json};
use std::path::Path;

type Relabeled = Result<(String, DatasetReference), PoolError>;

/// A request against an already registered entry, with what it would change.
struct RegistrationUpdate<'a> {
    key: &'a str,
    existing: &'a DatasetReference,
    name: &'a str,
    note: &'a str,
    sheets: Option<&'a [String]>,
    changes_sheets: bool,
    /// Excel refuses an empty name before relabeling; pclm passes it through.
    require_name: bool,
    /// pclm re-projects an open detail after relabeling; Excel does not.
    reproject: bool,
}

impl RegistrationUpdate<'_> {
    fn unchanged(&self) -> bool {
        let changes_name = !self.name.is_empty() && self.name != self.existing.name;
        let changes_note = !self.note.is_empty() && self.note != self.existing.note;
        !changes_name && !changes_note && !self.changes_sheets
    }
}

/// Whether a sheet selection would change the entry's stored sheets or its default
/// sheet field (`sheet` for Excel, `view` for pclm).
fn sheets_change(
    existing: &DatasetReference,
    selected: Option<&[String]>,
    field: &str,
    current: Option<&str>,
) -> bool {
    selected.is_some_and(|selected| {
        reference_sheets(existing).is_ok_and(|stored| stored != selected)
            || existing.opts.get(field).and_then(Value::as_str) != current
    })
}

/// The explicitly chosen pclm views; each must be named, include `view`, and exist in `db`.
fn selected_views(
    payload: &Map<String, Value>,
    view: &str,
    db: &str,
) -> Result<Option<Vec<String>>, String> {
    let Some(raw) = payload.get("views") else {
        return Ok(None);
    };
    let Some(values) = raw.as_array() else {
        return Err("읽을 시트를 고르세요.".into());
    };
    let selected = values.iter().filter_map(Value::as_str).collect::<Vec<_>>();
    if selected.len() != values.len()
        || selected.is_empty()
        || selected.iter().any(|name| name.is_empty())
        || !selected.contains(&view)
    {
        return Err("읽을 시트를 고르세요.".into());
    }
    let available =
        hwpx_filler::data_pclm::list_sqlite_sheets(db).map_err(|error| error.to_string())?;
    if selected
        .iter()
        .any(|name| !available.iter().any(|existing| existing == name))
    {
        return Err("시트를 찾을 수 없습니다. 파일을 다시 선택하세요.".into());
    }
    Ok(Some(selected.into_iter().map(str::to_owned).collect()))
}

/// A supplied pclm key must still name the same registration for this view.
fn stale_pclm_key(
    payload: &Map<String, Value>,
    same: Option<&(String, DatasetReference)>,
    view: &str,
) -> bool {
    payload
        .get("key")
        .and_then(Value::as_str)
        .is_some_and(|key| {
            !same.is_some_and(|(found, item)| {
                found == key && item.opts.get("view").and_then(Value::as_str) == Some(view)
            })
        })
}

/// A new pclm registration must name a view (and views) the contract list offers.
fn pclm_view_check(db: &str, view: &str, selected: Option<&[String]>) -> Result<(), String> {
    let available =
        hwpx_filler::data_pclm::list_sqlite_sheets(db).map_err(|error| error.to_string())?;
    if !available.iter().any(|name| name == view)
        || selected.is_some_and(|selected| {
            selected
                .iter()
                .any(|name| !available.iter().any(|existing| existing == name))
        })
    {
        let quoted = hwpx_filler::text_render::python_repr(&Value::String(view.into()));
        return Err(format!(
            "계약 목록이 약속한 뷰가 아닙니다: {quoted}\n쓸 수 있는 뷰:\n{}",
            available
                .iter()
                .map(|name| format!("  {name}"))
                .collect::<Vec<_>>()
                .join("\n")
        ));
    }
    Ok(())
}

fn pclm_opts(db: String, view: &str, selected: Option<Vec<String>>) -> Map<String, Value> {
    let mut opts = Map::new();
    opts.insert("db".into(), Value::String(db));
    opts.insert("view".into(), Value::String(view.into()));
    if let Some(selected) = selected {
        opts.insert("sheets".into(), json!(selected));
    }
    opts
}

impl PoolController {
    /// Records the column's success line, composed from the entry name and its summary.
    fn report_reference(
        &self,
        item: &DatasetReference,
        line: impl FnOnce(&str, &str) -> String,
    ) -> Result<(), GraphError> {
        let summary = hwpx_filler::dataset_pool::reference_summary(item)?;
        self.set_result(line(&item.name, &summary), "ok")
    }
    /// A refused confirmed command: a stale basis or the registry's own refusal.
    fn pool_refusal(&self, error: PoolError) -> Result<Value, GraphError> {
        match error {
            PoolError::Stale(_) => self.stale_basis(),
            error => self.refusal(error.to_string()),
        }
    }
    fn registration_sheets(
        payload: &Map<String, Value>,
    ) -> Result<(Option<String>, Option<Vec<String>>), String> {
        let mut sheet = payload
            .get("sheet")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .map(str::to_owned);
        let Some(selected) = payload.get("sheets") else {
            return Ok((sheet, None));
        };
        let path = payload.get("path").and_then(Value::as_str).unwrap_or("");
        let names = hwpx_filler::data_excel::sheet_overview(Path::new(path))
            .map_err(|error| error.to_string())?
            .into_iter()
            .map(|(name, _, _)| name)
            .collect::<Vec<_>>();
        let selected = selected.as_array().ok_or("읽을 시트를 고르세요.")?;
        if !names.is_empty() && selected.is_empty() {
            return Err("읽을 시트를 고르세요.".into());
        }
        let mut unique = Vec::new();
        for name in selected {
            let name = name
                .as_str()
                .ok_or("시트를 찾을 수 없습니다. 파일을 다시 선택하세요.")?;
            if !names.iter().any(|candidate| candidate == name) {
                return Err("시트를 찾을 수 없습니다. 파일을 다시 선택하세요.".into());
            }
            if !unique.iter().any(|candidate| candidate == name) {
                unique.push(name.into());
            }
        }
        if names.is_empty() {
            return Ok((None, None));
        }
        if sheet.is_none() {
            sheet = unique.first().cloned();
        }
        if !sheet.as_ref().is_some_and(|sheet| unique.contains(sheet)) {
            return Err("읽을 시트를 고르세요.".into());
        }
        Ok((sheet, Some(unique)))
    }

    pub(super) fn register_excel(&self, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let name = hwpx_filler::structure_scan::python_trim(
            payload.get("name").and_then(Value::as_str).unwrap_or(""),
        );
        let path = payload.get("path").and_then(Value::as_str).unwrap_or("");
        let note = payload.get("note").and_then(Value::as_str).unwrap_or("");
        let (sheet, sheets) = match Self::registration_sheets(payload) {
            Ok(value) => value,
            Err(error) => return self.refusal(error),
        };
        if !path.is_empty()
            && sheet.is_none()
            && let Some(error) = hwpx_filler::data_excel::ambiguous_sheet_error(Path::new(path), "")
        {
            return self.refusal(error);
        }
        let same = if path.is_empty() {
            None
        } else {
            self.registry.find_identity(path, sheet.as_deref())?
        };
        if let Some((key, existing)) = &same {
            let update = RegistrationUpdate {
                key,
                existing,
                name,
                note,
                sheets: sheets.as_deref(),
                changes_sheets: sheets_change(
                    existing,
                    sheets.as_deref(),
                    "sheet",
                    sheet.as_deref(),
                ),
                require_name: true,
                reproject: false,
            };
            return self.update_registration(&update, payload, |name, note, basis| {
                self.registry.commands().relabel_confirmed(
                    path,
                    sheet.as_deref(),
                    name,
                    note,
                    sheets.as_deref(),
                    basis,
                )
            });
        }
        self.add_excel(
            payload,
            name,
            path,
            note,
            sheet.as_deref(),
            sheets.as_deref(),
        )
    }

    fn add_excel(
        &self,
        payload: &Map<String, Value>,
        name: &str,
        path: &str,
        note: &str,
        sheet: Option<&str>,
        sheets: Option<&[String]>,
    ) -> Result<Value, GraphError> {
        if confirmed(payload) {
            return self.refusal(missing_message(name));
        }
        if name.is_empty() {
            return self.refusal("데이터셋 이름을 입력하세요.".into());
        }
        if path.is_empty() {
            return self.refusal("파일 경로가 비어 있습니다.".into());
        }
        let opts = match excel_reference_opts(path, sheet, sheets) {
            Ok(opts) => opts,
            Err(error) => return self.refusal(error.to_string()),
        };
        self.add_reference(name, "excel", opts, note)
    }

    pub(super) fn register_pclm(&self, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let name = hwpx_filler::structure_scan::python_trim(
            payload.get("name").and_then(Value::as_str).unwrap_or(""),
        );
        let view = payload.get("view").and_then(Value::as_str).unwrap_or("");
        let note = payload.get("note").and_then(Value::as_str).unwrap_or("");
        let db = match resolve_pclm_db(payload.get("db").and_then(Value::as_str).unwrap_or("")) {
            Ok(db) => db,
            Err(error) => return self.refusal(error.to_string()),
        };
        let selected = match selected_views(payload, view, &db) {
            Ok(selected) => selected,
            Err(message) => return self.refusal(message),
        };
        let identity = pclm_identity(&db, view);
        let same = self.registry.find_identity_raw(&identity)?;
        if stale_pclm_key(payload, same.as_ref(), view) {
            return self.refusal(missing_message(name));
        }
        if let Some((key, existing)) = &same {
            let update = RegistrationUpdate {
                key,
                existing,
                name,
                note,
                sheets: selected.as_deref(),
                changes_sheets: sheets_change(existing, selected.as_deref(), "view", Some(view)),
                require_name: false,
                reproject: true,
            };
            return self.update_registration(&update, payload, |name, note, basis| {
                self.registry.commands().relabel_confirmed_raw(
                    &identity,
                    name,
                    note,
                    selected.as_deref(),
                    basis,
                )
            });
        }
        self.add_pclm(payload, name, view, note, db, selected)
    }

    fn add_pclm(
        &self,
        payload: &Map<String, Value>,
        name: &str,
        view: &str,
        note: &str,
        db: String,
        selected: Option<Vec<String>>,
    ) -> Result<Value, GraphError> {
        if confirmed(payload) {
            return self.refusal(missing_message(name));
        }
        if name.is_empty() {
            return self.refusal("데이터셋 이름을 입력하세요.".into());
        }
        if let Err(message) = pclm_view_check(&db, view, selected.as_deref()) {
            return self.refusal(message);
        }
        self.add_reference(name, "pclm", pclm_opts(db, view, selected), note)
    }

    /// Re-pins an unchanged request, asks to confirm a changed one, and otherwise runs
    /// the confirmed relabel with the basis the user confirmed.
    fn update_registration(
        &self,
        update: &RegistrationUpdate<'_>,
        payload: &Map<String, Value>,
        relabel: impl Fn(&str, &str, Option<&str>) -> Relabeled,
    ) -> Result<Value, GraphError> {
        let basis = confirm_basis(&[bound_state(update.key, update.existing)?]);
        if update.unchanged() {
            return match relabel(&update.existing.name, "", Some(&basis)) {
                Ok((_, item)) => {
                    self.report_reference(&item, |name, summary| {
                        format!("이미 고정돼 있습니다: {name} ({summary})")
                    })?;
                    Ok(json!({"ok":true,"key":update.key,"name":item.name}))
                }
                Err(error) => self.pool_refusal(error),
            };
        }
        if !confirmed(payload) {
            return self.confirm_update(update, &basis);
        }
        if update.require_name && update.name.is_empty() {
            return self.refusal("데이터셋 이름을 입력하세요.".into());
        }
        match relabel(
            update.name,
            update.note,
            payload.get("basis").and_then(Value::as_str),
        ) {
            Ok((_, item)) => {
                if update.reproject {
                    self.reproject_open_detail(update.key)?;
                }
                self.report_reference(&item, |name, summary| {
                    format!("등록 데이터를 갱신했습니다: {name} ({summary})")
                })?;
                Ok(json!({"ok":true,"name":item.name}))
            }
            Err(error) => self.pool_refusal(error),
        }
    }

    fn confirm_update(
        &self,
        update: &RegistrationUpdate<'_>,
        basis: &str,
    ) -> Result<Value, GraphError> {
        let (key, existing, name) = (update.key, update.existing, update.name);
        let summary = hwpx_filler::dataset_pool::reference_summary(existing)?;
        let text = if update.changes_sheets {
            format!(
                "이 데이터는 이미 '{}' 으로 고정돼 있습니다({summary}).\n같은 등록을 유지하고 이름·메모·사용할 시트를 갱신합니다: '{name}'.\n사용할 시트: {}",
                existing.name,
                update.sheets.unwrap().join(", ")
            )
        } else {
            format!(
                "이 데이터는 이미 '{}' 으로 고정돼 있습니다({summary}).\n같은 등록을 유지하고 이름·메모를 갱신합니다: '{name}'.",
                existing.name
            )
        };
        Ok(
            json!({"ok":true,"needs_confirm":true,"key":key,"name":name,"basis":basis,"confirm_text":text}),
        )
    }

    fn add_reference(
        &self,
        name: &str,
        kind: &str,
        opts: Map<String, Value>,
        note: &str,
    ) -> Result<Value, GraphError> {
        let mut item = match DatasetReference::new(name, kind, opts) {
            Ok(item) => item,
            Err(error) => return self.refusal(error.to_string()),
        };
        item.note = note.into();
        if let Err(error) = self.registry.add(&item) {
            return self.refusal(error.to_string());
        }
        self.report_reference(&item, |name, summary| {
            format!("등록 데이터를 추가했습니다: {name} ({summary})")
        })?;
        Ok(json!({"ok":true,"name":item.name}))
    }

    pub(super) fn relink(&self, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let key = Self::required_string(payload, "key")?;
        let path = payload.get("path").and_then(Value::as_str).unwrap_or("");
        let note = payload.get("note").and_then(Value::as_str).unwrap_or("");
        let name = hwpx_filler::structure_scan::python_trim(
            payload.get("name").and_then(Value::as_str).unwrap_or(""),
        );
        let (sheet, sheets) = match Self::registration_sheets(payload) {
            Ok(value) => value,
            Err(error) => return self.refusal(error),
        };
        if path.is_empty() {
            return self.refusal("새 파일 경로가 비어 있습니다.".into());
        }
        if sheet.is_none()
            && let Some(error) = hwpx_filler::data_excel::ambiguous_sheet_error(Path::new(path), "")
        {
            return self.refusal(error);
        }
        if !confirmed(payload) {
            return self.confirm_relink(key, name, path, sheets.as_deref());
        }
        let request = ExcelRelink {
            path,
            sheet: sheet.as_deref(),
            note,
            name,
            sheets: sheets.as_deref(),
        };
        match self.registry.commands().relink_confirmed(
            key,
            &request,
            payload.get("basis").and_then(Value::as_str),
        ) {
            Ok(updated) => {
                self.reproject_open_detail(key)?;
                self.report_reference(&updated, |name, summary| {
                    format!("참조를 다시 연결했습니다: {name} ({summary})")
                })?;
                Ok(json!({"ok":true,"name":updated.name}))
            }
            Err(error) => self.pool_refusal(error),
        }
    }

    fn confirm_relink(
        &self,
        key: &str,
        name: &str,
        path: &str,
        sheets: Option<&[String]>,
    ) -> Result<Value, GraphError> {
        let item = match self.registry.load(key) {
            Ok(item) => item,
            Err(_) => {
                return self.refusal(missing_message(if name.is_empty() { key } else { name }));
            }
        };
        let rename = if !name.is_empty() && name != item.name {
            format!("\n이름도 '{}' → '{}' 으로 바뀝니다.", item.name, name)
        } else {
            String::new()
        };
        let sheets_clause = sheets
            .filter(|sheets| !sheets.is_empty())
            .map(|sheets| format!(" · {}", sheets.join(", ")))
            .unwrap_or_default();
        Ok(json!({
            "ok":true,"needs_confirm":true,"key":key,
            "basis":confirm_basis(&[bound_state(key,&item)?]),
            "confirm_text":format!(
                "'{}' 의 참조를 새 파일로 바꿉니다.\n기존: {}\n새 파일: {path}{sheets_clause}{}{}",
                item.name,hwpx_filler::dataset_pool::reference_summary(&item)?,
                hwpx_filler::dataset_pool::kind_transition_clause(&item),rename
            )
        }))
    }
}
