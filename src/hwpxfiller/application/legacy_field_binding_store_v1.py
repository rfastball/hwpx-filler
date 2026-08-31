"""``work-field-binding-store-v1`` 동결 사본 + v2 decode-path 마이그레이션.

데이터 값 타입 어휘(DECIMAL/DATE/DATETIME/BOOLEAN)를 코어에서 물리 제거하면서 이미 디스크에
적힌 v1 aggregate 는 무손실로 계속 읽혀야 한다. 그 v1 프레이밍(매직 bytes·길이 접두 UTF-8·
``field-binding/v1``·``source-schema/v1``·typed 값 태그)은 **여기 동결 사본으로만** 산다 —
:mod:`hwpxfiller.domain.field_binding` 은 v1 을 모른다(도메인은 현재 어휘 하나만 안다).

마이그레이션은 revision 마다 **3중 재계산 대조**를 먼저 통과시킨다(fail-closed):

1. 저장 ``canonical_binding_digest`` == v1 규칙 canonical bytes 재계산
2. 저장 ``canonical_source_schema_digest`` == v1 소스 스키마 canonical bytes 재계산
3. 저장 ``field_binding_authority_revision`` == v1 content-address 재유도

셋을 통과한 revision 만 SOURCE 의 ``value_type`` 을 **accept-and-drop** 하고 v2 규칙으로 옮긴다.
typed constant(v1 에서도 생산 경로가 없어 손편집으로만 만들어지는 값)는 조용한 의미 변환 대신
시끄럽게 거절한다. v2 revision id 는 새 content-address 로 **재유도**하고, old→new 사상표로
``current_by_application``·draft·ledger 의 revision 참조를 전부 재사상한다. ``command_fingerprint``·
``basis_fingerprint`` 는 역사 기록이라 손대지 않는다.

읽기 경로는 파일을 다시 쓰지 않는다 — 다음 durable commit 의 ``update()`` 가 v2 로 재봉인한다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hwpxfiller.application.field_binding_input import (
    FieldBindingRevision,
    field_binding_authority_revision_identity,
)
from hwpxfiller.application.stored_field_binding import (
    STORE_SCHEMA_VERSION,
    ApplicationRevisionPointer,
    CommittedDraftRecord,
    FieldBindingIdempotencyRecord,
    StoredFieldBindingError,
    StoredWorkFieldBinding,
)
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    FIELD_BINDING_SEMANTIC_VERSION,
    SOURCE,
    SOURCE_SCHEMA_VERSION,
    ExactText,
    FieldBindingError,
    FieldBindingInputIntegrityError,
    FieldBindingRule,
    digest_binding_rules,
    digest_source_schema,
    resolve_document_value_policy,
)

# ─── 동결 v1 상수(수정 금지 — 디스크에 이미 적힌 bytes 의 정의다) ─────────────────────────
STORE_SCHEMA_VERSION_V1 = "work-field-binding-store-v1"
FIELD_BINDING_SEMANTIC_VERSION_V1 = "field-binding/v1"
SOURCE_SCHEMA_VERSION_V1 = "source-schema/v1"

_BINDING_MAGIC_V1 = b"HFBIND1\0"
_SCHEMA_MAGIC_V1 = b"HFSSC1\0\0"
_U32_MAX = 0xFFFF_FFFF

#: v1 constant 값 태그 → canonical byte 태그·literal 키. EXACT_TEXT 만 v2 로 옮길 수 있다.
_V1_VALUE_TAGS: dict[str, tuple[bytes, str]] = {
    "EXACT_TEXT": (b"\x01", "text"),
    "DECIMAL": (b"\x02", "literal"),
    "DATE": (b"\x03", "iso"),
    "DATETIME": (b"\x04", "iso"),
    "BOOLEAN": (b"\x05", "value"),
}

#: v1 SOURCE 규칙이 나르던 값 유형 어휘 — accept-and-drop 대상이라 판별용으로만 남긴다.
_V1_VALUE_TYPES = ("EXACT_TEXT", "DECIMAL", "DATE", "DATETIME", "BOOLEAN")


class LegacyFieldBindingStoreV1Error(StoredFieldBindingError):
    """v1 aggregate 를 v2 로 옮길 수 없다 — 조용한 승격 대신 시끄러운 거절."""


# ─── 동결 v1 canonical framing ─────────────────────────────────────────────────────
def _text_v1(value: str) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > _U32_MAX:  # pragma: no cover - 4GB 초과 텍스트는 발생하지 않는다
        raise LegacyFieldBindingStoreV1Error("v1 canonical text 가 u32 범위 초과")
    return len(raw).to_bytes(4, "big") + raw


def _opt_text_v1(value: str | None) -> bytes:
    if value is None:
        return b"\x00"
    return b"\x01" + _text_v1(value)


def _u32_v1(value: int) -> bytes:
    if value < 0 or value > _U32_MAX:  # pragma: no cover - u32 범위 밖 count 는 없다
        raise LegacyFieldBindingStoreV1Error("v1 canonical count 가 u32 범위 초과")
    return value.to_bytes(4, "big")


def _encode_value_v1(data: Any) -> bytes:
    """저장된 v1 constant 값 표현 → v1 canonical bytes(도메인 객체 재구성 없이)."""
    if not isinstance(data, Mapping):
        raise LegacyFieldBindingStoreV1Error("v1 constant 값 표현이 malformed")
    kind = data.get("kind")
    entry = _V1_VALUE_TAGS.get(kind) if isinstance(kind, str) else None
    if entry is None:
        raise LegacyFieldBindingStoreV1Error(f"미지원 v1 constant 값 kind: {kind!r}")
    tag, literal_key = entry
    literal = data.get(literal_key)
    if kind == "BOOLEAN":
        if not isinstance(literal, bool):
            raise LegacyFieldBindingStoreV1Error("v1 BOOLEAN constant 값이 bool 이 아니다")
        return tag + (b"\x01" if literal else b"\x00")
    if not isinstance(literal, str):
        raise LegacyFieldBindingStoreV1Error(
            f"v1 {kind} constant literal 이 문자열이 아니다"
        )
    return tag + _text_v1(literal)


@dataclass(frozen=True)
class _V1Rule:
    """저장된 v1 규칙의 exact capture — 재해석 없이 원본 슬롯 그대로."""

    field_id: str
    binding_kind: str
    policy_id: str
    source_key: str | None
    value_type: str | None
    format_code: str | None
    canonical_constant_value: Any


def _decode_rule_v1(data: Any) -> _V1Rule:
    if not isinstance(data, Mapping):
        raise LegacyFieldBindingStoreV1Error("v1 규칙 표현이 malformed")
    field_id = data.get("field_id")
    binding_kind = data.get("binding_kind")
    policy_id = data.get("policy_id")
    if (
        not isinstance(field_id, str)
        or field_id == ""
        or not isinstance(binding_kind, str)
        or not isinstance(policy_id, str)
    ):
        raise LegacyFieldBindingStoreV1Error("v1 규칙의 field_id/binding_kind/policy_id 가 malformed")
    for name in ("source_key", "value_type", "format_code"):
        value = data.get(name)
        if value is not None and not isinstance(value, str):
            raise LegacyFieldBindingStoreV1Error(f"v1 규칙의 {name} 이 malformed")
    return _V1Rule(
        field_id=field_id,
        binding_kind=binding_kind,
        policy_id=policy_id,
        source_key=data.get("source_key"),
        value_type=data.get("value_type"),
        format_code=data.get("format_code"),
        canonical_constant_value=data.get("canonical_constant_value"),
    )


def _encode_rule_v1(rule: _V1Rule) -> bytes:
    out = bytearray()
    out += _text_v1(rule.field_id)
    out += _text_v1(rule.binding_kind)
    out += _text_v1(rule.policy_id)
    out += _opt_text_v1(rule.source_key)
    out += _opt_text_v1(rule.value_type)
    out += _opt_text_v1(rule.format_code)
    if rule.canonical_constant_value is None:
        out += b"\x00"
    else:
        out += b"\x01" + _encode_value_v1(rule.canonical_constant_value)
    return bytes(out)


def digest_binding_rules_v1(rules: tuple[_V1Rule, ...]) -> str:
    """``field-binding/v1`` 규칙 집합의 정본 digest(동결 재현)."""
    seen: set[str] = set()
    for rule in rules:
        if rule.field_id in seen:
            raise LegacyFieldBindingStoreV1Error(
                f"v1 한 Field 에 규칙이 둘 이상이다: {rule.field_id!r}"
            )
        seen.add(rule.field_id)
    out = bytearray()
    out += _BINDING_MAGIC_V1
    out += _text_v1(FIELD_BINDING_SEMANTIC_VERSION_V1)
    out += _u32_v1(len(rules))
    for rule in sorted(rules, key=lambda r: r.field_id.encode("utf-8")):
        encoded = _encode_rule_v1(rule)
        out += _u32_v1(len(encoded))
        out += encoded
    return "sha256:" + hashlib.sha256(bytes(out)).hexdigest()


def digest_source_schema_v1(keys: tuple[str, ...]) -> str:
    """``source-schema/v1`` key 집합의 정본 digest(동결 재현)."""
    seen: set[str] = set()
    for key in keys:
        if not isinstance(key, str):
            raise LegacyFieldBindingStoreV1Error("v1 source schema key 가 문자열이 아니다")
        if key in seen:
            raise LegacyFieldBindingStoreV1Error(f"v1 source schema 중복 key: {key!r}")
        seen.add(key)
    out = bytearray()
    out += _SCHEMA_MAGIC_V1
    out += _text_v1(SOURCE_SCHEMA_VERSION_V1)
    out += _u32_v1(len(keys))
    for key in sorted(keys, key=lambda k: k.encode("utf-8")):
        out += _text_v1(key)
    return "sha256:" + hashlib.sha256(bytes(out)).hexdigest()


# ─── v1 → v2 마이그레이션 ───────────────────────────────────────────────────────────
def _require_text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or value == "":
        raise LegacyFieldBindingStoreV1Error(f"v1 aggregate 의 {key} 가 malformed")
    return value


def _v2_rule(rule: _V1Rule) -> FieldBindingRule:
    """v1 규칙 → v2 규칙. SOURCE 의 value_type 은 accept-and-drop, typed constant 는 거절."""
    try:
        policy = resolve_document_value_policy(rule.policy_id)
    except FieldBindingError as exc:
        raise LegacyFieldBindingStoreV1Error(
            f"v1 규칙의 문서 값 정책을 해석할 수 없다: {rule.policy_id!r}"
        ) from exc
    if rule.binding_kind == SOURCE and rule.value_type not in _V1_VALUE_TYPES:
        raise LegacyFieldBindingStoreV1Error(
            f"v1 SOURCE 규칙의 미지원 value_type: {rule.value_type!r}"
        )
    constant: ExactText | None = None
    if rule.binding_kind == CONSTANT:
        raw = rule.canonical_constant_value
        if not isinstance(raw, Mapping) or raw.get("kind") != "EXACT_TEXT":
            kind = raw.get("kind") if isinstance(raw, Mapping) else None
            raise LegacyFieldBindingStoreV1Error(
                f"타입 있는 v1 고정값은 자동으로 옮길 수 없다(field {rule.field_id!r}, kind {kind!r})"
            )
        text = raw.get("text")
        if not isinstance(text, str):
            raise LegacyFieldBindingStoreV1Error("v1 EXACT_TEXT 고정값이 문자열이 아니다")
        constant = ExactText(text)
    try:
        return FieldBindingRule(
            field_id=rule.field_id,
            binding_kind=rule.binding_kind,
            document_content_value_policy=policy,
            source_key=rule.source_key,
            format_code=rule.format_code,
            canonical_constant_value=constant,
        )
    except FieldBindingInputIntegrityError as exc:
        raise LegacyFieldBindingStoreV1Error("v1 규칙이 현재 불변식을 만족하지 않는다") from exc


def _migrate_revision(data: Any) -> tuple[str, FieldBindingRevision]:
    """v1 revision 하나를 3중 대조 후 v2 revision 으로 옮긴다. 반환은 (old_id, v2 revision)."""
    if not isinstance(data, Mapping):
        raise LegacyFieldBindingStoreV1Error("v1 revision 표현이 malformed")
    raw_rules = data.get("binding_rules")
    raw_keys = data.get("source_schema_keys")
    if not isinstance(raw_rules, list) or not isinstance(raw_keys, list):
        raise LegacyFieldBindingStoreV1Error("v1 revision 규칙·스키마 표현이 malformed")
    if data.get("field_binding_semantic_contract_id") != FIELD_BINDING_SEMANTIC_VERSION_V1:
        raise LegacyFieldBindingStoreV1Error(
            "v1 revision 의 field-binding contract 가 v1 이 아니다: "
            f"{data.get('field_binding_semantic_contract_id')!r}"
        )
    if data.get("source_schema_contract_id") != SOURCE_SCHEMA_VERSION_V1:
        raise LegacyFieldBindingStoreV1Error(
            "v1 revision 의 source-schema contract 가 v1 이 아니다: "
            f"{data.get('source_schema_contract_id')!r}"
        )
    work_authority_id = _require_text(data, "work_authority_id")
    application_id = _require_text(data, "base_template_application_id")
    raw_record_contract_id = _require_text(data, "raw_record_contract_id")
    old_revision_id = _require_text(data, "field_binding_authority_revision")
    captured_at = _require_text(data, "captured_at")

    v1_rules = tuple(_decode_rule_v1(r) for r in raw_rules)
    v1_keys = tuple(raw_keys)

    # (1)·(2) 저장 digest 를 v1 프레이밍으로 재계산해 대조한다(claim 신뢰 금지).
    if digest_binding_rules_v1(v1_rules) != data.get("canonical_binding_digest"):
        raise LegacyFieldBindingStoreV1Error(
            f"v1 revision {old_revision_id} 의 규칙 digest 재계산 불일치"
        )
    if digest_source_schema_v1(v1_keys) != data.get("canonical_source_schema_digest"):
        raise LegacyFieldBindingStoreV1Error(
            f"v1 revision {old_revision_id} 의 소스 스키마 digest 재계산 불일치"
        )
    # (3) revision identity 를 v1 content-address 로 재유도해 대조한다.
    expected_v1_id = field_binding_authority_revision_identity(
        work_authority_id=work_authority_id,
        base_template_application_id=application_id,
        field_binding_semantic_contract_id=FIELD_BINDING_SEMANTIC_VERSION_V1,
        source_schema_contract_id=SOURCE_SCHEMA_VERSION_V1,
        raw_record_contract_id=raw_record_contract_id,
        canonical_binding_digest=str(data.get("canonical_binding_digest")),
        canonical_source_schema_digest=str(data.get("canonical_source_schema_digest")),
    )
    if expected_v1_id != old_revision_id:
        raise LegacyFieldBindingStoreV1Error(
            f"v1 revision {old_revision_id} 의 identity 가 content-address 와 불일치"
        )

    # value_type accept-and-drop → v2 규칙·digest·identity 재유도.
    v2_rules = tuple(_v2_rule(rule) for rule in v1_rules)
    binding_digest = digest_binding_rules(v2_rules)
    schema_digest = digest_source_schema(v1_keys)
    new_revision_id = field_binding_authority_revision_identity(
        work_authority_id=work_authority_id,
        base_template_application_id=application_id,
        field_binding_semantic_contract_id=FIELD_BINDING_SEMANTIC_VERSION,
        source_schema_contract_id=SOURCE_SCHEMA_VERSION,
        raw_record_contract_id=raw_record_contract_id,
        canonical_binding_digest=binding_digest,
        canonical_source_schema_digest=schema_digest,
    )
    try:
        revision = FieldBindingRevision(
            work_authority_id=work_authority_id,
            base_template_application_id=application_id,
            field_binding_authority_revision=new_revision_id,
            field_binding_semantic_contract_id=FIELD_BINDING_SEMANTIC_VERSION,
            source_schema_contract_id=SOURCE_SCHEMA_VERSION,
            raw_record_contract_id=raw_record_contract_id,
            binding_rules=v2_rules,
            source_schema_keys=v1_keys,
            canonical_binding_digest=binding_digest,
            canonical_source_schema_digest=schema_digest,
            captured_at=captured_at,
        )
    except FieldBindingError as exc:
        raise LegacyFieldBindingStoreV1Error("v1 revision 을 v2 로 봉인할 수 없다") from exc
    return old_revision_id, revision


def _remap(revision_id: Any, mapping: Mapping[str, str], what: str) -> str:
    if not isinstance(revision_id, str):
        raise LegacyFieldBindingStoreV1Error(f"{what} 의 revision 참조가 malformed")
    new_id = mapping.get(revision_id)
    if new_id is None:
        raise LegacyFieldBindingStoreV1Error(
            f"{what} 가 v1 aggregate 에 없는 revision 을 가리킨다: {revision_id}"
        )
    return new_id


def is_legacy_v1(content: Mapping[str, Any]) -> bool:
    """저장 content 가 v1 store schema 인가(``schema_version`` 필드 단독 판별)."""
    return content.get("schema_version") == STORE_SCHEMA_VERSION_V1


def migrate_stored_v1(content: Mapping[str, Any]) -> StoredWorkFieldBinding:
    """v1 aggregate content → v2 :class:`StoredWorkFieldBinding`(메모리 전용, 파일 무수정).

    실패는 전부 :class:`StoredFieldBindingError` 하위라 호출자(store ``load()``)가 기존 손상
    파일과 **같은 거동**으로 시끄럽게 닫는다.
    """
    if not isinstance(content, Mapping):  # pragma: no cover - 호출자가 dict 만 넘긴다
        raise LegacyFieldBindingStoreV1Error("v1 aggregate 표현이 malformed")
    if not is_legacy_v1(content):
        raise LegacyFieldBindingStoreV1Error(
            f"v1 aggregate 가 아니다: {content.get('schema_version')!r}"
        )
    for key in (
        "current_by_application",
        "immutable_binding_revisions",
        "first_seen_command_ledger",
        "migration_drafts",
        "application_review_drafts",
    ):
        if not isinstance(content.get(key), list):
            raise LegacyFieldBindingStoreV1Error(f"v1 aggregate 의 {key} 는 리스트여야 한다")

    id_map: dict[str, str] = {}
    revisions: list[FieldBindingRevision] = []
    seen_new: set[str] = set()
    for raw in content["immutable_binding_revisions"]:
        old_id, revision = _migrate_revision(raw)
        if old_id in id_map:
            raise LegacyFieldBindingStoreV1Error(f"v1 revision identity 중복: {old_id}")
        new_id = revision.field_binding_authority_revision
        id_map[old_id] = new_id
        # value_type 만 달랐던 두 v1 revision 은 같은 v2 content-address 로 접힌다 — 최초 것만 남긴다.
        if new_id in seen_new:
            continue
        seen_new.add(new_id)
        revisions.append(revision)

    pointers = tuple(
        ApplicationRevisionPointer(
            application_id=_pointer_application_id(raw),
            revision_id=_remap(
                raw.get("revision_id") if isinstance(raw, Mapping) else None,
                id_map,
                "current pointer",
            ),
        )
        for raw in content["current_by_application"]
    )
    return StoredWorkFieldBinding(
        schema_version=STORE_SCHEMA_VERSION,
        aggregate_version=content.get("aggregate_version"),
        workspace_instance_id=content.get("workspace_instance_id"),
        work_authority_id=content.get("work_authority_id"),
        current_by_application=pointers,
        immutable_binding_revisions=tuple(revisions),
        migration_drafts=tuple(
            _migrate_draft(raw, id_map) for raw in content["migration_drafts"]
        ),
        application_review_drafts=tuple(
            _migrate_draft(raw, id_map) for raw in content["application_review_drafts"]
        ),
        first_seen_command_ledger=tuple(
            _migrate_ledger(raw, id_map) for raw in content["first_seen_command_ledger"]
        ),
    )


def _pointer_application_id(raw: Any) -> Any:
    if not isinstance(raw, Mapping):
        raise LegacyFieldBindingStoreV1Error("v1 current pointer 표현이 malformed")
    return raw.get("application_id")


def _migrate_draft(raw: Any, id_map: Mapping[str, str]) -> CommittedDraftRecord:
    if not isinstance(raw, Mapping):
        raise LegacyFieldBindingStoreV1Error("v1 draft record 표현이 malformed")
    return CommittedDraftRecord(
        kind=raw.get("kind"),
        request_id=raw.get("request_id"),
        application_id=raw.get("application_id"),
        # basis_fingerprint 는 그때의 basis 를 가리키는 역사 기록이라 재계산하지 않는다.
        basis_fingerprint=raw.get("basis_fingerprint"),
        produced_revision_id=_remap(
            raw.get("produced_revision_id"), id_map, "draft record"
        ),
        recorded_at=raw.get("recorded_at"),
    )


def _migrate_ledger(
    raw: Any, id_map: Mapping[str, str]
) -> FieldBindingIdempotencyRecord:
    if not isinstance(raw, Mapping):
        raise LegacyFieldBindingStoreV1Error("v1 ledger record 표현이 malformed")
    return FieldBindingIdempotencyRecord(
        request_id=raw.get("request_id"),
        fingerprint_schema_version=raw.get("fingerprint_schema_version"),
        # command_fingerprint 는 그 요청이 무엇이었는지의 역사라 v2 로 다시 계산하지 않는다.
        command_fingerprint=raw.get("command_fingerprint"),
        produced_revision_id=_remap(
            raw.get("produced_revision_id"), id_map, "ledger record"
        ),
        outcome_code=raw.get("outcome_code"),
        recorded_at=raw.get("recorded_at"),
    )
