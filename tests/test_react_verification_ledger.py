"""old→new 검증 책임 원장의 재실측기 — R1-03 (#403).

원장(`docs/react_verification_ledger.toml`)은 「어느 검증 자산이 무엇을 지키고, React
이후에 누가 그 성질을 잇는가」를 든다. 이 파일은 그 선언을 믿지 않는다.

네 층으로 센다.

1. **전수 피복** — 게이트가 검증 트리를 스스로 열거하고(`VERIFICATION_TREE_GLOBS`), 그 안의
   모든 파일이 자산 행이거나 명시 제외에 덮이는지 묻는다. 러너 글롭 안쪽만 보면 글롭 **밖**
   으로 새는 파일이 조용히 남는다.
2. **제외의 무해성** — 제외 글롭은 러너 글롭이 잡는 파일을 **하나도** 건드리지 못한다.
   이것이 없으면 제외를 넓히고 크기를 맞추고 삼킨 행을 지우는 것으로 원장이 자기 분모를
   줄일 수 있다.
3. **술어 재실행** — 값을 든 항목(직접 브리지 · 제외 축 크기 · 문서 낡음의 오늘값 ·
   `markers` · `ci_jobs` · `runner_floor` · 미착지 델타)은 저장소에 다시 재서 대조한다.
   센서스 **총계**만은 재측정하지 않는다 — pytest 안에서 pytest 를 다시 수집하면 autouse
   홈 격리·coverage·`--strict-markers` 가 겹쳐 재귀가 되기 때문이다.
4. **분모 고정** — 축 이름 집합·자산 하한·`r_scope` 하한 술어·제외 축 목록·등급 필수 행·
   결손 필수 행은 **이 파일의 리터럴**로 산다. 원장에서 유도하면 극단에 빈 원장이 통과한다.

`check()` 가 파싱된 문서를 인자로 받는 이유는 음성 대조가 텍스트 전역 치환 없이 **한
좌표만** 바꾸게 하기 위해서다. 전역 치환은 자기가 겨눈 것 말고 다른 것까지 함께 붉혀서
「이 단언이 살아 있다」의 증거가 되지 못한다.
"""

from __future__ import annotations

import ast
import copy
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "docs" / "react_verification_ledger.toml"
SELF_REL = "tests/test_react_verification_ledger.py"

# ── 분모 리터럴 ────────────────────────────────────────────────────────────
# 원장이 자기 분모를 줄이지 못하게 게이트가 든다.

EXPECTED_SCHEMA = "react_verification_ledger/v1"
#: 이 값은 **git 이 아는 커밋**이어야 한다. 게이트가 그것을 확인한다 — 리터럴끼리 비교하면
#: 지어낸 40자도 자기 사본과는 언제나 같다.
EXPECTED_BASE_SHA = "8a69bc4c858eaf918e01089c0eec5d4dd127b4b8"
#: landed 사슬의 반대쪽 끝. 이것이 없으면 from_sha 가 아무 조상이어도 통과한다.
EXPECTED_PREVIOUS_SHA = "8fcc30ed07393ffe4608638761a778535caf3be5"
EXPECTED_OWNER_ISSUE = 403
EXPECTED_GATE = SELF_REL

#: 술어 3 이 전수로 도는 러너 글롭. 비재귀 `scripts/*.py` 는 `scripts/live101/` 을 조용히
#: 축 밖에 두므로 재귀이고, `packaging/` 의 검증 스크립트도 같은 축이다.
RUNNER_GLOBS: dict[str, tuple[str, ...]] = {
    "pytest": ("tests/test_*.py", "tests/*_test.py"),
    "node": ("tests/js/*.test.js",),
    "script": ("scripts/**/*.py", "packaging/**/*.py"),
}

#: 이 원장이 **피복을 주장하는 전체 트리**. 이 안의 파일은 자산 행이거나 명시 제외여야
#: 하고, 그 밖은 이 원장의 주장 범위가 아니다. 러너 글롭만으로는 「글롭 밖이라 안 셌다」가
#: 조용해진다.
VERIFICATION_TREE_GLOBS = (
    "tests/**/*.py",
    "tests/**/*.js",
    "tests/**/*.mjs",
    "scripts/**/*.py",
    "scripts/**/*.mjs",
    "packaging/**/*.py",
    "examples/**/*.py",
    "*.py",
    "*.mjs",
    # 어디에 생기든 셸 러너는 트리 안이다. 제외 글롭보다 좁으면 제외가 트리 밖을 덮어
    # 「덮이지 않은 것 0」이 거짓 빨강을 낸다.
    "**/*.ps1",
    "packaging/**/*.spec",
    # React 이관이 낳을 파일 형태. 지금 0 이지만 글롭이 없으면 그때 조용히 트리 밖이 된다.
    "tests/**/*.ts",
    "tests/**/*.tsx",
    "tests/**/*.jsx",
    "frontend/src/selftest/**/*.js",
    "src/hwpxfiller/webapp/selftest_api.py",
)

#: 전수 하한. 정확값이 아니라 하한이라 정상 성장은 안 막고 붕괴만 잡는다.
ASSET_FLOOR = 170
R_SCOPE_TRUE_FLOOR = 105

CENSUS_AXES = frozenset(
    {
        "pytest_collected",
        "pytest_unmarked",
        "pytest_live",
        "pytest_browser",
        "pytest_native",
        "node_pass",
    }
)
BRIDGE_SET_MEASURED = frozenset(
    {"documented", "bridge_js", "python_public", "python_public_non_dispatch"}
)
EXCLUDED_AXES = frozenset(
    {
        "node_build_and_extractor_modules",
        "pytest_support_modules",
        "powershell_runners",
        "node_hygiene_fixtures",
        "example_fixture_generators",
        "selftest_probe_surface",
        "packaging_specs",
    }
)
ORPHAN_SCRIPTS = frozenset(
    {
        "scripts/build_nara_testset.py",
        "scripts/gen_scenario_fixtures.py",
        "scripts/render_document_narmi_branding.py",
    }
)

#: 문서 낡음 행이 저장소에 되물어야 하는 프로브. **산문이 아니라 이 열거값으로 분기한다** —
#: 서술 문자열로 분기하면 문장을 고치는 것만으로 기계 검사가 조용히 꺼진다.
DOC_PROBES = frozenset(
    {"preserve_wrapped_files", "preserve_scroll_ids", "product_push_producers", "none"}
)
#: 프로브별로 **어느 문서의 낡음인지**까지 고정한다. file 이 자유로우면 낡음 주장과 기계
#: 검사가 서로 다른 문서를 볼 수 있다.
REQUIRED_DOC_PROBES: dict[str, str] = {
    "preserve_wrapped_files": "docs/WEB_RENDER_PRESERVATION.md",
    "preserve_scroll_ids": "docs/WEB_RENDER_PRESERVATION.md",
    "product_push_producers": "docs/WEB_RENDER_PRESERVATION.md",
}
#: 앵커가 한 글자여도 어떤 문서에서나 참이다. 좌표가 되려면 길이와 유일성이 있어야 한다.
DOC_ANCHOR_MIN_LENGTH = 8

#: 등급을 유예할 수 없는 행. 이 목록이 없으면 전부 `unassessed` 로 내려 nc_evidence 를
#: 비우는 길이 열린다.
GRADED_ROWS = frozenset(
    {
        "tests/test_web_selftest_gate.py",
        "tests/test_web_press_geometry.py",
        "tests/test_frontend_build_graph.py",
        "tests/test_frontend_module_units.py",
        "tests/js/n10_global_hygiene.test.js",
        "tests/test_packaging_contract.py",
        "tests/test_architecture.py",
        "tests/test_web_source_role.py",
        "tests/test_legacy_path_zero.py",
        "tests/test_suite_partition.py",
        "tests/test_quickstart_101_live.py",
        "tests/test_react_ownership_inventory.py",
        SELF_REL,
    }
)
#: 「알려진 결손」으로 고정된 행. `none` 을 `unassessed` 로 바꾸면 구현이 지던 수리가
#: 감사의 유예로 세탁된다 — U5 규율이 한 방향으로만 서 있던 자리다.
GAP_ROWS = frozenset(
    {
        "tests/test_web_dom_contract.py",
        "tests/test_web_product_api.py",
        "tests/test_web_css_manifest.py",
    }
)
#: 알려진 결손을 든 행. 지울 수 있으면 결손 기록이 흔적 없이 사라진다.
DEFECT_REQUIRED_ROWS = frozenset(
    {
        "tests/test_web_dom_contract.py",
        "tests/test_frontend_module_units.py",
        "tests/test_architecture.py",
        "tests/test_web_css_manifest.py",
    }
)

SUCCESSORS = frozenset({"keep", "react_equivalent", "retire", "out_of_scope"})
NEGATIVE_CONTROLS = frozenset({"present", "partial", "none", "unassessed"})
RUNNERS = frozenset(RUNNER_GLOBS)

#: R-GATE-MAP:v1 이 분배한 **구현** 슬라이스. reinforcement 는 여기 ∪ succession_issue 만
#: 허용한다 — 결손의 수리는 구현이 지지 감사가 지지 않는다(U5).
#: 이 두 집합의 정본은 저장소 밖(GitHub 이슈 #394 의 마커 댓글)이라 여기서는 리터럴이다.
IMPLEMENTATION_ISSUES = frozenset(
    {401, 402, 403, 405, 406, 407, 408, 410, 411, 412, 414, 415, 416, 417, 419, 420, 421, 433}
)
#: 감사 이슈. reinforcement 로는 금지, assessment_owner 로는 **필수**다 — 판정 유예의
#: 임자는 감사이고 결손의 임자는 구현이다. 두 열이 서로의 값 공간을 못 쓴다.
AUDIT_ISSUES = frozenset({400, 404, 409, 413, 418})

#: `r_scope` 하한 술어. 프런트 트리·웹 표면을 이름으로 부르는 자산은 전부 R 책임이다.
#: 이 술어가 못 보는데 사람이 R 책임으로 판정한 것만 아래 명시 목록으로 들어온다 —
#: 판정은 **넓히는 방향으로만** 자유롭다.
R_SCOPE_FLOOR_PREDICATE = re.compile(
    r"frontend[/\\]|build[/\\]web|index\.html|tests[/\\]js"
    r"|_web_source|_press_probe|_web_artifact_contract"
    r"|hwpxfiller\.webapp|hwpxfiller[/\\]webapp"
)
R_SCOPE_JUDGED_IN = frozenset(
    {
        "tests/test_contrast_wcag.py",
        "tests/test_packaging_contract.py",
        "tests/test_suite_partition.py",
        "tests/test_selftest_http_proxy.py",
        "scripts/live101/__init__.py",
        "scripts/live101/capture.py",
        "scripts/live101/scenario.py",
        "scripts/live101/surface.py",
        "scripts/render_document_narmi_branding.py",
        "scripts/selftest_http_proxy.py",
        "scripts/verify_packaged_web.py",
    }
)

AXIS_MARKERS = frozenset({"live", "native", "browser"})
AXIS_JOB = {"live": "live-webview2", "native": "windows-native", "browser": "browser-render"}
CONTRACT_JOB = "pytest-contract"

WORKFLOW = "quality.yml"
NODE_AXIS_SOURCE = "tests/test_frontend_module_units.py"
NODE_AXIS_SYMBOL = "EXPECTED_TEST_FILES"

#: 원장이 **읽는다고 선언한** 형식. 좌표 탐지(`_RAW_LINE_REF`)가 이 집합에서 유도되므로,
#: 검증 트리에 새 형식을 들이면 여기 한 줄이 규칙 전체를 함께 넓힌다.
#: `.tsx`·`.jsx` 는 오늘 0 개지만 트리가 이미 겨누므로 지금 든다 — 그 파일이 생긴 날
#: 규칙만 안 넓어져 있는 상태를 만들지 않는다.
TEXT_SUFFIXES = frozenset(
    {
        ".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".html", ".css",
        ".toml", ".json", ".md", ".yml", ".yaml", ".ps1", ".txt", ".spec",
    }
)
#: `invoked_by` 앵커가 살 수 있는 파일. 산문·스타일시트는 호출하지 못한다 — 문자열 언급을
#: 호출로 세는 것이 이 저장소가 이름 붙인 결함류다.
EXECUTABLE_SUFFIXES = frozenset({".py", ".ps1", ".yml", ".yaml", ".json", ".mjs", ".js", ".spec"})
COMMENT_PREFIXES = {
    ".py": ("#",),
    ".ps1": ("#",),
    ".yml": ("#",),
    ".yaml": ("#",),
    ".mjs": ("//", "/*", "*"),
    ".js": ("//", "/*", "*"),
    ".ts": ("//", "/*", "*"),
    ".tsx": ("//", "/*", "*"),
    ".jsx": ("//", "/*", "*"),
    ".json": (),
    ".spec": ("#",),
}


# ── 저장소 접근 ────────────────────────────────────────────────────────────
class Repo:
    """저장소를 한 번만 읽고 캐시한다. 게이트는 작업 트리를 본다(커밋이 아니라)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._text: dict[str, str | None] = {}
        self._tracked: list[str] | None = None

    def text(self, rel: str) -> str | None:
        if rel not in self._text:
            path = self.root / rel
            if not path.is_file():
                self._text[rel] = None
            elif path.suffix.lower() not in TEXT_SUFFIXES:
                self._text[rel] = None
            else:
                try:
                    self._text[rel] = path.read_text(encoding="utf-8-sig")
                except UnicodeDecodeError as exc:  # 텍스트여야 하는 파일이 아니었다
                    raise AssertionError(f"UTF-8 로 못 읽는 텍스트 파일: {rel}") from exc
        return self._text[rel]

    def exists(self, rel: str) -> bool:
        return (self.root / rel).is_file()

    def tracked(self) -> list[str]:
        if self._tracked is None:
            out = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=self.root,
                capture_output=True,
                check=True,
            ).stdout.decode("utf-8")
            self._tracked = [p for p in out.split("\0") if p]
        return self._tracked

    def glob(self, pattern: str) -> list[str]:
        """추적 파일 중 glob 에 맞는 것. `**` 는 디렉터리 경계를 넘고 `*` 는 안 넘는다."""
        rx = _glob_regex(pattern)
        return sorted(p for p in self.tracked() if rx.fullmatch(p))

    def path_exists_at(self, sha: str, rel: str) -> bool:
        return (
            subprocess.run(
                ["git", "cat-file", "-e", f"{sha}:{rel}"],
                cwd=self.root,
                capture_output=True,
            ).returncode
            == 0
        )

    def commit_exists(self, sha: str) -> bool:
        return (
            subprocess.run(
                ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                cwd=self.root,
                capture_output=True,
            ).returncode
            == 0
        )

    def is_ancestor(self, sha: str, of: str = "HEAD") -> bool:
        return (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", sha, of],
                cwd=self.root,
                capture_output=True,
            ).returncode
            == 0
        )


def _glob_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append(r"(?:[^/]+/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(r".*")
            i += 2
        elif ch == "*":
            out.append(r"[^/]*")
            i += 1
        elif ch == "?":
            out.append(r"[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("".join(out))


# ── 보고 ──────────────────────────────────────────────────────────────────
@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)

    def fail(self, where: str, message: str) -> None:
        self.problems.append(f"[{where}] {message}")

    def __bool__(self) -> bool:  # 문제가 있으면 참
        return bool(self.problems)

    def text(self) -> str:
        return "\n".join(self.problems)


# ── 앵커 (술어 1) ──────────────────────────────────────────────────────────
#: 문자열 **어디에든** 생 `file:line` 이 있으면 잡는다. 앞머리만 보면 산문 가운데 박힌
#: 좌표가 통과한다.
#:
#: 확장자 목록을 손으로 적지 않고 `TEXT_SUFFIXES` 에서 **유도**한다. 손으로 적으면 트리를
#: 넓힐 때 이 규칙만 안 넓어지고, 규칙이 존재하는데 그 자리에서만 침묵한다 — 직전 왕복에서
#: `.ts`·`.tsx`·`.jsx`·`.spec` 을 검증 트리에 들이면서 여기를 안 고쳐 실제로 그렇게 됐다.
#: 유도하면 「원장이 읽는다고 선언한 형식」과 「좌표로 알아보는 형식」이 정의상 같아진다.
_RAW_LINE_REF = re.compile(
    r"(?<![\w/\\.-])[\w./\\-]+\.(?:"
    + "|".join(re.escape(s.lstrip(".")) for s in sorted(TEXT_SUFFIXES))
    + r"):\d+"
)
#: `path#needle` · `path#needle@N` — N 은 기대 출현 수이고 **1 이상**이다. 생략하면 유일해야
#: 한다. `@0` 을 받으면 「없는 것을 없다고 확인했다」가 되어 아무 문자열이나 앵커가 된다 —
#: 그것은 앵커의 반대말이고, 이 형식을 들이기 전보다 나쁘다.
_OCCURRENCE_SUFFIX = re.compile(r"^(?P<needle>.+)@(?P<count>[1-9]\d*)$")
_ZERO_OCCURRENCE = re.compile(r"@0+$")


def _check_anchor(
    where: str, ref: str, repo: Repo, report: Report, *, executable: bool = False
) -> None:
    """`path` · `path::test_함수명` · `path#부분문자열[@N]` 셋만 유효하다."""
    if _RAW_LINE_REF.search(ref):
        report.fail(
            where,
            f"생 file:line 참조 {ref!r} — 앞줄이 하나 늘면 그날로 거짓이 된다. "
            "path::test_함수명 또는 path#부분문자열 로 적어라.",
        )
        return
    if "::" in ref:
        rel, fn = ref.split("::", 1)
        body = repo.text(rel)
        if body is None:
            report.fail(where, f"앵커가 가리키는 파일이 없다: {rel} (참조 {ref!r})")
            return
        if not re.search(rf"^\s*(?:async\s+)?def\s+{re.escape(fn)}\b", body, re.M):
            report.fail(where, f"{rel} 에 함수 {fn} 이 없다 (참조 {ref!r})")
            return
        if executable and Path(rel).suffix.lower() not in EXECUTABLE_SUFFIXES:
            report.fail(
                where,
                f"호출 앵커가 실행되지 않는 파일을 가리킨다: {rel} (참조 {ref!r}). "
                "산문·주석의 언급은 호출이 아니다.",
            )
        return
    if "#" in ref:
        rel, raw = ref.split("#", 1)
        if _ZERO_OCCURRENCE.search(raw):
            report.fail(
                where,
                f"@0 앵커 {ref!r} — 「없는 것을 없다고 확인했다」는 앵커가 아니다. "
                "그 형태를 받으면 아무 문자열이나 증거가 된다.",
            )
            return
        needle, expected = raw, 1
        m = _OCCURRENCE_SUFFIX.match(raw)
        if m:
            needle, expected = m.group("needle"), int(m.group("count"))
        elif re.fullmatch(r"@\d+", raw):
            report.fail(where, f"빈 앵커 {ref!r} — 어떤 파일에서나 참이다.")
            return
        if not needle.strip():
            report.fail(where, f"빈 앵커 {ref!r} — 어떤 파일에서나 참이다.")
            return
        body = repo.text(rel)
        if body is None:
            report.fail(where, f"앵커가 가리키는 파일이 없다: {rel} (참조 {ref!r})")
            return
        found = body.count(needle)
        if found != expected:
            report.fail(
                where,
                f"{rel} 에서 앵커 {needle!r} 의 출현이 {found} 인데 {expected} 를 기대한다 "
                f"(참조 {ref!r}). 유일하지 않으면 앵커를 늘리거나 @N 으로 수를 적어라.",
            )
            return
        if executable:
            _check_executable_anchor(where, rel, needle, body, ref, report)
        return
    if not repo.exists(ref):
        report.fail(where, f"참조가 가리키는 파일이 없다: {ref!r}")


def _check_executable_anchor(
    where: str, rel: str, needle: str, body: str, ref: str, report: Report
) -> None:
    """호출 앵커는 **실행되는 파일의 실행되는 줄**이어야 한다."""
    suffix = Path(rel).suffix.lower()
    if suffix not in EXECUTABLE_SUFFIXES:
        report.fail(
            where,
            f"호출 앵커가 실행되지 않는 파일을 가리킨다: {rel} (참조 {ref!r}). "
            "산문·주석의 언급은 호출이 아니다.",
        )
        return
    markers = COMMENT_PREFIXES.get(suffix, ())
    if not markers:
        return
    for line in body.splitlines():
        if needle in line and not line.strip().startswith(markers):
            return
    report.fail(
        where,
        f"호출 앵커 {needle!r} 가 {rel} 에서 주석 줄에만 있다 (참조 {ref!r}). "
        "언급을 호출로 세지 않는다.",
    )


def _require_count(where: str, name: str, value: Any, report: Report, *, signed: bool = False) -> bool:
    """원장의 수치 필드는 `bool` 이 아니고, 세는 값은 음수가 아니다.

    `bool` 은 `int` 의 하위형이라 `False == 0` · `True == 1` 이 참이다. 그래서 실측과
    비교하는 자리에서도 `False` 가 0 을 통과하고, **재측정하지 않는 축**(센서스 총계)에서는
    아무 경고 없이 불가능한 수가 실린다.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        report.fail(where, f"{name} 이 정수가 아니다: {value!r}. bool 은 정수처럼 비교돼 조용히 통과한다.")
        return False
    if not signed and value < 0:
        report.fail(where, f"{name} 이 음수다: {value}. 세는 값은 음수일 수 없다.")
        return False
    return True


# ── 술어 6·9: 값 항목의 술어 계약 ──────────────────────────────────────────
def _require_predicate_triple(where: str, item: dict[str, Any], report: Report) -> None:
    for key in ("predicate", "scope", "unit"):
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            report.fail(where, f"값을 든 항목이 {key} 를 안 든다 — 원장 항목으로 성립하지 않는다.")
    blind = item.get("blind_spot")
    if not isinstance(blind, str) or not blind.strip():
        report.fail(where, "술어를 든 항목이 blind_spot 을 안 든다 — 못 보는 것을 적지 않으면 다음 사람은 잰 줄 안다.")


# ── 추출기 ────────────────────────────────────────────────────────────────
def _axis_marks_on(node: ast.AST) -> set[str]:
    marks: set[str] = set()
    for dec in getattr(node, "decorator_list", []):
        expr = dec.func if isinstance(dec, ast.Call) else dec
        names: list[str] = []
        while isinstance(expr, ast.Attribute):
            names.append(expr.attr)
            expr = expr.value
        if isinstance(expr, ast.Name):
            names.append(expr.id)
        names.reverse()
        if len(names) >= 3 and names[0] == "pytest" and names[1] == "mark" and names[2] in AXIS_MARKERS:
            marks.add(names[2])
    return marks


def measure_axis_markers(repo: Repo, rel: str) -> tuple[list[str], bool]:
    """(파일에 등장하는 축 marker, 축 marker 없는 test 함수가 하나라도 있는가).

    **클래스에 붙은 marker 가 그 안의 메서드로 내려온다.** 함수 데코레이터만 보면
    `@pytest.mark.native` 를 클래스에 단 파일이 「무표 사례가 있다」로 잘못 읽히고,
    그 파일이 결정론 잡에 기여하지 않는데도 기여한다고 적히게 된다.
    """
    body = repo.text(rel)
    if body is None:
        return [], False
    tree = ast.parse(body)
    found: set[str] = set()
    has_bare = False

    def walk(node: ast.AST, inherited: set[str]) -> None:
        nonlocal has_bare, found
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, inherited | _axis_marks_on(child))
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if child.name.startswith("test_"):
                    effective = inherited | _axis_marks_on(child)
                    found |= effective
                    has_bare = has_bare or not effective
            else:
                walk(child, inherited)

    walk(tree, set())
    return sorted(found), has_bare


def measure_module_level_marks(repo: Repo, rel: str) -> bool:
    """`pytestmark = …` 대입이 모듈 최상위나 클래스 몸통에 있는가 — 위 술어의 사각."""
    body = repo.text(rel)
    if body is None:
        return False
    tree = ast.parse(body)

    def has_pytestmark(nodes: list[ast.stmt]) -> bool:
        for node in nodes:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            if any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
                return True
            if isinstance(node, ast.ClassDef) and has_pytestmark(node.body):
                return True
        return False

    return has_pytestmark(tree.body)


def measure_static_test_functions(repo: Repo, rel: str) -> tuple[int, bool]:
    """(`def test_*` 수, `parametrize` 를 쓰는가). 후자가 참이면 수집 수와 함수 수가 갈린다."""
    body = repo.text(rel)
    if body is None:
        return 0, False
    tree = ast.parse(body)
    count = 0
    parametrized = False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        count += 1
        # 파일 어딘가에 `parametrize` 라는 **글자**가 있는지 묻지 않는다 — 그 술어는 이
        # 파일 자신처럼 그 이름을 설명하는 산문만으로도 참이 된다. 데코레이터를 센다.
        for dec in node.decorator_list:
            expr = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(expr, ast.Attribute) and expr.attr == "parametrize":
                parametrized = True
    return count, parametrized


def measure_workflow_jobs(repo: Repo) -> tuple[set[str], set[str]]:
    """(`quality.yml` 의 잡 이름, `quality-gate` 의 needs 열거)."""
    body = repo.text(f".github/workflows/{WORKFLOW}")
    if body is None:
        return set(), set()
    jobs: set[str] = set()
    in_jobs = False
    for line in body.splitlines():
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if in_jobs:
            if line and not line.startswith(" ") and not line.startswith("#"):
                in_jobs = False
                continue
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if m:
                jobs.add(m.group(1))
    needs: set[str] = set()
    m = re.search(r"^  quality-gate:\s*$(.*?)^    steps:", body, re.M | re.S)
    if m:
        needs = set(re.findall(r"^\s*-\s+([A-Za-z0-9_-]+)\s*$", m.group(1), re.M))
    return jobs, needs


def measure_node_axis_files(repo: Repo) -> set[str]:
    """`EXPECTED_TEST_FILES` 를 그 트리의 AST 로 읽는다 — 상수를 복제하지 않는다(L10)."""
    body = repo.text(NODE_AXIS_SOURCE)
    if body is None:
        return set()
    tree = ast.parse(body)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == NODE_AXIS_SYMBOL for t in node.targets):
            continue
        value = node.value
        if isinstance(value, (ast.Set, ast.List, ast.Tuple)):
            return {
                el.value
                for el in value.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            }
    return set()


def measure_node_runner_floor(repo: Repo) -> int | None:
    """`node --test` 축이 pytest 에서 실제로 요구받는 **하한**. 실측값이 아니라 하한이다."""
    body = repo.text(NODE_AXIS_SOURCE)
    if body is None:
        return None
    m = re.search(r'counts\.get\(\s*"pass"\s*,\s*0\s*\)\s*>=\s*(\d+)', body)
    return int(m.group(1)) if m else None


_CANONICAL_BULLET = "직접 브리지 경로"


def measure_bridge_sets(repo: Repo) -> dict[str, Any]:
    contract = repo.text("docs/UI_CONTRACT.md") or ""
    bridge = repo.text("frontend/js/bridge.js") or ""
    app = repo.text("src/hwpxfiller/webapp/app.py") or ""

    lines = contract.splitlines()
    start = next((i for i, line in enumerate(lines) if _CANONICAL_BULLET in line), None)
    section: list[str] = []
    if start is not None:
        for line in lines[start:]:
            if not line.strip():
                break
            section.append(line)
    documented = {m for m in re.findall(r"`([a-z_][a-z0-9_]*)`", "\n".join(section))}

    bridge_js = set(re.findall(r"\bapi\.(\w+)", bridge)) - {"initial", "dispatch"}

    python_public: set[str] = set()
    if app:
        tree = ast.parse(app)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "WebFrontend":
                python_public = {
                    n.name
                    for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not n.name.startswith("_")
                }
                break
    non_dispatch = python_public - {"initial", "dispatch"}

    # 게이트 여유 — bridge.js 의 각 이름이 문서 어디에 사는가.
    section_span = range(start + 1, start + 1 + len(section)) if start is not None else range(0)
    outside_only = 0
    copy_outside = 0
    single_deletion = 0
    for name in bridge_js:
        hits = [i for i, line in enumerate(lines, 1) if f"`{name}`" in line]
        inside = [h for h in hits if h in section_span]
        outside = [h for h in hits if h not in section_span]
        if not inside and outside:
            outside_only += 1
        elif inside and outside:
            copy_outside += 1
            if len(inside) == 1:
                single_deletion += 1

    return {
        "documented": len(documented),
        "bridge_js": len(bridge_js),
        "python_public": len(python_public),
        "python_public_non_dispatch": len(non_dispatch),
        "js_only": len(bridge_js - non_dispatch),
        "python_only": len(non_dispatch - bridge_js),
        "documented_equals_intersection": documented == (bridge_js & non_dispatch),
        "satisfied_only_outside_section": outside_only,
        "has_copy_outside_section": copy_outside,
        "green_after_single_deletion": single_deletion,
        "invisible_to_the_gate": len(non_dispatch - bridge_js),
    }


def measure_doc_probe(repo: Repo, probe: str) -> list[str] | int | None:
    if probe == "preserve_wrapped_files":
        body = repo.text("tests/test_web_dom_contract.py") or ""
        m = re.search(r"^PRESERVE_WRAPPED_FILES\s*=\s*\((.*?)\)", body, re.M | re.S)
        return sorted(re.findall(r'"([^"]+)"', m.group(1))) if m else []
    if probe == "preserve_scroll_ids":
        body = repo.text("frontend/index.html") or ""
        found: list[str] = []
        for tag in re.finditer(r"<[^>]*data-preserve-scroll[^>]*>", body):
            m = re.search(r'id="([^"]+)"', tag.group(0))
            if m:
                found.append(m.group(1))
        return sorted(found)
    if probe == "product_push_producers":
        count = 0
        for rel in repo.tracked():
            if not (rel.startswith("frontend/") or rel.startswith("src/hwpxfiller/")):
                continue
            body = repo.text(rel)
            if body is None:
                continue
            count += len(re.findall(r"window\.__push\s*=", body))
        return count
    return None


# ── 본 검사 ───────────────────────────────────────────────────────────────
def _check_no_raw_coordinates(document: dict[str, Any], report: Report) -> None:
    """규칙 1 은 **원장 값 전체**에 걸린다 — 앵커와 defect.claim 두 자리만이 아니다."""

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str):
            m = _RAW_LINE_REF.search(node)
            if m:
                report.fail(
                    "raw_coordinate",
                    f"{path} 가 생 file:line 을 든다: {m.group(0)!r}. "
                    "좌표는 앵커가 지고 산문은 판단만 진다.",
                )

    walk(document, "")


def _probe_indirect_markers(repo: Repo, rels: set[str]) -> list[str]:
    """축 marker 를 별칭·`getattr` 로 붙인 자리 — 데코레이터 술어가 못 보는 형태.

    **AST 로 본다.** 원문을 정규식으로 훑으면 이 파일 자신처럼 그 모양을 문자열로 든
    테스트가 자기를 신고한다 — 부분열을 구조로 착각하는 그 결함류다.
    """
    found: list[str] = []
    for rel in sorted(rels):
        body = repo.text(rel)
        if body is None:
            continue
        try:
            tree = ast.parse(body)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            value = None
            if isinstance(node, ast.Assign):
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                value = node.value
            if (
                isinstance(value, ast.Attribute)
                and value.attr in AXIS_MARKERS
                and isinstance(value.value, ast.Attribute)
                and value.value.attr == "mark"
            ):
                found.append(rel)
                break
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and node.args
                and isinstance(node.args[0], ast.Attribute)
                and node.args[0].attr == "mark"
            ):
                found.append(rel)
                break
    return found


def check(document: dict[str, Any], repo: Repo) -> Report:
    report = Report()
    _check_no_raw_coordinates(document, report)
    _check_meta(document, repo, report)
    assets = _check_assets(document, repo, report)
    _check_census(document, repo, report)
    _check_bridge_sets(document, repo, report)
    _check_doc_staleness(document, repo, report)
    _check_orphan_scripts(document, repo, report)
    _check_excluded_axes(document, repo, report)
    _check_succession_issues(document, report)
    _check_coverage(document, assets, repo, report)
    _check_ci_job_coverage(document, assets, repo, report)
    return report


def _check_meta(document: dict[str, Any], repo: Repo, report: Report) -> None:
    if document.get("schema") != EXPECTED_SCHEMA:
        report.fail("meta", f"schema 가 {EXPECTED_SCHEMA!r} 가 아니다: {document.get('schema')!r}")
    base = document.get("base_sha")
    if base != EXPECTED_BASE_SHA:
        report.fail("meta", f"base_sha 가 게이트 리터럴과 다르다: {base!r}")
    _check_sha(("meta", "base_sha"), base, repo, report)
    if document.get("owner_issue") != EXPECTED_OWNER_ISSUE:
        report.fail("meta", f"owner_issue 가 {EXPECTED_OWNER_ISSUE} 가 아니다.")
    if document.get("gate") != EXPECTED_GATE:
        report.fail("meta", f"gate 가 {EXPECTED_GATE!r} 를 안 가리킨다.")
    for key in ("scope_statement", "not_asserted", "row_scope"):
        value = document.get(key)
        if not isinstance(value, str) or not value.strip():
            report.fail("meta", f"{key} 가 비어 있다 — 주장의 범위는 데이터다.")


def _check_sha(where: tuple[str, str], sha: Any, repo: Repo, report: Report) -> None:
    """SHA 는 **git 이 아는 커밋**이어야 한다. 리터럴끼리 비교하면 지어낸 값도 통과한다."""
    place, field_name = where
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        report.fail(place, f"{field_name} 가 40자리 커밋 해시가 아니다: {sha!r}")
        return
    if not repo.commit_exists(sha):
        report.fail(
            place,
            f"{field_name} 가 이 저장소에 없는 커밋이다: {sha}. "
            "앞 일곱 자만 맞고 나머지를 지어낸 값이 여기서 걸린다.",
        )
        return
    if not repo.is_ancestor(sha):
        report.fail(place, f"{field_name} {sha} 가 HEAD 의 조상이 아니다.")


def _check_assets(document: dict[str, Any], repo: Repo, report: Report) -> dict[str, dict]:
    assets = document.get("asset")
    if not isinstance(assets, dict):
        report.fail("asset", "asset 표가 없다.")
        return {}
    jobs, gate_needs = measure_workflow_jobs(repo)
    node_axis = measure_node_axis_files(repo)
    # 고아 면제는 **원장이 든 허용 목록**이 낸다. 게이트 리터럴은 그 목록이 조용히
    # 자라거나 줄지 못하게 하는 분모이고, 두 층은 서로를 대신하지 않는다.
    allowed_orphans = {
        row.get("path") for row in document.get("orphan_script", []) if isinstance(row, dict)
    }

    for rel, row in sorted(assets.items()):
        where = f"asset.{rel}"
        runner = row.get("runner")
        if runner not in RUNNERS:
            report.fail(where, f"runner 가 {sorted(RUNNERS)} 밖이다: {runner!r}")
            continue
        if not repo.exists(rel):
            report.fail(where, "원장에만 있는 유령 행이다 — 그 파일이 저장소에 없다.")
            continue

        # 술어 2 — 러너별 도달성.
        if runner == "node":
            if Path(rel).name not in node_axis:
                report.fail(
                    where,
                    f"{NODE_AXIS_SOURCE} 의 {NODE_AXIS_SYMBOL} 에 없다 — 러너가 그 파일을 안 센다.",
                )
        if runner == "script":
            invoked = row.get("invoked_by")
            if not isinstance(invoked, list):
                report.fail(where, "script 행이 invoked_by 를 안 든다.")
            elif not invoked and rel not in allowed_orphans:
                report.fail(
                    where,
                    "invoked_by 가 비었는데 [[orphan_script]] 허용 목록에도 없다 — "
                    "고아는 침묵이 아니라 명시 예외여야 한다.",
                )
            else:
                path = Path(rel)
                # 패키지 초기화 모듈은 자기 파일 이름이 아니라 **패키지 이름**으로 불린다.
                stem = path.parent.name if path.name == "__init__.py" else path.stem
                for ref in invoked:
                    _check_anchor(where + ".invoked_by", ref, repo, report, executable=True)
                    target = ref.split("#", 1)[-1].split("::", 1)[-1]
                    if stem not in target:
                        report.fail(
                            where + ".invoked_by",
                            f"앵커 {ref!r} 가 {stem!r} 를 이름으로 부르지 않는다 — "
                            "그 파일의 아무 줄이나 가리키면 「호출자가 있다」의 증거가 아니다.",
                        )
        else:
            declared_jobs = row.get("ci_jobs")
            if not isinstance(declared_jobs, list) or not declared_jobs:
                report.fail(where, "ci_jobs 가 비었다 — 아무 잡도 안 도는 자산은 도달 불가다.")
            else:
                for job in declared_jobs:
                    if job not in jobs:
                        report.fail(where, f"ci_jobs 의 {job!r} 가 {WORKFLOW} 에 없다.")
                    elif job not in gate_needs:
                        report.fail(where, f"ci_jobs 의 {job!r} 가 quality-gate needs 열거에 없다.")

        if runner == "node":
            declared_jobs = row.get("ci_jobs")
            if declared_jobs != [CONTRACT_JOB]:
                report.fail(
                    where,
                    f"node 행의 ci_jobs 는 {[CONTRACT_JOB]} 여야 한다 — 이 축은 무표 pytest "
                    f"사례 하나가 서브프로세스로 몬다. 선언 {declared_jobs!r} 은 자유 서술이다.",
                )

        # 술어 15 — markers 는 선언이 아니라 실측이다.
        if runner == "pytest":
            marks, bare = measure_axis_markers(repo, rel)
            declared = row.get("markers")
            if not isinstance(declared, list):
                report.fail(where, "pytest 행이 markers 를 안 든다.")
            elif sorted(declared) != marks:
                report.fail(where, f"markers 선언 {sorted(declared)} 이 실측 {marks} 과 다르다.")
            expected_jobs = ([CONTRACT_JOB] if bare else []) + [AXIS_JOB[m] for m in marks]
            declared_jobs = row.get("ci_jobs")
            if isinstance(declared_jobs, list) and sorted(declared_jobs) != sorted(expected_jobs):
                report.fail(
                    where,
                    f"ci_jobs {sorted(declared_jobs)} 가 marker 실측에서 유도한 {sorted(expected_jobs)} 과 다르다.",
                )

        # 술어 4·5 — 필드 완비와 판별력 등급의 정직성.
        r_scope = row.get("r_scope")
        if not isinstance(r_scope, bool):
            report.fail(where, "r_scope 가 불리언이 아니다.")
            continue
        if not r_scope:
            reason = row.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                report.fail(where, "r_scope=false 행이 reason 을 안 든다 — 조용한 면제 금지.")
            continue

        for key in ("protects", "stage", "blind_spot"):
            value = row.get(key)
            if not isinstance(value, str) or not value.strip():
                report.fail(where, f"r_scope=true 행이 {key} 를 안 든다.")
        successor = row.get("successor")
        if successor not in SUCCESSORS:
            report.fail(where, f"successor 가 {sorted(SUCCESSORS)} 밖이다: {successor!r}")
        elif successor in {"react_equivalent", "retire"}:
            target = row.get("successor_asset")
            if not isinstance(target, str) or not target.strip():
                report.fail(
                    where,
                    f"successor={successor} 인데 successor_asset 이 비었다 — "
                    "검증 책임은 공백 없이 1:1 로 이어져야 한다.",
                )

        nc = row.get("negative_control")
        if nc not in NEGATIVE_CONTROLS:
            report.fail(where, f"negative_control 이 {sorted(NEGATIVE_CONTROLS)} 밖이다: {nc!r}")
        elif nc in {"present", "partial"}:
            evidence = row.get("nc_evidence")
            if not isinstance(evidence, list) or not evidence:
                report.fail(where, f"negative_control={nc} 인데 nc_evidence 가 비었다.")
            else:
                for ref in evidence:
                    _check_anchor(where + ".nc_evidence", ref, repo, report)
        elif nc == "none":
            issue = row.get("reinforcement")
            if issue is None:
                report.fail(where, "negative_control=none 인데 reinforcement 가 없다 — 알려진 결손은 임자를 든다.")
            elif not _require_count(where, "reinforcement", issue, report):
                pass
            elif issue in AUDIT_ISSUES:
                report.fail(
                    where,
                    f"reinforcement 가 감사 이슈 #{issue} 다 — 결손의 수리는 구현 슬라이스가 진다.",
                )
            elif issue not in IMPLEMENTATION_ISSUES and issue not in _succession_ids(document):
                report.fail(where, f"reinforcement #{issue} 가 R-GATE-MAP 분배 항도 succession_issue 도 아니다.")
        elif nc == "unassessed":
            owner = row.get("assessment_owner")
            if not isinstance(owner, str) or not owner.strip():
                report.fail(where, "negative_control=unassessed 인데 assessment_owner 가 없다 — 유예는 임자를 든다.")
            else:
                m = re.search(r"#(\d+)", owner)
                if not m or int(m.group(1)) not in AUDIT_ISSUES:
                    report.fail(
                        where,
                        f"assessment_owner {owner!r} 가 감사 이슈를 안 가리킨다 — 판정 유예의 임자는 감사다.",
                    )
        if rel in GAP_ROWS and nc != "none":
            report.fail(
                where,
                f"이 행의 등급은 none 으로 고정돼 있다 — {nc!r} 로 바꾸면 구현이 지던 수리가 "
                "감사의 유예로 세탁된다. 내리려면 게이트의 목록을 먼저 고쳐야 한다.",
            )
        if rel in GRADED_ROWS and nc == "unassessed":
            report.fail(
                where,
                "이 행은 등급을 유예할 수 없다 — 게이트가 든 필수 등급 목록에 있다. "
                "판별력을 내리려면 목록을 먼저 고쳐야 하고 그 변경이 리뷰 대상이다.",
            )

        _check_defects(where, rel, row, repo, report)
    return assets


def _check_defects(
    where: str, rel: str, row: dict[str, Any], repo: Repo, report: Report
) -> None:
    defects = row.get("defect")
    if rel in DEFECT_REQUIRED_ROWS and not defects:
        report.fail(
            where,
            "알려진 결손을 든 행인데 defect 가 비었다 — 결손 기록은 흔적 없이 사라질 수 없다.",
        )
        return
    if defects is None:
        return
    if not isinstance(defects, list):
        report.fail(where, "defect 가 목록이 아니다.")
        return
    for index, item in enumerate(defects):
        place = f"{where}.defect[{index}]"
        if not isinstance(item, dict):
            report.fail(place, "defect 항목이 claim·evidence 를 든 표가 아니다.")
            continue
        claim = item.get("claim")
        if not isinstance(claim, str) or not claim.strip():
            report.fail(place, "claim 이 비었다.")
        elif _RAW_LINE_REF.search(claim):
            report.fail(
                place,
                f"claim 이 생 file:line 을 든다: {_RAW_LINE_REF.search(claim).group(0)!r}. "
                "좌표는 evidence 앵커가 진다.",
            )
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            report.fail(place, "evidence 가 비었다 — 결손 주장은 좌표를 든다.")
        else:
            for ref in evidence:
                _check_anchor(place + ".evidence", ref, repo, report)


def _succession_ids(document: dict[str, Any]) -> set[int]:
    return {
        item.get("id")
        for item in document.get("succession_issue", [])
        if isinstance(item.get("id"), int)
    }


def _check_census(document: dict[str, Any], repo: Repo, report: Report) -> None:
    census = document.get("census")
    if not isinstance(census, dict):
        report.fail("census", "census 표가 없다.")
        return
    if set(census) != CENSUS_AXES:
        report.fail(
            "census",
            f"축 집합이 게이트 리터럴과 다르다. 없는 것 {sorted(CENSUS_AXES - set(census))} · "
            f"남는 것 {sorted(set(census) - CENSUS_AXES)}",
        )
    for name, axis in sorted(census.items()):
        where = f"census.{name}"
        _require_predicate_triple(where, axis, report)
        _require_count(where, "value", axis.get("value"), report)
        adjustments = axis.get("adjustment")
        if not isinstance(adjustments, list) or not adjustments:
            report.fail(where, "adjustment 가 없다 — 기준 SHA 에서 오늘까지의 사슬이 있어야 한다.")
            continue
        landed = [a for a in adjustments if a.get("kind") == "landed"]
        if not landed:
            report.fail(where, "landed adjustment 가 하나도 없다.")
        for adj in adjustments:
            kind = adj.get("kind")
            if kind == "landed":
                if adj.get("to_sha") != EXPECTED_BASE_SHA:
                    report.fail(
                        where,
                        f"landed adjustment 의 to_sha 가 base_sha 와 다르다: {adj.get('to_sha')!r}. "
                        "사슬은 기준에서 닫혀야 한다.",
                    )
                _check_sha((where, "from_sha"), adj.get("from_sha"), repo, report)
                if adj.get("from_sha") != EXPECTED_PREVIOUS_SHA:
                    report.fail(
                        where,
                        f"landed adjustment 의 from_sha 가 게이트가 든 직전 기준과 다르다: "
                        f"{adj.get('from_sha')!r}. 아무 조상이나 받으면 사슬의 한쪽 끝이 자유롭다.",
                    )
                if "owner_pr" in adj:
                    report.fail(where, "landed adjustment 가 owner_pr 을 든다 — 그 열은 미착지 몫이다.")
            elif kind == "expected_landing":
                if not isinstance(adj.get("owner_pr"), str) or not adj.get("owner_pr"):
                    report.fail(where, "expected_landing adjustment 가 owner_pr 을 안 든다.")
                if "to_sha" in adj:
                    report.fail(
                        where,
                        "expected_landing adjustment 가 to_sha 를 든다 — 착지 SHA 는 작성 시점에 알 수 없다.",
                    )
                _check_expected_landing_delta(where, adj, repo, report)
            else:
                report.fail(where, f"adjustment.kind 가 landed/expected_landing 밖이다: {kind!r}")
            _require_count(where, "delta", adj.get("delta"), report, signed=True)
            if not isinstance(adj.get("reason"), str) or not adj.get("reason", "").strip():
                report.fail(where, "adjustment 가 reason 을 안 든다 — 정당화 없는 증감은 정당화가 아니다.")

    _check_census_chain_is_complete(census, repo, report)

    node_axis = census.get("node_pass", {})
    if "runner_floor" in node_axis:
        measured_floor = measure_node_runner_floor(repo)
        if measured_floor is None:
            report.fail(
                "census.node_pass",
                f"{NODE_AXIS_SOURCE} 에서 하한 술어를 못 찾았다 — 그 단언이 사라졌거나 모양이 바뀌었다.",
            )
        elif not _require_count("census.node_pass", "runner_floor", node_axis["runner_floor"], report):
            pass
        elif node_axis["runner_floor"] != measured_floor:
            report.fail(
                "census.node_pass",
                f"runner_floor 기록값 {node_axis['runner_floor']!r} 이 실측 {measured_floor} 과 다르다.",
            )
        if not isinstance(node_axis.get("runner_floor_predicate"), str):
            report.fail("census.node_pass", "runner_floor 가 자기 술어를 안 든다.")
    else:
        report.fail("census.node_pass", "runner_floor 가 없다 — 이 축이 실제로 요구받는 하한은 값과 다르다.")


#: 미착지 델타를 요구받는 축. node 축은 러너가 달라 이 술어의 대상이 아니다.
_PYTEST_CENSUS_AXES = ("pytest_collected", "pytest_unmarked")


def _check_census_chain_is_complete(
    census: dict[str, Any], repo: Repo, report: Report
) -> None:
    """`base_sha` 이후 새로 생긴 테스트 파일은 **전부** 미착지 행으로 계상돼야 한다.

    총계 자체는 재측정하지 않는다 — pytest 안에서 pytest 를 다시 수집하는 것이라 재귀다.
    그러나 「사슬에 빠진 파일이 있는가」는 재귀 없이 물을 수 있고, 그것이 없으면 미착지 행
    하나를 지우는 것으로 그 파일의 사례가 공표된 총계에서 **조용히** 빠진다.
    """
    new_files = sorted(
        rel
        for pattern in RUNNER_GLOBS["pytest"]
        for rel in repo.glob(pattern)
        if not repo.path_exists_at(EXPECTED_BASE_SHA, rel)
    )
    if not new_files:
        return
    for axis in _PYTEST_CENSUS_AXES:
        block = census.get(axis)
        if not isinstance(block, dict):
            continue
        accounted = {
            adj.get("file")
            for adj in block.get("adjustment", [])
            if isinstance(adj, dict) and adj.get("kind") == "expected_landing"
        }
        missing = [rel for rel in new_files if rel not in accounted]
        if missing:
            report.fail(
                f"census.{axis}",
                f"base_sha 이후 새로 생긴 테스트 파일 {len(missing)} 개가 미착지 행으로 "
                f"계상되지 않았다: {missing}. 그 사례들이 공표된 총계에서 조용히 빠진다.",
            )


def _check_expected_landing_delta(
    where: str, adj: dict[str, Any], repo: Repo, report: Report
) -> None:
    """미착지 델타는 **재측정한다.** 파일 하나의 사례 수는 재귀 없이 셀 수 있다."""
    rel = adj.get("file")
    if not isinstance(rel, str) or not rel:
        report.fail(
            where,
            "expected_landing adjustment 가 file 을 안 든다 — 어느 파일의 델타인지 없으면 재측정할 수 없다.",
        )
        return
    if not repo.exists(rel):
        report.fail(where, f"expected_landing 이 가리키는 파일이 없다: {rel}")
        return
    if repo.path_exists_at(EXPECTED_BASE_SHA, rel):
        report.fail(
            where,
            f"expected_landing 이 base_sha 에 **이미 있던** 파일을 가리킨다: {rel}. "
            "미착지 델타는 이 PR 이 새로 들이는 파일의 몫이다.",
        )
        return
    count, parametrized = measure_static_test_functions(repo, rel)
    if parametrized:
        report.fail(
            where,
            f"{rel} 이 parametrize 를 쓴다 — 함수 수와 수집 수가 갈리므로 이 재측정이 성립하지 않는다.",
        )
        return
    if adj.get("delta") != count:
        report.fail(
            where,
            f"expected_landing delta {adj.get('delta')!r} 이 {rel} 의 실측 test 함수 수 {count} 와 다르다.",
        )


def _check_bridge_sets(document: dict[str, Any], repo: Repo, report: Report) -> None:
    block = document.get("bridge_set")
    if not isinstance(block, dict):
        report.fail("bridge_set", "bridge_set 표가 없다.")
        return
    measured = measure_bridge_sets(repo)
    if set(block) != BRIDGE_SET_MEASURED | {"derived", "contract_gate_slack"}:
        report.fail("bridge_set", f"집합 목록이 게이트 리터럴과 다르다: {sorted(block)}")
    for name in sorted(BRIDGE_SET_MEASURED & set(block)):
        where = f"bridge_set.{name}"
        item = block[name]
        _require_predicate_triple(where, item, report)
        if not _require_count(where, "value", item.get("value"), report):
            pass
        elif item.get("value") != measured[name]:
            report.fail(where, f"기록값 {item.get('value')!r} 이 실측 {measured[name]} 과 다르다.")
        anchor = item.get("scope_anchor")
        if anchor is not None:
            _check_anchor(where + ".scope_anchor", anchor, repo, report)
    derived = block.get("derived", {})
    for key in ("js_only", "python_only"):
        if key in derived:
            _require_count("bridge_set.derived", key, derived[key], report)
    if not isinstance(derived.get("documented_equals_intersection"), bool):
        report.fail("bridge_set.derived", "documented_equals_intersection 이 불리언이 아니다.")
    for key in ("js_only", "python_only", "documented_equals_intersection"):
        if key not in derived:
            report.fail("bridge_set.derived", f"{key} 가 없다.")
        elif derived[key] != measured[key]:
            report.fail(
                "bridge_set.derived",
                f"{key} 기록값 {derived[key]!r} 이 실측 {measured[key]!r} 과 다르다.",
            )
    slack = block.get("contract_gate_slack", {})
    _require_predicate_triple("bridge_set.contract_gate_slack", slack, report)
    for key in (
        "satisfied_only_outside_section",
        "has_copy_outside_section",
        "green_after_single_deletion",
        "invisible_to_the_gate",
    ):
        if key not in slack:
            report.fail("bridge_set.contract_gate_slack", f"{key} 가 없다.")
        elif not _require_count("bridge_set.contract_gate_slack", key, slack[key], report):
            pass
        elif slack[key] != measured[key]:
            report.fail(
                "bridge_set.contract_gate_slack",
                f"{key} 기록값 {slack[key]!r} 이 실측 {measured[key]!r} 과 다르다.",
            )


def _check_doc_staleness(document: dict[str, Any], repo: Repo, report: Report) -> None:
    rows = document.get("doc_staleness")
    if not isinstance(rows, list):
        report.fail("doc_staleness", "doc_staleness 목록이 없다.")
        return
    seen_probes: set[str] = set()
    for index, row in enumerate(rows):
        where = f"doc_staleness[{index}]"
        rel = row.get("file")
        anchor = row.get("anchor")
        body = repo.text(rel) if isinstance(rel, str) else None
        if body is None:
            report.fail(where, f"file 이 가리키는 파일이 없다: {rel!r}")
        elif not isinstance(anchor, str) or anchor not in body:
            report.fail(
                where,
                f"앵커 {anchor!r} 가 {rel} 에서 사라졌다. 낡음 기록이 스스로 낡았다 — "
                "이 행의 은퇴는 그 텍스트를 고친 PR 의 몫이다.",
            )
        if isinstance(anchor, str) and body is not None:
            if len(anchor) < DOC_ANCHOR_MIN_LENGTH:
                report.fail(
                    where,
                    f"앵커 {anchor!r} 가 너무 짧다 — 한두 글자는 어떤 문서에서나 참이라 좌표가 아니다.",
                )
            elif body.count(anchor) != 1:
                report.fail(
                    where,
                    f"앵커 {anchor!r} 가 {rel} 에서 {body.count(anchor)} 번 나온다 — 유일해야 좌표다.",
                )
        for key in ("stale_claim", "predicate", "scope", "unit", "successor_doc"):
            value = row.get(key)
            if not isinstance(value, str) or not value.strip():
                report.fail(where, f"{key} 가 비었다.")

        probe = row.get("probe")
        if probe not in DOC_PROBES:
            report.fail(where, f"probe 가 {sorted(DOC_PROBES)} 밖이다: {probe!r}")
            continue
        if probe in seen_probes:
            report.fail(where, f"probe {probe!r} 가 두 행에 있다 — 같은 사실을 두 자리가 든다.")
        seen_probes.add(probe)
        expected_file = REQUIRED_DOC_PROBES.get(probe)
        if expected_file is not None and rel != expected_file:
            report.fail(
                where,
                f"probe {probe!r} 는 {expected_file} 의 낡음을 재는데 이 행의 file 은 {rel!r} 이다 — "
                "낡음 주장과 기계 검사가 다른 문서를 보면 둘 다 의미가 없다.",
            )

        if probe == "none":
            owner = row.get("assessment_owner")
            if not isinstance(owner, str) or not owner.strip():
                report.fail(where, "probe=none 인 행이 assessment_owner 를 안 든다 — 안 잰 것은 임자를 든다.")
            elif not (m := re.search(r"#(\d+)", owner)) or int(m.group(1)) not in AUDIT_ISSUES:
                report.fail(where, f"assessment_owner {owner!r} 가 감사 이슈를 안 가리킨다.")
            continue

        measured = measure_doc_probe(repo, probe)
        if measured == [] :
            report.fail(
                where,
                f"probe {probe!r} 의 추출기가 아무것도 못 찾았다 — 저장소가 정말 비었거나 "
                "술어가 겨누던 모양이 사라졌다. 빈손은 조용한 0 이 아니다.",
            )
        recorded = row.get("today_measured")
        if isinstance(measured, list):
            if not isinstance(recorded, list) or sorted(recorded) != measured:
                report.fail(
                    where,
                    f"today_measured 기록값 {recorded!r} 이 실측 {measured!r} 과 다르다. "
                    "부분집합도 초집합도 아닌 **정확 일치**여야 줄어드는 방향을 잡는다.",
                )
        elif isinstance(measured, int):
            if isinstance(recorded, bool) or not isinstance(recorded, int):
                report.fail(
                    where,
                    f"today_measured 가 정수가 아니다: {recorded!r}. False 와 0.0 은 0 과 "
                    "같다고 비교돼 통과한다.",
                )
            elif recorded != measured:
                report.fail(
                    where,
                    f"today_measured 기록값 {recorded!r} 이 실측 {measured!r} 과 다르다.",
                )

    missing = set(REQUIRED_DOC_PROBES) - seen_probes
    if missing:
        report.fail(
            "doc_staleness",
            f"저장소에 되묻는 프로브가 빠졌다: {sorted(missing)}. "
            "행을 자리표시로 바꿔 기계 검사를 끄는 길을 막는다.",
        )
    report.notes["doc_probes"] = sorted(seen_probes)


def _check_orphan_scripts(document: dict[str, Any], repo: Repo, report: Report) -> None:
    rows = document.get("orphan_script")
    if not isinstance(rows, list):
        report.fail("orphan_script", "orphan_script 목록이 없다.")
        return
    listed = {row.get("path") for row in rows}
    if listed != set(ORPHAN_SCRIPTS):
        report.fail(
            "orphan_script",
            f"허용 목록이 게이트 리터럴과 다르다. 없는 것 {sorted(ORPHAN_SCRIPTS - listed)} · "
            f"남는 것 {sorted(listed - ORPHAN_SCRIPTS)}",
        )
    unknown = 0
    for index, row in enumerate(rows):
        where = f"orphan_script[{index}]"
        rel = row.get("path")
        if not isinstance(rel, str) or not repo.exists(rel):
            report.fail(where, f"path 가 가리키는 파일이 없다: {rel!r}")
        if row.get("invoked_by") != []:
            report.fail(where, "고아 행의 invoked_by 는 빈 목록이어야 한다.")
        evidence = row.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            report.fail(where, "evidence 가 없다.")
        else:
            _check_anchor(where, evidence, repo, report)
        if not isinstance(row.get("reason"), str) or not row.get("reason", "").strip():
            report.fail(where, "reason 이 없다.")
        if row.get("disposition_owner") == "unknown":
            unknown += 1
    report.notes["orphan_scripts"] = sorted(x for x in listed if isinstance(x, str))
    report.notes["orphan_disposition_unknown"] = unknown


def _excluded_files(document: dict[str, Any], repo: Repo) -> set[str]:
    return {
        path
        for row in document.get("excluded_axis", [])
        for glob in (row.get("globs") or [])
        if isinstance(glob, str)
        for path in repo.glob(glob)
    }


def _runner_files(repo: Repo) -> dict[str, set[str]]:
    return {
        runner: {p for pattern in globs for p in repo.glob(pattern)}
        for runner, globs in RUNNER_GLOBS.items()
    }


def _check_excluded_axes(document: dict[str, Any], repo: Repo, report: Report) -> None:
    rows = document.get("excluded_axis")
    if not isinstance(rows, list):
        report.fail("excluded_axis", "excluded_axis 목록이 없다.")
        return
    names = {row.get("axis") for row in rows}
    if names != set(EXCLUDED_AXES):
        report.fail(
            "excluded_axis",
            f"제외 축 목록이 게이트 리터럴과 다르다. 없는 것 {sorted(EXCLUDED_AXES - names)} · "
            f"남는 것 {sorted(names - EXCLUDED_AXES)}",
        )
    runner_files = set().union(*_runner_files(repo).values())
    for index, row in enumerate(rows):
        where = f"excluded_axis[{index}]"
        globs = row.get("globs")
        if not isinstance(globs, list) or not globs:
            report.fail(where, "globs 가 없다 — 무엇을 뺐는지 모르는 제외는 제외가 아니다.")
            continue
        for key in ("reason", "owner"):
            if not isinstance(row.get(key), str) or not row.get(key, "").strip():
                report.fail(where, f"{key} 가 없다.")
        measured = sorted({p for g in globs for p in repo.glob(g)})
        if not _require_count(where, "size", row.get("size"), report):
            continue
        if row.get("size") != len(measured):
            report.fail(
                where,
                f"size 기록값 {row.get('size')!r} 이 실측 {len(measured)} 과 다르다: {measured}",
            )
        if not measured:
            report.fail(where, "아무것도 안 덮는 제외 축이다 — 크기 0 의 제외는 장식이다.")
        swallowed = sorted(set(measured) & runner_files)
        if swallowed:
            report.fail(
                where,
                f"제외 글롭이 러너 글롭이 잡는 자산 {len(swallowed)} 개를 삼킨다: {swallowed[:10]}. "
                "제외를 넓혀 자산 행을 지우는 길을 막는다.",
            )
    seen: dict[str, str] = {}
    for row in rows:
        axis = row.get("axis")
        for glob in row.get("globs") or []:
            for path in repo.glob(glob):
                if path in seen and seen[path] != axis:
                    report.fail(
                        "excluded_axis",
                        f"{path} 를 두 축이 함께 든다: {seen[path]} · {axis}. "
                        "축 사이에 파일을 옮기면 사유·소유가 장식이 된다.",
                    )
                seen.setdefault(path, axis)
    report.notes["excluded_axis_sizes"] = {
        row.get("axis"): row.get("size") for row in rows if isinstance(row, dict)
    }


def _check_succession_issues(document: dict[str, Any], report: Report) -> None:
    rows = document.get("succession_issue")
    if not isinstance(rows, list) or not rows:
        report.fail("succession_issue", "승계 이슈 목록이 없다.")
        return
    for index, row in enumerate(rows):
        where = f"succession_issue[{index}]"
        if not _require_count(where, "id", row.get("id"), report):
            continue
        if row["id"] in AUDIT_ISSUES:
            report.fail(where, f"승계 이슈가 감사 이슈 #{row['id']} 다.")
        for key in ("reason", "origin"):
            if not isinstance(row.get(key), str) or not row.get(key, "").strip():
                report.fail(where, f"{key} 가 없다.")


def _check_ci_job_coverage(
    document: dict[str, Any], assets: dict[str, dict], repo: Repo, report: Report
) -> None:
    """차단 잡은 자산이 지거나 명시로 비워져야 한다. 선언→실재 한 방향만 보면 잡이 조용히 샌다."""
    _, gate_needs = measure_workflow_jobs(repo)
    claimed = {job for row in assets.values() for job in (row.get("ci_jobs") or [])}
    declared_empty = {
        row.get("job"): row for row in document.get("uncovered_ci_job", []) if isinstance(row, dict)
    }
    for job in sorted(gate_needs):
        if job in claimed:
            continue
        row = declared_empty.get(job)
        if row is None:
            report.fail(
                "ci_job",
                f"quality-gate 가 요구하는 잡 {job!r} 을 어느 자산도 지지 않고 "
                "[[uncovered_ci_job]] 선언도 없다 — 차단 잡이 조용히 원장 밖에 있다.",
            )
            continue
        for key in ("reason", "owner"):
            if not isinstance(row.get(key), str) or not row.get(key, "").strip():
                report.fail("ci_job", f"uncovered_ci_job {job!r} 이 {key} 를 안 든다.")
    stale = sorted(set(declared_empty) - gate_needs)
    if stale:
        report.fail("ci_job", f"uncovered_ci_job 이 quality-gate needs 밖의 잡을 든다: {stale}")
    report.notes["ci_jobs_claimed"] = sorted(claimed)
    report.notes["ci_jobs_declared_empty"] = sorted(declared_empty)


def _check_coverage(
    document: dict[str, Any], assets: dict[str, dict], repo: Repo, report: Report
) -> None:
    """술어 3 — 러너 전수와 **검증 트리 전수**를 함께 본다."""
    measured = _runner_files(repo)
    all_measured = set().union(*measured.values())
    excluded_files = _excluded_files(document, repo)

    missing = sorted(all_measured - set(assets))
    if missing:
        report.fail(
            "coverage",
            f"원장이 안 든 자산 {len(missing)}: {missing[:20]}" + (" …" if len(missing) > 20 else ""),
        )
    ghosts = sorted(set(assets) - all_measured)
    if ghosts:
        report.fail("coverage", f"어느 러너 글롭에도 없는 유령 행 {len(ghosts)}: {ghosts[:20]}")

    for runner, found in measured.items():
        for rel in sorted(found & set(assets)):
            declared = assets[rel].get("runner")
            if declared != runner:
                report.fail(
                    f"asset.{rel}",
                    f"runner 선언 {declared!r} 이 글롭 실측 {runner!r} 과 다르다.",
                )

    # 검증 트리 전수 — 러너 글롭 **밖으로** 새는 파일을 잡는다.
    universe = {p for g in VERIFICATION_TREE_GLOBS for p in repo.glob(g)}
    uncovered = sorted(universe - set(assets) - excluded_files)
    if uncovered:
        report.fail(
            "coverage",
            f"검증 트리 안인데 자산 행도 명시 제외도 아닌 파일 {len(uncovered)}: {uncovered[:20]}. "
            "「안 센 것」은 침묵이 아니라 데이터다.",
        )

    outside = sorted(excluded_files - universe)
    if outside:
        report.fail(
            "coverage",
            f"제외가 검증 트리 밖을 덮는다 {len(outside)}: {outside[:10]}. "
            "트리보다 넓은 제외는 「덮이지 않은 것 0」을 거짓 빨강으로 만든다.",
        )

    if len(assets) < ASSET_FLOOR:
        report.fail("coverage", f"자산 행 {len(assets)} 이 하한 {ASSET_FLOOR} 아래다.")

    # r_scope 하한 술어 — 넓히는 방향으로만 자유롭다.
    floor_hits = {
        rel for rel in all_measured if (body := repo.text(rel)) and R_SCOPE_FLOOR_PREDICATE.search(body)
    }
    true_rows = {rel for rel, row in assets.items() if row.get("r_scope") is True}
    escaped = sorted(floor_hits - true_rows)
    if escaped:
        report.fail(
            "r_scope",
            f"프런트 트리·웹 표면을 이름으로 부르는데 r_scope=false 인 자산 {len(escaped)}: {escaped}",
        )
    if len(true_rows) < R_SCOPE_TRUE_FLOOR:
        report.fail("r_scope", f"r_scope=true 행 {len(true_rows)} 이 하한 {R_SCOPE_TRUE_FLOOR} 아래다.")
    stale_judged = sorted(R_SCOPE_JUDGED_IN - true_rows)
    if stale_judged:
        report.fail(
            "r_scope",
            f"게이트가 명시 판정으로 든 자산이 원장에서 r_scope=true 가 아니다: {stale_judged}",
        )

    # 등급의 방벽은 하한이 아니라 **GRADED_ROWS 목록**이다. 하한은 그 목록의 크기를 복제할
    # 뿐이라 정직한 성장·하향에서 먼저 깨지고, 부정직한 하향은 목록이 이미 막는다.
    graded = {
        rel
        for rel, row in assets.items()
        if row.get("r_scope") is True and row.get("negative_control") in {"present", "partial"}
    }

    report.notes["asset_rows"] = len(assets)
    report.notes["r_scope_true"] = len(true_rows)
    report.notes["r_scope_false"] = len(assets) - len(true_rows)
    report.notes["r_scope_floor_hits"] = len(floor_hits)
    report.notes["graded"] = len(graded)
    report.notes["unassessed"] = sum(
        1 for row in assets.values() if row.get("negative_control") == "unassessed"
    )
    report.notes["verification_tree"] = len(universe)
    report.notes["excluded_files"] = len(excluded_files)
    report.notes["module_level_marks"] = sorted(
        rel for rel in measured["pytest"] if measure_module_level_marks(repo, rel)
    )
    report.notes["indirect_marks"] = _probe_indirect_markers(repo, measured["pytest"])


# ── 하니스 ────────────────────────────────────────────────────────────────
def load_document(path: Path = LEDGER_PATH) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


class OverlayRepo(Repo):
    """저장소 위에 파일 내용을 덮어써 보는 프로브. 디스크는 건드리지 않는다."""

    def __init__(self, base: Repo, overlay: dict[str, str]) -> None:
        super().__init__(base.root)
        self._overlay = overlay

    def text(self, rel: str) -> str | None:
        if rel in self._overlay:
            return self._overlay[rel]
        return super().text(rel)


@pytest.fixture(scope="module")
def repo() -> Repo:
    return Repo(REPO_ROOT)


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    return load_document()


def _mutate(document: dict[str, Any], mutate) -> dict[str, Any]:
    clone = copy.deepcopy(document)
    mutate(clone)
    return clone


def _expect_red(document: dict[str, Any], repo: Repo, *needles: str) -> None:
    report = check(document, repo)
    assert report.problems, "변형했는데 게이트가 조용하다 — 이 단언은 판별력이 없다."
    joined = report.text()
    for needle in needles:
        assert needle in joined, f"실패 메시지가 {needle!r} 를 이름으로 말하지 않는다:\n{joined}"


# ── 양성 대조 ─────────────────────────────────────────────────────────────
def test_the_shipped_ledger_passes_so_the_negative_controls_mean_something(
    document: dict[str, Any], repo: Repo
) -> None:
    """변형 없는 원장이 초록임을 먼저 못박는다. 이것 없이는 아래 red 가 자기 변형의 것이라고 말할 수 없다."""
    report = check(document, repo)
    assert not report.problems, report.text()


def test_the_gate_reports_the_shape_it_measured_out_loud(
    document: dict[str, Any], repo: Repo
) -> None:
    """유예·제외·고아는 조용한 0 이 아니라 시끄러운 숫자다."""
    report = check(document, repo)
    notes = report.notes
    assert notes["asset_rows"] >= ASSET_FLOOR
    assert notes["r_scope_true"] >= R_SCOPE_TRUE_FLOOR
    assert notes["r_scope_true"] + notes["r_scope_false"] == notes["asset_rows"]
    assert notes["graded"] == len(GRADED_ROWS), (
        "등급 확정 행이 게이트가 든 목록과 다르다 — 목록이 방벽이고 수는 그 그림자다."
    )
    assert notes["orphan_scripts"] == sorted(ORPHAN_SCRIPTS)
    assert notes["orphan_disposition_unknown"] == len(ORPHAN_SCRIPTS)
    assert set(notes["excluded_axis_sizes"]) == set(EXCLUDED_AXES)
    assert sorted(notes["doc_probes"]) == sorted(DOC_PROBES)
    assert notes["verification_tree"] == notes["asset_rows"] + notes["excluded_files"], (
        "검증 트리가 자산과 제외의 합과 다르다 — 어느 쪽에도 안 든 파일이 있다는 뜻이다."
    )
    assert notes["unassessed"] > 0, "유예가 0 이면 이 원장은 읽지 않은 것을 등급으로 승격했다는 뜻이다."
    assert notes["indirect_marks"] == [], (
        "축 marker 를 별칭이나 getattr 로 붙인 파일이 생겼다. markers 술어는 "
        f"`pytest.mark.<축>` 모양만 보므로 그 파일의 축을 지금 잘못 세고 있다: {notes['indirect_marks']}"
    )
    assert notes["module_level_marks"] == [], (
        "모듈·클래스 몸통에 pytestmark 가 생겼다. markers 술어는 데코레이터만 보므로 "
        f"그 파일의 축은 지금 잘못 세고 있다: {notes['module_level_marks']}"
    )


def test_the_base_sha_is_a_commit_this_repository_actually_has(repo: Repo) -> None:
    """리터럴끼리 비교하면 지어낸 40자도 자기 사본과는 언제나 같다."""
    assert repo.commit_exists(EXPECTED_BASE_SHA), (
        f"게이트가 든 base_sha {EXPECTED_BASE_SHA} 가 이 저장소에 없는 커밋이다."
    )
    assert repo.is_ancestor(EXPECTED_BASE_SHA)


# ── 등급 B — red 의 원인이 조작이 아니라 저장소 사실인 음성 대조 ───────────
def test_b1_dropping_an_orphan_row_reds_because_that_script_really_has_no_caller(
    document: dict[str, Any], repo: Repo
) -> None:
    """B-①: 허용 목록에서 한 행을 빼면 붉는다. 원인은 그 스크립트에 호출자가 실제로 없다는 저장소 사실이다."""
    target = "scripts/build_nara_testset.py"

    def mutate(doc: dict[str, Any]) -> None:
        doc["orphan_script"] = [r for r in doc["orphan_script"] if r.get("path") != target]

    _expect_red(_mutate(document, mutate), repo, target, "허용 목록에도 없다")


def test_b2_faking_the_scroll_container_value_reds_because_those_ids_really_are_gone(
    document: dict[str, Any], repo: Repo
) -> None:
    """B-②: 오늘값을 「여섯 컨테이너 전부 실재」로 조작하면 붉는다. index.html 에 그 id 들이 실제로 없기 때문이다."""

    def mutate(doc: dict[str, Any]) -> None:
        for row in doc["doc_staleness"]:
            if row.get("probe") == "preserve_scroll_ids":
                row["today_measured"] = [
                    "renderView",
                    "tokPanel",
                    "editor-body",
                    "recList",
                    "mxJobList",
                    "mxRecList",
                ]

    _expect_red(_mutate(document, mutate), repo, "today_measured", "libraryList")


def test_b3_promoting_a_gradeless_asset_reds_because_that_file_has_no_such_test(
    document: dict[str, Any], repo: Repo
) -> None:
    """B-③: 판별력을 present 로 올리고 함수명을 적으면 붉는다. 그 파일에 자기 대조 테스트가 실제로 없기 때문이다."""

    def mutate(doc: dict[str, Any]) -> None:
        row = doc["asset"]["tests/test_web_dom_contract.py"]
        row["negative_control"] = "present"
        row["nc_evidence"] = [
            "tests/test_web_dom_contract.py::test_the_dom_contract_notices_when_its_own_extractor_dies"
        ]

    _expect_red(
        _mutate(document, mutate),
        repo,
        "test_the_dom_contract_notices_when_its_own_extractor_dies",
        "없다",
    )


def test_b4_declaring_a_prose_mention_as_an_invoker_reds_because_it_is_a_comment(
    document: dict[str, Any], repo: Repo
) -> None:
    """B-④: 산문 언급을 호출로 적으면 붉는다. 그 줄이 실제로 주석이거나 마크다운이기 때문이다."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["scripts/gen_design_tokens.py"]["invoked_by"] = [
            "docs/UI_CONTRACT.md#scripts/gen_design_tokens.py"
        ]

    _expect_red(_mutate(document, mutate), repo, "실행되지 않는 파일", "docs/UI_CONTRACT.md")


# ── 등급 C — 합성 변형. 술어마다 하나씩 ────────────────────────────────────
def test_c_predicate_1_raw_file_line_references_are_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_legacy_path_zero.py"]["nc_evidence"] = ["tests/test_legacy_path_zero.py:112"]

    _expect_red(_mutate(document, mutate), repo, "생 file:line", "tests/test_legacy_path_zero.py:112")


def test_c_predicate_1b_a_dead_substring_anchor_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_frontend_module_units.py"]["nc_evidence"] = [
            "tests/test_frontend_module_units.py#EXPECTED_MODULE_FILES"
        ]

    _expect_red(_mutate(document, mutate), repo, "EXPECTED_MODULE_FILES", "출현이 0")


def test_c_predicate_1c_a_vague_anchor_that_matches_many_lines_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """`#def ` 같은 앵커는 아무 파이썬 파일에서나 참이라 좌표가 아니다."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_legacy_path_zero.py"]["nc_evidence"] = [
            "tests/test_legacy_path_zero.py#def "
        ]

    _expect_red(_mutate(document, mutate), repo, "유일하지 않으면")


def test_c_predicate_1d_a_defect_claim_carrying_a_raw_coordinate_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """규칙 1 이 금지한 좌표가 `defect` 로 새던 자리."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_web_dom_contract.py"]["defect"][0]["claim"] = (
            "SCREEN_ROOTS 가 tests/test_web_dom_contract.py:107 에서 둘만 든다"
        )

    _expect_red(_mutate(document, mutate), repo, "claim 이 생 file:line", "좌표는 evidence 앵커가 진다")


def test_c_predicate_2_a_ci_job_outside_the_gate_needs_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_architecture.py"]["ci_jobs"] = ["quality-gate"]

    _expect_red(_mutate(document, mutate), repo, "quality-gate", "needs 열거에 없다")


def test_c_predicate_2b_a_node_file_the_runner_does_not_enumerate_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """러너의 전수 상수에서 이름이 빠지면 그 행은 도달 불가다.

    유령 행으로는 이 술어를 증명할 수 없다 — 파일 부재가 먼저 걸려 도달성 검사까지 가지
    않는다. 그래서 파일은 그대로 두고 **러너의 상수 쪽**을 덮어 본다.
    """
    body = repo.text(NODE_AXIS_SOURCE) or ""
    overlay = OverlayRepo(repo, {NODE_AXIS_SOURCE: body.replace('    "esc.test.js",\n', "", 1)})
    report = check(load_document(), overlay)
    joined = report.text()
    assert "tests/js/esc.test.js" in joined, joined
    assert "러너가 그 파일을 안 센다" in joined, joined


def test_c_predicate_2c_a_script_without_invokers_or_an_orphan_row_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["scripts/seal_web_artifact.py"]["invoked_by"] = []

    _expect_red(_mutate(document, mutate), repo, "scripts/seal_web_artifact.py", "고아는 침묵이")


def test_c_predicate_3_a_missing_asset_row_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        del doc["asset"]["tests/test_web_selftest_gate.py"]

    _expect_red(_mutate(document, mutate), repo, "원장이 안 든 자산", "tests/test_web_selftest_gate.py")


def test_c_predicate_3b_widening_an_exclusion_to_swallow_assets_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """분모 축소의 완성형 — 글롭을 넓히고 size 를 맞추고 삼킨 행을 지운다."""
    swallowed = [
        "tests/test_web_dom_contract.py",
        "tests/test_web_selftest_gate.py",
        "tests/test_web_product_api.py",
        "tests/test_web_css_manifest.py",
        "tests/test_web_press_geometry.py",
    ]

    def mutate(doc: dict[str, Any]) -> None:
        for row in doc["excluded_axis"]:
            if row.get("axis") == "pytest_support_modules":
                row["globs"] = [*row["globs"], "tests/test_web_*.py"]
                row["size"] = 6 + len(
                    [p for p in Repo(REPO_ROOT).glob("tests/test_web_*.py")]
                )
        for rel in swallowed:
            doc["asset"].pop(rel, None)

    _expect_red(_mutate(document, mutate), repo, "러너 글롭이 잡는 자산", "삼킨다")


def test_c_predicate_3c_a_file_outside_every_axis_and_exclusion_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """러너 글롭 **밖으로** 새는 파일 — 축만 보면 영영 조용한 자리."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["excluded_axis"] = [
            r for r in doc["excluded_axis"] if r.get("axis") != "node_hygiene_fixtures"
        ]

    _expect_red(_mutate(document, mutate), repo, "node_hygiene_fixtures")


def test_c_predicate_4_a_react_equivalent_row_without_a_successor_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_web_product_api.py"]["successor_asset"] = ""

    _expect_red(_mutate(document, mutate), repo, "successor_asset", "1:1")


def test_c_predicate_5_an_unassessed_row_without_an_owner_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_dispatch_wiring.py"]["assessment_owner"] = ""

    _expect_red(_mutate(document, mutate), repo, "assessment_owner", "유예는 임자를")


def test_c_predicate_5b_a_known_defect_pointed_at_an_audit_issue_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """결손의 수리는 구현이 진다 — 감사에 떠넘기면 붉는다(U5)."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_web_dom_contract.py"]["reinforcement"] = 409

    _expect_red(_mutate(document, mutate), repo, "감사 이슈 #409", "구현 슬라이스가 진다")


def test_c_predicate_5c_a_deferred_assessment_pointed_at_an_implementation_issue_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """두 열이 서로의 값 공간을 못 쓴다 — 유예를 구현에 떠넘기면 붉는다."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_dispatch_wiring.py"]["assessment_owner"] = "R4-01 #414"

    _expect_red(_mutate(document, mutate), repo, "감사 이슈를 안 가리킨다")


def test_c_predicate_5d_downgrading_a_graded_row_to_deferred_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """등급은 유예로 내려갈 수 없다 — 내리려면 게이트의 필수 목록을 먼저 고쳐야 한다."""

    def mutate(doc: dict[str, Any]) -> None:
        row = doc["asset"]["tests/test_legacy_path_zero.py"]
        row["negative_control"] = "unassessed"
        row["nc_evidence"] = []
        row["assessment_owner"] = "R1-99 #400"

    _expect_red(_mutate(document, mutate), repo, "등급을 유예할 수 없다")


def test_c_predicate_5e_erasing_a_known_defect_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_architecture.py"].pop("defect", None)

    _expect_red(_mutate(document, mutate), repo, "결손 기록은 흔적 없이")


def test_c_predicate_6_a_value_without_its_predicate_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        del doc["census"]["node_pass"]["unit"]

    _expect_red(_mutate(document, mutate), repo, "census.node_pass", "unit")


def test_c_predicate_7_a_landed_chain_that_does_not_close_at_the_base_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["census"]["pytest_collected"]["adjustment"][0]["to_sha"] = (
            "0123456789abcdef0123456789abcdef01234567"
        )

    _expect_red(_mutate(document, mutate), repo, "to_sha 가 base_sha 와 다르다")


def test_c_predicate_7b_an_unlanded_delta_claiming_a_merge_sha_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        for adj in doc["census"]["pytest_collected"]["adjustment"]:
            if adj.get("kind") == "expected_landing":
                adj["to_sha"] = EXPECTED_BASE_SHA

    _expect_red(_mutate(document, mutate), repo, "착지 SHA 는 작성 시점에 알 수 없다")


def test_c_predicate_7c_an_unlanded_delta_that_does_not_match_its_file_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """미착지 델타는 재귀 없이 재잴 수 있다 — 파일 하나의 사례 수는 AST 가 센다."""

    def mutate(doc: dict[str, Any]) -> None:
        for adj in doc["census"]["pytest_collected"]["adjustment"]:
            if adj.get("kind") == "expected_landing":
                adj["delta"] = adj["delta"] - 1

    _expect_red(_mutate(document, mutate), repo, "expected_landing delta", "실측 test 함수 수")


def test_c_predicate_7d_a_fabricated_commit_hash_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """앞 일곱 자만 맞고 나머지를 지어낸 SHA — 리터럴 대조만으로는 영영 안 걸리는 자리."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["census"]["pytest_collected"]["adjustment"][0]["from_sha"] = (
            "8fcc30eddeadbeefdeadbeefdeadbeefdeadbeef"
        )

    _expect_red(_mutate(document, mutate), repo, "없는 커밋이다")


def test_c_predicate_8_a_reinforcement_outside_the_gate_map_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_web_css_manifest.py"]["reinforcement"] = 999

    _expect_red(_mutate(document, mutate), repo, "#999", "succession_issue")


def test_c_predicate_8b_dropping_the_succession_list_breaks_the_row_that_leans_on_it(
    document: dict[str, Any], repo: Repo
) -> None:
    """승계 목록이 TOML 안에 있어야 하는 이유 — 목록이 비면 그것에 기댄 행이 그 자리에서 붉는다."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["succession_issue"] = []
        doc["asset"]["tests/test_web_css_manifest.py"]["reinforcement"] = 455

    _expect_red(_mutate(document, mutate), repo, "승계 이슈 목록이 없다", "#455")


def test_c_predicate_9_a_predicate_without_its_blind_spot_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["bridge_set"]["bridge_js"]["blind_spot"] = "   "

    _expect_red(_mutate(document, mutate), repo, "bridge_set.bridge_js", "blind_spot")


def test_c_predicate_10_a_stale_record_that_went_stale_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["doc_staleness"][0]["anchor"] = "네 화면(`txt`·`editor`·`run`·`job`)"

    _expect_red(_mutate(document, mutate), repo, "사라졌다", "은퇴는 그 텍스트를 고친 PR")


def test_c_predicate_10b_replacing_a_staleness_row_with_a_placeholder_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """서술을 고쳐 기계 검사를 끄는 길 — 프로브가 열거값이라 사라지면 그 자리에서 보인다."""

    def mutate(doc: dict[str, Any]) -> None:
        for row in doc["doc_staleness"]:
            row["probe"] = "none"
            row["assessment_owner"] = "R3-99 #409"
            row.pop("today_measured", None)

    _expect_red(_mutate(document, mutate), repo, "되묻는 프로브가 빠졌다")


def test_c_predicate_10c_a_shrinking_measurement_is_refused_not_only_a_growing_one(
    document: dict[str, Any], repo: Repo
) -> None:
    """줄어드는 방향 — 초집합 검사였다면 영영 조용했을 자리."""
    body = repo.text("tests/test_web_dom_contract.py") or ""
    shrunk = body.replace(
        'PRESERVE_WRAPPED_FILES = ("screens/editor.js", "screens/job.js", "screens/workbench.js")',
        'PRESERVE_WRAPPED_FILES = ("screens/editor.js", "screens/job.js")',
        1,
    )
    assert shrunk != body, "대조 재료를 못 만들었다 — 상수의 모양이 바뀌었다."
    overlay = OverlayRepo(repo, {"tests/test_web_dom_contract.py": shrunk})
    report = check(load_document(), overlay)
    assert "today_measured" in report.text(), report.text()


def test_c_predicate_11_flipping_a_web_facing_asset_out_of_scope_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """r_scope 를 원장의 자유 변수로 만들려는 시도 — 하한 술어가 그 자리에서 잡는다."""

    def mutate(doc: dict[str, Any]) -> None:
        row = doc["asset"]["tests/test_web_dom_contract.py"]
        for key in (
            "protects",
            "successor",
            "successor_asset",
            "stage",
            "negative_control",
            "nc_evidence",
            "blind_spot",
            "defect",
            "reinforcement",
        ):
            row.pop(key, None)
        row["r_scope"] = False
        row["reason"] = "React 와 무관하다고 판단한다."

    _expect_red(
        _mutate(document, mutate),
        repo,
        "이름으로 부르는데 r_scope=false",
        "tests/test_web_dom_contract.py",
    )


def test_c_predicate_12_a_bridge_set_value_that_drifts_from_the_repo_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["bridge_set"]["documented"]["value"] = 23

    _expect_red(_mutate(document, mutate), repo, "bridge_set.documented", "실측 21")


def test_c_predicate_12b_hiding_the_contract_gate_slack_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """`test_architecture.py` 의 여유를 0 으로 적으면 붉는다 — 그 세 수가 산문이 아니라 필드인 이유다."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["bridge_set"]["contract_gate_slack"]["satisfied_only_outside_section"] = 0

    _expect_red(_mutate(document, mutate), repo, "satisfied_only_outside_section", "실측 2")


def test_c_predicate_12c_a_dead_scope_anchor_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """앵커처럼 생겼는데 아무도 안 보던 유일한 필드."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["bridge_set"]["documented"]["scope_anchor"] = "docs/NOPE.md#nothing"

    _expect_red(_mutate(document, mutate), repo, "scope_anchor", "docs/NOPE.md")


def test_c_predicate_13_a_markers_declaration_that_drifts_from_the_source_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_web_press_geometry.py"]["markers"] = []

    _expect_red(_mutate(document, mutate), repo, "markers 선언", "실측 ['browser']")


def test_c_predicate_13b_a_class_level_marker_is_not_mistaken_for_an_unmarked_case(
    repo: Repo
) -> None:
    """클래스에 붙은 축 marker 가 메서드로 내려온다 — 함수만 보면 그 파일이 결정론 잡에
    기여한다고 잘못 적히고, 게이트가 같은 술어를 써서 그 오답을 확인해 준다."""
    marks, bare = measure_axis_markers(repo, "tests/test_native_positive.py")
    assert marks == ["native"]
    assert not bare, (
        "클래스 데코레이터를 못 보고 있다 — 이 파일의 사례는 전부 native 라 "
        "pytest-contract 잡에는 하나도 기여하지 않는다."
    )


def test_c_predicate_14_an_empty_ledger_does_not_pass(repo: Repo) -> None:
    """분모가 게이트에 있어야 하는 이유 — 빈 원장은 통과하지 못한다."""
    _expect_red({}, repo, "schema", "asset 표가 없다")


def test_c_predicate_15_shrinking_the_axis_list_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """축을 지우고 그만큼 행을 정리하는 길 — 축 이름 집합이 게이트 리터럴이라 막힌다."""

    def mutate(doc: dict[str, Any]) -> None:
        del doc["census"]["node_pass"]

    _expect_red(_mutate(document, mutate), repo, "축 집합이 게이트 리터럴과 다르다", "node_pass")


def test_c_predicate_16_dropping_an_explicit_exclusion_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["excluded_axis"] = [
            r for r in doc["excluded_axis"] if r.get("axis") != "powershell_runners"
        ]

    _expect_red(_mutate(document, mutate), repo, "powershell_runners")


def test_c_predicate_17_a_runner_floor_that_drifts_from_the_source_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """이 축이 실제로 요구받는 것은 값이 아니라 하한이다 — 그 하한이 움직이면 붉는다."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["census"]["node_pass"]["runner_floor"] = 596

    _expect_red(_mutate(document, mutate), repo, "runner_floor", "실측 220")


def test_c_predicate_18_a_blocking_ci_job_nobody_owns_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """차단 잡이 원장 밖으로 새는 길 — 선언→실재 한 방향만 보면 영영 조용하다."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["uncovered_ci_job"] = [
            r for r in doc["uncovered_ci_job"] if r.get("job") != "sealed-web"
        ]

    _expect_red(_mutate(document, mutate), repo, "sealed-web", "차단 잡이 조용히")


# ── 2왕복 반증이 연 자리들 ─────────────────────────────────────────────────
def test_c_predicate_19_a_zero_occurrence_anchor_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """`@N` 형식이 열어 버린 자리 — `@0` 은 아무 문자열이나 증거로 만든다."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_legacy_path_zero.py"]["nc_evidence"] = [
            "tests/test_legacy_path_zero.py#Q7x_NO_SUCH_TOKEN_9z@0"
        ]

    _expect_red(_mutate(document, mutate), repo, "@0 앵커", "앵커가 아니다")


def test_c_predicate_19b_an_empty_anchor_needle_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_legacy_path_zero.py"]["nc_evidence"] = [
            "tests/test_legacy_path_zero.py#@3"
        ]

    _expect_red(_mutate(document, mutate), repo, "빈 앵커")


def test_c_predicate_20_a_prose_invoker_in_function_form_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """`#` 형식만 막고 `::` 형식은 열려 있던 자리 — 같은 거짓이 다른 문법으로 통과했다."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["scripts/gen_design_tokens.py"]["invoked_by"] = [
            "docs/UX_FEEDBACK_U2.md::_run_marker"
        ]

    _expect_red(_mutate(document, mutate), repo, "실행되지 않는 파일")


def test_c_predicate_20b_an_invoker_anchor_that_never_names_the_script_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """실행되는 파일의 실행되는 줄이어도, 그 스크립트를 안 부르면 호출의 증거가 아니다."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["scripts/gen_design_tokens.py"]["invoked_by"] = [
            "tests/test_react_verification_ledger.py#ASSET_FLOOR = 170"
        ]

    _expect_red(_mutate(document, mutate), repo, "이름으로 부르지 않는다")


def test_c_predicate_21_an_unlanded_delta_pointed_at_an_existing_file_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """`file` 이 원장의 자유 변수이면 재측정이 자기 일관성일 뿐 검증이 아니다."""

    def mutate(doc: dict[str, Any]) -> None:
        for adj in doc["census"]["pytest_collected"]["adjustment"]:
            if adj.get("kind") == "expected_landing":
                adj["file"] = "tests/test_webapp_editor.py"
                adj["delta"] = 114

    _expect_red(_mutate(document, mutate), repo, "이미 있던", "미착지 델타는")


def test_c_predicate_22_a_landed_chain_starting_anywhere_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """사슬의 한쪽 끝만 고정하면 반대쪽은 아무 조상이어도 통과한다."""
    root = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()[0]

    def mutate(doc: dict[str, Any]) -> None:
        doc["census"]["pytest_collected"]["adjustment"][0]["from_sha"] = root

    _expect_red(_mutate(document, mutate), repo, "직전 기준과 다르다")


def test_c_predicate_23_a_node_row_claiming_a_job_it_does_not_run_in_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """node 행의 ci_jobs 가 자유 서술이면 차단 잡 피복이 세탁된다."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/js/n10_global_hygiene.test.js"]["ci_jobs"] = ["distribution-webview2"]
        doc["uncovered_ci_job"] = [
            r for r in doc["uncovered_ci_job"] if r.get("job") != "distribution-webview2"
        ]

    _expect_red(_mutate(document, mutate), repo, "node 행의 ci_jobs")


def test_c_predicate_24_laundering_a_known_gap_into_a_deferral_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """U5 가 한 방향으로만 서 있던 자리 — 결손을 유예로 바꾸면 임자가 구현에서 감사로 넘어간다."""

    def mutate(doc: dict[str, Any]) -> None:
        row = doc["asset"]["tests/test_web_product_api.py"]
        row["negative_control"] = "unassessed"
        row.pop("reinforcement", None)
        row["assessment_owner"] = "R1-99 #400"

    _expect_red(_mutate(document, mutate), repo, "none 으로 고정")


def test_c_predicate_25_a_staleness_row_pointed_at_another_document_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """낡음 주장과 기계 검사가 서로 다른 문서를 보던 자리."""

    def mutate(doc: dict[str, Any]) -> None:
        for row in doc["doc_staleness"]:
            if row.get("probe") == "preserve_scroll_ids":
                row["file"] = "docs/README.md"
                row["anchor"] = "유지·아카이브·폐기 기준"

    _expect_red(_mutate(document, mutate), repo, "다른 문서를 보면")


def test_c_predicate_25b_a_one_character_staleness_anchor_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["doc_staleness"][0]["anchor"] = "3"

    _expect_red(_mutate(document, mutate), repo, "너무 짧다")


def test_c_predicate_26_a_boolean_masquerading_as_a_count_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """`False == 0` 이라 정수 분기가 형을 안 물으면 조용히 통과한다."""

    def mutate(doc: dict[str, Any]) -> None:
        for row in doc["doc_staleness"]:
            if row.get("probe") == "product_push_producers":
                row["today_measured"] = False

    _expect_red(_mutate(document, mutate), repo, "정수가 아니다")


def test_c_predicate_27_an_exclusion_that_excludes_nothing_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        for row in doc["excluded_axis"]:
            if row.get("axis") == "node_hygiene_fixtures":
                row["globs"] = ["tests/js/NOTHING/**/*.js"]
                row["size"] = 0

    _expect_red(_mutate(document, mutate), repo, "크기 0 의 제외는 장식")


def test_c_predicate_27b_two_axes_covering_the_same_file_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """축 사이로 파일을 옮길 수 있으면 사유·소유가 장식이 된다."""

    def mutate(doc: dict[str, Any]) -> None:
        for row in doc["excluded_axis"]:
            if row.get("axis") == "pytest_support_modules":
                row["globs"] = [*row["globs"], "tests/js/fixtures/**/*.js"]
                row["size"] = 6 + 27

    _expect_red(_mutate(document, mutate), repo, "두 축이 함께 든다")


def test_c_predicate_28_an_exclusion_wider_than_the_declared_tree_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """트리보다 넓은 제외는 「덮이지 않은 것 0」을 거짓 빨강으로 만든다."""

    def mutate(doc: dict[str, Any]) -> None:
        for row in doc["excluded_axis"]:
            if row.get("axis") == "example_fixture_generators":
                row["globs"] = ["examples/**/*.py", "docs/**/*.md"]
                row["size"] = 1 + len(Repo(REPO_ROOT).glob("docs/**/*.md"))

    _expect_red(_mutate(document, mutate), repo, "검증 트리 밖을 덮는다")


def test_c_predicate_29_the_indirect_marker_probe_actually_fires(repo: Repo) -> None:
    """프로브가 **살아 있는가**를 묻는다.

    이 단언 없이 실린 첫 판은 정규식 끝에 제어 문자 하나가 섞여 어떤 입력에도 영영
    안 맞았다 — 「사각을 본다」는 선언만 남고 결과는 죽어 있었다. 프로브가 잡아야 할
    모양을 실제로 만들어 먹여 본다.
    """
    target = "tests/test_native_positive.py"
    body = repo.text(target) or ""
    for injected in (
        "native = pytest.mark.native\n" + body.replace("@pytest.mark.native", "@native", 1),
        'native = getattr(pytest.mark, "native")\n' + body.replace("@pytest.mark.native", "@native", 1),
    ):
        overlay = OverlayRepo(repo, {target: injected})
        assert _probe_indirect_markers(overlay, {target}) == [target], (
            "프로브가 자기가 잡겠다고 선언한 모양을 못 잡는다."
        )
    # 양성 대조 — 오늘의 저장소에는 그 모양이 없다.
    assert _probe_indirect_markers(repo, {target}) == []


def test_c_predicate_30_a_boolean_census_total_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """센서스 총계는 재귀 때문에 재측정하지 않는 **유일한** 축이라, 형을 안 물으면
    `false` 가 0 으로 실린 채 영영 조용하다."""

    def mutate(doc: dict[str, Any]) -> None:
        doc["census"]["pytest_collected"]["value"] = False

    _expect_red(_mutate(document, mutate), repo, "정수가 아니다", "bool 은 정수처럼")


def test_c_predicate_30b_a_negative_census_total_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["census"]["pytest_collected"]["value"] = -1

    _expect_red(_mutate(document, mutate), repo, "음수다", "세는 값은 음수일 수 없다")


def test_c_predicate_30c_the_numeric_contract_covers_every_counting_field(
    document: dict[str, Any], repo: Repo
) -> None:
    """지적은 센서스 한 자리를 겨눴지만 같은 결함류는 원장의 모든 수치 필드였다.

    필드마다 고치면 다음 필드가 다음 지적이 된다 — 계약을 하나 세우고 그것이 전 필드에
    걸리는지를 여기서 센다.
    """
    coordinates = [
        ("census.pytest_collected.value", lambda d: d["census"]["pytest_collected"].__setitem__("value", True)),
        ("census.node_pass.runner_floor", lambda d: d["census"]["node_pass"].__setitem__("runner_floor", True)),
        ("bridge_set.documented.value", lambda d: d["bridge_set"]["documented"].__setitem__("value", True)),
        ("bridge_set.derived.js_only", lambda d: d["bridge_set"]["derived"].__setitem__("js_only", True)),
        (
            "bridge_set.contract_gate_slack",
            lambda d: d["bridge_set"]["contract_gate_slack"].__setitem__("invisible_to_the_gate", True),
        ),
        ("excluded_axis.size", lambda d: d["excluded_axis"][0].__setitem__("size", True)),
        ("succession_issue.id", lambda d: d["succession_issue"][0].__setitem__("id", True)),
        (
            "adjustment.delta",
            lambda d: d["census"]["pytest_collected"]["adjustment"][0].__setitem__("delta", True),
        ),
    ]
    for name, mutate in coordinates:
        report = check(_mutate(document, mutate), repo)
        assert "정수가 아니다" in report.text(), (
            f"{name} 이 불리언을 받는다 — 수치 계약이 이 자리에 안 걸려 있다.\n{report.text()}"
        )


def test_c_predicate_31_dropping_an_unlanded_row_from_the_chain_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """총계는 재측정하지 않지만 **사슬의 완비성**은 재귀 없이 물을 수 있다 —
    미착지 행을 지우면 이 PR 이 들이는 사례가 공표된 총계에서 조용히 빠진다."""

    def mutate(doc: dict[str, Any]) -> None:
        block = doc["census"]["pytest_unmarked"]
        block["adjustment"] = [a for a in block["adjustment"] if a.get("kind") != "expected_landing"]

    _expect_red(_mutate(document, mutate), repo, "미착지 행으로", "조용히 빠진다")


def test_c_predicate_32_a_coordinate_in_a_migration_era_suffix_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """규칙 1 의 확장자 목록이 검증 트리보다 좁던 자리.

    `.tsx`·`.jsx`·`.yaml`·`.spec` 은 트리가 이미 겨누는데 좌표 탐지만 안 넓어져 있었다.
    이제 둘 다 `TEXT_SUFFIXES` 하나에서 나오므로 정의상 같이 움직인다.
    """
    for coordinate in (
        "frontend/src/App.tsx:123",
        "frontend/src/App.jsx:7",
        ".github/workflows/x.yaml:12",
        "packaging/hwpx_cli.spec:30",
    ):
        def mutate(doc: dict[str, Any], c: str = coordinate) -> None:
            doc["asset"]["tests/test_web_dom_contract.py"]["blind_spot"] = f"사각 하나는 {c} 다."

        report = check(_mutate(document, mutate), repo)
        assert "생 file:line" in report.text(), (
            f"{coordinate} 가 좌표로 안 잡힌다 — 규칙 1 이 이 형식에서만 침묵한다.\n{report.text()}"
        )
