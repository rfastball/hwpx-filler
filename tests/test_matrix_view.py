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
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _wait_pool_load(view, timeout: float = 8.0) -> None:
    """풀 복원이 QThread(RC-12 공용 계층)로 돌므로 완료(스레드 해제)까지 이벤트 루프."""
    import time

    from PySide6.QtCore import QCoreApplication

    deadline = time.monotonic() + timeout
    while view._data_thread is not None:
        QCoreApplication.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("풀 복원이 제한시간 내에 끝나지 않았습니다")
        time.sleep(0.005)
    QCoreApplication.processEvents()


def _registry(tmp_path):
    reg = JobRegistry(tmp_path / "jobs")
    tpl = tmp_path / "t.hwpx"
    xml = (
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p/></hs:sec>'
    ).encode()
    HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}).save(str(tpl))
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
    _wait_pool_load(view)  # 복원은 QThread(RC-12) — 단일 실행과 같은 비동기 공용 경로
    assert len(view.vm.records) == 1
    assert view.ed_data.text().startswith("풀: 6월")
    assert view.btn_pool.isEnabled()  # 복원 후 데이터 버튼 잠금 해제


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

        def __init__(self, jobs, datasource, indices, out_dir, *, overwrite=False,
                     now=None):
            super().__init__()
            captured["jobs"] = jobs
            captured["indices"] = indices
            captured["out_dir"] = out_dir
            captured["overwrite"] = overwrite
            captured["now"] = now

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


def test_matrix_view_partial_failure_modal_mentions_failures(qapp, tmp_path, monkeypatch):
    """RC-30(매트릭스 사본) — 부분 실패 완료 모달: 실패 병기(경고형) + 행동 지향 로그."""
    from PySide6.QtWidgets import QMessageBox as MB

    from hwpxfiller.batch import BatchResult, MatrixJobResult, MatrixResult
    from hwpxfiller.core.engine import GenerateResult
    from hwpxfiller.gui import batch_run
    from hwpxfiller.gui.matrix_view import MatrixRunView

    view = MatrixRunView(_registry(tmp_path))
    out_dir = str(tmp_path / "out")
    view._out_dir = out_dir  # 생성 시작 시점 캡처값(완료 모달이 소비)
    seen = {}
    monkeypatch.setattr(
        MB, "warning",
        lambda parent, title, text, *a, **k: (seen.update(text=text), MB.Yes)[1],
    )
    monkeypatch.setattr(
        MB, "question",
        lambda *a, **k: pytest.fail("부분 실패는 경고형 모달이어야 한다(RC-30)"),
    )
    opened = []
    monkeypatch.setattr(batch_run, "open_folder", opened.append)

    batch = BatchResult(total=2, succeeded=1, results=[
        GenerateResult(True, "a.hwpx"),
        GenerateResult(False, "b.hwpx",
                       error="저장 실패: [Errno 13] Permission denied: 'b.hwpx'"),
    ])
    result = MatrixResult(per_job=[MatrixJobResult("공고", out_dir + "/공고", batch)])
    view._on_finished(result)

    assert "1건 성공" in seen["text"] and "1건 실패" in seen["text"] and "로그" in seen["text"]
    assert opened == [out_dir]                            # 확정(Yes) → 공용 open_folder
    assert view.lbl_result.property("level") == "danger"
    log = view.log.toPlainText()
    assert "파일 접근이 거부됐습니다" in log                # 행동 지향 문구(RC-30)
    assert "b.hwpx" in log                                 # 실패 대상 식별 가능


def _field_template(path, fields):
    body = "".join(
        f'<hp:run><hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl></hp:run>'
        f'<hp:run><hp:t>{{{{{name}}}}}</hp:t></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        for name in fields
    )
    xml = (
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        + body + '</hp:p></hs:sec>'
    ).encode()
    HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}).save(str(path))


def test_matrix_view_missing_gate_blocks_and_badges_appear(qapp, tmp_path, monkeypatch):
    """UD-04 — 미입력 배지·확인 게이트 이식: 미확인 미입력이 일괄 생성을 막고(우회
    소멸 해소), 배지 클릭 확인 후 워커가 기동된다."""
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QPushButton

    from hwpxfiller.core.mapping import FieldMapping, MappingProfile  # noqa: E402
    from hwpxfiller.gui import matrix_view as mv
    from hwpxfiller.gui.matrix_view import MatrixRunView

    reg = JobRegistry(tmp_path / "jobs")
    tpl = tmp_path / "t.hwpx"
    _field_template(tpl, ["공고명", "추정가격"])
    reg.save(Job(name="공고", template_path=str(tpl), mapping=MappingProfile(mappings=[
        FieldMapping("공고명", ["공고명"]), FieldMapping("추정가격", ["추정가격"]),
    ]), filename_pattern="공고-{{공고명}}"))
    csv = tmp_path / "d.csv"
    csv.write_text("공고명,추정가격\n전산,\n", encoding="utf-8")  # 추정가격 빈값 → 미입력

    view = MatrixRunView(reg)
    view.job_list.item(0).setCheckState(Qt.Checked)
    view.vm.load_file(str(csv))
    view._after_data_loaded(str(csv))
    view.ed_out.setText(str(tmp_path / "out"))

    # 미확인 미입력 → 게이트 닫힘(버튼 비활성) + 인라인 사유 재진술 + missing 배지 존재.
    assert view.btn_generate.isEnabled() is False
    assert "추정가격" in view.lbl_gate.text()
    missing_chips = [w for w in view.badge_host.findChildren(QPushButton)
                     if w.property("fb") == "missing"]
    assert missing_chips, "미입력 배지가 렌더돼야 한다"

    started = {}

    class _FakeWorker(QObject):
        progress = Signal(int, int)
        finished = Signal(object)
        failed = Signal(str)

        def __init__(self, *a, **k):
            super().__init__()
            started["yes"] = True

        def run(self):
            pass

    monkeypatch.setattr(mv, "MatrixGenerateWorker", _FakeWorker)

    # 우회 재현: 미확인 상태에서 생성 시도 → 워커 미기동(하드스톱 유지).
    view._on_generate()
    assert view._thread is None and "yes" not in started

    # 배지 클릭 확인 → 게이트 열림 → 생성 기동.
    view._ack_field("공고", "추정가격")
    assert view.btn_generate.isEnabled() is True
    view._on_generate()
    try:
        assert started.get("yes") is True
    finally:
        view._teardown_thread()


def test_app_controller_opens_matrix_run(qapp, tmp_path):
    from hwpxfiller.gui.app import AppController
    from hwpxfiller.gui.matrix_view import MatrixRunView

    ctrl = AppController(_registry(tmp_path))
    ctrl._open_matrix_run()
    views = [c for c in ctrl._children if isinstance(c, MatrixRunView)]
    assert len(views) == 1


def test_app_controller_records_matrix_run(qapp, tmp_path):
    """매트릭스 성공분이 작업별 last_run_at 에 기록된다."""
    from hwpxfiller.gui.app import AppController

    reg = _registry(tmp_path)
    ctrl = AppController(reg)

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
