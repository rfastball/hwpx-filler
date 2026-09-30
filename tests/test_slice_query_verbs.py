"""가공(field-binding/v5) 편집 칸의 동사 — `set_slice`/`set_map_slice` 새 방식 왕복과 무변이 질의
(`preview_slice`/`propose_slice`, `preview_map_slice`/`propose_map_slice`)의 결선.

판정 자체는 :mod:`hwpxfiller.viewmodel.slice_assist`(``tests/test_slice_assist.py``)와
:mod:`hwpxfiller.domain.text_slice`(``tests/test_text_slice.py``)가 이미 잰다. 여기는 그
판정기가 **브리지 동사로 결선된 자리**만 잰다: 무변이 질의가 push·세션 clean 표지를 건드리지
않는가, `set_slice`/`set_map_slice` 가 새 방식·malformed 명세를 어떻게 다루는가.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hwpxfiller.domain.job import Job
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.domain.text_slice import TextSliceError
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.webapp.action_registry import ACTION_REGISTRY, validate_dispatch
from hwpxfiller.webapp.screen_workbench import TargetFontSetting, WorkbenchController

_NOW = datetime(2026, 9, 30, 12, 0, 0)


# ─── 작업대(workbench) — 가벼운 헤드리스 고정 ───────────────────────────────────
def _job(tmp_path: Path, *, name: str = "발주요청") -> Job:
    tpl = tmp_path / "발주요청.txt"
    tpl.write_text("수신: {{수신}}\n건명: {{건명}}", encoding="utf-8")
    return Job(
        name=name,
        template_path=str(tpl),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="수신", source="부서"),
            FieldMapping(template_field="건명", source="사업명"),
        ]),
    )


def _records() -> "list[tuple[int, dict]]":
    return [
        (0, {"부서": "회계과", "사업명": "R26BK09017075-000"}),
        (1, {"부서": "총무과", "사업명": "R26BK09017076-001"}),
    ]


def _workbench(tmp_path: Path) -> "tuple[WorkbenchController, JobRegistry, list]":
    reg = JobRegistry(tmp_path / "jobs")
    pushes: list = []
    ctrl = WorkbenchController(
        reg, lambda s, snap: pushes.append((s, snap)),
        clock=lambda: _NOW, target_font=TargetFontSetting(),
    )
    job = _job(tmp_path)
    reg.save(job)
    ctrl.open(reg.load(job.name), _records())
    return ctrl, reg, pushes


def _send(ctrl: WorkbenchController, action: str, payload: "dict | None" = None):
    checked = validate_dispatch(ctrl.name, action, payload or {})
    return ctrl.dispatch(action, checked)


def test_preview_map_slice_is_a_query_no_push_and_no_dirty(tmp_path):
    ctrl, _reg, pushes = _workbench(tmp_path)
    before = len(pushes)
    result = _send(ctrl, "preview_map_slice", {"name": "건명", "sample": 0})
    assert result["ok"] is True
    assert result["rows"][0]["result"] == "R26BK09017075-000"  # 가공 없음 — 원문 그대로
    assert len(pushes) == before, "무변이 질의는 push 하지 않는다"


def test_propose_map_slice_is_a_query_no_push_and_no_dirty(tmp_path):
    ctrl, _reg, pushes = _workbench(tmp_path)
    before = len(pushes)
    result = _send(ctrl, "propose_map_slice", {"name": "건명", "sample": 0, "start": 0, "end": 13})
    assert result["ok"] is True
    assert [c["mode"] for c in result["candidates"]] == ["before", "split", "head"]
    assert len(pushes) == before, "무변이 질의는 push 하지 않는다"


def test_set_map_slice_with_a_new_mode_round_trips_into_the_row_and_projection(tmp_path):
    ctrl, reg, pushes = _workbench(tmp_path)
    before = len(pushes)
    _send(ctrl, "set_map_slice", {
        "name": "건명", "slice": {"mode": "before", "delimiter": "-", "on_missing": "keep"},
    })
    assert len(pushes) == before + 1, "가공 설정은 변이다 — push 한다"
    row = next(r for r in ctrl.snapshot()["rows"] if r["name"] == "건명")
    assert row["value"] == "R26BK09017075"
    assert row["slice"] == {"mode": "before", "delimiter": "-", "on_missing": "keep"}
    assert row["slice_label"] == "‘-’ 앞까지"


def test_set_map_slice_rejects_a_malformed_new_mode_spec(tmp_path):
    ctrl, _reg, _pushes = _workbench(tmp_path)
    with pytest.raises(ValueError, match="가공 기준 글자가 비었음"):
        _send(ctrl, "set_map_slice", {
            "name": "건명", "slice": {"mode": "between", "open": "", "close": ")"},
        })
    row = next(r for r in ctrl.snapshot()["rows"] if r["name"] == "건명")
    assert row["slice"] is None, "거절된 명세가 반쯤 적용되지 않는다"


def test_set_map_slice_none_clears_the_slice(tmp_path):
    ctrl, _reg, _pushes = _workbench(tmp_path)
    _send(ctrl, "set_map_slice", {"name": "건명", "slice": {"mode": "head", "count": 3}})
    _send(ctrl, "set_map_slice", {"name": "건명", "slice": None})
    row = next(r for r in ctrl.snapshot()["rows"] if r["name"] == "건명")
    assert row["slice"] is None


# ─── 편집기(editor) — 실 설치 예시 위(라이브러리 서식·계약목록.csv) ────────────────────
def _editor_app(app):
    from hwpxfiller.host.locations import home_dir

    def asset(name: str) -> Path:
        return next(home_dir().rglob(name))

    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    app.dispatch("editor", "use_library_template", {"path": str(asset("계약체결안내.hwpx"))})
    editor.load_data_path(str(asset("계약목록.csv")))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    return editor


@pytest.fixture
def app():
    from hwpxfiller.webapp.app import WebFrontend

    frontend = WebFrontend()
    assert frontend.dispatch("tpl", "install_examples", {"confirm": True})["ok"] is True
    return frontend


def _slice_row_index(editor, field: str) -> int:
    for row in editor.snapshot()["rows"]:
        if row.get("template_field") == field:
            return row["index"]
    raise AssertionError(f"row not found: {field!r}")


def test_preview_slice_is_a_query_no_push_and_keeps_the_session_clean(app):
    editor = _editor_app(app)
    editor.edit.clean = True
    index = _slice_row_index(editor, "공고번호")
    result = app.dispatch("editor", "preview_slice", {"index": index, "sample": 0})
    assert result["ok"] is True
    assert result["sample"]["value"] == "20260812-001"
    assert editor.edit.clean is True, "무변이 질의는 세션을 더럽히지 않는다"


def test_propose_slice_is_a_query_no_push_and_keeps_the_session_clean(app):
    editor = _editor_app(app)
    editor.edit.clean = True
    index = _slice_row_index(editor, "공고번호")
    result = app.dispatch(
        "editor", "propose_slice", {"index": index, "sample": 0, "start": 0, "end": 8}
    )
    assert result["ok"] is True
    assert [c["mode"] for c in result["candidates"]] == ["before", "split", "head"]
    assert editor.edit.clean is True


def test_set_slice_with_a_new_mode_round_trips(app):
    editor = _editor_app(app)
    index = _slice_row_index(editor, "공고번호")
    app.dispatch(
        "editor", "set_slice",
        {"index": index, "slice": {"mode": "before", "delimiter": "-", "on_missing": "keep"}},
    )
    row = editor.snapshot()["rows"][index]
    assert row["slice"] == {"mode": "before", "delimiter": "-", "on_missing": "keep"}
    assert row["slice_label"] == "‘-’ 앞까지"
    # WebFrontend.dispatch 는 ValueError 를 거절 봉투로 감싼다(pywebview 왕복 규약) — 컨트롤러를
    # 직접 부르면 판정기가 던지는 그대로다.
    with pytest.raises(TextSliceError):
        editor.dispatch("set_slice", {"index": index, "slice": {"mode": "head", "count": 0}})
    row = editor.snapshot()["rows"][index]
    assert row["slice"] == {"mode": "before", "delimiter": "-", "on_missing": "keep"}, (
        "거절된 명세가 반쯤 적용되지 않는다"
    )


# ─── action registry — 신설 동사가 등록돼 있다 ───────────────────────────────────
def test_query_verbs_are_registered_in_the_action_registry() -> None:
    editor_actions = ACTION_REGISTRY["editor"]
    workbench_actions = ACTION_REGISTRY["workbench"]
    assert {"preview_slice", "propose_slice", "set_slice"} <= set(editor_actions)
    assert {"preview_map_slice", "propose_map_slice", "set_map_slice"} <= set(workbench_actions)
    # 무변이 질의는 index/name + 질의 재료만 받는다(변이 필드는 없다).
    assert editor_actions["preview_slice"].required == frozenset({"index"})
    assert editor_actions["propose_slice"].required == frozenset({"index", "sample", "start", "end"})
    assert workbench_actions["preview_map_slice"].required == frozenset({"name"})
    assert workbench_actions["propose_map_slice"].required == frozenset(
        {"name", "sample", "start", "end"}
    )
