"""데이터셋 풀 워크숍 ViewModel(J1) 헤드리스 테스트 — Qt 무접촉.

등록(참조만)·상태 전이·행 성형·KPI(home_state)를 못박는다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.core.dataset_pool import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_RETIRED,
    DatasetPoolRegistry,
)
from hwpxfiller.gui.dataset_pool_state import (
    DatasetPoolViewModel,
    available_actions,
    reference_summary,
)


def _vm(tmp_path):
    return DatasetPoolViewModel(DatasetPoolRegistry(tmp_path))


def test_register_excel_stores_path_reference(tmp_path):
    vm = _vm(tmp_path)
    assert vm.is_empty()
    vm.register_excel("6월 데이터", "/data/june.xlsx", sheet="Sheet1")
    rows = vm.rows()
    assert len(rows) == 1
    r = rows[0]
    assert r.kind == "excel" and r.status == STATUS_ACTIVE
    assert "june.xlsx" in r.reference and "Sheet1" in r.reference
    assert vm.count_label() == "1건"


def test_register_nara_stores_query_only_no_key(tmp_path):
    vm = _vm(tmp_path)
    item = vm.register_nara("공고쿼리", "202606010000", "202606302359", num_rows=100)
    assert "service_key" not in item.opts
    saved = DatasetPoolRegistry(tmp_path).path_for("공고쿼리").read_text(encoding="utf-8")
    assert "ServiceKey" not in saved and "service_key" not in saved
    assert "기간" in vm.rows()[0].reference


def test_register_rejects_empty_name(tmp_path):
    vm = _vm(tmp_path)
    with pytest.raises(ValueError):
        vm.register_excel("  ", "/x.xlsx")
    with pytest.raises(ValueError):
        vm.register_nara("이름있음", "", "202606302359")


def test_status_transitions_via_dispatch(tmp_path):
    vm = _vm(tmp_path)
    vm.register_excel("D", "/d.xlsx")
    vm.dispatch("archive", "D")
    assert vm.rows()[0].status == STATUS_ARCHIVED
    vm.dispatch("retire", "D")
    assert vm.rows()[0].status == STATUS_RETIRED
    vm.dispatch("activate", "D")
    assert vm.rows()[0].status == STATUS_ACTIVE
    vm.dispatch("delete", "D")
    assert vm.is_empty()


def test_available_actions_per_status():
    assert [a.key for a in available_actions(STATUS_ACTIVE)] == ["archive", "retire", "delete"]
    assert [a.key for a in available_actions(STATUS_ARCHIVED)] == ["activate", "retire", "delete"]
    assert [a.key for a in available_actions(STATUS_RETIRED)] == ["activate", "delete"]


def test_reference_summary_unknown_kind():
    from hwpxfiller.core.dataset_pool import DatasetPoolItem

    it = DatasetPoolItem(name="x", kind="excel", opts={})
    assert "경로 없음" in reference_summary(it)


# ------------------------------------------------------------ home KPI (헤드리스)
def test_home_kpi_counts_active_pool_items(tmp_path):
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.home_state import HomeViewModel

    pool = DatasetPoolRegistry(tmp_path / "datasets")
    pvm = DatasetPoolViewModel(pool)
    pvm.register_excel("A", "/a.xlsx")
    pvm.register_excel("B", "/b.xlsx")
    pvm.dispatch("retire", "B")  # 은퇴는 활성 카운트에서 제외

    home = HomeViewModel(JobRegistry(tmp_path / "jobs"), pool_registry=pool)
    assert home.kpi().pool_count == 1  # A 만 활성


def test_home_kpi_pool_count_zero_without_registry(tmp_path):
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.home_state import HomeViewModel

    home = HomeViewModel(JobRegistry(tmp_path))
    assert home.kpi().pool_count == 0
