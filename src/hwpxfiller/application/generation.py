"""생성 transaction·run lifecycle 의 Application use case (P2-23 #571).

생성의 **척추**(입력 고정 → 게이트 판정 → plan → materialize → progress/cancel →
완주 판정 → durable completion 기록 → stable result facts)를 한 곳이 소유한다.
GUI(:mod:`~hwpxfiller.webapp.screen_job`)와 CLI(:mod:`~hwpxfiller.cli`)는 같은
use case 를 **각자의 게이트 선언**으로 부른다 — 게이트 판정 입력(검토 요구·빈값
처리·덮어쓰기 확정)은 호출자가 명시 선언해 넘기는 facts 다. CLI 생성 경로의 현
의미(검토 게이트 없음·빈값 기본 차단+``--ack-empty``·완주 스탬프 없음·취소 없음)는
**의도된 제품 계약**이라 CLI 는 그 부재를 인자 생략이 아니라 선언(``store=None``·
``review_check=None``)으로 말한다.

:mod:`hwpxfiller.batch` 와 :mod:`hwpxfiller.gui.run_state` 는 ring 계약
(`docs/module_rings.toml`)이 APPLICATION 으로 판정한 동륜이라 직접 소비가 합법이다.
엔진(zip IO 결속)은 Host/ring 2 가 인자로 관통시킨다 — Application 은 concrete
opener 를 모른다(P2-19 와 같은 seam). 시각도 같다: 이 모듈은 wall clock 을 직접
고르지 않고 ``now``/``completed_at`` 을 호출자가 선언한다(boundary 게이트).

한국어 요약 문장·버튼 문구·모달 구성은 Presentation 잔류다 — 여기는 수치·상태
facts 만 낸다(제목 :func:`~hwpxfiller.webapp.screen_job._run_title` 류의 문안
oracle 은 종전 owner 그대로 산다).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..batch import generate_batch
from ..core.job import MISSING_MARKER, Job, rules_fingerprints
from ..gui.run_state import GenerationPlan
from .jobs import JobStorePort, stamp_run_completion

if TYPE_CHECKING:
    from datetime import datetime

    from ..gui.run_state import GateError, RunViewModel


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


@dataclass(frozen=True)
class PlanDecision:
    """게이트 판정 1회의 facts — 거절·검토 미충족·덮어쓰기 확인 필요·확정 plan 중 하나.

    문안 조립(거절 재진술·모달 수치 합성)은 Presentation 몫이고 여기는 사실만 싣는다.
    ``rejection`` 은 링1 :class:`~hwpxfiller.gui.run_state.GateError` 관통(판정·문안
    모두 링1 소유 — 재조립 금지), ``review_unmet`` 은 호출자가 선언한 검토 판정기가
    돌려준 값을 **불투명하게** 되돌린다(Application 은 검토 문안·지문 구조를 모른다).
    """

    plan: "GenerationPlan | None" = None
    rejection: "GateError | None" = None
    review_unmet: Any = None
    blanks: "tuple[str, ...]" = ()
    marker: str = ""
    conflicts: "tuple[str, ...]" = ()
    needs_overwrite: bool = False


def plan_generation(
    vm: "RunViewModel",
    indices: "list[int]",
    out_dir: str,
    *,
    now: "datetime",
    review_check: "Callable[[list[str]], Any] | None" = None,
    confirm_overwrite: bool = False,
) -> PlanDecision:
    """실행 요청의 유효성 판정 **순서**와 게이트 facts — confirm-or-alarm 순서 보존.

    순서는 현행 제품 계약 그대로다: ①기본 가드(링1 ``validate_generate`` 단일 판정)
    → ②빈 값 집합(표식·승인 백스톱이 같은 집합 소비, §2.13 단일 술어) → ③검토
    백스톱(버튼이 이미 비활성이어도 다시 묻는다 — 1R P1) → ④표식 결정 → ⑤덮어쓰기
    확인(RC-02: 확정 없이는 plan 을 짓지 않는다) → ⑥불변 생성 계획(RC-07).

    ``review_check`` 는 호출자가 선언한 게이트 fact 다: GUI 는 **이 런의 주체**로
    묻는 세션 판정기를 넘기고, CLI 는 ``None``(검토 게이트 없음 — 의도된 계약)을
    선언한다. ``now`` 는 날짜 토큰 기준 시각 — 확인이 조회한 대상과 실제 생성이
    같은 값을 쓰도록 호출자가 고정해 넘긴다(RC-02, 미리보기 핀은 호출자 소유).
    """
    errors = vm.validate_generate(indices, out_dir)
    if errors:
        return PlanDecision(rejection=errors[0])

    blanks = list(vm.blank_fields(indices))
    unmet = review_check(blanks) if review_check is not None else None
    if unmet is not None:
        return PlanDecision(review_unmet=unmet, blanks=tuple(blanks))

    marker = blank_marker(blanks)
    conflicts = vm.output_conflicts(indices, out_dir, mark_missing=marker, now=now)
    if conflicts and not confirm_overwrite:
        return PlanDecision(
            blanks=tuple(blanks), marker=marker,
            conflicts=tuple(conflicts), needs_overwrite=True,
        )
    plan = vm.build_generation_plan(
        indices, out_dir, marker=marker, overwrite=bool(conflicts), now=now
    )
    return PlanDecision(
        plan=plan, blanks=tuple(blanks), marker=marker, conflicts=tuple(conflicts),
    )


def direct_plan(
    template: str,
    records: "list[dict]",
    out_dir: str,
    pattern: str,
    *,
    marker: str = "",
    overwrite: bool = False,
    mapping: Any = None,
) -> "GenerationPlan":
    """VM 없는 호출자(CLI)의 불변 생성 계획 — 게이트는 호출자가 이미 스스로 선언·판정했다.

    CLI 는 검토 게이트·사전 덮어쓰기 확인이 **없는 것이 계약**이라 :func:`plan_generation`
    을 지나지 않는다. 그래도 materialize 가 소비하는 계획은 같은 형(RC-07 불변 스냅샷)
    이어야 한다 — 두 표면이 다른 입력 형으로 배치를 부르면 실행 의미가 갈라진다.
    ``now=None`` 은 날짜 토큰이 생성 시각을 쓴다는 뜻(현 CLI 의미 그대로)이다.
    """
    return GenerationPlan(
        template=template,
        records=tuple(records),
        out_dir=out_dir,
        pattern=pattern,
        marker=marker,
        indices=tuple(range(len(records))),
        source_pointer="",
        overwrite=overwrite,
        mapping=mapping,
    )


@dataclass(frozen=True)
class GenerationOutcome:
    """run 1회의 stable result facts — 표면(제목·요약·payload)은 이것만 소비한다.

    ``failed`` 는 취소 런에서 **시도분 중 실패**(attempted-succeeded)다 — 미착수를
    실패로 세지 않는다(취소 산술의 정본). ``error`` 는 배치 진입 전 실패(구조
    드리프트·산출물 충돌·폴더 오류)의 원본 예외 — 시도가 0 이므로 성공/실패로
    가르지 않고(같은 레코드를 두 번 세지 않는다) 사유 번역은 호출자 몫이다.
    ``stamp_error`` 는 완주 기록 실패의 loud surface(confirm-or-alarm) — 문서는
    이미 만들어졌으므로 예외로 완료 서사를 날리지 않고 사유를 facts 로 남긴다.
    """

    status: str
    cancelled: bool
    succeeded: int
    failed: int
    total: int
    attempted: int
    unstarted: int
    completed: bool
    stamp_error: str = ""
    stamped_job: "Job | None" = None
    results: "tuple[Any, ...]" = ()
    error: "BaseException | None" = None


def run_generation(
    run: GenerationRun,
    plan: "GenerationPlan",
    *,
    engine: Any,
    progress: "Callable[[int, int], None] | None" = None,
    capture: "tuple[type[BaseException], ...]" = (),
    store: "JobStorePort | None" = None,
    completed_at: "Callable[[], str] | None" = None,
) -> GenerationOutcome:
    """확정된 plan 의 materialize → 완주 판정 → durable completion 기록 → facts.

    ``capture`` 는 배치 진입 전 실패를 facts 로 회수할 예외 종류의 **호출자 선언**이다
    — GUI 는 ``(ValueError, OSError)`` 전체를 결과 구획으로 회수하고, CLI 는
    ``(OutputCollisionError, ValueError)`` 만 exit 1 로 다루며 환경성 OSError 를
    최상위 번역 경계(exit 2)로 흘린다(RC-16). 선언 밖 예외는 그대로 상승한다.

    완주(:func:`run_completed`)이고 ``store`` 가 선언됐을 때만
    :func:`~hwpxfiller.application.jobs.stamp_run_completion` 으로 기록한다 —
    기준선은 **이 run 이 고정한 규칙**(``run.rules``)이다(1R P1: 디스크의 지금
    규칙으로 찍으면 배치 중 착지한 에디터 저장이 실행된 적 없는 규칙을 검토받은
    것으로 만든다). ``store=None`` 은 「완주 스탬프 없음」의 명시 선언(CLI 계약)이다.
    """
    total = len(plan.records)
    if progress is not None:
        # 시작 델타(0/N) — 표면 진행바가 「시작했다」를 배치 첫 레코드 완료 전에 안다.
        progress(0, total)
    try:
        batch = generate_batch(
            plan.template, list(plan.records), plan.out_dir, plan.pattern, engine,
            now=plan.now, overwrite=plan.overwrite, mapping=plan.mapping,
            progress=progress, cancelled=run.cancel.is_set,
        )
    except capture as exc:
        return GenerationOutcome(
            status="failed", cancelled=False, succeeded=0, failed=total,
            total=total, attempted=0, unstarted=total, completed=False, error=exc,
        )

    # getattr 기본값은 종전 컨트롤러 계약 그대로다 — 배치 대역(테스트 fake)이 협조적
    # 취소 이전의 형(BatchResult 축소형)을 내도 「취소 없음·전건 시도」로 읽는다.
    cancelled = bool(getattr(batch, "cancelled", False))
    attempted = int(getattr(batch, "attempted", len(batch.results)))
    completed = run_completed(cancelled, batch.failed)
    stamp_error = ""
    stamped: "Job | None" = None
    if completed and store is not None:
        if completed_at is None:
            raise ValueError("완주 기록에는 completed_at 시각 선언이 필요합니다.")
        try:
            stamped = stamp_run_completion(
                store, run.job_name, completed_at(), rules=run.rules
            )
        except (OSError, ValueError) as exc:
            stamp_error = str(exc) or exc.__class__.__name__
    return GenerationOutcome(
        status=run_status(batch.succeeded, batch.total, cancelled),
        cancelled=cancelled,
        succeeded=batch.succeeded,
        failed=attempted - batch.succeeded if cancelled else batch.failed,
        total=batch.total,
        attempted=attempted,
        unstarted=batch.total - attempted,
        completed=completed,
        stamp_error=stamp_error,
        stamped_job=stamped,
        results=tuple(batch.results),
    )
