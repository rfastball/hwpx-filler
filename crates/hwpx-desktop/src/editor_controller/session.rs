//! Template and data changes inside the live editor session.

use super::*;

impl EditorController {
    pub fn new_draft_with_data(
        &self,
        source_ref: &Value,
        context: &Value,
    ) -> Result<(), GraphError> {
        let context =
            editor_context("", context).map_err(|error| -> GraphError { error.into() })?;
        let data = Self::read_source_ref(source_ref)?;
        let mut state = self.state()?;
        state.reset();
        state.context = context;
        Self::adopt_source(&mut state, data);
        state.entry_data = (state.data_path.clone(), state.data_sheet.clone());
        self.rederive_name(&mut state)?;
        drop(state);
        self.push_snapshot()
    }
    pub fn adopt_imported_template(&self, dest: &Path) -> Result<String, GraphError> {
        let name = dest
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("")
            .to_owned();
        let media = template_media(&dest.to_string_lossy());
        if media == "hwpx" {
            match read_template_intake(dest) {
                Err(_) => {
                    self.state()?.set_notice(format!("'{name}' 을 가져왔지만 읽을 수 없습니다. 목록의 행 ⋮ → '자세히…'에서 사유를 보거나 '폴더에서 보기'로 파일을 확인하세요."), "warn");
                    self.push_snapshot()?;
                    return Ok(name);
                }
                Ok(intake) if intake.schema.is_none() => {
                    self.state()?.set_notice(format!("'{name}' 은 누름틀이 없는 원본(RAW)입니다. 목록의 행 ⋮ → '누름틀·구간 변환'을 거친 뒤 시작하세요."), "warn");
                    self.push_snapshot()?;
                    return Ok(name);
                }
                _ => (),
            }
        } else if read_template(dest)
            .ok()
            .and_then(|bytes| String::from_utf8(bytes).ok())
            .is_none()
        {
            self.state()?.set_notice(format!("'{name}' 을 가져왔지만 읽을 수 없습니다(UTF-8 아님). 목록의 행 ⋮ → '자세히…'에서 사유를 보거나 '폴더에서 보기'로 파일을 확인하세요."), "warn");
            self.push_snapshot()?;
            return Ok(name);
        }
        self.new_job_session(&dest.to_string_lossy())?;
        self.state()?
            .set_notice(format!("'{name}' 을 라이브러리로 복사해 시작합니다."), "ok");
        self.push_snapshot()?;
        Ok(name)
    }
    pub fn reconcile_template_mutation(&self, kind: &str, path: &Path) -> Result<(), GraphError> {
        if !["mutated", "deleted"].contains(&kind) {
            return Err(format!(
                "알 수 없는 템플릿 변이 종류: {}",
                hwpx_filler::text_render::python_repr(&json!(kind))
            )
            .into());
        }
        let active = self.state()?.template_path.clone();
        if active.is_empty() {
            return Ok(());
        }
        let identity = |path: &Path| {
            std::fs::canonicalize(path)
                .or_else(|_| std::path::absolute(path))
                .unwrap_or_else(|_| path.to_path_buf())
                .to_string_lossy()
                .replace('/', "\\")
                .to_lowercase()
        };
        if identity(Path::new(&active)) != identity(path) {
            return Ok(());
        }
        if kind == "deleted" {
            self.state()?.set_notice(
                "편집 중인 템플릿이 삭제됐습니다. 되돌리거나 다른 템플릿을 선택하세요.",
                "danger",
            );
            return self.push_snapshot();
        }
        let mut state = self.state()?;
        self.load_template_into(&mut state, &active)?;
        if state.schema.is_none() {
            state.model = None;
            state.model_key = None;
            state.unconfirm_undo.clear();
            state.set_notice("편집 중인 템플릿 파일이 바뀌어 채울 항목이 없어졌습니다. 되돌리거나 다른 템플릿을 선택하세요.", "danger");
        } else {
            let mut message = "편집 중인 템플릿 파일이 바뀌어 세션을 다시 읽었습니다.".to_owned();
            if state.model.is_some() {
                let before = state.notice_text.clone();
                state.model_key = None;
                Self::ensure_model(&mut state)?;
                if state.notice_text != before {
                    message.push('\n');
                    message.push_str(&state.notice_text);
                }
            }
            state.set_notice(message, "warn");
        }
        drop(state);
        self.push_snapshot()
    }
    pub(super) fn load_template_into(
        &self,
        state: &mut EditorSessionState,
        path: &str,
    ) -> Result<(), GraphError> {
        state.template_path = path.into();
        state.schema = None;
        state.gate = None;
        state.gate_error = false;
        state.raw_block.clear();
        self.rederive_name(state)?;
        let intake = read_template_intake(Path::new(path))
            .map_err(|error| -> GraphError { error.into() })?;
        state.schema = intake.schema;
        state.gate = intake.gate;
        state.gate_error = intake.gate_error;
        state.raw_block = intake.raw_block;
        Ok(())
    }
    pub(super) fn new_job_session(&self, path: &str) -> Result<(), GraphError> {
        let mut state = self.state()?;
        let previous = std::mem::take(&mut *state);
        let anchored = [
            "document_browser_new_work",
            "document_browser_repair",
            "workbench_result",
        ]
        .contains(&previous.context["entry_reason"].as_str().unwrap_or(""))
            && !previous.data_path.is_empty();
        if anchored {
            state.data_path = previous.data_path;
            state.data_sheet = previous.data_sheet;
            state.data_header_row = previous.data_header_row;
            state.data_kind = previous.data_kind;
            state.data_pool_key = previous.data_pool_key;
            state.source_fields = previous.source_fields;
            state.records = previous.records;
            state.entry_data = previous.entry_data;
            state.context = previous.context;
        }
        self.load_template_into(&mut state, path)
    }
    pub(super) fn rederive_name(&self, state: &mut EditorSessionState) -> Result<(), GraphError> {
        if state.job_name_is_derived {
            let left = Path::new(&state.template_path)
                .file_stem()
                .and_then(|name| name.to_str())
                .unwrap_or("");
            let right = self.data_name(state, self.registered_data(state)?.as_ref());
            state.job_name = derive_job_name(left, &right);
            state.derived_name_baseline = state.job_name.clone();
        }
        Ok(())
    }
    pub(super) fn ensure_model(state: &mut EditorSessionState) -> Result<(), GraphError> {
        let schema = state
            .schema
            .as_ref()
            .ok_or("템플릿이 로드되지 않았습니다.")?;
        let key = state.model_key_now();
        if state.model.is_some() && state.model_key.as_ref() == Some(&key) {
            return Ok(());
        }
        let prior = state
            .model
            .as_ref()
            .and_then(|model| model.carry_profile("").ok())
            .filter(|profile| !profile.mappings.is_empty());
        let manual = state
            .model
            .as_ref()
            .map(|model| {
                model
                    .rows
                    .iter()
                    .filter(|row| row.manual_unconfirmed)
                    .map(|row| row.template_field.clone())
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let lost_auto = state.model.as_ref().is_some_and(|model| {
            model
                .rows
                .iter()
                .any(|row| row.auto_confirmed_exact && !state.source_fields.contains(&row.source))
        });
        let mut model =
            EditorMappingModel::from_suggestions(schema, &state.source_fields, &HashMap::new());
        let carried = prior
            .as_ref()
            .map_or(0, |profile| model.apply_profile(profile, false, false));
        for (index, row) in model.rows.clone().iter().enumerate() {
            if manual.contains(&row.template_field) {
                model.set_confirmed(index, false)?;
            }
        }
        let auto = if let (Some(_), Some(base), Some(contract)) = (
            prior.as_ref(),
            state.base.as_ref(),
            state
                .base
                .as_ref()
                .and_then(|job| job.data_contract.as_ref()),
        ) {
            Some(model.apply_data_contract(contract, &base.mapping, &state.records))
        } else {
            None
        };
        if prior.is_some() || lost_auto {
            let (message, level) = carry_notice(auto, carried, &model);
            state.set_notice(message, level);
        }
        state.model = Some(model);
        state.model_key = Some(key);
        state.unconfirm_undo.clear();
        Ok(())
    }
    pub fn load_data_path(
        &self,
        path: &Path,
        sheet: Option<&str>,
        header_row: usize,
    ) -> Result<(), GraphError> {
        let mut source = source_for_path(path, sheet, header_row.max(1))?;
        let records = source.records()?;
        if records.is_empty() {
            return Err("데이터에 행이 없습니다.".into());
        }
        let fields = source.fields()?;
        let mut state = self.state()?;
        state.data_path = path.to_string_lossy().into();
        state.data_sheet = sheet.unwrap_or("").into();
        state.data_header_row = header_row as u64;
        state.data_kind.clear();
        state.data_pool_key.clear();
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
        drop(state);
        self.push_snapshot()
    }
}

/// Notice for a rebuilt mapping draft: carried rows, and package-condition auto confirmation.
fn carry_notice(
    auto: Option<usize>,
    carried: usize,
    model: &EditorMappingModel,
) -> (String, &'static str) {
    match auto {
        None => (
            format!(
                "템플릿/데이터가 바뀌어 매핑 초안을 다시 만들었습니다. 직접 확인하거나 편집한 {carried}개 행의 소스·유형·서식은 이월했습니다. 확인이 필요한 행을 다시 확정하세요."
            ),
            "warn",
        ),
        Some(count) if model.is_complete() => (
            format!(
                "템플릿/데이터가 바뀌어 매핑 초안을 다시 만들었습니다. 이월한 {carried}개 행 중 {count}개 행은 꾸러미 조건과 일치해 자동확정했습니다."
            ),
            "ok",
        ),
        Some(count) => (
            format!(
                "템플릿/데이터가 바뀌어 매핑 초안을 다시 만들었습니다. 이월한 {carried}개 행 중 {count}개 행은 꾸러미 조건과 일치해 자동확정했습니다. 확인이 필요한 행을 다시 확정하세요."
            ),
            "warn",
        ),
    }
}
