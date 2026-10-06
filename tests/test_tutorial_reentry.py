"""연습 과정 재진입의 전제 — 다시 들어온 단계는 지금도 성립하는 전제 위에만 선다(Codex 리뷰 후속).

- 열린 메뉴 안의 항목을 상자로 든 단계(``TRANSIENT_TARGETS``)는 메뉴가 닫히면(웹의 UI 사실) 또는
  다시 들어오면(재개·과정 선택·앱 재시작) 그 메뉴를 여는 단계로 돌아간다 — 메뉴는 복원되지 않는다.
- 시드한 연습 작업이 사라지거나 손상되면 재개·선택은 준비 안 됨이다(성공으로 낮추지 않는다).
- 연습 작업 공간을 갈아 끼우는 전환은 그 공간의 미저장 저작을 먼저 묻는다 — 갈아 끼운 뒤에는
  창 종료 가드도 그 손실을 볼 수 없다.
"""
from __future__ import annotations

import pytest

from hwpxfiller.viewmodel.tutorial_lessons import BY_ID, LESSONS, TRANSIENT_TARGETS, UI_PRESS_EVENTS
from test_tutorial_walk import Authoring, Walk, _open_practice_txt

NOT_READY = "연습 파일이 준비되지 않았습니다. 예제로 시작하세요."


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    return WebFrontend()


def _rejected(result) -> bool:
    return isinstance(result, dict) and "__hwpx_dispatch_rejection_v1__" in result


def _to_open_edit(walk: Walk) -> None:
    walk.step("open_list", lambda: walk.send("editor", "new_session"))
    walk.press("open_menu")
    assert walk.beat()["id"] == "open_edit" and walk.beat()["transient"] is True


def test_every_menu_item_beat_stands_right_after_the_press_that_opens_its_menu():
    for lesson in LESSONS:
        for index, beat in enumerate(lesson.beats):
            if beat.target in TRANSIENT_TARGETS:
                opener = lesson.beats[index - 1]
                assert index > 0 and opener.event in UI_PRESS_EVENTS, (lesson.id, beat.id)
                assert [item.id for item in lesson.beats].index(opener.id) == index - 1, (lesson.id, beat.id)


def test_a_menu_closed_unpressed_returns_to_the_press_that_opens_it(app):
    walk = Walk(app, "field_trial")
    _to_open_edit(walk)
    snap = app.initial("tutorial")
    report = {"scenario_id": "field_trial", "checkpoint": snap["checkpoint"], "anchor": "menu-item"}
    for stale in ({"anchor": "template-more"}, {"checkpoint": snap["checkpoint"] - 1}, {"scenario_id": "option_apply"}):
        app.dispatch("tutorial", "observe_ui_closed", {**report, **stale})
        assert walk.beat()["id"] == "open_edit", stale
    app.dispatch("tutorial", "observe_ui_closed", report)
    assert walk.beat()["id"] == "open_menu" and walk.beat()["transient"] is False
    app.dispatch("tutorial", "observe_ui_closed", {**report, "checkpoint": snap["checkpoint"] - 1, "anchor": "template-more"})
    assert walk.beat()["id"] == "open_menu", "a beat outside a menu never rewinds on a closed report"
    walk.press("open_menu")
    _open_practice_txt_tail(walk)


def _open_practice_txt_tail(walk: Walk) -> None:
    txt = walk.asset("낙찰자 선정 및 계약체결 안내.txt")
    walk.step("open_edit", lambda: walk.app.open_authoring_document(txt, True))


def test_resume_and_a_restarted_app_never_stand_on_a_menu_item_beat(app, tmp_path):
    from hwpxfiller.webapp.app import WebFrontend

    walk = Walk(app, "field_trial")
    _to_open_edit(walk)
    app.dispatch("tutorial", "pause", {})
    app.dispatch("tutorial", "resume", {})
    assert walk.beat()["id"] == "open_menu", "the menu was not restored by resuming"

    walk.press("open_menu")
    reopened = WebFrontend()
    reopened.dispatch("tutorial", "resume", {})
    assert reopened.initial("tutorial")["beat"]["id"] == "open_menu", "nor by restarting the app"


def test_replace_data_resuggest_returns_to_its_binding_menu(app):
    walk = Walk(app, "replace_data")
    beats = [beat.id for beat in BY_ID["replace_data"].beats]
    walk.tutorial.progress.record("replace_data")["checkpoint"] = beats.index("resuggest")
    app.dispatch("tutorial", "pause", {})
    app.dispatch("tutorial", "resume", {})
    assert walk.beat()["id"] == "menu"


def _drop_seeded_job(walk: Walk, damage: bool) -> None:
    from hwpxfiller.external.job_store import JobRegistry

    path = JobRegistry(walk.tutorial.switch.practice.home / "jobs").path_for(walk.ctx["job_name"])
    if damage:
        path.write_text("{", encoding="utf-8")
    else:
        path.unlink()


@pytest.mark.parametrize("damage", [False, True], ids=["deleted", "damaged"])
def test_a_missing_or_damaged_seeded_job_is_not_ready_on_resume_or_select(app, damage):
    walk = Walk(app, "blank_values")
    assert walk.tutorial._resources()[0]
    walk.tutorial.progress.record("blank_values")["checkpoint"] = 1
    _drop_seeded_job(walk, damage)
    app.dispatch("tutorial", "pause", {})
    assert _rejected(app.dispatch("tutorial", "resume", {}))
    snap = app.initial("tutorial")
    assert snap["resources"]["ready"] is False and snap["recovery"]["body"] == NOT_READY

    app.dispatch("tutorial", "select", {"scenario_id": "blank_values"})
    snap = app.initial("tutorial")
    assert snap["paused"] and snap["resources"]["ready"] is False and snap["recovery"]["body"] == NOT_READY
    app.dispatch("tutorial", "restart", {"scenario_id": "blank_values"})
    assert app.initial("tutorial")["resources"]["ready"] is True, "starting over reseeds the job"


def _dirty_practice_template(app) -> Walk:
    walk = Walk(app, "field_trial")
    _open_practice_txt(walk)
    doc = Authoring(walk)
    walk.send("authoring", "update", doc.fence(content=doc.text() + "\n덧붙임"))
    assert app.controllers["authoring"].close_guard_reason()
    return walk


def test_replacing_a_practice_workspace_with_unsaved_authoring_asks_first(app):
    walk = _dirty_practice_template(app)
    tutorial = walk.tutorial
    reason = app.controllers["authoring"].close_guard_reason()
    asked = tutorial.dispatch("preflight", {"screen": "authoring", "action": "select", "scenario_id": "first_hwpx"})
    assert asked["needs_confirm"] is True
    assert asked["confirm_text"] == f"지금 연습의 다음 진행 상태가 사라집니다:\n\n• {reason}"
    restart = tutorial.dispatch("preflight", {"screen": "authoring", "action": "restart", "scenario_id": "field_trial"})
    assert restart["needs_confirm"] is True
    for same_home in ({"action": "resume"}, {"action": "select", "scenario_id": "field_trial"}):
        kept = tutorial.dispatch("preflight", {"screen": "authoring", **same_home})
        assert kept["needs_confirm"] is False, same_home

    assert _rejected(app.dispatch("tutorial", "select", {"scenario_id": "first_hwpx"})), "no token: never silently"
    assert tutorial.switch.practice.controllers["authoring"].close_guard_reason() == reason

    confirmed = tutorial.dispatch("preflight", {"screen": "authoring", "action": "select", "scenario_id": "first_hwpx"})
    tutorial.dispatch("select", {"scenario_id": "first_hwpx", "transition_token": confirmed["transition_token"]})
    assert app.initial("tutorial")["scenario_id"] == "first_hwpx"


def test_a_practice_workspace_left_for_the_user_one_is_still_asked_about(app):
    walk = _dirty_practice_template(app)
    walk.tutorial.dispatch("exit", {})
    assert walk.tutorial.switch.practice_home is None
    asked = walk.tutorial.dispatch("preflight", {"screen": "job", "action": "start", "scenario_id": "first_hwpx"})
    assert asked["needs_confirm"] is True
