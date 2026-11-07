//! Shared HWPX resource limits and diagnostics for byte and file admission.

use super::PackageError;
pub(super) const MIB: u64 = 1024 * 1024;

#[derive(Clone, Copy, Debug)]
pub struct PackageLimits {
    pub max_archive_bytes: u64,
    pub max_directory_signatures: usize,
    pub max_entries: usize,
    pub max_entry_bytes: u64,
    pub max_total_bytes: u64,
    pub max_compression_ratio: u64,
    pub ratio_min_entry_bytes: u64,
}

impl Default for PackageLimits {
    fn default() -> Self {
        Self {
            max_archive_bytes: 1024 * MIB,
            max_directory_signatures: 65536,
            max_entries: 4096,
            max_entry_bytes: 256 * MIB,
            max_total_bytes: 1024 * MIB,
            max_compression_ratio: 500,
            ratio_min_entry_bytes: MIB,
        }
    }
}

pub(super) fn budget(
    dimension: &'static str,
    observed: u64,
    limit: u64,
    detail: impl FnOnce() -> String,
) -> Result<(), PackageError> {
    if observed > limit {
        Err(PackageError::Budget {
            dimension,
            observed,
            limit,
            detail: detail(),
        })
    } else {
        Ok(())
    }
}

pub(super) fn fmt_bytes(size: u64) -> String {
    if size >= MIB {
        format!("{:.1} MiB", size as f64 / MIB as f64)
    } else {
        format!("{size} B")
    }
}

impl PackageLimits {
    pub fn check_archive_size(&self, size: u64) -> Result<(), PackageError> {
        budget("archive_bytes", size, self.max_archive_bytes, || {
            format!(
                "파일 크기 {} > {}",
                fmt_bytes(size),
                fmt_bytes(self.max_archive_bytes)
            )
        })
    }
}
