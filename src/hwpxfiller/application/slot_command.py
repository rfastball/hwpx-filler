"""S4 Slot Configuration command 의 pure 계약 — verified claims·fingerprint·판정 (S4-07 · #677).

이 모듈은 store·fence·crypto token·IO 를 모른다. outer Product boundary 가 이미 token 을 열고
route binding·authorization 을 확인해 넘긴 :class:`ConfigurationCommandContext`(verified claims)만
소비한다. fence 획득·store commit 결선은 ``external/slot_command_runner.py`` 가 진다.

fingerprint 는 token ciphertext·nonce·key_id·issued_at 에 의존하지 않는다 — 검증된 semantic
claims 와 command payload 를 versioned canonical encoding 으로 계산한다. 같은 claims 를 새 token
으로 다시 봉인해도 fingerprint 는 같다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from hwpxfiller.application.slot_configuration_context import SlotConfigurationContext
from hwpxfiller.application.work_slot_configuration import (
    WorkSlotConfigurationDraft,
    apply_selections,
)
from hwpxfiller.domain.slot_selection import (
    EXACTLY_ONE,
    SlotSelection,
    SlotSelectionSet,
    resolve_selection_policy,
)

FINGERPRINT_SCHEMA_VERSION = "slot-configuration-command-fingerprint/v1"
_MAGIC = b"HFPCMD1\0"  # exact 8 bytes
_U32_MAX = 0xFFFF_FFFF

# command kinds.
SELECT = "SELECT"
CLEAR = "CLEAR"

# terminal ledger outcome codes.
CHANGED = "CHANGED"
NO_CHANGE = "NO_CHANGE"
STALE_TEMPLATE_APPLICATION = "STALE_TEMPLATE_APPLICATION"
STALE_CONFIGURATION = "STALE_CONFIGURATION"
UNKNOWN_SLOT = "UNKNOWN_SLOT"
UNKNOWN_OPTION = "UNKNOWN_OPTION"
NO_AVAILABLE_OPTIONS = "NO_AVAILABLE_OPTIONS"
CARDINALITY_VIOLATION = "CARDINALITY_VIOLATION"
UNSUPPORTED_SELECTION_POLICY = "UNSUPPORTED_SELECTION_POLICY"
SLOT_CONFIGURATION_NOT_APPLICABLE = "SLOT_CONFIGURATION_NOT_APPLICABLE"


class SlotCommandError(Exception):
    """저장하지 않는 command 실패(token·cross-work·authorization·integrity)."""


class CrossWorkConfigurationToken(SlotCommandError):
    pass


class ConfigurationContextClaimMismatch(SlotCommandError):
    pass


class WorkspaceIdentityMismatch(SlotCommandError):
    """저장된 aggregate 의 workspace 와 context workspace 가 다르다(cross-workspace 재사용)."""


@dataclass(frozen=True)
class ConfigurationCommandContext:
    """outer boundary 가 token 을 열고 검증해 넘긴 claims — 이 층은 다시 열지 않는다."""

    workspace_instance_id: str
    expected_work_authority_id: str  # route-bound
    token_work_authority_id: str
    token_template_application_id: str
    token_selection_contract_id: str
    token_configuration_presence: bool
    token_configuration_version: int | None
    actor_binding_digest: str


@dataclass(frozen=True)
class ConfigurationMutationOutcome:
    outcome_code: str
    changed: bool
    application_id: str
    source_configuration_version: int | None
    resulting_configuration_version: int | None
    outcome_replayed: bool


# ─── versioned command fingerprint ──────────────────────────────────────────────
def _text(value: str) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > _U32_MAX:
        raise SlotCommandError("fingerprint text 가 u32 범위 초과")
    return len(raw).to_bytes(4, "big") + raw


def _opt_text(value: str | None) -> bytes:
    if value is None:
        return b"\x00"
    return b"\x01" + _text(value)


def _opt_u32(value: int | None) -> bytes:
    if value is None:
        return b"\x00"
    if value < 0 or value > _U32_MAX:
        raise SlotCommandError("fingerprint u32 값이 범위 초과")
    return b"\x01" + value.to_bytes(4, "big")


def command_fingerprint(
    kind: str,
    context: ConfigurationCommandContext,
    slot_id: str,
    option_id: str | None,
) -> str:
    """slot-configuration-command-fingerprint/v1 digest.

    optional ``option_id`` 는 SELECT 에서 option, CLEAR 에서 None(clear marker)이다 —
    presence tag 로 구별해 어떤 option ID 와도 충돌하지 않는다.
    """
    out = bytearray()
    out += _MAGIC
    out += _text(FINGERPRINT_SCHEMA_VERSION)
    out += _text(kind)
    out += _text(context.workspace_instance_id)
    out += _text(context.expected_work_authority_id)
    out += _text(context.token_work_authority_id)
    out += _text(context.token_template_application_id)
    out += b"\x01" if context.token_configuration_presence else b"\x00"
    out += _opt_u32(context.token_configuration_version)
    out += _text(context.token_selection_contract_id)
    out += _text(slot_id)
    out += _opt_text(option_id)
    out += _text(context.actor_binding_digest)
    return "sha256:" + hashlib.sha256(bytes(out)).hexdigest()


# ─── pure decision ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Decision:
    outcome_code: str
    changed: bool
    new_config: WorkSlotConfigurationDraft | None  # None → configuration 무변경
    source_version: int
    resulting_version: int


def _slot_by_id(context_structure, slot_id: str):
    return next((s for s in context_structure.slots if s.id == slot_id), None)


def _declared_option_ids(config: WorkSlotConfigurationDraft, slot_id: str) -> tuple[str, ...]:
    for entry in config.selections.selections:
        if entry.slot_id == slot_id:
            return entry.selected_option_ids
    return ()


def _with_slot(
    selections: SlotSelectionSet, slot_id: str, option_ids: tuple[str, ...]
) -> SlotSelectionSet:
    """slot_id entry 를 option_ids 로 교체(빈 tuple 이면 제거)."""
    kept = tuple(e for e in selections.selections if e.slot_id != slot_id)
    if option_ids:
        kept = kept + (SlotSelection(slot_id, option_ids),)
    return SlotSelectionSet(kept)


def decide_select(
    ctx: SlotConfigurationContext,
    config: WorkSlotConfigurationDraft,
    slot_id: str,
    option_id: str,
    now: str,
) -> _Decision:
    """Select-one 판정 — validation gate 를 통과하면 slot 선택을 option 하나로 replace."""
    src = config.version
    slot = _slot_by_id(ctx.template_structure, slot_id)
    if slot is None:
        return _Decision(UNKNOWN_SLOT, False, None, src, src)
    # Select-one 은 EXACTLY_ONE 만 다룬다 — 다른 정책(향후 MANY 등)은 이 command 미지원.
    if resolve_selection_policy(ctx.selection_semantic_contract, None) != EXACTLY_ONE:
        return _Decision(UNSUPPORTED_SELECTION_POLICY, False, None, src, src)
    available = tuple(o.id for o in slot.options)
    if len(available) == 0:
        return _Decision(NO_AVAILABLE_OPTIONS, False, None, src, src)
    if option_id not in available:
        return _Decision(UNKNOWN_OPTION, False, None, src, src)
    new_config = apply_selections(config, _with_slot(config.selections, slot_id, (option_id,)), now)
    changed = new_config.version != src
    return _Decision(
        CHANGED if changed else NO_CHANGE, changed,
        new_config if changed else None, src, new_config.version,
    )


def decide_clear(
    ctx: SlotConfigurationContext,
    config: WorkSlotConfigurationDraft,
    slot_id: str,
    now: str,
) -> _Decision:
    """Clear 판정 — current Structure 에 slot 이 있거나 Config 에 entry 가 있어야 유효 target."""
    src = config.version
    slot_in_structure = _slot_by_id(ctx.template_structure, slot_id) is not None
    has_entry = _declared_option_ids(config, slot_id) != ()
    if not slot_in_structure and not has_entry:
        return _Decision(UNKNOWN_SLOT, False, None, src, src)
    if not has_entry:
        return _Decision(NO_CHANGE, False, None, src, src)  # entry 없음 → no-op
    new_config = apply_selections(config, _with_slot(config.selections, slot_id, ()), now)
    changed = new_config.version != src
    return _Decision(
        CHANGED if changed else NO_CHANGE, changed,
        new_config if changed else None, src, new_config.version,
    )


# CARDINALITY_VIOLATION·SLOT_CONFIGURATION_NOT_APPLICABLE 은 ledger terminal 어휘로 등재만
# 한다 — v1 Select-one·Clear 는 단일 option 만 다뤄 이 코드로 귀결되지 않는다(향후 MANY 용).
