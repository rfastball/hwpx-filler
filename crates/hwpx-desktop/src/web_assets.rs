//! Immutable bytes for the Tauri custom protocol, sourced only from a verified seal.

use hwpx_artifact::{VerifiedArtifact, Violation, resolve_frozen, resolve_source};
use std::borrow::Cow;
use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;
use tauri::utils::assets::{AssetKey, AssetsIter, CspHash};
use tauri::{Assets, Runtime};

#[derive(Clone)]
pub struct WebAssets {
    pub artifact_id: String,
    pub tree_sha256: String,
    files: Arc<BTreeMap<String, Vec<u8>>>,
}

impl WebAssets {
    fn from_verified(verified: VerifiedArtifact) -> Result<Self, Violation> {
        let files = verified.snapshot_bytes()?;
        Ok(Self {
            artifact_id: verified.artifact_id,
            tree_sha256: verified.tree_sha256,
            files: Arc::new(files),
        })
    }

    pub fn source(repo: &Path) -> Result<Self, Violation> {
        Self::from_verified(resolve_source(repo)?)
    }

    pub fn frozen(frozen: &Path) -> Result<Self, Violation> {
        Self::from_verified(resolve_frozen(frozen)?)
    }

    /// The protocol never opens a file after this snapshot is built.
    pub fn get(&self, request_path: &str) -> Option<(&[u8], &'static str)> {
        let path = if request_path == "/" {
            "index.html"
        } else {
            request_path.strip_prefix('/')?
        };
        // Encoded separators and normalization are not accepted at the URI boundary.
        if path.is_empty()
            || path.contains(['%', '\\', '?', '#'])
            || path
                .split('/')
                .any(|segment| segment.is_empty() || segment == "." || segment == "..")
        {
            return None;
        }
        let bytes = self.files.get(path)?;
        let mime = match Path::new(path)
            .extension()
            .and_then(|ext| ext.to_str())
            .unwrap_or("")
        {
            "html" | "htm" => "text/html; charset=utf-8",
            "js" | "mjs" => "text/javascript; charset=utf-8",
            "css" => "text/css; charset=utf-8",
            "json" => "application/json; charset=utf-8",
            "svg" => "image/svg+xml",
            "wasm" => "application/wasm",
            "woff2" => "font/woff2",
            "png" => "image/png",
            "ico" => "image/x-icon",
            _ => "application/octet-stream",
        };
        Some((bytes, mime))
    }
}

impl<R: Runtime> Assets<R> for WebAssets {
    fn get(&self, key: &AssetKey) -> Option<Cow<'_, [u8]>> {
        WebAssets::get(self, key.as_ref()).map(|(bytes, _)| Cow::Borrowed(bytes))
    }

    fn iter(&self) -> Box<AssetsIter<'_>> {
        Box::new(self.files.iter().map(|(path, bytes)| {
            (
                Cow::Owned(format!("/{path}")),
                Cow::Borrowed(bytes.as_slice()),
            )
        }))
    }

    fn csp_hashes(&self, _html_path: &AssetKey) -> Box<dyn Iterator<Item = CspHash<'_>> + '_> {
        Box::new(std::iter::empty())
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::WebAssets;
    use crate::tauri_host::verified_context;
    use std::collections::BTreeMap;
    use std::sync::Arc;

    #[test]
    fn protocol_exposes_only_exact_snapshotted_paths() {
        let files = BTreeMap::from([
            ("index.html".into(), b"home".to_vec()),
            ("rhwp/studio/index.html".into(), b"studio".to_vec()),
        ]);
        let assets = WebAssets {
            artifact_id: "id".into(),
            tree_sha256: "tree".into(),
            files: Arc::new(files),
        };
        assert_eq!(assets.get("/").unwrap().0, b"home");
        assert_eq!(assets.get("/rhwp/studio/index.html").unwrap().0, b"studio");
        let context = verified_context(assets.clone());
        let key = tauri::utils::assets::AssetKey::from("index.html");
        assert_eq!(context.assets().get(&key).unwrap().as_ref(), b"home");
        for path in [
            "/../index.html",
            "//index.html",
            "/%2e%2e/index.html",
            "/rhwp\\studio/index.html",
            "/missing.html",
        ] {
            assert!(assets.get(path).is_none(), "{path}");
        }
    }
}
