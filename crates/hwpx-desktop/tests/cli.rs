//! CLI process boundary: redirected UTF-8, exit codes, diagnostics and document effects.

use hwpx_core::package::{HwpxPackage, MIMETYPE_NAME, MIMETYPE_VALUE, PackageEntry};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn repo() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}
fn text(path: &Path) -> &str {
    path.to_str().unwrap()
}
struct Cli {
    root: PathBuf,
    template: PathBuf,
    data: PathBuf,
    out: PathBuf,
}
impl Cli {
    fn new() -> Self {
        let root = repo()
            .join("target/cli-process")
            .join(uuid::Uuid::new_v4().to_string());
        fs::create_dir_all(root.join("temp")).unwrap();
        fs::create_dir_all(root.join("home/jobs")).unwrap();
        fs::write(root.join("home/jobs/user.job.json"), "user-owned").unwrap();
        let data = root.join("자료.csv");
        fs::write(&data, "입찰공고번호,공고명,계약방법,추정가격,개찰일시,관리번호\nR-1,관급자재 구매,일반경쟁,12000000,2026-08-01 10:00,K-1\n").unwrap();
        Self {
            template: repo().join("tests/corpus/real/bid_notice_limited_under100m.hwpx"),
            data,
            out: root.join("out"),
            root,
        }
    }
    fn run(&self, args: &[&str], code: i32) -> (String, String) {
        let result = Command::new(env!("CARGO_BIN_EXE_hwpxfiller"))
            .args(args)
            .current_dir(&self.root)
            .env("HWPXFILLER_HOME", self.root.join("home"))
            .env("TEMP", self.root.join("temp"))
            .env("TMP", self.root.join("temp"))
            .output()
            .unwrap();
        let stdout = String::from_utf8(result.stdout).expect("redirected stdout must be UTF-8");
        let stderr = String::from_utf8(result.stderr).expect("redirected stderr must be UTF-8");
        assert_eq!(
            fs::read(self.root.join("home/jobs/user.job.json")).unwrap(),
            b"user-owned"
        );
        assert_eq!(fs::read_dir(self.root.join("home")).unwrap().count(), 1);
        assert_eq!(
            fs::read_dir(self.root.join("home/jobs")).unwrap().count(),
            1
        );
        assert_eq!(
            result.status.code(),
            Some(code),
            "{args:?}\n{stdout}\n{stderr}"
        );
        assert!(
            !stderr.contains("panicked") && !stderr.contains("Traceback"),
            "{stderr}"
        );
        (stdout, stderr)
    }
    fn generate(&self, extra: &[&str], code: i32) -> (String, String) {
        let mut args = vec![
            "--template",
            text(&self.template),
            "--data",
            text(&self.data),
            "--out",
            text(&self.out),
            "--pattern",
            "공고-{{입찰공고번호}}",
        ];
        args.extend_from_slice(extra);
        self.run(&args, code)
    }
    fn files(&self, extension: &str) -> Vec<PathBuf> {
        if !self.out.exists() {
            return Vec::new();
        }
        let mut files = fs::read_dir(&self.out)
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .filter(|path| path.extension().is_some_and(|ext| ext == extension))
            .collect::<Vec<_>>();
        files.sort();
        files
    }
}
impl Drop for Cli {
    fn drop(&mut self) {
        assert!(self.root.starts_with(repo().join("target/cli-process")));
        let _ = fs::remove_dir_all(&self.root);
    }
}
fn package(path: &Path) -> HwpxPackage {
    HwpxPackage::from_bytes(&fs::read(path).unwrap(), Default::default()).unwrap()
}
fn fields(path: &Path) -> Vec<(String, String)> {
    hwpx_filler::fields::read_fields(&package(path)).unwrap()
}

#[test]
fn redirected_help_fields_and_errors_keep_the_public_console_contract() {
    let cli = Cli::new();
    let (help, err) = cli.run(&["--help"], 0);
    assert!(err.is_empty());
    for word in [
        "schema",
        "fieldize",
        "lint",
        "drift",
        "render",
        "diff",
        "매핑 프로파일",
    ] {
        assert!(help.contains(word), "{word}");
    }
    assert!(
        cli.run(&["fieldize", "--help"], 0)
            .0
            .contains("누름틀 변환")
    );
    let help = cli.run(&["drift", "--help"], 0).0;
    assert!(help.contains("구판") && help.contains("신판"));
    let err = cli.run(&["bogsub"], 2).1;
    for word in ["알 수 없는 하위명령", "bogsub", "schema", "lint"] {
        assert!(err.contains(word));
    }
    assert!(!err.contains("the following arguments are required"));
    let (listed, _) = cli.run(&["--template", text(&cli.template), "--fields"], 0);
    for word in ["입찰공고번호", "공고명", "계약방법", "추정가격", "개찰일시"]
    {
        assert!(listed.contains(word));
    }
    assert!(
        cli.run(&["--template", text(&cli.template)], 2)
            .1
            .contains("--data")
    );
    let missing = cli.root.join("없는.hwpx");
    let err = cli.run(&["--template", text(&missing), "--fields"], 2).1;
    assert!(err.starts_with("[오류]"));
    assert_eq!(err.lines().count(), 1);
    fs::write(&missing, "손상 파일").unwrap();
    assert!(
        cli.run(&["lint", text(&missing)], 2)
            .1
            .starts_with("[오류]")
    );
    let vocab = cli.root.join("vocab.txt");
    fs::write(&vocab, "\u{feff}입찰공고번호\n공고명\n").unwrap();
    let out = cli
        .run(&["lint", text(&cli.template), "--vocab", text(&vocab)], 1)
        .0;
    assert!(!out.contains('\u{feff}') && !out.contains("'입찰공고번호'"));
}

#[test]
fn generation_requires_overwrite_and_keeps_ledger_evidence_for_each_run() {
    let cli = Cli::new();
    cli.generate(&[], 0);
    assert!(cli.files("json").is_empty());
    let document = cli.out.join("공고-R-1.hwpx");
    assert_eq!(package(&document).entries[0].name, "mimetype");
    fs::write(&document, "user-edited").unwrap();
    let err = cli.generate(&[], 1).1;
    assert!(err.contains("덮어쓰") && err.contains("--overwrite"));
    assert_eq!(fs::read(&document).unwrap(), b"user-edited");
    for expected_count in [1, 2] {
        assert!(
            cli.generate(&["--overwrite", "--ledger"], 0)
                .1
                .contains("[원장]")
        );
        let ledgers = cli.files("json");
        assert_eq!(ledgers.len(), expected_count);
        for ledger in ledgers {
            let value: Value = serde_json::from_slice(&fs::read(ledger).unwrap()).unwrap();
            assert_eq!(value["ledger_kind"], "managed-delivery/v1");
            assert_eq!(value["outcome"], "DeliveryCompleted");
            assert_eq!(value["source"], format!("file:{}", cli.data.display()));
            for key in ["execution_basis_digest", "plan_semantic_digest"] {
                assert!(value[key].as_str().unwrap().starts_with("sha256:"));
            }
            assert_eq!(value["delivered"][0]["relative_path"], "공고-R-1.hwpx");
            assert_eq!(
                value["delivered"][0]["collision_disposition"],
                "WRITE_OVERWRITE"
            );
            assert!(
                value["delivered"][0]["output_digest"]
                    .as_str()
                    .unwrap()
                    .starts_with("sha256:")
            );
        }
    }
    assert_eq!(cli.files("hwpx"), [document]);
}

#[test]
fn generation_refuses_unsafe_names_and_drift_and_acknowledges_empty_values() {
    let mut cli = Cli::new();
    for pattern in ["../公고", "C:공고", "CON", "공고-{{관리번호}}"] {
        let err = cli.generate(&["--pattern", pattern], 1).1;
        assert!(err.contains("[오류]"));
        assert!(cli.files("hwpx").is_empty());
        if pattern.contains("관리번호") {
            assert!(err.contains("OUTPUT_NAME_TOKEN_UNRESOLVED"));
        }
    }
    let profile = cli.root.join("partial.json");
    fs::write(&profile, json!({"mappings":[{"template_field":"입찰공고번호","source_key":"입찰공고번호","type":"text"}]}).to_string()).unwrap();
    assert!(
        cli.generate(&["--profile", text(&profile)], 1)
            .1
            .contains("구조 드리프트")
    );
    assert!(cli.files("hwpx").is_empty());
    let blocked = cli.root.join("blocked");
    fs::write(&blocked, "existing").unwrap();
    assert!(
        cli.generate(&["--out", text(&blocked)], 2)
            .1
            .contains("[오류]")
    );
    assert_eq!(fs::read(&blocked).unwrap(), b"existing");
    fs::write(&cli.data, "입찰공고번호,공고명\n,관급자재 구매\n").unwrap();
    let err = cli.generate(&["--pattern", "公고-{{공고명}}"], 1).1;
    assert!(err.contains("입찰공고번호") && err.contains("--ack-empty"));
    assert!(cli.files("hwpx").is_empty());
    cli.generate(
        &["--pattern", "공고-{{공고명}}", "--ack-empty", "--ledger"],
        0,
    );
    let ledger: Value = serde_json::from_slice(&fs::read(&cli.files("json")[0]).unwrap()).unwrap();
    let delivered = &ledger["delivered"][0];
    assert_eq!(delivered["collision_disposition"], "WRITE_NEW");
    let output = cli.out.join(delivered["relative_path"].as_str().unwrap());
    assert_eq!(
        delivered["output_digest"],
        format!(
            "sha256:{}",
            Sha256::digest(fs::read(&output).unwrap())
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>()
        )
    );
    let values = fields(&output);
    assert!(values.contains(&("입찰공고번호".into(), "〘미입력·입찰공고번호〙".into())));
    assert!(values.contains(&("공고명".into(), "관급자재 구매".into())));
    cli.out = cli.root.join("case-twins");
    fs::write(&cli.data, "입찰공고번호,공고명\nReport,공고\nreport,공고\n").unwrap();
    cli.generate(&["--pattern", "{{입찰공고번호}}"], 0);
    let names: Vec<_> = cli
        .files("hwpx")
        .iter()
        .map(|path| path.file_name().unwrap().to_str().unwrap().to_lowercase())
        .collect();
    assert_eq!(names, ["report.hwpx", "report_1.hwpx"]);
}

#[test]
fn pclm_requires_explicit_database_and_sheet_and_reports_source_pointer() {
    let mut cli = Cli::new();
    for extra in [
        vec!["--source", "pclm"],
        vec!["--source", "pclm", "--view", "v_통합_v2"],
    ] {
        assert!(
            cli.generate(&extra, 2)
                .1
                .contains("[오류] 데이터 참조에 경로가 없습니다.")
        );
    }
    let db = cli.root.join("계약.db");
    assert!(
        cli.generate(&["--source", "pclm", "--db", text(&db)], 2)
            .1
            .starts_with("[오류]")
    );
    fs::write(&db, b"not a database").unwrap();
    assert!(
        cli.generate(&["--source", "pclm", "--db", text(&db)], 2)
            .1
            .contains("열지 못했습니다")
    );
    fs::remove_file(&db).unwrap();
    let connection = rusqlite::Connection::open(&db).unwrap();
    connection.execute_batch("CREATE TABLE 계약 (입찰공고번호 TEXT, 공고명 TEXT); INSERT INTO 계약 VALUES ('R-DB', '계약 자료'); CREATE VIEW v_통합_v2 AS SELECT * FROM 계약;").unwrap();
    drop(connection);
    let err = cli.generate(&["--source", "pclm", "--db", text(&db)], 2).1;
    assert!(err.contains("--view") && err.contains("  v_통합_v2\n  계약"));
    assert!(!err.contains("v_통합_v1"));
    let err = cli
        .generate(
            &["--source", "pclm", "--db", text(&db), "--view", "v_없음"],
            2,
        )
        .1;
    for word in ["v_없음", "v_통합_v2", "계약"] {
        assert!(err.contains(word));
    }
    assert!(!cli.out.exists());
    for view in ["계약", "v_통합_v2"] {
        cli.out = cli.root.join(view);
        let err = cli
            .generate(
                &[
                    "--source",
                    "pclm",
                    "--db",
                    text(&db),
                    "--view",
                    view,
                    "--ledger",
                ],
                0,
            )
            .1;
        for word in ["[계약 목록]", text(&db), view, "1건"] {
            assert!(err.contains(word));
        }
        assert_eq!(cli.files("hwpx"), [cli.out.join("공고-R-DB.hwpx")]);
        let ledger: Value =
            serde_json::from_slice(&fs::read(&cli.files("json")[0]).unwrap()).unwrap();
        assert_eq!(ledger["source"], format!("sqlite:{}#{view}", db.display()));
        assert!(!ledger["source"].as_str().unwrap().contains("R-DB"));
    }
}

#[test]
fn workbook_selection_and_text_structure_are_checked_before_output() {
    let mut cli = Cli::new();
    let workbook = repo().join("tests/fixtures/multi_sheet.xlsx");
    let template = cli.root.join("plain.txt");
    fs::write(&template, "업체: {{업체명}}\r\n").unwrap();
    for args in [
        vec![
            "--template",
            text(&cli.template),
            "--data",
            text(&workbook),
            "--out",
            text(&cli.out),
        ],
        vec!["render", text(&template), "--data", text(&workbook)],
    ] {
        let err = cli.run(&args, 2).1;
        for name in ["공고목록", "낙찰현황", "--sheet"] {
            assert!(err.contains(name));
        }
        assert!(!cli.out.exists());
    }
    let rendered = cli.root.join("rendered.txt");
    cli.run(
        &[
            "render",
            text(&template),
            "--data",
            text(&workbook),
            "--sheet",
            "낙찰현황",
            "--out",
            text(&rendered),
        ],
        0,
    );
    assert_eq!(fs::read(&rendered).unwrap(), "업체: 가나상사\n".as_bytes());
    cli.generate(
        &[
            "--data",
            text(&workbook),
            "--sheet",
            "공고목록",
            "--pattern",
            "{{공고명}}",
        ],
        0,
    );
    assert_eq!(
        cli.files("hwpx"),
        [cli.out.join("사무용품.hwpx"), cli.out.join("전산장비.hwpx")]
    );
    let single = repo().join("tests/corpus/scenario/data/조달_한글.xlsx");
    cli.out = cli.root.join("single");
    cli.generate(&["--data", text(&single)], 0);
    assert_eq!(
        cli.files("hwpx"),
        ["2026-001", "2026-002", "2026-003"].map(|id| cli.out.join(format!("공고-{id}.hwpx")))
    );
    assert!(
        fields(&cli.out.join("공고-2026-001.hwpx"))
            .contains(&("공고명".into(), "친환경 선박용 소화장비 구매".into()))
    );
    cli.run(
        &[
            "render",
            text(&template),
            "--data",
            text(&single),
            "--out",
            text(&rendered),
        ],
        0,
    );
    fs::write(
        &template,
        "공고: {{공고명}}\n{{#항목 첨부 첨부}}\n{{#선택 가 가}}\n가 본문\n{{/선택}}\n{{/항목}}\n",
    )
    .unwrap();
    fs::remove_file(&rendered).unwrap();
    let (stdout, err) = cli.run(
        &[
            "render",
            text(&template),
            "--data",
            text(&cli.data),
            "--out",
            text(&rendered),
        ],
        1,
    );
    assert!(stdout.is_empty() && !rendered.exists());
    for word in ["구간 표기가 4건", "작업대", "문서 만들기"] {
        assert!(err.contains(word));
    }
    fs::write(&template, "공고: {{공고명}}\n번호: {{입찰공고번호}}\n").unwrap();
    cli.run(
        &[
            "render",
            text(&template),
            "--data",
            text(&cli.data),
            "--out",
            text(&rendered),
        ],
        0,
    );
    assert_eq!(
        fs::read(&rendered).unwrap(),
        "공고: 관급자재 구매\n번호: R-1\n".as_bytes()
    );
}

#[test]
fn fill_notes_are_emitted_once_for_the_whole_batch() {
    let mut cli = Cli::new();
    let section = r#"<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p><hp:run><hp:ctrl><hp:fieldBegin name="계약명"/></hp:ctrl></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run><hp:run><hp:ctrl><hp:fieldBegin name="공고번호"/></hp:ctrl></hp:run><hp:run><hp:t>OLD<hp:markpenBegin/>X<hp:markpenEnd/></hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p></hs:sec>"#;
    let package = HwpxPackage {
        entries: vec![
            PackageEntry {
                name: MIMETYPE_NAME.into(),
                data: MIMETYPE_VALUE.into(),
                stored: true,
            },
            PackageEntry {
                name: "Contents/section0.xml".into(),
                data: section.as_bytes().into(),
                stored: false,
            },
        ],
    };
    cli.template = cli.root.join("notes.hwpx");
    fs::write(&cli.template, package.to_bytes().unwrap()).unwrap();
    fs::write(
        &cli.data,
        "계약명,공고번호\n정보시스템 구축,2026-001\n정보시스템 구축,2026-002\n",
    )
    .unwrap();
    let err = cli.generate(&["--pattern", "doc-{{공고번호}}"], 0).1;
    for message in [
        "빈 누름틀 '계약명'",
        "인라인 요소(markpenBegin, markpenEnd)",
    ] {
        assert_eq!(err.matches(message).count(), 1, "{err}");
    }
    assert_eq!(cli.files("hwpx").len(), 2);
}
