//! Trial inputs, saved cases, and native trial execution.

use super::*;

impl AuthoringController {
    pub(super) fn dispatch_trial(
        &self,
        state: &mut AuthoringState,
        action: &str,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        match action {
            "trial_input" => self.action_trial_input(state, payload),
            "case_upsert" => self.action_case_upsert(state, payload),
            "case_remove" => self.action_case_remove(state, payload),
            "save_cases" => self.action_save_cases(state, payload),
            "trial_fill_names" => self.action_trial_fill_names(state, payload),
            "trial" => self.action_trial(state, payload),
            _ => unreachable!(),
        }
    }
    fn action_trial_input(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        let (Some(values), Some(selected)) = (
            payload.get("values").and_then(Value::as_object),
            payload.get("selected").and_then(Value::as_object),
        ) else {
            return Err(fail("시험 입력이 올바르지 않습니다."));
        };
        session.replace_trial_input(values.clone(), selected.clone());
        session.trial_error.clear();
        Ok(json!({"input_revision":session.trial_input_revision,"stale":session.trial_stale()}))
    }
    fn action_case_upsert(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        let case = json!({"name":payload.get("name"),
                    "values":payload.get("values").unwrap_or(&json!(session.values)),
                    "selected":payload.get("selected").unwrap_or(&json!(session.selected)),
                    "schema":schema_key(&session.analysis)});
        validate_cases(std::slice::from_ref(&case))?;
        session.cases.retain(|item| item["name"] != case["name"]);
        session.cases.push(case.clone());
        session.cases_dirty = true;
        Ok(json!({"ok":true,"case":case}))
    }
    fn action_case_remove(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        let before = session.cases.len();
        session
            .cases
            .retain(|case| case.get("name") != payload.get("name"));
        if session.cases.len() == before {
            return Err(fail("시험 케이스를 찾을 수 없습니다."));
        }
        session.cases_dirty = true;
        Ok(json!({"ok":true}))
    }
    fn action_save_cases(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, false)?;
        if session.save_path.is_empty() {
            return Ok(json!({"needs_document_save":true}));
        }
        if !session.cases_error.is_empty() {
            return Ok(json!({"needs_case_repair":true,"message":session.cases_error}));
        }
        if session.trial_inputs_dirty() {
            return Ok(json!({"needs_case_name":true}));
        }
        self.store.write_cases(
            &AuthoringStore::key(Path::new(&session.save_path))?,
            &session.cases,
        )?;
        session.cases_dirty = false;
        Ok(json!({"ok":true}))
    }
    fn action_trial_fill_names(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        let mut values = session.values.clone();
        let mut added = false;
        for field in session.analysis["fields"].as_array().into_iter().flatten() {
            if let Some(name) = field["name"].as_str()
                && values.get(name).is_none_or(Value::is_null)
            {
                values.insert(name.into(), json!(name));
                added = true;
            }
        }
        if !added {
            return Err(fail("시험 입력이 올바르지 않습니다."));
        }
        session.replace_trial_input(values, session.selected.clone());
        session.trial_error.clear();
        Ok(json!({"values":session.values,"selected":session.selected,
                    "input_revision":session.trial_input_revision,"stale":session.trial_stale()}))
    }
    fn action_trial(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        session.trial_document_revision = -1;
        session.trial_values_revision = -1;
        let result = (|| -> Result<Value, GraphError> {
            if session.media == "txt" {
                let text = std::str::from_utf8(&session.content)?;
                Ok(trial_txt_authoring(
                    text,
                    &session.values,
                    &session.selected,
                )?)
            } else {
                let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
                let selected: HashMap<String, String> = session
                    .selected
                    .iter()
                    .filter_map(|(key, value)| {
                        value
                            .as_str()
                            .map(|choice| (key.clone(), choice.to_owned()))
                    })
                    .collect();
                let trial = trial_hwpx(&package, &session.values, &selected)?;
                Ok(json!({"content":STANDARD.encode(&trial.bytes),
                        "section_entries":section_entries(&HwpxPackage::from_bytes(&trial.bytes,PackageLimits::default())?)?,
                        "excluded":trial.excluded,"occurrences":trial.occurrences,"report":trial.report}))
            }
        })();
        let mut result = match result {
            Ok(result) => result,
            Err(error) => {
                session.trial_error = error.to_string();
                return Ok(json!({"ok":false,"message":session.trial_error}));
            }
        };
        result["tested_selection"] = json!(session.selected);
        result["source_revision"] = json!(session.revision);
        if result["report"]["missing_fields"]
            .as_array()
            .is_none_or(Vec::is_empty)
            && result["report"]["errors"]
                .as_array()
                .is_none_or(Vec::is_empty)
        {
            let fingerprint = projection::trial_input_fingerprint(session);
            for slot in session.analysis["slots"].as_array().into_iter().flatten() {
                for option in slot["options"].as_array().into_iter().flatten() {
                    if let (Some(slot_id), Some(option_id)) =
                        (slot["id"].as_str(), option["id"].as_str())
                        && session.selected.get(slot_id) == Some(&json!(option_id))
                    {
                        session.trial_coverage_evidence.insert(
                            (slot_id.into(), option_id.into()),
                            (session.revision, fingerprint.clone()),
                        );
                    }
                }
            }
        }
        session.trial_result = Some(result.clone());
        session.trial_generation += 1;
        session.trial_error.clear();
        session.trial_document_revision = session.revision as i64;
        session.trial_values_revision = session.trial_input_revision as i64;
        result["session_id"] = json!(session.id);
        result["revision"] = json!(session.revision);
        result["input_revision"] = json!(session.trial_input_revision);
        Ok(result)
    }
}
