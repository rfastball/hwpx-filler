"""PySide6 메인 창 — 템플릿·데이터 선택 → 검증 → 일괄 생성."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread
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
    QVBoxLayout,
    QWidget,
)

from ..core.engine import HwpxEngine
from ..core.validate import validate
from ..data.excel import ExcelDataSource
from .worker import GenerateWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HWPX Filler — 누름틀 일괄 생성기")
        self.resize(720, 560)
        self._records: list[dict] = []
        self._thread: QThread | None = None
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # --- 입력 그룹 ---
        box = QGroupBox("입력")
        grid = QGridLayout(box)

        self.ed_template = QLineEdit(); self.ed_template.setReadOnly(True)
        self.ed_data = QLineEdit(); self.ed_data.setReadOnly(True)
        self.ed_out = QLineEdit()
        self.ed_pattern = QLineEdit("공고서-{{ID}}")

        grid.addWidget(QLabel("템플릿(.hwpx)"), 0, 0)
        grid.addWidget(self.ed_template, 0, 1)
        btn_t = QPushButton("찾아보기…"); btn_t.clicked.connect(self._pick_template)
        grid.addWidget(btn_t, 0, 2)

        grid.addWidget(QLabel("데이터(.xlsx/.csv)"), 1, 0)
        grid.addWidget(self.ed_data, 1, 1)
        btn_d = QPushButton("찾아보기…"); btn_d.clicked.connect(self._pick_data)
        grid.addWidget(btn_d, 1, 2)

        grid.addWidget(QLabel("저장 폴더"), 2, 0)
        grid.addWidget(self.ed_out, 2, 1)
        btn_o = QPushButton("찾아보기…"); btn_o.clicked.connect(self._pick_out)
        grid.addWidget(btn_o, 2, 2)

        grid.addWidget(QLabel("파일명 패턴"), 3, 0)
        grid.addWidget(self.ed_pattern, 3, 1)
        grid.addWidget(QLabel("토큰: {{필드}}, {{date:YYYYMMDD}}, {{seq:001}}"), 3, 2)

        root.addWidget(box)

        # --- 액션 버튼 ---
        actions = QHBoxLayout()
        self.btn_validate = QPushButton("검증"); self.btn_validate.clicked.connect(self._on_validate)
        self.btn_generate = QPushButton("생성"); self.btn_generate.clicked.connect(self._on_generate)
        self.btn_generate.setEnabled(False)
        actions.addWidget(self.btn_validate)
        actions.addWidget(self.btn_generate)
        actions.addStretch(1)
        root.addLayout(actions)

        # --- 진행/로그 ---
        self.progress = QProgressBar(); self.progress.setValue(0)
        root.addWidget(self.progress)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        root.addWidget(self.log, 1)

    # -------------------------------------------------------------- pickers
    def _pick_template(self):
        p, _ = QFileDialog.getOpenFileName(self, "HWPX 템플릿 선택", "", "HWPX (*.hwpx)")
        if p:
            self.ed_template.setText(p)
            if not self.ed_out.text():
                self.ed_out.setText(str(Path(p).parent / "Results"))

    def _pick_data(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "데이터 파일 선택", "", "엑셀/CSV (*.xlsx *.xlsm *.csv)")
        if p:
            self.ed_data.setText(p)

    def _pick_out(self):
        p = QFileDialog.getExistingDirectory(self, "저장 폴더 선택")
        if p:
            self.ed_out.setText(p)

    # --------------------------------------------------------------- logging
    def _say(self, msg: str):
        self.log.appendPlainText(msg)

    # -------------------------------------------------------------- validate
    def _on_validate(self) -> bool:
        template = self.ed_template.text().strip()
        data = self.ed_data.text().strip()
        if not template or not Path(template).exists():
            QMessageBox.warning(self, "확인", "유효한 템플릿(.hwpx)을 선택하세요.")
            return False
        if not data or not Path(data).exists():
            QMessageBox.warning(self, "확인", "유효한 데이터 파일을 선택하세요.")
            return False

        self.log.clear()
        try:
            engine = HwpxEngine()
            required = engine.required_fields(template)
            self._records = ExcelDataSource(data).records()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"검증 중 오류:\n{exc}")
            return False

        self._say(f"템플릿 요구 누름틀 {len(required)}개: {', '.join(required) or '(없음)'}")
        self._say(f"데이터 레코드 {len(self._records)}건 로드")

        report = validate(required, self._records)
        if report.missing_columns:
            self._say(f"[치명] 데이터에 없는 필드(빈칸 생성됨): {', '.join(report.missing_columns)}")
        if report.empty_valued:
            self._say(f"[경고] 값이 비어있는 행이 있는 필드: {', '.join(report.empty_valued)}")
        if not report.has_issues:
            self._say("검증 통과 — 누락/빈 값 없음.")

        ok = len(self._records) > 0
        self.btn_generate.setEnabled(ok)
        return ok

    # -------------------------------------------------------------- generate
    def _on_generate(self):
        if not self._records and not self._on_validate():
            return
        out_dir = self.ed_out.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "확인", "저장 폴더를 지정하세요.")
            return
        pattern = self.ed_pattern.text().strip() or "output-{{ID}}"

        self.btn_generate.setEnabled(False)
        self.btn_validate.setEnabled(False)
        self.progress.setMaximum(len(self._records))
        self.progress.setValue(0)
        self._say(f"생성 시작: {len(self._records)}건 → {out_dir}")

        self._thread = QThread()
        self._worker = GenerateWorker(self.ed_template.text().strip(), self._records, out_dir, pattern)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _on_progress(self, done: int, total: int):
        self.progress.setValue(done)

    def _on_finished(self, batch):
        self._teardown_thread()
        self._say(f"완료: {batch.succeeded}/{batch.total} 성공, {batch.failed} 실패")
        for res in batch.results:
            if not res.ok:
                self._say(f"  [실패] {res.output_path}: {res.error}")
            elif res.unmatched:
                self._say(f"  [주의] 매칭 안 된 필드: {', '.join(res.unmatched)} → {Path(res.output_path).name}")
        self.btn_generate.setEnabled(True)
        self.btn_validate.setEnabled(True)

        out_dir = self.ed_out.text().strip()
        if batch.succeeded > 0 and QMessageBox.question(
            self, "완료", f"{batch.succeeded}건 생성 완료.\n결과 폴더를 여시겠습니까?"
        ) == QMessageBox.Yes:
            self._open_folder(out_dir)

    def _on_failed(self, msg: str):
        self._teardown_thread()
        QMessageBox.critical(self, "오류", f"생성 중 오류:\n{msg}")
        self.btn_generate.setEnabled(True)
        self.btn_validate.setEnabled(True)

    def _teardown_thread(self):
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None

    @staticmethod
    def _open_folder(path: str):
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
