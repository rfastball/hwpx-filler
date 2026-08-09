"""P1-02D transport 축 — screen/action·직접 host 메서드·snapshot·push/event 전수 원장(#516).

React↔Python 경계의 **모든 transport endpoint** 를 실제 Python producer 와 JS 소비자 증거에
연결한다. 정본은 이미 있는 실물이다 — ``webapp/action_registry.py``(화면×액션×payload 키),
``webapp/app.py`` 의 ``WebFrontend`` js_api 공개 표면, ``frontend/js/bridge.js``(제품 JS 의
유일한 호스트 통로, N-07), ``webapp/product_api.py``(Python→웹 이벤트 4채널),
``webapp/selftest_api.py``(시험 전용 별도 계정) — 여기서는 새 어휘를 발명하지 않고 그것들을
**전수로 세고 연결이 닫히는지**를 기계 술어로 만든다.

이 축의 불변식(#516)은 어휘가 아니라 구분이다:

- endpoint 가 **존재한다**는 것과 **실소비자가 있다**는 것을 다른 열로 적는다. dispatch
  증거는 액션 토큰이 아니라 ``(screen, action)`` 발신 쌍에 결속하고, snapshot 증거도 화면별
  제품 모듈 폐포 안의 필드 read 로 결속한다. 소비자 분류(``product``/``selftest_only``/
  ``none_found``)는 그 실측의 요약이다.
- transport DTO 모양(payload 키·snapshot 필드)은 사실로 기록하되 domain 모델로 승격하지
  않는다. 판정은 P1-03 소유다.

커밋 생성물은 02A 규약 그대로 **digest 핀 + 전수 원장**이다: 기반 사실 digest 는 02A 원장의
핀을 그대로 나른다(같은 baseline src/ 스냅숏 — 게이트가 두 원장의 값 일치를 교차 단언한다).
src/ 밖 입력(bridge.js·product_api.js·contract.gen.ts)은 sha256 앵커로 정체를 든다.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import posixpath
import re
import tempfile
import tomllib
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from .schema import FactGraphError
from .static_graph import (
    BASELINE_SHA,
    _baseline_source_problems,
)
from .static_graph import LEDGER_REL_PATH as STATIC_LEDGER_REL_PATH

COLLECTOR = "factgraph.transport_graph"

LEDGER_REL_PATH = "docs/factgraph/transport_graph_02d.toml"
REGEN_COMMAND = "uv run python scripts/gen_transport_graph_02d.py"

#: 소비자 증거를 찾는 프런트 텍스트 코퍼스. ``contract.gen.ts`` 는 registry 에서 **생성**되는
#: 파일이라 제외한다 — 넣으면 모든 액션이 "소비됨"으로 읽혀 관측자가 관측을 오염시킨다.
_FRONTEND_ROOTS = ("frontend/js", "frontend/src")
_FRONTEND_SUFFIXES = (".js", ".ts", ".tsx")
_GENERATED_CONTRACT = "frontend/src/contract/contract.gen.ts"
_SELFTEST_PREFIX = "frontend/src/selftest/"

_BRIDGE_REL_PATH = "frontend/js/bridge.js"
_PRODUCT_API_JS_REL_PATH = "frontend/src/product_api.js"
_BOOTSTRAP_JS_REL_PATH = "frontend/src/bootstrap.js"

#: bridge.js 의 호스트 소비 — ``window.pywebview.api.<이름>(`` 실호출.
_BRIDGE_CONSUME = re.compile(r"window\.pywebview\.api\.(\w+)\(")
#: bridge.js 별칭 정의 — ``jsName(args) { return [unwrapDispatch(]window.pywebview.api.pyName(``.
_BRIDGE_ALIAS = re.compile(
    r"(\w+)\([^)]*\)\s*\{\s*return\s+(?:unwrapDispatch\()?window\.pywebview\.api\.(\w+)\(",
    re.S,
)


# ------------------------------------------------------------------ 원장 행


@dataclass(frozen=True)
class DispatchEndpoint:
    """registry 액션 하나 = dispatch 경로 endpoint 하나."""

    screen: str
    action: str
    required: tuple[str, ...]
    optional: tuple[str, ...]
    zone_mutation: bool
    handler: str  # ``module:Class._do_<action>#method`` — MRO 에서 실제 정의 클래스
    consumer: str  # "product" | "selftest_only" | "none_found"
    js_evidence: tuple[str, ...]  # 액션 이름 인용 리터럴이 실재하는 프런트 파일(FACT)


@dataclass(frozen=True)
class HostMethod:
    """``WebFrontend`` js_api 공개 메서드 하나 = 직접 브리지 endpoint 하나."""

    name: str
    params: tuple[tuple[str, bool], ...]  # (이름, 선택 여부) — 정의 순서
    bridge_alias: str  # bridge.js 별칭. "" = bridge.js 가 부르지 않는다
    consumer: str  # "product" | "host_internal"
    python_consumer: str  # host_internal 의 파이썬 소비자 symbol ("" = 해당 없음)


@dataclass(frozen=True)
class SnapshotField:
    """스냅샷 채널(화면)의 최상위 필드 하나 — producer·consumer 양쪽이 닫힌 사실."""

    screen: str
    field: str
    producer: str  # ``module:Class.snapshot#method``
    runtime_observed: bool  # 빈 상태 initial() 실측에서 보였는가(거짓 = 조건부 방출 선언)
    consumer: str  # "product" | "selftest_only" | "none_found"
    js_evidence: tuple[str, ...]  # 화면에 결속된 모듈 폐포 안의 필드 read 파일


@dataclass(frozen=True)
class SnapshotOracleInventory:
    """독립 snapshot consumer 분모의 불변 측정값.

    원장 행 mutation 여러 개를 같은 source checkout 에 대조할 때 source 측정은 한 번만 한다.
    행을 바꾸는 시험은 이 값을 공유할 수 있지만, source 를 바꾸는 시험은 반드시 다시 잰다.
    """

    rows: tuple[tuple[str, str, tuple[str, ...]], ...]

    def as_dict(self) -> "dict[tuple[str, str], tuple[str, ...]]":
        return {(screen, field): evidence for screen, field, evidence in self.rows}


@dataclass(frozen=True)
class PushChannel:
    """Python→웹 push/event 채널 하나."""

    kind: str  # "product_event" | "partial_push" | "selftest_host_op"
    name: str
    producer: str
    fields: tuple[str, ...]
    consumer_evidence: tuple[str, ...]


@dataclass(frozen=True)
class Enablement:
    """02A 인계 — prefix dispatch 복원 폐포 중 registry 가 실제로 켜는 부분집합."""

    screen: str
    handlers: int
    actions: int
    enabled: int
    dead_handlers: tuple[str, ...]  # ``_do_`` 는 있는데 registry 액션이 없다(소비 불가)
    actions_without_handler: tuple[str, ...]  # registry 가 약속했는데 착지 못 한다(모순 후보)


@dataclass(frozen=True)
class TransportInventory:
    endpoints: tuple[DispatchEndpoint, ...]
    host_methods: tuple[HostMethod, ...]
    bridge_consumed_product: tuple[str, ...]
    bridge_consumed_selftest: tuple[str, ...]
    snapshot_fields: tuple[SnapshotField, ...]
    channels: tuple[PushChannel, ...]
    enablement: tuple[Enablement, ...]
    protocol: str
    version: int
    capabilities: tuple[str, ...]
    python_error_codes: tuple[str, ...]
    js_error_codes: tuple[str, ...]
    rejection_key: str
    rejection_fields: tuple[str, ...]
    input_sha256: tuple[tuple[str, str], ...]  # src/ 밖 입력 파일의 정체 앵커

    @property
    def digest(self) -> str:
        canonical = json.dumps(
            asdict(self), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ 공용 관측


def _assert_probe_matches(repo_root: Path) -> None:
    """import 된 제품이 **이 저장소의 것**인지 실측한다.

    계측기가 다른 사본(설치본·다른 워크트리)을 읽으면 전 계측이 조용히 거짓이 된다 —
    「계측기가 무엇을 읽는가」를 렌더 모델과 함께 옮기지 않은 결함류의 이 축 판본이다.
    """
    import hwpxfiller

    package_file = Path(hwpxfiller.__file__ or "").resolve()
    expected_root = (repo_root / "src" / "hwpxfiller").resolve()
    if not package_file.is_relative_to(expected_root):
        raise FactGraphError(
            f"hwpxfiller import 가 계측 대상 밖이다: {package_file} (기대 루트 {expected_root})"
        )


@contextmanager
def _isolated_home():
    """런타임 프로브의 홈 격리 — 개발자 실설정을 읽지도 쓰지도 않는다(CLAUDE.md 안전망 동형)."""
    prior = os.environ.get("HWPXFILLER_HOME")
    with tempfile.TemporaryDirectory(prefix="factgraph-02d-home-") as home:
        os.environ["HWPXFILLER_HOME"] = home
        try:
            yield Path(home)
        finally:
            if prior is None:
                os.environ.pop("HWPXFILLER_HOME", None)
            else:
                os.environ["HWPXFILLER_HOME"] = prior


def _controller_classes(repo_root: Path) -> "dict[str, type]":
    """화면 id → 컨트롤러 클래스. 정본은 ``WebFrontend.__init__`` 의 실제 배선이다.

    이름 표를 손으로 들지 않는다 — 화면이 늘거나 개명되면 이 사상이 따라 움직여야
    registry 대조가 드리프트를 문다.
    """
    _assert_probe_matches(repo_root)
    from hwpxfiller.webapp.app import WebFrontend

    with _isolated_home() as home:
        frontend = WebFrontend(home / "txt-templates")
        return {screen: type(ctrl) for screen, ctrl in frontend.controllers.items()}


def _runtime_snapshot_fields(repo_root: Path) -> "dict[str, tuple[str, ...]]":
    """빈 상태 ``initial()`` 의 화면별 최상위 필드 실측 — 「항상 방출」의 하한 증거."""
    _assert_probe_matches(repo_root)
    from hwpxfiller.webapp.app import WebFrontend

    with _isolated_home() as home:
        frontend = WebFrontend(home / "txt-templates")
        return {
            screen: tuple(sorted(frontend.initial(screen)))
            for screen in sorted(frontend.controllers)
        }


def _frontend_corpus(repo_root: Path) -> "dict[str, str]":
    corpus: dict[str, str] = {}
    for base in _FRONTEND_ROOTS:
        root = repo_root / base
        if not root.is_dir():
            raise FactGraphError(f"프런트 코퍼스 루트가 없다: {base}")
        for path in sorted(root.rglob("*")):
            if path.suffix not in _FRONTEND_SUFFIXES:
                continue
            rel = path.relative_to(repo_root).as_posix()
            if rel == _GENERATED_CONTRACT:
                continue
            corpus[rel] = path.read_text(encoding="utf-8")
    return corpus


_CONST_STR = re.compile(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*[\"']([\w-]+)[\"']")
_PAIR_SEND = re.compile(
    r"(?:\bcall|\bdispatch)\(\s*([A-Za-z_$][\w$]*|[\"'][\w-]+[\"'])"
    r"\s*,\s*[\"'](\w+)[\"']"
)
_PAIR_FORWARD = re.compile(
    r"(?:\bcall|\bdispatch)\(\s*([A-Za-z_$][\w$]*|[\"'][\w-]+[\"'])"
    r"\s*,\s*action\b"
)
_WRAPPER_DEF = re.compile(r"(?<![.\w$])(\w+)\(([^)]*\baction\b[^)]*)\)[^;{]*\{")


def _javascript_lexical_code(
    text: str, *, preserve_relative_modules: bool = False
) -> str:
    """정적 계측용 JS/TS code view.

    주석과 문자열 **본문**을 regex 입력에서 지우되, 화면/action 인자가 될 수 있는 단순 문자열
    리터럴(``"job"``·``"toggle_group"``)만 보존한다. 길이와 줄바꿈은 원문과 같아서 블록
    위치·진단 위치가 갈리지 않는다. 따라서 문자열 속 ``dispatch("tpl", …)`` 산문이나 주석은
    호출로 승격될 수 없고, 실제 호출의 리터럴 인자는 계속 구조 계측할 수 있다.
    """
    chars = list(text)

    def blank(start: int, end: int) -> None:
        for offset in range(start, end):
            if chars[offset] not in "\r\n":
                chars[offset] = " "

    index = 0
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if char == "/" and nxt == "/":
            end = text.find("\n", index + 2)
            end = len(text) if end < 0 else end
            blank(index, end)
            index = end
            continue
        if char == "/" and nxt == "*":
            close = text.find("*/", index + 2)
            end = len(text) if close < 0 else close + 2
            blank(index, end)
            index = end
            continue
        if char == "/":
            previous_index = index - 1
            while previous_index >= 0 and text[previous_index].isspace():
                previous_index -= 1
            previous = text[previous_index] if previous_index >= 0 else ""
            # JS regex literal이 올 수 있는 식 시작 문맥. 그 본문 속 call-shaped 문자는 코드가 아니다.
            prefix = text[:index].rstrip()
            regex_context = (
                previous == ""
                or previous in "=([{,:;!?&|"
                or prefix.endswith("=>")
                or re.search(r"\b(?:return|throw|yield|case)\s*$", prefix) is not None
                or re.search(
                    r"\b(?:if|while|for|switch|with)\s*\([^;{}]*\)\s*$", prefix
                )
                is not None
                or re.search(r"\b(?:else|do)\s*$", prefix) is not None
            )
            if regex_context:
                end = index + 1
                escaped = False
                in_class = False
                while end < len(text):
                    current = text[end]
                    if escaped:
                        escaped = False
                    elif current == "\\":
                        escaped = True
                    elif current == "[":
                        in_class = True
                    elif current == "]":
                        in_class = False
                    elif current == "/" and not in_class:
                        end += 1
                        while end < len(text) and text[end].isalpha():
                            end += 1
                        break
                    end += 1
                blank(index, end)
                index = end
                continue
        if char == "`":
            template_start = index
            end = index + 1
            escaped = False
            expressions: list[tuple[int, int, str]] = []
            while end < len(text):
                current = text[end]
                if escaped:
                    escaped = False
                    end += 1
                    continue
                if current == "\\":
                    escaped = True
                    end += 1
                    continue
                if current == "`":
                    end += 1
                    break
                if current == "$" and end + 1 < len(text) and text[end + 1] == "{":
                    block = _balanced_block(text, end + 1)
                    close = end + len(block)
                    expression_start = end + 2
                    expressions.append(
                        (
                            expression_start,
                            close,
                            _javascript_lexical_code(
                                text[expression_start:close],
                                preserve_relative_modules=preserve_relative_modules,
                            ),
                        )
                    )
                    end = close + 1
                    continue
                end += 1
            blank(template_start, end)
            for expression_start, expression_end, expression in expressions:
                chars[expression_start:expression_end] = expression
            index = end
            continue
        if char not in "\"'":
            index += 1
            continue
        quote = char
        end = index + 1
        escaped = False
        value: list[str] = []
        while end < len(text):
            current = text[end]
            if escaped:
                value.append(current)
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == quote:
                end += 1
                break
            else:
                value.append(current)
            end += 1
        literal_value = "".join(value)
        simple_literal = re.fullmatch(r"[A-Za-z_$][\w$-]*", literal_value)
        relative_module = (
            re.fullmatch(r"\.{1,2}/[A-Za-z0-9_@./-]+", literal_value)
            if preserve_relative_modules
            else None
        )
        if simple_literal is None and relative_module is None:
            blank(index, end)
        index = end
    return "".join(chars)


def _javascript_import_code(text: str) -> str:
    """import/export graph 전용 code view — 실제 상대 module specifier만 추가 보존."""
    return _javascript_lexical_code(text, preserve_relative_modules=True)


def _dispatch_code_corpus(corpus: "dict[str, str]") -> "dict[str, str]":
    return {rel: _javascript_lexical_code(text) for rel, text in corpus.items()}


def _pool_snapshot_action_domain() -> tuple[str, ...]:
    """``row.actions[].key``의 제품 값-domain — 링1 상태표를 런타임으로 전수 열거한다."""
    from hwpxfiller.core.dataset_pool import STATUS_ACTIVE, STATUS_ARCHIVED
    from hwpxfiller.gui.dataset_pool_state import available_actions

    return tuple(
        sorted(
            {
                action.key
                for status in (STATUS_ACTIVE, STATUS_ARCHIVED)
                for action in available_actions(status)
            }
        )
    )


_DYNAMIC_FIXED_SEND = re.compile(
    r"\b(?:call|dispatch)\(\s*[\"'](?P<screen>[A-Za-z_$][\w$-]*)[\"']"
    r"\s*,\s*(?P<carrier>[A-Za-z_$][\w$]*)\s*,"
)
_PICKER_OPEN_SCREEN = re.compile(
    r"\bdataPicker\s*\.\s*open\(\s*\{\s*screen\s*:\s*"
    r"[\"']([A-Za-z_$][\w$-]*)[\"']"
)
_RELINK_CALL_SCREEN = re.compile(
    r"\.\s*relinkTemplate\(\s*[\"']([A-Za-z_$][\w$-]*)[\"']"
)


def _brace_stack_at(text: str, end: int) -> tuple[int, ...]:
    """lexer-safe code view 의 ``end`` 위치를 감싼 brace stack."""
    stack: list[int] = []
    for index, char in enumerate(text[:end]):
        if char == "{":
            stack.append(index)
        elif char == "}" and stack:
            stack.pop()
    return tuple(stack)


def _visible_assignment_literals(text: str, name: str, send_at: int) -> tuple[str, ...]:
    """동적 발신 위치에서 보이는 가장 가까운 변수 대입의 유한 literal domain.

    같은 파일의 문자열을 전부 주워 담지 않는다. 선언 scope 가 발신 scope 의 조상인 동일
    이름 대입 중 가장 가까운 것 하나만 고르고, 그 우변에 직접 적힌 단순 문자열만 센다.
    """
    declaration = re.compile(
        rf"\b(?:const|let|var)\s+{re.escape(name)}"
        r"(?:\s*:\s*[^=;]+)?\s*=\s*(?P<rhs>[^;]+);"
    )
    send_stack = _brace_stack_at(text, send_at)
    visible: list[re.Match] = []
    for match in declaration.finditer(text, 0, send_at):
        declaration_stack = _brace_stack_at(text, match.start())
        if declaration_stack == send_stack[: len(declaration_stack)]:
            visible.append(match)
    if not visible:
        return ()
    rhs = visible[-1].group("rhs")
    return tuple(
        sorted(set(re.findall(r"[\"']([A-Za-z_$][\w$-]*)[\"']", rhs)))
    )


def _collector_dynamic_dispatch_pairs(
    corpus: "dict[str, str]",
) -> "dict[tuple[str, str], tuple[str, ...]]":
    """제품이 제한한 값 domain 과 동적 dispatch carrier 를 결속한다.

    screen/action 과 무관한 파일 문자열은 어느 경로에서도 domain 이 되지 않는다. 값은 실제
    picker/relink 호출 인자, 발신 위치에서 보이는 대입 우변, 또는 ``row.actions`` 의 Python
    producer 상태표 중 하나에서만 온다.
    """
    from hwpxfiller.webapp.action_registry import ACTION_REGISTRY

    observed: "dict[tuple[str, str], set[str]]" = {}

    def add(screen: str, action: str, *files: str) -> None:
        if screen in ACTION_REGISTRY and action in ACTION_REGISTRY[screen]:
            observed.setdefault((screen, action), set()).update(files)

    picker_screens = [
        (match.group(1), rel)
        for rel, text in corpus.items()
        for match in _PICKER_OPEN_SCREEN.finditer(text)
    ]
    relink_screens = [
        (match.group(1), rel)
        for rel, text in corpus.items()
        for match in _RELINK_CALL_SCREEN.finditer(text)
    ]

    for rel, text in corpus.items():
        if re.search(
            r"\b(?:call|dispatch)\(\s*session\s*\.\s*screen\s*,"
            r"\s*[\"']load_pool[\"']",
            text,
        ):
            for screen, callsite in picker_screens:
                add(screen, "load_pool", rel, callsite)

        target_names = set(
            re.findall(
                r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
                r"relinkScreen\(\s*screen\s*\)",
                text,
            )
        )
        for target in target_names:
            if not re.search(
                rf"\b(?:call|dispatch)\(\s*{re.escape(target)}\s*,"
                r"\s*[\"']relink_template[\"']",
                text,
            ):
                continue
            for screen, callsite in relink_screens:
                add(screen, "relink_template", rel, callsite)

        for send in _DYNAMIC_FIXED_SEND.finditer(text):
            for action in _visible_assignment_literals(
                text, send.group("carrier"), send.start()
            ):
                add(send.group("screen"), action, rel)

        has_pool_action_carrier = re.search(
            r"\b(?:call|dispatch)\(\s*[\"']pool[\"']\s*,\s*action\s*,",
            text,
        )
        has_snapshot_domain = re.search(r"\brow\s*\.\s*actions\b", text) and re.search(
            r"\bpoolAction\(\s*action\s*\.\s*key\b", text
        )
        if has_pool_action_carrier and has_snapshot_domain:
            for action in _pool_snapshot_action_domain():
                add("pool", action, rel)

    return {key: tuple(sorted(files)) for key, files in observed.items()}


def _balanced_block(text: str, open_index: int) -> str:
    """``{`` 위치부터 짝이 맞는 ``}``까지. 문자열·주석 안 중괄호는 세지 않는다."""
    depth = 0
    quote = ""
    escaped = False
    line_comment = False
    block_comment = False
    index = open_index
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and nxt == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            index += 1
            continue
        if char == "/" and nxt == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and nxt == "*":
            block_comment = True
            index += 2
            continue
        if char in "\"'`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_index : index + 1]
        index += 1
    raise FactGraphError("프런트 소스의 중괄호 블록이 닫히지 않았다")


def _screen_of_expr(expr: str, consts: "dict[str, str]") -> "str | None":
    if expr[:1] in "\"'":
        return expr[1:-1]
    return consts.get(expr)


def _action_param_index(params: str) -> "int | None":
    for index, raw in enumerate(params.split(",")):
        if re.split(r"[:=]", raw, maxsplit=1)[0].strip() == "action":
            return index
    return None


def _argument_literal_pattern(name: str, index: int) -> re.Pattern:
    head = rf"(?<![\w$]){re.escape(name)}\(\s*"
    before = r"(?:[^,()\"']*,\s*)" * index
    return re.compile(head + before + r"[\"'](\w+)[\"']")


def _argument_forward_pattern(name: str, index: int) -> re.Pattern:
    head = rf"(?<![\w$]){re.escape(name)}\(\s*"
    before = r"(?:[^,()\"']*,\s*)" * index
    return re.compile(head + before + r"action\b")


@dataclass(frozen=True)
class _DispatchWrapper:
    file: str
    name: str
    action_index: int
    body: str


def _dispatch_wrappers(
    corpus: "dict[str, str]",
) -> "tuple[dict[str, dict[str, tuple[str, int]]], dict[str, tuple[str, int]]]":
    """action wrapper를 파일 지역 우선으로 해소해 ``wrapper(action) → screen``을 얻는다."""
    wrappers: list[_DispatchWrapper] = []
    screens_of: "dict[tuple[str, str], set[str]]" = {}
    index_of: "dict[tuple[str, str], int]" = {}
    for rel, text in corpus.items():
        consts = dict(_CONST_STR.findall(text))
        for match in _WRAPPER_DEF.finditer(text):
            action_index = _action_param_index(match.group(2))
            if action_index is None:
                continue
            key = (rel, match.group(1))
            if key in index_of and index_of[key] != action_index:
                screens_of.setdefault(key, set()).update({"?a", "?b"})
                continue
            body = _balanced_block(text, match.end() - 1)
            index_of[key] = action_index
            wrappers.append(_DispatchWrapper(rel, match.group(1), action_index, body))
            for expr in _PAIR_FORWARD.findall(body):
                screen = _screen_of_expr(expr, consts)
                if screen is not None:
                    screens_of.setdefault(key, set()).add(screen)

    def lookup(file: str, name: str) -> "tuple[set[str], int] | None":
        local = (file, name)
        if local in index_of and len(screens_of.get(local, ())) == 1:
            return set(screens_of[local]), index_of[local]
        candidates = [
            (set(screens), index_of[key])
            for key, screens in screens_of.items()
            if key[1] == name and len(screens) == 1
        ]
        unique = {(next(iter(screens)), index) for screens, index in candidates}
        if len(unique) == 1:
            screen, index = next(iter(unique))
            return {screen}, index
        return None

    changed = True
    while changed:
        changed = False
        for wrapper in wrappers:
            own = (wrapper.file, wrapper.name)
            for known in {key[1] for key in index_of if key != own}:
                resolved = lookup(wrapper.file, known)
                if resolved is None:
                    continue
                screens, index = resolved
                if not _argument_forward_pattern(known, index).search(wrapper.body):
                    continue
                before = set(screens_of.get(own, ()))
                screens_of.setdefault(own, set()).update(screens)
                changed |= screens_of[own] != before

    by_file: "dict[str, dict[str, tuple[str, int]]]" = {}
    for (rel, name), screens in screens_of.items():
        if len(screens) == 1 and not next(iter(screens)).startswith("?"):
            by_file.setdefault(rel, {})[name] = (next(iter(screens)), index_of[(rel, name)])

    global_unique: "dict[str, tuple[str, int]]" = {}
    ambiguous: set[str] = set()
    for entries in by_file.values():
        for name, resolved in entries.items():
            if name in global_unique and global_unique[name] != resolved:
                ambiguous.add(name)
            else:
                global_unique[name] = resolved
    for name in ambiguous:
        global_unique.pop(name, None)
    return by_file, global_unique


def dispatch_pair_evidence(
    repo_root: Path, corpus: "dict[str, str] | None" = None
) -> "dict[tuple[str, str], tuple[str, ...]]":
    """프런트 발신을 정확한 ``(screen, action)`` 후보에 결속한다.

    직접 호출과 wrapper 폐포를 닫되, 화면이나 action의 값 domain을 호출부에서 증명하지
    못하면 증거로 승격하지 않는다. 같은 파일의 무관한 문자열이나 Python producer의 action
    라벨은 JS 발신 쌍의 증거가 아니다.
    """
    from hwpxfiller.webapp.action_registry import ACTION_REGISTRY

    source_corpus = _frontend_corpus(repo_root) if corpus is None else corpus
    corpus = _dispatch_code_corpus(source_corpus)
    by_file, global_unique = _dispatch_wrappers(corpus)
    pairs: "dict[tuple[str, str], set[str]]" = {}

    def add(screen: str, action: str, rel: str) -> None:
        if screen in ACTION_REGISTRY and action in ACTION_REGISTRY[screen]:
            pairs.setdefault((screen, action), set()).add(rel)

    for rel, text in corpus.items():
        consts = dict(_CONST_STR.findall(text))
        for expr, action in _PAIR_SEND.findall(text):
            screen = _screen_of_expr(expr, consts)
            if screen is not None:
                add(screen, action, rel)

        wrappers = {**global_unique, **by_file.get(rel, {})}
        for name, (screen, index) in wrappers.items():
            for match in _argument_literal_pattern(name, index).finditer(text):
                add(screen, match.group(1), rel)

    for pair, files in _collector_dynamic_dispatch_pairs(corpus).items():
        pairs.setdefault(pair, set()).update(files)

    return {key: tuple(sorted(files)) for key, files in pairs.items()}


def _dispatch_pair_oracle(
    repo_root: Path, corpus: "dict[str, str] | None" = None
) -> "dict[tuple[str, str], tuple[str, ...]]":
    """endpoint gate의 별도 구조 열거 — 수집기의 동적 후보 추론을 재사용하지 않는다."""
    from hwpxfiller.webapp.action_registry import ACTION_REGISTRY

    source_corpus = _frontend_corpus(repo_root) if corpus is None else corpus
    corpus = _dispatch_code_corpus(source_corpus)
    direct = re.compile(
        r"\b(?:call|dispatch)\(\s*([A-Za-z_$][\w$]*|[\"'][\w-]+[\"'])"
        r"\s*,\s*[\"']([A-Za-z_$][\w$]*)[\"']"
    )
    definition = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)\(([^)]*)\)[^;{]*\{")
    forward = re.compile(
        r"\b(?:call|dispatch)\(\s*([A-Za-z_$][\w$]*|[\"'][\w-]+[\"'])"
        r"\s*,\s*action\b"
    )
    candidates: list[tuple[str, str, int, str]] = []
    local_wrappers: "dict[str, dict[str, tuple[str, int]]]" = {}
    for rel, text in corpus.items():
        constants = dict(_CONST_STR.findall(text))
        for match in definition.finditer(text):
            params = [re.split(r"[:=]", raw, maxsplit=1)[0].strip() for raw in match.group(2).split(",")]
            if "action" not in params:
                continue
            body = _balanced_block(text, match.end() - 1)
            action_index = params.index("action")
            candidates.append((rel, match.group(1), action_index, body))
            screens = {
                screen
                for expr in forward.findall(body)
                if (screen := _screen_of_expr(expr, constants)) in ACTION_REGISTRY
            }
            if len(screens) != 1:
                continue
            resolved = (next(iter(screens)), action_index)
            local_wrappers.setdefault(rel, {})[match.group(1)] = resolved

    def globals_now() -> "dict[str, tuple[str, int]]":
        values: "dict[str, set[tuple[str, int]]]" = {}
        for entries in local_wrappers.values():
            for name, resolved in entries.items():
                values.setdefault(name, set()).add(resolved)
        return {
            name: next(iter(resolved))
            for name, resolved in values.items()
            if len(resolved) == 1
        }

    changed = True
    while changed:
        changed = False
        global_wrappers = globals_now()
        for rel, name, action_index, body in candidates:
            if name in local_wrappers.get(rel, {}):
                continue
            screens: set[str] = set()
            known = {**global_wrappers, **local_wrappers.get(rel, {})}
            for target, (screen, target_index) in known.items():
                prefix = (
                    rf"(?<![\w$]){re.escape(target)}\(\s*"
                    + r"(?:[^,()\"']*,\s*)" * target_index
                )
                if re.search(prefix + r"action\b", body):
                    screens.add(screen)
            if len(screens) == 1:
                local_wrappers.setdefault(rel, {})[name] = (
                    next(iter(screens)),
                    action_index,
                )
                changed = True
    global_wrappers = globals_now()

    observed: "dict[tuple[str, str], set[str]]" = {}

    def add(screen: str, action: str, *files: str) -> None:
        if screen in ACTION_REGISTRY and action in ACTION_REGISTRY[screen]:
            observed.setdefault((screen, action), set()).update(files)

    for rel, text in corpus.items():
        constants = dict(_CONST_STR.findall(text))
        for expression, action in direct.findall(text):
            screen = _screen_of_expr(expression, constants)
            if screen is not None:
                add(screen, action, rel)
        wrappers = {**global_wrappers, **local_wrappers.get(rel, {})}
        for name, (screen, index) in wrappers.items():
            prefix = rf"(?<![\w$]){re.escape(name)}\(\s*" + r"(?:[^,()\"']*,\s*)" * index
            for invocation in re.finditer(prefix + r"[\"']([A-Za-z_$][\w$]*)[\"']", text):
                add(screen, invocation.group(1), rel)

    # 수집기와 다른 분모: named function body, 제품 port 호출부, snapshot carrier 를 각각
    # 직접 열거한다. 입력은 위 lexer-safe code view 라 주석/문자열 속 call-shaped 산문이
    # 오라클 분모에 들어오지 않는다.
    named_function = re.compile(
        r"\b(?:async\s+)?function\s+[A-Za-z_$][\w$]*\s*\([^)]*\)"
        r"\s*(?::\s*[^={]+)?\s*\{"
    )
    variable_send = re.compile(
        r"\b(?:call|dispatch)\(\s*[\"']([A-Za-z_$][\w$-]*)[\"']"
        r"\s*,\s*([A-Za-z_$][\w$]*)\s*,"
    )
    picker_domains = [
        (match.group(1), rel)
        for rel, text in corpus.items()
        for match in re.finditer(
            r"\bdataPicker\.open\(\s*\{\s*screen\s*:\s*"
            r"[\"']([A-Za-z_$][\w$-]*)[\"']",
            text,
        )
    ]
    relink_domains = [
        (match.group(1), rel)
        for rel, text in corpus.items()
        for match in re.finditer(
            r"\.relinkTemplate\(\s*[\"']([A-Za-z_$][\w$-]*)[\"']", text
        )
    ]
    for rel, text in corpus.items():
        if re.search(
            r"\bdispatch\(\s*session\.screen\s*,\s*[\"']load_pool[\"']", text
        ):
            for screen, callsite in picker_domains:
                add(screen, "load_pool", rel, callsite)

        for target in re.findall(
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
            r"relinkScreen\(\s*screen\s*\)",
            text,
        ):
            if re.search(
                rf"\bdispatch\(\s*{re.escape(target)}\s*,"
                r"\s*[\"']relink_template[\"']",
                text,
            ):
                for screen, callsite in relink_domains:
                    add(screen, "relink_template", rel, callsite)

        for function in named_function.finditer(text):
            body = _balanced_block(text, function.end() - 1)
            for screen, carrier in variable_send.findall(body):
                declarations = re.findall(
                    rf"\b(?:const|let|var)\s+{re.escape(carrier)}"
                    r"(?:\s*:\s*[^=;]+)?\s*=\s*([^;]+);",
                    body,
                )
                for rhs in declarations:
                    for action in re.findall(
                        r"[\"']([A-Za-z_$][\w$-]*)[\"']", rhs
                    ):
                        add(screen, action, rel)

        product_pool_carrier = re.search(
            r"\bdispatch\(\s*[\"']pool[\"']\s*,\s*action\s*,", text
        )
        product_pool_domain = re.search(r"\brow\.actions\b", text) and re.search(
            r"\bpoolAction\(\s*action\.key\b", text
        )
        if product_pool_carrier and product_pool_domain:
            for action in _pool_snapshot_action_domain():
                add("pool", action, rel)
    return {key: tuple(sorted(files)) for key, files in observed.items()}


def _classify_consumer(evidence: tuple[str, ...]) -> str:
    if any(not rel.startswith(_SELFTEST_PREFIX) for rel in evidence):
        return "product"
    if evidence:
        return "selftest_only"
    return "none_found"


def _method_symbol(cls: type, name: str) -> str:
    """``name`` 이 실제로 정의된 MRO 클래스의 symbol id — 소유를 상속으로 뭉개지 않는다."""
    for owner in cls.__mro__:
        if name in vars(owner):
            return f"{owner.__module__}:{owner.__qualname__}.{name}#method"
    raise FactGraphError(f"{cls.__qualname__} MRO 에 {name!r} 정의가 없다")


# ------------------------------------------------------------ dispatch 경로


def collect_endpoints(
    repo_root: Path, *, controllers: "dict[str, type] | None" = None
) -> tuple[tuple[DispatchEndpoint, ...], tuple[Enablement, ...]]:
    from hwpxfiller.webapp.action_registry import ACTION_REGISTRY, ZONE_MUTATIONS

    controllers = _controller_classes(repo_root) if controllers is None else controllers
    if sorted(ACTION_REGISTRY) != sorted(controllers):
        raise FactGraphError(
            f"registry 화면과 배선된 컨트롤러가 다르다: {sorted(ACTION_REGISTRY)} ≠ "
            f"{sorted(controllers)}"
        )
    corpus = _frontend_corpus(repo_root)
    evidence_by_pair = dispatch_pair_evidence(repo_root, corpus)
    endpoints: list[DispatchEndpoint] = []
    enablement: list[Enablement] = []
    for screen in sorted(ACTION_REGISTRY):
        cls = controllers[screen]
        handlers = {n[len("_do_") :] for n in dir(cls) if n.startswith("_do_")}
        actions = set(ACTION_REGISTRY[screen])
        enablement.append(
            Enablement(
                screen=screen,
                handlers=len(handlers),
                actions=len(actions),
                enabled=len(handlers & actions),
                dead_handlers=tuple(sorted(handlers - actions)),
                actions_without_handler=tuple(sorted(actions - handlers)),
            )
        )
        for action in sorted(ACTION_REGISTRY[screen]):
            schema = ACTION_REGISTRY[screen][action]
            evidence = evidence_by_pair.get((screen, action), ())
            handler = _method_symbol(cls, f"_do_{action}") if action in handlers else ""
            endpoints.append(
                DispatchEndpoint(
                    screen=screen,
                    action=action,
                    required=tuple(sorted(schema.required)),
                    optional=tuple(sorted(schema.optional)),
                    zone_mutation=action in ZONE_MUTATIONS,
                    handler=handler,
                    consumer=_classify_consumer(evidence),
                    js_evidence=evidence,
                )
            )
    return tuple(endpoints), tuple(enablement)


# ------------------------------------------------------ 직접 host 메서드 경로


def _bridge_source(repo_root: Path) -> str:
    return (repo_root / _BRIDGE_REL_PATH).read_text(encoding="utf-8")


def bridge_consumption(bridge_source: str) -> "tuple[tuple[str, ...], tuple[str, ...]]":
    """bridge.js 가 실제로 부르는 호스트 메서드 — (제품, 시험 전용)."""
    consumed = sorted(set(_BRIDGE_CONSUME.findall(bridge_source)))
    product = tuple(n for n in consumed if not n.startswith("selftest_"))
    selftest = tuple(n for n in consumed if n.startswith("selftest_"))
    return product, selftest


def bridge_aliases(bridge_source: str) -> "dict[str, str]":
    """python 메서드 이름 → bridge.js 별칭."""
    aliases: dict[str, str] = {}
    for js_name, py_name in _BRIDGE_ALIAS.findall(bridge_source):
        aliases[py_name] = js_name
    return aliases


def _internal_python_consumers(repo_root: Path, method: str) -> tuple[str, ...]:
    """``WebFrontend`` 안에서 ``self.<method>()`` 를 부르는 메서드 — host-internal 의 소비자."""
    tree = ast.parse(
        (repo_root / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(encoding="utf-8")
    )
    cls = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "WebFrontend"),
        None,
    )
    if cls is None:
        raise FactGraphError("app.py 에서 WebFrontend 를 찾지 못했다")
    consumers: list[str] = []
    for node in cls.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == method
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "self"
            ):
                consumers.append(f"hwpxfiller.webapp.app:WebFrontend.{node.name}#method")
                break
    return tuple(sorted(set(consumers)))


def collect_host_methods(repo_root: Path) -> tuple[HostMethod, ...]:
    import gen_bridge_contract  # scripts/ 동거 모듈 — factgraph 가 import 가능하면 함께 가능하다

    contract = gen_bridge_contract.extract_app_contract(
        (repo_root / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(encoding="utf-8")
    )
    bridge_source = _bridge_source(repo_root)
    product_consumed, _selftest = bridge_consumption(bridge_source)
    aliases = bridge_aliases(bridge_source)
    rows: list[HostMethod] = []
    for name, params in contract.methods:
        consumed = name in product_consumed
        python_consumer = ""
        if not consumed:
            internal = _internal_python_consumers(repo_root, name)
            python_consumer = " ".join(internal)
        rows.append(
            HostMethod(
                name=name,
                params=tuple(params),
                bridge_alias=aliases.get(name, ""),
                consumer="product" if consumed else "host_internal",
                python_consumer=python_consumer,
            )
        )
    return tuple(rows)


# ------------------------------------------------------------ snapshot 채널


def _class_def(module_path: Path, qualname: str) -> ast.ClassDef:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == qualname:
            return node
    raise FactGraphError(f"{module_path.name} 에 클래스 {qualname!r} 가 없다")


def _dict_literal_keys(node: ast.expr) -> "list[str]":
    if not isinstance(node, ast.Dict):
        return []
    keys: list[str] = []
    for key in node.keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.append(key.value)
    return keys


def _static_snapshot_keys(repo_root: Path, cls: type) -> tuple[str, ...]:
    """``snapshot()`` 이 방출**할 수 있는** 최상위 키의 정적 합집합.

    빈 상태 실측만 들면 조건부 방출(작업대 열림의 ``fmt_options`` 등)이 조용히 빠진다 —
    선언(코드가 놓는 키)과 실측(빈 상태에서 보인 키)을 둘 다 들고, 실측이 선언을 넘으면
    추출기 자신이 틀린 것이므로 render 가 시끄럽게 죽는다(계측기 완전성 오러클).
    """
    owner = next(c for c in cls.__mro__ if "snapshot" in vars(c))
    module_path = repo_root / ("src/" + owner.__module__.replace(".", "/") + ".py")
    class_node = _class_def(module_path, owner.__qualname__)
    fn = next(
        (n for n in class_node.body if isinstance(n, ast.FunctionDef) and n.name == "snapshot"),
        None,
    )
    if fn is None:
        raise FactGraphError(f"{owner.__qualname__}.snapshot 정의를 찾지 못했다")

    returned: set[str] = set()
    keys: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Name):
            returned.add(node.value.id)
    for node in ast.walk(fn):
        if isinstance(node, ast.Return):
            keys.update(_dict_literal_keys(node.value) if node.value is not None else [])
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in returned:
                keys.update(_dict_literal_keys(node.value))
            elif (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id in returned
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)
            ):
                keys.add(target.slice.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in returned and node.value is not None:
                keys.update(_dict_literal_keys(node.value))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in returned
            and node.args
        ):
            keys.update(_dict_literal_keys(node.args[0]))
    if not keys:
        raise FactGraphError(f"{owner.__qualname__}.snapshot 에서 키를 하나도 못 읽었다")
    return tuple(sorted(keys))


_MODEL_CALL = re.compile(
    r"\.model(?:<[^;()]*>)?\(\s*([\"'][^\"']+[\"']|[A-Za-z_$][\w$]*)\s*\)"
)
_RELATIVE_IMPORT = re.compile(
    r"(?ms)^\s*(?:import|export)\s+(?!type\b)(?:(?:(?!;).)*?\s+from\s+)?"
    r"[\"'](\.[^\"']+)[\"']\s*;"
)
_VALUE_IMPORT = re.compile(
    r"(?ms)^\s*import\s+(?!type\b)((?:(?!;).)*?)\s+from\s+"
    r"[\"'](\.[^\"']+)[\"']\s*;"
)


def _resolve_relative_module(
    corpus: "dict[str, str]", importer: str, specifier: str
) -> "str | None":
    base = posixpath.normpath(
        posixpath.join(str(PurePosixPath(importer).parent), specifier)
    )
    stem, suffix = posixpath.splitext(base)
    candidates = [base]
    if suffix in _FRONTEND_SUFFIXES:
        candidates.extend(stem + candidate for candidate in _FRONTEND_SUFFIXES)
    else:
        candidates.extend(base + candidate for candidate in _FRONTEND_SUFFIXES)
        candidates.extend(
            posixpath.join(base, "index" + candidate) for candidate in _FRONTEND_SUFFIXES
        )
    return next((candidate for candidate in candidates if candidate in corpus), None)


def _declared_screen_models(text: str, screens: "set[str]") -> "set[str]":
    code = _javascript_lexical_code(text)
    constants = dict(_CONST_STR.findall(code))
    declared: set[str] = set()
    for expression in _MODEL_CALL.findall(code):
        if expression[:1] in {"\"", "'"}:
            screen = expression[1:-1]
        else:
            screen = constants.get(expression, "")
        if screen in screens:
            declared.add(screen)
    return declared


def _screen_consumer_modules(
    corpus: "dict[str, str]", screens: "set[str]"
) -> "dict[str, tuple[str, ...]]":
    """``runtime.model(screen)`` 구독 root의 제품 relative-import 폐포."""
    product = {
        rel: text
        for rel, text in corpus.items()
        if rel.startswith("frontend/src/") and not rel.startswith(_SELFTEST_PREFIX)
    }
    lexical = {rel: _javascript_import_code(text) for rel, text in product.items()}
    roots: "dict[str, set[str]]" = {screen: set() for screen in screens}
    for rel, text in lexical.items():
        for screen in _declared_screen_models(text, screens):
            roots[screen].add(rel)

    imports: "dict[str, tuple[str, ...]]" = {}
    for rel, text in lexical.items():
        resolved = {
            target
            for specifier in _RELATIVE_IMPORT.findall(text)
            if (target := _resolve_relative_module(product, rel, specifier)) is not None
        }
        imports[rel] = tuple(sorted(resolved))

    closures: "dict[str, tuple[str, ...]]" = {}
    for screen, screen_roots in roots.items():
        seen: set[str] = set()
        pending = list(screen_roots)
        while pending:
            rel = pending.pop()
            if rel in seen:
                continue
            seen.add(rel)
            pending.extend(target for target in imports.get(rel, ()) if target not in seen)

        # 화면 root가 내보낸 snapshot hook을 가져다 그리는 sibling도 소비자다. 모든 reverse
        # importer를 닫으면 product_screens.ts 같은 여러 화면 aggregator가 화면 폐포를 합쳐
        # 버리므로, 값 import가 ``*Snapshot`` symbol을 명시한 모듈만 한 홉 포함한다.
        for importer, text in lexical.items():
            if importer in seen:
                continue
            for clause, specifier in _VALUE_IMPORT.findall(text):
                target = _resolve_relative_module(product, importer, specifier)
                if target in seen and re.search(r"\buse[A-Za-z_$][\w$]*Snapshot\b", clause):
                    seen.add(importer)
                    break
        closures[screen] = tuple(sorted(seen))
    return closures


def _imported_value_symbols(clause: str) -> "set[str] | None":
    """named import의 원래 export 이름. ``None``은 default/namespace라 파일 전체."""
    match = re.search(r"\{(.*)\}", clause, re.S)
    if match is None:
        return None
    names: set[str] = set()
    for raw in match.group(1).split(","):
        item = re.sub(r"^\s*type\s+", "", raw).strip()
        if not item:
            continue
        names.add(re.split(r"\s+as\s+", item, maxsplit=1)[0].strip())
    return names


def _module_function_blocks(text: str) -> "dict[str, str]":
    code = _javascript_lexical_code(text)
    blocks: dict[str, str] = {}
    pattern = re.compile(
        r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+"
        r"([A-Za-z_$][\w$]*)\s*\([^)]*\)[^{;]*\{"
    )
    for match in pattern.finditer(code):
        body = _balanced_block(code, match.end() - 1)
        blocks[match.group(1)] = code[match.start() : match.end() - 1] + body
    return blocks


def _dependency_symbol_source(text: str, imported: "set[str]") -> str:
    """실제로 import한 함수와 그 함수가 부르는 같은-module helper의 폐포만 남긴다."""
    blocks = _module_function_blocks(text)
    selected: set[str] = set()
    pending = list(imported)
    while pending:
        name = pending.pop()
        if name in selected or name not in blocks:
            continue
        selected.add(name)
        body = blocks[name]
        pending.extend(
            called
            for called in re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", body)
            if called in blocks and called not in selected
        )
    return "\n".join(blocks[name] for name in sorted(selected))


def _snapshot_screen_sources(
    corpus: "dict[str, str]", closures: "dict[str, tuple[str, ...]]", screen: str
) -> "dict[str, str]":
    """root/reverse hook는 전부, dependency는 실제 imported export 폐포만."""
    modules = set(closures.get(screen, ()))
    roots = {
        rel for rel in modules if screen in _declared_screen_models(corpus[rel], {screen})
    }
    lexical = {rel: _javascript_import_code(corpus[rel]) for rel in modules}
    reverse_hooks = {
        rel
        for rel in modules - roots
        if any(
            re.search(r"\buse[A-Za-z_$][\w$]*Snapshot\b", clause)
            for clause, _specifier in _VALUE_IMPORT.findall(lexical[rel])
        )
    }
    imports_by_target: "dict[str, set[str] | None]" = {}
    for importer in modules:
        for clause, specifier in _VALUE_IMPORT.findall(lexical[importer]):
            target = _resolve_relative_module(corpus, importer, specifier)
            if target not in modules:
                continue
            names = _imported_value_symbols(clause)
            if names is None or imports_by_target.get(target) is None and target in imports_by_target:
                imports_by_target[target] = None
            elif target not in imports_by_target:
                imports_by_target[target] = set(names)
            else:
                assert imports_by_target[target] is not None
                imports_by_target[target].update(names)

    sources: dict[str, str] = {}
    for rel in sorted(modules):
        if rel in roots or rel in reverse_hooks:
            sources[rel] = corpus[rel]
            continue
        imported = imports_by_target.get(rel)
        if imported is None:
            if rel in imports_by_target:
                sources[rel] = corpus[rel]
            continue
        scoped = _dependency_symbol_source(corpus[rel], imported)
        if scoped:
            sources[rel] = scoped
    return sources


_SNAPSHOT_ASSIGNMENT = re.compile(
    r"(?ms)\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*((?:(?!;).)*)\s*;"
)
_ProductBinding = tuple[str, int, tuple[int, ...], str]


def _direct_product_snapshot_rhs(rhs: str) -> bool:
    """alias RHS 전체가 snapshot source call일 때만 참 — nested alias/호출은 제외."""
    expression = rhs.strip()
    get_snapshot = re.fullmatch(
        r"(?:await\s+)?[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*"
        r"\s*\.\s*getSnapshot\s*\([^;{}]*\)",
        expression,
        re.S,
    )
    hook_snapshot = re.fullmatch(
        r"(?:await\s+)?(?:snapshot|fullSnapshot|useJob|use[A-Za-z_$][\w$]*Snapshot)"
        r"\s*\([^;{}]*\)",
        expression,
        re.S,
    )
    subscribed_model = re.fullmatch(
        r"useSyncExternalStore\s*\((?s:.*)\)", expression
    ) and re.search(r"(?:\.model\.|poolModel\b)", expression)
    return get_snapshot is not None or hook_snapshot is not None or bool(subscribed_model)


def _nearest_product_binding(
    bindings: "list[_ProductBinding]", name: str, at: int, scope: tuple[int, ...]
) -> "_ProductBinding | None":
    visible = [
        binding
        for binding in bindings
        if binding[0] == name
        and binding[1] < at
        and binding[2] == scope[: len(binding[2])]
    ]
    if not visible:
        return None
    return max(visible, key=lambda binding: (len(binding[2]), binding[1]))


def _product_snapshot_field_access(source: str, field: str) -> bool:
    """제품 snapshot alias/parameter와 field access를 같은 lexical scope에 결속한다."""
    code = _javascript_lexical_code(source)
    bindings: list[_ProductBinding] = []
    for match in _SNAPSHOT_ASSIGNMENT.finditer(code):
        name, rhs = match.groups()
        kind = "snapshot" if _direct_product_snapshot_rhs(rhs) else ""
        bindings.append((name, match.start(), _brace_stack_at(code, match.start()), kind))

    function_pattern = re.compile(
        r"\b(?:export\s+)?(?:async\s+)?function\s+[A-Za-z_$][\w$]*"
        r"\s*\((?P<params>[^)]*)\)\s*(?::\s*[^\{]+)?\s*\{"
    )
    for function in function_pattern.finditer(code):
        params = function.group("params")
        scope = _brace_stack_at(code, function.end())
        for raw_param in params.split(","):
            name_match = re.match(r"\s*([A-Za-z_$][\w$]*)", raw_param)
            if name_match is None:
                continue
            name = name_match.group(1)
            kind = "snapshot" if name == "snapshot" else ""
            if name != "snapshot" and re.search(r"\bsnapshot\s*:", raw_param):
                kind = "container"
            bindings.append((name, function.end() - 1, scope, kind))

    destructuring = re.compile(
        r"\b(?:const|let|var)\s*\{(?P<items>[^}]*)\}\s*=\s*"
        r"(?P<source>[A-Za-z_$][\w$]*)\s*;"
    )
    for declaration in destructuring.finditer(code):
        scope = _brace_stack_at(code, declaration.start())
        source_binding = _nearest_product_binding(
            bindings, declaration.group("source"), declaration.start(), scope
        )
        for raw_item in declaration.group("items").split(","):
            item = raw_item.strip()
            if not item:
                continue
            parts = [part.strip() for part in item.split(":", maxsplit=1)]
            exported = parts[0]
            local = parts[-1].split("=", maxsplit=1)[0].strip()
            if not re.fullmatch(r"[A-Za-z_$][\w$]*", local):
                continue
            kind = ""
            if (
                exported == "snapshot"
                and source_binding is not None
                and source_binding[3] == "container"
            ):
                kind = "snapshot"
            bindings.append((local, declaration.start(), scope, kind))

    token = re.escape(field)
    alias_access = re.compile(
        rf"(?<![\w$])([A-Za-z_$][\w$]*)\s*(?:\?\.|\.)\s*{token}\b"
        rf"|(?<![\w$])([A-Za-z_$][\w$]*)\s*\[\s*[\"']{token}[\"']\s*\]"
    )
    for access in alias_access.finditer(code):
        name = access.group(1) or access.group(2)
        binding = _nearest_product_binding(
            bindings, name, access.start(), _brace_stack_at(code, access.start())
        )
        if binding is not None and binding[3] == "snapshot":
            return True

    container_access = re.compile(
        rf"(?<![\w$])([A-Za-z_$][\w$]*)\s*(?:\?\.|\.)\s*snapshot"
        rf"\s*(?:\?\.|\.)\s*{token}\b"
    )
    for access in container_access.finditer(code):
        binding = _nearest_product_binding(
            bindings,
            access.group(1),
            access.start(),
            _brace_stack_at(code, access.start()),
        )
        if binding is not None and binding[3] == "container":
            return True

    direct_call = re.compile(
        rf"(?<![\w$])(?:snapshot|fullSnapshot|useJob|use[A-Za-z_$][\w$]*Snapshot)"
        rf"\s*\([^;{{}}]*?\)\s*(?:\?\.|\.)\s*{token}\b"
    )
    return direct_call.search(code) is not None


def _snapshot_field_evidence(
    corpus: "dict[str, str]", closures: "dict[str, tuple[str, ...]]", screen: str, field: str
) -> tuple[str, ...]:
    """화면 구독 폐포 안에서만 최상위 필드 read 표기를 찾는다."""
    sources = _snapshot_screen_sources(corpus, closures, screen)
    return tuple(
        rel for rel, source in sources.items() if _product_snapshot_field_access(source, field)
    )


_ScopedAssignment = tuple[str, str, int, tuple[int, ...]]


def _scoped_assignments(code: str) -> tuple[_ScopedAssignment, ...]:
    return tuple(
        (match.group(1), match.group(2), match.start(), _brace_stack_at(code, match.start()))
        for match in _SNAPSHOT_ASSIGNMENT.finditer(code)
    )


def _nearest_scoped_assignment(
    assignments: tuple[_ScopedAssignment, ...], name: str, at: int, scope: tuple[int, ...]
) -> "_ScopedAssignment | None":
    visible = [
        assignment
        for assignment in assignments
        if assignment[0] == name
        and assignment[2] < at
        and assignment[3] == scope[: len(assignment[3])]
    ]
    if not visible:
        return None
    return max(visible, key=lambda assignment: (len(assignment[3]), assignment[2]))


def _finite_selftest_state_domains(
    code: str, assignments: tuple[_ScopedAssignment, ...]
) -> "dict[str, set[str]]":
    """``initial(key) -> store[key] -> ctx.state.prop``의 유한 screen domain."""
    loop_pattern = re.compile(
        r"\[(?P<domain>(?:\s*[\"'][A-Za-z_$][\w$-]*[\"']\s*,?)+)\]"
        r"\s*\.\s*forEach\(\s*\(?\s*(?P<key>[A-Za-z_$][\w$]*)\s*\)?"
        r"\s*=>\s*\{"
    )
    state_domains: "dict[str, set[str]]" = {}
    for loop in loop_pattern.finditer(code):
        domain_text = loop.group("domain")
        residue = re.sub(r"[\"'][A-Za-z_$][\w$-]*[\"']|[\s,]", "", domain_text)
        if residue:
            continue
        screens = set(re.findall(r"[\"']([A-Za-z_$][\w$-]*)[\"']", domain_text))
        if not screens:
            continue
        key = loop.group("key")
        body = _balanced_block(code, loop.end() - 1)
        if not re.search(
            rf"\b(?:initial|loadInitial)\(\s*{re.escape(key)}\s*\)", body
        ):
            continue
        stores = set(
            re.findall(
                rf"\b([A-Za-z_$][\w$]*)\s*\[\s*{re.escape(key)}\s*\]\s*=",
                body,
            )
        )
        loop_scope = _brace_stack_at(code, loop.start())
        for store in stores:
            binding = _nearest_scoped_assignment(assignments, store, loop.start(), loop_scope)
            if binding is None:
                continue
            state_write = re.compile(
                r"\b[A-Za-z_$][\w$]*\s*\.\s*state\s*\.\s*"
                r"([A-Za-z_$][\w$]*)\s*=\s*"
                + re.escape(store)
                + r"\b"
            )
            for write in state_write.finditer(code):
                write_scope = _brace_stack_at(code, write.start())
                visible = _nearest_scoped_assignment(
                    assignments, store, write.start(), write_scope
                )
                if visible is not None and visible[2] == binding[2]:
                    state_domains.setdefault(write.group(1), set()).update(screens)
    return state_domains


def _selftest_snapshot_screens_by_assignment(
    code: str, assignments: tuple[_ScopedAssignment, ...]
) -> "dict[int, str]":
    """직접 literal probe와 유한 state store에서 유래한 alias의 screen 귀속."""
    state_domains = _finite_selftest_state_domains(code, assignments)
    store_domains: "dict[int, set[str]]" = {}
    for _name, rhs, position, _scope in assignments:
        state_read = re.search(
            r"\b[A-Za-z_$][\w$]*\s*\.\s*state\s*\.\s*([A-Za-z_$][\w$]*)\b",
            rhs,
        )
        if state_read is not None and state_read.group(1) in state_domains:
            store_domains[position] = state_domains[state_read.group(1)]

    screens: dict[int, str] = {}
    for _name, rhs, position, scope in assignments:
        direct = re.search(
            r"\b(?:[A-Za-z_$][\w$]*\s*\.\s*)+"
            r"(?:initial|loadInitial|model)\(\s*[\"']([A-Za-z_$][\w$-]*)[\"']\s*\)",
            rhs,
        )
        if direct is not None:
            screens[position] = direct.group(1)
            continue
        stored = re.search(
            r"\b([A-Za-z_$][\w$]*)\s*(?:\.\s*([A-Za-z_$][\w$-]*)"
            r"|\[\s*[\"']([A-Za-z_$][\w$-]*)[\"']\s*\])",
            rhs,
        )
        if stored is None:
            continue
        store = _nearest_scoped_assignment(assignments, stored.group(1), position, scope)
        screen = stored.group(2) or stored.group(3)
        if store is not None and screen in store_domains.get(store[2], set()):
            screens[position] = screen
    return screens


def _snapshot_selftest_inventory(
    corpus: "dict[str, str]",
) -> "dict[tuple[str, str], tuple[str, ...]]":
    """selftest snapshot access 전부를 파일당 한 번의 scope 해석으로 역색인한다."""
    evidence: "dict[tuple[str, str], set[str]]" = {}
    for rel, text in corpus.items():
        if not rel.startswith(_SELFTEST_PREFIX):
            continue
        code = _javascript_lexical_code(text)
        assignments = _scoped_assignments(code)
        screens = _selftest_snapshot_screens_by_assignment(code, assignments)
        names = {assignment[0] for assignment in assignments if assignment[2] in screens}
        if not names:
            continue
        receivers = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
        access = re.compile(
            rf"(?<![\w$])({receivers})\s*(?:\?\.|\.)\s*"
            r"([A-Za-z_$][\w$-]*)\b"
            rf"|(?<![\w$])({receivers})\s*\[\s*[\"']"
            r"([A-Za-z_$][\w$-]*)[\"']\s*\]"
        )
        for read in access.finditer(code):
            name = read.group(1) or read.group(3)
            field = read.group(2) or read.group(4)
            scope = _brace_stack_at(code, read.start())
            binding = _nearest_scoped_assignment(assignments, name, read.start(), scope)
            if binding is not None and (screen := screens.get(binding[2])) is not None:
                evidence.setdefault((screen, field), set()).add(rel)
    return {key: tuple(sorted(files)) for key, files in evidence.items()}


def _snapshot_selftest_evidence(
    corpus: "dict[str, str]", screen: str, field: str
) -> tuple[str, ...]:
    """selftest에서 lexical scope와 유한 state store에 결속된 필드 access."""
    return _snapshot_selftest_inventory(corpus).get((screen, field), ())


def _snapshot_oracle_selftest_inventory(
    raw: "dict[str, str]",
) -> "dict[tuple[str, str], tuple[str, ...]]":
    """collector helper와 별개로 selftest snapshot access 전부를 scope 역색인한다."""
    evidence: "dict[tuple[str, str], set[str]]" = {}
    for rel, source in raw.items():
        if not rel.startswith(_SELFTEST_PREFIX):
            continue
        code = _javascript_lexical_code(source)
        declarations = [
            (
                match.group(1),
                match.group(2),
                match.start(),
                _brace_stack_at(code, match.start()),
            )
            for match in re.finditer(
                r"(?ms)\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
                r"((?:(?!;).)*)\s*;",
                code,
            )
        ]

        def oracle_nearest(
            name: str,
            position: int,
            scope: tuple[int, ...],
            current_declarations=declarations,
        ) -> "tuple[str, str, int, tuple[int, ...]] | None":
            visible = [
                declaration
                for declaration in current_declarations
                if declaration[0] == name
                and declaration[2] < position
                and declaration[3] == scope[: len(declaration[3])]
            ]
            if not visible:
                return None
            return max(
                visible, key=lambda declaration: (len(declaration[3]), declaration[2])
            )

        origin: dict[int, str] = {}
        for _name, rhs, position, _scope in declarations:
            literal_source = re.search(
                r"\b(?:[A-Za-z_$][\w$]*\s*\.\s*)+"
                r"(?:initial|loadInitial|model)\(\s*[\"']"
                r"([A-Za-z_$][\w$-]*)[\"']\s*\)",
                rhs,
            )
            if literal_source is not None:
                origin[position] = literal_source.group(1)

        state_domains: "dict[str, set[str]]" = {}
        finite_loop = re.compile(
            r"\[(?P<values>(?:\s*[\"'][A-Za-z_$][\w$-]*[\"']\s*,?)+)\]"
            r"\s*\.forEach\(\s*\(?\s*(?P<key>[A-Za-z_$][\w$]*)\s*\)?"
            r"\s*=>\s*\{"
        )
        for loop in finite_loop.finditer(code):
            values = set(
                re.findall(r"[\"']([A-Za-z_$][\w$-]*)[\"']", loop.group("values"))
            )
            key = loop.group("key")
            body = _balanced_block(code, loop.end() - 1)
            if not values or re.search(
                rf"\b(?:initial|loadInitial)\(\s*{re.escape(key)}\s*\)", body
            ) is None:
                continue
            loop_scope = _brace_stack_at(code, loop.start())
            for store in set(
                re.findall(
                    rf"\b([A-Za-z_$][\w$]*)\s*\[\s*{re.escape(key)}\s*\]\s*=",
                    body,
                )
            ):
                store_binding = oracle_nearest(store, loop.start(), loop_scope)
                if store_binding is None:
                    continue
                for write in re.finditer(
                    r"\b[A-Za-z_$][\w$]*\.state\.([A-Za-z_$][\w$]*)\s*=\s*"
                    + re.escape(store)
                    + r"\b",
                    code,
                ):
                    visible = oracle_nearest(
                        store, write.start(), _brace_stack_at(code, write.start())
                    )
                    if visible is not None and visible[2] == store_binding[2]:
                        state_domains.setdefault(write.group(1), set()).update(values)

        state_store: "dict[int, set[str]]" = {}
        for _name, rhs, position, _scope in declarations:
            state_read = re.search(
                r"\b[A-Za-z_$][\w$]*\.state\.([A-Za-z_$][\w$]*)\b", rhs
            )
            if state_read is not None and state_read.group(1) in state_domains:
                state_store[position] = state_domains[state_read.group(1)]
        for _name, rhs, position, scope in declarations:
            stored = re.search(
                r"\b([A-Za-z_$][\w$]*)\s*(?:\.([A-Za-z_$][\w$-]*)"
                r"|\[\s*[\"']([A-Za-z_$][\w$-]*)[\"']\s*\])",
                rhs,
            )
            if stored is None:
                continue
            store_binding = oracle_nearest(stored.group(1), position, scope)
            stored_screen = stored.group(2) or stored.group(3)
            if (
                store_binding is not None
                and stored_screen in state_store.get(store_binding[2], set())
            ):
                origin[position] = stored_screen

        names = {declaration[0] for declaration in declarations if declaration[2] in origin}
        if not names:
            continue
        receivers = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
        oracle_access = re.compile(
            rf"(?<![\w$])({receivers})\s*(?:\?\.|\.)\s*"
            r"([A-Za-z_$][\w$-]*)\b"
            rf"|(?<![\w$])({receivers})\s*\[\s*[\"']"
            r"([A-Za-z_$][\w$-]*)[\"']\s*\]"
        )
        for access_match in oracle_access.finditer(code):
            receiver = access_match.group(1) or access_match.group(3)
            field = access_match.group(2) or access_match.group(4)
            declaration = oracle_nearest(
                receiver,
                access_match.start(),
                _brace_stack_at(code, access_match.start()),
            )
            if declaration is not None and (screen := origin.get(declaration[2])) is not None:
                evidence.setdefault((screen, field), set()).add(rel)
    return {key: tuple(sorted(files)) for key, files in evidence.items()}


def _oracle_product_snapshot_field_access(
    code: str, field: str, hook_names: "set[str]"
) -> bool:
    """oracle 전용 제품 alias/scope 열거 — collector binding helper를 재사용하지 않는다."""
    bindings: "list[tuple[str, int, tuple[int, ...], str]]" = []
    literal_hooks = "|".join(
        re.escape(name)
        for name in sorted({*hook_names, "snapshot", "fullSnapshot", "useJob"}, key=len, reverse=True)
    )
    hook_call = rf"(?:{literal_hooks}|use[A-Za-z_$][\w$]*Snapshot)"

    def direct_source(rhs: str) -> bool:
        expression = rhs.strip()
        get_snapshot = re.fullmatch(
            r"(?:await\s+)?[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*"
            r"\s*\.\s*getSnapshot\s*\([^;{}]*\)",
            expression,
            re.S,
        )
        hook_snapshot = re.fullmatch(
            rf"(?:await\s+)?(?:{hook_call})\s*\([^;{{}}]*\)",
            expression,
            re.S,
        )
        subscribed = re.fullmatch(
            r"useSyncExternalStore\s*\((?s:.*)\)", expression
        ) and re.search(r"(?:\.model\.|poolModel\b)", expression)
        return get_snapshot is not None or hook_snapshot is not None or bool(subscribed)

    for declaration in re.finditer(
        r"(?ms)\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
        r"((?:(?!;).)*)\s*;",
        code,
    ):
        name, rhs = declaration.groups()
        kind = "snapshot" if direct_source(rhs) else ""
        bindings.append(
            (name, declaration.start(), _brace_stack_at(code, declaration.start()), kind)
        )

    functions = re.compile(
        r"\b(?:export\s+)?(?:async\s+)?function\s+[A-Za-z_$][\w$]*"
        r"\s*\((?P<params>[^)]*)\)\s*(?::\s*[^\{]+)?\s*\{"
    )
    for function in functions.finditer(code):
        scope = _brace_stack_at(code, function.end())
        for raw_param in function.group("params").split(","):
            name_match = re.match(r"\s*([A-Za-z_$][\w$]*)", raw_param)
            if name_match is None:
                continue
            name = name_match.group(1)
            kind = "snapshot" if name == "snapshot" else ""
            if name != "snapshot" and re.search(r"\bsnapshot\s*:", raw_param):
                kind = "container"
            bindings.append((name, function.end() - 1, scope, kind))

    def nearest(
        name: str, position: int, scope: tuple[int, ...]
    ) -> "tuple[str, int, tuple[int, ...], str] | None":
        visible = [
            binding
            for binding in bindings
            if binding[0] == name
            and binding[1] < position
            and binding[2] == scope[: len(binding[2])]
        ]
        if not visible:
            return None
        return max(visible, key=lambda binding: (len(binding[2]), binding[1]))

    destructured_field = False
    destructuring = re.compile(
        r"\b(?:const|let|var)\s*\{(?P<items>[^}]*)\}\s*=\s*"
        r"(?P<rhs>[^;]+)\s*;"
    )
    for declaration in destructuring.finditer(code):
        rhs = declaration.group("rhs").strip()
        scope = _brace_stack_at(code, declaration.start())
        rhs_name = re.fullmatch(r"[A-Za-z_$][\w$]*", rhs)
        rhs_binding = (
            nearest(rhs, declaration.start(), scope) if rhs_name is not None else None
        )
        snapshot_source = direct_source(rhs) or (
            rhs_binding is not None and rhs_binding[3] == "snapshot"
        )
        for raw_item in declaration.group("items").split(","):
            item = raw_item.strip()
            if not item:
                continue
            parts = [part.strip() for part in item.split(":", maxsplit=1)]
            exported = parts[0]
            local = parts[-1].split("=", maxsplit=1)[0].strip()
            if not re.fullmatch(r"[A-Za-z_$][\w$]*", local):
                continue
            kind = ""
            if (
                exported == "snapshot"
                and rhs_binding is not None
                and rhs_binding[3] == "container"
            ):
                kind = "snapshot"
            bindings.append((local, declaration.start(), scope, kind))
            if exported == field and snapshot_source:
                destructured_field = True

    token = re.escape(field)
    alias_access = re.compile(
        rf"(?<![\w$])([A-Za-z_$][\w$]*)\s*(?:\?\.|\.)\s*{token}\b"
        rf"|(?<![\w$])([A-Za-z_$][\w$]*)\s*\[\s*[\"']{token}[\"']\s*\]"
    )
    for access in alias_access.finditer(code):
        receiver = access.group(1) or access.group(2)
        binding = nearest(
            receiver, access.start(), _brace_stack_at(code, access.start())
        )
        if binding is not None and binding[3] == "snapshot":
            return True

    container_access = re.compile(
        rf"(?<![\w$])([A-Za-z_$][\w$]*)\s*(?:\?\.|\.)\s*snapshot"
        rf"\s*(?:\?\.|\.)\s*{token}\b"
    )
    for access in container_access.finditer(code):
        binding = nearest(
            access.group(1), access.start(), _brace_stack_at(code, access.start())
        )
        if binding is not None and binding[3] == "container":
            return True

    direct_access = re.compile(
        rf"(?<![\w$])(?:{hook_call})\s*\([^;{{}}]*?\)"
        rf"\s*(?:\?\.|\.)\s*{token}\b"
    )
    return destructured_field or direct_access.search(code) is not None


def _snapshot_oracle_evidence(
    repo_root: Path,
    screen: str,
    field: str,
    *,
    raw_corpus: "dict[str, str] | None" = None,
    selftest_inventory: "dict[tuple[str, str], tuple[str, ...]] | None" = None,
) -> tuple[str, ...]:
    """수집기와 closure·access matcher를 공유하지 않는 snapshot gate 분모."""
    raw = _frontend_corpus(repo_root) if raw_corpus is None else raw_corpus
    corpus = {
        rel: text
        for rel, text in raw.items()
        if rel.startswith("frontend/src/") and not rel.startswith(_SELFTEST_PREFIX)
    }
    const_pattern = re.compile(
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*[\"']([\w-]+)[\"']"
    )
    model_pattern = re.compile(
        r"\.model(?:<[^;()]*>)?\(\s*([\"'][^\"']+[\"']|[A-Za-z_$][\w$]*)\s*\)"
    )
    import_pattern = re.compile(
        r"(?ms)^\s*import\s+(?!type\b)((?:(?!;).)*?)\s+from\s+"
        r"[\"'](\.[^\"']+)[\"']\s*;"
    )

    roots: set[str] = set()
    imports: "dict[str, list[tuple[str, str]]]" = {}
    for rel, text in corpus.items():
        lexical = _javascript_lexical_code(text)
        constants = dict(const_pattern.findall(lexical))
        for expression in model_pattern.findall(lexical):
            value = expression[1:-1] if expression[:1] in {"\"", "'"} else constants.get(expression)
            if value == screen:
                roots.add(rel)
        imports[rel] = []
        for clause, specifier in import_pattern.findall(_javascript_import_code(text)):
            target = _resolve_relative_module(corpus, rel, specifier)
            if target is not None:
                imports[rel].append((clause, target))

    modules: set[str] = set()
    pending = list(roots)
    while pending:
        rel = pending.pop()
        if rel in modules:
            continue
        modules.add(rel)
        pending.extend(target for _clause, target in imports.get(rel, ()) if target not in modules)
    reverse_modules: set[str] = set()
    for importer, entries in imports.items():
        if importer in modules:
            continue
        if any(
            target in modules and re.search(r"\buse[A-Za-z_$][\w$]*Snapshot\b", clause)
            for clause, target in entries
        ):
            modules.add(importer)
            reverse_modules.add(importer)

    selected_by_target: "dict[str, set[str] | None]" = {}
    for importer in modules:
        for clause, target in imports.get(importer, ()):
            if target not in modules:
                continue
            braces = re.search(r"\{(.*)\}", clause, re.S)
            if braces is None:
                selected_by_target[target] = None
                continue
            names = {
                re.split(r"\s+as\s+", re.sub(r"^\s*type\s+", "", item).strip())[0]
                for item in braces.group(1).split(",")
                if item.strip()
            }
            if target not in selected_by_target:
                selected_by_target[target] = names
            elif selected_by_target[target] is not None:
                selected_by_target[target].update(names)

    oracle_sources: dict[str, str] = {}
    function_pattern = re.compile(
        r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+"
        r"([A-Za-z_$][\w$]*)\s*\([^)]*\)[^{;]*\{"
    )
    for rel in sorted(modules):
        if rel in roots or rel in reverse_modules:
            oracle_sources[rel] = corpus[rel]
            continue
        selected = selected_by_target.get(rel)
        if selected is None:
            if rel in selected_by_target:
                oracle_sources[rel] = corpus[rel]
            continue
        lexical_source = _javascript_lexical_code(corpus[rel])
        blocks = {}
        for match in function_pattern.finditer(lexical_source):
            body = _balanced_block(lexical_source, match.end() - 1)
            blocks[match.group(1)] = (
                lexical_source[match.start() : match.end() - 1] + body
            )
        reached: set[str] = set()
        queue = list(selected)
        while queue:
            name = queue.pop()
            if name in reached or name not in blocks:
                continue
            reached.add(name)
            queue.extend(
                called
                for called in re.findall(
                    r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", blocks[name]
                )
                if called in blocks and called not in reached
            )
        if reached:
            oracle_sources[rel] = "\n".join(blocks[name] for name in sorted(reached))

    evidence: list[str] = []
    for rel, source in oracle_sources.items():
        code = _javascript_lexical_code(source)
        hook_names = {"snapshot", "useJob"}
        for clause, _target in imports.get(rel, ()):
            for hook, alias in re.findall(
                r"\b(use[A-Za-z_$][\w$]*Snapshot)\b(?:\s+as\s+([A-Za-z_$][\w$]*))?",
                clause,
            ):
                hook_names.add(alias or hook)
        if _oracle_product_snapshot_field_access(code, field, hook_names):
            evidence.append(rel)

    oracle_selftest = (
        _snapshot_oracle_selftest_inventory(raw)
        if selftest_inventory is None
        else selftest_inventory
    )
    evidence.extend(oracle_selftest.get((screen, field), ()))
    return tuple(sorted(set(evidence)))


def snapshot_oracle_inventory(
    repo_root: Path,
    *,
    controllers: "dict[str, type] | None" = None,
) -> SnapshotOracleInventory:
    """현재 source 의 독립 snapshot consumer 분모를 정확히 한 번 측정한다."""
    controllers = _controller_classes(repo_root) if controllers is None else controllers
    oracle_raw = _frontend_corpus(repo_root)
    oracle_selftest = _snapshot_oracle_selftest_inventory(oracle_raw)
    rows: list[tuple[str, str, tuple[str, ...]]] = []
    for screen in sorted(controllers):
        for field in sorted(_static_snapshot_keys(repo_root, controllers[screen])):
            rows.append(
                (
                    screen,
                    field,
                    _snapshot_oracle_evidence(
                        repo_root,
                        screen,
                        field,
                        raw_corpus=oracle_raw,
                        selftest_inventory=oracle_selftest,
                    ),
                )
            )
    return SnapshotOracleInventory(tuple(rows))


def collect_snapshot_fields(
    repo_root: Path,
    *,
    controllers: "dict[str, type] | None" = None,
    runtime_fields: "dict[str, tuple[str, ...]] | None" = None,
) -> tuple[SnapshotField, ...]:
    controllers = _controller_classes(repo_root) if controllers is None else controllers
    runtime_fields = (
        _runtime_snapshot_fields(repo_root) if runtime_fields is None else runtime_fields
    )
    corpus = _frontend_corpus(repo_root)
    closures = _screen_consumer_modules(corpus, set(controllers))
    selftest_evidence = _snapshot_selftest_inventory(corpus)
    rows: list[SnapshotField] = []
    for screen in sorted(controllers):
        cls = controllers[screen]
        producer = _method_symbol(cls, "snapshot")
        declared = set(_static_snapshot_keys(repo_root, cls))
        observed = set(runtime_fields.get(screen, ()))
        runtime_only = sorted(observed - declared)
        if runtime_only:
            raise FactGraphError(
                f"{screen} 스냅샷 실측 키가 정적 선언 밖이다(추출기 결손): {runtime_only}"
            )
        for field in sorted(declared):
            evidence = tuple(
                sorted(
                    {
                        *_snapshot_field_evidence(corpus, closures, screen, field),
                        *selftest_evidence.get((screen, field), ()),
                    }
                )
            )
            rows.append(
                SnapshotField(
                    screen=screen,
                    field=field,
                    producer=producer,
                    runtime_observed=field in observed,
                    consumer=_classify_consumer(evidence),
                    js_evidence=evidence,
                )
            )
    return tuple(rows)


# ---------------------------------------------------------- push/event 채널


def _payload_builder_fields(module_tree: ast.Module, builder: str) -> tuple[str, ...]:
    """payload builder의 실키. 제어 흐름 안에서만 더해지는 키에는 ``?``를 붙인다."""
    function = next(
        (
            node
            for node in module_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == builder
        ),
        None,
    )
    if function is None:
        raise FactGraphError(f"payload builder 정의를 찾지 못했다: {builder}")

    returned_names = {
        node.value.id
        for node in ast.walk(function)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Name)
    }
    if len(returned_names) > 1:
        raise FactGraphError(
            f"{builder}: payload 반환 변수가 둘 이상이라 키를 귀속할 수 없다: "
            f"{sorted(returned_names)}"
        )
    payload_name = next(iter(returned_names), None)
    unconditional: set[str] = set()
    conditional: set[str] = set()

    def add(keys: "list[str]", *, guarded: bool) -> None:
        (conditional if guarded else unconditional).update(keys)

    def target_key(target: ast.expr) -> "str | None":
        if not (
            payload_name is not None
            and isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == payload_name
            and isinstance(target.slice, ast.Constant)
            and isinstance(target.slice.value, str)
        ):
            return None
        return target.slice.value

    def visit(statements: "list[ast.stmt]", *, guarded: bool) -> None:
        for statement in statements:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                value = statement.value
                if value is not None:
                    for target in targets:
                        if (
                            payload_name is not None
                            and isinstance(target, ast.Name)
                            and target.id == payload_name
                        ):
                            add(_dict_literal_keys(value), guarded=guarded)
                        key = target_key(target)
                        if key is not None:
                            add([key], guarded=guarded)
                continue
            if isinstance(statement, ast.Return) and statement.value is not None:
                add(_dict_literal_keys(statement.value), guarded=guarded)
                continue
            if isinstance(statement, ast.If):
                visit(statement.body, guarded=True)
                visit(statement.orelse, guarded=True)
                continue
            if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                visit(statement.body, guarded=True)
                visit(statement.orelse, guarded=True)
                continue
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                visit(statement.body, guarded=guarded)
                continue
            if isinstance(statement, ast.Try):
                visit(statement.body, guarded=True)
                for handler in statement.handlers:
                    visit(handler.body, guarded=True)
                visit(statement.orelse, guarded=True)
                visit(statement.finalbody, guarded=guarded)
                continue
            if isinstance(statement, ast.Match):
                for case in statement.cases:
                    visit(case.body, guarded=True)

    visit(function.body, guarded=False)
    conditional.difference_update(unconditional)
    if not unconditional and not conditional:
        raise FactGraphError(f"{builder}: payload 키를 하나도 도출하지 못했다")
    return (*sorted(unconditional), *(f"{key}?" for key in sorted(conditional)))


def _payload_builder_of(method: ast.FunctionDef, delivery: ast.Call) -> str:
    """``_deliver`` 둘째 인자에서 module-level payload builder 이름을 1-hop 해소한다."""
    payload = delivery.args[1]
    if isinstance(payload, ast.Call) and isinstance(payload.func, ast.Name):
        return payload.func.id
    if isinstance(payload, ast.Name):
        bindings: list[tuple[int, str]] = []
        for node in ast.walk(method):
            if not (
                isinstance(node, (ast.Assign, ast.AnnAssign))
                and node.value is not None
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == payload.id for target in targets):
                bindings.append((node.lineno, node.value.func.id))
        preceding = [entry for entry in bindings if entry[0] < delivery.lineno]
        if preceding:
            return max(preceding)[1]
    raise FactGraphError(
        f"ProductApiClient.{method.name}: _deliver payload builder를 해소하지 못했다"
    )


def _product_event_producers(
    repo_root: Path,
) -> "dict[str, tuple[str, tuple[str, ...]]]":
    """이벤트 값 → (발신 메서드 symbol, payload builder 실키)."""
    from hwpxfiller.webapp import product_api

    module_path = repo_root / "src" / "hwpxfiller" / "webapp" / "product_api.py"
    module_tree = ast.parse(module_path.read_text(encoding="utf-8"))
    class_node = next(
        (
            node
            for node in module_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ProductApiClient"
        ),
        None,
    )
    if class_node is None:
        raise FactGraphError("product_api.py 에서 ProductApiClient 를 찾지 못했다")
    producers: "dict[str, tuple[str, tuple[str, ...]]]" = {}
    for node in class_node.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "_deliver"
                and len(call.args) >= 2
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id.startswith("EVENT_")
            ):
                event_value = getattr(product_api, call.args[0].id)
                if event_value in producers:
                    raise FactGraphError(f"product event producer가 둘 이상이다: {event_value}")
                builder = _payload_builder_of(node, call)
                producers[event_value] = (
                    f"hwpxfiller.webapp.product_api:ProductApiClient.{node.name}#method",
                    _payload_builder_fields(module_tree, builder),
                )
    return producers


def _handler_key_pattern(event: str) -> re.Pattern:
    """객체 handler 키의 quoted/bare 두 표기. 일반 문자열 출현은 증거로 세지 않는다."""
    forms = [rf"[\"']{re.escape(event)}[\"']\s*:"]
    if re.fullmatch(r"[A-Za-z_$][\w$]*", event):
        forms.append(rf"(?<![\w$]){re.escape(event)}\s*:")
    return re.compile("|".join(forms))


def _partial_push_channels(
    repo_root: Path, controllers: "dict[str, type]"
) -> tuple[PushChannel, ...]:
    """``self._push_sink(self.name, {리터럴})`` — 전체 스냅샷이 아닌 부분 push 의 전수.

    이 스캔이 분모다: 새 부분 push 가 생기면 여기 나타나고, 원장과 어긋나면 드리프트가
    무는 구조라 부분 채널이 조용히 늘 수 없다.
    """
    class_of_module: dict[str, list[tuple[str, type]]] = {}
    for screen, cls in controllers.items():
        for owner in cls.__mro__:
            if owner.__module__.startswith("hwpxfiller.webapp"):
                class_of_module.setdefault(owner.__module__, []).append((screen, owner))
    channels: list[PushChannel] = []
    webapp_dir = repo_root / "src" / "hwpxfiller" / "webapp"
    for path in sorted(webapp_dir.glob("*.py")):
        module = "hwpxfiller.webapp." + path.stem
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for class_node in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            owners = [
                (screen, owner)
                for screen, owner in class_of_module.get(module, [])
                if owner.__qualname__ == class_node.name
            ]
            for fn in (n for n in class_node.body if isinstance(n, ast.FunctionDef)):
                for call in ast.walk(fn):
                    if not (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "_push_sink"
                        and len(call.args) == 2
                        and isinstance(call.args[1], ast.Dict)
                    ):
                        continue
                    fields: list[str] = []
                    for key, value in zip(call.args[1].keys, call.args[1].values, strict=True):
                        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                            continue
                        nested = _dict_literal_keys(value)
                        if nested:
                            fields.extend(f"{key.value}.{sub}" for sub in nested)
                        else:
                            fields.append(key.value)
                    for screen, owner in owners or [("?", None)]:
                        producer = (
                            f"{module}:{class_node.name}.{fn.name}#method"
                            if owner is None
                            else f"{owner.__module__}:{owner.__qualname__}.{fn.name}#method"
                        )
                        channels.append(
                            PushChannel(
                                kind="partial_push",
                                name=f"{screen}:{fn.name}",
                                producer=producer,
                                fields=tuple(sorted(fields)),
                                consumer_evidence=(),
                            )
                        )
    return tuple(sorted(channels, key=lambda c: (c.name, c.producer)))


def collect_channels(
    repo_root: Path, *, controllers: "dict[str, type] | None" = None
) -> tuple[PushChannel, ...]:
    from hwpxfiller.webapp import product_api, selftest_api

    controllers = _controller_classes(repo_root) if controllers is None else controllers
    event_consumer_sources = {
        rel: (repo_root / rel).read_text(encoding="utf-8")
        for rel in (_PRODUCT_API_JS_REL_PATH, _BOOTSTRAP_JS_REL_PATH)
    }
    producers = _product_event_producers(repo_root)
    channels: list[PushChannel] = []
    for event in product_api.EVENTS:
        entry = producers.get(event)
        if entry is None:
            raise FactGraphError(f"이벤트 {event!r} 의 발신 메서드를 찾지 못했다")
        producer, fields = entry
        key_pattern = _handler_key_pattern(event)
        evidence = tuple(
            sorted(
                rel for rel, source in event_consumer_sources.items() if key_pattern.search(source)
            )
        )
        channels.append(
            PushChannel(
                kind="product_event",
                name=event,
                producer=producer,
                fields=fields,
                consumer_evidence=evidence,
            )
        )
    channels.extend(_partial_push_channels(repo_root, controllers))

    operations = selftest_api.HostOperations
    corpus = _frontend_corpus(repo_root)
    selftest_corpus = {
        rel: text for rel, text in corpus.items() if rel.startswith(_SELFTEST_PREFIX)
    }
    for op in sorted(operations._HANDLERS):
        handler = operations._HANDLERS[op]
        evidence = tuple(
            sorted(
                rel
                for rel, text in selftest_corpus.items()
                if re.search(rf"[\"']{re.escape(op)}[\"']", text)
            )
        )
        channels.append(
            PushChannel(
                kind="selftest_host_op",
                name=op,
                producer=(f"hwpxfiller.webapp.selftest_api:HostOperations.{handler}#method"),
                fields=(),
                consumer_evidence=evidence,
            )
        )
    return tuple(channels)


# ------------------------------------------------------------------ 조립


def _sha256_of(repo_root: Path, rel: str) -> str:
    return hashlib.sha256((repo_root / rel).read_bytes()).hexdigest()


def build(repo_root: Path) -> TransportInventory:
    repo_root = Path(repo_root)
    if not (repo_root / "src" / "hwpxfiller" / "webapp" / "app.py").is_file():
        raise FactGraphError(
            f"transport 계측은 제품 저장소 전용이다 — webapp/app.py 가 없다: {repo_root}"
        )
    import gen_bridge_contract

    from hwpxfiller.webapp import product_api

    controllers = _controller_classes(repo_root)
    endpoints, enablement = collect_endpoints(repo_root, controllers=controllers)
    host_methods = collect_host_methods(repo_root)
    product_consumed, selftest_consumed = bridge_consumption(_bridge_source(repo_root))
    snapshot_fields = collect_snapshot_fields(repo_root, controllers=controllers)
    channels = collect_channels(repo_root, controllers=controllers)
    python_codes = tuple(
        sorted(
            value
            for name, value in vars(product_api).items()
            if name.startswith("CODE_") and isinstance(value, str)
        )
    )
    contract = gen_bridge_contract.extract_app_contract(
        (repo_root / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(encoding="utf-8")
    )
    js_codes = tuple(
        gen_bridge_contract.extract_js_error_codes(
            (repo_root / _PRODUCT_API_JS_REL_PATH).read_text(encoding="utf-8")
        )
    )
    return TransportInventory(
        endpoints=endpoints,
        host_methods=host_methods,
        bridge_consumed_product=product_consumed,
        bridge_consumed_selftest=selftest_consumed,
        snapshot_fields=snapshot_fields,
        channels=channels,
        enablement=enablement,
        protocol=product_api.PROTOCOL,
        version=product_api.VERSION,
        capabilities=tuple(product_api.CAPABILITIES),
        python_error_codes=python_codes,
        js_error_codes=js_codes,
        rejection_key=contract.rejection_key,
        rejection_fields=tuple(contract.rejection_fields),
        input_sha256=tuple(
            (rel, _sha256_of(repo_root, rel))
            for rel in (
                _BRIDGE_REL_PATH,
                _PRODUCT_API_JS_REL_PATH,
                _GENERATED_CONTRACT,
            )
        ),
    )


# ---------------------------------------------------------- 독립 분모 술어
#
# 아래 술어들은 원장(파싱본)을 받아 **저장소에서 다시 센 분모**와 대조하고 문제 목록을
# 돌려준다(빈 목록 = 통과). 게이트가 실물로 양성을, 변형 사본으로 음성을 각각 세운다.


def endpoint_problems(
    repo_root: Path,
    endpoints: tuple[DispatchEndpoint, ...],
    *,
    controllers: "dict[str, type] | None" = None,
) -> "list[str]":
    from hwpxfiller.webapp.action_registry import ACTION_REGISTRY, ZONE_MUTATIONS

    controllers = _controller_classes(repo_root) if controllers is None else controllers
    evidence_by_pair = _dispatch_pair_oracle(repo_root)
    problems: list[str] = []
    rows = {(e.screen, e.action): e for e in endpoints}
    if len(rows) != len(endpoints):
        problems.append("endpoint 행에 중복 (screen, action) 이 있다")
    registry_keys = {
        (screen, action) for screen in ACTION_REGISTRY for action in ACTION_REGISTRY[screen]
    }
    for key in sorted(registry_keys - set(rows)):
        problems.append(f"registry 액션이 원장에 없다: {key[0]}/{key[1]}")
    for key in sorted(set(rows) - registry_keys):
        problems.append(f"원장에만 있는 유령 endpoint: {key[0]}/{key[1]}")
    for key in sorted(registry_keys & set(rows)):
        screen, action = key
        row = rows[key]
        actual_evidence = evidence_by_pair.get(key, ())
        schema = ACTION_REGISTRY[screen][action]
        if row.required != tuple(sorted(schema.required)):
            problems.append(
                f"{screen}/{action}: required 키 드리프트 — 원장 {list(row.required)} ≠ "
                f"정본 {sorted(schema.required)}"
            )
        if row.optional != tuple(sorted(schema.optional)):
            problems.append(
                f"{screen}/{action}: optional 키 드리프트 — 원장 {list(row.optional)} ≠ "
                f"정본 {sorted(schema.optional)}"
            )
        if row.zone_mutation != (action in ZONE_MUTATIONS):
            problems.append(f"{screen}/{action}: zone_mutation 플래그가 정본과 다르다")
        cls = controllers.get(screen)
        if cls is None:
            problems.append(f"{screen}: 배선된 컨트롤러가 없다")
            continue
        handler_name = f"_do_{action}"
        if not any(handler_name in vars(owner) for owner in cls.__mro__):
            if row.handler:
                problems.append(
                    f"{screen}/{action}: 원장이 실재하지 않는 handler 를 주장한다 -> {row.handler}"
                )
        else:
            expected = _method_symbol(cls, handler_name)
            if row.handler != expected:
                problems.append(
                    f"{screen}/{action}: handler 귀속 불일치 — 원장 {row.handler!r} ≠ "
                    f"실측 {expected!r}"
                )
        if row.js_evidence != actual_evidence:
            problems.append(
                f"{screen}/{action}: 소비자 증거 드리프트 — "
                f"원장 {list(row.js_evidence)} ≠ 실측 {list(actual_evidence)}"
            )
        for rel in row.js_evidence:
            if not (repo_root / rel).is_file():
                problems.append(f"{screen}/{action}: 소비자 증거 파일이 없다 -> {rel}")
        if row.consumer != _classify_consumer(row.js_evidence):
            problems.append(
                f"{screen}/{action}: consumer 분류가 증거와 어긋난다 — {row.consumer!r}"
            )
    return problems


def host_method_problems(
    repo_root: Path,
    host_methods: tuple[HostMethod, ...],
    bridge_consumed_product: tuple[str, ...],
    bridge_consumed_selftest: tuple[str, ...],
) -> "list[str]":
    import gen_bridge_contract

    contract = gen_bridge_contract.extract_app_contract(
        (repo_root / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(encoding="utf-8")
    )
    bridge_source = _bridge_source(repo_root)
    product, selftest = bridge_consumption(bridge_source)
    aliases = bridge_aliases(bridge_source)
    problems: list[str] = []
    if tuple(bridge_consumed_product) != product:
        problems.append(
            f"bridge 제품 소비 드리프트 — 원장 {list(bridge_consumed_product)} ≠ 실측 {list(product)}"
        )
    if tuple(bridge_consumed_selftest) != selftest:
        problems.append(
            f"bridge 시험 소비 드리프트 — 원장 {list(bridge_consumed_selftest)} ≠ 실측 {list(selftest)}"
        )
    declared = {m.name: m for m in host_methods}
    expected_names = [name for name, _params in contract.methods]
    if list(declared) != expected_names:
        problems.append(
            f"host 메서드 전수 불일치 — 원장 {list(declared)} ≠ WebFrontend {expected_names}"
        )
        return problems
    ghost = sorted(set(product) - set(expected_names))
    if ghost:
        problems.append(f"bridge.js 가 공개 표면에 없는 메서드를 부른다: {ghost}")
    for name, params in contract.methods:
        row = declared[name]
        if row.params != tuple(params):
            problems.append(f"{name}: 인자 형상이 정본과 다르다 — {row.params}")
        should_be = "product" if name in product else "host_internal"
        if row.consumer != should_be:
            problems.append(
                f"{name}: 소비 분류 드리프트 — 원장 {row.consumer!r} ≠ 실측 {should_be!r}"
            )
        if row.bridge_alias != aliases.get(name, ""):
            problems.append(
                f"{name}: bridge 별칭 불일치 — 원장 {row.bridge_alias!r} ≠ "
                f"실측 {aliases.get(name, '')!r}"
            )
        if should_be == "host_internal":
            actual = " ".join(_internal_python_consumers(repo_root, name))
            if not actual:
                problems.append(f"{name}: JS 도 파이썬도 부르지 않는 죽은 공개 endpoint 다")
            elif row.python_consumer != actual:
                problems.append(
                    f"{name}: host-internal 소비자 불일치 — 원장 {row.python_consumer!r} ≠ "
                    f"실측 {actual!r}"
                )
        elif row.python_consumer:
            problems.append(f"{name}: 제품 소비 메서드에 내부 소비자 주장이 붙어 있다")
    return problems


def snapshot_problems(
    repo_root: Path,
    snapshot_fields: tuple[SnapshotField, ...],
    *,
    controllers: "dict[str, type] | None" = None,
    runtime_fields: "dict[str, tuple[str, ...]] | None" = None,
    oracle_inventory: "SnapshotOracleInventory | None" = None,
) -> "list[str]":
    controllers = _controller_classes(repo_root) if controllers is None else controllers
    runtime_fields = (
        _runtime_snapshot_fields(repo_root) if runtime_fields is None else runtime_fields
    )
    oracle_inventory = (
        snapshot_oracle_inventory(repo_root, controllers=controllers)
        if oracle_inventory is None
        else oracle_inventory
    )
    evidence_by_field = oracle_inventory.as_dict()
    problems: list[str] = []
    if len(evidence_by_field) != len(oracle_inventory.rows):
        problems.append("snapshot consumer 독립 분모에 중복 (screen, field) 행이 있다")
    declared_by_screen = {
        screen: set(_static_snapshot_keys(repo_root, cls))
        for screen, cls in controllers.items()
    }
    declared_keys = {
        (screen, field)
        for screen, fields in declared_by_screen.items()
        for field in fields
    }
    oracle_keys = set(evidence_by_field)
    for screen, field in sorted(declared_keys - oracle_keys):
        problems.append(f"snapshot consumer 독립 분모에 없다: {screen}.{field}")
    for screen, field in sorted(oracle_keys - declared_keys):
        problems.append(f"snapshot consumer 독립 분모에만 있는 유령 필드: {screen}.{field}")
    by_screen: dict[str, dict[str, SnapshotField]] = {}
    for row in snapshot_fields:
        if row.field in by_screen.setdefault(row.screen, {}):
            problems.append(f"{row.screen}: 스냅샷 필드 중복 행 -> {row.field}")
        by_screen[row.screen][row.field] = row
    if sorted(by_screen) != sorted(controllers):
        problems.append(
            f"스냅샷 채널 전수 불일치 — 원장 {sorted(by_screen)} ≠ 배선 {sorted(controllers)}"
        )
    for screen in sorted(set(by_screen) & set(controllers)):
        cls = controllers[screen]
        declared = declared_by_screen[screen]
        observed = set(runtime_fields.get(screen, ()))
        rows = by_screen[screen]
        for field in sorted(declared - set(rows)):
            problems.append(f"{screen}: producer 미분류 스냅샷 필드 -> {field}")
        for field in sorted(set(rows) - declared):
            problems.append(f"{screen}: 원장에만 있는 유령 필드 -> {field}")
        producer = _method_symbol(cls, "snapshot")
        for field in sorted(set(rows) & declared):
            row = rows[field]
            actual_evidence = evidence_by_field.get((screen, field), ())
            if row.producer != producer:
                problems.append(
                    f"{screen}.{field}: producer 귀속 불일치 — {row.producer!r} ≠ {producer!r}"
                )
            if row.runtime_observed != (field in observed):
                problems.append(f"{screen}.{field}: 빈 상태 실측 표지가 실측과 다르다")
            if row.js_evidence != actual_evidence:
                problems.append(
                    f"{screen}.{field}: 소비자 증거 드리프트 — "
                    f"원장 {list(row.js_evidence)} ≠ 실측 {list(actual_evidence)}"
                )
            if row.consumer != _classify_consumer(row.js_evidence):
                problems.append(
                    f"{screen}.{field}: consumer 분류가 증거와 어긋난다 — {row.consumer!r}"
                )
    return problems


def _top_level_object_keys(source: str, marker: str, *, label: str) -> tuple[str, ...]:
    """marker가 여는 JS 객체의 최상위 키 전수. handler 수집 정규식과 독립인 분모다."""
    match = re.search(marker, source)
    if match is None:
        raise FactGraphError(f"{label} 객체를 찾지 못했다")
    block = _balanced_block(source, match.end() - 1)
    depth = 0
    quote = ""
    escaped = False
    line_comment = False
    block_comment = False
    top_level: list[str] = []
    index = 0
    while index < len(block):
        char = block[index]
        nxt = block[index + 1] if index + 1 < len(block) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
                if depth == 1:
                    top_level.append(char)
            index += 1
            continue
        if block_comment:
            if char == "*" and nxt == "/":
                block_comment = False
                index += 2
            else:
                if char == "\n" and depth == 1:
                    top_level.append(char)
                index += 1
            continue
        if quote:
            if depth == 1:
                top_level.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            index += 1
            continue
        if char == "/" and nxt == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and nxt == "*":
            block_comment = True
            index += 2
            continue
        if char in "\"'`":
            quote = char
            if depth == 1:
                top_level.append(char)
            index += 1
            continue
        if char == "{":
            depth += 1
            index += 1
            continue
        if char == "}":
            depth -= 1
            index += 1
            continue
        if depth == 1:
            top_level.append(char)
        index += 1

    key_pattern = re.compile(
        r"(?m)^[ \t]*(?:\"([^\"\r\n]+)\"|'([^'\r\n]+)'|([A-Za-z_$][\w$]*))[ \t]*:"
    )
    return tuple(
        sorted(
            match.group(1) or match.group(2) or match.group(3)
            for match in key_pattern.finditer("".join(top_level))
        )
    )


def event_route_problems(repo_root: Path, channels: tuple[PushChannel, ...]) -> "list[str]":
    """Python EVENTS, facade ROUTES, bootstrap handlers, 원장 증거의 독립 폐포."""
    from hwpxfiller.webapp import product_api

    registry_keys = {
        _PRODUCT_API_JS_REL_PATH: set(
            _top_level_object_keys(
                (repo_root / _PRODUCT_API_JS_REL_PATH).read_text(encoding="utf-8"),
                r"\bconst\s+ROUTES\s*=\s*\{",
                label="product_api.js ROUTES",
            )
        ),
        _BOOTSTRAP_JS_REL_PATH: set(
            _top_level_object_keys(
                (repo_root / _BOOTSTRAP_JS_REL_PATH).read_text(encoding="utf-8"),
                r"\bhandlers\s*:\s*\{",
                label="bootstrap.js handlers",
            )
        ),
    }
    events = set(product_api.EVENTS)
    problems: list[str] = []
    for rel, keys in registry_keys.items():
        for name in sorted(events - keys):
            problems.append(f"Python 이벤트에 {rel} handler가 없다: {name}")
        for name in sorted(keys - events):
            problems.append(f"{rel}에만 있는 handler 키: {name}")

    product_rows = [row for row in channels if row.kind == "product_event"]
    rows = {row.name: row for row in product_rows}
    if len(rows) != len(product_rows):
        problems.append("product event 채널 행에 중복 이름이 있다")
    for name in sorted(events):
        row = rows.get(name)
        if row is None:
            problems.append(f"product event 채널 행이 없다: {name}")
            continue
        expected_files = {
            rel for rel, keys in registry_keys.items() if name in keys
        }
        evidence = set(row.consumer_evidence)
        if expected_files and not evidence:
            problems.append(f"활성 라우트인데 원장 소비 증거가 비었다: {name}")
            continue
        for rel in sorted(expected_files - evidence):
            problems.append(f"{name}: 활성 handler 소비 증거가 없다 -> {rel}")
        for rel in sorted(evidence - expected_files):
            problems.append(f"{name}: handler 레지스트리 밖 소비 증거다 -> {rel}")
    return problems


def channel_problems(
    repo_root: Path,
    channels: tuple[PushChannel, ...],
    *,
    controllers: "dict[str, type] | None" = None,
) -> "list[str]":
    controllers = _controller_classes(repo_root) if controllers is None else controllers
    measured = collect_channels(repo_root, controllers=controllers)
    problems = event_route_problems(repo_root, channels)
    declared_keys = [(c.kind, c.name) for c in channels]
    measured_keys = [(c.kind, c.name) for c in measured]
    for key in sorted(set(measured_keys) - set(declared_keys)):
        problems.append(f"채널이 원장에 없다: {key[0]}/{key[1]}")
    for key in sorted(set(declared_keys) - set(measured_keys)):
        problems.append(f"원장에만 있는 유령 채널: {key[0]}/{key[1]}")
    measured_map = {(c.kind, c.name): c for c in measured}
    for row in channels:
        real = measured_map.get((row.kind, row.name))
        if real is None:
            continue
        if row != real:
            problems.append(f"채널 내용 드리프트: {row.kind}/{row.name} — 원장 {row} ≠ 실측 {real}")
    return problems


def vocabulary_problems(repo_root: Path, inventory: TransportInventory) -> "list[str]":
    import gen_bridge_contract

    from hwpxfiller.webapp import product_api

    problems: list[str] = []
    if inventory.protocol != product_api.PROTOCOL:
        problems.append(f"protocol 불일치: {inventory.protocol!r}")
    if inventory.version != product_api.VERSION:
        problems.append(f"version 불일치: {inventory.version!r}")
    if inventory.capabilities != tuple(product_api.CAPABILITIES):
        problems.append(f"capabilities 불일치: {list(inventory.capabilities)}")
    codes = tuple(
        sorted(
            value
            for name, value in vars(product_api).items()
            if name.startswith("CODE_") and isinstance(value, str)
        )
    )
    if inventory.python_error_codes != codes:
        problems.append("python 오류 어휘가 정본과 다르다")
    js_codes = tuple(
        gen_bridge_contract.extract_js_error_codes(
            (repo_root / _PRODUCT_API_JS_REL_PATH).read_text(encoding="utf-8")
        )
    )
    if inventory.js_error_codes != js_codes:
        problems.append("JS 오류 어휘가 정본과 다르다")
    contract = gen_bridge_contract.extract_app_contract(
        (repo_root / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(encoding="utf-8")
    )
    if inventory.rejection_key != contract.rejection_key:
        problems.append("dispatch 거절 봉투 키가 정본과 다르다")
    if inventory.rejection_fields != tuple(contract.rejection_fields):
        problems.append("dispatch 거절 봉투 필드가 정본과 다르다")
    for rel, digest in inventory.input_sha256:
        actual = _sha256_of(repo_root, rel)
        if digest != actual:
            problems.append(f"입력 앵커 불일치: {rel} — 원장 {digest[:12]}… ≠ 실측 {actual[:12]}…")
    return problems


# ------------------------------------------------------------------ 원장 파싱


def parse_ledger(document: "dict[str, object]") -> TransportInventory:
    """커밋 원장 → 인벤토리 — 게이트가 변형 사본으로 음성 대조를 세울 수 있는 형태."""

    def rows(name: str) -> "list[dict]":
        value = document.get(name, [])
        return list(value) if isinstance(value, list) else []

    endpoints = tuple(
        DispatchEndpoint(
            screen=str(row["screen"]),
            action=str(row["action"]),
            required=tuple(row["required"]),
            optional=tuple(row["optional"]),
            zone_mutation=bool(row["zone_mutation"]),
            handler=str(row["handler"]),
            consumer=str(row["consumer"]),
            js_evidence=tuple(row["js_evidence"]),
        )
        for row in rows("endpoint")
    )
    host_methods = tuple(
        HostMethod(
            name=str(row["name"]),
            params=tuple((str(n), bool(o)) for n, o in row["params"]),
            bridge_alias=str(row["bridge_alias"]),
            consumer=str(row["consumer"]),
            python_consumer=str(row["python_consumer"]),
        )
        for row in rows("host_method")
    )
    snapshot_fields = tuple(
        SnapshotField(
            screen=str(row["screen"]),
            field=str(row["field"]),
            producer=str(row["producer"]),
            runtime_observed=bool(row["runtime_observed"]),
            consumer=str(row["consumer"]),
            js_evidence=tuple(row["js_evidence"]),
        )
        for row in rows("snapshot_field")
    )
    channels = tuple(
        PushChannel(
            kind=str(row["kind"]),
            name=str(row["name"]),
            producer=str(row["producer"]),
            fields=tuple(row["fields"]),
            consumer_evidence=tuple(row["consumer_evidence"]),
        )
        for row in rows("channel")
    )
    enablement = tuple(
        Enablement(
            screen=str(row["screen"]),
            handlers=int(row["handlers"]),
            actions=int(row["actions"]),
            enabled=int(row["enabled"]),
            dead_handlers=tuple(row["dead_handlers"]),
            actions_without_handler=tuple(row["actions_without_handler"]),
        )
        for row in rows("dispatch_enablement")
    )
    vocab = document.get("vocabulary", {})
    assert isinstance(vocab, dict)
    bridge = document.get("bridge", {})
    assert isinstance(bridge, dict)
    return TransportInventory(
        endpoints=endpoints,
        host_methods=host_methods,
        bridge_consumed_product=tuple(bridge.get("consumed_product", ())),
        bridge_consumed_selftest=tuple(bridge.get("consumed_selftest", ())),
        snapshot_fields=snapshot_fields,
        channels=channels,
        enablement=enablement,
        protocol=str(vocab.get("protocol", "")),
        version=int(vocab.get("version", 0)),
        capabilities=tuple(vocab.get("capabilities", ())),
        python_error_codes=tuple(vocab.get("python_error_codes", ())),
        js_error_codes=tuple(vocab.get("js_error_codes", ())),
        rejection_key=str(vocab.get("rejection_key", "")),
        rejection_fields=tuple(vocab.get("rejection_fields", ())),
        input_sha256=tuple((str(row["file"]), str(row["sha256"])) for row in rows("input")),
    )


# ------------------------------------------------------------------ 원장 출력

_HEADER = (
    "# 생성 파일 — 직접 편집 금지. P1-02D transport·snapshot·push/event 원장(#516).\n"
    "# 원천: 고정 baseline src/ + frontend 소비자 증거의 결정론 재계측\n"
    f"# 재생성: {REGEN_COMMAND}\n"
    f"# 검사:   {REGEN_COMMAND} --check\n"
    'schema = "transport-graph-02d/v1"\n'
)


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _str_list(values: "tuple[str, ...]") -> str:
    if not values:
        return "[]"
    return "[\n" + "".join(f"  {_q(v)},\n" for v in values) + "]"


def _static_base_digest_pin(repo_root: Path) -> str:
    """02A 원장이 핀한 기반 사실 digest — 같은 baseline src/ 를 쟀다는 교차 앵커.

    재계측하지 않는다: digest↔저장소 검증은 02A 게이트의 단독 소유이고, 여기서 한 번 더
    돌리면 같은 판정이 두 곳에 산다. 이 원장은 그 핀을 나르고, 게이트는 두 원장의 값이
    같은지만 교차 단언한다.
    """
    static_ledger = repo_root / STATIC_LEDGER_REL_PATH
    if not static_ledger.is_file():
        raise FactGraphError(
            f"02A 원장이 없다({STATIC_LEDGER_REL_PATH}) — 02D 는 02A 착지를 전제한다"
        )
    document = tomllib.loads(static_ledger.read_text(encoding="utf-8"))
    digest = document.get("digests", {}).get("base_facts", "")
    if not digest:
        raise FactGraphError("02A 원장에 digests.base_facts 가 없다")
    return str(digest)


def render(repo_root: Path, *, _baseline_checked: bool = False) -> str:
    repo_root = Path(repo_root)
    if not _baseline_checked:
        baseline_problems = _baseline_source_problems(repo_root)
        if baseline_problems:
            raise FactGraphError("; ".join(baseline_problems))
    inventory = build(repo_root)

    consumer_zero_actions = tuple(
        f"{e.screen}/{e.action}" for e in inventory.endpoints if e.consumer == "none_found"
    )
    selftest_only_actions = tuple(
        f"{e.screen}/{e.action}" for e in inventory.endpoints if e.consumer == "selftest_only"
    )
    consumer_zero_snapshot_fields = tuple(
        f"{field.screen}.{field.field}"
        for field in inventory.snapshot_fields
        if field.consumer == "none_found"
    )
    host_internal = tuple(m.name for m in inventory.host_methods if m.consumer == "host_internal")
    unique_keys = sorted({k for e in inventory.endpoints for k in (*e.required, *e.optional)})

    parts = [_HEADER, "\n[baseline]\n"]
    parts.append(f"git_sha = {_q(BASELINE_SHA)}\n")

    parts.append("\n[digests]\n")
    parts.append(f'base_facts_02a = "{_static_base_digest_pin(repo_root)}"\n')
    parts.append(f'transport = "{inventory.digest}"\n')

    parts.append("\n[counts]\n")
    parts.append(f"screens = {len(inventory.enablement)}\n")
    parts.append(f"actions = {len(inventory.endpoints)}\n")
    parts.append(f"payload_required_pairs = {sum(len(e.required) for e in inventory.endpoints)}\n")
    parts.append(f"payload_optional_pairs = {sum(len(e.optional) for e in inventory.endpoints)}\n")
    parts.append(f"payload_unique_keys = {len(unique_keys)}\n")
    parts.append(f"host_methods_public = {len(inventory.host_methods)}\n")
    parts.append(f"host_methods_product = {len(inventory.host_methods) - len(host_internal)}\n")
    parts.append(f"host_methods_internal = {len(host_internal)}\n")
    parts.append(f"bridge_consumed_product = {len(inventory.bridge_consumed_product)}\n")
    parts.append(f"bridge_consumed_selftest = {len(inventory.bridge_consumed_selftest)}\n")
    parts.append(f"snapshot_channels = {len({f.screen for f in inventory.snapshot_fields})}\n")
    parts.append(f"snapshot_fields = {len(inventory.snapshot_fields)}\n")
    parts.append(
        "snapshot_fields_runtime_observed = "
        f"{sum(1 for f in inventory.snapshot_fields if f.runtime_observed)}\n"
    )
    parts.append(
        "snapshot_fields_conditional = "
        f"{sum(1 for f in inventory.snapshot_fields if not f.runtime_observed)}\n"
    )
    for consumer in ("product", "selftest_only", "none_found"):
        parts.append(
            f"snapshot_fields_{consumer} = "
            f"{sum(1 for f in inventory.snapshot_fields if f.consumer == consumer)}\n"
        )
    parts.append(
        f"channels_product_event = "
        f"{sum(1 for c in inventory.channels if c.kind == 'product_event')}\n"
    )
    parts.append(
        f"channels_partial_push = "
        f"{sum(1 for c in inventory.channels if c.kind == 'partial_push')}\n"
    )
    parts.append(
        f"channels_selftest_host_op = "
        f"{sum(1 for c in inventory.channels if c.kind == 'selftest_host_op')}\n"
    )
    product_events = tuple(c for c in inventory.channels if c.kind == "product_event")
    parts.append(f"product_event_fields = {sum(len(c.fields) for c in product_events)}\n")
    parts.append(
        "product_event_fields_conditional = "
        f"{sum(field.endswith('?') for c in product_events for field in c.fields)}\n"
    )
    parts.append(
        "product_event_consumer_zero = "
        f"{sum(not c.consumer_evidence for c in product_events)}\n"
    )
    parts.append(f"consumer_zero_actions = {len(consumer_zero_actions)}\n")
    parts.append(f"selftest_only_actions = {len(selftest_only_actions)}\n")
    parts.append(f"dead_handlers = {sum(len(e.dead_handlers) for e in inventory.enablement)}\n")
    parts.append(
        "actions_without_handler = "
        f"{sum(len(e.actions_without_handler) for e in inventory.enablement)}\n"
    )

    parts.append("\n[vocabulary]\n")
    parts.append(f"protocol = {_q(inventory.protocol)}\n")
    parts.append(f"version = {inventory.version}\n")
    parts.append(f"capabilities = {_str_list(inventory.capabilities)}\n")
    parts.append(f"python_error_codes = {_str_list(inventory.python_error_codes)}\n")
    parts.append(f"js_error_codes = {_str_list(inventory.js_error_codes)}\n")
    parts.append(f"rejection_key = {_q(inventory.rejection_key)}\n")
    parts.append(f"rejection_fields = {_str_list(inventory.rejection_fields)}\n")

    parts.append("\n[bridge]\n")
    parts.append(f"consumed_product = {_str_list(inventory.bridge_consumed_product)}\n")
    parts.append(f"consumed_selftest = {_str_list(inventory.bridge_consumed_selftest)}\n")

    parts.append("\n# 소비자 0 / 시험 전용 소비 endpoint — loud 분리(#516 완료 조건).\n")
    parts.append("[consumer_zero]\n")
    parts.append(f"actions = {_str_list(consumer_zero_actions)}\n")
    parts.append(f"selftest_only_actions = {_str_list(selftest_only_actions)}\n")
    parts.append(f"snapshot_fields = {_str_list(consumer_zero_snapshot_fields)}\n")
    parts.append(f"host_internal_methods = {_str_list(host_internal)}\n")

    parts.append("\n# src/ 밖 입력의 정체 앵커 — baseline SHA 가 못 봉하는 절반.\n")
    for rel, digest in inventory.input_sha256:
        parts.append("\n[[input]]\n")
        parts.append(f"file = {_q(rel)}\n")
        parts.append(f'sha256 = "{digest}"\n')

    parts.append("\n# 02A 인계 — prefix dispatch 복원 폐포 중 registry 가 실제로 켜는 부분집합.\n")
    for row in inventory.enablement:
        parts.append("\n[[dispatch_enablement]]\n")
        parts.append(f"screen = {_q(row.screen)}\n")
        parts.append(f"handlers = {row.handlers}\n")
        parts.append(f"actions = {row.actions}\n")
        parts.append(f"enabled = {row.enabled}\n")
        parts.append(f"dead_handlers = {_str_list(row.dead_handlers)}\n")
        parts.append(f"actions_without_handler = {_str_list(row.actions_without_handler)}\n")

    for row in inventory.endpoints:
        parts.append("\n[[endpoint]]\n")
        parts.append(f"screen = {_q(row.screen)}\n")
        parts.append(f"action = {_q(row.action)}\n")
        parts.append(f"required = {_str_list(row.required)}\n")
        parts.append(f"optional = {_str_list(row.optional)}\n")
        parts.append(f"zone_mutation = {'true' if row.zone_mutation else 'false'}\n")
        parts.append(f"handler = {_q(row.handler)}\n")
        parts.append(f"consumer = {_q(row.consumer)}\n")
        parts.append(f"js_evidence = {_str_list(row.js_evidence)}\n")

    for method in inventory.host_methods:
        parts.append("\n[[host_method]]\n")
        parts.append(f"name = {_q(method.name)}\n")
        params = ", ".join(
            f"[{_q(param)}, {'true' if optional else 'false'}]" for param, optional in method.params
        )
        parts.append(f"params = [{params}]\n")
        parts.append(f"bridge_alias = {_q(method.bridge_alias)}\n")
        parts.append(f"consumer = {_q(method.consumer)}\n")
        parts.append(f"python_consumer = {_q(method.python_consumer)}\n")

    for field in inventory.snapshot_fields:
        parts.append("\n[[snapshot_field]]\n")
        parts.append(f"screen = {_q(field.screen)}\n")
        parts.append(f"field = {_q(field.field)}\n")
        parts.append(f"producer = {_q(field.producer)}\n")
        parts.append(f"runtime_observed = {'true' if field.runtime_observed else 'false'}\n")
        parts.append(f"consumer = {_q(field.consumer)}\n")
        parts.append(f"js_evidence = {_str_list(field.js_evidence)}\n")

    for channel in inventory.channels:
        parts.append("\n[[channel]]\n")
        parts.append(f"kind = {_q(channel.kind)}\n")
        parts.append(f"name = {_q(channel.name)}\n")
        parts.append(f"producer = {_q(channel.producer)}\n")
        parts.append(f"fields = {_str_list(channel.fields)}\n")
        parts.append(f"consumer_evidence = {_str_list(channel.consumer_evidence)}\n")

    return "".join(parts)


def check(repo_root: Path) -> "list[str]":
    repo_root = Path(repo_root)
    baseline_problems = _baseline_source_problems(repo_root)
    if baseline_problems:
        return baseline_problems
    target = repo_root / LEDGER_REL_PATH
    expected = render(repo_root, _baseline_checked=True)
    if not target.is_file():
        return [f"{LEDGER_REL_PATH}: 생성물이 없습니다 — `{REGEN_COMMAND}` 로 생성하세요."]
    if target.read_text(encoding="utf-8") == expected:
        return []
    problems = [f"{LEDGER_REL_PATH}: 원장 드리프트 — `{REGEN_COMMAND}` 로 재생성하세요."]
    try:
        actual_digests = tomllib.loads(target.read_text(encoding="utf-8")).get("digests", {})
        expected_digests = tomllib.loads(expected).get("digests", {})
        for key in sorted(set(actual_digests) | set(expected_digests)):
            if actual_digests.get(key) != expected_digests.get(key):
                problems.append(
                    f"  digest {key}: 커밋본 {actual_digests.get(key)} ≠ "
                    f"재계측 {expected_digests.get(key)}"
                )
    except tomllib.TOMLDecodeError as exc:
        problems.append(f"  커밋본을 파싱할 수 없다(직접 편집 흔적?): {exc}")
    return problems


def rewrite(repo_root: Path) -> Path:
    repo_root = Path(repo_root)
    target = repo_root / LEDGER_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(repo_root), encoding="utf-8", newline="\n")
    return target
