"""결정적 후보 생성 — 문서 어디에 ``프로그램(행[열])`` 이 나올 수 있는가.

열마다 쓸 수 있는 표시 형식 프로그램의 글자를 문단 평문에서 찾는다. 낱말 경계를 지키는 자리만 남긴다:
숫자는 다른 숫자에 붙지 않아야 하고(``2026000``·``12,026`` 속 ``2026`` 은 아니다), 라틴 글자는 다른
라틴 글자에 붙지 않아야 한다. 한글은 조사가 바로 붙으므로(``한국상사귀하``) 경계를 보지 않는다.
이미 필드 값인 구간은 후보가 아니다. 마스킹은 문단마다 겹치지 않는 자리를 가장 긴 것부터 고른다 —
같은 구간을 내는 프로그램들은 함께 남는다(선택이 아니라 모호함이다).

실험 엔진 ``core/candidates.py`` 의 이식이다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .transforms import renderings


@dataclass(frozen=True)
class CellRef:
    """표 칸 하나의 자리 — 같은 표 안에서 왼쪽·위 칸을 찾는 데 쓴다."""

    table: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1


@dataclass(frozen=True)
class ParagraphText:
    """문단(TXT 는 줄) 하나의 평문 — 어댑터가 채운다.

    ``text`` 의 글자 위치가 편집기 선택 좌표와 같은 구간은 ``editable_end`` 앞까지다(그 뒤는 제어 요소
    뒤라 필드로 만들 수 없다). ``field_spans`` 는 이미 필드 값인 구간이다. ``cell`` 은 표 칸 문단의 자리다.
    """

    key: str
    text: str
    editable_end: int
    field_spans: tuple[tuple[int, int], ...] = ()
    cell: CellRef | None = None


@dataclass(frozen=True)
class Candidate:
    column: str
    transform: str
    rendered: str
    paragraph: int
    start: int
    end: int


@dataclass
class Slot:
    paragraph: int
    start: int
    end: int
    candidates: list[Candidate] = field(default_factory=list)


def _is_latin(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _digit_glued(text: str, outer: int, step: int) -> bool:
    """숫자 끝이 ``outer`` 쪽 글자에 붙었는가 — 숫자·라틴 글자, 또는 ``,``·``.`` 너머 숫자."""
    if not 0 <= outer < len(text):
        return False
    ch = text[outer]
    if ch.isdigit() or _is_latin(ch):
        return True
    beyond = outer + step
    return ch in ",." and 0 <= beyond < len(text) and text[beyond].isdigit()


def _latin_glued(text: str, outer: int) -> bool:
    return 0 <= outer < len(text) and (_is_latin(text[outer]) or text[outer].isdigit())


def boundary_ok(text: str, start: int, end: int) -> bool:
    """``text[start:end]`` 가 낱말 경계를 지키는가(엔진 ``boundary_ok``)."""
    first, last = text[start], text[end - 1]
    if first.isdigit() and _digit_glued(text, start - 1, -1):
        return False
    if last.isdigit() and _digit_glued(text, end, 1):
        return False
    if _is_latin(first) and _latin_glued(text, start - 1):
        return False
    return not (_is_latin(last) and _latin_glued(text, end))


def _inside_field(paragraph: ParagraphText, start: int, end: int) -> bool:
    return any(lo < end and start < hi for lo, hi in paragraph.field_spans)


def occurrences(paragraph: ParagraphText, rendered: str) -> list[tuple[int, int]]:
    """한 문단에서 ``rendered`` 의 경계 맞는 자리(필드 값 밖)."""
    found: list[tuple[int, int]] = []
    text = paragraph.text
    pos = text.find(rendered)
    while pos != -1:
        end = pos + len(rendered)
        if boundary_ok(text, pos, end) and not _inside_field(paragraph, pos, end):
            found.append((pos, end))
        pos = text.find(rendered, pos + 1)
    return found


def find_candidates(paragraphs: Sequence[ParagraphText], row: Mapping[str, str | None]) -> list[Candidate]:
    out: list[Candidate] = []
    for column, value in row.items():
        if not value:
            continue  # 빈 값(None·"")은 증거가 없다
        for transform, rendered in renderings(value):
            for index, paragraph in enumerate(paragraphs):
                out.extend(Candidate(column, transform.id, rendered, index, lo, hi)
                           for lo, hi in occurrences(paragraph, rendered))
    return out


def mask(candidates: Sequence[Candidate]) -> list[Slot]:
    """문단마다 가장 긴 구간부터 겹치지 않게 고른다 — 같은 구간의 후보는 한 자리에 모인다."""
    by_span: dict[tuple[int, int, int], list[Candidate]] = {}
    for candidate in candidates:
        by_span.setdefault((candidate.paragraph, candidate.start, candidate.end), []).append(candidate)
    order = sorted(by_span, key=lambda key: (-(key[2] - key[1]), key[0], key[1]))
    kept: list[Slot] = []
    for paragraph, start, end in order:
        if any(slot.paragraph == paragraph and start < slot.end and slot.start < end for slot in kept):
            continue
        kept.append(Slot(paragraph, start, end, by_span[(paragraph, start, end)]))
    kept.sort(key=lambda slot: (slot.paragraph, slot.start))
    return kept


def specificity(rendered: str) -> float:
    """이 글자가 템플릿에 우연히 있을 수 없는 정도(0..1) — 확률이 아닌 문서화된 거친 사전.

    짧은 숫자는 0 에 가깝고 날짜·긴 이름은 1 에 가깝다(엔진 ``specificity``).
    """
    core = rendered.strip()
    digits = sum(ch.isdigit() for ch in core)
    if digits and all(ch.isdigit() or ch in ",.-" for ch in core):
        return max(0.0, min(1.0, (digits - 1) / 5))
    if digits and any("가" <= ch <= "힣" for ch in core):  # 예: "2026년 9월 30일"
        return 1.0
    return max(0.0, min(1.0, len(core) / 4))


def found_columns(paragraphs: Sequence[ParagraphText], row: Mapping[str, str | None]) -> int:
    """행 고르기의 점수 — 값을 문서에서 (경계 맞게, 필드 밖에서) 하나라도 찾은 열 수."""
    whole = "\n".join(paragraph.text for paragraph in paragraphs)
    return sum(
        any(rendered in whole and any(occurrences(paragraph, rendered) for paragraph in paragraphs)
            for _, rendered in renderings(value))
        for value in row.values() if value
    )
