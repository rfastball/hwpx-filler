"""HWPX 템플릿 판독·컴파일 파일 효과의 외부 어댑터.

파서 의미론 층(schema·authoring·template_status·lint·fields)은 **열린 package 전용**이다
(P2-19R, #576). 경로를 받아 package adapter로 한 번 열고 Domain 순수
함수를 부르는 path 진입 함수들이 여기 산다 — ring 2/Host 는 직접 부르고, Application VM
(gui)은 External 을 import 할 수 없어 ring 2 가 이 함수들을 포트로 결속해 주입한다
(P2-12 ``inspect_hwpx_template`` 동형).
"""

from __future__ import annotations

import json
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, NamedTuple, TypeVar, cast

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
    BookmarkRemovalBlocker,
    BookmarkRemovalBlockerKind,
    FieldFillBlocker,
    FieldFillBlockerKind,
    FieldFillObservation,
    NativeCapabilityInspection,
    inspect_native_capabilities,
)
from hwpxcore.package import HwpxPackage
from hwpxcore.structural_boundary import (
    BookmarkBegin,
    BookmarkEnd,
    BoundaryPairRef,
    ContentEntryKind,
    FieldBegin,
    FieldEnd,
    StructuralBoundaryScan,
    StructuralDiagnosticKind,
    scan_structural_boundaries,
)
from hwpxcore.text_extract import PackageLike, require_package, section_xml_names

from ..application.execution_composition import NATIVE_PRIMITIVE_CONTRACT_V1
from ..application.execution_structure import (
    LABELED_EXECUTION_QUALIFICATION_PROFILE_ID,
    LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
    OWNER_OPTION,
    OWNER_ROOT,
    OWNER_SLOT_SHARED,
    ContentEntry,
    ExecutionTemplateStructure,
    FieldOccurrence,
    OptionRegionObservation,
    SlotRegionObservation,
    build_execution_structure,
)
from ..application.qualification_evidence import (
    QualificationProfileManifest,
    build_manifest,
)
from ..application.template_qualification import (
    QualificationProfile,
    QualificationInspection,
    TemplateDiagnostic,
    TemplateInspectionContractError,
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from ..domain.authoring import (
    PLACEMENT_OPTION,
    PLACEMENT_SLOT,
    CompileReport,
    StructureScan,
    TokenSite,
    begin_marker_text,
    compile_document,
    end_marker_text,
    insert_marker_paragraphs,
    scan_structure,
    scan_tokens,
)
from ..domain.fields import fill_precheck, normalize_field_id, read_fields
from ..domain.lint import LintReport, SchemaDrift, diff_schema, lint_template
from ..domain.schema import extract_schema
from ..domain.slot import Slot, SlotOption
from ..domain.template_status import TemplateStatus, compile_status
from ..gui.template_manager_state import (
    TemplateFileOps,
    TemplateInspection,
)
from .hwpx_package_io import read_hwpx_package, write_hwpx_package

_PRODUCT_KINDS = frozenset({"slot", "slot_option"})
_NATIVE_NAME = "#hf"


class ProductClassification(StrEnum):
    NON_PRODUCT = "non_product"
    KNOWN_PRODUCT = "known_product"
    INVALID_PRODUCT = "invalid_product"


class ProductScopeRole(StrEnum):
    NONE = "none"
    SLOT = "slot"
    OPTION = "option"
    INVALID_PRODUCT = "invalid_product"


class ProductInspectionContractError(RuntimeError):
    """The supplied structural scan violates its advertised pair contract."""


@dataclass(frozen=True)
class ProductScopeObservation:
    pair: BoundaryPairRef
    entry: str
    classification: ProductClassification
    scope_role: ProductScopeRole
    scope_usable: bool
    kind: str | None
    product_id: str | None
    owning_slot_pair: BoundaryPairRef | None
    product_label: str | None = None


@dataclass(frozen=True)
class ProductBookmarkInspection:
    observations: tuple[ProductScopeObservation, ...]
    diagnostics: tuple[TemplateDiagnostic, ...]
    _projection_pairs: frozenset[BoundaryPairRef] = field(
        default_factory=frozenset, repr=False, compare=False
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


class _ParsedProduct(NamedTuple):
    classification: ProductClassification
    kind: str | None = None
    product_id: str | None = None
    label: str | None = None


class _OpenBookmark(NamedTuple):
    pair: BoundaryPairRef
    kind: str | None
    scope_usable: bool


class _SlotSnapshot(NamedTuple):
    slots: tuple[Slot, ...]
    diagnostics: tuple[TemplateDiagnostic, ...]
    slot_regions: dict[str, BookmarkRegion]
    option_regions: dict[tuple[str, str], BookmarkRegion]


def _diagnostic(
    kind: str, entry: str, bookmark_name: str | None, detail: str
) -> TemplateDiagnostic:
    return TemplateDiagnostic(kind, f"{entry}: BOOKMARK {bookmark_name!r}: {detail}")


def _serialize_product_metatag(
    kind: str, identifier: str, label: str | None = None
) -> str:
    product = {"kind": kind, "id": identifier}
    if label is not None:
        product["label"] = _require_text(label, f"{kind} label")
    return json.dumps(
        {"hwpxFiller": product, "name": _NATIVE_NAME},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def serialize_slot_metatag(slot: Slot) -> str:
    """Serialize one canonical object-local Slot payload; native ``name`` is last."""
    _require_text(slot.id, "Slot id")
    return _serialize_product_metatag("slot", slot.id, slot.label)


def serialize_slot_option_metatag(option: SlotOption) -> str:
    """Serialize one canonical object-local Slot Option payload."""
    _require_text(option.id, "Slot Option id")
    return _serialize_product_metatag("slot_option", option.id, option.label)


def _product_tag(
    entry: str,
    begin: BookmarkBegin,
    diagnostics: list[TemplateDiagnostic],
) -> _ParsedProduct:
    parsed: list[dict[str, object]] = []
    malformed = False
    product_signal = False
    for raw in begin.meta_tags:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            diagnostics.append(
                _diagnostic("malformed-json", entry, begin.bookmark_name, "invalid MetaTag JSON")
            )
            malformed = True
            continue
        if not isinstance(value, dict):
            continue
        if "hwpxFiller" not in value:
            if value.get("name") == _NATIVE_NAME:
                product_signal = True
                diagnostics.append(
                    _diagnostic(
                        "invalid-product-payload",
                        entry,
                        begin.bookmark_name,
                        "canonical product MetaTag has no hwpxFiller object",
                    )
                )
            continue
        product_signal = True
        parsed.append(value)

    attribute_product: dict[str, object] | None = None
    if begin.meta_tag_attribute:
        try:
            attribute = json.loads(begin.meta_tag_attribute)
        except (json.JSONDecodeError, TypeError):
            diagnostics.append(
                _diagnostic(
                    "malformed-json",
                    entry,
                    begin.bookmark_name,
                    "invalid fieldBegin@metaTag JSON",
                )
            )
            malformed = True
            attribute = None
        if isinstance(attribute, dict) and (
            "hwpxFiller" in attribute or attribute.get("name") == _NATIVE_NAME
        ):
            product_signal = True
            diagnostics.append(
                _diagnostic(
                    "unsupported-carrier",
                    entry,
                    begin.bookmark_name,
                    "product metadata cannot use fieldBegin@metaTag",
                )
            )
        if (
            isinstance(attribute, dict)
            and attribute.get("name") == _NATIVE_NAME
            and "hwpxFiller" not in attribute
        ):
            diagnostics.append(
                _diagnostic(
                    "invalid-product-payload",
                    entry,
                    begin.bookmark_name,
                    "fieldBegin@metaTag has no hwpxFiller object",
                )
            )
        if isinstance(attribute, dict) and "hwpxFiller" in attribute:
            attribute_product = attribute

    if len(parsed) > 1:
        diagnostics.append(
            _diagnostic(
                "conflicting-product-metatag",
                entry,
                begin.bookmark_name,
                "multiple product MetaTags",
            )
        )
        return _ParsedProduct(ProductClassification.INVALID_PRODUCT)
    root = parsed[0] if parsed else attribute_product
    unsupported_carrier = not parsed and attribute_product is not None
    if root is None:
        return _ParsedProduct(
            ProductClassification.INVALID_PRODUCT
            if product_signal or malformed
            else ProductClassification.NON_PRODUCT
        )

    body = root.get("hwpxFiller")
    if not isinstance(body, dict):
        diagnostics.append(
            _diagnostic(
                "invalid-product-payload",
                entry,
                begin.bookmark_name,
                "hwpxFiller must be an object",
            )
        )
        return _ParsedProduct(ProductClassification.INVALID_PRODUCT)
    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in _PRODUCT_KINDS:
        diagnostics.append(
            _diagnostic("unknown-kind", entry, begin.bookmark_name, f"unknown kind {kind!r}")
        )
        return _ParsedProduct(ProductClassification.INVALID_PRODUCT)

    identifier = body.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        diagnostics.append(
            _diagnostic(
                "invalid-id",
                entry,
                begin.bookmark_name,
                "id must be a non-empty string",
            )
        )
        return _ParsedProduct(ProductClassification.KNOWN_PRODUCT, kind)
    label = body.get("label") if "label" in body else None
    if "label" in body and (not isinstance(label, str) or not label.strip()):
        diagnostics.append(
            _diagnostic(
                "invalid-label",
                entry,
                begin.bookmark_name,
                "label must be a non-empty string when present",
            )
        )
        label = None
    native_name = root.get("name")
    if native_name != _NATIVE_NAME:
        diagnostics.append(
            _diagnostic(
                "native-name-mismatch",
                entry,
                begin.bookmark_name,
                f"name must be {_NATIVE_NAME!r}, got {native_name!r}",
            )
        )

    return _ParsedProduct(
        ProductClassification.KNOWN_PRODUCT,
        kind,
        None if unsupported_carrier else identifier,
        None if unsupported_carrier else label,
    )


def _translate_structural_diagnostics(
    scan: StructuralBoundaryScan,
) -> list[TemplateDiagnostic]:
    diagnostics: list[TemplateDiagnostic] = []
    for item in scan.diagnostics:
        if item.kind.name.startswith("FIELD_"):
            continue
        kind = (
            "crossing-range"
            if item.kind is StructuralDiagnosticKind.BOOKMARK_CROSSING
            else "bookmark-resolve-failed"
        )
        location = item.entry or "package"
        detail = f": {item.detail}" if item.detail else ""
        diagnostics.append(TemplateDiagnostic(kind, f"{location}: {item.kind.value}{detail}"))
    return diagnostics


def _validate_pair_lifecycle(scan: StructuralBoundaryScan) -> None:
    opened: dict[BoundaryPairRef, tuple[str, bool]] = {}
    closed: set[BoundaryPairRef] = set()
    for entry in scan.entries:
        for event in entry.events:
            if isinstance(event, (FieldBegin, BookmarkBegin)):
                if event.pair in opened or event.pair in closed:
                    raise ProductInspectionContractError(
                        f"{entry.entry}: boundary pair reused"
                    )
                opened[event.pair] = (
                    entry.entry,
                    isinstance(event, BookmarkBegin),
                )
                continue
            if not isinstance(event, (FieldEnd, BookmarkEnd)):
                raise ProductInspectionContractError(
                    f"{entry.entry}: unsupported boundary event"
                )
            begin = opened.pop(event.pair, None)
            if begin != (entry.entry, isinstance(event, BookmarkEnd)):
                raise ProductInspectionContractError(
                    f"{entry.entry}: boundary pair end contradicts begin"
                )
            closed.add(event.pair)
    if opened:
        raise ProductInspectionContractError(
            "Structural boundary scan ended with open pairs"
        )


def inspect_product_bookmarks(
    scan: StructuralBoundaryScan,
) -> ProductBookmarkInspection:
    """Project product meaning from the exact supplied native boundary scan."""
    if not isinstance(scan, StructuralBoundaryScan):
        raise TypeError(f"scan must be StructuralBoundaryScan: {type(scan)!r}")

    _validate_pair_lifecycle(scan)
    diagnostics = _translate_structural_diagnostics(scan)
    structural_product_entries = {
        item.entry for item in scan.diagnostics if not item.kind.name.startswith("FIELD_")
    }
    unattributed_metatag_entries = {
        item.entry
        for item in scan.diagnostics
        if item.kind
        in {
            StructuralDiagnosticKind.NON_NATIVE_METATAG,
            StructuralDiagnosticKind.INVALID_METATAG_SHAPE,
        }
    }
    projection_pairs = frozenset(
        event.pair
        for entry in scan.entries
        if entry.kind is ContentEntryKind.SECTION
        and entry.bookmark_topology_usable
        and entry.entry not in unattributed_metatag_entries
        for event in entry.events
        if isinstance(event, BookmarkBegin)
    )
    for entry in scan.entries:
        if not entry.bookmark_topology_usable and entry.entry not in structural_product_entries:
            diagnostics.append(
                TemplateDiagnostic(
                    "bookmark-resolve-failed",
                    f"{entry.entry}: bookmark topology is unusable",
                )
            )
    observations: list[ProductScopeObservation] = []
    names: dict[BoundaryPairRef, str | None] = {}

    for entry in scan.entries:
        open_bookmarks: list[_OpenBookmark] = []
        for event in entry.events:
            if isinstance(event, BookmarkBegin):
                names[event.pair] = event.bookmark_name
                product = _product_tag(entry.entry, event, diagnostics)
                if not entry.bookmark_topology_usable:
                    observations.append(
                        ProductScopeObservation(
                            event.pair,
                            entry.entry,
                            product.classification,
                            ProductScopeRole.INVALID_PRODUCT,
                            False,
                            product.kind,
                            product.product_id,
                            None,
                            product.label,
                        )
                    )
                    continue
                if entry.entry in unattributed_metatag_entries:
                    observations.append(
                        ProductScopeObservation(
                            event.pair,
                            entry.entry,
                            product.classification,
                            ProductScopeRole.INVALID_PRODUCT,
                            False,
                            product.kind,
                            product.product_id,
                            None,
                            product.label,
                        )
                    )
                    open_bookmarks.append(_OpenBookmark(event.pair, None, False))
                    continue
                scope_blocked = any(not item.scope_usable for item in open_bookmarks)
                slot_ancestors = [item.pair for item in open_bookmarks if item.kind == "slot"]
                option_ancestors = [
                    item.pair for item in open_bookmarks if item.kind == "slot_option"
                ]
                owning_slot = (
                    slot_ancestors[0]
                    if not scope_blocked
                    and product.kind == "slot_option"
                    and len(slot_ancestors) == 1
                    else None
                )
                role = ProductScopeRole.NONE
                usable = True

                if product.classification is ProductClassification.INVALID_PRODUCT:
                    role = ProductScopeRole.INVALID_PRODUCT
                    usable = False
                elif product.classification is ProductClassification.KNOWN_PRODUCT:
                    if entry.kind is not ContentEntryKind.SECTION:
                        diagnostics.append(
                            _diagnostic(
                                "unsupported-product-entry",
                                entry.entry,
                                event.bookmark_name,
                                "product Slot/Option is supported only in section entries",
                            )
                        )
                        role = ProductScopeRole.INVALID_PRODUCT
                        usable = False
                    elif product.kind == "slot":
                        if slot_ancestors:
                            diagnostics.append(
                                _diagnostic(
                                    "nested-slot",
                                    entry.entry,
                                    event.bookmark_name,
                                    "Slot is inside another Slot",
                                )
                            )
                            role = ProductScopeRole.INVALID_PRODUCT
                            usable = False
                        else:
                            role = ProductScopeRole.SLOT
                    else:
                        if option_ancestors:
                            diagnostics.append(
                                _diagnostic(
                                    "nested-option",
                                    entry.entry,
                                    event.bookmark_name,
                                    "Option is inside another Option",
                                )
                            )
                            usable = False
                        if not slot_ancestors:
                            diagnostics.append(
                                _diagnostic(
                                    "orphan-option",
                                    entry.entry,
                                    event.bookmark_name,
                                    "Option has no product Slot ancestor",
                                )
                            )
                            usable = False
                        elif len(slot_ancestors) > 1:
                            diagnostics.append(
                                _diagnostic(
                                    "ambiguous-membership",
                                    entry.entry,
                                    event.bookmark_name,
                                    "Option has more than one product Slot ancestor",
                                )
                            )
                            usable = False
                        role = (
                            ProductScopeRole.OPTION if usable else ProductScopeRole.INVALID_PRODUCT
                        )

                if scope_blocked:
                    role = ProductScopeRole.INVALID_PRODUCT
                    usable = False
                    owning_slot = None

                observations.append(
                    ProductScopeObservation(
                        event.pair,
                        entry.entry,
                        product.classification,
                        role,
                        usable,
                        product.kind,
                        product.product_id,
                        owning_slot,
                        product.label,
                    )
                )
                open_bookmarks.append(_OpenBookmark(event.pair, product.kind, usable))
                continue

            if not isinstance(event, BookmarkEnd) or not entry.bookmark_topology_usable:
                continue
            if not open_bookmarks or open_bookmarks[-1].pair is not event.pair:
                raise ProductInspectionContractError(
                    f"{entry.entry}: BOOKMARK end contradicts usable topology"
                )
            open_bookmarks.pop()

    by_pair = {item.pair: item for item in observations}
    seen_slot_ids: set[str] = set()
    seen_option_ids: dict[BoundaryPairRef, set[str]] = {}
    for item in observations:
        if (
            item.classification is not ProductClassification.KNOWN_PRODUCT
            or item.product_id is None
            or item.pair not in projection_pairs
        ):
            continue
        if item.kind == "slot":
            if item.product_id in seen_slot_ids:
                diagnostics.append(
                    _diagnostic(
                        "duplicate-slot-id",
                        item.entry,
                        names[item.pair],
                        f"duplicate Slot id {item.product_id!r}",
                    )
                )
            seen_slot_ids.add(item.product_id)
        elif item.owning_slot_pair is not None:
            owner_ids = seen_option_ids.setdefault(item.owning_slot_pair, set())
            if item.product_id in owner_ids:
                owner = by_pair[item.owning_slot_pair]
                diagnostics.append(
                    _diagnostic(
                        "duplicate-option-id",
                        item.entry,
                        names[item.pair],
                        f"duplicate Option id {item.product_id!r} in Slot {owner.product_id!r}",
                    )
                )
            owner_ids.add(item.product_id)

    return ProductBookmarkInspection(
        tuple(observations),
        tuple(diagnostics),
        projection_pairs,
    )


def _blocker_summary(
    blockers: tuple[FieldFillBlocker | BookmarkRemovalBlocker, ...],
) -> str:
    return "; ".join(
        item.kind.value + (f": {', '.join(item.detail)}" if item.detail else "")
        for item in blockers
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
                    and item.kind in _PRODUCT_KINDS
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

        entry_kinds[entry.entry] = entry.kind
        entry_removal_blockers.setdefault(entry.entry, [])

        for event in entry.events:
            order_counter += 1
            structural_order = order_counter
            if isinstance(event, FieldBegin):
                fill = _consume_observation(
                    field_fill_cursor, event.pair, "Field fill", entry.entry
                )
                fill_blocker_kinds.extend(blocker.kind for blocker in fill.blockers)
                if open_field is not None:
                    raise TemplateInspectionContractError(
                        f"{entry.entry}: Field began while another Field was open"
                    )
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
                elif open_field.field_id is None:
                    diagnostics.append(
                        TemplateDiagnostic(
                            "invalid-field-id",
                            f"{entry.entry}: Field {field_label} has no valid ID",
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
                    and observation.kind in _PRODUCT_KINDS
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
HWPX_QUALIFICATION_PROFILE = QualificationProfile(
    LABELED_EXECUTION_QUALIFICATION_PROFILE_ID,
    inspect_hwpx_qualification,
)


def hwpx_qualification_manifest(created_at: str) -> "QualificationProfileManifest":
    """제품 HWPX profile 의 durable semantic manifest — profile identity 와 같은 곳에서 소유.

    S3-09 코디네이터가 최초 사용 시 qualification store 에 create-once 로 시딩한다. 버전
    문자열들은 profile id 처럼 **규칙이 바뀌면 함께 올린다** — manifest 는 immutable 이라
    같은 id 로 다른 의미를 다시 쓰는 경로가 없다.
    """
    return build_manifest(
        qualification_profile_id=HWPX_QUALIFICATION_PROFILE.id,
        media="hwpx",
        adapter_contract_version="hwpx-inspection-v4",
        product_rule_version="hwpx-qualification-rules-v4",
        # label·composition fact 는 operation 종류·피연산자·순서를 바꾸지 않는다.
        operation_alphabet_version="hwpx-operations-v1",
        projection_schema_version=LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        manifest_payload={},
        created_at=created_at,
    )


def _project_slots(inspection: ProductBookmarkInspection) -> tuple[Slot, ...]:
    options: dict[BoundaryPairRef, list[tuple[str, str | None]]] = {}
    for item in inspection.observations:
        if (
            item.classification is ProductClassification.KNOWN_PRODUCT
            and item.kind == "slot_option"
            and item.product_id is not None
            and item.owning_slot_pair is not None
            and item.pair in inspection._projection_pairs
        ):
            options.setdefault(item.owning_slot_pair, []).append(
                (item.product_id, item.product_label)
            )
    return tuple(
        Slot(
            item.product_id,
            tuple(
                SlotOption(identifier, order, label)
                for order, (identifier, label) in enumerate(options.get(item.pair, ()))
            ),
            item.product_label,
        )
        for item in inspection.observations
        if item.classification is ProductClassification.KNOWN_PRODUCT
        and item.kind == "slot"
        and item.product_id is not None
        and item.pair in inspection._projection_pairs
    )


def _inspect_slot_snapshot(pkg: object) -> _SlotSnapshot:
    package = require_package(pkg)
    scan = scan_structural_boundaries(package)
    inspection = inspect_product_bookmarks(scan)
    slots = _project_slots(inspection)
    if inspection.diagnostics:
        return _SlotSnapshot(slots, inspection.diagnostics, {}, {})

    section_begins = [
        (entry.entry, event)
        for entry in scan.entries
        if entry.kind is ContentEntryKind.SECTION
        for event in entry.events
        if isinstance(event, BookmarkBegin)
    ]
    try:
        regions = resolve_bookmark_topology(package)
    except ValueError as exc:
        return _SlotSnapshot(
            slots,
            (TemplateDiagnostic("bookmark-resolve-failed", str(exc)),),
            {},
            {},
        )
    try:
        aligned = list(zip(section_begins, regions, strict=True))
    except ValueError as exc:
        raise ProductInspectionContractError(
            "Structural scan and BOOKMARK mutation resolver disagree"
        ) from exc
    pair_regions: dict[BoundaryPairRef, BookmarkRegion] = {}
    for (entry, begin), region in aligned:
        if (
            entry != region.section
            or begin.bookmark_name != region.name
            or begin.meta_tags != region.meta_tags
            or begin.meta_tag_attribute != region.meta_tag_attribute
        ):
            raise ProductInspectionContractError(
                "Structural scan and BOOKMARK mutation resolver order disagree"
            )
        pair_regions[begin.pair] = region

    by_pair = {item.pair: item for item in inspection.observations}
    slot_regions: dict[str, BookmarkRegion] = {}
    option_regions: dict[tuple[str, str], BookmarkRegion] = {}
    for item in inspection.observations:
        if (
            item.classification is not ProductClassification.KNOWN_PRODUCT
            or item.product_id is None
            or item.scope_role is ProductScopeRole.INVALID_PRODUCT
        ):
            continue
        region = pair_regions.get(item.pair)
        if region is None:
            raise ProductInspectionContractError(
                f"Product pair in {item.entry!r} has no mutation handle"
            )
        if item.kind == "slot":
            slot_regions[item.product_id] = region
        elif item.owning_slot_pair is not None:
            owner = by_pair.get(item.owning_slot_pair)
            if owner is None or owner.product_id is None:
                raise ProductInspectionContractError(
                    "Option owning Slot pair is absent from product inspection"
                )
            option_regions[(owner.product_id, item.product_id)] = region
    return _SlotSnapshot(slots, (), slot_regions, option_regions)


def inspect_slots(pkg: object) -> tuple[tuple[Slot, ...], tuple[TemplateDiagnostic, ...]]:
    """Inspect one open package; diagnostics are blocking but do not hide valid Slots."""
    snapshot = _inspect_slot_snapshot(pkg)
    return snapshot.slots, snapshot.diagnostics


def _require_mutable_snapshot(pkg: object) -> tuple[object, _SlotSnapshot]:
    package = require_package(pkg)
    snapshot = _inspect_slot_snapshot(package)
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
    actual, diagnostics = inspect_slots(package)
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
    identifier = _require_text(slot_id, "Slot id")
    package, snapshot = _require_mutable_snapshot(pkg)
    region = snapshot.slot_regions.get(identifier)
    if region is None:
        raise ValueError(f"Slot {identifier!r} was not found")
    expected = tuple(slot for slot in snapshot.slots if slot.id != identifier)
    _remove_product_region(package, region, expected)


def remove_slot_option(pkg: object, slot_id: str, option_id: str) -> None:
    """Remove one canonical Slot Option selected by its Slot-local product id."""
    owner_id = _require_text(slot_id, "Slot id")
    target_id = _require_text(option_id, "Slot Option id")
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
    identifier = _require_text(slot_id, "Slot id")
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
    payload = serialize_slot_metatag(
        next(slot for slot in expected if slot.id == identifier)
    )
    _guarded_slot_mutation(
        package,
        lambda: replace_bookmark_metatag(package, region, index, payload),
        lambda: _require_slots(package, expected, "Slot rename"),
    )


def decompile_slot(pkg: object, slot_id: str) -> None:
    """컴파일된 Slot 하나를 **구간 표기로 되돌린다**(:func:`compile_structure` 의 역함수).

    ① 대상 Slot region 과 소속 Option region 의 **변이 전 좌표**를 뜬다.
    ② Option → Slot 순으로 ``unwrap_bookmark_region`` 으로 ctrl 쌍만 걷는다(문단
       무변형이라 ①의 좌표가 그대로 유효하다).
    ③ 그 좌표에 마커 문단을 되심는다 — 문서 읽기 순서(항목 여는 마커 → 선택 마커들 →
       항목 닫는 마커)대로 실어 보내고 삽입 순서 처리는 Domain 이 진다.
    ④ 사후조건: 표기 진단 0 · 그 선언이 표기로 전건 복원 · 남은 제품 Slot == 기존 − 대상 ·
       비제품 region 정체 보존. 하나라도 깨지면 패키지는 원본으로 돌아간다.

    **문서 전체 일괄 풀기는 없다**(#822 D6) — 대상은 언제나 Slot 하나다.
    """
    identifier = _require_text(slot_id, "Slot id")
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

    def mutate() -> None:
        for _option, option_region in options:
            unwrap_bookmark_region(package, _relocate_region(package, option_region))
        unwrap_bookmark_region(package, _relocate_region(package, region))
        insert_marker_paragraphs(package, entry, markers)

    def verify() -> None:
        residue = scan_structure(package)
        if residue.diagnostics or residue.slots != (slot,):
            raise ValueError(
                "Slot decompile postcondition (notation) failed: "
                f"expected {(slot,)!r}, got {residue.to_dict()!r}"
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
    existing, diagnostics = inspect_slots(package)
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
    for region in resolve_bookmark_topology(package):
        if (region.section, region.name) in wanted:
            refusals.append(
                _refusal(
                    StructureCompileRefusalKind.NAME_COLLISION,
                    region.name,
                    f"{region.section}: 「{region.name}」 이름의 책갈피가 이미 있습니다 — "
                    "선언 id 를 바꾸거나 기존 책갈피를 지우세요.",
                )
            )
    return tuple(refusals)


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
            payload = serialize_slot_option_metatag(option)
            parent = _locate_region(package, slot_locator[placement.slot_id])
        else:
            name = structure_region_name(placement.slot_id)
            payload = serialize_slot_metatag(slot)
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
    snapshot = _inspect_slot_snapshot(package)
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
    slots, diagnostics = inspect_slots(package)
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


def compile_structure_file(path: str) -> StructureCompileReport:
    """경로의 구간 표기를 컴파일해 **같은 경로에 저장**(변이가 있을 때만).

    거절·no-op 이면 파일을 한 바이트도 쓰지 않는다(:func:`compile_template_file` 선례).
    """
    package = read_hwpx_package(path)
    report = compile_structure(package)
    if report.modified:
        write_hwpx_package(path, package)
    return report


def _mutate_slot_file(
    path: str, mutate: "Callable[[object], None]"
) -> "tuple[Slot, ...]":
    """경로를 열어 Slot 동사 하나를 돌리고 **성공했을 때만** 같은 경로에 저장.

    동사가 거절하면(``ValueError``) 파일은 한 바이트도 바뀌지 않는다 —
    :func:`compile_structure_file` 과 같은 규율이다. 반환은 변이 뒤 제품 Slot 목록이라
    상위 링이 결과를 재진술하려고 파일을 다시 열지 않는다.
    """
    package = read_hwpx_package(path)
    mutate(package)
    write_hwpx_package(path, package)
    slots, _diagnostics = inspect_slots(package)
    return slots


def rename_slot_label_file(path: str, slot_id: str, label: "str | None" = None):
    """경로의 Slot label 을 바꾸고 제자리 저장(성공 시에만)."""
    return _mutate_slot_file(path, lambda pkg: rename_slot_label(pkg, slot_id, label))


def decompile_slot_file(path: str, slot_id: str):
    """경로의 Slot 하나를 구간 표기로 되돌리고 제자리 저장(성공 시에만)."""
    return _mutate_slot_file(path, lambda pkg: decompile_slot(pkg, slot_id))


def remove_slot_file(path: str, slot_id: str):
    """경로의 Slot 하나를 **내용째** 지우고 제자리 저장(성공 시에만)."""
    return _mutate_slot_file(path, lambda pkg: remove_slot(pkg, slot_id))


def scan_template_structure(path: str) -> StructureScan:
    """경로 → 구간 표기 스캔(읽기 전용, 파일 무변형)."""
    return scan_structure(read_hwpx_package(path))


def inspect_hwpx_template(path: str) -> TemplateInspection:
    """경로를 한 번 열고 같은 패키지 스냅샷에서 상태와 사전고지를 계산한다."""
    package = read_hwpx_package(path)
    slots, diagnostics = inspect_slots(package)
    return TemplateInspection(
        status=compile_status(package),
        precheck_notes=tuple(fill_precheck(package)),
        fields=tuple(extract_schema(package).field_names()),
        slots=slots,
        diagnostics=diagnostics,
    )


def template_compile_status(path: str) -> TemplateStatus:
    """경로 → 컴파일 수명주기 상태(C2). 홈/라이브러리 배지 파생 포트의 concrete."""
    return compile_status(read_hwpx_package(path))


def scan_template_tokens(path: str) -> "list[TokenSite]":
    """경로 → 토큰 스캔 미리보기(읽기 전용, 파일 무변형)."""
    return scan_tokens(read_hwpx_package(path))


def compile_template_file(path: str) -> CompileReport:
    """경로의 토큰을 누름틀로 컴파일해 **같은 경로에 저장**(변경이 있을 때만).

    바뀐 게 없으면(``modified=False``) 아무것도 쓰지 않는다 — 종전
    ``TemplateManagerViewModel.apply_fieldize`` 의 저장 판정 그대로.
    """
    pkg, report = compile_document(read_hwpx_package(path))
    if report.modified:
        write_hwpx_package(path, pkg)
    return report


def compile_to_sibling(path: str, *, overwrite: bool = False) -> "tuple[str | None, CompileReport]":
    """토큰을 컴파일해 **원본 옆** ``<이름>.compiled.hwpx`` 로 저장(원본 무변형).

    출력 경로 파생·저장·충돌 정책을 뷰가 하드코딩하지 않는다(RC-28). 정책:

    - 바꿀 토큰이 없으면(``modified=False``) 아무것도 쓰지 않고 ``(None, report)``.
    - 컴파일본이 이미 있으면 ``overwrite=True`` 없이는 :class:`FileExistsError`
      (메시지 = 충돌 경로)로 시끄럽게 차단 — 조용한 덮어쓰기 금지(RC-02). 호출측이
      사용자 확정을 받은 뒤 ``overwrite=True`` 로 재호출한다.
    - 컴파일·저장 실패는 그대로 raise(호출측이 시끄럽게 표시).

    (P2-19R 에서 ``domain.authoring`` 과 분리 — 경로 열기·충돌 검사·저장이 파일 IO 개시라
    Domain 에 둘 수 없다. 의미 불변.)
    """
    pkg, report = compile_document(read_hwpx_package(path))
    if not report.modified:
        return None, report
    compiled_path = str(Path(path).with_suffix(".compiled.hwpx"))
    if Path(compiled_path).exists() and not overwrite:
        raise FileExistsError(compiled_path)
    write_hwpx_package(compiled_path, pkg)
    return compiled_path, report


def lint_template_file(
    path: str, vocabulary: "list[str] | set[str] | None" = None
) -> LintReport:
    """경로 → 단일 템플릿 위생 점검(읽기 전용)."""
    return lint_template(read_hwpx_package(path), vocabulary=vocabulary)


def diff_template_schemas(old_path: str, new_path: str) -> SchemaDrift:
    """두 경로의 판본 간 필드셋 드리프트(추가/삭제/개명 추정). 읽기 전용."""
    return diff_schema(read_hwpx_package(old_path), read_hwpx_package(new_path))


def read_template_fields(path: str) -> "dict[str, str]":
    """경로 → 모든 누름틀 현재 값(C1 read_fields)."""
    return read_fields(read_hwpx_package(path))


#: :class:`~hwpxfiller.gui.template_manager_state.TemplateFileOps` 의 concrete 결속 —
#: ring 2 가 ``TemplateManagerViewModel(file_ops=HWPX_TEMPLATE_OPS)`` 로 주입한다.
HWPX_TEMPLATE_OPS = TemplateFileOps(
    scan_tokens=scan_template_tokens,
    compile_file=compile_template_file,
    lint=lint_template_file,
    diff=diff_template_schemas,
    read_fields=read_template_fields,
    scan_structure=scan_template_structure,
    compile_structure_file=compile_structure_file,
    rename_slot_label=rename_slot_label_file,
    decompile_slot=decompile_slot_file,
    remove_slot=remove_slot_file,
)
