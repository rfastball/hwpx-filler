"""리뷰 정산 판독기의 계약(`docs/REVIEW_POLICY.md`).

실 API 를 부르지 않는다 — `gh` seam 을 고정 응답 대역으로 갈아 끼운다. 리뷰 상태는 우리가
만들 수 없는 원격 사실이라 픽스처로 재현해야 **양성·음성 두 대조**를 각각 세울 수 있다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
        recalls: list[dict] | None = None,
    ) -> None:
        self.repo = "rfastball/hwpx-filler"
        self.head = head
        self.files = files if files is not None else ["src/a.py"]
        self.threads = threads or []
        self.reactions = reactions or []
        self.issues = issues or {}
        self.recalls = recalls or []
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
            return {"number": PR, "state": "open", "head": {"sha": self.head, "ref": "topic"}}
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
        if path == "pulls?state=open":
            return [{"number": PR, "head": {"sha": self.head, "ref": "topic"}}]
        if path == f"pulls/{PR}/files":
            return [{"filename": name} for name in self.files]
        if path == f"issues/{PR}/comments":
            return self.recalls
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


def _recall(when: datetime, association: str = "OWNER") -> dict:
    return {
        "body": "@codex review",
        "author_association": association,
        "created_at": when.isoformat().replace("+00:00", "Z"),
    }


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


def test_defer_needs_an_issue_that_exists() -> None:
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


def test_a_defer_survives_its_issue_being_closed() -> None:
    """남의 이슈 정리가 무관한 PR 을 빨갛게 만들지 않는다 — 실재는 남는다. 닫힌 이슈도
    증거는 증거이고, 「안 끝난 것」과 「틀린 것」은 다른 색이어야 한다."""
    fake = FakeGitHub(
        head="c1",
        threads=[_thread(1, "c1", replies=["triage: defer #77"])],
        issues={77: {"number": 77, "state": "closed"}},
        reactions=[_reaction("+1")],
    )
    assert evaluate(fake, PR, now=NOW).status == READY


def test_a_defer_without_a_number_is_not_a_settlement() -> None:
    """이슈를 지목하지 않는 분리는 문법에서 이미 성립하지 않는다."""
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", replies=["triage: defer"])])
    report = evaluate(fake, PR, now=NOW)
    assert [f.id for f in report.unsettled] == [1] and report.status != READY


# ── 빠른 경로 ──────────────────────────────────────────────────────────────────


def test_prose_only_changes_take_the_fast_path() -> None:
    fake = FakeGitHub(
        files=["docs/README.md", "README.md", "docs/UI_GALLERY.html"],
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
        # 규칙서는 규칙의 대상이다 — 빠른 경로면 리뷰 규칙을 무리뷰로 고칠 수 있다.
        "docs/REVIEW_POLICY.md",
        "CLAUDE.md",
        "AGENTS.md",
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


def test_a_fixed_pull_request_does_not_time_out_before_the_recall_is_posted() -> None:
    """픽스 뒤의 회수 창은 재호출이 선행해야 돈다 — 안 부르면 10분이 지나도 안 닫힌다.
    종전에는 여기가 뚫려 「픽스가 읽힐 때까지 막는다」던 문서가 거짓말이었다."""
    fake = FakeGitHub(
        head="c9", threads=[_thread(1, "c1", resolved=True, replies=["triage: block:2"])]
    )
    report = evaluate(fake, PR, now=PUSHED + review_rounds.RECOVERY_WINDOW + timedelta(hours=3))
    assert not report.timed_out and report.needs_recall and report.status == WAIT


def test_a_fixed_pull_request_times_out_after_the_recall_went_unanswered() -> None:
    """양성 대조 — 재호출을 불렀는데도 리뷰어가 침묵하면 창 소진으로 시끄럽게 닫힌다."""
    called = PUSHED + timedelta(minutes=1)
    fake = FakeGitHub(
        head="c9",
        threads=[_thread(1, "c1", resolved=True, replies=["triage: block:2"])],
        recalls=[_recall(called)],
    )
    report = evaluate(fake, PR, now=called + review_rounds.RECOVERY_WINDOW + timedelta(seconds=1))
    assert report.timed_out and report.status == READY


def test_the_recall_window_counts_from_the_call_not_the_push() -> None:
    """재호출이 push 보다 한참 늦었으면 창도 거기서부터다 — push 시각으로 재면 부르자마자
    이미 소진돼 있어 재리뷰가 읽힐 틈이 없다."""
    called = PUSHED + review_rounds.RECOVERY_WINDOW + timedelta(minutes=30)
    fake = FakeGitHub(
        head="c9",
        threads=[_thread(1, "c1", resolved=True, replies=["triage: block:2"])],
        recalls=[_recall(called)],
    )
    report = evaluate(fake, PR, now=called + timedelta(minutes=5))
    assert not report.timed_out and report.status == WAIT


def test_a_recall_posted_before_the_push_does_not_count() -> None:
    """순서가 계약이다 — push 앞의 재호출은 리뷰어가 옛 head 를 읽었다는 뜻이라, 그것으로
    창을 돌리면 픽스는 안 읽힌 채 초록이 된다."""
    fake = FakeGitHub(
        head="c9",
        threads=[_thread(1, "c1", resolved=True, replies=["triage: block:2"])],
        recalls=[_recall(PUSHED - timedelta(minutes=30))],
    )
    report = evaluate(fake, PR, now=PUSHED + review_rounds.RECOVERY_WINDOW + timedelta(hours=1))
    assert not report.timed_out and report.status == WAIT


def test_an_outsiders_recall_does_not_open_the_window() -> None:
    """남이 재호출 코멘트를 달아 잠금을 밖에서 풀 수 없다."""
    called = PUSHED + timedelta(minutes=1)
    fake = FakeGitHub(
        head="c9",
        threads=[_thread(1, "c1", resolved=True, replies=["triage: block:2"])],
        recalls=[_recall(called, association="NONE")],
    )
    report = evaluate(fake, PR, now=called + review_rounds.RECOVERY_WINDOW + timedelta(hours=1))
    assert not report.timed_out and report.status == WAIT


def test_the_reviewers_graphql_spelling_still_counts() -> None:
    """같은 봇을 REST 는 `…[bot]`, GraphQL 은 접미사 없이 쓴다 — 실주행 양성 대조가 잡은
    결함이다(지적 15건이 0건으로 읽혔다). 표기 하나로 걸면 다른 경로가 조용히 남이 된다."""
    bare = REVIEWER.removesuffix("[bot]")
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", author=bare)])
    report = evaluate(fake, PR, now=NOW)
    assert report.reviewed and [f.id for f in report.unsettled] == [1]


def test_reviewer_logins_rotate_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """봇 로그인이 바뀌면 코드 수정 없이 env 로 회전한다."""
    monkeypatch.setenv("REVIEW_GATE_REVIEWERS", "new-reviewer[bot]")
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", author="new-reviewer[bot]")])
    report = evaluate(fake, PR, now=NOW)
    assert report.reviewed
    assert [f.id for f in report.unsettled] == [1]

    stale = FakeGitHub(head="c1", threads=[_thread(1, "c1")])  # 옛 로그인
    assert not evaluate(stale, PR, now=NOW).reviewed


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


# ── 입구 훅: 발행 인지와 정산 전 종료 차단 ─────────────────────────────────────
#
# 머지 훅은 루프의 **출구**에 선다. 발행하고 아무것도 안 한 채 턴이 끝나는 길은 그 훅이 영영
# 못 본다 — 머지를 시도하지 않으니까. 아래 둘이 그 입구를 맡는다.


@pytest.fixture
def watch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """감시 목록을 임시 폴더로 못박는다 — 실제 `.git/` 을 건드리지 않는다."""
    path = tmp_path / review_rounds.WATCH_FILE
    monkeypatch.setattr(review_rounds, "_watch_path", lambda: path)
    return path


class JustPushed(FakeGitHub):
    """회수 창이 아직 도는 PR.

    훅은 `evaluate` 를 **실시간**으로 부른다 — 고정 픽스처 시각을 쓰면 창이 이미 지난 것으로
    읽혀 대기가 통째로 `READY` 가 되고, 이 축의 음성 대조가 사라진다.
    """

    def get(self, path: str) -> dict:
        if path.endswith("/check-suites"):
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return {
                "check_suites": [
                    {"created_at": now, "head_branch": "topic", "pull_requests": [{"number": PR}]}
                ]
            }
        return super().get(path)


def test_the_post_hook_ignores_commands_that_do_not_create_a_pr(watch: Path) -> None:
    payload = json.dumps({"tool_input": {"command": "gh pr view 430"}})
    assert review_rounds._hook_post(payload) == 0
    assert not watch.exists()


def test_the_post_hook_records_the_new_pr_and_tells_the_session(
    watch: Path, capsys: pytest.CaptureFixture
) -> None:
    """훅은 스킬을 대신 부를 수 없다 — 확정할 수 있는 것은 **인지**뿐이라 그것을 확정한다."""
    payload = json.dumps(
        {
            "tool_input": {"command": "gh pr create --fill"},
            "tool_response": {"stdout": "https://github.com/rfastball/hwpx-filler/pull/456\n"},
        }
    )
    assert review_rounds._hook_post(payload) == 0
    assert json.loads(watch.read_text(encoding="utf-8")) == {"456": {"holds": 0}}
    spoken = json.loads(capsys.readouterr().out)
    assert "/review-round" in spoken["hookSpecificOutput"]["additionalContext"]


def test_the_post_hook_stays_silent_when_the_creation_failed(
    watch: Path, capsys: pytest.CaptureFixture
) -> None:
    """명령만 보고 기록하면 실패한 발행이 감시 목록에 올라 매 턴 판정 실패로 시끄러워진다."""
    payload = json.dumps(
        {
            "tool_input": {"command": "gh pr create --fill"},
            "tool_response": {"stderr": "a pull request already exists"},
        }
    )
    assert review_rounds._hook_post(payload) == 0
    assert not watch.exists()
    assert capsys.readouterr().out == ""


def test_the_stop_hook_does_nothing_without_a_watched_pr(
    watch: Path, capsys: pytest.CaptureFixture
) -> None:
    """감시할 PR 이 없으면 API 도 안 부른다 — 모든 턴 끝에서 도는 훅이라 침묵이 기본값이다."""
    assert review_rounds._hook_stop("{}") == 0
    assert capsys.readouterr().out == ""


def test_the_stop_hook_holds_the_turn_until_the_review_is_settled(
    watch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    watch.write_text(json.dumps({str(PR): {"holds": 0}}), encoding="utf-8")
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", replies=["triage: block:2"])])
    monkeypatch.setattr(GitHub, "discover", staticmethod(lambda: fake))
    assert review_rounds._hook_stop("{}") == 0
    spoken = json.loads(capsys.readouterr().out)
    assert spoken["decision"] == "block"
    assert "/review-round" in spoken["reason"]
    assert json.loads(watch.read_text(encoding="utf-8")) == {str(PR): {"holds": 1}}


def test_the_stop_hook_holds_a_pr_that_is_still_waiting_for_its_review(
    watch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """**발행 직후의 `WAIT` 이 곧 루프가 끊기는 지점이다.** 대기를 놓아 주면 이 훅이 겨눈 것을
    그대로 놓친다 — 지적이 아직 하나도 없는 상태가 정확히 그 모양이다."""
    watch.write_text(json.dumps({str(PR): {"holds": 0}}), encoding="utf-8")
    fake = JustPushed(head="c1", threads=[])
    monkeypatch.setattr(GitHub, "discover", staticmethod(lambda: fake))
    assert review_rounds._hook_stop("{}") == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "block"


def test_the_stop_hook_releases_a_settled_pr(
    watch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    watch.write_text(json.dumps({str(PR): {"holds": 1}}), encoding="utf-8")
    fake = FakeGitHub(files=["docs/README.md"])  # 빠른 경로 → READY
    monkeypatch.setattr(GitHub, "discover", staticmethod(lambda: fake))
    assert review_rounds._hook_stop("{}") == 0
    assert not watch.exists(), "정산이 끝난 PR 을 계속 감시하면 매 턴 API 를 헛되이 친다"
    assert capsys.readouterr().out == ""


def test_the_stop_hook_drops_a_pr_that_is_no_longer_open(
    watch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watch.write_text(json.dumps({str(PR): {"holds": 0}}), encoding="utf-8")

    class Merged(FakeGitHub):
        def get(self, path: str) -> dict:
            if path == f"pulls/{PR}":
                return {"number": PR, "state": "closed", "head": {"sha": self.head}}
            raise AssertionError("닫힌 PR 을 계속 판정했습니다")

    monkeypatch.setattr(GitHub, "discover", staticmethod(lambda: Merged()))
    assert review_rounds._hook_stop("{}") == 0
    assert not watch.exists()


def test_the_stop_hook_lets_go_after_the_hold_budget(
    watch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """플랫폼에는 「이 종료가 훅 때문인가」를 알려 주는 표시가 없다 — 우리가 세지 않으면
    리뷰가 영영 안 오는 PR 에서 세션이 못 빠져나온다."""
    spent = json.dumps({str(PR): {"holds": review_rounds.STOP_HOLD_BUDGET}})
    watch.write_text(spent, encoding="utf-8")
    fake = FakeGitHub(head="c1", threads=[_thread(1, "c1", replies=["triage: block:2"])])
    monkeypatch.setattr(GitHub, "discover", staticmethod(lambda: fake))
    assert review_rounds._hook_stop("{}") == 0
    spoken = json.loads(capsys.readouterr().out)
    assert "decision" not in spoken, "예산을 넘기고도 붙잡으면 무한 루프다"
    assert "사람 판단" in spoken["systemMessage"], "놓을 때는 조용히 놓지 않는다"
    assert not watch.exists()


def test_the_stop_hook_does_not_brick_the_session_when_github_is_unreachable(
    watch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """조회 불가는 판정 불가다. 그렇다고 붙잡으면 인증 하나 끊긴 것이 세션을 벽돌로 만든다 —
    실제 게이트는 required check 라 놓아 주어도 머지는 못 한다."""
    watch.write_text(json.dumps({str(PR): {"holds": 0}}), encoding="utf-8")

    def explode() -> GitHub:
        raise GitHubError("gh 미인증")

    monkeypatch.setattr(GitHub, "discover", staticmethod(explode))
    assert review_rounds._hook_stop("{}") == 0
    spoken = json.loads(capsys.readouterr().out)
    assert "decision" not in spoken
    assert "읽지 못했습니다" in spoken["systemMessage"]
    assert watch.exists(), "판정하지 못한 PR 을 감시에서 지우면 다음 턴에 다시 보지 못한다"


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


def test_the_sweep_publishes_verdicts_without_a_pending_overlay() -> None:
    """스윕은 이벤트 경로와 다른 concurrency 그룹이라 서로 취소하지 못한다 — 느린 스윕이
    pending 을 깔면 최신 판정을 in_progress 로 가리거나 실패 시 고아로 남긴다."""
    fake = FakeGitHub(files=["docs/README.md"])
    assert review_rounds._sweep(fake) == 0
    assert fake.posted, "스윕이 판정을 게시하지 않았습니다"
    assert all(payload["status"] == "completed" for _, payload in fake.posted)


def test_the_check_run_is_anchored_to_the_pr_head() -> None:
    """이벤트가 무엇이든 head SHA 에 붙어야 required check 로 성립한다."""
    fake = FakeGitHub(files=["docs/README.md"], head="head-sha")
    review_rounds.publish_check(fake, evaluate(fake, PR, now=NOW))
    _, payload = fake.posted[0]
    assert payload["head_sha"] == "head-sha"
    assert payload["conclusion"] == "success"
