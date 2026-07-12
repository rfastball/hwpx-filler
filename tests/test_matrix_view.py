"""매트릭스 실행 GUI(J2) 스모크 — offscreen. 창 배선 + 대시보드 진입 + 생성 오케스트레이션.

깊은 로직은 test_matrix*.py 가 헤드리스로 검증한다.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry  # noqa: E402
from hwpxfiller.core.job import Job, JobRegistry  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _registry(tmp_path):
    reg = JobRegistry(tmp_path / "jobs")
    tpl = tmp_path / "t.hwpx"
    tpl.write_bytes(b"dummy")
    reg.save(Job(name="공고", template_path=str(tpl), filename_pattern="공고-{{ID}}"))
    reg.save(Job(name="요청", template_path=str(tpl), filename_pattern="요청-{{ID}}"))
    return reg


def test_matrix_view_lists_and_toggles_jobs(qapp, tmp_path):
    from hwpxfiller.gui.matrix_view import MatrixRunView

    view = MatrixRunView(_registry(tmp_path))
    assert view.job_list.count() == 2
    # 항목은 체크 가능, 기본 미선택.
    it = view.job_list.item(0)
    assert it.flags() & Qt.ItemIsUserCheckable
    it.setCheckState(Qt.Checked)
    assert view.vm.selection_count() == 1
    assert "1개" in view.lbl_sel.text()

    view._check_all(True)
    assert view.vm.selection_count() == 2
    view._check_all(False)
    assert view.vm.selection_count() == 0


def test_matrix_view_pool_pick_loads_records(qapp, tmp_path, monkeypatch):
    from hwpxfiller.gui.matrix_view import MatrixRunView

    csv = tmp_path / "d.csv"
    csv.write_text("ID,공고명\n1,전산\n", encoding="utf-8")
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pool.save(DatasetPoolItem(name="6월", kind="excel", opts={"path": str(csv)}))

    view = MatrixRunView(_registry(tmp_path), pool_registry=pool)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("6월", True))
    view._pick_from_pool()
    assert len(view.vm.records) == 1
    assert view.ed_data.text().startswith("풀: 6월")


def test_matrix_view_pool_empty_informs(qapp, tmp_path, monkeypatch):
    from hwpxfiller.gui.matrix_view import MatrixRunView

    view = MatrixRunView(_registry(tmp_path), pool_registry=DatasetPoolRegistry(tmp_path / "p"))
    seen = {}
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: seen.setdefault("m", a[2]))
    view._pick_from_pool()
    assert "활성 데이터가 없습니다" in seen.get("m", "")


def test_matrix_view_generate_gate_and_worker(qapp, tmp_path, monkeypatch):
    """생성 게이트(선택·데이터·행·폴더) 통과 시 매트릭스 워커를 선택 작업으로 기동."""
    from PySide6.QtCore import QObject, Signal

    from hwpxfiller.gui import matrix_view as mv
    from hwpxfiller.gui.matrix_view import MatrixRunView

    csv = tmp_path / "d.csv"
    csv.write_text("ID\n1\n2\n", encoding="utf-8")
    view = MatrixRunView(_registry(tmp_path))

    # 아무것도 준비 안 됨 → 게이트가 경고로 막고 워커 미기동.
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.setdefault("m", a[2]))
    view._on_generate()
    assert view._thread is None and "작업" in warned.get("m", "")

    captured = {}

    class _FakeWorker(QObject):
        progress = Signal(int, int)
        finished = Signal(object)
        failed = Signal(str)

        def __init__(self, jobs, datasource, indices, out_dir):
            super().__init__()
            captured["jobs"] = jobs
            captured["indices"] = indices
            captured["out_dir"] = out_dir

        def run(self):
            pass

    monkeypatch.setattr(mv, "MatrixGenerateWorker", _FakeWorker)

    view.job_list.item(0).setCheckState(Qt.Checked)  # 공고
    view.vm.load_file(str(csv))
    view.selector.set_records(view.vm.records, "행-{{seq}}")
    view.ed_out.setText(str(tmp_path / "out"))
    view._on_generate()
    try:
        assert [j.name for j in captured["jobs"]] == ["공고"]
        assert captured["indices"] == [0, 1]
        assert captured["out_dir"].endswith("out")
    finally:
        view._teardown_thread()


def test_app_controller_opens_matrix_run(qapp, tmp_path):
    from hwpxfiller.gui.app import _AppController
    from hwpxfiller.gui.matrix_view import MatrixRunView

    ctrl = _AppController(_registry(tmp_path))
    ctrl._open_matrix_run()
    views = [c for c in ctrl._children if isinstance(c, MatrixRunView)]
    assert len(views) == 1


def test_app_controller_records_matrix_run(qapp, tmp_path):
    """매트릭스 성공분이 작업별 last_run_at 에 기록된다."""
    from hwpxfiller.gui.app import _AppController

    reg = _registry(tmp_path)
    ctrl = _AppController(reg)

    class _Batch:
        succeeded = 2

    class _JR:
        job_name = "공고"
        batch = _Batch()

    class _Result:
        per_job = [_JR()]

    ctrl._record_matrix_run(_Result())
    assert reg.load("공고").last_run_at != ""
    assert reg.load("요청").last_run_at == ""  # 미실행 작업은 불변
