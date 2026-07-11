"""집행(Run) 화면 — 저장된 작업을 골라 데이터·행을 겨눠 생성한다.

트랙 C UX 결정([[hwpx-filler-scope]]): 셋업(에디터)과 집행(여기)을 가른다. 무거운 명시성
게이트(매핑 확정)는 셋업에만 있다 — **여기선 매핑 재확정이 없다.** 집행은 사전검증만 한다.

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

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
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
    QVBoxLayout,
    QWidget,
)

from ..core.job import MISSING_MARKER, Job
from .record_select import RecordSelector
from .run_state import RunViewModel
from .style import BASE_QSS, mark
from .worker import GenerateWorker


class RunView(QMainWindow):
    """작업 1건을 집행 — 데이터 겨눔 → 행 선택 → 사전검증 → 생성."""

    run_finished = Signal(object)  # BatchResult
    back_requested = Signal()

    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        self.job = job
        self.vm = RunViewModel(job)            # 집행 결정(Qt 비의존)
        self._running = False
        self._thread: "QThread | None" = None
        self._marked_fields: "list[str]" = []  # 이번 생성에서 표식 주입된 필드(결과 요약용)

        self.setWindowTitle(f"HWPX Filler — 집행: {job.name}")
        self.resize(760, 680)
        self.setStyleSheet(BASE_QSS)
        central = QWidget()
        self.setCentralWidget(central)
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
        self.rb_cont = QRadioButton("이전 출력 이어채우기 — 이전 단계 출력(.hwpx)에 이 단계 값을 채웁니다")
        self.rb_new.toggled.connect(self._on_target_mode)
        tb.addWidget(self.rb_new)
        tb.addWidget(self.rb_cont)
        prow = QHBoxLayout()
        self.ed_prev = QLineEdit()
        self.ed_prev.setReadOnly(True)
        self.btn_prev = QPushButton("이전 출력 선택…")
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

        # ---- 데이터 겨눔(이음새) ----
        drow = QHBoxLayout()
        self.ed_data = QLineEdit()
        self.ed_data.setReadOnly(True)
        btn_data = QPushButton("데이터 선택…")
        btn_data.clicked.connect(self._pick_data)
        drow.addWidget(QLabel("데이터(.xlsx/.csv)"))
        drow.addWidget(self.ed_data, 1)
        drow.addWidget(btn_data)
        root.addLayout(drow)

        # ---- 사전검증(표시) ----
        self.lbl_preflight = QLabel("")
        self.lbl_preflight.setWordWrap(True)
        root.addWidget(self.lbl_preflight)

        # ---- 행 선택 ----
        root.addWidget(QLabel("생성 대상 레코드"))
        self.selector = RecordSelector()
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
        root.addLayout(orow)

        # ---- 액션 ----
        actions = QHBoxLayout()
        self.btn_generate = QPushButton("생성")
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

        self._check_template()

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
            self, "이전 출력 선택", "", "HWPX (*.hwpx)"
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
        self.ed_data.setText(path)
        self.selector.set_records(self.vm.records, self.job.filename_pattern)
        self._run_preflight()

    def _run_preflight(self) -> None:
        """사전검증 표시 — 뷰모델 판정을 라벨에 반영. 매핑 재확정 아님."""
        pf = self.vm.preflight(self.selector.selected_indices())
        mark(self.lbl_preflight, "level", pf.level)
        self.lbl_preflight.setText(pf.text)

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

        # ---- 능동 빈칸 게이트: 수동 로그가 아니라 물어보고 표식을 넣는다. ----
        # "표식 없이 생성" 은 없다 — 미충족 공란을 조용히 내면 "누락은 시끄럽게" 위반
        # (의도적 공란은 매핑이 키를 제외해 이미 조용한 경로가 있다).
        pf = self.vm.preflight(indices)
        self._marked_fields = list(pf.empty_valued)
        if self._marked_fields:
            if QMessageBox.question(
                self, "빈칸 확인",
                f"빈칸 {len(self._marked_fields)}필드 — {', '.join(self._marked_fields)}\n\n"
                f"미입력 표식({MISSING_MARKER.format(field='필드')})을 넣고 생성할까요?\n"
                "표식은 누름틀로 남아 한글에서 클릭해 채우거나, 다음 단계 "
                "이어채우기에서 덮입니다.",
            ) != QMessageBox.Yes:
                return
            mapped = self.vm.mapped_records(indices, mark_missing=MISSING_MARKER)
        else:
            mapped = self.vm.mapped_records(indices)
        issues = pf.issues()
        if issues:
            self._say("사전검증 이슈: " + ", ".join(issues))

        template = self.vm.effective_template()
        self._running = True
        self.btn_generate.setEnabled(False)
        self.lbl_result.setText("")
        self.progress.setMaximum(len(mapped))
        self.progress.setValue(0)
        mode = "누적(이전 출력 이어채우기)" if self._template_override else "신규"
        self._say(f"생성 시작[{mode}]: {len(mapped)}건 → {out_dir}")

        self._thread = QThread()
        self._worker = GenerateWorker(
            template, mapped, out_dir, self.job.filename_pattern
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
            summary += f" · 미입력 표식 {len(marked)}필드({', '.join(marked)})"
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
        self.run_finished.emit(batch)
        out_dir = self.ed_out.text().strip()
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
        self.btn_generate.setEnabled(True)

    @staticmethod
    def _open_folder(path: str) -> None:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
