"""실행(Run) 화면 — 저장된 작업을 골라 데이터·행을 겨눠 생성한다.

트랙 C UX 결정([[hwpx-filler-scope]]): 셋업(에디터)과 실행(여기)을 가른다. 무거운 명시성
게이트(매핑 확정)는 셋업에만 있다 — **여기선 매핑 재확정이 없다.** 실행은 사전검증만 한다.

레이어링(아키텍처 분리): 이 위젯은 **얇은 렌더러/오케스트레이터**다 — 데이터 로드·대상
문서 결정·사전검증·생성 게이트는 :class:`~hwpxfiller.gui.run_state.RunViewModel`(Qt 비의존,
링1)이 소유한다. 위젯은 QMessageBox·QFileDialog·진행/로그 표현만 담당하고, 백엔드
(``DataSource``·``HwpxEngine``)를 직접 만지지 않는다. ``datasource``/``records``/
``_template_override``/``_effective_template()`` 는 뷰모델로 위임하는 프로퍼티다(스캐폴드·
스모크 계약 보존). QThread 수명주기·데이터 겨눔 3종은 매트릭스 실행과 공용 계층
(:mod:`~hwpxfiller.gui.batch_run`, RC-22)이 소유한다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.job import MISSING_MARKER, Job
from .batch_run import (
    BatchRunController,
    DataAcquireController,
    ask_open_result_folder,
    describe_result_error,
)
from .confirm import confirm_destructive
from .file_filters import HWPX_FILTER
from .flow_layout import FlowLayout
from .record_select import RecordSelector
from .run_state import GenerationPlan, RunViewModel
from .style import BASE_QSS, ContrastProgressBar, mark
from .view_helpers import ElidedLabel, restore_geometry, save_geometry, wire_submit_shortcut
from .worker import GenerateWorker


class RunView(QMainWindow):
    """작업 1건을 실행 — 데이터 겨눔 → 행 선택 → 사전검증 → 생성."""

    run_finished = Signal(object)  # BatchResult
    back_requested = Signal()

    def __init__(self, job: Job, parent=None, *, pool_registry=None,
                 secret_store=None, nara_fetcher=None):
        super().__init__(parent)
        self.job = job
        self.vm = RunViewModel(job)            # 실행 결정(Qt 비의존)
        # 데이터 풀(참조) — 실행 시점에 겨눈다. 주입 가능(테스트); 기본은 홈 레지스트리.
        if pool_registry is None:
            from ..core.dataset_pool import (
                DatasetPoolRegistry,
                default_dataset_pool_dir,
            )
            pool_registry = DatasetPoolRegistry(default_dataset_pool_dir())
        self._pool_registry = pool_registry
        self._secret_store = secret_store
        self._nara_fetcher = nara_fetcher
        self._plan: "GenerationPlan | None" = None  # 이번 생성의 불변 계획(RC-07)
        self._marked_fields: "list[str]" = []  # 이번 생성에서 미입력 표시가 들어간 필드(결과 요약용)

        self.setWindowTitle(f"HWPX Filler — 실행: {job.name}")
        restore_geometry(self, "run", default_size=(760, 680))  # ST-11
        self.setStyleSheet(BASE_QSS)
        # 폼이 세로로 길다 — 창을 줄이면 위젯이 찌그러지지 않고 스크롤되도록 QScrollArea 로 감싼다.
        central = QWidget()
        root = QVBoxLayout(central)

        # ---- 작업 요약 ----
        # 작업명·템플릿명·파일명 패턴 연결 문자열은 형제 라벨과 달리 wordWrap 이 없어
        # 긴 이름에서 폼 전체 가로 스크롤을 유발할 수 있었다(UD-30 C) — 말줄임+전체 툴팁으로
        # 봉합한다(최소폭을 작게 둬 스크롤 대신 말줄임).
        lbl_job = ElidedLabel(
            f"작업: {job.name}  ·  템플릿: {Path(job.template_path).name}  ·  "
            f"파일명: {job.filename_pattern}"
        )
        mark(lbl_job, "heading", True)
        root.addWidget(lbl_job)

        # ---- 대상 문서(신규 vs 누적치환 단건) ----
        target_box = QGroupBox("대상 문서")
        tb = QVBoxLayout(target_box)
        self.rb_new = QRadioButton(f"새 문서 생성 — 작업 템플릿({Path(job.template_path).name})")
        self.rb_new.setChecked(True)
        self.rb_cont = QRadioButton("기존 문서 이어채우기 — 선택한 .hwpx 문서에 이 단계 값을 채웁니다")
        self.rb_new.toggled.connect(self._on_target_mode)
        tb.addWidget(self.rb_new)
        tb.addWidget(self.rb_cont)
        prow = QHBoxLayout()
        self.ed_prev = QLineEdit()
        self.ed_prev.setReadOnly(True)
        self.btn_prev = QPushButton("기존 문서 선택…")
        self.btn_prev.clicked.connect(self._pick_prev)
        prow.addSpacing(20)
        prow.addWidget(self.ed_prev, 1)
        prow.addWidget(self.btn_prev)
        tb.addLayout(prow)
        self.lbl_prev_note = QLabel("")
        self.lbl_prev_note.setWordWrap(True)
        tb.addWidget(self.lbl_prev_note)
        root.addWidget(target_box)
        self._on_target_mode()  # 초기 상태(신규) 반영

        # ---- 데이터 ---- (UD-41: 동급 섹션 카드 프레이밍 통일 — 섹션명은 박스 제목으로)
        data_box = QGroupBox("데이터")
        drow = QHBoxLayout(data_box)
        self.ed_data = QLineEdit()
        self.ed_data.setReadOnly(True)
        self.btn_pool = QPushButton("데이터 풀에서…")
        self.btn_pool.clicked.connect(self._pick_from_pool)
        self.btn_data = QPushButton("파일 선택…")
        self.btn_data.clicked.connect(self._pick_data)
        self.btn_nara = QPushButton("나라장터…")
        self.btn_nara.clicked.connect(self._pick_nara)
        drow.addWidget(self.ed_data, 1)
        drow.addWidget(self.btn_pool)
        drow.addWidget(self.btn_data)
        drow.addWidget(self.btn_nara)
        root.addWidget(data_box)

        # ---- 사전검증(치명 소스누락 표시) ----
        self.lbl_preflight = QLabel("")
        self.lbl_preflight.setWordWrap(True)
        root.addWidget(self.lbl_preflight)

        # ---- 빈칸 표면화(상시 인라인 + 강제 확인 게이트, ADR-E) ----
        gate_box = QGroupBox("미입력 필드 확인")
        gbl = QVBoxLayout(gate_box)
        lbl_gate_help = QLabel(
            "필드 상태를 확인하세요. 미입력 필드는 직접 확인해야 문서를 생성할 수 있습니다."
        )
        lbl_gate_help.setWordWrap(True)
        mark(lbl_gate_help, "muted", True)
        gbl.addWidget(lbl_gate_help)
        self.badge_host = QWidget()
        self.badge_flow = FlowLayout(self.badge_host, margin=0, spacing=6)
        gbl.addWidget(self.badge_host)
        self.lbl_gate = QLabel("")
        self.lbl_gate.setWordWrap(True)
        gbl.addWidget(self.lbl_gate)
        root.addWidget(gate_box)

        # ---- 생성 대상 레코드 ---- (UD-41: 동급 섹션 카드 프레이밍 통일)
        rec_box = QGroupBox("생성 대상 레코드")
        rec_l = QVBoxLayout(rec_box)
        self.selector = RecordSelector()
        self.selector.selectionChanged.connect(self._on_selection_changed)
        rec_l.addWidget(self.selector, 1)
        root.addWidget(rec_box, 1)

        # ---- 저장 폴더 ---- (UD-41: 동급 섹션 카드 프레이밍 통일 — 섹션명은 박스 제목으로)
        out_box = QGroupBox("저장 폴더")
        orow = QGridLayout(out_box)
        orow.setColumnStretch(0, 1)
        self.ed_out = QLineEdit()
        if job.template_path:
            self.ed_out.setText(str(Path(job.template_path).parent / "Results"))
        # 저장 폴더는 게이트 전제조건(UD-06) — 편집 시 게이트를 다시 평가해 '버튼
        # 비활성 + 인라인 사유'가 즉시 반영되게 한다.
        self.ed_out.textChanged.connect(self._sync_generate_enabled)
        btn_out = QPushButton("찾아보기…")
        btn_out.clicked.connect(self._pick_out)
        orow.addWidget(self.ed_out, 0, 0)
        orow.addWidget(btn_out, 0, 1)
        # 생성 원장(L2) — 기본 꺼짐(opt-in). 고위험 문서 계보가 필요할 때만 켠다.
        self.chk_ledger = QCheckBox("생성 원장(JSON) 저장 — 들어간 값의 증거")
        self.chk_ledger.setToolTip(
            "저장 폴더에 실행별 fill-ledger-<시각>.json 을 남깁니다(이전 실행 증거 보존): "
            "소스 실제형 샘플, 필드별 주입 예정값, 생성 후 문서 되읽기 검증(✓/✗). "
            "값은 텍스트이며 HWPX 렌더가 아닙니다."
        )
        orow.addWidget(self.chk_ledger, 1, 0)
        root.addWidget(out_box)

        # ---- 액션 ----
        actions = QHBoxLayout()
        self.btn_generate = QPushButton("문서 생성")
        mark(self.btn_generate, "primary", True)
        self.btn_generate.clicked.connect(self._on_generate)
        wire_submit_shortcut(self, self.btn_generate)  # Ctrl+Return → 문서 생성(ST-12)
        actions.addWidget(self.btn_generate)
        # 실행 중 협조적 취소(RC-06) — 레코드 경계에서 중단, 부분 결과는 요약으로 남는다.
        self.btn_cancel = QPushButton("생성 취소")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel_generate)
        actions.addWidget(self.btn_cancel)
        actions.addStretch(1)
        root.addLayout(actions)

        self.progress = ContrastProgressBar()  # 청크 위 퍼센트 대비 복원(UD-31)
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.lbl_result = QLabel("")
        self.lbl_result.setWordWrap(True)
        root.addWidget(self.lbl_result)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(self.log, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(central)
        self.setCentralWidget(scroll)

        # ---- 공용 실행 계층(RC-22) — QThread 수명주기·데이터 겨눔은 매트릭스와 공유 ----
        self._runner = BatchRunController(
            self, progress=self.progress, lbl_result=self.lbl_result,
            btn_generate=self.btn_generate, btn_cancel=self.btn_cancel,
            say=self._say, on_idle=self._sync_generate_enabled,
            on_result=self._render_finished,
        )
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

        self._check_template()
        self._refresh_field_panel()

    # ------------------------------- 뷰모델 위임 프로퍼티(스캐폴드·스모크 계약) ----
    @property
    def datasource(self):
        return self.vm.datasource

    @datasource.setter
    def datasource(self, value) -> None:
        self.vm.datasource = value

    @property
    def records(self) -> "list[dict]":
        return self.vm.records

    @records.setter
    def records(self, value) -> None:
        self.vm.records = value

    @property
    def _template_override(self) -> "str | None":
        return self.vm.template_override

    @_template_override.setter
    def _template_override(self, value) -> None:
        self.vm.template_override = value

    def _effective_template(self) -> str:
        return self.vm.effective_template()

    # ------------------------- 공용 실행 계층 위임 프로퍼티(스캐폴드·스모크 계약, RC-22)
    @property
    def _thread(self):
        return self._runner.thread

    @property
    def _running(self) -> bool:
        return self._runner.running

    @_running.setter
    def _running(self, value: bool) -> None:
        self._runner.running = value

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt 오버라이드
        # 생성 진행 중 닫기 = 협조적 취소 확인(ST-21) — 파이프라인 이탈 가드와 대칭.
        if self._running:
            if not confirm_destructive(
                self, "생성 중단",
                "문서 생성이 진행 중입니다 — 창을 닫으면 남은 생성을 중단합니다.",
                "중단하고 닫기",
            ):
                event.ignore()
                return
            self._runner.request_cancel()
            self._runner.teardown()
        save_geometry(self, "run")  # 세션 간 크기·위치 유지(ST-11)
        super().closeEvent(event)

    @property
    def _data_thread(self):
        return self._data.thread

    # ------------------------------------------------------------------ helpers
    def _say(self, msg: str) -> None:
        self.log.appendPlainText(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _check_template(self) -> None:
        path = self.vm.effective_template()
        if path and not Path(path).exists():
            self._say(f"[경고] 템플릿을 찾을 수 없습니다: {path}")

    # ------------------------------------------------------- 대상 문서(누적치환)
    def _on_target_mode(self, *_args) -> None:
        cont = self.rb_cont.isChecked()
        self.vm.set_target_mode("continue" if cont else "new")
        self.ed_prev.setEnabled(cont)
        self.btn_prev.setEnabled(cont)
        if not cont:
            self.ed_prev.clear()
            self.lbl_prev_note.setText("")

    def _pick_prev(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "기존 문서 선택", "", HWPX_FILTER
        )
        if not path:
            return
        self.ed_prev.setText(path)
        note = self.vm.set_prev_output(path)
        mark(self.lbl_prev_note, "level", note.level)
        self.lbl_prev_note.setText(note.text)

    # ------------------------------------------ 데이터(겨눔 3종은 공용 계층 위임, RC-22)
    def _pick_data(self) -> None:
        self._data.pick_file()

    def _pick_from_pool(self) -> None:
        """데이터 풀에서 골라 실행 시점 재읽기(싱크) — 복원은 백그라운드(RC-12)."""
        self._data.pick_from_pool()

    def _pick_nara(self) -> None:
        """일회 나라장터 취득(애드혹) — 풀 등록 없이 이번 실행만 겨눈다."""
        self._data.pick_nara()

    def _set_data_busy(self, busy: bool) -> None:
        """데이터 복원(네트워크 가능) 중 겨눔 버튼 잠금 — 진행 중 재진입·경합 방지(RC-12)."""
        for b in (self.btn_pool, self.btn_data, self.btn_nara):
            b.setEnabled(not busy)

    def _after_data_loaded(self, label: str) -> None:
        """데이터 겨눔 공통 꼬리 — 라벨 표시 + 레코드 선택기 채움 + 사전검증/패널 갱신.

        set_records 가 selectionChanged 를 쏘아 _on_selection_changed(사전검증+패널)를 부른다.
        서술 대상(데이터)이 바뀌었으므로 이전 실행의 결과 표면을 먼저 리셋한다
        (UD-10: 완료 후 재겨눔 시 스테일 '완료' 요약·만충 진행바가 현재 상태처럼 잔존하던 결함).
        """
        self._reset_result_surface()
        self.ed_data.setText(label)
        self.selector.set_records(self.vm.records, self.job.filename_pattern)
        self._on_selection_changed()

    def _reset_result_surface(self) -> None:
        """결과 라벨·진행바를 초기화(UD-10) — 서술 대상 변경 이벤트에 결과 수명주기를 결합."""
        self.lbl_result.setText("")
        mark(self.lbl_result, "level", "")
        self.progress.setValue(0)

    def _on_selection_changed(self) -> None:
        """행 선택/데이터가 바뀌면 사전검증·인라인 필드 패널·생성 게이트를 다시 계산."""
        self._refresh_field_panel()

    # ------------------------------- 상시 인라인 필드 패널 + 강제 확인 게이트(ADR-E)
    def _clear_badges(self) -> None:
        while self.badge_flow.count():
            item = self.badge_flow.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                # UD-32 제품 방어: 지연 삭제(deleteLater) 전에 즉시 숨기고 부모에서 떼어
                # 구세대 칩이 DeferredDelete 처리 전까지 유령으로 잔존하지 않게 한다.
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _refresh_field_panel(self) -> None:
        """상태 스냅샷 1회(vm.refresh)로 사전검증·필드 배지·게이트를 함께 렌더(RC-23).

        표시 결정(level/text/활성)은 전부 링1 산출을 **그대로** 렌더한다 — 위젯 재조립이
        만들던 모순 신호(상단 '통과' 녹색 + 하단 드리프트 차단)와 표시면별 재질의의
        템플릿 zip 5회 재파싱을 함께 해소.
        """
        snap = self.vm.refresh(
            self.selector.selected_indices(), self.ed_out.text().strip()
        )
        mark(self.lbl_preflight, "level", snap.preflight.level)
        self.lbl_preflight.setText(snap.preflight.text)
        self._clear_badges()
        if not snap.field_states:
            # 빈 상태 안내(UD-06 · ADR-B '빈 공간으로 보이면 안 됨') — 데이터 미겨눔이면
            # 배지 영역이 통째 공백이 아니라 다음 행동을 발화한다.
            hint = QLabel("데이터를 선택하면 필드별 채움 상태가 여기에 표시됩니다.")
            hint.setWordWrap(True)
            mark(hint, "muted", True)
            self.badge_flow.addWidget(hint)
        for st in snap.field_states:
            if st.state == "filled":
                chip = QLabel(f"✓ {st.name}")
                mark(chip, "fb", "fill")
            elif st.state == "blank":
                chip = QLabel(f"◦ {st.name} (비움)")
                mark(chip, "fb", "blank")
            elif st.state == "drift":
                # 구조 드리프트는 레코드별 값 판단이 아니므로 ack 버튼이 될 수 없다.
                # missing 색 차용 대신 drift 전용 시각 정체성(점선 pill)으로 렌더(UD-16)
                # — 값 문제(클릭형 미입력)와 구조 문제를 시각 분리.
                chip = QLabel(f"⚠ {st.name} — 매핑 재확정 필요")
                mark(chip, "fb", "drift")
                chip.setEnabled(False)
            elif st.acknowledged:
                # UD-19: 확정 ack 도 활성 토글 — 재클릭으로 제자리 철회(비가역 원클릭 해소).
                chip = QPushButton(f"✓ {st.name} — 미입력 표시 예정")
                mark(chip, "fb", "ack")
                chip.setCursor(Qt.PointingHandCursor)
                chip.setToolTip("다시 눌러 확인을 취소합니다(게이트가 다시 닫힙니다).")
                chip.clicked.connect(
                    lambda _checked=False, f=st.name: self._unack_field(f)
                )
            else:
                chip = QPushButton(f"● {st.name} — 미입력 확인")
                mark(chip, "fb", "missing")
                chip.setCursor(Qt.PointingHandCursor)
                chip.clicked.connect(lambda _checked=False, f=st.name: self._ack_field(f))
            self.badge_flow.addWidget(chip)
        self._apply_gate(snap.gate)

    def _ack_field(self, field: str) -> None:
        """미입력 배지 클릭 = 직접 확인(강제 상호작용). 다 확인되면 생성이 열린다."""
        self.vm.acknowledge(field)
        self._refresh_field_panel()

    def _unack_field(self, field: str) -> None:
        """ack 칩 재클릭 = 확인 철회(UD-19 토글) — 게이트가 다시 닫힌다."""
        self.vm.unacknowledge(field)
        self._refresh_field_panel()

    def _apply_gate(self, gate) -> None:
        """링1 게이트 결정(GateState)을 그대로 렌더 — 판정·문구 재조립 금지(RC-23)."""
        self.btn_generate.setEnabled(gate.enabled and not self._running)
        mark(self.lbl_gate, "level", gate.level)
        self.lbl_gate.setText(gate.text)

    def _sync_generate_enabled(self) -> None:
        """게이트만 재평가(teardown 후 버튼 복원 등) — 결정은 vm.gate_state 단일 출처."""
        self._apply_gate(self.vm.gate_state(
            self.selector.selected_indices(), self.ed_out.text().strip()
        ))

    def _pick_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "저장 폴더 선택")
        if path:
            self.ed_out.setText(path)

    # ------------------------------------------------------------------ 생성
    def _on_generate(self) -> None:
        indices = self.selector.selected_indices()
        out_dir = self.ed_out.text().strip()
        errors = self.vm.validate_generate(indices, out_dir)
        if errors:
            err = errors[0]
            if err.level == "danger":
                QMessageBox.critical(self, "오류", err.message)
            else:
                QMessageBox.warning(self, "확인", err.message)
            return

        # ---- 빈칸 게이트(ADR-E): 차단 모달이 아니라 상시 인라인 + 강제 확인. ----
        # 버튼이 이미 미확인 미입력이 있으면 비활성이지만, 방어적으로 재확인한다.
        # "표식 없이 생성" 은 없다 — 미충족 공란을 조용히 내면 "누락은 시끄럽게" 위반
        # (의도적 공란은 매핑이 키를 제외해 이미 조용한 경로가 있다).
        unmet = self.vm.unmet_blanks(indices)
        if unmet:
            self._say("미입력 필드를 먼저 확인하세요: " + ", ".join(unmet))
            self._refresh_field_panel()
            return
        blanks = self.vm.blank_fields(indices)
        self._marked_fields = list(blanks)
        marker = MISSING_MARKER if blanks else ""
        if blanks:
            self._say("미입력 표시 적용: " + ", ".join(blanks))

        # ---- 덮어쓰기 확인(RC-02): 기존 파일을 조용히 파괴하지 않는다. ----
        # 확정 없이 진행하다 충돌하면 generate_batch 가 raise → _on_failed 로 시끄럽게.
        conflicts = self.vm.output_conflicts(indices, out_dir, mark_missing=marker)
        overwrite = False
        if conflicts:
            names = [Path(p).name for p in conflicts]
            shown = "\n".join(names[:10]) + (f"\n… 외 {len(names) - 10}개" if len(names) > 10 else "")
            if not confirm_destructive(
                self, "덮어쓰기 확인",
                f"저장 폴더에 같은 이름의 파일이 이미 있습니다.\n"
                f"계속하면 기존 파일 {len(conflicts)}개를 덮어씁니다:\n\n{shown}",
                "덮어쓰고 진행",
            ):
                self._say("생성 취소 — 기존 파일 덮어쓰기를 확정하지 않았습니다.")
                return
            overwrite = True
            self._say(f"덮어쓰기 확정: 기존 파일 {len(conflicts)}개")

        # ---- 불변 생성 계획 캡처(RC-07): 워커·완료 핸들러·원장이 이것만 소비한다. ----
        # 실행 중 위젯 조작(출력 폴더 편집·데이터 재로드)이 결과·증거에 끼어들 수 없다.
        plan = self.vm.build_generation_plan(
            indices, out_dir, marker=marker,
            ledger=self.chk_ledger.isChecked(), overwrite=overwrite,
        )
        self._plan = plan
        mode = "기존 문서 이어채우기" if self._template_override else "새 문서"
        self._say(f"생성 시작[{mode}]: {len(plan.records)}건 → {plan.out_dir}")

        worker = GenerateWorker(plan)
        worker.stage.connect(self._say)  # '원장 검증 중' 등 단계 고지(RC-07)
        self._runner.start(worker, total=len(plan.records))

    def _on_cancel_generate(self) -> None:
        """협조적 취소(RC-06) — 진행 중 레코드까지 마치고 중단, 부분 결과는 요약으로."""
        self._runner.request_cancel()

    def _on_finished(self, batch) -> None:
        """완료 신호 진입점(스모크/테스트 계약) — 공용 라우팅(teardown+렌더)에 위임."""
        self._runner.finish(batch)

    def _render_finished(self, batch, worker) -> None:
        plan = self._plan
        if plan is None:  # 계획 없는 완료 신호는 배선 오류 — 조용히 무시하지 않는다
            self._say("[오류] 생성 계획이 없는 완료 신호 — 배선 오류입니다.")
            return
        cancelled = bool(getattr(batch, "cancelled", False))
        if cancelled:
            # 부분 결과 요약(RC-06) — 어디까지 만들어졌는지 침묵하지 않는다.
            summary = (
                f"취소됨 — 처리 {batch.attempted}/{batch.total}건 · "
                f"성공 {batch.succeeded} · 미처리 {batch.total - batch.attempted}건"
            )
            mark(self.lbl_result, "level", "warn")
        else:
            summary = f"완료 — 성공 {batch.succeeded}/{batch.total} · 실패 {batch.failed}"
            marked = self._marked_fields
            if marked:
                summary += f" · 미입력 표시 필드 {len(marked)}개({', '.join(marked)})"
            mark(self.lbl_result, "level", "ok" if batch.failed == 0 else "danger")
        self.lbl_result.setText(summary)
        self._say(summary)
        for res in batch.results:
            if not res.ok:
                # 원시 errno 관통 해소(RC-30) — 행동 지향 문구 + 원문 보존.
                self._say(f"  [실패] {res.output_path}: {describe_result_error(res.error)}")
            elif res.unmatched:
                self._say(
                    f"  [주의] 매칭 안 된 필드: {', '.join(res.unmatched)} → "
                    f"{Path(res.output_path).name}"
                )
        # 원장은 워커 꼬리에서 이미 저장·검증됐다(RC-07) — 여기선 결과만 표면화.
        if plan.ledger and worker is not None:
            if worker.ledger_error:
                self._say(f"[원장 실패] 사이드카를 저장하지 못했습니다: {worker.ledger_error}")
                mark(self.lbl_result, "level", "warn")
            elif worker.ledger_path:
                self._say(f"[원장] {worker.ledger_path} 저장 — 값은 텍스트이며 HWPX 렌더가 아닙니다.")
        self.run_finished.emit(batch)
        if not cancelled:
            # 완료 모달은 부분 실패를 무언급하지 않는다(RC-30) — 공용 문구·경고형.
            ask_open_result_folder(self, batch.succeeded, batch.failed, plan.out_dir)

    def _on_failed(self, msg: str) -> None:
        """실패 신호 진입점(스모크/테스트 계약) — 공용 라우팅(RC-07 대칭 정리)에 위임."""
        self._runner.fail(msg)

    def _teardown_thread(self) -> None:
        self._runner.teardown()
