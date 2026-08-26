"""blocker 어포던스 선언 ↔ 실재의 정적 대조 + **역방향 고아 액션 0**(#912 (a) 층).

## 이 파일이 겨누는 결함류

#912 전수 감사가 이름 지은 것: **「blocker X 가 섰는데 그것을 지울 활성 컨트롤이 렌더되지
않거나, 액션이 등록만 되고 호출자가 없다」**. 이 결함류는 어느 한 층만 보면 전부 초록이다 —
링1 은 blocker 를 옳게 세우고, registry 는 액션을 옳게 등록하고, 렌더는 문안을 옳게 그린다.
빠진 것은 **층 사이의 연결**이라, 그것을 보는 계약은 층을 가로질러야 한다.

네 가지를 본다.

1. **전수 선언** — 어휘 정본의 blocker 전건이 어포던스 표에 있다. 새 blocker 를 추가하는
   사람이 세 형태(활성 동사 / 자동 진행 / 설계상 없음) 중 하나를 명시로 고르지 않으면
   여기서 막힌다.
2. **액션 실재** — 활성 동사가 지목한 dispatch 좌표가 ``action_registry`` 에 있거나,
   직접 브리지 메서드가 ``WebFrontend`` 공개 메서드로 있다.
3. **셀렉터 실재** — 선언한 셀렉터의 id/클래스 토큰이 ``frontend/src/**`` 에 실재한다.
4. **역방향(고아 0)** — registry 에 등록된 액션 중 프런트 호출자가 0 인 것이 없다. 이것이
   D4 를 잡는 방향이다: ``refresh_observation`` 은 registry·핸들러 양쪽에 있었고 위 1~3 은
   전부 통과했지만, **부르는 쪽이 없었다**.

## 이 대조의 정직한 한계

3·4 는 **문자열 실재**를 본다 — 「그 셀렉터가 그 상태에서 실제로 렌더되고 활성인가」는
정적으로 볼 수 없다(CLAUDE.md: 정적 계약은 규칙의 존재를 보고 결과를 못 본다). 그 층은
헤드리스 불변식(``tests/test_webapp_job_blocker_affordance.py``)과 실창 대본
(``scripts/live101/scenario.py`` 의 관리 검토 사슬)이 각각 진다. 여기서 잡는 것은 **연결이
아예 없는** 자리다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from hwpxfiller.application.document_creation_vocabulary import (
    BLOCKER_CODES,
    PRIMARY_ACTION_CODES,
)
from hwpxfiller.webapp.action_registry import ACTION_REGISTRY
from hwpxfiller.webapp.blocker_affordance import (
    ACTIVE_VERB,
    AUTOMATIC_PROGRESS,
    BLOCKER_AFFORDANCES,
    NO_VERB_BY_DESIGN,
    BlockerAffordance,
    managed_primary_action_controls,
)

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = ROOT / "frontend" / "src"
BRIDGE_JS = ROOT / "frontend" / "js" / "bridge.js"
APP_PY = ROOT / "src" / "hwpxfiller" / "webapp" / "app.py"

#: 생성물이라 원천이 아니다 — 여기서 액션 이름이 발견되면 「소비자가 있다」가 거짓이 된다
#: (registry 를 그대로 방출한 파일이므로 모든 이름이 자기 자신을 증명해 버린다).
_GENERATED = ("contract.gen.ts",)

_STRING_LITERAL = re.compile(r"""['"]([a-z][a-z0-9_]*)['"]""")
#: 셀렉터에서 실재를 물어볼 토큰 — `#id` 와 `.class` 만 뽑는다(태그·조합자는 제외).
_SELECTOR_TOKEN = re.compile(r"[#.]([A-Za-z][\w-]*)")


def _frontend_sources() -> "list[Path]":
    files = [
        path
        for pattern in ("*.ts", "*.js")
        for path in FRONTEND_SRC.rglob(pattern)
        if not path.name.endswith(_GENERATED)
    ]
    assert files, "frontend/src 소스를 하나도 읽지 못했습니다"
    return files


def _frontend_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in _frontend_sources())


def _frontend_literals() -> "set[str]":
    literals: "set[str]" = set()
    for path in _frontend_sources():
        literals |= set(_STRING_LITERAL.findall(path.read_text(encoding="utf-8")))
    # 직접 브리지 경로는 `frontend/js/bridge.js` 가 소비한다 — 같은 소비로 인정한다.
    literals |= set(_STRING_LITERAL.findall(BRIDGE_JS.read_text(encoding="utf-8")))
    return literals


def _webfrontend_public_methods() -> "set[str]":
    """``WebFrontend`` 공개 메서드 이름 — 직접 브리지 경로의 실재 오러클."""
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "WebFrontend":
            return {
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not item.name.startswith("_")
            }
    raise AssertionError("webapp/app.py 에서 WebFrontend 클래스를 찾지 못했습니다")


# ─────────────────────────────────────────────────────── 1. 전수 선언 ──


def test_every_blocker_declares_an_affordance() -> None:
    """어휘 정본의 blocker 전건이 표에 있고, 표에 어휘 밖 항목이 없다."""
    assert tuple(BLOCKER_AFFORDANCES) == BLOCKER_CODES


def test_the_three_forms_are_each_actually_used() -> None:
    """세 형태가 전부 실재 표본을 갖는다 — 「형태를 정의만 하고 안 쓴다」를 막는다.

    특히 :data:`NO_VERB_BY_DESIGN` 이 비면 그것은 「설계상 없음」이 선언 가능한 값이 아니라
    죽은 상수라는 뜻이고, 그러면 다음 사람은 동사 없는 blocker 를 **빈칸**으로 둔다 —
    빈칸은 「아직 안 배선했다」와 구별되지 않는다.
    """
    kinds = {affordance.kind for affordance in BLOCKER_AFFORDANCES.values()}
    assert kinds == {ACTIVE_VERB, AUTOMATIC_PROGRESS, NO_VERB_BY_DESIGN}
    # 알림 설계로 못박힌 둘 — 여기에 동사가 붙으면 누를 수 있다는 거짓을 말하게 된다.
    for code in ("POLICY_BLOCKED", "RUNTIME_NOT_ADMITTED"):
        assert BLOCKER_AFFORDANCES[code].kind == NO_VERB_BY_DESIGN


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        # 활성 동사인데 셀렉터가 없다 — 「누르라」고 하면서 누를 자리를 안 적은 선언이다.
        ({"kind": ACTIVE_VERB, "dispatch_action": "job.resolve_execution"}, "ACTIVE_VERB"),
        # 활성 동사인데 액션 좌표가 없다 — 눌러도 아무 데도 안 가는 버튼의 선언이다.
        ({"kind": ACTIVE_VERB, "selector": "#x"}, "ACTIVE_VERB"),
        # 좌표 둘 — 어느 경로로 가는지가 선언에서 갈리지 않으면 대조가 무의미해진다.
        (
            {
                "kind": ACTIVE_VERB,
                "selector": "#x",
                "dispatch_action": "job.resolve_execution",
                "bridge_method": "pick_data_file",
            },
            "ACTIVE_VERB",
        ),
        # 자동 진행에 액션을 달면 그것은 자동 진행이 아니라 활성 동사다.
        (
            {"kind": AUTOMATIC_PROGRESS, "selector": "#x", "dispatch_action": "job.set_all"},
            "AUTOMATIC_PROGRESS",
        ),
        # 「설계상 없음」에 셀렉터가 붙으면 없다는 선언이 거짓이 된다.
        ({"kind": NO_VERB_BY_DESIGN, "selector": "#x"}, "NO_VERB_BY_DESIGN"),
        ({"kind": "SOMETHING_ELSE"}, "모르는 어포던스 형태"),
    ],
)
def test_malformed_declarations_are_refused_at_construction(
    kwargs: dict, fragment: str
) -> None:
    """형태와 좌표가 어긋난 선언은 **만들어지는 순간** 거절된다.

    이 불변식이 없으면 표는 자유 서식 메모가 된다 — 셀렉터 없는 「활성 동사」나 좌표 붙은
    「설계상 없음」이 들어와도 아무도 묻지 않고, 그러면 표를 읽는 세 층이 각자 다른 것을
    가정한다.
    """
    with pytest.raises(ValueError, match=fragment):
        BlockerAffordance(rationale="시험", **kwargs)


def test_a_declaration_without_a_reason_is_refused() -> None:
    """사유 없는 선언도 거절한다 — 특히 「동사 없음」은 사유가 곧 그 선언의 내용이다."""
    with pytest.raises(ValueError, match="사유"):
        BlockerAffordance(kind=NO_VERB_BY_DESIGN, rationale="")


# ─────────────────────────────────────────────────── 2. 액션 실재 ──


@pytest.mark.parametrize("code", [c for c in BLOCKER_CODES])
def test_declared_verb_action_exists(code: str) -> None:
    """활성 동사가 지목한 좌표가 registry 또는 ``WebFrontend`` 공개 메서드로 실재한다."""
    affordance = BLOCKER_AFFORDANCES[code]
    if affordance.dispatch_action is not None:
        screen, _, action = affordance.dispatch_action.partition(".")
        assert screen in ACTION_REGISTRY, f"{code}: 모르는 화면 {screen!r}"
        assert action in ACTION_REGISTRY[screen], (
            f"{code}: {screen!r} 에 등록되지 않은 액션 {action!r}"
        )
    if affordance.bridge_method is not None:
        assert affordance.bridge_method in _webfrontend_public_methods(), (
            f"{code}: WebFrontend 공개 메서드가 아닙니다 — {affordance.bridge_method!r}"
        )


# ─────────────────────────────────────────────────── 3. 셀렉터 실재 ──


@pytest.mark.parametrize("code", [c for c in BLOCKER_CODES])
def test_declared_selector_tokens_exist_in_frontend(code: str) -> None:
    """선언한 셀렉터의 id/클래스 토큰이 프런트 source 에 실재한다.

    「그 상태에서 실제로 서는가」는 못 본다(모듈 머리말의 한계) — 여기서 잡는 것은 이름이
    갈렸는데 표가 안 따라온 자리다.
    """
    selector = BLOCKER_AFFORDANCES[code].selector
    if selector is None:
        return
    text = _frontend_text()
    tokens = _SELECTOR_TOKEN.findall(selector)
    assert tokens, f"{code}: 셀렉터에서 실재를 물어볼 토큰이 없습니다 — {selector!r}"
    missing = [token for token in tokens if token not in text]
    assert not missing, f"{code}: 프런트에 없는 셀렉터 토큰 {missing} — {selector!r}"


# ─────────────────────────────────────────────── 4. 역방향(고아 0) ──


def test_no_registered_action_is_without_a_frontend_caller() -> None:
    """registry 에 등록된 액션 중 프런트 호출자가 0 인 것이 없다(#912 D4 재발 방지).

    이 방향이 없으면 「등록했고 핸들러도 썼다」로 끝난 배선이 조용히 산다 —
    ``refresh_observation`` 이 정확히 그랬다. 판정 기준은 액션 이름이 프런트 source 의
    문자열 리터럴로 등장하는가다: 화면 귀속(어느 screen 으로 보내는가)까지는 정적으로 못
    가른다(대부분의 화면이 screen 을 닫아 둔 지역 ``dispatch`` 를 쓴다). 생성물
    ``contract.gen.ts`` 는 registry 를 그대로 방출한 파일이라 **제외**한다 — 넣으면 모든
    이름이 자기 자신을 증명해 계약이 항진명제가 된다.
    """
    literals = _frontend_literals()
    orphans = sorted(
        f"{screen}.{action}"
        for screen, actions in ACTION_REGISTRY.items()
        for action in actions
        if action not in literals
    )
    assert not orphans, (
        f"등록만 되고 프런트 호출자가 0 인 액션: {orphans}"
        " — 단방향 배선입니다(등록을 걷거나 호출자를 세우세요)"
    )


# ─────────────────────────────────────── 파생: 실창 대본이 쓰는 매핑 ──


def test_managed_controls_derive_from_the_single_source() -> None:
    """Primary Action → 셀렉터 파생이 표와 어휘 정본만으로 선다(#912 D6).

    실창 대본이 지던 사설 매핑표의 승계자다. 그 표는 정본과 결속이 없어 거짓 항목을 실었다:
    ``RESOLVE_RUNTIME_POLICY → #jobResolveExecution`` — runtime/policy 는 설계상 동사가 없어
    그 조합에서 버튼이 렌더되지 않는다. 파생에서는 그 항목이 **만들어질 수 없다**.
    """
    controls = managed_primary_action_controls()
    assert set(controls) <= set(PRIMARY_ACTION_CODES)
    # 동사 없는 축은 파생에 없다 — 이것이 D6 가 실었던 거짓 항목의 자리다.
    assert "RESOLVE_RUNTIME_POLICY" not in controls
    # 확인 축 셋(동사 둘 + 자동 진행 하나)이 하나의 셀렉터로 접힌다.
    assert controls["RESOLVE_EXECUTION"] == "#jobResolveExecution"
    assert controls["RECOVER_CONTEXT"] == "#jobRecoverContext"
    assert controls["REVIEW_DELIVERY"] == "#jobRefreshDelivery"
