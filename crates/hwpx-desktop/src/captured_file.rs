//! Stable exact-byte file capture from a pinned source path.

use hwpx_filler::candidate_revision::{
    MutableSourceBinding, SOURCE_BINDING_CHANGED, SOURCE_CAPTURE_ERROR, SourceCaptureError,
    StableCapture, TemplateSourceReader, blob_digest,
};
use serde_json::{Map, json};
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;
use std::sync::Arc;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FileIdentity {
    pub file_index: u64,
    pub volume_serial: u32,
    pub size: u64,
    pub mtime_ns: u64,
}
#[cfg(windows)]
fn file_identity(file: &File) -> Option<FileIdentity> {
    use std::mem::MaybeUninit;
    use std::os::windows::fs::MetadataExt;
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Storage::FileSystem::{
        BY_HANDLE_FILE_INFORMATION, GetFileInformationByHandle,
    };
    let mut info = MaybeUninit::<BY_HANDLE_FILE_INFORMATION>::uninit();
    if unsafe { GetFileInformationByHandle(file.as_raw_handle(), info.as_mut_ptr()) } == 0 {
        return None;
    }
    let info = unsafe { info.assume_init() };
    let meta = file.metadata().ok()?;
    Some(FileIdentity {
        file_index: (u64::from(info.nFileIndexHigh) << 32) | u64::from(info.nFileIndexLow),
        volume_serial: info.dwVolumeSerialNumber,
        size: meta.file_size(),
        mtime_ns: meta.last_write_time().checked_mul(100)?,
    })
}
#[cfg(not(windows))]
fn file_identity(file: &File) -> Option<FileIdentity> {
    let meta = file.metadata().ok()?;
    use std::os::unix::fs::MetadataExt;
    Some(FileIdentity {
        file_index: meta.ino(),
        volume_serial: u32::try_from(meta.dev()).ok()?,
        size: meta.size(),
        mtime_ns: u64::try_from(meta.mtime())
            .ok()?
            .checked_mul(1_000_000_000)?
            .checked_add(u64::try_from(meta.mtime_nsec()).ok()?)?,
    })
}
pub fn classify_capture_stability(
    pre: &FileIdentity,
    post: &FileIdentity,
    on_path: &FileIdentity,
    expected_generation: u64,
    probed_generation: u64,
) -> Option<&'static str> {
    if pre != post
        || (on_path.file_index, on_path.volume_serial) != (post.file_index, post.volume_serial)
    {
        return Some(SOURCE_CAPTURE_ERROR);
    }
    if expected_generation != probed_generation {
        return Some(SOURCE_BINDING_CHANGED);
    }
    None
}
fn capture_error(reason: &str) -> SourceCaptureError {
    SourceCaptureError {
        reason: reason.into(),
    }
}
pub struct FileTemplateSourceReader<P> {
    probe_generation: P,
}
impl<P> FileTemplateSourceReader<P>
where
    P: Fn(&str) -> Result<u64, SourceCaptureError>,
{
    pub fn new(probe_generation: P) -> Self {
        Self { probe_generation }
    }
    fn capture_inner(
        &self,
        binding: &MutableSourceBinding,
        interference: Option<&dyn Fn()>,
    ) -> Result<StableCapture, SourceCaptureError> {
        let path = Path::new(&binding.host_reference);
        let mut handle = File::open(path).map_err(|_| capture_error(SOURCE_CAPTURE_ERROR))?;
        let pre = file_identity(&handle).ok_or_else(|| capture_error(SOURCE_CAPTURE_ERROR))?;
        let mut bytes = Vec::new();
        handle
            .read_to_end(&mut bytes)
            .map_err(|_| capture_error(SOURCE_CAPTURE_ERROR))?;
        if let Some(interference) = interference {
            interference();
        }
        handle
            .seek(SeekFrom::Start(0))
            .map_err(|_| capture_error(SOURCE_CAPTURE_ERROR))?;
        let mut reread = Vec::new();
        handle
            .read_to_end(&mut reread)
            .map_err(|_| capture_error(SOURCE_CAPTURE_ERROR))?;
        let post = file_identity(&handle).ok_or_else(|| capture_error(SOURCE_CAPTURE_ERROR))?;
        let on_path_handle = File::open(path).map_err(|_| capture_error(SOURCE_CAPTURE_ERROR))?;
        let on_path =
            file_identity(&on_path_handle).ok_or_else(|| capture_error(SOURCE_CAPTURE_ERROR))?;
        let probed_generation = (self.probe_generation)(&binding.source_binding_id)?;
        if let Some(reason) =
            classify_capture_stability(&pre, &post, &on_path, binding.generation, probed_generation)
        {
            return Err(capture_error(reason));
        }
        if bytes != reread {
            return Err(capture_error(SOURCE_CAPTURE_ERROR));
        }
        let mut observed_metadata = Map::new();
        observed_metadata.insert("byte_length".into(), json!(bytes.len()));
        // Python reports UNIX nanoseconds; Windows FILETIME starts in 1601.
        #[cfg(windows)]
        let mtime_ns = post.mtime_ns.saturating_sub(11_644_473_600_000_000_000);
        #[cfg(not(windows))]
        let mtime_ns = post.mtime_ns;
        observed_metadata.insert("mtime_ns".into(), json!(mtime_ns));
        Ok(StableCapture {
            captured_content_digest: blob_digest(&bytes),
            exact_bytes: Arc::from(bytes),
            source_binding_id: binding.source_binding_id.clone(),
            source_binding_generation: binding.generation,
            capture_method: "file-handle-stable".into(),
            observed_metadata,
        })
    }
    pub fn capture_with_interference(
        &self,
        binding: &MutableSourceBinding,
        interference: &dyn Fn(),
    ) -> Result<StableCapture, SourceCaptureError> {
        self.capture_inner(binding, Some(interference))
    }
}
impl<P> TemplateSourceReader for FileTemplateSourceReader<P>
where
    P: Fn(&str) -> Result<u64, SourceCaptureError>,
{
    fn capture(
        &mut self,
        binding: &MutableSourceBinding,
    ) -> Result<StableCapture, SourceCaptureError> {
        self.capture_inner(binding, None)
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn capture_checks_identity_bytes_generation_and_missing_path() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-capture-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("template.hwpx");
        fs::write(&path, b"same size").unwrap();
        let binding = MutableSourceBinding {
            source_binding_id: "source".into(),
            media: "hwpx".into(),
            host_reference: path.to_string_lossy().into(),
            display_metadata: Map::new(),
            generation: 7,
        };
        let mut reader = FileTemplateSourceReader::new(|_| Ok(7));
        let stable = reader.capture(&binding).unwrap();
        assert_eq!(&*stable.exact_bytes, b"same size");
        assert_eq!(stable.captured_content_digest, blob_digest(b"same size"));
        let original_modified = fs::metadata(&path).unwrap().modified().unwrap();
        let overwritten = reader.capture_with_interference(&binding, &|| {
            fs::write(&path, b"overwrite").unwrap();
            fs::File::options()
                .write(true)
                .open(&path)
                .unwrap()
                .set_times(std::fs::FileTimes::new().set_modified(original_modified))
                .unwrap();
        });
        assert_eq!(
            fs::metadata(&path).unwrap().len(),
            b"same size".len() as u64
        );
        assert_eq!(
            fs::metadata(&path).unwrap().modified().unwrap(),
            original_modified
        );
        assert_eq!(overwritten.unwrap_err().reason, SOURCE_CAPTURE_ERROR);
        let mut repinned = FileTemplateSourceReader::new(|_| Ok(8));
        assert_eq!(
            repinned.capture(&binding).unwrap_err().reason,
            SOURCE_BINDING_CHANGED
        );
        fs::remove_file(&path).unwrap();
        assert_eq!(
            reader.capture(&binding).unwrap_err().reason,
            SOURCE_CAPTURE_ERROR
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn classifier_checks_replacement_even_when_metadata_matches() {
        let before = FileIdentity {
            file_index: 1,
            volume_serial: 2,
            size: 10,
            mtime_ns: 20,
        };
        let replaced = FileIdentity {
            file_index: 3,
            ..before.clone()
        };
        assert_eq!(
            classify_capture_stability(&before, &before, &replaced, 7, 7),
            Some(SOURCE_CAPTURE_ERROR)
        );
        assert_eq!(
            classify_capture_stability(&before, &before, &before, 7, 8),
            Some(SOURCE_BINDING_CHANGED)
        );
    }
}
