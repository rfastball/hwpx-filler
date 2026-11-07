//! Headless product walks for the eight shipped lessons. The action fixture keeps
//! only portable commands and checkpoint expectations from the former Python owner.

use hwpx_desktop::generation_gate::GenerationGate;
use hwpx_desktop::live_graph::LiveGraph;
use hwpx_desktop::locations::Locations;
use hwpx_desktop::native_methods::NativeMethods;
use hwpx_desktop::onboarding_controller::OnboardingController;
use hwpx_desktop::tutorial_lessons::{LESSONS, is_ui_press_event, lesson};
use hwpx_desktop::tutorial_workspace::TutorialWorkspace;
use hwpx_desktop::workspace_runtime::{RuntimeBuilder, RuntimeResources};
use hwpx_desktop::workspace_switch::{ScreenController, WorkspaceSwitch};
use serde_json::{Value, json};
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::Arc;

struct Walk {
    graph: Arc<LiveGraph<RuntimeResources>>,
    native: NativeMethods,
    home: PathBuf,
    lesson: String,
    session: String,
    preview_content: Value,
    configuration: Value,
    change_token: Value,
}

impl Walk {
    fn new(home: PathBuf, lesson: &str) -> Self {
        let locations = Locations::new(Path::new("C:/unused"), Some(home.clone().into_os_string()));
        let onboarding = Arc::new(OnboardingController::new(
            locations.tutorial_workspace_root(),
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../examples/tutorial"),
            TutorialWorkspace::first_launch_candidate(&home),
            |message| panic!("tutorial alert: {message}"),
        ));
        let builder = Arc::new(RuntimeBuilder {
            locations: locations.clone(),
            onboarding: onboarding.clone(),
            generation: Arc::new(GenerationGate::new()),
            alert: Arc::new(|message| panic!("runtime alert: {message}")),
        });
        let switch = WorkspaceSwitch::new(
            locations,
            |_, _| Ok(None),
            move |home, push, token| builder.build(home, push, token),
        )
        .unwrap();
        let graph = Arc::new(LiveGraph::new(switch));
        onboarding.bind_graph(&graph).unwrap();
        let native = NativeMethods::new(graph.clone())
            .unwrap()
            .with_onboarding(onboarding);
        Self {
            graph,
            native,
            home,
            lesson: lesson.into(),
            session: String::new(),
            preview_content: Value::Null,
            configuration: Value::Null,
            change_token: Value::Null,
        }
    }

    fn tutorial(&self) -> Value {
        self.graph.initial("tutorial").unwrap()
    }

    fn select(&mut self) {
        let lesson = self.lesson.clone();
        self.dispatch("tutorial", "select", json!({"scenario_id":lesson}));
    }

    fn press(&mut self) {
        let snapshot = self.tutorial();
        let anchor = snapshot["beat"]["target"].as_str().unwrap();
        self.dispatch(
            "tutorial",
            "observe_ui",
            json!({"scenario_id":self.lesson,"checkpoint":snapshot["checkpoint"],"anchor":anchor}),
        );
    }

    fn open_practice_txt(&mut self) {
        self.dispatch("editor", "new_session", json!({}));
        self.press();
        let path = self.asset("낙찰자 선정 및 계약체결 안내.txt");
        let result = self
            .native
            .call("open_authoring_document", &[path, json!(true)], || {
                panic!("clipboard not expected")
            })
            .unwrap();
        self.session = result["session_id"].as_str().unwrap().into();
    }

    fn context(&self) -> Value {
        let data = fs::read(self.home.join("tutorial_workspace/progress.json")).unwrap();
        serde_json::from_slice::<Value>(&data).unwrap()["records"][&self.lesson]["context"].clone()
    }

    fn asset(&self, name: &str) -> Value {
        self.context()["assets"][name]["path"].clone()
    }

    fn resolve(&self, value: &Value) -> Value {
        match value {
            Value::Object(map) if map.len() == 1 => {
                if let Some(name) = map.get("asset").and_then(Value::as_str) {
                    return self.asset(name);
                }
                if let Some(name) = map.get("pool").and_then(Value::as_str) {
                    return self.context()["pool_keys"][name].clone();
                }
                if map.contains_key("derived_data") {
                    return self.context()["derived_data_path"].clone();
                }
                if map.contains_key("applied_template") {
                    return self.graph.initial("job").unwrap()["template_path"].clone();
                }
                if map.contains_key("preview_content") {
                    return self.preview_content.clone();
                }
                if map.contains_key("change_token") {
                    return self.change_token.clone();
                }
                Value::Object(
                    map.iter()
                        .map(|(key, value)| (key.clone(), self.resolve(value)))
                        .collect(),
                )
            }
            Value::Array(values) => Value::Array(values.iter().map(|v| self.resolve(v)).collect()),
            Value::Object(map) => Value::Object(
                map.iter()
                    .map(|(key, value)| (key.clone(), self.resolve(value)))
                    .collect(),
            ),
            _ => value.clone(),
        }
    }

    fn dispatch(&mut self, screen: &str, action: &str, mut payload: Value) -> Value {
        if screen == "authoring" {
            payload["session_id"] = json!(self.session);
        }
        if action == "select_slot_option" {
            let slot_label = payload["slot"].as_str().unwrap();
            let option_label = payload["option"].as_str().unwrap();
            let slot = self.configuration["projection"]["slots"]
                .as_array()
                .unwrap()
                .iter()
                .find(|slot| slot["display_text"] == slot_label)
                .unwrap_or_else(|| panic!("slot {slot_label} missing"));
            let option = slot["options"]
                .as_array()
                .unwrap()
                .iter()
                .find(|option| option["display_text"] == option_label)
                .unwrap_or_else(|| panic!("option {option_label} missing"));
            payload = json!({
                "configuration_token": self.configuration["new_configuration_token"],
                "slot_id": slot["slot_id"], "option_id": option["option_id"],
                "request_id": payload["request_id"]
            });
        }
        let result = self
            .graph
            .dispatch(screen, action, &payload)
            .unwrap_or_else(|error| panic!("{screen}.{action}: {error}"));
        assert!(
            result.get("__hwpx_dispatch_rejection_v1__").is_none(),
            "{screen}.{action}: {result}"
        );
        if action == "open_slot_configuration" {
            self.configuration = result["current_view"].clone();
        }
        if action == "preview" {
            self.preview_content = result["content"].clone();
        }
        if action == "prepare_apply" {
            self.change_token = result["change_token"].clone();
        }
        result
    }

    fn run(&mut self, event: &Value) -> Value {
        let method = event["method"].as_str().unwrap();
        let args = self.resolve(&event["args"]);
        let args = args.as_array().unwrap();
        match method {
            "dispatch" => self.dispatch(
                args[0].as_str().unwrap(),
                args[1].as_str().unwrap(),
                args[2].clone(),
            ),
            "generate" => {
                let out = self.home.join("out");
                fs::create_dir_all(&out).unwrap();
                self.graph
                    .active_resources()
                    .unwrap()
                    .job
                    .set_output_folder(out.to_str().unwrap())
                    .unwrap();
                self.native
                    .call(method, args, || panic!("clipboard not expected"))
                    .unwrap()
            }
            "pick_data_file" => {
                let selected = self.context()["derived_data_path"]
                    .as_str()
                    .unwrap()
                    .to_owned();
                self.native
                    .selected_data_file(args[0].as_str().unwrap(), Path::new(&selected))
                    .unwrap()
            }
            "copy_clipboard" => {
                let token = self.graph.product_token();
                let resources = self.graph.active_resources().unwrap();
                let precheck = resources
                    .workbench
                    .dispatch("copy_precheck", &json!({}))
                    .unwrap();
                let copy_token = precheck["token"].as_str().unwrap();
                let result = resources.workbench.copy_to(copy_token, |_| Ok(())).unwrap();
                if result["copied"] == true {
                    self.graph.returned_product(
                        token.as_ref(),
                        "workbench",
                        "copy_clipboard",
                        &json!({"token": copy_token}),
                        &result,
                    );
                }
                result
            }
            "open_authoring_document" => {
                let result = self
                    .native
                    .call(method, args, || panic!("clipboard not expected"))
                    .unwrap();
                self.session = result["session_id"].as_str().unwrap().into();
                result
            }
            _ => self
                .native
                .call(method, args, || panic!("clipboard not expected"))
                .unwrap(),
        }
    }
}

fn test_home(tag: &str) -> PathBuf {
    let repo = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap();
    let parent = repo.join(".cache").join("tutorial-walk-reentry");
    fs::create_dir_all(&parent).unwrap();
    parent.join(format!("{tag}-{}", uuid::Uuid::new_v4()))
}

fn remove_test_home(home: &Path) {
    let resolved = home.canonicalize().unwrap();
    let parent = home.parent().unwrap().canonicalize().unwrap();
    assert!(resolved.starts_with(&parent));
    fs::remove_dir_all(resolved).unwrap();
}

fn make_dirty_practice(walk: &mut Walk) -> String {
    walk.select();
    walk.open_practice_txt();
    let content = fs::read_to_string(
        walk.asset("낙찰자 선정 및 계약체결 안내.txt")
            .as_str()
            .unwrap(),
    )
    .unwrap();
    walk.dispatch(
        "authoring",
        "update",
        json!({"revision":0,"content":format!("{content}\n덧붙임")}),
    );
    walk.graph
        .active_resources()
        .unwrap()
        .authoring
        .close_guard_reason()
        .unwrap()
        .unwrap()
}

#[test]
fn resumed_lessons_rewind_transient_menu_and_refuse_damaged_or_dirty_work() {
    for item in LESSONS.iter() {
        for (index, beat) in item.beats.iter().enumerate() {
            if beat.target.as_deref() == Some("menu-item") {
                assert!(index > 0, "{}:{}", item.id, beat.id);
                assert!(
                    item.beats[index - 1]
                        .event
                        .as_deref()
                        .is_some_and(is_ui_press_event)
                );
            }
        }
    }

    let home = test_home("menu");
    let mut walk = Walk::new(home.clone(), "field_trial");
    walk.select();
    walk.dispatch("editor", "new_session", json!({}));
    walk.press();
    assert_eq!(walk.tutorial()["beat"]["id"], "open_edit");
    assert_eq!(walk.tutorial()["beat"]["transient"], true);
    let checkpoint = walk.tutorial()["checkpoint"].as_u64().unwrap();
    for stale in [
        json!({"scenario_id":"field_trial","checkpoint":checkpoint,"anchor":"template-more"}),
        json!({"scenario_id":"field_trial","checkpoint":checkpoint-1,"anchor":"menu-item"}),
        json!({"scenario_id":"option_apply","checkpoint":checkpoint,"anchor":"menu-item"}),
    ] {
        walk.dispatch("tutorial", "observe_ui_closed", stale);
        assert_eq!(walk.tutorial()["beat"]["id"], "open_edit");
    }
    walk.dispatch(
        "tutorial",
        "observe_ui_closed",
        json!({
            "scenario_id":"field_trial","checkpoint":checkpoint,"anchor":"menu-item"
        }),
    );
    assert_eq!(walk.tutorial()["beat"]["id"], "open_menu");
    walk.press();
    assert_eq!(walk.tutorial()["beat"]["id"], "open_edit");
    walk.dispatch("tutorial", "pause", json!({}));
    walk.dispatch("tutorial", "resume", json!({}));
    assert_eq!(walk.tutorial()["beat"]["id"], "open_menu");
    walk.press();
    drop(walk);
    let mut reopened = Walk::new(home.clone(), "field_trial");
    reopened.dispatch("tutorial", "resume", json!({}));
    assert_eq!(reopened.tutorial()["beat"]["id"], "open_menu");
    drop(reopened);
    remove_test_home(&home);

    let home = test_home("resuggest");
    let mut walk = Walk::new(home.clone(), "replace_data");
    walk.select();
    let progress_path = home.join("tutorial_workspace").join("progress.json");
    let mut progress: Value = serde_json::from_slice(&fs::read(&progress_path).unwrap()).unwrap();
    let index = lesson("replace_data")
        .unwrap()
        .beats
        .iter()
        .position(|beat| beat.id == "resuggest")
        .unwrap();
    progress["records"]["replace_data"]["checkpoint"] = json!(index);
    fs::write(&progress_path, serde_json::to_vec(&progress).unwrap()).unwrap();
    drop(walk);
    let mut reopened = Walk::new(home.clone(), "replace_data");
    reopened.dispatch("tutorial", "resume", json!({}));
    assert_eq!(reopened.tutorial()["beat"]["id"], "menu");
    drop(reopened);
    remove_test_home(&home);

    for damaged in [false, true] {
        let home = test_home(if damaged { "damaged" } else { "deleted" });
        let mut walk = Walk::new(home.clone(), "blank_values");
        walk.select();
        let name = walk.context()["job_name"].as_str().unwrap().to_owned();
        walk.dispatch("library", "select_work", json!({"name":name}));
        assert_eq!(walk.tutorial()["checkpoint"], 1);
        let path = walk.graph.active_resources().unwrap().jobs.path_for(&name);
        if damaged {
            fs::write(path, b"{").unwrap();
        } else {
            fs::remove_file(path).unwrap();
        }
        walk.dispatch("tutorial", "pause", json!({}));
        assert!(
            walk.graph
                .dispatch("tutorial", "resume", &json!({}))
                .is_err()
        );
        let snap = walk.tutorial();
        assert_eq!(snap["resources"]["ready"], false);
        assert_eq!(
            snap["recovery"]["body"],
            "연습 파일이 준비되지 않았습니다. 예제로 시작하세요."
        );
        walk.dispatch("tutorial", "select", json!({"scenario_id":"blank_values"}));
        assert_eq!(walk.tutorial()["paused"], true);
        walk.dispatch("tutorial", "restart", json!({"scenario_id":"blank_values"}));
        assert_eq!(walk.tutorial()["resources"]["ready"], true);
        drop(walk);
        remove_test_home(&home);
    }

    let home = test_home("dirty");
    let mut walk = Walk::new(home.clone(), "field_trial");
    let reason = make_dirty_practice(&mut walk);
    let preflight = walk.dispatch(
        "tutorial",
        "preflight",
        json!({
            "screen":"authoring","action":"select","scenario_id":"first_hwpx"
        }),
    );
    assert_eq!(preflight["needs_confirm"], true);
    assert_eq!(
        preflight["confirm_text"],
        format!("지금 연습의 다음 진행 상태가 사라집니다:\n\n• {reason}")
    );
    let restart = walk.dispatch(
        "tutorial",
        "preflight",
        json!({
            "screen":"authoring","action":"restart","scenario_id":"field_trial"
        }),
    );
    assert_eq!(restart["needs_confirm"], true);
    for payload in [
        json!({"screen":"authoring","action":"resume"}),
        json!({"screen":"authoring","action":"select","scenario_id":"field_trial"}),
    ] {
        assert_eq!(
            walk.dispatch("tutorial", "preflight", payload)["needs_confirm"],
            false
        );
    }
    assert!(
        walk.graph
            .dispatch("tutorial", "select", &json!({"scenario_id":"first_hwpx"}))
            .is_err()
    );
    assert_eq!(
        walk.graph
            .active_resources()
            .unwrap()
            .authoring
            .close_guard_reason()
            .unwrap(),
        Some(reason)
    );
    let confirmed = walk.dispatch(
        "tutorial",
        "preflight",
        json!({"screen":"authoring","action":"select","scenario_id":"first_hwpx"}),
    );
    walk.dispatch(
        "tutorial",
        "select",
        json!({
            "scenario_id":"first_hwpx","transition_token":confirmed["transition_token"]
        }),
    );
    assert_eq!(walk.tutorial()["scenario_id"], "first_hwpx");
    drop(walk);
    remove_test_home(&home);

    let home = test_home("dirty-exit");
    let mut walk = Walk::new(home.clone(), "field_trial");
    make_dirty_practice(&mut walk);
    walk.dispatch("tutorial", "exit", json!({}));
    assert!(walk.graph.practice_home().unwrap().is_none());
    let asked = walk.dispatch(
        "tutorial",
        "preflight",
        json!({
            "screen":"job","action":"start","scenario_id":"first_hwpx"
        }),
    );
    assert_eq!(asked["needs_confirm"], true);
    drop(walk);
    remove_test_home(&home);
}

#[test]
fn all_eight_lessons_walk_product_graph_and_isolate_output() {
    let repo = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap();
    let parent = repo.join(".cache").join("tutorial-walk-owner");
    fs::create_dir_all(&parent).unwrap();
    let tutorial_source = repo.join("examples").join("tutorial");
    let source_hwpx = fs::read(tutorial_source.join("물품 구매입찰 공고.hwpx")).unwrap();
    let source_txt = fs::read(tutorial_source.join("낙찰자 선정 및 계약체결 안내.txt")).unwrap();
    let root = parent.join(uuid::Uuid::new_v4().to_string());
    let scenarios: Value =
        serde_json::from_str(include_str!("fixtures/tutorial_walk_actions.json")).unwrap();
    assert_eq!(scenarios.as_array().unwrap().len(), 8);
    for scenario in scenarios.as_array().unwrap() {
        let lesson = scenario["lesson"].as_str().unwrap();
        let home = root.join(lesson);
        let mut walk = Walk::new(home.clone(), lesson);
        if lesson == "first_hwpx" {
            let user = walk.graph.active_resources().unwrap();
            user.job
                .set_output_folder(home.join("사용자 결과").to_str().unwrap())
                .unwrap();
            user.workbench
                .dispatch("set_target_font", &json!({"font":"dotumche"}))
                .unwrap();
            walk.native
                .call("set_theme", &[json!("light")], || {
                    panic!("clipboard not expected")
                })
                .unwrap();
        }
        let mut current = walk.tutorial();
        for (index, event) in scenario["events"].as_array().unwrap().iter().enumerate() {
            assert_eq!(
                current["checkpoint"], event["before"],
                "{lesson}:{index} before"
            );
            assert_eq!(
                current["beat"]["id"], event["beat"],
                "{lesson}:{index} beat"
            );
            let result = walk.run(event);
            assert!(
                result
                    .get("error")
                    .is_none_or(|error| error.is_null() || error == ""),
                "{lesson}:{index} {result}"
            );
            let after = walk.tutorial();
            assert_eq!(
                after["checkpoint"], event["after"],
                "{lesson}:{index} after {result}"
            );
            current = after;
        }
        let final_state = current;
        assert_eq!(
            final_state["checkpoint"], final_state["beat_count"],
            "{lesson}"
        );
        assert_eq!(final_state["active"], false, "{lesson}");
        assert_eq!(
            final_state["result"]["count"], scenario["count"],
            "{lesson}"
        );
        assert_eq!(
            final_state["result"]["next_scenario_id"], scenario["next"],
            "{lesson}"
        );
        assert!(
            walk.graph
                .practice_home()
                .unwrap()
                .unwrap()
                .starts_with(&home)
        );
        if lesson == "first_hwpx" {
            let documents = final_state["result"]["documents"].as_array().unwrap();
            assert_eq!(documents.len(), 3);
            for document in documents {
                let path = PathBuf::from(document["path"].as_str().unwrap());
                assert!(path.starts_with(home.join("out")));
                let blob = fs::read(&path).unwrap();
                let mut archive = zip::ZipArchive::new(std::io::Cursor::new(&blob)).unwrap();
                let mut section = String::new();
                archive
                    .by_name("Contents/section0.xml")
                    .unwrap()
                    .read_to_string(&mut section)
                    .unwrap();
                assert!(!section.contains("{{게시일}}"));
                assert!(!section.contains("{{낙찰하한율}}"));
                let package = hwpx_core::package::HwpxPackage::from_bytes(
                    &blob,
                    hwpx_core::package::PackageLimits::default(),
                )
                .unwrap();
                let values = hwpx_filler::fields::field_values(&package).unwrap();
                assert!(
                    values
                        .iter()
                        .any(|(name, value)| name == "게시일" && value == "2026. 10.")
                );
                for (field, expected) in [
                    ("계약담당자", "홍길동"),
                    ("계약담당 전화번호", "042-000-0000"),
                    ("계약담당 팩스번호", "0505-000-0000"),
                ] {
                    assert!(
                        values
                            .iter()
                            .any(|(name, value)| name == field && value == expected)
                    );
                }
                for field in ["입찰개시일시", "입찰마감일시", "개찰일시", "등록마감일시"]
                {
                    assert!(values.iter().any(|(name, value)| {
                        name == field && value.starts_with("2026. 10. ") && value.contains(':')
                    }));
                }
            }
        } else if lesson == "replace_data" {
            assert_eq!(
                walk.graph.initial("job").unwrap()["data_row"]["path"],
                walk.context()["derived_data_path"]
            );
        } else if lesson == "blank_values" {
            let card = walk.graph.initial("workbench").unwrap()["card"].clone();
            let marks = card["marks"].as_array().unwrap();
            assert!(
                marks
                    .iter()
                    .any(|mark| mark["name"] == "단위" && mark["kind"] == "declared")
            );
            assert!(
                marks
                    .iter()
                    .any(|mark| mark["name"] == "계약보증금" && mark["kind"] == "blank")
            );
            assert!(
                !card["empty_fields"]
                    .as_array()
                    .unwrap()
                    .contains(&json!("단위"))
            );
            assert!(
                card["empty_fields"]
                    .as_array()
                    .unwrap()
                    .contains(&json!("계약보증금"))
            );
        } else if lesson == "field_trial" {
            let saved = fs::read_to_string(
                walk.asset("낙찰자 선정 및 계약체결 안내.txt")
                    .as_str()
                    .unwrap(),
            )
            .unwrap();
            assert!(saved.contains("{{재배정기한}}"));
        } else if lesson == "option_apply" {
            let saved = fs::read_to_string(
                walk.asset("낙찰자 선정 및 계약체결 안내.txt")
                    .as_str()
                    .unwrap(),
            )
            .unwrap();
            assert!(saved.contains("{{#항목 예산재배정"));
            assert!(saved.contains("{{#선택 안내포함"));
            assert!(saved.contains("{{#선택 안내생략"));
        } else if lesson == "change_apply" {
            let applied = PathBuf::from(
                walk.graph.initial("job").unwrap()["template_path"]
                    .as_str()
                    .unwrap(),
            );
            let practice = PathBuf::from(walk.context()["home"].as_str().unwrap());
            assert!(applied.starts_with(practice.join("template_authority").join("applied")));
            assert!(fs::read_to_string(applied).unwrap().contains("예산재배정"));
            let source = fs::read_to_string(
                walk.asset("낙찰자 선정 및 계약체결 안내.txt")
                    .as_str()
                    .unwrap(),
            )
            .unwrap();
            assert!(!source.contains("예산재배정"));
        }
        if lesson == "first_hwpx" {
            assert_workspace_settings_follow_the_active_graph(&walk);
        }
    }
    assert_eq!(fs::read_dir(&root).unwrap().count(), 8);
    assert_eq!(
        fs::read(tutorial_source.join("물품 구매입찰 공고.hwpx")).unwrap(),
        source_hwpx
    );
    assert_eq!(
        fs::read(tutorial_source.join("낙찰자 선정 및 계약체결 안내.txt")).unwrap(),
        source_txt
    );
    let resolved = root.canonicalize().unwrap();
    assert!(resolved.starts_with(parent.canonicalize().unwrap()));
    fs::remove_dir_all(resolved).unwrap();
}

fn assert_workspace_settings_follow_the_active_graph(walk: &Walk) {
    use hwpx_desktop::template_groups::GroupSettings;

    let user_path = walk.home.join("settings.json");
    let user_before = fs::read(&user_path).unwrap();
    let mut expected_user: Value = serde_json::from_slice(&user_before).unwrap();
    let practice = walk.graph.practice_home().unwrap().unwrap();
    let resources = walk.graph.active_resources().unwrap();
    assert!(resources.templates.path().starts_with(&practice));
    let output = practice.join("연습 결과");
    resources
        .job
        .set_output_folder(output.to_str().unwrap())
        .unwrap();
    resources
        .workbench
        .dispatch("set_target_font", &json!({"font":"malgun"}))
        .unwrap();
    let groups = GroupSettings::new(practice.join("settings.json"), |_| {});
    groups.save_job_collapsed(&json!(["연습"])).unwrap();
    groups
        .save_template_groups("hwpx", &json!({"공고.hwpx":"연습"}))
        .unwrap();
    assert_eq!(fs::read(&user_path).unwrap(), user_before);
    let saved: Value =
        serde_json::from_slice(&fs::read(practice.join("settings.json")).unwrap()).unwrap();
    assert_eq!(saved["last_output_directory"], json!(output));
    assert_eq!(saved["draft_target_font"], "malgun");
    assert_eq!(saved["job_collapsed_groups"], json!(["연습"]));
    assert_eq!(
        saved["template_groups"]["hwpx"],
        json!({"공고.hwpx":"연습"})
    );
    walk.native
        .call("set_theme", &[json!("dark")], || {
            panic!("clipboard not expected")
        })
        .unwrap();
    expected_user["theme"] = json!("dark");
    assert_eq!(
        serde_json::from_slice::<Value>(&fs::read(&user_path).unwrap()).unwrap(),
        expected_user
    );
    assert_eq!(
        serde_json::from_slice::<Value>(&fs::read(practice.join("settings.json")).unwrap())
            .unwrap(),
        saved
    );
    walk.graph.leave_practice().unwrap();
    let user = walk.graph.active_resources().unwrap();
    assert_eq!(user.settings.load_theme().unwrap(), "dark");
    assert_eq!(user.workbench.initial().unwrap()["target_font"], "dotumche");
    assert_eq!(
        user.job.remembered_output_directory().unwrap(),
        walk.home.join("사용자 결과").to_string_lossy()
    );
    assert!(
        GroupSettings::new(user_path, |_| {})
            .load_job_collapsed()
            .unwrap()
            .is_empty()
    );
}
