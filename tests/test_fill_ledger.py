"""템플릿-구조 드리프트(Domain)와 managed 배달 원장 사이드카(External).

legacy 생성 원장(``FillLedger``·매핑 행·값 미리보기·되읽기 행·원천 프로파일 —
``hwpx-fill-ledger``)은 legacy 생성기와 함께 #1081 PR3 에서 퇴역했다. 생성 원장은 GUI 와
CLI 가 같이 쓰는 ``managed-delivery/v1`` 이다.
"""
import json

from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.domain.fields import FillNote
from hwpxfiller.domain.fill_ledger import (
    template_structure_drift,
    template_path_drift,
)
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.delivery_coordinator import (
    DeliveredDocument,
    DeliveryAborted,
    DeliveryCompleted,
)
from hwpxfiller.external.ledger_export import write_managed_delivery_ledger
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
    write_hwpx_package(
        path,
        HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}),
    )


def _mapping():
    return MappingProfile(mappings=[
        FieldMapping("공고명", "name"),
        FieldMapping("비고", type="const"),   # 명시적 비움 = 빈 고정값
    ])


def test_symmetric_difference_preserves_both_directions():
    drift = template_structure_drift(["공고명", "신규필드"], _mapping())
    assert drift.template_uncovered == ("신규필드",)
    assert drift.mapping_orphaned == ("비고",)
    assert drift.symmetric_difference == {"신규필드", "비고"}


def test_declared_blank_completes_coverage_quietly():
    drift = template_structure_drift(["공고명", "비고"], _mapping())
    assert not drift.has_drift


def test_mapping_duplicate_conflict_fails_closed():
    mapping = MappingProfile(mappings=[
        FieldMapping("공고명", "name"),
        FieldMapping("공고명", type="const"),
    ])
    drift = template_structure_drift(["공고명"], mapping)
    assert drift.has_drift and drift.conflicting == ("공고명",)


def test_template_path_seam_reloads_and_fails_closed(tmp_path):
    path = tmp_path / "t.hwpx"
    _template(path, ["공고명", "비고"])
    assert not template_path_drift(str(path), _mapping(), engine=make_hwpx_engine()).has_drift
    _template(path, ["공고명", "비고", "신규"])
    assert template_path_drift(str(path), _mapping(), engine=make_hwpx_engine()).template_uncovered == ("신규",)
    path.write_bytes(b"broken")
    assert template_path_drift(str(path), _mapping(), engine=make_hwpx_engine()).read_error


# ------------------------------------------------- 실행별 사이드카 경로(RC-02)
def test_ledger_sidecar_path_is_timestamped(tmp_path):
    from hwpxfiller.external.ledger_export import ledger_sidecar_path

    p = ledger_sidecar_path(tmp_path, "2026-07-12T14:05:03")
    assert p == tmp_path / "fill-ledger-20260712-140503.json"
    # 비정상(초 해상도 미만) 입력도 조용히 덮지 않는다 — 접미사 루프를 같은 이름으로 탄다.
    assert ledger_sidecar_path(tmp_path, "") == tmp_path / "fill-ledger.json"


def test_ledger_sidecar_path_same_second_accumulates(tmp_path):
    """같은 초 재실행 — 기존 증거를 덮지 않고 접미사로 비켜 간다(증거는 축적)."""
    from hwpxfiller.external.ledger_export import ledger_sidecar_path

    first = ledger_sidecar_path(tmp_path, "2026-07-12T14:05:03")
    first.write_text("{}", encoding="utf-8")
    second = ledger_sidecar_path(tmp_path, "2026-07-12T14:05:03")
    assert second == tmp_path / "fill-ledger-20260712-140503-1.json"
    assert second != first and first.exists()


# ------------------------------------------------- managed 배달 원장
def _doc(ordinal: int, notes=()) -> DeliveredDocument:
    return DeliveredDocument(
        ordinal, f"rec-{ordinal}", f"doc-{ordinal}.hwpx", f"C:/out/doc-{ordinal}.hwpx",
        "WRITE_NEW", "sha256:" + str(ordinal) * 64, tuple(notes),
    )


def _write(tmp_path, result, **kw):
    return write_managed_delivery_ledger(
        tmp_path,
        generated_at="2026-07-12T14:05:03",
        work_authority_id="w-1",
        execution_basis_digest="sha256:" + "b" * 64,
        plan_semantic_digest="sha256:" + "p" * 64,
        result=result,
        **kw,
    )


def test_managed_ledger_records_documents_and_fill_notes(tmp_path):
    note = FillNote("계약명", "inline_stripped", ("markpenBegin",))
    sidecar = _write(tmp_path, DeliveryCompleted(str(tmp_path), (_doc(0, [note]), _doc(1))))
    assert sidecar == tmp_path / "fill-ledger-20260712-140503.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["ledger_kind"] == "managed-delivery/v1"
    assert payload["outcome"] == "DeliveryCompleted"
    assert [doc["relative_path"] for doc in payload["delivered"]] == ["doc-0.hwpx", "doc-1.hwpx"]
    # 완화 노트도 증거다 — 조용한 데이터 손실 금지(#154).
    assert payload["delivered"][0]["execution_notes"] == [
        {"field": "계약명", "kind": "inline_stripped", "detail": ["markpenBegin"]}
    ]
    assert "source" not in payload  # GUI 는 출처 포인터를 싣지 않는다


def test_managed_ledger_keeps_the_abort_and_what_landed(tmp_path):
    aborted = DeliveryAborted(
        code="DELIVERY_WRITE_FAILED", detail="잠김", failed_item_ordinal=1,
        delivered=(_doc(0),),
    )
    payload = json.loads(_write(tmp_path, aborted).read_text(encoding="utf-8"))
    assert payload["outcome"] == "DeliveryAborted"
    assert payload["aborted"] == {
        "code": "DELIVERY_WRITE_FAILED", "detail": "잠김", "failed_item_ordinal": 1,
    }
    assert [doc["item_ordinal"] for doc in payload["delivered"]] == [0]


def test_managed_ledger_source_pointer_is_redacted(tmp_path):
    """CLI 출처 포인터에 키 흔적이 섞여도 사이드카에 남지 않는다(N1 관통)."""
    leaky = "https://apis.example/x?ServiceKey=TOPSECRET&y=1"
    sidecar = _write(tmp_path, DeliveryCompleted(str(tmp_path), ()), source=leaky)
    text = sidecar.read_text(encoding="utf-8")
    assert "TOPSECRET" not in text and "[REDACTED]" in text
