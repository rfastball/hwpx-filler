"""composition theorem evidence + pure runtime premise verifier (S5-04 · #700).

S5-03(:mod:`hwpxfiller.application.execution_structure`)은 exact structural fact 를 낸다 —
occurrence·option region·target-target/target-owner/target-retained relation·envelope·
resolver fact. 이 slice 는 그 fact 의 **admission 의미** 를 소유한다: 어떤 relation 이
deterministic ordered ``RemoveOption`` composition 에서 안전한지 판정하고, C1~C10 premise 를
exact projection fact 만으로 증명한다.

경계(issue #700):
- **native mutation 0**. verifier 는 ``ExecutionTemplateStructure`` DTO 와 contract 만 읽는다.
  HWPX clone/parse/serialize/remove·writer·sequence simulation·post-mutation inspection 을
  절대 호출하지 않는다(그래서 이 모듈은 hwpxcore/native 를 import 하지 않는다).
- **fail-closed**. 증명 안 된 composition 은 PASS 하지 않는다. fact 누락/모순은 latest 로
  fallback 하지 않고 issue 가 열거한 error code 로 시끄럽게 닫힌다.
- **semantic vs current 분리**. theorem evidence(반영구 semantic)와 runtime materializer
  conformance(current admission)는 서로 다른 identity 다 — premise digest 에 runtime 을 섞지
  않는다.

digest seam: byte framing·SHA-256 은 S5-06 소유. 여기서는 semantic payload + stable ordering
만 고정하고 :func:`content_digest`(canonical JSON sha256)로 주소화한다
(# ponytail: 로컬 canonical dict 인코더 재사용, S5-06 이 closed byte framing 으로 대체).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hwpxfiller.application.execution_structure import (
    CONTAINED,
    CONTAINS,
    CROSSING,
    DISJOINT,
    OWNER_OPTION,
    OWNER_ROOT,
    OWNER_SLOT_SHARED,
    SAME_SPAN,
    TOUCHING,
    COINCIDE_INTERIOR,
    COINCIDE_SAME_END,
    COINCIDE_SAME_SPAN,
    COINCIDE_SAME_START,
    POSITION_INSIDE,
    ExecutionTemplateStructure,
)
from hwpxfiller.application.qualification_evidence import content_digest

# ─── contract identity(의미가 바뀌면 새 ID — 같은 ID 의미 수정 금지) ───────────────────
COMPOSITION_CONTRACT_ID = "hwpx-composition/v1"
COMPOSITION_PREMISE_SCHEMA = "hwpx-composition-premises/v1"
COMPOSITION_PREMISE_VERIFIER_VERSION = "hwpx-composition-verifier/v1"
NATIVE_PRIMITIVE_CONTRACT_ID = "hwpx-native-primitive/v1"
PRIMITIVE_SEMANTICS_VERSION = "1"

# 결과 status.
PASS = "PASS"

# premise id — issue C1~C10.
PREMISE_IDS = (
    "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10",
)

# per-premise 평가 status.
OK = "OK"
FAILED = "FAILED"  # fact 가 있고 unsafe → 증명 불가(Blocked)
INCOMPLETE = "INCOMPLETE"  # 필요한 fact 부재/모순 → 평가 불가(ContextError)


# ─── 오류 code(issue 열거 그대로) ──────────────────────────────────────────────────
class CompositionAdmissionError(ValueError):
    """S5-04 admission·verification 오류의 뿌리."""

    code = "EXECUTION_COMPOSITION_ERROR"


class UnsupportedCompositionContract(CompositionAdmissionError):
    code = "UNSUPPORTED_COMPOSITION_CONTRACT"


class UnsupportedNativePrimitiveContract(CompositionAdmissionError):
    code = "UNSUPPORTED_NATIVE_PRIMITIVE_CONTRACT"


class CompositionTheoremEvidenceIntegrityError(CompositionAdmissionError):
    code = "COMPOSITION_THEOREM_EVIDENCE_INTEGRITY_ERROR"


class CompositionTheoremEvidenceUnproven(CompositionAdmissionError):
    code = "EXECUTION_COMPOSITION_CONTRACT_UNPROVEN"


class RuntimeMaterializerConformanceNotAdmitted(CompositionAdmissionError):
    code = "RUNTIME_MATERIALIZER_CONFORMANCE_NOT_ADMITTED"


# ─── target-target admission policy(S5-04 가 소유하는 의미) ─────────────────────────
# v1 admission tier. DISJOINT 는 무조건, TOUCHING 은 exact theorem 이 있을 때만, 나머지는 항상 거절.
_UNCONDITIONAL_TARGET_TARGET = frozenset({DISJOINT})
_THEOREM_GATED_TARGET_TARGET = frozenset({TOUCHING})
_REJECTED_TARGET_TARGET = frozenset({CONTAINS, CONTAINED, SAME_SPAN, CROSSING})
_KNOWN_TARGET_TARGET = (
    _UNCONDITIONAL_TARGET_TARGET | _THEOREM_GATED_TARGET_TARGET | _REJECTED_TARGET_TARGET
)


def classify_target_target_admission(relation: str, *, touching_theorem_available: bool) -> str:
    """distinct RemoveOption target pair 하나의 admission 판정(pure policy).

    반환: ``OK``(admitted) · ``FAILED``(거절/미증명) · ``INCOMPLETE``(미지 relation 어휘).
    DISJOINT 는 항상 admitted, TOUCHING 은 exact primitive theorem 이 있을 때만, CONTAINS/
    CONTAINED/SAME_SPAN/CROSSING 은 항상 거절이다. 두 distinct Option 이 같은 region 을
    가리키면(SAME_SPAN) compiler 가 축약하지 않고 seal 을 차단한다.
    """
    if relation in _UNCONDITIONAL_TARGET_TARGET:
        return OK
    if relation in _THEOREM_GATED_TARGET_TARGET:
        return OK if touching_theorem_available else FAILED
    if relation in _REJECTED_TARGET_TARGET:
        return FAILED
    return INCOMPLETE


# ─── target-owner admission policy(target-target 와 혼동 0) ─────────────────────────
_OWNER_COINCIDENT = frozenset(
    {COINCIDE_SAME_SPAN, COINCIDE_SAME_START, COINCIDE_SAME_END}
)


def is_owner_coincidence_admitted(
    coincidence: str,
    *,
    preserves_owner_marker: bool,
    coincident_boundary_admissible: bool,
    coincidence_theorem_available: bool,
) -> str:
    """owning Slot/content-entry envelope 와 target 의 boundary 일치 admission.

    INTERIOR(owner 가 target 을 strictly 포함)는 무조건 OK. same-start/end/span 은 current
    remover 가 owner marker·content-entry envelope 를 보존한다는 exact capability fact 와
    theorem evidence 가 **모두** 있을 때만 admitted 다.
    """
    if coincidence == COINCIDE_INTERIOR:
        return OK
    if coincidence not in _OWNER_COINCIDENT:
        return INCOMPLETE
    if not preserves_owner_marker or not coincident_boundary_admissible:
        return FAILED
    return OK if coincidence_theorem_available else FAILED


# ─── native-primitive-contract/v1 semantic manifest ─────────────────────────────────
@dataclass(frozen=True)
class NativePrimitiveContractManifest:
    """remover·resolver·writer 의 추상 동작을 결속하는 semantic manifest.

    shipping 구현 binary/package version 을 pin 하지 않는다 — 같은 ID 의 의미 수정은 금지,
    새 primitive 의미는 새 ID 다.
    """

    native_primitive_contract_id: str
    option_resolver_contract_id: str
    option_removal_contract_id: str
    field_resolver_contract_id: str
    field_write_contract_id: str
    envelope_postcondition_contract_id: str
    intentional_blank_write_contract_id: str
    primitive_semantics_version: str


NATIVE_PRIMITIVE_CONTRACT_V1 = NativePrimitiveContractManifest(
    native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
    option_resolver_contract_id="hwpx-option-resolver/v1",
    option_removal_contract_id="remove-option/v1",  # OptionRegion.removal_capability_ref 와 결속
    field_resolver_contract_id="hwpx-field-resolver/v1",  # FieldOccurrence.resolver_contract_id 와 결속
    field_write_contract_id="hwpx-field-write/v1",
    envelope_postcondition_contract_id="hwpx-envelope-postcondition/v1",
    intentional_blank_write_contract_id="hwpx-intentional-blank/v1",
    primitive_semantics_version=PRIMITIVE_SEMANTICS_VERSION,
)


def encode_native_primitive_contract(m: NativePrimitiveContractManifest) -> dict[str, Any]:
    return {
        "native_primitive_contract_id": m.native_primitive_contract_id,
        "option_resolver_contract_id": m.option_resolver_contract_id,
        "option_removal_contract_id": m.option_removal_contract_id,
        "field_resolver_contract_id": m.field_resolver_contract_id,
        "field_write_contract_id": m.field_write_contract_id,
        "envelope_postcondition_contract_id": m.envelope_postcondition_contract_id,
        "intentional_blank_write_contract_id": m.intentional_blank_write_contract_id,
        "primitive_semantics_version": m.primitive_semantics_version,
    }


# ─── theorem/counterexample fixture corpus(admitted ↔ counterexample 분리) ──────────
# admitted corpus: theorem 이 참이어야 하는 최소 positive 표본.
POSITIVE_THEOREM_FIXTURES: tuple[Mapping[str, Any], ...] = (
    {"id": "content-entry-options-only", "family": "envelope", "admitted": True},
    {"id": "selected-option-region-empty", "family": "envelope", "admitted": True},
    {"id": "multiple-slots-same-content-entry", "family": "layout", "admitted": True},
    {"id": "owner-target-same-start", "family": "target_owner", "admitted": True},
    {"id": "owner-target-same-end", "family": "target_owner", "admitted": True},
    {"id": "owner-target-same-span", "family": "target_owner", "admitted": True},
    {"id": "distinct-target-disjoint", "family": "target_target", "relation": DISJOINT,
     "admitted": True},
    {"id": "distinct-target-touching", "family": "target_target", "relation": TOUCHING,
     "admitted": True},
    {"id": "unselected-option-envelope", "family": "envelope", "admitted": True},
    {"id": "remove-option-active-field-parity", "family": "resolver", "admitted": True},
    {"id": "multi-field-write-remaining-parity", "family": "resolver", "admitted": True},
    {"id": "intentional-blank-write-parity", "family": "resolver", "admitted": True},
)

# counterexample corpus: 반드시 거절해야 하는 표본(admitted=False).
COUNTEREXAMPLE_THEOREM_FIXTURES: tuple[Mapping[str, Any], ...] = (
    {"id": "distinct-target-contains", "family": "target_target", "relation": CONTAINS,
     "admitted": False},
    {"id": "distinct-target-contained", "family": "target_target", "relation": CONTAINED,
     "admitted": False},
    {"id": "distinct-target-same-span", "family": "target_target", "relation": SAME_SPAN,
     "admitted": False},
    {"id": "distinct-target-crossing", "family": "target_target", "relation": CROSSING,
     "admitted": False},
    {"id": "retained-content-inside-target", "family": "target_retained", "admitted": False},
    {"id": "s2-global-native-admission", "family": "global", "admitted": False},
)

# theorem 이 exact 하게 attest 하는 target-target relation(positive corpus 에서 유도).
_ATTESTED_TARGET_TARGET_RELATIONS = frozenset(
    f["relation"]
    for f in POSITIVE_THEOREM_FIXTURES
    if f.get("family") == "target_target"
)


def fixture_manifest_digest(fixtures: tuple[Mapping[str, Any], ...]) -> str:
    """fixture corpus 의 content-address(id 정렬로 저장 순서 ≠ identity)."""
    return content_digest(sorted((dict(f) for f in fixtures), key=lambda f: f["id"]))


# ─── CompositionTheoremEvidenceManifest ─────────────────────────────────────────────
@dataclass(frozen=True)
class CompositionTheoremEvidenceManifest:
    """exact composition/native primitive contract 에 결속된 immutable theorem evidence.

    theorem evidence 는 S6 runtime implementation conformance 와 다르다 — 이 manifest 는
    semantic 증명이고 runtime PASS 가 아니다.
    """

    composition_contract_id: str
    premise_schema_version: str
    native_primitive_contract_id: str
    premise_verifier_version: str
    theorem_test_suite_digest: str
    counterexample_fixture_manifest_digest: str
    evidence_status: str


def theorem_evidence_digest(m: CompositionTheoremEvidenceManifest) -> str:
    return content_digest(
        {
            "composition_contract_id": m.composition_contract_id,
            "premise_schema_version": m.premise_schema_version,
            "native_primitive_contract_id": m.native_primitive_contract_id,
            "premise_verifier_version": m.premise_verifier_version,
            "theorem_test_suite_digest": m.theorem_test_suite_digest,
            "counterexample_fixture_manifest_digest": m.counterexample_fixture_manifest_digest,
            "evidence_status": m.evidence_status,
        }
    )


THEOREM_EVIDENCE_V1 = CompositionTheoremEvidenceManifest(
    composition_contract_id=COMPOSITION_CONTRACT_ID,
    premise_schema_version=COMPOSITION_PREMISE_SCHEMA,
    native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
    premise_verifier_version=COMPOSITION_PREMISE_VERIFIER_VERSION,
    theorem_test_suite_digest=fixture_manifest_digest(POSITIVE_THEOREM_FIXTURES),
    counterexample_fixture_manifest_digest=fixture_manifest_digest(
        COUNTEREXAMPLE_THEOREM_FIXTURES
    ),
    evidence_status=PASS,
)


class TheoremEvidenceRegistry:
    """(composition, native primitive) → canonical theorem evidence. append-only·no fallback."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], CompositionTheoremEvidenceManifest] = {}

    def register(self, manifest: CompositionTheoremEvidenceManifest) -> None:
        key = (manifest.composition_contract_id, manifest.native_primitive_contract_id)
        existing = self._by_key.get(key)
        if existing is not None and existing != manifest:
            # historical manifest 를 latest 로 덮지 않는다.
            raise CompositionTheoremEvidenceIntegrityError(
                f"theorem evidence {key} 는 이미 등록됨 — historical 대체 금지"
            )
        self._by_key[key] = manifest

    def resolve(
        self, composition_contract_id: str, native_primitive_contract_id: str
    ) -> CompositionTheoremEvidenceManifest:
        key = (composition_contract_id, native_primitive_contract_id)
        manifest = self._by_key.get(key)
        if manifest is None:
            raise UnsupportedCompositionContract(
                f"등록되지 않은 theorem evidence(latest fallback 없음): {key}"
            )
        return manifest


DEFAULT_THEOREM_EVIDENCE_REGISTRY = TheoremEvidenceRegistry()
DEFAULT_THEOREM_EVIDENCE_REGISTRY.register(THEOREM_EVIDENCE_V1)


def verify_theorem_evidence_integrity(
    manifest: CompositionTheoremEvidenceManifest,
    *,
    registry: TheoremEvidenceRegistry = DEFAULT_THEOREM_EVIDENCE_REGISTRY,
) -> None:
    """theorem evidence 가 등록된 canonical 과 정합하고 PASS 임을 강제(fail-closed).

    status != PASS → unproven, fixture/test digest tamper 나 registered 와 불일치 → integrity
    error. unknown contract 는 resolve 에서 latest fallback 없이 닫힌다.
    """
    if manifest.composition_contract_id != COMPOSITION_CONTRACT_ID:
        raise UnsupportedCompositionContract(
            f"미지원 composition contract: {manifest.composition_contract_id!r}"
        )
    if manifest.native_primitive_contract_id != NATIVE_PRIMITIVE_CONTRACT_ID:
        raise UnsupportedNativePrimitiveContract(
            f"미지원 native primitive contract: {manifest.native_primitive_contract_id!r}"
        )
    registered = registry.resolve(
        manifest.composition_contract_id, manifest.native_primitive_contract_id
    )
    if manifest.evidence_status != PASS:
        raise CompositionTheoremEvidenceUnproven(
            f"theorem evidence status 가 PASS 가 아니다: {manifest.evidence_status!r}"
        )
    # digest tamper: 저장 digest 를 fixture corpus 에서 재계산해 대조.
    if manifest.theorem_test_suite_digest != fixture_manifest_digest(POSITIVE_THEOREM_FIXTURES):
        raise CompositionTheoremEvidenceIntegrityError("theorem test suite digest 불일치")
    if manifest.counterexample_fixture_manifest_digest != fixture_manifest_digest(
        COUNTEREXAMPLE_THEOREM_FIXTURES
    ):
        raise CompositionTheoremEvidenceIntegrityError("counterexample fixture digest 불일치")
    # registered canonical 과 전 필드 정합(위조된 verifier_version 등 차단).
    if manifest != registered:
        raise CompositionTheoremEvidenceIntegrityError(
            "theorem evidence 가 등록된 canonical 과 불일치"
        )


# ─── RuntimeMaterializerConformance seam(current admission — semantic 아님) ──────────
@dataclass(frozen=True)
class RuntimeMaterializerConformanceManifest:
    """shipping runtime 의 current capability/conformance. S5 는 schema·registry·query 만 둔다.

    실제 PASS manifest 발행은 S6 소유. theorem evidence 와 **다른 identity** 다 — semantic
    digest 에 섞이지 않는다.
    """

    runtime_capability_manifest_digest: str
    materialization_contract_id: str
    materialization_base_contract_id: str
    native_primitive_contract_id: str
    admitted_composition_contract_ids: tuple[str, ...]
    supported_plan_schema_versions: tuple[str, ...]
    supported_canonical_encoding_versions: tuple[str, ...]
    conformance_status: str


def runtime_conformance_digest(m: RuntimeMaterializerConformanceManifest) -> str:
    return content_digest(
        {
            "runtime_capability_manifest_digest": m.runtime_capability_manifest_digest,
            "materialization_contract_id": m.materialization_contract_id,
            "materialization_base_contract_id": m.materialization_base_contract_id,
            "native_primitive_contract_id": m.native_primitive_contract_id,
            "admitted_composition_contract_ids": sorted(m.admitted_composition_contract_ids),
            "supported_plan_schema_versions": sorted(m.supported_plan_schema_versions),
            "supported_canonical_encoding_versions": sorted(
                m.supported_canonical_encoding_versions
            ),
            "conformance_status": m.conformance_status,
        }
    )


class RuntimeMaterializerConformanceRegistry:
    """current runtime conformance manifest 의 admission query port. 기본은 비어 있다(S6 채움)."""

    def __init__(self) -> None:
        self._admitted: list[RuntimeMaterializerConformanceManifest] = []

    def register(self, manifest: RuntimeMaterializerConformanceManifest) -> None:
        if manifest.conformance_status != PASS:
            raise RuntimeMaterializerConformanceNotAdmitted(
                f"PASS 아닌 conformance 는 등록 불가: {manifest.conformance_status!r}"
            )
        self._admitted.append(manifest)

    def is_admitted(
        self,
        *,
        materialization_contract_id: str,
        native_primitive_contract_id: str,
        composition_contract_id: str,
        plan_schema_version: str,
        canonical_encoding_version: str,
    ) -> bool:
        return any(
            m.materialization_contract_id == materialization_contract_id
            and m.native_primitive_contract_id == native_primitive_contract_id
            and composition_contract_id in m.admitted_composition_contract_ids
            and plan_schema_version in m.supported_plan_schema_versions
            and canonical_encoding_version in m.supported_canonical_encoding_versions
            for m in self._admitted
        )

    def require_admitted(self, **query: str) -> None:
        if not self.is_admitted(**query):
            raise RuntimeMaterializerConformanceNotAdmitted(
                f"admitted runtime materializer conformance 부재: {query}"
            )


DEFAULT_RUNTIME_CONFORMANCE_REGISTRY = RuntimeMaterializerConformanceRegistry()


# ─── verifier 결과 sum type ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CompositionPremisesPassed:
    """모든 required premise 가 exact projection fact 에서 증명됨."""

    composition_contract_id: str
    native_primitive_contract_id: str
    theorem_evidence_manifest_digest: str
    verified_premise_facts: Mapping[str, Any]
    premise_verification_digest: str


@dataclass(frozen=True)
class CompositionPremisesBlocked:
    """premise 가 provably false — structure/profile 이 seal 불가(definitive negative)."""

    code: str
    premise_id: str
    reason: str


@dataclass(frozen=True)
class CompositionPremiseContextError:
    """평가 자체가 불가(fact 부재/모순·미지 contract·evidence integrity)."""

    code: str
    premise_id: str | None
    reason: str


CompositionPremiseVerificationResult = (
    CompositionPremisesPassed | CompositionPremisesBlocked | CompositionPremiseContextError
)


# ─── premise 평가(pure) ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _PremiseOutcome:
    status: str  # OK | FAILED | INCOMPLETE
    reason: str = ""


def _bool_fact(facts: Mapping[str, Any], key: str) -> _PremiseOutcome:
    value = facts.get(key)
    if not isinstance(value, bool):
        return _PremiseOutcome(INCOMPLETE, f"{key} fact 부재/비-bool")
    return _PremiseOutcome(OK if value else FAILED, "" if value else f"{key}=False")


def _premise_c1(structure: ExecutionTemplateStructure) -> _PremiseOutcome:
    refs = [(r.slot_id, r.option_id) for r in structure.option_regions]
    if len(set(refs)) != len(refs):
        return _PremiseOutcome(FAILED, "RemoveOption target 이 서로 다른 Option 이 아니다")
    return _PremiseOutcome(OK)


def _premise_c2(
    structure: ExecutionTemplateStructure, *, touching_theorem_available: bool
) -> _PremiseOutcome:
    n = len(structure.option_regions)
    expected_pairs = n * (n - 1) // 2
    relations = structure.removal_target_relations
    if len(relations) != expected_pairs:
        return _PremiseOutcome(
            INCOMPLETE, f"target-target relation 수 {len(relations)} != 기대 {expected_pairs}"
        )
    seen: set[tuple[Any, Any]] = set()
    for rel in relations:
        pair = (
            (rel.left_option_ref.slot_id, rel.left_option_ref.option_id),
            (rel.right_option_ref.slot_id, rel.right_option_ref.option_id),
        )
        if pair in seen:
            return _PremiseOutcome(INCOMPLETE, f"중복 relation fact: {pair}")
        seen.add(pair)
        verdict = classify_target_target_admission(
            rel.relation, touching_theorem_available=touching_theorem_available
        )
        if verdict == INCOMPLETE:
            return _PremiseOutcome(INCOMPLETE, f"미지 relation 어휘: {rel.relation!r}")
        if verdict == FAILED:
            return _PremiseOutcome(FAILED, f"admit 불가 relation {rel.relation} @ {pair}")
    return _PremiseOutcome(OK)


def _premise_c3(structure: ExecutionTemplateStructure) -> _PremiseOutcome:
    return _bool_fact(
        structure.global_composition_facts.resolver_stability_facts,
        "remaining_target_resolvable_after_removal",
    )


def _premise_c4(
    structure: ExecutionTemplateStructure, *, coincidence_theorem_available: bool
) -> _PremiseOutcome:
    entry_envelope = {
        e.content_entry_id: e.envelope_capability_facts for e in structure.content_entries
    }
    for region in structure.option_regions:
        slot_fact = next(
            (f for f in region.owner_relation_facts if f.get("relation") == "target_owner_slot"),
            None,
        )
        if slot_fact is None or not isinstance(slot_fact.get("coincidence"), str):
            return _PremiseOutcome(INCOMPLETE, f"owner coincidence fact 부재 @ {region.option_id}")
        envelope = entry_envelope.get(region.content_entry_id)
        if envelope is None:
            return _PremiseOutcome(INCOMPLETE, f"region content entry envelope 부재 @ {region.option_id}")
        marker = envelope.get("preserves_owner_marker")
        boundary = envelope.get("coincident_boundary_admissible")
        if not isinstance(marker, bool) or not isinstance(boundary, bool):
            return _PremiseOutcome(INCOMPLETE, f"owner envelope fact 부재 @ {region.option_id}")
        verdict = is_owner_coincidence_admitted(
            slot_fact["coincidence"],
            preserves_owner_marker=marker,
            coincident_boundary_admissible=boundary,
            coincidence_theorem_available=coincidence_theorem_available,
        )
        if verdict == INCOMPLETE:
            return _PremiseOutcome(INCOMPLETE, f"미지 coincidence 어휘 @ {region.option_id}")
        if verdict == FAILED:
            return _PremiseOutcome(
                FAILED, f"owner coincidence admit 불가 @ {region.option_id}"
            )
    return _PremiseOutcome(OK)


def _premise_c5(structure: ExecutionTemplateStructure) -> _PremiseOutcome:
    for slot in structure.product_structure.slots:
        if len(slot.options) == 0:
            return _PremiseOutcome(FAILED, f"Slot {slot.id!r} 이 selected Option 을 유지 못 한다")
    return _PremiseOutcome(OK)


def _premise_c6(structure: ExecutionTemplateStructure) -> _PremiseOutcome:
    for region in structure.option_regions:
        for fact in region.retained_content_relation_facts:
            position = fact.get("position")
            if not isinstance(position, str):
                return _PremiseOutcome(INCOMPLETE, f"retained position fact 부재 @ {region.option_id}")
            if position == POSITION_INSIDE:
                return _PremiseOutcome(
                    FAILED,
                    f"retained content {fact.get('field_id')!r} 가 removal target 안 @ {region.option_id}",
                )
    return _PremiseOutcome(OK)


def _premise_c7(structure: ExecutionTemplateStructure) -> _PremiseOutcome:
    outcome = _bool_fact(
        structure.global_composition_facts.resolver_stability_facts,
        "active_field_resolvable_after_removal",
    )
    if outcome.status != OK:
        return outcome
    for occ in structure.field_occurrences:
        if not occ.native_value_target_class or not occ.resolver_contract_id:
            return _PremiseOutcome(
                INCOMPLETE, f"Active Field {occ.field_id!r} value target/resolver fact 부재"
            )
    return _PremiseOutcome(OK)


def _premise_c8(structure: ExecutionTemplateStructure) -> _PremiseOutcome:
    return _bool_fact(
        structure.global_composition_facts.resolver_stability_facts,
        "field_write_preserves_identity",
    )


def _premise_c9(structure: ExecutionTemplateStructure) -> _PremiseOutcome:
    # group 내부 순서는 native 안전성에 무관하고 canonical identity 만 결정한다 —
    # 그 identity 가 결정 가능함(ordinal 이 field 별 0..n-1)만 확인한다.
    by_field: dict[str, list[int]] = {}
    for occ in structure.field_occurrences:
        by_field.setdefault(occ.field_id, []).append(occ.occurrence_ordinal)
    for field_id, ordinals in by_field.items():
        if set(ordinals) != set(range(len(ordinals))):
            return _PremiseOutcome(
                INCOMPLETE, f"Field {field_id!r} occurrence identity 가 canonical 하지 않다"
            )
    return _PremiseOutcome(OK)


def _premise_c10(structure: ExecutionTemplateStructure) -> _PremiseOutcome:
    affected: set[str] = {r.content_entry_id for r in structure.option_regions}
    affected |= {o.content_entry_id for o in structure.field_occurrences}
    entry_envelope = {
        e.content_entry_id: e.envelope_capability_facts for e in structure.content_entries
    }
    for entry_id in sorted(affected):
        envelope = entry_envelope.get(entry_id)
        if envelope is None:
            return _PremiseOutcome(INCOMPLETE, f"affected content entry envelope 부재: {entry_id}")
        for key in ("retains_admissible_envelope", "handles_empty_edges"):
            value = envelope.get(key)
            if not isinstance(value, bool):
                return _PremiseOutcome(INCOMPLETE, f"{entry_id} envelope fact {key} 부재")
            if not value:
                return _PremiseOutcome(FAILED, f"{entry_id} 가 {key} 를 유지 못 한다")
    return _PremiseOutcome(OK)


def evaluate_composition_premises(
    structure: ExecutionTemplateStructure,
    *,
    theorem_evidence_valid: bool,
) -> dict[str, _PremiseOutcome]:
    """C1~C10 을 exact projection fact 만으로 평가한다(pure·deterministic).

    ``theorem_evidence_valid`` 는 target-target TOUCHING gate 와 owner coincidence gate 를 연다 —
    exact primitive theorem 이 있을 때만.
    """
    return {
        "C1": _premise_c1(structure),
        "C2": _premise_c2(structure, touching_theorem_available=theorem_evidence_valid),
        "C3": _premise_c3(structure),
        "C4": _premise_c4(structure, coincidence_theorem_available=theorem_evidence_valid),
        "C5": _premise_c5(structure),
        "C6": _premise_c6(structure),
        "C7": _premise_c7(structure),
        "C8": _premise_c8(structure),
        "C9": _premise_c9(structure),
        "C10": _premise_c10(structure),
    }


# ─── verifier ────────────────────────────────────────────────────────────────────────
def verify_execution_composition_premises(
    *,
    structure: ExecutionTemplateStructure,
    native_primitive_contract: NativePrimitiveContractManifest,
    theorem_evidence: CompositionTheoremEvidenceManifest,
    composition_contract_id: str = COMPOSITION_CONTRACT_ID,
    theorem_registry: TheoremEvidenceRegistry = DEFAULT_THEOREM_EVIDENCE_REGISTRY,
) -> CompositionPremiseVerificationResult:
    """exact projection fact + theorem evidence 로 ordered composition premise 를 판정한다.

    PASS 는 (1) composition/native primitive contract 가 등록됨, (2) theorem evidence 가
    integrity·PASS, (3) projection resolver/removal contract 가 native primitive contract 와
    결속, (4) C1~C10 이 전부 증명될 때만. 증명 안 되면 latest fallback 없이 Blocked/ContextError.
    """
    # (1) contract 등록 — 미지원은 latest fallback 없이 context error.
    if composition_contract_id != COMPOSITION_CONTRACT_ID:
        return CompositionPremiseContextError(
            UnsupportedCompositionContract.code, None,
            f"미지원 composition contract: {composition_contract_id!r}",
        )
    if native_primitive_contract.native_primitive_contract_id != NATIVE_PRIMITIVE_CONTRACT_ID:
        return CompositionPremiseContextError(
            UnsupportedNativePrimitiveContract.code, None,
            f"미지원 native primitive contract: "
            f"{native_primitive_contract.native_primitive_contract_id!r}",
        )
    # native primitive contract 는 semantic 의미가 고정 — 위조 필드는 context error.
    if native_primitive_contract != NATIVE_PRIMITIVE_CONTRACT_V1:
        return CompositionPremiseContextError(
            UnsupportedNativePrimitiveContract.code, None,
            "native primitive contract 가 등록된 canonical 과 불일치(같은 ID 의미 수정 금지)",
        )

    # (2) theorem evidence integrity·PASS.
    try:
        verify_theorem_evidence_integrity(theorem_evidence, registry=theorem_registry)
    except CompositionTheoremEvidenceUnproven as exc:
        return CompositionPremiseContextError(exc.code, None, str(exc))
    except CompositionAdmissionError as exc:
        return CompositionPremiseContextError(exc.code, None, str(exc))
    # integrity 가 evidence == 등록 canonical(=요청 contract 와 같은 ID)임을 이미 강제하므로
    # evidence↔요청 contract 재대조는 불요(dead) — 여기서 다시 세우지 않는다.

    # (3) projection 이 native primitive contract 로 servable — resolver/removal 결속.
    binding = _check_native_binding(structure, native_primitive_contract)
    if binding is not None:
        return binding

    # (4) C1~C10.
    outcomes = evaluate_composition_premises(structure, theorem_evidence_valid=True)
    # 부재/모순(INCOMPLETE) 을 provable-false(FAILED) 보다 먼저 — 평가 불가가 우선.
    for premise_id in PREMISE_IDS:
        outcome = outcomes[premise_id]
        if outcome.status == INCOMPLETE:
            return CompositionPremiseContextError(
                "EXECUTION_COMPOSITION_PREMISE_INCOMPLETE", premise_id, outcome.reason
            )
    for premise_id in PREMISE_IDS:
        outcome = outcomes[premise_id]
        if outcome.status == FAILED:
            return CompositionPremisesBlocked(
                "EXECUTION_COMPOSITION_PREMISE_FAILED", premise_id, outcome.reason
            )

    verified_premise_facts = _verified_premise_facts(structure, outcomes)
    evidence_digest = theorem_evidence_digest(theorem_evidence)
    premise_verification_digest = content_digest(
        {
            "composition_contract_id": composition_contract_id,
            "native_primitive_contract_id": (
                native_primitive_contract.native_primitive_contract_id
            ),
            "theorem_evidence_manifest_digest": evidence_digest,
            "verified_premise_facts": dict(verified_premise_facts),
        }
    )
    return CompositionPremisesPassed(
        composition_contract_id=composition_contract_id,
        native_primitive_contract_id=native_primitive_contract.native_primitive_contract_id,
        theorem_evidence_manifest_digest=evidence_digest,
        verified_premise_facts=verified_premise_facts,
        premise_verification_digest=premise_verification_digest,
    )


def _check_native_binding(
    structure: ExecutionTemplateStructure,
    contract: NativePrimitiveContractManifest,
) -> CompositionPremiseContextError | None:
    """projection 의 resolver/removal contract id 가 native primitive contract 와 결속되는지.

    불일치 = 이 native primitive contract 로 이 projection 을 servable 하지 못함 →
    latest fallback 없이 context error.
    """
    for occ in structure.field_occurrences:
        if occ.resolver_contract_id != contract.field_resolver_contract_id:
            return CompositionPremiseContextError(
                UnsupportedNativePrimitiveContract.code, "C7",
                f"Field {occ.field_id!r} resolver {occ.resolver_contract_id!r} 가 "
                f"native primitive field resolver {contract.field_resolver_contract_id!r} 와 불일치",
            )
    for region in structure.option_regions:
        if region.removal_capability_ref != contract.option_removal_contract_id:
            return CompositionPremiseContextError(
                UnsupportedNativePrimitiveContract.code, "C2",
                f"Option {region.option_id!r} removal {region.removal_capability_ref!r} 가 "
                f"native primitive removal {contract.option_removal_contract_id!r} 와 불일치",
            )
    return None


def _verified_premise_facts(
    structure: ExecutionTemplateStructure,
    outcomes: Mapping[str, _PremiseOutcome],
) -> dict[str, Any]:
    """PASS 결과에 담을 canonical premise fact — stable ordering, runtime conformance 없음."""
    relation_counts: dict[str, int] = {}
    for rel in structure.removal_target_relations:
        relation_counts[rel.relation] = relation_counts.get(rel.relation, 0) + 1
    owner_kinds = {
        OWNER_ROOT: 0, OWNER_SLOT_SHARED: 0, OWNER_OPTION: 0,
    }
    for occ in structure.field_occurrences:
        owner_kinds[occ.owner_kind] = owner_kinds.get(occ.owner_kind, 0) + 1
    return {
        "premises_proven": {pid: outcomes[pid].status for pid in PREMISE_IDS},
        "crossing_free": structure.global_composition_facts.crossing_free,
        "target_target_relation_counts": relation_counts,
        "attested_target_target_relations": sorted(_ATTESTED_TARGET_TARGET_RELATIONS),
        "occurrence_owner_kind_counts": owner_kinds,
        "removal_target_count": len(structure.option_regions),
    }
