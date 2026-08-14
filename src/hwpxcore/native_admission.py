"""Pair-local admission shared by native inspection and mutation.

The public surface deliberately stops at opaque scan pair observations.  Native
node references live only in private plans consumed by the existing writers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from lxml import etree

from .field_occurrence import FieldOccurrence
from .structural_boundary import (
    BookmarkBegin,
    BookmarkEnd,
    BoundaryPairRef,
    ContentEntryKind,
    FieldBegin,
    FieldEnd,
    StructuralBoundaryScan,
    StructuralDiagnosticKind,
)
from .text_extract import HP_NS, local_name, require_package

_HP = f"{{{HP_NS}}}"
_RANGE_MARKERS = {
    "markpenBegin": ("markpen", True),
    "markpenEnd": ("markpen", False),
    "insertBegin": ("insert", True),
    "insertEnd": ("insert", False),
    "deleteBegin": ("delete", True),
    "deleteEnd": ("delete", False),
}
_SAFE_INLINE = {"tab", "lineBreak"}
_RANGE_TAGS = {f"{_HP}{name}" for name in _RANGE_MARKERS}
_SAFE_INLINE_TAGS = {f"{_HP}{name}" for name in _SAFE_INLINE}


class NativeAdmissionContractError(RuntimeError):
    """The supplied scan no longer maps exactly to its package snapshot."""


class FieldFillEffectKind(StrEnum):
    SYNTHESIZE_SLOT = "synthesize-slot"
    REMOVE_INLINE = "remove-inline"
    NORMALIZE_FRAGMENTS = "normalize-fragments"


class FieldFillBlockerKind(StrEnum):
    FIELD_PAIRING_UNUSABLE = "field-pairing-unusable"
    NO_VALUE_POSITION = "no-value-position"
    PROTECTED_RANGE_CROSSING = "protected-range-crossing"
    UNPAIRED_PROTECTED_RANGE = "unpaired-protected-range"
    UNSUPPORTED_INLINE_OBJECT = "unsupported-inline-object"


class BookmarkRemovalBlockerKind(StrEnum):
    UNSUPPORTED_ENTRY = "unsupported-entry"
    BOOKMARK_TOPOLOGY_UNUSABLE = "bookmark-topology-unusable"
    BOOKMARK_METADATA_UNUSABLE = "bookmark-metadata-unusable"
    UNSUPPORTED_BOUNDARY = "unsupported-boundary"
    PARTIAL_PARAGRAPH_BEGIN = "partial-paragraph-begin"
    PARTIAL_PARAGRAPH_END = "partial-paragraph-end"
    NON_PARAGRAPH_EXTENT = "non-paragraph-extent"
    COLLATERAL_BOOKMARK = "collateral-bookmark"
    WHOLE_SECTION = "whole-section"
    SECTION_DEFINITION = "section-definition"
    FIELD_PAIRING_UNUSABLE = "field-pairing-unusable"
    FIELD_INTERSECTION = "field-intersection"
    FIELD_ENCLOSES_TARGET = "field-encloses-target"
    PROTECTED_RANGE_CROSSING = "protected-range-crossing"
    UNPAIRED_PROTECTED_RANGE = "unpaired-protected-range"


@dataclass(frozen=True)
class FieldFillEffect:
    kind: FieldFillEffectKind
    detail: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldFillBlocker:
    kind: FieldFillBlockerKind
    detail: tuple[str, ...] = ()


@dataclass(frozen=True)
class BookmarkRemovalBlocker:
    kind: BookmarkRemovalBlockerKind
    detail: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldFillObservation:
    pair: BoundaryPairRef
    supported_effects: tuple[FieldFillEffect, ...]
    blockers: tuple[FieldFillBlocker, ...]

    @property
    def fillable(self) -> bool:
        return not self.blockers


@dataclass(frozen=True)
class BookmarkRemovalObservation:
    pair: BoundaryPairRef
    blockers: tuple[BookmarkRemovalBlocker, ...]

    @property
    def removable(self) -> bool:
        return not self.blockers


@dataclass(frozen=True)
class NativeCapabilityInspection:
    field_fills: tuple[FieldFillObservation, ...]
    bookmark_removals: tuple[BookmarkRemovalObservation, ...]


@dataclass(frozen=True)
class _ProtectedRange:
    begin: etree._Element
    end: etree._Element
    begin_name: str
    end_name: str


@dataclass(frozen=True)
class NativeAdmissionIndex:
    root: etree._Element
    nodes: tuple[etree._Element, ...]
    order: dict[etree._Element, int]
    ranges: tuple[_ProtectedRange, ...]
    unpaired: tuple[etree._Element, ...]
    unsupported_inline: tuple[etree._Element, ...]
    top_level_spans: dict[etree._Element, tuple[int, int]]
    top_level_nonparagraph_prefix: tuple[int, ...]
    section_definition_orders: tuple[int, ...]


def _range_key(node: etree._Element, kind: str) -> tuple[str, ...] | None:
    if kind == "markpen":
        return ()
    pair_id, cell_id = node.get("Id"), node.get("TcId")
    if not pair_id or not cell_id:
        return None
    return pair_id, cell_id


def build_native_admission_index(
    root: etree._Element,
    nodes: tuple[etree._Element, ...] | None = None,
    order: dict[etree._Element, int] | None = None,
) -> NativeAdmissionIndex:
    """Index protected ranges once for one parsed entry."""
    native_nodes = nodes or tuple(
        node for node in root.iter() if isinstance(node.tag, str)
    )
    native_order = order or {node: index for index, node in enumerate(native_nodes)}
    stack: list[tuple[str, tuple[str, ...], etree._Element]] = []
    pairs: list[_ProtectedRange] = []
    unpaired: list[etree._Element] = []
    for node in native_nodes:
        if not isinstance(node.tag, str) or not node.tag.startswith(_HP):
            continue
        marker = _RANGE_MARKERS.get(local_name(node.tag))
        if marker is None:
            continue
        kind, is_begin = marker
        key = _range_key(node, kind)
        if key is None:
            unpaired.append(node)
            continue
        if is_begin:
            stack.append((kind, key, node))
            continue
        if stack and stack[-1][:2] == (kind, key):
            _, _, begin = stack.pop()
            pairs.append(
                _ProtectedRange(
                    begin,
                    node,
                    local_name(begin.tag),
                    local_name(node.tag),
                )
            )
        else:
            unpaired.append(node)
    unpaired.extend(begin for _, _, begin in stack)

    unsupported: list[etree._Element] = []
    for text in root.iter(f"{_HP}t"):
        for child in text:
            if child.tag in _SAFE_INLINE_TAGS | _RANGE_TAGS:
                unsupported.extend(child.iterdescendants())
            else:
                unsupported.extend(child.iter())
    top_level_spans: dict[etree._Element, tuple[int, int]] = {}
    nonparagraph_prefix = [0]
    for child in root:
        child_orders = [
            native_order[node] for node in child.iter() if node in native_order
        ]
        if child_orders:
            top_level_spans[child] = (child_orders[0], child_orders[-1])
        nonparagraph_prefix.append(
            nonparagraph_prefix[-1] + (child.tag != f"{_HP}p")
        )
    return NativeAdmissionIndex(
        root,
        native_nodes,
        native_order,
        tuple(pairs),
        tuple(unpaired),
        tuple(unsupported),
        top_level_spans,
        tuple(nonparagraph_prefix),
        tuple(
            native_order[node]
            for node in native_nodes
            if node.tag in {f"{_HP}secPr", f"{_HP}colPr"}
        ),
    )


def _node_name(node: etree._Element) -> str:
    if isinstance(node, etree._Comment):
        return "#comment"
    if isinstance(node, etree._ProcessingInstruction):
        return "#pi"
    return local_name(node.tag) or "#node"


def _removed_inline_nodes(occurrence: FieldOccurrence) -> set[etree._Element]:
    return {
        node
        for text in occurrence.texts
        for child in text
        for node in child.iter()
    }


def _unpaired_may_intersect(
    index: NativeAdmissionIndex,
    node: etree._Element,
    start_order: int,
    end_order: int,
) -> bool:
    order = index.order[node]
    name = local_name(node.tag)
    return (
        start_order <= order <= end_order
        or name.endswith("Begin") and order < start_order
        or name.endswith("End") and order > end_order
    )


@dataclass(frozen=True)
class FieldFillPlan:
    occurrence: FieldOccurrence
    removed_nodes: frozenset[etree._Element]
    effects: tuple[FieldFillEffect, ...]
    blockers: tuple[FieldFillBlocker, ...]


def plan_field_fill(
    index: NativeAdmissionIndex,
    occurrence: FieldOccurrence,
    *,
    pairing_usable: bool = True,
) -> FieldFillPlan:
    removed = _removed_inline_nodes(occurrence)
    blockers: list[FieldFillBlocker] = []
    if not pairing_usable:
        blockers.append(
            FieldFillBlocker(FieldFillBlockerKind.FIELD_PAIRING_UNUSABLE)
        )
    if not occurrence.texts and occurrence.end_ctrl is occurrence.begin_ctrl:
        blockers.append(FieldFillBlocker(FieldFillBlockerKind.NO_VALUE_POSITION))

    safe_removed: set[etree._Element] = set()
    for item in index.ranges:
        begin_removed = item.begin in removed
        end_removed = item.end in removed
        if begin_removed != end_removed:
            blockers.append(
                FieldFillBlocker(
                    FieldFillBlockerKind.PROTECTED_RANGE_CROSSING,
                    (item.begin_name, item.end_name),
                )
            )
        elif begin_removed:
            safe_removed.update((item.begin, item.end))
    start_order = index.order[occurrence.begin]
    end_order = index.order[occurrence.end]
    unpaired = tuple(
        sorted(
            {
                _node_name(node)
                for node in index.unpaired
                if _unpaired_may_intersect(index, node, start_order, end_order)
            }
        )
    )
    if unpaired:
        blockers.append(
            FieldFillBlocker(
                FieldFillBlockerKind.UNPAIRED_PROTECTED_RANGE, unpaired
            )
        )
    unsupported = tuple(
        sorted({_node_name(node) for node in index.unsupported_inline if node in removed})
    )
    if unsupported:
        blockers.append(
            FieldFillBlocker(
                FieldFillBlockerKind.UNSUPPORTED_INLINE_OBJECT, unsupported
            )
        )
    safe_removed.update(
        node
        for node in removed
        if isinstance(node.tag, str) and node.tag in _SAFE_INLINE_TAGS
    )

    effects: list[FieldFillEffect] = []
    if not occurrence.texts and occurrence.end_ctrl is not occurrence.begin_ctrl:
        effects.append(FieldFillEffect(FieldFillEffectKind.SYNTHESIZE_SLOT))
    if safe_removed:
        effects.append(
            FieldFillEffect(
                FieldFillEffectKind.REMOVE_INLINE,
                tuple(sorted({_node_name(node) for node in safe_removed})),
            )
        )
    if len(occurrence.texts) > 1:
        effects.append(FieldFillEffect(FieldFillEffectKind.NORMALIZE_FRAGMENTS))
    return FieldFillPlan(
        occurrence, frozenset(removed), tuple(effects), tuple(dict.fromkeys(blockers))
    )


@dataclass(frozen=True)
class FieldFillMutation:
    filled: bool
    modified: bool
    structure_changed: bool
    effects: tuple[FieldFillEffect, ...]
    blockers: tuple[FieldFillBlocker, ...]


def apply_field_fill(
    index: NativeAdmissionIndex,
    occurrence: FieldOccurrence,
    new_value: str,
) -> FieldFillMutation:
    """Apply exactly the plan used by inspection; never mutate a blocked pair."""
    plan = plan_field_fill(index, occurrence)
    if plan.blockers:
        return FieldFillMutation(False, False, False, (), plan.blockers)
    texts = list(occurrence.texts)
    if texts and "".join("".join(text.itertext()) for text in texts) == new_value:
        return FieldFillMutation(True, False, False, (), ())

    modified = False
    structure_changed = False
    performed: list[FieldFillEffect] = []
    if not texts:
        slot = etree.Element(f"{_HP}t")
        if occurrence.end_run is occurrence.begin_run:
            occurrence.begin_run.insert(
                occurrence.begin_run.index(occurrence.end_ctrl), slot
            )
        else:
            new_run = etree.Element(
                f"{_HP}run", dict(occurrence.begin_run.attrib)
            )
            new_run.append(slot)
            occurrence.end_run.addprevious(new_run)
        texts = [slot]
        modified = structure_changed = True
        performed.append(FieldFillEffect(FieldFillEffectKind.SYNTHESIZE_SLOT))

    removed_any = False
    for text in texts:
        for child in list(text):
            text.remove(child)
            removed_any = modified = True
    if removed_any:
        performed.extend(
            effect
            for effect in plan.effects
            if effect.kind is FieldFillEffectKind.REMOVE_INLINE
        )
    first = texts[0]
    if (first.text or "") != new_value:
        first.text = new_value
        modified = True
    for fragment in texts[1:]:
        if fragment.text:
            fragment.text = ""
            modified = True
    if modified and len(texts) > 1:
        performed.append(FieldFillEffect(FieldFillEffectKind.NORMALIZE_FRAGMENTS))
    return FieldFillMutation(True, modified, structure_changed, tuple(performed), ())


@dataclass(frozen=True)
class BookmarkRemovalCandidate:
    begin: etree._Element
    end: etree._Element
    name: str | None


@dataclass(frozen=True)
class BookmarkRemovalPlan:
    blockers: tuple[BookmarkRemovalBlocker, ...]
    protected_markers: tuple[etree._Element, ...] = ()
    removed_begins: tuple[etree._Element, ...] = ()


def _is_bookmark_boundary_ctrl(node: etree._Element) -> bool:
    return node.tag == f"{_HP}ctrl" and len(node) > 0 and all(
        child.tag == f"{_HP}fieldEnd"
        or (child.tag == f"{_HP}fieldBegin" and child.get("type") == "BOOKMARK")
        for child in node
    )


def _has_payload(node: etree._Element) -> bool:
    if node.tag == f"{_HP}linesegarray":
        return False
    if node.tag == f"{_HP}t":
        return bool("".join(node.itertext()) or len(node))
    if node.tag == f"{_HP}run":
        return bool((node.text or "").strip()) or any(
            _has_payload(child) or bool((child.tail or "").strip()) for child in node
        )
    return not _is_bookmark_boundary_ctrl(node)


def _payload_outside(
    node: etree._Element, paragraph: etree._Element, *, preceding: bool
) -> bool:
    current = node
    while current is not paragraph:
        parent = current.getparent()
        if parent is None:
            return True
        if preceding and (parent.text or "").strip():
            return True
        if not preceding and (current.tail or "").strip():
            return True
        if any(
            _has_payload(sibling) or bool((sibling.tail or "").strip())
            for sibling in current.itersiblings(preceding=preceding)
        ):
            return True
        current = parent
    return False


def _boundary_paragraph(
    node: etree._Element, root: etree._Element
) -> etree._Element | None:
    ctrl = node.getparent()
    run = ctrl.getparent() if ctrl is not None else None
    paragraph = run.getparent() if run is not None else None
    if (
        ctrl is None
        or run is None
        or paragraph is None
        or ctrl.tag != f"{_HP}ctrl"
        or run.tag != f"{_HP}run"
        or paragraph.tag != f"{_HP}p"
        or paragraph.getparent() is not root
    ):
        return None
    return paragraph


def _inside_children(
    root: etree._Element, node: etree._Element, start: int, stop: int
) -> bool:
    current = node
    while current.getparent() is not root:
        parent = current.getparent()
        if parent is None:
            return False
        current = parent
    position = root.index(current)
    return start <= position <= stop


def plan_bookmark_removal(
    *,
    entry: str,
    kind: ContentEntryKind,
    index: NativeAdmissionIndex,
    target_begin: etree._Element,
    target_end: etree._Element,
    bookmarks: tuple[BookmarkRemovalCandidate, ...],
    fields: tuple[FieldOccurrence, ...],
    field_pairing_error: str | None,
    bookmark_topology_usable: bool,
    bookmark_metadata_usable: bool = True,
    reject_whole_section: bool = True,
    reject_section_definition: bool = True,
) -> BookmarkRemovalPlan:
    blockers: list[BookmarkRemovalBlocker] = []

    def block(kind_: BookmarkRemovalBlockerKind, message: str) -> None:
        blockers.append(BookmarkRemovalBlocker(kind_, (message,)))

    if kind is not ContentEntryKind.SECTION:
        block(
            BookmarkRemovalBlockerKind.UNSUPPORTED_ENTRY,
            f"{entry}: BOOKMARK removal is supported only in section entries",
        )
    if not bookmark_topology_usable:
        block(
            BookmarkRemovalBlockerKind.BOOKMARK_TOPOLOGY_UNUSABLE,
            f"{entry}: BOOKMARK topology is unusable",
        )
    if not bookmark_metadata_usable:
        block(
            BookmarkRemovalBlockerKind.BOOKMARK_METADATA_UNUSABLE,
            f"{entry}: BOOKMARK metadata is unusable",
        )
    if blockers:
        return BookmarkRemovalPlan(tuple(blockers))

    start_paragraph = _boundary_paragraph(target_begin, index.root)
    stop_paragraph = _boundary_paragraph(target_end, index.root)
    if start_paragraph is None or stop_paragraph is None:
        block(
            BookmarkRemovalBlockerKind.UNSUPPORTED_BOUNDARY,
            f"{entry}: BOOKMARK boundary is not native ctrl/run/top-level-p content",
        )
        return BookmarkRemovalPlan(tuple(blockers))
    start = index.root.index(start_paragraph)
    stop = index.root.index(stop_paragraph)
    extent_start = index.top_level_spans[start_paragraph][0]
    extent_end = index.top_level_spans[stop_paragraph][1]

    target_order = index.order[target_begin], index.order[target_end]
    removed = tuple(
        item
        for item in bookmarks
        if target_order[0] <= index.order[item.begin]
        and index.order[item.end] <= target_order[1]
    )
    ancestors = tuple(
        item
        for item in bookmarks
        if index.order[item.begin] < target_order[0]
        and target_order[1] < index.order[item.end]
    )
    removed_begins = tuple(item.begin for item in removed)
    ancestor_nodes = {node for item in ancestors for node in (item.begin, item.end)}
    protected = tuple(
        node
        for node in ancestor_nodes
        if _inside_children(index.root, node, start, stop)
    )
    collateral = tuple(
        sorted(
            {
                repr(item.name)
                for item in bookmarks
                if item not in removed
                and item not in ancestors
                and (
                    _inside_children(index.root, item.begin, start, stop)
                    or _inside_children(index.root, item.end, start, stop)
                )
            }
        )
    )
    if collateral:
        block(
            BookmarkRemovalBlockerKind.COLLATERAL_BOOKMARK,
            f"{entry}: removing BOOKMARK would cut BOOKMARK markers outside it: "
            + ", ".join(collateral),
        )
    if _payload_outside(target_begin, start_paragraph, preceding=True):
        block(
            BookmarkRemovalBlockerKind.PARTIAL_PARAGRAPH_BEGIN,
            f"{entry}: partial-paragraph BOOKMARK begin is unsupported",
        )
    if _payload_outside(target_end, stop_paragraph, preceding=False):
        block(
            BookmarkRemovalBlockerKind.PARTIAL_PARAGRAPH_END,
            f"{entry}: partial-paragraph BOOKMARK end is unsupported",
        )
    if (
        index.top_level_nonparagraph_prefix[stop + 1]
        != index.top_level_nonparagraph_prefix[start]
    ):
        block(
            BookmarkRemovalBlockerKind.NON_PARAGRAPH_EXTENT,
            f"{entry}: non-paragraph section child in BOOKMARK extent is unsupported",
        )
    if reject_whole_section and start == 0 and stop + 1 == len(index.root) and not protected:
        block(
            BookmarkRemovalBlockerKind.WHOLE_SECTION,
            f"{entry}: removing BOOKMARK would leave no paragraph",
        )
    if reject_section_definition and any(
        extent_start <= order <= extent_end
        for order in index.section_definition_orders
    ):
        block(
            BookmarkRemovalBlockerKind.SECTION_DEFINITION,
            "BOOKMARK content removal would delete section definition",
        )
    if field_pairing_error:
        block(
            BookmarkRemovalBlockerKind.FIELD_PAIRING_UNUSABLE,
            field_pairing_error,
        )
    else:
        for occurrence in fields:
            begin_inside = _inside_children(index.root, occurrence.begin, start, stop)
            end_inside = _inside_children(index.root, occurrence.end, start, stop)
            if begin_inside != end_inside:
                block(
                    BookmarkRemovalBlockerKind.FIELD_INTERSECTION,
                    f"{entry}: field pair intersects BOOKMARK extent",
                )
            elif not begin_inside and (
                index.order[occurrence.begin] < extent_start
                and index.order[occurrence.end] > extent_end
            ):
                block(
                    BookmarkRemovalBlockerKind.FIELD_ENCLOSES_TARGET,
                    f"{entry}: field pair encloses BOOKMARK extent",
                )
        for item in index.ranges:
            begin_inside = _inside_children(index.root, item.begin, start, stop)
            end_inside = _inside_children(index.root, item.end, start, stop)
            encloses = (
                index.order[item.begin] < extent_start
                and index.order[item.end] > extent_end
            )
            if begin_inside != end_inside or encloses:
                block(
                    BookmarkRemovalBlockerKind.PROTECTED_RANGE_CROSSING,
                    f"{entry}: {item.begin_name}/{item.end_name} range intersects "
                    "BOOKMARK extent",
                )
        unpaired = tuple(
            sorted(
                {
                    _node_name(node)
                    for node in index.unpaired
                    if _unpaired_may_intersect(
                        index, node, extent_start, extent_end
                    )
                }
            )
        )
        if unpaired:
            block(
                BookmarkRemovalBlockerKind.UNPAIRED_PROTECTED_RANGE,
                f"{entry}: unpaired protected range in BOOKMARK extent: "
                + ", ".join(unpaired),
            )
    return BookmarkRemovalPlan(
        tuple(dict.fromkeys(blockers)), protected, removed_begins
    )


def _event_pairs(entry: object, begin_type: type, end_type: type) -> set[BoundaryPairRef]:
    events = entry.events  # type: ignore[attr-defined]
    begins = [event.pair for event in events if isinstance(event, begin_type)]
    ends = [event.pair for event in events if isinstance(event, end_type)]
    if len(begins) != len(set(begins)) or len(ends) != len(set(ends)):
        raise NativeAdmissionContractError("duplicate boundary event pair")
    if set(begins) != set(ends):
        raise NativeAdmissionContractError("boundary begin/end pair mismatch")
    return set(begins)


def inspect_native_capabilities(
    pkg: object, scan: StructuralBoundaryScan
) -> NativeCapabilityInspection:
    """Observe exact supplied scan pairs without reparsing or mutating entries."""
    package = require_package(pkg)
    public_by_entry = {item.entry: item for item in scan.entries}
    if len(public_by_entry) != len(scan.entries):
        raise NativeAdmissionContractError("duplicate public scan entry")
    private_by_entry = {item.entry: item for item in scan._native_entries}
    if len(private_by_entry) != len(scan._native_entries):
        raise NativeAdmissionContractError("duplicate private scan entry")
    fatal = {
        diagnostic.entry
        for diagnostic in scan.diagnostics
        if diagnostic.kind.value
        in {"malformed-xml", "invalid-entry-root", "invalid-content-envelope"}
    }
    if fatal - set(public_by_entry) or set(private_by_entry) != set(public_by_entry) - fatal:
        raise NativeAdmissionContractError("public/private scan entry mismatch")
    if (
        scan.entries != scan._expected_entries
        or scan.diagnostics != scan._expected_diagnostics
    ):
        raise NativeAdmissionContractError("structural scan evidence mismatch")
    if frozenset(package.entries) != scan._package_entry_names:
        raise NativeAdmissionContractError("stale structural scan entry roster")
    for entry, digest in scan._source_manifest:
        source = package.entries.get(entry)
        if source is None or sha256(source).digest() != digest:
            raise NativeAdmissionContractError(f"stale structural scan for {entry}")

    metadata_unusable = {
        diagnostic.entry
        for diagnostic in scan.diagnostics
        if diagnostic.kind
        in {
            StructuralDiagnosticKind.NON_NATIVE_METATAG,
            StructuralDiagnosticKind.INVALID_METATAG_SHAPE,
        }
    }

    field_observations: list[FieldFillObservation] = []
    bookmark_observations: list[BookmarkRemovalObservation] = []
    seen_pairs: set[BoundaryPairRef] = set()
    for public in scan.entries:
        detail = private_by_entry.get(public.entry)
        if detail is None:
            if (
                public.events
                or public.field_pairing_usable
                or public.bookmark_topology_usable
            ):
                raise NativeAdmissionContractError(
                    "failed scan entry exposes usable boundary state"
                )
            continue
        if detail.kind is not public.kind:
            raise NativeAdmissionContractError("public/private entry kind mismatch")
        source = package.entries.get(public.entry)
        if source is None or sha256(source).digest() != detail.source_sha256:
            raise NativeAdmissionContractError(
                f"stale structural scan for {public.entry}"
            )
        field_pairs = _event_pairs(public, FieldBegin, FieldEnd)
        bookmark_pairs = _event_pairs(public, BookmarkBegin, BookmarkEnd)
        native_field_pairs = {pair for pair, _ in detail.fields}
        native_bookmark_pairs = {pair for pair, _ in detail.bookmarks}
        if (
            len(native_field_pairs) != len(detail.fields)
            or len(native_bookmark_pairs) != len(detail.bookmarks)
            or field_pairs != native_field_pairs
            or bookmark_pairs != native_bookmark_pairs
            or field_pairs & bookmark_pairs
            or seen_pairs & (field_pairs | bookmark_pairs)
        ):
            raise NativeAdmissionContractError("native boundary pair registry mismatch")
        seen_pairs.update(field_pairs | bookmark_pairs)

        index = build_native_admission_index(detail.root, detail.nodes, detail.order)
        for pair, occurrence in detail.fields:
            plan = plan_field_fill(
                index,
                occurrence,
                pairing_usable=public.field_pairing_usable,
            )
            field_observations.append(
                FieldFillObservation(pair, plan.effects, plan.blockers)
            )
        candidates = tuple(
            BookmarkRemovalCandidate(pair.begin, pair.end, pair.name)
            for _, pair in detail.bookmarks
        )
        for pair_ref, bookmark in detail.bookmarks:
            plan = plan_bookmark_removal(
                entry=detail.entry,
                kind=detail.kind,
                index=index,
                target_begin=bookmark.begin,
                target_end=bookmark.end,
                bookmarks=candidates,
                fields=tuple(occurrence for _, occurrence in detail.fields),
                field_pairing_error=(
                    None
                    if public.field_pairing_usable
                    else f"{detail.entry}: ordinary Field pairing is unusable"
                ),
                bookmark_topology_usable=public.bookmark_topology_usable,
                bookmark_metadata_usable=detail.entry not in metadata_unusable,
            )
            bookmark_observations.append(
                BookmarkRemovalObservation(pair_ref, plan.blockers)
            )
    return NativeCapabilityInspection(
        tuple(field_observations), tuple(bookmark_observations)
    )
