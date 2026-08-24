"""Native BOOKMARK structural regions with deliberately narrow support."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from types import SimpleNamespace

from lxml import etree

from .field_occurrence import FieldResolution, resolve_field_occurrences
from .lineseg import serialize_modified_section
from .native_admission import (
    BookmarkRemovalCandidate,
    BookmarkRemovalPlan,
    NativeAdmissionIndex,
    build_native_admission_index,
    plan_bookmark_removal,
)
from .structural_boundary import ContentEntryKind
from .text_extract import (
    PackageLike,
    HP_NS as _HP_NS,
    local_name,
    require_package,
    section_xml_names,
)

_HS_NS = "http://www.hancom.co.kr/hwpml/2011/section"
_HP = f"{{{_HP_NS}}}"
_PAIRING_ID_START = 1_600_000_001
#: Local names whose presence makes a paragraph undeletable.  Boundary controls
#: pair across paragraphs, so dropping one half silently breaks the pairing that
#: every resolver here depends on; the section/column definition is the section's
#: own layout root.  Local names (not namespaced tags) so a non-native carrier of
#: the same name is refused too, never silently deleted.
_UNDELETABLE_LOCAL_NAMES = frozenset(
    {"fieldBegin", "fieldEnd", "secPr", "colPr"}
)


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
    ordinary_fields: FieldResolution
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
                ordinary_fields=resolve_field_occurrences(entry, root),
                snapshot=sha256(source).digest(),
            )
        )
    return sections


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
            admission_index = build_native_admission_index(
                section.root, tuple(section.nodes), section.order
            )
            candidates = tuple(
                BookmarkRemovalCandidate(item.begin, item.end, item.region.name)
                for item in section_regions
            )
            for item in section_regions:
                _validate_mutable_extent(
                    item,
                    reject_whole_section=True,
                    reject_section_definition=True,
                    admission_index=admission_index,
                    candidates=candidates,
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
    *,
    reject_whole_section: bool,
    reject_section_definition: bool = False,
    admission_index: NativeAdmissionIndex | None = None,
    candidates: tuple[BookmarkRemovalCandidate, ...] | None = None,
) -> BookmarkRemovalPlan:
    section = resolved.section
    native_candidates = (
        candidates
        if candidates is not None
        else tuple(
            BookmarkRemovalCandidate(
                begin, section.ends[begin_id][0], begin.get("name")
            )
            for begin in section.bookmark_begins
            if (begin_id := begin.get("id")) is not None
            and len(section.begins.get(begin_id, ())) == 1
            and len(section.ends.get(begin_id, ())) == 1
        )
    )
    native_index = admission_index or build_native_admission_index(
        section.root,
        tuple(section.nodes),
        section.order,
    )
    diagnostics = section.ordinary_fields.diagnostics
    plan = plan_bookmark_removal(
        entry=section.entry,
        kind=ContentEntryKind.SECTION,
        index=native_index,
        target_begin=resolved.begin,
        target_end=resolved.end,
        bookmarks=native_candidates,
        fields=section.ordinary_fields.occurrences,
        field_pairing_error=(
            "; ".join(map(str, diagnostics)) if diagnostics else None
        ),
        bookmark_topology_usable=True,
        reject_whole_section=reject_whole_section,
        reject_section_definition=reject_section_definition,
    )
    if plan.blockers:
        raise ValueError("; ".join(blocker.detail[0] for blocker in plan.blockers))
    return plan


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
    _validate_mutable_extent(created[0], reject_whole_section=False)
    before_shape = _topology_shape(current, include_positions=True)
    after_shape = _topology_shape(after, include_positions=True)
    if {
        key: value for key, value in after_shape.items() if key != (section, pairing_id)
    } != before_shape:
        raise ValueError("creating BOOKMARK changed existing native topology")
    package.entries[section] = data
    return created[0].region


def remove_top_level_paragraph(
    pkg: object, section: str, paragraph_index: int
) -> None:
    """Delete one section-direct ``hp:p`` that carries no structural meaning.

    Addressing matches :func:`create_bookmark_region` exactly — a section entry
    name plus the zero-based position among that section's direct ``hp:p``
    children — so a caller that computed a range with one can delete with the
    other without translating coordinates.

    Every refusal is a loud ``ValueError`` and leaves ``package.entries``
    untouched: the paragraph may not carry a field/BOOKMARK boundary control
    (removing one half of a pair destroys the pairing), may not carry the section
    or column definition, and the section must keep at least one paragraph.

    Regions survive with their names, containment and MetaTags intact; only
    positions move, and deterministically — a region entirely after the deleted
    paragraph shifts by one, a region containing it loses one from its end, and a
    region entirely before it does not move.  Any other observed change is a
    postcondition failure and nothing is committed.
    """
    if not isinstance(section, str):
        raise TypeError(f"section must be str: {type(section)!r}")
    if isinstance(paragraph_index, bool) or not isinstance(paragraph_index, int):
        raise TypeError(f"paragraph_index must be int: {type(paragraph_index)!r}")

    package = require_package(pkg)
    current = _resolve(package, require_removable=False)
    sections = _parse_sections(package)
    matches = [item for item in sections if item.entry == section]
    if len(matches) != 1:
        raise ValueError(f"HWPX section was not found: {section!r}")
    parsed = matches[0]
    paragraphs = [child for child in parsed.root if child.tag == f"{_HP}p"]
    if paragraph_index < 0 or paragraph_index >= len(paragraphs):
        raise ValueError(
            f"invalid paragraph index {paragraph_index} "
            f"for {len(paragraphs)} paragraphs"
        )
    if len(paragraphs) == 1:
        raise ValueError(f"{section}: removing the paragraph would leave none")
    target = paragraphs[paragraph_index]
    for node in target.iter():
        if not isinstance(node.tag, str):
            continue
        if local_name(node.tag) in _UNDELETABLE_LOCAL_NAMES:
            raise ValueError(
                f"{section}: paragraph {paragraph_index} carries "
                f"{local_name(node.tag)} and cannot be removed"
            )

    wanted = _topology_shape(current, include_positions=True)
    for item in current:
        region = item.region
        if region.section != section:
            continue
        value = list(wanted[_region_key(item)])
        # The refusals above guarantee the deleted index is neither bound of any
        # region, so "<" and "<=" split the three cases without overlap.
        if paragraph_index < region.start_paragraph:
            value[-2] = region.start_paragraph - 1
        if paragraph_index <= region.end_paragraph:
            value[-1] = region.end_paragraph - 1
        wanted[_region_key(item)] = tuple(value)

    parsed.root.remove(target)
    data, after = _candidate_resolution(
        package, section, parsed.root, require_removable=False
    )
    if _topology_shape(after, include_positions=True) != wanted:
        raise ValueError("top-level paragraph removal postcondition failed")
    package.entries[section] = data


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
    plan = _validate_mutable_extent(
        resolved,
        reject_whole_section=True,
        reject_section_definition=True,
    )
    removed_begins = set(plan.removed_begins)
    removed = {
        _region_key(item)
        for item in current
        if item.begin in removed_begins
    }
    protected = set(plan.protected_markers)
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
