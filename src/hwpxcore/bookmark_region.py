"""Native BOOKMARK structural regions with deliberately narrow support."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from types import SimpleNamespace

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
_PAIRING_ID_START = 1_600_000_001


def _object_metatags(node: etree._Element, entry: str) -> tuple[str, ...]:
    """Read direct native ``hp:metaTag`` values as opaque ordered strings."""
    values: list[str] = []
    for child in node:
        if local_name(child.tag) != "metaTag":
            continue
        if child.tag != f"{_HP}metaTag":
            raise ValueError(f"{entry}: object-local metaTag uses a non-native namespace")
        if len(child):
            raise ValueError(f"{entry}: object-local hp:metaTag must contain text only")
        values.append(child.text or "")
    return tuple(values)


@dataclass(frozen=True)
class BookmarkRegion:
    """A current-snapshot handle for one supported native BOOKMARK region.

    Paragraph indices are zero-based section-direct ``hp:p`` positions and both
    bounds are inclusive. ``parent`` is the immediately enclosing region, or
    ``None`` at the top level, and containment follows document order, never the
    paragraph indices: Hancom lets a region open and close in the same paragraphs
    as the one containing it, so two nested regions can report an identical span
    (S0-G). Re-resolve after any section mutation; the private pairing reference
    and snapshot digest are deliberately not durable identity.
    """

    name: str | None
    section: str
    start_paragraph: int
    end_paragraph: int
    parent: BookmarkRegion | None
    meta_tags: tuple[str, ...]
    meta_tag_attribute: str | None
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


def _is_bookmark_boundary_ctrl(node: etree._Element) -> bool:
    """True for a ``ctrl`` holding nothing but BOOKMARK range markers.

    Hancom writes a sibling boundary like this when one region opens or closes in
    the same paragraph as the region containing it (S0-G). Such a marker is not
    paragraph content, so it must not make the neighbouring boundary look partial.
    A pair belonging to some other field is still caught by the extent checks.
    """
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


def _resolve(
    pkg: PackageLike, *, require_removable: bool = True
) -> list[_ResolvedRegion]:
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
            first, last = section.root.index(start), section.root.index(stop)
            start_paragraph = section.paragraphs[start]
            end_paragraph = section.paragraphs[stop]
            section_regions.append(
                _ResolvedRegion(
                    region=BookmarkRegion(
                        name=begin.get("name"),
                        section=section.entry,
                        start_paragraph=start_paragraph,
                        end_paragraph=end_paragraph,
                        parent=None,  # filled in by _link_containment
                        meta_tags=_object_metatags(begin, section.entry),
                        meta_tag_attribute=begin.get("metaTag"),
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
        if require_removable:
            for item in section_regions:
                _validate_mutable_extent(
                    item, section_regions, reject_whole_section=True
                )
        resolved.extend(section_regions)
    return resolved


def resolve_bookmark_regions(pkg: object) -> list[BookmarkRegion]:
    """List supported native BOOKMARK regions, containers before their contents."""
    return [resolved.region for resolved in _resolve(require_package(pkg))]


def resolve_bookmark_topology(pkg: object) -> list[BookmarkRegion]:
    """Resolve native BOOKMARK containment without paragraph-removal constraints."""
    return [
        resolved.region
        for resolved in _resolve(require_package(pkg), require_removable=False)
    ]


def _fresh_region(
    package: PackageLike,
    region: BookmarkRegion,
    *,
    require_removable: bool,
) -> tuple[_ResolvedRegion, list[_ResolvedRegion]]:
    if not isinstance(region, BookmarkRegion):
        raise TypeError(f"BOOKMARK region must be BookmarkRegion: {type(region)!r}")
    current = _resolve(package, require_removable=require_removable)
    matches = [item for item in current if item.region == region]
    if len(matches) != 1:
        raise ValueError(
            "BOOKMARK region is not present in the current package snapshot; resolve again"
        )
    return matches[0], current


def _candidate_resolution(
    package: PackageLike,
    entry: str,
    root: etree._Element,
    *,
    require_removable: bool,
) -> tuple[bytes, list[_ResolvedRegion]]:
    data = serialize_modified_section(root)
    candidate = SimpleNamespace(entries={**package.entries, entry: data})
    return data, _resolve(candidate, require_removable=require_removable)


def _region_key(item: _ResolvedRegion) -> tuple[str, str]:
    return item.region.section, item.region._pairing_id


def _parent_key(region: BookmarkRegion) -> tuple[str, str] | None:
    if region.parent is None:
        return None
    return region.parent.section, region.parent._pairing_id


def _topology_shape(
    items: list[_ResolvedRegion], *, include_positions: bool
) -> dict[tuple[str, str], tuple[object, ...]]:
    shaped: dict[tuple[str, str], tuple[object, ...]] = {}
    for item in items:
        region = item.region
        value: tuple[object, ...] = (
            region.name,
            _parent_key(region),
            region.meta_tags,
            region.meta_tag_attribute,
        )
        if include_positions:
            value += (region.start_paragraph, region.end_paragraph)
        shaped[_region_key(item)] = value
    return shaped


def _validate_mutable_extent(
    resolved: _ResolvedRegion,
    current: list[_ResolvedRegion],
    *,
    reject_whole_section: bool,
    reject_section_definition: bool = False,
) -> None:
    section = resolved.section
    start = _boundary_paragraph(resolved.begin, section.root, section.entry)
    stop = _boundary_paragraph(resolved.end, section.root, section.entry)
    if _payload_outside_boundary(resolved.begin, start, preceding=True):
        raise ValueError(
            f"{section.entry}: partial-paragraph BOOKMARK begin is unsupported"
        )
    if _payload_outside_boundary(resolved.end, stop, preceding=False):
        raise ValueError(
            f"{section.entry}: partial-paragraph BOOKMARK end is unsupported"
        )
    if any(
        child.tag != f"{_HP}p"
        for child in list(section.root)[
            resolved.start_child : resolved.end_child + 1
        ]
    ):
        raise ValueError(
            f"{section.entry}: non-paragraph section child in BOOKMARK extent "
            "is unsupported"
        )
    if reject_whole_section and (
        resolved.region.end_paragraph - resolved.region.start_paragraph + 1
        == len(section.paragraphs)
    ):
        raise ValueError(f"{section.entry}: removing BOOKMARK would leave no paragraph")
    if reject_section_definition and any(
        node.tag in {f"{_HP}secPr", f"{_HP}colPr"}
        for child in list(section.root)[
            resolved.start_child : resolved.end_child + 1
        ]
        for node in child.iter()
    ):
        raise ValueError("BOOKMARK content removal would delete section definition")
    _reject_intersecting_fields(
        resolved,
        {
            item.region._pairing_id
            for item in current
            if item.region.section == resolved.region.section
        },
    )
    _reject_intersecting_non_field_ranges(resolved)


def _next_pairing_id(sections: list[_Section]) -> str:
    used = {
        pairing_id
        for section in sections
        for pairing_id in set(section.begins) | set(section.ends)
    }
    value = _PAIRING_ID_START
    while str(value) in used:
        value += 1
    return str(value)


def create_bookmark_region(
    pkg: object,
    section: str,
    start_paragraph: int,
    end_paragraph: int,
    *,
    name: str,
    parent: BookmarkRegion | None = None,
) -> BookmarkRegion:
    """Wrap an inclusive top-level paragraph range in a native BOOKMARK pair."""
    if not isinstance(section, str):
        raise TypeError(f"section must be str: {type(section)!r}")
    for label, value in (
        ("start_paragraph", start_paragraph),
        ("end_paragraph", end_paragraph),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{label} must be int: {type(value)!r}")
    if not isinstance(name, str):
        raise TypeError(f"BOOKMARK name must be str: {type(name)!r}")
    if not name.strip():
        raise ValueError("BOOKMARK name must be a non-empty string")
    if parent is not None and not isinstance(parent, BookmarkRegion):
        raise TypeError(f"parent must be BookmarkRegion or None: {type(parent)!r}")

    package = require_package(pkg)
    current = _resolve(package, require_removable=False)
    resolved_parent: _ResolvedRegion | None = None
    if parent is not None:
        matches = [item for item in current if item.region == parent]
        if len(matches) != 1:
            raise ValueError(
                "parent BOOKMARK is not present in the current package snapshot; "
                "resolve again"
            )
        resolved_parent = matches[0]
        if parent.section != section:
            raise ValueError("BOOKMARK range and parent must be in the same section")
        if not (
            parent.start_paragraph <= start_paragraph <= end_paragraph
            <= parent.end_paragraph
        ):
            raise ValueError("BOOKMARK range must be contained by its requested parent")

    sections = _parse_sections(package)
    matches = [item for item in sections if item.entry == section]
    if len(matches) != 1:
        raise ValueError(f"HWPX section was not found: {section!r}")
    parsed = matches[0]
    paragraphs = [child for child in parsed.root if child.tag == f"{_HP}p"]
    if (
        start_paragraph < 0
        or end_paragraph < start_paragraph
        or end_paragraph >= len(paragraphs)
    ):
        raise ValueError(
            f"invalid BOOKMARK paragraph range {start_paragraph}..{end_paragraph} "
            f"for {len(paragraphs)} paragraphs"
        )
    start, stop = paragraphs[start_paragraph], paragraphs[end_paragraph]
    start_runs = [child for child in start if child.tag == f"{_HP}run"]
    end_runs = [child for child in stop if child.tag == f"{_HP}run"]
    if not start_runs or not end_runs:
        raise ValueError("BOOKMARK boundary paragraphs must contain a direct native hp:run")

    pairing_id = _next_pairing_id(sections)
    begin_ctrl = etree.Element(f"{_HP}ctrl")
    etree.SubElement(
        begin_ctrl,
        f"{_HP}fieldBegin",
        id=pairing_id,
        type="BOOKMARK",
        name=name,
    )
    end_ctrl = etree.Element(f"{_HP}ctrl")
    etree.SubElement(end_ctrl, f"{_HP}fieldEnd", beginIDRef=pairing_id)

    if resolved_parent is not None and parent.start_paragraph == start_paragraph:
        parent_begin = next(
            node
            for node in parsed.root.iter(f"{_HP}fieldBegin")
            if node.get("id") == parent._pairing_id
        )
        parent_ctrl = parent_begin.getparent()
        assert parent_ctrl is not None
        parent_run = parent_ctrl.getparent()
        assert parent_run is not None
        parent_run.insert(parent_run.index(parent_ctrl) + 1, begin_ctrl)
    else:
        start_runs[0].insert(0, begin_ctrl)

    if resolved_parent is not None and parent.end_paragraph == end_paragraph:
        parent_end = next(
            node
            for node in parsed.root.iter(f"{_HP}fieldEnd")
            if node.get("beginIDRef") == parent._pairing_id
        )
        parent_ctrl = parent_end.getparent()
        assert parent_ctrl is not None
        parent_run = parent_ctrl.getparent()
        assert parent_run is not None
        parent_run.insert(parent_run.index(parent_ctrl), end_ctrl)
    else:
        end_runs[-1].append(end_ctrl)

    data, after = _candidate_resolution(
        package, section, parsed.root, require_removable=False
    )
    created = [item for item in after if item.region._pairing_id == pairing_id]
    expected_parent = (
        (parent.section, parent._pairing_id) if parent is not None else None
    )
    if len(created) != 1 or (
        created[0].region.section,
        created[0].region.start_paragraph,
        created[0].region.end_paragraph,
        _parent_key(created[0].region),
    ) != (section, start_paragraph, end_paragraph, expected_parent):
        raise ValueError("created BOOKMARK does not match the requested native topology")
    _validate_mutable_extent(
        created[0], after, reject_whole_section=False
    )
    before_shape = _topology_shape(current, include_positions=True)
    after_shape = _topology_shape(after, include_positions=True)
    if {
        key: value for key, value in after_shape.items() if key != (section, pairing_id)
    } != before_shape:
        raise ValueError("creating BOOKMARK changed existing native topology")
    package.entries[section] = data
    return created[0].region


def _commit_metatag_mutation(
    package: PackageLike,
    resolved: _ResolvedRegion,
    current: list[_ResolvedRegion],
    expected: tuple[str, ...],
) -> None:
    data, after = _candidate_resolution(
        package,
        resolved.section.entry,
        resolved.section.root,
        require_removable=False,
    )
    wanted = _topology_shape(current, include_positions=True)
    key = _region_key(resolved)
    value = list(wanted[key])
    value[2] = expected
    wanted[key] = tuple(value)
    if _topology_shape(after, include_positions=True) != wanted:
        raise ValueError("BOOKMARK MetaTag mutation postcondition failed")
    package.entries[resolved.section.entry] = data


def append_bookmark_metatag(pkg: object, region: BookmarkRegion, payload: str) -> None:
    """Append one opaque object-local MetaTag to a freshly resolved BOOKMARK begin."""
    if not isinstance(payload, str):
        raise TypeError(f"hp:metaTag payload must be str: {type(payload)!r}")
    package = require_package(pkg)
    resolved, current = _fresh_region(
        package, region, require_removable=False
    )
    child = etree.SubElement(resolved.begin, f"{_HP}metaTag")
    child.text = payload
    _commit_metatag_mutation(
        package, resolved, current, (*region.meta_tags, payload)
    )


def _require_metatag_index(index: int) -> None:
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError(f"hp:metaTag index must be int: {type(index)!r}")
    if index < 0:
        raise ValueError("hp:metaTag index must be non-negative")


def replace_bookmark_metatag(
    pkg: object, region: BookmarkRegion, index: int, payload: str
) -> None:
    """Replace one direct object-local MetaTag payload by ordered index."""
    _require_metatag_index(index)
    if not isinstance(payload, str):
        raise TypeError(f"hp:metaTag payload must be str: {type(payload)!r}")
    package = require_package(pkg)
    resolved, current = _fresh_region(
        package, region, require_removable=False
    )
    children = [child for child in resolved.begin if child.tag == f"{_HP}metaTag"]
    if index >= len(children):
        raise ValueError(f"hp:metaTag index out of range: {index}")
    children[index].text = payload
    expected = list(region.meta_tags)
    expected[index] = payload
    _commit_metatag_mutation(package, resolved, current, tuple(expected))


def remove_bookmark_metatag(
    pkg: object, region: BookmarkRegion, index: int
) -> None:
    """Remove one direct object-local MetaTag by ordered index."""
    _require_metatag_index(index)
    package = require_package(pkg)
    resolved, current = _fresh_region(
        package, region, require_removable=False
    )
    children = [child for child in resolved.begin if child.tag == f"{_HP}metaTag"]
    if index >= len(children):
        raise ValueError(f"hp:metaTag index out of range: {index}")
    resolved.begin.remove(children[index])
    expected = list(region.meta_tags)
    expected.pop(index)
    _commit_metatag_mutation(package, resolved, current, tuple(expected))


def _remove_marker(node: etree._Element) -> None:
    ctrl = node.getparent()
    assert ctrl is not None
    previous = node.getprevious()
    tail = node.tail or ""
    ctrl.remove(node)
    if tail:
        if previous is None:
            ctrl.text = (ctrl.text or "") + tail
        else:
            previous.tail = (previous.tail or "") + tail
    if len(ctrl) or (ctrl.text or "").strip():
        return
    run = ctrl.getparent()
    assert run is not None
    previous = ctrl.getprevious()
    trailing = (ctrl.text or "") + (ctrl.tail or "")
    run.remove(ctrl)
    if trailing:
        if previous is None:
            run.text = (run.text or "") + trailing
        else:
            previous.tail = (previous.tail or "") + trailing


def unwrap_bookmark_region(pkg: object, region: BookmarkRegion) -> None:
    """Remove one fresh BOOKMARK pair while preserving its content and children."""
    package = require_package(pkg)
    resolved, current = _fresh_region(
        package, region, require_removable=False
    )
    target_key = _region_key(resolved)
    promoted_parent = _parent_key(region)
    wanted = _topology_shape(current, include_positions=True)
    del wanted[target_key]
    for item in current:
        key = _region_key(item)
        if key not in wanted or _parent_key(item.region) != target_key:
            continue
        value = list(wanted[key])
        value[1] = promoted_parent
        wanted[key] = tuple(value)

    _remove_marker(resolved.begin)
    _remove_marker(resolved.end)
    data, after = _candidate_resolution(
        package,
        resolved.section.entry,
        resolved.section.root,
        require_removable=False,
    )
    if _topology_shape(after, include_positions=True) != wanted:
        raise ValueError("BOOKMARK unwrap postcondition failed")
    package.entries[resolved.section.entry] = data


def _is_descendant(candidate: BookmarkRegion, target: BookmarkRegion) -> bool:
    ancestor = candidate.parent
    while ancestor is not None:
        if ancestor == target:
            return True
        ancestor = ancestor.parent
    return False


def _prune_to_markers(
    paragraph: etree._Element, markers: set[etree._Element]
) -> None:
    keep: set[etree._Element] = set(markers)
    for marker in markers:
        current = marker.getparent()
        while current is not None and current is not paragraph:
            keep.add(current)
            current = current.getparent()

    def prune(node: etree._Element) -> None:
        node.text = None
        for child in list(node):
            if child not in keep:
                node.remove(child)
                continue
            if child not in markers:
                prune(child)
            child.tail = None

    prune(paragraph)


def remove_bookmark_region(pkg: object, region: BookmarkRegion) -> None:
    """Remove a freshly resolved region from its open package, in place.

    The whole paragraph range goes, so removing a container removes everything it
    contains — regions nested inside it disappear with their paragraphs. Hancom's
    own deletion of the same range behaves identically (S0-F), and a region whose
    container is removed separately is promoted to the top level rather than
    orphaned.
    """
    package = require_package(pkg)
    resolved, current = _fresh_region(package, region, require_removable=False)
    removed = {
        _region_key(item)
        for item in current
        if item.region == region or _is_descendant(item.region, region)
    }
    ancestors: set[tuple[str, str]] = set()
    ancestor = region.parent
    while ancestor is not None:
        ancestors.add((ancestor.section, ancestor._pairing_id))
        ancestor = ancestor.parent

    # A region may share a boundary paragraph with the one it contains (S0-G), so
    # deleting that paragraph can cut a marker belonging to a region we were not
    # asked to remove and leave its partner orphaned.
    collateral = sorted(
        {
            repr(other.region.name)
            for other in current
            if _region_key(other) not in removed | ancestors
            and (_is_inside(resolved, other.begin) or _is_inside(resolved, other.end))
        }
    )
    if collateral:
        raise ValueError(
            f"{region.section}: removing {region.name!r} would cut BOOKMARK markers "
            f"outside it: {', '.join(collateral)}"
        )

    protected = {
        marker
        for item in current
        if _region_key(item) in ancestors
        for marker in (item.begin, item.end)
        if _is_inside(resolved, marker)
    }
    _validate_mutable_extent(
        resolved,
        current,
        reject_whole_section=not protected,
        reject_section_definition=True,
    )
    for child in list(resolved.section.root)[
        resolved.start_child : resolved.end_child + 1
    ]:
        markers = {
            marker
            for marker in protected
            if _boundary_paragraph(marker, resolved.section.root, region.section) is child
        }
        if markers:
            _prune_to_markers(child, markers)
        else:
            resolved.section.root.remove(child)

    wanted = {
        key: value
        for key, value in _topology_shape(
            current, include_positions=False
        ).items()
        if key not in removed
    }
    data, after = _candidate_resolution(
        package,
        resolved.section.entry,
        resolved.section.root,
        require_removable=False,
    )
    if _topology_shape(after, include_positions=False) != wanted:
        raise ValueError("BOOKMARK content removal postcondition failed")
    package.entries[region.section] = data
