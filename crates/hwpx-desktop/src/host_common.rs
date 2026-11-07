//! Product IPC verbs that need a graph, without depending on the native window.

use crate::live_graph::LiveGraph;
use serde_json::{Value, json};

pub fn call<R>(
    graph: &LiveGraph<R>,
    method: &str,
    args: &[Value],
) -> Option<Result<Value, String>> {
    if matches!(
        method,
        "initial" | "dispatch" | "close_guard_state" | "close_flush_required"
    ) && let Err(error) = crate::native_methods::validate_host_call(method, args)
    {
        return Some(Err(error));
    }
    let required = |index: usize| {
        args.get(index)
            .and_then(Value::as_str)
            .ok_or_else(|| format!("{method}: 문자열 인자 {index}가 필요합니다."))
    };
    let arity = |count: usize| {
        if args.len() == count {
            Ok(())
        } else {
            Err(format!("{method}: 인자 수가 올바르지 않습니다."))
        }
    };
    match method {
        "initial" => {
            Some(arity(1).and_then(|()| graph.initial(required(0)?).map_err(|e| e.to_string())))
        }
        "dispatch" => Some((|| {
            let default_payload = json!({});
            let payload = if args.get(2).is_none_or(Value::is_null) {
                &default_payload
            } else {
                &args[2]
            };
            let screen = required(0)?;
            let action = required(1)?;
            match graph.dispatch(screen, action, payload) {
                Ok(value) => Ok(value),
                Err(error) if error.is::<crate::action_registry::DispatchError>() => {
                    Ok(dispatch_rejection(&error.to_string()))
                }
                Err(error)
                    if screen == "job"
                        && action == "recover_record_issue"
                        && error
                            .downcast_ref::<crate::job_controller::JobControllerError>()
                            .is_some_and(|job| job.code.is_none()) =>
                {
                    Ok(dispatch_rejection(&error.to_string()))
                }
                Err(error) => Err(error.to_string()),
            }
        })()),
        "close_guard_state" => {
            Some(arity(0).and_then(|()| graph.close_guard_state().map_err(|e| e.to_string())))
        }
        "close_flush_required" => Some(arity(0).and_then(|()| {
            graph
                .close_flush_required()
                .map(|value| json!(value))
                .map_err(|e| e.to_string())
        })),
        _ => None,
    }
}

fn dispatch_rejection(message: &str) -> Value {
    json!({"__hwpx_dispatch_rejection_v1__": {"name": "ValueError", "message": message}})
}
