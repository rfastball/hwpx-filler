#!/usr/bin/env python3
"""Generate code-derived references; check document inventory, links and review inputs.

stdlib only. --write never acknowledges prose review. --review names exactly one
human-owned document and records its normalized body and source-set fingerprints.
These fingerprints detect drift; they are not a proof of semantic correctness.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
import re
import sys
import tomllib
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/manifest.toml"
INDEX = "docs/README.md"
REFERENCE = "docs/reference/runtime.md"
KINDS = {"current", "generated", "evidence", "research", "machine"}
FIELDS = {"path", "kind", "role", "max_lines", "sources", "tests", "source_sha256", "body_sha256"}


class ContractError(ValueError):
    """An input is missing or is outside the explicitly supported contract."""


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def relative(root: Path, name: str) -> Path:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ContractError(f"unsafe relative path: {name}")
    result = root / path
    if not result.resolve().is_relative_to(root.resolve()):
        raise ContractError(f"path leaves repository: {name}")
    return result


def documents(root: Path) -> list[dict]:
    value = tomllib.loads(read(root / MANIFEST))
    if set(value) != {"schema", "document"} or value["schema"] != "docs-contract/v1":
        raise ContractError("invalid documentation manifest schema")
    records = value["document"]
    if not isinstance(records, list) or not records:
        raise ContractError("empty document inventory")
    paths: set[str] = set()
    roles: set[str] = set()
    for item in records:
        if not isinstance(item, dict) or set(item) - FIELDS:
            raise ContractError("unknown document fields")
        for field in ("path", "kind", "role"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ContractError(f"missing/invalid document {field}")
        name = item["path"]
        relative(root, name)
        if name in paths or item["role"] in roles:
            raise ContractError(f"duplicate document path/role: {name}")
        paths.add(name)
        roles.add(item["role"])
        if item["kind"] not in KINDS:
            raise ContractError(f"invalid document kind: {name}")
        if type(item.get("max_lines")) is not int or item["max_lines"] <= 0:
            raise ContractError(f"invalid line budget: {name}")
        for field in ("sources", "tests"):
            values = item.get(field, [])
            if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
                raise ContractError(f"invalid {field}: {name}")
            if len(values) != len(set(values)):
                raise ContractError(f"duplicate {field}: {name}")
        if item["kind"] == "current":
            if not item.get("sources") or not item.get("tests"):
                raise ContractError(f"current document needs sources and tests: {name}")
            for field in ("source_sha256", "body_sha256"):
                if not re.fullmatch(r"[a-f0-9]{64}", item.get(field, "")):
                    raise ContractError(f"invalid {field}: {name}")
        elif {"source_sha256", "body_sha256"} & set(item):
            raise ContractError(f"only current prose has review fingerprints: {name}")
    return records


def source_paths(root: Path, item: dict) -> list[Path]:
    paths: set[Path] = set()
    for pattern in item.get("sources", []):
        relative(root, pattern)
        hits = [p for p in root.glob(pattern) if p.is_file()]
        if not hits:
            raise ContractError(f"empty source glob: {item['path']}: {pattern}")
        for p in hits:
            relative(root, p.relative_to(root).as_posix())
            paths.add(p)
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def source_digest(root: Path, item: dict) -> str:
    digest = hashlib.sha256()
    # Tests are review inputs too. Renames and removals cannot disappear silently.
    paths = set(source_paths(root, item))
    for name in item.get("tests", []):
        p = relative(root, name)
        if not p.is_file() or not name.startswith("tests/"):
            raise ContractError(f"missing/invalid evidence test: {item['path']}: {name}")
        paths.add(p)
    for p in sorted(paths, key=lambda p: p.relative_to(root).as_posix()):
        digest.update(p.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(read(p).encode("utf-8") + b"\0")
    return digest.hexdigest()


def body_digest(root: Path, name: str) -> str:
    return hashlib.sha256(read(relative(root, name)).encode("utf-8")).hexdigest()


def _mapping(node: ast.AST, bindings: dict[str, ast.AST]) -> dict[str, ast.AST]:
    if isinstance(node, ast.Name):
        if node.id not in bindings:
            raise ContractError(f"unknown registry expansion: {node.id}")
        node = bindings[node.id]
    if not isinstance(node, ast.Dict):
        raise ContractError("registry must use literal dictionaries and named expansions")
    out: dict[str, ast.AST] = {}
    for key, value in zip(node.keys, node.values, strict=True):
        if key is None:
            out.update(_mapping(value, bindings))
        elif isinstance(key, ast.Constant) and isinstance(key.value, str):
            out[key.value] = value
        else:
            raise ContractError("registry key must be a string literal")
    return out


def registry(root: Path) -> dict[str, dict[str, tuple[str, str]]]:
    tree = ast.parse(read(root / "src/hwpxfiller/webapp/action_registry.py"))
    bindings: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            bindings[node.target.id] = node.value
    if "_REGISTRY" not in bindings:
        raise ContractError("missing _REGISTRY")
    out = {}
    for screen, actions in _mapping(bindings["_REGISTRY"], bindings).items():
        out[screen] = {}
        for name, call in _mapping(actions, bindings).items():
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                raise ContractError(f"unrecognized action schema: {screen}.{name}")
            if call.func.id != "_schema" or len(call.args) > 2:
                raise ContractError(f"unrecognized action schema: {screen}.{name}")
            values = {"required": "", "optional": ""}
            for field, arg in zip(values, call.args, strict=False):
                values[field] = ast.literal_eval(arg)
            for kw in call.keywords:
                if kw.arg not in values:
                    raise ContractError(f"unrecognized schema keyword: {kw.arg}")
                values[kw.arg] = ast.literal_eval(kw.value)
            if not all(isinstance(v, str) for v in values.values()):
                raise ContractError(f"nonliteral schema: {screen}.{name}")
            out[screen][name] = (values["required"], values["optional"])
    return out


def public_methods(
    root: Path, source: str = "src/hwpxfiller/webapp/app.py", class_name: str = "WebFrontend"
) -> list[tuple[str, str]]:
    tree = ast.parse(read(root / source))
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name), None)
    if cls is None:
        raise ContractError(f"missing {class_name} class")
    out = []
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            out.append((node.name, ast.unparse(node.args).removeprefix("self, ").removeprefix("self")))
    if not out:
        raise ContractError("empty public method surface")
    return sorted(out)


def workflow_jobs(root: Path) -> tuple[list[str], list[str]]:
    # Deliberately supports the repository's explicit job/needs YAML representation.
    # Semantic topology is independently tested by test_quality_workflow.py.
    text = read(root / ".github/workflows/quality.yml")
    if "\njobs:\n" not in text:
        raise ContractError("missing explicit workflow jobs mapping")
    jobs_text = text.split("\njobs:\n", 1)[1]
    keys = re.findall(r"(?m)^  (\S[^\n]*):[^\n]*$", jobs_text)
    if not keys or any(not re.fullmatch(r"[A-Za-z_][\w-]*", k) for k in keys):
        raise ContractError("unsupported workflow job key syntax")
    if "quality-gate" not in keys:
        raise ContractError("missing quality-gate job")
    gate = jobs_text.split("  quality-gate:\n", 1)[1]
    gate = re.split(r"\n  [A-Za-z_][\w-]*:", gate, maxsplit=1)[0]
    match = re.search(r"(?m)^    needs:\s*\n((?:      - [\w-]+\n)+)", gate)
    if not match:
        raise ContractError("quality-gate needs must explicitly enumerate jobs")
    needs = re.findall(r"- ([\w-]+)", match.group(1))
    return keys, needs


def render_reference(root: Path) -> str:
    project = tomllib.loads(read(root / "pyproject.toml"))["project"]
    package = json.loads(read(root / "package.json"))
    rows = [
        ("제품 버전", project["version"], "pyproject.toml"),
        ("Python 요구 범위", project["requires-python"], "pyproject.toml"),
        ("Python pin", read(root / ".python-version").strip(), ".python-version"),
        ("Node pin", read(root / ".node-version").strip(), ".node-version"),
        ("Node engine", package["engines"]["node"], "package.json"),
        ("npm engine", package["engines"]["npm"], "package.json"),
        ("package manager", package["packageManager"], "package.json"),
    ]
    lines = ["# 코드에서 생성한 런타임 참조", "",
             "> 생성물: `uv run python scripts/docs_contract.py --write`. 직접 편집하지 않는다.",
             "> 선언·등록 목록이다. 채널이나 메서드가 있다는 사실은 사용자 기능의 노출을 뜻하지 않는다.",
             "", "## 환경 선언", "", "| 항목 | 선언 | 원천 |", "|---|---|---|"]
    lines += [f"| {label} | `{value}` | [{source}](../../{source}) |" for label, value, source in rows]
    lines += ["", "## 진입점", "", "| 종류 | 명령 | Python 대상 |", "|---|---|---|"]
    for kind in ("scripts", "gui-scripts"):
        for name, target in sorted(project.get(kind, {}).items()):
            lines.append(f"| {kind} | `{name}` | `{target}` |")
    jobs, needs = workflow_jobs(root)
    lines += ["", "## 품질 CI", "",
              "원천: [quality.yml](../../.github/workflows/quality.yml). 실제 설정의 등록 목록이다.",
              "", "- Jobs: " + ", ".join(f"`{j}`" for j in jobs),
              "- `quality-gate.needs`: " + ", ".join(f"`{j}`" for j in needs),
              "", "## WebFrontend 공개 메서드", "",
              "원천: [app.py](../../src/hwpxfiller/webapp/app.py)의 클래스 AST.",
              "host 내부 소비용 메서드도 포함한다. 실제 웹 호출은 [bridge.js](../../frontend/js/bridge.js)와",
              "독립 브리지 계약 테스트로 대조한다.", "", "| 메서드 | 인자 |", "|---|---|"]
    for name, args in public_methods(root):
        lines.append(f"| `{name}` | `{args.replace('|', '&#124;')}` |")
    lines += ["", "## Selftest 전용 공개 메서드", "",
              "원천: [selftest_api.py](../../src/hwpxfiller/webapp/selftest_api.py)의 SelftestHostFacade.",
              "제품 WebFrontend의 메서드가 아니다. selftest 권한·수명 검사를 거치는 별도 경계다.",
              "", "| 메서드 | 인자 |", "|---|---|"]
    for name, args in public_methods(root, "src/hwpxfiller/webapp/selftest_api.py", "SelftestHostFacade"):
        lines.append(f"| `{name}` | `{args.replace('|', '&#124;')}` |")
    lines += ["", "## Dispatch registry", "",
              "원천: [action_registry.py](../../src/hwpxfiller/webapp/action_registry.py).",
              "공유 dictionary expansion을 포함한다. 직접 host 호출의 payload 검증은 이 표 밖이다."]
    for screen, actions in sorted(registry(root).items()):
        lines += ["", f"### {screen}", "", "| 액션 | 필수 키 | 선택 키 |", "|---|---|---|"]
        for action, (required, optional) in sorted(actions.items()):
            fmt = lambda value: ", ".join(f"`{k}`" for k in value.split()) or "—"
            lines.append(f"| `{action}` | {fmt(required)} | {fmt(optional)} |")
    return "\n".join(lines) + "\n"


def render_index(records: list[dict]) -> str:
    labels = {"current": "현재 계약", "generated": "자동 생성 참조", "machine": "기계 판독 정본",
              "evidence": "형식 관측 증거", "research": "연구·제안"}
    lines = ["# 문서 지도", "", "> `manifest.toml`에서 생성한다. 이 파일은 직접 편집하지 않는다.",
             "", "현재 동작은 코드·테스트·빌드 설정이 최종 권위다. 현재 계약을 먼저 읽는다.",
             "변경 이력·완료 보고는 Git, 실행 상태는 GitHub 이슈가 소유한다.",
             "문서의 생성·검토·삭제 절차는 [유지 규칙](MAINTENANCE.md)을 따른다."]
    for kind, label in labels.items():
        lines += ["", f"## {label}", "", "| 문서 | 소유하는 내용 |", "|---|---|"]
        for item in records:
            if item["kind"] == kind and item["path"] != INDEX:
                path = item["path"]
                target = path.removeprefix("docs/") if path.startswith("docs/") else "../" + path
                lines.append(f"| [{Path(path).name}]({target}) | {item['role']} |")
    lines += ["", "증거·연구는 현재 구현의 다른 정본이 아니다. 관측의 맥락과 미래 제안을 구분한다."]
    return "\n".join(lines) + "\n"


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.targets: list[str] = []
        self.anchors: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if not value:
                continue
            if name in {"href", "src"}:
                self.targets.append(value)
            if name == "srcset":
                self.targets.extend(v.strip().split()[0] for v in value.split(",") if v.strip())
            if name == "id" or (tag == "a" and name == "name"):
                self.anchors.add(value)


def without_fences(text: str) -> str:
    lines = []
    fence = ""
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            run = match.group(1)
            if not fence:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = ""
            continue
        if not fence:
            lines.append(line)
    return "\n".join(lines)


def anchors(text: str) -> set[str]:
    text = without_fences(text)
    parser = _Links()
    parser.feed(text)
    out = parser.anchors
    seen: dict[str, int] = {}
    for match in re.finditer(r"(?m)^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", text):
        title = re.sub(r"<[^>]+>", "", html.unescape(match.group(1))).lower()
        # GitHub's useful heading subset: keep letters, numbers, spaces, _ and -.
        slug = "".join(c for c in title if c in " _-" or unicodedata.category(c)[0] in "LNM")
        slug = slug.replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        out.add(slug + (f"-{count}" if count else ""))
    return out


def link_targets(text: str) -> list[str]:
    text = re.sub(r"`+[^`\n]*`+", "", without_fences(text))
    parser = _Links()
    parser.feed(text)
    out = parser.targets
    # Inline destinations support escaped / nested parentheses and optional titles.
    for match in re.finditer(r"!?\[[^\n]*?\]\(", text):
        start = match.end()
        depth, pos = 1, start
        while pos < len(text) and depth:
            char = text[pos]
            if char == "\\":
                pos += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            pos += 1
        if depth:
            raise ContractError("unterminated Markdown link")
        target = text[start:pos - 1].strip()
        if target.startswith("<"):
            out.append(target[1:target.index(">")])
        elif target:
            out.append(target.split()[0])
    refs = dict(re.findall(r"(?m)^ {0,3}\[([^\]]+)\]:\s*<?([^\s>]+)>?", text))
    refs = {key.casefold(): value for key, value in refs.items()}
    out.extend(refs.values())
    for label, ident in re.findall(r"\[([^\]\n]+)\]\[([^\]\n]*)\]", text):
        if (ident or label).casefold() not in refs:
            raise ContractError(f"undefined reference link: {ident or label}")
    return out


def link_problems(root: Path, name: str) -> list[str]:
    path = root / name
    if path.suffix.lower() not in {".md", ".html"}:
        return []
    out = []
    for raw in link_targets(read(path)):
        parts = urlsplit(html.unescape(raw))
        if parts.scheme or parts.netloc:
            continue  # Never use online availability as the deterministic merge gate.
        target_name = unquote(parts.path)
        target = ((root / target_name.lstrip("/")) if target_name.startswith("/")
                  else path.parent / target_name) if target_name else path
        target = target.resolve()
        if not target.is_relative_to(root.resolve()) or not target.exists():
            out.append(f"broken local link: {name}: {raw}")
        elif parts.fragment and target.suffix.lower() in {".md", ".html"}:
            if unquote(parts.fragment) not in anchors(read(target)):
                out.append(f"broken anchor: {name}: {raw}")
    return out


def check(root: Path) -> list[str]:
    problems: list[str] = []
    try:
        records = documents(root)
        generated = {INDEX: render_index(records), REFERENCE: render_reference(root)}
    except (OSError, ValueError, KeyError, SyntaxError, RecursionError) as exc:
        return [str(exc)]
    actual = {p.relative_to(root).as_posix() for p in (root / "docs").rglob("*")
              if p.is_file() and p.suffix.lower() in {".md", ".html", ".toml"}}
    expected = {r["path"] for r in records if r["path"].startswith("docs/")} | {MANIFEST}
    if actual != expected:
        problems.append(f"inventory mismatch: unregistered={sorted(actual - expected)}, "
                        f"missing={sorted(expected - actual)}")
    if {r["path"] for r in records if r["kind"] == "generated"} != set(generated):
        problems.append("generated inventory must exactly match generator outputs")
    for item in records:
        name = item["path"]
        try:
            text = read(relative(root, name))
            if len(text.splitlines()) > item["max_lines"]:
                problems.append(f"line budget exceeded: {name}")
            problems.extend(link_problems(root, name))
            # Validate all declared source and test paths, including machine ledgers.
            observed = source_digest(root, item)
            if item["kind"] == "current":
                if (observed != item["source_sha256"]
                        or body_digest(root, name) != item["body_sha256"]):
                    problems.append(f"review required: {name}")
            if name in generated and text != generated[name]:
                problems.append(f"generated drift: {name}")
        except (OSError, ValueError, KeyError, SyntaxError, RecursionError) as exc:
            problems.append(f"{name}: {exc}")
    return problems


def write_generated(root: Path) -> None:
    records = documents(root)
    outputs = {INDEX: render_index(records), REFERENCE: render_reference(root)}
    for name, text in outputs.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def acknowledge_review(root: Path, name: str) -> None:
    item = next((r for r in documents(root) if r["path"] == name), None)
    if item is None or item["kind"] != "current":
        raise ContractError(f"review must name one current document: {name}")
    values = {"source_sha256": source_digest(root, item), "body_sha256": body_digest(root, name)}
    blocks = read(root / MANIFEST).split("[[document]]")
    found = False
    for i, block in enumerate(blocks[1:], start=1):
        parsed = tomllib.loads(block)
        if parsed.get("path") != name:
            continue
        for field, value in values.items():
            block, count = re.subn(rf'(?m)^{field} = "[a-f0-9]{{64}}"$',
                                  f'{field} = "{value}"', block)
            if count != 1:
                raise ContractError(f"cannot update {name}: {field}")
        blocks[i] = block
        found = True
    if not found:
        raise ContractError(f"missing review record: {name}")
    (root / MANIFEST).write_text("[[document]]".join(blocks), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="check without writing (default)")
    modes.add_argument("--write", action="store_true", help="regenerate references, not prose reviews")
    modes.add_argument("--review", metavar="DOCUMENT", help="acknowledge one manually reviewed document")
    args = parser.parse_args(argv)
    try:
        if args.write:
            write_generated(ROOT)
            print("Generated docs updated; prose review fingerprints unchanged.")
            return 0
        if args.review:
            acknowledge_review(ROOT, args.review)
            print(f"Review fingerprints recorded: {args.review}; semantic review remains human-owned.")
            return 0
        problems = check(ROOT)
    except (OSError, ValueError, KeyError, SyntaxError, RecursionError) as exc:
        problems = [str(exc)]
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("Documentation contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
