"""실행 화면 「문서」 열 == 배달이 쓸 이름 (#798 · #1081 PR1).

「문서」 열은 legacy 파일명 규칙(대소문자 구분 충돌)으로, 배달은 managed 규칙(casefold)으로
이름을 지어서, ``Report``·``report`` 두 행이 있으면 화면은 ``report.hwpx`` 를 약속하고 배달은
``report_1.hwpx`` 를 썼다. 둘이 같은 이름 kernel 을 부르는지 실제 제품 조립으로 본다.
"""
from __future__ import annotations

import csv
import uuid
from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder

from hwpxfiller.host.locations import home_dir

WORK = "이름일치"


@pytest.fixture
def app(tmp_path):
    from hwpxfiller.webapp.app import WebFrontend

    frontend = WebFrontend()
    assert frontend.dispatch("tpl", "install_examples", {"confirm": True})["ok"] is True
    return frontend


def _asset(name: str) -> Path:
    return next(home_dir().rglob(name))


def _data_with_case_twins(tmp_path: Path) -> Path:
    """동봉 계약목록에서 품명만 대소문자 쌍으로 바꾼 사본."""
    with _asset("계약목록.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["품명"], rows[1]["품명"], rows[2]["품명"] = "Report", "report", "B"
    target = tmp_path / "쌍둥이.csv"
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return target


def _seat_managed_work(app, tmp_path: Path, pattern: str) -> None:
    practice = _asset("공고서_연습.hwpx")
    assert app.dispatch("tpl", "compile", {"path": str(practice), "confirm": True})["mutated"]
    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    app.dispatch("editor", "use_library_template", {"path": str(practice)})
    editor.load_data_path(str(_data_with_case_twins(tmp_path)))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    app.dispatch("editor", "confirm_suggested", {})
    app.dispatch("editor", "set_name", {"name": WORK})
    assert app.dispatch("editor", "save", {}) == {"ok": True, "saved_name": WORK}
    job = app.controllers["job"]

    def use_pattern(saved) -> None:
        saved.filename_pattern = pattern

    job.registry.mutate(WORK, use_pattern)
    app.dispatch("job", "select_job", {"name": WORK})
    app.dispatch("job", "set_all", {})
    pick_output_folder(job, tmp_path / "out")
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
    assert job.snapshot()["managed_hwpx"] is True, "전제: managed 갈래"


def _shown_names(app) -> list[str]:
    snapshot = app.controllers["job"].snapshot()
    return [row["name"] for row in snapshot["records"] if row["selected"]]


def _planned(app) -> dict:
    return app.controllers["job"].snapshot()["workbench_observation"]["delivery"]


def test_document_column_shows_the_names_delivery_will_write(app, tmp_path):
    _seat_managed_work(app, tmp_path, "{{품명}}")

    planned = [
        doc["relative_path"]
        for doc in sorted(_planned(app)["planned_documents"], key=lambda d: d["item_ordinal"])
    ]
    # 배치 순서는 표시순서다 — 어느 쪽이 먼저든 대소문자 쌍의 둘째가 꼬리표를 단다(casefold).
    assert len(planned) == 3 and "B.hwpx" in planned
    twins = [name for name in planned if name != "B.hwpx"]
    assert twins[0].casefold() == "report.hwpx" and twins[1].casefold() == "report_1.hwpx"
    assert _shown_names(app) == planned

    result = app.generate("job")
    assert result["ok"] is True and result["status"] == "completed", result
    assert [row["filename"] for row in result["delivered"]] == planned


def test_document_column_is_empty_when_delivery_refuses_the_pattern(app, tmp_path):
    """이름을 만들 수 없는 패턴(닫히지 않은 ``{{``)은 두 표면 모두 이름을 내지 않는다."""
    _seat_managed_work(app, tmp_path, "{{품명")

    delivery = _planned(app)
    assert delivery["planned_documents"] == []
    assert [b["code"] for b in delivery["blockers"]] == ["OUTPUT_NAME_PATTERN_INVALID"]
    assert set(_shown_names(app)) == {""}
