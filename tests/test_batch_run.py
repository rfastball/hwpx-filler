"""run/matrix 공용 실행 계층(RC-22) — 완료 문구(RC-30)·오류 번역·QThread 수명주기 계약.

사본 시절 한쪽만 고쳐지던 것들(완료 모달·teardown·실패 라우팅)이 이제 한 곳에 있다 —
그 한 곳의 계약을 직접 못박는다. 뷰 관통은 test_gui_smoke/test_matrix_view 가 검증한다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QWidget,
)

from hwpxfiller.gui.batch_run import (  # noqa: E402
    BatchRunController,
    DataAcquireController,
    completion_notice,
    describe_result_error,
)

MULTI_SHEET = Path(__file__).parent / "fixtures" / "multi_sheet.xlsx"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ------------------------------------------------------------ 완료 모달 문구(RC-30)
def test_completion_notice_mentions_partial_failure():
    """부분 실패는 '완료' 서사로 덮이지 않는다 — 실패 건수·로그 안내 병기 + 경고형."""
    level, text = completion_notice(2, 1)
    assert level == "warn"
    assert "2건 성공" in text and "1건 실패" in text and "로그" in text
    assert "결과 폴더를 여시겠습니까?" in text


def test_completion_notice_all_success_stays_question():
    level, text = completion_notice(3, 0)
    assert level == "ok"
    assert "3건 생성 완료" in text and "실패" not in text


def test_describe_result_error_translates_to_actionable_korean():
    """원시 errno → 행동 지향 문구(RC-30). 원문은 증거로 보존, 미지 오류는 무변형."""
    raw = "저장 실패: [Errno 13] Permission denied: 'C:/out/doc-가.hwpx'"
    described = describe_result_error(raw)
    assert "파일 접근이 거부됐습니다" in described and "확인하세요" in described
    assert raw in described                       # 원문 보존(조용한 재작성 금지)
    assert describe_result_error("알 수 없는 오류") == "알 수 없는 오류"


def test_describe_result_error_fires_on_localized_winerror():
    """한국어 Windows 의 WinError 지역화 문자열에 발화(반려 조치) — os.replace 원자
    쓰기(실제 저장 경로)는 영문 errno 가 아니라 "[WinError N] …" 로 도착한다."""
    # 실 재현 형태(권한 거부): 임시파일 rename 내부까지 노출되는 원시 문자열 그대로.
    raw = (
        "저장 실패: [WinError 5] 액세스가 거부되었습니다: "
        "'C:/out/.doc-가.hwpx.tmp' -> 'C:/out/doc-가.hwpx'"
    )
    described = describe_result_error(raw)
    assert "파일 접근이 거부됐습니다" in described
    assert raw in described                       # 원문 보존(조용한 재작성 금지)
    # 힌트 문구가 스스로 안내하는 시나리오(한글 등에 열린 파일 = WinError 32)도 발화.
    locked = (
        "[WinError 32] 다른 프로세스가 파일을 사용 중이기 때문에 "
        "프로세스가 액세스 할 수 없습니다: 'C:/out/doc.hwpx'"
    )
    assert "닫은 뒤 다시 시도하세요" in describe_result_error(locked)
    # 디스크 부족(WinError 112).
    full = "[WinError 112] 디스크에 공간이 부족합니다: 'C:/out/doc.hwpx'"
    assert "디스크 공간이 부족합니다" in describe_result_error(full)


# ------------------------------------------------------------ QThread 수명주기(RC-22)
class _FakeWorker(QObject):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.cancelled = False

    def run(self):
        pass

    def cancel(self):
        self.cancelled = True


def _harness(qapp):
    """컨트롤러 + 위젯 다발 — 뷰 없이 수명주기 계약만 본다."""
    view = QWidget()
    widgets = {
        "progress": QProgressBar(view),
        "lbl_result": QLabel(view),
        "btn_generate": QPushButton(view),
        "btn_cancel": QPushButton(view),
    }
    widgets["btn_cancel"].setEnabled(False)
    log: "list[str]" = []
    seen: "dict[str, object]" = {}
    runner = BatchRunController(
        view,
        progress=widgets["progress"],
        lbl_result=widgets["lbl_result"],
        btn_generate=widgets["btn_generate"],
        btn_cancel=widgets["btn_cancel"],
        say=log.append,
        on_idle=lambda: seen.setdefault("idle", True),
        on_result=lambda result, worker: seen.update(result=result, worker=worker),
    )
    return view, runner, widgets, log, seen


def test_controller_start_finish_routes_result_after_teardown(qapp):
    view, runner, w, _log, seen = _harness(qapp)
    worker = _FakeWorker()
    runner.start(worker, total=5)
    try:
        assert runner.running is True
        assert not w["btn_generate"].isEnabled() and w["btn_cancel"].isEnabled()
        assert w["progress"].maximum() == 5 and w["progress"].value() == 0
    finally:
        runner.finish("RESULT")                    # 완료 라우팅: teardown → on_result
    assert runner.running is False and runner.thread is None
    assert seen["result"] == "RESULT" and seen["worker"] is worker
    assert seen.get("idle") is True                # 생성 버튼 복원은 뷰별 콜백
    assert not w["btn_cancel"].isEnabled()


def test_controller_fail_cleans_state_loudly(qapp, monkeypatch):
    """실패도 성공과 대칭(RC-07) — 라벨(danger)·로그·진행바 박제 + 모달."""
    view, runner, w, log, _seen = _harness(qapp)
    criticals: "list[str]" = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: criticals.append(a[2]))
    worker = _FakeWorker()
    runner.start(worker, total=3)
    w["progress"].setValue(2)
    runner.fail("디스크 오류")
    assert criticals and "디스크 오류" in criticals[0]
    assert w["lbl_result"].property("level") == "danger"
    assert "디스크 오류" in w["lbl_result"].text()
    assert any("디스크 오류" in line for line in log)
    assert w["progress"].value() == 0
    assert runner.running is False and runner.thread is None


def test_controller_request_cancel_is_cooperative(qapp):
    view, runner, w, log, _seen = _harness(qapp)
    worker = _FakeWorker()
    runner.request_cancel()                        # 실행 전 취소 요청 = 무동작
    assert worker.cancelled is False
    runner.start(worker, total=1)
    try:
        runner.request_cancel()
        assert worker.cancelled is True
        assert not w["btn_cancel"].isEnabled()     # 중복 취소 차단
        assert any("취소 요청" in line for line in log)
    finally:
        runner.teardown()


# ------------------------------------------------ 파일 겨눔 + 시트 확정(T2, RC-22 공용)
def _acquire_harness():
    """DataAcquireController + 콜백 기록 다발 — pick_file 계약만 본다."""
    view = QWidget()
    calls: "dict[str, object]" = {}

    def load_file(path, sheet=None):
        calls["load"] = (path, sheet)
        return [{"a": "1"}]

    ctrl = DataAcquireController(
        view,
        pool_registry=None,
        load_file=load_file,
        restore_pool_item=lambda item: [],
        set_acquired=lambda ds, recs: None,
        after_loaded=lambda label: calls.__setitem__("label", label),
        say=lambda msg: None,
        set_busy=lambda busy: None,
    )
    return view, ctrl, calls


def test_pick_file_confirms_sheet_and_restates_it_in_label(qapp, tmp_path, monkeypatch):
    """다중 시트 — 확정 다이얼로그 경유(행×열 병기) → load_file(sheet=) 관통 →
    after_loaded 라벨에 선택 시트명 재진술."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))  # last_dir INI 오염 방지
    view, ctrl, calls = _acquire_harness()
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(MULTI_SHEET), "")
    )
    seen: "list[list[str]]" = []

    def fake_get_item(parent, title, label, items, *a, **k):
        seen.append(list(items))
        return next(t for t in items if t.startswith("낙찰현황")), True

    monkeypatch.setattr(QInputDialog, "getItem", fake_get_item)
    ctrl.pick_file()
    assert calls["load"] == (str(MULTI_SHEET), "낙찰현황")
    label = calls["label"]
    assert str(MULTI_SHEET) in label and "낙찰현황" in label  # 시트명 재진술
    assert any("행" in t and "열" in t for t in seen[0])       # 행×열 근사 병기


def test_pick_file_skips_sheet_dialog_for_csv_and_single_sheet(qapp, tmp_path, monkeypatch):
    """단일 시트·CSV — getItem 미호출, sheet=None(기본) 로드, 라벨은 경로 그대로."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))  # last_dir INI 오염 방지
    monkeypatch.setattr(
        QInputDialog, "getItem",
        lambda *a, **k: pytest.fail("단일 시트/CSV 엔 시트 다이얼로그 금지"),
    )
    view, ctrl, calls = _acquire_harness()

    csv = tmp_path / "rec.csv"
    csv.write_text("a\n1\n", encoding="utf-8-sig")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(csv), ""))
    ctrl.pick_file()
    assert calls["load"] == (str(csv), None)
    assert calls["label"] == str(csv)              # 시트 표기 없음

    from openpyxl import Workbook

    xlsx = tmp_path / "one.xlsx"
    wb = Workbook()
    wb.active.append(["a"])
    wb.active.append(["1"])
    wb.save(xlsx)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(xlsx), ""))
    ctrl.pick_file()
    assert calls["load"] == (str(xlsx), None)
    assert calls["label"] == str(xlsx)


def test_pick_from_pool_restates_item_sheet_in_label(qapp, monkeypatch):
    """풀 겨눔 라벨 — 항목 참조에 시트가 있으면 파일 겨눔(T2)과 대칭으로 병기하고,
    시트 없는 항목(CSV·나라 등)은 '등록 데이터: 이름' 그대로다(침묵 금지·과잉 표기 금지)."""
    import time

    from PySide6.QtCore import QCoreApplication

    from hwpxfiller.core.dataset_pool import DatasetPoolItem

    view = QWidget()
    calls: "dict[str, object]" = {}
    items = [
        DatasetPoolItem(
            name="6월", kind="excel",
            opts={"path": str(MULTI_SHEET), "sheet": "낙찰현황"},
        ),
        DatasetPoolItem(name="수기", kind="excel", opts={"path": "d.csv"}),
    ]

    class _Reg:
        def list_items(self, status=None):
            return items

    ctrl = DataAcquireController(
        view,
        pool_registry=_Reg(),
        load_file=lambda path, sheet=None: [],
        restore_pool_item=lambda item: [{"a": "1"}],
        set_acquired=lambda ds, recs: None,
        after_loaded=lambda label: calls.__setitem__("label", label),
        say=lambda msg: None,
        set_busy=lambda busy: None,
    )

    def _pick(name):
        monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: (name, True))
        ctrl.pick_from_pool()
        deadline = time.monotonic() + 5.0
        while ctrl.thread is not None and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)
        QCoreApplication.processEvents()
        return calls.pop("label")

    assert _pick("6월") == "등록 데이터: 6월 [시트: 낙찰현황]"   # 시트 병기(파일 겨눔과 대칭)
    assert _pick("수기") == "등록 데이터: 수기"                  # 시트 없는 참조는 이름만


def test_pick_file_sheet_cancel_aborts_whole_targeting(qapp, tmp_path, monkeypatch):
    """시트 확정 취소 — 파일 겨눔 전체 중단(load_file·after_loaded 미호출, 폴백 없음)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))  # last_dir INI 오염 방지
    view, ctrl, calls = _acquire_harness()
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(MULTI_SHEET), "")
    )
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("", False))
    ctrl.pick_file()
    assert "load" not in calls and "label" not in calls  # 부분 겨눔·첫-시트 폴백 금지
