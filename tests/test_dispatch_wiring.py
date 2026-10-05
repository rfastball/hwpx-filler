"""Screen-scoped WebView dispatch registry completeness and rejection gates."""
from __future__ import annotations

import ast
import inspect
import re
import textwrap

import pytest

from _web_source import source_text
from hwpxfiller.webapp.action_registry import ACTION_REGISTRY, validate_dispatch
from hwpxfiller.webapp.app import _DISPATCH_REJECTION_KEY, WebFrontend
from hwpxfiller.webapp.screen_editor import EditorController
from hwpxfiller.webapp.screen_library import LibraryController
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.screen_pool import PoolController
from hwpxfiller.webapp.screen_template import TemplateController
from hwpxfiller.webapp.onboarding import OnboardingController
from hwpxfiller.webapp.screen_workbench import WorkbenchController
from hwpxfiller.webapp.screen_authoring import AuthoringController
from hwpxfiller.viewmodel.edit_session import EditSession
from hwpxfiller.webapp.editor_session import EditorLoader
from hwpxfiller.webapp.data_zone import JobDataSession
from hwpxfiller.webapp.artifact_view_session import ArtifactViewSession
from hwpxfiller.webapp.authoring_proposal import ProposalPanel


CONTROLLERS = {
    "library": LibraryController,
    "editor": EditorController,
    "job": JobController,
    "pool": PoolController,
    "tpl": TemplateController,
    "workbench": WorkbenchController,
    # 템플릿 저작 작업대(#1015) — 몰입 화면. 문서 세션·명령 미리보기·시험·복구·적용 어휘.
    "authoring": AuthoringController,
    # 화면이 아니라 채널이다(#894) — DOM 루트도 탭도 없고 표면은 셸 레벨 React 패널이지만,
    # 스냅샷 채널과 디스패치 어휘는 이 registry 에서만 나온다(`pool` 과 같은 형상).
    "tutorial": OnboardingController,
}

# SCREEN 상수의 소유 화면. 공유 모듈은 호출 시 화면을 인자로 받으므로 별도 정적 추측 대신
# 해당 액션의 백엔드 MRO↔registry 동등성으로 검증한다.
SCREEN_JS = {
    "library": "src/screens/library.ts",
    "editor": "src/screens/editor.ts",
    "job": "src/screens/job_run.ts",
    # `pool` 화면은 사망(재작성 F1) — 그 액션의 프런트 소비자는 데이터 선택 다이얼로그다.
    # 여기 호출은 전부 명시 리터럴("pool")이고 마운트 호출만 호스트 화면 변수(session.screen).
    "pool": "src/screens/data_picker.ts",
    # `tpl` 화면도 사망(F8 §10.17) — 12액션의 프런트 소비자는 편집기 「템플릿」 탭이고 호출은
    # 전부 명시 리터럴("tpl")이라 editor.ts 스캔(owner="editor")에서 그대로 검증된다.
    # 별도 행을 두면 editor.ts 의 SCREEN 상수 호출이 tpl 로 오해석돼 거짓 실패가 난다.
    "workbench": "src/screens/workbench.ts",
}

_LITERAL_CALL = re.compile(
    r"(?:Bridge\.call|dispatch)\(\s*(?:SCREEN|['\"](?P<screen>[a-z]+)['\"])\s*,\s*"
    r"['\"](?P<action>[a-z0-9_]+)['\"]"
)


class _StubTutorial:
    def observation_token(self):
        return (None, None, 0)

    def observe_product(self, *_args, **_kwargs):
        return False


def _controller_actions(controller: type) -> set[str]:
    """Collect the effective dispatch surface, including inherited mixins."""

    if controller is EditorController:
        return _editor_actions()
    if controller is OnboardingController:
        tree = ast.parse(textwrap.dedent(inspect.getsource(OnboardingController._dispatch)))
        actions = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name) or node.left.id != "action":
                continue
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                    actions.add(comparator.value)
                elif isinstance(comparator, (ast.Set, ast.Tuple)):
                    actions.update(item.value for item in comparator.elts
                                   if isinstance(item, ast.Constant) and isinstance(item.value, str))
        return actions

    owners = controller.__mro__
    if controller is JobController:
        # 데이터 존·만든 문서 관찰 세션(`_action_owner`)이 job 액션의 일부를 소유한다.
        owners = (*owners, JobDataSession, ArtifactViewSession)
    if controller is AuthoringController:
        # 「데이터로 필드 찾기」(#1156) 패널이 propose_* 액션을 소유한다(`ProposalPanel.handlers`).
        owners = (*owners, ProposalPanel)
    return {
        name.removeprefix("_do_")
        for cls in owners
        for name in vars(cls)
        if name.startswith("_do_")
    }


def _editor_actions() -> set[str]:
    """Read the editor's split loader/session/controller dispatch owners."""
    actions = {
        name.removeprefix("_do_")
        for name in vars(EditorLoader)
        if name.startswith("_do_")
    }
    controller_tree = ast.parse(textwrap.dedent(inspect.getsource(EditorController._dispatch)))
    session_tree = ast.parse(textwrap.dedent(inspect.getsource(EditSession.apply_mapping_action)))
    for tree in (controller_tree, session_tree):
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Name)
                and node.left.id == "action"
            ):
                actions.update(
                    comparator.value
                    for comparator in node.comparators
                    if isinstance(comparator, ast.Constant)
                    and isinstance(comparator.value, str)
                )
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "mapping_actions"
                    for target in node.targets
                )
                and isinstance(node.value, (ast.Set, ast.Tuple, ast.List))
            ):
                actions.update(
                    item.value
                    for item in node.value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
    return actions


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
        text = source_text(relative)
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
    api.controllers = {"pool": Stub(), "tutorial": _StubTutorial()}
    assert api.dispatch("pool", "refresh", None) == {"action": "refresh", "payload": {}}
    rejected = api.dispatch("pool", "refresh", {"typo": True})
    assert set(rejected) == {_DISPATCH_REJECTION_KEY}
    assert rejected[_DISPATCH_REJECTION_KEY]["name"] == "ValueError"
    assert "미등록 키=['typo']" in rejected[_DISPATCH_REJECTION_KEY]["message"]


def test_webfrontend_dispatch_envelopes_expected_refusal_but_not_defects() -> None:
    class Stub:
        def __init__(self, error: Exception) -> None:
            self.error = error

        def dispatch(self, _action: str, _payload: dict):
            raise self.error

    api = WebFrontend.__new__(WebFrontend)
    api.controllers = {"pool": Stub(ValueError("데이터가 없습니다")), "tutorial": _StubTutorial()}
    assert api.dispatch("pool", "refresh", {}) == {
        _DISPATCH_REJECTION_KEY: {
            "name": "ValueError",
            "message": "데이터가 없습니다",
        }
    }

    api.controllers = {"pool": Stub(RuntimeError("controller defect")), "tutorial": _StubTutorial()}
    with pytest.raises(RuntimeError, match="controller defect"):
        api.dispatch("pool", "refresh", {})
