//! One library scan supplies both visible rows and the live-path mutation gate.

use crate::library_observation::{read_template, template_display_name};
use crate::template_root::TemplateRoot;
use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_filler::template_library_state::TemplateRow;
use hwpx_filler::text_render::template_fields;
use std::collections::HashMap;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Arc;

#[derive(Default)]
pub(crate) struct TemplateInventoryCache {
    inventory: Option<Arc<TemplateInventory>>,
}
impl TemplateInventoryCache {
    pub fn clear(&mut self) {
        self.inventory = None;
    }
    pub fn current(&mut self, selection: &TemplateRoot) -> io::Result<Arc<TemplateInventory>> {
        let root = selection.path();
        let paths = discover_paths(&root)?;
        if !self
            .inventory
            .as_ref()
            .is_some_and(|inventory| inventory.matches_paths(&root, &paths))
        {
            self.inventory = Some(Arc::new(TemplateInventory::read_paths(root, paths)?));
        }
        Ok(self.inventory.as_ref().unwrap().clone())
    }
    pub fn live_row(
        &mut self,
        selection: &TemplateRoot,
        path: &Path,
        media: Option<&str>,
    ) -> io::Result<Option<TemplateRow>> {
        let matches = |row: &&TemplateRow| {
            Path::new(&row.path) == path && media.is_none_or(|media| row.media == media)
        };
        if let Some(inventory) = &self.inventory
            && inventory.root == selection.path()
            && path.is_file()
            && let Some(row) = inventory.rows.iter().find(matches)
        {
            return Ok(Some(row.clone()));
        }
        Ok(self.current(selection)?.rows.iter().find(matches).cloned())
    }
}

pub struct TemplateInventory {
    pub root: PathBuf,
    pub rows: Vec<TemplateRow>,
    paths: HashMap<PathBuf, Option<(u64, std::time::SystemTime)>>,
}
impl TemplateInventory {
    pub fn read(selection: &TemplateRoot) -> io::Result<Self> {
        let root = selection.path();
        let paths = discover_paths(&root)?;
        Self::read_paths(root, paths)
    }
    pub(crate) fn read_paths(root: PathBuf, mut paths: Vec<PathBuf>) -> io::Result<Self> {
        let members = paths
            .iter()
            .map(|path| (path.clone(), file_stamp(path)))
            .collect();
        paths.sort_by(|left, right| {
            left.file_name()
                .cmp(&right.file_name())
                .then(left.cmp(right))
        });
        let mut hwpx = Vec::new();
        let mut txt = Vec::new();
        for path in paths {
            let row = read_row(&root, &path)?;
            if row.media == "hwpx" {
                hwpx.push(row);
            } else {
                txt.push(row);
            }
        }
        hwpx.extend(txt);
        Ok(Self {
            root,
            rows: hwpx,
            paths: members,
        })
    }
    pub(crate) fn matches_paths(&self, root: &Path, paths: &[PathBuf]) -> bool {
        self.root == root
            && self.paths.len() == paths.len()
            && paths.iter().all(|path| {
                file_stamp(path).is_some_and(|stamp| self.paths.get(path) == Some(&Some(stamp)))
            })
    }
    pub fn contains(&self, media: &str, path: &Path) -> bool {
        self.rows
            .iter()
            .any(|row| row.media == media && Path::new(&row.path) == path)
    }
}

// Cache only presentation rows; review and every mutation still read current file contents.
fn file_stamp(path: &Path) -> Option<(u64, std::time::SystemTime)> {
    let metadata = fs::metadata(path).ok()?;
    Some((metadata.len(), metadata.modified().ok()?))
}

fn read_row(root: &Path, path: &Path) -> io::Result<TemplateRow> {
    let media = if path
        .extension()
        .is_some_and(|ext| ext.eq_ignore_ascii_case("hwpx"))
    {
        "hwpx"
    } else {
        "txt"
    };
    let name = template_display_name(
        root,
        path.to_str().ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidData, "template path is not Unicode")
        })?,
    );
    let label = path.to_str().unwrap();
    let row = match (media, read_template(path)) {
        ("hwpx", Ok(bytes)) => match HwpxPackage::from_bytes(&bytes, PackageLimits::default()) {
            Ok(package) => TemplateRow::hwpx(&name, label, &package)
                .unwrap_or_else(|error| TemplateRow::error(&name, label, "hwpx", &error)),
            Err(error) => TemplateRow::error(&name, label, "hwpx", &error.to_string()),
        },
        ("txt", Ok(bytes)) => match String::from_utf8(bytes) {
            Ok(content) => TemplateRow::txt(&name, label, template_fields(&content).len(), ""),
            Err(error) => TemplateRow::error(&name, label, "txt", &error.to_string()),
        },
        (_, Err(error)) => TemplateRow::error(&name, label, media, &error.to_string()),
        _ => unreachable!(),
    };
    Ok(row)
}

pub(crate) fn discover_paths(root: &Path) -> io::Result<Vec<PathBuf>> {
    let mut paths = Vec::new();
    if root.is_dir() {
        discover(root, &mut paths)?;
    }
    Ok(paths)
}

fn discover(directory: &Path, paths: &mut Vec<PathBuf>) -> io::Result<()> {
    for entry in fs::read_dir(directory)? {
        let entry = entry?;
        let path = entry.path();
        let kind = entry.file_type()?;
        if kind.is_dir() {
            if entry.file_name() != ".trash" && entry.file_name() != "Results" {
                discover(&path, paths)?;
            }
        } else if (kind.is_file() || (kind.is_symlink() && path.is_file()))
            && path.extension().is_some_and(|ext| {
                ext.eq_ignore_ascii_case("hwpx") || ext.eq_ignore_ascii_case("txt")
            })
        {
            paths.push(path);
        }
    }
    Ok(())
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{TemplateInventory, TemplateInventoryCache};
    use crate::shell_settings::ShellSettings;
    use crate::template_root::TemplateRoot;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::Arc;

    #[test]
    fn one_selected_root_supplies_visible_rows_and_gate() {
        let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let root = repo.join(format!(
            ".cache/template-inventory-owner-{}",
            std::process::id()
        ));
        let first = root.join("first");
        let second = root.join("second");
        for directory in [
            first.join("sub"),
            first.join("Results"),
            first.join("sub/Results"),
            first.join(".trash"),
            second.clone(),
        ] {
            fs::create_dir_all(directory).unwrap();
        }
        fs::write(first.join("sub/good.txt"), "안녕 {{이름}}").unwrap();
        fs::write(first.join("sub/bad.hwpx"), b"bad zip").unwrap();
        fs::write(first.join("sub/caps.HwPx"), b"bad zip").unwrap();
        fs::write(first.join("Results/ignored.txt"), "{{오염}}").unwrap();
        fs::write(first.join("sub/Results/ignored.hwpx"), b"bad zip").unwrap();
        fs::write(first.join(".trash/removed.hwpx"), b"bad zip").unwrap();
        fs::write(second.join("next.txt"), "{{다음}}").unwrap();
        let settings = Arc::new(ShellSettings::new(root.join("settings.json"), |_| {}));
        let selection = TemplateRoot::new(settings, first.clone()).unwrap();
        let (inventory, reads) = crate::library_observation::observe_template_reads(|| {
            TemplateInventory::read(&selection).unwrap()
        });
        assert_eq!(reads.len(), 3);
        assert_eq!(
            reads.iter().collect::<std::collections::HashSet<_>>().len(),
            3
        );
        assert_eq!(inventory.rows.len(), 3);
        assert_eq!(inventory.rows[0].media, "hwpx");
        assert!(!inventory.rows[0].error.is_empty());
        assert!(inventory.rows[0].status.is_none() && inventory.rows[0].actions().is_empty());
        assert!(!inventory.rows[0].select_block_reason().is_empty());
        assert!(
            inventory
                .rows
                .iter()
                .any(|row| row.media == "hwpx" && row.name == "sub/caps")
        );
        assert_eq!(inventory.rows[2].name, "sub/good");
        assert!(inventory.contains("txt", &first.join("sub/good.txt")));
        assert!(!inventory.contains("txt", &first.join("Results/ignored.txt")));
        let mut cache = TemplateInventoryCache::default();
        cache.current(&selection).unwrap();
        let (_, reads) = crate::library_observation::observe_template_reads(|| {
            assert!(
                cache
                    .live_row(&selection, &first.join("sub/good.txt"), Some("txt"))
                    .unwrap()
                    .is_some()
            );
            assert!(
                cache
                    .live_row(&selection, &first.join("sub/good.txt"), Some("hwpx"))
                    .unwrap()
                    .is_none()
            );
        });
        assert!(reads.is_empty(), "membership must not reread the library");
        selection.set(second.to_str().unwrap()).unwrap();
        assert_eq!(cache.current(&selection).unwrap().rows[0].name, "next");
        assert!(
            cache
                .live_row(&selection, &first.join("sub/good.txt"), None)
                .unwrap()
                .is_none()
        );
        let inventory = TemplateInventory::read(&selection).unwrap();
        assert_eq!(inventory.rows.len(), 1);
        assert_eq!(inventory.rows[0].name, "next");
        assert!(!inventory.contains("txt", &first.join("sub/good.txt")));
        assert!(
            root.canonicalize()
                .unwrap()
                .starts_with(repo.canonicalize().unwrap())
        );
        fs::remove_dir_all(root).unwrap();
    }
}
