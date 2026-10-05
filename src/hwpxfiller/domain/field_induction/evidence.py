"""자리 하나의 증거 — 문서 안의 문맥(줄·표 칸), 라벨, 고정 문구 단서, 문장 속 여부, 위치 표지.

문서는 문단(TXT 는 줄)의 차례다. 엔진의 「선형 문서」(텍스트 단위를 ``\\n`` 으로 이은 것)와 같이 읽되,
표 칸 자리의 「앞 줄」은 문서 차례의 앞 문단이 아니라 같은 표의 **왼쪽 칸**(라벨 칸이 아니면 **위 칸**)이다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .candidates import CellRef, ParagraphText, Slot
from .labels import (
    CUE_GENERIC,
    data_cue,
    extract_label,
    glued_left,
    is_label_cell,
    label_matches,
    leading_marker,
    normalize_label,
    raw_label,
    static_cue,
    strip_markers,
)

#: 표 칸 자리의 위치 표지(계약 「where」).
WHERE_CELL = "표 칸"
_PREFIX_WIDTH = 32
_PREFIX_LIMIT = 50


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

    @property
    def labelled(self) -> bool:
        return bool(self.matched) and not self.glued and self.cue is None

    @property
    def generic(self) -> bool:
        return self.cue == CUE_GENERIC


class DocumentView:
    """문단 차례 위의 문맥 질의 — 한 번 짓고 자리마다 묻는다."""

    def __init__(self, paragraphs: Sequence[ParagraphText]) -> None:
        self.paragraphs = list(paragraphs)
        self.whole = "\n".join(paragraph.text for paragraph in self.paragraphs)
        self._cells = _cell_texts(self.paragraphs)
        self._where = _where_labels(self.paragraphs)

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

    def previous_line(self, index: int) -> str:
        """자리 줄의 「앞 줄」 — 표 칸이면 왼쪽 라벨 칸, 아니면 위 라벨 칸, 표 밖이면 앞 문단."""
        cell = self.paragraphs[index].cell
        if cell is not None:
            for neighbour in (self._left_of(cell), self._above(cell)):
                if neighbour and is_label_cell(strip_markers(neighbour)):
                    return neighbour
        return self.paragraphs[index - 1].text if index > 0 else ""

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


def _standalone(line_left: str, line_right: str) -> bool:
    """자리가 문장 속이 아니다 — 줄(칸)에 자리 말고는 목록 기호·라벨·괄호·짧은 단위만 있다."""
    # 범위 표기(「A ~ B」)의 양쪽 값은 각자 한 자리다 — 물결표에서 줄을 끊어 본다.
    line_left = re.split(r"[~∼]", line_left)[-1]
    line_right = re.split(r"[~∼]", line_right)[0]
    left = strip_markers(line_left).strip()
    left_ok = not re.search(r"[가-힣A-Za-z0-9]", left) or bool(re.search(r"[:：]\s*$", left))
    right = re.sub(r"\([^)]*\)|（[^）]*）", "", line_right)
    return left_ok and len(re.findall(r"[가-힣A-Za-z0-9]", right)) <= 2


def spot_evidence(view: DocumentView, slot: Slot, columns: Sequence[str]) -> SpotEvidence:
    """자리 하나의 증거. ``columns`` 는 이 자리를 낸 후보 열(후보 열 차례)이다."""
    paragraph = view.paragraphs[slot.paragraph]
    span = paragraph.text[slot.start:slot.end]
    line_left = paragraph.text[:slot.start].rsplit("\n", 1)[-1]
    line_right = paragraph.text[slot.end:].split("\n", 1)[0]
    left = view.previous_line(slot.paragraph) + "\n" + paragraph.text[:slot.start]
    right = paragraph.text[slot.end:] + "\n" + view.next_line(slot.paragraph)
    label, how = extract_label(left)
    fuzzy = how in ("colon", "cell")
    matched = tuple(column for column in columns
                    if label_matches(label, normalize_label(column), fuzzy=fuzzy)) if label else ()
    cue = static_cue(left, span, right, repeats=view.repeats(span), prefixes=view.line_prefixes(span))
    return SpotEvidence(
        slot=slot, text=span, label=raw_label(left, how) if label else "", matched=matched,
        glued=glued_left(line_left, span), cue=cue, data=data_cue(span, right),
        standalone=_standalone(line_left, line_right),
        creatable=slot.end < paragraph.editable_end,
    )
