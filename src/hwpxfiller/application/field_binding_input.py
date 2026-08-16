"""S5 Field Binding capture 경계 — exact 입력 DTO·immutable revision·legacy migration·review.

이 모듈이 소유하는 순수 판정: :class:`FieldBindingInput` capture DTO 의 integrity 검증,
create-once :class:`FieldBindingRevision` 과 그 단일 identity(``field_binding_authority_revision``),
legacy ``legacy-field-binding/v0`` capture + migration draft 계산, current Application review 분류,
그리고 두 commit 의 순수 결정(fence·store 없음).

store·fence·wall-clock·native 는 모른다 — 시간은 caller 가 넘긴 ``captured_at``/``now`` 다.
migration draft 는 legacy authority 를 수정하지 않는다. review 는 Field 구조·규칙 적용가능성만
분류하고 Active/inactive 최종 execution projection 은 S5-05 소유다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from hwpxfiller.domain.field_binding import (
    CONSTANT,
    DATE,
    DECIMAL,
    DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    EXACT_TEXT,
    FIELD_BINDING_SEMANTIC_VERSION,
    INTENTIONAL_BLANK,
    SOURCE,
    SOURCE_SCHEMA_VERSION,
    ExactText,
    FieldBindingInputIntegrityError,
    FieldBindingRule,
    canonicalize_binding_rules,
    canonicalize_source_schema,
    digest_binding_rules,
    digest_source_schema,
    require_field_binding_contract,
    require_single_rule_per_field,
    require_source_schema_contract,
    validate_source_schema_keys,
)

# migration 시 legacy value 유형 → v1 value_type 매핑(text/date/amount 만 소스 값을 나른다).
_LEGACY_TYPE_TO_VALUE_TYPE = {"text": EXACT_TEXT, "date": DATE, "amount": DECIMAL}

# review 분류 어휘.
PRESERVED = "PRESERVED"
BROKEN = "BROKEN"
NEW_ACTIVE_FIELD = "NEW_ACTIVE_FIELD"
INACTIVE_ONLY = "INACTIVE_ONLY"

# migration blocker 어휘.
AMBIGUOUS_BLANK_OMISSION = "AMBIGUOUS_BLANK_OMISSION"

# commit terminal outcome 어휘.
FIELD_BINDING_REVISION_COMMITTED = "FIELD_BINDING_REVISION_COMMITTED"

# migration/review 가 요구하는 명시 결정 코드(commit 이 아직 불가함을 시끄럽게 알린다).
NEEDS_BINDING_SEMANTIC_MIGRATION = "NEEDS_BINDING_SEMANTIC_MIGRATION"
NEEDS_FIELD_BINDING_APPLICATION_REVIEW = "NEEDS_FIELD_BINDING_APPLICATION_REVIEW"


class FieldBindingReviewRequired(Exception):
    """commit 이 아직 불가 — 사용자 명시 결정이 남았다(context 도 integrity 도 아니다)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StaleFieldBindingBasis(Exception):
    """capture 시 basis(current Application/legacy)가 commit 시점에 이동 — commit 없이 닫는다."""

    code = "STALE_TEMPLATE_APPLICATION"


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
        require_field_binding_contract(self.field_binding_semantic_contract_id)
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


# ─── immutable FieldBindingRevision ──────────────────────────────────────────────
@dataclass(frozen=True)
class FieldBindingRevision:
    """create-once immutable revision — Work·exact Template Application 에 결속된다.

    identity 는 ``field_binding_authority_revision`` 하나뿐이다(revision_id·snapshot_id·
    epoch 없음). ``work_authority_id`` == Job.authority_id == DocumentWork.work_id.
    """

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
        expected = field_binding_authority_revision_identity(
            work_authority_id=self.work_authority_id,
            base_template_application_id=self.base_template_application_id,
            field_binding_semantic_contract_id=self.field_binding_semantic_contract_id,
            source_schema_contract_id=self.source_schema_contract_id,
            raw_record_contract_id=self.raw_record_contract_id,
            canonical_binding_digest=self.canonical_binding_digest,
            canonical_source_schema_digest=self.canonical_source_schema_digest,
        )
        if self.field_binding_authority_revision != expected:
            raise FieldBindingInputIntegrityError(
                "field_binding_authority_revision 이 내용 content-address 와 불일치"
            )
        if digest_binding_rules(self.binding_rules) != self.canonical_binding_digest:
            raise FieldBindingInputIntegrityError("revision 규칙/digest mismatch")
        if digest_source_schema(self.source_schema_keys) != (
            self.canonical_source_schema_digest
        ):
            raise FieldBindingInputIntegrityError("revision 스키마/digest mismatch")


def revision_from_input(inp: FieldBindingInput) -> FieldBindingRevision:
    """integrity-valid 입력을 immutable revision 으로 봉인한다(base 는 입력의 exact Application)."""
    return FieldBindingRevision(
        work_authority_id=inp.work_authority_id,
        base_template_application_id=inp.base_template_application_id,
        field_binding_authority_revision=inp.field_binding_authority_revision,
        field_binding_semantic_contract_id=inp.field_binding_semantic_contract_id,
        source_schema_contract_id=inp.source_schema_contract_id,
        raw_record_contract_id=inp.raw_record_contract_id,
        binding_rules=inp.binding_rules,
        source_schema_keys=inp.source_schema_keys,
        canonical_binding_digest=inp.canonical_binding_digest,
        canonical_source_schema_digest=inp.canonical_source_schema_digest,
        captured_at=inp.captured_at,
    )


# ─── legacy-field-binding/v0 capture + migration draft ───────────────────────────
@dataclass(frozen=True)
class LegacyFieldBindingEntry:
    """legacy Mapping 한 항목의 exact capture(재해석 없음)."""

    template_field: str
    legacy_type: str  # text·date·amount·const·blank
    source: str
    const: str
    fmt: str


@dataclass(frozen=True)
class MigrationCandidateRule:
    """migration 후보 규칙 — 명시 정책 후보를 붙여 표면화하되 자동 확정하지 않는다."""

    field_id: str
    binding_kind: str
    source_key: str | None
    value_type: str | None
    format_code: str | None
    canonical_constant_value: object | None
    proposed_policy_id: str
    whitespace_decision_required: bool


@dataclass(frozen=True)
class MigrationBlocker:
    field_id: str
    reason: str


@dataclass(frozen=True)
class FieldBindingMigrationDraft:
    """legacy → v1 migration 초안 — legacy authority 를 수정하지 않는다.

    ``blockers`` 가 비어 있지 않으면 commit 은 명시 사용자 결정 없이는 진행하지 않는다.
    ``legacy_basis_fingerprint`` 로 commit 시점 legacy basis 이동을 되짚는다.
    """

    work_authority_id: str
    base_template_application_id: str
    legacy_basis_fingerprint: str
    candidate_rules: tuple[MigrationCandidateRule, ...]
    blockers: tuple[MigrationBlocker, ...]
    captured_at: str


def legacy_field_binding_basis_fingerprint(
    entries: Iterable[LegacyFieldBindingEntry],
) -> str:
    """legacy Mapping 의 exact fingerprint — 저장 순서 무관, 재해석 없이 원본 값만 담는다."""
    hasher = hashlib.sha256()
    hasher.update(b"legacy-field-binding/v0\0")
    for entry in sorted(
        entries, key=lambda e: e.template_field.encode("utf-8")
    ):
        for part in (
            entry.template_field,
            entry.legacy_type,
            entry.source,
            entry.const,
            entry.fmt,
        ):
            raw = part.encode("utf-8")
            hasher.update(len(raw).to_bytes(4, "big"))
            hasher.update(raw)
    return "sha256:" + hasher.hexdigest()


def prepare_legacy_field_binding_migration(
    *,
    work_authority_id: str,
    base_template_application_id: str,
    legacy_entries: Iterable[LegacyFieldBindingEntry],
    captured_at: str,
) -> FieldBindingMigrationDraft:
    """legacy Mapping 을 exact capture 해 후보 규칙·명시 결정·blocker 를 계산한다.

    - text/date/amount 의 암묵 strip 을 **명시 whitespace 정책 후보**(legacy-strip)로 옮긴다.
    - const 는 canonicalization 후보(ExactText)로 옮긴다.
    - blank omission 은 자동으로 Intentional Blank 로 바꾸지 않고 **명시 결정**으로 blocker 로 남긴다.
    """
    entries = tuple(legacy_entries)
    candidates: list[MigrationCandidateRule] = []
    blockers: list[MigrationBlocker] = []
    for entry in entries:
        if entry.legacy_type == "blank":
            # legacy 는 blank 를 "출력 제외(omission)"로 다뤘다 — Intentional Blank 와 다르다.
            blockers.append(
                MigrationBlocker(entry.template_field, AMBIGUOUS_BLANK_OMISSION)
            )
            continue
        if entry.legacy_type == "const":
            candidates.append(
                MigrationCandidateRule(
                    field_id=entry.template_field,
                    binding_kind=CONSTANT,
                    source_key=None,
                    value_type=None,
                    canonical_constant_value=ExactText(entry.const),
                    format_code=None,
                    proposed_policy_id=DOCUMENT_CONTENT_VALUE_POLICY_V1.policy_id,
                    whitespace_decision_required=False,
                )
            )
            continue
        value_type = _LEGACY_TYPE_TO_VALUE_TYPE.get(entry.legacy_type)
        if value_type is None:
            raise FieldBindingInputIntegrityError(
                f"미지원 legacy 유형: {entry.legacy_type!r} ({entry.template_field!r})"
            )
        candidates.append(
            MigrationCandidateRule(
                field_id=entry.template_field,
                binding_kind=SOURCE,
                source_key=entry.source,
                value_type=value_type,
                canonical_constant_value=None,
                format_code=entry.fmt or None,
                # legacy 는 값을 암묵 strip 했다 — 명시 whitespace 결정을 요구한다.
                proposed_policy_id=DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP.policy_id,
                whitespace_decision_required=True,
            )
        )
    return FieldBindingMigrationDraft(
        work_authority_id=work_authority_id,
        base_template_application_id=base_template_application_id,
        legacy_basis_fingerprint=legacy_field_binding_basis_fingerprint(entries),
        candidate_rules=tuple(candidates),
        blockers=tuple(blockers),
        captured_at=captured_at,
    )


def decide_migration_commit(
    draft: FieldBindingMigrationDraft,
    resolved_input: FieldBindingInput,
    current_legacy_basis_fingerprint: str,
) -> FieldBindingRevision:
    """migration commit 순수 결정 — 성공하면 immutable revision, 아니면 typed 오류.

    - basis 이동 → :class:`StaleFieldBindingBasis`(ledger 미기록).
    - blocker field 가 resolved_input 에 명시 규칙으로 없으면 → review required(미기록).
    - 그 외 integrity 위반 → :class:`FieldBindingInputIntegrityError`(미기록).
    """
    if (
        current_legacy_basis_fingerprint != draft.legacy_basis_fingerprint
        or resolved_input.base_template_application_id
        != draft.base_template_application_id
    ):
        raise StaleFieldBindingBasis("legacy migration basis 가 capture 이후 이동했다")
    resolved_fields = {rule.field_id for rule in resolved_input.binding_rules}
    for blocker in draft.blockers:
        if blocker.field_id not in resolved_fields:
            raise FieldBindingReviewRequired(
                "FIELD_BINDING_MIGRATION_REVIEW_REQUIRED",
                f"미해결 blocker: {blocker.field_id!r} ({blocker.reason})",
            )
    if resolved_input.work_authority_id != draft.work_authority_id:
        raise FieldBindingInputIntegrityError(
            "resolved_input 의 work_authority_id 가 draft 와 다르다"
        )
    return revision_from_input(resolved_input)


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
    """old revision 규칙과 current Application 구조의 대조 결과."""

    work_authority_id: str
    target_application_id: str
    review_basis_digest: str
    classifications: tuple[FieldReviewClassification, ...]

    def broken_field_ids(self) -> tuple[str, ...]:
        return tuple(
            c.field_id for c in self.classifications if c.category == BROKEN
        )


def review_basis_digest(structure: CurrentApplicationFieldStructure) -> str:
    """current Application 구조의 content-address — commit 시점 재확인 기준."""
    hasher = hashlib.sha256()
    hasher.update(b"field-binding-review-basis/v1\0")
    raw = structure.application_id.encode("utf-8")
    hasher.update(len(raw).to_bytes(4, "big"))
    hasher.update(raw)
    for label, values in (
        (b"active", structure.active_field_ids),
        (b"inactive", structure.inactive_field_ids),
        (b"schema", structure.source_schema_keys),
    ):
        hasher.update(label)
        hasher.update(len(values).to_bytes(4, "big"))
        for value in sorted(values, key=lambda v: v.encode("utf-8")):
            r = value.encode("utf-8")
            hasher.update(len(r).to_bytes(4, "big"))
            hasher.update(r)
    return "sha256:" + hasher.hexdigest()


def review_field_binding_for_current_application(
    old_revision: FieldBindingRevision,
    structure: CurrentApplicationFieldStructure,
) -> FieldBindingApplicationReview:
    """old exact 규칙 vs A18 Field 구조 대조 → PRESERVED/BROKEN/NEW_ACTIVE_FIELD/INACTIVE_ONLY.

    source 규칙은 exact source key 재결속 가능성까지 본다(현재 스키마에 없으면 BROKEN).
    silent rebase·old revision base 재지정은 하지 않는다 — 분류만 낸다.
    """
    active = set(structure.active_field_ids)
    inactive = set(structure.inactive_field_ids)
    schema = set(structure.source_schema_keys)
    classifications: list[FieldReviewClassification] = []
    old_fields: set[str] = set()
    for rule in old_revision.binding_rules:
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
    return FieldBindingApplicationReview(
        work_authority_id=old_revision.work_authority_id,
        target_application_id=structure.application_id,
        review_basis_digest=review_basis_digest(structure),
        classifications=tuple(classifications),
    )


def decide_application_review_commit(
    review: FieldBindingApplicationReview,
    resolved_input: FieldBindingInput,
    current_structure: CurrentApplicationFieldStructure,
) -> FieldBindingRevision:
    """review commit 순수 결정 — 성공하면 base=current Application 의 immutable revision.

    - current Application 이 review target 과 다르거나 basis digest 이동 → stale(미기록).
    - resolved_input 이 current active 아닌 Field 를 여전히 참조 → 미해결 BROKEN(미기록).
    - base 는 current Application 이어야 한다(old revision base 재지정 없음).
    """
    if current_structure.application_id != review.target_application_id or (
        review_basis_digest(current_structure) != review.review_basis_digest
    ):
        raise StaleFieldBindingBasis("review basis 가 capture 이후 이동했다")
    if resolved_input.base_template_application_id != review.target_application_id:
        raise FieldBindingInputIntegrityError(
            "resolved_input base 는 current Application 이어야 한다"
        )
    active = set(current_structure.active_field_ids)
    for rule in resolved_input.binding_rules:
        if rule.field_id not in active:
            raise FieldBindingReviewRequired(
                "FIELD_BINDING_APPLICATION_REVIEW_REQUIRED",
                f"미해결 Field(현재 active 아님): {rule.field_id!r}",
            )
    if resolved_input.work_authority_id != review.work_authority_id:
        raise FieldBindingInputIntegrityError(
            "resolved_input 의 work_authority_id 가 review 와 다르다"
        )
    return revision_from_input(resolved_input)
