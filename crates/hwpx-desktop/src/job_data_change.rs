//! Re-judging the seated work after the mounted data changes.

use super::*;
use hwpx_filler::active_work_state::DataTransitionReconciliation;
use std::collections::HashMap;

impl JobController {
    pub(super) fn restore_active_after_data_change(&self, state: &mut JobState) {
        state.invalidate_results();
        let Some(seated) = state.seated.clone() else {
            self.restate_preferred_after_data_change(state);
            return;
        };
        let decision = self.reconcile_seated(seated, &state.data);
        if decision.release {
            state.seated = None;
        }
        rebuild_idle_hwpx_filter(&mut state.data, state.seated.as_ref());
        if !decision.warning.is_empty() {
            state.data.notice_text = decision.warning;
            state.data.notice_level = "warn".into();
        }
        self.restate_preferred_after_data_change(state);
    }
    /// Collects the stored facts about the seated work and hands them to the pure reconciler.
    fn reconcile_seated(
        &self,
        seated: SeatedJob,
        data: &MountedData,
    ) -> DataTransitionReconciliation {
        let (active_job, restore_failed) = match self.registry.load(&seated.job.name) {
            Ok(job) => (Some(job), false),
            Err(_) => (None, true),
        };
        let (application, application_failed) = self.seated_application(active_job.as_ref());
        let (same_job, fingerprint_failed) = self.same_seated_job(active_job.as_ref(), &seated.job);
        let exact = seated.job.media() == "hwpx"
            && !seated.job.authority_id.is_empty()
            && same_job
            && application.is_some()
            && application == seated.application_id;
        let bound = active_job.as_ref().is_some_and(|job| {
            data_binding_matches(job, &data.path, &data.sheet, data.header_row, &data.kind)
        });
        reconcile_data_transition(
            ActiveWorkContext {
                active_name: seated.job.name,
                template_application_ref: application,
                exact_context_restorable: exact,
                bound_to_current_data: bound,
            },
            restore_failed || application_failed || fingerprint_failed,
            active_job.is_some(),
        )
    }
    /// The reloaded work's current template application, and whether reading it failed.
    fn seated_application(&self, active_job: Option<&Job>) -> (Option<String>, bool) {
        let application = active_job.and_then(|job| {
            (!job.authority_id.is_empty())
                .then(|| self.change.current_application_id(Some(&job.authority_id)))
        });
        match application {
            Some(Ok(value)) => (value, false),
            Some(Err(_)) => (None, true),
            None => (None, false),
        }
    }
    /// Whether the reloaded work is still the seated one, and whether fingerprinting failed.
    fn same_seated_job(&self, current: Option<&Job>, seated: &Job) -> (bool, bool) {
        let fingerprints = current.map(|current| {
            (
                self.registry.content_fingerprint(current),
                self.registry.content_fingerprint(seated),
            )
        });
        let fingerprint_failed = fingerprints
            .as_ref()
            .is_some_and(|(current, seated)| current.is_err() || seated.is_err());
        let same_fingerprint = matches!(
            fingerprints,
            Some((Ok(current), Ok(seated))) if current == seated
        );
        let same_job = current.is_some_and(|current| {
            current.authority_id == seated.authority_id
                && current.template_revision == seated.template_revision
                && current.binding_revision == seated.binding_revision
                && current.previous_rules == seated.previous_rules
                && same_fingerprint
        });
        (same_job, fingerprint_failed)
    }
    pub(super) fn restate_preferred_after_data_change(&self, state: &mut JobState) {
        let preferred = std::mem::take(&mut state.preferred);
        if preferred.is_empty() {
            return;
        }
        let jobs = self
            .registry
            .list_jobs_with_corruption()
            .ok()
            .map(|(jobs, _)| jobs);
        let active = state
            .seated
            .as_ref()
            .map_or("", |seat| seat.job.name.as_str());
        if let Some((text, level)) =
            preferred_notice(&preferred, active, jobs.as_deref(), &state.data.fields)
        {
            if !state.data.notice_text.is_empty() {
                state.data.notice_text.push(' ');
            }
            state.data.notice_text.push_str(&text);
            if state.data.notice_level != "warn" {
                state.data.notice_level = level.into();
            }
        }
    }
    pub fn load_data_path(
        &self,
        path: &Path,
        sheet: Option<&str>,
        header_row: usize,
    ) -> Result<(), JobControllerError> {
        let _session = self.session()?;
        self.generation
            .with_mutation("데이터를 바꾸세요", || {
                let mut state = self.state()?;
                state
                    .data
                    .mount_file_registered(&self.pool, path, sheet, header_row)
                    .map_err(error)?;
                self.restore_active_after_data_change(&mut state);
                Ok(())
            })
            .map_err(error)??;
        let stored = self.remember_current_data_source();
        let pushed = self.push_snapshot();
        stored?;
        pushed
    }
    pub fn load_pool(&self, key: &str, sheet: Option<&str>) -> Result<(), JobControllerError> {
        let _session = self.session()?;
        self.generation
            .with_mutation("데이터를 바꾸세요", || {
                let mut state = self.state()?;
                state
                    .data
                    .mount_pool(&self.pool, key, sheet)
                    .map_err(error)?;
                self.restore_active_after_data_change(&mut state);
                Ok(())
            })
            .map_err(error)??;
        let stored = self.remember_current_data_source();
        let pushed = self.push_snapshot();
        stored?;
        pushed
    }
}

/// Column kind hints from the work's text/date/amount mappings.
pub(super) fn mapping_kind_hints(job: &Job) -> HashMap<String, String> {
    job.mapping
        .mappings
        .iter()
        .filter(|mapping| {
            !mapping.source.is_empty()
                && [KIND_TEXT, KIND_DATE, KIND_AMOUNT].contains(&mapping.field_type.as_str())
        })
        .map(|mapping| (mapping.source.clone(), mapping.field_type.clone()))
        .collect()
}

/// An idle filter over loaded rows is rebuilt from the still-seated HWPX work's hints.
fn rebuild_idle_hwpx_filter(data: &mut MountedData, seated: Option<&SeatedJob>) {
    if !data.records.is_empty()
        && data
            .filter
            .as_ref()
            .is_some_and(|filter| !filter.is_active())
        && let Some(seat) = seated
        && seat.job.media() == "hwpx"
    {
        let hints = mapping_kind_hints(&seat.job);
        data.filter = Some(FilterModel::new(
            data.fields.clone(),
            sniff_column_kinds(&data.records, &hints),
        ));
    }
}
