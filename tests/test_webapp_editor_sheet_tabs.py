"""편집기 「연결 확인」의 시트 탭 — 등록이 선언한 시트 중 작업이 쓸 시트를 고른다.

탭의 행·활성·고를 수 있는가는 작업 화면 하단 탭과 **같은 함수**
(:func:`hwpxfiller.webapp.screens.registered_sheet_tabs`)가 낸다. 전환은 등록 데이터 겨눔
(``use_pool_data``)에 시트를 실은 것이라 열·매핑 재조립도 데이터 교체와 같은 길을 지난다.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from hwpxfiller.domain.dataset_reference import DatasetReference
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.webapp.data_zone import JobDataSession
from hwpxfiller.webapp.screen_editor import EditorController
from hwpxfiller.webapp.screens import corrupt_dataset_text, registered_sheet_tabs

REPO = Path(__file__).resolve().parents[1]
TPL_COMPILED = REPO / "tests" / "corpus" / "scenario" / "templates" / "구매요청서.hwpx"
MULTI_SHEET = REPO / "tests" / "fixtures" / "multi_sheet.xlsx"
_PCLM_VIEW = "v_통합_v1"


def _editor(tmp_path: Path) -> "tuple[EditorController, DatasetPoolRegistry]":
    pool = DatasetPoolRegistry(tmp_path / "datasets")
    ctrl = EditorController(
        JobRegistry(tmp_path / "jobs"),
        lambda s, snap: None,
        clock=lambda: datetime(2026, 10, 7, 9, 0, 0),
        pool_registry=pool,
        is_library_path=lambda media, path: True,
    )
    return ctrl, pool


def _pclm_db(tmp_path: Path) -> str:
    """표 하나(``계약``) 위에 계약면 뷰를 얹은 SQLite — 표와 뷰가 서로 다른 시트다."""
    db = tmp_path / "pclm.db"
    connection = sqlite3.connect(db)
    connection.execute('CREATE TABLE 계약 ("계약건명" TEXT, "계약금액" TEXT);')
    connection.execute("INSERT INTO 계약 VALUES ('잔류항생제분석기', '170,309,180');")
    connection.execute(f'CREATE VIEW "{_PCLM_VIEW}" AS SELECT * FROM 계약;')
    connection.commit()
    connection.close()
    return str(db)


def _confirm_every_row(ctrl: EditorController) -> None:
    """전 행 확인 — 채울 것이 없는 행은 빈 고정값 선언으로 답한다(표면의 실제 동선)."""
    for row in ctrl.snapshot()["rows"]:
        if not row["confirmable"]:
            ctrl.dispatch("set_display", {"index": row["index"], "type": "const", "fmt": ""})
        ctrl.dispatch("set_confirmed", {"index": row["index"], "confirmed": True})


@pytest.mark.parametrize("kind", ["excel", "pclm"])
def test_binding_sheet_tabs_switch_save_and_reopen_on_the_chosen_sheet(tmp_path, kind):
    """탭은 선언한 시트뿐이고, 선언 밖은 fail-closed, 고른 시트가 저장본의 시트다.

    저장한 작업을 다시 열면 겨눔 표지(``data_pool_key``)가 없어도 등록 조회로 같은 탭이
    켜진다 — 우 열의 「지금 선 행」과 같은 조회다.
    """
    ctrl, pool = _editor(tmp_path)
    first, second = ("공고목록", "낙찰현황") if kind == "excel" else (_PCLM_VIEW, "계약")
    opts = {"path": str(MULTI_SHEET), "sheet": first} if kind == "excel" else {
        "db": _pclm_db(tmp_path), "view": first,
    }
    key = pool.add(DatasetReference(
        name="월별 공고", kind=kind, opts={**opts, "sheets": [first, second]},
    ))
    csv = tmp_path / "other.csv"
    csv.write_text("품명,수량\n연필,3\n", encoding="utf-8")
    other = pool.add(DatasetReference(name="다른 데이터", kind="excel", opts={"path": str(csv)}))
    ctrl.loader.load_template_path(str(TPL_COMPILED))
    assert ctrl.snapshot()["data_sheet_tabs"] == []

    assert ctrl.dispatch("use_pool_data", {"key": key})["ok"] is True
    tabs = ctrl.snapshot()["data_sheet_tabs"]
    assert [(r["key"], r["sheet"], r["active"], r["selectable"]) for r in tabs] == [
        (key, first, True, True), (key, second, False, True),
    ]
    # 작업 화면과 **같은 함수**의 투영이다 — 표면마다 탭 판정이 갈리지 않는다.
    assert tabs == registered_sheet_tabs(
        pool, key, path=ctrl.edit.data_path, sheet=first, kind=ctrl.edit.data_kind,
    )

    ctrl.dispatch("goto_section", {"section": "binding"})
    assert ctrl.dispatch("use_pool_data", {"key": key, "sheet": second}) == {
        "ok": True, "label": "월별 공고",
    }
    snap = ctrl.snapshot()
    assert snap["section"] == "binding" and snap["data_sheet"] == second
    assert [(r["sheet"], r["active"]) for r in snap["data_sheet_tabs"]] == [
        (first, False), (second, True),
    ]
    if kind == "excel":
        assert ctrl.edit.source_fields == ["업체명", "낙찰금액", "계약일"]
    assert ctrl.edit.model_key == ctrl.edit.model_key_now()

    # 선언 밖 시트는 마운트 전에 거절 — 데이터·매핑 어느 것도 바뀌지 않는다.
    records, model = ctrl.edit.records, ctrl.edit.model
    refused = ctrl.dispatch("use_pool_data", {"key": key, "sheet": "미등록"})
    assert refused["ok"] is False and refused["error"]
    assert ctrl.edit.data_sheet == second and ctrl.edit.records is records
    assert ctrl.edit.model is model

    _confirm_every_row(ctrl)
    ctrl.dispatch("set_name", {"name": "시트작업"})
    assert ctrl.dispatch("save", {})["ok"] is True
    assert JobRegistry(tmp_path / "jobs").load("시트작업").data_sheet == second
    # 고른 시트는 작업의 것이다 — 등록의 기본 시트는 그대로다.
    assert pool.load(key).opts["sheet" if kind == "excel" else "view"] == first

    reopened, _ = _editor(tmp_path)
    reopened.load_job("시트작업")
    snap = reopened.snapshot()
    assert snap["data_pool_key"] == "" and snap["data_sheet"] == second
    assert [(r["key"], r["sheet"], r["active"]) for r in snap["data_sheet_tabs"]] == [
        (key, first, False), (key, second, True),
    ]
    assert reopened.dispatch("use_pool_data", {"key": key, "sheet": first})["ok"] is True
    assert reopened.edit.data_sheet == first and reopened.has_unsaved_work()

    # 다른 등록으로 바꾸면 그 등록의 선언만 남는다 — 시트 선언이 없으면 탭 띠도 없다.
    assert reopened.dispatch("use_pool_data", {"key": other})["ok"] is True
    assert reopened.snapshot()["data_sheet_tabs"] == []


def test_binding_sheet_tabs_do_not_mix_a_relinked_registration_with_the_open_file(tmp_path):
    """다시 연결한 등록의 시트를 아직 열린 옛 파일의 탭으로 세우지 않는다(작업 화면 동형)."""
    ctrl, pool = _editor(tmp_path)
    sheets = ["공고목록", "낙찰현황"]
    key = pool.add(DatasetReference(name="월별 공고", kind="excel", opts={
        "path": str(MULTI_SHEET), "sheet": "공고목록", "sheets": sheets,
    }))
    ctrl.loader.load_template_path(str(TPL_COMPILED))
    assert ctrl.dispatch("use_pool_data", {"key": key})["ok"] is True
    moved = tmp_path / "moved.xlsx"
    shutil.copy(MULTI_SHEET, moved)
    pool.relink_excel(key, str(moved), sheet="공고목록", sheets=sheets)
    ctrl.refresh_panel()

    assert ctrl.snapshot()["data_sheet_tabs"] == []


def test_a_corrupt_registration_is_not_projected_as_a_registration_without_tabs(tmp_path):
    """손상된 등록을 「시트 선언 없음」(빈 띠)으로 낮추지 않는다 — 막힌 탭과 손상 문장이 선다.

    문장은 풀 목록의 손상 통지와 **같은 함수**가 짓는다(같은 손상을 두 문형으로 말하지 않는다).
    지워진 등록은 종전대로 띠가 없다. 읽어 둔 데이터는 어느 쪽이든 그대로다.
    """
    ctrl, pool = _editor(tmp_path)
    key = pool.add(DatasetReference(name="월별 공고", kind="excel", opts={
        "path": str(MULTI_SHEET), "sheet": "공고목록", "sheets": ["공고목록", "낙찰현황"],
    }))
    ctrl.loader.load_template_path(str(TPL_COMPILED))
    assert ctrl.dispatch("use_pool_data", {"key": key})["ok"] is True
    records = ctrl.edit.records

    pool.slot_path(key).write_text("{깨진 JSON", encoding="utf-8")
    ctrl.refresh_panel()
    _entries, corrupted = pool.list_references()
    assert [entry.file_name for entry in corrupted] == [pool.slot_path(key).name]
    assert ctrl.snapshot()["data_sheet_tabs"] == [{
        "key": key, "sheet": "공고목록", "active": True, "selectable": False,
        "reason": corrupt_dataset_text(corrupted[0].file_name, corrupted[0].error),
        "damaged": True,
    }]
    assert ctrl.edit.records is records
    # 막힌 탭을 우회해 보내도 마운트 관문이 손상을 그대로 거절한다(상태 불변).
    refused = ctrl.dispatch("use_pool_data", {"key": key, "sheet": "낙찰현황"})
    assert refused["ok"] is False and ctrl.edit.records is records

    # 작업 화면 하단 띠도 같은 함수다 — 같은 손상에 같은 막힌 탭을 낸다.
    zone = JobDataSession(pool)
    zone.pool_key, zone.path, zone.sheet, zone.kind = key, ctrl.edit.data_path, "공고목록", ""
    assert zone.sheet_tabs() == ctrl.snapshot()["data_sheet_tabs"]

    pool.slot_path(key).unlink()
    ctrl.refresh_panel()
    assert ctrl.snapshot()["data_sheet_tabs"] == []
    assert zone.sheet_tabs() == []


@pytest.mark.parametrize("remembered,broken", [(False, False), (True, False), (True, True), (False, True)])
def test_registered_data_boot_keeps_remembered_mount_and_reports_discovery_failure(tmp_path, remembered, broken):
    from test_webapp_job import _controller, _data_csv
    ctrl, _ = _controller(tmp_path)
    csv = _data_csv(tmp_path)
    discovered = tmp_path / "registered.csv"
    discovered.write_text("field\nvalue\n", encoding="utf-8")
    descriptor = {"source": "file", "path": str(discovered), "sheet": "", "header_row": 0, "pool_key": ""}
    calls = []

    def discover():
        calls.append(True)
        if broken:
            raise ValueError("broken registered source")
        return descriptor

    ctrl._registered_data = discover
    if remembered:
        ctrl._remembered_data_source = {**descriptor, "path": csv}
    ctrl.initial()
    assert ctrl.data.path == (csv if remembered else "" if broken else str(discovered))
    if broken:
        assert "broken registered source" in ctrl.data.notice_text
    ctrl.initial()
    assert calls == [True]


def test_sheet_reordering_persists_without_changing_binding_or_filters(tmp_path):
    from hwpxfiller.domain.dataset_reference import reference_sheets
    from hwpxfiller.webapp.screens import registered_sheet_tabs

    from test_webapp_pool import _controller
    ctrl, registry, _ = _controller(tmp_path)
    path = str(tmp_path / "book.xlsx")
    Path(path).touch()
    key = registry.add(DatasetReference(name="book", kind="excel", opts={
        "path": path, "sheet": "A", "sheets": ["A", "B", "C"],
    }, filters=[{"name": "keep", "state": {}}],
        sheet_filters={"B": [{"name": "also keep", "state": {}}]}))
    before = registry.load(key).to_dict()
    ctrl.dispatch("reorder_sheets", {"key": key, "sheets": ["C", "A", "B"]})
    reopened = DatasetPoolRegistry(registry.directory)
    saved = reopened.load(key)
    assert reference_sheets(saved) == ["C", "A", "B"]
    assert saved.opts["sheet"] == "A"
    assert saved.filters == before["filters"] and saved.sheet_filters == before["sheet_filters"]
    assert [(r["sheet"], r["active"]) for r in registered_sheet_tabs(
        reopened, key, path=path, sheet="B", kind="excel",
    )] == [("C", False), ("A", False), ("B", True)]
    for invalid in (["A", "B"], ["A", "B", "B"], ["A", "B", "foreign"], "ABC", [[], "B", "C"]):
        with pytest.raises(ValueError, match="시트"):
            ctrl.dispatch("reorder_sheets", {"key": key, "sheets": invalid})
    assert reopened.load(key).to_dict() == saved.to_dict()
