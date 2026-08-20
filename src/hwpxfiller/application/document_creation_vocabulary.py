"""문서 만들기 작업대의 **wire-level 어휘 단일 출처**(SX-01 · #724).

SX-01 의 나머지 Application/Product 모듈(``preview_requirement`` · ``run_delivery_intent`` ·
``document_creation_workbench``)은 이 파일의 상수를 **import 만** 한다. 여기에는 판정 로직이
없다 — 순수 상수/어휘 tuple 과 사용자 문안 매핑뿐이다. blocker 우선순위 계산·PreviewRequirement
정책·collision 재해결은 각각 그 모듈이 소유하고, 이 파일은 그들이 합의할 **문자열의 정본**만
진다.

두 부류를 담는다.

1. **사용자 문안 매핑**(#724 §1) — 내부 도메인어 → 사용자 문안. 내부 어휘(Slot/Plan/Sealed/
   digest 등)는 진단 표면 밖에서 **기본 사용자 문안으로 노출하지 않는다**(§테스트 12). 이
   매핑이 그 계약의 오러클이다 — 값은 사용자가 읽을 한국어 문안이고 내부 영어 어휘를 담지
   않는다.
2. **wire-level 코드 tuple** — blocker 계열(§3) · Primary Action 우선순위(§3) ·
   PreviewRequirement 종류(§6) · collision policy(§8). 정의 순서가 곧 계약이다:
   ``scripts/gen_bridge_contract.py`` 가 이 tuple 들을 ``frontend/src/contract/contract.gen.ts``
   로 방출하고 드리프트 게이트가 바이트로 지킨다. 순서를 흔들면 Python↔TypeScript parity 가
   깨진다.
"""

from __future__ import annotations

# ------------------------------------------------------------------ 사용자 어휘

#: 내부 도메인어 → 사용자 문안(#724 §1). 값은 사용자에게 그대로 보이는 한국어 문안이라
#: 내부 영어 어휘(Slot/Plan/Sealed/digest 등)를 담지 않는다 — 그것이 §테스트 12 의 계약이다.
#: ``Sealed Plan`` 은 기본 비노출이라 여기 없다(:data:`NOT_EXPOSED_BY_DEFAULT`).
USER_VOCABULARY: dict[str, str] = {
    "Slot": "포함할 내용",
    "Option": "선택지",
    "Active Field": "입력이 필요한 항목",
    "Working Configuration": "현재 선택/문서 구성",
    "Plan current": "현재 설정이 반영됐습니다",
    "Plan stale": "설정이 바뀌어 다시 확인해야 합니다",
    "Resolved Delivery": "생성 예정 문서",
    "Artifact": "실제 생성된 결과",
}

#: 기본 사용자 표면에 **문안 자체를 두지 않는** 내부 개념(#724 §1: ``Sealed Plan → 기본 비노출``).
#: 진단/개발자 표면에서만 이름으로 등장하고, 사용자 작업대에는 대응 문안이 없다.
NOT_EXPOSED_BY_DEFAULT: tuple[str, ...] = ("Sealed Plan",)

# ------------------------------------------------------------------ blocker 계열

#: 사용자 작업대 blocker 계열(#724 §3). **정의 순서가 곧 우선순위 기반**이다 — 여러 blocker 가
#: 동시에 서 있어도 Primary Action 은 이 순서로 하나만 고른다. React 가 이 순서를 재구현하지
#: 않는다(합성은 backend Product 계약이 진다).
BLOCKER_CODES: tuple[str, ...] = (
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

# ------------------------------------------------------------------ Primary Action

#: Primary Action 코드 — **우선순위 순서**(#724 §3). 첫 원소가 최우선(context 복원 실패)이고
#: 마지막이 ``CREATE_DOCUMENTS`` 다. 우선순위 사슬은 이슈가 못박은 것이고, 각 단계의 코드 이름은
#: blocker 계열과 나란히 붙였다(``EXECUTION_CHECKING``/``EXECUTION_STALE`` 두 blocker → 하나의
#: ``RESOLVE_EXECUTION``, ``RUNTIME_NOT_ADMITTED``/``POLICY_BLOCKED`` 두 blocker → 하나의
#: ``RESOLVE_RUNTIME_POLICY`` 로 접힌다). 이슈가 리터럴로 고정한 코드는 종단 ``CREATE_DOCUMENTS``
#: 뿐이고 나머지 식별자 명명은 이 정본이 소유한다.
PRIMARY_ACTION_CODES: tuple[str, ...] = (
    "RECOVER_CONTEXT",         # context 복원 실패 → 복구
    "SELECT_DATA",             # 데이터
    "SELECT_RECORDS",          # 레코드
    "SELECT_WORK",             # Work
    "REVIEW_TEMPLATE_CHANGE",  # Template change
    "CHOOSE_CONTENT",          # content
    "REVIEW_BINDING",          # Binding
    "RESOLVE_EXECUTION",       # execution checking/stale
    "REVIEW_RECORD_DATA",      # record
    "REVIEW_DELIVERY",         # delivery
    "REVIEW_PREVIEW",          # required preview
    "RESOLVE_RUNTIME_POLICY",  # runtime/policy
    "CREATE_DOCUMENTS",        # 최종 실행(이슈가 리터럴로 고정)
)

# ------------------------------------------------------------------ PreviewRequirement

#: PreviewRequirement 종류. ``REQUIRED`` reason 은 current delivery 의 실제 overwrite 사실이다.
PREVIEW_REQUIREMENT_KINDS: tuple[str, ...] = ("NOT_REQUIRED", "OPTIONAL", "REQUIRED")

#: semantic/value preview 정체 라벨. 이 미리보기는 current Plan + VDR 의 사용자 투영이라
#: **HWPX bytes·actual layout·Artifact 가 아니다**. 그래서 라벨은 "실제 생성된 결과"(=Artifact
#: 문안)처럼 읽히지 않고 "확인" 계열로만 말한다.
SEMANTIC_PREVIEW_LABEL = "생성 내용 확인"

# ------------------------------------------------------------------ RunDeliveryIntent

#: session-scoped RunDeliveryIntent 의 collision policy(#724 §8). 기본은
#: :data:`DEFAULT_COLLISION_POLICY`(``ADD_SUFFIX``)이고 ``OVERWRITE_EXPLICIT`` 은 명시적 선택이
#: 필요하다. 선택 사실만으로 preview 를 REQUIRED 로 만들지는 않는다.
COLLISION_POLICIES: tuple[str, ...] = ("ADD_SUFFIX", "FAIL", "OVERWRITE_EXPLICIT")

#: 기본 충돌 정책 — 덮어쓰기는 사용자가 명시로 골라야 한다(조용히 덮지 않는다).
DEFAULT_COLLISION_POLICY = "ADD_SUFFIX"
