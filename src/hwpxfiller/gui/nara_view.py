"""나라장터 취득 대화상자 — 소스 선택(위저드 DataPage)에서 열리는 키 등록 + 취득 표면.

얇은 렌더러/오케스트레이터다: 키 등록/삭제/연결시험·기간검증·취득·redaction 은 전부
:class:`~hwpxfiller.gui.nara_state.NaraAcquireViewModel`(Qt 비의존, 링1)이 소유한다.
위젯은 입력 수집·라벨 갱신·수용(accept) 게이트만 담당하고 ``DataSource``·``SecretStore`` 를
직접 만지지 않는다.

수용 시 :attr:`records`·:attr:`fields`·:attr:`datasource`(키 없는 스냅샷)·:attr:`label` 을
노출해 DataPage 가 위저드 세션에 심는다. **키는 이 대화상자를 통과하지 않는다** —
입력창 값은 즉시 SecretStore 로 넘어가고(등록), 취득은 저장된 키로만 이뤄진다.
"""

from __future__ import annotations

from PySide6.QtCore import QDateTime
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
        # 수용 시 DataPage 가 읽는 취득 산출물(키 없음).
        self.records: "list[dict[str, str]]" = []
        self.fields: "list[str]" = []
        self.datasource = None
        self.label: str = ""

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

        self._sync_key_ui()

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
        btn_row.addWidget(self.btn_acquire)
        btn_row.addWidget(self.btn_retry)
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
        res = self.vm.test_connection()
        mark(self.lbl_test, "level", "ok" if res.ok else "danger")
        self.lbl_test.setText(res.message)

    # ------------------------------------------------------------------ 취득
    def _bgn_text(self) -> str:
        return self.dt_bgn.dateTime().toString(_QT_DT_FMT)

    def _end_text(self) -> str:
        return self.dt_end.dateTime().toString(_QT_DT_FMT)

    def _on_acquire(self) -> None:
        res = self.vm.acquire(
            self._bgn_text(), self._end_text(),
            num_rows=self.spin_rows.value(), page_no=self.spin_page.value(),
        )
        self.btn_retry.setEnabled(True)
        mark(self.lbl_result, "level", "ok" if (res.ok and res.records) else "danger")
        self.lbl_result.setText(res.summary())
        if res.ok and res.records:
            self.records = res.records
            self.fields = res.fields
            self.datasource = res.as_datasource()  # 키 없는 스냅샷
            self.label = f"나라장터 · {self._bgn_text()}~{self._end_text()} · {res.count}건"
            self._ok_button().setEnabled(True)
        else:
            # 실패/0건은 수용 불가(빈 데이터로 매핑 진행 금지) — 확인 버튼 잠금 유지.
            self.records = []
            self._ok_button().setEnabled(False)

    def datetime_range(self) -> "tuple[str, str]":
        """현재 입력된 (시작, 종료) 일시 문자열(YYYYMMDDHHMM) — 검증·표시용."""
        return self._bgn_text(), self._end_text()


# DT_FMT 재노출(테스트·호출측이 포맷 상수를 한 곳에서 참조).
__all__ = ["NaraAcquireDialog", "DT_FMT"]
