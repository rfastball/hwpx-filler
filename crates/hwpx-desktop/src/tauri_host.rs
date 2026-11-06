//! Tauri shell inputs: verified assets and a same-origin navigation boundary.
//! The caller is the fully assembled controller graph; no network asset fallback exists.

use crate::boot_budget::BootTiming;
use crate::live_graph::LiveGraph;
use crate::shell_settings::{ShellSettings, WindowGeometry};
use crate::web_assets::WebAssets;
use serde_json::{Map, Value, json};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};
use tauri::webview::PageLoadEvent;
use tauri::{
    Context, LogicalSize, Manager, PhysicalSize, State, Url, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder, Wry,
};

pub trait ProductCaller: Send + Sync + 'static {
    fn call(
        &self,
        method: &str,
        args: &[Value],
        window: &WebviewWindow<Wry>,
    ) -> Result<Value, String>;
}

type NativeMethod =
    dyn Fn(&str, &[Value], &WebviewWindow<Wry>) -> Result<Value, String> + Send + Sync;

pub struct LiveCaller<R> {
    graph: Arc<LiveGraph<R>>,
    native: Arc<NativeMethod>,
}

impl<R: Send + Sync + 'static> LiveCaller<R> {
    pub fn new(
        graph: Arc<LiveGraph<R>>,
        native: impl Fn(&str, &[Value], &WebviewWindow<Wry>) -> Result<Value, String>
        + Send
        + Sync
        + 'static,
    ) -> Self {
        Self {
            graph,
            native: Arc::new(native),
        }
    }

    fn common_call(&self, method: &str, args: &[Value]) -> Option<Result<Value, String>> {
        crate::host_common::call(&self.graph, method, args)
    }
}

impl<R: Send + Sync + 'static> ProductCaller for LiveCaller<R> {
    fn call(
        &self,
        method: &str,
        args: &[Value],
        window: &WebviewWindow<Wry>,
    ) -> Result<Value, String> {
        if let Some(result) = self.common_call(method, args) {
            result
        } else {
            (self.native)(method, args, window)
        }
    }
}

struct HostState {
    caller: Arc<dyn ProductCaller>,
    alert: Arc<dyn Fn(&str) + Send + Sync>,
    settings: Arc<ShellSettings>,
    geometry: Mutex<WindowGeometry>,
    geometry_revision: AtomicU64,
    geometry_stop: AtomicBool,
    boot_started: AtomicBool,
    shown: Mutex<bool>,
    close_authorized: AtomicBool,
    close_prompt_open: AtomicBool,
    selftest: Option<Arc<crate::native_selftest::NativeSelftest>>,
    live_token: Option<String>,
}

#[tauri::command]
async fn product_call(
    state: State<'_, Arc<HostState>>,
    window: WebviewWindow<Wry>,
    method: String,
    args: Vec<Value>,
) -> Result<Value, String> {
    let host = state.inner().clone();
    if method == "selftest_claim" || method == "selftest_host_op" {
        let selftest = host
            .selftest
            .as_ref()
            .ok_or("selftest capability unavailable")?;
        if !selftest.web_capability() {
            return Err("selftest capability unavailable".into());
        }
        return match method.as_str() {
            "selftest_claim" if args.len() == 1 => Ok(selftest.claim(&args[0])),
            "selftest_host_op" if args.len() == 2 => Ok(selftest.host_op(
                args[0].as_str().ok_or("selftest op must be a string")?,
                &args[1],
                &window,
                &host.settings,
            )),
            _ => Err("selftest argument shape invalid".into()),
        };
    }
    crate::native_methods::validate_host_call(&method, &args)?;
    tauri::async_runtime::spawn_blocking(move || match method.as_str() {
        "confirm_window_close" => {
            host.close_authorized.store(true, Ordering::SeqCst);
            host.close_prompt_open.store(false, Ordering::SeqCst);
            if let Err(error) = window.close() {
                host.close_authorized.store(false, Ordering::SeqCst);
                return Err(error.to_string());
            }
            Ok(json!(true))
        }
        "cancel_window_close" => {
            host.close_prompt_open.store(false, Ordering::SeqCst);
            Ok(json!(true))
        }
        _ => host.caller.call(&method, &args, &window),
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn selftest_finish(
    state: State<'_, Arc<HostState>>,
    window: WebviewWindow<Wry>,
    response: Value,
) -> Result<(), String> {
    let host = state.inner();
    let selftest = host
        .selftest
        .as_ref()
        .ok_or("selftest capability unavailable")?;
    let result = selftest.finish(&response);
    host.close_authorized.store(true, Ordering::SeqCst);
    let closed = window.close().map_err(|error| error.to_string());
    result?;
    closed
}

#[tauri::command]
fn live101_queue_dialog(
    state: State<'_, Arc<HostState>>,
    token: String,
    kind: String,
    path: Option<String>,
) -> Result<(), String> {
    if state.live_token.as_deref() != Some(token.as_str()) {
        return Err("live dialog capability unavailable".into());
    }
    crate::dialogs::queue_live_answer(&kind, path.as_deref()).map_err(|error| error.to_string())
}

/// Start from already verified, in-memory assets. No loopback server or filesystem asset fallback.
pub struct ShellBoot {
    pub selftest: Option<Arc<crate::native_selftest::NativeSelftest>>,
    pub timing: BootTiming,
    pub live_debug: Option<(u16, String)>,
}

pub fn run_shell(
    assets: WebAssets,
    caller: Arc<dyn ProductCaller>,
    alert: Arc<dyn Fn(&str) + Send + Sync>,
    window_binding: Arc<OnceLock<WebviewWindow<Wry>>>,
    expected_resources: PathBuf,
    _instance: ShellInstance,
    boot: ShellBoot,
) -> Result<(), String> {
    #[cfg(not(windows))]
    return Err("문서나르미 데스크톱 셸은 Windows에서만 실행됩니다.".into());
    let ShellBoot {
        selftest,
        timing,
        live_debug,
    } = boot;
    let live_token = live_debug.as_ref().map(|(_, token)| token.clone());
    let locations = crate::locations::Locations::from_env().map_err(str::to_owned)?;
    let profile = prepare_webview_profile(locations.home(), &alert)?;
    let settings = Arc::new(ShellSettings::new(locations.global_settings(), {
        let alert = alert.clone();
        move |message| alert(message)
    }));
    let saved = settings
        .load_window_geometry()
        .map_err(|error| error.to_string())?;
    let saved = saved.filter(|geometry| {
        let visible = virtual_screen_bounds().is_none_or(|bounds| geometry.visible_in(bounds));
        if !visible {
            alert("저장된 창 위치가 현재 화면 밖이라 기본 위치로 복원합니다");
        }
        visible
    });
    let initial = saved.clone().unwrap_or(WindowGeometry {
        x: 0,
        y: 0,
        width: 1440,
        height: 900,
        maximized: false,
    });
    let state = Arc::new(HostState {
        caller,
        alert,
        settings,
        geometry: Mutex::new(initial),
        geometry_revision: AtomicU64::new(0),
        geometry_stop: AtomicBool::new(false),
        boot_started: AtomicBool::new(false),
        shown: Mutex::new(false),
        close_authorized: AtomicBool::new(false),
        close_prompt_open: AtomicBool::new(false),
        selftest,
        live_token,
    });
    let context = verified_context(assets);
    let setup_state = state.clone();
    let boot_timing = timing;
    tauri::Builder::default()
        .manage(state.clone())
        .invoke_handler(tauri::generate_handler![product_call, selftest_finish, live101_queue_dialog])
        .setup(move |app| {
            let actual = app.path().resource_dir()?;
            let actual_display = crate::single_instance::normalize_windows_path(&actual)?;
            let expected_display =
                crate::single_instance::normalize_windows_path(&expected_resources)?;
            if !actual_display.eq_ignore_ascii_case(&expected_display) {
                return Err(
                    format!("bundle resource directory changed: {}", actual.display()).into(),
                );
            }
            let mut builder =
                WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                    .title("문서나르미")
                    .inner_size(
                        saved.as_ref().map_or(1440.0, |item| item.width as f64),
                        saved.as_ref().map_or(900.0, |item| item.height as f64),
                    )
                    .min_inner_size(720.0, 560.0)
                    .visible(false)
                    .data_directory(profile.clone())
                    .on_navigation(is_app_navigation)
                    .on_page_load({
                        let state = setup_state.clone();
                        let completed_runtime = boot_timing.runtime_version.clone();
                        move |webview, payload| {
                            if payload.event() != PageLoadEvent::Finished
                                || state.boot_started.swap(true, Ordering::SeqCst)
                            {
                                return;
                            }
                            if let Err(error) = state.settings.save_boot_completed(&completed_runtime) {
                                (state.alert)(&format!(
                                    "부팅 완료 기록 저장 실패 — 다음 부팅도 넓은 예산: {error:?}"
                                ));
                            }
                            let Some(window) = webview.app_handle().get_webview_window("main")
                            else {
                                (state.alert)("기본 창을 찾지 못했습니다.");
                                return;
                            };
                            let state = state.clone();
                            tauri::async_runtime::spawn(async move {
                                apply_preferences_then_show(&window, &state).await;
                                if let Some(selftest) = state.selftest.as_ref() {
                                    match selftest.driver_script() {
                                        Ok(script) => {
                                            if let Err(error) = window.eval(&script) {
                                                (state.alert)(&format!(
                                                    "WebView2 selftest 시작 실패: {error}"
                                                ));
                                            }
                                        }
                                        Err(error) => (state.alert)(&format!(
                                            "WebView2 selftest 구성 실패: {error}"
                                        )),
                                    }
                                }
                            });
                        }
                    });
            if let Some((port, token)) = live_debug.as_ref() {
                builder = builder.additional_browser_args(&format!(
                    "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection \
                     --remote-debugging-address=127.0.0.1 --remote-debugging-port={port}"
                ));
                builder = builder.initialization_script(format!(
                    "Object.defineProperty(window,'__hwpxLive101',{{value:{}}});",
                    serde_json::to_string(token)?
                ));
            }
            if setup_state
                .selftest
                .as_ref()
                .is_some_and(|selftest| selftest.web_capability())
            {
                builder = builder.initialization_script(
                    "Object.defineProperty(Object.getPrototypeOf(window), '__HWPX_NATIVE_SELFTEST__', {value:true});",
                );
            }
            if let Some(geometry) = saved.as_ref() {
                builder = builder
                    .position(geometry.x as f64, geometry.y as f64)
                    .maximized(geometry.maximized);
            }
            let fallback_started = Instant::now();
            let window = builder.build()?;
            if saved.as_ref().is_some_and(|item| item.maximized) {
                window.unmaximize()?;
            }
            configure_outer_size(
                &window,
                saved.as_ref().map_or(1440, |item| item.width as u32),
                saved.as_ref().map_or(900, |item| item.height as u32),
            )?;
            if saved.as_ref().is_some_and(|item| item.maximized) {
                window.maximize()?;
            }
            window_binding
                .set(window.clone())
                .map_err(|_| "main window was already bound")?;
            let fallback_state = setup_state.clone();
            let fallback_budget = boot_timing.fallback_seconds;
            let fallback_reason = boot_timing.reason.clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_secs(fallback_budget).saturating_sub(fallback_started.elapsed()));
                if fallback_state.geometry_stop.load(Ordering::SeqCst)
                    || fallback_state.shown.lock().is_ok_and(|shown| *shown)
                {
                    return;
                }
                if show_once(&window, &fallback_state).is_ok() {
                    let message = if fallback_state.boot_started.load(Ordering::SeqCst) {
                        "loaded 후 표시 매달림. 폴백으로 창 표시(테마 미주입 가능)"
                    } else {
                        "loaded 미발화. 폴백으로 창 표시(테마 미주입 가능)"
                    };
                    (fallback_state.alert)(&format!(
                        "{message} [예산 {fallback_budget}s · {fallback_reason}]"
                    ));
                }
            });
            let geometry_state = setup_state.clone();
            std::thread::spawn(move || {
                let mut saved_revision = 0;
                while !geometry_state.geometry_stop.load(Ordering::SeqCst) {
                    std::thread::sleep(Duration::from_millis(250));
                    let revision = geometry_state.geometry_revision.load(Ordering::SeqCst);
                    if revision != saved_revision
                        && !geometry_state.geometry_stop.load(Ordering::SeqCst)
                    {
                        persist_geometry(&geometry_state);
                        saved_revision = revision;
                    }
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(
                event,
                tauri::WindowEvent::Moved(_) | tauri::WindowEvent::Resized(_)
            ) {
                let state = window.state::<Arc<HostState>>().inner().clone();
                record_geometry(window, &state);
            }
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.state::<Arc<HostState>>().inner().clone();
                state.geometry_stop.store(true, Ordering::SeqCst);
                persist_geometry(&state);
            }
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let state = window.state::<Arc<HostState>>().inner().clone();
                if state.close_authorized.swap(false, Ordering::SeqCst) {
                    return;
                }
                api.prevent_close();
                if state.close_prompt_open.swap(true, Ordering::SeqCst) {
                    return;
                }
                let Some(webview) = window.app_handle().get_webview_window("main") else {
                    state.close_prompt_open.store(false, Ordering::SeqCst);
                    return;
                };
                tauri::async_runtime::spawn(async move {
                    let caller = state.caller.clone();
                    let check_window = webview.clone();
                    let guard = tauri::async_runtime::spawn_blocking(move || {
                        let state = caller.call("close_guard_state", &[], &check_window)?;
                        let flush = caller.call("close_flush_required", &[], &check_window)?;
                        Ok::<_, String>((state, flush))
                    })
                    .await;
                    match guard {
                        Ok(Ok((Value::Object(body), Value::Bool(false))))
                            if body.get("armed") == Some(&Value::Bool(false)) =>
                        {
                            state.close_authorized.store(true, Ordering::SeqCst);
                            if let Err(error) = webview.close() {
                                state.close_authorized.store(false, Ordering::SeqCst);
                                (state.alert)(&format!("창을 닫지 못했습니다: {error}"));
                            }
                        }
                        Ok(Ok((Value::Object(body), Value::Bool(_)))) => {
                            let alert = state.alert.clone();
                            let api = crate::product_transport::TauriProductApi::new(
                                webview,
                                move |message| alert(message),
                            );
                            let outcome = api.close_request(&body).await;
                            if !outcome.ok {
                                state.close_prompt_open.store(false, Ordering::SeqCst);
                                (state.alert)(&format!(
                                    "닫기 확인창 전달 실패: {}",
                                    outcome.detail
                                ));
                            }
                        }
                        _ => {
                            state.close_prompt_open.store(false, Ordering::SeqCst);
                            let alert = state.alert.clone();
                            let api = crate::product_transport::TauriProductApi::new(
                                webview,
                                move |message| alert(message),
                            );
                            let _ = api.notice("창 닫기 상태를 확인하지 못했습니다.").await;
                        }
                    }
                });
            }
        })
        .run(context)
        .map_err(|error| error.to_string())?;
    if let Some(selftest) = state.selftest.as_ref()
        && !selftest.succeeded()
    {
        return Err("WebView2 selftest failed".into());
    }
    Ok(())
}

async fn apply_preferences_then_show(window: &WebviewWindow<Wry>, state: &HostState) {
    let result = async {
        let api = crate::product_transport::TauriProductApi::new(window.clone(), {
            let alert = state.alert.clone();
            move |message| alert(message)
        });
        api.describe(Some(&["preferences"]))
            .await
            .map_err(|error| error.to_string())?;
        let mut preferences = Map::new();
        preferences.insert(
            "font_scale".into(),
            json!(
                state
                    .settings
                    .load_font_scale()
                    .map_err(|error| error.to_string())?
            ),
        );
        preferences.insert(
            "master_width".into(),
            json!(
                state
                    .settings
                    .load_master_width()
                    .map_err(|error| error.to_string())?
            ),
        );
        let (outline, properties) = state
            .settings
            .load_authoring_widths()
            .map_err(|error| error.to_string())?;
        let mut widths = Map::new();
        if let Some(outline) = outline {
            widths.insert("outline".into(), json!(outline));
        }
        if let Some(properties) = properties {
            widths.insert("properties".into(), json!(properties));
        }
        preferences.insert("authoring_widths".into(), Value::Object(widths));
        let theme = state
            .settings
            .load_theme()
            .map_err(|error| error.to_string())?;
        let outcome = api.preferences(&preferences, Some(&theme)).await;
        if !outcome.ok() {
            return Err(outcome
                .failure_text()
                .unwrap_or_else(|| "기본 설정을 적용하지 못했습니다".into()));
        }
        Ok::<(), String>(())
    }
    .await;
    if let Err(error) = show_once(window, state) {
        (state.alert)(&format!("창 표시(show) 실패: {error}"));
    }
    if let Err(error) = result {
        (state.alert)(&format!("테마 주입 실패: {error}"));
    }
}

fn show_once(window: &WebviewWindow<Wry>, state: &HostState) -> Result<(), String> {
    let mut shown = state.shown.lock().map_err(|error| error.to_string())?;
    if !*shown {
        window.show().map_err(|error| error.to_string())?;
        *shown = true;
    }
    Ok(())
}

fn record_geometry(window: &tauri::Window<Wry>, state: &Arc<HostState>) {
    let Ok(maximized) = window.is_maximized() else {
        return;
    };
    let mut geometry = match state.geometry.lock() {
        Ok(geometry) => geometry,
        Err(_) => return,
    };
    geometry.maximized = maximized;
    if !maximized {
        let (Ok(position), Ok(size), Ok(scale)) = (
            window.outer_position(),
            window.outer_size(),
            window.scale_factor(),
        ) else {
            return;
        };
        let position = position.to_logical::<f64>(scale);
        let size = size.to_logical::<f64>(scale);
        geometry.x = position.x.round() as i64;
        geometry.y = position.y.round() as i64;
        geometry.width = (size.width.round() as i64).max(760);
        geometry.height = (size.height.round() as i64).max(600);
    }
    drop(geometry);
    state.geometry_revision.fetch_add(1, Ordering::SeqCst);
}

/// Tauri sizes the content area; the previous Windows shell persisted the
/// decorated window frame. Derive the content size from the actual frame.
pub(crate) fn set_outer_logical_size(
    window: &WebviewWindow<Wry>,
    width: u32,
    height: u32,
) -> Result<(), String> {
    let scale = window.scale_factor().map_err(|error| error.to_string())?;
    let outer = window.outer_size().map_err(|error| error.to_string())?;
    let inner = window.inner_size().map_err(|error| error.to_string())?;
    let frame_width = outer.width.saturating_sub(inner.width);
    let frame_height = outer.height.saturating_sub(inner.height);
    let requested = LogicalSize::new(width as f64, height as f64).to_physical::<u32>(scale);
    window
        .set_size(PhysicalSize::new(
            requested.width.saturating_sub(frame_width).max(1),
            requested.height.saturating_sub(frame_height).max(1),
        ))
        .map_err(|error| error.to_string())
}

fn configure_outer_size(
    window: &WebviewWindow<Wry>,
    width: u32,
    height: u32,
) -> Result<(), String> {
    let scale = window.scale_factor().map_err(|error| error.to_string())?;
    let outer = window.outer_size().map_err(|error| error.to_string())?;
    let inner = window.inner_size().map_err(|error| error.to_string())?;
    let minimum = LogicalSize::new(760.0, 600.0).to_physical::<u32>(scale);
    window
        .set_min_size(Some(PhysicalSize::new(
            minimum
                .width
                .saturating_sub(outer.width.saturating_sub(inner.width)),
            minimum
                .height
                .saturating_sub(outer.height.saturating_sub(inner.height)),
        )))
        .map_err(|error| error.to_string())?;
    set_outer_logical_size(window, width, height)
}

fn persist_geometry(state: &HostState) {
    let Ok(geometry) = state.geometry.lock() else {
        return;
    };
    if let Err(error) = state.settings.save_window_geometry(&geometry) {
        (state.alert)(&format!(
            "창 위치 저장 실패 — 현재 실행은 계속합니다: {error}"
        ));
    }
}

#[cfg(windows)]
fn virtual_screen_bounds() -> Option<(i64, i64, i64, i64)> {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        GetSystemMetrics, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN, SM_XVIRTUALSCREEN,
        SM_YVIRTUALSCREEN,
    };
    Some(unsafe {
        (
            GetSystemMetrics(SM_XVIRTUALSCREEN) as i64,
            GetSystemMetrics(SM_YVIRTUALSCREEN) as i64,
            GetSystemMetrics(SM_CXVIRTUALSCREEN) as i64,
            GetSystemMetrics(SM_CYVIRTUALSCREEN) as i64,
        )
    })
}

#[cfg(not(windows))]
fn virtual_screen_bounds() -> Option<(i64, i64, i64, i64)> {
    None
}

#[cfg(windows)]
pub type ShellInstance = crate::single_instance::InstanceGuard;
#[cfg(not(windows))]
pub type ShellInstance = ();

fn prepare_webview_profile(
    home: &std::path::Path,
    alert: &Arc<dyn Fn(&str) + Send + Sync>,
) -> Result<PathBuf, String> {
    let root = home.join("webview");
    if let Err(error) = std::fs::remove_dir_all(&root)
        && error.kind() != std::io::ErrorKind::NotFound
    {
        alert(&format!(
            "WebView2 프로필 청소 실패 — 스테일 프로필 재사용 가능(구자산 서빙): {error}"
        ));
    }
    let profile = root.join("profile");
    std::fs::create_dir_all(&profile).map_err(|e| e.to_string())?;
    std::fs::canonicalize(&profile).map_err(|e| e.to_string())
}

pub fn verified_context(assets: WebAssets) -> Context<Wry> {
    let mut context = tauri::generate_context!();
    context.set_assets(Box::new(assets));
    context
}

pub fn is_app_navigation(url: &Url) -> bool {
    (url.scheme() == "http" && url.host_str() == Some("tauri.localhost"))
        && url.port().is_none()
        && url.username().is_empty()
        && url.password().is_none()
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{LiveCaller, is_app_navigation, prepare_webview_profile};
    use crate::live_graph::LiveGraph;
    use crate::locations::Locations;
    use crate::workspace_switch::{GraphError, ScreenController, WorkspaceGraph, WorkspaceSwitch};
    use serde_json::{Value, json};
    use std::fs;
    use std::path::Path;
    use std::sync::Arc;
    #[cfg(windows)]
    use std::sync::Mutex;
    use tauri::Url;

    struct Job;
    impl ScreenController for Job {
        fn initial(&self) -> Result<Value, GraphError> {
            Ok(json!({"ready":true}))
        }
        fn dispatch(&self, action: &str, _: &Value) -> Result<Value, GraphError> {
            if action == "recover_record_issue" {
                return Err(Box::new(crate::job_controller::JobControllerError {
                    message: "현재 데이터 확인 결과가 없습니다. 다시 확인해 주세요.".into(),
                    code: None,
                }));
            }
            Ok(json!({"ok":true}))
        }
        fn close_guard_reason(&self) -> Result<Option<String>, GraphError> {
            Ok(None)
        }
    }

    #[test]
    fn webview_profile_first_boot_and_restart_purge_stale_layouts() {
        let home =
            std::env::temp_dir().join(format!("hwpx-webview-profile-{}", uuid::Uuid::new_v4()));
        let alert: Arc<dyn Fn(&str) + Send + Sync> =
            Arc::new(|message| panic!("unexpected alert: {message}"));

        let profile = prepare_webview_profile(&home, &alert).unwrap();
        assert_eq!(
            profile,
            fs::canonicalize(home.join("webview/profile")).unwrap()
        );
        assert!(profile.is_dir());

        fs::create_dir_all(profile.join("Default/Cache")).unwrap();
        fs::write(profile.join("Default/Cache/stale.js"), "old asset").unwrap();
        fs::create_dir_all(home.join("webview/EBWebView/Default")).unwrap();
        fs::create_dir_all(home.join("webview/profile-99999")).unwrap();

        let restarted = prepare_webview_profile(&home, &alert).unwrap();
        assert_eq!(restarted, profile);
        assert!(fs::read_dir(&restarted).unwrap().next().is_none());
        assert!(!home.join("webview/EBWebView").exists());
        assert!(!home.join("webview/profile-99999").exists());
        fs::remove_dir_all(home).unwrap();
    }

    #[cfg(windows)]
    #[test]
    fn webview_profile_alerts_and_boots_when_locked_profile_cannot_be_purged() {
        use std::os::windows::fs::OpenOptionsExt;

        let home =
            std::env::temp_dir().join(format!("hwpx-webview-profile-{}", uuid::Uuid::new_v4()));
        let locked_path = home.join("webview/profile/locked");
        fs::create_dir_all(locked_path.parent().unwrap()).unwrap();
        fs::write(&locked_path, "locked").unwrap();
        let locked = fs::OpenOptions::new()
            .read(true)
            .write(true)
            .share_mode(0)
            .open(&locked_path)
            .unwrap();
        let alerts = Arc::new(Mutex::new(Vec::new()));
        let alert: Arc<dyn Fn(&str) + Send + Sync> = {
            let alerts = alerts.clone();
            Arc::new(move |message| alerts.lock().unwrap().push(message.to_owned()))
        };

        let profile = prepare_webview_profile(&home, &alert).unwrap();
        assert!(profile.is_dir());
        assert!(
            alerts
                .lock()
                .unwrap()
                .iter()
                .any(|message| message.contains("프로필 청소 실패"))
        );

        drop(locked);
        fs::remove_dir_all(home).unwrap();
    }

    #[test]
    fn ipc_common_methods_validate_arity_and_registry_before_controller() {
        let switch = WorkspaceSwitch::new(
            Locations::new(Path::new("C:/User"), None),
            |_, _| Ok(None),
            |home, _, token| {
                Ok(WorkspaceGraph::new(
                    home.map(Path::to_path_buf),
                    vec![("job".into(), Arc::new(Job))],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let caller = LiveCaller::new(Arc::new(LiveGraph::new(switch)), |_, _, _| {
            Err("unknown method".into())
        });
        assert_eq!(
            caller
                .common_call("initial", &[json!("job")])
                .unwrap()
                .unwrap(),
            json!({"ready":true})
        );
        assert!(caller.common_call("initial", &[]).unwrap().is_err());
        assert!(
            caller
                .common_call("initial", &[json!("job"), json!("extra")])
                .unwrap()
                .is_err()
        );
        assert_eq!(
            caller
                .common_call(
                    "dispatch",
                    &[json!("job"), json!("artifact_close"), json!([])]
                )
                .unwrap()
                .unwrap()["__hwpx_dispatch_rejection_v1__"]["name"],
            "ValueError"
        );
        assert_eq!(
            caller
                .common_call(
                    "dispatch",
                    &[json!("job"), json!("not_registered"), json!({})]
                )
                .unwrap()
                .unwrap(),
            json!({"__hwpx_dispatch_rejection_v1__": {
                "name":"ValueError",
                "message":"등록되지 않은 'job' 액션: 'not_registered'"
            }})
        );
        assert_eq!(
            caller
                .common_call(
                    "dispatch",
                    &[
                        json!("job"),
                        json!("recover_record_issue"),
                        json!({"target":{}})
                    ]
                )
                .unwrap()
                .unwrap(),
            json!({"__hwpx_dispatch_rejection_v1__": {
                "name":"ValueError",
                "message":"현재 데이터 확인 결과가 없습니다. 다시 확인해 주세요."
            }})
        );
        assert_eq!(
            caller
                .common_call("close_flush_required", &[])
                .unwrap()
                .unwrap(),
            json!(false)
        );
    }

    #[test]
    fn shell_navigation_keeps_main_frame_on_app_origin() {
        assert!(is_app_navigation(
            &Url::parse("http://tauri.localhost/rhwp/studio/index.html").unwrap()
        ));
        for url in [
            "https://example.com/",
            "https://tauri.localhost/",
            "tauri://localhost/",
            "http://tauri.localhost.evil.example/",
            "http://tauri.localhost:10080/",
            "file:///C:/secret.txt",
            "javascript:alert(1)",
        ] {
            assert!(!is_app_navigation(&Url::parse(url).unwrap()), "{url}");
        }
    }
}
