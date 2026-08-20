"""문서 만들기 작업대 어휘 정본(SX-01 · #724)의 원소·순서·개수·문안 노출 계약.

이 파일은 ``document_creation_vocabulary`` 를 import 해 정확한 값을 단언한다 — 정본이 바뀌면
여기가 먼저 빨강이 된다. wire-level parity(생성 TS 와의 대조)는 별도로
``tests/repo_contract/test_bridge_contract.py`` 의 독립 오러클이 진다.
"""

from __future__ import annotations

import re

from hwpxfiller.application import document_creation_vocabulary as vocab

# ─── #724 §3 blocker 계열 — 정의 순서가 곧 우선순위 기반, 정확히 14개 ────────────────────

EXPECTED_BLOCKERS = (
    "SELECT_DATA",
    "SELECT_RECORDS",
    "SELECT_WORK",
    "REVIEW_TEMPLATE_CHANGE",
    "CHOOSE_CONTENT",
    "REVIEW_BINDING",
    "REVIEW_RECORD_DATA",
    "REVIEW_DELIVERY",
    "REVIEW_PREVIEW",
    "EXECUTION_CHECKING",
    "EXECUTION_STALE",
    "POLICY_BLOCKED",
    "RUNTIME_NOT_ADMITTED",
    "CONTEXT_ERROR",
)

# ─── #724 §3 Primary Action — 우선순위 순서, 종단 CREATE_DOCUMENTS, 정확히 13개 ─────────

EXPECTED_PRIMARY_ACTIONS = (
    "RECOVER_CONTEXT",
    "SELECT_DATA",
    "SELECT_RECORDS",
    "SELECT_WORK",
    "REVIEW_TEMPLATE_CHANGE",
    "CHOOSE_CONTENT",
    "REVIEW_BINDING",
    "RESOLVE_EXECUTION",
    "REVIEW_RECORD_DATA",
    "REVIEW_DELIVERY",
    "REVIEW_PREVIEW",
    "RESOLVE_RUNTIME_POLICY",
    "CREATE_DOCUMENTS",
)


def test_blocker_codes_exact_order_and_count() -> None:
    assert vocab.BLOCKER_CODES == EXPECTED_BLOCKERS
    assert len(vocab.BLOCKER_CODES) == 14
    assert len(set(vocab.BLOCKER_CODES)) == 14  # 중복 없음


def test_primary_action_codes_exact_order_and_count() -> None:
    assert vocab.PRIMARY_ACTION_CODES == EXPECTED_PRIMARY_ACTIONS
    assert len(vocab.PRIMARY_ACTION_CODES) == 13
    assert len(set(vocab.PRIMARY_ACTION_CODES)) == 13
    # 우선순위 계약: 첫째는 context 복원, 마지막은 최종 실행(이슈가 리터럴로 고정).
    assert vocab.PRIMARY_ACTION_CODES[0] == "RECOVER_CONTEXT"
    assert vocab.PRIMARY_ACTION_CODES[-1] == "CREATE_DOCUMENTS"


def test_preview_requirement_kinds_exact() -> None:
    assert vocab.PREVIEW_REQUIREMENT_KINDS == ("NOT_REQUIRED", "OPTIONAL", "REQUIRED")


def test_collision_policies_exact_and_default() -> None:
    assert vocab.COLLISION_POLICIES == ("ADD_SUFFIX", "FAIL", "OVERWRITE_EXPLICIT")
    # 기본은 ADD_SUFFIX, overwrite 는 명시 선택(§8) — 기본이 정책 집합 안에 있고 덮어쓰기가 아님.
    assert vocab.DEFAULT_COLLISION_POLICY == "ADD_SUFFIX"
    assert vocab.DEFAULT_COLLISION_POLICY in vocab.COLLISION_POLICIES
    assert vocab.DEFAULT_COLLISION_POLICY != "OVERWRITE_EXPLICIT"


def test_user_vocabulary_maps_expected_domain_terms() -> None:
    # #724 §1 — 내부 도메인어 → 사용자 문안. exact 키·값 대조(정본이 바뀌면 빨강).
    assert vocab.USER_VOCABULARY == {
        "Slot": "포함할 내용",
        "Option": "선택지",
        "Active Field": "입력이 필요한 항목",
        "Working Configuration": "현재 선택/문서 구성",
        "Plan current": "현재 설정이 반영됐습니다",
        "Plan stale": "설정이 바뀌어 다시 확인해야 합니다",
        "Resolved Delivery": "생성 예정 문서",
        "Artifact": "실제 생성된 결과",
    }
    # Sealed Plan 은 기본 비노출이라 사용자 문안 매핑에 **없다**(§1).
    assert "Sealed Plan" not in vocab.USER_VOCABULARY
    assert vocab.NOT_EXPOSED_BY_DEFAULT == ("Sealed Plan",)


# ─── #724 §테스트 12 — 내부 어휘가 기본 사용자 문안으로 새지 않음 ──────────────────────────

#: 사용자 문안 값에 등장하면 안 되는 내부 진단어(독립 기술 — 모듈이 주는 목록을 쓰지 않는다).
_INTERNAL_DIAGNOSTIC = re.compile(
    r"Slot|Sealed|digest|Plan\b|VDR|Binding|Artifact|Delivery", re.IGNORECASE
)


def test_user_facing_copy_never_leaks_internal_vocabulary() -> None:
    leaks = {
        term: text
        for term, text in vocab.USER_VOCABULARY.items()
        if _INTERNAL_DIAGNOSTIC.search(text)
    }
    assert not leaks, f"사용자 문안이 내부 어휘를 노출한다: {leaks}"


def test_preview_identity_labels_do_not_impersonate_artifact() -> None:
    # semantic/value preview 는 Artifact 가 아니다(§7) — 라벨이 "실제 생성된 결과"(Artifact
    # 문안)이거나 내부 진단어를 담으면 안 된다.
    assert vocab.PREVIEW_IDENTITY_LABELS == (
        vocab.SEMANTIC_PREVIEW_LABEL,
        vocab.VALUE_PREVIEW_LABEL,
    )
    artifact_copy = vocab.USER_VOCABULARY["Artifact"]
    for label in vocab.PREVIEW_IDENTITY_LABELS:
        assert label != artifact_copy
        assert not _INTERNAL_DIAGNOSTIC.search(label)
