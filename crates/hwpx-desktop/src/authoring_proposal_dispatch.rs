//! Proposed field candidates and their preview commands.

use super::*;

impl AuthoringController {
    pub(super) fn proposal_view(
        &self,
        session: &mut AuthoringSession,
    ) -> Result<Option<Value>, GraphError> {
        let Some(state) = session.proposal.as_mut() else {
            return Ok(None);
        };
        if let Some((revision, cached)) = &session.proposal_cache
            && *revision == session.revision
        {
            return Ok(Some(cached.clone()));
        }
        let datasets = self
            .proposal_data
            .as_ref()
            .map_or(Ok(Vec::new()), ProposalData::datasets)
            .map_err(fail)?;
        let value = if state.loaded.is_none() {
            empty_view("needs_data", session.revision, &datasets, "", None)
        } else if state
            .loaded
            .as_ref()
            .is_some_and(|loaded| !loaded.error.is_empty() || loaded.rows.is_empty())
        {
            let error = state
                .loaded
                .as_ref()
                .map_or("", |loaded| loaded.error.as_str());
            empty_view("failed", session.revision, &datasets, error, Some(state))
        } else if session.media == "txt" {
            let source = std::str::from_utf8(&session.content)?;
            let (paragraphs, places) = read_txt(source);
            let existing = session.analysis["fields"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|item| item["name"].as_str().map(str::to_owned))
                .collect::<Vec<_>>();
            proposal_view(
                state,
                session.revision,
                &paragraphs,
                &|index, start, end| spot_location("txt", source, &places[index], start, end),
                &existing,
                &datasets,
            )
        } else {
            let package = HwpxPackage::from_bytes(&session.content, PackageLimits::default())?;
            let (paragraphs, places) =
                read_hwpx(&package).map_err(|error| fail(error.to_string()))?;
            let existing = session.analysis["fields"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|item| item["name"].as_str().map(str::to_owned))
                .collect::<Vec<_>>();
            proposal_view(
                state,
                session.revision,
                &paragraphs,
                &|index, start, end| spot_location("hwpx", "", &places[index], start, end),
                &existing,
                &datasets,
            )
        };
        session.proposal_cache = Some((session.revision, value.clone()));
        Ok(Some(value))
    }
    pub(super) fn proposal_group(
        &self,
        session: &mut AuthoringSession,
        group_id: Option<&Value>,
    ) -> Result<Value, GraphError> {
        self.proposal_view(session)?
            .and_then(|view| {
                view["groups"].as_array().and_then(|groups| {
                    groups
                        .iter()
                        .find(|group| group.get("id") == group_id)
                        .cloned()
                })
            })
            .ok_or_else(|| fail("제안을 찾을 수 없습니다. 제안 목록에서 다시 고르세요."))
    }
    pub(super) fn proposal_preview(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
        command: Value,
        groups: Vec<Value>,
        toast: String,
    ) -> Result<Value, GraphError> {
        let session = state.session(payload, true)?;
        let request =
            json!({"session_id":session.id,"revision":session.revision,"command":command});
        let mut result = self.dispatch_inner(
            state,
            "preview",
            request.as_object().expect("preview object"),
        )?;
        if result.get("ok") == Some(&json!(false)) {
            return Ok(result);
        }
        let session = state.session_mut(payload, true)?;
        let (bindings, values) = drafts(&groups);
        let bytes = &session
            .last_preview
            .as_ref()
            .ok_or("성공한 미리보기에 결과 문서가 없습니다.")?
            .0;
        session.proposal_pending = Some((digest(bytes), bindings, values));
        result["command"] = command;
        result["toast"] = json!(toast);
        Ok(result)
    }
    pub(super) fn apply_txt_proposal_fields(
        text: &str,
        command: &Value,
    ) -> Result<(Vec<u8>, Value), GraphError> {
        let fields = command["fields"]
            .as_array()
            .filter(|fields| !fields.is_empty())
            .ok_or("고른 위치가 올바르지 않습니다.")?;
        let mut sites = Vec::new();
        for field in fields {
            let ranges = field["ranges"]
                .as_array()
                .filter(|ranges| !ranges.is_empty())
                .ok_or("고른 위치가 올바르지 않습니다.")?;
            for range in ranges {
                let mut site = range
                    .as_object()
                    .cloned()
                    .ok_or("고른 위치가 올바르지 않습니다.")?;
                site.insert("type".into(), json!("create_field"));
                site.insert("name".into(), field["name"].clone());
                sites.push(Value::Object(site));
            }
        }
        let existing: HashSet<_> = txt_authoring::analyze(text)["fields"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|item| item["name"].as_str().map(str::to_owned))
            .collect();
        sites.sort_by_key(|site| std::cmp::Reverse(site["start"].as_i64().unwrap_or(0)));
        let mut changed = text.to_owned();
        for site in &sites {
            changed = txt_authoring::apply(&changed, site)?.0
        }
        let links = fields.iter().any(|field| {
            field["name"]
                .as_str()
                .is_some_and(|name| existing.contains(name))
        });
        let impact = json!({"affected":sites.len(),"result":txt_authoring::analyze(&changed),
            "original":null,"before":null,"after":null,"included":null,"expanded":false,
            "requires_cascade":false,"label":"필드로 만들기","edits":[],"links_existing":links});
        Ok((changed.into_bytes(), impact))
    }
    pub(super) fn dispatch_proposal(
        &self,
        state: &mut AuthoringState,
        action: &str,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        match action {
            "propose_fields" => self.action_propose_fields(state, payload),
            "propose_make" => self.action_propose_make(state, payload),
            "propose_make_all" => self.action_propose_make_all(state, payload),
            "propose_dismiss" => self.action_propose_dismiss(state, payload),
            "propose_off" => self.action_propose_off(state, payload),
            "propose_pick_column" => self.action_propose_pick_column(state, payload),
            _ => unreachable!(),
        }
    }
    fn action_propose_fields(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        let proposal = session
            .proposal
            .get_or_insert_with(FieldProposalState::default);
        let requested = payload
            .get("pool_key")
            .and_then(Value::as_str)
            .filter(|text| !text.is_empty())
            .map(|key| {
                (
                    key.to_owned(),
                    payload
                        .get("sheet")
                        .and_then(Value::as_str)
                        .filter(|text| !text.is_empty())
                        .map(str::to_owned),
                )
            });
        let source = if requested.is_some() {
            requested
        } else if proposal.pool_key.is_empty() {
            self.proposal_data
                .as_ref()
                .map(ProposalData::current)
                .transpose()
                .map_err(fail)?
                .flatten()
        } else {
            None
        };
        if let Some((key, sheet)) = source {
            proposal.pool_key = key.clone();
            proposal.sheet = sheet.clone();
            proposal.row = None;
            proposal.loaded = self
                .proposal_data
                .as_ref()
                .map(|data| data.load(&key, sheet.as_deref()));
        }
        if let Some(row) = payload
            .get("row")
            .and_then(Value::as_u64)
            .filter(|row| *row >= 1)
        {
            proposal.row = Some(row as usize);
        }
        session.proposal_cache = None;
        self.proposal_view(session)?
            .ok_or_else(|| fail("제안을 읽을 수 없습니다."))
    }
    fn action_propose_make(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        let group = self.proposal_group(session, payload.get("group_id"))?;
        let command = group_command(&group, payload.get("spot_id"))
            .map_err(|error| fail(error.to_string()))?;
        self.proposal_preview(
            state,
            payload,
            command,
            vec![group.clone()],
            toast_one(group["name"].as_str().unwrap_or("")),
        )
    }
    fn action_propose_make_all(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        let view = self
            .proposal_view(session)?
            .ok_or("제안을 찾을 수 없습니다. 제안 목록에서 다시 고르세요.")?;
        let (command, groups) = all_command(&view).map_err(|error| fail(error.to_string()))?;
        let toast = toast_many(groups.len());
        self.proposal_preview(state, payload, command, groups, toast)
    }
    fn action_propose_dismiss(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        let group = self.proposal_group(session, payload.get("group_id"))?;
        let state = session.proposal.as_mut().expect("group needs proposal");
        let item = (
            group["column"].as_str().unwrap_or("").to_owned(),
            group["raw"].as_str().unwrap_or("").to_owned(),
        );
        if !state.dismissed.contains(&item) {
            state.dismissed.push(item)
        }
        session.proposal_cache = None;
        self.proposal_view(session)?
            .ok_or_else(|| fail("제안을 읽을 수 없습니다."))
    }
    fn action_propose_off(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, false)?;
        session.proposal = None;
        session.proposal_cache = None;
        session.proposal_pending = None;
        Ok(json!({"ok":true}))
    }
    fn action_propose_pick_column(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let session = state.session_mut(payload, true)?;
        let group = self.proposal_group(session, payload.get("group_id"))?;
        let proposal = session.proposal.as_mut().expect("group needs proposal");
        pick_column(
            proposal,
            &group,
            payload.get("column").unwrap_or(&Value::Null),
        )
        .map_err(|error| fail(error.to_string()))?;
        session.proposal_cache = None;
        self.proposal_view(session)?
            .ok_or_else(|| fail("제안을 읽을 수 없습니다."))
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn txt_multi_field_sites_apply_back_to_front_and_refuse_overlap() {
        let source = "공고명: 장비\n수요기관: 조달청\n장비\n";
        let command = json!({"type":"create_fields","fields":[
            {"name":"공고명","ranges":[{"start":5,"end":7},{"start":18,"end":20}]},
            {"name":"수요기관","ranges":[{"start":14,"end":17}]}
        ]});
        let (changed, impact) =
            AuthoringController::apply_txt_proposal_fields(source, &command).unwrap();
        assert_eq!(
            std::str::from_utf8(&changed).unwrap(),
            "공고명: {{공고명}}\n수요기관: {{수요기관}}\n{{공고명}}\n"
        );
        assert_eq!(impact["affected"], 3);
        let overlap = json!({"type":"create_fields","fields":[
            {"name":"a","ranges":[{"start":5,"end":7}]},
            {"name":"b","ranges":[{"start":6,"end":8}]}
        ]});
        assert!(AuthoringController::apply_txt_proposal_fields(source, &overlap).is_err());
        assert_eq!(source, "공고명: 장비\n수요기관: 조달청\n장비\n");
    }
}
