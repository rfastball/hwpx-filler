"""Project the saved Job mapping into the execution Binding contract."""

from __future__ import annotations

from hwpxfiller.application.field_binding_input import FieldBindingInput, build_field_binding_input
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    RUNTIME_DATE,
    SOURCE,
    ExactText,
    FieldBindingRule,
    resolve_document_value_policy,
    txt_document_value_policy,
)
from hwpxfiller.domain.job import Job
from hwpxfiller.domain.mapping import TYPES, MappingProfile
from hwpxfiller.domain.raw_data_record import RAW_RECORD_CONTRACT_ID


def source_schema_keys(mapping: MappingProfile) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.source
            for item in mapping.mappings
            if item.type in {"text", "date", "amount"}
        )
    )


def mapping_rules(job: Job) -> tuple[FieldBindingRule, ...]:
    """Translate every saved Mapping rule, including inactive template fields."""
    policy = txt_document_value_policy if job.media == "txt" else resolve_document_value_policy
    rules: list[FieldBindingRule] = []
    for item in job.mapping.mappings:
        if item.type == "const":
            rules.append(FieldBindingRule(
                item.template_field, CONSTANT,
                policy(DOCUMENT_CONTENT_VALUE_POLICY_V1.policy_id),
                canonical_constant_value=ExactText(item.const),
            ))
        elif item.type == "today":
            rules.append(FieldBindingRule(
                item.template_field, RUNTIME_DATE,
                policy(DOCUMENT_CONTENT_VALUE_POLICY_V1.policy_id),
                format_kind="date", format_code=item.fmt,
            ))
        elif item.type in {"text", "date", "amount"}:
            format_kind = None if item.type == "text" and not item.fmt else item.type
            rules.append(FieldBindingRule(
                item.template_field, SOURCE,
                policy(DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP.policy_id),
                source_key=item.source,
                format_kind=format_kind,
                format_code=None if format_kind is None else item.fmt,
                text_slice=item.slice,
            ))
        else:
            raise ValueError(f"지원하지 않는 유형: {item.type!r} (지원: {TYPES})")
    return tuple(rules)


def job_binding_input(
    job: Job, workspace_id: str, application_id: str, captured_at: str
) -> FieldBindingInput:
    """Build the exact execution input from the atomic Job JSON."""
    return build_field_binding_input(
        workspace_instance_id=workspace_id,
        work_authority_id=job.authority_id,
        base_template_application_id=application_id,
        binding_rules=mapping_rules(job),
        source_schema_keys=source_schema_keys(job.mapping),
        raw_record_contract_id=RAW_RECORD_CONTRACT_ID,
        captured_at=captured_at,
    )
