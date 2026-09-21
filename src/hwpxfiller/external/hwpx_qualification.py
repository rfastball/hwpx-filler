"""Read-only HWPX qualification from a single native inspection snapshot."""

from __future__ import annotations

import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar, cast

from hwpxcore.native_admission import (
    BookmarkRemovalBlocker, BookmarkRemovalBlockerKind, FieldFillBlocker,
    FieldFillBlockerKind, FieldFillObservation, NativeCapabilityInspection,
    inspect_native_capabilities,
)
from hwpxcore.package import HwpxPackage
from hwpxcore.structural_boundary import (
    BookmarkBegin, BookmarkEnd, BoundaryPairRef, ContentEntryKind, FieldBegin,
    FieldEnd, StructuralBoundaryScan, scan_structural_boundaries,
)
from hwpxcore.text_extract import require_package, section_xml_names

from ..application.execution_composition import NATIVE_PRIMITIVE_CONTRACT_V1
from ..application.execution_structure import (
    LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA, OWNER_OPTION, OWNER_ROOT,
    OWNER_SLOT_SHARED, ContentEntry, ExecutionTemplateStructure, FieldOccurrence,
    OptionRegionObservation, SlotRegionObservation, build_execution_structure,
)
from ..application.template_qualification import (
    QualificationInspection, TemplateDiagnostic, TemplateInspectionContractError,
    TemplateOption, TemplateSlot, TemplateStructure,
)
from ..domain.fields import fill_precheck, is_fill_target_field_type, normalize_field_id
from .hwpx_product_inspection import (
    ProductBookmarkInspection, ProductClassification, ProductScopeRole,
    ProductScopeObservation, PRODUCT_KINDS, inspect_product_bookmarks,
)

@dataclass(frozen=True)
class _HwpxInspectionDetail:
    """External-only native evidence used to build a qualification result."""

    structural: StructuralBoundaryScan
    products: ProductBookmarkInspection
    capabilities: NativeCapabilityInspection


class _FieldOwnerTag(StrEnum):
    ROOT = "root"
    SLOT_SHARED = "slot_shared"
    OPTION = "option"
    UNRESOLVED = "unresolved"


_FieldOwner = tuple[_FieldOwnerTag, BoundaryPairRef | None]
_ObservationT = TypeVar("_ObservationT")
#: blocker 어휘 하나에 묶는 TypeVar — removal/fill 을 섞어 먹이지 못하게 한다(#773 리뷰).
_BlockerT = TypeVar("_BlockerT", BookmarkRemovalBlockerKind, FieldFillBlockerKind)


@dataclass
class _OpenField:
    pair: BoundaryPairRef
    raw_name: str | None
    field_id: str | None
    owner: _FieldOwner
    fill: FieldFillObservation
    #: 이 Field 가 열린 문서 순서(#773 composition projection 의 structural_order).
    structural_order: int = 0
    product_boundary_opened: bool = False
    #: 채울 누름틀인가 — 아니면 한글이 자동으로 낳은 필드다(#931).
    fill_target: bool = True
    #: 진단이 자리를 재진술하는 데 쓰는 표지(entry-local 필드 순번·원문 발췌).
    entry_ordinal: int = 0
    text_preview: str = ""


def _blocker_summary(
    blockers: tuple[FieldFillBlocker | BookmarkRemovalBlocker, ...],
) -> str:
    return "; ".join(
        item.kind.value + (f": {', '.join(item.detail)}" if item.detail else "")
        for item in blockers
    )


def _unnamed_field_message(entry: str, open_field: _OpenField) -> str:
    """이름 없는 누름틀 진단 문안 — 자리와 원문을 재진술한다(#931).

    ``repr(raw_name)`` 만 싣던 예전 문안은 이름이 빈 문자열일 때 ``Field ''`` 로 정보가
    0 이었고, 사용자가 문서에서 그 필드를 찾을 길이 없었다. entry·필드 순번·감싼 원문이
    그 자리를 가리키고, 조치 동사가 다음 걸음을 준다.
    """
    where = f"{open_field.entry_ordinal}번째 필드"
    if open_field.text_preview:
        where += f" '{open_field.text_preview}'"
    return (
        f"{entry}: {where}에 이름이 없습니다. "
        "한글에서 그 누름틀에 이름을 지정하거나 필드를 지우세요."
    )


def _consume_observation(
    cursor: Iterator[_ObservationT],
    pair: BoundaryPairRef,
    label: str,
    entry: str,
) -> _ObservationT:
    observation = next(cursor, None)
    if observation is None or getattr(observation, "pair", None) is not pair:
        raise TemplateInspectionContractError(f"{entry}: {label} observation order mismatch")
    return observation


def _product_observation_consistent(
    item: ProductScopeObservation,
    *,
    diagnostics_present: bool,
) -> bool:
    if item.scope_role is ProductScopeRole.INVALID_PRODUCT:
        return (
            not item.scope_usable
            and diagnostics_present
            and (
                (
                    item.classification is ProductClassification.KNOWN_PRODUCT
                    and item.kind in PRODUCT_KINDS
                )
                or (
                    item.classification is not ProductClassification.KNOWN_PRODUCT
                    and item.kind is None
                    and item.product_id is None
                )
            )
            and (
                item.owning_slot_pair is None
                or (
                    item.classification is ProductClassification.KNOWN_PRODUCT
                    and item.kind == "slot_option"
                )
            )
        )
    if item.scope_role is ProductScopeRole.NONE:
        return (
            item.scope_usable
            and item.classification is ProductClassification.NON_PRODUCT
            and item.kind is None
            and item.product_id is None
            and item.owning_slot_pair is None
        )
    expected = {
        ProductScopeRole.SLOT: ("slot", False),
        ProductScopeRole.OPTION: ("slot_option", True),
    }.get(item.scope_role)
    return (
        item.scope_usable
        and item.classification is ProductClassification.KNOWN_PRODUCT
        and expected is not None
        and item.kind == expected[0]
        and (item.owning_slot_pair is not None) is expected[1]
        and (item.product_id is not None or diagnostics_present)
    )


def _current_owner(
    *,
    bookmark_topology_usable: bool,
    invalid_product_depth: int,
    current_slot_pair: BoundaryPairRef | None,
    current_option_pair: BoundaryPairRef | None,
) -> _FieldOwner:
    if not bookmark_topology_usable or invalid_product_depth:
        return (_FieldOwnerTag.UNRESOLVED, None)
    if current_option_pair is not None:
        return (_FieldOwnerTag.OPTION, current_option_pair)
    if current_slot_pair is not None:
        return (_FieldOwnerTag.SLOT_SHARED, current_slot_pair)
    return (_FieldOwnerTag.ROOT, None)


def _field_structural_diagnostics(
    scan: StructuralBoundaryScan,
) -> list[TemplateDiagnostic]:
    return [
        TemplateDiagnostic(item.kind.value, f"{item.entry}: {item.kind.value}")
        for item in scan.diagnostics
        if item.kind.name.startswith("FIELD_")
    ]


def _inspect_hwpx_detail(pkg: object) -> _HwpxInspectionDetail:
    package = require_package(pkg)
    scan = scan_structural_boundaries(package)
    return _HwpxInspectionDetail(
        scan,
        inspect_product_bookmarks(scan),
        inspect_native_capabilities(package, scan),
    )


# ─── #773 composition fact 유도 — 관찰된 blocker 의 부재가 근거다 ────────────────────────
# 각 fact 는 **서로 다른** blocker 집합에서 나온다.
#
# 정직하게 적어 둔다: **현재 PASS 경로에서 이 값들은 전부 True 다.** product region 에 removal
# blocker 가 하나라도 있으면 바로 아래에서 `product-selection-not-removable` 진단이 되고, fill
# blocker 는 `field-not-fillable` 진단이 되며, 진단이 하나라도 있으면 structure 없이 FAIL 로 닫힌다
# — 그래서 여기까지 오면 두 목록은 비어 있다. 즉 이 fact 들은 지금 **판별력이 없다**(“qualification
# 이 PASS 였다” 의 일곱 가지 재진술이다). product bookmark 가 없는 content entry 의 envelope fact 는
# 관찰 0 건에서 나오므로 공허하게 참이다(그 entry 에선 아무것도 제거하지 않으니 무해하다).
#
# 그럼에도 상수 True 를 쓰지 않는 이유는 둘이다. (1) 값이 관찰에서 나와야 “blocker 면 FAIL” 규칙이
# 나중에 완화될 때 projection 이 따라 움직인다. (2) fact 마다 근거 집합이 달라서, 어떤 blocker 가
# 어떤 fact 를 무너뜨리는지가 코드에 남는다. 판별력 있는 검사가 필요해지는 시점은 S6 가 이 fact 를
# 실제로 소비할 때이고, 그 판정은 이 슬라이스 소유가 아니다.
_ENVELOPE_FACT_BLOCKERS: dict[str, frozenset[BookmarkRemovalBlockerKind]] = {
    "retains_admissible_envelope": frozenset(
        {
            BookmarkRemovalBlockerKind.UNSUPPORTED_ENTRY,
            BookmarkRemovalBlockerKind.WHOLE_SECTION,
            BookmarkRemovalBlockerKind.SECTION_DEFINITION,
        }
    ),
    "handles_empty_edges": frozenset(
        {
            BookmarkRemovalBlockerKind.PARTIAL_PARAGRAPH_BEGIN,
            BookmarkRemovalBlockerKind.PARTIAL_PARAGRAPH_END,
            BookmarkRemovalBlockerKind.NON_PARAGRAPH_EXTENT,
        }
    ),
    "preserves_owner_marker": frozenset(
        {
            BookmarkRemovalBlockerKind.COLLATERAL_BOOKMARK,
            BookmarkRemovalBlockerKind.FIELD_ENCLOSES_TARGET,
        }
    ),
    "coincident_boundary_admissible": frozenset(
        {
            BookmarkRemovalBlockerKind.UNSUPPORTED_BOUNDARY,
            BookmarkRemovalBlockerKind.PROTECTED_RANGE_CROSSING,
            BookmarkRemovalBlockerKind.UNPAIRED_PROTECTED_RANGE,
            BookmarkRemovalBlockerKind.BOOKMARK_TOPOLOGY_UNUSABLE,
            BookmarkRemovalBlockerKind.BOOKMARK_METADATA_UNUSABLE,
        }
    ),
}

_REMOVAL_RESOLVER_FACT_BLOCKERS: dict[str, frozenset[BookmarkRemovalBlockerKind]] = {
    "remaining_target_resolvable_after_removal": frozenset(
        {
            BookmarkRemovalBlockerKind.FIELD_INTERSECTION,
            BookmarkRemovalBlockerKind.COLLATERAL_BOOKMARK,
        }
    ),
    "active_field_resolvable_after_removal": frozenset(
        {
            BookmarkRemovalBlockerKind.FIELD_INTERSECTION,
            BookmarkRemovalBlockerKind.FIELD_ENCLOSES_TARGET,
            BookmarkRemovalBlockerKind.FIELD_PAIRING_UNUSABLE,
        }
    ),
}

_FIELD_WRITE_IDENTITY_BLOCKERS = frozenset(
    {
        FieldFillBlockerKind.FIELD_PAIRING_UNUSABLE,
        FieldFillBlockerKind.UNSUPPORTED_INLINE_OBJECT,
        FieldFillBlockerKind.PROTECTED_RANGE_CROSSING,
        FieldFillBlockerKind.UNPAIRED_PROTECTED_RANGE,
    }
)

#: 이 adapter 가 쓰는 native value target class — adapter contract version 과 함께 올린다.
_NATIVE_VALUE_TARGET_CLASS = "hwpx-field-value/v1"

#: publication 은 admission 이 아니다(#699) — 이 projection 은 admission 을 주장하지 않는다.
_ADMITTED_RELATION_PROFILE = "unadmitted"

_OWNER_KIND_BY_TAG = {
    _FieldOwnerTag.ROOT: OWNER_ROOT,
    _FieldOwnerTag.SLOT_SHARED: OWNER_SLOT_SHARED,
    _FieldOwnerTag.OPTION: OWNER_OPTION,
}


def _envelope_class(kind: ContentEntryKind) -> str:
    return f"{kind.value}-body/v1"


def _facts_from_absent_blockers(
    groups: "dict[str, frozenset[_BlockerT]]", observed: "Iterable[_BlockerT]"
) -> dict[str, bool]:
    """관찰된 blocker 집합에서 fact 를 유도한다 — 해당 근거가 없으면 True.

    ``_BlockerT`` 로 묶어 둔 이유: 두 blocker 어휘는 모두 ``StrEnum`` 이라 값이 같으면 서로
    **동등하고 해시도 같다**(`FIELD_PAIRING_UNUSABLE` 가 양쪽에 있다). ``Any`` 로 두면 fill
    blocker 를 removal group 에 먹여도 타입검사와 집합연산이 둘 다 조용히 통과한다.
    """
    seen = set(observed)
    return {name: not (seen & blockers) for name, blockers in groups.items()}


def _analyze_hwpx_detail(detail: _HwpxInspectionDetail) -> QualificationInspection:
    scan, products, capabilities = (
        detail.structural,
        detail.products,
        detail.capabilities,
    )
    if any(
        not _product_observation_consistent(
            item, diagnostics_present=bool(products.diagnostics)
        )
        for item in products.observations
    ):
        raise TemplateInspectionContractError("product scope observation conflicts")
    field_fill_cursor = iter(capabilities.field_fills)
    bookmark_removal_cursor = iter(capabilities.bookmark_removals)
    product_cursor = iter(products.observations)
    slot_observations: list[ProductScopeObservation] = []
    option_observations: dict[BoundaryPairRef, list[ProductScopeObservation]] = {}
    shared_fields: dict[BoundaryPairRef, list[str]] = {}
    option_fields: dict[BoundaryPairRef, list[str]] = {}

    # ── #773 composition observation 수집기 ──────────────────────────────────────────
    # 문서 순서 counter 하나가 모든 event 를 훑는다 — begin/end 가 서로 다른 event 라 어떤
    # region 도 begin < end 를 만족하고(단일 paragraph Option 포함), order 는 전역 유일하다.
    # paragraph index 를 쓰지 않는 이유가 이것이다(inclusive 라 단일 paragraph 는 begin==end).
    order_counter = 0
    occurrence_rows: list[tuple[str, _FieldOwner, str, int]] = []
    slot_span_rows: dict[BoundaryPairRef, tuple[int, int, str]] = {}
    option_span_rows: dict[BoundaryPairRef, tuple[int, int, str]] = {}
    entry_kinds: dict[str, ContentEntryKind] = {}
    entry_removal_blockers: dict[str, list[BookmarkRemovalBlockerKind]] = {}
    fill_blocker_kinds: list[FieldFillBlockerKind] = []
    removal_blocker_kinds: list[BookmarkRemovalBlockerKind] = []

    diagnostics = list(products.diagnostics)
    diagnostics.extend(_field_structural_diagnostics(scan))
    root_fields: list[str] = []

    for entry in scan.entries:
        current_slot_pair: BoundaryPairRef | None = None
        current_option_pair: BoundaryPairRef | None = None
        invalid_product_depth = 0
        open_field: _OpenField | None = None
        entry_field_ordinal = 0

        entry_kinds[entry.entry] = entry.kind
        entry_removal_blockers.setdefault(entry.entry, [])

        for event in entry.events:
            order_counter += 1
            structural_order = order_counter
            if isinstance(event, FieldBegin):
                # 관측 cursor 는 kernel occurrence 순서와 자리를 맞춰 전진한다 — 누름틀이
                # 아닌 Field 라도 **반드시** 소비한다(건너뛰면 이후 전부 어긋난다).
                fill = _consume_observation(
                    field_fill_cursor, event.pair, "Field fill", entry.entry
                )
                fill_target = is_fill_target_field_type(event.field_type)
                if fill_target:
                    # 자동 필드의 기입 장애는 이 판정에 들지 않는다 — 채우지 않을 자리라
                    # 세면 `field_write_preserves_identity` 가 근거 없이 내려간다(#931).
                    fill_blocker_kinds.extend(blocker.kind for blocker in fill.blockers)
                if open_field is not None:
                    raise TemplateInspectionContractError(
                        f"{entry.entry}: Field began while another Field was open"
                    )
                entry_field_ordinal += 1
                open_field = _OpenField(
                    event.pair,
                    event.raw_name,
                    normalize_field_id(event.raw_name),
                    _current_owner(
                        bookmark_topology_usable=entry.bookmark_topology_usable,
                        invalid_product_depth=invalid_product_depth,
                        current_slot_pair=current_slot_pair,
                        current_option_pair=current_option_pair,
                    ),
                    fill,
                    structural_order,
                    fill_target=fill_target,
                    entry_ordinal=entry_field_ordinal,
                    text_preview=event.text_preview,
                )
                continue

            if isinstance(event, FieldEnd):
                if open_field is None or open_field.pair is not event.pair:
                    raise TemplateInspectionContractError(
                        f"{entry.entry}: Field end contradicts open Field"
                    )
                current_owner = _current_owner(
                    bookmark_topology_usable=entry.bookmark_topology_usable,
                    invalid_product_depth=invalid_product_depth,
                    current_slot_pair=current_slot_pair,
                    current_option_pair=current_option_pair,
                )
                field_label = repr(
                    open_field.field_id if open_field.field_id is not None else open_field.raw_name
                )
                if (
                    open_field.owner[0] is _FieldOwnerTag.UNRESOLVED
                    or current_owner[0] is _FieldOwnerTag.UNRESOLVED
                ):
                    diagnostics.append(
                        TemplateDiagnostic(
                            "unresolved-field-owner",
                            f"{entry.entry}: Field {field_label} owner is unresolved",
                        )
                    )
                elif open_field.owner != current_owner:
                    diagnostics.append(
                        TemplateDiagnostic(
                            "field-crosses-selection-boundary",
                            f"{entry.entry}: Field {field_label} crosses a selection boundary",
                        )
                    )
                elif open_field.product_boundary_opened:
                    diagnostics.append(
                        TemplateDiagnostic(
                            "field-contains-selection-boundary",
                            f"{entry.entry}: Field {field_label} contains a selection boundary",
                        )
                    )
                elif not open_field.fill_target:
                    # 한글이 자동으로 낳은 필드(하이퍼링크 등)다 — 이름이 없어도 정상이고
                    # 채울 자리도 아니라 필드 집합·occurrence 어디에도 들지 않는다(#931).
                    # 위의 구조 진단(소유자·경계 교차)은 그대로 받는다: 자동 필드의 짝도
                    # 구간 제거가 자를 수 있는 실체라 침묵시키면 조용히 틀린다.
                    pass
                elif open_field.field_id is None:
                    diagnostics.append(
                        TemplateDiagnostic(
                            "invalid-field-id",
                            _unnamed_field_message(entry.entry, open_field),
                        )
                    )
                elif not open_field.fill.fillable:
                    diagnostics.append(
                        TemplateDiagnostic(
                            "field-not-fillable",
                            f"{entry.entry}: Field {field_label}: "
                            f"{_blocker_summary(open_field.fill.blockers)}",
                        )
                    )
                else:
                    owner_tag, owner_pair = open_field.owner
                    if owner_tag is _FieldOwnerTag.ROOT:
                        root_fields.append(open_field.field_id)
                    elif owner_tag is _FieldOwnerTag.SLOT_SHARED:
                        shared_fields[cast(BoundaryPairRef, owner_pair)].append(
                            open_field.field_id
                        )
                    else:
                        option_fields[cast(BoundaryPairRef, owner_pair)].append(
                            open_field.field_id
                        )
                    # 제품 구조에 실린 Field 만 occurrence 를 갖는다 — 진단으로 거절된 Field 는
                    # 애초에 PASS 가 아니므로 여기 오지 않는다.
                    occurrence_rows.append(
                        (
                            open_field.field_id,
                            open_field.owner,
                            entry.entry,
                            open_field.structural_order,
                        )
                    )
                open_field = None
                continue

            if isinstance(event, BookmarkBegin):
                observation = _consume_observation(
                    product_cursor, event.pair, "product scope", entry.entry
                )
                removal = _consume_observation(
                    bookmark_removal_cursor,
                    event.pair,
                    "BOOKMARK removal",
                    entry.entry,
                )
                if observation.entry != entry.entry:
                    raise TemplateInspectionContractError("product scope entry mismatch")
                role = observation.scope_role

                if (
                    observation.classification is ProductClassification.KNOWN_PRODUCT
                    and observation.kind in PRODUCT_KINDS
                ):
                    # envelope·resolver capability fact 의 **관찰 근거**(#773). 아래 진단과 같은
                    # 관찰을 보므로 한 조건 아래 둔다 — 둘이 갈리면 fact 와 진단이 서로 다른
                    # 표본을 보게 된다.
                    kinds = [blocker.kind for blocker in removal.blockers]
                    entry_removal_blockers[entry.entry].extend(kinds)
                    removal_blocker_kinds.extend(kinds)
                    if not removal.removable:
                        diagnostics.append(
                            TemplateDiagnostic(
                                "product-selection-not-removable",
                                f"{entry.entry}: {observation.kind} "
                                f"{observation.product_id!r}: "
                                f"{_blocker_summary(removal.blockers)}",
                            )
                        )
                if not entry.bookmark_topology_usable:
                    continue
                if open_field is not None and role is not ProductScopeRole.NONE:
                    open_field.product_boundary_opened = True
                if invalid_product_depth and role is not ProductScopeRole.INVALID_PRODUCT:
                    raise TemplateInspectionContractError(
                        f"{entry.entry}: usable product scope inside invalid scope"
                    )
                if role is ProductScopeRole.NONE:
                    continue
                if role is ProductScopeRole.INVALID_PRODUCT:
                    if (
                        observation.owning_slot_pair is not None
                        and observation.owning_slot_pair is not current_slot_pair
                    ):
                        raise TemplateInspectionContractError(
                            f"{entry.entry}: invalid product owning Slot "
                            "contradicts current Slot"
                        )
                    invalid_product_depth += 1
                    continue
                if role is ProductScopeRole.SLOT:
                    if current_slot_pair is not None or current_option_pair is not None:
                        raise TemplateInspectionContractError(
                            f"{entry.entry}: Slot begin contradicts current scope"
                        )
                    current_slot_pair = event.pair
                    slot_observations.append(observation)
                    shared_fields[event.pair] = []
                    slot_span_rows[event.pair] = (structural_order, -1, entry.entry)
                    continue
                if (
                    current_slot_pair is not observation.owning_slot_pair
                    or current_option_pair is not None
                ):
                    raise TemplateInspectionContractError(
                        f"{entry.entry}: Option owning Slot contradicts current Slot"
                    )
                current_option_pair = event.pair
                owner = cast(BoundaryPairRef, observation.owning_slot_pair)
                option_observations.setdefault(owner, []).append(observation)
                option_fields[event.pair] = []
                option_span_rows[event.pair] = (structural_order, -1, entry.entry)
                continue

            if not entry.bookmark_topology_usable:
                continue
            if invalid_product_depth:
                invalid_product_depth -= 1
                continue
            if current_option_pair is event.pair:
                begin, _, owner_entry = option_span_rows[event.pair]
                option_span_rows[event.pair] = (begin, structural_order, owner_entry)
                current_option_pair = None
                continue
            if current_slot_pair is event.pair:
                if current_option_pair is not None:
                    raise TemplateInspectionContractError(
                        f"{entry.entry}: Slot end contradicts current scope"
                    )
                begin, _, owner_entry = slot_span_rows[event.pair]
                slot_span_rows[event.pair] = (begin, structural_order, owner_entry)
                current_slot_pair = None

        if (
            open_field is not None
            or current_slot_pair is not None
            or current_option_pair is not None
            or invalid_product_depth
        ):
            raise TemplateInspectionContractError(
                f"{entry.entry}: analyzer ended with impossible state"
            )

    for label, cursor in (
        ("Field fill", field_fill_cursor),
        ("BOOKMARK removal", bookmark_removal_cursor),
        ("product scope", product_cursor),
    ):
        if next(cursor, None) is not None:
            raise TemplateInspectionContractError(f"extra {label} observation")

    if diagnostics:
        return QualificationInspection(None, tuple(diagnostics))

    slots: list[TemplateSlot] = []
    for slot in slot_observations:
        options: list[TemplateOption] = []
        for option in option_observations.get(slot.pair, ()):
            options.append(
                TemplateOption(
                    cast(str, option.product_id),
                    tuple(option_fields[option.pair]),
                    label=option.product_label,
                )
            )
        slots.append(
            TemplateSlot(
                cast(str, slot.product_id),
                tuple(shared_fields[slot.pair]),
                tuple(options),
                label=slot.product_label,
            )
        )
    structure = TemplateStructure(tuple(root_fields), tuple(slots))
    execution_structure = _build_execution_structure(
        structure=structure,
        slot_observations=slot_observations,
        option_observations=option_observations,
        occurrence_rows=occurrence_rows,
        slot_span_rows=slot_span_rows,
        option_span_rows=option_span_rows,
        entry_kinds=entry_kinds,
        entry_removal_blockers=entry_removal_blockers,
        removal_blocker_kinds=removal_blocker_kinds,
        fill_blocker_kinds=fill_blocker_kinds,
    )
    return QualificationInspection(structure, (), execution_structure)


def _build_execution_structure(
    *,
    structure: TemplateStructure,
    slot_observations: list[ProductScopeObservation],
    option_observations: dict[BoundaryPairRef, list[ProductScopeObservation]],
    occurrence_rows: list[tuple[str, _FieldOwner, str, int]],
    slot_span_rows: dict[BoundaryPairRef, tuple[int, int, str]],
    option_span_rows: dict[BoundaryPairRef, tuple[int, int, str]],
    entry_kinds: dict[str, ContentEntryKind],
    entry_removal_blockers: dict[str, list[BookmarkRemovalBlockerKind]],
    removal_blocker_kinds: list[BookmarkRemovalBlockerKind],
    fill_blocker_kinds: list[FieldFillBlockerKind],
) -> ExecutionTemplateStructure:
    """PASS inspection 한 번의 관찰값에서 label-bearing composition projection(v4)을 조립한다.

    HWPX 를 다시 열지 않는다 — 위 event pass 가 이미 본 것만 쓴다. 같은 bytes 는 같은 order·
    같은 payload 를 낸다(결정적). fact 누락·모순은 :func:`build_execution_structure` 가 typed
    오류로 닫는다 — 여기서 추측 기본값을 채우지 않는다.
    """
    slot_id_by_pair = {obs.pair: cast(str, obs.product_id) for obs in slot_observations}
    option_ref_by_pair: dict[BoundaryPairRef, tuple[str, str]] = {
        obs.pair: (slot_id_by_pair[owner_pair], cast(str, obs.product_id))
        for owner_pair, observations in option_observations.items()
        for obs in observations
    }

    slot_regions = tuple(
        SlotRegionObservation(
            slot_id=slot_id_by_pair[pair],
            content_entry_id=entry_id,
            begin_order=begin,
            end_order=end,
        )
        for pair, (begin, end, entry_id) in sorted(
            slot_span_rows.items(), key=lambda item: item[1][0]
        )
    )
    option_regions = tuple(
        OptionRegionObservation(
            slot_id=option_ref_by_pair[pair][0],
            option_id=option_ref_by_pair[pair][1],
            content_entry_id=entry_id,
            begin_order=begin,
            end_order=end,
            removal_capability_ref=NATIVE_PRIMITIVE_CONTRACT_V1.option_removal_contract_id,
        )
        for pair, (begin, end, entry_id) in sorted(
            option_span_rows.items(), key=lambda item: item[1][0]
        )
    )

    # occurrence ordinal 은 같은 field_id 안에서 문서 순서대로 0..n-1 이다.
    ordinal_seen: dict[str, int] = {}
    occurrences: list[FieldOccurrence] = []
    for field_id, owner, entry_id, order in sorted(
        occurrence_rows, key=lambda row: row[3]
    ):
        owner_tag, owner_pair = owner
        slot_ref: str | None = None
        option_ref: str | None = None
        if owner_tag is _FieldOwnerTag.SLOT_SHARED:
            slot_ref = slot_id_by_pair[cast(BoundaryPairRef, owner_pair)]
        elif owner_tag is _FieldOwnerTag.OPTION:
            slot_ref, option_ref = option_ref_by_pair[cast(BoundaryPairRef, owner_pair)]
        ordinal = ordinal_seen.get(field_id, 0)
        ordinal_seen[field_id] = ordinal + 1
        occurrences.append(
            FieldOccurrence(
                field_id=field_id,
                occurrence_ordinal=ordinal,
                owner_kind=_OWNER_KIND_BY_TAG[owner_tag],
                owner_slot_id=slot_ref,
                owner_option_id=option_ref,
                content_entry_id=entry_id,
                structural_order=order,
                native_value_target_class=_NATIVE_VALUE_TARGET_CLASS,
                resolver_contract_id=(
                    NATIVE_PRIMITIVE_CONTRACT_V1.field_resolver_contract_id
                ),
            )
        )

    referenced_entries = (
        {occ.content_entry_id for occ in occurrences}
        | {region.content_entry_id for region in slot_regions}
        | {region.content_entry_id for region in option_regions}
    )
    content_entries = tuple(
        ContentEntry(
            content_entry_id=entry_id,
            envelope_class=_envelope_class(entry_kinds[entry_id]),
            envelope_capability_facts=_facts_from_absent_blockers(
                _ENVELOPE_FACT_BLOCKERS, entry_removal_blockers.get(entry_id, ())
            ),
        )
        for entry_id in sorted(referenced_entries)
    )

    resolver_facts = _facts_from_absent_blockers(
        _REMOVAL_RESOLVER_FACT_BLOCKERS, removal_blocker_kinds
    )
    resolver_facts["field_write_preserves_identity"] = not (
        set(fill_blocker_kinds) & _FIELD_WRITE_IDENTITY_BLOCKERS
    )

    return build_execution_structure(
        product_structure=structure,
        occurrences=tuple(occurrences),
        slot_regions=slot_regions,
        option_regions=option_regions,
        content_entries=content_entries,
        resolver_stability_facts=resolver_facts,
        admitted_relation_profile=_ADMITTED_RELATION_PROFILE,
        projection_schema_version=LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
    )


def inspect_hwpx_qualification(canonical_bytes: bytes) -> QualificationInspection:
    """Inspect immutable canonical HWPX bytes without exposing native objects."""
    if not isinstance(canonical_bytes, bytes):
        raise TypeError("canonical_bytes must be bytes")
    try:
        package = HwpxPackage.from_bytes(canonical_bytes)
    except (ValueError, zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        if (
            isinstance(exc, RuntimeError)
            and not isinstance(exc, NotImplementedError)
            and not str(exc).endswith(" is encrypted, password required for extraction")
        ):
            raise
        return QualificationInspection(
            None,
            (TemplateDiagnostic("invalid-hwpx-package", str(exc)),),
        )
    return _analyze_hwpx_detail(_inspect_hwpx_detail(package))


# Bump this identity whenever the HWPX qualification rule set or projection changes.
# v4(#773): 같은 read-only inspection 이 canonical label 과 composition-ready execution fact 를
# 함께 낸다. v3 는 label 만, v2 는 composition fact 만 실을 수 있어 둘 중 어느 것도 shipping
# Qualification 이 S4·S5 를 동시에 먹일 수 없었다.
