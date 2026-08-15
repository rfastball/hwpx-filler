"""Python↔TypeScript 제품 브리지의 생성물과 공개 표면을 대조한다."""

from __future__ import annotations

import re

import gen_bridge_contract as gen
from _web_source import source_text
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
