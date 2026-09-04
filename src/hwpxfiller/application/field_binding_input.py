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
    DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
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

#: 소스 값을 나르는 legacy 유형(나머지는 const·today 로 따로 갈린다). 값 유형 어휘가
#: 사라졌으므로 이 집합은 "SOURCE 후보인가"만 가른다 — 미지 유형은 조용히 확장하지 않고
#: 시끄럽게 거절한다.
_LEGACY_SOURCE_TYPES = ("text", "date", "amount")

# review 분류 어휘.
PRESERVED = "PRESERVED"
BROKEN = "BROKEN"
NEW_ACTIVE_FIELD = "NEW_ACTIVE_FIELD"
#: 판본에 규칙이 있으나 current Application 에서 비활성인 Field — **판본이 계속 보존하는 규칙**이다
#: (U3-04 #877). 확정 이후 Option 을 바꿔 비활성이 됐다는 사실 하나로 규칙을 버리면, 그 Option 으로
#: 되돌아올 때마다 같은 결정을 다시 확정하게 된다. 실행에 참여하지 않을 뿐 판본에서는 산다.
INACTIVE_ONLY = "INACTIVE_ONLY"

# migration blocker 어휘.
#: legacy ``today``(오늘 날짜, U4-E1 #939) — 값이 **실행 시각**에서 나오므로 SOURCE(데이터
#: 열)도 CONSTANT(고정 리터럴)도 아니다. 이 slice 는 binding kind 어휘를 늘리지 않으므로
#: 후보 규칙을 짓지 않고 blocker 로 남긴다. SOURCE(빈 source_key)나 CONSTANT(그때의 렌더값)로
#: 접으면 **거짓 durable 규칙**을 판본에 적는다 — 조용히 틀리느니 시끄럽게 막는다.
RUNTIME_TODAY_UNSUPPORTED = "RUNTIME_TODAY_UNSUPPORTED"

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
        # 저장 revision 이 미지원 contract 를 담고 있으면 fail-closed(구버전 앱이 모르는 의미 방지).
        require_field_binding_contract(self.field_binding_semantic_contract_id)
        require_source_schema_contract(self.source_schema_contract_id)
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
    legacy_type: str  # text·date·amount·const·today
    source: str
    const: str
    fmt: str


@dataclass(frozen=True)
class MigrationCandidateRule:
    """migration 후보 규칙 — 명시 정책 후보를 붙여 표면화하되 자동 확정하지 않는다."""

    field_id: str
    binding_kind: str
    source_key: str | None
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
    """legacy → field-binding migration 초안 — legacy authority 를 수정하지 않는다.

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
    - const 는 canonicalization 후보(ExactText)로 옮긴다 — 빈 const 는 ``ExactText("")``,
      곧 「빈 문자열을 써 넣는다」는 선언 그대로다(옛 blank omission 의 후계라 모호하지 않다).
    """
    entries = tuple(legacy_entries)
    candidates: list[MigrationCandidateRule] = []
    blockers: list[MigrationBlocker] = []
    for entry in entries:
        if entry.legacy_type == "const":
            candidates.append(
                MigrationCandidateRule(
                    field_id=entry.template_field,
                    binding_kind=CONSTANT,
                    source_key=None,
                    canonical_constant_value=ExactText(entry.const),
                    format_code=None,
                    proposed_policy_id=DOCUMENT_CONTENT_VALUE_POLICY_V1.policy_id,
                    whitespace_decision_required=False,
                )
            )
            continue
        if entry.legacy_type == "today":
            # 실행 시각에서 값을 얻는 Field — binding kind 어휘(SOURCE/CONSTANT/
            # INTENTIONAL_BLANK)에 대응이 없다. 억지로 접지 않고 명시 결정으로 남긴다.
            blockers.append(
                MigrationBlocker(entry.template_field, RUNTIME_TODAY_UNSUPPORTED)
            )
            continue
        if entry.legacy_type not in _LEGACY_SOURCE_TYPES:
            raise FieldBindingInputIntegrityError(
                f"미지원 legacy 유형: {entry.legacy_type!r} ({entry.template_field!r})"
            )
        candidates.append(
            MigrationCandidateRule(
                field_id=entry.template_field,
                binding_kind=SOURCE,
                source_key=entry.source,
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
    current_application_id: str,
    current_legacy_basis_fingerprint: str,
    omitted_field_ids: "frozenset[str] | set[str]" = frozenset(),
) -> FieldBindingRevision:
    """migration commit 순수 결정 — 성공하면 immutable revision, 아니면 typed 오류.

    - basis 이동(legacy fingerprint **또는** current Application 이동) → :class:`StaleFieldBindingBasis`.
    - draft 가 표면화한 field(candidate·blocker) 가 resolved_input 에 없고 명시 omission 결정도
      없으면 → review required(값 누락 silent drop 방지, 미기록).
    - 그 외 integrity 위반 → :class:`FieldBindingInputIntegrityError`(미기록).
    """
    # current Application 이 draft 의 base 와 다르면 legacy fingerprint 가 같아도 stale 이다.
    if (
        current_legacy_basis_fingerprint != draft.legacy_basis_fingerprint
        or current_application_id != draft.base_template_application_id
        or resolved_input.base_template_application_id
        != draft.base_template_application_id
    ):
        raise StaleFieldBindingBasis("legacy migration basis 가 capture 이후 이동했다")
    resolved_fields = {rule.field_id for rule in resolved_input.binding_rules}
    accounted = resolved_fields | set(omitted_field_ids)
    # draft 가 드러낸 모든 field 는 명시 규칙이거나 명시 omission 이어야 한다(누락=silent drop).
    surfaced = {c.field_id for c in draft.candidate_rules} | {
        b.field_id for b in draft.blockers
    }
    for field_id in surfaced:
        if field_id not in accounted:
            raise FieldBindingReviewRequired(
                "FIELD_BINDING_MIGRATION_REVIEW_REQUIRED",
                f"미해결 legacy field(규칙·명시 omission 없음): {field_id!r}",
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

    def inactive_only_field_ids(self) -> tuple[str, ...]:
        """판본이 보존해야 할 비활성 Field — 다음 commit 이 그대로 실어 나른다(#877).

        BROKEN(템플릿에서 사라졌거나 재결속 불가)은 여기 들지 않는다 — 보존 가능한 것은 current
        Application 이 여전히 아는 Field 뿐이다.
        """
        return tuple(
            c.field_id for c in self.classifications if c.category == INACTIVE_ONLY
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

    분류의 스코프는 판본이다(#877): INACTIVE_ONLY 는 "판본이 보존 중이나 지금은 실행에 참여하지
    않는 규칙"이고, NEW_ACTIVE_FIELD 는 "판본에 규칙이 정말 없는 활성 Field"다. 비활성이었다가
    다시 활성이 된 Field 는 규칙이 판본에 남아 있으므로 PRESERVED 로 온다(재확정 요구 0).
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
    - resolved_input 이 current Application 이 모르는 Field(active 도 inactive 도 아님)를
      참조하면 → 미해결 BROKEN(미기록).
    - **Active Field 에 결속한** SOURCE 규칙이 current schema 에 없는 source_key 를 쓰면 →
      미해결 BROKEN(미기록). 실행에 참여하는 규칙은 current data 에 결속 가능해야 한다.
    - base 는 current Application 이어야 한다(old revision base 재지정 없음).

    **판본 스코프는 active 절단이 아니다**(U3-04 #877). 판본은 "한 번이라도 확정된 Field 의
    규칙"을 담고, 그 중 지금 실행에 참여하는 것은 compile 이 Active projection 으로 고른다
    (:func:`hwpxfiller.application.execution_compilation.qualify_and_compile_execution`). 그래서
    비활성 Field 규칙을 실은 입력도 여기서 거절하지 않는다 — 거절하면 Option 을 오갈 때마다 이미
    확정한 결정이 판본에서 탈락해 재확정을 무한히 요구하게 된다. 비활성 규칙의 source_key 는
    current schema 대조 대상이 아니다(다시 활성이 될 때 review 가 BROKEN 으로 시끄럽게 잡는다).
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
    inactive = set(current_structure.inactive_field_ids)
    current_schema = set(current_structure.source_schema_keys)
    for rule in resolved_input.binding_rules:
        if rule.field_id not in active:
            # 보존 중인 비활성 규칙은 통과, current Application 이 아예 모르는 Field 는 거절.
            if rule.field_id not in inactive:
                raise FieldBindingReviewRequired(
                    "FIELD_BINDING_APPLICATION_REVIEW_REQUIRED",
                    f"미해결 Field(현재 Application 에 없음): {rule.field_id!r}",
                )
            continue
        # Active SOURCE 규칙은 current schema 에 있는 source_key 로만 결속돼야 한다(stale 결속 방지).
        if rule.binding_kind == SOURCE and rule.source_key not in current_schema:
            raise FieldBindingReviewRequired(
                "FIELD_BINDING_APPLICATION_REVIEW_REQUIRED",
                f"미해결 source_key(current schema 부재): {rule.source_key!r}",
            )
    if resolved_input.work_authority_id != review.work_authority_id:
        raise FieldBindingInputIntegrityError(
            "resolved_input 의 work_authority_id 가 review 와 다르다"
        )
    return revision_from_input(resolved_input)
