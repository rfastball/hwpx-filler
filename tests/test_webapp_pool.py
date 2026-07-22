"""데이터 관리(pool) 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

웹 패리티 회수(#26 단위 A, #4)의 회귀 심. 풀 목록·상태 배지·상태별 게이트 액션(보관/
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
    # 상태 게이트: 활성 → [보관][삭제].
    assert [a["key"] for a in row["actions"]] == ["archive", "delete"]
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
    assert "추가했습니다" in ctrl.snapshot()["result"]["text"]  # 신규 = 추가

    res1 = ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/b.xlsx"})
    assert res1["needs_confirm"] is True
    assert "a.xlsx" in res1["confirm_text"]  # 기존 참조 요약 재진술
    assert reg.load("발주").opts["path"] == "C:/data/a.xlsx"  # 1차는 무변형

    res2 = ctrl.dispatch(
        "register_excel", {"name": "발주", "path": "C:/data/b.xlsx", "confirm": True})
    assert res2["ok"] is True
    assert reg.load("발주").opts["path"] == "C:/data/b.xlsx"
    # 동명 갱신은 항목 추가가 아니라 참조 교체 — 결과줄이 실제 일어난 일을 말한다(#45).
    assert "갱신했습니다" in ctrl.snapshot()["result"]["text"]


def test_slug_collision_is_worded_not_raised(tmp_path):
    """다른 이름·같은 slug 는 날것 예외로 새지 않고 문구로 loud 재진술(danger 결과줄)."""
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "예산/2026", "path": "C:/d/a.xlsx"})

    res = ctrl.dispatch("register_excel", {"name": "예산_2026", "path": "C:/d/b.xlsx"})
    assert res["ok"] is False and "소실됩니다" in res["error"]
    assert ctrl.snapshot()["result"]["level"] == "danger"
    assert reg.load("예산/2026").opts["path"] == "C:/d/a.xlsx"  # 기존 항목 무변형


def test_empty_name_is_worded_not_raised(tmp_path):
    ctrl, _, _ = _controller(tmp_path)
    res = ctrl.dispatch("register_excel", {"name": "  ", "path": "C:/d/a.xlsx"})
    assert res["ok"] is False and "이름" in res["error"]
    assert ctrl.snapshot()["result"]["level"] == "danger"


def test_state_transitions_gate_actions(tmp_path):
    """활성→[보관][삭제], 보관→[활성화][삭제], 활성화 복귀 — 2상태 게이트 단일 출처(#5)."""
    ctrl, _, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})

    ctrl.dispatch("archive", {"name": "발주"})
    row = ctrl.snapshot()["rows"][0]
    assert row["status"] == "archived" and row["badge_label"] == "보관"
    assert row["badge_level"] == "muted"
    assert [a["key"] for a in row["actions"]] == ["activate", "delete"]

    ctrl.dispatch("activate", {"name": "발주"})
    assert ctrl.snapshot()["rows"][0]["status"] == "active"


def test_retire_action_is_rejected_loudly(tmp_path):
    """폐기된 retire 액션(#5)은 웹 경계에서 loud ValueError — 조용한 무반응 금지."""
    ctrl, _, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    with pytest.raises(ValueError, match="알 수 없는 pool 액션"):
        ctrl.dispatch("retire", {"name": "발주"})


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


def test_confirmed_reregister_does_not_resurrect_concurrently_deleted_item(tmp_path):
    """기존 참조 교체 확인은, 확인 중 삭제된 항목의 신규 생성 승인으로 변하지 않는다."""
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/a.xlsx"})
    first = ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/b.xlsx"})
    assert first["needs_confirm"] is True

    DatasetPoolRegistry(reg.directory).delete("발주")
    second = ctrl.dispatch(
        "register_excel", {"name": "발주", "path": "C:/data/b.xlsx", "confirm": True}
    )

    assert second["ok"] is False and "삭제" in second["error"]
    assert not reg.exists("발주")


def test_unknown_action_is_loud(tmp_path):
    ctrl, _, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 pool 액션"):
        ctrl.dispatch("drop_all", {})


MULTI_SHEET = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "multi_sheet.xlsx"


def test_corrupt_pool_file_is_quarantined_not_boot_crash(tmp_path):
    """손상 .dataset.json 1개가 화면·부팅을 죽이지 않고 격리·표면화된다(RC-05, #26 #2).

    예전엔 list_items 가 예외를 전파했고 어떤 호출측도 잡지 않아 컨트롤러 생성(=앱 부팅
    경로, 7화면 전부)이 손상 파일 하나로 무너졌다. 지금은 정상 항목이 살고 손상은 재진술된다.
    """
    reg = DatasetPoolRegistry(tmp_path / "datasets")
    reg.save(DatasetPoolItem(name="살아있음", kind="excel", opts={"path": "C:/a.xlsx"}))
    # 손상 파일 투입(잘린 JSON) — 손편집·크래시 잔여 시뮬레이션.
    (reg.directory / ("깨진" + reg.SUFFIX)).write_text("{ not json", encoding="utf-8")

    # 컨트롤러 생성(=앱 부팅 경로)이 손상 파일 하나로 크래시하지 않아야 한다.
    ctrl, _, _ = _controller(tmp_path)
    snap = ctrl.snapshot()
    assert [r["name"] for r in snap["rows"]] == ["살아있음"]   # 정상 항목 생존
    assert snap["corrupted"] and snap["corrupted"][0]["file"].endswith(reg.SUFFIX)


def test_register_excel_multi_sheet_without_sheet_is_blocked(tmp_path):
    """수동 등록에서 시트 미지정 다중시트 워크북은 등록을 막고 시트 지정을 요구(#26 #3, #33 대칭).

    등록은 참조 저장이라 파일을 열지 않지만, 시트가 여럿인데 미지정이면 실행 복원 때 첫
    시트를 조용히 읽는다 — 등록 시점에 막아 에디터 자동등록(확정 시트 동봉)과 대칭을 맞춘다.
    """
    ctrl, reg, _ = _controller(tmp_path)
    res = ctrl.dispatch("register_excel", {"name": "모호", "path": str(MULTI_SHEET)})
    assert res["ok"] is False and "시트" in res["error"]
    assert not reg.exists("모호")                     # 등록되지 않음(모호 참조 방지)
    # 시트를 지정하면 통과 — 확정 시트가 참조에 남는다.
    res2 = ctrl.dispatch(
        "register_excel", {"name": "확정", "path": str(MULTI_SHEET), "sheet": "낙찰현황"})
    assert res2["ok"] is True and reg.load("확정").opts["sheet"] == "낙찰현황"


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


# ------------------------------------------------- 다시 연결 표면(#67)
def test_rows_expose_sheet_and_missing_for_relink(tmp_path):
    """행이 시트(프리필)와 참조 끊김(missing)을 노출한다 — 죽은 참조를 조용히 두지 않는다(#67)."""
    ctrl, _, _ = _controller(tmp_path)
    live = tmp_path / "살아있는.csv"
    live.write_text("a,b\n1,2\n", encoding="utf-8")
    ctrl.dispatch("register_excel", {"name": "살아있음", "path": str(live)})
    ctrl.dispatch("register_excel",
                  {"name": "끊김", "path": str(tmp_path / "이동된.xlsx"), "sheet": "낙찰현황"})
    rows = {r["name"]: r for r in ctrl.snapshot()["rows"]}
    assert rows["살아있음"]["missing"] is False
    assert rows["살아있음"]["sheet"] == ""
    assert rows["끊김"]["missing"] is True                 # 파일 부재 → 배지 대상
    assert rows["끊김"]["sheet"] == "낙찰현황"              # 다시 연결 모달 프리필


def test_nara_row_has_no_missing_badge(tmp_path):
    """비파일 참조(nara)는 locate_path 가 없어 missing 판정 대상이 아니다(#67)."""
    from hwpxfiller.core.dataset_pool import DatasetPoolItem

    ctrl, reg, _ = _controller(tmp_path)
    reg.save(DatasetPoolItem(
        name="나라7월", kind="nara",
        opts={"bgn_dt": "202607010000", "end_dt": "202607080000"}))
    ctrl.dispatch("refresh", {})
    row = ctrl.snapshot()["rows"][0]
    assert row["missing"] is False and row["locate_path"] == ""
