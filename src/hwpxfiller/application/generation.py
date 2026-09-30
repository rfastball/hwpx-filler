"""생성 run lifecycle 의 Application facts (P2-23 #571 · #1081 PR3).

생성의 척추(봉인 → 레코드 검증 → 배달 계획 → materialization → 배달)는 managed 파이프라인
(:mod:`hwpxfiller.external.managed_generation`)이 소유한다. GUI 와 CLI 가 같은 파이프라인을
부르며, 종전 legacy 척추(``plan_generation``·``direct_plan``·``run_generation`` →
``hwpxfiller.batch``)는 #1081 PR3 에서 퇴역했다.

여기 남는 것은 run 1회의 상태 정본(주체·판본·규칙 고정 + cancel event + token)과 그 결과
분류 facts(결과 3태·완주 술어·미입력 표식 결정)다. 한국어 요약 문장·버튼 문구는
Presentation 잔류다 — 여기는 수치·상태 facts 만 낸다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from ..domain.job import MISSING_MARKER, Job, rules_fingerprints


def blank_marker(blanks: "list[str] | tuple[str, ...]") -> str:
    """미입력 표식 결정의 **단일 출처**(U2 §2.13) — 조건은 「빈 값이 있으면」 하나다.

    종전에 컨트롤러 안 4자리에 흩어져 있던 같은 식(census #568 원자재 ③-4)의 정본.
    표시용 소비자(:meth:`~hwpxfiller.webapp.screen_job.JobController._run_marker` 등)도
    이 함수를 참조한다 — 조건이 자리마다 갈리면 각각 다른 실행 입력을 그리거나
    승인하게 된다.
    """
    return MISSING_MARKER if blanks else ""


def run_status(succeeded: int, total: int, cancelled: bool = False) -> str:
    """결과 3태 분류 facts(계약 §10 · 지도 §10.10 판정 A) — 성공/전체 + 중단의 함수.

    불변식 §13-10("일부 성공을 전체 성공으로 표시하지 않는다"): 전건 성공만
    ``completed``, 1건이라도 성공했고 남은 게 있으면 ``partiallyCompleted``, 성공
    0건은 ``failed``. **취소는 네 번째 태가 아니라** ``partiallyCompleted`` 의
    변종이다 — 첫 레코드 전에 멈춘 런은 성공 0·실패 0인데 성공 수만 보면 ``failed``
    가 되어 없던 실패를 지어낸다(1R P2). 표면은 이 판정을 재계산하지 않는다
    (제목·요약 **문안**은 Presentation 소유 — 여기는 태 facts 만).
    """
    if cancelled:
        return "partiallyCompleted"
    if total > 0 and succeeded >= total:
        return "completed"
    if succeeded > 0:
        return "partiallyCompleted"
    return "failed"


def run_completed(cancelled: bool, failed: int) -> bool:
    """완주 술어의 **단일 출처** — 취소 없이 전건 성공(#129).

    완주는 두 소비자(가드 무장 해제·``last_run_at`` 스탬프)가 **같은 사건**을 봐야
    한다 — 술어가 둘로 갈라지면 홈 이력과 가드가 서로 다른 실행을 완료로 부른다.
    종전 컨트롤러 안 물리 중복 2자리(census #568 원자재 ③-7)의 정본.
    """
    return not cancelled and failed == 0


@dataclass
class GenerationRun:
    """장기 run 1회의 상태 정본 — 주체·판본·규칙 고정 + cancel event + run token.

    **screen/controller 수명과 독립**이다(#571 불변식): 컨트롤러는 이 객체의 핸들을
    쥐고 취소 요청·진행 라벨 조회(transport)만 한다. 시작 시점 고정(#302 P1·§13-7):
    생성 중 작업 전환·에디터 저장이 세션을 갈아끼워도 이 run 의 주체·판본·규칙
    지문은 변하지 않는다 — 완주 스탬프가 남의 작업에 역사를 적지 않는 근거.
    """

    job_name: str = ""
    revisions: "dict[str, int]" = field(default_factory=dict)
    rules: "dict[str, str] | None" = None
    token: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)

    def request_cancel(self) -> None:
        """협조적 취소 요청(RC-06) — 진행 중 문서는 완결하고 레코드 경계에서 멈춘다."""
        self.cancel.set()


def start_run(job: "Job | None", *, job_name: str = "", token: str = "") -> GenerationRun:
    """run 시작 시점에 주체 identity·Template/Binding 판본·규칙 지문을 고정한다.

    ``job`` 이 없으면(작업 정체 없는 실행 — CLI) 빈 판본·규칙 없음으로 시작한다 —
    판본을 **모르면 모른다고 한다**(F5 판정 N 동형: 기본값 ``r1`` 을 채우지 않는다).
    """
    if job is None:
        return GenerationRun(job_name=job_name, token=token)
    return GenerationRun(
        job_name=job_name or job.name,
        revisions={"template": job.template_revision, "binding": job.binding_revision},
        rules=rules_fingerprints(job),
        token=token,
    )
