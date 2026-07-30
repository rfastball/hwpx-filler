"""데이터 관리(pool) 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

웹 패리티 회수(#26 단위 A, #4)의 회귀 심. 풀 목록·상태 배지·상태별 게이트 액션(보관/
활성화/삭제 확인 라운드트립)·참조 등록 end-to-end 를 창 없이 확인한다. 레지스트리는 tmp
주입(위치-불가지) — 파일 피커만 브리지 담당.

**정체성 재편(#347, U2 §5.3)**: 항목 조작은 슬롯 ``key``, 등록 중복 판정은 정체성
(경로+시트)이다. 이름은 순수 라벨(중복 허용) — 구 동명 확인·slug 충돌 게이트는 소멸했고,
같은 데이터 재등록은 라벨 갱신 확정 또는 「이미 고정됨」 재진술로 접힌다. 구판(이름=키)이
남긴 같은 정체성 2건은 duplicates 로 loud 표면화되고 사용자 확정(``resolve_duplicate``)
으로만 병합된다.

결정 회귀: 나라장터 등록 미노출(동결 2026-07-16 — ``register_nara`` 액션 없음), 단 기존
nara 항목은 숨기지 않고 표시.
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
    row = ctrl.snapshot()["rows"][0]
    assert reg.load(row["key"]).opts["sheet"] == "낙찰현황"
    assert "시트 낙찰현황" in row["reference"]


def test_same_data_reregister_is_relabel_not_second_entry(tmp_path):
    """같은 데이터(경로+시트) 재등록은 2건이 아니라 기존 등록의 라벨 갱신이다(§5.3 C).

    1차는 기존 이름을 재진술하는 확인 승격, confirm 시에만 라벨·메모가 갱신된다 —
    참조는 바뀔 수 없다(정체성이 곧 참조).
    """
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/a.xlsx"})
    assert "추가했습니다" in ctrl.snapshot()["result"]["text"]  # 신규 = 추가

    res1 = ctrl.dispatch("register_excel", {"name": "발주 최신", "path": "C:/data/a.xlsx"})
    assert res1["needs_confirm"] is True
    assert "'발주'" in res1["confirm_text"]      # 기존 이름 재진술
    assert "a.xlsx" in res1["confirm_text"]      # 기존 참조 요약 재진술
    assert [r.name for r in ctrl.vm.rows()] == ["발주"]  # 1차는 무변형

    res2 = ctrl.dispatch(
        "register_excel", {"name": "발주 최신", "path": "C:/data/a.xlsx", "confirm": True})
    assert res2["ok"] is True
    rows = ctrl.snapshot()["rows"]
    assert len(rows) == 1                        # 2건이 되지 않는다
    assert rows[0]["name"] == "발주 최신"
    assert reg.load(rows[0]["key"]).opts["path"] == "C:/data/a.xlsx"  # 참조 불변
    assert "갱신했습니다" in ctrl.snapshot()["result"]["text"]


def test_same_data_same_name_reregister_is_noop_restated(tmp_path):
    """바뀌는 게 없는 재등록(같은 이름·빈 메모)은 확인 소음 없이 「이미 고정됨」으로 접힌다."""
    ctrl, _, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/a.xlsx"})
    res = ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/a.xlsx"})
    assert res["ok"] is True and "needs_confirm" not in res
    assert "이미 고정돼 있습니다" in ctrl.snapshot()["result"]["text"]
    assert len(ctrl.snapshot()["rows"]) == 1


def test_same_name_different_data_are_two_entries(tmp_path):
    """이름은 순수 라벨(§5.3 C) — 같은 이름·다른 파일은 확인 없이 2건으로 공존한다.

    구 이름=키 시절의 동명 확인 게이트(참조 재지정 함정)·slug 충돌 거절은 정체성 재편으로
    소멸했다 — 이름이 참조를 드는 소비자 자체가 없다(`default_dataset_ref` 폐기).
    """
    ctrl, _, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "매출", "path": "C:/d/1월.xlsx"})
    res = ctrl.dispatch("register_excel", {"name": "매출", "path": "C:/d/2월.xlsx"})
    assert res["ok"] is True and "needs_confirm" not in res
    rows = ctrl.snapshot()["rows"]
    assert [r["name"] for r in rows] == ["매출", "매출"]
    assert len({r["key"] for r in rows}) == 2  # 슬롯 키가 둘을 가른다


def test_empty_name_is_worded_not_raised(tmp_path):
    ctrl, _, _ = _controller(tmp_path)
    res = ctrl.dispatch("register_excel", {"name": "  ", "path": "C:/d/a.xlsx"})
    assert res["ok"] is False and "이름" in res["error"]
    assert ctrl.snapshot()["result"]["level"] == "danger"


def test_state_transitions_gate_actions(tmp_path):
    """활성→[보관][삭제], 보관→[활성화][삭제], 활성화 복귀 — 2상태 게이트 단일 출처(#5)."""
    ctrl, _, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]

    ctrl.dispatch("archive", {"key": key})
    row = ctrl.snapshot()["rows"][0]
    assert row["status"] == "archived" and row["badge_label"] == "보관"
    assert row["badge_level"] == "muted"
    assert [a["key"] for a in row["actions"]] == ["activate", "delete"]

    ctrl.dispatch("activate", {"key": key})
    assert ctrl.snapshot()["rows"][0]["status"] == "active"


def test_retire_action_is_rejected_loudly(tmp_path):
    """폐기된 retire 액션(#5)은 웹 경계에서 loud ValueError — 조용한 무반응 금지."""
    ctrl, _, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    with pytest.raises(ValueError, match="알 수 없는 pool 액션"):
        ctrl.dispatch("retire", {"key": ctrl.snapshot()["rows"][0]["key"]})


def test_delete_two_phase_confirm_roundtrip(tmp_path):
    """1차=needs_confirm(무변형·원본 미삭제 재진술), 2차 confirm=삭제. 조용한 파괴 금지."""
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]

    res1 = ctrl.dispatch("delete", {"key": key})
    assert res1["needs_confirm"] is True
    assert "원본 파일은 지우지 않습니다" in res1["confirm_text"]
    assert "발주" in res1["confirm_text"]  # 사람 어휘(라벨) 재진술
    assert reg.exists(key)  # 1차는 무변형

    ctrl.dispatch("delete", {"key": key, "confirm": True})
    assert not reg.exists(key)
    assert ctrl.snapshot()["empty"] is True


def test_confirmed_relabel_does_not_resurrect_concurrently_deleted_item(tmp_path):
    """라벨 갱신 확인은, 확인 중 삭제된 항목의 신규 생성 승인으로 변하지 않는다."""
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/a.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]
    first = ctrl.dispatch("register_excel", {"name": "발주 최신", "path": "C:/data/a.xlsx"})
    assert first["needs_confirm"] is True

    DatasetPoolRegistry(reg.directory).delete(key)
    second = ctrl.dispatch(
        "register_excel", {"name": "발주 최신", "path": "C:/data/a.xlsx", "confirm": True}
    )

    assert second["ok"] is False and "삭제" in second["error"]
    assert not reg.exists(key)
    assert ctrl.snapshot()["rows"] == []  # 신규 생성으로 부활하지 않았다


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
    reg.add(DatasetPoolItem(name="살아있음", kind="excel", opts={"path": "C:/a.xlsx"}))
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
    assert ctrl.snapshot()["rows"] == []              # 등록되지 않음(모호 참조 방지)
    # 시트를 지정하면 통과 — 확정 시트가 참조에 남는다.
    res2 = ctrl.dispatch(
        "register_excel", {"name": "확정", "path": str(MULTI_SHEET), "sheet": "낙찰현황"})
    assert res2["ok"] is True
    key = ctrl.snapshot()["rows"][0]["key"]
    assert reg.load(key).opts["sheet"] == "낙찰현황"


def test_existing_nara_item_is_shown_not_hidden(tmp_path):
    """나라 등록은 동결로 미노출이지만, 기존 nara 항목은 숨기지 않고 표시한다(조용한 은닉 금지)."""
    ctrl, reg, _ = _controller(tmp_path)
    reg.add(DatasetPoolItem(
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
    reg.add(DatasetPoolItem(
        name="나라7월", kind="nara",
        opts={"bgn_dt": "202607010000", "end_dt": "202607080000"}))
    ctrl.dispatch("refresh", {})
    row = ctrl.snapshot()["rows"][0]
    assert row["missing"] is False and row["locate_path"] == ""


# ------------------------------------------------- 다시 연결 액션(#67 → §5.3 키 재편)
def test_relink_two_phase_keeps_slot_and_lifecycle(tmp_path):
    """relink 1차=기존→새 참조 재진술(무변형), confirm=같은 슬롯의 참조 교체(수명 보존)."""
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx", "note": "7월분"})
    key = ctrl.snapshot()["rows"][0]["key"]
    ctrl.dispatch("archive", {"key": key})  # 보관 수명이 재연결에도 보존되는지 본다

    res1 = ctrl.dispatch("relink", {"key": key, "path": "C:/d/이동된.xlsx", "sheet": ""})
    assert res1["needs_confirm"] is True
    assert "a.xlsx" in res1["confirm_text"] and "이동된.xlsx" in res1["confirm_text"]
    assert reg.load(key).opts["path"] == "C:/d/a.xlsx"  # 1차는 무변형

    res2 = ctrl.dispatch(
        "relink", {"key": key, "path": "C:/d/이동된.xlsx", "sheet": "", "confirm": True})
    assert res2["ok"] is True
    updated = reg.load(key)
    assert updated.opts["path"] == "C:/d/이동된.xlsx"
    assert updated.status == "archived"   # 수명 보존 — 조용한 재활성화 금지
    assert updated.note == "7월분"        # 빈 메모 입력 = 진술 없음(보존)


def test_relink_rejects_identity_of_another_slot(tmp_path):
    """다른 슬롯이 이미 가리키는 데이터로는 재연결 못 한다 — 같은 데이터 2건 봉쇄(loud)."""
    ctrl, _, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "A", "path": "C:/d/a.xlsx"})
    ctrl.dispatch("register_excel", {"name": "B", "path": "C:/d/b.xlsx"})
    rows = {r["name"]: r for r in ctrl.snapshot()["rows"]}
    res = ctrl.dispatch(
        "relink", {"key": rows["B"]["key"], "path": "C:/d/a.xlsx", "sheet": "", "confirm": True})
    assert res["ok"] is False and "이미" in res["error"]
    assert ctrl.snapshot()["result"]["level"] == "danger"


# ------------------------------------------------- 구판 병합(§5.3 마이그레이션 loud 경로)
def _legacy_write(reg: DatasetPoolRegistry, name: str, path: str) -> None:
    """구판(이름 slug 파일명) .dataset.json 을 그대로 흉내낸다 — 마이그레이션 입력."""
    import json as _json

    reg.directory.mkdir(parents=True, exist_ok=True)
    item = DatasetPoolItem(name=name, kind="excel", opts={"path": path})
    (reg.directory / f"{name}{reg.SUFFIX}").write_text(
        _json.dumps(item.to_dict(), ensure_ascii=False), encoding="utf-8"
    )


def test_legacy_duplicates_surface_loudly_in_snapshot(tmp_path):
    """다른 이름·같은 경로 2건(구판 잔재)은 숨기지 않고 duplicates 로 재진술된다."""
    ctrl, reg, _ = _controller(tmp_path)
    _legacy_write(reg, "7월 공고", "C:/d/same.xlsx")
    _legacy_write(reg, "공고 최신", "C:/d/same.xlsx")
    ctrl.dispatch("refresh", {})
    snap = ctrl.snapshot()
    assert len(snap["rows"]) == 2                       # 병합 전에도 둘 다 목록에 산다
    assert len(snap["duplicates"]) == 1
    group = snap["duplicates"][0]
    assert {e["name"] for e in group["entries"]} == {"7월 공고", "공고 최신"}
    assert "same.xlsx" in group["reference"]


def test_resolve_duplicate_two_phase_confirm(tmp_path):
    """병합은 1차=무엇이 남고 지워지는지 재진술(무변형), confirm 시에만 나머지 삭제.

    확정은 1차가 재진술한 멤버 키 집합(``group_keys``)을 되실어 보낸다 — 승인의 대상이
    「그 집합」임을 백엔드가 대조한다(코덱스 1R P1).
    """
    ctrl, reg, _ = _controller(tmp_path)
    _legacy_write(reg, "7월 공고", "C:/d/same.xlsx")
    _legacy_write(reg, "공고 최신", "C:/d/same.xlsx")
    ctrl.dispatch("refresh", {})
    keep = next(
        e["key"] for e in ctrl.snapshot()["duplicates"][0]["entries"]
        if e["name"] == "공고 최신"
    )

    res1 = ctrl.dispatch("resolve_duplicate", {"keep": keep})
    assert res1["needs_confirm"] is True
    assert "'공고 최신'" in res1["confirm_text"]        # 남는 것
    assert "'7월 공고'" in res1["confirm_text"]          # 지워지는 것 — 둘 다 재진술
    assert sorted(res1["group_keys"]) == sorted(
        e["key"] for e in ctrl.snapshot()["duplicates"][0]["entries"]
    )                                                    # 승인 대상 = 멤버 키 집합
    assert len(ctrl.snapshot()["rows"]) == 2             # 1차는 무변형

    res2 = ctrl.dispatch(
        "resolve_duplicate",
        {"keep": keep, "confirm": True, "group_keys": res1["group_keys"]},
    )
    assert res2["ok"] is True and res2["kept"] == "공고 최신" and res2["removed"] == 1
    snap = ctrl.snapshot()
    assert [r["name"] for r in snap["rows"]] == ["공고 최신"]
    assert snap["duplicates"] == []


def test_resolve_duplicate_stale_group_is_restated(tmp_path):
    """확인 사이 그룹이 사라졌으면(다른 표면의 삭제) 낡은 확정을 실행하지 않고 재진술한다."""
    ctrl, reg, _ = _controller(tmp_path)
    _legacy_write(reg, "7월 공고", "C:/d/same.xlsx")
    _legacy_write(reg, "공고 최신", "C:/d/same.xlsx")
    ctrl.dispatch("refresh", {})
    entries = ctrl.snapshot()["duplicates"][0]["entries"]
    keep = entries[0]["key"]
    res1 = ctrl.dispatch("resolve_duplicate", {"keep": keep})
    DatasetPoolRegistry(reg.directory).delete(entries[1]["key"])  # 다른 표면이 먼저 정리

    res = ctrl.dispatch(
        "resolve_duplicate",
        {"keep": keep, "confirm": True, "group_keys": res1["group_keys"]},
    )
    assert res["ok"] is False and "중복" in res["error"]
    assert len(ctrl.snapshot()["rows"]) == 1  # 남은 항목은 건드리지 않았다


def test_resolve_duplicate_refuses_when_group_grew_after_confirm(tmp_path):
    """확인 사이 같은 정체성의 등록이 **늘었으면** 삭제 0건 + loud 재진술(코덱스 1R P1).

    재조회 결과를 그대로 채택하면 사용자가 삭제된다고 들은 적 없는 셋째 등록이 drop 에
    조용히 포함된다 — 승인한 집합과 지금 집합이 다르면 아무것도 지우지 않는다.
    """
    ctrl, reg, _ = _controller(tmp_path)
    _legacy_write(reg, "7월 공고", "C:/d/same.xlsx")
    _legacy_write(reg, "공고 최신", "C:/d/same.xlsx")
    ctrl.dispatch("refresh", {})
    keep = next(
        e["key"] for e in ctrl.snapshot()["duplicates"][0]["entries"]
        if e["name"] == "공고 최신"
    )
    res1 = ctrl.dispatch("resolve_duplicate", {"keep": keep})
    assert res1["needs_confirm"] is True

    _legacy_write(reg, "셋째 등록", "C:/d/same.xlsx")     # 확인 사이 다른 writer 의 추가

    res2 = ctrl.dispatch(
        "resolve_duplicate",
        {"keep": keep, "confirm": True, "group_keys": res1["group_keys"]},
    )
    assert res2["ok"] is False and "바뀌어" in res2["error"]
    assert ctrl.snapshot()["result"]["level"] == "danger"
    assert len(ctrl.snapshot()["rows"]) == 3              # 삭제 0건 — 셋째 등록 무사
    # 새 집합으로 다시 확인하면 성사된다(거절은 재확인 요구이지 막다른길이 아니다).
    res3 = ctrl.dispatch("resolve_duplicate", {"keep": keep})
    assert res3["needs_confirm"] is True and len(res3["group_keys"]) == 3
    res4 = ctrl.dispatch(
        "resolve_duplicate",
        {"keep": keep, "confirm": True, "group_keys": res3["group_keys"]},
    )
    assert res4["ok"] is True and res4["removed"] == 2


def test_resolve_duplicate_confirm_without_basis_is_refused(tmp_path):
    """근거(group_keys) 미동봉 확정은 fail-closed — 무엇을 승인했는지 모르는 삭제 금지."""
    ctrl, reg, _ = _controller(tmp_path)
    _legacy_write(reg, "7월 공고", "C:/d/same.xlsx")
    _legacy_write(reg, "공고 최신", "C:/d/same.xlsx")
    ctrl.dispatch("refresh", {})
    keep = ctrl.snapshot()["duplicates"][0]["entries"][0]["key"]
    res = ctrl.dispatch("resolve_duplicate", {"keep": keep, "confirm": True})
    assert res["ok"] is False and "다시 확인" in res["error"]
    assert len(ctrl.snapshot()["rows"]) == 2              # 삭제 0건
