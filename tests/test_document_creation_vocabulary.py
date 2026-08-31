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
    "CONNECT_DATA",
    "REVIEW_TEMPLATE_CHANGE",
    "CHOOSE_CONTENT",
    "REVIEW_BINDING",
    "REVIEW_RECORD_DATA",
    "REVIEW_DELIVERY",
    # REVIEW_PREVIEW 는 #957 슬라이스 ③ 에서 사망했다 — 생성값 미리보기·승인 축 자체가 없다.
    "EXECUTION_NO_EVIDENCE",
    "EXECUTION_CHECKING",
    "EXECUTION_STALE",
    "POLICY_BLOCKED",
    "RUNTIME_NOT_ADMITTED",
    "CONTEXT_ERROR",
)

# ─── #724 §3 Primary Action — 우선순위 순서, 종단 CREATE_DOCUMENTS, 정확히 14개 ─────────

EXPECTED_PRIMARY_ACTIONS = (
    "RECOVER_CONTEXT",
    "SELECT_DATA",
    "SELECT_RECORDS",
    "SELECT_WORK",
    "CONNECT_DATA",
    "REVIEW_TEMPLATE_CHANGE",
    "CHOOSE_CONTENT",
    "REVIEW_BINDING",
    "RESOLVE_EXECUTION",
    "REVIEW_RECORD_DATA",
    "REVIEW_DELIVERY",
    # 대응 blocker 가 사라졌으므로 Primary Action 사슬에서도 함께 걷혔다(#957).
    "RESOLVE_RUNTIME_POLICY",
    "CREATE_DOCUMENTS",
)


def test_blocker_codes_exact_order_and_count() -> None:
    assert vocab.BLOCKER_CODES == EXPECTED_BLOCKERS
    assert len(vocab.BLOCKER_CODES) == 15   # -REVIEW_PREVIEW(#957 슬라이스 ③)
    assert len(set(vocab.BLOCKER_CODES)) == 15  # 중복 없음
    # 미리보기 승인 축은 어휘에서도 흔적이 없다 — 되살리려면 계약 변경으로 다시 등록해야 한다.
    assert "REVIEW_PREVIEW" not in vocab.BLOCKER_CODES
    # 확인 축 셋은 나란히 선다(#912 D1) — 「아직 확인 안 함」이 runtime 거절로 접히면
    # 그것을 지울 동사가 사슬 끝으로 밀려 사라진다.
    execution_axis = vocab.BLOCKER_CODES.index("EXECUTION_NO_EVIDENCE")
    assert vocab.BLOCKER_CODES[execution_axis : execution_axis + 3] == (
        "EXECUTION_NO_EVIDENCE",
        "EXECUTION_CHECKING",
        "EXECUTION_STALE",
    )


def test_primary_action_codes_exact_order_and_count() -> None:
    assert vocab.PRIMARY_ACTION_CODES == EXPECTED_PRIMARY_ACTIONS
    assert len(vocab.PRIMARY_ACTION_CODES) == 13   # -REVIEW_PREVIEW(#957 슬라이스 ③)
    assert len(set(vocab.PRIMARY_ACTION_CODES)) == 13
    # 우선순위 계약: 첫째는 context 복원, 마지막은 최종 실행(이슈가 리터럴로 고정).
    assert vocab.PRIMARY_ACTION_CODES[0] == "RECOVER_CONTEXT"
    assert vocab.PRIMARY_ACTION_CODES[-1] == "CREATE_DOCUMENTS"
    assert "REVIEW_PREVIEW" not in vocab.PRIMARY_ACTION_CODES


def test_preview_vocabulary_is_absent() -> None:
    """미리보기 축의 어휘 상수는 정본에 **없다**(#957 슬라이스 ③).

    음성 대조로 남긴다 — 상수가 조용히 되살아나면 그것을 읽는 표면도 함께 돌아오고,
    「확인의 자리는 만들어진 문서」라는 현행 정책과 두 목소리가 된다.
    """
    assert not hasattr(vocab, "PREVIEW_REQUIREMENT_KINDS")
    assert not hasattr(vocab, "SEMANTIC_PREVIEW_LABEL")


def test_collision_policies_exact_and_default() -> None:
    assert vocab.COLLISION_POLICIES == ("ADD_SUFFIX", "FAIL", "OVERWRITE_EXPLICIT")
    # U4 계열2-27: 기본은 덮어쓰기다. 이름 충돌 자체는 blocker 가 아니고, 고르는 자리도 없다.
    # 「조용히 덮지 않는다」를 지키는 것은 이 값이 아니라 그 결과다 — #957 이후 그 자리는
    # 생성 호출이 ``needs_overwrite`` 로 되돌아오는 확인 왕복이 진다(승인 축 아님).
    assert vocab.DEFAULT_COLLISION_POLICY == "OVERWRITE_EXPLICIT"
    assert vocab.DEFAULT_COLLISION_POLICY in vocab.COLLISION_POLICIES


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
