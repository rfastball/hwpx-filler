"""S5-11(#707) SealExecutionPlan Product API — command outcome + current Sealed Plan 관찰.

S5F R2-04b-1(#740): historical durable Plan lookup·opaque Plan ref/HMAC·resolve_plan_reference·
PublishedPlanObservation·digest-vs-stored currentness(CURRENT/STALE)·command_replayed 를 제거했다.
observation 은 store 의 과거 Plan 이 아니라 current authority 에서 SealedExecutionPlanValue 를 직접
재계산한다(value 가 곧 현재라 currentness 축이 없다). command_outcome 의 StaleExecutionBasis(capture→
final gate concurrency)와 ProfileFence·runtime admission 은 유지한다. content-addressed Plan store 로의
publish(create/reuse)는 orchestration 이 아직 진다(04b-2 대상).

seal seam(capture/summary/shipping)은 seal runner 테스트의 fake World/Resolver 를 재사용한다.
plan store·admission store 는 실 primitive 로 돌린다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.application.execution_capture import (
    CapturedExecutionPolicyBlock,
    CapturedFieldBinding,
    CapturedSelection,
    DomainBlockedSelection,
    ExecutionCaptureContextError,
)
from hwpxfiller.application.execution_capture import (
    QUALIFICATION_PROFILE_REVOKED as CAP_PROFILE_REVOKED,
)
from hwpxfiller.application.execution_compilation import SLOT_CONFIGURATION_INCOMPLETE
from hwpxfiller.application.execution_semantic_kernel import SealedExecutionPlanValue
from hwpxfiller.application.fresh_execution_observation import (
    ADMISSION_CONTEXT_ERROR,
    ADMITTED,
    DOMAIN_BLOCKED,
    MATERIALIZATION_CONTRACT_NOT_ADMITTED,
    MATERIALIZER_ADMITTED,
    MATERIALIZER_CONTEXT_ERROR,
    NOT_ADMITTED,
    NOT_READY,
    POLICY_BLOCKED,
    QUALIFICATION_PROFILE_ADMISSION_STATE_MISSING,
    QUALIFICATION_PROFILE_REVOKED,
    READY,
    RUNTIME_CAPABILITY_CONTEXT_ERROR,
    SEALABILITY_CONTEXT_ERROR,
    CurrentSealedPlanObservation,
    CurrentWorkExecutionObservation,
    ExecutionObservationContextError,
    RuntimeAdmissionFacts,
    decide_runtime_policy_admission,
)
from hwpxfiller.application.seal_execution_plan import AuthorizationError, RouteResolutionError
from hwpxfiller.application.stored_profile_admission import (
    AdmissionIdempotencyRecord,
    AdmissionOutcome,
    bootstrap_stored,
    commit_next,
)
from hwpxfiller.domain.qualification_profile_admission import (
    ADMITTED as DEC_ADMITTED,
    REVOKED as DEC_REVOKED,
    AdmissionDecision,
    ProfileAdmissionStateMissing,
    decision_ref,
)
from hwpxfiller.external.profile_admission_runner import (
    read_qualification_profile_admission_under_fence,
)
from hwpxfiller.external.profile_admission_store import ProfileAdmissionStore
from hwpxfiller.external.work_execution_plan_store import WorkExecutionPlanStore
from hwpxfiller.webapp.seal_execution_plan_product import (
    EXECUTION_OBSERVATION_CONTEXT_ERROR,
    ExecutionPolicyBlockedProductOutcome,
    ExecutionQualificationBlockedProductOutcome,
    PlanPublishedProductOutcome,
    RuntimeMaterializerConformance,
    SealExecutionPlanProduct,
    SealExecutionPlanProductCommand,
    StaleExecutionBasisProductOutcome,
    s6_absent_runtime_conformance,
)

from tests.test_execution_compilation import (
    APP,
    AT,
    PROFILE,
    WORK,
    WS,
    _binding,
    _rules,
    _snapshot,
    _structure,
)
from tests.test_seal_orchestration_runner import Resolver, World


def _revoked_block() -> CapturedExecutionPolicyBlock:
    return CapturedExecutionPolicyBlock(
        policy_code=CAP_PROFILE_REVOKED, observed_at=AT, qualification_profile_id=PROFILE,
        observed_policy_version="2", policy_observation_digest="sha256:pol",
    )


# ─── admission seed helpers ────────────────────────────────────────────────────────────
def _seed_admitted(store: ProfileAdmissionStore, profile_id: str = PROFILE) -> None:
    dec = AdmissionDecision(1, DEC_ADMITTED, decision_ref(profile_id, 1), "seed1", None, "t0")
    rec = AdmissionIdempotencyRecord(
        "seed1", "fp1", AdmissionOutcome("INIT", 1, DEC_ADMITTED, dec.decision_ref), "t0"
    )
    store.create(
        bootstrap_stored(
            qualification_profile_id=profile_id,
            bound_manifest_digest="sha256:m",
            decision=dec,
            record=rec,
        )
    )


def _revoke(store: ProfileAdmissionStore, profile_id: str = PROFILE) -> None:
    stored = store.load(profile_id)
    v = stored.decisions[-1].policy_version + 1
    dec = AdmissionDecision(v, DEC_REVOKED, decision_ref(profile_id, v), f"rev{v}", "why", "t1")
    rec = AdmissionIdempotencyRecord(
        f"rev{v}", f"fp{v}", AdmissionOutcome("REVOKED", v, DEC_REVOKED, dec.decision_ref), "t1"
    )
    store.commit(profile_id, stored.aggregate_version, commit_next(stored, new_decision=dec, record=rec))


def _admission_port(store: ProfileAdmissionStore):
    """ProfileFence 를 보유한 Product 가 부르는 admission-state 읽기 port(state missing → None)."""

    def read(profile_id: str) -> "str | None":
        try:
            return read_qualification_profile_admission_under_fence(store, profile_id).state
        except ProfileAdmissionStateMissing:
            return None

    return read


def _admitting_runtime(**_kw) -> RuntimeMaterializerConformance:
    return RuntimeMaterializerConformance(MATERIALIZER_ADMITTED, True, True, "sha256:manifest")


def _ctx_error_runtime(**_kw) -> RuntimeMaterializerConformance:
    return RuntimeMaterializerConformance(MATERIALIZER_CONTEXT_ERROR, True, True, None)


# ─── product harness ───────────────────────────────────────────────────────────────────
class _Harness:
    def __init__(self, product, plan_store, admission_store, world):
        self.product = product
        self.plan_store = plan_store
        self.admission_store = admission_store
        self.world = world


def _product(
    tmp_path, world=None, *, resolver=None, authorize=None, route=None, runtime=None,
    clock=None, seed_admission=True, admission_store=None,
) -> _Harness:
    world = world or World()
    plan_store = WorkExecutionPlanStore(tmp_path / "plans")
    adm = admission_store or ProfileAdmissionStore(tmp_path / "adm")
    if seed_admission and not adm.exists(PROFILE):
        _seed_admitted(adm)
    product = SealExecutionPlanProduct(
        plan_store=plan_store,
        read_admission_state=_admission_port(adm),
        resolve_route=route or (lambda ws, ref: WORK),
        authorize=authorize or (lambda wid, ws: None),
        read_summary=world.summary,
        capture_under_fence=world.capture,
        resolve_shipping_policy=resolver or Resolver(),
        clock=clock or (lambda: "t0"),
        runtime_conformance=runtime or s6_absent_runtime_conformance,
    )
    return _Harness(product, plan_store, adm, world)


def _pcmd(request_id="r1", **over) -> SealExecutionPlanProductCommand:
    return SealExecutionPlanProductCommand(
        workspace_instance_id=WS, work_ref="job-ref", request_id=request_id, **over
    )


# ══ command outcome ════════════════════════════════════════════════════════════════════
def test_blocked_and_stale_outcomes_carry_no_plan_ref(tmp_path) -> None:
    world = World(selection=DomainBlockedSelection(SLOT_CONFIGURATION_INCOMPLETE, "미완"))
    h = _product(tmp_path, world)
    blocked = h.product.seal_execution_plan(_pcmd("r1")).command_outcome
    assert not hasattr(blocked, "opaque_plan_ref")
    assert not hasattr(blocked, "plan_semantic_digest")


def test_revoked_profile_leaves_plan_semantic_digest_unchanged(tmp_path) -> None:
    h = _product(tmp_path)
    before = h.product.seal_execution_plan(_pcmd("r1")).command_outcome
    _revoke(h.admission_store)
    after = h.product.seal_execution_plan(_pcmd("r1")).command_outcome
    assert isinstance(before, PlanPublishedProductOutcome)
    assert isinstance(after, PlanPublishedProductOutcome)
    assert before.plan_semantic_digest == after.plan_semantic_digest


def test_no_current_plan_pointer_stored(tmp_path) -> None:
    h = _product(tmp_path)
    h.product.seal_execution_plan(_pcmd("r1"))
    aggregate = h.plan_store.load(WORK)
    for forbidden in ("current_plan_id", "is_current", "latest", "current_plan"):
        assert not hasattr(aggregate, forbidden)


# ══ current Sealed Plan observation ════════════════════════════════════════════════════
def test_current_sealable_returns_recomputed_plan_value(tmp_path) -> None:
    h = _product(tmp_path, runtime=_admitting_runtime)
    resp = h.product.seal_execution_plan(_pcmd("r1"))
    obs = resp.fresh_observation
    assert isinstance(obs, CurrentSealedPlanObservation)
    assert isinstance(obs.sealed_plan_value, SealedExecutionPlanValue)


def test_observation_returns_recomputed_current_value_not_a_stored_one(tmp_path) -> None:
    # observation 은 store 의 first-seen Plan 을 되읽지 않고 current authority 를 재계산한다:
    # 실 selection 을 바꾸면 관찰된 value 도 바뀐다(같은 저장 Plan 을 replay 하지 않는다).
    h = _product(tmp_path, runtime=_admitting_runtime)
    a = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(a, CurrentSealedPlanObservation)
    h.world._sel = CapturedSelection(_snapshot(h.world.structure, selected="o2", app=APP))
    b = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(b, CurrentSealedPlanObservation)
    assert b.sealed_plan_value != a.sealed_plan_value  # 재계산 — 저장본 replay 가 아니다


def test_s6_absent_current_not_admitted_not_ready(tmp_path) -> None:
    h = _product(tmp_path)  # 기본 = s6_absent_runtime_conformance, profile ADMITTED
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, CurrentSealedPlanObservation)
    assert obs.runtime_policy_admission.state == NOT_ADMITTED
    assert obs.runtime_policy_admission.reasons == (MATERIALIZATION_CONTRACT_NOT_ADMITTED,)
    assert obs.materialization_readiness == NOT_READY


def test_runtime_admitted_ready(tmp_path) -> None:
    h = _product(tmp_path, runtime=_admitting_runtime)
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, CurrentSealedPlanObservation)
    assert obs.runtime_policy_admission.state == ADMITTED
    assert obs.materialization_readiness == READY


def test_profile_state_missing_is_admission_context_error(tmp_path) -> None:
    h = _product(tmp_path, seed_admission=False, runtime=_admitting_runtime)
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, CurrentSealedPlanObservation)
    assert obs.runtime_policy_admission.state == ADMISSION_CONTEXT_ERROR
    assert QUALIFICATION_PROFILE_ADMISSION_STATE_MISSING in obs.runtime_policy_admission.reasons


def test_runtime_capability_context_error(tmp_path) -> None:
    h = _product(tmp_path, runtime=_ctx_error_runtime)
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, CurrentSealedPlanObservation)
    assert obs.runtime_policy_admission.state == ADMISSION_CONTEXT_ERROR
    assert RUNTIME_CAPABILITY_CONTEXT_ERROR in obs.runtime_policy_admission.reasons


def test_current_policy_blocked_is_current_work_observation(tmp_path) -> None:
    h = _product(tmp_path, runtime=_admitting_runtime)
    h.product.seal_execution_plan(_pcmd("r1"))
    h.world.policy_block = _revoked_block()  # 관찰 시점 current 가 policy block
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, CurrentWorkExecutionObservation)
    assert obs.current_sealability == POLICY_BLOCKED
    assert obs.normalized_blockers_or_policy == (CAP_PROFILE_REVOKED,)


def test_current_blocked_candidate_is_current_work_observation(tmp_path) -> None:
    h = _product(tmp_path, runtime=_admitting_runtime)
    h.product.seal_execution_plan(_pcmd("r1"))
    # current binding 에서 active field 하나를 떨어뜨려 current 가 seal 불가(BlockedCandidate).
    h.world._bind = CapturedFieldBinding(
        _binding(h.world.structure, app=APP, rules=_rules(drop=("성명",)))
    )
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, CurrentWorkExecutionObservation)
    assert obs.current_sealability == DOMAIN_BLOCKED
    assert obs.normalized_blockers_or_policy  # nonempty


def test_current_capture_context_error_is_current_work_observation(tmp_path) -> None:
    # command 은 gate+final capture(1,2)로 정상 봉인하고, 관찰 시점 capture(3)만 context error 로
    # 만들어 sealability CONTEXT_ERROR 를 낸다(_capture 는 command·observation 이 공유하므로, command
    # 자신의 capture 를 error 로 만들면 봉인이 loud attempt error 로 먼저 닫힌다 — fail-closed).
    h = _product(tmp_path, runtime=_admitting_runtime)
    real = h.world.capture
    state = {"n": 0}

    def gated(*a, **k):
        state["n"] += 1
        if state["n"] >= 3:  # 3번째부터 = observation capture
            return ExecutionCaptureContextError("SELECTION_CONTRACT_INTEGRITY_ERROR", "복원 불가")
        return real(*a, **k)

    h.product._capture = gated
    resp = h.product.seal_execution_plan(_pcmd("r1"))
    assert isinstance(resp.command_outcome, PlanPublishedProductOutcome)  # command 은 정상 봉인
    assert state["n"] == 3  # gate+final(2) 정상, observation(1) context error
    obs = resp.fresh_observation
    assert isinstance(obs, CurrentWorkExecutionObservation)
    assert obs.current_sealability == SEALABILITY_CONTEXT_ERROR


# ══ current-work observation on stale command outcome ══════════════════════════════════
def _stale_world() -> World:
    world = World()

    def mutate(w):
        w._sel = CapturedSelection(_snapshot(w.structure, selected="o2", app=w.app))

    world.on_after_capture_gate = mutate
    return world


def test_stale_command_then_current_work_policy_blocked(tmp_path) -> None:
    h = _product(tmp_path, _stale_world())
    first = h.product.seal_execution_plan(_pcmd("r1"))
    assert isinstance(first.command_outcome, StaleExecutionBasisProductOutcome)
    h.world.policy_block = _revoked_block()
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, CurrentWorkExecutionObservation)
    assert obs.current_sealability == POLICY_BLOCKED
    assert obs.normalized_blockers_or_policy == (CAP_PROFILE_REVOKED,)


def test_stale_command_then_current_work_domain_blocked(tmp_path) -> None:
    h = _product(tmp_path, _stale_world())
    h.product.seal_execution_plan(_pcmd("r1"))
    h.world._bind = CapturedFieldBinding(
        _binding(h.world.structure, app=APP, rules=_rules(drop=("성명",)))
    )
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, CurrentWorkExecutionObservation)
    assert obs.current_sealability == DOMAIN_BLOCKED
    assert obs.normalized_blockers_or_policy  # nonempty


# ══ authorization / API ════════════════════════════════════════════════════════════════
def test_authorization_repeated_each_call(tmp_path) -> None:
    h = _product(tmp_path)
    h.product.seal_execution_plan(_pcmd("r1"))
    calls = {"n": 0}

    def deny(wid, ws):
        calls["n"] += 1
        raise AuthorizationError("denied")

    other = SealExecutionPlanProduct(
        plan_store=h.plan_store, read_admission_state=_admission_port(h.admission_store),
        resolve_route=lambda ws, r: WORK, authorize=deny,
        read_summary=h.world.summary, capture_under_fence=h.world.capture,
        resolve_shipping_policy=Resolver(), clock=lambda: "t0",
    )
    with pytest.raises(AuthorizationError):
        other.seal_execution_plan(_pcmd("r1"))
    assert calls["n"] == 1  # 매 호출 authorize 를 다시 확인(replay 없음)


def test_route_failure_no_ledger_mutation(tmp_path) -> None:
    def boom(ws, ref):
        raise RouteResolutionError("route 불가")

    h = _product(tmp_path, route=boom)
    with pytest.raises(RouteResolutionError):
        h.product.seal_execution_plan(_pcmd("r1"))
    assert not h.plan_store.exists(WORK)


def test_product_reaches_real_s5_10_service_and_persists(tmp_path) -> None:
    h = _product(tmp_path)
    h.product.seal_execution_plan(_pcmd("r1"))
    aggregate = h.plan_store.load(WORK)  # 실 store 에 durable 하게 남는다(content-addressed)
    assert len(aggregate.plans_by_semantic_digest) == 1
    assert not hasattr(aggregate, "first_seen_ledger")  # R2-04a: ledger 제거


def test_product_contract_vocabulary_is_closed() -> None:
    # 노출 어휘가 닫힌 집합이다 — opaque ref code 는 사라지고 관찰 강등 code 만 남는다.
    import hwpxfiller.webapp.seal_execution_plan_product as mod

    assert isinstance(EXECUTION_OBSERVATION_CONTEXT_ERROR, str)
    for gone in ("PLAN_REFERENCE_INVALID", "PLAN_REFERENCE_UNRESOLVABLE",
                 "resolve_plan_reference"):
        assert not hasattr(mod, gone)


# ══ lock order ═════════════════════════════════════════════════════════════════════════
def test_fresh_observation_profile_then_work_no_reverse(tmp_path) -> None:
    h = _product(tmp_path)
    h.product.seal_execution_plan(_pcmd("r1"))
    # seal(gate·final) + fresh observation 의 모든 capture 는 ProfileFence(0)→WorkFence(1) 아래.
    assert h.world.capture_ranks  # 최소 한 번은 capture
    assert all(ranks == [0, 1] for ranks in h.world.capture_ranks)


def test_fresh_observation_no_store_write(tmp_path) -> None:
    h = _product(tmp_path)
    h.product.seal_execution_plan(_pcmd("r1"))
    version_after_seal = h.plan_store.load(WORK).aggregate_version
    h.product.seal_execution_plan(_pcmd("r1"))  # 재호출 + fresh observe
    assert h.plan_store.load(WORK).aggregate_version == version_after_seal


# ══ Codex #723 finding 2: observation-only port 실패는 command outcome 을 소거하지 않는다 ═══
def test_observation_port_failure_degrades_keeps_command_outcome(tmp_path) -> None:
    h = _product(tmp_path, runtime=_admitting_runtime)
    h.product.seal_execution_plan(_pcmd("r1"))

    def boom(_pid):
        raise RuntimeError("corrupt profile-admission read")

    h.product._read_admission = boom
    resp = h.product.seal_execution_plan(_pcmd("r1"))  # 재봉인 + observe
    assert isinstance(resp.command_outcome, PlanPublishedProductOutcome)  # 보존
    assert isinstance(resp.fresh_observation, ExecutionObservationContextError)
    assert resp.fresh_observation.code == EXECUTION_OBSERVATION_CONTEXT_ERROR


# ══ pure decision units ════════════════════════════════════════════════════════════════
def test_decide_admission_all_not_admitted_reasons_accumulate() -> None:
    facts = RuntimeAdmissionFacts(
        profile_admission_state="REVOKED",
        execution_base_kind_admitted=False,
        plan_schema_supported_by_runtime=False,
        canonical_encoding_supported_by_runtime=False,
        materializer_conformance="NOT_ADMITTED",
    )
    verdict = decide_runtime_policy_admission(facts)
    assert verdict.state == NOT_ADMITTED
    assert QUALIFICATION_PROFILE_REVOKED in verdict.reasons
    assert MATERIALIZATION_CONTRACT_NOT_ADMITTED in verdict.reasons


def test_decide_admission_all_pass_admitted() -> None:
    facts = RuntimeAdmissionFacts(ADMITTED, True, True, True, MATERIALIZER_ADMITTED)
    assert decide_runtime_policy_admission(facts).state == ADMITTED


def test_command_rejects_empty_fields() -> None:
    with pytest.raises(ValueError):
        SealExecutionPlanProductCommand(workspace_instance_id="", work_ref="r", request_id="r")
