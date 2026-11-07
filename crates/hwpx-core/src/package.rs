//! Pure byte codec for the HWPX OCF container.

mod admission;
mod budget;
use admission::{check_metadata, decode_name, validate_name};
#[cfg(test)]
use budget::MIB;
pub use budget::PackageLimits;
use budget::{budget, fmt_bytes};

use std::collections::{HashMap, HashSet};
use std::io::{Cursor, Read, Seek, SeekFrom, Write};
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, DateTime, ZipArchive, ZipWriter};

pub const MIMETYPE_NAME: &str = "mimetype";
pub const MIMETYPE_VALUE: &[u8] = b"application/hwp+zip";
const CENTRAL_SIGNATURE: &[u8] = b"PK\x01\x02";

#[derive(Debug, PartialEq, Eq)]
pub enum PackageError {
    Invalid(String),
    Budget {
        dimension: &'static str,
        observed: u64,
        limit: u64,
        detail: String,
    },
}

/// Name/flag failures from the generic ZIP admission seam. Callers may map
/// these facts to their own product wording without parsing ZIP error text.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ZipNameIssue {
    UnsafeName {
        raw_name: String,
        effective_name: String,
    },
    DuplicateEffectiveName {
        effective_name: String,
    },
    UnsupportedCompression {
        raw_name: String,
    },
    UnsupportedFlags {
        raw_name: String,
    },
}

#[derive(Debug)]
pub enum ZipPreflightError {
    Name(ZipNameIssue),
    Package(PackageError),
}
impl std::fmt::Display for ZipPreflightError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Name(issue) => write!(f, "{issue:?}"),
            Self::Package(error) => error.fmt(f),
        }
    }
}
impl std::error::Error for ZipPreflightError {}

impl std::fmt::Display for PackageError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Invalid(message) => write!(f, "invalid HWPX: {message}"),
            Self::Budget { detail, .. } => write!(f, "HWPX 자원 한도 초과: {detail}"),
        }
    }
}
impl std::error::Error for PackageError {}

fn invalid(message: impl Into<String>) -> PackageError {
    PackageError::Invalid(message.into())
}

fn le16(bytes: &[u8], at: usize) -> Result<usize, PackageError> {
    let end = at
        .checked_add(2)
        .ok_or_else(|| invalid("ZIP offset overflow"))?;
    Ok(u16::from_le_bytes(
        bytes
            .get(at..end)
            .ok_or_else(|| invalid("truncated ZIP directory"))?
            .try_into()
            .unwrap(),
    ) as usize)
}

fn le32(bytes: &[u8], at: usize) -> Result<usize, PackageError> {
    let end = at
        .checked_add(4)
        .ok_or_else(|| invalid("ZIP offset overflow"))?;
    Ok(u32::from_le_bytes(
        bytes
            .get(at..end)
            .ok_or_else(|| invalid("truncated ZIP metadata"))?
            .try_into()
            .unwrap(),
    ) as usize)
}

fn le64(bytes: &[u8], at: usize) -> Result<usize, PackageError> {
    let end = at
        .checked_add(8)
        .ok_or_else(|| invalid("ZIP offset overflow"))?;
    usize::try_from(u64::from_le_bytes(
        bytes
            .get(at..end)
            .ok_or_else(|| invalid("truncated ZIP metadata"))?
            .try_into()
            .unwrap(),
    ))
    .map_err(|_| invalid("ZIP offset overflow"))
}

#[derive(Clone, Copy)]
struct DirectoryLocation {
    start: usize,
    archive_offset: usize,
    size: usize,
    entries: usize,
}

fn zip64_locations(blob: &[u8], search_start: usize) -> HashMap<usize, usize> {
    let mut wanted = HashSet::new();
    for end in search_start..=blob.len() - 22 {
        if end >= 20
            && blob.get(end..end + 4) == Some(b"PK\x05\x06".as_slice())
            && blob.get(end - 20..end - 16) == Some(b"PK\x06\x07".as_slice())
        {
            wanted.insert(end - 20);
        }
    }
    let mut found = HashMap::new();
    for at in 0..blob.len().saturating_sub(12) {
        if blob.get(at..at + 4) == Some(b"PK\x06\x06".as_slice())
            && let Ok(size) = le64(blob, at + 4)
        {
            if size < 44 {
                continue;
            }
            if let Some(end) = at.checked_add(12).and_then(|n| n.checked_add(size))
                && wanted.contains(&end)
            {
                found.insert(end, at);
            }
        }
    }
    found
}

fn directory_start(blob: &[u8]) -> Result<DirectoryLocation, PackageError> {
    if blob.len() < 22 {
        return Err(invalid("missing ZIP end directory"));
    }
    let search_start = blob.len().saturating_sub(65_557);
    let mut zip64 = None;
    for end in (search_start..=blob.len() - 22).rev() {
        if blob.get(end..end + 4) != Some(b"PK\x05\x06".as_slice()) {
            continue;
        }
        let comment = le16(blob, end + 20)?;
        if end + 22 + comment > blob.len() {
            continue;
        }
        let size = le32(blob, end + 12)?;
        let is_zip64 = size == u32::MAX as usize
            || le32(blob, end + 16)? == u32::MAX as usize
            || le16(blob, end + 10)? == u16::MAX as usize;
        if le16(blob, end + 4)? != 0 || le16(blob, end + 6)? != 0 {
            continue;
        }
        let (position, relative, size, entries) = if is_zip64 {
            let locator = end
                .checked_sub(20)
                .ok_or_else(|| invalid("missing ZIP64 locator"))?;
            if blob.get(locator..locator + 4) != Some(b"PK\x06\x07".as_slice()) {
                continue;
            }
            if le32(blob, locator + 4)? != 0 || le32(blob, locator + 16)? != 1 {
                continue;
            }
            let positions = zip64.get_or_insert_with(|| zip64_locations(blob, search_start));
            let Some(&position) = positions.get(&locator) else {
                continue;
            };
            let stored = le64(blob, locator + 8)?;
            if position < stored {
                continue;
            }
            let size = le64(blob, position + 40)?;
            if le32(blob, position + 16)? != 0
                || le32(blob, position + 20)? != 0
                || le64(blob, position + 24)? != le64(blob, position + 32)?
            {
                continue;
            }
            (
                position.checked_sub(size),
                le64(blob, position + 48)?,
                size,
                le64(blob, position + 32)?,
            )
        } else {
            if le16(blob, end + 8)? != le16(blob, end + 10)? {
                continue;
            }
            (
                end.checked_sub(size),
                le32(blob, end + 16)?,
                size,
                le16(blob, end + 10)?,
            )
        };
        if let Some(position) =
            position.filter(|&at| blob.get(at..at.saturating_add(4)) == Some(CENTRAL_SIGNATURE))
            && let Some(archive_offset) = position.checked_sub(relative)
        {
            if is_zip64 {
                let stored = le64(blob, end - 12)?;
                let actual = zip64
                    .as_ref()
                    .and_then(|positions| positions.get(&(end - 20)))
                    .copied();
                if actual.and_then(|at| at.checked_sub(stored)) != Some(archive_offset) {
                    continue;
                }
            }
            return Ok(DirectoryLocation {
                start: position,
                archive_offset,
                size,
                entries,
            });
        }
    }
    Err(invalid("missing ZIP central directory"))
}

fn local_header_offset(
    record: &[u8],
    extra_start: usize,
    extra_end: usize,
) -> Result<usize, PackageError> {
    let direct = le32(record, 42)?;
    if direct != u32::MAX as usize {
        return Ok(direct);
    }
    let mut at = extra_start;
    while extra_end - at >= 4 {
        let id = le16(record, at)?;
        let size = le16(record, at + 2)?;
        let end = at
            .checked_add(4)
            .and_then(|n| n.checked_add(size))
            .ok_or_else(|| invalid("ZIP extra field length overflow"))?;
        if end > extra_end {
            return Err(invalid("truncated ZIP extra field"));
        }
        if id == 1 {
            let mut field = at + 4;
            if le32(record, 24)? == u32::MAX as usize {
                field += 8;
            }
            if le32(record, 20)? == u32::MAX as usize {
                field += 8;
            }
            if field + 8 <= end {
                return le64(record, field);
            }
            return Err(invalid("missing ZIP64 local offset"));
        }
        at = end;
    }
    Err(invalid("missing ZIP64 local offset"))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PackageEntry {
    pub name: String,
    pub data: Vec<u8>,
    pub stored: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HwpxPackage {
    pub entries: Vec<PackageEntry>,
}

struct DirectoryEntry {
    name: String,
    original_name: String,
}

/// Central-directory names before and after a valid UnicodePath alias is applied.
/// Callers retain their own logical layout policy; `effective_name` is used to
/// reject collisions that a ZIP library's name index could otherwise collapse.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ZipPreflightName {
    pub raw_name: String,
    pub effective_name: String,
}

struct MetadataOverlay<'a> {
    original: &'a [u8],
    central_tail: Vec<u8>,
    position: u64,
}

impl Read for MetadataOverlay<'_> {
    fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
        let Ok(start) = usize::try_from(self.position) else {
            return Ok(0);
        };
        let count = if start < self.original.len() {
            let count = buffer.len().min(self.original.len() - start);
            buffer[..count].copy_from_slice(&self.original[start..start + count]);
            count
        } else {
            let at = start - self.original.len();
            let count = buffer.len().min(self.central_tail.len().saturating_sub(at));
            if count > 0 {
                buffer[..count].copy_from_slice(&self.central_tail[at..at + count]);
            }
            count
        };
        self.position += count as u64;
        Ok(count)
    }
}

impl Seek for MetadataOverlay<'_> {
    fn seek(&mut self, position: SeekFrom) -> std::io::Result<u64> {
        let total = (self.original.len() + self.central_tail.len()) as i128;
        let target = match position {
            SeekFrom::Start(at) => i128::from(at),
            SeekFrom::Current(by) => i128::from(self.position) + i128::from(by),
            SeekFrom::End(by) => total + i128::from(by),
        };
        self.position = u64::try_from(target).map_err(|_| {
            std::io::Error::new(std::io::ErrorKind::InvalidInput, "ZIP seek overflow")
        })?;
        Ok(self.position)
    }
}

/// Bounded central-directory name preflight for another ZIP-backed format.
/// It checks flags, compression, UTF-8/CP437/UnicodePath metadata, path safety,
/// and duplicate effective names. Payload CRC and local headers remain the
/// caller's ZIP reader responsibility.
pub fn preflight_zip_names(
    blob: &[u8],
    limits: PackageLimits,
) -> Result<Vec<ZipPreflightName>, PackageError> {
    preflight_zip_names_with_issue(blob, limits, &mut None)
}

/// The same bounded preflight with structured name/flag failures for another
/// ZIP-backed product. Other archive failures retain their original details.
pub fn preflight_zip_names_detailed(
    blob: &[u8],
    limits: PackageLimits,
) -> Result<Vec<ZipPreflightName>, ZipPreflightError> {
    let mut issue = None;
    preflight_zip_names_with_issue(blob, limits, &mut issue)
        .map_err(|error| issue.map_or(ZipPreflightError::Package(error), ZipPreflightError::Name))
}

fn preflight_zip_names_with_issue(
    blob: &[u8],
    limits: PackageLimits,
    issue: &mut Option<ZipNameIssue>,
) -> Result<Vec<ZipPreflightName>, PackageError> {
    limits.check_archive_size(blob.len() as u64)?;
    let signatures = blob.windows(4).filter(|s| *s == CENTRAL_SIGNATURE).count();
    budget(
        "directory_signatures",
        signatures as u64,
        limits.max_directory_signatures as u64,
        || {
            format!(
                "ZIP 디렉터리 서명 수 {signatures} > {}",
                limits.max_directory_signatures
            )
        },
    )?;
    let location = directory_start(blob)?;
    let (names, _) = preflight_directory(blob, location, limits, false, issue)?;
    Ok(names
        .into_iter()
        .map(|entry| ZipPreflightName {
            raw_name: entry.original_name,
            effective_name: entry.name,
        })
        .collect())
}

impl HwpxPackage {
    pub fn from_bytes(blob: &[u8], limits: PackageLimits) -> Result<Self, PackageError> {
        limits.check_archive_size(blob.len() as u64)?;
        let signatures = blob.windows(4).filter(|s| *s == CENTRAL_SIGNATURE).count();
        budget(
            "directory_signatures",
            signatures as u64,
            limits.max_directory_signatures as u64,
            || {
                format!(
                    "ZIP 디렉터리 서명 수 {signatures} > {}",
                    limits.max_directory_signatures
                )
            },
        )?;
        let location = directory_start(blob)?;
        let (names, central_tail) = preflight_directory(blob, location, limits, true, &mut None)?;
        let mut zip = ZipArchive::new(MetadataOverlay {
            original: blob,
            central_tail,
            position: 0,
        })
        .map_err(|e| invalid(e.to_string()))?;
        if names.len() != zip.len() {
            return Err(invalid("ZIP central directory entry count mismatch"));
        }
        check_metadata(blob, location.start, &mut zip, &names, limits)?;
        Ok(Self {
            entries: read_entries(&mut zip, &names)?,
        })
    }

    pub fn to_bytes(&self) -> Result<Vec<u8>, PackageError> {
        let first = self
            .entries
            .iter()
            .find(|e| e.name == MIMETYPE_NAME)
            .ok_or_else(|| invalid("missing mimetype"))?;
        if first.data != MIMETYPE_VALUE {
            return Err(invalid("wrong mimetype value"));
        }
        let mut seen = HashSet::new();
        for entry in &self.entries {
            validate_name(&entry.name)?;
            if !seen.insert(&entry.name) {
                return Err(invalid("duplicate ZIP entry"));
            }
        }
        let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
        let timestamp = DateTime::default();
        for entry in
            std::iter::once(first).chain(self.entries.iter().filter(|e| e.name != MIMETYPE_NAME))
        {
            let method = if entry.name == MIMETYPE_NAME || entry.stored {
                CompressionMethod::Stored
            } else {
                CompressionMethod::Deflated
            };
            let options = SimpleFileOptions::default()
                .compression_method(method)
                .last_modified_time(timestamp);
            writer
                .start_file(&entry.name, options)
                .map_err(|e| invalid(e.to_string()))?;
            writer
                .write_all(&entry.data)
                .map_err(|e| invalid(e.to_string()))?;
        }
        let bytes = writer
            .finish()
            .map_err(|e| invalid(e.to_string()))?
            .into_inner();
        Ok(bytes)
    }

    pub fn content_xml_names(&self) -> Vec<&str> {
        self.entries
            .iter()
            .filter_map(|entry| {
                let low = entry.name.to_ascii_lowercase();
                let base = low.rsplit('/').next().unwrap_or(&low);
                (base.ends_with(".xml")
                    && ["section", "header", "footer"]
                        .iter()
                        .any(|prefix| base.starts_with(prefix)))
                .then_some(entry.name.as_str())
            })
            .collect()
    }
}

fn preflight_directory(
    blob: &[u8],
    location: DirectoryLocation,
    limits: PackageLimits,
    require_mimetype: bool,
    issue: &mut Option<ZipNameIssue>,
) -> Result<(Vec<DirectoryEntry>, Vec<u8>), PackageError> {
    let mut offset = location.start;
    let mut names = Vec::new();
    let mut decoded_seen = HashSet::new();
    let mut central_tail = Vec::new();
    while blob.get(offset..offset.saturating_add(4)) == Some(CENTRAL_SIGNATURE) {
        let name_len = le16(blob, offset + 28)?;
        let extra_len = le16(blob, offset + 30)?;
        let comment_len = le16(blob, offset + 32)?;
        let end = offset
            .checked_add(46)
            .and_then(|n| n.checked_add(name_len))
            .and_then(|n| n.checked_add(extra_len))
            .and_then(|n| n.checked_add(comment_len))
            .ok_or_else(|| invalid("ZIP directory length overflow"))?;
        let record = blob
            .get(offset..end)
            .ok_or_else(|| invalid("truncated ZIP directory"))?;
        let raw = record[46..46 + name_len].to_vec();
        let flags = le16(record, 8)?;
        if flags & (0x01 | 0x40) != 0 {
            *issue = Some(ZipNameIssue::UnsupportedFlags {
                raw_name: decode_name(&raw, flags & 0x0800 != 0).unwrap_or_default(),
            });
            return Err(invalid("encrypted ZIP entry"));
        }
        if flags & 0x20 != 0 {
            *issue = Some(ZipNameIssue::UnsupportedFlags {
                raw_name: decode_name(&raw, flags & 0x0800 != 0).unwrap_or_default(),
            });
            return Err(invalid("unsupported ZIP flags"));
        }
        if !matches!(le16(record, 10)?, 0 | 8) {
            *issue = Some(ZipNameIssue::UnsupportedCompression {
                raw_name: decode_name(&raw, flags & 0x0800 != 0).unwrap_or_default(),
            });
            return Err(invalid("unsupported ZIP compression"));
        }
        let decoded = decode_name(&raw, flags & 0x0800 != 0)?;
        if !require_mimetype && let Err(error) = validate_name(&decoded) {
            *issue = Some(ZipNameIssue::UnsafeName {
                raw_name: decoded.clone(),
                effective_name: decoded,
            });
            return Err(error);
        }
        let mut effective = decoded.clone();
        let mut extra_shadow = record[46 + name_len..46 + name_len + extra_len].to_vec();
        let mut extra = 46 + name_len;
        let extra_end = extra + extra_len;
        while extra_end - extra >= 4 {
            let id = le16(record, extra)?;
            let size = le16(record, extra + 2)?;
            let next = extra
                .checked_add(4)
                .and_then(|at| at.checked_add(size))
                .ok_or_else(|| invalid("ZIP extra field length overflow"))?;
            if next > extra_end {
                return Err(invalid("truncated ZIP extra field"));
            }
            if id == 0x7075 {
                let shadow_at = extra - (46 + name_len);
                extra_shadow[shadow_at..shadow_at + 2].copy_from_slice(&0xffffu16.to_le_bytes());
                let body = &record[extra + 4..next];
                if body.len() < 5 {
                    return Err(invalid("corrupt UnicodePath extra field"));
                }
                let crc = u32::from_le_bytes(body[1..5].try_into().unwrap());
                if body[0] == 1 && crc == crc32fast::hash(&raw) {
                    let alias = std::str::from_utf8(&body[5..])
                        .map_err(|_| invalid("invalid UnicodePath UTF-8"))?;
                    if !alias.is_empty() {
                        effective = alias.to_owned();
                    }
                }
            }
            extra = next;
        }
        // CPython ignores a final 1–3 bytes that cannot form an extra-field header.
        // zip rejects some such tails, so omit only those bytes from its shadow directory.
        extra_shadow.truncate(extra - (46 + name_len));
        // Python ZipInfo normalizes Windows separators while reading archives.
        let name = effective
            .split('\0')
            .next()
            .unwrap_or("")
            .replace('\\', "/");
        if let Err(error) = validate_name(&name) {
            *issue = Some(ZipNameIssue::UnsafeName {
                raw_name: decoded.clone(),
                effective_name: name,
            });
            return Err(error);
        }
        if !decoded_seen.insert(name.clone()) {
            *issue = Some(ZipNameIssue::DuplicateEffectiveName {
                effective_name: name,
            });
            return Err(invalid("duplicate decoded ZIP entry"));
        }
        names.push(DirectoryEntry {
            name,
            original_name: decoded,
        });
        budget(
            "entries",
            names.len() as u64,
            limits.max_entries as u64,
            || format!("ZIP 엔트리 수 {} > {}", names.len(), limits.max_entries),
        )?;
        let synthetic_name = format!("__hwpx_{:04}", names.len() - 1);
        let local = local_header_offset(record, 46 + name_len, extra_end)?
            .checked_add(location.archive_offset)
            .ok_or_else(|| invalid("ZIP local offset overflow"))?;
        let local = u32::try_from(local).map_err(|_| invalid("ZIP local offset overflow"))?;
        let mut header = record[..46].to_vec();
        header[28..30].copy_from_slice(&(synthetic_name.len() as u16).to_le_bytes());
        header[30..32].copy_from_slice(&(extra_shadow.len() as u16).to_le_bytes());
        header[42..46].copy_from_slice(&local.to_le_bytes());
        central_tail.extend(header);
        central_tail.extend(synthetic_name.as_bytes());
        central_tail.extend(extra_shadow);
        central_tail.extend(&record[46 + name_len + extra_len..]);
        offset = end;
    }
    if names.is_empty() {
        return Err(invalid("ZIP central directory entry count mismatch"));
    }
    if require_mimetype && names[0].name != MIMETYPE_NAME {
        return Err(invalid("mimetype is not first"));
    }
    if names.len() != location.entries || offset != location.start + location.size {
        return Err(invalid("ZIP central directory entry count mismatch"));
    }
    let count = u16::try_from(names.len()).map_err(|_| invalid("ZIP entry count overflow"))?;
    let size = u32::try_from(central_tail.len()).map_err(|_| invalid("ZIP directory too large"))?;
    let start = u32::try_from(blob.len()).map_err(|_| invalid("ZIP archive too large"))?;
    central_tail.extend(b"PK\x05\x06");
    central_tail.extend([0; 4]);
    central_tail.extend(count.to_le_bytes());
    central_tail.extend(count.to_le_bytes());
    central_tail.extend(size.to_le_bytes());
    central_tail.extend(start.to_le_bytes());
    central_tail.extend([0; 2]);
    Ok((names, central_tail))
}

fn read_entries<R: Read + Seek>(
    zip: &mut ZipArchive<R>,
    names: &[DirectoryEntry],
) -> Result<Vec<PackageEntry>, PackageError> {
    let mut entries = Vec::with_capacity(names.len());
    for (index, name) in names.iter().enumerate() {
        let mut file = zip.by_index(index).map_err(|e| invalid(e.to_string()))?;
        let size = file.size();
        let mut data =
            Vec::with_capacity(usize::try_from(size).map_err(|_| invalid("entry too large"))?);
        let mut limited = (&mut file).take(size + 1);
        limited
            .read_to_end(&mut data)
            .map_err(|e| invalid(e.to_string()))?;
        if data.len() as u64 != size {
            return Err(PackageError::Budget {
                dimension: "declared_size",
                observed: data.len() as u64,
                limit: size,
                detail: format!(
                    "엔트리 {} 실제 {} B != 선언 {size} B",
                    crate::structural_boundary::python_string_repr(&name.name),
                    data.len()
                ),
            });
        }
        if index == 0 && data != MIMETYPE_VALUE {
            return Err(invalid("wrong mimetype value"));
        }
        entries.push(PackageEntry {
            name: name.name.clone(),
            data,
            stored: file.compression() == CompressionMethod::Stored,
        });
    }
    Ok(entries)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    fn small() -> Vec<u8> {
        HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: "mimetype".into(),
                    data: MIMETYPE_VALUE.into(),
                    stored: true,
                },
                PackageEntry {
                    name: "a.xml".into(),
                    data: b"hello".into(),
                    stored: true,
                },
                PackageEntry {
                    name: "b.xml".into(),
                    data: b"world".into(),
                    stored: false,
                },
            ],
        }
        .to_bytes()
        .unwrap()
    }

    fn central_positions(blob: &[u8]) -> Vec<usize> {
        blob.windows(4)
            .enumerate()
            .filter_map(|(i, s)| (s == CENTRAL_SIGNATURE).then_some(i))
            .collect()
    }

    fn raw_zip(entries: &[(&str, &[u8])]) -> Vec<u8> {
        let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
        for (name, data) in entries {
            writer
                .start_file(
                    *name,
                    SimpleFileOptions::default().compression_method(CompressionMethod::Stored),
                )
                .unwrap();
            writer.write_all(data).unwrap();
        }
        writer.finish().unwrap().into_inner()
    }

    fn add_unicode_path(blob: &mut Vec<u8>, index: usize, target: &[u8]) -> usize {
        let central = central_positions(blob)[index];
        let name_len = le16(blob, central + 28).unwrap();
        let extra_len = le16(blob, central + 30).unwrap();
        let raw = &blob[central + 46..central + 46 + name_len];
        let mut extra = vec![0x75, 0x70];
        extra.extend(((target.len() + 5) as u16).to_le_bytes());
        extra.push(1);
        extra.extend(crc32fast::hash(raw).to_le_bytes());
        extra.extend(target);
        blob[central + 30..central + 32]
            .copy_from_slice(&((extra_len + extra.len()) as u16).to_le_bytes());
        let at = central + 46 + name_len + extra_len;
        blob.splice(at..at, extra.iter().copied());
        let eocd = blob.windows(4).rposition(|s| s == b"PK\x05\x06").unwrap();
        let size = le32(blob, eocd + 12).unwrap();
        blob[eocd + 12..eocd + 16].copy_from_slice(&((size + extra.len()) as u32).to_le_bytes());
        at
    }

    #[test]
    fn central_extra_short_tail_is_ignored_with_or_without_unicode_path() {
        for alias in [false, true] {
            for tail in [vec![0x01], vec![0x01, 0x00], vec![0x01, 0x00, 0xff]] {
                let mut blob = small();
                if alias {
                    add_unicode_path(&mut blob, 2, b"alias.xml");
                }
                let central = central_positions(&blob)[2];
                let name_len = le16(&blob, central + 28).unwrap();
                let extra_len = le16(&blob, central + 30).unwrap();
                let insert_at = central + 46 + name_len + extra_len;
                blob.splice(insert_at..insert_at, tail.iter().copied());
                blob[central + 30..central + 32]
                    .copy_from_slice(&((extra_len + tail.len()) as u16).to_le_bytes());
                let eocd = blob
                    .windows(4)
                    .rposition(|bytes| bytes == b"PK\x05\x06")
                    .unwrap();
                let central_size = le32(&blob, eocd + 12).unwrap();
                blob[eocd + 12..eocd + 16]
                    .copy_from_slice(&((central_size + tail.len()) as u32).to_le_bytes());
                let package = HwpxPackage::from_bytes(&blob, PackageLimits::default()).unwrap();
                assert_eq!(
                    package.entries[2].name,
                    if alias { "alias.xml" } else { "b.xml" }
                );
                assert_eq!(package.entries[2].data, b"world");
            }
        }
    }

    #[test]
    fn fixture_roundtrip_keeps_order_and_stored_entries() {
        let fixture = include_bytes!("../../../tests/fixtures/template_v1.hwpx");
        let package = HwpxPackage::from_bytes(fixture, PackageLimits::default()).unwrap();
        let names: Vec<_> = package.entries.iter().map(|e| e.name.as_str()).collect();
        assert_eq!(names.first(), Some(&MIMETYPE_NAME));
        assert!(!package.content_xml_names().is_empty());
        let names_only = HwpxPackage {
            entries: [
                "Contents/section0.xml",
                "header1.xml",
                "Footer2.XML",
                "Contents/content.hpf",
                "Contents/styles.xml",
                "Preview/PrvText.txt",
            ]
            .into_iter()
            .map(|name| PackageEntry {
                name: name.into(),
                data: Vec::new(),
                stored: false,
            })
            .collect(),
        };
        assert_eq!(
            names_only.content_xml_names(),
            ["Contents/section0.xml", "header1.xml", "Footer2.XML"]
        );
        let normalized = package.to_bytes().unwrap();
        assert_eq!(normalized, package.to_bytes().unwrap());
        let again = HwpxPackage::from_bytes(&normalized, PackageLimits::default()).unwrap();
        assert_eq!(package.entries, again.entries);
        assert_eq!(again.to_bytes().unwrap(), normalized);
        let mut zip = ZipArchive::new(Cursor::new(normalized)).unwrap();
        assert_eq!(zip.name_for_index(0), Some(MIMETYPE_NAME));
        for index in 0..zip.len() {
            let file = zip.by_index(index).unwrap();
            let time = file.last_modified().unwrap();
            assert_eq!(
                (
                    time.year(),
                    time.month(),
                    time.day(),
                    time.hour(),
                    time.minute(),
                    time.second()
                ),
                (1980, 1, 1, 0, 0, 0)
            );
            if index == 0 {
                assert_eq!(file.compression(), CompressionMethod::Stored);
            }
        }
    }

    #[test]
    fn central_metadata_rejected_before_payload() {
        assert_metadata_refusals_precede_payload();
        let blob = small();
        let positions = central_positions(&blob);
        assert_eq!(positions.len(), 3);

        let mut duplicate = blob.clone();
        duplicate[positions[2] + 46] = b'a';
        assert_eq!(
            HwpxPackage::from_bytes(&duplicate, PackageLimits::default()).unwrap_err(),
            invalid("duplicate decoded ZIP entry")
        );
        assert!(matches!(
            preflight_zip_names_detailed(&duplicate, PackageLimits::default()),
            Err(ZipPreflightError::Name(
                ZipNameIssue::DuplicateEffectiveName { .. }
            ))
        ));

        let mut encrypted = blob.clone();
        encrypted[positions[1] + 8] |= 1;
        assert_eq!(
            HwpxPackage::from_bytes(&encrypted, PackageLimits::default()).unwrap_err(),
            invalid("encrypted ZIP entry")
        );
        assert!(matches!(
            preflight_zip_names_detailed(&encrypted, PackageLimits::default()),
            Err(ZipPreflightError::Name(
                ZipNameIssue::UnsupportedFlags { .. }
            ))
        ));

        let mut unsupported = blob.clone();
        unsupported[positions[1] + 10..positions[1] + 12].copy_from_slice(&12u16.to_le_bytes());
        assert!(matches!(
            preflight_zip_names_detailed(&unsupported, PackageLimits::default()),
            Err(ZipPreflightError::Name(
                ZipNameIssue::UnsupportedCompression { .. }
            ))
        ));

        let mut oversized = blob.clone();
        oversized[positions[1] + 24..positions[1] + 28]
            .copy_from_slice(&(300 * MIB as u32).to_le_bytes());
        assert!(matches!(
            HwpxPackage::from_bytes(&oversized, PackageLimits::default()),
            Err(PackageError::Budget {
                dimension: "entry_bytes",
                ..
            })
        ));

        let mut invalid_utf8 = blob.clone();
        invalid_utf8[positions[1] + 9] |= 0x08;
        invalid_utf8[positions[1] + 46] = 0xff;
        assert_eq!(
            HwpxPackage::from_bytes(&invalid_utf8, PackageLimits::default()).unwrap_err(),
            invalid("invalid UTF-8 ZIP name")
        );
    }

    #[test]
    fn zip_names_and_mimetype_contract() {
        assert_serialization_admission();
        let safe = raw_zip(&[
            (MIMETYPE_NAME, MIMETYPE_VALUE),
            ("Contents/section0.xml", b"<s/>"),
        ]);
        assert!(HwpxPackage::from_bytes(&safe, PackageLimits::default()).is_ok());
        for name in [
            "",
            "/absolute.xml",
            "C:/absolute.xml",
            "C:drive.xml",
            "../escape.xml",
            "Contents/../../escape.xml",
            r"Contents\..\escape.xml",
        ] {
            let blob = raw_zip(&[(MIMETYPE_NAME, MIMETYPE_VALUE), (name, b"payload")]);
            assert!(
                matches!(
                    HwpxPackage::from_bytes(&blob, PackageLimits::default()),
                    Err(PackageError::Invalid(_))
                ),
                "{name:?}"
            );
            assert!(matches!(
                preflight_zip_names_detailed(&blob, PackageLimits::default()),
                Err(ZipPreflightError::Name(ZipNameIssue::UnsafeName { .. }))
            ));
        }
        for blob in [
            raw_zip(&[("a.xml", b"x")]),
            raw_zip(&[(MIMETYPE_NAME, b"application/zip"), ("a.xml", b"x")]),
            raw_zip(&[("a.xml", b"x"), (MIMETYPE_NAME, MIMETYPE_VALUE)]),
        ] {
            assert!(matches!(
                HwpxPackage::from_bytes(&blob, PackageLimits::default()),
                Err(PackageError::Invalid(_))
            ));
        }
    }

    #[test]
    fn corrupted_payload_is_not_returned() {
        let mut blob = small();
        let content = blob.windows(5).position(|s| s == b"hello").unwrap();
        blob[content] ^= 1;
        assert!(HwpxPackage::from_bytes(&blob, PackageLimits::default()).is_err());
    }

    #[test]
    fn false_declared_sizes_fail_closed() {
        let blob = small();
        for index in [1, 2] {
            let central = central_positions(&blob)[index];
            for size in [1u32, 1000] {
                let mut changed = blob.clone();
                changed[central + 24..central + 28].copy_from_slice(&size.to_le_bytes());
                let error =
                    HwpxPackage::from_bytes(&changed, PackageLimits::default()).unwrap_err();
                if size == 1000 {
                    let name = if index == 1 { "a.xml" } else { "b.xml" };
                    assert!(matches!(
                        error,
                        PackageError::Budget {
                            dimension: "declared_size",
                            observed: 5,
                            limit: 1000,
                            ..
                        }
                    ));
                    assert_eq!(
                        error.to_string(),
                        format!("HWPX 자원 한도 초과: 엔트리 '{name}' 실제 5 B != 선언 1000 B")
                    );
                }
            }
        }
    }

    #[test]
    fn local_name_must_match_central_name() {
        let mut blob = small();
        let local = blob.windows(5).position(|s| s == b"a.xml").unwrap();
        blob[local] = b'z';
        assert_eq!(
            HwpxPackage::from_bytes(&blob, PackageLimits::default()).unwrap_err(),
            invalid("ZIP local and central names differ")
        );

        let mut overlapped = small();
        let second = central_positions(&overlapped)[1];
        overlapped[second + 20..second + 24].copy_from_slice(&100u32.to_le_bytes());
        assert_eq!(
            HwpxPackage::from_bytes(&overlapped, PackageLimits::default()).unwrap_err(),
            invalid("overlapping ZIP entries")
        );

        let mut unicode = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: MIMETYPE_NAME.into(),
                    data: MIMETYPE_VALUE.into(),
                    stored: true,
                },
                PackageEntry {
                    name: "é.xml".into(),
                    data: b"x".into(),
                    stored: true,
                },
            ],
        }
        .to_bytes()
        .unwrap();
        let mut zip = ZipArchive::new(Cursor::new(&unicode)).unwrap();
        let header = zip.by_index_raw(1).unwrap().header_start() as usize;
        drop(zip);
        let flags = u16::from_le_bytes(unicode[header + 6..header + 8].try_into().unwrap());
        assert_ne!(flags & 0x0800, 0);
        unicode[header + 6..header + 8].copy_from_slice(&(flags & !0x0800).to_le_bytes());
        assert_eq!(
            HwpxPackage::from_bytes(&unicode, PackageLimits::default()).unwrap_err(),
            invalid("ZIP local and central names differ")
        );
    }

    #[test]
    fn deflated_mimetype_is_normalized_to_stored() {
        let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
        writer
            .start_file(
                MIMETYPE_NAME,
                SimpleFileOptions::default().compression_method(CompressionMethod::Deflated),
            )
            .unwrap();
        writer.write_all(MIMETYPE_VALUE).unwrap();
        let blob = writer.finish().unwrap().into_inner();
        let package = HwpxPackage::from_bytes(&blob, PackageLimits::default()).unwrap();
        let normalized = package.to_bytes().unwrap();
        assert_eq!(
            ZipArchive::new(Cursor::new(normalized))
                .unwrap()
                .by_index(0)
                .unwrap()
                .compression(),
            CompressionMethod::Stored
        );
    }

    #[test]
    fn prefixed_and_zip64_directories_keep_local_offsets() {
        let mut prefixed = b"PRELUDE".to_vec();
        prefixed.extend(small());
        assert_eq!(
            HwpxPackage::from_bytes(&prefixed, PackageLimits::default())
                .unwrap()
                .entries
                .len(),
            3
        );

        let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
        writer.set_raw_zip64_extensible_data_sector(Vec::new().into_boxed_slice());
        writer
            .start_file(
                MIMETYPE_NAME,
                SimpleFileOptions::default()
                    .compression_method(CompressionMethod::Stored)
                    .large_file(true),
            )
            .unwrap();
        writer.write_all(MIMETYPE_VALUE).unwrap();
        let zip64 = writer.finish().unwrap().into_inner();
        assert!(zip64.windows(4).any(|bytes| bytes == b"PK\x06\x06"));
        assert!(zip64.windows(4).any(|bytes| bytes == b"PK\x06\x07"));
        assert_eq!(
            HwpxPackage::from_bytes(&zip64, PackageLimits::default())
                .unwrap()
                .entries[0]
                .data,
            MIMETYPE_VALUE
        );
        let mut prefixed_zip64 = b"PRELUDE".to_vec();
        prefixed_zip64.extend(zip64);
        assert_eq!(
            HwpxPackage::from_bytes(&prefixed_zip64, PackageLimits::default())
                .unwrap()
                .entries[0]
                .data,
            MIMETYPE_VALUE
        );
        let mut tampered = prefixed_zip64.clone();
        let locator = tampered
            .windows(4)
            .rposition(|bytes| bytes == b"PK\x06\x07")
            .unwrap();
        let stored = le64(&tampered, locator + 8).unwrap();
        tampered[locator + 8..locator + 16].copy_from_slice(&((stored + 1) as u64).to_le_bytes());
        assert!(HwpxPackage::from_bytes(&tampered, PackageLimits::default()).is_err());
    }

    #[test]
    fn unicode_path_extra_preserves_effective_names_and_payloads() {
        let mut blob = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: MIMETYPE_NAME.into(),
                    data: MIMETYPE_VALUE.into(),
                    stored: true,
                },
                PackageEntry {
                    name: "a.xml".into(),
                    data: b"a.xml".into(),
                    stored: true,
                },
                PackageEntry {
                    name: "b.xml".into(),
                    data: b"b.xml".into(),
                    stored: false,
                },
            ],
        }
        .to_bytes()
        .unwrap();
        let extra_at = add_unicode_path(&mut blob, 2, b"a.xml");
        let central = central_positions(&blob)[2];
        assert_eq!(
            HwpxPackage::from_bytes(&blob, PackageLimits::default()).unwrap_err(),
            invalid("duplicate decoded ZIP entry")
        );
        assert_eq!(
            preflight_zip_names(&blob, PackageLimits::default()).unwrap_err(),
            invalid("duplicate decoded ZIP entry")
        );

        let alias_at = extra_at + 9;
        let mut distinct = blob.clone();
        distinct[alias_at..alias_at + 5].copy_from_slice(b"c.xml");
        let package = HwpxPackage::from_bytes(&distinct, PackageLimits::default()).unwrap();
        let names = preflight_zip_names(&distinct, PackageLimits::default()).unwrap();
        assert_eq!(names[2].raw_name, "b.xml");
        assert_eq!(names[2].effective_name, "c.xml");
        let work_zip = raw_zip(&[("manifest.json", b"{}")]);
        assert_eq!(
            preflight_zip_names(&work_zip, PackageLimits::default()).unwrap()[0].raw_name,
            "manifest.json"
        );
        assert!(HwpxPackage::from_bytes(&work_zip, PackageLimits::default()).is_err());
        assert_eq!(
            package
                .entries
                .iter()
                .map(|entry| entry.name.as_str())
                .collect::<Vec<_>>(),
            ["mimetype", "a.xml", "c.xml"]
        );
        assert_eq!(package.entries[1].data, b"a.xml");
        assert_eq!(package.entries[2].data, b"b.xml");
        assert!(package.entries[1].stored);
        assert!(!package.entries[2].stored);
        assert_eq!(
            HwpxPackage::from_bytes(&package.to_bytes().unwrap(), PackageLimits::default())
                .unwrap(),
            package
        );

        let mut repeated_alias = distinct.clone();
        add_unicode_path(&mut repeated_alias, 2, b"d.xml");
        let latest = HwpxPackage::from_bytes(&repeated_alias, PackageLimits::default()).unwrap();
        assert_eq!(latest.entries[2].name, "d.xml");
        assert_eq!(latest.entries[2].data, b"b.xml");

        let mut repeated_raw = distinct.clone();
        let mut zip = ZipArchive::new(Cursor::new(&distinct)).unwrap();
        let local = zip.by_index_raw(2).unwrap().header_start() as usize;
        drop(zip);
        repeated_raw[central + 46] = b'a';
        repeated_raw[local + 30] = b'a';
        repeated_raw[extra_at + 5..extra_at + 9]
            .copy_from_slice(&crc32fast::hash(b"a.xml").to_le_bytes());
        let repeated = HwpxPackage::from_bytes(&repeated_raw, PackageLimits::default()).unwrap();
        assert_eq!(
            repeated
                .entries
                .iter()
                .map(|entry| entry.name.as_str())
                .collect::<Vec<_>>(),
            ["mimetype", "a.xml", "c.xml"]
        );
        assert_eq!(repeated.entries[2].data, b"b.xml");

        for change in [extra_at + 4, extra_at + 5] {
            let mut ignored = distinct.clone();
            ignored[change] ^= 1;
            let parsed = HwpxPackage::from_bytes(&ignored, PackageLimits::default()).unwrap();
            assert_eq!(parsed.entries[2].name, "b.xml");
            assert_eq!(parsed.entries[2].data, b"b.xml");
        }
        let mut malformed = distinct.clone();
        malformed[extra_at + 2] = 4;
        assert_eq!(
            HwpxPackage::from_bytes(&malformed, PackageLimits::default()).unwrap_err(),
            invalid("corrupt UnicodePath extra field")
        );
    }

    #[test]
    fn unicode_path_index_handles_short_raw_name_collisions() {
        let mut empty = raw_zip(&[(MIMETYPE_NAME, MIMETYPE_VALUE), ("", b"first")]);
        add_unicode_path(&mut empty, 1, b"first.xml");
        let parsed = HwpxPackage::from_bytes(&empty, PackageLimits::default()).unwrap();
        assert_eq!(
            parsed
                .entries
                .iter()
                .map(|entry| entry.name.as_str())
                .collect::<Vec<_>>(),
            ["mimetype", "first.xml"]
        );
        assert_eq!(parsed.entries[1].data, b"first");

        let mut short = raw_zip(&[
            (MIMETYPE_NAME, MIMETYPE_VALUE),
            ("a", b"first"),
            ("b", b"second"),
        ]);
        add_unicode_path(&mut short, 1, b"first.xml");
        let second_extra = add_unicode_path(&mut short, 2, b"second.xml");
        let central = central_positions(&short)[2];
        let mut zip = ZipArchive::new(Cursor::new(&short)).unwrap();
        let local = zip.by_index_raw(2).unwrap().header_start() as usize;
        drop(zip);
        short[central + 46] = b'a';
        short[local + 30] = b'a';
        short[second_extra + 5..second_extra + 9]
            .copy_from_slice(&crc32fast::hash(b"a").to_le_bytes());
        let parsed = HwpxPackage::from_bytes(&short, PackageLimits::default()).unwrap();
        assert_eq!(
            parsed
                .entries
                .iter()
                .map(|entry| entry.name.as_str())
                .collect::<Vec<_>>(),
            ["mimetype", "first.xml", "second.xml"]
        );
        assert_eq!(parsed.entries[1].data, b"first");
        assert_eq!(parsed.entries[2].data, b"second");

        let mut cp437 = raw_zip(&[
            (MIMETYPE_NAME, MIMETYPE_VALUE),
            ("a1", b"one"),
            ("b1", b"two"),
        ]);
        let central = central_positions(&cp437)[1];
        let mut zip = ZipArchive::new(Cursor::new(&cp437)).unwrap();
        let local = zip.by_index_raw(1).unwrap().header_start() as usize;
        drop(zip);
        cp437[central + 46..central + 48].copy_from_slice(&[0xc3, 0xa9]);
        cp437[local + 30..local + 32].copy_from_slice(&[0xc3, 0xa9]);
        add_unicode_path(&mut cp437, 2, "é".as_bytes());
        let parsed = HwpxPackage::from_bytes(&cp437, PackageLimits::default()).unwrap();
        assert_eq!(parsed.entries[1].name, "├⌐");
        assert_eq!(parsed.entries[2].name, "é");
        assert_eq!(parsed.entries[1].data, b"one");
        assert_eq!(parsed.entries[2].data, b"two");
    }

    #[test]
    fn resource_limits_accept_boundary_and_refuse_one_over() {
        assert_budget_details_and_ratio_floor();
        fn set_limit(limits: &mut PackageLimits, dimension: &str, value: u64) {
            match dimension {
                "archive_bytes" => limits.max_archive_bytes = value,
                "directory_signatures" => limits.max_directory_signatures = value as usize,
                "entries" => limits.max_entries = value as usize,
                "entry_bytes" => limits.max_entry_bytes = value,
                "total_bytes" => limits.max_total_bytes = value,
                _ => unreachable!(),
            }
        }
        let blob = small();
        let mut limits = PackageLimits::default();
        let total = MIMETYPE_VALUE.len() as u64 + 10;
        for (dimension, at_limit, over_limit) in [
            ("archive_bytes", blob.len() as u64, blob.len() as u64 - 1),
            ("directory_signatures", 3, 2),
            ("entries", 3, 2),
            (
                "entry_bytes",
                MIMETYPE_VALUE.len() as u64,
                MIMETYPE_VALUE.len() as u64 - 1,
            ),
            ("total_bytes", total, total - 1),
        ] {
            set_limit(&mut limits, dimension, at_limit);
            assert!(
                HwpxPackage::from_bytes(&blob, limits).is_ok(),
                "{dimension}"
            );
            set_limit(&mut limits, dimension, over_limit);
            assert!(
                matches!(HwpxPackage::from_bytes(&blob, limits), Err(PackageError::Budget { dimension: found, .. }) if found == dimension)
            );
            limits = PackageLimits::default();
        }

        let compressed = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: MIMETYPE_NAME.into(),
                    data: MIMETYPE_VALUE.into(),
                    stored: true,
                },
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: vec![b'x'; 1000],
                    stored: false,
                },
            ],
        }
        .to_bytes()
        .unwrap();
        let mut zip = ZipArchive::new(Cursor::new(&compressed)).unwrap();
        let file = zip.by_index_raw(1).unwrap();
        let ratio_limit = file.size().div_ceil(file.compressed_size());
        let limits = PackageLimits {
            ratio_min_entry_bytes: 0,
            max_compression_ratio: ratio_limit,
            ..PackageLimits::default()
        };
        assert!(HwpxPackage::from_bytes(&compressed, limits).is_ok());
        assert!(matches!(
            HwpxPackage::from_bytes(
                &compressed,
                PackageLimits {
                    max_compression_ratio: ratio_limit - 1,
                    ..limits
                }
            ),
            Err(PackageError::Budget {
                dimension: "compression_ratio",
                ..
            })
        ));
    }

    #[test]
    fn bundled_documents_parse() {
        fn visit(root: &std::path::Path, count: &mut usize) {
            for item in std::fs::read_dir(root).unwrap() {
                let path = item.unwrap().path();
                if path.is_dir() {
                    visit(&path, count);
                } else if matches!(
                    path.extension().and_then(|s| s.to_str()),
                    Some("hwpx" | "hwpt")
                ) {
                    let blob = std::fs::read(&path).unwrap();
                    assert_document_budget_margin(&path, &blob);
                    HwpxPackage::from_bytes(&blob, PackageLimits::default())
                        .unwrap_or_else(|e| panic!("{}: {e}", path.display()));
                    *count += 1;
                }
            }
        }
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let mut count = 0;
        for dir in ["tests/corpus", "tests/fixtures", "examples"] {
            visit(&root.join(dir), &mut count);
        }
        assert!(count > 0);
    }

    fn corrupt_first_payload(blob: &mut [u8]) {
        let at = blob
            .windows(MIMETYPE_VALUE.len())
            .position(|part| part == MIMETYPE_VALUE)
            .unwrap();
        blob[at] ^= 1;
    }

    fn assert_metadata_refusals_precede_payload() {
        let mut blob = small();
        corrupt_first_payload(&mut blob);
        let positions = central_positions(&blob);
        for (flag, message) in [
            (1, "encrypted ZIP entry"),
            (0x40, "encrypted ZIP entry"),
            (0x20, "unsupported ZIP flags"),
        ] {
            let mut changed = blob.clone();
            changed[positions[1] + 8] |= flag;
            assert_eq!(
                HwpxPackage::from_bytes(&changed, PackageLimits::default()).unwrap_err(),
                invalid(message)
            );
        }
        for index in [0, 1] {
            for method in [12u16, 14] {
                let mut changed = blob.clone();
                changed[positions[index] + 10..positions[index] + 12]
                    .copy_from_slice(&method.to_le_bytes());
                assert_eq!(
                    HwpxPackage::from_bytes(&changed, PackageLimits::default()).unwrap_err(),
                    invalid("unsupported ZIP compression")
                );
            }
            let mut changed = blob.clone();
            changed[positions[index] + 24..positions[index] + 28]
                .copy_from_slice(&(300 * MIB as u32).to_le_bytes());
            let error = HwpxPackage::from_bytes(&changed, PackageLimits::default()).unwrap_err();
            let name = if index == 0 { "mimetype" } else { "a.xml" };
            assert!(
                matches!(error, PackageError::Budget { dimension: "entry_bytes", observed, limit, .. } if observed == 300 * MIB && limit == 256 * MIB)
            );
            assert_eq!(
                error.to_string(),
                format!("HWPX 자원 한도 초과: 엔트리 '{name}' 300.0 MiB > 256.0 MiB")
            );
        }
    }

    fn assert_serialization_admission() {
        let package = HwpxPackage::from_bytes(&small(), PackageLimits::default()).unwrap();
        for invalid_entry in [
            PackageEntry {
                name: MIMETYPE_NAME.into(),
                data: MIMETYPE_VALUE.into(),
                stored: true,
            },
            PackageEntry {
                name: "../escape.xml".into(),
                data: b"x".into(),
                stored: false,
            },
        ] {
            let mut changed = package.clone();
            changed.entries.push(invalid_entry);
            let before = changed.clone();
            assert!(changed.to_bytes().is_err());
            assert_eq!(changed, before);
        }
        let mut changed = package.clone();
        changed.entries.remove(0);
        assert_eq!(changed.to_bytes().unwrap_err(), invalid("missing mimetype"));
        let mut changed = package;
        changed.entries[0].data = b"application/zip".to_vec();
        assert_eq!(
            changed.to_bytes().unwrap_err(),
            invalid("wrong mimetype value")
        );
    }

    fn assert_budget_details_and_ratio_floor() {
        let mut blob = small();
        corrupt_first_payload(&mut blob);
        let cases = [
            (
                PackageLimits {
                    max_archive_bytes: blob.len() as u64 - 1,
                    ..Default::default()
                },
                "archive_bytes",
                format!("파일 크기 {} B > {} B", blob.len(), blob.len() - 1),
            ),
            (
                PackageLimits {
                    max_directory_signatures: 2,
                    ..Default::default()
                },
                "directory_signatures",
                "ZIP 디렉터리 서명 수 3 > 2".into(),
            ),
            (
                PackageLimits {
                    max_entries: 2,
                    ..Default::default()
                },
                "entries",
                "ZIP 엔트리 수 3 > 2".into(),
            ),
            (
                PackageLimits {
                    max_total_bytes: 28,
                    ..Default::default()
                },
                "total_bytes",
                "비압축 합계 29 B > 28 B".into(),
            ),
            (
                PackageLimits {
                    max_entry_bytes: 18,
                    ..Default::default()
                },
                "entry_bytes",
                "엔트리 'mimetype' 19 B > 18 B".into(),
            ),
        ];
        for (limits, expected, detail) in cases {
            let error = HwpxPackage::from_bytes(&blob, limits).unwrap_err();
            assert!(
                matches!(&error, PackageError::Budget { dimension, observed, limit, .. } if *dimension == expected && observed > limit)
            );
            assert_eq!(error.to_string(), format!("HWPX 자원 한도 초과: {detail}"));
        }
        let mut package = HwpxPackage::from_bytes(&small(), PackageLimits::default()).unwrap();
        package.entries[2].data = vec![b'x'; 1000];
        let compressed = package.to_bytes().unwrap();
        let floor = PackageLimits {
            max_compression_ratio: 1,
            ratio_min_entry_bytes: 1000,
            ..Default::default()
        };
        assert!(HwpxPackage::from_bytes(&compressed, floor).is_ok());
        let error = HwpxPackage::from_bytes(
            &compressed,
            PackageLimits {
                ratio_min_entry_bytes: 999,
                ..floor
            },
        )
        .unwrap_err();
        assert!(matches!(
            error,
            PackageError::Budget {
                dimension: "compression_ratio",
                limit: 1,
                ..
            }
        ));
        assert!(
            error
                .to_string()
                .starts_with("HWPX 자원 한도 초과: 엔트리 'b.xml' 압축률 ")
        );
        assert!(error.to_string().ends_with(":1 > 1:1"));
        let mut bomb = compressed;
        let central = central_positions(&bomb)[2];
        bomb[central + 24..central + 28].copy_from_slice(&(8 * MIB as u32).to_le_bytes());
        corrupt_first_payload(&mut bomb);
        assert!(matches!(
            HwpxPackage::from_bytes(&bomb, PackageLimits::default()),
            Err(PackageError::Budget {
                dimension: "compression_ratio",
                limit: 500,
                ..
            })
        ));
    }

    fn assert_document_budget_margin(path: &std::path::Path, blob: &[u8]) {
        let limits = PackageLimits::default();
        let mut zip = ZipArchive::new(Cursor::new(blob)).unwrap();
        assert!(zip.len() * 100 <= limits.max_entries, "{}", path.display());
        let mut total = 0;
        for index in 0..zip.len() {
            let info = zip.by_index_raw(index).unwrap();
            total += info.size();
            assert!(
                u128::from(info.size()) * 5
                    <= u128::from(info.compressed_size().max(1))
                        * u128::from(limits.max_compression_ratio),
                "{}:{}",
                path.display(),
                info.name()
            );
        }
        assert!(total * 100 <= limits.max_total_bytes, "{}", path.display());
    }
}
