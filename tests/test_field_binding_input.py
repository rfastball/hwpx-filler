"""S5-01 FieldBindingInput capture·revision identity·legacy migration·review (#697)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from hwpxfiller.application.field_binding_input import (
    BROKEN,
    INACTIVE_ONLY,
    NEW_ACTIVE_FIELD,
    PRESERVED,
    CurrentApplicationFieldStructure,
    FieldBindingInput,
    FieldBindingRevision,
    FieldBindingReviewRequired,
    StaleFieldBindingBasis,
    LegacyFieldBindingEntry,
    build_field_binding_input,
    decide_application_review_commit,
    decide_migration_commit,
    field_binding_authority_revision_identity,
    RUNTIME_TODAY_UNSUPPORTED,
    prepare_legacy_field_binding_migration,
    review_field_binding_for_current_application,
    revision_from_input,
)
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    INTENTIONAL_BLANK,
    SOURCE,
    ExactText,
    FieldBindingInputIntegrityError,
    FieldBindingRule,
    UnsupportedFieldBindingContractError,
)

POLICY = DOCUMENT_CONTENT_VALUE_POLICY_V1
WS = "ws-1"
WORK = "work-1"
NOW = "2026-01-01T00:00:00+09:00"


def _rule(field_id: str, key: str = "name") -> FieldBindingRule:
    return FieldBindingRule(field_id, SOURCE, POLICY, source_key=key)


def _input(
    *,
    base: str = "A17",
    rules=None,
    keys=("name", "amount"),
    work: str = WORK,
) -> FieldBindingInput:
    return build_field_binding_input(
        workspace_instance_id=WS,
        work_authority_id=work,
        base_template_application_id=base,
        binding_rules=rules if rules is not None else [_rule("계약명")],
        source_schema_keys=list(keys),
        raw_record_contract_id="raw-record/v1",
        captured_at=NOW,
    )


# ─── identity 단일성 / provenance ────────────────────────────────────────────────
def test_authority_revision_is_single_content_addressed_identity() -> None:
    inp = _input()
    rev = revision_from_input(inp)
    # WorkAuthorityId 단일성: revision 의 work id == 주어진 work id.
    assert rev.work_authority_id == WORK
    # 두 번째 identity 부재 — 금지된 이름의 필드가 없다.
    for forbidden in ("revision_id", "binding_snapshot_id", "mapping_application_epoch"):
        assert not hasattr(rev, forbidden)
    # content-address: 같은 내용 → 같은 id, captured_at 은 identity 에 불참(provenance).
    later = replace(inp, captured_at="2027-09-09T00:00:00+09:00")
    assert later.field_binding_authority_revision == inp.field_binding_authority_revision
    # 다른 base → 다른 id.
    assert _input(base="A18").field_binding_authority_revision != (
        inp.field_binding_authority_revision
    )


def test_revision_rejects_tampered_identity_and_digest() -> None:
    inp = _input()
    with pytest.raises(FieldBindingInputIntegrityError):
        replace(inp, field_binding_authority_revision="fbrev:sha256:deadbeef")
    with pytest.raises(FieldBindingInputIntegrityError):
        FieldBindingRevision(
            work_authority_id=WORK,
            base_template_application_id="A17",
            field_binding_authority_revision=field_binding_authority_revision_identity(
                work_authority_id=WORK, base_template_application_id="A17",
                field_binding_semantic_contract_id="field-binding/v2",
                source_schema_contract_id="source-schema/v2",
                raw_record_contract_id="raw-record/v1",
                canonical_binding_digest=inp.canonical_binding_digest,
                canonical_source_schema_digest=inp.canonical_source_schema_digest,
            ),
            field_binding_semantic_contract_id="field-binding/v2",
            source_schema_contract_id="source-schema/v2",
            raw_record_contract_id="raw-record/v1",
            binding_rules=inp.binding_rules,
            source_schema_keys=inp.source_schema_keys,
            canonical_binding_digest="sha256:wrong",  # digest mismatch
            canonical_source_schema_digest=inp.canonical_source_schema_digest,
            captured_at=NOW,
        )


def test_revision_rejects_tampered_rules_and_keys() -> None:
    rev = revision_from_input(_input(rules=[_rule("f1")], keys=("name", "amount")))
    # identity/digest 는 그대로 두고 규칙만 바꾸면 규칙/digest mismatch.
    with pytest.raises(FieldBindingInputIntegrityError):
        replace(rev, binding_rules=(_rule("other"),))
    with pytest.raises(FieldBindingInputIntegrityError):
        replace(rev, source_schema_keys=("name",))


def test_input_integrity_digest_and_contract_checks() -> None:
    inp = _input()
    with pytest.raises(FieldBindingInputIntegrityError):
        replace(inp, canonical_binding_digest="sha256:nope")
    with pytest.raises(FieldBindingInputIntegrityError):
        replace(inp, canonical_source_schema_digest="sha256:nope")
    with pytest.raises(UnsupportedFieldBindingContractError):
        replace(inp, field_binding_semantic_contract_id="field-binding/v1")
    with pytest.raises(FieldBindingInputIntegrityError):
        replace(inp, base_template_application_id="")


# ─── legacy migration ────────────────────────────────────────────────────────────
def _legacy(entries):
    return prepare_legacy_field_binding_migration(
        work_authority_id=WORK,
        base_template_application_id="A17",
        legacy_entries=entries,
        captured_at=NOW,
    )


def test_prepare_surfaces_implicit_strip_as_explicit_policy_candidate() -> None:
    draft = _legacy([
        LegacyFieldBindingEntry("계약명", "text", "name", "", ""),
        LegacyFieldBindingEntry("금액", "amount", "amt", "", "{:,}"),
        LegacyFieldBindingEntry("고정", "const", "", "확정", ""),
    ])
    by_field = {c.field_id: c for c in draft.candidate_rules}
    # text/amount 는 legacy-strip whitespace 정책 후보 + 명시 결정 요구.
    assert by_field["계약명"].proposed_policy_id == (
        DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP.policy_id
    )
    assert by_field["계약명"].whitespace_decision_required is True
    assert by_field["금액"].binding_kind == SOURCE
    assert by_field["금액"].format_code == "{:,}"
    # const → canonicalization 후보(ExactText), 자동 strip 결정 없음.
    assert by_field["고정"].binding_kind == CONSTANT
    assert by_field["고정"].canonical_constant_value == ExactText("확정")
    assert draft.blockers == ()


def test_empty_constant_is_an_exact_empty_text_candidate_not_a_blocker() -> None:
    """빈 고정값은 모호하지 않다 — ``ExactText("")`` 후보로 곧장 간다.

    옛 ``blank``(출력 제외)만이 Intentional Blank 와 뜻이 갈려 명시 결정을 요구했고, 그
    유형이 퇴역하면서 그 blocker(``AMBIGUOUS_BLANK_OMISSION``)도 함께 죽었다.
    """
    draft = _legacy([
        LegacyFieldBindingEntry("빈칸", "const", "", "", ""),
        LegacyFieldBindingEntry("계약명", "text", "name", "", ""),
    ])
    by_field = {c.field_id: c for c in draft.candidate_rules}
    assert by_field["빈칸"].binding_kind == CONSTANT
    assert by_field["빈칸"].canonical_constant_value == ExactText("")
    assert draft.blockers == ()


def test_today_is_blocker_not_a_false_source_or_constant_rule() -> None:
    """U4-E1 #939 — legacy ``today``(오늘 날짜)는 v1 binding kind 어휘에 대응이 없다.

    값이 **실행 시각**에서 나오므로 SOURCE(데이터 열)도 CONSTANT(고정 리터럴)도 아니다.
    빈 ``source_key`` 의 SOURCE 나 그때의 렌더값을 담은 CONSTANT 로 접으면 판본에 **거짓
    durable 규칙**을 적는다 — 조용히 틀리느니 명시 결정으로 남긴다.
    """
    draft = _legacy([
        LegacyFieldBindingEntry("작성일", "today", "", "", "%Y-%m-%d"),
        LegacyFieldBindingEntry("계약명", "text", "name", "", ""),
    ])
    assert all(c.field_id != "작성일" for c in draft.candidate_rules)
    assert [(b.field_id, b.reason) for b in draft.blockers] == [
        ("작성일", RUNTIME_TODAY_UNSUPPORTED)
    ]
    # 다른 Field 는 그대로 후보가 된다(한 행의 미지원이 판본 전체를 삼키지 않는다).
    assert [c.field_id for c in draft.candidate_rules] == ["계약명"]


def test_prepare_rejects_unknown_legacy_type() -> None:
    with pytest.raises(FieldBindingInputIntegrityError):
        _legacy([LegacyFieldBindingEntry("f", "weird", "s", "", "")])


def test_migration_commit_decision_paths() -> None:
    draft = _legacy([
        LegacyFieldBindingEntry("빈칸", "today", "", "", ""),
        LegacyFieldBindingEntry("계약명", "text", "name", "", ""),
    ])
    basis = draft.legacy_basis_fingerprint
    # 미해결 blocker(빈칸 없음) → review required.
    partial = _input(rules=[_rule("계약명")])
    with pytest.raises(FieldBindingReviewRequired) as ei:
        decide_migration_commit(draft, partial, "A17", basis)
    assert ei.value.code == "FIELD_BINDING_MIGRATION_REVIEW_REQUIRED"
    resolved = _input(rules=[_rule("계약명"), FieldBindingRule("빈칸", INTENTIONAL_BLANK, POLICY)])
    # legacy fingerprint 이동 → stale.
    with pytest.raises(StaleFieldBindingBasis):
        decide_migration_commit(draft, resolved, "A17", "sha256:moved")
    # current Application 이동(A17→A18, legacy 그대로) → stale(#6).
    with pytest.raises(StaleFieldBindingBasis):
        decide_migration_commit(draft, resolved, "A18", basis)
    # 모두 해결 → immutable revision.
    rev = decide_migration_commit(draft, resolved, "A17", basis)
    assert isinstance(rev, FieldBindingRevision)
    assert rev.base_template_application_id == "A17"
    # 다른 work 결속 → integrity.
    with pytest.raises(FieldBindingInputIntegrityError):
        decide_migration_commit(
            replace(draft, work_authority_id="other"), resolved, "A17", basis
        )


def test_migration_commit_blocks_dropped_candidate_unless_omitted() -> None:
    # candidate field 를 resolved_input 에서 빼면 silent drop 대신 review required(#2).
    draft = _legacy([
        LegacyFieldBindingEntry("계약명", "text", "name", "", ""),
        LegacyFieldBindingEntry("금액", "amount", "amt", "", ""),
    ])
    basis = draft.legacy_basis_fingerprint
    only_one = _input(rules=[_rule("계약명")], keys=("name", "amt"))
    with pytest.raises(FieldBindingReviewRequired):
        decide_migration_commit(draft, only_one, "A17", basis)
    # 명시 omission 결정을 주면 commit 가능.
    rev = decide_migration_commit(draft, only_one, "A17", basis, omitted_field_ids={"금액"})
    assert isinstance(rev, FieldBindingRevision)


def test_revision_rejects_unsupported_contract_on_reconstruction() -> None:
    # 저장 revision 이 미지원 contract 를 담으면 loud fail(#7).
    inp = _input()
    identity = field_binding_authority_revision_identity(
        work_authority_id=WORK, base_template_application_id="A17",
        field_binding_semantic_contract_id="field-binding/v3",
        source_schema_contract_id="source-schema/v2",
        raw_record_contract_id="raw-record/v1",
        canonical_binding_digest=inp.canonical_binding_digest,
        canonical_source_schema_digest=inp.canonical_source_schema_digest,
    )
    with pytest.raises(UnsupportedFieldBindingContractError):
        FieldBindingRevision(
            work_authority_id=WORK, base_template_application_id="A17",
            field_binding_authority_revision=identity,
            field_binding_semantic_contract_id="field-binding/v3",
            source_schema_contract_id="source-schema/v2",
            raw_record_contract_id="raw-record/v1",
            binding_rules=inp.binding_rules, source_schema_keys=inp.source_schema_keys,
            canonical_binding_digest=inp.canonical_binding_digest,
            canonical_source_schema_digest=inp.canonical_source_schema_digest,
            captured_at=NOW,
        )


# ─── application review ──────────────────────────────────────────────────────────
def _structure(active, inactive=(), keys=("name",)) -> CurrentApplicationFieldStructure:
    return CurrentApplicationFieldStructure("A18", tuple(active), tuple(inactive), tuple(keys))


def test_review_classifies_preserved_broken_new_inactive() -> None:
    old = revision_from_input(_input(rules=[
        _rule("preserved", "name"),
        _rule("removed", "name"),
        _rule("moved_inactive", "name"),
        _rule("source_gone", "vanished_key"),
    ], keys=("name", "vanished_key")))
    structure = _structure(
        active=("preserved", "source_gone", "brand_new"),
        inactive=("moved_inactive",),
        keys=("name",),  # vanished_key 없음
    )
    review = review_field_binding_for_current_application(old, structure)
    got = {c.field_id: c.category for c in review.classifications}
    assert got["preserved"] == PRESERVED
    assert got["removed"] == BROKEN  # 삭제됨
    assert got["moved_inactive"] == INACTIVE_ONLY
    assert got["source_gone"] == BROKEN  # source key 재결속 불가
    assert got["brand_new"] == NEW_ACTIVE_FIELD
    assert set(review.broken_field_ids()) == {"removed", "source_gone"}
    # 보존 대상은 INACTIVE_ONLY 뿐이다(#877) — 삭제된 Field 는 BROKEN 이라 판본이 이어 나르지
    # 않는다(존재하지 않는 Field 규칙을 실은 판본은 commit 결정이 거절한다).
    assert review.inactive_only_field_ids() == ("moved_inactive",)


def test_review_commit_decision_paths() -> None:
    old = revision_from_input(_input(rules=[_rule("f1")], keys=("name",)))
    structure = _structure(active=("f1", "f2"), keys=("name",))
    review = review_field_binding_for_current_application(old, structure)
    resolved = _input(base="A18", rules=[_rule("f1")], keys=("name",))
    # current Application 이 review target 과 다름 → stale.
    other = _structure(active=("f1",))
    changed = replace(other, application_id="A19")
    with pytest.raises(StaleFieldBindingBasis):
        decide_application_review_commit(review, resolved, changed)
    # basis digest 이동(같은 app id, 다른 구조) → stale.
    drifted = _structure(active=("f1", "f2", "f3"), keys=("name",))
    with pytest.raises(StaleFieldBindingBasis):
        decide_application_review_commit(review, drifted, drifted)
    # resolved 가 current active 아닌 Field 참조 → review required.
    bad = _input(base="A18", rules=[_rule("ghost")], keys=("name",))
    with pytest.raises(FieldBindingReviewRequired) as ei:
        decide_application_review_commit(review, bad, structure)
    assert ei.value.code == "FIELD_BINDING_APPLICATION_REVIEW_REQUIRED"
    # SOURCE 규칙이 current schema 에 없는 source_key 로 결속 → review required(#3).
    stale_key = _input(base="A18", rules=[_rule("f1", "vanished")], keys=("vanished",))
    with pytest.raises(FieldBindingReviewRequired) as ei2:
        decide_application_review_commit(review, stale_key, structure)
    assert ei2.value.code == "FIELD_BINDING_APPLICATION_REVIEW_REQUIRED"
    # base 가 current Application 아님 → integrity(old base 재지정 금지).
    wrong_base = _input(base="A17", rules=[_rule("f1")], keys=("name",))
    with pytest.raises(FieldBindingInputIntegrityError):
        decide_application_review_commit(review, wrong_base, structure)
    # 정상 → base=A18 revision.
    rev = decide_application_review_commit(review, resolved, structure)
    assert rev.base_template_application_id == "A18"
    # 다른 work 결속 → integrity.
    with pytest.raises(FieldBindingInputIntegrityError):
        decide_application_review_commit(
            replace(review, work_authority_id="zzz"), resolved, structure
        )


def test_review_commit_keeps_inactive_rules_and_rejects_absent_fields() -> None:
    # U3-04(#877): 판본 스코프는 활성 절단이 아니다 — 비활성 Field 규칙을 실은 입력도 통과하고
    # (그 규칙이 판본에 남아야 옵션 왕복이 재확정을 요구하지 않는다), current Application 이
    # 아예 모르는 Field 규칙만 거절한다.
    old = revision_from_input(_input(rules=[_rule("f1"), _rule("f2")], keys=("name",)))
    structure = _structure(active=("f1",), inactive=("f2",), keys=("name",))
    review = review_field_binding_for_current_application(old, structure)
    assert review.inactive_only_field_ids() == ("f2",)

    kept = _input(base="A18", rules=[_rule("f1"), _rule("f2")], keys=("name",))
    rev = decide_application_review_commit(review, kept, structure)
    assert {r.field_id for r in rev.binding_rules} == {"f1", "f2"}

    # 비활성 규칙의 source_key 는 current schema 대조 대상이 아니다(실행에 참여하지 않는다).
    stale_inactive = _input(
        base="A18", rules=[_rule("f1"), _rule("f2", "vanished")], keys=("name",)
    )
    assert decide_application_review_commit(review, stale_inactive, structure)

    # active 도 inactive 도 아닌 Field(템플릿에서 사라짐) → 미해결 BROKEN.
    ghost = _input(base="A18", rules=[_rule("f1"), _rule("gone")], keys=("name",))
    with pytest.raises(FieldBindingReviewRequired) as ei:
        decide_application_review_commit(review, ghost, structure)
    assert ei.value.code == "FIELD_BINDING_APPLICATION_REVIEW_REQUIRED"
