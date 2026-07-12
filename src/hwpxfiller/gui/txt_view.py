"""txt 즉시 기안 화면 — 템플릿 + 데이터 → 실시간 렌더 → 복사(Qt 얇은 렌더러).

레이어링: 결정·렌더는 :class:`~hwpxfiller.gui.txt_state.TxtDraftViewModel`(Qt 비의존, 링1)이
소유하고, 이 위젯은 QComboBox·QFileDialog·클립보드·표현만 담당한다. **실시간 view 가 진실**
(ADR C 트랙 분기): 템플릿/레코드가 바뀔 때마다 다시 렌더하고, 누락 토큰은 ``{{}}`` 를 빨강으로
남긴다(조용히 안 지움 — ADR E). 클립보드 복사가 사용자의 완료 동작이다.
"""
from __future__ import annotations

import html as _html
import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from hwpxcore.atomic import write_text_atomic

from ..core.text_registry import TextTemplateRegistry
from .file_filters import EXCEL_FILTER
from .flow_layout import FlowLayout
from .style import BASE_QSS, mark
from .txt_state import TxtDraftViewModel

_TOKEN = re.compile(r"\{\{\s*([^{}|]+?)\s*\}\}")
_STATE_LABEL = {"fill": "✓ 채움", "blank": "◦ 빈 값", "missing": "● 미입력"}
# 완료 라벨(lbl_note)의 기본 안내 — 복사/저장 전, 그리고 레코드·템플릿 전환 후 복귀 문구.
_NOTE_DEFAULT = "현재 미리보기 내용을 복사합니다. 미입력 토큰은 그대로 표시됩니다."


class TxtDraftView(QMainWindow):
    """즉시 기안 — 정해진 루트의 템플릿 선택 + 데이터 결합 + 실시간 렌더/복사."""

    back_requested = Signal()

    def __init__(self, registry: TextTemplateRegistry, parent=None):
        super().__init__(parent)
        self.vm = TxtDraftViewModel(registry)
        self.setWindowTitle("HWPX Filler — 즉시 기안")
        self.resize(880, 680)
        self.setStyleSheet(BASE_QSS)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ---- 화면 제목(heading 관례 — 최상위 표면 6곳과 동형, UD-39) ----
        head = QHBoxLayout()
        title = QLabel("즉시 기안")
        mark(title, "heading", True)
        sub = QLabel("템플릿 + 데이터를 실시간으로 채워 기안문을 복사·저장합니다.")
        mark(sub, "muted", True)
        head.addWidget(title)
        head.addWidget(sub)
        head.addStretch(1)
        root.addLayout(head)

        # ---- 컨트롤 줄: 템플릿 · 데이터 · 레코드 ----
        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("템플릿"))
        self.cbo = QComboBox()
        self.cbo.addItems(self.vm.template_names())
        self.cbo.activated.connect(self._on_template)
        ctl.addWidget(self.cbo)
        ctl.addWidget(QLabel("데이터"))
        self.ed_data = QLineEdit()
        self.ed_data.setReadOnly(True)
        ctl.addWidget(self.ed_data, 1)
        btn_data = QPushButton("데이터 선택…")
        btn_data.clicked.connect(self._pick_data)
        ctl.addWidget(btn_data)
        ctl.addWidget(QLabel("레코드"))
        self.btn_prev = QPushButton("◀")
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.lbl_idx = QLabel("0/0")
        self.btn_next = QPushButton("▶")
        self.btn_next.clicked.connect(lambda: self._step(1))
        ctl.addWidget(self.btn_prev)
        ctl.addWidget(self.lbl_idx)
        ctl.addWidget(self.btn_next)
        root.addLayout(ctl)

        # ---- 두 판: 토큰 상태 | 실시간 렌더 ----
        panes = QHBoxLayout()
        tok_box = QGroupBox("필드 상태 (토큰)")
        tb = QVBoxLayout(tok_box)
        self.tok_host = QWidget()
        self.tok_flow = FlowLayout(self.tok_host, margin=0, spacing=6)
        tb.addWidget(self.tok_host)
        tb.addStretch(1)
        tok_box.setFixedWidth(280)
        panes.addWidget(tok_box)
        view_box = QGroupBox("기안 미리보기")
        vb = QVBoxLayout(view_box)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        vb.addWidget(self.view)
        panes.addWidget(view_box, 1)
        root.addLayout(panes, 1)

        # ---- 액션 ----
        foot = QHBoxLayout()
        self.btn_copy = QPushButton("클립보드로 복사")
        mark(self.btn_copy, "primary", True)
        self.btn_copy.clicked.connect(self._copy)
        btn_save = QPushButton("텍스트 파일로 저장…")
        btn_save.clicked.connect(self._save)
        self.lbl_note = QLabel(_NOTE_DEFAULT)
        mark(self.lbl_note, "muted", True)
        self.lbl_note.setWordWrap(True)
        foot.addWidget(self.btn_copy)
        foot.addWidget(btn_save)
        foot.addWidget(self.lbl_note, 1)
        root.addLayout(foot)

        names = self.vm.template_names()
        if names:
            self.vm.select_template(names[0])
        self._render()

    def select_template(self, name: str) -> None:
        """외부(대시보드 라우팅)에서 특정 템플릿을 선택해 연다."""
        idx = self.cbo.findText(name)
        if idx >= 0:
            self.cbo.setCurrentIndex(idx)
        self.vm.select_template(name)
        self._render()

    # ------------------------------------------------------------------ 핸들러
    def _on_template(self, idx: int) -> None:
        name = self.cbo.itemText(idx)
        if name:
            self.vm.select_template(name)
        self._render()

    def _pick_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "데이터 파일 선택", "", EXCEL_FILTER
        )
        if not path:
            return
        try:
            records = self.vm.load_data(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"데이터 로드 실패:\n{exc}")
            return
        if not records:
            QMessageBox.warning(self, "확인", "레코드가 없습니다. 다른 파일을 선택하세요.")
            return
        self.ed_data.setText(path)
        self._render()

    def _step(self, delta: int) -> None:
        self.vm.step(delta)
        self._render()

    def _clear_tokens(self) -> None:
        while self.tok_flow.count():
            item = self.tok_flow.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()

    def _reset_note(self) -> None:
        """완료 라벨을 기본 안내+muted 로 되돌린다 — 레코드/템플릿 전환 후 '✓ 복사 완료'
        스테일 문구가 새 레코드에 잔존하는 것을 막는다(UD-02). level 을 해제하고 muted 로
        복귀시켜 다음 완료 동작 전까지 성공/경고 색이 남지 않게 한다."""
        mark(self.lbl_note, "level", "")   # 이전 완료 레벨(ok/warn) 해제
        mark(self.lbl_note, "muted", True)  # 기본 부차(회색) 안내로 복귀
        self.lbl_note.setText(_NOTE_DEFAULT)

    def _announce(self, report, action: str) -> None:
        """완료 동작(복사/저장) 결과를 RenderReport 로 재진술한다(UD-02).

        미입력(레코드에 없어 빨간 ``{{토큰}}`` 잔존)·빈 값을 이름으로 재진술하고, 전량
        채움일 때만 ok 성공 신호를 낸다. muted 를 해제해 level 색이 회색에 패배하지 않게
        한다(style.py 선언 순서와 이중 방어)."""
        missing = report.missing_fields
        empty = report.empty_fields
        if missing:
            level = "warn"
            text = (f"⚠ 미입력 {len(missing)}건({', '.join(missing)}) 포함 {action}됨 "
                    "— 빨간 토큰을 확인한 뒤 붙여넣으세요.")
        elif empty:
            level = "warn"
            text = (f"⚠ 빈 값 {len(empty)}건({', '.join(empty)}) 포함 {action}됨 "
                    "— 확인한 뒤 붙여넣으세요.")
        else:
            level = "ok"
            text = f"✓ 전량 채움 {action} 완료 — 필요한 곳에 붙여넣으세요."
        mark(self.lbl_note, "muted", False)  # 완료 레벨이 muted 를 이기도록 배타 해제
        mark(self.lbl_note, "level", level)
        self.lbl_note.setText(text)

    def _render(self) -> None:
        """토큰 상태 배지 + 실시간 렌더 view 를 현재 템플릿/레코드로 다시 그린다."""
        self._reset_note()
        self._clear_tokens()
        for tok in self.vm.token_states():
            chip = QLabel("{{" + tok.name + "}} · " + _STATE_LABEL[tok.state])
            mark(chip, "fb", tok.state)
            self.tok_flow.addWidget(chip)

        text, _report = self.vm.render()
        esc = _html.escape(text)

        def _hl(m: "re.Match") -> str:
            # 미충족 토큰은 빨강으로 그대로 노출(조용히 지우지 않음).
            return ('<span style="background:#fde2dd;color:#c0392b;">{{'
                    + _html.escape(m.group(1).strip()) + '}}</span>')

        esc = _TOKEN.sub(_hl, esc)
        self.view.setHtml(
            '<div style="font-family:Malgun Gothic,sans-serif;font-size:14px;'
            'line-height:1.8;white-space:pre-wrap;">' + esc + '</div>'
        )

        n = self.vm.record_count()
        self.lbl_idx.setText(f"{(self.vm.record_index % n) + 1 if n else 0}/{n}")
        self.btn_prev.setEnabled(n > 1)
        self.btn_next.setEnabled(n > 1)

    def _copy(self) -> None:
        text, report = self.vm.render()
        QApplication.clipboard().setText(text)
        self._announce(report, "복사")

    def _save(self) -> None:
        text, report = self.vm.render()
        path, _ = QFileDialog.getSaveFileName(self, "txt 저장", "기안.txt", "텍스트 (*.txt)")
        if not path:
            return
        try:
            write_text_atomic(path, text)  # 원자 쓰기(RC-01) — 실패해도 기존 파일 무손상
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"저장 실패:\n{exc}")
            return
        self._announce(report, "저장")
        if report.missing_fields or report.empty_fields:
            QMessageBox.warning(
                self, "저장",
                "기안 텍스트를 저장했습니다. 미입력/빈 값이 포함되어 있으니 확인하세요.",
            )
        else:
            QMessageBox.information(self, "저장", "기안 텍스트를 저장했습니다.")
