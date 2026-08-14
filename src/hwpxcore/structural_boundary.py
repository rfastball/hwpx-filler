"""Read-only entry-local Field and BOOKMARK boundary projection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from lxml import etree

from .field_occurrence import (
    FieldDiagnosticKind,
    paragraph_container,
    resolve_field_occurrences,
)
from .text_extract import HP_NS, local_name, require_package

_HS_NS = "http://www.hancom.co.kr/hwpml/2011/section"
_HP = f"{{{HP_NS}}}"
_HS = f"{{{_HS_NS}}}"


class ContentEntryKind(StrEnum):
    SECTION = "section"
    HEADER = "header"
    FOOTER = "footer"


class StructuralDiagnosticKind(StrEnum):
    """Typed format failures emitted by a structural scan."""

    MISSING_SECTION_ENTRY = "missing-section-entry"
    UNSUPPORTED_CONTENT_ENTRY = "unsupported-content-entry"
    MALFORMED_XML = "malformed-xml"
    INVALID_ENTRY_ROOT = "invalid-entry-root"
    INVALID_CONTENT_ENVELOPE = "invalid-content-envelope"
    NON_NATIVE_BOUNDARY = "non-native-boundary"
    UNSUPPORTED_BOOKMARK_CONTROL_SHAPE = "unsupported-bookmark-control-shape"
    UNSUPPORTED_BOOKMARK_TRAVERSAL_LANE = "unsupported-bookmark-traversal-lane"
    BOOKMARK_BEGIN_MISSING_ID = "bookmark-begin-missing-id"
    BOOKMARK_DUPLICATE_BEGIN_ID = "bookmark-duplicate-begin-id"
    BOOKMARK_MISSING_END = "bookmark-missing-end"
    BOOKMARK_AMBIGUOUS_END = "bookmark-ambiguous-end"
    BOOKMARK_END_PRECEDES_BEGIN = "bookmark-end-precedes-begin"
    BOOKMARK_CROSSING = "bookmark-crossing"
    NON_NATIVE_METATAG = "non-native-metatag"
    INVALID_METATAG_SHAPE = "invalid-metatag-shape"
    FIELD_UNMATCHED_BEGIN = "field-unmatched-begin"
    FIELD_ORPHAN_END = "field-orphan-end"
    FIELD_AMBIGUOUS_END = "field-ambiguous-end"
    FIELD_NESTED = "field-nested"
    FIELD_NON_NATIVE_CONTROL = "field-non-native-control"
    FIELD_UNSUPPORTED_CONTROL_SHAPE = "field-unsupported-control-shape"
    FIELD_UNSUPPORTED_TRAVERSAL_LANE = "field-unsupported-traversal-lane"
    FIELD_PARAGRAPH_CROSSING = "field-paragraph-crossing"
    FIELD_UNSUPPORTED_CONTAINER_CROSSING = (
        "field-unsupported-container-crossing"
    )


@dataclass(frozen=True)
class StructuralDiagnostic:
    entry: str | None
    kind: StructuralDiagnosticKind
    order: int | None = None
    detail: str = ""


class BoundaryPairRef:
    """Opaque identity shared only by matching events from one scan."""

    __slots__ = ()


@dataclass(frozen=True)
class FieldBegin:
    pair: BoundaryPairRef
    raw_name: str | None


@dataclass(frozen=True)
class FieldEnd:
    pair: BoundaryPairRef


@dataclass(frozen=True)
class BookmarkBegin:
    pair: BoundaryPairRef
    bookmark_name: str | None
    meta_tags: tuple[str, ...]
    meta_tag_attribute: str | None


@dataclass(frozen=True)
class BookmarkEnd:
    pair: BoundaryPairRef


BoundaryEvent = FieldBegin | FieldEnd | BookmarkBegin | BookmarkEnd


@dataclass(frozen=True)
class StructuralEntryScan:
    entry: str
    kind: ContentEntryKind
    events: tuple[BoundaryEvent, ...]
    field_pairing_usable: bool
    bookmark_topology_usable: bool


@dataclass(frozen=True)
class StructuralBoundaryScan:
    entries: tuple[StructuralEntryScan, ...]
    diagnostics: tuple[StructuralDiagnostic, ...]


_ENTRY_PATTERNS = (
    (ContentEntryKind.SECTION, 0, re.compile(r"section(\d+)\.xml", re.IGNORECASE)),
    (ContentEntryKind.HEADER, 1, re.compile(r"header(\d+)\.xml", re.IGNORECASE)),
    (ContentEntryKind.FOOTER, 2, re.compile(r"footer(\d+)\.xml", re.IGNORECASE)),
)
_CONTENT_LIKE = re.compile(r"(?:section|header|footer).*\.xml", re.IGNORECASE)
# Numeric header/footer content parts are section-shaped in the existing product
# contract; unnumbered ``header.xml`` is the unrelated style table.
_ENTRY_ROOT = {
    ContentEntryKind.SECTION: f"{_HS}sec",
    ContentEntryKind.HEADER: f"{_HS}sec",
    ContentEntryKind.FOOTER: f"{_HS}sec",
}
_ENTRY_CHILD = {
    ContentEntryKind.SECTION: f"{_HP}p",
    ContentEntryKind.HEADER: f"{_HP}p",
    ContentEntryKind.FOOTER: f"{_HP}p",
}
_FIELD_DIAGNOSTIC_KIND = {
    FieldDiagnosticKind.UNMATCHED_BEGIN: StructuralDiagnosticKind.FIELD_UNMATCHED_BEGIN,
    FieldDiagnosticKind.ORPHAN_END: StructuralDiagnosticKind.FIELD_ORPHAN_END,
    FieldDiagnosticKind.AMBIGUOUS_END: StructuralDiagnosticKind.FIELD_AMBIGUOUS_END,
    FieldDiagnosticKind.NESTED_FIELD: StructuralDiagnosticKind.FIELD_NESTED,
    FieldDiagnosticKind.NON_NATIVE_FIELD_CONTROL: (
        StructuralDiagnosticKind.FIELD_NON_NATIVE_CONTROL
    ),
    FieldDiagnosticKind.UNSUPPORTED_CONTROL_SHAPE: (
        StructuralDiagnosticKind.FIELD_UNSUPPORTED_CONTROL_SHAPE
    ),
    FieldDiagnosticKind.UNSUPPORTED_TRAVERSAL_LANE: (
        StructuralDiagnosticKind.FIELD_UNSUPPORTED_TRAVERSAL_LANE
    ),
    FieldDiagnosticKind.PARAGRAPH_CROSSING: (
        StructuralDiagnosticKind.FIELD_PARAGRAPH_CROSSING
    ),
    FieldDiagnosticKind.UNSUPPORTED_CONTAINER_CROSSING: (
        StructuralDiagnosticKind.FIELD_UNSUPPORTED_CONTAINER_CROSSING
    ),
}


@dataclass(frozen=True)
class _BookmarkPair:
    begin: etree._Element
    end: etree._Element
    name: str | None
    meta_tags: tuple[str, ...]
    meta_tag_attribute: str | None


def _entry_match(name: str) -> tuple[ContentEntryKind, int, int] | None:
    base = name.rsplit("/", 1)[-1]
    for kind, kind_order, pattern in _ENTRY_PATTERNS:
        if match := pattern.fullmatch(base):
            return kind, kind_order, int(match.group(1))
    return None


def _looks_boundary_bearing(source: bytes) -> bool:
    try:
        root = etree.fromstring(
            source,
            etree.XMLParser(remove_blank_text=False, resolve_entities=False),
        )
    except (etree.XMLSyntaxError, TypeError, ValueError):
        return b"fieldBegin" in source or b"fieldEnd" in source
    return any(
        local_name(node.tag) in {"fieldBegin", "fieldEnd"}
        for node in root.iter()
        if isinstance(node.tag, str)
    )


def _content_entries(package: object) -> tuple[
    list[tuple[ContentEntryKind, str]], list[StructuralDiagnostic]
]:
    entries = package.entries  # type: ignore[attr-defined]
    supported: list[tuple[int, int, str, ContentEntryKind]] = []
    diagnostics: list[StructuralDiagnostic] = []
    for name, source in entries.items():
        if match := _entry_match(name):
            kind, kind_order, suffix = match
            supported.append((kind_order, suffix, name, kind))
            continue
        base = name.rsplit("/", 1)[-1]
        if _CONTENT_LIKE.fullmatch(base) and _looks_boundary_bearing(source):
            diagnostics.append(
                StructuralDiagnostic(
                    name, StructuralDiagnosticKind.UNSUPPORTED_CONTENT_ENTRY
                )
            )
    supported.sort(key=lambda item: item[:3])
    diagnostics.sort(key=lambda item: item.entry or "")
    if not any(item[3] is ContentEntryKind.SECTION for item in supported):
        diagnostics.insert(
            0,
            StructuralDiagnostic(
                None, StructuralDiagnosticKind.MISSING_SECTION_ENTRY
            ),
        )
    return [(kind, name) for _, _, name, kind in supported], diagnostics


def _marker_problem(
    node: etree._Element, root: etree._Element
) -> StructuralDiagnosticKind | None:
    ctrl = node.getparent()
    run = ctrl.getparent() if ctrl is not None else None
    paragraph = run.getparent() if run is not None else None
    chain = (
        (node, local_name(node.tag), f"{_HP}{local_name(node.tag)}"),
        (ctrl, "ctrl", f"{_HP}ctrl"),
        (run, "run", f"{_HP}run"),
        (paragraph, "p", f"{_HP}p"),
    )
    if any(item is None or local_name(item.tag) != expected for item, expected, _ in chain):
        return StructuralDiagnosticKind.UNSUPPORTED_BOOKMARK_CONTROL_SHAPE
    if any(item.tag != expected for item, _, expected in chain):
        return StructuralDiagnosticKind.NON_NATIVE_BOUNDARY
    assert paragraph is not None
    if paragraph_container(paragraph, root) is None:
        return StructuralDiagnosticKind.UNSUPPORTED_BOOKMARK_TRAVERSAL_LANE
    return None


def _bookmark_pairs(
    entry: str,
    root: etree._Element,
    nodes: list[etree._Element],
    order: dict[etree._Element, int],
) -> tuple[list[_BookmarkPair], list[StructuralDiagnostic], bool]:
    diagnostics: list[StructuralDiagnostic] = []
    usable = True

    def report(
        kind: StructuralDiagnosticKind,
        node: etree._Element | None = None,
        detail: str = "",
        *,
        topology: bool = True,
    ) -> None:
        nonlocal usable
        item_order = order.get(node) if node is not None else None
        diagnostics.append(StructuralDiagnostic(entry, kind, item_order, detail))
        if topology:
            usable = False

    all_begins: dict[str, list[etree._Element]] = {}
    ends: dict[str, list[etree._Element]] = {}
    bookmark_begins: list[etree._Element] = []
    for node in nodes:
        if local_name(node.tag) == "fieldBegin":
            if node.tag == f"{_HP}fieldBegin" and (pair_id := node.get("id")):
                all_begins.setdefault(pair_id, []).append(node)
            if node.get("type") == "BOOKMARK":
                bookmark_begins.append(node)
        elif local_name(node.tag) == "fieldEnd" and (
            begin_ref := node.get("beginIDRef")
        ):
            ends.setdefault(begin_ref, []).append(node)

    pairs: list[_BookmarkPair] = []
    for begin in bookmark_begins:
        if problem := _marker_problem(begin, root):
            report(problem, begin)
            continue
        pair_id = begin.get("id")
        if not pair_id:
            report(StructuralDiagnosticKind.BOOKMARK_BEGIN_MISSING_ID, begin)
            continue
        begin_matches = all_begins.get(pair_id, [])
        if len(begin_matches) != 1:
            report(
                StructuralDiagnosticKind.BOOKMARK_DUPLICATE_BEGIN_ID,
                begin,
                f"id={pair_id!r}",
            )
            continue
        end_matches = ends.get(pair_id, [])
        native_ends = [end for end in end_matches if end.tag == f"{_HP}fieldEnd"]
        for foreign_end in (end for end in end_matches if end.tag != f"{_HP}fieldEnd"):
            report(StructuralDiagnosticKind.NON_NATIVE_BOUNDARY, foreign_end)
        if not native_ends:
            report(
                StructuralDiagnosticKind.BOOKMARK_MISSING_END,
                begin,
                f"id={pair_id!r}",
            )
            continue
        if len(native_ends) != 1:
            report(
                StructuralDiagnosticKind.BOOKMARK_AMBIGUOUS_END,
                native_ends[0],
                f"beginIDRef={pair_id!r}",
            )
            continue
        end = native_ends[0]
        if problem := _marker_problem(end, root):
            report(problem, end)
            continue
        if order[end] <= order[begin]:
            report(
                StructuralDiagnosticKind.BOOKMARK_END_PRECEDES_BEGIN,
                end,
                f"id={pair_id!r}",
            )
            continue

        meta_tags: list[str] = []
        for child in begin:
            if local_name(child.tag) != "metaTag":
                continue
            if child.tag != f"{_HP}metaTag":
                report(
                    StructuralDiagnosticKind.NON_NATIVE_METATAG,
                    child,
                    topology=False,
                )
                continue
            if len(child):
                report(
                    StructuralDiagnosticKind.INVALID_METATAG_SHAPE,
                    child,
                    topology=False,
                )
                continue
            meta_tags.append(child.text or "")
        pairs.append(
            _BookmarkPair(
                begin,
                end,
                begin.get("name"),
                tuple(meta_tags),
                begin.get("metaTag"),
            )
        )

    open_pairs: list[_BookmarkPair] = []
    for pair in sorted(pairs, key=lambda item: order[item.begin]):
        while open_pairs and order[open_pairs[-1].end] < order[pair.begin]:
            open_pairs.pop()
        if open_pairs and order[pair.end] > order[open_pairs[-1].end]:
            report(
                StructuralDiagnosticKind.BOOKMARK_CROSSING,
                pair.begin,
                f"{open_pairs[-1].name!r}, {pair.name!r}",
            )
        open_pairs.append(pair)

    diagnostics.sort(
        key=lambda item: (
            item.order is not None,
            item.order if item.order is not None else -1,
            item.kind.value,
            item.detail,
        )
    )
    return pairs, diagnostics, usable


def _failed_entry(
    entry: str, kind: ContentEntryKind, diagnostic: StructuralDiagnostic
) -> tuple[StructuralEntryScan, list[StructuralDiagnostic]]:
    return StructuralEntryScan(entry, kind, (), False, False), [diagnostic]


def _scan_entry(
    entry: str, kind: ContentEntryKind, source: bytes
) -> tuple[StructuralEntryScan, list[StructuralDiagnostic]]:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    try:
        root = etree.fromstring(source, parser)
    except (etree.XMLSyntaxError, TypeError, ValueError) as exc:
        return _failed_entry(
            entry,
            kind,
            StructuralDiagnostic(
                entry, StructuralDiagnosticKind.MALFORMED_XML, detail=str(exc)
            ),
        )
    if root.tag != _ENTRY_ROOT[kind]:
        return _failed_entry(
            entry,
            kind,
            StructuralDiagnostic(
                entry,
                StructuralDiagnosticKind.INVALID_ENTRY_ROOT,
                detail=f"expected {_ENTRY_ROOT[kind]!r}, got {root.tag!r}",
            ),
        )

    direct_children = [child for child in root if isinstance(child.tag, str)]
    if not direct_children or any(child.tag != _ENTRY_CHILD[kind] for child in direct_children):
        return _failed_entry(
            entry,
            kind,
            StructuralDiagnostic(
                entry,
                StructuralDiagnosticKind.INVALID_CONTENT_ENVELOPE,
                detail=f"expected one or more direct {_ENTRY_CHILD[kind]!r} children",
            ),
        )

    nodes = [node for node in root.iter() if isinstance(node.tag, str)]
    order = {node: index for index, node in enumerate(nodes)}
    field_resolution = resolve_field_occurrences(entry, root)
    diagnostics = [
        StructuralDiagnostic(
            item.entry,
            _FIELD_DIAGNOSTIC_KIND[item.kind],
            item.order,
            item.detail,
        )
        for item in field_resolution.diagnostics
    ]
    bookmark_pairs, bookmark_diagnostics, bookmark_usable = _bookmark_pairs(
        entry, root, nodes, order
    )
    # A fieldEnd has no type of its own. Without a local begin it cannot be
    # classified as ordinary Field or BOOKMARK, so both trust axes fail closed.
    if any(
        item.kind is FieldDiagnosticKind.ORPHAN_END
        for item in field_resolution.diagnostics
    ):
        bookmark_usable = False
    diagnostics.extend(bookmark_diagnostics)

    events: list[tuple[int, BoundaryEvent]] = []
    for occurrence in field_resolution.occurrences:
        pair = BoundaryPairRef()
        events.append((occurrence.begin_order, FieldBegin(pair, occurrence.raw_name)))
        events.append((occurrence.end_order, FieldEnd(pair)))
    for bookmark in bookmark_pairs:
        pair = BoundaryPairRef()
        events.append(
            (
                order[bookmark.begin],
                BookmarkBegin(
                    pair,
                    bookmark.name,
                    bookmark.meta_tags,
                    bookmark.meta_tag_attribute,
                ),
            )
        )
        events.append((order[bookmark.end], BookmarkEnd(pair)))
    events.sort(key=lambda item: item[0])
    diagnostics.sort(
        key=lambda item: (
            item.order is not None,
            item.order if item.order is not None else -1,
            item.kind.value,
            item.detail,
        )
    )
    return (
        StructuralEntryScan(
            entry,
            kind,
            tuple(event for _, event in events),
            field_resolution.pairing_usable,
            bookmark_usable,
        ),
        diagnostics,
    )


def scan_structural_boundaries(pkg: object) -> StructuralBoundaryScan:
    """Project Field/BOOKMARK boundaries without mutating an open package."""
    package = require_package(pkg)
    content_entries, diagnostics = _content_entries(package)
    entries: list[StructuralEntryScan] = []
    for kind, entry in content_entries:
        scanned, entry_diagnostics = _scan_entry(
            entry, kind, package.entries[entry]
        )
        entries.append(scanned)
        diagnostics.extend(entry_diagnostics)
    return StructuralBoundaryScan(tuple(entries), tuple(diagnostics))
