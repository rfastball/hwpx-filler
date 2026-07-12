"""매트릭스 실행 화면 — 여러 작업(=템플릿+매핑)을 한 데이터에 일괄 적용해 생성한다.

얇은 렌더러/오케스트레이터: 작업 다중선택·데이터 겨눔·사전검증은
:class:`~hwpxfiller.gui.matrix_state.MatrixRunViewModel`(Qt 비의존)이 소유하고, 생성은
:class:`~hwpxfiller.gui.worker.MatrixGenerateWorker`(QThread)가 :func:`~hwpxfiller.batch.
generate_matrix` 로 수행한다(작업별 하위폴더). QThread 수명주기·완료/실패 라우팅·데이터
겨눔 3종은 단일 실행과 공용 계층(:mod:`~hwpxfiller.gui.batch_run`, RC-22)을 공유한다 —
풀 복원(네트워크 가능)도 그 계층의 TaskWorker 비동기 경로를 그대로 탄다(RC-12).

**매핑 재확정 없음**(매핑은 작업 정의 때 확정). 데이터 겨눔은 단일 실행과 같은 리졸버라
나라 키 마스킹·스냅샷이 그대로 관통한다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .batch_run import (
    BatchRunController,
    DataAcquireController,
    ask_open_result_folder,
    describe_result_error,
)
from .confirm import confirm_destructive
from .flow_layout import FlowLayout
from .matrix_state import MatrixRunViewModel
from .record_select import RecordSelector
from .style import BASE_QSS, mark
from .worker import MatrixGenerateWorker


class MatrixRunView(QMainWindow):
    """여러 작업 일괄 실행 — 작업 다중선택 × 공유 데이터 → 작업별 하위폴더 생성."""

    run_finished = Signal(object)  # MatrixResult

    def __init__(self, job_registry, parent=None, *, pool_registry=None,
                 secret_store=None, nara_fetcher=None):
        super().__init__(parent)
        self.vm = MatrixRunViewModel(
            job_registry, pool_registry=pool_registry,
            secret_store=secret_store, fetcher=nara_fetcher,
        )
        self._secret_store = secret_store
        self._nara_fetcher = nara_fetcher
        self._out_dir = ""  # 이번 생성이 겨눈 저장 폴더(시작 시점 캡처 — 완료 모달용)
        self._marked_missing: "list[tuple[str, str]]" = []  # 이번 생성 표식 필드(UD-04)

        self.setWindowTitle("HWPX Filler — 여러 작업 일괄 실행")
        self.resize(780, 720)
        self.setStyleSheet(BASE_QSS)
        central = QWidget()
        root = QVBoxLayout(central)

        lbl_head = QLabel("선택한 작업들을 한 데이터에 일괄 적용해 생성합니다 "
                          "(작업마다 하위폴더에 저장).")
        mark(lbl_head, "heading", True)
        lbl_head.setWordWrap(True)
        root.addWidget(lbl_head)

        # ---- 작업 다중선택 ----
        job_box = QGroupBox("작업 선택 (여러 개)")
        jb = QVBoxLayout(job_box)
        sel_row = QHBoxLayout()
        self.lbl_sel = QLabel("선택 0개")
        mark(self.lbl_sel, "muted", True)
        btn_all = QPushButton("전체 선택")
        btn_all.clicked.connect(lambda: self._check_all(True))
        btn_none = QPushButton("전체 해제")
        btn_none.clicked.connect(lambda: self._check_all(False))
        sel_row.addWidget(self.lbl_sel)
        sel_row.addStretch(1)
        sel_row.addWidget(btn_all)
        sel_row.addWidget(btn_none)
        jb.addLayout(sel_row)
        self.job_list = QListWidget()
        self.job_list.setObjectName("jobList")
        # 세로 예산(UD-42): 대부분 공백인 작업 리스트가 무제한 선호높이를 고집해 표준
        # 크기에서도 페이지 스크롤을 유발하던 것을 빌더식 캡으로 막는다(내부 대조:
        # pipeline_builder 보조 리스트 setMaximumHeight). 내부 스크롤로 다량도 수용.
        self.job_list.setMaximumHeight(150)
        self.job_list.itemChanged.connect(self._on_job_toggled)
        jb.addWidget(self.job_list)
        root.addWidget(job_box)
        self._populate_jobs()

        # ---- 데이터 겨눔 ----
        drow = QHBoxLayout()
        self.ed_data = QLineEdit()
        self.ed_data.setReadOnly(True)
        self.btn_pool = QPushButton("데이터 풀에서…")
        self.btn_pool.clicked.connect(self._pick_from_pool)
        self.btn_file = QPushButton("파일 선택…")
        self.btn_file.clicked.connect(self._pick_file)
        self.btn_nara = QPushButton("나라장터…")
        self.btn_nara.clicked.connect(self._pick_nara)
        drow.addWidget(QLabel("데이터"))
        drow.addWidget(self.ed_data, 1)
        drow.addWidget(self.btn_pool)
        drow.addWidget(self.btn_file)
        drow.addWidget(self.btn_nara)
        root.addLayout(drow)

        # ---- 미입력 필드 확인(작업별 3상태 배지 + 강제 확인 게이트, UD-04·ADR-B/E) ----
        # 단일 실행의 하드스톱이 매트릭스 우회로 조용히 소멸하던 결함의 봉합 — 작업별
        # 필드 스냅샷을 배지로 노출하고, 미확인 미입력이 있으면 일괄 생성을 막는다.
        gate_box = QGroupBox("미입력 필드 확인")
        gbl = QVBoxLayout(gate_box)
        lbl_gate_help = QLabel(
            "작업별 필드 상태를 확인하세요. 미입력 필드는 직접 확인해야 일괄 생성이 가능합니다."
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

        # ---- 행 선택 ----
        root.addWidget(QLabel("생성 대상 레코드"))
        self.selector = RecordSelector()
        self.selector.selectionChanged.connect(self._refresh_field_panel)
        # 세로 예산(UD-42): 두 번째 리스트 단도 캡해 표준 크기에서 결과·로그 푸터가
        # 접힘 아래로 밀리지 않게 한다(내부 스크롤로 다량 레코드 수용).
        self.selector.setMaximumHeight(200)
        root.addWidget(self.selector)

        # ---- 출력 폴더 ----
        orow = QGridLayout()
        self.ed_out = QLineEdit()
        btn_out = QPushButton("찾아보기…")
        btn_out.clicked.connect(self._pick_out)
        orow.addWidget(QLabel("저장 폴더(작업별 하위폴더 생성)"), 0, 0)
        orow.addWidget(self.ed_out, 0, 1)
        orow.addWidget(btn_out, 0, 2)
        root.addLayout(orow)

        # ---- 액션·진행·결과·로그: 고정 푸터(UD-42) ----
        # 스크롤되는 폼(위) 밖의 고정 푸터로 둬, 표준·좁은 폭 모두에서 결과 라벨·로그가
        # 접힘 아래로 밀리지 않고 상시 보이게 한다(무제한 리스트 예산 전가의 봉합).
        outer = QWidget()
        outer_l = QVBoxLayout(outer)
        outer_l.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(central)
        outer_l.addWidget(scroll, 1)

        actions = QHBoxLayout()
        self.btn_generate = QPushButton("일괄 생성")
        mark(self.btn_generate, "primary", True)
        self.btn_generate.clicked.connect(self._on_generate)
        actions.addWidget(self.btn_generate)
        # 실행 중 협조적 취소(RC-06) — 작업·레코드 경계에서 중단, 부분 결과 요약.
        self.btn_cancel = QPushButton("생성 취소")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel_generate)
        actions.addWidget(self.btn_cancel)
        actions.addStretch(1)
        outer_l.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        outer_l.addWidget(self.progress)
        self.lbl_result = QLabel("")
        self.lbl_result.setWordWrap(True)
        outer_l.addWidget(self.lbl_result)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)  # 푸터 로그도 캡 — 푸터가 폼을 압도하지 않게.
        outer_l.addWidget(self.log)

        self.setCentralWidget(outer)
        self._sync_sel_label()

        # ---- 공용 실행 계층(RC-22) — QThread 수명주기·데이터 겨눔은 단일 실행과 공유 ----
        self._runner = BatchRunController(
            self, progress=self.progress, lbl_result=self.lbl_result,
            btn_generate=self.btn_generate, btn_cancel=self.btn_cancel,
            say=self._say,
            # UD-04: 이제 매트릭스에도 미입력 확인 게이트가 있다 — teardown 후 버튼을
            # 무조건 재활성하지 않고 게이트 결정을 재적용한다(미확인 미입력이 남으면 잠금).
            on_idle=self._sync_generate_enabled,
            on_result=self._render_finished,
        )
        self._data = DataAcquireController(
            self, pool_registry=self.vm.pool_registry,
            load_file=self.vm.load_file,
            restore_pool_item=self.vm.load_pool_item,
            set_acquired=self.vm.set_acquired,
            after_loaded=self._after_data_loaded,
            say=self._say, set_busy=self._set_data_busy,
            secret_store=self._secret_store, nara_fetcher=self._nara_fetcher,
        )
        # 초기 배지·게이트 렌더(빈 상태 안내) — _running 을 읽으므로 _runner 생성 뒤에 둔다.
        self._refresh_field_panel()

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

    @property
    def _data_thread(self):
        return self._data.thread

    # ------------------------------------------------------------- 작업 목록
    def _populate_jobs(self) -> None:
        self.job_list.blockSignals(True)
        self.job_list.clear()
        for name in self.vm.all_job_names():
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if self.vm.is_selected(name) else Qt.Unchecked)
            self.job_list.addItem(item)
        self.job_list.blockSignals(False)

    def _on_job_toggled(self, item: QListWidgetItem) -> None:
        self.vm.set_job_selected(item.text(), item.checkState() == Qt.Checked)
        self._sync_sel_label()
        self._refresh_field_panel()  # 선택 작업 변경 → 배지·게이트 재계산(UD-04)

    def _check_all(self, on: bool) -> None:
        self.job_list.blockSignals(True)
        state = Qt.Checked if on else Qt.Unchecked
        for i in range(self.job_list.count()):
            it = self.job_list.item(i)
            it.setCheckState(state)
            self.vm.set_job_selected(it.text(), on)
        self.job_list.blockSignals(False)
        self._sync_sel_label()
        self._refresh_field_panel()  # 선택 작업 변경 → 배지·게이트 재계산(UD-04)

    def _sync_sel_label(self) -> None:
        n = self.vm.selection_count()
        self.lbl_sel.setText(f"선택 {n}개")
        mark(self.lbl_sel, "level", "ok" if n else "")

    # --------------------------- 작업별 필드 3상태 배지 + 강제 확인 게이트(UD-04·ADR-B/E)
    def _clear_badges(self) -> None:
        while self.badge_flow.count():
            item = self.badge_flow.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                # 지연 삭제 전에 즉시 숨기고 부모에서 떼어 유령 칩 잔존을 막는다(UD-32 대칭).
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _refresh_field_panel(self) -> None:
        """작업별 필드 스냅샷(vm.field_summaries)을 배지로 렌더 + 확인 게이트 적용(UD-04).

        단일 실행과 같은 링1 산출을 소비한다 — 위젯은 표시 결정(배지 상태·게이트
        level/text/활성)을 **그대로** 렌더하고 재조립하지 않는다. 미확인 미입력이
        남으면 게이트가 '버튼 비활성 + 인라인 사유'로 일괄 생성을 막는다.
        """
        self._clear_badges()
        summaries = self.vm.field_summaries(self.selector.selected_indices())
        if not summaries:
            hint = QLabel("작업과 데이터를 선택하면 작업별 필드 채움 상태가 여기에 표시됩니다.")
            hint.setWordWrap(True)
            mark(hint, "muted", True)
            self.badge_flow.addWidget(hint)
        for js in summaries:
            head = QLabel(f"[{js.job_name}]")
            mark(head, "muted", True)
            self.badge_flow.addWidget(head)
            for st in js.field_states:
                self.badge_flow.addWidget(self._make_chip(js.job_name, st))
        self._apply_gate(self.vm.missing_gate(self.selector.selected_indices()))

    def _make_chip(self, job_name: str, st):
        """필드 1개의 상태 배지 — 미입력만 클릭형(확인/철회 토글), 나머지는 정적 라벨."""
        if st.state == "filled":
            chip = QLabel(f"✓ {st.name}")
            mark(chip, "fb", "fill")
        elif st.state == "blank":
            chip = QLabel(f"◦ {st.name} (비움)")
            mark(chip, "fb", "blank")
        elif st.state == "drift":
            # 구조 드리프트는 레코드별 값 문제가 아니라 매핑 재확정 대상 — validate 하드스톱
            # 이 별도로 막는다. 여기선 비클릭 전용 정체성(점선)으로 값 문제와 시각 분리.
            chip = QLabel(f"⚠ {st.name} — 매핑 재확정 필요")
            mark(chip, "fb", "drift")
            chip.setEnabled(False)
        elif st.acknowledged:
            chip = QPushButton(f"✓ {st.name} — 미입력 표시 예정")
            mark(chip, "fb", "ack")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setToolTip("다시 눌러 확인을 취소합니다(게이트가 다시 닫힙니다).")
            chip.clicked.connect(
                lambda _c=False, j=job_name, f=st.name: self._unack_field(j, f)
            )
        else:
            chip = QPushButton(f"● {st.name} — 미입력 확인")
            mark(chip, "fb", "missing")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(
                lambda _c=False, j=job_name, f=st.name: self._ack_field(j, f)
            )
        return chip

    def _ack_field(self, job_name: str, field: str) -> None:
        """미입력 배지 클릭 = 직접 확인(강제 상호작용). 다 확인되면 일괄 생성이 열린다."""
        self.vm.acknowledge(job_name, field)
        self._refresh_field_panel()

    def _unack_field(self, job_name: str, field: str) -> None:
        """ack 칩 재클릭 = 확인 철회(토글) — 게이트가 다시 닫힌다."""
        self.vm.unacknowledge(job_name, field)
        self._refresh_field_panel()

    def _apply_gate(self, gate) -> None:
        """링1 게이트 결정(GateState)을 그대로 렌더 — 판정·문구 재조립 금지."""
        self.btn_generate.setEnabled(gate.enabled and not self._running)
        mark(self.lbl_gate, "level", gate.level)
        self.lbl_gate.setText(gate.text)

    def _sync_generate_enabled(self) -> None:
        """게이트만 재평가(teardown 후 버튼 복원 등) — 결정은 vm.missing_gate 단일 출처."""
        self._apply_gate(self.vm.missing_gate(self.selector.selected_indices()))

    # ------------------------------------------ 데이터(겨눔 3종은 공용 계층 위임, RC-22)
    def _say(self, msg: str) -> None:
        self.log.appendPlainText(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _pick_file(self) -> None:
        self._data.pick_file()

    def _pick_from_pool(self) -> None:
        """데이터 풀에서 골라 실행 시점 재읽기(싱크) — 복원은 백그라운드(RC-12)."""
        self._data.pick_from_pool()

    def _pick_nara(self) -> None:
        """일회 나라장터 취득(애드혹) — 풀 등록 없이 이번 실행만 겨눈다."""
        self._data.pick_nara()

    def _set_data_busy(self, busy: bool) -> None:
        """데이터 복원(네트워크 가능) 중 겨눔 버튼 잠금 — 진행 중 재진입·경합 방지(RC-12)."""
        for b in (self.btn_pool, self.btn_file, self.btn_nara):
            b.setEnabled(not busy)

    def _after_data_loaded(self, label: str) -> None:
        self.ed_data.setText(label)
        self.selector.set_records(self.vm.records, "행-{{seq}}")
        self._say(f"데이터 겨눔: {label} — {len(self.vm.records)}행")
        self._refresh_field_panel()  # 새 데이터 → 작업별 필드 배지·게이트 재계산(UD-04)

    def _pick_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "저장 폴더 선택")
        if path:
            self.ed_out.setText(path)

    # ------------------------------------------------------------------ 생성
    def _on_generate(self) -> None:
        indices = self.selector.selected_indices()
        out_dir = self.ed_out.text().strip()
        errors = self.vm.validate(indices, out_dir)
        if errors:
            QMessageBox.warning(self, "확인", "\n".join(errors))
            return
        # ---- 미입력 확인 게이트(UD-04·ADR-E): 단일 실행의 하드스톱이 매트릭스 우회로
        # 조용히 소멸하지 않게 한다. 버튼은 미확인 미입력이 있으면 이미 비활성이지만
        # (게이트 렌더), worker/API 우회에도 방어적으로 재확인해 원자 차단한다.
        unmet = self.vm.unmet_missing(indices)
        if unmet:
            names = "; ".join(f"{jn}·{f}" for jn, f in unmet)
            self._say(f"미입력 필드를 먼저 확인하세요: {names}")
            self._refresh_field_panel()
            return
        # 이번 생성에서 표식이 들어갈 미입력 필드(확인 완료분) — 완료 요약이 병기한다
        # (표식 포함 문서를 무언급으로 '성공' 집계하던 낙관 서사 해소).
        self._marked_missing = [
            (js.job_name, s.name)
            for js in self.vm.field_summaries(indices)
            for s in js.field_states if s.state == "missing"
        ]
        # ---- 덮어쓰기 확인(RC-02): 기존 파일을 조용히 파괴하지 않는다. ----
        conflicts = self.vm.output_conflicts(indices, out_dir)
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
        jobs = self.vm.selected_jobs()
        self._out_dir = out_dir  # 완료 모달이 소비(시작 시점 캡처 — 실행 중 편집 무관)
        self._say(f"일괄 생성 시작: 작업 {len(jobs)}개 × 레코드 {len(indices)}건 → {out_dir}")

        worker = MatrixGenerateWorker(
            jobs, self.vm.datasource, indices, out_dir, overwrite=overwrite
        )
        self._runner.start(worker, total=len(jobs) * len(indices))

    def _on_cancel_generate(self) -> None:
        """협조적 취소(RC-06) — 진행 중인 레코드까지 마치고 중단한다."""
        self._runner.request_cancel()

    def _on_finished(self, result) -> None:
        """완료 신호 진입점(스모크/테스트 계약) — 공용 라우팅(teardown+렌더)에 위임."""
        self._runner.finish(result)

    def _render_finished(self, result, _worker) -> None:
        cancelled = bool(getattr(result, "cancelled", False))
        if cancelled:
            # 부분 결과 요약(RC-06) — 처리된 작업/문서 수를 침묵하지 않는다.
            attempted = sum(len(jr.batch.results) for jr in result.per_job)
            summary = (
                f"취소됨 — 작업 {result.job_count}개 처리 · 문서 {attempted}건 시도 · "
                f"성공 {result.succeeded}"
            )
            mark(self.lbl_result, "level", "warn")
        else:
            summary = (
                f"완료 — 작업 {result.job_count}개, 문서 {result.succeeded}/{result.total} 성공 · "
                f"실패 {result.failed}"
            )
            if self._marked_missing:
                # 표식 포함 문서를 무언급으로 '성공' 집계하던 낙관 서사 해소(UD-04) —
                # 확인된 미입력이라도 표식이 들어갔음을 완료 시점에 병기한다.
                summary += f" · 미입력 표시 {len(self._marked_missing)}필드"
            mark(self.lbl_result, "level", "ok" if result.failed == 0 else "danger")
        self.lbl_result.setText(summary)
        self._say(summary)
        for jr in result.per_job:
            self._say(
                f"  [{jr.job_name}] {jr.batch.succeeded}/{jr.batch.total} → "
                f"{Path(jr.out_dir).name}/"
            )
            for res in jr.batch.results:
                if not res.ok:
                    # 실패 개별 사유 — 원시 errno 관통 해소(RC-30), 행동 지향 문구.
                    self._say(f"    [실패] {res.output_path}: {describe_result_error(res.error)}")
        self.run_finished.emit(result)
        if not cancelled:
            # 완료 모달은 부분 실패를 무언급하지 않는다(RC-30) — 공용 문구·경고형.
            ask_open_result_folder(self, result.succeeded, result.failed, self._out_dir)

    def _on_failed(self, msg: str) -> None:
        """실패 신호 진입점(스모크/테스트 계약) — 공용 라우팅(RC-07 대칭 정리)에 위임."""
        self._runner.fail(msg)

    def _teardown_thread(self) -> None:
        self._runner.teardown()
