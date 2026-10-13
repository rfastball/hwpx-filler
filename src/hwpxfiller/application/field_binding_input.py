"""Current Job Mapping에서 파생한 실행 Binding 입력과 Field 검토."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from hwpxfiller.domain.field_binding import (
    FIELD_BINDING_SEMANTIC_VERSION,
    SOURCE,
    SOURCE_SCHEMA_VERSION,
    FieldBindingInputIntegrityError,
    FieldBindingRule,
    canonicalize_binding_rules,
    digest_binding_rules,
    digest_source_schema,
    require_current_field_binding_contract,
    require_single_rule_per_field,
    require_source_schema_contract,
    validate_source_schema_keys,
)

# review 분류 어휘.
PRESERVED = "PRESERVED"
BROKEN = "BROKEN"
NEW_ACTIVE_FIELD = "NEW_ACTIVE_FIELD"
#: Job Mapping에는 있지만 current Application에서 비활성인 Field.
INACTIVE_ONLY = "INACTIVE_ONLY"

# ─── FieldBindingInput capture DTO ───────────────────────────────────────────────
@dataclass(frozen=True)
class FieldBindingInput:
    """exact capture — 규칙·소스 스키마·digest 를 담고 integrity 를 스스로 검증한다.

    ``field_binding_authority_revision``·``captured_at`` 은 provenance 다(identity 아님):
    같은 effective 의미면 authority revision 자체는 ExecutionBasis semantic identity 에
    참여하지 않아 기존 Plan 재사용을 막지 않는다.
    """

    workspace_instance_id: str
    work_authority_id: str
    base_template_application_id: str
    field_binding_authority_revision: str
    field_binding_semantic_contract_id: str
    source_schema_contract_id: str
    raw_record_contract_id: str
    binding_rules: tuple[FieldBindingRule, ...]
    source_schema_keys: tuple[str, ...]
    canonical_binding_digest: str
    canonical_source_schema_digest: str
    captured_at: str

    def __post_init__(self) -> None:
        for name in (
            "workspace_instance_id",
            "work_authority_id",
            "base_template_application_id",
            "field_binding_authority_revision",
            "raw_record_contract_id",
            "captured_at",
        ):
            _require_nonempty(getattr(self, name), name)
        # 실행 입력은 현재 판만 허용한다.
        require_current_field_binding_contract(self.field_binding_semantic_contract_id)
        require_source_schema_contract(self.source_schema_contract_id)
        rules = require_single_rule_per_field(self.binding_rules)
        keys = validate_source_schema_keys(self.source_schema_keys)
        if canonicalize_binding_rules(rules) != canonicalize_binding_rules(
            self.binding_rules
        ):  # pragma: no cover - require_single_rule_per_field 이 순서를 보존
            raise FieldBindingInputIntegrityError("규칙 정규화 불일치")
        if digest_binding_rules(rules) != self.canonical_binding_digest:
            raise FieldBindingInputIntegrityError(
                "canonical_binding_digest 가 규칙과 불일치(payload/digest mismatch)"
            )
        if digest_source_schema(keys) != self.canonical_source_schema_digest:
            raise FieldBindingInputIntegrityError(
                "canonical_source_schema_digest 가 소스 스키마와 불일치"
            )
        expected_revision = field_binding_authority_revision_identity(
            work_authority_id=self.work_authority_id,
            base_template_application_id=self.base_template_application_id,
            field_binding_semantic_contract_id=self.field_binding_semantic_contract_id,
            source_schema_contract_id=self.source_schema_contract_id,
            raw_record_contract_id=self.raw_record_contract_id,
            canonical_binding_digest=self.canonical_binding_digest,
            canonical_source_schema_digest=self.canonical_source_schema_digest,
        )
        if self.field_binding_authority_revision != expected_revision:
            raise FieldBindingInputIntegrityError(
                "field_binding_authority_revision 이 내용 content-address 와 불일치"
            )


def _require_nonempty(value: object, what: str) -> None:
    if not isinstance(value, str) or value == "":
        raise FieldBindingInputIntegrityError(f"{what} 는 비어 있지 않은 문자열이어야 한다")


def build_field_binding_input(
    *,
    workspace_instance_id: str,
    work_authority_id: str,
    base_template_application_id: str,
    binding_rules: Iterable[FieldBindingRule],
    source_schema_keys: Iterable[str],
    raw_record_contract_id: str,
    captured_at: str,
) -> FieldBindingInput:
    """규칙·스키마에서 digest·authority revision identity 를 유도해 integrity-valid 입력을 만든다."""
    rules = require_single_rule_per_field(binding_rules)
    keys = validate_source_schema_keys(source_schema_keys)
    binding_digest = digest_binding_rules(rules)
    schema_digest = digest_source_schema(keys)
    revision_id = field_binding_authority_revision_identity(
        work_authority_id=work_authority_id,
        base_template_application_id=base_template_application_id,
        field_binding_semantic_contract_id=FIELD_BINDING_SEMANTIC_VERSION,
        source_schema_contract_id=SOURCE_SCHEMA_VERSION,
        raw_record_contract_id=raw_record_contract_id,
        canonical_binding_digest=binding_digest,
        canonical_source_schema_digest=schema_digest,
    )
    return FieldBindingInput(
        workspace_instance_id=workspace_instance_id,
        work_authority_id=work_authority_id,
        base_template_application_id=base_template_application_id,
        field_binding_authority_revision=revision_id,
        field_binding_semantic_contract_id=FIELD_BINDING_SEMANTIC_VERSION,
        source_schema_contract_id=SOURCE_SCHEMA_VERSION,
        raw_record_contract_id=raw_record_contract_id,
        binding_rules=rules,
        source_schema_keys=keys,
        canonical_binding_digest=binding_digest,
        canonical_source_schema_digest=schema_digest,
        captured_at=captured_at,
    )


def field_binding_authority_revision_identity(
    *,
    work_authority_id: str,
    base_template_application_id: str,
    field_binding_semantic_contract_id: str,
    source_schema_contract_id: str,
    raw_record_contract_id: str,
    canonical_binding_digest: str,
    canonical_source_schema_digest: str,
) -> str:
    """revision 단일 identity — content-address 라 같은 내용은 같은 id(create-once).

    ``captured_at`` 은 identity 에 넣지 않는다(provenance). 두 번째 identity 를 만들지 않는다.
    """
    parts = (
        work_authority_id,
        base_template_application_id,
        field_binding_semantic_contract_id,
        source_schema_contract_id,
        raw_record_contract_id,
        canonical_binding_digest,
        canonical_source_schema_digest,
    )
    hasher = hashlib.sha256()
    for part in parts:
        raw = part.encode("utf-8")
        hasher.update(len(raw).to_bytes(4, "big"))
        hasher.update(raw)
    return "fbrev:sha256:" + hasher.hexdigest()


# ─── current Application review ──────────────────────────────────────────────────
@dataclass(frozen=True)
class CurrentApplicationFieldStructure:
    """current Template Application 의 Field 구조(소비 값 — projection 은 S5-05/구조층 소유)."""

    application_id: str
    active_field_ids: tuple[str, ...]
    inactive_field_ids: tuple[str, ...]
    source_schema_keys: tuple[str, ...]


@dataclass(frozen=True)
class FieldReviewClassification:
    field_id: str
    category: str


@dataclass(frozen=True)
class FieldBindingApplicationReview:
    """Job Mapping 규칙과 current Application 구조의 대조 결과."""

    classifications: tuple[FieldReviewClassification, ...]

    def broken_field_ids(self) -> tuple[str, ...]:
        return tuple(
            c.field_id for c in self.classifications if c.category == BROKEN
        )

    def inactive_only_field_ids(self) -> tuple[str, ...]:
        """Job Mapping이 보존한 비활성 Field."""
        return tuple(
            c.field_id for c in self.classifications if c.category == INACTIVE_ONLY
        )


def review_field_binding_for_current_application(
    binding: FieldBindingInput,
    structure: CurrentApplicationFieldStructure,
) -> FieldBindingApplicationReview:
    """Current Mapping 규칙을 활성·비활성·끊김·신규 Field로 분류한다."""
    active = set(structure.active_field_ids)
    inactive = set(structure.inactive_field_ids)
    schema = set(structure.source_schema_keys)
    classifications: list[FieldReviewClassification] = []
    old_fields: set[str] = set()
    for rule in binding.binding_rules:
        old_fields.add(rule.field_id)
        if rule.field_id in active:
            broken = rule.binding_kind == SOURCE and rule.source_key not in schema
            category = BROKEN if broken else PRESERVED
        elif rule.field_id in inactive:
            category = INACTIVE_ONLY
        else:
            category = BROKEN  # 삭제됨
        classifications.append(FieldReviewClassification(rule.field_id, category))
    for field_id in structure.active_field_ids:
        if field_id not in old_fields:
            classifications.append(
                FieldReviewClassification(field_id, NEW_ACTIVE_FIELD)
            )
    return FieldBindingApplicationReview(tuple(classifications))
