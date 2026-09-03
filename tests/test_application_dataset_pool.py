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
from hwpxfiller.data.factory import source_from_pool_item
from hwpxfiller.domain.dataset_reference import (
    DatasetReference,
    excel_identity,
    pclm_identity,
    reference_identity,
)
from hwpxfiller.domain.pclm_views import PCLM_VIEW_LABELS, PCLM_VIEWS
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

    def find_identity_raw(self, ident):
        for k, it in self.list_references()[0]:
            if reference_identity(it) == ident:
                return (k, it)
        return None

    def find_identity(self, path, sheet=""):
        return self.find_identity_raw(excel_identity(path, sheet))

    def add(self, item):
        ident = reference_identity(item)
        if ident is not None and self.find_identity_raw(ident):
            raise ValueError("같은 데이터가 이미 고정돼 있습니다.")
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

    def relabel_confirmed_raw(self, ident, name, *, note="", expected_basis):
        same = self.find_identity_raw(ident)
        if same is None:
            raise FileNotFoundError(name)
        key, existing = same
        self._check(expected_basis, [bound_state(key, existing)])
        return key, self.relabel(key, name, note=note)

    def relabel_confirmed(self, path, sheet, name, *, note="", expected_basis):
        return self.relabel_confirmed_raw(
            excel_identity(path, sheet or ""), name, note=note,
            expected_basis=expected_basis,
        )

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


def _vm(registry) -> DatasetPoolViewModel:
    """소스 복원기는 ``registry`` 와 같은 **필수 주입**이다(공용 ⑤ 리뷰).

    이 파일의 전건은 참조만 만지므로(등록은 데이터를 열지 않는다) 복원기가 불려 갈 일이
    없지만, 기본값을 두지 않는 것이 계약이라 조립도 여기서 한 번만 한다 — 포트가 늘면
    이 한 자리가 먼저 부러진다.
    """
    return DatasetPoolViewModel(registry, source_factory=source_from_pool_item)


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
    vm = _vm(registry)
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


def test_register_pclm_always_stores_both_opts_and_resolves_the_default_db(
    registry, monkeypatch, tmp_path
):
    """계약 목록 등록은 db·뷰 **두 키를 항상** 채운다 — 빈 db = 「기본 자리」의 해석.

    미기재로 두면 정체성이 지어지지 않아 중복 판정이 통째로 죽고, 나중에 기본 자리가
    바뀌면 같은 항목이 조용히 다른 DB 를 가리킨다.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    # 기본 자리 해석은 %APPDATA% 쪽지(config.json)도 본다 — 개발 기기의 실제 쪽지 격리.
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    vm = _vm(registry)

    item = vm.register_pclm("계약 목록", view="v_통합_v1", note="기본 자리")
    assert item.kind == "pclm"
    assert set(item.opts) == {"db", "view"}
    assert item.opts["db"] == str(tmp_path / "AppData" / "Local" / "Pclm" / "pclm.db")
    assert item.opts["view"] == "v_통합_v1"
    assert vm.find_same_pclm(str(item.opts["db"]), "v_통합_v1") is not None

    # 명시 db 는 절대경로로 정규화돼 들어간다(표기 변형은 정체성이 흡수).
    named = vm.register_pclm("다른 DB", str(tmp_path / "other.db"), view="v_품목_v1")
    assert named.opts == {"db": str(tmp_path / "other.db"), "view": "v_품목_v1"}
    # 같은 DB 의 다른 뷰는 **다른 데이터**다(계약면마다 한 줄의 뜻이 다르다).
    assert vm.find_same_pclm(str(tmp_path / "other.db"), "v_통합_v1") is None
    assert len(vm.rows()) == 2


def test_register_pclm_is_fail_closed_on_name_view_and_duplicate(registry, tmp_path):
    """빈 이름·미지 뷰·같은 정체성 재등록은 전부 loud — 죽은 참조를 조용히 만들지 않는다."""
    vm = _vm(registry)
    db = str(tmp_path / "pclm.db")
    with pytest.raises(ValueError, match="이름"):
        vm.register_pclm("  ", db, view="v_통합_v1")
    with pytest.raises(ValueError) as caught:
        vm.register_pclm("오타", db, view="v_통합")
    # 거절은 쓸 수 있는 뷰를 설명과 함께 재진술한다(허용목록 재구현 금지의 관측면).
    assert all(view in str(caught.value) for view in PCLM_VIEWS)
    assert PCLM_VIEW_LABELS["v_품목_v1"] in str(caught.value)
    assert vm.is_empty()

    vm.register_pclm("계약", db, view="v_계약_v1")
    with pytest.raises(ValueError, match="이미"):
        vm.register_pclm("다른 이름", db, view="v_계약_v1")
    assert len(vm.rows()) == 1


def test_relabel_confirmed_raw_binds_pclm_to_shown_state(registry, tmp_path):
    """정체성 판 확정 왕복이 계약 목록에도 같은 결속으로 선다(종류별 확정 경로 복제 금지)."""
    vm = _vm(registry)
    db = str(tmp_path / "pclm.db")
    vm.register_pclm("계약 목록", db, view="v_통합_v1")
    key = vm.rows()[0].key
    ident = pclm_identity(db, "v_통합_v1")
    _item, basis = vm.inspect(key)

    updated = vm.relabel_confirmed_raw(ident, "계약 목록(통합)", basis=basis)
    assert updated.name == "계약 목록(통합)"
    assert updated.opts == {"db": db, "view": "v_통합_v1"}  # 참조 불변
    with pytest.raises(StaleConfirmError):
        vm.relabel_confirmed_raw(ident, "또 갱신", basis=basis)
    with pytest.raises(StaleConfirmError):
        vm.relabel_confirmed_raw(ident, "근거 없음", basis=None)
    assert vm.rows()[0].name == "계약 목록(통합)"


def test_duplicate_pclm_registrations_merge_by_identity(registry, tmp_path):
    """손편집이 남긴 같은 DB+뷰 2건도 정체성으로 묶여 확정 병합된다(엑셀과 같은 기제)."""
    db = str(tmp_path / "pclm.db")
    ref = DatasetReference(name="구판", kind="pclm", opts={"db": db, "view": "v_공고_v1"})
    keep_ref = DatasetReference(
        name="최신", kind="pclm", opts={"db": db, "view": "v_공고_v1"}
    )
    if isinstance(registry, DatasetPoolRegistry):
        registry.directory.mkdir(parents=True, exist_ok=True)
        for slug, item in (("구판", ref), ("최신", keep_ref)):
            (registry.directory / f"{slug}{registry.SUFFIX}").write_text(
                json.dumps(item.to_dict(), ensure_ascii=False), encoding="utf-8"
            )
        keep = "최신"
    else:
        registry.slots["구판"] = ref
        registry.slots["최신"] = keep_ref
        keep = "최신"

    vm = _vm(registry)
    group = vm.duplicate_group(keep)
    assert group is not None and len(group) == 2
    basis = confirm_basis([bound_state(k, it) for k, it in group])
    kept, removed = vm.resolve_duplicates(keep, basis=basis)
    assert (kept, removed) == ("최신", 1)
    assert [r.name for r in vm.rows()] == ["최신"]


def test_relabel_confirmed_binds_to_shown_state(registry):
    vm = _vm(registry)
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
    vm = _vm(registry)
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
    vm = _vm(registry)
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
    vm = _vm(registry)
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
    vm = _vm(registry)
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
