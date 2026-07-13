"""셸(ShellWindow) 계약 테스트 — 레일↔스택 동기·지연 생성·이탈 게이트·run 슬롯(ST-01).

셸 로직은 실제 능력 뷰 없이 더미 페이지(덕타이핑 프로토콜: can_leave/refresh)로
검증한다 — 실제 뷰의 임베드 배선은 test_gui_smoke.py 가 검증한다(SHELL_DESIGN §6).
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from hwpxfiller.gui.shell import ShellWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def shell(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))  # QSettings 격리(ST-11)
    win = ShellWindow()
    yield win
    win.deleteLater()


class _Page(QWidget):
    """페이지 프로토콜 더미 — can_leave 응답·refresh 호출 횟수를 계측한다."""

    def __init__(self, title="페이지", leave=True):
        super().__init__()
        self.setWindowTitle(title)
        self.leave = leave
        self.refreshed = 0
        self.leave_asked = 0

    def can_leave(self) -> bool:
        self.leave_asked += 1
        return self.leave

    def refresh(self) -> None:
        self.refreshed += 1


def test_rail_stack_sync_and_lazy_factory(shell):
    """레일 행 ↔ 현재 페이지 동기(현재 위치 표지) + factory 는 첫 방문에 1회만."""
    shell.register_static("home", "대시보드")
    shell.register_static("pool", "데이터 풀")
    calls = {"home": 0, "pool": 0}

    def make(key):
        def _factory():
            calls[key] += 1
            return _Page(key)

        return _factory

    home = shell.activate("home", factory=make("home"))
    assert shell.current_key() == "home"
    assert shell.rail.currentRow() == 0
    pool = shell.activate("pool", factory=make("pool"))
    assert shell.current_key() == "pool"
    assert shell.rail.currentRow() == 1
    # 재진입 — factory 재호출 없이 같은 인스턴스 재사용(은닉 보존) + refresh(스테일 방지).
    again = shell.activate("home", factory=make("home"))
    assert again is home
    assert calls["home"] == 1
    assert home.refreshed == 1
    # 첫 생성 직후엔 refresh 를 부르지 않는다(생성자가 신선).
    assert pool.refreshed == 0


def test_activate_current_page_is_noop(shell):
    """이미 전면인 페이지 재요청은 게이트도 refresh 도 부르지 않는다."""
    shell.register_static("home", "대시보드")
    page = shell.activate("home", factory=_Page)
    shell.activate("home")
    assert page.refreshed == 0
    assert page.leave_asked == 0


def test_can_leave_refusal_blocks_switch_and_restores_rail(shell):
    """이탈 거부(D8) — 전환 무산·현재 페이지 유지·레일 하이라이트 복원."""
    shell.register_static("busy", "실행형")
    shell.register_static("other", "다른 페이지")
    busy = shell.activate("busy", factory=lambda: _Page("실행형", leave=False))
    result = shell.activate("other", factory=_Page)
    assert result is busy  # 전환 무산 — 현재 페이지 반환
    assert shell.current_key() == "busy"
    assert shell.rail.currentRow() == 0  # 하이라이트 복원
    assert busy.leave_asked == 1
    busy.leave = True
    other = shell.activate("other", factory=_Page)
    assert other is not busy
    assert shell.current_key() == "other"


def test_rail_click_requests_nav_and_controller_activates(shell):
    """레일 클릭 → nav_requested 요청 → (컨트롤러 역할) activate — 배선 소유 분리."""
    shell.register_static("home", "대시보드")
    shell.register_static("pool", "데이터 풀")
    pages = {"home": _Page("홈"), "pool": _Page("풀")}
    shell.nav_requested.connect(
        lambda key: shell.activate(key, factory=lambda: pages[key])
    )
    shell.activate("home", factory=lambda: pages["home"])
    shell.rail.setCurrentRow(1)  # 사용자 레일 클릭 상당
    assert shell.current_key() == "pool"


def test_activate_unknown_without_factory_is_loud(shell):
    """미등록 페이지를 factory 없이 요청 = 배선 오류 — 조용한 무시 대신 KeyError."""
    with pytest.raises(KeyError):
        shell.activate("ghost")


def test_close_gated_by_page_and_geometry_persists(qapp, tmp_path, monkeypatch):
    """셸 닫기도 can_leave 경유(D8) + "shell" 지오메트리 키 왕복(ST-11, D7)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    win = ShellWindow()
    win.register_static("busy", "실행형")
    page = win.activate("busy", factory=lambda: _Page(leave=False))
    win.show()
    assert win.close() is False  # 이탈 거부 → 닫기 무산
    assert win.isVisible()
    page.leave = True
    # offscreen 가상 화면(800×600) 안의 크기만 왕복 검증 — 화면 초과 폭은 Qt 가
    # 복원 시 화면에 맞게 클램프한다(기존 ST-11 테스트와 같은 제약).
    win.resize(720, 540)
    assert win.close() is True
    win.deleteLater()
    reborn = ShellWindow()
    assert (reborn.width(), reborn.height()) == (720, 540)
    reborn.deleteLater()


def test_open_run_slot_reuses_replaces_and_gates(shell):
    """run 파라미터 슬롯: 같은 작업 재사용 / 다른 작업 게이트 경유 교체 / 거부 시 존치."""
    made = []

    def factory_for(job):
        def _factory():
            page = _Page(f"실행 {job}")
            made.append(page)
            return page

        return _factory

    first = shell.open_run("보고서", factory_for("보고서"))
    assert shell.current_key() == "run"
    assert shell.rail.item(shell.rail.currentRow()).text() == "실행: 보고서"
    # 같은 작업 재요청 → 재사용(새 인스턴스 없음).
    again = shell.open_run("보고서", factory_for("보고서"))
    assert again is first
    assert len(made) == 1
    # 다른 작업 → 기존 페이지 게이트 통과 시 교체(동적 레일 라벨 갱신).
    second = shell.open_run("계약서", factory_for("계약서"))
    assert second is not first
    assert len(made) == 2
    assert shell.rail.item(shell.rail.currentRow()).text() == "실행: 계약서"
    # 실행 중(이탈 거부) 교체 시도 → 기존 실행 페이지 존치·전면 유지.
    second.leave = False
    third = shell.open_run("보고서", factory_for("보고서"))
    assert third is second
    assert len(made) == 2
    assert shell.current_key() == "run"
