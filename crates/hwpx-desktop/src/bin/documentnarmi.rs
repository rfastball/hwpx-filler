//! Native Windows shell over the verified web artifact and one active product graph.
#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

use hwpx_desktop::boot_budget::{self, BootTiming};
use hwpx_desktop::generation_gate::GenerationGate;
use hwpx_desktop::live_graph::LiveGraph;
use hwpx_desktop::locations::Locations;
use hwpx_desktop::native_methods::NativeMethods;
use hwpx_desktop::native_selftest::NativeSelftest;
use hwpx_desktop::onboarding_controller::OnboardingController;
use hwpx_desktop::product_api::ApiError;
use hwpx_desktop::product_transport::TauriProductApi;
use hwpx_desktop::tauri_host::{LiveCaller, ShellBoot, run_shell};
use hwpx_desktop::tutorial_workspace::{ORIGINALS, TutorialWorkspace};
use hwpx_desktop::web_assets::WebAssets;
use hwpx_desktop::workspace_runtime::RuntimeBuilder;
use hwpx_desktop::workspace_switch::{PushResult, WorkspaceSwitch};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant};
use tauri::{WebviewWindow, Wry};

fn main() {
    if let Err(error) = start() {
        eprintln!("문서나르미 시작 실패: {error}");
        let selftest = std::env::args().skip(1).any(|arg| arg == "--selftest");
        if selftest {
            if let Err(write_error) = write_startup_selftest_error(&error.to_string()) {
                eprintln!("WebView2 selftest 시작 오류 기록 실패: {write_error}");
            }
        } else if !std::env::args()
            .skip(1)
            .any(|arg| arg == "--selfcheck" || arg == "--live101")
        {
            startup_error_dialog(&error.to_string());
        }
        std::process::exit(1);
    }
}

fn write_startup_selftest_error(detail: &str) -> std::io::Result<()> {
    let Some(path) = std::env::var_os("HWPX_SELFTEST_OUT").map(PathBuf::from) else {
        return Ok(());
    };
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        std::fs::create_dir_all(parent)?;
    }
    let mut output = match std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
    {
        Ok(output) => output,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => return Ok(()),
        Err(error) => return Err(error),
    };
    let payload = serde_json::json!({"error":format!("문서나르미 시작 실패: {detail}")});
    output.write_all(payload.to_string().as_bytes())?;
    output.sync_all()
}

#[cfg(windows)]
fn startup_error_dialog(detail: &str) {
    use windows_sys::Win32::UI::WindowsAndMessaging::{MB_ICONERROR, MB_OK, MessageBoxW};
    let body = format!("문서나르미 시작 실패: {detail}")
        .encode_utf16()
        .chain(Some(0))
        .collect::<Vec<_>>();
    let title = "문서나르미"
        .encode_utf16()
        .chain(Some(0))
        .collect::<Vec<_>>();
    unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            body.as_ptr(),
            title.as_ptr(),
            MB_OK | MB_ICONERROR,
        );
    }
}

#[cfg(not(windows))]
fn startup_error_dialog(_: &str) {}

type StartError = Box<dyn std::error::Error + Send + Sync>;
type Alert = Arc<dyn Fn(&str) + Send + Sync>;

fn start() -> Result<(), StartError> {
    let process_started = Instant::now();
    let resources = std::env::current_exe()?
        .parent()
        .ok_or("실행 경로가 없습니다.")?
        .to_path_buf();
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args == ["--selfcheck"] {
        return run_selfcheck(&resources);
    }
    let selftest_mode = args.first().is_some_and(|arg| arg == "--selftest");
    let live101_mode = args.first().is_some_and(|arg| arg == "--live101");
    let live_debug = live_debug_from_env(live101_mode)?;
    let asset_args = if selftest_mode || live101_mode {
        &args[1..]
    } else {
        &args[..]
    };
    let (artifact_root, tutorial) = asset_paths(&resources, asset_args)?;
    require_tutorial(&tutorial)?;
    let assets = WebAssets::frozen(&artifact_root)?;
    let selftest = selftest_mode
        .then(|| NativeSelftest::from_env(&assets).map(Arc::new))
        .transpose()?;
    let locations = Locations::from_env()?;
    if live101_mode {
        hwpx_desktop::dialogs::enable_live_answers(locations.home())?;
    }
    #[cfg(windows)]
    let instance = match hwpx_desktop::single_instance::acquire(locations.home())? {
        hwpx_desktop::single_instance::Acquisition::Primary(guard) => guard,
        hwpx_desktop::single_instance::Acquisition::Existing => {
            hwpx_desktop::single_instance::focus_existing("문서나르미");
            return Ok(());
        }
    };
    #[cfg(not(windows))]
    let instance = ();
    let alert = shell_alert(&locations);
    let timing = boot_timing(&locations, &alert)?;
    if let Some(selftest) = selftest.as_ref() {
        spawn_selftest_watchdog(
            selftest.clone(),
            alert.clone(),
            timing.clone(),
            process_started,
        );
    }
    let onboarding = Arc::new(OnboardingController::new(
        locations.tutorial_workspace_root(),
        tutorial,
        TutorialWorkspace::first_launch_candidate(locations.home()),
        {
            let alert = alert.clone();
            move |message| alert(&message)
        },
    ));
    let binding: Arc<OnceLock<WebviewWindow<Wry>>> = Arc::new(OnceLock::new());
    let builder = Arc::new(RuntimeBuilder {
        locations: locations.clone(),
        onboarding: onboarding.clone(),
        generation: Arc::new(GenerationGate::new()),
        alert: alert.clone(),
    });
    let switch = WorkspaceSwitch::new(
        locations,
        snapshot_sink(binding.clone(), alert.clone()),
        move |home, push, token| {
            if selftest_mode || live101_mode {
                builder.build(home, push, token)
            } else {
                builder.build_with_registered_data(home, push, token)
            }
        },
    )?;
    let graph = Arc::new(LiveGraph::new(switch));
    onboarding.bind_graph(&graph)?;
    let native = NativeMethods::new(graph.clone())?.with_onboarding(onboarding);
    let caller = Arc::new(LiveCaller::new(graph, move |method, args, window| {
        native.call(method, args, || window_handle(window))
    }));
    run_shell(
        assets,
        caller,
        alert,
        binding,
        resources,
        instance,
        ShellBoot {
            selftest,
            timing,
            live_debug,
        },
    )
    .map_err(Into::into)
}

fn run_selfcheck(resources: &Path) -> Result<(), StartError> {
    let result = hwpx_desktop::packaged_selfcheck::run(resources);
    if let Some(path) = std::env::var_os("HWPX_SELFCHECK_OUT") {
        hwpx_desktop::packaged_selfcheck::write_evidence(Path::new(&path), &result)?;
    }
    let evidence = result?;
    println!(
        "selfcheck: artifact_id={} tree_sha256={} -> OK",
        evidence.artifact_id, evidence.tree_sha256
    );
    Ok(())
}

/// The live101 driver's debug port request and window token; refused unless the driver
/// is named and the token is long enough.
fn live_debug_from_env(live101_mode: bool) -> Result<Option<(u16, String)>, StartError> {
    if !live101_mode {
        return Ok(None);
    }
    if std::env::var_os("HWPX_LIVE101_DRIVER").is_none() {
        return Err("실주행 드라이버가 지정되지 않았습니다.".into());
    }
    let token = std::env::var("HWPX_LIVE101_TOKEN")?;
    if token.len() < 32 {
        return Err("실주행 창 식별자가 올바르지 않습니다.".into());
    }
    Ok(Some((0, token)))
}

fn shell_alert(locations: &Locations) -> Alert {
    let alert_home = locations.home().to_path_buf();
    Arc::new(move |message| {
        hwpx_desktop::settings_store::alert(&alert_home, message);
    })
}

fn boot_timing(locations: &Locations, alert: &Alert) -> Result<BootTiming, StartError> {
    let seen_runtime =
        hwpx_desktop::shell_settings::ShellSettings::new(locations.global_settings(), {
            let alert = alert.clone();
            move |message| alert(message)
        })
        .load_boot_completed()?;
    Ok(BootTiming::new(
        &seen_runtime,
        boot_budget::runtime_version(),
    ))
}

/// Ends a selftest run that outlives its whole boot budget, reporting which phase hung.
fn spawn_selftest_watchdog(
    selftest: Arc<NativeSelftest>,
    alert: Alert,
    timing: BootTiming,
    process_started: Instant,
) {
    std::thread::spawn(move || {
        std::thread::sleep(
            Duration::from_secs(timing.hard_stop_seconds())
                .saturating_sub(process_started.elapsed()),
        );
        let state = match selftest.timeout() {
            Ok(true) => "run_hung",
            Ok(false) if selftest.succeeded() => "teardown_hung",
            Ok(false) => "run_hung",
            Err(_) => "run_hung",
        };
        alert(&format!(
            "WebView2 selftest {state}: 전체 예산 안에 종료되지 않았습니다 \
             [예산 {}s · {}]",
            timing.hard_stop_seconds(),
            timing.reason,
        ));
        std::process::exit(if state == "teardown_hung" { 7 } else { 8 });
    });
}

/// Delivers each screen snapshot to the bound main window over the product transport.
fn snapshot_sink(
    binding: Arc<OnceLock<WebviewWindow<Wry>>>,
    alert: Alert,
) -> impl Fn(&str, &serde_json::Value) -> PushResult + Send + Sync + 'static {
    move |screen, snapshot| {
        let window = binding.get().ok_or_else(|| ApiError {
            code: "window-unbound".into(),
            detail: "main window is not ready".into(),
            event: Some("snapshot".into()),
        })?;
        let api = TauriProductApi::new(window.clone(), {
            let alert = alert.clone();
            move |message| alert(message)
        });
        let body = snapshot.as_object().ok_or_else(|| ApiError {
            code: "snapshot-shape".into(),
            detail: "screen snapshot is not an object".into(),
            event: Some("snapshot".into()),
        })?;
        let delivered = tauri::async_runtime::block_on(api.push(screen, body));
        if !delivered.ok {
            return Err(ApiError {
                code: delivered.code,
                detail: delivered.detail,
                event: Some(delivered.event),
            });
        }
        Ok(Some(delivered))
    }
}

/// The main window's native handle, which owns dialogs and the clipboard.
fn window_handle(window: &WebviewWindow<Wry>) -> Result<isize, String> {
    #[cfg(windows)]
    {
        window
            .hwnd()
            .map(|handle| handle.0 as isize)
            .map_err(|error| error.to_string())
    }
    #[cfg(not(windows))]
    {
        let _ = window;
        Err("Windows 창이 없습니다.".into())
    }
}

fn asset_paths(
    resources: &Path,
    args: &[String],
) -> Result<(PathBuf, PathBuf), Box<dyn std::error::Error + Send + Sync>> {
    if args.is_empty() {
        return Ok((resources.to_path_buf(), resources.join("examples/tutorial")));
    }
    if cfg!(debug_assertions) && args.len() == 3 && args[0] == "--dev-assets" {
        let web = PathBuf::from(&args[1]);
        if web.file_name().is_none_or(|name| name != "web") {
            return Err("개발용 웹 자산 경로는 web 디렉터리여야 합니다.".into());
        }
        return Ok((
            web.parent()
                .ok_or("웹 자산 상위 경로가 없습니다.")?
                .to_path_buf(),
            PathBuf::from(&args[2]),
        ));
    }
    Err("허용되지 않은 실행 인자입니다.".into())
}

fn require_tutorial(path: &Path) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    for name in ORIGINALS {
        let file = path.join(name);
        if !file.is_file() || file.is_symlink() {
            return Err(format!("배포 튜토리얼 원본이 없습니다: {}", file.display()).into());
        }
    }
    Ok(())
}
