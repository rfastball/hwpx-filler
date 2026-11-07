//! Template library screen over the shared root, one mixed inventory, and native package views.

use crate::action_registry::validate_dispatch;
use crate::atomic_file::write_bytes_atomic;
use crate::directory_lock::DirectoryLock;
use crate::example_pack::ExamplePack;
use crate::library_observation::read_template;
use crate::template_groups::GroupSettings;
use crate::template_inventory::TemplateInventoryCache;
use crate::template_root::TemplateRoot;
use crate::workspace_switch::{GraphError, PushGate, ScreenController};
use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_filler::authoring::{compile_document, scan_tokens};
use hwpx_filler::home_state::example_entry_state;
use hwpx_filler::hwpx_product_inspection::inspect_slots;
use hwpx_filler::hwpx_structure::scan_structure;
use hwpx_filler::hwpx_structure_ops::{StructureCompileReport, compile_structure};
use hwpx_filler::hwpx_structure_ops::{
    decompile_slot, decompile_structure, remove_slot, rename_slot_label,
};
use hwpx_filler::lint::{DEFAULT_SIMILARITY_THRESHOLD, lint_template};
use hwpx_filler::structure_scan::python_trim;
use hwpx_filler::template_library_state::{template_hwpx_detail, template_txt_detail};
use hwpx_filler::text_render::{python_repr, template_fields};
use serde_json::{Map, Value, json};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

mod review;
mod slots;

#[derive(Default)]
struct TemplateState {
    result_text: String,
    result_level: String,
    detail: Option<Value>,
    inventory: TemplateInventoryCache,
}

type MutationSink = dyn Fn(&str, &Path) -> Result<(), GraphError> + Send + Sync;
type CompileSink = dyn Fn(&Path) -> Result<(), GraphError> + Send + Sync;
type InstallSink = dyn Fn() -> Result<(), GraphError> + Send + Sync;

pub struct TemplateController {
    root: Arc<TemplateRoot>,
    examples: Option<Arc<ExamplePack>>,
    groups: Arc<GroupSettings>,
    push: PushGate,
    on_mutation: Arc<MutationSink>,
    on_compile: Arc<CompileSink>,
    on_install: Arc<InstallSink>,
    state: Mutex<TemplateState>,
    push_order: Mutex<()>,
}
impl TemplateController {
    pub fn new(
        root: Arc<TemplateRoot>,
        examples: Arc<ExamplePack>,
        push: PushGate,
        on_mutation: Arc<MutationSink>,
        on_compile: Arc<CompileSink>,
        on_install: Arc<InstallSink>,
    ) -> Self {
        Self::with_examples(
            root,
            Arc::new(examples.group_settings()),
            Some(examples),
            push,
            on_mutation,
            on_compile,
            on_install,
        )
    }
    /// Live template backend without the retired example installer or an asset fallback.
    pub fn new_live(
        root: Arc<TemplateRoot>,
        groups: Arc<GroupSettings>,
        push: PushGate,
        on_mutation: Arc<MutationSink>,
        on_compile: Arc<CompileSink>,
    ) -> Self {
        Self::with_examples(
            root,
            groups,
            None,
            push,
            on_mutation,
            on_compile,
            Arc::new(|| Ok(())),
        )
    }
    fn with_examples(
        root: Arc<TemplateRoot>,
        groups: Arc<GroupSettings>,
        examples: Option<Arc<ExamplePack>>,
        push: PushGate,
        on_mutation: Arc<MutationSink>,
        on_compile: Arc<CompileSink>,
        on_install: Arc<InstallSink>,
    ) -> Self {
        Self {
            root,
            examples,
            groups,
            push,
            on_mutation,
            on_compile,
            on_install,
            state: Mutex::new(TemplateState {
                result_level: "muted".into(),
                ..TemplateState::default()
            }),
            push_order: Mutex::new(()),
        }
    }
    fn push_current(&self) -> Result<(), GraphError> {
        let _serial = self
            .push_order
            .lock()
            .map_err(|_| "template push order poisoned")?;
        self.push.push("tpl", &self.snapshot()?)?;
        Ok(())
    }
    fn state(&self) -> Result<std::sync::MutexGuard<'_, TemplateState>, GraphError> {
        Ok(self
            .state
            .lock()
            .map_err(|_| "template controller state poisoned")?)
    }
    fn live_row(
        &self,
        path: &Path,
        media: Option<&str>,
    ) -> Result<hwpx_filler::template_library_state::TemplateRow, GraphError> {
        if let Some(row) = self.state()?.inventory.live_row(&self.root, path, media)? {
            return Ok(row);
        }
        self.push_current()?;
        Err(if media.is_some() {
            "현재 라이브러리 목록에 없는 경로는 바꿀 수 없습니다."
        } else {
            "현재 라이브러리 목록에 없는 경로는 검토할 수 없습니다."
        }
        .into())
    }
    pub fn root(&self) -> &Arc<TemplateRoot> {
        &self.root
    }
    pub fn set_templates_root(&self, path: &str) -> Result<Value, GraphError> {
        let trimmed = python_trim(path);
        if trimmed.is_empty() {
            return Err("서식 폴더 경로가 비어 있습니다.".into());
        }
        let target = Path::new(trimmed);
        if target.is_file() {
            return Err(format!("폴더가 아니라 파일입니다: {}", target.display()).into());
        }
        let resolution = self.root.set(trimmed)?;
        self.result(
            format!("서식 폴더를 바꿨습니다: {}", resolution.directory),
            "ok",
        )?;
        self.push_current()?;
        Ok(json!({"ok":true,"directory":resolution.directory}))
    }
    fn result(&self, text: String, level: &str) -> Result<(), GraphError> {
        let mut state = self.state()?;
        state.result_text = text;
        state.result_level = level.into();
        Ok(())
    }
    pub fn snapshot(&self) -> Result<Value, GraphError> {
        let inventory = self.state()?.inventory.current(&self.root)?;
        let mut state = self.state()?;
        if state.detail.as_ref().is_some_and(|detail| {
            let media = detail["media"].as_str().unwrap_or("");
            let path = detail["path"].as_str().unwrap_or("");
            !inventory.contains(media, Path::new(path))
        }) {
            state.detail = None;
        }
        let rows = inventory
            .rows
            .iter()
            .map(|row| {
                let key = Path::new(&row.path)
                    .strip_prefix(&inventory.root)
                    .unwrap_or_else(|_| Path::new(&row.path))
                    .to_string_lossy()
                    .replace('\\', "/");
                row.pool_row(&key)
            })
            .collect::<Vec<_>>();
        for media in ["hwpx", "txt"] {
            let live = inventory
                .rows
                .iter()
                .filter(|row| row.media == media)
                .filter_map(|row| Path::new(&row.path).strip_prefix(&inventory.root).ok())
                .map(|relative| relative.to_string_lossy().replace('\\', "/"))
                .collect::<HashSet<_>>();
            self.groups.reconcile_templates(media, &live)?;
        }
        let count = rows.len();
        let resolution = self.root.resolution();
        let examples = example_entry_state(match &self.examples {
            Some(examples) => examples.installed()?,
            None => false,
        });
        Ok(json!({
            "column":{"rows":rows,"notices":[],"empty_hint":resolution.empty_hint(inventory.root.is_dir()),
                "count_label":if count==0{String::new()}else{format!("{count}개")},
                "result":{"text":state.result_text,"level":state.result_level}},
            "templates_root":resolution.to_dict(),"detail":state.detail,"examples":examples
        }))
    }
    fn review(&self, path: &str) -> Result<Value, GraphError> {
        let target = Path::new(path);
        let row = self.live_row(target, None)?;
        let (detail, package) = if row.media == "txt" {
            (review::txt_review_detail(&row, path, target), None)
        } else {
            review::hwpx_review_detail(&row, path, target)
        };
        let error = detail["error"].as_str().unwrap_or("");
        if !error.is_empty() {
            self.result(format!("검토 {}: {error}", row.name), "danger")?;
        } else if row.media == "txt" {
            self.result(
                format!(
                    "검토 {}: {}",
                    row.name,
                    detail["field_summary"].as_str().unwrap_or("")
                ),
                "ok",
            )?;
        } else {
            let (line, level) =
                review::lint_summary(target, package.as_ref().ok_or("template package missing")?)?;
            self.result(line, level)?;
        }
        self.state()?.detail = Some(detail);
        Ok(json!({"ok":true}))
    }
    fn refresh_detail_if_target(&self, path: &Path) -> Result<(), GraphError> {
        let target = path.to_str().ok_or("template path is not Unicode")?;
        let viewing = self
            .state()?
            .detail
            .as_ref()
            .is_some_and(|detail| detail["path"] == target);
        if viewing {
            let package = read_package(path)?;
            let name = crate::library_observation::template_display_name(&self.root.path(), target);
            let detail = template_hwpx_detail(&name, target, &package).map_err(GraphError::from)?;
            self.state()?.detail = Some(detail);
        }
        Ok(())
    }
    fn compile(&self, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let path = required_path(payload)?;
        self.live_row(&path, Some("hwpx"))?;
        let name = path
            .file_name()
            .ok_or("template filename missing")?
            .to_string_lossy();
        if payload.get("confirm").and_then(Value::as_bool) != Some(true) {
            let package = read_package(&path)?;
            let tokens = scan_tokens(&package)?;
            let scan = scan_structure(&package)?;
            if !scan.diagnostics.is_empty() {
                let reasons = scan
                    .diagnostics
                    .iter()
                    .map(|item| format!("- {}", item.message))
                    .collect::<Vec<_>>()
                    .join("\n");
                self.result(
                    format!(
                        "변환할 수 없습니다 {name}: 구간 표기를 고친 뒤 다시 시도하세요.\n{reasons}"
                    ),
                    "warn",
                )?;
                return Ok(json!({"ok":true,"applied":false,"blocked":true}));
            }
            let compilable = tokens
                .iter()
                .filter(|site| site.compilable)
                .collect::<Vec<_>>();
            let skipped = tokens
                .iter()
                .filter(|site| !site.compilable)
                .collect::<Vec<_>>();
            if compilable.is_empty() && scan.summary.slots == 0 {
                let mut line = format!("변환 {name}: 변환할 토큰과 구간이 없습니다");
                if !skipped.is_empty() {
                    line.push_str(&format!(
                        " (건너뜀 {}개: {})",
                        skipped.len(),
                        skipped
                            .iter()
                            .map(|site| site.name.as_str())
                            .collect::<Vec<_>>()
                            .join(", ")
                    ));
                }
                self.result(line, "warn")?;
                return Ok(json!({"ok":true,"applied":false}));
            }
            let mut lines = vec![
                format!(
                    "항목 {}개 · 선택 {}개 · 누름틀 {}개",
                    scan.summary.slots,
                    scan.summary.options,
                    compilable.len()
                ),
                String::new(),
            ];
            lines.extend(compilable.iter().map(|site| format!("+ {}", site.name)));
            lines.extend(
                skipped
                    .iter()
                    .map(|site| format!("! {}: {}", site.name, site.reason)),
            );
            lines.push(format!(
                "\n지금 변환하면 파일이 제자리에서 바뀝니다: {name}"
            ));
            return Ok(
                json!({"ok":true,"needs_confirm":true,"confirm_text":lines.join("\n"),"path":path}),
            );
        }
        let lock = DirectoryLock::new(&self.root.path())?;
        let outcome = lock.with(|| {
            apply_conversion(&path, |package| {
                compile_structure(package).map_err(Into::into)
            })
        })?;
        let (line, level) = outcome.message(&name);
        self.result(line, level)?;
        if outcome.mutated {
            self.state()?.inventory.clear();
            self.refresh_detail_if_target(&path)?;
            (self.on_mutation)("mutated", &path)?;
            (self.on_compile)(&path)?;
        }
        Ok(
            json!({"ok":true,"applied":true,"refused":!outcome.refusals.is_empty(),"mutated":outcome.mutated}),
        )
    }
    fn slot_action(&self, action: &str, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let path = required_path(payload)?;
        self.live_row(&path, Some("hwpx"))?;
        let name = path
            .file_name()
            .ok_or("template filename missing")?
            .to_string_lossy();
        let slot_id = slots::slot_target(action, payload)?;
        if matches!(
            action,
            "slot_decompile" | "slot_decompile_all" | "slot_remove"
        ) && payload.get("confirm").and_then(Value::as_bool) != Some(true)
        {
            return slots::slot_confirmation(action, &path, &name, &slot_id);
        }
        let label = slots::slot_label(payload);
        let lock = DirectoryLock::new(&self.root.path())?;
        let (count, mutated) =
            lock.with(|| slots::mutate_slots(&path, action, &slot_id, &label))?;
        let told = slots::slot_done_line(action, &label, &slot_id);
        self.result(format!("{told}: {name}"), "ok")?;
        if mutated {
            self.state()?.inventory.clear();
            self.refresh_detail_if_target(&path)?;
            (self.on_mutation)("mutated", &path)?;
        }
        Ok(json!({"ok":true,"slot_count":count}))
    }
    fn install_examples(&self, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let examples = self
            .examples
            .as_ref()
            .ok_or("동봉 예제 자산을 찾지 못했습니다")?;
        if payload.get("confirm").and_then(Value::as_bool) != Some(true) {
            return Ok(json!({"needs_confirm":true,"confirm_text":examples.confirm_text()?}));
        }
        self.state()?.inventory.clear();
        let done = match examples.install() {
            Ok(done) => done,
            Err(error) => {
                let reason = error.to_string();
                self.result(format!("예제를 설치하지 못했습니다: {reason}"), "danger")?;
                return Ok(json!({"ok":false,"error":reason}));
            }
        };
        let mut line = format!(
            "예제 템플릿 {}건을 '예제' 그룹에 넣고 데이터 {}건을 고정했습니다.",
            done.templates, done.pool_keys
        );
        if !done.renamed.is_empty() {
            line.push_str(&format!(
                " 같은 이름의 파일이 있어 {} 로 넣었습니다.",
                done.renamed.join(", ")
            ));
        }
        self.result(line, "ok")?;
        (self.on_install)()?;
        Ok(json!({"ok":true,"installed":done.templates+done.data_files}))
    }
    fn remove_examples(&self, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let examples = self.examples.as_ref().ok_or("설치된 예제가 없습니다.")?;
        let plan = match examples.removal_plan() {
            Ok(Some(plan)) => plan,
            Ok(None) => {
                let reason = "설치된 예제가 없습니다.";
                self.result(reason.into(), "danger")?;
                return Ok(json!({"ok":false,"error":reason}));
            }
            Err(error) => {
                let reason = error.to_string();
                self.result(format!("예제를 제거하지 못했습니다: {reason}"), "danger")?;
                return Ok(json!({"ok":false,"error":reason}));
            }
        };
        if payload.get("confirm").and_then(Value::as_bool) != Some(true) {
            return Ok(
                json!({"needs_confirm":true,"confirm_text":ExamplePack::remove_confirm_text(&plan)}),
            );
        }
        self.state()?.inventory.clear();
        let done = match examples.remove() {
            Ok(done) => done,
            Err(error) => {
                let reason = error.to_string();
                self.result(format!("예제를 제거하지 못했습니다: {reason}"), "danger")?;
                return Ok(json!({"ok":false,"error":reason}));
            }
        };
        for path in &done.removed {
            (self.on_mutation)("deleted", path)?;
        }
        let mut line = format!(
            "예제 템플릿 {}건과 데이터 {}건을 걷고 고정 {}건을 해제했습니다. 되돌리려면 다시 설치하세요.",
            done.removed.len(),
            done.data_removed,
            done.unpinned
        );
        if !done.missing.is_empty() {
            line.push_str(&format!(" 이미 없던 항목: {}.", done.missing.join(", ")));
        }
        if !done.kept_pins.is_empty() {
            line.push_str(&format!(
                " 다른 데이터로 다시 연결된 고정은 남겼습니다: {}.",
                done.kept_pins.join(", ")
            ));
        }
        self.result(line, "ok")?;
        Ok(json!({"ok":true,"removed":done.removed.len()+done.data_removed}))
    }
    fn perform(&self, action: &str, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        match action {
            "refresh" => {
                self.state()?.inventory.clear();
                self.result(String::new(), "muted")?;
                Ok(Value::Null)
            }
            "review" => self.review(
                required_path(payload)?
                    .to_str()
                    .ok_or("template path is not Unicode")?,
            ),
            "compile" => self.compile(payload),
            "slot_rename" | "slot_decompile" | "slot_decompile_all" | "slot_remove" => {
                self.slot_action(action, payload)
            }
            "install_examples" => self.install_examples(payload),
            "remove_examples" => self.remove_examples(payload),
            _ => Err(format!("알 수 없는 tpl 액션: {}", python_repr(&json!(action))).into()),
        }
    }
}
impl ScreenController for TemplateController {
    fn initial(&self) -> Result<Value, GraphError> {
        self.snapshot()
    }
    fn dispatch(&self, action: &str, payload: &Value) -> Result<Value, GraphError> {
        let object = validate_dispatch("tpl", action, payload)?;
        let result = self.perform(action, object)?;
        self.push_current()?;
        Ok(result)
    }
    fn close_guard_reason(&self) -> Result<Option<String>, GraphError> {
        Ok(None)
    }
}
fn required_path(payload: &Map<String, Value>) -> Result<PathBuf, GraphError> {
    Ok(PathBuf::from(
        payload
            .get("path")
            .and_then(Value::as_str)
            .ok_or("template path must be a string")?,
    ))
}
#[derive(Default)]
struct ConversionOutcome {
    fields: usize,
    slots: usize,
    options: usize,
    refusals: Vec<String>,
    errors: Vec<String>,
    mutated: bool,
}

impl ConversionOutcome {
    fn message(&self, name: &str) -> (String, &'static str) {
        let Self {
            fields,
            slots,
            options,
            refusals,
            errors,
            mutated,
        } = self;
        let mut parts = vec![format!("누름틀 {fields}개")];
        if *slots > 0 {
            parts.push(format!("항목 {slots}개"));
        }
        if *options > 0 {
            parts.push(format!("선택 {options}개"));
        }
        if !errors.is_empty() {
            let head = if *mutated {
                format!("구간 변환이 중단됐습니다 {name}: 누름틀 {fields}개는 저장됐습니다.")
            } else {
                format!("구간 변환이 중단됐습니다 {name}: 파일은 바뀌지 않았습니다.")
            };
            (
                format!(
                    "{head}\n{}",
                    errors
                        .iter()
                        .map(|item| format!("- {item}"))
                        .collect::<Vec<_>>()
                        .join("\n")
                ),
                "danger",
            )
        } else if !refusals.is_empty() {
            (
                format!(
                    "변환 완료 {name}: {}\n구간 변환은 하지 못했습니다:\n{}",
                    parts.join(" · "),
                    refusals
                        .iter()
                        .map(|item| format!("- {item}"))
                        .collect::<Vec<_>>()
                        .join("\n")
                ),
                "warn",
            )
        } else {
            (format!("변환 완료 {name}: {}", parts.join(" · ")), "ok")
        }
    }
}

fn apply_conversion(
    path: &Path,
    compile_ranges: impl FnOnce(&mut HwpxPackage) -> Result<StructureCompileReport, GraphError>,
) -> Result<ConversionOutcome, GraphError> {
    let mut package = read_package(path)?;
    let fields = compile_document(&mut package, None)?;
    if fields.modified {
        write_bytes_atomic(path, &package.to_bytes()?)?;
    }
    let mut outcome = ConversionOutcome {
        fields: fields.compiled.len(),
        mutated: fields.modified,
        ..Default::default()
    };
    // Field conversion is committed before ranges; a later failure must retain that fact.
    let structure = (|| -> Result<_, GraphError> {
        let mut package = read_package(path)?;
        let report = compile_ranges(&mut package)?;
        if report.modified {
            write_bytes_atomic(path, &package.to_bytes()?)?;
        }
        Ok(report)
    })();
    match structure {
        Ok(report) => {
            outcome.mutated |= report.modified;
            outcome.slots = report.slots.len();
            outcome.options = report.options;
            outcome.refusals = report
                .refusal
                .unwrap_or_default()
                .into_iter()
                .map(|item| item.message)
                .collect();
        }
        Err(error) => outcome
            .errors
            .push(format!("구간 변환 중 오류가 났습니다: {error}")),
    }
    Ok(outcome)
}

fn read_package(path: &Path) -> Result<HwpxPackage, GraphError> {
    Ok(HwpxPackage::from_bytes(
        &read_template(path)?,
        PackageLimits::default(),
    )?)
}
fn failed_detail(
    row: &hwpx_filler::template_library_state::TemplateRow,
    path: &str,
    error: &str,
) -> Value {
    json!({"path":path,"name":row.name,"media":"hwpx","state":"","badge_label":"오류","badge_level":"danger",
        "field_count":0,"field_summary":format!("읽기 실패: {error}"),"fields":[],"actions":[],"diagnostics":[],"slots":null,"error":error})
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{GroupSettings, TemplateController};
    use crate::dataset_registry::DatasetPoolRegistry;
    use crate::example_pack::ExamplePack;
    use crate::locations::Locations;
    use crate::shell_settings::ShellSettings;
    use crate::template_files::TemplateFileStore;
    use crate::template_root::TemplateRoot;
    use crate::workspace_switch::{WorkspaceGraph, WorkspaceSwitch};
    use serde_json::json;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::mpsc;
    use std::sync::{Arc, Mutex};
    use std::time::{Duration, Instant};

    fn assert_column_view(
        controller: &dyn crate::workspace_switch::ScreenController,
        directory: &Path,
    ) {
        let raw = conversion_package(&["{{계약명}}"]);
        fs::write(directory.join("raw.hwpx"), raw.to_bytes().unwrap()).unwrap();
        let mut compiled = raw.clone();
        hwpx_filler::authoring::compile_document(&mut compiled, None).unwrap();
        fs::write(
            directory.join("compiled.hwpx"),
            compiled.to_bytes().unwrap(),
        )
        .unwrap();
        let mut marker = raw;
        marker.entries[1].data = br#"<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p><hp:run><hp:ctrl><hp:fieldBegin name="title"/></hp:ctrl></hp:run><hp:run><hp:t>V<hp:markpenBegin/><hp:markpenEnd/></hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p></hs:sec>"#.to_vec();
        fs::write(directory.join("marker.hwpx"), marker.to_bytes().unwrap()).unwrap();
        fs::write(directory.join("column.txt"), "{{공고명}}").unwrap();
        let trash = directory.join(".trash");
        fs::create_dir_all(&trash).unwrap();
        fs::write(trash.join("old.hwpx"), compiled.to_bytes().unwrap()).unwrap();
        fs::write(trash.join("old.txt"), "{{옛것}}").unwrap();
        controller.dispatch("refresh", &json!({})).unwrap();
        let view = controller.initial().unwrap();
        let rows = view["column"]["rows"].as_array().unwrap();
        assert!(
            rows.iter()
                .all(|row| !row["name"].as_str().unwrap().contains(".trash")
                    && row.get("group").is_none())
        );
        let find = |name: &str| rows.iter().find(|row| row["name"] == name).unwrap();
        let raw = find("raw");
        assert_eq!(raw["selectable"], false);
        assert_eq!(raw["reason"], "누름틀·구간 변환을 해야 고를 수 있습니다.");
        assert_eq!(raw["actions"][0]["key"], "compile");
        let compiled = find("compiled");
        assert_eq!(compiled["selectable"], true);
        assert_eq!(compiled["reason"], "");
        assert_eq!(compiled["warns"], json!([]));
        let txt = find("column");
        assert_eq!(txt["badge_label"], "TXT");
        assert_eq!(txt["badge_level"], "muted");
        assert_eq!(txt["sub"], "필드 1개");
        assert_eq!(txt["icon"], "txt");
        assert_eq!(txt["selectable"], true);
        assert_eq!(txt["actions"], json!([]));
        assert_eq!(txt["warns"], json!([]));
        let warns = find("marker")["warns"].as_array().unwrap();
        assert_eq!(warns.len(), 1);
        assert!(warns[0].as_str().unwrap().contains("markpenBegin"));
        let first_txt = rows.iter().position(|row| row["icon"] == "txt").unwrap();
        assert!(rows[..first_txt].iter().all(|row| row["icon"] == "hwpx"));
        assert!(rows[first_txt..].iter().all(|row| row["icon"] == "txt"));
    }

    fn assert_root_switching(
        native: &TemplateController,
        sandbox: &Path,
        template_dir: &Path,
        pushed: &Mutex<Vec<serde_json::Value>>,
    ) {
        let root = native.root();
        let path = template_dir.join("canonical.hwpx");
        let previous = root.path();
        let push_count = pushed.lock().unwrap().len();
        assert!(native.set_templates_root("   ").is_err());
        assert!(native.set_templates_root(path.to_str().unwrap()).is_err());
        assert_eq!(root.path(), previous);
        assert_eq!(pushed.lock().unwrap().len(), push_count);
        let switched = sandbox.join("다른서식");
        fs::create_dir_all(switched.join("하위")).unwrap();
        fs::write(
            switched.join("하위/새서식.hwpx"),
            conversion_package(&["{{건명}}"]).to_bytes().unwrap(),
        )
        .unwrap();
        fs::write(switched.join("하위/새기안.txt"), "{{건명}}").unwrap();
        assert_eq!(
            native
                .set_templates_root(switched.to_str().unwrap())
                .unwrap(),
            json!({"ok":true,"directory":switched})
        );
        assert_eq!(pushed.lock().unwrap().len(), push_count + 1);
        let switched_view = pushed.lock().unwrap().last().unwrap().clone();
        assert_eq!(
            switched_view["column"]["rows"]
                .as_array()
                .unwrap()
                .iter()
                .map(|row| row["name"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["하위/새서식", "하위/새기안"]
        );
        assert_eq!(
            switched_view["templates_root"]["source_label"],
            "설정한 폴더"
        );
        let persisted: serde_json::Value =
            serde_json::from_slice(&fs::read(sandbox.join("settings.json")).unwrap()).unwrap();
        assert_eq!(persisted["templates_root"], switched.to_str().unwrap());
        let missing = sandbox.join("빈폴더");
        native
            .set_templates_root(missing.to_str().unwrap())
            .unwrap();
        let view = native.snapshot().unwrap();
        assert_eq!(view["column"]["count_label"], "");
        assert_eq!(view["column"]["rows"], json!([]));
        assert!(view["detail"].is_null());
        let hint = view["column"]["empty_hint"].as_str().unwrap();
        assert!(hint.contains("폴더가 없습니다") && hint.contains(missing.to_str().unwrap()));
        fs::create_dir_all(&missing).unwrap();
        assert!(
            native.snapshot().unwrap()["column"]["empty_hint"]
                .as_str()
                .unwrap()
                .contains("템플릿이 없습니다")
        );
        fs::write(missing.join("new.txt"), "{{필드}}").unwrap();
        let view = native.snapshot().unwrap();
        assert_eq!(view["column"]["count_label"], "1개");
        assert_eq!(view["column"]["rows"].as_array().unwrap().len(), 1);
        root.set(template_dir.to_str().unwrap()).unwrap();
    }

    fn assert_review_reads_and_membership(
        controller: &dyn crate::workspace_switch::ScreenController,
        directory: &Path,
        pushed: &Mutex<Vec<serde_json::Value>>,
    ) {
        use crate::library_observation::observe_template_reads;
        let path = directory.join("검토.hwpx");
        let mut package = conversion_package(&["계약명: {{계약명}} / 작성일자: {{작성일자}}"]);
        hwpx_filler::authoring::compile_document(&mut package, None).unwrap();
        fs::write(&path, package.to_bytes().unwrap()).unwrap();
        let broken = directory.join("깨진.hwpx");
        fs::write(&broken, b"not a zip").unwrap();
        let broken_txt = directory.join("깨진.txt");
        fs::write(&broken_txt, [0xff, 0xfe]).unwrap();
        controller.dispatch("refresh", &json!({})).unwrap();
        let (answer, reads) = observe_template_reads(|| {
            controller
                .dispatch("review", &json!({"path":path}))
                .unwrap()
        });
        assert_eq!(answer, json!({"ok":true}));
        assert_eq!(
            reads,
            std::slice::from_ref(&path),
            "warm review must read only its target once"
        );
        let view = controller.initial().unwrap();
        let detail = &view["detail"];
        assert_eq!(detail["name"], "검토");
        assert_eq!(detail["state"], "compiled");
        assert_eq!(
            detail["fields"],
            json!([
                {"name":"계약명","type_hint":"text"}, {"name":"작성일자","type_hint":"date"}
            ])
        );
        assert_eq!(detail["field_summary"], "필드 2개");
        assert_eq!(detail["actions"], json!([]));
        assert_eq!(detail["diagnostics"], json!([]));
        assert_eq!(detail["error"], "");
        assert_eq!(detail["slots"]["rows"], json!([]));
        assert_eq!(view["column"]["result"]["level"], "ok");
        for (text, compile, phrase) in [
            ("{{계약명}}", false, "미치환 토큰"),
            ("{{계약명}} / {{계약 명}}", true, "공백/표기만 다른 필드명"),
        ] {
            let mut document = conversion_package(&[text]);
            if compile {
                hwpx_filler::authoring::compile_document(&mut document, None).unwrap();
            }
            fs::write(&path, document.to_bytes().unwrap()).unwrap();
            let (_, reads) = observe_template_reads(|| {
                controller
                    .dispatch("review", &json!({"path":path}))
                    .unwrap()
            });
            assert_eq!(reads.iter().filter(|read| *read == &path).count(), 2);
            let result = controller.initial().unwrap()["column"]["result"].clone();
            assert_eq!(result["level"], "warn");
            let text = result["text"].as_str().unwrap();
            assert!(text.contains("검토.hwpx") && text.contains(phrase) && text.contains("[경고]"));
            assert!(!text.contains("[warning]"));
        }
        for target in [&broken, &broken_txt] {
            let (_, reads) = observe_template_reads(|| {
                controller
                    .dispatch("review", &json!({"path":target}))
                    .unwrap()
            });
            assert_eq!(reads, std::slice::from_ref(target));
            let view = controller.initial().unwrap();
            let detail = &view["detail"];
            assert!(!detail["error"].as_str().unwrap().is_empty());
            assert_eq!(detail["fields"], json!([]));
            assert_eq!(detail["slots"], serde_json::Value::Null);
            assert_eq!(detail["actions"], json!([]));
            assert!(
                detail["field_summary"]
                    .as_str()
                    .unwrap()
                    .starts_with("읽기 실패: ")
            );
            assert_eq!(view["column"]["result"]["level"], "danger");
        }
        let note = directory.join("note.txt");
        let (_, reads) = observe_template_reads(|| {
            controller
                .dispatch("review", &json!({"path":note}))
                .unwrap()
        });
        assert_eq!(reads, std::slice::from_ref(&note));
        let detail = controller.initial().unwrap()["detail"].clone();
        assert_eq!(detail["media"], "txt");
        assert_eq!(
            detail["fields"],
            json!([{"name":"이름","type_hint":"text"}])
        );
        assert_eq!(detail["state"], "");
        assert_eq!(detail["slots"], serde_json::Value::Null);
        assert_eq!(detail["actions"], json!([]));

        fs::write(&note, "{{이름}} {{새 필드}}").unwrap();
        let view = controller.initial().unwrap();
        let row = view["column"]["rows"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["path"] == note.to_str().unwrap())
            .unwrap();
        assert_eq!(
            row["sub"], "필드 2개",
            "external TXT edits must invalidate the presented row"
        );

        let fresh = directory.join("새로온.hwpx");
        fs::write(&fresh, package.to_bytes().unwrap()).unwrap();
        controller
            .dispatch("review", &json!({"path":fresh}))
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["detail"]["path"],
            fresh.to_str().unwrap()
        );
        let outside = directory.parent().unwrap().join("foreign.hwpx");
        fs::write(&outside, package.to_bytes().unwrap()).unwrap();
        assert!(
            controller
                .dispatch("review", &json!({"path":outside}))
                .is_err()
        );
        fs::remove_file(&fresh).unwrap();
        let before = pushed.lock().unwrap().len();
        assert!(
            controller
                .dispatch("review", &json!({"path":fresh}))
                .is_err()
        );
        let pushes = pushed.lock().unwrap();
        assert!(
            pushes.len() > before,
            "rejection must publish the refreshed list"
        );
        let last = pushes.last().unwrap();
        assert!(last["detail"].is_null());
        assert!(
            last["column"]["rows"]
                .as_array()
                .unwrap()
                .iter()
                .all(|row| row["path"] != fresh.to_str().unwrap())
        );
        drop(pushes);

        // An edit elsewhere cannot change which detail is open; explicit refresh replaces cached rows.
        controller
            .dispatch("review", &json!({"path":note}))
            .unwrap();
        fs::write(
            &path,
            conversion_package(&["{{새필드}} "]).to_bytes().unwrap(),
        )
        .unwrap();
        controller
            .dispatch("compile", &json!({"path":path,"confirm":true}))
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["detail"]["path"],
            note.to_str().unwrap()
        );
        fs::write(&path, b"broken externally").unwrap();
        controller.dispatch("refresh", &json!({})).unwrap();
        let rows = controller.initial().unwrap()["column"]["rows"].clone();
        assert_eq!(
            rows.as_array()
                .unwrap()
                .iter()
                .find(|row| row["path"] == path.to_str().unwrap())
                .unwrap()["badge_label"],
            "오류"
        );
    }

    fn conversion_package(lines: &[&str]) -> hwpx_core::package::HwpxPackage {
        use hwpx_core::package::{HwpxPackage, MIMETYPE_NAME, MIMETYPE_VALUE, PackageEntry};
        let body = lines
            .iter()
            .map(|line| {
                format!("<hp:p><hp:run charPrIDRef=\"0\"><hp:t>{line}</hp:t></hp:run></hp:p>")
            })
            .collect::<String>();
        HwpxPackage { entries: vec![
            PackageEntry { name: MIMETYPE_NAME.into(), data: MIMETYPE_VALUE.into(), stored: true },
            PackageEntry { name: "Contents/section0.xml".into(), data: format!(r#"<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">{body}</hs:sec>"#).into_bytes(), stored: false },
        ] }
    }

    fn assert_structure_conversion(
        controller: &dyn crate::workspace_switch::ScreenController,
        directory: &Path,
        changes: &Mutex<Vec<(String, PathBuf)>>,
    ) {
        use hwpx_filler::schema::extract_schema;
        let path = directory.join("구간.hwpx");
        let bytes = conversion_package(&[
            "{{#항목 특약 특약 사항}}",
            "{{#선택 지체상금 지체상금 조항}}",
            "지체상금은 {{지체상금률}} 로 한다.",
            "{{/선택}}",
            "{{/항목}}",
            "발주자: {{수요기관}}",
        ])
        .to_bytes()
        .unwrap();
        fs::write(&path, &bytes).unwrap();
        let before_events = changes.lock().unwrap().len();
        let preview = controller
            .dispatch("compile", &json!({"path":path}))
            .unwrap();
        assert_eq!(preview["needs_confirm"], true);
        assert!(
            preview["confirm_text"]
                .as_str()
                .unwrap()
                .starts_with("항목 1개 · 선택 1개 · 누름틀 2개")
        );
        assert_eq!(fs::read(&path).unwrap(), bytes);
        assert_eq!(changes.lock().unwrap().len(), before_events);
        controller
            .dispatch("review", &json!({"path":path}))
            .unwrap();
        let applied = controller
            .dispatch("compile", &json!({"path":path,"confirm":true}))
            .unwrap();
        assert_eq!(
            applied,
            json!({"ok":true,"applied":true,"refused":false,"mutated":true})
        );
        let package = super::read_package(&path).unwrap();
        assert_eq!(
            extract_schema(&package).unwrap().field_names(),
            ["지체상금률", "수요기관"]
        );
        assert_eq!(changes.lock().unwrap().len(), before_events + 1);
        let view = controller.initial().unwrap();
        assert_eq!(view["column"]["result"]["level"], "ok");
        assert!(
            view["column"]["result"]["text"]
                .as_str()
                .unwrap()
                .contains("누름틀 2개 · 항목 1개 · 선택 1개")
        );
        assert_eq!(view["detail"]["slots"]["summary"], "항목 1개 · 선택 1개");
        assert_eq!(
            view["detail"]["slots"]["rows"],
            json!([
                {"id":"특약","label":"특약 사항","option_count":1,"options":["지체상금 조항"]}
            ])
        );

        assert_slot_transitions(controller, &path, changes);
        let before_events = changes.lock().unwrap().len();

        // A fresh malformed declaration blocks preview; explicit apply still reports its refusal.
        fs::write(
            &path,
            conversion_package(&["{{#항목 특약}}", "본문 {{값}}"])
                .to_bytes()
                .unwrap(),
        )
        .unwrap();
        let before = fs::read(&path).unwrap();
        let blocked = controller
            .dispatch("compile", &json!({"path":path}))
            .unwrap();
        assert_eq!(blocked, json!({"ok":true,"applied":false,"blocked":true}));
        let result = controller.initial().unwrap()["column"]["result"].clone();
        assert_eq!(result["level"], "warn");
        let text = result["text"].as_str().unwrap();
        assert!(text.contains("변환할 수 없습니다 구간.hwpx") && text.contains("닫는 마커"));
        assert_eq!(fs::read(&path).unwrap(), before);
        assert_eq!(changes.lock().unwrap().len(), before_events);
        let refused = controller
            .dispatch("compile", &json!({"path":path,"confirm":true}))
            .unwrap();
        assert_eq!(refused["refused"], true);
        assert_eq!(refused["mutated"], true);
        let result = controller.initial().unwrap()["column"]["result"].clone();
        assert_eq!(result["level"], "warn");
        let text = result["text"].as_str().unwrap();
        assert!(
            text.contains("누름틀 1개")
                && text.contains("구간 변환은 하지 못했습니다")
                && text.contains("닫는 마커")
        );
        assert_eq!(changes.lock().unwrap().len(), before_events + 1);

        fs::write(
            &path,
            conversion_package(&["바꿀 것이 없는 본문입니다."])
                .to_bytes()
                .unwrap(),
        )
        .unwrap();
        let before = fs::read(&path).unwrap();
        let noop = controller
            .dispatch("compile", &json!({"path":path,"confirm":true}))
            .unwrap();
        assert_eq!(noop["mutated"], false);
        assert_eq!(noop["refused"], false);
        let preview = controller
            .dispatch("compile", &json!({"path":path}))
            .unwrap();
        assert_eq!(preview, json!({"ok":true,"applied":false}));
        let result = controller.initial().unwrap()["column"]["result"].clone();
        assert_eq!(result["level"], "warn");
        assert!(
            result["text"]
                .as_str()
                .unwrap()
                .contains("변환할 토큰과 구간이 없습니다")
        );
        assert_eq!(fs::read(&path).unwrap(), before);
        assert_eq!(changes.lock().unwrap().len(), before_events + 1);
        assert_conversion_failure_retains_commit(&path);
        assert_serialization_failure_preserves_file(&path);
    }

    fn assert_slot_transitions(
        controller: &dyn crate::workspace_switch::ScreenController,
        path: &Path,
        changes: &Mutex<Vec<(String, PathBuf)>>,
    ) {
        let before_events = changes.lock().unwrap().len();
        let before = fs::read(path).unwrap();
        let outside = path
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("outside.hwpx");
        fs::write(&outside, &before).unwrap();
        for action in [
            "slot_rename",
            "slot_decompile",
            "slot_remove",
            "slot_decompile_all",
        ] {
            for confirm in [false, true] {
                let mut payload = json!({"path":outside});
                if action != "slot_decompile_all" {
                    payload["slot_id"] = json!("특약");
                }
                if action == "slot_rename" {
                    payload["label"] = json!("변경 금지");
                } else {
                    payload["confirm"] = json!(confirm);
                }
                assert!(controller.dispatch(action, &payload).is_err());
                assert_eq!(fs::read(&outside).unwrap(), before);
                assert_eq!(changes.lock().unwrap().len(), before_events);
            }
        }
        assert!(
            controller
                .dispatch(
                    "slot_rename",
                    &json!({"path":path,"slot_id":"  ","label":"x"})
                )
                .unwrap_err()
                .to_string()
                .contains("항목 id 가 비어")
        );
        for (action, phrase) in [
            ("slot_decompile", "구간 표기로 되돌립니다"),
            ("slot_remove", "사라지는 것:"),
            (
                "slot_decompile_all",
                "항목 1개를 전부 구간 표기로 되돌립니다",
            ),
        ] {
            let mut payload = json!({"path":path});
            if action != "slot_decompile_all" {
                payload["slot_id"] = json!("특약");
            }
            let preview = controller.dispatch(action, &payload).unwrap();
            assert_eq!(preview["needs_confirm"], true);
            let text = preview["confirm_text"].as_str().unwrap();
            assert!(text.contains(phrase) && text.contains("구간.hwpx"));
            assert!(!text.contains('—') && !text.contains('「'));
            assert!(text.contains(if action == "slot_remove" {
                "선택 1개"
            } else {
                "문서를 만들 수 없습니다"
            }));
            assert_eq!(fs::read(path).unwrap(), before);
            assert_eq!(changes.lock().unwrap().len(), before_events);
        }
        controller
            .dispatch(
                "slot_rename",
                &json!({"path":path,"slot_id":"특약","label":"새 이름"}),
            )
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["detail"]["slots"]["rows"][0]["label"],
            "새 이름"
        );
        controller
            .dispatch(
                "slot_rename",
                &json!({"path":path,"slot_id":"특약","label":"  "}),
            )
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["detail"]["slots"]["rows"][0]["label"],
            ""
        );
        controller
            .dispatch(
                "slot_rename",
                &json!({"path":path,"slot_id":"특약","label":"새 이름"}),
            )
            .unwrap();
        for action in ["slot_decompile", "slot_decompile_all"] {
            let mut payload = json!({"path":path,"confirm":true});
            if action != "slot_decompile_all" {
                payload["slot_id"] = json!("특약");
            }
            let response = controller.dispatch(action, &payload).unwrap();
            assert_eq!(response["slot_count"], 0);
            assert_eq!(
                controller.initial().unwrap()["detail"]["slots"]["rows"],
                json!([])
            );
            let package = super::read_package(path).unwrap();
            assert_eq!(
                hwpx_filler::hwpx_structure::scan_structure(&package)
                    .unwrap()
                    .summary
                    .slots,
                1
            );
            controller
                .dispatch("compile", &json!({"path":path,"confirm":true}))
                .unwrap();
            assert_eq!(
                controller.initial().unwrap()["detail"]["slots"]["rows"][0]["label"],
                "새 이름"
            );
        }
        let response = controller
            .dispatch(
                "slot_remove",
                &json!({"path":path,"slot_id":"특약","confirm":true}),
            )
            .unwrap();
        assert_eq!(response["slot_count"], 0);
        assert_eq!(
            controller.initial().unwrap()["detail"]["slots"]["rows"],
            json!([])
        );
        let package = super::read_package(path).unwrap();
        assert_eq!(
            hwpx_filler::hwpx_structure::scan_structure(&package)
                .unwrap()
                .summary
                .slots,
            0
        );
        assert_eq!(
            hwpx_filler::schema::extract_schema(&package)
                .unwrap()
                .field_names(),
            ["수요기관"]
        );
        assert_eq!(changes.lock().unwrap().len(), before_events + 8);
        let before = (
            fs::read(path).unwrap(),
            fs::metadata(path).unwrap().modified().unwrap(),
        );
        controller
            .dispatch("slot_decompile_all", &json!({"path":path,"confirm":true}))
            .unwrap();
        assert_eq!(
            (
                fs::read(path).unwrap(),
                fs::metadata(path).unwrap().modified().unwrap()
            ),
            before
        );
        assert_eq!(changes.lock().unwrap().len(), before_events + 8);
        assert!(
            changes.lock().unwrap()[before_events..]
                .iter()
                .all(|(kind, changed)| kind == "mutated" && changed == path)
        );
        assert_decompile_all_slots(controller, path);
    }

    fn assert_decompile_all_slots(
        controller: &dyn crate::workspace_switch::ScreenController,
        path: &Path,
    ) {
        let package = conversion_package(&[
            "{{#항목 특약 특약 사항}}",
            "{{#선택 지체상금 지체상금 조항}}",
            "지체상금은 {{지체상금률}} 로 한다.",
            "{{/선택}}",
            "{{/항목}}",
            "{{#항목 부기 부기 사항}}",
            "부기: {{부기문}}",
            "{{/항목}}",
            "발주자: {{수요기관}}",
        ]);
        fs::write(path, package.to_bytes().unwrap()).unwrap();
        controller
            .dispatch("compile", &json!({"path":path,"confirm":true}))
            .unwrap();
        let detail = controller.initial().unwrap()["detail"].clone();
        assert_eq!(
            detail["slots"]["rows"]
                .as_array()
                .unwrap()
                .iter()
                .map(|row| row["id"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["특약", "부기"]
        );
        let before = fs::read(path).unwrap();
        let ask = controller
            .dispatch("slot_decompile_all", &json!({"path":path}))
            .unwrap();
        assert!(ask.get("slot_id").is_none());
        assert_eq!(ask["kind"], "slot_decompile_all");
        assert!(
            ask["confirm_text"]
                .as_str()
                .unwrap()
                .contains("항목 2개를 전부")
        );
        assert_eq!(fs::read(path).unwrap(), before);
        let done = controller
            .dispatch("slot_decompile_all", &json!({"path":path,"confirm":true}))
            .unwrap();
        assert_eq!(done, json!({"ok":true,"slot_count":0}));
        let snapshot = controller.initial().unwrap();
        assert_eq!(snapshot["detail"]["slots"]["rows"], json!([]));
        assert_eq!(snapshot["detail"]["state"], "partial");
        assert_eq!(
            hwpx_filler::hwpx_structure::scan_structure(&super::read_package(path).unwrap())
                .unwrap()
                .summary
                .slots,
            2
        );
    }

    fn assert_conversion_failure_retains_commit(path: &Path) {
        use hwpx_filler::schema::extract_schema;
        fs::write(
            path,
            conversion_package(&["값: {{값}}"]).to_bytes().unwrap(),
        )
        .unwrap();
        for expected_mutation in [true, false] {
            let before = (
                fs::read(path).unwrap(),
                fs::metadata(path).unwrap().modified().unwrap(),
            );
            let outcome = super::apply_conversion(path, |package| {
                assert_eq!(extract_schema(package).unwrap().field_names(), ["값"]);
                assert_eq!(
                    extract_schema(&super::read_package(path).unwrap())
                        .unwrap()
                        .field_names(),
                    ["값"]
                );
                Err("커널이 멈췄습니다".into())
            })
            .unwrap();
            assert_eq!(outcome.fields, usize::from(expected_mutation));
            assert_eq!(outcome.mutated, expected_mutation);
            assert_eq!(outcome.slots, 0);
            assert!(outcome.refusals.is_empty());
            let (line, level) = outcome.message("구간.hwpx");
            assert_eq!(level, "danger");
            assert!(
                line.contains("구간 변환이 중단됐습니다 구간.hwpx")
                    && line.contains("커널이 멈췄습니다")
            );
            assert!(line.contains(if expected_mutation {
                "누름틀 1개는 저장됐습니다"
            } else {
                "파일은 바뀌지 않았습니다"
            }));
            let after = (
                fs::read(path).unwrap(),
                fs::metadata(path).unwrap().modified().unwrap(),
            );
            if expected_mutation {
                assert_ne!(after.0, before.0);
            } else {
                assert_eq!(after, before);
            }
        }
    }

    fn assert_serialization_failure_preserves_file(path: &Path) {
        let before = fs::read(path).unwrap();
        let parent = path.parent().unwrap();
        let names = || {
            let mut paths = fs::read_dir(parent)
                .unwrap()
                .map(|item| item.unwrap().path())
                .collect::<Vec<_>>();
            paths.sort();
            paths
        };
        let before_names = names();
        let outcome = super::apply_conversion(path, |package| {
            package.entries.retain(|entry| entry.name != "mimetype");
            Ok(hwpx_filler::hwpx_structure_ops::StructureCompileReport {
                modified: true,
                slots: Vec::new(),
                options: 0,
                refusal: None,
            })
        })
        .unwrap();
        assert!(!outcome.mutated);
        assert_eq!(outcome.errors.len(), 1);
        assert!(outcome.errors[0].contains("missing mimetype"));
        assert_eq!(fs::read(path).unwrap(), before);
        assert_eq!(names(), before_names);
    }

    fn assert_compile_preserves_preview_and_noop(
        controller: &dyn crate::workspace_switch::ScreenController,
        directory: &Path,
        changes: &Mutex<Vec<(String, PathBuf)>>,
    ) {
        use hwpx_filler::home_state::{CompileState, compile_status};
        let mut package = conversion_package(&["{{title}}"]);
        let path = directory.join("convert.hwpx");
        let before = package.to_bytes().unwrap();
        fs::write(&path, &before).unwrap();
        let before_events = changes.lock().unwrap().len();
        let preview = controller
            .dispatch("compile", &json!({"path":path}))
            .unwrap();
        assert_eq!(preview["needs_confirm"], true);
        assert!(
            preview["confirm_text"]
                .as_str()
                .unwrap()
                .contains("누름틀 1개")
        );
        assert_eq!(fs::read(&path).unwrap(), before);
        assert_eq!(changes.lock().unwrap().len(), before_events);
        assert_eq!(
            compile_status(&super::read_package(&path).unwrap()).unwrap(),
            CompileState::Raw
        );
        controller
            .dispatch("review", &json!({"path":path}))
            .unwrap();
        let applied = controller
            .dispatch("compile", &json!({"path":path,"confirm":true}))
            .unwrap();
        assert_eq!(applied["mutated"], true);
        package = super::read_package(&path).unwrap();
        assert_eq!(compile_status(&package).unwrap(), CompileState::Compiled);
        assert_eq!(controller.initial().unwrap()["detail"]["state"], "compiled");
        assert_eq!(changes.lock().unwrap().len(), before_events + 1);
        let unchanged = (
            fs::read(&path).unwrap(),
            fs::metadata(&path).unwrap().modified().unwrap(),
        );
        let noop = controller
            .dispatch("compile", &json!({"path":path,"confirm":true}))
            .unwrap();
        assert_eq!(noop["mutated"], false);
        assert_eq!(
            (
                fs::read(&path).unwrap(),
                fs::metadata(&path).unwrap().modified().unwrap()
            ),
            unchanged
        );
        assert_eq!(changes.lock().unwrap().len(), before_events + 1);
        let no_preview = controller
            .dispatch("compile", &json!({"path":path}))
            .unwrap();
        assert_eq!(no_preview["applied"], false);
        assert_eq!(
            controller.initial().unwrap()["column"]["result"]["level"],
            "warn"
        );
        package.entries[1].data = String::from_utf8(package.entries[1].data.clone())
            .unwrap()
            .replace(
                "</hs:sec>",
                "<hp:p><hp:run><hp:t>{{title}}</hp:t></hp:run></hp:p></hs:sec>",
            )
            .into_bytes();
        fs::write(&path, package.to_bytes().unwrap()).unwrap();
        assert_eq!(
            compile_status(&super::read_package(&path).unwrap()).unwrap(),
            CompileState::Partial { remaining: 1 }
        );
        assert_eq!(
            controller
                .dispatch("compile", &json!({"path":path,"confirm":true}))
                .unwrap()["mutated"],
            true
        );
        assert_eq!(
            compile_status(&super::read_package(&path).unwrap()).unwrap(),
            CompileState::Compiled
        );
        assert_eq!(changes.lock().unwrap().len(), before_events + 2);
    }

    #[test]
    fn review_and_slot_mutation_share_live_path_and_refresh_detail() {
        let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let sandbox = repo.join(format!(
            ".cache/template-controller-owner-{}",
            std::process::id()
        ));
        let template_dir = sandbox.join("templates");
        fs::create_dir_all(&template_dir).unwrap();
        let path = template_dir.join("canonical.hwpx");
        fs::copy(repo.join("tests/corpus/slots/canonical.hwpx"), &path).unwrap();
        fs::write(template_dir.join("note.txt"), "{{이름}}").unwrap();
        let settings_path = sandbox.join("settings.json");
        let settings = Arc::new(ShellSettings::new(settings_path.clone(), |_| {}));
        let root = Arc::new(TemplateRoot::new(settings, template_dir.clone()).unwrap());
        let files = Arc::new(TemplateFileStore::new({
            let root = root.clone();
            move || root.path()
        }));
        let pools = Arc::new(DatasetPoolRegistry::new(sandbox.join("datasets")).unwrap());
        let examples = Arc::new(ExamplePack {
            assets: repo.join("examples/onboarding"),
            data_dir: sandbox.join("example_data"),
            settings_path,
            root: root.clone(),
            files,
            pools,
            alert: Arc::new(|_| {}),
        });
        let changed = Arc::new(Mutex::new(Vec::new()));
        let for_graph = (root.clone(), examples.clone(), changed.clone());
        let pushed = Arc::new(Mutex::new(Vec::new()));
        let observed = pushed.clone();
        let pause_next = Arc::new(AtomicBool::new(false));
        let pause_sink = pause_next.clone();
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let release_rx = Mutex::new(release_rx);
        let graph = WorkspaceSwitch::new(
            Locations::new(
                Path::new("C:/Users/test"),
                Some(sandbox.as_os_str().to_os_string()),
            ),
            move |_screen, snapshot| {
                if pause_sink.swap(false, Ordering::SeqCst) {
                    entered_tx.send(()).unwrap();
                    release_rx.lock().unwrap().recv().unwrap();
                }
                observed.lock().unwrap().push(snapshot.clone());
                Ok(None)
            },
            move |home, gate, token| {
                let changed = for_graph.2.clone();
                let controller = Arc::new(TemplateController::new(
                    for_graph.0.clone(),
                    for_graph.1.clone(),
                    gate,
                    Arc::new(move |kind, path| {
                        changed
                            .lock()
                            .unwrap()
                            .push((kind.to_owned(), path.to_path_buf()));
                        Ok(())
                    }),
                    Arc::new(|_| Ok(())),
                    Arc::new(|| Ok(())),
                ));
                Ok(WorkspaceGraph::new(
                    home.map(Path::to_path_buf),
                    vec![("tpl".into(), controller.clone())],
                    controller,
                    token,
                ))
            },
        )
        .unwrap();
        let controller = graph.active().controller("tpl").unwrap();
        let initial = controller.initial().unwrap();
        assert_eq!(initial["column"]["count_label"], "2개");
        assert_eq!(
            initial
                .as_object()
                .unwrap()
                .keys()
                .map(String::as_str)
                .collect::<std::collections::BTreeSet<_>>(),
            std::collections::BTreeSet::from(["column", "templates_root", "detail", "examples"])
        );
        assert_eq!(
            initial["column"]
                .as_object()
                .unwrap()
                .keys()
                .map(String::as_str)
                .collect::<std::collections::BTreeSet<_>>(),
            std::collections::BTreeSet::from([
                "rows",
                "notices",
                "empty_hint",
                "count_label",
                "result"
            ])
        );
        assert_eq!(initial["column"]["notices"], json!([]));
        assert!(initial["detail"].is_null());
        assert_eq!(
            initial["templates_root"],
            json!({"directory":template_dir,"source":"default","source_label":"기본 폴더","notice":""})
        );
        for row in initial["column"]["rows"].as_array().unwrap() {
            assert_eq!(
                row.as_object()
                    .unwrap()
                    .keys()
                    .map(String::as_str)
                    .collect::<std::collections::BTreeSet<_>>(),
                std::collections::BTreeSet::from([
                    "key",
                    "name",
                    "sub",
                    "reason",
                    "warns",
                    "badge_label",
                    "badge_level",
                    "icon",
                    "selectable",
                    "path",
                    "actions"
                ])
            );
        }
        assert_eq!(initial["column"]["rows"][1]["badge_label"], "TXT");
        controller
            .dispatch("review", &json!({"path":path}))
            .unwrap();
        let before = controller.initial().unwrap();
        let slot_id = before["detail"]["slots"]["rows"][0]["id"].as_str().unwrap();
        assert!(
            controller
                .dispatch(
                    "slot_rename",
                    &json!({"path":sandbox.join("outside.hwpx"),"slot_id":slot_id,"label":"bad"})
                )
                .is_err()
        );
        assert!(changed.lock().unwrap().is_empty());
        controller
            .dispatch(
                "slot_rename",
                &json!({"path":path,"slot_id":slot_id,"label":"새 제목"}),
            )
            .unwrap();
        let after = controller.initial().unwrap();
        assert_eq!(after["detail"]["slots"]["rows"][0]["label"], "새 제목");
        assert_eq!(
            changed.lock().unwrap().as_slice(),
            &[("mutated".into(), path.clone())]
        );
        let live_groups = Arc::new(GroupSettings::new(sandbox.join("settings.json"), |_| {}));
        let live = WorkspaceSwitch::new(Locations::new(&sandbox, None), |_, _| Ok(None), {
            let root = root.clone();
            let groups = live_groups.clone();
            move |home, gate, token| {
                let controller = Arc::new(TemplateController::new_live(
                    root.clone(),
                    groups.clone(),
                    gate,
                    Arc::new(|_, _| Ok(())),
                    Arc::new(|_| Ok(())),
                ));
                Ok(WorkspaceGraph::new(
                    home.map(Path::to_path_buf),
                    vec![("tpl".into(), controller)],
                    (),
                    token,
                ))
            }
        })
        .unwrap();
        for (media, kept, gone) in [
            ("hwpx", "canonical.hwpx", "ghost.hwpx"),
            ("txt", "note.txt", "ghost.txt"),
        ] {
            live_groups
                .update_template_state(media, |groups, folds| {
                    groups.insert(kept.into(), "유지".into());
                    groups.insert(gone.into(), "유령".into());
                    folds.insert("유지".into());
                })
                .unwrap();
        }
        let live_tpl = live.active().controller("tpl").unwrap();
        assert_eq!(live_tpl.initial().unwrap()["column"]["count_label"], "2개");
        assert!(live_tpl.dispatch("install_examples", &json!({})).is_err());
        assert!(live_tpl.dispatch("remove_examples", &json!({})).is_err());
        for (media, kept) in [("hwpx", "canonical.hwpx"), ("txt", "note.txt")] {
            assert_eq!(
                live_groups.load_template_groups(media).unwrap(),
                std::collections::BTreeMap::from([(kept.into(), "유지".into())])
            );
            assert_eq!(
                live_groups.load_template_collapsed(media).unwrap(),
                ["유지"]
            );
        }
        for action in [
            "delete",
            "undo_delete",
            "scan_import_folder",
            "import_folder",
            "frobnicate",
        ] {
            assert!(live_tpl.dispatch(action, &json!({})).is_err());
        }
        let before = pushed.lock().unwrap().len();
        pause_next.store(true, Ordering::SeqCst);
        let first = controller.clone();
        let earlier_path = path.clone();
        let earlier = std::thread::spawn(move || {
            first
                .dispatch("review", &json!({"path":earlier_path}))
                .unwrap();
        });
        entered_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        let note = template_dir.join("note.txt");
        let second = controller.clone();
        let later_path = note.clone();
        let later = std::thread::spawn(move || {
            second
                .dispatch("review", &json!({"path":later_path}))
                .unwrap();
        });
        let deadline = Instant::now() + Duration::from_secs(2);
        while controller.initial().unwrap()["detail"]["path"] != note.to_str().unwrap() {
            assert!(
                Instant::now() < deadline,
                "later template mutation did not land"
            );
            std::thread::yield_now();
        }
        release_tx.send(()).unwrap();
        earlier.join().unwrap();
        later.join().unwrap();
        let snapshots = pushed.lock().unwrap();
        assert_eq!(snapshots[before]["detail"]["path"], path.to_str().unwrap());
        assert_eq!(
            snapshots[before + 1]["detail"]["path"],
            note.to_str().unwrap()
        );
        drop(snapshots);
        assert_compile_preserves_preview_and_noop(controller.as_ref(), &template_dir, &changed);
        assert_structure_conversion(controller.as_ref(), &template_dir, &changed);
        assert_review_reads_and_membership(controller.as_ref(), &template_dir, &pushed);
        assert_column_view(controller.as_ref(), &template_dir);
        assert_root_switching(&graph.active().resources, &sandbox, &template_dir, &pushed);
        assert!(
            sandbox
                .canonicalize()
                .unwrap()
                .starts_with(repo.canonicalize().unwrap())
        );
        fs::remove_dir_all(sandbox).unwrap();
    }
}
