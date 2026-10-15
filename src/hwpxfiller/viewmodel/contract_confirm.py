"""데이터 계약 자동확정의 행 상태 — 재조립한 매핑 초안에 계약 판정을 얹고 표에 투영한다(#1188 WP-02).

데이터를 바꾸면 이월한 행의 확정이 전원 풀린다(C1, :func:`~hwpxfiller.webapp.editor_transitions.
ensure_model`). **데이터 계약을 든 작업만** 예외다: 이월한 사람 소유 행 가운데 계약을 통과한 행은
확정으로 착지하고 「자동확정 · 꾸러미 조건 일치」로 구별되며, 통과하지 못한 행은 미확정으로 남고
Python 이 지은 사유를 같은 행 투영으로 낸다(판정은 :mod:`hwpxfiller.domain.data_contract_check`).

판정은 **그 판정을 받은 연결**에만 붙는다: 행에 남는 것은 판정 + 판정한 연결 지문이고, 투영은
지금 연결의 지문이 같을 때만 표지·사유를 낸다. 그래서 행을 편집하면 표지·사유가 저절로 걷히고,
사람이 확인을 다시 누르면(:meth:`~hwpxfiller.viewmodel.mapping_state.MappingModel.set_confirmed`)
판정이 걷혀 사람의 확인으로 읽힌다. 사람이 명시로 확인을 푼 행은 다시 확정하지 않는다.

데이터 교체 확인(「확정했거나 직접 편집한 매핑 N개 … 미확정으로 돌아갑니다」)의 N 도 같은 규칙을
따른다(:func:`reset_stakes`, #1193): 계약이 다시 판정할 행 — 연결이 계약 항목(고정값·오늘 날짜는
저장본)과 같고 사람이 명시로 풀지 않은 행 — 은 사람이 만든 것을 잃지 않으므로 세지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from ..domain.data_contract import DataContract, binding_fingerprint
from ..domain.data_contract_check import ContractVerdict, contract_target, judge_job_binding
from ..domain.mapping import FieldMapping, MappingProfile

if TYPE_CHECKING:
    from ..domain.job import Job
    from .mapping_state import MappingModel, RowState

AUTO_CONFIRM_CONTRACT_LABEL = "자동확정 · 꾸러미 조건 일치"


def _current(row: "RowState") -> "ContractVerdict | None":
    verdict = row.contract_verdict
    if verdict is None or verdict.binding != binding_fingerprint(row.to_mapping()):
        return None
    return verdict


def contract_state_label(row: "RowState") -> str:
    """계약으로 확정된 행의 배지 문안 — 아니면 ``""``(일반 상태 문안이 선다)."""
    verdict = _current(row)
    return AUTO_CONFIRM_CONTRACT_LABEL if row.confirmed and verdict and verdict.passed else ""


def contract_reason(row: "RowState") -> str:
    """계약을 통과하지 못해 미확정으로 남은 행의 사유 — 아니면 ``""``."""
    verdict = _current(row)
    return verdict.reason if not row.confirmed and verdict and not verdict.passed else ""


def apply_data_contract(
    model: "MappingModel",
    contract: DataContract,
    saved: MappingProfile,
    records: "Sequence[Mapping[str, object]]",
) -> int:
    """재조립한 초안의 이월 행(사람 소유)에 계약 판정을 얹는다 — 반환은 자동확정한 행 수."""
    confirmed = 0
    for row in model.rows:
        if not row.touched or row.manual_unconfirmed:
            continue  # 새 데이터 기준의 제안 행·사람이 명시로 확인을 푼 행은 판정하지 않는다
        verdict = judge_job_binding(contract, saved, row.to_mapping(), model.source_fields, records)
        row.contract_verdict = verdict
        if verdict is not None and verdict.passed:
            row.confirmed = True
            confirmed += 1
    return confirmed


def _rejudged(mapping: FieldMapping, contract: DataContract, saved: MappingProfile) -> bool:
    """이 연결을 계약이 다시 판정하는가 — 계약 항목(데이터를 읽지 않는 연결은 저장본)과 같은 연결."""
    if contract_target(mapping):
        entry = contract.entry_for(mapping.template_field)
        return entry is not None and entry.binding == binding_fingerprint(mapping)
    saved_mapping = next(
        (m for m in saved.mappings if m.template_field == mapping.template_field), None
    )
    return saved_mapping is not None and binding_fingerprint(saved_mapping) == binding_fingerprint(mapping)


def reset_stakes(model: "MappingModel", base: "Job | None", *, rejudge: bool) -> int:
    """재조립이 미확정으로 되돌릴 사람 소유 행 수 — 이월 행에서 계약이 다시 판정할 행을 뺀다.

    ``rejudge`` 는 재조립 뒤 계약을 댈 데이터가 있는가다(데이터 교체이거나 지금 데이터가 서 있다).
    계약이 없는 작업·판정할 데이터가 없는 재조립은 이월 행 전부다(C1 그대로).
    """
    carried = model.carry_profile().mappings
    if base is None or base.data_contract is None or not rejudge:
        return len(carried)
    contract = base.data_contract
    rejudged = {
        row.template_field for row in model.rows
        if not row.manual_unconfirmed and _rejudged(row.to_mapping(), contract, base.mapping)
    }
    return sum(1 for mapping in carried if mapping.template_field not in rejudged)


def reset_stakes_view(
    model: "MappingModel | None",
    base: "Job | None",
    resuggest_targets: "list[int]",
    *,
    rejudge: bool,
) -> dict:
    """편집기 확인 관문의 수 — 교체가 되돌릴 행(``human``)·다시 받기가 지울 수동 행·확정 행."""
    if model is None:
        return {"human": 0, "resuggest_manual": 0, "confirmed": 0}
    return {
        "human": reset_stakes(model, base, rejudge=rejudge),
        "resuggest_manual": sum(model.rows[i].touched for i in resuggest_targets),
        "confirmed": model.confirmed_count(),
    }


__all__ = [
    "AUTO_CONFIRM_CONTRACT_LABEL",
    "apply_data_contract",
    "reset_stakes",
    "reset_stakes_view",
    "contract_reason",
    "contract_state_label",
]
