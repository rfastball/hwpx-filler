#!/usr/bin/env python3
"""사용자 문안 census — 화면에 서는 **문장**을 세고 allowlist 와 대조한다.

새 문장은 기본 0 이다(`docs/COPY_STYLE_GUIDE.md` §1·§8). 이 스크립트는 문안 생산자
(링1 상태 모델 · 링2 컨트롤러 · 프런트 화면 · index.html)에서 종결어미로 끝나는 문자열을
모아 `docs/ui_copy_census.toml` 과 다중집합으로 맞춘다. 문장이 늘면 게이트가 빨강이 되고,
정말 남겨야 하는 문장만 PR 사유와 함께 allowlist 에 오른다.

    python scripts/ui_copy_census.py            # 요약 출력(쓰지 않음)
    python scripts/ui_copy_census.py --check    # allowlist 대조(어긋나면 non-zero)
    python scripts/ui_copy_census.py --write    # allowlist 재생성

낭독 패턴(`NARRATION_PATTERNS`)은 `docs/COPY_STYLE_GUIDE.md` §8 의 구현이다 — 정본은 그
문서고 여기는 그것을 기계가 읽는 형태로 옮긴 것이다. 패턴에 걸리는 **기존** 문장만
`legacy = true` 로 등재되고, 그 수는 늘지 않는다(줄이기만).

dev/CI 전용이며 앱 실행 시 돌지 않는다. stdlib 만 쓴다.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "docs" / "ui_copy_census.toml"

# ── 스캔 범위 — 사용자 문안 생산자만 ────────────────────────────────────────────────
#: 링1 상태 모델과 링2 컨트롤러. 도메인(`domain/`·`hwpxcore`)은 문안을 짓지 않는다.
PY_GLOBS = (
    "src/hwpxfiller/gui/**/*.py",
    "src/hwpxfiller/webapp/**/*.py",
    # 데이터 풀 VM 은 `application/` 에 살지만 링1 판정·문안(고르기 거절 사유·빈 목록 안내)을
    # 짓는다 — 고르기 열 통합(PR #995)에서 그 문장들이 `webapp/screen_pool.py` 에서 여기로
    # 내려왔다. 범위 밖으로 흘리면 census 가 그 문장들을 「사라졌다」고만 말한다.
    "src/hwpxfiller/application/dataset_pool.py",
)
#: 프런트 source. `frontend/src/selftest/**` 는 프로브·픽스처라 제품 문안이 아니다.
JS_GLOBS = ("frontend/src/**/*.ts", "frontend/src/**/*.tsx", "frontend/src/**/*.js",
            "frontend/js/*.js")
JS_EXCLUDE_PREFIXES = ("frontend/src/selftest/",)
#: 정적 문안의 다른 단일 출처(CLAUDE.md 「단일 출처 목록」).
HTML_FILES = ("frontend/index.html",)

#: 태그 속성 중 사용자에게 읽히는 것.
HTML_TEXT_ATTRS = ("title", "placeholder", "aria-label", "alt")

# ── 문장 판정 ───────────────────────────────────────────────────────────────────────
#: 한국어 종결어미. `입니다·습니다·합니다·됩니다` 는 전부 `니다` 로 잡힌다.
SENTENCE_RE = re.compile(r"(니다|세요|십시오|까요|네요|군요)(?=[.!?…)\]'\"」』]|\s|$)")

#: 낭독 패턴 — 정본은 `docs/COPY_STYLE_GUIDE.md` §8. (번호, 정규식, 사유).
NARRATION_PATTERNS: tuple[tuple[int, re.Pattern[str], str], ...] = (
    (1, re.compile(r"해야 .{0,20}할 수 있습니다"),
     "전제 조건 낭독. 차단은 동작(비활성 + 사유)이 한다"),
    (2, re.compile(r"불러왔습니다|가져왔습니다|복원했습니다"),
     "정상 경로 완료 낭독. 화면에 결과가 이미 보인다"),
    (3, re.compile(r"^.{0,40}(입니다|습니다)\s*·\s"),
     "문장 뒤에 `·` 로 수치를 이어 붙인 혼합형. 수치만 남긴다"),
    (4, re.compile(r"실제 .{0,10}입니다"),
     "시스템 원칙 낭독"),
    (5, re.compile(r"을\(를\) 편집합니다|을\(를\) 봅니다|화면입니다"),
     "현재 모드 낭독. 제목이 이미 말한다"),
)


def normalize(text: str) -> str:
    """공백 연속을 한 칸으로 줄이고 양끝을 다듬는다."""
    return re.sub(r"\s+", " ", text).strip()


def is_sentence(text: str) -> bool:
    return bool(SENTENCE_RE.search(text))


def narration_hits(text: str) -> list[tuple[int, str]]:
    """문장이 걸린 낭독 패턴의 (번호, 사유) 목록."""
    return [(number, why) for number, pattern, why in NARRATION_PATTERNS if pattern.search(text)]


# ── Python ─────────────────────────────────────────────────────────────────────────
def _docstring_nodes(tree: ast.AST) -> set[int]:
    """module/class/def 본문 첫 문자열 리터럴(= docstring) 노드 id 집합."""
    marked: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            marked.add(id(first.value))
    return marked


def _joined_text(node: ast.JoinedStr) -> str:
    """f-string 을 하나의 텍스트로. 치환 자리는 `{}` 로 접는다."""
    parts: list[str] = []
    for piece in node.values:
        if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
            parts.append(piece.value)
        else:
            parts.append("{}")
    return "".join(parts)


def scan_python(text: str) -> list[tuple[int, str]]:
    """(줄번호, 정규화 텍스트) — docstring 은 제외, f-string 은 한 덩어리."""
    tree = ast.parse(text)
    skip = _docstring_nodes(tree)
    found: list[tuple[int, str]] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.JoinedStr):
            found.append((node.lineno, normalize(_joined_text(node))))
            return  # 조각을 다시 세지 않는다
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in skip:
                found.append((node.lineno, normalize(node.value)))
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return found


# ── TS/JS ──────────────────────────────────────────────────────────────────────────
_JS_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0"}


def scan_js(text: str) -> list[tuple[int, str]]:
    """따옴표·템플릿 리터럴만 뽑는 작은 상태기계. 주석은 건너뛴다."""
    found: list[tuple[int, str]] = []
    index = 0
    size = len(text)
    line = 1
    while index < size:
        char = text[index]
        if char == "\n":
            line += 1
            index += 1
            continue
        if char == "/" and index + 1 < size and text[index + 1] == "/":
            while index < size and text[index] != "\n":
                index += 1
            continue
        if char == "/" and index + 1 < size and text[index + 1] == "*":
            index += 2
            while index + 1 < size and not (text[index] == "*" and text[index + 1] == "/"):
                if text[index] == "\n":
                    line += 1
                index += 1
            index += 2
            continue
        if char in ("'", '"', "`"):
            start = line
            template = char == "`"
            index += 1
            buffer: list[str] = []
            while index < size:
                current = text[index]
                if current == "\\":
                    if index + 1 < size:
                        following = text[index + 1]
                        if following == "\n":
                            line += 1
                            buffer.append("\n")
                        else:
                            buffer.append(_JS_ESCAPES.get(following, following))
                        index += 2
                        continue
                    index += 1
                    continue
                if current == char:
                    index += 1
                    break
                if template and current == "$" and index + 1 < size and text[index + 1] == "{":
                    depth = 1
                    index += 2
                    while index < size and depth:
                        if text[index] == "\n":
                            line += 1
                        elif text[index] == "{":
                            depth += 1
                        elif text[index] == "}":
                            depth -= 1
                        index += 1
                    buffer.append("{}")
                    continue
                if current == "\n":
                    line += 1
                    if not template:
                        break  # 종료되지 않은 따옴표 — 줄에서 끊는다
                buffer.append(current)
                index += 1
            found.append((start, normalize("".join(buffer))))
            continue
        index += 1
    return found


# ── HTML ───────────────────────────────────────────────────────────────────────────
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_RAW = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.DOTALL | re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]*>", re.DOTALL)
_HTML_ATTR = re.compile(
    r"\b(" + "|".join(HTML_TEXT_ATTRS) + r")\s*=\s*(\"([^\"]*)\"|'([^']*)')",
    re.IGNORECASE,
)


def _blank_out(match: re.Match[str]) -> str:
    """줄번호를 보존하며 지운다 — 개행만 남긴다."""
    return "\n" * match.group(0).count("\n")


def scan_html(text: str) -> list[tuple[int, str]]:
    """태그 사이 텍스트 노드와 읽히는 속성값."""
    stripped = _HTML_RAW.sub(_blank_out, _HTML_COMMENT.sub(_blank_out, text))
    found: list[tuple[int, str]] = []

    def line_of(offset: int) -> int:
        return stripped.count("\n", 0, offset) + 1

    cursor = 0
    for tag in _HTML_TAG.finditer(stripped):
        if tag.start() > cursor:
            found.append((line_of(cursor), normalize(stripped[cursor : tag.start()])))
        for attr in _HTML_ATTR.finditer(tag.group(0)):
            value = attr.group(3) if attr.group(3) is not None else attr.group(4)
            found.append((line_of(tag.start()), normalize(value or "")))
        cursor = tag.end()
    if cursor < len(stripped):
        found.append((line_of(cursor), normalize(stripped[cursor:])))
    return found


# ── census ─────────────────────────────────────────────────────────────────────────
def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _sorted_files(globs: tuple[str, ...]) -> list[Path]:
    seen: dict[str, Path] = {}
    for pattern in globs:
        for path in ROOT.glob(pattern):
            if path.is_file():
                seen[_relative(path)] = path
    return [seen[key] for key in sorted(seen)]


def census() -> list[tuple[str, int, str]]:
    """(파일, 줄, 문장) 목록 — 파일·줄 순."""
    rows: list[tuple[str, int, str]] = []
    for path in _sorted_files(PY_GLOBS):
        for line, text in scan_python(path.read_text(encoding="utf-8")):
            if is_sentence(text):
                rows.append((_relative(path), line, text))
    for path in _sorted_files(JS_GLOBS):
        name = _relative(path)
        if name.startswith(JS_EXCLUDE_PREFIXES):
            continue
        for line, text in scan_js(path.read_text(encoding="utf-8")):
            if is_sentence(text):
                rows.append((name, line, text))
    for name in HTML_FILES:
        path = ROOT / name
        if not path.is_file():
            continue
        for line, text in scan_html(path.read_text(encoding="utf-8")):
            if is_sentence(text):
                rows.append((name, line, text))
    return rows


def census_counts(rows: list[tuple[str, int, str]] | None = None) -> Counter[tuple[str, str]]:
    """(파일, 문장) 다중집합."""
    return Counter((file, text) for file, _line, text in (rows if rows is not None else census()))


# ── allowlist ──────────────────────────────────────────────────────────────────────
def load_allowlist(path: Path = ALLOWLIST) -> list[dict]:
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return list(data.get("sentence", []))


def allowlist_counts(entries: list[dict]) -> Counter[tuple[str, str]]:
    return Counter((entry["file"], entry["text"]) for entry in entries)


_TOML_ESCAPES = {"\\": "\\\\", '"': '\\"', "\b": "\\b", "\f": "\\f",
                 "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _toml_string(value: str) -> str:
    out = ["\""]
    for char in value:
        if char in _TOML_ESCAPES:
            out.append(_TOML_ESCAPES[char])
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            out.append(f"\\u{ord(char):04X}")
        else:
            out.append(char)
    out.append("\"")
    return "".join(out)


HEADER = """\
# 사용자 문안 census. 생성: uv run python scripts/ui_copy_census.py --write
# 검사: --check (tests/repo_contract/test_ui_copy_census.py 가 같은 것을 본다)
# 규범: docs/COPY_STYLE_GUIDE.md §1·§2·§8. 새 문장은 기본 0 이고, 등재는 사유가 PR 에 서야 한다.
"""


def render_allowlist(counts: Counter[tuple[str, str]], legacy_keys: set[tuple[str, str]]) -> str:
    lines = [HEADER]
    for file, text in sorted(counts):
        for _ in range(counts[(file, text)]):
            lines.append("\n[[sentence]]\n")
            lines.append(f"file = {_toml_string(file)}\n")
            lines.append(f"text = {_toml_string(text)}\n")
            if (file, text) in legacy_keys:
                lines.append("legacy = true\n")
    return "".join(lines)


def write_allowlist(path: Path = ALLOWLIST) -> tuple[int, int, list[tuple[str, str]]]:
    """allowlist 재생성. (총수, legacy 수, 낭독인데 legacy 를 못 받은 새 항목) 반환."""
    previous = load_allowlist(path)
    bootstrap = not path.is_file()
    known = {(entry["file"], entry["text"]) for entry in previous}
    counts = census_counts()
    legacy_keys: set[tuple[str, str]] = set()
    unmarked: list[tuple[str, str]] = []
    for key in counts:
        if not narration_hits(key[1]):
            continue
        if bootstrap or key in known:
            legacy_keys.add(key)
        else:
            unmarked.append(key)
    path.write_text(render_allowlist(counts, legacy_keys), encoding="utf-8", newline="\n")
    total = sum(counts.values())
    legacy_total = sum(counts[key] for key in legacy_keys)
    return total, legacy_total, sorted(unmarked)


ADVICE = (
    "새 문장은 기본 0 이다(COPY_STYLE_GUIDE §1·§8). 걷는 것이 먼저고, 정말 남겨야 하면 "
    "`docs/ui_copy_census.toml` 에 등재하고 PR 에 사유를 쓴다. 지운 문장은 allowlist 에서도 지운다."
)


def diff_report(path: Path = ALLOWLIST) -> list[str]:
    """실 스캔과 allowlist 의 차이를 사람이 읽는 줄로. 빈 목록이면 일치."""
    rows = census()
    actual = census_counts(rows)
    expected = allowlist_counts(load_allowlist(path))
    added = actual - expected
    removed = expected - actual
    if not added and not removed:
        return []
    where: dict[tuple[str, str], list[int]] = {}
    for file, line, text in rows:
        where.setdefault((file, text), []).append(line)
    report: list[str] = []
    if added:
        report.append(f"추가된 문장 {sum(added.values())}건:")
        for file, text in sorted(added):
            for line in sorted(where.get((file, text), []))[: added[(file, text)]]:
                report.append(f"  + {file}:{line}  {text}")
    if removed:
        report.append(f"사라진 문장 {sum(removed.values())}건:")
        for file, text in sorted(removed):
            for _ in range(removed[(file, text)]):
                report.append(f"  - {file}  {text}")
    report.append("")
    report.append(ADVICE)
    return report


def _summary(counts: Counter[tuple[str, str]]) -> str:
    trees = Counter()
    for (file, _text), number in counts.items():
        if file.startswith("frontend/index.html"):
            tree = "html"
        elif file.startswith("frontend/"):
            tree = "frontend"
        elif file.startswith("src/hwpxfiller/gui/"):
            tree = "gui"
        elif file.startswith("src/hwpxfiller/webapp/"):
            tree = "webapp"
        else:
            tree = "기타"
        trees[tree] += number
    parts = " · ".join(f"{name} {trees[name]}" for name in sorted(trees))
    return f"문장 {sum(counts.values())}건 ({parts})"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="사용자 문안 census")
    parser.add_argument("--check", action="store_true", help="allowlist 대조(쓰지 않음)")
    parser.add_argument("--write", action="store_true", help="allowlist 재생성")
    args = parser.parse_args(argv)
    if args.check and args.write:
        parser.error("--check 와 --write 는 함께 쓸 수 없다")
    if args.write:
        total, legacy_total, unmarked = write_allowlist()
        for file, text in unmarked:
            hits = ", ".join(f"#{number} {why}" for number, why in narration_hits(text))
            print(f"경고: 새 문장이 낭독 패턴에 걸린다 — {file}: {text}\n        {hits}",
                  file=sys.stderr)
        print(f"재생성 완료: {_relative(ALLOWLIST)} — {total}건 (legacy {legacy_total})")
        return 0
    if args.check:
        problems = diff_report()
        if problems:
            print("사용자 문안 census 불일치:\n" + "\n".join(problems), file=sys.stderr)
            return 1
        print(f"census 일치 — {_summary(census_counts())}")
        return 0
    print(_summary(census_counts()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
