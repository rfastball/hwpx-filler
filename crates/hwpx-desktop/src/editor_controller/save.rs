use super::*;
use crate::job_registry::JobWriteSession;
use hwpx_filler::mapping::MappingProfile;

/// What the save transaction found under the destination name before writing.
struct SaveTarget {
    exists: bool,
    job: Option<Job>,
}

impl SaveTarget {
    /// The stored work whose durable metadata the new save keeps.
    fn preserved<'a>(
        &'a self,
        self_update: bool,
        origin: Option<&'a Job>,
        base: Option<&'a Job>,
    ) -> Option<&'a Job> {
        if self.exists {
            self.job.as_ref().or(if self_update { base } else { None })
        } else {
            origin.or(base)
        }
    }
}

/// Post-commit facts the guarded save hands back for the notifications that follow it.
#[derive(Default)]
struct SaveLanding {
    saved: Option<Job>,
    error: Option<String>,
}

impl EditorController {
    fn overwrite_text(name: &str, victim: Option<&str>) -> String {
        match victim {
            None => format!(
                "작업 '{name}' 의 저장 위치에 기존 작업 파일이 있습니다(손상되어 어떤 작업인지 확인할 수 없습니다).\n계속하면 그 파일을 덮어씁니다."
            ),
            Some(other) if other != name => format!(
                "작업 이름 '{name}' 은(는) 기존 작업 '{other}' 과(와) 같은 파일로 저장됩니다.\n계속하면 작업 '{other}' 을(를) 덮어씁니다."
            ),
            Some(_) => {
                format!("작업 '{name}' 이(가) 이미 있습니다.\n계속하면 기존 작업을 덮어씁니다.")
            }
        }
    }
    pub(super) fn save(&self, payload: &Value) -> Result<Value, GraphError> {
        let state = self.state()?.clone();
        let verdict = validate_save(
            state.model.as_ref(),
            &state.job_name,
            &state.pattern,
            &state.data_path,
            state.schema.as_ref(),
            &state.template_path,
        );
        if !verdict.ok() {
            return Ok(
                json!({"ok":false,"block_reason":verdict.block_reason,"blocked_field":verdict.blocked_field}),
            );
        }
        let Some(gate) = self.generation_gate.as_ref() else {
            return Ok(
                json!({"ok":false,"block_reason":"문서 생성이 진행 중입니다. 끝난 뒤에 Mapping을 저장하세요."}),
            );
        };
        let mut landing = SaveLanding::default();
        let guarded = gate.with_editor_save_guard(|| {
            self.save_guarded(&state, verdict.profile, payload, &mut landing)
        })?;
        let Some(outcome) = guarded else {
            return Ok(
                json!({"ok":false,"block_reason":"문서 생성이 진행 중입니다. 끝난 뒤에 Mapping을 저장하세요."}),
            );
        };
        let mut outcome = outcome?;
        if outcome["ok"] == true {
            self.after_save(&mut outcome, &state.job_name, landing)?;
        }
        Ok(outcome)
    }
    /// The save body that runs while the generation fence is held.
    fn save_guarded(
        &self,
        state: &EditorSessionState,
        profile: Option<MappingProfile>,
        payload: &Value,
        landing: &mut SaveLanding,
    ) -> Result<Value, GraphError> {
        if !Path::new(&state.template_path).is_file() {
            let file = Path::new(&state.template_path)
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("");
            return Ok(
                json!({"ok":false,"block_reason":format!("'{file}' 템플릿 파일이 없어 저장하지 않았습니다. 삭제를 되돌리거나 다른 템플릿을 선택하세요.")}),
            );
        }
        let media = template_media(&state.template_path);
        let data_name = self.data_name(state, self.registered_data(state)?.as_ref());
        let mut profile = profile.ok_or("validated profile missing")?;
        profile.provenance = build_provenance(
            &state.template_path,
            state.schema.as_ref(),
            &profile,
            &data_name,
            &state.loaded_provenance,
            (self.clock)(),
        );
        let outcome = self.jobs.transaction(|session| {
            self.save_in_session(session, state, media, profile, payload, landing)
        })?;
        Ok(outcome)
    }
    /// Collision and drift checks, the durable write, and the landing reload in one write lock.
    fn save_in_session(
        &self,
        session: &JobWriteSession<'_>,
        state: &EditorSessionState,
        media: &str,
        profile: MappingProfile,
        payload: &Value,
        landing: &mut SaveLanding,
    ) -> Result<Value, StoreError> {
        let name = &state.job_name;
        let exists = self.jobs.path_for(name).exists();
        let target = SaveTarget {
            exists,
            job: if exists {
                session.load(name).ok()
            } else {
                None
            },
        };
        if let Some(victim) = target.job.as_ref()
            && victim.media() != media
        {
            let label = hwpx_filler::home_state::work_mode_label(victim.media());
            return Ok(
                json!({"ok":false,"block_reason":format!("작업 이름 '{name}' 은(는) 이미 '{label}' 작업입니다. 형식이 다른 작업은 덮어쓸 수 없으니 다른 이름으로 저장하거나 기존 작업을 삭제한 뒤 다시 저장하세요.")}),
            );
        }
        let self_update = !state.editing_origin.is_empty() && *name == state.editing_origin;
        let drift = self.overwrite_drift(state, &target, self_update)?;
        if !drift.is_empty()
            && (payload["confirm_overwrite"] != true
                || payload["confirmed_overwrite_text"] != drift)
        {
            return Ok(json!({"ok":false,"needs_overwrite":true,"overwrite_text":drift}));
        }
        let origin = if state.editing_origin.is_empty() {
            None
        } else {
            session.load(&state.editing_origin).ok()
        };
        let preserved = target.preserved(self_update, origin.as_ref(), state.base.as_ref());
        let mut job = saved_job(state, profile, &target, preserved);
        carry_dropped_mappings(&mut job, &target, state);
        mapping_rules(&job).map_err(|error| StoreError::Invalid(error.to_string()))?;
        session.save(&mut job, true)?;
        self.land_saved(session, state, landing)?;
        Ok(json!({"ok":true,"saved_name":name}))
    }
    /// The confirmation text an existing destination demands; empty when none is needed.
    fn overwrite_drift(
        &self,
        state: &EditorSessionState,
        target: &SaveTarget,
        self_update: bool,
    ) -> Result<String, StoreError> {
        if !target.exists {
            return Ok(String::new());
        }
        if !self_update {
            return Ok(Self::overwrite_text(
                &state.job_name,
                target.job.as_ref().map(|job| job.name.as_str()),
            ));
        }
        Ok(match target.job.as_ref() {
            None => format!(
                "작업 '{}' 파일이 편집을 여는 사이 손상돼 현재 내용을 확인할 수 없습니다.\n지금 저장하면 그 자리를 이 편집 세션의 상태로 덮어씁니다.",
                state.editing_origin
            ),
            Some(current)
                if self
                    .jobs
                    .content_fingerprint(current)
                    .map_err(|error| StoreError::Invalid(error.to_string()))?
                    != state.editing_fingerprint =>
            {
                format!(
                    "편집 중 외부 변경: 작업 '{}' 이 이 편집 세션을 여는 사이 다른 곳에서 바뀌었습니다.\n지금 저장하면 그 변경 내용을 이 편집 세션의 상태로 덮어씁니다.",
                    state.editing_origin
                )
            }
            _ => String::new(),
        })
    }
    /// Reloads the committed work into the session; failures land as warnings, not errors.
    fn land_saved(
        &self,
        session: &JobWriteSession<'_>,
        state: &EditorSessionState,
        landing: &mut SaveLanding,
    ) -> Result<(), StoreError> {
        let name = &state.job_name;
        match session.load(name) {
            Err(error) => {
                landing.error = Some(format!("저장한 작업을 다시 읽지 못했습니다: {error}"))
            }
            Ok(saved) => {
                if let Err(error) = self.restore_job(saved.clone()) {
                    landing.error = Some(format!(
                        "저장한 작업을 화면에 다시 싣지 못했습니다: {error}"
                    ));
                } else {
                    let mut landed = self
                        .state()
                        .map_err(|error| StoreError::Invalid(error.to_string()))?;
                    landed.section = state.section.clone();
                    landed.context = state.context.clone();
                    landed.context["work"] = json!(name);
                    let failure = landed.reload_failure.clone();
                    if failure.is_empty() {
                        landed.set_notice(format!("작업 '{name}' 을(를) 저장했습니다."), "ok");
                    } else {
                        landed.set_notice(format!("작업 '{name}' 을(를) 저장했습니다.\n연결된 데이터를 다시 읽지 못했습니다: {failure}"),"warn");
                    }
                }
                landing.saved = Some(saved);
            }
        }
        Ok(())
    }
    /// Post-commit refreshes; each failure becomes a save warning instead of undoing the save.
    fn after_save(
        &self,
        outcome: &mut Value,
        name: &str,
        landing: SaveLanding,
    ) -> Result<(), GraphError> {
        if let Some(detail) = landing.error {
            self.post_save_warning(outcome, &detail)?;
        }
        if let (Some(notify), Some(saved)) = (&self.saved_notification, landing.saved.as_ref())
            && let Err(error) = notify(saved)
        {
            self.post_save_warning(
                outcome,
                &format!("저장 알림을 갱신하지 못했습니다: {error}"),
            )?;
        }
        if let Some(after) = &self.after_mapping_saved
            && let Err(error) = after(name)
        {
            self.post_save_warning(
                outcome,
                &format!("실행 확인을 갱신하지 못했습니다: {error}"),
            )?;
        }
        if let Err(error) = self.refresh_binding_pending() {
            self.post_save_warning(
                outcome,
                &format!("연결 상태를 갱신하지 못했습니다: {error}"),
            )?;
        }
        Ok(())
    }
    fn post_save_warning(&self, outcome: &mut Value, detail: &str) -> Result<(), GraphError> {
        let prior = outcome["warning"]
            .as_str()
            .unwrap_or("")
            .strip_prefix("작업은 저장됐지만 ")
            .unwrap_or(outcome["warning"].as_str().unwrap_or(""));
        let warning = format!(
            "작업은 저장됐지만 {}{detail}",
            if prior.is_empty() {
                String::new()
            } else {
                format!("{prior}; ")
            }
        );
        self.state()?.set_notice(&warning, "warn");
        outcome["warning"] = json!(warning);
        Ok(())
    }
}

/// The durable work to write. Exhaustive fields make new durable metadata require an
/// ownership decision here.
fn saved_job(
    state: &EditorSessionState,
    profile: MappingProfile,
    target: &SaveTarget,
    preserved: Option<&Job>,
) -> Job {
    let found = target.job.is_some();
    Job {
        name: state.job_name.clone(),
        template_path: state.template_path.clone(),
        mapping: profile,
        filename_pattern: state.pattern.clone(),
        data_path: state.data_path.clone(),
        data_sheet: state.data_sheet.clone(),
        data_header_row: state.data_header_row,
        data_kind: state.data_kind.clone(),
        last_run_at: if target.exists {
            preserved.map_or_else(String::new, |job| job.last_run_at.clone())
        } else {
            String::new()
        },
        favorited_at: if found {
            preserved.map_or_else(String::new, |job| job.favorited_at.clone())
        } else {
            String::new()
        },
        tags: preserved.map_or_else(Map::new, |job| job.tags.clone()),
        group: preserved.map_or_else(String::new, |job| job.group.clone()),
        authority_id: if found {
            preserved.map_or_else(String::new, |job| job.authority_id.clone())
        } else {
            String::new()
        },
        reviewed_rules: if found {
            preserved.map_or_else(Map::new, |job| job.reviewed_rules.clone())
        } else {
            Map::new()
        },
        data_contract: preserved.and_then(|job| job.data_contract.clone()),
        version: 2,
        template_revision: 1,
        binding_revision: 1,
        previous_rules: json!({}),
    }
}

/// Keeps stored rows for template fields the new profile omitted when the template is unchanged.
fn carry_dropped_mappings(job: &mut Job, target: &SaveTarget, state: &EditorSessionState) {
    if let Some(previous) = target
        .job
        .as_ref()
        .filter(|previous| previous.template_path == job.template_path)
    {
        let present = job
            .mapping
            .mappings
            .iter()
            .map(|item| item.template_field.as_str())
            .collect::<std::collections::HashSet<_>>();
        let schema_fields = state
            .schema
            .as_ref()
            .map(|schema| schema.field_names())
            .unwrap_or_default();
        let missing = previous
            .mapping
            .mappings
            .iter()
            .filter(|item| {
                schema_fields.contains(&item.template_field)
                    && !present.contains(item.template_field.as_str())
            })
            .cloned()
            .collect::<Vec<_>>();
        job.mapping.mappings.extend(missing);
    }
}
