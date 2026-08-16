"""S5-12(#708) RawDataRecordSnapshot·CanonicalSourceValue·RecordReviewEvidence 도메인 검증.

순수 층: exact tagged scalar 보존·MISSING/NULL/empty/space 구분·duplicate-key 경계·삽입순서
무관 digest·UTF-8 key 정렬·review basis 결속. 값·codec·digest 만 본다(Plan validation 은 형제 파일).
"""

from __future__ import annotations

import pytest

from hwpxfiller.domain.field_binding import (
    FieldBindingInputIntegrityError,
    SourceSchemaDuplicateKeyError,
)
from hwpxfiller.domain.raw_data_record import (
    RECORD_REVIEW_EXAMINED,
    RawRecordCaptureProvenance,
    RawRecordDuplicateKeyError,
    RawRecordIntegrityError,
    RecordReviewEvidenceIntegrityError,
    SourceBoolean,
    SourceDate,
    SourceDateTime,
    SourceDecimal,
    SourceNull,
    SourceText,
    build_raw_record_snapshot,
    build_record_review_evidence,
    compute_review_basis_digest,
    decode_source_value,
    encode_source_value,
    source_value_type_of,
    verify_raw_record_snapshot,
    verify_record_review_evidence_integrity,
)

_PROV = RawRecordCaptureProvenance(
    source_adapter_contract_id="excel-adapter/v1",
    captured_at="2026-01-01T00:00:00+09:00",
)


def _snap(pairs, *, keys=None, identity="rec-1"):
    return build_raw_record_snapshot(
        source_schema_keys=keys if keys is not None else [k for k, _ in pairs],
        source_values=pairs,
        record_identity=identity,
        capture_provenance=_PROV,
    )


# ─── exact tagged scalar 보존 ────────────────────────────────────────────────────────────
def test_source_text_preserves_whitespace_and_nfc_nfd() -> None:
    nfc = "é"  # é 합성
    nfd = "é"  # é 분해 — NFC 와 다른 scalar sequence
    snap = _snap(
        [("a", SourceText("  spaced \t ")), ("b", SourceText(nfc)), ("c", SourceText(nfd))]
    )
    assert snap.value_for("a").text == "  spaced \t "
    assert snap.value_for("b").text == nfc
    assert snap.value_for("c").text == nfd
    # NFC ≠ NFD 는 서로 다른 값 → 다른 digest 기여.
    assert encode_source_value(snap.value_for("b")) != encode_source_value(snap.value_for("c"))


def test_scalar_types_positive() -> None:
    snap = _snap(
        [
            ("t", SourceText("x")),
            ("d", SourceDecimal("1.50")),
            ("day", SourceDate("2026-01-02")),
            ("dt", SourceDateTime("2026-01-02T03:04:05+09:00")),
            ("b", SourceBoolean(True)),
            ("n", SourceNull()),
        ]
    )
    assert source_value_type_of(snap.value_for("d")) == "DECIMAL"
    assert source_value_type_of(snap.value_for("n")) == "NULL"
    assert encode_source_value(SourceDecimal("1.50")) == {"value_type": "DECIMAL", "literal": "1.50"}
    assert encode_source_value(SourceNull()) == {"value_type": "NULL"}
    assert encode_source_value(SourceBoolean(False)) == {"value_type": "BOOLEAN", "literal": False}


def test_missing_null_empty_space_are_four_distinct_states() -> None:
    snap = _snap([("null", SourceNull()), ("empty", SourceText("")), ("space", SourceText(" "))])
    # MISSING: key 부재.
    assert snap.value_for("absent") is None
    assert snap.has_key("absent") is False
    # NULL ≠ empty ≠ space, 그리고 셋 다 MISSING 과 다르다.
    assert isinstance(snap.value_for("null"), SourceNull)
    assert snap.value_for("empty").text == ""
    assert snap.value_for("space").text == " "
    enc = snap.semantic_payload_encoded["source_values"]
    tagged = {e["source_key"]: e["tagged_value"] for e in enc}
    assert tagged["null"] == {"value_type": "NULL"}
    assert tagged["empty"] == {"value_type": "EXACT_TEXT", "literal": ""}
    assert tagged["space"] == {"value_type": "EXACT_TEXT", "literal": " "}


def test_nan_infinity_implicit_timezone_rejected() -> None:
    with pytest.raises(FieldBindingInputIntegrityError):
        SourceDecimal("NaN")
    with pytest.raises(FieldBindingInputIntegrityError):
        SourceDecimal("Infinity")
    with pytest.raises(FieldBindingInputIntegrityError):
        SourceDateTime("2026-01-02T03:04:05")  # timezone offset 없음


def test_non_canonical_source_value_rejected() -> None:
    with pytest.raises(RawRecordIntegrityError):
        _snap([("a", "raw string not a source value")])  # type: ignore[list-item]


# ─── duplicate key 경계(map 축약 전) ─────────────────────────────────────────────────────
def test_duplicate_exact_key_rejected_before_map() -> None:
    with pytest.raises(RawRecordDuplicateKeyError):
        _snap([("name", SourceText("A")), ("name", SourceText("B"))])


def test_case_and_whitespace_distinct_keys_not_duplicate() -> None:
    # "name" ≠ "Name" ≠ "name " — snapshot 생성 성공(중복 아님).
    snap = _snap([("name", SourceText("a")), ("Name", SourceText("b")), ("name ", SourceText("c"))])
    assert snap.has_key("name") and snap.has_key("Name") and snap.has_key("name ")


def test_schema_duplicate_key_rejected() -> None:
    with pytest.raises(SourceSchemaDuplicateKeyError):
        _snap([("a", SourceText("x"))], keys=["a", "a"])


# ─── digest: 삽입순서 무관·UTF-8 key 정렬 ────────────────────────────────────────────────
def test_insertion_order_independent_digest() -> None:
    a = _snap([("b", SourceText("2")), ("a", SourceText("1"))])
    b = _snap([("a", SourceText("1")), ("b", SourceText("2"))])
    assert a.raw_record_digest == b.raw_record_digest
    assert a.canonical_payload_bytes == b.canonical_payload_bytes


def test_source_values_sorted_by_utf8_byte_order() -> None:
    snap = _snap([("z", SourceText("1")), ("Z", SourceText("2")), ("a", SourceText("3"))])
    keys = [e["source_key"] for e in snap.semantic_payload_encoded["source_values"]]
    # 대문자(0x5A)가 소문자(0x61, 0x7A)보다 앞: 'Z' < 'a' < 'z'.
    assert keys == ["Z", "a", "z"]


def test_record_identity_distinct_from_digest_and_verify() -> None:
    snap = _snap([("a", SourceText("x"))], identity="rec-42")
    assert snap.record_identity == "rec-42"
    assert snap.record_identity != snap.raw_record_digest
    verify_raw_record_snapshot(snap)  # 자기정합


def test_same_values_distinct_identity_allowed() -> None:
    a = _snap([("a", SourceText("x"))], identity="rec-1")
    b = _snap([("a", SourceText("x"))], identity="rec-2")
    # 같은 값·다른 identity → 다른 raw digest(identity 가 payload 에 참여).
    assert a.raw_record_digest != b.raw_record_digest


def test_capture_provenance_excluded_from_digest() -> None:
    other = RawRecordCaptureProvenance(
        source_adapter_contract_id="csv-adapter/v1",
        captured_at="2027-12-31T23:59:59+09:00",
        source_observation_ref="obs://x",
    )
    a = _snap([("a", SourceText("x"))])
    b = build_raw_record_snapshot(
        source_schema_keys=["a"],
        source_values=[("a", SourceText("x"))],
        record_identity="rec-1",
        capture_provenance=other,
    )
    assert a.raw_record_digest == b.raw_record_digest


def test_empty_record_identity_rejected() -> None:
    with pytest.raises(RawRecordIntegrityError):
        _snap([("a", SourceText("x"))], identity="")


def test_non_string_and_surrogate_identity_rejected() -> None:
    with pytest.raises(RawRecordIntegrityError):
        _snap([("a", SourceText("x"))], identity=123)  # type: ignore[arg-type]
    with pytest.raises(RawRecordIntegrityError):
        _snap([("a", SourceText("x"))], identity="\ud800")  # lone surrogate


def test_verify_detects_tampered_snapshot() -> None:
    import dataclasses

    snap = _snap([("a", SourceText("x"))])
    tampered = dataclasses.replace(snap, raw_record_digest="sha256:wrong")
    with pytest.raises(RawRecordIntegrityError):
        verify_raw_record_snapshot(tampered)


def test_source_value_encode_decode_round_trip() -> None:
    for v in (
        SourceText("  x\n"),
        SourceText(""),
        SourceDecimal("1.50"),
        SourceDate("2026-01-02"),
        SourceDateTime("2026-01-02T03:04:05+09:00"),
        SourceBoolean(True),
        SourceBoolean(False),
        SourceNull(),
    ):
        assert decode_source_value(encode_source_value(v)) == v


def test_decode_rejects_unknown_type_and_tampered_literal() -> None:
    with pytest.raises(RawRecordIntegrityError):
        decode_source_value({"value_type": "MONEY", "literal": "1"})
    with pytest.raises(RawRecordIntegrityError):
        decode_source_value({"value_type": "DECIMAL", "literal": "NaN"})  # 생성자 검증 실패
    with pytest.raises(RawRecordIntegrityError):
        decode_source_value({"value_type": "BOOLEAN", "literal": "true"})  # bool 아님


def test_verify_detects_divergent_values_keeping_digest() -> None:
    import dataclasses

    snap = _snap([("a", SourceText("x"))])
    # digest 는 그대로인데 _values 만 sealed payload 와 갈라 놓는다.
    diverged = dataclasses.replace(snap, _values={"a": SourceText("TAMPERED")})
    with pytest.raises(RawRecordIntegrityError):
        verify_raw_record_snapshot(diverged)


# ─── RecordReviewEvidence ────────────────────────────────────────────────────────────────
def _evidence(**over):
    kw = dict(
        workspace_instance_id="ws-1",
        work_authority_id="work-1",
        plan_semantic_digest="sha256:plan",
        raw_record_digest="sha256:raw",
        record_identity="rec-1",
        actor_binding="user:alice",
        reviewed_at="2026-01-01T00:00:00+09:00",
    )
    kw.update(over)
    return build_record_review_evidence(**kw)


def test_review_basis_binds_plan_raw_identity_policy() -> None:
    ev = _evidence()
    assert ev.review_policy_basis == RECORD_REVIEW_EXAMINED
    assert ev.review_basis_digest == compute_review_basis_digest(
        plan_semantic_digest="sha256:plan",
        raw_record_digest="sha256:raw",
        record_identity="rec-1",
        record_review_contract_id="record-review/v1",
        review_policy_basis=RECORD_REVIEW_EXAMINED,
    )
    verify_record_review_evidence_integrity(ev)


def test_review_basis_excludes_actor_and_time() -> None:
    a = _evidence(actor_binding="user:alice", reviewed_at="2026-01-01T00:00:00+09:00")
    b = _evidence(actor_binding="user:bob", reviewed_at="2027-07-07T07:07:07+09:00")
    # actor·time 은 basis 제외 → 같은 basis digest.
    assert a.review_basis_digest == b.review_basis_digest


def test_review_basis_differs_across_plan_raw_identity_policy() -> None:
    base = _evidence().review_basis_digest
    assert _evidence(plan_semantic_digest="sha256:other").review_basis_digest != base
    assert _evidence(raw_record_digest="sha256:other").review_basis_digest != base
    assert _evidence(record_identity="rec-9").review_basis_digest != base
    assert _evidence(review_policy_basis="OTHER").review_basis_digest != base


def test_tampered_review_evidence_rejected() -> None:
    import dataclasses

    ev = _evidence()
    tampered = dataclasses.replace(ev, plan_semantic_digest="sha256:swapped")
    # basis digest 는 그대로인데 plan digest 만 바꿈 → 재계산 불일치.
    with pytest.raises(RecordReviewEvidenceIntegrityError):
        verify_record_review_evidence_integrity(tampered)
