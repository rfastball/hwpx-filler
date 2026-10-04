"""Project a saved Job Mapping into the current execution Binding contract."""

from __future__ import annotations

from hwpxfiller.application.field_binding_input import (
    FieldBindingInput,
    LegacyFieldBindingEntry,
    MigrationCandidateRule,
    build_field_binding_input,
    prepare_legacy_field_binding_migration,
)
from hwpxfiller.domain.field_binding import (
    FieldBindingRule,
    resolve_document_value_policy,
    txt_document_value_policy,
)
from hwpxfiller.domain.job import Job
from hwpxfiller.domain.mapping import MappingProfile
from hwpxfiller.domain.raw_data_record import RAW_RECORD_CONTRACT_ID


def legacy_entries(mapping: MappingProfile) -> tuple[LegacyFieldBindingEntry, ...]:
    return tuple(
        LegacyFieldBindingEntry(
            item.template_field, item.type, item.source, item.const, item.fmt, item.slice
        )
        for item in mapping.mappings
    )


def source_schema_keys(mapping: MappingProfile) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.source
            for item in mapping.mappings
            if item.type in {"text", "date", "amount"}
        )
    )


def rule_from_candidate(
    candidate: MigrationCandidateRule, *, media: str
) -> FieldBindingRule:
    resolve_policy = (
        txt_document_value_policy if media == "txt" else resolve_document_value_policy
    )
    return FieldBindingRule(
        field_id=candidate.field_id,
        binding_kind=candidate.binding_kind,
        document_content_value_policy=resolve_policy(candidate.proposed_policy_id),
        source_key=candidate.source_key,
        format_code=candidate.format_code,
        canonical_constant_value=candidate.canonical_constant_value,
        format_kind=candidate.format_kind,
        text_slice=candidate.text_slice,
    )


def mapping_rules(job: Job) -> tuple[FieldBindingRule, ...]:
    """Validate every saved rule, including inactive fields; do not test run readiness."""
    draft = prepare_legacy_field_binding_migration(
        work_authority_id=job.authority_id or "draft-work",
        base_template_application_id="draft-application",
        legacy_entries=legacy_entries(job.mapping),
        captured_at="draft",
    )
    if draft.blockers:
        raise ValueError(f"Mapping 규칙을 옮길 수 없습니다: {draft.blockers!r}")
    rules = tuple(rule_from_candidate(item, media=job.media) for item in draft.candidate_rules)
    # The builder checks one rule per field and canonical source keys. The draft
    # identifiers are only structural validation; no Application is read or written.
    build_field_binding_input(
        workspace_instance_id="draft-workspace",
        work_authority_id=job.authority_id or "draft-work",
        base_template_application_id="draft-application",
        binding_rules=rules,
        source_schema_keys=source_schema_keys(job.mapping),
        raw_record_contract_id=RAW_RECORD_CONTRACT_ID,
        captured_at="draft",
    )
    return rules


def job_binding_input(
    job: Job, workspace_id: str, application_id: str, captured_at: str
) -> FieldBindingInput:
    """Make a revision-keyed immutable execution input from the atomic Job JSON."""
    return build_field_binding_input(
        workspace_instance_id=workspace_id,
        work_authority_id=job.authority_id,
        base_template_application_id=application_id,
        binding_rules=mapping_rules(job),
        source_schema_keys=source_schema_keys(job.mapping),
        raw_record_contract_id=RAW_RECORD_CONTRACT_ID,
        captured_at=captured_at,
    )
