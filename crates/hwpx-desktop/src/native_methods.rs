//! Direct host verbs that require a Windows dialog, clipboard, shell, or trusted live session.

#[path = "native_authoring_files.rs"]
mod authoring_files;
#[path = "native_data_sheets.rs"]
mod data_sheets;

use crate::dialogs::{hwpx_file_filter, open_file_dialog, open_folder_dialog, save_file_dialog};
use crate::live_graph::LiveGraph;
use crate::onboarding_controller::OnboardingController;
use crate::owned_paths::{collect_owned_paths, validate_owned_path};
use crate::reveal::{open_path, reveal_in_explorer};
use crate::template_inventory::discover_paths;
use crate::workspace_runtime::RuntimeResources;
use hwpx_filler::data_source::{CONTRACT_LIST_FILE_EXTENSIONS, SUPPORTED_DATA_FILE_EXTENSIONS};
use serde_json::{Value, json};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::OnceLock;

pub struct NativeMethods {
    graph: Arc<LiveGraph<RuntimeResources>>,
    base_dir: PathBuf,
    onboarding: Option<Arc<OnboardingController>>,
}

fn listed_template_path(root: &Path, media: &str, selected: &Path) -> Result<bool, String> {
    let selected_media = selected
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    if selected_media != media {
        return Ok(false);
    }
    Ok(discover_paths(root)
        .map_err(|error| error.to_string())?
        .iter()
        .any(|path| path == selected))
}

pub fn host_contract() -> &'static Value {
    static CONTRACT: OnceLock<Value> = OnceLock::new();
    CONTRACT.get_or_init(|| {
        serde_json::from_str(include_str!("host_contract.json")).expect("embedded host contract")
    })
}

pub fn validate_host_call(method: &str, args: &[Value]) -> Result<(), String> {
    let methods = host_contract()["host_methods"]
        .as_array()
        .expect("host methods array");
    let entry = methods
        .iter()
        .find(|entry| entry["name"] == method)
        .ok_or_else(|| format!("등록되지 않은 네이티브 명령: {method}"))?;
    let params = entry["params"].as_array().expect("method params array");
    let required = params
        .iter()
        .filter(|item| item["optional"] != true)
        .count();
    if args.len() < required || args.len() > params.len() {
        return Err(format!("{method}: 인자 수가 올바르지 않습니다."));
    }
    for (index, value) in args.iter().enumerate() {
        // dispatch's payload schema belongs to action_registry: it produces the
        // established ValueError envelope, rather than a transport type error.
        if method == "dispatch" && index == 2 {
            continue;
        }
        let param = &params[index];
        if value.is_null() && param["optional"] == true {
            continue;
        }
        let good = match param["type"].as_str().expect("param type") {
            "any" => true,
            "string" => value.is_string(),
            "boolean" => value.is_boolean(),
            "integer" => value.as_i64().is_some() || value.as_u64().is_some(),
            "object" => value.is_object(),
            "string-or-array" => {
                value.is_string()
                    || value
                        .as_array()
                        .is_some_and(|items| items.iter().all(Value::is_string))
            }
            _ => false,
        };
        if !good {
            return Err(format!(
                "{method}: {} 인자가 올바르지 않습니다.",
                param["name"].as_str().unwrap_or("unknown")
            ));
        }
    }
    Ok(())
}

impl NativeMethods {
    pub fn new(graph: Arc<LiveGraph<RuntimeResources>>) -> Result<Self, String> {
        Ok(Self {
            graph,
            base_dir: std::env::current_dir().map_err(|e| e.to_string())?,
            onboarding: None,
        })
    }

    pub fn with_onboarding(mut self, onboarding: Arc<OnboardingController>) -> Self {
        self.onboarding = Some(onboarding);
        self
    }

    /// Production processing after the dialog has supplied a path. The same path
    /// is used by native replay with an injected picker result.
    pub fn selected_data_file(&self, screen: &str, path: &Path) -> Result<Value, String> {
        let token = self.graph.product_token();
        let resources = self.graph.active_resources().map_err(|e| e.to_string())?;
        let result = self.process_selected_data_file(&resources, screen, path);
        if result.is_object() {
            self.graph.returned_product(
                token.as_ref(),
                screen,
                "pick_data_file",
                &json!({"path":path.to_string_lossy()}),
                &result,
            );
        }
        Ok(result)
    }

    fn process_selected_data_file(
        &self,
        resources: &RuntimeResources,
        screen: &str,
        target: &Path,
    ) -> Value {
        let path = target.to_string_lossy().into_owned();
        if hwpx_filler::data_factory::is_contract_list_file(target) {
            return json!({"contract_list":true,"path":path});
        }
        let selected = (|| -> Result<Value, String> {
            let sheets =
                hwpx_filler::data_excel::ambiguous_sheets(target).map_err(|e| e.to_string())?;
            if !sheets.is_empty() {
                let names = sheets
                    .into_iter()
                    .map(|(name, rows, cols)| json!({"name":name,"rows":rows,"cols":cols}))
                    .collect::<Vec<_>>();
                return Ok(json!({"needs_sheet":true,"path":path,
                    "name":target.file_name().unwrap_or_default().to_string_lossy(),"sheets":names}));
            }
            self.mount_data(resources, screen, target, None)
        })();
        selected.unwrap_or_else(|error| json!(format!("ERROR: {error}")))
    }

    pub fn call(
        &self,
        method: &str,
        args: &[Value],
        clipboard_owner: impl Fn() -> Result<isize, String>,
    ) -> Result<Value, String> {
        let token = self.graph.product_token();
        let result = self.call_inner(method, args, clipboard_owner)?;
        if let Some((screen, action, payload)) = direct_observation(method, args, &result) {
            self.graph
                .returned_product(token.as_ref(), &screen, action, &payload, &result);
        }
        Ok(result)
    }

    /// Routes one validated host verb to its handler; every arm is a single call.
    fn call_inner(
        &self,
        method: &str,
        args: &[Value],
        clipboard_owner: impl Fn() -> Result<isize, String>,
    ) -> Result<Value, String> {
        validate_host_call(method, args)?;
        let resources = self.graph.active_resources().map_err(|e| e.to_string())?;
        let call = HostCall {
            method,
            args,
            owner: &clipboard_owner,
        };
        let r = &resources;
        match method {
            "pick_data_file" => self.pick_data_file(r, &call),
            "load_data_sheet" => self.load_data_sheet(r, &call),
            "copy_clipboard" => copy_clipboard(r, &call),
            "save_artifact_as" => save_artifact_as(r, &call),
            "open_job_in_editor" => open_job_in_editor(r, &call),
            "new_job_from_data" => new_job_from_data(r, &call),
            "set_theme" => set_theme(r, &call),
            "set_font_scale" => set_font_scale(r, &call),
            "set_master_width" => set_master_width(r, &call),
            "set_authoring_width" => set_authoring_width(r, &call),
            "generate" => generate(r, &call),
            "pick_output_folder" => pick_output_folder(r, &call),
            "pick_templates_root" => pick_templates_root(r, &call),
            "pick_pool_data_file" => self.pick_pool_data_file(&call),
            "pick_template_path" => pick_template_path(&call),
            "pick_work_package_path" => pick_work_package_path(&call),
            "reveal_corrupt_job" => reveal_corrupt_job(r, &call),
            "open_path" | "reveal_path" | "copy_path" => self.owned_path_verb(r, &call),
            "open_authoring_document" => authoring_files::open_authoring_document(r, &call),
            "save_authoring_document" => authoring_files::save_authoring_document(r, &call),
            "authoring_cases_file" => authoring_files::authoring_cases_file(r, &call),
            "export_authoring_result" => authoring_files::export_authoring_result(r, &call),
            "import_template_file" => authoring_files::import_template_file(r, &call),
            _ => Err(format!("등록되지 않은 네이티브 명령: {method}")),
        }
    }

    /// The tutorial's file-picker hint for `screen`, or none outside the tutorial.
    fn file_picker_hint(&self, screen: &str) -> Result<String, String> {
        Ok(self
            .onboarding
            .as_ref()
            .map(|tutorial| {
                tutorial
                    .file_picker_hint("data", screen)
                    .map_err(|e| e.to_string())
            })
            .transpose()?
            .unwrap_or_default())
    }

    fn pick_data_file(
        &self,
        resources: &RuntimeResources,
        call: &HostCall<'_>,
    ) -> Result<Value, String> {
        let screen = call.string(0)?;
        let hint = self.file_picker_hint(screen)?;
        let path =
            open_file_dialog(data_filters(), call.hwnd()?, hint).map_err(|e| e.to_string())?;
        let Some(path) = path else {
            return Ok(Value::Null);
        };
        Ok(self.process_selected_data_file(resources, screen, Path::new(&path)))
    }

    fn pick_pool_data_file(&self, call: &HostCall<'_>) -> Result<Value, String> {
        let hint = self.file_picker_hint("")?;
        Ok(json!(
            open_file_dialog(excel_filters(), call.hwnd()?, hint).map_err(|e| e.to_string())?
        ))
    }

    /// `open_path`, `reveal_path`, `copy_path`: only a path this app owns right now.
    fn owned_path_verb(
        &self,
        resources: &RuntimeResources,
        call: &HostCall<'_>,
    ) -> Result<Value, String> {
        let path = call.string(0)?;
        let result = (|| -> Result<(), String> {
            let owned = self.owned_paths(resources)?;
            let path =
                validate_owned_path(path, &owned, &self.base_dir).map_err(|e| e.to_string())?;
            match call.method {
                "open_path" => {
                    open_path(Path::new(path)).map_err(|e| e.to_string())?;
                }
                "reveal_path" => {
                    reveal_in_explorer(Path::new(path)).map_err(|e| e.to_string())?;
                }
                _ => {
                    crate::clipboard::set_clipboard_text(call.hwnd()?, path)
                        .map_err(|e| e.to_string())?;
                }
            }
            Ok(())
        })();
        Ok(result
            .err()
            .map(|e| json!(format!("ERROR: {e}")))
            .unwrap_or(Value::Null))
    }

    fn owned_paths(&self, resources: &RuntimeResources) -> Result<HashSet<String>, String> {
        let mut session = resources
            .job
            .owned_session_paths()
            .map_err(|e| e.to_string())?;
        let (template, data) = resources
            .editor
            .owned_session_paths()
            .map_err(|e| e.to_string())?;
        session.extend([
            template,
            data,
            resources.templates.path().to_string_lossy().into_owned(),
        ]);
        collect_owned_paths(
            &resources.jobs,
            &resources.datasets,
            &session,
            &self.base_dir,
        )
        .map_err(|e| e.to_string())
    }

    fn mount_data(
        &self,
        resources: &RuntimeResources,
        screen: &str,
        path: &Path,
        sheet: Option<&str>,
    ) -> Result<Value, String> {
        match screen {
            "job" => resources
                .job
                .load_data_path(path, sheet, 0)
                .map_err(|e| e.to_string())?,
            "editor" => resources
                .editor
                .load_data_path(path, sheet, 0)
                .map_err(|e| e.to_string())?,
            _ => return Err("데이터를 가져올 화면과 파일을 확인하세요.".into()),
        }
        let rows = if screen == "job" {
            resources
                .job
                .data()
                .map_err(|e| e.to_string())?
                .records
                .len()
        } else {
            let mut source = hwpx_filler::data_factory::source_for_path(path, sheet, 1)
                .map_err(|e| e.to_string())?;
            source.records().map_err(|e| e.to_string())?.len()
        };
        let label = path
            .file_name()
            .ok_or("데이터 파일명이 없습니다.")?
            .to_string_lossy();
        Ok(
            json!({"label":format!("파일: {label}"),"path":path.to_string_lossy(),"sheet":sheet.unwrap_or(""),"rows":rows}),
        )
    }
}

/// One validated host call: its verb, raw arguments, and the clipboard/dialog owner window.
struct HostCall<'a> {
    method: &'a str,
    args: &'a [Value],
    owner: &'a dyn Fn() -> Result<isize, String>,
}

impl<'a> HostCall<'a> {
    fn string(&self, index: usize) -> Result<&'a str, String> {
        self.args
            .get(index)
            .and_then(Value::as_str)
            .ok_or_else(|| format!("{}: 문자열 인자 {index}가 필요합니다.", self.method))
    }

    fn hwnd(&self) -> Result<isize, String> {
        (self.owner)()
    }
}

fn copy_clipboard(resources: &RuntimeResources, call: &HostCall<'_>) -> Result<Value, String> {
    if call.string(0)? != "workbench" {
        return Err("이 화면은 클립보드 복사 거래를 소유하지 않습니다.".into());
    }
    let token = call.args.get(1).and_then(Value::as_str).unwrap_or("");
    resources
        .workbench
        .copy_to(token, |text| {
            crate::clipboard::set_clipboard_text(call.hwnd().map_err(std::io::Error::other)?, text)
                .map_err(Into::into)
        })
        .map_err(|e| e.to_string())
}

fn save_artifact_as(resources: &RuntimeResources, call: &HostCall<'_>) -> Result<Value, String> {
    resources.job.save_artifact_as(
        call.args.first().unwrap_or(&Value::Null),
        |name, filters, extension| {
            save_file_dialog(name, filters, extension, call.hwnd()?)
                .map_err(|error| error.to_string())
        },
    )
}

/// The object argument at `index`, or an empty object.
fn context_arg(call: &HostCall<'_>, index: usize) -> Value {
    call.args
        .get(index)
        .filter(|value| value.is_object())
        .cloned()
        .unwrap_or_else(|| json!({}))
}

/// A handoff result as the host's string-or-`ERROR:` value.
fn handoff_value(result: Result<String, String>) -> Value {
    match result {
        Ok(text) => json!(text),
        Err(error) => json!(format!("ERROR: {error}")),
    }
}

fn open_job_in_editor(resources: &RuntimeResources, call: &HostCall<'_>) -> Result<Value, String> {
    let name = call.string(0)?;
    let context = context_arg(call, 1);
    let result = (|| -> Result<String, String> {
        resources
            .generation
            .raise_if_generating("편집기를 여세요", false)
            .map_err(|e| e.to_string())?;
        let reason = context["entry_reason"].as_str().unwrap_or("");
        let source = if matches!(
            reason,
            "document_browser_new_work" | "document_browser_repair" | "workbench_result"
        ) {
            Some(
                resources
                    .job
                    .new_work_handoff()
                    .map_err(|e| e.to_string())?
                    .0,
            )
        } else {
            None
        };
        resources
            .editor
            .load_job_with_context(name, &context, source.as_ref())
            .map_err(|e| e.to_string())?;
        Ok(name.into())
    })();
    Ok(handoff_value(result))
}

fn new_job_from_data(resources: &RuntimeResources, call: &HostCall<'_>) -> Result<Value, String> {
    let context = context_arg(call, 0);
    let result = (|| -> Result<String, String> {
        resources
            .generation
            .raise_if_generating("새 작업을 시작하세요", false)
            .map_err(|e| e.to_string())?;
        let (source, blocked) = resources
            .job
            .new_work_handoff()
            .map_err(|e| e.to_string())?;
        if !blocked.is_empty() {
            return Err(blocked);
        }
        resources
            .editor
            .new_draft_with_data(&source, &context)
            .map_err(|e| e.to_string())?;
        Ok(source["path"].as_str().unwrap_or("").into())
    })();
    Ok(handoff_value(result))
}

fn set_theme(resources: &RuntimeResources, call: &HostCall<'_>) -> Result<Value, String> {
    let value = call.string(0)?;
    resources
        .settings
        .save_theme(value)
        .map_err(|e| e.to_string())?;
    Ok(json!(value))
}

fn set_font_scale(resources: &RuntimeResources, call: &HostCall<'_>) -> Result<Value, String> {
    let value = call.string(0)?;
    resources
        .settings
        .save_font_scale(value)
        .map_err(|e| e.to_string())?;
    Ok(json!(value))
}

fn set_master_width(resources: &RuntimeResources, call: &HostCall<'_>) -> Result<Value, String> {
    let value = call
        .args
        .first()
        .and_then(Value::as_i64)
        .ok_or("폭이 정수가 아닙니다.")?;
    resources
        .settings
        .save_master_width(value)
        .map_err(|e| e.to_string())?;
    Ok(json!(value))
}

fn set_authoring_width(resources: &RuntimeResources, call: &HostCall<'_>) -> Result<Value, String> {
    let panel = call.string(0)?;
    let value = call
        .args
        .get(1)
        .and_then(Value::as_i64)
        .ok_or("폭이 정수가 아닙니다.")?;
    resources
        .settings
        .save_authoring_width(panel, value)
        .map_err(|e| e.to_string())?;
    Ok(json!(value))
}

fn generate(resources: &RuntimeResources, call: &HostCall<'_>) -> Result<Value, String> {
    if call.string(0)? != "job" {
        return Err("문서 생성 화면이 아닙니다.".into());
    }
    let overwrite = call.args.get(1).and_then(Value::as_bool).unwrap_or(false);
    let token = call.args.get(2).and_then(Value::as_str).unwrap_or("");
    resources
        .job
        .generate(overwrite, token)
        .map_err(|e| e.to_string())
}

fn pick_output_folder(resources: &RuntimeResources, call: &HostCall<'_>) -> Result<Value, String> {
    if call.string(0)? != "job" {
        return Err("저장 폴더를 고를 화면이 아닙니다.".into());
    }
    let path =
        open_folder_dialog("저장 폴더 선택".into(), call.hwnd()?).map_err(|e| e.to_string())?;
    let Some(path) = path else {
        return Ok(Value::Null);
    };
    match resources.job.set_output_folder(&path) {
        Ok(()) => Ok(json!(path)),
        Err(e) => Ok(json!(format!("ERROR: {e}"))),
    }
}

fn pick_templates_root(resources: &RuntimeResources, call: &HostCall<'_>) -> Result<Value, String> {
    if call.string(0)?.is_empty() {
        return Err("호출 화면 이름이 비어 있습니다.".into());
    }
    let path =
        open_folder_dialog("서식 폴더 선택".into(), call.hwnd()?).map_err(|e| e.to_string())?;
    let Some(path) = path else {
        return Ok(Value::Null);
    };
    match resources.template.set_templates_root(&path) {
        Ok(_) => Ok(json!(path)),
        Err(e) => Ok(json!(format!("ERROR: {e}"))),
    }
}

fn pick_template_path(call: &HostCall<'_>) -> Result<Value, String> {
    Ok(json!(
        open_file_dialog(
            vec![hwpx_file_filter(), ("모든 파일".into(), "*.*".into())],
            call.hwnd()?,
            String::new()
        )
        .map_err(|e| e.to_string())?
    ))
}

fn pick_work_package_path(call: &HostCall<'_>) -> Result<Value, String> {
    Ok(json!(pick_package_path(
        call.string(0)?,
        |filters| open_file_dialog(filters, call.hwnd()?, String::new()).map_err(|e| e.to_string()),
        |name, filters, extension| save_file_dialog(name, filters, extension, call.hwnd()?)
            .map_err(|e| e.to_string()),
    )?))
}

fn reveal_corrupt_job(resources: &RuntimeResources, call: &HostCall<'_>) -> Result<Value, String> {
    let path = call.string(0)?;
    let result = resources
        .library
        .validate_corrupt_path(path)
        .and_then(|path| reveal_in_explorer(&path).map(|_| ()).map_err(Into::into));
    Ok(result
        .err()
        .map(|e| json!(format!("ERROR: {e}")))
        .unwrap_or(Value::Null))
}

fn direct_observation(
    method: &str,
    args: &[Value],
    result: &Value,
) -> Option<(String, &'static str, Value)> {
    let screen = args.first().and_then(Value::as_str).unwrap_or("");
    match method {
        "generate" => Some(("job".into(), "generate", json!({}))),
        "copy_clipboard" => Some((
            screen.into(),
            "copy_clipboard",
            json!({"token":args.get(1)}),
        )),
        "pick_data_file" if result.is_object() => Some((
            screen.into(),
            "pick_data_file",
            json!({"path":result["path"]}),
        )),
        "load_data_sheet" => Some((
            screen.into(),
            "load_data_sheet",
            json!({"path":args.get(1),"sheet":args.get(2)}),
        )),
        "open_job_in_editor" => Some((
            "editor".into(),
            "open_job_in_editor",
            json!({"name":args.first()}),
        )),
        "open_authoring_document" => Some((
            "authoring".into(),
            "open_authoring_document",
            json!({"path":args.first()}),
        )),
        "save_authoring_document" => Some((
            "authoring".into(),
            "save_authoring_document",
            json!({"session_id":args.first()}),
        )),
        _ => None,
    }
}

fn pick_package_path(
    action: &str,
    open_file: impl FnOnce(Vec<(String, String)>) -> Result<Option<String>, String>,
    save_file: impl FnOnce(String, Vec<(String, String)>, String) -> Result<Option<String>, String>,
) -> Result<Option<String>, String> {
    let filters = vec![("작업 꾸러미 (*.narumi)".into(), "*.narumi".into())];
    match action {
        "export" => save_file("작업 꾸러미.narumi".into(), filters, "narumi".into()),
        "import" => open_file(filters),
        _ => Err(format!(
            "꾸러미 파일 선택 action 은 export·import 중 하나여야 한다: {}",
            hwpx_filler::text_render::python_repr(&json!(action))
        )),
    }
}

fn data_filters() -> Vec<(String, String)> {
    let excel = extension_pattern(&SUPPORTED_DATA_FILE_EXTENSIONS);
    let contracts = extension_pattern(&CONTRACT_LIST_FILE_EXTENSIONS);
    vec![
        ("데이터 파일".into(), format!("{excel};{contracts}")),
        ("엑셀/CSV 데이터".into(), excel),
        ("계약 목록 자료".into(), contracts),
        ("모든 파일".into(), "*.*".into()),
    ]
}

fn excel_filters() -> Vec<(String, String)> {
    vec![
        (
            "엑셀/CSV 데이터".into(),
            extension_pattern(&SUPPORTED_DATA_FILE_EXTENSIONS),
        ),
        ("모든 파일".into(), "*.*".into()),
    ]
}

fn extension_pattern(extensions: &[&str]) -> String {
    extensions
        .iter()
        .map(|extension| format!("*{extension}"))
        .collect::<Vec<_>>()
        .join(";")
}

fn current_applied_template(resources: &RuntimeResources, path: &Path) -> Result<bool, String> {
    let target = std::fs::canonicalize(path).map_err(|e| e.to_string())?;
    let authority = resources
        .jobs
        .directory()
        .parent()
        .ok_or("작업 저장소의 상위 경로가 없습니다.")?
        .join("template_authority/applied");
    let Ok(applied) = std::fs::canonicalize(authority) else {
        return Ok(false);
    };
    if !target.starts_with(applied) {
        return Ok(false);
    }
    let target =
        crate::single_instance::normalize_windows_path(&target).map_err(|e| e.to_string())?;
    let jobs = resources
        .jobs
        .list_jobs_with_corruption()
        .map_err(|e| e.to_string())?
        .0;
    Ok(jobs.iter().any(|job| {
        std::fs::canonicalize(&job.template_path)
            .ok()
            .and_then(|path| crate::single_instance::normalize_windows_path(&path).ok())
            .is_some_and(|owned| owned.eq_ignore_ascii_case(&target))
    }))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn direct_host_calls_reject_bad_arguments_before_native_effects() {
        assert!(
            validate_host_call(
                "load_data_sheet",
                &[json!("job"), json!("C:/data.xlsx"), json!(["One", "Two"])]
            )
            .is_ok()
        );
        for (method, args) in [
            (
                "load_data_sheet",
                vec![json!("job"), json!("C:/data.xlsx"), json!(7)],
            ),
            (
                "save_authoring_document",
                vec![json!("session"), json!(0.5)],
            ),
            ("copy_clipboard", vec![json!("workbench"), json!(false)]),
            ("pick_pool_data_file", vec![json!("extra")]),
            ("not_registered", vec![]),
        ] {
            assert!(
                validate_host_call(method, &args).is_err(),
                "{method}: {args:?}"
            );
        }
        assert!(
            validate_host_call("dispatch", &[json!("job"), json!("action"), json!([])]).is_ok(),
            "dispatch payload refusal belongs to the action registry"
        );
    }

    #[test]
    fn data_pickers_offer_supported_formats_for_their_destination() {
        assert_eq!(
            hwpx_file_filter(),
            ("HWPX (*.hwpx)".into(), "*.hwpx".into())
        );
        assert_eq!(
            data_filters(),
            vec![
                (
                    "데이터 파일".into(),
                    "*.xlsx;*.xlsm;*.csv;*.db;*.pclm".into()
                ),
                ("엑셀/CSV 데이터".into(), "*.xlsx;*.xlsm;*.csv".into()),
                ("계약 목록 자료".into(), "*.db;*.pclm".into()),
                ("모든 파일".into(), "*.*".into()),
            ]
        );
        assert_eq!(
            excel_filters(),
            vec![
                ("엑셀/CSV 데이터".into(), "*.xlsx;*.xlsm;*.csv".into()),
                ("모든 파일".into(), "*.*".into()),
            ]
        );
    }

    #[test]
    fn package_picker_preserves_host_arguments_cancellation_and_failures() {
        let filters = vec![("작업 꾸러미 (*.narumi)".into(), "*.narumi".into())];
        assert_eq!(
            pick_package_path(
                "export",
                |_| panic!("unexpected open"),
                |name, actual, extension| {
                    assert_eq!(name, "작업 꾸러미.narumi");
                    assert_eq!(actual, filters);
                    assert_eq!(extension, "narumi");
                    Ok(Some("C:/out/a.narumi".into()))
                }
            )
            .unwrap(),
            Some("C:/out/a.narumi".into())
        );
        assert_eq!(
            pick_package_path(
                "import",
                |actual| {
                    assert_eq!(actual, filters);
                    Ok(None)
                },
                |_, _, _| panic!("unexpected save")
            )
            .unwrap(),
            None
        );
        assert_eq!(
            pick_package_path(
                "delete",
                |_| panic!("unexpected open"),
                |_, _, _| panic!("unexpected save")
            )
            .unwrap_err(),
            "꾸러미 파일 선택 action 은 export·import 중 하나여야 한다: 'delete'"
        );
        assert_eq!(
            pick_package_path(
                "export",
                |_| panic!("unexpected open"),
                |_, _, _| Err("host failed".into())
            )
            .unwrap_err(),
            "host failed"
        );
    }

    #[test]
    fn direct_authoring_path_gate_uses_live_membership_without_parsing_other_templates() {
        let root = std::env::temp_dir().join(format!(
            "hwpx-native-listed-{}",
            uuid::Uuid::new_v4().simple()
        ));
        std::fs::create_dir(&root).unwrap();
        let corrupt = root.join("listed.hwpx");
        std::fs::write(&corrupt, b"broken package").unwrap();
        assert!(listed_template_path(&root, "hwpx", &corrupt).unwrap());
        assert!(!listed_template_path(&root, "txt", &corrupt).unwrap());
        let outside = root.parent().unwrap().join("not-listed.hwpx");
        assert!(!listed_template_path(&root, "hwpx", &outside).unwrap());
        std::fs::remove_file(&corrupt).unwrap();
        assert!(!listed_template_path(&root, "hwpx", &corrupt).unwrap());
        std::fs::remove_dir(&root).unwrap();
    }
}
