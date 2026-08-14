"""Entry-local Field/BOOKMARK structural boundary scan contract."""

from __future__ import annotations

from _ordinary_field_grammar import UNSUPPORTED_FIELD_GRAMMAR

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxcore.structural_boundary import (
    BookmarkBegin,
    BookmarkEnd,
    ContentEntryKind,
    FieldBegin,
    FieldEnd,
    StructuralDiagnosticKind,
    scan_structural_boundaries,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
SECTION = "Contents/section0.xml"


def _package(entries: dict[str, bytes]) -> HwpxPackage:
    return HwpxPackage(
        entries={MIMETYPE_NAME: MIMETYPE_VALUE, **entries},
        stored={MIMETYPE_NAME},
    )


def _entry(body: str, *, root: str = "hs:sec", namespaces: str = "") -> bytes:
    return (
        f'<{root} xmlns:hs="{HS}" xmlns:hp="{HP}" {namespaces}>'
        f"{body}</{root}>"
    ).encode()


def _paragraph(body: str = "") -> str:
    return f"<hp:p><hp:run>{body}</hp:run></hp:p>"


def _begin(pair_id: int, name: str, *, kind: str = "BOOKMARK", extra: str = "") -> str:
    return (
        f'<hp:ctrl><hp:fieldBegin id="{pair_id}" type="{kind}" '
        f'name="{name}"{extra}/></hp:ctrl>'
    )


def _end(pair_id: int, *, prefix: str = "hp") -> str:
    return f'<{prefix}:ctrl><{prefix}:fieldEnd beginIDRef="{pair_id}"/></{prefix}:ctrl>'


def _bookmark(pair_id: int, name: str) -> str:
    return _begin(pair_id, name) + "<hp:t>값</hp:t>" + _end(pair_id)


def test_projects_supported_entries_in_deterministic_native_order() -> None:
    mixed = _entry(
        _paragraph(
            '<hp:ctrl><hp:fieldBegin id="7" type="CLICK_HERE" name="FIELD"/>'
            '<hp:fieldBegin id="8" type="BOOKMARK" name="MARK" metaTag="legacy">'
            "<hp:parameters/><hp:metaTag>one</hp:metaTag><hp:metaTag>two</hp:metaTag>"
            "</hp:fieldBegin></hp:ctrl>"
            "<hp:t>값<hp:markpenBegin/></hp:t>"
            '<hp:ctrl><hp:fieldEnd beginIDRef="8"/>'
            '<hp:fieldEnd beginIDRef="7"/></hp:ctrl>'
        )
    )
    entries = {
        "Contents/footer10.xml": _entry(_paragraph()),
        "Contents/header2.xml": _entry(_paragraph()),
        "Contents/section10.xml": _entry(_paragraph()),
        "Contents/section2.xml": mixed,
        "A/section2.xml": _entry(
            _paragraph(
                "<hp:tbl><hp:tr><hp:tc><hp:subList>"
                + _paragraph(_bookmark(8, "REMOTE") + _bookmark(9, "NEXT"))
                + "</hp:subList></hp:tc></hp:tr></hp:tbl>"
            )
        ),
        "Contents/footer1.xml": _entry(_paragraph()),
        "Contents/header1.xml": _entry(_paragraph()),
        "Contents/header.xml": (
            '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"/>'
        ).encode(),
        "Contents/headerCustom.xml": _entry(_paragraph()),
    }
    package = _package(entries)
    before = dict(package.entries)

    scan = scan_structural_boundaries(package)

    assert [(item.kind, item.entry) for item in scan.entries] == [
        (ContentEntryKind.SECTION, "A/section2.xml"),
        (ContentEntryKind.SECTION, "Contents/section2.xml"),
        (ContentEntryKind.SECTION, "Contents/section10.xml"),
        (ContentEntryKind.HEADER, "Contents/header1.xml"),
        (ContentEntryKind.HEADER, "Contents/header2.xml"),
        (ContentEntryKind.FOOTER, "Contents/footer1.xml"),
        (ContentEntryKind.FOOTER, "Contents/footer10.xml"),
    ]
    assert not scan.diagnostics
    assert [type(event) for event in scan.entries[0].events] == [
        BookmarkBegin,
        BookmarkEnd,
        BookmarkBegin,
        BookmarkEnd,
    ]
    projected = scan.entries[1].events
    assert [type(event) for event in projected] == [
        FieldBegin,
        BookmarkBegin,
        BookmarkEnd,
        FieldEnd,
    ]
    assert projected[0].raw_name == "FIELD"
    assert projected[1].bookmark_name == "MARK"
    assert projected[1].meta_tags == ("one", "two")
    assert projected[1].meta_tag_attribute == "legacy"
    assert projected[0].pair is projected[3].pair
    assert projected[1].pair is projected[2].pair
    assert projected[0].pair is not projected[1].pair
    assert scan.entries[0].events[0].pair is not projected[1].pair
    assert (
        scan.entries[1].field_pairing_usable,
        scan.entries[1].bookmark_topology_usable,
    ) == (True, True)
    assert package.entries == before


def test_keeps_entry_trust_independent_without_cross_entry_repair() -> None:
    package = _package(
        {
            SECTION: _entry(
                _paragraph(
                    _begin(1, "FIELD", kind="CLICK_HERE")
                    + "<hp:t>값</hp:t>"
                    + _end(1)
                    + _begin(7, "LOCAL_MISSING")
                )
            ),
            "Contents/section1.xml": _entry(
                _paragraph(
                    _begin(20, "LEFT")
                    + _begin(21, "RIGHT")
                    + _end(20)
                    + _end(21)
                )
            ),
            "Contents/header0.xml": _entry(
                _paragraph(
                    _begin(1, "FIELD", kind="CLICK_HERE")
                    + _bookmark(7, "REMOTE_VALID")
                )
            ),
            "Contents/footer0.xml": _entry(_paragraph(_end(7))),
            "Contents/footer1.xml": _entry(
                _paragraph(_bookmark(8, "LOCAL_VALID") + _end(99, prefix="x")),
                namespaces='xmlns:x="urn:foreign"',
            ),
            "Contents/footer2.xml": _entry(
                _paragraph(
                    _bookmark(9, "LOCAL_VALID")
                    + '<hp:fieldEnd beginIDRef="100"/>'
                )
            ),
        }
    )

    scan = scan_structural_boundaries(package)
    by_entry = {item.entry: item for item in scan.entries}

    assert (
        by_entry[SECTION].field_pairing_usable,
        by_entry[SECTION].bookmark_topology_usable,
    ) == (True, False)
    assert [type(event) for event in by_entry[SECTION].events] == [FieldBegin, FieldEnd]
    assert (
        by_entry["Contents/section1.xml"].field_pairing_usable,
        by_entry["Contents/section1.xml"].bookmark_topology_usable,
    ) == (True, False)
    assert (
        by_entry["Contents/header0.xml"].field_pairing_usable,
        by_entry["Contents/header0.xml"].bookmark_topology_usable,
    ) == (False, True)
    assert [type(event) for event in by_entry["Contents/header0.xml"].events] == [
        BookmarkBegin,
        BookmarkEnd,
    ]
    assert (
        by_entry["Contents/footer0.xml"].field_pairing_usable,
        by_entry["Contents/footer0.xml"].bookmark_topology_usable,
    ) == (False, False)
    assert (
        by_entry["Contents/footer1.xml"].field_pairing_usable,
        by_entry["Contents/footer1.xml"].bookmark_topology_usable,
    ) == (False, False)
    assert [type(event) for event in by_entry["Contents/footer1.xml"].events] == [
        BookmarkBegin,
        BookmarkEnd,
    ]
    assert (
        by_entry["Contents/footer2.xml"].field_pairing_usable,
        by_entry["Contents/footer2.xml"].bookmark_topology_usable,
    ) == (False, False)
    assert [type(event) for event in by_entry["Contents/footer2.xml"].events] == [
        BookmarkBegin,
        BookmarkEnd,
    ]
    assert {(item.entry, item.kind) for item in scan.diagnostics} >= {
        (SECTION, StructuralDiagnosticKind.BOOKMARK_MISSING_END),
        ("Contents/section1.xml", StructuralDiagnosticKind.BOOKMARK_CROSSING),
        ("Contents/header0.xml", StructuralDiagnosticKind.FIELD_UNMATCHED_BEGIN),
        ("Contents/footer0.xml", StructuralDiagnosticKind.FIELD_ORPHAN_END),
        ("Contents/footer1.xml", StructuralDiagnosticKind.FIELD_NON_NATIVE_CONTROL),
        (
            "Contents/footer2.xml",
            StructuralDiagnosticKind.FIELD_UNSUPPORTED_CONTROL_SHAPE,
        ),
    }


def test_reports_typed_format_diagnostics() -> None:
    malformed_unsupported = (
        _entry(_paragraph(_bookmark(2, "MALFORMED"))).decode()[:-1].encode("utf-16")
    )
    entity_entry = (
        '<!DOCTYPE hs:sec [<!ENTITY hidden \''
        '<hp:ctrl><hp:fieldBegin id="77" type="BOOKMARK" name="HIDDEN"/>'
        '<hp:fieldEnd beginIDRef="77"/></hp:ctrl>\'>]>'
    ).encode() + _entry(_paragraph("&hidden;"))
    format_cases = {
        "package": (
            _package(
                {
                    "Contents/headerCustom.xml": _entry(
                        _paragraph(_bookmark(1, "UNSUPPORTED"))
                    ).decode().encode("utf-16")
                }
            ),
            {
                StructuralDiagnosticKind.MISSING_SECTION_ENTRY,
                StructuralDiagnosticKind.UNSUPPORTED_CONTENT_ENTRY,
            },
        ),
        "xml": (
            _package({SECTION: b"<hs:sec"}),
            {StructuralDiagnosticKind.MALFORMED_XML},
        ),
        "malformed-unsupported": (
            _package(
                {
                    SECTION: _entry(_paragraph()),
                    "Contents/headerCustom.xml": malformed_unsupported,
                }
            ),
            {StructuralDiagnosticKind.UNSUPPORTED_CONTENT_ENTRY},
        ),
        "entity": (
            _package({SECTION: entity_entry}),
            {StructuralDiagnosticKind.MALFORMED_XML},
        ),
        "root": (
            _package(
                {
                    SECTION: _entry(
                        "<hp:p/>", root="x:sec", namespaces='xmlns:x="urn:foreign"'
                    )
                }
            ),
            {StructuralDiagnosticKind.INVALID_ENTRY_ROOT},
        ),
        "envelope": (
            _package({SECTION: _entry("<hp:foo/>")}),
            {StructuralDiagnosticKind.INVALID_CONTENT_ENVELOPE},
        ),
        "namespace": (
            _package(
                {
                    SECTION: _entry(
                        _paragraph(
                            '<hp:ctrl><x:fieldBegin id="2" type="BOOKMARK"/>'
                            "</hp:ctrl>"
                        ),
                        namespaces='xmlns:x="urn:foreign"',
                    )
                }
            ),
            {StructuralDiagnosticKind.NON_NATIVE_BOUNDARY},
        ),
        "metatag": (
            _package(
                {
                    SECTION: _entry(
                        _paragraph(
                            '<hp:ctrl><hp:fieldBegin id="1" type="BOOKMARK">'
                            "<x:metaTag>foreign</x:metaTag>"
                            "<hp:metaTag><hp:t>nested</hp:t></hp:metaTag>"
                            "<hp:metaTag>valid</hp:metaTag>"
                            "</hp:fieldBegin></hp:ctrl>"
                            + _end(1)
                        ),
                        namespaces='xmlns:x="urn:foreign"',
                    )
                }
            ),
            {
                StructuralDiagnosticKind.NON_NATIVE_METATAG,
                StructuralDiagnosticKind.INVALID_METATAG_SHAPE,
            },
        ),
        "control-shape": (
            _package(
                {
                    SECTION: _entry(
                        _paragraph('<hp:fieldBegin id="1" type="BOOKMARK"/>')
                    )
                }
            ),
            {StructuralDiagnosticKind.UNSUPPORTED_BOOKMARK_CONTROL_SHAPE},
        ),
        "traversal-lane": (
            _package(
                {
                    SECTION: _entry(
                        _paragraph(
                            "<hp:foo><hp:subList><hp:p><hp:run><hp:ctrl>"
                            '<hp:fieldBegin id="1" type="BOOKMARK"/>'
                            "</hp:ctrl></hp:run></hp:p></hp:subList></hp:foo>"
                        )
                    )
                }
            ),
            {StructuralDiagnosticKind.UNSUPPORTED_BOOKMARK_TRAVERSAL_LANE},
        ),
        "missing-id": (
            _package(
                {
                    SECTION: _entry(
                        _paragraph('<hp:ctrl><hp:fieldBegin type="BOOKMARK"/></hp:ctrl>')
                    )
                }
            ),
            {StructuralDiagnosticKind.BOOKMARK_BEGIN_MISSING_ID},
        ),
        "duplicate-id": (
            _package(
                {
                    SECTION: _entry(
                        _paragraph(_begin(1, "A") + _begin(1, "B") + _end(1))
                    )
                }
            ),
            {StructuralDiagnosticKind.BOOKMARK_DUPLICATE_BEGIN_ID},
        ),
        "missing-end": (
            _package({SECTION: _entry(_paragraph(_begin(1, "A")))}),
            {StructuralDiagnosticKind.BOOKMARK_MISSING_END},
        ),
        "ambiguous-end": (
            _package(
                {SECTION: _entry(_paragraph(_begin(1, "A") + _end(1) + _end(1)))}
            ),
            {StructuralDiagnosticKind.BOOKMARK_AMBIGUOUS_END},
        ),
        "end-before-begin": (
            _package({SECTION: _entry(_paragraph(_end(1) + _begin(1, "A")))}),
            {StructuralDiagnosticKind.BOOKMARK_END_PRECEDES_BEGIN},
        ),
        "end-control-shape": (
            _package(
                {
                    SECTION: _entry(
                        _paragraph(
                            _begin(1, "A")
                            + '<hp:fieldEnd beginIDRef="1"/>'
                        )
                    )
                }
            ),
            {StructuralDiagnosticKind.UNSUPPORTED_BOOKMARK_CONTROL_SHAPE},
        ),
        "foreign-end": (
            _package(
                {
                    SECTION: _entry(
                        _paragraph(_begin(1, "A") + _end(1, prefix="x")),
                        namespaces='xmlns:x="urn:foreign"',
                    )
                }
            ),
            {
                StructuralDiagnosticKind.NON_NATIVE_BOUNDARY,
                StructuralDiagnosticKind.BOOKMARK_MISSING_END,
            },
        ),
    }
    for name, (package, expected) in format_cases.items():
        result = scan_structural_boundaries(package)
        actual = {item.kind for item in result.diagnostics}
        assert actual == expected, name
        if name == "metatag":
            entry = result.entries[0]
            assert entry.bookmark_topology_usable
            assert [type(event) for event in entry.events] == [
                BookmarkBegin,
                BookmarkEnd,
            ]
            assert entry.events[0].meta_tags == ("valid",)
        elif name == "entity":
            entry = result.entries[0]
            assert (
                entry.field_pairing_usable,
                entry.bookmark_topology_usable,
                entry.events,
            ) == (False, False, ())

    field_kinds = {
        "unmatched-begin": StructuralDiagnosticKind.FIELD_UNMATCHED_BEGIN,
        "orphan-end": StructuralDiagnosticKind.FIELD_ORPHAN_END,
        "ambiguous-end": StructuralDiagnosticKind.FIELD_AMBIGUOUS_END,
        "nested-field": StructuralDiagnosticKind.FIELD_NESTED,
        "non-native-field-control": StructuralDiagnosticKind.FIELD_NON_NATIVE_CONTROL,
        "unsupported-control-shape": (
            StructuralDiagnosticKind.FIELD_UNSUPPORTED_CONTROL_SHAPE
        ),
        "unsupported-traversal-lane": (
            StructuralDiagnosticKind.FIELD_UNSUPPORTED_TRAVERSAL_LANE
        ),
        "paragraph-crossing": StructuralDiagnosticKind.FIELD_PARAGRAPH_CROSSING,
        "unsupported-container-crossing": (
            StructuralDiagnosticKind.FIELD_UNSUPPORTED_CONTAINER_CROSSING
        ),
    }
    field_cases = (
        "paragraph_crossing",
        "container_crossing",
        "nested_fields",
        "ambiguous_end",
        "foreign_namespace",
        "marker_outside_control",
        "mixed_pair_identity",
        "unmatched_begin",
        "non_run_lane_gap",
    )
    for name in field_cases:
        case = UNSUPPORTED_FIELD_GRAMMAR[name]
        scan = scan_structural_boundaries(_package({case.entry: case.xml}))
        assert field_kinds[case.unsupported_kind] in {
            item.kind for item in scan.diagnostics
        }, name
