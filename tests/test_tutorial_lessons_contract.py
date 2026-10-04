"""튜토리얼 커리큘럼의 구조 계약(#1127): 한 단계 = 상자 하나 = 동작 하나.

- 동작 단계마다 그 단계를 끝낼 **관찰 경로가 실재**한다 — 제품 명령을 보는 매처이거나, 제품
  명령이 없는 누르기의 UI 사실(``observe_ui``)이다. 어느 쪽에도 없으면 그 단계는 영영 넘어가지
  않는다(조용한 정지).
- 상자 키는 프런트 ``ANCHORS`` 에 있고 선택자 하나(첫 일치가 곧 그 컨트롤)이며, 매개가 필요한
  선택자와 매개를 든 단계가 서로 맞는다.
- UI 사실은 지금 단계의 것만 받는다(다른 과정·위치·상자·제품 명령 단계의 보고는 무시).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from hwpxfiller.viewmodel.tutorial_lessons import BY_ID, CURRICULUM, LESSONS, UI_PRESS_EVENTS, LessonProgress
from hwpxfiller.webapp.onboarding_match_results import MATCHERS

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "frontend" / "src" / "tutorial" / "anchors.ts"


def _anchors() -> dict[str, str]:
    source = PANEL.read_text(encoding="utf-8")
    body = source[source.index("ANCHORS"):source.index("});", source.index("ANCHORS"))]
    return dict(re.findall(r'^\s*"?([a-z][a-z-]*)"?:\s*"((?:[^"\\]|\\.)*)"', body, re.MULTILINE))


def _beats():
    return [(lesson.id, beat) for lesson in LESSONS for beat in lesson.beats]


def test_every_action_beat_has_an_observation_path_and_no_matcher_is_dead():
    events = {beat.event for _lesson, beat in _beats() if beat.event}
    missing = sorted(event for event in events if event not in MATCHERS and event not in UI_PRESS_EVENTS)
    assert not missing, f"관찰 경로가 없는 단계 이벤트: {missing}"
    assert not (set(MATCHERS) & UI_PRESS_EVENTS), "UI 누르기 단계가 제품 매처도 가졌습니다"
    assert not (set(MATCHERS) - events), f"어느 단계도 쓰지 않는 매처: {sorted(set(MATCHERS) - events)}"
    assert not (UI_PRESS_EVENTS - events), f"어느 단계도 쓰지 않는 UI 사실: {sorted(UI_PRESS_EVENTS - events)}"


def test_every_beat_boxes_one_control_named_by_a_single_selector():
    anchors = _anchors()
    assert anchors, "ANCHORS 를 읽지 못했습니다"
    for lesson, beat in _beats():
        where = f"{lesson}/{beat.id}"
        if beat.target is None:
            assert beat.mode == "explain" and not beat.arg, where
            continue
        selector = anchors.get(beat.target)
        assert selector is not None, f"{where}: 상자 키 {beat.target!r} 가 ANCHORS 에 없습니다"
        assert "," not in selector, f"{where}: 선택자가 여러 후보를 듭니다 — 첫 일치가 다른 컨트롤일 수 있습니다"
        assert ("{arg}" in selector) == bool(beat.arg), f"{where}: 매개와 선택자가 맞지 않습니다"


def test_finish_targets_are_anchors_too():
    anchors = _anchors()
    for key in ("results", "data-label", "wb-copy", "txt-review", "save-template"):
        assert key in anchors and "," not in anchors[key], key


def test_beat_ids_are_unique_within_a_lesson_and_names_carry_no_runtime_tail():
    for lesson in LESSONS:
        ids = [beat.id for beat in lesson.beats]
        assert len(ids) == len(set(ids)), lesson.id
        for beat in lesson.beats:
            assert "연습 " not in beat.body and "튜토리얼 " not in beat.body, (lesson.id, beat.id)
    assert [lesson.id for lesson in LESSONS][-2:] == ["option_apply", "change_apply"]


def test_an_older_curriculum_keeps_completion_but_restarts_position():
    stored = {"version": 1, "selected": "first_hwpx",
              "records": {"first_hwpx": {"checkpoint": 5, "completed": True, "context": {"home": "x"}}}}
    old = LessonProgress(stored)
    assert old.record("first_hwpx") == {"checkpoint": 0, "completed": True, "context": {}}
    current = LessonProgress({**stored, "curriculum": CURRICULUM})
    assert current.record("first_hwpx")["checkpoint"] == 5
    assert LessonProgress().progress()["curriculum"] == CURRICULUM


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    return WebFrontend()


def _report(app, **override):
    snap = app.initial("tutorial")
    payload = {"scenario_id": snap["scenario_id"], "checkpoint": snap["checkpoint"],
               "anchor": snap["beat"]["target"], **override}
    app.dispatch("tutorial", "observe_ui", payload)
    return app.initial("tutorial")["checkpoint"]


def test_ui_press_reports_only_complete_the_current_ui_beat(app):
    tutorial = app.controllers["tutorial"]
    app.dispatch("tutorial", "select", {"scenario_id": "replace_data"})
    beats = BY_ID["replace_data"].beats
    sheet = [beat.id for beat in beats].index("sheet")
    # A product-command beat never completes from a UI report, even one naming its own box.
    assert app.initial("tutorial")["beat"]["press"] is False
    assert _report(app) == 0
    tutorial.progress.record("replace_data")["checkpoint"] = sheet
    assert app.initial("tutorial")["beat"]["press"] is True
    assert _report(app, anchor="sheet-import") == sheet          # another control
    assert _report(app, checkpoint=sheet - 1) == sheet           # stale position
    assert _report(app, scenario_id="first_hwpx") == sheet       # another lesson
    current = {"scenario_id": "replace_data", "checkpoint": sheet, "anchor": "sheet-check"}
    tutorial.dispatch("pause", {})
    app.dispatch("tutorial", "observe_ui", current)
    assert tutorial.progress.record("replace_data")["checkpoint"] == sheet  # paused guidance
    tutorial.progress.select("replace_data")
    assert _report(app) == sheet + 1


def test_a_changed_editor_input_returns_to_the_beat_that_chose_it(app):
    tutorial = app.controllers["tutorial"]
    send = app.dispatch
    send("tutorial", "select", {"scenario_id": "first_hwpx"})
    send("tutorial", "next", {})
    send("editor", "new_session", {})
    ctx = tutorial._context()
    send("editor", "use_library_template", {"path": ctx["assets"]["물품 구매입찰 공고.hwpx"]["path"]})
    send("editor", "use_pool_data", {"key": ctx["pool_keys"]["공고"]})
    send("editor", "goto_section", {"section": "binding"})
    assert app.initial("tutorial")["beat"]["id"] == "confirm_method"
    # The other registered sheet replaces the data: the beat shown is the data beat, own words and box.
    send("editor", "use_pool_data", {"key": ctx["pool_keys"]["계약"]})
    beat = app.initial("tutorial")["beat"]
    assert (beat["id"], beat["target"]) == ("data", "data-row")
    assert beat["body"] == BY_ID["first_hwpx"].beats[3].body and beat["arg"] == ctx["pool_keys"]["공고"]
    send("editor", "new_session", {})
    assert app.initial("tutorial")["beat"]["id"] == "template"


def test_one_command_completes_at_most_one_beat(app):
    tutorial = app.controllers["tutorial"]
    app.dispatch("tutorial", "select", {"scenario_id": "repeat_hwpx"})
    # select_work is this beat's command; the next beat (use the job) needs its own press.
    app.dispatch("library", "select_work", {"name": "공고서 작업"})
    assert tutorial.progress.record("repeat_hwpx")["checkpoint"] == 1
    app.dispatch("job", "prefer_work", {"name": "공고서 작업"})
    app.dispatch("job", "prefer_work", {"name": "공고서 작업"})
    assert tutorial.progress.record("repeat_hwpx")["checkpoint"] == 2


def test_seeded_names_are_fixed_and_lessons_one_and_three_register_both_sheets(app):
    tutorial = app.controllers["tutorial"]
    expected_jobs = {"repeat_hwpx": "공고서 작업", "replace_data": "공고서 작업",
                     "purchase_txt": "구매추진 안내 작업", "blank_values": "계약 안내 작업(빈 칸)",
                     "change_apply": "계약 안내 작업"}
    for lesson, name in expected_jobs.items():
        tutorial.dispatch("select", {"scenario_id": lesson})
        assert tutorial._context()["job_name"] == name
        assert app._job_registry.names() == [name]
    for lesson in ("first_hwpx", "contract_txt"):
        tutorial.dispatch("select", {"scenario_id": lesson})
        keys = tutorial._context()["pool_keys"]
        rows = app.controllers["pool"].snapshot()["column"]["rows"]
        assert {row["key"]: row["sub"].rsplit(" ", 1)[-1] for row in rows} == {keys["공고"]: "공고", keys["계약"]: "계약"}
        assert app._job_registry.names() == []


def test_lesson_nine_starts_with_the_finished_template_open_and_its_change_pending(app):
    tutorial = app.controllers["tutorial"]
    tutorial.dispatch("select", {"scenario_id": "change_apply"})
    path = tutorial._context()["assets"]["낙찰자 선정 및 계약체결 안내.txt"]["path"]
    text = Path(path).read_text(encoding="utf-8")
    assert "{{#항목 예산재배정 예산재배정}}" in text and "{{#선택 안내생략 안내생략}}\n\n{{/선택}}" in text
    authoring = app.controllers["authoring"]
    session = authoring.sessions[authoring.active_id]
    assert session.source_path == session.save_path == path
    assert [slot["label"] for slot in session.analysis["slots"]] == ["예산재배정"]
    assert tutorial.snapshot()["resources"]["ready"], "깔아 둔 서식이 수정된 연습 파일로 오인됐습니다"
    assert app.controllers["job"].work.name == "계약 안내 작업"
    assert app.initial("tutorial")["beat"]["id"] == "impact"


def test_a_failure_after_the_switch_returns_the_window_to_the_user_workspace(app, monkeypatch):
    from hwpxfiller.webapp import onboarding_practice

    tutorial = app.controllers["tutorial"]
    user = dict(app.controllers)

    def broken(*_args):
        raise ValueError("seed failed")

    monkeypatch.setattr(onboarding_practice, "seed_after_switch", broken)
    with pytest.raises(ValueError, match="seed failed"):
        tutorial.dispatch("select", {"scenario_id": "first_hwpx"})
    assert all(app.controllers[name] is controller for name, controller in user.items())
    assert not tutorial.snapshot()["practice"]["active"]
