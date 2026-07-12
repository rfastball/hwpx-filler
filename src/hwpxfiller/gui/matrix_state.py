"""매트릭스 실행 ViewModel — Qt 비의존(링1). M 작업 × 공유 데이터(N행) 일괄 생성 결정.

위젯(:class:`~hwpxfiller.gui.matrix_view.MatrixRunView`)은 이 뷰모델을 들고 작업 다중선택·
데이터 겨눔·사전검증만 오케스트레이션한다. 데이터 겨눔은 단일 실행과 **완전히 같은**
리졸버(:func:`~hwpxfiller.gui.run_state.resolve_file_source`/``resolve_pool_source``)를 재사용
— 나라 키 마스킹·스냅샷·resultCode 정합이 매트릭스에도 그대로 관통한다(중복 0).

**매핑 재확정 없음**: 각 작업의 매핑은 정의 때 확정됐다. 생성은 :func:`~hwpxfiller.batch.
generate_matrix` 가 작업별 하위폴더로 수행한다(교차 충돌 차단·빈값 표식).
"""

from __future__ import annotations

from pathlib import Path

from ..core.dataset_pool import (
    STATUS_ACTIVE,
    DatasetPoolRegistry,
    default_dataset_pool_dir,
)
from ..core.job import Job, JobRegistry
from .run_state import resolve_file_source, resolve_pool_source


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
        return records

    def load_pool_by_name(self, name: str) -> "list[dict]":
        return self.load_pool_item(self.pool_registry.load(name))

    def set_acquired(self, datasource, records: "list[dict]") -> None:
        """애드혹 나라 취득 등 이미 만들어진 (키 없는) 소스·레코드를 직접 겨눈다."""
        self.datasource = datasource
        self.records = list(records)

    # ---------------------------------------------------------- 사전검증
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
        return errs
