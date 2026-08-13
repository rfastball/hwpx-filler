from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from lxml import etree

from _hwpx_structure_probe import dump_structure
from hwpxcore.bookmark_region import (
    BookmarkRegion,
    remove_bookmark_region,
    resolve_bookmark_regions,
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


def test_resolves_coincident_boundaries_and_refuses_removals_that_cut_outsiders() -> None:
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

    # Deleting the inner range would cut the container's own marker in half.
    for name, inner, outer in (
        ("G/G1-coincident-start.hwpx", "S0_SLOT", "S0_OPT_A"),
        ("G/G2-coincident-end.hwpx", "S0_OPT_B", "S0_SLOT"),
        ("G/G3-same-range.hwpx", "S0_OPT_X", "S0_SLOT"),
    ):
        pkg = _native(name)
        with pytest.raises(ValueError, match="would cut BOOKMARK markers outside it"):
            remove_bookmark_region(pkg, _region(pkg, inner))
        # The container still goes, taking what it contains with it.
        remove_bookmark_region(pkg, _region(pkg, outer))
        assert _paragraph_texts(pkg) == ["AAA"]
        begins, ends = _pairing_ids(pkg)
        assert begins == ends == set()


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
    field_end_inside = (
        _paragraph(_begin("9", "F", kind="CLICK_HERE") + "<hp:t>OUT</hp:t>")
        + _paragraph(_begin() + "<hp:t>IN</hp:t>" + _end("9"))
        + _paragraph("<hp:t>IN2</hp:t>" + _end())
        + _paragraph("<hp:t>OUT2</hp:t>")
    )
    field_begin_inside = (
        _paragraph("<hp:t>OUT</hp:t>")
        + _paragraph(_begin() + _begin("9", "F", kind="CLICK_HERE") + "<hp:t>IN</hp:t>")
        + _paragraph("<hp:t>IN2</hp:t>" + _end())
        + _paragraph("<hp:t>OUT2</hp:t>" + _end("9"))
    )
    field_encloses = (
        _paragraph(_begin("9", "F", kind="CLICK_HERE") + "<hp:t>OUT</hp:t>")
        + _paragraph(_begin() + "<hp:t>IN</hp:t>")
        + _paragraph("<hp:t>IN2</hp:t>" + _end())
        + _paragraph("<hp:t>OUT2</hp:t>" + _end("9"))
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
        (_package(field_end_inside), "field pair intersects BOOKMARK extent"),
        (_package(field_begin_inside), "field pair intersects BOOKMARK extent"),
        (_package(field_encloses), "field pair encloses BOOKMARK extent"),
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
