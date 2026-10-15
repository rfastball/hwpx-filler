"""데이터 계약 — 보낸 쪽 데이터에서 계산한 **값 없는** 연결별 통계의 값 모델과 codec(#1188 WP-02).

작업 꾸러미로 건넨 작업은 받는 사람의 데이터를 처음 만난다. 데이터를 바꾸면 연결 확정이 전원
풀리는 규칙(C1)이 그대로 서면 받는 사람이 필드 수만큼 다시 확정해야 하므로, 보낸 쪽이 자기 데이터로
관찰한 사실을 작업에 싣고 받는 쪽 데이터가 그 사실보다 나쁘지 않은 연결만 자동확정한다(판정은
:mod:`hwpxfiller.domain.data_contract_check`).

계약은 **열이 아니라 템플릿 필드마다** 선다 — 한 열이 유형·표시형·가공이 다른 여러 필드를 먹일 수
있고, 실패는 그 연결 전체(열·유형·표시형·가공)가 정한다. 항목이 담는 것:

- ``field``·``column`` — 템플릿 필드와 읽는 열 이름(매핑에 이미 있는 이름이다).
- ``binding`` — 그 필드 연결 명세의 지문(:func:`binding_fingerprint`). 받는 쪽의 지금 연결이 이
  지문과 다르면 계약은 그 연결에 대해 말하지 않는다(편집한 행은 자동확정되지 않는다).
- ``rows``·``blanks``·``failures`` — 관찰한 행 수, 그중 빈 값 행 수, 렌더 실패 행 수.
- ``shape``·``length`` — 성공한 값들의 모양 등급과 글자 수 범위(``shape="empty"`` 면 범위 없음).

**값·표본은 절대 싣지 않는다** — 계약은 꾸러미에 실려 다른 사람에게 가므로 데이터 값이 새면 안 된다
(테스트로 고정). 고정값·오늘 날짜 연결은 데이터를 읽지 않아 항목이 없다.

엄격 해독: 모르는 판·키·모양은 시끄럽게 거절한다(:mod:`hwpxfiller.domain.preset` 과 같은 규율) —
틀린 계약을 관대하게 읽으면 근거 없는 자동확정이 된다. 이 모듈은 순수하다(I/O 없음).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .mapping import FieldMapping

DATA_CONTRACT_SCHEMA = "data-contract/v1"

#: 값 모양 등급 — 성공한 값(빈 값·실패 제외)이 모두 숫자 모양이면 ``number``, 모두 날짜 모양이면
#: ``date``, 섞이거나 그 밖이면 ``text``, 성공한 값이 하나도 없으면 ``empty``.
SHAPE_EMPTY = "empty"
SHAPE_NUMBER = "number"
SHAPE_DATE = "date"
SHAPE_TEXT = "text"
SHAPES = (SHAPE_EMPTY, SHAPE_NUMBER, SHAPE_DATE, SHAPE_TEXT)

_ENTRY_KEYS = frozenset(
    {"field", "column", "binding", "rows", "blanks", "failures", "shape", "length"}
)
_CONTRACT_KEYS = frozenset({"schema", "fields"})
_BINDING_RE = re.compile(r"sha256:[0-9a-f]{64}")


class DataContractError(ValueError):
    """데이터 계약이 이 판이 아는 모양이 아니다 — 근거 없는 자동확정을 막으려 시끄럽게 거절한다."""


def binding_fingerprint(mapping: FieldMapping) -> str:
    """연결 명세의 지문 — 열·유형·고정값·표시형·가공(빠짐 처리 포함). 필드 이름은 들지 않는다.

    렌더를 정하는 전부가 :meth:`FieldMapping.to_dict` 에 있으므로 그 사전(필드 이름 제외)의 정본
    JSON 을 잰다. 가공은 있을 때만 키가 서므로 가공 없는 연결의 지문이 가공 축 도입과 무관하다.
    """
    payload = {k: v for k, v in mapping.to_dict().items() if k != "template_field"}
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _count(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DataContractError(f"데이터 계약의 {what} 는 0 이상의 정수여야 합니다: {value!r}")
    return value


def _name(value: object, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise DataContractError(f"데이터 계약의 {what} 는 비어 있지 않은 문자열이어야 합니다")
    return value


@dataclass(frozen=True)
class FieldContract:
    """템플릿 필드 하나의 계약 — 보낸 쪽 데이터 전 행을 그 연결로 렌더한 통계."""

    field: str
    column: str
    binding: str
    rows: int
    blanks: int
    failures: int
    shape: str
    length: "tuple[int, int] | None"

    def __post_init__(self) -> None:
        _name(self.field, "field")
        _name(self.column, "column")
        if not isinstance(self.binding, str) or not _BINDING_RE.fullmatch(self.binding):
            raise DataContractError(f"데이터 계약의 binding 지문 모양이 아닙니다: {self.binding!r}")
        if _count(self.rows, "rows") < 1:
            raise DataContractError("데이터 계약의 rows 는 1 이상이어야 합니다")
        if _count(self.blanks, "blanks") + _count(self.failures, "failures") > self.rows:
            raise DataContractError("데이터 계약의 blanks·failures 합이 rows 보다 큽니다")
        if self.shape not in SHAPES:
            raise DataContractError(f"모르는 값 모양 등급: {self.shape!r} (지원: {SHAPES})")
        self._check_length()

    def _check_length(self) -> None:
        if self.shape == SHAPE_EMPTY:
            if self.length is not None:
                raise DataContractError("값이 없는(empty) 항목에는 길이 범위가 없어야 합니다")
            return
        if not isinstance(self.length, tuple) or len(self.length) != 2:
            raise DataContractError("데이터 계약의 length 는 [최소, 최대] 두 정수여야 합니다")
        low, high = (_count(n, "length") for n in self.length)
        if low > high:
            raise DataContractError("데이터 계약의 length 최소가 최대보다 큽니다")

    @property
    def filled(self) -> int:
        """빈 값이 아닌 행 수 — 실패율의 분모."""
        return self.rows - self.blanks


@dataclass(frozen=True)
class DataContract:
    """작업 하나의 데이터 계약 — 필드 계약의 묶음(필드 이름 유일)."""

    fields: "tuple[FieldContract, ...]"

    def __post_init__(self) -> None:
        names = [entry.field for entry in self.fields]
        if len(set(names)) != len(names):
            raise DataContractError("데이터 계약에 같은 필드가 두 번 있습니다")

    def entry_for(self, template_field: str) -> "FieldContract | None":
        for entry in self.fields:
            if entry.field == template_field:
                return entry
        return None


def encode_data_contract(contract: DataContract) -> dict:
    """저장·꾸러미 표현 — 키 순서 고정, 값·표본 없음."""
    return {
        "schema": DATA_CONTRACT_SCHEMA,
        "fields": [
            {
                "field": entry.field,
                "column": entry.column,
                "binding": entry.binding,
                "rows": entry.rows,
                "blanks": entry.blanks,
                "failures": entry.failures,
                "shape": entry.shape,
                "length": None if entry.length is None else list(entry.length),
            }
            for entry in contract.fields
        ],
    }


def _decode_length(raw: object) -> "tuple[int, int] | None":
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) != 2:
        raise DataContractError("데이터 계약의 length 는 [최소, 최대] 두 정수여야 합니다")
    return (_count(raw[0], "length"), _count(raw[1], "length"))


def _decode_entry(raw: object) -> FieldContract:
    if not isinstance(raw, dict):
        raise DataContractError("데이터 계약의 항목은 사전이어야 합니다")
    if set(raw) != _ENTRY_KEYS:
        raise DataContractError(
            f"데이터 계약 항목의 키가 다릅니다: {sorted(set(raw) ^ _ENTRY_KEYS)}"
        )
    return FieldContract(
        field=raw["field"],
        column=raw["column"],
        binding=raw["binding"],
        rows=raw["rows"],
        blanks=raw["blanks"],
        failures=raw["failures"],
        shape=raw["shape"],
        length=_decode_length(raw["length"]),
    )


def decode_data_contract(raw: object) -> DataContract:
    """저장·꾸러미 표현 → 계약. 모르는 판·키·모양은 :class:`DataContractError`."""
    if not isinstance(raw, dict):
        raise DataContractError(f"데이터 계약은 사전이어야 하는데 {type(raw).__name__} 입니다")
    if set(raw) != _CONTRACT_KEYS:
        raise DataContractError(f"데이터 계약의 키가 다릅니다: {sorted(set(raw) ^ _CONTRACT_KEYS)}")
    if raw["schema"] != DATA_CONTRACT_SCHEMA:
        raise DataContractError(f"지원하지 않는 데이터 계약: {raw['schema']!r}")
    fields = raw["fields"]
    if not isinstance(fields, list):
        raise DataContractError("데이터 계약의 fields 는 목록이어야 합니다")
    return DataContract(fields=tuple(_decode_entry(item) for item in fields))


__all__ = [
    "DATA_CONTRACT_SCHEMA",
    "SHAPES",
    "SHAPE_DATE",
    "SHAPE_EMPTY",
    "SHAPE_NUMBER",
    "SHAPE_TEXT",
    "DataContract",
    "DataContractError",
    "FieldContract",
    "binding_fingerprint",
    "decode_data_contract",
    "encode_data_contract",
]
