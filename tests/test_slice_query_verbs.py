"""가공(field-binding/v5) 편집 칸의 동사 — 편집기 `set_slice` 새 방식 왕복과 무변이 질의
(`preview_slice`/`propose_slice`)의 결선.

판정 자체는 :mod:`hwpxfiller.viewmodel.slice_assist`(``tests/test_slice_assist.py``)와
:mod:`hwpxfiller.domain.text_slice`(``tests/test_text_slice.py``)가 이미 잰다. 여기는 그
판정기가 **브리지 동사로 결선된 자리**만 잰다: 무변이 질의가 push·세션 clean 표지를 건드리지
않는가, `set_slice` 가 새 방식·malformed 명세를 어떻게 다루는가.

작업대의 짝동사(`preview_map_slice`·`propose_map_slice`·`set_map_slice`)는 #1148 이 걷었다 —
작업대는 더 이상 필드 연결 표를 들지 않고, 연결 가공은 편집기(「연결 편집」)로 나가 고친다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.domain.text_slice import TextSliceError
from hwpxfiller.webapp.action_registry import ACTION_REGISTRY

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
    # 작업대는 가공 동사를 들지 않는다(#1148) — 걷힌 자리는 등록에도 없어야 한다.
    assert not {"preview_map_slice", "propose_map_slice", "set_map_slice"} & set(workbench_actions)
    # 무변이 질의는 index + 질의 재료만 받는다(변이 필드는 없다).
    assert editor_actions["preview_slice"].required == frozenset({"index"})
    assert editor_actions["propose_slice"].required == frozenset({"index", "sample", "start", "end"})
