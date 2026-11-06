//! Shared configured template root for HWPX, TXT, imports, and Job links.

use crate::shell_settings::ShellSettings;
use hwpx_filler::template_library_state::{TemplateRootResolution, resolve_templates_root};
use std::io;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

pub struct TemplateRoot {
    settings: Arc<ShellSettings>,
    default_root: PathBuf,
    cached: Mutex<TemplateRootResolution>,
}
impl TemplateRoot {
    pub fn new(settings: Arc<ShellSettings>, default_root: PathBuf) -> io::Result<Self> {
        let configured = settings.load_templates_root()?;
        let cached = resolve(&configured, &default_root)?;
        Ok(Self {
            settings,
            default_root,
            cached: Mutex::new(cached),
        })
    }
    pub fn resolution(&self) -> TemplateRootResolution {
        self.cached
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone()
    }
    pub fn path(&self) -> PathBuf {
        PathBuf::from(self.resolution().directory)
    }
    pub fn set(&self, path: &str) -> io::Result<TemplateRootResolution> {
        // Hold the same lock across persistence and publication so readers never see a later
        // selection replaced by an earlier caller's delayed update.
        let mut cached = self
            .cached
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        self.settings.save_templates_root(path)?;
        let next = resolve(path, &self.default_root)?;
        *cached = next.clone();
        Ok(next)
    }
}

fn resolve(configured: &str, default_root: &Path) -> io::Result<TemplateRootResolution> {
    let root = default_root.to_str().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            "서식 폴더 경로를 읽을 수 없습니다",
        )
    })?;
    Ok(resolve_templates_root(
        configured,
        !configured.is_empty() && Path::new(configured).is_dir(),
        root,
    ))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::TemplateRoot;
    use crate::shell_settings::ShellSettings;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::Arc;

    #[test]
    fn configured_missing_root_stays_selected_until_replaced() {
        let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let root = repo.join(format!(".cache/template-root-owner-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let settings = Arc::new(ShellSettings::new(root.join("settings.json"), |_| {}));
        assert_eq!(settings.load_templates_root().unwrap(), "");
        let default = root.join("default");
        let selection = TemplateRoot::new(settings.clone(), default.clone()).unwrap();
        assert_eq!(selection.path(), default);
        assert_eq!(selection.resolution().source, "default");
        let missing = root.join("missing");
        let selected = selection.set(missing.to_str().unwrap()).unwrap();
        assert_eq!(selection.path(), missing);
        assert_eq!(selected.source, "configured");
        assert!(!selected.notice.is_empty());
        assert!(selection.set(" \u{1c} ").is_err());
        assert_eq!(selection.path(), missing);
        assert_eq!(
            settings.load_templates_root().unwrap(),
            missing.to_str().unwrap()
        );
        fs::create_dir_all(&missing).unwrap();
        assert!(!selection.resolution().notice.is_empty());
        let refreshed = selection.set(missing.to_str().unwrap()).unwrap();
        assert_eq!(refreshed.source, "configured");
        assert_eq!(refreshed.notice, "");
        assert_eq!(selection.resolution(), refreshed);
        assert_eq!(
            settings.load_templates_root().unwrap(),
            missing.to_str().unwrap()
        );
        // A later reader must use the published root without another settings read.
        fs::write(root.join("settings.json"), [0xff]).unwrap();
        assert!(settings.load_templates_root().is_err());
        assert_eq!(selection.path(), missing);
        assert_eq!(selection.resolution(), refreshed);
        assert!(selection.set(default.to_str().unwrap()).is_err());
        assert_eq!(selection.resolution(), refreshed);
        assert!(
            root.canonicalize()
                .unwrap()
                .starts_with(repo.canonicalize().unwrap())
        );
        fs::remove_dir_all(root).unwrap();
    }
}
