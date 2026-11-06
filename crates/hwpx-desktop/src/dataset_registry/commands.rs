//! Dataset lifecycle commands. Confirmation and mutation share the registry writer gate.

use super::{DatasetPoolRegistry, PoolError};
use hwpx_filler::dataset_pool::{bound_state, confirm_basis};
use hwpx_filler::dataset_reference::{
    DatasetReference, excel_identity, excel_reference_opts, filter_presets_shape,
    reference_identity, reference_sheets,
};
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::{fs, io};

pub struct ExcelRelink<'a> {
    pub path: &'a str,
    pub sheet: Option<&'a str>,
    pub note: &'a str,
    pub name: &'a str,
    pub sheets: Option<&'a [String]>,
}

pub struct DatasetPoolCommands<'a> {
    pub(super) registry: &'a DatasetPoolRegistry,
}

impl DatasetPoolCommands<'_> {
    pub fn register_nara(
        &self,
        name: &str,
        bgn_dt: &str,
        end_dt: &str,
        num_rows: Option<i64>,
        page_no: Option<i64>,
        note: &str,
    ) -> Result<DatasetReference, PoolError> {
        let item = hwpx_filler::dataset_pool::nara_reference(
            name, bgn_dt, end_dt, num_rows, page_no, note,
        )?;
        self.registry.add(&item)?;
        Ok(item)
    }

    pub fn archive(&self, key: &str) -> Result<DatasetReference, PoolError> {
        self.registry.mutate(key, |item| {
            item.archive();
            Ok(())
        })
    }
    pub fn activate(&self, key: &str) -> Result<DatasetReference, PoolError> {
        self.registry.mutate(key, |item| {
            item.activate();
            Ok(())
        })
    }
    pub fn relabel(
        &self,
        key: &str,
        name: &str,
        note: &str,
    ) -> Result<DatasetReference, PoolError> {
        self.registry.mutate(key, |item| {
            item.name = name.into();
            if !note.is_empty() {
                item.note = note.into();
            }
            Ok(())
        })
    }
    pub fn reorder_sheets(
        &self,
        key: &str,
        sheets: &[String],
    ) -> Result<DatasetReference, PoolError> {
        self.registry.mutate(key, |item| {
            let current = reference_sheets(item)?;
            let unique: HashSet<_> = sheets.iter().collect();
            if sheets.len() != current.len()
                || unique.len() != current.len()
                || current.iter().any(|sheet| !unique.contains(sheet))
            {
                return Err(PoolError::Invalid(
                    "등록할 시트와 기본 시트를 확인하세요.".into(),
                ));
            }
            item.opts.insert(
                "sheets".into(),
                Value::Array(sheets.iter().cloned().map(Value::String).collect()),
            );
            Ok(())
        })
    }
    pub fn set_filters(
        &self,
        key: &str,
        filters: &Value,
        sheet: Option<&str>,
    ) -> Result<DatasetReference, PoolError> {
        self.registry.mutate(key, |item| {
            let presets = filter_presets_shape(filters)?;
            let default = item
                .opts
                .get(if item.kind == "excel" {
                    "sheet"
                } else {
                    "view"
                })
                .and_then(Value::as_str)
                .unwrap_or("");
            if sheet.is_none_or(|sheet| sheet == default)
                || !matches!(item.kind.as_str(), "excel" | "pclm")
            {
                item.filters = presets;
            } else if let Some(sheet) = sheet
                && reference_sheets(item)?.iter().any(|name| name == sheet)
            {
                item.sheet_filters.insert(
                    sheet.into(),
                    Value::Array(presets.iter().map(|preset| preset.to_dict()).collect()),
                );
            } else {
                return Err(PoolError::Invalid("등록된 시트를 선택하세요.".into()));
            }
            Ok(())
        })
    }
    pub fn relink_excel(
        &self,
        key: &str,
        path: &str,
        sheet: Option<&str>,
        note: &str,
        name: &str,
        sheets: Option<&[String]>,
    ) -> Result<DatasetReference, PoolError> {
        self.registry
            .lock
            .with(|| self.relink_excel_unlocked(key, path, sheet, note, name, sheets))
    }
    fn relink_excel_unlocked(
        &self,
        key: &str,
        path: &str,
        sheet: Option<&str>,
        note: &str,
        name: &str,
        sheets: Option<&[String]>,
    ) -> Result<DatasetReference, PoolError> {
        let opts = excel_reference_opts(path, sheet, sheets)?;
        let identity = excel_identity(path, sheet);
        if let Some((taken, existing)) = self
            .registry
            .scan(true, None)?
            .0
            .into_iter()
            .find(|(_, item)| reference_identity(item).as_deref() == Some(&identity))
            && taken != key
        {
            return Err(PoolError::Invalid(format!(
                "그 파일·시트는 이미 '{}' 으로 고정돼 있습니다. 그 항목을 쓰거나 먼저 정리하세요.",
                existing.name
            )));
        }
        let mut item = self.registry.load(key)?;
        replace_reference_opts(&mut item, opts, "excel")?;
        if !note.is_empty() {
            item.note = note.into();
        }
        if !name.is_empty() {
            item.name = name.into();
        }
        self.registry.write_at(key, &item)?;
        Ok(item)
    }
    pub fn relink_confirmed(
        &self,
        key: &str,
        request: &ExcelRelink<'_>,
        expected_basis: Option<&str>,
    ) -> Result<DatasetReference, PoolError> {
        self.registry.lock.with(|| {
            let current = self.slot_or_missing(key)?;
            check_basis(expected_basis, &[bound_state(key, &current)?])?;
            self.relink_excel_unlocked(
                key,
                request.path,
                request.sheet,
                request.note,
                request.name,
                request.sheets,
            )
        })
    }
    pub fn relabel_confirmed_raw(
        &self,
        identity: &str,
        name: &str,
        note: &str,
        sheets: Option<&[String]>,
        expected_basis: Option<&str>,
    ) -> Result<(String, DatasetReference), PoolError> {
        self.registry.lock.with(|| {
            let (key, mut current) =
                self.registry.find_identity_raw(identity)?.ok_or_else(|| {
                    PoolError::Invalid(format!("등록 데이터를 찾을 수 없습니다: {name}"))
                })?;
            check_basis(expected_basis, &[bound_state(&key, &current)?])?;
            if let Some(sheets) = sheets {
                let sheet_key = if current.kind == "excel" {
                    "sheet"
                } else {
                    "view"
                };
                let default = if current.kind == "pclm" {
                    current
                        .opts
                        .get(sheet_key)
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_owned()
                } else {
                    sheets.first().cloned().unwrap_or_default()
                };
                let mut opts = current.opts.clone();
                opts.insert(
                    "sheets".into(),
                    Value::Array(sheets.iter().cloned().map(Value::String).collect()),
                );
                opts.insert(sheet_key.into(), Value::String(default));
                let kind = current.kind.clone();
                replace_reference_opts(&mut current, opts, &kind)?;
            }
            current.name = name.into();
            if !note.is_empty() {
                current.note = note.into();
            }
            self.registry.write_at(&key, &current)?;
            Ok((key, current))
        })
    }
    pub fn relabel_confirmed(
        &self,
        path: &str,
        sheet: Option<&str>,
        name: &str,
        note: &str,
        sheets: Option<&[String]>,
        expected_basis: Option<&str>,
    ) -> Result<(String, DatasetReference), PoolError> {
        if sheets.is_none() {
            return self.relabel_confirmed_raw(
                &excel_identity(path, sheet),
                name,
                note,
                None,
                expected_basis,
            );
        }
        let opts = excel_reference_opts(path, sheet, sheets)?;
        self.registry.lock.with(|| {
            let (key, mut current) =
                self.registry.find_identity(path, sheet)?.ok_or_else(|| {
                    PoolError::Invalid(format!("등록 데이터를 찾을 수 없습니다: {name}"))
                })?;
            check_basis(expected_basis, &[bound_state(&key, &current)?])?;
            let mut merged = current.opts.clone();
            merged.extend(opts);
            replace_reference_opts(&mut current, merged, "excel")?;
            current.name = name.into();
            if !note.is_empty() {
                current.note = note.into();
            }
            self.registry.write_at(&key, &current)?;
            Ok((key, current))
        })
    }
    fn slot_or_missing(&self, key: &str) -> Result<DatasetReference, PoolError> {
        match self.registry.load(key) {
            Ok(item) => Ok(item),
            Err(PoolError::Io(error)) if error.kind() == io::ErrorKind::NotFound => Err(
                PoolError::Invalid(format!("등록 데이터를 찾을 수 없습니다: {key}")),
            ),
            Err(PoolError::Invalid(_) | PoolError::Codec(_)) => Err(PoolError::Invalid(format!(
                "등록 데이터를 찾을 수 없습니다: {key}"
            ))),
            Err(error) => Err(error),
        }
    }
    pub fn delete_confirmed(
        &self,
        key: &str,
        expected_basis: Option<&str>,
    ) -> Result<DatasetReference, PoolError> {
        self.registry.lock.with(|| {
            let item = self.slot_or_missing(key)?;
            check_basis(expected_basis, &[bound_state(key, &item)?])?;
            fs::remove_file(self.registry.slot_path(key)?)?;
            Ok(item)
        })
    }
    pub fn resolve_duplicates(
        &self,
        keep: &str,
        expected_basis: Option<&str>,
    ) -> Result<(String, usize), PoolError> {
        self.registry.lock.with(|| {
            let entries = self.registry.scan(true, None)?.0;
            let target = entries
                .iter()
                .find(|(key, _)| key == keep)
                .and_then(|(_, item)| reference_identity(item));
            let group = entries
                .into_iter()
                .filter(|(_, item)| {
                    target
                        .as_ref()
                        .is_some_and(|identity| reference_identity(item).as_ref() == Some(identity))
                })
                .collect::<Vec<_>>();
            if group.len() < 2 {
                return Err(PoolError::Invalid(
                    "병합할 중복 등록이 더는 없습니다.".into(),
                ));
            }
            let states = group
                .iter()
                .map(|(key, item)| bound_state(key, item))
                .collect::<Result<Vec<_>, _>>()?;
            check_basis(expected_basis, &states)?;
            let kept = group
                .iter()
                .find(|(key, _)| key == keep)
                .expect("kept member was in the group")
                .1
                .name
                .clone();
            let mut removed = 0;
            for (key, _) in group {
                if key != keep {
                    fs::remove_file(self.registry.slot_path(&key)?)?;
                    removed += 1;
                }
            }
            Ok((kept, removed))
        })
    }
}

fn check_basis(expected: Option<&str>, states: &[Map<String, Value>]) -> Result<(), PoolError> {
    if expected != Some(confirm_basis(states).as_str()) {
        return Err(PoolError::Stale("확인 근거가 지금 상태와 다릅니다.".into()));
    }
    Ok(())
}

fn replace_reference_opts(
    item: &mut DatasetReference,
    opts: serde_json::Map<String, Value>,
    kind: &str,
) -> Result<(), PoolError> {
    let key = if kind == "excel" { "sheet" } else { "view" };
    let previous = item.opts.get(key).and_then(Value::as_str);
    let current = opts.get(key).and_then(Value::as_str);
    if item.kind == kind
        && let Some(previous) = previous.filter(|name| !name.is_empty())
        && Some(previous) != current
    {
        item.sheet_filters.insert(
            previous.into(),
            Value::Array(item.filters.iter().map(|preset| preset.to_dict()).collect()),
        );
        item.filters = if let Some(current) = current
            && let Some(raw) = item.sheet_filters.remove(current)
        {
            filter_presets_shape(&raw)?
        } else {
            Vec::new()
        };
    }
    item.kind = kind.into();
    item.opts = opts;
    item.validate()?;
    Ok(())
}
