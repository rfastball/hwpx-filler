"""slot 없는 동봉 예제의 문서 생성 수용 — HWPX 생성 경로는 managed 하나다(#1081 PR2).

실제 제품 조립(:class:`WebFrontend`)과 동봉 예제(``install_examples``)로 편집기 저장 → 작업
선택 → 「문서 만들기」를 태운다. 테스트 전용 배선·술어 교체가 없다 — slot 없는 작업이 실제로
managed 파이프라인을 지나는지가 여기서 재는 사실이다.

- 두 번째 실행은 앞서 만든 파일을 보고 덮어쓰기를 묻고, 확인하면 같은 이름을 다시 쓴다.
- 배달 전 취소는 파일 0건이다(전건 materialization 뒤에만 배달한다).
- 「내용 보기」는 slot 없는 작업의 결과 문서도 연다(모든 HWPX 결과가 managed 배달 사실이다).
- 배달마다 저장 폴더에 ``fill-ledger-*.json`` 사이드카가 쌓인다.
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder

from hwpxcore import extract_document
from hwpxcore.package import HwpxPackage
from hwpxcore.text_extract import full_text
from hwpxfiller.host.locations import home_dir
from hwpxfiller.webapp.artifact_view_session import ARTIFACT_OBSERVED

WORK = "수용"


@pytest.fixture
def app():
    # conftest 가 ``HWPXFILLER_HOME`` 을 테스트별 임시 폴더로 못박는다 — 실 홈을 건드리지 않는다.
    from hwpxfiller.webapp.app import WebFrontend

    frontend = WebFrontend()
    assert frontend.dispatch("tpl", "install_examples", {"confirm": True})["ok"] is True
    return frontend


def _asset(name: str) -> Path:
    return next(home_dir().rglob(name))


def _seat_sample(app, out: Path):
    """편집기 제안 그대로 저장한 slot 없는 작업을 고르고 전체 선택 + 저장 폴더까지."""
    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    app.dispatch("editor", "use_library_template", {"path": str(_asset("계약체결안내.hwpx"))})
    editor.load_data_path(str(_asset("계약목록.csv")))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    app.dispatch("editor", "confirm_suggested", {})
    app.dispatch("editor", "set_name", {"name": WORK})
    assert app.dispatch("editor", "save", {}) == {"ok": True, "saved_name": WORK}
    job = app.controllers["job"]
    app.dispatch("job", "select_job", {"name": WORK})
    app.dispatch("job", "set_all", {})
    pick_output_folder(job, out)
    snapshot = job.refresh_panel()
    assert snapshot["managed_hwpx"] is True
    assert not snapshot["slot_configuration"]["current_view"]["projection"]["slots"]
    assert snapshot["workbench_observation"]["create_action"]["enabled"] is True
    return job


def test_the_second_run_asks_to_overwrite_and_each_delivery_leaves_a_ledger(app, tmp_path):
    out = tmp_path / "out"
    _seat_sample(app, out)

    first = app.generate("job")
    assert first["ok"] is True and first["status"] == "completed", first
    made = sorted(p.name for p in out.glob("*.hwpx"))
    assert len(made) == 3

    asked = app.generate("job")
    assert asked["needs_overwrite"] is True, asked
    assert sorted(asked["conflict_names"]) == made
    assert sorted(p.name for p in out.glob("*.hwpx")) == made  # 묻는 동안 쓰지 않는다

    second = app.generate("job", confirm_overwrite=True)
    assert second["ok"] is True and second["status"] == "completed", second
    assert sorted(p.name for p in out.glob("*.hwpx")) == made
    assert len(list(out.glob("fill-ledger-*.json"))) == 2  # 배달마다 축적, 덮지 않는다


def test_cancel_before_delivery_writes_nothing(app, tmp_path):
    out = tmp_path / "out"
    job = _seat_sample(app, out)
    push = job._push_sink

    def cancel_after_first_record(screen, payload):
        # 첫 레코드가 materialization 을 마친 순간 사용자가 「다음 건부터 중단」을 누른다.
        if isinstance(payload, dict) and payload.get("progress", {}).get("done") == 1:
            assert app.dispatch("job", "cancel_generation", {})["ok"] is True
        push(screen, payload)

    job._push_sink = cancel_after_first_record
    result = app.generate("job")

    assert result["status"] == "cancelled" and result["cancelled"] is True, result
    assert result["succeeded"] == 0 and result["failed"] == 0
    assert not list(out.glob("*.hwpx")), "배달 전 취소가 문서를 남겼다"


def test_content_view_opens_a_slotless_result(app, tmp_path):
    out = tmp_path / "out"
    job = _seat_sample(app, out)
    made = app.generate("job")
    assert made["ok"] is True and made["status"] == "completed", made

    app.dispatch("job", "artifact_open", {"ordinal": 0})
    view = job.snapshot()["artifact_view"]

    assert view["open"] is True and view["status"] == ARTIFACT_OBSERVED, view
    assert view["filename"] == made["delivered"][0]["filename"]
    # 보기 원료는 그 문서의 검증된 bytes 다(#1138) — 그 bytes 에 첫 행 값이 표시형 그대로 있다.
    content = app.dispatch("job", "artifact_content", {})
    assert content["ok"] is True, content
    document = extract_document(HwpxPackage.from_bytes(base64.b64decode(content["content"])))
    assert "24,750,000원" in full_text(document)
