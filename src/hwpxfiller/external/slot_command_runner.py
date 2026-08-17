"""S4 Slot Configuration command 결선 — fence-first public entry + store commit (S4-07 · #677).

각 mutation command 는 shared :func:`per_work_mutation_fence` 를 먼저 잡고 ``*_under_fence``
helper 로 위임한다(#675 pattern, non-reentrant). helper 는 fence 를 재획득하지 않는다.
``tests/repo_contract/test_per_work_fence_gate.py`` 가 under-fence 직접 호출을 정적으로 막는다.

idempotency 17단계(fence→load/ledger-create→fingerprint→replay|key-reuse→S3 read→exact app→
context resolve→exact contract→ensure config→config version CAS→mutate→one commit→fresh view)를
이 순서대로 닫는다. ledger replay 는 과거 context decoder 없이 trusted fingerprint 만으로 최초
outcome 을 재생한다 — current view 계산은 replay 뒤 별도 단계라 실패해도 replay outcome 과 섞지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from hwpxfiller.application.slot_command import (
    CHANGED,
    CLEAR,
    FINGERPRINT_SCHEMA_VERSION,
    NO_CHANGE,
    SELECT,
    STALE_CONFIGURATION,
    STALE_TEMPLATE_APPLICATION,
    ConfigurationCommandContext,
    ConfigurationContextClaimMismatch,
    ConfigurationMutationOutcome,
    CrossWorkConfigurationToken,
    WorkspaceIdentityMismatch,
    command_fingerprint,
    decide_clear,
    decide_select,
)
from hwpxfiller.application.slot_configuration_context import (
    AppliedCandidateReadPort,
    QualificationReadPort,
    SlotConfigurationContext,
    SlotConfigurationContextError,
    StaleTemplateApplication,
    WorkTemplateStateReadPort,
    resolve_exact_applied_template_input,
    resolve_slot_configuration_context,
)
from hwpxfiller.application.candidate_revision import CandidateObjectStorePort
from hwpxfiller.application.execution_structure import (
    ExecutionStructureError,
    decode_execution_structure,
)
from hwpxfiller.application.qualification_evidence import PASS
from hwpxfiller.application.selection_compatibility import ChainApplicationFacts
from hwpxfiller.application.slot_selection_input import (
    SlotSelectionInput,
    plan_capture,
)
from hwpxfiller.application.slotless_run_bridge import (
    AdmittedSlotlessRun,
    ExecutionConfigurationProvenancePort,
    admit_slotless_run,
)
from hwpxfiller.host.staged_template import stage_exact_applied_bytes
from hwpxfiller.application.slot_configuration_projection import (
    CurrentSlotConfigurationView,
    project_context_error,
    project_current_slot_configuration,
)
from hwpxfiller.application.slot_reconciliation import (
    ReconciliationApplication,
    plan_successor_reconciliation,
    resolve_slot_configuration,
)
from hwpxfiller.application.stored_work_configuration import (
    IdempotencyKeyReused,
    IdempotencyRecord,
    StoredWorkConfiguration,
    TerminalOutcome,
    empty_stored,
    find_request,
)
from hwpxfiller.application.work_slot_configuration import (
    WorkSlotConfigurationAggregate,
    WorkSlotConfigurationDraft,
    create_empty,
    create_reconciled,
)
from hwpxfiller.domain.slot_selection import (
    DEFAULT_SELECTION_SEMANTIC_REGISTRY,
    SelectionSemanticBindingKey,
    SlotSelectionError,
    SlotSelectionSet,
    resolve_selection_policy,
)
from hwpxfiller.host.per_work_fence import per_work_mutation_fence

from .qualification_store import ObjectNotFound
from .work_configuration_store import WorkSlotConfigurationStore


@dataclass(frozen=True)
class SlotCommandResult:
    """mutation terminal outcome + 같은 fence 아래 fresh view(#675 TOCTOU 차단).

    view 계산 실패는 outcome 과 **분리**한다 — mutation outcome(replay 포함)은 그대로 서고
    view 만 None + ``view_error`` 로 표식한다(#677: current view 실패는 별도 context error).
    """

    outcome: ConfigurationMutationOutcome
    view: CurrentSlotConfigurationView | None
    view_error: str | None


# ─── shared helpers (module-private) ─────────────────────────────────────────────
def _resolve_context(
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    context: ConfigurationCommandContext,
) -> SlotConfigurationContext:
    """token Application 을 expected 로 걸어 context 를 복원한다(mismatch → StaleTemplateApplication)."""
    return resolve_slot_configuration_context(
        work_state, qualification, candidate,
        context.workspace_instance_id,
        context.expected_work_authority_id,
        context.token_template_application_id,
    )


def _current_config(
    stored: StoredWorkConfiguration, application_id: str
) -> WorkSlotConfigurationDraft | None:
    for config in stored.configurations.configurations:
        if config.base_template_application_id == application_id:
            return config
    return None


def _put_config(
    aggregate: WorkSlotConfigurationAggregate, config: WorkSlotConfigurationDraft
) -> WorkSlotConfigurationAggregate:
    kept = tuple(
        c for c in aggregate.configurations
        if c.base_template_application_id != config.base_template_application_id
    )
    return replace(aggregate, configurations=kept + (config,))


def _chain_application_facts(
    qualification: QualificationReadPort, pass_evidence_id: str
) -> ChainApplicationFacts:
    """한 Application 의 PASS Evidence 에서 compatibility 판정 입력을 파생한다(fail-closed).

    원 HWPX 를 다시 parse 하지 않는다 — 이미 durable 한 v2 execution structure 를 decode 하고
    self-consistency 를 재검증할 뿐이다. v1/missing/integrity-fail 이면 셋 다 None 을 낸다
    (false AUTO_KEEP 금지 — unknown evidence 는 절대 승계 근거가 되지 못한다).
    """
    try:
        evidence = qualification.get_evidence(pass_evidence_id)
        proj = evidence.structure_projection
        if evidence.result != PASS or proj is None:
            return ChainApplicationFacts(None, None, None)
        structure = decode_execution_structure(proj.payload)
        contract = DEFAULT_SELECTION_SEMANTIC_REGISTRY.resolve(
            SelectionSemanticBindingKey(
                evidence.qualification_profile_id, proj.projection_schema_version
            )
        )
        return ChainApplicationFacts(
            structure, contract.contract_id, resolve_selection_policy(contract, None)
        )
    except (ExecutionStructureError, SlotSelectionError, ObjectNotFound):
        return ChainApplicationFacts(None, None, None)


def _plan_new_config(
    existing_configs: tuple[WorkSlotConfigurationDraft, ...],
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    ctx: SlotConfigurationContext,
    now: str,
) -> WorkSlotConfigurationDraft | None:
    """current Application 의 Configuration 을 #676 plan 으로 만든다.

    None 은 **barrier**(slotless + retained source 없음 = Configuration 이 없어야 함)이고
    caller 는 이를 explicit-empty 로 물질화하지 않는다(#672 부재 vs tombstone 구분 보존).
    """
    aggregate = work_state.load(ctx.work_id)
    if aggregate is None:  # pragma: no cover - context resolve 가 이미 보장
        return None
    lineage = aggregate.work.template_lineage_id
    apps = {
        a.application_id: ReconciliationApplication(
            a.application_id, a.previous_application_id, a.application_epoch,
            a.work_id, lineage,
        )
        for a in aggregate.applications
    }
    # 각 chain Application 의 exact v2 evidence 에서 compatibility 입력을 파생한다(SG-01 #733).
    chain_facts = {
        a.application_id: _chain_application_facts(qualification, a.pass_evidence_id)
        for a in aggregate.applications
    }
    configs = {c.base_template_application_id: c for c in existing_configs}
    plan = plan_successor_reconciliation(
        ctx.template_application_id, ctx.template_structure,
        ctx.selection_semantic_contract, apps, configs,
        chain_facts=chain_facts,
    )
    if not plan.should_create_configuration:
        return None
    if plan.source_application_id is not None:
        return create_reconciled(
            ctx.work_id, ctx.template_application_id, plan.initial_selections,
            plan.source_application_id, plan.source_configuration_version,
            plan.source_declared_selection_digest, now,
        )
    return create_empty(ctx.work_id, ctx.template_application_id, now)


def _load_existing(
    store: WorkSlotConfigurationStore, ws: str, work_id: str
) -> StoredWorkConfiguration | None:
    """존재하면 load(없으면 None) — 저장은 storable terminal outcome 시점까지 미룬다(#677).

    load 한 aggregate 의 workspace 가 context 와 다르면 cross-workspace 재사용이라 거절한다.
    """
    if not store.exists(work_id):
        return None
    stored = store.load(work_id)
    if stored.workspace_instance_id != ws:
        raise WorkspaceIdentityMismatch(
            f"저장 workspace {stored.workspace_instance_id!r} 가 context {ws!r} 와 다르다"
        )
    return stored


def _persist(
    store: WorkSlotConfigurationStore,
    ws: str,
    work_id: str,
    stored: StoredWorkConfiguration | None,
    config: WorkSlotConfigurationDraft | None,
    record: IdempotencyRecord | None,
) -> None:
    """Configuration(있으면) + first-seen record(있으면) 를 한 commit 으로 쓴다.

    aggregate 는 여기(=storable terminal outcome 확정)서 처음 생긴다 — token·contract·
    integrity 로 raise 한 경로는 storage 를 건드리지 않는다(#677 저장 안 함 계약).
    Ensure 는 record 없이 config 만 남긴다(ledger 는 Select/Clear 만).
    """
    records = (record,) if record is not None else ()
    if stored is None:
        base = empty_stored(ws, work_id)  # version 1
        aggregate = _put_config(base.configurations, config) if config else base.configurations
        store.create(replace(base, configurations=aggregate, processed_requests=records))
        return
    aggregate = _put_config(stored.configurations, config) if config else stored.configurations
    new_stored = replace(
        stored,
        configurations=aggregate,
        processed_requests=stored.processed_requests + records,
        aggregate_version=stored.aggregate_version + 1,
    )
    store.update(stored.work_id, stored.aggregate_version, lambda _cur: new_stored)


def _record(
    context: ConfigurationCommandContext,
    request_id: str,
    fingerprint: str,
    outcome_code: str,
    changed: bool,
    src_version: int | None,
    res_version: int | None,
    now: str,
) -> IdempotencyRecord:
    return IdempotencyRecord(
        request_id=request_id,
        fingerprint_schema_version=FINGERPRINT_SCHEMA_VERSION,
        command_fingerprint=fingerprint,
        terminal_outcome=TerminalOutcome(
            context.token_template_application_id, outcome_code, changed,
            src_version, res_version,
        ),
        request_actor_binding_digest=context.actor_binding_digest,
        recorded_at=now,
    )


def _replay_outcome(record: IdempotencyRecord) -> ConfigurationMutationOutcome:
    o = record.terminal_outcome
    return ConfigurationMutationOutcome(
        o.outcome_code, o.changed, o.application_id,
        o.source_configuration_version, o.resulting_configuration_version,
        outcome_replayed=True,
    )


def _outcome(record: IdempotencyRecord) -> ConfigurationMutationOutcome:
    o = record.terminal_outcome
    return ConfigurationMutationOutcome(
        o.outcome_code, o.changed, o.application_id,
        o.source_configuration_version, o.resulting_configuration_version,
        outcome_replayed=False,
    )


def _config_version_cas(
    context: ConfigurationCommandContext, pre: WorkSlotConfigurationDraft | None
) -> bool:
    """token 이 본 Configuration 상태와 현재가 정확히 일치하는지(stale 이면 False)."""
    if context.token_configuration_presence:
        return pre is not None and context.token_configuration_version == pre.version
    return pre is None


# ─── under-fence fresh view (Get·Capture·mutation 응답) ─────────────────────────
def _compute_view(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    context: ConfigurationCommandContext,
) -> CurrentSlotConfigurationView:
    work_id = context.expected_work_authority_id
    ctx = _resolve_context(work_state, qualification, candidate, context)
    config = None
    if store.exists(work_id):
        config = _current_config(store.load(work_id), ctx.template_application_id)
    selections = config.selections if config is not None else SlotSelectionSet(())
    resolution = resolve_slot_configuration(
        selections, ctx.template_structure, ctx.selection_semantic_contract
    )
    return project_current_slot_configuration(ctx, config, resolution)


def _result(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    context: ConfigurationCommandContext,
    outcome: ConfigurationMutationOutcome,
) -> SlotCommandResult:
    """outcome 에 같은 fence 아래 fresh view 를 붙인다 — view 실패는 outcome 과 분리."""
    try:
        view = _compute_view(store, work_state, qualification, candidate, context)
        return SlotCommandResult(outcome, view, None)
    except SlotConfigurationContextError as exc:
        # current view 계산 실패(stale·integrity)는 mutation outcome 과 분리해 표식만 한다.
        return SlotCommandResult(outcome, None, str(exc))


# ─── mutation commands ───────────────────────────────────────────────────────────
def _mutate_under_fence(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    context: ConfigurationCommandContext,
    request_id: str,
    kind: str,
    slot_id: str,
    option_id: str | None,
    now: str,
) -> SlotCommandResult:
    if context.expected_work_authority_id != context.token_work_authority_id:
        raise CrossWorkConfigurationToken("route Work 와 token Work 가 다르다")
    work_id = context.expected_work_authority_id
    ws = context.workspace_instance_id
    fingerprint = command_fingerprint(kind, context, slot_id, option_id)
    stored = _load_existing(store, ws, work_id)  # 없으면 None — storage 는 commit 시점까지 미룬다

    if stored is not None:
        existing = find_request(stored, request_id)
        if existing is not None:  # replay 는 context decoder 없이 최초 outcome 재생
            if (
                existing.command_fingerprint == fingerprint
                and existing.fingerprint_schema_version == FINGERPRINT_SCHEMA_VERSION
            ):
                return _result(
                    store, work_state, qualification, candidate, context,
                    _replay_outcome(existing),
                )
            raise IdempotencyKeyReused(
                f"request {request_id} 가 다른 fingerprint 로 재사용됨"
            )

    def _committed(
        config: WorkSlotConfigurationDraft | None, rec: IdempotencyRecord
    ) -> SlotCommandResult:
        _persist(store, ws, work_id, stored, config, rec)
        return _result(
            store, work_state, qualification, candidate, context, _outcome(rec)
        )

    try:
        ctx = _resolve_context(work_state, qualification, candidate, context)
    except StaleTemplateApplication:
        return _committed(None, _record(
            context, request_id, fingerprint, STALE_TEMPLATE_APPLICATION, False,
            context.token_configuration_version, context.token_configuration_version, now,
        ))

    if ctx.selection_semantic_contract_id != context.token_selection_contract_id:
        raise ConfigurationContextClaimMismatch("token contract claim 이 current 와 다르다")

    existing_configs = stored.configurations.configurations if stored else ()
    pre = _current_config(stored, ctx.template_application_id) if stored else None
    if not _config_version_cas(context, pre):
        return _committed(None, _record(
            context, request_id, fingerprint, STALE_CONFIGURATION, False,
            pre.version if pre else None, pre.version if pre else None, now,
        ))

    planned = pre if pre is not None else _plan_new_config(
        existing_configs, work_state, qualification, ctx, now
    )
    # barrier(planned is None): Configuration 을 만들지 않는다 — 판정은 transient empty 로만.
    decision_config = planned if planned is not None else create_empty(
        ctx.work_id, ctx.template_application_id, now
    )
    if kind == SELECT:
        assert option_id is not None
        decision = decide_select(ctx, decision_config, slot_id, option_id, now)
    else:
        decision = decide_clear(ctx, decision_config, slot_id, now)

    # committed config: mutation 이 바꿨거나(new_config), 새로 plan 된 config 를 no-op 이어도 남긴다.
    # barrier(planned None)면 committed 는 None 으로 유지해 부재를 explicit-empty 로 물질화하지 않는다.
    committed_config = decision.new_config
    if committed_config is None and pre is None and planned is not None:
        committed_config = planned
    return _committed(committed_config, _record(
        context, request_id, fingerprint, decision.outcome_code, decision.changed,
        decision.source_version, decision.resulting_version, now,
    ))


def select_slot_option(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    *,
    context: ConfigurationCommandContext,
    request_id: str,
    slot_id: str,
    option_id: str,
    now: str,
) -> SlotCommandResult:
    with per_work_mutation_fence(
        context.workspace_instance_id, context.expected_work_authority_id
    ):
        return _mutate_under_fence(
            store, work_state, qualification, candidate, context, request_id,
            SELECT, slot_id, option_id, now,
        )


def clear_slot_selection(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    *,
    context: ConfigurationCommandContext,
    request_id: str,
    slot_id: str,
    now: str,
) -> SlotCommandResult:
    with per_work_mutation_fence(
        context.workspace_instance_id, context.expected_work_authority_id
    ):
        return _mutate_under_fence(
            store, work_state, qualification, candidate, context, request_id,
            CLEAR, slot_id, None, now,
        )


# ─── ensure / get ────────────────────────────────────────────────────────────────
def _ensure_under_fence(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    context: ConfigurationCommandContext,
    now: str,
) -> SlotCommandResult:
    work_id = context.expected_work_authority_id
    ws = context.workspace_instance_id
    stored = _load_existing(store, ws, work_id)  # 없으면 None(workspace guard 포함)
    ctx = _resolve_context(work_state, qualification, candidate, context)
    app = ctx.template_application_id
    pre = _current_config(stored, app) if stored else None
    if pre is not None:  # 이미 존재 → 무변경, storage 없음
        outcome = ConfigurationMutationOutcome(NO_CHANGE, False, app, pre.version, pre.version, False)
        return _result(store, work_state, qualification, candidate, context, outcome)
    existing_configs = stored.configurations.configurations if stored else ()
    config = _plan_new_config(existing_configs, work_state, qualification, ctx, now)
    if config is None:  # barrier → 생성 생략(부재 유지), storage 없음
        outcome = ConfigurationMutationOutcome(NO_CHANGE, False, app, None, None, False)
        return _result(store, work_state, qualification, candidate, context, outcome)
    _persist(store, ws, work_id, stored, config, None)  # ledger record 없음
    outcome = ConfigurationMutationOutcome(CHANGED, True, app, None, config.version, False)
    return _result(store, work_state, qualification, candidate, context, outcome)


def ensure_current_slot_configuration(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    *,
    context: ConfigurationCommandContext,
    now: str,
) -> SlotCommandResult:
    with per_work_mutation_fence(
        context.workspace_instance_id, context.expected_work_authority_id
    ):
        return _ensure_under_fence(
            store, work_state, qualification, candidate, context, now
        )


def get_current_slot_configuration(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    *,
    context: ConfigurationCommandContext,
) -> CurrentSlotConfigurationView:
    with per_work_mutation_fence(
        context.workspace_instance_id, context.expected_work_authority_id
    ):
        try:
            return _compute_view(store, work_state, qualification, candidate, context)
        except SlotConfigurationContextError as exc:
            # context error → partial fallback 없이 CONTEXT_ERROR projection(#678).
            # 소비자는 localized 메시지가 아니라 stable .code 로 분기한다(원문은 detail).
            return project_context_error(exc.code, str(exc))


# ─── capture (S5 입력 경계, S4-10 · #680) ────────────────────────────────────────
def _capture_under_fence(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    workspace_instance_id: str,
    expected_work_authority_id: str,
    expected_template_application_id: str,
    expected_configuration_presence: bool | None,
    expected_configuration_version: int | None,
    captured_at: str,
) -> SlotSelectionInput:
    # 단계 2·3: expected Application 을 exact 로 걸어 context 복원(mismatch → StaleTemplateApplication).
    context = resolve_slot_configuration_context(
        work_state, qualification, candidate,
        workspace_instance_id, expected_work_authority_id,
        expected_template_application_id,
    )
    # 단계 4: current Configuration read(ensure 하지 않는다 — capture 는 mutation 아님).
    # _load_existing 로 읽어 다른 workspace 의 aggregate 를 거절한다(WorkspaceIdentityMismatch).
    stored = _load_existing(store, workspace_instance_id, expected_work_authority_id)
    config = (
        _current_config(stored, context.template_application_id)
        if stored is not None
        else None
    )
    # 단계 5~8: 순수 presence/version CAS·resolution·slotless/complete 판정·immutable value.
    return plan_capture(
        context, config, captured_at,
        expected_configuration_presence=expected_configuration_presence,
        expected_configuration_version=expected_configuration_version,
    )


def capture_slot_selection_input(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    *,
    workspace_instance_id: str,
    expected_work_authority_id: str,
    expected_template_application_id: str,
    expected_configuration_presence: bool | None = None,
    expected_configuration_version: int | None = None,
    captured_at: str,
) -> SlotSelectionInput:
    """CaptureSlotSelectionInput — shared fence 아래 S5 입력을 immutable value 로 낸다(#680).

    Snapshot 을 current 권위로 저장하지 않는다. S5 가 자기 evidence/Plan 안에 보존한다.
    presence/version 은 caller 가 관찰한 Configuration 상태의 exact CAS 다(#681 token claims).
    """
    with per_work_mutation_fence(workspace_instance_id, expected_work_authority_id):
        return _capture_under_fence(
            store, work_state, qualification, candidate,
            workspace_instance_id, expected_work_authority_id,
            expected_template_application_id, expected_configuration_presence,
            expected_configuration_version, captured_at,
        )


# ─── slotless run bridge admission (S4-11 #681) ──────────────────────────────────
def admit_managed_slotless_run(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    candidate_bytes: CandidateObjectStorePort,
    provenance: ExecutionConfigurationProvenancePort,
    home: "str",
    *,
    workspace_instance_id: str,
    expected_work_authority_id: str,
    expected_template_application_id: str,
    expected_configuration_presence: bool | None = None,
    expected_configuration_version: int | None = None,
    captured_at: str,
) -> AdmittedSlotlessRun:
    """slotless legacy 실행 admission — shared fence 아래 exact context·bytes·provenance 를 고정한다.

    guard 순서(#681): route auth(caller) → fence → current Application + SlotSelectionInput capture →
    execution provenance read → exact current Application 대조 → exact Candidate bytes integrity →
    immutable run-plan input 고정 → fence release. 장기 generation 은 fence **밖**에서 이 고정값
    (staged_template_path)만 쓴다 — 이후 Apply 가 running run 의 bytes 를 갈아치우지 못한다.
    """
    with per_work_mutation_fence(workspace_instance_id, expected_work_authority_id):
        return _admit_slotless_run_under_fence(
            store, work_state, qualification, candidate, candidate_bytes, provenance,
            home, workspace_instance_id, expected_work_authority_id,
            expected_template_application_id, expected_configuration_presence,
            expected_configuration_version, captured_at,
        )


def _admit_slotless_run_under_fence(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    candidate_bytes: CandidateObjectStorePort,
    provenance: ExecutionConfigurationProvenancePort,
    home: str,
    workspace_instance_id: str,
    expected_work_authority_id: str,
    expected_template_application_id: str,
    expected_configuration_presence: bool | None,
    expected_configuration_version: int | None,
    captured_at: str,
) -> AdmittedSlotlessRun:
    # SlotSelectionInput capture(exact Application·version 검증 포함) — capture 와 같은 seam.
    selection_input = _capture_under_fence(
        store, work_state, qualification, candidate,
        workspace_instance_id, expected_work_authority_id,
        expected_template_application_id, expected_configuration_presence,
        expected_configuration_version, captured_at,
    )
    # exact applied Candidate bytes 참조(존재·digest 결속만; parse 0). 다른 Application → 무결성 오류.
    applied_input = resolve_exact_applied_template_input(
        work_state, qualification, candidate,
        expected_work_authority_id, expected_template_application_id,
    )
    # 전체 execution configuration provenance(기존 Job/Mapping 권위) — 없으면 UNKNOWN(None).
    base = provenance.resolve_base_template_application_id(expected_work_authority_id)
    return admit_slotless_run(
        selection_input, applied_input, base,
        lambda digest: stage_exact_applied_bytes(candidate_bytes, home, digest),
    )
