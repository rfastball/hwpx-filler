"""자리 하나의 증거 — 문서 안의 문맥(줄·표 칸), 라벨, 고정 문구 단서, 문장 속 여부, 위치 표지.

문서는 문단(TXT 는 줄)의 차례다. 엔진의 「선형 문서」(텍스트 단위를 ``\\n`` 으로 이은 것)와 같이 읽되,
표 칸 자리의 「앞 줄」은 문서 차례의 앞 문단이 아니라 같은 표의 **왼쪽 칸과 위 칸**(라벨 칸인 것)이다 —
둘 다 라벨로 대어 보고 열을 부르는 쪽을 쓴다.

「값만 있는 줄」(문장 속이 아님)은 같은 문단의 **다른 후보 자리를 가리고** 본다 — 「연락처: ⟦기관⟧ ⟦부서⟧
⟦이름⟧ (☎ ⟦전화⟧)」의 각 값은 저마다 값만 있는 자리다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from .candidates import SPECIFIC, CellRef, ParagraphText, Slot, hangul_bounded, specificity
from .labels import (
    CUE_FIXED,
    CUE_GENERIC,
    CUE_REPEAT,
    data_cue,
    extract_label,
    glued_left,
    is_label_cell,
    label_matches,
    leading_marker,
    names_literally,
    normalize_label,
    number_frame,
    raw_label,
    static_cue,
    strip_markers,
    word_windows,
)

#: 표 칸 자리의 위치 표지(계약 「where」).
WHERE_CELL = "표 칸"
#: 다른 후보 자리를 가린 글자 — 문자·숫자가 아니다.
MASK = "␀"
_PREFIX_WIDTH = 32
_PREFIX_LIMIT = 50
_ALNUM = re.compile(r"[가-힣A-Za-z0-9]")


@dataclass(frozen=True)
class SpotEvidence:
    slot: Slot
    text: str
    label: str  # 사람에게 보일 라벨 원문 — 없으면 ""
    matched: tuple[str, ...]  # 라벨이 부르는 후보 열(후보 열 차례)
    glued: bool
    cue: str | None
    data: bool
    standalone: bool
    creatable: bool
    bounded: bool = True  # 양쪽 글자가 한글이 아니다(짧은 값의 낱말 속 출현을 가른다)
    literal: tuple[str, ...] = ()  # 라벨이 이름을 글자 그대로 담은(또는 이름에 담긴) 열 — 동의어·글자쌍 일치는 아니다

    @property
    def labelled(self) -> bool:
        """라벨 자리 — 라벨이 열을 부르고, 낱말 가운데가 아니고, 고정 문구 단서가 없다(약한 반복 단서는 된다)."""
        return bool(self.matched) and not self.glued and self.cue in (None, CUE_REPEAT)

    @property
    def anchored(self) -> bool:
        """문장 속이 아닌 자리 — 값만 있는 줄·칸이거나 자료 단서(전화번호·직함 앞 이름·번호 틀)가 있다."""
        return (self.standalone or self.data) and not self.glued

    @property
    def generic(self) -> bool:
        return self.cue == CUE_GENERIC

    @property
    def fixed(self) -> bool:
        return self.cue == CUE_FIXED


class DocumentView:
    """문단 차례 위의 문맥 질의 — 한 번 짓고 자리마다 묻는다. ``slots`` 는 가릴 후보 자리(마스킹 결과)다."""

    def __init__(self, paragraphs: Sequence[ParagraphText], slots: Sequence[Slot] = ()) -> None:
        self.paragraphs = list(paragraphs)
        self.whole = "\n".join(paragraph.text for paragraph in self.paragraphs)
        self._cells = _cell_texts(self.paragraphs)
        self._where = _where_labels(self.paragraphs)
        self._masks = _maskable(self.paragraphs, slots)

    def where(self, index: int) -> str:
        return self._where[index]

    def repeats(self, text: str) -> int:
        return self.whole.count(text)

    def line_prefixes(self, text: str) -> list[str]:
        """``text`` 의 출현마다 같은 줄의 앞 글자(끝 32자) — 문서 차례로 최대 50곳."""
        out: list[str] = []
        start = 0
        while len(out) < _PREFIX_LIMIT:
            found = self.whole.find(text, start)
            if found < 0:
                break
            line_start = self.whole.rfind("\n", 0, found) + 1
            out.append(self.whole[max(line_start, found - _PREFIX_WIDTH):found])
            start = found + len(text)
        return out

    def masked_line(self, slot: Slot) -> tuple[str, str]:
        """자리 줄의 왼쪽·오른쪽 글자 — 같은 문단의 다른 후보 자리는 :data:`MASK` 로 가린다."""
        chars = list(self.paragraphs[slot.paragraph].text)
        for start, end in self._masks.get(slot.paragraph, ()):
            if (start, end) != (slot.start, slot.end):
                chars[start:end] = MASK * (end - start)
        text = "".join(chars)
        return text[:slot.start].rsplit("\n", 1)[-1], text[slot.end:].split("\n", 1)[0]

    def previous_lines(self, index: int) -> list[str]:
        """자리 줄의 「앞 줄」 후보 — 표 칸이면 라벨 칸인 왼쪽·위 칸(차례대로), 아니면(또는 없으면) 앞 문단."""
        cell = self.paragraphs[index].cell
        if cell is not None:
            labels = [neighbour for neighbour in (self._left_of(cell), self._above(cell))
                      if neighbour and is_label_cell(strip_markers(neighbour))]
            if labels:
                return labels
        return [self.paragraphs[index - 1].text if index > 0 else ""]

    def _left_of(self, cell: CellRef) -> str:
        return next((text for other, text in self._cells.items() if other.table == cell.table
                     and other.row <= cell.row < other.row + other.row_span
                     and other.col + other.col_span == cell.col), "")

    def _above(self, cell: CellRef) -> str:
        return next((text for other, text in self._cells.items() if other.table == cell.table
                     and other.col <= cell.col < other.col + other.col_span
                     and other.row + other.row_span == cell.row), "")

    def next_line(self, index: int) -> str:
        return self.paragraphs[index + 1].text if index + 1 < len(self.paragraphs) else ""


def _maskable(paragraphs: Sequence[ParagraphText], slots: Sequence[Slot]) -> dict[int, list[tuple[int, int]]]:
    """문단마다 가릴 후보 자리 — 낱말 속의 짧은 값(「대전」의 「대」)은 값의 출현이 아니라 가리지 않는다."""
    out: dict[int, list[tuple[int, int]]] = {}
    for slot in slots:
        text = paragraphs[slot.paragraph].text
        if specificity(text[slot.start:slot.end]) >= SPECIFIC or hangul_bounded(text, slot.start, slot.end):
            out.setdefault(slot.paragraph, []).append((slot.start, slot.end))
    return out


def _cell_texts(paragraphs: Sequence[ParagraphText]) -> dict[CellRef, str]:
    cells: dict[CellRef, list[str]] = {}
    for paragraph in paragraphs:
        if paragraph.cell is not None:
            cells.setdefault(paragraph.cell, []).append(paragraph.text)
    return {cell: " ".join(" ".join(texts).split()) for cell, texts in cells.items()}


def _where_labels(paragraphs: Sequence[ParagraphText]) -> list[str]:
    """문단마다 위치 표지 — 지금까지의 법령식 번호 층위(「1. 나」), 표 칸이면 「표 칸」을 앞에."""
    stack: dict[int, str] = {}
    labels: list[str] = []
    for paragraph in paragraphs:
        marker = leading_marker(paragraph.text) if paragraph.cell is None else None
        if marker is not None:
            level, token = marker
            stack = {depth: value for depth, value in stack.items() if depth < level}
            stack[level] = token
        path = " ".join(stack[depth] for depth in sorted(stack)).rstrip(".")
        if paragraph.cell is not None:
            path = ", ".join(part for part in (WHERE_CELL, path) if part)
        labels.append(path)
    return labels


def _standalone(span: str, line_left: str, line_right: str) -> bool:
    """자리가 문장 속이 아니다 — 줄(칸)에 자리 말고는 목록 기호·라벨·괄호·짧은 단위·가린 다른 값만 있다.

    줄 끝에 정렬된 값(왼쪽이 공백 둘 이상·탭으로 끝나고 오른쪽에 글자가 없다)도 값만 있는 자리다.
    한글로 끝나는 값 바로 뒤에 한글이 붙으면(「⟦전자입찰⟧서」) 낱말의 일부라 아니다(「⟦48,500,000⟧원」은 단위).
    """
    if re.match(r"[가-힣]", span[-1:]) and re.match(r"[가-힣]", line_right):
        return False
    # 범위 표기(「A ~ B」)의 양쪽 값은 각자 한 자리다 — 물결표에서 줄을 끊어 본다.
    line_left = re.split(r"[~∼]", line_left)[-1]
    line_right = re.split(r"[~∼]", line_right)[0]
    letters = len(_ALNUM.findall(re.sub(r"\([^)]*\)|（[^）]*）", "", line_right)))
    if letters == 0 and re.search(r"(?: {2,}|\t)$", line_left):
        return True
    left = strip_markers(line_left).strip()
    left_ok = not _ALNUM.search(left) or bool(re.search(rf"[:：][\s{MASK}]*$", left))
    return left_ok and letters <= 2


def _apposition(line_left: str, line_right: str) -> bool:
    """다른 값 바로 뒤 괄호 속 값 — 「⟦9901000101⟧(⟦전동드릴⟧)」의 이름처럼 값에 붙은 풀이다."""
    return bool(re.search(rf"{MASK}[(（]$", line_left)) and bool(re.match(r"[)）]", line_right))


def _matching(columns: Sequence[str], label: str, *, fuzzy: bool) -> tuple[str, ...]:
    return tuple(column for column in columns if label_matches(label, normalize_label(column), fuzzy=fuzzy))


class _Label(NamedTuple):
    text: str  # 사람에게 보일 라벨 원문
    matched: tuple[str, ...]
    literal: tuple[str, ...]
    left: str = ""  # 라벨을 읽은 왼쪽 문맥(앞 줄 + 자리 줄 앞 글자)


def _found(text: str, key: str, matched: tuple[str, ...]) -> _Label:
    return _Label(text, matched, tuple(column for column in matched if names_literally(key, normalize_label(column))))


def _line_label(left: str, columns: Sequence[str]) -> _Label:
    """앞 낱말 라벨은 20자 창이 안 맞으면 마지막 1·2·3낱말 창을 대어 본다.

    쌍점 라벨과 자리 사이에 다른 값이 있을 때(「세부품명: 소화기 (품명번호 ⟦…⟧)」)도 앞 낱말 창을 대어 본다.
    """
    label, how = extract_label(left)
    matched = _matching(columns, label, fuzzy=how in ("colon", "cell")) if label else ()
    if matched or how not in ("before", "colon-but-value-between"):
        return _found(raw_label(left, how) if label else "", label, matched)
    for window in word_windows(strip_markers(left.rsplit("\n", 1)[-1])):
        key = normalize_label(window)
        hit = _matching(columns, key, fuzzy=False)
        if hit:
            return _found(window, key, hit)
    return _found(raw_label(left, how) if label else "", label, ())


def _label(view: DocumentView, slot: Slot, columns: Sequence[str]) -> _Label:
    """앞 줄 후보마다 대어 보고 열을 부르는 첫 후보, 없으면 첫 후보의 라벨."""
    before = view.paragraphs[slot.paragraph].text[:slot.start]
    first: _Label | None = None
    for previous in view.previous_lines(slot.paragraph):
        left = previous + "\n" + before
        found = _line_label(left, columns)._replace(left=left)
        if found.matched:
            return found
        first = first or found
    assert first is not None  # previous_lines 는 늘 하나 이상이다
    return first


def spot_evidence(view: DocumentView, slot: Slot, columns: Sequence[str]) -> SpotEvidence:
    """자리 하나의 증거. ``columns`` 는 이 자리를 낸 후보 열(후보 열 차례)이다."""
    paragraph = view.paragraphs[slot.paragraph]
    span = paragraph.text[slot.start:slot.end]
    line_left = paragraph.text[:slot.start].rsplit("\n", 1)[-1]
    line_right = paragraph.text[slot.end:].split("\n", 1)[0]
    right = paragraph.text[slot.end:] + "\n" + view.next_line(slot.paragraph)
    label = _label(view, slot, columns)
    masked_left, masked_right = view.masked_line(slot)
    cue = static_cue(label.left, span, right, repeats=view.repeats(span), prefixes=view.line_prefixes(span))
    return SpotEvidence(
        slot=slot, text=span, label=label.text, matched=label.matched, literal=label.literal,
        glued=glued_left(line_left, span) and not number_frame(line_left, line_right), cue=cue,
        data=data_cue(line_left, span, right) or _apposition(masked_left, masked_right),
        standalone=_standalone(span, masked_left, masked_right),
        creatable=slot.end < paragraph.editable_end,
        bounded=hangul_bounded(paragraph.text, slot.start, slot.end),
    )
