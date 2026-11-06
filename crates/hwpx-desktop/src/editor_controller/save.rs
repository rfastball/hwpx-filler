use super::*;

impl EditorController {
    fn overwrite_text(name: &str, victim: Option<&str>) -> String {
        match victim {
            None => format!(
                "작업 '{name}' 의 저장 위치에 기존 작업 파일이 있습니다(손상되어 어떤 작업인지 확인할 수 없습니다).\n계속하면 그 파일을 덮어씁니다."
            ),
            Some(other) if other != name => format!(
                "작업 이름 '{name}' 은(는) 기존 작업 '{other}' 과(와) 같은 파일로 저장됩니다.\n계속하면 작업 '{other}' 을(를) 덮어씁니다."
            ),
            Some(_) => {
                format!("작업 '{name}' 이(가) 이미 있습니다.\n계속하면 기존 작업을 덮어씁니다.")
            }
        }
    }
    pub(super) fn save(&self, payload: &Value) -> Result<Value, GraphError> {
        let state = self.state()?.clone();
        let verdict = validate_save(
            state.model.as_ref(),
            &state.job_name,
            &state.pattern,
            &state.data_path,
            state.schema.as_ref(),
            &state.template_path,
        );
        if !verdict.ok() {
            return Ok(
                json!({"ok":false,"block_reason":verdict.block_reason,"blocked_field":verdict.blocked_field}),
            );
        }
        let Some(gate) = self.generation_gate.as_ref() else {
            return Ok(
                json!({"ok":false,"block_reason":"문서 생성이 진행 중입니다. 끝난 뒤에 Mapping을 저장하세요."}),
            );
        };
        let name = state.job_name.clone();
        let mut saved_after = None;
        let mut land_error = None;
        let guarded=gate.with_editor_save_guard(||->Result<Value,GraphError>{
          if !Path::new(&state.template_path).is_file() {
            let file = Path::new(&state.template_path)
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("");
            return Ok(
                json!({"ok":false,"block_reason":format!("'{file}' 템플릿 파일이 없어 저장하지 않았습니다. 삭제를 되돌리거나 다른 템플릿을 선택하세요.")}),
            );
          }
        let media = template_media(&state.template_path);
        let data_name = self.data_name(&state, self.registered_data(&state)?.as_ref());
        let mut profile = verdict.profile.ok_or("validated profile missing")?;
        profile.provenance = build_provenance(
            &state.template_path,
            state.schema.as_ref(),
            &profile,
            &data_name,
            &state.loaded_provenance,
            (self.clock)(),
        );
        let outcome=self.jobs.transaction(|session|{
            let target_exists=self.jobs.path_for(&name).exists();
            let target=if target_exists{session.load(&name).ok()}else{None};
            if let Some(victim)=target.as_ref()&&victim.media()!=media {
                let label=hwpx_filler::home_state::work_mode_label(victim.media());
                return Ok(json!({"ok":false,"block_reason":format!("작업 이름 '{name}' 은(는) 이미 '{label}' 작업입니다. 형식이 다른 작업은 덮어쓸 수 없으니 다른 이름으로 저장하거나 기존 작업을 삭제한 뒤 다시 저장하세요.")}));
            }
            let self_update=!state.editing_origin.is_empty() && name==state.editing_origin;
            let drift=if self_update && target_exists {
                match target.as_ref(){
                    None=>format!("작업 '{}' 파일이 편집을 여는 사이 손상돼 현재 내용을 확인할 수 없습니다.\n지금 저장하면 그 자리를 이 편집 세션의 상태로 덮어씁니다.",state.editing_origin),
                    Some(current) if self.jobs.content_fingerprint(current).map_err(|error|StoreError::Invalid(error.to_string()))?!=state.editing_fingerprint=>
                        format!("편집 중 외부 변경: 작업 '{}' 이 이 편집 세션을 여는 사이 다른 곳에서 바뀌었습니다.\n지금 저장하면 그 변경 내용을 이 편집 세션의 상태로 덮어씁니다.",state.editing_origin),
                    _=>String::new(),
                }
            } else if target_exists {Self::overwrite_text(&name,target.as_ref().map(|job|job.name.as_str()))}
            else {String::new()};
            if !drift.is_empty() && (payload["confirm_overwrite"]!=true || payload["confirmed_overwrite_text"]!=drift){
                return Ok(json!({"ok":false,"needs_overwrite":true,"overwrite_text":drift}));
            }
            let origin=if state.editing_origin.is_empty(){None}else{session.load(&state.editing_origin).ok()};
            let preserved=if target_exists {
                target.as_ref().or(if self_update {state.base.as_ref()} else {None})
            } else {
                origin.as_ref().or(state.base.as_ref())
            };
            // Exhaustive fields make new durable metadata require an ownership decision here.
            let mut job=Job{
                name:name.clone(),template_path:state.template_path.clone(),mapping:profile,
                filename_pattern:state.pattern.clone(),data_path:state.data_path.clone(),data_sheet:state.data_sheet.clone(),
                data_header_row:state.data_header_row,data_kind:state.data_kind.clone(),
                last_run_at:if target_exists {preserved.map_or_else(String::new,|job|job.last_run_at.clone())}else{String::new()},
                favorited_at:if target.is_some(){preserved.map_or_else(String::new,|job|job.favorited_at.clone())}else{String::new()},
                tags:preserved.map_or_else(Map::new,|job|job.tags.clone()),group:preserved.map_or_else(String::new,|job|job.group.clone()),
                authority_id:if target.is_some(){preserved.map_or_else(String::new,|job|job.authority_id.clone())}else{String::new()},
                reviewed_rules:if target.is_some(){preserved.map_or_else(Map::new,|job|job.reviewed_rules.clone())}else{Map::new()},
                data_contract:preserved.and_then(|job|job.data_contract.clone()),
                version:2, template_revision:1, binding_revision:1, previous_rules:json!({})
            };
            if let Some(previous)=target.as_ref().filter(|previous|previous.template_path==job.template_path){
                let present=job.mapping.mappings.iter().map(|item|item.template_field.as_str()).collect::<std::collections::HashSet<_>>();
                let schema_fields=state.schema.as_ref().map(|schema|schema.field_names()).unwrap_or_default();
                let missing=previous.mapping.mappings.iter().filter(|item|schema_fields.contains(&item.template_field)&&!present.contains(item.template_field.as_str())).cloned().collect::<Vec<_>>();
                job.mapping.mappings.extend(missing);
            }
            mapping_rules(&job).map_err(|error|StoreError::Invalid(error.to_string()))?;
            session.save(&mut job,true)?;
            match session.load(&name) {
                Err(error) => land_error = Some(format!("저장한 작업을 다시 읽지 못했습니다: {error}")),
                Ok(saved) => {
                    if let Err(error) = self.restore_job(saved.clone()) {
                        land_error = Some(format!("저장한 작업을 화면에 다시 싣지 못했습니다: {error}"));
                    } else {
                        let mut landed = self.state().map_err(|error|StoreError::Invalid(error.to_string()))?;
                        landed.section = state.section.clone();
                        landed.context = state.context.clone();
                        landed.context["work"] = json!(name);
                        let failure = landed.reload_failure.clone();
                        if failure.is_empty() {
                            landed.set_notice(format!("작업 '{name}' 을(를) 저장했습니다."), "ok");
                        } else {
                            landed.set_notice(format!("작업 '{name}' 을(를) 저장했습니다.\n연결된 데이터를 다시 읽지 못했습니다: {failure}"),"warn");
                        }
                    }
                    saved_after = Some(saved);
                }
            }
            Ok(json!({"ok":true,"saved_name":name}))
        })?;
        Ok(outcome)
        })?;
        let Some(outcome) = guarded else {
            return Ok(
                json!({"ok":false,"block_reason":"문서 생성이 진행 중입니다. 끝난 뒤에 Mapping을 저장하세요."}),
            );
        };
        let mut outcome = outcome?;
        if outcome["ok"] == true {
            if let Some(detail) = land_error {
                self.post_save_warning(&mut outcome, &detail)?;
            }
            if let (Some(notify), Some(saved)) = (&self.saved_notification, saved_after.as_ref())
                && let Err(error) = notify(saved)
            {
                self.post_save_warning(
                    &mut outcome,
                    &format!("저장 알림을 갱신하지 못했습니다: {error}"),
                )?;
            }
            if let Some(after) = &self.after_mapping_saved
                && let Err(error) = after(&name)
            {
                self.post_save_warning(
                    &mut outcome,
                    &format!("실행 확인을 갱신하지 못했습니다: {error}"),
                )?;
            }
            if let Err(error) = self.refresh_binding_pending() {
                self.post_save_warning(
                    &mut outcome,
                    &format!("연결 상태를 갱신하지 못했습니다: {error}"),
                )?;
            }
        }
        Ok(outcome)
    }
    fn post_save_warning(&self, outcome: &mut Value, detail: &str) -> Result<(), GraphError> {
        let prior = outcome["warning"]
            .as_str()
            .unwrap_or("")
            .strip_prefix("작업은 저장됐지만 ")
            .unwrap_or(outcome["warning"].as_str().unwrap_or(""));
        let warning = format!(
            "작업은 저장됐지만 {}{detail}",
            if prior.is_empty() {
                String::new()
            } else {
                format!("{prior}; ")
            }
        );
        self.state()?.set_notice(&warning, "warn");
        outcome["warning"] = json!(warning);
        Ok(())
    }
}
