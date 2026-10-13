"""Current Binding input integrity and Job Mapping review."""

from __future__ import annotations

from dataclasses import replace

import pytest

from hwpxfiller.application.field_binding_input import (
    BROKEN,
    INACTIVE_ONLY,
    NEW_ACTIVE_FIELD,
    PRESERVED,
    CurrentApplicationFieldStructure,
    build_field_binding_input,
    review_field_binding_for_current_application,
)
from hwpxfiller.domain.field_binding import (
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    SOURCE,
    FieldBindingInputIntegrityError,
    FieldBindingRule,
    UnsupportedFieldBindingContractError,
)


def _rule(field_id: str, key: str = "name") -> FieldBindingRule:
    return FieldBindingRule(field_id, SOURCE, DOCUMENT_CONTENT_VALUE_POLICY_V1, source_key=key)


def _input(*, rules=None, keys=("name", "amount"), base="A17"):
    return build_field_binding_input(
        workspace_instance_id="ws-1",
        work_authority_id="work-1",
        base_template_application_id=base,
        binding_rules=rules if rules is not None else [_rule("계약명")],
        source_schema_keys=keys,
        raw_record_contract_id="raw-record/v1",
        captured_at="2026-01-01T00:00:00+09:00",
    )


def test_input_identity_is_deterministic_and_checks_digest() -> None:
    binding = _input()
    assert replace(binding, captured_at="later").field_binding_authority_revision == (
        binding.field_binding_authority_revision
    )
    assert _input(base="A18").field_binding_authority_revision != (
        binding.field_binding_authority_revision
    )
    with pytest.raises(FieldBindingInputIntegrityError):
        replace(binding, field_binding_authority_revision="fbrev:sha256:deadbeef")
    with pytest.raises(FieldBindingInputIntegrityError):
        replace(binding, canonical_binding_digest="sha256:nope")
    with pytest.raises(FieldBindingInputIntegrityError):
        replace(binding, canonical_source_schema_digest="sha256:nope")
    with pytest.raises(UnsupportedFieldBindingContractError):
        replace(binding, field_binding_semantic_contract_id="field-binding/v1")
    with pytest.raises(FieldBindingInputIntegrityError):
        replace(binding, base_template_application_id="")


def test_current_review_classifies_mapping_and_template_fields() -> None:
    binding = _input(rules=[
        _rule("preserved"), _rule("removed"), _rule("moved_inactive"),
        _rule("source_gone", "vanished_key"),
    ], keys=("name", "vanished_key"))
    structure = CurrentApplicationFieldStructure(
        "A18", ("preserved", "source_gone", "brand_new"),
        ("moved_inactive",), ("name",),
    )
    review = review_field_binding_for_current_application(binding, structure)
    assert {item.field_id: item.category for item in review.classifications} == {
        "preserved": PRESERVED,
        "removed": BROKEN,
        "moved_inactive": INACTIVE_ONLY,
        "source_gone": BROKEN,
        "brand_new": NEW_ACTIVE_FIELD,
    }
    assert set(review.broken_field_ids()) == {"removed", "source_gone"}
    assert review.inactive_only_field_ids() == ("moved_inactive",)
