//! Shape current host facts into the pure document-creation workbench authority.

use hwpx_filler::document_creation_workbench::{
    ActiveWorkContext, ContentSelectionSummary, DataScopeSummary, DeliveryPreviewSummary,
    DocumentCreationWorkbenchResult, HistoricalOutcomeSummary, InputRequirement,
    RecordValidationSummary, WorkbenchCompositionInput, WorkbenchContextIntegrity,
    binding_review_needed, compose_document_creation_workbench,
};
use hwpx_filler::execution_compilation::{ACTIVE_FIELD_UNBOUND, REQUIRED_SOURCE_KEY_MISSING};
use hwpx_filler::field_binding_input::{INACTIVE_ONLY, PRESERVED};
use hwpx_filler::fresh_execution_observation::{
    ADMISSION_CONTEXT_ERROR, EXECUTION_EVIDENCE_NOT_OBSERVED, FreshExecutionObservation,
    NOT_ADMITTED, RuntimePolicyAdmission,
};
use hwpx_filler::run_delivery_intent::RunDeliveryIntent;
use hwpx_filler::slot_reconciliation::{BLOCKED, SlotConfigurationResolution};
use hwpx_filler::slot_selection::{
    CARDINALITY_VIOLATION, MISSING_REQUIRED_SELECTION, NO_AVAILABLE_OPTIONS,
};
use hwpx_filler::workbench_execution_status::{
    CHECKING, NO_EVIDENCE, STALE, derive_workbench_execution_status,
    workbench_execution_status_phrase,
};
use serde_json::{Value, json};

pub struct WorkbenchFacts {
    pub data_mounted: bool,
    pub selected_record_count: usize,
    pub total_record_count: usize,
    pub active_work_ref: Option<String>,
    pub active_work_data_bound: bool,
    pub slot_view: Option<SlotConfigurationResolution>,
    pub orchestration: String,
    pub fresh_observation: Option<FreshExecutionObservation>,
    pub active_field_requirement_ids: Vec<String>,
    pub binding_review_needed: bool,
    pub template_change_verdict: Option<String>,
    pub input_requirements: Vec<InputRequirement>,
    pub record_validation: Option<RecordValidationSummary>,
    pub delivery: Option<DeliveryPreviewSummary>,
    pub run_delivery_intent: Option<RunDeliveryIntent>,
    pub context_integrity: Option<WorkbenchContextIntegrity>,
    pub historical_outcome: Option<HistoricalOutcomeSummary>,
}

pub struct WorkbenchObservationProduct;

impl WorkbenchObservationProduct {
    pub fn content_selection_from_view(
        view: Option<&SlotConfigurationResolution>,
    ) -> ContentSelectionSummary {
        let Some(view) = view else {
            return ContentSelectionSummary::default();
        };
        let selectable = [
            MISSING_REQUIRED_SELECTION,
            "SELECTED_OPTION_REMOVED",
            CARDINALITY_VIOLATION,
        ];
        ContentSelectionSummary {
            selected_option_ids: view
                .slots
                .iter()
                .flat_map(|slot| slot.effective_option_ids.clone())
                .collect(),
            has_unselected_required_content: view.configuration_status == BLOCKED
                && view
                    .slots
                    .iter()
                    .any(|slot| selectable.contains(&slot.status.as_str())),
            requires_template_repair: view.slots.iter().any(|slot| {
                matches!(
                    slot.status.as_str(),
                    NO_AVAILABLE_OPTIONS | "UNSUPPORTED_SELECTION_POLICY"
                )
            }),
        }
    }

    pub fn binding_review_pending(
        fresh: Option<&FreshExecutionObservation>,
        requirements: &[InputRequirement],
    ) -> bool {
        let blocked = match fresh {
            Some(FreshExecutionObservation::WorkBlocked(work)) => {
                work.normalized_blockers_or_policy.iter().any(|code| {
                    matches!(
                        code.as_str(),
                        ACTIVE_FIELD_UNBOUND | REQUIRED_SOURCE_KEY_MISSING
                    )
                })
            }
            _ => false,
        };
        binding_review_needed(blocked, requirements)
    }

    fn verdicts(
        fresh: Option<&FreshExecutionObservation>,
    ) -> (RuntimePolicyAdmission, Option<&str>, Vec<String>) {
        match fresh {
            Some(FreshExecutionObservation::Sealed(sealed)) => {
                (sealed.runtime_policy_admission.clone(), None, vec![])
            }
            Some(FreshExecutionObservation::WorkBlocked(work)) => (
                unobserved(),
                Some(work.current_sealability.as_str()),
                work.normalized_blockers_or_policy.clone(),
            ),
            Some(FreshExecutionObservation::ContextError(error)) => (
                RuntimePolicyAdmission {
                    state: ADMISSION_CONTEXT_ERROR.into(),
                    reasons: vec![error.detail.clone()],
                },
                None,
                vec![],
            ),
            None => (unobserved(), None, vec![]),
        }
    }

    pub fn execution_status(
        orchestration: &str,
        fresh: Option<&FreshExecutionObservation>,
    ) -> (&'static str, &'static str) {
        let (admission, sealability, _) = Self::verdicts(fresh);
        let code = derive_workbench_execution_status(orchestration, Some(&admission), sealability);
        (
            code,
            workbench_execution_status_phrase(code).expect("seven known execution states"),
        )
    }

    pub fn compose(
        mut facts: WorkbenchFacts,
    ) -> Result<
        (
            DocumentCreationWorkbenchResult,
            (&'static str, &'static str),
        ),
        String,
    > {
        let (admission, sealability, blockers) = Self::verdicts(facts.fresh_observation.as_ref());
        let status =
            derive_workbench_execution_status(&facts.orchestration, Some(&admission), sealability);
        let phrase =
            workbench_execution_status_phrase(status).expect("seven known execution states");
        if facts.input_requirements.is_empty()
            && let Some(FreshExecutionObservation::Sealed(sealed)) =
                facts.fresh_observation.as_ref()
        {
            for requirement in &sealed.sealed_plan_value.active_field_requirements {
                let field_id = requirement
                    .get("field_id")
                    .and_then(Value::as_str)
                    .ok_or("sealed active field requirement lacks field_id")?;
                facts.input_requirements.push(InputRequirement {
                    field_id: field_id.into(),
                    display_label: field_id.into(),
                    binding_state: PRESERVED.into(),
                    exact_target: format!("binding/{field_id}"),
                });
            }
        }
        if facts.active_field_requirement_ids.is_empty() {
            facts.active_field_requirement_ids = facts
                .input_requirements
                .iter()
                .filter(|item| item.binding_state != INACTIVE_ONLY)
                .map(|item| item.field_id.clone())
                .collect();
        }
        let signal = facts.binding_review_needed
            || blockers.iter().any(|code| {
                matches!(
                    code.as_str(),
                    ACTIVE_FIELD_UNBOUND | REQUIRED_SOURCE_KEY_MISSING
                )
            });
        let input = WorkbenchCompositionInput {
            data_scope: DataScopeSummary {
                mounted: facts.data_mounted,
                record_scope_required: true,
                selected_record_count: facts.selected_record_count,
                total_record_count: facts.total_record_count,
            },
            content_selection: Self::content_selection_from_view(facts.slot_view.as_ref()),
            active_work: match facts.active_work_ref.filter(|work| !work.is_empty()) {
                Some(work_ref) => ActiveWorkContext {
                    active: true,
                    work_ref: Some(work_ref),
                    data_bound: facts.active_work_data_bound,
                    ..Default::default()
                },
                None => ActiveWorkContext::default(),
            },
            admission,
            orchestration: facts.orchestration,
            delivery: facts.delivery.unwrap_or_default(),
            record_validation: facts.record_validation.unwrap_or_default(),
            template_change_verdict: facts.template_change_verdict,
            active_field_requirement_ids: facts.active_field_requirement_ids,
            binding_review_needed: signal,
            input_requirements: facts.input_requirements,
            run_delivery_intent: facts.run_delivery_intent,
            context_integrity: facts.context_integrity,
            historical_outcome: facts.historical_outcome,
        };
        Ok((
            compose_document_creation_workbench(input)?,
            (status, phrase),
        ))
    }

    pub fn observe(facts: WorkbenchFacts) -> Result<Value, String> {
        let (result, (status, phrase)) = Self::compose(facts)?;
        Ok(serialize_observation(&result, status, phrase))
    }
}

fn unobserved() -> RuntimePolicyAdmission {
    RuntimePolicyAdmission {
        state: NOT_ADMITTED.into(),
        reasons: vec![EXECUTION_EVIDENCE_NOT_OBSERVED.into()],
    }
}

pub fn serialize_observation(
    result: &DocumentCreationWorkbenchResult,
    status: &str,
    phrase: &str,
) -> Value {
    match result {
        DocumentCreationWorkbenchResult::ContextError(error) => json!({
            "kind":"context_error", "code":error.code, "detail":error.detail,
            "user_fixable":false, "primary_action":"RECOVER_CONTEXT",
            "execution_status_code":status, "execution_status_phrase":phrase,
            "recover_action":{"label":"다시 확인","enabled":true,"disabled_reason":null},
            "create_action":{"label":"문서 만들기","enabled":false,"disabled_reason":phrase},
        }),
        DocumentCreationWorkbenchResult::Observation(observation) => {
            let input = &observation.input;
            let enabled = observation.create_documents_enabled()
                || (input.orchestration != CHECKING
                    && observation.blockers.iter().any(|code| {
                        matches!(code.as_str(), "EXECUTION_NO_EVIDENCE" | "EXECUTION_STALE")
                    })
                    && observation.blockers.iter().all(|code| {
                        matches!(
                            code.as_str(),
                            "EXECUTION_NO_EVIDENCE" | "EXECUTION_STALE" | "REVIEW_DELIVERY"
                        )
                    }));
            let requirements: Vec<_> = input.input_requirements.iter().filter(|item| item.action_required())
                .map(|item| json!({"field_id":item.field_id,"display_label":item.display_label,
                    "binding_state":item.binding_state,"action_required":true,"exact_target":item.exact_target})).collect();
            let issue_count = input.record_validation.marked_value_count();
            let notice = if input.record_validation.advisories.is_empty() {
                String::new()
            } else {
                format!("빈 값 {issue_count}칸이 있습니다. 문서에는 미입력 표식이 들어갑니다.")
            };
            json!({
                "kind":"observation", "primary_action":observation.primary_action,
                "primary_action_enabled":observation.disabled_reason.is_none(),
                "disabled_reason":observation.disabled_reason,
                "execution_action": if matches!(status, NO_EVIDENCE | CHECKING | STALE) {
                    json!({"label":"현재 설정 확인",
                        "enabled":observation.resolve_execution_disabled_reason().is_none(),
                        "disabled_reason":observation.resolve_execution_disabled_reason()})
                } else { Value::Null },
                "create_action":{"label":"문서 만들기","enabled":enabled,
                    "disabled_reason":if enabled { None } else { observation.create_documents_disabled_reason() }},
                "blockers":observation.blockers, "deep_link_targets":observation.deep_link_targets,
                "execution_status_code":status,"execution_status_phrase":phrase,
                "materialization_readiness":observation.materialization_readiness,
                "admission":{"state":input.admission.state,"reasons":input.admission.reasons},
                "historical_outcome":input.historical_outcome,
                "active_field_requirement_ids":input.active_field_requirement_ids,
                "input_requirements":requirements,
                "binding_review_needed":observation.blockers.iter().any(|code| code == "REVIEW_BINDING"),
                "record_validation":{"validated_count":input.record_validation.validated_count,
                    "blocked_count":input.record_validation.blocked_count,
                    "issue_count":input.record_validation.issue_count,
                    "issues":input.record_validation.issues,
                    "advisory_count":issue_count,"advisory_notice":notice,
                    "advisories":input.record_validation.advisories},
                "run_delivery_intent":input.run_delivery_intent.as_ref().map(|item| json!({
                    "output_directory":item.output_directory,"collision_policy":item.collision_policy})),
                "delivery":{"resolvable":input.delivery.resolvable,
                    "planned_documents":input.delivery.planned_documents,"blockers":input.delivery.blockers},
                "content_section_label":"포함할 내용", "input_requirements_label":"입력이 필요한 항목",
                "delivery_label":"생성 예정 문서",
                "active_work":{"active":input.active_work.active,"work_ref":input.active_work.work_ref},
                "data_scope":{"mounted":input.data_scope.mounted,
                    "selected_record_count":input.data_scope.selected_record_count,
                    "total_record_count":input.data_scope.total_record_count},
            })
        }
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_filler::field_binding_input::{BROKEN, NEW_ACTIVE_FIELD};
    use hwpx_filler::fresh_execution_observation::{
        ADMITTED, CurrentSealedPlanObservation, CurrentWorkExecutionObservation,
        ExecutionObservationContextError,
    };
    use hwpx_filler::workbench_execution_status::CURRENT;

    fn facts() -> WorkbenchFacts {
        WorkbenchFacts {
            data_mounted: true,
            selected_record_count: 1,
            total_record_count: 1,
            active_work_ref: Some("job".into()),
            active_work_data_bound: true,
            slot_view: None,
            orchestration: NO_EVIDENCE.into(),
            fresh_observation: None,
            active_field_requirement_ids: vec![],
            binding_review_needed: false,
            template_change_verdict: None,
            input_requirements: vec![],
            record_validation: None,
            delivery: None,
            run_delivery_intent: None,
            context_integrity: None,
            historical_outcome: None,
        }
    }

    #[test]
    fn unobserved_execution_keeps_resolve_and_request_create_separate() {
        for (mounted, status) in [(false, NO_EVIDENCE), (true, NO_EVIDENCE), (true, STALE)] {
            let view = WorkbenchObservationProduct::observe(WorkbenchFacts {
                data_mounted: mounted,
                orchestration: status.into(),
                ..facts()
            })
            .unwrap();
            assert_eq!(view["execution_status_code"], status);
            assert_eq!(
                view["primary_action"],
                if mounted {
                    "RESOLVE_EXECUTION"
                } else {
                    "SELECT_DATA"
                }
            );
            assert_eq!(
                view["execution_action"],
                json!({"label":"현재 설정 확인",
                "enabled":true,"disabled_reason":null})
            );
            assert_eq!(view["create_action"]["enabled"], mounted);
            assert_eq!(view["delivery"]["resolvable"], false);
            assert_eq!(view["materialization_readiness"], "NOT_READY");
            assert_eq!(
                view["admission"],
                json!({"state":"NOT_ADMITTED",
                "reasons":[EXECUTION_EVIDENCE_NOT_OBSERVED]})
            );
            assert!(
                !view["blockers"]
                    .as_array()
                    .unwrap()
                    .contains(&json!("RUNTIME_NOT_ADMITTED"))
            );
            if !mounted {
                assert_eq!(
                    view["execution_status_phrase"],
                    "현재 설정을 확인해야 합니다"
                );
                assert_eq!(
                    view["create_action"]["disabled_reason"],
                    "필요한 준비를 먼저 완료해 주세요"
                );
            }
        }
    }

    #[test]
    fn current_work_blockers_and_context_failures_keep_their_recovery_meaning() {
        for code in [ACTIVE_FIELD_UNBOUND, REQUIRED_SOURCE_KEY_MISSING] {
            let fresh = FreshExecutionObservation::WorkBlocked(CurrentWorkExecutionObservation {
                work_authority_ref: "job".into(),
                current_sealability: "DOMAIN_BLOCKED".into(),
                observed_at: "now".into(),
                current_template_application_ref: None,
                normalized_blockers_or_policy: vec![code.into()],
            });
            let (admission, sealability, reasons) =
                WorkbenchObservationProduct::verdicts(Some(&fresh));
            assert_eq!(admission.state, NOT_ADMITTED);
            assert_eq!(sealability, Some("DOMAIN_BLOCKED"));
            assert_eq!(reasons, [code]);
            assert!(WorkbenchObservationProduct::binding_review_pending(
                Some(&fresh),
                &[]
            ));
            let view = WorkbenchObservationProduct::observe(WorkbenchFacts {
                fresh_observation: Some(fresh),
                ..facts()
            })
            .unwrap();
            assert_eq!(view["primary_action"], "REVIEW_BINDING");
            assert_eq!(view["materialization_readiness"], "NOT_READY");
            assert_eq!(view["create_action"]["enabled"], false);
        }
        let fresh = FreshExecutionObservation::ContextError(ExecutionObservationContextError {
            code: "C_ERR".into(),
            detail: "복원 실패".into(),
        });
        assert_eq!(
            WorkbenchObservationProduct::verdicts(Some(&fresh)).0.state,
            ADMISSION_CONTEXT_ERROR
        );
        assert!(!WorkbenchObservationProduct::binding_review_pending(
            Some(&fresh),
            &[]
        ));
        let view = WorkbenchObservationProduct::observe(WorkbenchFacts {
            orchestration: CURRENT.into(),
            fresh_observation: Some(fresh),
            ..facts()
        })
        .unwrap();
        assert_eq!(view["kind"], "context_error");
        assert_eq!(view["detail"], "복원 실패");
        assert_eq!(view["primary_action"], "RECOVER_CONTEXT");
        assert_eq!(view["user_fixable"], false);
        assert_eq!(view["execution_status_code"], "CONTEXT_ERROR");
        assert_eq!(view["create_action"]["enabled"], false);
    }

    #[test]
    fn requirement_display_filters_actions_without_discarding_classification() {
        let sealed = FreshExecutionObservation::Sealed(Box::new(CurrentSealedPlanObservation {
            sealed_plan_value: crate::current_execution_preparation::tests::source_plan(),
            runtime_policy_admission: RuntimePolicyAdmission {
                state: ADMITTED.into(),
                reasons: vec![],
            },
            observed_at: "now".into(),
            current_field_binding: None,
        }));
        let (result, (status, phrase)) = WorkbenchObservationProduct::compose(WorkbenchFacts {
            orchestration: CURRENT.into(),
            fresh_observation: Some(sealed.clone()),
            ..facts()
        })
        .unwrap();
        let DocumentCreationWorkbenchResult::Observation(observation) = &result else {
            panic!("observation")
        };
        assert_eq!(observation.input.input_requirements.len(), 1);
        assert_eq!(
            observation.input.input_requirements[0].binding_state,
            PRESERVED
        );
        let view = serialize_observation(&result, status, phrase);
        assert_eq!(view["input_requirements"], json!([]));
        assert_eq!(view["input_requirements_label"], "입력이 필요한 항목");
        assert_eq!(view["delivery_label"], "생성 예정 문서");
        assert!(view["delivery"].get("is_artifact").is_none());
        assert_eq!(view["execution_status_code"], CURRENT);
        assert_eq!(view["materialization_readiness"], "READY");
        for text in [
            view["execution_status_phrase"].as_str().unwrap(),
            view["content_section_label"].as_str().unwrap(),
            view["input_requirements_label"].as_str().unwrap(),
            view["delivery_label"].as_str().unwrap(),
            view["disabled_reason"].as_str().unwrap_or(""),
        ] {
            for word in [
                "Slot",
                "Sealed",
                "Plan",
                "digest",
                "Application",
                "VDR",
                "Candidate",
            ] {
                assert!(!text.contains(word), "{text}");
            }
        }
        let requirements = [
            ("보존", PRESERVED),
            ("깨짐", BROKEN),
            ("신규", NEW_ACTIVE_FIELD),
            ("비활성", INACTIVE_ONLY),
        ]
        .map(|(field, state)| InputRequirement {
            field_id: field.into(),
            display_label: field.into(),
            binding_state: state.into(),
            exact_target: format!("binding/{field}"),
        })
        .to_vec();
        let (result, (status, phrase)) = WorkbenchObservationProduct::compose(WorkbenchFacts {
            orchestration: CURRENT.into(),
            fresh_observation: Some(sealed),
            input_requirements: requirements.clone(),
            ..facts()
        })
        .unwrap();
        let DocumentCreationWorkbenchResult::Observation(observation) = &result else {
            panic!("observation")
        };
        assert_eq!(observation.input.input_requirements, requirements);
        let view = serialize_observation(&result, status, phrase);
        assert_eq!(
            view["input_requirements"]
                .as_array()
                .unwrap()
                .iter()
                .map(|item| item["field_id"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["깨짐", "신규"]
        );
        assert!(
            view["input_requirements"]
                .as_array()
                .unwrap()
                .iter()
                .all(|item| item["action_required"] == true)
        );
    }
}
