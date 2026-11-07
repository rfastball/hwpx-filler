//! Asynchronous Tauri evaluation for the existing versioned `window.__hwpx` facade.

use crate::product_api::{
    ApiError, DeliveryOutcome, Descriptor, PreferencesOutcome, classify_result,
    close_request_payload, deliver_expression, describe_expression, notice_payload,
    preferences_payload, snapshot_payload, verify_descriptor,
};
use serde_json::{Map, Value};
use std::sync::{Arc, mpsc};
use std::time::Duration;
use tauri::{WebviewWindow, Wry};

const CALLBACK_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone)]
pub struct TauriProductApi {
    window: WebviewWindow<Wry>,
    durable_alert: Arc<dyn Fn(&str) + Send + Sync>,
}
impl TauriProductApi {
    pub fn new(
        window: WebviewWindow<Wry>,
        durable_alert: impl Fn(&str) + Send + Sync + 'static,
    ) -> Self {
        Self {
            window,
            durable_alert: Arc::new(durable_alert),
        }
    }

    async fn evaluate(&self, expression: &str) -> Result<Value, ApiError> {
        // WebView2 ignores uncaught JS exceptions in eval_with_callback. Convert them into a
        // distinct transport failure instead of misclassifying them as a facade rejection.
        let script = format!(
            "(()=>{{try{{return {{ok:true,value:({expression})}}}}catch(error){{return {{ok:false,error:String(error)}}}}}})()"
        );
        let (sender, receiver) = mpsc::sync_channel(1);
        self.window
            .eval_with_callback(script, move |raw| {
                let _ = sender.try_send(raw);
            })
            .map_err(|cause| transport_error(format!("평가 호출 실패: {cause}")))?;
        let raw =
            tauri::async_runtime::spawn_blocking(move || receiver.recv_timeout(CALLBACK_TIMEOUT))
                .await
                .map_err(|cause| transport_error(format!("평가 작업 실패: {cause}")))?
                .map_err(|cause| transport_error(format!("평가 응답 실패: {cause}")))?;
        let envelope: Value = serde_json::from_str(&raw)
            .map_err(|cause| transport_error(format!("평가 응답 손상: {cause}")))?;
        match envelope.as_object() {
            Some(body) if body.get("ok") == Some(&Value::Bool(true)) => body
                .get("value")
                .cloned()
                .ok_or_else(|| transport_error("평가 결과가 없습니다.")),
            Some(body) if body.get("ok") == Some(&Value::Bool(false)) => {
                Err(transport_error(format!(
                    "JavaScript 평가 예외: {}",
                    body.get("error")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown")
                )))
            }
            _ => Err(transport_error("평가 응답 형식이 올바르지 않습니다.")),
        }
    }

    pub async fn describe(&self, required: Option<&[&str]>) -> Result<Descriptor, ApiError> {
        let raw = self
            .evaluate(describe_expression())
            .await
            .map_err(|mut error| {
                error.detail = format!("describe() 평가 실패: {}", error.detail);
                error
            })?;
        verify_descriptor(&raw, required)
    }

    async fn deliver(&self, event: &str, payload: &Value) -> DeliveryOutcome {
        let expression = match deliver_expression(event, payload) {
            Ok(expression) => expression,
            Err(error) => return failed(event, error.code, error.detail),
        };
        match self.evaluate(&expression).await {
            Ok(raw) => classify_result(event, &raw),
            Err(error) => failed(
                event,
                error.code,
                format!("deliver() 평가 실패: {}", error.detail),
            ),
        }
    }

    pub async fn push(&self, screen: &str, snapshot: &Map<String, Value>) -> DeliveryOutcome {
        self.deliver("snapshot", &snapshot_payload(screen, snapshot))
            .await
    }
    pub async fn close_request(&self, state: &Map<String, Value>) -> DeliveryOutcome {
        self.deliver("close-request", &close_request_payload(state))
            .await
    }
    pub async fn preferences(
        &self,
        personalization: &Map<String, Value>,
        theme: Option<&str>,
    ) -> PreferencesOutcome {
        let payload = preferences_payload(personalization, theme);
        let theme_sent = payload.get("theme").is_some();
        crate::product_api::preferences_outcome(
            self.deliver("preferences", &payload).await,
            theme_sent,
        )
    }
    pub async fn notice(&self, message: &str) -> DeliveryOutcome {
        (self.durable_alert)(message);
        self.deliver("notice", &notice_payload(message)).await
    }
}

fn transport_error(detail: impl Into<String>) -> ApiError {
    ApiError {
        code: "evaluate-failed".into(),
        detail: detail.into(),
        event: None,
    }
}
fn failed(event: &str, code: String, detail: String) -> DeliveryOutcome {
    DeliveryOutcome {
        event: event.into(),
        ok: false,
        code,
        detail,
        result: None,
    }
}
