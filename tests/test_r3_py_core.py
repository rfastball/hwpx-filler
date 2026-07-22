"""코드리뷰 3차(py-core) 회귀 — K3 격리 루프 단일화·C5 손상 조용한 증발 봉합·
K2 동명/충돌 분류 공유·K5 멀티시트 게이트 통일.

- K3: :func:`~hwpxfiller.core.job.load_isolated` — 세 레지스트리에 복붙돼 있던
  손상 격리 try/except 루프의 단일 출처. 수집 리스트를 넘기면 격리+수집,
  안 넘기면(None) 그대로 raise.
- C5: :meth:`~hwpxfiller.core.dataset_pool.DatasetPoolRegistry.list_items` 가
  ``corrupted`` 미전달 호출자에게 손상 항목을 무표시 드롭하던 정합 결함 —
  미전달=raise 로 되돌리고, 각 표면(피커·홈 KPI)은 명시 수집 후 병기 표면화.
- K2: :func:`~hwpxfiller.core.job.classify_existing` — exists→load→손상?→이름
  불일치?→동명 분류 사다리의 단일 출처(이 라운드는 pool 등록 사이트만 이관).
- K5: :func:`~hwpxfiller.data.excel.ambiguous_sheet_error` — #33 멀티시트 거절
  정책(모호 거부·읽기실패 통과·복수 시 거부)+문구의 단일 출처(등록·겨눔 공유).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.dataset_pool import (
    STATUS_ACTIVE,
    DatasetPoolItem,
    DatasetPoolRegistry,
)
from hwpxfiller.core.job import JobRegistry, classify_existing, load_isolated
from hwpxfiller.data.excel import ambiguous_sheet_error
from hwpxfiller.gui.home_state import HomeViewModel
from hwpxfiller.gui.pipeline_builder_state import PipelineBuilderViewModel
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.screen_pool import PoolController
from hwpxfiller.webapp.screens import load_pool_item_checked, pool_sources_payload

MULTI_SHEET = Path(__file__).resolve().parent / "fixtures" / "multi_sheet.xlsx"

_push_noop = lambda screen, snap: None  # noqa: E731 — 푸시 sink 수집 불필요


# ------------------------------------------------------------------ 헬퍼
def _pool_with_corruption(tmp_path) -> DatasetPoolRegistry:
    """활성 1건 + 손상 파일 1개가 든 풀 레지스트리."""
    reg = DatasetPoolRegistry(tmp_path / "datasets")
    reg.save(DatasetPoolItem(name="살아있음", kind="excel", opts={"path": "C:/a.xlsx"}))
    (reg.directory / ("깨진" + reg.SUFFIX)).write_text("{ not json", encoding="utf-8")
    return reg


# ================================================================== K3
def test_load_isolated_collects_per_file_failures():
    """수집 리스트를 넘기면 실패 파일만 (경로, 오류) 로 격리되고 정상 항목은 산다."""
    def loader(p):
        if "bad" in str(p):
            raise ValueError("깨짐")
        return f"ok:{p}"

    corrupted: "list[tuple]" = []
    items = load_isolated(["a", "bad1", "b", "bad2"], loader, corrupted)
    assert items == ["ok:a", "ok:b"]
    assert [(p, e) for p, e in corrupted] == [("bad1", "깨짐"), ("bad2", "깨짐")]


def test_load_isolated_without_sink_raises():
    """수집처(None) 없이 격리하면 손상이 무표시 증발한다 — 그대로 raise 가 계약(C5)."""
    def loader(p):
        raise ValueError("깨짐")

    with pytest.raises(ValueError, match="깨짐"):
        load_isolated(["x"], loader, None)


# ================================================================== C5
def test_list_items_without_corrupted_raises_on_corruption(tmp_path):
    """corrupted 미전달 = 옛 불변식(읽기 실패 시 raise) 복원 — 조용한 드롭 삭제."""
    reg = _pool_with_corruption(tmp_path)
    with pytest.raises(ValueError):  # json.JSONDecodeError ⊂ ValueError
        reg.list_items()
    # 명시 수집이면 격리 + 정상 항목 생존(기존 RC-05 경로 불변).
    corrupted: "list[tuple]" = []
    items = reg.list_items(corrupted=corrupted)
    assert [it.name for it in items] == ["살아있음"]
    assert len(corrupted) == 1 and corrupted[0][0].name.endswith(reg.SUFFIX)


def test_pool_sources_payload_surfaces_corruption_note(tmp_path):
    """피커 페이로드 — 손상은 목록에서 빠지되 '손상 N건' 노트로 병기된다(무표시 증발 금지)."""
    reg = _pool_with_corruption(tmp_path)
    payload = pool_sources_payload(reg)
    assert [i["name"] for i in payload["items"]] == ["살아있음"]
    assert payload["corrupted_note"] == "손상 1건(데이터 관리에서 확인)"
    # 손상이 없으면 노트는 빈 문자열(거짓 경보 없음).
    clean = DatasetPoolRegistry(tmp_path / "clean")
    clean.save(DatasetPoolItem(name="정상", kind="excel", opts={"path": "C:/b.xlsx"}))
    assert pool_sources_payload(clean)["corrupted_note"] == ""


def test_job_pool_sources_action_carries_corruption_note(tmp_path):
    """작업 화면 pool_sources 액션도 노트를 나른다 — 화면 하나의 손상이 다른 화면을
    전멸시키지 않되(items 생존), 어디서도 조용히 사라지지 않는다(corrupted_note)."""
    reg = _pool_with_corruption(tmp_path)
    ctrl = JobController(JobRegistry(tmp_path / "jobs"), _push_noop, pool_registry=reg)
    res = ctrl.dispatch("pool_sources", {})
    assert [i["name"] for i in res["items"]] == ["살아있음"]
    assert "손상 1건" in res["corrupted_note"]


def test_home_kpi_counts_pool_corruption(tmp_path):
    """홈 KPI — 손상 파일이 0 으로 위장 강등되지 않고 pool_corrupted 로 세어진다."""
    reg = _pool_with_corruption(tmp_path)
    home = HomeViewModel(JobRegistry(tmp_path / "jobs"), pool_registry=reg)
    kpi = home.kpi()
    assert kpi.pool_count == 1          # 활성 항목은 계속 세어진다
    assert kpi.pool_corrupted == 1      # 손상은 감춰지지 않고 병기된다


def test_pipeline_pool_name_lists_follow_c5_contract(tmp_path):
    """pipeline 후보 목록 — 미전달=raise, 명시 수집=격리(list_items 계약 통과)."""
    reg = _pool_with_corruption(tmp_path)
    builder = PipelineBuilderViewModel(reg)
    with pytest.raises(ValueError):  # json.JSONDecodeError ⊂ ValueError
        builder.available_source_names()
    corrupted2: "list[tuple]" = []
    assert builder.available_source_names(corrupted=corrupted2) == ["살아있음"]
    assert len(corrupted2) == 1


# ================================================================== K2
def test_classify_existing_four_kinds(tmp_path):
    """absent/same/collision/corrupt — 동명 확인 승격·충돌 차단 게이트의 공용 분류."""
    reg = DatasetPoolRegistry(tmp_path / "datasets")
    assert classify_existing(reg, "없음") == ("absent", None)

    reg.save(DatasetPoolItem(name="동명", kind="excel", opts={"path": "C:/a.xlsx"}))
    kind, item = classify_existing(reg, "동명")
    assert kind == "same" and item.name == "동명"

    reg.save(DatasetPoolItem(name="a/b", kind="excel", opts={"path": "C:/a.xlsx"}))
    kind, item = classify_existing(reg, "a_b")  # 다른 이름·같은 slug 파일
    assert kind == "collision" and item.name == "a/b"

    (reg.path_for("깨진자리")).write_text("{ not json", encoding="utf-8")
    assert classify_existing(reg, "깨진자리") == ("corrupt", None)


def test_pool_register_gate_uses_shared_classification(tmp_path):
    """pool 수동 등록 — 동명=확인 승격, 충돌=이름 안내(loud), 손상=조용히 덮지 않음."""
    reg = DatasetPoolRegistry(tmp_path / "datasets")
    ctrl = PoolController(reg, _push_noop)

    # 동명: 1차=기존 참조 재진술 확인, confirm 재호출=참조 교체.
    ctrl.dispatch("register_excel", {"name": "6월", "path": "C:/old.csv"})
    res = ctrl.dispatch("register_excel", {"name": "6월", "path": "C:/new.csv"})
    assert res.get("needs_confirm") is True and "6월" in res["confirm_text"]
    res2 = ctrl.dispatch(
        "register_excel", {"name": "6월", "path": "C:/new.csv", "confirm": True})
    assert res2["ok"] is True and reg.load("6월").opts["path"] == "C:/new.csv"

    # 충돌(다른 이름·같은 slug): 덮어쓰기 경로 없이 loud 거절(가드 문구 재진술).
    ctrl.dispatch("register_excel", {"name": "a/b", "path": "C:/a.csv"})
    res3 = ctrl.dispatch("register_excel", {"name": "a_b", "path": "C:/b.csv"})
    assert res3["ok"] is False and "같은 파일" in res3["error"]
    assert reg.load("a/b").opts["path"] == "C:/a.csv"  # 기존 참조 무손상

    # 손상 자리: 소유 불명 — 조용히 덮지 않고 loud 거절.
    (reg.path_for("깨진자리")).write_text("{ not json", encoding="utf-8")
    res4 = ctrl.dispatch("register_excel", {"name": "깨진자리", "path": "C:/c.csv"})
    assert res4["ok"] is False and "손상" in res4["error"]


# ================================================================== K5
def test_ambiguous_sheet_error_policy_single_source(tmp_path):
    """모호=거절 문구(시트 병기)·CSV/단일=None·읽기 실패=None(후속 관문이 재방어)."""
    msg = ambiguous_sheet_error(MULTI_SHEET)
    assert msg and "공고목록" in msg and "낙찰현황" in msg and "시트" in msg
    # 컨텍스트 프리픽스 병기.
    assert ambiguous_sheet_error(MULTI_SHEET, prefix="X — ").startswith("X — ")

    csv = tmp_path / "단일.csv"
    csv.write_text("이름\n가\n", encoding="utf-8")
    assert ambiguous_sheet_error(csv) is None
    assert ambiguous_sheet_error(tmp_path / "없는파일.xlsx") is None  # 읽기 실패 통과


def test_multisheet_gate_sites_share_wording(tmp_path):
    """등록(pool)과 겨눔(load_pool_item_checked) 두 사이트가 같은 단일 출처 문구를 낸다
    — 문구 표류(락스텝 편집 누락) 재발 방지의 계약."""
    shared = ambiguous_sheet_error(MULTI_SHEET)

    # 등록 사이트: 시트 미지정 다중시트 등록 거부 문구 == 단일 출처 문구.
    reg = DatasetPoolRegistry(tmp_path / "datasets")
    ctrl = PoolController(reg, _push_noop)
    res = ctrl.dispatch("register_excel", {"name": "모호", "path": str(MULTI_SHEET)})
    assert res["ok"] is False and res["error"] == shared
    assert not reg.exists("모호")

    # 겨눔 사이트: 프리픽스(항목 이름 컨텍스트)만 다르고 몸통은 동일.
    reg.save(DatasetPoolItem(name="모호참조", kind="excel", opts={"path": str(MULTI_SHEET)}))
    with pytest.raises(ValueError) as exc:
        load_pool_item_checked(reg, "모호참조")
    assert str(exc.value) == ambiguous_sheet_error(
        str(MULTI_SHEET),
        prefix="등록 데이터 '모호참조' 에 시트가 지정되지 않았습니다. ",
    )
    assert str(exc.value).endswith(shared)  # 몸통 공유(표류 봉인)
