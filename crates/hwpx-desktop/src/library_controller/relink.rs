//! Template relink for a stored work: media, structure, and token checks before confirmation.

use super::*;

impl LibraryController {
    pub(super) fn cross_media_refusal(name: &str, old_path: &str, new_media: &str) -> Value {
        let noun = if new_media == "txt" {
            "온나라 기안 TXT"
        } else {
            "HWPX"
        };
        json!({"ok":false,"error":format!(
            "작업 '{name}' 은(는) '{}' 작업이라 {noun} 템플릿을 연결할 수 없습니다. 작업 방식을 바꾸려면 이 작업을 삭제하고 새로 만드세요.",
            work_mode_label(work_mode(old_path)))})
    }
    pub(super) fn read_relink_template(path: &str) -> Result<Vec<u8>, String> {
        read_template(Path::new(path)).map_err(|error| {
            let Some(code) = error.raw_os_error() else {
                return error.to_string();
            };
            let raw = error.to_string();
            let detail = raw
                .split(" (os error ")
                .next()
                .unwrap_or(&raw)
                .trim_end_matches('.');
            format!("[WinError {code}] {detail}: {}", python_repr(&json!(path)))
        })
    }
    pub(super) fn relink_template(
        &self,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let generation_active = (self.generation_active)();
        if generation_active {
            return Err("문서 생성이 진행 중입니다. 끝난 뒤에 템플릿을 다시 연결하세요.".into());
        }
        let name = payload
            .get("name")
            .and_then(Value::as_str)
            .ok_or("name required")?;
        let path = payload.get("path").and_then(Value::as_str).unwrap_or("");
        Self::relink_job_template(
            &self.jobs,
            false,
            name,
            path,
            Self::truthy(payload.get("confirm")),
        )
    }

    pub fn relink_job_template(
        jobs: &JobRegistry,
        generation_active: bool,
        name: &str,
        path: &str,
        confirm: bool,
    ) -> Result<Value, GraphError> {
        if generation_active {
            return Err("문서 생성이 진행 중입니다. 끝난 뒤에 템플릿을 다시 연결하세요.".into());
        }
        if path.is_empty() {
            return Ok(json!({"ok":false,"error":"새 템플릿 경로가 비어 있습니다."}));
        }
        let job = match load_relink_job(jobs, name) {
            Ok(job) => job,
            Err(refusal) => return Ok(refusal),
        };
        let drift_clause = match relink_preflight(&job, name, path) {
            Ok(clause) => clause,
            Err(refusal) => return Ok(refusal),
        };
        if !confirm {
            return Ok(relink_confirmation(&job, name, path, &drift_clause));
        }
        commit_relink(jobs, job, name, path)
    }
}

fn load_relink_job(jobs: &JobRegistry, name: &str) -> Result<Job, Value> {
    match jobs.load(name) {
        Ok(job) => Ok(job),
        Err(StoreError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => Err(
            json!({"ok":false,"error":format!("작업을 찾을 수 없습니다(이미 삭제된 작업): {name}")}),
        ),
        Err(error) => Err(json!({"ok":false,"error":format!("작업을 읽을 수 없습니다: {error}")})),
    }
}

/// Media and template checks before confirmation; `Ok` carries the structure drift clause.
fn relink_preflight(job: &Job, name: &str, path: &str) -> Result<String, Value> {
    let old_media = template_media(&job.template_path);
    let new_media = template_media(path);
    if !matches!(new_media, "hwpx" | "txt") {
        return Err(
            json!({"ok":false,"error":"새 템플릿이 HWPX 도 온나라 기안 TXT 도 아닙니다. HWPX 또는 TXT 파일을 선택하세요."}),
        );
    }
    if matches!(old_media, "hwpx" | "txt") && old_media != new_media {
        return Err(LibraryController::cross_media_refusal(
            name,
            &job.template_path,
            new_media,
        ));
    }
    if new_media == "hwpx" {
        hwpx_drift_clause(job, path)
    } else {
        txt_template_check(path).map(|()| String::new())
    }
}

/// A readable HWPX whose structure differs from the confirmed mapping still relinks, with a warning.
fn hwpx_drift_clause(job: &Job, path: &str) -> Result<String, Value> {
    let fields = LibraryController::read_relink_template(path)
        .and_then(|bytes| {
            hwpx_core::package::HwpxPackage::from_bytes(
                &bytes,
                hwpx_core::package::PackageLimits::default(),
            )
            .map_err(|e| e.to_string())
        })
        .and_then(|package| {
            hwpx_filler::fields::required_fields(&package).map_err(|e| e.to_string())
        });
    let drift = StructureDrift::from_fields(job, fields);
    if !drift.read_error.is_empty() {
        return Err(
            json!({"ok":false,"error":format!("새 템플릿을 읽을 수 없습니다: {}",drift.read_error)}),
        );
    }
    if drift.has_drift() {
        return Ok(format!(
            "\n\n⚠ 새 파일의 구조가 이 작업의 확정 매핑과 다릅니다:\n{}\n매핑을 다시 확정하기 전에는 생성이 차단됩니다.",
            drift.describe("\n")
        ));
    }
    Ok(String::new())
}

/// A TXT template must decode as UTF-8 and carry at least one fill token.
fn txt_template_check(path: &str) -> Result<(), Value> {
    let text = LibraryController::read_relink_template(path)
        .and_then(|bytes| String::from_utf8(bytes).map_err(|e| e.to_string()));
    let text = match text {
        Ok(text) => text,
        Err(error) => {
            return Err(
                json!({"ok":false,"error":format!("새 템플릿을 읽을 수 없습니다: {error}")}),
            );
        }
    };
    if hwpx_filler::text_render::template_fields(&text).is_empty() {
        return Err(
            json!({"ok":false,"error":"채울 {{토큰}}이 없는 TXT 템플릿입니다.\n목록의 행 ⋮ → '내용 편집'에서 원문에 {{필드이름}} 토큰을 넣은 뒤 다시 고르세요."}),
        );
    }
    Ok(())
}

fn relink_confirmation(job: &Job, name: &str, path: &str, drift_clause: &str) -> Value {
    let old_media = template_media(&job.template_path);
    let history_clause = if !matches!(old_media, "hwpx" | "txt") && !job.last_run_at.is_empty() {
        "\n\n형식을 확인할 수 없던 작업이라 최근 사용 기록은 함께 지워집니다."
    } else {
        ""
    };
    let old = if job.template_path.is_empty() {
        "(비어 있음)"
    } else {
        &job.template_path
    };
    json!({"ok":true,"needs_confirm":true,"name":name,
        "confirm_text":format!("작업 '{name}' 의 템플릿 연결을 바꿉니다.\n기존: {old}\n새 파일: {path}{drift_clause}{history_clause}")})
}

fn commit_relink(
    jobs: &JobRegistry,
    job: Job,
    name: &str,
    path: &str,
) -> Result<Value, GraphError> {
    let old = job.template_path;
    match jobs.relink_template(name, path, None) {
        Ok(_) => Ok(
            json!({"ok":true,"relinked":true,"name":name,"old":old,"path":path,
            "restated":"템플릿을 다시 연결했습니다."}),
        ),
        Err(StoreError::CrossMedia {
            old_path,
            new_media,
        }) => Ok(LibraryController::cross_media_refusal(
            name, &old_path, new_media,
        )),
        Err(error) => Err(error.into()),
    }
}
