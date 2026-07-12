"""어휘 워크벤치 위젯 — 공유 베이스 매핑의 관리면(얇은 렌더러).

레이어링: 목록·참조수·삭제·이름변경은 :class:`~hwpxfiller.gui.vocab_workbench_state.
VocabWorkbenchViewModel`(Qt 비의존)이 소유. 이 위젯은 카드로 얹고 액션을 배선하며 저작은
위저드로 위임한다(``edit_base_requested`` → app 이 베이스 시드 위저드를 연다).

**전파 경고**: 삭제/이름변경 시 참조 작업 수를 시끄럽게 고지한다(ADR J).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .style import BASE_QSS, mark
from .vocab_workbench_state import VocabBaseRow, VocabWorkbenchViewModel


class _BaseCard(QWidget):
    """공유 베이스 1건 카드 — 이름 + 필드수 + 참조 배지 + [편집][이름변경][삭제]."""

    def __init__(self, row: VocabBaseRow, on_action, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(3)

        name_row = QHBoxLayout()
        lbl_name = QLabel(row.name)
        mark(lbl_name, "heading", True)
        name_row.addWidget(lbl_name)
        badge = QLabel(row.ref_badge())
        mark(badge, "level", "warn" if row.ref_count else "muted")
        name_row.addWidget(badge)
        name_row.addStretch(1)
        root.addLayout(name_row)

        lbl_meta = QLabel(f"정준 필드 {row.field_count}개")
        mark(lbl_meta, "muted", True)
        root.addWidget(lbl_meta)

        foot = QHBoxLayout()
        foot.addStretch(1)
        for key, label in (("edit", "편집"), ("rename", "이름변경"), ("delete", "삭제")):
            btn = QPushButton(label)
            if key == "delete":
                mark(btn, "level", "danger")
            btn.clicked.connect(
                lambda _c=False, k=key, n=row.name: on_action(k, n)
            )
            foot.addWidget(btn)
        root.addLayout(foot)


class VocabWorkbenchPanel(QMainWindow):
    """공유 베이스 매핑 워크벤치. :class:`VocabWorkbenchViewModel` 을 렌더한다."""

    edit_base_requested = Signal(str)  # 베이스 이름 → app 이 위저드를 베이스 시드로 연다
    base_changed = Signal()            # 삭제/이름변경 후 — 홈/에디터 갱신용

    def __init__(self, base_registry, job_registry=None, parent=None):
        super().__init__(parent)
        self.vm = VocabWorkbenchViewModel(base_registry, job_registry)

        self.setWindowTitle("HWPX Filler — 어휘 워크벤치")
        self.resize(680, 520)
        self.setStyleSheet(BASE_QSS)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        title = QLabel("공유 베이스 매핑")
        mark(title, "heading", True)
        self.lbl_count = QLabel("")
        mark(self.lbl_count, "muted", True)
        header.addWidget(title)
        header.addWidget(self.lbl_count)
        header.addStretch(1)
        root.addLayout(header)

        self.list = QListWidget()
        self.list.setObjectName("jobList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.list, 1)

        self.lbl_empty = QLabel(
            "저장된 공유 베이스가 없습니다 — 작업 편집기의 매핑 단계에서 매핑을 확정한 뒤 "
            "'공유 베이스로 저장'으로 만드세요. 이후 다른 템플릿에 '공유 베이스 적용'으로 "
            "이름 교집합 투영해 재사용합니다."
        )
        self.lbl_empty.setWordWrap(True)
        mark(self.lbl_empty, "muted", True)
        root.addWidget(self.lbl_empty)

        self.vm.subscribe(self._render)
        self._render()

    # ------------------------------------------------------------- 렌더
    def refresh(self) -> None:
        self.vm.refresh()

    def _render(self) -> None:
        self.lbl_count.setText(self.vm.count_label())
        self.lbl_empty.setVisible(self.vm.is_empty())
        self.list.clear()
        for row in self.vm.rows():
            self.list.addItem(row.name)
            item = self.list.item(self.list.count() - 1)
            item.setForeground(QColor(0, 0, 0, 0))
            card = _BaseCard(row, on_action=self._dispatch)
            item.setSizeHint(card.sizeHint())
            self.list.setItemWidget(item, card)

    # ---------------------------------------------------- 액션 디스패치
    def _dispatch(self, key: str, name: str) -> None:
        if key == "edit":
            self.edit_base_requested.emit(name)
        elif key == "rename":
            self._rename(name)
        elif key == "delete":
            self._delete(name)

    def _delete(self, name: str) -> None:
        refs = self.vm.ref_names(name)
        msg = f"공유 베이스 '{name}' 을(를) 삭제할까요?"
        if refs:
            msg += (
                f"\n\n이 베이스를 참조하는 작업 {len(refs)}개가 있습니다"
                f"({', '.join(refs[:5])}). 작업의 매핑 자체는 그대로지만 계보 연결이 끊깁니다."
            )
        if QMessageBox.question(self, "삭제", msg) != QMessageBox.Yes:
            return
        self.vm.delete(name)
        self.base_changed.emit()

    def _rename(self, name: str) -> None:
        new, ok = QInputDialog.getText(self, "이름변경", "새 이름:", text=name)
        if not ok:
            return
        refs = self.vm.ref_names(name)
        if refs and QMessageBox.question(
            self, "이름변경",
            f"참조 작업 {len(refs)}개의 계보도 새 이름으로 갱신됩니다"
            f"({', '.join(refs[:5])}). 계속할까요?",
        ) != QMessageBox.Yes:
            return
        try:
            self.vm.rename(name, new)
        except ValueError as exc:
            QMessageBox.warning(self, "확인", str(exc))
            return
        self.base_changed.emit()
