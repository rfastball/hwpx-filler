"""매핑 위저드 — 템플릿 → 데이터 → 필드 매핑(사람 확정) → 생성, 4스텝 QWizard.

핵심은 3단계의 **명시성 게이트**: 자동 제안은 초안일 뿐이고, 사람이 모든 행을
확정하기 전에는 생성 스텝으로 넘어갈 수 없다(MappingModel.is_complete).

세션 상태(template_path, schema, data_path, source_fields, records, model)는
위저드 객체가 들고, 각 페이지는 ``self.wizard()`` 로 접근한다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from ..core.mapping import MappingProfile
from ..core.schema import extract_schema
from ..data.excel import ExcelDataSource
from .mapping_state import MappingModel
from .mapping_table import MappingTable
from .worker import GenerateWorker

# 요약 라벨에 나열할 필드 이름 최대 개수(넘치면 말줄임).
_SUMMARY_MAX_FIELDS = 12


class MappingWizard(QWizard):
    """4스텝 매핑 위저드 — GUI 진입점(app.main)이 기동한다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HWPX Filler — 매핑 위저드")
        self.resize(920, 660)
        self.setWizardStyle(QWizard.ModernStyle)

        # ---- 공유 세션 상태 ----
        self.template_path: str = ""
        self.schema = None                      # TemplateSchema
        self.data_path: str = ""
        self.datasource = None                  # ExcelDataSource
        self.source_fields: "list[str]" = []
        self.records: "list[dict]" = []
        self.model: "MappingModel | None" = None

        self.addPage(TemplatePage())
        self.addPage(DataPage())
        self.addPage(MappingPage())
        self.addPage(GeneratePage())


class TemplatePage(QWizardPage):
    """1단계 — HWPX 템플릿 선택 + 스키마 추출(필드·타입 요약, stray 경고)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("1단계 — 템플릿 선택")
        self.setSubTitle("누름틀이 들어 있는 HWPX 템플릿을 선택하세요.")
        self._valid = False

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.ed_path = QLineEdit()
        self.ed_path.setReadOnly(True)
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
        self.lbl_warn.setStyleSheet("color: #A05A00;")
        layout.addWidget(self.lbl_warn)
        layout.addStretch(1)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "HWPX 템플릿 선택", "", "HWPX (*.hwpx)")
        if not path:
            return
        wiz: MappingWizard = self.wizard()
        self._valid = False
        self.lbl_warn.setText("")
        try:
            schema = extract_schema(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"템플릿 스키마 추출 실패:\n{exc}")
            self.lbl_summary.setText("")
            self.completeChanged.emit()
            return

        self.ed_path.setText(path)
        if not schema.fields:
            self.lbl_summary.setText(
                "이 템플릿에는 누름틀 필드가 없습니다 — 채울 대상이 없어 진행할 수 없습니다.\n"
                "한글에서 누름틀을 삽입하거나 저작 보조(compile)로 토큰을 변환한 템플릿을 쓰세요."
            )
            self.completeChanged.emit()
            return

        wiz.template_path = path
        wiz.schema = schema
        names = [f"{f.name}({f.inferred_type})" for f in schema.fields]
        shown = ", ".join(names[:_SUMMARY_MAX_FIELDS])
        if len(names) > _SUMMARY_MAX_FIELDS:
            shown += f" 외 {len(names) - _SUMMARY_MAX_FIELDS}개"
        self.lbl_summary.setText(f"필드 {len(names)}개: {shown}")
        if schema.stray_tokens:
            self.lbl_warn.setText(
                "경고(비차단): 본문에 누름틀이 아닌 {{...}} 토큰이 남아 있습니다 — "
                + ", ".join(schema.stray_tokens)
                + "\n이 토큰은 값이 주입되지 않습니다. 필요하면 저작 보조로 누름틀로 변환하세요."
            )
        self._valid = True
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._valid


class DataPage(QWizardPage):
    """2단계 — 데이터 파일 선택(xlsx/csv). 컬럼·레코드 수 요약."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("2단계 — 데이터 선택")
        self.setSubTitle("레코드(행)마다 문서 1건을 생성할 데이터 파일을 선택하세요.")
        self._valid = False

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.ed_path = QLineEdit()
        self.ed_path.setReadOnly(True)
        btn = QPushButton("찾아보기…")
        btn.clicked.connect(self._pick)
        row.addWidget(QLabel("데이터(.xlsx/.csv)"))
        row.addWidget(self.ed_path, 1)
        row.addWidget(btn)
        layout.addLayout(row)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)
        layout.addStretch(1)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "데이터 파일 선택", "", "엑셀/CSV (*.xlsx *.xlsm *.csv)"
        )
        if not path:
            return
        wiz: MappingWizard = self.wizard()
        self._valid = False
        try:
            source = ExcelDataSource(path)
            fields = source.fields()
            records = source.records()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"데이터 로드 실패:\n{exc}")
            self.lbl_summary.setText("")
            self.completeChanged.emit()
            return

        self.ed_path.setText(path)
        if not fields or not records:
            self.lbl_summary.setText(
                f"컬럼 {len(fields)}개, 레코드 {len(records)}건 — 빈 데이터로는 진행할 수 없습니다.\n"
                "1행이 헤더(필드명), 2행부터가 레코드인 파일을 선택하세요."
            )
            self.completeChanged.emit()
            return

        wiz.data_path = path
        wiz.datasource = source
        wiz.source_fields = fields
        wiz.records = records
        self.lbl_summary.setText(f"컬럼 {len(fields)}개, 레코드 {len(records)}건 로드.")
        self._valid = True
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._valid


class MappingPage(QWizardPage):
    """3단계 — 필드 매핑 확정. 전 행 확정 전에는 다음으로 못 간다(명시성 게이트)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("3단계 — 필드 매핑 확정")
        self.setSubTitle(
            "자동 제안은 초안일 뿐입니다. 모든 행을 검토해 확정해야 다음으로 진행합니다. "
            "채우지 않을 필드는 소스를 (비움)으로 두고 확정하세요."
        )
        self._built_for: "tuple[str, str] | None" = None

        layout = QVBoxLayout(self)
        self.table = MappingTable()
        self.table.completeChanged.connect(self.completeChanged.emit)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        btn_load = QPushButton("프로파일 불러오기…")
        btn_load.clicked.connect(self._load_profile)
        btn_save = QPushButton("프로파일 저장…")
        btn_save.clicked.connect(self._save_profile)
        buttons.addWidget(btn_load)
        buttons.addWidget(btn_save)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def initializePage(self):
        wiz: MappingWizard = self.wizard()
        key = (wiz.template_path, wiz.data_path)
        if self._built_for != key or wiz.model is None:
            # 템플릿/데이터 조합이 바뀌었을 때만 초안을 새로 뽑는다
            # (뒤로 갔다 와도 사람이 만진 확정 상태를 잃지 않게).
            wiz.model = MappingModel.from_suggestions(wiz.schema, wiz.source_fields)
            self._built_for = key
        preview = wiz.records[0] if wiz.records else {}
        self.table.set_model(wiz.model, preview)
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        wiz: MappingWizard = self.wizard()
        return wiz is not None and wiz.model is not None and wiz.model.is_complete()

    # ----------------------------------------------------------- 프로파일 IO
    def _load_profile(self):
        wiz: MappingWizard = self.wizard()
        if wiz.model is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "매핑 프로파일 불러오기", "", "매핑 프로파일 (*.json)"
        )
        if not path:
            return
        try:
            profile = MappingProfile.load(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"프로파일 로드 실패:\n{exc}")
            return
        applied = wiz.model.apply_profile(profile)
        self.table.refresh()
        self.completeChanged.emit()
        QMessageBox.information(
            self, "프로파일 적용",
            f"{applied}개 필드에 프로파일을 적용했습니다(적용 행은 확정 상태).\n"
            "프로파일에 없는 필드는 직접 확정하세요.",
        )

    def _save_profile(self):
        wiz: MappingWizard = self.wizard()
        if wiz.model is None:
            return
        profile = wiz.model.to_profile()
        if not profile.mappings:
            QMessageBox.warning(
                self, "확인", "저장할 확정 매핑이 없습니다. 행을 확정한 뒤 저장하세요."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "매핑 프로파일 저장", "mapping_profile.json", "매핑 프로파일 (*.json)"
        )
        if not path:
            return
        profile.name = Path(path).stem
        try:
            profile.save(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"프로파일 저장 실패:\n{exc}")
            return
        QMessageBox.information(
            self, "저장 완료", f"확정 매핑 {len(profile.mappings)}개를 저장했습니다."
        )


class GeneratePage(QWizardPage):
    """4단계 — 저장 폴더·파일명 패턴 지정 후 일괄 생성(백그라운드 워커)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("4단계 — 생성")
        self.setSubTitle("확정된 매핑으로 레코드마다 문서를 생성합니다.")
        self._running = False
        self._thread: "QThread | None" = None

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        self.ed_out = QLineEdit()
        btn_out = QPushButton("찾아보기…")
        btn_out.clicked.connect(self._pick_out)
        self.ed_pattern = QLineEdit("공고서-{{ID}}")
        grid.addWidget(QLabel("저장 폴더"), 0, 0)
        grid.addWidget(self.ed_out, 0, 1)
        grid.addWidget(btn_out, 0, 2)
        grid.addWidget(QLabel("파일명 패턴"), 1, 0)
        grid.addWidget(self.ed_pattern, 1, 1)
        grid.addWidget(QLabel("예: 공고서-{{공고명}} (키는 템플릿 필드명)"), 1, 2)
        layout.addLayout(grid)

        actions = QHBoxLayout()
        self.btn_generate = QPushButton("생성")
        self.btn_generate.clicked.connect(self._on_generate)
        actions.addWidget(self.btn_generate)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)

    def initializePage(self):
        wiz: MappingWizard = self.wizard()
        if not self.ed_out.text() and wiz.template_path:
            self.ed_out.setText(str(Path(wiz.template_path).parent / "Results"))
        mapped = len(wiz.model.to_profile().mappings) if wiz.model else 0
        self._say(f"준비 완료: 레코드 {len(wiz.records)}건 × 확정 매핑 {mapped}개 필드.")

    def isComplete(self) -> bool:
        return not self._running  # 생성 중에는 마침 버튼 잠금

    def _pick_out(self):
        path = QFileDialog.getExistingDirectory(self, "저장 폴더 선택")
        if path:
            self.ed_out.setText(path)

    def _say(self, msg: str):
        self.log.appendPlainText(msg)

    # --------------------------------------------------------------- 생성
    def _on_generate(self):
        wiz: MappingWizard = self.wizard()
        if wiz.model is None or not wiz.model.is_complete():
            QMessageBox.warning(self, "확인", "3단계에서 모든 행을 확정해야 생성할 수 있습니다.")
            return
        out_dir = self.ed_out.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "확인", "저장 폴더를 지정하세요.")
            return
        profile = wiz.model.to_profile()
        if not profile.mappings:
            QMessageBox.warning(
                self, "확인",
                "확정된 매핑이 전부 비움이라 생성할 값이 없습니다. 3단계에서 소스를 지정하세요.",
            )
            return
        pattern = self.ed_pattern.text().strip() or "output-{{ID}}"
        mapped_records = profile.apply_all(wiz.records)

        self._running = True
        self.btn_generate.setEnabled(False)
        self.completeChanged.emit()
        self.progress.setMaximum(len(mapped_records))
        self.progress.setValue(0)
        self._say(f"생성 시작: {len(mapped_records)}건 → {out_dir}")

        self._thread = QThread()
        self._worker = GenerateWorker(wiz.template_path, mapped_records, out_dir, pattern)
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
                self._say(
                    f"  [주의] 매칭 안 된 필드: {', '.join(res.unmatched)} → "
                    f"{Path(res.output_path).name}"
                )
        out_dir = self.ed_out.text().strip()
        if batch.succeeded > 0 and QMessageBox.question(
            self, "완료", f"{batch.succeeded}건 생성 완료.\n결과 폴더를 여시겠습니까?"
        ) == QMessageBox.Yes:
            self._open_folder(out_dir)

    def _on_failed(self, msg: str):
        self._teardown_thread()
        QMessageBox.critical(self, "오류", f"생성 중 오류:\n{msg}")

    def _teardown_thread(self):
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
        self._running = False
        self.btn_generate.setEnabled(True)
        self.completeChanged.emit()

    @staticmethod
    def _open_folder(path: str):
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
