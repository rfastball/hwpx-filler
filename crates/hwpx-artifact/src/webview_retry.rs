//! Narrow WebView2 cold-boot classification for the packaged selftest retry gate.

use serde::Serialize;
use serde_json::Value;
use std::fs;
use std::path::Path;

#[derive(Debug, Serialize)]
pub struct Verdict {
    pub verdict: &'static str,
    pub reason: &'static str,
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_none_or(|value| value != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

pub fn classify(evidence: &Value) -> Verdict {
    let runtime = evidence.get("runtime");
    for (flag, reason) in [
        (
            "external_fetch_completed",
            "제품 증거가 있다: runtime.external_fetch_completed=true — 창이 떠서 판정 지점까지 갔다",
        ),
        (
            "external_fetch_succeeded",
            "제품 증거가 있다: runtime.external_fetch_succeeded=true — 창이 떠서 판정 지점까지 갔다",
        ),
        (
            "external_fetch_blocked",
            "제품 증거가 있다: runtime.external_fetch_blocked=true — 창이 떠서 판정 지점까지 갔다",
        ),
    ] {
        if runtime.and_then(|value| value.get(flag)) == Some(&Value::Bool(true)) {
            return Verdict {
                verdict: "not-environment",
                reason,
            };
        }
    }
    if runtime
        .and_then(|value| value.get("forbidden_resources"))
        .is_some_and(truthy)
    {
        return Verdict {
            verdict: "not-environment",
            reason: "제품 증거가 있다: forbidden_resources 비어 있지 않음",
        };
    }
    let Some(error) = evidence
        .get("error")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
    else {
        return Verdict {
            verdict: "not-environment",
            reason: "error 부재 — 분류할 실패가 없다",
        };
    };
    if error.contains("[evaluate-failed]") && error.contains("Main window failed to start") {
        return Verdict {
            verdict: "environment-boot-failure",
            reason: "콜드 부팅 실패 — 창이 서기 전의 통로 실패라 제품에 대해 아무것도 말하지 않는다",
        };
    }
    Verdict {
        verdict: "not-environment",
        reason: "환경 서명 밖의 실패 — 제품 판정으로 남긴다",
    }
}

pub fn classify_file(path: &Path) -> Result<Verdict, String> {
    let bytes = fs::read(path)
        .map_err(|error| format!("증거를 읽지 못해 판정 불능: {} ({error})", path.display()))?;
    let evidence: Value = serde_json::from_slice(&bytes)
        .map_err(|error| format!("증거를 읽지 못해 판정 불능: {} ({error})", path.display()))?;
    if !evidence.is_object() {
        return Err(format!(
            "증거가 객체가 아니라 판정 불능: {}",
            path.display()
        ));
    }
    Ok(classify(&evidence))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::classify;
    use serde_json::json;

    #[test]
    fn product_evidence_always_beats_the_exact_cold_boot_signature() {
        let boot = "자가검증 full 실패 [evaluate-failed] readiness 평가 실패: WebViewException('Main window failed to start')";
        assert_eq!(
            classify(&json!({"error":boot})).verdict,
            "environment-boot-failure"
        );
        for runtime in [
            json!({"external_fetch_blocked":true}),
            json!({"external_fetch_completed":true}),
            json!({"external_fetch_succeeded":true}),
            json!({"forbidden_resources":["https://example.com/x.js"]}),
        ] {
            assert_eq!(
                classify(&json!({"error":boot,"runtime":runtime})).verdict,
                "not-environment"
            );
        }
        for evidence in [
            json!({"error":"자가검증 full 실패 [refused] 다른 이유"}),
            json!({"error":"readiness 평가 실패: Main window failed to start"}),
            json!({}),
        ] {
            assert_eq!(classify(&evidence).verdict, "not-environment");
        }
    }
}
