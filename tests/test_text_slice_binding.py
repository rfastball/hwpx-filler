"""가공이 연결 판본(field-binding/v4)을 지나는 길 — 규칙·저장 codec·migration·지문 (가산 계약).

가공은 **있을 때만** 새 키·새 바이트를 만든다: 가공 없는 Mapping·규칙·계획의 지문은 v4 이전과
같아야 한다(진행 중인 migration draft·검토 기준선·봉인된 계획이 판 올림만으로 stale 이 되지 않게).
"""
from __future__ import annotations

import pytest

from hwpxfiller.application.field_binding_input import (
    LegacyFieldBindingEntry,
    legacy_field_binding_basis_fingerprint,
    prepare_legacy_field_binding_migration,
)
from hwpxfiller.application.stored_field_binding import (
    StoredFieldBindingError,
    _decode_rule,
    _encode_rule,
)
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP,
    FIELD_BINDING_SEMANTIC_VERSION_V2,
    FIELD_BINDING_SEMANTIC_VERSION_V3,
    SOURCE,
    ExactText,
    FieldBindingInputIntegrityError,
    FieldBindingRule,
    UnsupportedTextSliceError,
    digest_binding_rules,
    render_source_value,
    require_text_slice,
)
from hwpxfiller.domain.job import Job, rules_fingerprints, rules_values
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.domain.text_slice import TextSlice

POLICY = DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP
SPLIT = TextSlice("split", delimiter="-", index=1)


def _rule(**kw) -> FieldBindingRule:
    return FieldBindingRule("공고번호", SOURCE, POLICY, source_key="입찰공고번호", **kw)


# ─── 규칙 모델 ───────────────────────────────────────────────────────────────────
def test_slice_stands_only_on_source_rules() -> None:
    with pytest.raises(FieldBindingInputIntegrityError, match="SOURCE"):
        FieldBindingRule(
            "f", CONSTANT, POLICY, canonical_constant_value=ExactText("x"), text_slice=SPLIT
        )
    with pytest.raises(FieldBindingInputIntegrityError, match="TextSlice"):
        _rule(text_slice={"mode": "split", "delimiter": "-", "index": 1})  # type: ignore[arg-type]


@pytest.mark.parametrize("contract", [FIELD_BINDING_SEMANTIC_VERSION_V2, FIELD_BINDING_SEMANTIC_VERSION_V3])
def test_outdated_framings_refuse_a_slice(contract) -> None:
    """v2·v3 framing 은 동결이다 — 가공을 실은 규칙을 이전 판으로 봉인하지 않는다(조용한 손실 금지)."""
    with pytest.raises(FieldBindingInputIntegrityError, match="가공"):
        digest_binding_rules([_rule(text_slice=SPLIT)], contract_id=contract)


def test_render_source_value_is_slice_then_format() -> None:
    assert render_source_value("amount", "", {"mode": "split", "delimiter": "원", "index": 1},
                               "170,309,180원 (VAT 포함)") == "170,309,180원"
    assert render_source_value(None, None, None, " 그대로 ") == " 그대로 "
    with pytest.raises(UnsupportedTextSliceError):
        render_source_value(None, None, {"mode": "chars", "start": 0}, "x")
    with pytest.raises(UnsupportedTextSliceError):
        require_text_slice({"mode": "regex"})


# ─── 저장 codec ───────────────────────────────────────────────────────────────────
def test_codec_round_trips_the_slice_and_omits_it_when_absent() -> None:
    plain = _rule()
    assert "text_slice" not in _encode_rule(plain)  # v2·v3 판본의 저장 표현은 byte 그대로
    assert _decode_rule(_encode_rule(plain)) == plain
    sliced = _rule(text_slice=TextSlice("chars", start=1, length=3))
    encoded = _encode_rule(sliced)
    assert encoded["text_slice"] == {"mode": "chars", "start": 1, "length": 3}
    assert _decode_rule(encoded) == sliced


def test_codec_rejects_a_malformed_stored_slice() -> None:
    encoded = {**_encode_rule(_rule()), "text_slice": {"mode": "split", "delimiter": "", "index": 1}}
    with pytest.raises(StoredFieldBindingError, match="text_slice"):
        _decode_rule(encoded)


# ─── legacy Mapping → 판본 migration ─────────────────────────────────────────────
def _entry(slice_=None) -> LegacyFieldBindingEntry:
    return LegacyFieldBindingEntry("공고번호", "text", "입찰공고번호", "", "", slice_)


def test_migration_carries_the_slice_into_the_candidate() -> None:
    draft = prepare_legacy_field_binding_migration(
        work_authority_id="w", base_template_application_id="a",
        legacy_entries=[_entry(SPLIT)], captured_at="2026-09-30T00:00:00",
    )
    (candidate,) = draft.candidate_rules
    assert candidate.text_slice == SPLIT
    assert (candidate.format_kind, candidate.format_code) == (None, None)


def test_legacy_fingerprint_is_unchanged_without_a_slice_and_moves_with_one() -> None:
    import hashlib

    # v4 이전 산식(가공 칸 없음)을 그대로 다시 계산해 대조한다 — 지문이 판 올림으로 움직이면
    # 진행 중인 migration draft 가 전부 stale 로 읽힌다.
    hasher = hashlib.sha256()
    hasher.update(b"legacy-field-binding/v0\0")
    for part in ("공고번호", "text", "입찰공고번호", "", ""):
        raw = part.encode("utf-8")
        hasher.update(len(raw).to_bytes(4, "big"))
        hasher.update(raw)
    assert legacy_field_binding_basis_fingerprint([_entry()]) == "sha256:" + hasher.hexdigest()
    with_slice = legacy_field_binding_basis_fingerprint([_entry(SPLIT)])
    assert with_slice != legacy_field_binding_basis_fingerprint([_entry()])
    assert with_slice != legacy_field_binding_basis_fingerprint(
        [_entry(TextSlice("split", delimiter="-", index=2))]
    )


# ─── 작업 규칙 축(검토·판본) ─────────────────────────────────────────────────────────
def _job(slice_=None) -> Job:
    return Job(
        name="계약",
        template_path="t.hwpx",
        mapping=MappingProfile(mappings=[FieldMapping("공고번호", "입찰공고번호", slice=slice_)]),
    )


def test_rules_fingerprint_without_slice_is_the_pre_v4_string() -> None:
    """가공 없는 필드의 source 지문은 옛 4 축 결합 그대로 — 저장된 검토 기준선이 헛 검토를 부르지 않는다."""
    assert rules_fingerprints(_job())["field:공고번호:source"] == "\x1f".join(
        ("입찰공고번호", "text", "", "")
    )
    assert rules_values(_job())["fields"]["공고번호"]["slice"] == ""


def test_slice_change_is_a_semantic_binding_change() -> None:
    plain, sliced = rules_fingerprints(_job()), rules_fingerprints(_job(SPLIT))
    assert plain["field:공고번호:source"] != sliced["field:공고번호:source"]
    assert plain["field:공고번호:format"] == sliced["field:공고번호:format"]
    assert rules_values(_job(SPLIT))["fields"]["공고번호"]["slice"] == (
        '{"delimiter": "-", "index": 1, "mode": "split"}'
    )


def test_saving_a_slice_advances_the_binding_revision() -> None:
    from hwpxfiller.domain.job import advance_revisions

    previous, current = _job(), _job(SPLIT)
    advance_revisions(current, previous)
    assert current.binding_revision == previous.binding_revision + 1
    assert current.previous_rules["fields"]["공고번호"]["slice"] == ""


# ─── outdated 판 무손실 승격 판정 — 사영에 가공이 남는다 ───────────────────────────────
def test_outdated_projections_split_on_a_slice() -> None:
    """v2·v3 판본의 규칙은 가공이 언제나 없다 — 현재 Mapping 에 가공이 있으면 승격하지 않는다."""
    from hwpxfiller.external.seal_execution_plan_service import (
        _OUTDATED_PROJECTIONS,
        _v2_projection,
        _v3_projection,
    )

    assert set(_OUTDATED_PROJECTIONS) == {
        FIELD_BINDING_SEMANTIC_VERSION_V2,
        FIELD_BINDING_SEMANTIC_VERSION_V3,
    }
    plain, sliced = _rule(), _rule(text_slice=SPLIT)
    for projection in (_v2_projection, _v3_projection):
        assert projection(plain) == projection(_rule())
        assert projection(plain) != projection(sliced)
    # v3 사영은 표시형 kind 를 담고(v3 판본은 kind 를 알았다), v2 사영은 버린다.
    amount = _rule(format_kind="amount", format_code="")
    assert _v3_projection(amount) != _v3_projection(plain)
    assert _v2_projection(amount) == _v2_projection(plain)
