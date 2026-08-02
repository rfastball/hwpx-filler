"""리뷰 게이트 워크플로의 **형상 계약**(`docs/REVIEW_POLICY.md` §7).

이 파일이 지키는 것은 하나다 — **PR 이 자기 게이트를 약화시킬 수 없어야 한다.** 그 성질은
YAML 한 줄(`pull_request` 대 `pull_request_target`)에 달려 있고, 바뀌어도 워크플로는 여전히
잘 도는 것처럼 보인다. 그래서 사람이 눈으로 지킬 수 없다.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / ".github" / "workflows" / "review-gate.yml"

#: 브랜치 보호가 겨누는 이름. 스크립트가 head SHA 에 게시하는 체크런 쪽이다.
CHECK = "review-gate"


def _workflow() -> tuple[str, dict]:
    text = GATE.read_text(encoding="utf-8")
    loaded = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict)
    return text, loaded


def test_the_gate_runs_the_base_revision_not_the_pull_request_revision() -> None:
    """`pull_request` 로 돌면 PR 판본의 워크플로·스크립트가 돌아 게이트가 자기를 봐준다."""
    _, workflow = _workflow()
    triggers = workflow["on"]
    assert "pull_request_target" in triggers
    assert "pull_request" not in triggers


def test_the_gate_checks_out_the_default_branch_explicitly() -> None:
    """이벤트마다 기본 체크아웃이 다르다 — 암묵에 기대면 리뷰 이벤트에서 PR head 가 잡힌다.

    fork 가드가 `pull_request.head.repo` 를 **읽는** 것은 허용한다 — 금지는 head 를
    체크아웃 대상으로 잡는 것이다(sha·ref)."""
    text, workflow = _workflow()
    steps = workflow["jobs"]["judge"]["steps"]
    checkouts = [s for s in steps if "checkout" in s.get("uses", "")]
    assert len(checkouts) == 1
    assert checkouts[0]["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert "pull_request.head.sha" not in text and "pull_request.head.ref" not in text


def test_the_gate_sweeps_open_pull_requests_on_a_schedule() -> None:
    """리액션·회수 창 경과는 이벤트를 만들지 않는다 — 깨울 사건이 없으면 영영 기다린다."""
    _, workflow = _workflow()
    assert "schedule" in workflow["on"]
    steps = workflow["jobs"]["judge"]["steps"]
    assert any("--all-open" in step.get("run", "") for step in steps)


def test_the_sweep_cadence_is_hourly_off_peak() -> None:
    """schedule 은 최선노력 큐다(실측 2.7시간 0회 발화) — 백스톱이지 엔진이 아니다.
    10분 크론으로 되돌리면 공용 rate 풀을 다시 태우면서 신뢰성은 얻지 못한다. 정시(0분)는
    부하 스파이크라 피한다."""
    _, workflow = _workflow()
    crons = [entry["cron"] for entry in workflow["on"]["schedule"]]
    assert crons == ["17 * * * *"]


def test_the_gate_can_be_kicked_when_no_event_will_come() -> None:
    """리액션·창 경과의 재판정은 클라이언트 킥이 1차다 — cron 을 각성원으로 믿지 않는다."""
    _, workflow = _workflow()
    dispatch = workflow["on"]["workflow_dispatch"]
    assert dispatch["inputs"]["pr"]["required"] in (True, "true")
    steps = workflow["jobs"]["judge"]["steps"]
    judge = next(s for s in steps if "--publish-check" in s.get("run", "") and "--all-open" not in s["run"])
    assert "inputs.pr" in str(judge["env"]["PR_NUMBER"])


def test_the_rejected_thread_trigger_stays_out() -> None:
    """`pull_request_review_thread` 는 Actions 파서가 거부한다(2026-08-02 실측) — 문서·
    PyYAML·이 테스트 파일의 옛 단언까지 전부 초록인 채 **머지 직후 파일 전체가 파싱 불능**이
    돼 게이트가 통째로 죽었다. 선언은 살고 결과는 죽는 결함류의 표본이라, 여기서는 반대
    방향을 계약으로 잠근다."""
    _, workflow = _workflow()
    assert "pull_request_review_thread" not in workflow["on"]


def test_sweep_runs_do_not_share_a_group_with_pull_request_runs() -> None:
    """PR 번호가 없는 이벤트가 빈 그룹으로 뭉치면 스윕끼리 서로를 죽인다."""
    _, workflow = _workflow()
    group = workflow["concurrency"]["group"]
    assert "'sweep'" in group and "github.event_name == 'schedule'" in group
    assert workflow["concurrency"]["cancel-in-progress"] in (True, "true")


def test_fork_born_events_do_not_run_the_judge() -> None:
    """review·thread 계열 이벤트는 base 판본 보장이 없다 — fork 발은 걸러서 스윕이 덮는다."""
    _, workflow = _workflow()
    guard = workflow["jobs"]["judge"]["if"]
    assert "github.event.pull_request.head.repo.full_name == github.repository" in guard


def test_the_gate_re_evaluates_when_settlement_markers_arrive() -> None:
    """정산은 코멘트로 온다. 코드 push 만 보면 정산이 끝나도 초록으로 안 바뀐다."""
    _, workflow = _workflow()
    triggers = workflow["on"]
    for event in ("issue_comment", "pull_request_review", "pull_request_review_comment"):
        assert event in triggers


def test_the_job_name_is_not_the_required_check_name() -> None:
    """둘이 같으면 어느 쪽이 필수인지 흐려진다 — 필수는 head SHA 에 게시한 체크런이다."""
    _, workflow = _workflow()
    assert CHECK not in workflow["jobs"]


def test_the_gate_can_write_checks_and_read_no_more_than_it_needs() -> None:
    _, workflow = _workflow()
    permissions = workflow["permissions"]
    assert permissions["checks"] == "write"
    assert permissions["contents"] == "read"
    assert "write" not in {value for key, value in permissions.items() if key != "checks"}


def test_every_action_is_pinned_to_a_full_commit_sha() -> None:
    """태그는 움직이는 이름이다 — 같은 워크플로가 어제와 다른 코드를 돌릴 수 있다."""
    text, _ = _workflow()
    for reference in re.findall(r"uses:\s*(\S+)", text):
        assert re.search(r"@[0-9a-f]{40}$", reference), f"{reference} 가 SHA 로 고정되지 않았습니다"
