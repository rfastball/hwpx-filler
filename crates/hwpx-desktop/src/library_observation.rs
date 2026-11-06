//! Host file facts for the pure library health and search projection.

use crate::dataset_registry::DatasetPoolRegistry;
use crate::job_registry::{CorruptJobEntry, JobRegistry};
use crate::locations::Locations;
use crate::settings_store;
use hwpx_core::package::PackageLimits;
use hwpx_filler::data_factory::source_for_binding;
use hwpx_filler::dataset_reference::{excel_identity, pclm_identity};
use hwpx_filler::home_state::{
    JobRow, LibraryLens, RowObservation, example_entry_state, inspect_hwpx_bytes, work_mode_label,
};
use hwpx_filler::job::Job;
use hwpx_filler::library_detail::FirstRowRead;
use hwpx_filler::library_detail::primary_action;
use serde_json::{Value, json};
use std::fs;
use std::io::{self, Read};
use std::path::Path;

#[cfg(test)]
thread_local! {
    static TEMPLATE_READS: std::cell::RefCell<Option<Vec<std::path::PathBuf>>> = const { std::cell::RefCell::new(None) };
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(crate) fn observe_template_reads<T>(
    action: impl FnOnce() -> T,
) -> (T, Vec<std::path::PathBuf>) {
    struct Reset;
    impl Drop for Reset {
        fn drop(&mut self) {
            TEMPLATE_READS.with(|reads| *reads.borrow_mut() = None);
        }
    }
    TEMPLATE_READS.with(|reads| {
        assert!(reads.borrow().is_none());
        *reads.borrow_mut() = Some(Vec::new());
    });
    let _reset = Reset;
    let result = action();
    let reads = TEMPLATE_READS.with(|reads| reads.borrow_mut().take().unwrap());
    (result, reads)
}

pub(crate) fn read_template(path: &Path) -> io::Result<Vec<u8>> {
    #[cfg(test)]
    TEMPLATE_READS.with(|reads| {
        if let Some(reads) = reads.borrow_mut().as_mut() {
            reads.push(path.to_path_buf());
        }
    });
    let file = fs::File::open(path)?;
    let size = file.metadata()?.len();
    read_template_bytes(file, size, PackageLimits::default())
}

fn read_template_bytes(reader: impl Read, size: u64, limits: PackageLimits) -> io::Result<Vec<u8>> {
    limits
        .check_archive_size(size)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    let mut bytes = Vec::new();
    reader
        .take(limits.max_archive_bytes + 1)
        .read_to_end(&mut bytes)?;
    limits
        .check_archive_size(bytes.len() as u64)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    Ok(bytes)
}

pub fn observe_job(job: &Job) -> RowObservation {
    let mut fact = RowObservation::default();
    if job.template_path.is_empty() {
        return fact;
    }
    let path = Path::new(&job.template_path);
    fact.template_missing = !path.exists();
    if fact.template_missing {
        return fact;
    }
    match job.media() {
        "hwpx" => {
            if let Ok(bytes) = read_template(path)
                && let Ok((status, fields)) = inspect_hwpx_bytes(&bytes)
            {
                fact.compile = Some(status);
                fact.template_fields = Some(fields);
            }
        }
        "txt" => match read_template(path).and_then(|bytes| {
            String::from_utf8(bytes)
                .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))
        }) {
            Ok(text) => {
                fact.template_fields = Some(Ok(hwpx_filler::text_render::template_fields(&text)));
            }
            Err(error) => {
                fact.txt_readable = false;
                fact.template_fields = Some(Err(error.to_string()));
            }
        },
        _ => (),
    }
    fact
}

/// One host read of the durable library. Corrupt job and dataset slots remain visible facts.
pub struct LibraryInventory {
    pub rows: Vec<JobRow>,
    pub corrupt_jobs: Vec<CorruptJobEntry>,
    pub pool_corrupted: usize,
}

pub fn read_library(
    jobs: &JobRegistry,
    datasets: &DatasetPoolRegistry,
) -> Result<LibraryInventory, String> {
    let (jobs, corrupt_jobs) = jobs
        .list_jobs_with_corruption()
        .map_err(|error| error.to_string())?;
    let rows = jobs
        .iter()
        .map(|job| JobRow::from_job(job, observe_job(job)))
        .collect();
    let (_, corrupt_datasets) = datasets
        .list_references(Some("active"))
        .map_err(|error| error.to_string())?;
    Ok(LibraryInventory {
        rows,
        corrupt_jobs,
        pool_corrupted: corrupt_datasets.len(),
    })
}

pub fn read_first_row(job: &Job) -> FirstRowRead {
    let (path, sheet, header_row, kind) = job.data_binding();
    let failed = |reason: String| FirstRowRead {
        state: "error".into(),
        reason,
        record: Default::default(),
        headers: Vec::new(),
        record_count: 0,
    };
    if !path.is_empty() && !Path::new(path).exists() {
        return failed(format!("경로를 찾을 수 없음: {path}"));
    }
    let header_row = if header_row == 0 {
        None
    } else {
        match usize::try_from(header_row) {
            Ok(value) => Some(value),
            Err(_) => return failed("header_row는 1 이상의 정수여야 합니다.".into()),
        }
    };
    let result = (|| {
        let mut source =
            source_for_binding(path, sheet, header_row, kind).map_err(|error| error.to_string())?;
        let records = source.records().map_err(|error| error.to_string())?;
        let headers = source.fields().map_err(|error| error.to_string())?;
        Ok::<_, String>((records, headers))
    })();
    let (records, headers) = match result {
        Ok(value) => value,
        Err(error) => return failed(error),
    };
    let Some(first) = records.first() else {
        return FirstRowRead {
            state: "error".into(),
            reason: "데이터에 행이 없습니다.".into(),
            record: Default::default(),
            headers,
            record_count: 0,
        };
    };
    FirstRowRead {
        state: "ready".into(),
        reason: String::new(),
        record: first
            .iter()
            .map(|(key, value)| (key.clone(), Value::String(value.clone())))
            .collect(),
        headers,
        record_count: records.len(),
    }
}

pub fn template_display_name(template_root: &Path, template_path: &str) -> String {
    let path = Path::new(template_path);
    match path.strip_prefix(template_root) {
        Ok(relative) => relative
            .with_extension("")
            .to_string_lossy()
            .replace('\\', "/"),
        Err(_) => path
            .file_stem()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned(),
    }
}

pub fn editable_applied_template_path(job: &Job, locations: &Locations) -> String {
    if job.authority_id.is_empty()
        || job.template_path.is_empty()
        || !Path::new(&job.template_path).is_file()
    {
        return String::new();
    }
    let applied = locations.template_authority().join("applied");
    match (
        Path::new(&job.template_path).canonicalize(),
        applied.canonicalize(),
    ) {
        (Ok(path), Ok(root)) if path.starts_with(&root) => job.template_path.clone(),
        _ => String::new(),
    }
}

pub fn dataset_display_name(registry: &DatasetPoolRegistry, job: &Job) -> String {
    if job.data_path.is_empty() {
        return String::new();
    }
    let identity = if job.data_kind == "pclm" {
        pclm_identity(&job.data_path, &job.data_sheet)
    } else {
        excel_identity(
            &job.data_path,
            (!job.data_sheet.is_empty()).then_some(job.data_sheet.as_str()),
        )
    };
    if let Ok(Some((_, item))) = registry.find_identity_raw(&identity) {
        return item.name;
    }
    Path::new(&job.data_path)
        .file_stem()
        .map_or_else(String::new, |name| name.to_string_lossy().into_owned())
}

pub fn tutorial_manifest_installed(settings_path: &Path, alert: impl Fn(&str)) -> io::Result<bool> {
    let settings = settings_store::read_with_alert(settings_path, alert)?;
    let manifest = settings
        .get("tutorial")
        .and_then(Value::as_object)
        .and_then(|tutorial| tutorial.get("manifest"))
        .and_then(Value::as_object);
    Ok(manifest.is_some_and(|manifest| {
        manifest
            .get("templates")
            .and_then(Value::as_array)
            .is_some_and(|templates| {
                templates.iter().all(|item| {
                    item.as_object()
                        .and_then(|item| item.get("path"))
                        .is_some_and(Value::is_string)
                })
            })
    }))
}

fn row_json(row: &JobRow) -> Value {
    let (severity, text) = row.health();
    let mode = row.library_mode();
    json!({
        "name": row.name,
        "meta_line": row.meta_line(),
        "compile_badge": row.compile_badge,
        "badge_level": row.badge_level(),
        "template_missing": row.template_missing,
        "data_bound": row.data_bound,
        "runnable": row.is_runnable(),
        "favorited": !row.favorited_at.is_empty(),
        "media": mode,
        "mode_label": work_mode_label(mode),
        "health": {"severity": severity, "text": text},
    })
}

/// Selected detail extends the same inventory snapshot; a vanished job keeps an empty detail.
pub fn selected_snapshot(
    inventory: &LibraryInventory,
    lens: &LibraryLens,
    examples_installed: bool,
    selected: &str,
    job: Option<&Job>,
    pairing: Option<Value>,
    template_edit_path: &str,
) -> Value {
    let mut snapshot = unselected_snapshot(inventory, lens, examples_installed);
    snapshot["selected"] = Value::String(selected.into());
    let Some(row) = inventory.rows.iter().find(|row| row.name == selected) else {
        return snapshot;
    };
    let Some(job) = job else {
        return snapshot;
    };
    let Some(pairing) = pairing else {
        return snapshot;
    };
    let mut detail = row_json(row);
    detail["primary"] = primary_action(row);
    detail["template_path"] = Value::String(job.template_path.clone());
    detail["template_edit_path"] = Value::String(template_edit_path.into());
    detail["data_label"] = Value::String(row.data_label.clone());
    detail["data_path"] = Value::String(job.data_path.clone());
    detail["health_causes"] = json!(
        row.health_causes()
            .into_iter()
            .map(|(severity, text)| json!({"severity": severity, "text": text}))
            .collect::<Vec<_>>()
    );
    detail["pairing_detail"] = pairing;
    snapshot["detail"] = detail;
    snapshot
}

/// Exact initial/unselected library payload; selected detail is a separate read path.
pub fn unselected_snapshot(
    inventory: &LibraryInventory,
    lens: &LibraryLens,
    examples_installed: bool,
) -> Value {
    let counts = lens.counts(&inventory.rows);
    let sections = lens
        .sections(&inventory.rows, false)
        .into_iter()
        .map(|section| {
            json!({
                "value": section.value,
                "label": section.value,
                "count": section.rows.len(),
                "is_untagged": section.is_untagged,
                "headed": false,
                "collapsed": false,
                "rows": section.rows.iter().map(row_json).collect::<Vec<_>>(),
            })
        })
        .collect::<Vec<_>>();
    json!({
        "alerts": {
            "missing_template_count": inventory.rows.iter().filter(|row| row.template_missing).count(),
            "pool_corrupted": inventory.pool_corrupted,
        },
        "is_empty": inventory.rows.is_empty() && inventory.corrupt_jobs.is_empty(),
        "export_all_enabled": !inventory.rows.is_empty(),
        "examples": example_entry_state(examples_installed),
        "view": lens.view,
        "mode": lens.mode,
        "query": lens.query,
        "counts": {
            "all": counts[0], "recent": counts[1],
            "favorites": counts[2], "needsAction": counts[3],
        },
        "sections": sections,
        "selected": "",
        "detail": Value::Null,
        "corrupt_rows": inventory.corrupt_jobs.iter().map(|entry| json!({
            "file_name": entry.file_name,
            "detail_line": format!("작업 파일을 읽을 수 없습니다: {}", entry.error),
            "path": entry.token,
        })).collect::<Vec<_>>(),
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{
        read_first_row, read_library, selected_snapshot, tutorial_manifest_installed,
        unselected_snapshot,
    };
    use crate::dataset_registry::DatasetPoolRegistry;
    use crate::job_registry::JobRegistry;
    use chrono::NaiveDate;
    use hwpx_filler::home_state::LibraryLens;
    use hwpx_filler::job::Job;
    use hwpx_filler::library_detail::pairing_detail;
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn template_read_checks_size_before_io_and_bounds_growth_after_metadata() {
        use std::io::{self, Cursor, Read};
        struct Unreadable;
        impl Read for Unreadable {
            fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
                panic!("oversize metadata must be rejected before reading");
            }
        }
        let limits = hwpx_core::package::PackageLimits {
            max_archive_bytes: 4,
            ..Default::default()
        };
        let error = super::read_template_bytes(Unreadable, 5, limits).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);
        assert_eq!(
            error.to_string(),
            "HWPX 자원 한도 초과: 파일 크기 5 B > 4 B"
        );
        let mut growing = Cursor::new(b"123456789");
        let error = super::read_template_bytes(&mut growing, 4, limits).unwrap_err();
        assert_eq!(
            error.to_string(),
            "HWPX 자원 한도 초과: 파일 크기 5 B > 4 B"
        );
        assert_eq!(growing.position(), 5);
        assert_eq!(
            super::read_template_bytes(&b"1234"[..], 4, limits).unwrap(),
            b"1234"
        );
    }

    #[test]
    fn template_display_name_is_relative_inside_root_and_basename_outside() {
        let root = PathBuf::from("D:/서식");
        for (path, expected) in [
            (root.join("공고서.hwpx"), "공고서"),
            (root.join("온나라/기안.txt"), "온나라/기안"),
            (PathBuf::from("E:/남의/문서.hwpx"), "문서"),
        ] {
            assert_eq!(
                super::template_display_name(&root, path.to_str().unwrap()),
                expected
            );
        }
    }

    #[test]
    fn initial_library_snapshot_uses_live_store_and_manifest_facts() {
        let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = workspace.join(format!(
            ".cache/library-observation-{}-{stamp}",
            std::process::id()
        ));
        fs::create_dir_all(&root).unwrap();
        assert!(root.canonicalize().unwrap().starts_with(&workspace));
        let templates = root.join("templates");
        let jobs = JobRegistry::new(root.join("jobs"), {
            let templates = templates.clone();
            move || templates.clone()
        })
        .unwrap();
        let datasets = DatasetPoolRegistry::new(root.join("datasets")).unwrap();
        assert_inventory_corruption(&root, &jobs, &datasets);
        assert_template_observations(&root, &jobs, &datasets);
        assert_applied_template_path(&root);
        let mut job = Job {
            name: "계약".into(),
            template_path: templates.join("absent.hwpx").to_str().unwrap().into(),
            filename_pattern: "계약-{{없는필드}}".into(),
            ..Job::default()
        };
        let csv = root.join("source.csv");
        fs::write(&csv, "사업명\n청사 교체\n").unwrap();
        job.data_path = csv.to_str().unwrap().into();
        job.data_header_row = 1;
        jobs.save(&mut job, false).unwrap();
        let read = read_first_row(&job);
        assert_eq!(read.state, "ready");
        assert_eq!(read.record["사업명"], "청사 교체");
        let inventory = read_library(&jobs, &datasets).unwrap();
        let snapshot = unselected_snapshot(&inventory, &LibraryLens::default(), false);
        assert_eq!(snapshot["alerts"]["missing_template_count"], 1);
        assert_eq!(snapshot["counts"]["needsAction"], 1);
        assert_eq!(snapshot["sections"][0]["rows"][0]["name"], "계약");
        assert_eq!(
            snapshot["sections"][0]["rows"][0]["health"]["text"],
            "템플릿 파일을 찾을 수 없습니다."
        );
        assert_eq!(snapshot["examples"]["label"], "예제로 시작하기…");
        assert_eq!(snapshot["sections"][0]["rows"][0]["data_bound"], true);
        assert_eq!(snapshot["sections"][0]["rows"][0]["runnable"], false);
        assert_eq!(
            snapshot["sections"][0]["rows"][0]["mode_label"],
            "HWPX 문서 생성"
        );
        let now = NaiveDate::from_ymd_opt(2026, 11, 5)
            .unwrap()
            .and_hms_opt(12, 0, 0)
            .unwrap();
        let pairing = pairing_detail(
            &inventory.rows[0],
            &job,
            "absent",
            "source",
            Some(&read),
            now,
        )
        .unwrap();
        let selected = selected_snapshot(
            &inventory,
            &LibraryLens::default(),
            false,
            "계약",
            Some(&job),
            Some(pairing),
            "",
        );
        assert_eq!(selected["selected"], "계약");
        assert_eq!(selected["detail"]["primary"]["target"], "job");
        assert_eq!(
            selected["detail"]["primary"]["label"],
            "문서 만들기에서 사용"
        );
        assert_eq!(selected["detail"]["data_path"], job.data_path);
        assert_eq!(selected["detail"]["data_label"], "source.csv");
        assert_eq!(
            selected["detail"]["health_causes"],
            serde_json::json!([
                {"severity":3,"text":"템플릿 파일을 찾을 수 없습니다."},
                {"severity":3,"text":"파일명 패턴의 토큰을 채우지 못합니다."},
            ])
        );
        assert_eq!(
            selected["detail"]["pairing_detail"]["first_row"],
            serde_json::Value::Null
        );
        let settings = root.join("settings.json");
        fs::write(
            &settings,
            br#"{"tutorial":{"manifest":{"templates":[{"path":"x"}]}}}"#,
        )
        .unwrap();
        assert!(tutorial_manifest_installed(&settings, |_| panic!("unexpected alert")).unwrap());
        fs::remove_dir_all(&root).unwrap();
    }

    fn assert_applied_template_path(root: &std::path::Path) {
        let locations =
            crate::locations::Locations::new(root, Some(root.as_os_str().to_os_string()));
        let path = locations
            .template_authority()
            .join("applied/work/template.hwpx");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, b"broken but owned").unwrap();
        let mut job = Job {
            template_path: path.to_str().unwrap().into(),
            authority_id: "work".into(),
            ..Job::default()
        };
        assert_eq!(
            super::editable_applied_template_path(&job, &locations),
            job.template_path
        );
        let external = root.join("external.hwpx");
        fs::write(&external, b"external").unwrap();
        job.template_path = external.to_str().unwrap().into();
        assert_eq!(super::editable_applied_template_path(&job, &locations), "");
        job.template_path = path.to_str().unwrap().into();
        job.authority_id.clear();
        assert_eq!(super::editable_applied_template_path(&job, &locations), "");
        job.authority_id = "work".into();
        fs::remove_file(&path).unwrap();
        assert_eq!(super::editable_applied_template_path(&job, &locations), "");
    }

    fn assert_inventory_corruption(
        root: &std::path::Path,
        jobs: &JobRegistry,
        datasets: &DatasetPoolRegistry,
    ) {
        let snapshot = || {
            unselected_snapshot(
                &read_library(jobs, datasets).unwrap(),
                &LibraryLens::default(),
                false,
            )
        };
        assert_eq!(snapshot()["is_empty"], true);
        assert_eq!(snapshot()["counts"]["all"], 0);
        assert_eq!(snapshot()["alerts"]["pool_corrupted"], 0);
        let broken_dataset = root.join("datasets/broken.dataset.json");
        fs::create_dir_all(broken_dataset.parent().unwrap()).unwrap();
        fs::write(&broken_dataset, "{ not json").unwrap();
        assert_eq!(snapshot()["alerts"]["pool_corrupted"], 1);
        fs::remove_file(broken_dataset).unwrap();
        let broken = root.join("jobs/broken.job.json");
        fs::create_dir_all(broken.parent().unwrap()).unwrap();
        fs::write(&broken, "{\"name\":").unwrap();
        let corrupt = snapshot();
        assert_eq!(corrupt["is_empty"], false);
        assert_eq!(corrupt["export_all_enabled"], false);
        assert_eq!(corrupt["corrupt_rows"][0]["file_name"], "broken.job.json");
        assert!(
            corrupt["corrupt_rows"][0]["detail_line"]
                .as_str()
                .unwrap()
                .contains("읽을 수 없습니다")
        );
        fs::write(&broken, r#"{"name":"broken","tags":{"금액구간":123}}"#).unwrap();
        let mut job = Job {
            name: "정상".into(),
            ..Job::default()
        };
        jobs.save(&mut job, false).unwrap();
        let inventory = read_library(jobs, datasets).unwrap();
        assert_eq!(inventory.rows.len(), 1);
        assert_eq!(inventory.rows[0].name, "정상");
        assert_eq!(inventory.corrupt_jobs.len(), 1);
        assert!(!inventory.corrupt_jobs[0].error.is_empty());
        assert_eq!(snapshot()["counts"]["all"], 1);
        assert_eq!(
            LibraryLens::default().sections(&inventory.rows, true)[0]
                .rows
                .len(),
            1
        );
        assert!(LibraryLens::default().facets(&inventory.rows).is_empty());
        jobs.delete("정상").unwrap();
        fs::remove_file(broken).unwrap();
    }

    fn assert_template_observations(
        root: &std::path::Path,
        jobs: &JobRegistry,
        datasets: &DatasetPoolRegistry,
    ) {
        use hwpx_core::package::{HwpxPackage, MIMETYPE_NAME, MIMETYPE_VALUE, PackageEntry};
        use hwpx_filler::authoring::compile_document;
        use hwpx_filler::fields::FieldDocument;
        use hwpx_filler::home_state::{CompileState, JobRow};
        use hwpx_filler::mapping::FieldMapping;
        const SECTION: &str = "Contents/section0.xml";
        let mut package = HwpxPackage { entries: vec![PackageEntry {
            name: MIMETYPE_NAME.into(), data: MIMETYPE_VALUE.into(), stored: true,
        }, PackageEntry {
            name: SECTION.into(),
            data: format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{}'><hp:p><hp:run><hp:t>{{{{계약명}}}}</hp:t></hp:run></hp:p></hs:sec>", hwpx_core::text_model::HP_NS).into_bytes(),
            stored: false,
        }] };
        let path = root.join("observed.hwpx");
        let mut job = Job {
            name: "관찰".into(),
            template_path: path.to_str().unwrap().into(),
            ..Job::default()
        };
        job.mapping
            .mappings
            .push(FieldMapping::new("계약명", "src", "text", "", "", None).unwrap());
        let row = |job: &Job| JobRow::from_job(job, super::observe_job(job));
        fs::write(&path, package.to_bytes().unwrap()).unwrap();
        let raw = row(&job);
        assert_eq!(raw.compile_state, Some(CompileState::Raw));
        assert_eq!(raw.compile_badge, "✏ 원문·누름틀 변환 필요");
        assert!(raw.is_runnable());
        let structure = raw.structure.unwrap();
        assert!(structure.readable && structure.template_fields.is_empty());
        compile_document(&mut package, None).unwrap();
        for (value, status, badge) in [
            (None, CompileState::Compiled, "✅ 실행 준비"),
            (
                Some("{{미결}}"),
                CompileState::Partial { remaining: 1 },
                "⚠ 미확인 토큰 1개",
            ),
            (
                Some("정보시스템 구축 사업"),
                CompileState::Compiled,
                "✅ 실행 준비",
            ),
        ] {
            if let Some(value) = value {
                assert!(
                    FieldDocument::new(&mut package, SECTION)
                        .unwrap()
                        .set_field("계약명", value)
                        .unwrap()
                );
            }
            fs::write(&path, package.to_bytes().unwrap()).unwrap();
            let observed = row(&job);
            assert_eq!(observed.compile_state, Some(status));
            assert_eq!(observed.compile_badge, badge);
            assert!(observed.is_runnable() && !observed.template_missing);
            if value == Some("{{미결}}") {
                assert_eq!(observed.health(), (2, badge.into()));
                assert_eq!(LibraryLens::default().counts(&[observed])[3], 1);
            } else {
                assert_eq!(observed.health(), (0, String::new()));
            }
        }
        assert_structure_and_health(&job);
        jobs.save(&mut job, false).unwrap();
        assert_eq!(
            read_library(jobs, datasets).unwrap().rows[0].compile_state,
            Some(CompileState::Compiled)
        );
        let original = package.entries[1].data.clone();
        for (notation, remaining) in [
            ("추가항목: {{추가}}", 2),
            ("{{#항목 특약 특약 사항}}{{/항목}}", 2),
        ] {
            package.entries[1].data = String::from_utf8(original.clone())
                .unwrap()
                .replace(
                    "</hs:sec>",
                    &format!("<hp:p><hp:run><hp:t>{notation}</hp:t></hp:run></hp:p></hs:sec>"),
                )
                .into_bytes();
            fs::write(&path, package.to_bytes().unwrap()).unwrap();
            let refreshed = read_library(jobs, datasets).unwrap();
            assert_eq!(
                refreshed.rows[0].compile_state,
                Some(CompileState::Partial { remaining })
            );
            assert_eq!(
                refreshed.rows[0].compile_badge,
                format!("⚠ 미확인 토큰 {remaining}개")
            );
            assert!(refreshed.rows[0].is_runnable());
        }
        jobs.delete(&job.name).unwrap();
        fs::write(&path, b"not a zip").unwrap();
        let corrupt = row(&job);
        assert_eq!(corrupt.compile_state, None);
        assert_eq!(corrupt.compile_badge, "⚠ 템플릿 오류");
        assert!(!corrupt.is_runnable() && corrupt.structure.is_none());
        assert_eq!(
            corrupt.health_causes(),
            [(3, "템플릿을 읽을 수 없습니다.".into())]
        );
        fs::remove_file(&path).unwrap();
        let missing = row(&job);
        assert!(missing.template_missing && !missing.is_runnable());
        assert_eq!(missing.compile_badge, "❌ 템플릿 없음");
        job.filename_pattern = "계약-{{추정가격}}".into();
        let causes = row(&job).health_causes();
        assert_eq!(
            causes,
            [
                (3, "템플릿 파일을 찾을 수 없습니다.".into()),
                (3, "파일명 패턴의 토큰을 채우지 못합니다.".into())
            ]
        );
        assert_eq!(row(&job).health(), causes[0]);
        job.filename_pattern = Job::default().filename_pattern;
        job.template_path.clear();
        let unlinked = row(&job);
        assert!(!unlinked.template_missing && !unlinked.is_runnable());
        assert_eq!(unlinked.compile_badge, "");
        assert!(unlinked.structure.is_none());
        assert_eq!(unlinked.library_mode(), "hwpx");
        assert_eq!(
            unlinked.health_causes(),
            [(3, "템플릿을 아직 연결하지 않았습니다.".into())]
        );
        job.template_path = root.join("unknown.doc").to_str().unwrap().into();
        assert_eq!(row(&job).library_mode(), "");
        assert_eq!(
            row(&job).health(),
            (3, "템플릿 파일을 찾을 수 없습니다.".into())
        );
        assert_txt_observations(root);
    }

    fn assert_structure_and_health(job: &Job) {
        use hwpx_filler::{home_state::JobRow, mapping::FieldMapping};
        let row = |job: &Job| JobRow::from_job(job, super::observe_job(job));
        let structure = row(job).structure.unwrap();
        assert!(structure.readable);
        assert_eq!(structure.template_fields, ["계약명"]);
        assert!(structure.template_only.is_empty() && structure.mapping_only.is_empty());
        let mut changed = job.clone();
        changed.mapping.mappings =
            vec![FieldMapping::new("없는필드", "src", "text", "", "", None).unwrap()];
        let drifted = row(&changed);
        assert_eq!(
            drifted.health(),
            (2, "템플릿 구조가 확정 매핑과 달라졌습니다.".into())
        );
        let structure = drifted.structure.unwrap();
        assert_eq!(structure.template_fields, ["계약명"]);
        assert_eq!(structure.template_only, ["계약명"]);
        assert_eq!(structure.mapping_only, ["없는필드"]);
        changed.mapping.mappings.clear();
        assert_eq!(
            row(&changed).health(),
            (3, "매핑을 아직 확정하지 않았습니다.".into())
        );
        changed = job.clone();
        for (pattern, expected) in [
            (
                "계약-{{추정가격}}",
                vec![(3, "파일명 패턴의 토큰을 채우지 못합니다.".into())],
            ),
            ("계약-{{계약명}}", vec![]),
        ] {
            changed.filename_pattern = pattern.into();
            assert_eq!(row(&changed).health_causes(), expected);
        }
    }

    fn assert_txt_observations(root: &std::path::Path) {
        use hwpx_filler::{home_state::JobRow, mapping::FieldMapping};
        let path = root.join("기안.txt");
        let mut job = Job {
            template_path: path.to_str().unwrap().into(),
            ..Job::default()
        };
        let row = |job: &Job| JobRow::from_job(job, super::observe_job(job));
        fs::write(&path, "제목 {{공고명}}\r\n담당 {{담당자}} / {{공고명}}\r\n").unwrap();
        assert_eq!(
            row(&job).health_causes(),
            [(2, "매핑을 아직 확정하지 않았습니다.".into())]
        );
        job.mapping.mappings = ["공고명", "옛필드"]
            .map(|name| FieldMapping::new(name, "src", "text", "", "", None).unwrap())
            .into();
        let observed = row(&job);
        assert!(observed.structure_drift());
        assert_eq!(
            observed.health_causes(),
            [(2, "템플릿 구조가 확정 매핑과 달라졌습니다.".into())]
        );
        let structure = observed.structure.unwrap();
        assert!(structure.readable);
        assert_eq!(structure.template_fields, ["공고명", "담당자"]);
        assert_eq!(structure.template_only, ["담당자"]);
        assert_eq!(structure.mapping_only, ["옛필드"]);
        job.mapping.mappings[1] = FieldMapping::new("담당자", "src", "text", "", "", None).unwrap();
        assert_eq!(row(&job).health(), (0, String::new()));
        fs::write(&path, [0xff, 0xfe, 0x80, 0x81]).unwrap();
        for directory in [false, true] {
            if directory {
                fs::remove_file(&path).unwrap();
                fs::create_dir(&path).unwrap();
            }
            let observed = row(&job);
            assert!(!observed.txt_readable && !observed.structure_drift());
            assert_eq!(
                observed.health_causes(),
                [(3, "템플릿을 읽을 수 없습니다.".into())]
            );
            let structure = observed.structure.unwrap();
            assert!(!structure.readable && !structure.read_error.is_empty());
            assert!(structure.template_fields.is_empty());
        }
    }
}
