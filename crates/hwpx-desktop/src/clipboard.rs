//! Win32 CF_UNICODETEXT clipboard access; caller owns authorization and UX.

use std::io;

#[cfg(windows)]
mod win {
    use super::io;
    use std::thread;
    use std::time::Duration;
    use windows_sys::Win32::Foundation::GlobalFree;
    use windows_sys::Win32::System::DataExchange::{
        CloseClipboard, EmptyClipboard, GetClipboardData, IsClipboardFormatAvailable,
        OpenClipboard, SetClipboardData,
    };
    use windows_sys::Win32::System::Memory::{
        GMEM_MOVEABLE, GlobalAlloc, GlobalLock, GlobalSize, GlobalUnlock,
    };

    const CF_UNICODETEXT: u32 = 13;
    struct Clipboard;
    impl Clipboard {
        fn open(owner_hwnd: isize) -> io::Result<Self> {
            for attempt in 0..10 {
                // SAFETY: the HWND is supplied by the host and remains live for this call.
                if unsafe { OpenClipboard(owner_hwnd as _) } != 0 {
                    return Ok(Self);
                }
                if attempt < 9 {
                    thread::sleep(Duration::from_millis(20));
                }
            }
            Err(io::Error::other("클립보드를 열 수 없습니다."))
        }
    }
    impl Drop for Clipboard {
        fn drop(&mut self) {
            unsafe {
                CloseClipboard();
            }
        }
    }

    pub fn set_clipboard_text(owner_hwnd: isize, text: &str) -> io::Result<()> {
        if owner_hwnd == 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "클립보드 소유 창이 없습니다.",
            ));
        }
        if text.contains('\0') {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "클립보드 텍스트에 NUL이 있습니다.",
            ));
        }
        let _clipboard = Clipboard::open(owner_hwnd)?;
        let wide: Vec<u16> = text.encode_utf16().chain([0]).collect();
        let size = wide
            .len()
            .checked_mul(2)
            .ok_or_else(|| io::Error::other("클립보드 텍스트가 너무 큽니다."))?;
        // SAFETY: GlobalAlloc returns an owned movable block or null.
        let memory = unsafe { GlobalAlloc(GMEM_MOVEABLE, size) };
        if memory.is_null() {
            return Err(io::Error::other("클립보드 메모리를 할당할 수 없습니다."));
        }
        let result = (|| {
            // SAFETY: the allocation is at least `size` bytes and stays locked during the copy.
            let pointer = unsafe { GlobalLock(memory) };
            if pointer.is_null() {
                return Err(io::Error::other("클립보드 메모리를 잠글 수 없습니다."));
            }
            unsafe {
                std::ptr::copy_nonoverlapping(wide.as_ptr(), pointer.cast::<u16>(), wide.len());
                GlobalUnlock(memory);
            }
            if unsafe { EmptyClipboard() } == 0 {
                return Err(io::Error::other("클립보드를 비울 수 없습니다."));
            }
            // SAFETY: successful SetClipboardData transfers ownership of `memory` to Windows.
            if unsafe { SetClipboardData(CF_UNICODETEXT, memory) }.is_null() {
                return Err(io::Error::other("클립보드 데이터를 기록할 수 없습니다."));
            }
            Ok(())
        })();
        if result.is_err() {
            unsafe {
                GlobalFree(memory);
            }
        }
        result
    }

    pub fn get_clipboard_text() -> io::Result<Option<String>> {
        let _clipboard = Clipboard::open(0)?;
        if unsafe { IsClipboardFormatAvailable(CF_UNICODETEXT) } == 0 {
            return Ok(None);
        }
        let handle = unsafe { GetClipboardData(CF_UNICODETEXT) };
        if handle.is_null() {
            return Err(io::Error::other("클립보드 데이터를 읽을 수 없습니다."));
        }
        let size = unsafe { GlobalSize(handle) };
        if size < 2 || size % 2 != 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "클립보드 텍스트 크기가 올바르지 않습니다.",
            ));
        }
        let pointer = unsafe { GlobalLock(handle) };
        if pointer.is_null() {
            return Err(io::Error::other("클립보드 메모리를 잠글 수 없습니다."));
        }
        // SAFETY: GlobalSize bounds the allocation; GlobalLock keeps it stable until unlock.
        let words = unsafe { std::slice::from_raw_parts(pointer.cast::<u16>(), size / 2) };
        let end = words.iter().position(|unit| *unit == 0);
        let decoded = end
            .ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::InvalidData,
                    "클립보드 텍스트 종료가 없습니다.",
                )
            })
            .and_then(|end| {
                String::from_utf16(&words[..end]).map_err(|_| {
                    io::Error::new(
                        io::ErrorKind::InvalidData,
                        "클립보드 텍스트가 UTF-16이 아닙니다.",
                    )
                })
            });
        unsafe {
            GlobalUnlock(handle);
        }
        decoded.map(Some)
    }
}
#[cfg(windows)]
pub use win::{get_clipboard_text, set_clipboard_text};

#[cfg(not(windows))]
pub fn set_clipboard_text(_owner_hwnd: isize, _text: &str) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "클립보드 쓰기는 Windows 에서만 지원됩니다.",
    ))
}
#[cfg(not(windows))]
pub fn get_clipboard_text() -> io::Result<Option<String>> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "클립보드 읽기는 Windows 에서만 지원됩니다.",
    ))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::set_clipboard_text;

    #[test]
    fn writing_requires_a_real_owner_and_complete_text() {
        assert!(set_clipboard_text(0, "hello").is_err());
        assert!(set_clipboard_text(1, "before\0after").is_err());
    }
}
