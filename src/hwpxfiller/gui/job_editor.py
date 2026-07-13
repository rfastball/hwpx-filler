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

from ..core.job import DEFAULT_FILENAME_PATTERN, Job, JobRegistry
from .confirm import confirm_destructive
from .job_editor_state import (
    needs_overwrite_confirm,
    overwrite_confirm_text,
    validate_save,
)
from .style import BASE_QSS, mark
from .view_helpers import restore_geometry, save_geometry, show_error
from .wizard import DataPage, MappingPage, TemplatePage


class JobEditorWizard(QWizard):
    """작업 저작 위저드 — 템플릿 → 데이터 → 매핑 확정 → **작업 저장**.

    세션 상태를 옛 위저드와 동일한 속성명으로 노출해 저작 페이지들을 그대로 호스팅한다.
    ``registry`` 는 주입받는다(홈이 소유). 저장 성공 시 :attr:`job_saved` 를 방출한다.

    ``secret_store``/``nara_fetcher`` 는 나라장터 취득 대화상자(DataPage)로 관통하는
    **선언된 주입 계약**이다 — 평시 ``None`` 이면 대화상자가 OS 자격증명 저장소·실
    네트워크 기본값을 쓴다. 생성자 파라미터로 못박아 주입 오타가 조용한 실 저장소·실
    네트워크 폴백이 아니라 ``TypeError`` 로 시끄럽게 실패한다(RC-25).
    """

    job_saved = Signal(str)  # 저장된 작업 이름

    def __init__(self, registry: JobRegistry, initial_job: "Job | None" = None, parent=None,
                 *, base_registry=None, secret_store=None, nara_fetcher=None):
        super().__init__(parent)
        # 편집 모드: 기존 작업을 프리로드(템플릿 자동 로드·매핑 프리시드·이름/패턴 프리필).
        # 게이트는 그대로다 — 프리시드는 "과거 사람 확정"의 복원이지 자동 확정이 아니다.
        self.initial_job = initial_job
        if initial_job is not None:
            self.setWindowTitle(f"HWPX Filler — 작업 편집: {initial_job.name}")
        else:
            self.setWindowTitle("HWPX Filler — 작업 편집기")
        restore_geometry(self, "editor", default_size=(920, 660))  # ST-11
        self.setWizardStyle(QWizard.ModernStyle)
        self.setStyleSheet(BASE_QSS)
        # 마지막 스텝 = 저장(생성 아님)을 버튼 문안으로 못박는다.
        self.setButtonText(QWizard.FinishButton, "작업 저장")
        # 위저드 전진 버튼에 primary 마킹(UD-22): QWizard 자체 생성 내비 버튼(Next/Finish/
        # Commit)에 마킹 관례가 미적용돼 저작 표면 4스텝 전부 primary 0개 — Next/'작업 저장'이
        # Cancel·Back 과 동일 룩이라 주 행동 탐색 비용·Cancel 오클릭 위험이 컸다. 화면당
        # primary 1개(전진 버튼) 규율을 위저드에도 적용한다. 스텝별로 하나만 노출된다
        # (Next 또는 Finish/Commit) — 뷰포트 primary 는 항상 1개.
        for _wb in (
            QWizard.WizardButton.NextButton,
            QWizard.WizardButton.FinishButton,
            QWizard.WizardButton.CommitButton,
        ):
            _btn = self.button(_wb)
            if _btn is not None:
                mark(_btn, "primary", True)
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
        # 나라장터 주입 이음새(선언 계약, RC-25) — None = 대화상자 기본(OS 자격증명·실 네트워크).
        self.secret_store = secret_store        # SecretStore | None
        self.nara_fetcher = nara_fetcher        # (url)->bytes | None

        self.addPage(TemplatePage())
        self.addPage(DataPage())
        self.addPage(MappingPage())
        self._save_page = SaveJobPage()
        self.addPage(self._save_page)

    def accept(self):
        """마침 = 저장(생성 아님). 게이트 판정은 링1(:mod:`job_editor_state`), 여기선 표시만."""
        name = self._save_page.job_name()
        pattern = self._save_page.pattern()
        verdict = validate_save(self.model, name, pattern)
        if not verdict.ok:
            QMessageBox.warning(self, "확인", verdict.block_reason)
            return
        profile = verdict.profile
        assert profile is not None  # verdict.ok 이면 링1이 확정 프로파일을 담아 반환
        # 자기 자신 갱신(편집 모드, 이름 그대로)은 자명 — 이름을 바꿔 다른 작업을
        # 덮게 될 때만 확인을 묻는다(판정·문구 성형은 링1, 다이얼로그만 여기서).
        if needs_overwrite_confirm(
            name,
            self.initial_job.name if self.initial_job is not None else None,
            self.registry.exists(name),
        ):
            # 실제 파괴 대상을 문구에 못박는다(RC-15 P6): 레지스트리는 slug 로 저장하므로
            # 입력 이름('예산/2026')과 파괴되는 기존 작업 이름('예산_2026')이 다를 수 있다.
            try:
                victim = self.registry.load(name).name or name
            except Exception:  # noqa: BLE001 — 손상 파일: 이름 불명을 조용히 추측하지 않는다
                victim = ""
            if not confirm_destructive(
                self, "작업 덮어쓰기", overwrite_confirm_text(name, victim), "덮어쓰기"
            ):
                return
        job = Job(
            name=name,
            template_path=self.template_path,
            mapping=profile,
            filename_pattern=pattern,
            # 편집 재저장이 사용 메타를 지우지 않게 이월.
            last_run_at=self.initial_job.last_run_at if self.initial_job else "",
            # J3 계보: 이 작업의 매핑을 시드한 공유 베이스 이름(순수 메타, run-path 무관).
            base_mapping_name=self.base_mapping_name,
        )
        try:
            self.registry.save(job)
        except Exception as exc:  # noqa: BLE001
            show_error(self, "작업 저장 실패", exc)  # 유형별 문구 + 원문 접기(ST-20)
            return
        self.job_saved.emit(name)
        save_geometry(self, "editor")  # ST-11
        super().accept()

    def _confirm_discard(self) -> bool:
        """진행 중 저작(확정 행)이 있으면 폐기 확인 — 없으면 즉시 True(ST-08).

        model 미도달(매핑 페이지 전) 또는 확정 0행이면 잃을 게 없어 통과. 확정 행이
        있으면 반사적 X/Esc/취소가 다스텝 저작을 침묵 폐기하지 못하게 확인을 강제한다
        (pipeline_builder 이탈 게이트와 대칭, confirm-or-alarm).
        """
        model = self.model
        if model is None or model.confirmed_count() <= 0:
            return True
        return confirm_destructive(
            self, "편집 취소",
            "확정한 매핑이 있습니다 — 저장하지 않고 닫으면 이 편집 내용이 사라집니다.",
            "저장 안 함",
        )

    def reject(self):
        # Cancel/Esc(및 X → closeEvent 위임) 공통 이탈 경로 — 단일 가드(ST-08).
        if not self._confirm_discard():
            return
        save_geometry(self, "editor")  # ST-11
        super().reject()

    def closeEvent(self, event):  # noqa: N802 — X 버튼을 reject 경로로 위임(이중 프롬프트 방지)
        event.ignore()
        self.reject()


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
        self.ed_pattern = QLineEdit(DEFAULT_FILENAME_PATTERN)
        # 라벨-입력을 프로그램적으로 연결(ST-07, WCAG 1.3.1/4.1.2/3.3.2): setBuddy 가
        # 접근성 LabeledBy 관계를 만들어 스크린리더가 각 칸의 이름을 읽는다(인접 배치만으론
        # 연결 안 됨). accessibleName 도 병기해 리더 구현 차이를 흡수한다.
        lbl_name = QLabel("작업 이름")
        lbl_name.setBuddy(self.ed_name)
        self.ed_name.setAccessibleName("작업 이름")
        lbl_pattern = QLabel("파일명 패턴")
        lbl_pattern.setBuddy(self.ed_pattern)
        self.ed_pattern.setAccessibleName("파일명 패턴")
        grid.addWidget(lbl_name, 0, 0)
        grid.addWidget(self.ed_name, 0, 1)
        grid.addWidget(lbl_pattern, 1, 0)
        grid.addWidget(self.ed_pattern, 1, 1)
        grid.addWidget(QLabel("토큰: {{필드}}, {{date:YYYYMMDD}}, {{seq:001}}"), 2, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        self.ed_name.textChanged.connect(self.completeChanged)
        self.ed_pattern.textChanged.connect(self.completeChanged)
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
            and bool(self.pattern())  # 빈 패턴은 저장 게이트에서 차단(RC-20)
            and wiz is not None
            and getattr(wiz, "model", None) is not None
            and wiz.model.is_complete()
        )
