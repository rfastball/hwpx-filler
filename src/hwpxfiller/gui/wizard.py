"""작업 에디터 저작 페이지 — 템플릿 → 데이터 → 필드 매핑(사람 확정).

이 세 페이지(:class:`TemplatePage`·:class:`DataPage`·:class:`MappingPage`)는 작업 에디터
(:mod:`hwpxfiller.gui.job_editor`)가 조립해 쓰는 재사용 저작 스텝이다. 핵심은 매핑 단계의
**명시성 게이트**: 자동 제안은 초안일 뿐이고, 사람이 모든 행을 확정하기 전에는 다음으로
넘어갈 수 없다(``MappingModel.is_complete``).

세션 상태(template_path, schema, data_path, source_fields, records, model)는 호스트 위저드
객체가 들고, 각 페이지는 ``self.wizard()`` 로 접근한다(덕타이핑 — 같은 속성명을 노출하는
어떤 QWizard 든 이 페이지들을 그대로 호스팅할 수 있다). 나라장터 주입 이음새
(``secret_store``/``nara_fetcher``)도 호스트 계약의 일부다 — 페이지가 직접 속성 접근하므로
호스트는 (None 이라도) 반드시 선언해야 한다(미선언 폴백 금지, RC-25).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)

from ..core.authoring import compile_to_sibling
from ..core.mapping import MappingProfile
from ..core.schema import extract_schema
from ..data import source_for_path
from .confirm import confirm_destructive
from .file_filters import EXCEL_FILTER, HWPX_FILTER
from .mapping_state import (
    RAW_BLOCK_MESSAGE,
    MappingModel,
    PartialGate,
    gate_for_template,
)
from .mapping_table import MappingTable
from .style import mark

# 요약 라벨에 나열할 필드 이름 최대 개수(넘치면 말줄임).
_SUMMARY_MAX_FIELDS = 12


class TemplatePage(QWizardPage):
    """1단계 — HWPX 템플릿 선택 + 스키마 추출 + PARTIAL 확정 게이트.

    필드가 있어도 skip/파편/평문 잔존 토큰이 남은 **PARTIAL**("다 된 것 같지만 아닌")
    상태는 값이 조용히 누락되는 위험이라 그냥 통과시키지 않는다. 게이트를 열려면 사람이
    (a) [여기서 누름틀 변환]으로 잔존 평문 토큰을 누름틀로 바꾸거나, (b) 그 토큰들을 비움으로
    구체 이름으로 **명시 확인**해야 한다(순수 판정은 :class:`PartialGate`, 헤드리스 테스트).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("1단계 — 템플릿 선택")
        self.setSubTitle("누름틀이 들어 있는 HWPX 템플릿을 선택하세요.")
        self._valid = False
        self._gate: "PartialGate | None" = None
        # 게이트 계산 자체가 실패한 상태(fail-closed): PARTIAL 여부를 배제할 수 없으므로
        # 진행을 막고 경고를 지우지 않는다. ``_gate is None``(COMPILED/FILLED 정상)과 구분.
        self._gate_error = False

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.ed_path = QLineEdit()
        self.ed_path.setReadOnly(True)
        # 읽기전용 경로 표시 필드는 포커스 체인에서 제외한다(UD-37): 남겨두면 스텝1
        # 첫 포커스가 여기 착지해 :focus 파랑 테두리+전체 선택이 :read-only 회색 룩을
        # 덮어 '편집하라'/'편집 불가'를 동시 발신했다. NoFocus 로 첫 포커스를 실제
        # 실행동인 '찾아보기…' 버튼에 넘긴다(style.py 의 read-only:focus 규칙이 2차 방어).
        self.ed_path.setFocusPolicy(Qt.NoFocus)
        btn = QPushButton("찾아보기…")
        btn.clicked.connect(self._pick)
        row.addWidget(QLabel("템플릿(.hwpx)"))
        row.addWidget(self.ed_path, 1)
        row.addWidget(btn)
        layout.addLayout(row)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)
        self.lbl_warn = QLabel("")
        self.lbl_warn.setWordWrap(True)
        mark(self.lbl_warn, "level", "warn")
        layout.addWidget(self.lbl_warn)

        # PARTIAL 게이트 해소 액션 — 평상시 숨김, PARTIAL 일 때만 노출.
        gate_row = QHBoxLayout()
        self.btn_compile = QPushButton("여기서 누름틀 변환")
        self.btn_compile.clicked.connect(self._compile_here)
        self.btn_ack = QPushButton("비움 확인…")
        self.btn_ack.clicked.connect(self._ack_partial)
        self.btn_compile.setVisible(False)
        self.btn_ack.setVisible(False)
        gate_row.addWidget(self.btn_compile)
        gate_row.addWidget(self.btn_ack)
        gate_row.addStretch(1)
        layout.addLayout(gate_row)
        layout.addStretch(1)

    def initializePage(self):
        # 편집 모드: 저장된 템플릿을 자동 로드(부재 시 경고만 — 사용자가 재선택).
        wiz = self.wizard()
        job = getattr(wiz, "initial_job", None)
        if job is None or self._valid or self.ed_path.text():
            return
        if job.template_path and Path(job.template_path).exists():
            self._load_template(job.template_path)
        elif job.template_path:
            self.lbl_warn.setText(
                f"저장된 템플릿을 찾을 수 없습니다: {job.template_path}\n"
                "템플릿을 다시 선택하세요."
            )

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "HWPX 템플릿 선택", "", HWPX_FILTER)
        if path:
            self._load_template(path)

    def _load_template(self, path: str) -> bool:
        """스키마 추출·요약 표시 + PARTIAL 게이트 계산. 실패/필드 0개면 미완료 유지."""
        wiz = self.wizard()
        self._valid = False
        self._gate = None
        self._gate_error = False
        self.lbl_warn.setText("")
        self.btn_compile.setVisible(False)
        self.btn_ack.setVisible(False)
        try:
            schema = extract_schema(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"템플릿 스키마 추출 실패:\n{exc}")
            self.lbl_summary.setText("")
            self.completeChanged.emit()
            return False

        self.ed_path.setText(path)
        if not schema.fields:
            # RAW(진짜 필드 0개) — 채울 대상이 없어 진행 불가. 차단 사유를 같은 페이지
            # PARTIAL 차단과 동일한 warn 채널(lbl_warn)로 렌더하고, 문구는 단일 원천
            # (mapping_state.RAW_BLOCK_MESSAGE)에서 가져온다(UD-21: 무마크 요약·이중화 해소).
            # lbl_summary 는 성공 요약 전용으로 비운다.
            self.lbl_summary.setText("")
            self.lbl_warn.setText(RAW_BLOCK_MESSAGE)
            self.completeChanged.emit()
            return False

        wiz.template_path = path
        wiz.schema = schema
        names = [f"{f.name}({f.inferred_type})" for f in schema.fields]
        shown = ", ".join(names[:_SUMMARY_MAX_FIELDS])
        if len(names) > _SUMMARY_MAX_FIELDS:
            shown += f" 외 {len(names) - _SUMMARY_MAX_FIELDS}개"
        self.lbl_summary.setText(f"필드 {len(names)}개: {shown}")

        # 컴파일 상태 게이트 — PARTIAL 이면 비차단 경고를 확정 게이트로 승격한다.
        # (종전엔 stray 만 비차단 경고였다 — 값이 조용히 누락되는 위험을 소리 나게 세운다.)
        # 계산 자체가 실패하면 PARTIAL 여부를 배제할 수 없다 → fail-closed(진행 차단 + 시끄럽게).
        try:
            self._gate = gate_for_template(path)
        except Exception as exc:  # noqa: BLE001 - 계산 실패는 fail-closed(조용히 통과 금지)
            self._gate = None
            self._gate_error = True
            self.lbl_warn.setText(
                f"진행 차단: 누름틀 변환 상태를 계산할 수 없습니다 — {exc}\n"
                "PARTIAL 여부를 확인할 수 없어 진행할 수 없습니다. 템플릿을 다시 선택하세요."
            )
        self._valid = True
        self._refresh_gate_ui()
        self.completeChanged.emit()
        return True

    def _refresh_gate_ui(self) -> None:
        """게이트 상태를 경고 라벨·액션 버튼에 반영(PARTIAL 에서만 게이트 UI 노출)."""
        if self._gate_error:
            # 계산 실패 = fail-closed. 경고 텍스트를 지우지 않고(시끄럽게 유지) 버튼만 숨긴다.
            self.btn_compile.setVisible(False)
            self.btn_ack.setVisible(False)
            return
        gate = self._gate
        if gate is None or not gate.needs_gate():
            self.lbl_warn.setText("")
            self.btn_compile.setVisible(False)
            self.btn_ack.setVisible(False)
            return
        self.lbl_warn.setText(gate.message())
        # 인라인 컴파일은 잔존 평문(컴파일 가능)이 있을 때만 제안한다.
        self.btn_compile.setVisible(gate.status.compilable_n > 0)
        self.btn_ack.setVisible(not gate.is_acked())

    def _compile_here(self) -> None:
        """[여기서 누름틀 변환] — 잔존 평문 토큰을 누름틀로 변환해 COMPILED 로 승격.

        원본은 건드리지 않는다. 컴파일·경로 파생·저장·충돌 정책은 코어
        :func:`~hwpxfiller.core.authoring.compile_to_sibling` 이 수행한다(뷰에 IO 정책
        하드코딩 없음 — RC-28). 여기선 충돌 시 사용자 확정(RC-02)과 컴파일본 전환
        (재로딩·스키마·게이트 재계산)만 오케스트레이션한다.
        """
        path = self.ed_path.text()
        if not path:
            return
        try:
            compiled_path, report = compile_to_sibling(path)
        except FileExistsError as exc:
            # 컴파일본이 이미 있으면(사람이 손봤을 수 있음) 조용히 덮지 않는다(RC-02)
            # — 명시 확정 후에만 overwrite 로 재시도한다.
            if not confirm_destructive(
                self, "덮어쓰기 확인",
                f"변환본이 이미 있습니다:\n{exc}\n\n"
                "계속하면 기존 변환본을 덮어씁니다.",
                "덮어쓰고 진행",
            ):
                return
            try:
                compiled_path, report = compile_to_sibling(path, overwrite=True)
            except Exception as exc2:  # noqa: BLE001
                QMessageBox.critical(self, "오류", f"누름틀 변환 실패:\n{exc2}")
                return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"누름틀 변환 실패:\n{exc}")
            return
        if compiled_path is None:
            QMessageBox.information(
                self, "변환할 토큰 없음",
                "누름틀로 바꿀 수 있는 평문 토큰이 없습니다(파편·필드 값 내부 잔존).\n"
                "'비움 확인'으로 진행하세요.",
            )
            return
        QMessageBox.information(
            self, "누름틀 변환 완료",
            f"{len(report.compiled)}개 토큰을 누름틀로 변환했습니다.\n"
            f"원본은 그대로 두고 변환본으로 전환합니다:\n{compiled_path}",
        )
        # 변환본으로 재로딩 — 상태가 COMPILED 면 게이트가 저절로 열린다.
        self._load_template(compiled_path)

    def _ack_partial(self) -> None:
        """[비움 확인] — 미해결 토큰을 **구체 이름으로 재진술**하고 직접 확인시킨다.

        범용 확인이 아니라 이름을 못박은 확인이라야 반사적 dismiss 에 저항한다(ADR-E).
        기본 버튼은 '취소'라 Enter/Space 로는 확인되지 않는다.
        """
        gate = self._gate
        if gate is None or not gate.needs_gate():
            return
        names = ", ".join(gate.unmet_tokens)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("비움 확인")
        box.setText(
            f"다음 {len(gate.unmet_tokens)}개 토큰은 값이 주입되지 않습니다:\n\n{names}\n\n"
            "이 토큰들을 비우고 진행하는 것이 의도한 바가 맞습니까?"
        )
        proceed = box.addButton("비우고 진행", QMessageBox.AcceptRole)
        cancel = box.addButton("취소", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)  # 반사적 Enter/Space 로는 확인되지 않음(ADR-E)
        box.exec()
        if box.clickedButton() is proceed:
            gate.acknowledge(gate.unmet_tokens)  # 정확히 재진술된 이름 전체를 확인
            self._refresh_gate_ui()
            self.completeChanged.emit()

    def isComplete(self) -> bool:
        # 필드가 있고(_valid), 상태 계산이 성공했으며(not _gate_error), PARTIAL 이면
        # ack-or-compile 로 게이트가 열려야 완료. 계산 실패는 fail-closed(진행 불가).
        return (
            self._valid
            and not self._gate_error
            and (self._gate is None or self._gate.can_proceed())
        )


class DataPage(QWizardPage):
    """2단계 — 데이터 소스 선택(엑셀/CSV 파일 **또는** 나라장터 취득). 컬럼·레코드 수 요약.

    소스가 자기 어휘를 소유한다(V1): 나라장터는 영문 코드 키를 반환하고 ``field_labels()``
    로 퍼지 매핑 타겟을 제공한다. 취득 산출물은 **키 없는 스냅샷**(``AcquiredNaraData``)이라
    위저드 세션/작업 직렬화 표면에 ServiceKey 가 닿지 않는다(키 저장/사용은 N1 SecretStore).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("2단계 — 데이터 선택 (선택)")
        self.setSubTitle(
            "선택 단계입니다 — 미리보기·자동제안용 샘플을 불러오거나 건너뛰세요. "
            "매핑은 데이터 없이 스키마만으로 확정할 수 있고, 실제 데이터는 실행할 때 고릅니다."
        )
        self._valid = False
        self._reverting = False  # 소스 토글 취소 시 라디오 되돌림의 재진입 가드

        layout = QVBoxLayout(self)

        # ---- 소스 선택(엑셀/CSV | 나라장터) ----
        src_row = QHBoxLayout()
        self.rb_excel = QRadioButton("엑셀/CSV 파일")
        self.rb_nara = QRadioButton("나라장터")
        self.rb_excel.setChecked(True)
        self._src_group = QButtonGroup(self)
        self._src_group.addButton(self.rb_excel)
        self._src_group.addButton(self.rb_nara)
        self.rb_excel.toggled.connect(self._on_source_toggle)
        src_row.addWidget(QLabel("데이터 소스"))
        src_row.addWidget(self.rb_excel)
        src_row.addWidget(self.rb_nara)
        src_row.addStretch(1)
        layout.addLayout(src_row)

        # ---- 엑셀/CSV 파일 선택 행 ----
        self.excel_row = QWidget()
        row = QHBoxLayout(self.excel_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.ed_path = QLineEdit()
        self.ed_path.setReadOnly(True)
        # 읽기전용 경로 필드는 포커스 체인에서 제외(UD-37 — 스텝1과 동일 시맨틱).
        self.ed_path.setFocusPolicy(Qt.NoFocus)
        btn = QPushButton("찾아보기…")
        btn.clicked.connect(self._pick)
        row.addWidget(QLabel("데이터(.xlsx/.csv)"))
        row.addWidget(self.ed_path, 1)
        row.addWidget(btn)
        layout.addWidget(self.excel_row)

        # ---- 나라장터 취득 행 ----
        self.nara_row = QWidget()
        nrow = QHBoxLayout(self.nara_row)
        nrow.setContentsMargins(0, 0, 0, 0)
        self.btn_nara = QPushButton("나라장터에서 가져오기…")
        self.btn_nara.clicked.connect(self._open_nara)
        nrow.addWidget(QLabel("조달청 표준 입찰공고"))
        nrow.addWidget(self.btn_nara)
        nrow.addStretch(1)
        self.nara_row.setVisible(False)
        layout.addWidget(self.nara_row)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)
        layout.addStretch(1)

    def _has_loaded_data(self) -> bool:
        """파기될 실데이터(파일 로드분·나라장터 스냅샷)가 세션에 있는가.

        뷰 경로칸이 아니라 **세션**(records/data_path)만 본다 — 빈 파일 선택 후처럼
        경로칸에는 시도 경로가 남아도 세션이 비었으면 잃을 것이 없다(오탐 방지).
        """
        wiz = self.wizard()
        if wiz is None:
            return False
        return bool(getattr(wiz, "records", None)) or bool(getattr(wiz, "data_path", ""))

    def _on_source_toggle(self, *_args) -> None:
        """소스 전환 — 해당 입력 행만 노출하고 이전 선택을 무효화(소스 혼선 방지).

        이전에 불러온 데이터(특히 네트워크 왕복 산출물인 나라장터 스냅샷)가 있으면
        탐색적 클릭 한 번에 조용히 파기하지 않는다 — 파괴 확인을 거치고, 거부하면
        라디오를 되돌린다(UD-08: 무확인·무고지 즉시 파기 해소).
        """
        if self._reverting:
            return
        excel = self.rb_excel.isChecked()
        if self._has_loaded_data() and not confirm_destructive(
            self, "데이터 소스 전환",
            "지금 불러온 데이터 선택이 지워집니다"
            "(나라장터 취득분은 다시 가져와야 합니다).\n소스를 전환하시겠습니까?",
            "전환하고 지우기",
        ):
            # 되돌림 — 이 재-토글이 다시 확인을 띄우지 않도록 가드.
            self._reverting = True
            self.rb_excel.setChecked(not excel)
            self._reverting = False
            return
        self.excel_row.setVisible(excel)
        self.nara_row.setVisible(not excel)
        self.reset_data_session()
        self.completeChanged.emit()

    def reset_data_session(self) -> None:
        """이전 데이터 선택을 뷰·위저드 세션 **양쪽에서 원자적으로** 무효화.

        뷰(경로칸·요약)만 지우면 세션 사본(data_path·datasource·records·source_fields)
        이 잔존해 매핑 스텝이 사용자가 지웠다고 믿는 옛 데이터로 조용히 구동된다
        (RC-09) — 이중 사본을 한 자리에서 함께 지운다.
        """
        self._valid = False
        self.ed_path.clear()
        self.lbl_summary.setText("")
        wiz = self.wizard()
        if wiz is not None:
            wiz.data_path = ""
            wiz.datasource = None
            wiz.source_fields = []
            wiz.records = []

    def _open_nara(self) -> None:
        """나라장터 취득 대화상자를 열고, 수용 시 취득 산출물을 위저드 세션에 심는다.

        ``secret_store``/``nara_fetcher`` 는 호스트 위저드의 **선언된 계약 속성**이다
        (:class:`~hwpxfiller.gui.job_editor.JobEditorWizard` 생성자 파라미터, RC-25) —
        직접 읽어서, 계약을 선언하지 않은 호스트는 조용한 실 자격증명 저장소·실 네트워크
        폴백이 아니라 ``AttributeError`` 로 시끄럽게 실패한다. ``None`` 이면 대화상자가
        OS 자격증명 저장소·실 네트워크 기본값을 쓴다.
        """
        from .nara_view import NaraAcquireDialog

        wiz = self.wizard()
        dlg = NaraAcquireDialog(
            self,
            store=wiz.secret_store,
            fetcher=wiz.nara_fetcher,
        )
        if dlg.exec() == dlg.Accepted and dlg.records:
            self._apply_nara_result(dlg.records, dlg.fields, dlg.datasource, dlg.label)

    def _apply_nara_result(self, records, fields, datasource, label: str) -> None:
        """취득 결과(키 없는 스냅샷)를 위저드 세션에 반영 — 파일 경로 대신 합성 라벨 사용.

        ``data_path`` 는 매핑 초안 캐시 키의 일부라 취득마다 달라지게 라벨을 심는다
        (MappingPage 가 조합 변경을 감지해 재초안). 헤드리스 테스트가 다이얼로그 없이 직접
        호출할 수 있게 분리한다.
        """
        wiz = self.wizard()
        wiz.data_path = label
        wiz.datasource = datasource
        wiz.source_fields = fields
        wiz.records = records
        self.ed_path.setText(label)
        self.lbl_summary.setText(
            f"나라장터 {len(fields)}개 필드, {len(records)}건 취득."
        )
        self._valid = bool(fields and records)
        self.completeChanged.emit()

    def initializePage(self):
        # 편집 모드 고지: Job 은 데이터를 저장하지 않는다(핸드오프 §3) — 매핑 검토용
        # 샘플 데이터를 다시 고른다는 사실을 정직하게 노출.
        if getattr(self.wizard(), "initial_job", None) is not None:
            self.setSubTitle(
                "작업에 데이터는 저장되지 않습니다 — 매핑 검토용 샘플은 선택입니다"
                "(건너뛰어도 됩니다). 실제 데이터·행은 실행할 때 고릅니다."
            )

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "데이터 파일 선택", "", EXCEL_FILTER
        )
        if not path:
            return
        wiz = self.wizard()
        try:
            source = source_for_path(path)
            fields = source.fields()
            records = source.records()
        except Exception as exc:  # noqa: BLE001
            # 실패 시 뷰·세션을 원자적으로 정렬해 옛 데이터가 매핑을 조용히 구동하지
            # 않게 한다(UD-08). 시도 경로는 보여주되 세션은 비운다.
            self.reset_data_session()
            self.ed_path.setText(path)
            self.lbl_summary.setText(
                "데이터 로드에 실패했습니다 — 이전 선택은 지워졌습니다. "
                "다른 파일을 선택하거나 데이터 없이 다음 단계로 진행하세요."
            )
            QMessageBox.critical(self, "오류", f"데이터 로드 실패:\n{exc}")
            self.completeChanged.emit()
            return

        if not fields or not records:
            # 빈 데이터는 샘플로 불러오지 않는다 — 그러나 데이터 스텝은 **선택**(ADR-J)
            # 이므로 '진행할 수 없습니다'로 게이트를 오도하지 않는다. 뷰·세션을 정렬하고
            # (옛 데이터 잔존 제거) 사실에 맞는 문구로 교체한다(UD-08).
            self.reset_data_session()
            self.ed_path.setText(path)
            self.lbl_summary.setText(
                f"컬럼 {len(fields)}개, 레코드 {len(records)}건 — 이 파일은 비어 있어 "
                "샘플로 불러오지 않았습니다(이전 선택은 지워짐).\n"
                "1행이 헤더(필드명)·2행부터 레코드인 파일을 선택하거나, "
                "데이터 없이 다음 단계로 진행하세요."
            )
            self.completeChanged.emit()
            return

        self._valid = False
        self.ed_path.setText(path)
        wiz.data_path = path
        wiz.datasource = source
        wiz.source_fields = fields
        wiz.records = records
        self.lbl_summary.setText(f"컬럼 {len(fields)}개, 레코드 {len(records)}건 로드.")
        self._valid = True
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        # 데이터 스텝은 **선택**(ADR J 강등) — 데이터 없이도 다음(매핑)으로 진행할 수 있다.
        # 샘플을 불러오면 매핑 초안·미리보기가 채워지고, 건너뛰면 스키마만으로 확정한다.
        # (``_valid`` 는 요약 표시·소스전환 내부 상태로만 유지.)
        return True


class MappingPage(QWizardPage):
    """3단계 — 필드 매핑 확정. 전 행 확정 전에는 다음으로 못 간다(명시성 게이트)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("3단계 — 필드 매핑 확정")
        self.setSubTitle(
            "자동 제안은 초안일 뿐입니다. 모든 행을 검토해 확정해야 다음으로 진행합니다. "
            "채우지 않을 필드는 소스를 (비움)으로 두고 확정하세요."
        )
        self._built_for: "tuple[str, str, tuple[str, ...]] | None" = None
        self._preview_index = 0

        layout = QVBoxLayout(self)
        self.table = MappingTable()
        self.table.completeChanged.connect(self._on_table_changed)
        layout.addWidget(self.table, 1)

        # 레코드 스텝퍼 — 어떤 레코드로 미리보기할지 훑는다. 라벨을 '이전/다음
        # 레코드'로 구체화한다(UD-40): 위저드 푸터의 '다음(N)'(페이지 이동)과 스텝퍼의
        # '다음'(레코드 이동)이 한 화면에서 두 '다음'으로 공존해 혼동될 여지를 없앤다.
        stepper = QHBoxLayout()
        self.btn_prev = QPushButton("◀ 이전 레코드")
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.btn_next = QPushButton("다음 레코드 ▶")
        self.btn_next.clicked.connect(lambda: self._step(1))
        self.lbl_index = QLabel("레코드 0/0")
        self.lbl_preview_summary = QLabel("")
        self.lbl_preview_summary.setWordWrap(True)
        stepper.addWidget(self.btn_prev)
        stepper.addWidget(self.lbl_index)
        stepper.addWidget(self.btn_next)
        stepper.addSpacing(12)
        stepper.addWidget(self.lbl_preview_summary, 1)
        layout.addLayout(stepper)

        buttons = QHBoxLayout()
        self.lbl_progress = QLabel("확정 0/0")
        mark(self.lbl_progress, "muted", True)
        btn_base_apply = QPushButton("매핑 프로파일 적용…")
        btn_base_apply.clicked.connect(self._apply_base)
        btn_base_save = QPushButton("매핑 프로파일로 저장…")
        btn_base_save.clicked.connect(self._save_base)
        btn_load = QPushButton("매핑 파일 불러오기…")
        btn_load.clicked.connect(self._load_profile)
        btn_save = QPushButton("매핑 파일 저장…")
        btn_save.clicked.connect(self._save_profile)
        buttons.addWidget(self.lbl_progress)
        buttons.addStretch(1)
        buttons.addWidget(btn_base_apply)
        buttons.addWidget(btn_base_save)
        buttons.addWidget(btn_load)
        buttons.addWidget(btn_save)
        layout.addLayout(buttons)

    def initializePage(self):
        wiz = self.wizard()
        # 캐시 키에 소스 필드 집합을 포함한다(RC-09): 경로쌍만으로는 내용 불감이라
        # 같은 경로의 수정된 파일 재선택·소스 전환 후에도 옛 어휘로 조용히 구동됐다.
        key = (wiz.template_path, wiz.data_path, tuple(wiz.source_fields))
        if self._built_for != key or wiz.model is None:
            # 템플릿/데이터 조합이 바뀌었을 때만 초안을 새로 뽑는다
            # (뒤로 갔다 와도 사람이 만진 확정 상태를 잃지 않게).
            # 선택된 소스가 자기 어휘를 소유한다: 나라장터처럼 영문 코드 키 소스는
            # field_labels() 로 퍼지 타겟을 제공하고, Excel/CSV(사람 라벨 헤더)는 {}.
            ds = getattr(wiz, "datasource", None)
            labels_fn = getattr(ds, "field_labels", None)
            aliases = labels_fn() if callable(labels_fn) else {}
            wiz.model = MappingModel.from_suggestions(
                wiz.schema, wiz.source_fields, aliases
            )
            self._built_for = key
            # 공유 베이스(J3): fresh 초안 위에 베이스를 **이름 교집합**으로 투영한다
            # (apply_profile 이 이 템플릿에 없는 베이스 필드는 자동 skip). 베이스가 커버
            # 못 한 템플릿 필드는 **미확정 유지** → is_complete 게이트가 loud 차단(ADR D).
            base = getattr(wiz, "base_mapping", None)
            if base is not None and base.mappings:
                applied = wiz.model.apply_profile(base)
                uncovered = sum(1 for r in wiz.model.rows if not r.confirmed)
                self.setSubTitle(
                    f"매핑 프로파일에서 {applied}개 필드를 반영했습니다(확정 상태). "
                    f"매핑 프로파일이 커버하지 못한 {uncovered}개 필드는 직접 검토·확정하세요."
                )
            # 편집 모드: 저장된 매핑을 프리시드 — 일치 행은 과거 사람 확정의 복원이라
            # 확정 상태로 온다(apply_profile). 프로파일에 없는 행은 미확정 유지:
            # 의도적 공란과 새 필드를 구별할 수 없어 자동 확정은 게이트를 몰래 약화시킨다.
            # 베이스 다음에 적용해 **인별 오버레이가 베이스를 이긴다**(변경 행만 덮음).
            job = getattr(wiz, "initial_job", None)
            if job is not None and job.mapping.mappings:
                applied = wiz.model.apply_profile(job.mapping)
                self.setSubTitle(
                    f"기존 매핑 {applied}개 필드를 불러왔습니다(확정 상태). "
                    "소스에 없거나 새로 생긴 필드만 검토해 확정하세요."
                )
        preview = wiz.records[0] if wiz.records else {}
        self.table.set_model(wiz.model, preview)
        # 데이터가 바뀌면 인덱스가 범위 밖일 수 있으니 클램프.
        if self._preview_index >= len(wiz.records):
            self._preview_index = 0
        self._sync_preview()
        self._sync_progress()
        self.completeChanged.emit()

    def _on_table_changed(self):
        # 매핑 편집 시 미리보기 요약도 함께 갱신(미리보기 셀은 테이블이 이미 갱신).
        self._sync_preview_summary()
        self._sync_progress()
        self.completeChanged.emit()

    def _sync_progress(self):
        """확정 진행 카운터 — 게이트(전 행 확정)까지 얼마나 남았는지 상시 노출.

        위계는 상태 의존적이다(UD-14): 차단 중(미완료)에는 스텝1 차단 신호와 같은
        warn 로 강조하고 잔여 수를 재진술하며, 해소되면 ok 로 축하한다. 차단일수록
        muted 회색으로 눕던 강조 역전을 바로잡는다.
        """
        model = self.wizard().model if self.wizard() else None
        if model is None or not model.rows:
            self.lbl_progress.setText("확정 0/0")
            mark(self.lbl_progress, "muted", True)
            mark(self.lbl_progress, "level", "")
            return
        done = sum(1 for r in model.rows if r.confirmed)
        total = len(model.rows)
        mark(self.lbl_progress, "muted", False)
        if done == total:
            self.lbl_progress.setText(f"확정 {done}/{total}")
            mark(self.lbl_progress, "level", "ok")
        else:
            self.lbl_progress.setText(f"확정 {done}/{total} — {total - done}개 남음")
            mark(self.lbl_progress, "level", "warn")

    def _step(self, delta: int):
        wiz = self.wizard()
        n = len(wiz.records)
        if n == 0:
            return
        self._preview_index = max(0, min(n - 1, self._preview_index + delta))
        self._sync_preview()

    def _sync_preview(self):
        wiz = self.wizard()
        n = len(wiz.records)
        if n == 0:
            # 레코드 0/0 빈 상태 안내(UD-28): 미리보기할 데이터가 없다는 사실을 그냥
            # 침묵으로 두지 않고, 왜(데이터 미연결)·무엇을 할 수 있는지(상수·비움 확정)를
            # 재진술한다. 스텝퍼 인덱스는 '레코드 0/0'로 유지(비활성).
            self.lbl_index.setText("레코드 0/0")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            self.lbl_preview_summary.setText(
                "미리보기할 데이터가 없습니다 — 데이터 미연결(스키마만 편집 중). "
                "상수로 채우거나 (비움)으로 확정하세요. 실제 데이터는 실행할 때 고릅니다."
            )
            return
        rec = wiz.records[self._preview_index]
        self.table.set_preview_record(rec)
        self.lbl_index.setText(f"레코드 {self._preview_index + 1}/{n}")
        self.btn_prev.setEnabled(self._preview_index > 0)
        self.btn_next.setEnabled(self._preview_index < n - 1)
        self._sync_preview_summary()

    def _sync_preview_summary(self):
        wiz = self.wizard()
        if wiz.model is None or not wiz.records:
            self.lbl_preview_summary.setText("")
            return
        rec = wiz.records[self._preview_index]
        empties = wiz.model.preview_empties(rec)
        # 3상태 전량 집계(UD-27): 채움·빈 값·미매핑의 합 = 전체 필드 수. 미매핑 잔존
        # 필드가 무집계로 빠져 합계가 필드 수와 어긋나던 공란 규모 과소 진술을 해소.
        filled, empty_n, unmapped = wiz.model.preview_counts(rec)
        text = f"채움 {filled} · 빈 값 {empty_n} · 미매핑 {unmapped}"
        if empties:
            text += " — " + ", ".join(empties)
        self.lbl_preview_summary.setText(text)

    def isComplete(self) -> bool:
        wiz = self.wizard()
        return wiz is not None and wiz.model is not None and wiz.model.is_complete()

    # ----------------------------------------------------------- 프로파일 IO
    def _load_profile(self):
        wiz = self.wizard()
        if wiz.model is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "매핑 파일 불러오기", "", "매핑 파일 (*.json)"
        )
        if not path:
            return
        try:
            profile = MappingProfile.load(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"매핑 파일 로드 실패:\n{exc}")
            return
        applied = wiz.model.apply_profile(profile)
        self.table.refresh()
        self.completeChanged.emit()
        QMessageBox.information(
            self, "매핑 파일 적용",
            f"{applied}개 필드에 매핑 파일을 적용했습니다(적용 행은 확정 상태).\n"
            "매핑 파일에 없는 필드는 직접 확정하세요.",
        )

    def _save_profile(self):
        wiz = self.wizard()
        if wiz.model is None:
            return
        profile = wiz.model.to_profile()
        if not profile.mappings:
            QMessageBox.warning(
                self, "확인", "저장할 확정 매핑이 없습니다. 행을 확정한 뒤 저장하세요."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "매핑 파일 저장", "mapping_profile.json", "매핑 파일 (*.json)"
        )
        if not path:
            return
        profile.name = Path(path).stem
        try:
            profile.save(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"매핑 파일 저장 실패:\n{exc}")
            return
        QMessageBox.information(
            self, "저장 완료", f"확정 매핑 {len(profile.mappings)}개를 저장했습니다."
        )

    # -------------------------------------------------------- 공유 베이스(J3)
    def _base_registry(self):
        """베이스 레지스트리 — 위저드 주입 우선, 아니면 홈 기본(테스트 이음새)."""
        reg = getattr(self.wizard(), "base_registry", None)
        if reg is not None:
            return reg
        from ..core.mapping_base import MappingBaseRegistry, default_mapping_bases_dir

        return MappingBaseRegistry(default_mapping_bases_dir())

    def _referencing_jobs(self, base_name: str) -> "list[str] | None":
        """이 베이스를 계보로 참조하는 작업 이름들(전파 경고 근거).

        ``None`` = **참조 여부 판단 불가**(레지스트리 부재·조회 실패·손상 작업 파일 존재)
        — 호출부는 이를 '참조 없음'([])과 구별해 시끄럽게 재진술해야 한다(RC-15 P5b:
        과거엔 조회 실패를 []로 삼켜 실존 참조의 전파 경고를 우회시켰다).
        """
        job_reg = getattr(self.wizard(), "registry", None)
        if job_reg is None:
            return None
        corrupted: "list[tuple[Path, str]]" = []
        try:
            jobs = job_reg.list_jobs(corrupted=corrupted)
        except Exception:  # noqa: BLE001 — 실패를 '참조 없음'으로 오역하지 않는다
            return None
        if corrupted:
            # 손상 작업이 이 베이스를 참조할 수도 있다 — 전수 확인이 불가능하면 불명.
            return None
        return [
            j.name for j in jobs
            if getattr(j, "base_mapping_name", "") == base_name
        ]

    def _apply_base(self):
        """공유 베이스를 골라 현재 모델에 **이름 교집합**으로 투영(apply_profile)."""
        wiz = self.wizard()
        if wiz.model is None:
            return
        reg = self._base_registry()
        names = reg.names()
        if not names:
            QMessageBox.information(
                self, "매핑 프로파일",
                "저장된 매핑 프로파일이 없습니다. 매핑을 확정한 뒤 '매핑 프로파일로 저장'으로 만드세요.",
            )
            return
        name, ok = QInputDialog.getItem(
            self, "매핑 프로파일 적용", "매핑 프로파일:", names, 0, False
        )
        if not ok or not name:
            return
        try:
            base = reg.load(name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"베이스 로드 실패:\n{exc}")
            return
        applied = wiz.model.apply_profile(base)  # 이 템플릿에 없는 필드는 자동 skip
        wiz.base_mapping_name = name
        self.table.refresh()
        self.completeChanged.emit()
        uncovered = sum(1 for r in wiz.model.rows if not r.confirmed)
        QMessageBox.information(
            self, "매핑 프로파일 적용",
            f"'{name}'에서 {applied}개 필드를 반영했습니다(확정 상태).\n"
            f"매핑 프로파일이 커버하지 못한 {uncovered}개 필드는 직접 확정하세요.",
        )

    def _save_base(self):
        """현재 확정 매핑을 named 공유 베이스로 저장 — 참조 작업 있으면 전파 경고."""
        wiz = self.wizard()
        if wiz.model is None:
            return
        profile = wiz.model.to_profile()
        if not profile.mappings:
            QMessageBox.warning(
                self, "확인", "저장할 확정 매핑이 없습니다. 행을 확정한 뒤 저장하세요."
            )
            return
        name, ok = QInputDialog.getText(
            self, "매핑 프로파일로 저장", "매핑 프로파일 이름:",
            text=getattr(wiz, "base_mapping_name", "") or "",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        reg = self._base_registry()
        if reg.exists(name):
            # 베이스는 durable 공유 자산 — 참조 유무와 **무관하게** 덮어쓰기 확인을
            # 요구한다(RC-15 P5a: 과거엔 참조 0개면 확인 자체가 없었다).
            refs = self._referencing_jobs(name)
            if refs:
                detail = (
                    f"이 매핑 프로파일을 참조하는 작업 {len(refs)}개가 있습니다"
                    f"({', '.join(refs[:5])}). 덮어쓰면 그 작업들의 매핑을 다시 "
                    "검토·확정해야 할 수 있습니다."
                )
            elif refs is None:
                detail = (
                    "참조 작업 여부를 확인할 수 없습니다(작업 목록 조회 실패·손상) — "
                    "이 매핑 프로파일을 참조하는 작업이 있을 수 있습니다."
                )
            else:
                detail = "참조하는 작업은 없지만, 저장된 매핑 프로파일이 지금 매핑으로 교체됩니다."
            if not confirm_destructive(
                self, "매핑 프로파일 덮어쓰기",
                f"매핑 프로파일 '{name}' 이(가) 이미 있습니다.\n{detail}",
                "덮어쓰기",
            ):
                return
        profile.name = name
        try:
            reg.save(profile)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"베이스 저장 실패:\n{exc}")
            return
        wiz.base_mapping_name = name
        QMessageBox.information(
            self, "저장 완료",
            f"매핑 프로파일 '{name}'({len(profile.mappings)}개 필드)를 저장했습니다.",
        )
