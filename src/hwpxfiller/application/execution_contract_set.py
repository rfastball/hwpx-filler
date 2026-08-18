"""closed ExecutionContractSet + capture·basis·Plan canonical digest 결속(S5-06 · #702).

S5-02..05 는 semantic payload 와 stable ordering 을 고정했다. 이 slice 는 그 위에 세 가지를 얹는다:

1. **closed byte framing set** — :mod:`hwpxfiller.domain.canonical_execution_encoding` 가 capture·
   basis·Plan digest 의 단일 byte framing 이다(각 slice 의 ``# ponytail:`` content_digest 자리를
   대신한다). 이 모듈은 그 encoder 로 basis·Plan·contract-set·qualification digest 를 낸다.
2. **immutable ExecutionContractSet** — issue 가 열거한 12 contract 역할 + theorem evidence digest
   를 하나의 closed manifest 로 묶는다. unknown → latest fallback 금지, 같은 schema version 의 의미
   수정 금지, 과거 manifest 삭제 금지(append-only registry).
3. **Plan identity 계약** — ``plan_semantic_digest`` framing + ``PlanCompilationKey`` functional
   dependency(같은 key → 최대 1 plan digest) + Plan decode 시 nested digest 재계산 검증.

제외(S5-00 불변식 5): 모든 timestamp·store/object path·authority revision provenance·object
address 는 어떤 semantic digest 에도 들어가지 않는다.

경계: additive. product route(webapp/bridge/frontend)·Plan durable store(S5-07)·native
materialization(S6)를 배선하지 않는다. Raw Record/VDR/delivery payload codec(S5-12/13)은
contract ID 로 결속만 하고 payload bytes 를 선행 구현하지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from hwpxfiller.application.execution_capture import (
    MATERIALIZATION_BASE_CONTRACT_ID,
    EffectiveSelectionBasis,
    ExactTemplateExecutionBasis,
    QualificationProfileSemanticPayload,
)
from hwpxfiller.application.execution_compilation import (
    EffectiveFieldBindingBasis,
    active_binding_digest,
    encode_value_expression,
    required_source_key_set_digest,
)
from hwpxfiller.application.execution_composition import (
    DEFAULT_THEOREM_EVIDENCE_REGISTRY,
    TheoremEvidenceRegistry,
    theorem_evidence_digest,
)
from hwpxfiller.domain.canonical_execution_encoding import (
    CANONICAL_ENCODING_VERSION,
    canonical_execution_digest,
    require_supported_encoding,
)

# ─── S5-06 schema identity(의미가 바뀌면 새 버전 — 같은 버전 의미 수정 금지) ──────────────
CONTRACT_SET_SCHEMA_VERSION = "execution-contract-set/v1"
PLAN_APPLY_FIELD_BINDING = "APPLY_FIELD_BINDING"
PLAN_REMOVE_OPTION = "REMOVE_OPTION"


# ─── 오류(issue 열거 그대로) ─────────────────────────────────────────────────────────
class ExecutionContractSetIntegrityError(Exception):
    code = "EXECUTION_CONTRACT_SET_INTEGRITY_ERROR"


class QualificationProfileManifestIntegrityError(Exception):
    code = "QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR"


class ExecutionBasisIntegrityError(Exception):
    code = "EXECUTION_BASIS_INTEGRITY_ERROR"


class ExecutionPlanIntegrityError(Exception):
    code = "EXECUTION_PLAN_INTEGRITY_ERROR"


class ExecutionPlanCompilationIntegrityError(Exception):
    code = "EXECUTION_PLAN_COMPILATION_INTEGRITY_ERROR"


class UnsupportedPlanSchemaError(Exception):
    code = "UNSUPPORTED_PLAN_SCHEMA"


class DurableCaptureEvidenceIntegrityError(Exception):
    code = "DURABLE_CAPTURE_EVIDENCE_INTEGRITY_ERROR"


def _require_nonempty(value: object, what: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ExecutionContractSetIntegrityError(f"{what} 는 비어 있지 않은 문자열이어야 한다")
    return value


def _deep_freeze(value: Any) -> Any:
    """JSON-safe 값을 재귀적으로 깊이 복사·동결한다(dict→MappingProxyType, list→tuple).

    seal 시점에 caller 의 nested dict(예: value_expression)와의 alias 를 끊어, 봉인 뒤 원본을
    고쳐도 plan_semantic_digest 가 조용히 흔들리지 못하게 한다.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    return value


# ─── ExecutionContractSet ────────────────────────────────────────────────────────────
_CONTRACT_ROLE_FIELDS = (
    "slot_selection_contract_id",
    "field_binding_contract_id",
    "source_schema_contract_id",
    "raw_record_contract_id",
    "execution_semantic_contract_id",
    "binding_value_contract_id",
    "document_value_resolution_contract_id",
    "record_validation_contract_id",
    "record_review_contract_id",
    "composition_contract_id",
    "native_primitive_contract_id",
    "materialization_base_contract_id",
    "materialization_contract_id",
)


@dataclass(frozen=True)
class ExecutionContractSet:
    """실행 semantics 를 결정하는 모든 contract 역할을 묶은 immutable closed manifest.

    ``contract_set_manifest_digest`` 는 나머지 필드의 canonical content-address 다 — 위조/부분
    변경은 :meth:`__post_init__` 의 recompute 대조에서 시끄럽게 걸린다. unknown 역할을 latest 로
    풀지 않는다: 모든 역할은 exact 하게 채워져야 하고(nonempty), 결속 검증은
    :func:`build_execution_contract_set` 가 진다.
    """

    slot_selection_contract_id: str
    field_binding_contract_id: str
    source_schema_contract_id: str
    raw_record_contract_id: str
    execution_semantic_contract_id: str
    binding_value_contract_id: str
    document_value_resolution_contract_id: str
    record_validation_contract_id: str
    record_review_contract_id: str
    composition_contract_id: str
    native_primitive_contract_id: str
    materialization_base_contract_id: str
    materialization_contract_id: str
    composition_theorem_evidence_manifest_digest: str
    contract_set_schema_version: str
    contract_set_manifest_digest: str

    def __post_init__(self) -> None:
        for name in _CONTRACT_ROLE_FIELDS:
            _require_nonempty(getattr(self, name), name)
        _require_nonempty(
            self.composition_theorem_evidence_manifest_digest,
            "composition_theorem_evidence_manifest_digest",
        )
        if self.contract_set_schema_version != CONTRACT_SET_SCHEMA_VERSION:
            raise ExecutionContractSetIntegrityError(
                f"미지원 contract set schema: {self.contract_set_schema_version!r}"
            )
        recomputed = _contract_set_manifest_digest(self)
        if self.contract_set_manifest_digest != recomputed:
            raise ExecutionContractSetIntegrityError(
                "contract_set_manifest_digest 가 canonical recompute 와 불일치"
            )


def encode_execution_contract_set(contracts: ExecutionContractSet) -> dict[str, Any]:
    """manifest digest 를 제외한 contract set 의 canonical semantic payload."""
    payload = {name: getattr(contracts, name) for name in _CONTRACT_ROLE_FIELDS}
    payload["contract_set_schema_version"] = contracts.contract_set_schema_version
    payload["composition_theorem_evidence_manifest_digest"] = (
        contracts.composition_theorem_evidence_manifest_digest
    )
    return payload


def _contract_set_manifest_digest(contracts: ExecutionContractSet) -> str:
    return canonical_execution_digest(encode_execution_contract_set(contracts))


def contract_set_manifest_digest(contracts: ExecutionContractSet) -> str:
    """closed contract set 의 content-address(canonical framing)."""
    return _contract_set_manifest_digest(contracts)


def build_execution_contract_set(
    *,
    slot_selection_contract_id: str,
    field_binding_contract_id: str,
    source_schema_contract_id: str,
    raw_record_contract_id: str,
    execution_semantic_contract_id: str,
    binding_value_contract_id: str,
    document_value_resolution_contract_id: str,
    record_validation_contract_id: str,
    record_review_contract_id: str,
    composition_contract_id: str,
    native_primitive_contract_id: str,
    materialization_base_contract_id: str,
    materialization_contract_id: str,
    composition_theorem_evidence_manifest_digest: str,
    theorem_registry: "TheoremEvidenceRegistry | None" = DEFAULT_THEOREM_EVIDENCE_REGISTRY,
) -> ExecutionContractSet:
    """모든 contract 역할을 exact 하게 결속해 closed set 을 만든다(fail-closed).

    theorem/base 결속을 실측한다: materialization base 는 admitted base contract 여야 하고,
    ``composition_theorem_evidence_manifest_digest`` 는 (composition, native primitive) 로 registry 가
    resolve 한 canonical theorem evidence digest 와 정확히 일치해야 한다 — 미등록 pair 는 latest 로
    fallback 하지 않고 registry.resolve 가 시끄럽게 닫는다.

    R2-01(#740): ``theorem_registry=None`` 은 theorem runtime bureaucracy 결합을 끊은 semantic
    kernel 용 opt-out 이다 — registry 를 consult 하지 않고 caller 가 신뢰하는 digest 를 그대로
    싣는다(digest 는 여전히 nonempty). 결과 ExecutionContractSet 은 registry 검증 경로와 **byte
    동일**하다(검증만 생략, 구성값 동일). 기존 caller 는 default registry 로 종전대로 검증한다.
    """
    if materialization_base_contract_id != MATERIALIZATION_BASE_CONTRACT_ID:
        raise ExecutionContractSetIntegrityError(
            f"materialization base contract 가 admitted base 가 아니다(latest fallback 없음): "
            f"{materialization_base_contract_id!r}"
        )
    if theorem_registry is not None:
        # theorem evidence 는 (composition, native primitive) 로 registry 가 resolve — 미등록은 fail-closed.
        registered = theorem_registry.resolve(
            composition_contract_id, native_primitive_contract_id
        )
        if theorem_evidence_digest(registered) != _require_nonempty(
            composition_theorem_evidence_manifest_digest,
            "composition_theorem_evidence_manifest_digest",
        ):
            raise ExecutionContractSetIntegrityError(
                "composition_theorem_evidence_manifest_digest 가 등록된 theorem evidence 와 불일치"
            )
    else:
        # registry 미consult(kernel opt-out) — digest 는 caller 신뢰값이되 비어 있을 수 없다(fail-closed).
        _require_nonempty(
            composition_theorem_evidence_manifest_digest,
            "composition_theorem_evidence_manifest_digest",
        )
    roles = {
        "slot_selection_contract_id": _require_nonempty(
            slot_selection_contract_id, "slot_selection_contract_id"
        ),
        "field_binding_contract_id": _require_nonempty(
            field_binding_contract_id, "field_binding_contract_id"
        ),
        "source_schema_contract_id": _require_nonempty(
            source_schema_contract_id, "source_schema_contract_id"
        ),
        "raw_record_contract_id": _require_nonempty(
            raw_record_contract_id, "raw_record_contract_id"
        ),
        "execution_semantic_contract_id": _require_nonempty(
            execution_semantic_contract_id, "execution_semantic_contract_id"
        ),
        "binding_value_contract_id": _require_nonempty(
            binding_value_contract_id, "binding_value_contract_id"
        ),
        "document_value_resolution_contract_id": _require_nonempty(
            document_value_resolution_contract_id, "document_value_resolution_contract_id"
        ),
        "record_validation_contract_id": _require_nonempty(
            record_validation_contract_id, "record_validation_contract_id"
        ),
        "record_review_contract_id": _require_nonempty(
            record_review_contract_id, "record_review_contract_id"
        ),
        "composition_contract_id": _require_nonempty(
            composition_contract_id, "composition_contract_id"
        ),
        "native_primitive_contract_id": _require_nonempty(
            native_primitive_contract_id, "native_primitive_contract_id"
        ),
        "materialization_base_contract_id": materialization_base_contract_id,
        "materialization_contract_id": _require_nonempty(
            materialization_contract_id, "materialization_contract_id"
        ),
    }
    # digest 를 먼저 계산해 채운다 — __post_init__ 이 같은 encode 로 재계산·대조한다(위조 차단).
    manifest_payload = dict(roles)
    manifest_payload["contract_set_schema_version"] = CONTRACT_SET_SCHEMA_VERSION
    manifest_payload["composition_theorem_evidence_manifest_digest"] = (
        composition_theorem_evidence_manifest_digest
    )
    return ExecutionContractSet(
        composition_theorem_evidence_manifest_digest=composition_theorem_evidence_manifest_digest,
        contract_set_schema_version=CONTRACT_SET_SCHEMA_VERSION,
        contract_set_manifest_digest=canonical_execution_digest(manifest_payload),
        **roles,
    )


class ExecutionContractSetRegistry:
    """schema version → closed manifest 의 append-only registry. unknown → latest fallback 없음.

    같은 schema version 에 다른 manifest 를 등록하면(=같은 ID 의 의미 수정) 거절한다. 과거 manifest 를
    삭제/자동 대체하지 않는다.
    """

    def __init__(self) -> None:
        self._by_schema: dict[str, ExecutionContractSet] = {}

    def register(self, contracts: ExecutionContractSet) -> None:
        key = contracts.contract_set_schema_version
        existing = self._by_schema.get(key)
        if existing is not None and existing != contracts:
            raise ExecutionContractSetIntegrityError(
                f"contract set schema {key!r} 의 의미 수정 금지 — 이미 다른 manifest 등록됨"
            )
        self._by_schema[key] = contracts

    def resolve(self, contract_set_schema_version: str) -> ExecutionContractSet:
        contracts = self._by_schema.get(contract_set_schema_version)
        if contracts is None:
            raise ExecutionContractSetIntegrityError(
                f"미등록 contract set schema(latest fallback 없음): {contract_set_schema_version!r}"
            )
        return contracts


# ─── Qualification Profile semantic digest ────────────────────────────────────────────
def encode_qualification_profile_semantic(
    payload: QualificationProfileSemanticPayload,
) -> dict[str, Any]:
    """qualification_profile_semantic_digest 가 식별하는 exact semantic 집합.

    포함: profile id·media·adapter/product/operation/projection version·manifest payload.
    제외(payload 타입이 이미 강제): created_at·store envelope·runtime admission/revocation.
    """
    return {
        "qualification_profile_id": payload.qualification_profile_id,
        "media": payload.media,
        "adapter_contract_version": payload.adapter_contract_version,
        "product_rule_version": payload.product_rule_version,
        "operation_alphabet_version": payload.operation_alphabet_version,
        "projection_schema_version": payload.projection_schema_version,
        "manifest_payload": dict(payload.manifest_payload),
    }


def qualification_profile_semantic_digest(
    payload: QualificationProfileSemanticPayload,
) -> str:
    """전체 qualification semantics 의 content-address(S3 manifest_digest 를 재사용하지 않는다)."""
    return canonical_execution_digest(encode_qualification_profile_semantic(payload))


def require_consistent_qualification_profile(
    known: Mapping[str, str], payload: QualificationProfileSemanticPayload
) -> str:
    """같은 profile id 에 다른 semantic payload 가 관찰되면 integrity error(fail-closed).

    ``known`` 은 profile_id → 이미 관찰된 semantic digest. 반환값은 이 payload 의 digest.
    """
    digest = qualification_profile_semantic_digest(payload)
    prior = known.get(payload.qualification_profile_id)
    if prior is not None and prior != digest:
        raise QualificationProfileManifestIntegrityError(
            f"qualification profile {payload.qualification_profile_id!r} 의 semantic payload 가 "
            "이전 관찰과 불일치(같은 ID 의미 수정 금지)"
        )
    return digest


# ─── effective selection / binding digest(nested 재계산 seam) ──────────────────────────
def encode_effective_selection(selection: EffectiveSelectionBasis) -> dict[str, Any]:
    """effective selection basis 의 canonical payload — detached/declared/provenance 제외.

    포함: slot_mode·selection contract·structure digest·effective selection digest. 제외:
    declared_selection_digest·work/application route·source configuration version·captured_at.
    """
    return {
        "slot_mode": selection.slot_mode,
        "selection_semantic_contract_id": selection.selection_semantic_contract_id,
        "template_structure_digest": selection.template_structure_digest,
        "effective_selection_digest": selection.effective_selection_digest,
    }


def encode_effective_field_binding(binding: EffectiveFieldBindingBasis) -> dict[str, Any]:
    """effective field binding basis 의 canonical payload — inactive/unused/revision/path 제외.

    active binding 규칙 자체는 ``active_binding_digest`` 가 이미 content-address 로 담는다(rule 을 다시
    풀어 넣지 않는다 — 중복 identity 없음). source key 는 unsigned UTF-8 byte order 다. 두 nested
    digest 는 decode 시 EffectiveFieldBindingBasis 의 rule/key 에서 재계산해 대조한다.
    """
    return {
        "active_binding_digest": binding.active_binding_digest,
        # UTF-8 byte order 로 정렬 — 저장 tuple 순서가 하나의 semantic basis 를 여러 identity 로 쪼개지 못하게 한다.
        "required_source_keys": sorted(
            binding.required_source_keys, key=lambda k: k.encode("utf-8")
        ),
        "required_source_key_set_digest": binding.required_source_key_set_digest,
    }


def recompute_active_binding_digest(binding: EffectiveFieldBindingBasis) -> str:
    """저장된 active_binding_digest 를 rule 에서 재계산한다(claim 신뢰 금지)."""
    return active_binding_digest(binding.effective_active_binding_rules)


def recompute_required_source_key_set_digest(binding: EffectiveFieldBindingBasis) -> str:
    return required_source_key_set_digest(binding.required_source_keys)


# ─── ExecutionBasis ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ExecutionBasis:
    """workspace·Work·exact template·closed contracts·effective selection·effective binding 의 묶음.

    이 묶음의 digest 가 Plan compilation 의 functional dependency key 다. nested field 의 payload 와
    digest 가 모두 일치해야 한다 — decode 시 digest 문자열만 신뢰하지 않는다.
    """

    workspace_instance_id: str
    work_authority_id: str
    # 같은 candidate/selection/binding 이라도 다른 Qualification Profile semantics(profile manifest·
    # product rule version 등) 로 자격됐으면 다른 Plan identity 여야 한다 — 그 digest 를 basis 에 결속한다.
    qualification_profile_semantic_digest: str
    template: ExactTemplateExecutionBasis
    contracts: ExecutionContractSet
    selection: EffectiveSelectionBasis
    field_binding: EffectiveFieldBindingBasis


def _encode_exact_template(template: ExactTemplateExecutionBasis) -> dict[str, Any]:
    # canonical_blob_reference 는 store/object address 라 제외(exact_content_digest 가 semantic).
    return {
        "execution_base_kind": template.execution_base_kind,
        "materialization_base_contract_id": template.materialization_base_contract_id,
        "work_authority_id": template.work_authority_id,
        "template_application_id": template.template_application_id,
        "exact_content_digest": template.exact_content_digest,
    }


def encode_execution_basis(basis: ExecutionBasis) -> dict[str, Any]:
    """ExecutionBasis 의 canonical semantic payload — nested digest 를 그대로 담는다."""
    return {
        "workspace_instance_id": basis.workspace_instance_id,
        "work_authority_id": basis.work_authority_id,
        "qualification_profile_semantic_digest": basis.qualification_profile_semantic_digest,
        "template": _encode_exact_template(basis.template),
        "contracts": encode_execution_contract_set(basis.contracts),
        "contract_set_manifest_digest": basis.contracts.contract_set_manifest_digest,
        "selection": encode_effective_selection(basis.selection),
        "field_binding": encode_effective_field_binding(basis.field_binding),
    }


def execution_basis_digest(basis: ExecutionBasis) -> str:
    """ExecutionBasis 의 content-address(canonical framing)."""
    return canonical_execution_digest(encode_execution_basis(basis))


def verify_execution_basis_integrity(basis: ExecutionBasis) -> None:
    """nested digest 를 payload 에서 재계산해 대조한다 — 주장값만 믿지 않는다(fail-closed).

    contract_set_manifest_digest 는 :meth:`ExecutionContractSet.__post_init__` 가 이미 재계산·강제하므로
    여기서는 스스로 검증하지 않는 binding digest 만 재계산한다: active binding·required source key set.
    또 selection/template locator 는 semantic digest 에서 제외되므로(우연 collision 방지) 여기서
    cross-object identity(work + template application) 정합을 명시로 강제한다 — cross-work Plan 을 닫는다.
    """
    if not (
        basis.work_authority_id
        == basis.template.work_authority_id
        == basis.selection.work_id
    ):
        raise ExecutionBasisIntegrityError(
            "work authority id 가 basis·template·selection 에서 불일치(cross-work Plan)"
        )
    if basis.template.template_application_id != basis.selection.template_application_id:
        raise ExecutionBasisIntegrityError(
            "template application id 가 template·selection 에서 불일치"
        )
    if basis.field_binding.active_binding_digest != recompute_active_binding_digest(
        basis.field_binding
    ):
        raise ExecutionBasisIntegrityError("active_binding_digest 재계산 불일치")
    if (
        basis.field_binding.required_source_key_set_digest
        != recompute_required_source_key_set_digest(basis.field_binding)
    ):
        raise ExecutionBasisIntegrityError("required_source_key_set_digest 재계산 불일치")


# ─── Sealed Execution Plan ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SealedExecutionPlanSemanticPayload:
    """Plan 의 semantic identity 집합 — random Plan ID 를 만들지 않는다(identity = plan_semantic_digest).

    제외(issue): first_sealed_at·request_id·actor session·opaque token·captured_at·현 runtime
    capability·현 Profile admission·actual record value·resolved output path·authority revision.
    """

    plan_schema_version: str
    canonical_encoding_version: str
    execution_basis: ExecutionBasis
    active_field_requirements: tuple[Mapping[str, Any], ...]
    ordered_operations: tuple[Mapping[str, Any], ...]


def encode_sealed_plan(payload: SealedExecutionPlanSemanticPayload) -> dict[str, Any]:
    """Sealed Plan 의 canonical semantic payload — execution_basis_digest 를 함께 담는다."""
    return {
        "plan_schema_version": payload.plan_schema_version,
        "canonical_encoding_version": payload.canonical_encoding_version,
        "execution_basis": encode_execution_basis(payload.execution_basis),
        "execution_basis_digest": execution_basis_digest(payload.execution_basis),
        "active_field_requirements": [dict(r) for r in payload.active_field_requirements],
        "ordered_operations": [dict(o) for o in payload.ordered_operations],
    }


def plan_semantic_digest(payload: SealedExecutionPlanSemanticPayload) -> str:
    """Sealed Plan 의 content identity — 별도 random Plan ID 없음."""
    return canonical_execution_digest(encode_sealed_plan(payload))


def canonicalize_execution_operations(
    active_field_requirements: Iterable[Mapping[str, Any]],
    ordered_operations: Iterable[Mapping[str, Any]],
) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    """ordered_operations 를 deep-freeze 하고 active_field_requirements 를 APPLY 순서로 정본화한다.

    :func:`build_sealed_plan`(legacy Plan payload)과 semantic kernel(closed manifest 없는 값)이
    **같은** canonical ordering 을 공유하는 단일 출처다 — requirement array 를 APPLY operation 순서로
    정본화해 두 array 가 같은 canonical sequence 를 쓰게 한다(#702 operation order canonicality).
    deep-freeze 로 nested value_expression 까지 alias 를 끊어 봉인 뒤 변이를 막는다.
    """
    ops = tuple(_deep_freeze(o) for o in ordered_operations)
    reqs = [_deep_freeze(r) for r in active_field_requirements]
    apply_seq = [
        o.get("field_id") for o in ops if o.get("op") == PLAN_APPLY_FIELD_BINDING
    ]
    apply_rank = {f: i for i, f in enumerate(apply_seq) if isinstance(f, str)}
    reqs.sort(key=lambda r: apply_rank.get(r.get("field_id"), len(apply_rank)))
    return tuple(reqs), ops


def build_sealed_plan(
    *,
    execution_basis: ExecutionBasis,
    active_field_requirements: Iterable[Mapping[str, Any]],
    ordered_operations: Iterable[Mapping[str, Any]],
    plan_schema_version: str,
    canonical_encoding_version: str = CANONICAL_ENCODING_VERSION,
) -> SealedExecutionPlanSemanticPayload:
    """S5-05 compilation 산물(requirements·operations)을 exact basis 위에 봉인한다.

    ``active_field_requirements``·``ordered_operations`` 는 S5-05 가 이미 encode 한 JSON-safe dict 다
    (compilation.execution_basis_semantic_payload 의 같은 키). 이 함수는 그 참여 필드를 바꾸지 않고
    Plan payload 로 봉인만 한다. encoding version 은 fail-closed 로 지원 여부를 확인한다.
    """
    require_supported_encoding(canonical_encoding_version)
    _require_nonempty(plan_schema_version, "plan_schema_version")
    reqs, ops = canonicalize_execution_operations(
        active_field_requirements, ordered_operations
    )
    return SealedExecutionPlanSemanticPayload(
        plan_schema_version=plan_schema_version,
        canonical_encoding_version=canonical_encoding_version,
        execution_basis=execution_basis,
        active_field_requirements=reqs,
        ordered_operations=ops,
    )


def verify_sealed_plan_integrity(
    payload: SealedExecutionPlanSemanticPayload,
    *,
    supported_plan_schemas: Sequence[str],
) -> None:
    """Plan decode 최소 검증 — nested object 를 재canonicalize 해 재계산하고 구조 불변식을 강제한다.

    확인: supported plan schema·supported canonical encoding·ExecutionBasis nested digest 재계산·
    requirement↔operation bijection·operation order canonicality. unknown schema/encoding 은
    latest 로 fallback 하지 않고 fail-closed.
    """
    if payload.plan_schema_version not in supported_plan_schemas:
        raise UnsupportedPlanSchemaError(
            f"미지원 plan schema(latest fallback 없음): {payload.plan_schema_version!r}"
        )
    require_supported_encoding(payload.canonical_encoding_version)
    # ExecutionBasis nested digest 전부 재계산(주장값만 믿지 않는다).
    verify_execution_basis_integrity(payload.execution_basis)
    _verify_requirement_operation_bijection(payload)
    _verify_operation_order_canonicality(payload)


def _verify_requirement_operation_bijection(
    payload: SealedExecutionPlanSemanticPayload,
) -> None:
    """requirement ↔ APPLY_FIELD_BINDING 을 **순서까지** 대조하고, 각 requirement 의 value_expression 이
    basis 의 effective binding rule 과 일치함을 강제한다(field 이름만 보지 않는다).

    - 집합 bijection·중복 0 (기존).
    - APPLY field 순서 == requirement field 순서 — array 순서가 Plan identity 의 일부이고 compiler 가
      APPLY 순서를 active_logical_field_order 로 고정하므로, 순서 뒤섞임을 거절한다.
    - COMPLETE requirement 의 value_expression == 대응 effective binding rule 의 value_expression —
      field 는 그대로 두고 source key/constant 만 바꾼 위조 Plan 을 잡는다.
    """
    req_fields = [
        _field_id(r, "active field requirement") for r in payload.active_field_requirements
    ]
    apply_fields = [
        _field_id(o, "APPLY_FIELD_BINDING operation")
        for o in payload.ordered_operations
        if o.get("op") == PLAN_APPLY_FIELD_BINDING
    ]
    if len(set(req_fields)) != len(req_fields):
        raise ExecutionPlanIntegrityError("active field requirement field 중복")
    if len(set(apply_fields)) != len(apply_fields):
        raise ExecutionPlanIntegrityError("APPLY_FIELD_BINDING field 중복")
    if req_fields != apply_fields:
        raise ExecutionPlanIntegrityError(
            "requirement ↔ APPLY_FIELD_BINDING 순서/집합 불일치"
        )
    rule_ve = {
        r.field_id: encode_value_expression(r.value_expression)
        for r in payload.execution_basis.field_binding.effective_active_binding_rules
    }
    for req in payload.active_field_requirements:
        field_id = _field_id(req, "active field requirement")
        expected = rule_ve.get(field_id)
        if expected is None:
            raise ExecutionPlanIntegrityError(
                f"requirement {field_id!r} 에 대응하는 effective binding rule 이 없다"
            )
        if req.get("value_expression") != expected:
            raise ExecutionPlanIntegrityError(
                f"requirement {field_id!r} 의 value_expression 이 effective binding rule 과 불일치"
            )


def _verify_operation_order_canonicality(
    payload: SealedExecutionPlanSemanticPayload,
) -> None:
    """canonical operation order: 모든 REMOVE_OPTION 이 모든 APPLY_FIELD_BINDING 앞에 온다."""
    seen_apply = False
    for op in payload.ordered_operations:
        code = op.get("op")
        if code == PLAN_APPLY_FIELD_BINDING:
            seen_apply = True
        elif code == PLAN_REMOVE_OPTION:
            if seen_apply:
                raise ExecutionPlanIntegrityError(
                    "operation order 비canonical: REMOVE_OPTION 이 APPLY_FIELD_BINDING 뒤에 온다"
                )
            # operand 검증 — 빈/비문자열 slot·option 을 decode 경계에서 통과시키지 않는다.
            for name in ("slot_id", "option_id"):
                value = op.get(name)
                if not isinstance(value, str) or value == "":
                    raise ExecutionPlanIntegrityError(
                        f"REMOVE_OPTION 에 {name} 가 없다/비어 있다"
                    )
        else:
            raise ExecutionPlanIntegrityError(f"미지원 operation code: {code!r}")


def _field_id(entry: Mapping[str, Any], what: str) -> str:
    value = entry.get("field_id")
    if not isinstance(value, str) or value == "":
        raise ExecutionPlanIntegrityError(f"{what} 에 field_id 가 없다")
    return value


# ─── PlanCompilationKey ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PlanCompilationKey:
    """(execution_basis_digest, plan_schema_version, canonical_encoding_version).

    불변식: 한 key 는 최대 하나의 ``plan_semantic_digest`` 를 갖는다. 같은 execution basis 라도
    plan schema/encoding version 이 다르면 다른 key → 다른 Plan digest 가 허용된다.
    """

    execution_basis_digest: str
    plan_schema_version: str
    canonical_encoding_version: str


def plan_compilation_key_of(payload: SealedExecutionPlanSemanticPayload) -> PlanCompilationKey:
    return PlanCompilationKey(
        execution_basis_digest=execution_basis_digest(payload.execution_basis),
        plan_schema_version=payload.plan_schema_version,
        canonical_encoding_version=payload.canonical_encoding_version,
    )


def encode_plan_compilation_key(key: PlanCompilationKey) -> dict[str, Any]:
    return {
        "execution_basis_digest": key.execution_basis_digest,
        "plan_schema_version": key.plan_schema_version,
        "canonical_encoding_version": key.canonical_encoding_version,
    }


def plan_compilation_key_digest(key: PlanCompilationKey) -> str:
    """PlanCompilationKey 의 canonical content-address."""
    return canonical_execution_digest(encode_plan_compilation_key(key))


class PlanCompilationLedger:
    """functional dependency 계약: PlanCompilationKey → 최대 1 plan_semantic_digest.

    같은 key 에서 다른 plan digest 가 관찰되면 EXECUTION_PLAN_COMPILATION_INTEGRITY_ERROR. 이 검사는
    끌 수 없다(record 가 유일한 삽입 경로다). durable store/publication 은 S5-07 소유다 — 여기서는
    functional dependency 판정만 진다.
    """

    def __init__(self) -> None:
        self._by_key: dict[str, str] = {}

    def record(self, key: PlanCompilationKey, plan_digest: str) -> None:
        key_digest = plan_compilation_key_digest(key)
        existing = self._by_key.get(key_digest)
        if existing is not None and existing != plan_digest:
            raise ExecutionPlanCompilationIntegrityError(
                f"PlanCompilationKey 가 서로 다른 plan digest 로 매핑됨: {existing} != {plan_digest}"
            )
        self._by_key[key_digest] = plan_digest

    def get(self, key: PlanCompilationKey) -> str | None:
        return self._by_key.get(plan_compilation_key_digest(key))


# ─── DurableSealCaptureEvidence codec seam ─────────────────────────────────────────────
@dataclass(frozen=True)
class CaptureEvidenceProvenance:
    """digest 에서 제외되지만 lossless 저장이 필요한 exact S4 provenance.

    같은 semantic input 을 다른 authority revision 에서 관찰할 수 있으므로 capture evidence record
    key 를 semantic digest 하나로 삼지 않는다 — provenance 가 그 구분을 진다.
    """

    field_binding_authority_revision: str
    source_configuration_version: str
    captured_at: str


@dataclass(frozen=True)
class CompleteSealCaptureEvidence:
    captured_execution_input_semantic_projection: Mapping[str, Any]
    captured_execution_input_digest: str
    provenance: CaptureEvidenceProvenance


@dataclass(frozen=True)
class AttemptSealCaptureEvidence:
    captured_attempt_semantic_projection: Mapping[str, Any]
    captured_attempt_digest: str
    normalized_blockers: tuple[str, ...]
    provenance: CaptureEvidenceProvenance


DurableSealCaptureEvidence = CompleteSealCaptureEvidence | AttemptSealCaptureEvidence

_COMPLETE = "COMPLETE"
_ATTEMPT = "ATTEMPT"


def _encode_provenance(p: CaptureEvidenceProvenance) -> dict[str, Any]:
    return {
        "field_binding_authority_revision": p.field_binding_authority_revision,
        "source_configuration_version": p.source_configuration_version,
        "captured_at": p.captured_at,
    }


def encode_durable_capture_evidence(evidence: DurableSealCaptureEvidence) -> dict[str, Any]:
    """capture semantic payload + exact provenance 를 lossless dict 로(store layout 은 S5-07).

    semantic digest 는 semantic projection 의 canonical digest 와 정합해야 한다 — 위조는 encode 시점에
    시끄럽게 닫힌다.
    """
    if isinstance(evidence, CompleteSealCaptureEvidence):
        projection = dict(evidence.captured_execution_input_semantic_projection)
        if canonical_execution_digest(projection) != evidence.captured_execution_input_digest:
            raise DurableCaptureEvidenceIntegrityError(
                "captured_execution_input_digest 가 semantic projection 과 불일치"
            )
        return {
            "kind": _COMPLETE,
            "semantic_projection": projection,
            "semantic_digest": evidence.captured_execution_input_digest,
            "provenance": _encode_provenance(evidence.provenance),
        }
    projection = dict(evidence.captured_attempt_semantic_projection)
    if canonical_execution_digest(projection) != evidence.captured_attempt_digest:
        raise DurableCaptureEvidenceIntegrityError(
            "captured_attempt_digest 가 semantic projection 과 불일치"
        )
    return {
        "kind": _ATTEMPT,
        "semantic_projection": projection,
        "semantic_digest": evidence.captured_attempt_digest,
        "normalized_blockers": list(evidence.normalized_blockers),
        "provenance": _encode_provenance(evidence.provenance),
    }


def _decode_provenance(value: object) -> CaptureEvidenceProvenance:
    if not isinstance(value, Mapping):
        raise DurableCaptureEvidenceIntegrityError("provenance 가 매핑이 아니다")
    def _prov_str(field: str) -> str:
        raw = value.get(field)
        # str() 강제 변환 금지 — null/number/list/mapping 을 조용히 문자열로 만들지 않고 fail-closed.
        if not isinstance(raw, str) or raw == "":
            raise DurableCaptureEvidenceIntegrityError(
                f"provenance.{field} 는 비어 있지 않은 문자열이어야 한다"
            )
        return raw

    return CaptureEvidenceProvenance(
        field_binding_authority_revision=_prov_str("field_binding_authority_revision"),
        source_configuration_version=_prov_str("source_configuration_version"),
        captured_at=_prov_str("captured_at"),
    )


def decode_durable_capture_evidence(payload: object) -> DurableSealCaptureEvidence:
    """persisted dict → capture evidence + semantic digest 재계산 검증(신뢰 경계).

    semantic digest 는 semantic projection 에서 재계산해 저장값과 대조한다 — digest 만 맞는 garbage
    를 조용히 통과시키지 않는다. unknown kind 는 fail-closed.
    """
    if not isinstance(payload, Mapping):
        raise DurableCaptureEvidenceIntegrityError("capture evidence 가 매핑이 아니다")
    kind = payload.get("kind")
    projection = payload.get("semantic_projection")
    stored_digest = payload.get("semantic_digest")
    if not isinstance(projection, Mapping) or not isinstance(stored_digest, str):
        raise DurableCaptureEvidenceIntegrityError("capture evidence 형식 불량")
    projection = dict(projection)
    if canonical_execution_digest(projection) != stored_digest:
        raise DurableCaptureEvidenceIntegrityError("semantic digest 재계산 불일치")
    provenance = _decode_provenance(payload.get("provenance"))
    if kind == _COMPLETE:
        return CompleteSealCaptureEvidence(
            captured_execution_input_semantic_projection=projection,
            captured_execution_input_digest=stored_digest,
            provenance=provenance,
        )
    if kind == _ATTEMPT:
        blockers = payload.get("normalized_blockers")
        if not isinstance(blockers, list) or not all(isinstance(b, str) for b in blockers):
            raise DurableCaptureEvidenceIntegrityError("normalized_blockers 형식 불량")
        return AttemptSealCaptureEvidence(
            captured_attempt_semantic_projection=projection,
            captured_attempt_digest=stored_digest,
            normalized_blockers=tuple(blockers),
            provenance=provenance,
        )
    raise DurableCaptureEvidenceIntegrityError(f"미지원 capture evidence kind: {kind!r}")
