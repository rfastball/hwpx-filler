"""복잡도 예산의 측정기 — **단일 출처**. 원장 판정(`complexity_budget.py`)과 계약 테스트
(`tests/repo_contract/test_complexity_budget.py`)가 같은 함수로 잰다.

## 왜 줄 수가 아니라 AST 인가

줄 수는 줄 잇기(`;`)·독스트링 삭제로 공짜로 줄어들고, 긴 한국어 독스트링을 벌한다. 그래서
네 축 모두 구문 트리 노드를 센다 — 같은 코드를 어떻게 줄바꿈하든 같은 값이 나온다.

| 축 | 단위 | 세는 것 |
|---|---|---|
| `module_statements` | 파일 | 파일 안 **모든** 문장 노드(독스트링 식 문장·JS 지시어 제외) |
| `class_methods` | 클래스 | 클래스 몸체에 **직접** 놓인 메서드(JS 는 함수 값을 가진 필드 포함) |
| `function_complexity` | 함수 | 1 + 분기점(아래) |
| `function_statements` | 함수 | 함수 몸체의 문장 노드(독스트링 제외) |

분기점: `if`/`elif`·삼항·`for`·`while`·`except`·불리언 연산자 피연산자(n개 → n−1)·
컴프리헨션의 `for`/`if`·`match` 의 각 `case`(무조건 `case _` 제외). `with` 는 세지 않는다 —
정상 흐름이 갈리지 않는다. `assert`·루프/`try` 의 `else` 도 세지 않는다.

중첩 함수는 **자기 단위**로 따로 잰다. 바깥 함수에는 그 `def` 문장 1개만 남고 몸체는 이중
계산하지 않는다. `lambda` 는 이름이 없어 바깥 함수에 접힌다. JS 의 익명 함수(콜백)도 같은
이유로 소유 함수에 접힌다 — 안정적인 이름이 없는 것은 원장 키가 될 수 없고, 쪼개려면 이름을
주는 것이 곧 처방이다. 예외: 첫 인수가 문자열 리터럴인 호출의 익명 콜백(`test("…", () => …)`,
`addEventListener("click", …)`)은 `callee("…")` 이름의 단위가 된다. JS 측 규칙의 정본은
`scripts/complexity_axes.mjs` 다.

같은 식별자가 두 번 나오면(프로퍼티 getter/setter 등) 축마다 **최댓값**을 쓴다.

## 범위와 등급

`production` 등급과 느슨한 `test` 등급 둘이다. `tests/**`·루트 `conftest.py` 와
`frontend/src/selftest/**`(실앱을 몰아 보는 selftest 하니스·probe — 제품 거동이 아니라 검증
코드)가 `test` 등급이고, 나머지(`src/`·`scripts/`·`packaging/`·`frontend/`)는 `production`
등급이다. `scripts/` 는 계약 엔진·생성기·CI 도구라 제품과 같은 구조 기준을 받는다.

제외는 `EXCLUDED` 에 사유와 함께 적힌 것뿐이다 — 조용한 제외는 없다.
"""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

METRICS = ("module_statements", "class_methods", "function_complexity", "function_statements")

#: 등급별 상한. **목표 품질 값**이다 — 현재 위반은 원장에 동결되고 리팩터링으로 내려간다.
CEILINGS: dict[str, dict[str, int]] = {
    "production": {
        "module_statements": 300,
        "class_methods": 20,
        "function_complexity": 10,
        "function_statements": 50,
    },
    "test": {
        "module_statements": 800,
        "class_methods": 60,
        "function_complexity": 20,
        "function_statements": 120,
    },
}

PY_ROOTS = ("src", "tests", "scripts", "packaging")
JS_ROOTS = ("frontend", "tests/js", "scripts")
JS_SUFFIXES = (".js", ".mjs", ".ts", ".tsx")
TEST_TIER_PREFIXES = ("tests/", "frontend/src/selftest/")
TEST_TIER_FILES = ("conftest.py",)

#: 명시 제외 — 접두 → 사유. 여기 없는 코드는 전부 잰다.
EXCLUDED: dict[str, str] = {
    "frontend/vendor/": "제3자 번들(rhwp editor) — 구조를 우리가 소유하지 않는다",
    "tests/js/fixtures/": "다른 게이트의 음성 입력 표본 — 일부러 기형이고 코드로 유지하지 않는다",
    "tests/fixtures/": "테스트 입력 자료 — 코드로 유지하지 않는다",
    "tests/corpus/": "테스트 입력 자료 — 코드로 유지하지 않는다",
}
_SKIP_DIRS = frozenset({"__pycache__", "node_modules", ".pytest_cache"})

_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_PLAIN_BRANCHES = (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler)


class MeasureError(RuntimeError):
    """측정을 못 했다 — 예산 판정의 근거가 없으므로 통과가 아니라 실패다."""


@dataclass
class Unit:
    """측정 단위 하나. `qual` 이 빈 문자열이면 모듈이다."""

    path: str
    qual: str
    kind: str
    metrics: dict[str, int]
    detail: list = field(default_factory=list)

    @property
    def ident(self) -> str:
        return f"{self.path}::{self.qual}" if self.qual else self.path

    @property
    def tier(self) -> str:
        return tier_of(self.path)


def tier_of(rel: str) -> str:
    if rel.startswith(TEST_TIER_PREFIXES) or rel in TEST_TIER_FILES:
        return "test"
    return "production"


def excluded(rel: str) -> bool:
    return rel.startswith(tuple(EXCLUDED))


# ───────────────────────── 파일 발견 ─────────────────────────


def _walk(root: Path, base: str, suffixes: tuple[str, ...]) -> list[str]:
    start = root / base
    if not start.is_dir():
        return []
    found = []
    for path in start.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if path.suffix not in suffixes or not path.is_file():
            continue
        if _SKIP_DIRS.intersection(path.relative_to(root).parts) or excluded(rel):
            continue
        found.append(rel)
    return found


def discover(root: Path) -> dict[str, list[str]]:
    """언어별 측정 대상(저장소 상대 POSIX 경로, 정렬)."""
    python = {p.name for p in root.glob("*.py")}
    js = {p.name for p in root.iterdir() if p.is_file() and p.suffix in JS_SUFFIXES}
    for base in PY_ROOTS:
        python.update(_walk(root, base, (".py",)))
    for base in JS_ROOTS:
        js.update(_walk(root, base, JS_SUFFIXES))
    return {"python": sorted(python), "js": sorted(js)}


# ───────────────────────── Python ─────────────────────────


def _docstrings(tree: ast.Module) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, *_SCOPE)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                ids.add(id(first))
    return ids


def _branch_weight(node: ast.AST) -> int:
    if isinstance(node, _PLAIN_BRANCHES):
        return 1
    if isinstance(node, ast.BoolOp):
        return len(node.values) - 1
    if isinstance(node, ast.comprehension):
        return 1 + len(node.ifs)
    if isinstance(node, ast.match_case):
        wildcard = isinstance(node.pattern, ast.MatchAs) and node.pattern.pattern is None
        return 0 if wildcard and node.guard is None else 1
    return 0


def _own(nodes: list[ast.stmt]):
    """중첩 def/class 의 몸체로 내려가지 않는 순회 — 그 문장 자체는 낸다."""
    stack: list[ast.AST] = list(nodes)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPE):
            stack.extend(ast.iter_child_nodes(node))


def _tally(nodes: list[ast.stmt], docs: set[int]) -> tuple[int, int]:
    statements = branches = 0
    for node in _own(nodes):
        if isinstance(node, ast.stmt) and id(node) not in docs:
            statements += 1
        branches += _branch_weight(node)
    return statements, branches


def _function_unit(path: str, qual: str, node: ast.FunctionDef | ast.AsyncFunctionDef,
                   docs: set[int]) -> Unit:
    statements, branches = _tally(node.body, docs)
    blocks = []
    for child in node.body:
        if id(child) in docs:
            continue
        stmts, weight = _tally([child], docs)
        blocks.append([child.lineno, type(child).__name__.lower(), stmts, weight])
    metrics = {"function_complexity": 1 + branches, "function_statements": statements}
    return Unit(path, qual, "function", metrics, blocks)


def _class_unit(path: str, qual: str, node: ast.ClassDef) -> Unit:
    methods = [child.name for child in node.body if isinstance(child, _FUNC)]
    return Unit(path, qual, "class", {"class_methods": len(methods)}, methods)


def _scan(node: ast.AST, path: str, prefix: str, docs: set[int], sink: list[Unit]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            sink.append(_class_unit(path, prefix + child.name, child))
            _scan(child, path, f"{prefix}{child.name}.", docs, sink)
        elif isinstance(child, _FUNC):
            sink.append(_function_unit(path, prefix + child.name, child, docs))
            _scan(child, path, f"{prefix}{child.name}.", docs, sink)
        else:
            _scan(child, path, prefix, docs, sink)


def _top_label(node: ast.stmt) -> str:
    if isinstance(node, _SCOPE):
        return node.name
    return f"{type(node).__name__.lower()}@L{node.lineno}"


def measure_python_source(path: str, source: str) -> list[Unit]:
    """소스 한 편의 단위 목록. 구문 오류는 숨기지 않고 `MeasureError` 다."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        raise MeasureError(f"{path}: 파싱 실패 — 예산을 잴 수 없습니다: {error}") from error
    docs = _docstrings(tree)
    total = sum(1 for node in ast.walk(tree) if isinstance(node, ast.stmt) and id(node) not in docs)
    tops = []
    for child in tree.body:
        if id(child) not in docs:
            size = sum(1 for n in ast.walk(child) if isinstance(n, ast.stmt) and id(n) not in docs)
            tops.append([_top_label(child), size])
    units = [Unit(path, "", "module", {"module_statements": total}, tops)]
    _scan(tree, path, "", docs, units)
    return units


# ───────────────────────── JS/TS (oxc via node) ─────────────────────────

#: 측정기는 `node_modules` 를 해소하려고 저장소 트리 안에 산다 — 재는 파일의 뿌리와 무관하다.
JS_MEASURER = Path(__file__).with_name("complexity_axes.mjs")


def measure_js_files(root: Path, rels: list[str], *, node: str | None = None) -> list[Unit]:
    """`root` 기준 `rels` 를 `complexity_axes.mjs` 로 잰다.

    Node·vite 부재는 스킵이 아니라 `MeasureError` 다.
    """
    if not rels:
        return []
    executable = shutil.which(node or "node")
    if executable is None:
        raise MeasureError(
            "Node 를 찾지 못했습니다 — 프런트 복잡도 예산은 oxc(vite parseAst)로 잽니다. "
            "Node 와 `npm ci` 는 이 저장소의 빌드 전제조건이므로 부재는 스킵 사유가 아닙니다."
        )
    payload = json.dumps({"root": str(root), "files": rels}, ensure_ascii=False)
    done = subprocess.run(
        [executable, str(JS_MEASURER)], input=payload.encode("utf-8"),
        capture_output=True, cwd=JS_MEASURER.parent, check=False,
    )
    if done.returncode != 0:
        raise MeasureError(f"JS 측정기 실패(exit {done.returncode}):\n"
                           + done.stderr.decode("utf-8", "replace"))
    return [Unit(**row) for row in json.loads(done.stdout.decode("utf-8"))]


# ───────────────────────── 집계 ─────────────────────────


def merge_units(units: list[Unit]) -> dict[str, Unit]:
    """식별자별 하나로 — 중복(getter/setter 등)은 축마다 최댓값."""
    merged: dict[str, Unit] = {}
    for unit in units:
        seen = merged.get(unit.ident)
        if seen is None:
            merged[unit.ident] = unit
            continue
        for metric, value in unit.metrics.items():
            if value > seen.metrics.get(metric, -1):
                seen.metrics[metric] = value
                seen.detail = unit.detail
    return merged


def measure_repository(root: Path, *, node: str | None = None) -> tuple[dict[str, Unit], dict]:
    """저장소 전체 측정 — (식별자 → 단위, 발견 파일 목록)."""
    files = discover(root)
    units: list[Unit] = []
    for rel in files["python"]:
        units.extend(measure_python_source(rel, (root / rel).read_text(encoding="utf-8-sig")))
    units.extend(measure_js_files(root, files["js"], node=node))
    return merge_units(units), files
