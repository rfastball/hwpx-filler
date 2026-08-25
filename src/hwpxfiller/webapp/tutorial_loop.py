"""튜토리얼 루프 감지의 **세션 이력 요약** — 슬라이스 E(#894).

화면 컨트롤러가 아니라 링2 값 타입이라 ``screen_*.py`` 밖에 산다. 그 배치는 취향이 아니라
계약이다: ``webapp/screen_*.py`` 는 서로를 직접 import 하지 않고(화면 간 위임은 조립부가
결선하는 callable 하나뿐), 그 음성 게이트는 모듈 이름의 ``screen_`` 접두로 판정한다
(:func:`tests.repo_contract.test_architecture.test_screen_controllers_stay_transport_thin`).
「문서 만들기」가 이 이력을 들어야 하므로 튜토리얼 컨트롤러 파일에 두면 그 간선이 생긴다.

## 왜 세션이 직접 세는가

§3.3 T8(같은 작업 2번째 생성)·§3.4 T9(같은 마운트 위 작업 전환)·§3.6 T17·T18(구간 구성
변화)의 달성 판정은 **생성 이력**인데, 앱은 그것을 어디에도 들고 있지 않다:

- :class:`~hwpxfiller.domain.job.Job` 은 ``last_run_at`` 한 칸이라 횟수를 세지 않는다.
- managed 배달 원장은 출력 폴더에 쌓이는 **쓰기 전용** 사이드카라 실행 시점에 되읽지 않는다.
- 「마운트가 바뀌었는가」를 말하는 플래그도 없다.

그래서 여기가 센다. **세는 것만** 한다 — 어느 T 인지의 의미는 호출자가 정한다. 여기서 T
번호를 알면 링2 가 커리큘럼을 두 번째로 판정하게 된다(판정 재구현 금지).
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["GenerationLoopFacts", "GenerationLoopLedger"]


@dataclass(frozen=True)
class GenerationLoopFacts:
    """생성 한 번이 이 세션의 이력에 비춰 무엇이었는가 — **사실이지 단계가 아니다**.

    어느 마일스톤인지의 의미는 호출자가 정한다. 여기서 T 번호를 알면 링2 컨트롤러가 커리큘럼
    을 두 번째로 판정하게 된다.
    """

    #: 같은 작업으로 이미 한 번 만든 적이 있다(§3.3 T8 「한 바퀴 더」의 사실 절반).
    repeat_job: bool
    #: 같은 마운트를 유지한 채 **다른 작업**으로 만든 적이 있다(§3.4 T9 작업 전환).
    other_job_same_mount: bool
    #: 같은 작업의 직전 실행과 견줘 **항목 구성**이 달라졌다(§3.6 T17).
    items_changed: bool
    #: 항목 구성은 같은데 **고른 갈래**가 달라졌다(§3.6 T18).
    options_changed: bool


@dataclass
class GenerationLoopLedger:
    """튜토리얼 루프 감지에 쓰는 **세션 이력 요약**(#894) — 판정이 아니라 기억이다.

    이 클래스가 있는 이유는 앱이 그 이력을 **어디에도 들고 있지 않기** 때문이다:
    :class:`~hwpxfiller.domain.job.Job` 은 ``last_run_at`` 한 칸뿐이라 횟수를 세지 않고,
    managed 배달 원장은 출력 폴더에 쌓이는 쓰기 전용 사이드카라 실행 시점에 되읽지 않으며,
    「마운트가 바뀌었는가」를 말하는 플래그도 없다. 그런데 §3.3 T8·§3.4 T9·§3.6 T17·T18 의
    달성 판정이 정확히 그 이력이다. 그래서 세션이 직접 센다 — **세는 것만** 한다.

    수명은 세션이다(앱 재시작에서 사라진다). 달성 자체는 링1 이 영속하므로 한 번 체크된
    단계가 재부팅으로 풀리지는 않는다. 다만 첫 바퀴와 두 번째 바퀴가 다른 세션으로 갈리면
    그 루프는 이 세션에서 완성된 것으로 보이지 않는다 — 「하지 않은 일을 했다고 말하지
    않는다」쪽으로 기운 의도된 보수성이다.
    """

    #: 이 세션에서 생성을 완주한 작업 이름.
    generated_jobs: "set[str]" = field(default_factory=set)
    #: 현재 마운트의 정체(교체되면 아래 집합을 비운다).
    mount_key: "str | None" = None
    #: 현재 마운트에서 생성을 완주한 작업 이름.
    mount_jobs: "set[str]" = field(default_factory=set)
    #: 이 세션에서 누름틀 변환된 템플릿 경로(정규화 없이 tpl 채널이 준 값 그대로).
    compiled_templates: "set[str]" = field(default_factory=set)
    #: 작업 이름 → 그 작업의 **직전 실행** 구간 구성.
    slot_shapes: "dict[str, dict[str, frozenset[str]]]" = field(default_factory=dict)

    def note_compiled(self, path: str) -> None:
        """누름틀 변환 성립을 기억한다 — T16 이 「변환본으로 만들었는가」를 묻는 재료."""
        self.compiled_templates.add(path)

    def was_compiled(self, path: str) -> bool:
        return bool(path) and path in self.compiled_templates

    def note_generated(
        self,
        job: str,
        *,
        mount_key: str,
        slot_shape: "dict[str, frozenset[str]] | None",
    ) -> GenerationLoopFacts:
        """생성 완주 하나를 기록하고 **기록 직전의 이력에 비춘 사실**을 돌려준다.

        마운트가 갈리면 그 마운트의 작업 집합을 비운다 — 「같은 마운트를 유지한 채」가 T9 의
        요체라서, 데이터를 바꾼 뒤의 두 번째 작업은 작업 전환이 아니라 새 세션이다.
        """
        if mount_key != self.mount_key:
            self.mount_key = mount_key
            self.mount_jobs = set()
        repeat_job = job in self.generated_jobs
        other_job_same_mount = bool(self.mount_jobs - {job})
        items_changed = False
        options_changed = False
        if slot_shape is not None:
            previous = self.slot_shapes.get(job)
            if previous is not None:
                # 항목 구성 = **고른 것이 있는 항목의 집합**이다. 「항목을 뺀다」가 곧 그
                # 항목의 선택을 비우는 것이라(§3.6 T17), 갈래만 바뀐 T18 과 이 축으로 갈린다.
                before = {sid for sid, opts in previous.items() if opts}
                after = {sid for sid, opts in slot_shape.items() if opts}
                if before != after:
                    items_changed = True
                elif previous != slot_shape:
                    options_changed = True
            self.slot_shapes[job] = dict(slot_shape)
        self.generated_jobs.add(job)
        self.mount_jobs.add(job)
        return GenerationLoopFacts(
            repeat_job=repeat_job,
            other_job_same_mount=other_job_same_mount,
            items_changed=items_changed,
            options_changed=options_changed,
        )
