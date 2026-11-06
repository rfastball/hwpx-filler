//! One writer process per JobRegistry directory, shared across same-process registries.

use crate::per_work_fence::StoreLeaseOrderGuard;
use crate::single_instance::{normalize_windows_path, resolved_home};
use sha1::{Digest, Sha1};
use std::collections::HashMap;
use std::fmt;
use std::io;
use std::path::Path;
use std::sync::{Arc, Mutex, OnceLock, Weak};

#[cfg(windows)]
use crate::single_instance::{Acquisition, InstanceGuard, acquire_named};

#[derive(Debug)]
pub struct OwnershipError(pub String);
impl fmt::Display for OwnershipError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}
impl std::error::Error for OwnershipError {}

pub fn mutex_name(directory: &Path) -> io::Result<String> {
    let key = normalize_windows_path(&resolved_home(directory))?.to_lowercase();
    let digest = Sha1::digest(key.as_bytes());
    let prefix = digest
        .iter()
        .take(12)
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    Ok(format!("hwpx-job-registry-writer-{prefix}"))
}

struct WriteState {
    gate: Mutex<()>,
    #[cfg(windows)]
    owner: Mutex<Option<InstanceGuard>>,
}
type States = HashMap<String, Weak<WriteState>>;
static STATES: OnceLock<Mutex<States>> = OnceLock::new();

#[derive(Clone)]
pub struct JobWriterLease {
    name: String,
    state: Arc<WriteState>,
}
impl JobWriterLease {
    pub fn new(directory: &Path) -> io::Result<Self> {
        let name = mutex_name(directory)?;
        let mut states = STATES
            .get_or_init(|| Mutex::new(HashMap::new()))
            .lock()
            .map_err(|_| io::Error::other("job writer state lock poisoned"))?;
        states.retain(|_, state| state.strong_count() > 0);
        let state = match states.get(&name).and_then(Weak::upgrade) {
            Some(state) => state,
            None => {
                let state = Arc::new(WriteState {
                    gate: Mutex::new(()),
                    #[cfg(windows)]
                    owner: Mutex::new(None),
                });
                states.insert(name.clone(), Arc::downgrade(&state));
                state
            }
        };
        Ok(Self { name, state })
    }

    /// The caller keeps the read/compare/write sequence within this callback.
    pub fn with_write_lock<T>(&self, write: impl FnOnce() -> T) -> Result<T, OwnershipError> {
        let _rank = StoreLeaseOrderGuard::enter();
        let _gate = self
            .state
            .gate
            .lock()
            .map_err(|_| OwnershipError("작업 저장소 잠금이 손상되었습니다.".into()))?;
        #[cfg(windows)]
        {
            let mut owner =
                self.state.owner.lock().map_err(|_| {
                    OwnershipError("작업 저장소 소유권 잠금이 손상되었습니다.".into())
                })?;
            if owner.is_none() {
                match acquire_named(&self.name) {
                    Ok(Acquisition::Primary(handle)) => *owner = Some(handle),
                    Ok(Acquisition::Existing) => return Err(OwnershipError(
                        "이 작업 저장소는 이미 다른 문서나르미 프로세스가 쓰고 있습니다. 기존 앱을 닫은 뒤 다시 시도하세요.".into()
                    )),
                    Err(error) => return Err(OwnershipError(format!(
                        "작업 저장소 writer 소유권을 확인할 수 없습니다 (WinError {}).",
                        error.raw_os_error().unwrap_or(0)
                    ))),
                }
            }
        }
        #[cfg(not(windows))]
        return Err(OwnershipError(format!(
            "Windows job writer lease unavailable: {}",
            self.name
        )));
        #[cfg(windows)]
        Ok(write())
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{JobWriterLease, mutex_name};
    use std::path::Path;

    #[test]
    fn writer_name_and_shared_state_match_the_windows_directory_contract() {
        let directory = Path::new("C:/Users/Test/.hwpxfiller/jobs");
        assert_eq!(
            mutex_name(directory).unwrap(),
            "hwpx-job-registry-writer-f8975df2b6474fde665c8964"
        );
        let unique = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join(format!("../../.cache/job-writer-{}", std::process::id()));
        let first = JobWriterLease::new(&unique).unwrap();
        let second = JobWriterLease::new(&unique).unwrap();
        assert!(std::sync::Arc::ptr_eq(&first.state, &second.state));
        let alias = JobWriterLease::new(&unique.join("child/..")).unwrap();
        assert!(std::sync::Arc::ptr_eq(&first.state, &alias.state));
        #[cfg(windows)]
        {
            first.with_write_lock(|| ()).unwrap();
            second.with_write_lock(|| ()).unwrap();
        }
    }

    #[cfg(windows)]
    #[test]
    fn refused_ownership_releases_thread_gate_and_recovers_without_running_write() {
        use crate::single_instance::{Acquisition, acquire_named};
        use std::sync::{Arc, mpsc};
        use std::thread;
        use std::time::Duration;

        let unique = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/job-writer-refusal-{}",
            std::process::id()
        ));
        let mut lease = JobWriterLease::new(&unique).unwrap();
        let name = lease.name.clone();
        lease.name = format!("missing-namespace-{}\\mutex", std::process::id());
        let error = lease
            .with_write_lock(|| panic!("a refused writer cannot run"))
            .unwrap_err();
        assert!(
            error
                .0
                .starts_with("작업 저장소 writer 소유권을 확인할 수 없습니다 (WinError ")
        );
        assert!(lease.state.owner.lock().unwrap().is_none());
        assert!(lease.state.gate.try_lock().is_ok());
        lease.name = name;
        let primary = match acquire_named(&lease.name).unwrap() {
            Acquisition::Primary(owner) => owner,
            Acquisition::Existing => panic!("fresh writer key is already owned"),
        };
        let error = lease
            .with_write_lock(|| panic!("an occupied writer cannot run"))
            .unwrap_err();
        assert!(error.0.contains("다른 문서나르미 프로세스"));
        assert!(lease.state.owner.lock().unwrap().is_none());
        drop(primary);

        let (sent, received) = mpsc::channel();
        let retry = lease.clone();
        let worker = thread::spawn(move || sent.send(retry.with_write_lock(|| 7)).unwrap());
        assert_eq!(
            received
                .recv_timeout(Duration::from_secs(3))
                .unwrap()
                .unwrap(),
            7
        );
        worker.join().unwrap();
        assert!(lease.state.owner.lock().unwrap().is_some());
        let weak = Arc::downgrade(&lease.state);
        drop(lease);
        assert!(weak.upgrade().is_none());
        let unclaimed = JobWriterLease::new(&unique).unwrap();
        assert!(unclaimed.state.owner.lock().unwrap().is_none());
        drop(unclaimed);
        assert!(matches!(
            acquire_named(&mutex_name(&unique).unwrap()).unwrap(),
            Acquisition::Primary(_)
        ));
    }
}
