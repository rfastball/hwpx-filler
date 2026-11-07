//! Direct host verbs that require a Windows dialog, clipboard, shell, or trusted live session.

use crate::dialogs::{hwpx_file_filter, open_file_dialog, open_folder_dialog, save_file_dialog};
use crate::live_graph::LiveGraph;
use crate::onboarding_controller::OnboardingController;
use crate::owned_paths::{collect_owned_paths, validate_owned_path};
use crate::reveal::{open_path, reveal_in_explorer};
use crate::template_inventory::discover_paths;
use crate::workspace_runtime::RuntimeResources;
use crate::workspace_switch::ScreenController;
use hwpx_filler::data_source::{CONTRACT_LIST_FILE_EXTENSIONS, SUPPORTED_DATA_FILE_EXTENSIONS};
use serde_json::{Value, json};
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

    fn call_inner(
        &self,
        method: &str,
        args: &[Value],
        clipboard_owner: impl Fn() -> Result<isize, String>,
    ) -> Result<Value, String> {
        validate_host_call(method, args)?;
        let resources = self.graph.active_resources().map_err(|e| e.to_string())?;
        let string = |index: usize| {
            args.get(index)
                .and_then(Value::as_str)
                .ok_or_else(|| format!("{method}: 문자열 인자 {index}가 필요합니다."))
        };
        let owner_hwnd = || clipboard_owner();
        match method {
            "pick_data_file" => {
                let screen = string(0)?;
                let hint = self
                    .onboarding
                    .as_ref()
                    .map(|tutorial| {
                        tutorial
                            .file_picker_hint("data", screen)
                            .map_err(|e| e.to_string())
                    })
                    .transpose()?
                    .unwrap_or_default();
                let path = open_file_dialog(data_filters(), owner_hwnd()?, hint)
                    .map_err(|e| e.to_string())?;
                let Some(path) = path else {
                    return Ok(Value::Null);
                };
                Ok(self.process_selected_data_file(&resources, screen, Path::new(&path)))
            }
            "load_data_sheet" => {
                let screen = string(0)?;
                let path = string(1)?;
                if let Some(sheets) = args.get(2).and_then(Value::as_array) {
                    let selected = self.register_data_sheets(
                        &resources,
                        screen,
                        Path::new(path),
                        sheets,
                        args.get(3),
                    );
                    return Ok(selected.unwrap_or_else(|error| json!(format!("ERROR: {error}"))));
                }
                if args.get(3).is_some_and(|value| !value.is_null()) {
                    return Ok(json!("ERROR: 데이터를 가져올 화면과 파일을 확인하세요."));
                }
                let sheet = string(2)?;
                let selected = (|| -> Result<Value, String> {
                    let names = hwpx_filler::data_excel::sheet_overview(Path::new(path))
                        .map_err(|e| e.to_string())?;
                    if !names.iter().any(|(name, _, _)| name == sheet) {
                        return Err(format!(
                            "'{sheet}' 시트를 찾을 수 없습니다. 시트를 다시 선택하세요."
                        ));
                    }
                    self.mount_data(&resources, screen, Path::new(path), Some(sheet))
                })();
                Ok(selected.unwrap_or_else(|error| json!(format!("ERROR: {error}"))))
            }
            "copy_clipboard" => {
                if string(0)? != "workbench" {
                    return Err("이 화면은 클립보드 복사 거래를 소유하지 않습니다.".into());
                }
                let token = args.get(1).and_then(Value::as_str).unwrap_or("");
                resources
                    .workbench
                    .copy_to(token, |text| {
                        crate::clipboard::set_clipboard_text(
                            clipboard_owner().map_err(std::io::Error::other)?,
                            text,
                        )
                        .map_err(Into::into)
                    })
                    .map_err(|e| e.to_string())
            }
            "save_artifact_as" => resources.job.save_artifact_as(
                args.first().unwrap_or(&Value::Null),
                |name, filters, extension| {
                    save_file_dialog(name, filters, extension, owner_hwnd()?)
                        .map_err(|error| error.to_string())
                },
            ),
            "open_job_in_editor" => {
                let name = string(0)?;
                let context = args
                    .get(1)
                    .filter(|value| value.is_object())
                    .cloned()
                    .unwrap_or_else(|| json!({}));
                let result = (|| -> Result<String, String> {
                    resources
                        .generation
                        .raise_if_generating("편집기를 여세요", false)
                        .map_err(|e| e.to_string())?;
                    let reason = context["entry_reason"].as_str().unwrap_or("");
                    let source = if matches!(
                        reason,
                        "document_browser_new_work"
                            | "document_browser_repair"
                            | "workbench_result"
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
                Ok(match result {
                    Ok(name) => json!(name),
                    Err(error) => json!(format!("ERROR: {error}")),
                })
            }
            "new_job_from_data" => {
                let context = args
                    .first()
                    .filter(|value| value.is_object())
                    .cloned()
                    .unwrap_or_else(|| json!({}));
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
                Ok(match result {
                    Ok(path) => json!(path),
                    Err(error) => json!(format!("ERROR: {error}")),
                })
            }
            "set_theme" => {
                let value = string(0)?;
                resources
                    .settings
                    .save_theme(value)
                    .map_err(|e| e.to_string())?;
                Ok(json!(value))
            }
            "set_font_scale" => {
                let value = string(0)?;
                resources
                    .settings
                    .save_font_scale(value)
                    .map_err(|e| e.to_string())?;
                Ok(json!(value))
            }
            "set_master_width" => {
                let value = args
                    .first()
                    .and_then(Value::as_i64)
                    .ok_or("폭이 정수가 아닙니다.")?;
                resources
                    .settings
                    .save_master_width(value)
                    .map_err(|e| e.to_string())?;
                Ok(json!(value))
            }
            "set_authoring_width" => {
                let panel = string(0)?;
                let value = args
                    .get(1)
                    .and_then(Value::as_i64)
                    .ok_or("폭이 정수가 아닙니다.")?;
                resources
                    .settings
                    .save_authoring_width(panel, value)
                    .map_err(|e| e.to_string())?;
                Ok(json!(value))
            }
            "generate" => {
                if string(0)? != "job" {
                    return Err("문서 생성 화면이 아닙니다.".into());
                }
                let overwrite = args.get(1).and_then(Value::as_bool).unwrap_or(false);
                let token = args.get(2).and_then(Value::as_str).unwrap_or("");
                resources
                    .job
                    .generate(overwrite, token)
                    .map_err(|e| e.to_string())
            }
            "pick_output_folder" => {
                if string(0)? != "job" {
                    return Err("저장 폴더를 고를 화면이 아닙니다.".into());
                }
                let path = open_folder_dialog("저장 폴더 선택".into(), owner_hwnd()?)
                    .map_err(|e| e.to_string())?;
                let Some(path) = path else {
                    return Ok(Value::Null);
                };
                match resources.job.set_output_folder(&path) {
                    Ok(()) => Ok(json!(path)),
                    Err(e) => Ok(json!(format!("ERROR: {e}"))),
                }
            }
            "pick_templates_root" => {
                if string(0)?.is_empty() {
                    return Err("호출 화면 이름이 비어 있습니다.".into());
                }
                let path = open_folder_dialog("서식 폴더 선택".into(), owner_hwnd()?)
                    .map_err(|e| e.to_string())?;
                let Some(path) = path else {
                    return Ok(Value::Null);
                };
                match resources.template.set_templates_root(&path) {
                    Ok(_) => Ok(json!(path)),
                    Err(e) => Ok(json!(format!("ERROR: {e}"))),
                }
            }
            "pick_pool_data_file" => {
                let hint = self
                    .onboarding
                    .as_ref()
                    .map(|tutorial| {
                        tutorial
                            .file_picker_hint("data", "")
                            .map_err(|e| e.to_string())
                    })
                    .transpose()?
                    .unwrap_or_default();
                Ok(json!(
                    open_file_dialog(excel_filters(), owner_hwnd()?, hint)
                        .map_err(|e| e.to_string())?
                ))
            }
            "pick_template_path" => Ok(json!(
                open_file_dialog(
                    vec![hwpx_file_filter(), ("모든 파일".into(), "*.*".into())],
                    owner_hwnd()?,
                    String::new()
                )
                .map_err(|e| e.to_string())?
            )),
            "pick_work_package_path" => Ok(json!(pick_package_path(
                string(0)?,
                |filters| open_file_dialog(filters, owner_hwnd()?, String::new())
                    .map_err(|e| e.to_string()),
                |name, filters, extension| save_file_dialog(
                    name,
                    filters,
                    extension,
                    owner_hwnd()?
                )
                .map_err(|e| e.to_string()),
            )?)),
            "reveal_corrupt_job" => {
                let path = string(0)?;
                let result = resources
                    .library
                    .validate_corrupt_path(path)
                    .and_then(|path| reveal_in_explorer(&path).map(|_| ()).map_err(Into::into));
                Ok(result
                    .err()
                    .map(|e| json!(format!("ERROR: {e}")))
                    .unwrap_or(Value::Null))
            }
            "open_path" | "reveal_path" | "copy_path" => {
                let path = string(0)?;
                let result = (|| -> Result<(), String> {
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
                    let owned = collect_owned_paths(
                        &resources.jobs,
                        &resources.datasets,
                        &session,
                        &self.base_dir,
                    )
                    .map_err(|e| e.to_string())?;
                    let path = validate_owned_path(path, &owned, &self.base_dir)
                        .map_err(|e| e.to_string())?;
                    match method {
                        "open_path" => {
                            open_path(Path::new(path)).map_err(|e| e.to_string())?;
                        }
                        "reveal_path" => {
                            reveal_in_explorer(Path::new(path)).map_err(|e| e.to_string())?;
                        }
                        _ => {
                            crate::clipboard::set_clipboard_text(clipboard_owner()?, path)
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
            "open_authoring_document" => {
                let supplied = args.first().and_then(Value::as_str).unwrap_or("");
                let as_template = args.get(1).and_then(Value::as_bool).unwrap_or(false);
                let path = if supplied.is_empty() {
                    open_file_dialog(
                        vec![hwpx_file_filter(), ("모든 파일".into(), "*.*".into())],
                        owner_hwnd()?,
                        String::new(),
                    )
                    .map_err(|e| e.to_string())?
                } else {
                    Some(supplied.into())
                };
                let Some(path) = path else {
                    return Ok(Value::Null);
                };
                if !supplied.is_empty() {
                    let media = Path::new(&path)
                        .extension()
                        .and_then(|v| v.to_str())
                        .unwrap_or("")
                        .to_ascii_lowercase();
                    if !listed_template_path(&resources.templates.path(), &media, Path::new(&path))?
                        && !current_applied_template(&resources, Path::new(&path))?
                    {
                        return Err("현재 템플릿 목록에 없는 경로입니다.".into());
                    }
                }
                resources
                    .authoring
                    .open_path(Path::new(&path), as_template)
                    .map_err(|e| e.to_string())
            }
            "save_authoring_document" => {
                let id = string(0)?;
                let revision = args
                    .get(1)
                    .and_then(Value::as_u64)
                    .ok_or("문서 판본이 올바르지 않습니다.")?;
                let content = resources
                    .authoring
                    .dispatch("content", &json!({"session_id":id}))
                    .map_err(|e| e.to_string())?;
                if content["revision"].as_u64() != Some(revision) {
                    return Err("문서가 변경되었습니다. 다시 저장하세요.".into());
                }
                let media = content["media"].as_str().ok_or("문서 매체가 없습니다.")?;
                let stem = content["source_stem"].as_str().unwrap_or("");
                let name = if stem.is_empty() {
                    format!("새 템플릿.{media}")
                } else {
                    format!("{stem}_템플릿.{media}")
                };
                let path = save_file_dialog(
                    name,
                    vec![(media.to_ascii_uppercase(), format!("*.{media}"))],
                    media.into(),
                    owner_hwnd()?,
                )
                .map_err(|e| e.to_string())?;
                match path {
                    Some(path) => resources
                        .authoring
                        .save_to_path(id, revision, Path::new(&path))
                        .map_err(|e| e.to_string()),
                    None => Ok(Value::Null),
                }
            }
            "authoring_cases_file" => {
                let session_id = string(0)?;
                let action = string(1)?;
                resources
                    .authoring
                    .dispatch("content", &json!({"session_id":session_id}))
                    .map_err(|e| e.to_string())?;
                let filters = vec![("시험 케이스 JSON".into(), "*.json".into())];
                match action {
                    "import" => match open_file_dialog(filters, owner_hwnd()?, String::new())
                        .map_err(|e| e.to_string())?
                    {
                        Some(path) => resources
                            .authoring
                            .import_cases_path(session_id, Path::new(&path))
                            .map_err(|e| e.to_string()),
                        None => Ok(Value::Null),
                    },
                    "export" => match save_file_dialog(
                        "시험 케이스.json".into(),
                        filters,
                        "json".into(),
                        owner_hwnd()?,
                    )
                    .map_err(|e| e.to_string())?
                    {
                        Some(path) => resources
                            .authoring
                            .export_cases_path(session_id, Path::new(&path))
                            .map_err(|e| e.to_string()),
                        None => Ok(Value::Null),
                    },
                    _ => Err("시험 자료 파일 명령이 잘못되었습니다.".into()),
                }
            }
            "export_authoring_result" => {
                let session_id = string(0)?;
                let revision = args
                    .get(1)
                    .and_then(Value::as_u64)
                    .ok_or("문서가 변경되었습니다. 다시 시험하세요.")?;
                let content = resources
                    .authoring
                    .dispatch("content", &json!({"session_id":session_id}))
                    .map_err(|e| e.to_string())?;
                if content["revision"].as_u64() != Some(revision) {
                    return Err("문서가 변경되었습니다. 다시 시험하세요.".into());
                }
                let media = content["media"].as_str().ok_or("문서 매체가 없습니다.")?;
                let name = resources
                    .authoring
                    .export_result_name(session_id)
                    .map_err(|e| e.to_string())?;
                match save_file_dialog(
                    name,
                    vec![(media.to_ascii_uppercase(), format!("*.{media}"))],
                    media.into(),
                    owner_hwnd()?,
                )
                .map_err(|e| e.to_string())?
                {
                    Some(path) => resources
                        .authoring
                        .export_result_path(session_id, revision, Path::new(&path))
                        .map_err(|e| e.to_string()),
                    None => Ok(Value::Null),
                }
            }
            "import_template_file" => {
                let screen = string(0)?;
                let path = open_file_dialog(
                    vec![("HWPX·TXT 템플릿".into(), "*.hwpx;*.txt".into())],
                    owner_hwnd()?,
                    String::new(),
                )
                .map_err(|e| e.to_string())?;
                let Some(path) = path else {
                    return Ok(Value::Null);
                };
                let result: Result<String, crate::workspace_switch::GraphError> = (|| {
                    let dest = resources
                        .template_files
                        .copy_into_library(Path::new(&path))?;
                    if screen == "editor" {
                        Ok(resources.editor.adopt_imported_template(&dest)?)
                    } else {
                        Err("가져온 템플릿을 받을 화면이 아닙니다.".into())
                    }
                })(
                );
                Ok(match result {
                    Ok(name) => json!(name),
                    Err(error) => json!(format!("ERROR: {error}")),
                })
            }
            _ => Err(format!("등록되지 않은 네이티브 명령: {method}")),
        }
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

    fn register_data_sheets(
        &self,
        resources: &RuntimeResources,
        screen: &str,
        path: &Path,
        sheets: &[Value],
        confirmation: Option<&Value>,
    ) -> Result<Value, String> {
        if !matches!(screen, "job" | "editor") || path.as_os_str().is_empty() {
            return Err("데이터를 가져올 화면과 파일을 확인하세요.".into());
        }
        let basis = match confirmation {
            None | Some(Value::Null) => None,
            Some(Value::Object(map)) if map.len() == 1 => map.get("basis").and_then(Value::as_str),
            _ => return Err("데이터를 가져올 화면과 파일을 확인하세요.".into()),
        };
        if confirmation.is_some_and(|value| !value.is_null()) && basis.is_none() {
            return Err("데이터를 가져올 화면과 파일을 확인하세요.".into());
        }
        if sheets.is_empty()
            || sheets
                .iter()
                .any(|name| name.as_str().is_none_or(str::is_empty))
        {
            return Err("가져올 시트를 선택하세요.".into());
        }
        let names = hwpx_filler::data_excel::sheet_overview(path)
            .map_err(|e| e.to_string())?
            .into_iter()
            .map(|(name, _, _)| name)
            .collect::<Vec<_>>();
        let requested = sheets.iter().filter_map(Value::as_str).collect::<Vec<_>>();
        if requested
            .iter()
            .any(|name| !names.iter().any(|known| known == name))
        {
            return Err("시트를 찾을 수 없습니다. 파일을 다시 선택하세요.".into());
        }
        let selected = names
            .into_iter()
            .filter(|name| requested.contains(&name.as_str()))
            .collect::<Vec<_>>();
        let path_text = path.to_string_lossy();
        let same = resources
            .datasets
            .find_identity(&path_text, selected.first().map(String::as_str))
            .map_err(|e| e.to_string())?;
        let mut rows = Vec::new();
        for name in &selected {
            let checked = (|| -> Result<(), String> {
                let mut source = if let Some((_, item)) = &same {
                    if hwpx_filler::dataset_reference::reference_sheets(item)
                        .map_err(|e| e.to_string())?
                        .iter()
                        .any(|sheet| sheet == name)
                    {
                        let reference =
                            hwpx_filler::dataset_reference::reference_for_sheet(item, Some(name))
                                .map_err(|e| e.to_string())?;
                        crate::nara_source::source_from_pool_reference_live(&reference)
                            .map_err(|e| e.to_string())?
                    } else {
                        hwpx_filler::data_factory::source_for_path(
                            path,
                            Some(name),
                            item.opts
                                .get("header_row")
                                .and_then(Value::as_u64)
                                .unwrap_or(1) as usize,
                        )
                        .map_err(|e| e.to_string())?
                    }
                } else {
                    hwpx_filler::data_factory::source_for_path(path, Some(name), 1)
                        .map_err(|e| e.to_string())?
                };
                if source.records().map_err(|e| e.to_string())?.is_empty() {
                    return Err("데이터에 행이 없습니다.".into());
                }
                if let Some((key, item)) = &same {
                    let row =
                        hwpx_filler::dataset_pool::DatasetPoolRow::from_item(key, item, false)
                            .map_err(|e| e.to_string())?;
                    let reason = row.select_block_reason();
                    if !reason.is_empty() {
                        return Err(reason);
                    }
                }
                Ok(())
            })();
            rows.push(json!({"name":name,"error":checked.err().unwrap_or_default()}));
        }
        let errors = rows
            .iter()
            .filter_map(|row| {
                let error = row["error"].as_str().filter(|error| !error.is_empty())?;
                Some(format!("{}: {error}", row["name"].as_str().unwrap_or("")))
            })
            .collect::<Vec<_>>();
        if !errors.is_empty() {
            return Ok(json!({"sheets":rows,"mount":null,"error":errors.join("\n")}));
        }
        let name = same.as_ref().map_or_else(
            || {
                path.file_stem()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned()
            },
            |(_, item)| item.name.clone(),
        );
        let mut request =
            json!({"name":name,"path":path_text,"sheet":selected[0],"sheets":selected});
        if let Some(basis) = basis {
            request["confirm"] = json!(true);
            request["basis"] = json!(basis);
        }
        let registered = resources
            .pool
            .dispatch("register_excel", &request)
            .map_err(|e| e.to_string())?;
        if registered["needs_confirm"] == true {
            let mut response = json!({"sheets":[],"mount":null,"error":""});
            response
                .as_object_mut()
                .unwrap()
                .extend(registered.as_object().cloned().unwrap_or_default());
            return Ok(response);
        }
        if registered["ok"] != true {
            return Ok(json!({"sheets":rows,"mount":null,"error":registered["error"]}));
        }
        let (key, item) = resources
            .datasets
            .find_identity(&path_text, Some(&selected[0]))
            .map_err(|e| e.to_string())?
            .ok_or("등록 데이터를 찾을 수 없습니다. 다시 가져오세요.")?;
        for row in &mut rows {
            row["key"] = json!(key);
        }
        let mounted = (|| -> Result<Value, String> {
            match screen {
                "job" => resources
                    .job
                    .load_pool(&key, Some(&selected[0]))
                    .map_err(|e| e.to_string())?,
                _ => {
                    let result = resources
                        .editor
                        .dispatch("use_pool_data", &json!({"key":key}))
                        .map_err(|e| e.to_string())?;
                    if result["ok"] != true {
                        return Err(result["error"]
                            .as_str()
                            .unwrap_or("등록 데이터를 활성화하지 못했습니다.")
                            .to_owned());
                    }
                }
            }
            let mut descriptor =
                self.mount_data_descriptor(resources, screen, path, &selected[0])?;
            descriptor["label"] = json!(format!("등록 데이터: {}", item.name));
            Ok(descriptor)
        })();
        match mounted {
            Ok(mount) => Ok(json!({"sheets":rows,"mount":mount,"error":""})),
            Err(error) => Ok(json!({"sheets":rows,"mount":null,"error":error})),
        }
    }

    fn mount_data_descriptor(
        &self,
        resources: &RuntimeResources,
        screen: &str,
        path: &Path,
        sheet: &str,
    ) -> Result<Value, String> {
        let rows = if screen == "job" {
            resources
                .job
                .data()
                .map_err(|e| e.to_string())?
                .records
                .len()
        } else {
            let mut source = hwpx_filler::data_factory::source_for_path(path, Some(sheet), 1)
                .map_err(|e| e.to_string())?;
            source.records().map_err(|e| e.to_string())?.len()
        };
        Ok(
            json!({"label":format!("파일: {}",path.file_name().unwrap_or_default().to_string_lossy()),
            "path":path.to_string_lossy(),"sheet":sheet,"rows":rows}),
        )
    }
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
