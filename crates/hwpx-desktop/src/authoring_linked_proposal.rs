//! Job linkage and field proposal decisions for an authoring session.

use super::*;

impl AuthoringController {
    pub(super) fn linked_jobs(
        &self,
        session: &AuthoringSession,
    ) -> Result<(Vec<hwpx_filler::job::Job>, usize), GraphError> {
        if session.save_path.is_empty() {
            return Ok((Vec::new(), 0));
        }
        let (jobs, corrupt) = self.jobs.list_jobs_with_corruption()?;
        let target = crate::single_instance::normalize_windows_path(Path::new(&session.save_path))?
            .to_lowercase();
        Ok((
            jobs.into_iter()
                .filter(|job| {
                    !job.template_path.is_empty()
                        && crate::single_instance::normalize_windows_path(Path::new(
                            &job.template_path,
                        ))
                        .is_ok_and(|path| path.to_lowercase() == target)
                })
                .collect(),
            corrupt.len(),
        ))
    }
    pub(super) fn saved_for_jobs(&self, session: &mut AuthoringSession) -> Result<(), GraphError> {
        if session.save_path.is_empty() || session.dirty() {
            return Err(fail("문서를 저장한 뒤 기존 작업에 적용하세요."));
        }
        if self
            .store
            .current_fingerprint(Path::new(&session.save_path))?
            .as_ref()
            != session.baseline.as_ref()
        {
            session.external_changed = true;
            return Err(fail("파일이 외부에서 변경되었습니다. 다시 확인하세요."));
        }
        Ok(())
    }
    pub(super) fn linked_job(
        &self,
        session: &AuthoringSession,
        name: Option<&str>,
    ) -> Result<hwpx_filler::job::Job, GraphError> {
        let name = name
            .filter(|name| !name.is_empty())
            .ok_or("적용할 작업 이름이 없습니다.")?;
        self.linked_jobs(session)?
            .0
            .into_iter()
            .find(|job| job.name == name)
            .ok_or_else(|| fail("이 문서를 사용하는 작업을 찾을 수 없습니다."))
    }
    pub(super) fn seed_proposal_bindings(
        &self,
        job_name: &str,
        session: &AuthoringSession,
        result: &Value,
    ) -> Result<usize, GraphError> {
        if session.proposal_bindings.is_empty()
            || !matches!(
                result["status"].as_str(),
                Some("applied" | "already_applied")
            )
            || result.get("is_current") == Some(&Value::Bool(false))
        {
            return Ok(0);
        }
        let fields: HashSet<_> = session.analysis["fields"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|field| field["name"].as_str().map(str::to_owned))
            .collect();
        let drafts = session
            .proposal_bindings
            .iter()
            .filter(|(name, _)| fields.contains(*name))
            .map(|(name, binding)| {
                hwpx_filler::mapping::FieldMapping::new(
                    name.as_str(),
                    binding["source"].as_str().unwrap_or(""),
                    binding["type"].as_str().unwrap_or(""),
                    "",
                    binding["fmt"].as_str().unwrap_or(""),
                    None,
                )
            })
            .collect::<Result<Vec<_>, _>>()?;
        let count = self.jobs.transaction(|writer| {
            let mut job = writer.load(job_name)?;
            let existing: HashSet<_> = job
                .mapping
                .mappings
                .iter()
                .map(|item| item.template_field.as_str())
                .collect();
            let added: Vec<_> = drafts
                .into_iter()
                .filter(|item| !existing.contains(item.template_field.as_str()))
                .collect();
            let count = added.len();
            if count > 0 {
                job.mapping.mappings.extend(added);
                writer.save(&mut job, true)?
            }
            Ok(count)
        })?;
        Ok(count)
    }
    pub(super) fn dispatch_linked_proposal(
        &self,
        state: &mut AuthoringState,
        action: &str,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        match action {
            "impact" => self.action_impact(state, payload),
            "prepare_apply" => self.action_prepare_apply(state, payload),
            "apply_job" => self.action_apply_job(state, payload),
            "propose_fields"
            | "propose_make"
            | "propose_make_all"
            | "propose_dismiss"
            | "propose_off"
            | "propose_pick_column" => self.dispatch_proposal(state, action, payload),
            _ => unreachable!(),
        }
    }
    pub(super) fn has_linked_jobs(&self, session: &AuthoringSession) -> Result<bool, GraphError> {
        if session.save_path.is_empty() {
            return Ok(false);
        }
        if self.template_change.is_none() {
            return Ok(true);
        }
        let (jobs, corrupt) = self.linked_jobs(session)?;
        Ok(!jobs.is_empty() || corrupt > 0)
    }
    pub(super) fn preview_impact(
        &self,
        session: &AuthoringSession,
        preview: &Value,
        command: &Value,
    ) -> Result<Value, GraphError> {
        let (jobs, corrupt) = if session.save_path.is_empty() {
            (Vec::new(), 0)
        } else {
            let (jobs, corrupt) = self.jobs.list_jobs_with_corruption()?;
            let target =
                crate::single_instance::normalize_windows_path(Path::new(&session.save_path))?;
            (
                jobs.into_iter()
                    .filter(|job| {
                        crate::single_instance::normalize_windows_path(Path::new(
                            &job.template_path,
                        ))
                        .is_ok_and(|path| path == target)
                    })
                    .map(|job| job.name)
                    .collect(),
                corrupt.len(),
            )
        };
        let field_set = |analysis: &Value| -> BTreeSet<String> {
            analysis["fields"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|field| field["name"].as_str().map(str::to_owned))
                .collect()
        };
        let before = field_set(&session.analysis);
        let after = field_set(&preview["result"]);
        let action = command["type"].as_str().unwrap_or("");
        let body_changed = matches!(
            action,
            "delete"
                | "unset_field"
                | "repair_marker"
                | "duplicate"
                | "move"
                | "paste"
                | "revert_template"
        ) || action == "create_field"
            && preview.get("original").is_some_and(truthy);
        Ok(json!({"linked_jobs":jobs,"impact_unverified":corrupt,
            "field_delta":{"added_fields":after.difference(&before).collect::<Vec<_>>(),
                "removed_fields":before.difference(&after).collect::<Vec<_>>()},
            "structure_delta":structure_delta(&session.analysis,&preview["result"],renamed(command)),
            "body_changed":body_changed}))
    }
    fn action_impact(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session(payload, true)?;
        let Some(coordinator) = self.template_change.as_ref() else {
            return Ok(
                json!({"available":false,"reason":"작업 연결을 확인할 수 없습니다.","jobs":[]}),
            );
        };
        let (jobs, corrupted) = self.linked_jobs(session)?;
        let current_fields: BTreeSet<_> = session.analysis["fields"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|field| field["name"].as_str().map(str::to_owned))
            .collect();
        let readiness = projection::readiness(session, &projection::problems(session)?);
        let blocked = if readiness["state"] != "ready" {
            readiness.get("message").cloned().unwrap_or(Value::Null)
        } else if session.save_path.is_empty() || session.dirty() {
            json!("문서를 저장한 뒤 기존 작업에 적용하세요.")
        } else if session.external_changed {
            json!("파일이 외부에서 변경되었습니다. 다시 확인하세요.")
        } else {
            Value::Null
        };
        let current_slots: HashSet<_> = session.analysis["slots"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|slot| slot["id"].as_str().map(str::to_owned))
            .collect();
        let current_options: HashSet<_> = session.analysis["slots"]
            .as_array()
            .into_iter()
            .flatten()
            .flat_map(|slot| {
                slot["options"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(move |option| {
                        Some((
                            slot["id"].as_str()?.to_owned(),
                            option["id"].as_str()?.to_owned(),
                        ))
                    })
            })
            .collect();
        let changes: Vec<_> = session
            .identifier_changes
            .iter()
            .filter(|change| {
                if change["kind"] == "slot" {
                    !current_slots.contains(change["from"].as_str().unwrap_or(""))
                } else {
                    !current_options.contains(&(
                        change["slot_id"].as_str().unwrap_or("").to_owned(),
                        change["from"].as_str().unwrap_or("").to_owned(),
                    ))
                }
            })
            .cloned()
            .collect();
        let mut jobs_view = Vec::new();
        for job in jobs {
            let change = coordinator.zone(
                &job.name,
                job.media(),
                !Path::new(&job.template_path).is_file(),
            )?;
            let old: BTreeSet<_> = job.template_fields().into_iter().collect();
            let added: Vec<_> = current_fields.difference(&old).cloned().collect();
            let removed: Vec<_> = old.difference(&current_fields).cloned().collect();
            let status = change["preparation"]["status"].as_str().map(str::to_owned);
            jobs_view.push(json!({"name":job.name,"added_fields":added,"unmapped_fields":removed,
                        "removed_fields":removed,"change":change,"change_status":status,"blocked_reason":blocked}));
        }
        Ok(
            json!({"available":true,"save_required":session.dirty() || session.save_path.is_empty(),
                    "usable":blocked.is_null(),"content_changed_since_save":session.dirty(),
                    "structure_delta":structure_delta(&session.saved_analysis,&session.analysis,changes.clone()),
                    "identifier_changes":changes,"unverified_jobs":corrupted,"jobs":jobs_view}),
        )
    }
    fn action_prepare_apply(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let coordinator = self
            .template_change
            .as_ref()
            .ok_or("작업 변경 확인이 연결되지 않았습니다.")?;
        let session = state.session_mut(payload, true)?;
        self.saved_for_jobs(session)?;
        let job = self.linked_job(session, payload.get("job_name").and_then(Value::as_str))?;
        let result = coordinator.check(&job.name, &Uuid::new_v4().simple().to_string())?;
        let mut result = result
            .as_object()
            .cloned()
            .ok_or("작업 변경 확인 결과가 올바르지 않습니다.")?;
        result.insert("job_name".into(), json!(job.name));
        result.insert(
            "change_token".into(),
            result
                .get("preparation")
                .and_then(|prep| prep.get("change_token"))
                .cloned()
                .unwrap_or(Value::Null),
        );
        Ok(Value::Object(result))
    }
    fn action_apply_job(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let coordinator = self
            .template_change
            .as_ref()
            .ok_or("작업 변경 적용이 연결되지 않았습니다.")?;
        let session = state.session_mut(payload, true)?;
        self.saved_for_jobs(session)?;
        let job = self.linked_job(session, payload.get("job_name").and_then(Value::as_str))?;
        let token = payload
            .get("change_token")
            .and_then(Value::as_str)
            .filter(|token| !token.is_empty())
            .ok_or("변경 확인 토큰이 없습니다.")?;
        let mut result = coordinator.apply(&job.name, token)?;
        let seeded = self.seed_proposal_bindings(&job.name, session, &result)?;
        result["seeded_bindings"] = json!(seeded);
        result["job_name"] = json!(job.name);
        Ok(result)
    }
}
