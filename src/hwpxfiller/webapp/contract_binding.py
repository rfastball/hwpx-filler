"""데이터 계약을 든 미결속 작업의 결속 — 편집기 없이 데이터를 잇는 두 자리(#1193).

작업 꾸러미로 받은 작업은 「데이터 연결 필요」로 착지한다. 같은 모양의 데이터를 이미 가진 사람에게
편집기·데이터 고르기·저장을 다시 시키지 않으려고, **데이터 계약을 든 미결속 작업**만 계약 판정
(:func:`~hwpxfiller.domain.data_contract_check.judge_job_contract`)을 근거로 결속한다. 쓰기는
:func:`~hwpxfiller.external.contract_data_binding.bind_contract_data` 하나이고 쓰기 잠금 안에서
판정한 작업과 지금 작업을 다시 대조한다. 일반 작업(계약 없음)은 종전대로 편집기 저장만 결속한다.

- **불러오기 직후**(:class:`ImportAutobinder`) — 받는 쪽 등록 데이터(활성 항목, 선언한 시트마다)
  가운데 계약을 전부 통과하는 데이터가 **정확히 하나**면 결속한다. 없거나 둘 이상이면 고르지 않는다.
  읽지 못한 등록 데이터가 하나라도 있으면 그 데이터가 통과했을지 모르므로 고르지 않는다(자리에 없는
  파일·손상된 등록 항목은 지금 가진 데이터가 아니라 후보가 아니다). 판정·쓰기가 실패해도 불러오기는
  그대로 성공이다 — 작업은 문서에 적힌 착지(「데이터 연결 필요」)에 남는다.
- **데이터 선택 뒤**(:class:`ContractDataBinding`) — 「문서 만들기」에 데이터가 서면 그 데이터에
  결속된 작업과 함께 **계약을 통과하는 미결속 작업**도 후보다. 그런 작업을 고르면 지금 데이터로
  결속하고 결속된 작업과 같은 길을 간다. 통과하지 못하면 결속하지 않고 사유 줄을 낸다.

판정은 마운트(세대)마다 작업의 연결·계약별로 한 번만 계산한다 — 스냅샷마다 행 전체를 다시 돌리지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..application.dataset_pool import reference_missing
from ..data.factory import source_for_binding
from ..domain.data_contract import binding_fingerprint
from ..domain.data_contract_check import JobContractFit, judge_job_contract
from ..domain.dataset_reference import STATUS_ACTIVE, excel_identity, reference_for_sheet, reference_sheets
from ..domain.job import Job, has_data_binding
from ..external.contract_data_binding import ContractBindingRefused, bind_contract_data
from .screens import pool_reference_quad

if TYPE_CHECKING:
    from ..external.dataset_store import DatasetPoolRegistry
    from ..external.job_store import JobRegistry
    from .data_zone import JobDataSession

Binding = tuple[str, str, int, str]

#: 계약을 통과하지 못한 연결 줄의 머리 — 뒤에 `: 필드(사유), 필드(사유)`.
CONTRACT_MISMATCH_HEAD = "꾸러미 조건과 다른 연결"

#: 불러오기 자동 결속의 작업별 결과(문장이 아니라 판정 이름이다).
AUTOBIND_BOUND = "bound"
AUTOBIND_NO_CONTRACT = "no_contract"
AUTOBIND_NO_MATCH = "no_match"
AUTOBIND_AMBIGUOUS = "ambiguous"
AUTOBIND_UNREADABLE = "unreadable"
AUTOBIND_REFUSED = "refused"


def contract_mismatch_line(fit: JobContractFit) -> str:
    """통과하지 못한 연결 줄 — 「꾸러미 조건과 다른 연결: 필드(사유), …」. 사유가 없으면 ``""``."""
    if not fit.failures:
        return ""
    return f"{CONTRACT_MISMATCH_HEAD}: " + ", ".join(
        f"{field}({reason})" for field, reason in fit.failures
    )


def _fit_key(job: Job) -> tuple:
    """같은 판정을 다시 쓸 수 있는 열쇠 — 이름·계약·연결 지문이 같으면 같은 판정이다."""
    return (
        job.name,
        job.data_contract,
        tuple((m.template_field, binding_fingerprint(m)) for m in job.mapping.mappings),
    )


class ContractDataBinding:
    """「문서 만들기」의 계약 후보·선택 결속 — ``bind`` 가 없으면 계약 후보도 없다(종전 거동)."""

    def __init__(self, bind: "Callable[[Job, Binding], Job] | None" = None) -> None:
        self._bind = bind
        self._mount: "tuple[int, int] | None" = None
        self._fits: "dict[tuple, JobContractFit]" = {}

    def _eligible(self, job: Job, data: "JobDataSession") -> bool:
        return (
            self._bind is not None
            and job.data_contract is not None
            and not has_data_binding(job)
            and bool(data.path)
            and bool(data.records)
        )

    def _fit(self, job: Job, data: "JobDataSession") -> JobContractFit:
        assert job.data_contract is not None  # _eligible 가 먼저 걸렀다
        mount = (data.snapshot_generation, id(data.records))
        if mount != self._mount:
            self._mount, self._fits = mount, {}
        key = _fit_key(job)
        if key not in self._fits:
            self._fits[key] = judge_job_contract(
                job.data_contract, job.mapping, list(data.records[0]), data.records
            )
        return self._fits[key]

    def candidates(self, data: "JobDataSession", jobs: "list[Job]") -> "list[Job]":
        """이 마운트에 결속된 작업 + 계약을 통과하는 미결속 작업(입력 순서 그대로)."""
        bound = {job.name for job in data.bound_jobs(jobs)}
        return [
            job for job in jobs
            if job.name in bound or (self._eligible(job, data) and self._fit(job, data).passed)
        ]

    def bind_for_selection(self, job: Job, data: "JobDataSession") -> "tuple[Job, str]":
        """고른 작업이 계약을 통과하면 지금 데이터로 결속한 작업을, 아니면 그대로와 사유 줄을 낸다."""
        if not self._eligible(job, data) or self._bind is None:
            return job, ""
        fit = self._fit(job, data)
        if not fit.passed:
            return job, contract_mismatch_line(fit)
        try:
            return self._bind(job, (data.path, data.sheet, data.header_row, data.kind)), ""
        except ContractBindingRefused:  # 그사이 결속·연결이 바뀌었다 — 지금 판정은 그 작업의 것이 아니다
            return job, ""


# ------------------------------------------------------------------ 불러오기 직후


@dataclass(frozen=True)
class DataReading:
    """등록 데이터 하나를 읽은 결과 — ``columns`` 가 ``None`` 이면 읽지 못했다."""

    binding: Binding
    columns: "tuple[str, ...] | None"
    records: "Sequence[Mapping[str, object]]" = ()


@dataclass(frozen=True)
class AutobindOutcome:
    """불러온 작업 하나의 자동 결속 결과 — ``binding`` 은 결속했을 때만 선다."""

    name: str
    status: str
    binding: "Binding | None" = None


def _item_bindings(item) -> "list[Binding]":
    """등록 항목 하나가 선언한 시트마다의 결속 한 벌 — 파일 참조(엑셀·계약 목록)만."""
    if item.kind not in ("excel", "pclm"):
        return []
    try:
        sheets = reference_sheets(item)
    except ValueError:  # 시트 선언이 깨진 항목은 기본 시트만 본다
        sheets = []
    return [pool_reference_quad(reference_for_sheet(item, sheet)) for sheet in sheets or [None]]


def registered_bindings(pool_registry: "DatasetPoolRegistry") -> "list[Binding]":
    """받는 쪽이 지금 가진 등록 데이터의 결속 후보 — 활성·자리에 있는 파일만, 같은 데이터는 한 번."""
    found: "dict[tuple, Binding]" = {}
    for _key, item in pool_registry.list_entries(STATUS_ACTIVE, corrupted=[]):
        for binding in _item_bindings(item):
            path, sheet, header_row, kind = binding
            if path and not reference_missing(path):
                found.setdefault((kind, excel_identity(path, sheet), header_row), binding)
    return list(found.values())


def read_binding(binding: Binding) -> DataReading:
    """결속 한 벌을 실제 어댑터로 읽는다 — 실패는 「모름」(``columns=None``)이지 예외가 아니다."""
    path, sheet, header_row, kind = binding
    try:
        source = source_for_binding(
            {"path": path, "sheet": sheet, "header_row": header_row, "kind": kind}
        )
        records = source.records()
        columns = tuple(source.fields())
    except Exception:  # noqa: BLE001 — 읽지 못한 데이터는 고르지 않는 근거다(불러오기는 실패가 아니다)
        return DataReading(binding, None)
    return DataReading(binding, columns, records)


def choose_binding(job: Job, readings: "Sequence[DataReading]") -> "tuple[str, Binding | None]":
    """계약을 통과하는 데이터가 정확히 하나일 때만 그 결속 — 아니면 고르지 않은 이유."""
    if job.data_contract is None:
        return AUTOBIND_NO_CONTRACT, None
    if any(reading.columns is None for reading in readings):
        return AUTOBIND_UNREADABLE, None
    fits = [
        reading.binding for reading in readings
        if judge_job_contract(
            job.data_contract, job.mapping, reading.columns or (), reading.records
        ).passed
    ]
    if len(fits) == 1:
        return AUTOBIND_BOUND, fits[0]
    return (AUTOBIND_AMBIGUOUS if fits else AUTOBIND_NO_MATCH), None


class ImportAutobinder:
    """불러온 작업들을 받는 쪽 등록 데이터에 자동 결속한다 — 등록 데이터는 한 번만 읽는다."""

    def __init__(
        self,
        registry: "JobRegistry",
        pool_registry: "DatasetPoolRegistry",
        *,
        read: "Callable[[Binding], DataReading]" = read_binding,
    ) -> None:
        self._registry = registry
        self._pool = pool_registry
        self._read = read

    def bind_imported(self, names: "Sequence[str]") -> "list[AutobindOutcome]":
        jobs = [self._registry.load(name) for name in names]
        if not any(job.data_contract is not None for job in jobs):
            return [AutobindOutcome(job.name, AUTOBIND_NO_CONTRACT) for job in jobs]
        readings = [self._read(binding) for binding in registered_bindings(self._pool)]
        return [self._bind_one(job, readings) for job in jobs]

    def _bind_one(self, job: Job, readings: "Sequence[DataReading]") -> AutobindOutcome:
        status, binding = choose_binding(job, readings)
        if binding is None:
            return AutobindOutcome(job.name, status)
        try:
            bind_contract_data(self._registry, job, binding)
        except Exception:  # noqa: BLE001 — 거절·쓰기 실패는 미결속 착지로 남는다(불러오기는 성공)
            return AutobindOutcome(job.name, AUTOBIND_REFUSED)
        return AutobindOutcome(job.name, AUTOBIND_BOUND, binding)


__all__ = [
    "AUTOBIND_AMBIGUOUS",
    "AUTOBIND_BOUND",
    "AUTOBIND_NO_CONTRACT",
    "AUTOBIND_NO_MATCH",
    "AUTOBIND_REFUSED",
    "AUTOBIND_UNREADABLE",
    "CONTRACT_MISMATCH_HEAD",
    "AutobindOutcome",
    "ContractDataBinding",
    "DataReading",
    "ImportAutobinder",
    "choose_binding",
    "contract_mismatch_line",
    "read_binding",
    "registered_bindings",
]
