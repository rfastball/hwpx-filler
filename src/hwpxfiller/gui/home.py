"""홈 — 작업(Job) 레지스트리 목록 + 라우팅(오케스트레이터).

트랙 C UX 결정([[hwpx-filler-scope]]): 앱의 홈은 하나의 태스크(위저드)가 아니라 저장된
**작업 목록**이다. 여기서 새 작업을 만들거나(에디터), 기존 작업을 집행한다(집행 화면).

디자인 패스(핸드오프 §2): 작업 **카드**(템플릿·필드수·최근 집행 메타) + **빈 상태**
(작업 0개 → 새 작업 유도) + 레이아웃/스타일. **네비게이션 시그널 계약은 불변** —
아이템 text 는 계속 작업 이름을 담고(findItems 선택 보존·스모크 계약), 카드는 그 위에
setItemWidget 으로 얹는다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.job import Job, JobRegistry
from .style import BASE_QSS, mark


def _fmt_iso(ts: str) -> str:
    """ISO-8601 → 'YYYY-MM-DD HH:MM' (파싱 실패 시 원문)."""
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


class _JobCard(QWidget):
    """작업 1건의 카드 — 이름 + 메타(템플릿·필드수·파일명) + 최근 집행.

    배경은 투명(리스트 선택 하이라이트가 비치도록) — 이름 텍스트는 카드가 아니라
    아이템이 소유하되 투명 전경으로 감춘다(refresh 참조).
    """

    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(2)

        name_row = QHBoxLayout()
        lbl_name = QLabel(job.name)
        mark(lbl_name, "heading", True)
        name_row.addWidget(lbl_name)
        if job.template_path and not Path(job.template_path).exists():
            # 집행 화면의 템플릿 가드를 홈에서 선고지(비차단).
            lbl_missing = QLabel("템플릿 없음")
            mark(lbl_missing, "level", "warn")
            name_row.addWidget(lbl_missing)
        name_row.addStretch(1)
        root.addLayout(name_row)

        meta = (
            f"템플릿 {Path(job.template_path).name or '—'} · "
            f"필드 {len(job.mapping.mappings)}개 · 파일명 {job.filename_pattern}"
        )
        lbl_meta = QLabel(meta)
        mark(lbl_meta, "muted", True)
        root.addWidget(lbl_meta)

        run_text = (
            f"최근 집행 {_fmt_iso(job.last_run_at)}" if job.last_run_at else "아직 집행 안 함"
        )
        lbl_run = QLabel(run_text)
        mark(lbl_run, "muted", True)
        root.addWidget(lbl_run)


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
        self.setStyleSheet(BASE_QSS)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ---- 헤더 ----
        header = QHBoxLayout()
        title = QLabel("작업 목록")
        mark(title, "heading", True)
        self.lbl_count = QLabel("")
        mark(self.lbl_count, "muted", True)
        self.btn_new = QPushButton("새 작업 만들기")
        mark(self.btn_new, "primary", True)
        self.btn_new.clicked.connect(self.new_job_requested)
        header.addWidget(title)
        header.addWidget(self.lbl_count)
        header.addStretch(1)
        header.addWidget(self.btn_new)
        root.addLayout(header)

        # ---- 목록 / 빈 상태 ----
        self.stack = QStackedWidget()
        self.list = QListWidget()
        self.list.setObjectName("jobList")
        self.list.itemSelectionChanged.connect(self._sync_buttons)
        self.list.itemDoubleClicked.connect(lambda _it: self._emit_for_selected(self.run_job_requested))
        self.stack.addWidget(self.list)          # index 0 = 목록
        self.stack.addWidget(self._build_empty_state())  # index 1 = 빈 상태
        root.addWidget(self.stack, 1)

        # ---- 액션(선택 대상) ----
        actions = QHBoxLayout()
        self.btn_run = QPushButton("집행")
        mark(self.btn_run, "primary", True)
        self.btn_run.clicked.connect(lambda: self._emit_for_selected(self.run_job_requested))
        self.btn_edit = QPushButton("편집")
        self.btn_edit.clicked.connect(lambda: self._emit_for_selected(self.edit_job_requested))
        self.btn_delete = QPushButton("삭제")
        self.btn_delete.clicked.connect(lambda: self._emit_for_selected(self.delete_job_requested))
        actions.addStretch(1)
        actions.addWidget(self.btn_run)
        actions.addWidget(self.btn_edit)
        actions.addWidget(self.btn_delete)
        root.addLayout(actions)

        self.refresh()

    def _build_empty_state(self) -> QWidget:
        """작업 0개일 때 — 첫 작업 만들기 유도(핸드오프 §2)."""
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.addStretch(2)
        lbl = QLabel("저장된 작업이 없습니다")
        mark(lbl, "heading", True)
        lbl.setAlignment(Qt.AlignCenter)
        sub = QLabel("템플릿과 매핑을 묶어 첫 작업을 만드세요.\n데이터·행은 집행할 때 고릅니다.")
        mark(sub, "muted", True)
        sub.setAlignment(Qt.AlignCenter)
        self.btn_empty_new = QPushButton("새 작업 만들기")
        mark(self.btn_empty_new, "primary", True)
        self.btn_empty_new.clicked.connect(self.new_job_requested)  # 헤더 버튼과 동일 시그널
        box.addWidget(lbl)
        box.addWidget(sub)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_empty_new)
        row.addStretch(1)
        box.addLayout(row)
        box.addStretch(3)
        return panel

    # ------------------------------------------------------------- 데이터 바인딩
    def refresh(self) -> None:
        """레지스트리에서 작업 목록을 다시 읽어 카드로 채운다(선택 보존 시도)."""
        prev = self.selected_job_name()
        self.list.clear()
        jobs = self.registry.list_jobs()
        for job in jobs:
            self.list.addItem(job.name)
            item = self.list.item(self.list.count() - 1)
            # 이름은 아이템 text 로 유지(시그널·findItems 계약) — 표시만 카드가 담당.
            item.setForeground(QColor(0, 0, 0, 0))
            card = _JobCard(job)
            item.setSizeHint(card.sizeHint())
            self.list.setItemWidget(item, card)
        self.lbl_count.setText(f"{len(jobs)}건" if jobs else "")
        self.stack.setCurrentIndex(0 if jobs else 1)
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
