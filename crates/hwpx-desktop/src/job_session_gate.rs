//! Reentrant Job-session serialization for screen and cross-screen transitions.

use std::sync::{Condvar, Mutex};
use std::thread::ThreadId;

#[derive(Default)]
struct Owner {
    thread: Option<ThreadId>,
    depth: usize,
}

#[derive(Default)]
pub(super) struct JobSessionGate {
    owner: Mutex<Owner>,
    available: Condvar,
}

pub(super) struct JobSessionLease<'a> {
    gate: &'a JobSessionGate,
}

impl JobSessionGate {
    pub(super) fn enter(&self) -> Result<JobSessionLease<'_>, &'static str> {
        let current = std::thread::current().id();
        let mut owner = self
            .owner
            .lock()
            .map_err(|_| "작업 화면 상태 잠금이 손상되었습니다.")?;
        while owner.thread.is_some() && owner.thread != Some(current) {
            owner = self
                .available
                .wait(owner)
                .map_err(|_| "작업 화면 상태 잠금이 손상되었습니다.")?;
        }
        owner.thread = Some(current);
        owner.depth += 1;
        Ok(JobSessionLease { gate: self })
    }
}

impl Drop for JobSessionLease<'_> {
    fn drop(&mut self) {
        let Ok(mut owner) = self.gate.owner.lock() else {
            return;
        };
        owner.depth -= 1;
        if owner.depth == 0 {
            owner.thread = None;
            self.gate.available.notify_one();
        }
    }
}
