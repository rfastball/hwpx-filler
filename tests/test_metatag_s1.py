"""S1 spike owner: our own round-trip of authored HWPX metadata carriers.

This file proves only claim A of the S1 matrix — that hwpx-filler can author,
serialize and re-read native metadata carriers without losing payload.  Hancom
open/save preservation is claim C and is judged from committed resaved
fixtures, not from anything here.
"""

from __future__ import annotations

import json
from pathlib import Path

from _hwpx_metatag_spike import (
    CATALOG_META_NAME,
    DECLARED_ENTRY,
    MANIFEST,
    UNDECLARED_ENTRY,
    build_attribute_probe,
    build_element_probe,
    build_package_probe,
    metatag_carriers,
)
from hwpxcore.bookmark_region import resolve_bookmark_topology
from hwpxcore.package import HwpxPackage
from hwpxfiller.external.template_inspection import (
    inspect_hwpx_template,
    scan_template_structure,
)

CORPUS = Path(__file__).parent / "corpus"
S0 = CORPUS / "structural_range_s0"
S1 = CORPUS / "metatag_s1"
ELEMENT_PROBE = S1 / "G1-element-carriers.hwpx"
CASES = (
    (S0 / "R0-plain.hwpx", build_element_probe, ELEMENT_PROBE, 4),
    (S0 / "R3-table-crossing.hwpx", build_attribute_probe, S1 / "G2-attribute-carriers.hwpx", 3),
    (S0 / "R0-plain.hwpx", build_package_probe, S1 / "G3-package-carriers.hwpx", 1),
)


def _hancom(name: str) -> dict[str, str]:
    return metatag_carriers(HwpxPackage.from_bytes((S1 / name).read_bytes()))


def _authored(carriers: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in carriers.items() if '"hwpxFiller"' in value}


def _topology(name: str) -> list[dict[str, object]]:
    """Region shape as committed: names, spans, nesting and decoded payloads."""
    package = HwpxPackage.from_bytes((S1 / name).read_bytes())
    return [
        {
            "name": region.name,
            "section": region.section,
            "span": (region.start_paragraph, region.end_paragraph),
            "parent": region.parent.name if region.parent is not None else None,
            "meta_tags": [json.loads(value) for value in region.meta_tags],
            "meta_tag_attribute": region.meta_tag_attribute,
        }
        for region in resolve_bookmark_topology(package)
    ]


def _product_reading(name: str) -> dict[str, object]:
    """What the product itself reads out of the file — slots, fields, residue."""
    path = str(S1 / name)
    inspection = inspect_hwpx_template(path)
    scan = scan_template_structure(path)
    return {
        "fields": list(inspection.fields),
        "state": inspection.status.state.value,
        "stray_n": inspection.status.stray_n,
        "structure_marker_n": inspection.status.structure_marker_n,
        "slots": [
            {
                "id": slot.id,
                "label": slot.label,
                "options": [
                    {"id": option.id, "label": option.label, "order": option.order}
                    for option in slot.options
                ],
            }
            for slot in inspection.slots
        ],
        "diagnostics": [item.message for item in inspection.diagnostics],
        "scan_markers": scan.summary.markers,
        "scan_diagnostics": [item.message for item in scan.diagnostics],
    }


def test_authored_metatag_payloads_survive_our_own_serialize_reparse() -> None:
    for source, build, fixture, authored in CASES:
        package = HwpxPackage.from_bytes(source.read_bytes())
        before = metatag_carriers(package)
        build(package)
        carriers = metatag_carriers(package)

        assert not _authored(before)
        assert all(
            carriers[key] == value
            for key, value in before.items()
            if value and not key.startswith("#")
        )
        payloads = [json.loads(value) for value in _authored(carriers).values()]
        assert len(payloads) == authored
        for payload in payloads:
            # Hancom's own metatag-ex slices first "#" to last '"'; keeping "name"
            # last and "#" unique to it means that slice still yields a bare tag.
            body = json.dumps(payload, ensure_ascii=False)
            assert body[body.index("#") : body.rindex('"')] == payload["name"]
            assert payload["hwpxFiller"]["v"] == 1

        generated = package.to_bytes()
        assert generated == fixture.read_bytes()
        assert metatag_carriers(HwpxPackage.from_bytes(generated)) == carriers

        repeated = HwpxPackage.from_bytes(source.read_bytes())
        build(repeated)
        assert repeated.to_bytes() == generated


def test_authored_payload_charset_and_length_survive_every_carrier_shape() -> None:
    package = HwpxPackage.from_bytes(
        (S1 / "G2-attribute-carriers.hwpx").read_bytes()
    )
    shapes = _authored(metatag_carriers(package))
    assert {key.rsplit("|", 1)[1] for key in shapes} == {"@metaTag", "@metatag", "#text"}
    for value in shapes.values():
        body = json.loads(value)["hwpxFiller"]
        assert body["quoted"] == 'he said "yes" & <no>'
        assert body["label"] == "추가 지급 안내"
        assert body["spaced"] == "  leading and trailing  "
        assert len(body["long"]) == 512


def test_hancom_authored_metatags_land_in_three_distinct_native_carriers() -> None:
    """Priority-1 evidence: what Hancom's own 「태그 넣기」 writes, and where."""
    carriers = _hancom("M1-hancom-authored.hwpx")
    assert {key: value for key, value in carriers.items() if value.startswith("{")} == {
        # document scope -> hh:metaTag element in header.xml
        "Contents/header.xml|head[0]/metaTag[0]|#text": '{"name":"#hf_test_doc"}',
        # control scope -> hp:metaTag child element on the object
        "Contents/section0.xml|sec[0]/p[5]/run[0]/tbl[0]/metaTag[0]|#text":
            '{"name":"#hf_test_table"}',
        "Contents/section0.xml|sec[0]/p[6]/run[0]/ctrl[0]/fieldBegin[0]/metaTag[0]|#text":
            '{"name":"#hf_test_field"}',
        "Contents/section0.xml|sec[0]/p[6]/run[0]/polygon[0]/metaTag[0]|#text":
            '{"name":"#hf_test_shape"}',
        # list scope (cell) -> lowercase metatag attribute on hp:subList
        "Contents/section0.xml|sec[0]/p[5]/run[0]/tbl[0]/tr[0]/tc[0]/subList[0]|@metatag":
            '{"name":"#hf_test_cell"}',
    }
    # The camel fieldBegin@metaTag attribute coexists but Hancom leaves it empty:
    # the child element is the carrier, the attribute is not.
    assert carriers[
        "Contents/section0.xml|sec[0]/p[6]/run[0]/ctrl[0]/fieldBegin[0]|@metaTag"
    ] == ""


def test_hancom_normalizes_a_missing_sharp_prefix_onto_the_stored_tag_name() -> None:
    """M3: names typed without ``#`` come back with it, so storage always has one."""
    authored = _hancom("M1-hancom-authored.hwpx")
    no_sharp = _hancom("M3-no-sharp.hwpx")
    tags = {key: value for key, value in authored.items() if value.startswith("{")}

    assert {json.loads(value)["name"] for value in tags.values()} == {
        "#hf_test_doc",
        "#hf_test_table",
        "#hf_test_cell",
        "#hf_test_field",
        "#hf_test_shape",
    }
    # Re-entering every name without "#" leaves the stored payloads untouched.
    assert {key: no_sharp[key] for key in tags} == tags


def test_hancom_round_trip_preserves_tags_and_renames_only_the_edited_one() -> None:
    authored = _hancom("M1-hancom-authored.hwpx")
    volatile = {"#entries", f"{MANIFEST}|opf:meta[@name=ModifiedDate]"}

    resaved = _hancom("M1-resaved.hwpx")
    assert {k: v for k, v in resaved.items() if k not in volatile} == {
        k: v for k, v in authored.items() if k not in volatile
    }

    renamed = _hancom("M2-renamed.hwpx")
    changed = {
        key
        for key in set(authored) | set(renamed)
        if key not in volatile and authored.get(key) != renamed.get(key)
    }
    assert changed == {
        "Contents/section0.xml|sec[0]/p[6]/run[0]/ctrl[0]/fieldBegin[0]/metaTag[0]|#text"
    }
    assert renamed[changed.pop()] == '{"name":"#hf_slot_test"}'


def test_hancom_preserves_modelled_carriers_and_wipes_everything_else() -> None:
    """Claim C: which carriers survive a real Hancom open/edit/save."""
    survived = {
        "Contents/header.xml|head[0]/metaTag[0]|#text",
        "Contents/section0.xml|sec[0]/p[1]/run[0]/ctrl[0]/fieldBegin[0]/metaTag[0]|#text",
        "Contents/section0.xml|sec[0]/p[2]/run[0]/ctrl[0]/fieldBegin[0]/metaTag[0]|#text",
        "Contents/section0.xml|sec[0]/p[3]/run[0]/ctrl[0]/fieldBegin[0]/metaTag[0]|#text",
        "Contents/section0.xml|sec[0]/p[2]/run[0]/tbl[0]/metaTag[0]|#text",
        "Contents/section0.xml|sec[0]/p[2]/run[0]/tbl[0]/tr[0]/tc[0]/subList[0]|@metatag",
    }
    for source, resaved in (
        ("G1-element-carriers.hwpx", "G1-resaved.hwpx"),
        ("G2-attribute-carriers.hwpx", "G2-resaved.hwpx"),
        ("G3-package-carriers.hwpx", "G3-resaved.hwpx"),
    ):
        before, after = _authored(_hancom(source)), _hancom(resaved)
        for key, value in before.items():
            if key not in survived:
                # Out-of-model camel attribute, custom opf:meta and extra package
                # entries all come back empty or gone.
                assert not after.get(key), key
                continue
            payload = json.loads(value)
            assert json.loads(after[key]) == payload, key
            # Hancom rewrites the JSON compactly; content and key order survive.
            assert after[key] == json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ), key
            assert list(payload)[-1] == "name" and payload["name"].startswith("#")

    entries = _hancom("G3-resaved.hwpx")["#entries"].split(", ")
    assert DECLARED_ENTRY not in entries and UNDECLARED_ENTRY not in entries


def test_hancom_round_trip_preserves_the_nested_kernel_region_pair() -> None:
    """Claim C for the kernel minimum under nesting — the shape G1..G3 lack.

    ``N1-nested-kernel.hwpx`` was authored by the product compile path over
    ``corpus/structural_range_s0/R0-plain.hwpx``: nothing but
    ``fieldBegin@type=BOOKMARK`` regions carrying ``hp:metaTag`` children, with
    one 항목 region containing two sibling 선택 regions.  ``N1-resaved.hwpx`` is
    that file opened and saved unedited by Hancom Office Hangul 12.0.0.4426
    (2026-08-25, #807 §6 condition 10 verification session).
    """
    before, after = _topology("N1-nested-kernel.hwpx"), _topology("N1-resaved.hwpx")

    assert [region["name"] for region in before] == [
        "계약방식",
        "계약방식/일반경쟁",
        "계약방식/수의계약",
    ]
    assert [region["span"] for region in before] == [(5, 6), (5, 5), (6, 6)]
    slot, *options = before
    for option in options:
        # The two 선택 regions are siblings nested inside the 항목 region, and
        # each spans a paragraph range the parent's range contains.
        assert option["parent"] == slot["name"] and slot["parent"] is None
        assert option["section"] == slot["section"]
        assert slot["span"][0] <= option["span"][0]
        assert option["span"][1] <= slot["span"][1]
    assert [region["meta_tags"] for region in before] == [
        [{"hwpxFiller": {"kind": "slot", "id": "계약방식", "label": "계약 방식"}, "name": "#hf"}],
        [
            {
                "hwpxFiller": {"kind": "slot_option", "id": "일반경쟁", "label": "일반경쟁 계약"},
                "name": "#hf",
            }
        ],
        [
            {
                "hwpxFiller": {"kind": "slot_option", "id": "수의계약", "label": "수의 계약"},
                "name": "#hf",
            }
        ],
    ]

    # The single allowed normalization, the one M1 already records: the camel
    # fieldBegin@metaTag attribute is absent as we author it and empty after a
    # Hancom save.  The child element is the carrier and product reads are
    # truthiness over the attribute, so absent and empty mean the same thing.
    assert [region["meta_tag_attribute"] for region in before] == [None, None, None]
    assert [region["meta_tag_attribute"] for region in after] == ["", "", ""]
    assert [
        {key: value for key, value in region.items() if key != "meta_tag_attribute"}
        for region in after
    ] == [
        {key: value for key, value in region.items() if key != "meta_tag_attribute"}
        for region in before
    ]

    reading = _product_reading("N1-nested-kernel.hwpx")
    assert _product_reading("N1-resaved.hwpx") == reading
    assert reading["slots"] == [
        {
            "id": "계약방식",
            "label": "계약 방식",
            "options": [
                {"id": "일반경쟁", "label": "일반경쟁 계약", "order": 0},
                {"id": "수의계약", "label": "수의 계약", "order": 1},
            ],
        }
    ]
    assert reading["state"] == "compiled"
    assert reading["fields"] == ["수요기관", "담당자", "계약금액", "납품기한", "수의사유"]
    assert reading["diagnostics"] == [] and reading["scan_diagnostics"] == []
    assert reading["scan_markers"] == 0 and reading["structure_marker_n"] == 0
    assert reading["stray_n"] == 0


def test_package_probe_adds_declared_and_undeclared_catalog_entries() -> None:
    package = HwpxPackage.from_bytes((S1 / "G3-package-carriers.hwpx").read_bytes())
    carriers = metatag_carriers(package)

    assert {DECLARED_ENTRY, UNDECLARED_ENTRY} <= set(carriers["#entries"].split(", "))
    assert DECLARED_ENTRY.encode() in package.entries[MANIFEST]
    assert UNDECLARED_ENTRY.encode() not in package.entries[MANIFEST]
    assert list(_authored(carriers)) == [
        f"{MANIFEST}|opf:meta[@name={CATALOG_META_NAME}]"
    ]
