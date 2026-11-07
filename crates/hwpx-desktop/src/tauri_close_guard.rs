//! Main-window close guard: a user close waits for the product's armed/flush verdict.

use super::HostState;
use serde_json::Value;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use tauri::{Manager, WebviewWindow, Wry};

/// A user close is held until the product says nothing is armed or unflushed; otherwise
/// the product's own close prompt decides.
pub(super) fn close_requested(window: &tauri::Window<Wry>, api: &tauri::CloseRequestApi) {
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
    tauri::async_runtime::spawn(resolve_close_request(state, webview));
}

async fn resolve_close_request(state: Arc<HostState>, webview: WebviewWindow<Wry>) {
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
            let api = crate::product_transport::TauriProductApi::new(webview, move |message| {
                alert(message)
            });
            let outcome = api.close_request(&body).await;
            if !outcome.ok {
                state.close_prompt_open.store(false, Ordering::SeqCst);
                (state.alert)(&format!("닫기 확인창 전달 실패: {}", outcome.detail));
            }
        }
        _ => {
            state.close_prompt_open.store(false, Ordering::SeqCst);
            let alert = state.alert.clone();
            let api = crate::product_transport::TauriProductApi::new(webview, move |message| {
                alert(message)
            });
            let _ = api.notice("창 닫기 상태를 확인하지 못했습니다.").await;
        }
    }
}
