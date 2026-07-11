"""레코드 선택 위젯 — SelectionModel 을 체크 리스트로 렌더한다.

각 항목 라벨은 **그 레코드가 만들 출력 파일명 미리보기**다(현재 패턴·연번 반영) — 선택과
파일명을 한눈에 잇는다. 전체 선택/해제 버튼은 VBA ``modUIUtils`` 역할.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..naming import make_output_filename
from .selection_state import SelectionModel


class RecordSelector(QWidget):
    """생성 대상 레코드를 고르는 체크 리스트 + 전체 선택/해제."""

    selectionChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = SelectionModel(0)
        self._records: "list[dict]" = []
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        self.lbl_count = QLabel("선택 0/0")
        btn_all = QPushButton("전체 선택")
        btn_all.clicked.connect(self._on_all)
        btn_none = QPushButton("전체 해제")
        btn_none.clicked.connect(self._on_none)
        top.addWidget(self.lbl_count)
        top.addStretch(1)
        top.addWidget(btn_all)
        top.addWidget(btn_none)
        layout.addLayout(top)

        self.list = QListWidget()
        self.list.setObjectName("recordList")
        # 체크 상태가 유일한 선택 표현 — 행 하이라이트(SingleSelection)와의 이중 상태 모호 제거.
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        # 체크 토글마다 current 아이템으로 자동 스크롤되며 뷰가 날뛰는 것 방지.
        self.list.setAutoScroll(False)
        self.list.setUniformItemSizes(True)
        self.list.setMinimumHeight(96)  # 창을 줄여도 목록이 스크롤될 최소 높이 확보
        self.list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list, 1)

    def model(self) -> SelectionModel:
        return self._model

    def selected_indices(self) -> "list[int]":
        return self._model.selected_indices()

    def set_records(self, records: "list[dict]", pattern: str):
        """레코드 목록으로 리스트를 (재)구성. 라벨은 각 레코드의 출력 파일명 미리보기.

        선택 상태를 전체 선택으로 초기화한다(페이지 진입/데이터 변경 시).
        """
        self._records = list(records)
        self._model = SelectionModel(len(records))
        self._updating = True
        try:
            self.list.clear()
            for i, rec in enumerate(records, 1):
                item = QListWidgetItem(self._label_for(i, rec, pattern))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.list.addItem(item)
        finally:
            self._updating = False
        self._sync_count()
        self.selectionChanged.emit()

    def relabel(self, records: "list[dict]", pattern: str):
        """항목 라벨(파일명 미리보기)만 갱신 — 선택 상태는 보존.

        레코드 수가 바뀌었으면 전체 재구성(set_records)으로 위임한다.
        """
        if len(records) != self.list.count():
            self.set_records(records, pattern)
            return
        self._updating = True
        try:
            for i, rec in enumerate(records, 1):
                self.list.item(i - 1).setText(self._label_for(i, rec, pattern))
        finally:
            self._updating = False

    @staticmethod
    def _label_for(seq: int, rec: "dict", pattern: str) -> str:
        return f"{seq}. {make_output_filename(pattern, rec, seq=seq)}"

    # ------------------------------------------------------------------ 핸들러
    def _on_item_changed(self, item: QListWidgetItem):
        if self._updating:
            return
        ri = self.list.row(item)
        self._model.toggle(ri, item.checkState() == Qt.Checked)
        self._sync_count()
        self.selectionChanged.emit()

    def _on_all(self):
        self._model.set_all()
        self._apply_model_to_view()

    def _on_none(self):
        self._model.set_none()
        self._apply_model_to_view()

    def _apply_model_to_view(self):
        self._updating = True
        try:
            for i in range(self.list.count()):
                self.list.item(i).setCheckState(
                    Qt.Checked if self._model.is_selected(i) else Qt.Unchecked
                )
        finally:
            self._updating = False
        self._sync_count()
        self.selectionChanged.emit()

    def _sync_count(self):
        self.lbl_count.setText(f"선택 {self._model.selected_count()}/{len(self._model)}")
