import json

from hwpxfiller.core.engine import HwpxEngine
from hwpxfiller.core.fill_ledger import (
    LEDGER_SIDECAR_NAME,
    StructureState,
    ValueState,
    build_fill_ledger,
    export_run_ledger,
    ledger_outputs,
    manifest_rows,
    template_structure_drift,
    template_path_drift,
    verify_output,
)
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.source_profile import profile_fields
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
        FieldMapping("공고명", "name"),
        FieldMapping("비고", type="blank"),
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
        FieldMapping("공고명", "name"),
        FieldMapping("공고명", type="blank"),
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


# ==================================================================== L2 원장 export
MARKER = "〘미입력·{field}〙"


def test_manifest_rows_statuses_and_previews():
    rows = {r.field: r for r in manifest_rows(
        _mapping(), ["공고명", "비고", "신규"],
        {"공고명": "관급자재 구매"},
    )}
    assert rows["공고명"].status == "filled"
    assert rows["공고명"].preview_text == "관급자재 구매"
    assert rows["공고명"].source == "name"
    assert rows["비고"].status == "blank" and rows["비고"].preview_text == ""
    assert rows["신규"].status == "drift"
    # 전 행이 미검증 상태(dry-run) — injected 는 증거이지 추정이 아니다.
    assert all(r.injected is None for r in rows.values())


def test_manifest_rows_marker_counts_as_missing_but_records_real_value():
    marked = MARKER.format(field="공고명")
    (row,) = [r for r in manifest_rows(
        _mapping(), ["공고명", "비고"], {"공고명": marked}, missing_marker=MARKER,
    ) if r.field == "공고명"]
    assert row.status == "missing"
    assert row.preview_text == marked  # 원장은 실제 들어가는 값을 그대로 기록


def test_verify_output_reads_back_evidence(tmp_path):
    template = tmp_path / "t.hwpx"
    _template(template, ["공고명", "비고"])
    out = tmp_path / "doc.hwpx"
    res = HwpxEngine().generate(str(template), {"공고명": "실제값"}, str(out))
    assert res.ok

    rows = manifest_rows(_mapping(), ["공고명", "비고"], {"공고명": "실제값"})
    verified = {r.field: r for r in verify_output(str(out), rows)}
    assert verified["공고명"].injected is True and verified["공고명"].read_back == ""
    assert verified["비고"].injected is None  # 공란 선언 — 검증 대상 아님

    # 기대값이 문서 실값과 다르면 증거로 불일치를 남긴다(주장 ≠ 관측).
    lying = manifest_rows(_mapping(), ["공고명", "비고"], {"공고명": "다른값"})
    bad = {r.field: r for r in verify_output(str(out), lying)}
    assert bad["공고명"].injected is False
    assert bad["공고명"].read_back == "실제값"


def test_ledger_outputs_verifies_success_and_keeps_failure_loud(tmp_path):
    template = tmp_path / "t.hwpx"
    _template(template, ["공고명", "비고"])
    out = tmp_path / "doc.hwpx"
    res = HwpxEngine().generate(str(template), {"공고명": "가"}, str(out))
    entries = ledger_outputs(
        [res], [{"공고명": "가"}], _mapping(), ["공고명", "비고"],
    )
    assert entries[0].ok and entries[0].verify_error == ""
    assert {r.field: r.injected for r in entries[0].rows}["공고명"] is True

    # 산출물이 사라지면 되읽기 실패가 조용한 통과가 아니라 verify_error 로 남는다.
    out.unlink()
    (entry,) = ledger_outputs(
        [res], [{"공고명": "가"}], _mapping(), ["공고명", "비고"],
    )
    assert entry.verify_error.startswith("되읽기 실패")


def test_export_redacts_service_key_and_notes_no_render(tmp_path):
    template = tmp_path / "t.hwpx"
    _template(template, ["공고명", "비고"])
    out = tmp_path / "doc.hwpx"
    leaky = "https://apis.example/x?ServiceKey=TOPSECRET&y=1"
    res = HwpxEngine().generate(str(template), {"공고명": leaky}, str(out))
    entries = ledger_outputs([res], [{"공고명": leaky}], _mapping(), ["공고명", "비고"])
    sidecar = tmp_path / LEDGER_SIDECAR_NAME
    payload = export_run_ledger(
        sidecar,
        template=str(template),
        source="file:data.xlsx",
        outputs=entries,
        job_name="작업",
        profiles=profile_fields([{"name": leaky}], ["name"]),
        generated_at="2026-07-12T00:00:00",
    )
    text = sidecar.read_text(encoding="utf-8")
    # 키 비직렬화 — 값·프로파일 샘플 어디에도 비밀이 남지 않는다(N1 관통).
    assert "TOPSECRET" not in text and "[REDACTED]" in text
    assert payload["kind"] == "hwpx-fill-ledger"
    assert "렌더" in payload["note"]  # 값 미리보기 ≠ HWPX 렌더(ADR C)
    assert json.loads(text) == payload


# ------------------------------------------------- 실행별 사이드카 경로(RC-02)
def test_ledger_sidecar_path_is_timestamped(tmp_path):
    from hwpxfiller.core.fill_ledger import ledger_sidecar_path

    p = ledger_sidecar_path(tmp_path, "2026-07-12T14:05:03")
    assert p == tmp_path / "fill-ledger-20260712-140503.json"


def test_ledger_sidecar_path_same_second_accumulates(tmp_path):
    """같은 초 재실행 — 기존 증거를 덮지 않고 접미사로 비켜 간다(증거는 축적)."""
    from hwpxfiller.core.fill_ledger import ledger_sidecar_path

    first = ledger_sidecar_path(tmp_path, "2026-07-12T14:05:03")
    first.write_text("{}", encoding="utf-8")
    second = ledger_sidecar_path(tmp_path, "2026-07-12T14:05:03")
    assert second == tmp_path / "fill-ledger-20260712-140503-1.json"
    assert second != first and first.exists()


def test_ledger_records_fill_notes_as_evidence(tmp_path):
    """완화 사실(#154)은 원장 사이드카에 남는다 — "왜 표식이 사라졌나"의 사후 복원."""
    from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

    sec = (
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
        ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        '<hp:run><hp:ctrl><hp:fieldBegin name="공고명"/></hp:ctrl></hp:run>'
        "<hp:run><hp:t>OLD<hp:markpenBegin/>X</hp:t></hp:run>"
        "<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>"
        "</hp:p></hs:sec>"
    ).encode("utf-8")
    template = tmp_path / "t.hwpx"
    HwpxPackage(
        entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": sec}
    ).save(str(template))
    out = tmp_path / "doc.hwpx"
    res = HwpxEngine().generate(str(template), {"공고명": "가"}, str(out))
    assert res.notes  # 선조건: 완화가 실제 발생

    (entry,) = ledger_outputs([res], [{"공고명": "가"}], _mapping(), ["공고명"])
    payload = entry.to_dict()
    assert payload["notes"] == [
        {"field": "공고명", "kind": "inline_stripped", "detail": ["markpenBegin"]}
    ]
