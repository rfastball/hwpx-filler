"""HWPX·TXT 템플릿 통합 관리면(얇은 렌더러).

레이어링: 위젯은 얇은 렌더러 — 상태 판정·상태별 게이트 액션·2단계 fieldize(스캔→적용)·
lint/drift 는 전부 :class:`~hwpxfiller.gui.template_manager_state.TemplateManagerViewModel`
(Qt 비의존, 링1)이 소유. 이 위젯은 행을 카드로 얹고 상태별 버튼을 배선한다.

- 템플릿 목록: compile_status 배지 + 필드 수 + 스킵/잔존 상세.
- HWPX 상태 게이트 버튼: RAW=[컴파일] · PARTIAL=[마저 컴파일][검토] ·
  COMPILED=[작업 만들기]. HWPX 미리보기는 작업 위저드와 중복이라 노출하지 않는다.
- TXT 템플릿: 기존 텍스트 레지스트리를 같은 화면에서 열기·편집·생성·삭제한다.
- fieldize: 스캔 미리보기(dry-run) → 명시적 적용(확인 시에만 변환·저장) — CLI 2단계 미러.
- lint 결과 표시. 판본 비교는 hwpxdiff 책임이라 이 화면에서 노출하지 않는다.

라우팅: 홈 헤더 [템플릿 관리] 버튼 → ``manage_templates_requested`` →
:class:`~hwpxfiller.gui.app.AppController` 가 이 패널을 열고 수명을 소유하며
``make_job_requested`` 시그널을 에디터로 연결한다(RC-04 로 홈 진입점 착지).
"""

from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from hwpxcore.atomic import write_text_atomic

from ..core.text_registry import TextTemplate, TextTemplateRegistry
from .confirm import confirm_destructive
from .style import BASE_QSS, mark
from .template_manager_state import TemplateManagerViewModel, TemplateRow
from .view_helpers import (
    ElidedLabel,
    busy_cursor,
    hide_item_text,
    last_dir,
    resync_card_item_heights,
    save_last_dir,
    show_error,
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
        # [마저 변환][검토], COMPILED 는 [작업 만들기]로 선언 순서
        # 그대로 화면화돼 카드마다 주 액션 위치가 좌/우 반전되던 것을, 주 액션을 항상 마지막
        # (카드 우측 끝)에 두어 위치를 고정한다. 강조는 화면 전역 primary(채움)가 아니라 카드
        # 반복 액션용 emphasis=card — 목록 전체에 채운 primary 가 곱절로 번지지 않게 한다.
        # 버튼 생성 순서는 선언 순서를 지켜(findItems·스모크 라벨 계약) 배치만 재정렬한다.
        primary_btn = None
        # 링1의 preview seam은 호환을 위해 보존하되, 위저드의 필드/토큰 정보와 중복되는
        # HWPX 미리보기 액션은 링2에서 노출하지 않는다(#13 10F2FF98-B).
        for act in (action for action in row.actions() if action.key != "preview"):
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


class TxtTemplateCard(QWidget):
    """TXT 템플릿 1건 카드 — 기존 레지스트리 항목의 관리 액션만 화면화한다."""

    def __init__(
        self,
        template: TextTemplate,
        on_action,
        *,
        field_count: "int | None",
        error: "Exception | None" = None,
        parent=None,
    ):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(3)

        name_row = QHBoxLayout()
        lbl_name = ElidedLabel(template.name, max_width=360)
        mark(lbl_name, "heading", True)
        name_row.addWidget(lbl_name)
        badge = QLabel("TXT" if error is None else "읽기 실패")
        mark(badge, "pill", "info" if error is None else "danger")
        name_row.addWidget(badge)
        name_row.addStretch(1)
        root.addLayout(name_row)

        if error is None:
            meta = f"토큰 {field_count or 0}개 · {template.path.name}"
        else:
            meta = f"파일을 읽을 수 없습니다: {error}"
        lbl_meta = QLabel(meta)
        mark(lbl_meta, "muted" if error is None else "level", True if error is None else "danger")
        lbl_meta.setWordWrap(True)
        root.addWidget(lbl_meta)

        foot = QHBoxLayout()
        foot.addStretch(1)
        if error is None:
            for key, label in (("edit", "내용 편집"), ("open", "즉시 기안에서 열기")):
                btn = QPushButton(label)
                btn.clicked.connect(
                    lambda _checked=False, k=key: on_action(k, template)
                )
                if key == "open":
                    mark(btn, "emphasis", "card")
                foot.addWidget(btn)
        btn_delete = QPushButton("삭제")
        btn_delete.clicked.connect(
            lambda _checked=False: on_action("delete", template)
        )
        foot.addWidget(btn_delete)
        root.addLayout(foot)


class TemplateManagerPanel(QWidget):
    """템플릿 라이브러리 워크숍. :class:`TemplateManagerViewModel` 을 렌더한다.

    셸 페이지(ST-01, SHELL_DESIGN §2) — 창 크롬(지오메트리·closeEvent)은 셸이 소유.
    독립 생성(테스트)도 계속 동작한다.
    """

    make_job_requested = Signal(str)  # 템플릿 경로 → 에디터로(app.py 가 연결)
    open_txt_requested = Signal(str)  # TXT 템플릿 이름 → 즉시 기안으로(app.py 가 연결)
    templates_changed = Signal()      # TXT 변경 → 홈 요약·목록 새로고침

    def __init__(self, library_dir=None, parent=None, *, text_registry=None):
        super().__init__(parent)
        if library_dir is None:
            # 홈의 기본 레지스트리 주입 관례 미러(RC-14) — 진입점이 폴더를 안 넘겨도
            # 백지가 아니라 표준 라이브러리(~/.hwpxfiller/templates)를 겨눈다.
            from ..core.template_status import default_templates_dir

            library_dir = default_templates_dir()
        self.vm = TemplateManagerViewModel(library_dir)
        if text_registry is None:
            from ..core.text_registry import default_text_templates_dir

            text_registry = TextTemplateRegistry(default_text_templates_dir())
        self.text_registry = text_registry

        self.setWindowTitle("HWPX Filler — 템플릿 관리")
        wire_refresh_shortcut(self)  # F5 → 새로고침(ST-12)
        self.setStyleSheet(BASE_QSS)
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("템플릿 관리")
        mark(title, "heading", True)
        header.addWidget(title)
        subtitle = QLabel("HWPX와 TXT 템플릿을 한곳에서 관리합니다.")
        mark(subtitle, "muted", True)
        header.addWidget(subtitle)
        header.addStretch(1)
        root.addLayout(header)

        catalogs = QSplitter(Qt.Horizontal)
        catalogs.setChildrenCollapsible(False)

        hwpx_group = QGroupBox("HWPX 템플릿")
        hwpx_box = QVBoxLayout(hwpx_group)
        hwpx_head = QHBoxLayout()
        self.lbl_count = QLabel("")
        mark(self.lbl_count, "muted", True)
        hwpx_head.addWidget(self.lbl_count)
        hwpx_head.addStretch(1)
        self.btn_dir = QPushButton("폴더 선택")
        self.btn_dir.clicked.connect(self._on_choose_dir)
        hwpx_head.addWidget(self.btn_dir)
        hwpx_box.addLayout(hwpx_head)

        self.stack = QStackedWidget()
        self.list = QListWidget()
        self.list.setObjectName("jobList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stack.addWidget(self.list)                    # 0 = 목록
        self.stack.addWidget(self._build_empty_state())    # 1 = 빈 상태(홈 패턴 미러)
        hwpx_box.addWidget(self.stack, 1)
        catalogs.addWidget(hwpx_group)

        txt_group = QGroupBox("TXT 템플릿")
        txt_box = QVBoxLayout(txt_group)
        txt_head = QHBoxLayout()
        self.lbl_txt_count = QLabel("")
        mark(self.lbl_txt_count, "muted", True)
        txt_head.addWidget(self.lbl_txt_count)
        txt_head.addStretch(1)
        self.btn_new_txt = QPushButton("새 TXT 템플릿")
        self.btn_new_txt.clicked.connect(self._on_new_txt)
        txt_head.addWidget(self.btn_new_txt)
        txt_box.addLayout(txt_head)
        self.lbl_txt_dir = ElidedLabel(str(self.text_registry.directory), max_width=440)
        mark(self.lbl_txt_dir, "muted", True)
        txt_box.addWidget(self.lbl_txt_dir)

        self.txt_stack = QStackedWidget()
        self.txt_list = QListWidget()
        self.txt_list.setObjectName("txtTemplateList")
        self.txt_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.txt_stack.addWidget(self.txt_list)
        self.txt_stack.addWidget(self._build_txt_empty_state())
        txt_box.addWidget(self.txt_stack, 1)
        catalogs.addWidget(txt_group)
        catalogs.setStretchFactor(0, 1)
        catalogs.setStretchFactor(1, 1)
        catalogs.setSizes([1, 1])
        root.addWidget(catalogs, 1)

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
        self.lbl_empty_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
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

    def _build_txt_empty_state(self) -> QWidget:
        """TXT 루트가 비었을 때 생성 동작을 바로 제공한다."""
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.addStretch(2)
        lbl = QLabel("표시할 TXT 템플릿이 없습니다")
        mark(lbl, "heading", True)
        lbl.setAlignment(Qt.AlignCenter)
        hint = QLabel("새 TXT 템플릿을 만들면 즉시 기안 화면에서 바로 사용할 수 있습니다.")
        mark(hint, "muted", True)
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        btn = QPushButton("새 TXT 템플릿")
        mark(btn, "primary", True)
        btn.clicked.connect(self._on_new_txt)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        row.addStretch(1)
        box.addWidget(lbl)
        box.addWidget(hint)
        box.addLayout(row)
        box.addStretch(3)
        return panel

    # ------------------------------------------------------------- 렌더
    def refresh(self) -> None:
        with busy_cursor():  # 라이브러리 템플릿 재파싱(compile 상태) 동안 대기 커서(ST-16)
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
        self._render_txt()

    def _render_txt(self) -> None:
        templates = self.text_registry.list_templates()
        self.lbl_txt_count.setText(f"{len(templates)}건")
        self.lbl_txt_dir.setText(str(self.text_registry.directory))
        self.txt_list.clear()
        for template in templates:
            error = None
            field_count = None
            try:
                field_count = len(template.fields())
            except Exception as exc:  # noqa: BLE001 — 손상 파일도 삭제 가능한 행으로 loud 노출
                error = exc
            self.txt_list.addItem(template.name)
            item = self.txt_list.item(self.txt_list.count() - 1)
            hide_item_text(item)
            card = TxtTemplateCard(
                template,
                self._dispatch_txt,
                field_count=field_count,
                error=error,
            )
            item.setSizeHint(card.sizeHint())
            self.txt_list.setItemWidget(item, card)
        self.txt_stack.setCurrentIndex(0 if templates else 1)
        self._sync_txt_cards()
        QTimer.singleShot(0, self._sync_txt_cards)

    def _sync_cards(self) -> None:
        """카드 item sizeHint 를 폴리시 후 재계산(UD-11 공용 헬퍼)."""
        resync_card_item_heights(self.list)

    def _sync_txt_cards(self) -> None:
        resync_card_item_heights(self.txt_list)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt 오버라이드
        super().resizeEvent(event)
        self._sync_cards()
        self._sync_txt_cards()

    def _on_choose_dir(self) -> None:
        # 현재 라이브러리 폴더 우선, 미설정이면 용도별 마지막 디렉터리(T3)로 시작.
        start = str(self.vm.library_dir) if self.vm.library_dir is not None else last_dir("library")
        chosen = QFileDialog.getExistingDirectory(self, "템플릿 라이브러리 폴더", start)
        if not chosen:
            return
        save_last_dir("library", chosen)  # 성공 선택만 기억(T3) — 취소는 직전 값 보존
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

    # ---------------------------------------------------- TXT 관리
    def _dispatch_txt(self, key: str, template: TextTemplate) -> None:
        if key == "open":
            self.open_txt_requested.emit(template.name)
        elif key == "edit":
            self._on_edit_txt(template)
        elif key == "delete":
            self._on_delete_txt(template)

    def _validated_txt_name(self, raw_name: str) -> "str | None":
        name = raw_name.strip()
        if not name:
            QMessageBox.warning(self, "TXT 템플릿 이름 필요", "템플릿 이름을 입력해 주세요.")
            return None
        if name.lower().endswith(".txt") or re.search(r'[\\/:*?"<>|]', name) or name in (".", ".."):
            QMessageBox.warning(
                self,
                "TXT 템플릿 이름 확인",
                "확장자와 경로 문자를 제외한 이름만 입력해 주세요.",
            )
            return None
        return name

    def _on_new_txt(self) -> None:
        raw_name, accepted = QInputDialog.getText(
            self,
            "새 TXT 템플릿",
            "템플릿 이름(확장자 제외)",
        )
        if not accepted:
            return
        name = self._validated_txt_name(raw_name)
        if name is None:
            return
        path = self.text_registry.directory / f"{name}.txt"
        if path.exists():
            QMessageBox.warning(
                self,
                "TXT 템플릿 중복",
                f"이미 같은 이름의 템플릿이 있습니다: {name}",
            )
            return
        content, accepted = QInputDialog.getMultiLineText(
            self,
            "새 TXT 템플릿",
            "{{필드}} 토큰을 포함한 템플릿 내용을 입력하세요.",
        )
        if not accepted:
            return

        def create() -> None:
            self.text_registry.directory.mkdir(parents=True, exist_ok=True)
            write_text_atomic(path, content)
            self._finish_txt_change(f"TXT 템플릿을 만들었습니다: {name}")

        self._run_action("TXT 템플릿 생성", str(path), create)

    def _on_edit_txt(self, template: TextTemplate) -> None:
        try:
            current = template.content()
        except Exception as exc:  # noqa: BLE001 — 읽기 실패를 모달+잔존 라벨로 통지
            self._run_action(
                "TXT 템플릿 읽기",
                str(template.path),
                lambda error=exc: (_ for _ in ()).throw(error),
            )
            return
        content, accepted = QInputDialog.getMultiLineText(
            self,
            f"TXT 템플릿 편집 — {template.name}",
            "확인을 누르면 이 템플릿에 저장됩니다.",
            current,
        )
        if not accepted or content == current:
            return

        def save() -> None:
            write_text_atomic(template.path, content)
            self._finish_txt_change(f"TXT 템플릿을 저장했습니다: {template.name}")

        self._run_action("TXT 템플릿 저장", str(template.path), save)

    def _on_delete_txt(self, template: TextTemplate) -> None:
        if not confirm_destructive(
            self,
            "TXT 템플릿 삭제",
            f"삭제하면 즉시 기안 목록에서도 사라집니다:\n{template.path}",
            "삭제",
        ):
            return

        def delete() -> None:
            template.path.unlink()
            self._finish_txt_change(f"TXT 템플릿을 삭제했습니다: {template.name}")

        self._run_action("TXT 템플릿 삭제", str(template.path), delete)

    def _finish_txt_change(self, message: str) -> None:
        mark(self.lbl_result, "level", "success")
        self.lbl_result.setText(message)
        self._render_txt()
        self.templates_changed.emit()

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
            show_error(self, f"{title} 실패", exc)  # 유형별 문구 + 원문 접기(ST-20)

    def _on_compile(self, path: str) -> None:
        """CLI 2단계 미러 — 스캔 미리보기(dry-run) → 사용자 확인 시에만 적용·저장."""
        with busy_cursor():  # HWPX 스캔(ST-16)
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
        with busy_cursor():  # 제자리 변환·저장(ST-16)
            report = self.vm.apply_fieldize(path)
        self._show_result(self.vm.format_compile_result(path, report))

    def _on_review(self, path: str) -> None:
        with busy_cursor():  # lint HWPX 파싱(ST-16)
            result = self.vm.lint(path)
        self._show_result(self.vm.format_lint_result(path, result))

    def _on_preview(self, path: str) -> None:
        with busy_cursor():  # 필드 값 읽기 HWPX 파싱(ST-16)
            values = self.vm.filled_values(path)
        self._show_result(self.vm.format_preview_result(path, values))
