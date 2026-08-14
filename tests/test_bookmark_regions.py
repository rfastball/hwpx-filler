from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from lxml import etree

from _hwpx_structure_probe import dump_structure
import hwpxcore.bookmark_region as bookmark_region
from hwpxcore.bookmark_region import (
    BookmarkRegion,
    append_bookmark_metatag,
    create_bookmark_region,
    remove_bookmark_region,
    remove_bookmark_metatag,
    replace_bookmark_metatag,
    resolve_bookmark_regions,
    resolve_bookmark_topology,
    unwrap_bookmark_region,
)
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxcore.text_extract import local_name

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
CORPUS = Path(__file__).parent / "corpus" / "structural_range_s0"
SECTION = "Contents/section0.xml"


def _native(name: str) -> HwpxPackage:
    return HwpxPackage.from_bytes((CORPUS / name).read_bytes())


def _paragraph_text(paragraph: etree._Element) -> str:
    return "".join(
        "".join(node.itertext())
        for node in paragraph.iter()
        if local_name(node.tag) == "t"
    )


def _paragraph_texts(pkg: HwpxPackage) -> list[str]:
    root = etree.fromstring(pkg.entries[SECTION])
    return [
        _paragraph_text(paragraph)
        for paragraph in root
        if local_name(paragraph.tag) == "p"
    ]


def _paragraphs_without_layout(pkg: HwpxPackage, wanted: set[str]) -> list[bytes]:
    root = etree.fromstring(pkg.entries[SECTION])
    kept = []
    for paragraph in root:
        if local_name(paragraph.tag) != "p" or _paragraph_text(paragraph) not in wanted:
            continue
        clone = deepcopy(paragraph)
        etree.strip_elements(clone, f"{{{HP}}}linesegarray", with_tail=False)
        kept.append(etree.tostring(clone))
    return kept


def _package(section0: str, section1: str | None = None) -> HwpxPackage:
    entries = {
        MIMETYPE_NAME: MIMETYPE_VALUE,
        SECTION: f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section0}</hs:sec>'.encode(),
    }
    if section1 is not None:
        entries["Contents/section1.xml"] = (
            f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section1}</hs:sec>'
        ).encode()
    return HwpxPackage(entries=entries, stored={MIMETYPE_NAME})


def _paragraph(content: str) -> str:
    return f"<hp:p><hp:run>{content}</hp:run></hp:p>"


def _begin(begin_id: str = "1", name: str = "A", *, kind: str = "BOOKMARK") -> str:
    return (
        f'<hp:ctrl><hp:fieldBegin id="{begin_id}" type="{kind}" '
        f'name="{name}"/></hp:ctrl>'
    )


def _end(begin_id: str = "1") -> str:
    return f'<hp:ctrl><hp:fieldEnd beginIDRef="{begin_id}"/></hp:ctrl>'


def _region(pkg: HwpxPackage, name: str) -> BookmarkRegion:
    return next(region for region in resolve_bookmark_regions(pkg) if region.name == name)


def _markers(pkg: HwpxPackage) -> list[tuple[int, str, str | None]]:
    root = etree.fromstring(pkg.entries[SECTION])
    found = []
    for index, paragraph in enumerate(
        child for child in root if local_name(child.tag) == "p"
    ):
        for node in paragraph.iter():
            tag = local_name(node.tag)
            if tag in {"fieldBegin", "fieldEnd"}:
                found.append((index, tag, node.get("name")))
    return found


def _pairing_ids(pkg: HwpxPackage) -> tuple[set[str], set[str]]:
    root = etree.fromstring(pkg.entries[SECTION])
    begins = {
        node.get("id") for node in root.iter() if local_name(node.tag) == "fieldBegin"
    }
    ends = {
        node.get("beginIDRef")
        for node in root.iter()
        if local_name(node.tag) == "fieldEnd"
    }
    return begins, ends


def _assert_clean(pkg: HwpxPackage) -> None:
    root = etree.fromstring(pkg.entries[SECTION])
    assert not any(
        local_name(node.tag) in {"p", "run"} and len(node) == 0 and not node.text
        for node in root.iter()
    )
    assert b"linesegarray" not in pkg.entries[SECTION]


def test_resolves_native_r2_r3_r4_regions_in_document_order() -> None:
    assert resolve_bookmark_regions(_native("R0-plain.hwpx")) == []

    r2 = resolve_bookmark_regions(_native("R2-block-bookmark.hwpx"))
    assert [(region.name, region.start_paragraph, region.end_paragraph) for region in r2] == [
        ("S0_BLOCK", 1, 3)
    ]

    r3 = resolve_bookmark_regions(_native("R3-table-crossing.hwpx"))
    assert [(region.name, region.start_paragraph, region.end_paragraph) for region in r3] == [
        ("S0_TABLE", 1, 3)
    ]

    r4_pkg = _native("R4-adjacent.hwpx")
    r4 = resolve_bookmark_regions(r4_pkg)
    assert [(region.name, region.start_paragraph, region.end_paragraph) for region in r4] == [
        ("S0_LEFT", 1, 1),
        ("S0_RIGHT", 2, 2),
    ]
    assert resolve_bookmark_regions(HwpxPackage.from_bytes(r4_pkg.to_bytes())) == r4


def test_creates_d6_native_bookmark_and_reparses_deterministically() -> None:
    pkg = _native("R0-plain.hwpx")
    content = _paragraph_texts(pkg)
    created = create_bookmark_region(
        pkg, SECTION, 1, 3, name="S0_GENERATED"
    )

    assert (
        created.name,
        created.start_paragraph,
        created.end_paragraph,
        created.parent,
    ) == ("S0_GENERATED", 1, 3, None)
    assert _paragraph_texts(pkg) == content
    assert pkg.to_bytes() == (CORPUS / "D6-generated-minimal.hwpx").read_bytes()
    reparsed = HwpxPackage.from_bytes(pkg.to_bytes())
    assert resolve_bookmark_regions(reparsed) == [created]

    create_bookmark_region(reparsed, SECTION, 4, 4, name="SECOND")
    assert _pairing_ids(reparsed) == (
        {"1600000001", "1600000002"},
        {"1600000001", "1600000002"},
    )


@pytest.mark.parametrize(
    ("start", "end"),
    ((2, 2), (1, 1), (3, 3), (1, 3)),
    ids=("ordinary", "coincident-start", "coincident-end", "same-span"),
)
def test_creates_nested_and_coincident_bookmarks(
    start: int, end: int
) -> None:
    pkg = _native("R0-plain.hwpx")
    content = _paragraph_texts(pkg)
    outer = create_bookmark_region(pkg, SECTION, 1, 3, name="OUTER")
    inner = create_bookmark_region(
        pkg, SECTION, start, end, name="INNER", parent=outer
    )

    regions = resolve_bookmark_regions(pkg)
    assert [(item.name, item.start_paragraph, item.end_paragraph) for item in regions] == [
        ("OUTER", 1, 3),
        ("INNER", start, end),
    ]
    assert regions[1].parent == regions[0]
    assert inner == regions[1]
    assert _paragraph_texts(pkg) == content
    assert resolve_bookmark_regions(HwpxPackage.from_bytes(pkg.to_bytes())) == regions


def test_create_bookmark_failures_leave_the_package_unchanged() -> None:
    pkg = _native("R0-plain.hwpx")
    outer = create_bookmark_region(pkg, SECTION, 1, 3, name="OUTER")
    before = dict(pkg.entries)
    with pytest.raises(ValueError, match="crossing BOOKMARK regions"):
        create_bookmark_region(pkg, SECTION, 2, 4, name="CROSSING")
    assert pkg.entries == before

    append_bookmark_metatag(pkg, outer, "changed")
    before = dict(pkg.entries)
    with pytest.raises(ValueError, match="current package snapshot"):
        create_bookmark_region(
            pkg, SECTION, 2, 2, name="STALE_PARENT", parent=outer
        )
    assert pkg.entries == before

    with pytest.raises(ValueError, match="invalid BOOKMARK paragraph range"):
        create_bookmark_region(pkg, SECTION, -1, 2, name="INVALID")
    assert pkg.entries == before

    fresh = _region(pkg, "OUTER")
    invalid_calls = (
        lambda: create_bookmark_region(pkg, 1, 1, 1, name="X"),
        lambda: create_bookmark_region(pkg, SECTION, True, 1, name="X"),
        lambda: create_bookmark_region(pkg, SECTION, 1, 1, name=1),
        lambda: create_bookmark_region(pkg, SECTION, 1, 1, name=" "),
        lambda: create_bookmark_region(
            pkg, SECTION, 1, 1, name="X", parent=object()
        ),
        lambda: create_bookmark_region(
            pkg, "Contents/section1.xml", 1, 1, name="X", parent=fresh
        ),
        lambda: create_bookmark_region(
            pkg, SECTION, 0, 0, name="X", parent=fresh
        ),
        lambda: create_bookmark_region(pkg, "missing.xml", 0, 0, name="X"),
    )
    for call in invalid_calls:
        with pytest.raises((TypeError, ValueError)):
            call()
        assert pkg.entries == before

    no_run = _package(
        "<hp:p><hp:t>not in a run</hp:t></hp:p>"
        + _paragraph("<hp:t>OUT</hp:t>")
    )
    no_run_before = dict(no_run.entries)
    with pytest.raises(ValueError, match="must contain a direct native hp:run"):
        create_bookmark_region(no_run, SECTION, 0, 0, name="X")
    assert no_run.entries == no_run_before

    reparent = _native("R0-plain.hwpx")
    create_bookmark_region(reparent, SECTION, 1, 1, name="EXISTING")
    reparent_before = dict(reparent.entries)
    with pytest.raises(ValueError, match="changed existing native topology"):
        create_bookmark_region(reparent, SECTION, 1, 3, name="NEW_TOP")
    assert reparent.entries == reparent_before


def test_mutation_postcondition_failures_never_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = bookmark_region._candidate_resolution

    def lose_topology(*args, **kwargs):
        data, _after = original(*args, **kwargs)
        return data, []

    monkeypatch.setattr(bookmark_region, "_candidate_resolution", lose_topology)
    created = _native("R0-plain.hwpx")
    tagged = _native("R2-block-bookmark.hwpx")
    unwrapped = _native("R5-nested.hwpx")
    removed = _native("R4-adjacent.hwpx")
    cases = (
        (
            created,
            lambda: create_bookmark_region(
                created, SECTION, 1, 3, name="POSTCONDITION"
            ),
        ),
        (
            tagged,
            lambda: append_bookmark_metatag(
                tagged, _region(tagged, "S0_BLOCK"), "payload"
            ),
        ),
        (
            unwrapped,
            lambda: unwrap_bookmark_region(
                unwrapped, _region(unwrapped, "S0_OPT_A")
            ),
        ),
        (
            removed,
            lambda: remove_bookmark_region(
                removed, _region(removed, "S0_LEFT")
            ),
        ),
    )
    for package, mutate in cases:
        before = dict(package.entries)
        with pytest.raises(ValueError):
            mutate()
        assert package.entries == before


def test_bookmark_metatags_are_opaque_ordered_and_mutable() -> None:
    pkg = _package(
        _paragraph(
            '<hp:ctrl><hp:fieldBegin id="1" type="BOOKMARK" name="A" '
            'metaTag="legacy"><hp:parameters/><hp:metaTag>{"future": [1, 2]}</hp:metaTag>'
            "<hp:metaTag>not-json</hp:metaTag></hp:fieldBegin></hp:ctrl>"
            "<hp:t>A</hp:t>"
            + _end()
        )
        + _paragraph("<hp:t>OUT</hp:t>")
    )
    region = resolve_bookmark_regions(pkg)[0]
    assert region.meta_tags == ('{"future": [1, 2]}', "not-json")
    assert region.meta_tag_attribute == "legacy"

    appended = '{"한글": "그대로"}'
    append_bookmark_metatag(pkg, region, appended)
    with pytest.raises(ValueError, match="current package snapshot"):
        append_bookmark_metatag(pkg, region, "stale")

    reparsed = HwpxPackage.from_bytes(pkg.to_bytes())
    current = resolve_bookmark_regions(reparsed)[0]
    assert current.meta_tags == (*region.meta_tags, appended)
    assert current.meta_tag_attribute == "legacy"

    replace_bookmark_metatag(reparsed, current, 1, "replacement")
    with pytest.raises(ValueError, match="current package snapshot"):
        remove_bookmark_metatag(reparsed, current, 0)
    current = resolve_bookmark_regions(reparsed)[0]
    assert current.meta_tags == ('{"future": [1, 2]}', "replacement", appended)
    remove_bookmark_metatag(reparsed, current, 0)
    current = resolve_bookmark_regions(reparsed)[0]
    assert current.meta_tags == ("replacement", appended)
    assert current.meta_tag_attribute == "legacy"
    assert resolve_bookmark_regions(HwpxPackage.from_bytes(reparsed.to_bytes())) == [
        current
    ]

    before = dict(reparsed.entries)
    with pytest.raises(ValueError, match="out of range"):
        replace_bookmark_metatag(reparsed, current, 9, "missing")
    with pytest.raises(ValueError, match="non-negative"):
        remove_bookmark_metatag(reparsed, current, -1)
    with pytest.raises(ValueError, match="out of range"):
        remove_bookmark_metatag(reparsed, current, 9)
    with pytest.raises(TypeError, match="index must be int"):
        remove_bookmark_metatag(reparsed, current, True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="payload must be str"):
        replace_bookmark_metatag(reparsed, current, 0, 1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be BookmarkRegion"):
        unwrap_bookmark_region(reparsed, object())  # type: ignore[arg-type]
    assert reparsed.entries == before
    with pytest.raises(TypeError, match="payload must be str"):
        append_bookmark_metatag(reparsed, current, 1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("filename", "target", "remaining", "parents"),
    (
        (
            "R5-nested.hwpx",
            "S0_OPT_A",
            ("S0_SLOT", "S0_OPT_B"),
            (None, "S0_SLOT"),
        ),
        (
            "R5-nested.hwpx",
            "S0_SLOT",
            ("S0_OPT_A", "S0_OPT_B"),
            (None, None),
        ),
        (
            "G/G1-coincident-start.hwpx",
            "S0_SLOT",
            ("S0_OPT_A",),
            (None,),
        ),
        (
            "G/G2-coincident-end.hwpx",
            "S0_OPT_B",
            ("S0_SLOT",),
            (None,),
        ),
        (
            "G/G3-same-range.hwpx",
            "S0_OPT_X",
            ("S0_SLOT",),
            (None,),
        ),
    ),
)
def test_unwrap_preserves_content_and_non_target_topology(
    filename: str,
    target: str,
    remaining: tuple[str, ...],
    parents: tuple[str | None, ...],
) -> None:
    pkg = _native(filename)
    content = _paragraph_texts(pkg)
    stale = _region(pkg, target)
    unwrap_bookmark_region(pkg, stale)

    regions = resolve_bookmark_topology(pkg)
    assert tuple(item.name for item in regions) == remaining
    assert tuple(item.parent.name if item.parent else None for item in regions) == parents
    assert _paragraph_texts(pkg) == content
    assert resolve_bookmark_topology(HwpxPackage.from_bytes(pkg.to_bytes())) == regions

    before = dict(pkg.entries)
    with pytest.raises(ValueError, match="current package snapshot"):
        unwrap_bookmark_region(pkg, stale)
    assert pkg.entries == before


def test_unwrap_matches_hancom_marker_removal_structure() -> None:
    for target, native in (
        ("S0_OPT_A", "F/F5-remove-inner-bookmark.hwpx"),
        ("S0_SLOT", "F/F6-remove-outer-bookmark.hwpx"),
    ):
        pkg = _native("R5-nested.hwpx")
        unwrap_bookmark_region(pkg, _region(pkg, target))
        assert dump_structure(pkg) == dump_structure(_native(native))


def test_removes_native_r2_and_table_crossing_r3_without_collateral_damage() -> None:
    cases = (
        ("R2-block-bookmark.hwpx", "S0_BLOCK", set()),
        ("R3-table-crossing.hwpx", "S0_TABLE", {"tbl", "tr", "tc", "subList"}),
    )
    for filename, bookmark, removed_containers in cases:
        pkg = _native(filename)
        entries_before = dict(pkg.entries)
        outside_before = _paragraphs_without_layout(pkg, {"AAA", "EEE"})

        remove_bookmark_region(pkg, _region(pkg, bookmark))
        assert _paragraph_texts(pkg) == ["AAA", "EEE"]
        assert _paragraphs_without_layout(pkg, {"AAA", "EEE"}) == outside_before
        assert all(
            data == pkg.entries[entry]
            for entry, data in entries_before.items()
            if entry != SECTION
        )
        root = etree.fromstring(pkg.entries[SECTION])
        tags = {local_name(node.tag) for node in root.iter()}
        assert not {"fieldBegin", "fieldEnd"} & tags
        assert not removed_containers & tags
        _assert_clean(pkg)

        reparsed = HwpxPackage.from_bytes(pkg.to_bytes())
        assert resolve_bookmark_regions(reparsed) == []
        assert dump_structure(reparsed) == dump_structure(pkg)

        repeated = _native(filename)
        remove_bookmark_region(repeated, _region(repeated, bookmark))
        assert repeated.to_bytes() == pkg.to_bytes()


def test_removes_each_native_r4_region_without_touching_its_neighbor() -> None:
    cases = (
        ("S0_LEFT", "S0_RIGHT", "RIGHT"),
        ("S0_RIGHT", "S0_LEFT", "LEFT"),
    )
    for removed_name, survivor_name, survivor_text in cases:
        pkg = _native("R4-adjacent.hwpx")
        entries_before = dict(pkg.entries)
        kept = {"AAA", survivor_text, "EEE"}
        kept_before = _paragraphs_without_layout(pkg, kept)
        removed = _region(pkg, removed_name)

        remove_bookmark_region(pkg, removed)
        assert _paragraph_texts(pkg) == ["AAA", survivor_text, "EEE"]
        assert _paragraphs_without_layout(pkg, kept) == kept_before
        assert [region.name for region in resolve_bookmark_regions(pkg)] == [survivor_name]
        assert all(
            data == pkg.entries[entry]
            for entry, data in entries_before.items()
            if entry != SECTION
        )
        _assert_clean(pkg)
        with pytest.raises(ValueError, match="current package snapshot"):
            remove_bookmark_region(pkg, removed)

        reparsed = HwpxPackage.from_bytes(pkg.to_bytes())
        assert resolve_bookmark_regions(reparsed)[0].name == survivor_name
        assert dump_structure(reparsed) == dump_structure(pkg)

    stale_pkg = _native("R2-block-bookmark.hwpx")
    stale = _region(stale_pkg, "S0_BLOCK")
    stale_pkg.entries[SECTION] = stale_pkg.entries[SECTION].replace(b"CCC", b"CXC")
    with pytest.raises(ValueError, match="current package snapshot"):
        remove_bookmark_region(stale_pkg, stale)


def test_native_r4_removal_is_composable_after_reparse_in_both_orders() -> None:
    final_structures = []
    for first, second in (("S0_LEFT", "S0_RIGHT"), ("S0_RIGHT", "S0_LEFT")):
        pkg = _native("R4-adjacent.hwpx")
        entries_before = dict(pkg.entries)
        outside_before = _paragraphs_without_layout(pkg, {"AAA", "EEE"})

        remove_bookmark_region(pkg, _region(pkg, first))
        intermediate = HwpxPackage.from_bytes(pkg.to_bytes())
        assert [region.name for region in resolve_bookmark_regions(intermediate)] == [second]
        remove_bookmark_region(intermediate, _region(intermediate, second))

        assert _paragraph_texts(intermediate) == ["AAA", "EEE"]
        assert resolve_bookmark_regions(intermediate) == []
        assert _paragraphs_without_layout(intermediate, {"AAA", "EEE"}) == outside_before
        assert all(
            data == intermediate.entries[entry]
            for entry, data in entries_before.items()
            if entry != SECTION
        )
        _assert_clean(intermediate)

        final = HwpxPackage.from_bytes(intermediate.to_bytes())
        final_probe = dump_structure(final)
        assert final_probe == dump_structure(intermediate)
        final_structures.append((final.entries[SECTION], final_probe))

    assert final_structures[0] == final_structures[1]


def test_removes_nested_regions_exactly_as_hancom_deletes_the_same_range() -> None:
    """S0-F: our paragraph-range removal reproduces Hancom's own deletion."""
    cases = (
        ("S0_OPT_A", "F/F1-delete-inner-paragraph.hwpx"),
        ("S0_SLOT", "F/F2-delete-outer-range.hwpx"),
    )
    for target, native in cases:
        pkg = _native("R5-nested.hwpx")
        remove_bookmark_region(pkg, _region(pkg, target))
        hancom = _native(native)

        assert _paragraph_texts(pkg) == _paragraph_texts(hancom)
        assert _markers(pkg) == _markers(hancom)
        assert [
            (region.name, region.start_paragraph, region.end_paragraph,
             region.parent.name if region.parent else None)
            for region in resolve_bookmark_regions(pkg)
        ] == [
            (region.name, region.start_paragraph, region.end_paragraph,
             region.parent.name if region.parent else None)
            for region in resolve_bookmark_regions(hancom)
        ]
        _assert_clean(pkg)
        assert dump_structure(HwpxPackage.from_bytes(pkg.to_bytes())) == dump_structure(pkg)

    # Hancom never leaves a half pair behind, whichever paragraph is deleted.
    for name in (
        "F/F1-delete-inner-paragraph.hwpx",
        "F/F2-delete-outer-range.hwpx",
        "F/F3-delete-outer-start.hwpx",
        "F/F4-delete-outer-end.hwpx",
        "F/F5-remove-inner-bookmark.hwpx",
        "F/F6-remove-outer-bookmark.hwpx",
    ):
        begins, ends = _pairing_ids(_native(name))
        assert begins == ends, name

    # Deleting only the container's boundary paragraph promotes its contents.
    for name in ("F/F3-delete-outer-start.hwpx", "F/F4-delete-outer-end.hwpx",
                 "F/F6-remove-outer-bookmark.hwpx"):
        assert [
            (region.name, region.parent) for region in resolve_bookmark_regions(_native(name))
        ] == [("S0_OPT_A", None), ("S0_OPT_B", None)], name


def test_resolves_and_removes_coincident_inner_regions_without_cutting_parent() -> None:
    """S0-G: a region may share boundary paragraphs with the one containing it."""
    shape = lambda items: [  # noqa: E731 - local projection, not an API
        (region.name, region.start_paragraph, region.end_paragraph,
         region.parent.name if region.parent else None)
        for region in items
    ]
    # In G1 the outer bookmark is the one named S0_OPT_A; names are labels, not
    # identity, and the sample was authored with them the other way round.
    assert shape(resolve_bookmark_regions(_native("G/G1-coincident-start.hwpx"))) == [
        ("S0_OPT_A", 1, 4, None),
        ("S0_SLOT", 1, 1, "S0_OPT_A"),
    ]
    assert shape(resolve_bookmark_regions(_native("G/G1-resaved.hwpx"))) == [
        ("S0_OPT_A", 1, 4, None),
        ("S0_SLOT", 1, 1, "S0_OPT_A"),
    ]
    assert shape(resolve_bookmark_regions(_native("G/G2-coincident-end.hwpx"))) == [
        ("S0_SLOT", 1, 4, None),
        ("S0_OPT_B", 4, 4, "S0_SLOT"),
    ]
    # Identical paragraph spans: only document order says which one contains which.
    assert shape(resolve_bookmark_regions(_native("G/G3-same-range.hwpx"))) == [
        ("S0_SLOT", 1, 4, None),
        ("S0_OPT_X", 1, 4, "S0_SLOT"),
    ]

    for name, inner, outer, texts in (
        (
            "G/G1-coincident-start.hwpx",
            "S0_SLOT",
            "S0_OPT_A",
            ["AAA", "", "CCC", "DDD", "EEE"],
        ),
        (
            "G/G2-coincident-end.hwpx",
            "S0_OPT_B",
            "S0_SLOT",
            ["AAA", "BBB", "CCC", "DDD", ""],
        ),
        (
            "G/G3-same-range.hwpx",
            "S0_OPT_X",
            "S0_SLOT",
            ["AAA", "", ""],
        ),
    ):
        pkg = _native(name)
        remove_bookmark_region(pkg, _region(pkg, inner))
        assert _paragraph_texts(pkg) == texts
        assert [item.name for item in resolve_bookmark_regions(pkg)] == [outer]
        begins, ends = _pairing_ids(pkg)
        assert begins == ends and len(begins) == 1
        reparsed = HwpxPackage.from_bytes(pkg.to_bytes())
        assert [item.name for item in resolve_bookmark_regions(reparsed)] == [outer]

        complete = _native(name)
        remove_bookmark_region(complete, _region(complete, outer))
        assert _paragraph_texts(complete) == ["AAA"]
        assert _pairing_ids(complete) == (set(), set())


def test_content_removal_still_refuses_unrelated_boundary_markers_atomically() -> None:
    pkg = _package(
        _paragraph("<hp:t>OUT</hp:t>")
        + _paragraph(_begin("1", "A") + "<hp:t>A</hp:t>")
        + _paragraph(_end("1") + _begin("2", "B"))
        + _paragraph("<hp:t>B</hp:t>" + _end("2"))
        + _paragraph("<hp:t>OUT2</hp:t>")
    )
    before = dict(pkg.entries)
    with pytest.raises(ValueError, match="would cut BOOKMARK markers outside it"):
        remove_bookmark_region(pkg, _region(pkg, "A"))
    assert pkg.entries == before

    section_definition = _native("R0-plain.hwpx")
    outer = create_bookmark_region(
        section_definition, SECTION, 0, 1, name="OUTER"
    )
    inner = create_bookmark_region(
        section_definition, SECTION, 0, 1, name="INNER", parent=outer
    )
    before = dict(section_definition.entries)
    with pytest.raises(ValueError, match="would delete section definition"):
        remove_bookmark_region(section_definition, inner)
    assert section_definition.entries == before

    ordinary = _native("R0-plain.hwpx")
    top = create_bookmark_region(ordinary, SECTION, 0, 0, name="TOP")
    before = dict(ordinary.entries)
    with pytest.raises(ValueError, match="would delete section definition"):
        remove_bookmark_region(ordinary, top)
    assert ordinary.entries == before


def test_hancom_never_stores_crossing_so_only_authored_files_can_carry_it() -> None:
    """S0-H: asking Hancom for crossing ranges silently yields nesting instead."""
    shape = lambda items: [  # noqa: E731 - local projection, not an API
        (region.name, region.start_paragraph, region.end_paragraph,
         region.parent.name if region.parent else None)
        for region in items
    ]
    # Authored as S0_LEFT=BBB..DDD and S0_RIGHT=CCC..EEE, which would cross.
    # Hancom kept the end markers where they fell but swapped which begin they
    # reference, so LEFT swallowed EEE and RIGHT gave it up. No warning was shown.
    nested_instead = [("S0_LEFT", 1, 4, None), ("S0_RIGHT", 2, 3, "S0_LEFT")]
    for name in ("H/H1-crossing.hwpx", "H/H1-resaved.hwpx", "H/H2-reverse-order.hwpx"):
        assert shape(resolve_bookmark_regions(_native(name))) == nested_instead, name

    # Deleting the shared paragraphs drops the inner range whole, never a half pair.
    assert shape(resolve_bookmark_regions(_native("H/H3-overlap-deleted.hwpx"))) == [
        ("S0_LEFT", 1, 2, None)
    ]
    for name in ("H/H1-crossing.hwpx", "H/H2-reverse-order.hwpx",
                 "H/H3-overlap-deleted.hwpx"):
        begins, ends = _pairing_ids(_native(name))
        assert begins == ends, name


def test_resolves_nested_regions_with_containment() -> None:
    pkg = _native("R5-nested.hwpx")
    regions = resolve_bookmark_regions(pkg)
    shape = lambda items: [  # noqa: E731 - local projection, not an API
        (region.name, region.start_paragraph, region.end_paragraph,
         region.parent.name if region.parent else None)
        for region in items
    ]
    assert shape(regions) == [
        ("S0_SLOT", 1, 4, None),
        ("S0_OPT_A", 2, 2, "S0_SLOT"),
        ("S0_OPT_B", 3, 3, "S0_SLOT"),
    ]
    assert regions[1].parent == regions[0] and regions[2].parent == regions[0]
    assert shape(resolve_bookmark_regions(_native("R5-nested-resaved.hwpx"))) == shape(regions)

    depth = _package(
        _paragraph("<hp:t>OUT</hp:t>")
        + _paragraph(_begin("1", "OUTER") + "<hp:t>A</hp:t>")
        + _paragraph(_begin("2", "MID") + "<hp:t>B</hp:t>")
        + _paragraph(_begin("3", "INNER") + "<hp:t>C</hp:t>" + _end("3"))
        + _paragraph("<hp:t>D</hp:t>" + _end("2"))
        + _paragraph("<hp:t>E</hp:t>" + _end("1"))
        + _paragraph("<hp:t>OUT2</hp:t>")
    )
    assert shape(resolve_bookmark_regions(depth)) == [
        ("OUTER", 1, 5, None),
        ("MID", 2, 4, "OUTER"),
        ("INNER", 3, 3, "MID"),
    ]

    # Only BOOKMARK markers are exempt from the boundary payload rule: real text
    # beside a boundary still makes the range partial.
    partial = _package(
        _paragraph(
            _begin("1", "OUTER")
            + "<hp:t>prefix</hp:t>"
            + _begin("2", "INNER")
            + "<hp:t>A</hp:t>"
            + _end("2")
            + _end("1")
        )
        + _paragraph("<hp:t>OUT</hp:t>")
    )
    assert [region.name for region in resolve_bookmark_topology(partial)] == [
        "OUTER",
        "INNER",
    ]
    with pytest.raises(ValueError, match="partial-paragraph BOOKMARK begin"):
        resolve_bookmark_regions(partial)

    # A region that opens after its predecessor closed is a sibling, not a child.
    siblings = _package(
        _paragraph(_begin("1", "A") + "<hp:t>A</hp:t>")
        + _paragraph(_begin("2", "A1") + "<hp:t>B</hp:t>" + _end("2"))
        + _paragraph("<hp:t>C</hp:t>" + _end("1"))
        + _paragraph(_begin("3", "B") + "<hp:t>D</hp:t>" + _end("3"))
        + _paragraph("<hp:t>OUT</hp:t>")
    )
    assert shape(resolve_bookmark_regions(siblings)) == [
        ("A", 0, 2, None),
        ("A1", 1, 1, "A"),
        ("B", 3, 3, None),
    ]
    remove_bookmark_region(siblings, _region(siblings, "B"))
    assert _paragraph_texts(siblings) == ["A", "B", "C", "OUT"]


def test_bookmark_removal_accepts_idless_field_wholly_inside_target() -> None:
    ordinary = (
        '<hp:ctrl><hp:fieldBegin type="CLICK_HERE" name="ordinary"/></hp:ctrl>'
        "<hp:t>FIELD</hp:t><hp:ctrl><hp:fieldEnd/></hp:ctrl>"
    )
    pkg = _package(
        _paragraph(_begin() + ordinary + _end())
        + _paragraph("<hp:t>OUT</hp:t>")
    )

    target = _region(pkg, "A")
    remove_bookmark_region(pkg, target)

    assert _paragraph_texts(pkg) == ["OUT"]


def test_bookmark_removal_rejects_unusable_field_pairing_without_mutation() -> None:
    pkg = _package(
        _paragraph(_begin() + "<hp:t>IN</hp:t>" + _end())
        + _paragraph("<hp:ctrl><hp:fieldEnd/></hp:ctrl><hp:t>OUT</hp:t>")
    )
    before = dict(pkg.entries)

    with pytest.raises(ValueError, match="orphan-end"):
        resolve_bookmark_regions(pkg)
    target = next(region for region in resolve_bookmark_topology(pkg) if region.name == "A")
    with pytest.raises(ValueError, match="orphan-end"):
        remove_bookmark_region(pkg, target)
    assert pkg.entries == before


def test_rejects_malformed_or_unsupported_bookmark_regions_loudly() -> None:
    ordinary = _package(
        _paragraph(
            '<hp:ctrl><hp:fieldBegin name="ordinary"/></hp:ctrl>'
            "<hp:t>A</hp:t><hp:ctrl><hp:fieldEnd/></hp:ctrl>"
        )
    )
    assert resolve_bookmark_regions(ordinary) == []

    reused_id = _package(
        _paragraph(_begin("7", "A") + "<hp:t>A</hp:t>" + _end("7"))
        + _paragraph("<hp:t>OUT</hp:t>"),
        _paragraph(_begin("7", "B") + "<hp:t>B</hp:t>" + _end("7"))
        + _paragraph("<hp:t>OUT</hp:t>"),
    )
    assert [region.name for region in resolve_bookmark_regions(reused_id)] == ["A", "B"]

    cross_section_id_collision = _package(
        _paragraph(_begin("7", "FIELD", kind="CLICK_HERE") + "<hp:t>OUT</hp:t>")
        + _paragraph(_begin("1", "TARGET") + "<hp:t>IN</hp:t>")
        + _paragraph("<hp:t>IN2</hp:t>" + _end("1"))
        + _paragraph("<hp:t>OUT2</hp:t>" + _end("7"))
        + _paragraph("<hp:t>TAIL</hp:t>"),
        _paragraph(_begin("7", "OTHER") + "<hp:t>OTHER</hp:t>" + _end("7"))
        + _paragraph("<hp:t>TAIL</hp:t>"),
    )
    before = dict(cross_section_id_collision.entries)
    target = next(
        region
        for region in resolve_bookmark_topology(cross_section_id_collision)
        if region.name == "TARGET"
    )
    with pytest.raises(ValueError, match="paragraph-crossing"):
        remove_bookmark_region(cross_section_id_collision, target)
    assert cross_section_id_collision.entries == before

    nested_boundary = (
        "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>"
        + _paragraph(_begin() + "<hp:t>A</hp:t>" + _end())
        + "</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
    )
    crossing = (
        _paragraph("<hp:t>OUT</hp:t>")
        + _paragraph(_begin("1", "A") + "<hp:t>A1</hp:t>")
        + _paragraph(_begin("2", "B") + "<hp:t>B1</hp:t>")
        + _paragraph("<hp:t>A2</hp:t>" + _end("1"))
        + _paragraph("<hp:t>B2</hp:t>" + _end("2"))
        + _paragraph("<hp:t>OUT2</hp:t>")
    )
    markpen_crosses = (
        _paragraph('<hp:t><hp:markpenBegin color="#ffff00"/>OUT</hp:t>')
        + _paragraph(_begin() + "<hp:t>IN<hp:markpenEnd/></hp:t>")
        + _paragraph("<hp:t>IN2</hp:t>" + _end())
        + _paragraph("<hp:t>OUT2</hp:t>")
    )
    insert_crosses = (
        _paragraph("<hp:t>OUT</hp:t>")
        + _paragraph(_begin() + '<hp:t>IN<hp:insertBegin Id="2" TcId="3"/></hp:t>')
        + _paragraph("<hp:t>IN2</hp:t>" + _end())
        + _paragraph('<hp:t>OUT2<hp:insertEnd Id="2" TcId="3"/></hp:t>')
    )
    delete_encloses = (
        _paragraph('<hp:t><hp:deleteBegin Id="4" TcId="5"/>OUT</hp:t>')
        + _paragraph(_begin() + "<hp:t>IN</hp:t>")
        + _paragraph("<hp:t>IN2</hp:t>" + _end())
        + _paragraph('<hp:t>OUT2<hp:deleteEnd Id="4" TcId="5"/></hp:t>')
    )
    cases = (
        (
            _package(_paragraph('<hp:ctrl><hp:fieldBegin type="BOOKMARK"/></hp:ctrl>')),
            "fieldBegin has no id",
        ),
        (
            _package(_paragraph(_begin()) + _paragraph(_begin()) + _paragraph(_end())),
            "duplicate fieldBegin",
        ),
        (
            _package(_paragraph(_begin()) + _paragraph(_end()) + _paragraph(_end())),
            "ambiguous BOOKMARK fieldEnd",
        ),
        (_package(_paragraph(_begin())), "has no fieldEnd"),
        (_package(_paragraph(_end() + _begin())), "end precedes begin"),
        (
            _package(
                _paragraph(
                    "<hp:t>prefix</hp:t>"
                    + _begin()
                    + "<hp:t>inside</hp:t>"
                    + _end()
                )
            ),
            "partial-paragraph BOOKMARK begin",
        ),
        (
            _package(
                _paragraph(
                    _begin()
                    + "<hp:t>inside</hp:t>"
                    + _end()
                    + "<hp:t>suffix</hp:t>"
                )
            ),
            "partial-paragraph BOOKMARK end",
        ),
        (_package(nested_boundary), "not native ctrl/run/top-level-p"),
        (
            _package(
                '<hp:p><hp:run><hp:fieldBegin id="1" type="BOOKMARK" '
                'name="A"/><hp:t>A</hp:t><hp:fieldEnd beginIDRef="1"/>'
                "</hp:run></hp:p>"
                + _paragraph("<hp:t>OUT</hp:t>")
            ),
            "not native ctrl/run/top-level-p",
        ),
        (
            _package(
                _paragraph(_begin() + "<hp:t>A</hp:t>")
                + "<hp:foo/>"
                + _paragraph("<hp:t>B</hp:t>" + _end())
            ),
            "non-paragraph section child",
        ),
        (_package(crossing), "crossing BOOKMARK regions"),
        (
            _package(
                _paragraph(_begin() + "<hp:t>A</hp:t>"),
                _paragraph("<hp:t>B</hp:t>" + _end()),
            ),
            "cross-section BOOKMARK",
        ),
        (
            _package(
                _paragraph(_begin() + "<hp:t>A</hp:t>" + _end())
                + _paragraph("<hp:t>OUT</hp:t>"),
                _paragraph(_end()) + _paragraph("<hp:t>OUT</hp:t>"),
            ),
            "cross-section BOOKMARK end collision",
        ),
        (_package(markpen_crosses), "markpenBegin/markpenEnd range intersects"),
        (_package(insert_crosses), "insertBegin/insertEnd range intersects"),
        (_package(delete_encloses), "deleteBegin/deleteEnd range intersects"),
        (
            _package(
                '<x:p xmlns:x="urn:s0-foreign"><x:run><x:ctrl>'
                '<x:fieldBegin id="1" type="BOOKMARK" name="A"/>'
                "</x:ctrl><x:t>A</x:t><x:ctrl>"
                '<x:fieldEnd beginIDRef="1"/></x:ctrl></x:run></x:p>'
                + _paragraph("<hp:t>OUT</hp:t>")
            ),
            "non-native namespace",
        ),
        (
            _package(
                _paragraph(
                    '<hp:ctrl xmlns:x="urn:s0-foreign"><hp:fieldBegin id="1" '
                    'type="BOOKMARK" name="A"><x:metaTag>{}</x:metaTag>'
                    "</hp:fieldBegin></hp:ctrl><hp:t>A</hp:t>" + _end()
                )
                + _paragraph("<hp:t>OUT</hp:t>")
            ),
            "metaTag uses a non-native namespace",
        ),
        (
            _package(
                _paragraph(
                    '<hp:ctrl><hp:fieldBegin id="1" type="BOOKMARK" name="A">'
                    "<hp:metaTag><hp:t>nested</hp:t></hp:metaTag>"
                    "</hp:fieldBegin></hp:ctrl><hp:t>A</hp:t>" + _end()
                )
                + _paragraph("<hp:t>OUT</hp:t>")
            ),
            "hp:metaTag must contain text only",
        ),
        (
            _package(
                '<hp:p xmlns:x="urn:s0-foreign"><hp:run><x:ctrl>'
                + _begin()
                + "</x:ctrl><hp:t>A</hp:t>"
                + _end()
                + "</hp:run></hp:p>"
                + _paragraph("<hp:t>OUT</hp:t>")
            ),
            "not native ctrl/run/top-level-p",
        ),
        (
            _package(
                _paragraph(_begin() + "<hp:t>A</hp:t>")
                + '<x:p xmlns:x="urn:s0-foreign"><x:run><x:t>X</x:t></x:run></x:p>'
                + _paragraph("<hp:t>B</hp:t>" + _end())
                + _paragraph("<hp:t>OUT</hp:t>")
            ),
            "non-paragraph section child",
        ),
        (
            _package(
                _paragraph(_begin() + "<hp:t>A</hp:t>")
                + _paragraph("<hp:t>B</hp:t>" + _end())
            ),
            "would leave no paragraph",
        ),
    )
    for pkg, message in cases:
        with pytest.raises(ValueError, match=message):
            resolve_bookmark_regions(pkg)
