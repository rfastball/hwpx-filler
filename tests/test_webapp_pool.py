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

from hwpxfiller.domain.dataset_reference import DatasetReference
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.webapp.screen_pool import PoolController


def _controller(tmp_path: Path) -> "tuple[PoolController, DatasetPoolRegistry, list]":
    pushes: list = []
    reg = DatasetPoolRegistry(tmp_path / "datasets")
    ctrl = PoolController(reg, lambda s, snap: pushes.append((s, snap)))
    return ctrl, reg, pushes


def test_initial_then_registration_serializes_and_pushes(tmp_path):
    ctrl, reg, pushes = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["rows"] == []
    assert snap["empty"] is True
    assert snap["count"] == ""
    assert snap["result"]["text"] == ""
    res = ctrl.dispatch(
        "register_excel",
        {"name": "발주 7월", "path": "C:/data/발주.xlsx", "sheet": "낙찰현황"},
    )
    assert res["ok"] is True and res["name"] == "발주 7월"
    assert pushes and pushes[-1][0] == "pool"  # 액션 후 관측 푸시
    row = pushes[-1][1]["rows"][0]
    assert row["name"] == "발주 7월"
    assert row["kind_label"] == "엑셀/CSV"
    assert row["status"] == "active" and row["badge_label"] == "활성"
    assert "발주.xlsx" in row["reference"]
    assert row["sheet"] == "낙찰현황"
    assert reg.load(row["key"]).opts["sheet"] == "낙찰현황"
    # 상태 게이트: 활성 → [보관][삭제].
    assert [a["key"] for a in row["actions"]] == ["archive", "delete"]
    assert ctrl.snapshot()["result"]["level"] == "ok"


def test_same_data_reregister_is_relabel_not_second_entry(tmp_path):
    """같은 데이터(경로+시트) 재등록은 2건이 아니라 기존 등록의 라벨 갱신이다(§5.3 C).

    1차는 기존 이름을 재진술하는 확인 승격, confirm 시에만 라벨·메모가 갱신된다 —
    참조는 바뀔 수 없다(정체성이 곧 참조).
    """
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/a.xlsx"})
    assert "추가했습니다" in ctrl.snapshot()["result"]["text"]  # 신규 = 추가

    noop = ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/a.xlsx"})
    assert noop["ok"] is True and "needs_confirm" not in noop
    assert "이미 고정돼 있습니다" in ctrl.snapshot()["result"]["text"]

    res1 = ctrl.dispatch("register_excel", {"name": "발주 최신", "path": "C:/data/a.xlsx"})
    assert res1["needs_confirm"] is True


    assert "'발주'" in res1["confirm_text"]      # 기존 이름 재진술
    assert "a.xlsx" in res1["confirm_text"]      # 기존 참조 요약 재진술
    assert res1["basis"]                         # 승인 대상 = 그 등록의 지금 상태
    assert [r.name for r in ctrl.vm.rows()] == ["발주"]  # 1차는 무변형

    res2 = ctrl.dispatch(
        "register_excel",
        {"name": "발주 최신", "path": "C:/data/a.xlsx", "confirm": True,
         "basis": res1["basis"]})
    assert res2["ok"] is True
    rows = ctrl.snapshot()["rows"]
    assert len(rows) == 1                        # 2건이 되지 않는다
    assert rows[0]["name"] == "발주 최신"
    assert reg.load(rows[0]["key"]).opts["path"] == "C:/data/a.xlsx"  # 참조 불변
    assert "갱신했습니다" in ctrl.snapshot()["result"]["text"]


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

    ctrl.dispatch("delete", {"key": key, "confirm": True, "basis": res1["basis"]})
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


def test_removed_and_unknown_actions_are_loud(tmp_path):
    ctrl, _, _ = _controller(tmp_path)
    for action in ("retire", "drop_all"):
        with pytest.raises(ValueError, match="알 수 없는 pool 액션"):
            ctrl.dispatch(action, {})


MULTI_SHEET = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "multi_sheet.xlsx"


def test_corrupt_pool_file_is_quarantined_not_boot_crash(tmp_path):
    """손상 .dataset.json 1개가 화면·부팅을 죽이지 않고 격리·표면화된다(RC-05, #26 #2).

    예전엔 list_items 가 예외를 전파했고 어떤 호출측도 잡지 않아 컨트롤러 생성(=앱 부팅
    경로, 7화면 전부)이 손상 파일 하나로 무너졌다. 지금은 정상 항목이 살고 손상은 재진술된다.
    """
    reg = DatasetPoolRegistry(tmp_path / "datasets")
    reg.add(DatasetReference(name="살아있음", kind="excel", opts={"path": "C:/a.xlsx"}))
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
    reg.add(DatasetReference(
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
    ctrl, reg, _ = _controller(tmp_path)
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
    reg.add(DatasetReference(
        name="나라7월", kind="nara",
        opts={"bgn_dt": "202607010000", "end_dt": "202607080000"}))
    ctrl.dispatch("refresh", {})
    nara = next(row for row in ctrl.snapshot()["rows"] if row["name"] == "나라7월")
    assert nara["missing"] is False and nara["locate_path"] == ""


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
    assert res1["basis"]                               # 승인 대상 = 이 슬롯의 지금 상태
    assert reg.load(key).opts["path"] == "C:/d/a.xlsx"  # 1차는 무변형

    res2 = ctrl.dispatch(
        "relink", {"key": key, "path": "C:/d/이동된.xlsx", "sheet": "",
                   "confirm": True, "basis": res1["basis"]})
    assert res2["ok"] is True
    updated = reg.load(key)
    assert updated.opts["path"] == "C:/d/이동된.xlsx"
    assert updated.status == "archived"   # 수명 보존 — 조용한 재활성화 금지
    assert updated.note == "7월분"        # 빈 메모 입력 = 진술 없음(보존)


def test_data_released_by_a_relink_can_be_pinned_again(tmp_path):
    """A 고정 → B 로 재연결 → **A 다시 고정**이 성사된다(코덱스 4R P2, 표면 왕복).

    「지금 아무도 안 쓰는 데이터」가 옛 슬롯 키 점유 때문에 거절되던 자리 — 사용자에게는
    존재하지 않는 항목과 충돌한다는 말로 보였다. 실제 중복은 여전히 갱신 확정으로 접힌다.
    """
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "보고", "path": "C:/A.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]
    first = ctrl.dispatch("relink", {"key": key, "path": "C:/B.xlsx", "sheet": ""})
    assert ctrl.dispatch(
        "relink", {"key": key, "path": "C:/B.xlsx", "sheet": "",
                   "confirm": True, "basis": first["basis"]})["ok"] is True

    res = ctrl.dispatch("register_excel", {"name": "A 재고정", "path": "C:/A.xlsx"})
    assert res["ok"] is True and "needs_confirm" not in res, res
    names = sorted(r["name"] for r in ctrl.snapshot()["rows"])
    assert names == ["A 재고정", "보고"]
    assert ctrl.snapshot()["duplicates"] == []
    # 대조군 — 실제 중복(현재 B 를 쓰는 항목이 있는데 또 B)은 라벨 갱신 확정으로 접힌다.
    dup = ctrl.dispatch("register_excel", {"name": "B 재고정", "path": "C:/B.xlsx"})
    assert dup.get("needs_confirm") is True and "'보고'" in dup["confirm_text"]
    assert len(ctrl.snapshot()["rows"]) == 2             # 3건이 되지 않는다


def test_relink_rejects_identity_of_another_slot(tmp_path):
    """다른 슬롯이 이미 가리키는 데이터로는 재연결 못 한다 — 같은 데이터 2건 봉쇄(loud)."""
    ctrl, _, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "A", "path": "C:/d/a.xlsx"})
    ctrl.dispatch("register_excel", {"name": "B", "path": "C:/d/b.xlsx"})
    rows = {r["name"]: r for r in ctrl.snapshot()["rows"]}
    key_b = rows["B"]["key"]
    first = ctrl.dispatch("relink", {"key": key_b, "path": "C:/d/a.xlsx", "sheet": ""})
    res = ctrl.dispatch(
        "relink", {"key": key_b, "path": "C:/d/a.xlsx", "sheet": "",
                   "confirm": True, "basis": first["basis"]})
    assert res["ok"] is False and "이미" in res["error"]
    assert ctrl.snapshot()["result"]["level"] == "danger"


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("reference", lambda it: it.opts.update({"path": "C:/d/남이바꾼.xlsx"})),
        ("name", lambda it: setattr(it, "name", "남이 개명")),
        ("note", lambda it: setattr(it, "note", "남이 단 메모")),
        ("status", lambda it: it.archive()),
    ],
)
def test_relink_refuses_when_the_slot_changed_under_the_modal(tmp_path, field, mutate):
    """확인 사이 같은 슬롯이 재연결·개명됐으면 덮어쓰기 0건 + loud 재진술(코덱스 2R P2).

    정체성 검사는 「새 참조가 남의 것인가」만 보므로 이 자리를 못 잡는다 — 사용자가 승인한
    것은 **1차가 보여준 그 슬롯 상태**이지 슬롯 키가 아니다. 병합과 **같은 결속 기제**
    (basis)를 쓰므로 두 경로가 함께 닫힌다.
    """
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx", "note": "6월분"})
    key = ctrl.snapshot()["rows"][0]["key"]
    res1 = ctrl.dispatch("relink", {"key": key, "path": "C:/d/새것.xlsx", "sheet": ""})
    assert res1["needs_confirm"] is True

    DatasetPoolRegistry(reg.directory).mutate(key, mutate)  # 다른 호출이 먼저 손댔다
    before = reg.load(key).to_dict()

    res2 = ctrl.dispatch(
        "relink", {"key": key, "path": "C:/d/새것.xlsx", "sheet": "",
                   "confirm": True, "basis": res1["basis"]})
    assert res2["ok"] is False and "바뀌어" in res2["error"], field
    assert ctrl.snapshot()["result"]["level"] == "danger"
    assert reg.load(key).to_dict() == before, f"{field} 변경 뒤에도 고지 없이 덮었습니다."
    # 재확인은 새 상태 기준으로 성사된다(거절 = 재확인 요구이지 막다른길이 아니다).
    res3 = ctrl.dispatch("relink", {"key": key, "path": "C:/d/새것.xlsx", "sheet": ""})
    res4 = ctrl.dispatch(
        "relink", {"key": key, "path": "C:/d/새것.xlsx", "sheet": "",
                   "confirm": True, "basis": res3["basis"]})
    assert res4["ok"] is True
    assert reg.load(key).opts["path"] == "C:/d/새것.xlsx"


def test_relink_confirm_without_basis_is_refused(tmp_path):
    """근거(basis) 미동봉 relink 확정도 fail-closed — 병합과 같은 계약 하나."""
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]
    res = ctrl.dispatch(
        "relink", {"key": key, "path": "C:/d/새것.xlsx", "sheet": "", "confirm": True})
    assert res["ok"] is False and "다시 확인" in res["error"]
    assert reg.load(key).opts["path"] == "C:/d/a.xlsx"   # 덮어쓰기 0건


def test_relink_refuses_when_only_the_directory_changed_under_the_modal(tmp_path):
    """확인 사이 같은 파일명·다른 폴더로 재연결되면 덮어쓰기 0건 + loud(코덱스 3R P2-1).

    ``/a/report.xlsx`` → ``/b/report.xlsx`` 는 표시 요약(basename+시트)이 **같다** —
    결속 재료가 그 요약이면 지문이 그대로라 옛 확정이 더 새로운 참조를 덮는다. 지문이
    정규화 경로 전체를 들기 때문에 여기서 걸린다.
    """
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "보고", "path": "C:/a/report.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]
    res1 = ctrl.dispatch("relink", {"key": key, "path": "C:/새것/report.xlsx", "sheet": ""})
    assert res1["needs_confirm"] is True

    # 다른 호출이 먼저 폴더만 다른 같은 이름 파일로 재연결(표시 요약은 불변).
    other = ctrl.dispatch("relink", {"key": key, "path": "C:/b/report.xlsx", "sheet": ""})
    assert ctrl.dispatch(
        "relink", {"key": key, "path": "C:/b/report.xlsx", "sheet": "",
                   "confirm": True, "basis": other["basis"]})["ok"] is True
    assert reg.load(key).opts["path"] == "C:/b/report.xlsx"

    res2 = ctrl.dispatch(
        "relink", {"key": key, "path": "C:/새것/report.xlsx", "sheet": "",
                   "confirm": True, "basis": res1["basis"]})
    assert res2["ok"] is False and "바뀌어" in res2["error"]
    assert reg.load(key).opts["path"] == "C:/b/report.xlsx"   # 덮어쓰기 0건


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("name", lambda it: setattr(it, "name", "남이 개명")),
        ("note", lambda it: setattr(it, "note", "남이 단 메모")),
        ("status", lambda it: it.archive()),
    ],
)
def test_relabel_refuses_when_metadata_changed_under_the_modal(tmp_path, field, mutate):
    """라벨 갱신 확정도 표시된 메타에 결속된다 — 확인 중 변경 시 덮어쓰기 0건(3R P2-2).

    정체성(path+sheet)만 확인하는 확정은 더 새로운 이름·비고를 무조건 덮는다. 사용자가
    승인한 것은 1차가 보여준 **옛 라벨**이므로, 달라졌으면 아무것도 갱신하지 않는다.
    """
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx", "note": "6월분"})
    key = ctrl.snapshot()["rows"][0]["key"]
    res1 = ctrl.dispatch("register_excel", {"name": "발주 최신", "path": "C:/d/a.xlsx"})
    assert res1["needs_confirm"] is True

    DatasetPoolRegistry(reg.directory).mutate(key, mutate)   # 다른 호출이 먼저 손댔다
    before = reg.load(key).to_dict()

    res2 = ctrl.dispatch(
        "register_excel",
        {"name": "발주 최신", "path": "C:/d/a.xlsx", "confirm": True, "basis": res1["basis"]},
    )
    assert res2["ok"] is False and "바뀌어" in res2["error"], field
    assert ctrl.snapshot()["result"]["level"] == "danger"
    assert reg.load(key).to_dict() == before, f"{field} 변경 뒤에도 고지 없이 덮었습니다."


def test_relabel_confirm_without_basis_is_refused(tmp_path):
    """근거 미동봉 라벨 갱신 확정도 fail-closed — 네 확정이 같은 계약을 상속한다."""
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]
    res = ctrl.dispatch(
        "register_excel", {"name": "발주 최신", "path": "C:/d/a.xlsx", "confirm": True})
    assert res["ok"] is False and "다시 확인" in res["error"]
    assert reg.load(key).name == "발주"                  # 갱신 0건


def test_delete_refuses_when_the_slot_changed_under_the_modal(tmp_path):
    """삭제 확정도 같은 결속을 쓴다 — 확인 중 재연결·개명되면 삭제 0건 + loud(3R 인구조사).

    파괴 앞에서 「무엇을 지우는지」가 승인 시점과 갈리면 그게 조용한 파괴다.
    """
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]
    res1 = ctrl.dispatch("delete", {"key": key})
    assert res1["needs_confirm"] is True and res1["basis"]

    DatasetPoolRegistry(reg.directory).mutate(key, lambda it: setattr(it, "name", "남이 개명"))

    res2 = ctrl.dispatch("delete", {"key": key, "confirm": True, "basis": res1["basis"]})
    assert res2["ok"] is False and "바뀌어" in res2["error"]
    assert reg.exists(key)                               # 삭제 0건
    # 새 상태로 다시 확인하면 성사된다.
    res3 = ctrl.dispatch("delete", {"key": key})
    assert ctrl.dispatch(
        "delete", {"key": key, "confirm": True, "basis": res3["basis"]})["ok"] is True
    assert not reg.exists(key)


def test_delete_confirm_without_basis_is_refused(tmp_path):
    """근거 미동봉 삭제 확정도 fail-closed."""
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/d/a.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]
    res = ctrl.dispatch("delete", {"key": key, "confirm": True})
    assert res["ok"] is False and "다시 확인" in res["error"]
    assert reg.exists(key)                               # 삭제 0건


# ------------------------------------------------- 구판 병합(§5.3 마이그레이션 loud 경로)
def _legacy_write(reg: DatasetPoolRegistry, name: str, path: str) -> None:
    """구판(이름 slug 파일명) .dataset.json 을 그대로 흉내낸다 — 마이그레이션 입력."""
    import json as _json

    reg.directory.mkdir(parents=True, exist_ok=True)
    item = DatasetReference(name=name, kind="excel", opts={"path": path})
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

    확정은 1차가 재진술한 **상태의 지문**(``basis``)을 되실어 보낸다 — 승인의 대상이
    「그때 읽은 값」임을 백엔드가 대조한다(코덱스 1R·2R 근본 조치).
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
    assert res1["basis"]                                 # 승인 대상 = 보여준 상태의 지문
    assert len(ctrl.snapshot()["rows"]) == 2             # 1차는 무변형

    res2 = ctrl.dispatch(
        "resolve_duplicate", {"keep": keep, "confirm": True, "basis": res1["basis"]},
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
        "resolve_duplicate", {"keep": keep, "confirm": True, "basis": res1["basis"]},
    )
    assert res["ok"] is False and "중복" in res["error"]
    assert len(ctrl.snapshot()["rows"]) == 1  # 남은 항목은 건드리지 않았다


def test_resolve_duplicate_refuses_when_group_grew_after_confirm(tmp_path):
    """확인 사이 같은 정체성의 등록이 **늘었으면** 삭제 0건 + loud 재진술(코덱스 1R P1).

    재조회 결과를 그대로 채택하면 사용자가 삭제된다고 들은 적 없는 셋째 등록이 drop 에
    조용히 포함된다 — 승인한 상태와 지금 상태가 다르면 아무것도 지우지 않는다.
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
        "resolve_duplicate", {"keep": keep, "confirm": True, "basis": res1["basis"]},
    )
    assert res2["ok"] is False and "바뀌어" in res2["error"]
    assert ctrl.snapshot()["result"]["level"] == "danger"
    assert len(ctrl.snapshot()["rows"]) == 3              # 삭제 0건 — 셋째 등록 무사
    # 새 상태로 다시 확인하면 성사된다(거절은 재확인 요구이지 막다른길이 아니다).
    res3 = ctrl.dispatch("resolve_duplicate", {"keep": keep})
    assert res3["needs_confirm"] is True and res3["basis"] != res1["basis"]
    res4 = ctrl.dispatch(
        "resolve_duplicate", {"keep": keep, "confirm": True, "basis": res3["basis"]},
    )
    assert res4["ok"] is True and res4["removed"] == 2


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("name", lambda it: setattr(it, "name", "밖에서 개명")),
        ("note", lambda it: setattr(it, "note", "밖에서 단 메모")),
        ("reference", lambda it: it.opts.update({"sheet": "밖에서 지정"})),
        ("status", lambda it: it.archive()),
        ("kind", lambda it: setattr(it, "kind", "pipeline")),
    ],
)
def test_resolve_duplicate_refuses_when_any_shown_field_changed(tmp_path, field, mutate):
    """확인 사이 멤버의 **어떤 성분이라도** 바뀌면 삭제 0건 + loud 재진술(코덱스 2R P1).

    키와 정체성은 그대로인 채 이름·비고만 바뀌어도, 지워지는 것은 사용자가 본 적 없는
    내용의 등록이다 — 결속 단위가 키 집합이면 이 자리가 조용히 통과한다. 성분을 열거로
    관리하지 않도록 :data:`SHOWN_FIELDS` 전체를 순회한다(참조·종류처럼 정체성 축을 함께
    건드리는 변경은 그룹 해소 분기로, 나머지는 지문 불일치로 — 둘 다 파괴 0건이 계약이다).
    """
    ctrl, reg, _ = _controller(tmp_path)
    _legacy_write(reg, "7월 공고", "C:/d/same.xlsx")
    _legacy_write(reg, "공고 최신", "C:/d/same.xlsx")
    ctrl.dispatch("refresh", {})
    entries = ctrl.snapshot()["duplicates"][0]["entries"]
    keep = entries[0]["key"]
    victim = entries[1]["key"]
    res1 = ctrl.dispatch("resolve_duplicate", {"keep": keep})
    assert res1["needs_confirm"] is True

    DatasetPoolRegistry(reg.directory).mutate(victim, mutate)  # 다른 writer 의 내용 변경

    res2 = ctrl.dispatch(
        "resolve_duplicate", {"keep": keep, "confirm": True, "basis": res1["basis"]},
    )
    assert res2["ok"] is False and res2["error"], field
    assert ctrl.snapshot()["result"]["level"] == "danger"
    assert reg.exists(victim), f"{field} 변경 뒤에도 고지 없이 삭제됐습니다."
    assert reg.exists(keep)


def test_confirm_basis_is_not_derived_from_the_display_summary(tmp_path):
    """지문은 **표시 요약에서 파생되지 않는다** — 요약은 정보를 버리는 함수다(코덱스 3R).

    ``reference_summary`` 는 경로를 basename 으로 줄이므로 ``/a/report.xlsx`` 와
    ``/b/report.xlsx`` 가 같은 문자열이 된다. 결속 재료가 그 요약이면 경로만 다른
    재연결이 지문을 통과한다 — 지문은 표시보다 **정보를 덜 잃어야** 한다.
    """
    from hwpxfiller.application.dataset_pool import reference_summary
    from hwpxfiller.webapp.screen_pool import bound_state, confirm_basis, display_reference

    a = DatasetReference(name="발주", kind="excel", opts={"path": "/a/report.xlsx"})
    b = DatasetReference(name="발주", kind="excel", opts={"path": "/b/report.xlsx"})
    # 표시 요약은 둘을 구별하지 못한다(그래서 결속 재료가 될 수 없다).
    assert display_reference(a) == display_reference(b) == reference_summary(a)
    # 지문은 구별한다.
    assert confirm_basis([bound_state("k", a)]) != confirm_basis([bound_state("k", b)])
    # 정체성 밖 opts(읽기 규칙 등)도 결속에 든다 — 정체성만 들면 통과하던 자리.
    c = DatasetReference(name="발주", kind="excel", opts={"path": "/a/report.xlsx", "header_row": 3})
    assert confirm_basis([bound_state("k", a)]) != confirm_basis([bound_state("k", c)])


def test_confirm_texts_and_basis_share_the_same_item(tmp_path):
    """재진술 문안과 지문은 **같은 항목**에서 나온다 — 선언과 결과의 분리 금지.

    문안은 사람이 읽는 표시 요약을, 지문은 정보를 덜 잃는 전체 값을 쓰되 **소재는 하나**
    (그 시점의 디스크 항목)여야 한다. 소재가 갈리면 「보여준 것」과 「대조하는 것」이
    어긋나고, 그 틈이 라운드마다 반복된 결함이었다. 네 확정 경로 전부가 대상이다.
    """
    from hwpxfiller.webapp.screen_pool import (
        BOUND_FIELDS,
        bound_state,
        confirm_basis,
        display_reference,
    )

    ctrl, reg, _ = _controller(tmp_path)
    _legacy_write(reg, "7월 공고", "C:/d/same.xlsx")
    _legacy_write(reg, "공고 최신", "C:/d/same.xlsx")
    ctrl.dispatch("refresh", {})
    entries = ctrl.snapshot()["duplicates"][0]["entries"]
    keep = entries[0]["key"]
    states = [bound_state(e["key"], reg.load(e["key"])) for e in entries]

    merge = ctrl.dispatch("resolve_duplicate", {"keep": keep})
    for e in entries:                                   # 문안이 이름 전부를 재진술
        assert e["name"] in merge["confirm_text"]
    assert display_reference(reg.load(keep)) in merge["confirm_text"]
    assert merge["basis"] == confirm_basis(states)      # 지문은 같은 항목들의 전체 값

    relink = ctrl.dispatch("relink", {"key": keep, "path": "C:/d/new.xlsx", "sheet": ""})
    keep_state = bound_state(keep, reg.load(keep))
    assert reg.load(keep).name in relink["confirm_text"]
    assert display_reference(reg.load(keep)) in relink["confirm_text"]
    assert relink["basis"] == confirm_basis([keep_state])

    delete = ctrl.dispatch("delete", {"key": keep})
    assert display_reference(reg.load(keep)) in delete["confirm_text"]
    assert delete["basis"] == confirm_basis([keep_state])

    relabel = ctrl.dispatch(
        "register_excel", {"name": "새 라벨", "path": "C:/d/same.xlsx", "sheet": ""})
    same_key, same_item = ctrl.vm.find_same_data("C:/d/same.xlsx", "")
    assert same_item.name in relabel["confirm_text"]
    assert relabel["basis"] == confirm_basis([bound_state(same_key, same_item)])
    # 성분 목록은 단일 출처다(경로마다 다른 성분을 쓰면 그 자리가 다음 구멍이다).
    assert tuple(keep_state) == BOUND_FIELDS


def test_resolve_duplicate_confirm_without_basis_is_refused(tmp_path):
    """근거(basis) 미동봉 확정은 fail-closed — 무엇을 승인했는지 모르는 삭제 금지."""
    ctrl, reg, _ = _controller(tmp_path)
    _legacy_write(reg, "7월 공고", "C:/d/same.xlsx")
    _legacy_write(reg, "공고 최신", "C:/d/same.xlsx")
    ctrl.dispatch("refresh", {})
    keep = ctrl.snapshot()["duplicates"][0]["entries"][0]["key"]
    res = ctrl.dispatch("resolve_duplicate", {"keep": keep, "confirm": True})
    assert res["ok"] is False and "다시 확인" in res["error"]
    assert len(ctrl.snapshot()["rows"]) == 2              # 삭제 0건


def test_noop_reregister_report_survives_concurrent_delete(tmp_path):
    """무변경 재등록의 「이미 고정」 보고는 잠금 안 재검증을 지난다(코덱스 #578 P2).

    find 스냅샷과 보고 사이에 다른 스레드가 슬롯을 지우면 — 거짓 성사 대신
    기존 stale 접기(부활 없음·loud)로 갈린다.
    """
    ctrl, reg, _ = _controller(tmp_path)
    ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/a.xlsx"})
    key = ctrl.snapshot()["rows"][0]["key"]
    stale = (key, reg.load(key))

    reg.delete(key)  # 확인 사이 다른 화면의 삭제 모사
    ctrl.vm.find_same_data = lambda path, sheet=None: stale  # find 시점 스냅샷 고정

    res = ctrl.dispatch("register_excel", {"name": "발주", "path": "C:/data/a.xlsx"})
    assert res["ok"] is False
    assert "이미 고정돼 있습니다" not in ctrl.snapshot()["result"]["text"]
    assert reg.list_references()[0] == []  # 부활 0건


# ------------------------------------------------- 계약 목록(pclm) 등록 표면(ADR N)
def test_register_pclm_three_branches_and_stale_confirm(tmp_path):
    """신규 추가 / 무변경 멱등 확정 / 이름 갱신 확정(결속) — 엑셀 등록의 거울이다."""
    ctrl, reg, pushes = _controller(tmp_path)
    db = str(tmp_path / "pclm.db")

    res = ctrl.dispatch("register_pclm", {"name": "계약 목록", "db": db, "view": "v_통합_v1"})
    assert res["ok"] is True and res["name"] == "계약 목록"
    assert "추가했습니다" in ctrl.snapshot()["result"]["text"]
    row = pushes[-1][1]["rows"][0]
    assert row["kind"] == "pclm" and row["kind_label"] == "계약 목록"
    assert row["reference"] == "DB: pclm.db · 시트 통합"   # 표면 어휘는 시트 + 제목
    assert row["locate_path"] == db and row["missing"] is True  # 없는 파일은 끊김으로

    noop = ctrl.dispatch("register_pclm", {"name": "계약 목록", "db": db, "view": "v_통합_v1"})
    assert noop["ok"] is True and "needs_confirm" not in noop
    assert "이미 고정돼 있습니다" in ctrl.snapshot()["result"]["text"]

    first = ctrl.dispatch("register_pclm", {"name": "통합면", "db": db, "view": "v_통합_v1"})
    assert first["needs_confirm"] is True
    assert "'계약 목록'" in first["confirm_text"]   # 기존 이름 재진술
    assert "pclm.db" in first["confirm_text"]       # 기존 참조 요약 재진술
    assert [r.name for r in ctrl.vm.rows()] == ["계약 목록"]   # 1차는 무변형

    # 확인 사이 라벨이 바뀌면 갱신 0건(결속 대조는 종류를 묻지 않는다).
    key = ctrl.snapshot()["rows"][0]["key"]
    DatasetPoolRegistry(reg.directory).relabel(key, "남이 개명")
    stale = ctrl.dispatch(
        "register_pclm",
        {"name": "통합면", "db": db, "view": "v_통합_v1", "confirm": True,
         "basis": first["basis"]})
    assert stale["ok"] is False and "다시 확인" in stale["error"]
    assert [r.name for r in ctrl.vm.rows()] == ["남이 개명"]

    fresh = ctrl.dispatch("register_pclm", {"name": "통합면", "db": db, "view": "v_통합_v1"})
    done = ctrl.dispatch(
        "register_pclm",
        {"name": "통합면", "db": db, "view": "v_통합_v1", "confirm": True,
         "basis": fresh["basis"]})
    assert done["ok"] is True
    rows = ctrl.snapshot()["rows"]
    assert len(rows) == 1 and rows[0]["name"] == "통합면"      # 2건이 되지 않는다
    assert reg.load(rows[0]["key"]).opts == {"db": db, "view": "v_통합_v1"}


def test_register_pclm_without_db_pins_the_default_place(tmp_path, monkeypatch):
    """db 를 비우면 「기본 자리」로 해석돼 opts 에 박힌다 — 조회와 등록이 같은 자리를 본다."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    # 기본 자리 해석은 %APPDATA% 쪽지(config.json)도 본다 — 개발 기기의 실제 쪽지 격리.
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    ctrl, reg, _ = _controller(tmp_path)
    res = ctrl.dispatch("register_pclm", {"name": "기본 자리", "view": "v_계약_v1"})
    assert res["ok"] is True
    key = ctrl.snapshot()["rows"][0]["key"]
    assert reg.load(key).opts == {
        "db": str(tmp_path / "AppData" / "Local" / "Pclm" / "pclm.db"),
        "view": "v_계약_v1",
    }
    # 같은 뜻의 재등록(빈 db)은 2건이 아니라 「이미 고정」으로 접힌다.
    again = ctrl.dispatch("register_pclm", {"name": "기본 자리", "view": "v_계약_v1"})
    assert again["ok"] is True and len(ctrl.snapshot()["rows"]) == 1


def test_register_pclm_unknown_view_is_worded_not_raised(tmp_path):
    """미지 뷰는 날것 예외가 아니라 사용자 문구 — 쓸 수 있는 뷰를 설명과 함께 재진술한다."""
    from hwpxfiller.domain.pclm_views import PCLM_VIEW_LABELS, PCLM_VIEWS

    ctrl, _reg, _ = _controller(tmp_path)
    res = ctrl.dispatch(
        "register_pclm", {"name": "오타", "db": "C:/d/pclm.db", "view": "v_통합"})
    assert res["ok"] is False
    assert all(view in res["error"] for view in PCLM_VIEWS)
    assert PCLM_VIEW_LABELS["v_통합_v1"] in res["error"]
    assert ctrl.snapshot()["rows"] == [] and ctrl.snapshot()["result"]["level"] == "danger"
    empty = ctrl.dispatch("register_pclm", {"name": " ", "db": "C:/d/pclm.db",
                                            "view": "v_통합_v1"})
    assert empty["ok"] is False and "이름" in empty["error"]


def test_register_pclm_confirm_does_not_resurrect_deleted_item(tmp_path):
    """확인 사이 삭제됐으면 확정을 신규 등록 승인으로 바꾸지 않는다(엑셀 판과 같은 규율)."""
    ctrl, reg, _ = _controller(tmp_path)
    db = str(tmp_path / "pclm.db")
    ctrl.dispatch("register_pclm", {"name": "계약", "db": db, "view": "v_공고_v1"})
    first = ctrl.dispatch("register_pclm", {"name": "공고면", "db": db, "view": "v_공고_v1"})
    reg.delete(ctrl.snapshot()["rows"][0]["key"])

    res = ctrl.dispatch(
        "register_pclm",
        {"name": "공고면", "db": db, "view": "v_공고_v1", "confirm": True,
         "basis": first["basis"]})
    assert res["ok"] is False and "이미 삭제된 항목" in res["error"]
    assert reg.list_references()[0] == []   # 부활 0건


def test_pclm_duplicates_merge_through_the_same_confirm_path(tmp_path):
    """같은 DB+뷰 2건(손편집 잔재)도 duplicates 로 표면화되고 확정 병합된다."""
    import json as _json

    ctrl, reg, _ = _controller(tmp_path)
    reg.directory.mkdir(parents=True, exist_ok=True)
    for slug, name in (("구판", "구판 계약"), ("최신", "최신 계약")):
        item = DatasetReference(
            name=name, kind="pclm",
            opts={"db": "C:/d/pclm.db", "view": "v_품목_v1"})
        (reg.directory / f"{slug}{reg.SUFFIX}").write_text(
            _json.dumps(item.to_dict(), ensure_ascii=False), encoding="utf-8")
    ctrl.dispatch("refresh", {})

    group = ctrl.snapshot()["duplicates"][0]
    assert "pclm.db" in group["reference"] and len(group["entries"]) == 2
    keep = next(e["key"] for e in group["entries"] if e["name"] == "최신 계약")
    res1 = ctrl.dispatch("resolve_duplicate", {"keep": keep})
    res2 = ctrl.dispatch(
        "resolve_duplicate", {"keep": keep, "confirm": True, "basis": res1["basis"]})
    assert res2["ok"] is True and res2["removed"] == 1
    assert [r["name"] for r in ctrl.snapshot()["rows"]] == ["최신 계약"]


def test_pclm_snapshot_block_carries_default_db_doc_views_and_every_title(
    tmp_path, monkeypatch,
):
    """스냅샷이 기본 DB 자리·**고르게 할 뷰**·**뷰 전수 제목표**를 낸다.

    두 목록은 다른 일을 한다: ``views`` 는 새로 고를 수 있는 것(품목 제외 3건)이고,
    ``titles`` 는 이미 선 마운트를 제목으로 그리기 위한 전수 매핑(4건)이다. 후자를 같이
    좁히면 CLI 로 등록한 품목 마운트가 카드에서 내부 이름으로 새 나간다.
    """
    from hwpxfiller.domain.pclm_views import (
        PCLM_DOC_VIEWS,
        PCLM_VIEW_DESCS,
        PCLM_VIEW_TITLES,
        PCLM_VIEWS,
    )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    # 기본 자리 해석은 %APPDATA% 쪽지(config.json)도 본다 — 개발 기기의 실제 쪽지 격리.
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    ctrl, _reg, _ = _controller(tmp_path)
    block = ctrl.initial()["pclm"]
    assert block["default_db"] == str(
        tmp_path / "AppData" / "Local" / "Pclm" / "pclm.db"
    )
    assert [v["name"] for v in block["views"]] == list(PCLM_DOC_VIEWS)
    assert "v_품목_v1" not in [v["name"] for v in block["views"]]
    assert all(v["title"] == PCLM_VIEW_TITLES[v["name"]] for v in block["views"])
    assert all(v["desc"] == PCLM_VIEW_DESCS[v["name"]] for v in block["views"])
    # 종전 `label` 키는 폐기 — 표면이 「설명. 뜻」 한 줄을 다시 조립하지 않는다.
    assert all("label" not in v for v in block["views"])
    assert block["titles"] == {v: PCLM_VIEW_TITLES[v] for v in PCLM_VIEWS}
    assert set(block["titles"]) == set(PCLM_VIEWS)


def test_targeting_gate_rejects_a_broken_pclm_view_and_still_freezes_nara(tmp_path):
    """겨눔 관문의 백스톱 — 손편집·구판이 남긴 미지 뷰는 거절하고, 나라 동결은 그대로다.

    등록 게이트(링1)가 뷰를 확정해도 그 게이트를 지나지 않은 항목(직접 쓴
    ``.dataset.json``)이 있다. 뷰 이름은 SELECT 에 그대로 박히므로 다중 시트 게이트와
    같은 자리에서 한 번 더 잡는다.
    """
    from hwpxfiller.domain.pclm_views import PCLM_VIEWS
    from hwpxfiller.webapp.screens import NARA_FROZEN_TEXT, load_pool_item_checked

    reg = DatasetPoolRegistry(tmp_path / "datasets")
    good = reg.add(DatasetReference(
        name="정상", kind="pclm", opts={"db": "C:/d/pclm.db", "view": "v_통합_v1"}))
    broken = reg.add(DatasetReference(
        name="구판", kind="pclm", opts={"db": "C:/d/pclm.db", "view": "v_통합"}))
    missing = reg.add(DatasetReference(
        name="뷰 없음", kind="pclm", opts={"db": "C:/d/other.db"}))
    nara = reg.add(DatasetReference(
        name="나라", kind="nara", opts={"bgn_dt": "1", "end_dt": "2"}))

    assert load_pool_item_checked(reg, good).opts["view"] == "v_통합_v1"
    for key in (broken, missing):
        with pytest.raises(ValueError) as caught:
            load_pool_item_checked(reg, key)
        assert reg.load(key).name in str(caught.value)      # 항목 이름으로 재진술
        assert all(view in str(caught.value) for view in PCLM_VIEWS)
    with pytest.raises(ValueError, match="나라장터"):        # 동결 회귀 — 문구 불변
        load_pool_item_checked(reg, nara)
    assert NARA_FROZEN_TEXT.startswith("나라장터 소스는")


def test_pclm_db_is_reachable_from_the_locate_whitelist(tmp_path):
    """계약 목록 DB 도 사용자 소유 파일이라 열기·폴더보기가 열린다(끊김만 알리고 못 여는 일 금지)."""
    from hwpxfiller.external.job_store import JobRegistry
    from hwpxfiller.webapp.screens import collect_owned_paths, norm_path

    reg = DatasetPoolRegistry(tmp_path / "datasets")
    db = tmp_path / "pclm.db"
    reg.add(DatasetReference(name="계약", kind="pclm",
                             opts={"db": str(db), "view": "v_통합_v1"}))
    owned = collect_owned_paths(
        JobRegistry(tmp_path / "jobs"), reg, base_dir=tmp_path)
    assert owned == {norm_path(db, tmp_path)}


# ------------------------------- 「쓸 수 있는가」의 단일 판정 자리(U6-B #976)
def test_rows_carry_the_single_selection_verdict_and_its_reason(tmp_path):
    """행이 「이 데이터를 작업에 쓸 수 있나」와 그 사유를 진다 — 표면은 다시 판정하지 않는다.

    같은 스냅샷을 두 표면이 소비한다(「데이터 선택」 다이얼로그 · 편집기 고르기 우 열).
    종전에는 두 표면이 각자 문장을 지어 같은 상태가 두 어휘를 가졌다 — 그 재판정을 걷은
    자리가 이 두 필드다. **숨기지 않고 비활성 + 사유**라 목록에는 그대로 선다.
    """
    ctrl, reg, _ = _controller(tmp_path)
    live = tmp_path / "발주.xlsx"
    live.write_bytes(b"x")
    ctrl.dispatch("register_excel", {"name": "살아있음", "path": str(live), "sheet": "s"})
    ctrl.dispatch(
        "register_excel",
        {"name": "끊김", "path": str(tmp_path / "없음.xlsx"), "sheet": "s"},
    )
    rows = {r["name"]: r for r in ctrl.snapshot()["rows"]}
    assert rows["살아있음"]["selectable"] is True
    assert rows["살아있음"]["select_block_reason"] == ""
    assert rows["끊김"]["selectable"] is False
    assert "참조가 끊겼습니다" in rows["끊김"]["select_block_reason"]
    assert "다시 연결" in rows["끊김"]["select_block_reason"]   # 엑셀에는 그 동사가 있다

    # 보관은 숨기지 않고 활성화 동선을 지목한다(그 동사가 같은 행에 서 있다).
    ctrl.dispatch("archive", {"key": rows["살아있음"]["key"]})
    archived = {r["name"]: r for r in ctrl.snapshot()["rows"]}["살아있음"]
    assert archived["selectable"] is False
    assert "활성화" in archived["select_block_reason"]
    assert [a["key"] for a in archived["actions"]] == ["activate", "delete"]


def test_frozen_source_rows_are_refused_loudly_not_hidden(tmp_path):
    """나라장터 항목은 숨기지 않고 **시끄럽게 거절**한다(동결 규율 — CLAUDE.md 작업 규율)."""
    ctrl, reg, _ = _controller(tmp_path)
    reg.add(DatasetReference(name="나라 참조", kind="nara", opts={}))
    ctrl.dispatch("refresh", {})
    row = {r["name"]: r for r in ctrl.snapshot()["rows"]}["나라 참조"]
    assert row["selectable"] is False
    assert "작업 데이터로 연결할 수 없습니다" in row["select_block_reason"]


# ---------------------------- 고르기 우 열 공용 존(고르기 열 공용 계약 ①)
def test_column_zone_has_exactly_five_keys_and_rows_of_the_shared_shape(tmp_path):
    """우 열은 좌 열과 **같은 형**으로 선다 — 키 집합의 정본은 `webapp/pool_column.py`.

    옛 키(`rows`·`count`·`duplicates`…)는 웹이 이 존으로 옮겨 갈 때까지 그대로 산다.
    여기서 못박는 것은 새 존이 그 형을 정확히 지킨다는 것이다(몰래 얹은 키가 두 열이
    갈리는 첫 자리다).
    """
    from hwpxfiller.webapp.pool_column import POOL_ROW_KEYS

    ctrl, _, _ = _controller(tmp_path)
    live = tmp_path / "발주.xlsx"
    live.write_bytes(b"x")
    ctrl.dispatch("register_excel", {"name": "발주", "path": str(live), "sheet": "s",
                                     "note": "7월분"})
    column = ctrl.snapshot()["column"]
    assert tuple(column) == ("rows", "notices", "empty_hint", "count_label", "result")
    row = column["rows"][0]
    assert tuple(row) == POOL_ROW_KEYS
    assert row["icon"] == "excel" and row["path"] == str(live)
    assert row["sub"].startswith("파일: 발주.xlsx") and row["sub"].endswith("7월분")
    # 동사 전수는 링1 이 낸다 — 표면이 「다시 연결…」을 자기 판정으로 덧붙이지 않는다.
    assert [a["key"] for a in row["actions"]] == ["relink", "archive", "delete"]
    assert column["count_label"] == "1건" and column["empty_hint"] == ""


def test_column_rows_mirror_the_ring1_verdict_for_archived_and_missing(tmp_path):
    """`reason`·`selectable` 은 링1 판정 그대로다 — 링2 가 다시 짓지 않는다."""
    from hwpxfiller.application.dataset_pool import DatasetPoolRow

    ctrl, reg, _ = _controller(tmp_path)
    live = tmp_path / "발주.xlsx"
    live.write_bytes(b"x")
    ctrl.dispatch("register_excel", {"name": "살아있음", "path": str(live), "sheet": "s"})
    ctrl.dispatch(
        "register_excel", {"name": "끊김", "path": str(tmp_path / "없음.xlsx"), "sheet": "s"}
    )
    ctrl.dispatch("archive", {
        "key": next(r["key"] for r in ctrl.snapshot()["rows"] if r["name"] == "살아있음"),
    })

    for row in ctrl.snapshot()["column"]["rows"]:
        ring1 = next(r for r in ctrl.vm.rows() if r.key == row["key"])
        assert row["reason"] == ring1.select_block_reason()
        assert row["selectable"] is (not ring1.select_block_reason())
    by_name = {r["name"]: r for r in ctrl.snapshot()["column"]["rows"]}
    assert "보관한 항목입니다" in by_name["살아있음"]["reason"]
    assert "참조가 끊겼습니다" in by_name["끊김"]["reason"]
    assert isinstance(DatasetPoolRow.missing, property)   # 판정 재료도 링1 행이 든다


def test_column_notice_restates_a_corrupted_entry_as_danger(tmp_path):
    """손상 격리는 존 통지로 선다 — 종전 웹 리터럴(`pool_list.ts`)이 여기로 왔다."""
    ctrl, reg, _ = _controller(tmp_path)
    reg.add(DatasetReference(name="살아있음", kind="excel", opts={"path": "C:/a.xlsx"}))
    (reg.directory / ("깨진" + reg.SUFFIX)).write_text("{ not json", encoding="utf-8")
    ctrl.dispatch("refresh", {})
    notices = ctrl.snapshot()["column"]["notices"]
    corrupt = ctrl.snapshot()["corrupted"][0]
    assert notices == [{
        "level": "danger",
        "text": f"⚠ 손상된 등록 데이터: {corrupt['file']} — {corrupt['error']}",
        "actions": [],
    }]


def test_column_notice_offers_one_keep_verb_per_duplicate_entry(tmp_path):
    """중복 통지는 처분을 **같은 자리**에 세운다 — 「골라 정리하세요」의 고를 자리."""
    ctrl, reg, _ = _controller(tmp_path)
    _legacy_write(reg, "7월 공고", "C:/d/same.xlsx")
    _legacy_write(reg, "공고 최신", "C:/d/same.xlsx")
    ctrl.dispatch("refresh", {})
    notice = ctrl.snapshot()["column"]["notices"][0]
    assert notice["level"] == "warn"
    assert "등록이 2건입니다" in notice["text"] and "same.xlsx" in notice["text"]
    assert {a["label"] for a in notice["actions"]} == {"'7월 공고' 남기기", "'공고 최신' 남기기"}
    assert {a["key"] for a in notice["actions"]} == {"resolve_duplicate"}
    keys = {r["key"] for r in ctrl.snapshot()["column"]["rows"]}
    # payload 키는 `pool/resolve_duplicate` 스키마 그대로이고 값은 슬롯 키다.
    assert {a["payload"]["keep"] for a in notice["actions"]} == keys


def test_column_empty_hint_speaks_only_while_the_pool_is_empty(tmp_path):
    ctrl, _, _ = _controller(tmp_path)
    assert ctrl.snapshot()["column"]["empty_hint"] == "고정한 데이터가 없습니다."
    ctrl.dispatch("register_excel", {"name": "A", "path": "C:/a.xlsx", "sheet": "s"})
    assert ctrl.snapshot()["column"]["empty_hint"] == ""


def test_column_row_of_a_kind_without_its_own_icon_stands_as_other(tmp_path):
    """자기 표지가 없는 종류(조립)는 숨기지도, 다른 표지로 접지도 않는다 — `other` 로 선다."""
    ctrl, reg, _ = _controller(tmp_path)
    reg.add(DatasetReference(name="조립", kind="pipeline", opts={"sources": [], "steps": []}))
    ctrl.dispatch("refresh", {})
    row = ctrl.snapshot()["column"]["rows"][0]
    assert row["icon"] == "other"
    assert "작업 데이터로 연결할 수 없습니다" in row["reason"]
