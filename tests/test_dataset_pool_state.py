"""데이터셋 풀 워크숍 ViewModel(J1) 헤드리스 테스트 — Qt 무접촉.

등록(참조만)·상태 전이·행 성형·KPI(home_state)를 못박는다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.core.dataset_pool import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
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


def test_register_excel_embeds_sheet_and_restore_targets_it(tmp_path):
    """T2 — 확정 시트가 풀 항목 opts 에 임베딩되고, 복원이 그 시트 레코드를 준다."""
    from pathlib import Path

    from hwpxfiller.data.factory import source_from_pool_item

    fixture = Path(__file__).parent / "fixtures" / "multi_sheet.xlsx"
    vm = _vm(tmp_path)
    item = vm.register_excel("다중시트", str(fixture), sheet="낙찰현황")
    assert item.opts["sheet"] == "낙찰현황"
    # 복원 경로(source_from_pool_item)는 무수정 통과 — opts 그대로 관통해
    # 지정 시트 레코드가 온다(실행 시점 재읽기=싱크).
    src = source_from_pool_item(item)
    assert src.records()[0]["업체명"] == "가나상사"
    assert len(src.records()) == 3


def test_register_nara_stores_query_only_no_key(tmp_path):
    vm = _vm(tmp_path)
    item = vm.register_nara("공고쿼리", "202606010000", "202606302359", num_rows=100)
    assert "service_key" not in item.opts
    reg = DatasetPoolRegistry(tmp_path)
    key = vm.rows()[0].key
    saved = reg.slot_path(key).read_text(encoding="utf-8")
    assert "ServiceKey" not in saved and "service_key" not in saved
    assert "기간" in vm.rows()[0].reference


def test_register_rejects_empty_name(tmp_path):
    vm = _vm(tmp_path)
    with pytest.raises(ValueError):
        vm.register_excel("  ", "/x.xlsx")
    with pytest.raises(ValueError):
        vm.register_nara("이름있음", "", "202606302359")


def test_register_nara_validates_range(tmp_path):
    """RC-13: 등록 경로도 기간 검증 — 취득 게이트 우회로 미검증 기간이 조용히 저장되면
    실행 시점마다 실패하는 죽은 참조가 된다(등록 시점에 시끄럽게 거절)."""
    vm = _vm(tmp_path)
    with pytest.raises(ValueError, match="1개월"):
        vm.register_nara("긴기간", "202601010000", "202607010000")
    with pytest.raises(ValueError):
        vm.register_nara("형식오류", "2026-06-01 00", "202606302359")
    assert vm.is_empty()  # 거절된 등록은 흔적 없음


def test_status_transitions(tmp_path):
    """VM 전이 메서드(웹 컨트롤러가 _do_* 에서 직접 호출) — 활성↔보관, 삭제. 겨눔=슬롯 키."""
    vm = _vm(tmp_path)
    vm.register_excel("D", "/d.xlsx")
    key = vm.rows()[0].key
    vm.archive(key)
    assert vm.rows()[0].status == STATUS_ARCHIVED
    vm.activate(key)
    assert vm.rows()[0].status == STATUS_ACTIVE
    vm.delete(key)
    assert vm.is_empty()


def test_unknown_status_transition_fails_loudly(tmp_path):
    vm = _vm(tmp_path)
    vm.register_excel("D", "/d.xlsx")
    key = vm.rows()[0].key
    with pytest.raises(ValueError, match="지원하지 않는 데이터셋 전이"):
        vm._transition(key, "typo")


def test_stale_reference_update_does_not_resurrect_deleted_item(tmp_path):
    """확인 전에 읽은 항목이 삭제되면 갱신은 loud 실패하고 신규 항목으로 부활하지 않는다."""
    directory = tmp_path / "datasets"
    reg = DatasetPoolRegistry(directory)
    vm = DatasetPoolViewModel(reg)
    vm.register_excel("D", "/old.xlsx")
    key = vm.rows()[0].key
    DatasetPoolRegistry(directory).delete(key)

    with pytest.raises(FileNotFoundError):
        vm.update_excel_reference(key, "/new.xlsx")
    assert not reg.exists(key)


def test_find_same_data_and_relabel(tmp_path):
    """같은 데이터(경로+시트) 재고정 = 새 항목이 아니라 기존 슬롯의 라벨·메모 갱신(§5.3 C)."""
    vm = _vm(tmp_path)
    vm.register_excel("7월", "/a.xlsx", note="첫 등록")
    found = vm.find_same_data("/a.xlsx")
    assert found is not None
    key, existing = found
    assert existing.name == "7월"
    updated = vm.relabel(key, "7월 최신")
    assert updated.name == "7월 최신"
    assert updated.note == "첫 등록"       # 빈 메모 입력 = 진술 없음(보존)
    assert len(vm.rows()) == 1             # 여전히 1건 — 정체성이 같다
    # 다른 시트는 다른 데이터 — 판정에 시트가 든다(#33).
    assert vm.find_same_data("/a.xlsx", "물품") is None


def test_update_excel_reference_keeps_slot_but_rejects_identity_theft(tmp_path):
    """다시 연결 = 같은 슬롯의 참조 교체(수명 보존). 남의 정체성으로는 못 갈아탄다."""
    vm = _vm(tmp_path)
    vm.register_excel("A", "/a.xlsx")
    vm.register_excel("B", "/b.xlsx")
    rows = {r.name: r for r in vm.rows()}
    vm.archive(rows["A"].key)  # 보관 상태가 재연결에도 보존되는지 함께 본다
    updated = vm.update_excel_reference(rows["A"].key, "/a2.xlsx")
    assert updated.opts["path"] == "/a2.xlsx"
    assert updated.status == STATUS_ARCHIVED  # 수명 보존 — 조용한 재활성화 금지
    with pytest.raises(ValueError, match="이미"):
        vm.update_excel_reference(rows["B"].key, "/a2.xlsx")  # A 슬롯의 정체성과 충돌


def test_concurrent_relink_to_same_identity_loses_loudly(tmp_path, monkeypatch):
    """서로 다른 슬롯 둘을 같은 경로+시트로 동시 재연결하면 하나만 이기고 하나는 loud 거절.

    코덱스 1R P2 — 정체성 검사가 잠금 밖이면 둘 다 선검사를 통과하고 mutate 만 직렬화돼
    같은 정체성의 슬롯 2개가 남는다(레지스트리 불변식 붕괴). 검사·변이가 공유 쓰기 잠금
    한 경계 안이어야 한다: A 가 잠금 안(원자 쓰기 중)에 있는 동안 B 는 검사에 못 들어가고,
    A 커밋 뒤 B 의 잠금 안 재검사가 충돌을 잡는다.
    """
    import threading

    from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry

    directory = tmp_path / "datasets"
    vm_a = DatasetPoolViewModel(DatasetPoolRegistry(directory))
    vm_b = DatasetPoolViewModel(DatasetPoolRegistry(directory))
    vm_a.register_excel("A", "/a.xlsx")
    vm_a.register_excel("B", "/b.xlsx")
    rows = {r.name: r for r in vm_a.rows()}

    entered = threading.Event()
    release = threading.Event()
    real_save = DatasetPoolItem.save

    def slow_save(item, path):
        entered.set()
        assert release.wait(2)
        return real_save(item, path)

    monkeypatch.setattr(DatasetPoolItem, "save", slow_save)
    errors: "list[Exception]" = []

    def relink(vm, key):
        try:
            vm.update_excel_reference(key, "/target.xlsx")
        except ValueError as exc:
            errors.append(exc)

    first = threading.Thread(target=relink, args=(vm_a, rows["A"].key))
    first.start()
    assert entered.wait(2)                       # A: 검사 통과, 잠금 안에서 쓰기 중
    second = threading.Thread(target=relink, args=(vm_b, rows["B"].key))
    second.start()
    second.join(0.05)
    assert second.is_alive()                     # B: 검사가 잠금 안이라 진입 자체가 대기
    release.set()
    first.join(2)
    second.join(2)
    assert not first.is_alive() and not second.is_alive()

    assert len(errors) == 1 and "이미" in str(errors[0])   # 한쪽만 loud 패배
    reg = DatasetPoolRegistry(directory)
    winners = [
        (key, it) for key, it in reg.list_entries()
        if it.opts.get("path") == "/target.xlsx"
    ]
    assert [k for k, _ in winners] == [rows["A"].key]       # 같은 정체성 슬롯은 1개뿐
    assert reg.duplicate_identity_groups(corrupted=[]) == []  # 불변식 유지


def test_duplicates_surface_from_legacy_files(tmp_path):
    """구판(이름=키)이 남긴 같은 경로 2건이 VM duplicates 로 표면화된다(§5.3 병합 loud)."""
    import json as _json

    from hwpxfiller.core.dataset_pool import DatasetPoolItem

    tmp_path.mkdir(parents=True, exist_ok=True)
    for name in ("7월 공고", "공고 최신"):
        item = DatasetPoolItem(name=name, kind="excel", opts={"path": "/same.xlsx"})
        (tmp_path / f"{name}.dataset.json").write_text(
            _json.dumps(item.to_dict(), ensure_ascii=False), encoding="utf-8"
        )
    vm = _vm(tmp_path)
    groups = vm.duplicates()
    assert len(groups) == 1
    assert {r.name for r in groups[0]} == {"7월 공고", "공고 최신"}
    assert len(vm.rows()) == 2  # 병합 전에도 목록에는 둘 다 산다(숨김 금지)


def test_available_actions_per_status():
    assert [a.key for a in available_actions(STATUS_ACTIVE)] == ["archive", "delete"]
    assert [a.key for a in available_actions(STATUS_ARCHIVED)] == ["activate", "delete"]


def test_reference_summary_unknown_kind():
    from hwpxfiller.core.dataset_pool import DatasetPoolItem

    it = DatasetPoolItem(name="x", kind="excel", opts={})
    assert "경로 없음" in reference_summary(it)


def test_pipeline_row_renders_kind_label_and_summary(tmp_path):
    """파이프라인 풀 항목(KB)이 풀 목록에서 종류 라벨·조립 요약으로 성형된다."""
    from hwpxfiller.core.dataset_pool import DatasetPoolItem

    it = DatasetPoolItem(
        name="6월 조립", kind="pipeline",
        opts={
            "sources": [{"kind": "excel", "opts": {"path": "/a.csv"}},
                        {"kind": "excel", "opts": {"path": "/b.csv"}}],
            "steps": [{"op": "merge", "source": 1, "on": "id", "how": "inner"}],
        },
    )
    reg = DatasetPoolRegistry(tmp_path)
    reg.add(it)
    vm = DatasetPoolViewModel(reg)
    r = vm.rows()[0]
    assert r.kind_label == "파이프라인"
    assert "소스 2개" in r.reference and "merge" in r.reference


# ------------------------------------------------------------ home KPI (헤드리스)
def test_home_kpi_counts_active_pool_items(tmp_path):
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.home_state import HomeViewModel

    pool = DatasetPoolRegistry(tmp_path / "datasets")
    pvm = DatasetPoolViewModel(pool)
    pvm.register_excel("A", "/a.xlsx")
    pvm.register_excel("B", "/b.xlsx")
    key_b = next(r.key for r in pvm.rows() if r.name == "B")
    pvm.archive(key_b)  # 보관은 활성 카운트에서 제외

    home = HomeViewModel(JobRegistry(tmp_path / "jobs"), pool_registry=pool)
    assert home.kpi().pool_count == 1  # A 만 활성


def test_home_kpi_pool_count_zero_without_registry(tmp_path):
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.home_state import HomeViewModel

    home = HomeViewModel(JobRegistry(tmp_path))
    assert home.kpi().pool_count == 0
