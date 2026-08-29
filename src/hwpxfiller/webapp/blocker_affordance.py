"""blocker 코드 → **어포던스 선언**의 단일 출처(#912 (a) 층).

## 왜 이 표가 있는가

#912 전수 감사가 이름 지은 결함류는 하나다: **「blocker X 가 섰는데 그것을 지울 활성 컨트롤이
렌더되지 않거나, 액션이 등록만 되고 호출자가 없다」**. D1 은 확인 동사가 Primary Action
우선순위에 묶여 사라진 자리였고, D4 는 ``refresh_observation`` 이 registry·핸들러 양쪽에 있는데
프런트 호출자가 0 이었던 자리(단방향 배선)다. 둘 다 **어느 한 층만 보면 초록**이다 — 링1 은
blocker 를 옳게 세웠고, registry 는 액션을 옳게 등록했고, 렌더는 문안을 옳게 그렸다.

그래서 이 표는 「그 blocker 를 사용자가 무엇으로 지우는가」를 **한 자리에 선언**하고,
``tests/repo_contract/test_blocker_affordance_registry.py`` 가 선언과 실재를 대조한다. 새 blocker
를 추가하는 사람은 세 형태 중 하나를 **명시로 고르지 않으면** 지나가지 못한다.

## 세 형태 — 「없음」도 선언이다

* :data:`ACTIVE_VERB` — 지금 누를 수 있는 동사가 화면에 있다. 셀렉터 + 그것이 부르는
  dispatch 액션(``"화면.액션"``) 또는 직접 브리지 메서드(``WebFrontend`` 공개 메서드).
* :data:`AUTOMATIC_PROGRESS` — 자동 진행 중이라 동사가 **비활성 + 사유**로 선다. 숨기지 않는다
  (``EXECUTION_CHECKING`` — 자동 확인이 이미 그 일을 하는 중이다).
* :data:`NO_VERB_BY_DESIGN` — 사용자가 지금 지울 수 없는 상태라 **동사를 설계상 두지 않는다**.
  ``POLICY_BLOCKED``·``RUNTIME_NOT_ADMITTED`` 가 그것이고, 그 자리는 알림(사유 병기)이 맡는다.
  **생략이 아니라 선언**이다 — 빈칸으로 두면 「아직 안 배선했다」와 구별되지 않고, 그 구별이
  없으면 D4 같은 자리가 다시 조용히 산다.

## 링 위치

셀렉터(DOM 좌표)를 담으므로 링2 다. 링0/링1 은 이 파일을 import 하지 않는다 — blocker 어휘의
정본은 ``application/document_creation_vocabulary.py`` 이고 여기는 그 어휘의 **표면 착지**만
진다. 어휘를 늘리는 것은 저쪽, 착지를 선언하는 것은 이쪽이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..application.document_creation_vocabulary import BLOCKER_CODES

#: 지금 누를 수 있는 동사가 있다(셀렉터 + 액션).
ACTIVE_VERB = "ACTIVE_VERB"
#: 자동 진행 중 — 동사는 서되 비활성 + 사유 병기.
AUTOMATIC_PROGRESS = "AUTOMATIC_PROGRESS"
#: 설계상 동사 없음 — 알림 설계(생략이 아니라 명시 선언).
NO_VERB_BY_DESIGN = "NO_VERB_BY_DESIGN"

AFFORDANCE_KINDS: tuple[str, ...] = (ACTIVE_VERB, AUTOMATIC_PROGRESS, NO_VERB_BY_DESIGN)


@dataclass(frozen=True)
class BlockerAffordance:
    """blocker 하나의 어포던스 선언 — 형태 + 그 형태가 요구하는 좌표.

    불변식(:meth:`validate` 가 구성 시점에 강제):

    * ``ACTIVE_VERB`` ⇒ ``selector`` 가 있고 ``dispatch_action``/``bridge_method`` **정확히 하나**.
    * ``AUTOMATIC_PROGRESS`` ⇒ ``selector`` 가 있고 액션 좌표는 없다(누를 것이 아니라 볼 것이다).
    * ``NO_VERB_BY_DESIGN`` ⇒ 셀렉터·액션 모두 없다. ``rationale`` 이 왜 없는지를 말한다.
    """

    kind: str
    rationale: str
    selector: "str | None" = None
    dispatch_action: "str | None" = None  # "화면.액션" — action_registry 좌표
    bridge_method: "str | None" = None  # WebFrontend 공개 메서드(직접 브리지 경로)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.kind not in AFFORDANCE_KINDS:
            raise ValueError(f"모르는 어포던스 형태: {self.kind!r}")
        if not self.rationale:
            raise ValueError("어포던스 선언에는 사유가 있어야 한다")
        coordinates = [c for c in (self.dispatch_action, self.bridge_method) if c is not None]
        if self.kind == ACTIVE_VERB:
            if self.selector is None or len(coordinates) != 1:
                raise ValueError(
                    "ACTIVE_VERB 는 셀렉터와 액션 좌표 정확히 하나를 요구한다"
                    f" — {self.selector!r} / {coordinates!r}"
                )
        elif self.kind == AUTOMATIC_PROGRESS:
            if self.selector is None or coordinates:
                raise ValueError(
                    "AUTOMATIC_PROGRESS 는 셀렉터만 갖는다(누를 것이 아니라 볼 것이다)"
                )
        elif self.selector is not None or coordinates:
            raise ValueError("NO_VERB_BY_DESIGN 은 셀렉터도 액션도 갖지 않는다")


_TABLE: dict[str, BlockerAffordance] = {
    "SELECT_DATA": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector="#jobBtnPickData",
        bridge_method="pick_data_file",
        rationale="네이티브 파일 피커가 관여해 직접 브리지 경로다(디스패치 밖).",
    ),
    "SELECT_RECORDS": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector="#jobSelAll",
        dispatch_action="job.set_all",
        rationale="표의 행 선택 동사. 개별 토글(`toggle_record`)도 같은 축이지만 "
        "「지금 0건이라 막혔다」를 한 번에 지우는 것은 모두 선택이다.",
    ),
    "SELECT_WORK": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector="#jobCandidates .cand-pick",
        dispatch_action="job.select_job",
        rationale="이 데이터에 연결된 작업 후보 카드가 곧 선택 동사다(U4 §2.4 — 후보 축은 결속이다).",
    ),
    "CONNECT_DATA": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector="#jobConnectData",
        bridge_method="open_job_in_editor",
        rationale="결속을 쓰는 자리는 편집기 저장 하나라(U4 §2.4) 복구도 거기다. "
        "동사를 데이터 머리에 두는 이유는 게이트가 「현재 데이터」 구획을 지목하기 "
        "때문이다 — 없는 자리를 가리키는 지시는 이행 불가능하다. 네이티브 진입이 "
        "아니라 직접 브리지인 이유는 편집기 진입이 이탈 가드·미저장 확인을 지나기 "
        "때문이다(디스패치 밖).",
    ),
    "REVIEW_TEMPLATE_CHANGE": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector="#jobTplCheck",
        dispatch_action="job.template_check",
        rationale="「변경사항 확인」이 이 요구를 지운다(적용은 그 다음 동사라 여기 아니다).",
    ),
    "CHOOSE_CONTENT": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector=".cs-option-input",
        dispatch_action="job.select_slot_option",
        rationale="구간 갈래 라디오(EXACTLY_ONE). "
        "선택 불가 상태만 남은 갈래는 라디오가 비활성이라 이 선언이 거짓이 된다 — "
        "그 자리는 별도 blocker 로 분기해야 하고 #921(D3) 이 그 수리를 진다.",
    ),
    "REVIEW_BINDING": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector="#jobInputRequirements button",
        bridge_method="open_job_in_editor",
        rationale="결속 확정은 편집기에서 한다 — 진입이 네이티브 창 수명주기를 지나 "
        "직접 브리지다. 무변경 확정 동사 무장은 #911 이 세웠다.",
    ),
    "REVIEW_RECORD_DATA": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector="#jobRecordValidationIssues button",
        dispatch_action="job.recover_record_issue",
        rationale="「문제 위치 보기」가 지목된 칸으로 데려간다(겨눔은 backend exact target).",
    ),
    "REVIEW_DELIVERY": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector="#jobManagedPickFolder",
        bridge_method="pick_output_folder",
        rationale="이름 충돌은 U4 계열2-27 이후 blocker 가 아니다(기본이 덮어쓰기이고 "
        "파괴 확인은 REVIEW_PREVIEW 가 진다). 그래서 이 자리에 남는 원인은 「그 이름이 "
        "덮어쓸 수 없는 물건(폴더·바로가기)에 걸렸다」이고, 그것을 지우는 동사는 저장 "
        "폴더를 바꾸는 것이다 — 네이티브 피커라 직접 브리지 경로다. 파일 이름 규칙 자체의 "
        "미해소는 저장 시점 게이트(U4 계열4-4 `validate_save`)가 앱 안에서 만들어지는 것을 "
        "막고, 앱 밖에서 편집된 작업이 그것을 들고 오면 사유를 `#jobDeliveryBlockers` 가 "
        "병기한다. 종전 좌표 `#jobRefreshDelivery` 는 「목록 새로 확인」이었는데, 그 동사는 "
        "충돌 갈래에서만 참이었고 나머지 원인에는 아무 일도 하지 않았다.",
    ),
    "REVIEW_PREVIEW": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector="#jobManagedPreviewOpen",
        dispatch_action="job.preview_open",
        rationale="확인 면을 열어야 승인이 성립한다. 승인 자체(`preview_approve`)는 "
        "그 면 안의 동사라 이 자리의 좌표는 여는 쪽이다.",
    ),
    "EXECUTION_NO_EVIDENCE": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector="#jobResolveExecution",
        dispatch_action="job.resolve_execution",
        rationale="#912 D1 이 세운 축 — 앞선 blocker 가 Primary Action 을 가져가도 "
        "이 동사는 사라지지 않는다(적재 조건이 status code 축이다).",
    ),
    "EXECUTION_CHECKING": BlockerAffordance(
        kind=AUTOMATIC_PROGRESS,
        selector="#jobResolveExecution",
        rationale="자동 확인이 진행 중이라 누를 것이 없다. 숨기지 않고 비활성 + "
        "사유(「설정을 확인하고 있습니다」)로 서고, 링1 의 "
        "`resolve_execution_disabled_reason` 이 그 사유의 단일 출처다.",
    ),
    "EXECUTION_STALE": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector="#jobResolveExecution",
        dispatch_action="job.resolve_execution",
        rationale="설정이 갈려 재확인이 필요한 자리 — 같은 확인 동사가 지운다.",
    ),
    "POLICY_BLOCKED": BlockerAffordance(
        kind=NO_VERB_BY_DESIGN,
        rationale="정책이 거절한 상태라 사용자가 지금 지울 수단이 없다. 동사를 세우면 "
        "누를 수 있다는 거짓을 말하게 된다 — 그 자리는 생성 버튼의 사유 병기"
        "(「정책상 지금은 문서를 만들 수 없습니다」)가 맡는다.",
    ),
    "RUNTIME_NOT_ADMITTED": BlockerAffordance(
        kind=NO_VERB_BY_DESIGN,
        rationale="런타임이 이 실행을 받지 못하는 상태 — 사용자 행동으로 바뀌지 않는다. "
        "POLICY_BLOCKED 와 같은 이유로 알림 설계이고, 사유는 "
        "「현재 환경에서는 문서를 만들 수 없습니다」다.",
    ),
    "CONTEXT_ERROR": BlockerAffordance(
        kind=ACTIVE_VERB,
        selector="#jobRecoverContext",
        dispatch_action="job.refresh_observation",
        rationale="#912 D4 — `refresh_observation` 은 registry·핸들러 양쪽에 있었는데 "
        "프런트 호출자가 0 이라 복구 동사가 화면에 선 적이 없었다. 다시 관찰해 "
        "성공하면 맥락이 복원되고, 실패하면 새 context error 로 시끄럽게 교체된다.",
    ),
}

_undeclared = sorted(set(_TABLE) - set(BLOCKER_CODES))
if _undeclared:  # pragma: no cover — import 시점 계약(테스트가 아니라 모듈이 진다)
    raise RuntimeError(f"blocker 어휘에 없는 어포던스 선언: {_undeclared}")
_missing = sorted(set(BLOCKER_CODES) - set(_TABLE))
if _missing:  # pragma: no cover
    raise RuntimeError(f"어포던스 선언이 없는 blocker: {_missing}")

#: blocker 코드 → 어포던스 선언. 어휘 정본(`BLOCKER_CODES`) 순서를 그대로 따른다.
BLOCKER_AFFORDANCES: Mapping[str, BlockerAffordance] = MappingProxyType(
    {code: _TABLE[code] for code in BLOCKER_CODES}
)


def managed_primary_action_controls() -> "dict[str, str]":
    """Primary Action → 그것을 푸는 화면 셀렉터 — **이 표에서 파생**(#912 D6).

    실창 대본(`scripts/live101/scenario.py`)이 관리 검토 사슬을 걸을 때 쓰던 사설 매핑표를
    대체한다. 그 표는 정본과 결속이 없어 거짓 항목을 실었다:
    ``RESOLVE_RUNTIME_POLICY → #jobResolveExecution`` — 그 조합에서는 확인 동사가 렌더되지
    않는다(runtime/policy 는 :data:`NO_VERB_BY_DESIGN` 이다). 파생으로 바꾸면 그 항목은
    **만들어질 수 없다**: 동사 없는 형태는 셀렉터를 갖지 않기 때문이다.

    접힘(여러 blocker → 하나의 Primary Action)은 어휘 정본의 사슬을 그대로 읽는다. 같은
    Primary Action 에 형태가 갈리는 blocker 들이 접힐 때(확인 축의 NO_EVIDENCE/STALE 은 동사,
    CHECKING 은 자동 진행) **활성 동사 쪽 셀렉터**를 낸다 — 대본이 겨누는 것은 누를 자리다.
    서로 다른 셀렉터가 한 Primary Action 에 접히면 시끄럽게 거절한다(조용한 승자 금지).

    접힘 규칙을 여기서 재구현하지 않는다 — blocker 하나만 담은 집합을
    :func:`~hwpxfiller.application.document_creation_workbench.compose_primary_action` 에 넣어
    **정본이 고르게** 한다. 우선순위 사슬이 바뀌면 이 파생도 같이 따라간다.
    """
    from ..application.document_creation_workbench import compose_primary_action

    controls: "dict[str, str]" = {}
    for blocker_code, affordance in BLOCKER_AFFORDANCES.items():
        if affordance.kind != ACTIVE_VERB or affordance.selector is None:
            continue
        action_code = compose_primary_action((blocker_code,))
        seated = controls.get(action_code)
        if seated is not None and seated != affordance.selector:
            raise RuntimeError(
                f"Primary Action {action_code!r} 에 셀렉터 둘이 접힙니다:"
                f" {seated!r} vs {affordance.selector!r}"
            )
        controls[action_code] = affordance.selector
    return controls


__all__ = [
    "ACTIVE_VERB",
    "AUTOMATIC_PROGRESS",
    "NO_VERB_BY_DESIGN",
    "AFFORDANCE_KINDS",
    "BlockerAffordance",
    "BLOCKER_AFFORDANCES",
    "managed_primary_action_controls",
]
