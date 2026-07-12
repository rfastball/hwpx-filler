"""앱 A — 규격서 개정 diff 리뷰어(별도 앱). 검토자용 단일 화면.

    python -m hwpxdiff

트랙 C UX 결정([[hwpx-filler-scope]]): diff 는 메일머지 앱(앱 B)과 **별도 앱**이다 —
별도 진입점+창+exe, `core/` 만 공유(UI 상태 공유 0).

뷰 형태(사용자 피드백으로 확정, 2026-07):
  - **신구대비표** — 원문 **전체**를 좌(구판)/우(신판) 대조로 렌더한다. 변경만 발라낸
    리포트는 본문 맥락이 날아가 diff 를 파악할 수 없었다. equal 행을 포함한 전문
    스트림은 코어가 준다(``DiffResult.rows``).
  - **변경 리스트 = 네비게이션.** 좌측 리스트는 인접 변경을 묶은 그룹 단위(파편화 완화),
    클릭하면 전문 뷰의 해당 행으로 이동(앵커 ``chg-{seq}``).
  - **필터는 종류(kind) 셋뿐** — 추가/삭제/변경. 세분 범주(숫자/조항/문구…)는 부정확해
    노이즈였다. 번호변경(renumber)은 전용 토글(기본 접힘, 개수는 노출).
  - **내보내기 없음** — 브라우저 열기/HTML 저장 제거(불필요 기능). 코어 ``render_html``
    은 CLI(diff --html)용으로만 남는다.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

# 종류 어휘·색·성형(그룹화·coalesce)·빈 상태 카피의 단일 출처는 core —
# 사본을 두면 코어의 변경이 GUI 에서 조용히 어긋난다(같은 결과가 표면마다 다르게 렌더).
from .diff import (
    KIND_COLORS,
    KIND_LABELS,
    KIND_TINTS,
    NO_CHANGES_MESSAGE,
    ChangeGroup,
    DiffResult,
    DocRow,
    WordOp,
    coalesce_word_ops,
    diff_files,
    row_group_key,
)
# 앱 B(hwpxfiller) 목업 디자인 문법 — 자립 사본(런타임 hwpxcore-only). 색 단일 출처는
# design_tokens.json(generator), 배지색 단일 출처는 core.diff.KIND_COLORS.
from .style import BASE_QSS, INK, mark

# 전문 뷰(QTextBrowser) 기본 스타일 — Qt 리치텍스트가 실제 지원하는 속성만.
# del/ins 팔레트는 core.diff(KIND_COLORS/KIND_TINTS) 단일 출처 — CLI HTML 과 동일.
_QT_VIEW_CSS = f"""
body{{font-family:'Malgun Gothic','맑은 고딕',sans-serif;font-size:13px;color:{INK};}}
del{{background-color:{KIND_TINTS["removed"]};color:{KIND_COLORS["removed"]};}}
ins{{background-color:{KIND_TINTS["added"]};color:{KIND_COLORS["added"]};text-decoration:none;}}
"""

_RECENT_KEY = "recent_pairs"
_RECENT_MAX = 5

# 필터로 전부 숨었을 때의 안내 — '진짜 변경 없음'(NO_CHANGES_MESSAGE)과 구분되는 카피.
_FILTERED_ALL_MESSAGE = "필터에 걸려 표시된 변경이 없습니다 — 종류 필터·번호변경 토글을 확인하세요."


def _visible(kind: str, enabled: "set[str]", show_renumber: bool) -> bool:
    """변경 그룹 행 표시 판정(순수 함수 — 헤드리스 테스트 표적).

    renumber 는 종류 체크가 아니라 전용 토글을 따른다 — 실질 변경과 섞지 않되
    조용히 버리지 않는 규칙의 리스트 짝.
    """
    if kind == "renumber":
        return show_renumber
    return kind in enabled


# 성형·그룹화(coalesce_word_ops·group_changes·row_group_key)는 core.diff 소유 —
# GUI 와 CLI HTML 이 같은 함수를 공유한다(RC-17: 표면 간 렌더 동등성).


# ------------------------------------------------------------- 전문 뷰 렌더
def _side_html(ops: "list[WordOp]", side: str) -> str:
    """낱말 op 를 한쪽 판본 관점으로 렌더 — 구판엔 삭제만, 신판엔 삽입만 강조."""
    out: "list[str]" = []
    for w in ops:
        if w.op == "equal":
            out.append(html.escape(w.old))
        elif side == "old" and w.op in ("delete", "replace"):
            out.append(f"<del>{html.escape(w.old)}</del>")
        elif side == "new" and w.op in ("insert", "replace"):
            out.append(f"<ins>{html.escape(w.new)}</ins>")
    return "".join(out) or "&nbsp;"


def _multiline(s: str) -> str:
    return html.escape(s).replace("\n", "<br>") or "&nbsp;"


def _render_doc_html(rows: "list[DocRow]") -> str:
    """전문 신구대비표 HTML(Qt 리치텍스트 호환) — 원문 전체 + 인라인 강조 + 앵커."""
    out: "list[str]" = ["<body>"]
    out.append("<table width='100%' cellspacing='0' cellpadding='6'>")
    out.append(
        "<tr bgcolor='#eef1f4'><td width='54'></td>"
        "<td width='47%'><font color='#4a505a'><b>구판</b></font></td>"
        "<td width='47%'><font color='#4a505a'><b>신판</b></font></td></tr>"
    )
    prev_key = None
    for r in rows:
        key = row_group_key(r.label)  # 라벨→그룹 헤더 역산은 라벨 생산자(core.diff) 소유
        if key != prev_key:
            out.append(
                f"<tr bgcolor='#f6f7f9'><td colspan='3'>"
                f"<font color='#7a7f87' size='2'><b>{html.escape(key)}</b></font></td></tr>"
            )
            prev_key = key
        anchor = f"<a name='chg-{r.seq}'></a>" if r.seq is not None else ""
        if r.kind == "equal":
            body = _multiline(r.new_text)
            out.append(f"<tr><td></td><td>{body}</td><td>{body}</td></tr>")
            continue
        color = KIND_COLORS.get(r.kind, "#555555")
        tag = (f"{anchor}<font color='{color}' size='2'>"
               f"<b>{KIND_LABELS.get(r.kind, r.kind)}</b></font>")
        if r.kind == "added":
            out.append(f"<tr><td>{tag}</td><td></td>"
                       f"<td bgcolor='{KIND_TINTS['added']}'>{_multiline(r.new_text)}</td></tr>")
        elif r.kind == "removed":
            out.append(f"<tr><td>{tag}</td>"
                       f"<td bgcolor='{KIND_TINTS['removed']}'>{_multiline(r.old_text)}</td>"
                       "<td></td></tr>")
        else:  # changed / renumber — 좌: 삭제 강조, 우: 삽입 강조
            ops = coalesce_word_ops(r.word_ops) or [
                WordOp("replace", old=r.old_text, new=r.new_text)
            ]
            old_html = _side_html(ops, "old")
            new_html = _side_html(ops, "new")
            if r.kind == "renumber":
                old_html = f"<font color='{KIND_COLORS['renumber']}'>{old_html}</font>"
                new_html = f"<font color='{KIND_COLORS['renumber']}'>{new_html}</font>"
            out.append(f"<tr><td>{tag}</td><td>{old_html}</td><td>{new_html}</td></tr>")
    out.append("</table></body>")
    return "".join(out)


class DiffReviewWindow(QMainWindow):
    """판본 2개 → 변경 그룹 리스트(좌) + 전문 신구대비표(우). 읽기 도구."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HWPX 규격서 개정 비교")
        self.resize(1280, 800)
        self.result: DiffResult | None = None
        self._html: str = ""            # 전문 뷰 HTML(무효화·테스트 표적)
        self._groups: "list[ChangeGroup]" = []
        self._settings = QSettings("hwpxdiff", "diff")  # 최근 비교(테스트에서 교체 가능)
        self.setAcceptDrops(True)  # .hwpx 드래그&드롭 투입
        self.setStyleSheet(BASE_QSS)  # 앱 B 목업 디자인 문법(카드/입력/버튼/타일) 적용

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)

        # ---- 헤더(제목 + 부제) ----
        header = QHBoxLayout()
        title = QLabel("규격서 개정 비교")
        mark(title, "heading", True)
        sub = QLabel("HWPX 신구대비 리뷰어 · 구판 ↔ 신판")
        mark(sub, "muted", True)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(sub)
        root.addLayout(header)

        # ---- 판본 선택(카드) ----
        pick_card = QFrame()
        pick_card.setProperty("card", True)
        pc = QVBoxLayout(pick_card)
        pc.setContentsMargins(14, 12, 14, 12)
        pc.setSpacing(8)
        self.ed_old = QLineEdit()
        self.ed_old.setReadOnly(True)
        self.ed_old.setPlaceholderText("구판 .hwpx 를 고르거나 여기로 끌어다 놓으세요")
        self.ed_new = QLineEdit()
        self.ed_new.setReadOnly(True)
        self.ed_new.setPlaceholderText("신판 .hwpx 를 고르거나 여기로 끌어다 놓으세요")
        btn_old = QPushButton("구판 선택…")
        btn_old.clicked.connect(lambda: self._pick(self.ed_old))
        btn_new = QPushButton("신판 선택…")
        btn_new.clicked.connect(lambda: self._pick(self.ed_new))
        self.btn_compare = QPushButton("비교")
        mark(self.btn_compare, "primary", True)
        self.btn_compare.clicked.connect(self._on_compare)
        self.btn_compare.setEnabled(False)
        self.btn_recent = QPushButton("최근 ▾")
        self._recent_menu = QMenu(self)
        self._recent_menu.aboutToShow.connect(self._populate_recent_menu)
        self.btn_recent.setMenu(self._recent_menu)

        row_old = QHBoxLayout()
        lbl_old = QLabel("구판")
        lbl_old.setFixedWidth(40)
        mark(lbl_old, "muted", True)
        row_old.addWidget(lbl_old)
        row_old.addWidget(self.ed_old, 1)
        row_old.addWidget(btn_old)
        pc.addLayout(row_old)

        row_new = QHBoxLayout()
        lbl_new = QLabel("신판")
        lbl_new.setFixedWidth(40)
        mark(lbl_new, "muted", True)
        row_new.addWidget(lbl_new)
        row_new.addWidget(self.ed_new, 1)
        row_new.addWidget(btn_new)
        pc.addLayout(row_new)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self.btn_recent)
        actions.addWidget(self.btn_compare)
        pc.addLayout(actions)
        root.addWidget(pick_card)

        # ---- 요약 KPI 타일(비교 후 노출) + 비교 전 안내 문구 ----
        self.lbl_summary = QLabel("판본 2개를 선택하고 비교를 누르세요.")
        mark(self.lbl_summary, "muted", True)
        root.addWidget(self.lbl_summary)

        self.kpi_wrap = QWidget()
        self.kpi_row = QHBoxLayout(self.kpi_wrap)
        self.kpi_row.setContentsMargins(0, 0, 0, 0)
        self.kpi_row.setSpacing(10)
        self._kpi_vals: "dict[str, QLabel]" = {}
        for kind in ("added", "removed", "changed", "renumber"):
            tile, val = self._kpi_tile(KIND_LABELS[kind], KIND_COLORS[kind])
            self._kpi_vals[kind] = val
            self.kpi_row.addWidget(tile)
        self.kpi_wrap.hide()  # 결과가 없을 땐 감춘다(가짜 0 지표 방지)
        root.addWidget(self.kpi_wrap)

        # ---- 종류 필터(고정 3종 + 번호변경 토글) ----
        srow = QHBoxLayout()
        flabel = QLabel("필터")
        mark(flabel, "subheading", True)
        srow.addWidget(flabel)
        srow.addSpacing(4)
        self._filter_checks: "dict[str, QCheckBox]" = {}
        for kind in ("added", "removed", "changed"):
            cb = QCheckBox(KIND_LABELS[kind])
            cb.setChecked(True)
            dot = QPixmap(10, 10)
            dot.fill(QColor(KIND_COLORS[kind]))
            cb.setIcon(dot)
            cb.toggled.connect(self._apply_filter)
            self._filter_checks[kind] = cb
            srow.addWidget(cb)
        srow.addStretch(1)
        self.chk_renumber = QCheckBox("번호변경 표시")
        self.chk_renumber.setChecked(False)  # 기본 접힘 — 개수는 비교 후 라벨에 노출
        self.chk_renumber.toggled.connect(self._apply_filter)
        srow.addWidget(self.chk_renumber)
        root.addLayout(srow)

        # 필터 0행 안내 — 변경은 있는데 필터가 전부 숨겼을 때만 노출('진짜 동일'과 구분).
        self.lbl_filter_notice = QLabel(_FILTERED_ALL_MESSAGE)
        mark(self.lbl_filter_notice, "muted", True)
        self.lbl_filter_notice.hide()
        root.addWidget(self.lbl_filter_notice)

        # ---- 변경 그룹 리스트(좌) + 전문 대조 뷰(우) ----
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
        self.view.document().setDefaultStyleSheet(_QT_VIEW_CSS)
        split.addWidget(self.view)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

    # ------------------------------------------------------------------ 빌더
    def _kpi_tile(self, label: str, color: str) -> "tuple[QFrame, QLabel]":
        """요약 KPI 타일(카드) — 값 라벨은 종류색, 아래 작은 라벨. 값은 _bind_result 가 채운다."""
        tile = QFrame()
        tile.setProperty("card", True)
        box = QVBoxLayout(tile)
        box.setContentsMargins(13, 10, 13, 10)
        box.setSpacing(2)
        val = QLabel("0")
        mark(val, "kpi", "value")
        val.setStyleSheet(f"color:{color};")  # 종류색(추가 초록/삭제 빨강/변경 파랑/번호 회색)
        lbl = QLabel(label)
        mark(lbl, "kpi", "label")
        box.addWidget(val)
        box.addWidget(lbl)
        return tile, val

    # ------------------------------------------------------------------ 입력
    def _pick(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "HWPX 선택", "", "HWPX (*.hwpx)")
        if path:
            edit.setText(path)
            # 판본이 바뀌면 이전 결과는 화면의 경로와 어긋난다.
            self._invalidate_result("판본이 바뀌었습니다 — 비교를 다시 누르세요.")
        self._sync_compare_button()

    def _sync_compare_button(self) -> None:
        self.btn_compare.setEnabled(bool(self.ed_old.text() and self.ed_new.text()))

    # ------------------------------------------------------------ 드래그&드롭
    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 오버라이드)
        if any(u.toLocalFile().lower().endswith(".hwpx") for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt 오버라이드)
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.toLocalFile().lower().endswith(".hwpx")]
        if paths:
            self._ingest_paths(paths)
            event.acceptProposedAction()

    def _ingest_paths(self, paths: "list[str]") -> None:
        """파일 투입(DnD·최근 목록 공용). 2개면 순서대로 구→신, 1개면 빈 칸 우선(구→신)."""
        paths = [p for p in paths if p.lower().endswith(".hwpx")]
        if not paths:
            return
        if len(paths) >= 2:
            self.ed_old.setText(paths[0])
            self.ed_new.setText(paths[1])
        elif not self.ed_old.text():
            self.ed_old.setText(paths[0])
        elif not self.ed_new.text():
            self.ed_new.setText(paths[0])
        else:
            self.ed_old.setText(paths[0])  # 둘 다 차 있으면 구판 교체(비교 방향 유지)
        self._invalidate_result("판본이 바뀌었습니다 — 비교를 다시 누르세요.")
        self._sync_compare_button()

    # ------------------------------------------------------------- 최근 비교
    def _recent_pairs(self) -> "list[tuple[str, str]]":
        try:
            raw = json.loads(self._settings.value(_RECENT_KEY, "[]"))
            return [(str(o), str(n)) for o, n in raw]
        except (ValueError, TypeError):
            return []

    def _push_recent(self, old: str, new: str) -> None:
        pairs = [(o, n) for o, n in self._recent_pairs() if (o, n) != (old, new)]
        pairs.insert(0, (old, new))
        self._settings.setValue(_RECENT_KEY, json.dumps(pairs[:_RECENT_MAX]))

    def _populate_recent_menu(self) -> None:
        self._recent_menu.clear()
        pairs = self._recent_pairs()
        if not pairs:
            act = self._recent_menu.addAction("최근 비교 없음")
            act.setEnabled(False)
            return
        for old, new in pairs:
            act = self._recent_menu.addAction(f"{Path(old).name} ↔ {Path(new).name}")
            if Path(old).exists() and Path(new).exists():
                act.triggered.connect(
                    lambda _=False, o=old, n=new: self._ingest_paths([o, n])
                )
            else:
                act.setEnabled(False)  # 파일이 사라진 항목은 고를 수 없게

    def _invalidate_result(self, message: str) -> None:
        # 사유(실패·판본 변경)는 결과 유무와 무관하게 **항상** 표시한다 — 새 창 첫 비교
        # 실패에서도 화면에 남아야 한다('지울 결과 없음' ≠ '표시할 메시지 없음', RC-31).
        self.lbl_summary.setText(message)
        self.lbl_summary.show()
        if self.result is None and not self._html:
            return  # 조기 반환은 결과 클리어에만 적용
        self.result = None
        self._html = ""
        self._groups = []
        self.items.setRowCount(0)
        self.view.clear()
        self.chk_renumber.setText("번호변경 표시")
        self.kpi_wrap.hide()  # 결과 없음 → KPI 감추고 안내 문구 노출
        self.lbl_filter_notice.hide()

    # ------------------------------------------------------------------ 비교
    def _on_compare(self) -> None:
        old, new = self.ed_old.text(), self.ed_new.text()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.result = diff_files(old, new)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()  # 모달 뜨기 전에 커서 복원
            self._invalidate_result("비교 실패 — 판본을 확인하고 다시 시도하세요.")
            QMessageBox.critical(self, "오류", f"비교 실패:\n{exc}")
            return
        QApplication.restoreOverrideCursor()
        self._push_recent(old, new)
        self._html = _render_doc_html(self.result.rows)
        self._bind_result()

    def _bind_result(self) -> None:
        s = self.result.summary
        for kind, val in self._kpi_vals.items():
            val.setText(str(s.get(kind, 0)))
        if self.result.changes:
            self.lbl_summary.hide()   # 카운트는 이제 KPI 타일이 보여준다
        else:
            # 0건은 검토 결론이다 — KPI 0 나열이 아니라 확정 문장으로 남긴다(카피는
            # CLI 요약·HTML 리포트와 공유, RC-32).
            self.lbl_summary.setText(NO_CHANGES_MESSAGE)
            self.lbl_summary.show()
        self.kpi_wrap.show()
        n_renumber = s.get("renumber", 0)
        self.chk_renumber.setText(
            f"번호변경 {n_renumber}건 표시" if n_renumber else "번호변경 표시"
        )
        # 그룹화는 core 소유(rows 스트림 인접 기준) — seq 연속은 문서 인접이 아니다.
        self._groups = self.result.change_groups
        self.items.setRowCount(len(self._groups))
        for r, g in enumerate(self._groups):
            cell = QTableWidgetItem(KIND_LABELS.get(g.kind, g.kind))
            cell.setData(Qt.UserRole, g.seqs[0])  # 앵커 표적(첫 변경의 seq)
            cell.setBackground(QColor(KIND_COLORS.get(g.kind, "#555555")))
            cell.setForeground(QColor("#ffffff"))
            cell.setTextAlignment(Qt.AlignCenter)
            self.items.setItem(r, 0, cell)
            self.items.setItem(r, 1, QTableWidgetItem(g.label))
            self.items.setItem(r, 2, QTableWidgetItem(g.detail))
        self.view.setHtml(self._html)
        self._apply_filter()

    # ------------------------------------------------------------------ 필터
    def _apply_filter(self) -> None:
        if self.result is None:
            return
        enabled = {k for k, cb in self._filter_checks.items() if cb.isChecked()}
        show_renumber = self.chk_renumber.isChecked()
        n_visible = 0
        for r, g in enumerate(self._groups):
            visible = _visible(g.kind, enabled, show_renumber)
            self.items.setRowHidden(r, not visible)
            n_visible += visible
        # 변경이 있는데 필터가 전부 숨겼으면 말없이 빈 리스트로 두지 않는다(RC-32).
        self.lbl_filter_notice.setVisible(bool(self._groups) and n_visible == 0)

    # ------------------------------------------------------------- 클릭 이동
    def _on_item_selected(self) -> None:
        row = self.items.currentRow()
        if row < 0:
            return
        seq = self.items.item(row, 0).data(Qt.UserRole)
        self.view.scrollToAnchor(f"chg-{seq}")


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    win = DiffReviewWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
