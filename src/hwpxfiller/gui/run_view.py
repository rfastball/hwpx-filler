"""실행(Run) 화면 — 저장된 작업을 골라 데이터·행을 겨눠 생성한다.

트랙 C UX 결정([[hwpx-filler-scope]]): 셋업(에디터)과 실행(여기)을 가른다. 무거운 명시성
게이트(매핑 확정)는 셋업에만 있다 — **여기선 매핑 재확정이 없다.** 실행은 사전검증만 한다.

레이어링(아키텍처 분리): 이 위젯은 **얇은 렌더러/오케스트레이터**다 — 데이터 로드·대상
문서 결정·사전검증·생성 게이트는 :class:`~hwpxfiller.gui.run_state.RunViewModel`(Qt 비의존,
링1)이 소유한다. 위젯은 QThread·QMessageBox·QFileDialog·진행/로그 표현만 담당하고, 백엔드
(``DataSource``·``HwpxEngine``)를 직접 만지지 않는다. ``datasource``/``records``/
``_template_override``/``_effective_template()`` 는 뷰모델로 위임하는 프로퍼티다(스캐폴드·
스모크 계약 보존).
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
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
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.job import MISSING_MARKER, Job
from .flow_layout import FlowLayout
from .record_select import RecordSelector
from .run_state import RunViewModel
from .style import BASE_QSS, mark
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
        self._running = False
        self._thread: "QThread | None" = None
        self._marked_fields: "list[str]" = []  # 이번 생성에서 미입력 표시가 들어간 필드(결과 요약용)

        self.setWindowTitle(f"HWPX Filler — 실행: {job.name}")
        self.resize(760, 680)
        self.setStyleSheet(BASE_QSS)
        # 폼이 세로로 길다 — 창을 줄이면 위젯이 찌그러지지 않고 스크롤되도록 QScrollArea 로 감싼다.
        central = QWidget()
        root = QVBoxLayout(central)

        # ---- 작업 요약 ----
        lbl_job = QLabel(
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

        # ---- 데이터 겨눔 ----
        drow = QHBoxLayout()
        self.ed_data = QLineEdit()
        self.ed_data.setReadOnly(True)
        self.btn_pool = QPushButton("데이터 풀에서…")
        self.btn_pool.clicked.connect(self._pick_from_pool)
        btn_data = QPushButton("파일 선택…")
        btn_data.clicked.connect(self._pick_data)
        self.btn_nara = QPushButton("나라장터…")
        self.btn_nara.clicked.connect(self._pick_nara)
        drow.addWidget(QLabel("데이터"))
        drow.addWidget(self.ed_data, 1)
        drow.addWidget(self.btn_pool)
        drow.addWidget(btn_data)
        drow.addWidget(self.btn_nara)
        root.addLayout(drow)

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

        # ---- 행 선택 ----
        root.addWidget(QLabel("생성 대상 레코드"))
        self.selector = RecordSelector()
        self.selector.selectionChanged.connect(self._on_selection_changed)
        root.addWidget(self.selector, 1)

        # ---- 출력 폴더 ----
        orow = QGridLayout()
        self.ed_out = QLineEdit()
        if job.template_path:
            self.ed_out.setText(str(Path(job.template_path).parent / "Results"))
        btn_out = QPushButton("찾아보기…")
        btn_out.clicked.connect(self._pick_out)
        orow.addWidget(QLabel("저장 폴더"), 0, 0)
        orow.addWidget(self.ed_out, 0, 1)
        orow.addWidget(btn_out, 0, 2)
        # 생성 원장(L2) — 기본 꺼짐(opt-in). 고위험 문서 계보가 필요할 때만 켠다.
        self.chk_ledger = QCheckBox("생성 원장(JSON) 저장 — 들어간 값의 증거")
        self.chk_ledger.setToolTip(
            "저장 폴더에 실행별 fill-ledger-<시각>.json 을 남깁니다(이전 실행 증거 보존): "
            "소스 실제형 샘플, 필드별 주입 예정값, 생성 후 문서 되읽기 검증(✓/✗). "
            "값은 텍스트이며 HWPX 렌더가 아닙니다."
        )
        orow.addWidget(self.chk_ledger, 1, 1)
        root.addLayout(orow)

        # ---- 액션 ----
        actions = QHBoxLayout()
        self.btn_generate = QPushButton("문서 생성")
        mark(self.btn_generate, "primary", True)
        self.btn_generate.clicked.connect(self._on_generate)
        actions.addWidget(self.btn_generate)
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
            self, "기존 문서 선택", "", "HWPX (*.hwpx)"
        )
        if not path:
            return
        self.ed_prev.setText(path)
        note = self.vm.set_prev_output(path)
        mark(self.lbl_prev_note, "level", note.level)
        self.lbl_prev_note.setText(note.text)

    # ------------------------------------------------------------------ 데이터
    def _pick_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "데이터 파일 선택", "", "엑셀/CSV (*.xlsx *.xlsm *.csv)"
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
        self._after_data_loaded(path)

    def _pick_from_pool(self) -> None:
        """데이터 풀(활성 항목)에서 참조를 골라 실행 시점에 재읽기(싱크)한다."""
        from PySide6.QtWidgets import QInputDialog

        from ..core.dataset_pool import STATUS_ACTIVE

        items = self._pool_registry.list_items(status=STATUS_ACTIVE)
        if not items:
            QMessageBox.information(
                self, "데이터 풀", "활성 데이터가 없습니다. 먼저 데이터 풀에 등록하세요."
            )
            return
        names = [it.name for it in items]
        name, ok = QInputDialog.getItem(
            self, "데이터 풀에서 선택", "데이터셋:", names, 0, False
        )
        if not ok or not name:
            return
        item = next(it for it in items if it.name == name)
        try:
            records = self.vm.load_pool_item(
                item, secret_store=self._secret_store, fetcher=self._nara_fetcher
            )
        except Exception as exc:  # noqa: BLE001 - 복원 실패(키 미등록·읽기)는 시끄럽게
            QMessageBox.critical(self, "오류", f"데이터 복원 실패:\n{exc}")
            return
        if not records:
            QMessageBox.warning(self, "확인", "레코드가 없습니다(취득 0건).")
            return
        self._after_data_loaded(f"풀: {item.name}")

    def _pick_nara(self) -> None:
        """일회 나라장터 취득(애드혹) — 풀 등록 없이 이번 실행만 겨눈다."""
        from .nara_view import NaraAcquireDialog

        dlg = NaraAcquireDialog(
            self, store=self._secret_store, fetcher=self._nara_fetcher
        )
        if dlg.exec() != dlg.Accepted or not dlg.records:
            return
        # 대화상자가 키 없는 스냅샷(AcquiredNaraData)을 이미 만들었다 — 그대로 겨눈다.
        self.vm.datasource = dlg.datasource
        self.vm.records = dlg.records
        self.vm.reset_acks()
        self._after_data_loaded(dlg.label)

    def _after_data_loaded(self, label: str) -> None:
        """데이터 겨눔 공통 꼬리 — 라벨 표시 + 레코드 선택기 채움 + 사전검증/패널 갱신.

        set_records 가 selectionChanged 를 쏘아 _on_selection_changed(사전검증+패널)를 부른다.
        """
        self.ed_data.setText(label)
        self.selector.set_records(self.vm.records, self.job.filename_pattern)
        self._on_selection_changed()

    def _on_selection_changed(self) -> None:
        """행 선택/데이터가 바뀌면 사전검증·인라인 필드 패널·생성 게이트를 다시 계산."""
        self._run_preflight()
        self._refresh_field_panel()

    def _run_preflight(self) -> None:
        """사전검증 — 치명(데이터에 없는 항목)만 라벨에. 빈칸은 아래 인라인 패널이 맡는다."""
        pf = self.vm.preflight(self.selector.selected_indices())
        if pf.missing_columns:
            mark(self.lbl_preflight, "level", "danger")
            self.lbl_preflight.setText(
                "[치명] 데이터에 없는 항목입니다(빈칸 생성됨): " + ", ".join(pf.missing_columns)
            )
        elif self.vm.datasource is None:
            mark(self.lbl_preflight, "level", "")
            self.lbl_preflight.setText("")
        else:
            mark(self.lbl_preflight, "level", "ok")
            self.lbl_preflight.setText("사전검증 통과 — 치명 누락 없음. 아래 빈칸 표면화를 확인하세요.")

    # ------------------------------- 상시 인라인 필드 패널 + 강제 확인 게이트(ADR-E)
    def _clear_badges(self) -> None:
        while self.badge_flow.count():
            item = self.badge_flow.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()

    def _refresh_field_panel(self) -> None:
        """뷰모델 필드 상태를 채움/공란/미입력/구조 드리프트 배지로 렌더."""
        self._clear_badges()
        indices = self.selector.selected_indices()
        for st in self.vm.field_states(indices):
            if st.state == "filled":
                chip = QLabel(f"✓ {st.name}")
                mark(chip, "fb", "fill")
            elif st.state == "blank":
                chip = QLabel(f"◦ {st.name} (채우지 않음)")
                mark(chip, "fb", "blank")
            elif st.state == "drift":
                # 구조 드리프트는 레코드별 값 판단이 아니므로 ack 버튼이 될 수 없다.
                chip = QLabel(f"⚠ {st.name} — 매핑 재확정 필요")
                mark(chip, "fb", "missing")
                chip.setEnabled(False)
            elif st.acknowledged:
                chip = QPushButton(f"✓ {st.name} — 미입력 표시 예정")
                mark(chip, "fb", "ack")
                chip.setEnabled(False)
            else:
                chip = QPushButton(f"● {st.name} — 미입력 확인")
                mark(chip, "fb", "missing")
                chip.setCursor(Qt.PointingHandCursor)
                chip.clicked.connect(lambda _checked=False, f=st.name: self._ack_field(f))
            self.badge_flow.addWidget(chip)
        self._sync_generate_enabled()

    def _ack_field(self, field: str) -> None:
        """미입력 배지 클릭 = 직접 확인(강제 상호작용). 다 확인되면 생성이 열린다."""
        self.vm.acknowledge(field)
        self._refresh_field_panel()

    def _sync_generate_enabled(self) -> None:
        indices = self.selector.selected_indices()
        unmet = self.vm.unmet_blanks(indices) if self.vm.datasource is not None else []
        drift = self.vm.structure_drift() if self.vm.datasource is not None else None
        if self._running:
            self.btn_generate.setEnabled(False)
            return
        self.btn_generate.setEnabled(not unmet and not (drift and drift.has_drift))
        if drift and drift.has_drift:
            names = list(drift.template_only) + list(drift.mapping_only) + list(drift.conflicting)
            mark(self.lbl_gate, "level", "danger")
            if drift.read_error:
                self.lbl_gate.setText("템플릿 구조를 읽을 수 없어 생성이 차단됩니다.")
            else:
                self.lbl_gate.setText(
                    "템플릿 구조 드리프트 — 매핑을 다시 확정해야 생성할 수 있습니다: "
                    + ", ".join(names)
                )
        elif unmet:
            mark(self.lbl_gate, "level", "warn")
            self.lbl_gate.setText(
                f"미입력 {len(unmet)}필드를 확인해야 문서 생성이 가능합니다: {', '.join(unmet)}"
            )
        else:
            mark(self.lbl_gate, "level", "")
            self.lbl_gate.setText("")

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
            mapped = self.vm.mapped_records(indices, mark_missing=marker)
            self._say("미입력 표시 적용: " + ", ".join(blanks))
        else:
            mapped = self.vm.mapped_records(indices)
        # 원장 export(_on_finished)가 생성과 동일한 선택·표식으로 행을 재구성하기 위한 문맥.
        self._ledger_ctx = (list(indices), marker) if self.chk_ledger.isChecked() else None

        # ---- 덮어쓰기 확인(RC-02): 기존 파일을 조용히 파괴하지 않는다. ----
        # 확정 없이 진행하다 충돌하면 generate_batch 가 raise → _on_failed 로 시끄럽게.
        conflicts = self.vm.output_conflicts(indices, out_dir, mark_missing=marker)
        overwrite = False
        if conflicts:
            names = [Path(p).name for p in conflicts]
            shown = "\n".join(names[:10]) + (f"\n… 외 {len(names) - 10}개" if len(names) > 10 else "")
            if QMessageBox.question(
                self, "덮어쓰기 확인",
                f"저장 폴더에 같은 이름의 파일이 이미 있습니다.\n"
                f"계속하면 기존 파일 {len(conflicts)}개를 덮어씁니다:\n\n{shown}\n\n"
                "덮어쓰고 진행할까요?",
            ) != QMessageBox.Yes:
                self._say("생성 취소 — 기존 파일 덮어쓰기를 확정하지 않았습니다.")
                return
            overwrite = True
            self._say(f"덮어쓰기 확정: 기존 파일 {len(conflicts)}개")

        template = self.vm.effective_template()
        self._running = True
        self.btn_generate.setEnabled(False)
        self.lbl_result.setText("")
        self.progress.setMaximum(len(mapped))
        self.progress.setValue(0)
        mode = "기존 문서 이어채우기" if self._template_override else "새 문서"
        self._say(f"생성 시작[{mode}]: {len(mapped)}건 → {out_dir}")

        self._thread = QThread()
        self._worker = GenerateWorker(
            template, mapped, out_dir, self.job.filename_pattern, overwrite=overwrite
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda done, total: self.progress.setValue(done))
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _on_finished(self, batch) -> None:
        self._teardown_thread()
        summary = f"완료 — 성공 {batch.succeeded}/{batch.total} · 실패 {batch.failed}"
        marked = getattr(self, "_marked_fields", [])
        if marked:
            summary += f" · 미입력 표시 {len(marked)}필드({', '.join(marked)})"
        mark(self.lbl_result, "level", "ok" if batch.failed == 0 else "danger")
        self.lbl_result.setText(summary)
        self._say(f"완료: {batch.succeeded}/{batch.total} 성공, {batch.failed} 실패")
        for res in batch.results:
            if not res.ok:
                self._say(f"  [실패] {res.output_path}: {res.error}")
            elif res.unmatched:
                self._say(
                    f"  [주의] 매칭 안 된 필드: {', '.join(res.unmatched)} → "
                    f"{Path(res.output_path).name}"
                )
        out_dir = self.ed_out.text().strip()
        ctx = getattr(self, "_ledger_ctx", None)
        if ctx is not None:
            indices, marker = ctx
            try:
                sidecar = self.vm.export_run_ledger(
                    out_dir, indices, batch, mark_missing=marker
                )
                self._say(f"[원장] {sidecar} 저장 — 값은 텍스트이며 HWPX 렌더가 아닙니다.")
            except Exception as exc:  # noqa: BLE001 - 증거 저장 실패는 조용히 넘기지 않는다
                self._say(f"[원장 실패] 사이드카를 저장하지 못했습니다: {exc}")
                mark(self.lbl_result, "level", "warn")
        self.run_finished.emit(batch)
        if batch.succeeded > 0 and QMessageBox.question(
            self, "완료", f"{batch.succeeded}건 생성 완료.\n결과 폴더를 여시겠습니까?"
        ) == QMessageBox.Yes:
            self._open_folder(out_dir)

    def _on_failed(self, msg: str) -> None:
        self._teardown_thread()
        QMessageBox.critical(self, "오류", f"생성 중 오류:\n{msg}")

    def _teardown_thread(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
        self._running = False
        self._sync_generate_enabled()  # 게이트(미확인 미입력) 재평가 후 버튼 상태 복원

    @staticmethod
    def _open_folder(path: str) -> None:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
