"""Ordered start gate (S6-02 · #810) — fence 아래 pin 을 세우고 풀린 뒤 LongMaterialization.

`S6_START_GATE_LOCK_ORDER`(application/seal_execution_plan.py)가 선언만 해 둔 순서의 구현이다:

```text
PerWorkMutationFence
  → Plan·current basis·runtime admission·VDR·dependency pin
  → <fences released>
  → LongMaterialization (= ProductionMaterializationRunner.materialize, S6-01)
```

긴 materialization 을 fence 밖에서 돌리는 이유가 이 모듈의 존재 이유다 — fence 는 pin(짧은
관찰·대조)만 지키고, bytes 작업이 다른 Work 명령을 막지 않는다. pin 의 재료는 전부 기존
기계다(새 판정 0): Plan·VDR·dependency 는 :class:`MaterializationInputPort`, current basis 는
`execution_basis_digest` 동등성, runtime admission 은 :func:`evaluate_managed_run_admission`.

거절 어휘도 기존 것을 재진술한다(D3 결): stale 은 `stored_execution_plan` 의 두 사유
(`DIGEST_MISMATCH`·`CURRENT_BASIS_NOT_SEALABLE`), admission 거절은 `ManagedRunAdmission.status`
그대로. executor/verifier 는 직접 부르지 않는다 — 러너 경유가 repo-contract
(`test_materialization_port_gate`)다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ContextManager, Protocol

from hwpxfiller.application.execution_composition import (
    RuntimeMaterializerConformanceRegistry,
)
from hwpxfiller.application.execution_contract_set import execution_basis_digest
from hwpxfiller.application.generation_delivery import (
    MaterializationInput,
    MaterializationInputPort,
    evaluate_managed_run_admission,
)
from hwpxfiller.application.stored_execution_plan import (
    CURRENT_BASIS_NOT_SEALABLE,
    DIGEST_MISMATCH,
)
from hwpxfiller.host.per_work_fence import per_work_mutation_fence

from .materialization_runner import (
    MaterializationOutcome,
    MaterializationProcurementError,
)

_WorkFence = Callable[[str, str], ContextManager[None]]


class MaterializationRunnerPort(Protocol):
    """pin 이 풀린 뒤 부르는 LongMaterialization — 매체마다 다른 러너가 이 자리에 선다.

    S10-04(#861)로 TXT 러너가 두 번째 구현이 되면서 gate 가 concrete class 를 이름으로 아는
    이유가 사라졌다(gate 는 순서·pin 만 지고 bytes 를 만들지 않는다). 러너 자격은 여전히
    `test_materialization_port_gate` 가 진다 — executor/verifier 를 직접 부를 수 있는 모듈은
    러너뿐이다.
    """

    def materialize(
        self, materialization_input: MaterializationInput
    ) -> MaterializationOutcome: ...

# current basis 관찰 seam — fence 아래에서 current Work 의 execution_basis_digest 를 읽는다.
# 관찰 불가(미봉인·chain 단절)는 None 으로 돌려 CURRENT_BASIS_NOT_SEALABLE 로 닫는다.
CurrentBasisDigestReader = Callable[[], "str | None"]


@dataclass(frozen=True)
class StartMaterializationRefusal:
    """pin 이 서지 않아 LongMaterialization 에 진입하지 않았다 — 사유는 기존 어휘 재진술."""

    code: str
    detail: str


StartMaterializationResult = MaterializationOutcome | StartMaterializationRefusal


def start_materialization(
    *,
    workspace_instance_id: str,
    work_authority_id: str,
    materialization_input: MaterializationInput,
    input_port: MaterializationInputPort,
    runner: MaterializationRunnerPort,
    runtime_registry: RuntimeMaterializerConformanceRegistry,
    runtime_capability_manifest_digest: str,
    current_basis_digest_reader: CurrentBasisDigestReader,
    work_fence: _WorkFence = per_work_mutation_fence,
) -> StartMaterializationResult:
    """S6_START_GATE_LOCK_ORDER 그대로: fence → pin → fences released → LongMaterialization.

    pin 넷은 전부 대조이고 어느 것도 filesystem 을 만지지 않는다. 거절은 refusal 값으로,
    조달 불능은 loud 예외로 닫힌다 — 둘 다 fence 해제 후 filesystem 불변이다.
    """
    with work_fence(workspace_instance_id, work_authority_id):
        # pin 1 — Plan·VDR·dependency: digest 재검증·cross-bind·완결성은 기존 port 가 진다.
        plan, _vdr = input_port.resolve(materialization_input)

        # pin 1b — 이 Work 의 Plan 인가(다른 Work 의 Plan 으로 이 fence 아래 실행 금지).
        basis = plan.execution_basis
        if (
            basis.work_authority_id != work_authority_id
            or basis.workspace_instance_id != workspace_instance_id
        ):
            raise MaterializationProcurementError(
                f"Plan 의 Work identity ({basis.workspace_instance_id!r}, "
                f"{basis.work_authority_id!r}) 가 start 요청과 불일치"
            )

        # pin 2 — current basis: 봉인 이후 authority 가 움직였으면 시작하지 않는다.
        current = current_basis_digest_reader()
        if current is None:
            return StartMaterializationRefusal(
                CURRENT_BASIS_NOT_SEALABLE,
                "current Work 의 execution basis 를 관찰할 수 없다 — 시작하지 않는다",
            )
        pinned = execution_basis_digest(basis)
        if current != pinned:
            return StartMaterializationRefusal(
                DIGEST_MISMATCH,
                f"current basis {current} 가 Plan 의 basis {pinned} 와 불일치(stale Plan)",
            )

        # pin 3 — runtime admission: query 는 Plan 에서 파생된다(caller 위조 불가).
        admission = evaluate_managed_run_admission(
            runtime_registry=runtime_registry,
            sealed_execution_plan=plan,
            runtime_capability_manifest_digest=runtime_capability_manifest_digest,
        )
        if not admission.materialization_startable:
            return StartMaterializationRefusal(
                admission.status,
                "runtime materializer conformance 가 admit 되지 않았다 — 시작하지 않는다",
            )

    # <fences released> — 긴 bytes 작업은 다른 Work 명령을 막지 않는다.
    return runner.materialize(materialization_input)


__all__ = [
    "CurrentBasisDigestReader",
    "MaterializationRunnerPort",
    "StartMaterializationRefusal",
    "StartMaterializationResult",
    "start_materialization",
]
