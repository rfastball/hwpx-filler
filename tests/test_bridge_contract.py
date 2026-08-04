"""Python↔TS 브리지 계약 — 드리프트 게이트 + 생성기 비경유 독립 오러클 (R2-02 · #406).

두 겹이 다른 실패를 잡는다(패킷 rev3 §4.1):

- **드리프트**: 재생성 바이트 비교(``gen_bridge_contract.check``). 정본이 변했는데 생성물이
  안 따라온 것, 생성물 손 편집을 잡는다. 생성기 경유라 생성기 오독은 **못** 잡는다.
- **오러클**: 생성기를 부르지도, 그 추출·파싱 코드를 공유하지도 않는다(제3 공유 헬퍼 금지 —
  같은 정규식을 나눠 쓰면 한쪽 오독이 양쪽 초록으로 남는다). 정본을 축별 **제2 엔진**으로
  읽어 생성물 본문과 대조한다: Python 직접 import / ``webapp.app`` 런타임 리플렉션 /
  생성기와 다른 독립 JS 판독(``test_selftest_api`` 의 HOST_OPS 선례). 생성기가 정본을
  오독하면 바이트 비교는 초록이어도 이 층이 빨갛다.

상수 축 음성 대조가 판별력을 먼저 세운다 — 합성 변조 각각이 실제로 빨간지.
"""
from __future__ import annotations

import re

import pytest

import gen_bridge_contract as gen
from _web_source import source_text
from hwpxfiller.webapp import product_api
from hwpxfiller.webapp.action_registry import ACTION_REGISTRY
from hwpxfiller.webapp.app import _DISPATCH_REJECTION_KEY, WebFrontend


def _generated() -> str:
    return source_text("src", "contract", "contract.gen.ts")


# ------------------------------------------------------------ 오러클의 제2 엔진들
# 아래 판독기는 생성기(gen_bridge_contract)의 코드를 한 줄도 쓰지 않는다.


def _const_array(text: str, name: str) -> "list[str]":
    """생성물의 여러 줄 ``export const X = [...] as const`` 배열 — 순서 보존 판독."""
    match = re.search(
        rf"export const {name} = \[\n(?P<body>(?:  \"[^\"\n]+\",\n)*)\] as const;", text
    )
    if match is None:
        return []
    return re.findall(r'"([^"]+)"', match.group("body"))


def _generated_screen_actions(
    text: str,
) -> "dict[str, dict[str, tuple[list[str], list[str]]]]":
    """SCREEN_ACTIONS 블록의 줄 단위 판독 — 화면→액션→(required, optional)."""
    lines = text.splitlines()
    if "export const SCREEN_ACTIONS = {" not in lines:
        return {}
    result: "dict[str, dict[str, tuple[list[str], list[str]]]]" = {}
    screen = None
    for line in lines[lines.index("export const SCREEN_ACTIONS = {") + 1 :]:
        if line == "} as const;":
            break
        opened = re.fullmatch(r"  (\w+): \{", line)
        if opened:
            screen = opened.group(1)
            result[screen] = {}
            continue
        if line == "  },":
            screen = None
            continue
        entry = re.fullmatch(
            r"    (\w+): \{ required: \[(.*?)\], optional: \[(.*?)\] \},", line
        )
        if entry and screen is not None:
            result[screen][entry.group(1)] = (
                re.findall(r'"([^"]+)"', entry.group(2)),
                re.findall(r'"([^"]+)"', entry.group(3)),
            )
    return result


def _runtime_public_surface() -> "list[str]":
    """직접 메서드 축의 제2 엔진 — headless import + 런타임 리플렉션(정의 순서)."""
    return [
        name
        for name, value in vars(WebFrontend).items()
        if not name.startswith("_") and callable(value)
    ]


def _runtime_rejection_fields() -> "list[str]":
    """거절 봉투 축의 제2 엔진 — 실 dispatch 거절을 일으켜 봉투 내부 키를 그대로 읽는다."""
    api = WebFrontend.__new__(WebFrontend)
    api.controllers = {}
    rejected = api.dispatch("ghost", "nope", {})
    assert set(rejected) == {_DISPATCH_REJECTION_KEY}, rejected
    return list(rejected[_DISPATCH_REJECTION_KEY])


def _js_snake_codes() -> "list[str]":
    """snake 축의 제2 엔진 — 생성기와 다른 줄 단위 판독(HOST_OPS 드리프트 게이트 선례)."""
    lines = source_text("src", "product_api.js").splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if "PRODUCT_ERROR_CODES = Object.freeze({" in line
    )
    codes: "list[str]" = []
    for line in lines[start + 1 :]:
        if line.strip() == "});":
            break
        entry = re.fullmatch(r"\s*[A-Z_]+:\s*\"([a-z_]+)\",?", line)
        if entry:
            codes.append(entry.group(1))
    return codes


def _bridge_called_methods() -> "set[str]":
    """legacy 브리지가 실제로 부르는 호스트 메서드 — host-internal 기록의 실측 대조."""
    return set(
        re.findall(r"window\.pywebview\.api\.([a-z_]+)\(", source_text("js", "bridge.js"))
    )


def _oracle_problems(text: str) -> "list[str]":
    """생성물 본문 ↔ 정본(제2 엔진) 대조 — 문제 목록(빈 리스트=일치)."""
    problems: "list[str]" = []

    if f"export const PRODUCT_VERSION = {product_api.VERSION};" not in text:
        problems.append("version: PRODUCT_VERSION 이 product_api.VERSION 과 다르다")
    if f'export const PRODUCT_PROTOCOL = "{product_api.PROTOCOL}";' not in text:
        problems.append("protocol: PRODUCT_PROTOCOL 이 product_api.PROTOCOL 과 다르다")
    if _const_array(text, "PRODUCT_CAPABILITIES") != list(product_api.CAPABILITIES):
        problems.append("capabilities: 전수·순서가 CAPABILITIES 와 다르다(순서가 계약이다)")

    kebab = [
        value
        for name, value in vars(product_api).items()
        if name.startswith("CODE_") and isinstance(value, str)
    ]
    if _const_array(text, "PYTHON_ERROR_CODES") != kebab:
        problems.append("kebab: PYTHON_ERROR_CODES 전수가 product_api.CODE_* 와 다르다")
    if _const_array(text, "JS_PRODUCT_ERROR_CODES") != _js_snake_codes():
        problems.append("snake: JS_PRODUCT_ERROR_CODES 전수가 product_api.js 와 다르다")

    if f'export const DISPATCH_REJECTION_KEY = "{_DISPATCH_REJECTION_KEY}";' not in text:
        problems.append("rejection-key: 거절 봉투 키가 app.py 와 다르다")
    fields = ", ".join(f'"{field}"' for field in _runtime_rejection_fields())
    if f"export const DISPATCH_REJECTION_FIELDS = [{fields}] as const;" not in text:
        problems.append("rejection-fields: 봉투 내부 키가 실 거절 봉투와 다르다")

    actions = _generated_screen_actions(text)
    if set(actions) != set(ACTION_REGISTRY):
        problems.append("screens: 화면 전수가 ACTION_REGISTRY 와 다르다")
    for screen in set(actions) & set(ACTION_REGISTRY):
        if len(actions[screen]) != len(ACTION_REGISTRY[screen]):
            problems.append(f"action-count: {screen} 액션 수가 registry 와 다르다")
    for screen, action in (("pool", "register_excel"), ("job", "toggle_record")):
        schema = ACTION_REGISTRY[screen][action]
        expected = (sorted(schema.required), sorted(schema.optional))
        if actions.get(screen, {}).get(action) != expected:
            problems.append(f"sample-action: {screen}/{action} 키 집합이 registry 와 다르다")

    surface = _runtime_public_surface()
    if _const_array(text, "HOST_METHODS") != surface:
        problems.append("methods: HOST_METHODS 전수가 WebFrontend 공개 표면과 다르다")
    called = _bridge_called_methods()
    internal = [name for name in surface if name not in called]
    if _const_array(text, "HOST_INTERNAL_METHODS") != internal:
        problems.append(
            "host-internal: 기록이 실측(브리지 미호출 표면)과 다르다 — "
            f"실측={internal}"
        )

    # 비혼합 불변식(#406) — selftest 계약은 제품 계약에 섞지 않는다.
    if "selftest" in text.lower() or "__hwpxTest" in text:
        problems.append("non-mixing: 생성물에 selftest 어휘가 섞였다")

    return problems


# ------------------------------------------------------------------ 양성


def test_contract_is_in_sync() -> None:
    """드리프트 층 — 재생성 결과와 커밋본이 바이트 동일하다."""
    problems = gen.check()
    assert not problems, (
        "계약 드리프트: " + "; ".join(problems)
        + " — `python scripts/gen_bridge_contract.py` 로 재생성하세요."
    )


def test_oracle_finds_no_problems_on_the_committed_artifact() -> None:
    """오러클 층 — 정본의 제2 엔진 판독과 생성물 본문이 일치한다."""
    problems = _oracle_problems(_generated())
    assert not problems, "\n".join(problems)


def test_second_engines_are_not_empty() -> None:
    """부재판별력 — 제2 엔진들이 실제로 무언가를 읽는다(0 판독의 공허한 초록 차단)."""
    assert len(_runtime_public_surface()) >= 20
    assert len(_js_snake_codes()) >= 6
    assert _runtime_rejection_fields()
    assert len(_bridge_called_methods()) >= 23  # 23 직접 + selftest 시험 통로 2
    real = _generated_screen_actions(_generated())
    assert sum(len(actions) for actions in real.values()) >= 100


# ------------------------------------------------------------ 음성 — 상수 축 판별력


def _swap_capability_order(text: str) -> str:
    return text.replace(
        '  "snapshot",\n  "close-request",', '  "close-request",\n  "snapshot",', 1
    )


def _drop_sample_required_key(text: str) -> str:
    return text.replace(
        'register_excel: { required: ["name", "path"]',
        'register_excel: { required: ["path"]',
        1,
    )


@pytest.mark.parametrize(
    ("axis", "tamper"),
    [
        ("version", lambda text: text.replace(
            "export const PRODUCT_VERSION = 1;", "export const PRODUCT_VERSION = 2;", 1)),
        ("capabilities", _swap_capability_order),
        ("sample-action", _drop_sample_required_key),
        ("snake", lambda text: text.replace('  "handler_failed",\n', "", 1)),
        ("methods", lambda text: text.replace('  "close_guard_state",\n', "", 1)),
        ("non-mixing", lambda text: text + "// selftest\n"),
    ],
)
def test_oracle_bites_on_synthetic_tampering(axis: str, tamper) -> None:
    """상수 축 음성 — 각 변조가 해당 축의 문제로 실제로 빨갛다(rev3 §7)."""
    original = _generated()
    tampered = tamper(original)
    assert tampered != original, "변조가 아무것도 바꾸지 않았다 — 이 음성은 공허하다"
    problems = _oracle_problems(tampered)
    assert any(problem.startswith(axis) for problem in problems), (
        f"{axis} 변조를 오러클이 놓쳤다: {problems}"
    )


# ---------------------------------------------------------- 음성 — 드리프트 판별력


def test_drift_gate_bites_on_absence_and_hand_edits(tmp_path, monkeypatch) -> None:
    """생성물 부재·손 편집 1바이트가 각각 빨갛다 — check() 의 판별력."""
    target = tmp_path / "contract.gen.ts"
    monkeypatch.setattr(gen, "OUTPUT", target)

    assert gen.check() == [f"{target.name}: 생성물이 없습니다 — 재생성하세요."]

    text = gen.render_contract()
    target.write_text(text, encoding="utf-8", newline="\n")
    assert gen.check() == []

    target.write_text(text.replace("unknown", "unknowm", 1), encoding="utf-8", newline="\n")
    assert gen.check(), "1바이트 손 편집이 드리프트로 잡히지 않았다"


def test_regeneration_tracks_source_changes() -> None:
    """registry 증감·공개 메서드 증감·snake 증감이 재생성 결과를 실제로 바꾼다."""
    disk = _generated()

    shrunk = {screen: dict(actions) for screen, actions in ACTION_REGISTRY.items()}
    del shrunk["pool"]["refresh"]
    assert gen.render_contract(registry=shrunk) != disk

    app = gen.extract_app_contract()
    fewer = gen.AppContract(app.rejection_key, app.rejection_fields, app.methods[:-1])
    assert gen.render_contract(app=fewer) != disk

    assert gen.render_contract(js_codes=gen.extract_js_error_codes()[:-1]) != disk
