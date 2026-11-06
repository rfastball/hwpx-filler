//! Discover the registered contract-list workfile and its default pool source.

use crate::dataset_registry::DatasetPoolRegistry;
use hwpx_filler::data_pclm::registered_workfile_sheets;
use hwpx_filler::dataset_reference::{DatasetReference, STATUS_ACTIVE, pclm_identity};
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};

#[cfg(windows)]
const REGISTRATION: &str = "Software\\Classes\\Pclm.Workfile\\shell\\open\\command";

/// Read the v1 pointer without opening or changing the registered workfile.
pub fn read_workfile_config(path: &Path) -> Result<(String, String), String> {
    let bytes = fs::read(path).map_err(|error| format!("{error}: {}", path.display()))?;
    let bytes = bytes.strip_prefix(&[0xef, 0xbb, 0xbf]).unwrap_or(&bytes);
    let config: Value = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
    let valid = config
        .as_object()
        .and_then(|data| {
            let version = data.get("version")?;
            if version != 1 && version != true && version != 1.0 {
                return None;
            }
            let workfile = data.get("workfile")?.as_str()?;
            let dataset_id = data.get("datasetId")?.as_str()?;
            (Path::new(workfile).is_absolute() && !dataset_id.is_empty())
                .then(|| (workfile.to_owned(), dataset_id.to_owned()))
        })
        .ok_or_else(|| format!("계약 목록의 작업자료 설정을 확인하세요: {}", path.display()))?;
    Ok(valid)
}

#[cfg(windows)]
fn registered_command() -> Result<Option<String>, String> {
    use std::ptr;
    use windows_sys::Win32::Foundation::ERROR_FILE_NOT_FOUND;
    use windows_sys::Win32::System::Registry::{
        HKEY, HKEY_CURRENT_USER, KEY_READ, RegCloseKey, RegOpenKeyExW, RegQueryValueExW,
    };
    let mut key: HKEY = ptr::null_mut();
    let name = REGISTRATION
        .encode_utf16()
        .chain(Some(0))
        .collect::<Vec<_>>();
    let status = unsafe { RegOpenKeyExW(HKEY_CURRENT_USER, name.as_ptr(), 0, KEY_READ, &mut key) };
    if status == ERROR_FILE_NOT_FOUND {
        return Ok(None);
    }
    if status != 0 {
        return Err(std::io::Error::from_raw_os_error(status as i32).to_string());
    }
    struct Key(HKEY);
    impl Drop for Key {
        fn drop(&mut self) {
            unsafe { RegCloseKey(self.0) };
        }
    }
    let _guard = Key(key);
    let mut value_type = 0;
    let mut len = 0;
    let status = unsafe {
        RegQueryValueExW(
            key,
            ptr::null(),
            ptr::null(),
            &mut value_type,
            ptr::null_mut(),
            &mut len,
        )
    };
    if status != 0 {
        return Err(std::io::Error::from_raw_os_error(status as i32).to_string());
    }
    validate_command_value(value_type, len as usize)?;
    let mut bytes = vec![0_u8; len as usize];
    let status = unsafe {
        RegQueryValueExW(
            key,
            ptr::null(),
            ptr::null(),
            &mut value_type,
            bytes.as_mut_ptr(),
            &mut len,
        )
    };
    if status != 0 {
        return Err(std::io::Error::from_raw_os_error(status as i32).to_string());
    }
    decode_registered_command(value_type, &bytes[..len as usize]).map(Some)
}

#[cfg(windows)]
fn validate_command_value(value_type: u32, len: usize) -> Result<(), String> {
    use windows_sys::Win32::System::Registry::{REG_EXPAND_SZ, REG_SZ};
    if !matches!(value_type, REG_SZ | REG_EXPAND_SZ) || !len.is_multiple_of(2) || len > 64 * 1024 {
        return Err("계약 목록의 작업자료 설정을 확인하세요: Pclm.Workfile".into());
    }
    Ok(())
}

#[cfg(windows)]
fn decode_registered_command(value_type: u32, bytes: &[u8]) -> Result<String, String> {
    validate_command_value(value_type, bytes.len())?;
    let text = bytes
        .chunks_exact(2)
        .map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
        .take_while(|letter| *letter != 0)
        .collect::<Vec<_>>();
    String::from_utf16(&text).map_err(|error| error.to_string())
}

/// Query HKCU registration first. A missing registration leaves discovery inactive.
pub fn registered_workfile() -> Result<Option<(String, String)>, String> {
    #[cfg(not(windows))]
    {
        Ok(None)
    }
    #[cfg(windows)]
    {
        registered_workfile_at(registered_command(), || std::env::var_os("LOCALAPPDATA"))
    }
}

#[cfg(any(windows, test))]
fn registered_workfile_at(
    command: Result<Option<String>, String>,
    local: impl FnOnce() -> Option<std::ffi::OsString>,
) -> Result<Option<(String, String)>, String> {
    let Some(command) = command? else {
        return Ok(None);
    };
    if hwpx_filler::structure_scan::python_trim(&command).is_empty() {
        return Err("계약 목록의 작업자료 설정을 확인하세요: Pclm.Workfile".into());
    }
    let local = local()
        .filter(|value| !value.is_empty())
        .ok_or("계약 목록의 작업자료 설정을 확인하세요: LOCALAPPDATA")?;
    read_workfile_config(&PathBuf::from(local).join("Pclm/config.json")).map(Some)
}

/// Observe the registered default and add it only when no matching pool slot exists.
pub fn registered_data_source(
    pool: &DatasetPoolRegistry,
    located: Option<(String, String)>,
) -> Result<Option<Value>, String> {
    let Some((path, dataset_id)) = located else {
        return Ok(None);
    };
    let sheets =
        registered_workfile_sheets(&path, &dataset_id).map_err(|error| error.to_string())?;
    let first = sheets.first().ok_or("pclm 자료를 열지 못했습니다")?.clone();
    let key = match pool
        .find_identity_raw(&pclm_identity(&path, &first))
        .map_err(|error| error.to_string())?
    {
        Some((key, item)) if item.status == STATUS_ACTIVE => key,
        Some(_) => return Ok(None),
        None => {
            let item = DatasetReference::new(
                "계약 목록",
                "pclm",
                json!({"db":path,"view":first,"sheets":sheets})
                    .as_object()
                    .expect("literal object")
                    .clone(),
            )
            .map_err(|error| error.to_string())?;
            pool.add(&item).map_err(|error| error.to_string())?
        }
    };
    Ok(Some(json!({"source":"pool","path":path,"sheet":first,
        "pool_key":key,"header_row":0})))
}

/// Runtime entry point; callers in a practice workspace omit this callback entirely.
pub fn discover_registered_data(pool: &DatasetPoolRegistry) -> Result<Option<Value>, String> {
    registered_data_source(pool, registered_workfile()?)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(crate) mod tests {
    use super::*;

    pub(crate) fn assert_registered_workfile_pointer(
        root: &Path,
        workfile: &Path,
    ) -> (String, String) {
        let command = || Ok(Some("\"C:\\Apps\\계약목록.exe\" \"%1\"".into()));
        let local = || Some(root.as_os_str().to_owned());
        assert_eq!(
            registered_workfile_at(Ok(None), || panic!("unregistered app read environment"))
                .unwrap(),
            None
        );
        for error in ["registry access denied", "registered command missing"] {
            assert_eq!(
                registered_workfile_at(Err(error.into()), || panic!(
                    "failed registration read environment"
                ))
                .unwrap_err(),
                error
            );
        }
        for blank in ["", "  ", "\t\u{3000}\n"] {
            assert!(
                registered_workfile_at(Ok(Some(blank.into())), || panic!(
                    "invalid registration read environment"
                ))
                .unwrap_err()
                .contains("Pclm.Workfile")
            );
        }
        for local in [None, Some(std::ffi::OsString::new())] {
            assert!(
                registered_workfile_at(command(), || local)
                    .unwrap_err()
                    .contains("LOCALAPPDATA")
            );
        }
        let config = root.join("Pclm/config.json");
        fs::create_dir_all(config.parent().unwrap()).unwrap();
        let valid = json!({"version":1,"workfile":workfile,"datasetId":"source-id"});
        let expected = (
            workfile.to_str().unwrap().to_owned(),
            "source-id".to_owned(),
        );
        for version in [json!(1), json!(true), json!(1.0)] {
            let mut value = valid.clone();
            value["version"] = version;
            fs::write(&config, format!("\u{feff}{value}")).unwrap();
            assert_eq!(
                registered_workfile_at(command(), local).unwrap(),
                Some(expected.clone())
            );
        }
        for (key, invalid) in [
            ("version", json!(2)),
            ("version", json!(null)),
            ("version", json!("1")),
            ("workfile", json!("relative.pclm")),
            ("workfile", json!("")),
            ("workfile", json!(12)),
            ("datasetId", json!("")),
            ("datasetId", json!(null)),
            ("datasetId", json!(12)),
        ] {
            let mut value = valid.clone();
            value[key] = invalid;
            fs::write(&config, value.to_string()).unwrap();
            assert!(
                registered_workfile_at(command(), local)
                    .unwrap_err()
                    .contains("작업자료 설정"),
                "{value}"
            );
        }
        for value in [json!([]), json!({}), json!(null)] {
            fs::write(&config, value.to_string()).unwrap();
            assert!(
                registered_workfile_at(command(), local)
                    .unwrap_err()
                    .contains("작업자료 설정")
            );
        }
        for invalid in [b"{bad json".as_slice(), b"\xff"] {
            fs::write(&config, invalid).unwrap();
            assert!(registered_workfile_at(command(), local).is_err());
        }
        fs::remove_file(&config).unwrap();
        assert!(
            registered_workfile_at(command(), local)
                .unwrap_err()
                .contains(config.to_str().unwrap())
        );
        // A pointer describes the workfile; discovery must not open or create it.
        let absent = root.join("not-created.pclm");
        let mut value = valid.clone();
        value["workfile"] = json!(absent);
        fs::write(&config, value.to_string()).unwrap();
        assert_eq!(
            registered_workfile_at(command(), local).unwrap().unwrap().0,
            absent.to_str().unwrap()
        );
        assert!(!absent.exists());
        fs::write(&config, valid.to_string()).unwrap();
        #[cfg(windows)]
        assert_command_value_decoding();
        #[cfg(not(windows))]
        assert_eq!(registered_workfile().unwrap(), None);
        expected
    }

    #[cfg(windows)]
    fn assert_command_value_decoding() {
        use windows_sys::Win32::System::Registry::{REG_DWORD, REG_EXPAND_SZ, REG_SZ};
        let command = "\"C:\\Apps\\계약목록.exe\" \"%1\"";
        let mut encoded = command
            .encode_utf16()
            .flat_map(u16::to_le_bytes)
            .collect::<Vec<_>>();
        for kind in [REG_SZ, REG_EXPAND_SZ] {
            assert_eq!(decode_registered_command(kind, &encoded).unwrap(), command);
        }
        encoded.extend_from_slice(&[0, 0]);
        assert_eq!(
            decode_registered_command(REG_SZ, &encoded).unwrap(),
            command
        );
        assert_eq!(decode_registered_command(REG_SZ, &[]).unwrap(), "");
        for (kind, bytes) in [
            (REG_DWORD, vec![0; 4]),
            (REG_SZ, vec![0]),
            (REG_SZ, vec![0; 65_538]),
        ] {
            assert!(
                decode_registered_command(kind, &bytes)
                    .unwrap_err()
                    .contains("Pclm.Workfile")
            );
        }
        assert!(decode_registered_command(REG_SZ, &[0, 0xd8]).is_err());
    }
}
