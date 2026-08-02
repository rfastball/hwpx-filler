"""리뷰 라운드 판독기의 계약(`docs/REVIEW_POLICY.md`).

실 API 를 부르지 않는다 — `gh` seam 을 고정 응답 대역으로 갈아 끼운다. 리뷰 상태는 우리가
만들 수 없는 원격 사실이라 픽스처로 재현해야 **양성·음성 두 대조**를 각각 세울 수 있다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts import review_rounds
from scripts.review_rounds import BLOCKED, READY, WAIT, GitHub, GitHubError, NotFound, evaluate

PR = 430
NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
PUSHED = NOW - timedelta(minutes=1)


def _comment(comment_id: int, commit: str, *, path: str = "src/a.py", line: int | None = 10) -> dict:
    return {
        "id": comment_id,
        "path": path,
        "line": line,
        "original_commit_id": commit,
        "user": {"login": "chatgpt-codex-connector[bot]"},
        "body": f"finding {comment_id}",
    }


class FakeGitHub:
    """`GitHub` 와 같은 표면만 갖는 대역."""

    def __init__(
        self,
        *,
        head: str = "c1",
        files: list[str] | None = None,
        comments: list[dict] | None = None,
        triage: list[str] | None = None,
        settler: str = "OWNER",
        reactions: list[dict] | None = None,
        trees: dict[str, str] | None = None,
        issues: dict[int, dict] | None = None,
    ) -> None:
        self.repo = "rfastball/hwpx-filler"
        self.head = head
        self.files = files if files is not None else ["src/a.py"]
        self.comments = comments or []
        self.triage = triage or []
        self.settler = settler
        self.reactions = reactions or []
        self.trees = trees or {}
        self.issues = issues or {}
        self.posted: list[tuple[str, dict]] = []
        self.resolved: set[int] = set()

    def graphql(self, query: str, **variables: object) -> dict:
        nodes = [
            {
                "isResolved": raw["id"] in self.resolved,
                "isOutdated": raw.get("line") is None,
                "comments": {"nodes": [{"databaseId": raw["id"]}]},
            }
            for raw in self.comments
            if not raw.get("in_reply_to_id")
        ]
        return {
            "data": {
                "repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}}}
            }
        }

    def post(self, path: str, payload: dict) -> dict:
        self.posted.append((path, payload))
        return {"id": 1}

    def get(self, path: str) -> dict:
        if path == f"pulls/{PR}":
            return {"number": PR, "head": {"sha": self.head, "ref": "topic"}}
        if path.endswith("/check-suites"):
            return {
                "check_suites": [
                    {
                        "created_at": PUSHED.isoformat().replace("+00:00", "Z"),
                        "head_branch": "topic",
                        "pull_requests": [{"number": PR}],
                    }
                ]
            }
        if path.startswith("commits/"):
            sha = path.split("/", 1)[1]
            return {
                "commit": {
                    "tree": {"sha": self.trees.get(sha, f"tree-{sha}")},
                    "committer": {"date": PUSHED.isoformat().replace("+00:00", "Z")},
                }
            }
        if path.startswith("issues/"):
            number = int(path.split("/", 1)[1])
            if number not in self.issues:
                raise NotFound(f"404 issues/{number}")
            return self.issues[number]
        raise AssertionError(f"예상하지 못한 조회: {path}")

    def paged(self, path: str) -> list[dict]:
        if path == f"pulls/{PR}/files":
            return [{"filename": name} for name in self.files]
        if path == f"pulls/{PR}/comments":
            return self.comments
        if path == f"issues/{PR}/comments":
            return [
                {"body": body, "author_association": self.settler} for body in self.triage
            ]
        if path == f"issues/{PR}/reactions":
            return self.reactions
        raise AssertionError(f"예상하지 못한 목록 조회: {path}")

    def pr_for_current_branch(self) -> int:
        return PR


def _reaction(content: str, *, login: str = review_rounds.REVIEWER_LOGINS[0]) -> dict:
    return {
        "content": content,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "user": {"login": login},
    }


def _open_issue(number: int) -> dict:
    return {"number": number, "state": "open"}


# ── 라운드 카운트 ──────────────────────────────────────────────────────────────


def test_rounds_are_counted_by_original_commit_id() -> None:
    """#426 실측 형상 — 서로 다른 커밋 8개에 앵커된 지적은 8라운드다."""
    comments = [_comment(100 + i, f"sha{i}") for i in range(8)]
    report = evaluate(
        FakeGitHub(head="sha7", comments=comments, triage=[f"triage: {100 + i} block" for i in range(8)]),
        PR,
        now=NOW,
    )
    assert len(report.rounds) == 8
    assert [r.commit for r in report.rounds] == [f"sha{i}" for i in range(8)]


def test_a_rebase_only_push_is_not_a_round() -> None:
    """코드가 안 바뀐 재발화는 앞 라운드에 흡수된다 — 착지 순서가 라운드를 부풀리지 않는다."""
    comments = [_comment(1, "before"), _comment(2, "rebased")]
    fake = FakeGitHub(
        head="rebased",
        comments=comments,
        trees={"before": "same-tree", "rebased": "same-tree"},
        triage=["triage: 1 block", "triage: 2 block"],
    )
    report = evaluate(fake, PR, now=NOW)
    assert len(report.rounds) == 1
    assert [f.id for f in report.rounds[0].findings] == [1, 2]


def test_distinct_trees_stay_separate_rounds() -> None:
    """음성 대조 — 트리가 다르면 흡수하지 않는다."""
    comments = [_comment(1, "before"), _comment(2, "after")]
    fake = FakeGitHub(
        head="after",
        comments=comments,
        trees={"before": "tree-a", "after": "tree-b"},
        triage=["triage: 1 block", "triage: 2 block"],
    )
    assert len(evaluate(fake, PR, now=NOW).rounds) == 2


# ── 정산 완결성 ────────────────────────────────────────────────────────────────


def test_an_unsettled_finding_holds_the_gate() -> None:
    settled_and_fixed = _comment(1, "c1", line=None)
    fake = FakeGitHub(head="c1", comments=[settled_and_fixed, _comment(2, "c1")], triage=["triage: 1 block"])
    report = evaluate(fake, PR, now=NOW)
    assert report.status == WAIT
    assert [f.id for f in report.unsettled] == [2]


def test_settled_and_resolved_findings_are_ready() -> None:
    """차단은 **outdated 가 되어야** 해소다 — 코멘트가 사라진 것이 고쳐졌다는 원격 증거다."""
    fixed = _comment(1, "c0", line=None)
    fake = FakeGitHub(
        head="c1",
        comments=[fixed],
        triage=["triage: 1 block"],
        reactions=[_reaction("+1")],
    )
    report = evaluate(fake, PR, now=NOW)
    assert report.status == READY
    assert report.open_blocks == []


def test_a_resolved_thread_closes_a_block_even_while_the_comment_lives() -> None:
    """GitHub 은 앵커 hunk 가 살아 있으면 코멘트를 재앵커해 유지한다 — 바로 옆을 고쳐도
    outdated 가 되지 않으므로 그것만으로는 해소를 못 잰다. 스레드 해결이 옳은 신호다."""
    fake = FakeGitHub(head="c1", comments=[_comment(1, "c1")], triage=["triage: 1 block"])
    fake.resolved.add(1)
    report = evaluate(fake, PR, now=NOW)
    assert report.open_blocks == [] and report.status == READY


def test_a_block_that_is_still_live_blocks() -> None:
    fake = FakeGitHub(head="c1", comments=[_comment(1, "c1")], triage=["triage: 1 block"])
    report = evaluate(fake, PR, now=NOW)
    assert report.status == BLOCKED
    assert [f.id for f in report.open_blocks] == [1]


# ── 분리는 이슈 실재로 확인된다 ────────────────────────────────────────────────


def test_defer_needs_an_issue_that_exists_and_is_open() -> None:
    fake = FakeGitHub(
        head="c1",
        comments=[_comment(1, "c1")],
        triage=["triage: 1 defer #77"],
        issues={77: _open_issue(77)},
        reactions=[_reaction("+1")],
    )
    assert evaluate(fake, PR, now=NOW).status == READY


@pytest.mark.parametrize(
    ("issues", "fragment"),
    [
        ({}, "이슈가 없습니다"),
        ({77: {"number": 77, "state": "closed"}}, "닫혀 있습니다"),
        ({77: {"number": 77, "state": "open", "pull_request": {}}}, "PR 입니다"),
    ],
)
def test_a_defer_marker_alone_does_not_pass(issues: dict, fragment: str) -> None:
    """번호만 적어서는 못 지나간다 — 증거는 원격 상태다."""
    fake = FakeGitHub(head="c1", comments=[_comment(1, "c1")], triage=["triage: 1 defer #77"], issues=issues)
    report = evaluate(fake, PR, now=NOW)
    assert report.status == BLOCKED
    assert fragment in report.bad_defers[0][1]


def test_a_defer_without_a_number_does_not_pass() -> None:
    fake = FakeGitHub(head="c1", comments=[_comment(1, "c1")], triage=["triage: 1 defer"])
    assert evaluate(fake, PR, now=NOW).status == BLOCKED


# ── 빠른 경로 ──────────────────────────────────────────────────────────────────


def test_prose_only_changes_take_the_fast_path() -> None:
    fake = FakeGitHub(files=["docs/README.md", "CLAUDE.md", "docs/UI_GALLERY.html"], comments=[_comment(1, "c1")])
    report = evaluate(fake, PR, now=NOW)
    assert report.fast_path and report.status == READY


@pytest.mark.parametrize(
    "path",
    [
        "src/hwpxfiller/core/job.py",
        "frontend/js/app.js",
        ".github/workflows/quality.yml",
        "docs/UI_CONTRACT.md",
        # 게이트 기계다 — 깨지면 계약이 거짓말한다(#423 하니스, #426 의 P1 2건).
        "tests/test_quickstart_101_live.py",
        "scripts/capture_101_screenshots.py",
        # `docs/` 아래여도 기계가 읽는 원장은 산문이 아니다.
        "docs/package_coverage_floors.toml",
    ],
)
def test_anything_but_prose_forfeits_the_fast_path(path: str) -> None:
    """음성 대조 — 허용 목록 밖은 전부 리뷰를 기다린다."""
    fake = FakeGitHub(files=["docs/README.md", path], comments=[_comment(1, "c1")])
    report = evaluate(fake, PR, now=NOW)
    assert not report.fast_path
    assert report.status != READY


def test_a_rename_out_of_the_product_is_not_prose() -> None:
    """`src/x.py` → `docs/x.md` 는 제품 코드를 지우면서 산문뿐인 변경으로 보인다."""

    class Renaming(FakeGitHub):
        def paged(self, path: str) -> list[dict]:
            if path == f"pulls/{PR}/files":
                return [{"filename": "docs/x.md", "previous_filename": "src/x.py"}]
            return super().paged(path)

    assert not evaluate(Renaming(comments=[_comment(1, "c1")]), PR, now=NOW).fast_path


def test_a_root_level_html_asset_is_not_prose() -> None:
    """루트의 `.html` 은 산문이 아니라 실행되는 웹 자산일 수 있다 — 문서는 root 를 `.md` 로 적었다."""
    assert not evaluate(FakeGitHub(files=["index.html"], comments=[_comment(1, "c1")]), PR, now=NOW).fast_path


def test_an_empty_diff_is_not_a_fast_path() -> None:
    """변경이 없으면 「산문뿐」이 공허하게 참이 된다 — 그 길로 초록이 나가지 않는다."""
    assert not evaluate(FakeGitHub(files=[], comments=[_comment(1, "c1")]), PR, now=NOW).fast_path


# ── 리뷰 회수 ──────────────────────────────────────────────────────────────────


def test_the_gate_waits_until_the_last_push_is_reviewed() -> None:
    fake = FakeGitHub(head="c2", comments=[_comment(1, "c1", line=None)], triage=["triage: 1 block"])
    report = evaluate(fake, PR, now=NOW)
    assert report.status == WAIT and not report.head_reviewed


def test_the_window_is_measured_from_the_push_not_the_commit_date() -> None:
    """cherry-pick 한 커밋은 만들어진 지 오래다 — 커밋 시각으로 재면 첫 판정부터 창이 지난다."""

    class OldCommitJustPushed(FakeGitHub):
        def get(self, path: str) -> dict:
            if path.endswith("/check-suites"):
                return {"check_suites": [{"created_at": NOW.isoformat().replace("+00:00", "Z")}]}
            return super().get(path)

    fake = OldCommitJustPushed(head="c2", comments=[_comment(1, "c1", line=None)], triage=["triage: 1 block"])
    report = evaluate(fake, PR, now=NOW + timedelta(minutes=1))
    assert report.status == WAIT and not report.timed_out


def test_a_head_with_no_check_suite_has_not_timed_out() -> None:
    """방금 올라와 CI 도 안 붙은 SHA 를 「창이 지났다」로 읽지 않는다."""

    class NoSuiteYet(FakeGitHub):
        def get(self, path: str) -> dict:
            if path.endswith("/check-suites"):
                return {"check_suites": []}
            return super().get(path)

    fake = NoSuiteYet(head="c2", comments=[_comment(1, "c1", line=None)], triage=["triage: 1 block"])
    assert not evaluate(fake, PR, now=NOW).timed_out


def test_the_recovery_window_closes_on_its_own_but_says_so() -> None:
    """창 소진은 리뷰가 아니라 **교착 탈출**이다. 조용히 초록이 되면 「리뷰를 받았다」와
    「리뷰어가 침묵했다」가 같은 색이 된다."""
    fake = FakeGitHub(head="c2", comments=[_comment(1, "c1", line=None)], triage=["triage: 1 block"])
    report = evaluate(fake, PR, now=PUSHED + review_rounds.RECOVERY_WINDOW + timedelta(seconds=1))
    assert report.status == READY and report.timed_out
    assert "받지 못한 채" in review_rounds.render(report)

    review_rounds.publish_check(fake, report)
    assert "회수 창 소진" in fake.posted[0][1]["output"]["title"]


def test_a_reviewed_head_is_not_marked_as_timed_out() -> None:
    """음성 대조 — 신호를 받고 닫힌 것은 침묵으로 닫힌 것과 다르다."""
    fake = FakeGitHub(
        head="c1",
        comments=[_comment(1, "c1", line=None)],
        triage=["triage: 1 block"],
        reactions=[_reaction("+1")],
    )
    report = evaluate(fake, PR, now=PUSHED + review_rounds.RECOVERY_WINDOW + timedelta(seconds=1))
    assert report.status == READY and not report.timed_out


def test_only_the_reviewer_can_signal_no_findings() -> None:
    """작성자가 자기 PR 에 `+1` 을 달아 리뷰 없이 초록을 만들면 게이트가 거짓말한다."""
    fake = FakeGitHub(
        head="c2",
        comments=[_comment(1, "c1", line=None)],
        triage=["triage: 1 block"],
        reactions=[_reaction("+1", login="rfastball")],
    )
    report = evaluate(fake, PR, now=NOW)
    assert report.signal is None and report.status == WAIT


def test_an_authored_comment_on_head_is_not_a_review() -> None:
    """리액션만 조이면 이 경로가 열린 채 남는다 — 작성자가 head 에 코멘트를 달아 정산하면
    「리뷰를 받았다」가 스스로 만들어진다."""
    mine = _comment(2, "c2") | {"user": {"login": "rfastball"}}
    fake = FakeGitHub(
        head="c2",
        comments=[_comment(1, "c1", line=None), mine],
        triage=["triage: 1 block", "triage: 2 defer #77"],
        issues={77: _open_issue(77)},
    )
    fake.resolved.add(1)
    report = evaluate(fake, PR, now=NOW)
    assert not report.head_reviewed and report.status == WAIT


def test_a_reviewer_comment_on_head_is_a_review() -> None:
    """양성 대조 — 리뷰어가 head 를 짚었으면 그 push 는 읽힌 것이다."""
    fake = FakeGitHub(head="c2", comments=[_comment(1, "c2")], triage=["triage: 1 block"])
    fake.resolved.add(1)
    assert evaluate(fake, PR, now=NOW).head_reviewed


def test_only_trusted_actors_can_settle() -> None:
    """공개 PR 에서는 아무나 코멘트를 단다. 뒤 마커가 앞을 덮으므로 통제 없이 두면 남이
    게이트를 열거나 붙잡아 둘 수 있다."""
    fake = FakeGitHub(
        head="c1", comments=[_comment(1, "c1")], triage=["triage: 1 defer #77"], settler="NONE"
    )
    report = evaluate(fake, PR, now=NOW)
    assert [f.id for f in report.unsettled] == [1]


def test_a_check_suite_from_another_pull_request_does_not_start_the_clock() -> None:
    """같은 SHA 가 다른 브랜치에서 이미 돌았으면 그때의 스위트가 함께 실린다 — 그것으로 재면
    이 PR 로서는 처음인 판정이 이미 창을 넘긴 것이 된다."""

    class Elsewhere(FakeGitHub):
        def get(self, path: str) -> dict:
            if path.endswith("/check-suites"):
                return {
                    "check_suites": [
                        {
                            "created_at": (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                            "head_branch": "other-branch",
                            "pull_requests": [{"number": 999}],
                        }
                    ]
                }
            return super().get(path)

    fake = Elsewhere(head="c2", comments=[_comment(1, "c1", line=None)], triage=["triage: 1 block"])
    fake.resolved.add(1)
    assert not evaluate(fake, PR, now=NOW).timed_out


def test_eyes_is_not_a_no_findings_signal() -> None:
    """`eyes` 는 진행 중이다 — `+1` 과 혼동하면 리뷰를 안 기다리고 넘어간다."""
    fake = FakeGitHub(
        head="c2",
        comments=[_comment(1, "c1", line=None)],
        triage=["triage: 1 block"],
        reactions=[_reaction("eyes")],
    )
    report = evaluate(fake, PR, now=NOW)
    assert report.signal == "eyes" and report.status == WAIT


# ── 회귀 후보 ──────────────────────────────────────────────────────────────────


def test_the_same_place_twice_is_flagged_as_a_regression_candidate() -> None:
    fake = FakeGitHub(
        head="c2",
        comments=[_comment(1, "c1", line=10), _comment(2, "c2", line=12)],
        triage=["triage: 1 block", "triage: 2 block"],
    )
    report = evaluate(fake, PR, now=NOW)
    assert [(b.id, a.id) for b, a in report.regressions] == [(1, 2)]


def test_a_different_file_is_not_a_regression_candidate() -> None:
    fake = FakeGitHub(
        head="c2",
        comments=[_comment(1, "c1", path="src/a.py"), _comment(2, "c2", path="src/b.py")],
        triage=["triage: 1 block", "triage: 2 block"],
    )
    assert evaluate(fake, PR, now=NOW).regressions == []


# ── 답글은 지적이 아니다 ───────────────────────────────────────────────────────


def test_replies_do_not_create_their_own_settlement_duty() -> None:
    reply = _comment(2, "c1") | {"in_reply_to_id": 1}
    fake = FakeGitHub(
        head="c1",
        comments=[_comment(1, "c1", line=None), reply],
        triage=["triage: 1 block"],
        reactions=[_reaction("+1")],
    )
    report = evaluate(fake, PR, now=NOW)
    assert report.unsettled == [] and report.status == READY


# ── 실패는 통과가 아니다 ───────────────────────────────────────────────────────


def test_a_lookup_failure_exits_two(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """조회 실패를 초록으로 바꾸지 않는다 — 판정 불가는 판정 통과가 아니다."""
    monkeypatch.setattr("sys.argv", ["review_rounds.py"])

    def explode() -> GitHub:
        raise GitHubError("gh 미인증")

    monkeypatch.setattr(GitHub, "discover", staticmethod(explode))
    assert review_rounds.main() == 2
    assert "읽지 못했습니다" in capsys.readouterr().err


# ── 훅은 머지 명령에만 반응한다 ────────────────────────────────────────────────


def test_the_hook_ignores_commands_that_are_not_a_merge() -> None:
    assert review_rounds._hook(json.dumps({"tool_input": {"command": "git status"}})) == 0


def test_the_hook_refuses_a_merge_that_is_not_ready(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    fake = FakeGitHub(head="c1", comments=[_comment(1, "c1")], triage=["triage: 1 block"])
    monkeypatch.setattr(GitHub, "discover", staticmethod(lambda: fake))
    payload = json.dumps({"tool_input": {"command": "gh pr merge 430 --squash"}})
    assert review_rounds._hook(payload) == 2
    assert "/review-round" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command",
    [
        f"gh pr merge {PR} --squash",
        f"gh pr merge https://github.com/rfastball/hwpx-filler/pull/{PR}",
    ],
)
def test_the_hook_judges_the_pr_named_in_the_command(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """현재 브랜치만 물으면 다른 브랜치에 서서 머지할 때 엉뚱한 PR 에 초록을 준다."""

    class WrongBranch(FakeGitHub):
        def pr_for_current_branch(self) -> int:
            raise AssertionError("명령에 적힌 PR 을 두고 현재 브랜치를 물었습니다")

    fake = WrongBranch(head="c1", comments=[_comment(1, "c1")], triage=["triage: 1 block"])
    monkeypatch.setattr(GitHub, "discover", staticmethod(lambda: fake))
    assert review_rounds._hook(json.dumps({"tool_input": {"command": command}})) == 2


def test_the_hook_allows_a_ready_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGitHub(files=["docs/README.md"])
    monkeypatch.setattr(GitHub, "discover", staticmethod(lambda: fake))
    payload = json.dumps({"tool_input": {"command": "gh pr merge 430 --squash"}})
    assert review_rounds._hook(payload) == 0


# ── 체크런 게시 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("triage", "status", "conclusion"),
    [
        (["triage: 1 block"], BLOCKED, "failure"),
        ([], WAIT, "action_required"),
    ],
)
def test_the_check_run_carries_the_verdict(triage: list[str], status: str, conclusion: str) -> None:
    """`success` 만 머지를 연다. 아직 안 끝난 것과 틀린 것은 다른 색으로 찍는다."""
    fake = FakeGitHub(head="c1", comments=[_comment(1, "c1")], triage=triage)
    report = evaluate(fake, PR, now=NOW)
    assert report.status == status
    review_rounds.publish_check(fake, report)
    path, payload = fake.posted[0]
    assert path == "check-runs"
    assert payload["name"] == review_rounds.CHECK_NAME
    assert payload["conclusion"] == conclusion


def test_the_check_run_is_anchored_to_the_pr_head() -> None:
    """이벤트가 무엇이든 head SHA 에 붙어야 required check 로 성립한다."""
    fake = FakeGitHub(files=["docs/README.md"], head="head-sha")
    review_rounds.publish_check(fake, evaluate(fake, PR, now=NOW))
    _, payload = fake.posted[0]
    assert payload["head_sha"] == "head-sha"
    assert payload["conclusion"] == "success"
