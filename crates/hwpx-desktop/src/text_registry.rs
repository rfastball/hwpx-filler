//! Workspace TXT template inventory; token semantics stay in hwpx-filler.

use crate::template_inventory::discover_paths;
use hwpx_filler::text_render::template_fields;
use std::fs;
use std::io;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TextTemplate {
    pub name: String,
    pub path: PathBuf,
}
impl TextTemplate {
    pub fn content(&self) -> io::Result<String> {
        fs::read_to_string(&self.path)
    }
    pub fn fields(&self) -> io::Result<Vec<String>> {
        Ok(template_fields(&self.content()?))
    }
}

pub struct TextTemplateRegistry {
    root: Arc<dyn Fn() -> PathBuf + Send + Sync>,
    write_lock: Mutex<()>,
}
impl TextTemplateRegistry {
    pub fn new(root: PathBuf) -> Self {
        Self::with_root(move || root.clone())
    }
    pub fn with_root(root: impl Fn() -> PathBuf + Send + Sync + 'static) -> Self {
        Self {
            root: Arc::new(root),
            write_lock: Mutex::new(()),
        }
    }
    pub fn directory(&self) -> PathBuf {
        (self.root)()
    }
    pub fn write_lock(&self) -> &Mutex<()> {
        &self.write_lock
    }
    pub fn list_templates(&self) -> io::Result<Vec<TextTemplate>> {
        let root = self.directory();
        let mut files = discover_paths(&root)?;
        files.retain(|path| {
            path.extension()
                .is_some_and(|ext| ext.eq_ignore_ascii_case("txt"))
        });
        files.sort_by(|left, right| {
            left.file_name()
                .cmp(&right.file_name())
                .then_with(|| left.cmp(right))
        });
        files
            .into_iter()
            .map(|path| {
                let relative = path.strip_prefix(&root).map_err(|_| {
                    io::Error::new(io::ErrorKind::InvalidData, "template escaped root")
                })?;
                let without_ext = relative.with_extension("");
                let name = without_ext
                    .to_str()
                    .ok_or_else(|| {
                        io::Error::new(io::ErrorKind::InvalidData, "template name is not Unicode")
                    })?
                    .replace('\\', "/");
                Ok(TextTemplate { name, path })
            })
            .collect()
    }
    pub fn names(&self) -> io::Result<Vec<String>> {
        Ok(self
            .list_templates()?
            .into_iter()
            .map(|template| template.name)
            .collect())
    }
    pub fn count(&self) -> io::Result<usize> {
        Ok(self.list_templates()?.len())
    }
    pub fn load(&self, name: &str) -> io::Result<TextTemplate> {
        if let Some(found) = self
            .list_templates()?
            .into_iter()
            .find(|template| template.name == name)
        {
            return Ok(found);
        }
        Ok(TextTemplate {
            name: name.into(),
            path: self.directory().join(format!("{name}.txt")),
        })
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::TextTemplateRegistry;
    use std::fs;
    use std::path::Path;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex};
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn recursive_inventory_keeps_unique_names_and_switches_roots() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-text-registry-{}-{stamp}",
            std::process::id()
        ));
        let first = root.join("first");
        let second = root.join("second");
        for directory in [
            first.join("a"),
            first.join("b"),
            first.join("Results"),
            first.join(".trash"),
            second.clone(),
        ] {
            fs::create_dir_all(directory).unwrap();
        }
        fs::write(first.join("a/same.txt"), "A {{가}}").unwrap();
        fs::write(first.join("b/same.txt"), "B {{나}}").unwrap();
        fs::write(first.join("Results/ignored.txt"), "ignored").unwrap();
        fs::write(first.join(".trash/deleted.txt"), "deleted").unwrap();
        fs::write(second.join("new.txt"), "{{새것}}").unwrap();
        let current = Arc::new(Mutex::new(first.clone()));
        let watched = current.clone();
        let reads = Arc::new(AtomicUsize::new(0));
        let counted = reads.clone();
        let registry = TextTemplateRegistry::with_root(move || {
            counted.fetch_add(1, Ordering::Relaxed);
            watched.lock().unwrap().clone()
        });
        assert_eq!(registry.names().unwrap(), ["a/same", "b/same"]);
        assert_eq!(reads.load(Ordering::Relaxed), 1);
        assert_eq!(registry.count().unwrap(), 2);
        assert_eq!(
            registry.load("a/same").unwrap().content().unwrap(),
            "A {{가}}"
        );
        assert_eq!(
            registry.load("b/same").unwrap().path,
            first.join("b/same.txt")
        );
        assert_eq!(registry.load("b/same").unwrap().fields().unwrap(), ["나"]);
        let absent = registry.load("없는이름").unwrap();
        assert_eq!(absent.path, first.join("없는이름.txt"));
        assert!(absent.content().is_err());
        let missing = TextTemplateRegistry::new(root.join("missing"));
        assert!(missing.names().unwrap().is_empty());
        assert_eq!(missing.count().unwrap(), 0);
        *current.lock().unwrap() = second;
        assert_eq!(registry.names().unwrap(), ["new"]);
        *current.lock().unwrap() = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus/scenario/text_templates");
        assert_eq!(registry.names().unwrap(), ["게시요약", "온나라기안"]);
        assert!(
            registry
                .load("게시요약")
                .unwrap()
                .fields()
                .unwrap()
                .contains(&"입찰방법".into())
        );
        assert!(
            root.canonicalize().unwrap().starts_with(
                Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../..")
                    .canonicalize()
                    .unwrap()
            )
        );
        fs::remove_dir_all(root).unwrap();
    }
}
