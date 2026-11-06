//! Bounded, fail-closed `.narumi` ZIP bytes and atomic file effects.

use crate::atomic_file::write_bytes_atomic;
use hwpx_core::package::{
    PackageError, PackageLimits, ZipNameIssue, ZipPreflightError, ZipPreflightName,
    preflight_zip_names_detailed,
};
use hwpx_filler::work_package::{
    WorkPackageError, WorkPackageManifest, decode_work_package, encode_work_package,
};
use serde::de::{self, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::fs;
use std::io::{Cursor, Read, Write};
use std::path::Path;
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, DateTime, ZipArchive, ZipWriter};

const MIB: u64 = 1024 * 1024;
pub const MAX_TEMPLATES: usize = 256;
const MAX_ENTRIES: usize = MAX_TEMPLATES + 1;
const MAX_MANIFEST_BYTES: u64 = 16 * MIB;
const MAX_TEMPLATE_BYTES: u64 = 256 * MIB;
const MAX_TOTAL_BYTES: u64 = 1024 * MIB;
const MAX_ARCHIVE_BYTES: u64 = 1024 * MIB;
const MAX_COMPRESSION_RATIO: u64 = 200;
const RATIO_MIN_ENTRY_BYTES: u64 = MIB;
const MAX_DIRECTORY_SIGNATURES: usize = 65_536;
const FORBIDDEN_FLAGS: u16 = 0x1 | 0x20 | 0x40;

fn fail(message: impl Into<String>) -> WorkPackageError {
    WorkPackageError(message.into())
}
fn quoted(name: &str) -> String {
    hwpx_filler::text_render::python_repr(&Value::String(name.into()))
}
fn check_raw_name(name: &str) -> Result<(), WorkPackageError> {
    if name.is_empty() {
        return Err(fail("꾸러미에 이름 없는 항목이 있습니다"));
    }
    if name.contains('\0') {
        return Err(fail(format!(
            "꾸러미 항목 이름에 NUL 문자가 있습니다: {}",
            quoted(name)
        )));
    }
    if name.contains('\\') {
        return Err(fail(format!(
            "꾸러미 항목 경로에 역슬래시가 있습니다: {}",
            quoted(name)
        )));
    }
    if name.starts_with('/')
        || (name.chars().next().is_some_and(char::is_alphabetic)
            && name.chars().nth(1) == Some(':'))
    {
        return Err(fail(format!(
            "꾸러미 항목 경로가 절대 경로입니다: {}",
            quoted(name)
        )));
    }
    if name.split('/').any(|part| part == "..") {
        return Err(fail(format!(
            "꾸러미 항목 경로가 상위 폴더를 가리킵니다: {}",
            quoted(name)
        )));
    }
    Ok(())
}
fn preflight_error(error: ZipPreflightError) -> WorkPackageError {
    match error {
        ZipPreflightError::Name(ZipNameIssue::UnsafeName {
            raw_name,
            effective_name,
        }) => check_raw_name(&raw_name).err().unwrap_or_else(|| {
            fail(format!(
                "꾸러미에 허용되지 않은 항목이 있습니다: {}",
                quoted(&effective_name)
            ))
        }),
        ZipPreflightError::Name(ZipNameIssue::DuplicateEffectiveName { effective_name }) => fail(
            format!("꾸러미 항목 이름이 겹칩니다: {}", quoted(&effective_name)),
        ),
        ZipPreflightError::Name(ZipNameIssue::UnsupportedCompression { raw_name }) => {
            fail(format!(
                "꾸러미 항목의 압축 방식을 지원하지 않습니다: {}",
                quoted(&raw_name)
            ))
        }
        ZipPreflightError::Name(ZipNameIssue::UnsupportedFlags { raw_name }) => fail(format!(
            "꾸러미 항목이 암호화됐거나 지원하지 않는 ZIP 기능을 씁니다: {}",
            quoted(&raw_name)
        )),
        ZipPreflightError::Package(PackageError::Budget {
            dimension: "directory_signatures",
            ..
        }) => fail("꾸러미의 ZIP 디렉터리 서명이 너무 많습니다"),
        ZipPreflightError::Package(PackageError::Budget {
            dimension: "entries",
            observed,
            ..
        }) => fail(format!("꾸러미 항목이 너무 많습니다({observed}개)")),
        error => fail(format!("꾸러미 압축을 풀 수 없습니다: {error}")),
    }
}
fn template_name(digest: &str, media: &str) -> String {
    format!("templates/{digest}.{media}")
}
fn template_entry(name: &str) -> Option<(&str, &str)> {
    let suffix = name.strip_prefix("templates/")?;
    let (digest, media) = suffix.rsplit_once('.')?;
    if digest.len() == 64
        && digest
            .bytes()
            .all(|ch| ch.is_ascii_hexdigit() && !ch.is_ascii_uppercase())
        && ["hwpx", "txt"].contains(&media)
    {
        Some((digest, media))
    } else {
        None
    }
}
fn digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

#[derive(Debug)]
pub struct WorkPackageContents {
    pub manifest: WorkPackageManifest,
    pub templates: HashMap<String, Vec<u8>>,
}

/// JSON object visitor that rejects duplicate keys at every nesting level.
struct StrictJson(Value);
impl<'de> Deserialize<'de> for StrictJson {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct StrictVisitor;
        impl<'de> Visitor<'de> for StrictVisitor {
            type Value = StrictJson;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("JSON value")
            }
            fn visit_bool<E: de::Error>(self, value: bool) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::Bool(value)))
            }
            fn visit_i64<E: de::Error>(self, value: i64) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::from(value)))
            }
            fn visit_u64<E: de::Error>(self, value: u64) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::from(value)))
            }
            fn visit_f64<E: de::Error>(self, value: f64) -> Result<Self::Value, E> {
                serde_json::Number::from_f64(value)
                    .map(Value::Number)
                    .map(StrictJson)
                    .ok_or_else(|| E::custom("manifest 에 JSON 이 아닌 값이 있습니다"))
            }
            fn visit_str<E: de::Error>(self, value: &str) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::String(value.into())))
            }
            fn visit_string<E: de::Error>(self, value: String) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::String(value)))
            }
            fn visit_none<E: de::Error>(self) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::Null))
            }
            fn visit_unit<E: de::Error>(self) -> Result<Self::Value, E> {
                Ok(StrictJson(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(
                self,
                mut sequence: A,
            ) -> Result<Self::Value, A::Error> {
                let mut values = Vec::new();
                while let Some(StrictJson(value)) = sequence.next_element()? {
                    values.push(value);
                }
                Ok(StrictJson(Value::Array(values)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut access: A) -> Result<Self::Value, A::Error> {
                let mut values = Map::new();
                while let Some((key, StrictJson(value))) =
                    access.next_entry::<String, StrictJson>()?
                {
                    if values.insert(key, value).is_some() {
                        return Err(de::Error::custom("manifest 에 같은 키가 두 번 있습니다"));
                    }
                }
                Ok(StrictJson(Value::Object(values)))
            }
        }
        deserializer.deserialize_any(StrictVisitor)
    }
}
fn parse_manifest(bytes: &[u8]) -> Result<WorkPackageManifest, WorkPackageError> {
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    let StrictJson(value) = StrictJson::deserialize(&mut deserializer).map_err(|error| {
        if error
            .to_string()
            .contains("manifest 에 같은 키가 두 번 있습니다")
        {
            fail("manifest 에 같은 키가 두 번 있습니다")
        } else if let Some(token) = non_json_constant(bytes, &error) {
            fail(format!("manifest 에 JSON 이 아닌 값이 있습니다: {token}"))
        } else {
            fail(format!("manifest.json 을 읽을 수 없습니다: {error}"))
        }
    })?;
    deserializer
        .end()
        .map_err(|error| fail(format!("manifest.json 을 읽을 수 없습니다: {error}")))?;
    decode_work_package(&value)
}

fn non_json_constant(bytes: &[u8], error: &serde_json::Error) -> Option<&'static str> {
    if !error.is_syntax() || error.column() == 0 {
        return None;
    }
    let mut start = 0usize;
    for _ in 1..error.line() {
        start += bytes.get(start..)?.iter().position(|byte| *byte == b'\n')? + 1;
    }
    let at = start.checked_add(error.column() - 1)?;
    let remaining = bytes.get(at..)?;
    if remaining.starts_with(b"NaN") {
        Some("NaN")
    } else if remaining.starts_with(b"Infinity") {
        Some("Infinity")
    } else if remaining.starts_with(b"-Infinity")
        || at > 0 && bytes[at - 1..].starts_with(b"-Infinity")
    {
        Some("-Infinity")
    } else {
        None
    }
}

struct Admitted {
    name: String,
    index: usize,
    size: u64,
}
fn admit_entry_shape(
    name: &str,
    entry: &zip::read::ZipFileEntry<'_>,
) -> Result<(), WorkPackageError> {
    let unix_kind = (entry.external_attributes() >> 16) & 0o170000;
    if entry.is_dir() || unix_kind == 0o040000 {
        return Err(fail(format!(
            "꾸러미에 폴더 항목이 있습니다: {}",
            quoted(name)
        )));
    }
    if entry.is_symlink() || unix_kind == 0o120000 {
        return Err(fail(format!(
            "꾸러미에 링크 항목이 있습니다: {}",
            quoted(name)
        )));
    }
    if entry.flags().as_u16() & FORBIDDEN_FLAGS != 0 {
        return Err(fail(format!(
            "꾸러미 항목이 암호화됐거나 지원하지 않는 ZIP 기능을 씁니다: {}",
            quoted(name)
        )));
    }
    if !matches!(
        entry.compression(),
        CompressionMethod::Stored | CompressionMethod::Deflated
    ) {
        return Err(fail(format!(
            "꾸러미 항목의 압축 방식을 지원하지 않습니다: {}",
            quoted(name)
        )));
    }
    Ok(())
}
fn admit_entry_budget(
    name: &str,
    entry: &zip::read::ZipFileEntry<'_>,
) -> Result<(), WorkPackageError> {
    let limit = if name == "manifest.json" {
        MAX_MANIFEST_BYTES
    } else if template_entry(name).is_some() {
        MAX_TEMPLATE_BYTES
    } else {
        return Err(fail(format!(
            "꾸러미에 허용되지 않은 항목이 있습니다: {}",
            quoted(name)
        )));
    };
    if entry.size() > limit {
        return Err(fail(format!(
            "꾸러미 항목이 너무 큽니다: {} ({} B)",
            quoted(name),
            entry.size()
        )));
    }
    if entry.size() > RATIO_MIN_ENTRY_BYTES
        && u128::from(entry.size())
            > u128::from(MAX_COMPRESSION_RATIO) * u128::from(entry.compressed_size().max(1))
    {
        return Err(fail(format!(
            "꾸러미 항목의 압축률이 비정상입니다: {}",
            quoted(name)
        )));
    }
    Ok(())
}
fn admit_entries(
    archive: &ZipArchive<Cursor<&[u8]>>,
    preflight: &[ZipPreflightName],
) -> Result<Vec<Admitted>, WorkPackageError> {
    if archive.metadata().has_duplicate_names() {
        return Err(fail("꾸러미 항목 이름이 겹칩니다"));
    }
    if archive.len() != preflight.len() {
        return Err(fail("꾸러미 ZIP 디렉터리 항목 수가 다릅니다"));
    }
    if archive.len() > MAX_ENTRIES {
        return Err(fail(format!(
            "꾸러미 항목이 너무 많습니다({}개)",
            archive.len()
        )));
    }
    let mut admitted = Vec::new();
    let mut names = HashSet::new();
    let mut total = 0u64;
    for (index, observed) in preflight.iter().enumerate() {
        let entry = archive
            .by_index_data(index)
            .map_err(|error| fail(format!("꾸러미 압축을 풀 수 없습니다: {error}")))?;
        let raw_name = observed.raw_name.as_str();
        check_raw_name(raw_name)?;
        let decoded = entry.name().map_err(|error| fail(error.to_string()))?;
        if decoded.as_ref() != observed.effective_name {
            return Err(fail(format!(
                "꾸러미 항목 이름이 정규형이 아닙니다: {}",
                quoted(raw_name)
            )));
        }
        let name = observed.effective_name.as_str();
        if !names.insert(name.to_owned()) {
            return Err(fail(format!(
                "꾸러미 항목 이름이 겹칩니다: {}",
                quoted(name)
            )));
        }
        admit_entry_shape(name, &entry)?;
        admit_entry_budget(name, &entry)?;
        total = total
            .checked_add(entry.size())
            .ok_or_else(|| fail("꾸러미의 압축 해제 합계가 너무 큽니다"))?;
        admitted.push(Admitted {
            name: name.into(),
            index,
            size: entry.size(),
        });
    }
    if total > MAX_TOTAL_BYTES {
        return Err(fail("꾸러미의 압축 해제 합계가 너무 큽니다"));
    }
    if !names.contains("manifest.json") {
        return Err(fail("꾸러미에 manifest.json 이 없습니다"));
    }
    Ok(admitted)
}
fn read_entry(
    archive: &mut ZipArchive<Cursor<&[u8]>>,
    entry: &Admitted,
) -> Result<Vec<u8>, WorkPackageError> {
    let mut reader = archive
        .by_index(entry.index)
        .map_err(|error| fail(format!("꾸러미 압축을 풀 수 없습니다: {error}")))?;
    let mut bytes = Vec::new();
    reader
        .by_ref()
        .take(entry.size + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| fail(format!("꾸러미 압축을 풀 수 없습니다: {error}")))?;
    if bytes.len() as u64 != entry.size {
        return Err(fail(format!(
            "꾸러미 항목의 실제 크기가 선언과 다릅니다: {}",
            quoted(&entry.name)
        )));
    }
    Ok(bytes)
}
pub fn read_work_package_bytes(bytes: &[u8]) -> Result<WorkPackageContents, WorkPackageError> {
    if bytes.len() as u64 > MAX_ARCHIVE_BYTES {
        return Err(fail(format!(
            "꾸러미 파일이 너무 큽니다({} B)",
            bytes.len()
        )));
    }
    let preflight = preflight_zip_names_detailed(
        bytes,
        PackageLimits {
            max_archive_bytes: MAX_ARCHIVE_BYTES,
            max_directory_signatures: MAX_DIRECTORY_SIGNATURES,
            max_entries: MAX_ENTRIES,
            max_entry_bytes: MAX_TEMPLATE_BYTES,
            max_total_bytes: MAX_TOTAL_BYTES,
            max_compression_ratio: MAX_COMPRESSION_RATIO,
            ratio_min_entry_bytes: RATIO_MIN_ENTRY_BYTES,
        },
    )
    .map_err(preflight_error)?;
    let mut archive = ZipArchive::new(Cursor::new(bytes))
        .map_err(|error| fail(format!("꾸러미 압축을 풀 수 없습니다: {error}")))?;
    let admitted = admit_entries(&archive, &preflight)?;
    let manifest_entry = admitted
        .iter()
        .find(|entry| entry.name == "manifest.json")
        .expect("admitted manifest");
    let manifest = parse_manifest(&read_entry(&mut archive, manifest_entry)?)?;
    let declared = manifest.template_by_digest();
    let present = admitted
        .iter()
        .filter_map(|entry| {
            template_entry(&entry.name).map(|(digest, media)| (digest.to_owned(), (entry, media)))
        })
        .collect::<HashMap<_, _>>();
    if present.len() != admitted.len() - 1 {
        return Err(fail("같은 템플릿이 다른 형식으로 두 번 들어 있습니다"));
    }
    if present.keys().collect::<HashSet<_>>() != declared.keys().collect::<HashSet<_>>() {
        return Err(fail("꾸러미의 템플릿 파일이 manifest 선언과 다릅니다"));
    }
    let mut templates = HashMap::new();
    for (digest, (entry, media)) in present {
        let template = declared[&digest];
        if media != template.media {
            return Err(fail(format!(
                "템플릿 파일 형식이 manifest 선언과 다릅니다: {digest}"
            )));
        }
        if entry.size != template.size {
            return Err(fail(format!(
                "템플릿 크기가 manifest 선언과 다릅니다: {digest}"
            )));
        }
        let content = read_entry(&mut archive, entry)?;
        if self::digest(&content) != digest {
            return Err(fail(format!(
                "템플릿 내용이 digest 와 다릅니다(손상·변조): {digest}"
            )));
        }
        templates.insert(digest, content);
    }
    Ok(WorkPackageContents {
        manifest,
        templates,
    })
}
pub fn read_work_package(path: &Path) -> Result<WorkPackageContents, WorkPackageError> {
    let file = fs::File::open(path)
        .map_err(|error| fail(format!("꾸러미 파일을 열 수 없습니다: {error}")))?;
    let size = file
        .metadata()
        .map_err(|error| fail(format!("꾸러미 파일을 열 수 없습니다: {error}")))?
        .len();
    read_work_package_stream(file, size)
}
fn read_work_package_stream(
    reader: impl Read,
    size: u64,
) -> Result<WorkPackageContents, WorkPackageError> {
    if size > MAX_ARCHIVE_BYTES {
        return Err(fail("꾸러미 파일이 너무 큽니다"));
    }
    let mut bytes = Vec::new();
    reader
        .take(MAX_ARCHIVE_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| fail(format!("꾸러미 파일을 열 수 없습니다: {error}")))?;
    read_work_package_bytes(&bytes)
}
pub fn build_work_package_bytes(
    manifest: &WorkPackageManifest,
    templates: &HashMap<String, Vec<u8>>,
) -> Result<Vec<u8>, WorkPackageError> {
    manifest.validate()?;
    let declared = manifest.template_by_digest();
    if templates.keys().collect::<HashSet<_>>() != declared.keys().collect::<HashSet<_>>() {
        return Err(fail("템플릿 bytes 집합이 manifest 선언과 다릅니다"));
    }
    for (key, template) in &declared {
        let content = &templates[key];
        if digest(content) != *key || content.len() as u64 != template.size {
            return Err(fail(format!(
                "템플릿 bytes 가 선언 digest·크기와 다릅니다: {key}"
            )));
        }
    }
    let encoded = encode_work_package(manifest)?;
    let text = serde_json::to_vec_pretty(&encoded)
        .map_err(|error| fail(format!("manifest 를 JSON 으로 쓸 수 없습니다: {error}")))?;
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    let options = SimpleFileOptions::default()
        .compression_method(CompressionMethod::Deflated)
        .last_modified_time(DateTime::default());
    writer
        .start_file("manifest.json", options)
        .map_err(|error| fail(error.to_string()))?;
    writer
        .write_all(&text)
        .map_err(|error| fail(error.to_string()))?;
    let mut ordered = manifest.templates.iter().collect::<Vec<_>>();
    ordered.sort_by(|left, right| left.digest.cmp(&right.digest));
    for template in ordered {
        let method = if template.media == "hwpx" {
            CompressionMethod::Stored
        } else {
            CompressionMethod::Deflated
        };
        let options = SimpleFileOptions::default()
            .compression_method(method)
            .last_modified_time(DateTime::default());
        writer
            .start_file(template_name(&template.digest, &template.media), options)
            .map_err(|error| fail(error.to_string()))?;
        writer
            .write_all(&templates[&template.digest])
            .map_err(|error| fail(error.to_string()))?;
    }
    let bytes = writer
        .finish()
        .map_err(|error| fail(error.to_string()))?
        .into_inner();
    read_work_package_bytes(&bytes)?;
    Ok(bytes)
}
pub fn write_work_package(
    path: &Path,
    manifest: &WorkPackageManifest,
    templates: &HashMap<String, Vec<u8>>,
) -> Result<(), WorkPackageError> {
    let bytes = build_work_package_bytes(manifest, templates)?;
    write_bytes_atomic(path, &bytes).map_err(|error| fail(error.to_string()))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{build_work_package_bytes, digest, read_work_package_bytes};
    use hwpx_filler::mapping::MappingProfile;
    use hwpx_filler::work_package::{PackagedJob, PackagedTemplate, WorkPackageManifest};
    use serde_json::Map;
    use std::collections::HashMap;
    use std::io::{Cursor, Write};
    use zip::{CompressionMethod, ZipArchive, ZipWriter, write::SimpleFileOptions};

    fn package() -> (WorkPackageManifest, HashMap<String, Vec<u8>>) {
        let mut manifest = WorkPackageManifest {
            created_at: "2026-11-05T12:00:00".into(),
            templates: Vec::new(),
            jobs: Vec::new(),
        };
        let mut templates = HashMap::new();
        for (media, content) in [
            ("hwpx", b"PK\x03\x04 template".as_slice()),
            ("txt", "공고명: {{공고명}}\n".as_bytes()),
        ] {
            let digest = digest(content);
            manifest.templates.push(PackagedTemplate {
                digest: digest.clone(),
                media: media.into(),
                display_name: format!("공고서.{media}"),
                size: content.len() as u64,
            });
            manifest.jobs.push(PackagedJob {
                name: format!("공고서 {media}"),
                media: media.into(),
                template_digest: digest.clone(),
                mapping: MappingProfile::new("", Vec::new(), Map::new()).unwrap(),
                filename_pattern: "공고서-{{seq:001}}".into(),
                selection_presets: Vec::new(),
                data_contract: None,
            });
            templates.insert(digest, content.to_vec());
        }
        let mut shared = manifest.jobs[0].clone();
        shared.name = "공유 서식".into();
        manifest.jobs.push(shared);
        (manifest, templates)
    }

    fn entries() -> Vec<(String, Vec<u8>)> {
        let (manifest, templates) = package();
        let mut entries = vec![(
            "manifest.json".into(),
            serde_json::to_vec(&super::encode_work_package(&manifest).unwrap()).unwrap(),
        )];
        entries.extend(manifest.templates.iter().map(|template| {
            (
                super::template_name(&template.digest, &template.media),
                templates[&template.digest].clone(),
            )
        }));
        entries
    }

    fn raw_zip(entries: &[(String, Vec<u8>)]) -> Vec<u8> {
        let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
        for (name, content) in entries {
            writer
                .start_file(
                    name,
                    SimpleFileOptions::default().compression_method(CompressionMethod::Stored),
                )
                .unwrap();
            writer.write_all(content).unwrap();
        }
        writer.finish().unwrap().into_inner()
    }

    fn rejects(bytes: &[u8], expected: &str) {
        let error = read_work_package_bytes(bytes).unwrap_err();
        assert!(error.0.contains(expected), "expected {expected}: {error}");
    }

    fn central(bytes: &[u8], index: usize) -> usize {
        let eocd = bytes
            .windows(4)
            .rposition(|part| part == b"PK\x05\x06")
            .unwrap();
        let mut at = u32::from_le_bytes(bytes[eocd + 16..eocd + 20].try_into().unwrap()) as usize;
        for _ in 0..index {
            let lengths: usize = [28, 30, 32]
                .into_iter()
                .map(|offset| {
                    u16::from_le_bytes(bytes[at + offset..at + offset + 2].try_into().unwrap())
                        as usize
                })
                .sum();
            at += 46 + lengths;
        }
        at
    }

    #[test]
    fn deterministic_archive_preserves_shared_templates_and_rejects_mismatched_payloads() {
        let (manifest, templates) = package();
        let bytes = build_work_package_bytes(&manifest, &templates).unwrap();
        assert_eq!(
            build_work_package_bytes(&manifest, &templates).unwrap(),
            bytes
        );
        let read = read_work_package_bytes(&bytes).unwrap();
        assert_eq!(read.manifest, manifest);
        assert_eq!(read.templates, templates);
        let mut zip = ZipArchive::new(Cursor::new(&bytes)).unwrap();
        assert_eq!(zip.len(), 3);
        assert_eq!(zip.by_index(0).unwrap().name().unwrap(), "manifest.json");
        for template in &manifest.templates {
            let file = zip
                .by_name(&super::template_name(&template.digest, &template.media))
                .unwrap();
            assert_eq!(
                file.compression(),
                if template.media == "hwpx" {
                    CompressionMethod::Stored
                } else {
                    CompressionMethod::Deflated
                }
            );
        }
        let mut wrong = templates.clone();
        wrong.insert(manifest.templates[0].digest.clone(), b"other".to_vec());
        assert!(
            build_work_package_bytes(&manifest, &wrong)
                .unwrap_err()
                .0
                .contains("digest·크기")
        );
        wrong.remove(&manifest.templates[0].digest);
        assert!(
            build_work_package_bytes(&manifest, &wrong)
                .unwrap_err()
                .0
                .contains("bytes 집합")
        );
        assert_eq!(
            read_work_package_bytes(&raw_zip(&entries()))
                .unwrap()
                .manifest,
            manifest
        );
        assert_archive_manifest_mismatches();
    }

    fn assert_archive_manifest_mismatches() {
        let valid = entries();
        let mut changed = valid.clone();
        changed[1].1[0] ^= 1;
        rejects(&raw_zip(&changed), "digest 와 다릅니다");
        changed = valid.clone();
        let mut manifest: serde_json::Value = serde_json::from_slice(&changed[0].1).unwrap();
        manifest["templates"][0]["size"] = serde_json::json!(changed[1].1.len() + 1);
        changed[0].1 = serde_json::to_vec(&manifest).unwrap();
        rejects(&raw_zip(&changed), "크기가 manifest 선언과 다릅니다");
        changed = valid.clone();
        changed[2].0 = changed[2].0.replace(".txt", ".hwpx");
        rejects(&raw_zip(&changed), "형식이 manifest 선언과 다릅니다");
        changed.push(valid[2].clone());
        rejects(&raw_zip(&changed), "두 번");
        rejects(&raw_zip(&valid[..2]), "선언과 다릅니다");
        changed = valid.clone();
        changed.push((
            format!("templates/{}.txt", "c".repeat(64)),
            b"another".to_vec(),
        ));
        rejects(&raw_zip(&changed), "선언과 다릅니다");
        rejects(&raw_zip(&valid[1..]), "manifest.json 이 없습니다");
    }

    #[test]
    fn malformed_manifest_and_corrupt_zip_fail_without_partial_contents() {
        for (payload, expected) in [
            (b"\xff\xfe".as_slice(), "읽을 수 없습니다"),
            (b"{not json", "읽을 수 없습니다"),
            (br#"{"nested":{"x":1,"x":2}}"#, "같은 키"),
            (
                br#"{"schema_version":"work-package/v1","schema_version":"x"}"#,
                "같은 키",
            ),
            (br#"{"size": NaN}"#, "JSON 이 아닌 값"),
            (br#"{"size": Infinity}"#, "JSON 이 아닌 값"),
            (br#"{"size": -Infinity}"#, "JSON 이 아닌 값"),
            (
                br#"{"schema_version":"work-package/v9"}"#,
                "모르는 꾸러미 버전",
            ),
        ] {
            let mut changed = entries();
            changed[0].1 = payload.to_vec();
            rejects(&raw_zip(&changed), expected);
        }
        let mut trailing = entries();
        trailing[0].1.extend(b" true");
        rejects(&raw_zip(&trailing), "읽을 수 없습니다");
        rejects(b"not a zip", "압축을 풀 수 없습니다");
        let valid = entries();
        let mut corrupt = raw_zip(&valid);
        let at = corrupt
            .windows(valid[1].1.len())
            .position(|part| part == valid[1].1)
            .unwrap();
        corrupt[at] ^= 1;
        rejects(&corrupt, "압축을 풀 수 없습니다");
        let mut short = raw_zip(&valid);
        let at = central(&short, 0) + 24;
        short[at..at + 4].copy_from_slice(&((valid[0].1.len() + 1) as u32).to_le_bytes());
        rejects(&short, "실제 크기가 선언과 다릅니다");
    }

    #[test]
    fn hostile_names_modes_flags_and_compression_are_rejected_before_payloads() {
        for (name, expected) in [
            ("../x", "상위 폴더"),
            ("templates/../manifest.json", "상위 폴더"),
            ("/abs/manifest.json", "절대 경로"),
            ("C:/x.txt", "절대 경로"),
            ("templates\\x.txt", "역슬래시"),
            ("..\\x", "역슬래시"),
            ("manifest.json\0.txt", "NUL"),
            ("readme.txt", "허용되지 않은 항목"),
            ("templates/abc.txt", "허용되지 않은 항목"),
            ("templates/", "폴더"),
        ] {
            let mut changed = entries();
            // Replace a same-length innocuous name after writing, because ZIP writers normalize names.
            let placeholder = "x".repeat(name.len());
            changed.push((placeholder.clone(), b"x".to_vec()));
            let mut bytes = raw_zip(&changed);
            let positions: Vec<_> = bytes
                .windows(placeholder.len())
                .enumerate()
                .filter_map(|(at, part)| (part == placeholder.as_bytes()).then_some(at))
                .collect();
            for at in positions {
                bytes[at..at + name.len()].copy_from_slice(name.as_bytes());
            }
            rejects(&bytes, expected);
        }
        let valid = entries();
        for name in [
            valid[1].0.to_uppercase(),
            valid[1].0.replace(".hwpx", ".exe"),
            format!("nested/{}", valid[1].0),
        ] {
            let mut changed = valid.clone();
            changed.push((name, b"x".to_vec()));
            rejects(&raw_zip(&changed), "허용되지 않은 항목");
        }
        for (offset, value, expected) in [
            (8, 1u16, "암호화"),
            (8, 0x20, "암호화"),
            (8, 0x40, "암호화"),
            (10, 12, "압축 방식"),
        ] {
            let mut bytes = raw_zip(&valid);
            let at = central(&bytes, 0) + offset;
            bytes[at..at + 2].copy_from_slice(&value.to_le_bytes());
            rejects(&bytes, expected);
        }
        for (mode, expected) in [(0o120777u32, "링크"), (0o040777, "폴더")] {
            let mut bytes = raw_zip(&valid);
            let at = central(&bytes, 1);
            bytes[at + 5] = 3;
            bytes[at + 38..at + 42].copy_from_slice(&(mode << 16).to_le_bytes());
            rejects(&bytes, expected);
        }
    }

    #[test]
    fn archive_budgets_reject_declared_sizes_counts_and_signature_floods() {
        let valid = entries();
        for (index, size) in [
            (0, super::MAX_MANIFEST_BYTES + 1),
            (1, super::MAX_TEMPLATE_BYTES + 1),
        ] {
            let mut bytes = raw_zip(&valid);
            let at = central(&bytes, index) + 24;
            bytes[at..at + 4].copy_from_slice(&(size as u32).to_le_bytes());
            rejects(&bytes, "항목이 너무 큽니다");
        }
        let mut bomb = raw_zip(&valid);
        let at = central(&bomb, 1) + 24;
        bomb[at..at + 4]
            .copy_from_slice(&((super::RATIO_MIN_ENTRY_BYTES + 1) as u32).to_le_bytes());
        rejects(&bomb, "압축률");
        let mut total = valid.clone();
        for index in 0..3 {
            total.push((format!("templates/{index:064x}.txt"), b"x".to_vec()));
        }
        let mut bytes = raw_zip(&total);
        for index in 1..total.len() {
            let at = central(&bytes, index);
            bytes[at + 20..at + 24]
                .copy_from_slice(&((super::MAX_TEMPLATE_BYTES / 100) as u32).to_le_bytes());
            bytes[at + 24..at + 28]
                .copy_from_slice(&(super::MAX_TEMPLATE_BYTES as u32).to_le_bytes());
        }
        rejects(&bytes, "합계");
        let mut many = valid;
        for index in 0..super::MAX_ENTRIES {
            many.push((format!("templates/{index:064x}.txt"), b"x".to_vec()));
        }
        rejects(&raw_zip(&many), "항목이 너무 많습니다");
        rejects(
            &b"PK\x01\x02".repeat(super::MAX_DIRECTORY_SIGNATURES + 1),
            "서명",
        );
        rejects(
            &raw_zip(&[(String::new(), b"x".to_vec())]),
            "이름 없는 항목",
        );
    }

    #[test]
    fn file_roundtrip_and_refusals_preserve_existing_destination() {
        use std::fs;
        let workspace = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let root = workspace.join(format!(".cache/work-package-io-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        assert!(root.canonicalize().unwrap().starts_with(&workspace));
        let path = root.join("작업.narumi");
        assert!(
            super::read_work_package(&path)
                .unwrap_err()
                .0
                .contains("열 수 없습니다")
        );
        let (manifest, templates) = package();
        assert!(super::write_work_package(&path, &manifest, &HashMap::new()).is_err());
        assert!(!path.exists());
        super::write_work_package(&path, &manifest, &templates).unwrap();
        let contents = super::read_work_package(&path).unwrap();
        assert_eq!(contents.manifest, manifest);
        assert_eq!(contents.templates, templates);
        let original = fs::read(&path).unwrap();
        assert!(super::write_work_package(&path, &manifest, &HashMap::new()).is_err());
        assert_eq!(fs::read(&path).unwrap(), original);
        assert!(
            super::write_work_package(
                &root.join("missing/destination.narumi"),
                &manifest,
                &templates
            )
            .is_err()
        );
        assert!(
            super::read_work_package_stream(Cursor::new(&original), super::MAX_ARCHIVE_BYTES + 1)
                .unwrap_err()
                .0
                .contains("너무 큽니다")
        );
        assert_eq!(
            super::read_work_package_stream(Cursor::new(&original), super::MAX_ARCHIVE_BYTES)
                .unwrap()
                .manifest,
            manifest
        );
        struct FailedRead;
        impl std::io::Read for FailedRead {
            fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> {
                Err(std::io::Error::other("unreadable"))
            }
        }
        assert!(
            super::read_work_package_stream(FailedRead, 1)
                .unwrap_err()
                .0
                .contains("열 수 없습니다")
        );
        fs::remove_dir_all(&root).unwrap();
    }

    fn add_unicode_alias(bytes: &mut Vec<u8>, index: usize, alias: &str) {
        let eocd = bytes
            .windows(4)
            .rposition(|part| part == b"PK\x05\x06")
            .unwrap();
        let mut central =
            u32::from_le_bytes(bytes[eocd + 16..eocd + 20].try_into().unwrap()) as usize;
        for _ in 0..index {
            let name =
                u16::from_le_bytes(bytes[central + 28..central + 30].try_into().unwrap()) as usize;
            let extra =
                u16::from_le_bytes(bytes[central + 30..central + 32].try_into().unwrap()) as usize;
            let comment =
                u16::from_le_bytes(bytes[central + 32..central + 34].try_into().unwrap()) as usize;
            central += 46 + name + extra + comment;
        }
        let name =
            u16::from_le_bytes(bytes[central + 28..central + 30].try_into().unwrap()) as usize;
        let extra_len =
            u16::from_le_bytes(bytes[central + 30..central + 32].try_into().unwrap()) as usize;
        let raw = &bytes[central + 46..central + 46 + name];
        let mut crc = !0u32;
        for byte in raw {
            crc ^= u32::from(*byte);
            for _ in 0..8 {
                crc = (crc >> 1) ^ (0u32.wrapping_sub(crc & 1) & 0xedb8_8320);
            }
        }
        let mut field = vec![0x75, 0x70];
        field.extend(((alias.len() + 5) as u16).to_le_bytes());
        field.push(1);
        field.extend((!crc).to_le_bytes());
        field.extend(alias.as_bytes());
        bytes[central + 30..central + 32]
            .copy_from_slice(&((extra_len + field.len()) as u16).to_le_bytes());
        bytes.splice(
            central + 46 + name + extra_len..central + 46 + name + extra_len,
            field.iter().copied(),
        );
        let eocd = eocd + field.len();
        let size = u32::from_le_bytes(bytes[eocd + 12..eocd + 16].try_into().unwrap());
        bytes[eocd + 12..eocd + 16].copy_from_slice(&(size + field.len() as u32).to_le_bytes());
    }

    #[test]
    fn unicode_aliases_are_accepted_but_duplicate_effective_names_fail() {
        let (manifest, templates) = package();
        let archive = build_work_package_bytes(&manifest, &templates).unwrap();
        let duplicate = raw_zip(&entries()[..1]);
        // The writer refuses duplicates, so duplicate its central record as hostile input.
        let eocd = duplicate
            .windows(4)
            .rposition(|part| part == b"PK\x05\x06")
            .unwrap();
        let directory =
            u32::from_le_bytes(duplicate[eocd + 16..eocd + 20].try_into().unwrap()) as usize;
        let record = duplicate[directory..eocd].to_vec();
        let mut duplicate_entry = duplicate.clone();
        duplicate_entry.splice(eocd..eocd, record.iter().copied());
        let shifted_eocd = eocd + record.len();
        duplicate_entry[shifted_eocd + 8..shifted_eocd + 12].copy_from_slice(&[2, 0, 2, 0]);
        duplicate_entry[shifted_eocd + 12..shifted_eocd + 16]
            .copy_from_slice(&(2 * record.len() as u32).to_le_bytes());
        assert!(
            read_work_package_bytes(&duplicate_entry)
                .unwrap_err()
                .0
                .contains("항목 이름이 겹칩니다")
        );
        let mut aliased = archive.clone();
        let eocd = aliased
            .windows(4)
            .rposition(|part| part == b"PK\x05\x06")
            .unwrap();
        let central =
            u32::from_le_bytes(aliased[eocd + 16..eocd + 20].try_into().unwrap()) as usize;
        aliased[30..43].copy_from_slice(b"source00.json");
        aliased[central + 46..central + 59].copy_from_slice(b"source00.json");
        add_unicode_alias(&mut aliased, 0, "manifest.json");
        assert_eq!(
            read_work_package_bytes(&aliased).unwrap().manifest,
            manifest
        );
        let mut collided = archive.clone();
        add_unicode_alias(&mut collided, 1, "manifest.json");
        assert!(
            read_work_package_bytes(&collided)
                .unwrap_err()
                .0
                .contains("항목 이름이 겹칩니다")
        );
        let mut escaping = archive;
        add_unicode_alias(&mut escaping, 1, "../outside.txt");
        rejects(&escaping, "허용되지 않은 항목");
    }
}
