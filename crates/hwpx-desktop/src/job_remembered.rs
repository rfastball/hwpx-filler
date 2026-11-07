//! Persist and restore the last successful Job data mount through workspace settings.

use super::*;
use hwpx_filler::structure_scan::python_trim;
use hwpx_filler::text_render::python_repr;
use serde_json::json;

struct BootRestoreGuard<'a>(&'a std::sync::atomic::AtomicBool);
impl Drop for BootRestoreGuard<'_> {
    fn drop(&mut self) {
        self.0.store(false, std::sync::atomic::Ordering::SeqCst);
    }
}

#[derive(Clone)]
struct RememberedSource {
    source: String,
    path: String,
    sheet: String,
    header_row: usize,
    pool_key: String,
}
impl RememberedSource {
    fn decode(raw: &Value) -> Option<Self> {
        let object = raw.as_object()?;
        let source = object.get("source")?.as_str()?;
        let path = object.get("path")?.as_str()?;
        let sheet = object.get("sheet")?.as_str()?;
        let pool_key = object.get("pool_key")?.as_str()?;
        let header_row = usize::try_from(object.get("header_row")?.as_u64()?).ok()?;
        if !matches!(source, "file" | "pool" | "pclm")
            || (source == "file" && path.is_empty())
            || (source == "pool" && pool_key.is_empty())
            || (source == "pclm" && (path.is_empty() || sheet.is_empty()))
        {
            return None;
        }
        Some(Self {
            source: source.into(),
            path: path.into(),
            sheet: sheet.into(),
            header_row,
            pool_key: pool_key.into(),
        })
    }
}

impl JobController {
    pub(super) fn remember_current_data_source(&self) -> Result<(), JobControllerError> {
        let descriptor = {
            let state = self.state()?;
            let data = &state.data;
            if data.source_kind.is_empty() {
                return Ok(());
            }
            match data.source_kind.as_str() {
                "file" if python_trim(&data.path).is_empty() => {
                    return Err(error("파일 마운트 기억에는 데이터 파일 경로가 필요합니다"));
                }
                "pool" if python_trim(&data.pool_key).is_empty() => {
                    return Err(error("등록 데이터 마운트 기억에는 슬롯 키가 필요합니다"));
                }
                "pclm"
                    if python_trim(&data.path).is_empty()
                        || python_trim(&data.sheet).is_empty() =>
                {
                    return Err(error("계약 목록 마운트 기억에는 DB 경로와 뷰가 필요합니다"));
                }
                "file" | "pool" | "pclm" => {}
                _ => {
                    return Err(error(format!(
                        "유효하지 않은 데이터 출처: {} (허용: ('file', 'pool', 'pclm'))",
                        python_repr(&json!(data.source_kind))
                    )));
                }
            }
            json!({"source":data.source_kind,"path":data.path,"sheet":data.sheet,
                "header_row":data.header_row,"pool_key":data.pool_key})
        };
        // The mount already succeeded; persistence failure must not undo its session memory.
        self.state()?.remembered_data_source = Some(descriptor.clone());
        settings_store::mutate(&self.settings_path, |settings| {
            settings.insert("last_data_source".into(), descriptor.clone());
        })
        .map_err(error)
    }

    /// First screen observation restores the remembered mount once, before rendering.
    pub fn initial(&self) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        self.boot_restore_in_progress
            .store(true, std::sync::atomic::Ordering::SeqCst);
        let _boot_guard = BootRestoreGuard(&self.boot_restore_in_progress);
        let (already_restored, has_source, remembered) = {
            let mut state = self.state()?;
            if state.boot_data_restored {
                (true, false, None)
            } else {
                state.boot_data_restored = true;
                let has_source = !state.data.source_kind.is_empty();
                (false, has_source, state.remembered_data_source.clone())
            }
        };
        if already_restored {
            return self.refresh_panel();
        }
        let mut discovery_refusal = String::new();
        let discovered = if let Some(discover) = &self.registered_data {
            match discover() {
                Ok(value) => value,
                Err(reason) => {
                    discovery_refusal =
                        format!("지난번에 사용한 데이터를 다시 불러오지 못했습니다. {reason}");
                    self.state()?.data.notice_text = discovery_refusal.clone();
                    self.state()?.data.notice_level = "warn".into();
                    None
                }
            }
        } else {
            None
        };
        let descriptor = remembered
            .or(discovered)
            .as_ref()
            .and_then(RememberedSource::decode);
        let candidate = if has_source { None } else { descriptor };
        if let Some(descriptor) = candidate {
            let refusal = self.restore_mount(&descriptor);
            let combined = [discovery_refusal.as_str(), refusal.as_deref().unwrap_or("")]
                .into_iter()
                .filter(|item| !item.is_empty())
                .collect::<Vec<_>>()
                .join("\n");
            if !combined.is_empty() {
                let mut state = self.state()?;
                state.data.notice_text = combined;
                state.data.notice_level = "warn".into();
            }
        }
        self.refresh_panel()
    }

    fn restore_mount(&self, descriptor: &RememberedSource) -> Option<String> {
        match descriptor.source.as_str() {
            "pool" => self
                .load_pool(&descriptor.pool_key, Some(&descriptor.sheet))
                .err()
                .map(|error| format!("지난번에 사용한 데이터를 다시 불러오지 못했습니다. {error}")),
            "file" | "pclm" if !Path::new(&descriptor.path).is_file() => Some(format!(
                "지난번에 사용한 데이터 파일을 찾을 수 없습니다: {}. 데이터를 다시 고르세요.",
                descriptor.path
            )),
            "file" => self
                .load_data_path(
                    &PathBuf::from(&descriptor.path),
                    (!descriptor.sheet.is_empty()).then_some(descriptor.sheet.as_str()),
                    descriptor.header_row,
                )
                .err()
                .map(|error| format!("지난번에 사용한 데이터를 다시 불러오지 못했습니다. {error}")),
            "pclm" => self
                .generation
                .with_mutation("데이터를 바꾸세요", || {
                    let mut state = self.state()?;
                    state
                        .data
                        .mount_binding(
                            &self.pool,
                            &descriptor.path,
                            &descriptor.sheet,
                            descriptor.header_row as u64,
                            "pclm",
                        )
                        .map_err(error)?;
                    self.restore_active_after_data_change(&mut state);
                    Ok(())
                })
                .map_err(error)
                .and_then(|result| result)
                .and_then(|()| self.remember_current_data_source())
                .err()
                .map(|error| format!("지난번에 사용한 데이터를 다시 불러오지 못했습니다. {error}")),
            _ => None,
        }
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn remembered_source_requires_complete_typed_mount_facts() {
        for (source, path, sheet, header_row, pool_key) in [
            ("file", "C:/d/발주.xlsx", "7월", 2, ""),
            ("pool", "", "", 0, "slot-7"),
            ("pclm", "C:/d/pclm.db", "v_통합_v1", 0, ""),
        ] {
            let raw = json!({"source":source,"path":path,"sheet":sheet,"header_row":header_row,"pool_key":pool_key});
            let decoded = RememberedSource::decode(&raw).unwrap();
            assert_eq!(
                (
                    decoded.source.as_str(),
                    decoded.path.as_str(),
                    decoded.sheet.as_str(),
                    decoded.header_row,
                    decoded.pool_key.as_str()
                ),
                (source, path, sheet, header_row, pool_key)
            );
            for key in ["source", "path", "sheet", "header_row", "pool_key"] {
                let mut incomplete = raw.clone();
                incomplete.as_object_mut().unwrap().remove(key);
                assert!(
                    RememberedSource::decode(&incomplete).is_none(),
                    "{key}: {raw}"
                );
            }
        }
        let base = json!({"source":"file","path":"p","sheet":"","header_row":0,"pool_key":""});
        assert!(RememberedSource::decode(&json!("손상")).is_none());
        for (key, value) in [
            ("source", json!("registry")),
            ("source", Value::Null),
            ("path", json!(3)),
            ("sheet", Value::Null),
            ("pool_key", json!(7)),
            ("header_row", json!("1")),
            ("header_row", json!(true)),
            ("header_row", json!(-1)),
            ("header_row", json!(1.5)),
            ("path", json!("")),
        ] {
            let mut raw = base.clone();
            raw[key] = value;
            assert!(RememberedSource::decode(&raw).is_none(), "{raw}");
        }
        for (source, path, sheet) in [
            ("pool", "p", ""),
            ("pclm", "", "v_통합_v1"),
            ("pclm", "p", ""),
        ] {
            let raw =
                json!({"source":source,"path":path,"sheet":sheet,"header_row":0,"pool_key":""});
            assert!(RememberedSource::decode(&raw).is_none(), "{raw}");
        }
    }
}
