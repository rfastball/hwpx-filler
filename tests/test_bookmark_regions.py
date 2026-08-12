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


def test_rejects_malformed_or_unsupported_bookmark_regions_loudly() -> None:
    ordinary = _package(
        _paragraph(
            '<hp:ctrl><hp:fieldBegin name="ordinary"/></hp:ctrl>'
            "<hp:t>A</hp:t><hp:ctrl><hp:fieldEnd/></hp:ctrl>"
        )
    )
    assert resolve_bookmark_regions(ordinary) == []

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
    nested = (
        _paragraph("<hp:t>OUT</hp:t>")
        + _paragraph(_begin("1", "A") + "<hp:t>A1</hp:t>")
        + _paragraph(_begin("2", "B") + "<hp:t>B1</hp:t>")
        + _paragraph("<hp:t>B2</hp:t>" + _end("2"))
        + _paragraph("<hp:t>A2</hp:t>" + _end("1"))
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
        (_package(nested), "nested BOOKMARK regions"),
        (
            _package(
                _paragraph(_begin() + "<hp:t>A</hp:t>"),
                _paragraph("<hp:t>B</hp:t>" + _end()),
            ),
            "cross-section BOOKMARK pair",
        ),
        (_package(field_end_inside), "field pair intersects BOOKMARK extent"),
        (_package(field_begin_inside), "field pair intersects BOOKMARK extent"),
        (_package(field_encloses), "field pair encloses BOOKMARK extent"),
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
