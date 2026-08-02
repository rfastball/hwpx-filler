"""리뷰 라운드와 정산 상태를 GitHub 상태에서만 판독한다(`docs/REVIEW_POLICY.md`).

이 스크립트는 **계측**만 한다. 「이 지적이 차단인가」는 정책 §1 리트머스로 사람·에이전트가
판정하고 §2 정산 마커가 담는다. 여기서 세는 것은 그 정산의 **완결성**이다 — 판정과 계측을
한 곳에 섞으면 둘 다 못 믿게 된다.

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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

#: 리뷰 결과를 기다리는 창. 이 시간이 지나도록 아무 신호가 없으면 회수 창 소진으로 본다.
RECOVERY_WINDOW = timedelta(minutes=10)

#: 회귀 후보 판정의 라인 근방. 같은 파일에서 이만큼 안에 두 라운드 연속 지적이 들어오면
#: 같은 자리를 두 번 맞은 것으로 **의심**한다 — 확정은 사람이 한다.
REGRESSION_LINE_SPAN = 20

#: 빠른 경로는 **허용 목록**이다. 금지 목록으로 짜면 새로 생긴 경로가 기본값으로 통과한다.
#:
#: `tests/`·`scripts/` 는 여기 없다. 그 둘은 게이트 기계이고, 게이트가 깨지면 계약이
#: 거짓말한다 — 101 하니스는 몇 달째 깨진 채였는데 어떤 게이트도 그것을 못 봤다(#423).
#: 실제로 PR #426 은 `scripts/`·`tests/` 만 고치고도 P1 을 2건 받았다.
FAST_PATH_SUFFIXES = (".md", ".html")

#: 허용 확장자여도 기계가 읽는 것·계약 원문은 뺀다.
FAST_PATH_EXCEPTIONS = ("docs/UI_CONTRACT.md",)

#: 정산 마커. `docs/REVIEW_POLICY.md` §2 의 계약이다.
TRIAGE_PATTERN = re.compile(
    r"^\s*triage:\s*(?P<id>\d+)\s+(?P<verdict>block|defer)(?:\s+#(?P<issue>\d+))?",
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
class Finding:
    """정산해야 하는 인라인 리뷰 지적 하나."""

    id: int
    path: str
    line: int | None
    commit: str
    outdated: bool
    author: str
    severity: str
    excerpt: str

    def label(self) -> str:
        mark = "" if self.line is None else f":{self.line}"
        return f"{self.id} [{self.severity}] {self.path}{mark} — {self.excerpt}"


@dataclass
class Round:
    """한 커밋에 앵커된 지적 묶음. 리베이스 전용 푸시는 여기 들어오지 않는다."""

    commit: str
    tree: str
    findings: list[Finding] = field(default_factory=list)


@dataclass(frozen=True)
class Triage:
    """정산 마커 한 줄."""

    finding_id: int
    verdict: str
    issue: int | None


@dataclass
class Report:
    pr: int
    head: str
    fast_path: bool
    rounds: list[Round]
    unsettled: list[Finding]
    open_blocks: list[Finding]
    bad_defers: list[tuple[Finding, str]]
    regressions: list[tuple[Finding, Finding]]
    signal: str | None
    head_reviewed: bool
    status: str

    def as_dict(self) -> dict:
        return {
            "pr": self.pr,
            "head": self.head,
            "status": self.status,
            "fast_path": self.fast_path,
            "rounds": [
                {"commit": r.commit, "findings": [f.id for f in r.findings]}
                for r in self.rounds
            ],
            "unsettled": [f.id for f in self.unsettled],
            "open_blocks": [f.id for f in self.open_blocks],
            "bad_defers": [{"finding": f.id, "reason": why} for f, why in self.bad_defers],
            "regressions": [
                {"previous": before.id, "repeat": after.id, "path": after.path}
                for before, after in self.regressions
            ],
            "signal": self.signal,
            "head_reviewed": self.head_reviewed,
        }


class GitHub:
    """`gh` 호출 seam. 테스트는 같은 메서드를 가진 대역으로 갈아 끼운다."""

    def __init__(self, repo: str) -> None:
        self.repo = repo

    @classmethod
    def discover(cls) -> GitHub:
        return cls(cls._run(["gh", "repo", "view", "--json", "nameWithOwner"])["nameWithOwner"])

    @staticmethod
    def _run(command: list[str]) -> dict:
        if shutil.which(command[0]) is None:
            raise GitHubError(f"{command[0]} 을 찾지 못했습니다")
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            message = (done.stderr or done.stdout or "").strip()
            if "404" in message or "Not Found" in message:
                raise NotFound(message)
            raise GitHubError(message or f"{' '.join(command)} 실패")
        return json.loads(done.stdout)

    def get(self, path: str) -> dict:
        return self._run(["gh", "api", f"repos/{self.repo}/{path}"])

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


def _findings(client: GitHub, pr: int) -> list[Finding]:
    """인라인 리뷰 코멘트가 곧 지적이다.

    답글(`in_reply_to_id`)은 뺀다 — 뿌리 코멘트가 그 지적을 대표하고, 답글까지 정산 대상으로
    삼으면 우리가 쓴 해명이 스스로 게이트를 세운다.
    """
    findings = []
    for raw in client.paged(f"pulls/{pr}/comments"):
        if raw.get("in_reply_to_id"):
            continue
        body = raw.get("body") or ""
        severity = SEVERITY_PATTERN.search(body)
        findings.append(
            Finding(
                id=int(raw["id"]),
                path=raw.get("path") or "",
                line=raw.get("line"),
                commit=raw["original_commit_id"],
                outdated=raw.get("line") is None,
                author=(raw.get("user") or {}).get("login", ""),
                severity=severity.group(1) if severity else "??",
                excerpt=_plain(body),
            )
        )
    return findings


def _plain(body: str) -> str:
    """배지·HTML·강조를 걷어낸 첫 줄. 표에서 사람이 지적을 알아볼 만큼만 남긴다."""
    for pattern in _MARKUP:
        body = pattern.sub("", body)
    for line in body.splitlines():
        stripped = " ".join(line.split())
        if stripped:
            return stripped[:100]
    return ""


def _rounds(client: GitHub, findings: list[Finding]) -> list[Round]:
    """`original_commit_id` 로 묶고, 트리가 같은 커밋은 앞 라운드에 흡수한다.

    리베이스는 새 SHA 를 만들어 리뷰어를 재발화시키지만 코드는 안 바뀌었다. 그것을 라운드로
    세면 착지 순서가 라운드 수를 부풀린다(#426 은 그렇게 3개 늘었다).
    """
    order: list[str] = []
    grouped: dict[str, list[Finding]] = {}
    for finding in findings:
        if finding.commit not in grouped:
            grouped[finding.commit] = []
            order.append(finding.commit)
        grouped[finding.commit].append(finding)

    rounds: list[Round] = []
    for commit in order:
        tree = client.get(f"commits/{commit}")["commit"]["tree"]["sha"]
        if rounds and rounds[-1].tree == tree:
            rounds[-1].findings.extend(grouped[commit])
            continue
        rounds.append(Round(commit=commit, tree=tree, findings=list(grouped[commit])))
    return rounds


def _triage(client: GitHub, pr: int) -> dict[int, Triage]:
    settled: dict[int, Triage] = {}
    for comment in client.paged(f"issues/{pr}/comments"):
        for match in TRIAGE_PATTERN.finditer(comment.get("body") or ""):
            issue = match.group("issue")
            settled[int(match.group("id"))] = Triage(
                finding_id=int(match.group("id")),
                verdict=match.group("verdict"),
                issue=int(issue) if issue else None,
            )
    return settled


def _defer_problem(client: GitHub, triage: Triage) -> str | None:
    """분리는 이슈가 **실재하고 열려 있어야** 성립한다. 번호만 적어서는 못 지나간다."""
    if triage.issue is None:
        return "이슈 번호가 없습니다"
    try:
        issue = client.get(f"issues/{triage.issue}")
    except NotFound:
        return f"#{triage.issue} 이슈가 없습니다"
    if "pull_request" in issue:
        return f"#{triage.issue} 은 이슈가 아니라 PR 입니다"
    if issue.get("state") != "open":
        return f"#{triage.issue} 이슈가 닫혀 있습니다"
    return None


def _regressions(rounds: list[Round]) -> list[tuple[Finding, Finding]]:
    """같은 파일·근방 라인에 두 라운드 연속 지적이면 회귀 **후보**로 표시한다."""
    found = []
    for previous, current in zip(rounds, rounds[1:], strict=False):
        for after in current.findings:
            for before in previous.findings:
                if before.path != after.path or not before.line or not after.line:
                    continue
                if abs(before.line - after.line) <= REGRESSION_LINE_SPAN:
                    found.append((before, after))
                    break
    return found


def _is_prose(name: str) -> bool:
    """산문 문서인가 — 최상위 `*.md` 또는 `docs/` 아래의 문서 파일."""
    if name in FAST_PATH_EXCEPTIONS or not name.endswith(FAST_PATH_SUFFIXES):
        return False
    return "/" not in name or name.startswith("docs/")


def _fast_path(client: GitHub, pr: int) -> bool:
    changed = [entry["filename"] for entry in client.paged(f"pulls/{pr}/files")]
    return bool(changed) and all(_is_prose(name) for name in changed)


def _signal(client: GitHub, pr: int) -> tuple[str | None, datetime | None]:
    """무결과는 코멘트가 아니라 리액션으로 온다. `eyes` 는 진행 중, `+1` 이 무결과다."""
    latest: tuple[str | None, datetime | None] = (None, None)
    for reaction in client.paged(f"issues/{pr}/reactions"):
        content = reaction.get("content")
        if content not in {"+1", "eyes"}:
            continue
        when = _moment(reaction["created_at"])
        if latest[1] is None or when > latest[1]:
            latest = (content, when)
    return latest


def evaluate(client: GitHub, pr: int, now: datetime | None = None) -> Report:
    now = now or datetime.now(timezone.utc)
    head = client.get(f"pulls/{pr}")["head"]["sha"]

    if _fast_path(client, pr):
        return Report(
            pr=pr,
            head=head,
            fast_path=True,
            rounds=[],
            unsettled=[],
            open_blocks=[],
            bad_defers=[],
            regressions=[],
            signal=None,
            head_reviewed=True,
            status=READY,
        )

    findings = _findings(client, pr)
    rounds = _rounds(client, findings)
    settled = _triage(client, pr)

    unsettled = [f for f in findings if f.id not in settled]
    open_blocks = [
        f
        for f in findings
        if (t := settled.get(f.id)) and t.verdict == "block" and not f.outdated
    ]
    bad_defers = []
    for finding in findings:
        triage = settled.get(finding.id)
        if triage is None or triage.verdict != "defer":
            continue
        problem = _defer_problem(client, triage)
        if problem:
            bad_defers.append((finding, problem))

    signal, signalled_at = _signal(client, pr)
    pushed_at = _moment(client.get(f"commits/{head}")["commit"]["committer"]["date"])
    head_reviewed = (
        any(f.commit == head for f in findings)
        or (signal == "+1" and signalled_at is not None and signalled_at >= pushed_at)
        or now - pushed_at > RECOVERY_WINDOW
    )

    if open_blocks or bad_defers:
        status = BLOCKED
    elif unsettled or not head_reviewed:
        status = WAIT
    else:
        status = READY

    return Report(
        pr=pr,
        head=head,
        fast_path=False,
        rounds=rounds,
        unsettled=unsettled,
        open_blocks=open_blocks,
        bad_defers=bad_defers,
        regressions=_regressions(rounds),
        signal=signal,
        head_reviewed=head_reviewed,
        status=status,
    )


def render(report: Report) -> str:
    lines = [f"PR #{report.pr} — {report.status}"]
    if report.fast_path:
        lines.append("빠른 경로: 계약·제품 코드에 닿지 않아 리뷰 회수를 기다리지 않습니다.")
        return "\n".join(lines)

    lines.append(f"라운드 {len(report.rounds)}회 · 신호 {report.signal or '없음'}")
    for index, round_ in enumerate(report.rounds, start=1):
        lines.append(f"  {index}. {round_.commit[:7]} — 지적 {len(round_.findings)}건")
    if report.unsettled:
        lines.append("미정산:")
        lines.extend(f"  {f.label()}" for f in report.unsettled)
    if report.open_blocks:
        lines.append("미해결 차단:")
        lines.extend(f"  {f.label()}" for f in report.open_blocks)
    for finding, why in report.bad_defers:
        lines.append(f"분리 불성립: {finding.id} — {why}")
    for before, after in report.regressions:
        lines.append(f"회귀 후보: {after.path}:{after.line} (앞 라운드 {before.id})")
    if not report.head_reviewed:
        lines.append("마지막 푸시에 대한 리뷰를 아직 회수하지 못했습니다.")
    return "\n".join(lines)


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
    report = evaluate(client, client.pr_for_current_branch())
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
    parser.add_argument("--json", action="store_true", help="기계 판독용 출력")
    parser.add_argument("--hook", action="store_true", help="stdin 의 훅 payload 를 읽는다")
    args = parser.parse_args()

    try:
        if args.hook:
            return _hook(sys.stdin.read())
        client = GitHub.discover()
        report = evaluate(client, args.pr or client.pr_for_current_branch())
    except GitHubError as error:
        print(f"리뷰 상태를 읽지 못했습니다: {error}", file=sys.stderr)
        return 2

    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if args.json else render(report))
    return 0 if report.status == READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
