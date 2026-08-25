"""온보딩 튜토리얼의 **진행 감지 체크리스트** 링1 코어 — 슬라이스 D(#893).

정본은 :doc:`docs/ONBOARDING_TUTORIAL.md` §1 D3(체크리스트 + 순간 카드)·§3.3–3.6(티어·단계
판정표)·§4.3–4.4(구현 좌표·영속)다. 이 모듈이 소유하는 것은 셋이다.

1. **단계·티어 구조** — T0~T18 과 기본/응용/고급/심화 4티어. 티어 졸업·다음 티어 제안·
   전체 완주 판정이 여기 한 곳에서만 난다("같은 상태를 두 곳이 판정하지 않는다").
2. **문안** — 단계별 제목 한 줄·다음 걸음 한 줄·순간 카드 문안(:attr:`TutorialStep.
   moment_copy`). 링2 는 이 문자열을 그리기만 하고 다시 조립하지 않는다.
3. **달성 집합** — :meth:`TutorialViewModel.notify` 로 들어온 사실의 기록.

## 판정하지 않는 것 — notify 는 사실의 입구다

각 단계의 달성 조건(§3.3–3.6 표의 「달성 판정」)은 **컨트롤러의 기존 전이 지점**에서 이미
성립한다: 작업 저장, 데이터 마운트, 승인 전이, 생성 완료, 복사 카운트, compile 성립. 링1 은
그 전이를 재판정하지 않고 통지받은 마일스톤을 기록만 한다. 재판정을 여기 두면 같은 사실을
두 곳이 판정하게 되고, 링2 가 조건을 조금 다르게 조립하는 순간 체크가 조용히 어긋난다.

그래서 이 모듈은 파일도 설정도 읽지 않는다(Qt-free · DOM-free · IO 0). 영속은 값으로만
드나든다: 부팅 때 :meth:`TutorialViewModel.from_progress` 로 넣고, 변화 후
:meth:`TutorialViewModel.progress` 가 낸 값을 컨트롤러가
:func:`hwpxfiller.external.settings.save_tutorial_progress` 로 저장한다.

## 비차단·순서 비강제

단계는 달성 사실만 체크한다. 뒤 단계가 먼저 통지돼도 그대로 기록하고(선행 단계를 자동으로
채우지 않는다 — 하지 않은 일을 했다고 말하지 않는다), 같은 마일스톤의 중복 통지는 무해하다.

## 시작·종료·재개

**명시 시작**은 예제 설치(:attr:`Milestone.INSTALL_EXAMPLES`)다. 그 전에 도착한 통지도
기록은 되지만 표면은 서지 않는다 — 튜토리얼을 시작한 적 없는 사용자의 평소 사용이 패널을
불러내면 안 된다. **명시 종료**는 :meth:`TutorialViewModel.dismiss`, 되돌리기는
:meth:`TutorialViewModel.resume` 다.

닫힌 동안의 통지는 **기록하되 순간 카드를 큐에 넣지 않는다**(설계 결정): 기록을 멈추면
재개했을 때 그동안의 진행이 통째로 거짓이 되고, 카드를 큐에 넣으면 닫아 둔 사용자에게
재개 순간 밀린 카드가 쏟아진다.

## 순간 카드 큐

큐에는 **이 세션에서 새로 달성된** 단계만 들어간다. 영속에서 복원한 달성은 이미 지나간
사실이라 큐에 넣지 않는다(부팅 때마다 옛 카드가 다시 뜨지 않게). 동시 1장·억제(확인 모달
표시 중)·자동 소멸은 표면의 몫이라 링1 은 **미소비 카드 목록**만 낸다 — 표면이 한 장을 띄우고
:meth:`TutorialViewModel.consume_moment` 로 소비를 되알린다. 놓친 문안은 사라지지 않는다:
같은 ``moment_copy`` 가 체크리스트의 완료 단계 펼침에 그대로 남는다(§1 D3).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from ..domain.job import MISSING_MARKER

#: 스냅샷 형상의 이름표 — 소비자가 형상을 되묻지 않고 분기할 수 있게 값에 박는다.
_SNAPSHOT_KIND = "tutorial-checklist/v1"


class Tier(StrEnum):
    """루프 커리큘럼의 티어(§3.1 원칙 2 — 문서가 선언한 반복 빈도 서열)."""

    BASIC = "basic"
    APPLIED = "applied"
    ADVANCED = "advanced"
    DEEP = "deep"


class Milestone(StrEnum):
    """단계 열거 — §3.3–3.6 표의 「달성 판정」과 1:1.

    값(``T0``…``T18``)이 곧 영속·스냅샷의 식별자다. 컨트롤러는 이 열거로만 통지한다.
    """

    INSTALL_EXAMPLES = "T0"
    PICK_TEMPLATE = "T1"
    CONFIRM_MAPPING = "T2"
    SAVE_JOB = "T3"
    MOUNT_DATA = "T4"
    SELECT_ROWS = "T5"
    APPROVE_VALUES = "T6"
    GENERATE = "T7"
    SECOND_LAP = "T8"
    SWITCH_JOB = "T9"
    SAVE_TXT_JOB = "T10"
    COPY_DRAFT = "T11"
    REPLACE_DATA = "T12"
    APPROVE_WITH_BLANKS = "T13"
    CONFIRM_EMPTY_FIELD = "T14"
    COMPILE_TEMPLATE = "T15"
    GENERATE_FROM_COMPILED = "T16"
    TOGGLE_SECTION = "T17"
    SWITCH_OPTION = "T18"


@dataclass(frozen=True)
class TutorialStep:
    """단계 하나의 정의 — 판정 재료가 아니라 **이름과 문안**이다.

    - ``title`` — 체크리스트 한 줄의 제목.
    - ``next_step`` — 아직 달성 전인 단계의 다음 걸음 한 줄(행동 전 안내).
    - ``moment_copy`` — 달성 직후 순간 카드가 말할 '방금 걸음의 의미'(행동 후 의미 부여).
      완료 단계를 펼쳤을 때도 같은 문안이 남는다.
    """

    milestone: Milestone
    tier: Tier
    title: str
    next_step: str
    moment_copy: str


@dataclass(frozen=True)
class TierDefinition:
    """티어 하나의 정의 — 이름·소속 단계·졸업 문안·진입 제안 문안.

    ``optional`` 인 티어(심화)는 표준 완주에 들지 않는다. 표준 완주는 고급까지다(§3.6).
    """

    tier: Tier
    label: str
    title: str
    graduation_copy: str
    invitation: str
    optional: bool = False


STEPS: "tuple[TutorialStep, ...]" = (
    TutorialStep(
        milestone=Milestone.INSTALL_EXAMPLES,
        tier=Tier.BASIC,
        title="예제 설치",
        next_step="'문서 작업'의 빈 목록에서 '예제로 시작하기'를 누르세요.",
        moment_copy=(
            "예제 서식과 데이터가 들어왔습니다. 연습용 환경이 아니라 평소 쓰는 화면 그대로입니다."
        ),
    ),
    TutorialStep(
        milestone=Milestone.PICK_TEMPLATE,
        tier=Tier.BASIC,
        title="템플릿 고르기",
        next_step="'새 작업'에서 '계약체결안내'를 '이 템플릿으로' 고르세요.",
        moment_copy="템플릿의 필드가 그대로 올라왔습니다. 다음은 필드마다 데이터 열을 지정합니다.",
    ),
    TutorialStep(
        milestone=Milestone.CONFIRM_MAPPING,
        tier=Tier.BASIC,
        title="데이터 열 연결",
        next_step="데이터 파일로 '계약목록.csv'를 고르고 필드마다 데이터 열을 확정하세요.",
        moment_copy=(
            "헤더 이름이 필드와 같아 자동으로 제안됐습니다. 확정은 검토를 대신하지 않습니다."
        ),
    ),
    TutorialStep(
        milestone=Milestone.SAVE_JOB,
        tier=Tier.BASIC,
        title="작업 저장",
        next_step="작업 이름과 파일명 규칙을 정하고 '작업 저장'을 누르세요.",
        moment_copy="정의는 한 번입니다. 이제 데이터만 바꿔 몇 번이든 다시 만듭니다.",
    ),
    TutorialStep(
        milestone=Milestone.MOUNT_DATA,
        tier=Tier.BASIC,
        title="데이터 연결",
        next_step="'문서 만들기'에서 이번에 쓸 데이터를 고르세요.",
        moment_copy="데이터가 화면에 올라왔습니다. 다음 실행부터는 마지막 데이터가 자동으로 올라옵니다.",
    ),
    TutorialStep(
        milestone=Milestone.SELECT_ROWS,
        tier=Tier.BASIC,
        title="작업과 행 선택",
        next_step="작업 카드를 고르고 '전체 선택'으로 만들 행을 선택하세요.",
        moment_copy="고른 행만 만듭니다. 선택은 데이터를 바꾸기 전까지 그대로 남습니다.",
    ),
    TutorialStep(
        milestone=Milestone.APPROVE_VALUES,
        tier=Tier.BASIC,
        title="이름과 값 승인",
        next_step="만들 이름과 값을 확인하고 '이 이름과 값으로 승인'을 누르세요.",
        moment_copy="승인이 생성을 열었습니다. 무엇이 어떤 이름으로 나가는지 먼저 보고 확정합니다.",
    ),
    TutorialStep(
        milestone=Milestone.GENERATE,
        tier=Tier.BASIC,
        title="문서 생성",
        next_step="'이 작업으로 문서 생성'을 누르세요.",
        moment_copy="첫 문서가 만들어졌습니다. 같은 작업으로 한 바퀴 더 돌면 리듬이 손에 붙습니다.",
    ),
    TutorialStep(
        milestone=Milestone.SECOND_LAP,
        tier=Tier.BASIC,
        title="한 바퀴 더",
        next_step="같은 작업으로 다시 생성하고 '덮어쓰고 생성'으로 확인하세요.",
        moment_copy=(
            "이번에는 승인을 묻지 않았습니다. 규칙 승인은 작업당 한 번이고, "
            "같은 이름의 파일만 덮기 전에 확인을 받습니다."
        ),
    ),
    TutorialStep(
        milestone=Milestone.SWITCH_JOB,
        tier=Tier.APPLIED,
        title="작업 전환",
        next_step="데이터를 그대로 둔 채 '구매추진안내'로 두 번째 작업을 만들어 생성하세요.",
        moment_copy=(
            "데이터를 다시 고르지 않았습니다. 데이터는 작업이 아니라 화면이 들고 있습니다."
        ),
    ),
    TutorialStep(
        milestone=Milestone.SAVE_TXT_JOB,
        tier=Tier.APPLIED,
        title="TXT 작업 저장",
        next_step="'계약안내_기안'으로 TXT 작업을 저장하세요.",
        moment_copy="같은 데이터가 TXT 산출도 냅니다. TXT는 파일 대신 복사로 건넵니다.",
    ),
    TutorialStep(
        milestone=Milestone.COPY_DRAFT,
        tier=Tier.APPLIED,
        title="검토와 복사",
        next_step="작업대에서 행을 넘기며 '복사'를 누르세요.",
        moment_copy="복사가 곧 완료 표시입니다. 남은 행은 목록이 계속 셉니다.",
    ),
    TutorialStep(
        milestone=Milestone.REPLACE_DATA,
        tier=Tier.APPLIED,
        title="데이터 교체",
        next_step="'계약목록_2.csv'로 데이터를 바꾸세요.",
        moment_copy=(
            "데이터를 바꾸자 선택이 0건에서 다시 시작했습니다. "
            "앞 데이터의 선택을 새 행에 물려주지 않습니다."
        ),
    ),
    TutorialStep(
        milestone=Milestone.APPROVE_WITH_BLANKS,
        tier=Tier.APPLIED,
        title="빈 값 포함 승인",
        next_step="빈 값이 있는 행을 선택하고 지목된 '납품기한'을 확인한 뒤 다시 승인하세요.",
        moment_copy=(
            "이번 실행에 빈 값이 있어 승인이 다시 섰습니다. "
            f"빈 값은 빈칸으로 새지 않고 {MISSING_MARKER.format(field='납품기한')} 표식으로 남습니다."
        ),
    ),
    TutorialStep(
        milestone=Milestone.CONFIRM_EMPTY_FIELD,
        tier=Tier.APPLIED,
        title="비움 확정",
        next_step="'오류연습_보증금' TXT 작업을 저장하며 비움 확정을 지나세요.",
        moment_copy=(
            "데이터에 열 자체가 없는 항목은 저장할 때 한 번 비움을 확정합니다. "
            "값이 빈 것과 열이 없는 것은 확인받는 자리가 다릅니다."
        ),
    ),
    TutorialStep(
        milestone=Milestone.COMPILE_TEMPLATE,
        tier=Tier.ADVANCED,
        title="누름틀 변환",
        next_step="'공고서_연습' 행의 더보기에서 누름틀 변환을 확인하세요.",
        moment_copy="타이핑한 서식이 템플릿이 됐습니다. 필드 토큰과 구간 표기를 함께 지났습니다.",
    ),
    TutorialStep(
        milestone=Milestone.GENERATE_FROM_COMPILED,
        tier=Tier.ADVANCED,
        title="변환본으로 생성",
        next_step="변환된 템플릿으로 작업을 만들고 문서를 생성하세요.",
        moment_copy=(
            "변환의 출구가 첫 티어의 입구였습니다. "
            "이제 당신의 서식 파일을 '가져오기…'로 들여와 같은 변환을 하세요."
        ),
    ),
    TutorialStep(
        milestone=Milestone.TOGGLE_SECTION,
        tier=Tier.DEEP,
        title="항목 넣고 빼기",
        next_step="'포함할 내용'에서 항목 하나를 빼고 다시 승인해 생성하세요.",
        moment_copy=(
            "구성을 바꾸자 승인이 다시 섰습니다. "
            "규칙이 갈리면 확인을 받는다는 그 규칙이 그대로 선 것입니다."
        ),
    ),
    TutorialStep(
        milestone=Milestone.SWITCH_OPTION,
        tier=Tier.DEEP,
        title="선택 갈래 바꾸기",
        next_step="선택 구간의 갈래를 바꿔 생성하세요.",
        moment_copy="서식이 갈라질 이유가 한 벌 안으로 접혔습니다. 갈래를 바꿔도 작업은 하나입니다.",
    ),
)

TIERS: "tuple[TierDefinition, ...]" = (
    TierDefinition(
        tier=Tier.BASIC,
        label="기본",
        title="첫 문서",
        graduation_copy="이 작업으로 언제든 다시 만들 수 있습니다.",
        invitation="예제 서식과 데이터로 첫 문서를 만듭니다. 15분이면 충분합니다.",
    ),
    TierDefinition(
        tier=Tier.APPLIED,
        label="응용",
        title="한 데이터로 여러 산출, 그리고 새 데이터",
        graduation_copy="데이터가 바뀌어도, 산출이 여러 가지여도 리듬은 같습니다.",
        invitation="연결한 데이터를 그대로 두고 산출을 늘려 봅니다. 데이터 교체도 여기서 만납니다.",
    ),
    TierDefinition(
        tier=Tier.ADVANCED,
        label="고급",
        title="내 서식",
        graduation_copy="당신의 서식을 가져와 같은 변환을 할 수 있습니다.",
        invitation="직접 쓴 서식을 템플릿으로 바꿉니다. 이 앱을 당신의 문서에 쓰는 길입니다.",
    ),
    TierDefinition(
        tier=Tier.DEEP,
        label="심화",
        title="구간: 서식 여러 벌을 한 벌로",
        graduation_copy="서식이 갈라질 이유가 구간으로 접힙니다.",
        invitation=(
            "거의 같은 서식이 여러 벌로 갈라져 있다면, 구간이 그것을 한 벌로 만듭니다. "
            "고르지 않아도 됩니다."
        ),
        optional=True,
    ),
)

#: 마일스톤 → 단계 정의. 열거와 정의표가 어긋나면 이 dict 가 짧아진다(테스트가 센다).
_STEP_BY_MILESTONE: "dict[Milestone, TutorialStep]" = {step.milestone: step for step in STEPS}

#: 티어 → 소속 단계(표 순서 유지).
_STEPS_BY_TIER: "dict[Tier, tuple[TutorialStep, ...]]" = {
    definition.tier: tuple(step for step in STEPS if step.tier == definition.tier)
    for definition in TIERS
}


def _coerce(milestone: "Milestone | str") -> Milestone:
    """통지 인자를 열거로 정규화 — 모르는 값은 조용히 무시하지 않고 ``ValueError``.

    통지는 컨트롤러 배선의 산물이라 오타는 사용자 입력이 아니라 결함이다. 조용히 흘리면
    영영 체크되지 않는 단계가 생기고 그 침묵은 화면에서 구분되지 않는다(confirm-or-alarm).
    """
    try:
        return Milestone(milestone)
    except ValueError:
        raise ValueError(f"알 수 없는 튜토리얼 단계: {milestone!r}") from None


class TutorialViewModel:
    """진행 감지 체크리스트의 상태 모델(링1).

    슬라이스 E(표면·배선)가 쓰는 공개 API 는 다음이 전부다.

    - :meth:`from_progress` / :meth:`progress` — 영속 왕복. 값만 주고받고 이 모듈은
      ``settings`` 를 import 하지 않는다.
    - :meth:`notify` — 이미 성립한 전이 사실의 통지. 새로 기록됐으면 ``True``.
    - :meth:`dismiss` / :meth:`resume` — 명시 종료·재개.
    - :meth:`pending_moments` / :meth:`consume_moment` — 순간 카드 큐(동시 1장은 표면 몫).
    - :meth:`snapshot` — JSON-safe 스냅샷. 링2 는 이것만 그린다.
    """

    def __init__(
        self,
        *,
        achieved: "Iterable[str] | None" = None,
        dismissed: bool = False,
    ) -> None:
        """영속에서 복원한 값으로 상태를 세운다.

        ``achieved`` 의 모르는 식별자는 걸러낸다 — 옛 버전이 남긴 죽은 단계 키가 부팅을
        막지 않는다(설정 판독의 부분 손상 관용 전례와 동형). 통지(:meth:`notify`)의 오타는
        배선 결함이라 반대로 loud 다.
        """
        self._achieved: "set[Milestone]" = set()
        for raw in achieved or ():
            try:
                self._achieved.add(Milestone(raw))
            except ValueError:
                continue
        self._dismissed = bool(dismissed)
        self._pending: "list[Milestone]" = []  # 이 세션에서 새로 달성된 것만

    @classmethod
    def from_progress(cls, progress: "dict | None") -> "TutorialViewModel":
        """``load_tutorial_progress()`` 산출 형상(``{"achieved", "dismissed"}``)에서 복원."""
        data = progress if isinstance(progress, dict) else {}
        raw = data.get("achieved")
        return cls(
            achieved=raw if isinstance(raw, list) else (),
            dismissed=bool(data.get("dismissed")),
        )

    def progress(self) -> "dict":
        """영속할 값 — ``save_tutorial_progress(**vm.progress())`` 로 그대로 넘어간다.

        달성 목록은 표 순서(T0…T18)로 정규화한다 — 통지 순서가 파일 diff 를 흔들지 않게.
        """
        return {
            "achieved": [str(step.milestone) for step in STEPS if step.milestone in self._achieved],
            "dismissed": self._dismissed,
        }

    def notify(self, milestone: "Milestone | str") -> bool:
        """이미 성립한 전이 사실을 기록한다 — 새로 기록됐으면 ``True``.

        재판정하지 않는다. 순서를 강제하지 않고(뒤 단계가 먼저 와도 그대로 기록하며 앞
        단계를 자동으로 채우지 않는다), 중복 통지는 무해하다(``False`` 만 낸다).

        닫힌 동안에도 기록은 한다. 다만 순간 카드는 큐에 넣지 않는다 — 닫아 둔 사용자가
        재개하는 순간 밀린 카드가 쏟아지지 않게(모듈 docstring의 설계 결정).
        """
        step = _coerce(milestone)
        if step in self._achieved:
            return False
        self._achieved.add(step)
        if not self._dismissed:
            self._pending.append(step)
        return True

    def dismiss(self) -> None:
        """명시 종료 — 표면을 내리고 대기 중인 순간 카드를 버린다."""
        self._dismissed = True
        self._pending.clear()

    def resume(self) -> None:
        """재개 — 달성 기록은 그대로 살아 있으므로 진행은 이어진다."""
        self._dismissed = False

    @property
    def dismissed(self) -> bool:
        return self._dismissed

    @property
    def started(self) -> bool:
        """명시 시작 여부 — 예제 설치가 곧 시작이다(§1 D3)."""
        return Milestone.INSTALL_EXAMPLES in self._achieved

    @property
    def active(self) -> bool:
        """표면이 설 조건 — 시작했고 닫히지 않았다."""
        return self.started and not self._dismissed

    def is_achieved(self, milestone: "Milestone | str") -> bool:
        return _coerce(milestone) in self._achieved

    def tier_complete(self, tier: "Tier | str") -> bool:
        """티어 졸업 — 그 티어의 전 단계가 달성됐다(§3.3–3.6 졸업 판정)."""
        return all(step.milestone in self._achieved for step in _STEPS_BY_TIER[Tier(tier)])

    @property
    def standard_complete(self) -> bool:
        """표준 완주 — 선택 진입인 심화를 뺀 세 티어가 모두 졸업(§3.6)."""
        return all(
            self.tier_complete(definition.tier) for definition in TIERS if not definition.optional
        )

    @property
    def all_complete(self) -> bool:
        """전체 완주 — 심화까지 포함해 T0~T18 이 모두 달성."""
        return len(self._achieved) == len(STEPS)

    @property
    def suggested_tier(self) -> str:
        """다음에 제안할 티어 — **비강제**(막지 않고 권하기만 한다).

        아직 졸업하지 못한 첫 티어이고, 전부 졸업했으면 빈 문자열이다. 심화는 앞 세 티어를
        졸업한 뒤에야 제안 자리에 온다(선택 진입).
        """
        for definition in TIERS:
            if not self.tier_complete(definition.tier):
                return str(definition.tier)
        return ""

    def pending_moments(self) -> "tuple[Milestone, ...]":
        """아직 표면이 띄우지 않은 순간 카드 — 달성 순서."""
        return tuple(self._pending)

    def consume_moment(self, milestone: "Milestone | str") -> bool:
        """순간 카드 한 장을 소비 처리 — 큐에 있었으면 ``True``.

        표면이 한 장을 띄운 뒤 되알린다(동시 1장·억제·자동 소멸은 표면 몫). 소비해도 문안은
        사라지지 않는다 — 체크리스트의 완료 단계 펼침에 같은 ``moment_copy`` 가 남는다.
        """
        step = _coerce(milestone)
        if step not in self._pending:
            return False
        self._pending.remove(step)
        return True

    def snapshot(self) -> "dict":
        """JSON-safe 스냅샷 — 링2 는 이 값을 그리기만 한다.

        키:

        - ``kind`` — 스냅샷 형상 이름표.
        - ``started``/``active``/``dismissed`` — 시작·표면 노출·닫힘 상태.
        - ``achieved_count``/``step_count`` — 전체 진행 수치.
        - ``standard_complete``/``all_complete`` — 표준 완주(고급까지)·전체 완주.
        - ``suggested_tier`` — 다음 제안 티어 식별자(없으면 ``""``).
        - ``tiers`` — 티어별 ``{tier,label,title,optional,complete,graduation_copy,
          invitation,achieved_count,step_count,steps}``. ``steps`` 항목은
          ``{milestone,title,next_step,moment_copy,achieved}``.
        - ``moment_queue`` — 미소비 카드 ``{milestone,title,moment_copy}`` 목록(달성 순서).
        """
        return {
            "kind": _SNAPSHOT_KIND,
            "started": self.started,
            "active": self.active,
            "dismissed": self._dismissed,
            "achieved_count": len(self._achieved),
            "step_count": len(STEPS),
            "standard_complete": self.standard_complete,
            "all_complete": self.all_complete,
            "suggested_tier": self.suggested_tier,
            "tiers": [self._tier_snapshot(definition) for definition in TIERS],
            "moment_queue": [
                {
                    "milestone": str(step),
                    "title": _STEP_BY_MILESTONE[step].title,
                    "moment_copy": _STEP_BY_MILESTONE[step].moment_copy,
                }
                for step in self._pending
            ],
        }

    def _tier_snapshot(self, definition: TierDefinition) -> "dict":
        steps = _STEPS_BY_TIER[definition.tier]
        return {
            "tier": str(definition.tier),
            "label": definition.label,
            "title": definition.title,
            "optional": definition.optional,
            "complete": self.tier_complete(definition.tier),
            "graduation_copy": definition.graduation_copy,
            "invitation": definition.invitation,
            "achieved_count": sum(1 for step in steps if step.milestone in self._achieved),
            "step_count": len(steps),
            "steps": [
                {
                    "milestone": str(step.milestone),
                    "title": step.title,
                    "next_step": step.next_step,
                    "moment_copy": step.moment_copy,
                    "achieved": step.milestone in self._achieved,
                }
                for step in steps
            ],
        }
