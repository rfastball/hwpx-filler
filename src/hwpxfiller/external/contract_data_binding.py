"""데이터 계약을 통과한 작업의 데이터 결속 쓰기 — 편집기 저장 밖의 유일한 결속 쓰기(#1193).

데이터 결속은 편집기 저장이 쓴다. 예외는 하나다: 작업 꾸러미로 받은 작업처럼 **데이터 계약을 든
미결속 작업**이 어떤 데이터에서 계약을 전부 통과하면, 그 데이터의 참조 한 벌(경로·시트·헤더 행·
종류)을 편집기 없이 결속한다. 판정은 호출자(:func:`~hwpxfiller.domain.data_contract_check.
judge_job_contract`)가 끝냈고, 여기서는 그 판정이 **지금 디스크의 작업에 대해서도 참인지** 쓰기 잠금
안에서 다시 대조한 뒤에만 쓴다:

- 아직 결속이 없다(그사이 다른 표면이 결속했으면 덮지 않는다),
- 판정한 작업과 내용 지문·데이터 계약이 같다(그사이 연결이 바뀌었으면 판정은 그 연결의 것이 아니다).

어느 하나라도 어긋나면 :class:`ContractBindingRefused` 로 아무것도 쓰지 않는다. 결속은 규칙 축이
아니라 판본·검토 기준선이 움직이지 않는다(:func:`~hwpxfiller.domain.job.rules_values`).
"""

from __future__ import annotations

from ..domain.job import Job, has_data_binding
from .job_store import JobRegistry


class ContractBindingRefused(Exception):
    """판정한 작업이 지금 디스크의 작업과 다르거나 이미 결속됐다 — 아무것도 쓰지 않았다."""


def bind_contract_data(registry: JobRegistry, judged: Job, binding: "tuple[str, str, int, str]") -> Job:
    """판정한 작업 ``judged`` 에 데이터 결속 ``binding`` 을 쓴다 — 갱신된 작업을 돌려준다.

    ``binding`` 은 :func:`~hwpxfiller.domain.job.data_binding_of` 와 같은 한 벌
    ``(path, sheet, header_row, kind)`` 이다.
    """
    if judged.data_contract is None or not binding[0]:
        raise ContractBindingRefused()
    expected = registry.content_fingerprint(judged)

    def _bind(job: Job) -> None:
        if (
            has_data_binding(job)
            or job.data_contract != judged.data_contract
            or registry.content_fingerprint(job) != expected
        ):
            raise ContractBindingRefused()
        job.data_path, job.data_sheet, job.data_header_row, job.data_kind = binding

    return registry.mutate(judged.name, _bind)


__all__ = ["ContractBindingRefused", "bind_contract_data"]
