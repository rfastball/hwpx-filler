from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from _hwpx_metatag_spike import build_slot_probe
from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.domain.slot import Slot, SlotOption
from hwpxfiller.external.template_inspection import (
    inspect_hwpx_template,
    inspect_slots,
    serialize_slot_metatag,
    serialize_slot_option_metatag,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
SECTION = "Contents/section0.xml"
CORPUS = Path(__file__).parent / "corpus" / "structural_range_s0"
SLOT_CORPUS = Path(__file__).parent / "corpus" / "slots"


def _native(name: str) -> HwpxPackage:
    return HwpxPackage.from_bytes((CORPUS / name).read_bytes())


def _slot(
    identifier: str = "extra_notice",
    *,
    label: object = "추가 지급 안내",
    v: object = 1,
    kind: object = "slot",
    cardinality: object = "exactly_one",
    min_options: object = 1,
    ordering: object = "template_order",
    name: object = "#hf_slot",
    **extra: object,
) -> str:
    return json.dumps(
        {
            "hwpxFiller": {
                "v": v,
                "kind": kind,
                "id": identifier,
                "label": label,
                "cardinality": cardinality,
                "minOptions": min_options,
                "ordering": ordering,
                **extra,
            },
            "name": name,
        },
        ensure_ascii=False,
    )


def _option(
    identifier: str = "bonus",
    *,
    label: object = "성과급 안내",
    v: object = 1,
    kind: object = "slot_option",
    name: object = "#hf_slot_option",
    **extra: object,
) -> str:
    return json.dumps(
        {
            "hwpxFiller": {
                "v": v,
                "kind": kind,
                "id": identifier,
                "label": label,
                **extra,
            },
            "name": name,
        },
        ensure_ascii=False,
    )


def _write_tags(
    pkg: HwpxPackage,
    payloads: dict[str, str | tuple[str, ...]],
    *,
    attributes: dict[str, str] | None = None,
) -> HwpxPackage:
    root = etree.fromstring(pkg.entries[SECTION])
    bookmark_begins = [
        node
        for node in root.iter(f"{{{HP}}}fieldBegin")
        if node.get("type") == "BOOKMARK"
    ]
    for name, values in payloads.items():
        matches = [node for node in bookmark_begins if node.get("name") == name]
        if len(matches) != 1:
            raise ValueError(f"expected one BOOKMARK named {name!r}; found {len(matches)}")
        node = matches[0]
        for value in (values,) if isinstance(values, str) else values:
            child = etree.SubElement(node, f"{{{HP}}}metaTag")
            child.text = value
    for name, value in (attributes or {}).items():
        matches = [node for node in bookmark_begins if node.get("name") == name]
        if len(matches) != 1:
            raise ValueError(f"expected one BOOKMARK named {name!r}; found {len(matches)}")
        matches[0].set("metaTag", value)
    pkg.entries[SECTION] = serialize_modified_section(root)
    return pkg


def _xml_package(events: str) -> HwpxPackage:
    return HwpxPackage(
        entries={
            MIMETYPE_NAME: MIMETYPE_VALUE,
            SECTION: f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{events}</hs:sec>'.encode(),
        },
        stored={MIMETYPE_NAME},
    )


def _p(content: str) -> str:
    return f"<hp:p><hp:run>{content}</hp:run></hp:p>"


def _begin(identifier: str, name: str) -> str:
    return (
        f'<hp:ctrl><hp:fieldBegin id="{identifier}" type="BOOKMARK" '
        f'name="{name}"/></hp:ctrl>'
    )


def _end(identifier: str) -> str:
    return f'<hp:ctrl><hp:fieldEnd beginIDRef="{identifier}"/></hp:ctrl>'


def _plain_ancestor_package() -> HwpxPackage:
    return _xml_package(
        _p(_begin("1", "SLOT") + "<hp:t>A</hp:t>")
        + _p(_begin("2", "PLAIN") + "<hp:t>B</hp:t>")
        + _p(_begin("3", "OPTION") + "<hp:t>C</hp:t>" + _end("3"))
        + _p("<hp:t>D</hp:t>" + _end("2"))
        + _p("<hp:t>E</hp:t>" + _end("1"))
        + _p("<hp:t>OUT</hp:t>")
    )


def _two_slot_package() -> HwpxPackage:
    package = _xml_package(
        _p(_begin("1", "Z_SLOT") + "<hp:t>A</hp:t>")
        + _p(_begin("2", "Z_OPT") + "<hp:t>B</hp:t>" + _end("2"))
        + _p("<hp:t>C</hp:t>" + _end("1"))
        + _p(_begin("3", "A_SLOT") + "<hp:t>D</hp:t>")
        + _p(_begin("4", "A_OPT") + "<hp:t>E</hp:t>" + _end("4"))
        + _p("<hp:t>F</hp:t>" + _end("3"))
        + _p("<hp:t>OUT</hp:t>")
    )
    return _write_tags(
        package,
        {
            "Z_SLOT": _slot("z_slot", cardinality="zero_or_one"),
            "Z_OPT": _option("same"),
            "A_SLOT": _slot("a_slot", cardinality="many"),
            "A_OPT": _option("same"),
        },
    )


@pytest.mark.parametrize(
    ("source", "payloads", "expected"),
    (
        (
            lambda: _native("R5-nested.hwpx"),
            {
                "S0_SLOT": (
                    json.dumps(["vendor"]),
                    json.dumps({"vendor": {"future": True}}),
                    _slot(min_options=2, future={"kept": True}),
                ),
                "S0_OPT_A": _option("bonus"),
                "S0_OPT_B": _option("special", label="특별수당 안내"),
            },
            Slot(
                id="extra_notice",
                label="추가 지급 안내",
                cardinality="exactly_one",
                min_options=2,
                options=(
                    SlotOption("bonus", "성과급 안내", 0),
                    SlotOption("special", "특별수당 안내", 1),
                ),
            ),
        ),
        (
            lambda: _native("G/G1-coincident-start.hwpx"),
            {"S0_OPT_A": _slot(), "S0_SLOT": _option()},
            Slot(
                id="extra_notice",
                label="추가 지급 안내",
                cardinality="exactly_one",
                min_options=1,
                options=(SlotOption("bonus", "성과급 안내", 0),),
            ),
        ),
        (
            lambda: _native("G/G2-coincident-end.hwpx"),
            {"S0_SLOT": _slot(), "S0_OPT_B": _option()},
            Slot(
                id="extra_notice",
                label="추가 지급 안내",
                cardinality="exactly_one",
                min_options=1,
                options=(SlotOption("bonus", "성과급 안내", 0),),
            ),
        ),
        (
            lambda: _native("G/G3-same-range.hwpx"),
            {"S0_SLOT": _slot(), "S0_OPT_X": _option()},
            Slot(
                id="extra_notice",
                label="추가 지급 안내",
                cardinality="exactly_one",
                min_options=1,
                options=(SlotOption("bonus", "성과급 안내", 0),),
            ),
        ),
        (
            _plain_ancestor_package,
            {"SLOT": _slot(), "OPTION": _option()},
            Slot(
                id="extra_notice",
                label="추가 지급 안내",
                cardinality="exactly_one",
                min_options=1,
                options=(SlotOption("bonus", "성과급 안내", 0),),
            ),
        ),
    ),
    ids=("ordinary", "coincident-start", "coincident-end", "same-span", "plain-ancestor"),
)
def test_slots_follow_native_parent_and_document_order(
    source, payloads: dict[str, str | tuple[str, ...]], expected: Slot
) -> None:
    package = source()
    original_entries = dict(package.entries)
    slots, diagnostics = inspect_slots(_write_tags(package, payloads))
    assert slots == (expected,)
    assert diagnostics == ()
    assert all(
        data == package.entries[name] for name, data in original_entries.items() if name != SECTION
    )
    assert inspect_slots(HwpxPackage.from_bytes(package.to_bytes())) == (slots, diagnostics)


def test_slot_order_and_option_identity_are_native_and_slot_local() -> None:
    assert inspect_slots(_two_slot_package()) == (
        (
            Slot(
                id="z_slot",
                label="추가 지급 안내",
                cardinality="zero_or_one",
                min_options=1,
                options=(SlotOption("same", "성과급 안내", 0),),
            ),
            Slot(
                id="a_slot",
                label="추가 지급 안내",
                cardinality="many",
                min_options=1,
                options=(SlotOption("same", "성과급 안내", 0),),
            ),
        ),
        (),
    )


@pytest.mark.parametrize(
    ("payloads", "attributes", "kinds"),
    (
        ({"S0_SLOT": "{"}, None, {"malformed-json"}),
        ({"S0_SLOT": json.dumps({"hwpxFiller": []})}, None, {"invalid-product-payload"}),
        ({"S0_SLOT": json.dumps({"name": "#hf_slot"})}, None, {"invalid-product-payload"}),
        ({"S0_SLOT": _slot(v=[])}, None, {"invalid-product-payload"}),
        ({"S0_SLOT": _slot(v=True)}, None, {"invalid-product-payload"}),
        ({"S0_SLOT": _slot(v=2)}, None, {"unsupported-version"}),
        ({"S0_SLOT": _slot(kind=[])}, None, {"unknown-kind"}),
        ({"S0_SLOT": _slot("")}, None, {"invalid-id"}),
        ({"S0_SLOT": _slot(label=3)}, None, {"invalid-label"}),
        (
            {"S0_SLOT": _slot(label=3), "S0_OPT_A": _option()},
            None,
            {"invalid-label"},
        ),
        ({"S0_SLOT": _slot(cardinality=[])}, None, {"unknown-cardinality"}),
        ({"S0_SLOT": _slot(min_options=-1)}, None, {"invalid-min-options"}),
        ({"S0_SLOT": _slot(ordering="id")}, None, {"unsupported-ordering"}),
        (
            {"S0_SLOT": _slot(name="#wrong", min_options=0)},
            None,
            {"native-name-mismatch"},
        ),
        ({}, {"S0_SLOT": _slot()}, {"unsupported-carrier"}),
        (
            {},
            {"S0_SLOT": json.dumps({"name": "#hf_slot"})},
            {"unsupported-carrier", "invalid-product-payload"},
        ),
        ({}, {"S0_SLOT": json.dumps({"vendor": 1})}, set()),
        (
            {},
            {"S0_SLOT": "{"},
            {"malformed-json"},
        ),
        ({"S0_SLOT": (_slot(), _slot("other"))}, None, {"conflicting-product-metatag"}),
    ),
)
def test_payload_failures_have_stable_diagnostics(
    payloads: dict[str, str | tuple[str, ...]],
    attributes: dict[str, str] | None,
    kinds: set[str],
) -> None:
    _slots, diagnostics = inspect_slots(
        _write_tags(_native("R5-nested.hwpx"), payloads, attributes=attributes)
    )
    assert {diagnostic.kind for diagnostic in diagnostics} == kinds


def _tag_events(events: str, payloads: dict[str, str]) -> HwpxPackage:
    return _write_tags(_xml_package(events), payloads)


@pytest.mark.parametrize(
    ("package", "expected"),
    (
        (
            _tag_events(
                _p(_begin("1", "A") + "<hp:t>A</hp:t>" + _end("1"))
                + _p(_begin("2", "B") + "<hp:t>B</hp:t>" + _end("2"))
                + _p("<hp:t>OUT</hp:t>"),
                {"A": _slot("same", min_options=0), "B": _slot("same", min_options=0)},
            ),
            {"duplicate-slot-id"},
        ),
        (
            _write_tags(
                _native("R5-nested.hwpx"),
                {
                    "S0_SLOT": _slot(),
                    "S0_OPT_A": _option("same"),
                    "S0_OPT_B": _option("same"),
                },
            ),
            {"duplicate-option-id"},
        ),
        (
            _tag_events(
                _p(_begin("1", "O") + "<hp:t>A</hp:t>" + _end("1"))
                + _p("<hp:t>OUT</hp:t>"),
                {"O": _option()},
            ),
            {"orphan-option"},
        ),
        (
            _tag_events(
                _p(_begin("1", "A") + "<hp:t>A</hp:t>")
                + _p(_begin("2", "B") + "<hp:t>B</hp:t>")
                + _p(_begin("3", "O") + "<hp:t>C</hp:t>" + _end("3"))
                + _p("<hp:t>D</hp:t>" + _end("2"))
                + _p("<hp:t>E</hp:t>" + _end("1"))
                + _p("<hp:t>OUT</hp:t>"),
                {"A": _slot("a", min_options=0), "B": _slot("b", min_options=0), "O": _option()},
            ),
            {"nested-slot", "ambiguous-membership"},
        ),
        (
            _tag_events(
                _p(_begin("1", "S") + "<hp:t>A</hp:t>")
                + _p(_begin("2", "A") + "<hp:t>B</hp:t>")
                + _p(_begin("3", "B") + "<hp:t>C</hp:t>" + _end("3"))
                + _p("<hp:t>D</hp:t>" + _end("2"))
                + _p("<hp:t>E</hp:t>" + _end("1"))
                + _p("<hp:t>OUT</hp:t>"),
                {"S": _slot(min_options=0), "A": _option("a"), "B": _option("b")},
            ),
            {"nested-option"},
        ),
        (
            _write_tags(_native("R5-nested.hwpx"), {"S0_SLOT": _slot(min_options=3)}),
            {"min-options-unsatisfied"},
        ),
        (
            _xml_package(
                _p(_begin("1", "A") + "<hp:t>A</hp:t>")
                + _p(_begin("2", "B") + "<hp:t>B</hp:t>")
                + _p("<hp:t>C</hp:t>" + _end("1"))
                + _p("<hp:t>D</hp:t>" + _end("2"))
                + _p("<hp:t>OUT</hp:t>")
            ),
            {"crossing-range"},
        ),
        (
            _xml_package(_p(_begin("1", "A") + "<hp:t>A</hp:t>") + _p("<hp:t>OUT</hp:t>")),
            {"bookmark-resolve-failed"},
        ),
        (
            HwpxPackage(
                entries={MIMETYPE_NAME: MIMETYPE_VALUE, SECTION: b"<broken>"},
                stored={MIMETYPE_NAME},
            ),
            {"bookmark-resolve-failed"},
        ),
    ),
    ids=(
        "duplicate-slot",
        "duplicate-option",
        "orphan",
        "nested-slot",
        "nested-option",
        "min-options",
        "crossing",
        "malformed-pair",
        "malformed-xml",
    ),
)
def test_topology_failures_have_stable_diagnostics(
    package: HwpxPackage, expected: set[str]
) -> None:
    _slots, diagnostics = inspect_slots(package)
    assert {diagnostic.kind for diagnostic in diagnostics} == expected


def test_canonical_serializers_fix_schema_and_native_name_last() -> None:
    slot = Slot(
        id="extra_notice",
        label="추가 지급 안내",
        cardinality="exactly_one",
        min_options=2,
        options=(),
    )
    option = SlotOption("bonus", "성과급 안내", 0)
    slot_raw = serialize_slot_metatag(slot)
    option_raw = serialize_slot_option_metatag(option)
    assert slot_raw.endswith('"name":"#hf_slot"}')
    assert option_raw.endswith('"name":"#hf_slot_option"}')
    assert json.loads(slot_raw) == {
        "hwpxFiller": {
            "v": 1,
            "kind": "slot",
            "id": "extra_notice",
            "label": "추가 지급 안내",
            "cardinality": "exactly_one",
            "minOptions": 2,
            "ordering": "template_order",
        },
        "name": "#hf_slot",
    }
    assert json.loads(option_raw)["hwpxFiller"]["kind"] == "slot_option"


@pytest.mark.parametrize(
    "slot",
    (
        Slot("", "label", "exactly_one", 0, ()),
        Slot(1, "label", "exactly_one", 0, ()),  # type: ignore[arg-type]
        Slot("id", "label", [], 0, ()),  # type: ignore[arg-type]
        Slot("id", "label", "future", 0, ()),
        Slot("id", "label", "exactly_one", True, ()),
        Slot("id", "label", "exactly_one", -1, ()),
        Slot("id", "label", "exactly_one", 0, (), "id_order"),
    ),
)
def test_canonical_slot_serializer_rejects_invalid_values(slot: Slot) -> None:
    with pytest.raises(ValueError):
        serialize_slot_metatag(slot)


def test_canonical_fixture_is_reproducible_and_path_adapter_restores_slots(
    tmp_path: Path,
) -> None:
    package = _native("R5-nested.hwpx")
    build_slot_probe(package)
    canonical_bytes = (SLOT_CORPUS / "canonical.hwpx").read_bytes()
    assert package.to_bytes() == canonical_bytes

    canonical = HwpxPackage.from_bytes(canonical_bytes)
    resaved = HwpxPackage.from_bytes((SLOT_CORPUS / "canonical-resaved.hwpx").read_bytes())
    assert canonical.to_bytes() != resaved.to_bytes()
    assert b"AAA" in canonical.entries[SECTION] and b"AAX" in resaved.entries[SECTION]

    expected = inspect_slots(canonical)
    assert not expected[1]
    assert inspect_slots(resaved) == expected

    path = tmp_path / "canonical.hwpx"
    path.write_bytes(resaved.to_bytes())
    inspection = inspect_hwpx_template(str(path))
    assert (inspection.slots, inspection.diagnostics) == expected
