"""same-ID 선택을 compatibility-aware 로 판정하는 순수 모듈 (SG-01 · #733).

canonical identity(`kind + id`)는 그대로 둔다. 이 모듈은 identity equality 와 selection
compatibility 를 분리한다: 같은 Slot/Option id 라는 이유만으로 이전 Application 의 선택을
자동 승계하지 않고, exact historical structure evidence 에서 **의미 동일성이 증명될 때만**
`AUTO_KEEP` 한다. 증명 못 하면 `REVIEW_REQUIRED`(사용자 재선택), target 에 없으면 `DETACHED`.

fail-closed 계약: false `REVIEW_REQUIRED` 는 허용, false `AUTO_KEEP` 는 금지. evidence 가
unknown/missing/v1 이면 fingerprint 가 None → `REVIEW_REQUIRED`(절대 `AUTO_KEEP` 아님).

fingerprint 는 **RELATIVE/intrinsic fact 만** 쓴다(span_length·relative_order·resolver/removal
contract id·envelope fact). 절대 order·다른 Slot·revision·timestamp·경로·store 위치는 제외 —
무관한 Slot 의 변경이 이 Option 의 fingerprint 를 흔들지 않게 한다.

새 durable authority 가 아니다: :class:`SelectionCompatibilityFacts` 는 reconciliation 마다
exact evidence 에서 파생하고 저장하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from hwpxfiller.application.execution_structure import (
    ExecutionTemplateStructure,
)

# ─── 판정 어휘 ───────────────────────────────────────────────────────────────────
AUTO_KEEP = "AUTO_KEEP"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
DETACHED = "DETACHED"

# 사유(판정의 근거 — UI 문구·감사용).
PRESENT_MATCH = "PRESENT_MATCH"  # AUTO_KEEP
FINGERPRINT_CHANGED = "FINGERPRINT_CHANGED"  # REVIEW
REMOVED_IN_CHAIN = "REMOVED_IN_CHAIN"  # REVIEW (removed 뒤 same id 재등장)
EVIDENCE_MISSING = "EVIDENCE_MISSING"  # REVIEW (unknown/v1/missing evidence)
POLICY_CHANGED = "POLICY_CHANGED"  # REVIEW (contract·policy 변경)
DETACHED_ABSENT = "DETACHED_ABSENT"  # DETACHED (target 에 없음)

FINGERPRINT_SCHEMA = "selection-compatibility-fingerprint/v1"


@dataclass(frozen=True)
class SelectionCompatibilityFacts:
    slot_id: str
    option_id: str
    classification: str
    source_fingerprint: str | None
    target_fingerprint: str | None
    reason: str


@dataclass(frozen=True)
class ChainApplicationFacts:
    """한 Application 의 compatibility 판정 입력 — 전부 fail-closed(None) 가능.

    evidence 가 v1/missing/integrity-fail 이면 셋 다 None 이고, 그 hop 은 판정에서
    evidence-missing 으로 취급돼 `AUTO_KEEP` 가 되지 못한다.
    """

    execution_structure: ExecutionTemplateStructure | None
    selection_contract_id: str | None
    selection_policy: str | None


def _option_present(structure: ExecutionTemplateStructure, slot_id: str, option_id: str) -> bool:
    for slot in structure.product_structure.slots:
        if slot.id == slot_id:
            return any(opt.id == option_id for opt in slot.options)
    return False


def option_compatibility_fingerprint(
    structure: ExecutionTemplateStructure, slot_id: str, option_id: str
) -> str | None:
    """(slot, option) 의 RELATIVE/intrinsic fingerprint. region 부재 시 None(removed/absent).

    같은 의미(같은 region 폭·내부 배치·resolver/removal contract·envelope)면 절대 위치가
    달라도 같은 fingerprint. 무관한 Slot 이 앞에 끼어 절대 order 가 밀려도 안 바뀐다.
    """
    region = next(
        (r for r in structure.option_regions if r.slot_id == slot_id and r.option_id == option_id),
        None,
    )
    if region is None:
        return None
    entries = {e.content_entry_id: e for e in structure.content_entries}
    region_entry = entries.get(region.content_entry_id)

    owner_coincidence = next(
        (
            f.get("coincidence")
            for f in region.owner_relation_facts
            if f.get("relation") == "target_owner_slot"
        ),
        None,
    )

    owned = sorted(
        (
            occ
            for occ in structure.field_occurrences
            if occ.owner_kind == "OPTION"
            and occ.owner_slot_id == slot_id
            and occ.owner_option_id == option_id
        ),
        key=lambda o: (o.field_id, o.occurrence_ordinal),
    )
    owned_fields = [
        {
            "field_id": occ.field_id,
            "occurrence_ordinal": occ.occurrence_ordinal,
            # relative_order: 절대 structural_order 를 region 시작 기준 상대값으로 — 무관한
            # Slot 변경으로 절대 order 가 밀려도 안 흔들린다.
            "relative_order": occ.structural_order - region.begin_order,
            "native_value_target_class": occ.native_value_target_class,
            "resolver_contract_id": occ.resolver_contract_id,
            "envelope_class": (
                entries[occ.content_entry_id].envelope_class
                if occ.content_entry_id in entries
                else None
            ),
        }
        for occ in owned
    ]

    payload = {
        "schema": FINGERPRINT_SCHEMA,
        "region": {
            "span_length": region.end_order - region.begin_order,
            "owner_coincidence": owner_coincidence,
            "removal_capability_ref": region.removal_capability_ref,
            "envelope_class": region_entry.envelope_class if region_entry else None,
            "envelope_capability_facts": (
                dict(sorted(region_entry.envelope_capability_facts.items()))
                if region_entry
                else None
            ),
        },
        "owned_fields": owned_fields,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def classify_selection(
    slot_id: str,
    option_id: str,
    chain_execution_structures: Sequence[ExecutionTemplateStructure | None],
    *,
    source_contract_id: str | None,
    target_contract_id: str,
    source_policy: str | None,
    target_policy: str,
) -> SelectionCompatibilityFacts:
    """source..target chain 을 걸어 한 (slot, option) 선택의 compatibility 를 판정한다.

    ``chain_execution_structures`` 는 source 부터 target 까지 순서대로다(양끝 포함). 모든 hop 이
    present-and-identical 일 때만 AUTO_KEEP — 중간 hop 에서 removed(fingerprint None)면 같은 id
    재등장이라도 REVIEW_REQUIRED 다(false AUTO_KEEP 금지).
    """
    target = chain_execution_structures[-1] if chain_execution_structures else None
    source = chain_execution_structures[0] if chain_execution_structures else None
    source_fp = (
        option_compatibility_fingerprint(source, slot_id, option_id) if source is not None else None
    )

    def facts(classification: str, reason: str, target_fp: str | None) -> SelectionCompatibilityFacts:
        return SelectionCompatibilityFacts(
            slot_id=slot_id,
            option_id=option_id,
            classification=classification,
            source_fingerprint=source_fp,
            target_fingerprint=target_fp,
            reason=reason,
        )

    if target is None:
        return facts(REVIEW_REQUIRED, EVIDENCE_MISSING, None)
    if not _option_present(target, slot_id, option_id):
        return facts(DETACHED, DETACHED_ABSENT, None)

    target_fp = option_compatibility_fingerprint(target, slot_id, option_id)
    if target_fp is None:  # present 인데 region 부재 = evidence 불완전(방어).
        return facts(REVIEW_REQUIRED, EVIDENCE_MISSING, None)

    if source_contract_id != target_contract_id or source_policy != target_policy:
        return facts(REVIEW_REQUIRED, POLICY_CHANGED, target_fp)

    for structure in chain_execution_structures:
        if structure is None:
            return facts(REVIEW_REQUIRED, EVIDENCE_MISSING, target_fp)
        hop_fp = option_compatibility_fingerprint(structure, slot_id, option_id)
        if hop_fp is None:
            return facts(REVIEW_REQUIRED, REMOVED_IN_CHAIN, target_fp)
        if hop_fp != target_fp:
            return facts(REVIEW_REQUIRED, FINGERPRINT_CHANGED, target_fp)

    return facts(AUTO_KEEP, PRESENT_MATCH, target_fp)
