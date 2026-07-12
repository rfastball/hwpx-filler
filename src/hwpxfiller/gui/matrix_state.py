"""매트릭스 실행 ViewModel — Qt 비의존(링1). M 작업 × 공유 데이터(N행) 일괄 생성 결정.

위젯(:class:`~hwpxfiller.gui.matrix_view.MatrixRunView`)은 이 뷰모델을 들고 작업 다중선택·
데이터 겨눔·사전검증만 오케스트레이션한다. 데이터 겨눔은 단일 실행과 **완전히 같은**
리졸버(:func:`~hwpxfiller.gui.run_state.resolve_file_source`/``resolve_pool_source``)를 재사용
— 나라 키 마스킹·스냅샷·resultCode 정합이 매트릭스에도 그대로 관통한다(중복 0).

**매핑 재확정 없음**: 각 작업의 매핑은 정의 때 확정됐다. 생성은 :func:`~hwpxfiller.batch.
generate_matrix` 가 작업별 하위폴더로 수행한다(교차 충돌 차단·빈값 표식).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.dataset_pool import (
    STATUS_ACTIVE,
    DatasetPoolRegistry,
    default_dataset_pool_dir,
)
from ..core.job import Job, JobRegistry
from ..core.fill_ledger import template_path_drift
from .run_state import (
    FieldState,
    GateState,
    RunViewModel,
    resolve_file_source,
    resolve_pool_source,
)


@dataclass(frozen=True)
class JobFieldSummary:
    """한 작업의 필드 3상태 스냅샷(UD-04) — 매트릭스 행 배지·확인 게이트의 원천.

    단일 실행이 :class:`~hwpxfiller.gui.run_state.RunViewModel` 로 계산하는 필드 상태
    (채움/의도적 빈칸/미입력/구조 드리프트)를 **작업별로** 집계한 것이다. 매트릭스가
    이 스냅샷을 소비해 단일 실행과 같은 ADR-B 3상태 배지·ADR-E 확인 게이트를 얻는다
    (매트릭스 우회로 게이트가 조용히 소멸하던 결함의 봉합). ``acknowledged`` 는 미입력
    상태에만 유효하며 매트릭스 VM 의 (작업, 필드) 확인 집합을 반영한다.
    """

    job_name: str
    field_states: "tuple[FieldState, ...]"

    def _count(self, state: str) -> int:
        return sum(1 for s in self.field_states if s.state == state)

    @property
    def filled(self) -> int:
        return self._count("filled")

    @property
    def blank(self) -> int:
        return self._count("blank")

    @property
    def missing(self) -> int:
        return self._count("missing")

    @property
    def drift(self) -> int:
        return self._count("drift")

    def unmet(self) -> "list[str]":
        """미입력이면서 아직 확인 안 된 필드 — 있으면 이 작업이 게이트를 닫는다."""
        return [s.name for s in self.field_states
                if s.state == "missing" and not s.acknowledged]


class MatrixRunViewModel:
    """매트릭스 실행 상태 — 작업 다중선택 + 공유 데이터 겨눔 + 사전검증(Qt 비의존).

    ``pool_registry``/``secret_store``/``fetcher`` 주입 가능(테스트·앱 공유). 데이터는 파일·풀·
    나라(애드혹) 어느 경로로든 겨눌 수 있고, 결과 datasource/records 는 전 작업이 공유한다.
    """

    def __init__(
        self,
        job_registry: JobRegistry,
        *,
        pool_registry: "DatasetPoolRegistry | None" = None,
        secret_store=None,
        fetcher=None,
    ):
        self.job_registry = job_registry
        self.pool_registry = (
            pool_registry if pool_registry is not None
            else DatasetPoolRegistry(default_dataset_pool_dir())
        )
        self._secret_store = secret_store
        self._fetcher = fetcher
        self.datasource = None
        self.records: "list[dict]" = []
        self._selected: "set[str]" = set()
        # 사용자가 직접 확인한 (작업, 미입력필드) — 단일 실행의 ADR-E ack 의 매트릭스판.
        # 작업×필드 단위라 스테일 ack 로 미입력 게이트가 무단 통과하지 않는다(UD-04).
        self._acked: "set[tuple[str, str]]" = set()

    # ---------------------------------------------------------- 작업 선택
    def all_job_names(self) -> "list[str]":
        return self.job_registry.names()

    def set_job_selected(self, name: str, selected: bool) -> None:
        if selected:
            self._selected.add(name)
        else:
            self._selected.discard(name)

    def is_selected(self, name: str) -> bool:
        return name in self._selected

    def selected_job_names(self) -> "list[str]":
        """선택된 작업 이름(레지스트리 순서 유지, 사라진 선택은 무시)."""
        return [n for n in self.all_job_names() if n in self._selected]

    def selected_jobs(self) -> "list[Job]":
        return [self.job_registry.load(n) for n in self.selected_job_names()]

    def selection_count(self) -> int:
        return len(self.selected_job_names())

    # ---------------------------------------------------------- 데이터 겨눔
    def load_file(self, path: str) -> "list[dict]":
        source, records = resolve_file_source(path)
        if not records:
            return []
        self.datasource = source
        self.records = records
        self.reset_acks()  # 새 데이터 → 미입력 확인 재평가(UD-04)
        return records

    def active_pool_names(self) -> "list[str]":
        return [it.name for it in self.pool_registry.list_items(status=STATUS_ACTIVE)]

    def load_pool_item(self, item) -> "list[dict]":
        source, records = resolve_pool_source(
            item, secret_store=self._secret_store, fetcher=self._fetcher
        )
        if not records:
            return []
        self.datasource = source
        self.records = records
        self.reset_acks()  # 새 데이터 → 미입력 확인 재평가(UD-04)
        return records

    def load_pool_by_name(self, name: str) -> "list[dict]":
        return self.load_pool_item(self.pool_registry.load(name))

    def set_acquired(self, datasource, records: "list[dict]") -> None:
        """애드혹 나라 취득 등 이미 만들어진 (키 없는) 소스·레코드를 직접 겨눈다."""
        self.datasource = datasource
        self.records = list(records)
        self.reset_acks()  # 새 데이터 → 미입력 확인 재평가(UD-04)

    # ---------------------------------------------------------- 사전검증
    def output_conflicts(self, indices: "list[int]", out_dir: str) -> "list[str]":
        """생성이 덮어쓸 **기존** 파일 경로 목록(작업별 하위폴더 규칙 동일, RC-02).

        :func:`~hwpxfiller.batch.matrix_output_conflicts` 위임 — 위젯은 이 목록이 비지
        않으면 사용자 확정을 받은 뒤에만 ``overwrite=True`` 로 진행한다(확인-또는-경보).
        """
        from ..batch import matrix_output_conflicts

        return matrix_output_conflicts(
            self.selected_jobs(), self.datasource, indices, out_dir
        )

    def validate(self, indices: "list[int]", out_dir: str) -> "list[str]":
        """생성 전 가드 — 모든 위반 사유(빈 목록이면 통과). 시끄럽게 표면화."""
        errs: "list[str]" = []
        jobs = self.selected_jobs()
        if not jobs:
            errs.append("작업을 1개 이상 선택하세요.")
        if self.datasource is None:
            errs.append("데이터를 선택하세요.")
        if not list(indices):
            errs.append("생성할 레코드를 1건 이상 선택하세요.")
        if not out_dir:
            errs.append("저장 폴더를 지정하세요.")
        # 템플릿이 없거나(경로 미지정) 파일이 부재한 작업은 게이트에서 시끄럽게 막는다
        # (생성 단계 개별 실패로 흘리지 않고 착수 전에 고지).
        unrunnable = [
            j.name for j in jobs
            if not j.template_path or not Path(j.template_path).exists()
        ]
        if unrunnable:
            errs.append("템플릿이 없거나 찾을 수 없는 작업: " + ", ".join(unrunnable))
        for job in jobs:
            if not job.template_path or not Path(job.template_path).exists():
                continue
            drift = template_path_drift(job.template_path, job.mapping)
            if drift.has_drift:
                if drift.read_error:
                    detail = "구조를 읽을 수 없음"
                else:
                    fields = list(drift.template_only) + list(drift.mapping_only) + list(drift.conflicting)
                    detail = ", ".join(fields)
                errs.append(f"템플릿 구조 드리프트({job.name}): {detail}")
        return errs

    # ---------------------------------- 필드 3상태 배지·확인 게이트(UD-04, ADR-B/E)
    def field_summaries(self, indices: "list[int]") -> "list[JobFieldSummary]":
        """선택 작업×겨눈 데이터의 작업별 필드 3상태 집계(배지·게이트의 원천, UD-04).

        각 작업의 필드 상태는 단일 실행과 **완전히 같은** 링1 산출
        (:meth:`~hwpxfiller.gui.run_state.RunViewModel.field_states`)을 재사용해 계산한다
        — 매트릭스가 별도 판정 로직을 재발명하지 않는다(내부 다수 패턴 정합). 미입력
        상태의 ``acknowledged`` 는 이 VM 의 (작업, 필드) 확인 집합에서 덮어쓴다. 데이터
        미겨눔이면 빈 목록(위젯이 빈 상태 안내를 렌더).
        """
        if self.datasource is None:
            return []
        idx = list(indices)
        summaries: "list[JobFieldSummary]" = []
        for job in self.selected_jobs():
            rvm = RunViewModel(job)
            rvm.datasource = self.datasource
            rvm.records = self.records
            states: "list[FieldState]" = []
            for s in rvm.field_states(idx):
                if s.state == "missing":
                    states.append(
                        FieldState(s.name, s.state, (job.name, s.name) in self._acked)
                    )
                else:
                    states.append(s)
            summaries.append(JobFieldSummary(job.name, tuple(states)))
        return summaries

    def unmet_missing(self, indices: "list[int]") -> "list[tuple[str, str]]":
        """전 선택 작업에서 미입력이면서 아직 확인 안 된 (작업, 필드) — 게이트가 닫힌다."""
        return [
            (js.job_name, name)
            for js in self.field_summaries(indices)
            for name in js.unmet()
        ]

    def acknowledge(self, job_name: str, field: str) -> None:
        """미입력 배지 클릭 = 직접 확인(강제 상호작용). 다 확인되면 일괄 생성이 열린다."""
        self._acked.add((job_name, field))

    def unacknowledge(self, job_name: str, field: str) -> None:
        """확인 철회(제자리 토글) — 게이트가 다시 닫혀 확인의 의미를 보전한다(UD-19 대칭)."""
        self._acked.discard((job_name, field))

    def reset_acks(self) -> None:
        """확인 상태 초기화(새 데이터 겨눔 등) — 스테일 ack 로 게이트가 새지 않게 한다."""
        self._acked.clear()

    def missing_gate(self, indices: "list[int]") -> GateState:
        """미입력 확인 게이트의 단일 표시 결정(UD-04) — 위젯은 그대로 렌더한다.

        단일 실행이 우회 없이 강제하는 ADR-E 미입력 확인을 매트릭스에도 이식한다 —
        미확인 미입력이 하나라도 있으면 '버튼 비활성 + 인라인 사유'로 막고, 사유엔
        어느 작업의 어느 필드인지를 재진술한다(강제 상호작용). 데이터·작업·폴더 같은
        기본 전제는 :meth:`validate` 가 계속 소유한다(중복 판정 금지) — 이 게이트는
        미입력 확인 축만 얹는다.
        """
        unmet = self.unmet_missing(indices)
        if not unmet:
            return GateState(True, "", "")
        by_job: "dict[str, list[str]]" = {}
        for job_name, field in unmet:
            by_job.setdefault(job_name, []).append(field)
        parts = "; ".join(f"{jn}({', '.join(fs)})" for jn, fs in by_job.items())
        return GateState(
            False, "warn",
            f"미입력 {len(unmet)}필드의 배지를 눌러 확인해야 일괄 생성이 가능합니다: {parts}",
        )
