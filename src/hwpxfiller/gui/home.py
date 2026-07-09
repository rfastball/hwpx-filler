"""홈 — 작업(Job) 레지스트리 목록 + 라우팅(오케스트레이터).

트랙 C UX 결정([[hwpx-filler-scope]]): 앱의 홈은 하나의 태스크(위저드)가 아니라 저장된
**작업 목록**이다. 여기서 새 작업을 만들거나(에디터), 기존 작업을 집행한다(집행 화면).

**스캐폴드 범위(의도적으로 얇음):** 목록 바인딩 + 네비게이션 시그널 계약 + 모델 부착
지점까지만. 작업 카드 위젯·빈 상태·레이아웃·스타일은 후속 디자인 패스의 몫이다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.job import JobRegistry


class JobListHome(QMainWindow):
    """작업 목록 홈. :class:`JobRegistry` 를 읽어 표시하고, 액션을 시그널로 방출한다.

    시그널 계약(app.py 가 배선): 새 작업/편집 → 에디터, 집행 → 집행 화면. 이 창은 라우팅만
    하고 자식 창의 수명은 배선 측이 소유한다.
    """

    new_job_requested = Signal()
    edit_job_requested = Signal(str)   # 작업 이름
    run_job_requested = Signal(str)    # 작업 이름
    delete_job_requested = Signal(str)  # 작업 이름

    def __init__(self, registry: JobRegistry, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.setWindowTitle("HWPX Filler — 작업")
        self.resize(720, 520)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addWidget(QLabel("작업 목록"))
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._sync_buttons)
        self.list.itemDoubleClicked.connect(lambda _it: self._emit_for_selected(self.run_job_requested))
        root.addWidget(self.list, 1)

        actions = QHBoxLayout()
        self.btn_new = QPushButton("새 작업 만들기")
        self.btn_new.clicked.connect(self.new_job_requested)
        self.btn_run = QPushButton("집행")
        self.btn_run.clicked.connect(lambda: self._emit_for_selected(self.run_job_requested))
        self.btn_edit = QPushButton("편집")
        self.btn_edit.clicked.connect(lambda: self._emit_for_selected(self.edit_job_requested))
        self.btn_delete = QPushButton("삭제")
        self.btn_delete.clicked.connect(lambda: self._emit_for_selected(self.delete_job_requested))
        actions.addWidget(self.btn_new)
        actions.addStretch(1)
        actions.addWidget(self.btn_run)
        actions.addWidget(self.btn_edit)
        actions.addWidget(self.btn_delete)
        root.addLayout(actions)

        self.refresh()

    # ------------------------------------------------------------- 데이터 바인딩
    def refresh(self) -> None:
        """레지스트리에서 작업 목록을 다시 읽어 리스트를 채운다(선택 보존 시도)."""
        prev = self.selected_job_name()
        self.list.clear()
        for name in self.registry.names():
            self.list.addItem(name)
        if prev is not None:
            items = self.list.findItems(prev, Qt.MatchExactly)
            if items:
                self.list.setCurrentItem(items[0])
        self._sync_buttons()

    def selected_job_name(self) -> "str | None":
        it = self.list.currentItem()
        return it.text() if it is not None else None

    # ------------------------------------------------------------- 내부
    def _emit_for_selected(self, signal) -> None:
        name = self.selected_job_name()
        if name is not None:
            signal.emit(name)

    def _sync_buttons(self) -> None:
        has = self.selected_job_name() is not None
        self.btn_run.setEnabled(has)
        self.btn_edit.setEnabled(has)
        self.btn_delete.setEnabled(has)
