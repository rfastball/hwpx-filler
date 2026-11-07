//! Fixed Workbench record capture into the current sealed TXT authority.

use crate::job_registry::JobRegistry;
use crate::managed_generation_service::{UnpublishedTxtResult, materialize_one_unpublished_txt};
use crate::seal_execution_service::SealExecutionService;
use crate::slot_configuration_product::SlotConfigurationProduct;
use crate::workbench_controller::{MaterializePort, MaterializedTxt, SelectionPort};
use crate::workspace_switch::GraphError;
use chrono::NaiveDateTime;
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::Arc;

pub(crate) fn selection_port(
    selection: Arc<SlotConfigurationProduct>,
    registry: Arc<JobRegistry>,
) -> Arc<SelectionPort> {
    Arc::new(move |work_ref| {
        let job = registry.load(work_ref)?;
        if job.authority_id.is_empty() {
            return Err(
                "포함할 내용을 불러오지 못했습니다(TEMPLATE_INITIALIZATION_REQUIRED)".into(),
            );
        }
        let read = selection.zone(work_ref, Some(&job), false)?;
        let projection = &read.zone["current_view"]["projection"];
        if !projection.is_object() {
            return Err(format!(
                "포함할 내용을 불러오지 못했습니다({})",
                read.zone["current_view"]["context_error"]
                    .as_str()
                    .unwrap_or("NO_PROJECTION")
            )
            .into());
        }
        projected_selection(projection)
    })
}

fn projected_selection(
    projection: &serde_json::Value,
) -> Result<HashMap<String, HashSet<String>>, GraphError> {
    let mut result = HashMap::new();
    for slot in projection["slots"]
        .as_array()
        .ok_or("포함할 내용 목록이 손상됐습니다.")?
    {
        let id = slot["slot_id"]
            .as_str()
            .ok_or("포함할 내용 ID가 손상됐습니다.")?;
        let options = slot["effective_option_ids"]
            .as_array()
            .ok_or("선택 ID 목록이 손상됐습니다.")?;
        let options = options
            .iter()
            .map(|item| {
                item.as_str()
                    .map(str::to_owned)
                    .ok_or("선택 ID가 손상됐습니다.")
            })
            .collect::<Result<HashSet<_>, _>>()?;
        result.insert(id.to_owned(), options);
    }
    Ok(result)
}

/// The graph supplies one authority root and its JobRegistry; every copy seals fresh basis.
pub fn materialization_port(
    authority_root: PathBuf,
    registry: Arc<JobRegistry>,
) -> Arc<MaterializePort> {
    Arc::new(move |work_ref, record, copy_token, now: NaiveDateTime| {
        let captured_at = now.format("%Y-%m-%dT%H:%M:%S").to_string();
        let seal = SealExecutionService::new(&authority_root, &registry, {
            let captured_at = captured_at.clone();
            move || captured_at.clone()
        })?;
        match materialize_one_unpublished_txt(
            &authority_root,
            &seal,
            work_ref,
            copy_token,
            record,
            &captured_at,
        )? {
            UnpublishedTxtResult::Materialized(bytes) => Ok(MaterializedTxt::Ready(
                String::from_utf8(bytes.output_bytes)?,
            )),
            UnpublishedTxtResult::Refused { detail, .. } => Ok(MaterializedTxt::Refused(detail)),
        }
    })
}
