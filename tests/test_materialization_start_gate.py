"""S6-02(#810) ordered start gate — fence 아래 pin, 풀린 뒤 LongMaterialization.

S6_START_GATE_LOCK_ORDER 의 실구현을 잰다: (1) pin 넷(Plan·VDR·dependency / Work identity /
current basis / runtime admission)이 실제 fence 를 쥔 채 선다는 것(잠금 원장 관찰), (2) 긴
materialization 은 fence 가 풀린 뒤 돈다는 것, (3) 어느 거절 갈래도 러너에 진입하지 않고
기존 어휘를 재진술한다는 것.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from hwpxfiller.application.execution_contract_set import (
    execution_basis_digest,
    plan_semantic_digest,
)
from hwpxfiller.application.generation_delivery import (
    MANAGED_RUN_CONSTRUCTION_ONLY,
    MaterializationInput,
    MaterializationInputPort,
)
from hwpxfiller.application.execution_composition import (
    RuntimeMaterializerConformanceRegistry,
)
from hwpxfiller.application.record_validation import ImmutableVdrStore
from hwpxfiller.application.stored_execution_plan import (
    CURRENT_BASIS_NOT_SEALABLE,
    DIGEST_MISMATCH,
)
from hwpxfiller.external.materialization_runner import (
    MaterializationProcurementError,
    MaterializedDocumentBytes,
    ProductionMaterializationRunner,
)
from hwpxfiller.external.materialization_start_gate import (
    StartMaterializationRefusal,
    start_materialization,
)
from hwpxfiller.external.runtime_capability import admitted_runtime_conformance_registry
from hwpxfiller.host import per_work_fence
from hwpxfiller.host.per_work_fence import WORK_FENCE_RANK, per_work_mutation_fence

from tests._materialization_case import WORK, WS, Case, _build_case, _one_of_two


# ─── 조립 helper ──────────────────────────────────────────────────────────────────────
class _Kit:
    """case 하나로 gate 호출에 필요한 모든 seam 을 세운다(실 fence + 실 러너 + 실 registry)."""

    def __init__(self, case: Case):
        self.case = case
        vdr_store = ImmutableVdrStore()
        self.vdr_ref = vdr_store.put(case.vdr)
        self.plan_ref = plan_semantic_digest(case.plan)
        self.input_port = MaterializationInputPort(
            plan_resolver={self.plan_ref: case.plan}.__getitem__, vdr_store=vdr_store
        )
        self.runner = ProductionMaterializationRunner(
            input_port=self.input_port,
            candidate_blob_resolver=lambda digest: case.bytes,
            structure_resolver=lambda plan: case.structure,
        )
        self.registry, self.manifest = admitted_runtime_conformance_registry()
        self.current_basis = execution_basis_digest(case.plan.execution_basis)
        # 잠금 원장 관찰: pin 시점(reader)과 러너 진입 시점의 보유 rank 를 기록한다.
        self.reader_ranks: "list[int] | None" = None
        self.runner_ranks: "list[int] | None" = None

    def reader(self) -> "str | None":
        self.reader_ranks = list(per_work_fence._held.ranks)
        return self.current_basis

    def observing_runner(self):
        kit = self

        class _Runner:
            def materialize(self, materialization_input):
                kit.runner_ranks = list(per_work_fence._held.ranks)
                return kit.runner.materialize(materialization_input)

        return _Runner()

    def start(self, **over):
        kw = dict(
            workspace_instance_id=WS,
            work_authority_id=WORK,
            materialization_input=MaterializationInput(
                sealed_execution_plan_ref=self.plan_ref,
                validated_record_ref=self.vdr_ref,
            ),
            input_port=self.input_port,
            runner=self.observing_runner(),
            runtime_registry=self.registry,
            runtime_capability_manifest_digest=(
                self.manifest.runtime_capability_manifest_digest
            ),
            current_basis_digest_reader=self.reader,
        )
        kw.update(over)
        return start_materialization(**kw)


# ═══ 양성 — lock order 그대로 완주한다 ═══════════════════════════════════════════════
def test_admitted_current_plan_materializes_after_fence_release() -> None:
    kit = _Kit(_build_case(_one_of_two()))
    outcome = kit.start()
    assert isinstance(outcome, MaterializedDocumentBytes), outcome
    # pin 은 실제 PerWorkMutationFence 를 쥔 채 섰고(rank 원장에 WORK_FENCE_RANK),
    assert kit.reader_ranks == [WORK_FENCE_RANK]
    # LongMaterialization 은 fence 가 전부 풀린 뒤 돌았다(<fences released>).
    assert kit.runner_ranks == []


def test_default_fence_is_the_production_per_work_fence() -> None:
    import inspect

    signature = inspect.signature(start_materialization)
    assert signature.parameters["work_fence"].default is per_work_mutation_fence


# ═══ 거절 갈래 — 러너 미진입 + 기존 어휘 재진술 ═══════════════════════════════════════
def test_unobservable_current_basis_refuses_without_starting() -> None:
    kit = _Kit(_build_case(_one_of_two()))
    outcome = kit.start(current_basis_digest_reader=lambda: None)
    assert isinstance(outcome, StartMaterializationRefusal)
    assert outcome.code == CURRENT_BASIS_NOT_SEALABLE
    assert kit.runner_ranks is None  # 러너 미진입


def test_stale_plan_refuses_with_digest_mismatch() -> None:
    kit = _Kit(_build_case(_one_of_two()))
    outcome = kit.start(current_basis_digest_reader=lambda: "sha256:" + "f" * 64)
    assert isinstance(outcome, StartMaterializationRefusal)
    assert outcome.code == DIGEST_MISMATCH
    assert kit.runner_ranks is None


def test_unadmitted_runtime_refuses_with_admission_status() -> None:
    kit = _Kit(_build_case(_one_of_two()))
    outcome = kit.start(runtime_registry=RuntimeMaterializerConformanceRegistry())
    assert isinstance(outcome, StartMaterializationRefusal)
    assert outcome.code == MANAGED_RUN_CONSTRUCTION_ONLY  # 상태 문자열 재진술(새 어휘 0)
    assert kit.runner_ranks is None


def test_foreign_work_identity_fails_closed() -> None:
    kit = _Kit(_build_case(_one_of_two()))
    with pytest.raises(MaterializationProcurementError):
        kit.start(work_authority_id="work-other")
    assert kit.runner_ranks is None


def test_resolve_failure_under_fence_releases_the_fence() -> None:
    # pin 중 예외가 나도 fence 는 풀린다 — 같은 키를 즉시 다시 잡을 수 있다(데드락 0).
    kit = _Kit(_build_case(_one_of_two()))
    with pytest.raises(KeyError):
        kit.start(
            materialization_input=MaterializationInput(
                sealed_execution_plan_ref="sha256:" + "0" * 64,
                validated_record_ref=kit.vdr_ref,
            )
        )
    with per_work_mutation_fence(WS, WORK):
        pass  # 재획득 성공 = 원장이 되감겼다


def test_refusal_paths_leave_no_partial_output() -> None:
    # 거절 갈래는 bytes 산출이 없다(부분 산출물 금지의 gate 층 얼굴).
    kit = _Kit(_build_case(_one_of_two()))
    refusal = kit.start(current_basis_digest_reader=lambda: None)
    assert not hasattr(refusal, "output_bytes")
