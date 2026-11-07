//! Seating, preferring, and browsing works, and the selection basis queries.

use super::*;

impl JobController {
    pub fn selected_job_name(&self) -> Result<String, JobControllerError> {
        let _session = self.session()?;
        Ok(self
            .state()?
            .seated
            .as_ref()
            .map_or(String::new(), |item| item.job.name.clone()))
    }
    pub fn transition_basis(&self) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        let state = self.state()?;
        Ok(json!([
            state
                .seated
                .as_ref()
                .map_or("", |item| item.job.name.as_str()),
            self.data_identity,
            state.data.snapshot_generation,
            state.data.committed_range().fingerprint(),
        ]))
    }
    pub(super) fn contract_fit(job: &Job, data: &MountedData) -> Option<(bool, String)> {
        let contract = job.data_contract.as_ref()?;
        if job.has_data_binding() || data.path.is_empty() || data.records.is_empty() {
            return None;
        }
        let columns = data.records[0].keys().cloned().collect::<Vec<_>>();
        let records = data
            .records
            .iter()
            .map(|record| {
                record
                    .iter()
                    .map(|(key, value)| (key.clone(), Value::String(value.clone())))
                    .collect::<Map<_, _>>()
            })
            .collect::<Vec<_>>();
        let fit = judge_job_contract(contract, &job.mapping, &columns, &records);
        let reason = if fit.failures.is_empty() {
            String::new()
        } else {
            format!(
                "꾸러미 조건과 다른 연결: {}",
                fit.failures
                    .iter()
                    .map(|(field, reason)| format!("{field}({reason})"))
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        };
        Some((fit.passed, reason))
    }
    pub fn select_job(&self, name: &str) -> Result<(), JobControllerError> {
        let _session = self.session()?;
        let automatic = self
            .generation
            .with_mutation("작업을 전환하세요", || {
                let mut state = self.state()?;
                self.seat_job(&mut state, name)
            })
            .map_err(error)??;
        if automatic {
            self.resolve_execution()?;
        }
        Ok(())
    }
    /// Seats `name` (or releases the seat for an empty name) inside the generation mutation.
    /// Returns whether the seated work resolves its execution automatically.
    fn seat_job(&self, state: &mut JobState, name: &str) -> Result<bool, JobControllerError> {
        state.data.notice_text.clear();
        state.data.notice_level.clear();
        state.preferred.clear();
        if name.is_empty() {
            state.seated = None;
            reset_execution_evidence(state);
            return Ok(false);
        }
        let (job, contract_notice) = self.contract_bound_job(name, &state.data)?;
        let mut notices = self.mount_job_binding(&mut state.data, &job);
        if !contract_notice.is_empty() {
            notices.push(contract_notice);
        }
        self.change.ensure_bootstrapped(&job.name).map_err(error)?;
        let job = self.registry.load(&job.name).map_err(error)?;
        let application_id = self
            .change
            .current_application_id(
                (!job.authority_id.is_empty()).then_some(job.authority_id.as_str()),
            )
            .map_err(error)?;
        state.seated = Some(SeatedJob {
            job,
            application_id,
        });
        reseed_hwpx_filter(state)?;
        reset_execution_evidence(state);
        if !notices.is_empty() {
            state.data.notice_text = notices.join(" ");
            state.data.notice_level = "warn".into();
        }
        Ok(state
            .seated
            .as_ref()
            .is_some_and(|seat| seat.job.media() == "hwpx" && !seat.job.authority_id.is_empty()))
    }
    /// Loads the work and binds a contract-fitting current data; a misfit reason becomes a notice.
    fn contract_bound_job(
        &self,
        name: &str,
        data: &MountedData,
    ) -> Result<(Job, String), JobControllerError> {
        let job = self.registry.load(name).map_err(error)?;
        let Some((passed, reason)) = Self::contract_fit(&job, data) else {
            return Ok((job, String::new()));
        };
        if !passed {
            return Ok((job, reason));
        }
        match bind_contract_data(
            &self.registry,
            &job,
            (&data.path, &data.sheet, data.header_row, &data.kind),
        ) {
            Ok(bound) => Ok((bound, String::new())),
            Err(ContractBindingError::Refused) => Ok((job, String::new())),
            Err(other) => Err(error(other)),
        }
    }
    /// Mounts the work's own data binding when the policy asks for it; returns the notices.
    fn mount_job_binding(&self, data: &mut MountedData, job: &Job) -> Vec<String> {
        let discards = data.selection.selected_count() > 0 || data.range_draft.is_some();
        let decision = data_binding_mount(
            job,
            (&data.path, &data.sheet, data.header_row, &data.kind),
            !job.data_path.is_empty() && !Path::new(&job.data_path).exists(),
            discards,
        );
        let mut notices = Vec::new();
        if decision.action == "mount" {
            match data.mount_binding(
                &self.pool,
                &decision.path,
                &decision.sheet,
                decision.header_row,
                &decision.kind,
            ) {
                Ok(()) if decision.discards => notices.push(format!(
                    "이 작업에 연결된 데이터 '{}' 을(를) 불러왔습니다. 항목 선택은 초기화됐습니다.",
                    data.label
                )),
                Ok(()) => (),
                Err(failure) => notices.push(format!(
                    "이 작업에 연결된 데이터를 불러오지 못했습니다. {failure}"
                )),
            }
        } else if !decision.notice.is_empty() {
            notices.push(decision.notice);
        }
        notices
    }
    pub fn prefer_work(&self, name: &str) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        let name = hwpx_filler::structure_scan::python_trim(name);
        if name.is_empty() {
            return Err(error("겨눌 작업 이름이 비어 있습니다."));
        }
        let job = self.registry.load(name).map_err(error)?;
        let (jobs, _) = self.registry.list_jobs_with_corruption().map_err(error)?;
        let fields = {
            let state = self.state()?;
            state
                .data
                .records
                .first()
                .map(|row| row.keys().cloned().collect::<Vec<_>>())
        };
        let decision = request_preferred(&job, &jobs, fields.as_deref());
        if decision.action == "select" {
            self.select_job(name)?;
            return Ok(json!({"promoted":true,"name":name}));
        }
        self.state()?.preferred = name.into();
        Ok(json!({"stored":true,"reason":decision.reason,"name":name}))
    }
    pub fn browse(&self, tab: Option<&str>, query: Option<&str>) -> Result<(), JobControllerError> {
        let _session = self.session()?;
        let mut state = self.state()?;
        if let Some(tab) = tab {
            state.browse_tab = if tab == "needs_action" {
                "needs_action"
            } else {
                "available"
            }
            .into();
        }
        if let Some(query) = query {
            state.browse_query = query.into();
        }
        Ok(())
    }
}

/// A seat change drops the previous work's run evidence and results.
fn reset_execution_evidence(state: &mut JobState) {
    state.fresh_observation = None;
    state.orchestration = hwpx_filler::workbench_execution_status::NO_EVIDENCE.into();
    state.invalidate_results();
    state.last_failed.clear();
}

/// An idle filter is reseeded from the newly seated HWPX work, keeping its saved presets.
fn reseed_hwpx_filter(state: &mut JobState) -> Result<(), JobControllerError> {
    let Some(seat) = state.seated.as_ref() else {
        return Ok(());
    };
    if state.data.records.is_empty()
        || state
            .data
            .filter
            .as_ref()
            .is_none_or(|filter| filter.is_active())
        || seat.job.media() != "hwpx"
    {
        return Ok(());
    }
    let presets = state.data.filter.as_ref().expect("checked above").presets();
    let hints = data_change::mapping_kind_hints(&seat.job);
    let mut filter = FilterModel::new(
        state.data.fields.clone(),
        sniff_column_kinds(&state.data.records, &hints),
    );
    filter
        .set_presets(&presets, &std::collections::HashMap::new())
        .map_err(|failure| error(failure.message))?;
    state.data.filter = Some(filter);
    Ok(())
}
