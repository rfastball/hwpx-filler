"""데이터 관리(pool) 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

웹 패리티 회수(#26 단위 A, #4)의 회귀 심. 풀 목록·상태 배지·상태별 게이트 액션(보관/은퇴/
활성화/삭제 확인 라운드트립)·참조 등록(동명 확인 승격·slug 충돌 문구 재진술) end-to-end 를
창 없이 확인한다. 레지스트리는 tmp 주입(위치-불가지) — 파일 피커만 브리지 담당.

결정 회귀: 나라장터 등록 미노출(동결 2026-07-16 — ``register_nara`` 액션 없음), 단 기존
nara 항목은 숨기지 않고 표시. 동명 재등록의 조용한 opts 재지정 금지(적대적 검토 지적).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from hwpxfiller.webapp.screen_pool import PoolController


def _controller(tmp_path: Path) -> "tuple[PoolController, DatasetPoolRegistry, list]":
    pushes: list = []
    reg = DatasetPoolRegistry(tmp_path / "datasets")
    ctrl = PoolController(reg, lambda s, snap: pushes.append((s, snap)))
    return ctrl, reg, pushes


def test_initial_empty_pool(tmp_path):
    ctrl, _, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["rows"] == []
    assert snap["empty"] is True
    assert snap["count"] == ""
    assert snap["result"]["text"] == ""


def test_register_excel_reflects_in_rows_and_pushes(tmp_path):
    ctrl, _, pushes = _controller(tmp_path)
    res = ctrl.dispatch(
        "register_excel", {"name": "발주 7월", "path": "C:/data/발주.xlsx"})
    assert res["ok"] is True and res["name"] == "발주 7월"
    assert pushes and pushes[-1][0] == "pool"  # 액션 후 관측 푸시
    row = pushes[-1][1]["rows"][0]
    assert row["name"] == "발주 7월"
    assert row["kind_label"] == "엑셀/CSV"
    assert row["status"] == "active" and row["badge_label"] == "활성"
    assert "발주.xlsx" in row["reference"]
    # 상태 게이트: 활성 → [보관][은퇴][삭제].
    assert [a["key"] for a in row["actions"]] == ["archive", "retire", "delete"]
    assert ctrl.snapshot()["result"]["level"] == "ok"


def test_register_excel_with_sheet_keeps_sheet_pointer(tmp_path):
    """확정 시트는 참조 포인터에 남는다 — 다중시트 파일의 죽은/모호 참조 방지(RC-13 동종)."""
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel",
                  {"name": "낙찰", "path": "C:/d/멀티.xlsx", "sheet": "낙찰현황"})
    assert reg.load("낙찰").opts["sheet"] == "낙찰현황"
    assert "시트 낙찰현황" in ctrl.snapshot()["rows"][0]["reference"]


def test_same_name_reregister_needs_confirm_then_overwrites(tmp_path):
    """동명 재등록 = 조용한 참조 재지정 함정 — 1차는 기존 참조 재진술, confirm 시에만 덮는다."""
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/a.xlsx"})

    res1 = ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/b.xlsx"})
    assert res1["needs_confirm"] is True
    assert "a.xlsx" in res1["confirm_text"]  # 기존 참조 요약 재진술
    assert reg.load("발주").opts["path"] == "C:/data/a.xlsx"  # 1차는 무변형

    res2 = ctrl.dispatch(
        "register_excel", {"name": "발주", "path": "C:/data/b.xlsx", "confirm": True})
    assert res2["ok"] is True
    assert reg.load("발주").opts["path"] == "C:/data/b.xlsx"


def test_slug_collision_is_worded_not_raised(tmp_path):
    """다른 이름·같은 slug 는 날것 예외로 새지 않고 문구로 loud 재진술(danger 결과줄)."""
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "예산/2026", "path": "C:/d/a.xlsx"})

    res = ctrl.dispatch("register_excel", {"name": "예산_2026", "path": "C:/d/b.xlsx"})
    assert res["ok"] is False and "조용히" in res["error"]
    assert ctrl.snapshot()["result"]["level"] == "danger"
    assert reg.load("예산/2026").opts["path"] == "C:/d/a.xlsx"  # 기존 항목 무변형


def test_empty_name_is_worded_not_raised(tmp_path):
    ctrl, _, _ = _controller(tmp_path)
    res = ctrl.dispatch("register_excel", {"name": "  ", "path": "C:/d/a.xlsx"})
    assert res["ok"] is False and "이름" in res["error"]
    assert ctrl.snapshot()["result"]["level"] == "danger"


def test_state_transitions_gate_actions(tmp_path):
    """보관→[활성화][은퇴][삭제], 은퇴→[활성화][삭제], 활성화 복귀 — 상태 게이트 단일 출처."""
    ctrl, _, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})

    ctrl.dispatch("archive", {"name": "발주"})
    row = ctrl.snapshot()["rows"][0]
    assert row["status"] == "archived" and row["badge_label"] == "보관"
    assert [a["key"] for a in row["actions"]] == ["activate", "retire", "delete"]

    ctrl.dispatch("retire", {"name": "발주"})
    row = ctrl.snapshot()["rows"][0]
    assert row["status"] == "retired" and row["badge_level"] == "muted"
    assert [a["key"] for a in row["actions"]] == ["activate", "delete"]

    ctrl.dispatch("activate", {"name": "발주"})
    assert ctrl.snapshot()["rows"][0]["status"] == "active"


def test_delete_two_phase_confirm_roundtrip(tmp_path):
    """1차=needs_confirm(무변형·원본 미삭제 재진술), 2차 confirm=삭제. 조용한 파괴 금지."""
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})

    res1 = ctrl.dispatch("delete", {"name": "발주"})
    assert res1["needs_confirm"] is True
    assert "원본 파일은 지우지 않습니다" in res1["confirm_text"]
    assert reg.exists("발주")  # 1차는 무변형

    ctrl.dispatch("delete", {"name": "발주", "confirm": True})
    assert not reg.exists("발주")
    assert ctrl.snapshot()["empty"] is True


def test_unknown_action_is_loud(tmp_path):
    ctrl, _, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 pool 액션"):
        ctrl.dispatch("drop_all", {})


def test_existing_nara_item_is_shown_not_hidden(tmp_path):
    """나라 등록은 동결로 미노출이지만, 기존 nara 항목은 숨기지 않고 표시한다(조용한 은닉 금지)."""
    ctrl, reg, _ = _controller(tmp_path)
    reg.save(DatasetPoolItem(
        name="나라 7월", kind="nara", opts={"bgn_dt": "202607010000", "end_dt": "202607310000"}))
    ctrl.dispatch("refresh", {})

    row = ctrl.snapshot()["rows"][0]
    assert row["kind_label"] == "나라장터"
    assert "기간 202607010000~202607310000" in row["reference"]
    # 동결 결정 회귀 — 나라 등록 액션은 존재하지 않는다(웹 표면 부재가 계약).
    with pytest.raises(ValueError, match="알 수 없는 pool 액션"):
        ctrl.dispatch("register_nara", {"name": "x", "bgn_dt": "a", "end_dt": "b"})
