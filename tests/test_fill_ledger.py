from hwpxfiller.core.fill_ledger import (
    StructureState,
    ValueState,
    build_fill_ledger,
    template_structure_drift,
    template_path_drift,
)
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage


def _template(path, fields):
    body = "".join(
        f'<hp:run><hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl></hp:run>'
        f'<hp:run><hp:t>{{{{{name}}}}}</hp:t></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        for name in fields
    )
    xml = (
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        + body + '</hp:p></hs:sec>'
    ).encode()
    HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}).save(str(path))


def _mapping():
    return MappingProfile(mappings=[
        FieldMapping("공고명", ["name"]),
        FieldMapping("비고", transform="blank"),
    ])


def test_symmetric_difference_preserves_both_directions():
    drift = template_structure_drift(["공고명", "신규필드"], _mapping())
    assert drift.template_uncovered == ("신규필드",)
    assert drift.mapping_orphaned == ("비고",)
    assert drift.symmetric_difference == {"신규필드", "비고"}


def test_declared_blank_completes_coverage_quietly():
    drift = template_structure_drift(["공고명", "비고"], _mapping())
    assert not drift.has_drift


def test_structure_and_value_axes_are_independent():
    ledger = build_fill_ledger(
        ["공고명", "비고"], _mapping(), source_fields=[], empty_values=["공고명"]
    )
    assert ledger.structure_state is StructureState.SOURCE_DRIFT
    assert ledger.source_structure_drift and not ledger.template_structure_drift
    assert ledger.value_state is ValueState.EMPTY


def test_mapping_blank_conflict_fails_closed():
    mapping = MappingProfile(mappings=[
        FieldMapping("공고명", ["name"]),
        FieldMapping("공고명", transform="blank"),
    ])
    drift = template_structure_drift(["공고명"], mapping)
    assert drift.has_drift and drift.conflicting == ("공고명",)


def test_template_path_seam_reloads_and_fails_closed(tmp_path):
    path = tmp_path / "t.hwpx"
    _template(path, ["공고명", "비고"])
    assert not template_path_drift(str(path), _mapping()).has_drift
    _template(path, ["공고명", "비고", "신규"])
    assert template_path_drift(str(path), _mapping()).template_uncovered == ("신규",)
    path.write_bytes(b"broken")
    assert template_path_drift(str(path), _mapping()).read_error
