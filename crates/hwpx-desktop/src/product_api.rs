//! Versioned `window.__hwpx` payload and acknowledgement contract.

use hwpx_filler::text_render::python_repr as py_repr;
use serde::Serialize;
use serde_json::{Map, Value, json};
use std::fmt;

pub const PROTOCOL: &str = "hwpx-product";
pub const VERSION: u8 = 1;
pub const CAPABILITIES: [&str; 4] = ["snapshot", "close-request", "preferences", "notice"];
pub const ERROR_CODES: [&str; 12] = [
    "facade-absent",
    "evaluate-failed",
    "descriptor-malformed",
    "protocol-mismatch",
    "version-unsupported",
    "capability-missing",
    "result-not-object",
    "result-missing-ok",
    "result-ok-not-bool",
    "rejected",
    "payload-unserializable",
    "adapter-internal",
];
const ROOT: &str = "window.__hwpx";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ApiError {
    pub code: String,
    pub detail: String,
    pub event: Option<String>,
}
impl fmt::Display for ApiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if let Some(event) = self.event.as_deref() {
            write!(f, "{event} ")?;
        }
        write!(f, "[{}] {}", self.code, self.detail)
    }
}
impl std::error::Error for ApiError {}
fn error(code: &str, detail: impl Into<String>) -> ApiError {
    ApiError {
        code: code.into(),
        detail: detail.into(),
        event: None,
    }
}

#[derive(Serialize)]
struct Envelope<'a> {
    version: u8,
    event: &'a str,
    payload: &'a Value,
}
pub fn describe_expression() -> &'static str {
    "window.__hwpx ? window.__hwpx.describe() : null"
}
pub fn deliver_expression(event: &str, payload: &Value) -> Result<String, ApiError> {
    if !CAPABILITIES.contains(&event) {
        return Err(error(
            "adapter-internal",
            format!("계약에 없는 event: '{event}'"),
        ));
    }
    if !payload.is_object() {
        return Err(error("payload-unserializable", "payload는 객체여야 합니다"));
    }
    let envelope = Envelope {
        version: VERSION,
        event,
        payload,
    };
    let literal = serde_json::to_string(&envelope)
        .map_err(|cause| {
            error(
                "payload-unserializable",
                format!("JSON 으로 실을 수 없는 값: {cause}"),
            )
        })?
        .replace('\u{2028}', "\\u2028")
        .replace('\u{2029}', "\\u2029");
    Ok(format!("{ROOT} ? {ROOT}.deliver({literal}) : null"))
}
pub fn snapshot_payload(screen: &str, snapshot: &Map<String, Value>) -> Value {
    json!({"screen": screen, "snapshot": snapshot})
}
pub fn close_request_payload(state: &Map<String, Value>) -> Value {
    json!({"state": state})
}
pub fn preferences_payload(personalization: &Map<String, Value>, theme: Option<&str>) -> Value {
    let mut payload = Map::new();
    payload.insert(
        "personalization".into(),
        Value::Object(personalization.clone()),
    );
    if let Some(theme @ ("light" | "dark")) = theme {
        payload.insert("theme".into(), json!(theme));
    }
    Value::Object(payload)
}
pub fn notice_payload(message: &str) -> Value {
    json!({"message": format!("[hwpx] {message}")})
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Descriptor {
    pub protocol: String,
    pub version: u8,
    pub capabilities: Vec<String>,
}
pub fn parse_descriptor(raw: &Value) -> Result<Descriptor, ApiError> {
    if raw.is_null() {
        return Err(error(
            "facade-absent",
            "window.__hwpx 부재(describe() 반환=None)",
        ));
    }
    let object = raw.as_object().ok_or_else(|| {
        error(
            "descriptor-malformed",
            format!("describe() 반환이 객체가 아니다: {}", py_repr(raw)),
        )
    })?;
    if object.get("protocol").and_then(Value::as_str) != Some(PROTOCOL) {
        return Err(error(
            "protocol-mismatch",
            format!(
                "프로토콜 불일치: {} (기대 '{PROTOCOL}')",
                object.get("protocol").map_or("None".into(), py_repr)
            ),
        ));
    }
    let version = object
        .get("version")
        .ok_or_else(|| error("version-unsupported", "describe() 에 version 필드가 없다"))?;
    let number = version.as_f64().ok_or_else(|| {
        error(
            "version-unsupported",
            format!("version 이 수가 아니다: {}", py_repr(version)),
        )
    })?;
    if !number.is_finite() || number.fract() != 0.0 {
        return Err(error(
            "version-unsupported",
            format!("version 이 정수가 아니다: {}", py_repr(version)),
        ));
    }
    if number != f64::from(VERSION) {
        return Err(error(
            "version-unsupported",
            format!(
                "지원하지 않는 version: {} (이 어댑터는 {VERSION})",
                py_repr(version)
            ),
        ));
    }
    let capabilities = object
        .get("capabilities")
        .and_then(Value::as_array)
        .ok_or_else(|| {
            error(
                "descriptor-malformed",
                format!(
                    "capabilities 가 배열이 아니다: {}",
                    object.get("capabilities").map_or("None".into(), py_repr)
                ),
            )
        })?;
    let mut names = Vec::with_capacity(capabilities.len());
    for capability in capabilities {
        names.push(
            capability
                .as_str()
                .ok_or_else(|| {
                    error(
                        "descriptor-malformed",
                        format!(
                            "capabilities 원소가 문자열이 아니다: {}",
                            py_repr(&Value::Array(capabilities.clone()))
                        ),
                    )
                })?
                .to_owned(),
        );
    }
    Ok(Descriptor {
        protocol: PROTOCOL.into(),
        version: VERSION,
        capabilities: names,
    })
}
pub fn verify_descriptor(raw: &Value, required: Option<&[&str]>) -> Result<Descriptor, ApiError> {
    let descriptor = parse_descriptor(raw)?;
    let missing: Vec<_> = required
        .unwrap_or(&CAPABILITIES)
        .iter()
        .filter(|name| {
            !descriptor
                .capabilities
                .iter()
                .any(|capability| capability == **name)
        })
        .copied()
        .collect();
    if !missing.is_empty() {
        return Err(error(
            "capability-missing",
            format!(
                "능력 부재: {} (파사드 신고={})",
                missing.join(", "),
                py_repr(&json!(descriptor.capabilities))
            ),
        ));
    }
    Ok(descriptor)
}

#[derive(Clone, Debug, PartialEq)]
pub struct DeliveryOutcome {
    pub event: String,
    pub ok: bool,
    pub code: String,
    pub detail: String,
    pub result: Option<Map<String, Value>>,
}
impl DeliveryOutcome {
    fn failed(
        event: &str,
        code: &str,
        detail: impl Into<String>,
        result: Option<Map<String, Value>>,
    ) -> Self {
        Self {
            event: event.into(),
            ok: false,
            code: code.into(),
            detail: detail.into(),
            result,
        }
    }
    pub fn alarm_text(&self) -> String {
        format!("{} 전달 실패 [{}] {}", self.event, self.code, self.detail)
    }
    pub fn require_success(self) -> Result<Self, ApiError> {
        if self.ok {
            return Ok(self);
        }
        Err(ApiError {
            code: self.code,
            detail: self.detail,
            event: Some(self.event),
        })
    }
}
pub fn classify_result(event: &str, raw: &Value) -> DeliveryOutcome {
    if raw.is_null() {
        return DeliveryOutcome::failed(
            event,
            "facade-absent",
            "window.__hwpx 부재(deliver() 반환=None)",
            None,
        );
    }
    let Some(result) = raw.as_object() else {
        return DeliveryOutcome::failed(
            event,
            "result-not-object",
            format!("deliver() 반환이 객체가 아니다: {}", py_repr(raw)),
            None,
        );
    };
    if !result.contains_key("ok") {
        return DeliveryOutcome::failed(
            event,
            "result-missing-ok",
            format!("결과에 ok 가 없다: {}", py_repr(raw)),
            Some(result.clone()),
        );
    }
    let Some(ok) = result["ok"].as_bool() else {
        return DeliveryOutcome::failed(
            event,
            "result-ok-not-bool",
            format!("ok 가 참/거짓이 아니다: {}", py_repr(&result["ok"])),
            Some(result.clone()),
        );
    };
    if ok {
        return DeliveryOutcome {
            event: event.into(),
            ok: true,
            code: "ok".into(),
            detail: String::new(),
            result: Some(result.clone()),
        };
    }
    let code = result
        .get("code")
        .and_then(Value::as_str)
        .filter(|code| !code.is_empty())
        .unwrap_or("rejected");
    DeliveryOutcome::failed(
        event,
        code,
        format!("파사드가 거절했다: {}", py_repr(raw)),
        Some(result.clone()),
    )
}

#[derive(Clone, Debug, PartialEq)]
pub struct PreferencesOutcome {
    pub delivery: DeliveryOutcome,
    pub expected: Vec<&'static str>,
    pub applied: Vec<&'static str>,
    pub failed: Vec<&'static str>,
    pub attributed: bool,
    pub notes: Vec<String>,
}
impl PreferencesOutcome {
    pub fn ok(&self) -> bool {
        self.failed.is_empty()
    }
    pub fn theme_sent(&self) -> bool {
        self.expected.contains(&"theme")
    }
    pub fn failure_text(&self) -> Option<String> {
        if self.ok() {
            return None;
        }
        let parts = self
            .failed
            .iter()
            .map(|part| match *part {
                "theme" => "테마",
                _ => "개인화",
            })
            .collect::<Vec<_>>()
            .join(", ");
        let suffix = if self.attributed {
            ""
        } else {
            " (귀속 불명)"
        };
        Some(format!(
            "환경설정 주입 실패: {parts}{suffix} [{}] {}",
            self.delivery.code, self.delivery.detail
        ))
    }
}
fn names(value: Option<&Value>) -> Option<Vec<&str>> {
    let values = value?.as_array()?;
    values.iter().map(Value::as_str).collect()
}
pub fn preferences_outcome(delivery: DeliveryOutcome, theme_sent: bool) -> PreferencesOutcome {
    let mut expected = vec!["personalization"];
    if theme_sent {
        expected.push("theme");
    }
    let applied = delivery
        .result
        .as_ref()
        .and_then(|result| result.get("applied"));
    let applied_names = match applied {
        Some(Value::Object(map)) => Some(
            map.iter()
                .filter_map(|(name, value)| {
                    value.as_bool().filter(|yes| *yes).map(|_| name.as_str())
                })
                .collect(),
        ),
        other => names(other),
    };
    if let Some(names) = applied_names {
        let applied: Vec<_> = expected
            .iter()
            .copied()
            .filter(|name| names.contains(name))
            .collect();
        let failed: Vec<_> = expected
            .iter()
            .copied()
            .filter(|name| !applied.contains(name))
            .collect();
        let contradiction = failed.is_empty() && !delivery.ok;
        return PreferencesOutcome {
            delivery,
            expected: expected.clone(),
            applied: if contradiction { vec![] } else { applied },
            failed: if contradiction { expected } else { failed },
            attributed: !contradiction,
            notes: if contradiction {
                vec!["applied 와 ok 가 모순".into()]
            } else {
                vec![]
            },
        };
    }
    let missing = delivery
        .result
        .as_ref()
        .and_then(|result| names(result.get("missing")));
    if let Some(names) = missing {
        let failed: Vec<_> = expected
            .iter()
            .copied()
            .filter(|name| names.contains(name))
            .collect();
        if !failed.is_empty() {
            let applied = expected
                .iter()
                .copied()
                .filter(|name| !failed.contains(name))
                .collect();
            return PreferencesOutcome {
                delivery,
                expected,
                applied,
                failed,
                attributed: true,
                notes: vec![],
            };
        }
    }
    if delivery.ok {
        return PreferencesOutcome {
            delivery,
            expected: expected.clone(),
            applied: expected,
            failed: vec![],
            attributed: true,
            notes: vec![],
        };
    }
    PreferencesOutcome {
        delivery,
        expected: expected.clone(),
        applied: vec![],
        failed: expected,
        attributed: false,
        notes: vec![],
    }
}
pub fn classify_preferences(raw: &Value, theme_sent: bool) -> PreferencesOutcome {
    preferences_outcome(classify_result("preferences", raw), theme_sent)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{
        CAPABILITIES, classify_result, deliver_expression, parse_descriptor, preferences_outcome,
        verify_descriptor,
    };
    use serde_json::json;

    #[test]
    fn descriptor_and_delivery_fail_closed_with_distinct_codes() {
        assert_eq!(
            parse_descriptor(&json!(null)).unwrap_err().code,
            "facade-absent"
        );
        assert_eq!(
            parse_descriptor(
                &json!({"protocol": "hwpx-product", "version": true, "capabilities": []})
            )
            .unwrap_err()
            .code,
            "version-unsupported"
        );
        assert_eq!(
            verify_descriptor(
                &json!({"protocol": "hwpx-product", "version": 1.0, "capabilities": CAPABILITIES}),
                None
            )
            .unwrap()
            .version,
            1
        );
        assert_eq!(
            classify_result("snapshot", &json!({"ok": 1})).code,
            "result-ok-not-bool"
        );
        assert_eq!(
            classify_result("close-request", &json!(null)).code,
            "facade-absent"
        );
        assert_eq!(
            classify_result("notice", &json!({"ok": false, "code": "closed"})).code,
            "closed"
        );
    }

    #[test]
    fn preferences_partial_ack_and_js_literal_keep_the_wire_shape() {
        let partial = classify_result(
            "preferences",
            &json!({"ok": true, "applied": ["personalization"]}),
        );
        let outcome = preferences_outcome(partial, true);
        assert_eq!(outcome.failed, ["theme"]);
        assert!(outcome.failure_text().unwrap().contains("테마"));
        let inconsistent = preferences_outcome(
            classify_result(
                "preferences",
                &json!({"ok": false, "applied": ["personalization", "theme"]}),
            ),
            true,
        );
        assert_eq!(inconsistent.failed, ["personalization", "theme"]);
        assert!(!inconsistent.attributed);
        let expression = deliver_expression(
            "snapshot",
            &json!({"screen": "job", "snapshot": {"text": "가\u{2028}나"}}),
        )
        .unwrap();
        assert!(expression.starts_with("window.__hwpx ? window.__hwpx.deliver({\"version\":1,\"event\":\"snapshot\",\"payload\":"));
        assert!(expression.contains("\\u2028"));
    }

    #[test]
    fn malformed_facade_messages_never_become_success_or_a_guessed_capability() {
        for (raw, code) in [
            (json!(42), "descriptor-malformed"),
            (
                json!({"protocol":"other","version":1,"capabilities":CAPABILITIES}),
                "protocol-mismatch",
            ),
            (
                json!({"protocol":"hwpx-product","version":2,"capabilities":CAPABILITIES}),
                "version-unsupported",
            ),
            (
                json!({"protocol":"hwpx-product","version":1,"capabilities":["snapshot",7]}),
                "descriptor-malformed",
            ),
        ] {
            assert_eq!(parse_descriptor(&raw).unwrap_err().code, code);
        }
        assert_eq!(
            verify_descriptor(
                &json!({"protocol":"hwpx-product","version":1,"capabilities":["snapshot"]}),
                None,
            )
            .unwrap_err()
            .code,
            "capability-missing"
        );
        assert_eq!(
            deliver_expression("unregistered", &json!({}))
                .unwrap_err()
                .code,
            "adapter-internal"
        );
        assert_eq!(
            deliver_expression("snapshot", &json!([])).unwrap_err().code,
            "payload-unserializable"
        );
        for (raw, code) in [
            (json!(7), "result-not-object"),
            (json!({}), "result-missing-ok"),
            (json!({"ok":1}), "result-ok-not-bool"),
            (json!({"ok":false,"code":""}), "rejected"),
        ] {
            assert_eq!(classify_result("snapshot", &raw).code, code);
        }
    }
}
