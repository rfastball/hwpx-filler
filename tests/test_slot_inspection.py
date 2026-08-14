from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from _hwpx_metatag_spike import build_slot_probe
from hwpxcore.bookmark_region import resolve_bookmark_topology
from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxcore.structural_boundary import (
    BookmarkBegin,
    BookmarkEnd,
    BoundaryPairRef,
    ContentEntryKind,
    FieldBegin,
    FieldEnd,
    StructuralBoundaryScan,
    StructuralDiagnostic,
    StructuralDiagnosticKind,
    StructuralEntryScan,
    scan_structural_boundaries,
)
import hwpxfiller.external.template_inspection as template_inspection
from hwpxfiller.domain.slot import Slot, SlotOption
from hwpxfiller.external.template_inspection import (
    ProductClassification,
    ProductInspectionContractError,
    ProductScopeRole,
    inspect_hwpx_template,
    inspect_product_bookmarks,
    inspect_slots,
    remove_slot,
    remove_slot_option,
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
    identifier: object = "추가 지급 안내",
    *,
    kind: object = "slot",
    name: object = "#hf",
    **extra: object,
) -> str:
    return json.dumps(
        {
            "hwpxFiller": {
                "kind": kind,
                "id": identifier,
                **extra,
            },
            "name": name,
        },
        ensure_ascii=False,
    )


def _option(
    identifier: object = "성과급 안내",
    *,
    kind: object = "slot_option",
    name: object = "#hf",
    **extra: object,
) -> str:
    return json.dumps(
        {
            "hwpxFiller": {
                "kind": kind,
                "id": identifier,
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
        + _p(
            "<hp:t>ordinary prefix</hp:t>"
            + _begin("5", "PLAIN_PARTIAL")
            + "<hp:t>ordinary bookmark</hp:t>"
            + _end("5")
        )
        + _p("<hp:t>OUT</hp:t>")
    )
    return _write_tags(
        package,
        {
            "Z_SLOT": _slot("z_slot"),
            "Z_OPT": _option("same"),
            "A_SLOT": _slot("a_slot"),
            "A_OPT": _option("same"),
        },
    )


def _three_option_package() -> HwpxPackage:
    package = _xml_package(
        _p("<hp:t>OUT</hp:t>")
        + _p(_begin("1", "SLOT") + "<hp:t>S</hp:t>")
        + _p(_begin("2", "A") + "<hp:t>A</hp:t>" + _end("2"))
        + _p(_begin("3", "B") + "<hp:t>B</hp:t>" + _end("3"))
        + _p(_begin("4", "C") + "<hp:t>C</hp:t>" + _end("4"))
        + _p("<hp:t>Z</hp:t>" + _end("1"))
        + _p("<hp:t>OUT2</hp:t>")
    )
    return _write_tags(
        package,
        {
            "SLOT": _slot("slot"),
            "A": _option("a"),
            "B": _option("b"),
            "C": _option("c"),
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
                    _slot(),
                ),
                "S0_OPT_A": _option("성과급 안내"),
                "S0_OPT_B": _option("특별수당 안내"),
            },
            Slot(
                id="추가 지급 안내",
                options=(
                    SlotOption("성과급 안내", 0),
                    SlotOption("특별수당 안내", 1),
                ),
            ),
        ),
        (
            lambda: _native("G/G1-coincident-start.hwpx"),
            {"S0_OPT_A": _slot(), "S0_SLOT": _option()},
            Slot(
                id="추가 지급 안내",
                options=(SlotOption("성과급 안내", 0),),
            ),
        ),
        (
            lambda: _native("G/G2-coincident-end.hwpx"),
            {"S0_SLOT": _slot(), "S0_OPT_B": _option()},
            Slot(
                id="추가 지급 안내",
                options=(SlotOption("성과급 안내", 0),),
            ),
        ),
        (
            lambda: _native("G/G3-same-range.hwpx"),
            {"S0_SLOT": _slot(), "S0_OPT_X": _option()},
            Slot(
                id="추가 지급 안내",
                options=(SlotOption("성과급 안내", 0),),
            ),
        ),
        (
            _plain_ancestor_package,
            {"SLOT": _slot(), "OPTION": _option()},
            Slot(
                id="추가 지급 안내",
                options=(SlotOption("성과급 안내", 0),),
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
                options=(SlotOption("same", 0),),
            ),
            Slot(
                id="a_slot",
                options=(SlotOption("same", 0),),
            ),
        ),
        (),
    )


@pytest.mark.parametrize(
    ("target", "remaining"),
    (("a", ("b", "c")), ("b", ("a", "c")), ("c", ("a", "b"))),
    ids=("first", "middle", "last"),
)
def test_remove_slot_option_preserves_siblings_and_rebuilds_native_order(
    target: str, remaining: tuple[str, ...]
) -> None:
    package = _three_option_package()
    remove_slot_option(package, "slot", target)

    expected = (
        Slot(
            "slot",
            tuple(SlotOption(identifier, order) for order, identifier in enumerate(remaining)),
        ),
    )
    assert inspect_slots(package) == (expected, ())
    assert inspect_slots(HwpxPackage.from_bytes(package.to_bytes())) == (expected, ())


def test_product_removal_uses_slot_local_ids_and_preserves_plain_bookmarks() -> None:
    package = _two_slot_package()
    remove_slot_option(package, "z_slot", "same")
    assert inspect_slots(package) == (
        (
            Slot("z_slot", ()),
            Slot("a_slot", (SlotOption("same", 0),)),
        ),
        (),
    )
    assert "PLAIN_PARTIAL" in {
        region.name for region in resolve_bookmark_topology(package)
    }

    current = HwpxPackage.from_bytes(package.to_bytes())
    remove_slot(current, "z_slot")
    assert inspect_slots(current) == (
        (Slot("a_slot", (SlotOption("same", 0),)),),
        (),
    )
    assert "PLAIN_PARTIAL" in {
        region.name for region in resolve_bookmark_topology(current)
    }


@pytest.mark.parametrize(
    ("source", "payloads"),
    (
        (
            lambda: _native("G/G1-coincident-start.hwpx"),
            {"S0_OPT_A": _slot("slot"), "S0_SLOT": _option("option")},
        ),
        (
            lambda: _native("G/G2-coincident-end.hwpx"),
            {"S0_SLOT": _slot("slot"), "S0_OPT_B": _option("option")},
        ),
        (
            lambda: _native("G/G3-same-range.hwpx"),
            {"S0_SLOT": _slot("slot"), "S0_OPT_X": _option("option")},
        ),
        (
            _plain_ancestor_package,
            {"SLOT": _slot("slot"), "OPTION": _option("option")},
        ),
    ),
    ids=("coincident-start", "coincident-end", "same-span", "plain-ancestor"),
)
def test_remove_slot_option_supports_every_canonical_parent_topology(
    source, payloads: dict[str, str]
) -> None:
    package = _write_tags(source(), payloads)
    remove_slot_option(package, "slot", "option")
    assert inspect_slots(package) == ((Slot("slot", ()),), ())
    assert inspect_slots(HwpxPackage.from_bytes(package.to_bytes())) == (
        (Slot("slot", ()),),
        (),
    )


def test_product_removal_failures_are_atomic(monkeypatch: pytest.MonkeyPatch) -> None:
    package = _three_option_package()
    for action in (
        lambda: remove_slot(package, "missing"),
        lambda: remove_slot_option(package, "slot", "missing"),
    ):
        before = dict(package.entries)
        with pytest.raises(ValueError, match="was not found"):
            action()
        assert package.entries == before

    duplicate = _write_tags(
        _native("R5-nested.hwpx"),
        {
            "S0_SLOT": _slot("slot"),
            "S0_OPT_A": _option("same"),
            "S0_OPT_B": _option("same"),
        },
    )
    before = dict(duplicate.entries)
    with pytest.raises(ValueError, match="blocked by diagnostics"):
        remove_slot_option(duplicate, "slot", "same")
    assert duplicate.entries == before

    resolver = template_inspection.resolve_bookmark_topology
    monkeypatch.setattr(
        template_inspection,
        "resolve_bookmark_topology",
        lambda pkg: tuple(reversed(resolver(pkg))),
    )
    mismatched = _three_option_package()
    before = dict(mismatched.entries)
    with pytest.raises(ProductInspectionContractError, match="order disagree"):
        remove_slot_option(mismatched, "slot", "b")
    assert mismatched.entries == before
    monkeypatch.setattr(template_inspection, "resolve_bookmark_topology", resolver)

    def corrupt(pkg: HwpxPackage, _region) -> None:
        pkg.entries["partial-write"] = b"leak"

    monkeypatch.setattr(template_inspection, "remove_bookmark_region", corrupt)
    rollback = _three_option_package()
    before = dict(rollback.entries)
    with pytest.raises(ValueError, match="postcondition failed"):
        remove_slot_option(rollback, "slot", "b")
    assert rollback.entries == before


@pytest.mark.parametrize(
    ("payloads", "attributes", "kinds"),
    (
        ({"S0_SLOT": "{"}, None, {"malformed-json"}),
        ({"S0_SLOT": json.dumps({"hwpxFiller": []})}, None, {"invalid-product-payload"}),
        ({"S0_SLOT": json.dumps({"name": "#hf"})}, None, {"invalid-product-payload"}),
        ({"S0_SLOT": _slot(kind=[])}, None, {"unknown-kind"}),
        ({"S0_SLOT": _slot("")}, None, {"invalid-id"}),
        ({"S0_SLOT": _slot(3)}, None, {"invalid-id"}),
        (
            {"S0_SLOT": _slot(name="#hf_slot")},
            None,
            {"native-name-mismatch"},
        ),
        ({}, {"S0_SLOT": _slot()}, {"unsupported-carrier"}),
        (
            {},
            {"S0_SLOT": json.dumps({"name": "#hf"})},
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


def test_product_inspection_preserves_exact_scan_pairs_and_pair_local_membership() -> None:
    scan = scan_structural_boundaries(_two_slot_package())
    inspection = inspect_product_bookmarks(scan)
    begins = [
        event
        for entry in scan.entries
        for event in entry.events
        if isinstance(event, BookmarkBegin)
    ]

    assert inspection.diagnostics == ()
    assert [item.pair for item in inspection.observations] == [event.pair for event in begins]
    z_slot, z_option, a_slot, a_option, plain = inspection.observations
    assert (
        z_slot.classification,
        z_slot.scope_role,
        z_slot.scope_usable,
        z_slot.kind,
        z_slot.product_id,
    ) == (
        ProductClassification.KNOWN_PRODUCT,
        ProductScopeRole.SLOT,
        True,
        "slot",
        "z_slot",
    )
    assert z_option.owning_slot_pair is z_slot.pair
    assert a_option.owning_slot_pair is a_slot.pair
    assert z_option.owning_slot_pair is not a_option.owning_slot_pair
    assert plain.classification is ProductClassification.NON_PRODUCT
    assert plain.scope_role is ProductScopeRole.NONE
    assert plain.owning_slot_pair is None


def test_known_noncanonical_products_keep_role_without_inventing_identity() -> None:
    cases = (
        ("invalid-id", {"S0_SLOT": _slot("")}, None, {"invalid-id"}, None, ()),
        (
            "native-name",
            {"S0_SLOT": _slot("slot", name="#wrong")},
            None,
            {"native-name-mismatch"},
            "slot",
            (Slot("slot", ()),),
        ),
        (
            "attribute",
            {},
            {"S0_SLOT": _slot("slot")},
            {"unsupported-carrier"},
            None,
            (),
        ),
        (
            "malformed-extra",
            {"S0_SLOT": ("{", _slot("slot"))},
            None,
            {"malformed-json"},
            "slot",
            (Slot("slot", ()),),
        ),
        (
            "canonical-over-attribute",
            {"S0_SLOT": _slot("slot")},
            {"S0_SLOT": _slot("unsupported")},
            {"unsupported-carrier"},
            "slot",
            (Slot("slot", ()),),
        ),
    )
    for name, payloads, attributes, expected_kinds, expected_id, expected_slots in cases:
        package = _write_tags(_native("R5-nested.hwpx"), payloads, attributes=attributes)
        inspection = inspect_product_bookmarks(scan_structural_boundaries(package))
        observation = next(item for item in inspection.observations if item.kind == "slot")

        assert observation.classification is ProductClassification.KNOWN_PRODUCT, name
        assert observation.scope_role is ProductScopeRole.SLOT, name
        assert observation.scope_usable, name
        assert observation.product_id == expected_id, name
        assert {item.kind for item in inspection.diagnostics} == expected_kinds, name
        assert inspect_slots(package)[0] == expected_slots, name


def test_invalid_inner_scope_restores_outer_and_only_options_store_membership() -> None:
    package = _tag_events(
        _p(_begin("1", "SLOT") + "<hp:t>A</hp:t>")
        + _p(_begin("2", "PLAIN") + "<hp:t>B</hp:t>" + _end("2"))
        + _p(_begin("3", "BAD") + "<hp:t>C</hp:t>" + _end("3"))
        + _p(_begin("4", "OPTION") + "<hp:t>D</hp:t>" + _end("4"))
        + _p("<hp:t>E</hp:t>" + _end("1")),
        {
            "SLOT": _slot("outer"),
            "BAD": _slot("bad", kind="future"),
            "OPTION": _option("after"),
        },
    )

    inspection = inspect_product_bookmarks(scan_structural_boundaries(package))
    slot, plain, invalid, option = inspection.observations

    assert {item.kind for item in inspection.diagnostics} == {"unknown-kind"}
    assert slot.scope_role is ProductScopeRole.SLOT
    assert plain.owning_slot_pair is None
    assert invalid.scope_role is ProductScopeRole.INVALID_PRODUCT
    assert not invalid.scope_usable
    assert option.scope_role is ProductScopeRole.OPTION
    assert option.owning_slot_pair is slot.pair
    assert inspect_slots(package)[0] == (Slot("outer", (SlotOption("after", 0),)),)


def test_header_and_footer_products_are_unusable_and_never_projected() -> None:
    tagged = _tag_events(
        _p(_begin("1", "PRODUCT") + "<hp:t>A</hp:t>" + _end("1")),
        {"PRODUCT": _slot("unsupported")},
    ).entries[SECTION]
    for kind in (ContentEntryKind.HEADER, ContentEntryKind.FOOTER):
        package = _xml_package(_p(""))
        entry = f"Contents/{kind.value}0.xml"
        package.entries[entry] = tagged

        inspection = inspect_product_bookmarks(scan_structural_boundaries(package))
        observation = next(item for item in inspection.observations if item.entry == entry)

        assert observation.classification is ProductClassification.KNOWN_PRODUCT
        assert observation.scope_role is ProductScopeRole.INVALID_PRODUCT
        assert not observation.scope_usable
        assert {item.kind for item in inspection.diagnostics} == {"unsupported-product-entry"}
        assert inspect_slots(package)[0] == ()


def test_unattributed_native_metatag_failure_closes_every_pair_in_entry() -> None:
    package = _write_tags(
        _native("R5-nested.hwpx"),
        {
            "S0_SLOT": _slot("slot"),
            "S0_OPT_A": _option("a"),
            "S0_OPT_B": _option("b"),
        },
    )
    root = etree.fromstring(package.entries[SECTION])
    begin = next(node for node in root.iter(f"{{{HP}}}fieldBegin") if node.get("name") == "S0_SLOT")
    etree.SubElement(begin, "{urn:foreign}metaTag").text = _slot("hidden")
    package.entries[SECTION] = serialize_modified_section(root)

    inspection = inspect_product_bookmarks(scan_structural_boundaries(package))

    assert inspection.observations
    assert all(
        item.scope_role is ProductScopeRole.INVALID_PRODUCT
        and not item.scope_usable
        and item.owning_slot_pair is None
        for item in inspection.observations
    )
    assert {item.kind for item in inspection.diagnostics} == {"bookmark-resolve-failed"}
    assert inspect_slots(package)[0] == ()


def test_unusable_topology_stays_core_owned_and_usable_contract_breaks_loudly() -> None:
    pair = BoundaryPairRef()
    begin = BookmarkBegin(pair, "OPTION", (_option("option"),), None)
    field_ambiguous = StructuralBoundaryScan(
        (
            StructuralEntryScan(
                SECTION,
                ContentEntryKind.SECTION,
                (begin, BookmarkEnd(pair)),
                False,
                False,
            ),
        ),
        (StructuralDiagnostic(SECTION, StructuralDiagnosticKind.FIELD_ORPHAN_END),),
    )

    inspection = inspect_product_bookmarks(field_ambiguous)

    assert {item.kind for item in inspection.diagnostics} == {"bookmark-resolve-failed"}
    assert inspection.observations[0].scope_role is ProductScopeRole.INVALID_PRODUCT
    assert not inspection.observations[0].scope_usable
    assert inspection.observations[0].owning_slot_pair is None

    broken_contract = StructuralBoundaryScan(
        (
            StructuralEntryScan(
                SECTION,
                ContentEntryKind.SECTION,
                (begin,),
                True,
                True,
            ),
        ),
        (),
    )
    with pytest.raises(ProductInspectionContractError, match="open pairs"):
        inspect_product_bookmarks(broken_contract)

    shared_pair = BoundaryPairRef()
    cross_kind_reuse = StructuralBoundaryScan(
        (
            StructuralEntryScan(
                SECTION,
                ContentEntryKind.SECTION,
                (
                    FieldBegin(shared_pair, "FIELD"),
                    BookmarkBegin(shared_pair, "OPTION", (_option("option"),), None),
                    BookmarkEnd(shared_pair),
                    FieldEnd(shared_pair),
                ),
                True,
                True,
            ),
        ),
        (),
    )
    with pytest.raises(ProductInspectionContractError, match="pair reused"):
        inspect_product_bookmarks(cross_kind_reuse)


@pytest.mark.parametrize(
    ("package", "expected"),
    (
        (
            _tag_events(
                _p(_begin("1", "A") + "<hp:t>A</hp:t>" + _end("1"))
                + _p(_begin("2", "B") + "<hp:t>B</hp:t>" + _end("2"))
                + _p("<hp:t>OUT</hp:t>"),
                {"A": _slot("same"), "B": _slot("same")},
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
                {"A": _slot("a"), "B": _slot("b"), "O": _option()},
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
                {"S": _slot(), "A": _option("a"), "B": _option("b")},
            ),
            {"nested-option"},
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
    if expected == {"nested-slot", "ambiguous-membership"}:
        assert _slots == (Slot("a", ()), Slot("b", ()))
    elif expected == {"nested-option"}:
        assert _slots == (
            Slot(
                "추가 지급 안내",
                (SlotOption("a", 0), SlotOption("b", 1)),
            ),
        )
    if expected in ({"duplicate-slot-id"}, {"duplicate-option-id"}):
        observations = inspect_product_bookmarks(scan_structural_boundaries(package)).observations
        duplicate_kind = "slot" if "duplicate-slot-id" in expected else "slot_option"
        duplicates = [item for item in observations if item.kind == duplicate_kind]
        assert len(duplicates) == 2
        assert duplicates[0].product_id == duplicates[1].product_id
        assert duplicates[0].pair is not duplicates[1].pair


def test_canonical_serializers_fix_schema_and_native_name_last() -> None:
    slot = Slot("추가 지급 안내", ())
    option = SlotOption("성과급 안내", 0)
    slot_raw = serialize_slot_metatag(slot)
    option_raw = serialize_slot_option_metatag(option)
    assert slot_raw.endswith('"name":"#hf"}')
    assert option_raw.endswith('"name":"#hf"}')
    assert json.loads(slot_raw) == {
        "hwpxFiller": {
            "kind": "slot",
            "id": "추가 지급 안내",
        },
        "name": "#hf",
    }
    assert json.loads(option_raw) == {
        "hwpxFiller": {"kind": "slot_option", "id": "성과급 안내"},
        "name": "#hf",
    }


def test_canonical_serializers_reject_invalid_ids() -> None:
    for value, serialize in (
        (Slot("", ()), serialize_slot_metatag),
        (SlotOption("", 0), serialize_slot_option_metatag),
    ):
        with pytest.raises(ValueError):
            serialize(value)  # type: ignore[arg-type]


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
    assert inspection.fields == ()
    assert inspection.status.field_n == 0
