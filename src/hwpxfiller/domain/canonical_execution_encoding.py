"""S5 실행 semantic 의 closed canonical byte framing — capture·basis·Plan digest 단일 출처(S5-06 · #702).

S5-02..05 는 semantic payload 와 stable ordering 만 고정하고 byte framing·SHA-256 은
``# ponytail:`` 로컬 encoder 로 대신했다(정렬 JSON content_digest). 이 모듈이 그 자리를 대신하는
**closed byte framing set** 이다: JSON-value 의미 모델(None·bool·int·str·list·map)을 versioned
binary 로 정본화해, 같은 의미가 dict/저장 순서와 무관하게 같은 bytes·같은 digest 를 낸다.

:mod:`hwpxfiller.domain.slot_selection` 의 framing 규율을 그대로 따른다:
8-byte MAGIC + length-prefixed UTF-8(u32 big-endian) + typed tag + map key 를 UTF-8 byte order
로 정렬. Python·TypeScript(:mod:`frontend/src/domain/canonical_execution_encoding.ts`)가 같은
golden vector(:file:`tests/fixtures/execution_canonical_v1_golden.json`)를 재현한다.

금지(issue #702): JSON object order·Python dict/repr·float semantic identity·host locale.
float 은 semantic identity 를 갖지 않으므로 시끄럽게 거절한다. bool 은 int 서브타입이라 int 보다
**먼저** 판별한다(조용한 1/0 오인 차단).

PURE domain: 저장소·HWPX·native·application 을 import 하지 않는다.
"""

from __future__ import annotations

import hashlib

_U32_MAX = 0xFFFF_FFFF
_U64_MAX = 0xFFFF_FFFF_FFFF_FFFF

# canonical encoding v1 상수 — 코드·TS 미러·golden vector 단일 출처.
_MAGIC = b"HFPXEC1\0"  # exact 8 bytes
CANONICAL_ENCODING_VERSION = "execution-canonical/v1"

# value tag(closed) — 두 언어가 같은 상수를 쓴다.
_TAG_NULL = 0x00
_TAG_FALSE = 0x01
_TAG_TRUE = 0x02
_TAG_INT = 0x03
_TAG_STR = 0x04
_TAG_ARRAY = 0x05
_TAG_MAP = 0x06


class CanonicalExecutionEncodingError(Exception):
    """canonical 값 encoding 규율 위반(float·overflow·미지원 타입·lone surrogate)."""

    code = "CANONICAL_EXECUTION_ENCODING_ERROR"


class UnsupportedCanonicalEncodingError(Exception):
    """미지원 canonical encoding version — latest 로 fallback 하지 않는다."""

    code = "UNSUPPORTED_CANONICAL_ENCODING"


def _u32(value: int) -> bytes:
    if value < 0 or value > _U32_MAX:
        raise CanonicalExecutionEncodingError(f"count/length 가 u32 범위 초과: {value}")
    return value.to_bytes(4, "big")


def _utf8(value: str) -> bytes:
    """유효한 Unicode scalar sequence 만 UTF-8 로 인코딩한다(lone surrogate 거절)."""
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as exc:  # lone surrogate·invalid scalar
        raise CanonicalExecutionEncodingError("텍스트에 유효하지 않은 Unicode scalar") from exc


def _text(value: str) -> bytes:
    raw = _utf8(value)
    return _u32(len(raw)) + raw


def _encode_value(value: object, out: bytearray) -> None:
    """JSON-value 의미 모델을 canonical binary 로 재귀 인코딩한다.

    bool 을 int 보다 먼저 판별한다(`isinstance(True, int)` 가 True). float·기타 타입은 semantic
    identity 를 갖지 않으므로 거절한다 — 조용한 강제 변환 없음.
    """
    if value is None:
        out.append(_TAG_NULL)
    elif value is True:
        out.append(_TAG_TRUE)
    elif value is False:
        out.append(_TAG_FALSE)
    elif isinstance(value, int):
        magnitude = abs(value)
        if magnitude > _U64_MAX:
            raise CanonicalExecutionEncodingError(f"정수 magnitude 가 u64 범위 초과: {value}")
        out.append(_TAG_INT)
        out.append(0x01 if value < 0 else 0x00)
        out += magnitude.to_bytes(8, "big")
    elif isinstance(value, str):
        out.append(_TAG_STR)
        out += _text(value)
    elif isinstance(value, (list, tuple)):
        out.append(_TAG_ARRAY)
        out += _u32(len(value))
        for item in value:
            _encode_value(item, out)
    elif isinstance(value, dict):
        out.append(_TAG_MAP)
        out += _u32(len(value))
        # map key 를 UTF-8 byte order 로 정렬 — 저장/삽입 순서 ≠ identity.
        items = []
        for key in value:
            if not isinstance(key, str):
                raise CanonicalExecutionEncodingError(f"map key 는 문자열이어야 한다: {key!r}")
            items.append((_utf8(key), key, value[key]))
        for _, key, item in sorted(items, key=lambda kv: kv[0]):
            out += _text(key)
            _encode_value(item, out)
    elif isinstance(value, float):
        raise CanonicalExecutionEncodingError("float 은 semantic identity 를 갖지 않는다")
    else:
        raise CanonicalExecutionEncodingError(f"미지원 canonical 값 타입: {type(value).__name__}")


def canonical_execution_bytes(payload: object) -> bytes:
    """semantic payload 의 execution-canonical/v1 정본 bytes(저장 순서 무관)."""
    out = bytearray()
    out += _MAGIC
    out += _text(CANONICAL_ENCODING_VERSION)
    _encode_value(payload, out)
    return bytes(out)


def canonical_execution_digest(payload: object) -> str:
    """canonical bytes 의 sha256 content-address — capture·basis·Plan digest 단일 seam."""
    return "sha256:" + hashlib.sha256(canonical_execution_bytes(payload)).hexdigest()


def require_supported_encoding(canonical_encoding_version: str) -> None:
    """미지원 canonical encoding version 을 latest 로 풀지 않고 시끄럽게 닫는다(fail-closed)."""
    if canonical_encoding_version != CANONICAL_ENCODING_VERSION:
        raise UnsupportedCanonicalEncodingError(
            f"미지원 canonical encoding version: {canonical_encoding_version!r}"
        )
