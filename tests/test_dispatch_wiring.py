"""Screen-scoped WebView dispatch registry completeness and rejection gates."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from hwpxfiller.webapp.action_registry import ACTION_REGISTRY, validate_dispatch
from hwpxfiller.webapp.app import WebFrontend
from hwpxfiller.webapp.screen_draft import DraftController
from hwpxfiller.webapp.screen_editor import EditorController
from hwpxfiller.webapp.screen_home import HomeController
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.screen_pool import PoolController
from hwpxfiller.webapp.screen_template import TemplateController


ROOT = Path(__file__).resolve().parents[1]

CONTROLLERS = {
    "home": HomeController,
    "editor": EditorController,
    "job": JobController,
    "draft": DraftController,
    "pool": PoolController,
    "tpl": TemplateController,
}

# SCREEN 상수의 소유 화면. 공유 모듈은 호출 시 화면을 인자로 받으므로 별도 정적 추측 대신
# 해당 액션의 백엔드 MRO↔registry 동등성으로 검증한다.
SCREEN_JS = {
    "home": "web/js/screens/home.js",
    "editor": "web/js/screens/editor.js",
    "job": "web/js/screens/job.js",
    "draft": "web/js/screens/draft.js",
    "pool": "web/js/screens/pool.js",
    "tpl": "web/js/screens/template.js",
}

_LITERAL_CALL = re.compile(
    r"Bridge\.call\(\s*(?:SCREEN|['\"](?P<screen>[a-z]+)['\"])\s*,\s*"
    r"['\"](?P<action>[a-z0-9_]+)['\"]"
)


def _controller_actions(controller: type) -> set[str]:
    """Collect the effective dispatch surface, including inherited mixins."""

    return {
        name.removeprefix("_do_")
        for cls in controller.__mro__
        for name in vars(cls)
        if name.startswith("_do_")
    }


def test_registry_has_exactly_the_runtime_controller_surface() -> None:
    assert set(ACTION_REGISTRY) == set(CONTROLLERS)
    for screen, controller in CONTROLLERS.items():
        assert set(ACTION_REGISTRY[screen]) == _controller_actions(controller), screen


def test_payload_schema_key_sets_are_unambiguous() -> None:
    for screen, actions in ACTION_REGISTRY.items():
        for action, schema in actions.items():
            assert schema.required.isdisjoint(schema.optional), f"{screen}/{action}"


def test_literal_frontend_calls_are_allowed_on_their_own_screen() -> None:
    """Catch stale/cross-screen literals without the old repository-wide false pass."""

    offenders: list[str] = []
    for owner, relative in SCREEN_JS.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for match in _LITERAL_CALL.finditer(text):
            screen = match.group("screen") or owner
            action = match.group("action")
            if action not in ACTION_REGISTRY.get(screen, {}):
                offenders.append(f"{relative}: {screen}/{action}")
    assert not offenders, "화면 registry 밖의 프런트 호출:\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    ("screen", "action", "payload", "message"),
    [
        ("ghost", "refresh", {}, "등록되지 않은 화면"),
        ("pool", "ghost", {}, "등록되지 않은 'pool' 액션"),
        ("pool", "archive", {}, "필수 키 누락"),
        ("pool", "refresh", {"typo": True}, "미등록 키"),
        ("pool", "refresh", [], "payload는 객체"),
    ],
)
def test_unknown_screen_action_and_payload_are_rejected_loudly(
    screen: str, action: str, payload: object, message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_dispatch(screen, action, payload)


def test_webfrontend_dispatch_enforces_registry_before_controller() -> None:
    class Stub:
        def dispatch(self, action: str, payload: dict):
            return {"action": action, "payload": payload}

    api = WebFrontend.__new__(WebFrontend)
    api.controllers = {"pool": Stub()}
    assert api.dispatch("pool", "refresh", None) == {"action": "refresh", "payload": {}}
    with pytest.raises(ValueError, match="미등록 키"):
        api.dispatch("pool", "refresh", {"typo": True})
