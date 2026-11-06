//! Windows CLI for managed HWPX generation and template tools.
#![cfg_attr(coverage_nightly, feature(coverage_attribute))]

#[path = "hwpxfiller/generate.rs"]
mod generate;
#[path = "hwpxfiller/generate_run.rs"]
mod generate_run;

use hwpx_core::package::{HwpxPackage, PackageError, PackageLimits};
use hwpx_filler::authoring::{compile_document, scan_tokens};
use hwpx_filler::data_excel::{ExcelDataSource, ambiguous_sheets};
use hwpx_filler::data_source::DataSource;
use hwpx_filler::fields::required_fields;
use hwpx_filler::lint::{DEFAULT_SIMILARITY_THRESHOLD, lint_template};
use hwpx_filler::mapping::MappingProfile;
use hwpx_filler::schema::extract_schema;
use hwpx_filler::schema_drift::{SchemaDrift, diff_schema};
use hwpx_filler::structure_scan::python_trim;
use hwpx_filler::text_render::render_record;
use hwpx_filler::text_structure::scan_text_structure;
use serde_json::Value;
use std::collections::HashMap;
use std::ffi::OsString;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

const GENERATION_HELP: &str = r#"usage: hwpxfiller [-h] --template TEMPLATE [--source {excel,nara,pclm}]
                  [--data DATA] [--out OUT] [--pattern PATTERN]
                  [--sheet SHEET] [--profile PROFILE] [--fields] [--overwrite]
                  [--ack-empty] [--ledger] [--service-key SERVICE_KEY]
                  [--service-key-file SERVICE_KEY_FILE] [--bgn BGN]
                  [--end END] [--num-rows NUM_ROWS] [--page PAGE] [--db DB]
                  [--view VIEW]

options:
  -h, --help            show this help message and exit
  --template TEMPLATE   HWPX 템플릿 경로
  --source {excel,nara,pclm}
                        데이터 소스 (기본: excel). pclm 은 계약 목록 DB 의 시트(뷰·표)이며 --view
                        가 필수입니다
  --data DATA           엑셀/CSV 데이터 경로 (--source excel)
  --out OUT             결과 저장 폴더
  --pattern PATTERN     파일명 패턴({{필드}}, 기본 공고서-{{date}}-{{seq:001}}). 토큰은 템플릿
                        필드 이름이며 연결된 값으로 채워집니다 — 풀 수 없는 토큰은 오류
  --sheet SHEET         엑셀 시트명(기본: 첫 시트)
  --profile PROFILE     매핑 프로파일 JSON(소스 키→템플릿 필드; 나라장터 영문키에 사실상 필수).
                        작업(.job.json)의 mapping 과 같은 형식의 독립 JSON 입니다
  --fields              템플릿 요구 필드만 출력
  --overwrite           같은 이름의 기존 산출물 덮어쓰기 허용(옵트인). 없으면 대상 파일이 하나라도 이미 있을 때 생성
                        전체를 차단하고 종료코드 1
  --ack-empty           값이 비어 있는 필드를 확인했음을 표시(옵트인) — 빈 필드에 미입력 표식(〘미입력·필드명〙)을
                        넣고 진행. 없으면 빈 값 발견 시 생성 전체를 차단하고 종료코드 1
  --ledger              생성 원장 JSON 사이드카를 out 폴더에 저장(opt-in) — 소스 프로파일·dry-run
                        매니페스트·주입 되읽기 증거. 값은 텍스트이며 HWPX 렌더가 아님
  --service-key SERVICE_KEY
                        data.go.kr ServiceKey 인라인(비권장·노출 위험). --service-key-
                        file/DATA_GO_KR_KEY/저장된 키를 우선 쓰세요
  --service-key-file SERVICE_KEY_FILE
                        ServiceKey 를 담은 파일 경로(권장 — 프로세스 목록/히스토리 미노출)
  --bgn BGN             공고 시작일시 YYYYMMDDHHMM (--source nara)
  --end END             공고 종료일시 YYYYMMDDHHMM (bgn 과 1개월 이내)
  --num-rows NUM_ROWS   나라장터 페이지당 건수(기본 100)
  --page PAGE           나라장터 페이지 번호(기본 1)
  --db DB               pclm SQLite 경로 (필수, --source pclm)
  --view VIEW           pclm 시트(뷰·표) 이름 (필수, --source pclm). 이름 목록은 미지정 시 안내

하위명령(자세한 도움말: hwpxfiller <하위명령> --help):
  schema TPL.hwpx           템플릿 스키마(필드·타입·표 영역)를 JSON 으로 추출
  fieldize TPL.hwpx         평문 {{토큰}} → 누름틀 변환(--out 없으면 미리보기)
  lint TPL.hwpx             템플릿 위생 점검(--vocab 통제 어휘) — 이슈 있으면 exit 1
  drift OLD.hwpx NEW.hwpx   판본 간 필드 드리프트(추가/삭제/개명)
  render TPL.txt --data D   텍스트 템플릿 치환(온나라 기안 등)
  diff                      별도 제품·별도 저장소로 분리됨(hwpxdiff OLD.hwpx NEW.hwpx)"#;
const SCHEMA_HELP: &str = "사용법: hwpxfiller schema TPL.hwpx [--out schema.json]\n  template  HWPX 템플릿 경로\n  --out     JSON 저장 경로(생략 시 표준출력)";
const FIELDIZE_HELP: &str = "사용법: hwpxfiller fieldize TPL.hwpx [--out compiled.hwpx]\n  template  평문 토큰이 든 HWPX 경로\n  --out     누름틀 변환 결과 저장 경로(생략 시 미리보기만)";
const LINT_HELP: &str = "사용법: hwpxfiller lint TPL.hwpx [--vocab words.txt]\n  template  HWPX 템플릿 경로\n  --vocab   통제 어휘 사전(한 줄에 필드명 하나)";
const DRIFT_HELP: &str =
    "사용법: hwpxfiller drift OLD.hwpx NEW.hwpx\n  old  구판 HWPX\n  new  신판 HWPX";
const RENDER_HELP: &str = "사용법: hwpxfiller render TEMPLATE --data DATA [--profile PROFILE] [--record N] [--sheet SHEET] [--out PATH] [--clip]";
const RENDER_ARGPARSE_USAGE: &str = "usage: hwpxfiller render [-h] --data DATA [--profile PROFILE]\n                         [--record RECORD] [--sheet SHEET] [--out OUT]\n                         [--clip]\n                         template";

enum Command {
    Help(&'static str),
    Unknown(String),
    RetiredDiff,
    Generate(Box<generate::GenerateArgs>),
    Fields(PathBuf),
    Schema {
        template: PathBuf,
        out: Option<PathBuf>,
    },
    Fieldize {
        template: PathBuf,
        out: Option<PathBuf>,
    },
    Lint {
        template: PathBuf,
        vocab: Option<PathBuf>,
    },
    Drift {
        old: PathBuf,
        new: PathBuf,
    },
    Render {
        template: PathBuf,
        data: PathBuf,
        profile: Option<PathBuf>,
        record: usize,
        sheet: Option<String>,
        out: Option<PathBuf>,
        clip: bool,
    },
}

fn parse_args(args: impl IntoIterator<Item = OsString>) -> Result<Command, String> {
    let args: Vec<_> = args.into_iter().collect();
    match args.first().and_then(|arg| arg.to_str()) {
        Some("diff") => Ok(Command::RetiredDiff),
        Some("schema") => parse_schema(&args[1..]),
        Some("fieldize") => parse_template_option(&args[1..], "fieldize", "--out", FIELDIZE_HELP)
            .map(|command| match command {
                Command::Schema { template, out } => Command::Fieldize { template, out },
                other => other,
            }),
        Some("lint") => {
            parse_template_option(&args[1..], "lint", "--vocab", LINT_HELP).map(|command| {
                match command {
                    Command::Schema { template, out } => Command::Lint {
                        template,
                        vocab: out,
                    },
                    other => other,
                }
            })
        }
        Some("drift") => parse_drift(&args[1..]),
        Some("render") => parse_render(&args[1..]),
        Some(name) if !name.starts_with('-') => Ok(Command::Unknown(name.into())),
        _ => parse_fields(&args),
    }
}

fn parse_render(args: &[OsString]) -> Result<Command, String> {
    let mut template = None;
    let mut data = None;
    let mut profile = None;
    let mut record = 1usize;
    let mut sheet = None;
    let mut out = None;
    let mut clip = false;
    let mut at = 0;
    let mut positional_only = false;
    while at < args.len() {
        let arg = &args[at];
        if !positional_only && arg == "--" {
            positional_only = true;
        } else if !positional_only && (arg == "--help" || arg == "-h") {
            return Ok(Command::Help(RENDER_HELP));
        } else if !positional_only && arg == "--clip" {
            clip = true;
        } else if !positional_only
            && ["--data", "--profile", "--record", "--sheet", "--out"]
                .iter()
                .any(|name| arg == name)
        {
            let key = arg.to_string_lossy().into_owned();
            at += 1;
            let value = args
                .get(at)
                .ok_or_else(|| format!("render {key} 에 값이 필요합니다."))?;
            assign_render_option(
                &key,
                value,
                &mut data,
                &mut profile,
                &mut record,
                &mut sheet,
                &mut out,
            )?;
        } else if !positional_only
            && arg
                .to_str()
                .is_some_and(|text| text.starts_with("--") && text.contains('='))
        {
            let (key, value) = arg.to_str().unwrap().split_once('=').unwrap();
            assign_render_option(
                key,
                &OsString::from(value),
                &mut data,
                &mut profile,
                &mut record,
                &mut sheet,
                &mut out,
            )?;
        } else if (!positional_only && arg != "-" && arg.to_string_lossy().starts_with('-'))
            || template.is_some()
        {
            return Err(format!("지원하지 않는 인자: {}", arg.to_string_lossy()));
        } else {
            template = Some(PathBuf::from(arg));
        }
        at += 1;
    }
    Ok(Command::Render {
        template: template.ok_or("render 에 텍스트 템플릿 경로가 필요합니다.")?,
        data: data.ok_or("render --data 에 경로가 필요합니다.")?,
        profile,
        record,
        sheet,
        out,
        clip,
    })
}

fn assign_render_option(
    key: &str,
    value: &OsString,
    data: &mut Option<PathBuf>,
    profile: &mut Option<PathBuf>,
    record: &mut usize,
    sheet: &mut Option<String>,
    out: &mut Option<PathBuf>,
) -> Result<(), String> {
    if value.is_empty() {
        return Err(format!("render {key} 에 값이 필요합니다."));
    }
    match key {
        "--data" => *data = Some(PathBuf::from(value)),
        "--profile" => *profile = Some(PathBuf::from(value)),
        "--out" => *out = Some(PathBuf::from(value)),
        "--sheet" => *sheet = Some(value.to_string_lossy().into_owned()),
        "--record" => {
            *record = value
                .to_string_lossy()
                .parse()
                .map_err(|_| "--record 는 정수여야 합니다.")?
        }
        _ => return Err(format!("지원하지 않는 인자: {key}")),
    }
    Ok(())
}

fn parse_template_option(
    args: &[OsString],
    command: &str,
    option: &str,
    help: &'static str,
) -> Result<Command, String> {
    let mut template = None;
    let mut output = None;
    let mut positional_only = false;
    let mut at = 0;
    while at < args.len() {
        let arg = &args[at];
        if !positional_only && arg == "--" {
            positional_only = true;
        } else if !positional_only && (arg == "--help" || arg == "-h") {
            return Ok(Command::Help(help));
        } else if !positional_only && arg == option {
            at += 1;
            let value = args
                .get(at)
                .ok_or_else(|| format!("{command} {option} 에 경로가 필요합니다."))?;
            if value.is_empty() || (value != "-" && value.to_string_lossy().starts_with('-')) {
                return Err(format!("{command} {option} 에 경로가 필요합니다."));
            }
            output = Some(PathBuf::from(value));
        } else if !positional_only
            && let Some(path) = arg
                .to_str()
                .and_then(|s| s.strip_prefix(&format!("{option}=")))
        {
            output = (!path.is_empty()).then(|| PathBuf::from(path));
        } else if (!positional_only && arg != "-" && arg.to_string_lossy().starts_with('-'))
            || template.is_some()
        {
            return Err(format!("지원하지 않는 인자: {}", arg.to_string_lossy()));
        } else {
            template = Some(PathBuf::from(arg));
        }
        at += 1;
    }
    template
        .map(|template| Command::Schema {
            template,
            out: output,
        })
        .ok_or_else(|| format!("{command} 에 HWPX 템플릿 경로가 필요합니다."))
}

fn parse_schema(args: &[OsString]) -> Result<Command, String> {
    let mut template = None;
    let mut out = None;
    let mut positional_only = false;
    let mut at = 0;
    while at < args.len() {
        let arg = &args[at];
        if !positional_only && arg == "--" {
            positional_only = true;
        } else if !positional_only && (arg == "--help" || arg == "-h") {
            return Ok(Command::Help(SCHEMA_HELP));
        } else if !positional_only && arg == "--out" {
            at += 1;
            let value = args
                .get(at)
                .ok_or("schema --out 에 저장 경로가 필요합니다.")?;
            if value != "-" && value.to_string_lossy().starts_with('-') {
                return Err("schema --out 에 저장 경로가 필요합니다.".into());
            }
            out = (!value.is_empty()).then(|| PathBuf::from(value.clone()));
        } else if !positional_only
            && let Some(path) = arg.to_str().and_then(|s| s.strip_prefix("--out="))
        {
            out = (!path.is_empty()).then(|| PathBuf::from(path));
        } else if (!positional_only && arg != "-" && arg.to_string_lossy().starts_with('-'))
            || template.is_some()
        {
            return Err(format!("지원하지 않는 인자: {}", arg.to_string_lossy()));
        } else {
            template = Some(PathBuf::from(arg.clone()));
        }
        at += 1;
    }
    template
        .map(|template| Command::Schema { template, out })
        .ok_or_else(|| "schema 에 HWPX 템플릿 경로가 필요합니다.".into())
}

fn parse_drift(args: &[OsString]) -> Result<Command, String> {
    let mut paths = Vec::new();
    let mut positional_only = false;
    for arg in args {
        if !positional_only && arg == "--" {
            positional_only = true;
        } else if !positional_only && (arg == "--help" || arg == "-h") {
            return Ok(Command::Help(DRIFT_HELP));
        } else if !positional_only && arg != "-" && arg.to_string_lossy().starts_with('-') {
            return Err(format!("지원하지 않는 인자: {}", arg.to_string_lossy()));
        } else {
            paths.push(PathBuf::from(arg.clone()));
        }
    }
    if paths.len() != 2 {
        return Err("drift 에 구판·신판 HWPX 경로가 필요합니다.".into());
    }
    Ok(Command::Drift {
        old: paths.remove(0),
        new: paths.remove(0),
    })
}

fn parse_fields(args: &[OsString]) -> Result<Command, String> {
    match generate::parse(args)? {
        generate::Parsed::Help => Ok(Command::Help(GENERATION_HELP)),
        generate::Parsed::Fields(path) => Ok(Command::Fields(path)),
        generate::Parsed::Generate(args) => Ok(Command::Generate(args)),
    }
}

fn read_capped<R: Read>(reader: R, max_bytes: u64) -> io::Result<Vec<u8>> {
    let mut bytes = Vec::new();
    reader.take(max_bytes + 1).read_to_end(&mut bytes)?;
    PackageLimits {
        max_archive_bytes: max_bytes,
        ..Default::default()
    }
    .check_archive_size(bytes.len() as u64)
    .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    Ok(bytes)
}

fn read_package(path: &Path) -> Result<HwpxPackage, String> {
    let file = File::open(path)
        .map_err(|err| format!("파일을 읽거나 쓸 수 없습니다: {} — {err}", path.display()))?;
    let limits = PackageLimits::default();
    let size = file
        .metadata()
        .map_err(|err| format!("파일을 읽거나 쓸 수 없습니다: {} — {err}", path.display()))?
        .len();
    limits
        .check_archive_size(size)
        .map_err(|err| err.to_string())?;
    let bytes = read_capped(file, limits.max_archive_bytes).map_err(|err| {
        if err.kind() == io::ErrorKind::InvalidData {
            err.to_string()
        } else {
            format!("파일을 읽거나 쓸 수 없습니다: {} — {err}", path.display())
        }
    })?;
    HwpxPackage::from_bytes(&bytes, limits).map_err(|err| match err {
        PackageError::Invalid(_) => format!("HWPX(zip) 파일이 아니거나 손상됐습니다: {err}"),
        PackageError::Budget { .. } => err.to_string(),
    })
}

fn field_lines(path: &Path) -> Result<Vec<String>, String> {
    let package = read_package(path)?;
    required_fields(&package).map_err(|err| err.to_string())
}

fn schema_json(path: &Path) -> Result<String, String> {
    let package = read_package(path)?;
    let schema = extract_schema(&package).map_err(|err| err.to_string())?;
    serde_json::to_string_pretty(&schema).map_err(|err| err.to_string())
}

fn drift_lines(old: &Path, new: &Path) -> Result<Vec<String>, String> {
    let old = read_package(old)?;
    let new = read_package(new)?;
    let drift = diff_schema(&old, &new).map_err(|err| err.to_string())?;
    render_drift(drift)
}

fn render_drift(drift: SchemaDrift) -> Result<Vec<String>, String> {
    if !drift.has_changes() {
        return Ok(vec!["필드셋 변화 없음.".into()]);
    }
    let mut lines = Vec::new();
    lines.extend(
        drift
            .added
            .into_iter()
            .map(|name| format!("  + 추가: {name}")),
    );
    lines.extend(
        drift
            .removed
            .into_iter()
            .map(|name| format!("  - 삭제: {name}")),
    );
    for rename in drift.renamed {
        let score = serde_json::to_string(&rename.score).map_err(|err| err.to_string())?;
        lines.push(format!(
            "  ~ 개명(추정): {} -> {} (유사도 {score})",
            rename.old, rename.new
        ));
    }
    Ok(lines)
}

fn write_bytes_atomic(target: &Path, bytes: &[u8]) -> io::Result<()> {
    let directory = target
        .parent()
        .filter(|path| !path.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    for attempt in 0..16 {
        let temporary = directory.join(format!(
            "hwpxfiller-{}-{stamp}-{attempt}.tmp",
            std::process::id()
        ));
        let mut file = match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
        {
            Ok(file) => file,
            Err(err) if err.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(err) => return Err(err),
        };
        let written = file.write_all(bytes);
        drop(file);
        let result = written.and_then(|()| fs::rename(&temporary, target));
        if let Err(err) = result {
            return Err(match fs::remove_file(&temporary) {
                Ok(()) => err,
                Err(cleanup) => io::Error::new(
                    err.kind(),
                    format!(
                        "{err}; 임시 파일 정리 실패: {} — {cleanup}",
                        temporary.display()
                    ),
                ),
            });
        }
        return Ok(());
    }
    Err(io::Error::new(
        io::ErrorKind::AlreadyExists,
        "temporary file name collision",
    ))
}

fn write_text_atomic(target: &Path, text: &str) -> io::Result<()> {
    write_bytes_atomic(target, text.as_bytes())
}

fn read_vocabulary(path: &Path) -> Result<Vec<String>, String> {
    let bytes = fs::read(path)
        .map_err(|err| format!("파일을 읽거나 쓸 수 없습니다: {} — {err}", path.display()))?;
    let text = String::from_utf8(bytes).map_err(|err| err.to_string())?;
    let text = text.strip_prefix('\u{feff}').unwrap_or(&text);
    Ok(text
        .split(['\r', '\n'])
        .map(python_trim)
        .filter(|line| !line.is_empty())
        .map(str::to_owned)
        .collect())
}

fn render_text(
    template: &Path,
    data: &Path,
    profile: Option<&Path>,
    record_number: usize,
    sheet: Option<&str>,
    out: Option<&Path>,
    clip: bool,
) -> Result<u8, String> {
    let text = fs::read_to_string(template).map_err(|err| {
        format!(
            "파일을 읽거나 쓸 수 없습니다: {} — {err}",
            template.display()
        )
    })?;
    let text = text.replace("\r\n", "\n").replace('\r', "\n");
    let markers = scan_text_structure(&text).summary.markers;
    if markers > 0 {
        eprintln!(
            "구간 표기가 {markers}건 있는 템플릿입니다 — 이 명령은 '포함할 내용'을 고를 수 없어 문서를 만들 수 없습니다.\n문서나르미의 '문서 만들기'에서 이 작업을 실행하고 검토·복사 작업대에서 복사하세요."
        );
        return Ok(1);
    }
    if sheet.is_none() {
        let sheets = ambiguous_sheets(data).map_err(|err| err.to_string())?;
        if !sheets.is_empty() {
            let listing = sheets
                .iter()
                .map(|(name, rows, cols)| format!("  - {name} ({rows}행 x {cols}열)"))
                .collect::<Vec<_>>()
                .join("\n");
            eprintln!("{RENDER_ARGPARSE_USAGE}");
            eprintln!(
                "hwpxfiller render: error: '{}' 에 시트가 여러 개입니다 — 조용히 첫 시트를 쓰지 않습니다. --sheet <이름> 으로 지정하세요:\n{listing}",
                data.display()
            );
            return Ok(2);
        }
    }
    let mut source =
        ExcelDataSource::new(data, sheet.map(str::to_owned), 1).map_err(|err| err.to_string())?;
    let records = source.records().map_err(|err| err.to_string())?;
    if records.is_empty() {
        eprintln!("데이터에 레코드가 없습니다.");
        return Ok(1);
    }
    if record_number == 0 || record_number > records.len() {
        eprintln!("--record {record_number} 범위 밖(1..{}).", records.len());
        return Ok(1);
    }
    let raw = records[record_number - 1]
        .iter()
        .map(|(key, value)| (key.clone(), Value::String(value.clone())))
        .collect::<serde_json::Map<_, _>>();
    let record = if let Some(path) = profile {
        let bytes = fs::read(path)
            .map_err(|err| format!("파일을 읽거나 쓸 수 없습니다: {} — {err}", path.display()))?;
        let encoded: Value = serde_json::from_slice(&bytes).map_err(|err| err.to_string())?;
        let mapping = MappingProfile::from_dict(&encoded).map_err(|err| err.to_string())?;
        mapping
            .apply(&raw, Some(chrono::Local::now().naive_local()))
            .map_err(|err| err.to_string())?
    } else {
        raw
    };
    let record: HashMap<_, _> = record.into_iter().collect();
    let (rendered, report) = render_record(&text, &record);
    if !report.missing_fields.is_empty() {
        eprintln!(
            "[경고] 데이터에 없는 필드(토큰 유지): {}",
            report.missing_fields.join(", ")
        );
    }
    if !report.empty_fields.is_empty() {
        eprintln!(
            "[안내] 값이 비어있는 필드: {}",
            report.empty_fields.join(", ")
        );
    }
    if let Some(path) = out {
        write_text_atomic(path, &rendered)
            .map_err(|err| format!("파일을 읽거나 쓸 수 없습니다: {} — {err}", path.display()))?;
        eprintln!("렌더 저장: {}", path.display());
    } else {
        print_lines([rendered.clone()])?;
    }
    if clip {
        copy_to_clipboard(&rendered);
    }
    Ok(0)
}

fn copy_to_clipboard(text: &str) {
    #[cfg(windows)]
    use std::os::windows::process::CommandExt;
    use std::process::{Command as ProcessCommand, Stdio};

    let mut command = ProcessCommand::new("powershell");
    command
        .args([
            "-NoProfile",
            "-Command",
            "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); $value = [Console]::In.ReadToEnd(); Set-Clipboard -Value $value",
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    command.creation_flags(0x0800_0000);
    let mut process = match command.spawn() {
        Ok(process) => process,
        Err(error) => {
            eprintln!("[안내] 클립보드 복사 실패({error}). 표준출력/--out 을 쓰세요.");
            return;
        }
    };
    let written = process
        .stdin
        .take()
        .map(|mut stdin| stdin.write_all(text.as_bytes()));
    let result = written
        .transpose()
        .and_then(|_| process.wait().map(|status| status.success()));
    match result {
        Ok(true) => eprintln!("클립보드로 복사했습니다."),
        Ok(false) => eprintln!("[안내] 클립보드 복사 실패(powershell). 표준출력/--out 을 쓰세요."),
        Err(error) => eprintln!("[안내] 클립보드 복사 실패({error}). 표준출력/--out 을 쓰세요."),
    }
}

fn print_lines(lines: impl IntoIterator<Item = String>) -> Result<(), String> {
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in lines {
        writeln!(out, "{line}").map_err(|err| format!("파일을 읽거나 쓸 수 없습니다: {err}"))?;
    }
    Ok(())
}

fn run(command: Command) -> Result<u8, String> {
    match command {
        Command::Help(help) => print_lines([help.to_owned()]).map(|()| 0),
        Command::Unknown(name) => {
            eprintln!(
                "[오류] 알 수 없는 하위명령: {}",
                hwpx_filler::text_render::python_repr(&Value::String(name))
            );
            eprintln!("문서 생성은 'hwpxfiller --template ...' 이고, 하위명령은 아래와 같습니다:");
            // The final help paragraph owns the command list for both routes.
            eprintln!(
                "{}",
                GENERATION_HELP
                    .rsplit("\n\n")
                    .next()
                    .unwrap_or(GENERATION_HELP)
            );
            Ok(2)
        }
        Command::Generate(args) => Ok(generate_run::execute(*args)),
        Command::Fields(path) => print_lines(field_lines(&path)?).map(|()| 0),
        Command::Schema { template, out } => {
            let payload = schema_json(&template)?;
            if let Some(path) = out {
                write_text_atomic(&path, &payload).map_err(|err| {
                    format!("파일을 읽거나 쓸 수 없습니다: {} — {err}", path.display())
                })?;
                eprintln!("스키마 저장: {}", path.display());
                Ok(0)
            } else {
                print_lines([payload]).map(|()| 0)
            }
        }
        Command::Fieldize { template, out } => {
            let mut package = read_package(&template)?;
            if let Some(path) = out {
                let report = compile_document(&mut package, None).map_err(|err| err.to_string())?;
                for site in &report.skipped {
                    eprintln!("  [건너뜀] {} — {}", site.name, site.reason);
                }
                if !report.modified {
                    print_lines(["변환할 토큰이 없습니다(이미 누름틀이거나 토큰 없음).".into()])?;
                    return Ok(0);
                }
                let bytes = package.to_bytes().map_err(|err| err.to_string())?;
                write_bytes_atomic(&path, &bytes).map_err(|err| {
                    format!("파일을 읽거나 쓸 수 없습니다: {} — {err}", path.display())
                })?;
                print_lines([format!(
                    "누름틀 변환 완료: 필드 {}개 -> {}",
                    report.compiled.len(),
                    path.display()
                )])?;
            } else {
                let sites = scan_tokens(&package).map_err(|err| err.to_string())?;
                let compilable: Vec<_> = sites.iter().filter(|site| site.compilable).collect();
                let skipped: Vec<_> = sites.iter().filter(|site| !site.compilable).collect();
                print_lines([format!(
                    "[미리보기] 변환 가능 {}개 / 건너뜀 {}개",
                    compilable.len(),
                    skipped.len()
                )])?;
                for site in compilable {
                    print_lines([format!("  + {}  ({})", site.name, site.context)])?;
                }
                for site in skipped {
                    eprintln!("  ! {}  — {}", site.name, site.reason);
                }
                print_lines(["실제 변환하려면 --out <경로> 를 지정하세요.".into()])?;
            }
            Ok(0)
        }
        Command::Lint { template, vocab } => {
            let package = read_package(&template)?;
            let vocabulary = vocab.as_deref().map(read_vocabulary).transpose()?;
            let report = lint_template(
                &package,
                vocabulary.as_deref(),
                DEFAULT_SIMILARITY_THRESHOLD,
            )
            .map_err(|err| err.to_string())?;
            if report.findings.is_empty() {
                print_lines(["이슈 없음.".into()])?;
            } else {
                print_lines(report.findings.iter().map(|finding| {
                    format!(
                        "  [{}] {}: {}",
                        finding.severity, finding.kind, finding.message
                    )
                }))?;
            }
            Ok(u8::from(report.has_issues()))
        }
        Command::RetiredDiff => {
            eprintln!(
                "diff 는 별도 제품 hwpxdiff 입니다: hwpxdiff OLD.hwpx NEW.hwpx [--html out.html]\n  설치: https://github.com/rfastball/hwpx-diff"
            );
            Ok(2)
        }
        Command::Drift { old, new } => print_lines(drift_lines(&old, &new)?).map(|()| 0),
        Command::Render {
            template,
            data,
            profile,
            record,
            sheet,
            out,
            clip,
        } => render_text(
            &template,
            &data,
            profile.as_deref(),
            record,
            sheet.as_deref(),
            out.as_deref(),
            clip,
        ),
    }
}

fn main() -> std::process::ExitCode {
    let args = std::env::args_os().skip(1).collect::<Vec<_>>();
    let generation = !matches!(
        args.first().and_then(|value| value.to_str()),
        Some("schema" | "fieldize" | "lint" | "drift" | "render" | "diff")
    );
    let command = match parse_args(args) {
        Ok(command) => command,
        Err(err) => {
            if generation {
                eprintln!("{}", generate::GENERATION_ARGPARSE_USAGE);
                eprintln!("hwpxfiller: error: {err}");
            } else {
                eprintln!("[오류] {err}");
            }
            return std::process::ExitCode::from(2);
        }
    };
    match run(command) {
        Ok(code) => std::process::ExitCode::from(code),
        Err(err) => {
            eprintln!("[오류] {err}");
            std::process::ExitCode::from(2)
        }
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn parses_native_commands_and_default_generation() {
        for args in [
            vec!["diff"],
            vec!["diff", "--help"],
            vec!["diff", "old.hwpx", "new.hwpx"],
        ] {
            let command = parse_args(args.into_iter().map(OsString::from)).unwrap();
            assert!(matches!(command, Command::RetiredDiff));
            assert_eq!(run(command).unwrap(), 2);
        }
        assert!(matches!(
            parse_args(["--help".into()]),
            Ok(Command::Help(_))
        ));
        assert!(matches!(
            parse_args(["--template".into(), "문서.hwpx".into(), "--help".into()]),
            Ok(Command::Help(_))
        ));
        assert!(matches!(
            parse_args(["--template".into(), "문서.hwpx".into(), "--fields".into()]),
            Ok(Command::Fields(path)) if path == Path::new("문서.hwpx")
        ));
        assert!(matches!(
            parse_args(["--template".into(), "".into(), "--fields".into()]),
            Ok(Command::Fields(path)) if path == Path::new("")
        ));
        assert!(matches!(
            parse_args(["--fields".into(), "--template=a.hwpx".into(), "--template".into(), "b.hwpx".into(), "--fields".into()]),
            Ok(Command::Fields(path)) if path == Path::new("b.hwpx")
        ));
        assert!(matches!(
            parse_args(["--template".into(), "문서.hwpx".into(), "--data".into(), "data.xlsx".into(), "--fields".into()]),
            Ok(Command::Fields(path)) if path == Path::new("문서.hwpx")
        ));
        assert!(matches!(
            parse_args(["--template".into(), "문서.hwpx".into()]),
            Ok(Command::Generate(args)) if args.template == Path::new("문서.hwpx")
                && args.pattern == hwpx_filler::job::DEFAULT_FILENAME_PATTERN
        ));
        assert!(matches!(
            parse_args(["schema".into(), "문서.hwpx".into(), "--out".into(), "schema.json".into()]),
            Ok(Command::Schema { template, out: Some(out) })
                if template == Path::new("문서.hwpx") && out == Path::new("schema.json")
        ));
        assert!(matches!(
            parse_args(["schema".into(), "--out=a.json".into(), "문서.hwpx".into(), "--out=b.json".into()]),
            Ok(Command::Schema { out: Some(out), .. }) if out == Path::new("b.json")
        ));
        assert!(matches!(
            parse_args(["schema".into(), "--out".into(), "-".into(), "--".into(), "-old.hwpx".into()]),
            Ok(Command::Schema { template, out: Some(out) })
                if template == Path::new("-old.hwpx") && out == Path::new("-")
        ));
        assert!(matches!(
            parse_args(["drift".into(), "old.hwpx".into(), "new.hwpx".into()]),
            Ok(Command::Drift { old, new })
                if old == Path::new("old.hwpx") && new == Path::new("new.hwpx")
        ));
        assert!(matches!(
            parse_args(["drift".into(), "--".into(), "-old.hwpx".into(), "-new.hwpx".into()]),
            Ok(Command::Drift { old, new })
                if old == Path::new("-old.hwpx") && new == Path::new("-new.hwpx")
        ));
        assert!(matches!(
            parse_args(["fieldize".into(), "문서.hwpx".into(), "--out=결과.hwpx".into()]),
            Ok(Command::Fieldize { template, out: Some(out) })
                if template == Path::new("문서.hwpx") && out == Path::new("결과.hwpx")
        ));
        assert!(matches!(
            parse_args(["lint".into(), "문서.hwpx".into(), "--vocab".into(), "단어.txt".into()]),
            Ok(Command::Lint { template, vocab: Some(vocab) })
                if template == Path::new("문서.hwpx") && vocab == Path::new("단어.txt")
        ));
        assert!(matches!(
            parse_args(["render".into(), "양식.txt".into(), "--data".into(), "자료.csv".into(), "--record=2".into(), "--out".into(), "결과.txt".into()]),
            Ok(Command::Render { template, data, record: 2, out: Some(out), .. })
                if template == Path::new("양식.txt") && data == Path::new("자료.csv") && out == Path::new("결과.txt")
        ));
        for args in [
            vec!["schema"],
            vec!["schema", "문서.hwpx", "--out"],
            vec!["drift", "old.hwpx"],
            vec!["drift", "old.hwpx", "new.hwpx", "--out", "x.json"],
            vec!["fieldize", "doc.hwpx", "--out"],
            vec!["lint", "doc.hwpx", "--vocab"],
            vec!["render", "양식.txt"],
            vec!["render", "양식.txt", "--data"],
            vec!["--template", "--fields", "--fields"],
        ] {
            assert!(parse_args(args.into_iter().map(OsString::from)).is_err());
        }
    }

    pub(super) fn test_directory() -> PathBuf {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../target/cli-tests");
        fs::create_dir_all(&root).unwrap();
        let stamp = uuid::Uuid::new_v4().simple();
        let path = root.join(format!("{}-{stamp}", std::process::id()));
        fs::create_dir(&path).unwrap();
        path
    }

    #[test]
    fn profile_display_formats_reach_generated_paragraphs_and_table_cells() {
        use hwpx_filler::mapping::FieldMapping;

        let root = test_directory();
        let template = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus/real/bid_notice_limited_under100m.hwpx");
        let package =
            HwpxPackage::from_bytes(&fs::read(&template).unwrap(), PackageLimits::default())
                .unwrap();
        let fields = required_fields(&package).unwrap();
        let data = root.join("data.csv");
        let profile = root.join("map.json");
        let samples = [
            ("수요기관", "text", "", "대한상사", "대한상사"),
            ("공고명", "text", "phone", "01012345678", "010-1234-5678"),
            ("세부품명", "date", "", "2026/7/17 18:05", "2026. 7. 17."),
            (
                "담당자",
                "date",
                "datetime",
                "2026/7/17 18:05",
                "2026. 7. 17. 18:05",
            ),
            ("계약방법", "amount", "", "24750000", "24,750,000원"),
            ("추정가격", "amount", "{:,.2f}", "24750000", "24,750,000.00"),
        ];
        let headers = samples
            .iter()
            .map(|sample| sample.0)
            .collect::<Vec<_>>()
            .join(",");
        let values = samples
            .iter()
            .map(|sample| sample.3)
            .collect::<Vec<_>>()
            .join(",");
        fs::write(&data, format!("\u{feff}번호,{headers}\nR-1,{values}\n")).unwrap();
        let mappings = fields
            .iter()
            .map(|field| {
                if field == "입찰공고번호" {
                    FieldMapping::new(field, "번호", "text", "", "", None)
                } else if let Some((_, kind, code, _, _)) =
                    samples.iter().find(|sample| sample.0 == field)
                {
                    FieldMapping::new(field, field, *kind, "", *code, None)
                } else {
                    FieldMapping::new(field, "", "const", "", "", None)
                }
                .unwrap()
            })
            .collect();
        let mapping = MappingProfile::new("p", mappings, serde_json::Map::new()).unwrap();
        fs::write(&profile, serde_json::to_vec(&mapping.to_dict()).unwrap()).unwrap();
        let output = root.join("output");
        let command = parse_args([
            OsString::from("--template"),
            template.as_os_str().to_owned(),
            OsString::from("--data"),
            data.as_os_str().to_owned(),
            OsString::from("--profile"),
            profile.as_os_str().to_owned(),
            OsString::from("--out"),
            output.as_os_str().to_owned(),
            OsString::from("--pattern"),
            OsString::from("p-{{입찰공고번호}}"),
        ])
        .unwrap();
        assert_eq!(run(command).unwrap(), 0);
        let bytes = fs::read(output.join("p-R-1.hwpx")).unwrap();
        let package = HwpxPackage::from_bytes(&bytes, PackageLimits::default()).unwrap();
        let actual = hwpx_filler::fields::read_fields(&package).unwrap();
        for (name, kind, code, _, expected) in samples {
            let values = actual
                .iter()
                .filter(|(field, _)| field == name)
                .map(|(_, value)| value.as_str())
                .collect::<Vec<_>>();
            assert!(!values.is_empty(), "{name}");
            assert!(
                values.iter().all(|value| *value == expected),
                "{kind}:{code} {name}: {values:?}"
            );
        }
        assert_eq!(fs::read_dir(&output).unwrap().count(), 1);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn atomic_schema_text_replaces_or_preserves_target_and_cleans_temp() {
        let dir = test_directory();
        let target = dir.join("schema.json");
        fs::write(&target, b"previous").unwrap();
        write_text_atomic(&target, "{\"공고명\": \"관급자재\"}").unwrap();
        assert_eq!(
            fs::read_to_string(&target).unwrap(),
            "{\"공고명\": \"관급자재\"}"
        );

        let long_name = dir.join(format!("{}.json", "x".repeat(230)));
        write_text_atomic(&long_name, "long").unwrap();
        assert_eq!(fs::read_to_string(&long_name).unwrap(), "long");

        let blocked = dir.join("directory");
        fs::create_dir(&blocked).unwrap();
        assert!(write_text_atomic(&blocked, "new").is_err());
        assert!(blocked.is_dir());
        assert_eq!(fs::read_dir(&dir).unwrap().count(), 3);

        fs::remove_file(target).unwrap();
        fs::remove_file(long_name).unwrap();
        fs::remove_dir(blocked).unwrap();
        fs::remove_dir(dir).unwrap();
    }

    #[test]
    fn schema_out_can_replace_disposable_input_after_full_read() {
        let dir = test_directory();
        let path = dir.join("template.hwpx");
        let fixture = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus/real/form_purchase_v1.hwpx");
        fs::copy(fixture, &path).unwrap();
        run(Command::Schema {
            template: path.clone(),
            out: Some(path.clone()),
        })
        .unwrap();
        let bytes = fs::read(&path).unwrap();
        assert!(bytes.starts_with(b"{\n  \"fields\": "));
        assert!(!bytes.ends_with(b"\n"));
        serde_json::from_slice::<serde_json::Value>(&bytes).unwrap();
        fs::remove_file(path).unwrap();
        fs::remove_dir(dir).unwrap();
    }

    #[test]
    fn fieldize_noop_preserves_target_and_lint_warning_exits_one() {
        use hwpx_core::package::{MIMETYPE_NAME, MIMETYPE_VALUE, PackageEntry};

        let dir = test_directory();
        let template = dir.join("plain.hwpx");
        let target = dir.join("existing.hwpx");
        let package = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: MIMETYPE_NAME.into(),
                    data: MIMETYPE_VALUE.into(),
                    stored: true,
                },
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: b"<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph'><hp:p><hp:run><hp:t>plain</hp:t></hp:run></hp:p></hs:sec>".to_vec(),
                    stored: false,
                },
            ],
        };
        fs::write(&template, package.to_bytes().unwrap()).unwrap();
        fs::write(&target, b"previous").unwrap();
        let vocab = dir.join("words.txt");
        fs::write(&vocab, "\u{feff}첫째\r둘째\r\n 셋째 \n".as_bytes()).unwrap();
        assert_eq!(read_vocabulary(&vocab).unwrap(), ["첫째", "둘째", "셋째"]);
        assert_eq!(
            run(Command::Fieldize {
                template: template.clone(),
                out: Some(target.clone()),
            })
            .unwrap(),
            0
        );
        assert_eq!(fs::read(&target).unwrap(), b"previous");
        assert_eq!(
            run(Command::Lint {
                template: template.clone(),
                vocab: None,
            })
            .unwrap(),
            1
        );
        fs::remove_file(template).unwrap();
        fs::remove_file(target).unwrap();
        fs::remove_file(vocab).unwrap();
        fs::remove_dir(dir).unwrap();
    }

    #[test]
    fn capped_read_rejects_file_growth() {
        assert_eq!(read_capped(&b"1234"[..], 4).unwrap(), b"1234");
        assert_eq!(
            read_capped(&b"12345"[..], 4).unwrap_err().kind(),
            io::ErrorKind::InvalidData
        );
    }

    #[test]
    fn renders_whitespace_only_rename_with_python_float_text() {
        use hwpx_filler::schema_drift::Rename;

        let lines = render_drift(SchemaDrift {
            added: vec![],
            removed: vec![],
            renamed: vec![Rename {
                old: "공고명".into(),
                new: "공고 명".into(),
                score: 1.0,
            }],
        })
        .unwrap();
        assert_eq!(lines, ["  ~ 개명(추정): 공고명 -> 공고 명 (유사도 1.0)"]);
    }
}
