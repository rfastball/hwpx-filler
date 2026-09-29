"""managed 「문서 만들기」의 반복 실행·진행 델타·완주 기록 (#1081 PR0).

legacy 갈래가 이미 지키던 세 계약을 managed 갈래가 빠뜨리고 있었다. 제품 조립
(:class:`WebFrontend`)과 동봉 예제로 실제 동선을 밟는다 — 구간 변환 → 편집기 새 작업 저장 →
착석 → 구간 선택 → 생성.

1. **두 번째 실행**: 배달 준비는 폴더 관찰에 묶인 값인데 런이 파일을 앉힌 뒤에도 그대로 남아,
   다음 실행이 「없던 파일」로 계획해 덮어쓰기 확인 대신 관찰 불일치로 멈췄다.
2. **진행 델타**: managed 파이프라인의 진행 hook 이 조립되지 않아 진행바가 움직이지 않았다.
3. **완주 기록**: 전건 안착해도 ``last_run_at``·검토 기준선이 찍히지 않았다(legacy 는 찍는다).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder

from hwpxfiller.domain.job import rules_fingerprints
from hwpxfiller.host.locations import home_dir

WORK = "공고작업"


@pytest.fixture
def app(tmp_path):
    # conftest 가 ``HWPXFILLER_HOME`` 을 테스트별 임시 폴더로 못박는다 — 실 홈을 건드리지 않는다.
    from hwpxfiller.webapp.app import WebFrontend

    frontend = WebFrontend()
    assert frontend.dispatch("tpl", "install_examples", {"confirm": True})["ok"] is True
    return frontend


def _asset(name: str) -> Path:
    return next(home_dir().rglob(name))


def _open_slot_work(app, out: Path) -> None:
    """구간 템플릿 새 작업을 착석시키고 모든 구간을 고른다 — managed 갈래의 실제 진입."""
    practice = _asset("공고서_연습.hwpx")
    assert app.dispatch("tpl", "compile", {"path": str(practice), "confirm": True})["mutated"]
    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    app.dispatch("editor", "use_library_template", {"path": str(practice)})
    editor.load_data_path(str(_asset("계약목록.csv")))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    app.dispatch("editor", "confirm_suggested", {})
    app.dispatch("editor", "set_name", {"name": WORK})
    assert app.dispatch("editor", "save", {}) == {"ok": True, "saved_name": WORK}
    app.dispatch("job", "select_job", {"name": WORK})
    app.dispatch("job", "set_all", {})
    pick_output_folder(app.controllers["job"], out)
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
    assert app.controllers["job"].snapshot()["managed_hwpx"] is True, "전제: managed 갈래"


def _planned_dispositions(app) -> list[str]:
    wb = app.controllers["job"].snapshot()["workbench_observation"]
    return [doc["collision_disposition"] for doc in wb["delivery"]["planned_documents"]]


def _hwpx_names(out: Path) -> list[str]:
    return sorted(path.name for path in out.glob("*.hwpx"))


def test_second_managed_run_asks_to_overwrite_then_overwrites(app, tmp_path):
    out = tmp_path / "out"
    _open_slot_work(app, out)

    first = app.generate("job")
    assert first["ok"] is True and first["status"] == "completed" and first["succeeded"] == 3
    names = _hwpx_names(out)
    assert len(names) == 3
    # 런이 앉힌 파일을 다음 계획이 본다 — 낡은 WRITE_NEW 관찰을 재사용하지 않는다.
    assert _planned_dispositions(app) == ["WRITE_OVERWRITE"] * 3

    second = app.generate("job")
    assert second["ok"] is False
    assert second["needs_overwrite"] is True
    assert second["overwrite_count"] == 3 and second["new_count"] == 0
    assert sorted(second["conflict_names"]) == names
    assert _hwpx_names(out) == names, "확인 전에는 아무것도 바꾸지 않는다"

    confirmed = app.generate("job", confirm_overwrite=True)
    assert confirmed["ok"] is True and confirmed["status"] == "completed"
    assert confirmed["succeeded"] == 3 and confirmed["failed"] == 0
    assert {row["disposition"] for row in confirmed["delivered"]} == {"WRITE_OVERWRITE"}
    assert _hwpx_names(out) == names


def test_managed_run_pushes_progress_deltas_in_order(app, tmp_path):
    _open_slot_work(app, tmp_path / "out")
    job = app.controllers["job"]
    deltas: list[dict] = []
    forward = job._push_sink

    def sink(screen: str, payload: dict) -> None:
        if "progress" in payload:
            deltas.append(payload["progress"])
        forward(screen, payload)

    job._push_sink = sink
    result = app.generate("job", run_token="tok-1")

    assert result["ok"] is True and result["succeeded"] == 3
    assert [(d["done"], d["total"]) for d in deltas] == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert {d["run_token"] for d in deltas} == {"tok-1"}


def test_completed_managed_run_stamps_last_run_and_reviewed_rules(app, tmp_path):
    _open_slot_work(app, tmp_path / "out")
    job = app.controllers["job"]
    before = job.registry.load(WORK)
    assert before.last_run_at == "", "전제: 미실행"

    result = app.generate("job")

    assert result["ok"] is True and result["status"] == "completed"
    after = job.registry.load(WORK)
    assert after.last_run_at != ""
    assert after.reviewed_rules == rules_fingerprints(after)
    # 세션 사본도 완주 기록을 본다 — 디스크만 바뀌면 다음 스냅샷이 옛 기준선으로 판정한다.
    assert job.work.vm.job.last_run_at == after.last_run_at


def test_cancelled_managed_run_writes_nothing_and_stamps_nothing(app, tmp_path):
    out = tmp_path / "out"
    _open_slot_work(app, out)
    job = app.controllers["job"]
    forward = job._push_sink

    def cancel_on_start(screen: str, payload: dict) -> None:
        if payload.get("progress", {}).get("done") == 0:
            job.runs.request_cancel()
        forward(screen, payload)

    job._push_sink = cancel_on_start
    result = app.generate("job")

    assert result["ok"] is True and result["cancelled"] is True
    assert result["status"] == "cancelled" and result["attempted"] == 0
    assert _hwpx_names(out) == []
    assert job.registry.load(WORK).last_run_at == ""


def test_completion_stamp_failure_is_reported_not_raised(app, tmp_path, monkeypatch):
    out = tmp_path / "out"
    _open_slot_work(app, out)
    job = app.controllers["job"]

    def refuse(*_args, **_kwargs):
        raise OSError("디스크 가득 참 대역")

    monkeypatch.setattr(job.registry, "stamp_last_run", refuse)
    result = app.generate("job")

    assert result["ok"] is True and result["status"] == "completed"
    assert result["level"] == "danger"
    assert "실행 기록 저장에 실패했습니다(디스크 가득 참 대역)" in result["summary"]
    assert len(_hwpx_names(out)) == 3, "문서는 이미 앉았다"
    assert job.registry.load(WORK).last_run_at == ""
