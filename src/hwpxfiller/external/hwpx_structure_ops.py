"""열린 HWPX package의 Slot 구조 변이와 컴파일."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from hwpxcore.bookmark_region import (
    BookmarkRegion,
    append_bookmark_metatag,
    create_bookmark_region,
    remove_bookmark_region,
    remove_top_level_paragraph,
    replace_bookmark_metatag,
    resolve_bookmark_topology,
    unwrap_bookmark_region,
)
from hwpxcore.native_admission import (
    BookmarkRemovalBlockerKind,
    FieldFillBlockerKind,
    inspect_native_capabilities,
)
from hwpxcore.structural_boundary import scan_structural_boundaries
from hwpxcore.text_extract import PackageLike, require_package, section_xml_names

from ..domain.authoring import (
    PLACEMENT_OPTION,
    PLACEMENT_SLOT,
    StructureScan,
    begin_marker_text,
    end_marker_text,
    insert_marker_paragraphs,
    scan_structure,
)
from ..domain.slot import Slot, SlotOption
from . import hwpx_product_inspection as _product_inspection

def _require_mutable_snapshot(
    pkg: object,
) -> tuple[object, _product_inspection._SlotSnapshot]:
    package = require_package(pkg)
    snapshot = _product_inspection._inspect_slot_snapshot(package)
    if snapshot.diagnostics:
        details = "; ".join(
            f"{item.kind}: {item.message}" for item in snapshot.diagnostics
        )
        raise ValueError(f"Slot mutation blocked by diagnostics: {details}")
    return package, snapshot


def _guarded_slot_mutation(
    package: object,
    mutate: "Callable[[], None]",
    verify: "Callable[[], None]",
) -> None:
    """제품 Slot 변이의 공용 몸통 — entries 백업 → 변이 → 사후조건 → 실패 시 롤백.

    사후조건이 동사마다 다르므로(삭제는 남은 Slot, 풀기는 표기 복원까지) 검사 자체는
    호출자가 ``verify`` 로 싣는다. **롤백 범위는 이 몸통 하나**라 어느 동사도 반쯤
    바뀐 패키지를 남기지 않는다.
    """
    entries = package.entries  # type: ignore[attr-defined]
    original = dict(entries)
    try:
        mutate()
        verify()
    except Exception:
        entries.clear()
        entries.update(original)
        raise


def _require_slots(
    package: object, expected: "tuple[Slot, ...]", what: str
) -> None:
    """변이 후 제품 판독이 기대치와 같은가 — 다르면 어느 동사가 왜 깨졌는지 남긴다."""
    actual, diagnostics = _product_inspection.inspect_slots(package)
    if diagnostics or actual != expected:
        raise ValueError(
            f"{what} postcondition failed: "
            f"expected {expected!r}, got {actual!r} with {diagnostics!r}"
        )


def _remove_product_region(
    package: object,
    region: BookmarkRegion,
    expected: tuple[Slot, ...],
) -> None:
    _guarded_slot_mutation(
        package,
        lambda: remove_bookmark_region(package, region),
        lambda: _require_slots(package, expected, "Slot removal"),
    )


def remove_slot(pkg: object, slot_id: str) -> None:
    """Remove one canonical Slot region selected by its product id."""
    identifier = _product_inspection._require_text(slot_id, "Slot id")
    package, snapshot = _require_mutable_snapshot(pkg)
    region = snapshot.slot_regions.get(identifier)
    if region is None:
        raise ValueError(f"Slot {identifier!r} was not found")
    expected = tuple(slot for slot in snapshot.slots if slot.id != identifier)
    _remove_product_region(package, region, expected)


def remove_slot_option(pkg: object, slot_id: str, option_id: str) -> None:
    """Remove one canonical Slot Option selected by its Slot-local product id."""
    owner_id = _product_inspection._require_text(slot_id, "Slot id")
    target_id = _product_inspection._require_text(option_id, "Slot Option id")
    package, snapshot = _require_mutable_snapshot(pkg)
    region = snapshot.option_regions.get((owner_id, target_id))
    if region is None:
        raise ValueError(
            f"Option {target_id!r} was not found in Slot {owner_id!r}"
        )
    expected = tuple(
        slot
        if slot.id != owner_id
        else Slot(
            slot.id,
            tuple(
                SlotOption(option.id, order, option.label)
                for order, option in enumerate(
                    item for item in slot.options if item.id != target_id
                )
            ),
            slot.label,
        )
        for slot in snapshot.slots
    )
    _remove_product_region(package, region, expected)


# --------------------------------------- 컴파일된 Slot 의 개명·표기로 풀기(S8-03 #834)
# 삭제(:func:`remove_slot`)와 같은 결이다: ``_require_mutable_snapshot`` fail-closed →
# 변이 전 좌표·핸들 확보 → :func:`_guarded_slot_mutation` 안에서 변이·사후조건·롤백.
# **커널 신설 0** — 소비하는 프리미티브는 ``replace_bookmark_metatag``(개명)과
# ``unwrap_bookmark_region``(풀기)뿐이고, 마커 문단 저작은 Domain 이 진다.


def _is_product_payload(raw: str) -> bool:
    """이 MetaTag 문자열이 제품 payload 인가(``hwpxFiller`` 보유)."""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(value, dict) and "hwpxFiller" in value


def _product_metatag_index(region: BookmarkRegion) -> int:
    """제품 payload 를 실은 ``hp:metaTag`` 의 **순서 index**(교체 프리미티브의 주소).

    진단 0 인 스냅샷에서만 부른다 — 제품 payload 가 2건 이상이면
    ``conflicting-product-metatag`` 진단이 먼저 서서 여기 도달하지 않는다. 그래도
    1건이 아니면 엉뚱한 MetaTag 를 덮지 않고 시끄럽게 멈춘다.
    """
    matches = [
        index for index, raw in enumerate(region.meta_tags) if _is_product_payload(raw)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"product MetaTag is not uniquely addressable: {region.name!r} ({len(matches)})"
        )
    return matches[0]


def _relocate_region(package: object, region: BookmarkRegion) -> BookmarkRegion:
    """같은 정체(이름·좌표·MetaTag)의 **현재** 핸들을 다시 집는다.

    핸들은 섹션 바이트에 묶여 있어 변이 한 번이면 낡는다(:func:`_locate_region` 동형).
    여러 region 을 잇달아 걷을 때 각 걸음 직전에 이것으로 되집는다.
    """
    identity = (
        region.section,
        region.name,
        region.start_paragraph,
        region.end_paragraph,
        region.meta_tags,
    )
    matches = [
        item
        for item in resolve_bookmark_topology(package)
        if (
            item.section,
            item.name,
            item.start_paragraph,
            item.end_paragraph,
            item.meta_tags,
        )
        == identity
    ]
    if len(matches) != 1:
        raise ValueError(
            f"BOOKMARK is not uniquely resolvable: {identity!r} ({len(matches)})"
        )
    return matches[0]


def _region_identity_counter(
    regions: "Iterable[BookmarkRegion]",
) -> "Counter[tuple[object, ...]]":
    """region 정체(이름·MetaTag)의 다중집합 — 위치·계층은 뺀다.

    위치는 마커 문단이 늘면서 **의도대로** 밀린다. 계층도 뺀다: 걷어낸 region 안에
    있던 남의 region 은 커널 unwrap 이 부모로 승격시키는 것이 계약이고 그 승격의
    정확성은 커널 자신의 사후조건이 이미 검사한다. 여기서 계층까지 못박으면 정상적인
    승격이 「보존 실패」로 뒤집힌다.
    """
    return Counter(
        (region.section, region.name, region.meta_tags, region.meta_tag_attribute)
        for region in regions
    )


def rename_slot_label(pkg: object, slot_id: str, new_label: "str | None" = None) -> None:
    """컴파일된 Slot 의 **label 만** 바꾼다(구조 무변형).

    ``new_label`` 이 ``None`` 이거나 공백뿐이면 label 을 **뗀다**(payload 에서 키 탈락).
    공백은 접는다 — 되쓰기(:func:`decompile_slot`)가 도로 읽을 수 있는 값만 만든다.
    """
    identifier = _product_inspection._require_text(slot_id, "Slot id")
    if new_label is not None and not isinstance(new_label, str):
        raise ValueError(f"Slot label must be str or None: {type(new_label)!r}")
    label = " ".join(new_label.split()) if new_label else ""
    package, snapshot = _require_mutable_snapshot(pkg)
    region = snapshot.slot_regions.get(identifier)
    if region is None:
        raise ValueError(f"Slot {identifier!r} was not found")
    index = _product_metatag_index(region)
    expected = tuple(
        Slot(slot.id, slot.options, label or None) if slot.id == identifier else slot
        for slot in snapshot.slots
    )
    payload = _product_inspection.serialize_slot_metatag(
        next(slot for slot in expected if slot.id == identifier)
    )
    _guarded_slot_mutation(
        package,
        lambda: replace_bookmark_metatag(package, region, index, payload),
        lambda: _require_slots(package, expected, "Slot rename"),
    )


def _notation_identity(slots: "tuple[Slot, ...]") -> "list[Slot]":
    """표기 선언 대조용 정규형 — id 순 정렬(문서 안에서 선언 id 는 유일하다).

    풀기는 표기가 이미 서 있는 문서에도 걸린다(부분 컴파일 · 전체판의 2번째 슬롯부터).
    그때 새로 풀린 선언이 기존 표기의 앞에 설지 뒤에 설지는 **문서 좌표**가 정하는
    것이지 사후조건이 재판정할 사실이 아니다 — 선언 **안**의 순서(선택 order)는 Slot
    값 자체가 지므로 여기서 잃는 것이 없다.
    """
    return sorted(slots, key=lambda slot: slot.id)


def decompile_slot(pkg: object, slot_id: str) -> None:
    """컴파일된 Slot 하나를 **구간 표기로 되돌린다**(:func:`compile_structure` 의 역함수).

    ① 대상 Slot region 과 소속 Option region 의 **변이 전 좌표**를 뜬다.
    ② Option → Slot 순으로 ``unwrap_bookmark_region`` 으로 ctrl 쌍만 걷는다(문단
       무변형이라 ①의 좌표가 그대로 유효하다).
    ③ 그 좌표에 마커 문단을 되심는다 — 문서 읽기 순서(항목 여는 마커 → 선택 마커들 →
       항목 닫는 마커)대로 실어 보내고 삽입 순서 처리는 Domain 이 진다.
    ④ 사후조건: 표기 진단 0 · 그 선언이 **기존 표기 위에** 더해져 전건 복원 · 남은 제품
       Slot == 기존 − 대상 · 비제품 region 정체 보존. 하나라도 깨지면 원본으로 돌아간다.

    대상은 언제나 Slot 하나다. 문서 전체는 :func:`decompile_structure` 가 이 동사를
    **반복 호출**해 세운다(U4-E3 #939 — 매 호출이 좌표를 다시 세우므로 앞선 풀기가 민
    문단 index 를 물려받지 않는다).
    """
    identifier = _product_inspection._require_text(slot_id, "Slot id")
    package, snapshot = _require_mutable_snapshot(pkg)
    region = snapshot.slot_regions.get(identifier)
    if region is None:
        raise ValueError(f"Slot {identifier!r} was not found")
    slot = next(item for item in snapshot.slots if item.id == identifier)
    options = [
        (option, snapshot.option_regions[(identifier, option.id)])
        for option in slot.options
    ]
    entry = region.section
    for option, option_region in options:
        if option_region.section != entry:
            # 범위는 한 content XML 안에서 닫힌다(스캐너와 같은 계약) — 어긋나면
            # 되쓴 표기가 도로 읽히지 않는다.
            raise ValueError(
                f"Slot {identifier!r} option {option.id!r} lives in another entry"
            )

    markers: "list[tuple[int, str]]" = [
        (region.start_paragraph, begin_marker_text(PLACEMENT_SLOT, slot.id, slot.label))
    ]
    for option, option_region in options:
        markers.append(
            (
                option_region.start_paragraph,
                begin_marker_text(PLACEMENT_OPTION, option.id, option.label),
            )
        )
        markers.append((option_region.end_paragraph + 1, end_marker_text(PLACEMENT_OPTION)))
    markers.append((region.end_paragraph + 1, end_marker_text(PLACEMENT_SLOT)))

    expected = tuple(item for item in snapshot.slots if item.id != identifier)
    before = _region_identity_counter(resolve_bookmark_topology(package))
    removed = _region_identity_counter(
        [region, *(option_region for _option, option_region in options)]
    )
    #: 변이 **전** 표기 — 되돌린 선언은 이 위에 더해져야 한다(기존 표기를 먹지 않는다).
    notation_before = scan_structure(package).slots

    def mutate() -> None:
        for _option, option_region in options:
            unwrap_bookmark_region(package, _relocate_region(package, option_region))
        unwrap_bookmark_region(package, _relocate_region(package, region))
        insert_marker_paragraphs(package, entry, markers)

    def verify() -> None:
        residue = scan_structure(package)
        expected_notation = (*notation_before, slot)
        if residue.diagnostics or _notation_identity(
            residue.slots
        ) != _notation_identity(expected_notation):
            raise ValueError(
                "Slot decompile postcondition (notation) failed: "
                f"expected {expected_notation!r}, got {residue.to_dict()!r}"
            )
        _require_slots(package, expected, "Slot decompile")
        after = _region_identity_counter(resolve_bookmark_topology(package))
        if after != before - removed:
            raise ValueError(
                "Slot decompile postcondition (pre-existing regions) failed: "
                f"expected {sorted(map(repr, before - removed))!r}, "
                f"got {sorted(map(repr, after))!r}"
            )

    _guarded_slot_mutation(package, mutate, verify)


def _assert_decompile_structure_postconditions(
    package: object,
    declared: "tuple[Slot, ...]",
    before: "Counter[tuple[object, ...]]",
    removed: "Counter[tuple[object, ...]]",
) -> None:
    """전체판 **종료 상태** — ⓐ 남은 native Slot 0 · ⓑ 선언 전건 되읽기 · ⓒ 비제품 region 보존.

    슬롯별 사후조건은 이미 각 :func:`decompile_slot` 호출이 졌다. 여기서 다시 재는 것은
    **한 슬롯의 성공들이 문서 하나의 성공과 같은가**뿐이다 — 중간 단계가 전부 초록이어도
    마지막에 native 구조가 남아 있거나 표기 한 건이 유실됐으면 전체판은 실패다.
    """
    _require_slots(package, (), "Structure decompile")
    residue = scan_structure(package)
    if residue.diagnostics or _notation_identity(residue.slots) != _notation_identity(
        declared
    ):
        raise ValueError(
            "structure decompile postcondition (notation) failed: "
            f"expected {declared!r}, got {residue.to_dict()!r}"
        )
    after = _region_identity_counter(resolve_bookmark_topology(package))
    if after != before - removed:
        raise ValueError(
            "structure decompile postcondition (pre-existing regions) failed: "
            f"expected {sorted(map(repr, before - removed))!r}, "
            f"got {sorted(map(repr, after))!r}"
        )


def decompile_structure(pkg: object) -> "tuple[Slot, ...]":
    """열린 package 의 **전 Slot** 을 구간 표기로 되돌린다(:func:`compile_structure` 의 역함수).

    새 풀기 기제를 만들지 않는다 — :func:`decompile_slot` 을 문서 순서대로 반복 호출하고,
    매 호출이 ``_require_mutable_snapshot`` 으로 **좌표를 다시 세운다**. 앞선 풀기가 마커
    문단을 심어 뒤 슬롯의 문단 index 를 밀어도 그 이동이 다음 호출에 새지 않는 근거가 이것이다.

    **원자성은 문서 단위**다(:func:`compile_structure` 선례 동형): 진입에서 ``entries`` 를
    통째로 백업하고 어느 한 슬롯이라도 실패하면 **전량 원복 후 raise** 한다 — 반쯤 풀린
    템플릿을 남기지 않는다. 슬롯이 0 이면 무변형 no-op 이고 빈 튜플을 돌려준다.

    반환은 **되돌린 선언 목록**(변이 전 제품 판독 그대로)이라 상위 링이 결과를 재진술하려고
    파일을 다시 열지 않는다. 진단이 서 있으면 단건 동사와 같이 fail-closed 로 거절한다.

    #822 D6(「일괄 풀기 없음」)은 U4-E3 에서 철회됐다: 금지의 근거는 단건 동사가 세운
    안전 불변식(사후조건 4종 + 롤백)이 전체판에 없다는 것이었는데, 전체판이 그 동사를
    **그대로 반복**하고 같은 사후조건을 종료 상태에서 한 번 더 상속하므로 근거가 소멸했다.
    """
    package, snapshot = _require_mutable_snapshot(pkg)
    declared = snapshot.slots
    if not declared:
        return ()
    before = _region_identity_counter(resolve_bookmark_topology(package))
    removed = _region_identity_counter(
        [*snapshot.slot_regions.values(), *snapshot.option_regions.values()]
    )
    entries = package.entries  # type: ignore[attr-defined]
    original = dict(entries)
    try:
        for slot in declared:
            decompile_slot(package, slot.id)
        _assert_decompile_structure_postconditions(package, declared, before, removed)
    except Exception:
        entries.clear()
        entries.update(original)
        raise
    return declared


# ------------------------------------------------- 구간 표기 → native Slot 컴파일(S8-02)
# **왜 여기(External)인가.** #822 는 domain 확장을 「제안」했지만, 이 오케스트레이션의
# 사후조건이 :func:`inspect_slots`(External 이 소유한 제품 판독)를 요구하고, 「entries
# 백업 → 변이 → 사후조건 대조 → 실패 시 롤백」 선례도 이 모듈(:func:`_remove_product_region`)
# 이 이미 진다. Domain 에 두면 Domain 이 External 을 역참조해야 해 P2-19R 이 깨진다.
#
# **필드 토큰(``{{필드}}``) 컴파일은 이 함수가 하지 않는다** — 그것은
# :func:`~hwpxfiller.domain.authoring.compile_document` 소관이고, 표면에서 두 동사를
# 「누름틀·구간 변환」 하나로 묶을지는 S8-03 판단이다.


def structure_region_name(slot_id: str, option_id: "str | None" = None) -> str:
    """컴파일이 만들 native BOOKMARK ``name`` — 단일 출처.

    S1 canonical 규약에서 제품 의미를 지는 것은 ``hp:metaTag`` payload 하나뿐이다
    (``{"hwpxFiller":{kind,id[,label]},"name":"#hf"}`` — :func:`serialize_slot_metatag`).
    BOOKMARK ``name`` 은 한글 「책갈피」 목록에 그대로 보이는 사람용 이름이라 새 어휘를
    만들지 않고 **선언 id 를 그대로** 쓰고, 선택만 소속 항목을 앞에 붙여 문서 전역에서
    갈리게 한다.
    """
    return slot_id if option_id is None else f"{slot_id}/{option_id}"


class StructureCompileRefusalKind(StrEnum):
    """컴파일 거절 사유의 안정 식별자 — 상위 링이 문안 대신 이 값으로 분기한다."""

    NOTATION_DIAGNOSTIC = "notation-diagnostic"
    UNSUPPORTED_ENTRY = "unsupported-entry"
    NATIVE_BLOCKER = "native-blocker"
    EXISTING_PRODUCT = "existing-product"
    NAME_COLLISION = "name-collision"
    EXISTING_REGION_OVERLAP = "existing-region-overlap"


#: :attr:`StructureCompileRefusalKind.EXISTING_PRODUCT` 의 전용 code — 선언 id 가 기존
#: 제품 Slot id 와 겹쳤다(사후조건 성립 불가). 기존 제품 **판독 진단** 과 갈라 두는 이유는
#: 상위 링의 조치가 다르기 때문이다(id 를 바꾼다 vs 깨진 구조를 고친다).
DUPLICATE_SLOT_ID = "duplicate-slot-id"


@dataclass(frozen=True)
class StructureCompileRefusal:
    """거절 1건 — ``code`` 는 하위 어휘(진단 kind·blocker kind)의 값 그대로다."""

    kind: StructureCompileRefusalKind
    code: str
    message: str

    def to_dict(self) -> "dict[str, str]":
        return {"kind": str(self.kind), "code": self.code, "message": self.message}


@dataclass(frozen=True)
class StructureCompileReport:
    """구간 표기 컴파일 결과.

    ``refusal`` 이 ``None`` 이 아니면 **변이는 0건**이고 사유가 전량 재진술돼 있다.
    ``modified=False`` + ``refusal=None`` 은 바꿀 마커가 없었다는 뜻이다(no-op).
    ``options`` 는 ``slots`` 를 상위 링이 다시 세지 않게 하는 편의 수치다.
    """

    modified: bool
    slots: "tuple[Slot, ...]"
    options: int
    refusal: "tuple[StructureCompileRefusal, ...] | None"

    def to_dict(self) -> "dict[str, Any]":
        return {
            "modified": self.modified,
            "slots": [
                {
                    "id": slot.id,
                    "label": slot.label or "",
                    "options": [
                        {"id": option.id, "label": option.label or ""}
                        for option in slot.options
                    ],
                }
                for slot in self.slots
            ],
            "options": self.options,
            "refusal": (
                None if self.refusal is None else [item.to_dict() for item in self.refusal]
            ),
        }


#: 컴파일 자체를 막는 removal blocker 어휘 — 「이 entry 의 구조 판독을 못 믿는다」 급만
#: 고른다. 나머지(WHOLE_SECTION·COLLATERAL_BOOKMARK·PARTIAL_PARAGRAPH_* 등)는 **기존
#: region 하나를 삭제할 때**의 기하 문제라 새 region 생성을 막을 이유가 없다.
_COMPILE_BLOCKING_REMOVAL_BLOCKERS = frozenset(
    {
        BookmarkRemovalBlockerKind.UNSUPPORTED_ENTRY,
        BookmarkRemovalBlockerKind.BOOKMARK_TOPOLOGY_UNUSABLE,
        BookmarkRemovalBlockerKind.BOOKMARK_METADATA_UNUSABLE,
        BookmarkRemovalBlockerKind.FIELD_PAIRING_UNUSABLE,
    }
)
_RegionShape = tuple[object, object]


def _created_region_names(scan: StructureScan) -> "frozenset[tuple[str, str]]":
    """컴파일이 만들 (entry, BOOKMARK name) 집합 — 생성·대조가 같은 출처를 본다."""
    return frozenset(
        (
            placement.entry,
            structure_region_name(
                placement.slot_id,
                placement.option_id if placement.kind == PLACEMENT_OPTION else None,
            ),
        )
        for placement in scan.placements
    )


def _refusal(
    kind: StructureCompileRefusalKind, code: object, message: str
) -> StructureCompileRefusal:
    return StructureCompileRefusal(kind, str(code), message)


def _structure_preflight(
    package: PackageLike, scan: StructureScan
) -> "tuple[StructureCompileRefusal, ...]":
    """변이 전에 기존 native 상태를 **구조화 API 로만** 확인한다.

    커널 예외 문자열을 파싱하지 않는다 — blocker 어휘(:class:`BookmarkRemovalBlockerKind`
    ·:class:`FieldFillBlockerKind`)와 scan 의 entry 급 usable 플래그만 읽는다. 단계마다
    거절이 서면 즉시 멈춘다: 뒤 단계는 앞 단계가 성립해야 의미가 있는 판독이다.

    누름틀 짝짓기가 깨진 문서는 :class:`FieldFillObservation` 자체가 나오지 않으므로
    (커널이 진단이 있는 entry 의 occurrence 를 전량 버린다) 그 조건은 entry 급
    ``field_pairing_usable`` 플래그로 받는다 — 관찰이 없는 어휘를 훑는 죽은 경로를
    두지 않는다.
    """
    refusals: "list[StructureCompileRefusal]" = []
    sections = set(section_xml_names(package))
    for placement in scan.placements:
        if placement.entry not in sections:
            refusals.append(
                _refusal(
                    StructureCompileRefusalKind.UNSUPPORTED_ENTRY,
                    placement.entry,
                    f"「{placement.slot_id}」 범위가 본문 섹션이 아닌 {placement.entry} 에 "
                    "있습니다 — 구간은 본문 섹션에서만 만들 수 있습니다.",
                )
            )

    boundary = scan_structural_boundaries(package)
    capabilities = inspect_native_capabilities(package, boundary)
    for entry in boundary.entries:
        if not entry.field_pairing_usable:
            refusals.append(
                _refusal(
                    StructureCompileRefusalKind.NATIVE_BLOCKER,
                    FieldFillBlockerKind.FIELD_PAIRING_UNUSABLE,
                    f"{entry.entry}: 기존 누름틀 짝짓기를 신뢰할 수 없습니다.",
                )
            )
        if not entry.bookmark_topology_usable:
            refusals.append(
                _refusal(
                    StructureCompileRefusalKind.NATIVE_BLOCKER,
                    BookmarkRemovalBlockerKind.BOOKMARK_TOPOLOGY_UNUSABLE,
                    f"{entry.entry}: 기존 BOOKMARK 계층을 신뢰할 수 없습니다.",
                )
            )
    for removal in capabilities.bookmark_removals:
        for blocker in removal.blockers:
            if blocker.kind in _COMPILE_BLOCKING_REMOVAL_BLOCKERS:
                refusals.append(
                    _refusal(
                        StructureCompileRefusalKind.NATIVE_BLOCKER,
                        blocker.kind,
                        "; ".join(blocker.detail) or str(blocker.kind),
                    )
                )
    if refusals:
        return tuple(dict.fromkeys(refusals))

    # 기존 제품 Slot 과의 공존(S8-03 D6). 사후조건 ⓐ 는 「컴파일 뒤 제품 Slot ==
    # 기존 ∪ 선언」으로 일반화됐으므로(:func:`_merged_slot_expectation`) 유효한 기존
    # 구조는 더 이상 거절 사유가 아니다 — 풀기→한글 수정→재컴파일 왕복은 **다른 슬롯이
    # 컴파일된 채 남아 있는 문서**에서 성립해야 하는 경로다. 남는 거절은 둘이다:
    # 기존 제품 판독 진단(그 문서의 구조를 못 믿는다)과 **id 중복**(같은 id 가 둘이면
    # 사후조건이 성립할 수 없고 판독도 어느 쪽을 가리키는지 갈린다).
    existing, diagnostics = _product_inspection.inspect_slots(package)
    refusals.extend(
        _refusal(
            StructureCompileRefusalKind.EXISTING_PRODUCT, item.kind, item.message
        )
        for item in diagnostics
    )
    taken = {slot.id for slot in existing}
    refusals.extend(
        _refusal(
            StructureCompileRefusalKind.EXISTING_PRODUCT,
            DUPLICATE_SLOT_ID,
            f"'{slot.id}' 항목이 이미 누름틀 구조로 들어 있습니다. 표기의 id 를 바꾸거나 "
            "기존 항목을 먼저 지우세요.",
        )
        for slot in scan.slots
        if slot.id in taken
    )
    if refusals:
        return tuple(refusals)

    # 같은 이름의 기존 BOOKMARK 가 있으면 「신설분 제외」 대조(사후조건 ⓒ)가 어느 쪽을
    # 가리키는지 갈리지 않는다 — 조용히 틀리는 대신 먼저 거절한다.
    wanted = _created_region_names(scan)
    existing_regions = tuple(resolve_bookmark_topology(package))
    for region in existing_regions:
        if (region.section, region.name) in wanted:
            refusals.append(
                _refusal(
                    StructureCompileRefusalKind.NAME_COLLISION,
                    region.name,
                    f"{region.section}: 「{region.name}」 이름의 책갈피가 이미 있습니다 — "
                    "선언 id 를 바꾸거나 기존 책갈피를 지우세요.",
                )
            )
    refusals.extend(_existing_region_overlaps(scan, existing_regions))
    return tuple(dict.fromkeys(refusals))


def _existing_region_overlaps(
    scan: StructureScan, regions: "Iterable[BookmarkRegion]"
) -> "list[StructureCompileRefusal]":
    """선언 content 범위와 문단이 겹치는 기존 BOOKMARK 를 구조화 거절로 낸다(S8-F2 · #853).

    **판정 근거는 커널 실측이다.** 컴파일은 항목 region 을 ``parent=None`` 으로 만들므로
    (:func:`_create_structure_regions`) 겹치는 네 위상이 전부 커널에서 raise 로 닫힌다:

    - 기존이 범위 **안**(동일 span 포함) → 새 region 이 그것을 감싸 부모가 바뀐다
      (``creating BOOKMARK changed existing native topology``).
    - 기존이 범위를 **감싼다** → 새 region 이 그 자식으로 서는데 요청 부모는 ``None`` 이다
      (``created BOOKMARK does not match the requested native topology``).
    - **부분 교차** → ``crossing BOOKMARK regions are unsupported``.

    롤백은 정상이었으나 그 영문 문자열이 ``app.dispatch`` 봉투를 타고 그대로 사용자에게
    나갔다(감사 F-2). 그래서 겹침 전부를 여기서 먼저 한국어 사유로 닫는다 — 커널 raise 는
    심층 방어로 그대로 남는다. 겹치지 않는(disjoint) 기존 region 은 종전대로 통과하고
    사후조건 ⓒ 가 그 보존을 검증한다.
    """
    found: "list[StructureCompileRefusal]" = []
    for placement in scan.placements:
        name = structure_region_name(
            placement.slot_id,
            placement.option_id if placement.kind == PLACEMENT_OPTION else None,
        )
        for region in regions:
            if region.section != placement.entry:
                continue
            if (
                region.start_paragraph > placement.content_end
                or region.end_paragraph < placement.content_start
            ):
                continue  # disjoint — 컴파일이 건드리지 않는다
            label = region.name or "(이름 없음)"
            found.append(
                _refusal(
                    StructureCompileRefusalKind.EXISTING_REGION_OVERLAP,
                    region.name or "",
                    f"'{name}' 범위가 기존 '{label}' 책갈피와 겹칩니다. "
                    "그 책갈피를 범위 밖으로 옮기거나 지운 뒤 다시 변환하세요.",
                )
            )
    return found


def _non_product_region_shape(
    regions: "Iterable[BookmarkRegion]",
    created: "frozenset[tuple[str, str]]",
) -> "Counter[_RegionShape]":
    """신설분을 뺀 region 집합의 (이름·계층·metatag) 형상.

    위치는 뺀다 — 마커 문단이 사라지면서 남는 region 이 앞으로 당겨지는 것은 **의도된**
    변화다. 계층은 직계 부모 그대로 본다: 커널은 기존 region 을 새로 감싸는 생성을
    아예 거절하므로(``create_bookmark_region`` 의 「changed existing native topology」),
    살아남은 region 의 부모가 신설분으로 바뀌는 경우가 없다.
    """

    def identity(region: "BookmarkRegion | None") -> object:
        if region is None:
            return None
        return (
            region.section,
            region.name,
            region.meta_tags,
            region.meta_tag_attribute,
        )

    shape: "Counter[_RegionShape]" = Counter()
    for region in regions:
        if (region.section, region.name) in created:
            continue
        shape[(identity(region), identity(region.parent))] += 1
    return shape


def _create_structure_regions(package: PackageLike, scan: StructureScan) -> None:
    """선언대로 native region 을 만들고 metatag 를 붙인 뒤 마커 문단을 지운다.

    **순서 근거.** ``append_bookmark_metatag`` 와 문단 삭제는 섹션 바이트를 바꿔 이미
    받아 둔 :class:`~hwpxcore.bookmark_region.BookmarkRegion` 핸들의 동등성을 깨뜨린다.
    그래서 핸들을 쓰는 생성(부모 지정)이 **전부** 끝난 뒤에 metatag 를 붙이고, 문단
    삭제는 좌표까지 흔들므로 맨 마지막에 entry 별 내림차순으로 한다.
    """
    by_slot_id = {slot.id: slot for slot in scan.slots}
    slot_locator: "dict[str, tuple[str, str, int, int]]" = {}
    created: "list[tuple[tuple[str, str, int, int], str]]" = []

    for placement in scan.placements:
        slot = by_slot_id[placement.slot_id]
        parent = None
        if placement.kind == PLACEMENT_OPTION:
            name = structure_region_name(placement.slot_id, placement.option_id)
            option = next(
                item for item in slot.options if item.id == placement.option_id
            )
            payload = _product_inspection.serialize_slot_option_metatag(option)
            parent = _locate_region(package, slot_locator[placement.slot_id])
        else:
            name = structure_region_name(placement.slot_id)
            payload = _product_inspection.serialize_slot_metatag(slot)
        create_bookmark_region(
            package,
            placement.entry,
            placement.content_start,
            placement.content_end,
            name=name,
            parent=parent,
        )
        locator = (
            placement.entry,
            name,
            placement.content_start,
            placement.content_end,
        )
        if placement.kind == PLACEMENT_SLOT:
            slot_locator[placement.slot_id] = locator
        created.append((locator, payload))

    for locator, payload in created:
        append_bookmark_metatag(package, _locate_region(package, locator), payload)

    markers: "dict[str, set[int]]" = {}
    for placement in scan.placements:
        markers.setdefault(placement.entry, set()).update(
            (placement.begin_marker_index, placement.end_marker_index)
        )
    for entry in sorted(markers):
        for index in sorted(markers[entry], reverse=True):
            remove_top_level_paragraph(package, entry, index)


def _locate_region(
    package: PackageLike, locator: "tuple[str, str, int, int]"
) -> BookmarkRegion:
    """방금 만든 region 의 **현재** 핸들을 좌표+이름으로 다시 집는다.

    핸들은 섹션 바이트에 묶여 있어 다음 변이 한 번이면 낡는다. 이름 충돌은 preflight
    가 이미 거절했고, 여기서도 정확히 1건이 아니면 시끄럽게 멈춘다.
    """
    matches = [
        region
        for region in resolve_bookmark_topology(package)
        if (
            region.section,
            region.name,
            region.start_paragraph,
            region.end_paragraph,
        )
        == locator
    ]
    if len(matches) != 1:
        raise ValueError(
            f"created BOOKMARK is not uniquely resolvable: {locator!r} ({len(matches)})"
        )
    return matches[0]


def _merged_slot_expectation(
    package: PackageLike, scan: StructureScan
) -> "tuple[Slot, ...]":
    """사후조건 ⓐ 의 기대치 — 기존 slots ∪ 선언 slots 를 **문서 위치 순**으로 병합(S8-03).

    위치는 **변이 전 좌표**로 잰다: 기존 region 은 시작 문단, 선언은 배치의
    ``content_start``. 컴파일이 하는 변형은 마커 문단 삭제와 BOOKMARK 쌍 삽입뿐이라
    **상대 순서를 바꾸지 않으므로** 변이 전 좌표로 세운 이 순서가 변이 후 판독
    (:func:`inspect_slots` 의 문서 순서)과 같다.

    같은 좌표에서는 기존이 앞선다 — 선언 범위가 기존 region 을 품으면 커널이 먼저
    거절하므로(``changed existing native topology``) 실제로 겹치는 경우가 없고, 그래도
    갈리면 사후조건이 시끄럽게 깨지는 쪽을 고른다.
    """
    order = {name: index for index, name in enumerate(section_xml_names(package))}
    snapshot = _product_inspection._inspect_slot_snapshot(package)
    placed: "list[tuple[tuple[int, int, int], Slot]]" = []
    for slot in snapshot.slots:
        region = snapshot.slot_regions[slot.id]
        placed.append(((order[region.section], region.start_paragraph, 0), slot))
    starts = {
        placement.slot_id: (order[placement.entry], placement.content_start)
        for placement in scan.placements
        if placement.kind == PLACEMENT_SLOT
    }
    for slot in scan.slots:
        entry_index, start = starts[slot.id]
        placed.append(((entry_index, start, 1), slot))
    placed.sort(key=lambda item: item[0])
    return tuple(slot for _key, slot in placed)


def _assert_structure_postconditions(
    package: PackageLike,
    expected: "tuple[Slot, ...]",
    created: "frozenset[tuple[str, str]]",
    before: "Counter[_RegionShape]",
) -> None:
    """ⓐ 선언 복원 · ⓑ 표기 잔존 0 · ⓒ 기존 region 보존. 어느 쪽이 왜 깨졌는지 구분한다."""
    slots, diagnostics = _product_inspection.inspect_slots(package)
    if diagnostics or slots != expected:
        raise ValueError(
            "structure compile postcondition A (declared Slots) failed: "
            f"expected {expected!r}, got {slots!r} with {diagnostics!r}"
        )
    residue = scan_structure(package)
    if residue.slots or residue.diagnostics or residue.placements:
        raise ValueError(
            "structure compile postcondition B (notation residue) failed: "
            f"{residue.to_dict()!r}"
        )
    after = _non_product_region_shape(resolve_bookmark_topology(package), created)
    if after != before:
        raise ValueError(
            "structure compile postcondition C (pre-existing regions) failed: "
            f"expected {sorted(map(repr, before))!r}, got {sorted(map(repr, after))!r}"
        )


def compile_structure(pkg: object) -> StructureCompileReport:
    """열린 package 의 구간 표기를 native Slot 구조로 컴파일한다(제자리 변이).

    **전 단계가 한 흐름이고 부분 컴파일 경로가 없다**(#822 D3): 표기 진단이 1건이라도
    있거나 preflight blocker 가 서면 **변이 0건**으로 거절하고, 변환에 들어간 뒤에는
    사후조건 셋을 전부 통과해야 커밋한다 — 하나라도 깨지면 ``entries`` 를 원본으로
    되돌리고 어느 사후조건이 왜 깨졌는지 재진술해 raise 한다.
    """
    package = require_package(pkg)
    scan = scan_structure(package)
    if scan.diagnostics:
        return StructureCompileReport(
            False,
            (),
            0,
            tuple(
                _refusal(
                    StructureCompileRefusalKind.NOTATION_DIAGNOSTIC,
                    item.kind,
                    item.message,
                )
                for item in scan.diagnostics
            ),
        )
    if not scan.placements:
        return StructureCompileReport(False, (), 0, None)
    refusals = _structure_preflight(package, scan)
    if refusals:
        return StructureCompileReport(False, (), 0, refusals)

    created = _created_region_names(scan)
    before = _non_product_region_shape(
        resolve_bookmark_topology(package), frozenset()
    )
    expected = _merged_slot_expectation(package, scan)
    entries = package.entries
    original = dict(entries)
    try:
        _create_structure_regions(package, scan)
        _assert_structure_postconditions(package, expected, created, before)
    except Exception:
        entries.clear()
        entries.update(original)
        raise
    return StructureCompileReport(
        True, scan.slots, sum(len(slot.options) for slot in scan.slots), None
    )
