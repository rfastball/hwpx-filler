"""Immutable Qualification 영속 객체 — Profile Manifest·Attempt·Evidence (S3-01 #651).

S2 의 :func:`~hwpxfiller.application.template_qualification.qualify_template` 는
``revision_id + qualification_profile_id`` 에 결속된 PASS·FAIL·ATTEMPT ERROR 결과 *값* 을
낸다. 이 모듈은 그 결과를 S3 가 재사용할 **immutable persistent object** 로 바꾸되:

- Qualification semantics identity 는 ``qualification_profile_id`` 하나다
  (Profile 과 Contract 이중 identity 를 만들지 않는다).
- PASS Evidence 는 당시 :class:`TemplateStructure` projection 을 durable 하게 보존한다 —
  S4 는 binary 로 재실행하지 않고 이 projection 을 소비한다.
- ATTEMPT ERROR 는 Candidate FAIL 로 영속하지 않는다(Attempt 만, Evidence 없음).

불변식은 dataclass ``__post_init__`` 이 진다 — 어느 구성 경로로 만들든 깨진 객체는
생성 시점에 시끄럽게 거절된다(확인-또는-경보). 파일 create-once·digest 검증은
:mod:`hwpxfiller.external.qualification_store` 어댑터가 진다 — 여기는 native-free 모델·코덱이다.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .template_qualification import (
    TemplateQualificationAttemptErrored,
    TemplateQualificationFailed,
    TemplateQualificationPassed,
    TemplateQualificationResult,
    TemplateStructure,
)

PASS = "PASS"
FAIL = "FAIL"
ERROR = "ERROR"
_LABEL_PROJECTION_SCHEMA = "hwpx-structure-projection-v3"


class QualificationEvidenceError(ValueError):
    """Qualification 영속 객체의 불변식·결속 위반."""


def content_digest(payload: Any) -> str:
    """serializable payload 의 canonical(정렬·조밀) sha256 — 내용 주소·손상 검출용."""
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StructureProjection:
    """PASS 당시 TemplateStructure 의 durable historical payload (canonical bytes 대체 아님)."""

    projection_schema_version: str
    payload: Mapping[str, Any]
    payload_digest: str

    def __post_init__(self) -> None:
        if self.payload_digest != content_digest(self.payload):
            raise QualificationEvidenceError("structure projection payload_digest 불일치")


def project_structure(
    structure: TemplateStructure, projection_schema_version: str
) -> StructureProjection:
    """native-free TemplateStructure 를 serializable projection + digest 로 고정한다."""
    include_labels = projection_schema_version == _LABEL_PROJECTION_SCHEMA
    if not include_labels and any(
        slot.label is not None
        or any(option.label is not None for option in slot.options)
        for slot in structure.slots
    ):
        raise QualificationEvidenceError(
            "label-bearing structure requires hwpx-structure-projection-v3"
        )
    payload = {
        "root_fields": list(structure.root_fields),
        "slots": [
            {
                "id": slot.id,
                "shared_fields": list(slot.shared_fields),
                "options": [
                    {
                        "id": opt.id,
                        "fields": list(opt.fields),
                        **({"label": opt.label} if include_labels else {}),
                    }
                    for opt in slot.options
                ],
                **({"label": slot.label} if include_labels else {}),
            }
            for slot in structure.slots
        ],
    }
    return StructureProjection(projection_schema_version, payload, content_digest(payload))


@dataclass(frozen=True)
class QualificationProfileManifest:
    """qualification_profile_id 에 결속된 immutable semantic manifest."""

    qualification_profile_id: str
    media: str
    adapter_contract_version: str
    product_rule_version: str
    operation_alphabet_version: str
    projection_schema_version: str
    manifest_payload: Mapping[str, Any]
    manifest_digest: str
    created_at: str

    def __post_init__(self) -> None:
        if self.manifest_digest != content_digest(self.manifest_payload):
            raise QualificationEvidenceError("manifest_digest 가 manifest_payload 와 불일치")


def build_manifest(
    *,
    qualification_profile_id: str,
    media: str,
    adapter_contract_version: str,
    product_rule_version: str,
    operation_alphabet_version: str,
    projection_schema_version: str,
    manifest_payload: Mapping[str, Any],
    created_at: str,
) -> QualificationProfileManifest:
    # caller-owned payload 를 deep-copy 해 alias 를 끊는다 — frozen dataclass 는 attribute
    # 재바인딩만 막고 nested mapping/list 는 못 막는다. 사본 위에서 digest 를 계산·보존해야
    # build 이후 원본을 고쳐도 저장 digest 가 stale 해지지 않는다.
    manifest_payload = copy.deepcopy(dict(manifest_payload))
    return QualificationProfileManifest(
        qualification_profile_id=qualification_profile_id,
        media=media,
        adapter_contract_version=adapter_contract_version,
        product_rule_version=product_rule_version,
        operation_alphabet_version=operation_alphabet_version,
        projection_schema_version=projection_schema_version,
        manifest_payload=manifest_payload,
        manifest_digest=content_digest(manifest_payload),
        created_at=created_at,
    )


@dataclass(frozen=True)
class QualificationProfileRevocation:
    """Manifest 를 수정하지 않고 남기는 별도 immutable revocation record."""

    qualification_profile_id: str
    reason: str
    authority: str
    revoked_at: str


class ProfileIdentityMismatch(QualificationEvidenceError):
    """runtime Profile.id 와 저장된 Manifest.qualification_profile_id 불일치."""


def verify_runtime_profile(
    manifest: QualificationProfileManifest, runtime_profile_id: str
) -> None:
    """불일치하면 qualification 을 시작하지 않고 integrity error 로 닫는다."""
    if manifest.qualification_profile_id != runtime_profile_id:
        raise ProfileIdentityMismatch(
            f"runtime profile {runtime_profile_id!r} != manifest "
            f"{manifest.qualification_profile_id!r}"
        )


@dataclass(frozen=True)
class QualificationAttempt:
    """PASS·FAIL·ERROR 한 번의 immutable 실행 기록."""

    attempt_id: str
    preparation_id: str
    revision_id: str
    qualification_profile_id: str
    outcome: str
    evidence_id: str | None
    error_code: str | None
    started_at: str
    completed_at: str

    def __post_init__(self) -> None:
        if self.outcome not in (PASS, FAIL, ERROR):
            raise QualificationEvidenceError(f"미상 outcome {self.outcome!r}")
        if self.outcome == ERROR:
            if self.evidence_id is not None:
                raise QualificationEvidenceError("ERROR Attempt 는 Evidence 를 갖지 않는다")
            if not self.error_code:
                raise QualificationEvidenceError("ERROR Attempt 는 error_code 가 필수다")
        else:
            if self.evidence_id is None:
                raise QualificationEvidenceError(f"{self.outcome} Attempt 는 Evidence 가 필수다")
            if self.error_code is not None:
                raise QualificationEvidenceError(
                    f"{self.outcome} Attempt 에 error_code 가 있으면 안 된다"
                )


@dataclass(frozen=True)
class QualificationEvidence:
    """exact Revision + exact Profile 의 PASS/FAIL attestation."""

    evidence_id: str
    attempt_id: str
    revision_id: str
    qualification_profile_id: str
    result: str
    structure_projection: StructureProjection | None
    diagnostics: tuple[Mapping[str, str], ...]
    engine_metadata: Mapping[str, str]
    qualified_at: str

    def __post_init__(self) -> None:
        if self.result == PASS:
            if self.structure_projection is None:
                raise QualificationEvidenceError("PASS Evidence 는 structure projection 이 필수다")
            if self.diagnostics:
                raise QualificationEvidenceError("PASS Evidence 에 diagnostics 가 있으면 안 된다")
        elif self.result == FAIL:
            if self.structure_projection is not None:
                raise QualificationEvidenceError("FAIL Evidence 에 structure 가 있으면 안 된다")
            if not self.diagnostics:
                raise QualificationEvidenceError("FAIL Evidence 는 diagnostics 가 1개 이상이다")
        else:
            raise QualificationEvidenceError(f"Evidence result 는 PASS|FAIL 뿐 ({self.result!r})")


def build_records(
    result: TemplateQualificationResult,
    *,
    attempt_id: str,
    preparation_id: str,
    evidence_id: str,
    projection_schema_version: str,
    engine_metadata: Mapping[str, str],
    started_at: str,
    completed_at: str,
    qualified_at: str,
) -> tuple[QualificationAttempt, QualificationEvidence | None]:
    """S2 결과 하나를 immutable Attempt(+PASS/FAIL 이면 Evidence)로 고정한다.

    ATTEMPT ERROR 는 Evidence 없이 Attempt 만 낸다.
    """
    engine_metadata = copy.deepcopy(dict(engine_metadata))  # caller alias 차단(build_manifest 동형)
    if isinstance(result, TemplateQualificationAttemptErrored):
        attempt = QualificationAttempt(
            attempt_id=attempt_id,
            preparation_id=preparation_id,
            revision_id=result.revision_id,
            qualification_profile_id=result.qualification_profile_id,
            outcome=ERROR,
            evidence_id=None,
            error_code=result.error_code,
            started_at=started_at,
            completed_at=completed_at,
        )
        return attempt, None

    if isinstance(result, TemplateQualificationPassed):
        evidence = QualificationEvidence(
            evidence_id=evidence_id,
            attempt_id=attempt_id,
            revision_id=result.revision_id,
            qualification_profile_id=result.qualification_profile_id,
            result=PASS,
            structure_projection=project_structure(
                result.structure, projection_schema_version
            ),
            diagnostics=(),
            engine_metadata=engine_metadata,
            qualified_at=qualified_at,
        )
        outcome = PASS
    elif isinstance(result, TemplateQualificationFailed):
        evidence = QualificationEvidence(
            evidence_id=evidence_id,
            attempt_id=attempt_id,
            revision_id=result.revision_id,
            qualification_profile_id=result.qualification_profile_id,
            result=FAIL,
            structure_projection=None,
            diagnostics=tuple(
                {"kind": d.kind, "message": d.message} for d in result.diagnostics
            ),
            engine_metadata=engine_metadata,
            qualified_at=qualified_at,
        )
        outcome = FAIL
    else:  # pragma: no cover - 합 타입 소진
        raise QualificationEvidenceError(f"미상 qualification 결과 {type(result).__name__}")

    attempt = QualificationAttempt(
        attempt_id=attempt_id,
        preparation_id=preparation_id,
        revision_id=result.revision_id,
        qualification_profile_id=result.qualification_profile_id,
        outcome=outcome,
        evidence_id=evidence_id,
        error_code=None,
        started_at=started_at,
        completed_at=completed_at,
    )
    return attempt, evidence


def validate_evidence_binding(
    attempt: QualificationAttempt, evidence: QualificationEvidence
) -> None:
    """Evidence 가 자기 Attempt 의 exact revision/profile/outcome 에 결속됨을 강제한다."""
    if evidence.attempt_id != attempt.attempt_id:
        raise QualificationEvidenceError("Evidence.attempt_id 가 Attempt 와 불일치")
    if attempt.evidence_id != evidence.evidence_id:
        raise QualificationEvidenceError("Attempt.evidence_id 가 Evidence 와 불일치")
    if evidence.revision_id != attempt.revision_id:
        raise QualificationEvidenceError("Evidence revision 이 Attempt 와 불일치")
    if evidence.qualification_profile_id != attempt.qualification_profile_id:
        raise QualificationEvidenceError("Evidence profile 이 Attempt 와 불일치")
    if evidence.result != attempt.outcome:
        raise QualificationEvidenceError("Evidence result 가 Attempt outcome 과 불일치")


# ─── codec: 저장 어댑터가 쓰는 native-free dict ↔ 값 ──────────────────────────

def encode_manifest(manifest: QualificationProfileManifest) -> dict[str, Any]:
    return {
        "qualification_profile_id": manifest.qualification_profile_id,
        "media": manifest.media,
        "adapter_contract_version": manifest.adapter_contract_version,
        "product_rule_version": manifest.product_rule_version,
        "operation_alphabet_version": manifest.operation_alphabet_version,
        "projection_schema_version": manifest.projection_schema_version,
        "manifest_payload": dict(manifest.manifest_payload),
        "manifest_digest": manifest.manifest_digest,
        "created_at": manifest.created_at,
    }


def decode_manifest(data: Mapping[str, Any]) -> QualificationProfileManifest:
    return QualificationProfileManifest(
        qualification_profile_id=data["qualification_profile_id"],
        media=data["media"],
        adapter_contract_version=data["adapter_contract_version"],
        product_rule_version=data["product_rule_version"],
        operation_alphabet_version=data["operation_alphabet_version"],
        projection_schema_version=data["projection_schema_version"],
        manifest_payload=data["manifest_payload"],
        manifest_digest=data["manifest_digest"],
        created_at=data["created_at"],
    )


def encode_revocation(revocation: QualificationProfileRevocation) -> dict[str, Any]:
    return {
        "qualification_profile_id": revocation.qualification_profile_id,
        "reason": revocation.reason,
        "authority": revocation.authority,
        "revoked_at": revocation.revoked_at,
    }


def decode_revocation(data: Mapping[str, Any]) -> QualificationProfileRevocation:
    return QualificationProfileRevocation(
        qualification_profile_id=data["qualification_profile_id"],
        reason=data["reason"],
        authority=data["authority"],
        revoked_at=data["revoked_at"],
    )


def encode_attempt(attempt: QualificationAttempt) -> dict[str, Any]:
    return {
        "attempt_id": attempt.attempt_id,
        "preparation_id": attempt.preparation_id,
        "revision_id": attempt.revision_id,
        "qualification_profile_id": attempt.qualification_profile_id,
        "outcome": attempt.outcome,
        "evidence_id": attempt.evidence_id,
        "error_code": attempt.error_code,
        "started_at": attempt.started_at,
        "completed_at": attempt.completed_at,
    }


def decode_attempt(data: Mapping[str, Any]) -> QualificationAttempt:
    return QualificationAttempt(
        attempt_id=data["attempt_id"],
        preparation_id=data["preparation_id"],
        revision_id=data["revision_id"],
        qualification_profile_id=data["qualification_profile_id"],
        outcome=data["outcome"],
        evidence_id=data["evidence_id"],
        error_code=data["error_code"],
        started_at=data["started_at"],
        completed_at=data["completed_at"],
    )


def _encode_projection(projection: StructureProjection) -> dict[str, Any]:
    return {
        "projection_schema_version": projection.projection_schema_version,
        "payload": dict(projection.payload),
        "payload_digest": projection.payload_digest,
    }


def encode_evidence(evidence: QualificationEvidence) -> dict[str, Any]:
    projection = evidence.structure_projection
    return {
        "evidence_id": evidence.evidence_id,
        "attempt_id": evidence.attempt_id,
        "revision_id": evidence.revision_id,
        "qualification_profile_id": evidence.qualification_profile_id,
        "result": evidence.result,
        "structure_projection": (
            _encode_projection(projection) if projection is not None else None
        ),
        "diagnostics": [dict(d) for d in evidence.diagnostics],
        "engine_metadata": dict(evidence.engine_metadata),
        "qualified_at": evidence.qualified_at,
    }


def decode_evidence(data: Mapping[str, Any]) -> QualificationEvidence:
    raw = data["structure_projection"]
    projection = (
        StructureProjection(
            raw["projection_schema_version"], raw["payload"], raw["payload_digest"]
        )
        if raw is not None
        else None
    )
    return QualificationEvidence(
        evidence_id=data["evidence_id"],
        attempt_id=data["attempt_id"],
        revision_id=data["revision_id"],
        qualification_profile_id=data["qualification_profile_id"],
        result=data["result"],
        structure_projection=projection,
        diagnostics=tuple(dict(d) for d in data["diagnostics"]),
        engine_metadata=data["engine_metadata"],
        qualified_at=data["qualified_at"],
    )
