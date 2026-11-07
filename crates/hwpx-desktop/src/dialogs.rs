//! Native Windows dialogs on a dedicated OLE STA thread.

use std::collections::VecDeque;
use std::io;
use std::path::{Component, Path};
use std::sync::{Mutex, OnceLock};

const MAX_PATH_CHARS: usize = 4096;
static LIVE_ANSWERS: OnceLock<LiveDialogs> = OnceLock::new();

pub(crate) fn hwpx_file_filter() -> (String, String) {
    let pattern = "*.hwpx";
    (format!("HWPX ({pattern})"), pattern.into())
}

struct DialogAnswer {
    kind: String,
    path: Option<String>,
}

struct LiveDialogs {
    home: String,
    answers: Mutex<VecDeque<DialogAnswer>>,
}

impl LiveDialogs {
    fn new(home: &Path) -> io::Result<Self> {
        Ok(Self {
            home: crate::single_instance::normalize_windows_path(
                &crate::single_instance::resolved_home(home),
            )?
            .to_lowercase(),
            answers: Mutex::new(VecDeque::new()),
        })
    }

    fn queue(&self, kind: &str, path: Option<&str>) -> io::Result<()> {
        if !matches!(kind, "file" | "folder" | "save") {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "unknown dialog kind",
            ));
        }
        if let Some(path) = path {
            let candidate = Path::new(path);
            if !candidate.is_absolute()
                || candidate
                    .components()
                    .any(|part| matches!(part, Component::ParentDir))
                || path.contains('\0')
            {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "unsafe live dialog path",
                ));
            }
            let resolved = crate::single_instance::normalize_windows_path(
                &crate::single_instance::resolved_home(candidate),
            )?
            .to_lowercase();
            let prefix = format!("{}\\", self.home.trim_end_matches('\\'));
            if !resolved.starts_with(&prefix) {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "live dialog path leaves isolated home",
                ));
            }
        }
        self.answers
            .lock()
            .map_err(|_| io::Error::other("live dialog answers poisoned"))?
            .push_back(DialogAnswer {
                kind: kind.into(),
                path: path.map(str::to_owned),
            });
        Ok(())
    }

    fn take(&self, kind: &str) -> io::Result<Option<String>> {
        let answer = self
            .answers
            .lock()
            .map_err(|_| io::Error::other("live dialog answers poisoned"))?
            .pop_front()
            .ok_or_else(|| io::Error::other("unplanned native dialog in live journey"))?;
        if answer.kind != kind {
            return Err(io::Error::other(format!(
                "native dialog order changed: expected {kind}, queued {}",
                answer.kind
            )));
        }
        Ok(answer.path)
    }
}

pub fn enable_live_answers(home: &Path) -> io::Result<()> {
    LIVE_ANSWERS
        .set(LiveDialogs::new(home)?)
        .map_err(|_| io::Error::other("live dialog answers already enabled"))
}

pub fn queue_live_answer(kind: &str, path: Option<&str>) -> io::Result<()> {
    LIVE_ANSWERS
        .get()
        .ok_or_else(|| io::Error::new(io::ErrorKind::PermissionDenied, "live dialogs unavailable"))?
        .queue(kind, path)
}

fn take_live_answer(kind: &str) -> Option<io::Result<Option<String>>> {
    LIVE_ANSWERS.get().map(|answers| answers.take(kind))
}

fn dialog_result(ok: bool, selected: String, error_code: u32) -> io::Result<Option<String>> {
    if ok {
        Ok(Some(selected))
    } else if error_code == 0 {
        Ok(None)
    } else {
        Err(io::Error::other(format!(
            "공용 파일 다이얼로그 실패 (0x{error_code:04X})"
        )))
    }
}

#[cfg(windows)]
mod win {
    use super::{MAX_PATH_CHARS, dialog_result};
    use std::io;
    use std::path::Path;
    use std::thread;
    use windows_sys::Win32::System::Com::CoTaskMemFree;
    use windows_sys::Win32::System::Ole::{OleInitialize, OleUninitialize};
    use windows_sys::Win32::UI::Controls::Dialogs::{
        CommDlgExtendedError, GetOpenFileNameW, GetSaveFileNameW, OFN_EXPLORER, OFN_FILEMUSTEXIST,
        OFN_HIDEREADONLY, OFN_NOCHANGEDIR, OFN_OVERWRITEPROMPT, OFN_PATHMUSTEXIST, OPENFILENAMEW,
    };
    use windows_sys::Win32::UI::Shell::{
        BIF_EDITBOX, BIF_NEWDIALOGSTYLE, BIF_RETURNONLYFSDIRS, BROWSEINFOW, SHBrowseForFolderW,
        SHGetPathFromIDListW,
    };

    fn wide(text: &str) -> io::Result<Vec<u16>> {
        if text.contains('\0') {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "dialog text contains NUL",
            ));
        }
        Ok(text.encode_utf16().chain([0]).collect())
    }
    fn selected(buffer: &[u16]) -> io::Result<String> {
        String::from_utf16(
            &buffer[..buffer
                .iter()
                .position(|unit| *unit == 0)
                .unwrap_or(buffer.len())],
        )
        .map_err(|_| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                "다이얼로그 경로가 유효한 UTF-16이 아닙니다.",
            )
        })
    }
    fn filter_block(filters: &[(String, String)]) -> io::Result<Vec<u16>> {
        let mut result = Vec::new();
        for (description, pattern) in filters {
            result.extend(wide(&format!("{description} ({pattern})"))?);
            result.extend(wide(pattern)?);
        }
        result.push(0);
        if filters.is_empty() {
            result.push(0);
        }
        Ok(result)
    }
    fn owner(handle: isize) -> io::Result<isize> {
        if handle == 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "대화상자 소유 창이 없습니다.",
            ));
        }
        Ok(handle)
    }
    fn in_sta<T: Send + 'static>(
        task: impl FnOnce() -> io::Result<T> + Send + 'static,
    ) -> io::Result<T> {
        thread::Builder::new()
            .name("win32-file-dialog".into())
            .spawn(move || {
                // The dedicated thread has no other COM apartment. A failed OLE initialization
                // must not open a new-style dialog outside the required apartment.
                let status = unsafe { OleInitialize(std::ptr::null()) };
                if status < 0 {
                    return Err(io::Error::other(format!(
                        "OLE 초기화 실패 (0x{:08X})",
                        status as u32
                    )));
                }
                let result = task();
                unsafe {
                    OleUninitialize();
                }
                result
            })?
            .join()
            .map_err(|_| io::Error::other("파일 다이얼로그 스레드 실패"))?
    }
    fn file_dialog(
        save: bool,
        name: String,
        filters: Vec<(String, String)>,
        default_ext: String,
        owner_hwnd: isize,
    ) -> io::Result<Option<String>> {
        in_sta(move || {
            let mut buffer = [0u16; MAX_PATH_CHARS];
            let initial = wide(&name)?;
            if initial.len() > buffer.len() {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "파일 이름이 너무 깁니다.",
                ));
            }
            buffer[..initial.len()].copy_from_slice(&initial);
            let filter = filter_block(&filters)?;
            let extension = wide(&default_ext)?;
            let initial_dir = if !save && !name.is_empty() {
                let parent = Path::new(&name).parent().unwrap_or_else(|| Path::new(""));
                wide(&parent.to_string_lossy())?
            } else {
                Vec::new()
            };
            let mut ofn = OPENFILENAMEW {
                lStructSize: std::mem::size_of::<OPENFILENAMEW>() as u32,
                hwndOwner: owner(owner_hwnd)? as _,
                lpstrFilter: filter.as_ptr(),
                lpstrFile: buffer.as_mut_ptr(),
                nMaxFile: MAX_PATH_CHARS as u32,
                lpstrInitialDir: if initial_dir.is_empty() {
                    std::ptr::null()
                } else {
                    initial_dir.as_ptr()
                },
                lpstrDefExt: if default_ext.is_empty() {
                    std::ptr::null()
                } else {
                    extension.as_ptr()
                },
                Flags: OFN_EXPLORER
                    | OFN_PATHMUSTEXIST
                    | OFN_HIDEREADONLY
                    | OFN_NOCHANGEDIR
                    | if save {
                        OFN_OVERWRITEPROMPT
                    } else {
                        OFN_FILEMUSTEXIST
                    },
                ..Default::default()
            };
            // SAFETY: all pointers into owned buffers remain valid until the modal call returns.
            let ok = unsafe {
                if save {
                    GetSaveFileNameW(&mut ofn)
                } else {
                    GetOpenFileNameW(&mut ofn)
                }
            } != 0;
            let error = if ok {
                0
            } else {
                unsafe { CommDlgExtendedError() }
            };
            dialog_result(
                ok,
                if ok {
                    selected(&buffer)?
                } else {
                    String::new()
                },
                error,
            )
        })
    }
    pub fn open_file_dialog(
        filters: Vec<(String, String)>,
        owner_hwnd: isize,
        initial_path: String,
    ) -> io::Result<Option<String>> {
        file_dialog(false, initial_path, filters, String::new(), owner_hwnd)
    }
    pub fn save_file_dialog(
        default_name: String,
        filters: Vec<(String, String)>,
        default_ext: String,
        owner_hwnd: isize,
    ) -> io::Result<Option<String>> {
        file_dialog(true, default_name, filters, default_ext, owner_hwnd)
    }
    pub fn open_folder_dialog(title: String, owner_hwnd: isize) -> io::Result<Option<String>> {
        in_sta(move || {
            let mut display_name = [0u16; MAX_PATH_CHARS];
            let mut path = [0u16; MAX_PATH_CHARS];
            let title = wide(&title)?;
            let browse = BROWSEINFOW {
                hwndOwner: owner(owner_hwnd)? as _,
                pszDisplayName: display_name.as_mut_ptr(),
                lpszTitle: title.as_ptr(),
                ulFlags: BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE | BIF_EDITBOX,
                ..Default::default()
            };
            // SAFETY: the buffers are valid for the modal call; the shell-owned PIDL is freed below.
            let pidl = unsafe { SHBrowseForFolderW(&browse) };
            if pidl.is_null() {
                return Ok(None);
            }
            let ok = unsafe { SHGetPathFromIDListW(pidl, path.as_mut_ptr()) } != 0;
            unsafe {
                CoTaskMemFree(pidl.cast());
            }
            if ok {
                Ok(Some(selected(&path)?))
            } else {
                Err(io::Error::last_os_error())
            }
        })
    }

    #[cfg(test)]
    mod positive_tests {
        use super::in_sta;
        use windows_sys::Win32::System::Com::{CoTaskMemAlloc, CoTaskMemFree};

        #[test]
        #[ignore = "requires a real Windows desktop session and OLE apartment"]
        fn windows_sta_dialog_result_and_pidl_allocator_round_trip() {
            in_sta(|| {
                assert_eq!(
                    super::super::dialog_result(true, "C:\\선택.hwpx".into(), 0)?,
                    Some("C:\\선택.hwpx".into())
                );
                assert_eq!(super::super::dialog_result(false, String::new(), 0)?, None);
                assert!(super::super::dialog_result(false, String::new(), 0x3002).is_err());
                for _ in 0..64 {
                    let pidl = unsafe { CoTaskMemAlloc(64) };
                    assert!(!pidl.is_null(), "CoTaskMemAlloc failed");
                    unsafe { CoTaskMemFree(pidl) };
                }
                Ok(())
            })
            .unwrap();
        }
    }
}

#[cfg(windows)]
pub fn open_file_dialog(
    filters: Vec<(String, String)>,
    owner_hwnd: isize,
    initial_path: String,
) -> io::Result<Option<String>> {
    if let Some(answer) = take_live_answer("file") {
        return answer;
    }
    win::open_file_dialog(filters, owner_hwnd, initial_path)
}

#[cfg(windows)]
pub fn open_folder_dialog(title: String, owner_hwnd: isize) -> io::Result<Option<String>> {
    if let Some(answer) = take_live_answer("folder") {
        return answer;
    }
    win::open_folder_dialog(title, owner_hwnd)
}

#[cfg(windows)]
pub fn save_file_dialog(
    default_name: String,
    filters: Vec<(String, String)>,
    default_ext: String,
    owner_hwnd: isize,
) -> io::Result<Option<String>> {
    if let Some(answer) = take_live_answer("save") {
        return answer;
    }
    win::save_file_dialog(default_name, filters, default_ext, owner_hwnd)
}

#[cfg(not(windows))]
pub fn open_file_dialog(
    _filters: Vec<(String, String)>,
    _owner_hwnd: isize,
    _initial_path: String,
) -> io::Result<Option<String>> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "파일 다이얼로그는 Windows 에서만 지원됩니다.",
    ))
}
#[cfg(not(windows))]
pub fn save_file_dialog(
    _default_name: String,
    _filters: Vec<(String, String)>,
    _default_ext: String,
    _owner_hwnd: isize,
) -> io::Result<Option<String>> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "파일 다이얼로그는 Windows 에서만 지원됩니다.",
    ))
}
#[cfg(not(windows))]
pub fn open_folder_dialog(_title: String, _owner_hwnd: isize) -> io::Result<Option<String>> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "파일 다이얼로그는 Windows 에서만 지원됩니다.",
    ))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{LiveDialogs, dialog_result};

    #[test]
    fn selected_cancelled_and_failed_dialogs_remain_distinct() {
        assert_eq!(
            dialog_result(true, "C:\\a.hwpx".into(), 0).unwrap(),
            Some("C:\\a.hwpx".into())
        );
        assert_eq!(dialog_result(false, String::new(), 0).unwrap(), None);
        assert!(
            dialog_result(false, String::new(), 0x3002)
                .unwrap_err()
                .to_string()
                .contains("0x3002")
        );
    }

    #[test]
    fn live_dialog_answers_are_bounded_to_the_isolated_home_and_order() {
        let home = std::env::current_dir().unwrap();
        let answers = LiveDialogs::new(&home).unwrap();
        let file = home.join("data/source.csv");
        answers.queue("file", file.to_str()).unwrap();
        assert_eq!(
            answers.take("file").unwrap(),
            file.to_str().map(str::to_owned)
        );
        assert!(
            answers
                .queue("file", home.parent().unwrap().join("outside.csv").to_str())
                .is_err()
        );
        answers
            .queue("folder", home.join("templates").to_str())
            .unwrap();
        assert!(answers.take("file").is_err());
        assert!(answers.take("file").is_err());
    }
}
