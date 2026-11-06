//! One fixed TXT review session. Clipboard writes and session transitions share one lock.

use crate::action_registry::validate_dispatch;
use crate::job_registry::JobRegistry;
use crate::shell_settings::{ShellSettings, is_proportional_font};
use crate::workspace_switch::{GraphError, PushGate, ScreenController};
use chrono::{Local, NaiveDateTime};
use hwpx_filler::home_state::work_mode_label;
use hwpx_filler::job::Job;
use hwpx_filler::mapping::MappingProfile;
use hwpx_filler::mapping_state::{RowState, txt_live_profile_from_rows, txt_review_rows};
use hwpx_filler::text_render::python_repr;
use hwpx_filler::text_structure::{project_selected_text, scan_text_structure};
use hwpx_filler::txt_card::{gate_empty_fields, render_card};
use hwpx_filler::txt_card_diff::plain_edit;
use hwpx_filler::txt_card_edit::{
    CardEdits, CardView, card_view, editor_card, line_break, raw_card, source_text,
};
use hwpx_filler::txt_queue::TxtQueue;
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::Path;
use std::sync::{Arc, Mutex};

const NO_SELECTION: &str = "포함할 내용을 불러오지 못해 템플릿 원문 그대로 보여 줍니다. '문서 만들기'에서 템플릿을 다시 확인하세요.";
const NO_MATERIALIZER: &str = "구간 표기가 있는 템플릿의 복사 준비가 이 창에 연결되지 않았습니다. '문서 만들기'에서 다시 시작하세요.";
const DIFFERENT_MATERIALIZATION: &str =
    "화면에 보이는 문장과 실제로 만들어진 문서가 다릅니다. 전각 정렬을 끈 뒤 다시 복사하세요.";
type Selection = HashMap<String, HashSet<String>>;
pub(crate) type SelectionPort = dyn Fn(&str) -> Result<Selection, GraphError> + Send + Sync;
pub enum MaterializedTxt {
    Ready(String),
    Refused(String),
}
pub type MaterializePort = dyn Fn(&str, &Map<String, Value>, &str, NaiveDateTime) -> Result<MaterializedTxt, GraphError>
    + Send
    + Sync;
type Clock = dyn Fn() -> NaiveDateTime + Send + Sync;
type CopiedMilestone = dyn Fn() + Send + Sync;
fn tuple_repr(parts: Vec<String>) -> String {
    match parts.len() {
        0 => "()".into(),
        1 => format!("({},)", parts[0]),
        _ => format!("({})", parts.join(", ")),
    }
}
fn slice_repr(slice: &hwpx_filler::text_slice::TextSlice) -> String {
    let data = slice.to_dict();
    let fields = [
        "mode",
        "start",
        "length",
        "delimiter",
        "index",
        "open",
        "close",
        "count",
        "find",
        "replace",
        "on_missing",
    ];
    let parts = fields
        .iter()
        .map(|key| {
            let value = data.get(*key).cloned().unwrap_or_else(|| {
                if *key == "on_missing" {
                    json!("empty")
                } else {
                    Value::Null
                }
            });
            format!("{key}={}", python_repr(&value))
        })
        .collect::<Vec<_>>();
    format!("TextSlice({})", parts.join(", "))
}

struct Session {
    job: Option<Job>,
    mapping: MappingProfile,
    mapping_rows: Vec<RowState>,
    template: String,
    card_template: String,
    selection_note: String,
    marker_count: usize,
    records: Vec<Map<String, Value>>,
    source_rows: Vec<usize>,
    queue: TxtQueue,
    view: String,
    advance_after: bool,
    fullwidth: bool,
    font: String,
    last_copy: Option<Value>,
    copied_total: usize,
    stamped: bool,
    copied_rules: HashMap<usize, String>,
    edits: CardEdits,
}
impl Session {
    fn empty(font: String) -> Self {
        Self {
            job: None,
            mapping: MappingProfile::new("", Vec::new(), Map::new()).expect("empty mapping"),
            mapping_rows: Vec::new(),
            template: String::new(),
            card_template: String::new(),
            selection_note: String::new(),
            marker_count: 0,
            records: Vec::new(),
            source_rows: Vec::new(),
            queue: TxtQueue::new(0),
            view: "filled".into(),
            advance_after: false,
            fullwidth: false,
            font,
            last_copy: None,
            copied_total: 0,
            stamped: false,
            copied_rules: HashMap::new(),
            edits: CardEdits::default(),
        }
    }
    fn job(&self) -> Result<&Job, GraphError> {
        self.job
            .as_ref()
            .ok_or_else(|| "작업대 세션이 없습니다. 「문서 만들기」에서 다시 시작하세요.".into())
    }
    fn record(&self, index: Option<usize>) -> Map<String, Value> {
        index
            .and_then(|i| self.records.get(i))
            .cloned()
            .unwrap_or_default()
    }
    fn rules(&self) -> String {
        let rows = self
            .mapping_rows
            .iter()
            .map(|row| {
                tuple_repr(vec![
                    python_repr(&json!(row.template_field)),
                    python_repr(&json!(row.source)),
                    python_repr(&json!(row.field_type)),
                    python_repr(&json!(row.constant)),
                    python_repr(&json!(row.fmt)),
                    row.slice.as_ref().map_or_else(|| "None".into(), slice_repr),
                    if row.confirmed {
                        "True".into()
                    } else {
                        "False".into()
                    },
                ])
            })
            .collect::<Vec<_>>();
        format!(
            "({}, {})",
            tuple_repr(rows),
            if self.fullwidth { "True" } else { "False" }
        )
    }
    fn token(&self) -> String {
        self.queue.current().map_or_else(String::new, |cur| {
            format!("{cur}|{}", self.edits.signature(cur, &self.rules()))
        })
    }
    fn review(&self, index: Option<usize>) -> &'static str {
        let Some(index) = index else { return "todo" };
        let Some(copied) = self.copied_rules.get(&index) else {
            return "todo";
        };
        if *copied == self.edits.signature(index, &self.rules()) {
            "copied"
        } else {
            "recheck"
        }
    }
    fn card(&self, index: Option<usize>, now: NaiveDateTime) -> Result<CardView, GraphError> {
        self.job()?;
        let rendered = render_card(
            &self.card_template,
            &self.mapping,
            &self.record(index),
            false,
            Some(now),
        )?;
        Ok(card_view(
            &rendered,
            &self.mapping.declared_empty_fields().into_iter().collect(),
            &gate_empty_fields(&rendered.report, &self.mapping),
            self.edits.get(index),
            self.fullwidth,
        ))
    }
    fn copy_block(&self, materializer: bool) -> &'static str {
        if self.marker_count > 0 && !materializer {
            NO_MATERIALIZER
        } else if self.view != "filled" {
            "원문 보기에서는 복사하지 않습니다. 「채운 모습」으로 바꾼 뒤 복사하세요."
        } else {
            ""
        }
    }
    fn edit_or_navigate(
        &mut self,
        action: &str,
        payload: &Map<String, Value>,
        clock: &Clock,
    ) -> Result<(), GraphError> {
        self.job()?;
        match action {
            "step" => {
                let delta = payload["delta"]
                    .as_i64()
                    .ok_or("delta는 정수여야 합니다.")?;
                self.queue
                    .step(delta.try_into().map_err(|_| "delta 범위를 벗어났습니다.")?);
            }
            "set_current" => {
                let index = payload["index"]
                    .as_u64()
                    .ok_or("index는 음이 아닌 정수여야 합니다.")?;
                self.queue.set_current(Some(
                    index.try_into().map_err(|_| "index 범위를 벗어났습니다.")?,
                ));
            }
            "set_card_text" => {
                if self.view != "filled" {
                    return Err("원문 보기에서는 본문을 고치지 않습니다.".into());
                }
                let index = payload["index"]
                    .as_u64()
                    .ok_or("index는 음이 아닌 정수여야 합니다.")?
                    as usize;
                if index >= self.records.len() {
                    return Err(format!("없는 항목입니다: {index}").into());
                }
                let typed = payload["text"]
                    .as_str()
                    .ok_or("text는 문자열이어야 합니다.")?;
                let view = self.card(Some(index), clock())?;
                let edited = source_text(&view.text, typed, line_break(&self.template));
                self.edits.put(
                    index,
                    plain_edit(&view.text, &view.plain, &edited),
                    &view.plain_base,
                );
            }
            "revert_card" => {
                let index = payload["index"]
                    .as_u64()
                    .ok_or("index는 음이 아닌 정수여야 합니다.")?
                    as usize;
                self.edits.revert(index);
            }
            _ => unreachable!(),
        }
        Ok(())
    }
    fn guard(&self) -> Value {
        let Some(_) = self.job else {
            return json!({"armed":false,"lines":[]});
        };
        let mut lines = Vec::new();
        let copied = self.queue.copied_count();
        let total = self.records.len();
        if copied > 0 && copied < total {
            lines.push(format!(
                "복사 진행 {copied}/{total}건 — 나가면 이 진행은 사라집니다."
            ));
        }
        let recheck = self
            .copied_rules
            .keys()
            .filter(|i| self.review(Some(**i)) == "recheck")
            .count();
        if recheck > 0 {
            lines.push(format!(
                "규칙이 바뀌어 다시 확인해야 하는 항목 {recheck}건 — 나가면 그 표시가 사라집니다."
            ));
        }
        if !self.edits.is_empty() {
            lines.push(format!(
                "임시로 고친 항목 {}건 — 나가면 고친 내용은 사라집니다.",
                self.edits.len()
            ));
        }
        json!({"armed":!lines.is_empty(),"lines":lines})
    }
}

pub struct WorkbenchController {
    state: Mutex<Session>,
    registry: Arc<JobRegistry>,
    settings: Arc<ShellSettings>,
    push: PushGate,
    push_serial: Mutex<()>,
    clock: Arc<Clock>,
    selection: Option<Arc<SelectionPort>>,
    materialize: Option<Arc<MaterializePort>>,
    copied_milestone: Option<Arc<CopiedMilestone>>,
}
impl WorkbenchController {
    pub fn new(
        registry: Arc<JobRegistry>,
        settings: Arc<ShellSettings>,
        push: PushGate,
        selection: Option<Arc<SelectionPort>>,
        materialize: Option<Arc<MaterializePort>>,
    ) -> Result<Self, GraphError> {
        let font = settings.load_draft_target_font()?;
        Ok(Self {
            state: Mutex::new(Session::empty(font)),
            registry,
            settings,
            push,
            push_serial: Mutex::new(()),
            clock: Arc::new(|| Local::now().naive_local()),
            selection,
            materialize,
            copied_milestone: None,
        })
    }
    pub fn with_clock(mut self, clock: impl Fn() -> NaiveDateTime + Send + Sync + 'static) -> Self {
        self.clock = Arc::new(clock);
        self
    }
    pub fn with_copied_milestone(mut self, milestone: impl Fn() + Send + Sync + 'static) -> Self {
        self.copied_milestone = Some(Arc::new(milestone));
        self
    }
    pub fn open(&self, job: Job, rows: Vec<(usize, Map<String, Value>)>) -> Result<(), GraphError> {
        if job.work_mode() != "text_review_copy" {
            return Err("검토·복사 작업대는 TXT 작업만 받습니다.".into());
        }
        let text = fs::read_to_string(Path::new(&job.template_path))?;
        let scan = scan_text_structure(&text);
        let (card_template, note) = if scan.summary.markers == 0 {
            (text.clone(), String::new())
        } else {
            match self.selection.as_ref().map(|port| port(&job.name)) {
                Some(Ok(selection)) => match project_selected_text(&text, &scan, &selection) {
                    Ok(projected) => (projected, String::new()),
                    Err(_) => (text.clone(), NO_SELECTION.into()),
                },
                _ => (text.clone(), NO_SELECTION.into()),
            }
        };
        let font = self.settings.load_draft_target_font()?;
        let records = rows
            .iter()
            .map(|(_, record)| record.clone())
            .collect::<Vec<_>>();
        let mapping_rows = txt_review_rows(&text, &records, &job.mapping);
        let mapping = txt_live_profile_from_rows(&mapping_rows)?;
        let next = Session {
            job: Some(job),
            mapping,
            mapping_rows,
            template: text,
            card_template,
            selection_note: note,
            marker_count: scan.summary.markers,
            source_rows: rows.iter().map(|(index, _)| index + 1).collect(),
            records,
            queue: TxtQueue::new(0),
            ..Session::empty(font)
        };
        let count = next.records.len();
        let next = Session {
            queue: TxtQueue::new(count),
            ..next
        };
        *self
            .state
            .lock()
            .map_err(|_| "작업대 상태 잠금이 손상됐습니다.")? = next;
        self.push_snapshot()?;
        Ok(())
    }
    pub fn close(&self) -> Result<(), GraphError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| "작업대 상태 잠금이 손상됐습니다.")?;
        let font = state.font.clone();
        *state = Session::empty(font);
        drop(state);
        self.push_snapshot()?;
        Ok(())
    }
    pub fn close_flush_required(&self) -> Result<bool, GraphError> {
        Ok(self
            .state
            .lock()
            .map_err(|_| "작업대 상태 잠금이 손상됐습니다.")?
            .job
            .is_some())
    }
    fn push_snapshot(&self) -> Result<(), GraphError> {
        let _serial = self
            .push_serial
            .lock()
            .map_err(|_| "workbench push poisoned")?;
        self.push.push("workbench", &self.snapshot()?)?;
        Ok(())
    }
    fn snapshot(&self) -> Result<Value, GraphError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| "작업대 상태 잠금이 손상됐습니다.")?;
        let job_name = state.job.as_ref().map_or("", |job| job.name.as_str());
        let mut base = json!({"open":state.job.is_some(),"job_name":job_name,"mode_label":work_mode_label("txt"),
            "view":state.view,"target_font":state.font,
            "notice":{"text":state.selection_note,"level":if state.selection_note.is_empty(){"muted"}else{"warn"}}});
        if state.job.is_none() {
            base.as_object_mut().unwrap().extend(
                json!({"card":null,"template_path":"","guard":{"armed":false,"lines":[]},
                "revision":{"template":0,"binding":0},"total":0,"copied_count":0})
                .as_object()
                .unwrap()
                .clone(),
            );
            return Ok(base);
        }
        let cur = state.queue.current();
        let now = (self.clock)();
        let view = state.card(cur, now)?;
        let (shown, marks) = if state.view == "filled" {
            editor_card(&view.text, &view.marks)
        } else {
            let (raw, marks) = raw_card(&state.template);
            editor_card(&raw, &marks)
        };
        let order = state.queue.display_order().to_vec();
        let position = cur
            .and_then(|i| order.iter().position(|item| *item == i))
            .map_or(-1, |p| p as isize);
        let index_map=order.iter().map(|i|json!({"index":i,"row":state.source_rows.get(*i),
            "state":if Some(*i)==cur{"current"}else if state.queue.is_copied(*i){"copied"}else{"uncopied"},
            "recheck":state.review(Some(*i))=="recheck"})).collect::<Vec<_>>();
        let text_rev = state.edits.text_rev(cur, &view.plain_base);
        let text_key = format!(
            "{}|{}|{}|{}|{}",
            cur.map_or("None".into(), |i| i.to_string()),
            state.view,
            u8::from(state.fullwidth),
            state.edits.epoch,
            text_rev
        );
        let job = state.job.as_ref().unwrap();
        let card = json!({"index":cur,"has_current":cur.is_some(),"queue_degenerate":state.records.len()<=1,
            "position":position,"can_prev":position>0,"can_next":position>=0 && (position as usize)<order.len().saturating_sub(1),
            "source_row":cur.and_then(|i|state.source_rows.get(i)),"review_state":state.review(cur),"index_map":index_map,
            "uncopied_count":state.queue.uncopied().len(),"advance_after":state.advance_after,
            "text":shown,"marks":marks,"edited":cur.is_some_and(|i|state.edits.contains(i)),"text_key":text_key,
            "missing_fields":view.missing_fields,"empty_fields":view.empty_fields,
            "lint":{"proportional":is_proportional_font(&state.font),"space_run":view.space_run,"applied":state.fullwidth,
                "active":state.fullwidth || (is_proportional_font(&state.font) && view.space_run)},
            "last_copy":state.last_copy,"copied_total":state.copied_total,"copy_block":state.copy_block(self.materialize.is_some())});
        base.as_object_mut().unwrap().extend(json!({"card":card,"total":state.records.len(),"copied_count":state.queue.copied_count(),
            "is_complete":state.queue.is_complete(),"fullwidth":state.fullwidth,"template_path":job.template_path,
            "revision":{"template":job.template_revision,"binding":job.binding_revision},"guard":state.guard()}).as_object().unwrap().clone());
        Ok(base)
    }
    pub fn copy_to(
        &self,
        token: &str,
        write: impl FnOnce(&str) -> Result<(), GraphError>,
    ) -> Result<Value, GraphError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| "작업대 상태 잠금이 손상됐습니다.")?;
        if state.job.is_none() {
            return Ok(json!({"copied":false,"missing_fields":[],"empty_fields":[],
            "error":"작업대 세션이 없습니다."}));
        }
        let block = state.copy_block(self.materialize.is_some());
        if !block.is_empty() {
            return Ok(json!({"copied":false,"missing_fields":[],"empty_fields":[],"error":block}));
        }
        if token != state.token() {
            return Ok(json!({"copied":false,"stale":true,"missing_fields":[],"empty_fields":[]}));
        }
        let Some(cur) = state.queue.current() else {
            return Ok(json!({"copied":false,"missing_fields":[],"empty_fields":[]}));
        };
        let now = (self.clock)();
        let view = state.card(Some(cur), now)?;
        if let Some(reason) = self.materialization_refusal(&state, token, &view, now)? {
            return Ok(
                json!({"copied":false,"missing_fields":[],"empty_fields":[],"error":reason}),
            );
        }
        write(&view.text)?;
        let stamp_error = self.stamp_recent_use(&mut state)?;
        state.last_copy = Some(
            json!({"row":state.source_rows[cur],"missing_fields":view.missing_fields,
            "empty_fields":view.empty_fields,"stamp_error":stamp_error}),
        );
        state.copied_total += 1;
        let signature = state.edits.signature(cur, &state.rules());
        state.copied_rules.insert(cur, signature);
        state.queue.copy(Some(cur));
        if state.advance_after {
            state.queue.advance_to_next_uncopied();
        }
        state.queue.reconcile();
        let result = json!({"copied":true,"missing_fields":view.missing_fields,"empty_fields":view.empty_fields});
        drop(state);
        if let Some(milestone) = &self.copied_milestone {
            milestone();
        }
        self.push_snapshot()?;
        Ok(result)
    }
    fn materialization_refusal(
        &self,
        state: &Session,
        token: &str,
        view: &CardView,
        now: NaiveDateTime,
    ) -> Result<Option<String>, GraphError> {
        if state.marker_count == 0 {
            return Ok(None);
        }
        let materialize = self
            .materialize
            .as_ref()
            .expect("copy_block checked materialization");
        let work = &state.job()?.name;
        let record = state.record(state.queue.current());
        Ok(match materialize(work, &record, token, now) {
            Ok(MaterializedTxt::Ready(text)) => {
                (text != view.base).then(|| DIFFERENT_MATERIALIZATION.into())
            }
            Ok(MaterializedTxt::Refused(reason)) => Some(reason),
            Err(error) => Some(format!("문서를 만들지 못했습니다: {error}")),
        })
    }
    fn stamp_recent_use(&self, state: &mut Session) -> Result<String, GraphError> {
        if state.stamped {
            return Ok(String::new());
        }
        let name = &state.job()?.name;
        match self.registry.stamp_last_run(
            name,
            &(self.clock)().format("%Y-%m-%dT%H:%M:%S").to_string(),
            None,
        ) {
            Ok(job) => {
                state.stamped = true;
                state.job = Some(job);
                Ok(String::new())
            }
            Err(error) => Ok(error.to_string()),
        }
    }
    fn update(&self, action: &str, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| "작업대 상태 잠금이 손상됐습니다.")?;
        if action == "leave_guard" {
            return Ok(state.guard());
        }
        if action == "copy_precheck" {
            state.job()?;
            let cur = state.queue.current();
            let view = state.card(cur, (self.clock)())?;
            return Ok(
                json!({"token":state.token(),"row":cur.and_then(|i|state.source_rows.get(i)),
                "missing_fields":view.missing_fields,"empty_fields":view.empty_fields}),
            );
        }
        state.last_copy = None;
        let result = match action {
            "close" => {
                let font = state.font.clone();
                *state = Session::empty(font);
                json!({"ok":true})
            }
            "toggle_advance" => {
                state.advance_after = payload["value"]
                    .as_bool()
                    .ok_or("value는 bool이어야 합니다.")?;
                Value::Null
            }
            "set_view" => {
                let view = payload.get("view").and_then(Value::as_str).unwrap_or("");
                if !matches!(view, "filled" | "raw") {
                    return Err(format!("알 수 없는 보기: {}", python_repr(&json!(view))).into());
                }
                state.view = view.into();
                Value::Null
            }
            "set_target_font" => {
                let font = payload.get("font").and_then(Value::as_str).unwrap_or("");
                self.settings.save_draft_target_font(font)?;
                state.font = font.into();
                Value::Null
            }
            "set_fullwidth" => {
                state.fullwidth = payload["value"]
                    .as_bool()
                    .ok_or("value는 bool이어야 합니다.")?;
                Value::Null
            }
            "step" | "set_current" | "set_card_text" | "revert_card" => {
                state.edit_or_navigate(action, payload, self.clock.as_ref())?;
                Value::Null
            }
            _ => {
                return Err(
                    format!("알 수 없는 workbench 액션: {}", python_repr(&json!(action))).into(),
                );
            }
        };
        drop(state);
        self.push_snapshot()?;
        Ok(result)
    }
}
impl ScreenController for WorkbenchController {
    fn initial(&self) -> Result<Value, GraphError> {
        self.snapshot()
    }
    fn dispatch(&self, action: &str, payload: &Value) -> Result<Value, GraphError> {
        let object = validate_dispatch("workbench", action, payload)?;
        self.update(action, object)
    }
    fn close_guard_reason(&self) -> Result<Option<String>, GraphError> {
        let state = self
            .state
            .lock()
            .map_err(|_| "작업대 상태 잠금이 손상됐습니다.")?;
        Ok(state.guard()["armed"]
            .as_bool()
            .filter(|armed| *armed)
            .map(|_| "검토·복사 작업대의 복사 진행 또는 임시로 고친 본문".into()))
    }
    fn close_flush_required(&self) -> Result<bool, GraphError> {
        WorkbenchController::close_flush_required(self)
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::WorkbenchController;
    use super::{Clock, MaterializePort, MaterializedTxt, SelectionPort};
    use crate::job_registry::JobRegistry;
    use crate::locations::Locations;
    use crate::managed_generation_service::tests::RunFixture;
    use crate::shell_settings::ShellSettings;
    use crate::slot_configuration_product::SlotConfigurationProduct;
    use crate::workbench_materialization::{materialization_port, selection_port};
    use crate::workspace_switch::{ScreenController, WorkspaceGraph, WorkspaceSwitch};
    use hwpx_filler::job::Job;
    use hwpx_filler::mapping::{FieldMapping, MappingProfile};
    use serde_json::json;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::Condvar;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex};
    use std::time::{Duration, Instant};

    fn txt_workbench(
        fixture: &RunFixture,
        materializer: Option<Arc<MaterializePort>>,
        clock: Arc<Clock>,
    ) -> (Arc<WorkbenchController>, WorkspaceSwitch<()>) {
        let selections = Arc::new(SlotConfigurationProduct::new(
            &fixture.authority,
            fixture.jobs.clone(),
            || "2026-11-05T12:00:00".into(),
        ));
        let (controller, graph, _) = workbench_with_selection(
            fixture,
            Some(selection_port(selections, fixture.jobs.clone())),
            materializer,
            clock,
        );
        (controller, graph)
    }

    fn workbench_with_selection(
        fixture: &RunFixture,
        selection: Option<Arc<SelectionPort>>,
        materializer: Option<Arc<MaterializePort>>,
        clock: Arc<Clock>,
    ) -> (
        Arc<WorkbenchController>,
        WorkspaceSwitch<()>,
        Arc<AtomicUsize>,
    ) {
        let jobs = fixture.jobs.clone();
        let settings = Arc::new(ShellSettings::new(
            fixture.root.join("settings.json"),
            |_| {},
        ));
        let pushes = Arc::new(AtomicUsize::new(0));
        let count = pushes.clone();
        let captured = Arc::new(Mutex::new(None));
        let output = captured.clone();
        let graph = WorkspaceSwitch::new(
            Locations::new(&fixture.root, None),
            move |_, _| {
                count.fetch_add(1, Ordering::SeqCst);
                Ok(None)
            },
            move |home, push, token| {
                let clock = clock.clone();
                let controller = Arc::new(
                    WorkbenchController::new(
                        jobs.clone(),
                        settings.clone(),
                        push,
                        selection.clone(),
                        materializer.clone(),
                    )?
                    .with_clock(move || clock()),
                );
                *output.lock().unwrap() = Some(controller.clone());
                Ok(WorkspaceGraph::new(
                    home.map(PathBuf::from),
                    vec![("workbench".into(), controller as Arc<dyn ScreenController>)],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let controller = captured.lock().unwrap().clone().unwrap();
        (controller, graph, pushes)
    }

    fn review_job(fixture: &RunFixture, text: &str) -> Job {
        let path = fixture.root.join("review.txt");
        fs::write(&path, text).unwrap();
        let mut job = Job {
            name: "검토".into(),
            template_path: path.to_string_lossy().into_owned(),
            mapping: MappingProfile::new(
                "",
                vec![
                    FieldMapping::new("수신", "부서", "text", "", "", None).unwrap(),
                    FieldMapping::new("건명", "사업명", "text", "", "", None).unwrap(),
                ],
                Default::default(),
            )
            .unwrap(),
            ..Job::default()
        };
        fixture.jobs.save(&mut job, false).unwrap();
        job
    }

    fn review_rows() -> Vec<(usize, serde_json::Map<String, serde_json::Value>)> {
        [
            (2, json!({"부서":"회계과", "사업명":"복사기 임차"})),
            (0, json!({"부서":"총무과", "사업명":"책상 구매"})),
        ]
        .into_iter()
        .map(|(index, record)| (index, record.as_object().unwrap().clone()))
        .collect()
    }

    fn fixed_clock() -> Arc<Clock> {
        Arc::new(|| {
            chrono::NaiveDate::from_ymd_opt(2026, 11, 5)
                .unwrap()
                .and_hms_opt(12, 0, 0)
                .unwrap()
        })
    }

    fn copy_token(controller: &WorkbenchController) -> String {
        controller.dispatch("copy_precheck", &json!({})).unwrap()["token"]
            .as_str()
            .unwrap()
            .into()
    }

    #[test]
    fn session_freezes_inputs_preserves_previous_state_on_open_failure_and_queries_do_not_push() {
        let fixture = RunFixture::txt();
        let (controller, graph, pushes) = workbench_with_selection(
            &fixture,
            Some(Arc::new(|_| panic!("slotless selection lookup"))),
            None,
            fixed_clock(),
        );
        let closed = controller.initial().unwrap();
        assert_eq!(closed["open"], false);
        assert_eq!(closed["card"], serde_json::Value::Null);
        assert_eq!(closed["template_path"], "");
        assert!(!graph.close_flush_required().unwrap());
        assert!(controller.dispatch("step", &json!({"delta":1})).is_err());
        assert!(controller.dispatch("unknown", &json!({})).is_err());
        assert_eq!(
            controller.copy_to("", |_| panic!("closed copy")).unwrap()["copied"],
            false
        );
        let mut job = review_job(&fixture, "수신: {{수신}}\r\n건명: {{건명}}");
        let mut rows = review_rows();
        controller.open(job.clone(), rows.clone()).unwrap();
        let before = controller.initial().unwrap();
        assert_eq!(before["total"], 2);
        assert_eq!(before["card"]["text"], "수신: 회계과\n건명: 복사기 임차");
        assert_eq!(before["card"]["source_row"], 3);
        assert_eq!(before["template_path"], job.template_path);
        assert_eq!(before["notice"]["text"], "");
        rows[0].1.insert("부서".into(), json!("외부 수정"));
        rows.push((9, Default::default()));
        job.mapping.mappings.clear();
        fs::write(&job.template_path, "외부 수정").unwrap();
        assert_eq!(controller.initial().unwrap(), before);
        job.template_path = fixture.root.join("missing.txt").to_string_lossy().into();
        assert!(controller.open(job.clone(), rows.clone()).is_err());
        job.template_path = fixture.root.join("wrong.hwpx").to_string_lossy().into();
        assert!(controller.open(job, rows).is_err());
        assert_eq!(controller.initial().unwrap(), before);
        let count = pushes.load(Ordering::SeqCst);
        copy_token(&controller);
        assert_eq!(
            controller.dispatch("leave_guard", &json!({})).unwrap(),
            json!({"armed":false,"lines":[]})
        );
        assert_eq!(pushes.load(Ordering::SeqCst), count);
        controller.dispatch("step", &json!({"delta":1})).unwrap();
        assert_eq!(pushes.load(Ordering::SeqCst), count + 1);
        controller.dispatch("close", &json!({})).unwrap();
        assert_eq!(controller.initial().unwrap(), closed);
        assert!(!graph.close_flush_required().unwrap());
    }

    #[test]
    fn copies_preserve_frozen_navigation_stamp_once_and_recheck_only_changed_rules() {
        let fixture = RunFixture::txt();
        let (controller, _graph) = txt_workbench(&fixture, None, fixed_clock());
        let job = review_job(&fixture, "수신: {{수신}}\n건명: {{건명}}");
        controller.open(job, review_rows()).unwrap();
        assert!(fixture.jobs.load("검토").unwrap().last_run_at.is_empty());
        let token = copy_token(&controller);
        assert_eq!(
            controller
                .copy_to("stale", |_| panic!("stale copy"))
                .unwrap()["stale"],
            true
        );
        assert_eq!(controller.initial().unwrap()["copied_count"], 0);
        assert!(fixture.jobs.load("검토").unwrap().last_run_at.is_empty());
        assert_eq!(
            controller.copy_to(&token, |_| Ok(())).unwrap()["copied"],
            true
        );
        let card = &controller.initial().unwrap()["card"];
        assert_eq!(card["position"], 0);
        assert_eq!(card["can_prev"], false);
        assert_eq!(card["can_next"], true);
        assert_eq!(card["review_state"], "copied");
        assert_eq!(card["last_copy"]["row"], 3);
        assert_eq!(
            card["index_map"],
            json!([
                {"index":0,"row":3,"state":"current","recheck":false},
                {"index":1,"row":1,"state":"uncopied","recheck":false}
            ])
        );
        let stamped = fixture.jobs.load("검토").unwrap();
        assert_eq!(stamped.last_run_at, "2026-11-05T12:00:00");
        assert!(stamped.reviewed_rules.is_empty());
        let guard = controller.dispatch("leave_guard", &json!({})).unwrap();
        assert_eq!(
            guard["lines"],
            json!(["복사 진행 1/2건 — 나가면 이 진행은 사라집니다."])
        );
        // A subsequent copy must not overwrite a newer durable timestamp.
        fixture.jobs.stamp_last_run("검토", "later", None).unwrap();
        controller
            .dispatch("toggle_advance", &json!({"value":true}))
            .unwrap();
        controller.copy_to(&token, |_| Ok(())).unwrap();
        assert_eq!(controller.initial().unwrap()["card"]["index"], 1);
        assert_eq!(fixture.jobs.load("검토").unwrap().last_run_at, "later");
        controller
            .copy_to(&copy_token(&controller), |_| Ok(()))
            .unwrap();
        assert_eq!(controller.initial().unwrap()["card"]["index"], 1);
        assert_eq!(controller.initial().unwrap()["is_complete"], true);
        assert_eq!(
            controller.dispatch("leave_guard", &json!({})).unwrap()["armed"],
            false
        );
        let token = copy_token(&controller);
        controller
            .dispatch("set_fullwidth", &json!({"value":true}))
            .unwrap();
        assert_ne!(copy_token(&controller), token);
        assert_eq!(
            controller.initial().unwrap()["card"]["review_state"],
            "recheck"
        );
        assert_eq!(
            controller.dispatch("leave_guard", &json!({})).unwrap()["lines"],
            json!(["규칙이 바뀌어 다시 확인해야 하는 항목 2건 — 나가면 그 표시가 사라집니다."])
        );
        controller
            .copy_to(&copy_token(&controller), |_| Ok(()))
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["card"]["review_state"],
            "copied"
        );
        controller
            .dispatch("set_current", &json!({"index":0}))
            .unwrap();
        let card = &controller.initial().unwrap()["card"];
        assert_eq!(card["position"], 0);
        assert_eq!(card["last_copy"], serde_json::Value::Null);
        assert_eq!(card["index_map"][0]["recheck"], true);
        assert_eq!(card["index_map"][1]["state"], "copied");
        controller.dispatch("step", &json!({"delta":99})).unwrap();
        assert_eq!(controller.initial().unwrap()["card"]["can_next"], false);
    }

    #[test]
    fn failed_recent_use_write_keeps_successful_clipboard_and_reports_then_retries_stamp() {
        let fixture = RunFixture::txt();
        let (controller, _graph) = txt_workbench(&fixture, None, fixed_clock());
        let mut job = review_job(&fixture, "수신: {{수신}}");
        controller.open(job.clone(), review_rows()).unwrap();
        fixture.jobs.delete(&job.name).unwrap();
        assert_eq!(
            controller
                .copy_to(&copy_token(&controller), |text| {
                    assert_eq!(text, "수신: 회계과");
                    Ok(())
                })
                .unwrap()["copied"],
            true
        );
        let state = controller.initial().unwrap();
        assert_eq!(state["copied_count"], 1);
        assert!(
            !state["card"]["last_copy"]["stamp_error"]
                .as_str()
                .unwrap()
                .is_empty()
        );
        fixture.jobs.save(&mut job, false).unwrap();
        controller
            .copy_to(&copy_token(&controller), |_| Ok(()))
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["card"]["last_copy"]["stamp_error"],
            ""
        );
        assert_eq!(
            fixture.jobs.load(&job.name).unwrap().last_run_at,
            "2026-11-05T12:00:00"
        );
    }

    #[test]
    fn row_edits_keep_caret_identity_revert_explicitly_and_never_leak_to_other_rows() {
        let fixture = RunFixture::txt();
        let (controller, _graph) = txt_workbench(&fixture, None, fixed_clock());
        controller
            .open(review_job(&fixture, "수신:    {{수신}}"), review_rows())
            .unwrap();
        let before = controller.initial().unwrap()["card"].clone();
        for (font, proportional) in [("malgun", true), ("dotumche", false), ("gulimche", false)] {
            controller
                .dispatch("set_target_font", &json!({"font":font}))
                .unwrap();
            let snapshot = controller.initial().unwrap();
            assert_eq!(snapshot["target_font"], font);
            assert_eq!(snapshot["card"]["lint"]["proportional"], proportional);
            assert_eq!(snapshot["card"]["lint"]["active"], proportional);
            assert_eq!(snapshot["card"]["text"], before["text"]);
            assert_eq!(controller.settings.load_draft_target_font().unwrap(), font);
        }
        controller
            .copy_to(&copy_token(&controller), |_| Ok(()))
            .unwrap();
        let token = copy_token(&controller);
        controller
            .dispatch(
                "set_card_text",
                &json!({"index":0,"text":"수신:    회계과!"}),
            )
            .unwrap();
        let edited = controller.initial().unwrap()["card"].clone();
        assert_eq!(edited["edited"], true);
        assert_eq!(edited["text_key"], before["text_key"]);
        assert_eq!(edited["review_state"], "recheck");
        assert_eq!(edited["last_copy"], serde_json::Value::Null);
        assert_ne!(copy_token(&controller), token);
        assert_eq!(
            controller.close_guard_reason().unwrap().unwrap(),
            "검토·복사 작업대의 복사 진행 또는 임시로 고친 본문"
        );
        assert!(
            controller.dispatch("leave_guard", &json!({})).unwrap()["lines"]
                .as_array()
                .unwrap()
                .contains(&json!(
                    "임시로 고친 항목 1건 — 나가면 고친 내용은 사라집니다."
                ))
        );
        controller
            .dispatch("revert_card", &json!({"index":0}))
            .unwrap();
        let reverted = controller.initial().unwrap()["card"].clone();
        assert_eq!(reverted["edited"], false);
        assert_eq!(reverted["text"], before["text"]);
        assert_ne!(reverted["text_key"], edited["text_key"]);
        controller
            .dispatch(
                "set_card_text",
                &json!({"index":1,"text":"수신:    총무과!!"}),
            )
            .unwrap();
        assert_eq!(controller.initial().unwrap()["card"]["edited"], false);
        controller
            .dispatch("set_current", &json!({"index":1}))
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["card"]["text"],
            "수신:    총무과!!"
        );
        controller
            .dispatch("set_fullwidth", &json!({"value":true}))
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["card"]["text"],
            "수신:　　총무과!!"
        );
        controller
            .dispatch(
                "set_card_text",
                &json!({"index":1,"text":"수신:　　총무과!"}),
            )
            .unwrap();
        controller
            .dispatch("set_fullwidth", &json!({"value":false}))
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["card"]["text"],
            "수신:    총무과!"
        );
        controller
            .dispatch("set_fullwidth", &json!({"value":true}))
            .unwrap();
        controller
            .dispatch(
                "set_card_text",
                &json!({"index":1,"text":"수신:　　총무과"}),
            )
            .unwrap();
        assert_eq!(controller.initial().unwrap()["card"]["edited"], false);
        assert!(
            controller
                .dispatch("set_card_text", &json!({"index":99,"text":"x"}))
                .is_err()
        );
        controller
            .dispatch("set_view", &json!({"view":"raw"}))
            .unwrap();
        assert!(
            controller
                .dispatch("set_card_text", &json!({"index":1,"text":"x"}))
                .is_err()
        );
        assert!(
            controller
                .dispatch("set_view", &json!({"view":"unknown"}))
                .is_err()
        );
        let raw = controller.initial().unwrap()["card"].clone();
        assert_eq!(raw["text"], "수신:    {{수신}}");
        let blocked = controller
            .copy_to(&copy_token(&controller), |_| panic!("raw copy"))
            .unwrap();
        assert_eq!(blocked["copied"], false);
        assert_eq!(blocked["error"], raw["copy_block"]);
    }

    #[test]
    fn blank_gates_follow_all_occurrences_declared_constants_and_editor_utf16_crlf_coordinates() {
        let fixture = RunFixture::txt();
        let (controller, _graph) = txt_workbench(&fixture, None, fixed_clock());
        let job = review_job(
            &fixture,
            "😀 수신: {{수신}}\r\n참조: {{수신}}\r\n건명: {{건명}}\r\n",
        );
        let rows = vec![(
            0,
            json!({"부서":"","사업명":""}).as_object().unwrap().clone(),
        )];
        controller.open(job.clone(), rows.clone()).unwrap();
        assert_eq!(
            controller.initial().unwrap()["card"]["queue_degenerate"],
            true
        );
        let pre = controller.dispatch("copy_precheck", &json!({})).unwrap();
        assert_eq!(pre["empty_fields"].as_array().unwrap().len(), 2);
        let original = controller.initial().unwrap()["card"]["text"].clone();
        controller
            .dispatch("set_card_text", &json!({"index":0,"text":original}))
            .unwrap();
        assert_eq!(controller.initial().unwrap()["card"]["edited"], false);
        for (text, empty) in [
            ("😀 수신: 회계과\n참조: \n건명: \n", json!(["수신", "건명"])),
            ("😀 수신: 회계과\n참조: 총무과\n건명: \n", json!(["건명"])),
            (
                "😀 수신: 회계과\n참조: 총무과\n건명: 복사기 임차\n붙임 1부\n",
                json!([]),
            ),
        ] {
            controller
                .dispatch("set_card_text", &json!({"index":0,"text":text}))
                .unwrap();
            assert_eq!(
                controller.dispatch("copy_precheck", &json!({})).unwrap()["empty_fields"],
                empty
            );
        }
        let card = controller.initial().unwrap()["card"].clone();
        let units = card["text"]
            .as_str()
            .unwrap()
            .encode_utf16()
            .collect::<Vec<_>>();
        for mark in card["marks"].as_array().unwrap() {
            let text = String::from_utf16(
                &units[mark["start"].as_u64().unwrap() as usize
                    ..mark["end"].as_u64().unwrap() as usize],
            )
            .unwrap();
            assert!(
                ["회계과", "총무과", "복사기 임차"].contains(&text.as_str()),
                "{mark}: {text}"
            );
        }
        controller
            .copy_to(&copy_token(&controller), |text| {
                assert_eq!(
                    text,
                    "😀 수신: 회계과\r\n참조: 총무과\r\n건명: 복사기 임차\r\n붙임 1부\r\n"
                );
                Ok(())
            })
            .unwrap();
        controller
            .dispatch("set_view", &json!({"view":"raw"}))
            .unwrap();
        let raw = controller.initial().unwrap()["card"].clone();
        let units = raw["text"]
            .as_str()
            .unwrap()
            .encode_utf16()
            .collect::<Vec<_>>();
        for mark in raw["marks"].as_array().unwrap() {
            let token = String::from_utf16(
                &units[mark["start"].as_u64().unwrap() as usize
                    ..mark["end"].as_u64().unwrap() as usize],
            )
            .unwrap();
            assert_eq!(token, format!("{{{{{}}}}}", mark["name"].as_str().unwrap()));
        }
        let mut declared = job;
        declared.mapping.mappings[1].field_type = "const".into();
        declared.mapping.mappings[1].source.clear();
        controller.open(declared, rows).unwrap();
        assert_eq!(
            controller.dispatch("copy_precheck", &json!({})).unwrap()["empty_fields"],
            json!(["수신"])
        );
        let card = controller.initial().unwrap()["card"].clone();
        let mark = card["marks"]
            .as_array()
            .unwrap()
            .iter()
            .find(|mark| mark["name"] == "건명")
            .unwrap();
        assert_eq!(mark["kind"], "declared");
        assert_eq!(mark["start"], mark["end"]);
    }

    #[test]
    fn clock_changes_refresh_unedited_cards_without_replacing_an_active_edit() {
        let fixture = RunFixture::txt();
        let now = Arc::new(Mutex::new(fixed_clock()()));
        let clock = now.clone();
        let (controller, _graph) =
            txt_workbench(&fixture, None, Arc::new(move || *clock.lock().unwrap()));
        let mut job = review_job(&fixture, "시각: {{작성}}\n수신: {{수신}}");
        job.mapping
            .mappings
            .push(FieldMapping::new("작성", "", "today", "", "%H:%M", None).unwrap());
        controller.open(job, review_rows()).unwrap();
        let before = controller.initial().unwrap()["card"].clone();
        *now.lock().unwrap() += chrono::Duration::minutes(1);
        let after = controller.initial().unwrap()["card"].clone();
        assert_eq!(after["text"], "시각: 12:01\n수신: 회계과");
        assert_ne!(after["text_key"], before["text_key"]);
        *now.lock().unwrap() += chrono::Duration::minutes(1);
        let text = format!("{}!", after["text"].as_str().unwrap());
        controller
            .dispatch("set_card_text", &json!({"index":0,"text":text}))
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["card"]["text_key"],
            after["text_key"]
        );
        *now.lock().unwrap() += chrono::Duration::minutes(1);
        let edited = controller.initial().unwrap()["card"].clone();
        assert_eq!(edited["text"], text);
        assert_eq!(edited["text_key"], after["text_key"]);
    }

    #[test]
    fn selected_content_is_frozen_until_reopen_and_unavailable_selection_keeps_source_with_reason()
    {
        let fixture = RunFixture::txt();
        fixture.choose("o1");
        let (controller, _graph) = txt_workbench(&fixture, None, fixed_clock());
        let rows = vec![(0, json!({"열":"홍길동"}).as_object().unwrap().clone())];
        let job = fixture.jobs.load("생성").unwrap();
        controller.open(job.clone(), rows.clone()).unwrap();
        let before = controller.initial().unwrap();
        let text = before["card"]["text"].as_str().unwrap();
        assert!(
            text.contains("담당: 홍길동")
                && text.contains("계약서 홍길동")
                && text.ends_with("끝.\n")
        );
        assert!(!text.contains("견적서") && !text.contains("{{#"));
        assert_eq!(before["notice"]["text"], "");
        fixture.choose("o2");
        assert_eq!(controller.initial().unwrap(), before);
        controller
            .open(fixture.jobs.load("생성").unwrap(), rows.clone())
            .unwrap();
        let next = controller.initial().unwrap();
        let text = next["card"]["text"].as_str().unwrap();
        assert!(text.contains("견적서 홍길동") && !text.contains("계약서"));
        controller
            .dispatch("set_view", &json!({"view":"raw"}))
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["card"]["copy_block"],
            super::NO_MATERIALIZER
        );
        let failed: Arc<SelectionPort> = Arc::new(|_| Err("selection unavailable".into()));
        let empty: Arc<SelectionPort> = Arc::new(|_| Ok(Default::default()));
        for (broken, selection) in [(false, None), (false, Some(failed)), (true, Some(empty))] {
            if broken {
                fs::write(
                    &job.template_path,
                    "수신: {{성명}}\n{{#항목 첨부}}\n닫힘 없음",
                )
                .unwrap();
            }
            let (controller, _graph, _) =
                workbench_with_selection(&fixture, selection, None, fixed_clock());
            controller.open(job.clone(), rows.clone()).unwrap();
            let snap = controller.initial().unwrap();
            assert!(snap["card"]["text"].as_str().unwrap().contains("{{#항목"));
            assert_eq!(
                snap["notice"],
                json!({"text":super::NO_SELECTION,"level":"warn"})
            );
            controller
                .dispatch("set_view", &json!({"view":"raw"}))
                .unwrap();
            assert_eq!(controller.initial().unwrap()["notice"], snap["notice"]);
        }
    }

    #[test]
    fn clipboard_transaction_excludes_overlapping_copy_navigation_and_both_close_paths() {
        let fixture = RunFixture::txt();
        let (controller, _graph) = txt_workbench(&fixture, None, fixed_clock());
        let job = review_job(&fixture, "수신: {{수신}}");
        for operation in ["copy", "move", "close", "native_close"] {
            controller.open(job.clone(), review_rows()).unwrap();
            if operation == "copy" {
                controller
                    .dispatch("toggle_advance", &json!({"value":true}))
                    .unwrap();
            }
            let token = copy_token(&controller);
            let (start_tx, start_rx) = std::sync::mpsc::channel();
            let (attempt_tx, attempt_rx) = std::sync::mpsc::channel();
            let other = controller.clone();
            let other_token = token.clone();
            let worker = std::thread::spawn(move || {
                start_rx.recv_timeout(Duration::from_secs(3)).unwrap();
                attempt_tx.send(()).unwrap();
                match operation {
                    "copy" => other
                        .copy_to(&other_token, |_| panic!("unprechecked copy"))
                        .unwrap(),
                    "move" => other.dispatch("set_current", &json!({"index":1})).unwrap(),
                    "close" => other.dispatch("close", &json!({})).unwrap(),
                    _ => {
                        other.close().unwrap();
                        json!(null)
                    }
                }
            });
            let copied = controller
                .copy_to(&token, |text| {
                    assert_eq!(text, "수신: 회계과");
                    start_tx.send(()).unwrap();
                    attempt_rx.recv_timeout(Duration::from_secs(3)).unwrap();
                    assert!(
                        controller.state.try_lock().is_err(),
                        "copy released session before write completion"
                    );
                    Ok(())
                })
                .unwrap();
            let result = worker.join().unwrap();
            assert_eq!(copied["copied"], true);
            let snap = controller.initial().unwrap();
            match operation {
                "copy" => {
                    assert_eq!(result["stale"], true);
                    assert_eq!(snap["copied_count"], 1);
                    assert_eq!(snap["card"]["index"], 1);
                }
                "move" => {
                    assert_eq!(snap["card"]["index"], 1);
                    assert_eq!(snap["card"]["index_map"][0]["state"], "copied");
                    assert_eq!(snap["card"]["last_copy"], serde_json::Value::Null);
                }
                _ => assert_eq!(snap["open"], false),
            }
        }
    }

    #[test]
    fn sealed_txt_copy_matches_visible_mapping_and_preserves_edits_and_one_clock() {
        let fixture = RunFixture::txt();
        fixture.choose("o1");
        let port = materialization_port(fixture.authority.clone(), fixture.jobs.clone());
        let (controller, _graph) = txt_workbench(&fixture, Some(port.clone()), fixed_clock());
        for (kind, code, slice, value, expected) in [
            ("text", "", None, "대한상사", "대한상사"),
            ("text", "phone", None, "01012345678", "010-1234-5678"),
            ("date", "", None, "2026/7/17 18:05", "2026. 7. 17."),
            (
                "date",
                "datetime",
                None,
                "2026/7/17 18:05",
                "2026. 7. 17. 18:05",
            ),
            ("amount", "", None, "24750000", "24,750,000원"),
            ("amount", "{:,.2f}", None, "24750000", "24,750,000.00"),
            (
                "text",
                "",
                Some(json!({"mode":"split","delimiter":"-","index":1})),
                "R26-000",
                "R26",
            ),
            (
                "text",
                "",
                Some(json!({"mode":"before","delimiter":"-","on_missing":"keep"})),
                "R26-000",
                "R26",
            ),
        ] {
            let mut job = fixture.jobs.load("생성").unwrap();
            let field = job
                .mapping
                .mappings
                .iter_mut()
                .find(|field| field.template_field == "선택")
                .unwrap();
            field.field_type = kind.into();
            field.fmt = code.into();
            field.slice = hwpx_filler::text_slice::text_slice_from_payload(slice.as_ref()).unwrap();
            fixture.jobs.save(&mut job, true).unwrap();
            controller
                .open(
                    job,
                    vec![(0, json!({"열":value}).as_object().unwrap().clone())],
                )
                .unwrap();
            let base = controller.initial().unwrap()["card"]["text"]
                .as_str()
                .unwrap()
                .to_owned();
            assert!(base.contains(&format!("계약서 {expected}\n")), "{base}");
            let mut written = String::new();
            let result = controller
                .copy_to(&copy_token(&controller), |text| {
                    written = text.into();
                    Ok(())
                })
                .unwrap();
            assert_eq!(result["copied"], true, "{result}");
            assert_eq!(written, base);
            let edited = base.replace("끝.", "끝. (수정)");
            controller
                .dispatch("set_card_text", &json!({"index":0,"text":edited}))
                .unwrap();
            assert_eq!(
                controller
                    .copy_to(&copy_token(&controller), |text| {
                        assert_eq!(text, edited);
                        Ok(())
                    })
                    .unwrap()["copied"],
                true
            );
        }
        let mut job = fixture.jobs.load("생성").unwrap();
        let field = job
            .mapping
            .mappings
            .iter_mut()
            .find(|field| field.template_field == "성명")
            .unwrap();
        field.field_type = "today".into();
        field.source.clear();
        field.fmt = "%Y.%m.%d".into();
        fixture.jobs.save(&mut job, true).unwrap();
        let ticks = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let tick = ticks.clone();
        let clock = Arc::new(move || {
            fixed_clock()()
                + chrono::Duration::days(
                    tick.fetch_add(1, std::sync::atomic::Ordering::SeqCst) as i64
                )
        });
        let (dated, _dated_graph) = txt_workbench(&fixture, Some(port), clock);
        dated
            .open(
                job,
                vec![(0, json!({"열":"R26-000"}).as_object().unwrap().clone())],
            )
            .unwrap();
        let token = copy_token(&dated);
        let expected = fixed_clock()()
            + chrono::Duration::days(ticks.load(std::sync::atomic::Ordering::SeqCst) as i64);
        let result = dated
            .copy_to(&token, |text| {
                assert!(text.starts_with(&format!("성명:    {}\n", expected.format("%Y.%m.%d"))));
                Ok(())
            })
            .unwrap();
        assert_eq!(result["copied"], true, "{result}");
    }

    #[test]
    fn sealed_txt_refusals_preserve_clipboard_and_session_even_after_editing() {
        let fixture = RunFixture::txt();
        let real_port = materialization_port(fixture.authority.clone(), fixture.jobs.clone());
        let (controller, _graph) = txt_workbench(&fixture, Some(real_port.clone()), fixed_clock());
        let open = |controller: &WorkbenchController| {
            controller
                .open(
                    fixture.jobs.load("생성").unwrap(),
                    vec![(0, json!({"열":"홍길동"}).as_object().unwrap().clone())],
                )
                .unwrap()
        };
        let refused = |controller: &WorkbenchController, reason: &str| {
            let result = controller
                .copy_to(&copy_token(controller), |_| {
                    panic!("refusal changed clipboard")
                })
                .unwrap();
            assert_eq!(result["copied"], false, "{result}");
            assert!(
                result["error"].as_str().unwrap().contains(reason),
                "{result}"
            );
            assert!(controller.close_flush_required().unwrap());
            assert_eq!(controller.initial().unwrap()["copied_count"], 0);
        };
        open(&controller);
        refused(&controller, "SLOT_CONFIGURATION_INCOMPLETE");
        fixture.choose("o1");
        open(&controller);
        controller
            .dispatch("set_fullwidth", &json!({"value":true}))
            .unwrap();
        refused(&controller, super::DIFFERENT_MATERIALIZATION);
        let base = controller.initial().unwrap()["card"]["text"]
            .as_str()
            .unwrap()
            .to_owned();
        controller
            .dispatch("set_card_text", &json!({"index":0,"text":base + "수정"}))
            .unwrap();
        refused(&controller, super::DIFFERENT_MATERIALIZATION);
        let refusal_port: Arc<MaterializePort> =
            Arc::new(|_, _, _, _| Ok(MaterializedTxt::Refused("stale Plan".into())));
        let error_port: Arc<MaterializePort> =
            Arc::new(|_, _, _, _| Err("저장소가 사라졌다".into()));
        for (port, reason) in [
            (None, super::NO_MATERIALIZER),
            (Some(refusal_port), "stale Plan"),
            (Some(error_port), "저장소가 사라졌다"),
        ] {
            let (controller, _graph) = txt_workbench(&fixture, port, fixed_clock());
            open(&controller);
            refused(&controller, reason);
        }
    }

    #[test]
    fn delayed_workbench_push_cannot_overwrite_a_newer_view() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/workbench-controller-tests")
            .join(uuid::Uuid::new_v4().to_string());
        fs::create_dir_all(&root).unwrap();
        let registry = Arc::new(
            JobRegistry::new(root.join("jobs"), {
                let root = root.clone();
                move || root.clone()
            })
            .unwrap(),
        );
        let settings = Arc::new(ShellSettings::new(root.join("settings.json"), |_| {}));
        let held = Arc::new((Mutex::new((false, false)), Condvar::new()));
        let delivered = Arc::new(Mutex::new(Vec::<String>::new()));
        let saved = Arc::new(Mutex::new(None::<Arc<WorkbenchController>>));
        let gate = held.clone();
        let out = delivered.clone();
        let capture = saved.clone();
        let _graph = WorkspaceSwitch::new(
            Locations::new(&root, None),
            move |_, snapshot| {
                let view = snapshot["view"].as_str().unwrap_or("").to_owned();
                if view == "raw" {
                    let (lock, ready) = &*gate;
                    let mut state = lock.lock().unwrap();
                    state.0 = true;
                    ready.notify_all();
                    while !state.1 {
                        state = ready.wait(state).unwrap();
                    }
                }
                out.lock().unwrap().push(view);
                Ok(None)
            },
            move |home, push, token| {
                let controller = Arc::new(WorkbenchController::new(
                    registry.clone(),
                    settings.clone(),
                    push,
                    None,
                    None,
                )?);
                *capture.lock().unwrap() = Some(controller.clone());
                Ok(WorkspaceGraph::new(
                    home.map(PathBuf::from),
                    vec![("workbench".into(), controller as Arc<dyn ScreenController>)],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let workbench = saved.lock().unwrap().as_ref().unwrap().clone();
        let first = {
            let workbench = workbench.clone();
            std::thread::spawn(move || {
                workbench
                    .dispatch("set_view", &json!({"view":"raw"}))
                    .unwrap()
            })
        };
        let (lock, ready) = &*held;
        let state = lock.lock().unwrap();
        let (state, timeout) = ready
            .wait_timeout_while(state, Duration::from_secs(3), |state| !state.0)
            .unwrap();
        assert!(!timeout.timed_out(), "first workbench push was not held");
        drop(state);
        let second = {
            let workbench = workbench.clone();
            std::thread::spawn(move || {
                workbench
                    .dispatch("set_view", &json!({"view":"filled"}))
                    .unwrap()
            })
        };
        let deadline = Instant::now() + Duration::from_secs(3);
        while workbench.state.lock().unwrap().view != "filled" {
            assert!(
                Instant::now() < deadline,
                "second workbench mutation did not run"
            );
            std::thread::yield_now();
        }
        let mut state = lock.lock().unwrap();
        state.1 = true;
        ready.notify_all();
        drop(state);
        first.join().unwrap();
        second.join().unwrap();
        assert_eq!(*delivered.lock().unwrap(), ["raw", "filled"]);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn fixed_txt_rows_copy_after_write_and_reject_stale_token() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .join(format!("workbench-owner-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let template = root.join("source.txt");
        fs::write(&template, "안녕 {{수신}}\r\n").unwrap();
        let registry = Arc::new(
            JobRegistry::new(root.join("jobs"), {
                let templates = root.clone();
                move || templates.clone()
            })
            .unwrap(),
        );
        let settings = Arc::new(ShellSettings::new(root.join("settings.json"), |_| {}));
        let captured: Arc<Mutex<Option<Arc<WorkbenchController>>>> = Arc::new(Mutex::new(None));
        let output = captured.clone();
        let registry_for_graph = registry.clone();
        let settings_for_graph = settings.clone();
        let graph = WorkspaceSwitch::new(
            Locations::new(&root, None),
            |_, _| Ok(None),
            move |home, gate, token| {
                let controller = Arc::new(WorkbenchController::new(
                    registry_for_graph.clone(),
                    settings_for_graph.clone(),
                    gate,
                    None,
                    Some(Arc::new(|_, _, _, _| {
                        panic!("slotless copy invoked materializer")
                    })),
                )?);
                *output.lock().unwrap() = Some(controller.clone());
                Ok(WorkspaceGraph::new(
                    home.map(PathBuf::from),
                    vec![("workbench".into(), controller as Arc<dyn ScreenController>)],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let controller = captured.lock().unwrap().as_ref().unwrap().clone();
        let mut job = Job {
            name: "TXT".into(),
            template_path: template.to_string_lossy().into_owned(),
            ..Job::default()
        };
        registry.save(&mut job, false).unwrap();
        let first = json!({"수신":"홍길동"}).as_object().unwrap().clone();
        let second = json!({"수신":"김철수"}).as_object().unwrap().clone();
        controller.open(job, vec![(4, first), (9, second)]).unwrap();
        assert!(graph.close_flush_required().unwrap());
        let initial = controller.initial().unwrap();
        assert_eq!(initial["card"]["text"], "안녕 홍길동\n");
        assert_eq!(initial["card"]["source_row"], 5);
        controller
            .dispatch("toggle_advance", &json!({"value":true}))
            .unwrap();
        let token = controller.dispatch("copy_precheck", &json!({})).unwrap()["token"]
            .as_str()
            .unwrap()
            .to_owned();
        assert!(
            controller
                .copy_to(&token, |_| Err("clipboard refused".into()))
                .is_err()
        );
        assert_eq!(controller.initial().unwrap()["copied_count"], 0);
        let copied = Arc::new(Mutex::new(String::new()));
        let written = copied.clone();
        assert_eq!(
            controller
                .copy_to(&token, move |text| {
                    *written.lock().unwrap() = text.into();
                    Ok(())
                })
                .unwrap()["copied"],
            true
        );
        assert_eq!(*copied.lock().unwrap(), "안녕 홍길동\r\n");
        assert_eq!(controller.initial().unwrap()["card"]["source_row"], 10);
        assert_eq!(
            controller
                .copy_to(&token, |_| panic!("stale token wrote clipboard"))
                .unwrap()["stale"],
            true
        );
        controller.dispatch("close", &json!({})).unwrap();
        assert!(!graph.close_flush_required().unwrap());
        let path = root.canonicalize().unwrap();
        assert!(
            path.starts_with(
                Path::new(env!("CARGO_MANIFEST_DIR"))
                    .canonicalize()
                    .unwrap()
                    .parent()
                    .unwrap()
                    .parent()
                    .unwrap()
            )
        );
        fs::remove_dir_all(path).unwrap();
    }
}
