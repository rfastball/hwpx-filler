//! Per-app-home Windows mutex compatible with the existing Python process.

use sha1::{Digest, Sha1};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

pub(crate) fn normalize_windows_path(path: &Path) -> io::Result<String> {
    let raw = path
        .to_str()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "home path is not Unicode"))?;
    let raw = raw
        .strip_prefix(r"\\?\UNC\")
        .map(|unc| format!(r"\\{unc}"))
        .or_else(|| raw.strip_prefix(r"\\?\").map(str::to_owned))
        .unwrap_or_else(|| raw.to_owned());
    Ok(raw.replace('/', "\\"))
}
pub(crate) fn resolved_home(home: &Path) -> PathBuf {
    if let Ok(path) = fs::canonicalize(home) {
        return path;
    }
    let absolute = std::path::absolute(home).unwrap_or_else(|_| home.to_path_buf());
    let mut missing = Vec::new();
    let mut ancestor = absolute.as_path();
    while !ancestor.exists() {
        let Some(name) = ancestor.file_name() else {
            break;
        };
        missing.push(name.to_os_string());
        let Some(parent) = ancestor.parent() else {
            break;
        };
        ancestor = parent;
    }
    let mut resolved = fs::canonicalize(ancestor).unwrap_or_else(|_| ancestor.to_path_buf());
    for name in missing.into_iter().rev() {
        resolved.push(name);
    }
    resolved
}
pub fn mutex_name(home: &Path) -> io::Result<String> {
    let key = normalize_windows_path(&resolved_home(home))?;
    let digest = Sha1::digest(key.as_bytes());
    let hex = digest
        .iter()
        .take(8)
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    Ok(format!("hwpx-filler-single-instance-{hex}"))
}

#[cfg(windows)]
mod win {
    use super::mutex_name;
    use std::io;
    use std::path::Path;
    use windows_sys::Win32::Foundation::{CloseHandle, ERROR_ALREADY_EXISTS, GetLastError, HANDLE};
    use windows_sys::Win32::System::Threading::CreateMutexW;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        FindWindowW, IsWindowVisible, SW_RESTORE, SetForegroundWindow, ShowWindow,
    };

    pub struct InstanceGuard(HANDLE);
    // A Win32 kernel HANDLE is process-wide and CloseHandle may run on any thread.
    unsafe impl Send for InstanceGuard {}
    impl Drop for InstanceGuard {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
    pub enum Acquisition {
        Primary(InstanceGuard),
        Existing,
    }

    pub(crate) fn acquire_named(name: &str) -> io::Result<Acquisition> {
        let wide: Vec<u16> = name.encode_utf16().chain([0]).collect();
        // SAFETY: null security attributes, NUL-terminated UTF-16 name, and owned HANDLE.
        let handle = unsafe { CreateMutexW(std::ptr::null(), 0, wide.as_ptr()) };
        let last = unsafe { GetLastError() };
        if handle.is_null() {
            return Err(io::Error::from_raw_os_error(last as i32));
        }
        if last == ERROR_ALREADY_EXISTS {
            unsafe {
                CloseHandle(handle);
            }
            return Ok(Acquisition::Existing);
        }
        Ok(Acquisition::Primary(InstanceGuard(handle)))
    }

    pub fn acquire(home: &Path) -> io::Result<Acquisition> {
        acquire_named(&mutex_name(home)?)
    }

    pub fn focus_existing(title: &str) -> bool {
        let wide: Vec<u16> = title.encode_utf16().chain([0]).collect();
        // SAFETY: null class, NUL-terminated title, and window handle is used only for Win32 calls.
        let window = unsafe { FindWindowW(std::ptr::null(), wide.as_ptr()) };
        if window.is_null() || unsafe { IsWindowVisible(window) } == 0 {
            return false;
        }
        unsafe {
            ShowWindow(window, SW_RESTORE);
            SetForegroundWindow(window);
        }
        true
    }
}
#[cfg(windows)]
pub(crate) use win::acquire_named;
#[cfg(windows)]
pub use win::{Acquisition, InstanceGuard, acquire, focus_existing};

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    fn assert_startup_claim_precedes_graph_and_window() {
        use syn::visit::{self, Visit};
        fn call_name(expr: &syn::Expr) -> Option<String> {
            let syn::Expr::Call(call) = expr else {
                return None;
            };
            let syn::Expr::Path(path) = call.func.as_ref() else {
                return None;
            };
            Some(
                path.path
                    .segments
                    .iter()
                    .map(|part| part.ident.to_string())
                    .collect::<Vec<_>>()
                    .join("::"),
            )
        }
        #[derive(Default)]
        struct Startup {
            calls: Vec<String>,
            existing_returns: bool,
            shell_owns_instance: bool,
            shell_owns_assets: bool,
        }
        impl<'ast> Visit<'ast> for Startup {
            fn visit_expr(&mut self, expr: &'ast syn::Expr) {
                if let Some(name) = call_name(expr) {
                    if name == "run_shell"
                        && let syn::Expr::Call(call) = expr
                    {
                        self.shell_owns_instance = call.args.iter().any(|arg| matches!(arg, syn::Expr::Path(path) if path.path.is_ident("instance")));
                        self.shell_owns_assets = call.args.iter().any(|arg| matches!(arg, syn::Expr::Path(path) if path.path.is_ident("assets")));
                    }
                    self.calls.push(name);
                }
                if let syn::Expr::Struct(value) = expr
                    && value.path.is_ident("RuntimeBuilder")
                {
                    self.calls.push("RuntimeBuilder".into());
                }
                if let syn::Expr::Match(choice) = expr
                    && let syn::Expr::Try(attempt) = choice.expr.as_ref()
                    && call_name(&attempt.expr).as_deref()
                        == Some("hwpx_desktop::single_instance::acquire")
                {
                    self.existing_returns = choice.arms.iter().any(|arm| {
                        matches!(&arm.pat, syn::Pat::Path(path) if path.path.segments.last().unwrap().ident == "Existing")
                            && matches!(arm.body.as_ref(), syn::Expr::Block(block) if block.block.stmts.iter().any(|stmt| matches!(stmt, syn::Stmt::Expr(syn::Expr::Return(_), _))))
                    });
                }
                visit::visit_expr(self, expr);
            }
        }
        let source = syn::parse_file(include_str!("bin/documentnarmi.rs")).unwrap();
        let start = source
            .items
            .iter()
            .find_map(|item| match item {
                syn::Item::Fn(function) if function.sig.ident == "start" => Some(function),
                _ => None,
            })
            .unwrap();
        let mut startup = Startup::default();
        startup.visit_block(&start.block);
        let position = |name: &str| startup.calls.iter().position(|call| call == name).unwrap();
        let frozen = position("WebAssets::frozen");
        assert!(position("require_tutorial") < frozen);
        for boundary in [
            "hwpx_desktop::single_instance::acquire",
            "RuntimeBuilder",
            "run_shell",
        ] {
            assert!(
                frozen < position(boundary),
                "{boundary} precedes sealed asset verification"
            );
        }
        let claim = startup
            .calls
            .iter()
            .position(|name| name == "hwpx_desktop::single_instance::acquire")
            .unwrap();
        for boundary in [
            "OnboardingController::new",
            "WorkspaceSwitch::new",
            "LiveGraph::new",
            "run_shell",
        ] {
            assert!(
                claim
                    < startup
                        .calls
                        .iter()
                        .position(|name| name == boundary)
                        .unwrap(),
                "{boundary} precedes the app-home claim"
            );
        }
        assert!(startup.existing_returns);
        assert!(startup.shell_owns_instance);
        assert!(startup.shell_owns_assets);
    }

    #[cfg(windows)]
    #[test]
    fn mutex_name_matches_the_python_app_home_key() {
        let name = super::mutex_name(std::path::Path::new("C:/Users/Test/.hwpxfiller")).unwrap();
        assert_eq!(name, "hwpx-filler-single-instance-49bb93327d8122e1");
    }

    #[cfg(windows)]
    #[test]
    fn same_home_has_one_primary_until_its_handle_is_released() {
        assert_startup_claim_precedes_graph_and_window();
        use super::{Acquisition, acquire};
        use std::time::{SystemTime, UNIX_EPOCH};
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let home = std::env::temp_dir().join(format!("hwpx-mutex-{}-{stamp}", std::process::id()));
        std::fs::create_dir(&home).unwrap();
        assert_eq!(
            super::mutex_name(&home).unwrap(),
            super::mutex_name(&home.join(".")).unwrap()
        );
        let other_home = home.join("other");
        assert_ne!(
            super::mutex_name(&home).unwrap(),
            super::mutex_name(&other_home).unwrap()
        );
        assert!(!super::mutex_name(&home).unwrap().contains('\\'));
        let primary = match acquire(&home).unwrap() {
            Acquisition::Primary(guard) => guard,
            Acquisition::Existing => panic!("unique app home already locked"),
        };
        assert!(matches!(acquire(&home).unwrap(), Acquisition::Existing));
        assert!(matches!(
            acquire(&home.join(".")).unwrap(),
            Acquisition::Existing
        ));
        let other = match acquire(&other_home).unwrap() {
            Acquisition::Primary(guard) => guard,
            Acquisition::Existing => panic!("different app home shares the first mutex"),
        };
        drop(primary);
        assert!(matches!(acquire(&home).unwrap(), Acquisition::Primary(_)));
        assert!(matches!(
            acquire(&other_home).unwrap(),
            Acquisition::Existing
        ));
        drop(other);
        assert!(!super::focus_existing(&format!(
            "absent-hwpx-window-{stamp}"
        )));
        std::fs::remove_dir(home).unwrap();
    }

    #[cfg(windows)]
    #[test]
    #[ignore = "requires a real Windows desktop and clipboard session"]
    fn windows_clipboard_and_visible_focus_round_trip() {
        use windows_sys::Win32::Foundation::HWND;
        use windows_sys::Win32::UI::WindowsAndMessaging::{
            CreateWindowExW, DestroyWindow, IsIconic, SW_MINIMIZE, ShowWindow, WS_OVERLAPPEDWINDOW,
            WS_VISIBLE,
        };

        struct ProbeWindow {
            hwnd: HWND,
            restore: Option<Option<String>>,
        }
        impl Drop for ProbeWindow {
            fn drop(&mut self) {
                if let Some(previous) = self.restore.take() {
                    let _ = crate::clipboard::set_clipboard_text(
                        self.hwnd as isize,
                        previous.as_deref().unwrap_or(""),
                    );
                }
                unsafe { DestroyWindow(self.hwnd) };
            }
        }

        let title = format!("HWPX native focus probe {}", uuid::Uuid::new_v4());
        let class = "STATIC\0".encode_utf16().collect::<Vec<_>>();
        let wide = title.encode_utf16().chain([0]).collect::<Vec<_>>();
        let hwnd = unsafe {
            CreateWindowExW(
                0,
                class.as_ptr(),
                wide.as_ptr(),
                WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                -32000,
                -32000,
                120,
                80,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null(),
            )
        };
        assert!(!hwnd.is_null(), "a real Windows probe window is required");
        let mut probe = ProbeWindow {
            hwnd,
            restore: None,
        };
        probe.restore = Some(crate::clipboard::get_clipboard_text().unwrap());
        let marker = format!("HWPX native probe {} — 한글 𠮷", uuid::Uuid::new_v4());
        crate::clipboard::set_clipboard_text(hwnd as isize, &marker).unwrap();
        assert_eq!(
            crate::clipboard::get_clipboard_text().unwrap(),
            Some(marker)
        );
        unsafe { ShowWindow(hwnd, SW_MINIMIZE) };
        assert_ne!(unsafe { IsIconic(hwnd) }, 0);
        assert!(super::focus_existing(&title));
        assert_eq!(unsafe { IsIconic(hwnd) }, 0);
        let previous = probe.restore.as_ref().unwrap().as_deref().unwrap_or("");
        crate::clipboard::set_clipboard_text(hwnd as isize, previous).unwrap();
        assert_eq!(
            crate::clipboard::get_clipboard_text().unwrap(),
            Some(previous.to_owned())
        );
        probe.restore = None;
    }
}
