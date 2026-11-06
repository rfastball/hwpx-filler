//! One nonblocking exclusion gate for generation and durable screen mutations.

use std::fmt;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, MutexGuard, TryLockError};

#[derive(Debug)]
pub struct GenerationGateError(pub String);
impl fmt::Display for GenerationGateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for GenerationGateError {}

pub struct GenerationGate {
    lock: Mutex<()>,
    cancel_requested: AtomicBool,
}
impl Default for GenerationGate {
    fn default() -> Self {
        Self::new()
    }
}
impl GenerationGate {
    pub fn is_active(&self) -> bool {
        self.try_lock().map_or(true, |guard| guard.is_none())
    }
    pub fn new() -> Self {
        Self {
            lock: Mutex::new(()),
            cancel_requested: AtomicBool::new(false),
        }
    }
    fn try_lock(&self) -> Result<Option<MutexGuard<'_, ()>>, GenerationGateError> {
        match self.lock.try_lock() {
            Ok(guard) => Ok(Some(guard)),
            Err(TryLockError::WouldBlock) => Ok(None),
            Err(TryLockError::Poisoned(_)) => Err(GenerationGateError(
                "문서 생성 잠금이 손상되었습니다.".into(),
            )),
        }
    }
    pub fn raise_if_generating(
        &self,
        then_do: &str,
        swap: bool,
    ) -> Result<(), GenerationGateError> {
        if self.try_lock()?.is_some() {
            return Ok(());
        }
        Err(GenerationGateError(if swap {
            format!("문서 생성이 진행 중입니다. 중단하거나 완료된 뒤 {then_do}.")
        } else {
            format!("문서 생성이 진행 중입니다. 끝난 뒤에 {then_do}.")
        }))
    }
    /// A run owns this lease through materialization and delivery.
    pub fn begin(&self) -> Result<Option<GenerationLease<'_>>, GenerationGateError> {
        let Some(guard) = self.try_lock()? else {
            return Ok(None);
        };
        self.cancel_requested.store(false, Ordering::SeqCst);
        Ok(Some(GenerationLease { gate: self, guard }))
    }
    /// A durable mutation and its dependent seal run under the same exclusion as generation.
    pub fn with_mutation<T>(
        &self,
        then_do: &str,
        work: impl FnOnce() -> T,
    ) -> Result<T, GenerationGateError> {
        let Some(_guard) = self.try_lock()? else {
            return Err(GenerationGateError(format!(
                "문서 생성이 진행 중입니다. 끝난 뒤에 {then_do}."
            )));
        };
        Ok(work())
    }
    /// Editor save gets the same lock; None means that generation currently owns it.
    pub fn with_editor_save_guard<T>(
        &self,
        work: impl FnOnce() -> T,
    ) -> Result<Option<T>, GenerationGateError> {
        let Some(_guard) = self.try_lock()? else {
            return Ok(None);
        };
        Ok(Some(work()))
    }
    pub fn request_cancel(&self) {
        self.cancel_requested.store(true, Ordering::SeqCst);
    }
    pub fn is_cancel_requested(&self) -> bool {
        self.cancel_requested.load(Ordering::SeqCst)
    }
}

pub struct GenerationLease<'a> {
    gate: &'a GenerationGate,
    guard: MutexGuard<'a, ()>,
}
impl GenerationLease<'_> {
    pub fn is_cancel_requested(&self) -> bool {
        self.gate.is_cancel_requested()
    }
    pub fn finish(self) {
        drop(self.guard);
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn run_and_editor_save_share_one_nonblocking_lease() {
        let gate = GenerationGate::new();
        let run = gate.begin().unwrap().unwrap();
        assert!(gate.begin().unwrap().is_none());
        assert_eq!(gate.with_editor_save_guard(|| 1).unwrap(), None);
        assert_eq!(
            gate.with_mutation("포함할 내용을 바꾸세요", || 1)
                .unwrap_err()
                .to_string(),
            "문서 생성이 진행 중입니다. 끝난 뒤에 포함할 내용을 바꾸세요."
        );
        assert_eq!(
            gate.raise_if_generating("작업을 전환하세요", true)
                .unwrap_err()
                .to_string(),
            "문서 생성이 진행 중입니다. 중단하거나 완료된 뒤 작업을 전환하세요."
        );
        gate.request_cancel();
        assert!(run.is_cancel_requested());
        run.finish();
        assert_eq!(gate.with_editor_save_guard(|| 7).unwrap(), Some(7));
        assert!(!gate.begin().unwrap().unwrap().is_cancel_requested());
    }
}
