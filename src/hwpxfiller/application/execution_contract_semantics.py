"""S5F R2-02(#740) execution contract semantics — closed manifest 없는 작은 소비 값.

R2 둘째 절개의 목표는 13-role :class:`ExecutionContractSet` 을 몇 개로 **줄이는** 것이 아니라,
semantic kernel 이 closed contract manifest 를 **전혀 필요로 하지 않게** 만드는 것이다. 저장소에서
실제로 contract id 를 deref 하는 compilation/validation/delivery 소비자가 읽는 semantics 만 이
작은 immutable value 로 뽑아낸다. 기존 :class:`ExecutionContractSet` 은 legacy caller(seal
path·record_validation·delivery 가 legacy plan 을 소비할 때)용 **compatibility shell** 로 그대로
둔다 — 이 절개는 그것을 삭제하지 않는다.

실제 소비 지점(저장소 grep 근거):
  - ``record_validation`` (materialization 시): raw_record·source_schema·binding_value·
    record_validation·record_review·document_value_resolution 를 상수와 대조(fail-closed).
  - ``generation_delivery`` / ``materialization_conformance``: composition·native_primitive·
    materialization_base·materialization 을 읽음.
소비되지 않는 identity-only 역할(slot_selection·field_binding·execution_semantic contract id,
composition_theorem_evidence_manifest_digest, contract_set_manifest_digest, schema version)은
담지 않는다 — 그것들은 closed manifest 의 identity/cache/control-plane 관심사다.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


class ExecutionContractSemanticsError(ValueError):
    """contract semantics 값이 exact 하지 않다(빈 역할). latest 로 풀지 않고 시끄럽게 닫는다."""


@dataclass(frozen=True)
class ExecutionContractSemantics:
    """실제 compilation/validation/delivery 소비자가 읽는 contract semantics 만 담은 작은 값.

    closed manifest 가 **아니다** — manifest digest·schema version·미소비 identity 역할을 싣지 않는다.
    semantic kernel 은 Sealed Execution Plan value 에 이 값만 싣는다. 모든 필드는 exact 하게 채워져야
    한다(nonempty) — 결속 상수 대조(binding value·record validation 등)는 각 소비자(record_validation)
    가 materialization 시점에 fail-closed 로 진다(책임 분리: per-input admission ≠ record validation).
    """

    # record validation(materialization) 이 읽는 6.
    raw_record_contract_id: str
    source_schema_contract_id: str
    binding_value_contract_id: str
    record_validation_contract_id: str
    record_review_contract_id: str
    document_value_resolution_contract_id: str
    # composition/native + materialization/delivery 가 읽는 4.
    composition_contract_id: str
    native_primitive_contract_id: str
    materialization_base_contract_id: str
    materialization_contract_id: str

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if not isinstance(value, str) or value == "":
                raise ExecutionContractSemanticsError(
                    f"contract semantics 의 {f.name} 는 비어 있을 수 없다(exact 역할 누락)"
                )

    @classmethod
    def from_contract_set(cls, contracts: Any) -> "ExecutionContractSemantics":
        """legacy closed :class:`ExecutionContractSet` 에서 소비되는 semantics 만 투영한다.

        compatibility bridge·parity 검증·점진 이행에 쓴다 — manifest digest·schema·미소비 역할은
        버린다. ``contracts`` 는 필요한 attribute 만 있으면 되므로 구조적으로(duck) 받는다.
        """
        return cls(
            raw_record_contract_id=contracts.raw_record_contract_id,
            source_schema_contract_id=contracts.source_schema_contract_id,
            binding_value_contract_id=contracts.binding_value_contract_id,
            record_validation_contract_id=contracts.record_validation_contract_id,
            record_review_contract_id=contracts.record_review_contract_id,
            document_value_resolution_contract_id=(
                contracts.document_value_resolution_contract_id
            ),
            composition_contract_id=contracts.composition_contract_id,
            native_primitive_contract_id=contracts.native_primitive_contract_id,
            materialization_base_contract_id=contracts.materialization_base_contract_id,
            materialization_contract_id=contracts.materialization_contract_id,
        )
