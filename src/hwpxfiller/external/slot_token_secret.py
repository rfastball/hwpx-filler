"""installation-scoped durable HMAC secret for configuration tokens (S4-09 · #679).

단일 active secret 을 create-once 로 심고 restart 뒤 그대로 읽는다. 손상은 fail-closed.
rotation·다중 key·key_id 는 비범위(설계 정정 2026-08-16 = HMAC signed token). SG-03(#735)에서
key-rotation UI/control plane·새 암호 라이브러리는 v1 목표에서 명시 제외됐다 — threat model
정본은 `docs/CONTROL_PLANE_SCOPE.md` §HMAC. secret 은 token 서명 integrity 만 지지하고
authorization/currentness 는 대체하지 않는다.
"""

from __future__ import annotations

import base64
import json
import secrets
import threading
from pathlib import Path

from hwpxfiller.application.qualification_evidence import content_digest

from .atomic import write_text_atomic

_FILENAME = "slot_token_secret.json"
_SCHEMA = "slot-token-secret/v1"
_SECRET_BYTES = 32


class SlotTokenSecretError(Exception):
    """secret 부재·손상 — token 검증이 fail-closed 로 INVALID 처리하도록 뿌리."""


# ponytail: process-local lock — single-writer desktop 전제. cross-process create-once 는
# v1 밖(#620). 두 프로세스가 최초 부팅에 동시에 mint 하면 하나가 이기고 나머지는 그 파일을 읽는다.
_mint_guard = threading.Lock()


class SlotTokenSecretStore:
    def __init__(self, root: "str | Path") -> None:
        self._path = Path(root).resolve() / _FILENAME

    def load_or_create_active_secret(self) -> bytes:
        if self._path.exists():
            return self._read()
        with _mint_guard:
            if self._path.exists():  # lock 안 재확인 — 경합에서 하나만 mint
                return self._read()
            secret = secrets.token_bytes(_SECRET_BYTES)
            content = {
                "schema_version": _SCHEMA,
                "secret_b64": base64.b64encode(secret).decode("ascii"),
            }
            envelope = {"digest": content_digest(content), "content": content}
            write_text_atomic(
                self._path, json.dumps(envelope, ensure_ascii=False, indent=2)
            )
            return secret

    def _read(self) -> bytes:
        try:
            envelope = json.loads(self._path.read_text(encoding="utf-8"))
            content = envelope["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SlotTokenSecretError("secret 파일 손상(JSON·형식)") from exc
        if envelope.get("digest") != content_digest(content):
            raise SlotTokenSecretError("secret digest 손상")
        if not isinstance(content, dict) or content.get("schema_version") != _SCHEMA:
            raise SlotTokenSecretError("secret schema 미상")
        try:
            # validate=True: 비알파벳 문자를 조용히 버리지 않고 손상으로 거절한다(fail-closed).
            secret = base64.b64decode(content["secret_b64"], validate=True)
        except (ValueError, KeyError, TypeError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
            raise SlotTokenSecretError("secret base64 손상") from exc
        if len(secret) != _SECRET_BYTES:
            raise SlotTokenSecretError("secret 길이 손상")
        return secret
