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
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
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

# 종류 어휘·색의 단일 출처는 core — 사본을 두면 코어의 어휘 변경이 GUI 에서 어긋난다.
from .diff import (
    KIND_COLORS,
    KIND_LABELS,
    Change,
    DiffResult,
    DocRow,
    WordOp,
    diff_files,
)

# 전문 뷰(QTextBrowser) 기본 스타일 — Qt 리치텍스트가 실제 지원하는 속성만.
_QT_VIEW_CSS = """
body{font-family:'Malgun Gothic','맑은 고딕',sans-serif;font-size:13px;color:#1b1b1b;}
del{background-color:#ffd9d9;color:#a61b1b;}
ins{background-color:#c9f2d0;color:#12681f;text-decoration:none;}
"""

_RECENT_KEY = "recent_pairs"
_RECENT_MAX = 5

# 낱말 diff 파편화 완화 — 변경 사이에 낀 이 길이 미만의 equal 조각은 양옆 변경에
# 흡수한다("제3조→제4조"의 '조' 같은 한두 글자가 del/ins 를 잘게 쪼개 붙이는 문제).
_COALESCE_MIN_EQUAL = 3


def _visible(kind: str, enabled: "set[str]", show_renumber: bool) -> bool:
    """변경 그룹 행 표시 판정(순수 함수 — 헤드리스 테스트 표적).

    renumber 는 종류 체크가 아니라 전용 토글을 따른다 — 실질 변경과 섞지 않되
    조용히 버리지 않는 규칙의 리스트 짝.
    """
    if kind == "renumber":
        return show_renumber
    return kind in enabled


def _coalesce_ops(ops: "list[WordOp] | None") -> "list[WordOp] | None":
    """변경 사이의 짧은 equal 조각을 replace 로 흡수 — 인라인 강조 가독성.

    공백뿐인 equal 은 낱말 경계라 남긴다(흡수하면 별개 낱말 변경이 한 덩어리로 뭉개짐).
    """
    if not ops:
        return ops
    out: "list[WordOp]" = []
    i = 0
    while i < len(ops):
        op = ops[i]
        if (op.op == "equal" and op.old.strip()
                and len(op.old) < _COALESCE_MIN_EQUAL
                and out and out[-1].op != "equal"
                and i + 1 < len(ops) and ops[i + 1].op != "equal"):
            prev = out.pop()
            nxt = ops[i + 1]
            out.append(WordOp(
                "replace",
                old=prev.old + op.old + nxt.old,
                new=prev.new + op.old + nxt.new,
            ))
            i += 2
            continue
        out.append(op)
        i += 1
    return out


@dataclass
class _ChangeGroup:
    """리스트 1행 = 인접 변경 묶음. 점프 표적은 첫 변경의 seq."""

    kind: str
    label: str
    detail: str
    seqs: "list[int]" = field(default_factory=list)


def _snippet(text: str, limit: int = 60) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _group_changes(changes: "list[Change]") -> "list[_ChangeGroup]":
    """seq 연속 + 같은 종류의 변경을 한 그룹으로(파편화 완화, 순수 함수).

    diff 는 문단 하나가 여러 조각으로 갈릴 때 인접 seq 로 연달아 방출한다 —
    리뷰어에게 그건 한 건의 변경이다.
    """
    groups: "list[_ChangeGroup]" = []
    for c in changes:
        if groups and c.kind == groups[-1].kind and c.seq == groups[-1].seqs[-1] + 1:
            groups[-1].seqs.append(c.seq)
            continue
        detail = _snippet(c.new_text or c.old_text)
        groups.append(_ChangeGroup(c.kind, c.location_label, detail, [c.seq]))
    for g in groups:
        if len(g.seqs) > 1:
            g.detail += f"  (연속 {len(g.seqs)}건)"
    return groups


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


def _row_group_key(label: str) -> str:
    """행 라벨 → 소속 그룹 헤더(마지막 단위 조각 제거).

    "본문 1 · 문단 12" → "본문 1", "본문 1 · 표 2 · 셀(3,4)" → "본문 1 · 표 2".
    """
    parts = label.split(" · ")
    return " · ".join(parts[:-1]) if len(parts) > 1 else label


def _render_doc_html(rows: "list[DocRow]") -> str:
    """전문 신구대비표 HTML(Qt 리치텍스트 호환) — 원문 전체 + 인라인 강조 + 앵커."""
    out: "list[str]" = ["<body>"]
    out.append("<table width='100%' cellspacing='0' cellpadding='6'>")
    out.append(
        "<tr bgcolor='#dfe3e8'><td width='54'></td>"
        "<td width='47%'><b>구판</b></td><td width='47%'><b>신판</b></td></tr>"
    )
    prev_key = None
    for r in rows:
        key = _row_group_key(r.label)
        if key != prev_key:
            out.append(
                f"<tr bgcolor='#eef0f3'><td colspan='3'>"
                f"<font color='#555555' size='2'><b>{html.escape(key)}</b></font></td></tr>"
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
                       f"<td bgcolor='#e9f7ee'>{_multiline(r.new_text)}</td></tr>")
        elif r.kind == "removed":
            out.append(f"<tr><td>{tag}</td>"
                       f"<td bgcolor='#fdecec'>{_multiline(r.old_text)}</td><td></td></tr>")
        else:  # changed / renumber — 좌: 삭제 강조, 우: 삽입 강조
            ops = _coalesce_ops(r.word_ops) or [
                WordOp("replace", old=r.old_text, new=r.new_text)
            ]
            old_html = _side_html(ops, "old")
            new_html = _side_html(ops, "new")
            if r.kind == "renumber":
                old_html = f"<font color='#7a7f87'>{old_html}</font>"
                new_html = f"<font color='#7a7f87'>{new_html}</font>"
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
        self._groups: "list[_ChangeGroup]" = []
        self._settings = QSettings("hwpxdiff", "diff")  # 최근 비교(테스트에서 교체 가능)
        self.setAcceptDrops(True)  # .hwpx 드래그&드롭 투입

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
        self.btn_recent = QPushButton("최근 ▾")
        self._recent_menu = QMenu(self)
        self._recent_menu.aboutToShow.connect(self._populate_recent_menu)
        self.btn_recent.setMenu(self._recent_menu)
        picks.addWidget(QLabel("구판(.hwpx)"))
        picks.addWidget(self.ed_old, 1)
        picks.addWidget(btn_old)
        picks.addSpacing(12)
        picks.addWidget(QLabel("신판(.hwpx)"))
        picks.addWidget(self.ed_new, 1)
        picks.addWidget(btn_new)
        picks.addWidget(self.btn_recent)
        picks.addWidget(self.btn_compare)
        root.addLayout(picks)

        # ---- 요약 + 종류 필터(고정 3종 + 번호변경 토글) ----
        srow = QHBoxLayout()
        self.lbl_summary = QLabel("판본 2개를 선택하고 비교를 누르세요.")
        srow.addWidget(self.lbl_summary, 1)
        srow.addWidget(QLabel("필터:"))
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
        self.chk_renumber = QCheckBox("번호변경 표시")
        self.chk_renumber.setChecked(False)  # 기본 접힘 — 개수는 비교 후 라벨에 노출
        self.chk_renumber.toggled.connect(self._apply_filter)
        srow.addSpacing(8)
        srow.addWidget(self.chk_renumber)
        root.addLayout(srow)

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
        if self.result is None and not self._html:
            return
        self.result = None
        self._html = ""
        self._groups = []
        self.items.setRowCount(0)
        self.view.clear()
        self.chk_renumber.setText("번호변경 표시")
        self.lbl_summary.setText(message)

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
        self.lbl_summary.setText(
            f"추가 {s.get('added', 0)} · 삭제 {s.get('removed', 0)} · "
            f"변경 {s.get('changed', 0)} · 번호변경 {s.get('renumber', 0)}"
        )
        n_renumber = s.get("renumber", 0)
        self.chk_renumber.setText(
            f"번호변경 {n_renumber}건 표시" if n_renumber else "번호변경 표시"
        )
        self._groups = _group_changes(self.result.changes)
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
        for r, g in enumerate(self._groups):
            self.items.setRowHidden(r, not _visible(g.kind, enabled, show_renumber))

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
