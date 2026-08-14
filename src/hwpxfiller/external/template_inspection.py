"""HWPX 템플릿 판독·컴파일 파일 효과의 외부 어댑터.

파서 의미론 층(schema·authoring·template_status·lint·fields)은 **열린 package 전용**이다
(P2-19R, #576). 경로를 받아 package adapter로 한 번 열고 Domain 순수
함수를 부르는 path 진입 함수들이 여기 산다 — ring 2/Host 는 직접 부르고, Application VM
(gui)은 External 을 import 할 수 없어 ring 2 가 이 함수들을 포트로 결속해 주입한다
(P2-12 ``inspect_hwpx_template`` 동형).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from hwpxcore.bookmark_region import (
    BookmarkRegion,
    remove_bookmark_region,
    resolve_bookmark_topology,
)
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
from hwpxcore.text_extract import require_package

from ..domain.authoring import CompileReport, TokenSite, compile_document, scan_tokens
from ..domain.fields import fill_precheck, read_fields
from ..domain.lint import LintReport, SchemaDrift, diff_schema, lint_template
from ..domain.schema import extract_schema
from ..domain.slot import Slot, SlotOption
from ..domain.template_status import TemplateStatus, compile_status
from ..gui.template_manager_state import (
    TemplateDiagnostic,
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


@dataclass(frozen=True)
class ProductBookmarkInspection:
    observations: tuple[ProductScopeObservation, ...]
    diagnostics: tuple[TemplateDiagnostic, ...]
    _projection_pairs: frozenset[BoundaryPairRef] = field(
        default_factory=frozenset, repr=False, compare=False
    )


class _ParsedProduct(NamedTuple):
    classification: ProductClassification
    kind: str | None = None
    product_id: str | None = None


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


def _serialize_product_metatag(kind: str, identifier: str) -> str:
    return json.dumps(
        {"hwpxFiller": {"kind": kind, "id": identifier}, "name": _NATIVE_NAME},
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
    return _serialize_product_metatag("slot", slot.id)


def serialize_slot_option_metatag(option: SlotOption) -> str:
    """Serialize one canonical object-local Slot Option payload."""
    _require_text(option.id, "Slot Option id")
    return _serialize_product_metatag("slot_option", option.id)


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


def _project_slots(inspection: ProductBookmarkInspection) -> tuple[Slot, ...]:
    option_ids: dict[BoundaryPairRef, list[str]] = {}
    for item in inspection.observations:
        if (
            item.classification is ProductClassification.KNOWN_PRODUCT
            and item.kind == "slot_option"
            and item.product_id is not None
            and item.owning_slot_pair is not None
            and item.pair in inspection._projection_pairs
        ):
            option_ids.setdefault(item.owning_slot_pair, []).append(item.product_id)
    return tuple(
        Slot(
            item.product_id,
            tuple(
                SlotOption(identifier, order)
                for order, identifier in enumerate(option_ids.get(item.pair, ()))
            ),
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


def _remove_product_region(
    package: object,
    region: BookmarkRegion,
    expected: tuple[Slot, ...],
) -> None:
    entries = package.entries  # type: ignore[attr-defined]
    original = dict(entries)
    try:
        remove_bookmark_region(package, region)
        actual, diagnostics = inspect_slots(package)
        if diagnostics or actual != expected:
            raise ValueError(
                "Slot removal postcondition failed: "
                f"expected {expected!r}, got {actual!r} with {diagnostics!r}"
            )
    except Exception:
        entries.clear()
        entries.update(original)
        raise


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
                SlotOption(option.id, order)
                for order, option in enumerate(
                    item for item in slot.options if item.id != target_id
                )
            ),
        )
        for slot in snapshot.slots
    )
    _remove_product_region(package, region, expected)


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
)
