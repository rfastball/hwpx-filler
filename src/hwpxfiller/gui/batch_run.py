"""run/matrix 공용 실행 계층(RC-22) — 배치 실행 뷰들의 축자 사본을 한 곳으로.

단일 실행(:class:`~hwpxfiller.gui.run_view.RunView`)과 매트릭스 실행
(:class:`~hwpxfiller.gui.matrix_view.MatrixRunView`)이 복붙으로 공유하던 것들을 소유한다:

- :class:`BatchRunController` — 생성 워커의 QThread 시작/진행/완료·실패 라우팅/teardown.
  사본 시절 ``_teardown_thread`` 가 이미 의미가 갈라졌던 지점(생성 버튼 복원: run 은 게이트
  재평가, matrix 는 무조건 재활성)은 ``on_idle`` 콜백으로만 남긴다 — 나머지 수명주기는 공용.
- :class:`DataAcquireController` — 데이터 겨눔 3종(파일·풀·나라) 공용. 풀 복원(네트워크
  가능)은 :class:`~hwpxfiller.gui.worker.TaskWorker` 로 비동기(RC-12) — run 사본에만 있던
  비동기화를 matrix 도 여기서 흡수한다(동기 복원의 UI 동결 해소).
- :func:`open_folder` / :func:`ask_open_result_folder` — 결과 폴더 열기·완료 모달.
  완료 모달은 부분 실패를 무언급하지 않는다(RC-30): failed>0 이면 경고형으로 병기.
- :func:`describe_result_error` — 레코드 실패 사유의 원시 errno 를 행동 지향 문구로(RC-30).

이 모듈은 링2(Qt 허용)다 — 판정·문구 결정 자체는 뷰모델(링1)이 소유하고, 여기는 Qt
오케스트레이션(스레드·모달·다이얼로그)만 담는다.
"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from .file_filters import EXCEL_FILTER
from .style import mark
from .view_helpers import ask_sheet_choice, last_dir, save_last_dir
from .worker import TaskWorker


def open_folder(path: str) -> None:
    """OS 파일 탐색기로 폴더 열기 — run/matrix 공용 유틸(RC-22)."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def completion_notice(succeeded: int, failed: int) -> "tuple[str, str]":
    """완료 모달 (level, 문구) — 부분 실패를 '완료' 서사로 덮지 않는다(RC-30).

    level "ok" = 전건 성공(question 모달), "warn" = 부분 실패(경고형 모달 + 실패 병기).
    """
    if failed > 0:
        return (
            "warn",
            f"{succeeded}건 성공 · {failed}건 실패 — 실패 내역은 로그를 확인하세요.\n"
            "결과 폴더를 여시겠습니까?",
        )
    return "ok", f"{succeeded}건 생성 완료.\n결과 폴더를 여시겠습니까?"


def ask_open_result_folder(parent, succeeded: int, failed: int, out_dir: str) -> None:
    """완료 모달 + 결과 폴더 열기(RC-22·RC-30 공용).

    성공 0건이면 열어 볼 산출물이 없다 — 모달 생략(실패는 결과 라벨(danger)·로그·
    실패 모달이 이미 시끄럽게 박제한다). failed>0 이면 경고형 아이콘으로 실패를 병기해
    최전면 모달이 화면 하단 요약보다 낙관적으로 말하지 않게 한다.
    """
    if succeeded <= 0:
        return
    level, text = completion_notice(succeeded, failed)
    if level == "warn":
        reply = QMessageBox.warning(
            parent, "완료(일부 실패)", text, QMessageBox.Yes | QMessageBox.No
        )
    else:
        reply = QMessageBox.question(parent, "완료", text)
    if reply == QMessageBox.Yes:
        open_folder(out_dir)


# 원시 오류 원문 → 행동 지향 안내(RC-30). 원문은 괄호로 보존한다(증거 무손실).
# Windows 에서 os.replace(원자 쓰기 = 이 제품의 실제 저장 경로)는 영문 errno 가 아니라
# 지역화된 "[WinError N] …" 문자열로 도착한다(한국어 Windows) — 숫자 코드와 한국어
# 메시지 양쪽을 겨눠야 대상 플랫폼에서 발화한다(반려 조치).
_HINT_ACCESS = (
    "파일 접근이 거부됐습니다 — 같은 이름의 문서가 다른 프로그램(한글 등)에 열려 있지 않은지, "
    "폴더 쓰기 권한이 있는지 확인하세요."
)
_HINT_IN_USE = (
    "파일이 다른 프로그램(한글 등)에 열려 있습니다 — 해당 문서를 닫은 뒤 다시 시도하세요."
)
_HINT_DISK = "디스크 공간이 부족합니다 — 공간을 비우거나 다른 저장 폴더를 지정하세요."
_HINT_MISSING = "경로를 찾을 수 없습니다 — 저장 폴더가 이동·삭제되지 않았는지 확인하세요."

_ERROR_HINTS: "tuple[tuple[str, str], ...]" = (
    # errno 영문(비-Windows·일부 라이브러리 경유)
    ("Permission denied", _HINT_ACCESS),
    ("No space left", _HINT_DISK),
    ("No such file or directory", _HINT_MISSING),
    # WinError — 코드(로케일 무관)와 한국어 메시지(코드가 잘려도) 양쪽을 겨눈다.
    ("[WinError 5]", _HINT_ACCESS),
    ("액세스가 거부", _HINT_ACCESS),
    ("[WinError 32]", _HINT_IN_USE),
    ("다른 프로세스가 파일을 사용 중", _HINT_IN_USE),
    ("[WinError 112]", _HINT_DISK),
    ("디스크에 공간이 부족", _HINT_DISK),
)


def describe_result_error(error: str) -> str:
    """레코드 실패 사유를 행동 지향 문구로 보강(RC-30) — 원시 errno 관통 해소.

    아는 패턴이 없으면 원문 그대로(조용한 재작성 금지 — 원문이 곧 증거).
    """
    for needle, hint in _ERROR_HINTS:
        if needle in error:
            return f"{hint} (원문: {error})"
    return error


class BatchRunController(QObject):
    """생성 워커 QThread 수명주기의 단일 소유(RC-22) — run/matrix 공유.

    시작(진행바·취소 버튼 셋업 + 시그널 배선)·진행 중계·완료/실패 라우팅·teardown 을
    한 곳에서 한다. 워커는 progress/finished/failed 시그널과 ``cancel()`` 계약만 지키면
    된다(GenerateWorker·MatrixGenerateWorker 공통). 추가 시그널(stage 등)은 뷰가
    ``start()`` 전에 직접 연결한다.

    - ``on_idle()``: teardown 후 생성 버튼 상태 복원 — run 은 게이트(미확인 미입력)
      재평가, matrix 는 단순 재활성. **의미가 다른 유일한 지점**이라 콜백으로 남긴다.
    - ``on_result(result, worker)``: 완료 요약 렌더(뷰별 문구·원장 표면화).
    """

    def __init__(self, view, *, progress, lbl_result, btn_generate, btn_cancel,
                 say, on_idle, on_result):
        super().__init__(view)
        self._view = view
        self._progress = progress
        self._lbl_result = lbl_result
        self._btn_generate = btn_generate
        self._btn_cancel = btn_cancel
        self._say = say
        self._on_idle = on_idle
        self._on_result = on_result
        self.running = False
        self.thread: "QThread | None" = None
        self.worker = None

    def start(self, worker, total: int) -> None:
        """워커를 QThread 로 기동 — 진행/완료/실패를 공용 라우팅에 배선."""
        self.worker = worker
        self.running = True
        self._btn_generate.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._lbl_result.setText("")
        self._progress.setMaximum(total)
        self._progress.setValue(0)
        self.thread = QThread()
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        # 수신자는 바운드 메서드(QObject 슬롯) — 큐드 연결로 UI 스레드에서 처리된다.
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self.finish)
        worker.failed.connect(self.fail)
        self.thread.start()

    def request_cancel(self) -> None:
        """협조적 취소(RC-06) — 진행 중인 레코드까지 마치고 중단한다."""
        if self.worker is not None and self.running:
            self.worker.cancel()
            self._btn_cancel.setEnabled(False)
            self._say("취소 요청 — 진행 중인 레코드까지 마치고 중단합니다.")

    def teardown(self) -> None:
        if self.thread:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
        self.running = False
        self._btn_cancel.setEnabled(False)
        self._on_idle()

    # -------------------------------------------------------------- 라우팅 슬롯
    def _on_progress(self, done: int, _total: int) -> None:
        self._progress.setValue(done)

    def finish(self, result) -> None:
        worker = self.worker
        self.teardown()
        self._on_result(result, worker)

    def fail(self, msg: str) -> None:
        self.teardown()
        # 실패도 성공 경로와 대칭으로 상태를 정리한다(RC-07) — 모달만 남기면 닫는 순간
        # 실패 증거가 증발한다(경보 휘발). 라벨·로그·진행바에 실패를 박제한다.
        self._progress.setValue(0)
        mark(self._lbl_result, "level", "danger")
        self._lbl_result.setText(f"실패 — 생성 중 오류: {msg}")
        self._say(f"[실패] 생성 중 오류: {msg}")
        QMessageBox.critical(self._view, "오류", f"생성 중 오류:\n{msg}")


class DataAcquireController(QObject):
    """데이터 겨눔 3종(파일·풀·나라) 공용 오케스트레이션(RC-22) — run/matrix 공유.

    뷰모델 결합은 콜백 계약으로만 한다(뷰별 뷰모델 표면 차이를 여기서 봉합하지 않는다):

    - ``load_file(path, sheet=None) -> records``: 파일 소스 겨눔(raise = 시끄러운 실패).
      ``sheet`` 는 시트 확정 다이얼로그(T2)가 받아낸 시트명(None=기본 시트).
    - ``restore_pool_item(item) -> records``: 풀 항목 복원 — **UI 스레드 밖**
      (:class:`TaskWorker`)에서 호출된다. UI 상태를 만지면 안 된다.
    - ``set_acquired(datasource, records)``: 나라 애드혹 취득 스냅샷 직접 겨눔.
    - ``after_loaded(label)``: 겨눔 공통 꼬리(라벨·레코드 선택기·게이트 갱신).
    - ``set_busy(bool)``: 복원 진행 중 데이터 버튼 잠금(재진입·경합 방지, RC-12).
    """

    def __init__(self, view, *, pool_registry, load_file, restore_pool_item,
                 set_acquired, after_loaded, say, set_busy,
                 secret_store=None, nara_fetcher=None):
        super().__init__(view)
        self._view = view
        self._pool_registry = pool_registry
        self._load_file = load_file
        self._restore_pool_item = restore_pool_item
        self._set_acquired = set_acquired
        self._after_loaded = after_loaded
        self._say = say
        self._set_busy = set_busy
        self._secret_store = secret_store
        self._nara_fetcher = nara_fetcher
        self.thread: "QThread | None" = None
        self.worker: "TaskWorker | None" = None
        self._pending_label = ""

    # ---------------------------------------------------------------- 파일
    def pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self._view, "데이터 파일 선택", last_dir("data"), EXCEL_FILTER
        )
        if not path:
            return
        save_last_dir("data", path)  # 성공 선택만 기억(T3) — 취소는 직전 값 보존
        # 다중 시트면 사용자 확정(T2) — 취소(None)는 파일 겨눔 **전체 중단**(이전
        # 상태 보존, 조용한 첫-시트 추측 금지). 단일 시트·CSV 는 생략("").
        try:
            sheet = ask_sheet_choice(self._view, path)
        except Exception as exc:  # noqa: BLE001 - 시트 열거 실패(손상 파일)도 시끄럽게
            QMessageBox.critical(self._view, "오류", f"데이터 로드 실패:\n{exc}")
            return
        if sheet is None:
            return
        try:
            records = self._load_file(path, sheet=sheet or None)
        except Exception as exc:  # noqa: BLE001 - 로드 실패는 시끄럽게
            QMessageBox.critical(self._view, "오류", f"데이터 로드 실패:\n{exc}")
            return
        if not records:
            QMessageBox.warning(self._view, "확인", "레코드가 없습니다. 다른 파일을 선택하세요.")
            return
        # 선택 시트명을 라벨에 재진술한다 — 어떤 시트가 겨눠졌는지 침묵하지 않는다.
        self._after_loaded(f"{path} [시트: {sheet}]" if sheet else path)

    # ---------------------------------------------------------------- 데이터 풀
    def pick_from_pool(self) -> None:
        """데이터 풀(활성 항목)에서 참조를 골라 실행 시점에 재읽기(싱크)한다.

        나라 풀 항목의 재취득은 네트워크라 UI 스레드에서 돌리면 이벤트 루프가
        동결된다(RC-12) — 복원은 :class:`TaskWorker`(QThread)로 옮기고, 복원 중엔
        데이터 버튼을 잠가 진행 상태를 시끄럽게 표시한다.
        """
        from ..core.dataset_pool import STATUS_ACTIVE

        items = self._pool_registry.list_items(status=STATUS_ACTIVE)
        if not items:
            QMessageBox.information(
                self._view,
                "등록 데이터",
                "사용 가능한 등록 데이터가 없습니다. 먼저 데이터 관리에서 등록하세요.",
            )
            return
        names = [it.name for it in items]
        name, ok = QInputDialog.getItem(
            self._view, "등록 데이터에서 선택", "데이터셋:", names, 0, False
        )
        if not ok or not name:
            return
        item = next(it for it in items if it.name == name)
        self._say(f"데이터 복원 중(백그라운드): {item.name}")
        self._set_busy(True)
        # 파일 겨눔 라벨(T2)과 대칭 — 항목 참조에 시트가 있으면 병기한다(어떤 시트가
        # 겨눠졌는지 침묵하지 않는다). 시트 없는 항목(CSV·나라·파이프라인)은 이름만.
        sheet = item.opts.get("sheet")
        self._pending_label = (
            f"등록 데이터: {item.name} [시트: {sheet}]"
            if sheet
            else f"등록 데이터: {item.name}"
        )
        self.thread = QThread()
        self.worker = TaskWorker(lambda: self._restore_pool_item(item))
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        # 수신자는 반드시 바운드 메서드(QObject 슬롯) — 큐드 연결로 UI 스레드에서 처리된다.
        self.worker.finished.connect(self._on_pool_loaded)
        self.worker.failed.connect(self._on_pool_load_failed)
        self.thread.start()

    def _teardown(self) -> None:
        if self.thread:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
        self.worker = None
        self._set_busy(False)

    def teardown(self) -> None:
        """복원 스레드 강제 정리(R4) — 페이지 이탈/파괴 전 호출, 진행 중이 아니면 무해.

        이탈 가드(:meth:`can_leave`)가 생성 워커만 정리하고 복원 스레드는 방치하면,
        느린 나라 복원 중 이탈 시 실행 중 QThread 가 파괴돼 'QThread: Destroyed while
        thread is still running' 으로 프로세스가 죽는다(R4 누수). 완료/실패 슬롯이 파괴
        중인 뷰를 만지지 않도록 시그널을 먼저 끊고, 워커 run() 이 반환할 때까지 접는다."""
        if self.worker is not None:
            for sig, slot in (
                (self.worker.finished, self._on_pool_loaded),
                (self.worker.failed, self._on_pool_load_failed),
            ):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self._teardown()

    def _on_pool_loaded(self, records) -> None:
        self._teardown()
        if not records:
            QMessageBox.warning(self._view, "확인", "레코드가 없습니다(취득 0건).")
            return
        self._after_loaded(self._pending_label)

    def _on_pool_load_failed(self, msg: str) -> None:
        # 복원 실패(키 미등록·읽기·API 오류)는 시끄럽게 — 마스킹은 하위 계층이 관통.
        self._teardown()
        self._say(f"[실패] 데이터 복원 실패: {msg}")
        QMessageBox.critical(self._view, "오류", f"데이터 복원 실패:\n{msg}")

    # ---------------------------------------------------------------- 나라장터
    def pick_nara(self) -> None:
        """일회 나라장터 취득(애드혹) — 풀 등록 없이 이번 실행만 겨눈다."""
        from .nara_view import NaraAcquireDialog

        dlg = NaraAcquireDialog(
            self._view, store=self._secret_store, fetcher=self._nara_fetcher
        )
        if dlg.exec() != dlg.Accepted or not dlg.records:
            return
        # 대화상자가 키 없는 스냅샷(AcquiredNaraData)을 이미 만들었다 — 그대로 겨눈다.
        self._set_acquired(dlg.datasource, dlg.records)
        self._after_loaded(dlg.label)
