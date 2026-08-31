#!/usr/bin/env python3
"""Python↔TypeScript 브리지 계약 — 실물 정본 → ``contract.gen.ts`` 재생성/드리프트 검사 (R2-02 · #406).

새 스키마 파일을 발명하지 않는다 — 정본은 이미 있는 실물 넷이다:

- ``webapp/action_registry.py``   화면×액션×payload 키 (순수 데이터 모듈 — **import**)
- ``webapp/product_api.py``       프로토콜·버전·capability 순서·kebab 오류 어휘 (**import**)
- ``webapp/app.py``               ``WebFrontend`` js_api 공개 표면 24 + 거절 봉투 (**AST** —
  창 경로를 import 하지 않는다. 공개 표면의 런타임 제2 엔진은 드리프트 게이트의 오러클이 진다)
- ``frontend/src/product_api.js`` JS snake 오류 어휘 6 (**독립 판독** — HOST_OPS 선례)

생성물 ``frontend/src/contract/contract.gen.ts`` 는 커밋되는 소스이고 손으로 고치지 않는다
(드리프트 게이트 ``tests/repo_contract/test_bridge_contract.py`` 가 재생성 바이트 비교 + 생성기와 코드를
공유하지 않는 독립 내용 오러클로 지킨다 — 패킷 rev3 §4.1).

    python scripts/gen_bridge_contract.py           # 재생성
    python scripts/gen_bridge_contract.py --check   # 드리프트 검사(어긋나면 non-zero)

stdlib + 정본 import 만 쓴다. dev/CI 전용이며 앱 실행 시 돌지 않는다.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hwpxfiller.application import document_creation_vocabulary as vocab  # noqa: E402
from hwpxfiller.application.template_change_product import (  # noqa: E402
    PRODUCT_APPLY_STATUSES,
    PRODUCT_PREPARATION_STATUSES,
)
from hwpxfiller.application.workbench_execution_status import (  # noqa: E402
    WORKBENCH_EXECUTION_STATUS_CODES,
)
from hwpxfiller.webapp import product_api  # noqa: E402
from hwpxfiller.webapp.action_registry import ACTION_REGISTRY  # noqa: E402

APP_PY = ROOT / "src" / "hwpxfiller" / "webapp" / "app.py"
PRODUCT_API_JS = ROOT / "frontend" / "src" / "product_api.js"
OUTPUT = ROOT / "frontend" / "src" / "contract" / "contract.gen.ts"

#: host-internal 표면의 **기록**(패킷 §4.1) — 웹 소비자 0 인 공개 메서드. 지우지도 승격하지도
#: 않는다. 이 값이 실측과 어긋나면(브리지가 부르기 시작하면) 오러클의 bridge.js 대조가 잡는다.
HOST_INTERNAL_METHODS = ("close_guard_state",)


# ------------------------------------------------------------------ 추출


@dataclass(frozen=True)
class AppContract:
    """``app.py`` 에서 AST 로 뜬 웹→Python 표면."""

    rejection_key: str
    rejection_fields: "tuple[str, ...]"
    #: (이름, ((인자, 선택 여부), ...)) — 클래스 본문 정의 순서 그대로.
    methods: "tuple[tuple[str, tuple[tuple[str, bool], ...]], ...]"


def extract_app_contract(source: "str | None" = None) -> AppContract:
    """``WebFrontend`` 공개 표면과 거절 봉투를 AST 로 뜬다 — import 부작용 없음."""
    tree = ast.parse(APP_PY.read_text(encoding="utf-8") if source is None else source)

    rejection_key = None
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_DISPATCH_REJECTION_KEY"
            and isinstance(node.value, ast.Constant)
        ):
            rejection_key = node.value.value
    if not isinstance(rejection_key, str):
        raise SystemExit("app.py 에서 _DISPATCH_REJECTION_KEY 리터럴을 찾지 못했습니다.")

    cls = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "WebFrontend"),
        None,
    )
    if cls is None:
        raise SystemExit("app.py 에서 WebFrontend 클래스를 찾지 못했습니다.")

    methods = []
    for stmt in cls.body:
        if not isinstance(stmt, ast.FunctionDef) or stmt.name.startswith("_"):
            continue
        positional = [a.arg for a in (stmt.args.posonlyargs + stmt.args.args)]
        first_optional = len(positional) - len(stmt.args.defaults)
        params = tuple(
            (name, index >= first_optional)
            for index, name in enumerate(positional)
            if name != "self"
        )
        methods.append((stmt.name, params))
    if not methods:
        raise SystemExit("WebFrontend 공개 메서드를 하나도 찾지 못했습니다.")

    dispatch = next(
        (s for s in cls.body if isinstance(s, ast.FunctionDef) and s.name == "dispatch"), None
    )
    if dispatch is None:
        raise SystemExit("WebFrontend.dispatch 를 찾지 못했습니다.")
    fields: "tuple[str, ...] | None" = None
    for node in ast.walk(dispatch):
        if (
            isinstance(node, ast.Dict)
            and len(node.keys) == 1
            and isinstance(node.keys[0], ast.Name)
            and node.keys[0].id == "_DISPATCH_REJECTION_KEY"
            and isinstance(node.values[0], ast.Dict)
        ):
            inner = node.values[0]
            if all(isinstance(k, ast.Constant) for k in inner.keys):
                fields = tuple(k.value for k in inner.keys)  # type: ignore[union-attr]
    if not fields:
        raise SystemExit("dispatch 의 거절 봉투 내부 키를 AST 에서 찾지 못했습니다.")

    return AppContract(rejection_key, fields, tuple(methods))


def extract_js_error_codes(source: "str | None" = None) -> "tuple[str, ...]":
    """``product_api.js`` 의 snake 오류 어휘 — 생성기 소유의 독립 판독."""
    text = PRODUCT_API_JS.read_text(encoding="utf-8") if source is None else source
    match = re.search(
        r"PRODUCT_ERROR_CODES\s*=\s*Object\.freeze\(\{(?P<body>.*?)\}\)", text, re.S
    )
    if match is None:
        raise SystemExit("product_api.js 에서 PRODUCT_ERROR_CODES 블록을 찾지 못했습니다.")
    codes = tuple(re.findall(r':\s*"([a-z_]+)"', match.group("body")))
    if not codes:
        raise SystemExit("PRODUCT_ERROR_CODES 에서 코드 값을 하나도 읽지 못했습니다.")
    return codes


def python_error_codes() -> "tuple[str, ...]":
    """``product_api.py`` 의 kebab 오류 어휘 — 정의 순서 그대로."""
    return tuple(
        value
        for name, value in vars(product_api).items()
        if name.startswith("CODE_") and isinstance(value, str)
    )


# ------------------------------------------------------------------ 렌더


def _string_array(name: str, values: "tuple[str, ...]") -> "list[str]":
    lines = [f"export const {name} = ["]
    lines += [f'  "{value}",' for value in values]
    lines.append("] as const;")
    return lines


def _keys(values: "frozenset[str]") -> str:
    return "[" + ", ".join(f'"{k}"' for k in sorted(values)) + "]"


def render_contract(
    app: "AppContract | None" = None,
    registry: "object | None" = None,
    js_codes: "tuple[str, ...] | None" = None,
) -> str:
    """생성물 전문. 인자 주입은 음성 대조(드리프트 게이트의 판별력 증명)용이다."""
    app = extract_app_contract() if app is None else app
    registry = ACTION_REGISTRY if registry is None else registry
    js_codes = extract_js_error_codes() if js_codes is None else js_codes

    lines = [
        "/* 자동 생성 — 손으로 고치지 않는다 (scripts/gen_bridge_contract.py · R2-02 #406).",
        " *",
        " * 정본: webapp/action_registry.py · webapp/product_api.py · webapp/app.py(WebFrontend)",
        " * · frontend/src/product_api.js(PRODUCT_ERROR_CODES). 드리프트 게이트:",
        " * tests/repo_contract/test_bridge_contract.py (재생성 바이트 비교 + 생성기 비경유 독립 오러클).",
        " *",
        " * v1 계약의 payload 값 타입은 **키 집합**이다 — 값은 도메인 컨트롤러 소유라 unknown",
        " * 이 정직한 번역이고, 더 좁히면 그게 조용한 추측이다(action_registry.py:16). */",
        "",
        f'export const PRODUCT_PROTOCOL = "{product_api.PROTOCOL}";',
        "",
        f"export const PRODUCT_VERSION = {product_api.VERSION};",
        "",
        "/* 순서가 계약이다 — 파사드 describe() 배열과 같은 순서로 읽힌다(product_api.py:60). */",
        *_string_array("PRODUCT_CAPABILITIES", tuple(product_api.CAPABILITIES)),
        "",
        "export type ProductCapability = (typeof PRODUCT_CAPABILITIES)[number];",
        "",
        "/* Python 어댑터(kebab)와 제품 JS(snake)의 오류 어휘는 **경로가 다르다**: kebab 은",
        " * Python 이 웹→Python·Python→웹 왕복을 판정하며 내는 코드, snake 는 제품 파사드",
        " * deliver() 가 돌려주는 코드다. 통합·번역은 이 단계 비소유 — 여기는 사실의 등재다. */",
        *_string_array("PYTHON_ERROR_CODES", python_error_codes()),
        "",
        "export type PythonErrorCode = (typeof PYTHON_ERROR_CODES)[number];",
        "",
        *_string_array("JS_PRODUCT_ERROR_CODES", js_codes),
        "",
        "export type JsProductErrorCode = (typeof JS_PRODUCT_ERROR_CODES)[number];",
        "",
        "/* 템플릿 변경 확인·적용의 제품 status 어휘(S3-09 #659) — 내부 Preparation/Change/Apply",
        " * 상태의 투영이고 정본은 application/template_change_product.py 다. 내부 어휘를 웹이",
        " * 직접 보지 않는다(opaque Product Contract). */",
        *_string_array("TEMPLATE_PREPARATION_STATUSES", PRODUCT_PREPARATION_STATUSES),
        "",
        "export type TemplatePreparationStatus = (typeof TEMPLATE_PREPARATION_STATUSES)[number];",
        "",
        *_string_array("TEMPLATE_APPLY_STATUSES", PRODUCT_APPLY_STATUSES),
        "",
        "export type TemplateApplyStatus = (typeof TEMPLATE_APPLY_STATUSES)[number];",
        "",
        f'export const DISPATCH_REJECTION_KEY = "{app.rejection_key}";',
        "",
        "export const DISPATCH_REJECTION_FIELDS = "
        + "[" + ", ".join(f'"{f}"' for f in app.rejection_fields) + "] as const;",
        "",
        "/* 화면×액션×payload 키 — validate_dispatch 가 거절의 정본이고 이 표는 그 타입 투영이다. */",
        "export const SCREEN_ACTIONS = {",
    ]
    for screen, actions in registry.items():  # type: ignore[attr-defined]
        lines.append(f"  {screen}: {{")
        for action, schema in actions.items():
            lines.append(
                f"    {action}: {{ required: {_keys(schema.required)},"
                f" optional: {_keys(schema.optional)} }},"
            )
        lines.append("  },")
    lines += [
        "} as const;",
        "",
        "export type ScreenName = keyof typeof SCREEN_ACTIONS;",
        "",
        "export type ActionName<S extends ScreenName> = keyof (typeof SCREEN_ACTIONS)[S] & string;",
        "",
        "/* WebFrontend js_api 공개 표면 — 클래스 본문 정의 순서 그대로. */",
        *_string_array("HOST_METHODS", tuple(name for name, _ in app.methods)),
        "",
        "export type HostMethodName = (typeof HOST_METHODS)[number];",
        "",
        "/* 웹 소비자 0 인 host-internal 표면의 기록 — 지우지도 승격하지도 않는다(패킷 §4.1). */",
        *_string_array("HOST_INTERNAL_METHODS", HOST_INTERNAL_METHODS),
        "",
        "export type HostInternalMethodName = (typeof HOST_INTERNAL_METHODS)[number];",
        "",
        "export interface HostApi {",
    ]
    for name, params in app.methods:
        rendered = ", ".join(
            f"{param}?: unknown" if optional else f"{param}: unknown"
            for param, optional in params
        )
        lines.append(f"  {name}({rendered}): unknown;")
    lines += ["}", ""]
    lines += [
        "/* 문서 만들기 작업대 blocker 계열(SX-01 #724 §3) — 정의 순서가 곧 우선순위 기반이다.",
        " * 정본: application/document_creation_vocabulary.py. React 가 이 순서를 재구현하지 않는다",
        " * (blocker 합성은 backend Product 계약이 진다). */",
        *_string_array("DOCUMENT_CREATION_BLOCKERS", vocab.BLOCKER_CODES),
        "",
        "export type DocumentCreationBlocker = (typeof DOCUMENT_CREATION_BLOCKERS)[number];",
        "",
        "/* Primary Action 코드 — 우선순위 순서(#724 §3). 첫 원소가 최우선, 마지막이",
        " * CREATE_DOCUMENTS. 표시층은 이 순서를 재계산하지 않고 backend 가 고른 하나를 소비한다. */",
        *_string_array("PRIMARY_ACTIONS", vocab.PRIMARY_ACTION_CODES),
        "",
        "export type PrimaryAction = (typeof PRIMARY_ACTIONS)[number];",
        "",
        "/* 작업대 execution status 7상태(SX-03 #726 §3) — orchestration+sealability+",
        " * admission verdict 의 재라벨. 정본: application/workbench_execution_status.py. 표시층은",
        " * 이 코드를 재판정하지 않고 backend 가 파생한 하나를 소비한다(문안은 STATUS_PHRASE 정본). */",
        *_string_array("WORKBENCH_EXECUTION_STATUSES", WORKBENCH_EXECUTION_STATUS_CODES),
        "",
        "export type WorkbenchExecutionStatus = (typeof WORKBENCH_EXECUTION_STATUSES)[number];",
        "",
        "/* RunDeliveryIntent collision policy(#724 §8) — 기본 ADD_SUFFIX, overwrite 는 명시 선택. */",
        *_string_array("COLLISION_POLICIES", vocab.COLLISION_POLICIES),
        "",
        "export type CollisionPolicy = (typeof COLLISION_POLICIES)[number];",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ 검사/재생성


def check() -> "list[str]":
    """디스크 생성물이 정본과 일치하는지 — 문제 목록 반환(빈 리스트=동기화됨)."""
    expected = render_contract()
    if not OUTPUT.is_file():
        return [f"{OUTPUT.name}: 생성물이 없습니다 — 재생성하세요."]
    if OUTPUT.read_text(encoding="utf-8") != expected:
        return [f"{OUTPUT.name}: 계약 드리프트(정본 재생성 결과와 불일치)"]
    return []


def rewrite() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_contract(), encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="드리프트만 검사(쓰지 않음)")
    args = ap.parse_args(argv)
    if args.check:
        problems = check()
        if problems:
            print("계약 드리프트:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        print("계약 동기화 OK (frontend/src/contract/contract.gen.ts)")
        return 0
    rewrite()
    print("재생성 완료: frontend/src/contract/contract.gen.ts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
