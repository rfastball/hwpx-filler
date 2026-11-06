//! Windows HTTPS transport for the Nara source. Only the fixed public-data endpoint is admitted.

use hwpx_filler::nara::{BASE, NaraFetcher};
use std::sync::Arc;

pub fn nara_fetcher(timeout_ms: i32) -> NaraFetcher {
    Arc::new(move |url| fetch_nara(url, timeout_ms))
}

fn query_from_url(url: &str) -> Result<&str, String> {
    url.strip_prefix(BASE)
        .and_then(|tail| tail.strip_prefix('?'))
        .filter(|query| !query.is_empty())
        .ok_or_else(|| "나라장터 요청 주소가 허용된 API 경로가 아닙니다.".to_owned())
}

pub fn fetch_nara(url: &str, timeout_ms: i32) -> Result<Vec<u8>, String> {
    let query = query_from_url(url)?;
    #[cfg(windows)]
    {
        windows::fetch(query, timeout_ms)
    }
    #[cfg(not(windows))]
    {
        let _ = (query, timeout_ms);
        Err("Windows HTTPS transport가 필요합니다.".into())
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn transport_admits_only_the_fixed_endpoint_with_a_query() {
        assert_eq!(query_from_url(&format!("{BASE}?pageNo=1")), Ok("pageNo=1"));
        for url in [
            "https://evil.example/?pageNo=1".to_string(),
            BASE.to_string(),
            format!("{BASE}/other?pageNo=1"),
            format!("{BASE}?"),
        ] {
            assert_eq!(
                query_from_url(&url).unwrap_err(),
                "나라장터 요청 주소가 허용된 API 경로가 아닙니다."
            );
        }
    }
}

#[cfg(windows)]
mod windows {
    use std::ffi::c_void;
    use std::ptr;
    use windows_sys::Win32::Networking::WinHttp::{
        INTERNET_DEFAULT_HTTPS_PORT, WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, WINHTTP_DISABLE_REDIRECTS,
        WINHTTP_FLAG_SECURE, WINHTTP_OPTION_DISABLE_FEATURE, WINHTTP_QUERY_FLAG_NUMBER,
        WINHTTP_QUERY_STATUS_CODE, WinHttpCloseHandle, WinHttpConnect, WinHttpOpen,
        WinHttpOpenRequest, WinHttpQueryHeaders, WinHttpReadData, WinHttpReceiveResponse,
        WinHttpSendRequest, WinHttpSetOption, WinHttpSetTimeouts,
    };

    const HOST: &str = "apis.data.go.kr";
    const PATH: &str = "/1230000/ao/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo";
    const MAX_RESPONSE_BYTES: usize = 32 * 1024 * 1024;

    struct Handle(*mut c_void);
    impl Drop for Handle {
        fn drop(&mut self) {
            if !self.0.is_null() {
                unsafe {
                    WinHttpCloseHandle(self.0);
                }
            }
        }
    }
    fn wide(text: &str) -> Vec<u16> {
        text.encode_utf16().chain([0]).collect()
    }
    fn error(step: &str) -> String {
        format!(
            "나라장터 HTTPS {step} 실패(Windows 코드 {}).",
            std::io::Error::last_os_error().raw_os_error().unwrap_or(0)
        )
    }

    pub(super) fn fetch(query: &str, timeout_ms: i32) -> Result<Vec<u8>, String> {
        if timeout_ms <= 0 {
            return Err("나라장터 HTTPS 제한 시간이 올바르지 않습니다.".into());
        }
        let agent = wide("document-narmi/0.15");
        let host = wide(HOST);
        let request_path = wide(&format!("{PATH}?{query}"));
        let verb = wide("GET");
        // Each handle stays in this scope; transport errors contain no URL or ServiceKey.
        let session = Handle(unsafe {
            WinHttpOpen(
                agent.as_ptr(),
                WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                ptr::null(),
                ptr::null(),
                0,
            )
        });
        if session.0.is_null() {
            return Err(error("세션"));
        }
        if unsafe { WinHttpSetTimeouts(session.0, timeout_ms, timeout_ms, timeout_ms, timeout_ms) }
            == 0
        {
            return Err(error("제한 시간"));
        }
        let connection = Handle(unsafe {
            WinHttpConnect(session.0, host.as_ptr(), INTERNET_DEFAULT_HTTPS_PORT, 0)
        });
        if connection.0.is_null() {
            return Err(error("연결"));
        }
        let request = Handle(unsafe {
            WinHttpOpenRequest(
                connection.0,
                verb.as_ptr(),
                request_path.as_ptr(),
                ptr::null(),
                ptr::null(),
                ptr::null(),
                WINHTTP_FLAG_SECURE,
            )
        });
        if request.0.is_null() {
            return Err(error("요청"));
        }
        let disable_redirects = WINHTTP_DISABLE_REDIRECTS;
        if unsafe {
            WinHttpSetOption(
                request.0,
                WINHTTP_OPTION_DISABLE_FEATURE,
                (&disable_redirects as *const u32).cast(),
                size_of::<u32>() as u32,
            )
        } == 0
        {
            return Err(error("리다이렉트 제한"));
        }
        if unsafe { WinHttpSendRequest(request.0, ptr::null(), 0, ptr::null(), 0, 0, 0) } == 0 {
            return Err(error("전송"));
        }
        if unsafe { WinHttpReceiveResponse(request.0, ptr::null_mut()) } == 0 {
            return Err(error("응답"));
        }
        let mut status = 0u32;
        let mut status_size = size_of::<u32>() as u32;
        if unsafe {
            WinHttpQueryHeaders(
                request.0,
                WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                ptr::null(),
                (&mut status as *mut u32).cast(),
                &mut status_size,
                ptr::null_mut(),
            )
        } == 0
        {
            return Err(error("응답 상태"));
        }
        if !(200..300).contains(&status) {
            return Err(format!("나라장터 HTTP 응답 오류: {status}."));
        }
        let mut body = Vec::new();
        loop {
            let mut chunk = [0u8; 8192];
            let mut read = 0u32;
            if unsafe {
                WinHttpReadData(
                    request.0,
                    chunk.as_mut_ptr().cast(),
                    chunk.len() as u32,
                    &mut read,
                )
            } == 0
            {
                return Err(error("본문 수신"));
            }
            if read == 0 {
                return Ok(body);
            }
            if body.len() + read as usize > MAX_RESPONSE_BYTES {
                return Err("나라장터 응답 크기가 허용 범위를 넘었습니다.".into());
            }
            body.extend_from_slice(&chunk[..read as usize]);
        }
    }
}
