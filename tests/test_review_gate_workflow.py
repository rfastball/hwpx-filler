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


def test_the_gate_does_not_check_out_the_pull_request_head() -> None:
    """base 판본을 받아 놓고 head 로 갈아타면 위 계약이 조용히 무효가 된다."""
    text, workflow = _workflow()
    steps = workflow["jobs"]["judge"]["steps"]
    checkout = next(s for s in steps if "checkout" in s.get("uses", ""))
    assert "with" not in checkout, "체크아웃에 ref 를 주면 base 판본 보장이 깨집니다"
    assert "github.event.pull_request.head.sha" not in text


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
