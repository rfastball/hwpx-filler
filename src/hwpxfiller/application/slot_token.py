"""HMAC-authenticated signed configuration token (S4-09 · #679).

**AEAD 아님**(설계 정정 2026-08-16): claims confidentiality 는 비요구다. installation secret 으로
HMAC-SHA256 서명해 integrity·authenticity 만 보장한다. token 은 Product consumer 에게 opaque 하되
내부적으로는 평문 claims 를 담는다 — secret 없이는 위조·변조가 불가능하고(hmac.compare_digest),
서명이 안 맞으면 fail-closed 다. native 암호 의존성·AEAD nonce·key_id·rotation 은 도입하지 않는다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass

TOKEN_SCHEME = "hfslot1"
TOKEN_SCHEMA_VERSION = "slot-configuration-token/v1"
TOKEN_PURPOSE = "SLOT_CONFIGURATION"
ACTOR_BINDING_SCHEME = "slot-actor-binding/v1"
_U32_MAX = 0xFFFF_FFFF


class ConfigurationTokenError(Exception):
    """token codec 오류의 뿌리."""


class InvalidConfigurationToken(ConfigurationTokenError):
    code = "INVALID_CONFIGURATION_TOKEN"


class TokenPurposeMismatch(ConfigurationTokenError):
    code = "TOKEN_PURPOSE_MISMATCH"


@dataclass(frozen=True)
class ConfigurationTokenClaims:
    token_schema_version: str
    token_purpose: str
    workspace_instance_id: str
    work_authority_id: str
    template_application_id: str
    selection_semantic_contract_id: str
    configuration_presence: bool
    configuration_version: int | None
    actor_binding_digest: str
    issued_at: str


def _text(value: str) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > _U32_MAX:
        raise ConfigurationTokenError("token text 가 u32 범위 초과")
    return len(raw).to_bytes(4, "big") + raw


def _opt_u32(value: int | None) -> bytes:
    if value is None:
        return b"\x00"
    if value < 0 or value > _U32_MAX:
        raise ConfigurationTokenError("token u32 값이 범위 초과")
    return b"\x01" + value.to_bytes(4, "big")


def _canonical(c: ConfigurationTokenClaims) -> bytes:
    out = bytearray()
    out += _text(c.token_schema_version)
    out += _text(c.token_purpose)
    out += _text(c.workspace_instance_id)
    out += _text(c.work_authority_id)
    out += _text(c.template_application_id)
    out += _text(c.selection_semantic_contract_id)
    out += b"\x01" if c.configuration_presence else b"\x00"
    out += _opt_u32(c.configuration_version)
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
            raise InvalidConfigurationToken("token claims 절단")
        chunk = self._data[self._i : self._i + n]
        self._i += n
        return chunk

    def text(self) -> str:
        n = int.from_bytes(self._take(4), "big")
        return self._take(n).decode("utf-8")

    def bool1(self) -> bool:
        tag = self._take(1)
        if tag not in (b"\x00", b"\x01"):
            raise InvalidConfigurationToken("token bool tag 손상")
        return tag == b"\x01"

    def opt_u32(self) -> int | None:
        tag = self._take(1)
        if tag == b"\x00":
            return None
        if tag != b"\x01":
            raise InvalidConfigurationToken("token opt tag 손상")
        return int.from_bytes(self._take(4), "big")

    def at_end(self) -> bool:
        return self._i == len(self._data)


def actor_binding_digest(authorization_subject: str, workspace_instance_id: str) -> str:
    """stable authorization subject + workspace scope → versioned digest.

    process session ID 에서 만들지 않는다 — restart-verifiable token 이므로 재시작 뒤에도 같은
    값이어야 한다(#679).
    """
    material = (
        _text(ACTOR_BINDING_SCHEME)
        + _text(authorization_subject)
        + _text(workspace_instance_id)
    )
    return "sha256:" + hashlib.sha256(material).hexdigest()


def sign_configuration_token(claims: ConfigurationTokenClaims, secret: bytes) -> str:
    """claims 를 installation secret 으로 HMAC-SHA256 서명해 opaque token 문자열을 낸다."""
    if claims.token_schema_version != TOKEN_SCHEMA_VERSION:
        raise ConfigurationTokenError("claims token_schema_version 불일치")
    if claims.token_purpose != TOKEN_PURPOSE:
        raise ConfigurationTokenError("claims token_purpose 불일치")
    payload = _b64e(_canonical(claims))
    signed = f"{TOKEN_SCHEME}.{payload}"
    tag = hmac.new(secret, signed.encode("ascii"), hashlib.sha256).digest()
    return f"{signed}.{_b64e(tag)}"


def open_configuration_token(token: str, secret: bytes) -> ConfigurationTokenClaims:
    """서명을 검증하고 claims 를 복원한다. tamper·형식 손상 → INVALID, purpose 불일치 → MISMATCH."""
    if not isinstance(token, str):
        raise InvalidConfigurationToken("token 이 문자열이 아니다")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_SCHEME:
        raise InvalidConfigurationToken("token 형식 불일치")
    try:
        claims_bytes = _b64d(parts[1])
        tag = _b64d(parts[2])
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise InvalidConfigurationToken("token base64 손상") from exc
    expected = hmac.new(
        secret, f"{parts[0]}.{parts[1]}".encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, tag):
        raise InvalidConfigurationToken("token 서명 불일치(tamper·secret)")
    reader = _Reader(claims_bytes)
    try:
        claims = ConfigurationTokenClaims(
            token_schema_version=reader.text(),
            token_purpose=reader.text(),
            workspace_instance_id=reader.text(),
            work_authority_id=reader.text(),
            template_application_id=reader.text(),
            selection_semantic_contract_id=reader.text(),
            configuration_presence=reader.bool1(),
            configuration_version=reader.opt_u32(),
            actor_binding_digest=reader.text(),
            issued_at=reader.text(),
        )
    except InvalidConfigurationToken:
        raise
    except (UnicodeDecodeError, ValueError) as exc:
        raise InvalidConfigurationToken("token claims 파싱 실패") from exc
    if not reader.at_end():
        raise InvalidConfigurationToken("token claims 잉여 바이트")
    if claims.token_purpose != TOKEN_PURPOSE:
        raise TokenPurposeMismatch(f"token purpose {claims.token_purpose!r}")
    if claims.token_schema_version != TOKEN_SCHEMA_VERSION:
        raise InvalidConfigurationToken(f"token schema {claims.token_schema_version!r}")
    return claims
