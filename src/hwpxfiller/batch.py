"""일괄 생성 오케스트레이션 — VBA ``Process_HWP_Generation`` 의 순수 로직 포트.

UI(MsgBox) 를 제거하고, 템플릿 + 레코드 목록 + 저장경로/파일명 패턴을 받아
문서를 일괄 생성하고 결과를 구조화해 반환한다. GUI/CLI 가 이를 감싼다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .core.engine import GenerateResult, HwpxEngine
from .naming import OutputNamer


@dataclass
class BatchResult:
    total: int = 0
    succeeded: int = 0
    results: "list[GenerateResult]" = field(default_factory=list)

    @property
    def failed(self) -> int:
        return self.total - self.succeeded


def generate_batch(
    template_path: str,
    records: "list[dict[str, str]]",
    out_dir: str,
    name_pattern: str,
    engine: "HwpxEngine | None" = None,
    *,
    progress: "Callable[[int, int], None] | None" = None,
    now: "datetime | None" = None,
) -> BatchResult:
    """레코드 목록을 순회하며 문서를 일괄 생성한다.

    파일명은 :class:`OutputNamer` 가 배치 단위로 할당한다(연번·날짜 토큰·충돌 접미사).
    ``progress(done, total)`` 는 레코드마다 호출되는 선택적 콜백(GUI 워커의 진행률용).
    ``now`` 는 날짜 토큰 기준 시각 주입(테스트 결정성).
    """
    engine = engine or HwpxEngine()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    namer = OutputNamer(name_pattern, now=now)

    batch = BatchResult(total=len(records))
    for i, rec in enumerate(records, 1):
        target = str(out / namer.next(rec))
        res = engine.generate(template_path, rec, target)
        batch.results.append(res)
        if res.ok:
            batch.succeeded += 1
        if progress:
            progress(i, batch.total)
    return batch


# ------------------------------------------------------------ 매트릭스 실행(J2)
@dataclass
class MatrixJobResult:
    """매트릭스 실행에서 한 작업(=템플릿+매핑)의 생성 결과 + 그 작업의 출력 하위폴더."""

    job_name: str
    out_dir: str
    batch: BatchResult


@dataclass
class MatrixResult:
    """M 작업 × 공유 데이터(N행) 일괄 생성의 집계 결과."""

    per_job: "list[MatrixJobResult]" = field(default_factory=list)

    @property
    def job_count(self) -> int:
        return len(self.per_job)

    @property
    def total(self) -> int:
        return sum(j.batch.total for j in self.per_job)

    @property
    def succeeded(self) -> int:
        return sum(j.batch.succeeded for j in self.per_job)

    @property
    def failed(self) -> int:
        return self.total - self.succeeded


def generate_matrix(
    jobs,
    datasource,
    indices: "list[int]",
    out_dir: str,
    engine: "HwpxEngine | None" = None,
    *,
    progress: "Callable[[int, int], None] | None" = None,
    now: "datetime | None" = None,
    mark_missing: "str | None" = None,
) -> MatrixResult:
    """**M 작업 × 공유 데이터(N행)** 일괄 생성 — 1:1 실행 표면 인공물 해소(ADR J 축2).

    각 작업은 자기 템플릿+매핑을 **같은** 선택 레코드에 적용하고, 결과를 **작업별
    하위폴더**(``out_dir/<작업이름>/``)에 쓴다 — 교차 충돌을 폴더로 원천 차단하고(작업별
    독립 :class:`OutputNamer`), 각 작업은 자기 파일명 패턴을 그대로 쓴다. 단일 잡×단일
    데이터는 이 함수를 안 거치는 기존 :func:`generate_batch` 경로 그대로라 회귀 불변.

    매핑·빈값 처리는 :meth:`~hwpxfiller.core.job.RunRequest.mapped_records` 재사용 —
    ``mark_missing`` 이 주어지면 빈 필드에 표식을 넣어 **누락을 시끄럽게**(기본은
    :data:`~hwpxfiller.core.job.MISSING_MARKER`; 명시적 ``""`` 로 끄기 가능). 엔진의 빈값
    스킵(``engine.py:42``)은 불변.
    """
    from .core.job import MISSING_MARKER, RunRequest, _slug
    from .core.fill_ledger import template_path_drift

    if mark_missing is None:
        mark_missing = MISSING_MARKER
    engine = engine or HwpxEngine()
    indices = list(indices)
    jobs = list(jobs)
    # 실제 생성 경계에서 **전 작업을 먼저** 재검사한다. GUI validate 이후 템플릿이
    # 바뀌거나 worker/API가 validate를 우회해도 한 작업이라도 구조 계약이 깨졌으면
    # 출력 폴더조차 만들기 전에 원자 차단한다(부분 생성 후 발견 금지).
    drift_errors: "list[str]" = []
    for job in jobs:
        drift = template_path_drift(job.template_path, job.mapping)
        if not drift.has_drift:
            continue
        if drift.read_error:
            detail = "구조를 읽을 수 없음: " + drift.read_error
        else:
            names = list(drift.template_only) + list(drift.mapping_only) + list(drift.conflicting)
            detail = "매핑 재확정 필요: " + ", ".join(names)
        drift_errors.append(f"{job.name}: {detail}")
    if drift_errors:
        raise ValueError("템플릿 구조 드리프트로 매트릭스 생성을 차단했습니다 — " + "; ".join(drift_errors))

    grand_total = len(jobs) * len(indices)
    root = Path(out_dir)
    result = MatrixResult()
    done = 0
    for job in jobs:
        req = RunRequest(job, datasource, indices)
        mapped = req.mapped_records(mark_missing=mark_missing)
        # 폴더명은 레지스트리 파일명과 같은 slug(공백 정리 + 빈이름→unnamed)로 일관.
        job_dir = str(root / _slug(job.name))

        def _job_progress(i: int, _n: int, _base: int = done) -> None:
            if progress:
                progress(_base + i, grand_total)

        batch = generate_batch(
            job.template_path, mapped, job_dir, job.filename_pattern,
            engine=engine, progress=_job_progress, now=now,
        )
        result.per_job.append(MatrixJobResult(job.name, job_dir, batch))
        done += batch.total
    return result
