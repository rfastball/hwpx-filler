//! Windowless release smoke using the sealed web tree and native template/editor graph.

use crate::dataset_registry::DatasetPoolRegistry;
use crate::editor_controller::EditorController;
use crate::job_registry::JobRegistry;
use crate::locations::Locations;
use crate::shell_settings::ShellSettings;
use crate::template_inventory::TemplateInventory;
use crate::template_root::TemplateRoot;
use crate::workspace_switch::{ScreenController, WorkspaceGraph, WorkspaceSwitch};
use hwpx_artifact::resolve_frozen;
use serde::Serialize;
use serde_json::{Value, json};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use uuid::Uuid;

const SAMPLE: &str = "제목: {{공고명}} / 담당: {{담당자}}";

#[derive(Debug, Serialize)]
pub struct SelfcheckEvidence {
    pub artifact_id: String,
    pub tree_sha256: String,
    pub viewmodel_ok: bool,
}

struct Scratch(PathBuf);
impl Scratch {
    fn new() -> io::Result<Self> {
        let root = std::env::temp_dir().join(format!("documentnarmi-selfcheck-{}", Uuid::new_v4()));
        fs::create_dir(&root)?;
        Ok(Self(root))
    }
}
impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

/// Verify the packaged bytes and the native TXT library-to-editor projection without a window.
pub fn run(resources: &Path) -> Result<SelfcheckEvidence, String> {
    let artifact = resolve_frozen(resources).map_err(|error| error.to_string())?;
    // Snapshot the exact bytes a WebView would receive; a seal alone is insufficient.
    artifact
        .snapshot_bytes()
        .map_err(|error| error.to_string())?;
    viewmodel_smoke()?;
    Ok(SelfcheckEvidence {
        artifact_id: artifact.artifact_id,
        tree_sha256: artifact.tree_sha256,
        viewmodel_ok: true,
    })
}

fn viewmodel_smoke() -> Result<(), String> {
    let scratch = Scratch::new().map_err(|error| error.to_string())?;
    let template = scratch.0.join("샘플.txt");
    fs::write(&template, SAMPLE).map_err(|error| error.to_string())?;
    let settings = Arc::new(ShellSettings::new(scratch.0.join("settings.json"), |_| {}));
    let templates = Arc::new(
        TemplateRoot::new(settings, scratch.0.clone()).map_err(|error| error.to_string())?,
    );
    let inventory = TemplateInventory::read(&templates).map_err(|error| error.to_string())?;
    if !inventory
        .rows
        .iter()
        .any(|row| row.media == "txt" && row.name == "샘플")
    {
        return Err("TXT 템플릿 목록 검사에 실패했습니다.".into());
    }
    let jobs_root = templates.clone();
    let jobs = Arc::new(
        JobRegistry::new(scratch.0.join("jobs"), move || jobs_root.path())
            .map_err(|error| error.to_string())?,
    );
    let datasets = Arc::new(
        DatasetPoolRegistry::new(scratch.0.join("datasets")).map_err(|error| error.to_string())?,
    );
    let graph = WorkspaceSwitch::new(Locations::new(&scratch.0, None), |_, _| Ok(None), {
        move |home, push, token| {
            let editor: Arc<dyn ScreenController> = Arc::new(EditorController::new(
                jobs.clone(),
                templates.clone(),
                datasets.clone(),
                push,
            )?);
            Ok(WorkspaceGraph::new(
                home.map(Path::to_path_buf),
                vec![("editor".into(), editor)],
                (),
                token,
            ))
        }
    })
    .map_err(|error| error.to_string())?;
    let editor = graph
        .active()
        .controller("editor")
        .ok_or("편집기 화면이 없습니다.")?;
    editor
        .dispatch("use_library_template", &json!({"path": template}))
        .map_err(|error| error.to_string())?;
    let snapshot = editor.initial().map_err(|error| error.to_string())?;
    if !viewmodel_ok(&snapshot) {
        return Err("TXT 편집기 스냅샷 검사에 실패했습니다.".into());
    }
    Ok(())
}

fn viewmodel_ok(snapshot: &Value) -> bool {
    snapshot["sections"] == json!(["template", "binding", "filename"])
        && snapshot["fields"]
            .as_array()
            .is_some_and(|fields| fields.iter().any(|field| field["name"] == "공고명"))
        && snapshot["pairing"]["template_name"] == "샘플"
        && snapshot["pairing"]["ready"] == false
        && snapshot["name"] == "샘플"
        && snapshot["job_name_is_derived"] == true
}

/// The caller writes this evidence even after a failed smoke and then exits finitely.
pub fn write_evidence(path: &Path, result: &Result<SelfcheckEvidence, String>) -> io::Result<()> {
    let value = match result {
        Ok(evidence) => serde_json::to_value(evidence)?,
        Err(error) => json!({"error":error,"viewmodel_ok":false}),
    };
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, format!("{}\n", serde_json::to_string_pretty(&value)?))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{viewmodel_ok, viewmodel_smoke, write_evidence};
    use serde_json::json;
    use std::fs;
    use std::path::PathBuf;

    #[test]
    fn missing_editor_contract_fails_and_error_evidence_is_finite() {
        viewmodel_smoke().unwrap();
        let mut projection = json!({"sections":["template","binding","filename"],
            "fields":[{"name":"공고명"}],"pairing":{"template_name":"샘플","ready":false},
            "name":"샘플","job_name_is_derived":true});
        assert!(viewmodel_ok(&projection));
        projection["pairing"]["ready"] = json!(true);
        assert!(!viewmodel_ok(&projection));
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/packaged-selfcheck-owner")
            .join(format!("{}-evidence.json", std::process::id()));
        write_evidence(&path, &Err("seal invalid".into())).unwrap();
        let evidence: serde_json::Value =
            serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(
            evidence,
            json!({"error":"seal invalid","viewmodel_ok":false})
        );
        fs::remove_file(path).unwrap();
    }
}
