"""빠른 기안 컨트롤러 골격 가드 — R-flow 블록 5, #90 슬라이스 7 PR-1(헤드리스).

빠른 기안 = 작업의 휘발 쌍둥이(결정 29). PR-1 은 도달 가능한 빈손 화면만 세운다 —
컨트롤러가 링1 :class:`~hwpxfiller.gui.quickdraft_state.QuickDraftViewModel` 을 소유해
빈 세션 스냅샷·템플릿 목록을 창 없이 내는지, 미지 액션을 시끄럽게 거부하는지, 브리지에
등록됐는지를 본다. 템플릿 소스(PR-2)·데이터 결속(PR-3)·복사/가드(PR-4)는 각 PR 에서 심는다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.dataset_pool import DatasetPoolRegistry
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screen_quickdraft import QuickDraftController


def _controller(tmp_path: Path) -> "tuple[QuickDraftController, list]":
    (tmp_path / "개찰참관보고.txt").write_text(
        "제목: {{사업명}} 개찰 참관 보고\n금액: {{추정가격}}", encoding="utf-8"
    )
    pushes: list = []
    ctrl = QuickDraftController(
        TextTemplateRegistry(tmp_path),
        lambda s, snap: pushes.append((s, snap)),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
    )
    return ctrl, pushes


def test_name_is_quickdraft(tmp_path):
    ctrl, _ = _controller(tmp_path)
    assert ctrl.name == "quickdraft"


def test_initial_lists_templates_and_merges_snapshot(tmp_path):
    """initial = 슬롯 드롭다운용 라이브러리 목록 + 빈 세션 스냅샷(txt/job 관례)."""
    ctrl, _ = _controller(tmp_path)
    init = ctrl.initial()
    assert init["templates"] == ["개찰참관보고"]
    # 스냅샷 키가 병합돼 있어야 한다(웹이 initial 1회로 첫 렌더).
    assert init["origin"] is None
    assert init["template_text"] == ""
    assert init["tokens"] == []
    assert init["has_data"] is False


def test_snapshot_empty_session_shape(tmp_path):
    """빈 세션 = 휘발 그릇 초기 형상. 없는 걸 있는 척하지 않는다(confirm-or-alarm)."""
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.snapshot()
    assert snap == {
        "origin": None,
        "template_name": None,
        "template_text": "",
        "modified": False,
        "tokens": [],
        "has_data": False,
        "data_label": "",
        "data_kind": "",
    }


def test_dispatch_unknown_action_raises(tmp_path):
    """미지 액션은 조용히 무시하지 않고 시끄럽게 거부(P5 규약 정렬)."""
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError):
        ctrl.dispatch("nope", {})


def test_registered_in_frontend(tmp_path, monkeypatch):
    """브리지가 빠른 기안 컨트롤러를 등록하고 initial 로 라우팅한다(등록 한 줄 결선 확인)."""
    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "default_jobs_dir", lambda: tmp_path / "jobs")
    frontend = app_mod.WebFrontend(tmp_path / "txt")
    assert "quickdraft" in frontend.controllers
    init = frontend.initial("quickdraft")
    assert "templates" in init and init["origin"] is None
