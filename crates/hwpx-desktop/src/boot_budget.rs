//! Host boot fallback and selftest deadline from the last completed WebView2 runtime.

pub const WARM_BOOT_SECONDS: u64 = 20;
pub const COLD_BOOT_SECONDS: u64 = 60;
pub const SELFTEST_ENGINE_SECONDS: u64 = 80;
pub const HARD_STOP_MARGIN_SECONDS: u64 = 60;
pub const SELFTEST_COLD_HARD_STOP_SECONDS: u64 =
    COLD_BOOT_SECONDS + SELFTEST_ENGINE_SECONDS + HARD_STOP_MARGIN_SECONDS;

#[derive(Clone, Debug)]
pub struct BootTiming {
    pub fallback_seconds: u64,
    pub reason: String,
    pub runtime_version: String,
}

impl BootTiming {
    pub fn new(seen: &str, runtime_version: String) -> Self {
        let (fallback_seconds, reason) = decide(seen, &runtime_version);
        Self {
            fallback_seconds,
            reason,
            runtime_version,
        }
    }

    pub fn hard_stop_seconds(&self) -> u64 {
        self.fallback_seconds + SELFTEST_ENGINE_SECONDS + HARD_STOP_MARGIN_SECONDS
    }
}

pub fn decide(seen: &str, current: &str) -> (u64, String) {
    if seen.is_empty() {
        return (COLD_BOOT_SECONDS, "첫 실행".into());
    }
    if !current.is_empty() && current != seen {
        return (
            COLD_BOOT_SECONDS,
            format!("런타임 교체({seen} → {current})"),
        );
    }
    (WARM_BOOT_SECONDS, "정상 부팅 이력 있음".into())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum RegistryRoot {
    Machine,
    User,
}

const RUNTIME_GUID: &str = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
const RUNTIME_BRANCHES: [(RegistryRoot, &str); 4] = [
    (
        RegistryRoot::Machine,
        "SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\",
    ),
    (
        RegistryRoot::Machine,
        "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\",
    ),
    (
        RegistryRoot::User,
        "SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\",
    ),
    (
        RegistryRoot::User,
        "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\",
    ),
];

fn runtime_version_from(mut read: impl FnMut(RegistryRoot, &str) -> Option<String>) -> String {
    for (root, branch) in RUNTIME_BRANCHES {
        let path = format!("{branch}{RUNTIME_GUID}");
        if let Some(value) = read(root, &path) {
            let version = value.trim();
            if !version.is_empty() {
                return version.into();
            }
        }
    }
    String::new()
}

#[cfg(windows)]
pub fn runtime_version() -> String {
    use windows_sys::Win32::System::Registry::{
        HKEY, HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, KEY_READ, REG_SZ, RegCloseKey, RegOpenKeyExW,
        RegQueryValueExW,
    };

    fn read(root: RegistryRoot, path: &str) -> Option<String> {
        let root: HKEY = match root {
            RegistryRoot::Machine => HKEY_LOCAL_MACHINE,
            RegistryRoot::User => HKEY_CURRENT_USER,
        };
        let path = path.encode_utf16().chain(Some(0)).collect::<Vec<_>>();
        let name = "pv".encode_utf16().chain(Some(0)).collect::<Vec<_>>();
        let mut key: HKEY = std::ptr::null_mut();
        if unsafe { RegOpenKeyExW(root, path.as_ptr(), 0, KEY_READ, &mut key) } != 0 {
            return None;
        }
        struct Key(HKEY);
        impl Drop for Key {
            fn drop(&mut self) {
                unsafe { RegCloseKey(self.0) };
            }
        }
        let _guard = Key(key);
        let mut kind = 0;
        let mut size = 0;
        if unsafe {
            RegQueryValueExW(
                key,
                name.as_ptr(),
                std::ptr::null(),
                &mut kind,
                std::ptr::null_mut(),
                &mut size,
            )
        } != 0
            || kind != REG_SZ
            || size == 0
            || size > 1024
            || size % 2 != 0
        {
            return None;
        }
        let mut bytes = vec![0u8; size as usize];
        if unsafe {
            RegQueryValueExW(
                key,
                name.as_ptr(),
                std::ptr::null(),
                &mut kind,
                bytes.as_mut_ptr(),
                &mut size,
            )
        } != 0
            || kind != REG_SZ
            || size as usize > bytes.len()
            || size % 2 != 0
        {
            return None;
        }
        let units = bytes[..size as usize]
            .chunks_exact(2)
            .map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
            .take_while(|unit| *unit != 0)
            .collect::<Vec<_>>();
        String::from_utf16(&units).ok()
    }
    runtime_version_from(read)
}

#[cfg(not(windows))]
pub fn runtime_version() -> String {
    String::new()
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn completed_runtime_narrows_only_matching_or_unknown_versions() {
        assert_eq!(decide("", ""), (60, "첫 실행".into()));
        assert_eq!(decide("unknown", ""), (20, "정상 부팅 이력 있음".into()));
        assert_eq!(decide("1", "2"), (60, "런타임 교체(1 → 2)".into()));
        assert_eq!(SELFTEST_COLD_HARD_STOP_SECONDS, 200);
        assert_eq!(BootTiming::new("1", "1".into()).hard_stop_seconds(), 160);
        assert_eq!(BootTiming::new("1", "2".into()).hard_stop_seconds(), 200);
    }

    #[test]
    fn runtime_version_skips_blank_values_and_handles_all_registry_misses() {
        let mut missed_roots = Vec::new();
        assert_eq!(
            runtime_version_from(|root, _| {
                missed_roots.push(root);
                None
            }),
            ""
        );
        assert_eq!(
            missed_roots,
            vec![
                RegistryRoot::Machine,
                RegistryRoot::Machine,
                RegistryRoot::User,
                RegistryRoot::User,
            ]
        );

        let mut values = ["", "  ", "\t", " 135.0.0 "].into_iter();
        let mut seen = 0;
        let value = runtime_version_from(|root, path| {
            seen += 1;
            assert_eq!(
                path,
                format!("{}{}", RUNTIME_BRANCHES[seen - 1].1, RUNTIME_GUID)
            );
            assert_eq!(root, RUNTIME_BRANCHES[seen - 1].0);
            Some(values.next().unwrap().into())
        });
        assert_eq!(value, "135.0.0");
        assert_eq!(seen, 4);
    }
}
