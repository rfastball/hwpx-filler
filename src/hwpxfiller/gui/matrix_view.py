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

        # ---- 행 선택 ----
        root.addWidget(QLabel("생성 대상 레코드"))
        self.selector = RecordSelector()
        root.addWidget(self.selector, 1)

        # ---- 출력 폴더 ----
        orow = QGridLayout()
        self.ed_out = QLineEdit()
        btn_out = QPushButton("찾아보기…")
        btn_out.clicked.connect(self._pick_out)
        orow.addWidget(QLabel("저장 폴더(작업별 하위폴더 생성)"), 0, 0)
        orow.addWidget(self.ed_out, 0, 1)
        orow.addWidget(btn_out, 0, 2)
        root.addLayout(orow)

        # ---- 액션 ----
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
        root.addLayout(actions)

        self.progress = QProgressBar()
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
        self._sync_sel_label()

        # ---- 공용 실행 계층(RC-22) — QThread 수명주기·데이터 겨눔은 단일 실행과 공유 ----
        self._runner = BatchRunController(
            self, progress=self.progress, lbl_result=self.lbl_result,
            btn_generate=self.btn_generate, btn_cancel=self.btn_cancel,
            say=self._say,
            # 매트릭스엔 인라인 게이트가 없다 — teardown 후 생성 버튼 단순 재활성.
            on_idle=lambda: self.btn_generate.setEnabled(True),
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

    def _check_all(self, on: bool) -> None:
        self.job_list.blockSignals(True)
        state = Qt.Checked if on else Qt.Unchecked
        for i in range(self.job_list.count()):
            it = self.job_list.item(i)
            it.setCheckState(state)
            self.vm.set_job_selected(it.text(), on)
        self.job_list.blockSignals(False)
        self._sync_sel_label()

    def _sync_sel_label(self) -> None:
        n = self.vm.selection_count()
        self.lbl_sel.setText(f"선택 {n}개")
        mark(self.lbl_sel, "level", "ok" if n else "")

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
