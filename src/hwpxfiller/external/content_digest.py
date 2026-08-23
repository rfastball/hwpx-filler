"""blob content digest 의 단일 산식 (S7-01 · #823).

``sha256:<hex>`` 라는 문자열 모양 하나에 materialization 의 산출 증거(``output_digest``)와
안착 파일 관찰(:mod:`hwpxfiller.external.artifact_observation`)의 대조가 동시에 걸린다. 두
자리가 각자 sha256 을 쓰면 산식이 조용히 갈라질 수 있어(접두어 유무·hexdigest 대소문자) 대조
자체가 무의미해진다 — 그래서 함수 하나를 공유한다(#820 D1: 관찰은 기록 digest 와의 대조로만
성립한다).
"""

from __future__ import annotations

from hashlib import sha256


def blob_digest(blob: bytes) -> str:
    return "sha256:" + sha256(blob).hexdigest()


__all__ = ["blob_digest"]
