"""Application 데이터셋 풀 계약(:mod:`hwpxfiller.application.dataset_pool`)의 owner.

새 파일 사유: P2-22 #570 이 세운 **새 durable product boundary**(semantic
``DatasetPoolPort`` + 확정 결속 use case)의 owner 다(write-lean 예외 조항 —
``tests/test_application_jobs.py`` 동형). 실제 JSON 어댑터
(:class:`~hwpxfiller.external.dataset_store.DatasetPoolRegistry`)와 파일·잠금 없는
in-memory 구현이 **같은 Application 계약**을 만족함을 한 파라미터 축으로 증명한다 —
포트 표면에 물리(lock·``Path`` out-param·콜백)가 새면 in-memory 구현이 성립하지 않아
여기가 가장 먼저 부러진다.

concrete 의미(원자 쓰기·공유 잠금 직렬화·legacy slug 슬롯·손상 격리)는 기존 owner
(``tests/test_dataset_pool.py``·``tests/test_webapp_pool.py``)가 계속 진다 — 이 파일은
값 단언을 되풀이하지 않고 **경계의 성립**만 잰다.
"""

from __future__ import annotations

import json

import pytest

from hwpxfiller.application.dataset_pool import (
    CorruptDatasetEntry,
    DatasetPoolViewModel,
    StaleConfirmError,
    bound_state,
    confirm_basis,
)
from hwpxfiller.domain.dataset_reference import (
    DatasetReference,
    excel_identity,
    reference_identity,
)
from hwpxfiller.external.dataset_store import DatasetPoolRegistry


class InMemoryDatasetPool:
    """:class:`~hwpxfiller.application.dataset_pool.DatasetPoolPort` 의 dict 구현.

    파일도 잠금도 없다. 의미는 concrete(:class:`DatasetPoolRegistry`)의 문서를 미러하되
    검증하려는 것은 「포트가 semantic 하다」는 사실이지 물리 세부가 아니다.
    """

    def __init__(self) -> None:
        self.slots: "dict[str, DatasetReference]" = {}
        self.corrupt: "list[CorruptDatasetEntry]" = []
        self._seq = 0

    # ------------------------------------------------------------ 내부(영속 격리)
    def _copy(self, ref: DatasetReference) -> DatasetReference:
        return DatasetReference.from_dict(ref.to_dict())

    def _update(self, key, change) -> DatasetReference:
        item = self.load(key)  # 부재는 FileNotFoundError 로 loud
        change(item)
        self.slots[key] = item
        return self._copy(item)

    def _check(self, expected, states) -> None:
        if expected != confirm_basis(states):
            raise StaleConfirmError("확인 근거가 지금 상태와 다릅니다.")

    # ------------------------------------------------------------ port 구현
    def load(self, key):
        if key not in self.slots:
            raise FileNotFoundError(key)
        return self._copy(self.slots[key])

    def list_references(self, status=None):
        entries = sorted(
            ((k, self._copy(it)) for k, it in self.slots.items()),
            key=lambda e: (e[1].name, e[0]),
        )
        if status is not None:
            entries = [e for e in entries if e[1].status == status]
        return entries, list(self.corrupt)

    def find_identity(self, path, sheet=""):
        ident = excel_identity(path, sheet)
        for k, it in self.list_references()[0]:
            if reference_identity(it) == ident:
                return (k, it)
        return None

    def add(self, item):
        ident = reference_identity(item)
        if ident is not None and self.find_identity(
            item.opts["path"], item.opts.get("sheet") or ""
        ):
            raise ValueError("같은 데이터(경로·시트)가 이미 고정돼 있습니다.")
        self._seq += 1
        key = f"mem{self._seq:04d}"
        self.slots[key] = self._copy(item)
        return key

    def delete(self, key):
        self.slots.pop(key, None)

    def archive(self, key):
        return self._update(key, lambda it: it.archive())

    def activate(self, key):
        return self._update(key, lambda it: it.activate())

    def relabel(self, key, name, *, note=""):
        def _c(it):
            it.name = name
            if note:
                it.note = note

        return self._update(key, _c)

    def relink_excel(self, key, path, *, sheet=None, note="", name=""):
        taken = self.find_identity(path, sheet or "")
        if taken is not None and taken[0] != key:
            raise ValueError(f"그 파일·시트는 이미 '{taken[1].name}' 으로 고정돼 있습니다.")
        opts: "dict[str, object]" = {"path": path}
        if sheet:
            opts["sheet"] = sheet

        def _c(it):
            it.kind = "excel"
            it.opts = opts
            if note:
                it.note = note
            if name:
                it.name = name

        return self._update(key, _c)

    def relabel_confirmed(self, path, sheet, name, *, note="", expected_basis):
        same = self.find_identity(path, sheet or "")
        if same is None:
            raise FileNotFoundError(name)
        key, existing = same
        self._check(expected_basis, [bound_state(key, existing)])
        return key, self.relabel(key, name, note=note)

    def relink_confirmed(
        self, key, path, *, sheet=None, note="", name="", expected_basis
    ):
        current = self.load(key)
        self._check(expected_basis, [bound_state(key, current)])
        return self.relink_excel(key, path, sheet=sheet, note=note, name=name)

    def delete_confirmed(self, key, *, expected_basis):
        item = self.load(key)
        self._check(expected_basis, [bound_state(key, item)])
        self.delete(key)
        return item

    def resolve_duplicates(self, keep, *, expected_basis):
        entries = self.list_references()[0]
        ident = {k: reference_identity(it) for k, it in entries}
        target = ident.get(keep)
        group = [
            (k, it) for k, it in entries if target is not None and ident[k] == target
        ]
        if target is None or len(group) < 2:
            raise FileNotFoundError("병합할 중복 등록이 더는 없습니다.")
        self._check(expected_basis, [bound_state(k, it) for k, it in group])
        kept = dict(group)[keep]
        removed = 0
        for k, _it in group:
            if k != keep:
                self.delete(k)
                removed += 1
        return kept.name, removed


@pytest.fixture(params=["json", "memory"])
def registry(request, tmp_path):
    """같은 계약을 두 구현으로 — JSON 어댑터 vs in-memory(#570 완료 조건)."""
    if request.param == "json":
        return DatasetPoolRegistry(tmp_path / "pool")
    return InMemoryDatasetPool()


def _seed_slot(registry, name: str, path: str) -> str:
    """중복 정체성도 심을 수 있는 저장층 직접 시드(구판 잔재 시뮬레이션) — 키를 돌려준다."""
    ref = DatasetReference(name=name, kind="excel", opts={"path": path})
    if isinstance(registry, DatasetPoolRegistry):
        registry.directory.mkdir(parents=True, exist_ok=True)
        (registry.directory / f"{name}{registry.SUFFIX}").write_text(
            json.dumps(ref.to_dict(), ensure_ascii=False), encoding="utf-8"
        )
        return name  # legacy slug 파일 = stem 이 그대로 슬롯 키
    registry.slots[name] = ref
    return name


def test_lifecycle_and_identity_reject_hold_for_both_ports(registry):
    """등록→보관→활성화→삭제 수명 + 같은 정체성 loud 거절이 두 구현에서 같다."""
    vm = DatasetPoolViewModel(registry)
    vm.register_excel("7월", "/a.xlsx", note="첫 등록")
    key = vm.rows()[0].key
    with pytest.raises(ValueError, match="이미"):
        vm.register_excel("다른이름", "/a.xlsx")
    vm.archive(key)
    assert vm.rows()[0].status == "archived"
    vm.activate(key)
    assert vm.rows()[0].status == "active"
    vm.delete(key)
    assert vm.is_empty()


def test_relabel_confirmed_binds_to_shown_state(registry):
    vm = DatasetPoolViewModel(registry)
    vm.register_excel("발주", "/a.xlsx")
    key = vm.rows()[0].key
    _item, basis = vm.inspect(key)

    updated = vm.relabel_confirmed("/a.xlsx", "", "발주 최신", basis=basis)
    assert updated.name == "발주 최신"
    # 낡은 지문(라벨 갱신 전 상태)으로는 fail-closed — 갱신 0건.
    with pytest.raises(StaleConfirmError):
        vm.relabel_confirmed("/a.xlsx", "", "또 갱신", basis=basis)
    assert vm.rows()[0].name == "발주 최신"
    # 확인 사이 삭제된 항목은 신규 등록으로 부활하지 않는다.
    vm.delete(key)
    with pytest.raises(FileNotFoundError):
        vm.relabel_confirmed("/a.xlsx", "", "부활", basis=basis)
    assert vm.is_empty()


def test_relink_confirmed_keeps_slot_and_rejects_identity_theft(registry):
    vm = DatasetPoolViewModel(registry)
    vm.register_excel("A", "/a.xlsx", note="6월분")
    vm.register_excel("B", "/b.xlsx")
    rows = {r.name: r for r in vm.rows()}
    vm.archive(rows["A"].key)  # 보관 수명이 재연결에도 보존되는지 함께 본다

    _item, basis = vm.inspect(rows["A"].key)
    updated = vm.relink_confirmed(rows["A"].key, "/a2.xlsx", basis=basis)
    assert updated.opts["path"] == "/a2.xlsx"
    assert updated.status == "archived"   # 수명 보존 — 조용한 재활성화 금지
    assert updated.note == "6월분"        # 빈 메모 입력 = 진술 없음(보존)

    # 다른 슬롯의 정체성으로는 못 갈아탄다(같은 데이터 2건 봉쇄, loud).
    _b, basis_b = vm.inspect(rows["B"].key)
    with pytest.raises(ValueError, match="이미"):
        vm.relink_confirmed(rows["B"].key, "/a2.xlsx", basis=basis_b)
    # 낡은 지문은 fail-closed(변이 0건) — 근거 미동봉(None)도 같은 거절이다.
    with pytest.raises(StaleConfirmError):
        vm.relink_confirmed(rows["A"].key, "/a3.xlsx", basis=basis)
    with pytest.raises(StaleConfirmError):
        vm.relink_confirmed(rows["A"].key, "/a3.xlsx", basis=None)
    assert vm.registry.load(rows["A"].key).opts["path"] == "/a2.xlsx"


def test_delete_confirmed_is_fail_closed_without_fresh_basis(registry):
    vm = DatasetPoolViewModel(registry)
    vm.register_excel("발주", "/a.xlsx")
    key = vm.rows()[0].key
    _item, basis = vm.inspect(key)
    vm.relabel(key, "남이 개명")  # 확인 사이 다른 writer 의 변경

    with pytest.raises(StaleConfirmError):
        vm.delete_confirmed(key, basis=basis)
    assert not vm.is_empty()  # 삭제 0건
    _item2, fresh = vm.inspect(key)
    deleted = vm.delete_confirmed(key, basis=fresh)
    assert deleted.name == "남이 개명"
    assert vm.is_empty()


def test_resolve_duplicates_contract_holds_for_both_ports(registry):
    """중복 그룹 표면화→확정 병합→그룹 소멸이 두 구현에서 같은 계약으로 선다."""
    _seed_slot(registry, "7월 공고", "/same.xlsx")
    keep = _seed_slot(registry, "공고 최신", "/same.xlsx")
    vm = DatasetPoolViewModel(registry)
    assert len(vm.duplicates()) == 1
    group = vm.duplicate_group(keep)
    assert group is not None and len(group) == 2
    basis = confirm_basis([bound_state(k, it) for k, it in group])

    # 확인 사이 멤버가 바뀌면 삭제 0건 + fail-closed.
    vm.relabel(group[0][0], "남이 개명")
    with pytest.raises(StaleConfirmError):
        vm.resolve_duplicates(keep, basis=basis)
    assert len(vm.rows()) == 2

    fresh_group = vm.duplicate_group(keep)
    fresh = confirm_basis([bound_state(k, it) for k, it in fresh_group])
    kept, removed = vm.resolve_duplicates(keep, basis=fresh)
    assert (kept, removed) == ("공고 최신", 1)
    assert [r.name for r in vm.rows()] == ["공고 최신"]
    assert vm.duplicates() == [] and vm.duplicate_group(keep) is None
    # 그룹이 사라진 뒤의 낡은 확정은 실행되지 않는다.
    with pytest.raises(FileNotFoundError):
        vm.resolve_duplicates(keep, basis=fresh)


def test_relink_and_relabel_carry_sheet_note_name_for_both_ports(registry):
    """재연결·재라벨의 조건 갱신 축 — 시트 명시·비고 진술·라벨 동반 갱신이 보존된다.

    비어 있으면 기존 값 보존(조용한 소거 금지), 있으면 그 확정에 함께 착지한다 —
    kind/opts 정합(하이브리드 손상 금지)까지 두 구현이 같은 계약이다.
    """
    vm = DatasetPoolViewModel(registry)
    vm.register_excel("발주", "/a.xlsx")
    key = vm.rows()[0].key
    _item, basis = vm.inspect(key)
    updated = vm.relink_confirmed(
        key, "/b.xlsx", sheet="7월", note="월분 교체", name="발주 7월", basis=basis
    )
    assert updated.kind == "excel"
    assert updated.opts == {"path": "/b.xlsx", "sheet": "7월"}
    assert updated.note == "월분 교체" and updated.name == "발주 7월"

    same = registry.find_identity("/b.xlsx", "7월")
    assert same is not None and same[0] == key
    relabeled = registry.relabel(key, "발주 8월", note="차월 재사용")
    assert relabeled.name == "발주 8월" and relabeled.note == "차월 재사용"

    # 확인 사이 삭제된 슬롯의 확정은 부활이 아니라 loud 부재로 접힌다(손상 키 포함).
    _item2, fresh = vm.inspect(key)
    vm.delete_confirmed(key, basis=fresh)
    with pytest.raises(FileNotFoundError):
        vm.delete_confirmed(key, basis=fresh)
