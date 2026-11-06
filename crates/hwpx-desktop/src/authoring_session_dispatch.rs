//! Session activation, source freshness, compatibility, and save commands.

use super::*;

impl AuthoringController {
    pub(super) fn dispatch_session(
        &self,
        state: &mut AuthoringState,
        action: &str,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        match action {
            "activate" | "content" | "update" => self.session_selection(state, action, payload),
            "rhwp_roundtrip_preflight" | "rhwp_unverified" | "check_external" | "remember_view" => {
                self.session_checks(state, action, payload)
            }
            "external_content" | "reload" | "close" | "save" => {
                self.session_lifecycle(state, action, payload)
            }
            _ => unreachable!(),
        }
    }
    fn session_selection(
        &self,
        state: &mut AuthoringState,
        action: &str,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        match action {
            "activate" => self.action_activate(state, payload),
            "content" => Self::contents(state.session(payload, false)?),
            "update" => self.action_update(state, payload),
            _ => unreachable!(),
        }
    }
    fn session_checks(
        &self,
        state: &mut AuthoringState,
        action: &str,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        match action {
            "rhwp_roundtrip_preflight" => self.action_rhwp_roundtrip_preflight(state, payload),
            "rhwp_unverified" => self.action_rhwp_unverified(state, payload),
            "check_external" => self.action_check_external(state, payload),
            "remember_view" => self.action_remember_view(state, payload),
            _ => unreachable!(),
        }
    }
    fn session_lifecycle(
        &self,
        state: &mut AuthoringState,
        action: &str,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        match action {
            "external_content" => self.action_external_content(state, payload),
            "reload" => self.action_reload(state, payload),
            "close" => self.action_close(state, payload),
            "save" => self.action_save(state, payload),
            _ => unreachable!(),
        }
    }
    fn action_activate(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session(payload, false)?;
        let id = session.id.clone();
        let mut result = Self::contents(session)?;
        result["restore"] = state.restores.get(&id).cloned().unwrap_or(Value::Null);
        state.active_id = id;
        Ok(result)
    }
    fn action_update(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        if session.media == "hwpx" && session.rhwp_editable != Some(true) {
            return Err(fail(
                "문서 보존 검증이 끝나지 않아 HWPX를 수정할 수 없습니다.",
            ));
        }
        let content = unwire(
            &session.media,
            payload.get("content").unwrap_or(&Value::Null),
        )?;
        let analysis = analyze(&session.media, &content)?;
        if session
            .last_preview
            .as_ref()
            .is_some_and(|preview| preview.0 == content)
        {
            session
                .identifier_changes
                .extend(session.last_preview.as_ref().unwrap().1.clone());
        }
        session.last_preview = None;
        session.replace_content(content, analysis.clone());
        session.trial_error.clear();
        Ok(json!({"session_id":session.id,"revision":session.revision,"analysis":analysis}))
    }
    fn action_rhwp_roundtrip_preflight(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        if session.media != "hwpx" {
            return Err(fail("HWPX 문서만 보존 검증을 합니다."));
        }
        let exported = unwire("hwpx", payload.get("content").unwrap_or(&Value::Null))?;
        let result = compare_rhwp_roundtrip(&session.content, &exported);
        session.rhwp_editable = result["editable"].as_bool();
        session.rhwp_diagnostics = result["diagnostics"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        session.cached_problems = None;
        Ok(result)
    }
    fn action_rhwp_unverified(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, false)?;
        if session.media != "hwpx" {
            return Err(fail("HWPX 문서만 보존 검증을 합니다."));
        }
        let detail = payload
            .get("detail")
            .and_then(Value::as_str)
            .ok_or("액션 입력이 올바르지 않습니다.")?;
        let revision = payload
            .get("revision")
            .and_then(Value::as_u64)
            .ok_or("액션 입력이 올바르지 않습니다.")?;
        if revision != session.revision {
            return Ok(json!({"applied":false}));
        }
        session.rhwp_editable = Some(false);
        session.rhwp_diagnostics = vec![json!({"kind":"preflight_unavailable",
                    "message":"HWPX 보존 검사를 실행할 수 없습니다.","detail":detail.chars().take(500).collect::<String>()})];
        session.cached_problems = None;
        Ok(json!({"applied":true}))
    }
    fn action_check_external(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, false)?;
        let path = if session.save_path.is_empty() {
            &session.source_path
        } else {
            &session.save_path
        };
        let expected = if session.save_path.is_empty() {
            &session.source_baseline
        } else {
            &session.baseline
        };
        let actual = if path.is_empty() {
            None
        } else {
            self.store.current_fingerprint(Path::new(path))?
        };
        session.external_changed = !path.is_empty() && actual != *expected;
        Ok(json!({"changed":session.external_changed,"fingerprint":actual}))
    }
    fn action_remember_view(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session(payload, false)?;
        let mode = payload
            .get("mode")
            .and_then(Value::as_str)
            .ok_or("payload 는 올바른 객체여야 한다")?;
        if !matches!(mode, "document" | "template" | "structure") {
            return Err(fail("payload 는 올바른 객체여야 한다"));
        }
        let selection = clean_selection(payload.get("selection"))?;
        let path = if session.save_path.is_empty() {
            &session.source_path
        } else {
            &session.save_path
        };
        if path.is_empty()
            || payload.get("revision").and_then(Value::as_u64) != Some(session.revision)
        {
            return Ok(json!({"stored":false}));
        }
        self.store.write_workspace(
            &AuthoringStore::key(Path::new(path))?,
            &digest(&session.content),
            mode,
            selection.as_ref(),
        )?;
        Ok(json!({"stored":true}))
    }
    fn action_external_content(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session(payload, false)?;
        let path = if session.save_path.is_empty() {
            &session.source_path
        } else {
            &session.save_path
        };
        if path.is_empty() {
            return Err(fail("원본 파일이 없습니다."));
        }
        let (raw, fingerprint) = self.store.read_document(Path::new(path))?;
        let content = if session.media == "txt" {
            normalized_text(&raw)?.0
        } else {
            raw
        };
        Ok(json!({"content":wire(&session.media,&content)?,"fingerprint":fingerprint}))
    }
    fn action_reload(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        let path = if session.save_path.is_empty() {
            &session.source_path
        } else {
            &session.save_path
        };
        if path.is_empty() {
            return Err(fail("다시 열 파일이 없습니다."));
        }
        if session.dirty() && payload.get("force") != Some(&Value::Bool(true)) {
            return Ok(json!({"needs_confirm":true,"document_dirty":true}));
        }
        let (raw, baseline) = self.store.read_document(Path::new(path))?;
        let (content, eol) = if session.media == "txt" {
            normalized_text(&raw)?
        } else {
            (raw, "\n".into())
        };
        let analysis = analyze(&session.media, &content)?;
        session.eol = eol;
        session.content = content.clone();
        session.saved_content = content;
        if session.save_path.is_empty() {
            session.source_baseline = Some(baseline)
        } else {
            session.baseline = Some(baseline)
        };
        session.analysis = analysis.clone();
        session.cached_problems = None;
        session.saved_analysis = analysis;
        session.identifier_changes.clear();
        session.last_preview = None;
        session.revision += 1;
        session.rhwp_editable = None;
        session.rhwp_diagnostics.clear();
        session.external_changed = false;
        let id = session.id.clone();
        let result = Self::contents(session)?;
        state.restores.remove(&id);
        Ok(result)
    }
    fn action_close(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session(payload, false)?;
        let dirty = session.dirty();
        let inputs_dirty = session.trial_inputs_dirty();
        let cases_dirty = session.cases_dirty || inputs_dirty;
        let id = session.id.clone();
        if (dirty || cases_dirty) && payload.get("force") != Some(&Value::Bool(true)) {
            return Ok(
                json!({"needs_confirm":true,"document_dirty":dirty,"dirty":dirty,
                        "cases_dirty":cases_dirty,"trial_inputs_dirty":inputs_dirty}),
            );
        }
        state.sessions.retain(|session| session.id != id);
        state.restores.remove(&id);
        if state.active_id == id {
            state.active_id = state
                .sessions
                .last()
                .map_or(String::new(), |item| item.id.clone());
        }
        Ok(json!({"ok":true}))
    }
    fn action_save(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        if session.save_path.is_empty() {
            return Ok(json!({"needs_path":true,"needs_save_as":true}));
        }
        let path = PathBuf::from(&session.save_path);
        let baseline = match self.store.save_document(
            &path,
            &on_disk(session, None)?,
            session.baseline.as_deref(),
        ) {
            Ok(value) => value,
            Err(AuthoringStoreError::ExternalChanged { fingerprint }) => {
                session.external_changed = true;
                return Ok(json!({"external_changed":true,"fingerprint":fingerprint,
                            "message":"파일이 외부에서 변경되었습니다. 다시 확인하세요."}));
            }
            Err(error) => return Err(Box::new(error)),
        };
        session.baseline = Some(baseline);
        session.saved_content = session.content.clone();
        session.saved_analysis = session.analysis.clone();
        session.identifier_changes.clear();
        session.external_changed = false;
        if let Some(sink) = &self.mutation_sink {
            sink("mutated", &path)?;
        }
        let errors = session.analysis["diagnostics"]
            .as_array()
            .map_or(0, |rows| {
                rows.iter().filter(|row| row["severity"] == "error").count()
            });
        Ok(
            json!({"ok":true,"path":session.save_path,"revision":session.revision,
                    "notice":if errors == 0 { None } else {Some(format!("초안은 저장되었습니다. 사용 전에 구조 오류 {errors}개를 확인하세요."))}}),
        )
    }
}
