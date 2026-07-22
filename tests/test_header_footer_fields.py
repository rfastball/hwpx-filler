"""#186 — body/header/footer 필드 채움·보존·diff 위치의 합성 왕복 계약."""

from __future__ import annotations

from lxml import etree

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxcore.text_extract import extract_document
from hwpxdiff.diff import diff_files
from hwpxfiller.core.engine import HwpxEngine
from hwpxfiller.core.fields import FieldDocument, field_xml_names, read_fields

BODY = "Contents/section0.xml"
UNTOUCHED_BODY = "Contents/section1.xml"
HEADER = "Contents/header0.xml"
FOOTER = "Contents/footer0.xml"
STYLE_HEADER = "Contents/header.xml"


def _field_part(label: str, field: str, value: str, *, unknown: str = "") -> bytes:
    return (
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
        f'data-preserve="{label}">'
        f"{unknown}"
        f"<hp:p><hp:run><hp:t>{label} 계약명: </hp:t></hp:run>"
        f'<hp:run><hp:ctrl><hp:fieldBegin name="{field}"/></hp:ctrl></hp:run>'
        f"<hp:run><hp:t>{value}</hp:t></hp:run>"
        "<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>"
        f"<hp:p><hp:run><hp:t>{label} 의미 보존</hp:t></hp:run></hp:p>"
        "</hs:sec>"
    ).encode()


def _style_header() -> bytes:
    return (
        '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:refList data-preserve="style"/></hh:head>'
    ).encode()


def _package_path(tmp_path, name: str = "template.hwpx", *, unknown=""):
    # 일부러 footer→header→body 역순으로 넣어 ZIP 순서가 필드 의미에 새지 않게 한다.
    pkg = HwpxPackage(
        entries={
            MIMETYPE_NAME: MIMETYPE_VALUE,
            FOOTER: _field_part("꼬리말", "공통", "꼬리말 구값"),
            HEADER: _field_part(
                "머리말",
                "공통",
                "머리말 구값",
                unknown=unknown,
            ),
            UNTOUCHED_BODY: _field_part("본문2", "유지필드", "유지값"),
            BODY: _field_part("본문", "공통", "본문 구값"),
            STYLE_HEADER: _style_header(),
            "BinData/keep.bin": b"\x00unchanged\xff",
        },
        stored={MIMETYPE_NAME},
    )
    path = tmp_path / name
    pkg.save(str(path))
    return path


def test_field_part_order_and_same_name_first_value_are_explicit(tmp_path):
    path = _package_path(tmp_path)
    pkg = HwpxPackage.open(str(path))

    assert field_xml_names(pkg) == [BODY, UNTOUCHED_BODY, HEADER, FOOTER]
    assert HwpxEngine().required_fields(str(path)) == ["공통", "유지필드"]
    assert read_fields(str(path)) == {"공통": "본문 구값", "유지필드": "유지값"}


def test_generate_fills_same_name_in_body_header_footer_and_preserves_other_parts(
    tmp_path,
):
    template = _package_path(tmp_path)
    before = HwpxPackage.open(str(template))
    output = tmp_path / "filled.hwpx"

    result = HwpxEngine().generate(str(template), {"공통": "새 계약값"}, str(output))

    assert result.ok, result.error
    assert result.applied == {"공통"}
    assert result.unmatched == set()
    after = HwpxPackage.open(str(output))
    for part in (BODY, HEADER, FOOTER):
        doc = FieldDocument(after.entries[part])
        assert doc.read_field("공통") == "새 계약값"
        root = etree.fromstring(after.entries[part])
        label = root.get("data-preserve")
        assert label in {"본문", "머리말", "꼬리말"}
        assert f"{label} 의미 보존" in "".join(root.itertext())

    for untouched in (UNTOUCHED_BODY, STYLE_HEADER, "BinData/keep.bin"):
        assert after.entries[untouched] == before.entries[untouched]
    assert FieldDocument(after.entries[UNTOUCHED_BODY]).read_field("유지필드") == "유지값"


def test_header_footer_changes_surface_with_region_locations(tmp_path):
    template = _package_path(tmp_path)
    output = tmp_path / "filled.hwpx"
    result = HwpxEngine().generate(str(template), {"공통": "새 계약값"}, str(output))
    assert result.ok, result.error

    diff = diff_files(str(template), str(output))
    changed_regions = {
        change.location["region"]
        for change in diff.changes
        if change.kind == "changed"
    }
    assert changed_regions == {"본문", "머리말", "꼬리말"}
    for region in changed_regions:
        assert any(
            change.location["region"] == region
            and change.location_label.startswith(f"{region} 1 · 문단")
            for change in diff.changes
        )


def test_unknown_header_structure_is_recorded_in_coverage_ledger(tmp_path):
    unknown = '<hp:futureHeader data-contract="unsupported"/>'
    path = _package_path(tmp_path, unknown=unknown)

    doc = extract_document(str(path))

    assert doc.unhandled == {"futureHeader": 1}
    assert "header0" in doc.unhandled_examples["futureHeader"]


def test_field_bearing_unsupported_header_part_fails_loudly(tmp_path):
    pkg = HwpxPackage(
        entries={
            MIMETYPE_NAME: MIMETYPE_VALUE,
            "Contents/headerCustom.xml": _field_part(
                "미지원 머리말", "공통", "구값"
            ),
        },
        stored={MIMETYPE_NAME},
    )
    template = tmp_path / "unsupported.hwpx"
    output = tmp_path / "must-not-exist.hwpx"
    pkg.save(str(template))

    result = HwpxEngine().generate(str(template), {"공통": "새값"}, str(output))

    assert not result.ok
    assert "지원하지 않는 필드 XML 파트" in result.error
    assert "headerCustom.xml" in result.error
    assert not output.exists()
