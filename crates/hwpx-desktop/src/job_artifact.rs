//! Delivered HWPX observation for the Job result sheet; bytes are reread on each request.

use super::*;
use crate::artifact_observation::{ArtifactObservation, observe_delivered_artifact};
use base64::Engine;

const NOT_IN_SESSION: &str = "ARTIFACT_NOT_IN_SESSION";
const NOT_IN_SESSION_DETAIL: &str =
    "이 문서는 지금 세션의 생성 결과에 없습니다. 문서를 다시 만든 뒤에 내용을 볼 수 있습니다.";

pub(super) fn closed_view() -> Value {
    json!({"open":false,"ordinal":-1,"filename":"","status":"","detail":""})
}

impl JobController {
    pub fn delivered_artifact(
        &self,
        ordinal: usize,
    ) -> Result<Option<crate::managed_generation_service::DeliveredDocument>, JobControllerError>
    {
        Ok(self
            .state()?
            .delivered
            .iter()
            .find(|item| item.item_ordinal == ordinal)
            .cloned())
    }

    pub fn owned_session_paths(&self) -> Result<Vec<String>, JobControllerError> {
        let state = self.state()?;
        let mut paths = vec![
            state
                .panel_snapshot
                .get("out_dir")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_owned(),
        ];
        paths.extend(
            state
                .delivered
                .iter()
                .map(|item| item.absolute_path.to_string_lossy().into_owned()),
        );
        Ok(paths)
    }

    fn observe_artifact(
        &self,
        ordinal: isize,
    ) -> Result<(Value, Option<Vec<u8>>), JobControllerError> {
        let document = self
            .state()?
            .delivered
            .iter()
            .find(|document| isize::try_from(document.item_ordinal).ok() == Some(ordinal))
            .cloned();
        let Some(document) = document else {
            return Ok((
                json!({"open":true,"ordinal":ordinal,"filename":"","status":NOT_IN_SESSION,"detail":NOT_IN_SESSION_DETAIL}),
                None,
            ));
        };
        let path = &document.absolute_path;
        let name = &document.relative_path;
        let refused = |code: &str, detail: String| {
            (
                json!({"open":true,"ordinal":ordinal,"filename":name,"status":code,"detail":detail}),
                None,
            )
        };
        let bytes = match observe_delivered_artifact(path, &document.output_digest, false)
            .map_err(error)?
        {
            ArtifactObservation::Observed(bytes) => bytes,
            ArtifactObservation::Refused { code, detail } => return Ok(refused(code, detail)),
        };
        Ok((
            json!({"open":true,"ordinal":ordinal,"filename":name,"status":"observed","detail":""}),
            Some(bytes),
        ))
    }
    /// Reopen, verify, and return the exact bytes approved for a native save-as action.
    pub fn observed_artifact_bytes(
        &self,
        ordinal: isize,
    ) -> Result<(Value, Option<Vec<u8>>), JobControllerError> {
        self.observe_artifact(ordinal)
    }
    pub fn artifact_open(&self, ordinal: isize) -> Result<Value, JobControllerError> {
        let (view, _) = self.observe_artifact(ordinal)?;
        self.state()?.artifact_view = view;
        Ok(json!({"ok":true}))
    }
    pub fn artifact_close(&self) -> Result<Value, JobControllerError> {
        self.state()?.artifact_view = closed_view();
        Ok(Value::Null)
    }
    pub fn artifact_content(&self) -> Result<Value, JobControllerError> {
        let view = self.state()?.artifact_view.clone();
        if view["open"] != true || view["status"] != "observed" {
            return Ok(json!({"ok":false,"ordinal":view["ordinal"],
                "status":view["status"].as_str().filter(|item|!item.is_empty()).unwrap_or(NOT_IN_SESSION),
                "detail":view["detail"].as_str().filter(|item|!item.is_empty()).unwrap_or(NOT_IN_SESSION_DETAIL)}));
        }
        let ordinal = view["ordinal"]
            .as_i64()
            .ok_or_else(|| error("산출물 번호가 손상되었습니다."))? as isize;
        let (current, bytes) = self.observe_artifact(ordinal)?;
        let Some(bytes) = bytes else {
            return Ok(
                json!({"ok":false,"ordinal":ordinal,"status":current["status"],"detail":current["detail"]}),
            );
        };
        Ok(
            json!({"ok":true,"ordinal":ordinal,"filename":current["filename"],
            "content":base64::engine::general_purpose::STANDARD.encode(bytes)}),
        )
    }
}

impl JobController {
    pub fn save_artifact_as(
        &self,
        raw_ordinal: &Value,
        save: impl FnOnce(String, Vec<(String, String)>, String) -> Result<Option<String>, String>,
    ) -> Result<Value, String> {
        let Some(ordinal) = raw_ordinal
            .as_i64()
            .map(i128::from)
            .or_else(|| raw_ordinal.as_u64().map(i128::from))
        else {
            return Ok(json!({"ok":false,"status":"SAVE_COPY_FAILED","path":"",
                "detail":format!("문서 번호가 정수가 아닙니다: {}",
                    hwpx_filler::text_render::python_repr(raw_ordinal))}));
        };
        let Ok(ordinal) = isize::try_from(ordinal) else {
            return Ok(artifact_outside_session());
        };
        let (observed, bytes) = self
            .observed_artifact_bytes(ordinal)
            .map_err(|e| e.to_string())?;
        let Some(bytes) = bytes else {
            if observed["status"] == "ARTIFACT_NOT_IN_SESSION" {
                return Ok(artifact_outside_session());
            }
            return Ok(
                json!({"ok":false,"status":observed["status"],"detail":observed["detail"],"path":""}),
            );
        };
        let default_name = observed["filename"]
            .as_str()
            .and_then(|path| Path::new(path).file_name())
            .map(|name| name.to_string_lossy().into_owned())
            .unwrap_or_else(|| "문서.hwpx".into());
        let chosen = save(
            default_name,
            vec![crate::dialogs::hwpx_file_filter()],
            "hwpx".into(),
        )?;
        let Some(path) = chosen.filter(|path| !path.is_empty()) else {
            return Ok(json!({"ok":false,"status":"cancelled","detail":"","path":""}));
        };
        match crate::atomic_file::write_bytes_atomic(Path::new(&path), &bytes) {
            Ok(()) => Ok(json!({"ok":true,"status":"saved","detail":"","path":path})),
            Err(error) => Ok(
                json!({"ok":false,"status":"SAVE_COPY_FAILED","detail":format!("{path} 에 저장하지 못했습니다: {error}"),"path":""}),
            ),
        }
    }
}

fn artifact_outside_session() -> Value {
    json!({"ok":false,"status":"ARTIFACT_NOT_IN_SESSION","path":"",
        "detail":"이 문서는 지금 세션의 생성 결과에 없습니다. 문서를 다시 만든 뒤에 저장할 수 있습니다."})
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(super) mod tests {
    use super::*;
    use std::fs;

    pub(in crate::job_controller) fn observation_push_gate(
        sandbox: &Path,
    ) -> (PushGate, Arc<std::sync::atomic::AtomicUsize>) {
        let pushes = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let sink_count = pushes.clone();
        let publication = crate::workspace_switch::WorkspaceSwitch::new(
            crate::locations::Locations::new(sandbox, None),
            move |_, _| {
                sink_count.fetch_add(1, Ordering::SeqCst);
                Ok(None)
            },
            |_, gate, token| {
                Ok(crate::workspace_switch::WorkspaceGraph::new(
                    None,
                    vec![],
                    gate,
                    token,
                ))
            },
        )
        .unwrap();
        (publication.active().resources.clone(), pushes)
    }

    pub(in crate::job_controller) fn assert_artifact_observation(
        controller: &JobController,
        sandbox: &Path,
        pushes: &std::sync::atomic::AtomicUsize,
    ) {
        use crate::workspace_switch::ScreenController;
        use base64::Engine;
        let bytes = include_bytes!("../../../tests/fixtures/template_v1.hwpx");
        let mut second = hwpx_core::package::HwpxPackage::from_bytes(
            bytes,
            hwpx_core::package::PackageLimits::default(),
        )
        .unwrap();
        second.entries.push(hwpx_core::package::PackageEntry {
            name: "BinData/second.bin".into(),
            data: b"second".to_vec(),
            stored: true,
        });
        let second = second.to_bytes().unwrap();
        let paths = [sandbox.join("result.hwpx"), sandbox.join("second.hwpx")];
        let mut documents = Vec::new();
        for (ordinal, path, content) in [
            (0, &paths[0], bytes.as_slice()),
            (7, &paths[1], second.as_slice()),
        ] {
            fs::write(path, content).unwrap();
            documents.push(crate::managed_generation_service::DeliveredDocument {
                item_ordinal: ordinal,
                record_identity: format!("row-{ordinal}"),
                relative_path: path.file_name().unwrap().to_string_lossy().into_owned(),
                absolute_path: path.clone(),
                collision_disposition: "WRITE_NEW".into(),
                output_digest: hwpx_filler::candidate_revision::blob_digest(content),
                execution_notes: Vec::new(),
            });
        }
        controller.state().unwrap().delivered = documents.clone();
        let dispatch = |action, payload: Value| {
            ScreenController::dispatch(controller, action, &payload).unwrap()
        };
        let closed = dispatch("artifact_content", json!({}));
        assert_eq!(closed["status"], "ARTIFACT_NOT_IN_SESSION");
        assert!(closed.get("content").is_none());
        assert!(
            ScreenController::dispatch(controller, "artifact_content", &json!({"ordinal":0}))
                .is_err()
        );
        for (ordinal, filename, content) in [
            (0, "result.hwpx", bytes.as_slice()),
            (7, "second.hwpx", second.as_slice()),
        ] {
            assert_eq!(
                dispatch("artifact_open", json!({"ordinal":ordinal})),
                json!({"ok":true})
            );
            let snapshot = controller.snapshot().unwrap();
            assert_eq!(
                snapshot["artifact_view"],
                json!({"open":true,"ordinal":ordinal,"filename":filename,"status":"observed","detail":""})
            );
            let count = pushes.load(Ordering::SeqCst);
            let reply = dispatch("artifact_content", json!({}));
            assert_eq!(reply["ordinal"], ordinal);
            assert_eq!(reply["filename"], filename);
            assert_eq!(
                base64::engine::general_purpose::STANDARD
                    .decode(reply["content"].as_str().unwrap())
                    .unwrap(),
                content
            );
            assert_eq!(controller.snapshot().unwrap(), snapshot);
            assert_eq!(
                pushes.load(Ordering::SeqCst),
                count,
                "content query must not push"
            );
        }
        assert_artifact_save(controller, sandbox, &paths[0], bytes);
        fs::write(&paths[1], b"changed").unwrap();
        let changed = dispatch("artifact_content", json!({}));
        assert_eq!(changed["status"], "ARTIFACT_DIGEST_MISMATCH");
        assert!(changed.get("content").is_none());
        assert!(
            changed["detail"]
                .as_str()
                .unwrap()
                .contains(&documents[1].output_digest)
        );
        dispatch("artifact_open", json!({"ordinal":7}));
        assert_eq!(
            controller.snapshot().unwrap()["artifact_view"]["status"],
            "ARTIFACT_DIGEST_MISMATCH"
        );
        fs::remove_file(&paths[1]).unwrap();
        dispatch("artifact_open", json!({"ordinal":7}));
        assert_eq!(
            controller.snapshot().unwrap()["artifact_view"]["status"],
            "ARTIFACT_FILE_MISSING"
        );
        assert_eq!(
            dispatch("artifact_content", json!({}))["status"],
            "ARTIFACT_FILE_MISSING"
        );
        dispatch("artifact_open", json!({"ordinal":99}));
        assert_eq!(
            controller.snapshot().unwrap()["artifact_view"]["status"],
            "ARTIFACT_NOT_IN_SESSION"
        );
        dispatch("artifact_close", json!({}));
        assert_eq!(
            controller.snapshot().unwrap()["artifact_view"],
            closed_view()
        );
        assert_eq!(
            dispatch("artifact_content", json!({}))["status"],
            "ARTIFACT_NOT_IN_SESSION"
        );
        for swap_data in [true, false] {
            controller.state().unwrap().delivered = documents.clone();
            dispatch("artifact_open", json!({"ordinal":0}));
            let owned = artifact_owned_paths(controller, sandbox);
            for path in [&paths[0], &sandbox.join("templates")] {
                crate::owned_paths::validate_owned_path(path.to_str().unwrap(), &owned, sandbox)
                    .unwrap();
            }
            for path in [
                sandbox.join("other.hwpx"),
                sandbox.join("templates/untracked.hwpx"),
            ] {
                assert!(
                    crate::owned_paths::validate_owned_path(
                        path.to_str().unwrap(),
                        &owned,
                        sandbox
                    )
                    .is_err()
                );
            }
            if swap_data {
                let data = controller.data().unwrap();
                assert!(
                    controller
                        .load_data_path(&sandbox.join("absent.csv"), None, 0)
                        .is_err()
                );
                assert_eq!(controller.state().unwrap().delivered, documents);
                assert_eq!(controller.state().unwrap().artifact_view["open"], true);
                controller
                    .load_data_path(
                        Path::new(&data.path),
                        None,
                        data.header_row.try_into().unwrap(),
                    )
                    .unwrap();
            } else {
                controller.select_job("").unwrap();
            }
            assert!(controller.delivered_artifact(0).unwrap().is_none());
            assert!(
                crate::owned_paths::validate_owned_path(
                    paths[0].to_str().unwrap(),
                    &artifact_owned_paths(controller, sandbox),
                    sandbox
                )
                .is_err()
            );
            assert_eq!(controller.state().unwrap().artifact_view, closed_view());
            assert!(
                !controller
                    .owned_session_paths()
                    .unwrap()
                    .contains(&paths[0].to_string_lossy().into_owned())
            );
        }
    }

    fn artifact_owned_paths(controller: &JobController, sandbox: &Path) -> HashSet<String> {
        let mut session = controller.owned_session_paths().unwrap();
        session.push(sandbox.join("templates").to_string_lossy().into_owned());
        crate::owned_paths::collect_owned_paths(
            &controller.registry,
            &controller.pool,
            &session,
            sandbox,
        )
        .unwrap()
    }

    fn assert_artifact_save(
        controller: &JobController,
        sandbox: &Path,
        source: &Path,
        bytes: &[u8],
    ) {
        let target = sandbox.join("copy.hwpx");
        let result = controller
            .save_artifact_as(&json!(0), |name, filters, extension| {
                assert_eq!(name, "result.hwpx");
                assert_eq!(filters, vec![("HWPX (*.hwpx)".into(), "*.hwpx".into())]);
                assert_eq!(extension, "hwpx");
                Ok(Some(target.to_string_lossy().into_owned()))
            })
            .unwrap();
        assert_eq!(
            result,
            json!({"ok":true,"status":"saved","detail":"","path":target})
        );
        assert_eq!(fs::read(&target).unwrap(), bytes);
        for choice in [None, Some(String::new())] {
            let cancelled = controller
                .save_artifact_as(&json!(0), |_, _, _| Ok(choice))
                .unwrap();
            assert_eq!(
                cancelled,
                json!({"ok":false,"status":"cancelled","detail":"","path":""})
            );
        }
        assert_eq!(fs::read(&target).unwrap(), bytes);
        let failed = controller
            .save_artifact_as(&json!(0), |_, _, _| {
                Ok(Some(
                    sandbox
                        .join("absent/copy.hwpx")
                        .to_string_lossy()
                        .into_owned(),
                ))
            })
            .unwrap();
        assert_eq!(failed["status"], "SAVE_COPY_FAILED");
        assert_eq!(failed["path"], "");
        assert!(!failed["detail"].as_str().unwrap().is_empty());
        assert_eq!(
            controller
                .save_artifact_as(&json!(0), |_, _, _| Err("host failed".into()))
                .unwrap_err(),
            "host failed"
        );
        for value in [json!("0"), json!(false), Value::Null, json!(0.5)] {
            let rejected = controller
                .save_artifact_as(&value, |_, _, _| panic!("invalid ordinal opened picker"))
                .unwrap();
            assert_eq!(rejected["status"], "SAVE_COPY_FAILED");
        }
        for value in [json!(99), json!(-1), json!(u64::MAX)] {
            let rejected = controller
                .save_artifact_as(&value, |_, _, _| panic!("missing ordinal opened picker"))
                .unwrap();
            assert_eq!(rejected["status"], "ARTIFACT_NOT_IN_SESSION");
        }
        fs::write(source, b"tampered").unwrap();
        let refused = controller
            .save_artifact_as(&json!(0), |_, _, _| panic!("unverified file opened picker"))
            .unwrap();
        assert_eq!(refused["status"], "ARTIFACT_DIGEST_MISMATCH");
        assert_eq!(refused["path"], "");
        fs::write(source, bytes).unwrap();
    }
}
