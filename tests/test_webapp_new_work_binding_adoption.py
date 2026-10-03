"""새 작업의 첫 「문서 만들기」 — 저장한 연결을 다시 묻지 않는다(0.9.0 실사용 보고).

편집기에서 연결을 모두 확정해 저장한 새 HWPX 작업이, 처음 「문서 만들기」에 앉으면 모든
필드를 「입력이 필요한 항목」으로 세우고 생성을 막았다. 원인은 값이 아니라 순서였다: 편집기
저장 시점에는 작업 권위(``authority_id``)가 없어 결속 확정이 불리지 않았고, 권위는 착석이
나중에 발급한다. 판본이 없는 Work 의 활성 Field 는 전부 NEW_ACTIVE_FIELD 로 분류된다.

여기서는 제품 조립(:class:`WebFrontend`)과 동봉 예제로 실제 동선을 밟는다 — 누름틀·구간
변환 → 편집기 새 작업 저장 → 착석 → 구간 선택 → 생성. 슬롯 없는 예제는 legacy 생성 갈래라
막히지는 않았지만, 같은 목록과 ``REVIEW_BINDING`` 을 세워 생성 가능한 작업을 막힌 것처럼
말했다.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder

from hwpxfiller.application.document_creation_workbench import (
    DocumentCreationWorkbenchContextError,
)
from hwpxfiller.domain.job import JOB_MAPPING_AUTHORITY
from hwpxfiller.host.locations import home_dir


@pytest.fixture
def app(tmp_path):
    # conftest 가 ``HWPXFILLER_HOME`` 을 테스트별 임시 폴더로 못박는다 — 실 홈을 건드리지 않는다.
    from hwpxfiller.webapp.app import WebFrontend

    frontend = WebFrontend()
    assert frontend.dispatch("tpl", "install_examples", {"confirm": True})["ok"] is True
    return frontend


def _asset(name: str) -> Path:
    return next(home_dir().rglob(name))


def _save_new_work(app, name: str, template: str, data: str = "계약목록.csv") -> None:
    """편집기 새 작업 한 바퀴 — 자동 제안을 확정하고 저장한다(표면이 밟는 동선 그대로)."""
    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    app.dispatch("editor", "use_library_template", {"path": str(_asset(template))})
    editor.load_data_path(str(_asset(data)))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    app.dispatch("editor", "confirm_suggested", {})
    app.dispatch("editor", "set_name", {"name": name})
    assert app.dispatch("editor", "save", {}) == {"ok": True, "saved_name": name}
    assert app.controllers["job"].registry.load(name).authority_id == "", (
        "전제: 새 작업의 편집기 저장 시점에는 권위가 없다"
    )


def _choose_every_slot(app) -> None:
    view = app.dispatch("job", "open_slot_configuration", {})["current_view"]
    for slot in view["projection"]["slots"]:
        if slot["effective_option_ids"]:
            continue
        view = app.dispatch("job", "select_slot_option", {
            "configuration_token": view["new_configuration_token"],
            "slot_id": slot["slot_id"],
            "option_id": slot["options"][0]["option_id"],
            "request_id": uuid.uuid4().hex,
        })["current_view"]


def _workbench(app) -> dict:
    return app.controllers["job"].snapshot()["workbench_observation"]


def _open_compiled_slot_work(app, tmp_path: Path) -> None:
    practice = _asset("공고서_연습.hwpx")
    applied = app.dispatch("tpl", "compile", {"path": str(practice), "confirm": True})
    assert applied["mutated"] is True
    _save_new_work(app, "공고작업", "공고서_연습.hwpx")
    app.dispatch("job", "select_job", {"name": "공고작업"})
    app.dispatch("job", "set_all", {})
    pick_output_folder(app.controllers["job"], tmp_path / "out")
    _choose_every_slot(app)


def test_freshly_compiled_slot_work_generates_without_reconfirming_bindings(app, tmp_path):
    """구간 템플릿 새 작업은 저장된 Mapping 으로 준비되어 생성이 열린다."""
    _open_compiled_slot_work(app, tmp_path)

    wb = _workbench(app)
    assert wb["input_requirements"] == []
    assert "REVIEW_BINDING" not in wb["blockers"]
    assert wb["primary_action"] == "CREATE_DOCUMENTS"
    assert app.controllers["job"].registry.load("공고작업").binding_authority == JOB_MAPPING_AUTHORITY
    assert not list((home_dir() / "template_authority" / "field_bindings").glob("*.json"))

    result = app.generate("job")
    assert result["ok"] is True and result["succeeded"] == 3 and result["failed"] == 0


def test_slotless_sample_work_does_not_claim_inputs_are_missing(app, tmp_path):
    """슬롯 없는 예제 새 작업 — 착석만으로 판본이 서고, 확인 뒤에도 입력 요구가 없다."""
    _save_new_work(app, "샘플", "계약체결안내.hwpx")
    app.dispatch("job", "select_job", {"name": "샘플"})
    app.dispatch("job", "set_all", {})
    pick_output_folder(app.controllers["job"], tmp_path / "out")
    app.dispatch("job", "resolve_execution", {})

    wb = _workbench(app)
    assert wb["input_requirements"] == []
    assert "REVIEW_BINDING" not in wb["blockers"]

    result = app.generate("job")
    assert result["ok"] is True and result["succeeded"] == 3


def test_managed_generate_refuses_a_context_error_instead_of_raising(app, tmp_path):
    """관리 생성 직전 관찰이 복구 필요 맥락 실패면 **거절**한다 — 속성 접근으로 터지지 않는다."""
    _open_compiled_slot_work(app, tmp_path)
    job = app.controllers["job"]
    failure = DocumentCreationWorkbenchContextError(code="TEST_CONTEXT", detail="맥락 실패 대역")
    job.workbench_observation = lambda **_kwargs: failure

    result = app.generate("job")

    assert result["ok"] is False
    assert result["level"] == "warn"
    assert result["error"] == failure.detail
