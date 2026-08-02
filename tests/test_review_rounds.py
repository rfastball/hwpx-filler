"""리뷰 정산 판독기의 계약(`docs/REVIEW_POLICY.md`).

실 API 를 부르지 않는다 — `gh` seam 을 고정 응답 대역으로 갈아 끼운다. 리뷰 상태는 우리가
만들 수 없는 원격 사실이라 픽스처로 재현해야 **양성·음성 두 대조**를 각각 세울 수 있다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts import review_rounds
from scripts.review_rounds import (
    BLOCKED,
    READY,
    WAIT,
    GitHub,
    GitHubError,
    NotFound,
    evaluate,
)

PR = 430
NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
PUSHED = NOW - timedelta(minutes=1)

REVIEWER = review_rounds.REVIEWER_LOGINS[0]


def _reply(body: str, association: str = "OWNER") -> dict:
    return {"body": body, "association": association}


def _thread(
    thread_id: int,
    commit: str,
    *,
    path: str = "src/a.py",
    line: int | None = 10,
    author: str = REVIEWER,
    replies: list[str | dict] | tuple = (),
    resolved: bool = False,
    outdated: bool = False,
) -> dict:
    return {
        "id": thread_id,
        "commit": commit,
        "path": path,
        "line": line,
        "author": author,
        "replies": [r if isinstance(r, dict) else _reply(r) for r in replies],
        "resolved": resolved,
        "outdated": outdated,
    }


class FakeGitHub:
    """`GitHub` 와 같은 표면만 갖는 대역."""

    def __init__(
        self,
        *,
        head: str = "c1",
        files: list[str] | None = None,
        threads: list[dict] | None = None,
        reactions: list[dict] | None = None,
        issues: dict[int, dict] | None = None,
    ) -> None:
        self.repo = "rfastball/hwpx-filler"
        self.head = head
        self.files = files if files is not None else ["src/a.py"]
        self.threads = threads or []
        self.reactions = reactions or []
        self.issues = issues or {}
        self.posted: list[tuple[str, dict]] = []
        self.resolved: set[int] = set()

    def graphql(self, query: str, **variables: object) -> dict:
        """스레드를 한 쪽에 하나씩만 실어 **페이지를 끝까지 도는지** 시험한다."""
        index = int(variables.get("after") or 0)
        nodes = []
        for thread in self.threads[index : index + 1]:
            comments = [
                {
                    "databaseId": thread["id"],
                    "body": f"finding {thread['id']}",
                    "authorAssociation": "NONE",
                    "author": {"login": thread["author"]},
                    "originalCommit": {"oid": thread["commit"]},
                }
            ]
            for offset, reply in enumerate(thread["replies"], start=1):
                comments.append(
                    {
                        "databaseId": thread["id"] * 1000 + offset,
                        "body": reply["body"],
                        "authorAssociation": reply["association"],
                        "author": {"login": "rfastball"},
                        "originalCommit": {"oid": thread["commit"]},
                    }
                )
            nodes.append(
                {
                    "isResolved": thread["resolved"] or thread["id"] in self.resolved,
                    "isOutdated": thread["outdated"],
                    "path": thread["path"],
                    "line": thread["line"],
                    "comments": {"nodes": comments},
                }
            )
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {
                                "hasNextPage": index + 1 < len(self.threads),
                                "endCursor": str(index + 1),
                            },
                            "nodes": nodes,
                        }
                    }
                }
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
        if path.startswith("issues/"):
            number = int(path.split("/", 1)[1])
            if number not in self.issues:
                raise NotFound(f"404 issues/{number}")
            return self.issues[number]
        raise AssertionError(f"예상하지 못한 조회: {path}")

    def paged(self, path: str) -> list[dict]:
        if path == f"pulls/{PR}/files":
            return [{"filename": name} for name in self.files]
        if path == f"issues/{PR}/reactions":
            return self.reactions
        raise AssertionError(f"예상하지 못한 목록 조회: {path}")

    def pr_for_current_branch(self) -> int:
        return PR


def _reaction(content: str, *, login: str = REVIEWER) -> dict:
    return {
        "content": content,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "user": {"login": login},
    }


def _open_issue(number: int) -> dict:
    return {"number": number, "state": "open"}


# ── 정산 완결성 ────────────────────────────────────────────────────────────────


def test_an_unsettled_finding_holds_the_gate() -> None:
    fake = FakeGitHub(
        head="c1",
        threads=[
            _thread(1, "c1", line=None, resolved=True, replies=["triage: block:3"]),
            _thread(2, "c1"),
        ],
    )
    report = evaluate(fake, PR, now=NOW)
    assert report.status == WAIT
    assert [f.id for f in report.unsettled] == [2]


def test_settled_and_resolved_findings_are_ready() -> None:
    """정산이 끝나고 차단이 해결됐으면 머지 가능이다."""
    fake = FakeGitHub(
        head="c1",
        threads=[_thread(1, "c0", line=None, resolved=True, replies=["triage: block:2"])],
        reactions=[_reaction("+1")],
    )
    report = evaluate(fake, PR, now=NOW)
    assert report.status == READY
    assert report.open_blocks == []


def test_a_resolved_thread_closes_a_block_even_while_the_comment_lives() -> None:
    """GitHub 은 앵커 hunk 가 살아 있으면 코멘트를 재앵커해 유지한다 — 바로 옆을 고쳐도
    outdated 가 되지 않으므로 그것만으로는 해소를 못 잰다. 스레드 해결이 옳은 신호다."""
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", replies=["triage: block:2"])])
    fake.resolved.add(1)
    report = evaluate(fake, PR, now=NOW)
    assert report.open_blocks == []


def test_an_outdated_block_still_needs_an_explicit_resolution() -> None:
    """outdated 는 부수 효과다 — 무관한 코드가 밀려 앵커가 사라져도 그렇게 된다."""
    fake = FakeGitHub(
        head="c1",
        threads=[_thread(1, "c1", line=None, outdated=True, replies=["triage: block:2"])],
    )
    report = evaluate(fake, PR, now=NOW)
    assert [f.id for f in report.open_blocks] == [1] and report.status == BLOCKED


def test_resolutions_beyond_the_first_page_are_seen() -> None:
    """첫 쪽만 보고 판정하면 그 뒤의 해결은 없는 것이 되고, 일부만 본 판정이 전부처럼 보인다."""
    threads = [
        _thread(i, "c1", line=None, resolved=True, replies=["triage: block:2"])
        for i in range(1, 6)
    ]
    fake = FakeGitHub(head="c1", threads=threads)
    assert evaluate(fake, PR, now=NOW).open_blocks == []


def test_a_block_that_is_still_live_blocks() -> None:
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", replies=["triage: block:1"])])
    report = evaluate(fake, PR, now=NOW)
    assert report.status == BLOCKED
    assert [f.id for f in report.open_blocks] == [1]


# ── 마커 문법 — 스레드 안의 답글이 정산이다 ────────────────────────────────────


def test_a_block_without_a_litmus_number_is_not_a_settlement() -> None:
    """어느 조항(①②③)이 참인지 말하지 못하는 차단은 정책의 정의상 분리다 — 그 마찰이
    「전부 차단」으로 쏠리는 손을 붙잡는 계약이다(§1)."""
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", replies=["triage: block"])])
    assert [f.id for f in evaluate(fake, PR, now=NOW).unsettled] == [1]


def test_the_old_top_level_marker_grammar_does_not_settle() -> None:
    """옛 문법(코멘트 id 지목)은 폐기됐다 — 반쯤 받아 주면 두 문법이 따로 늙는다."""
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", replies=["triage: 1 block"])])
    assert [f.id for f in evaluate(fake, PR, now=NOW).unsettled] == [1]


def test_an_outsiders_reply_does_not_settle() -> None:
    """공개 PR 에서는 아무나 답글을 달 수 있다 — 남이 게이트를 열 수 없어야 한다."""
    fake = FakeGitHub(
        head="c1",
        threads=[_thread(1, "c1", replies=[_reply("triage: block:2", association="NONE")])],
    )
    assert [f.id for f in evaluate(fake, PR, now=NOW).unsettled] == [1]


def test_the_last_marker_in_a_thread_wins() -> None:
    """판정을 바꿨으면 답글 하나로 덮는다 — 앞 마커를 지우러 다니지 않는다."""
    fake = FakeGitHub(
        head="c1",
        threads=[
            _thread(1, "c0", resolved=True, replies=["triage: block:2", "triage: defer #77"])
        ],
        issues={77: _open_issue(77)},
        reactions=[_reaction("+1")],
    )
    report = evaluate(fake, PR, now=NOW)
    assert report.status == READY  # defer 로 끝났으니 재리뷰도 필요 없다


def test_a_prose_reply_does_not_create_its_own_settlement_duty() -> None:
    """답글은 지적이 아니다 — 우리가 쓴 해명이 스스로 게이트를 세우면 안 된다."""
    fake = FakeGitHub(
        head="c1",
        threads=[
            _thread(1, "c1", line=None, replies=["이건 왜 이렇게 했는지 해명이다", "triage: defer #77"])
        ],
        issues={77: _open_issue(77)},
        reactions=[_reaction("+1")],
    )
    report = evaluate(fake, PR, now=NOW)
    assert report.unsettled == [] and report.status == READY


# ── 분리는 이슈 실재로 확인된다 ────────────────────────────────────────────────


def test_defer_needs_an_issue_that_exists_and_is_open() -> None:
    fake = FakeGitHub(
        head="c1",
        threads=[_thread(1, "c1", replies=["triage: defer #77"])],
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
    fake = FakeGitHub(
        head="c1", threads=[_thread(1, "c1", replies=["triage: defer #77"])], issues=issues
    )
    report = evaluate(fake, PR, now=NOW)
    assert report.status == BLOCKED
    assert fragment in report.bad_defers[0][1]


def test_a_defer_without_a_number_is_not_a_settlement() -> None:
    """이슈를 지목하지 않는 분리는 문법에서 이미 성립하지 않는다."""
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", replies=["triage: defer"])])
    report = evaluate(fake, PR, now=NOW)
    assert [f.id for f in report.unsettled] == [1] and report.status != READY


# ── 빠른 경로 ──────────────────────────────────────────────────────────────────


def test_prose_only_changes_take_the_fast_path() -> None:
    fake = FakeGitHub(
        files=["docs/README.md", "CLAUDE.md", "docs/UI_GALLERY.html"],
        threads=[_thread(1, "c1")],
    )
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
    fake = FakeGitHub(files=["docs/README.md", path], threads=[_thread(1, "c1")])
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

    assert not evaluate(Renaming(threads=[_thread(1, "c1")]), PR, now=NOW).fast_path


def test_a_root_level_html_asset_is_not_prose() -> None:
    """루트의 `.html` 은 산문이 아니라 실행되는 웹 자산일 수 있다 — 문서는 root 를 `.md` 로 적었다."""
    assert not evaluate(FakeGitHub(files=["index.html"], threads=[_thread(1, "c1")]), PR, now=NOW).fast_path


def test_an_empty_diff_is_not_a_fast_path() -> None:
    """변경이 없으면 「산문뿐」이 공허하게 참이 된다 — 그 길로 초록이 나가지 않는다."""
    assert not evaluate(FakeGitHub(files=[], threads=[_thread(1, "c1")]), PR, now=NOW).fast_path


# ── 리뷰 회수 ────────────────────────────────────────────────────────────────


def test_the_gate_waits_until_the_pull_request_has_been_read_at_all() -> None:
    """자동 리뷰는 PR 당 한 번이다 — 「마지막 push 를 봤는가」를 물으면 고칠 때마다 다시 안
    읽힌 상태가 돼 영영 안 닫힌다. 묻는 것은 「한 번이라도 읽혔는가」다."""
    report = evaluate(FakeGitHub(head="c1", threads=[]), PR, now=NOW)
    assert report.status == WAIT and not report.reviewed


def test_a_defer_only_settlement_survives_a_later_push() -> None:
    """분리만 했으면 코드가 안 바뀌었다 — 다시 읽힐 이유가 없다."""
    fake = FakeGitHub(
        head="c9",
        threads=[_thread(1, "c1", replies=["triage: defer #77"])],
        issues={77: _open_issue(77)},
    )
    assert evaluate(fake, PR, now=NOW).status == READY


def test_fixing_a_block_requires_the_result_to_be_read_again() -> None:
    """자동 리뷰가 PR 당 한 번인데 여기서 놓아 주면 라운드 폭증을 **미검토**로 맞바꾼다 —
    초기 diff 만 읽히고 그 뒤 픽스는 영영 안 읽힌 채 머지된다."""
    fake = FakeGitHub(
        head="c9", threads=[_thread(1, "c1", resolved=True, replies=["triage: block:2"])]
    )
    report = evaluate(fake, PR, now=NOW)
    assert report.needs_recall and report.status == WAIT
    assert "@codex review" in review_rounds.render(report)


def test_a_block_on_the_current_head_cannot_be_closed_without_pushing_the_fix() -> None:
    """그 지적은 바로 이 코드에 대한 것이니 고침은 아직 여기 없다 — 마커와 스레드 해결만으로
    초록이 되면 결함을 그대로 둔 채 머지된다."""
    fake = FakeGitHub(
        head="c1", threads=[_thread(1, "c1", resolved=True, replies=["triage: block:2"])]
    )
    report = evaluate(fake, PR, now=NOW)
    assert report.needs_recall and report.status == WAIT


def test_the_recovery_window_cannot_rescue_an_unpushed_fix() -> None:
    """나가는 문이 여럿이면 잠금은 문마다 다시 걸어야 한다 — 그래서 문을 하나로 뒀다.
    회수 창은 리뷰어가 안 왔을 때의 탈출구지, 고치지 않은 차단의 탈출구가 아니다."""
    fake = FakeGitHub(
        head="c1", threads=[_thread(1, "c1", resolved=True, replies=["triage: block:2"])]
    )
    report = evaluate(fake, PR, now=PUSHED + review_rounds.RECOVERY_WINDOW + timedelta(minutes=5))
    assert not report.timed_out and report.status == WAIT


def test_a_reviewer_who_read_the_fix_closes_it() -> None:
    """양성 대조 — 재리뷰가 head 를 짚었으면 그 픽스는 읽힌 것이다."""
    fake = FakeGitHub(
        head="c9",
        threads=[
            _thread(1, "c1", resolved=True, replies=["triage: block:2"]),
            _thread(2, "c9", replies=["triage: defer #77"]),
        ],
        issues={77: _open_issue(77)},
    )
    report = evaluate(fake, PR, now=NOW)
    assert not report.needs_recall and report.status == READY


def test_an_authored_thread_is_neither_a_review_nor_a_duty() -> None:
    """작성자가 인라인 코멘트를 달아 「읽혔다」를 스스로 만들 수 없고, 자기 메모가 정산
    의무를 만들지도 않는다 — 그 스레드의 해결은 룰셋(대화 해결 필수)이 따로 강제한다."""
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", author="rfastball")])
    report = evaluate(fake, PR, now=NOW)
    assert not report.reviewed and report.status == WAIT
    assert report.unsettled == []


def test_only_the_reviewer_can_signal_no_findings() -> None:
    """작성자가 자기 PR 에 `+1` 을 달아 리뷰 없이 초록을 만들면 게이트가 거짓말한다."""
    fake = FakeGitHub(head="c1", threads=[], reactions=[_reaction("+1", login="rfastball")])
    report = evaluate(fake, PR, now=NOW)
    assert report.signal is None and report.status == WAIT


def test_the_reviewers_thumbs_up_closes_a_finding_free_pull_request() -> None:
    """양성 대조 — 지적이 없으면 리뷰 결과는 리액션으로만 온다."""
    fake = FakeGitHub(head="c1", threads=[], reactions=[_reaction("+1")])
    assert evaluate(fake, PR, now=NOW).status == READY


def test_eyes_is_not_a_no_findings_signal() -> None:
    """`eyes` 는 진행 중이다 — `+1` 과 혼동하면 리뷰를 안 기다리고 넘어간다."""
    fake = FakeGitHub(head="c1", threads=[], reactions=[_reaction("eyes")])
    report = evaluate(fake, PR, now=NOW)
    assert report.signal == "eyes" and report.status == WAIT


def test_the_window_is_measured_from_the_push_not_the_commit_date() -> None:
    """cherry-pick 한 커밋은 만들어진 지 오래다 — 커밋 시각으로 재면 첫 판정부터 창이 지난다."""

    class OldCommitJustPushed(FakeGitHub):
        def get(self, path: str) -> dict:
            if path.endswith("/check-suites"):
                return {
                    "check_suites": [
                        {
                            "created_at": NOW.isoformat().replace("+00:00", "Z"),
                            "head_branch": "topic",
                            "pull_requests": [{"number": PR}],
                        }
                    ]
                }
            return super().get(path)

    report = evaluate(OldCommitJustPushed(head="c1", threads=[]), PR, now=NOW + timedelta(minutes=1))
    assert report.status == WAIT and not report.timed_out


def test_a_head_with_no_check_suite_has_not_timed_out() -> None:
    """방금 올라와 CI 도 안 붙은 SHA 를 「창이 지났다」로 읽지 않는다."""

    class NoSuiteYet(FakeGitHub):
        def get(self, path: str) -> dict:
            if path.endswith("/check-suites"):
                return {"check_suites": []}
            return super().get(path)

    assert not evaluate(NoSuiteYet(head="c1", threads=[]), PR, now=NOW).timed_out


def test_the_recovery_window_closes_on_its_own_but_says_so() -> None:
    """창 소진은 리뷰가 아니라 **교착 탈출**이다. 조용히 초록이 되면 「리뷰를 받았다」와
    「리뷰어가 침묵했다」가 같은 색이 된다."""
    fake = FakeGitHub(head="c1", threads=[])
    report = evaluate(fake, PR, now=PUSHED + review_rounds.RECOVERY_WINDOW + timedelta(seconds=1))
    assert report.status == READY and report.timed_out
    assert "받지 못한 채" in review_rounds.render(report)

    review_rounds.publish_check(fake, report)
    assert "회수 창 소진" in fake.posted[0][1]["output"]["title"]


def test_a_reviewed_pull_request_is_not_marked_as_timed_out() -> None:
    """음성 대조 — 신호를 받고 닫힌 것은 침묵으로 닫힌 것과 다르다."""
    fake = FakeGitHub(head="c1", threads=[], reactions=[_reaction("+1")])
    report = evaluate(fake, PR, now=PUSHED + review_rounds.RECOVERY_WINDOW + timedelta(seconds=1))
    assert report.status == READY and not report.timed_out


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
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", replies=["triage: block:2"])])
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

    fake = WrongBranch(head="c1", threads=[_thread(1, "c1", replies=["triage: block:2"])])
    monkeypatch.setattr(GitHub, "discover", staticmethod(lambda: fake))
    assert review_rounds._hook(json.dumps({"tool_input": {"command": command}})) == 2


def test_the_hook_allows_a_ready_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGitHub(files=["docs/README.md"])
    monkeypatch.setattr(GitHub, "discover", staticmethod(lambda: fake))
    payload = json.dumps({"tool_input": {"command": "gh pr merge 430 --squash"}})
    assert review_rounds._hook(payload) == 0


# ── 체크런 게시 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("replies", "status", "conclusion"),
    [
        (["triage: block:2"], BLOCKED, "failure"),
        ([], WAIT, "action_required"),
    ],
)
def test_the_check_run_carries_the_verdict(replies: list[str], status: str, conclusion: str) -> None:
    """`success` 만 머지를 연다. 아직 안 끝난 것과 틀린 것은 다른 색으로 찍는다."""
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", replies=replies)])
    report = evaluate(fake, PR, now=NOW)
    assert report.status == status
    review_rounds.publish_check(fake, report)
    path, payload = fake.posted[0]
    assert path == "check-runs"
    assert payload["name"] == review_rounds.CHECK_NAME
    assert payload["conclusion"] == conclusion


def test_a_pending_check_lands_before_the_verdict_is_recomputed() -> None:
    """재평가가 도중에 실패하면 이전 초록이 그대로 권위로 남는다 — 읽기 전에 덮는다."""
    fake = FakeGitHub(head="head-sha")
    review_rounds.publish_pending(fake, "head-sha")
    _, payload = fake.posted[0]
    assert payload["head_sha"] == "head-sha"
    assert payload["status"] == "in_progress" and "conclusion" not in payload


def test_the_check_run_is_anchored_to_the_pr_head() -> None:
    """이벤트가 무엇이든 head SHA 에 붙어야 required check 로 성립한다."""
    fake = FakeGitHub(files=["docs/README.md"], head="head-sha")
    review_rounds.publish_check(fake, evaluate(fake, PR, now=NOW))
    _, payload = fake.posted[0]
    assert payload["head_sha"] == "head-sha"
    assert payload["conclusion"] == "success"
