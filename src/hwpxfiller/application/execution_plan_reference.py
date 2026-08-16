"""opaque route-bound HMAC-signed Plan reference (S5-11 · #707).

Product route 가 raw ``plan_semantic_digest`` 를 직접 신뢰하지 않게 하는 restart-verifiable signed
wrapper 다. ``plan_semantic_digest`` 를 대체하는 새 identity 가 아니라 그 위에 얹는 route-bound
signed reference 다 — random Plan ID 를 만들지 않는다. installation secret 으로 HMAC-SHA256 서명해
integrity·authenticity 만 보장한다(**AEAD 아님**, claims confidentiality 비요구, S4-09 정정과 동일).

opaque ref 문자열·signature·issued_at 은 Plan/request semantic identity·idempotency fingerprint 에
**참여하지 않는다**. 서명이 안 맞으면 fail-closed. purpose·schema·workspace·Work 결속은 open 이후
Product API 가 route 와 **독립 비교**해 mismatch 를 시끄럽게 거절한다(여기서는 self-consistency 만).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass

PLAN_REF_SCHEME = "hfplan1"
PLAN_REF_SCHEMA_VERSION = "sealed-execution-plan-ref/v1"
PLAN_REF_PURPOSE = "sealed-execution-plan-ref/v1"
PLAN_REF_ACTOR_BINDING_SCHEME = "plan-ref-actor-binding/v1"
_U32_MAX = 0xFFFF_FFFF


class PlanReferenceError(Exception):
    """opaque Plan ref codec 오류의 뿌리."""


class InvalidPlanReference(PlanReferenceError):
    code = "PLAN_REFERENCE_INVALID"


class PlanReferencePurposeMismatch(PlanReferenceError):
    code = "PLAN_REFERENCE_PURPOSE_MISMATCH"


@dataclass(frozen=True)
class OpaquePlanReferenceClaims:
    """평문 claims — secret 없이는 위조·변조 불가(HMAC). digest identity 는 이 안에 복원된다."""

    ref_schema_version: str
    ref_purpose: str
    workspace_instance_id: str
    work_authority_id: str
    plan_semantic_digest: str
    plan_schema_version: str
    canonical_encoding_version: str
    actor_binding_digest: str
    issued_at: str


def _text(value: str) -> bytes:
    if not isinstance(value, str):
        raise PlanReferenceError("ref 필드는 문자열이어야 한다")
    raw = value.encode("utf-8")
    if len(raw) > _U32_MAX:
        raise PlanReferenceError("ref text 가 u32 범위 초과")
    return len(raw).to_bytes(4, "big") + raw


def _canonical(c: OpaquePlanReferenceClaims) -> bytes:
    out = bytearray()
    out += _text(c.ref_schema_version)
    out += _text(c.ref_purpose)
    out += _text(c.workspace_instance_id)
    out += _text(c.work_authority_id)
    out += _text(c.plan_semantic_digest)
    out += _text(c.plan_schema_version)
    out += _text(c.canonical_encoding_version)
    out += _text(c.actor_binding_digest)
    out += _text(c.issued_at)
    return bytes(out)


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class _Reader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._i = 0

    def _take(self, n: int) -> bytes:
        if self._i + n > len(self._data):
            raise InvalidPlanReference("ref claims 절단")
        chunk = self._data[self._i : self._i + n]
        self._i += n
        return chunk

    def text(self) -> str:
        n = int.from_bytes(self._take(4), "big")
        return self._take(n).decode("utf-8")

    def at_end(self) -> bool:
        return self._i == len(self._data)


def plan_reference_actor_binding_digest(
    authorization_subject: str, workspace_instance_id: str
) -> str:
    """stable authorization subject + workspace scope → versioned digest(restart-verifiable).

    process session ID 에서 만들지 않는다 — 재시작 뒤에도 같은 값이어야 opaque ref 가 검증된다.
    slot token 의 actor binding 과 scheme 이 달라 cross-purpose replay 도 배제한다.
    """
    material = (
        _text(PLAN_REF_ACTOR_BINDING_SCHEME)
        + _text(authorization_subject)
        + _text(workspace_instance_id)
    )
    return "sha256:" + hashlib.sha256(material).hexdigest()


def sign_plan_reference(claims: OpaquePlanReferenceClaims, secret: bytes) -> str:
    """claims 를 installation secret 으로 HMAC-SHA256 서명해 opaque ref 문자열을 낸다."""
    if claims.ref_schema_version != PLAN_REF_SCHEMA_VERSION:
        raise PlanReferenceError("claims ref_schema_version 불일치")
    if claims.ref_purpose != PLAN_REF_PURPOSE:
        raise PlanReferenceError("claims ref_purpose 불일치")
    payload = _b64e(_canonical(claims))
    signed = f"{PLAN_REF_SCHEME}.{payload}"
    tag = hmac.new(secret, signed.encode("ascii"), hashlib.sha256).digest()
    return f"{signed}.{_b64e(tag)}"


def open_plan_reference(ref: str, secret: bytes) -> OpaquePlanReferenceClaims:
    """서명 검증 후 claims 복원. tamper·형식 손상 → INVALID, purpose 불일치 → PURPOSE_MISMATCH."""
    if not isinstance(ref, str):
        raise InvalidPlanReference("ref 가 문자열이 아니다")
    parts = ref.split(".")
    if len(parts) != 3 or parts[0] != PLAN_REF_SCHEME:
        raise InvalidPlanReference("ref 형식 불일치")
    try:
        claims_bytes = _b64d(parts[1])
        tag = _b64d(parts[2])
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise InvalidPlanReference("ref base64 손상") from exc
    expected = hmac.new(
        secret, f"{parts[0]}.{parts[1]}".encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, tag):
        raise InvalidPlanReference("ref 서명 불일치(tamper·secret)")
    reader = _Reader(claims_bytes)
    try:
        claims = OpaquePlanReferenceClaims(
            ref_schema_version=reader.text(),
            ref_purpose=reader.text(),
            workspace_instance_id=reader.text(),
            work_authority_id=reader.text(),
            plan_semantic_digest=reader.text(),
            plan_schema_version=reader.text(),
            canonical_encoding_version=reader.text(),
            actor_binding_digest=reader.text(),
            issued_at=reader.text(),
        )
    except InvalidPlanReference:
        raise
    except (UnicodeDecodeError, ValueError) as exc:
        raise InvalidPlanReference("ref claims 파싱 실패") from exc
    if not reader.at_end():
        raise InvalidPlanReference("ref claims 잉여 바이트")
    # purpose·schema 를 signed payload 안에서 재확인한다(latest/default fallback 없음).
    if claims.ref_purpose != PLAN_REF_PURPOSE:
        raise PlanReferencePurposeMismatch(f"ref purpose {claims.ref_purpose!r}")
    if claims.ref_schema_version != PLAN_REF_SCHEMA_VERSION:
        raise InvalidPlanReference(f"ref schema {claims.ref_schema_version!r}")
    return claims
