"""집행(Run) 화면 — 저장된 작업을 골라 데이터·행을 겨눠 생성한다.

트랙 C UX 결정([[hwpx-filler-scope]]): 셋업(에디터)과 집행(여기)을 가른다. 무거운 명시성
게이트(매핑 확정)는 셋업에만 있다 — **여기선 매핑 재확정이 없다.** 집행은 사전검증만 한다.

- **데이터는 이음새 뒤.** 지금은 :class:`~hwpxfiller.data.excel.ExcelDataSource` 를 고르지만
  ``self.datasource`` 는 추상 참조다 — 누적치환(이전 출력을 소스로)·나라장터 세부·API 직결은
  같은 이음새에 꽂히는 미래의 *소스 종류*다(여기서 종류로 분기하지 않는다).
- **사전검증**은 :class:`~hwpxfiller.core.job.RunRequest` 가 Qt 밖에서 판정한 걸 표시만 한다.

**스캐폴드 범위:** 배선까지만. 소스-종류 선택기(신규 vs 이전출력)·능동 빈칸 게이트+표식
렌더·레이아웃/스타일은 후속 디자인 패스의 몫이다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
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

from ..core.job import Job, RunRequest
from ..data.excel import ExcelDataSource
from .record_select import RecordSelector
from .worker import GenerateWorker


class RunView(QMainWindow):
    """작업 1건을 집행 — 데이터 겨눔 → 행 선택 → 사전검증 → 생성."""

    run_finished = Signal(object)  # BatchResult
    back_requested = Signal()

    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        self.job = job
        self.datasource = None                 # DataSource 이음새(현재 Excel)
        self.records: "list[dict]" = []
        self._running = False
        self._thread: "QThread | None" = None

        self.setWindowTitle(f"HWPX Filler — 집행: {job.name}")
        self.resize(760, 620)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ---- 작업 요약 ----
        root.addWidget(QLabel(
            f"작업: {job.name}  ·  템플릿: {Path(job.template_path).name}  ·  "
            f"파일명: {job.filename_pattern}"
        ))

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
        self.btn_generate.clicked.connect(self._on_generate)
        actions.addWidget(self.btn_generate)
        actions.addStretch(1)
        root.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(self.log, 1)

        self._check_template()

    # ------------------------------------------------------------------ helpers
    def _say(self, msg: str) -> None:
        self.log.appendPlainText(msg)

    def _check_template(self) -> None:
        if self.job.template_path and not Path(self.job.template_path).exists():
            self._say(f"[경고] 템플릿을 찾을 수 없습니다: {self.job.template_path}")

    def _request(self) -> RunRequest:
        return RunRequest(self.job, self.datasource, self.selector.selected_indices())

    # ------------------------------------------------------------------ 데이터
    def _pick_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "데이터 파일 선택", "", "엑셀/CSV (*.xlsx *.xlsm *.csv)"
        )
        if not path:
            return
        try:
            source = ExcelDataSource(path)
            records = source.records()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"데이터 로드 실패:\n{exc}")
            return
        if not records:
            QMessageBox.warning(self, "확인", "레코드가 없습니다. 다른 파일을 선택하세요.")
            return
        self.ed_data.setText(path)
        self.datasource = source
        self.records = records
        self.selector.set_records(records, self.job.filename_pattern)
        self._run_preflight()

    def _run_preflight(self) -> None:
        """사전검증 표시 — 빠진 소스키(치명)·매핑 출력의 빈값(경고). 매핑 재확정 아님."""
        if self.datasource is None:
            self.lbl_preflight.setText("")
            return
        req = self._request()
        src = req.source_report()
        out = req.output_report()
        parts: "list[str]" = []
        if src.missing_columns:
            parts.append(
                "[치명] 데이터에 없는 소스키(빈칸 생성됨): " + ", ".join(src.missing_columns)
            )
        if out.empty_valued:
            parts.append("[경고] 값이 비어 있는 필드: " + ", ".join(out.empty_valued))
        self.lbl_preflight.setText("\n".join(parts) if parts else "사전검증 통과 — 누락/빈 값 없음.")

    def _pick_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "저장 폴더 선택")
        if path:
            self.ed_out.setText(path)

    # ------------------------------------------------------------------ 생성
    def _on_generate(self) -> None:
        if self.datasource is None:
            QMessageBox.warning(self, "확인", "먼저 데이터를 선택하세요.")
            return
        if self.job.template_path and not Path(self.job.template_path).exists():
            QMessageBox.critical(self, "오류", f"템플릿을 찾을 수 없습니다:\n{self.job.template_path}")
            return
        out_dir = self.ed_out.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "확인", "저장 폴더를 지정하세요.")
            return
        req = self._request()
        if not req.selected_indices:
            QMessageBox.warning(self, "확인", "생성할 레코드를 최소 1건 선택하세요.")
            return
        mapped = req.mapped_records()

        self._running = True
        self.btn_generate.setEnabled(False)
        self.progress.setMaximum(len(mapped))
        self.progress.setValue(0)
        self._say(f"생성 시작: {len(mapped)}건 → {out_dir}")

        self._thread = QThread()
        self._worker = GenerateWorker(
            self.job.template_path, mapped, out_dir, self.job.filename_pattern
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda done, total: self.progress.setValue(done))
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _on_finished(self, batch) -> None:
        self._teardown_thread()
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
