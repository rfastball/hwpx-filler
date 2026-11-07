//! Data-pool screen transport over the native registry and pure product projections.

use crate::action_registry::validate_dispatch;
use crate::dataset_registry::{DatasetPoolRegistry, PoolError};
use crate::workspace_switch::{GraphError, PushGate, ScreenController};
use hwpx_filler::dataset_pool::{DatasetDetail, DatasetPoolRow, bound_state, confirm_basis};
use hwpx_filler::dataset_reference::{DatasetReference, reference_identity};
use serde_json::{Map, Value, json};
use std::path::Path;
use std::sync::{Arc, Mutex};

mod projection;
mod registration;
use projection::{notices, row_json};

#[derive(Default)]
struct PoolState {
    detail: Option<DatasetDetail>,
    result_text: String,
    result_level: String,
}

pub struct PoolController {
    registry: Arc<DatasetPoolRegistry>,
    push: PushGate,
    state: Mutex<PoolState>,
    push_order: Mutex<()>,
}
impl PoolController {
    pub fn new(registry: Arc<DatasetPoolRegistry>, push: PushGate) -> Self {
        Self {
            registry,
            push,
            state: Mutex::new(PoolState {
                result_level: "muted".into(),
                ..PoolState::default()
            }),
            push_order: Mutex::new(()),
        }
    }
    fn push_current(&self) -> Result<(), GraphError> {
        let _serial = self
            .push_order
            .lock()
            .map_err(|_| "pool push order poisoned")?;
        self.push.push("pool", &self.snapshot()?)?;
        Ok(())
    }
    fn state(&self) -> Result<std::sync::MutexGuard<'_, PoolState>, GraphError> {
        Ok(self
            .state
            .lock()
            .map_err(|_| "pool controller state poisoned")?)
    }
    fn required_string<'a>(
        payload: &'a Map<String, Value>,
        key: &str,
    ) -> Result<&'a str, GraphError> {
        Ok(payload
            .get(key)
            .and_then(Value::as_str)
            .ok_or("pool payload string required")?)
    }
    fn snapshot(&self) -> Result<Value, GraphError> {
        let view = self.registry.project_view()?;
        let mut state = self.state()?;
        if state
            .detail
            .as_ref()
            .is_some_and(|detail| !view.rows.iter().any(|row| row.key == detail.key))
        {
            state.detail = None;
        }
        let rows = view.rows.iter().map(row_json).collect::<Vec<_>>();
        let notices = notices(&view);
        Ok(json!({
            "detail": state.detail.as_ref().map(DatasetDetail::to_dict),
            "column": {
                "rows": rows,
                "notices": notices,
                "empty_hint": view.empty_hint(),
                "count_label": view.count_label(),
                "result": {"text": state.result_text, "level": state.result_level}
            }
        }))
    }
    fn review(&self, key: &str) -> Result<DatasetDetail, GraphError> {
        let item = self.registry.load(key)?;
        let path = item
            .opts
            .get(if item.kind == "pclm" { "db" } else { "path" })
            .and_then(Value::as_str)
            .unwrap_or("");
        let row =
            DatasetPoolRow::from_item(key, &item, !path.is_empty() && !Path::new(path).exists())?;
        Ok(DatasetDetail::from_item(
            &row,
            &item,
            crate::nara_source::source_from_pool_reference_live(&item)
                .and_then(|mut source| source.fields())
                .map_err(|error| error.to_string()),
        )?)
    }
    fn set_result(&self, text: String, level: &str) -> Result<(), GraphError> {
        let mut state = self.state()?;
        state.result_text = text;
        state.result_level = level.into();
        Ok(())
    }
    fn refusal(&self, message: String) -> Result<Value, GraphError> {
        self.set_result(message.clone(), "danger")?;
        Ok(json!({"ok":false,"error":message}))
    }
    fn stale_basis(&self) -> Result<Value, GraphError> {
        self.refusal("확인하는 사이 이 데이터의 등록 상태가 바뀌어 실행하지 않았습니다. 목록을 새로 읽었으니 다시 확인해 주세요.".into())
    }
    fn reproject_open_detail(&self, key: &str) -> Result<(), GraphError> {
        if self
            .state()?
            .detail
            .as_ref()
            .is_some_and(|detail| detail.key == key)
        {
            let detail = self.review(key)?;
            self.state()?.detail = Some(detail);
        }
        Ok(())
    }
    /// Routes one validated pool action; every arm is a single call.
    fn perform(&self, action: &str, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        match action {
            "refresh" => Ok(Value::Null),
            "review" => self.open_review(payload),
            "archive" | "activate" => self.archive_or_activate(action, payload),
            "reorder_sheets" => self.reorder_sheets(payload),
            "inspect_sheets" => inspect_sheets(payload),
            "register_excel" => self.register_excel(payload),
            "register_pclm" => self.register_pclm(payload),
            "relink" => self.relink(payload),
            "delete" => self.delete_reference(payload),
            "resolve_duplicate" => self.resolve_duplicate(payload),
            _ => Err(format!("알 수 없는 pool 액션: {action:?}").into()),
        }
    }
    fn open_review(&self, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let key = Self::required_string(payload, "key")?;
        let detail = match self.review(key) {
            Ok(detail) => detail,
            Err(error)
                if matches!(
                    error.downcast_ref::<PoolError>(),
                    Some(PoolError::Io(io_error))
                        if io_error.kind() == std::io::ErrorKind::NotFound
                ) =>
            {
                self.state()?.detail = None;
                return self.refusal(missing_message(key));
            }
            Err(error) => return Err(error),
        };
        self.set_result(
            if detail.error.is_empty() {
                format!("검토 {}: {}", detail.name, detail.column_summary())
            } else {
                format!("검토 {}: {}", detail.name, detail.error)
            },
            if detail.error.is_empty() {
                "ok"
            } else {
                "danger"
            },
        )?;
        self.state()?.detail = Some(detail);
        Ok(json!({"ok":true}))
    }
    fn archive_or_activate(
        &self,
        action: &str,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let key = Self::required_string(payload, "key")?;
        let name = self.registry.load(key)?.name;
        let archive = action == "archive";
        if archive {
            self.registry.commands().archive(key)?;
        } else {
            self.registry.commands().activate(key)?;
        }
        self.reproject_open_detail(key)?;
        self.set_result(
            format!(
                "데이터셋을 {}했습니다: {name}",
                if archive { "보관" } else { "활성화" }
            ),
            "ok",
        )?;
        Ok(json!({"ok":true}))
    }
    fn reorder_sheets(&self, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let key = Self::required_string(payload, "key")?;
        let sheets = payload
            .get("sheets")
            .and_then(Value::as_array)
            .ok_or("pool sheets array required")?
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(str::to_owned)
                    .ok_or("pool sheet string required")
            })
            .collect::<Result<Vec<_>, _>>()?;
        self.registry.commands().reorder_sheets(key, &sheets)?;
        self.reproject_open_detail(key)?;
        Ok(Value::Null)
    }
    fn delete_reference(&self, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let key = Self::required_string(payload, "key")?;
        let item = self.registry.load(key)?;
        if !confirmed(payload) {
            return Ok(json!({
                "ok":true,"needs_confirm":true,"key":key,
                "basis":confirm_basis(&[bound_state(key,&item)?]),
                "confirm_text":format!(
                    "등록 데이터 참조를 삭제합니다(원본 파일은 지우지 않습니다):\n{} ({})",
                    item.name,hwpx_filler::dataset_pool::reference_summary(&item)?)
            }));
        }
        let basis = payload.get("basis").and_then(Value::as_str);
        match self.registry.commands().delete_confirmed(key, basis) {
            Ok(deleted) => {
                if self
                    .state()?
                    .detail
                    .as_ref()
                    .is_some_and(|detail| detail.key == key)
                {
                    self.state()?.detail = None;
                }
                self.set_result(
                    format!("데이터셋 참조를 삭제했습니다: {}", deleted.name),
                    "ok",
                )?;
                Ok(json!({"ok":true}))
            }
            Err(PoolError::Stale(_)) => self.stale_basis(),
            Err(error) => Err(error.into()),
        }
    }
    fn resolve_duplicate(&self, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let keep = Self::required_string(payload, "keep")?;
        let (entries, _) = self.registry.list_references(None)?;
        let identity = entries
            .iter()
            .find(|(key, _)| key == keep)
            .and_then(|(_, item)| reference_identity(item));
        let group = entries
            .into_iter()
            .filter(|(_, item)| {
                identity
                    .as_ref()
                    .is_some_and(|identity| reference_identity(item).as_ref() == Some(identity))
            })
            .collect::<Vec<_>>();
        if group.len() < 2 {
            return self.refusal(NO_DUPLICATES.into());
        }
        if !confirmed(payload) {
            return confirm_duplicate_merge(keep, &group);
        }
        match self
            .registry
            .commands()
            .resolve_duplicates(keep, payload.get("basis").and_then(Value::as_str))
        {
            Ok((kept, removed)) => {
                self.set_result(
                    format!("중복 등록 {removed}건을 정리하고 '{kept}' 을(를) 남겼습니다."),
                    "ok",
                )?;
                Ok(json!({"ok":true,"kept":kept,"removed":removed}))
            }
            Err(PoolError::Stale(_)) => self.stale_basis(),
            Err(PoolError::Invalid(_)) => self.refusal(NO_DUPLICATES.into()),
            Err(error) => Err(error.into()),
        }
    }
}

const NO_DUPLICATES: &str = "병합할 중복 등록이 더는 없습니다. 목록을 새로 읽었습니다.";

/// Whether the payload carries the user's confirmation of a previously shown request.
fn confirmed(payload: &Map<String, Value>) -> bool {
    payload
        .get("confirm")
        .and_then(Value::as_bool)
        .unwrap_or(false)
}

fn missing_message(name: &str) -> String {
    format!("등록 데이터를 찾을 수 없습니다(이미 삭제된 항목): {name}. 목록을 새로 읽었습니다.")
}

fn confirm_duplicate_merge(
    keep: &str,
    group: &[(String, DatasetReference)],
) -> Result<Value, GraphError> {
    let kept = group
        .iter()
        .find(|(key, _)| key == keep)
        .expect("keep belongs to group");
    let dropped = group
        .iter()
        .filter(|(key, _)| key != keep)
        .map(|(_, item)| format!("'{}'", item.name))
        .collect::<Vec<_>>()
        .join(", ");
    let states = group
        .iter()
        .map(|(key, item)| bound_state(key, item))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(json!({
        "ok":true,"needs_confirm":true,"keep":keep,
        "basis":confirm_basis(&states),
        "confirm_text":format!(
            "같은 데이터({})를 가리키는 등록 {}건을 '{}' 하나로 합칩니다.\n삭제되는 등록: {} — 그 이름·메모는 사라집니다(원본 파일은 지우지 않습니다).",
            hwpx_filler::dataset_pool::reference_summary(&kept.1)?,
            group.len(),kept.1.name,dropped
        )
    }))
}

fn inspect_sheets(payload: &Map<String, Value>) -> Result<Value, GraphError> {
    let path = PoolController::required_string(payload, "path")?;
    let inspected = if payload.get("kind").and_then(Value::as_str) == Some("pclm") {
        hwpx_filler::dataset_reference::resolve_pclm_db(path)
            .map_err(|error| error.to_string())
            .and_then(|resolved| {
                hwpx_filler::data_pclm::list_sqlite_sheets(resolved)
                    .map_err(|error| error.to_string())
            })
            .map(|names| {
                names
                    .into_iter()
                    .map(|name| json!({"name":name}))
                    .collect::<Vec<_>>()
            })
    } else {
        hwpx_filler::data_excel::sheet_overview(Path::new(path))
            .map_err(|error| error.to_string())
            .map(|rows| {
                rows.into_iter()
                    .map(|(name, rows, cols)| {
                        json!({
                            "name":name,"rows":rows,"cols":cols
                        })
                    })
                    .collect::<Vec<_>>()
            })
    };
    Ok(match inspected {
        Ok(sheets) => json!({"ok":true,"sheets":sheets}),
        Err(error) => json!({"ok":false,"error":error}),
    })
}
impl ScreenController for PoolController {
    fn initial(&self) -> Result<Value, GraphError> {
        self.snapshot()
    }
    fn dispatch(&self, action: &str, payload: &Value) -> Result<Value, GraphError> {
        let object = validate_dispatch("pool", action, payload)?;
        let result = self.perform(action, object)?;
        self.push_current()?;
        Ok(result)
    }
    fn close_guard_reason(&self) -> Result<Option<String>, GraphError> {
        Ok(None)
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::PoolController;
    use crate::dataset_registry::DatasetPoolRegistry;
    use crate::locations::Locations;
    use crate::registered_contract_data::registered_data_source;
    use crate::workspace_switch::{WorkspaceGraph, WorkspaceSwitch};
    use hwpx_filler::dataset_reference::DatasetReference;
    use serde_json::{Map, Value, json};
    use std::fs;
    use std::path::Path;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::mpsc;
    use std::sync::{Arc, Mutex};
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

    #[test]
    fn sheet_reordering_keeps_registered_pclm_default_binding_and_filters() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/pool-controller-tests")
            .join(format!("sheets-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        let db = root.join("registered.pclm");
        rusqlite::Connection::open(&db)
            .unwrap()
            .execute_batch(
                "CREATE TABLE pclm_file(singleton INTEGER, role TEXT, dataset_id TEXT);
             INSERT INTO pclm_file VALUES(1,'work','source-id');
             CREATE VIEW v_통합 AS SELECT 1 AS 항목;
             CREATE VIEW v_접수 AS SELECT 1 AS 항목;
             CREATE VIEW v_공고 AS SELECT 1 AS 항목;
             CREATE VIEW v_계약 AS SELECT 1 AS 항목;",
            )
            .unwrap();
        let registry = Arc::new(DatasetPoolRegistry::new(root.join("datasets")).unwrap());
        let located = (db.to_string_lossy().into_owned(), "source-id".to_owned());
        let descriptor = registered_data_source(&registry, Some(located.clone()))
            .unwrap()
            .unwrap();
        let key = descriptor["pool_key"].as_str().unwrap().to_owned();
        let original = registry.load(&key).unwrap();
        assert_eq!(
            original.opts["sheets"],
            json!(["v_통합", "v_접수", "v_공고", "v_계약"])
        );
        registry
            .commands()
            .set_filters(
                &key,
                &json!([{"name":"통합 필터","state":{}}]),
                Some("v_통합"),
            )
            .unwrap();
        registry
            .commands()
            .set_filters(
                &key,
                &json!([{"name":"계약 필터","state":{}}]),
                Some("v_계약"),
            )
            .unwrap();
        let for_graph = registry.clone();
        let graph = WorkspaceSwitch::new(
            Locations::new(&root, None),
            |_, _| Ok(None),
            move |home, gate, token| {
                Ok(WorkspaceGraph::new(
                    home.map(Path::to_path_buf),
                    vec![(
                        "pool".into(),
                        Arc::new(PoolController::new(for_graph.clone(), gate)),
                    )],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let controller = graph.active().controller("pool").unwrap();
        assert_eq!(
            controller.dispatch("review", &json!({"key":key})).unwrap()["ok"],
            true
        );
        let before = registry.load(&key).unwrap();
        let chosen = ["v_계약", "v_공고", "v_접수", "v_통합"];
        controller
            .dispatch("reorder_sheets", &json!({"key":key,"sheets":chosen}))
            .unwrap();
        let reopened = DatasetPoolRegistry::new(registry.directory().to_path_buf()).unwrap();
        let saved = reopened.load(&key).unwrap();
        assert_eq!(saved.opts["sheets"], json!(chosen));
        assert_eq!(saved.opts["view"], "v_통합");
        assert_eq!(saved.filters, before.filters);
        assert_eq!(saved.sheet_filters, before.sheet_filters);
        assert_eq!(
            controller.initial().unwrap()["detail"]["sheet_title"],
            chosen.join(", ")
        );
        assert_eq!(
            registered_data_source(&reopened, Some(located.clone())).unwrap(),
            Some(descriptor)
        );
        assert_eq!(reopened.load(&key).unwrap().opts["sheets"], json!(chosen));
        let sqlite = rusqlite::Connection::open(&db).unwrap();
        sqlite
            .execute_batch("CREATE VIEW u_사용자계약 AS SELECT 2 AS 항목;")
            .unwrap();
        let inspected = controller
            .dispatch("inspect_sheets", &json!({"kind":"pclm","path":db}))
            .unwrap();
        assert!(
            inspected["sheets"]
                .as_array()
                .unwrap()
                .iter()
                .any(|sheet| sheet["name"] == "u_사용자계약")
        );
        for invalid in [
            json!(["v_통합", "v_접수"]),
            json!(["v_통합", "v_접수", "v_공고", "v_공고"]),
            json!(["v_통합", "v_접수", "v_공고", "foreign"]),
            json!(["v_통합", "v_접수", "v_공고", ""]),
        ] {
            assert!(
                controller
                    .dispatch("reorder_sheets", &json!({"key":key,"sheets":invalid}))
                    .is_err()
            );
            assert_eq!(reopened.load(&key).unwrap().opts["sheets"], json!(chosen));
        }
        registry.commands().archive(&key).unwrap();
        assert_eq!(
            registered_data_source(&reopened, Some(located)).unwrap(),
            None
        );
        drop(sqlite);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn pool_graph_projects_real_slots_and_requires_the_same_delete_basis() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-pool-graph-{}-{stamp}",
            std::process::id()
        ));
        let registry = Arc::new(DatasetPoolRegistry::new(sandbox.join("datasets")).unwrap());
        let mut opts = Map::new();
        opts.insert(
            "path".into(),
            Value::String(sandbox.join("missing.csv").to_str().unwrap().into()),
        );
        let item = DatasetReference::new("등록", "excel", opts).unwrap();
        let key = registry.add(&item).unwrap();
        let pushed = Arc::new(Mutex::new(Vec::new()));
        let observed = pushed.clone();
        let pause_next = Arc::new(AtomicBool::new(false));
        let pause_sink = pause_next.clone();
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let release_rx = Mutex::new(release_rx);
        let for_graph = registry.clone();
        let locations = Locations::new(
            Path::new("C:/Users/test"),
            Some(sandbox.as_os_str().to_os_string()),
        );
        let graph = WorkspaceSwitch::new(
            locations,
            move |_screen, snapshot| {
                if pause_sink.swap(false, Ordering::SeqCst) {
                    entered_tx.send(()).unwrap();
                    release_rx.lock().unwrap().recv().unwrap();
                }
                observed.lock().unwrap().push(snapshot.clone());
                Ok(None)
            },
            move |home, gate, token| {
                let controller = Arc::new(PoolController::new(for_graph.clone(), gate));
                Ok(WorkspaceGraph::new(
                    home.map(Path::to_path_buf),
                    vec![("pool".into(), controller)],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let controller = graph.active().controller("pool").unwrap();
        assert_excel_review_boundary(controller.as_ref(), &registry);
        assert_initial_pool_projection(controller.as_ref());
        assert_eq!(
            controller
                .dispatch(
                    "inspect_sheets",
                    &json!({"path":sandbox.join("missing.csv").to_str().unwrap()})
                )
                .unwrap()["ok"],
            true
        );
        assert_eq!(
            controller
                .dispatch(
                    "inspect_sheets",
                    &json!({"path":sandbox.join("missing.xlsx").to_str().unwrap()})
                )
                .unwrap()["ok"],
            false
        );
        assert_eq!(
            controller.dispatch("review", &json!({"key":key})).unwrap(),
            json!({"ok":true})
        );
        assert_eq!(controller.initial().unwrap()["detail"]["column_count"], 0);
        assert_ne!(controller.initial().unwrap()["detail"]["error"], "");
        let pending = controller.dispatch("delete", &json!({"key":key})).unwrap();
        assert_eq!(pending["needs_confirm"], true);
        assert!(registry.exists(&key).unwrap());
        let refused = controller
            .dispatch("delete", &json!({"key":key,"confirm":true}))
            .unwrap();
        assert_eq!(refused["ok"], false);
        assert!(registry.exists(&key).unwrap());
        assert_eq!(
            controller
                .dispatch(
                    "delete",
                    &json!({"key":key,"confirm":true,"basis":pending["basis"]})
                )
                .unwrap(),
            json!({"ok":true})
        );
        assert!(!registry.exists(&key).unwrap());
        let keep = registry.add(&item).unwrap();
        registry.save_at("legacy", &item).unwrap();
        assert_column_notices(controller.as_ref(), &registry, &keep);
        let merge = controller
            .dispatch("resolve_duplicate", &json!({"keep":keep}))
            .unwrap();
        assert_eq!(merge["needs_confirm"], true);
        let refused = controller
            .dispatch("resolve_duplicate", &json!({"keep":keep,"confirm":true}))
            .unwrap();
        assert_eq!(refused["ok"], false);
        assert!(registry.exists("legacy").unwrap());
        let resolved = controller
            .dispatch(
                "resolve_duplicate",
                &json!({"keep":keep,"confirm":true,"basis":merge["basis"]}),
            )
            .unwrap();
        assert_eq!(resolved["removed"], 1);
        assert!(!registry.exists("legacy").unwrap());
        let moved_path = sandbox.join("moved.csv").to_str().unwrap().to_owned();
        let relink = controller
            .dispatch("relink", &json!({"key":keep,"path":moved_path}))
            .unwrap();
        assert_eq!(relink["needs_confirm"], true);
        let refused = controller
            .dispatch(
                "relink",
                &json!({
                    "key":keep,"path":moved_path,"confirm":true
                }),
            )
            .unwrap();
        assert_eq!(refused["ok"], false);
        assert_eq!(
            controller
                .dispatch(
                    "relink",
                    &json!({
                        "key":keep,"path":moved_path,"confirm":true,"basis":relink["basis"]
                    })
                )
                .unwrap()["ok"],
            true
        );
        assert_eq!(registry.load(&keep).unwrap().opts["path"], moved_path);
        let new_path = sandbox.join("new.csv").to_str().unwrap().to_owned();
        let added = controller
            .dispatch(
                "register_excel",
                &json!({"name":"새 데이터","path":new_path}),
            )
            .unwrap();
        assert_eq!(added["ok"], true);
        let rename = controller
            .dispatch(
                "register_excel",
                &json!({
                    "name":"새 이름","path":new_path
                }),
            )
            .unwrap();
        assert_eq!(rename["needs_confirm"], true);
        let refused = controller
            .dispatch(
                "register_excel",
                &json!({
                    "name":"새 이름","path":new_path,"confirm":true
                }),
            )
            .unwrap();
        assert_eq!(refused["ok"], false);
        let renamed = controller
            .dispatch(
                "register_excel",
                &json!({
                    "name":"새 이름","path":new_path,"confirm":true,"basis":rename["basis"]
                }),
            )
            .unwrap();
        assert_eq!(renamed["ok"], true);
        assert_eq!(
            registry
                .find_identity(&new_path, None)
                .unwrap()
                .unwrap()
                .1
                .name,
            "새 이름"
        );
        let db = sandbox.join("contracts.db");
        rusqlite::Connection::open(&db)
            .unwrap()
            .execute_batch(
                "CREATE TABLE 계약 (번호 INTEGER); CREATE VIEW 통합 AS SELECT * FROM 계약;",
            )
            .unwrap();
        let db_text = db.to_str().unwrap();
        assert_pclm_registration_boundary(controller.as_ref(), &registry, &db);
        let bad_view = controller
            .dispatch(
                "register_pclm",
                &json!({"name":"계약 목록","db":db_text,"view":"없는 뷰"}),
            )
            .unwrap();
        assert_eq!(bad_view["ok"], false);
        let registered = controller
            .dispatch(
                "register_pclm",
                &json!({"name":"계약 목록","db":db_text,"view":"통합","views":["통합"]}),
            )
            .unwrap();
        assert_eq!(registered["ok"], true);
        let pclm_key = registry
            .find_identity_raw(&hwpx_filler::dataset_reference::pclm_identity(
                db_text, "통합",
            ))
            .unwrap()
            .unwrap()
            .0;
        assert_eq!(
            controller
                .dispatch("review", &json!({"key":pclm_key}))
                .unwrap()["ok"],
            true
        );
        assert_eq!(
            controller.initial().unwrap()["detail"]["columns"],
            json!(["번호"])
        );
        let detail = controller.initial().unwrap()["detail"].clone();
        assert_eq!(detail["sheet"], "통합");
        assert_eq!(detail["sheet_title"], "통합");
        assert_eq!(detail["error"], "");
        assert!(
            detail["facts"]
                .as_array()
                .unwrap()
                .contains(&json!("시트: 통합"))
        );
        let repeated = controller
            .dispatch(
                "register_pclm",
                &json!({"name":"계약 목록","db":db_text,"view":"통합","views":["통합"]}),
            )
            .unwrap();
        assert_eq!(repeated["key"].as_str().unwrap().len(), 16);
        let pending = controller
            .dispatch(
                "register_pclm",
                &json!({"name":"계약 새 이름","db":db_text,"view":"통합","views":["통합"]}),
            )
            .unwrap();
        assert_eq!(pending["needs_confirm"], true);
        assert_eq!(
            controller
                .dispatch(
                    "register_pclm",
                    &json!({"name":"계약 새 이름","db":db_text,"view":"통합","views":["통합"],"confirm":true})
                )
                .unwrap()["ok"],
            false
        );
        assert_eq!(
            controller
                .dispatch(
                    "register_pclm",
                    &json!({"name":"계약 새 이름","db":db_text,"view":"통합","views":["통합"],"confirm":true,"basis":pending["basis"]})
                )
                .unwrap()["ok"],
            true
        );
        assert_eq!(
            registry
                .find_identity_raw(&hwpx_filler::dataset_reference::pclm_identity(
                    db_text, "통합"
                ))
                .unwrap()
                .unwrap()
                .1
                .name,
            "계약 새 이름"
        );
        let stale = controller.dispatch("register_pclm", &json!({"name":"덮어쓰기","db":db_text,"view":"통합","views":["통합"],"confirm":true,"basis":pending["basis"]})).unwrap();
        assert_eq!(stale["ok"], false);
        assert_eq!(registry.load(&pclm_key).unwrap().name, "계약 새 이름");
        assert!(!pushed.lock().unwrap().is_empty());
        let other_key = registry.find_identity(&new_path, None).unwrap().unwrap().0;
        let before = pushed.lock().unwrap().len();
        pause_next.store(true, Ordering::SeqCst);
        let first = controller.clone();
        let earlier = std::thread::spawn(move || {
            first.dispatch("review", &json!({"key":other_key})).unwrap();
        });
        entered_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        let second = controller.clone();
        let later_key = pclm_key.clone();
        let later = std::thread::spawn(move || {
            second
                .dispatch("review", &json!({"key":later_key}))
                .unwrap();
        });
        let deadline = Instant::now() + Duration::from_secs(2);
        while controller.initial().unwrap()["detail"]["key"] != pclm_key {
            assert!(
                Instant::now() < deadline,
                "later pool mutation did not land"
            );
            std::thread::yield_now();
        }
        release_tx.send(()).unwrap();
        earlier.join().unwrap();
        later.join().unwrap();
        let snapshots = pushed.lock().unwrap();
        assert_ne!(snapshots[before]["detail"]["key"], pclm_key);
        assert_eq!(snapshots[before + 1]["detail"]["key"], pclm_key);
        drop(snapshots);
        fs::remove_dir_all(sandbox).unwrap();
    }

    fn assert_initial_pool_projection(controller: &dyn crate::workspace_switch::ScreenController) {
        let first = controller.initial().unwrap();
        assert_eq!(first["column"]["rows"][0]["name"], "등록");
        assert_eq!(first["column"]["rows"][0]["selectable"], false);
        assert_eq!(first["detail"], Value::Null);
    }

    fn assert_excel_review_boundary(
        controller: &dyn crate::workspace_switch::ScreenController,
        registry: &DatasetPoolRegistry,
    ) {
        let before = registry.list_references(None).unwrap().0;
        let missing = controller
            .dispatch("review", &json!({"key":"없는키"}))
            .unwrap();
        assert_eq!(missing["ok"], false);
        assert!(
            missing["error"]
                .as_str()
                .unwrap()
                .contains("찾을 수 없습니다")
        );
        assert_eq!(
            controller.initial().unwrap()["column"]["result"]["level"],
            "danger"
        );
        assert_eq!(controller.initial().unwrap()["detail"], Value::Null);
        assert!(controller.dispatch("typo", &json!({})).is_err());
        let fixture =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/multi_sheet.xlsx");
        for payload in [
            json!({"name":"  ","path":fixture}),
            json!({"name":"시트 선언","path":fixture,"sheet":"낙찰현황","sheets":[]}),
            json!({"name":"시트 선언","path":fixture,"sheet":"낙찰현황","sheets":["다른시트"]}),
            json!({"name":"시트 선언","path":fixture,"sheet":"낙찰현황","sheets":["낙찰현황",""]}),
        ] {
            assert_eq!(
                controller.dispatch("register_excel", &payload).unwrap()["ok"],
                false,
                "{payload}"
            );
            assert_eq!(registry.list_references(None).unwrap().0, before);
        }
        let added = controller
            .dispatch(
                "register_excel",
                &json!({
                    "name":"다중시트", "path":fixture, "sheet":"낙찰현황", "sheets":["낙찰현황","낙찰현황"], "note":"분기 집계"
                }),
            )
            .unwrap();
        assert_eq!(added["ok"], true);
        let key = registry
            .find_identity(fixture.to_str().unwrap(), Some("낙찰현황"))
            .unwrap()
            .unwrap()
            .0;
        assert_eq!(registry.load(&key).unwrap().opts["sheet"], "낙찰현황");
        assert_eq!(
            registry.load(&key).unwrap().opts["sheets"],
            json!(["낙찰현황"])
        );
        let column = controller.initial().unwrap()["column"].clone();
        assert_eq!(
            column
                .as_object()
                .unwrap()
                .keys()
                .map(String::as_str)
                .collect::<Vec<_>>(),
            ["rows", "notices", "empty_hint", "count_label", "result"]
        );
        assert_eq!(column["count_label"], "2개");
        assert_eq!(column["empty_hint"], "");
        let row = column["rows"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["key"] == key)
            .unwrap();
        assert_eq!(
            row.as_object()
                .unwrap()
                .keys()
                .map(String::as_str)
                .collect::<Vec<_>>(),
            [
                "key",
                "name",
                "sub",
                "reason",
                "warns",
                "badge_label",
                "badge_level",
                "icon",
                "selectable",
                "path",
                "actions"
            ]
        );
        assert_eq!(row["icon"], "excel");
        assert_eq!(row["path"], fixture.to_str().unwrap());
        assert!(row["sub"].as_str().unwrap().ends_with("분기 집계"));
        assert_eq!(row["warns"], json!([]));
        assert_eq!(row["selectable"], true);
        assert_eq!(row["reason"], "");
        assert_eq!(
            row["actions"]
                .as_array()
                .unwrap()
                .iter()
                .map(|action| action["key"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["relink", "archive", "delete"]
        );
        controller.dispatch("review", &json!({"key":key})).unwrap();
        let detail = controller.initial().unwrap()["detail"].clone();
        assert_eq!(detail["key"], key);
        assert_eq!(detail["name"], "다중시트");
        assert_eq!(detail["error"], "");
        assert!(
            detail["columns"]
                .as_array()
                .unwrap()
                .contains(&json!("업체명"))
        );
        assert_eq!(
            detail["facts"],
            json!(["종류 엑셀/CSV", "시트: 낙찰현황", "메모: 분기 집계"])
        );
        assert_eq!(
            controller.initial().unwrap()["column"]["result"]["level"],
            "ok"
        );
        assert_eq!(detail["actions"], row["actions"]);
        controller.dispatch("archive", &json!({"key":key})).unwrap();
        let archived = controller.initial().unwrap();
        assert_eq!(archived["detail"]["badge_label"], "보관");
        assert_eq!(archived["detail"]["actions"][1]["key"], "activate");
        assert_eq!(
            archived["column"]["rows"]
                .as_array()
                .unwrap()
                .iter()
                .find(|row| row["key"] == key)
                .unwrap()["selectable"],
            false
        );
        controller
            .dispatch("activate", &json!({"key":key}))
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["detail"]["badge_label"],
            "활성"
        );
        registry.delete(&key).unwrap();
        assert_eq!(controller.initial().unwrap()["detail"], Value::Null);
        assert_eq!(registry.list_references(None).unwrap().0, before);
    }

    fn assert_column_notices(
        controller: &dyn crate::workspace_switch::ScreenController,
        registry: &DatasetPoolRegistry,
        keep: &str,
    ) {
        let corrupt = registry.directory().join("broken.dataset.json");
        fs::write(&corrupt, b"{").unwrap();
        let column = controller.initial().unwrap()["column"].clone();
        let notices = column["notices"].as_array().unwrap();
        assert_eq!(notices.len(), 2);
        assert_eq!(notices[0]["level"], "danger");
        assert!(
            notices[0]["text"]
                .as_str()
                .unwrap()
                .contains("broken.dataset.json")
        );
        assert_eq!(notices[0]["actions"], json!([]));
        assert_eq!(notices[1]["level"], "warn");
        assert!(
            notices[1]["text"]
                .as_str()
                .unwrap()
                .contains("등록이 2건입니다")
        );
        let actions = notices[1]["actions"].as_array().unwrap();
        assert_eq!(actions.len(), 2);
        assert!(
            actions
                .iter()
                .all(|action| action["key"] == "resolve_duplicate")
        );
        assert_eq!(
            actions
                .iter()
                .map(|action| action["payload"]["keep"].as_str().unwrap())
                .collect::<std::collections::HashSet<_>>(),
            [keep, "legacy"].into_iter().collect()
        );
        fs::remove_file(corrupt).unwrap();
    }

    fn assert_pclm_registration_boundary(
        controller: &dyn crate::workspace_switch::ScreenController,
        registry: &DatasetPoolRegistry,
        db: &Path,
    ) {
        use hwpx_filler::dataset_reference::pclm_identity;
        let before = registry.list_entries(None).unwrap();
        for (field, value) in [
            ("name", json!(" \t")),
            ("db", json!("")),
            ("view", json!("없는 뷰")),
            ("views", json!([])),
            ("views", json!(["통합", "없는 뷰"])),
            ("views", json!(["통합", "통합"])),
            ("views", json!(["계약"])),
        ] {
            let mut payload = json!({"name":"계약 목록","db":db,"view":"통합"});
            payload[field] = value;
            let rejected = controller.dispatch("register_pclm", &payload).unwrap();
            assert_eq!(rejected["ok"], false, "{payload}");
            if field == "view" {
                let detail = rejected["error"].as_str().unwrap();
                assert!(detail.contains("통합") && detail.contains("계약"));
            }
            assert_eq!(registry.list_entries(None).unwrap(), before);
        }
        let registered = controller
            .dispatch(
                "register_pclm",
                &json!({"name":"원천 표","db":db,"view":"계약"}),
            )
            .unwrap();
        assert_eq!(registered["ok"], true);
        let (key, item) = registry
            .find_identity_raw(&pclm_identity(db.to_str().unwrap(), "계약"))
            .unwrap()
            .unwrap();
        assert_eq!(item.kind, "pclm");
        assert_eq!(item.opts.len(), 2);
        assert_eq!(item.opts["view"], "계약");
        let stored_path = Path::new(item.opts["db"].as_str().unwrap());
        assert!(stored_path.is_absolute());
        assert_eq!(
            fs::canonicalize(stored_path).unwrap(),
            fs::canonicalize(db).unwrap()
        );
        for (action, status) in [("archive", "archived"), ("activate", "active")] {
            assert_eq!(
                controller.dispatch(action, &json!({"key":key})).unwrap()["ok"],
                true
            );
            assert_eq!(registry.load(&key).unwrap().status, status);
        }
        let declaration =
            json!({"name":"원천 표(여러면)","db":db,"view":"계약","views":["계약","통합"]});
        let pending = controller.dispatch("register_pclm", &declaration).unwrap();
        assert_eq!(pending["needs_confirm"], true);
        let mut confirmed = declaration;
        confirmed["confirm"] = json!(true);
        confirmed["basis"] = pending["basis"].clone();
        assert_eq!(
            controller.dispatch("register_pclm", &confirmed).unwrap()["ok"],
            true
        );
        assert_eq!(
            registry
                .find_identity_raw(&pclm_identity(db.to_str().unwrap(), "통합"))
                .unwrap()
                .unwrap()
                .0,
            key
        );
        confirmed["name"] = json!("낡은 변경");
        assert_eq!(
            controller.dispatch("register_pclm", &confirmed).unwrap()["ok"],
            false
        );
        assert_eq!(registry.load(&key).unwrap().name, "원천 표(여러면)");
        let other = db.with_file_name("other-contracts.db");
        fs::copy(db, &other).unwrap();
        assert_eq!(
            controller
                .dispatch(
                    "register_pclm",
                    &json!({"name":"다른 DB","db":other,"view":"통합"})
                )
                .unwrap()["ok"],
            true
        );
        let (other_key, _) = registry
            .find_identity_raw(&pclm_identity(other.to_str().unwrap(), "통합"))
            .unwrap()
            .unwrap();
        assert_ne!(other_key, key);
        assert!(
            registry
                .find_identity_raw(&pclm_identity(other.to_str().unwrap(), "계약"))
                .unwrap()
                .is_none()
        );
        registry.delete(&key).unwrap();
        registry.delete(&other_key).unwrap();
        assert_eq!(registry.list_entries(None).unwrap(), before);
    }
}
