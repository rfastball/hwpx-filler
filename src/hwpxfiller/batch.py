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
from .naming import existing_outputs, plan_output_names


@dataclass
class BatchResult:
    total: int = 0
    succeeded: int = 0
    results: "list[GenerateResult]" = field(default_factory=list)
    # 협조적 취소로 완주하지 못했는가(RC-06) — True 면 results 는 부분 결과다.
    cancelled: bool = False

    @property
    def failed(self) -> int:
        return self.total - self.succeeded

    @property
    def attempted(self) -> int:
        """실제 시도한 레코드 수 — 취소 시 total(계획)과 갈라진다."""
        return len(self.results)


def generate_batch(
    template_path: str,
    records: "list[dict[str, str]]",
    out_dir: str,
    name_pattern: str,
    engine: "HwpxEngine | None" = None,
    *,
    progress: "Callable[[int, int], None] | None" = None,
    now: "datetime | None" = None,
    overwrite: bool = False,
    mapping=None,
    cancelled: "Callable[[], bool] | None" = None,
) -> BatchResult:
    """레코드 목록을 순회하며 문서를 일괄 생성한다.

    ``mapping``(:class:`~hwpxfiller.core.mapping.MappingProfile`)이 주어지면 **생성
    경계에서** 템플릿 구조 드리프트를 재검사한다(RC-03) — 매트릭스와 대칭. 호출측
    validate 이후 템플릿이 교체돼도(TOCTOU) 다른 문서종이 '성공'으로 섞여 나가지
    않도록 첫 파일을 쓰기 전에 :class:`ValueError` 로 원자 차단한다. 문구는
    :meth:`~hwpxfiller.core.fill_ledger.TemplateStructureDrift.describe` 단일화.

    파일명은 :func:`~hwpxfiller.naming.plan_output_names` 로 **먼저 전부** 계산한다
    (연번·날짜 토큰·배치 내 충돌 접미사 — :class:`~hwpxfiller.naming.OutputNamer` 규칙).
    대상 중 디스크에 이미 존재하는 파일이 있으면 ``overwrite=True`` 없이는 생성을
    시작하기 전에 :class:`FileExistsError` 로 원자 차단한다(RC-02: 기존 산출물의
    무경고 파괴 금지 — GUI 는 사용자 확인 후, CLI 는 ``--overwrite`` 로만 통과).
    ``progress(done, total)`` 는 레코드마다 호출되는 선택적 콜백(GUI 워커의 진행률용).
    ``cancelled()`` 가 True 를 돌려주면 **레코드 경계에서** 중단한다(RC-06) — 진행
    중인 문서는 완결하고, 결과엔 ``cancelled=True`` 와 부분 결과가 남는다.
    ``now`` 는 날짜 토큰 기준 시각 주입(테스트 결정성).
    """
    if mapping is not None:
        from .core.fill_ledger import template_path_drift

        drift = template_path_drift(template_path, mapping)
        if drift.has_drift:
            raise ValueError(
                "템플릿 구조 드리프트로 생성을 차단했습니다 — " + drift.describe(sep="; ")
            )
    engine = engine or HwpxEngine()
    out = Path(out_dir)
    names = plan_output_names(name_pattern, records, now=now)
    clobbered = existing_outputs(out, names)
    if clobbered and not overwrite:
        raise FileExistsError(
            f"이미 존재하는 파일 {len(clobbered)}개를 덮어쓰게 됩니다 — 덮어쓰기 확정 "
            "없이는 생성하지 않습니다: "
            + ", ".join(Path(p).name for p in clobbered)
        )
    out.mkdir(parents=True, exist_ok=True)

    batch = BatchResult(total=len(records))
    for i, (rec, name) in enumerate(zip(records, names, strict=True), 1):
        if cancelled is not None and cancelled():
            batch.cancelled = True
            break
        target = str(out / name)
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
    # 협조적 취소로 완주하지 못했는가(RC-06) — True 면 per_job 은 부분 결과다.
    cancelled: bool = False

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


def matrix_output_conflicts(
    jobs,
    datasource,
    indices: "list[int]",
    out_dir: str,
    *,
    now: "datetime | None" = None,
    mark_missing: "str | None" = None,
) -> "list[str]":
    """매트릭스 생성이 덮어쓸 **기존** 파일 경로 전체(무변형 검출, RC-02).

    :func:`generate_matrix` 와 동일한 매핑(``mapped_records``)·작업별 하위폴더(slug)·
    파일명 규칙으로 대상 경로를 계산해 디스크 존재만 조회한다. GUI 사전 확인과
    :func:`generate_matrix` 의 기본 차단이 이 목록을 공유한다.
    """
    from .core.job import MISSING_MARKER, RunRequest, _slug

    if mark_missing is None:
        mark_missing = MISSING_MARKER
    root = Path(out_dir)
    indices = list(indices)
    conflicts: "list[str]" = []
    for job in jobs:
        mapped = RunRequest(job, datasource, indices).mapped_records(mark_missing=mark_missing)
        names = plan_output_names(job.filename_pattern, mapped, now=now)
        conflicts.extend(existing_outputs(root / _slug(job.name), names))
    return conflicts


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
    overwrite: bool = False,
    cancelled: "Callable[[], bool] | None" = None,
) -> MatrixResult:
    """**M 작업 × 공유 데이터(N행)** 일괄 생성 — 1:1 실행 표면 인공물 해소(ADR J 축2).

    각 작업은 자기 템플릿+매핑을 **같은** 선택 레코드에 적용하고, 결과를 **작업별
    하위폴더**(``out_dir/<작업이름>/``)에 쓴다 — 교차 충돌을 폴더로 원천 차단하고(작업별
    독립 :class:`OutputNamer`), 각 작업은 자기 파일명 패턴을 그대로 쓴다. 단일 잡×단일
    데이터는 이 함수를 안 거치는 기존 :func:`generate_batch` 경로 그대로라 회귀 불변.

    매핑·빈값 처리는 :meth:`~hwpxfiller.core.job.RunRequest.mapped_records` 재사용 —
    ``mark_missing`` 이 주어지면 빈 필드에 표식을 넣어 **누락을 시끄럽게**(기본은
    :data:`~hwpxfiller.core.job.MISSING_MARKER`; 명시적 ``""`` 로 끄기 가능). 엔진의 빈값
    스킵(``engine.py:42``)은 불변. 디스크의 기존 파일과 충돌하면 ``overwrite=True``
    없이는 :class:`FileExistsError` 로 착수 전에 원자 차단한다(RC-02).
    ``cancelled()`` 는 레코드 경계 협조적 취소(RC-06) — 작업·레코드 경계에서 중단하고
    ``MatrixResult.cancelled=True`` 와 부분 결과를 남긴다.
    """
    from .core.job import MISSING_MARKER, RunRequest, _slug
    from .core.fill_ledger import template_path_drift

    if mark_missing is None:
        mark_missing = MISSING_MARKER
    engine = engine or HwpxEngine()
    now = now or datetime.now()  # 충돌 검출과 생성이 같은 날짜 토큰 시각을 공유
    indices = list(indices)
    jobs = list(jobs)
    # 실제 생성 경계에서 **전 작업을 먼저** 재검사한다. GUI validate 이후 템플릿이
    # 바뀌거나 worker/API가 validate를 우회해도 한 작업이라도 구조 계약이 깨졌으면
    # 출력 폴더조차 만들기 전에 원자 차단한다(부분 생성 후 발견 금지).
    drift_errors: "list[str]" = []
    for job in jobs:
        drift = template_path_drift(job.template_path, job.mapping)
        if drift.has_drift:
            # 문구는 describe() 단일화(RC-03) — 표면별 재조립 금지.
            drift_errors.append(f"{job.name}: {drift.describe(sep='; ')}")
    if drift_errors:
        raise ValueError("템플릿 구조 드리프트로 매트릭스 생성을 차단했습니다 — " + "; ".join(drift_errors))

    # 디스크 충돌도 생성 경계에서 **전 작업을 먼저** 검사해 원자 차단한다(RC-02) —
    # 일부 작업만 생성된 뒤 발견하지 않는다. 통과·확정 후엔 배치 재검사를 끈다
    # (아래 generate_batch 에 overwrite=True — 결정은 이 경계에서 한 번).
    if not overwrite:
        clobbered = matrix_output_conflicts(
            jobs, datasource, indices, out_dir, now=now, mark_missing=mark_missing
        )
        if clobbered:
            raise FileExistsError(
                f"이미 존재하는 파일 {len(clobbered)}개를 덮어쓰게 됩니다 — 덮어쓰기 확정 "
                "없이는 생성하지 않습니다: "
                + ", ".join(Path(p).name for p in clobbered)
            )

    grand_total = len(jobs) * len(indices)
    root = Path(out_dir)
    result = MatrixResult()
    done = 0
    for job in jobs:
        if cancelled is not None and cancelled():
            result.cancelled = True
            break
        req = RunRequest(job, datasource, indices)
        mapped = req.mapped_records(mark_missing=mark_missing)
        # 폴더명은 레지스트리 파일명과 같은 slug(공백 정리 + 빈이름→unnamed)로 일관.
        job_dir = str(root / _slug(job.name))

        def _job_progress(i: int, _n: int, _base: int = done) -> None:
            if progress:
                progress(_base + i, grand_total)

        # mapping 전달로 작업 시작 직전에도 드리프트를 재검사한다(RC-03) — 위의 전건
        # 원자 검사 이후 미드매트릭스 템플릿 교체(TOCTOU)까지 닫는다.
        batch = generate_batch(
            job.template_path, mapped, job_dir, job.filename_pattern,
            engine=engine, progress=_job_progress, now=now, overwrite=True,
            mapping=job.mapping, cancelled=cancelled,
        )
        result.per_job.append(MatrixJobResult(job.name, job_dir, batch))
        done += batch.total
        if batch.cancelled:
            result.cancelled = True
            break
    return result
