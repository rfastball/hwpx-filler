//! Argument admission for the default document-generation command.

use std::ffi::OsString;
use std::path::PathBuf;

use chrono::Local;
use hwpx_filler::data_excel::{ExcelDataSource, ambiguous_sheets};
use hwpx_filler::data_pclm::{PclmDataSource, list_sqlite_sheets};
use hwpx_filler::data_source::{DataSource, Record};
use hwpx_filler::home_state::StructureDrift;
use hwpx_filler::job::{DEFAULT_FILENAME_PATTERN, Job, MISSING_MARKER};
use hwpx_filler::mapping::{FieldMapping, MappingProfile};
use hwpx_filler::output_name::pattern_field_tokens;
use hwpx_filler::text_render::python_repr;
use hwpx_filler::validation::validate;
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::fs;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GenerateArgs {
    pub template: PathBuf,
    pub source: Source,
    pub data: Option<PathBuf>,
    pub out: PathBuf,
    pub pattern: String,
    pub sheet: Option<String>,
    pub profile: Option<PathBuf>,
    pub overwrite: bool,
    pub ack_empty: bool,
    pub ledger: bool,
    pub db: Option<PathBuf>,
    pub view: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Source {
    Excel,
    Pclm,
}

pub enum Parsed {
    Help,
    Fields(PathBuf),
    Generate(Box<GenerateArgs>),
}

pub struct LoadedRecords {
    pub records: Vec<Record>,
    pub source_keys: Vec<String>,
    pub source_pointer: String,
    pub notices: Vec<String>,
}

pub struct PreparedGeneration {
    pub mapping: MappingProfile,
    pub notices: Vec<String>,
}

pub struct SourceFailure {
    pub exit_code: u8,
    pub message: String,
    pub notices: Vec<String>,
    pub argparse: bool,
}

pub const GENERATION_ARGPARSE_USAGE: &str = "usage: hwpxfiller [-h] --template TEMPLATE [--source {excel,pclm}]\n                  [--data DATA] [--out OUT] [--pattern PATTERN]\n                  [--sheet SHEET] [--profile PROFILE] [--fields] [--overwrite]\n                  [--ack-empty] [--ledger] [--db DB] [--view VIEW]";

pub fn failure(exit_code: u8, message: impl Into<String>) -> SourceFailure {
    SourceFailure {
        exit_code,
        message: message.into(),
        notices: Vec::new(),
        argparse: false,
    }
}

impl SourceFailure {
    fn with_notices(mut self, notices: &[String]) -> Self {
        self.notices.extend(notices.iter().cloned());
        self
    }

    fn argparse(mut self) -> Self {
        self.argparse = true;
        self
    }
}

fn source_keys(records: &[Record]) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut ordered = Vec::new();
    for record in records {
        for key in record.keys() {
            if seen.insert(key.clone()) {
                ordered.push(key.clone());
            }
        }
    }
    ordered
}

pub fn load_records(args: &GenerateArgs) -> Result<LoadedRecords, SourceFailure> {
    let mut notices = Vec::new();
    let (records, source_pointer) = match args.source {
        Source::Excel => {
            let path = args.data.as_deref().ok_or_else(|| {
                failure(
                    2,
                    "--data 가 필요합니다 (또는 --fields, 또는 --source pclm)",
                )
                .argparse()
            })?;
            if args.sheet.is_none() {
                let overview = ambiguous_sheets(path).map_err(|err| failure(2, err.to_string()))?;
                if !overview.is_empty() {
                    let listing = overview
                        .iter()
                        .map(|(name, rows, cols)| format!("  - {name} ({rows}행 x {cols}열)"))
                        .collect::<Vec<_>>()
                        .join("\n");
                    return Err(failure(
                        2,
                        format!(
                            "'{}' 에 시트가 여러 개입니다 — 조용히 첫 시트를 쓰지 않습니다. --sheet <이름> 으로 지정하세요:\n{listing}",
                            path.display()
                        ),
                    ).argparse());
                }
            }
            let mut source = ExcelDataSource::new(path, args.sheet.clone(), 1)
                .map_err(|err| failure(2, err.to_string()))?;
            let records = source
                .records()
                .map_err(|err| failure(2, err.to_string()))?;
            (records, format!("file:{}", path.display()))
        }
        Source::Pclm => {
            let db = args.db.as_deref().unwrap_or(std::path::Path::new(""));
            let view = match &args.view {
                Some(view) => view.clone(),
                None => {
                    let listing = list_sqlite_sheets(db)
                        .map_err(|err| failure(2, err.to_string()))?
                        .into_iter()
                        .map(|name| format!("  {name}"))
                        .collect::<Vec<_>>()
                        .join("\n");
                    return Err(failure(
                        2,
                        format!(
                            "--source pclm 에는 --view <이름> 이 필요합니다 — 조용히 기본 뷰를 쓰지 않습니다:\n{listing}"
                        ),
                    ).argparse());
                }
            };
            let mut source =
                PclmDataSource::new(db, view).map_err(|err| failure(2, err.to_string()))?;
            let records = source
                .records()
                .map_err(|err| failure(2, err.to_string()))?;
            notices.push(format!(
                "[계약 목록] {} 의 {} 에서 {}건",
                source.db.display(),
                source.view,
                records.len()
            ));
            let pointer = source.source_pointer().unwrap_or_default();
            (records, pointer)
        }
    };
    let source_keys = source_keys(&records);
    Ok(LoadedRecords {
        records,
        source_keys,
        source_pointer,
        notices,
    })
}

/// Reads and parses `--profile` into a `MappingProfile`. Only the file-shaped failures
/// (read/JSON/profile-shape) live here; structural fit against the template is checked
/// by the caller once `required` is also known.
fn load_profile(path: &std::path::Path) -> Result<MappingProfile, SourceFailure> {
    let raw = fs::read_to_string(path).map_err(|err| {
        failure(
            2,
            format!("파일을 읽거나 쓸 수 없습니다: {} — {err}", path.display()),
        )
    })?;
    let value: Value = serde_json::from_str(&raw).map_err(|err| failure(2, err.to_string()))?;
    MappingProfile::from_dict(&value).map_err(|err| failure(2, err.to_string()))
}

/// A template structure read failure is only fatal if there is no profile to fall back
/// on for field coverage; with a profile, it instead reports as a structure drift.
fn resolve_required_fields(
    required: Result<Vec<String>, String>,
    has_profile: bool,
) -> Result<Vec<String>, SourceFailure> {
    match required {
        Ok(fields) => Ok(fields),
        Err(reason) if has_profile => Err(failure(
            1,
            format!("템플릿 구조 드리프트 — 템플릿 구조를 읽을 수 없음: {reason}"),
        )),
        Err(reason) => Err(failure(2, reason)),
    }
}

/// With a profile, confirms it still covers `required` (structure drift) and reuses it
/// as-is; without one, derives a passthrough mapping from the source's own keys,
/// noting any `required` field the source does not provide.
fn derive_mapping(
    profile: Option<MappingProfile>,
    required: &[String],
    source_keys: &[String],
    notices: &mut Vec<String>,
) -> Result<MappingProfile, SourceFailure> {
    let Some(profile) = profile else {
        let mut mappings = Vec::with_capacity(required.len());
        let mut missing = Vec::new();
        for field in required {
            if source_keys.contains(field) {
                mappings.push(
                    FieldMapping::new(field, field, "text", "", "", None)
                        .map_err(|err| failure(2, err.to_string()))?,
                );
            } else {
                mappings.push(
                    FieldMapping::new(field, "", "const", "", "", None)
                        .map_err(|err| failure(2, err.to_string()))?,
                );
                missing.push(field.clone());
            }
        }
        if !missing.is_empty() {
            notices.push(format!(
                "[경고] 데이터에 없는 필드(빈 값 생성): {}",
                missing.join(", ")
            ));
        }
        return MappingProfile::new("", mappings, Map::new())
            .map_err(|err| failure(2, err.to_string()));
    };
    let job = Job {
        mapping: profile.clone(),
        ..Job::default()
    };
    let drift = StructureDrift::from_fields(&job, Ok(required.to_vec()));
    if drift.has_drift() {
        return Err(failure(
            1,
            format!("템플릿 구조 드리프트 — {}", drift.describe("; ")),
        ));
    }
    Ok(profile)
}

/// Only CLI-specific preflight; managed sealing and run admission stay in JobController.
pub fn prepare_generation(
    args: &GenerateArgs,
    loaded: &LoadedRecords,
    required: Result<Vec<String>, String>,
) -> Result<PreparedGeneration, SourceFailure> {
    let mut notices = loaded.notices.clone();
    let profile = args.profile.as_deref().map(load_profile).transpose()?;
    let required = resolve_required_fields(required, profile.is_some())?;
    let mapping = derive_mapping(profile, &required, &loaded.source_keys, &mut notices)?;
    let raw = loaded
        .records
        .iter()
        .map(|record| {
            record
                .iter()
                .map(|(key, value)| (key.clone(), Value::String(value.clone())))
                .collect::<Map<_, _>>()
        })
        .collect::<Vec<_>>();
    let effective_records = if args.profile.is_some() {
        mapping
            .apply_all(&raw, Some(Local::now().naive_local()))
            .map_err(|err| failure(2, err.to_string()))?
    } else {
        raw
    };
    let declared_empty = mapping
        .declared_empty_fields()
        .into_iter()
        .collect::<HashSet<_>>();
    let checked = required
        .iter()
        .filter(|field| !declared_empty.contains(*field))
        .cloned()
        .collect::<Vec<_>>();
    let validation = validate(&checked, &effective_records);
    if !validation.missing_columns.is_empty() {
        notices.push(format!(
            "[경고] 데이터에 없는 필드(빈 값 생성): {}",
            validation.missing_columns.join(", ")
        ));
    }
    if !validation.empty_valued.is_empty() {
        if !args.ack_empty {
            let marker = MISSING_MARKER.replace("{field}", "필드명");
            return Err(failure(
                1,
                format!(
                    "값이 비어 있는 필드가 있습니다 — 표식 없이 조용히 생성하지 않습니다: {}\n확인했으면 --ack-empty 를 지정하세요(빈 필드에 '{marker}' 표식을 넣고 진행).",
                    validation.empty_valued.join(", ")
                ),
            ).with_notices(&notices[loaded.notices.len()..]));
        }
        notices.push(format!(
            "[안내] 미입력 표식 주입: {}",
            validation.empty_valued.join(", ")
        ));
    }
    let tokens = pattern_field_tokens(&args.pattern);
    if !effective_records.is_empty() && !tokens.is_empty() {
        let unresolved = tokens
            .into_iter()
            .filter(|token| {
                effective_records
                    .iter()
                    .all(|record| !record.contains_key(token))
            })
            .collect::<Vec<_>>();
        if !unresolved.is_empty() {
            return Err(failure(
                2,
                format!(
                    "파일명 패턴의 토큰이 데이터에 없어 그대로 파일명이 됩니다: {} — --pattern 을 데이터 키에 맞게 지정하세요",
                    unresolved
                        .iter()
                        .map(|token| format!("{{{{{token}}}}}"))
                        .collect::<Vec<_>>()
                        .join(", ")
                ),
            ).with_notices(&notices[loaded.notices.len()..]).argparse());
        }
    }
    if loaded.records.is_empty() {
        return Err(failure(1, "데이터 레코드가 없어 문서를 만들지 않았습니다.")
            .with_notices(&notices[loaded.notices.len()..]));
    }
    Ok(PreparedGeneration { mapping, notices })
}

pub fn parse(args: &[OsString]) -> Result<Parsed, String> {
    let mut template = None;
    let mut source = Source::Excel;
    let mut data = None;
    let mut out = PathBuf::from("./out");
    let mut pattern = DEFAULT_FILENAME_PATTERN.to_owned();
    let mut sheet = None;
    let mut profile = None;
    let mut fields = false;
    let mut overwrite = false;
    let mut ack_empty = false;
    let mut ledger = false;
    let mut db = None;
    let mut view = None;
    let mut iter = args.iter();
    while let Some(arg) = iter.next() {
        let rendered = arg.to_string_lossy();
        let (key, inline) = rendered
            .split_once('=')
            .filter(|(key, _)| key.starts_with("--"))
            .map_or((rendered.as_ref(), None), |(key, value)| (key, Some(value)));
        match key {
            "-h" | "--help" => return Ok(Parsed::Help),
            "--fields" if inline.is_none() => fields = true,
            "--overwrite" if inline.is_none() => overwrite = true,
            "--ack-empty" if inline.is_none() => ack_empty = true,
            "--ledger" if inline.is_none() => ledger = true,
            "--template" | "--data" | "--out" | "--pattern" | "--sheet" | "--profile"
            | "--source" | "--db" | "--view" => {
                let value = match inline {
                    Some(value) => value.to_owned(),
                    None => iter
                        .next()
                        .ok_or_else(|| format!("argument {key}: expected one argument"))?
                        .to_string_lossy()
                        .into_owned(),
                };
                if inline.is_none() && value.starts_with('-') && value != "-" {
                    return Err(format!("argument {key}: expected one argument"));
                }
                match key {
                    "--template" => template = Some(PathBuf::from(value)),
                    "--data" => data = Some(PathBuf::from(value)),
                    "--out" => out = PathBuf::from(value),
                    "--pattern" => pattern = value,
                    "--sheet" => sheet = Some(value),
                    "--profile" => profile = Some(PathBuf::from(value)),
                    "--source" => {
                        source = match value.as_str() {
                            "excel" => Source::Excel,
                            "pclm" => Source::Pclm,
                            _ => {
                                return Err(format!(
                                    "argument --source: invalid choice: {} (choose from 'excel', 'pclm')",
                                    python_repr(&Value::String(value))
                                ));
                            }
                        }
                    }
                    "--db" => db = Some(PathBuf::from(value)),
                    "--view" => view = Some(value),
                    _ => unreachable!(),
                }
            }
            _ => return Err(format!("unrecognized arguments: {rendered}")),
        }
    }
    let template = template.ok_or("the following arguments are required: --template")?;
    if fields {
        return Ok(Parsed::Fields(template));
    }
    Ok(Parsed::Generate(Box::new(GenerateArgs {
        template,
        source,
        data,
        out,
        pattern,
        sheet,
        profile,
        overwrite,
        ack_empty,
        ledger,
        db,
        view,
    })))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::super::tests::test_directory;
    use super::*;

    #[test]
    fn generation_preflight_requires_explicit_empty_ack_and_nonempty_records() {
        assert!(matches!(
            parse(&[
                "--template".into(),
                "a.hwpx".into(),
                "--data".into(),
                "data.csv".into(),
                "--fields".into(),
            ]),
            Ok(Parsed::Fields(path)) if path == std::path::Path::new("a.hwpx")
        ));
        let Parsed::Generate(mut args) = parse(&[
            "--template".into(),
            "a.hwpx".into(),
            "--pattern".into(),
            "{{name}}".into(),
        ])
        .expect("generation arguments") else {
            panic!("generation argument shape");
        };
        let loaded = LoadedRecords {
            records: vec![Record::from_iter([("name".into(), " ".into())])],
            source_keys: vec!["name".into()],
            source_pointer: "file:data.csv".into(),
            notices: Vec::new(),
        };
        let refused = prepare_generation(&args, &loaded, Ok(vec!["name".into()]))
            .err()
            .expect("blank value must refuse");
        assert_eq!(refused.exit_code, 1);
        assert!(refused.message.contains("--ack-empty"));
        args.ack_empty = true;
        let ready = prepare_generation(&args, &loaded, Ok(vec!["name".into()]))
            .ok()
            .expect("explicit acknowledgement");
        assert_eq!(ready.mapping.cover_fields(), vec!["name"]);
        assert!(
            ready
                .notices
                .iter()
                .any(|line| line.contains("미입력 표식"))
        );
        let missing_column = LoadedRecords {
            records: vec![Record::from_iter([("other".into(), "value".into())])],
            source_keys: vec!["other".into()],
            source_pointer: loaded.source_pointer.clone(),
            notices: Vec::new(),
        };
        let missing_pattern = prepare_generation(&args, &missing_column, Ok(vec!["name".into()]))
            .err()
            .expect("pattern token cannot be invented by a blank mapping");
        assert_eq!(missing_pattern.exit_code, 2);
        assert!(missing_pattern.argparse);
        assert_eq!(
            missing_pattern.notices,
            vec!["[경고] 데이터에 없는 필드(빈 값 생성): name"]
        );
        let no_rows = LoadedRecords {
            records: Vec::new(),
            source_keys: Vec::new(),
            source_pointer: loaded.source_pointer.clone(),
            notices: Vec::new(),
        };
        let zero = prepare_generation(&args, &no_rows, Ok(vec!["name".into()]))
            .err()
            .expect("zero records must refuse");
        assert_eq!(zero.exit_code, 1);
        assert_eq!(zero.notices.len(), 1);
    }

    #[test]
    fn coded_records_reach_profiled_and_unprofiled_document_generation() {
        let root = test_directory();
        let Parsed::Generate(args) = parse(&["--template".into(), "a.hwpx".into()]).unwrap() else {
            panic!("generation arguments")
        };
        let mut args = *args;
        args.template = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus/real/bid_notice_limited_under100m.hwpx");
        args.out = root.join("profiled");
        args.pattern = "n-{{입찰공고번호}}".into();
        let required = super::super::field_lines(&args.template).unwrap();
        let mappings = required
            .iter()
            .map(|field| {
                let (key, kind) = match field.as_str() {
                    "입찰공고번호" => ("bidNtceNo", "text"),
                    "공고명" => ("bidNtceNm", "text"),
                    "추정가격" => ("presmptPrce", "amount"),
                    "개찰일시" => ("opengDate", "date"),
                    _ => ("", "const"),
                };
                FieldMapping::new(field, key, kind, "", "", None).unwrap()
            })
            .collect();
        let profile = MappingProfile::new("영문 코드", mappings, Map::new()).unwrap();
        let profile_path = root.join("profile.json");
        fs::write(
            &profile_path,
            serde_json::to_vec(&profile.to_dict()).unwrap(),
        )
        .unwrap();
        args.profile = Some(profile_path);
        let coded = || {
            let records = [
                [
                    ("bidNtceNo", "R26BK01561738"),
                    ("bidNtceNm", "2026 대구치맥페스티벌 컨테이너 라운지 조성"),
                    ("presmptPrce", "65454545"),
                    ("opengDate", "2026-06-15"),
                ],
                [
                    ("bidNtceNo", "R26BK01568286"),
                    (
                        "bidNtceNm",
                        "2026년 국립청주박물관 상설전시실 전시환경 개선",
                    ),
                    ("presmptPrce", "901818182"),
                    ("opengDate", "2026-06-24"),
                ],
            ]
            .map(|row| Record::from_iter(row.map(|(key, value)| (key.into(), value.into()))))
            .to_vec();
            LoadedRecords {
                source_keys: source_keys(&records),
                records,
                source_pointer: "file:coded.json".into(),
                notices: Vec::new(),
            }
        };
        let loaded = coded();
        assert_eq!(
            super::super::generate_run::execute_loaded(args.clone(), loaded),
            0
        );
        assert_eq!(fs::read_dir(&args.out).unwrap().count(), 2);
        let package = hwpx_core::package::HwpxPackage::from_bytes(
            &fs::read(args.out.join("n-R26BK01561738.hwpx")).unwrap(),
            Default::default(),
        )
        .unwrap();
        let fields = hwpx_filler::fields::read_fields(&package).unwrap();
        for (field, value) in [("추정가격", "65,454,545원"), ("개찰일시", "2026. 6. 15.")]
        {
            let actual: Vec<_> = fields.iter().filter(|(name, _)| name == field).collect();
            assert!(!actual.is_empty());
            assert!(actual.iter().all(|(_, text)| text == value));
        }
        args.profile = None;
        args.pattern = DEFAULT_FILENAME_PATTERN.into();
        args.out = root.join("unprofiled");
        let loaded = coded();
        args.pattern = "공고서-{{ID}}".into();
        let error = prepare_generation(&args, &loaded, Ok(required))
            .err()
            .unwrap();
        assert_eq!(error.exit_code, 2);
        assert!(error.argparse && error.message.contains("파일명 패턴의 토큰이 데이터에 없어"));
        assert!(!args.out.exists());
        args.pattern = DEFAULT_FILENAME_PATTERN.into();
        assert_eq!(
            super::super::generate_run::execute_loaded(args.clone(), loaded),
            0
        );
        assert_eq!(fs::read_dir(&args.out).unwrap().count(), 2);
        fs::remove_dir_all(root).unwrap();
    }
}
