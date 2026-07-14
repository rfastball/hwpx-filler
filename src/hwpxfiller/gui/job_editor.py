"""작업 에디터 — 저장된 "작업"(템플릿·매핑·파일명)을 저작한다.

트랙 C UX 결정([[hwpx-filler-scope]])으로 옛 매핑 위저드가 **작업 에디터로 강등**됐다:
마지막 스텝이 "생성"이 아니라 **"작업 저장"**이다(생성은 별도 실행 화면 :mod:`run_view`).

저작 페이지 1~3(:class:`~hwpxfiller.gui.wizard.TemplatePage`·``DataPage``·``MappingPage``)은
:mod:`hwpxfiller.gui.wizard` 에서 그대로 재사용한다 — 무거운 **명시성 게이트**(전 행 확정)는
여기, 작업 정의 시점에 **1회** 머문다. 4단계는 확정된 매핑을 :class:`~hwpxfiller.core.job.Job`
으로 굳혀 :class:`~hwpxfiller.core.job.JobRegistry` 에 쓴다.

**샘플 데이터의 행은 작업에 저장하지 않는다.** 다만 사용자가 선택한 소스 참조(파일 경로·
나라장터 쿼리)는 작업 저장 시 등록 데이터로 함께 등록해 실행 때 다시 찾는 마찰을 줄인다(#18).
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from ..core.job import DEFAULT_FILENAME_PATTERN, Job, JobRegistry
from .confirm import confirm_destructive
from .home_state import discover_tag_axes
from .job_editor_state import (
    needs_overwrite_confirm,
    overwrite_confirm_text,
    validate_save,
)
from .style import BASE_QSS, mark
from .view_helpers import restore_geometry, save_geometry, show_error
from .wizard import DataPage, MappingPage, TemplatePage


class _TagRow(QWidget):
    """분류 태그 한 줄 — 축(편집형 콤보, 발견된 축 후보) + 값 + 삭제(JOB_BROWSER_DESIGN D2).

    차원-불가지: 코드는 축·값이 무엇인지 모른다 — 사용자가 자유롭게 입력한다. enum/bool
    타입 필드를 발명하지 않는다.
    """

    def __init__(self, known_axes, axis="", value="", on_remove=None, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.cb_axis = QComboBox()
        self.cb_axis.setEditable(True)
        self.cb_axis.addItems(known_axes)
        self.cb_axis.setCurrentText(axis)
        self.cb_axis.lineEdit().setPlaceholderText("분류 기준 (예: 금액 구간)")
        self.cb_axis.setAccessibleName("태그 분류 기준")
        self.ed_value = QLineEdit(value)
        self.ed_value.setPlaceholderText("태그 값 (예: 1억 미만)")
        self.ed_value.setAccessibleName("태그 값")
        btn_del = QPushButton("삭제")
        mark(btn_del, "level", "danger")  # 파괴 버튼 시각 등급(UD-12)
        if on_remove is not None:
            btn_del.clicked.connect(lambda: on_remove(self))
        root.addWidget(self.cb_axis, 1)
        root.addWidget(self.ed_value, 1)
        root.addWidget(btn_del)

    def set_known_axes(self, axes) -> None:
        """축 후보 목록을 갱신하되 현재 입력값은 보존한다(재진입 시 발견 축 반영)."""
        cur = self.cb_axis.currentText()
        self.cb_axis.clear()
        self.cb_axis.addItems(axes)
        self.cb_axis.setCurrentText(cur)

    def axis(self) -> str:
        return self.cb_axis.currentText().strip()

    def value(self) -> str:
        return self.ed_value.text().strip()


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
                 *, base_registry=None, pool_registry=None,
                 secret_store=None, nara_fetcher=None):
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
        self.data_sheet: "str | None" = None    # 확정 시트명(T2, None=기본 시트)
        self.datasource = None                  # ExcelDataSource
        self.source_fields: "list[str]" = []
        self.records: "list[dict]" = []
        # 선택 샘플의 durable **참조**만 자동 등록한다(#18/31A5A484-C). 행 스냅샷·비밀은 없음.
        self.declared_data_kind: str = ""
        self.declared_data_opts: "dict[str, object]" = {}
        self.model = None                       # MappingModel
        # J3 공유 베이스: 시드용 프로파일(선택) + 계보 이름(저장 Job 에 이월) + 레지스트리(주입).
        self.base_mapping = None                # MappingProfile | None (MappingPage 시드)
        self.base_mapping_name: str = (
            initial_job.base_mapping_name if initial_job is not None else ""
        )
        self.base_registry = base_registry      # MappingBaseRegistry | None (없으면 홈 기본)
        if pool_registry is None:
            from ..core.dataset_pool import (
                DatasetPoolRegistry,
                default_dataset_pool_dir,
            )

            pool_registry = DatasetPoolRegistry(default_dataset_pool_dir())
        self.pool_registry = pool_registry
        # 나라장터 주입 이음새(선언 계약, RC-25) — None = 대화상자 기본(OS 자격증명·실 네트워크).
        self.secret_store = secret_store        # SecretStore | None
        self.nara_fetcher = nara_fetcher        # (url)->bytes | None

        self.addPage(TemplatePage())
        self.addPage(DataPage())
        self.addPage(MappingPage())
        self._save_page = SaveJobPage()
        self.addPage(self._save_page)

    @staticmethod
    def _declared_dataset_name(job_name: str) -> str:
        """작업이 선언한 자동 등록 데이터의 결정적 이름 — 실행 선택 목록에서 식별 가능."""
        return f"{job_name} · 등록 데이터"

    def _declared_pool_item(self, job_name: str):
        """현재 선택 소스를 데이터 풀 참조로 성형한다. 선택 없음은 ``None``.

        링0 Job에는 데이터·행을 넣지 않는다. 엑셀/CSV는 경로(+확정 시트), 나라장터는
        수용된 쿼리만 저장하며 ServiceKey와 취득 행은 들어오지 않는다.
        """
        if not self.declared_data_kind:
            return None
        if self.declared_data_kind not in {"excel", "nara"}:
            raise ValueError(
                f"자동 등록할 수 없는 데이터 종류입니다: {self.declared_data_kind!r}"
            )
        from ..core.dataset_pool import DatasetPoolItem

        return DatasetPoolItem(
            name=self._declared_dataset_name(job_name),
            kind=self.declared_data_kind,
            opts=dict(self.declared_data_opts),
            created_at=datetime.now().isoformat(timespec="seconds"),
            note=f"작업 '{job_name}' 저장 시 자동 등록",
        )

    def accept(self):
        """마침 = 저장(생성 아님). 게이트 판정은 링1(:mod:`job_editor_state`), 여기선 표시만."""
        name = self._save_page.job_name()
        pattern = self._save_page.pattern()
        verdict = validate_save(self.model, name, pattern)
        if not verdict.ok:
            QMessageBox.warning(self, "확인", verdict.block_reason)
            return
        # 분류 태그 저장 게이트 — 반쯤 채운 행·중복 축은 tags() 가 조용히 버리거나
        # 덮으므로(입력 소실), 저장 전 시끄럽게 막는다(확인-또는-경보). 덮어쓰기
        # 확인보다 먼저 판정해, 어차피 막힐 저장에 파괴 프롬프트를 띄우지 않는다.
        tag_reason = self._save_page.validate_tags()
        if tag_reason:
            QMessageBox.warning(self, "확인", tag_reason)
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
            # 브라우징 분류 태그(선택 — D12). 수동 입력, 이름 파싱·자동 제안 없음(제안은 보류).
            tags=self._save_page.tags(),
        )
        # 선언 데이터 자동 등록(#18). 같은 결정적 이름에 다른 참조가 있으면 조용히
        # 덮지 않고 실제 항목명을 재진술해 확인한다. 풀을 먼저 쓴 뒤 Job 저장이 실패하면
        # 기존 항목 복원/신규 항목 삭제로 되돌려 반쪽 저장을 남기지 않는다.
        try:
            pool_item = self._declared_pool_item(name)
            previous_pool_item = (
                self.pool_registry.load(pool_item.name)
                if pool_item is not None and self.pool_registry.exists(pool_item.name)
                else None
            )
        except Exception as exc:  # noqa: BLE001 — 손상 풀/알 수 없는 종류는 loud 차단
            show_error(self, "등록 데이터 확인 실패", exc)
            return
        if previous_pool_item is not None:
            changed = (
                previous_pool_item.name != pool_item.name
                or previous_pool_item.kind != pool_item.kind
                or previous_pool_item.opts != pool_item.opts
            )
            if changed and not confirm_destructive(
                self,
                "등록 데이터 교체",
                f"등록 데이터 '{previous_pool_item.name or pool_item.name}' 이(가) 이미 "
                "같은 저장 위치에서 다른 소스를 가리킵니다.\n"
                "작업을 저장하면 이 참조를 현재 선택으로 교체합니다.",
                "교체하고 저장",
            ):
                return
            # 최초 등록 시각은 보존하되, 다시 선언한 항목은 실행 후보로 활성화한다.
            pool_item.created_at = previous_pool_item.created_at or pool_item.created_at
        pool_saved = False
        try:
            if pool_item is not None:
                self.pool_registry.save(pool_item)
                pool_saved = True
            self.registry.save(job)
        except Exception as exc:  # noqa: BLE001
            rollback_error = ""
            if pool_saved:
                try:
                    if previous_pool_item is None:
                        self.pool_registry.delete(pool_item.name)
                    else:
                        self.pool_registry.save(previous_pool_item)
                except Exception as rollback_exc:  # noqa: BLE001 — 실패도 숨기지 않는다
                    rollback_error = f"\n등록 데이터 되돌리기도 실패했습니다: {rollback_exc}"
            detail = RuntimeError(f"{exc}{rollback_error}") if rollback_error else exc
            show_error(self, "작업 저장 실패", detail)  # 유형별 문구 + 원문 접기(ST-20)
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
        self.setSubTitle("작업 이름과 생성될 문서의 파일명 규칙을 확인한 뒤 저장하세요.")
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
        layout.addLayout(grid)

        token_box = QGroupBox("파일명에 넣을 수 있는 값")
        token_layout = QVBoxLayout(token_box)
        self.lbl_field_tokens = QLabel("매핑을 완료하면 사용할 수 있는 필드가 표시됩니다.")
        self.lbl_field_tokens.setWordWrap(True)
        self.lbl_field_tokens.setTextInteractionFlags(Qt.TextSelectableByMouse)
        token_layout.addWidget(self.lbl_field_tokens)
        self.lbl_reserved_tokens = QLabel(
            "날짜: {{date}} → 생성 날짜(YYYYMMDD) · {{date:YYYY-MM-DD}} → 하이픈 포함 날짜\n"
            "순번: {{seq}} → 1부터 증가 · {{seq:001}} → 001부터 세 자리로 증가"
        )
        self.lbl_reserved_tokens.setWordWrap(True)
        self.lbl_reserved_tokens.setTextInteractionFlags(Qt.TextSelectableByMouse)
        token_layout.addWidget(self.lbl_reserved_tokens)
        layout.addWidget(token_box)

        # 분류 태그(선택 — D12): 작업 브라우저(홈)의 group-by·facet 기준. 미태깅도 저장 자유.
        self._tag_rows: "list[_TagRow]" = []
        self._known_axes: "list[str]" = []
        tags_box = QGroupBox("분류 태그 (선택)")
        tags_box.setToolTip(
            "작업을 찾기 쉽도록 분류 기준과 태그 값을 추가합니다. 예: '금액 구간'에 "
            "'1억 미만'. 홈 화면에서 같은 기준끼리 모아 보거나 원하는 값만 찾을 수 있습니다. "
            "태그 없이도 저장할 수 있습니다."
        )
        tb = QVBoxLayout(tags_box)
        self.lbl_tag_help = QLabel(
            "작업을 찾기 쉽도록 분류 기준과 태그 값을 추가하세요. "
            "예: 금액 구간 — 1억 미만"
        )
        self.lbl_tag_help.setWordWrap(True)
        tb.addWidget(self.lbl_tag_help)
        self._tags_layout = QVBoxLayout()
        tb.addLayout(self._tags_layout)
        add_row = QHBoxLayout()
        btn_add = QPushButton("＋ 태그 추가")
        btn_add.clicked.connect(lambda: self._add_tag_row())
        add_row.addWidget(btn_add)
        add_row.addStretch(1)
        tb.addLayout(add_row)
        layout.addWidget(tags_box)

        layout.addStretch(1)
        self.ed_name.textChanged.connect(self.completeChanged)
        self.ed_pattern.textChanged.connect(self.completeChanged)
        self._prefilled = False  # 편집 모드 프리필은 1회 — 사용자 수정을 되돌리지 않는다

    def _add_tag_row(self, axis="", value="") -> "_TagRow":
        row = _TagRow(self._known_axes, axis, value, on_remove=self._remove_tag_row)
        self._tag_rows.append(row)
        self._tags_layout.addWidget(row)
        return row

    def _remove_tag_row(self, row: "_TagRow") -> None:
        if row in self._tag_rows:
            self._tag_rows.remove(row)
        self._tags_layout.removeWidget(row)
        row.deleteLater()

    def initializePage(self):
        wiz = self.wizard()
        job = getattr(wiz, "initial_job", None)
        self._refresh_filename_help(wiz)
        # 발견된 축(다른 작업들의 태그 키)을 후보로 — 재진입마다 갱신(값싼 순회).
        reg = getattr(wiz, "registry", None)
        if reg is not None:
            try:
                self._known_axes = list(discover_tag_axes(reg.list_jobs()).keys())
            except (OSError, ValueError):
                # 후보는 편의라 예상 가능한 IO·파싱 실패(디렉터리 접근·손상 JSON)만
                # 조용히 빈 목록으로 강등한다. 시그니처·반환형 회귀(list_jobs/
                # discover_tag_axes 가 던지는 TypeError/AttributeError 등)는 삼키지
                # 않고 전파시켜 교차파일 회귀가 자동완성을 조용히 꺼버리는 대신
                # 시끄럽게 실패하게 둔다(확인-또는-경보).
                self._known_axes = []
        if job is not None and not self._prefilled:
            self.ed_name.setText(job.name)
            self.ed_pattern.setText(job.filename_pattern)
            for axis, value in job.tags.items():  # 기존 태그 프리필(편집 재진입)
                self._add_tag_row(axis, value)
        self._prefilled = True
        for row in self._tag_rows:  # 이미 있는 행의 축 후보 갱신
            row.set_known_axes(self._known_axes)

    def _refresh_filename_help(self, wiz) -> None:
        """확정 매핑의 파일명 필드 토큰과 첫 샘플 대응 값을 표시한다.

        저장 화면에 도착할 때마다 다시 계산해 앞 단계에서 매핑이나 샘플을 바꾼 뒤 돌아와도
        오래된 도움말이 남지 않게 한다. 값은 실행 때와 같은 ``MappingModel.preview`` 변환을
        거치며, 샘플이 없거나 값이 비어 있으면 그 상태를 명시한다(조용한 추측 없음).
        """
        model = getattr(wiz, "model", None)
        if model is None:
            self.lbl_field_tokens.setText("매핑을 완료하면 사용할 수 있는 필드가 표시됩니다.")
            return

        rows = [row for row in model.rows if row.has_content()]
        if not rows:
            self.lbl_field_tokens.setText("파일명에 사용할 수 있는 매핑 필드가 없습니다.")
            return

        records = getattr(wiz, "records", None) or []
        sample = records[0] if records else {}
        preview = model.preview(sample)
        values = []
        for row in rows:
            value = preview.get(row.template_field, "")
            if value:
                display = str(value).replace("\r", " ").replace("\n", " ")
                if len(display) > 40:
                    display = display[:39] + "…"
            else:
                display = "(빈 값)" if records or row.type == "const" else "(샘플 데이터 없음)"
            values.append(f"{{{{{row.template_field}}}}} → {display}")
        self.lbl_field_tokens.setText("필드: " + " · ".join(values))

    def tags(self) -> "dict[str, str]":
        """확정된 태그 {축→값} — 축·값이 모두 채워진 행만(빈 축/빈 값 행은 무시, D12).

        반쯤 채운 행·중복 축은 :meth:`validate_tags` 가 저장 게이트에서 이미 걸러낸
        뒤라, 여기 도달하면 깔끔한 사전만 만들어 돌려준다(추측·자동병합 없음).
        """
        out: "dict[str, str]" = {}
        for row in self._tag_rows:
            axis, value = row.axis(), row.value()
            if axis and value:
                out[axis] = value
        return out

    def validate_tags(self) -> str:
        """태그 행 저장 게이트 — 차단 사유를 돌려준다("" = 통과, 확인-또는-경보).

        Job.tags 는 {축→값} 사전이라 한 축엔 값 하나뿐이다. 두 행이 같은 축을 쓰면
        :meth:`tags` 가 뒤 값으로 앞 값을 조용히 덮어(저장 시 앞 값 소실) 사용자 입력을
        말없이 버리므로, **중복 축**은 사용자 오류로 보고 막는다. 축·값 중 하나만 채운
        **반쯤 채운 행**도 :meth:`tags` 가 조용히 빠뜨려(태깅된 줄 알고 저장) 위험하므로
        막는다. 둘 다 빈 행은 무해한 no-op 이라 조용히 무시한다(D12 — 미태깅 허용).
        자동 병합·추측 없이 어느 축/값이 문제인지 재진술만 한다.
        """
        seen: "set[str]" = set()
        for row in self._tag_rows:
            axis, value = row.axis(), row.value()
            if not axis and not value:
                continue  # 완전 빈 행 = 양성 no-op(D12)
            if not axis or not value:
                filled, blank = (
                    ("태그 값", "분류 기준") if value else ("분류 기준", "태그 값")
                )
                return (
                    f"분류 태그에 {filled}만 있고 {blank}은(는) 빈 행이 있습니다"
                    f"('{axis or value}'). {blank}을(를) 채우거나 그 행을 삭제하세요."
                )
            if axis in seen:
                return (
                    f"분류 기준 '{axis}' 이(가) 여러 행에 중복됩니다 — 같은 분류 기준에는 "
                    "태그 값 하나만 저장됩니다. 중복 행을 하나로 합치거나 삭제하세요."
                )
            seen.add(axis)
        return ""

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
