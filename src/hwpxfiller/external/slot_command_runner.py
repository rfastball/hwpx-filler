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
    command_fingerprint,
    decide_clear,
    decide_select,
)
from hwpxfiller.application.slot_configuration_context import (
    AppliedCandidateReadPort,
    QualificationReadPort,
    SlotConfigurationContext,
    StaleTemplateApplication,
    WorkTemplateStateReadPort,
    resolve_slot_configuration_context,
)
from hwpxfiller.application.slot_reconciliation import (
    ReconciliationApplication,
    SlotConfigurationResolution,
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
from hwpxfiller.domain.slot_selection import SlotSelectionSet
from hwpxfiller.host.per_work_fence import per_work_mutation_fence

from .work_configuration_store import WorkSlotConfigurationStore


@dataclass(frozen=True)
class CurrentSlotConfigurationView:
    """Get·Capture read seam — Projection DTO 조립은 #678·#679 가 맡는다."""

    context: SlotConfigurationContext
    configuration: WorkSlotConfigurationDraft | None
    resolution: SlotConfigurationResolution
    configuration_version: int | None


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


def _plan_new_config(
    stored: StoredWorkConfiguration,
    work_state: WorkTemplateStateReadPort,
    ctx: SlotConfigurationContext,
    now: str,
) -> WorkSlotConfigurationDraft | None:
    """current Application 의 Configuration 을 #676 plan 으로 만든다(없으면 None=생성 생략)."""
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
    configs = {
        c.base_template_application_id: c
        for c in stored.configurations.configurations
    }
    plan = plan_successor_reconciliation(
        ctx.template_application_id, ctx.template_structure,
        ctx.selection_semantic_contract, apps, configs,
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


def _load_or_create(store: WorkSlotConfigurationStore, ws: str, work_id: str) -> StoredWorkConfiguration:
    if not store.exists(work_id):
        store.create(empty_stored(ws, work_id))  # ledger-only create
    return store.load(work_id)


def _commit(
    store: WorkSlotConfigurationStore,
    stored: StoredWorkConfiguration,
    config: WorkSlotConfigurationDraft | None,
    record: IdempotencyRecord,
) -> None:
    """Configuration(있으면) + first-seen record 를 한 aggregate commit 으로 쓴다."""
    aggregate = _put_config(stored.configurations, config) if config else stored.configurations
    new_stored = replace(
        stored,
        configurations=aggregate,
        processed_requests=stored.processed_requests + (record,),
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
) -> ConfigurationMutationOutcome:
    if context.expected_work_authority_id != context.token_work_authority_id:
        raise CrossWorkConfigurationToken("route Work 와 token Work 가 다르다")
    work_id = context.expected_work_authority_id
    fingerprint = command_fingerprint(kind, context, slot_id, option_id)
    stored = _load_or_create(store, context.workspace_instance_id, work_id)

    existing = find_request(stored, request_id)
    if existing is not None:  # replay 는 context decoder 없이 최초 outcome 재생
        if (
            existing.command_fingerprint == fingerprint
            and existing.fingerprint_schema_version == FINGERPRINT_SCHEMA_VERSION
        ):
            return _replay_outcome(existing)
        raise IdempotencyKeyReused(
            f"request {request_id} 가 다른 fingerprint 로 재사용됨"
        )

    try:
        ctx = _resolve_context(work_state, qualification, candidate, context)
    except StaleTemplateApplication:
        rec = _record(
            context, request_id, fingerprint, STALE_TEMPLATE_APPLICATION, False,
            context.token_configuration_version, context.token_configuration_version, now,
        )
        _commit(store, stored, None, rec)
        return _outcome(rec)

    if ctx.selection_semantic_contract_id != context.token_selection_contract_id:
        raise ConfigurationContextClaimMismatch("token contract claim 이 current 와 다르다")

    pre = _current_config(stored, ctx.template_application_id)
    if not _config_version_cas(context, pre):
        rec = _record(
            context, request_id, fingerprint, STALE_CONFIGURATION, False,
            pre.version if pre else None, pre.version if pre else None, now,
        )
        _commit(store, stored, None, rec)
        return _outcome(rec)

    config = pre if pre is not None else _plan_new_config(stored, work_state, ctx, now)
    if config is None:  # slotless barrier — 만들 Configuration 이 없다
        config = create_empty(ctx.work_id, ctx.template_application_id, now)

    if kind == SELECT:
        assert option_id is not None
        decision = decide_select(ctx, config, slot_id, option_id, now)
    else:
        decision = decide_clear(ctx, config, slot_id, now)

    committed_config = decision.new_config
    # config 가 새로 ensure 됐는데 mutation 이 no-op 이면 그 신규 config 도 남긴다.
    if committed_config is None and pre is None:
        committed_config = config
    rec = _record(
        context, request_id, fingerprint, decision.outcome_code, decision.changed,
        decision.source_version, decision.resulting_version, now,
    )
    _commit(store, stored, committed_config, rec)
    return _outcome(rec)


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
) -> ConfigurationMutationOutcome:
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
) -> ConfigurationMutationOutcome:
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
) -> ConfigurationMutationOutcome:
    work_id = context.expected_work_authority_id
    stored = _load_or_create(store, context.workspace_instance_id, work_id)
    ctx = _resolve_context(work_state, qualification, candidate, context)
    pre = _current_config(stored, ctx.template_application_id)
    if pre is not None:  # 이미 존재 → 무변경
        return ConfigurationMutationOutcome(
            NO_CHANGE, False, ctx.template_application_id, pre.version, pre.version, False
        )
    config = _plan_new_config(stored, work_state, ctx, now)
    if config is None:  # slotless + source 없음/empty barrier → 생성 생략
        return ConfigurationMutationOutcome(
            NO_CHANGE, False, ctx.template_application_id, None, None, False
        )
    new_stored = replace(
        stored,
        configurations=_put_config(stored.configurations, config),
        aggregate_version=stored.aggregate_version + 1,
    )
    store.update(work_id, stored.aggregate_version, lambda _cur: new_stored)
    return ConfigurationMutationOutcome(
        CHANGED, True, ctx.template_application_id, None, config.version, False
    )


def ensure_current_slot_configuration(
    store: WorkSlotConfigurationStore,
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    *,
    context: ConfigurationCommandContext,
    now: str,
) -> ConfigurationMutationOutcome:
    with per_work_mutation_fence(
        context.workspace_instance_id, context.expected_work_authority_id
    ):
        return _ensure_under_fence(
            store, work_state, qualification, candidate, context, now
        )


def _get_under_fence(
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
    return CurrentSlotConfigurationView(
        ctx, config, resolution, config.version if config else None
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
        return _get_under_fence(store, work_state, qualification, candidate, context)
