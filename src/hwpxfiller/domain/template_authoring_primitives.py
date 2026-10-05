"""Shared TXT authoring names, coordinates, and edit validation primitives."""

from __future__ import annotations

import itertools
from collections.abc import Mapping

from .structure_scan import normalize_field_id

FIELD_COMMANDS = frozenset({"create_field", "rename_field", "relink_field", "unset_field"})


REASON_INVALID_SELECTION = "고른 위치가 올바르지 않습니다."


REASON_REGION_OVERLAP = "고른 범위가 기존 영역과 겹칩니다. 범위를 다시 고르세요."


REASON_FIELD_OVERLAP = "고른 범위에 기존 필드가 포함되어 있습니다."


REASON_STRUCTURE_FIRST = "구조 오류를 먼저 수정한 뒤 영역 명령을 실행하세요."


REASON_NO_CONTENT_LINE = "고를 내용 줄이 없습니다."


class NameConflict(ValueError):
    """Renaming onto an existing field is never merged silently (AC08)."""

    def __init__(self, name: str, existing_count: int) -> None:
        self.name = name
        self.existing_count = existing_count
        self.message = f"‘{name}’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요."
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {"code": "name_conflict", "name": self.name,
                "existing_count": self.existing_count, "message": self.message}


#: 필드 이름 문법 거절(§13) — 비었거나 문법 기호가 든 이름.
INVALID_FIELD_NAME = "필드 이름을 확인하세요. 비어 있거나 문법 기호가 포함되어 있습니다."


#: 항목·선택 식별자가 빈 거절 — 만들기와 속성 변경이 각자의 문장을 쓴다(HWPX 가 먼저 쓰던 그 문장).
REASON_NEED_IDENTIFIER = "항목이나 선택의 식별자를 입력하세요."


REASON_NEED_NEW_IDENTIFIER = "항목이나 선택의 새 식별자를 입력하세요."


#: 여러 이름의 필드를 한 문서 변형으로 만드는 명령(#1156 「모두 필드로」) — ``fields: [{"name", "ranges"}]``.
CREATE_FIELDS = "create_fields"


#: HWPX 문단에서 고른 범위 앞이나 안에 제어 요소가 있다 — 편집기와 문서의 글자 위치가 갈릴 수 있어 필드를 만들지 않는다.
REASON_CONTROL_BEFORE = "고른 범위 앞이나 안에 제어 요소가 있어 문자 위치를 확정할 수 없습니다."


class InvalidName(ValueError):
    """A name or identifier the grammar cannot carry — refused in place, not raised as an error (P-06).

    ``field`` names the input the sentence belongs to: ``"name"`` (필드 이름·표시 이름) or
    ``"identifier"`` (연결 식별자). The surface puts the sentence right under that input.
    """

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"code": "invalid_name", "field": self.field, "message": self.message}


def region_identifier(raw: object, *, renaming: bool = False) -> str:
    """항목·선택 식별자 — 구간 표기로 되읽히는 값만 통과한다(두 매체 공유). 거절은 식별자 칸의 것이다."""
    from .authoring import marker_identifier

    if not isinstance(raw, str) or not raw.strip():
        raise InvalidName("identifier", REASON_NEED_NEW_IDENTIFIER if renaming else REASON_NEED_IDENTIFIER)
    try:
        return marker_identifier(raw)
    except ValueError as exc:
        raise InvalidName("identifier", str(exc)) from exc


def validate_region_label(raw: object) -> None:
    """항목·선택 표시 이름(이름 칸) — 되읽기 동등이 아니면 이름 칸의 거절이다."""
    from .authoring import marker_label

    try:
        marker_label(raw)
    except ValueError as exc:
        raise InvalidName("name", str(exc)) from exc


def whole_field_unset(command: Mapping[str, object]) -> bool:
    """필드 전체(구조 목록의 필드 행 — ``occurrences`` 를 실은 대상)의 의미 해제인가(IDE-06 P-20).

    전체 대상은 이름(``old_name``)이 같은 모든 사용 위치를 한 계획으로 치환한다. 사용 위치 한 곳의
    해제는 좌표(TXT)나 차례(HWPX)로 그 자리만 고친다.
    """
    return command.get("type") == "unset_field" and isinstance(command.get("occurrences"), list)


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def to_utf16(text: str, offset: int) -> int:
    return utf16_length(text[:offset])


def _from_utf16(text: str, offset: object) -> int:
    # ponytail: linear conversion is enough for ordinary templates; build an offset map if large documents make command latency visible.
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError(REASON_INVALID_SELECTION)
    units = 0
    for index, char in enumerate(text):
        if units == offset:
            return index
        units += utf16_length(char)
        if units > offset:
            raise ValueError("고른 위치가 문자 중간에 있습니다.")
    if units == offset:
        return len(text)
    raise ValueError("고른 위치가 문서 밖에 있습니다.")


def from_utf16(text: str, offset: object) -> int:
    """편집기 선택의 UTF-16 단위 위치 → code point 위치. 문자 중간·문서 밖·잘못된 값은 ValueError."""
    return _from_utf16(text, offset)


def line_starts(text: str) -> list[int]:
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return starts


def line_at(starts: list[int], offset: int) -> int:
    return max(0, next((i - 1 for i, start in enumerate(starts) if start > offset), len(starts) - 2))


def line_range(text: str, start: int, end: int) -> tuple[int, int, int, int]:
    starts = line_starts(text)
    if len(starts) == 1:
        raise ValueError(REASON_NO_CONTENT_LINE)
    first = line_at(starts, start)
    last = line_at(starts, max(start, end - 1))
    return first, last, starts[first], starts[last + 1]


def preferred_eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def field_identifier(raw: object) -> str:
    name = normalize_field_id(raw)
    if not name or "{{" in name or "}}" in name or "|" in name or name.startswith(("#", "/")):
        raise InvalidName("name", INVALID_FIELD_NAME)
    return name


def target_placement(scan, command: Mapping[str, object]):
    kind = str(command.get("kind", "slot"))
    slot_id = str(command.get("slot_id", ""))
    option_id = str(command.get("option_id", "")) if kind == "option" else None
    return next(
        (place for place in scan.placements if place.kind == kind
         and place.slot_id == slot_id and place.option_id == option_id),
        None,
    )


def field_spans(text: str, command: Mapping[str, object], start: int, end: int) -> list[tuple[int, int]]:
    """``create_field`` 의 자리들(code point) — ``ranges`` 가 있으면 고른 자리를 포함한 전부다(IDE-07 P-07).

    고른 자리(``start/end``)는 ``ranges`` 안에 있어야 한다. 서로 겹치거나 같은 자리는 필드 겹침 거절이다.
    """
    ranges = command.get("ranges")
    if ranges is None:
        return [(start, end)]
    if not isinstance(ranges, list) or not all(isinstance(item, Mapping) for item in ranges):
        raise ValueError(REASON_INVALID_SELECTION)
    spans = sorted((_from_utf16(text, item.get("start")), _from_utf16(text, item.get("end"))) for item in ranges)
    _validate_field_spans(text, spans, start, end)
    return spans


def _validate_field_spans(text: str, spans: list[tuple[int, int]], start: int, end: int) -> None:
    # 같은 문구 N곳이다 — 고른 자리가 들어 있고 모든 자리의 글자가 같아야 한다(옛 좌표를 짐작해 끼우지 않는다).
    if (start, end) not in spans or any(lo > hi or text[lo:hi] != text[start:end] for lo, hi in spans):
        raise ValueError(REASON_INVALID_SELECTION)
    if any(first[1] > second[0] or first == second for first, second in itertools.pairwise(spans)):
        raise ValueError(REASON_FIELD_OVERLAP)
