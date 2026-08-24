"""exact Application Context 조립 + cross-reference 무결성 게이트 (S4-04 · #674).

Work 의 current WorkTemplateApplication 에서 시작해 PASS Evidence → Revision +
Profile Manifest + Structure Projection → exact registry 를 지나 `SlotConfigurationContext`
와 `ExactAppliedTemplateInput` 을 조립한다. 이 모듈은 **신뢰 경계 coordinator** 다:
current pointer·evidence·revision·manifest·projection 이 서로 정합인지 전건 대조하고,
한 항목이라도 깨지면 다른 object 나 latest 값으로 보완하지 않고 fail-closed 한다.

정상 경로 금지 I/O: mutable HWPX source read 0 · HWPX parse 0 · Qualification 재실행 0 ·
latest Revision/Evidence 검색 0 · Structure 복제 저장 0. Structure 는 PASS Evidence 의
historical projection 을 decode 할 뿐이고, applied bytes 는 S3 Candidate blob 을 **참조만** 한다.

소유 밖: 공유 fence(#675)·reconciliation(#676)·command/CAS(#677)·Projection DTO(#678)·
token/API(#679)·Snapshot(#680)·run bridge(#681). route/token 검증은 안 한다(#679).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from hwpxfiller.application.qualification_evidence import (
    PASS,
    QualificationEvidence,
    QualificationProfileManifest,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.application.work_template_state import (
    WorkTemplateStateAggregate,
)
from hwpxfiller.domain.slot_selection import (
    DEFAULT_SELECTION_SEMANTIC_REGISTRY,
    SelectionSemanticBindingKey,
    SelectionSemanticContractManifest,
    SelectionSemanticContractRegistry,
)

# ─── candidate revision 타입은 결과 모델에 값으로만 실린다(순환 import 회피) ───────────
from hwpxfiller.application.candidate_revision import TemplateRevision


class SlotConfigurationContextError(ValueError):
    """S4-04 context 조립·무결성 오류의 뿌리."""

    code = "SLOT_CONFIGURATION_CONTEXT_ERROR"


class TemplateInitializationRequired(SlotConfigurationContextError):
    code = "TEMPLATE_INITIALIZATION_REQUIRED"


class StaleTemplateApplication(SlotConfigurationContextError):
    code = "STALE_TEMPLATE_APPLICATION"


class UnsupportedTemplateStructureProjection(SlotConfigurationContextError):
    code = "UNSUPPORTED_TEMPLATE_STRUCTURE_PROJECTION"


class TemplateStructureIntegrityError(SlotConfigurationContextError):
    code = "TEMPLATE_STRUCTURE_INTEGRITY_ERROR"


class AppliedTemplateContentIntegrityError(SlotConfigurationContextError):
    code = "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR"


class CrossWorkContext(SlotConfigurationContextError):
    code = "CROSS_WORK_CONTEXT"


# ─── 주입 read Port(application 은 external 을 import 하지 않는다) ────────────────────
class WorkTemplateStateReadPort(Protocol):
    def load(self, work_id: str) -> "WorkTemplateStateAggregate | None": ...


class QualificationReadPort(Protocol):
    def get_evidence(self, evidence_id: str) -> QualificationEvidence: ...

    def get_manifest(
        self, qualification_profile_id: str
    ) -> QualificationProfileManifest: ...


class AppliedCandidateReadPort(Protocol):
    def get_revision(self, revision_id: str) -> TemplateRevision: ...

    def has_blob(self, digest: str) -> bool: ...


# ─── Structure Projection decoder registry ──────────────────────────────────────
StructureDecoderFn = Callable[[Mapping[str, Any]], TemplateStructure]


def _str_list(value: object, what: str) -> tuple[str, ...]:
    """리스트이고 항목이 전부 문자열일 때만 tuple 로 — 스칼라 문자열을 char 로 안 쪼갠다."""
    if not isinstance(value, list):
        raise TemplateStructureIntegrityError(f"{what} 는 리스트여야 한다")
    for item in value:
        if not isinstance(item, str):
            raise TemplateStructureIntegrityError(f"{what} 항목은 문자열이어야 한다")
    return tuple(value)


def _str_field(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise TemplateStructureIntegrityError(f"{what} 는 문자열이어야 한다")
    return value


def _label_field(value: object, what: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TemplateStructureIntegrityError(
            f"{what} 는 null 또는 비어 있지 않은 문자열이어야 한다"
        )
    return value


def _decode_product_structure(
    payload: Mapping[str, Any], *, schema: str, include_labels: bool
) -> TemplateStructure:
    try:
        slots_raw = payload["slots"]
        root_fields = _str_list(payload["root_fields"], "root_fields")
        if not isinstance(slots_raw, list):
            raise TemplateStructureIntegrityError("slots 는 리스트여야 한다")
        slots = []
        for slot in slots_raw:
            if not isinstance(slot, Mapping):
                raise TemplateStructureIntegrityError("slot 항목이 매핑이 아니다")
            options_raw = slot["options"]
            if not isinstance(options_raw, list):
                raise TemplateStructureIntegrityError("options 는 리스트여야 한다")
            options = []
            for opt in options_raw:
                if not isinstance(opt, Mapping):
                    raise TemplateStructureIntegrityError("option 항목이 매핑이 아니다")
                options.append(
                    TemplateOption(
                        id=_str_field(opt["id"], "option.id"),
                        fields=_str_list(opt["fields"], "option.fields"),
                        label=(
                            _label_field(opt["label"], "option.label")
                            if include_labels
                            else None
                        ),
                    )
                )
            slots.append(
                TemplateSlot(
                    id=_str_field(slot["id"], "slot.id"),
                    shared_fields=_str_list(slot["shared_fields"], "slot.shared_fields"),
                    options=tuple(options),
                    label=(
                        _label_field(slot["label"], "slot.label")
                        if include_labels
                        else None
                    ),
                )
            )
        return TemplateStructure(root_fields=root_fields, slots=tuple(slots))
    except (KeyError, TypeError, AttributeError) as exc:
        raise TemplateStructureIntegrityError(
            f"structure projection payload 가 {schema} 형식과 불일치"
        ) from exc


def _decode_structure_v1(payload: Mapping[str, Any]) -> TemplateStructure:
    """hwpx-structure-projection-v1 payload → TemplateStructure(project_structure 의 역).

    digest 유효해도 형이 틀린 payload(예: ``root_fields: "title"``)는 조용히 char 로
    쪼개지 않고 시끄럽게 거절한다 — 이 decoder 가 persisted projection 의 신뢰 경계다.
    """
    return _decode_product_structure(payload, schema="v1", include_labels=False)


def _decode_structure_v2(payload: Mapping[str, Any]) -> TemplateStructure:
    """hwpx-structure-projection-v2 payload → TemplateStructure(product structure만).

    S4 는 selection 에 필요한 제품 구조(root/shared/option Field·순서)만 lossless projection
    하고 composition-only fact(occurrence/region/relation/envelope/resolver)는 S4 Configuration
    권위로 복제하지 않는다. product_structure 하위 dict 는 v1 payload 와 같은 shape 라 v1
    decoder 를 재사용한다.
    """
    product = payload.get("product_structure")
    if not isinstance(product, Mapping):
        raise TemplateStructureIntegrityError(
            "v2 projection payload 에 product_structure 매핑이 없다"
        )
    return _decode_structure_v1(product)


def _decode_structure_v3(payload: Mapping[str, Any]) -> TemplateStructure:
    """hwpx-structure-projection-v3 의 canonical Slot/Option label 을 복원한다."""
    return _decode_product_structure(payload, schema="v3", include_labels=True)


def _decode_structure_v4(payload: Mapping[str, Any]) -> TemplateStructure:
    """hwpx-structure-projection-v4 payload → TemplateStructure(label 포함 product structure).

    v4 는 v2 의 composition-ready shape 에 canonical label 을 더한 shipping schema 다(#773).
    S4 는 v2 때와 똑같이 ``product_structure`` 만 읽고 composition-only fact(occurrence/region/
    relation/envelope/resolver)는 S4 권위로 복제하지 않는다 — 다른 점은 label 뿐이다.
    """
    product = payload.get("product_structure")
    if not isinstance(product, Mapping):
        raise TemplateStructureIntegrityError(
            "v4 projection payload 에 product_structure 매핑이 없다"
        )
    return _decode_product_structure(product, schema="v4", include_labels=True)


def _decode_structure_txt_v1(payload: Mapping[str, Any]) -> TemplateStructure:
    """txt-structure-projection-v1 payload → TemplateStructure(label 포함 product structure).

    **S10-04(#861)에서 shape 이 한 겹 깊어졌다.** TXT profile 이 composition-ready 로 올라서면서
    (:data:`~hwpxfiller.application.execution_structure.TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA`)
    payload 는 v4 와 같이 ``product_structure`` 로 싸인 execution projection 이다. schema 이름을
    올리지 않은 것은 TXT 가 미출하라 되읽을 durable 사용자 payload 가 없기 때문이고, 그 이름에
    S10-03 의 selection binding key 가 걸려 있어 개명이 더 비싸기 때문이다.

    label 은 실린다 — TXT 의 Slot/Option label 은 사용자가 저작한 이름이라 안 읽으면 화면에
    내부 ID 가 뜬다. composition-only fact(occurrence/region/relation/envelope/resolver)는 v2/v4
    때와 똑같이 **읽지 않는다**: S4 는 selection 에 필요한 제품 구조만 복원한다.
    """
    product = payload.get("product_structure")
    if not isinstance(product, Mapping):
        raise TemplateStructureIntegrityError(
            "txt-v1 projection payload 에 product_structure 매핑이 없다"
        )
    return _decode_product_structure(product, schema="txt-v1", include_labels=True)


class StructureProjectionDecoderRegistry:
    """immutable projection-schema → decoder registry — unknown schema 를 latest 로 안 푼다."""

    def __init__(
        self, decoders: Iterable[tuple[str, StructureDecoderFn]]
    ) -> None:
        self._by_schema: dict[str, StructureDecoderFn] = {}
        for schema_version, decoder in decoders:
            if schema_version in self._by_schema:
                raise TemplateStructureIntegrityError(
                    f"decoder schema 중복 등록: {schema_version}"
                )
            self._by_schema[schema_version] = decoder

    def resolve(self, projection_schema_version: str) -> StructureDecoderFn:
        decoder = self._by_schema.get(projection_schema_version)
        if decoder is None:
            raise UnsupportedTemplateStructureProjection(
                f"미지원 structure projection schema: {projection_schema_version}"
            )
        return decoder


DEFAULT_STRUCTURE_DECODER_REGISTRY = StructureProjectionDecoderRegistry(
    [
        ("hwpx-structure-projection-v1", _decode_structure_v1),
        ("hwpx-structure-projection-v2", _decode_structure_v2),
        ("hwpx-structure-projection-v3", _decode_structure_v3),
        ("hwpx-structure-projection-v4", _decode_structure_v4),
        ("txt-structure-projection-v1", _decode_structure_txt_v1),
    ]
)


# ─── 결과 모델 ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SlotConfigurationContext:
    workspace_instance_id: str
    work_id: str
    template_application_id: str
    template_lineage_id: str
    application_epoch: int
    pass_evidence_id: str
    revision_id: str
    qualification_profile_id: str
    structure_projection_schema_version: str
    template_structure: TemplateStructure
    template_structure_digest: str
    selection_semantic_contract_id: str
    selection_semantic_contract: SelectionSemanticContractManifest


@dataclass(frozen=True)
class ExactAppliedTemplateInput:
    work_id: str
    template_application_id: str
    revision_id: str
    media: str
    template_lineage_id: str
    exact_content_digest: str
    canonical_blob_reference: str


# ─── 조립 + 무결성 ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _VerifiedChain:
    aggregate: WorkTemplateStateAggregate
    application_id: str
    application_epoch: int
    evidence: QualificationEvidence
    revision: TemplateRevision
    manifest: QualificationProfileManifest


def _resolve_verified_chain(
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    expected_work_authority_id: str,
    expected_application_id: str | None,
) -> _VerifiedChain:
    """exact chain 을 걷고 issue 가 열거한 cross-reference 를 전건 대조한다."""
    aggregate = work_state.load(expected_work_authority_id)
    if aggregate is None:
        raise TemplateInitializationRequired(
            f"work {expected_work_authority_id} 는 template application 이 없다"
        )
    work = aggregate.work
    if work.work_id != expected_work_authority_id:
        raise CrossWorkContext("aggregate work_id 가 요청 WorkAuthorityId 와 불일치")

    current_id = work.current_template_application_id
    if not current_id:
        raise TemplateInitializationRequired("current template application 부재")
    # S4 는 current Application 만 소비한다 — expected 를 줬는데 current 가 아니면 stale.
    if expected_application_id is not None and expected_application_id != current_id:
        raise StaleTemplateApplication(
            f"요청 Application {expected_application_id} 는 current({current_id}) 가 아니다"
        )
    application = next(
        (a for a in aggregate.applications if a.application_id == current_id), None
    )
    if application is None:
        raise TemplateStructureIntegrityError("current pointer 가 applications 에 없다")
    if application.work_id != expected_work_authority_id:
        raise CrossWorkContext("Application.work_id 가 요청 WorkAuthorityId 와 불일치")

    evidence = qualification.get_evidence(application.pass_evidence_id)
    if evidence.evidence_id != application.pass_evidence_id:
        raise TemplateStructureIntegrityError("Evidence id 가 Application 참조와 불일치")
    if evidence.result != PASS:
        raise TemplateStructureIntegrityError("current Application 의 Evidence 가 PASS 가 아니다")
    projection = evidence.structure_projection
    if projection is None:
        raise TemplateStructureIntegrityError("PASS Evidence 에 structure projection 부재")

    revision = candidate.get_revision(evidence.revision_id)
    if revision.revision_id != evidence.revision_id:
        raise TemplateStructureIntegrityError("Revision id 가 Evidence 참조와 불일치")
    if revision.template_lineage_id != work.template_lineage_id:
        raise TemplateStructureIntegrityError("Revision lineage 가 Work lineage 와 불일치")

    manifest = qualification.get_manifest(evidence.qualification_profile_id)
    if manifest.qualification_profile_id != evidence.qualification_profile_id:
        raise TemplateStructureIntegrityError("Manifest profile 이 Evidence 와 불일치")
    if manifest.media != revision.media:
        raise TemplateStructureIntegrityError("Manifest media 가 Revision media 와 불일치")
    if manifest.projection_schema_version != projection.projection_schema_version:
        raise TemplateStructureIntegrityError(
            "Manifest projection schema 가 Evidence projection schema 와 불일치"
        )
    return _VerifiedChain(
        aggregate=aggregate,
        application_id=current_id,
        application_epoch=application.application_epoch,
        evidence=evidence,
        revision=revision,
        manifest=manifest,
    )


def resolve_slot_configuration_context(
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    workspace_instance_id: str,
    expected_work_authority_id: str,
    expected_application_id: str | None = None,
    *,
    decoder_registry: StructureProjectionDecoderRegistry = (
        DEFAULT_STRUCTURE_DECODER_REGISTRY
    ),
    selection_registry: SelectionSemanticContractRegistry = (
        DEFAULT_SELECTION_SEMANTIC_REGISTRY
    ),
) -> SlotConfigurationContext:
    chain = _resolve_verified_chain(
        work_state, qualification, candidate,
        expected_work_authority_id, expected_application_id,
    )
    evidence = chain.evidence
    projection = evidence.structure_projection
    assert projection is not None  # _resolve_verified_chain 이 보장
    schema_version = projection.projection_schema_version

    # exact decoder — unknown schema 는 latest 로 풀지 않는다.
    decoder = decoder_registry.resolve(schema_version)
    structure = decoder(projection.payload)

    # exact selection binding — (profile, projection schema) → contract, latest fallback 없음.
    binding_key = SelectionSemanticBindingKey(
        qualification_profile_id=evidence.qualification_profile_id,
        structure_projection_schema_version=schema_version,
    )
    contract = selection_registry.resolve(binding_key)

    return SlotConfigurationContext(
        workspace_instance_id=workspace_instance_id,
        work_id=chain.aggregate.work.work_id,
        template_application_id=chain.application_id,
        template_lineage_id=chain.aggregate.work.template_lineage_id,
        application_epoch=chain.application_epoch,
        pass_evidence_id=evidence.evidence_id,
        revision_id=evidence.revision_id,
        qualification_profile_id=evidence.qualification_profile_id,
        structure_projection_schema_version=schema_version,
        template_structure=structure,
        # S4 는 digest 를 새로 만들지 않는다 — PASS Evidence 의 payload_digest 를 그대로 싣는다.
        template_structure_digest=projection.payload_digest,
        selection_semantic_contract_id=contract.contract_id,
        selection_semantic_contract=contract,
    )


def resolve_exact_applied_template_input(
    work_state: WorkTemplateStateReadPort,
    qualification: QualificationReadPort,
    candidate: AppliedCandidateReadPort,
    expected_work_authority_id: str,
    expected_application_id: str,
) -> ExactAppliedTemplateInput:
    """applied Candidate 의 exact canonical blob 을 **참조**로 돌려준다(bytes read·parse 0)."""
    chain = _resolve_verified_chain(
        work_state, qualification, candidate,
        expected_work_authority_id, expected_application_id,
    )
    revision = chain.revision
    # exact applied bytes 는 S3 Candidate blob 을 가리킨다 — 존재·digest 결속만 확인하고
    # bytes 를 읽거나 재직렬화하지 않는다.
    if not candidate.has_blob(revision.exact_content_digest):
        raise AppliedTemplateContentIntegrityError(
            f"applied Candidate blob 부재: {revision.exact_content_digest}"
        )
    return ExactAppliedTemplateInput(
        work_id=chain.aggregate.work.work_id,
        template_application_id=chain.application_id,
        revision_id=revision.revision_id,
        media=revision.media,
        template_lineage_id=revision.template_lineage_id,
        exact_content_digest=revision.exact_content_digest,
        canonical_blob_reference=revision.exact_content_digest,
    )
