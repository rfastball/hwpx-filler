#!/usr/bin/env python3
"""Route documentation by purpose; verify names, ownership, generated facts and review drift.

Uses only the standard library. --write never acknowledges review. --review accepts
one topic (or one small entry document), not a batch. Hashes cannot prove prose true.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tomllib
import unicodedata
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/manifest.toml"
INDEX = "docs/README.md"
REFERENCE = "docs/reference/runtime.md"
PRODUCT = "PRODUCT.md"
# This is the structural policy, not another inventory or routing table. Actual
# topic destinations, source globs and displayed titles belong to the manifest.
CORE = {
    "product": "docs/product.md",
    "architecture": "docs/architecture.md",
    "workflow": "docs/workflow.md",
    "ui-style": "docs/ui-style.md",
    "contributing": "CONTRIBUTING.md",
}
SLOTS = {
    **{role: ("canonical", path) for role, path in CORE.items()},
    "navigation": ("generated", INDEX),
    "runtime-reference": ("generated", REFERENCE),
    "product-adapter": ("generated", PRODUCT),
    "user-entry": ("current", "README.md"),
    "agents-entry": ("current", "AGENTS.md"),
    "claude-entry": ("current", "CLAUDE.md"),
    "ui-gallery": ("current", "docs/reference/ui-gallery.html"),
    "module-rings": ("machine", "tests/contracts/module-rings.toml"),
    "coverage-floors": ("machine", "tests/contracts/package-coverage-floors.toml"),
    "ui-copy-census": ("machine", "tests/contracts/ui-copy-census.toml"),
    "architecture-contract": ("machine", "tests/architecture_contract.toml"),
}
MAX_DOCS = 10
MAX_SUPPORT = 9
MAX_CORE_LINES = 850
MAX_CORE_BYTES = 75000
DOC_SUFFIXES = {".md", ".markdown", ".mdx", ".rst", ".html", ".htm"}
DOCUMENT_FIELDS = {"path", "kind", "role", "title", "max_lines", "sources", "tests",
                   "source_sha256", "body_sha256", "why_separate"}
TOPIC_FIELDS = {"id", "document", "sources", "tests", "source_sha256", "body_sha256"}
MARKER = re.compile(r'^<a id="([a-z][a-z0-9-]*)"></a>\s*$', re.M)


class ContractError(ValueError):
    """An input is missing or violates the documentation contract."""


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


def _strings(item: dict, key: str) -> list[str]:
    values = item.get(key, [])
    if (not isinstance(values, list) or not all(isinstance(v, str) and v for v in values)
            or len(values) != len(set(values))):
        raise ContractError(f"invalid or duplicate {key}: {item}")
    return values


def _review_fields(item: dict) -> None:
    if not _strings(item, "sources") or not _strings(item, "tests"):
        raise ContractError("review unit needs sources and tests")
    for key in ("source_sha256", "body_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}", item.get(key, "")):
            raise ContractError(f"invalid {key}")


def _normal_name(name: str) -> bool:
    stem = Path(name).stem
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", stem):
        return False
    return not any(re.fullmatch(r"(?:[vsu]\d+|(?:19|20)\d{2,6}|final|new|completion|spike)", part)
                   for part in stem.split("-"))


def inventory(root: Path) -> dict:
    value = tomllib.loads(read(root / MANIFEST))
    if set(value) != {"schema", "document", "topic", "support"} or value["schema"] != "docs-contract/v2":
        raise ContractError("invalid documentation manifest schema")
    records, topics, support = (value[k] for k in ("document", "topic", "support"))
    if any(not isinstance(items, list) for items in (records, topics, support)):
        raise ContractError("document/topic/support must be arrays")
    paths: set[str] = set()
    roles: set[str] = set()
    for item in records:
        if not isinstance(item, dict) or set(item) - DOCUMENT_FIELDS:
            raise ContractError("unknown document fields")
        for key in ("path", "kind", "role", "title"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ContractError(f"missing/invalid document {key}")
        name, role, kind = (item[k] for k in ("path", "role", "kind"))
        relative(root, name)
        if name in paths or role in roles:
            raise ContractError(f"duplicate document path/role: {name}")
        paths.add(name)
        roles.add(role)
        if role in SLOTS:
            if (kind, name) != SLOTS[role]:
                raise ContractError(f"role has a fixed kind/path: {role}")
        elif kind in {"evidence", "research"}:
            if (not name.startswith(f"docs/{kind}/") or len(Path(name).parts) != 3
                    or Path(name).suffix != ".md" or not _normal_name(name)
                    or role != f"{kind}-{Path(name).stem}" or not item.get("why_separate", "").strip()):
                raise ContractError(f"invalid independent document name/path/reason: {name}")
        else:
            raise ContractError(f"unknown document role: {role}; use --route before adding a file")
        if type(item.get("max_lines")) is not int or item["max_lines"] <= 0:
            raise ContractError(f"invalid line budget: {name}")
        for key in ("sources", "tests"):
            _strings(item, key)
        if kind == "current":
            _review_fields(item)
        elif {"source_sha256", "body_sha256"} & set(item):
            raise ContractError("only current entry documents have file review hashes")
        if kind == "canonical" and (item.get("sources") or item.get("tests")):
            raise ContractError("canonical review inputs belong to topics")
    if not set(SLOTS) <= roles:
        raise ContractError(f"missing fixed document roles: {sorted(set(SLOTS) - roles)}")
    if sum(p.startswith("docs/") and Path(p).suffix in DOC_SUFFIXES for p in paths) > MAX_DOCS:
        raise ContractError("documentation count budget exceeded")
    seen: set[str] = set()
    owned: set[str] = set()
    for item in topics:
        if not isinstance(item, dict) or set(item) != TOPIC_FIELDS:
            raise ContractError("invalid topic fields")
        name = item.get("id")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", name):
            raise ContractError("invalid topic id")
        if name in seen:
            raise ContractError(f"duplicate topic owner: {name}")
        seen.add(name)
        if item.get("document") not in CORE.values():
            raise ContractError(f"topic must belong to a canonical document: {name}")
        owned.add(item["document"])
        _review_fields(item)
    if owned != set(CORE.values()):
        raise ContractError("each canonical role needs an owned topic")
    if len(support) > MAX_SUPPORT:
        raise ContractError("support document count budget exceeded")
    for item in support:
        if not isinstance(item, dict) or set(item) != {"path", "kind", "reason"}:
            raise ContractError("invalid support record")
        name, kind = item["path"], item["kind"]
        relative(root, name)
        if name in paths or not item["reason"].strip():
            raise ContractError(f"duplicate/invalid support document: {name}")
        paths.add(name)
        allowed = ((kind == "example" and name.startswith("examples/") and Path(name).suffix == ".md")
                   or (kind == "corpus" and name.startswith("tests/corpus/") and Path(name).name == "README.md")
                   or (kind == "fixture" and name.startswith("tests/js/fixtures/") and Path(name).suffix == ".html")
                   or (kind == "runtime" and name == "frontend/index.html")
                   or (kind == "entry" and name == "packaging/README.md"))
        if not allowed:
            raise ContractError(f"support kind cannot shelter this path: {name}")
        if Path(name).suffix == ".md" and Path(name).name != "README.md" and not _normal_name(name):
            raise ContractError(f"invalid supporting document name: {name}")
    return value


def documents(root: Path) -> list[dict]:
    return inventory(root)["document"]


def source_paths(root: Path, item: dict) -> list[Path]:
    paths: set[Path] = set()
    for pattern in item.get("sources", []):
        relative(root, pattern)
        hits = [p for p in root.glob(pattern) if p.is_file()]
        if not hits:
            raise ContractError(f"empty source glob: {pattern}")
        for path in hits:
            relative(root, path.relative_to(root).as_posix())
            paths.add(path)
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def source_digest(root: Path, item: dict) -> str:
    digest = hashlib.sha256()
    # A glob narrowed to today's explicit files must also require review: the
    # current matched bytes can be identical while future coverage is reduced.
    scope = {"owner": item.get("document", item.get("path", "")), "topic": item.get("id", ""),
             "sources": sorted(item.get("sources", [])), "tests": sorted(item.get("tests", []))}
    digest.update(json.dumps(scope, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\0")
    paths = set(source_paths(root, item))
    for name in item.get("tests", []):
        path = relative(root, name)
        if not path.is_file() or not name.startswith("tests/"):
            raise ContractError(f"missing/invalid evidence test: {name}")
        paths.add(path)
    for path in sorted(paths, key=lambda p: p.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(read(path).encode("utf-8") + b"\0")
    return digest.hexdigest()


def body_digest(root: Path, name: str) -> str:
    return hashlib.sha256(read(relative(root, name)).encode("utf-8")).hexdigest()


def topic_bodies(root: Path, item: dict) -> dict[str, str]:
    text = read(root / item["path"])
    # Ignore examples inside code fences so they cannot create owners.
    visible = without_fences(text)
    names = MARKER.findall(visible)
    matches = list(MARKER.finditer(text))
    if [m[1] for m in matches] != names:
        raise ContractError("topic marker examples must not use a literal standalone marker")
    if not matches or text[:matches[0].start()] != f"# {item['title']}\n\n":
        raise ContractError(f"unowned canonical preamble: {item['path']}")
    if len(names) != len(set(names)):
        raise ContractError(f"duplicate topic marker: {item['path']}")
    bodies = {}
    for i, match in enumerate(matches):
        body = text[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        if not re.search(r"(?m)^## .+", body):
            raise ContractError(f"topic requires a heading: {match[1]}")
        bodies[match[1]] = body
    return bodies


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


def _from_docs(name: str) -> str:
    return name.removeprefix("docs/") if name.startswith("docs/") else "../" + name


def route(root: Path, selector: str = "") -> list[str]:
    """Return all owners of a role, topic or source path; never guess a new file."""
    data = inventory(root)
    selected = []
    for topic in data["topic"]:
        owner = next(d for d in data["document"] if d["path"] == topic["document"])
        target = f"{topic['document']}#{topic['id']}"
        patterns = topic["sources"] + topic["tests"]
        if (not selector or selector in {owner["role"], topic["id"], owner["path"], target}
                or any(PurePosixPath(selector).full_match(p) for p in patterns)):
            selected.append(target)
    for doc in data["document"]:
        if doc["kind"] == "canonical":
            continue
        if selector and (selector in {doc["role"], doc["path"]}
                         or any(PurePosixPath(selector).full_match(p)
                                for p in doc.get("sources", []) + doc.get("tests", []))):
            selected.append(doc["path"])
    if not selected:
        raise ContractError(f"no document owner: {selector!r}; classify the change before writing")
    return selected


def render_index(root: Path, data: dict) -> str:
    records = data["document"]
    lines = ["# 문서 지도", "", "> manifest.toml에서 생성한다. 직접 편집하지 않는다.", "",
             "현재 동작은 코드·테스트·빌드 설정이 최종 권위다. 같은 목적의 새 파일 대신 소유 절을 갱신한다.",
             "절차·이름·예산·검토 명령은 [기여 규칙](../CONTRIBUTING.md)을 따른다.",
             "", "## 읽기와 쓰기의 다섯 목적지", "", "| 목적 | 정본 |", "|---|---|"]
    for role, path in CORE.items():
        doc = next(d for d in records if d["role"] == role)
        lines.append(f"| `{role}` | [{doc['title']}]({_from_docs(path)}) |")
    lines += ["", "## 주제별 작성 라우팅", "", "| 주제 | 갱신할 절 |", "|---|---|"]
    for doc in records:
        if doc["kind"] != "canonical":
            continue
        bodies = topic_bodies(root, doc)
        for topic in (t for t in data["topic"] if t["document"] == doc["path"]):
            title = re.search(r"(?m)^## (.+)$", bodies[topic["id"]])[1]
            lines.append(f"| `{topic['id']}` | [{title}]({_from_docs(doc['path'])}#{topic['id']}) |")
    for kinds, label in [({"generated", "current"}, "진입점·생성 참조"),
                         ({"machine"}, "실행 가능한 원장"),
                         ({"evidence", "research"}, "관측과 연구")]:
        lines += ["", f"## {label}", ""]
        for doc in records:
            if doc["kind"] in kinds and doc["path"] != INDEX:
                lines.append(f"- [{doc['title']}]({_from_docs(doc['path'])})")
    lines += ["", "기능 계획·진행·담당·완료·리뷰는 GitHub 이슈·PR, 재현 입력은 테스트 fixture에 둔다.",
              "작은 제안은 이슈로, 독립 장문 모델만 연구로 분리한다. 증거·연구는 현재 계약을 대신하지 않는다.",
              "예제 설명·코퍼스·테스트/제품 HTML도 manifest에 용도별 정확한 경로로 등록한다."]
    return "\n".join(lines) + "\n"


def render_product(root: Path) -> str:
    """Keep the fixed Impeccable filename/schema without a second editable record."""
    text = read(root / CORE["product"]).split("\n", 1)[1].lstrip("\n")
    if not re.search(r"(?m)^### Platform\n\n(?:web|ios|android|adaptive)\s*$", text):
        raise ContractError("missing/invalid Platform in product source")
    text = MARKER.sub("", text)
    text = re.sub(r"(?m)^### ", "## ", text)

    def link(match: re.Match) -> str:
        target = match[1]
        parts = urlsplit(target)
        if parts.scheme or parts.netloc or not parts.path:
            return match[0]
        path = os.path.normpath("docs/" + parts.path).replace("\\", "/")
        return "](" + path + ("#" + parts.fragment if parts.fragment else "") + ")"

    text = re.sub(r"\]\(([^)]+)\)", link, text)
    return ("# Product\n\n<!-- impeccable:product-schema 1 -->\n\n"
            "> Generated from [docs/product.md](docs/product.md). Edit that source, then run "
            "`uv run python scripts/docs_contract.py --write`.\n\n" + text.lstrip("\n"))


def generated_outputs(root: Path, data: dict) -> dict[str, str]:
    return {INDEX: render_index(root, data), REFERENCE: render_reference(root), PRODUCT: render_product(root)}


def repository_files(root: Path) -> set[str]:
    top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], check=True,
                         capture_output=True, encoding="utf-8").stdout.strip()
    if Path(top).resolve() != root.resolve():
        raise ContractError("documentation inventory must run at the repository root")
    listing = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others",
                              "--exclude-standard", "-z"], check=True, capture_output=True).stdout
    return {s for s in listing.decode("utf-8").split("\0") if s and (root / s).is_file()}


ERRORS = (OSError, ValueError, KeyError, TypeError, SyntaxError, RecursionError, subprocess.CalledProcessError)


def check(root: Path) -> list[str]:
    problems: list[str] = []
    try:
        data = inventory(root)
        records = data["document"]
        generated = generated_outputs(root, data)
        files = repository_files(root)
    except ERRORS as exc:
        return [str(exc)]
    actual = {p for p in files if Path(p).suffix.lower() in DOC_SUFFIXES
              or (p.startswith("docs/") and Path(p).suffix == ".toml")}
    expected = {d["path"] for d in records if Path(d["path"]).suffix.lower() in DOC_SUFFIXES}
    expected |= {s["path"] for s in data["support"]} | {MANIFEST}
    if actual != expected:
        problems.append(f"inventory mismatch: unregistered={sorted(actual - expected)}, "
                        f"missing={sorted(expected - actual)}")
    core_texts = []
    for item in records:
        name = item["path"]
        try:
            text = read(relative(root, name))
            if len(text.splitlines()) > item["max_lines"]:
                problems.append(f"line budget exceeded: {name}")
            problems.extend(link_problems(root, name))
            if item["kind"] == "canonical":
                core_texts.append(text)
                bodies = topic_bodies(root, item)
                topics = [t for t in data["topic"] if t["document"] == name]
                if set(bodies) != {t["id"] for t in topics}:
                    problems.append(f"topic ownership mismatch: {name}")
                for topic in topics:
                    if topic["id"] not in bodies:
                        continue
                    observed = source_digest(root, topic)
                    body = hashlib.sha256(bodies[topic["id"]].encode("utf-8")).hexdigest()
                    if observed != topic["source_sha256"] or body != topic["body_sha256"]:
                        problems.append(f"review required: {name}#{topic['id']}")
            else:
                observed = source_digest(root, item)
                if item["kind"] == "current" and (observed != item["source_sha256"]
                        or body_digest(root, name) != item["body_sha256"]):
                    problems.append(f"review required: {name}")
            if name in generated and text != generated[name]:
                problems.append(f"generated drift: {name}")
        except ERRORS as exc:
            problems.append(f"{name}: {exc}")
    if (sum(len(t.splitlines()) for t in core_texts) > MAX_CORE_LINES
            or sum(len(t.encode("utf-8")) for t in core_texts) > MAX_CORE_BYTES):
        problems.append("canonical total budget exceeded; remove duplication before splitting files")
    for item in data["support"]:
        try:
            if item["kind"] not in {"runtime", "fixture"}:
                problems.extend(link_problems(root, item["path"]))
            # HTML test fixtures intentionally contain broken links/resources.
            if item["kind"] == "entry" and len(read(root / item["path"]).splitlines()) > 20:
                problems.append(f"support entry must remain a pointer: {item['path']}")
        except ERRORS as exc:
            problems.append(f"{item['path']}: {exc}")
    return problems


def write_generated(root: Path) -> None:
    for name, text in generated_outputs(root, inventory(root)).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def acknowledge_review(root: Path, target: str) -> None:
    data = inventory(root)
    name, _, ident = target.partition("#")
    doc = next((d for d in data["document"] if d["path"] == name), None)
    if doc is None:
        raise ContractError(f"unknown review destination: {target}")
    if doc["kind"] == "canonical":
        item = next((t for t in data["topic"] if t["document"] == name and t["id"] == ident), None)
        if item is None:
            raise ContractError("review must name one canonical topic: document#topic-id")
        section = topic_bodies(root, doc)[ident]
        body = hashlib.sha256(section.encode("utf-8")).hexdigest()
        kind, key, value = "topic", "id", ident
    elif doc["kind"] == "current" and not ident:
        item, body = doc, body_digest(root, name)
        kind, key, value = "document", "path", name
    else:
        raise ContractError("review must name one current document or canonical topic")
    values = {"source_sha256": source_digest(root, item), "body_sha256": body}
    text = read(root / MANIFEST)
    matches = list(re.finditer(r"(?m)^\[\[(document|topic|support)\]\]$", text))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[match.start():end]
        if match[1] != kind or tomllib.loads(block)[kind][0].get(key) != value:
            continue
        for field, digest in values.items():
            block, count = re.subn(rf'(?m)^{field} = "[a-f0-9]{{64}}"$', f'{field} = "{digest}"', block)
            if count != 1:
                raise ContractError(f"cannot record review: {target}: {field}")
        (root / MANIFEST).write_text(text[:match.start()] + block + text[end:], encoding="utf-8", newline="\n")
        return
    raise ContractError(f"missing review record: {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="verify without writing (default)")
    modes.add_argument("--write", action="store_true", help="regenerate outputs, never acknowledge review")
    modes.add_argument("--route", nargs="?", const="", metavar="ROLE_OR_SOURCE", help="find existing owners")
    modes.add_argument("--review", metavar="DOCUMENT#TOPIC", help="record one explicitly reviewed unit")
    args = parser.parse_args(argv)
    try:
        if args.route is not None:
            print("\n".join(route(ROOT, args.route)))
            return 0
        if args.write:
            write_generated(ROOT)
            print("Generated documents updated; review fingerprints unchanged.")
            return 0
        if args.review:
            acknowledge_review(ROOT, args.review)
            print(f"Review recorded: {args.review}; semantic accuracy remains reviewer-owned.")
            return 0
        problems = check(ROOT)
    except ERRORS as exc:
        problems = [str(exc)]
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
