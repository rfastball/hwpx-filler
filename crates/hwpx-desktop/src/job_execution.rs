//! Job-session execution observation; sealed facts never come from the UI.

use super::*;
use crate::seal_execution_service::SealExecutionService;
use crate::workbench_observation_product::WorkbenchObservationProduct;
use hwpx_filler::fresh_execution_observation::{
    ExecutionObservationContextError, FreshExecutionObservation,
};
use hwpx_filler::workbench_execution_status::{CHECKING, CURRENT, STALE};

impl JobController {
    /// Editor action availability uses the same current Binding review as the Job panel.
    pub fn binding_confirm_pending(&self, work_ref: &str) -> Result<bool, JobControllerError> {
        let _session = self.session()?;
        let (seat, fresh) = {
            let state = self.state()?;
            if !matches!(
                state.fresh_observation,
                Some(FreshExecutionObservation::WorkBlocked(_))
            ) {
                return Ok(false);
            }
            (state.seated.clone(), state.fresh_observation.clone())
        };
        let Some(seat) = seat.filter(|seat| {
            seat.job.name == work_ref
                && seat.job.media() == "hwpx"
                && !seat.job.authority_id.is_empty()
        }) else {
            return Ok(false);
        };
        let projection = self
            .seal_service()?
            .current_binding_review(&seat.job.name)
            .map_err(error)?;
        Ok(WorkbenchObservationProduct::binding_review_pending(
            fresh.as_ref(),
            projection
                .as_ref()
                .map_or(&[], |item| item.input_requirements.as_slice()),
        ))
    }

    /// A saved Editor mapping invalidates old execution evidence before any fresh check.
    pub fn after_mapping_saved(&self, work_ref: &str) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        if self.selected_job_name()? != work_ref {
            return Ok(json!({}));
        }
        {
            let mut state = self.state()?;
            state.fresh_observation = None;
            state.orchestration = STALE.into();
        }
        let job = self.registry.load(work_ref).map_err(error)?;
        if job.media() != "hwpx" || job.authority_id.is_empty() {
            return Ok(json!({}));
        }
        let Some(result) = self
            .generation
            .with_editor_save_guard(|| self.resolve_execution())
            .map_err(error)?
        else {
            return Ok(json!({}));
        };
        result?;
        Ok(json!({}))
    }
    pub(super) fn seal_service(&self) -> Result<SealExecutionService<'_>, JobControllerError> {
        let clock = self.clock.clone();
        SealExecutionService::new(self.change.authority_root(), &self.registry, move || {
            clock().format("%Y-%m-%dT%H:%M:%S").to_string()
        })
        .map_err(error)
    }

    fn observe_execution(&self, automatic: bool) -> Result<(), JobControllerError> {
        let work_ref = self.selected_job_name()?;
        if work_ref.is_empty() {
            return Ok(());
        }
        let service = self.seal_service()?;
        let response = service.seal(&work_ref, &uuid::Uuid::new_v4().simple().to_string());
        match response {
            Ok(response) => {
                let mut state = self.state()?;
                if automatic {
                    state.orchestration = if matches!(
                        response.fresh_observation,
                        FreshExecutionObservation::Sealed(_)
                    ) {
                        CURRENT.into()
                    } else {
                        STALE.into()
                    };
                }
                state.fresh_observation = Some(response.fresh_observation);
            }
            Err(failure) => {
                let mut state = self.state()?;
                if automatic {
                    state.orchestration = STALE.into();
                }
                state.fresh_observation = Some(FreshExecutionObservation::ContextError(
                    ExecutionObservationContextError {
                        code: "OBSERVATION_REFRESH_FAILED".into(),
                        detail: failure.to_string(),
                    },
                ));
            }
        }
        Ok(())
    }

    /// A read refresh replaces stale evidence without changing the orchestration state.
    pub fn refresh_execution_observation(&self) -> Result<(), JobControllerError> {
        let _session = self.session()?;
        self.observe_execution(false)
    }

    pub fn resolve_execution(&self) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        if self.selected_job_name()?.is_empty() {
            return Err(error("먼저 문서 작업을 선택하세요."));
        }
        {
            let mut state = self.state()?;
            if state.orchestration == CHECKING {
                return Ok(json!({"ok":true}));
            }
            state.orchestration = CHECKING.into();
        }
        self.observe_execution(true)?;
        Ok(json!({"ok":true}))
    }
}
