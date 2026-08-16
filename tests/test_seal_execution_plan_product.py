"""S5-11(#707) SealExecutionPlan Product API — historical outcome + fresh observation 분리.

체크리스트(issue #707): historical/fresh split(published-then-stale/revoked replay·blocked/stale
replay·observation context error preserves outcome·blocked/stale no arbitrary Plan ref) ·
currentness/admission(exact basis CURRENT·detached CURRENT·app change STALE·no current pointer·
S6 absent CURRENT+NOT_ADMITTED+NOT_READY·runtime admitted READY only with CURRENT·revoked profile
digest unchanged) · opaque ref(restart verify·tamper reject·route/Work cross-check·two-Work
cross-Work reject·digest identity·token not in fingerprint·no random ID) · authorization/API
(auth repeated on replay·route failure no ledger mutation·unknown fail-closed·reaches S5-10) ·
lock order(ProfileFence→WorkFence·no reverse·no store write).

seal seam(capture/summary/shipping)은 seal runner 테스트의 fake World/Resolver 를 재사용한다.
plan store·admission store·HMAC secret 은 실 primitive 로 돌린다.
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
from hwpxfiller.application.execution_plan_reference import (
    PLAN_REF_PURPOSE,
    PLAN_REF_SCHEMA_VERSION,
    OpaquePlanReferenceClaims,
    open_plan_reference,
    sign_plan_reference,
)
from hwpxfiller.application.fresh_execution_observation import (
    ADMISSION_CONTEXT_ERROR,
    ADMITTED,
    CURRENT,
    CURRENT_BASIS_NOT_SEALABLE,
    CURRENTNESS_CONTEXT_ERROR,
    DIGEST_MISMATCH,
    MATERIALIZATION_CONTRACT_NOT_ADMITTED,
    MATERIALIZER_ADMITTED,
    MATERIALIZER_CONTEXT_ERROR,
    NOT_ADMITTED,
    NOT_READY,
    QUALIFICATION_PROFILE_ADMISSION_STATE_MISSING,
    QUALIFICATION_PROFILE_REVOKED,
    READY,
    RUNTIME_CAPABILITY_CONTEXT_ERROR,
    SEALABLE,
    STALE,
    TEMPLATE_APPLICATION_CHANGED,
    CurrentWorkExecutionObservation,
    ExecutionObservationContextError,
    PublishedPlanObservation,
    RuntimeAdmissionFacts,
    decide_runtime_policy_admission,
)
from hwpxfiller.application.seal_execution_plan import AuthorizationError, RouteResolutionError
from hwpxfiller.application.stored_profile_admission import (
    STORE_SCHEMA_VERSION,
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
from hwpxfiller.application.stored_execution_plan import ExecutionPlanStoreIntegrityError
from hwpxfiller.external.profile_admission_store import ProfileAdmissionStore
from hwpxfiller.external.slot_token_secret import SlotTokenSecretError, SlotTokenSecretStore
from hwpxfiller.external.work_execution_plan_store import WorkExecutionPlanStore
from hwpxfiller.webapp.seal_execution_plan_product import (
    ExecutionPolicyBlockedProductOutcome,
    ExecutionQualificationBlockedProductOutcome,
    PlanPublishedProductOutcome,
    RuntimeMaterializerConformance,
    SealExecutionPlanProduct,
    SealExecutionPlanProductCommand,
    SealExecutionPlanProductError,
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

WORK2 = "work-2"
SECRET = b"\x11" * 32


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
    load_secret=None, clock=None, seed_admission=True, admission_store=None,
) -> _Harness:
    world = world or World()
    plan_store = WorkExecutionPlanStore(tmp_path / "plans")
    adm = admission_store or ProfileAdmissionStore(tmp_path / "adm")
    if seed_admission and not adm.exists(PROFILE):
        _seed_admitted(adm)
    product = SealExecutionPlanProduct(
        plan_store=plan_store,
        read_admission_state=_admission_port(adm),
        load_secret=load_secret or (lambda: SECRET),
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


# ══ historical/fresh split ═════════════════════════════════════════════════════════════
def test_published_then_stale_replay_keeps_published(tmp_path) -> None:
    h = _product(tmp_path)
    first = h.product.seal_execution_plan(_pcmd("r1"))
    assert isinstance(first.command_outcome, PlanPublishedProductOutcome)
    # 현재 Work 의 Application 이 바뀌어 Plan 이 stale 해진다.
    h.world.app = "app-2"
    replay = h.product.seal_execution_plan(_pcmd("r1"))
    assert replay.command_replayed is True
    # historical 은 그대로 PlanPublished, fresh 는 STALE 로 recompute.
    assert isinstance(replay.command_outcome, PlanPublishedProductOutcome)
    assert replay.command_outcome.plan_semantic_digest == first.command_outcome.plan_semantic_digest
    assert isinstance(replay.fresh_observation, PublishedPlanObservation)
    assert replay.fresh_observation.semantic_currentness.state == STALE
    assert replay.fresh_observation.semantic_currentness.reason == TEMPLATE_APPLICATION_CHANGED


def test_published_then_revoked_replay_keeps_success_not_admitted(tmp_path) -> None:
    h = _product(tmp_path, runtime=_admitting_runtime)
    h.product.seal_execution_plan(_pcmd("r1"))
    _revoke(h.admission_store)
    replay = h.product.seal_execution_plan(_pcmd("r1"))
    assert isinstance(replay.command_outcome, PlanPublishedProductOutcome)
    obs = replay.fresh_observation
    assert isinstance(obs, PublishedPlanObservation)
    assert obs.semantic_currentness.state == CURRENT  # basis 는 그대로 current
    assert obs.runtime_policy_admission.state == NOT_ADMITTED
    assert QUALIFICATION_PROFILE_REVOKED in obs.runtime_policy_admission.reasons
    assert obs.materialization_readiness == NOT_READY


def test_blocked_replay_after_work_fixed_keeps_blocked_fresh_sealable(tmp_path) -> None:
    world = World(selection=DomainBlockedSelection(SLOT_CONFIGURATION_INCOMPLETE, "미완"))
    h = _product(tmp_path, world)
    first = h.product.seal_execution_plan(_pcmd("r1"))
    assert isinstance(first.command_outcome, ExecutionQualificationBlockedProductOutcome)
    # Work 를 고친다(선택 완성) → fresh 는 SEALABLE, historical 은 여전히 blocked.
    h.world._sel = None
    replay = h.product.seal_execution_plan(_pcmd("r1"))
    assert isinstance(replay.command_outcome, ExecutionQualificationBlockedProductOutcome)
    obs = replay.fresh_observation
    assert isinstance(obs, CurrentWorkExecutionObservation)
    assert obs.current_sealability == SEALABLE


def test_stale_replay_after_work_changed_keeps_stale(tmp_path) -> None:
    world = World()

    def mutate(w):
        w._sel = CapturedSelection(_snapshot(w.structure, selected="o2", app=w.app))

    world.on_after_capture_gate = mutate
    h = _product(tmp_path, world)
    first = h.product.seal_execution_plan(_pcmd("r1"))
    assert isinstance(first.command_outcome, StaleExecutionBasisProductOutcome)
    replay = h.product.seal_execution_plan(_pcmd("r1"))
    assert isinstance(replay.command_outcome, StaleExecutionBasisProductOutcome)
    assert isinstance(replay.fresh_observation, CurrentWorkExecutionObservation)


def test_fresh_observation_context_error_preserves_outcome(tmp_path) -> None:
    h = _product(tmp_path)
    h.product.seal_execution_plan(_pcmd("r1"))
    # replay 는 ledger 에서 즉시 반환하므로 이후 관찰만 alternate 로 영영 mismatch → context error.
    h.world.alternate = True
    replay = h.product.seal_execution_plan(_pcmd("r1"))
    assert isinstance(replay.command_outcome, PlanPublishedProductOutcome)  # 보존
    assert isinstance(replay.fresh_observation, ExecutionObservationContextError)


def test_blocked_and_stale_outcomes_carry_no_plan_ref(tmp_path) -> None:
    world = World(selection=DomainBlockedSelection(SLOT_CONFIGURATION_INCOMPLETE, "미완"))
    h = _product(tmp_path, world)
    blocked = h.product.seal_execution_plan(_pcmd("r1")).command_outcome
    assert not hasattr(blocked, "opaque_plan_ref")
    assert not hasattr(blocked, "plan_semantic_digest")


# ══ currentness / admission ════════════════════════════════════════════════════════════
def test_exact_basis_equality_current(tmp_path) -> None:
    h = _product(tmp_path, runtime=_admitting_runtime)
    resp = h.product.seal_execution_plan(_pcmd("r1"))
    obs = resp.fresh_observation
    assert isinstance(obs, PublishedPlanObservation)
    assert obs.semantic_currentness.state == CURRENT
    assert obs.observed_execution_basis_digest == resp.command_outcome.execution_basis_digest


def test_detached_only_change_stays_current(tmp_path) -> None:
    from hwpxfiller.application.execution_capture import CapturedSelection

    h = _product(tmp_path, runtime=_admitting_runtime)
    h.product.seal_execution_plan(_pcmd("r1"))
    h.world._sel = CapturedSelection(_snapshot(h.world.structure, detached="o2", app=APP))
    replay = h.product.seal_execution_plan(_pcmd("r1"))
    obs = replay.fresh_observation
    assert isinstance(obs, PublishedPlanObservation)
    assert obs.semantic_currentness.state == CURRENT


def test_effective_change_same_app_is_digest_mismatch(tmp_path) -> None:
    from hwpxfiller.application.execution_capture import CapturedSelection

    h = _product(tmp_path)
    h.product.seal_execution_plan(_pcmd("r1"))
    h.world._sel = CapturedSelection(_snapshot(h.world.structure, selected="o2", app=APP))
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, PublishedPlanObservation)
    assert obs.semantic_currentness.state == STALE
    assert obs.semantic_currentness.reason == DIGEST_MISMATCH


def test_no_current_plan_pointer_stored(tmp_path) -> None:
    h = _product(tmp_path)
    h.product.seal_execution_plan(_pcmd("r1"))
    aggregate = h.plan_store.load(WORK)
    for forbidden in ("current_plan_id", "is_current", "latest", "current_plan"):
        assert not hasattr(aggregate, forbidden)


def test_s6_absent_current_not_admitted_not_ready(tmp_path) -> None:
    h = _product(tmp_path)  # 기본 = s6_absent_runtime_conformance, profile ADMITTED
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, PublishedPlanObservation)
    assert obs.semantic_currentness.state == CURRENT
    assert obs.runtime_policy_admission.state == NOT_ADMITTED
    assert obs.runtime_policy_admission.reasons == (MATERIALIZATION_CONTRACT_NOT_ADMITTED,)
    assert obs.materialization_readiness == NOT_READY


def test_runtime_admitted_ready_only_with_current(tmp_path) -> None:
    h = _product(tmp_path, runtime=_admitting_runtime)
    ready = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(ready, PublishedPlanObservation)
    assert ready.materialization_readiness == READY
    # 이제 app 을 바꿔 STALE 로 만들면 admitted 여도 READY 가 아니다.
    h.world.app = "app-2"
    stale = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(stale, PublishedPlanObservation)
    assert stale.runtime_policy_admission.state == ADMITTED
    assert stale.semantic_currentness.state == STALE
    assert stale.materialization_readiness == NOT_READY


def test_revoked_profile_leaves_plan_semantic_digest_unchanged(tmp_path) -> None:
    h = _product(tmp_path)
    before = h.product.seal_execution_plan(_pcmd("r1")).command_outcome
    _revoke(h.admission_store)
    after = h.product.seal_execution_plan(_pcmd("r1")).command_outcome
    assert isinstance(before, PlanPublishedProductOutcome)
    assert isinstance(after, PlanPublishedProductOutcome)
    assert before.plan_semantic_digest == after.plan_semantic_digest


def test_profile_state_missing_is_admission_context_error(tmp_path) -> None:
    h = _product(tmp_path, seed_admission=False, runtime=_admitting_runtime)
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, PublishedPlanObservation)
    assert obs.runtime_policy_admission.state == ADMISSION_CONTEXT_ERROR
    assert QUALIFICATION_PROFILE_ADMISSION_STATE_MISSING in obs.runtime_policy_admission.reasons


def test_runtime_capability_context_error(tmp_path) -> None:
    h = _product(tmp_path, runtime=_ctx_error_runtime)
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, PublishedPlanObservation)
    assert obs.runtime_policy_admission.state == ADMISSION_CONTEXT_ERROR
    assert RUNTIME_CAPABILITY_CONTEXT_ERROR in obs.runtime_policy_admission.reasons


# ══ opaque ref ═════════════════════════════════════════════════════════════════════════
def _publish_and_ref(tmp_path, **kw):
    root = tmp_path / "inst"
    secrets = SlotTokenSecretStore(root)
    h = _product(root / "state", load_secret=secrets.load_or_create_active_secret, **kw)
    resp = h.product.seal_execution_plan(_pcmd("r1"))
    assert isinstance(resp.command_outcome, PlanPublishedProductOutcome)
    return h, resp.command_outcome.opaque_plan_ref, resp.command_outcome.plan_semantic_digest


def test_restart_verification_with_durable_secret(tmp_path) -> None:
    root = tmp_path / "inst"
    secrets = SlotTokenSecretStore(root)
    h = _product(root / "state", load_secret=secrets.load_or_create_active_secret)
    ref = h.product.seal_execution_plan(_pcmd("r1")).command_outcome.opaque_plan_ref
    # 재시작 = 같은 root 의 새 Product/secret store. durable secret 이라 같은 secret 을 읽는다.
    secrets2 = SlotTokenSecretStore(root)
    h2 = _product(
        root / "state", load_secret=secrets2.load_or_create_active_secret,
        admission_store=h.admission_store,
    )
    resolved = h2.product.resolve_plan_reference(ref, "job-ref", WS)
    assert resolved.plan_semantic_digest


def test_ref_tamper_rejected(tmp_path) -> None:
    h, ref, _ = _publish_and_ref(tmp_path)
    tampered = ref[:-2] + ("aa" if not ref.endswith("aa") else "bb")
    with pytest.raises(SealExecutionPlanProductError) as ei:
        h.product.resolve_plan_reference(tampered, "job-ref", WS)
    assert ei.value.code == "PLAN_REFERENCE_INVALID"


def test_ref_wrong_secret_rejected(tmp_path) -> None:
    h, ref, _ = _publish_and_ref(tmp_path)
    other = SealExecutionPlanProduct(
        plan_store=h.plan_store, read_admission_state=_admission_port(h.admission_store),
        load_secret=lambda: b"\x99" * 32,
        resolve_route=lambda ws, r: WORK, authorize=lambda wid, ws: None,
        read_summary=h.world.summary, capture_under_fence=h.world.capture,
        resolve_shipping_policy=Resolver(), clock=lambda: "t0",
    )
    with pytest.raises(SealExecutionPlanProductError) as ei:
        other.resolve_plan_reference(ref, "job-ref", WS)
    assert ei.value.code == "PLAN_REFERENCE_INVALID"


def test_ref_purpose_mismatch_rejected(tmp_path) -> None:
    h, _ref, _ = _publish_and_ref(tmp_path)
    # 다른 purpose 로 서명된 ref 는 open 에서 PURPOSE_MISMATCH. sign 은 purpose 를 강제하므로
    # 직접 서명 우회 없이, open 이 강제하는 자리를 검증한다(craft 는 별도 pure 테스트에서).
    forged = _sign_wrong_purpose(SECRET)
    h2 = _product(tmp_path / "b")
    with pytest.raises(SealExecutionPlanProductError) as ei:
        h2.product.resolve_plan_reference(forged, "job-ref", WS)
    assert ei.value.code == "PLAN_REFERENCE_PURPOSE_MISMATCH"


def _sign_wrong_purpose(secret: bytes) -> str:
    # open 이 purpose 를 재확인하는 자리를 타격하려고, schema 는 맞고 purpose 만 틀린 claims 를
    # 서명한다(sign 은 purpose 를 강제하므로 canonical framing 을 직접 구성).
    from hwpxfiller.application import execution_plan_reference as ref_mod

    claims = OpaquePlanReferenceClaims(
        ref_schema_version=PLAN_REF_SCHEMA_VERSION, ref_purpose="WRONG",
        workspace_instance_id=WS, work_authority_id=WORK, plan_semantic_digest="sha256:x",
        plan_schema_version="hwpx-execution-plan/v1", canonical_encoding_version="e",
        actor_binding_digest="sha256:a", issued_at="t0",
    )
    payload = ref_mod._b64e(ref_mod._canonical(claims))
    signed = f"{ref_mod.PLAN_REF_SCHEME}.{payload}"
    import hashlib
    import hmac

    tag = hmac.new(secret, signed.encode("ascii"), hashlib.sha256).digest()
    return f"{signed}.{ref_mod._b64e(tag)}"


def test_ref_workspace_cross_check(tmp_path) -> None:
    h, ref, _ = _publish_and_ref(tmp_path)
    with pytest.raises(SealExecutionPlanProductError) as ei:
        h.product.resolve_plan_reference(ref, "job-ref", "other-ws")
    assert ei.value.code == "PLAN_REFERENCE_ROUTE_MISMATCH"


def test_ref_two_works_cross_work_rejected(tmp_path) -> None:
    # actor 가 두 Work 권한을 가져도 route Work 가 다르면 token claim Work 를 채택하지 않는다.
    route = {"job-ref": WORK, "job-ref-2": WORK2}
    h, ref, _ = _publish_and_ref(tmp_path, route=lambda ws, r: route[r])
    with pytest.raises(SealExecutionPlanProductError) as ei:
        h.product.resolve_plan_reference(ref, "job-ref-2", WS)
    assert ei.value.code == "PLAN_REFERENCE_WORK_MISMATCH"


def test_ref_unresolvable_when_plan_absent(tmp_path) -> None:
    h, _ref, _ = _publish_and_ref(tmp_path)
    forged = _sign_unknown_plan(SECRET, h)
    with pytest.raises(SealExecutionPlanProductError) as ei:
        h.product.resolve_plan_reference(forged, "job-ref", WS)
    assert ei.value.code == "PLAN_REFERENCE_UNRESOLVABLE"


def _sign_unknown_plan(secret, h) -> str:
    from hwpxfiller.application import execution_plan_reference as ref_mod

    claims = OpaquePlanReferenceClaims(
        ref_schema_version=PLAN_REF_SCHEMA_VERSION, ref_purpose=PLAN_REF_PURPOSE,
        workspace_instance_id=WS, work_authority_id=WORK,
        plan_semantic_digest="sha256:does-not-exist",
        plan_schema_version="hwpx-execution-plan/v1", canonical_encoding_version="e",
        actor_binding_digest=ref_mod.plan_reference_actor_binding_digest("local-user", WS),
        issued_at="t0",
    )
    return sign_plan_reference(claims, h.product._load_secret())


def test_ref_resolves_exact_digest_identity(tmp_path) -> None:
    h, ref, digest = _publish_and_ref(tmp_path)
    resolved = h.product.resolve_plan_reference(ref, "job-ref", WS)
    assert resolved.plan_semantic_digest == digest
    assert isinstance(resolved.fresh_observation, PublishedPlanObservation)


def test_ref_resolve_digest_survives_observation_failure(tmp_path) -> None:
    # fresh observation 실패(profile discovery 미수렴)해도 exact digest resolve 는 성공한다.
    h, ref, digest = _publish_and_ref(tmp_path)
    h.world.alternate = True
    resolved = h.product.resolve_plan_reference(ref, "job-ref", WS)
    assert resolved.plan_semantic_digest == digest
    assert isinstance(resolved.fresh_observation, ExecutionObservationContextError)


def test_ref_string_not_in_plan_or_request_identity(tmp_path) -> None:
    # issued_at 이 다른 두 ref 는 문자열이 달라도 같은 Plan digest 로 resolve 된다(ref 는 identity 밖).
    ticks = iter(["t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9"])
    h = _product(tmp_path, clock=lambda: next(ticks))
    a = h.product.seal_execution_plan(_pcmd("r1")).command_outcome
    b = h.product.seal_execution_plan(_pcmd("r2")).command_outcome  # REUSED, 다른 issued_at
    assert isinstance(a, PlanPublishedProductOutcome) and isinstance(b, PlanPublishedProductOutcome)
    assert a.opaque_plan_ref != b.opaque_plan_ref
    assert a.plan_semantic_digest == b.plan_semantic_digest  # 같은 content identity


# ══ authorization / API ════════════════════════════════════════════════════════════════
def test_authorization_repeated_on_replay(tmp_path) -> None:
    h = _product(tmp_path)
    h.product.seal_execution_plan(_pcmd("r1"))
    calls = {"n": 0}

    def deny(wid, ws):
        calls["n"] += 1
        raise AuthorizationError("denied")

    other = SealExecutionPlanProduct(
        plan_store=h.plan_store, read_admission_state=_admission_port(h.admission_store),
        load_secret=lambda: SECRET, resolve_route=lambda ws, r: WORK, authorize=deny,
        read_summary=h.world.summary, capture_under_fence=h.world.capture,
        resolve_shipping_policy=Resolver(), clock=lambda: "t0",
    )
    with pytest.raises(AuthorizationError):
        other.seal_execution_plan(_pcmd("r1"))
    assert calls["n"] == 1  # replay 에서도 authorize 를 다시 확인


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
    aggregate = h.plan_store.load(WORK)  # 실 store 에 durable 하게 남는다
    assert len(aggregate.plans_by_semantic_digest) == 1
    assert len(aggregate.first_seen_ledger) == 1


def test_product_contract_vocabulary_is_closed(tmp_path) -> None:
    # unknown result/error fail-closed: 노출 어휘가 닫힌 집합이다(TS 배선은 downstream slice).
    import hwpxfiller.webapp.seal_execution_plan_product as mod

    for name in ("PLAN_REFERENCE_INVALID", "PLAN_REFERENCE_UNRESOLVABLE",
                 "EXECUTION_OBSERVATION_CONTEXT_ERROR"):
        assert isinstance(getattr(mod, name), str)


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
    h.product.seal_execution_plan(_pcmd("r1"))  # replay + fresh observe
    assert h.plan_store.load(WORK).aggregate_version == version_after_seal


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


def test_open_ref_roundtrip_pure() -> None:
    claims = OpaquePlanReferenceClaims(
        ref_schema_version=PLAN_REF_SCHEMA_VERSION, ref_purpose=PLAN_REF_PURPOSE,
        workspace_instance_id=WS, work_authority_id=WORK, plan_semantic_digest="sha256:p",
        plan_schema_version="hwpx-execution-plan/v1", canonical_encoding_version="enc/v1",
        actor_binding_digest="sha256:a", issued_at="t0",
    )
    ref = sign_plan_reference(claims, SECRET)
    assert open_plan_reference(ref, SECRET) == claims


def test_currentness_stale_when_current_policy_blocked(tmp_path) -> None:
    h = _product(tmp_path, runtime=_admitting_runtime)
    h.product.seal_execution_plan(_pcmd("r1"))
    h.world.policy_block = _revoked_block()  # 관찰 시점 current 가 policy block
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, PublishedPlanObservation)
    assert obs.semantic_currentness.state == STALE
    assert obs.semantic_currentness.reason == CURRENT_BASIS_NOT_SEALABLE


def test_currentness_stale_when_current_blocked_candidate(tmp_path) -> None:
    h = _product(tmp_path, runtime=_admitting_runtime)
    h.product.seal_execution_plan(_pcmd("r1"))
    # current binding 에서 active field 하나를 떨어뜨려 current 가 seal 불가(BlockedCandidate).
    h.world._bind = CapturedFieldBinding(
        _binding(h.world.structure, app=APP, rules=_rules(drop=("성명",)))
    )
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, PublishedPlanObservation)
    assert obs.semantic_currentness.state == STALE
    assert obs.semantic_currentness.reason == CURRENT_BASIS_NOT_SEALABLE


def _stale_world() -> World:
    world = World()

    def mutate(w):
        w._sel = CapturedSelection(_snapshot(w.structure, selected="o2", app=w.app))

    world.on_after_capture_gate = mutate
    return world


def test_current_work_observation_policy_blocked(tmp_path) -> None:
    h = _product(tmp_path, _stale_world())
    first = h.product.seal_execution_plan(_pcmd("r1"))
    assert isinstance(first.command_outcome, StaleExecutionBasisProductOutcome)
    h.world.policy_block = _revoked_block()
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, CurrentWorkExecutionObservation)
    assert obs.current_sealability == "POLICY_BLOCKED"
    assert obs.normalized_blockers_or_policy == (CAP_PROFILE_REVOKED,)


def test_current_work_observation_domain_blocked(tmp_path) -> None:
    h = _product(tmp_path, _stale_world())
    h.product.seal_execution_plan(_pcmd("r1"))
    h.world._bind = CapturedFieldBinding(
        _binding(h.world.structure, app=APP, rules=_rules(drop=("성명",)))
    )
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, CurrentWorkExecutionObservation)
    assert obs.current_sealability == "DOMAIN_BLOCKED"
    assert obs.normalized_blockers_or_policy  # nonempty


# ══ Codex #723 findings ════════════════════════════════════════════════════════════════
def test_current_work_observation_uses_fresh_policy_not_recorded(tmp_path) -> None:
    # finding 1: 비-published fresh observation 은 durable first-seen record policy 를 재사용하지
    # 않고 CURRENT shipping policy 를 fresh resolve 한다(AUTO default 가 바뀌어도 obsolete 아님).
    resolver = Resolver(policy_resolution_version="v1")
    h = _product(tmp_path, _stale_world(), resolver=resolver)
    first = h.product.seal_execution_plan(_pcmd("r1"))
    assert isinstance(first.command_outcome, StaleExecutionBasisProductOutcome)
    resolver.policy_over["policy_resolution_version"] = "v2"  # 서버 shipping default 변경
    seen: list[str] = []
    orig = h.world.capture

    def spy(ws, wid, app, prof, policy):
        seen.append(policy.policy_resolution_version)
        return orig(ws, wid, app, prof, policy)

    h.product._capture = spy
    resp = h.product.seal_execution_plan(_pcmd("r1"))  # replay → fresh current-work observation
    assert isinstance(resp.command_outcome, StaleExecutionBasisProductOutcome)  # historical 보존
    assert isinstance(resp.fresh_observation, CurrentWorkExecutionObservation)
    assert seen and all(v == "v2" for v in seen)  # CURRENT policy, recorded v1 아님


def test_observation_port_failure_degrades_keeps_historical_outcome(tmp_path) -> None:
    # finding 2: observation-only port(admission read) 실패는 historical outcome 을 소거하지 않고
    # 이 축만 context error 로 강등한다.
    h = _product(tmp_path, runtime=_admitting_runtime)
    h.product.seal_execution_plan(_pcmd("r1"))

    def boom(_pid):
        raise RuntimeError("corrupt profile-admission read")

    h.product._read_admission = boom
    resp = h.product.seal_execution_plan(_pcmd("r1"))  # replay published + observe
    assert isinstance(resp.command_outcome, PlanPublishedProductOutcome)  # 보존
    assert isinstance(resp.fresh_observation, ExecutionObservationContextError)


def test_historical_store_corruption_surfaces_not_masked(tmp_path) -> None:
    # finding 2 반대면: historical plan store 손상은 fresh 축 degrade 로 삼켜지지 않고 surface 한다.
    h, ref, _ = _publish_and_ref(tmp_path)

    class _BoomStore:
        def load_or_empty(self, *_a, **_k):
            raise ExecutionPlanStoreIntegrityError("corrupt aggregate")

    h.product._plan_store = _BoomStore()
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        h.product.resolve_plan_reference(ref, "job-ref", WS)


def test_corrupt_secret_fails_before_consuming_request(tmp_path) -> None:
    # finding 3: signing dependency(HMAC secret)는 seal dispatch 전에 preflight 된다 — 손상이면
    # request 를 소비하기 전에 실패하고, secret 을 고치면 같은 request 가 정상 봉인된다(stranded 아님).
    state: dict[str, "bytes | None"] = {"secret": None}

    def load_secret() -> bytes:
        if state["secret"] is None:
            raise SlotTokenSecretError("secret 손상")
        return state["secret"]

    h = _product(tmp_path, load_secret=load_secret)
    with pytest.raises(SlotTokenSecretError):
        h.product.seal_execution_plan(_pcmd("r1"))
    assert not h.plan_store.exists(WORK)  # commit 전에 실패 — request 미소비
    state["secret"] = b"\x33" * 32
    resp = h.product.seal_execution_plan(_pcmd("r1"))  # 같은 request 가 이제 정상 봉인
    assert isinstance(resp.command_outcome, PlanPublishedProductOutcome)


def test_capture_context_error_currentness(tmp_path) -> None:
    world = World()
    h = _product(tmp_path, world)
    h.product.seal_execution_plan(_pcmd("r1"))

    def ctx(*a, **k):
        world.capture_calls += 1
        return ExecutionCaptureContextError("SELECTION_CONTRACT_INTEGRITY_ERROR", "복원 불가")

    h.product._capture = ctx  # 관찰 시점 capture 가 context error → currentness CONTEXT_ERROR
    obs = h.product.seal_execution_plan(_pcmd("r1")).fresh_observation
    assert isinstance(obs, PublishedPlanObservation)
    assert obs.semantic_currentness.state == CURRENTNESS_CONTEXT_ERROR
