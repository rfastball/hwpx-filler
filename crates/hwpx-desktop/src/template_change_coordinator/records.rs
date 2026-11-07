//! Initialization failure records, session-scoped opaque tokens, and preparation views.

use super::*;

impl TemplateChangeCoordinator {
    pub(super) fn failures_path(&self) -> PathBuf {
        self.root.join("init_failures.json")
    }
    pub(super) fn failures(&self) -> Result<Map<String, Value>, TemplateChangeError> {
        let _guard = self
            .failures
            .lock()
            .map_err(|_| fail("failure record lock poisoned"))?;
        self.read_failures()
    }
    pub(super) fn read_failures(&self) -> Result<Map<String, Value>, TemplateChangeError> {
        let bytes = match fs::read(self.failures_path()) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Map::new()),
            Err(error) => return Err(fail(error.to_string())),
        };
        serde_json::from_slice::<Map<String, Value>>(&bytes).map_err(|e| fail(e.to_string()))
    }
    pub(super) fn record_failure(
        &self,
        name: &str,
        entry: Option<Value>,
    ) -> Result<(), TemplateChangeError> {
        let _guard = self
            .failures
            .lock()
            .map_err(|_| fail("failure record lock poisoned"))?;
        let mut failures = self.read_failures()?;
        match entry {
            Some(value) => {
                failures.insert(name.into(), value);
            }
            None => {
                if failures.remove(name).is_none() {
                    return Ok(());
                }
            }
        }
        fs::create_dir_all(&self.root).map_err(|e| fail(e.to_string()))?;
        let bytes = serde_json::to_vec(&failures).map_err(|e| fail(e.to_string()))?;
        write_bytes_atomic(&self.failures_path(), &bytes).map_err(|e| fail(e.to_string()))
    }
    pub(super) fn token(
        &self,
        work_id: &str,
        id: &str,
        change: bool,
    ) -> Result<String, TemplateChangeError> {
        let mut state = self
            .session
            .lock()
            .map_err(|_| fail("session lock poisoned"))?;
        let key = (work_id.to_owned(), id.to_owned());
        if change {
            if let Some(value) = state.change_tokens.get(&key) {
                return Ok(value.clone());
            }
            let token = new_token();
            state.change_tokens.insert(key.clone(), token.clone());
            state.token_change.insert(token.clone(), key);
            Ok(token)
        } else {
            Ok(state
                .prep_tokens
                .entry(key)
                .or_insert_with(new_token)
                .clone())
        }
    }
    pub(super) fn diagnostics(
        &self,
        prep: &TemplateChangePreparation,
    ) -> Result<Vec<(String, String)>, TemplateChangeError> {
        let mut result = prep
            .diagnostics
            .iter()
            .map(|entry| {
                (
                    entry
                        .get("reason")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .into(),
                    String::new(),
                )
            })
            .collect::<Vec<_>>();
        if let Some(id) = &prep.evidence_id {
            match self.qualifications.get_evidence(id) {
                Ok(evidence) => result.extend(evidence.diagnostics.iter().map(|entry| {
                    (
                        entry
                            .get("kind")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .into(),
                        entry
                            .get("message")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .into(),
                    )
                })),
                Err(error) if error.kind == ObjectFileErrorKind::NotFound => {}
                Err(error) => return Err(fail(error.detail)),
            }
        }
        Ok(result)
    }
    pub(super) fn view(
        &self,
        aggregate: &WorkTemplateStateAggregate,
        work_id: &str,
        prep: &TemplateChangePreparation,
    ) -> Result<Value, TemplateChangeError> {
        let (status, token) = match prep.prepared_change_id.as_deref() {
            Some(id) => {
                let change = find_change(aggregate, id).map_err(|e| fail(e.0))?;
                (
                    Some(change.status.as_str()),
                    Some(self.token(work_id, id, true)?),
                )
            }
            None => (None, None),
        };
        preparation_view(
            prep,
            status,
            &self.token(work_id, &prep.preparation_id, false)?,
            token.as_deref(),
            &self.diagnostics(prep)?,
        )
        .map_err(fail)
    }
    pub(super) fn current_view(
        &self,
        aggregate: &WorkTemplateStateAggregate,
        work_id: &str,
    ) -> Result<Option<Value>, TemplateChangeError> {
        let Some(id) = aggregate.work.current_template_preparation_id.as_deref() else {
            return Ok(None);
        };
        let prep = find_preparation(aggregate, id).map_err(|e| fail(e.0))?;
        self.view(aggregate, work_id, prep).map(Some)
    }
}
