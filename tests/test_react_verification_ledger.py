"""old→new 검증 책임 원장의 재실측기 — R1-03 (#403).

원장(`docs/react_verification_ledger.toml`)은 「어느 검증 자산이 무엇을 지키고, React
이후에 누가 그 성질을 잇는가」를 든다. 이 파일은 그 선언을 믿지 않는다.

세 층으로 센다.

1. **전수 피복** — 네 러너 글롭(`tests/test_*.py` · `tests/*_test.py` ·
   `tests/js/*.test.js` · `scripts/**/*.py`)을 게이트가 스스로 열거하고, 원장이 안 든
   파일과 원장에만 있는 유령 행을 양방향으로 센다. 새 테스트 파일이 원장 없이 들어오면
   그 자리에서 붉는다.
2. **술어 재실행** — 값을 든 항목(직접 브리지 네 집합 · 제외 축 크기 · 문서 낡음 앵커 ·
   `markers` · `ci_jobs`)은 저장소에 다시 재서 기록값과 대조한다. 센서스만은 재측정하지
   않는다 — pytest 안에서 pytest 를 다시 수집하면 autouse 홈 격리·coverage·
   `--strict-markers` 가 겹쳐 재귀가 되기 때문이고, 그 축은 구조만 본다.
3. **분모 고정** — 축 이름 집합·자산 하한·`r_scope` 하한 술어·제외 축 목록은 **이 파일의
   리터럴**로 산다. 원장에서 유도하면 축을 지우고 그만큼 행을 정리하는 것으로 초록이 되고,
   극단에는 빈 원장이 통과한다.

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

# ── 분모 리터럴 ────────────────────────────────────────────────────────────
# 원장이 자기 분모를 줄이지 못하게 게이트가 든다.

EXPECTED_SCHEMA = "react_verification_ledger/v1"
EXPECTED_BASE_SHA = "8a69bc48b96a3f3a2fbbba7dcd2b0e93ba18e1c9"
EXPECTED_OWNER_ISSUE = 403
EXPECTED_GATE = "tests/test_react_verification_ledger.py"

#: 술어 3 이 전수로 도는 네 러너 글롭. 비재귀 `scripts/*.py` 는 `scripts/live101/` 여섯
#: 모듈을 조용히 축 밖에 두므로 **재귀**다.
RUNNER_GLOBS: dict[str, tuple[str, ...]] = {
    "pytest": ("tests/test_*.py", "tests/*_test.py"),
    "node": ("tests/js/*.test.js",),
    "script": ("scripts/**/*.py",),
}

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
    {"node_extractor_scripts", "pytest_support_modules", "powershell_runners"}
)
ORPHAN_SCRIPTS = frozenset(
    {"scripts/build_nara_testset.py", "scripts/gen_scenario_fixtures.py"}
)
DOC_STALENESS_FLOOR = 4

SUCCESSORS = frozenset({"keep", "react_equivalent", "retire", "out_of_scope"})
NEGATIVE_CONTROLS = frozenset({"present", "partial", "none", "unassessed"})
RUNNERS = frozenset(RUNNER_GLOBS)

#: R-GATE-MAP:v1 이 분배한 **구현** 슬라이스. reinforcement 는 여기 ∪ succession_issue 만
#: 허용한다 — 결손의 수리는 구현이 지지 감사가 지지 않는다(U5).
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

TEXT_SUFFIXES = frozenset(
    {".py", ".js", ".mjs", ".ts", ".html", ".css", ".toml", ".json", ".md", ".yml", ".ps1", ".txt"}
)


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
_RAW_LINE_REF = re.compile(r"^[\w./\\-]+\.(?:py|js|mjs|ts|html|css|toml|json|md|yml|ps1):\d+")


def _check_anchor(where: str, ref: str, repo: Repo, report: Report) -> None:
    """`path` · `path::test_함수명` · `path#부분문자열` 셋만 유효하다."""
    if _RAW_LINE_REF.match(ref):
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
    if "#" in ref:
        rel, needle = ref.split("#", 1)
        body = repo.text(rel)
        if body is None:
            report.fail(where, f"앵커가 가리키는 파일이 없다: {rel} (참조 {ref!r})")
            return
        if needle not in body:
            report.fail(where, f"{rel} 에 앵커 문자열 {needle!r} 이 없다 (참조 {ref!r})")
        return
    if not repo.exists(ref):
        report.fail(where, f"참조가 가리키는 파일이 없다: {ref!r}")


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
def measure_axis_markers(repo: Repo, rel: str) -> tuple[list[str], bool]:
    """(파일에 등장하는 축 marker, 축 marker 없는 test 함수가 하나라도 있는가)."""
    body = repo.text(rel)
    if body is None:
        return [], False
    tree = ast.parse(body)
    found: set[str] = set()
    has_bare = False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        mine: set[str] = set()
        for dec in node.decorator_list:
            expr = dec.func if isinstance(dec, ast.Call) else dec
            names: list[str] = []
            while isinstance(expr, ast.Attribute):
                names.append(expr.attr)
                expr = expr.value
            if isinstance(expr, ast.Name):
                names.append(expr.id)
            names.reverse()
            if len(names) >= 3 and names[0] == "pytest" and names[1] == "mark" and names[2] in AXIS_MARKERS:
                mine.add(names[2])
        found |= mine
        has_bare = has_bare or not mine
    return sorted(found), has_bare


def measure_module_level_marks(repo: Repo, rel: str) -> bool:
    """`pytestmark = …` 모듈 최상위 대입이 있는가 — 위 술어의 사각."""
    body = repo.text(rel)
    if body is None:
        return False
    tree = ast.parse(body)
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
            return True
    return False


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


def measure_node_runner_floor(repo: Repo) -> int | None:
    """`node --test` 축이 pytest 에서 실제로 요구받는 **하한**. 실측값이 아니라 하한이다."""
    body = repo.text(NODE_AXIS_SOURCE)
    if body is None:
        return None
    m = re.search(r'counts\.get\(\s*"pass"\s*,\s*0\s*\)\s*>=\s*(\d+)', body)
    return int(m.group(1)) if m else None


def measure_preserve_wrapped_files(repo: Repo) -> list[str]:
    body = repo.text("tests/test_web_dom_contract.py") or ""
    m = re.search(rf"^{'PRESERVE_WRAPPED_FILES'}\s*=\s*\((.*?)\)", body, re.M | re.S)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


def measure_preserve_scroll_ids(repo: Repo) -> list[str]:
    body = repo.text("frontend/index.html") or ""
    found: list[str] = []
    for tag in re.finditer(r"<[^>]*data-preserve-scroll[^>]*>", body):
        m = re.search(r'id="([^"]+)"', tag.group(0))
        if m:
            found.append(m.group(1))
    return sorted(found)


def measure_product_push_global(repo: Repo) -> int:
    """제품 전역 `window.__push` 의 **생산** 지점 수. 은퇴를 지키는 참조는 세지 않는다."""
    count = 0
    for rel in repo.tracked():
        if not (rel.startswith("frontend/") or rel.startswith("src/hwpxfiller/")):
            continue
        body = repo.text(rel)
        if body is None:
            continue
        count += len(re.findall(r"window\.__push\s*=", body))
    return count


# ── 본 검사 ───────────────────────────────────────────────────────────────
def check(document: dict[str, Any], repo: Repo) -> Report:
    report = Report()
    _check_meta(document, report)
    assets = _check_assets(document, repo, report)
    _check_census(document, repo, report)
    _check_bridge_sets(document, repo, report)
    _check_doc_staleness(document, repo, report)
    _check_orphan_scripts(document, repo, report)
    _check_excluded_axes(document, repo, report)
    _check_succession_issues(document, report)
    _check_coverage(document, assets, repo, report)
    return report


def _check_meta(document: dict[str, Any], report: Report) -> None:
    if document.get("schema") != EXPECTED_SCHEMA:
        report.fail("meta", f"schema 가 {EXPECTED_SCHEMA!r} 가 아니다: {document.get('schema')!r}")
    if document.get("base_sha") != EXPECTED_BASE_SHA:
        report.fail("meta", f"base_sha 가 게이트 리터럴과 다르다: {document.get('base_sha')!r}")
    if document.get("owner_issue") != EXPECTED_OWNER_ISSUE:
        report.fail("meta", f"owner_issue 가 {EXPECTED_OWNER_ISSUE} 가 아니다.")
    if document.get("gate") != EXPECTED_GATE:
        report.fail("meta", f"gate 가 {EXPECTED_GATE!r} 를 안 가리킨다.")
    for key in ("scope_statement", "not_asserted", "row_scope"):
        value = document.get(key)
        if not isinstance(value, str) or not value.strip():
            report.fail("meta", f"{key} 가 비어 있다 — 주장의 범위는 데이터다.")


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
        row.get("path")
        for row in document.get("orphan_script", [])
        if isinstance(row, dict)
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
                for ref in invoked:
                    _check_anchor(where + ".invoked_by", ref, repo, report)
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
            if not isinstance(issue, int):
                report.fail(where, "negative_control=none 인데 reinforcement 가 없다 — 알려진 결손은 임자를 든다.")
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

        if isinstance(row.get("defect"), list):
            for item in row["defect"]:
                if not isinstance(item, str) or not item.strip():
                    report.fail(where, "defect 항목이 비어 있다.")
    return assets


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
        if not isinstance(axis.get("value"), int):
            report.fail(where, "value 가 정수가 아니다.")
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
                if not isinstance(adj.get("from_sha"), str) or not adj.get("from_sha"):
                    report.fail(where, "landed adjustment 가 from_sha 를 안 든다.")
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
            else:
                report.fail(where, f"adjustment.kind 가 landed/expected_landing 밖이다: {kind!r}")
            if not isinstance(adj.get("delta"), int):
                report.fail(where, "adjustment 가 정수 delta 를 안 든다.")
            if not isinstance(adj.get("reason"), str) or not adj.get("reason", "").strip():
                report.fail(where, "adjustment 가 reason 을 안 든다 — 정당화 없는 증감은 정당화가 아니다.")

    node_axis = census.get("node_pass", {})
    if "runner_floor" in node_axis:
        measured_floor = measure_node_runner_floor(repo)
        if measured_floor is None:
            report.fail(
                "census.node_pass",
                f"{NODE_AXIS_SOURCE} 에서 하한 술어를 못 찾았다 — 그 단언이 사라졌거나 모양이 바뀌었다.",
            )
        elif node_axis["runner_floor"] != measured_floor:
            report.fail(
                "census.node_pass",
                f"runner_floor 기록값 {node_axis['runner_floor']!r} 이 실측 {measured_floor} 과 다르다.",
            )
        if not isinstance(node_axis.get("runner_floor_predicate"), str):
            report.fail("census.node_pass", "runner_floor 가 자기 술어를 안 든다.")
    else:
        report.fail("census.node_pass", "runner_floor 가 없다 — 이 축이 실제로 요구받는 하한은 값과 다르다.")


def _check_bridge_sets(document: dict[str, Any], repo: Repo, report: Report) -> None:
    block = document.get("bridge_set")
    if not isinstance(block, dict):
        report.fail("bridge_set", "bridge_set 표가 없다.")
        return
    measured = measure_bridge_sets(repo)
    if set(block) != BRIDGE_SET_MEASURED | {"derived", "contract_gate_slack"}:
        report.fail(
            "bridge_set",
            f"집합 목록이 게이트 리터럴과 다르다: {sorted(block)}",
        )
    for name in sorted(BRIDGE_SET_MEASURED & set(block)):
        where = f"bridge_set.{name}"
        item = block[name]
        _require_predicate_triple(where, item, report)
        if item.get("value") != measured[name]:
            report.fail(
                where,
                f"기록값 {item.get('value')!r} 이 실측 {measured[name]} 과 다르다.",
            )
    derived = block.get("derived", {})
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
        elif slack[key] != measured[key]:
            report.fail(
                "bridge_set.contract_gate_slack",
                f"{key} 기록값 {slack[key]!r} 이 실측 {measured[key]!r} 과 다르다.",
            )


def _check_doc_staleness(document: dict[str, Any], repo: Repo, report: Report) -> None:
    rows = document.get("doc_staleness")
    if not isinstance(rows, list) or len(rows) < DOC_STALENESS_FLOOR:
        report.fail(
            "doc_staleness",
            f"행이 하한 {DOC_STALENESS_FLOOR} 아래다: {len(rows) if isinstance(rows, list) else rows!r}",
        )
        if not isinstance(rows, list):
            return
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
        for key in ("stale_claim", "predicate", "scope", "unit", "successor_doc"):
            value = row.get(key)
            if not isinstance(value, str) or not value.strip():
                report.fail(where, f"{key} 가 비었다.")
        today = row.get("today_value")
        owner = row.get("assessment_owner")
        if not isinstance(today, str):
            report.fail(where, "today_value 가 없다.")
        elif not today.strip():
            if not isinstance(owner, str) or not owner.strip():
                report.fail(
                    where,
                    "today_value 가 비었는데 assessment_owner 도 없다 — 안 잰 것은 임자를 들어야 한다.",
                )
            elif not (m := re.search(r"#(\d+)", owner)) or int(m.group(1)) not in AUDIT_ISSUES:
                report.fail(where, f"assessment_owner {owner!r} 가 감사 이슈를 안 가리킨다.")

    # 오늘값이 실제 저장소 사실인지 — 세 행은 재실측으로 대조한다.
    wrapped = measure_preserve_wrapped_files(repo)
    scroll_ids = measure_preserve_scroll_ids(repo)
    push_producers = measure_product_push_global(repo)
    report.notes["preserve_wrapped_files"] = wrapped
    report.notes["preserve_scroll_ids"] = scroll_ids
    report.notes["product_push_producers"] = push_producers
    for index, row in enumerate(rows):
        today = row.get("today_value") or ""
        where = f"doc_staleness[{index}]"
        if "PRESERVE_WRAPPED_FILES" in (row.get("predicate") or ""):
            for name in wrapped:
                if name not in today:
                    report.fail(where, f"today_value 가 실측 원소 {name!r} 를 안 든다.")
        if "data-preserve-scroll" in (row.get("predicate") or ""):
            for name in scroll_ids:
                if name not in today:
                    report.fail(where, f"today_value 가 실측 id {name!r} 를 안 든다.")
        if "window.__push" in (row.get("predicate") or ""):
            if str(push_producers) not in today:
                report.fail(
                    where,
                    f"today_value 가 실측 생산 지점 수 {push_producers} 를 안 든다.",
                )


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
        if row.get("size") != len(measured):
            report.fail(
                where,
                f"size 기록값 {row.get('size')!r} 이 실측 {len(measured)} 과 다르다: {measured}",
            )
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
        if not isinstance(row.get("id"), int):
            report.fail(where, "id 가 정수가 아니다.")
        elif row["id"] in AUDIT_ISSUES:
            report.fail(where, f"승계 이슈가 감사 이슈 #{row['id']} 다.")
        for key in ("reason", "origin"):
            if not isinstance(row.get(key), str) or not row.get(key, "").strip():
                report.fail(where, f"{key} 가 없다.")


def _check_coverage(
    document: dict[str, Any], assets: dict[str, dict], repo: Repo, report: Report
) -> None:
    """술어 3 — 네 러너 글롭 전수가 행으로 있는가, 그리고 r_scope 하한을 지키는가."""
    excluded_globs = [
        g
        for row in document.get("excluded_axis", [])
        for g in (row.get("globs") or [])
        if isinstance(g, str)
    ]
    excluded_files = {p for g in excluded_globs for p in repo.glob(g)}

    measured: dict[str, set[str]] = {}
    for runner, globs in RUNNER_GLOBS.items():
        found: set[str] = set()
        for pattern in globs:
            found |= set(repo.glob(pattern))
        measured[runner] = found - excluded_files

    all_measured = set().union(*measured.values())
    missing = sorted(all_measured - set(assets))
    if missing:
        report.fail(
            "coverage",
            f"원장이 안 든 자산 {len(missing)}: {missing[:20]}"
            + (" …" if len(missing) > 20 else ""),
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

    if len(assets) < ASSET_FLOOR:
        report.fail("coverage", f"자산 행 {len(assets)} 이 하한 {ASSET_FLOOR} 아래다.")

    # r_scope 하한 술어 — 넓히는 방향으로만 자유롭다.
    floor_hits: set[str] = set()
    for rel in sorted(all_measured):
        body = repo.text(rel)
        if body and R_SCOPE_FLOOR_PREDICATE.search(body):
            floor_hits.add(rel)
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

    report.notes["asset_rows"] = len(assets)
    report.notes["r_scope_true"] = len(true_rows)
    report.notes["r_scope_false"] = len(assets) - len(true_rows)
    report.notes["r_scope_floor_hits"] = len(floor_hits)
    report.notes["unassessed"] = sum(
        1 for row in assets.values() if row.get("negative_control") == "unassessed"
    )
    report.notes["module_level_marks"] = sorted(
        rel for rel in measured["pytest"] if measure_module_level_marks(repo, rel)
    )


# ── 하니스 ────────────────────────────────────────────────────────────────
def load_document(path: Path = LEDGER_PATH) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


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
    assert notes["orphan_scripts"] == sorted(ORPHAN_SCRIPTS)
    assert notes["orphan_disposition_unknown"] == len(ORPHAN_SCRIPTS)
    assert set(notes["excluded_axis_sizes"]) == set(EXCLUDED_AXES)
    assert notes["unassessed"] > 0, "유예가 0 이면 이 원장은 읽지 않은 것을 등급으로 승격했다는 뜻이다."
    # 축 marker 술어의 사각 — 오늘 모듈 최상위 pytestmark 는 0 이고, 하나 생기면 여기서 보인다.
    assert notes["module_level_marks"] == [], (
        "모듈 최상위 pytestmark 가 생겼다. markers 술어는 데코레이터만 보므로 "
        f"그 파일의 축은 지금 잘못 세고 있다: {notes['module_level_marks']}"
    )


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
            if "data-preserve-scroll" in (row.get("predicate") or ""):
                row["today_value"] = "renderView · tokPanel · editor-body · recList · mxJobList · mxRecList 여섯이 전부 실재한다"

    _expect_red(_mutate(document, mutate), repo, "실측 id", "libraryList")


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

    _expect_red(_mutate(document, mutate), repo, "EXPECTED_MODULE_FILES", "앵커 문자열")


def test_c_predicate_2_a_ci_job_outside_the_gate_needs_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_architecture.py"]["ci_jobs"] = ["quality-gate"]

    _expect_red(_mutate(document, mutate), repo, "quality-gate", "needs 열거에 없다")


def test_c_predicate_2b_a_node_file_outside_the_runner_enumeration_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/js/n07_bridge.test.js"]["runner"] = "node"
        doc["asset"]["tests/js/ghost.test.js"] = dict(doc["asset"]["tests/js/n07_bridge.test.js"])

    _expect_red(_mutate(document, mutate), repo, "tests/js/ghost.test.js", "유령")


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


def test_c_predicate_3b_widening_an_exclusion_to_swallow_an_axis_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    """제외 글롭을 넓혀 자산을 삼키면 크기 실측이 그 자리에서 어긋난다."""

    def mutate(doc: dict[str, Any]) -> None:
        for row in doc["excluded_axis"]:
            if row.get("axis") == "pytest_support_modules":
                row["globs"] = ["tests/_*.py", "tests/conftest.py", "conftest.py", "tests/test_web_*.py"]

    _expect_red(_mutate(document, mutate), repo, "size 기록값", "실측")


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
        doc["census"]["pytest_collected"]["adjustment"][0]["to_sha"] = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

    _expect_red(_mutate(document, mutate), repo, "to_sha 가 base_sha 와 다르다")


def test_c_predicate_7b_an_unlanded_delta_claiming_a_merge_sha_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        for adj in doc["census"]["pytest_collected"]["adjustment"]:
            if adj.get("kind") == "expected_landing":
                adj["to_sha"] = EXPECTED_BASE_SHA

    _expect_red(_mutate(document, mutate), repo, "착지 SHA 는 작성 시점에 알 수 없다")


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


def test_c_predicate_13_a_markers_declaration_that_drifts_from_the_source_is_refused(
    document: dict[str, Any], repo: Repo
) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        doc["asset"]["tests/test_web_press_geometry.py"]["markers"] = []

    _expect_red(_mutate(document, mutate), repo, "markers 선언", "실측 ['browser']")


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
