"""S5-10(#706) SealExecutionPlan orchestration — optimistic capture·pure compile·final seal.

S5F R2-04b-2(#740): durable Plan store(aggregate·publish·create/reuse·dependency retention)를
제거했다. orchestration 은 store commit 없이 current candidate 에서 직접 ``ExecutionPlanSealed`` 를
낸다. 이 테스트는 capture races·revocation·final-gate stale·lock order·auth·fail-closed 판정을
검증한다 — durable publication·persistence 는 더는 검사 대상이 아니다.

capture port·fresh observation·shipping resolver 는 fake seam 이다. compile 은 실 primitive 로
돌려 실 basis digest·final gate 판정을 검증한다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.application.execution_capture import (
    QUALIFICATION_PROFILE_REVOKED,
    UNSUPPORTED_LOCAL_IMPLEMENTATION,
    CapturedExecutionPolicyBlock,
    CapturedFieldBinding,
    CapturedSelection,
    DomainBlockedSelection,
    ExecutionCaptureContextError,
    ResolvedSealPolicy,
    judge_captured_execution,
)
from hwpxfiller.application.execution_compilation import SLOT_CONFIGURATION_INCOMPLETE
from hwpxfiller.application.execution_composition import (
    COMPOSITION_CONTRACT_ID,
    NATIVE_PRIMITIVE_CONTRACT_ID,
    THEOREM_EVIDENCE_V1,
    TheoremEvidenceRegistry,
    theorem_evidence_digest,
)
from hwpxfiller.application.execution_capture import (
    APPLIED_TEMPLATE_CANDIDATE,
    MATERIALIZATION_BASE_CONTRACT_ID,
)
from hwpxfiller.application import seal_execution_plan as sep
from hwpxfiller.application.seal_execution_plan import (
    STALE_CURRENT_BASIS_NOT_SEALABLE,
    STALE_DIGEST_MISMATCH,
    AuthorizationError,
    BlockedCandidate,
    ExecutionQualificationContextError,
    PlanCandidate,
    SealExecutionPlanCommand,
    S6_START_GATE_LOCK_ORDER,
    UnsupportedLocalImplementation,
    WorkExecutionSummary,
    compile_candidate,
    decide_final_verdict,
    require_exact_selector_consistency,
)
from hwpxfiller.application.execution_contract_set import (
    CaptureEvidenceProvenance,
)
from hwpxfiller.application.stored_execution_plan import (
    ExecutionPlanSealed,
    ExecutionPolicyBlocked,
    ExecutionQualificationBlocked,
    RequestedExact,
    StaleExecutionBasis,
)
from hwpxfiller.domain.canonical_execution_encoding import (
    CANONICAL_ENCODING_VERSION,
    canonical_execution_digest,
)
from hwpxfiller.external.seal_orchestration_runner import (
    SealExecutionPlanResult,
    seal_execution_plan,
)
from hwpxfiller.host.per_work_fence import _held_ranks

from tests.test_execution_compilation import (
    APP,
    AT,
    PROFILE,
    WORK,
    WS,
    _binding,
    _rules,
    _slotless_selection,
    _slotless_structure,
    _snapshot,
    _structure,
    _template,
)


# ─── fixtures ─────────────────────────────────────────────────────────────────────────
def _policy(**over) -> ResolvedSealPolicy:
    kw = dict(
        policy_resolution_version="policy/v1",
        execution_base_kind=APPLIED_TEMPLATE_CANDIDATE,
        execution_semantic_contract_id="execution-semantics/v1",
        binding_value_contract_id="binding-value/v1",
        raw_record_contract_id="raw-record/v1",
        document_value_resolution_contract_id="document-content-value/v1",
        record_validation_contract_id="record-validation/v1",
        record_review_contract_id="record-review/v1",
        composition_contract_id=COMPOSITION_CONTRACT_ID,
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        composition_theorem_evidence_manifest_digest=theorem_evidence_digest(
            THEOREM_EVIDENCE_V1
        ),
        materialization_contract_id="materialization/v1",
        plan_schema_version="hwpx-execution-plan/v1",
        canonical_encoding_version=CANONICAL_ENCODING_VERSION,
    )
    kw.update(over)
    return ResolvedSealPolicy(**kw)


def _sel_value(selector, default):
    return selector.value if isinstance(selector, RequestedExact) else default


class Resolver:
    """new request + AUTO → shipping default. EXACT selector 는 그대로 받는다."""

    def __init__(self, **policy_over):
        self.calls = 0
        self.policy_over = policy_over

    def __call__(self, command, observed):
        self.calls += 1
        return _policy(
            execution_base_kind=command.requested_execution_base_kind,
            execution_semantic_contract_id=_sel_value(
                command.requested_execution_semantic_contract, "execution-semantics/v1"
            ),
            plan_schema_version=_sel_value(
                command.requested_plan_schema, "hwpx-execution-plan/v1"
            ),
            canonical_encoding_version=_sel_value(
                command.requested_canonical_encoding, CANONICAL_ENCODING_VERSION
            ),
            **self.policy_over,
        )


class World:
    """capture port·fresh observation fake — mutable current state + capture-gate 이후 mutation hook."""

    def __init__(self, *, selection=None, binding=None, profile=PROFILE, app=APP,
                 policy_block=None):
        self.structure = _structure()
        self._sel = selection
        self._bind = binding
        self.profile = profile
        self.app = app
        self.policy_block = policy_block
        self.capture_calls = 0
        self.summary_calls = 0
        self.capture_ranks: list[list[int]] = []
        self.on_after_capture_gate = None
        self.summary_script: list[WorkExecutionSummary] | None = None
        self.alternate = False

    def summary(self, ws, wid) -> WorkExecutionSummary:
        self.summary_calls += 1
        if self.alternate:
            pid = self.profile if self.summary_calls % 2 == 1 else "other-profile"
            return WorkExecutionSummary(pid, self.app)
        if self.summary_script:
            return self.summary_script.pop(0)
        return WorkExecutionSummary(self.profile, self.app)

    def _selection_obs(self):
        return self._sel if self._sel is not None else CapturedSelection(
            _snapshot(self.structure, app=self.app)
        )

    def _binding_obs(self):
        return self._bind if self._bind is not None else CapturedFieldBinding(
            _binding(self.structure, app=self.app)
        )

    def capture(self, ws, wid, exp_app, exp_profile, policy):
        self.capture_calls += 1
        self.capture_ranks.append(list(_held_ranks()))
        result = judge_captured_execution(
            workspace_instance_id=ws,
            work_authority_id=wid,
            expected_template_application_id=exp_app,
            expected_profile_id=exp_profile,
            resolved_seal_policy=policy,
            template=_template(self.structure, app=self.app),
            selection_observation=self._selection_obs(),
            field_binding_observation=self._binding_obs(),
            captured_at=AT,
            policy_block=self.policy_block,
        )
        if self.capture_calls == 1 and self.on_after_capture_gate:
            self.on_after_capture_gate(self)
        return result


def _command(request_id="r1", **over) -> SealExecutionPlanCommand:
    return SealExecutionPlanCommand(
        workspace_instance_id=WS, work_ref="job-ref", request_id=request_id, **over
    )


def _run(world, command=None, *, resolver=None, authorize=None, route=None, **over) -> SealExecutionPlanResult:
    return seal_execution_plan(
        command or _command(),
        resolve_route=route or (lambda ws, ref: WORK),
        authorize=authorize or (lambda wid, cmd: None),
        read_summary=world.summary,
        capture_under_fence=world.capture,
        resolve_shipping_policy=resolver or Resolver(),
        **over,
    )


# ══ seal 성공(durable publication 없이 current candidate 에서 직접) ══════════════════════
def test_publish_returns_sealed_current_value() -> None:
    result = _run(World())
    assert isinstance(result.terminal_outcome, ExecutionPlanSealed)
    assert result.terminal_outcome.execution_basis_digest  # nonempty basis identity


# ══ capture races ═════════════════════════════════════════════════════════════════════
def test_slot_mutation_after_capture_final_stale_digest_mismatch() -> None:
    world = World()

    def mutate(w):
        w._sel = CapturedSelection(_snapshot(w.structure, selected="o2", app=w.app))

    world.on_after_capture_gate = mutate
    result = _run(world)
    assert isinstance(result.terminal_outcome, StaleExecutionBasis)
    assert result.terminal_outcome.stale_reason == STALE_DIGEST_MISMATCH


def test_detached_only_mutation_same_basis_publishes() -> None:
    world = World()

    def mutate(w):  # declared 만 바뀌고 effective 는 동일 → 같은 basis
        w._sel = CapturedSelection(_snapshot(w.structure, detached="o2", app=w.app))

    world.on_after_capture_gate = mutate
    result = _run(world)
    assert isinstance(result.terminal_outcome, ExecutionPlanSealed)


def test_complete_becomes_incomplete_stale_not_blocker_rebase() -> None:
    world = World()

    def mutate(w):
        w._sel = DomainBlockedSelection(SLOT_CONFIGURATION_INCOMPLETE, "slot 미완")

    world.on_after_capture_gate = mutate
    result = _run(world)
    # current 가 seal 불가 → STALE(CURRENT_BASIS_NOT_SEALABLE), current blocker 를 기록하지 않는다.
    assert isinstance(result.terminal_outcome, StaleExecutionBasis)
    assert result.terminal_outcome.stale_reason == STALE_CURRENT_BASIS_NOT_SEALABLE


def test_application_change_stale() -> None:
    world = World()

    def mutate(w):
        w.app = "app-2"  # current Application 이동 → summary 가 candidate 와 불일치

    world.on_after_capture_gate = mutate
    result = _run(world)
    assert isinstance(result.terminal_outcome, StaleExecutionBasis)
    assert result.terminal_outcome.stale_reason == STALE_DIGEST_MISMATCH


# ══ revocation ════════════════════════════════════════════════════════════════════════
def _revoked_block():
    return CapturedExecutionPolicyBlock(
        policy_code=QUALIFICATION_PROFILE_REVOKED,
        observed_at=AT,
        qualification_profile_id=PROFILE,
        observed_policy_version="2",
        policy_observation_digest="sha256:pol",
    )


def test_revoke_before_capture_policy_block() -> None:
    result = _run(World(policy_block=_revoked_block()))
    assert isinstance(result.terminal_outcome, ExecutionPolicyBlocked)
    assert result.terminal_outcome.policy_code == QUALIFICATION_PROFILE_REVOKED


def test_revoke_between_capture_and_final_policy_block() -> None:
    world = World()

    def mutate(w):
        w.policy_block = _revoked_block()

    world.on_after_capture_gate = mutate
    result = _run(world)
    assert isinstance(result.terminal_outcome, ExecutionPolicyBlocked)


def test_no_reverse_lock_order_capture_under_profile_then_work() -> None:
    world = World()
    _run(world)  # 실 fence — 역순이면 LockOrderViolation 이 났을 것이다
    # capture 는 PerWorkFence(0) 아래에서만 일어난다.
    assert all(ranks == [0] for ranks in world.capture_ranks)


# ══ recompute-not-persist / auth ══════════════════════════════════════════════════════
def test_authorization_repeated_each_call() -> None:
    _run(World(), _command("r1"))

    calls = {"n": 0}

    def authz(wid, cmd):
        calls["n"] += 1
        raise AuthorizationError("denied")

    with pytest.raises(AuthorizationError):
        _run(World(), _command("r1"), authorize=authz)
    assert calls["n"] == 1  # 매 호출 authorize 를 다시 확인한다(replay 없음)


def test_same_request_recomputes_current_value_no_persistence() -> None:
    # durable store 가 없다 — 같은 request 를 다시 호출해도 방금 계산한 현재 결과를 낸다(persistence 없음).
    a = _run(World(), _command("r1")).terminal_outcome
    b = _run(World(), _command("r1")).terminal_outcome
    assert isinstance(a, ExecutionPlanSealed) and isinstance(b, ExecutionPlanSealed)
    assert a.execution_basis_digest == b.execution_basis_digest  # 같은 authority → 같은 basis


# ══ current basis: candidate contracts, not latest ════════════════════════════════════
def test_final_gate_uses_candidate_contracts_not_re_resolved() -> None:
    resolver = Resolver()
    _run(World(), resolver=resolver)
    assert resolver.calls == 1  # capture gate 에서 1회만 — final 은 candidate policy 재사용


def test_capture_context_error_raises_attempt() -> None:
    class CtxWorld(World):
        def capture(self, ws, wid, exp_app, exp_profile, policy):
            self.capture_calls += 1
            return ExecutionCaptureContextError(
                "SELECTION_CONTRACT_INTEGRITY_ERROR", "복원 불가"
            )

    with pytest.raises(ExecutionQualificationContextError):
        _run(CtxWorld())


# ══ S6 start admission port 선언 ══════════════════════════════════════════════════════
def test_s6_start_gate_lock_order_declared() -> None:
    # R2-05b: ProfileFence 제거로 outer rank 는 PerWorkMutationFence 다(S6 구현은 미착수).
    assert S6_START_GATE_LOCK_ORDER[0] == "PerWorkMutationFence"
    assert "QualificationProfileAdmissionFence" not in S6_START_GATE_LOCK_ORDER
    assert S6_START_GATE_LOCK_ORDER[-1] == "LongMaterialization"
    assert "<fences released>" in S6_START_GATE_LOCK_ORDER


# ══ forbidden work: pure section holds no fence ═══════════════════════════════════════
def test_long_pure_section_holds_no_fence(monkeypatch) -> None:
    from hwpxfiller.external import seal_orchestration_runner as runner_mod

    ranks_at_compile: list[list[int]] = []
    real = runner_mod.compile_candidate

    def spy(captured, **kw):
        ranks_at_compile.append(list(_held_ranks()))
        return real(captured, **kw)

    monkeypatch.setattr(runner_mod, "compile_candidate", spy)
    _run(World())
    # 첫 compile(candidate)은 fence 밖(빈 rank), 둘째(final current)는 [0] 아래.
    assert ranks_at_compile[0] == []
    assert ranks_at_compile[1] == [0]


def test_runner_declares_no_native_or_source_seam() -> None:
    import hwpxfiller.external.seal_orchestration_runner as runner_mod

    src = __import__("inspect").getsource(runner_mod)
    for forbidden in ("hwpxcore", "hwpx_engine", "template_source_reader",
                      "dataset_store", "output_files", "native"):
        assert forbidden not in src


# ══ pure unit: 판정 branch 직접 커버 ══════════════════════════════════════════════════
def _captured(world=None, policy=None):
    world = world or World()
    return judge_captured_execution(
        workspace_instance_id=WS, work_authority_id=WORK,
        expected_template_application_id=world.app, expected_profile_id=world.profile,
        resolved_seal_policy=policy or _policy(),
        template=_template(world.structure, app=world.app),
        selection_observation=CapturedSelection(_snapshot(world.structure, app=world.app)),
        field_binding_observation=CapturedFieldBinding(_binding(world.structure, app=world.app)),
        captured_at=AT, policy_block=None,
    )


def test_require_exact_selector_consistency_rejects_mismatch() -> None:
    cmd = _command(requested_plan_schema=RequestedExact("other-plan/v9"))
    with pytest.raises(ExecutionQualificationContextError):
        require_exact_selector_consistency(cmd, _policy())


def test_require_exact_selector_rejects_base_kind_and_unsupported() -> None:
    with pytest.raises(ExecutionQualificationContextError):
        require_exact_selector_consistency(
            _command(requested_execution_base_kind="OTHER"), _policy()
        )
    with pytest.raises(UnsupportedLocalImplementation):
        require_exact_selector_consistency(
            _command(), _policy(plan_schema_version="unknown/v0")
        )
    with pytest.raises(UnsupportedLocalImplementation):
        require_exact_selector_consistency(
            _command(), _policy(canonical_encoding_version="bad/v0")
        )


def test_compile_candidate_unsupported_composition_contract() -> None:
    captured = _captured(policy=_policy(composition_contract_id="unknown/v9"))
    with pytest.raises(UnsupportedLocalImplementation):
        compile_candidate(captured)


def test_compile_candidate_context_error_raises_attempt() -> None:
    # SLOTTED selection + 잘못된 structure digest → compile context error.
    from hwpxfiller.application.slot_selection_input import SlotConfigurationSnapshot

    world = World()
    captured = _captured(world)
    bad = SlotConfigurationSnapshot(
        work_id=WORK, template_application_id=APP, source_configuration_version=1,
        selection_semantic_contract_id=captured.selection.selection_semantic_contract_id,
        structure_projection_schema_version=captured.selection.structure_projection_schema_version,
        effective_selections=captured.selection.effective_selections,
        effective_selection_digest=captured.selection.effective_selection_digest,
        declared_selection_digest=captured.selection.declared_selection_digest,
        template_structure_digest="sha256:wrong",
        captured_at=AT,
    )
    import dataclasses
    captured2 = dataclasses.replace(captured, selection=bad)
    with pytest.raises(ExecutionQualificationContextError):
        compile_candidate(captured2)


def _blocked_candidate(digest="sha256:in", blockers=("ACTIVE_FIELD_UNBOUND",)):
    evidence = sep.CompleteSealCaptureEvidence(
        captured_execution_input_semantic_projection={"k": "v"},
        captured_execution_input_digest=canonical_execution_digest({"k": "v"}),
        provenance=CaptureEvidenceProvenance("r", "0", AT),
    )
    return BlockedCandidate(
        qualification_profile_id=PROFILE, template_application_id=APP,
        resolved_seal_policy=_policy(), normalized_blockers=blockers,
        capture_evidence=evidence, captured_execution_input_digest=digest,
    )


def _plan_candidate():
    return compile_candidate(_captured())


def test_decide_final_blocked_candidate_same_input_commits_blocked() -> None:
    cand = _blocked_candidate(digest="sha256:same")
    # current 도 blocked·같은 input digest → blocker first-seen commit.
    cur = _blocked_candidate(digest="sha256:same")
    current_result = _captured()  # complete placeholder; compiled 은 blocked
    verdict = decide_final_verdict(
        cand, current_result, cur, WorkExecutionSummary(PROFILE, APP)
    )
    assert isinstance(verdict, sep.FinalLedger)
    assert isinstance(verdict.outcome, ExecutionQualificationBlocked)


def test_decide_final_blocked_candidate_changed_input_raises() -> None:
    cand = _blocked_candidate(digest="sha256:a")
    cur = _blocked_candidate(digest="sha256:b")
    with pytest.raises(ExecutionQualificationContextError):
        decide_final_verdict(cand, _captured(), cur, WorkExecutionSummary(PROFILE, APP))


def test_decide_final_blocked_candidate_now_sealable_raises() -> None:
    cand = _blocked_candidate()
    cur = _plan_candidate()
    with pytest.raises(ExecutionQualificationContextError):
        decide_final_verdict(cand, _captured(), cur, WorkExecutionSummary(PROFILE, APP))


def test_decide_final_plan_candidate_current_blocked_stale() -> None:
    cand = _plan_candidate()
    cur = _blocked_candidate()
    verdict = decide_final_verdict(cand, _captured(), cur, WorkExecutionSummary(PROFILE, APP))
    assert isinstance(verdict, sep.FinalLedger)
    assert isinstance(verdict.outcome, StaleExecutionBasis)
    assert verdict.outcome.stale_reason == STALE_CURRENT_BASIS_NOT_SEALABLE


def test_decide_final_context_error_raises() -> None:
    cand = _plan_candidate()
    err = ExecutionCaptureContextError(UNSUPPORTED_LOCAL_IMPLEMENTATION, "local")
    with pytest.raises(UnsupportedLocalImplementation):
        decide_final_verdict(cand, err, None, WorkExecutionSummary(PROFILE, APP))


# ══ capture gate domain block (terminal at capture linearization point) ═══════════════
def test_capture_gate_domain_block_commits_qualification_blocked() -> None:
    world = World(
        selection=DomainBlockedSelection(SLOT_CONFIGURATION_INCOMPLETE, "slot 미완")
    )
    result = _run(world)
    # domain block 은 capture gate 자체가 linearization point — 즉시 terminal.
    assert isinstance(result.terminal_outcome, ExecutionQualificationBlocked)
    assert world.capture_calls == 1  # final gate 재capture 없음


def test_command_rejects_empty_request_id() -> None:
    with pytest.raises(ValueError):
        SealExecutionPlanCommand(workspace_instance_id=WS, work_ref="ref", request_id="")


def test_compile_slotless_captured_publishes() -> None:
    # slotless structure/selection → source_configuration_version None branch.
    structure = _slotless_structure()
    captured = judge_captured_execution(
        workspace_instance_id=WS, work_authority_id=WORK,
        expected_template_application_id=APP, expected_profile_id=PROFILE,
        resolved_seal_policy=_policy(),
        template=_template(structure, app=APP),
        selection_observation=CapturedSelection(_slotless_selection(structure)),
        field_binding_observation=CapturedFieldBinding(_binding(structure, app=APP)),
        captured_at=AT, policy_block=None,
    )
    candidate = compile_candidate(captured)
    assert isinstance(candidate, PlanCandidate)
    assert candidate.capture_evidence.provenance.source_configuration_version == (
        sep._SLOTLESS_CONFIG_REF
    )


def test_compile_unbound_active_field_is_blocked_candidate() -> None:
    structure = _structure()
    binding = _binding(structure, rules=_rules(drop=("성명",)))
    captured = judge_captured_execution(
        workspace_instance_id=WS, work_authority_id=WORK,
        expected_template_application_id=APP, expected_profile_id=PROFILE,
        resolved_seal_policy=_policy(),
        template=_template(structure, app=APP),
        selection_observation=CapturedSelection(_snapshot(structure, app=APP)),
        field_binding_observation=CapturedFieldBinding(binding),
        captured_at=AT, policy_block=None,
    )
    candidate = compile_candidate(captured)
    assert isinstance(candidate, BlockedCandidate)
    assert "ACTIVE_FIELD_UNBOUND" in candidate.normalized_blockers


def test_compile_bad_schema_encoding_raise_unsupported() -> None:
    with pytest.raises(UnsupportedLocalImplementation):
        compile_candidate(_captured(policy=_policy(plan_schema_version="nope/v0")))
    with pytest.raises(UnsupportedLocalImplementation):
        compile_candidate(_captured(policy=_policy(canonical_encoding_version="nope/v0")))


def test_complete_capture_evidence_missing_digest_raises() -> None:
    import dataclasses

    captured = _captured()
    broken = dataclasses.replace(captured, captured_execution_input_digest=None)
    with pytest.raises(ExecutionQualificationContextError):
        sep.complete_capture_evidence(broken)


def _domain_block_result():
    structure = _structure()
    return judge_captured_execution(
        workspace_instance_id=WS, work_authority_id=WORK,
        expected_template_application_id=APP, expected_profile_id=PROFILE,
        resolved_seal_policy=_policy(),
        template=_template(structure, app=APP),
        selection_observation=DomainBlockedSelection(SLOT_CONFIGURATION_INCOMPLETE, "미완"),
        field_binding_observation=CapturedFieldBinding(_binding(structure, app=APP)),
        captured_at=AT, policy_block=None,
    )


def test_decide_final_blocked_candidate_current_not_sealable_raises() -> None:
    cand = _blocked_candidate()
    with pytest.raises(ExecutionQualificationContextError):
        decide_final_verdict(
            cand, _domain_block_result(), None, WorkExecutionSummary(PROFILE, APP)
        )


def test_domain_block_evidence_provenance_from_observations() -> None:
    from hwpxfiller.application.execution_capture import (
        DomainBlockedFieldBinding,
        NEEDS_BINDING_SEMANTIC_MIGRATION,
    )

    structure = _structure()
    # selection captured(config ref from selection) + binding blocked(revision unresolved).
    block = judge_captured_execution(
        workspace_instance_id=WS, work_authority_id=WORK,
        expected_template_application_id=APP, expected_profile_id=PROFILE,
        resolved_seal_policy=_policy(),
        template=_template(structure, app=APP),
        selection_observation=CapturedSelection(_snapshot(structure, app=APP)),
        field_binding_observation=DomainBlockedFieldBinding(
            NEEDS_BINDING_SEMANTIC_MIGRATION, "migration 필요"
        ),
        captured_at=AT, policy_block=None,
    )
    evidence = sep._attempt_evidence_of_domain_block(block)
    assert evidence.provenance.field_binding_authority_revision == sep._PROVENANCE_UNRESOLVED
    assert evidence.provenance.source_configuration_version != sep._PROVENANCE_UNRESOLVED


def test_domain_block_missing_attempt_digest_raises() -> None:
    import dataclasses

    block = _domain_block_result()
    broken = dataclasses.replace(block, captured_attempt_digest=None)
    with pytest.raises(ExecutionQualificationContextError):
        sep._attempt_evidence_of_domain_block(broken)


# ══ Codex #722 finding fixes (store 무관 판정만 잔존) ══════════════════════════════════
def test_finding1_injected_theorem_registry_threaded_into_contract_set(monkeypatch) -> None:
    # build_execution_contract_set 가 injected registry 를 받아야 한다 — DEFAULT 로 조용히 fallback 하면
    # injected registry 가 admit 한 manifest 가 여기서 늦게 IntegrityError 로 터진다.
    injected = TheoremEvidenceRegistry()
    injected.register(THEOREM_EVIDENCE_V1)
    seen: list[object] = []
    real = sep.build_execution_contract_set

    def spy(*a, theorem_registry, **kw):
        seen.append(theorem_registry)
        return real(*a, theorem_registry=theorem_registry, **kw)

    monkeypatch.setattr(sep, "build_execution_contract_set", spy)
    candidate = compile_candidate(_captured(), theorem_registry=injected)
    assert isinstance(candidate, PlanCandidate)
    assert seen == [injected]  # DEFAULT 가 아니라 injected 를 그대로 받았다


def test_finding3_capture_policy_mismatch_rejected_fail_closed() -> None:
    class TamperWorld(World):
        def capture(self, ws, wid, exp_app, exp_profile, policy):
            self.capture_calls += 1
            tampered = _policy(policy_resolution_version="tampered/v9")  # ≠ 요청 policy
            return judge_captured_execution(
                workspace_instance_id=ws, work_authority_id=wid,
                expected_template_application_id=exp_app, expected_profile_id=exp_profile,
                resolved_seal_policy=tampered,
                template=_template(self.structure, app=self.app),
                selection_observation=CapturedSelection(_snapshot(self.structure, app=self.app)),
                field_binding_observation=CapturedFieldBinding(_binding(self.structure, app=self.app)),
                captured_at=AT, policy_block=None,
            )

    with pytest.raises(ExecutionQualificationContextError):
        _run(TamperWorld())


def test_finding4_profile_moved_and_revoked_records_policy_block() -> None:
    world = World()

    def mutate(w):
        w.profile = "profile-2"  # Profile 이동
        w.policy_block = _revoked_block()  # candidate profile 은 revoked

    world.on_after_capture_gate = mutate
    result = _run(world)
    # moved 를 이유로 revocation 을 놓치지 않는다 — policy block 이 precedence 상 앞선다.
    assert isinstance(result.terminal_outcome, ExecutionPolicyBlocked)


def test_finding4_profile_moved_and_admitted_is_stale() -> None:
    world = World()

    def mutate(w):
        w.profile = "profile-2"
        w.app = "app-2"  # candidate app 관측 시 cross-ref context error → moved stale

    world.on_after_capture_gate = mutate
    result = _run(world)
    assert isinstance(result.terminal_outcome, StaleExecutionBasis)
    assert result.terminal_outcome.stale_reason == STALE_DIGEST_MISMATCH
