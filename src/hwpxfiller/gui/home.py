"""홈 — 투트랙 허브 대시보드 + 라우팅(오케스트레이터).

트랙 이원성([[hwpx-filler-scope]], DECISIONS §트랙 이원성): 홈은 단순 목록이 아니라 **두 트랙의
허브 대시보드**다 — 좌: HWPX 문서 생성(Job-앵커·재사용 자산), 우: 즉시 기안(txt, 경량·
render→copy). 상단 KPI는 **실재 데이터만**(작업 수·최근 실행·템플릿 없는 작업·기안 템플릿 수) —
가짜 지표 없음(핸드오프 관통 경고: 없던 기능 발명 금지).

레이어링: 위젯은 얇은 렌더러 — 목록 성형·KPI·선택은 :class:`~hwpxfiller.gui.home_state.HomeViewModel`
(Qt 비의존, 링1)이 소유. **네비게이션 시그널 계약 불변** — HWPX(new/edit/run/delete_job_requested,
아이템 text=작업명)에 txt(new_txt/open_txt_requested)를 더한다. 작업 목록은 계속 QListWidget
(self.list)에 카드로 얹는다(findItems·스모크 계약 보존).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.job import JobRegistry
from ..core.template_status import CompileState
from .home_state import HomeViewModel, JobRow, TxtRow
from .style import BASE_QSS, mark


def _badge_fb(row: JobRow) -> str:
    """카드 컴파일 배지의 pill 심각도(style.py 의 fb 셀렉터 재사용).

    ready=초록·partial=호박·raw=보라(할 일)·부재/오류=빨강(주의). 어휘 자체는 배지 문구가
    나르고, 색은 한눈 식별 보조다.
    """
    if row.compile_state == CompileState.RAW:
        return "ack"
    if row.compile_state == CompileState.PARTIAL:
        return "blank"
    if row.compile_state in (CompileState.COMPILED, CompileState.FILLED):
        return "fill"
    return "missing"  # compile_state None + 배지 有 = 부재/오류(시끄러운 주의)


class _JobCard(QWidget):
    """HWPX 작업 카드 — 이름 + 상태 배지 + 메타 + 최근 실행 + 카드별 액션(실행/편집/삭제).

    성형된 :class:`JobRow` 와 콜백만 받는다(Job·레지스트리 직접 접근 없음).
    """

    def __init__(self, row: JobRow, on_run, on_edit, on_delete, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(3)

        name_row = QHBoxLayout()
        lbl_name = QLabel(row.name)
        mark(lbl_name, "heading", True)
        name_row.addWidget(lbl_name)
        # C2 파생 컴파일 상태 배지(부재·원문·미확인 N개·실행 준비) — 기존 '템플릿 없음'
        # pill 어휘를 확장한다. 문구는 JobRow.compile_badge(seam), 색은 상태에서 파생.
        if row.compile_badge:
            lbl_badge = QLabel(row.compile_badge)
            mark(lbl_badge, "fb", _badge_fb(row))
            name_row.addWidget(lbl_badge)
        name_row.addStretch(1)
        root.addLayout(name_row)

        lbl_meta = QLabel(row.meta_line())
        mark(lbl_meta, "muted", True)
        lbl_meta.setWordWrap(True)  # 카드 폭에 맞춰 줄바꿈(가로 넘침 방지)
        root.addWidget(lbl_meta)

        foot = QHBoxLayout()
        lbl_run = QLabel(row.last_run_display)
        mark(lbl_run, "muted", True)
        foot.addWidget(lbl_run)
        foot.addStretch(1)
        btn_run = QPushButton("문서 생성")
        mark(btn_run, "primary", True)
        btn_run.setEnabled(not row.template_missing)  # 템플릿 없으면 실행 불가(홈에서 선고지)
        btn_run.clicked.connect(lambda: on_run(row.name))
        btn_edit = QPushButton("작업 수정")
        btn_edit.clicked.connect(lambda: on_edit(row.name))
        btn_del = QPushButton("삭제")
        btn_del.clicked.connect(lambda: on_delete(row.name))
        foot.addWidget(btn_run)
        foot.addWidget(btn_edit)
        foot.addWidget(btn_del)
        root.addLayout(foot)


class _TxtCard(QWidget):
    """txt 기안 템플릿 카드 — 이름 + 필드 수 + [기안 열기]."""

    def __init__(self, row: TxtRow, on_open, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 7, 10, 7)
        box = QVBoxLayout()
        box.setSpacing(1)
        lbl_name = QLabel(f"{row.name}.txt")
        lbl_name.setStyleSheet("font-weight:600;")
        lbl_fields = QLabel(f"필드 {row.field_count}개")
        mark(lbl_fields, "muted", True)
        box.addWidget(lbl_name)
        box.addWidget(lbl_fields)
        root.addLayout(box)
        root.addStretch(1)
        btn_open = QPushButton("기안 작성")
        mark(btn_open, "primary", True)
        btn_open.clicked.connect(lambda: on_open(row.name))
        root.addWidget(btn_open)


class JobListHome(QMainWindow):
    """투트랙 허브 대시보드. :class:`HomeViewModel` 을 렌더하고 액션을 시그널로 방출한다."""

    # HWPX 트랙(불변 계약)
    new_job_requested = Signal()
    edit_job_requested = Signal(str)
    run_job_requested = Signal(str)
    delete_job_requested = Signal(str)
    # txt 트랙(신규)
    new_txt_requested = Signal()
    open_txt_requested = Signal(str)  # 템플릿 이름

    def __init__(self, registry: JobRegistry, text_registry=None, parent=None):
        super().__init__(parent)
        self.registry = registry
        # 기본 txt 레지스트리(주입 없으면 표준 루트) — 대시보드 txt 트랙.
        if text_registry is None:
            from ..core.text_registry import TextTemplateRegistry, default_text_templates_dir
            text_registry = TextTemplateRegistry(default_text_templates_dir())
        self.text_registry = text_registry
        self.vm = HomeViewModel(registry, text_registry)

        self.setWindowTitle("HWPX Filler — 대시보드")
        self.resize(900, 560)
        self.setStyleSheet(BASE_QSS)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ---- 헤더 ----
        header = QHBoxLayout()
        title = QLabel("대시보드")
        mark(title, "heading", True)
        sub = QLabel("내 작업 보관함")
        mark(sub, "muted", True)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(sub)
        root.addLayout(header)

        # ---- KPI 타일(내용은 _render 가 채운다) ----
        self.kpi_row = QHBoxLayout()
        self.kpi_row.setSpacing(10)
        root.addLayout(self.kpi_row)

        # ---- 투트랙 ----
        tracks = QHBoxLayout()
        tracks.setSpacing(14)

        # 좌: HWPX
        hwpx = self._panel("HWPX 문서 생성")
        hp = hwpx.layout()
        hhead = QHBoxLayout()
        self.btn_new = QPushButton("＋ 새 문서 작업")
        mark(self.btn_new, "primary", True)
        self.btn_new.clicked.connect(self.new_job_requested)
        hhead.addWidget(QLabel("누름틀 템플릿 + 매핑 → .hwpx 생성"))
        hhead.addStretch(1)
        hhead.addWidget(self.btn_new)
        hp.addLayout(hhead)
        self.stack = QStackedWidget()
        self.list = QListWidget()
        self.list.setObjectName("jobList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 카드가 뷰포트 폭에 맞음
        self.list.itemDoubleClicked.connect(
            lambda _it: self._emit_for_selected(self.run_job_requested)
        )
        self.stack.addWidget(self.list)                    # 0 = 목록
        self.stack.addWidget(self._build_empty_state())    # 1 = 빈 상태
        hp.addWidget(self.stack, 1)
        tracks.addWidget(hwpx, 3)

        # 우: txt
        txt = self._panel("간단 기안 작성")
        tp = txt.layout()
        thead = QHBoxLayout()
        self.btn_new_txt = QPushButton("＋ 새 기안")
        mark(self.btn_new_txt, "primary", True)
        self.btn_new_txt.clicked.connect(self.new_txt_requested)
        thead.addWidget(QLabel("기안 템플릿으로 문안 미리보기"))
        thead.addStretch(1)
        thead.addWidget(self.btn_new_txt)
        tp.addLayout(thead)
        self.txt_list = QListWidget()
        self.txt_list.setObjectName("jobList")
        self.txt_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.txt_list.itemDoubleClicked.connect(self._emit_txt_for_item)
        tp.addWidget(self.txt_list, 1)
        self.lbl_route = QLabel("기안 템플릿 보관함")
        mark(self.lbl_route, "muted", True)
        tp.addWidget(self.lbl_route)
        tracks.addWidget(txt, 2)

        root.addLayout(tracks, 1)

        self.vm.subscribe(self._render)
        self._render()

    # ------------------------------------------------------------- 빌더
    @staticmethod
    def _panel(title: str) -> QFrame:
        frame = QFrame()
        frame.setProperty("card", True)
        box = QVBoxLayout(frame)
        box.setContentsMargins(14, 12, 14, 12)
        lbl = QLabel(title)
        mark(lbl, "heading", True)
        box.addWidget(lbl)
        return frame

    def _build_empty_state(self) -> QWidget:
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.addStretch(2)
        lbl = QLabel("저장된 작업이 없습니다")
        mark(lbl, "heading", True)
        lbl.setAlignment(Qt.AlignCenter)
        sub = QLabel("템플릿과 매핑을 묶어 첫 작업을 만드세요.\n데이터·행은 실행할 때 고릅니다.")
        mark(sub, "muted", True)
        sub.setAlignment(Qt.AlignCenter)
        self.btn_empty_new = QPushButton("＋ 새 작업 만들기")
        mark(self.btn_empty_new, "primary", True)
        self.btn_empty_new.clicked.connect(self.new_job_requested)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_empty_new)
        row.addStretch(1)
        box.addWidget(lbl)
        box.addWidget(sub)
        box.addLayout(row)
        box.addStretch(3)
        return panel

    def _kpi_tile(self, value: str, label: str, warn: bool = False) -> QFrame:
        tile = QFrame()
        tile.setProperty("card", True)
        box = QVBoxLayout(tile)
        box.setContentsMargins(13, 11, 13, 11)
        box.setSpacing(2)
        v = QLabel(value)
        mark(v, "kpi", "value")
        if warn:
            mark(v, "level", "warn")
        lbl = QLabel(label)
        mark(lbl, "kpi", "label")
        box.addWidget(v)
        box.addWidget(lbl)
        return tile

    # ------------------------------------------------------------- 렌더
    def refresh(self) -> None:
        """배선(app.py)이 저장·삭제·실행 후 호출 → 뷰모델 재적재 → _render 통지."""
        self.vm.refresh()

    def _render(self) -> None:
        # KPI
        while self.kpi_row.count():
            item = self.kpi_row.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        k = self.vm.kpi()
        self.kpi_row.addWidget(self._kpi_tile(str(k.job_count), "저장된 작업 · HWPX"))
        self.kpi_row.addWidget(self._kpi_tile(k.recent_run, "최근 실행"))
        self.kpi_row.addWidget(
            self._kpi_tile(str(k.missing_template_count), "템플릿 없는 작업", warn=k.missing_template_count > 0)
        )
        self.kpi_row.addWidget(self._kpi_tile(str(k.txt_template_count), "기안 템플릿 · txt"))

        # HWPX 작업 목록
        prev = self.vm.selected_name
        self.list.blockSignals(True)
        self.list.clear()
        for row in self.vm.rows():
            self.list.addItem(row.name)
            item = self.list.item(self.list.count() - 1)
            item.setForeground(QColor(0, 0, 0, 0))  # 이름은 아이템 text(계약), 표시는 카드
            card = _JobCard(
                row,
                on_run=self.run_job_requested.emit,
                on_edit=self.edit_job_requested.emit,
                on_delete=self.delete_job_requested.emit,
            )
            item.setSizeHint(card.sizeHint())
            self.list.setItemWidget(item, card)
        self.stack.setCurrentIndex(1 if self.vm.is_empty() else 0)
        if prev is not None:
            items = self.list.findItems(prev, Qt.MatchExactly)
            if items:
                self.list.setCurrentItem(items[0])
        self.list.blockSignals(False)

        # txt 기안 템플릿 목록
        self.txt_list.clear()
        for trow in self.vm.txt_rows():
            self.txt_list.addItem(trow.name)
            item = self.txt_list.item(self.txt_list.count() - 1)
            item.setForeground(QColor(0, 0, 0, 0))
            card = _TxtCard(trow, on_open=self.open_txt_requested.emit)
            item.setSizeHint(card.sizeHint())
            self.txt_list.setItemWidget(item, card)

        # 폭/높이 동기화는 레이아웃이 자리잡은 뒤로 미룬다(생성 시 viewport 폭이 아직 미확정).
        self._sync_item_widths()
        QTimer.singleShot(0, self._sync_item_widths)

    def _sync_item_widths(self) -> None:
        """카드 폭을 뷰포트에 고정한 뒤 그 폭에서의 높이로 아이템을 잡는다 — 가로 스크롤 없고
        줄바꿈된 메타·카드별 액션이 온전히 보인다."""
        for lst in (self.list, self.txt_list):
            w = lst.viewport().width()
            for i in range(lst.count()):
                it = lst.item(i)
                widget = lst.itemWidget(it)
                if widget is None:
                    continue
                widget.setFixedWidth(w)                 # 폭 고정 → 줄바꿈·높이 재계산
                it.setSizeHint(QSize(w, widget.sizeHint().height()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_item_widths()

    # ------------------------------------------------------------- 선택/보조
    def selected_job_name(self) -> "str | None":
        it = self.list.currentItem()
        return it.text() if it is not None else None

    def _emit_for_selected(self, signal) -> None:
        name = self.selected_job_name()
        if name is not None:
            signal.emit(name)

    def _emit_txt_for_item(self, item) -> None:
        if item is not None:
            self.open_txt_requested.emit(item.text())
