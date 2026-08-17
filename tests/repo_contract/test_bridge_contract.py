"""Python↔TypeScript 제품 브리지의 생성물과 공개 표면을 대조한다."""

from __future__ import annotations

import re

import gen_bridge_contract as gen
from _web_source import (
    _frontend_sources,
    _js_masks,
    _resolve_frontend_module,
    source_text,
)
from hwpxfiller.application import template_change_product
from hwpxfiller.webapp import product_api
from hwpxfiller.webapp.action_registry import ACTION_REGISTRY
from hwpxfiller.webapp.app import _DISPATCH_REJECTION_KEY, WebFrontend


def _generated() -> str:
    return source_text("src", "contract", "contract.gen.ts")


def _const_array(text: str, name: str) -> list[str]:
    match = re.search(
        rf"export const {name} = \[\n(?P<body>(?:  \"[^\"\n]+\",\n)*)\] as const;",
        text,
    )
    return [] if match is None else re.findall(r'"([^"]+)"', match.group("body"))


def _screen_actions(text: str) -> dict[str, dict[str, tuple[list[str], list[str]]]]:
    lines = text.splitlines()
    result: dict[str, dict[str, tuple[list[str], list[str]]]] = {}
    screen: str | None = None
    for line in lines[lines.index("export const SCREEN_ACTIONS = {") + 1 :]:
        if line == "} as const;":
            break
        if opened := re.fullmatch(r"  (\w+): \{", line):
            screen = opened.group(1)
            result[screen] = {}
        elif line == "  },":
            screen = None
        elif screen and (
            entry := re.fullmatch(
                r"    (\w+): \{ required: \[(.*?)\], optional: \[(.*?)\] \},",
                line,
            )
        ):
            result[screen][entry.group(1)] = (
                re.findall(r'"([^"]+)"', entry.group(2)),
                re.findall(r'"([^"]+)"', entry.group(3)),
            )
    return result


def _runtime_rejection_fields() -> list[str]:
    frontend = WebFrontend.__new__(WebFrontend)
    frontend.controllers = {}
    rejected = frontend.dispatch("unknown", "unknown", {})
    assert set(rejected) == {_DISPATCH_REJECTION_KEY}
    return list(rejected[_DISPATCH_REJECTION_KEY])


def _js_error_codes() -> list[str]:
    lines = source_text("src", "product_api.js").splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if "PRODUCT_ERROR_CODES = Object.freeze({" in line
    )
    result: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() == "});":
            break
        if entry := re.fullmatch(r'\s*[A-Z_]+:\s*"([a-z_]+)",?', line):
            result.append(entry.group(1))
    return result


def test_generated_bridge_contract_is_current() -> None:
    problems = gen.check()
    assert not problems, (
        "브리지 계약 드리프트: "
        + "; ".join(problems)
        + " — python scripts/gen_bridge_contract.py 로 재생성하세요."
    )


def test_generated_bridge_contract_matches_independent_public_boundaries() -> None:
    text = _generated()
    expected_arrays = {
        "PRODUCT_CAPABILITIES": list(product_api.CAPABILITIES),
        "PYTHON_ERROR_CODES": [
            value
            for name, value in vars(product_api).items()
            if name.startswith("CODE_") and isinstance(value, str)
        ],
        "JS_PRODUCT_ERROR_CODES": _js_error_codes(),
        # 템플릿 변경 status 어휘(S3-09) — 정본 튜플과의 동치. 웹이 내부 어휘를 직접 보지
        # 않는 opaque 계약이라, 이 배열이 곧 웹에 허용된 status 전집이다.
        "TEMPLATE_PREPARATION_STATUSES": list(
            template_change_product.PRODUCT_PREPARATION_STATUSES
        ),
        "TEMPLATE_APPLY_STATUSES": list(template_change_product.PRODUCT_APPLY_STATUSES),
        "HOST_METHODS": [
            name
            for name, value in vars(WebFrontend).items()
            if not name.startswith("_") and callable(value)
        ],
    }
    called = set(
        re.findall(r"window\.pywebview\.api\.([a-z_]+)\(", source_text("js", "bridge.js"))
    )
    expected_arrays["HOST_INTERNAL_METHODS"] = [
        name for name in expected_arrays["HOST_METHODS"] if name not in called
    ]

    failures = [
        f"{name}: generated={_const_array(text, name)!r}, source={expected!r}"
        for name, expected in expected_arrays.items()
        if _const_array(text, name) != expected
    ]
    if f"export const PRODUCT_VERSION = {product_api.VERSION};" not in text:
        failures.append("PRODUCT_VERSION")
    if f'export const PRODUCT_PROTOCOL = "{product_api.PROTOCOL}";' not in text:
        failures.append("PRODUCT_PROTOCOL")
    if f'export const DISPATCH_REJECTION_KEY = "{_DISPATCH_REJECTION_KEY}";' not in text:
        failures.append("DISPATCH_REJECTION_KEY")
    fields = ", ".join(f'"{field}"' for field in _runtime_rejection_fields())
    if f"export const DISPATCH_REJECTION_FIELDS = [{fields}] as const;" not in text:
        failures.append("DISPATCH_REJECTION_FIELDS")

    generated_actions = _screen_actions(text)
    expected_actions = {
        screen: {
            action: (sorted(schema.required), sorted(schema.optional))
            for action, schema in actions.items()
        }
        for screen, actions in ACTION_REGISTRY.items()
    }
    if generated_actions != expected_actions:
        failures.append("SCREEN_ACTIONS")
    assert not failures, "\n".join(failures)


GENERATED_CONTRACT = "frontend/src/contract/contract.gen.ts"

#: production frontend 이 **값으로** 소비해야 하는 생성 계약 어휘. type-only import 는 이 집합을
#: 못 채운다 — display 코드가 backend-파생 값을 실제로 렌더한다는 증거다(SG-03 C5). 정본
#: `docs/CONTROL_PLANE_SCOPE.md` §backend-only semantic authority.
_EXPECTED_CONSUMED_GENERATED_VALUES = frozenset(
    {
        "SCREEN_ACTIONS",         # 화면·액션 어휘(routing/dispatch)
        "HOST_METHODS",           # host bridge method 어휘
        "HOST_INTERNAL_METHODS",  # 직접 브리지(비-dispatch) method 어휘
        "DISPATCH_REJECTION_KEY",  # dispatch 거절 프로토콜 키
    }
)


def _generated_value_exports(sources: dict[str, str]) -> set[str]:
    return set(re.findall(r"export const (\w+)", sources[GENERATED_CONTRACT]))


def _generated_value_consumption(sources: dict[str, str]) -> set[str]:
    """production frontend 이 contract.gen.ts 에서 **값으로 import 하고 참조하는** 상수 이름 집합.

    parity 의 나머지 반쪽: 생성 계약이 backend 단일 출처와 일치함(위 두 테스트)에 더해, 표시
    모듈이 그 계약의 **값**을 실제 소비한다는 것. ``import type { … }`` 절 전체와 절 안의 인라인
    ``type X`` specifier 는 세지 않는다 — type-only import 로는 어휘 재저작을 못 막기 때문이다.
    import 이후 코드 mask 에서 다시 참조돼야(≥2회 등장) 소비로 인정한다.
    """
    value_exports = _generated_value_exports(sources)
    consumed: set[str] = set()
    for relative, source in sources.items():
        if relative == GENERATED_CONTRACT:
            continue
        _comment, code = _js_masks(source)
        for match in re.finditer(
            r'import\s+(type\s+)?\{([^}]*)\}\s*from\s*["\']([^"\']+)["\']', source
        ):
            type_clause, clause, specifier = match.group(1), match.group(2), match.group(3)
            if type_clause:
                continue  # 절 전체가 type import
            if _resolve_frontend_module(relative, specifier, sources) != GENERATED_CONTRACT:
                continue
            for raw in clause.split(","):
                specifier_name = raw.strip()
                if not specifier_name or specifier_name.startswith("type "):
                    continue
                binding = (
                    specifier_name.split(" as ")[-1].strip()
                    if " as " in specifier_name
                    else specifier_name
                )
                if binding not in value_exports:
                    continue
                references = re.findall(rf"(?<![\w$]){re.escape(binding)}(?![\w$])", code)
                if len(references) >= 2:  # import + 최소 1회 사용
                    consumed.add(binding)
    return consumed


def test_frontend_display_consumes_generated_contract_values() -> None:
    """SG-03(#735) C5 — backend projection ↔ frontend 표시 parity 의 기전 pin.

    위 두 테스트는 생성 계약 ``contract.gen.ts`` 가 backend 단일 출처(error code·status·action·
    host method 어휘)와 정확히 일치함을 판정한다. 이 테스트는 나머지 반쪽을 잠근다: **production
    frontend 이 그 생성 계약의 값을 실제 소비해 표시한다** — 단순 import 존재(특히 type-only)가
    아니라 생성 **값**을 참조한다. 두 사실이 붙어야 "표시 = backend projection" parity 가 드리프트
    없이 성립한다(어휘 손 재작성 금지). 새 parity harness 를 짓지 않는다는 규율은 이 재사용이 지킨다.
    """
    sources = _frontend_sources()
    assert GENERATED_CONTRACT in sources, "생성 계약 모듈이 frontend source 에 없다"
    consumed = _generated_value_consumption(sources)
    missing = _EXPECTED_CONSUMED_GENERATED_VALUES - consumed
    assert not missing, (
        f"production frontend 이 생성 계약 값을 소비하지 않는다: {sorted(missing)} — type-only "
        "import 로 대체됐거나 어휘를 손으로 재작성했다. 표시 어휘가 backend-파생 단일 출처에서 "
        "온다는 parity 근거가 사라진다."
    )


def test_negative_probe_type_only_import_fails_c5_parity() -> None:
    """실 C5 게이트 함수가 정확한 회피(값→type-only import 전환)에 RED 되는지 본다."""
    value_source = (
        'import { SCREEN_ACTIONS } from "../contract/contract.gen.ts";\n'
        "export const routes = Object.keys(SCREEN_ACTIONS);\n"
    )
    type_only_source = (
        'import type { SCREEN_ACTIONS } from "../contract/contract.gen.ts";\n'
        "export const routes = [] as SCREEN_ACTIONS[];\n"
    )
    base = {GENERATED_CONTRACT: 'export const SCREEN_ACTIONS = {} as const;\n'}

    consuming = _generated_value_consumption(
        {**base, "frontend/src/screens/probe.ts": value_source}
    )
    assert "SCREEN_ACTIONS" in consuming  # 값 소비 → 통과

    type_only = _generated_value_consumption(
        {**base, "frontend/src/screens/probe.ts": type_only_source}
    )
    assert "SCREEN_ACTIONS" not in type_only  # type-only → 소비 아님 → 실 게이트가 RED
