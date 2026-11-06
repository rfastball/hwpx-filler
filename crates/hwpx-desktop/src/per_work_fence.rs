//! Process-local Work mutation fence and repository lock-order guard.

use std::cell::Cell;
use std::collections::HashMap;
use std::fmt;
use std::sync::{Arc, Mutex, OnceLock};

type FenceKey = (String, String);
static FENCES: OnceLock<Mutex<HashMap<FenceKey, Arc<Mutex<()>>>>> = OnceLock::new();
thread_local! { static STORE_DEPTH: Cell<u32> = const { Cell::new(0) }; }

#[derive(Debug)]
pub struct FenceError(pub String);
impl fmt::Display for FenceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for FenceError {}

/// Marks an inner store lease; a later Work fence acquisition on this thread refuses.
pub(crate) struct StoreLeaseOrderGuard;
impl StoreLeaseOrderGuard {
    pub(crate) fn enter() -> Self {
        STORE_DEPTH.with(|depth| depth.set(depth.get().saturating_add(1)));
        Self
    }
}
impl Drop for StoreLeaseOrderGuard {
    fn drop(&mut self) {
        STORE_DEPTH.with(|depth| depth.set(depth.get() - 1));
    }
}

pub struct PerWorkFence;
impl PerWorkFence {
    pub fn with<T>(
        workspace_id: &str,
        work_id: &str,
        work: impl FnOnce() -> T,
    ) -> Result<T, FenceError> {
        if workspace_id.is_empty() || work_id.is_empty() {
            return Err(FenceError(
                "fence key 의 workspace_instance_id·work_authority_id 는 비어 있을 수 없다".into(),
            ));
        }
        if STORE_DEPTH.with(Cell::get) > 0 {
            return Err(FenceError(
                "StoreWriterLease(안쪽)을 쥔 채 PerWorkMutationFence(바깥)을 기다릴 수 없다".into(),
            ));
        }
        let key = (workspace_id.to_owned(), work_id.to_owned());
        let lock = {
            let mut fences = FENCES
                .get_or_init(|| Mutex::new(HashMap::new()))
                .lock()
                .map_err(|_| FenceError("Work fence table poisoned".into()))?;
            fences
                .entry(key)
                .or_insert_with(|| Arc::new(Mutex::new(())))
                .clone()
        };
        let _guard = lock
            .lock()
            .map_err(|_| FenceError("Work fence poisoned".into()))?;
        Ok(work())
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(crate) mod tests {
    use super::{FENCES, PerWorkFence};
    use crate::directory_lock::DirectoryLock;
    use std::io;
    use std::path::Path;

    fn lock_for(workspace: &str, work: &str) -> std::sync::Arc<std::sync::Mutex<()>> {
        FENCES
            .get()
            .expect("fence table initialized")
            .lock()
            .unwrap()
            .get(&(workspace.into(), work.into()))
            .expect("fence acquired")
            .clone()
    }

    pub(crate) fn assert_held(workspace: &str, work: &str) {
        assert!(
            lock_for(workspace, work).try_lock().is_err(),
            "Work mutation escaped its fence"
        );
    }

    pub(crate) fn assert_released(workspace: &str, work: &str) {
        let lock = lock_for(workspace, work);
        assert!(
            lock.try_lock().is_ok(),
            "Work fence retained after start gate returned"
        );
    }

    #[test]
    fn store_lease_cannot_wait_for_outer_work_fence() {
        let lock = DirectoryLock::new(Path::new("C:/fence-rank-probe")).unwrap();
        lock.with(|| -> io::Result<()> {
            let error = PerWorkFence::with("workspace", "work", || ()).unwrap_err();
            assert!(error.0.contains("StoreWriterLease"));
            Ok(())
        })
        .unwrap();
        assert!(PerWorkFence::with("workspace", "work", || 7).is_ok_and(|value| value == 7));
        assert!(PerWorkFence::with("", "work", || ()).is_err());
        assert!(PerWorkFence::with("workspace", "", || ()).is_err());
        PerWorkFence::with("workspace", "work", || {
            lock.with(|| -> io::Result<()> { Ok(()) }).unwrap();
        })
        .unwrap();
        assert_released("workspace", "work");
    }

    #[test]
    fn same_work_serializes_while_other_work_and_workspace_remain_independent() {
        use std::sync::{Arc, mpsc};
        use std::time::Duration;
        let (attempt_tx, attempt_rx) = mpsc::channel();
        let (entered_tx, entered_rx) = mpsc::channel();
        let worker = PerWorkFence::with("serial-workspace", "work", || {
            let first = FENCES
                .get()
                .unwrap()
                .lock()
                .unwrap()
                .get(&("serial-workspace".into(), "work".into()))
                .unwrap()
                .clone();
            assert!(first.try_lock().is_err());
            for (workspace, work) in [("serial-workspace", "other"), ("other-workspace", "work")] {
                PerWorkFence::with(workspace, work, || {
                    let other = FENCES
                        .get()
                        .unwrap()
                        .lock()
                        .unwrap()
                        .get(&(workspace.into(), work.into()))
                        .unwrap()
                        .clone();
                    assert!(!Arc::ptr_eq(&first, &other));
                    assert!(other.try_lock().is_err());
                })
                .unwrap();
            }
            let worker = std::thread::spawn(move || {
                attempt_tx.send(()).unwrap();
                PerWorkFence::with("serial-workspace", "work", || entered_tx.send(()).unwrap())
                    .unwrap();
            });
            attempt_rx.recv_timeout(Duration::from_secs(2)).unwrap();
            assert!(matches!(
                entered_rx.try_recv(),
                Err(mpsc::TryRecvError::Empty)
            ));
            worker
        })
        .unwrap();
        entered_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        worker.join().unwrap();
        assert_released("serial-workspace", "work");
    }
}
