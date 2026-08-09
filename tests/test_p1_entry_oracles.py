"""P1-99 공개 entry characterization — controller 단위 증거를 transport 경계에 잇는다."""

from __future__ import annotations

from hwpxfiller.webapp import screen_editor
from hwpxfiller.webapp.app import WebFrontend


class _RecordingController:
    def __init__(self) -> None:
        self.calls: "list[tuple[str, dict]]" = []

    def initial(self) -> dict:
        return {"screen": "editor", "ready": True}

    def dispatch(self, action: str, payload: dict) -> dict:
        self.calls.append((action, dict(payload)))
        return {"action": action, "payload": dict(payload)}


def test_editor_initial_crosses_public_transport_boundary(tmp_path) -> None:
    """화면 부팅 oracle 은 controller 직접 호출이 아니라 WebFrontend entry 를 겨눈다."""
    frontend = WebFrontend(tmp_path / "txt")
    controller = _RecordingController()
    frontend.controllers["editor"] = controller

    assert frontend.initial("editor") == {"screen": "editor", "ready": True}
    assert screen_editor.EditorController.name == "editor"


def test_missing_gui_action_oracles_cross_public_dispatch_boundary(tmp_path) -> None:
    """P1-02E의 10개 action 공백을 payload 검증·라우팅 관찰값으로 특성화한다."""
    frontend = WebFrontend(tmp_path / "txt")
    controllers = {
        screen: _RecordingController() for screen in ("editor", "job", "tpl", "workbench")
    }
    frontend.controllers.update(controllers)

    assert frontend.dispatch("editor", "set_fmt", {"index": 0, "fmt": "date"}) == {
        "action": "set_fmt",
        "payload": {"index": 0, "fmt": "date"},
    }
    assert frontend.dispatch("editor", "step_preview", {"delta": 1})["action"] == "step_preview"
    assert frontend.dispatch("job", "cancel_generation", {})["action"] == "cancel_generation"
    assert frontend.dispatch(
        "job", "filter_col_text", {"column": "기관", "text": "교육청"}
    )["action"] == "filter_col_text"
    assert frontend.dispatch("job", "filter_clear_col", {"column": "기관"})[
        "action"
    ] == "filter_clear_col"
    assert frontend.dispatch("tpl", "txt_content", {"path": "draft.txt"})[
        "action"
    ] == "txt_content"
    assert frontend.dispatch("workbench", "revert_map", {"name": "수신"})[
        "action"
    ] == "revert_map"
    assert frontend.dispatch(
        "workbench", "set_map_fmt", {"name": "일자", "code": "date"}
    )["action"] == "set_map_fmt"
    assert frontend.dispatch(
        "workbench", "set_map_type", {"name": "금액", "type": "number"}
    )["action"] == "set_map_type"
    assert frontend.dispatch("workbench", "set_target_font", {"font": "함초롬바탕"})[
        "action"
    ] == "set_target_font"

    # 같은 공개 entry 에서 미등록 필드는 controller 에 닿기 전에 loud rejection 된다.
    rejected = frontend.dispatch("editor", "set_fmt", {"index": 0, "fmt": "date", "extra": 1})
    assert rejected == {
        "__hwpx_dispatch_rejection_v1__": {
            "name": "ValueError",
            "message": "'editor'/'set_fmt' payload 스키마 불일치: 미등록 키=['extra']",
        }
    }
    assert controllers["editor"].calls == [
        ("set_fmt", {"index": 0, "fmt": "date"}),
        ("step_preview", {"delta": 1}),
    ]
