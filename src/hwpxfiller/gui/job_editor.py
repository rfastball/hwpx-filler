"""작업 에디터 — 저장된 "작업"(템플릿·매핑·파일명)을 저작한다.

트랙 C UX 결정([[hwpx-filler-scope]])으로 옛 매핑 위저드가 **작업 에디터로 강등**됐다:
마지막 스텝이 "생성"이 아니라 **"작업 저장"**이다(생성은 별도 실행 화면 :mod:`run_view`).

저작 페이지 1~3(:class:`~hwpxfiller.gui.wizard.TemplatePage`·``DataPage``·``MappingPage``)은
:mod:`hwpxfiller.gui.wizard` 에서 그대로 재사용한다 — 무거운 **명시성 게이트**(전 행 확정)는
여기, 작업 정의 시점에 **1회** 머문다. 4단계는 확정된 매핑을 :class:`~hwpxfiller.core.job.Job`
으로 굳혀 :class:`~hwpxfiller.core.job.JobRegistry` 에 쓴다.

**샘플 데이터는 매핑 저작용일 뿐 작업에 저장하지 않는다** — 데이터·행은 실행 때 고른다.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from ..core.job import Job, JobRegistry
from .style import BASE_QSS
from .wizard import DataPage, MappingPage, TemplatePage


class JobEditorWizard(QWizard):
    """작업 저작 위저드 — 템플릿 → 데이터 → 매핑 확정 → **작업 저장**.

    세션 상태를 옛 위저드와 동일한 속성명으로 노출해 저작 페이지들을 그대로 호스팅한다.
    ``registry`` 는 주입받는다(홈이 소유). 저장 성공 시 :attr:`job_saved` 를 방출한다.
    """

    job_saved = Signal(str)  # 저장된 작업 이름

    def __init__(self, registry: JobRegistry, initial_job: "Job | None" = None, parent=None,
                 *, base_registry=None):
        super().__init__(parent)
        # 편집 모드: 기존 작업을 프리로드(템플릿 자동 로드·매핑 프리시드·이름/패턴 프리필).
        # 게이트는 그대로다 — 프리시드는 "과거 사람 확정"의 복원이지 자동 확정이 아니다.
        self.initial_job = initial_job
        if initial_job is not None:
            self.setWindowTitle(f"HWPX Filler — 작업 편집: {initial_job.name}")
        else:
            self.setWindowTitle("HWPX Filler — 작업 편집기")
        self.resize(920, 660)
        self.setWizardStyle(QWizard.ModernStyle)
        self.setStyleSheet(BASE_QSS)
        # 마지막 스텝 = 저장(생성 아님)을 버튼 문안으로 못박는다.
        self.setButtonText(QWizard.FinishButton, "작업 저장")
        self.registry = registry

        # ---- 공유 세션 상태(저작 페이지가 self.wizard() 로 읽음) ----
        self.template_path: str = ""
        self.schema = None                      # TemplateSchema
        self.data_path: str = ""
        self.datasource = None                  # ExcelDataSource
        self.source_fields: "list[str]" = []
        self.records: "list[dict]" = []
        self.model = None                       # MappingModel
        # J3 공유 베이스: 시드용 프로파일(선택) + 계보 이름(저장 Job 에 이월) + 레지스트리(주입).
        self.base_mapping = None                # MappingProfile | None (MappingPage 시드)
        self.base_mapping_name: str = (
            initial_job.base_mapping_name if initial_job is not None else ""
        )
        self.base_registry = base_registry      # MappingBaseRegistry | None (없으면 홈 기본)

        self.addPage(TemplatePage())
        self.addPage(DataPage())
        self.addPage(MappingPage())
        self._save_page = SaveJobPage()
        self.addPage(self._save_page)

    def accept(self):
        """마침 = 저장(생성 아님). 이름·매핑 확정 검증 후 레지스트리에 쓴다."""
        if self.model is None or not self.model.is_complete():
            QMessageBox.warning(self, "확인", "모든 매핑 행을 확정해야 작업을 저장할 수 있습니다.")
            return
        name = self._save_page.job_name()
        if not name:
            QMessageBox.warning(self, "확인", "작업 이름을 입력하세요.")
            return
        # '전부 비움' 가드(RC-08): blank 선언도 mappings 에 영속화되므로(L1) 판단은
        # 링1 질의(emits_any_value)로 — 뷰는 자료구조 내부 표현을 재구현하지 않는다.
        if not self.model.emits_any_value():
            QMessageBox.warning(
                self, "확인",
                "확정된 매핑이 전부 비움이라 채울 값이 없습니다. 소스를 지정한 뒤 저장하세요.",
            )
            return
        profile = self.model.to_profile(name)
        # 자기 자신 갱신(편집 모드, 이름 그대로)은 자명 — 이름을 바꿔 다른 작업을
        # 덮게 될 때만 확인을 묻는다.
        editing_self = self.initial_job is not None and name == self.initial_job.name
        if not editing_self and self.registry.exists(name) and QMessageBox.question(
            self, "덮어쓰기", f"작업 '{name}' 이(가) 이미 있습니다. 덮어쓸까요?"
        ) != QMessageBox.Yes:
            return
        job = Job(
            name=name,
            template_path=self.template_path,
            mapping=profile,
            filename_pattern=self._save_page.pattern() or "output-{{ID}}",
            # 편집 재저장이 사용 메타를 지우지 않게 이월.
            last_run_at=self.initial_job.last_run_at if self.initial_job else "",
            # J3 계보: 이 작업의 매핑을 시드한 공유 베이스 이름(순수 메타, run-path 무관).
            base_mapping_name=self.base_mapping_name,
        )
        try:
            self.registry.save(job)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "오류", f"작업 저장 실패:\n{exc}")
            return
        self.job_saved.emit(name)
        super().accept()


class SaveJobPage(QWizardPage):
    """4단계 — 작업 이름·파일명 패턴을 정하고 저장한다(생성 아님).

    출력 폴더·행 선택·생성은 여기 없다 — 그것들은 일회성이라 실행 화면의 몫이다.
    실제 저장은 위저드의 :meth:`JobEditorWizard.accept` 가 마침 버튼에서 수행한다.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("4단계 — 작업 저장")
        self.setSubTitle(
            "이 작업(템플릿·매핑·파일명)을 저장합니다. 데이터·행은 저장하지 않습니다 "
            "— 실행할 때 고릅니다."
        )
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        self.ed_name = QLineEdit()
        self.ed_pattern = QLineEdit("공고서-{{ID}}")
        grid.addWidget(QLabel("작업 이름"), 0, 0)
        grid.addWidget(self.ed_name, 0, 1)
        grid.addWidget(QLabel("파일명 패턴"), 1, 0)
        grid.addWidget(self.ed_pattern, 1, 1)
        grid.addWidget(QLabel("토큰: {{필드}}, {{date:YYYYMMDD}}, {{seq:001}}"), 2, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        self.ed_name.textChanged.connect(self.completeChanged)
        self._prefilled = False  # 편집 모드 프리필은 1회 — 사용자 수정을 되돌리지 않는다

    def initializePage(self):
        wiz = self.wizard()
        job = getattr(wiz, "initial_job", None)
        if job is not None and not self._prefilled:
            self.ed_name.setText(job.name)
            self.ed_pattern.setText(job.filename_pattern)
            self._prefilled = True

    def job_name(self) -> str:
        return self.ed_name.text().strip()

    def pattern(self) -> str:
        return self.ed_pattern.text().strip()

    def isComplete(self) -> bool:
        wiz = self.wizard()
        return (
            bool(self.job_name())
            and wiz is not None
            and getattr(wiz, "model", None) is not None
            and wiz.model.is_complete()
        )
