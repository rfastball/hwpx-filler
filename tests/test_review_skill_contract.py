"""`/review-round` 스킬이 절차의 **필수 단계**를 잃지 않았는지 센다.

이 파일이 생긴 이유는 실측이다. 같은 PR 에서 스킬을 세 번 고쳤고 그때마다 단계가 하나씩
죽었다 — 스레드 해결 단계가 사라져 시키는 대로 해도 게이트가 `BLOCKED` 에 머물렀고, 재리뷰
요청이 push 앞에 놓여 리뷰어가 옛 head 를 읽었고, heredoc 이 백슬래시를 삼켜 게이트 명령이
아예 안 도는 철자가 됐다. 셋 다 **산문이라 아무도 안 봤다.**

문장을 검사하지 않는다 — 문장은 계속 다듬어질 것이다. 그 절차가 **작동하는 데 필요한 것**만
센다: 실행할 명령의 철자, 순서, 그리고 정책이 요구하는 판단 단계의 존재.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude" / "skills" / "review-round" / "SKILL.md"
POLICY = ROOT / "docs" / "REVIEW_POLICY.md"


def _skill() -> str:
    return SKILL.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("command", "why"),
    [
        (".\\test.ps1", "게이트를 돌리는 명령"),
        ("uv run python scripts/review_rounds.py", "상태를 읽는 명령"),
        ("resolveReviewThread", "차단의 해소 신호를 남기는 명령"),
        ("@codex review", "재리뷰를 부르는 명령"),
        ("gh pr merge", "머지 명령"),
    ],
)
def test_the_skill_still_carries_every_command_the_procedure_needs(command: str, why: str) -> None:
    """철자 하나가 죽어도 산문은 멀쩡해 보인다 — `.\\test.ps1` 이 `.` + 탭 + `est.ps1` 이 됐던
    적이 있고, 시키는 대로 따라가면 게이트가 아예 안 돈 채 push 로 넘어갔다."""
    assert command in _skill(), f"{why}({command!r})이 스킬에서 사라졌습니다"


def test_the_review_request_comes_after_the_push() -> None:
    """순서가 계약이다. 먼저 부르면 리뷰어가 **옛 head** 를 읽고, 정작 픽스는 안 읽힌 채
    남는다 — push 는 더 이상 리뷰를 부르지 않으므로 스스로 복구되지도 않는다."""
    text = _skill()
    assert text.index("git push") < text.index("@codex review")


def test_the_skill_keeps_the_stop_signal_the_policy_defines() -> None:
    """게이트는 이것을 막지 않는다 — 판정이 `READY` 여도 사람이 멈춰야 하는 자리다.
    게이트가 대신 세워 주지 않으므로 절차에 적혀 있지 않으면 그냥 지나간다."""
    text = _skill()
    assert "재호출 예산" in text, "재호출 예산에서 결함류를 닫는 단계가 사라졌습니다"
    assert "세 번째" in text, "세 번째 재호출 앞에서 멈추는 문장이 사라졌습니다"


def test_the_skill_batches_fixes_into_one_commit_per_settlement_pass() -> None:
    """지적 하나마다 push 하면 리뷰어가 중간 상태를 읽고 코멘트가 push 마다 불어난다."""
    assert "한 커밋으로 묶는다" in _skill()


def test_the_skill_points_at_the_policy_instead_of_restating_it() -> None:
    """규칙 원문은 한 곳이 소유한다 — 두 벌은 따로 늙는다."""
    assert "docs/REVIEW_POLICY.md" in _skill()
    assert POLICY.exists()
