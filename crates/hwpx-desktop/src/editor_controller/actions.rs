use super::*;

fn mapping_index(payload: &Value, required: bool, row_count: usize) -> Result<usize, GraphError> {
    let value = match payload.get("index") {
        Some(value) => value,
        None if required => return Err("index가 없습니다.".into()),
        None => return Ok(0),
    };
    let raw = match value {
        Value::Bool(value) => Some(i64::from(*value)),
        Value::Number(value) => value
            .as_i64()
            .or_else(|| value.as_u64().and_then(|number| i64::try_from(number).ok()))
            .or_else(|| {
                value
                    .as_f64()
                    .filter(|number| number.is_finite())
                    .and_then(|number| {
                        let truncated = number.trunc();
                        (truncated >= i64::MIN as f64 && truncated < i64::MAX as f64)
                            .then_some(truncated as i64)
                    })
            }),
        Value::String(value) => value.trim().parse::<i64>().ok(),
        _ => None,
    }
    .ok_or("index는 정수로 변환할 수 있어야 합니다.")?;
    if raw < 0 {
        return Ok(row_count
            .checked_sub(raw.unsigned_abs() as usize)
            .unwrap_or(usize::MAX));
    }
    usize::try_from(raw).map_err(|_| "매핑 행 범위가 올바르지 않습니다.".into())
}

impl EditorController {
    fn discard_patch(&self, section: &str) -> Result<(), GraphError> {
        let before = self.state()?.clone();
        let base = before
            .base
            .clone()
            .ok_or("아직 저장하지 않은 새 작업이라 되돌릴 이전 상태가 없습니다.")?;
        if !section.is_empty() && !SECTIONS.contains(&section) {
            return Err(format!("이 작업에는 '{section}' 탭이 없습니다.").into());
        }
        if section.is_empty() {
            return self.discard_whole_session(before, base);
        }
        if section == SECTION_FILENAME {
            self.state()?.pattern = base.filename_pattern;
        } else if section == SECTION_BINDING {
            Self::discard_binding(&mut *self.state()?, &base);
        } else {
            self.discard_template(before, base)?;
        }
        let label = section_label(section);
        self.state()?
            .set_notice(format!("「{label}」 에서 바꾼 것만 되돌렸습니다."), "ok");
        Ok(())
    }
    fn discard_whole_session(
        &self,
        before: EditorSessionState,
        base: Job,
    ) -> Result<(), GraphError> {
        let data_changed = (
            before.data_path.as_str(),
            before.data_sheet.as_str(),
            before.data_header_row,
            before.data_kind.as_str(),
        ) != base.data_binding();
        if !data_changed && !before.has_unsaved_work() {
            return Ok(());
        }
        self.restore_job(base.clone())?;
        let tail = if !data_changed {
            ""
        } else if base.has_data_binding() {
            "\n데이터도 이 작업에 연결된 것으로 되돌렸습니다."
        } else {
            "\n고른 데이터도 함께 내려놨습니다."
        };
        let mut state = self.state()?;
        state.section = before.section;
        state.context = before.context;
        state.set_notice(
            format!("바꾼 내용을 버리고 저장된 상태로 되돌렸습니다.{tail}"),
            "ok",
        );
        Ok(())
    }
    fn discard_binding(state: &mut EditorSessionState, base: &Job) {
        if let Some(schema) = state.schema.clone() {
            let vocabulary = if state.data_path.is_empty() {
                profile_source_vocabulary(&base.mapping)
            } else {
                state.source_fields.clone()
            };
            if state.data_path.is_empty() {
                state.source_fields = vocabulary.clone();
            }
            let mut model =
                EditorMappingModel::from_suggestions(&schema, &vocabulary, &HashMap::new());
            model.apply_profile(&base.mapping, false, true);
            state.model = Some(model);
            state.model_key = Some(state.model_key_now());
        }
    }
    fn discard_template(&self, before: EditorSessionState, base: Job) -> Result<(), GraphError> {
        self.restore_job(base)?;
        let mut state = self.state()?;
        state.data_path = before.data_path;
        state.data_sheet = before.data_sheet;
        state.data_header_row = before.data_header_row;
        state.data_kind = before.data_kind;
        state.data_pool_key = before.data_pool_key;
        state.source_fields = before.source_fields;
        state.records = before.records;
        state.entry_data = before.entry_data;
        state.job_name = before.job_name;
        state.context = before.context;
        state.section = before.section;
        state.model_key = None;
        Self::ensure_model(&mut state)
    }
    fn use_pool_data(&self, payload: &Value) -> Value {
        let key = payload["key"].as_str().unwrap_or("");
        let result = (|| -> Result<String, GraphError> {
            let item = self.datasets.load(key).map_err(|error| -> GraphError {
                match error {
                    PoolError::Io(ref io) if io.kind() == std::io::ErrorKind::NotFound => {
                        "등록 데이터를 찾을 수 없습니다(이미 삭제된 항목).".into()
                    }
                    PoolError::Codec(_) | PoolError::Invalid(_) => {
                        "등록 데이터를 찾을 수 없습니다(이미 삭제된 항목).".into()
                    }
                    _ => error.into(),
                }
            })?;
            if item.status != "active" {
                return Err("사용할 수 없는 등록 데이터입니다.".into());
            }
            let item = reference_for_sheet(&item, payload["sheet"].as_str())?;
            let mut source = source_from_pool_reference_live(&item)?;
            let records = source.records()?;
            if records.is_empty() {
                return Err("데이터에 행이 없습니다.".into());
            }
            let fields = source.fields()?;
            let (path, sheet, header_row, kind) = binding_for_reference(&item);
            if path.is_empty() {
                return Err(format!(
                    "'{}' 은(는) 파일 참조가 아니라 연결할 수 없습니다.",
                    item.name
                )
                .into());
            }
            let mut state = self.state()?;
            state.data_path = path;
            state.data_sheet = sheet;
            state.data_header_row = header_row;
            state.data_kind = kind;
            state.data_pool_key = key.into();
            state.source_fields = fields;
            state.records = records
                .into_iter()
                .map(|row| {
                    row.into_iter()
                        .map(|(key, value)| (key, Value::String(value)))
                        .collect()
                })
                .collect();
            state.preview_index = 0;
            if state.model.is_some() {
                Self::ensure_model(&mut state)?;
            }
            self.rederive_name(&mut state)?;
            Ok(item.name)
        })();
        match result {
            Ok(label) => json!({"ok":true,"label":label}),
            Err(error) => json!({"ok":false,"error":error.to_string()}),
        }
    }
    fn mapping_action(
        state: &mut EditorSessionState,
        action: &str,
        payload: &Value,
    ) -> Result<Value, GraphError> {
        if action == "step_preview" {
            if !state.records.is_empty() {
                let delta = payload["delta"]
                    .as_i64()
                    .ok_or("delta는 정수여야 합니다.")?;
                state.preview_index = (state.preview_index as i64 + delta)
                    .rem_euclid(state.records.len() as i64)
                    as usize;
            }
            return Ok(Value::Null);
        }
        match action {
            "set_name" => {
                state.job_name = payload["name"]
                    .as_str()
                    .ok_or("name은 문자열이어야 합니다.")?
                    .into();
                state.job_name_is_derived = false;
                return Ok(Value::Null);
            }
            "set_pattern" => {
                state.pattern = payload["pattern"]
                    .as_str()
                    .ok_or("pattern은 문자열이어야 합니다.")?
                    .into();
                return Ok(Value::Null);
            }
            _ => (),
        }
        if action == "mapping_reset_stakes" && state.model.is_none() {
            return Ok(json!({"human":0,"resuggest_manual":0,"confirmed":0}));
        }
        let model = state
            .model
            .as_mut()
            .ok_or("매핑 모델이 준비되지 않았습니다.")?;
        let index = mapping_index(payload, false, model.rows.len())?;
        if !["unconfirm_all", "restore_confirmed", "mapping_reset_stakes"].contains(&action) {
            state.unconfirm_undo.clear();
        }
        match action {
            "mapping_reset_stakes" => {
                let rejudge = payload["cause"] == "data" || !state.records.is_empty();
                let human = model.reset_stakes(
                    state
                        .base
                        .as_ref()
                        .and_then(|job| job.data_contract.as_ref()),
                    state.base.as_ref().map(|job| &job.mapping),
                    rejudge,
                );
                let resuggest_manual = model
                    .rows
                    .iter()
                    .filter(|row| !row.confirmed && row.touched)
                    .count();
                let confirmed = model.rows.iter().filter(|row| row.confirmed).count();
                Ok(json!({"human":human,"resuggest_manual":resuggest_manual,"confirmed":confirmed}))
            }
            "set_source" => {
                model.set_source(
                    index,
                    payload["source"]
                        .as_str()
                        .ok_or("source는 문자열이어야 합니다.")?,
                )?;
                Ok(Value::Null)
            }
            "revert_source" => {
                model
                    .rows
                    .get(index)
                    .ok_or("매핑 행 범위가 올바르지 않습니다.")?;
                model.revert_to_auto(index)?;
                model.resuggest_row(index, &state.source_fields)?;
                Ok(Value::Null)
            }
            "resuggest_all" => {
                let (resuggested, kept_confirmed) = model.resuggest_all()?;
                Ok(json!({"resuggested":resuggested,"kept_confirmed":kept_confirmed}))
            }
            "set_display" => {
                model.set_display(
                    index,
                    payload["type"]
                        .as_str()
                        .ok_or("type은 문자열이어야 합니다.")?,
                    payload["fmt"].as_str().unwrap_or(""),
                )?;
                Ok(Value::Null)
            }
            "set_slice" => {
                model.set_slice(index, payload.get("slice"))?;
                Ok(Value::Null)
            }
            "set_const" => {
                model.set_const(
                    index,
                    payload["const"]
                        .as_str()
                        .ok_or("const는 문자열이어야 합니다.")?,
                )?;
                Ok(Value::Null)
            }
            "set_confirmed" => {
                model.set_confirmed(
                    index,
                    payload["confirmed"]
                        .as_bool()
                        .ok_or("confirmed는 bool이어야 합니다.")?,
                )?;
                Ok(Value::Null)
            }
            "confirm_suggested" => Ok(json!({"promoted":model.confirm_suggested()})),
            "unconfirm_all" => {
                state.unconfirm_undo = model.unconfirm_all();
                Ok(json!({"undo_count":state.unconfirm_undo.len()}))
            }
            "restore_confirmed" => {
                let restored = model.restore_confirmed(&state.unconfirm_undo);
                state.unconfirm_undo.clear();
                Ok(json!({"restored":restored}))
            }
            _ => Err(format!("알 수 없는 editor 액션: {action:?}").into()),
        }
    }
    pub(super) fn dispatch_inner(
        &self,
        action: &str,
        payload: &Value,
    ) -> Result<Value, GraphError> {
        if let Some(result) = self.session_action(action, payload) {
            return result;
        }
        match action {
            "preview_slice" | "propose_slice" => self.query_slice(action, payload),
            "save" => self.save(payload),
            "use_pool_data" => Ok(self.use_pool_data(payload)),
            _ => {
                let mut state = self.state()?;
                Self::mapping_action(&mut state, action, payload)
            }
        }
    }
    /// Session lifecycle and section navigation; `None` leaves the action to the other handlers.
    fn session_action(&self, action: &str, payload: &Value) -> Option<Result<Value, GraphError>> {
        let done = match action {
            "new_session" => self.state().map(|mut state| state.reset()),
            "discard_session" => self.discard_session(),
            "dismiss_notice" => self.state().map(|mut state| state.set_notice("", "muted")),
            "use_library_template" => self.use_library_template(payload),
            "goto_section" => self.goto_section(payload),
            "ack_gate" => self.ack_gate(),
            "discard_patch" => self.discard_patch(payload["section"].as_str().unwrap_or("")),
            _ => return None,
        };
        Some(done.map(|()| Value::Null))
    }
    fn discard_session(&self) -> Result<(), GraphError> {
        let mut state = self.state()?;
        if !state.editing_origin.is_empty() {
            return Err("저장된 작업 편집은 신규 마법사 취소로 닫을 수 없습니다.".into());
        }
        state.reset();
        Ok(())
    }
    fn use_library_template(&self, payload: &Value) -> Result<(), GraphError> {
        let path = payload["path"]
            .as_str()
            .ok_or("path는 문자열이어야 합니다.")?;
        if !self.template_live(path)? {
            return Err(
                "라이브러리에 없는 템플릿입니다. 목록을 새로 고쳤으니 다시 고르세요.".into(),
            );
        }
        if self.state()?.template_path == path {
            return Ok(());
        }
        self.new_job_session(path)
    }
    fn goto_section(&self, payload: &Value) -> Result<(), GraphError> {
        let target = payload["section"]
            .as_str()
            .ok_or("section은 문자열이어야 합니다.")?;
        if !SECTIONS.contains(&target) {
            return Err(format!("이 작업에는 '{target}' 탭이 없습니다.").into());
        }
        self.discard_blocking_sections(target)?;
        let mut state = self.state()?;
        if state.editing_origin.is_empty() {
            ensure_can_advance(&state, target)?;
        }
        if target == SECTION_BINDING {
            Self::ensure_model(&mut state)?;
        }
        state.section = target.into();
        Ok(())
    }
    /// Discards each section patch that blocks `target`, failing when one will not let go.
    fn discard_blocking_sections(&self, target: &str) -> Result<(), GraphError> {
        let mut discarded = std::collections::HashSet::new();
        loop {
            let blocked = self.state()?.blocking_section(target);
            let Some(blocked) = blocked else {
                return Ok(());
            };
            if !discarded.insert(blocked.clone()) {
                return Err(format!(
                    "「{blocked}」 에서 바꾼 것을 되돌리지 못해 이동할 수 없습니다."
                )
                .into());
            }
            self.discard_patch(&blocked)?;
        }
    }
    fn ack_gate(&self) -> Result<(), GraphError> {
        let mut state = self.state()?;
        let gate = state.gate.as_mut().ok_or("확인할 항목이 없습니다.")?;
        gate.acknowledge(&gate.unmet_tokens.clone());
        Ok(())
    }
    fn query_slice(&self, action: &str, payload: &Value) -> Result<Value, GraphError> {
        let state = self.state()?;
        let model = state
            .model
            .as_ref()
            .ok_or("매핑 모델이 준비되지 않았습니다.")?;
        let index = mapping_index(payload, true, model.rows.len())?;
        let row = model
            .rows
            .get(index)
            .ok_or("매핑 행 범위가 올바르지 않습니다.")?;
        slice_query(
            if action == "preview_slice" {
                "preview"
            } else {
                "propose"
            },
            &row.template_field,
            &row.source,
            row.slice.as_ref(),
            row.slice_enabled(),
            &state.records,
            payload,
        )
        .map_err(|error| -> GraphError { error.into() })
    }
}

fn section_label(section: &str) -> &'static str {
    match section {
        SECTION_TEMPLATE => "고르기",
        SECTION_BINDING => "연결 확인",
        _ => "이름·저장",
    }
}

/// A new draft may only move forward past sections whose conditions are already met.
fn ensure_can_advance(state: &EditorSessionState, target: &str) -> Result<(), GraphError> {
    let here = SECTIONS
        .iter()
        .position(|section| *section == state.section)
        .unwrap_or(0);
    let there = SECTIONS
        .iter()
        .position(|section| *section == target)
        .unwrap();
    for section in SECTIONS.get(here..there).unwrap_or(&[]) {
        if !editor_projection::can_advance(state, section) {
            let label = section_label(section);
            return Err(
                format!("「{label}」 조건을 아직 채우지 못해 다음으로 갈 수 없습니다.").into(),
            );
        }
    }
    Ok(())
}
