"""ServiceKey 비밀정보 마스킹의 순수 Domain 정본.

값을 알면 원문과 URL 인코딩 변형을 모두 지우고, 값을 몰라도 ``ServiceKey=``
파라미터명으로 지운다. 애매하면 과삭제하며 값·부분문자열·해시를 남기지 않는다.
"""

from __future__ import annotations

import re
import urllib.parse

__all__ = ["REDACTED", "redact", "redact_url"]

REDACTED = "[REDACTED]"

# ``ServiceKey=<값>`` / ``serviceKey=`` / ``service_key=`` 를 파라미터명으로 인식.
# 값을 몰라도(예: 우리가 만들지 않은 HTTPError 의 URL) 파라미터명만으로 지운다.
_PARAM_RE = re.compile(r"(?i)(service[_-]?key=)([^&\s#\"'<>]*)")


def redact(text: str, secret: "str | None" = None) -> str:
    """``text`` 에서 ServiceKey 흔적을 ``[REDACTED]`` 로 전면 치환.

    - ``secret`` 이 주어지면 **원문·퍼센트인코딩**(``quote``/``quote_plus``) 변형 모두 삭제.
    - ``secret`` 유무와 무관하게 **파라미터명**(``ServiceKey=...``)의 값을 삭제 —
      키 값을 모르는 URL/예외도 안전하게 마스킹된다.

    과삭제 원칙: 애매하면 지운다. 값의 해시조차 남기지 않는다.
    """
    if not text:
        return text
    out = text
    if secret:
        # 긴 변형부터 치환해 부분 겹침으로 인한 누락을 막는다.
        variants = {
            secret,
            urllib.parse.quote(secret, safe=""),
            urllib.parse.quote_plus(secret),
        }
        for variant in sorted((v for v in variants if v), key=len, reverse=True):
            out = out.replace(variant, REDACTED)
    out = _PARAM_RE.sub(lambda m: m.group(1) + REDACTED, out)
    return out


def redact_url(url: str, secret: "str | None" = None) -> str:
    """URL 전용 편의 래퍼 — 값 미상이어도 ``ServiceKey=`` 파라미터를 마스킹."""
    return redact(url, secret)
