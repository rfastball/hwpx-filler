"""S5-06(#702) canonical execution encoder — golden parity·determinism·loud rejection.

golden vector(`tests/fixtures/execution_canonical_v1_golden.json`)는 Python·TypeScript 공통
오러클이다. 여기서 Python 이, `tests/js/canonical_execution_encoding.test.js` 에서 TS 가 같은
파일을 재현한다.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

from hwpxfiller.domain.canonical_execution_encoding import (
    CANONICAL_ENCODING_VERSION,
    CanonicalExecutionEncodingError,
    UnsupportedCanonicalEncodingError,
    canonical_execution_bytes,
    canonical_execution_digest,
    require_supported_encoding,
)

_GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "execution_canonical_v1_golden.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("vector", _GOLDEN["vectors"], ids=lambda v: v["name"])
def test_golden_vector_reproduced(vector: dict) -> None:
    value = vector["value"]
    assert canonical_execution_bytes(value).hex() == vector["canonical_hex"]
    assert canonical_execution_digest(value) == vector["digest"]


def test_magic_and_version_framing() -> None:
    raw = canonical_execution_bytes(None)
    assert raw.startswith(b"HFPXEC1\0")
    # 8-byte MAGIC + u32 length + version bytes + 1 tag.
    assert raw[8:12] == len(CANONICAL_ENCODING_VERSION).to_bytes(4, "big")
    assert raw.endswith(b"\x00")  # NULL tag


def test_map_key_order_independent() -> None:
    a = {"b": 1, "a": [True, False, None], "z": -5}
    b = {"z": -5, "a": [True, False, None], "b": 1}
    assert canonical_execution_bytes(a) == canonical_execution_bytes(b)
    assert canonical_execution_digest(a) == canonical_execution_digest(b)


def test_utf8_byte_order_not_codepoint_order() -> None:
    # UTF-8 byte order 로 정렬 — 삽입 순서와 무관하게 같은 bytes.
    forward = {"a": 1, "ab": 2, "b": 3}
    shuffled = {"b": 3, "ab": 2, "a": 1}
    assert canonical_execution_bytes(forward) == canonical_execution_bytes(shuffled)


def test_variant_tags_distinct() -> None:
    # 같은 "내용" 이라도 타입 tag 가 다르면 bytes 가 다르다(변형 tag 변화).
    digests = {
        canonical_execution_digest(0),
        canonical_execution_digest(False),
        canonical_execution_digest(None),
        canonical_execution_digest("0"),
        canonical_execution_digest([0]),
        canonical_execution_digest({"0": 0}),
    }
    assert len(digests) == 6


def test_nfc_nfd_not_unified() -> None:
    nfc = unicodedata.normalize("NFC", "é")
    nfd = unicodedata.normalize("NFD", "é")
    assert nfc != nfd
    assert canonical_execution_bytes(nfc) != canonical_execution_bytes(nfd)


def test_float_rejected() -> None:
    with pytest.raises(CanonicalExecutionEncodingError):
        canonical_execution_bytes({"x": 1.5})
    with pytest.raises(CanonicalExecutionEncodingError):
        canonical_execution_bytes(2.0)


def test_u64_overflow_rejected() -> None:
    with pytest.raises(CanonicalExecutionEncodingError):
        canonical_execution_bytes(2**64)
    with pytest.raises(CanonicalExecutionEncodingError):
        canonical_execution_bytes(-(2**64))


def test_lone_surrogate_rejected() -> None:
    with pytest.raises(CanonicalExecutionEncodingError):
        canonical_execution_bytes("\ud800")
    with pytest.raises(CanonicalExecutionEncodingError):
        canonical_execution_bytes({"\udfff": 1})


def test_non_string_map_key_rejected() -> None:
    with pytest.raises(CanonicalExecutionEncodingError):
        canonical_execution_bytes({1: "x"})


def test_unsupported_value_type_rejected() -> None:
    with pytest.raises(CanonicalExecutionEncodingError):
        canonical_execution_bytes({1, 2, 3})  # set 은 JSON-value 가 아니다


def test_tuple_encodes_like_list() -> None:
    assert canonical_execution_bytes((1, 2)) == canonical_execution_bytes([1, 2])


def test_u32_length_guard() -> None:
    # 실 payload 로는 4GB 초과 count/length 가 안 나오지만 framing overflow 는 loud 여야 한다.
    from hwpxfiller.domain.canonical_execution_encoding import _u32

    with pytest.raises(CanonicalExecutionEncodingError):
        _u32(2**32)
    with pytest.raises(CanonicalExecutionEncodingError):
        _u32(-1)


def test_require_supported_encoding() -> None:
    require_supported_encoding(CANONICAL_ENCODING_VERSION)  # no raise
    with pytest.raises(UnsupportedCanonicalEncodingError):
        require_supported_encoding("execution-canonical/v2")
