"""``work-field-binding-store-v1`` decode-path 마이그레이션 (값 유형 어휘 퇴역).

값 유형 어휘를 코어에서 물리 제거해도 **이미 디스크에 적힌 v1 aggregate 는 무손실로 계속
읽혀야 한다**. 이 파일이 재는 것: 3중 재계산 대조(규칙 digest·소스 스키마 digest·revision
content-address)·SOURCE value_type accept-and-drop·typed constant 시끄러운 거절·v2 revision id
재유도와 포인터 재사상·다음 commit 의 v2 재봉인, 그리고 회귀 두 축(#877 INACTIVE_ONLY 보존,
Mapping 불변 작업의 거짓 changed 파문 소거).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import hwpxfiller.external.field_binding_store as store_mod
from hwpxfiller.application.field_binding_input import (
    INACTIVE_ONLY,
    CurrentApplicationFieldStructure,
    build_field_binding_input,
    field_binding_authority_revision_identity,
    review_field_binding_for_current_application,
    revision_from_input,
)
from hwpxfiller.application.legacy_field_binding_store_v1 import (
    FIELD_BINDING_SEMANTIC_VERSION_V1,
    SOURCE_SCHEMA_VERSION_V1,
    STORE_SCHEMA_VERSION_V1,
    LegacyFieldBindingStoreV1Error,
    _V1Rule,
    digest_binding_rules_v1,
    digest_source_schema_v1,
    is_legacy_v1,
    migrate_stored_v1,
)
from hwpxfiller.application.stored_field_binding import STORE_SCHEMA_VERSION
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    SOURCE,
    FieldBindingRule,
)
from hwpxfiller.external.field_binding_store import (
    FieldBindingIntegrityError,
    FieldBindingSchemaUnsupported,
    WorkFieldBindingStore,
)

WS = "ws-1"
WORK = "work-1"
APP = "A17"
RAW = "raw-record/v1"
NOW = "2026-01-01T00:00:00+09:00"
POLICY_ID = DOCUMENT_CONTENT_VALUE_POLICY_V1.policy_id


# ─── v1 파일 조립(동결 프레이밍으로 digest·identity 를 실제로 계산한다) ─────────────────
def _v1_source(field_id: str, key: str, value_type: str = "EXACT_TEXT") -> _V1Rule:
    return _V1Rule(field_id, SOURCE, POLICY_ID, key, value_type, None, None)


def _v1_constant(field_id: str, value: dict) -> _V1Rule:
    return _V1Rule(field_id, CONSTANT, POLICY_ID, None, None, None, value)


def _encode_v1_rule(rule: _V1Rule) -> dict:
    return {
        "field_id": rule.field_id,
        "binding_kind": rule.binding_kind,
        "policy_id": rule.policy_id,
        "source_key": rule.source_key,
        "value_type": rule.value_type,
        "format_code": rule.format_code,
        "canonical_constant_value": rule.canonical_constant_value,
    }


def _v1_revision(rules: tuple[_V1Rule, ...], keys: tuple[str, ...], *, app: str = APP) -> dict:
    binding_digest = digest_binding_rules_v1(rules)
    schema_digest = digest_source_schema_v1(keys)
    revision_id = field_binding_authority_revision_identity(
        work_authority_id=WORK,
        base_template_application_id=app,
        field_binding_semantic_contract_id=FIELD_BINDING_SEMANTIC_VERSION_V1,
        source_schema_contract_id=SOURCE_SCHEMA_VERSION_V1,
        raw_record_contract_id=RAW,
        canonical_binding_digest=binding_digest,
        canonical_source_schema_digest=schema_digest,
    )
    return {
        "work_authority_id": WORK,
        "base_template_application_id": app,
        "field_binding_authority_revision": revision_id,
        "field_binding_semantic_contract_id": FIELD_BINDING_SEMANTIC_VERSION_V1,
        "source_schema_contract_id": SOURCE_SCHEMA_VERSION_V1,
        "raw_record_contract_id": RAW,
        "binding_rules": [_encode_v1_rule(r) for r in rules],
        "source_schema_keys": list(keys),
        "canonical_binding_digest": binding_digest,
        "canonical_source_schema_digest": schema_digest,
        "captured_at": NOW,
    }


def _v1_content(revisions: list[dict]) -> dict:
    last = revisions[-1]
    return {
        "schema_version": STORE_SCHEMA_VERSION_V1,
        "aggregate_version": len(revisions),
        "workspace_instance_id": WS,
        "work_authority_id": WORK,
        "current_by_application": [
            {
                "application_id": last["base_template_application_id"],
                "revision_id": last["field_binding_authority_revision"],
            }
        ],
        "immutable_binding_revisions": revisions,
        "migration_drafts": [
            {
                "kind": "MIGRATION",
                "request_id": f"req-{index}",
                "application_id": rev["base_template_application_id"],
                "basis_fingerprint": f"sha256:basis-{index}",
                "produced_revision_id": rev["field_binding_authority_revision"],
                "recorded_at": NOW,
            }
            for index, rev in enumerate(revisions)
        ],
        "application_review_drafts": [],
        "first_seen_command_ledger": [
            {
                "request_id": f"req-{index}",
                "fingerprint_schema_version": "field-binding-commit-fingerprint/v1",
                "command_fingerprint": f"sha256:cmd-{index}",
                "produced_revision_id": rev["field_binding_authority_revision"],
                "outcome_code": "FIELD_BINDING_REVISION_COMMITTED",
                "recorded_at": NOW,
            }
            for index, rev in enumerate(revisions)
        ],
    }


def _write_v1(tmp_path: Path, content: dict) -> WorkFieldBindingStore:
    store = WorkFieldBindingStore(tmp_path)
    store_mod._write_enveloped(tmp_path / f"{WORK}.json", content)
    return store


def _expected_v2_revision(rules: tuple[FieldBindingRule, ...], keys: tuple[str, ...]):
    return revision_from_input(
        build_field_binding_input(
            workspace_instance_id=WS,
            work_authority_id=WORK,
            base_template_application_id=APP,
            binding_rules=rules,
            source_schema_keys=keys,
            raw_record_contract_id=RAW,
            captured_at=NOW,
        )
    )


# ─── 1. 정상 마이그레이션 ───────────────────────────────────────────────────────────
def test_v1_aggregate_loads_as_a_migrated_v2_aggregate(tmp_path: Path) -> None:
    keys = ("금액", "이름")
    rules = (_v1_source("f_name", "이름"), _v1_source("f_amount", "금액", "DECIMAL"))
    content = _v1_content([_v1_revision(rules, keys)])
    old_id = content["immutable_binding_revisions"][0]["field_binding_authority_revision"]
    store = _write_v1(tmp_path, content)

    stored = store.load(WORK)

    assert is_legacy_v1(content) is True
    assert stored.schema_version == STORE_SCHEMA_VERSION == "work-field-binding-store-v2"
    assert stored.aggregate_version == 1
    (revision,) = stored.immutable_binding_revisions
    # value_type 은 accept-and-drop, 나머지 슬롯은 무손실.
    assert {(r.field_id, r.binding_kind, r.source_key) for r in revision.binding_rules} == {
        ("f_name", SOURCE, "이름"),
        ("f_amount", SOURCE, "금액"),
    }
    assert all(not hasattr(r, "value_type") for r in revision.binding_rules)
    assert revision.field_binding_semantic_contract_id == "field-binding/v2"
    assert revision.source_schema_contract_id == "source-schema/v2"
    assert revision.source_schema_keys == keys
    # id 는 v2 content-address 로 재유도되고, 포인터가 그것을 가리킨다.
    expected = _expected_v2_revision(
        (
            FieldBindingRule("f_name", SOURCE, DOCUMENT_CONTENT_VALUE_POLICY_V1, source_key="이름"),
            FieldBindingRule("f_amount", SOURCE, DOCUMENT_CONTENT_VALUE_POLICY_V1, source_key="금액"),
        ),
        keys,
    )
    new_id = revision.field_binding_authority_revision
    assert new_id == expected.field_binding_authority_revision != old_id
    assert stored.current_by_application[0].revision_id == new_id
    # 역사 기록(fingerprint)은 그대로, revision 참조만 재사상된다.
    assert stored.first_seen_command_ledger[0].command_fingerprint == "sha256:cmd-0"
    assert stored.first_seen_command_ledger[0].produced_revision_id == new_id
    assert stored.migration_drafts[0].basis_fingerprint == "sha256:basis-0"
    assert stored.migration_drafts[0].produced_revision_id == new_id
    # 파일은 읽기 경로에서 다시 쓰이지 않는다.
    on_disk = json.loads((tmp_path / f"{WORK}.json").read_text("utf-8"))["content"]
    assert on_disk["schema_version"] == STORE_SCHEMA_VERSION_V1


def test_constant_rule_survives_as_flattened_text(tmp_path: Path) -> None:
    rules = (_v1_constant("f_kind", {"kind": "EXACT_TEXT", "text": "공고"}),)
    store = _write_v1(tmp_path, _v1_content([_v1_revision(rules, ("이름",))]))

    (revision,) = store.load(WORK).immutable_binding_revisions

    (rule,) = revision.binding_rules
    assert rule.binding_kind == CONSTANT
    assert rule.canonical_constant_value.text == "공고"


# ─── 2. 3중 대조 — 훼손은 시끄럽게 닫는다 ───────────────────────────────────────────
@pytest.mark.parametrize(
    "field",
    ["canonical_binding_digest", "canonical_source_schema_digest", "field_binding_authority_revision"],
)
def test_tampered_v1_revision_is_refused(tmp_path: Path, field: str) -> None:
    """저장 digest·identity 를 v1 프레이밍으로 재계산해 대조한다 — claim 을 믿지 않는다."""
    revision = _v1_revision((_v1_source("f_name", "이름"),), ("이름",))
    revision[field] = "sha256:tampered"
    content = _v1_content([revision])
    # 포인터도 함께 옮겨 "없는 revision" 이 아니라 "digest 불일치" 로 닫히게 한다.
    content["current_by_application"][0]["revision_id"] = revision[
        "field_binding_authority_revision"
    ]
    store = _write_v1(tmp_path, content)

    with pytest.raises(FieldBindingIntegrityError):
        store.load(WORK)


def test_dangling_pointer_in_v1_is_refused(tmp_path: Path) -> None:
    content = _v1_content([_v1_revision((_v1_source("f_name", "이름"),), ("이름",))])
    content["current_by_application"][0]["revision_id"] = "fbrev:sha256:ghost"
    store = _write_v1(tmp_path, content)

    with pytest.raises(FieldBindingIntegrityError):
        store.load(WORK)


def test_unknown_store_schema_is_still_unsupported(tmp_path: Path) -> None:
    content = _v1_content([_v1_revision((_v1_source("f_name", "이름"),), ("이름",))])
    store = _write_v1(tmp_path, {**content, "schema_version": "work-field-binding-store-v0"})

    with pytest.raises(FieldBindingSchemaUnsupported):
        store.load(WORK)


# ─── 3. typed constant — 조용한 의미 변환 대신 거절 ─────────────────────────────────
@pytest.mark.parametrize(
    "value",
    [
        {"kind": "DECIMAL", "literal": "1.50"},
        {"kind": "DATE", "iso": "2026-01-02"},
        {"kind": "DATETIME", "iso": "2026-01-02T03:04:05+09:00"},
        {"kind": "BOOLEAN", "value": True},
    ],
)
def test_typed_v1_constant_is_refused(tmp_path: Path, value: dict) -> None:
    """생산 경로가 없어 손편집으로만 생기는 값이다 — 텍스트로 조용히 접지 않는다."""
    store = _write_v1(
        tmp_path, _v1_content([_v1_revision((_v1_constant("f_kind", value),), ("이름",))])
    )

    with pytest.raises(FieldBindingIntegrityError):
        store.load(WORK)


def test_migrate_raises_the_store_error_family_directly() -> None:
    """store 가 catch 를 늘리지 않아도 되게, 실패는 전부 StoredFieldBindingError 하위다."""
    with pytest.raises(LegacyFieldBindingStoreV1Error):
        migrate_stored_v1({"schema_version": STORE_SCHEMA_VERSION})
    with pytest.raises(LegacyFieldBindingStoreV1Error):
        migrate_stored_v1({"schema_version": STORE_SCHEMA_VERSION_V1})


# ─── 4. 다음 commit 이 v2 로 재봉인한다 ─────────────────────────────────────────────
def test_next_commit_reseals_the_file_as_v2(tmp_path: Path) -> None:
    store = _write_v1(
        tmp_path, _v1_content([_v1_revision((_v1_source("f_name", "이름"),), ("이름",))])
    )
    migrated = store.load(WORK)

    store.update(
        WORK,
        migrated.aggregate_version,
        lambda cur: replace(cur, aggregate_version=cur.aggregate_version + 1),
    )

    on_disk = json.loads((tmp_path / f"{WORK}.json").read_text("utf-8"))["content"]
    assert on_disk["schema_version"] == STORE_SCHEMA_VERSION
    rule = on_disk["immutable_binding_revisions"][0]["binding_rules"][0]
    assert "value_type" not in rule
    assert rule["canonical_constant_text"] is None
    # 재봉인 뒤에는 마이그레이션 경로를 타지 않고 그대로 읽힌다.
    reread = store.load(WORK)
    assert reread.immutable_binding_revisions == migrated.immutable_binding_revisions


# ─── 5. #877 회귀 — 비활성 규칙은 마이그레이션을 살아서 건넌다 ──────────────────────
def test_inactive_only_rules_survive_the_migration(tmp_path: Path) -> None:
    keys = ("금액", "이름")
    rules = (_v1_source("f_name", "이름"), _v1_source("f_amount", "금액", "DECIMAL"))
    store = _write_v1(tmp_path, _v1_content([_v1_revision(rules, keys)]))

    (revision,) = store.load(WORK).immutable_binding_revisions
    review = review_field_binding_for_current_application(
        revision,
        CurrentApplicationFieldStructure("A18", ("f_name",), ("f_amount",), keys),
    )

    assert review.inactive_only_field_ids() == ("f_amount",)
    assert {c.category for c in review.classifications} >= {INACTIVE_ONLY}
    assert {r.field_id for r in revision.binding_rules} == {"f_name", "f_amount"}


# ─── 6. 거짓 changed 파문 소거 — 같은 Mapping 은 같은 v2 revision 이다 ──────────────
def test_unchanged_mapping_lands_on_the_same_v2_revision(tmp_path: Path) -> None:
    """업그레이드 후 첫 commit 이 새 판본을 만들지 않는다(revision dedup → changed=False)."""
    keys = ("이름",)
    store = _write_v1(tmp_path, _v1_content([_v1_revision((_v1_source("f_name", "이름"),), keys)]))
    prior = store.load(WORK).immutable_binding_revisions[0]

    rebuilt = _expected_v2_revision(
        (FieldBindingRule("f_name", SOURCE, DOCUMENT_CONTENT_VALUE_POLICY_V1, source_key="이름"),),
        keys,
    )

    # BindingCommitProjection 의 changed 는 이 두 id 비교다 — 같으면 파문이 없다.
    assert (
        prior.field_binding_authority_revision
        == rebuilt.field_binding_authority_revision
    )


# ─── 7. value_type 만 달랐던 두 판본은 하나로 접힌다 ────────────────────────────────
def test_revisions_differing_only_in_value_type_fold_into_one(tmp_path: Path) -> None:
    keys = ("금액",)
    first = _v1_revision((_v1_source("f_amount", "금액", "EXACT_TEXT"),), keys)
    second = _v1_revision((_v1_source("f_amount", "금액", "DECIMAL"),), keys)
    assert (
        first["field_binding_authority_revision"]
        != second["field_binding_authority_revision"]
    )
    store = _write_v1(tmp_path, _v1_content([first, second]))

    stored = store.load(WORK)

    # 하나로 접히되 최초 revision(그 captured_at·provenance)이 남는다.
    (revision,) = stored.immutable_binding_revisions
    new_id = revision.field_binding_authority_revision
    assert stored.current_by_application[0].revision_id == new_id
    # 두 요청의 원장·draft 는 둘 다 살아남아 같은 v2 판본을 가리킨다(요청 역사 보존).
    assert [r.request_id for r in stored.first_seen_command_ledger] == ["req-0", "req-1"]
    assert {r.produced_revision_id for r in stored.first_seen_command_ledger} == {new_id}
    assert {d.produced_revision_id for d in stored.migration_drafts} == {new_id}


def test_duplicate_v1_revision_identity_is_refused(tmp_path: Path) -> None:
    revision = _v1_revision((_v1_source("f_name", "이름"),), ("이름",))
    store = _write_v1(tmp_path, _v1_content([revision, dict(revision)]))

    with pytest.raises(FieldBindingIntegrityError):
        store.load(WORK)


# ─── malformed v1 — 모든 잎이 fail-closed 다(조용한 기본값 0) ──────────────────────
def _valid_v1_content() -> dict:
    return _v1_content([_v1_revision((_v1_source("f_name", "이름"),), ("이름",))])


@pytest.mark.parametrize(
    "key",
    [
        "current_by_application",
        "immutable_binding_revisions",
        "first_seen_command_ledger",
        "migration_drafts",
        "application_review_drafts",
    ],
)
def test_v1_collections_must_be_lists(key: str) -> None:
    content = _valid_v1_content()
    content[key] = "not-a-list"
    with pytest.raises(LegacyFieldBindingStoreV1Error):
        migrate_stored_v1(content)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.__setitem__("current_by_application", ["not-a-mapping"]),
        lambda c: c.__setitem__("migration_drafts", ["not-a-mapping"]),
        lambda c: c.__setitem__("first_seen_command_ledger", ["not-a-mapping"]),
        lambda c: c.__setitem__("immutable_binding_revisions", ["not-a-mapping"]),
        lambda c: c["immutable_binding_revisions"][0].__setitem__("binding_rules", "x"),
        lambda c: c["immutable_binding_revisions"][0].__setitem__("captured_at", ""),
        lambda c: c["immutable_binding_revisions"][0].__setitem__(
            "field_binding_semantic_contract_id", "field-binding/v2"
        ),
        lambda c: c["immutable_binding_revisions"][0].__setitem__(
            "source_schema_contract_id", "source-schema/v2"
        ),
        lambda c: c["immutable_binding_revisions"][0].__setitem__(
            "source_schema_keys", ["이름", "이름"]
        ),
        lambda c: c["immutable_binding_revisions"][0].__setitem__(
            "source_schema_keys", [7]
        ),
        lambda c: c["immutable_binding_revisions"][0]["binding_rules"].__setitem__(
            0, "not-a-mapping"
        ),
        lambda c: c["immutable_binding_revisions"][0]["binding_rules"][0].__setitem__(
            "field_id", ""
        ),
        lambda c: c["immutable_binding_revisions"][0]["binding_rules"][0].__setitem__(
            "value_type", 7
        ),
        lambda c: c["immutable_binding_revisions"][0]["binding_rules"][0].__setitem__(
            "value_type", "MONEY"
        ),
        lambda c: c["immutable_binding_revisions"][0]["binding_rules"][0].__setitem__(
            "policy_id", "document-content-value/v9"
        ),
        lambda c: c["immutable_binding_revisions"][0]["binding_rules"][0].__setitem__(
            "binding_kind", "MIXED"
        ),
        lambda c: c["immutable_binding_revisions"][0]["binding_rules"][0].__setitem__(
            "canonical_constant_value", "not-a-mapping"
        ),
        lambda c: c["immutable_binding_revisions"][0]["binding_rules"][0].__setitem__(
            "canonical_constant_value", {"kind": "MONEY", "literal": "1"}
        ),
        lambda c: c["immutable_binding_revisions"][0]["binding_rules"][0].__setitem__(
            "canonical_constant_value", {"kind": "BOOLEAN", "value": "yes"}
        ),
        lambda c: c["immutable_binding_revisions"][0]["binding_rules"][0].__setitem__(
            "canonical_constant_value", {"kind": "DECIMAL", "literal": 7}
        ),
        lambda c: c["immutable_binding_revisions"][0]["binding_rules"][0].__setitem__(
            "canonical_constant_value", {"kind": "EXACT_TEXT", "text": 7}
        ),
        lambda c: c["migration_drafts"][0].__setitem__("produced_revision_id", None),
        lambda c: c["first_seen_command_ledger"][0].__setitem__(
            "produced_revision_id", "fbrev:sha256:ghost"
        ),
    ],
)
def test_malformed_v1_leaves_are_refused(mutate) -> None:
    content = _valid_v1_content()
    mutate(content)
    with pytest.raises(LegacyFieldBindingStoreV1Error):
        migrate_stored_v1(content)


def test_two_rules_on_one_field_in_v1_is_refused() -> None:
    rule = _v1_source("f_name", "이름")
    with pytest.raises(LegacyFieldBindingStoreV1Error):
        digest_binding_rules_v1((rule, rule))


@pytest.mark.parametrize(
    "rule",
    [
        # 3중 대조는 통과하지만(자체 정합) v1 어휘 밖인 손편집 규칙들.
        _V1Rule("f", SOURCE, POLICY_ID, "이름", "MONEY", None, None),
        _V1Rule("f", SOURCE, "document-content-value/v9", "이름", "EXACT_TEXT", None, None),
        _V1Rule("f", "MIXED", POLICY_ID, "이름", "EXACT_TEXT", None, None),
        _V1Rule(
            "f", CONSTANT, POLICY_ID, "이름", None, None, {"kind": "EXACT_TEXT", "text": "x"}
        ),
    ],
)
def test_self_consistent_but_out_of_vocabulary_v1_rules_are_refused(rule: _V1Rule) -> None:
    """digest 를 다시 맞춘 손편집도 v2 어휘·불변식으로 한 번 더 걸린다(fail-closed)."""
    content = _v1_content([_v1_revision((rule,), ("이름",))])
    with pytest.raises(LegacyFieldBindingStoreV1Error):
        migrate_stored_v1(content)
