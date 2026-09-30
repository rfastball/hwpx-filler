"""생성 run facts(Application) 헤드리스 owner — run identity 고정과 결과 분류 술어.

생성 척추(봉인 → 레코드 검증 → 배달 계획 → materialization → 배달)는 managed 파이프라인이
소유하고 그 진실은 ``test_managed_generation``·``test_webapp_job``·``test_cli`` 가 잰다. 종전
이 파일이 재던 legacy 척추(``plan_generation``·``direct_plan``·``run_generation``)는 #1081 PR3
에서 퇴역했다 — 여기 남는 것은 run 1회의 identity 고정과 결과 분류 facts 다.
"""
from __future__ import annotations

from hwpxfiller.application.generation import (
    blank_marker,
    run_completed,
    run_status,
    start_run,
)
from hwpxfiller.domain.job import MISSING_MARKER, Job, rules_fingerprints


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


def test_cancel_request_is_cooperative_state_on_the_run():
    run = start_run(Job(name="공고서"))
    assert not run.cancel.is_set()
    run.request_cancel()
    assert run.cancel.is_set()


# ------------------------------------------------------------------ 결과 분류 facts
def test_completion_is_only_an_uncancelled_run_without_failures():
    assert run_completed(False, 0) is True
    assert run_completed(False, 1) is False       # 무장 해제·스탬프가 공유하는 술어(#129)
    assert run_completed(True, 0) is False


def test_run_status_never_invents_a_failure_for_a_cancel():
    assert run_status(2, 2) == "completed"
    assert run_status(1, 2) == "partiallyCompleted"
    assert run_status(0, 2) == "failed"
    assert run_status(0, 2, True) == "partiallyCompleted"
