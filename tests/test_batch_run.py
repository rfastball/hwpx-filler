"""run/matrix 공용 실행 계층(RC-22) — 완료 문구(RC-30)·오류 번역·QThread 수명주기 계약.

사본 시절 한쪽만 고쳐지던 것들(완료 모달·teardown·실패 라우팅)이 이제 한 곳에 있다 —
그 한 곳의 계약을 직접 못박는다. 뷰 관통은 test_gui_smoke/test_matrix_view 가 검증한다.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QWidget,
)

from hwpxfiller.gui.batch_run import (  # noqa: E402
    BatchRunController,
    completion_notice,
    describe_result_error,
)


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
