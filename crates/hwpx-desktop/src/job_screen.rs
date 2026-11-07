//! Screen transport around the Job session; product decisions stay in the controller.

use super::*;
use crate::action_registry::validate_dispatch;
use crate::workspace_switch::{GraphError, ScreenController};

impl JobController {
    pub(super) fn push_snapshot(&self) -> Result<(), JobControllerError> {
        let snapshot = self.refresh_panel()?;
        if !self.boot_restore_in_progress.load(Ordering::SeqCst)
            && let Some(gate) = &self.push_gate
        {
            gate.push("job", &snapshot).map_err(error)?;
        }
        Ok(())
    }
}

impl ScreenController for JobController {
    fn initial(&self) -> Result<Value, GraphError> {
        let _session = self.session()?;
        Ok(JobController::initial(self)?)
    }

    fn dispatch(&self, action: &str, payload: &Value) -> Result<Value, GraphError> {
        // Cancellation must stay callable while native generation is running.
        let _session = if action == "cancel_generation" {
            None
        } else {
            Some(self.session()?)
        };
        validate_dispatch("job", action, payload)?;
        let result = JobController::dispatch(self, action, payload)?;
        if ![
            "artifact_content",
            "filter_panel",
            "count_filter_state",
            "list_filter_columns",
            "guard_state",
            "recover_record_issue",
            "cancel_generation",
            "load_pool",
        ]
        .contains(&action)
        {
            self.push_snapshot()?;
        }
        Ok(result)
    }

    fn close_guard_reason(&self) -> Result<Option<String>, GraphError> {
        Ok(None)
    }
}
