"""Exact scan-pair admission and observation/action parity."""

from __future__ import annotations

from dataclasses import replace

import pytest

import hwpxcore.bookmark_region as bookmark_region_module
import hwpxcore.native_admission as native_admission_module
from hwpxcore.bookmark_region import (
    remove_bookmark_region,
    resolve_bookmark_regions,
    resolve_bookmark_topology,
)
from hwpxcore.native_admission import (
    BookmarkRemovalBlockerKind,
    FieldFillBlockerKind,
    FieldFillEffectKind,
    NativeAdmissionContractError,
    inspect_native_capabilities,
)
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxcore.structural_boundary import (
    BookmarkBegin,
    FieldBegin,
    StructuralBoundaryScan,
    scan_structural_boundaries,
)
from hwpxfiller.domain.fields import FieldDocument, FillNote

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
SECTION = "Contents/section0.xml"


def _paragraph(body: str) -> str:
    return f"<hp:p><hp:run>{body}</hp:run></hp:p>"


def _entry(body: str) -> bytes:
    return (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{body}</hs:sec>'
    ).encode()


def _package(body: str) -> HwpxPackage:
    return HwpxPackage(
        entries={
            MIMETYPE_NAME: MIMETYPE_VALUE,
            SECTION: _entry(body),
        },
        stored={MIMETYPE_NAME},
    )


def _field(value: str, *, name: str = "F") -> str:
    return (
        f'<hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl>'
        f"<hp:t>{value}</hp:t>"
        "<hp:ctrl><hp:fieldEnd/></hp:ctrl>"
    )


def _bookmark(value: str, *, pair_id: str = "1", name: str = "B") -> str:
    return (
        f'<hp:ctrl><hp:fieldBegin id="{pair_id}" type="BOOKMARK" '
        f'name="{name}"/></hp:ctrl>'
        f"<hp:t>{value}</hp:t>"
        f'<hp:ctrl><hp:fieldEnd beginIDRef="{pair_id}"/></hp:ctrl>'
    )


def test_inspection_keeps_exact_supplied_pairs_and_rejects_stale_or_detached_scan() -> None:
    pkg = _package(
        _paragraph(_field("OLD", name="F"))
        + _paragraph(_bookmark("IN", name="B"))
        + _paragraph("<hp:t>OUT</hp:t>")
    )
    pkg.entries["Contents/header.xml"] = _entry(
        _paragraph("<hp:t>STYLE</hp:t>")
    )
    before = dict(pkg.entries)
    scan = scan_structural_boundaries(pkg)
    field_pair = next(
        event.pair
        for event in scan.entries[0].events
        if isinstance(event, FieldBegin)
    )
    bookmark_pair = next(
        event.pair
        for event in scan.entries[0].events
        if isinstance(event, BookmarkBegin)
    )

    inspected = inspect_native_capabilities(pkg, scan)

    assert [item.pair for item in inspected.field_fills] == [field_pair]
    assert [item.pair for item in inspected.bookmark_removals] == [bookmark_pair]
    assert inspected.field_fills[0].fillable
    assert inspected.bookmark_removals[0].removable
    assert pkg.entries == before

    tampered_events = tuple(
        FieldBegin(event.pair, "OTHER")
        if isinstance(event, FieldBegin) and event.pair is field_pair
        else event
        for event in scan.entries[0].events
    )
    tampered = replace(
        scan,
        entries=(replace(scan.entries[0], events=tampered_events),),
    )
    with pytest.raises(NativeAdmissionContractError, match="evidence mismatch"):
        inspect_native_capabilities(pkg, tampered)

    pkg.entries[SECTION] = pkg.entries[SECTION].replace(b"OUT", b"TAIL")
    with pytest.raises(NativeAdmissionContractError, match="stale structural scan"):
        inspect_native_capabilities(pkg, scan)
    pkg.entries = before
    pkg.entries["Contents/header.xml"] = _entry(
        _paragraph(_field("NEW", name="LATE"))
    )
    with pytest.raises(NativeAdmissionContractError, match="stale structural scan"):
        inspect_native_capabilities(pkg, scan)
    pkg.entries = before
    pkg.entries["Contents/section1.xml"] = _entry(_paragraph("<hp:t>NEW</hp:t>"))
    with pytest.raises(NativeAdmissionContractError, match="entry roster"):
        inspect_native_capabilities(pkg, scan)
    pkg.entries.pop("Contents/section1.xml")
    detached = StructuralBoundaryScan(scan.entries, scan.diagnostics)
    with pytest.raises(NativeAdmissionContractError, match="public/private"):
        inspect_native_capabilities(pkg, detached)


@pytest.mark.parametrize(
    ("prefix", "value", "fillable", "kind"),
    (
        (
            "",
            "OLD<hp:markpenBegin/>X<hp:markpenEnd/>",
            True,
            FieldFillEffectKind.REMOVE_INLINE,
        ),
        (
            "",
            "OLD<hp:markpenBegin/>X",
            False,
            FieldFillBlockerKind.UNPAIRED_PROTECTED_RANGE,
        ),
        (
            "",
            'OLD<hp:insertBegin Id="7"/><hp:insertEnd Id="7"/>',
            False,
            FieldFillBlockerKind.UNPAIRED_PROTECTED_RANGE,
        ),
        (
            "",
            "OLD<hp:outer><hp:inner/></hp:outer>",
            False,
            FieldFillBlockerKind.UNSUPPORTED_INLINE_OBJECT,
        ),
        (
            "<hp:t><hp:markpenBegin/>BEFORE</hp:t>",
            "OLD",
            False,
            FieldFillBlockerKind.UNPAIRED_PROTECTED_RANGE,
        ),
    ),
)
def test_field_observation_and_writer_share_one_admission(
    prefix: str,
    value: str,
    fillable: bool,
    kind: FieldFillEffectKind | FieldFillBlockerKind,
) -> None:
    pkg = _package(
        _paragraph(prefix + _field(value)) + _paragraph("<hp:t>OUT</hp:t>")
    )
    observation = inspect_native_capabilities(
        pkg, scan_structural_boundaries(pkg)
    ).field_fills[0]
    doc = FieldDocument(pkg.entries[SECTION], entry=SECTION)
    before = doc.to_bytes()

    assert observation.fillable is fillable
    if fillable:
        assert kind in {effect.kind for effect in observation.supported_effects}
    else:
        assert kind in {blocker.kind for blocker in observation.blockers}
    assert doc.set_field("F", "NEW") is fillable
    if fillable:
        assert doc.read_field("F") == "NEW"
    else:
        assert doc.to_bytes() == before


def test_field_observation_types_a_protected_range_crossing() -> None:
    pkg = _package(
        _paragraph(
            '<hp:ctrl><hp:fieldBegin name="F"/></hp:ctrl>'
            "<hp:t>OLD<hp:markpenBegin/></hp:t>"
            "<hp:ctrl><hp:fieldEnd/></hp:ctrl>"
            "<hp:t>OUT<hp:markpenEnd/></hp:t>"
        )
        + _paragraph("<hp:t>TAIL</hp:t>")
    )

    observation = inspect_native_capabilities(
        pkg, scan_structural_boundaries(pkg)
    ).field_fills[0]
    doc = FieldDocument(pkg.entries[SECTION], entry=SECTION)
    before = doc.to_bytes()

    assert not observation.fillable
    assert FieldFillBlockerKind.PROTECTED_RANGE_CROSSING in {
        blocker.kind for blocker in observation.blockers
    }
    assert doc.set_field("F", "NEW") is False
    assert doc.notes == [FillNote("F", "occurrence_unfillable")]
    assert doc.modified is False
    assert doc.to_bytes() == before


@pytest.mark.parametrize(
    ("inline", "removable", "blocker"),
    (
        (
            "IN<hp:markpenBegin/>X<hp:markpenEnd/>",
            True,
            None,
        ),
        (
            "IN<hp:markpenBegin/>",
            False,
            BookmarkRemovalBlockerKind.UNPAIRED_PROTECTED_RANGE,
        ),
    ),
)
def test_bookmark_observation_and_remover_share_one_admission(
    inline: str,
    removable: bool,
    blocker: BookmarkRemovalBlockerKind | None,
) -> None:
    pkg = _package(
        _paragraph(_bookmark(inline)) + _paragraph("<hp:t>OUT</hp:t>")
    )
    observation = inspect_native_capabilities(
        pkg, scan_structural_boundaries(pkg)
    ).bookmark_removals[0]
    target = next(region for region in resolve_bookmark_topology(pkg) if region.name == "B")
    before = dict(pkg.entries)

    assert observation.removable is removable
    if blocker is not None:
        assert blocker in {item.kind for item in observation.blockers}
        with pytest.raises(ValueError, match="unpaired protected range"):
            remove_bookmark_region(pkg, target)
        assert pkg.entries == before
    else:
        remove_bookmark_region(pkg, target)
        assert b"OUT" in pkg.entries[SECTION]
        assert b"markpen" not in pkg.entries[SECTION]


def test_unpaired_external_range_and_malformed_metatag_fail_closed() -> None:
    external = _package(
        _paragraph("<hp:t><hp:markpenBegin/>BEFORE</hp:t>")
        + _paragraph(_bookmark("IN"))
        + _paragraph("<hp:t>OUT</hp:t>")
    )
    observation = inspect_native_capabilities(
        external, scan_structural_boundaries(external)
    ).bookmark_removals[0]
    target = resolve_bookmark_topology(external)[0]
    before = dict(external.entries)

    assert not observation.removable
    assert BookmarkRemovalBlockerKind.UNPAIRED_PROTECTED_RANGE in {
        item.kind for item in observation.blockers
    }
    with pytest.raises(ValueError, match="unpaired protected range"):
        remove_bookmark_region(external, target)
    assert external.entries == before

    malformed = _package(
        _paragraph(
            '<hp:ctrl><hp:fieldBegin id="1" type="BOOKMARK" name="B">'
            '<x:metaTag xmlns:x="urn:foreign">bad</x:metaTag>'
            "</hp:fieldBegin></hp:ctrl><hp:t>IN</hp:t>"
            '<hp:ctrl><hp:fieldEnd beginIDRef="1"/></hp:ctrl>'
        )
        + _paragraph("<hp:t>OUT</hp:t>")
    )
    malformed_scan = scan_structural_boundaries(malformed)
    malformed_observation = inspect_native_capabilities(
        malformed, malformed_scan
    ).bookmark_removals[0]

    assert not malformed_observation.removable
    assert BookmarkRemovalBlockerKind.BOOKMARK_METADATA_UNUSABLE in {
        item.kind for item in malformed_observation.blockers
    }
    with pytest.raises(ValueError, match="non-native namespace"):
        resolve_bookmark_topology(malformed)
    with pytest.raises(NativeAdmissionContractError, match="evidence mismatch"):
        inspect_native_capabilities(
            malformed, replace(malformed_scan, diagnostics=())
        )


def test_protected_index_is_built_once_per_entry_for_inspection_and_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg = _package(
        _paragraph("<hp:t>OUT0</hp:t>")
        + _paragraph(_bookmark("A", pair_id="1", name="A"))
        + _paragraph(_field("F", name="F"))
        + _paragraph(_bookmark("B", pair_id="2", name="B"))
        + _paragraph("<hp:t>OUT1</hp:t>")
    )
    scan = scan_structural_boundaries(pkg)
    inspect_calls = 0
    original_inspect_build = native_admission_module.build_native_admission_index

    class NoRescanNodes(tuple):
        def __iter__(self):
            raise AssertionError("native nodes were rescanned after indexing")

    def counted_inspect(*args, **kwargs):
        nonlocal inspect_calls
        inspect_calls += 1
        index = original_inspect_build(*args, **kwargs)
        return replace(index, nodes=NoRescanNodes(index.nodes))

    monkeypatch.setattr(
        native_admission_module, "build_native_admission_index", counted_inspect
    )
    inspected = inspect_native_capabilities(pkg, scan)
    assert len(inspected.bookmark_removals) == 2
    assert inspect_calls == 1

    preflight_calls = 0
    original_preflight_build = bookmark_region_module.build_native_admission_index

    def counted_preflight(*args, **kwargs):
        nonlocal preflight_calls
        preflight_calls += 1
        index = original_preflight_build(*args, **kwargs)
        return replace(index, nodes=NoRescanNodes(index.nodes))

    monkeypatch.setattr(
        bookmark_region_module, "build_native_admission_index", counted_preflight
    )
    assert len(resolve_bookmark_regions(pkg)) == 2
    assert preflight_calls == 1
