"""템플릿 관리 워크숍 — 특정 Job 밖의 템플릿 라이브러리 관리면(얇은 렌더러).

레이어링: 위젯은 얇은 렌더러 — 상태 판정·상태별 게이트 액션·2단계 fieldize(스캔→적용)·
lint/drift 는 전부 :class:`~hwpxfiller.gui.template_manager_state.TemplateManagerViewModel`
(Qt 비의존, 링1)이 소유. 이 위젯은 행을 카드로 얹고 상태별 버튼을 배선한다.

- 템플릿 목록: compile_status 배지 + 필드 수 + 스킵/잔존 상세.
- 상태 게이트 버튼: RAW=[컴파일] · PARTIAL=[마저 컴파일][검토] · COMPILED=[미리보기][작업 만들기]
  · FILLED=[미리보기].
- fieldize: 스캔 미리보기(dry-run) → 명시적 적용(확인 시에만 변환·저장) — CLI 2단계 미러.
- lint / drift 결과 표시.

라우팅: :class:`~hwpxfiller.gui.app._AppController` 가 이 패널의 수명을 소유하고
``make_job_requested`` 시그널을 에디터로 연결한다(홈은 건드리지 않는다 — C5 스코프).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .style import BASE_QSS, mark
from .template_manager_state import TemplateManagerViewModel, TemplateRow


class _TemplateCard(QWidget):
    """템플릿 1건 카드 — 이름 + 상태 배지 + 상세 + 상태별 게이트 액션 버튼.

    성형된 :class:`TemplateRow` 와 액션 디스패처만 받는다(코어 직접 접근 없음).
    """

    def __init__(self, row: TemplateRow, on_action, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(3)

        name_row = QHBoxLayout()
        lbl_name = QLabel(row.name)
        mark(lbl_name, "heading", True)
        name_row.addWidget(lbl_name)
        badge = QLabel(row.badge_label)
        mark(badge, "level", row.badge_level)
        name_row.addWidget(badge)
        name_row.addStretch(1)
        root.addLayout(name_row)

        lbl_meta = QLabel(row.detail_line())
        mark(lbl_meta, "muted", True)
        lbl_meta.setWordWrap(True)
        root.addWidget(lbl_meta)

        foot = QHBoxLayout()
        foot.addStretch(1)
        for act in row.actions():
            btn = QPushButton(act.label)
            if act.key in ("compile", "make_job"):
                mark(btn, "primary", True)
            btn.clicked.connect(
                lambda _checked=False, k=act.key: on_action(k, row.path)
            )
            foot.addWidget(btn)
        root.addLayout(foot)


class TemplateManagerPanel(QMainWindow):
    """템플릿 라이브러리 워크숍. :class:`TemplateManagerViewModel` 을 렌더한다."""

    make_job_requested = Signal(str)  # 템플릿 경로 → 에디터로(app.py 가 연결)

    def __init__(self, library_dir=None, parent=None):
        super().__init__(parent)
        self.vm = TemplateManagerViewModel(library_dir)

        self.setWindowTitle("HWPX Filler — 템플릿 관리")
        self.resize(720, 560)
        self.setStyleSheet(BASE_QSS)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        title = QLabel("템플릿 관리")
        mark(title, "heading", True)
        self.lbl_count = QLabel("")
        mark(self.lbl_count, "muted", True)
        header.addWidget(title)
        header.addWidget(self.lbl_count)
        header.addStretch(1)
        self.btn_drift = QPushButton("판본 비교(드리프트)")
        self.btn_drift.clicked.connect(self._on_drift)
        header.addWidget(self.btn_drift)
        root.addLayout(header)

        self.list = QListWidget()
        self.list.setObjectName("jobList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.list, 1)

        self.lbl_result = QLabel("")
        self.lbl_result.setWordWrap(True)
        mark(self.lbl_result, "muted", True)
        root.addWidget(self.lbl_result)

        self.vm.subscribe(self._render)
        self._render()

    # ------------------------------------------------------------- 렌더
    def refresh(self) -> None:
        self.vm.refresh()

    def _render(self) -> None:
        self.lbl_count.setText(self.vm.count_label())
        self.list.clear()
        for row in self.vm.rows():
            self.list.addItem(row.name)
            item = self.list.item(self.list.count() - 1)
            item.setForeground(QColor(0, 0, 0, 0))  # 이름은 아이템 text, 표시는 카드
            card = _TemplateCard(row, on_action=self._dispatch)
            item.setSizeHint(card.sizeHint())
            self.list.setItemWidget(item, card)

    # ---------------------------------------------------- 액션 디스패치
    def _dispatch(self, key: str, path: str) -> None:
        if key == "compile":
            self._on_compile(path)
        elif key == "review":
            self._on_review(path)
        elif key == "preview":
            self._on_preview(path)
        elif key == "make_job":
            self.make_job_requested.emit(path)

    def _on_compile(self, path: str) -> None:
        """CLI 2단계 미러 — 스캔 미리보기(dry-run) → 사용자 확인 시에만 적용·저장."""
        preview = self.vm.scan_preview(path)
        lines = [preview.summary(), ""]
        for s in preview.compilable:
            lines.append(f"+ {s.name}")
        for s in preview.skipped:
            lines.append(f"! {s.name} — {s.reason}")
        if not preview.has_compilable:
            lines.append("\n컴파일 가능한 토큰이 없습니다.")
            QMessageBox.information(self, "fieldize 미리보기", "\n".join(lines))
            return
        lines.append("\n지금 컴파일할까요? (파일이 변경됩니다)")
        if QMessageBox.question(
            self, "fieldize 미리보기 → 적용", "\n".join(lines)
        ) != QMessageBox.Yes:
            return  # dry-run 만 — 확인 없으면 변형 없음
        report = self.vm.apply_fieldize(path)
        self.lbl_result.setText(f"컴파일 완료: 필드 {len(report.compiled)}개 추가")

    def _on_review(self, path: str) -> None:
        report = self.vm.lint(path)
        if not report.findings:
            self.lbl_result.setText("검토: 이슈 없음.")
            return
        self.lbl_result.setText(
            "검토 결과:\n"
            + "\n".join(f"[{f.severity}] {f.message}" for f in report.findings)
        )

    def _on_preview(self, path: str) -> None:
        values = self.vm.filled_values(path)
        if not values:
            self.lbl_result.setText("미리보기: 누름틀 값이 없습니다.")
            return
        self.lbl_result.setText(
            "미리보기:\n" + "\n".join(f"{k} = {v}" for k, v in values.items())
        )

    def _on_drift(self) -> None:
        old, _ = QFileDialog.getOpenFileName(self, "이전 판본 HWPX", "", "HWPX (*.hwpx)")
        if not old:
            return
        new, _ = QFileDialog.getOpenFileName(self, "새 판본 HWPX", "", "HWPX (*.hwpx)")
        if not new:
            return
        drift = self.vm.drift(old, new)
        if not drift.has_changes:
            self.lbl_result.setText("드리프트: 필드셋 변화 없음.")
            return
        parts = []
        for n in drift.added:
            parts.append(f"+ 추가: {n}")
        for n in drift.removed:
            parts.append(f"- 삭제: {n}")
        for r in drift.renamed:
            parts.append(f"~ 개명(추정): {r['old']} → {r['new']} ({r['score']})")
        self.lbl_result.setText("드리프트:\n" + "\n".join(parts))
