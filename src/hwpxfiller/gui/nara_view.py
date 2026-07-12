"""나라장터 취득 대화상자 — 소스 선택(위저드 DataPage)에서 열리는 키 등록 + 취득 표면.

얇은 렌더러/오케스트레이터다: 키 등록/삭제/연결시험·기간검증·취득·redaction 은 전부
:class:`~hwpxfiller.gui.nara_state.NaraAcquireViewModel`(Qt 비의존, 링1)이 소유한다.
위젯은 입력 수집·라벨 갱신·수용(accept) 게이트만 담당하고 ``DataSource``·``SecretStore`` 를
직접 만지지 않는다.

수용 시 :attr:`records`·:attr:`fields`·:attr:`datasource`(키 없는 스냅샷)·:attr:`label` 을
노출해 DataPage 가 위저드 세션에 심는다 — 전부 뷰모델의 ``last_result``(원자 스냅샷,
성공 or None)에서 파생된 읽기 전용 프로퍼티라 실패·편집 시 부분 잔존이 없다.
**키는 이 대화상자를 통과하지 않는다** — 입력창 값은 즉시 SecretStore 로 넘어가고(등록),
취득은 저장된 키로만 이뤄진다.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QDateTime, QThread
from PySide6.QtWidgets import (
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .nara_state import DT_FMT, NaraAcquireViewModel
from .style import mark
from .worker import TaskWorker

# QDateTimeEdit 표시/파싱 포맷 — VM 의 DT_FMT(YYYYMMDDHHMM)와 1:1(strptime 호환).
_QT_DT_FMT = "yyyyMMddHHmm"


class NaraAcquireDialog(QDialog):
    """나라장터 키 등록 + 입찰공고 취득 대화상자.

    ``store``/``fetcher`` 는 뷰모델로 그대로 주입된다(테스트는 MemorySecretStore + 가짜
    fetcher 로 실 저장소·네트워크 무접촉). 취득 성공 전에는 확인 버튼이 비활성이다.
    """

    def __init__(self, parent=None, *, store=None, fetcher=None):
        super().__init__(parent)
        self.vm = NaraAcquireViewModel(store, fetcher=fetcher)
        # 네트워크(취득·연결시험)는 QThread 로(RC-12) — UI 스레드 동기 urlopen 금지.
        # _fetch_seq 는 '현재 유효한 요청' 표식: 중지·편집·닫기가 올리면 이미 떠난
        # 요청의 결과는 도착해도 폐기된다(스테일 커밋 금지 — RC-13 게이트 보존).
        self._busy = False
        self._fetch_seq = 0
        self._retry_available = False
        # 진행 중 태스크: {worker: (thread, seq, on_done)} — sender 로 짝을 찾는다.
        self._tasks: "dict[object, tuple[QThread, int, Callable[[object], None]]]" = {}

        self.setWindowTitle("나라장터에서 데이터 가져오기")
        self.resize(560, 460)
        root = QVBoxLayout(self)

        root.addWidget(self._build_key_group())
        root.addWidget(self._build_search_group())

        self.lbl_result = QLabel("")
        self.lbl_result.setWordWrap(True)
        root.addWidget(self.lbl_result)
        root.addStretch(1)

        # 확인(취득 성공 후에만) / 취소.
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self._ok_button().setEnabled(False)
        root.addWidget(self.buttons)

        # 취득 성공 뒤 기간·건수 편집 → 스냅샷과 입력이 어긋남 — OK 게이트 무효화(RC-13).
        # (위젯 생성·초기값 설정이 끝난 뒤에 배선 — 초기화가 편집으로 오인되지 않게)
        self.dt_bgn.dateTimeChanged.connect(self._on_query_edited)
        self.dt_end.dateTimeChanged.connect(self._on_query_edited)
        self.spin_rows.valueChanged.connect(self._on_query_edited)
        self.spin_page.valueChanged.connect(self._on_query_edited)

        self._sync_key_ui()

    # ------------------------------------------------ 취득 산출물(원자 스냅샷 파생)
    # 전부 vm.last_result(성공 or None)에서 파생 — 실패·편집 시 4속성 부분 잔존 불가(RC-24).
    @property
    def records(self) -> "list[dict[str, str]]":
        res = self.vm.last_result
        return res.records if res is not None else []

    @property
    def fields(self) -> "list[str]":
        res = self.vm.last_result
        return res.fields if res is not None else []

    @property
    def datasource(self):
        res = self.vm.last_result
        return res.as_datasource() if res is not None else None

    @property
    def label(self) -> str:
        res = self.vm.last_result
        return res.source_label() if res is not None else ""

    def query_options(self) -> "dict[str, object]":
        """수용된 취득의 쿼리 스냅샷 — **취득 시점 캡처값**(위젯 현재값 재독 금지, RC-13).

        풀 등록이 이걸 저장해야 '취득으로 검증된 기간'과 '저장되는 기간'이 항상 같다.
        수용 가능한 취득이 없으면 시끄럽게 실패한다(조용한 위젯값 폴백 금지).
        """
        res = self.vm.last_result
        if res is None:
            raise RuntimeError("수용 가능한 취득 결과가 없습니다 — 먼저 가져오기를 실행하세요.")
        return {
            "bgn_dt": res.bgn_dt, "end_dt": res.end_dt,
            "num_rows": res.num_rows, "page_no": res.page_no,
        }

    # ------------------------------------------------------------- 키 등록 그룹
    def _build_key_group(self) -> QGroupBox:
        box = QGroupBox("서비스키")
        v = QVBoxLayout(box)

        status_row = QHBoxLayout()
        self.lbl_status = QLabel("")
        status_row.addWidget(QLabel("상태:"))
        status_row.addWidget(self.lbl_status)
        status_row.addStretch(1)
        v.addLayout(status_row)

        key_row = QHBoxLayout()
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.Password)  # 어깨너머 노출 방지
        self.ed_key.setPlaceholderText("data.go.kr 에서 발급받은 ServiceKey")
        self.btn_save = QPushButton("등록")
        self.btn_save.clicked.connect(self._on_save_key)
        key_row.addWidget(self.ed_key, 1)
        key_row.addWidget(self.btn_save)
        v.addLayout(key_row)

        action_row = QHBoxLayout()
        self.btn_delete = QPushButton("삭제")
        self.btn_delete.clicked.connect(self._on_delete_key)
        self.btn_test = QPushButton("연결 시험")
        self.btn_test.clicked.connect(self._on_test)
        self.lbl_test = QLabel("")
        self.lbl_test.setWordWrap(True)
        action_row.addWidget(self.btn_delete)
        action_row.addWidget(self.btn_test)
        action_row.addWidget(self.lbl_test, 1)
        v.addLayout(action_row)
        return box

    # ------------------------------------------------------------- 취득 그룹
    def _build_search_group(self) -> QGroupBox:
        box = QGroupBox("입찰공고 취득 (기간 최대 1개월)")
        grid = QGridLayout(box)

        now = QDateTime.currentDateTime()
        self.dt_bgn = QDateTimeEdit(now.addDays(-7))
        self.dt_end = QDateTimeEdit(now)
        for dte in (self.dt_bgn, self.dt_end):
            dte.setDisplayFormat(_QT_DT_FMT)
            dte.setCalendarPopup(True)
        grid.addWidget(QLabel("시작 일시"), 0, 0)
        grid.addWidget(self.dt_bgn, 0, 1)
        grid.addWidget(QLabel("종료 일시"), 1, 0)
        grid.addWidget(self.dt_end, 1, 1)

        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 999)
        self.spin_rows.setValue(100)
        self.spin_page = QSpinBox()
        self.spin_page.setRange(1, 9999)
        self.spin_page.setValue(1)
        grid.addWidget(QLabel("페이지당 건수"), 2, 0)
        grid.addWidget(self.spin_rows, 2, 1)
        grid.addWidget(QLabel("페이지 번호"), 3, 0)
        grid.addWidget(self.spin_page, 3, 1)

        btn_row = QHBoxLayout()
        self.btn_acquire = QPushButton("가져오기")
        mark(self.btn_acquire, "primary", True)
        self.btn_acquire.clicked.connect(self._on_acquire)
        self.btn_retry = QPushButton("다시 시도")
        self.btn_retry.clicked.connect(self._on_acquire)
        self.btn_retry.setEnabled(False)
        # 진행 중 요청 중지(RC-12) — 도착할 결과를 폐기하고 UI 를 즉시 복원한다.
        self.btn_stop = QPushButton("중지")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop_fetch)
        btn_row.addWidget(self.btn_acquire)
        btn_row.addWidget(self.btn_retry)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch(1)
        grid.addLayout(btn_row, 4, 0, 1, 2)
        return box

    # ------------------------------------------------------------------ helpers
    def _ok_button(self) -> QPushButton:
        return self.buttons.button(QDialogButtonBox.Ok)

    def _sync_key_ui(self) -> None:
        """등록 상태를 라벨·버튼 문구에 반영(등록됨→'교체', 미등록→'등록')."""
        registered = self.vm.is_registered()
        self.lbl_status.setText(self.vm.status_label())
        mark(self.lbl_status, "level", "ok" if registered else "warn")
        self.btn_save.setText("교체" if registered else "등록")
        self.btn_delete.setEnabled(registered)
        self.btn_test.setEnabled(registered)

    # ------------------------------------------------------------------ 키 액션
    def _on_save_key(self) -> None:
        try:
            self.vm.save_key(self.ed_key.text())
        except ValueError as exc:
            QMessageBox.warning(self, "확인", str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - 저장소 미지원 등은 시끄럽게
            QMessageBox.critical(self, "오류", f"키 저장 실패:\n{exc}")
            return
        self.ed_key.clear()  # 입력창에 키를 남기지 않는다(저장소만이 값을 안다)
        self.lbl_test.setText("")
        self._sync_key_ui()

    def _on_delete_key(self) -> None:
        if QMessageBox.question(
            self, "삭제", "저장된 서비스키를 삭제할까요?"
        ) != QMessageBox.Yes:
            return
        try:
            self.vm.delete_key()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"키 삭제 실패:\n{exc}")
            return
        self.lbl_test.setText("")
        self._sync_key_ui()

    def _on_test(self) -> None:
        """연결 시험 — 네트워크는 QThread 로(RC-12), 결과는 UI 스레드에서 반영."""
        self._fetch_seq += 1
        self._set_busy(True)
        mark(self.lbl_test, "level", "")
        self.lbl_test.setText("연결 시험 중…")
        self._spawn_task(self.vm.test_connection, self._apply_test_result)

    def _apply_test_result(self, res) -> None:
        self._set_busy(False)
        mark(self.lbl_test, "level", "ok" if res.ok else "danger")
        self.lbl_test.setText(res.message)

    # ------------------------------------------------------------------ 취득
    def _bgn_text(self) -> str:
        return self.dt_bgn.dateTime().toString(_QT_DT_FMT)

    def _end_text(self) -> str:
        return self.dt_end.dateTime().toString(_QT_DT_FMT)

    def _on_acquire(self) -> None:
        """취득 시작 — 입력은 클릭 시점 캡처, 네트워크는 QThread(RC-12).

        진행 중엔 입력·액션이 잠기고(진행 표시), 중지·편집·닫기는 도착할 결과를
        폐기시킨다. 결과 커밋(:meth:`~hwpxfiller.gui.nara_state.NaraAcquireViewModel.
        commit`)은 UI 스레드에서만 일어난다 — 스냅샷 경합 없음.
        """
        bgn, end = self._bgn_text(), self._end_text()
        num_rows, page_no = self.spin_rows.value(), self.spin_page.value()
        self._fetch_seq += 1
        self._retry_available = True
        self._set_busy(True)
        mark(self.lbl_result, "level", "")
        self.lbl_result.setText("가져오는 중… (중지 가능)")
        self._spawn_task(
            lambda: self.vm.acquire_result(bgn, end, num_rows=num_rows, page_no=page_no),
            self._apply_acquire_result,
        )

    def _apply_acquire_result(self, res) -> None:
        self.vm.commit(res)  # 커밋은 UI 스레드에서만 — 편집/중지와 경합하지 않는다
        self._set_busy(False)
        mark(self.lbl_result, "level", "ok" if res.acceptable else "danger")
        self.lbl_result.setText(res.summary())
        # 수용성(성공+1건 이상)은 뷰모델 스냅샷이 판정 — 실패/0건이면 last_result 가
        # 원자로 None 이 돼 records/fields/datasource/label 도 함께 비워진다(RC-24).
        self._ok_button().setEnabled(res.acceptable)

    def _on_stop_fetch(self) -> None:
        """진행 중 요청 중지 — 도착할 결과를 폐기(seq 무효화)하고 UI 를 복원한다.

        저수준 소켓 중단은 urlopen 한계로 불가하지만 사용자 관점의 취소는 즉시
        보장된다: 결과는 커밋되지 않고, 수용 게이트는 마지막 유효 스냅샷 기준으로
        복원된다(조용한 스테일 수용 금지).
        """
        if not self._busy:
            return
        self._fetch_seq += 1
        self._set_busy(False)
        mark(self.lbl_result, "level", "warn")
        self.lbl_result.setText("요청을 중지했습니다 — 도착하는 결과는 무시됩니다.")

    def _on_query_edited(self, *_args) -> None:
        """취득 뒤 기간·건수 편집 — 스냅샷 폐기 + OK 잠금 + 재취득 안내(RC-13).

        편집된 입력은 검증되지 않았다: 그대로 수용·등록되면 '취득 성공에서만 수용'
        불변식이 깨진다. 진행 중 요청이 있으면 그 결과도 폐기한다(편집 후 도착한
        스테일 결과가 게이트를 여는 경합 차단). 스냅샷이 없으면(취득 전/이미 실패)
        게이트는 이미 잠겨 있다.
        """
        self._fetch_seq += 1
        if self.vm.last_result is None:
            return
        self.vm.invalidate()
        self._ok_button().setEnabled(False)
        mark(self.lbl_result, "level", "warn")
        self.lbl_result.setText("입력이 변경됨 — 다시 가져오세요.")

    # -------------------------------------------------------- 백그라운드 태스크(RC-12)
    def _set_busy(self, busy: bool) -> None:
        """요청 진행 중 UI 상태 — 입력·액션 잠금 + 중지 허용, 완료 시 게이트 복원."""
        self._busy = busy
        for w in (
            self.btn_acquire, self.btn_retry, self.btn_save, self.btn_delete,
            self.btn_test, self.dt_bgn, self.dt_end, self.spin_rows, self.spin_page,
        ):
            w.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        if busy:
            self._ok_button().setEnabled(False)
        else:
            self._sync_key_ui()  # 삭제/시험 버튼은 키 등록 상태를 따른다
            self.btn_retry.setEnabled(self._retry_available)
            self._ok_button().setEnabled(self.vm.last_result is not None)

    def _spawn_task(self, fn, on_done) -> None:
        """블로킹 호출 1개를 :class:`TaskWorker`+QThread 로 — 생성 워커와 같은 패턴.

        완료/실패 슬롯은 이 대화상자의 바운드 메서드(큐드 연결)라 UI 스레드에서
        돈다. 등록 시점의 ``_fetch_seq`` 가 도착 시점과 다르면 결과는 폐기된다.
        """
        thread = QThread()
        worker = TaskWorker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_task_result)
        worker.failed.connect(self._on_task_error)
        self._tasks[worker] = (thread, self._fetch_seq, on_done)
        thread.start()

    def _pop_task(self) -> "tuple[int, Callable[[object], None]] | None":
        worker = self.sender()
        entry = self._tasks.pop(worker, None)
        if entry is None:
            return None
        thread, seq, on_done = entry
        thread.quit()
        thread.wait()
        return seq, on_done

    def _on_task_result(self, result) -> None:
        entry = self._pop_task()
        if entry is None:
            return
        seq, on_done = entry
        if seq != self._fetch_seq:
            return  # 중지/편집/닫기로 무효화된 요청 — 결과 폐기(스테일 커밋 금지)
        on_done(result)

    def _on_task_error(self, msg: str) -> None:
        # 뷰모델이 알려진 실패를 결과 객체로 돌려주므로 여기는 예기치 못한 예외 전용 —
        # 그래도 조용히 삼키지 않는다(마스킹은 하위 계층이 관통).
        entry = self._pop_task()
        if entry is None:
            return
        seq, _on_done = entry
        if seq != self._fetch_seq:
            return
        self._set_busy(False)
        mark(self.lbl_result, "level", "danger")
        self.lbl_result.setText(f"요청 실패: {msg}")

    def reject(self) -> None:
        # 진행 중 닫기 — 도착할 결과를 폐기시키고 즉시 닫는다(프리즈 없음).
        self._fetch_seq += 1
        super().reject()

    def datetime_range(self) -> "tuple[str, str]":
        """현재 입력된 (시작, 종료) 일시 문자열(YYYYMMDDHHMM) — 검증·표시용."""
        return self._bgn_text(), self._end_text()


# DT_FMT 재노출(테스트·호출측이 포맷 상수를 한 곳에서 참조).
__all__ = ["NaraAcquireDialog", "DT_FMT"]
