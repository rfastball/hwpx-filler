//! Confirmation tier and the created or renamed target after a command.

use crate::text_render::python_truthy;
use serde_json::{Value, json};

fn requires_button(action: &str, command: &Value, preview: &Value) -> bool {
    matches!(action, "delete" | "revert_template")
        || (action == "unwrap"
            && (python_truthy(&preview["requires_cascade"]) || python_truthy(&command["cascade"])))
}
fn renames_identifier(action: &str, command: &Value) -> bool {
    matches!(action, "rename_slot" | "rename_option")
        && command.get("id").is_some()
        && command["id"]
            != command[if action == "rename_slot" {
                "slot_id"
            } else {
                "option_id"
            }]
}
fn command_requires_review(action: &str, command: &Value, preview: &Value) -> bool {
    matches!(
        action,
        "rename_field"
            | "adjust_range"
            | "move"
            | "duplicate"
            | "unwrap"
            | "unset_field"
            | "relink_field"
            | "paste"
            | "repair_marker"
    ) || renames_identifier(action, command)
        || python_truthy(&preview["expanded"])
        || (action == "create_field"
            && (python_truthy(&command["ranges"]) || python_truthy(&preview["links_existing"])))
}
fn impact_requires_review(impact: &Value) -> bool {
    python_truthy(&impact["field_delta"]["removed_fields"])
        || (python_truthy(&impact["linked_jobs"])
            && impact["structure_delta"]
                .as_object()
                .is_some_and(|map| map.values().any(python_truthy)))
        || impact["impact_unverified"]
            .as_i64()
            .is_some_and(|count| count > 0)
}
pub fn confirm_tier(command: &Value, preview: &Value, impact: Option<&Value>) -> &'static str {
    let action = command["type"].as_str().unwrap_or("");
    if requires_button(action, command, preview) {
        return "button";
    }
    if command_requires_review(action, command, preview)
        || impact_requires_review(impact.unwrap_or(&Value::Null))
    {
        return "enter";
    }
    "none"
}
pub fn created_target(command: &Value, result: &Value) -> Option<Value> {
    match command["type"].as_str()? {
        "create_field" => {
            let name = crate::fields::normalize_field_id(command["name"].as_str()?)?;
            let field = result["fields"]
                .as_array()?
                .iter()
                .find(|field| field["name"] == name)?;
            let occurrences = field["occurrences"].as_array()?.clone();
            let first = occurrences.first()?;
            Some(
                json!({"kind":"field","name":name,"count":field.get("count").cloned().unwrap_or(json!(occurrences.len())),
                "occurrences":occurrences,"location":first}),
            )
        }
        "create_slot" | "create_option" => {
            let slot_id = if command["type"] == "create_slot" {
                &command["id"]
            } else {
                &command["slot_id"]
            };
            let slot = result["slots"]
                .as_array()?
                .iter()
                .find(|slot| &slot["id"] == slot_id)?;
            if command["type"] == "create_slot" {
                return Some(json!({"kind":"slot","slot_id":slot_id,"location":slot["location"]}));
            }
            let option = slot["options"]
                .as_array()?
                .iter()
                .find(|option| option["id"] == command["id"])?;
            Some(
                json!({"kind":"option","slot_id":slot_id,"option_id":option["id"],"location":option["location"]}),
            )
        }
        _ => None,
    }
}
pub fn renamed_target(command: &Value, result: &Value) -> Option<Value> {
    match command["type"].as_str()? {
        "rename_field" => {
            let name = crate::fields::normalize_field_id(command["name"].as_str()?)?;
            let field = result["fields"]
                .as_array()?
                .iter()
                .find(|field| field["name"] == name)?;
            let occurrences = field["occurrences"].as_array()?.clone();
            let first = occurrences.first()?;
            Some(
                json!({"kind":"field","name":name,"count":field.get("count").cloned().unwrap_or(json!(occurrences.len())),
                "occurrences":occurrences,"location":first}),
            )
        }
        "rename_slot" | "rename_option" => {
            let slot_id = if command["type"] == "rename_slot" {
                command.get("id").unwrap_or(&command["slot_id"])
            } else {
                &command["slot_id"]
            };
            let slot = result["slots"]
                .as_array()?
                .iter()
                .find(|slot| &slot["id"] == slot_id)?;
            if command["type"] == "rename_slot" {
                let mut slot = slot.clone();
                slot["kind"] = json!("slot");
                slot["slot_id"] = slot_id.clone();
                return Some(slot);
            }
            let option_id = command.get("id").unwrap_or(&command["option_id"]);
            let option = slot["options"]
                .as_array()?
                .iter()
                .find(|option| &option["id"] == option_id)?;
            let mut option = option.clone();
            option["kind"] = json!("option");
            option["slot_id"] = slot_id.clone();
            option["option_id"] = option_id.clone();
            Some(option)
        }
        _ => None,
    }
}
