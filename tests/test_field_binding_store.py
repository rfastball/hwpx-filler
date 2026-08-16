"""S5-01 Field Binding 저장 aggregate codec + file-atomic store + fence-first commit (#697)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace

import pytest

from hwpxfiller.application.field_binding_input import (
    LegacyFieldBindingEntry,
    build_field_binding_input,
    prepare_legacy_field_binding_migration,
    review_field_binding_for_current_application,
    revision_from_input,
    CurrentApplicationFieldStructure,
)
from hwpxfiller.application.stored_field_binding import (
    APPLICATION_REVIEW,
    MIGRATION,
    ApplicationRevisionPointer,
    CommittedDraftRecord,
    FieldBindingIdempotencyRecord,
    StoredFieldBindingError,
    commit_revision,
    current_revision_id,
    decode_stored,
    empty_stored,
    encode_stored,
)
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    EXACT_TEXT,
    INTENTIONAL_BLANK,
    SOURCE,
    CanonicalBoolean,
    CanonicalDate,
    CanonicalDateTime,
    CanonicalDecimal,
    ExactText,
    FieldBindingRule,
)
import hwpxfiller.application.stored_field_binding as sfb
import hwpxfiller.external.field_binding_store as store_mod
from hwpxfiller.external.field_binding_store import (
    FieldBindingAggregateConflict,
    FieldBindingAggregateExists,
    FieldBindingAggregateNotFound,
    FieldBindingIntegrityError,
    FieldBindingSchemaUnsupported,
    FieldBindingWorkspaceMismatch,
    WorkFieldBindingStore,
    WorkFieldBindingStoreError,
    commit_field_binding_for_current_application,
    commit_field_binding_migration,
    load_current_revision,
)
from hwpxfiller.application.stored_field_binding import (
    FieldBindingIdempotencyKeyReused,
)

POLICY = DOCUMENT_CONTENT_VALUE_POLICY_V1
WS = "ws-1"
WORK = "work-1"
NOW = "2026-01-01T00:00:00+09:00"


def _rule(field_id: str, key: str = "name") -> FieldBindingRule:
    return FieldBindingRule(field_id, SOURCE, POLICY, source_key=key, value_type=EXACT_TEXT)


def _input(*, base="A17", rules=None, keys=("name",), work=WORK, ws=WS):
    return build_field_binding_input(
        workspace_instance_id=ws,
        work_authority_id=work,
        base_template_application_id=base,
        binding_rules=rules if rules is not None else [_rule("f1")],
        source_schema_keys=list(keys),
        raw_record_contract_id="raw-record/v1",
        captured_at=NOW,
    )


class _Basis:
    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint

    def current_legacy_basis_fingerprint(self, work_authority_id: str) -> str:
        return self.fingerprint


class _StructurePort:
    def __init__(self, structure: CurrentApplicationFieldStructure) -> None:
        self.structure = structure

    def current_application_field_structure(self, work_authority_id: str):
        return self.structure


# ─── codec round-trip (all value variants) ───────────────────────────────────────
def test_stored_codec_roundtrip_all_value_kinds() -> None:
    rules = [
        FieldBindingRule("t", SOURCE, POLICY, source_key="k", value_type=EXACT_TEXT),
        FieldBindingRule("c1", CONSTANT, POLICY, canonical_constant_value=ExactText("x")),
        FieldBindingRule("c2", CONSTANT, POLICY, canonical_constant_value=CanonicalDecimal("1.5")),
        FieldBindingRule("c3", CONSTANT, POLICY, canonical_constant_value=CanonicalDate("2026-01-02")),
        FieldBindingRule("c4", CONSTANT, POLICY,
                         canonical_constant_value=CanonicalDateTime("2026-01-02T03:04:05+09:00")),
        FieldBindingRule("c5", CONSTANT, POLICY, canonical_constant_value=CanonicalBoolean(True)),
        FieldBindingRule("b", INTENTIONAL_BLANK, POLICY),
    ]
    rev = revision_from_input(_input(rules=rules, keys=("k", "other")))
    stored = commit_revision(
        empty_stored(WS, WORK), rev,
        CommittedDraftRecord(MIGRATION, "r1", "A17", "sha256:b", rev.field_binding_authority_revision, NOW),
        FieldBindingIdempotencyRecord("r1", "field-binding-commit-fingerprint/v1", "sha256:f",
                                      rev.field_binding_authority_revision, "C", NOW),
    )
    back = decode_stored(json.loads(json.dumps(encode_stored(stored))))
    assert back == stored


def test_leaf_decoders_fail_closed() -> None:
    for bad in ("x", {"kind": "ZZZ"}, {"kind": "BOOLEAN", "value": "no"}):
        with pytest.raises(StoredFieldBindingError):
            sfb._decode_value(bad)
    for fn in (sfb._decode_rule, sfb._decode_revision, sfb._decode_pointer,
               sfb._decode_draft, sfb._decode_ledger):
        with pytest.raises(StoredFieldBindingError):
            fn("not-a-dict")
    with pytest.raises(StoredFieldBindingError):
        sfb._decode_revision({"binding_rules": "x", "source_schema_keys": []})
    with pytest.raises(StoredFieldBindingError):
        sfb._decode_draft_list("x", "migration_drafts")
    # revision 불변식 위반(digest tamper) → StoredFieldBindingError 로 정규화.
    rev = revision_from_input(_input())
    enc = sfb._encode_revision(rev)
    with pytest.raises(StoredFieldBindingError):
        sfb._decode_revision({**enc, "canonical_binding_digest": "sha256:bad"})


def test_lookups_return_none_when_absent() -> None:
    stored = empty_stored(WS, WORK)
    assert sfb.find_request(stored, "absent") is None
    assert sfb.revision_by_id(stored, "absent") is None
    assert current_revision_id(stored, "absent") is None


def test_idempotency_record_and_version_guards() -> None:
    with pytest.raises(StoredFieldBindingError):
        FieldBindingIdempotencyRecord("", "s", "f", "r", "o", NOW)
    good = empty_stored(WS, WORK)
    with pytest.raises(StoredFieldBindingError):
        replace(good, aggregate_version="x")
    with pytest.raises(StoredFieldBindingError):
        replace(good, aggregate_version=0)
    rev = revision_from_input(_input())
    with pytest.raises(StoredFieldBindingError):  # revision 이 아닌 항목
        replace(good, immutable_binding_revisions=("nope",))
    seeded = commit_revision(
        good, rev,
        CommittedDraftRecord(MIGRATION, "r", "A17", "b", rev.field_binding_authority_revision, NOW),
        FieldBindingIdempotencyRecord("r", "s", "f", rev.field_binding_authority_revision, "C", NOW),
    )
    # 같은 Application 에 pointer 둘 → 거절.
    dup = seeded.current_by_application[0]
    with pytest.raises(StoredFieldBindingError):
        replace(seeded, current_by_application=(dup, dup))
    # 같은 request_id ledger record 둘 → 거절.
    led = seeded.first_seen_command_ledger[0]
    with pytest.raises(StoredFieldBindingError):
        replace(seeded, first_seen_command_ledger=(led, led))


def test_aggregate_invariants() -> None:
    rev = revision_from_input(_input())
    rid = rev.field_binding_authority_revision
    good = commit_revision(
        empty_stored(WS, WORK), rev,
        CommittedDraftRecord(MIGRATION, "r1", "A17", "sha256:b", rid, NOW),
        FieldBindingIdempotencyRecord("r1", "s", "f", rid, "C", NOW),
    )
    # current pointer 가 없는 revision 을 가리키면 거절.
    with pytest.raises(StoredFieldBindingError):
        replace(good, current_by_application=(ApplicationRevisionPointer("A17", "fbrev:sha256:ghost"),))
    # duplicate revision identity 거절.
    with pytest.raises(StoredFieldBindingError):
        replace(good, immutable_binding_revisions=good.immutable_binding_revisions * 2)
    # 잘못된 schema_version 거절.
    with pytest.raises(StoredFieldBindingError):
        replace(good, schema_version="other")
    # draft kind 오류 거절.
    with pytest.raises(StoredFieldBindingError):
        CommittedDraftRecord("NOPE", "r", "A", "b", rid, NOW)


def test_decode_rejects_malformed_and_corrupt_policy() -> None:
    rev = revision_from_input(_input())
    payload = encode_stored(commit_revision(
        empty_stored(WS, WORK), rev,
        CommittedDraftRecord(MIGRATION, "r1", "A17", "b", rev.field_binding_authority_revision, NOW),
        FieldBindingIdempotencyRecord("r1", "s", "f", rev.field_binding_authority_revision, "C", NOW),
    ))
    with pytest.raises(StoredFieldBindingError):
        decode_stored("nope")
    with pytest.raises(StoredFieldBindingError):
        decode_stored({**payload, "immutable_binding_revisions": "x"})
    # 규칙 안의 policy_id 를 미상으로 바꾸면 fail-closed.
    corrupt = json.loads(json.dumps(payload))
    corrupt["immutable_binding_revisions"][0]["binding_rules"][0]["policy_id"] = "unknown/v9"
    with pytest.raises(StoredFieldBindingError):
        decode_stored(corrupt)


# ─── file-atomic store CRUD / CAS ────────────────────────────────────────────────
def _seed(store: WorkFieldBindingStore, rev, req="r1"):
    stored = commit_revision(
        empty_stored(WS, WORK), rev,
        CommittedDraftRecord(MIGRATION, req, rev.base_template_application_id, "b",
                             rev.field_binding_authority_revision, NOW),
        FieldBindingIdempotencyRecord(req, "s", "f", rev.field_binding_authority_revision, "C", NOW),
    )
    store.create(stored)
    return stored


def test_store_create_load_and_guards(tmp_path) -> None:
    store = WorkFieldBindingStore(tmp_path)
    rev = revision_from_input(_input())
    assert not store.exists(WORK)
    with pytest.raises(FieldBindingAggregateNotFound):
        store.load(WORK)
    _seed(store, rev)
    assert store.exists(WORK)
    # restart 복원: 새 인스턴스로 같은 revision 을 되읽는다.
    reloaded = WorkFieldBindingStore(tmp_path).load(WORK)
    assert reloaded.immutable_binding_revisions[0] == rev
    # create-once.
    with pytest.raises(FieldBindingAggregateExists):
        _seed(store, rev, req="r2")
    # version != 1 create 거절.
    with pytest.raises(WorkFieldBindingStoreError):
        store.create(replace(reloaded, aggregate_version=2, work_authority_id="w2"))


def test_store_corruption_fail_closed(tmp_path) -> None:
    store = WorkFieldBindingStore(tmp_path)
    _seed(store, revision_from_input(_input()))
    path = tmp_path / f"{WORK}.json"
    # digest 손상.
    path.write_text(json.dumps({"digest": "sha256:bad", "content": {"x": 1}}), encoding="utf-8")
    with pytest.raises(FieldBindingIntegrityError):
        store.load(WORK)
    # JSON 손상.
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(FieldBindingIntegrityError):
        store.load(WORK)


def test_store_schema_and_wrong_work_guard(tmp_path) -> None:
    store = WorkFieldBindingStore(tmp_path)
    _seed(store, revision_from_input(_input()))
    path = tmp_path / f"{WORK}.json"
    content = json.loads(path.read_text("utf-8"))["content"]
    # 다른 schema_version → envelope digest 재계산해 써야 로드 단계까지 도달.
    bad_schema = {**content, "schema_version": "old"}
    store_mod._write_enveloped(path, bad_schema)
    with pytest.raises(FieldBindingSchemaUnsupported):
        store.load(WORK)
    # 파일이 다른 work aggregate 를 담음.
    store_mod._write_enveloped(path, {**content, "work_authority_id": "someone-else"})
    with pytest.raises(FieldBindingIntegrityError):
        store.load(WORK)


def test_store_invalid_id_and_envelope_shape(tmp_path) -> None:
    store = WorkFieldBindingStore(tmp_path)
    with pytest.raises(WorkFieldBindingStoreError):
        store.load("bad/id")
    path = tmp_path / f"{WORK}.json"
    path.write_text(json.dumps([1, 2]), encoding="utf-8")  # envelope 가 dict 아님
    with pytest.raises(FieldBindingIntegrityError):
        store.load(WORK)
    from hwpxfiller.application.qualification_evidence import content_digest
    path.write_text(json.dumps({"digest": content_digest("s"), "content": "s"}), encoding="utf-8")
    with pytest.raises(FieldBindingIntegrityError):  # content 가 dict 아님
        store.load(WORK)
    # 유효 schema·digest 지만 내부가 malformed → decode 오류를 integrity 로 정규화.
    store_mod._write_enveloped(path, {
        "schema_version": "work-field-binding-store-v1", "aggregate_version": 1,
        "workspace_instance_id": WS, "work_authority_id": WORK,
        "current_by_application": "x", "immutable_binding_revisions": [],
        "first_seen_command_ledger": [],
    })
    with pytest.raises(FieldBindingIntegrityError):
        store.load(WORK)


def test_lock_registry_reuses_same_lock() -> None:
    assert store_mod._lock("dup-key") is store_mod._lock("dup-key")


def test_store_update_cas_and_append_only(tmp_path) -> None:
    store = WorkFieldBindingStore(tmp_path)
    seeded = _seed(store, revision_from_input(_input()))
    with pytest.raises(FieldBindingAggregateConflict):
        store.update(WORK, 99, lambda cur: cur)
    with pytest.raises(WorkFieldBindingStoreError):  # version 을 안 올림
        store.update(WORK, 1, lambda cur: cur)
    # ledger 를 지우면(append-only 위반) 거절.
    def _drop_ledger(cur):
        return replace(cur, aggregate_version=2, first_seen_command_ledger=())
    with pytest.raises(WorkFieldBindingStoreError):
        store.update(WORK, 1, _drop_ledger)
    # immutable revision history 를 지우면(append-only 위반) 거절.
    with pytest.raises(WorkFieldBindingStoreError):
        store.update(WORK, 1, lambda cur: replace(
            cur, aggregate_version=2, immutable_binding_revisions=(), current_by_application=()))
    # work id 변경 거절.
    with pytest.raises(WorkFieldBindingStoreError):
        store.update(WORK, 1, lambda cur: replace(cur, aggregate_version=2, work_authority_id="w2"))
    # workspace identity 변경 거절.
    with pytest.raises(WorkFieldBindingStoreError):
        store.update(WORK, 1, lambda cur: replace(cur, aggregate_version=2, workspace_instance_id="ws-x"))
    assert seeded.aggregate_version == 1


# ─── fence-first migration commit ────────────────────────────────────────────────
def _migration(entries):
    return prepare_legacy_field_binding_migration(
        work_authority_id=WORK, base_template_application_id="A17",
        legacy_entries=entries, captured_at=NOW,
    )


def test_migration_commit_creates_immutable_revision_and_ledger(tmp_path) -> None:
    store = WorkFieldBindingStore(tmp_path)
    draft = _migration([LegacyFieldBindingEntry("f1", "text", "name", "", "")])
    basis = _Basis(draft.legacy_basis_fingerprint)
    resolved = _input(rules=[_rule("f1")], keys=("name",))
    result = commit_field_binding_migration(
        store, basis, workspace_instance_id=WS, work_authority_id=WORK,
        request_id="req-1", draft=draft, resolved_input=resolved, now=NOW,
    )
    assert result.outcome_replayed is False
    stored = store.load(WORK)
    # mutation + ledger 한 aggregate commit.
    assert len(stored.immutable_binding_revisions) == 1
    assert len(stored.first_seen_command_ledger) == 1
    assert len(stored.migration_drafts) == 1
    assert current_revision_id(stored, "A17") == result.revision.field_binding_authority_revision
    assert load_current_revision(store, WORK, "A17") == result.revision
    assert load_current_revision(store, WORK, "A99") is None
    assert load_current_revision(store, "absent", "A17") is None


def test_migration_commit_idempotency_and_reuse(tmp_path) -> None:
    store = WorkFieldBindingStore(tmp_path)
    draft = _migration([LegacyFieldBindingEntry("f1", "text", "name", "", "")])
    basis = _Basis(draft.legacy_basis_fingerprint)
    resolved = _input(rules=[_rule("f1")], keys=("name",))
    args = dict(workspace_instance_id=WS, work_authority_id=WORK, draft=draft, now=NOW)
    first = commit_field_binding_migration(store, basis, request_id="req-1", resolved_input=resolved, **args)
    # same request + same fingerprint → replay(새 ledger 없음).
    replayed = commit_field_binding_migration(store, basis, request_id="req-1", resolved_input=resolved, **args)
    assert replayed.outcome_replayed is True
    assert replayed.revision == first.revision
    assert len(store.load(WORK).first_seen_command_ledger) == 1
    # same request + different fingerprint → reuse 거절.
    other = _input(rules=[_rule("f1", "changed")], keys=("changed",))
    with pytest.raises(FieldBindingIdempotencyKeyReused):
        commit_field_binding_migration(store, basis, request_id="req-1", resolved_input=other, **args)


def test_migration_commit_dedups_revision_but_appends_ledger(tmp_path) -> None:
    # 다른 request 지만 같은 내용 → content-address create-once dedup, ledger 는 추가.
    store = WorkFieldBindingStore(tmp_path)
    draft = _migration([LegacyFieldBindingEntry("f1", "text", "name", "", "")])
    basis = _Basis(draft.legacy_basis_fingerprint)
    resolved = _input(rules=[_rule("f1")], keys=("name",))
    args = dict(workspace_instance_id=WS, work_authority_id=WORK, draft=draft,
                resolved_input=resolved, now=NOW)
    commit_field_binding_migration(store, basis, request_id="req-1", **args)
    commit_field_binding_migration(store, basis, request_id="req-2", **args)
    stored = store.load(WORK)
    assert len(stored.immutable_binding_revisions) == 1  # dedup
    assert len(stored.first_seen_command_ledger) == 2
    assert stored.aggregate_version == 2


def test_migration_commit_workspace_and_route_guards(tmp_path) -> None:
    store = WorkFieldBindingStore(tmp_path)
    draft = _migration([LegacyFieldBindingEntry("f1", "text", "name", "", "")])
    basis = _Basis(draft.legacy_basis_fingerprint)
    # route: resolved_input work/workspace 결속이 route 와 다르면 거절.
    wrong = _input(rules=[_rule("f1")], keys=("name",), work="other")
    with pytest.raises(FieldBindingWorkspaceMismatch):
        commit_field_binding_migration(
            store, basis, workspace_instance_id=WS, work_authority_id=WORK,
            request_id="r", draft=draft, resolved_input=wrong, now=NOW,
        )
    # 저장 aggregate 의 workspace 가 다르면 거절.
    commit_field_binding_migration(
        store, basis, workspace_instance_id=WS, work_authority_id=WORK,
        request_id="r1", draft=draft, resolved_input=_input(rules=[_rule("f1")], keys=("name",)), now=NOW,
    )
    cross = _input(rules=[_rule("f1")], keys=("name",), ws="ws-2")
    with pytest.raises(FieldBindingWorkspaceMismatch):
        commit_field_binding_migration(
            store, basis, workspace_instance_id="ws-2", work_authority_id=WORK,
            request_id="r2", draft=replace(draft, work_authority_id=WORK),
            resolved_input=cross, now=NOW,
        )


def test_commit_acquires_work_fence(tmp_path, monkeypatch) -> None:
    store = WorkFieldBindingStore(tmp_path)
    draft = _migration([LegacyFieldBindingEntry("f1", "text", "name", "", "")])
    entered: list[tuple[str, str]] = []

    @contextmanager
    def _spy(ws, work):
        entered.append((ws, work))
        yield

    monkeypatch.setattr(store_mod, "per_work_mutation_fence", _spy)
    commit_field_binding_migration(
        store, _Basis(draft.legacy_basis_fingerprint), workspace_instance_id=WS,
        work_authority_id=WORK, request_id="r", draft=draft,
        resolved_input=_input(rules=[_rule("f1")], keys=("name",)), now=NOW,
    )
    assert entered == [(WS, WORK)]


# ─── fence-first application review commit ────────────────────────────────────────
def test_application_review_commit_keeps_old_base_and_races(tmp_path) -> None:
    store = WorkFieldBindingStore(tmp_path)
    # 먼저 A17 revision 을 심는다.
    draft = _migration([LegacyFieldBindingEntry("f1", "text", "name", "", "")])
    a17 = commit_field_binding_migration(
        store, _Basis(draft.legacy_basis_fingerprint), workspace_instance_id=WS,
        work_authority_id=WORK, request_id="r1", draft=draft,
        resolved_input=_input(rules=[_rule("f1")], keys=("name",)), now=NOW,
    ).revision
    # A18 로 review.
    structure = CurrentApplicationFieldStructure("A18", ("f1", "f2"), (), ("name",))
    review = review_field_binding_for_current_application(a17, structure)
    resolved18 = _input(base="A18", rules=[_rule("f1")], keys=("name",))
    # Application 이 그새 A19 로 바뀌면 commit 0(stale 전파).
    changed_port = _StructurePort(replace(structure, application_id="A19"))
    from hwpxfiller.application.field_binding_input import StaleFieldBindingBasis
    with pytest.raises(StaleFieldBindingBasis):
        commit_field_binding_for_current_application(
            store, changed_port, workspace_instance_id=WS, work_authority_id=WORK,
            request_id="r2", review=review, resolved_input=resolved18, now=NOW,
        )
    assert store.load(WORK).aggregate_version == 1  # commit 0
    # 정상 review commit → 새 immutable revision(base=A18), old A17 base 불변.
    result = commit_field_binding_for_current_application(
        store, _StructurePort(structure), workspace_instance_id=WS, work_authority_id=WORK,
        request_id="r3", review=review, resolved_input=resolved18, now=NOW,
    )
    assert result.revision.base_template_application_id == "A18"
    stored = store.load(WORK)
    assert current_revision_id(stored, "A17") == a17.field_binding_authority_revision
    assert current_revision_id(stored, "A18") == result.revision.field_binding_authority_revision
    assert len(stored.application_review_drafts) == 1
    # A17 revision 내용은 그대로(silent base reassignment 0).
    a17_still = next(r for r in stored.immutable_binding_revisions
                     if r.field_binding_authority_revision == a17.field_binding_authority_revision)
    assert a17_still.base_template_application_id == "A17"
    # 같은 request 재전송 → replay(새 ledger 없음).
    again = commit_field_binding_for_current_application(
        store, _StructurePort(structure), workspace_instance_id=WS, work_authority_id=WORK,
        request_id="r3", review=review, resolved_input=resolved18, now=NOW,
    )
    assert again.outcome_replayed is True and again.revision == result.revision
