"""매핑 프로파일 관리 위젯 — 재사용 매핑 프로파일(공유 베이스)의 관리면(얇은 렌더러).

레이어링: 목록·참조수·삭제·이름변경은 :class:`~hwpxfiller.gui.vocab_workbench_state.
VocabWorkbenchViewModel`(Qt 비의존)이 소유. 이 위젯은 카드로 얹고 액션을 배선하며 저작은
위저드로 위임한다(``edit_base_requested`` → app 이 베이스 시드 위저드를 연다). 클래스·시그널
이름은 코드 심볼로 유지하고, 사용자-가시 문구만 '매핑 프로파일'로 정렬한다(RC-26).

**전파 경고**: 삭제/이름변경 시 참조 작업 수를 시끄럽게 고지한다(ADR J).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .confirm import confirm_destructive
from .style import BASE_QSS, mark
from .view_helpers import build_empty_state, hide_item_text, resync_card_item_heights
from .vocab_workbench_state import VocabBaseRow, VocabWorkbenchViewModel


class _BaseCard(QWidget):
    """매핑 프로파일 1건 카드 — 이름 + 필드수 + 참조 배지 + [편집][이름변경][삭제]."""

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
            elif key == "edit":
                # 프로파일 생성 진입점은 이 화면에 없다(작업 편집기 매핑 단계 전용 — 없던
                # 진입점 발명 금지). 카드 주 액션 [편집]에 보조 등급(UD-22)만 부여해 화면
                # 전역 primary 없이도 카드 안의 주 행동을 시각으로 가른다.
                mark(btn, "emphasis", "card")
            btn.clicked.connect(
                lambda _c=False, k=key, n=row.name: on_action(k, n)
            )
            foot.addWidget(btn)
        root.addLayout(foot)


class VocabWorkbenchPanel(QMainWindow):
    """매핑 프로파일 관리 화면. :class:`VocabWorkbenchViewModel` 을 렌더한다."""

    edit_base_requested = Signal(str)  # 베이스 이름 → app 이 위저드를 베이스 시드로 연다
    base_changed = Signal()            # 삭제/이름변경 후 — 홈/에디터 갱신용

    def __init__(self, base_registry, job_registry=None, parent=None):
        super().__init__(parent)
        self.vm = VocabWorkbenchViewModel(base_registry, job_registry)

        self.setWindowTitle("HWPX Filler — 매핑 프로파일")
        self.resize(680, 520)
        self.setStyleSheet(BASE_QSS)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        title = QLabel("매핑 프로파일")
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
        # 빈 상태 이식(UD-17) — 백지 리스트 + 최하단 잔글씨이던 것을 상태 재진술 안내로
        # 스택 교체한다. 프로파일 생성 경로는 작업 편집기 매핑 단계뿐이라 CTA 는 두지 않고
        # (없던 진입점 발명 금지) 그 경로를 안내한다.
        self.stack = QStackedWidget()
        self.stack.addWidget(self.list)                                # 0 = 목록
        empty = build_empty_state(
            "저장된 매핑 프로파일이 없습니다",
            "작업 편집기의 매핑 단계에서 매핑을 확정한 뒤 '매핑 프로파일로 저장'으로 만드세요. "
            "이후 다른 템플릿에 '매핑 프로파일 적용'으로 이름 교집합 투영해 재사용합니다.",
        )
        self.stack.addWidget(empty)                                    # 1 = 빈 상태
        root.addWidget(self.stack, 1)

        self.vm.subscribe(self._render)
        self._render()

    # ------------------------------------------------------------- 렌더
    def refresh(self) -> None:
        self.vm.refresh()

    def _render(self) -> None:
        self.lbl_count.setText(self.vm.count_label())
        self.list.clear()
        for row in self.vm.rows():
            self.list.addItem(row.name)
            item = self.list.item(self.list.count() - 1)
            hide_item_text(item)  # 이름은 아이템 text, 표시는 카드(UD-33 공용 이디엄)
            card = _BaseCard(row, on_action=self._dispatch)
            item.setSizeHint(card.sizeHint())
            self.list.setItemWidget(item, card)
        self.stack.setCurrentIndex(1 if self.vm.is_empty() else 0)  # 0건 → 빈 상태(UD-17)
        # 카드 액션 버튼 세로 압착 방지(UD-11) — 폴리시·레이아웃 후 높이 재동기.
        self._sync_cards()
        QTimer.singleShot(0, self._sync_cards)

    def _sync_cards(self) -> None:
        """카드 item sizeHint 를 폴리시 후 재계산(UD-11 공용 헬퍼)."""
        resync_card_item_heights(self.list)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt 오버라이드
        super().resizeEvent(event)
        self._sync_cards()

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
        msg = f"매핑 프로파일 '{name}' 을(를) 삭제할까요?"
        if refs:
            msg += (
                f"\n\n이 매핑 프로파일을 참조하는 작업 {len(refs)}개가 있습니다"
                f"({', '.join(refs[:5])}). 작업의 매핑 자체는 그대로지만 계보 연결이 끊깁니다."
            )
        if not confirm_destructive(self, "매핑 프로파일 삭제", msg, "삭제"):
            return
        self.vm.delete(name)
        self.base_changed.emit()

    def _rename(self, name: str) -> None:
        new, ok = QInputDialog.getText(self, "이름변경", "새 이름:", text=name)
        if not ok:
            return
        refs = self.vm.ref_names(name)
        if refs and not confirm_destructive(
            self, "이름변경",
            f"매핑 프로파일 '{name}' 을(를) '{new}' 으(로) 바꿉니다.\n"
            f"참조 작업 {len(refs)}개의 계보도 새 이름으로 갱신됩니다"
            f"({', '.join(refs[:5])}).",
            "이름변경",
        ):
            return
        try:
            self.vm.rename(name, new)
        except ValueError as exc:
            QMessageBox.warning(self, "확인", str(exc))
            return
        self.base_changed.emit()
