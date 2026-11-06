//! The shipped lesson curriculum and its IO-free guidance position.

use serde::Deserialize;
use serde_json::{Map, Value, json};
use std::sync::LazyLock;

pub const CURRICULUM: u64 = 7;
const ROUND_KEYS: [&str; 5] = [
    "reviewed_rows",
    "copied_rows",
    "trial_options",
    "generated",
    "applied",
];
const UI_PRESS_EVENTS: [&str; 7] = [
    "create_form_opened",
    "trial_dock_opened",
    "sheet_checked",
    "slice_closed",
    "screen_entered_job",
    "binding_menu_opened",
    "template_menu_opened",
];

#[derive(Clone, Debug, Deserialize)]
pub struct Beat {
    pub id: String,
    pub title: String,
    pub body: String,
    pub screen: Option<String>,
    pub target: Option<String>,
    pub event: Option<String>,
    pub placement: String,
    pub entry_screen: Option<String>,
    pub arg: String,
}

impl Beat {
    pub fn view(&self) -> Value {
        json!({
            "id": self.id, "title": self.title, "body": self.body,
            "mode": if self.event.is_some() { "action" } else { "explain" },
            "screen": self.screen, "entry_screen": self.entry_screen,
            "target": self.target, "arg": self.arg,
            "press": self.event.as_deref().is_some_and(is_ui_press_event),
            "transient": self.target.as_deref() == Some("menu-item"),
            "placement": self.placement, "can_next": self.event.is_none(),
            "range": Value::Null,
        })
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct Lesson {
    pub id: String,
    pub title: String,
    pub description: String,
    pub beats: Vec<Beat>,
}

pub static LESSONS: LazyLock<Vec<Lesson>> = LazyLock::new(|| {
    serde_json::from_str(include_str!("tutorial_lessons.json"))
        .expect("bundled tutorial curriculum must be valid")
});

pub fn lesson(id: &str) -> Option<&'static Lesson> {
    LESSONS.iter().find(|item| item.id == id)
}

pub fn is_ui_press_event(event: &str) -> bool {
    UI_PRESS_EVENTS.contains(&event)
}

#[derive(Clone, Debug)]
pub struct LessonProgress {
    pub invite_seen: bool,
    pub first_launch: bool,
    pub entry_visible: bool,
    pub selected: Option<String>,
    pub records: Map<String, Value>,
    pub active: bool,
    pub result: Option<Value>,
}

impl LessonProgress {
    pub fn new(raw: &Value, first_launch: bool) -> Self {
        let valid = raw.get("version") == Some(&json!(1));
        let raw = if valid { raw } else { &Value::Null };
        let selected = raw
            .get("selected")
            .and_then(Value::as_str)
            .filter(|id| lesson(id).is_some())
            .map(str::to_owned);
        let current = raw.get("curriculum") == Some(&json!(CURRICULUM));
        let mut records = Map::new();
        for item in LESSONS.iter() {
            let Some(entry) = raw.get("records").and_then(|v| v.get(&item.id)) else {
                continue;
            };
            let Some(checkpoint) = entry.get("checkpoint").and_then(Value::as_u64) else {
                continue;
            };
            if checkpoint as usize > item.beats.len()
                || entry.get("checkpoint").is_some_and(Value::is_boolean)
            {
                continue;
            }
            let context = entry
                .get("context")
                .filter(|v| v.is_object() && current)
                .cloned()
                .unwrap_or_else(|| json!({}));
            records.insert(
                item.id.clone(),
                json!({"checkpoint": if current { checkpoint } else { 0 },
                       "completed": entry.get("completed") == Some(&Value::Bool(true)),
                       "context": context}),
            );
        }
        Self {
            invite_seen: raw.get("invite_seen") == Some(&Value::Bool(true)),
            first_launch,
            entry_visible: true,
            selected,
            records,
            active: false,
            result: None,
        }
    }

    pub fn progress(&self) -> Value {
        json!({"version": 1, "curriculum": CURRICULUM,
               "invite_seen": self.invite_seen, "selected": self.selected,
               "records": self.records})
    }

    pub fn record(&mut self, id: &str) -> Result<&mut Value, String> {
        if lesson(id).is_none() {
            return Err(format!("알 수 없는 튜토리얼 과정: {id}"));
        }
        Ok(self
            .records
            .entry(id.to_owned())
            .or_insert_with(|| json!({"checkpoint": 0, "completed": false, "context": {}})))
    }

    pub fn checkpoint(&self, id: &str) -> usize {
        self.records
            .get(id)
            .and_then(|v| v.get("checkpoint"))
            .and_then(Value::as_u64)
            .unwrap_or(0) as usize
    }

    pub fn context(&self) -> Option<&Map<String, Value>> {
        self.records
            .get(self.selected.as_deref()?)?
            .get("context")?
            .as_object()
    }

    pub fn context_mut(&mut self) -> Option<&mut Map<String, Value>> {
        self.records
            .get_mut(self.selected.as_deref()?)?
            .get_mut("context")?
            .as_object_mut()
    }

    pub fn later(&mut self) {
        self.invite_seen = true;
        self.active = false;
    }

    pub fn select(&mut self, id: &str) -> Result<(), String> {
        self.record(id)?;
        self.selected = Some(id.to_owned());
        self.invite_seen = true;
        self.active = self.checkpoint(id) < lesson(id).expect("checked lesson").beats.len();
        self.result = None;
        Ok(())
    }

    pub fn pause(&mut self) {
        self.active = false;
    }

    pub fn restart(&mut self, id: &str) -> Result<(), String> {
        let entry = self.record(id)?;
        entry["checkpoint"] = json!(0);
        if let Some(context) = entry.get_mut("context").and_then(Value::as_object_mut) {
            for key in ROUND_KEYS {
                context.remove(key);
            }
        }
        self.selected = Some(id.to_owned());
        self.active = true;
        self.result = None;
        Ok(())
    }

    pub fn beat(&self) -> Option<&'static Beat> {
        let id = self.selected.as_deref()?;
        lesson(id)?.beats.get(self.checkpoint(id))
    }

    pub fn rewind(&mut self, beat_id: &str) -> bool {
        let Some(id) = self.selected.clone() else {
            return false;
        };
        let Some(index) =
            lesson(&id).and_then(|item| item.beats.iter().position(|beat| beat.id == beat_id))
        else {
            return false;
        };
        if index >= self.checkpoint(&id) {
            return false;
        }
        self.records.get_mut(&id).expect("selected record")["checkpoint"] = json!(index);
        true
    }

    fn advance(&mut self) -> bool {
        let Some(id) = self.selected.clone() else {
            return false;
        };
        let count = lesson(&id).expect("selected lesson").beats.len();
        let index = self.checkpoint(&id) + 1;
        let entry = self.records.get_mut(&id).expect("selected record");
        entry["checkpoint"] = json!(index);
        if index == count {
            entry["completed"] = Value::Bool(true);
            self.active = false;
        }
        true
    }

    pub fn next_step(&mut self) -> Result<(), String> {
        if !self.active || self.beat().is_none_or(|beat| beat.event.is_some()) {
            return Err("이 단계는 실제 동작을 마친 뒤에 넘어갈 수 있습니다.".into());
        }
        self.advance();
        Ok(())
    }

    pub fn observed(&mut self, event: &str, context: Option<&Map<String, Value>>) -> bool {
        if !self.active || self.beat().and_then(|beat| beat.event.as_deref()) != Some(event) {
            return false;
        }
        if let (Some(context), Some(current)) = (context, self.context_mut()) {
            current.extend(context.clone());
        }
        self.advance()
    }

    pub fn snapshot(&mut self) -> Value {
        // Python's scenario projection materializes each missing record before persistence.
        for item in LESSONS.iter() {
            self.record(&item.id).expect("bundled lesson");
        }
        let selected_lesson = self.selected.as_deref().and_then(lesson);
        let checkpoint = self.selected.as_deref().map_or(0, |id| self.checkpoint(id));
        let stages: Vec<Value> = selected_lesson
            .into_iter()
            .flat_map(|lesson| lesson.beats.iter().enumerate())
            .map(|(index, beat)| {
                json!({"id": beat.id, "title": beat.title,
                       "status": if index < checkpoint { "done" } else if index == checkpoint { "current" } else { "pending" }})
            })
            .collect();
        let scenarios: Vec<Value> = LESSONS
            .iter()
            .enumerate()
            .map(|(index, item)| {
                let entry = self.records.get(&item.id);
                json!({"id": item.id, "title": item.title,
                       "description": item.description, "recommended": index == 0,
                       "completed": entry.and_then(|v| v.get("completed")) == Some(&Value::Bool(true)),
                       "checkpoint": self.checkpoint(&item.id), "step_count": item.beats.len()})
            })
            .collect();
        json!({
            "kind": "tutorial-lessons/v1",
            "invitation": {"visible": self.first_launch && !self.invite_seen && self.entry_visible,
                           "title": "문서나르미 첫 안내",
                           "body": "예제 서식과 데이터로 첫 문서를 만드세요. 시작할 때 연습 사본을 준비합니다."},
            "entry": {"visible": self.entry_visible},
            "active": self.active,
            "paused": !self.active && selected_lesson.is_some() &&
                      selected_lesson.is_some_and(|lesson| checkpoint < lesson.beats.len()),
            "scenario_id": self.selected, "checkpoint": checkpoint,
            "beat_count": selected_lesson.map_or(0, |lesson| lesson.beats.len()),
            "stages": stages, "scenarios": scenarios,
            "beat": if self.active { self.beat().map(Beat::view) } else { None },
            "recovery": Value::Null,
            "resources": {"ready": false, "summary": ""},
            "show_result": self.result.is_some(), "result": self.result,
            "copy": {
                "start": "예제로 시작", "later": "나중에", "pause": "안내 일시정지",
                "resume": "계속하기", "skip": "건너뛰기", "restart": "처음부터 안내",
                "next": "다음", "next_lesson": "다음 연습",
                "cleanup": "연습 파일 정리", "reset": "학습 기록 초기화",
                "cleanup_confirm": "아래 목록에서 삭제로 표시한 연습 사본만 지웁니다. 수정한 파일과 작업이 참조하는 파일은 그대로 둡니다.",
                "reset_confirm": "모든 과정의 학습 위치와 완료 기록을 지웁니다. 연습 파일, 사용자 파일, 저장한 작업과 생성 결과는 그대로 둡니다.",
                "open_tutorial": "튜토리얼", "close": "닫기", "choose_scenario": "과정 고르기",
                "practice": "연습 중", "exit": "연습 종료", "return": "현재 단계로 돌아가기"
            }
        })
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{CURRICULUM, LESSONS, LessonProgress, UI_PRESS_EVENTS};
    use serde_json::json;
    use std::collections::{HashMap, HashSet};

    #[test]
    fn guidance_resumes_only_current_curriculum_and_requires_observed_action() {
        assert_lesson_anchor_contract();
        let first = &LESSONS[0];
        assert_eq!(first.id, "first_hwpx");
        let raw = json!({"version":1,"curriculum": CURRICULUM-1,
                         "selected":"first_hwpx", "records": {"first_hwpx": {
                             "checkpoint": 3, "completed": true, "context": {"home":"old"}}}});
        let mut progress = LessonProgress::new(&raw, true);
        assert_eq!(progress.checkpoint("first_hwpx"), 0);
        assert_eq!(progress.record("first_hwpx").unwrap()["context"], json!({}));
        progress.select("first_hwpx").unwrap();
        assert_eq!(progress.snapshot()["beat"]["id"], "intro");
        assert_eq!(progress.records.len(), LESSONS.len());
        progress.next_step().unwrap();
        assert_eq!(progress.snapshot()["beat"]["id"], "new_job");
        assert!(progress.next_step().is_err());
        assert!(!progress.observed("wrong_event", None));
        assert!(progress.observed("new_job_opened", None));
        assert_eq!(progress.snapshot()["checkpoint"], 2);
    }

    fn assert_lesson_anchor_contract() {
        let source = include_str!("../../../frontend/src/tutorial/anchors.ts");
        let body = source
            .split_once("Object.freeze({")
            .unwrap()
            .1
            .split_once("});")
            .unwrap()
            .0;
        let anchors = body
            .lines()
            .filter_map(|line| {
                let (key, selector) = line.trim().split_once(':')?;
                Some((
                    key.trim_matches('"').to_owned(),
                    selector
                        .trim()
                        .trim_end_matches(',')
                        .trim_matches('"')
                        .to_owned(),
                ))
            })
            .collect::<HashMap<_, _>>();
        let mut ui_events = HashSet::new();
        for lesson in LESSONS.iter() {
            let mut beat_ids = HashSet::new();
            for beat in &lesson.beats {
                assert!(beat_ids.insert(&beat.id), "{}:{}", lesson.id, beat.id);
                if let Some(target) = &beat.target {
                    let selector = anchors.get(target).unwrap_or_else(|| {
                        panic!("{}:{} has no anchor {target}", lesson.id, beat.id)
                    });
                    assert!(
                        !selector.contains(','),
                        "{}:{} has multiple anchors",
                        lesson.id,
                        beat.id
                    );
                    assert_eq!(
                        selector.contains("{arg}"),
                        !beat.arg.is_empty(),
                        "{}:{} argument mismatch",
                        lesson.id,
                        beat.id
                    );
                } else {
                    assert!(
                        beat.event.is_none() && beat.arg.is_empty(),
                        "{}:{} has no control",
                        lesson.id,
                        beat.id
                    );
                }
                if let Some(event) = &beat.event
                    && UI_PRESS_EVENTS.contains(&event.as_str())
                {
                    ui_events.insert(event.clone());
                }
            }
        }
        assert_eq!(
            ui_events,
            UI_PRESS_EVENTS
                .into_iter()
                .map(str::to_owned)
                .collect::<HashSet<_>>()
        );
        for target in [
            "results",
            "data-label",
            "wb-copy",
            "txt-review",
            "save-template",
        ] {
            assert!(
                anchors.contains_key(target),
                "missing finish target {target}"
            );
        }
    }
}
