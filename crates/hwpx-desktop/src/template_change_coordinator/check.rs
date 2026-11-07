//! Template change check: authority bootstrap, durable prepare, capture, qualify, and admit.

use super::*;

impl TemplateChangeCoordinator {
    pub(super) fn seat_bootstrap(
        &self,
        name: &str,
        request_id: &str,
    ) -> Result<Option<(String, Job)>, TemplateChangeError> {
        self.manifest()?;
        let before = self.job(name)?;
        let minted = format!("w-{}", new_token());
        let bound = if before.authority_id.is_empty() {
            self.jobs
                .assign_authority_id(name, &minted)
                .map_err(|e| fail(e.to_string()))?
                .authority_id
        } else {
            before.authority_id
        };
        if bound.is_empty() {
            return Err(fail("문서 작업 권위를 다시 확인할 수 없습니다"));
        }
        let issued_now = bound == minted;
        let job = self.job(name)?;
        if job.authority_id != bound {
            return Err(fail("문서 작업 권위를 다시 확인할 수 없습니다"));
        }
        self.recover(&bound)?;
        if !self.works.exists(&bound).map_err(|e| fail(e.detail))? {
            let binding = self.binding(&bound, &job);
            let lineage = self.lineage(&bound, &binding);
            let mut candidates = self.candidate_lock()?;
            let mut runner = TemplateStageRunner {
                works: &self.works,
                candidates: &mut candidates,
                qualifications: &self.qualifications,
            };
            let boot_id = format!("boot-{request_id}");
            let result = runner
                .bootstrap(
                    BootstrapInput {
                        work_id: &bound,
                        request_id: &boot_id,
                        lineage: &lineage,
                        binding: &binding,
                        profile_id: qualification_profile_id(job.media())
                            .ok_or_else(|| fail("지원하지 않는 템플릿 형식"))?,
                        application_id: &format!("{bound}.{boot_id}.app"),
                        engine_metadata: &Map::from_iter([(
                            "engine".into(),
                            Value::String("hwpxfiller".into()),
                        )]),
                        actor: LOCAL_ACTOR,
                        at: &self.now(),
                    },
                    |_| {
                        Ok(self
                            .job(name)
                            .map_err(|e| StageError(e.0))?
                            .binding_revision)
                    },
                )
                .map_err(|e| fail(e.0))?;
            if result.result != BOOTSTRAP_OK {
                if issued_now {
                    self.jobs
                        .release_authority_id(name, &bound)
                        .map_err(|e| fail(e.to_string()))?;
                }
                let mut diagnostics =
                    vec![json!({"kind":result.reason.unwrap_or_default(),"message":""})];
                let id = format!("{bound}.{boot_id}.ev");
                match self.qualifications.get_evidence(&id) {
                    Ok(evidence) => {
                        diagnostics.extend(evidence.diagnostics.into_iter().map(Value::Object))
                    }
                    Err(error) if error.kind == ObjectFileErrorKind::NotFound => {}
                    Err(error) => return Err(fail(error.detail)),
                }
                self.record_failure(
                    name,
                    Some(json!({"signature":Self::signature(&job.template_path),
                    "diagnostics":diagnostics})),
                )?;
                return Ok(None);
            }
        }
        self.record_failure(name, None)?;
        let adopted = self.applied.adopt(name, false).map_err(|e| fail(e.0))?;
        Ok(Some((bound, adopted)))
    }
    pub fn check(&self, name: &str, request_id: &str) -> Result<Value, TemplateChangeError> {
        self.check_for_seated_context(name, request_id, LOCAL_ACTOR)
            .map(|item| item.0)
    }

    pub fn check_for_seated_context(
        &self,
        name: &str,
        request_id: &str,
        actor: &str,
    ) -> Result<(Value, Option<Job>, Option<String>), TemplateChangeError> {
        validate_request_id(request_id)?;
        let first = self.job(name)?;
        let Some(profile_id) = qualification_profile_id(first.media()) else {
            return Err(unsupported_check_media(&first));
        };
        if actor != LOCAL_ACTOR {
            return Err(fail(format!(
                "actor {:?} 는 이 Work 에 접근할 수 없습니다",
                actor
            )));
        }
        let Some((work_id, job)) = self.seat_bootstrap(name, request_id)? else {
            return Ok((
                json!({"ok":false,"reason":CAPABILITY_INITIALIZATION_REQUIRED}),
                None,
                None,
            ));
        };
        let mut prep = self.prepare_durably(&work_id, &job, request_id, profile_id)?;
        let mut candidates = self.candidate_lock()?;
        let mut runner = TemplateStageRunner {
            works: &self.works,
            candidates: &mut candidates,
            qualifications: &self.qualifications,
        };
        if prep.status == PREP_CAPTURING {
            prep = self.capture_stage(&mut runner, name, &work_id, &prep)?;
        }
        if prep.status == PREP_QUALIFYING {
            prep = self.qualify_stage(&runner, &work_id, &prep, &job)?;
        }
        let (aggregate, final_job) = self.admit_or_load(&runner, name, &work_id, &prep)?;
        prep = find_preparation(&aggregate, &prep.preparation_id)
            .map_err(|e| fail(e.0))?
            .clone();
        if final_job
            .as_ref()
            .is_some_and(|item: &Job| item.authority_id != work_id)
        {
            return Ok((
                json!({"ok":false,"reason":"work_context_changed"}),
                None,
                None,
            ));
        }
        let view = self.view(&aggregate, &work_id, &prep)?;
        let application_id = aggregate.work.current_template_application_id;
        Ok((
            json!({"ok":true,"preparation":view}),
            final_job,
            Some(application_id),
        ))
    }

    /// Plans (or replays) the request's Preparation inside the durable aggregate update.
    fn prepare_durably(
        &self,
        work_id: &str,
        job: &Job,
        request_id: &str,
        profile_id: &str,
    ) -> Result<TemplateChangePreparation, TemplateChangeError> {
        let binding = self.binding(work_id, job);
        let prep_id = format!("p-{request_id}");
        let now = self.now();
        let aggregate = self
            .works
            .update(work_id, |current| {
                if find_preparation_by_request(current, request_id).is_some() {
                    return Ok(current.clone());
                }
                let pins = PreparePins {
                    source_binding_id: binding.source_binding_id.clone(),
                    source_binding_generation: i64::try_from(binding.generation)
                        .map_err(|_| store_fail("binding_revision 범위 초과"))?,
                    qualification_profile_id: profile_id.into(),
                };
                plan_prepare(
                    current,
                    PrepareIntent {
                        prepare_request_id: request_id,
                        pins: &pins,
                        preparation_id: &prep_id,
                        execution_session_id: &self.session_id,
                        started_at: &now,
                    },
                )
                .map(|plan| plan.aggregate)
                .map_err(|e| store_fail(e.0))
            })
            .map_err(|e| fail(e.detail))?;
        Ok(find_preparation_by_request(&aggregate, request_id)
            .ok_or_else(|| fail("새 Preparation 이 durable aggregate 에 없습니다"))?
            .clone())
    }

    /// Captures a candidate against the binding generation the Preparation pinned.
    fn capture_stage(
        &self,
        runner: &mut TemplateStageRunner<'_>,
        name: &str,
        work_id: &str,
        prep: &TemplateChangePreparation,
    ) -> Result<TemplateChangePreparation, TemplateChangeError> {
        let initial = self.job(name)?;
        let pinned = MutableSourceBinding {
            source_binding_id: prep.source_binding_id.clone(),
            media: initial.media().into(),
            host_reference: initial.template_path,
            display_metadata: Map::new(),
            generation: u64::try_from(prep.source_binding_generation)
                .map_err(|_| fail("Preparation generation 범위 오류"))?,
        };
        let lineage = self.lineage(work_id, &pinned);
        runner
            .capture(
                CaptureInput {
                    work_id,
                    preparation_id: &prep.preparation_id,
                    lineage: &lineage,
                    binding: &pinned,
                    captured_at: &self.now(),
                    created_at: &self.now(),
                },
                |_| {
                    Ok(self
                        .job(name)
                        .map_err(|e| StageError(e.0))?
                        .binding_revision)
                },
            )
            .map_err(|e| fail(e.0))
    }

    fn qualify_stage(
        &self,
        runner: &TemplateStageRunner<'_>,
        work_id: &str,
        prep: &TemplateChangePreparation,
        job: &Job,
    ) -> Result<TemplateChangePreparation, TemplateChangeError> {
        runner
            .qualify(QualificationInput {
                work_id,
                preparation_id: &prep.preparation_id,
                media: job.media(),
                engine_metadata: &Map::from_iter([(
                    "engine".into(),
                    Value::String("hwpxfiller".into()),
                )]),
                started_at: &self.now(),
                completed_at: &self.now(),
                qualified_at: &self.now(),
            })
            .map_err(|e| fail(e.0))
    }

    /// Admits a qualified attempt (observing the Job it re-read) or reloads the aggregate.
    fn admit_or_load(
        &self,
        runner: &TemplateStageRunner<'_>,
        name: &str,
        work_id: &str,
        prep: &TemplateChangePreparation,
    ) -> Result<(WorkTemplateStateAggregate, Option<Job>), TemplateChangeError> {
        if !(prep.status == PREP_QUALIFYING && prep.attempt_id.is_some()) {
            let aggregate = self.works.load(work_id).map_err(|e| fail(e.detail))?;
            return Ok((aggregate, None));
        }
        let observed = std::cell::RefCell::new(None);
        let admitted = runner
            .admit(
                work_id,
                &prep.preparation_id,
                |_| {
                    let fresh = self.job(name).map_err(|e| StageError(e.0))?;
                    let generation = i64::try_from(fresh.binding_revision)
                        .map_err(|_| StageError("binding_revision 범위 초과".into()))?;
                    *observed.borrow_mut() = Some(fresh);
                    Ok((format!("{work_id}.binding"), generation))
                },
                &format!("{}-chg", prep.preparation_id),
                &self.now(),
            )
            .map_err(|e| fail(e.0))?;
        Ok((admitted.aggregate, observed.into_inner()))
    }
}

/// A check request key is a short ASCII token safe to embed in durable object ids.
fn validate_request_id(request_id: &str) -> Result<(), TemplateChangeError> {
    if request_id.is_empty()
        || request_id.len() > 64
        || !request_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return Err(fail(format!("잘못된 확인 요청 키 {:?}", request_id)));
    }
    Ok(())
}

fn unsupported_check_media(job: &Job) -> TemplateChangeError {
    fail(format!(
        "지원하지 않는 템플릿 형식이라 변경사항 확인을(를) 지원하지 않습니다(형식={})",
        if job.media().is_empty() {
            "미상"
        } else {
            job.media()
        }
    ))
}
