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

from ..core.engine import HwpxEngine
from ..core.job import MISSING_MARKER, Job, RunRequest
from ..data.excel import ExcelDataSource
from .record_select import RecordSelector
from .style import BASE_QSS, mark
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
        # 누적치환: 이전 출력이 **템플릿 자리**에 온다(데이터 소스 아님 — 이음새 무관).
        self._template_override: "str | None" = None
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

    # ------------------------------------------------------------------ helpers
    def _say(self, msg: str) -> None:
        self.log.appendPlainText(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _effective_template(self) -> str:
        """생성이 겨눌 문서 — 누적 모드면 이전 출력, 아니면 작업 템플릿."""
        return self._template_override or self.job.template_path

    def _check_template(self) -> None:
        path = self._effective_template()
        if path and not Path(path).exists():
            self._say(f"[경고] 템플릿을 찾을 수 없습니다: {path}")

    # ------------------------------------------------------- 대상 문서(누적치환)
    def _on_target_mode(self, *_args) -> None:
        cont = self.rb_cont.isChecked()
        self.ed_prev.setEnabled(cont)
        self.btn_prev.setEnabled(cont)
        if not cont:
            self._template_override = None
            self.ed_prev.clear()
            self.lbl_prev_note.setText("")

    def _pick_prev(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "이전 출력 선택", "", "HWPX (*.hwpx)"
        )
        if not path:
            return
        self.ed_prev.setText(path)
        self._template_override = path
        self._sync_prev_note()

    def _sync_prev_note(self) -> None:
        """이전 출력 정합 고지(비차단) — 이 작업의 필드가 그 문서에 실재하는가.

        누름틀은 채운 뒤에도 재발견되므로(engine.required_fields) 교집합으로 판정.
        값 수준 '이미 채워짐' 검사는 필드 값 읽기 API 부재로 파킹 — 겹침 덮어씀을
        정직하게 고지한다(단계별 필드 서로소 규칙).
        """
        prev = self._template_override
        if not prev:
            return
        try:
            doc_fields = set(HwpxEngine().required_fields(prev))
        except Exception as exc:  # noqa: BLE001
            mark(self.lbl_prev_note, "level", "danger")
            self.lbl_prev_note.setText(f"이전 출력을 읽을 수 없습니다: {exc}")
            return
        ours = set(self.job.template_fields())
        inter = doc_fields & ours
        if not inter:
            mark(self.lbl_prev_note, "level", "danger")
            self.lbl_prev_note.setText(
                "이 작업의 필드가 이 문서에 하나도 없습니다 — 파일을 확인하세요."
            )
        else:
            mark(self.lbl_prev_note, "level", "warn" if len(inter) < len(ours) else "")
            self.lbl_prev_note.setText(
                f"이 작업의 필드 {len(ours)}개 중 {len(inter)}개가 문서에 있습니다. "
                "이미 값이 있는 겹침 필드는 덮어씁니다 — 단계별 필드는 서로소로 설계하세요."
            )

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
        if src.missing_columns:
            mark(self.lbl_preflight, "level", "danger")
        elif out.empty_valued:
            mark(self.lbl_preflight, "level", "warn")
        else:
            mark(self.lbl_preflight, "level", "ok")
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
        if self.rb_cont.isChecked() and not self._template_override:
            QMessageBox.warning(self, "확인", "이어채울 이전 출력(.hwpx)을 선택하세요.")
            return
        template = self._effective_template()
        if template and not Path(template).exists():
            QMessageBox.critical(self, "오류", f"템플릿을 찾을 수 없습니다:\n{template}")
            return
        out_dir = self.ed_out.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "확인", "저장 폴더를 지정하세요.")
            return
        req = self._request()
        if not req.selected_indices:
            QMessageBox.warning(self, "확인", "생성할 레코드를 최소 1건 선택하세요.")
            return
        if self._template_override and len(req.selected_indices) != 1:
            # 누적 v1 = 단건(자명). 배치 누적은 "이전 출력↔레코드 파일키 매칭"이
            # 필요한 별개 설계 — 실데이터 확보 전 파킹(ROADMAP).
            QMessageBox.warning(
                self, "확인",
                "이전 출력 이어채우기는 레코드 1건만 지원합니다 — 문서 1개에 여러 "
                "레코드를 겹쳐 쓸 수 없습니다. 레코드를 1건만 선택하세요.",
            )
            return

        # ---- 능동 빈칸 게이트: 수동 로그가 아니라 물어보고 표식을 넣는다. ----
        # "표식 없이 생성" 은 없다 — 미충족 공란을 조용히 내면 "누락은 시끄럽게" 위반
        # (의도적 공란은 매핑이 키를 제외해 이미 조용한 경로가 있다).
        issues = list(dict.fromkeys(
            list(req.source_report().missing_columns) + list(req.output_report().empty_valued)
        ))
        self._marked_fields = list(req.output_report().empty_valued)
        if self._marked_fields:
            if QMessageBox.question(
                self, "빈칸 확인",
                f"빈칸 {len(self._marked_fields)}필드 — {', '.join(self._marked_fields)}\n\n"
                f"미입력 표식({MISSING_MARKER.format(field='필드')})을 넣고 생성할까요?\n"
                "표식은 누름틀로 남아 한글에서 클릭해 채우거나, 다음 단계 "
                "이어채우기에서 덮입니다.",
            ) != QMessageBox.Yes:
                return
            mapped = req.mapped_records(mark_missing=MISSING_MARKER)
        else:
            mapped = req.mapped_records()
        if issues:
            self._say("사전검증 이슈: " + ", ".join(issues))

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
