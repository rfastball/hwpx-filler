//! Preview, semantic capture, and paste commands.

use super::*;

impl AuthoringController {
    pub(super) fn dispatch_edit(
        &self,
        state: &mut AuthoringState,
        action: &str,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        match action {
            "preview" => self.action_preview(state, payload),
            "copy" => self.action_copy(state, payload),
            "preview_paste" => self.action_preview_paste(state, payload),
            _ => unreachable!(),
        }
    }
    fn action_preview(
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
        let command = payload
            .get("command")
            .filter(|value| value.is_object())
            .ok_or("명령이 올바르지 않습니다.")?;
        let (content, mut preview) = if session.media == "txt" {
            let text = std::str::from_utf8(&session.content)?;
            if command["type"] == "create_fields" {
                Self::apply_txt_proposal_fields(text, command)?
            } else {
                let (changed, preview) = txt_authoring::apply(text, command)?;
                (changed.into_bytes(), preview)
            }
        } else {
            let mut package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
            let preview = match apply_hwpx(&mut package, command) {
                Ok(preview) => preview,
                Err(error) if error.to_dict().is_some() => {
                    return Ok(json!({"ok":false,
                            "refusal":error.to_dict(),"session_id":session.id,"revision":session.revision}));
                }
                Err(error) => return Err(Box::new(error)),
            };
            (package.to_bytes()?, preview)
        };
        let impact = self.preview_impact(session, &preview, command)?;
        let renamed = impact["structure_delta"]["renamed"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        session.last_preview = Some((content.clone(), renamed));
        if command["type"] == "rename_field" {
            let affected = preview["affected"].as_u64().unwrap_or_else(|| {
                preview["edits"]
                    .as_array()
                    .map_or(0, |items| items.len() as u64)
            });
            let name = command["name"]
                .as_str()
                .map(hwpx_filler::structure_scan::python_trim)
                .unwrap_or("");
            preview["message"] = json!(rename_field_message(affected as usize, name));
        }
        let confirm = txt_authoring::confirm_tier(command, &preview, Some(&impact));
        let created = txt_authoring::created_target(command, &preview["result"]);
        let renamed_target = txt_authoring::renamed_target(command, &preview["result"]);
        if let Some(map) = preview.as_object_mut() {
            map.extend(impact.as_object().expect("impact object").clone());
        }
        preview["session_id"] = json!(session.id);
        preview["revision"] = json!(session.revision);
        preview["content"] = json!(wire(&session.media, &content)?);
        preview["confirm"] = json!(confirm);
        preview["created"] = json!(created);
        preview["renamed"] = json!(renamed_target);
        Ok(preview)
    }
    fn action_copy(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session(payload, true)?;
        let selector = payload
            .get("selector")
            .filter(|value| value.is_object())
            .ok_or("복사할 의미 요소를 고르세요.")?;
        let captured = if session.media == "txt" {
            capture_document(
                "txt",
                TransferSource::Txt(std::str::from_utf8(&session.content)?),
                selector,
            )?
        } else {
            let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
            capture_document("hwpx", TransferSource::Hwpx(&package), selector)?
        };
        let kind = match &captured {
            CapturedMeaning::Txt(value) | CapturedMeaning::Foreign(value) => {
                value["kind"].as_str().unwrap_or("").to_owned()
            }
            CapturedMeaning::Hwpx(value) => value.kind.clone(),
        };
        let media = session.media.clone();
        let token = Uuid::new_v4().simple().to_string();
        state.clipboard = Some((token.clone(), captured));
        Ok(json!({"clipboard_token":token,"kind":kind,"media":media}))
    }
    fn action_preview_paste(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session(payload, true)?;
        if session.media == "hwpx" && session.rhwp_editable != Some(true) {
            return Err(fail("이 문서는 현재 붙여넣을 수 없습니다."));
        }
        let (token, captured) = state
            .clipboard
            .as_ref()
            .ok_or("복사한 내용이 변경되었습니다. 다시 복사하세요.")?;
        if payload.get("clipboard_token").and_then(Value::as_str) != Some(token.as_str()) {
            return Err(fail("복사한 내용이 변경되었습니다. 다시 복사하세요."));
        }
        let destination = payload
            .get("destination")
            .filter(|value| value.is_object())
            .ok_or("붙여넣을 위치와 방식을 확인하세요.")?;
        let with_meaning = payload
            .get("with_meaning")
            .and_then(Value::as_bool)
            .ok_or("붙여넣을 위치와 방식을 확인하세요.")?;
        let captured_media = match captured {
            CapturedMeaning::Txt(value) | CapturedMeaning::Foreign(value) => {
                value["media"].as_str()
            }
            CapturedMeaning::Hwpx(value) => Some(value.media.as_str()),
        };
        if captured_media != Some(session.media.as_str()) {
            return Err(fail("다른 문서 형식으로 의미 요소를 붙여넣을 수 없습니다."));
        }
        let (content, mut preview) =
            Self::paste_captured(session, captured, destination, with_meaning)?;
        let additional = self.preview_impact(session, &preview, &json!({"type":"paste"}))?;
        if let Some(map) = preview.as_object_mut() {
            map.extend(additional.as_object().expect("impact object").clone());
        }
        preview["session_id"] = json!(session.id);
        preview["revision"] = json!(session.revision);
        preview["content"] = json!(wire(&session.media, &content)?);
        preview["clipboard_token"] = json!(token);
        Ok(preview)
    }

    fn paste_captured(
        session: &AuthoringSession,
        captured: &CapturedMeaning,
        destination: &Value,
        with_meaning: bool,
    ) -> Result<(Vec<u8>, Value), GraphError> {
        if session.media == "txt" {
            let outcome = paste_document(
                "txt",
                TransferTarget::Txt(std::str::from_utf8(&session.content)?),
                captured,
                destination,
                with_meaning,
            )?;
            let PasteOutcome::Txt { text, impact } = outcome else {
                return Err(fail("지원하지 않는 붙여넣기 형식입니다."));
            };
            Ok((text.into_bytes(), impact))
        } else {
            let mut package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
            let outcome = paste_document(
                "hwpx",
                TransferTarget::Hwpx(&mut package),
                captured,
                destination,
                with_meaning,
            )?;
            let PasteOutcome::Hwpx { impact } = outcome else {
                return Err(fail("지원하지 않는 붙여넣기 형식입니다."));
            };
            Ok((package.to_bytes()?, impact))
        }
    }
}
