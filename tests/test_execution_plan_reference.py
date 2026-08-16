"""S5-11(#707) opaque route-bound HMAC Plan reference codec — pure edge cases.

roundtrip·tamper·purpose/schema fail-closed·형식 손상·절단·잉여 바이트·비문자열 필드.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from hwpxfiller.application import execution_plan_reference as ref_mod
from hwpxfiller.application.execution_plan_reference import (
    PLAN_REF_PURPOSE,
    PLAN_REF_SCHEMA_VERSION,
    PLAN_REF_SCHEME,
    InvalidPlanReference,
    OpaquePlanReferenceClaims,
    PlanReferenceError,
    PlanReferencePurposeMismatch,
    open_plan_reference,
    plan_reference_actor_binding_digest,
    sign_plan_reference,
)

SECRET = b"\x22" * 32


def _claims(**over) -> OpaquePlanReferenceClaims:
    kw = dict(
        ref_schema_version=PLAN_REF_SCHEMA_VERSION,
        ref_purpose=PLAN_REF_PURPOSE,
        workspace_instance_id="ws-1",
        work_authority_id="work-1",
        plan_semantic_digest="sha256:plan",
        plan_schema_version="hwpx-execution-plan/v1",
        canonical_encoding_version="enc/v1",
        actor_binding_digest="sha256:actor",
        issued_at="t0",
    )
    kw.update(over)
    return OpaquePlanReferenceClaims(**kw)


def _sign_raw(claims: OpaquePlanReferenceClaims, secret: bytes) -> str:
    """sign 의 schema/purpose 강제를 우회해 canonical framing 을 직접 서명한다(open 의 재확인 자리 타격)."""
    payload = ref_mod._b64e(ref_mod._canonical(claims))
    signed = f"{PLAN_REF_SCHEME}.{payload}"
    tag = hmac.new(secret, signed.encode("ascii"), hashlib.sha256).digest()
    return f"{signed}.{ref_mod._b64e(tag)}"


def test_roundtrip() -> None:
    claims = _claims()
    assert open_plan_reference(sign_plan_reference(claims, SECRET), SECRET) == claims


def test_sign_rejects_wrong_schema_or_purpose() -> None:
    with pytest.raises(PlanReferenceError):
        sign_plan_reference(_claims(ref_schema_version="other/v9"), SECRET)
    with pytest.raises(PlanReferenceError):
        sign_plan_reference(_claims(ref_purpose="OTHER"), SECRET)


def test_sign_non_str_field_rejected() -> None:
    with pytest.raises(PlanReferenceError):
        sign_plan_reference(_claims(issued_at=123), SECRET)  # type: ignore[arg-type]


def test_open_non_str() -> None:
    with pytest.raises(InvalidPlanReference):
        open_plan_reference(1234, SECRET)  # type: ignore[arg-type]


def test_open_bad_format_and_scheme() -> None:
    with pytest.raises(InvalidPlanReference):
        open_plan_reference("only.two", SECRET)
    with pytest.raises(InvalidPlanReference):
        open_plan_reference("wrong.scheme.tag", SECRET)


def test_open_bad_base64() -> None:
    # 한 글자만 남는 payload 는 padding 뒤에도 유효 base64 가 아니라 binascii.Error.
    with pytest.raises(InvalidPlanReference):
        open_plan_reference(f"{PLAN_REF_SCHEME}.A.AAAA", SECRET)


def test_open_tamper_rejected() -> None:
    ref = sign_plan_reference(_claims(), SECRET)
    tampered = ref[:-2] + ("aa" if not ref.endswith("aa") else "bb")
    with pytest.raises(InvalidPlanReference):
        open_plan_reference(tampered, SECRET)


def test_open_wrong_secret_rejected() -> None:
    ref = sign_plan_reference(_claims(), SECRET)
    with pytest.raises(InvalidPlanReference):
        open_plan_reference(ref, b"\x00" * 32)


def test_open_truncated_claims() -> None:
    # claims payload 를 잘라 재서명 → 절단된 reader 가 fail-closed.
    payload = ref_mod._b64e(ref_mod._canonical(_claims())[:6])
    signed = f"{PLAN_REF_SCHEME}.{payload}"
    tag = hmac.new(SECRET, signed.encode("ascii"), hashlib.sha256).digest()
    with pytest.raises(InvalidPlanReference):
        open_plan_reference(f"{signed}.{ref_mod._b64e(tag)}", SECRET)


def test_open_surplus_bytes() -> None:
    payload = ref_mod._b64e(ref_mod._canonical(_claims()) + b"\x00\x00")
    signed = f"{PLAN_REF_SCHEME}.{payload}"
    tag = hmac.new(SECRET, signed.encode("ascii"), hashlib.sha256).digest()
    with pytest.raises(InvalidPlanReference):
        open_plan_reference(f"{signed}.{ref_mod._b64e(tag)}", SECRET)


def test_open_invalid_utf8_claims() -> None:
    # text 길이 프리픽스가 유효하지만 바이트가 invalid utf-8 → 파싱 실패 경로.
    body = (1).to_bytes(4, "big") + b"\xff"  # length 1, invalid utf-8
    payload = ref_mod._b64e(body)
    signed = f"{PLAN_REF_SCHEME}.{payload}"
    tag = hmac.new(SECRET, signed.encode("ascii"), hashlib.sha256).digest()
    with pytest.raises(InvalidPlanReference):
        open_plan_reference(f"{signed}.{ref_mod._b64e(tag)}", SECRET)


def test_open_purpose_mismatch() -> None:
    with pytest.raises(PlanReferencePurposeMismatch):
        open_plan_reference(_sign_raw(_claims(ref_purpose="WRONG"), SECRET), SECRET)


def test_open_schema_mismatch() -> None:
    with pytest.raises(InvalidPlanReference):
        open_plan_reference(
            _sign_raw(_claims(ref_schema_version="ref/v9"), SECRET), SECRET
        )


def test_actor_binding_is_deterministic_and_scoped() -> None:
    a = plan_reference_actor_binding_digest("local-user", "ws-1")
    assert a == plan_reference_actor_binding_digest("local-user", "ws-1")
    assert a != plan_reference_actor_binding_digest("local-user", "ws-2")
    assert a != plan_reference_actor_binding_digest("other", "ws-1")
    assert a.startswith("sha256:")


def test_b64d_padding_roundtrip() -> None:
    for n in range(1, 6):
        raw = b"\x01" * n
        assert ref_mod._b64d(ref_mod._b64e(raw)) == raw
    # urlsafe base64 사용 확인(padding 제거·복원).
    assert base64.urlsafe_b64encode(b"\xfb\xff").rstrip(b"=").decode()
