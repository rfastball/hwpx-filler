"""단일창 셸 — 좌 네비 레일 + QStackedWidget 페이지 호스트 (ST-01, docs/SHELL_DESIGN.md).

능력마다 별도 최상위 창을 띄우던 다중창 모델을 단일 QMainWindow 로 수렴한다:
좌측 네비 레일(현재 위치 표지 = 선택 하이라이트) + 페이지 스택. 페이지는
지연 생성(첫 방문 시 factory) · 은닉 보존(전환해도 파괴하지 않음 — 상태 유지) ·
재진입 시 ``refresh()`` 호출(은닉 중 외부 변경 스테일 방지)로 산다(D6).

페이지 프로토콜(덕타이핑 — ABC 발명 금지, SHELL_DESIGN §3):

- ``can_leave() -> bool`` (없으면 항상 허용): 이탈 가드 — 레일 전환·:meth:`activate`·
  셸 닫기·run 슬롯 교체가 공유하는 **단일 경로**(D8). False 면 전환/닫기가 무산된다.
- ``refresh()`` (없으면 no-op): 재진입 시 호출.
- ``windowTitle()``: 페이지 정체(기존 창 제목 유지 — 테스트·접근성 호환).

배선은 AppController 소유(핸드오프 §0 고정 이음새) — 레일 클릭은
:attr:`nav_requested` 로 **요청만** 하고, 컨트롤러가 factory 를 들고
:meth:`activate` 를 호출한다. 이탈 게이트는 :meth:`activate` 한 곳에서만 —
경로별 개별 확인(이중 다이얼로그)을 만들지 않는다.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from .style import BASE_QSS
from .view_helpers import restore_geometry, save_geometry

RAIL_WIDTH = 216  # UI_PROTOTYPE_APPB .shell 그리드(216px 1fr)와 일치
RUN_KEY = "run"  # run 파라미터 슬롯(§2) — 동적 레일 항목 "실행: {작업명}"


def _page_can_leave(page) -> bool:
    """페이지 이탈 가드 — ``can_leave`` 가 없으면 항상 허용(덕타이핑)."""
    gate = getattr(page, "can_leave", None)
    return bool(gate()) if callable(gate) else True


class ShellWindow(QMainWindow):
    """단일창 셸. 페이지 등록·전환·수명을 소유한다 — 배선(factory)은 컨트롤러 몫."""

    nav_requested = Signal(str)  # 레일 클릭 → 컨트롤러가 factory 들고 activate(key)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HWPX Filler")
        # ST-11 재적합(D7): 창이 하나뿐이므로 지속 키도 "shell" 하나. 레일 폭이 붙어
        # 기존 home 기본(900×560)보다 넓게 연다.
        restore_geometry(self, "shell", default_size=(1140, 720))
        self.setStyleSheet(BASE_QSS)

        self._pages: "dict[str, QWidget]" = {}
        self._rail_keys: "list[str]" = []  # 레일 행 ↔ 페이지 키 (행 순서 불변식)
        self._run_job: "str | None" = None  # run 슬롯이 현재 겨눈 작업명

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.rail = QListWidget()
        self.rail.setObjectName("navRail")
        self.rail.setFixedWidth(RAIL_WIDTH)
        self.rail.setAccessibleName("탐색")  # ST-06 — 보조기술 정체 노출
        self.rail.currentRowChanged.connect(self._on_rail_row)
        row.addWidget(self.rail)
        self.stack = QStackedWidget()
        row.addWidget(self.stack, 1)
        self.setCentralWidget(central)

    # ------------------------------------------------------------------ 레일
    def register_static(self, key: str, title: str, desc: str = "") -> None:
        """레일에 정적 항목을 예약한다 — 페이지 위젯은 지연(D6). 등록 순서 = 레일 순서.

        동적 run 항목은 :meth:`open_run` 이 끝에 덧붙이므로, 정적 등록은 기동 배선
        단계에서 모두 끝나 있어야 한다(순서 불변식).
        """
        if key in self._rail_keys:
            raise ValueError(f"이미 등록된 레일 키: {key}")  # 조용한 중복 금지
        item = QListWidgetItem(title)
        if desc:
            item.setToolTip(desc)
        self._rail_keys.append(key)
        self.rail.addItem(item)

    def _on_rail_row(self, row: int) -> None:
        """사용자 레일 선택 → 컨트롤러에 요청만. 게이트·복원은 activate 가 수행."""
        if not (0 <= row < len(self._rail_keys)):
            return
        key = self._rail_keys[row]
        page = self._pages.get(key)
        if page is not None and page is self.stack.currentWidget():
            return  # 이미 전면 — 요청 불요
        self.nav_requested.emit(key)

    def _set_rail_row(self, row: int) -> None:
        """프로그램적 레일 선택 — currentRowChanged 재귀(R6)를 차단한다."""
        self.rail.blockSignals(True)
        try:
            self.rail.setCurrentRow(row)
        finally:
            self.rail.blockSignals(False)

    def _sync_rail_to_current(self) -> None:
        """레일 하이라이트를 실제 현재 페이지로 복원한다(이탈 거부 후 시각 일관)."""
        current = self.stack.currentWidget()
        for key, page in self._pages.items():
            if page is current:
                self._set_rail_row(self._rail_keys.index(key))
                return

    # ---------------------------------------------------------------- 페이지
    def activate(self, key: str, factory=None) -> QWidget:
        """페이지를 전면으로. 없으면 ``factory()`` 로 생성·등록(지연 — D6), 있으면 재사용.

        현재 페이지의 ``can_leave()`` 가 거부하면 전환을 무산하고 현재 페이지를
        돌려준다(D8) — 레일 하이라이트도 현재 위치로 복원한다. 재진입(이미 있던
        페이지로 복귀) 시 ``refresh()`` 를 호출해 은닉 중 스테일을 해소한다.
        미등록 키를 factory 없이 요청하면 KeyError — 배선 오류는 시끄럽게.
        """
        page = self._pages.get(key)
        current = self.stack.currentWidget()
        if page is not None and page is current:
            return page  # 이미 전면 — 게이트·refresh 불요
        if current is not None and not _page_can_leave(current):
            self._sync_rail_to_current()
            return current
        created = False
        if page is None:
            if factory is None:
                raise KeyError(f"미등록 페이지: {key}")
            page = factory()
            self._pages[key] = page
            self.stack.addWidget(page)
            created = True
            if key not in self._rail_keys:
                # 동적 페이지(run) — 레일 끝에 항목 추가, 라벨은 페이지 창제목.
                self._rail_keys.append(key)
                self.rail.addItem(page.windowTitle() or key)
        self.stack.setCurrentWidget(page)
        self._set_rail_row(self._rail_keys.index(key))
        if not created and hasattr(page, "refresh"):
            page.refresh()  # 재진입 스테일 방지(D6) — 생성 직후는 생성자가 신선
        return page

    def open_run(self, job_name: str, factory) -> QWidget:
        """run 파라미터 슬롯(§2): 같은 작업은 재사용, 다른 작업은 게이트 경유 교체.

        기존 run 페이지가 실행 중이면 그 ``can_leave()``(협조적 취소 확인, ST-21)가
        교체를 게이트한다 — 수락 경로는 뷰가 취소 요청+teardown 을 보장한다(R4).
        거부 시 기존 실행 페이지를 전면으로 가져와 진행 중임을 보인다.
        """
        existing = self._pages.get(RUN_KEY)
        if existing is not None and self._run_job == job_name:
            return self.activate(RUN_KEY)  # 재사용 — 전면으로(+재진입 refresh)
        # 교체 경로: ① 현재 페이지 이탈 게이트(run 이 아닌 페이지를 보고 있을 때)
        current = self.stack.currentWidget()
        if current is not None and current is not existing and not _page_can_leave(current):
            self._sync_rail_to_current()
            return current
        # ② 기존 run 페이지 파괴 게이트(실행 중 확인 — 은닉 중이어도 파괴 전 확인)
        if existing is not None:
            if not _page_can_leave(existing):
                return self.activate(RUN_KEY)  # 교체 거부 — 진행 중 실행을 전면으로
            self._remove_page(RUN_KEY)
        page = factory()
        self._pages[RUN_KEY] = page
        self.stack.addWidget(page)
        if RUN_KEY not in self._rail_keys:
            self._rail_keys.append(RUN_KEY)
            self.rail.addItem("")
        # 동적 레일 라벨 = 실행 대상 명시(현재 위치 표지) — 창제목보다 짧은 레일용 표기.
        self.rail.item(self._rail_keys.index(RUN_KEY)).setText(f"실행: {job_name}")
        self._run_job = job_name
        self.stack.setCurrentWidget(page)
        self._set_rail_row(self._rail_keys.index(RUN_KEY))
        return page

    def _remove_page(self, key: str) -> None:
        """페이지를 스택·레일에서 제거하고 파괴를 예약한다(run 슬롯 교체 전용).

        takeItem 이 현재 레일 행을 옮기며 currentRowChanged 를 쏘면 nav_requested
        재진입(R6)이 일어나므로 레일 시그널을 막고 제거한다.
        """
        page = self._pages.pop(key)
        row = self._rail_keys.index(key)
        self._rail_keys.pop(row)
        self.rail.blockSignals(True)
        try:
            self.rail.takeItem(row)
        finally:
            self.rail.blockSignals(False)
        self.stack.removeWidget(page)
        page.deleteLater()
        if key == RUN_KEY:
            self._run_job = None

    # ------------------------------------------------------------------ 조회
    def go_home(self) -> QWidget:
        """홈 페이지로 복귀(인-윈도 내비게이션의 기저선)."""
        return self.activate("home")

    def current_key(self) -> "str | None":
        """현재 전면 페이지의 키 — 테스트 seam."""
        current = self.stack.currentWidget()
        for key, page in self._pages.items():
            if page is current:
                return key
        return None

    # ------------------------------------------------------------------ 수명
    def closeEvent(self, event) -> None:  # noqa: N802 — Qt 오버라이드
        # 전 생존 페이지 이탈 게이트(D8) — 현재 페이지부터(보고 있는 맥락 우선).
        pages = sorted(
            self._pages.values(), key=lambda p: p is not self.stack.currentWidget()
        )
        for page in pages:
            if not _page_can_leave(page):
                event.ignore()
                return
        save_geometry(self, "shell")  # 세션 간 크기·위치 유지(ST-11, D7)
        super().closeEvent(event)
