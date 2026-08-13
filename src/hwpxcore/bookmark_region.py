"""Native BOOKMARK structural regions with deliberately narrow support."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256

from lxml import etree

from .lineseg import serialize_modified_section
from .text_extract import (
    PackageLike,
    HP_NS as _HP_NS,
    local_name,
    require_package,
    section_xml_names,
)

_HS_NS = "http://www.hancom.co.kr/hwpml/2011/section"
_HP = f"{{{_HP_NS}}}"
_NON_FIELD_RANGE_MARKERS = (
    ("markpenBegin", "markpenEnd"),
    ("insertBegin", "insertEnd"),
    ("deleteBegin", "deleteEnd"),
)


@dataclass(frozen=True)
class BookmarkRegion:
    """A current-snapshot handle for one supported native BOOKMARK region.

    Paragraph indices are zero-based section-direct ``hp:p`` positions and both
    bounds are inclusive. ``parent`` is the immediately enclosing region, or
    ``None`` at the top level, and containment follows document order rather than
    those indices. Today the two agree — the full-paragraph boundary rule rejects
    a nested region that opens or closes in the same paragraph as its container,
    so every child spans strictly fewer paragraphs — but document order is what
    the format actually encodes. Re-resolve after any section mutation; the
    private pairing reference and snapshot digest are deliberately not durable
    identity.
    """

    name: str | None
    section: str
    start_paragraph: int
    end_paragraph: int
    parent: BookmarkRegion | None
    _pairing_id: str = field(repr=False)
    _section_sha256: bytes = field(repr=False)


@dataclass
class _Section:
    entry: str
    root: etree._Element
    nodes: list[etree._Element]
    order: dict[etree._Element, int]
    paragraphs: dict[etree._Element, int]
    begins: dict[str, list[etree._Element]]
    ends: dict[str, list[etree._Element]]
    bookmark_begins: list[etree._Element]
    snapshot: bytes


@dataclass(frozen=True)
class _ResolvedRegion:
    region: BookmarkRegion
    section: _Section = field(repr=False, compare=False)
    begin: etree._Element = field(repr=False, compare=False)
    end: etree._Element = field(repr=False, compare=False)
    start_child: int
    end_child: int
    begin_order: int
    end_order: int


def _has_payload(node: etree._Element) -> bool:
    if node.tag == f"{_HP}linesegarray":
        return False
    if node.tag == f"{_HP}t":
        return bool("".join(node.itertext()) or len(node))
    if node.tag == f"{_HP}run":
        return bool((node.text or "").strip()) or any(
            _has_payload(child) or bool((child.tail or "").strip()) for child in node
        )
    return True


def _payload_outside_boundary(
    node: etree._Element, paragraph: etree._Element, *, preceding: bool
) -> bool:
    current = node
    while current is not paragraph:
        parent = current.getparent()
        assert parent is not None  # native containment was checked first
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
    node: etree._Element, root: etree._Element, entry: str
) -> etree._Element:
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
        raise ValueError(
            f"{entry}: BOOKMARK boundary is not native ctrl/run/top-level-p content"
        )
    return paragraph


def _parse_sections(pkg: PackageLike) -> list[_Section]:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    sections: list[_Section] = []
    for entry in section_xml_names(pkg):
        source = pkg.entries[entry]
        root = etree.fromstring(source, parser)
        if root.tag != f"{{{_HS_NS}}}sec":
            raise ValueError(f"{entry}: section root is not native hs:sec")
        nodes = list(root.iter())
        begins: dict[str, list[etree._Element]] = {}
        ends: dict[str, list[etree._Element]] = {}
        bookmark_begins: list[etree._Element] = []
        for node in nodes:
            if (
                local_name(node.tag) == "fieldBegin"
                and node.get("type") == "BOOKMARK"
                and node.tag != f"{_HP}fieldBegin"
            ):
                raise ValueError(
                    f"{entry}: BOOKMARK fieldBegin uses a non-native namespace"
                )
            if node.tag == f"{_HP}fieldBegin":
                begin_id = node.get("id")
                if node.get("type") == "BOOKMARK":
                    bookmark_begins.append(node)
                    if not begin_id:
                        raise ValueError(f"{entry}: BOOKMARK fieldBegin has no id")
                if begin_id:
                    begins.setdefault(begin_id, []).append(node)
            elif node.tag == f"{_HP}fieldEnd" and (
                begin_ref := node.get("beginIDRef")
            ):
                ends.setdefault(begin_ref, []).append(node)
        sections.append(
            _Section(
                entry=entry,
                root=root,
                nodes=nodes,
                order={node: index for index, node in enumerate(nodes)},
                paragraphs={
                    node: index
                    for index, node in enumerate(
                        child for child in root if child.tag == f"{_HP}p"
                    )
                },
                begins=begins,
                ends=ends,
                bookmark_begins=bookmark_begins,
                snapshot=sha256(source).digest(),
            )
        )
    return sections


def _is_inside(region: _ResolvedRegion, node: etree._Element) -> bool:
    current = node
    while current.getparent() is not region.section.root:
        parent = current.getparent()
        if parent is None:
            return False
        current = parent
    child = region.section.root.index(current)
    return region.start_child <= child <= region.end_child


def _link_containment(regions: list[_ResolvedRegion]) -> list[_ResolvedRegion]:
    """Record each region's immediate container, rejecting crossing ranges.

    ``regions`` arrives in begin order, so a stack of still-open regions gives
    the enclosing one directly. Proper nesting closes in the reverse of the
    order it opened; anything else crosses and stays unsupported.
    """
    linked: list[_ResolvedRegion] = []
    open_regions: list[_ResolvedRegion] = []
    for item in regions:
        while open_regions and open_regions[-1].end_order < item.begin_order:
            open_regions.pop()
        container = open_regions[-1] if open_regions else None
        if container is not None and item.end_order > container.end_order:
            raise ValueError(
                f"{item.region.section}: crossing BOOKMARK regions are unsupported: "
                f"{container.region.name!r}, {item.region.name!r}"
            )
        nested = replace(
            item,
            region=replace(
                item.region, parent=container.region if container is not None else None
            ),
        )
        linked.append(nested)
        open_regions.append(nested)
    return linked


def _reject_intersecting_fields(
    region: _ResolvedRegion, bookmark_ids: set[str]
) -> None:
    section = region.section
    extent_orders = [
        section.order[node] for node in section.nodes if _is_inside(region, node)
    ]
    extent_start, extent_end = min(extent_orders), max(extent_orders)

    for node in section.nodes:
        if not _is_inside(region, node) or node in {region.begin, region.end}:
            continue
        tag = local_name(node.tag)
        if tag == "fieldBegin" and not node.get("id"):
            raise ValueError(
                f"{section.entry}: unpaired field marker intersects BOOKMARK extent"
            )
        if tag == "fieldEnd" and not node.get("beginIDRef"):
            raise ValueError(
                f"{section.entry}: unpaired field marker intersects BOOKMARK extent"
            )

    for pairing_id in set(section.begins) | set(section.ends):
        if pairing_id in bookmark_ids:
            continue
        begins = section.begins.get(pairing_id, [])
        ends = section.ends.get(pairing_id, [])
        begin_inside = [node for node in begins if _is_inside(region, node)]
        end_inside = [node for node in ends if _is_inside(region, node)]
        if begin_inside or end_inside:
            if len(begins) != 1 or len(ends) != 1 or not (
                begin_inside and end_inside
            ):
                raise ValueError(
                    f"{section.entry}: field pair intersects BOOKMARK extent"
                )
            continue
        if (
            len(begins) == 1
            and len(ends) == 1
            and section.order[begins[0]] < extent_start
            and section.order[ends[0]] > extent_end
        ):
            raise ValueError(f"{section.entry}: field pair encloses BOOKMARK extent")


def _reject_intersecting_non_field_ranges(region: _ResolvedRegion) -> None:
    section = region.section
    extent_orders = [
        section.order[node] for node in section.nodes if _is_inside(region, node)
    ]
    extent_start, extent_end = min(extent_orders), max(extent_orders)

    for begin_name, end_name in _NON_FIELD_RANGE_MARKERS:
        begins = [
            section.order[node]
            for node in section.nodes
            if node.tag == f"{_HP}{begin_name}"
        ]
        ends = [
            section.order[node]
            for node in section.nodes
            if node.tag == f"{_HP}{end_name}"
        ]
        endpoint_inside = any(extent_start <= order <= extent_end for order in begins + ends)
        possible_enclosure = any(order < extent_start for order in begins) and any(
            order > extent_end for order in ends
        )
        if endpoint_inside or possible_enclosure:
            raise ValueError(
                f"{section.entry}: {begin_name}/{end_name} range intersects BOOKMARK extent"
            )


def _resolve(pkg: PackageLike) -> list[_ResolvedRegion]:
    sections = _parse_sections(pkg)
    resolved: list[_ResolvedRegion] = []
    for section in sections:
        section_regions: list[_ResolvedRegion] = []
        for begin in sorted(section.bookmark_begins, key=section.order.__getitem__):
            begin_id = begin.get("id")
            assert begin_id is not None  # checked while parsing
            begin_matches = section.begins[begin_id]
            if len(begin_matches) != 1:
                raise ValueError(
                    f"{section.entry}: duplicate fieldBegin id {begin_id!r} "
                    f"({len(begin_matches)})"
                )
            remote_end_collisions = [
                other.entry
                for other in sections
                if other is not section
                and begin_id in other.ends
                and (
                    len(other.begins.get(begin_id, [])) != 1
                    or len(other.ends[begin_id]) != 1
                )
            ]
            if remote_end_collisions:
                raise ValueError(
                    f"{section.entry}: cross-section BOOKMARK end collision "
                    f"{begin_id!r} in {remote_end_collisions}"
                )
            end_matches = section.ends.get(begin_id, [])
            if not end_matches:
                raise ValueError(
                    f"{section.entry}: BOOKMARK begin id {begin_id!r} has no fieldEnd"
                )
            if len(end_matches) != 1:
                raise ValueError(
                    f"{section.entry}: ambiguous BOOKMARK fieldEnd reference "
                    f"{begin_id!r} ({len(end_matches)})"
                )
            end = end_matches[0]
            begin_order, end_order = section.order[begin], section.order[end]
            if end_order <= begin_order:
                raise ValueError(
                    f"{section.entry}: BOOKMARK end precedes begin id {begin_id!r}"
                )

            start = _boundary_paragraph(begin, section.root, section.entry)
            stop = _boundary_paragraph(end, section.root, section.entry)
            if _payload_outside_boundary(begin, start, preceding=True):
                raise ValueError(
                    f"{section.entry}: partial-paragraph BOOKMARK begin is unsupported"
                )
            if _payload_outside_boundary(end, stop, preceding=False):
                raise ValueError(
                    f"{section.entry}: partial-paragraph BOOKMARK end is unsupported"
                )

            first, last = section.root.index(start), section.root.index(stop)
            if any(
                child.tag != f"{_HP}p"
                for child in list(section.root)[first : last + 1]
            ):
                raise ValueError(
                    f"{section.entry}: non-paragraph section child in BOOKMARK extent "
                    "is unsupported"
                )
            start_paragraph = section.paragraphs[start]
            end_paragraph = section.paragraphs[stop]
            if end_paragraph - start_paragraph + 1 == len(section.paragraphs):
                raise ValueError(
                    f"{section.entry}: removing BOOKMARK would leave no paragraph"
                )
            section_regions.append(
                _ResolvedRegion(
                    region=BookmarkRegion(
                        name=begin.get("name"),
                        section=section.entry,
                        start_paragraph=start_paragraph,
                        end_paragraph=end_paragraph,
                        parent=None,  # filled in by _link_containment
                        _pairing_id=begin_id,
                        _section_sha256=section.snapshot,
                    ),
                    section=section,
                    begin=begin,
                    end=end,
                    start_child=first,
                    end_child=last,
                    begin_order=begin_order,
                    end_order=end_order,
                )
            )

        section_regions = _link_containment(section_regions)
        bookmark_ids = {item.region._pairing_id for item in section_regions}
        for item in section_regions:
            _reject_intersecting_fields(item, bookmark_ids)
            _reject_intersecting_non_field_ranges(item)
        resolved.extend(section_regions)
    return resolved


def resolve_bookmark_regions(pkg: object) -> list[BookmarkRegion]:
    """List supported native BOOKMARK regions, containers before their contents."""
    return [resolved.region for resolved in _resolve(require_package(pkg))]


def remove_bookmark_region(pkg: object, region: BookmarkRegion) -> None:
    """Remove a freshly resolved region from its open package, in place.

    The whole paragraph range goes, so removing a container removes everything it
    contains — regions nested inside it disappear with their paragraphs. Hancom's
    own deletion of the same range behaves identically (S0-F), and a region whose
    container is removed separately is promoted to the top level rather than
    orphaned.
    """
    package = require_package(pkg)
    matches = [resolved for resolved in _resolve(package) if resolved.region == region]
    if len(matches) != 1:
        raise ValueError(
            "BOOKMARK region is not present in the current package snapshot; resolve again"
        )
    resolved = matches[0]
    for child in list(resolved.section.root)[
        resolved.start_child : resolved.end_child + 1
    ]:
        resolved.section.root.remove(child)
    package.entries[region.section] = serialize_modified_section(resolved.section.root)
