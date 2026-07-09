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

import sys
import tempfile
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

from ..core.diff import diff_files, render_html

# 변경항목 리스트의 범주 라벨(core/diff._CAT_LABEL 과 동일 어휘).
_CAT_LABEL = {
    "number": "숫자",
    "clause_added": "조항추가",
    "clause_removed": "조항삭제",
    "text_changed": "문구변경",
    "text_added": "추가",
    "text_removed": "삭제",
    "table_added": "표추가",
    "table_removed": "표삭제",
    "renumber": "번호변경",
}


class DiffReviewWindow(QMainWindow):
    """판본 2개 → 변경항목 리스트 + HTML 리포트. 읽기 도구(문서를 바꾸지 않는다)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HWPX 규격서 개정 비교")
        self.resize(1100, 720)
        self.result = None          # DiffResult
        self._html: str = ""

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

        # ---- 변경항목 리스트(좌) + 리포트 뷰(우) ----
        split = QSplitter()
        self.items = QTableWidget(0, 3)
        self.items.setHorizontalHeaderLabels(["구분", "위치", "내용"])
        self.items.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
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
        self.btn_compare.setEnabled(bool(self.ed_old.text() and self.ed_new.text()))

    # ------------------------------------------------------------------ 비교
    def _on_compare(self) -> None:
        old, new = self.ed_old.text(), self.ed_new.text()
        try:
            self.result = diff_files(old, new)
        except Exception as exc:  # noqa: BLE001
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
        self.items.setRowCount(0)
        for it in self.result.change_items:
            r = self.items.rowCount()
            self.items.insertRow(r)
            cat = QTableWidgetItem(_CAT_LABEL.get(it.category, it.category))
            cat.setData(Qt.UserRole, it.order)  # 앵커 표적(Change.seq)
            self.items.setItem(r, 0, cat)
            self.items.setItem(r, 1, QTableWidgetItem(it.location_label))
            self.items.setItem(r, 2, QTableWidgetItem(it.detail))
        self.view.setHtml(self._html)
        self.btn_browser.setEnabled(True)
        self.btn_save.setEnabled(True)

    # ------------------------------------------------------------- 클릭 이동
    def _on_item_selected(self) -> None:
        row = self.items.currentRow()
        if row < 0:
            return
        seq = self.items.item(row, 0).data(Qt.UserRole)
        self.view.scrollToAnchor(f"chg-{seq}")

    # ------------------------------------------------------------- 내보내기
    def _open_in_browser(self) -> None:
        """원본 충실 뷰 — 임시 파일로 시스템 브라우저에서(임베드 뷰는 CSS 근사)."""
        if not self._html:
            return
        with tempfile.NamedTemporaryFile(
            "w", suffix=".html", delete=False, encoding="utf-8"
        ) as f:
            f.write(self._html)
        webbrowser.open(Path(f.name).as_uri())

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
