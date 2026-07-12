"""템플릿 관리 워크숍 — 특정 Job 밖의 템플릿 라이브러리 관리면(얇은 렌더러).

레이어링: 위젯은 얇은 렌더러 — 상태 판정·상태별 게이트 액션·2단계 fieldize(스캔→적용)·
lint/drift 는 전부 :class:`~hwpxfiller.gui.template_manager_state.TemplateManagerViewModel`
(Qt 비의존, 링1)이 소유. 이 위젯은 행을 카드로 얹고 상태별 버튼을 배선한다.

- 템플릿 목록: compile_status 배지 + 필드 수 + 스킵/잔존 상세.
- 상태 게이트 버튼: RAW=[컴파일] · PARTIAL=[마저 컴파일][검토] · COMPILED=[미리보기][작업 만들기]
  · FILLED=[미리보기].
- fieldize: 스캔 미리보기(dry-run) → 명시적 적용(확인 시에만 변환·저장) — CLI 2단계 미러.
- lint / drift 결과 표시.

라우팅: 홈 헤더 [템플릿 관리] 버튼 → ``manage_templates_requested`` →
:class:`~hwpxfiller.gui.app._AppController` 가 이 패널을 열고 수명을 소유하며
``make_job_requested`` 시그널을 에디터로 연결한다(RC-04 로 홈 진입점 착지).
"""

from __future__ import annotations

from pathlib import Path

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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .confirm import confirm_destructive
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
        if library_dir is None:
            # 홈의 기본 레지스트리 주입 관례 미러(RC-14) — 진입점이 폴더를 안 넘겨도
            # 백지가 아니라 표준 라이브러리(~/.hwpxfiller/templates)를 겨눈다.
            from ..core.template_status import default_templates_dir

            library_dir = default_templates_dir()
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
        self.btn_dir = QPushButton("폴더 선택")
        self.btn_dir.clicked.connect(self._on_choose_dir)
        header.addWidget(self.btn_dir)
        self.btn_drift = QPushButton("판본 비교(드리프트)")
        self.btn_drift.clicked.connect(self._on_drift)
        header.addWidget(self.btn_drift)
        root.addLayout(header)

        self.stack = QStackedWidget()
        self.list = QListWidget()
        self.list.setObjectName("jobList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stack.addWidget(self.list)                    # 0 = 목록
        self.stack.addWidget(self._build_empty_state())    # 1 = 빈 상태(홈 패턴 미러)
        root.addWidget(self.stack, 1)

        self.lbl_result = QLabel("")
        self.lbl_result.setWordWrap(True)
        mark(self.lbl_result, "muted", True)
        root.addWidget(self.lbl_result)

        self.vm.subscribe(self._render)
        self._render()

    # ------------------------------------------------------------- 빌더
    def _build_empty_state(self) -> QWidget:
        """빈 라이브러리 안내 — 백지 대신 원인(폴더 없음/빈 폴더)과 폴더 선택 유도(RC-14)."""
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.addStretch(2)
        lbl = QLabel("표시할 템플릿이 없습니다")
        mark(lbl, "heading", True)
        lbl.setAlignment(Qt.AlignCenter)
        self.lbl_empty_hint = QLabel("")
        mark(self.lbl_empty_hint, "muted", True)
        self.lbl_empty_hint.setAlignment(Qt.AlignCenter)
        self.lbl_empty_hint.setWordWrap(True)
        self.btn_empty_dir = QPushButton("폴더 선택")
        mark(self.btn_empty_dir, "primary", True)
        self.btn_empty_dir.clicked.connect(self._on_choose_dir)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_empty_dir)
        row.addStretch(1)
        box.addWidget(lbl)
        box.addWidget(self.lbl_empty_hint)
        box.addLayout(row)
        box.addStretch(3)
        return panel

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
        if self.vm.is_empty():
            self.lbl_empty_hint.setText(self.vm.empty_hint())
            self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(0)

    def _on_choose_dir(self) -> None:
        start = str(self.vm.library_dir) if self.vm.library_dir is not None else ""
        chosen = QFileDialog.getExistingDirectory(self, "템플릿 라이브러리 폴더", start)
        if not chosen:
            return
        self.lbl_result.setText("")  # 폴더가 바뀌면 직전 결과는 무의미(스테일 방지)
        self.vm.set_library_dir(chosen)

    # ---------------------------------------------------- 액션 디스패치
    def _dispatch(self, key: str, path: str) -> None:
        if key == "compile":
            self._run_action("컴파일", path, lambda: self._on_compile(path))
        elif key == "review":
            self._run_action("검토", path, lambda: self._on_review(path))
        elif key == "preview":
            self._run_action("미리보기", path, lambda: self._on_preview(path))
        elif key == "make_job":
            self.make_job_requested.emit(path)

    def _run_action(self, title: str, path: "str | None", fn) -> None:
        """액션 공통 예외 경계(RC-14) — 시작 시 스테일 결과부터 무효화하고, 실패는
        모달 + '실패: …' 라벨로 시끄럽게 남긴다(확인-또는-경보).

        슬롯에서 이탈한 예외는 PySide6 가 stderr 인쇄 후 삼키며 windowed exe 엔
        stderr 조차 없다 — 직전 성공 문구가 실패한 작업 밑에 남아 적극 오도하던
        침묵 실패를 여기서 끊는다.
        """
        self.lbl_result.setText("")  # 직전 결과 잔존 = 실패를 성공처럼 보이게 하는 오도
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — 액션 시점 실패는 전부 통지 대상
            name = Path(path).name if path else ""
            detail = f"{name} — {exc}" if name else str(exc)
            self.lbl_result.setText(f"실패: {title} · {detail}")
            QMessageBox.critical(self, f"{title} 실패", detail)

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
        lines.append(f"\n지금 컴파일하면 파일이 제자리에서 변경됩니다: {Path(path).name}")
        if not confirm_destructive(
            self, "fieldize 미리보기 → 적용", "\n".join(lines), "컴파일 적용"
        ):
            return  # dry-run 만 — 확인 없으면 변형 없음
        report = self.vm.apply_fieldize(path)
        self.lbl_result.setText(self.vm.format_compile_result(path, report))

    def _on_review(self, path: str) -> None:
        self.lbl_result.setText(self.vm.format_lint_result(path, self.vm.lint(path)))

    def _on_preview(self, path: str) -> None:
        self.lbl_result.setText(
            self.vm.format_preview_result(path, self.vm.filled_values(path))
        )

    def _on_drift(self) -> None:
        old, _ = QFileDialog.getOpenFileName(self, "이전 판본 HWPX", "", "HWPX (*.hwpx)")
        if not old:
            return
        new, _ = QFileDialog.getOpenFileName(self, "새 판본 HWPX", "", "HWPX (*.hwpx)")
        if not new:
            return
        self._run_action("드리프트", new, lambda: self._do_drift(old, new))

    def _do_drift(self, old: str, new: str) -> None:
        self.lbl_result.setText(
            self.vm.format_drift_result(old, new, self.vm.drift(old, new))
        )
