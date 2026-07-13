"""txt 즉시 기안 화면 — 템플릿 + 데이터 → 실시간 렌더 → 복사(Qt 얇은 렌더러).

레이어링: 결정·렌더는 :class:`~hwpxfiller.gui.txt_state.TxtDraftViewModel`(Qt 비의존, 링1)이
소유하고, 이 위젯은 QComboBox·QFileDialog·클립보드·표현만 담당한다. **실시간 view 가 진실**
(ADR C 트랙 분기): 템플릿/레코드가 바뀔 때마다 다시 렌더하고, 누락 토큰은 ``{{}}`` 를 빨강으로
남긴다(조용히 안 지움 — ADR E). 클립보드 복사가 사용자의 완료 동작이다.
"""
from __future__ import annotations

import html as _html
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
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
from ..data import make_source
from .batch_run import DataAcquireController
from .flow_layout import FlowLayout
from .style import BASE_QSS, DANGER, MISSING_BG, MUTED, mark
from .txt_state import TxtDraftViewModel
from .view_helpers import ElidedLabel, restore_geometry, save_geometry

_TOKEN = re.compile(r"\{\{\s*([^{}|]+?)\s*\}\}")
# 상태 어휘 3정의 경계(UD-20): txt 의 'missing'=데이터에 해당 **항목(열) 부재**라
# '항목 없음'으로 표기한다 — 실행 화면의 '미입력'(출력값 빔·ack 대상)과 구분한다.
# 'blank'=항목은 있으나 값이 빈 '빈 값'(원천 데이터 값 빔).
_STATE_LABEL = {"fill": "✓ 채움", "blank": "◦ 빈 값", "missing": "● 항목 없음"}
# 완료 라벨(lbl_note)의 기본 안내 — 복사/저장 전, 그리고 레코드·템플릿 전환 후 복귀 문구.
_NOTE_DEFAULT = "현재 미리보기 내용을 복사합니다. 항목 없는 토큰은 그대로 표시됩니다."


class TxtDraftView(QMainWindow):
    """즉시 기안 — 정해진 루트의 템플릿 선택 + 데이터 결합 + 실시간 렌더/복사."""

    back_requested = Signal()

    def __init__(self, registry: TextTemplateRegistry, parent=None, *,
                 pool_registry=None, secret_store=None, nara_fetcher=None):
        super().__init__(parent)
        self.vm = TxtDraftViewModel(registry)
        # 데이터 풀(참조) — 실행 표면과 대칭으로 txt 도 풀에서 겨눈다(UD-25). 주입 가능
        # (테스트); 기본은 홈 레지스트리(run_view 와 동형 기본값).
        if pool_registry is None:
            from ..core.dataset_pool import (
                DatasetPoolRegistry,
                default_dataset_pool_dir,
            )
            pool_registry = DatasetPoolRegistry(default_dataset_pool_dir())
        self._pool_registry = pool_registry
        self._secret_store = secret_store
        self._nara_fetcher = nara_fetcher
        self.setWindowTitle("HWPX Filler — 즉시 기안")
        restore_geometry(self, "txt", default_size=(880, 680))  # ST-11
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
        # 데이터 겨눔 대칭화(UD-25) — 실행 표면(풀·파일·나라)과 동형으로 풀·파일·수기 3종.
        self.btn_pool = QPushButton("데이터 풀에서…")
        self.btn_pool.clicked.connect(self._pick_from_pool)
        self.btn_data = QPushButton("파일 선택…")
        self.btn_data.clicked.connect(self._pick_data)
        self.btn_manual = QPushButton("수기 입력…")
        self.btn_manual.clicked.connect(self._manual_entry)
        ctl.addWidget(self.btn_pool)
        ctl.addWidget(self.btn_data)
        ctl.addWidget(self.btn_manual)
        ctl.addWidget(QLabel("레코드"))
        self.btn_prev = QPushButton("◀")
        # 글리프 전용 버튼에 접근가능 이름·툴팁 부여(ST-06, WCAG 4.1.2/1.1.1) — 스크린리더가
        # 삼각형 문자명이 아니라 기능을 읽는다.
        self.btn_prev.setAccessibleName("이전 레코드")
        self.btn_prev.setToolTip("이전 레코드")
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.lbl_idx = QLabel("0/0")
        self.btn_next = QPushButton("▶")
        self.btn_next.setAccessibleName("다음 레코드")
        self.btn_next.setToolTip("다음 레코드")
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

        # ---- 공용 데이터 취득 계층(RC-22) 재사용 — 실행 표면과 같은 겨눔 오케스트레이션 ----
        # 파일·풀 겨눔은 run/matrix 와 동일한 DataAcquireController 를 태운다(축자 사본 금지).
        # 나라 애드혹은 이 트랙 스코프 밖 — 파일·풀·수기 3경로만 배선한다.
        self._data = DataAcquireController(
            self, pool_registry=self._pool_registry,
            load_file=self.vm.load_data,
            restore_pool_item=lambda item: self.vm.load_pool_item(
                item, secret_store=self._secret_store, fetcher=self._nara_fetcher
            ),
            set_acquired=self.vm.set_acquired,
            after_loaded=self._after_data_loaded,
            say=self._say, set_busy=self._set_data_busy,
            secret_store=self._secret_store, nara_fetcher=self._nara_fetcher,
        )

        names = self.vm.template_names()
        if names:
            self.vm.select_template(names[0])
        self._render()

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt 오버라이드
        save_geometry(self, "txt")  # 세션 간 크기·위치 유지(ST-11)
        super().closeEvent(event)

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

    # ------------------------------- 데이터 겨눔(파일·풀은 공용 계층 위임, RC-22) ----
    def _pick_data(self) -> None:
        """파일 소스 겨눔 — run/matrix 와 같은 공용 계층에 위임(축자 사본 해소)."""
        self._data.pick_file()

    def _pick_from_pool(self) -> None:
        """데이터 풀에서 골라 실행 시점 재읽기(싱크) — 복원은 백그라운드(RC-12)."""
        self._data.pick_from_pool()

    def _manual_entry(self) -> None:
        """수기 1건 입력 — 현재 템플릿 토큰을 폼으로 받아 인라인 소스로 겨눈다(UD-25).

        값 몇 개만 넣고 바로 복사한다는 즉시 기안의 핵심 가치를 위해 엑셀 파일 제작을
        강제하지 않는다. 인라인 소스 생성은 공용 팩토리(``make_source("inline", …)``)를
        거친다 — txt 가 소스 클래스를 직접 만들지 않는다.
        """
        fields = self.vm.template_field_names()
        if not fields:
            QMessageBox.information(
                self, "수기 입력", "먼저 토큰({{…}})이 있는 템플릿을 선택하세요."
            )
            return
        dlg = ManualRecordDialog(self, fields)
        if dlg.exec() != QDialog.Accepted:
            return
        rec = dlg.record()
        source = make_source("inline", records=[rec])
        self.vm.set_acquired(source, [rec])
        self._after_data_loaded("수기 입력 1건")

    def _after_data_loaded(self, label: str) -> None:
        """겨눔 공통 꼬리 — 라벨 표기 + 실시간 재렌더(파일·풀·수기 공용)."""
        self.ed_data.setText(label)
        self._render()

    def _set_data_busy(self, busy: bool) -> None:
        """데이터 복원(네트워크 가능) 중 겨눔 버튼 잠금 — 재진입·경합 방지(RC-12)."""
        for b in (self.btn_pool, self.btn_data, self.btn_manual):
            b.setEnabled(not busy)

    def _say(self, msg: str) -> None:
        """진행 상태를 완료 라벨에 잠깐 표기(muted) — 다음 렌더가 기본 안내로 복귀시킨다.

        txt 는 로그 패널이 없다 — 풀 복원 같은 백그라운드 진행을 조용히 두지 않고
        (RC-12 진행 표시) lbl_note 에 muted 로 띄운다. 완료 시 ``_after_data_loaded`` →
        ``_render`` → ``_reset_note`` 가 스테일 진행 문구를 지운다(UD-02 서사 존중).
        """
        mark(self.lbl_note, "level", "")
        mark(self.lbl_note, "muted", True)
        self.lbl_note.setText(msg)

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
            text = (f"⚠ 항목 없음 {len(missing)}건({', '.join(missing)}) 포함 {action}됨 "
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
            # 고정폭 280px 패널에서 긴 토큰명이 배지를 넘기던 것을 말줄임+툴팁으로 봉합(UD-30 E).
            # 가운데 말줄임으로 토큰명 앞부분과 상태 접미('· ✓ 채움')를 모두 남긴다.
            chip = ElidedLabel(
                "{{" + tok.name + "}} · " + _STATE_LABEL[tok.state],
                mode=Qt.TextElideMode.ElideMiddle, max_width=248,
            )
            mark(chip, "fb", tok.state)
            self.tok_flow.addWidget(chip)

        # 미리보기는 템플릿에서 직접 토큰을 재진술 렌더한다(UD-26 E7) — 항목 없음은 빨강
        # {{토큰}}, 빈 값은 '〈빈 값〉' 마커로 위치를 남긴다. 채우다 만 자리가 무표시 빈
        # 공간으로 사라지지 않는다(ADR-B '빈 공간으로 보이면 안 됨'). 클립보드 복사(_copy)는
        # vm.render() 의 실제 텍스트를 쓰므로 마커에 영향받지 않는다.
        esc = self._build_preview_html(self.vm.template_text, self.vm.current_record())
        self.view.setHtml(
            '<div style="font-family:Malgun Gothic,sans-serif;font-size:14px;'
            'line-height:1.8;white-space:pre-wrap;">' + esc + '</div>'
        )

        n = self.vm.record_count()
        self.lbl_idx.setText(f"{(self.vm.record_index % n) + 1 if n else 0}/{n}")
        self.btn_prev.setEnabled(n > 1)
        self.btn_next.setEnabled(n > 1)

    @staticmethod
    def _build_preview_html(template: str, record: "dict") -> str:
        """템플릿의 토큰을 레코드로 치환하되 미충족을 명시 재진술한 미리보기 HTML(UD-26 E7).

        - 항목 없음(레코드에 없음): 빨강 ``{{토큰}}`` 으로 그대로 노출(조용히 안 지움, ADR-E).
        - 빈 값(필드는 있으나 값이 빔): ``〈빈 값〉`` muted 마커로 **위치**를 남긴다 — blank 가
          ``''`` 로 치환·소멸해 어느 자리가 빈 채 나가는지 특정 불가이던 결함을 봉합한다.
        - 채움: 값 그대로.
        """
        parts: "list[str]" = []
        last = 0
        for m in _TOKEN.finditer(template):
            parts.append(_html.escape(template[last:m.start()]))
            name = m.group(1).strip()
            if name not in record:
                # 미입력 토큰 강조는 배지 토큰 참조(UD-33 ③): raw #fde2dd(제3의 미입력색)·
                # #c0392b(DANGER 재타이핑)를 MISSING_BG·DANGER 로 환원 — 칩과 프리뷰 색 일치.
                parts.append(f'<span style="background:{MISSING_BG};color:{DANGER};">{{{{'
                             + _html.escape(name) + '}}</span>')
            else:
                raw = record.get(name)
                value = "" if raw is None else str(raw)
                if value.strip() == "":
                    parts.append(f'<span style="color:{MUTED};">〈빈 값〉</span>')
                else:
                    parts.append(_html.escape(value))
            last = m.end()
        parts.append(_html.escape(template[last:]))
        return "".join(parts)

    def _copy(self) -> None:
        text, report = self.vm.render()
        QApplication.clipboard().setText(text)
        self._announce(report, "복사")

    def _save(self) -> None:
        text, report = self.vm.render()
        path, _ = QFileDialog.getSaveFileName(
            self, "텍스트 파일로 저장", "기안.txt", "텍스트 (*.txt)")
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
                "기안 텍스트를 저장했습니다. 항목 없음/빈 값이 포함되어 있으니 확인하세요.",
            )
        else:
            QMessageBox.information(self, "저장", "기안 텍스트를 저장했습니다.")


class ManualRecordDialog(QDialog):
    """수기 1건 입력 — 현재 템플릿 토큰을 폼으로 받아 레코드 1건을 만든다(UD-25).

    파일·풀 겨눔과 대칭인 세 번째 데이터 진입점. 빈 칸은 빈 값으로 남겨 미리보기에서
    '빈 값'(blank)으로 표시되게 한다 — 조용히 지우지 않는다(ADR-E 미러). 레코드 dict
    조립만 하고 소스 생성(팩토리)·겨눔은 호출자(``TxtDraftView._manual_entry``)가 한다.
    """

    def __init__(self, parent, fields: "list[str]"):
        super().__init__(parent)
        self.setWindowTitle("수기 입력 — 1건")
        self._edits: "dict[str, QLineEdit]" = {}
        lay = QVBoxLayout(self)
        form = QFormLayout()
        for name in fields:
            ed = QLineEdit()
            self._edits[name] = ed
            form.addRow(name, ed)
        lay.addLayout(form)
        note = QLabel("빈 칸은 빈 값으로 채워집니다(미리보기에서 '빈 값'으로 표시).")
        mark(note, "muted", True)
        note.setWordWrap(True)
        lay.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def record(self) -> "dict[str, str]":
        """폼 입력을 레코드 1건(dict)으로 — 값이 없으면 빈 문자열."""
        return {name: ed.text() for name, ed in self._edits.items()}
