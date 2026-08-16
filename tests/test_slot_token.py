"""S4-09(#679) HMAC-signed configuration token codec + installation secret."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest

from hwpxfiller.application import slot_token as st
from hwpxfiller.application.slot_token import (
    TOKEN_PURPOSE,
    TOKEN_SCHEMA_VERSION,
    ConfigurationTokenClaims,
    InvalidConfigurationToken,
    TokenPurposeMismatch,
    actor_binding_digest,
    open_configuration_token,
    sign_configuration_token,
)
from hwpxfiller.external.slot_token_secret import (
    SlotTokenSecretError,
    SlotTokenSecretStore,
)

SECRET = b"\x11" * 32


def _claims(**over) -> ConfigurationTokenClaims:
    base = dict(
        token_schema_version=TOKEN_SCHEMA_VERSION,
        token_purpose=TOKEN_PURPOSE,
        workspace_instance_id="ws-1",
        work_authority_id="W-1",
        template_application_id="A18",
        selection_semantic_contract_id="slot-selection/v1",
        configuration_presence=True,
        configuration_version=7,
        actor_binding_digest="sha256:actor",
        issued_at="2026-08-16T00:00:00",
    )
    base.update(over)
    return ConfigurationTokenClaims(**base)


def _sign_raw(claims: ConfigurationTokenClaims, secret: bytes) -> str:
    # sign 은 purpose/schema 를 강제하므로, open 의 그 거부 분기를 시험하려면 저수준으로 만든다.
    payload = st._b64e(st._canonical(claims))
    signed = f"{st.TOKEN_SCHEME}.{payload}"
    tag = hmac.new(secret, signed.encode("ascii"), hashlib.sha256).digest()
    return f"{signed}.{st._b64e(tag)}"


def test_round_trip() -> None:
    token = sign_configuration_token(_claims(), SECRET)
    assert open_configuration_token(token, SECRET) == _claims()


def test_optional_version_none_round_trips() -> None:
    token = sign_configuration_token(_claims(configuration_version=None, configuration_presence=False), SECRET)
    got = open_configuration_token(token, SECRET)
    assert got.configuration_version is None and got.configuration_presence is False


def test_tamper_rejected() -> None:
    token = sign_configuration_token(_claims(), SECRET)
    # payload 한 글자 뒤집기 → 서명 불일치.
    parts = token.split(".")
    flipped = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
    with pytest.raises(InvalidConfigurationToken):
        open_configuration_token(f"{parts[0]}.{flipped}.{parts[2]}", SECRET)


def test_wrong_secret_rejected() -> None:
    token = sign_configuration_token(_claims(), SECRET)
    with pytest.raises(InvalidConfigurationToken):
        open_configuration_token(token, b"\x22" * 32)


@pytest.mark.parametrize("bad", ["", "nope", "a.b", "hfslot1.@@@.@@@", "wrong.x.y"])
def test_malformed_token_rejected(bad: str) -> None:
    with pytest.raises(InvalidConfigurationToken):
        open_configuration_token(bad, SECRET)


def test_purpose_mismatch_rejected() -> None:
    token = _sign_raw(_claims(token_purpose="OTHER"), SECRET)
    with pytest.raises(TokenPurposeMismatch):
        open_configuration_token(token, SECRET)


def test_schema_mismatch_rejected() -> None:
    token = _sign_raw(_claims(token_schema_version="slot-configuration-token/v2"), SECRET)
    with pytest.raises(InvalidConfigurationToken):
        open_configuration_token(token, SECRET)


def _sign_bytes(claims_bytes: bytes, secret: bytes) -> str:
    signed = f"{st.TOKEN_SCHEME}.{st._b64e(claims_bytes)}"
    tag = hmac.new(secret, signed.encode("ascii"), hashlib.sha256).digest()
    return f"{signed}.{st._b64e(tag)}"


def test_truncated_claims_rejected() -> None:
    # HMAC 은 유효하지만 claims 바이트가 잘려 reader 가 절단을 만난다.
    token = _sign_bytes(b"\x00\x00\x00\x04ab", SECRET)  # u32 len=4 인데 2바이트만
    with pytest.raises(InvalidConfigurationToken):
        open_configuration_token(token, SECRET)


def test_trailing_bytes_rejected() -> None:
    full = st._canonical(_claims())
    token = _sign_bytes(full + b"\x99", SECRET)  # 잉여 바이트
    with pytest.raises(InvalidConfigurationToken):
        open_configuration_token(token, SECRET)


def test_version_overflow_on_sign_rejected() -> None:
    from hwpxfiller.application.slot_token import ConfigurationTokenError

    with pytest.raises(ConfigurationTokenError):
        sign_configuration_token(_claims(configuration_version=0x1_0000_0000), SECRET)


def test_sign_guards_purpose_and_schema() -> None:
    from hwpxfiller.application.slot_token import ConfigurationTokenError

    with pytest.raises(ConfigurationTokenError):
        sign_configuration_token(_claims(token_purpose="X"), SECRET)
    with pytest.raises(ConfigurationTokenError):
        sign_configuration_token(_claims(token_schema_version="X"), SECRET)


# ── actor binding ─────────────────────────────────────────────────────────────
def test_actor_binding_stable_and_scoped() -> None:
    a = actor_binding_digest("local-user", "ws-1")
    assert actor_binding_digest("local-user", "ws-1") == a  # session 무관, 재계산 동일
    assert actor_binding_digest("local-user", "ws-2") != a  # workspace scope
    assert actor_binding_digest("other", "ws-1") != a  # subject


# ── installation secret ───────────────────────────────────────────────────────
def test_secret_create_once_and_restart(tmp_path: Path) -> None:
    store = SlotTokenSecretStore(tmp_path)
    s1 = store.load_or_create_active_secret()
    assert store.load_or_create_active_secret() == s1  # 재호출 동일
    assert SlotTokenSecretStore(tmp_path).load_or_create_active_secret() == s1  # restart 동일
    assert len(s1) == 32


def test_secret_corruption_fails_closed(tmp_path: Path) -> None:
    store = SlotTokenSecretStore(tmp_path)
    store.load_or_create_active_secret()
    path = tmp_path / "slot_token_secret.json"
    env = json.loads(path.read_text("utf-8"))
    env["content"]["secret_b64"] = "dGFtcGVyZWQ="  # digest 재계산 안 함
    path.write_text(json.dumps(env), "utf-8")
    with pytest.raises(SlotTokenSecretError):
        SlotTokenSecretStore(tmp_path).load_or_create_active_secret()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda env: env["content"].update(schema_version="other/v2"),
        lambda env: env["content"].update(secret_b64="!!!not-base64!!!"),
        lambda env: env.clear(),  # content 키 없음
    ],
)
def test_secret_various_corruption_fail_closed(tmp_path: Path, mutate) -> None:
    store = SlotTokenSecretStore(tmp_path)
    store.load_or_create_active_secret()
    path = tmp_path / "slot_token_secret.json"
    env = json.loads(path.read_text("utf-8"))
    mutate(env)
    # digest 는 손상 후 재계산하지 않으므로 대부분 digest 단계에서, content 삭제는 형식에서 걸린다.
    path.write_text(json.dumps(env), "utf-8")
    with pytest.raises(SlotTokenSecretError):
        SlotTokenSecretStore(tmp_path).load_or_create_active_secret()


@pytest.mark.parametrize("content", [
    {"schema_version": "other/v2", "secret_b64": "AAAA"},  # digest 유효·schema 미상
    {"schema_version": "slot-token-secret/v1", "secret_b64": "!!!"},  # digest 유효·base64 손상
])
def test_secret_wellformed_but_wrong_content_fails_closed(tmp_path: Path, content) -> None:
    from hwpxfiller.application.qualification_evidence import content_digest

    path = tmp_path / "slot_token_secret.json"
    path.write_text(json.dumps({"digest": content_digest(content), "content": content}), "utf-8")
    with pytest.raises(SlotTokenSecretError):
        SlotTokenSecretStore(tmp_path).load_or_create_active_secret()


def test_restart_opens_token_signed_with_durable_secret(tmp_path: Path) -> None:
    secret = SlotTokenSecretStore(tmp_path).load_or_create_active_secret()
    token = sign_configuration_token(_claims(), secret)
    # "restart": 새 store 인스턴스가 같은 secret 을 읽어 token 을 검증한다.
    reloaded = SlotTokenSecretStore(tmp_path).load_or_create_active_secret()
    assert open_configuration_token(token, reloaded) == _claims()
