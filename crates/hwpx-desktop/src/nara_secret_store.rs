//! Current-user Windows Credential Manager storage for the Nara ServiceKey.

pub const WINDOWS_TARGET_PREFIX: &str = "hwpx-tools/";
pub const WINDOWS_NARA_TARGET: &str = "hwpx-tools/nara-service-key";
#[cfg(windows)]
const INVALID_BLOB: &str = "저장된 자격증명 인코딩이 올바르지 않습니다.";

#[derive(Clone, Copy, Default)]
pub struct NaraSecretStore;

impl hwpx_filler::nara_acquire::SecretStorePort for NaraSecretStore {
    fn get(&self, name: &str) -> Result<Option<String>, String> {
        NaraSecretStore::get(self, name)
    }
    fn set(&self, name: &str, value: &str) -> Result<(), String> {
        NaraSecretStore::set(self, name, value)
    }
    fn delete(&self, name: &str) -> Result<(), String> {
        NaraSecretStore::delete(self, name)
    }
}

impl NaraSecretStore {
    pub fn target(name: &str) -> Result<String, String> {
        if name.is_empty() || name.contains('\0') {
            return Err("자격증명 이름이 올바르지 않습니다.".into());
        }
        Ok(format!("{WINDOWS_TARGET_PREFIX}{name}"))
    }
    pub fn get(&self, name: &str) -> Result<Option<String>, String> {
        let target = Self::target(name)?;
        #[cfg(windows)]
        {
            windows::get(&target)
        }
        #[cfg(not(windows))]
        {
            let _ = target;
            Err("Windows Credential Manager가 필요합니다.".into())
        }
    }
    pub fn set(&self, name: &str, value: &str) -> Result<(), String> {
        let target = Self::target(name)?;
        #[cfg(windows)]
        {
            windows::set(&target, value)
        }
        #[cfg(not(windows))]
        {
            let _ = (target, value);
            Err("Windows Credential Manager가 필요합니다.".into())
        }
    }
    pub fn delete(&self, name: &str) -> Result<(), String> {
        let target = Self::target(name)?;
        #[cfg(windows)]
        {
            windows::delete(&target)
        }
        #[cfg(not(windows))]
        {
            let _ = target;
            Err("Windows Credential Manager가 필요합니다.".into())
        }
    }
    pub fn has(&self, name: &str) -> Result<bool, String> {
        Ok(self.get(name)?.is_some())
    }
}

#[cfg(windows)]
mod windows {
    use std::ffi::c_void;
    use std::ptr;
    use windows_sys::Win32::Foundation::ERROR_NOT_FOUND;
    use windows_sys::Win32::Security::Credentials::{
        CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC, CREDENTIALW, CredDeleteW, CredFree,
        CredReadW, CredWriteW,
    };

    fn wide(text: &str) -> Vec<u16> {
        text.encode_utf16().chain([0]).collect()
    }
    fn error(step: &str) -> String {
        format!(
            "Credential Manager {step} 실패(Windows 코드 {}).",
            std::io::Error::last_os_error().raw_os_error().unwrap_or(0)
        )
    }
    pub(super) fn decode_blob(bytes: &[u8]) -> Result<String, String> {
        if !bytes.len().is_multiple_of(2) {
            return Err(super::INVALID_BLOB.into());
        }
        let words = bytes
            .chunks_exact(2)
            .map(|part| u16::from_le_bytes([part[0], part[1]]))
            .collect::<Vec<_>>();
        String::from_utf16(&words).map_err(|_| super::INVALID_BLOB.into())
    }
    pub(super) fn get(target: &str) -> Result<Option<String>, String> {
        let target = wide(target);
        let mut pointer: *mut CREDENTIALW = ptr::null_mut();
        if unsafe { CredReadW(target.as_ptr(), CRED_TYPE_GENERIC, 0, &mut pointer) } == 0 {
            if std::io::Error::last_os_error().raw_os_error() == Some(ERROR_NOT_FOUND as i32) {
                return Ok(None);
            }
            return Err(error("읽기"));
        }
        if pointer.is_null() {
            return Err("Credential Manager가 빈 자격증명 포인터를 반환했습니다.".into());
        }
        let result = unsafe {
            let credential = &*pointer;
            if credential.CredentialBlobSize == 0 {
                Ok(String::new())
            } else if credential.CredentialBlob.is_null() {
                Err(super::INVALID_BLOB.into())
            } else {
                let bytes = std::slice::from_raw_parts(
                    credential.CredentialBlob,
                    credential.CredentialBlobSize as usize,
                );
                decode_blob(bytes)
            }
        };
        unsafe {
            CredFree(pointer.cast::<c_void>());
        }
        result.map(Some)
    }
    pub(super) fn set(target: &str, value: &str) -> Result<(), String> {
        let mut target = wide(target);
        let mut blob = value
            .encode_utf16()
            .flat_map(u16::to_le_bytes)
            .collect::<Vec<u8>>();
        let size =
            u32::try_from(blob.len()).map_err(|_| "자격증명 값이 너무 깁니다.".to_owned())?;
        let credential = CREDENTIALW {
            Type: CRED_TYPE_GENERIC,
            TargetName: target.as_mut_ptr(),
            CredentialBlobSize: size,
            CredentialBlob: blob.as_mut_ptr(),
            Persist: CRED_PERSIST_LOCAL_MACHINE,
            ..Default::default()
        };
        if unsafe { CredWriteW(&credential, 0) } == 0 {
            return Err(error("저장"));
        }
        Ok(())
    }
    pub(super) fn delete(target: &str) -> Result<(), String> {
        let target = wide(target);
        if unsafe { CredDeleteW(target.as_ptr(), CRED_TYPE_GENERIC, 0) } == 0 {
            if std::io::Error::last_os_error().raw_os_error() == Some(ERROR_NOT_FOUND as i32) {
                return Ok(());
            }
            return Err(error("삭제"));
        }
        Ok(())
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    #[test]
    fn target_is_the_existing_credential_name() {
        assert_eq!(
            NaraSecretStore::target("nara-service-key").unwrap(),
            WINDOWS_NARA_TARGET
        );
        assert!(NaraSecretStore::target("bad\0name").is_err());
        assert!(NaraSecretStore::target("").is_err());
        #[cfg(windows)]
        {
            for value in ["", "aB3+xY/z9Q==pLm4Kn7", "한글키🔑"] {
                let bytes = value
                    .encode_utf16()
                    .flat_map(u16::to_le_bytes)
                    .collect::<Vec<_>>();
                assert_eq!(super::windows::decode_blob(&bytes).unwrap(), value);
            }
            for invalid in [&[0xff][..], &[0x00, 0xd8][..], &[0x00, 0xdc][..]] {
                assert_eq!(
                    super::windows::decode_blob(invalid).unwrap_err(),
                    super::INVALID_BLOB
                );
            }
        }
    }

    #[cfg(windows)]
    #[test]
    #[ignore = "native Windows credential store"]
    fn windows_credential_store_round_trip() {
        struct Cleanup(String);
        impl Drop for Cleanup {
            fn drop(&mut self) {
                let _ = NaraSecretStore.delete(&self.0);
            }
        }
        let name = format!("nara-service-key-rust-{}", uuid::Uuid::new_v4().simple());
        let store = NaraSecretStore;
        assert_eq!(store.get(&name).unwrap(), None);
        {
            let _cleanup = Cleanup(name.clone());
            for value in ["aB3+xY/z9Q==pLm4Kn7", "", "한글키🔑"] {
                store.set(&name, value).unwrap();
                assert_eq!(store.get(&name).unwrap().as_deref(), Some(value));
                assert!(store.has(&name).unwrap());
            }
            let oversized = "x".repeat(
                windows_sys::Win32::Security::Credentials::CRED_MAX_CREDENTIAL_BLOB_SIZE as usize,
            );
            let error = store.set(&name, &oversized).unwrap_err();
            assert!(error.contains("Credential Manager 저장 실패"));
            assert!(!error.contains(&oversized));
            assert_eq!(store.get(&name).unwrap().as_deref(), Some("한글키🔑"));
            store.set(&name, "REPLACED").unwrap();
            assert_eq!(store.get(&name).unwrap().as_deref(), Some("REPLACED"));
        }
        assert_eq!(store.get(&name).unwrap(), None);
        store.delete(&name).unwrap();
    }
}
