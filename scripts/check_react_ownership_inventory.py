"""React 소유권 인벤토리 원장(``docs/react_ownership_inventory.toml``)의 재실측기.

## 무엇을 지키는가

R1 의 완료물은 「React 소유 단위와 검증 책임의 **미분류 0** 원장」이다. 그 「0」을 선언으로
적으면 병합 다음 날부터 조용히 거짓이 된다 — 노드가 늘어도 원장은 초록이기 때문이다.
그래서 이 스크립트는 **선언을 읽지 않고 저장소를 다시 잰다**. 네 방향으로 센다:

* ``M − C`` — 저장소에 있는데 원장에 없는 노드(**미분류**)
* ``C − M`` — 원장에 있는데 저장소에서 사라진 노드(**유령 행**)
* ``members_expected`` — 접힌 컨테이너 행의 실제 배정 수(접기가 성장을 삼키지 못하게)
* ``blind_spot`` — 술어가 **못 보는 것**의 오늘 크기(사각이 자라면 붉는다)

넷째가 이 원장의 뼈대다. 이 저장소에서 계측 술어가 네 번 틀렸고, 그중 하나는 「정규식이
틀렸다」가 아니라 **「술어의 커버리지를 안 물었다」**였다(2칸 들여쓰기 관례가 0칸 최상위 4를
못 보고 비-export 함수 지역 12를 상태로 오독). 값만 지키는 계약은 그 결함류를 못 막는다.

## 형식 계약

* **TOML 만 읽는다.** 마크다운을 파싱하는 추출기는 만들지 않는다(`R1-ARTIFACT-LAYOUT:v2` §3).
  1차 구현 라운드가 695행 마크다운 파서로 무너진 자리다.
* **모든 계측 항목은 ``predicate``·``scope``·``unit`` 셋을 든다.** 하나라도 없으면 값이 아니라
  구조 오류다 — 같은 이름이 다른 것을 가리키는 사고(`innerHTML` 61/71/83/50)가 이 계약의 이유다.
* **``evidence`` 는 ``{file, line, anchor}``.** 파일 존재와 행수만 보면 824행 문서의 아무 줄이나
  초록이다. 앵커 문자열을 그 줄에서 실제로 읽는다 — 집필 중 남의 커밋이 상수를 15줄 밀었을 때
  앵커 없는 증거였다면 초록이었다.
* **분류 어휘는 소문자 5종.** 이 저장소의 기계 판독 TOML 은 enum 값에 대문자를 쓰지 않는다.

## 자족 판정

R1-99 감사자는 write 0 · 네트워크 0 · 실행 1회로 판정한다::

    uv run python scripts/check_react_ownership_inventory.py --report json

종료 코드가 판정이고, JSON 은 축별 ``measured/covered/unclassified/ghost/duplicate``,
``members_mismatch``, ``blind_spot_delta``, 계측 불일치, ``unknown`` 개수를 든다.

## 이 파일이 순수 함수를 노출하는 이유

:func:`check` 는 **파싱된 문서와 저장소 루트를 인자로** 받는다. 그래서 음성 대조가 파일 텍스트
전역 치환 없이 **한 좌표만** 바꿀 수 있다 — 전역 치환으로 음성 대조가 스스로를 가린 전례가
이 저장소에 있다.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCUMENT = REPO_ROOT / "docs" / "react_ownership_inventory.toml"
NODE_EXTRACTOR_SCRIPT = "scripts/extract_js_ast_axes.mjs"

#: 분류 어휘 — `R1-ARTIFACT-LAYOUT:v2` §2 가 정본이고 중앙 V1 이 소문자로 못박았다.
#: `classification` 과 구 `p_authority` 는 값 공간이 같은 한 축이라 중앙 V7 이 열을 합쳤다.
CLASSIFICATIONS = frozenset(
    {"react", "python_product", "host", "retire", "p_review_required"}
)
NODE_KINDS = frozenset({"dom", "state", "subscription", "lifecycle"})
BACKINGS = frozenset({"parser", "ast", "regex-convention", "python-import"})
#: ``per-line`` 은 줄 단위로 돌린 **일치 수**, ``per-occurrence`` 는 파일 전체에 돌린 일치 수,
#: ``per-matching-line`` 은 **일치가 있는 줄 수**다. 셋을 가르는 이유가 원장에 실측으로 있다 —
#: 같은 술어 ``window\.pywebview`` 가 32(줄) 와 34(회) 를 낸다.
GRANULARITIES = frozenset({"per-line", "per-occurrence", "per-matching-line"})
P_HANDOFF_VALUES = frozenset({"yes", "no"})

#: G15 「인계 항목 증거 연결 누락 0」의 기계 판독 형태. 공란은 실패이고 「모름」은 공란이
#: 아니라 ``unknown`` 명시값이다 — 게이트가 그 수를 **보고**해 R1-99 가 판정한다.
P_REVIEW_FIELDS = ("producer", "consumer", "call_path", "contract", "test")

#: 이관 슬라이스 어휘 — R2~R5 구현 슬라이스 이슈. `SCREEN-SPLIT-ROADMAP:v1` 의 책임 축이
#: R4-01~R4-03 에 정렬한다. 새 Vanilla 파일 목록을 만들지 않는다(L15).
HANDOFF_SLICES = frozenset(
    {
        "R2-01 #405", "R2-02 #406", "R2-03 #407", "R2-04 #408",
        "R3-01 #410", "R3-02 #411", "R3-03 #412",
        "R4-01 #414", "R4-02 #415", "R4-03 #416", "R4-04 #417",
        "R5-01 #419", "R5-02 #420", "R5-03 #421",
    }
)


class InventoryGateError(RuntimeError):
    """원장·저장소가 아니라 **게이트 자신의 전제**가 깨졌을 때만 던진다."""


# ──────────────────────────────────────────────────────────────────────────
# 저장소 컨텍스트 — 추출기가 공유하는 캐시
# ──────────────────────────────────────────────────────────────────────────


def _read_text(path: Path) -> str | None:
    """텍스트로 읽는다. 바이너리(글꼴 등)는 ``None`` — 세지 않되 죽지도 않는다."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


class Repo:
    """저장소 한 그루에 대한 read-only 측정 컨텍스트."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._files: dict[tuple[str, ...], list[Path]] = {}
        self._node_axes: dict[str, list[str]] | None = None
        self._html: _IndexParse | None = None

    def files(self, scope: tuple[str, ...]) -> list[Path]:
        cached = self._files.get(scope)
        if cached is None:
            seen: dict[Path, None] = {}
            for pattern in scope:
                for path in sorted(self.root.glob(pattern)):
                    if path.is_file():
                        seen[path] = None
            cached = list(seen)
            self._files[scope] = cached
        return cached

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def html(self) -> _IndexParse:
        if self._html is None:
            self._html = _parse_index(self.root / "frontend" / "index.html")
        return self._html

    def node_axes(self) -> dict[str, list[str]]:
        """Node AST 추출기를 **한 번** 돌려 세 축을 받는다.

        Node 부재는 조용한 스킵이 아니라 실패다 — Node 는 이 저장소의 빌드 전제조건이고
        CI contract 잡은 pytest 앞에서 프런트 툴체인을 설치한다.
        """
        if self._node_axes is None:
            node = shutil.which("node")
            if node is None:
                raise InventoryGateError(
                    "Node 가 PATH 에 없습니다 — JS AST 축(id 사이트·모듈 상태)을 잴 수 없습니다. "
                    "Node 는 이 저장소의 빌드 전제조건이라 부재는 스킵 사유가 아닙니다."
                )
            script = REPO_ROOT / NODE_EXTRACTOR_SCRIPT
            if not script.is_file():
                raise InventoryGateError(f"AST 추출기가 없습니다: {script}")
            result = subprocess.run(
                [node, str(script), "--repo-root", str(self.root)],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                raise InventoryGateError(
                    "AST 추출기가 실패했습니다.\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                )
            self._node_axes = json.loads(result.stdout)
        return self._node_axes


# ──────────────────────────────────────────────────────────────────────────
# 파서 추출기 — `frontend/index.html`
# ──────────────────────────────────────────────────────────────────────────

_VOID_ELEMENTS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "source", "track", "wbr",
    }
)


@dataclass
class _IndexParse:
    ids: list[str] = field(default_factory=list)
    id_lines: dict[str, int] = field(default_factory=dict)
    #: id → 자기 자신을 **포함하지 않는** 조상 스택(문서 순서, 바깥→안쪽).
    ancestors: dict[str, tuple[str, ...]] = field(default_factory=dict)
    data_attributes: Counter[str] = field(default_factory=Counter)
    unbalanced: int = 0


class _IndexCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out = _IndexParse()
        self._stack: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        mapping = dict(attrs)
        element_id = mapping.get("id")
        if element_id:
            self.out.ids.append(element_id)
            self.out.id_lines[element_id] = self.getpos()[0]
            self.out.ancestors[element_id] = tuple(
                name for name in self._stack if name is not None
            )
        for name in mapping:
            if name.startswith("data-"):
                self.out.data_attributes[name] += 1
        if tag not in _VOID_ELEMENTS:
            self._stack.append(element_id)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_ELEMENTS and self._stack:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_ELEMENTS:
            return
        if self._stack:
            self._stack.pop()
        else:
            self.out.unbalanced += 1

    def close(self) -> None:  # noqa: D102 - HTMLParser API
        super().close()
        self.out.unbalanced += len(self._stack)


def _parse_index(path: Path) -> _IndexParse:
    if not path.is_file():
        raise InventoryGateError(f"정적 DOM 원본이 없습니다: {path}")
    parser = _IndexCollector()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser.out


# ──────────────────────────────────────────────────────────────────────────
# 이름 붙은 추출기 레지스트리
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Extractor:
    """이름 붙은 추출기.

    ``scope`` 를 코드가 들고 원장의 ``scope`` 와 **일치를 강제**한다. 그래야 원장이 술어의
    범위를 혼자 다시 쓸 수 없다 — scope 부재·불일치가 이 저장소가 반복해 만난 결함류다.
    """

    backing: str
    scope: tuple[str, ...]
    run: Callable[[Repo], list[str]]


def _html_ids(repo: Repo) -> list[str]:
    return list(repo.html().ids)


def _html_data_attrs(repo: Repo) -> list[str]:
    return sorted(repo.html().data_attributes)


def _html_parse_anomalies(repo: Repo) -> list[str]:
    """파서의 관용 복구가 삼킬 수 있는 것 — 중복 id 와 태그 불균형."""
    parsed = repo.html()
    counts = Counter(parsed.ids)
    rows = [f"duplicate-id:{name}" for name, n in sorted(counts.items()) if n > 1]
    rows += [f"unbalanced-tag:{parsed.unbalanced}"] if parsed.unbalanced else []
    return rows


_NAIVE_DATA_ATTR = re.compile(r"data-[a-z-]+")


def _html_data_attr_regex_delta(repo: Repo) -> list[str]:
    """무앵커 정규식이 더 잡는 이름 — CSS 클래스·산문. 파서 쪽이 참값이다."""
    text = (repo.root / "frontend" / "index.html").read_text(encoding="utf-8")
    naive = set(_NAIVE_DATA_ATTR.findall(text))
    return sorted(naive - set(repo.html().data_attributes))


def _js_template_ids(repo: Repo) -> list[str]:
    return list(repo.node_axes()["js_template_ids"])


def _js_module_state(repo: Repo) -> list[str]:
    return list(repo.node_axes()["js_module_state"])


def _js_nonexported_fn_state(repo: Repo) -> list[str]:
    return list(repo.node_axes()["js_nonexported_fn_state"])


#: `dom_js_site` 의 앵커 정규식이 못 보는 네 형태. 오늘 전부 0이지만 **오늘 0인 것과 앞으로도
#: 0인 것은 다르다** — 그래서 프로브가 매번 그 0을 재확인한다.
_ID_ATTR_GAP_PATTERNS = (
    ("other-attr-suffix", r'[-a-zA-Z]id="'),
    ("single-quoted", r"id='"),
    ("unquoted-interpolation", r"id=\$\{"),
    ("selector-literal", r"\[id="),
)


def _js_id_attr_anchor_gaps(repo: Repo) -> list[str]:
    rows: list[str] = []
    for path in repo.files(("frontend/js/**/*.js",)):
        text = _read_text(path)
        if text is None:
            continue
        for name, pattern in _ID_ATTR_GAP_PATTERNS:
            for line_no, line in enumerate(text.splitlines(), 1):
                for _ in re.finditer(pattern, line):
                    rows.append(f"{repo.relative(path)}:{line_no}:{name}")
    return sorted(rows)


_CONVENTION_STATE = re.compile(r"(?m)^  (?:let|var)\s+([A-Za-z_$][\w$]*)")


def _js_module_state_convention(repo: Repo) -> list[str]:
    """2칸 들여쓰기 **관례** 술어 — `test_web_dom_contract.py` 의 예산 헬퍼와 같은 눈.

    원장은 이것을 값으로 쓰지 않는다. 예산 6파일 안에서는 AST 와 정확히 일치하고(36 = 36)
    그 밖에서는 거짓양성 12·거짓음성 4를 낸다 — 두 계측의 **관계**를 원장 한자리에 두려고
    ``aliases`` 로만 싣는다.
    """
    rows: list[str] = []
    for path in repo.files(("frontend/js/**/*.js",)):
        text = _read_text(path)
        if text is None:
            continue
        rel = repo.relative(path)
        for line_no, line in enumerate(text.splitlines(), 1):
            match = _CONVENTION_STATE.match(line)
            if match:
                rows.append(f"{rel}:{line_no} {match.group(1)}")
    return sorted(rows)


_BUDGET_SCOPE = (
    "frontend/js/screens/job.js",
    "frontend/js/screens/workbench.js",
    "frontend/js/screens/editor.js",
    "frontend/js/screens/library.js",
    "frontend/js/data_picker.js",
    "frontend/js/datazone.js",
)


def _js_module_state_convention_budget(repo: Repo) -> list[str]:
    allowed = {f"{rel}" for rel in _BUDGET_SCOPE}
    return [row for row in _js_module_state_convention(repo) if row.split(":")[0] in allowed]


def _action_registry_screens(repo: Repo) -> list[str]:
    from hwpxfiller.webapp.action_registry import ACTION_REGISTRY

    return sorted(ACTION_REGISTRY)


def _action_registry_pairs(repo: Repo) -> list[str]:
    from hwpxfiller.webapp.action_registry import ACTION_REGISTRY

    return sorted(
        f"{screen}/{action}"
        for screen, actions in ACTION_REGISTRY.items()
        for action in actions
    )


def _action_registry_dynamic(repo: Repo) -> list[str]:
    """레지스트리가 모듈 상수인가 — 런타임 변형 사이트를 센다(오늘 0)."""
    rows: list[str] = []
    pattern = r"ACTION_REGISTRY\s*\[|ACTION_REGISTRY\.(?:setdefault|update|pop)"
    for path in repo.files(("src/hwpxfiller/webapp/*.py",)):
        text = _read_text(path)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if re.search(pattern, line):
                rows.append(f"{repo.relative(path)}:{line_no}")
    return sorted(rows)


def _ring1_state_modules(repo: Repo) -> list[str]:
    return [repo.relative(path) for path in repo.files(("src/hwpxfiller/gui/*_state.py",))]


def _gui_non_state_modules(repo: Repo) -> list[str]:
    """`*_state.py` 이름 규약 밖의 링1 이웃 — 이 축이 못 보는 자리의 오늘 전수."""
    return [
        repo.relative(path)
        for path in repo.files(("src/hwpxfiller/gui/*.py",))
        if not path.name.endswith("_state.py") and path.name != "__init__.py"
    ]


_LISTENER_GAP_PATTERNS = (
    ("comment", r"(?m)^\s*(?://|\*|/\*).*(?:add|remove)EventListener"),
    ("bracket-call", r"\[[^\]\n]+\]\s*\(\s*[\"'][a-z]+[\"']\s*,"),
)


def _listener_convention_gaps(repo: Repo) -> list[str]:
    """관례 정규식이 **함께 세거나 못 보는** 것 — 주석 안 일치와 대괄호 표기 호출."""
    rows: list[str] = []
    for path in repo.files(("frontend/js/**/*.js",)):
        text = _read_text(path)
        if text is None:
            continue
        rel = repo.relative(path)
        for name, pattern in _LISTENER_GAP_PATTERNS:
            for match in re.finditer(pattern, text):
                line_no = text[: match.start()].count("\n") + 1
                rows.append(f"{rel}:{line_no}:{name}")
    return sorted(rows)


EXTRACTORS: dict[str, Extractor] = {
    "html_ids": Extractor("parser", ("frontend/index.html",), _html_ids),
    "html_data_attrs": Extractor("parser", ("frontend/index.html",), _html_data_attrs),
    "html_parse_anomalies": Extractor(
        "parser", ("frontend/index.html",), _html_parse_anomalies
    ),
    "html_data_attr_regex_delta": Extractor(
        "regex-convention", ("frontend/index.html",), _html_data_attr_regex_delta
    ),
    "js_template_ids": Extractor("ast", ("frontend/js/**/*.js",), _js_template_ids),
    "js_id_attr_anchor_gaps": Extractor(
        "regex-convention", ("frontend/js/**/*.js",), _js_id_attr_anchor_gaps
    ),
    "js_module_state": Extractor(
        "ast", ("frontend/js/**/*.js", "frontend/src/*.js"), _js_module_state
    ),
    "js_nonexported_fn_state": Extractor(
        "ast", ("frontend/js/**/*.js",), _js_nonexported_fn_state
    ),
    "js_module_state_convention": Extractor(
        "regex-convention", ("frontend/js/**/*.js",), _js_module_state_convention
    ),
    "js_module_state_convention_budget": Extractor(
        "regex-convention", _BUDGET_SCOPE, _js_module_state_convention_budget
    ),
    "action_registry_screens": Extractor(
        "python-import",
        ("src/hwpxfiller/webapp/action_registry.py",),
        _action_registry_screens,
    ),
    "action_registry_pairs": Extractor(
        "python-import",
        ("src/hwpxfiller/webapp/action_registry.py",),
        _action_registry_pairs,
    ),
    "action_registry_dynamic": Extractor(
        "regex-convention", ("src/hwpxfiller/webapp/*.py",), _action_registry_dynamic
    ),
    "ring1_state_modules": Extractor(
        "python-import", ("src/hwpxfiller/gui/*_state.py",), _ring1_state_modules
    ),
    "gui_non_state_modules": Extractor(
        "python-import", ("src/hwpxfiller/gui/*.py",), _gui_non_state_modules
    ),
    "listener_convention_gaps": Extractor(
        "regex-convention", ("frontend/js/**/*.js",), _listener_convention_gaps
    ),
}

#: `kind = "node_extractor"` 로 선언해야 하는 추출기 — 읽는 사람이 「이 값이 얼마나 믿을
#: 만한가」를 이름이 아니라 종류에서 읽게 한다.
_NODE_BACKED = frozenset(
    name for name, extractor in EXTRACTORS.items() if extractor.backing == "ast"
)


# ──────────────────────────────────────────────────────────────────────────
# 정규식 술어 — 패턴·범위·단위가 **원장 안에** 산다
# ──────────────────────────────────────────────────────────────────────────


def _regex_sites(repo: Repo, pattern: str, scope: tuple[str, ...], granularity: str) -> list[str]:
    """정규식 술어를 사이트 좌표로 편다.

    ``per-line`` 은 줄 단위로 돌린다 — 셸 ``grep`` 과 같은 눈이라 줄 끝 대입에서 값이 갈리는
    자리(`innerHTML` 61 vs 50)를 원장이 재현할 수 있다.
    """
    compiled = re.compile(pattern)
    rows: list[str] = []
    for path in repo.files(scope):
        text = _read_text(path)
        if text is None:
            continue
        rel = repo.relative(path)
        if granularity == "per-occurrence":
            seen: Counter[int] = Counter()
            for match in compiled.finditer(text):
                line_no = text[: match.start()].count("\n") + 1
                seen[line_no] += 1
                index = seen[line_no]
                rows.append(f"{rel}:{line_no}" + (f"#{index}" if index > 1 else ""))
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            matches = list(compiled.finditer(line))
            if not matches:
                continue
            if granularity == "per-matching-line":
                rows.append(f"{rel}:{line_no}")
                continue
            for index, _ in enumerate(matches, 1):
                rows.append(f"{rel}:{line_no}" + (f"#{index}" if index > 1 else ""))
    return rows


def _measure(repo: Repo, predicate: dict[str, Any], scope: tuple[str, ...],
             axis_members: dict[str, list[str]] | None = None) -> list[str]:
    """술어 하나를 저장소에 재실행해 **멤버 키 목록**을 돌려준다."""
    kind = predicate.get("kind")
    if kind in {"extractor", "node_extractor"}:
        name = predicate.get("name")
        extractor = EXTRACTORS.get(name or "")
        if extractor is None:
            raise InventoryGateError(f"등록되지 않은 추출기: {name!r}")
        return list(extractor.run(repo))
    if kind == "regex":
        return _regex_sites(
            repo, predicate["pattern"], scope, predicate.get("granularity", "per-occurrence")
        )
    if kind == "derived":
        axis = predicate.get("axis")
        if axis_members is None or axis not in axis_members:
            raise InventoryGateError(f"파생 술어가 가리키는 축을 못 잽니다: {axis!r}")
        members = axis_members[axis]
        return [member for member in members if _member_in_scope(member, scope)]
    raise InventoryGateError(f"알 수 없는 술어 종류: {kind!r}")


def _member_in_scope(member: str, scope: tuple[str, ...]) -> bool:
    """멤버 키의 경로 접두를 scope 글롭에 맞춘다 — 경로가 없는 멤버는 전부 통과."""
    head = member.split(":", 1)[0].split(" ", 1)[0]
    if "/" not in head:
        return True
    return any(_glob_match(head, pattern) for pattern in scope)


def _glob_match(path: str, pattern: str) -> bool:
    regex = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*")
    regex = regex.replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    return re.fullmatch(regex, path) is not None


# ──────────────────────────────────────────────────────────────────────────
# 보고서
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class AxisReport:
    axis: str
    measured: int = 0
    covered: int = 0
    unclassified: list[str] = field(default_factory=list)
    ghost: list[str] = field(default_factory=list)
    duplicate: list[str] = field(default_factory=list)
    members_mismatch: list[str] = field(default_factory=list)
    blind_spot_delta: list[str] = field(default_factory=list)


@dataclass
class Report:
    axes: dict[str, AxisReport] = field(default_factory=dict)
    metric_mismatch: list[str] = field(default_factory=list)
    structural: list[str] = field(default_factory=list)
    unknown_evidence: int = 0
    node_rows: int = 0

    @property
    def failures(self) -> list[str]:
        rows = list(self.structural)
        for axis in self.axes.values():
            rows += [f"[{axis.axis}] 미분류: {member}" for member in axis.unclassified]
            rows += [f"[{axis.axis}] 유령 행: {member}" for member in axis.ghost]
            rows += [f"[{axis.axis}] 중복 소유: {member}" for member in axis.duplicate]
            rows += [f"[{axis.axis}] {message}" for message in axis.members_mismatch]
            rows += [f"[{axis.axis}] {message}" for message in axis.blind_spot_delta]
        rows += self.metric_mismatch
        return rows

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "node_rows": self.node_rows,
            "unknown_evidence": self.unknown_evidence,
            "axes": {
                name: {
                    "measured": axis.measured,
                    "covered": axis.covered,
                    "unclassified": axis.unclassified,
                    "ghost": axis.ghost,
                    "duplicate": axis.duplicate,
                    "members_mismatch": axis.members_mismatch,
                    "blind_spot_delta": axis.blind_spot_delta,
                }
                for name, axis in self.axes.items()
            },
            "metric_mismatch": self.metric_mismatch,
            "structural": self.structural,
            "failures": self.failures,
        }


# ──────────────────────────────────────────────────────────────────────────
# 구조 술어
# ──────────────────────────────────────────────────────────────────────────


def _require_predicate_triple(where: str, item: dict[str, Any], report: Report) -> bool:
    """술어 3종 필수, 예외 0. ``derived`` 도 ``predicate.kind`` 의 한 값이라 면제가 아니다."""
    ok = True
    for field_name in ("predicate", "scope", "unit"):
        value = item.get(field_name)
        if value is None or (isinstance(value, (str, list)) and len(value) == 0):
            report.structural.append(
                f"{where}: `{field_name}` 이(가) 없습니다 — 값만 있는 항목은 성립하지 않습니다."
            )
            ok = False
    predicate = item.get("predicate")
    if not isinstance(predicate, dict) or "kind" not in predicate:
        report.structural.append(f"{where}: `predicate.kind` 가 없습니다.")
        return False
    kind = predicate["kind"]
    if kind == "regex":
        for field_name in ("pattern", "flavor", "granularity"):
            if not predicate.get(field_name):
                report.structural.append(
                    f"{where}: `backing=regex-convention` 술어는 `predicate.{field_name}` 을 듭니다."
                )
                ok = False
        if predicate.get("granularity") not in GRANULARITIES | {None}:
            report.structural.append(
                f"{where}: 알 수 없는 granularity {predicate.get('granularity')!r}."
            )
            ok = False
    elif kind in {"extractor", "node_extractor"}:
        name = predicate.get("name")
        extractor = EXTRACTORS.get(name or "")
        if extractor is None:
            report.structural.append(f"{where}: 등록되지 않은 추출기 {name!r}.")
            return False
        if (kind == "node_extractor") != (name in _NODE_BACKED):
            report.structural.append(
                f"{where}: 추출기 {name!r} 의 backing 은 {extractor.backing!r} 인데 "
                f"`kind={kind}` 로 선언됐습니다."
            )
            ok = False
        declared = tuple(item.get("scope") or ())
        if declared != extractor.scope:
            report.structural.append(
                f"{where}: 추출기 {name!r} 의 scope 는 {list(extractor.scope)} 인데 "
                f"원장은 {list(declared)} 라고 적었습니다."
            )
            ok = False
    elif kind != "derived":
        report.structural.append(f"{where}: 알 수 없는 술어 종류 {kind!r}.")
        ok = False
    return ok


def _check_evidence(node_id: str, evidence: Any, repo: Repo, report: Report) -> None:
    """``{file, line, anchor}`` 셋을 실제로 읽는다 — 앵커가 그 줄에 있어야 증거다."""
    if not isinstance(evidence, list) or not evidence:
        report.structural.append(f"노드 {node_id}: `evidence` 가 비었습니다.")
        return
    for item in evidence:
        if not isinstance(item, dict) or {"file", "line", "anchor"} - item.keys():
            report.structural.append(
                f"노드 {node_id}: `evidence` 는 {{file, line, anchor}} 여야 합니다 — {item!r}"
            )
            continue
        path = repo.root / str(item["file"])
        if not path.is_file():
            report.structural.append(f"노드 {node_id}: 증거 파일이 없습니다 — {item['file']}")
            continue
        text = _read_text(path)
        if text is None:
            report.structural.append(f"노드 {node_id}: 증거 파일을 읽지 못했습니다 — {item['file']}")
            continue
        lines = text.splitlines()
        line_no = int(item["line"])
        if not 1 <= line_no <= len(lines):
            report.structural.append(
                f"노드 {node_id}: 증거 좌표가 파일 밖입니다 — "
                f"{item['file']}:{line_no} (총 {len(lines)}행)"
            )
            continue
        if str(item["anchor"]) not in lines[line_no - 1]:
            report.structural.append(
                f"노드 {node_id}: 증거 앵커가 그 줄에 없습니다 — "
                f"{item['file']}:{line_no} 에서 {item['anchor']!r} 를 찾지 못했습니다."
            )


def _check_verification(node_id: str, entries: Any, repo: Repo, report: Report) -> None:
    """``verification`` 은 「오늘 이 노드를 보는 테스트」다.

    ``none`` 은 **명시값**이다 — 공란과 다르다. 나머지는 `파일` 또는 `파일::테스트` 이고
    게이트가 그 파일과 이름의 실재를 확인한다. 확인하지 않으면 이름이 죽은 뒤에도 원장은
    초록으로 「검증된다」고 말한다.
    """
    if not isinstance(entries, list) or not entries:
        report.structural.append(f"노드 {node_id}: `verification` 이 비었습니다(없으면 `none` 명시값).")
        return
    for entry in entries:
        if entry == "none":
            continue
        rel, _, test_name = str(entry).partition("::")
        path = repo.root / rel
        if not path.is_file():
            report.structural.append(f"노드 {node_id}: 검증 자산이 없습니다 — {entry}")
            continue
        if test_name:
            text = _read_text(path) or ""
            if f"def {test_name}(" not in text:
                report.structural.append(
                    f"노드 {node_id}: 검증 자산에 그 테스트가 없습니다 — {entry}"
                )


def _check_node_shape(node: dict[str, Any], declared_axes: set[str], report: Report) -> None:
    node_id = str(node.get("id", "<id 없음>"))
    for field_name in ("id", "kind", "axis", "selector", "classification", "verification"):
        if not node.get(field_name):
            report.structural.append(f"노드 {node_id}: `{field_name}` 이(가) 없습니다.")
    kind = node.get("kind")
    if kind is not None and kind not in NODE_KINDS:
        report.structural.append(
            f"노드 {node_id}: `kind` 는 {sorted(NODE_KINDS)} 중 하나여야 합니다 — {kind!r}"
        )
    classification = node.get("classification")
    if classification is not None and classification not in CLASSIFICATIONS:
        report.structural.append(
            f"노드 {node_id}: `classification` 은 소문자 5종 {sorted(CLASSIFICATIONS)} 중 "
            f"하나여야 합니다 — {classification!r}"
        )
    axis = node.get("axis")
    if axis is not None and axis not in declared_axes:
        report.structural.append(f"노드 {node_id}: 선언되지 않은 축 {axis!r}.")

    # 배타성(구조 술어 9)
    if classification == "react" and not node.get("handoff_slice"):
        report.structural.append(
            f"노드 {node_id}: `classification=react` 행은 `handoff_slice` 를 듭니다."
        )
    slice_name = node.get("handoff_slice")
    if slice_name and slice_name not in HANDOFF_SLICES:
        report.structural.append(
            f"노드 {node_id}: 알 수 없는 이관 슬라이스 {slice_name!r} — "
            f"R2~R5 구현 슬라이스여야 합니다."
        )
    if classification in {"python_product", "host", "retire"}:
        handoff = node.get("p_handoff")
        if handoff not in P_HANDOFF_VALUES:
            report.structural.append(
                f"노드 {node_id}: `classification={classification}` 행은 "
                f"`p_handoff` 를 yes|no 로 듭니다 — {handoff!r}"
            )
        if classification == "retire" and handoff == "yes":
            report.structural.append(
                f"노드 {node_id}: `retire` 행의 `p_handoff` 는 `no` 로 강제됩니다."
            )
    if classification == "p_review_required":
        review = node.get("p_review")
        if not isinstance(review, dict):
            report.structural.append(
                f"노드 {node_id}: `p_review_required` 행은 5증거 표 `[node.p_review]` 를 듭니다."
            )
        else:
            for field_name in P_REVIEW_FIELDS:
                value = review.get(field_name)
                if not value:
                    report.structural.append(
                        f"노드 {node_id}: `p_review.{field_name}` 이(가) 공란입니다 — "
                        "「모름」은 공란이 아니라 `unknown` 명시값입니다."
                    )
                elif value == "unknown" or value.startswith("unknown "):
                    report.unknown_evidence += 1


# ──────────────────────────────────────────────────────────────────────────
# 폐포
# ──────────────────────────────────────────────────────────────────────────


def _fold_dom(repo: Repo, containers: set[str], exact_ids: set[str]) -> dict[str, list[str]]:
    """자신을 포함하지 않는 **가장 가까운 선언된 컨테이너**에 배정한다.

    컨테이너 루트 자신은 자기 컨테이너에 속하지 않으므로 반드시 위쪽 어딘가에 `exact` 행이나
    바깥 컨테이너가 있어야 한다 — 그 규칙 때문에 루트 직속 9는 전부 `exact` 로 명시된다.
    """
    parsed = repo.html()
    assignment: dict[str, list[str]] = {name: [] for name in containers}
    assignment["ROOT"] = []
    for element_id in parsed.ids:
        if element_id in exact_ids:
            continue
        owner = "ROOT"
        for ancestor in reversed(parsed.ancestors.get(element_id, ())):
            if ancestor in containers:
                owner = ancestor
                break
        assignment[owner].append(element_id)
    return assignment


def _axis_coverage(
    axis_name: str,
    axis_decl: dict[str, Any],
    nodes: list[dict[str, Any]],
    measured: list[str],
    repo: Repo,
) -> AxisReport:
    result = AxisReport(axis=axis_name, measured=len(measured))
    measured_set = set(measured)

    exact_ids: set[str] = set()
    for node in nodes:
        selector = node.get("selector") or {}
        if selector.get("kind") == "exact":
            exact_ids.update(selector.get("members") or [])

    folded: dict[str, list[str]] = {}
    if axis_decl.get("fold"):
        containers = {
            (node.get("selector") or {}).get("root")
            for node in nodes
            if (node.get("selector") or {}).get("kind") == "subtree"
        }
        folded = _fold_dom(repo, {name for name in containers if name}, exact_ids)

    covered: Counter[str] = Counter()
    for node in nodes:
        node_id = str(node.get("id"))
        selector = node.get("selector") or {}
        if selector.get("kind") == "exact":
            covered.update(selector.get("members") or [])
        elif selector.get("kind") == "subtree":
            root = selector.get("root")
            members = folded.get(root, [])
            covered.update(members)
            expected = selector.get("members_expected")
            if expected is None:
                result.members_mismatch.append(
                    f"접힌 행 {node_id}: `members_expected` 가 없습니다 — "
                    "접기만 있으면 컨테이너 안쪽 성장이 영영 안 붉습니다."
                )
            elif int(expected) != len(members):
                result.members_mismatch.append(
                    f"접힌 행 {node_id}(root={root}): members_expected={expected} 인데 "
                    f"실제 배정은 {len(members)} 입니다."
                )
            if root not in measured_set and root is not None:
                result.ghost.append(f"{root} (컨테이너 루트가 저장소에 없습니다: {node_id})")
        else:
            result.members_mismatch.append(
                f"노드 {node_id}: 알 수 없는 selector 종류 {selector.get('kind')!r}."
            )

    result.covered = len(covered)
    result.duplicate = sorted(name for name, count in covered.items() if count > 1)
    result.unclassified = sorted(measured_set - set(covered))
    result.ghost += sorted(set(covered) - measured_set)
    return result


def _check_blind_spot(
    axis_name: str,
    axis_decl: dict[str, Any],
    repo: Repo,
    axis_members: dict[str, list[str]],
    report: Report,
    axis_report: AxisReport,
) -> None:
    blind = axis_decl.get("blind_spot")
    if not isinstance(blind, dict):
        report.structural.append(
            f"축 {axis_name}: `blind_spot` 이 없습니다 — 추출기 항목은 「이 술어가 못 보는 것」을 "
            "데이터로 듭니다(없으면 `current = 0` 과 그것을 세는 프로브를)."
        )
        return
    for field_name in ("description", "probe", "scope", "current"):
        if blind.get(field_name) is None:
            report.structural.append(f"축 {axis_name}: `blind_spot.{field_name}` 이(가) 없습니다.")
            return
    if not _require_predicate_triple(
        f"축 {axis_name} 의 blind_spot",
        {"predicate": blind["probe"], "scope": blind["scope"], "unit": blind.get("unit", "건")},
        report,
    ):
        return
    try:
        found = _measure(repo, blind["probe"], tuple(blind["scope"]), axis_members)
    except InventoryGateError as exc:
        report.structural.append(f"축 {axis_name}: 사각 프로브 실패 — {exc}")
        return
    if len(found) != int(blind["current"]):
        axis_report.blind_spot_delta.append(
            f"사각이 움직였습니다: 기록 {blind['current']} → 실측 {len(found)}. "
            f"실측 전수: {sorted(found)}"
        )
        return
    declared_members = blind.get("members")
    if declared_members is not None and sorted(declared_members) != sorted(found):
        axis_report.blind_spot_delta.append(
            "사각 멤버가 어긋납니다.\n"
            f"  기록에만: {sorted(set(declared_members) - set(found))}\n"
            f"  실측에만: {sorted(set(found) - set(declared_members))}"
        )


def _check_review_items(document: dict[str, Any], repo: Repo, report: Report) -> None:
    """축의 멤버가 아니면서 **사람 판정을 요구하는** 사실.

    「비소유」의 실행 규칙은 발견한 결함을 고치지 않고 기록하며 수정 소유 단계를 지목하는
    것이다. 그 기록이 산문 각주로 남으면 늙는다 — 여기서는 소유자와 증거 앵커가 게이트 대상이다.
    """
    items = list(document.get("review_item") or [])
    seen: set[str] = set()
    for item in items:
        item_id = str(item.get("id", "<id 없음>"))
        if item_id in seen:
            report.structural.append(f"판정 요구 항목 id 가 중복입니다: {item_id}")
        seen.add(item_id)
        for field_name in ("id", "subject", "classification", "owner"):
            if not item.get(field_name):
                report.structural.append(f"판정 요구 항목 {item_id}: `{field_name}` 이(가) 없습니다.")
        classification = item.get("classification")
        if classification is not None and classification not in CLASSIFICATIONS:
            report.structural.append(
                f"판정 요구 항목 {item_id}: `classification` 은 소문자 5종 중 하나여야 합니다 — "
                f"{classification!r}"
            )
        owner = item.get("owner")
        if owner and owner not in HANDOFF_SLICES:
            report.structural.append(
                f"판정 요구 항목 {item_id}: 알 수 없는 소유 슬라이스 {owner!r}."
            )
        _check_evidence(item_id, item.get("evidence"), repo, report)
        if classification == "p_review_required":
            review = item.get("p_review")
            if not isinstance(review, dict):
                report.structural.append(
                    f"판정 요구 항목 {item_id}: `p_review_required` 는 5증거 표를 듭니다."
                )
                continue
            for field_name in P_REVIEW_FIELDS:
                value = review.get(field_name)
                if not value:
                    report.structural.append(
                        f"판정 요구 항목 {item_id}: `p_review.{field_name}` 이(가) 공란입니다 — "
                        "「모름」은 공란이 아니라 `unknown` 명시값입니다."
                    )
                elif value == "unknown" or value.startswith("unknown "):
                    report.unknown_evidence += 1


# ──────────────────────────────────────────────────────────────────────────
# 계측
# ──────────────────────────────────────────────────────────────────────────


def _check_metric(
    metric: dict[str, Any],
    repo: Repo,
    axis_members: dict[str, list[str]],
    report: Report,
) -> None:
    metric_id = str(metric.get("id", "<id 없음>"))
    if metric.get("value") is None:
        report.structural.append(f"계측 {metric_id}: `value` 가 없습니다.")
    items: list[tuple[str, dict[str, Any]]] = [(metric_id, metric)]
    for index, alias in enumerate(metric.get("aliases") or [], 1):
        items.append((f"{metric_id}/alias[{index}]", alias))
    for where, item in items:
        if not _require_predicate_triple(f"계측 {where}", item, report):
            continue
        try:
            found = _measure(repo, item["predicate"], tuple(item["scope"]), axis_members)
        except InventoryGateError as exc:
            report.metric_mismatch.append(f"계측 {where}: 재실측 실패 — {exc}")
            continue
        recorded = item.get("value")
        if recorded is None or int(recorded) != len(found):
            report.metric_mismatch.append(
                f"계측 {where}: 기록 {recorded} → 재실측 {len(found)} (술어 {item['predicate']}, "
                f"scope {item['scope']})"
            )


# ──────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────


def load_document(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise InventoryGateError(f"원장이 없습니다: {path}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def check(
    document: dict[str, Any],
    repo_root: Path,
    axes: list[str] | None = None,
    metrics: list[str] | None = None,
) -> Report:
    """원장을 저장소에 재실행한다.

    ``axes``·``metrics`` 는 **음성 대조가 부분 트리를 쓰기 위한** 선택자다. 없는 파일 때문에
    무관한 축이 죽으면 그 음성 대조는 자기가 겨눈 좌표를 증명하지 못한다.
    """
    repo = Repo(repo_root)
    report = Report()

    if document.get("schema") != 1:
        report.structural.append(f"`schema` 가 1 이 아닙니다 — {document.get('schema')!r}")
    for field_name in ("baseline_sha", "scope_statement"):
        if not document.get(field_name):
            report.structural.append(f"머리말 `{field_name}` 이(가) 없습니다.")
    if document.get("repo_wide_metrics") is None:
        report.structural.append(
            "머리말 `repo_wide_metrics` 가 없습니다 — 저장소 전수 scope 계측이 오늘 몇 개인지를 "
            "데이터로 들어야 합니다(0이면 빈 배열)."
        )
    for excluded in document.get("excluded_axes") or []:
        for field_name in ("axis", "reason", "owner"):
            if not excluded.get(field_name):
                report.structural.append(
                    f"제외 축 {excluded.get('axis', '<이름 없음>')}: `{field_name}` 이(가) 없습니다 — "
                    "조용한 유예가 아니라 소리 나는 제외여야 합니다."
                )

    declared_axes = dict(document.get("axes") or {})
    selected_axes = set(declared_axes) if axes is None else set(axes)
    unknown_axes = selected_axes - set(declared_axes)
    if unknown_axes:
        raise InventoryGateError(f"선언되지 않은 축을 골랐습니다: {sorted(unknown_axes)}")

    nodes = list(document.get("node") or [])
    report.node_rows = len(nodes)
    duplicate_ids = sorted(
        name for name, count in Counter(str(node.get("id")) for node in nodes).items() if count > 1
    )
    for name in duplicate_ids:
        report.structural.append(f"노드 id 가 중복입니다: {name}")

    for node in nodes:
        _check_node_shape(node, set(declared_axes), report)
        if node.get("axis") in selected_axes:
            _check_evidence(str(node.get("id")), node.get("evidence"), repo, report)
            if axes is None:
                _check_verification(str(node.get("id")), node.get("verification"), repo, report)

    axis_members: dict[str, list[str]] = {}
    for axis_name in sorted(selected_axes):
        decl = declared_axes[axis_name]
        if not _require_predicate_triple(f"축 {axis_name}", decl, report):
            continue
        try:
            measured = _measure(repo, decl["predicate"], tuple(decl["scope"]))
        except InventoryGateError as exc:
            report.structural.append(f"축 {axis_name}: 재실측 실패 — {exc}")
            continue
        axis_members[axis_name] = measured
        axis_nodes = [node for node in nodes if node.get("axis") == axis_name]
        axis_report = _axis_coverage(axis_name, decl, axis_nodes, measured, repo)
        report.axes[axis_name] = axis_report
        _check_blind_spot(axis_name, decl, repo, axis_members, report, axis_report)

    if axes is None:
        _check_review_items(document, repo, report)

    declared_metrics = list(document.get("metric") or [])
    for metric in declared_metrics:
        if metrics is not None and str(metric.get("id")) not in metrics:
            continue
        _check_metric(metric, repo, axis_members, report)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--document", type=Path, default=DEFAULT_DOCUMENT)
    parser.add_argument("--report", choices=("text", "json"), default="text")
    parser.add_argument("--axis", action="append", dest="axes")
    args = parser.parse_args(argv)

    # 진단이 한국어라 콘솔 기본 코드페이지(cp949)에서는 실패 메시지 자체가 죽는다 —
    # 게이트가 좌표를 말하지 못하면 붉어도 쓸모가 없다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    try:
        document = load_document(args.document)
        report = check(document, args.repo_root.resolve(), axes=args.axes)
    except InventoryGateError as exc:
        print(f"게이트 전제가 깨졌습니다: {exc}", file=sys.stderr)
        return 2

    if args.report == "json":
        print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    else:
        for axis in report.axes.values():
            print(
                f"{axis.axis:26} 측정 {axis.measured:4}  피복 {axis.covered:4}  "
                f"미분류 {len(axis.unclassified):3}  유령 {len(axis.ghost):3}  "
                f"중복 {len(axis.duplicate):3}"
            )
        print(f"노드 행 {report.node_rows} · unknown 증거 {report.unknown_evidence}")
        for failure in report.failures:
            print(f"FAIL {failure}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
