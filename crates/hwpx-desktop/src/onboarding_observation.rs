//! Product command returns that may advance, rewind, or pause the current tutorial beat.

use super::*;
use serde_json::Map;

/// One product command return as the observer received it.
struct ProductReturn<'a> {
    screen: &'a str,
    action: &'a str,
    payload: &'a Value,
    result: &'a Value,
}

impl OnboardingController {
    fn rewind_unmet_inputs(
        &self,
        state: &mut OnboardingState,
        resources: &RuntimeResources,
    ) -> Result<bool, GraphError> {
        let Some(beat) = state.progress.beat() else {
            return Ok(false);
        };
        if beat.screen.as_deref() == Some("authoring")
            && !crate::onboarding_match_authoring::practice_template_open(state, resources)?
        {
            let first = authoring_restart_beat(state);
            return Ok(state.progress.rewind(first));
        }
        let Some(expected) = editor_lesson_inputs(state.progress.selected.as_deref()) else {
            return Ok(false);
        };
        if beat.screen.as_deref() != Some("editor") {
            return Ok(false);
        }
        let context = state.progress.context().ok_or("연습 기록이 없습니다.")?;
        let asset = |name: &str| {
            context
                .get("assets")
                .and_then(|assets| assets.get(name))
                .and_then(|entry| entry.get("path"))
                .and_then(Value::as_str)
                .unwrap_or("")
        };
        let editor = resources.editor.snapshot()?;
        if editor["template_path"] != asset(expected.0) {
            return Ok(state.progress.rewind("template"));
        }
        if editor["data_path"] != asset("공고목록.xlsx") || editor["data_sheet"] != expected.1 {
            return Ok(state.progress.rewind("data"));
        }
        Ok(false)
    }

    fn observe_product(
        &self,
        token: &Value,
        screen: &str,
        action: &str,
        payload: &Value,
        result: &Value,
    ) -> Result<(), GraphError> {
        let mut state = self.state()?;
        if !state.accepts_product_token(token) {
            return Ok(());
        }
        let graph = self.graph()?;
        let resources = graph.active_resources()?;
        if declined_result(result) {
            return Ok(());
        }
        let source = resources
            .authoring
            .active_facts()?
            .and_then(|facts| facts["source_path"].as_str().map(PathBuf::from));
        state.note_practice_save(screen, action, result, source.as_deref())?;
        let (ready, reason) = state.resources();
        if !ready {
            state.recovery = Some(reason);
            state.progress.pause();
            state.persist()?;
            return self.emit_state(state);
        }
        let before = state.progress.context().cloned();
        let rewound = self.rewind_unmet_inputs(&mut state, &resources)?;
        let Some(event) = state.progress.beat().and_then(|beat| beat.event.clone()) else {
            return Ok(());
        };
        if crate::tutorial_lessons::is_ui_press_event(&event) {
            if rewound {
                state.persist()?;
                return self.emit_state(state);
            }
            return Ok(());
        }
        let returned = ProductReturn {
            screen,
            action,
            payload,
            result,
        };
        self.observe_event(state, &resources, &event, before, rewound, &returned)
    }

    /// Matches the beat's backend event, then persists and pushes whatever moved.
    fn observe_event(
        &self,
        mut state: MutexGuard<'_, OnboardingState>,
        resources: &RuntimeResources,
        event: &str,
        before: Option<Map<String, Value>>,
        rewound: bool,
        returned: &ProductReturn<'_>,
    ) -> Result<(), GraphError> {
        let context = crate::onboarding_product::match_event(
            &mut state,
            resources,
            event,
            returned.screen,
            returned.action,
            returned.payload,
            returned.result,
        )?;
        let advanced = context
            .as_ref()
            .is_some_and(|context| state.progress.observed(event, Some(context)))
            || rewound;
        let context_changed = state.progress.context() != before.as_ref();
        if advanced || context_changed {
            state.persist()?;
        }
        if advanced || context_changed || refreshes_guide(returned.action) {
            return self.emit_state(state);
        }
        Ok(())
    }

    /// Releases the state lock before pushing the snapshot taken under it.
    fn emit_state(&self, mut state: MutexGuard<'_, OnboardingState>) -> Result<(), GraphError> {
        let snapshot = self.snapshot(&mut state)?;
        drop(state);
        self.emit(&snapshot)
    }
}

/// A refused, unconfirmed, or overwrite-pending return never advances a beat.
fn declined_result(result: &Value) -> bool {
    result.get("ok") == Some(&Value::Bool(false))
        || result.get("needs_confirm") == Some(&Value::Bool(true))
        || result.get("needs_overwrite") == Some(&Value::Bool(true))
}

/// The template and data sheet an editor lesson expects before its mapping beats.
fn editor_lesson_inputs(lesson: Option<&str>) -> Option<(&'static str, &'static str)> {
    match lesson {
        Some("first_hwpx") => Some(("물품 구매입찰 공고.hwpx", "공고")),
        Some("contract_txt") => Some(("낙찰자 선정 및 계약체결 안내.txt", "계약")),
        _ => None,
    }
}

/// Selection-changing actions refresh the guide even when no beat moved.
fn refreshes_guide(action: &str) -> bool {
    matches!(
        action,
        "use_library_template"
            | "select_job"
            | "prefer_work"
            | "toggle_record"
            | "set_all"
            | "set_none"
    )
}

impl ProductObserver for OnboardingController {
    fn token(&self) -> Value {
        self.observation_token().unwrap_or(Value::Null)
    }

    fn returned(&self, token: &Value, screen: &str, action: &str, payload: &Value, result: &Value) {
        if screen == "tutorial" || token.is_null() {
            return;
        }
        if let Err(error) = self.observe_product(token, screen, action, payload, result) {
            (self.alert)(format!("튜토리얼 제품 관찰 실패: {error}"));
            if let Ok(mut state) = self.state() {
                if let Err(recovery) = state.observation_failed(&error.to_string()) {
                    (self.alert)(format!("튜토리얼 복구 상태 저장 실패: {recovery}"));
                }
                let snapshot = match self.snapshot(&mut state) {
                    Ok(snapshot) => snapshot,
                    Err(error) => {
                        (self.alert)(format!("튜토리얼 복구 상태 관찰 실패: {error}"));
                        return;
                    }
                };
                drop(state);
                if let Err(push) = self.emit(&snapshot) {
                    (self.alert)(format!("튜토리얼 복구 상태 전달 실패: {push}"));
                }
            }
        }
    }
}
