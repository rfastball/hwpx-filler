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
:class:`~hwpxfiller.gui.app.AppController` 가 이 패널을 열고 수명을 소유하며
``make_job_requested`` 시그널을 에디터로 연결한다(RC-04 로 홈 진입점 착지).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
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
from .file_filters import HWPX_FILTER
from .style import BASE_QSS, mark
from .template_manager_state import TemplateManagerViewModel, TemplateRow
from .view_helpers import (
    ElidedLabel,
    hide_item_text,
    restore_geometry,
    resync_card_item_heights,
    save_geometry,
    wire_refresh_shortcut,
)


class TemplateCard(QWidget):
    """템플릿 1건 카드 — 이름 + 상태 배지 + 상세 + 상태별 게이트 액션 버튼.

    성형된 :class:`TemplateRow` 와 액션 디스패처만 받는다(코어 직접 접근 없음).
    """

    def __init__(self, row: TemplateRow, on_action, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(3)

        name_row = QHBoxLayout()
        # 긴 템플릿 파일명은 말줄임+툴팁(UD-30 F) — 가로 스크롤 Off 로 잘려 유사 판본
        # 파일명을 구별 못 하던 것을, 전체 이름 툴팁으로 보완한다.
        lbl_name = ElidedLabel(row.name, max_width=360)
        mark(lbl_name, "heading", True)
        name_row.addWidget(lbl_name)
        badge = QLabel(row.badge_label)
        # 같은 CompileState badge_level 을 홈 카드와 동일한 pill 계열로 렌더(UD-13/RC-29)
        # — 맨 텍스트(level)로 렌더되어 파일명과 구별이 약하던 화면별 배지 분열을 해소.
        mark(badge, "pill", row.badge_level)
        name_row.addWidget(badge)
        name_row.addStretch(1)
        root.addLayout(name_row)

        lbl_meta = QLabel(row.detail_line())
        mark(lbl_meta, "muted", True)
        lbl_meta.setWordWrap(True)
        root.addWidget(lbl_meta)

        foot = QHBoxLayout()
        foot.addStretch(1)
        # 카드 주 액션(compile·make_job)은 보조 등급 + 고정 끝(우측) 정렬(UD-22): PARTIAL 은
        # [마저 변환][검토], COMPILED 는 [미리보기][작업 만들기]로 _STATE_ACTIONS 선언 순서
        # 그대로 화면화돼 카드마다 주 액션 위치가 좌/우 반전되던 것을, 주 액션을 항상 마지막
        # (카드 우측 끝)에 두어 위치를 고정한다. 강조는 화면 전역 primary(채움)가 아니라 카드
        # 반복 액션용 emphasis=card — 목록 전체에 채운 primary 가 곱절로 번지지 않게 한다.
        # 버튼 생성 순서는 선언 순서를 지켜(findItems·스모크 라벨 계약) 배치만 재정렬한다.
        primary_btn = None
        for act in row.actions():
            btn = QPushButton(act.label)
            btn.clicked.connect(
                lambda _checked=False, k=act.key: on_action(k, row.path)
            )
            if act.key in ("compile", "make_job"):
                mark(btn, "emphasis", "card")
                primary_btn = btn  # 배치는 맨 끝으로 미룸(위치 고정)
            else:
                foot.addWidget(btn)
        if primary_btn is not None:
            foot.addWidget(primary_btn)
        root.addLayout(foot)


# 하위호환 별칭(RC-35): 스모크 테스트 등 크로스모듈 인용이 실재하는 공용 표면 —
# 기존 `_TemplateCard` 임포트는 이 별칭으로 계속 동작한다.
_TemplateCard = TemplateCard


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
        restore_geometry(self, "template", default_size=(720, 560))  # ST-11
        wire_refresh_shortcut(self)  # F5 → 새로고침(ST-12)
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
        # 결과 라벨은 성과별 심각도 채널(level)로 렌더한다(UD-07) — 경고·실패가 화면
        # 최저 위계의 muted 회색으로 고정 렌더되던 결함 해소. 초기(빈 문구)는 muted.
        mark(self.lbl_result, "level", "muted")
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

    def _show_result(self, line) -> None:
        """결과 문구 + 심각도 마킹(UD-07) — VM(링1)이 파생한 level 을 그대로 렌더한다.

        ``line`` 은 :class:`~hwpxfiller.gui.template_manager_state.ResultLine`(str 하위형)
        로 ``.level`` 을 싣는다 — 위젯은 심각도를 재판정하지 않고 마킹만 한다.
        """
        level = getattr(line, "level", "muted")
        mark(self.lbl_result, "level", level)
        self.lbl_result.setText(str(line))

    def _render(self) -> None:
        self.lbl_count.setText(self.vm.count_label())
        self.list.clear()
        for row in self.vm.rows():
            self.list.addItem(row.name)
            item = self.list.item(self.list.count() - 1)
            hide_item_text(item)  # 이름은 아이템 text, 표시는 카드(UD-33 공용 이디엄)
            card = TemplateCard(row, on_action=self._dispatch)
            item.setSizeHint(card.sizeHint())
            self.list.setItemWidget(item, card)
        if self.vm.is_empty():
            self.lbl_empty_hint.setText(self.vm.empty_hint())
            self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(0)
        # 카드 액션 버튼 세로 압착 방지(UD-11) — 폴리시·레이아웃 후 높이 재동기.
        self._sync_cards()
        QTimer.singleShot(0, self._sync_cards)

    def _sync_cards(self) -> None:
        """카드 item sizeHint 를 폴리시 후 재계산(UD-11 공용 헬퍼)."""
        resync_card_item_heights(self.list)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt 오버라이드
        save_geometry(self, "template")  # 세션 간 크기·위치 유지(ST-11)
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt 오버라이드
        super().resizeEvent(event)
        self._sync_cards()

    def _on_choose_dir(self) -> None:
        start = str(self.vm.library_dir) if self.vm.library_dir is not None else ""
        chosen = QFileDialog.getExistingDirectory(self, "템플릿 라이브러리 폴더", start)
        if not chosen:
            return
        # 폴더가 바뀌면 직전 결과는 무의미(스테일 방지) — 문구·심각도 함께 초기화.
        mark(self.lbl_result, "level", "muted")
        self.lbl_result.setText("")
        self.vm.set_library_dir(chosen)

    # ---------------------------------------------------- 액션 디스패치
    def _dispatch(self, key: str, path: str) -> None:
        if key == "compile":
            self._run_action("누름틀 변환", path, lambda: self._on_compile(path))
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
        # 직전 결과 잔존 = 실패를 성공처럼 보이게 하는 오도 — 문구·심각도 함께 소거.
        mark(self.lbl_result, "level", "muted")
        self.lbl_result.setText("")
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — 액션 시점 실패는 전부 통지 대상
            name = Path(path).name if path else ""
            detail = f"{name} — {exc}" if name else str(exc)
            # 실패 잔존 기록은 danger 로 시끄럽게(UD-07) — muted 회색 중립 메모로 오독 금지.
            mark(self.lbl_result, "level", "danger")
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
            # UD-24: '변환 가능 토큰 없음'을 차단 모달이 아니라 인라인 lbl_result 로 통일
            # (같은 화면 다른 결과 4종과 대칭 — 모달은 파괴 확정에만).
            self._show_result(self.vm.format_scan_empty_result(path, preview))
            return
        lines.append(f"\n지금 누름틀로 변환하면 파일이 제자리에서 변경됩니다: {Path(path).name}")
        if not confirm_destructive(
            self, "누름틀 변환 미리보기 → 적용", "\n".join(lines), "누름틀 변환 적용"
        ):
            return  # dry-run 만 — 확인 없으면 변형 없음
        report = self.vm.apply_fieldize(path)
        self._show_result(self.vm.format_compile_result(path, report))

    def _on_review(self, path: str) -> None:
        self._show_result(self.vm.format_lint_result(path, self.vm.lint(path)))

    def _on_preview(self, path: str) -> None:
        self._show_result(
            self.vm.format_preview_result(path, self.vm.filled_values(path))
        )

    def _on_drift(self) -> None:
        old, _ = QFileDialog.getOpenFileName(self, "이전 판본 HWPX", "", HWPX_FILTER)
        if not old:
            return
        new, _ = QFileDialog.getOpenFileName(self, "새 판본 HWPX", "", HWPX_FILTER)
        if not new:
            return
        self._run_action("드리프트", new, lambda: self._do_drift(old, new))

    def _do_drift(self, old: str, new: str) -> None:
        self._show_result(
            self.vm.format_drift_result(old, new, self.vm.drift(old, new))
        )
