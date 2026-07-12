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
from .compile_badge import badge_level
from .home_state import BADGE_CORRUPT, CorruptJobRow, HomeViewModel, JobRow, TxtRow
from .style import BASE_QSS, mark


class JobCard(QWidget):
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
        # pill 어휘를 확장한다. 문구는 JobRow.compile_badge(seam), 심각도 레벨은
        # compile_badge.badge_level(링1 단일 출처 — 템플릿 관리 배지와 동일 어휘, RC-29).
        # 실행 화면 필드 상태 셀렉터(fb)를 다른 뜻으로 재전용하지 않는다.
        if row.compile_badge:
            lbl_badge = QLabel(row.compile_badge)
            mark(lbl_badge, "pill", badge_level(row.compile_state))
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
        btn_run = QPushButton("실행")
        # 실행 진입 판정을 badge_level 단일 술어에 연결(UD-03): danger(부재·손상·오류)는
        # 비활성 — 더블클릭 경로도 같은 게이트(JobRow.is_runnable)를 공유한다. 주 액션
        # 강조(primary)는 '실행 준비'(ok)에만 준다 — RAW/PARTIAL 은 활성이되 최소 강등해
        # '지금 실행 준비 vs 아직 손봐야 함'을 시각으로 가른다.
        btn_run.setEnabled(row.is_runnable())
        if badge_level(row.compile_state) == "ok":
            mark(btn_run, "primary", True)
        btn_run.clicked.connect(lambda: on_run(row.name))
        btn_edit = QPushButton("작업 수정")
        btn_edit.clicked.connect(lambda: on_edit(row.name))
        btn_del = QPushButton("삭제")
        mark(btn_del, "level", "danger")  # 파괴 버튼 시각 등급(UD-12) — 안전 버튼과 구별
        btn_del.clicked.connect(lambda: on_delete(row.name))
        foot.addWidget(btn_run)
        foot.addWidget(btn_edit)
        foot.addWidget(btn_del)
        root.addLayout(foot)


# 하위호환 별칭(RC-35): 스모크 테스트 등 크로스모듈 인용이 실재하는 공용 표면 —
# 기존 `_JobCard` 임포트는 이 별칭으로 계속 동작한다.
_JobCard = JobCard


class _CorruptJobCard(QWidget):
    """손상 ``.job.json`` 행 카드 — 파일명 + '손상됨' 배지 + 오류·경로(RC-05).

    실행/편집은 없지만(파싱 불가라 실행 대상이 아님) 앱 내 해소 동선은 제공한다(UD-44):
    원인 파일을 폴더에서 열어 수동 복구하거나, 확인을 거쳐 삭제할 수 있다 — 정상 카드와
    같은 파괴 어휘([삭제]·confirm_destructive)라 '해소 불가 상시 경보'의 습관화를 막는다.
    """

    def __init__(self, row: CorruptJobRow, on_open=None, on_delete=None, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(3)

        name_row = QHBoxLayout()
        lbl_name = QLabel(row.file_name)
        mark(lbl_name, "heading", True)
        name_row.addWidget(lbl_name)
        lbl_badge = QLabel(BADGE_CORRUPT)
        # 손상 = 상태 판정 불가(None)와 같은 심각도(danger) — compile_badge 어휘 재사용.
        mark(lbl_badge, "pill", badge_level(None))
        name_row.addWidget(lbl_badge)
        name_row.addStretch(1)
        root.addLayout(name_row)

        lbl_meta = QLabel(f"{row.detail_line()}\n경로: {row.path}")
        mark(lbl_meta, "muted", True)
        lbl_meta.setWordWrap(True)
        root.addWidget(lbl_meta)

        # 해소 동선(UD-44) — 콜백은 손상 파일 경로를 나른다(이름 없음 → 경로 식별).
        foot = QHBoxLayout()
        foot.addStretch(1)
        btn_open = QPushButton("폴더 열기")
        if on_open is not None:
            btn_open.clicked.connect(lambda: on_open(row.path))
        btn_del = QPushButton("삭제")
        mark(btn_del, "level", "danger")  # 파괴 버튼 시각 등급(정상 카드와 동일 어휘)
        if on_delete is not None:
            btn_del.clicked.connect(lambda: on_delete(row.path))
        foot.addWidget(btn_open)
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
    # 데이터 풀 관리(J1) — 앱 컨트롤러(app.py)가 직결 배선한다.
    manage_pool_requested = Signal()
    # 여러 작업 일괄 실행(J2 매트릭스).
    matrix_run_requested = Signal()
    # 매핑 프로파일 관리(J3 — 공유 매핑 프로파일 계보). 시그널명은 코드 심볼로 유지.
    manage_vocab_requested = Signal()
    # 템플릿 관리 워크숍(C5) — 헤더 [템플릿 관리] 버튼이 방출(RC-04 소생 진입점).
    manage_templates_requested = Signal()
    # 손상 작업 파일 해소 동선(UD-44) — 앱 컨트롤러가 폴더 열기·확인 삭제로 처리.
    # 손상 행은 이름이 없어(파싱 불가) 인자는 파일 경로다(run_job_requested 의 작업명 계약과 별개).
    reveal_corrupt_requested = Signal(str)
    delete_corrupt_requested = Signal(str)

    def __init__(self, registry: JobRegistry, text_registry=None, parent=None,
                 pool_registry=None):
        super().__init__(parent)
        self.registry = registry
        # 기본 txt 레지스트리(주입 없으면 표준 루트) — 대시보드 txt 트랙.
        if text_registry is None:
            from ..core.text_registry import TextTemplateRegistry, default_text_templates_dir
            text_registry = TextTemplateRegistry(default_text_templates_dir())
        self.text_registry = text_registry
        # 기본 데이터 풀 레지스트리(durable 참조) — 대시보드 KPI + 관리 진입.
        if pool_registry is None:
            from ..core.dataset_pool import DatasetPoolRegistry, default_dataset_pool_dir
            pool_registry = DatasetPoolRegistry(default_dataset_pool_dir())
        self.pool_registry = pool_registry
        self.vm = HomeViewModel(registry, text_registry, pool_registry)

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
        # 부제는 제목 인접(UD-36) — 헤더 버튼 뒤 최우단 표류를 해소해 '무엇의 라벨인지'를
        # 위치로 말한다. 액션 버튼은 stretch 뒤 우측에 모은다.
        header.addWidget(title)
        header.addWidget(sub)
        header.addStretch(1)
        self.btn_templates = QPushButton("템플릿 관리")
        self.btn_templates.clicked.connect(self.manage_templates_requested)
        self.btn_pool = QPushButton("데이터 풀 관리")
        self.btn_pool.clicked.connect(self.manage_pool_requested)
        self.btn_vocab = QPushButton("매핑 프로파일 관리")
        self.btn_vocab.clicked.connect(self.manage_vocab_requested)
        header.addWidget(self.btn_templates)
        header.addWidget(self.btn_pool)
        header.addWidget(self.btn_vocab)
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
        self.btn_matrix = QPushButton("여러 작업 일괄 실행")
        self.btn_matrix.clicked.connect(self.matrix_run_requested)
        lbl_hwpx_hint = QLabel("누름틀 템플릿 + 매핑 → .hwpx 생성")
        mark(lbl_hwpx_hint, "muted", True)  # 부연 라벨 위계 통일(UD-36) — 화면 전체 muted
        hhead.addWidget(lbl_hwpx_hint)
        hhead.addStretch(1)
        hhead.addWidget(self.btn_matrix)
        hhead.addWidget(self.btn_new)
        hp.addLayout(hhead)
        self.stack = QStackedWidget()
        self.list = QListWidget()
        self.list.setObjectName("jobList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 카드가 뷰포트 폭에 맞음
        # 더블클릭 실행 진입 — 버튼 경로와 같은 게이트를 공유한다(UD-03). 무조건 배선하던
        # 과거는 손상 카드(비작업)를 조용한 크래시로, 실행 불가 카드를 무게이트 우회로 보냈다.
        self.list.itemDoubleClicked.connect(self._on_job_double_click)
        self.stack.addWidget(self.list)                    # 0 = 목록
        self.stack.addWidget(self._build_empty_state())    # 1 = 빈 상태
        hp.addWidget(self.stack, 1)
        tracks.addWidget(hwpx, 3)

        # 우: txt
        txt = self._panel("즉시 기안")
        tp = txt.layout()
        thead = QHBoxLayout()
        self.btn_new_txt = QPushButton("＋ 새 기안")
        mark(self.btn_new_txt, "primary", True)
        self.btn_new_txt.clicked.connect(self.new_txt_requested)
        lbl_txt_hint = QLabel("기안 템플릿으로 문안 미리보기")
        mark(lbl_txt_hint, "muted", True)  # 부연 라벨 위계 통일(UD-36)
        thead.addWidget(lbl_txt_hint)
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
        self.kpi_row.addWidget(self._kpi_tile(str(k.pool_count), "데이터 풀 · 활성"))

        # HWPX 작업 목록
        prev = self.vm.selected_name
        self.list.blockSignals(True)
        self.list.clear()
        for row in self.vm.rows():
            self.list.addItem(row.name)
            item = self.list.item(self.list.count() - 1)
            item.setForeground(QColor(0, 0, 0, 0))  # 이름은 아이템 text(계약), 표시는 카드
            card = JobCard(
                row,
                on_run=self.run_job_requested.emit,
                on_edit=self.edit_job_requested.emit,
                on_delete=self.delete_job_requested.emit,
            )
            item.setSizeHint(card.sizeHint())
            self.list.setItemWidget(item, card)
        # 손상 .job.json 행(RC-05) — 정상 작업 뒤에 '손상됨' 배지 카드로 시끄럽게 노출.
        # 아이템 text 는 파일명(이름을 알 수 없음 — findItems 작업명 계약과 충돌 없음).
        for crow in self.vm.corrupt_rows():
            self.list.addItem(crow.file_name)
            item = self.list.item(self.list.count() - 1)
            item.setForeground(QColor(0, 0, 0, 0))
            # 손상 행은 실행 대상이 아니다(UD-03 증상 3) — 선택 하이라이트로 실행 대상처럼
            # 보이지 않게 선택 플래그를 내린다. 더블클릭도 _on_job_double_click 가 무작업 처리.
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            card = _CorruptJobCard(
                crow,
                on_open=self.reveal_corrupt_requested.emit,
                on_delete=self.delete_corrupt_requested.emit,
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

    def _job_row_by_name(self, name: str) -> "JobRow | None":
        """이름으로 성형 행을 찾는다(더블클릭 게이트가 상태를 조회할 이음새)."""
        for r in self.vm.rows():
            if r.name == name:
                return r
        return None

    def _on_job_double_click(self, item) -> None:
        """더블클릭 실행 진입 — 버튼 [실행]과 같은 게이트(is_runnable)를 공유한다(UD-03).

        손상 행(비작업)은 무작업으로 무시하고(카드 자체 [폴더 열기]/[삭제]로 해소),
        실행 불가 상태(danger)는 조용한 no-op/크래시 대신 사유를 시끄럽게 고지한다.
        정상·실행 가능 행만 run_job_requested(작업명)를 방출한다 — 손상 행 파일명을
        방출하던 계약 위반(seam 은 작업명)도 함께 막힌다.
        """
        row = self._job_row_by_name(item.text())
        if row is None:
            return  # 손상/비작업 행 — 실행 대상 아님
        if not row.is_runnable():
            self._warn_not_runnable(row)
            return
        self.run_job_requested.emit(row.name)

    def _warn_not_runnable(self, row: "JobRow") -> None:
        """실행 불가 카드 진입 시 시끄러운 사유 고지(UD-03) — stderr 침묵 금지."""
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            self, "실행할 수 없습니다",
            f"'{row.name}' 은(는) 지금 실행할 수 없습니다 — {row.compile_badge or '템플릿 미설정'}.\n"
            "작업을 수정해 템플릿을 연결하거나 복구한 뒤 실행하세요.",
        )

    def _emit_txt_for_item(self, item) -> None:
        if item is not None:
            self.open_txt_requested.emit(item.text())
