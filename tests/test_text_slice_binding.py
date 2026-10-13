"""가공이 현재 Job Mapping, 규칙, 실행 지문을 지나는 길."""
from __future__ import annotations

import pytest

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
from hwpxfiller.external.job_binding_projection import mapping_rules

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


def test_current_contract_registry_accepts_all_readable_versions() -> None:
    """v5 는 유일한 실행 입력 판이고, v2·v3·v4 는 읽되 실행 입력이 되지 못한다."""
    from hwpxfiller.domain.field_binding import (
        FIELD_BINDING_SEMANTIC_VERSION,
        FIELD_BINDING_SEMANTIC_VERSION_V4,
        is_current_field_binding_contract,
        require_field_binding_contract,
    )

    for contract in (
        FIELD_BINDING_SEMANTIC_VERSION_V2,
        FIELD_BINDING_SEMANTIC_VERSION_V3,
        FIELD_BINDING_SEMANTIC_VERSION_V4,
        FIELD_BINDING_SEMANTIC_VERSION,
    ):
        assert require_field_binding_contract(contract) == contract
    assert is_current_field_binding_contract(FIELD_BINDING_SEMANTIC_VERSION) is True
    for outdated in (
        FIELD_BINDING_SEMANTIC_VERSION_V2,
        FIELD_BINDING_SEMANTIC_VERSION_V3,
        FIELD_BINDING_SEMANTIC_VERSION_V4,
    ):
        assert is_current_field_binding_contract(outdated) is False


def test_render_source_value_is_slice_then_format() -> None:
    assert render_source_value("amount", "", {"mode": "split", "delimiter": "원", "index": 1},
                               "170,309,180원 (VAT 포함)") == "170,309,180원"
    assert render_source_value(None, None, None, " 그대로 ") == " 그대로 "
    with pytest.raises(UnsupportedTextSliceError):
        render_source_value(None, None, {"mode": "chars", "start": 0}, "x")
    with pytest.raises(UnsupportedTextSliceError):
        require_text_slice({"mode": "regex"})


# ─── current Job Mapping projection ─────────────────────────────────────────
def test_mapping_projects_the_slice() -> None:
    (rule,) = mapping_rules(_job(SPLIT))
    assert rule.text_slice == SPLIT
    assert (rule.format_kind, rule.format_code) == (None, None)


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
