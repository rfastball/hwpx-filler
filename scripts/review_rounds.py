"""리뷰 정산 상태를 GitHub 상태에서만 판독한다(`docs/REVIEW_POLICY.md`).

이 스크립트는 **계측**만 한다. 「이 지적이 차단인가」는 정책 §1 리트머스로 사람·에이전트가
판정하고 §2 정산 마커 — 지적 스레드 **안의 답글** — 가 담는다. 여기서 세는 것은 그 정산의
**완결성**이다 — 판정과 계측을 한 곳에 섞으면 둘 다 못 믿게 된다.

증거는 원격 상태만 쓴다. 로컬 파일·메모는 그 PR 을 만든 쪽이 혼자 쓸 수 있어 증거가 되지
못한다.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

#: 리뷰 결과를 기다리는 창. 이 시간이 지나도록 아무 신호가 없으면 회수 창 소진으로 본다.
RECOVERY_WINDOW = timedelta(minutes=10)

# ── 신뢰의 축 ──────────────────────────────────────────────────────────────────
#
# 원격 입력마다 「이 행위자를 믿는가」를 따로 판정하면 한 군데 조이는 동안 다른 데가 열린
# 채로 남는다(실제로 리액션을 조인 라운드에 head 코멘트 경로가 그대로 열려 있었다). 축은
# 둘뿐이고, 밖에서 들어오는 모든 것이 이 둘 중 하나를 지난다.

#: 리뷰를 **낸다**고 인정하는 계정. 아니면 작성자가 자기 PR 에 `+1` 이나 인라인 코멘트를
#: 달아 「리뷰를 받았다」를 스스로 만들 수 있다.
REVIEWER_LOGINS = ("chatgpt-codex-connector[bot]",)

#: 정산을 **남긴다**고 인정하는 관계. 공개 PR 에서는 아무나 코멘트를 달 수 있고, 뒤 마커가
#: 앞 마커를 덮으므로 통제 없이 두면 남이 게이트를 열거나 붙잡아 둘 수 있다.
SETTLING_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def _is_reviewer(login: str | None) -> bool:
    return login in REVIEWER_LOGINS


def _may_settle(comment: dict) -> bool:
    association = comment.get("authorAssociation") or comment.get("author_association")
    return association in SETTLING_ASSOCIATIONS

#: 빠른 경로는 **허용 목록**이다. 금지 목록으로 짜면 새로 생긴 경로가 기본값으로 통과한다.
#:
#: `tests/`·`scripts/` 는 여기 없다. 그 둘은 게이트 기계이고, 게이트가 깨지면 계약이
#: 거짓말한다 — 101 하니스는 몇 달째 깨진 채였는데 어떤 게이트도 그것을 못 봤다(#423).
#: 실제로 PR #426 은 `scripts/`·`tests/` 만 고치고도 P1 을 2건 받았다.
#:
#: 최상위는 `.md` 뿐이다. 루트의 `.html` 은 산문이 아니라 실행되는 웹 자산일 수 있다.
FAST_PATH_ROOT_SUFFIXES = (".md",)
FAST_PATH_DOCS_SUFFIXES = (".md", ".html")

#: 허용 확장자여도 기계가 읽는 것·계약 원문·**규칙서 자신**은 뺀다. 규칙서가 빠른 경로면
#: 리뷰 규칙을 무리뷰로 고칠 수 있다 — 규칙서는 규칙의 대상이다.
FAST_PATH_EXCEPTIONS = (
    "docs/UI_CONTRACT.md",
    "docs/REVIEW_POLICY.md",
    "CLAUDE.md",
    "AGENTS.md",
)

#: 정산 마커. 지적 스레드 **안의 답글** 한 줄이다(`docs/REVIEW_POLICY.md` §2).
#:
#: 마커가 스레드에 앵커되므로 코멘트 id 를 옮겨 적는 부기가 없고, 판정이 지적 옆에 남아
#: 문맥이 보존된다. `block` 은 리트머스 번호(§1 의 ①②③)를 **반드시** 지닌다 — 어느 조항이
#: 참인지 말하지 못하는 차단은 정책의 정의상 분리다.
TRIAGE_PATTERN = re.compile(
    r"^\s*triage:\s*(?:block:(?P<litmus>[123])|defer\s+#(?P<issue>\d+))\s*$",
    re.MULTILINE,
)

READY, WAIT, BLOCKED = "READY", "WAIT", "BLOCKED"

#: 리뷰어가 배지 이미지로 싣는 심각도. **입력이지 분류가 아니다** — 표시만 하고 판정에는
#: 쓰지 않는다(정책 §1). 실제로 이 리뷰어는 P3 를 발급하지 않아, 배지에 정지 조건을 걸면
#: 종료 가지가 도달 불가능해진다.
SEVERITY_PATTERN = re.compile(r"badge/(P\d)-")

_MARKUP = (
    re.compile(r"!\[[^\]]*\]\([^)]*\)"),  # 배지 이미지
    re.compile(r"</?[^>]+>"),  # 인라인 HTML
    re.compile(r"[*_`]+"),  # 강조 기호
)


class GitHubError(RuntimeError):
    """조회가 실패했다. **조용히 통과시키지 않는다** — 판정 대신 exit 2 로 나간다."""


class NotFound(GitHubError):
    """대상이 없다. 분리 이슈 번호가 허구인 경우가 여기로 온다."""


@dataclass(frozen=True)
class Triage:
    """스레드 답글에서 읽은 정산 하나."""

    verdict: str
    litmus: int | None
    issue: int | None


@dataclass(frozen=True)
class Finding:
    """리뷰어가 뿌리인 리뷰 스레드 하나 = 정산해야 하는 지적 하나.

    리뷰어가 아닌 뿌리(작성자의 자기 메모, 지나가는 코멘트)는 정산 의무를 만들지 않는다 —
    그 스레드의 해결은 GitHub 룰셋(대화 해결 필수)이 따로 강제한다.
    """

    id: int
    path: str
    line: int | None
    commit: str
    outdated: bool
    resolved: bool
    severity: str
    excerpt: str
    triage: Triage | None

    def label(self) -> str:
        mark = "" if self.line is None else f":{self.line}"
        return f"{self.id} [{self.severity}] {self.path}{mark} — {self.excerpt}"


@dataclass
class Report:
    pr: int
    head: str
    fast_path: bool
    findings: list[Finding]
    unsettled: list[Finding]
    open_blocks: list[Finding]
    bad_defers: list[tuple[Finding, str]]
    signal: str | None
    reviewed: bool
    needs_recall: bool
    timed_out: bool
    status: str

    def as_dict(self) -> dict:
        return {
            "pr": self.pr,
            "head": self.head,
            "status": self.status,
            "fast_path": self.fast_path,
            "findings": [f.id for f in self.findings],
            "unsettled": [f.id for f in self.unsettled],
            "open_blocks": [f.id for f in self.open_blocks],
            "bad_defers": [{"finding": f.id, "reason": why} for f, why in self.bad_defers],
            "signal": self.signal,
            "reviewed": self.reviewed,
            "needs_recall": self.needs_recall,
            "timed_out": self.timed_out,
        }


class GitHub:
    """`gh` 호출 seam. 테스트는 같은 메서드를 가진 대역으로 갈아 끼운다."""

    def __init__(self, repo: str) -> None:
        self.repo = repo

    @classmethod
    def discover(cls) -> GitHub:
        return cls(cls._run(["gh", "repo", "view", "--json", "nameWithOwner"])["nameWithOwner"])

    @staticmethod
    def _run(command: list[str], stdin: str | None = None) -> dict:
        if shutil.which(command[0]) is None:
            raise GitHubError(f"{command[0]} 을 찾지 못했습니다")
        done = subprocess.run(
            command, input=stdin, capture_output=True, text=True, encoding="utf-8"
        )
        if done.returncode != 0:
            message = (done.stderr or done.stdout or "").strip()
            if "404" in message or "Not Found" in message:
                raise NotFound(message)
            raise GitHubError(message or f"{' '.join(command)} 실패")
        return json.loads(done.stdout)

    def get(self, path: str) -> dict:
        return self._run(["gh", "api", f"repos/{self.repo}/{path}"])

    def post(self, path: str, payload: dict) -> dict:
        return self._run(
            ["gh", "api", "-X", "POST", f"repos/{self.repo}/{path}", "--input", "-"],
            stdin=json.dumps(payload),
        )

    def graphql(self, query: str, **variables: str | int) -> dict:
        command = ["gh", "api", "graphql", "-f", f"query={query}"]
        for key, value in variables.items():
            command += ["-F", f"{key}={value}"]
        return self._run(command)

    def paged(self, path: str) -> list[dict]:
        """페이지를 직접 돈다 — `--paginate` 는 gh 판본에 따라 붙인 JSON 을 뱉는다."""
        joiner = "&" if "?" in path else "?"
        items: list[dict] = []
        page = 1
        while True:
            batch = self._run(
                ["gh", "api", f"repos/{self.repo}/{path}{joiner}per_page=100&page={page}"]
            )
            if not isinstance(batch, list):
                raise GitHubError(f"{path} 가 목록이 아닙니다")
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1

    def pr_for_current_branch(self) -> int:
        return int(self._run(["gh", "pr", "view", "--json", "number"])["number"])


def _moment(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


#: 지적·해결 상태·정산 답글을 **한 번에** 읽는다. 세 갈래로 나눠 읽던 시절(REST 인라인
#: 코멘트 + GraphQL 해결 상태 + 이슈 코멘트 마커)의 API 예산이 이 쿼리 하나로 줄었다.
THREAD_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$after:String){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      reviewThreads(first:100, after:$after){
        pageInfo{ hasNextPage endCursor }
        nodes{
          isResolved
          isOutdated
          path
          line
          comments(first:100){
            nodes{
              databaseId
              body
              authorAssociation
              author{ login }
              originalCommit{ oid }
            }
          }
        }
      }
    }
  }
}
"""


def _thread_triage(replies: list[dict]) -> Triage | None:
    """스레드 답글에서 정산을 읽는다. 마지막 유효 마커가 앞의 것을 덮는다.

    정산을 남길 수 있는 관계(`SETTLING_ASSOCIATIONS`)의 답글만 센다 — 공개 PR 에서는
    아무나 답글을 달 수 있고, 통제 없이 두면 남이 게이트를 열거나 붙잡아 둘 수 있다.
    """
    verdict: Triage | None = None
    for reply in replies:
        if not _may_settle(reply):
            continue
        for match in TRIAGE_PATTERN.finditer(reply.get("body") or ""):
            if match.group("litmus"):
                verdict = Triage(verdict="block", litmus=int(match.group("litmus")), issue=None)
            else:
                verdict = Triage(verdict="defer", litmus=None, issue=int(match.group("issue")))
    return verdict


def _findings(client: GitHub, pr: int) -> list[Finding]:
    """리뷰어가 뿌리인 스레드가 곧 지적이다.

    **전부** 본다 — 페이지를 끝까지 돈다. 첫 100건만 보고 판정하면 그 뒤의 해결·정산은
    없는 것이 되고, 조용히 일부만 본 판정이 전부를 본 판정처럼 보인다.

    스레드 해결(`isResolved`)만 해소의 증거로 센다. 코멘트가 outdated 가 된 것은 부수
    효과라 증거가 못 된다 — 무관한 코드가 밀려 앵커가 사라져도 outdated 가 되고, 반대로
    정말 고쳐도 GitHub 이 최신 커밋으로 재앵커해 살아남는다. 어느 쪽으로도 틀린다.

    스레드 안의 답글은 100건까지만 본다(내부 목록은 페이지를 돌지 않는다) — 답글이 그보다
    많은 스레드는 재호출 예산(정책 §3)이 먼저 막는 병리다.
    """
    owner, _, name = client.repo.partition("/")
    findings: list[Finding] = []
    cursor: str | None = None
    while True:
        # 선택 인자는 생략하거나 `null` 이 규약이다. 빈 문자열도 지금은 받아 주지만 그건
        # GitHub 의 관대함에 기대는 것이다(#448).
        extra = {"after": cursor} if cursor else {}
        page = client.graphql(THREAD_QUERY, owner=owner, name=name, number=pr, **extra)
        threads = page["data"]["repository"]["pullRequest"]["reviewThreads"]
        for thread in threads["nodes"]:
            comments = thread["comments"]["nodes"]
            if not comments:
                continue
            root = comments[0]
            if not _is_reviewer((root.get("author") or {}).get("login")):
                continue
            body = root.get("body") or ""
            severity = SEVERITY_PATTERN.search(body)
            findings.append(
                Finding(
                    id=int(root["databaseId"]),
                    path=thread.get("path") or "",
                    line=thread.get("line"),
                    commit=((root.get("originalCommit") or {}).get("oid")) or "",
                    outdated=bool(thread.get("isOutdated")),
                    resolved=bool(thread.get("isResolved")),
                    severity=severity.group(1) if severity else "??",
                    excerpt=_plain(body),
                    triage=_thread_triage(comments[1:]),
                )
            )
        info = threads["pageInfo"]
        if not info["hasNextPage"]:
            return findings
        cursor = info["endCursor"]


def _plain(body: str) -> str:
    """배지·HTML·강조를 걷어낸 첫 줄. 표에서 사람이 지적을 알아볼 만큼만 남긴다."""
    for pattern in _MARKUP:
        body = pattern.sub("", body)
    for line in body.splitlines():
        stripped = " ".join(line.split())
        if stripped:
            return stripped[:100]
    return ""


def _defer_problem(client: GitHub, triage: Triage) -> str | None:
    """분리는 이슈가 **실재해야** 성립한다. 번호만 적어서는 못 지나간다.

    열려 있음까지는 묻지 않는다 — 분리한 이슈를 누가 먼저 고쳐 닫으면 아무것도 안 틀린
    PR 이 빨간색이 된다. 「아직 안 끝난 것」과 「틀린 것」을 같은 색으로 칠하지 않는다는
    원칙이 여기도 적용된다. 실재는 남는다 — 닫힌 이슈도 증거는 증거다.
    """
    if triage.issue is None:
        return "이슈 번호가 없습니다"
    try:
        issue = client.get(f"issues/{triage.issue}")
    except NotFound:
        return f"#{triage.issue} 이슈가 없습니다"
    if "pull_request" in issue:
        return f"#{triage.issue} 은 이슈가 아니라 PR 입니다"
    return None


def _is_prose(name: str) -> bool:
    """산문 문서인가 — 최상위 `*.md` 또는 `docs/` 아래의 `.md`·`.html`."""
    if name in FAST_PATH_EXCEPTIONS:
        return False
    if "/" not in name:
        return name.endswith(FAST_PATH_ROOT_SUFFIXES)
    return name.startswith("docs/") and name.endswith(FAST_PATH_DOCS_SUFFIXES)


def _fast_path(client: GitHub, pr: int) -> bool:
    """rename 은 **양쪽 다** 산문이어야 한다.

    GitHub 은 이동한 파일의 목적지를 `filename` 에, 출발지를 `previous_filename` 에 싣는다.
    뒤엣것을 안 보면 `src/module.py` → `docs/module.md` 가 산문뿐인 변경으로 보이고, 제품
    코드를 지우면서 리뷰를 건너뛴다.
    """
    changed: list[str] = []
    for entry in client.paged(f"pulls/{pr}/files"):
        changed.append(entry["filename"])
        if entry.get("previous_filename"):
            changed.append(entry["previous_filename"])
    return bool(changed) and all(_is_prose(name) for name in changed)


def _signal(client: GitHub, pr: int) -> tuple[str | None, datetime | None]:
    """무결과는 코멘트가 아니라 리액션으로 온다. `eyes` 는 진행 중, `+1` 이 무결과다.

    **리뷰어의 리액션만 센다.** 아무나 센다면 작성자가 자기 PR 에 `+1` 을 달아 리뷰 없이
    초록을 만들 수 있다.
    """
    latest: tuple[str | None, datetime | None] = (None, None)
    for reaction in client.paged(f"issues/{pr}/reactions"):
        content = reaction.get("content")
        if content not in {"+1", "eyes"}:
            continue
        if not _is_reviewer((reaction.get("user") or {}).get("login")):
            continue
        when = _moment(reaction["created_at"])
        if latest[1] is None or when > latest[1]:
            latest = (content, when)
    return latest


def _pushed_at(client: GitHub, pull: dict, now: datetime) -> datetime:
    """이 PR 의 현재 head 가 **밀려 올라온** 시각. 커밋이 만들어진 시각이 아니다.

    `committer.date` 로 재면 cherry-pick·rebase 로 되살린 커밋이 첫 판정부터 회수 창을
    소진한 것으로 보인다 — 스택 착지가 정확히 그 모양이라(정책 §6) 리뷰를 한 번도 못 받은
    PR 이 초록이 된다.

    그렇다고 같은 SHA 의 체크 스위트를 통째로 세면 안 된다. 같은 커밋이 다른 브랜치나 다른
    PR 에서 이미 돈 적이 있으면 그때의 스위트가 함께 실려, 이 PR 로서는 처음인 판정이 이미
    창을 넘긴 것으로 보인다. **이 PR 에 딸린 스위트만** 본다.
    """
    head, branch = pull["head"]["sha"], pull["head"]["ref"]
    number = int(pull["number"])
    suites = client.get(f"commits/{head}/check-suites").get("check_suites") or []
    mine = [
        suite
        for suite in suites
        if any(int(p["number"]) == number for p in suite.get("pull_requests") or [])
        or suite.get("head_branch") == branch
    ]
    stamps = [_moment(suite["created_at"]) for suite in mine if suite.get("created_at")]
    if stamps:
        return min(stamps)
    # 이 PR 의 스위트가 아직 없다 = 방금 올라왔다. 커밋 시각으로 물러서면 창이 이미 지났다고
    # 볼 수 있으므로, 그런 경우는 **아직 안 지난 것**으로 취급하는 쪽이 안전하다.
    return now


def evaluate(client: GitHub, pr: int, now: datetime | None = None) -> Report:
    now = now or datetime.now(timezone.utc)
    pull = client.get(f"pulls/{pr}")
    head = pull["head"]["sha"]

    if _fast_path(client, pr):
        return Report(
            pr=pr,
            head=head,
            fast_path=True,
            findings=[],
            unsettled=[],
            open_blocks=[],
            bad_defers=[],
            signal=None,
            reviewed=True,
            needs_recall=False,
            timed_out=False,
            status=READY,
        )

    findings = _findings(client, pr)

    unsettled = [f for f in findings if f.triage is None]
    open_blocks = [
        f for f in findings if f.triage and f.triage.verdict == "block" and not f.resolved
    ]
    bad_defers = []
    for finding in findings:
        if finding.triage is None or finding.triage.verdict != "defer":
            continue
        problem = _defer_problem(client, finding.triage)
        if problem:
            bad_defers.append((finding, problem))

    signal, signalled_at = _signal(client, pr)
    pushed_at = _pushed_at(client, pull, now)

    # 자동 리뷰는 **PR 당 한 번** 발화한다(2026-08-02 설정 변경). 그래서 기본으로 묻는 것은
    # 「마지막 push 를 봤는가」가 아니라 **「이 PR 이 한 번이라도 읽혔는가」**다. 앞엣것을
    # 늘 물으면 고칠 때마다 다시 안 읽힌 상태가 돼 영영 안 닫힌다.
    #
    # 지적(`findings`)은 정의상 리뷰어가 뿌리인 스레드다 — 있다는 것 자체가 읽혔다는 뜻이다.
    reviewed = bool(findings) or signal == "+1"

    # **차단을 고쳤으면 그 결과가 다시 읽혀야 한다.** 고침은 새 코드이고 새 코드는 눈이
    # 필요하다 — 자동 리뷰가 한 번뿐인데 여기서 놓아 주면 라운드 폭증을 **미검토**로 맞바꾼다.
    # 분리만 했다면 코드가 안 바뀌었으므로 부를 이유가 없다.
    #
    # 재리뷰는 저절로 오지 않는다. `@codex review` 로 **우리가 부른다**(정책 §3).
    fixed_something = any(f.triage and f.triage.verdict == "block" for f in findings)

    # **하나의 긍정형 술어**로 묻는다 — 「지금 head 는 픽스가 읽힌 head 인가」.
    #
    # 종전에는 이것을 부정형 조건의 조합으로 뒀고, 그래서 초록으로 나가는 길이 하나 늘 때마다
    # (head 를 읽었다·회수 창이 지났다) `blocked_here` 를 빼먹는 사고가 반복됐다. 나가는 문이
    # 여럿이면 잠금은 문마다 다시 걸어야 한다 — 문을 하나로 만든다.
    blocked_here = any(
        f.commit == head and f.triage and f.triage.verdict == "block" for f in findings
    )
    read_head = any(f.commit == head for f in findings) or (
        signal == "+1" and signalled_at is not None and signalled_at >= pushed_at
    )
    # 차단이 지금 head 에 붙어 있으면 그 지적은 **바로 이 코드**에 대한 것이니 고침이 아직
    # 여기 없다. 그 head 는 무엇으로도 「픽스가 읽힌」 것이 되지 못한다 — 회수 창으로도.
    fix_was_read = read_head and not blocked_here
    needs_recall = fixed_something and not fix_was_read

    settled_enough = reviewed and not needs_recall
    timed_out = (
        not settled_enough and not blocked_here and now - pushed_at > RECOVERY_WINDOW
    )

    if open_blocks or bad_defers:
        status = BLOCKED
    elif unsettled or not (settled_enough or timed_out):
        status = WAIT
    else:
        status = READY

    return Report(
        pr=pr,
        head=head,
        fast_path=False,
        findings=findings,
        unsettled=unsettled,
        open_blocks=open_blocks,
        bad_defers=bad_defers,
        signal=signal,
        reviewed=reviewed,
        needs_recall=needs_recall,
        timed_out=timed_out,
        status=status,
    )


def render(report: Report) -> str:
    lines = [f"PR #{report.pr} — {report.status}"]
    if report.fast_path:
        lines.append("빠른 경로: 계약·제품 코드에 닿지 않아 리뷰 회수를 기다리지 않습니다.")
        return "\n".join(lines)

    lines.append(f"지적 {len(report.findings)}건 · 신호 {report.signal or '없음'}")
    if report.unsettled:
        lines.append("미정산:")
        lines.extend(f"  {f.label()}" for f in report.unsettled)
    if report.open_blocks:
        lines.append("미해결 차단:")
        lines.extend(f"  {f.label()}" for f in report.open_blocks)
    for finding, why in report.bad_defers:
        lines.append(f"분리 불성립: {finding.id} — {why}")
    if report.timed_out:
        lines.append(
            "회수 창이 지나도록 리뷰어가 침묵했습니다 — 리뷰를 **받지 못한 채** 닫습니다. "
            "`@codex review` 로 한 번 명시 트리거해 보고, 그래도 무응답이면 그대로 진행합니다."
        )
    elif report.needs_recall:
        lines.append(
            "차단을 고쳤으니 그 결과가 다시 읽혀야 합니다. 재리뷰는 저절로 오지 않습니다 —"
            " `gh pr comment " + str(report.pr) + ' --body "@codex review"` 로 부르십시오.'
        )
    elif not report.reviewed:
        lines.append("자동 리뷰를 아직 회수하지 못했습니다.")
    return "\n".join(lines)


#: 판정 → 체크런 결론. `success` 만 머지를 연다 — 나머지는 전부 막는다.
#:
#: `WAIT` 를 `failure` 로 찍지 않는 이유는 정직함이다. 아직 안 끝난 것과 틀린 것은 다르고,
#: 둘을 같은 빨간색으로 칠하면 빨간색이 무슨 뜻인지 아무도 안 묻게 된다.
CONCLUSIONS = {
    READY: "success",
    WAIT: "action_required",
    BLOCKED: "failure",
}

CHECK_NAME = "review-gate"


def publish_pending(client: GitHub, head: str) -> None:
    """판정을 **시작하기 전에** 그 SHA 의 초록을 내린다.

    같은 SHA 에 이미 성공한 `review-gate` 가 있는데 원격 상태가 나중에 바뀌면(새 지적이
    오거나 분리 이슈가 닫히면) 재평가가 돌아야 한다. 그 재평가가 도중에 실패하면 **이전
    초록이 그대로 권위로 남아** 이제는 미정산인 PR 이 머지될 수 있다. 판정 불가는 판정
    통과가 아니므로, 읽기 전에 먼저 대기 상태로 덮는다.
    """
    client.post(
        "check-runs",
        {
            "name": CHECK_NAME,
            "head_sha": head,
            "status": "in_progress",
            "output": {"title": "정산 상태를 다시 읽는 중", "summary": "`docs/REVIEW_POLICY.md`"},
        },
    )


def publish_check(client: GitHub, report: Report) -> None:
    """PR head SHA 에 체크런을 **직접** 게시한다.

    `issue_comment` 로 돌아간 워크플로의 기본 status 는 기본 브랜치에 붙는다 — 그러면
    required check 로 성립하지 않는다. 이벤트별로 갈리지 않게 항상 이 경로 하나만 쓴다.
    """
    body = render(report)
    client.post(
        "check-runs",
        {
            "name": CHECK_NAME,
            "head_sha": report.head,
            "status": "completed",
            "conclusion": CONCLUSIONS[report.status],
            "output": {
                "title": "READY (리뷰 없이 회수 창 소진)"
                if report.timed_out
                else f"{report.status} — 미정산 {len(report.unsettled)}건 · "
                f"미해결 차단 {len(report.open_blocks)}건",
                "summary": f"```\n{body}\n```\n\n절차: `docs/REVIEW_POLICY.md`",
            },
        },
    )


#: `gh pr merge <번호|URL>` 에서 대상 PR 을 집어낸다. 이것을 안 보고 현재 브랜치만 물으면
#: 다른 브랜치에 서서 머지할 때 **엉뚱한 PR 을 판정하고 초록을 준다**.
MERGE_TARGET = re.compile(r"gh\s+pr\s+merge\s+(?:\S*/pull/)?(\d+)")


def _sweep(client: GitHub) -> int:
    """열린 PR 을 전부 다시 판정한다.

    **리액션과 이슈 상태 변화는 워크플로 이벤트를 만들지 않는다.** 지적이 없는 PR 은 `+1`
    리액션만 받으므로 그것을 기다리는 게이트는 깨울 사건이 영영 오지 않는다. 회수 창이
    지나는 것도, 분리한 이슈가 닫히는 것도 마찬가지다. 그래서 주기적으로 훑는다.
    """
    failures = 0
    for pull in client.paged("pulls?state=open"):
        number = int(pull["number"])
        try:
            publish_pending(client, pull["head"]["sha"])
            report = evaluate(client, number)
            publish_check(client, report)
            print(f"#{number} {report.status}")
        except GitHubError as error:  # 한 PR 의 실패가 나머지를 못 보게 만들지 않는다
            failures += 1
            print(f"#{number} 판정 실패: {error}", file=sys.stderr)
    return 2 if failures else 0


def _hook(argv_json: str) -> int:
    """`gh pr merge` 직전의 빠른 실패. **게이트가 아니다** — 게이트는 required check 다."""
    try:
        payload = json.loads(argv_json)
    except json.JSONDecodeError:
        return 0
    command = ((payload.get("tool_input") or {}).get("command")) or ""
    if "gh pr merge" not in command:
        return 0
    client = GitHub.discover()
    target = MERGE_TARGET.search(command)
    report = evaluate(client, int(target.group(1)) if target else client.pr_for_current_branch())
    if report.status == READY:
        return 0
    print(render(report), file=sys.stderr)
    print("\n`/review-round` 로 정산을 마친 뒤 머지하십시오.", file=sys.stderr)
    return 2


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # cp949 콘솔에서 한글·em dash 가 깨진다
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="리뷰 라운드·정산 상태 판독")
    parser.add_argument("pr", nargs="?", type=int, help="PR 번호(생략하면 현재 브랜치)")
    parser.add_argument(
        "--all-open",
        action="store_true",
        help="열린 PR 전부를 재판정한다(리액션·이슈 상태는 이벤트를 깨우지 않는다)",
    )
    parser.add_argument("--json", action="store_true", help="기계 판독용 출력")
    parser.add_argument("--hook", action="store_true", help="stdin 의 훅 payload 를 읽는다")
    parser.add_argument(
        "--publish-check",
        action="store_true",
        help=f"판정을 PR head SHA 의 `{CHECK_NAME}` 체크런으로 게시한다(CI 용)",
    )
    args = parser.parse_args()

    try:
        if args.hook:
            return _hook(sys.stdin.read())
        client = GitHub.discover()
        if args.all_open:
            return _sweep(client)
        pr = args.pr or client.pr_for_current_branch()
        if args.publish_check:
            publish_pending(client, client.get(f"pulls/{pr}")["head"]["sha"])
        report = evaluate(client, pr)
        if args.publish_check:
            publish_check(client, report)
    except GitHubError as error:
        # 게시까지 실패하면 체크런이 아예 안 생긴다 — required check 가 비어 머지가 막힌다.
        # 판정 불가는 판정 통과가 아니므로 그 방향이 옳다.
        print(f"리뷰 상태를 읽지 못했습니다: {error}", file=sys.stderr)
        return 2

    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if args.json else render(report))
    if args.publish_check:
        # 판정은 체크런이 진다. 잡까지 빨갛게 만들면 「무엇이 빨간가」가 두 곳이 된다.
        return 0
    return 0 if report.status == READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
