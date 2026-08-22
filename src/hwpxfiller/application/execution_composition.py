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
from types import MappingProxyType
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
    POSITION_AFTER,
    POSITION_BEFORE,
    POSITION_INSIDE,
    ExecutionTemplateStructure,
    classify_span_relation,
    is_supported_execution_projection,
    template_structure_digest,
)
from hwpxfiller.application.qualification_evidence import content_digest

_VALID_RETAINED_POSITIONS = frozenset({POSITION_BEFORE, POSITION_INSIDE, POSITION_AFTER})

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
# 각 case 는 self-declared label 이 아니라 EXECUTABLE geometric 관찰값이다 — 실 classifier 로
# 재실행해 admit/reject 결과를 확인하고(prove_theorem_corpus), digest 를 그 case 내용(입력+
# 기대)에 결속한다. label 만 든 "admitted:true" manifest 는 실 corpus 와 digest 가 안 맞아
# fail-closed 다("declaration lives, result dies" 회피). structural/geometric theorem 층이고
# native_primitive_contract_id 에 결속된다 — shipping runtime conformance 는 별 seam.

# target-target: closed 정수 span 두 개 + touching theorem 유무 → 기대 admission.
_TARGET_TARGET_CASES: tuple[Mapping[str, Any], ...] = (
    {"case": "tt-disjoint", "family": "target_target", "a": [10, 20], "b": [30, 40],
     "touching_theorem": False, "expected": OK},
    {"case": "tt-touching-gated", "family": "target_target", "a": [10, 20], "b": [20, 40],
     "touching_theorem": True, "expected": OK},
    {"case": "tt-touching-ungated", "family": "target_target", "a": [10, 20], "b": [20, 40],
     "touching_theorem": False, "expected": FAILED},
    {"case": "tt-contains", "family": "target_target", "a": [10, 40], "b": [15, 30],
     "touching_theorem": True, "expected": FAILED},
    {"case": "tt-contained", "family": "target_target", "a": [15, 30], "b": [10, 40],
     "touching_theorem": True, "expected": FAILED},
    {"case": "tt-same-span", "family": "target_target", "a": [10, 40], "b": [10, 40],
     "touching_theorem": True, "expected": FAILED},
    {"case": "tt-crossing", "family": "target_target", "a": [10, 30], "b": [20, 40],
     "touching_theorem": True, "expected": FAILED},
)

# target-owner: owner/target coincidence + envelope capability + theorem → 기대 admission.
_OWNER_CASES: tuple[Mapping[str, Any], ...] = (
    {"case": "ow-interior", "family": "owner", "coincidence": COINCIDE_INTERIOR,
     "marker": True, "boundary": True, "theorem": False, "expected": OK},
    {"case": "ow-same-start-gated", "family": "owner", "coincidence": COINCIDE_SAME_START,
     "marker": True, "boundary": True, "theorem": True, "expected": OK},
    {"case": "ow-same-end-gated", "family": "owner", "coincidence": COINCIDE_SAME_END,
     "marker": True, "boundary": True, "theorem": True, "expected": OK},
    {"case": "ow-same-span-gated", "family": "owner", "coincidence": COINCIDE_SAME_SPAN,
     "marker": True, "boundary": True, "theorem": True, "expected": OK},
    {"case": "ow-same-start-ungated", "family": "owner", "coincidence": COINCIDE_SAME_START,
     "marker": True, "boundary": True, "theorem": False, "expected": FAILED},
    {"case": "ow-same-span-no-capability", "family": "owner", "coincidence": COINCIDE_SAME_SPAN,
     "marker": False, "boundary": True, "theorem": True, "expected": FAILED},
)

_THEOREM_CORPUS: tuple[Mapping[str, Any], ...] = _TARGET_TARGET_CASES + _OWNER_CASES


def _run_theorem_case(case: Mapping[str, Any]) -> str:
    """corpus case 를 실 classifier 로 재실행해 admission verdict 를 낸다(geometry → verdict)."""
    if case["family"] == "target_target":
        relation = classify_span_relation(tuple(case["a"]), tuple(case["b"]))
        return classify_target_target_admission(
            relation, touching_theorem_available=case["touching_theorem"]
        )
    return is_owner_coincidence_admitted(
        case["coincidence"],
        preserves_owner_marker=case["marker"],
        coincident_boundary_admissible=case["boundary"],
        coincidence_theorem_available=case["theorem"],
    )


def prove_theorem_corpus(corpus: tuple[Mapping[str, Any], ...] = _THEOREM_CORPUS) -> None:
    """corpus 전 case 를 재실행해 기대 admission 과 일치함을 강제한다(result-lives guard).

    theorem PASS 는 label 이 아니라 이 재증명에 결속된다 — 어긋나면 시끄럽게 닫힌다.
    """
    for case in corpus:
        verdict = _run_theorem_case(case)
        if verdict != case["expected"]:
            raise CompositionTheoremEvidenceIntegrityError(
                f"theorem corpus case {case['case']!r} 결과 {verdict} != 기대 {case['expected']}"
            )


# positive(admitted) / counterexample(rejected) 분리 — 실 case 내용에 digest 결속.
POSITIVE_THEOREM_FIXTURES: tuple[Mapping[str, Any], ...] = tuple(
    c for c in _THEOREM_CORPUS if c["expected"] == OK
)
COUNTEREXAMPLE_THEOREM_FIXTURES: tuple[Mapping[str, Any], ...] = tuple(
    c for c in _THEOREM_CORPUS if c["expected"] == FAILED
)

# import 시 corpus 가 실제로 성립함을 증명한다 — 통과 못 하면 모듈이 로드되지 않는다.
prove_theorem_corpus()

# theorem 이 attest 하는 target-target relation(admitted case 의 실 geometry 에서 유도).
_ATTESTED_TARGET_TARGET_RELATIONS = frozenset(
    classify_span_relation(tuple(c["a"]), tuple(c["b"]))
    for c in POSITIVE_THEOREM_FIXTURES
    if c["family"] == "target_target"
)


def fixture_manifest_digest(fixtures: tuple[Mapping[str, Any], ...]) -> str:
    """fixture corpus 의 content-address(case 정렬로 저장 순서 ≠ identity)."""
    return content_digest(sorted((dict(f) for f in fixtures), key=lambda f: f["case"]))


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
        runtime_capability_manifest_digest: str,
        materialization_contract_id: str,
        materialization_base_contract_id: str,
        native_primitive_contract_id: str,
        composition_contract_id: str,
        plan_schema_version: str,
        canonical_encoding_version: str,
    ) -> bool:
        # capability digest·base contract 를 함께 대조한다 — shipping runtime 이나 base contract 가
        # 바뀌면 옛 PASS manifest 는 더 이상 admit 되지 않는다(stale admission 차단).
        return any(
            m.runtime_capability_manifest_digest == runtime_capability_manifest_digest
            and m.materialization_contract_id == materialization_contract_id
            and m.materialization_base_contract_id == materialization_base_contract_id
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
def _deep_freeze(value: Any) -> Any:
    """JSON-safe 값을 재귀적으로 얼린다 — frozen dataclass 가 nested dict/list 변이를 못 막는다.

    dict → read-only MappingProxyType, list → tuple. scalar 는 그대로. 이로써 PASS 결과의
    verified_premise_facts 를 검증 뒤 고쳐도 premise_verification_digest 가 stale 해질 수 없다.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class CompositionPremisesPassed:
    """모든 required premise 가 exact projection fact 에서 증명됨.

    PASS = **static admission** 뿐이다: ordered ``RemoveOption``/``ApplyFieldBinding`` 이 지원되는
    static composition contract 에 속함을 뜻한다. actual HWPX bytes 생성·serialize/reparse·
    postcondition 충족·한글 layout 동일성·filesystem delivery 에 대해서는 **아무것도 단언하지
    않는다** — 그 actual native materialization conformance 는 별 identity 이고 SG-02 harness /
    S6 가 진다(SG-02 · #734).
    """

    composition_contract_id: str
    native_primitive_contract_id: str
    template_structure_digest: str
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
    # canonical UNORDERED pair set 를 option_regions 에서 유도한다 — count·ordered-dup 검사만으로는
    # (a,b),(b,a),(a,c) 처럼 실제 pair (b,c) 가 빠진 위조 DTO 가 통과한다.
    refs = sorted((r.slot_id, r.option_id) for r in structure.option_regions)
    expected_pairs = {
        frozenset((refs[i], refs[j]))
        for i in range(len(refs))
        for j in range(i + 1, len(refs))
    }
    valid_refs = set(refs)
    seen: set[frozenset[tuple[str, str]]] = set()
    for rel in structure.removal_target_relations:
        left = (rel.left_option_ref.slot_id, rel.left_option_ref.option_id)
        right = (rel.right_option_ref.slot_id, rel.right_option_ref.option_id)
        if left not in valid_refs or right not in valid_refs or left == right:
            return _PremiseOutcome(
                INCOMPLETE, f"relation 이 존재하지 않는/동일 Option 을 참조: {left}·{right}"
            )
        pair = frozenset((left, right))
        if pair in seen:
            return _PremiseOutcome(INCOMPLETE, f"중복 relation fact: {tuple(sorted(pair))}")
        seen.add(pair)
        verdict = classify_target_target_admission(
            rel.relation, touching_theorem_available=touching_theorem_available
        )
        if verdict == INCOMPLETE:
            return _PremiseOutcome(INCOMPLETE, f"미지 relation 어휘: {rel.relation!r}")
        if verdict == FAILED:
            return _PremiseOutcome(FAILED, f"admit 불가 relation {rel.relation} @ {tuple(sorted(pair))}")
    if seen != expected_pairs:
        return _PremiseOutcome(
            INCOMPLETE, f"target-target pair 집합 불완전: 누락 {sorted(expected_pairs - seen)}"
        )
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
    """retained content(root/slot-shared/다른 Option 의 Active Field)가 어떤 removal target 안에도
    없음을 증명한다.

    빈/미지 vocab 을 "밖에 있다"로 추정하지 않는다 — region 마다 기대 retained-occurrence 집합을
    structure 에서 재계산해 **완전 coverage** 를 강제한다. 누락·미지 position → context error(평가
    불가), INSIDE → Blocked. decode 경로가 이 집합을 재구성 안 하므로 여기서 닫아야 조용한
    Blocked→Passed 뒤집힘이 없다.
    """
    for region in structure.option_regions:
        expected = {
            (occ.field_id, occ.occurrence_ordinal)
            for occ in structure.field_occurrences
            if not (
                occ.owner_kind == OWNER_OPTION
                and occ.owner_slot_id == region.slot_id
                and occ.owner_option_id == region.option_id
            )
        }
        positions: dict[tuple[str, int], str] = {}
        for fact in region.retained_content_relation_facts:
            field_id = fact.get("field_id")
            ordinal = fact.get("occurrence_ordinal")
            position = fact.get("position")
            if not isinstance(field_id, str) or not isinstance(ordinal, int):
                return _PremiseOutcome(
                    INCOMPLETE, f"retained fact 의 occurrence 식별자 부재 @ {region.option_id}"
                )
            if position not in _VALID_RETAINED_POSITIONS:
                return _PremiseOutcome(
                    INCOMPLETE, f"retained position 어휘 밖({position!r}) @ {region.option_id}"
                )
            positions[(field_id, ordinal)] = position
        if set(positions) != expected:
            return _PremiseOutcome(
                INCOMPLETE,
                f"retained 집합 불완전 @ {region.option_id}: "
                f"누락 {sorted(expected - set(positions))}·잉여 {sorted(set(positions) - expected)}",
            )
        for key, position in positions.items():
            if position == POSITION_INSIDE:
                return _PremiseOutcome(
                    FAILED, f"retained content {key[0]!r} 가 removal target 안 @ {region.option_id}"
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
def _composition_identity_context_error(
    structure: ExecutionTemplateStructure,
    native_primitive_contract: NativePrimitiveContractManifest,
    composition_contract_id: str,
) -> "CompositionPremiseContextError | None":
    """(0) projection schema + (1) composition/native primitive contract identity(순수 fail-closed).

    theorem registry 를 consult 하지 않는다 — 미지원 contract/schema 는 latest fallback 없이 닫는다.
    """
    # (0) projection schema — 등록된 composition-ready schema 밖 structure 를 그 의미로 해석하지
    # 않는다(fail-closed). 판정은 execution_structure 의 pair 표 하나가 진다 — 여기서 상수를 따로
    # 들면 새 schema 를 더할 때 capture 는 통과하고 admission 만 막히는 반쪽 상태가 생긴다(#773).
    if not is_supported_execution_projection(structure.projection_schema_version):
        return CompositionPremiseContextError(
            "UNSUPPORTED_EXECUTION_STRUCTURE_PROJECTION", None,
            f"미지원 execution structure projection schema: "
            f"{structure.projection_schema_version!r}",
        )
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
    return None


def admit_composition_premises(
    *,
    structure: ExecutionTemplateStructure,
    native_primitive_contract: NativePrimitiveContractManifest,
    theorem_evidence_manifest_digest: str,
    composition_contract_id: str = COMPOSITION_CONTRACT_ID,
    theorem_capability_available: bool = True,
) -> CompositionPremiseVerificationResult:
    """C1~C10 structural admission 을 theorem runtime registry **없이** 판정한다(순수·deterministic).

    S5F R2-01(#740) 첫 절개 — theorem runtime bureaucracy 와 semantic kernel 의 결합을 끊는다.
    :func:`verify_execution_composition_premises` 의 (2) theorem evidence integrity(유일한 registry
    consult)를 제외한 전부 — (0) projection schema, (1) contract identity, (3) native binding,
    (4) C1~C10, PASS 조립 — 를 여기 순수하게 둔다. theorem evidence 의 manifest digest 는 caller 가
    신뢰하는 값(``theorem_evidence_manifest_digest``)으로 그대로 싣고, target-target TOUCHING·owner
    coincidence gate 는 caller 가 선언한 proven capability(``theorem_capability_available``)로 연다.
    그 capability correctness 는 theorem corpus 가 **test 로** 증명한다(runtime authority 아님).

    반환 의미는 verify 와 동일하다: PASS / INCOMPLETE(ContextError) / FAILED(Blocked).
    """
    identity_error = _composition_identity_context_error(
        structure, native_primitive_contract, composition_contract_id
    )
    if identity_error is not None:
        return identity_error

    # (3) projection 이 native primitive contract 로 servable — resolver/removal 결속.
    binding = _check_native_binding(structure, native_primitive_contract)
    if binding is not None:
        return binding

    # (4) C1~C10 — theorem capability 는 caller 선언(registry 아님).
    outcomes = evaluate_composition_premises(
        structure, theorem_evidence_valid=theorem_capability_available
    )
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
    structure_digest = template_structure_digest(structure)
    premise_verification_digest = content_digest(
        {
            "composition_contract_id": composition_contract_id,
            "native_primitive_contract_id": (
                native_primitive_contract.native_primitive_contract_id
            ),
            "template_structure_digest": structure_digest,
            "theorem_evidence_manifest_digest": theorem_evidence_manifest_digest,
            "verified_premise_facts": verified_premise_facts,
        }
    )
    return CompositionPremisesPassed(
        composition_contract_id=composition_contract_id,
        native_primitive_contract_id=native_primitive_contract.native_primitive_contract_id,
        template_structure_digest=structure_digest,
        theorem_evidence_manifest_digest=theorem_evidence_manifest_digest,
        verified_premise_facts=_deep_freeze(verified_premise_facts),
        premise_verification_digest=premise_verification_digest,
    )


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

    이 PASS 는 **static admission** 만을 뜻한다 — ordered ops 가 지원되는 static composition
    contract 에 속함. serialize/reparse/postcondition/한글 layout/delivery 성공에 대해서는 아무것도
    단언하지 않으며, runtime materializer conformance 를 **대체하지 않는다**(그 seam 은
    :class:`RuntimeMaterializerConformanceRegistry`·SG-02 harness·S6 소유). seal/compile 경로는
    admission 판정에 그 registry 를 절대 consult 하지 않는다.

    R2-01(#740): (2) theorem evidence integrity 만 이 wrapper 의 registry consult 로 남기고, 나머지
    순수 판정((0)(1)(3)(4)·PASS 조립)은 :func:`admit_composition_premises` 가 공유한다 — semantic
    kernel 은 그 순수 함수만 부른다(registry 미consult). 두 경로의 판정·byte 는 동일하다.
    """
    # (0),(1) identity — precedence 를 위해 (2) registry consult 앞에 둔다.
    identity_error = _composition_identity_context_error(
        structure, native_primitive_contract, composition_contract_id
    )
    if identity_error is not None:
        return identity_error
    # (2) theorem evidence integrity·PASS — 이 함수의 **유일한** registry consult.
    try:
        verify_theorem_evidence_integrity(theorem_evidence, registry=theorem_registry)
    except CompositionTheoremEvidenceUnproven as exc:
        return CompositionPremiseContextError(exc.code, None, str(exc))
    except CompositionAdmissionError as exc:
        return CompositionPremiseContextError(exc.code, None, str(exc))
    # integrity 가 evidence == 등록 canonical 임을 이미 강제하므로 evidence↔contract 재대조는 dead.
    # (3),(4),PASS 조립 — registry 없는 순수 판정에 위임(theorem digest 는 등록 canonical 값).
    return admit_composition_premises(
        structure=structure,
        native_primitive_contract=native_primitive_contract,
        theorem_evidence_manifest_digest=theorem_evidence_digest(theorem_evidence),
        composition_contract_id=composition_contract_id,
        theorem_capability_available=True,
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
