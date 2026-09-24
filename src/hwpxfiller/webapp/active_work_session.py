"""문서 생성 화면에서 선택한 작업과 데이터 전환 정합을 소유한다."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

from ..application.document_creation_workbench import (
    RELEASE,
    ActiveWorkContext,
    decide_active_work_after_data_transition,
)
from ..application.jobs import (
    JobStorePort,
    job_content_fingerprint,
    job_exists,
    list_jobs,
    load_job,
)
from ..domain.engine import HwpxEngine
from ..domain.job import Job, data_binding_matches, data_binding_of, has_data_binding
from ..viewmodel.run_state import RunViewModel
from ..viewmodel.work_mode import seat_kinds
from ..viewmodel.work_candidates import (
    TAB_AVAILABLE,
    TAB_NEEDS_ACTION,
    preferred_promotion,
    rank_available,
)
from .screens import reference_missing, relink_job_template


@dataclass(frozen=True)
class DataTransitionReconciliation:
    """새 데이터를 커밋하기 전에 고정한 active Work 판정."""

    context: ActiveWorkContext
    release: bool
    warning: str


@dataclass(frozen=True)
class ActiveWorkReload:
    changed: bool = False
    rules_changed: bool = False
    surface_changed: bool = False


@dataclass(frozen=True)
class PreferredWorkDecision:
    name: str
    action: str
    reason: str = ""


@dataclass(frozen=True)
class PreferredWorkNotice:
    text: str
    level: str = "warn"


@dataclass(frozen=True)
class WorkDataBinding:
    action: str
    path: str = ""
    sheet: str = ""
    header_row: int = 0
    kind: str = ""
    notice: str = ""


class ActiveWorkSession:
    """선택한 작업의 실행뷰·매체·durable identity 상태를 한 벌로 보관한다."""

    def __init__(
        self,
        registry: JobStorePort,
        template_change=None,
        engine: HwpxEngine | None = None,
        on_work_changed: Callable[[], None] = lambda: None,
    ) -> None:
        self._registry = registry
        self._template_change = template_change
        self._engine = engine
        self._on_work_changed = on_work_changed
        self.vm: RunViewModel | None = None
        self._name = ""
        self.is_txt = False
        self.unsupported = False
        self.data_unbound = False
        self.seated_template_application_id: str | None = None
        self.browse_tab = TAB_AVAILABLE
        self.browse_query = ""
        self.preferred = ""

    def _require_engine(self) -> HwpxEngine:
        if self._engine is None:
            raise ValueError("문서 생성 엔진이 조립되지 않았습니다")
        return self._engine

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        if value != self._name:
            self._name = value
            self._on_work_changed()

    def clear(self) -> None:
        self.vm = None
        self.name = ""
        self.is_txt = False
        self.unsupported = False
        self.data_unbound = False
        self.seated_template_application_id = None

    def seat(self, job: Job) -> None:
        """작업의 매체·실행뷰·결속·Application 정체를 한 번에 앉힌다."""
        is_txt, unsupported = seat_kinds(job.template_path)
        data_unbound = not has_data_binding(job)
        vm = (
            None
            if is_txt or unsupported
            else RunViewModel(job, engine=self._require_engine())
        )
        application_id = (
            self._template_change.current_template_application_id(
                job.authority_id or None
            )
            if self._template_change is not None
            else None
        )
        self.data_unbound = data_unbound
        self.vm = vm
        self.is_txt = is_txt
        self.unsupported = unsupported
        self.seated_template_application_id = application_id

    def select(self, job: Job) -> None:
        self.seat(job)
        self.name = job.name

    def load(self, name: str) -> Job:
        return load_job(self._registry, name)

    def prepare_for_seat(self, job: Job) -> tuple[Job, bool]:
        """최초 template authority를 명령 경로에서 확립한 뒤 seat 값을 돌려준다."""
        was_prepared = bool(job.authority_id)
        if self._template_change is not None:
            self._template_change.ensure_bootstrapped(job.name)
            job = load_job(self._registry, job.name)
        return job, was_prepared

    @staticmethod
    def data_binding_mount(
        job: Job,
        current: tuple[str, str, int, str],
    ) -> WorkDataBinding:
        """선택 작업의 durable 데이터 결속을 현재 마운트와 대조한다."""
        if not has_data_binding(job):
            return WorkDataBinding(
                "none",
                notice=(
                    f"'{job.name}' 작업에는 연결된 데이터가 없습니다. 데이터를 고른 뒤 "
                    "편집기에서 저장하면 다음부터 이 작업과 함께 열립니다."
                ),
            )
        path, sheet, header_row, kind = data_binding_of(job)
        if data_binding_matches(job, *current[:3], kind=current[3]):
            return WorkDataBinding("current")
        if reference_missing(path):
            return WorkDataBinding(
                "missing",
                notice=(
                    f"이 작업에 연결된 데이터 파일을 찾을 수 없습니다: {path}. "
                    "데이터를 다시 고른 뒤 작업을 저장하세요."
                ),
            )
        return WorkDataBinding("mount", path, sheet, header_row, kind)

    def reload(self) -> ActiveWorkReload:
        """durable Work와 seat를 대조하고 달라진 부분만 다시 앉힌다."""
        if not self.name:
            return ActiveWorkReload()
        try:
            job = load_job(self._registry, self.name)
        except Exception:  # noqa: BLE001 - health surface reports unreadable Work.
            return ActiveWorkReload()
        if seat_kinds(job.template_path) != (self.is_txt, self.unsupported):
            self.seat(job)
            return ActiveWorkReload(changed=True, rules_changed=True, surface_changed=True)
        if self.vm is None:
            return ActiveWorkReload()
        same_rules = (
            job_content_fingerprint(self._registry, job)
            == job_content_fingerprint(self._registry, self.vm.job)
        )
        same_generation = (
            job.template_revision == self.vm.job.template_revision
            and job.binding_revision == self.vm.job.binding_revision
            and job.previous_rules == self.vm.job.previous_rules
        )
        if same_rules and same_generation:
            return ActiveWorkReload()
        self.seat(job)
        return ActiveWorkReload(changed=True, rules_changed=not same_rules)

    def rename(self, old_name: str, new_name: str) -> bool:
        if self.name != old_name:
            return False
        self.name = new_name
        if self.vm is not None:
            self.vm.job.name = new_name
        return True

    def relink_template(self, name: str, path: str, *, confirm: bool) -> dict:
        result = relink_job_template(
            self._registry,
            name,
            path,
            engine=self._require_engine(),
            confirm=confirm,
        )
        result["active"] = self.name == name
        return result

    def set_browse_tab(self, value: str) -> None:
        self.browse_tab = TAB_NEEDS_ACTION if value == TAB_NEEDS_ACTION else TAB_AVAILABLE

    def set_browse_query(self, value: object) -> None:
        self.browse_query = str(value)

    def same_snapshot(self, seated: Job, restored: Job) -> bool:
        return (
            job_content_fingerprint(self._registry, restored)
            == job_content_fingerprint(self._registry, seated)
            and restored.template_revision == seated.template_revision
            and restored.binding_revision == seated.binding_revision
            and restored.previous_rules == seated.previous_rules
        )

    def can_adopt_seated_identity(self, seated: Job, restored: Job) -> bool:
        return (
            (not seated.authority_id or seated.authority_id == restored.authority_id)
            and self.same_snapshot(seated, restored)
        )

    def reconcile_data_transition(
        self, incoming: "tuple[str, str, int, str]"
    ) -> DataTransitionReconciliation:
        """새 데이터 좌표에서 active Work를 유지할 수 있는지 IO까지 마쳐 고정한다."""
        active_job = None
        restored_application_id = None
        restore_failed = False
        exact_context_restorable = False
        if self.name:
            try:
                active_job = load_job(self._registry, self.name)
                if self._template_change is not None:
                    restored_application_id = (
                        self._template_change.current_template_application_id(
                            active_job.authority_id or None
                        )
                    )
                    if active_job.authority_id and restored_application_id is None:
                        restore_failed = True
                exact_context_restorable = bool(
                    self.vm is not None
                    and self.vm.job.authority_id
                    and active_job.authority_id == self.vm.job.authority_id
                    and self.same_snapshot(self.vm.job, active_job)
                    and (
                        self._template_change is None
                        or bool(
                            restored_application_id
                            and self.seated_template_application_id
                            and restored_application_id
                            == self.seated_template_application_id
                        )
                    )
                )
            except Exception:  # noqa: BLE001 - unreadable active Work cannot be restored.
                active_job = None
                restore_failed = True
        context = ActiveWorkContext(
            active=bool(self.name),
            work_ref=self.name or None,
            template_application_ref=restored_application_id,
            exact_context_restorable=exact_context_restorable,
            bound_to_current_data=(
                active_job is not None
                and data_binding_matches(active_job, *incoming[:3], kind=incoming[3])
            ),
        )
        decision = decide_active_work_after_data_transition(context)
        warning = ""
        if restore_failed:
            warning = (
                "이전 문서 작업을 다시 확인할 수 없어 선택을 해제했습니다. "
                "문서 작업을 다시 선택하세요."
            )
        elif active_job is not None and not exact_context_restorable:
            warning = (
                "이전 문서 작업이 같은 작업인지 확인할 수 없어 선택을 해제했습니다. "
                "문서 작업을 다시 선택하세요."
            )
        elif active_job is not None and not context.bound_to_current_data:
            warning = (
                "이전 문서 작업은 다른 데이터에 연결돼 있어 선택을 해제했습니다. "
                "아래 후보를 선택하거나 「문서 작업」에서 그 작업을 여세요."
            )
        return DataTransitionReconciliation(
            context=context,
            release=decision.disposition == RELEASE and bool(self.name),
            warning=warning,
        )

    def request_preferred(
        self, name: str, *, present_fields: list[str] | None
    ) -> PreferredWorkDecision:
        """라이브러리의 명시 선택을 즉시 실행할지 다음 마운트까지 보관할지 판정한다."""
        if not name:
            raise ValueError("겨눌 작업 이름이 비어 있습니다.")
        if not job_exists(self._registry, name):
            raise ValueError(f"'{name}' 작업을 찾을 수 없습니다.")
        job = load_job(self._registry, name)
        if has_data_binding(job):
            self.preferred = ""
            return PreferredWorkDecision(name, "select")
        self.preferred = name
        if present_fields is None:
            return PreferredWorkDecision(name, "store", "no_binding")
        ranked = rank_available(list_jobs(self._registry), present_fields)
        if any(item.name == name for item in ranked):
            self.preferred = ""
            return PreferredWorkDecision(name, "select")
        return PreferredWorkDecision(name, "store", "incompatible")

    def consume_preferred(self, *, present_fields: list[str]) -> PreferredWorkNotice | None:
        """마운트 뒤 보관된 선택을 한 번만 소비해 다음 행동 문안을 결정한다."""
        name, self.preferred = self.preferred, ""
        if not name:
            return None
        try:
            exists = job_exists(self._registry, name)
            ranked = rank_available(list_jobs(self._registry), present_fields) if exists else []
        except Exception:  # noqa: BLE001 - successful data mount remains committed.
            return PreferredWorkNotice(
                f"「문서 작업」에서 고른 '{name}' 작업을 다시 확인할 수 없습니다. "
                "아래 후보에서 문서 작업을 다시 선택하세요."
            )
        if not exists:
            return PreferredWorkNotice(
                f"「문서 작업」에서 고른 '{name}' 작업이 더는 없습니다."
            )
        promoted = preferred_promotion(ranked, active=self.name, preferred=name)
        next_action = "'문서 작업'에서 직접 선택하세요."
        if promoted:
            return PreferredWorkNotice(
                f"이전에 고른 '{promoted}' 작업을 이 데이터로 쓸 수 있습니다. "
                f"{next_action}"
            )
        if self.name:
            return PreferredWorkNotice(
                f"'{self.name}' 작업이 이미 열려 있어 '{name}' 으로 바꾸지 않았습니다. "
                f"{next_action}"
            )
        return PreferredWorkNotice(
            f"「문서 작업」에서 고른 '{name}' 은(는) 이 데이터와 구조가 맞지 않습니다. "
            "필요한 열을 갖춘 데이터를 고르거나 편집기에서 연결을 고치세요."
        )


__all__ = [
    "ActiveWorkReload",
    "ActiveWorkSession",
    "DataTransitionReconciliation",
    "PreferredWorkDecision",
    "PreferredWorkNotice",
    "WorkDataBinding",
]
