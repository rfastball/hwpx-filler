//! Opening a saved work or a handed-off data source into the editor session.

use super::*;

impl EditorController {
    pub(super) fn read_source_ref(source_ref: &Value) -> Result<LoadedEditorData, GraphError> {
        let path = source_ref["path"].as_str().unwrap_or("");
        let sheet = source_ref["sheet"].as_str().unwrap_or("");
        let kind = source_ref["kind"].as_str().unwrap_or("");
        let header_row = if kind.is_empty() {
            source_ref["header_row"].as_u64().unwrap_or(0)
        } else {
            0
        };
        let mut source = source_for_binding(path, sheet, usize::try_from(header_row).ok(), kind)?;
        let records = source.records()?;
        if records.is_empty() {
            return Err("데이터에 행이 없습니다.".into());
        }
        let fields = source.fields()?;
        Ok(LoadedEditorData {
            path: path.into(),
            sheet: sheet.into(),
            kind: kind.into(),
            header_row,
            fields,
            records: records
                .into_iter()
                .map(|row| {
                    row.into_iter()
                        .map(|(key, value)| (key, Value::String(value)))
                        .collect()
                })
                .collect(),
        })
    }
    pub(super) fn adopt_source(state: &mut EditorSessionState, data: LoadedEditorData) {
        state.data_path = data.path;
        state.data_sheet = data.sheet;
        state.data_header_row = data.header_row;
        state.data_kind = data.kind;
        state.data_pool_key.clear();
        state.source_fields = data.fields;
        state.records = data.records;
        state.preview_index = 0;
    }
    pub fn load_job(&self, name: &str) -> Result<(), GraphError> {
        self.load_job_with_context(name, &json!({}), None)
    }
    pub fn load_job_with_context(
        &self,
        name: &str,
        context: &Value,
        source_ref: Option<&Value>,
    ) -> Result<(), GraphError> {
        let job = self.jobs.load(name)?;
        let landing_requested = context["landing_section"]
            .as_str()
            .unwrap_or(SECTION_BINDING)
            .to_owned();
        let context =
            editor_context(&job.name, context).map_err(|error| -> GraphError { error.into() })?;
        let target = context["target"].as_str().unwrap_or("");
        let landing = if target.is_empty() {
            landing_requested
        } else {
            target
                .split('/')
                .next()
                .unwrap_or(SECTION_BINDING)
                .to_owned()
        };
        self.restore_job_with_source(job, source_ref)?;
        {
            let mut state = self.state()?;
            state.context = context;
            state.section = if SECTIONS.contains(&landing.as_str()) {
                landing.as_str()
            } else {
                SECTION_BINDING
            }
            .into();
        }
        self.refresh_binding_pending()?;
        self.push_snapshot()
    }
    pub(super) fn refresh_binding_pending(&self) -> Result<(), GraphError> {
        let name = {
            let state = self.state()?;
            if state.editing_origin.is_empty() || state.job_name.is_empty() {
                None
            } else {
                Some(state.job_name.clone())
            }
        };
        let pending = name
            .as_deref()
            .and_then(|name| {
                self.binding_pending
                    .as_ref()
                    .and_then(|probe| probe(name).ok())
            })
            .unwrap_or(false);
        self.state()?.binding_confirm_pending = pending;
        Ok(())
    }
    pub(super) fn restore_job(&self, job: Job) -> Result<(), GraphError> {
        self.restore_job_with_source(job, None)
    }
    pub(super) fn restore_job_with_source(
        &self,
        job: Job,
        source_ref: Option<&Value>,
    ) -> Result<(), GraphError> {
        if !Path::new(&job.template_path).exists() {
            return Err(format!("템플릿 파일을 찾을 수 없습니다: {}\n파일을 되돌리거나, 홈/작업 화면의 [템플릿 다시 연결…]로 경로를 바꾸세요.",job.template_path).into());
        }
        let mut state = EditorSessionState::default();
        self.load_template_into(&mut state, &job.template_path)?;
        if state.schema.is_none() {
            return Err(if state.raw_block.is_empty() {
                "템플릿이 로드되지 않았습니다.".into()
            } else {
                state.raw_block.clone()
            }
            .into());
        }
        if state.gate_error {
            return Err("템플릿 상태를 확인할 수 없어 편집을 열 수 없습니다.".into());
        }
        let handoff_failure = Self::restore_session_data(&mut state, &job, source_ref);
        if state.data_path.is_empty() {
            state.source_fields = profile_source_vocabulary(&job.mapping);
        }
        let mut model = EditorMappingModel::from_suggestions(
            state.schema.as_ref().unwrap(),
            &state.source_fields,
            &HashMap::new(),
        );
        model.apply_profile(&job.mapping, !state.data_path.is_empty(), true);
        state.model = Some(model);
        state.model_key = Some(state.model_key_now());
        state.job_name = job.name.clone();
        state.job_name_is_derived = false;
        state.pattern = job.filename_pattern.clone();
        state.editing_origin = job.name.clone();
        state.editing_fingerprint = self.jobs.content_fingerprint(&job)?;
        state.loaded_provenance = job.mapping.provenance.clone();
        state.context["work"] = json!(job.name);
        state.entry_data = (state.data_path.clone(), state.data_sheet.clone());
        state.section = SECTION_BINDING.into();
        let lines = restore_report_lines(&job, state.model.as_ref().unwrap(), &handoff_failure);
        state.set_notice(
            lines.join("\n"),
            if lines.is_empty() { "ok" } else { "warn" },
        );
        state.base = Some(job);
        state.reload_failure = handoff_failure;
        *self.state()? = state;
        Ok(())
    }
    /// Seats the handed-off source, else the work's own binding; returns the reload failure.
    fn restore_session_data(
        state: &mut EditorSessionState,
        job: &Job,
        source_ref: Option<&Value>,
    ) -> String {
        if let Some(reference) = source_ref
            .filter(|reference| reference.as_object().is_some_and(|items| !items.is_empty()))
        {
            return match Self::read_source_ref(reference) {
                Ok(data) => {
                    Self::adopt_source(state, data);
                    String::new()
                }
                Err(error) => error.to_string(),
            };
        }
        if job.data_path.is_empty() {
            return String::new();
        }
        match source_for_binding(
            &job.data_path,
            &job.data_sheet,
            usize::try_from(job.data_header_row).ok(),
            &job.data_kind,
        )
        .and_then(|mut source| {
            let records = source.records()?;
            let fields = source.fields()?;
            Ok((fields, records))
        }) {
            Ok((fields, records)) if !records.is_empty() => {
                state.data_path = job.data_path.clone();
                state.data_sheet = job.data_sheet.clone();
                state.data_header_row = job.data_header_row;
                state.data_kind = job.data_kind.clone();
                state.source_fields = fields;
                state.records = records
                    .into_iter()
                    .map(|row| {
                        row.into_iter()
                            .map(|(key, value)| (key, Value::String(value)))
                            .collect()
                    })
                    .collect();
                String::new()
            }
            Ok(_) => "데이터에 행이 없습니다.".into(),
            Err(error) => error.to_string(),
        }
    }
}
