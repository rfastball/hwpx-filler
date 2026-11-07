//! Authoring session persistence, source opening, and file exports.

use super::*;

impl AuthoringController {
    pub(super) fn state(&self) -> Result<MutexGuard<'_, AuthoringState>, GraphError> {
        self.state
            .lock()
            .map_err(|_| fail("저작 작업대 상태를 읽을 수 없습니다."))
    }
    pub(super) fn contents(session: &AuthoringSession) -> Result<Value, GraphError> {
        let stem = if session.source_path.is_empty() {
            String::new()
        } else {
            Path::new(&session.source_path)
                .file_stem()
                .and_then(|part| part.to_str())
                .unwrap_or("")
                .to_owned()
        };
        let mut result = json!({"session_id":session.id,"revision":session.revision,
            "media":session.media,"source_stem":stem,"content":wire(&session.media,&session.content)?,
            "analysis":session.analysis});
        if session.media == "hwpx" {
            let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
            result["section_entries"] = json!(section_entries(&package)?);
        }
        Ok(result)
    }
    pub fn open_path(&self, path: &Path, as_template: bool) -> Result<Value, GraphError> {
        let source = fs::canonicalize(path)?;
        let media = media(&source)?;
        let source_text = crate::single_instance::normalize_windows_path(&source)?;
        let mut state = self.state()?;
        if let Some(existing) = state
            .sessions
            .iter()
            .find(|item| item.source_path == source_text)
        {
            let id = existing.id.clone();
            let result = Self::contents(existing)?;
            state.active_id = id;
            return Ok(result);
        }
        let session = self.opened_session(&source, source_text, media, as_template)?;
        let restore = self.workspace_restore(&source, &session)?;
        let id = session.id.clone();
        let result = Self::contents(&session)?;
        state.sessions.push(session);
        state.active_id = id;
        if let Some(restore) = restore {
            let id = state.active_id.clone();
            state.restores.insert(id, restore);
        }
        let mut result = result;
        result["notice"] = Value::Null;
        Ok(result)
    }

    fn opened_session(
        &self,
        source: &Path,
        source_text: String,
        media: &str,
        as_template: bool,
    ) -> Result<AuthoringSession, GraphError> {
        let (raw, baseline) = self.store.read_document(source)?;
        let (content, eol) = if media == "txt" {
            normalized_text(&raw)?
        } else {
            (raw, "\n".into())
        };
        let analysis = analyze(media, &content)?;
        let mut session = AuthoringSession::new(
            Uuid::new_v4().simple().to_string(),
            media.into(),
            content,
            analysis,
        );
        session.saved_content = session.content.clone();
        session.saved_analysis = session.analysis.clone();
        session.source_path = source_text;
        session.eol = eol;
        session.source_baseline = Some(baseline.clone());
        if as_template {
            session.save_path = session.source_path.clone();
            session.baseline = Some(baseline);
            self.read_template_cases(source, &mut session)?;
        }
        Ok(session)
    }

    fn read_template_cases(
        &self,
        source: &Path,
        session: &mut AuthoringSession,
    ) -> Result<(), GraphError> {
        let key = AuthoringStore::key(source)?;
        match self.store.read_cases(&key) {
            Ok(cases) => match validate_cases(&cases) {
                Ok(()) => session.cases = cases,
                Err(error) => {
                    session.cases_error = format!("시험 케이스를 읽을 수 없습니다: {error}")
                }
            },
            Err(error) => session.cases_error = format!("시험 케이스를 읽을 수 없습니다: {error}"),
        }
        Ok(())
    }

    fn workspace_restore(
        &self,
        source: &Path,
        session: &AuthoringSession,
    ) -> Result<Option<Value>, GraphError> {
        let key = AuthoringStore::key(source)?;
        Ok(self
            .read_workspace_restore(&key, session)
            .unwrap_or_else(|error| {
                Some(json!({"state":"unreadable","mode":null,"selection":null,
                "message":format!("최근 작업 위치를 읽을 수 없습니다: {error}")}))
            }))
    }

    fn read_workspace_restore(
        &self,
        key: &str,
        session: &AuthoringSession,
    ) -> Result<Option<Value>, GraphError> {
        let Some(record) = self.store.read_workspace(key)? else {
            return Ok(None);
        };
        let mode = record["mode"]
            .as_str()
            .ok_or("작업 위치 기록의 내용이 올바르지 않습니다.")?;
        if !matches!(mode, "document" | "template" | "structure") {
            return Err(fail("작업 위치 기록의 내용이 올바르지 않습니다."));
        }
        let selection = clean_selection(record.get("selection"))?;
        if record["fingerprint"] != digest(&session.content) {
            return Ok(Some(json!({"state":"stale","mode":mode,"selection":null,
                "message":"마지막 작업 이후 문서가 바뀌어 작업 위치를 복원하지 않았습니다."})));
        }
        if let Some(selected) = &selection
            && !selection_in(&session.media, &session.content, selected)?
        {
            return Err(fail("작업 위치 기록의 내용이 올바르지 않습니다."));
        }
        Ok(Some(
            json!({"state":"restored","mode":mode,"selection":selection,"message":null}),
        ))
    }
    pub fn save_to_path(
        &self,
        session_id: &str,
        revision: u64,
        path: &Path,
    ) -> Result<Value, GraphError> {
        let target = crate::single_instance::resolved_home(path);
        let mut state = self.state()?;
        let session = state
            .sessions
            .iter_mut()
            .find(|item| item.id == session_id)
            .ok_or("열려 있지 않은 문서 세션입니다.")?;
        if session.revision != revision {
            return Err(fail(
                "문서가 변경되었습니다. 최신 상태에서 다시 시도하세요.",
            ));
        }
        if media(&target)? != session.media {
            return Err(fail("저장할 파일 형식이 열린 문서와 다릅니다."));
        }
        let target_text = crate::single_instance::normalize_windows_path(&target)?;
        let same_path = !session.save_path.is_empty() && session.save_path == target_text;
        let new_baseline = match self.persist_document(&target, session, same_path)? {
            Ok(baseline) => baseline,
            Err(refusal) => return Ok(refusal),
        };
        let old_path = session.save_path.clone();
        session.save_path = target_text;
        session.baseline = Some(new_baseline);
        session.saved_content = session.content.clone();
        session.saved_analysis = session.analysis.clone();
        session.identifier_changes.clear();
        session.external_changed = false;
        if old_path != session.save_path && !session.cases.is_empty() {
            session.cases_dirty = true;
        }
        if let Some(sink) = &self.mutation_sink {
            sink("mutated", &target)?;
        }
        let errors = session.analysis["diagnostics"]
            .as_array()
            .map_or(0, |rows| {
                rows.iter().filter(|row| row["severity"] == "error").count()
            });
        let result = json!({"ok":true,"path":session.save_path,"revision":session.revision,
            "notice":if errors == 0 { None } else { Some(format!("초안은 저장되었습니다. 사용 전에 구조 오류 {errors}개를 확인하세요.")) }});
        self.publish_snapshot(state)?;
        Ok(result)
    }

    fn persist_document(
        &self,
        target: &Path,
        session: &mut AuthoringSession,
        same_path: bool,
    ) -> Result<Result<String, Value>, GraphError> {
        let expected = if same_path {
            session.baseline.as_deref()
        } else {
            None
        };
        match self
            .store
            .save_document(target, &on_disk(session, None)?, expected)
        {
            Ok(value) => Ok(Ok(value)),
            Err(AuthoringStoreError::ExternalChanged { fingerprint }) if same_path => {
                session.external_changed = true;
                Ok(Err(
                    json!({"external_changed":true,"fingerprint":fingerprint,
                    "message":"파일이 외부에서 변경되었습니다. 다시 확인하세요."}),
                ))
            }
            Err(AuthoringStoreError::ExternalChanged { .. }) => Ok(Err(json!({
                "conflict":"destination_exists",
                "message":"고른 위치에 파일이 이미 있습니다. 다른 이름을 고르세요."
            }))),
            Err(error) => Err(Box::new(error)),
        }
    }

    pub fn import_cases_path(&self, session_id: &str, path: &Path) -> Result<Value, GraphError> {
        let mut state = self.state()?;
        let session = state
            .sessions
            .iter_mut()
            .find(|item| item.id == session_id)
            .ok_or("열려 있지 않은 문서 세션입니다.")?;
        let cases = AuthoringStore::import_cases(path)?;
        validate_cases(&cases)?;
        session.cases = cases;
        session.cases_error.clear();
        session.cases_dirty = true;
        let key = schema_key(&session.analysis);
        let views: Vec<_> = session
            .cases
            .iter()
            .map(|case| {
                let mut view = case.clone();
                view["needs_review"] = json!(case.get("schema") != Some(&json!(key)));
                view
            })
            .collect();
        self.publish_snapshot(state)?;
        Ok(json!({"ok":true,"cases":views}))
    }

    pub fn export_cases_path(&self, session_id: &str, path: &Path) -> Result<Value, GraphError> {
        let state = self.state()?;
        let session = state
            .sessions
            .iter()
            .find(|item| item.id == session_id)
            .ok_or("열려 있지 않은 문서 세션입니다.")?;
        AuthoringStore::export_cases(path, &session.cases)?;
        Ok(json!({"ok":true,"path":path.to_string_lossy()}))
    }

    pub fn export_result_name(&self, session_id: &str) -> Result<String, GraphError> {
        let state = self.state()?;
        let session = state
            .sessions
            .iter()
            .find(|item| item.id == session_id)
            .ok_or("열려 있지 않은 문서 세션입니다.")?;
        let source = if session.save_path.is_empty() {
            &session.source_path
        } else {
            &session.save_path
        };
        let stem = if source.is_empty() {
            "새 템플릿"
        } else {
            Path::new(source)
                .file_stem()
                .and_then(|v| v.to_str())
                .unwrap_or("새 템플릿")
        };
        Ok(format!("{stem}_시험 결과.{}", session.media))
    }

    pub fn export_result_path(
        &self,
        session_id: &str,
        revision: u64,
        path: &Path,
    ) -> Result<Value, GraphError> {
        let state = self.state()?;
        let session = state
            .sessions
            .iter()
            .find(|item| item.id == session_id)
            .ok_or("열려 있지 않은 문서 세션입니다.")?;
        if session.revision != revision {
            return Err(fail("문서가 변경되었습니다. 다시 시험하세요."));
        }
        if session.trial_stale() || !session.trial_error.is_empty() {
            return Err(fail("최신 결과 시험을 먼저 완료하세요."));
        }
        let result = session
            .trial_result
            .as_ref()
            .ok_or("최신 결과 시험을 먼저 완료하세요.")?;
        if result["report"]["missing_fields"]
            .as_array()
            .is_some_and(|rows| !rows.is_empty())
            || result["report"]["errors"]
                .as_array()
                .is_some_and(|rows| !rows.is_empty())
        {
            return Err(fail("실패한 시험 결과는 내보낼 수 없습니다."));
        }
        if media(path)? != session.media {
            return Err(fail("결과 파일 형식이 문서와 다릅니다."));
        }
        let bytes = if session.media == "txt" {
            on_disk(
                session,
                Some(
                    result["text"]
                        .as_str()
                        .ok_or("시험 결과가 올바르지 않습니다.")?
                        .as_bytes(),
                ),
            )?
        } else {
            STANDARD.decode(
                result["content"]
                    .as_str()
                    .ok_or("시험 결과가 올바르지 않습니다.")?,
            )?
        };
        AuthoringStore::export_result(path, &bytes)?;
        Ok(json!({"ok":true,"path":path.to_string_lossy()}))
    }
}
