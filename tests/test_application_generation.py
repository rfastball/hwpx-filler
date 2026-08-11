"""생성 use case(Application) 헤드리스 owner — WebView/DOM/컨트롤러 없이 척추를 되읽는다.

준비→실행 요청→게이트 판정→plan→materialize→progress→cancel/complete→완주 기록→facts
(#571). 게이트 입력(검토 판정기·빈값 처리·덮어쓰기 확정)은 **호출자 선언**이고, 저장·
엔진은 in-memory 대역이다 — 같은 척추를 GUI(test_webapp_job)와 CLI(test_cli)가 각자의
표면 계약으로 다시 묻는다(층이 다르니 중복 아님: 여기는 판정 자체, 저쪽은 결선·문안).
"""
from __future__ import annotations

from datetime import datetime
from functools import partial

import pytest

from hwpxfiller.application.generation import (
    GenerationRun,
    blank_marker,
    direct_plan,
    plan_generation as _plan_generation,
    run_completed,
    run_generation as _run_generation,
    start_run,
)
from hwpxfiller.batch import OutputCollisionError
from hwpxfiller.domain.engine import GenerateResult
from hwpxfiller.domain.job import MISSING_MARKER, Job, rules_fingerprints
from hwpxfiller.gui.run_state import GateError
from hwpxfiller.external.output_files import ensure_output_directory, existing_output_paths

plan_generation = partial(_plan_generation, existing_outputs=existing_output_paths)
run_generation = partial(
    _run_generation,
    existing_outputs=existing_output_paths,
    ensure_output_dir=ensure_output_directory,
)


# ------------------------------------------------------------------ in-memory 대역
class _Engine:
    """레코드당 성공/실패를 선언받는 materializer 대역 — 파일은 만들지 않는다."""

    def __init__(self, oks=None, after_first=None):
        self.oks = list(oks) if oks is not None else None
        self.after_first = after_first          # 첫 레코드 완결 직후 훅(협조적 취소 재현)
        self.calls = 0

    def generate(self, template, rec, target):
        self.calls += 1
        ok = True if self.oks is None else self.oks.pop(0)
        if self.calls == 1 and self.after_first is not None:
            self.after_first()
        return GenerateResult(ok=ok, output_path=target, error="" if ok else "boom")


class _Store:
    """JobStorePort 의 완주 기록 대역 — 무엇이(이름·시각·규칙) 기록됐는지 붙든다."""

    def __init__(self, boom=None):
        self.stamps = []
        self.boom = boom

    def stamp_last_run(self, name, when, *, rules=None):
        if self.boom is not None:
            raise self.boom
        self.stamps.append((name, when, rules))
        job = Job(name=name)
        job.last_run_at = when
        job.reviewed_rules = dict(rules or {})
        return job


class _VM:
    """RunViewModel 의 게이트 표면 대역 — 호출 순서·관통 인자를 기록한다."""

    def __init__(self, errors=(), blanks=(), conflicts=()):
        self.errors, self.blanks, self.conflicts = list(errors), list(blanks), list(conflicts)
        self.trace = []
        self.plan_kwargs = None

    def validate_generate(self, indices, out_dir):
        self.trace.append("validate")
        return list(self.errors)

    def blank_fields(self, indices):
        self.trace.append("blanks")
        return list(self.blanks)

    def output_conflicts(
        self, indices, out_dir, *, mark_missing="", now=None, existing_outputs=None
    ):
        self.trace.append(("conflicts", mark_missing, now))
        return list(self.conflicts)

    def build_generation_plan(self, indices, out_dir, *, marker="", overwrite=False, now=None):
        self.trace.append("plan")
        self.plan_kwargs = {"marker": marker, "overwrite": overwrite, "now": now}
        return direct_plan(
            "t.hwpx", [{} for _ in indices], out_dir, "doc-{{seq:001}}",
            marker=marker, overwrite=overwrite,
        )


def _plan(tmp_path, n=2):
    """실행 가능한 최소 불변 계획 — 이름 계약(연번)만 쓰고 템플릿 바이트는 안 읽는다."""
    return direct_plan(
        str(tmp_path / "t.hwpx"), [{"ID": f"{i:03}"} for i in range(1, n + 1)],
        str(tmp_path / "out"), "doc-{{ID}}",
    )


# ------------------------------------------------------------------ 게이트 판정 순서
_NOW = datetime(2026, 8, 10, 9, 0, 0)


def test_gate_order_rejection_stops_before_review():
    vm = _VM(errors=[GateError("먼저 데이터를 선택하세요.", "warn")])
    decision = plan_generation(
        vm, [0], "out", now=_NOW,
        review_check=lambda bl: pytest.fail("거절 뒤에 검토를 물으면 순서 위반"),
    )
    assert decision.rejection is vm.errors[0] and decision.plan is None
    assert vm.trace == ["validate"]              # 빈 값·충돌 조회조차 하지 않는다


def test_review_backstop_consumes_the_same_blank_set():
    vm = _VM(blanks=["담당자"])
    unmet = object()                             # 판정기 반환은 불투명 관통
    seen = []
    decision = plan_generation(
        vm, [0], "out", now=_NOW, review_check=lambda bl: seen.append(bl) or unmet,
    )
    assert decision.review_unmet is unmet and decision.blanks == ("담당자",)
    assert seen == [["담당자"]]                  # 표식·승인이 같은 집합을 본다(§2.13)
    assert decision.plan is None and "plan" not in vm.trace


def test_overwrite_needs_confirmation_then_builds_the_plan():
    now = _NOW
    vm = _VM(blanks=["담당자"], conflicts=["out/doc-001.hwpx"])
    held = plan_generation(vm, [0, 1], "out", now=now, review_check=lambda bl: None)
    assert held.needs_overwrite and held.plan is None
    assert held.conflicts == ("out/doc-001.hwpx",)
    assert held.marker == MISSING_MARKER         # 확인 왕복에도 표식 사실은 이미 확정
    assert ("conflicts", MISSING_MARKER, now) in vm.trace  # 확인=생성 동일 시각·표식(RC-02)

    vm2 = _VM(blanks=[], conflicts=["out/doc-001.hwpx"])
    done = plan_generation(
        vm2, [0, 1], "out", now=now, review_check=lambda bl: None, confirm_overwrite=True,
    )
    assert done.plan is not None and done.plan.overwrite is True
    assert vm2.plan_kwargs == {"marker": "", "overwrite": True, "now": now}


def test_blank_marker_is_the_single_predicate():
    assert blank_marker(["담당자"]) == MISSING_MARKER
    assert blank_marker([]) == ""


# ------------------------------------------------------------------ run identity 고정
def test_start_run_fixes_subject_revisions_and_rules():
    job = Job(name="공고서")
    run = start_run(job, token="t-1")
    assert run.job_name == "공고서" and run.token == "t-1"
    assert run.revisions == {
        "template": job.template_revision, "binding": job.binding_revision,
    }
    assert run.rules == rules_fingerprints(job)

    anonymous = start_run(None, job_name="", token="")
    assert anonymous.job_name == "" and anonymous.revisions == {} and anonymous.rules is None


# ------------------------------------------------------------------ materialize→기록→facts
def test_complete_run_stamps_the_run_subject_with_run_rules(tmp_path):
    job = Job(name="공고서")
    run = start_run(job)
    store = _Store()
    deltas = []
    outcome = run_generation(
        run, _plan(tmp_path), engine=_Engine(), progress=lambda d, t: deltas.append((d, t)),
        store=store, completed_at=lambda: "2026-08-10T09:00:00",
    )
    assert outcome.status == "completed" and outcome.completed is True
    assert (outcome.succeeded, outcome.failed, outcome.total) == (2, 0, 2)
    assert deltas[0] == (0, 2) and deltas[-1] == (2, 2)   # 시작 델타 → 완료 델타 순서
    # 기록은 **이 run 이 고정한** 주체·규칙으로 — 세션이 아니라 run 이 정본이다.
    assert store.stamps == [("공고서", "2026-08-10T09:00:00", run.rules)]
    assert outcome.stamped_job is not None
    assert outcome.stamped_job.last_run_at == "2026-08-10T09:00:00"


def test_per_record_failure_is_not_completion_and_does_not_stamp(tmp_path):
    store = _Store()
    outcome = run_generation(
        start_run(Job(name="공고서")),
        _plan(tmp_path), engine=_Engine(oks=[True, False]),
        store=store, completed_at=lambda: "2026-08-10T09:00:00",
    )
    assert outcome.status == "partiallyCompleted" and outcome.completed is False
    assert outcome.failed == 1 and store.stamps == []
    assert run_completed(False, 1) is False       # 무장 해제·스탬프가 공유하는 술어(#129)


def test_cancel_keeps_completed_documents_and_separates_unstarted(tmp_path):
    run = start_run(Job(name="공고서"))
    store = _Store()
    engine = _Engine(after_first=run.request_cancel)   # 협조적 취소(RC-06) — 레코드 경계
    outcome = run_generation(
        run, _plan(tmp_path, n=3), engine=engine,
        store=store, completed_at=lambda: "2026-08-10T09:00:00",
    )
    assert outcome.cancelled is True and outcome.status == "partiallyCompleted"
    assert (outcome.succeeded, outcome.attempted, outcome.unstarted) == (1, 1, 2)
    assert outcome.failed == 0                    # 미착수는 실패가 아니다(취소 산술)
    assert outcome.completed is False and store.stamps == []
    assert len(outcome.results) == 1              # 완료된 문서의 결과만 남는다


def test_stamp_failure_is_a_loud_fact_not_an_exception(tmp_path):
    outcome = run_generation(
        start_run(Job(name="공고서")), _plan(tmp_path), engine=_Engine(),
        store=_Store(boom=OSError("디스크 쓰기 거부")),
        completed_at=lambda: "2026-08-10T09:00:00",
    )
    assert outcome.completed is True              # 문서는 만들어졌다 — 완료 서사 유지
    assert "디스크 쓰기 거부" in outcome.stamp_error
    assert outcome.stamped_job is None


def test_prebatch_failure_is_declared_capture_and_counts_no_attempt(tmp_path):
    plan = _plan(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "doc-001.hwpx").write_bytes(b"")       # 기존 산출물 = 수기 보정본일 수 있다(RC-02)
    collided = run_generation(
        start_run(None), plan, engine=_Engine(),
        capture=(OutputCollisionError,), store=None,
    )
    assert isinstance(collided.error, OutputCollisionError)
    assert collided.status == "failed" and collided.attempted == 0
    assert collided.unstarted == collided.total == 2  # 시도 0 — 같은 건을 두 번 세지 않는다

    with pytest.raises(OutputCollisionError):     # 선언 밖 예외는 그대로 상승(호출자 계약)
        run_generation(start_run(None), plan, engine=_Engine(), store=None)


def test_store_without_completed_at_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="completed_at"):
        run_generation(
            start_run(Job(name="공고서")), _plan(tmp_path), engine=_Engine(),
            store=_Store(), completed_at=None,
        )
