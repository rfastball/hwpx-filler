"""Product bookmark metadata inspection for open HWPX packages."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NamedTuple

from hwpxcore.bookmark_region import BookmarkRegion, resolve_bookmark_topology
from hwpxcore.structural_boundary import (
    BookmarkBegin, BookmarkEnd, BoundaryPairRef, ContentEntryKind, FieldBegin,
    FieldEnd, StructuralBoundaryScan, StructuralDiagnosticKind, scan_structural_boundaries,
)
from hwpxcore.text_extract import require_package

from ..application.template_qualification import TemplateDiagnostic
from ..domain.slot import Slot, SlotOption

PRODUCT_KINDS = frozenset({"slot", "slot_option"})
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
    if not isinstance(kind, str) or kind not in PRODUCT_KINDS:
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
