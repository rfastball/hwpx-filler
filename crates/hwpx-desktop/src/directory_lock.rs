//! Shared process-local writer gate for file registries without a cross-process lease.

use crate::per_work_fence::StoreLeaseOrderGuard;
use crate::single_instance::{normalize_windows_path, resolved_home};
use std::collections::HashMap;
use std::io;
use std::path::Path;
use std::sync::{Arc, Mutex, OnceLock, Weak};

type Gates = HashMap<String, Weak<Mutex<()>>>;
static GATES: OnceLock<Mutex<Gates>> = OnceLock::new();

#[derive(Clone)]
pub struct DirectoryLock(Arc<Mutex<()>>);
impl DirectoryLock {
    pub fn new(directory: &Path) -> io::Result<Self> {
        let key = normalize_windows_path(&resolved_home(directory))?.to_lowercase();
        let mut gates = GATES
            .get_or_init(|| Mutex::new(HashMap::new()))
            .lock()
            .map_err(|_| io::Error::other("directory lock table poisoned"))?;
        gates.retain(|_, gate| gate.strong_count() > 0);
        let gate = match gates.get(&key).and_then(Weak::upgrade) {
            Some(gate) => gate,
            None => {
                let gate = Arc::new(Mutex::new(()));
                gates.insert(key, Arc::downgrade(&gate));
                gate
            }
        };
        Ok(Self(gate))
    }
    pub fn with<T, E: From<io::Error>>(&self, work: impl FnOnce() -> Result<T, E>) -> Result<T, E> {
        let _rank = StoreLeaseOrderGuard::enter();
        let _guard = self
            .0
            .lock()
            .map_err(|_| E::from(io::Error::other("directory writer lock poisoned")))?;
        work()
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::DirectoryLock;
    use std::path::Path;
    use std::sync::Arc;

    #[test]
    fn same_directory_instances_share_one_writer_gate() {
        let first = DirectoryLock::new(Path::new("C:/hwpx-test/datasets")).unwrap();
        let second = DirectoryLock::new(Path::new("c:/HWPX-TEST/DATASETS")).unwrap();
        assert!(Arc::ptr_eq(&first.0, &second.0));
        first
            .with(|| -> Result<(), std::io::Error> { Ok(()) })
            .unwrap();
    }
}
