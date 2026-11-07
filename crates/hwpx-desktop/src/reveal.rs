//! Windows Explorer selection and default-application launch after caller authorization.

use std::io;
use std::path::Path;

fn require_exists(path: &Path) -> io::Result<()> {
    if path.exists() {
        Ok(())
    } else {
        Err(io::Error::new(
            io::ErrorKind::NotFound,
            format!("경로를 찾을 수 없습니다: {}", path.display()),
        ))
    }
}

#[cfg(windows)]
pub fn reveal_in_explorer(path: &Path) -> io::Result<bool> {
    reveal_with(path, |path| {
        std::process::Command::new("explorer")
            .arg("/select,")
            .arg(path)
            .spawn()
            .map(|_| ())
    })
}

#[cfg(windows)]
fn reveal_with(path: &Path, launch: impl FnOnce(&Path) -> io::Result<()>) -> io::Result<bool> {
    require_exists(path)?;
    launch(path).map_err(|cause| {
        io::Error::new(
            cause.kind(),
            format!(
                "탐색기에서 표시할 수 없습니다: {} ({cause})",
                path.display()
            ),
        )
    })?;
    Ok(true)
}

#[cfg(windows)]
pub fn open_path(path: &Path) -> io::Result<bool> {
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;
    open_with(path, |wide| unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            std::ptr::null(),
            wide.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            SW_SHOWNORMAL,
        ) as isize
    })
}

#[cfg(windows)]
fn open_with(path: &Path, execute: impl FnOnce(&[u16]) -> isize) -> io::Result<bool> {
    use std::os::windows::ffi::OsStrExt;
    require_exists(path)?;
    let mut wide: Vec<u16> = path.as_os_str().encode_wide().collect();
    if wide.contains(&0) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "path contains NUL",
        ));
    }
    wide.push(0);
    // The executor receives a valid NUL-terminated UTF-16 path.
    let result = execute(&wide);
    if result <= 32 {
        return Err(io::Error::other(format!(
            "기본 앱으로 열기할 수 없습니다: {} (ShellExecute={})",
            path.display(),
            result
        )));
    }
    Ok(true)
}

#[cfg(not(windows))]
pub fn reveal_in_explorer(_path: &Path) -> io::Result<bool> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "탐색기에서 보기는 Windows 에서만 지원됩니다.",
    ))
}
#[cfg(not(windows))]
pub fn open_path(_path: &Path) -> io::Result<bool> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "파일 열기는 Windows 에서만 지원됩니다.",
    ))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{open_path, reveal_in_explorer};
    use std::path::Path;

    #[test]
    fn missing_target_is_refused_before_any_os_launch() {
        let missing = Path::new("__hwpx_missing_reveal_target__");
        assert!(reveal_in_explorer(missing).is_err());
        assert!(open_path(missing).is_err());
    }

    #[cfg(windows)]
    #[test]
    fn launch_result_and_os_errors_are_restated_without_starting_explorer() {
        use super::{open_with, reveal_with};
        use std::fs;
        use std::io;
        use std::os::windows::ffi::OsStrExt;
        let target = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .join(format!("reveal-probe-{}.hwpx", uuid::Uuid::new_v4()));
        fs::create_dir_all(target.parent().unwrap()).unwrap();
        fs::write(&target, b"probe").unwrap();
        assert!(
            reveal_with(&target, |path| {
                assert_eq!(path, target);
                Ok(())
            })
            .unwrap()
        );
        assert!(
            open_with(&target, |wide| {
                assert_eq!(
                    wide,
                    target
                        .as_os_str()
                        .encode_wide()
                        .chain([0])
                        .collect::<Vec<_>>()
                );
                33
            })
            .unwrap()
        );
        let denied = reveal_with(&target, |_| {
            Err(io::Error::from(io::ErrorKind::PermissionDenied))
        })
        .unwrap_err();
        assert_eq!(denied.kind(), io::ErrorKind::PermissionDenied);
        assert!(denied.to_string().contains("탐색기에서 표시할 수 없습니다"));
        assert!(denied.to_string().contains(&target.display().to_string()));
        let denied = open_with(&target, |_| 5).unwrap_err();
        assert!(
            denied
                .to_string()
                .contains("기본 앱으로 열기할 수 없습니다")
        );
        assert!(denied.to_string().contains(&target.display().to_string()));
        assert!(denied.to_string().contains("ShellExecute=5"));
        fs::remove_file(target).unwrap();
    }
}
