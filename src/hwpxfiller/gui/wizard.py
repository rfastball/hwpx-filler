"""작업 에디터 저작 페이지 — 템플릿 → 데이터 → 필드 매핑(사람 확정).

이 세 페이지(:class:`TemplatePage`·:class:`DataPage`·:class:`MappingPage`)는 작업 에디터
(:mod:`hwpxfiller.gui.job_editor`)가 조립해 쓰는 재사용 저작 스텝이다. 핵심은 매핑 단계의
**명시성 게이트**: 자동 제안은 초안일 뿐이고, 사람이 모든 행을 확정하기 전에는 다음으로
넘어갈 수 없다(``MappingModel.is_complete``).

세션 상태(template_path, schema, data_path, source_fields, records, model)는 호스트 위저드
객체가 들고, 각 페이지는 ``self.wizard()`` 로 접근한다(덕타이핑 — 같은 속성명을 노출하는
어떤 QWizard 든 이 페이지들을 그대로 호스팅할 수 있다).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWizardPage,
)

from ..core.mapping import MappingProfile
from ..core.schema import extract_schema
from ..data import source_for_path
from .mapping_state import MappingModel
from .mapping_table import MappingTable
from .style import mark

# 요약 라벨에 나열할 필드 이름 최대 개수(넘치면 말줄임).
_SUMMARY_MAX_FIELDS = 12


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
        mark(self.lbl_warn, "level", "warn")
        layout.addWidget(self.lbl_warn)
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
        path, _ = QFileDialog.getOpenFileName(self, "HWPX 템플릿 선택", "", "HWPX (*.hwpx)")
        if path:
            self._load_template(path)

    def _load_template(self, path: str) -> bool:
        """스키마 추출·요약 표시. 실패/필드 0개면 미완료 유지."""
        wiz = self.wizard()
        self._valid = False
        self.lbl_warn.setText("")
        try:
            schema = extract_schema(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"템플릿 스키마 추출 실패:\n{exc}")
            self.lbl_summary.setText("")
            self.completeChanged.emit()
            return False

        self.ed_path.setText(path)
        if not schema.fields:
            self.lbl_summary.setText(
                "이 템플릿에는 누름틀 필드가 없습니다 — 채울 대상이 없어 진행할 수 없습니다.\n"
                "한글에서 누름틀을 삽입하거나 저작 보조(compile)로 토큰을 변환한 템플릿을 쓰세요."
            )
            self.completeChanged.emit()
            return False

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
        return True

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

    def initializePage(self):
        # 편집 모드 고지: Job 은 데이터를 저장하지 않는다(핸드오프 §3) — 매핑 검토용
        # 샘플 데이터를 다시 고른다는 사실을 정직하게 노출.
        if getattr(self.wizard(), "initial_job", None) is not None:
            self.setSubTitle(
                "작업에 데이터는 저장되지 않습니다 — 매핑 검토용 샘플 데이터를 "
                "다시 선택하세요. 실제 데이터·행은 집행할 때 고릅니다."
            )

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "데이터 파일 선택", "", "엑셀/CSV (*.xlsx *.xlsm *.csv)"
        )
        if not path:
            return
        wiz = self.wizard()
        self._valid = False
        try:
            source = source_for_path(path)
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
        self._preview_index = 0

        layout = QVBoxLayout(self)
        self.table = MappingTable()
        self.table.completeChanged.connect(self._on_table_changed)
        layout.addWidget(self.table, 1)

        # 레코드 스텝퍼 — 어떤 레코드로 미리보기할지 훑는다.
        stepper = QHBoxLayout()
        self.btn_prev = QPushButton("◀ 이전")
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.btn_next = QPushButton("다음 ▶")
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
        btn_load = QPushButton("프로파일 불러오기…")
        btn_load.clicked.connect(self._load_profile)
        btn_save = QPushButton("프로파일 저장…")
        btn_save.clicked.connect(self._save_profile)
        buttons.addWidget(self.lbl_progress)
        buttons.addStretch(1)
        buttons.addWidget(btn_load)
        buttons.addWidget(btn_save)
        layout.addLayout(buttons)

    def initializePage(self):
        wiz = self.wizard()
        key = (wiz.template_path, wiz.data_path)
        if self._built_for != key or wiz.model is None:
            # 템플릿/데이터 조합이 바뀌었을 때만 초안을 새로 뽑는다
            # (뒤로 갔다 와도 사람이 만진 확정 상태를 잃지 않게).
            wiz.model = MappingModel.from_suggestions(wiz.schema, wiz.source_fields)
            self._built_for = key
            # 편집 모드: 저장된 매핑을 프리시드 — 일치 행은 과거 사람 확정의 복원이라
            # 확정 상태로 온다(apply_profile). 프로파일에 없는 행은 미확정 유지:
            # 의도적 공란과 새 필드를 구별할 수 없어 자동 확정은 게이트를 몰래 약화시킨다.
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
        """확정 진행 카운터 — 게이트(전 행 확정)까지 얼마나 남았는지 상시 노출."""
        model = self.wizard().model if self.wizard() else None
        if model is None or not model.rows:
            self.lbl_progress.setText("확정 0/0")
            return
        done = sum(1 for r in model.rows if r.confirmed)
        complete = done == len(model.rows)
        self.lbl_progress.setText(f"확정 {done}/{len(model.rows)}")
        mark(self.lbl_progress, "muted", not complete)
        mark(self.lbl_progress, "level", "ok" if complete else "")

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
            self.lbl_index.setText("레코드 0/0")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            self.lbl_preview_summary.setText("")
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
        filled = sum(1 for r in wiz.model.rows if r.has_content()) - len(empties)
        text = f"채움 {filled} · 빈값 {len(empties)}"
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
