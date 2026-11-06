//! Export the native product vocabulary used to generate the TypeScript bridge contract.

use hwpx_desktop::product_api;
use hwpx_filler::{
    document_creation_workbench, run_delivery_intent, template_change_product,
    workbench_execution_status,
};
use serde_json::json;

fn main() {
    let descriptor = json!({
        "protocol": product_api::PROTOCOL,
        "version": product_api::VERSION,
        "capabilities": product_api::CAPABILITIES,
        "error_codes": product_api::ERROR_CODES,
        "preparation_statuses": template_change_product::PRODUCT_PREPARATION_STATUSES,
        "apply_statuses": template_change_product::PRODUCT_APPLY_STATUSES,
        "blocker_codes": document_creation_workbench::BLOCKER_CODES,
        "primary_actions": document_creation_workbench::PRIMARY_ACTION_CODES,
        "execution_statuses": workbench_execution_status::WORKBENCH_EXECUTION_STATUS_CODES,
        "collision_policies": run_delivery_intent::COLLISION_POLICIES,
        "session_data_key": hwpx_filler::job_presentation::SESSION_DATA_KEY,
    });
    println!("{descriptor}");
}
