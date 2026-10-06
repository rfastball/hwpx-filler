"""설정의 「튜토리얼 버튼 표시」 토글(#1147) — 백엔드 소유·판정.

값은 튜토리얼 전용 저장소의 별도 파일에 영속하고(학습 기록 초기화·연습 작업 공간 전환에 지워지지 않는다),
최종 표시값은 연습 중(``practice.active``)이면 토글과 무관하게 ``True``다.
"""
from __future__ import annotations

import pytest

from hwpxfiller.external import settings
from hwpxfiller.external.tutorial_workspace import TutorialWorkspace


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    return WebFrontend()


def test_default_visible_true(app):
    snap = app.initial("tutorial")
    assert snap["entry"]["visible"] is True
    assert snap["invitation"]["visible"] is True  # first_launch · invite_seen=False · toggle on


def test_toggle_off_hides_hud_and_invitation(app):
    app.dispatch("tutorial", "set_entry_visible", {"visible": False})
    snap = app.initial("tutorial")
    assert snap["entry"]["visible"] is False
    assert snap["invitation"]["visible"] is False


def test_toggle_off_then_on_restores(app):
    app.dispatch("tutorial", "set_entry_visible", {"visible": False})
    app.dispatch("tutorial", "set_entry_visible", {"visible": True})
    snap = app.initial("tutorial")
    assert snap["entry"]["visible"] is True
    assert snap["invitation"]["visible"] is True


def test_practice_active_keeps_hud_despite_toggle_off(app):
    app.dispatch("tutorial", "set_entry_visible", {"visible": False})
    app.dispatch("tutorial", "select", {"scenario_id": "first_hwpx"})
    snap = app.initial("tutorial")
    assert snap["practice"]["active"] is True
    assert snap["entry"]["visible"] is True  # HUD stays up through the practice workspace
    # The invitation never participates in the practice-active override — it is irrelevant
    # once a lesson is selected (``invite_seen`` becomes True), but it stays toggle-only.
    assert snap["invitation"]["visible"] is False

    app.dispatch("tutorial", "exit", {})
    after_exit = app.initial("tutorial")
    assert after_exit["practice"]["active"] is False
    assert after_exit["entry"]["visible"] is False  # toggle still off once practice ends


def test_setting_persists_across_new_frontend_instance(tmp_path, monkeypatch):
    from hwpxfiller.webapp.app import WebFrontend

    home = tmp_path / "home"
    monkeypatch.setenv("HWPXFILLER_HOME", str(home))
    first = WebFrontend()
    first.dispatch("tutorial", "set_entry_visible", {"visible": False})

    second = WebFrontend()
    assert second.initial("tutorial")["entry"]["visible"] is False


def test_reset_progress_preserves_the_toggle(app):
    app.dispatch("tutorial", "set_entry_visible", {"visible": False})
    app.dispatch("tutorial", "reset_progress", {"confirm": True})
    snap = app.initial("tutorial")
    assert snap["entry"]["visible"] is False


def test_invalid_payload_is_rejected(app):
    rejected = app.dispatch("tutorial", "set_entry_visible", {"visible": "yes"})
    assert isinstance(rejected, dict) and "__hwpx_dispatch_rejection_v1__" in rejected
    assert rejected["__hwpx_dispatch_rejection_v1__"]["name"] == "ValueError"
    # The toggle must not have moved on the rejected call.
    assert app.initial("tutorial")["entry"]["visible"] is True


def test_workspace_round_trip_and_damaged_file(tmp_path, monkeypatch):
    alerts = []
    monkeypatch.setattr(settings, "alert", alerts.append)
    workspace = TutorialWorkspace(tmp_path / "tw")
    assert workspace.load_entry_visible() is True
    workspace.save_entry_visible(False)
    assert workspace.load_entry_visible() is False
    with pytest.raises(ValueError):
        workspace.save_entry_visible("no")  # type: ignore[arg-type]
    assert workspace.load_entry_visible() is False, "a rejected value never reaches the file"
    (tmp_path / "tw" / "entry.json").write_text("{", encoding="utf-8")
    assert workspace.load_entry_visible() is True and len(alerts) == 1, "damage is alarmed and opens shown"
    for shape in ('{"visible": "no"}', '{"visible": 0}', '{}', '[false]', 'false'):
        alerts.clear()
        (tmp_path / "tw" / "entry.json").write_text(shape, encoding="utf-8")
        assert workspace.load_entry_visible() is True, shape
        assert len(alerts) == 1 and "판독 실패" in alerts[0], f"a wrong shape is damage, not a silent default: {shape}"


def test_toggle_writes_only_its_own_setting_and_pushes_the_new_value(app, monkeypatch):
    """#1152 리뷰: 학습 기록 쓰기 실패가 토글을 반쯤 적용된 실패로 만들지 않는다."""
    tutorial = app.controllers["tutorial"]
    pushes = []
    monkeypatch.setattr(tutorial, "_push", lambda screen, snap: pushes.append(snap))

    def broken(_value):
        raise OSError("progress.json 쓰기 실패")
    monkeypatch.setattr(tutorial.workspace, "save_progress", broken)
    result = app.dispatch("tutorial", "set_entry_visible", {"visible": False})
    assert result is None
    assert tutorial.workspace.load_entry_visible() is False
    assert pushes and pushes[-1]["entry"]["visible"] is False, "the snapshot carries the value now true"


def test_failed_toggle_write_changes_nothing_and_is_reported(app, monkeypatch):
    tutorial = app.controllers["tutorial"]
    pushes = []
    monkeypatch.setattr(tutorial, "_push", lambda screen, snap: pushes.append(snap))

    def broken(_value):
        raise OSError("entry.json 쓰기 실패")
    monkeypatch.setattr(tutorial.workspace, "save_entry_visible", broken)
    with pytest.raises(OSError):
        app.dispatch("tutorial", "set_entry_visible", {"visible": False})
    assert tutorial.progress.entry_visible is True and app.initial("tutorial")["entry"]["visible"] is True
    assert not pushes
