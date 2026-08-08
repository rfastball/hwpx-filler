"""P1-02D transport 축 — screen/action·직접 host 메서드·snapshot·push/event 전수 원장(#516).

React↔Python 경계의 **모든 transport endpoint** 를 실제 Python producer 와 JS 소비자 증거에
연결한다. 정본은 이미 있는 실물이다 — ``webapp/action_registry.py``(화면×액션×payload 키),
``webapp/app.py`` 의 ``WebFrontend`` js_api 공개 표면, ``frontend/js/bridge.js``(제품 JS 의
유일한 호스트 통로, N-07), ``webapp/product_api.py``(Python→웹 이벤트 4채널),
``webapp/selftest_api.py``(시험 전용 별도 계정) — 여기서는 새 어휘를 발명하지 않고 그것들을
**전수로 세고 연결이 닫히는지**를 기계 술어로 만든다.

이 축의 불변식(#516)은 어휘가 아니라 구분이다:

- endpoint 가 **존재한다**는 것과 **실소비자가 있다**는 것을 다른 열로 적는다. JS 소비자
  증거는 인용 리터럴 실측(FACT)이고, 소비자 분류(``product``/``selftest_only``/
  ``none_found``)는 그 실측의 요약이다 — 리터럴이 없는데 소비가 있는 경로(동적 이름 조립)는
  이 저장소가 정적 폐포 계약으로 금지하므로 요약이 사실을 넘지 않는다.
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
import re
import tempfile
import tomllib
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

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
    """스냅샷 채널(화면)의 최상위 필드 하나 — Python producer 귀속이 완료된 사실."""

    screen: str
    field: str
    producer: str  # ``module:Class.snapshot#method``
    runtime_observed: bool  # 빈 상태 initial() 실측에서 보였는가(거짓 = 조건부 방출 선언)


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


def _quoted_evidence(corpus: "dict[str, str]", token: str) -> tuple[str, ...]:
    """프런트에서 ``"token"``/``'token'`` 인용 리터럴이 실재하는 파일 — 이름 단위 FACT."""
    pattern = re.compile(rf"[\"']{re.escape(token)}[\"']")
    return tuple(sorted(rel for rel, text in corpus.items() if pattern.search(text)))


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
            evidence = _quoted_evidence(corpus, action)
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
            rows.append(
                SnapshotField(
                    screen=screen,
                    field=field,
                    producer=producer,
                    runtime_observed=field in observed,
                )
            )
    return tuple(rows)


# ---------------------------------------------------------- push/event 채널


def _product_event_producers(repo_root: Path) -> "dict[str, str]":
    """이벤트 값 → ``ProductApiClient`` 발신 메서드 symbol — ``_deliver(EVENT_X, …)`` 실측."""
    from hwpxfiller.webapp import product_api

    module_path = repo_root / "src" / "hwpxfiller" / "webapp" / "product_api.py"
    class_node = _class_def(module_path, "ProductApiClient")
    producers: dict[str, str] = {}
    for node in class_node.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "_deliver"
                and call.args
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id.startswith("EVENT_")
            ):
                event_value = getattr(product_api, call.args[0].id)
                producers[event_value] = (
                    f"hwpxfiller.webapp.product_api:ProductApiClient.{node.name}#method"
                )
    return producers


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
    product_api_js = (repo_root / _PRODUCT_API_JS_REL_PATH).read_text(encoding="utf-8")
    producers = _product_event_producers(repo_root)
    channels: list[PushChannel] = []
    for event in product_api.EVENTS:
        producer = producers.get(event, "")
        if not producer:
            raise FactGraphError(f"이벤트 {event!r} 의 발신 메서드를 찾지 못했다")
        evidence: tuple[str, ...] = ()
        if re.search(rf"[\"']{re.escape(event)}[\"']", product_api_js):
            evidence = (_PRODUCT_API_JS_REL_PATH,)
        channels.append(
            PushChannel(
                kind="product_event",
                name=event,
                producer=producer,
                fields=(),
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
) -> "list[str]":
    controllers = _controller_classes(repo_root) if controllers is None else controllers
    runtime_fields = (
        _runtime_snapshot_fields(repo_root) if runtime_fields is None else runtime_fields
    )
    problems: list[str] = []
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
        declared = set(_static_snapshot_keys(repo_root, cls))
        observed = set(runtime_fields.get(screen, ()))
        rows = by_screen[screen]
        for field in sorted(declared - set(rows)):
            problems.append(f"{screen}: producer 미분류 스냅샷 필드 -> {field}")
        for field in sorted(set(rows) - declared):
            problems.append(f"{screen}: 원장에만 있는 유령 필드 -> {field}")
        producer = _method_symbol(cls, "snapshot")
        for field in sorted(set(rows) & declared):
            row = rows[field]
            if row.producer != producer:
                problems.append(
                    f"{screen}.{field}: producer 귀속 불일치 — {row.producer!r} ≠ {producer!r}"
                )
            if row.runtime_observed != (field in observed):
                problems.append(f"{screen}.{field}: 빈 상태 실측 표지가 실측과 다르다")
    return problems


def channel_problems(
    repo_root: Path,
    channels: tuple[PushChannel, ...],
    *,
    controllers: "dict[str, type] | None" = None,
) -> "list[str]":
    controllers = _controller_classes(repo_root) if controllers is None else controllers
    measured = collect_channels(repo_root, controllers=controllers)
    problems: list[str] = []
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
