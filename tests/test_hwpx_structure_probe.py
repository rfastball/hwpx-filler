from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lxml import etree

from _hwpx_bookmark_creation_spike import (
    BOOKMARK_NAME,
    PAIRING_ID,
    add_minimal_bookmark,
)
from _hwpx_structure_probe import dump_structure
from hwpxcore.bookmark_region import resolve_bookmark_regions
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxcore.text_extract import local_name

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
NATIVE_CORPUS = Path(__file__).parent / "corpus" / "structural_range_s0"


def _package() -> HwpxPackage:
    section0 = f"""<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">
  <hp:p id="10"><hp:run charPrIDRef="2">
    <hp:t>AAA<hp:markpenBegin color="#ffff00"/>BBB</hp:t>
    <hp:ctrl><hp:bookmark name="point-A"/></hp:ctrl>
    <hp:ctrl><hp:hiddenComment id="note-1"/></hp:ctrl>
    <hp:ctrl><hp:fieldBegin name="field" id="7"><hp:metaTag>{{"k":1}}</hp:metaTag></hp:fieldBegin></hp:ctrl>
  </hp:run><hp:run><hp:t>CCC</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="7"/></hp:ctrl></hp:run>
  <hp:run><hp:tbl id="9"><hp:tr><hp:tc><hp:subList><hp:p id="11"><hp:run><hp:t>cell</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run>
  </hp:p>
</hs:sec>""".encode()
    section1 = f"""<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">
  <hp:p id="20"><hp:run><hp:t>later</hp:t></hp:run></hp:p>
</hs:sec>""".encode()
    return HwpxPackage(
        entries={
            MIMETYPE_NAME: MIMETYPE_VALUE,
            "Contents/section1.xml": section1,
            "Contents/section0.xml": section0,
        },
        stored={MIMETYPE_NAME},
    )


def test_probe_reports_positions_containment_and_controls_without_range_inference() -> None:
    dumped = dump_structure(_package())
    records = [json.loads(line) for line in dumped.splitlines()]

    assert [(r["section"], r["entry"]) for r in records if r["kind"] == "section"] == [
        (0, "Contents/section0.xml"),
        (1, "Contents/section1.xml"),
    ]
    paragraphs = [r for r in records if r["kind"] == "paragraph"]
    assert [(r["section"], r["paragraph"], r["id"]) for r in paragraphs] == [
        (0, 0, "10"),
        (0, 1, "11"),
        (1, 0, "20"),
    ]
    assert paragraphs[1]["parent"].endswith("tbl[0]/tr[0]/tc[0]/subList[0]")

    runs = [r for r in records if r["kind"] == "run" and r["section"] == 0]
    assert [(r["paragraph"], r["run"], r["text"]) for r in runs] == [
        (0, 0, "AAABBB"),
        (0, 1, "CCC"),
        (0, 2, ""),
        (1, 0, "cell"),
    ]
    controls = [r for r in records if r["kind"] == "control"]
    by_tag = {r["tag"]: r for r in controls if r["tag"] != "ctrl"}
    assert by_tag["bookmark"]["attrs"] == {"name": "point-A"}
    assert by_tag["hiddenComment"]["attrs"] == {"id": "note-1"}
    assert by_tag["fieldEnd"]["attrs"] == {"beginIDRef": "7"}
    assert by_tag["metaTag"]["value"] == '{"k":1}'
    assert by_tag["markpenBegin"]["role"] == "markpenBegin"
    assert by_tag["markpenBegin"]["child_index"] == 0
    assert any(r["kind"] == "container" and r["tag"] == "tbl" for r in records)
    assert "range" not in dumped.lower()


def test_probe_is_stable_after_package_serialize_reparse() -> None:
    pkg = _package()
    before = dump_structure(pkg)
    assert dump_structure(pkg) == before
    assert dump_structure(HwpxPackage.from_bytes(pkg.to_bytes())) == before


def test_native_bookmark_encodings_and_durability_observations() -> None:
    def records(name: str) -> list[dict[str, Any]]:
        pkg = HwpxPackage.from_bytes((NATIVE_CORPUS / name).read_bytes())
        return [json.loads(line) for line in dump_structure(pkg).splitlines()]

    def controls(name: str) -> list[dict[str, Any]]:
        return [record for record in records(name) if record["kind"] == "control"]

    assert not any(
        record["tag"] in {"bookmark", "fieldBegin", "fieldEnd"}
        for record in controls("R0-plain.hwpx")
    )

    point = controls("R1-point-bookmark.hwpx")
    bookmark = next(record for record in point if record["tag"] == "bookmark")
    assert (bookmark["attrs"], bookmark["paragraph"], bookmark["run"]) == (
        {"name": "S0_POINT"},
        2,
        0,
    )

    block = controls("R2-block-bookmark.hwpx")
    assert not any(record["tag"] == "bookmark" for record in block)
    begin = next(record for record in block if record["tag"] == "fieldBegin")
    end = next(record for record in block if record["tag"] == "fieldEnd")
    assert (begin["attrs"]["type"], begin["attrs"]["name"], begin["paragraph"]) == (
        "BOOKMARK",
        "S0_BLOCK",
        1,
    )
    assert end["attrs"]["beginIDRef"] == begin["attrs"]["id"]
    assert end["attrs"]["fieldid"] == begin["attrs"]["fieldid"]
    assert end["paragraph"] == 3

    begin_ctrl_path = begin["path"].rsplit("/", 1)[0]
    end_ctrl_path = end["path"].rsplit("/", 1)[0]
    begin_ctrl = next(record for record in block if record["path"] == begin_ctrl_path)
    end_ctrl = next(record for record in block if record["path"] == end_ctrl_path)
    assert begin_ctrl["child_index"] == 0  # before BBB
    assert end_ctrl["child_index"] == 1  # after DDD

    for name in (
        "T/T0-resave.hwpx",
        "T/T1-insert-before.hwpx",
        "T/T2-insert-inside.hwpx",
        "T/T3-edit-inside.hwpx",
    ):
        edited = controls(name)
        edited_begin = next(record for record in edited if record["tag"] == "fieldBegin")
        edited_end = next(record for record in edited if record["tag"] == "fieldEnd")
        assert edited_begin["attrs"] == begin["attrs"]
        assert edited_end["attrs"] == end["attrs"]

    for name in ("T/T4-delete-start-paragraph.hwpx", "T/T5-delete-end-paragraph.hwpx"):
        assert not any(
            record["tag"] in {"bookmark", "fieldBegin", "fieldEnd"}
            for record in controls(name)
        )

    copied = controls("T/T6-copy-paste.hwpx")
    copied_markers = [record for record in copied if record["tag"] in {"fieldBegin", "fieldEnd"}]
    assert [record["attrs"] for record in copied_markers] == [begin["attrs"], end["attrs"]]

    moved = controls("T/T7-cut-paste.hwpx")
    moved_begin = next(record for record in moved if record["tag"] == "fieldBegin")
    moved_end = next(record for record in moved if record["tag"] == "fieldEnd")
    assert moved_begin["attrs"]["id"] != begin["attrs"]["id"]
    assert moved_begin["attrs"]["name"] == begin["attrs"]["name"]
    assert moved_begin["attrs"]["fieldid"] == begin["attrs"]["fieldid"]
    assert moved_end["attrs"]["beginIDRef"] == moved_begin["attrs"]["id"]
    assert (moved_begin["paragraph"], moved_end["paragraph"]) == (2, 4)

    table_range = records("R3-table-crossing.hwpx")
    table_begin = next(record for record in table_range if record.get("tag") == "fieldBegin")
    table_end = next(record for record in table_range if record.get("tag") == "fieldEnd")
    table = next(record for record in table_range if record["kind"] == "container" and record["tag"] == "tbl")
    cell_paragraph = next(
        record
        for record in table_range
        if record["kind"] == "paragraph" and record["parent"].endswith("subList[0]")
    )
    assert (table_begin["attrs"]["type"], table_begin["attrs"]["name"]) == (
        "BOOKMARK",
        "S0_TABLE",
    )
    assert table_end["attrs"]["beginIDRef"] == table_begin["attrs"]["id"]
    assert (table_begin["paragraph"], cell_paragraph["paragraph"], table_end["paragraph"]) == (
        1,
        3,
        4,
    )
    assert table["parent"] == "sec[0]/p[2]/run[0]"

    adjacent = records("R4-adjacent.hwpx")
    markers = [
        record
        for record in adjacent
        if record.get("tag") in {"fieldBegin", "fieldEnd"}
    ]
    assert [(record["tag"], record["paragraph"]) for record in markers] == [
        ("fieldBegin", 1),
        ("fieldEnd", 1),
        ("fieldBegin", 2),
        ("fieldEnd", 2),
    ]
    left_begin, left_end, right_begin, right_end = markers
    assert [left_begin["attrs"]["name"], right_begin["attrs"]["name"]] == [
        "S0_LEFT",
        "S0_RIGHT",
    ]
    assert left_begin["attrs"]["id"] != right_begin["attrs"]["id"]
    assert left_end["attrs"]["beginIDRef"] == left_begin["attrs"]["id"]
    assert right_end["attrs"]["beginIDRef"] == right_begin["attrs"]["id"]
    assert left_end["attrs"]["beginIDRef"] != right_begin["attrs"]["id"]
    assert {left_begin["attrs"]["fieldid"], right_begin["attrs"]["fieldid"]} == {
        "627207531"
    }
    adjacent_paragraphs = [
        record for record in adjacent if record["kind"] == "paragraph"
    ]
    assert [adjacent_paragraphs[index]["id"] for index in (1, 2)] == ["0", "0"]


def test_d6_minimal_generated_bookmark_resolves_and_reparses_deterministically() -> None:
    source = (NATIVE_CORPUS / "R0-plain.hwpx").read_bytes()
    package = HwpxPackage.from_bytes(source)
    add_minimal_bookmark(package)

    regions = resolve_bookmark_regions(package)
    assert [
        (region.name, region.start_paragraph, region.end_paragraph)
        for region in regions
    ] == [(BOOKMARK_NAME, 1, 3)]

    generated = package.to_bytes()
    assert generated == (NATIVE_CORPUS / "D6-generated-minimal.hwpx").read_bytes()
    reparsed = HwpxPackage.from_bytes(generated)
    assert resolve_bookmark_regions(reparsed) == regions
    assert dump_structure(reparsed) == dump_structure(package)

    records = [json.loads(line) for line in dump_structure(reparsed).splitlines()]
    controls = [record for record in records if record["kind"] == "control"]
    begin = next(record for record in controls if record["tag"] == "fieldBegin")
    end = next(record for record in controls if record["tag"] == "fieldEnd")
    assert begin["attrs"] == {
        "id": PAIRING_ID,
        "name": BOOKMARK_NAME,
        "type": "BOOKMARK",
    }
    assert end["attrs"] == {"beginIDRef": PAIRING_ID}

    repeated = HwpxPackage.from_bytes(source)
    add_minimal_bookmark(repeated)
    assert repeated.to_bytes() == generated

    resaved = HwpxPackage.from_bytes(
        (NATIVE_CORPUS / "D6-generated-resaved.hwpx").read_bytes()
    )
    assert [
        (region.name, region.start_paragraph, region.end_paragraph)
        for region in resolve_bookmark_regions(resaved)
    ] == [(BOOKMARK_NAME, 1, 3)]
    resaved_records = [
        json.loads(line) for line in dump_structure(resaved).splitlines()
    ]
    resaved_begin = next(
        record for record in resaved_records if record.get("tag") == "fieldBegin"
    )
    resaved_end = next(
        record for record in resaved_records if record.get("tag") == "fieldEnd"
    )
    assert resaved_begin["attrs"] == {
        "dirty": "0",
        "editable": "1",
        "fieldid": "627207531",
        "id": PAIRING_ID,
        "metaTag": "",
        "name": BOOKMARK_NAME,
        "type": "BOOKMARK",
        "zorder": "-1",
    }
    assert resaved_begin["children"] == ["parameters"]
    assert resaved_end["attrs"] == {
        "beginIDRef": PAIRING_ID,
        "fieldid": "627207531",
    }
    root = etree.fromstring(resaved.entries["Contents/section0.xml"])
    parameter = next(
        node for node in root.iter() if local_name(node.tag) == "integerParam"
    )
    assert parameter.get("name") == "Prop" and parameter.text == "2"
