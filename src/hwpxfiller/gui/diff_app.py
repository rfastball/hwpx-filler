"""앱 A — 규격서 개정 diff 리뷰어(별도 앱). 검토자용 단일 화면.

    python -m hwpxfiller.gui.diff_app

트랙 C UX 결정([[hwpx-filler-scope]]): diff 는 메일머지 앱(앱 B)과 **별도 앱**이다 —
별도 진입점+창+exe, `core/` 만 공유(UI 상태 공유 0). 상호작용 형태가 근본 다르다
(위저드=쓰기 도구 vs 이것=읽기 도구) + 독립 상품성.

단일 화면: 판본 2개 선택 → 비교 → **변경항목 리스트(좌) + 색상 HTML 리포트(우), 클릭
이동**(`ChangeItem.order` == `Change.seq` → 앵커 ``chg-{seq}``). 임베드 뷰(QTextBrowser)는
리치텍스트 한계로 CSS 가 근사 렌더라, 원본 충실 뷰는 「브라우저에서 열기」로 제공한다.

**스캐폴드 범위:** 배선까지만(리스트·뷰·이동·저장). 배지 색·레이아웃·필터(범주별)·
번호변경 접기 토글 등 폴리시는 후속 디자인 패스의 몫이다. diff 는 실코퍼스 기준 ~30ms 라
동기 실행(대형 문서용 워커 스레드는 후일 옵션).
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

# 범주 어휘·배지색의 단일 출처는 core — 사본을 두면 코어의 범주 추가가 GUI 에서
# 조용히 누락된다(영문 키 노출·색 어긋남).
from ..core.diff import CATEGORY_COLORS, CATEGORY_LABELS, DiffResult, diff_files, render_html

# QTextBrowser 는 id= 앵커 해석이 불안정해 <a name> 이 필요하다. 코어 render_html 은
# 브라우저 기준을 유지하고(핸드오프 §8), Qt 호환 마크업은 여기 뷰 측에서 주입한다.
_ANCHOR_ID_RE = re.compile(r"id='(chg-\d+)'>")


def _qt_html(html_text: str) -> str:
    return _ANCHOR_ID_RE.sub(lambda m: f"{m.group(0)}<a name='{m.group(1)}'></a>", html_text)


def _visible(category: str, enabled: "set[str]", show_renumber: bool) -> bool:
    """변경항목 행 표시 판정(순수 함수 — 헤드리스 테스트 표적).

    renumber 는 범주 체크가 아니라 전용 토글을 따른다 — HTML 리포트가 재번호를
    실질 변경과 섞지 않되(기본 접힘) 조용히 버리지 않는 규칙의 리스트 짝.
    """
    if category == "renumber":
        return show_renumber
    return category in enabled


class DiffReviewWindow(QMainWindow):
    """판본 2개 → 변경항목 리스트 + HTML 리포트. 읽기 도구(문서를 바꾸지 않는다)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HWPX 규격서 개정 비교")
        self.resize(1100, 720)
        self.result: DiffResult | None = None
        self._html: str = ""
        self._browser_tmp: Path | None = None  # 「브라우저에서 열기」 재사용 임시파일

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ---- 판본 선택 ----
        picks = QHBoxLayout()
        self.ed_old = QLineEdit()
        self.ed_old.setReadOnly(True)
        self.ed_new = QLineEdit()
        self.ed_new.setReadOnly(True)
        btn_old = QPushButton("구판…")
        btn_old.clicked.connect(lambda: self._pick(self.ed_old))
        btn_new = QPushButton("신판…")
        btn_new.clicked.connect(lambda: self._pick(self.ed_new))
        self.btn_compare = QPushButton("비교")
        self.btn_compare.clicked.connect(self._on_compare)
        self.btn_compare.setEnabled(False)
        picks.addWidget(QLabel("구판(.hwpx)"))
        picks.addWidget(self.ed_old, 1)
        picks.addWidget(btn_old)
        picks.addSpacing(12)
        picks.addWidget(QLabel("신판(.hwpx)"))
        picks.addWidget(self.ed_new, 1)
        picks.addWidget(btn_new)
        picks.addWidget(self.btn_compare)
        root.addLayout(picks)

        # ---- 요약 + 액션 ----
        srow = QHBoxLayout()
        self.lbl_summary = QLabel("판본 2개를 선택하고 비교를 누르세요.")
        self.btn_browser = QPushButton("브라우저에서 열기")
        self.btn_browser.clicked.connect(self._open_in_browser)
        self.btn_browser.setEnabled(False)
        self.btn_save = QPushButton("HTML 저장…")
        self.btn_save.clicked.connect(self._save_html)
        self.btn_save.setEnabled(False)
        srow.addWidget(self.lbl_summary, 1)
        srow.addWidget(self.btn_browser)
        srow.addWidget(self.btn_save)
        root.addLayout(srow)

        # ---- 범주 필터 바(비교 결과에 실재하는 범주만 동적 생성) ----
        self.filter_bar = QHBoxLayout()
        self._filter_checks: "dict[str, QCheckBox]" = {}
        self.chk_renumber: "QCheckBox | None" = None
        root.addLayout(self.filter_bar)

        # ---- 변경항목 리스트(좌) + 리포트 뷰(우) ----
        split = QSplitter()
        self.items = QTableWidget(0, 3)
        self.items.setHorizontalHeaderLabels(["구분", "위치", "내용"])
        self.items.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.items.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.items.verticalHeader().setVisible(False)
        self.items.setAlternatingRowColors(True)
        self.items.setSelectionBehavior(QTableWidget.SelectRows)
        self.items.setEditTriggers(QTableWidget.NoEditTriggers)
        self.items.itemSelectionChanged.connect(self._on_item_selected)
        split.addWidget(self.items)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        split.addWidget(self.view)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)

    # ------------------------------------------------------------------ 입력
    def _pick(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "HWPX 선택", "", "HWPX (*.hwpx)")
        if path:
            edit.setText(path)
            # 판본이 바뀌면 이전 결과는 화면의 경로와 어긋난다 — 내보내기 오발송 방지.
            self._invalidate_result("판본이 바뀌었습니다 — 비교를 다시 누르세요.")
        self.btn_compare.setEnabled(bool(self.ed_old.text() and self.ed_new.text()))

    def _invalidate_result(self, message: str) -> None:
        if self.result is None and not self._html:
            return
        self.result = None
        self._html = ""
        self.items.setRowCount(0)
        self.view.clear()
        self._clear_filter_bar()
        self.btn_browser.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.lbl_summary.setText(message)

    # ------------------------------------------------------------------ 비교
    def _on_compare(self) -> None:
        old, new = self.ed_old.text(), self.ed_new.text()
        try:
            self.result = diff_files(old, new)
        except Exception as exc:  # noqa: BLE001
            self._invalidate_result("비교 실패 — 판본을 확인하고 다시 시도하세요.")
            QMessageBox.critical(self, "오류", f"비교 실패:\n{exc}")
            return
        self._html = render_html(self.result)
        self._bind_result()

    def _bind_result(self) -> None:
        s = self.result.summary
        self.lbl_summary.setText(
            f"추가 {s.get('added', 0)} · 삭제 {s.get('removed', 0)} · "
            f"변경 {s.get('changed', 0)} · 번호변경 {s.get('renumber', 0)} · "
            f"변경항목 {len(self.result.change_items)}"
        )
        self.items.setRowCount(len(self.result.change_items))
        muted = QColor(CATEGORY_COLORS["renumber"])
        for r, it in enumerate(self.result.change_items):
            cat = QTableWidgetItem(CATEGORY_LABELS.get(it.category, it.category))
            cat.setData(Qt.UserRole, it.order)  # 앵커 표적(Change.seq)
            # 배지색 = HTML 리포트의 .b-{category} 와 동일(코어 팔레트 단일 출처).
            if it.category in CATEGORY_COLORS:
                cat.setBackground(QColor(CATEGORY_COLORS[it.category]))
                cat.setForeground(QColor("#ffffff"))
            cat.setTextAlignment(Qt.AlignCenter)
            loc = QTableWidgetItem(it.location_label)
            det = QTableWidgetItem(it.detail)
            if it.category == "renumber":
                # 리포트의 .renumber-group{opacity:.72} 짝 — 실질 변경과 섞지 않는다.
                loc.setForeground(muted)
                det.setForeground(muted)
            self.items.setItem(r, 0, cat)
            self.items.setItem(r, 1, loc)
            self.items.setItem(r, 2, det)
        self.view.setHtml(_qt_html(self._html))
        self._rebuild_filter_bar()
        self._apply_filter()
        self.btn_browser.setEnabled(True)
        self.btn_save.setEnabled(True)

    # ------------------------------------------------------------------ 필터
    def _clear_filter_bar(self) -> None:
        while self.filter_bar.count():
            item = self.filter_bar.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._filter_checks = {}
        self.chk_renumber = None

    def _rebuild_filter_bar(self) -> None:
        """비교 결과에 실재하는 범주만 체크박스로(기본 켬). renumber 는 전용 토글(기본 끔)."""
        self._clear_filter_bar()
        cats: "dict[str, None]" = {}  # 등장순 중복제거
        n_renumber = 0
        for it in self.result.change_items:
            if it.category == "renumber":
                n_renumber += 1
            else:
                cats.setdefault(it.category, None)
        if not cats and not n_renumber:
            return
        self.filter_bar.addWidget(QLabel("필터:"))
        for cat in cats:
            cb = QCheckBox(CATEGORY_LABELS.get(cat, cat))
            cb.setChecked(True)
            # 배지색 점 아이콘 — 리스트 배지·리포트와 같은 팔레트.
            if cat in CATEGORY_COLORS:
                dot = QPixmap(10, 10)
                dot.fill(QColor(CATEGORY_COLORS[cat]))
                cb.setIcon(dot)
            cb.toggled.connect(self._apply_filter)
            self._filter_checks[cat] = cb
            self.filter_bar.addWidget(cb)
        if n_renumber:
            self.chk_renumber = QCheckBox(f"번호변경 {n_renumber}건 표시")
            self.chk_renumber.setChecked(False)  # 기본 접힘 — 개수는 항상 노출
            self.chk_renumber.toggled.connect(self._apply_filter)
            self.filter_bar.addSpacing(12)
            self.filter_bar.addWidget(self.chk_renumber)
        self.filter_bar.addStretch(1)

    def _apply_filter(self) -> None:
        if self.result is None:
            return
        enabled = {c for c, cb in self._filter_checks.items() if cb.isChecked()}
        show_renumber = self.chk_renumber is not None and self.chk_renumber.isChecked()
        for r, it in enumerate(self.result.change_items):
            self.items.setRowHidden(r, not _visible(it.category, enabled, show_renumber))

    # ------------------------------------------------------------- 클릭 이동
    def _on_item_selected(self) -> None:
        row = self.items.currentRow()
        if row < 0:
            return
        seq = self.items.item(row, 0).data(Qt.UserRole)
        self.view.scrollToAnchor(f"chg-{seq}")

    # ------------------------------------------------------------- 내보내기
    def _open_in_browser(self) -> None:
        """원본 충실 뷰 — 임시 파일로 시스템 브라우저에서(임베드 뷰는 CSS 근사).

        클릭마다 새 파일을 만들면 %TEMP% 에 규격서 본문이 무한 누적된다 —
        창당 파일 1개를 재사용하고 창 닫힐 때 지운다.
        """
        if not self._html:
            return
        if self._browser_tmp is None:
            fd, name = tempfile.mkstemp(suffix=".html")
            os.close(fd)
            self._browser_tmp = Path(name)
        self._browser_tmp.write_text(self._html, encoding="utf-8")
        webbrowser.open(self._browser_tmp.as_uri())

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 오버라이드)
        if self._browser_tmp is not None:
            try:
                self._browser_tmp.unlink(missing_ok=True)
            except OSError:
                pass  # 브라우저가 잡고 있으면 다음 부팅 정리에 맡긴다
        super().closeEvent(event)

    def _save_html(self) -> None:
        if not self._html:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "HTML 리포트 저장", "규격서_개정_diff.html", "HTML (*.html)"
        )
        if not path:
            return
        try:
            Path(path).write_text(self._html, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"저장 실패:\n{exc}")


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    win = DiffReviewWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
