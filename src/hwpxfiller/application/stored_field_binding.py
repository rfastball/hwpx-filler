"""S5 Work별 Field Binding 저장 aggregate — immutable revision·durable ledger (S5-01 · #697).

한 Work 의 durable Field Binding 상태를 담는다: create-once immutable revision history,
Application 별 current revision pointer, 두 commit 종류의 provenance record, 그리고 request 별
최초 terminal outcome 을 immutable 로 보존하는 first-seen idempotency ledger.

파일 원자 replace·writer lease·CAS 기계는 :mod:`hwpxfiller.external.field_binding_store` 가 진다 —
여기는 값·불변식·codec 만 소유한다. ``aggregate_version`` 은 durable commit 횟수다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from hwpxfiller.domain.field_binding import (
    ExactText,
    FieldBindingError,
    FieldBindingInputIntegrityError,
    FieldBindingRule,
    resolve_document_value_policy,
)
from hwpxfiller.application.field_binding_input import FieldBindingRevision

STORE_SCHEMA_VERSION = "work-field-binding-store-v2"

MIGRATION = "MIGRATION"
APPLICATION_REVIEW = "APPLICATION_REVIEW"
_DRAFT_KINDS = (MIGRATION, APPLICATION_REVIEW)


class StoredFieldBindingError(ValueError):
    """저장 aggregate 값·ledger 불변식 위반."""


class FieldBindingIdempotencyKeyReused(StoredFieldBindingError):
    """같은 request_id 를 다른 fingerprint 로 재사용 — 최초 record 를 수정하지 않는다."""

    code = "IDEMPOTENCY_KEY_REUSED"


def _require_nonempty(value: object, what: str) -> str:
    if not isinstance(value, str) or value == "":
        raise StoredFieldBindingError(f"{what} 는 비어 있지 않은 문자열이어야 한다")
    return value


# ─── ledger / provenance records ─────────────────────────────────────────────────
@dataclass(frozen=True)
class FieldBindingIdempotencyRecord:
    """request_id 별 최초 terminal record — 한번 적히면 immutable."""

    request_id: str
    fingerprint_schema_version: str
    command_fingerprint: str
    produced_revision_id: str
    outcome_code: str
    recorded_at: str

    def __post_init__(self) -> None:
        _require_nonempty(self.request_id, "request_id")
        _require_nonempty(self.fingerprint_schema_version, "fingerprint_schema_version")
        _require_nonempty(self.command_fingerprint, "command_fingerprint")
        _require_nonempty(self.produced_revision_id, "produced_revision_id")
        _require_nonempty(self.outcome_code, "outcome_code")
        _require_nonempty(self.recorded_at, "recorded_at")


@dataclass(frozen=True)
class CommittedDraftRecord:
    """commit 된 migration/review 의 durable provenance(어떤 basis 가 어떤 revision 을 냈는가)."""

    kind: str
    request_id: str
    application_id: str
    basis_fingerprint: str
    produced_revision_id: str
    recorded_at: str

    def __post_init__(self) -> None:
        if self.kind not in _DRAFT_KINDS:
            raise StoredFieldBindingError(f"미지원 draft kind: {self.kind!r}")
        _require_nonempty(self.request_id, "request_id")
        _require_nonempty(self.application_id, "application_id")
        _require_nonempty(self.basis_fingerprint, "basis_fingerprint")
        _require_nonempty(self.produced_revision_id, "produced_revision_id")
        _require_nonempty(self.recorded_at, "recorded_at")


@dataclass(frozen=True)
class ApplicationRevisionPointer:
    application_id: str
    revision_id: str

    def __post_init__(self) -> None:
        _require_nonempty(self.application_id, "application_id")
        _require_nonempty(self.revision_id, "revision_id")


# ─── aggregate ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class StoredWorkFieldBinding:
    schema_version: str
    aggregate_version: int
    workspace_instance_id: str
    work_authority_id: str
    current_by_application: tuple[ApplicationRevisionPointer, ...]
    immutable_binding_revisions: tuple[FieldBindingRevision, ...]
    migration_drafts: tuple[CommittedDraftRecord, ...]
    application_review_drafts: tuple[CommittedDraftRecord, ...]
    first_seen_command_ledger: tuple[FieldBindingIdempotencyRecord, ...]

    def __post_init__(self) -> None:
        if self.schema_version != STORE_SCHEMA_VERSION:
            raise StoredFieldBindingError(
                f"미상 store schema_version {self.schema_version!r}"
            )
        if isinstance(self.aggregate_version, bool) or not isinstance(
            self.aggregate_version, int
        ):
            raise StoredFieldBindingError("aggregate_version 은 정수여야 한다")
        if self.aggregate_version < 1:
            raise StoredFieldBindingError("aggregate_version 은 1 이상이다")
        _require_nonempty(self.workspace_instance_id, "workspace_instance_id")
        _require_nonempty(self.work_authority_id, "work_authority_id")
        revision_ids: set[str] = set()
        for revision in self.immutable_binding_revisions:
            if not isinstance(revision, FieldBindingRevision):
                raise StoredFieldBindingError("revision 이 FieldBindingRevision 이 아니다")
            rid = revision.field_binding_authority_revision
            if rid in revision_ids:
                raise StoredFieldBindingError(f"revision identity 중복: {rid}")
            revision_ids.add(rid)
        seen_app: set[str] = set()
        for pointer in self.current_by_application:
            if pointer.application_id in seen_app:
                raise StoredFieldBindingError(
                    f"Application 당 current pointer 는 하나: {pointer.application_id}"
                )
            seen_app.add(pointer.application_id)
            if pointer.revision_id not in revision_ids:
                raise StoredFieldBindingError(
                    f"current pointer 가 없는 revision 을 가리킨다: {pointer.revision_id}"
                )
        seen_req: set[str] = set()
        for record in self.first_seen_command_ledger:
            if record.request_id in seen_req:
                raise StoredFieldBindingError(
                    f"request_id 당 record 는 하나: {record.request_id}"
                )
            seen_req.add(record.request_id)


def empty_stored(
    workspace_instance_id: str, work_authority_id: str
) -> StoredWorkFieldBinding:
    return StoredWorkFieldBinding(
        schema_version=STORE_SCHEMA_VERSION,
        aggregate_version=1,
        workspace_instance_id=workspace_instance_id,
        work_authority_id=work_authority_id,
        current_by_application=(),
        immutable_binding_revisions=(),
        migration_drafts=(),
        application_review_drafts=(),
        first_seen_command_ledger=(),
    )


def find_request(
    stored: StoredWorkFieldBinding, request_id: str
) -> FieldBindingIdempotencyRecord | None:
    for record in stored.first_seen_command_ledger:
        if record.request_id == request_id:
            return record
    return None


def revision_by_id(
    stored: StoredWorkFieldBinding, revision_id: str
) -> FieldBindingRevision | None:
    for revision in stored.immutable_binding_revisions:
        if revision.field_binding_authority_revision == revision_id:
            return revision
    return None


def current_revision_id(
    stored: StoredWorkFieldBinding, application_id: str
) -> str | None:
    for pointer in stored.current_by_application:
        if pointer.application_id == application_id:
            return pointer.revision_id
    return None


def commit_revision(
    stored: StoredWorkFieldBinding,
    revision: FieldBindingRevision,
    draft_record: CommittedDraftRecord,
    ledger_record: FieldBindingIdempotencyRecord,
) -> StoredWorkFieldBinding:
    """한 aggregate commit 으로 revision(신규면 추가·기존이면 그대로)·current pointer·draft·ledger 갱신.

    revision 은 create-once content-address 라 같은 id 재등장은 dedup(기존 base 를 수정하지 않는다).
    dedup 판정은 identity(``field_binding_authority_revision``)로만 한다 — dataclass equality 는
    identity 에 불참하는 ``captured_at``(provenance)이나 digest-불변인 규칙·키 순서에서 갈려
    정상 재commit 을 거짓 충돌로 만든다. identity 가 같으면 **기존 revision 을 유지**한다.
    aggregate_version 은 store 가 CAS 로 +1 한다(여기선 그대로 둔다).
    """
    rid = revision.field_binding_authority_revision
    existing = revision_by_id(stored, rid)
    revisions = (
        stored.immutable_binding_revisions
        if existing is not None
        else stored.immutable_binding_revisions + (revision,)
    )
    pointers = tuple(
        p
        for p in stored.current_by_application
        if p.application_id != revision.base_template_application_id
    ) + (ApplicationRevisionPointer(revision.base_template_application_id, rid),)
    if draft_record.kind == MIGRATION:
        migrations = stored.migration_drafts + (draft_record,)
        reviews = stored.application_review_drafts
    else:
        migrations = stored.migration_drafts
        reviews = stored.application_review_drafts + (draft_record,)
    return replace(
        stored,
        current_by_application=pointers,
        immutable_binding_revisions=revisions,
        migration_drafts=migrations,
        application_review_drafts=reviews,
        first_seen_command_ledger=(
            stored.first_seen_command_ledger + (ledger_record,)
        ),
    )


# ─── codec ─────────────────────────────────────────────────────────────────────
def _encode_rule(rule: FieldBindingRule) -> dict[str, Any]:
    """v2 규칙 표현 — 고정값은 tagged 표현 없이 텍스트 하나로 평탄화한다(값 알파벳이 단형)."""
    return {
        "field_id": rule.field_id,
        "binding_kind": rule.binding_kind,
        "policy_id": rule.document_content_value_policy.policy_id,
        "source_key": rule.source_key,
        "format_code": rule.format_code,
        "canonical_constant_text": (
            None
            if rule.canonical_constant_value is None
            else rule.canonical_constant_value.text
        ),
    }


def _decode_rule(data: Any) -> FieldBindingRule:
    if not isinstance(data, dict):
        raise StoredFieldBindingError("규칙 표현이 malformed")
    try:
        policy = resolve_document_value_policy(data.get("policy_id"))
    except FieldBindingError as exc:  # policy_id None·미지원 → fail-closed
        raise StoredFieldBindingError("policy_id 표현이 malformed·미지원") from exc
    constant_text = data.get("canonical_constant_text")
    if constant_text is not None and not isinstance(constant_text, str):
        raise StoredFieldBindingError("canonical_constant_text 표현이 malformed")
    return FieldBindingRule(
        field_id=data.get("field_id"),
        binding_kind=data.get("binding_kind"),
        document_content_value_policy=policy,
        source_key=data.get("source_key"),
        format_code=data.get("format_code"),
        canonical_constant_value=(
            None if constant_text is None else ExactText(constant_text)
        ),
    )


def _encode_revision(revision: FieldBindingRevision) -> dict[str, Any]:
    return {
        "work_authority_id": revision.work_authority_id,
        "base_template_application_id": revision.base_template_application_id,
        "field_binding_authority_revision": revision.field_binding_authority_revision,
        "field_binding_semantic_contract_id": (
            revision.field_binding_semantic_contract_id
        ),
        "source_schema_contract_id": revision.source_schema_contract_id,
        "raw_record_contract_id": revision.raw_record_contract_id,
        "binding_rules": [_encode_rule(r) for r in revision.binding_rules],
        "source_schema_keys": list(revision.source_schema_keys),
        "canonical_binding_digest": revision.canonical_binding_digest,
        "canonical_source_schema_digest": revision.canonical_source_schema_digest,
        "captured_at": revision.captured_at,
    }


def _decode_revision(data: Any) -> FieldBindingRevision:
    if not isinstance(data, dict):
        raise StoredFieldBindingError("revision 표현이 malformed")
    rules = data.get("binding_rules")
    keys = data.get("source_schema_keys")
    if not isinstance(rules, list) or not isinstance(keys, list):
        raise StoredFieldBindingError("revision 규칙·스키마 표현이 malformed")
    try:
        return FieldBindingRevision(
            work_authority_id=data.get("work_authority_id"),
            base_template_application_id=data.get("base_template_application_id"),
            field_binding_authority_revision=data.get(
                "field_binding_authority_revision"
            ),
            field_binding_semantic_contract_id=data.get(
                "field_binding_semantic_contract_id"
            ),
            source_schema_contract_id=data.get("source_schema_contract_id"),
            raw_record_contract_id=data.get("raw_record_contract_id"),
            binding_rules=tuple(_decode_rule(r) for r in rules),
            source_schema_keys=tuple(keys),
            canonical_binding_digest=data.get("canonical_binding_digest"),
            canonical_source_schema_digest=data.get(
                "canonical_source_schema_digest"
            ),
            captured_at=data.get("captured_at"),
        )
    except FieldBindingInputIntegrityError as exc:
        # digest 유효해도 내부가 부정합이면 store 계약 오류로 정규화(fail-closed).
        raise StoredFieldBindingError("revision 불변식 위반") from exc


def _encode_pointer(pointer: ApplicationRevisionPointer) -> dict[str, Any]:
    return {
        "application_id": pointer.application_id,
        "revision_id": pointer.revision_id,
    }


def _decode_pointer(data: Any) -> ApplicationRevisionPointer:
    if not isinstance(data, dict):
        raise StoredFieldBindingError("current pointer 표현이 malformed")
    return ApplicationRevisionPointer(
        application_id=data.get("application_id"),
        revision_id=data.get("revision_id"),
    )


def _encode_draft(record: CommittedDraftRecord) -> dict[str, Any]:
    return {
        "kind": record.kind,
        "request_id": record.request_id,
        "application_id": record.application_id,
        "basis_fingerprint": record.basis_fingerprint,
        "produced_revision_id": record.produced_revision_id,
        "recorded_at": record.recorded_at,
    }


def _decode_draft(data: Any) -> CommittedDraftRecord:
    if not isinstance(data, dict):
        raise StoredFieldBindingError("draft record 표현이 malformed")
    return CommittedDraftRecord(
        kind=data.get("kind"),
        request_id=data.get("request_id"),
        application_id=data.get("application_id"),
        basis_fingerprint=data.get("basis_fingerprint"),
        produced_revision_id=data.get("produced_revision_id"),
        recorded_at=data.get("recorded_at"),
    )


def _encode_ledger(record: FieldBindingIdempotencyRecord) -> dict[str, Any]:
    return {
        "request_id": record.request_id,
        "fingerprint_schema_version": record.fingerprint_schema_version,
        "command_fingerprint": record.command_fingerprint,
        "produced_revision_id": record.produced_revision_id,
        "outcome_code": record.outcome_code,
        "recorded_at": record.recorded_at,
    }


def _decode_ledger(data: Any) -> FieldBindingIdempotencyRecord:
    if not isinstance(data, dict):
        raise StoredFieldBindingError("ledger record 표현이 malformed")
    return FieldBindingIdempotencyRecord(
        request_id=data.get("request_id"),
        fingerprint_schema_version=data.get("fingerprint_schema_version"),
        command_fingerprint=data.get("command_fingerprint"),
        produced_revision_id=data.get("produced_revision_id"),
        outcome_code=data.get("outcome_code"),
        recorded_at=data.get("recorded_at"),
    )


def _decode_draft_list(data: Any, what: str) -> tuple[CommittedDraftRecord, ...]:
    if not isinstance(data, list):
        raise StoredFieldBindingError(f"{what} 는 리스트여야 한다")
    return tuple(_decode_draft(d) for d in data)


def encode_stored(stored: StoredWorkFieldBinding) -> dict[str, Any]:
    return {
        "schema_version": stored.schema_version,
        "aggregate_version": stored.aggregate_version,
        "workspace_instance_id": stored.workspace_instance_id,
        "work_authority_id": stored.work_authority_id,
        "current_by_application": [
            _encode_pointer(p) for p in stored.current_by_application
        ],
        "immutable_binding_revisions": [
            _encode_revision(r) for r in stored.immutable_binding_revisions
        ],
        "migration_drafts": [_encode_draft(d) for d in stored.migration_drafts],
        "application_review_drafts": [
            _encode_draft(d) for d in stored.application_review_drafts
        ],
        "first_seen_command_ledger": [
            _encode_ledger(r) for r in stored.first_seen_command_ledger
        ],
    }


def decode_stored(data: Any) -> StoredWorkFieldBinding:
    if not isinstance(data, dict):
        raise StoredFieldBindingError("stored aggregate 표현이 malformed")
    for key in (
        "current_by_application",
        "immutable_binding_revisions",
        "first_seen_command_ledger",
    ):
        if not isinstance(data.get(key), list):
            raise StoredFieldBindingError(f"{key} 는 리스트여야 한다")
    return StoredWorkFieldBinding(
        schema_version=data.get("schema_version"),
        aggregate_version=data.get("aggregate_version"),
        workspace_instance_id=data.get("workspace_instance_id"),
        work_authority_id=data.get("work_authority_id"),
        current_by_application=tuple(
            _decode_pointer(p) for p in data["current_by_application"]
        ),
        immutable_binding_revisions=tuple(
            _decode_revision(r) for r in data["immutable_binding_revisions"]
        ),
        migration_drafts=_decode_draft_list(
            data.get("migration_drafts"), "migration_drafts"
        ),
        application_review_drafts=_decode_draft_list(
            data.get("application_review_drafts"), "application_review_drafts"
        ),
        first_seen_command_ledger=tuple(
            _decode_ledger(r) for r in data["first_seen_command_ledger"]
        ),
    )
