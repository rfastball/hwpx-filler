"""작업대 본문 카드의 **표식과 행별 임시 편집**(링1, #1148 PR B).

검토·복사 작업대의 본문은 편집기다 — 사용자는 복사하기 전에 그 행의 복사본만 고칠 수 있다
(템플릿·데이터·연결은 바뀌지 않는다). 그때도 「〈빈 값〉이 어디 있었고 채워졌는가」는 표면이
아니라 여기가 판정한다: 표식(값·빈 값·비워 둠·미치환)은 렌더 세그먼트에서 나고, 편집본 위의
자리는 원문→편집본 차이로 **사상**한다. 표면은 받은 좌표에 장식만 얹는다. 사상·채움·해소의
규칙(보수 판정)은 :mod:`~hwpxfiller.viewmodel.txt_card_diff` 가 진다.

전각 정렬(결정 17)은 **표식 밖**(템플릿 원문 자리)에만 건다 — :func:`align_segments` 가 값을
건드리지 않는 것과 같은 규율을 편집본에도 지킨다. 판정과 보관은 언제나 **정렬 전 글**에 서고,
정렬은 표시·복사 글자를 지을 때만 건다(되돌리기가 원래 반각 공백으로 돌아가게).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from ..domain.text_render import (
    SEG_BLANK, SEG_LITERAL, align_fullwidth, has_space_run, render_segments,
)
from .txt_card_diff import MARK_DECLARED, map_marks, plain_edit, resolved_names

__all__ = [
    "MARK_DECLARED", "CardEdits", "CardMark", "CardView", "EditedCard", "base_marks", "card_view",
    "edit_card", "plain_edit", "raw_card", "utf16_marks",
]


@dataclass(frozen=True)
class CardMark:
    """본문 위 표식 1건 — 코드 포인트 반열린 구간 ``[start, end)``."""

    kind: str
    name: str
    start: int
    end: int


@dataclass(frozen=True)
class EditedCard:
    """편집본 1건의 판정 — 표시·복사 텍스트, 사상한 표식, 채운 빈 자리, 고친 미치환."""

    text: str
    marks: "tuple[CardMark, ...]"
    filled: frozenset[str]
    resolved: frozenset[str]
    space_run: bool


def base_marks(segments, declared: "frozenset[str] | set[str]") -> "tuple[CardMark, ...]":
    """렌더 세그먼트 → 표식. 빈 값 중 선언된 비움은 ``declared`` 로 가른다(판정 단일 출처는
    :meth:`~hwpxfiller.viewmodel.mapping_state.MappingModel.declared_empty_fields`)."""
    marks: "list[CardMark]" = []
    pos = 0
    for seg in segments:
        if seg.kind != SEG_LITERAL:
            kind = MARK_DECLARED if seg.kind == SEG_BLANK and seg.name in declared else seg.kind
            marks.append(CardMark(kind, seg.name, pos, pos + len(seg.text)))
        pos += len(seg.text)
    return tuple(marks)


def _align_outside(text: str, marks: "tuple[CardMark, ...]") -> "tuple[str, tuple[CardMark, ...]]":
    """표식 밖 조각만 전각 치환하고 표식 좌표를 새 길이에 맞춘다."""
    out: "list[str]" = []
    moved: "list[CardMark]" = []
    cursor = 0
    for mark in sorted(marks, key=lambda m: (m.start, m.end)):
        start = max(mark.start, cursor)
        out.append(align_fullwidth(text[cursor:start]))
        new_start = sum(len(chunk) for chunk in out)
        out.append(text[start:mark.end])
        moved.append(replace(mark, start=new_start, end=new_start + max(0, mark.end - start)))
        cursor = max(cursor, mark.end)
    out.append(align_fullwidth(text[cursor:]))
    return "".join(out), tuple(moved)


def _outside_has_space_run(text: str, marks: "tuple[CardMark, ...]") -> bool:
    cursor, chunks = 0, []
    for mark in sorted(marks, key=lambda m: m.start):
        chunks.append(text[cursor:mark.start])
        cursor = max(cursor, mark.end)
    chunks.append(text[cursor:])
    return any(has_space_run(chunk) for chunk in chunks)


def edit_card(
    base: str, marks: "tuple[CardMark, ...]", edited: str, *, fullwidth: bool,
) -> EditedCard:
    """정렬 전 원문 ``base`` 와 그 표식 → 정렬 전 편집본 ``edited`` 의 판정.

    ``fullwidth`` 면 편집본의 표식 밖 자리에 전각 정렬을 건다. 연속 공백 린트는 치환 **전**
    편집본으로 잰다.
    """
    mapped_marks, filled = map_marks(base, marks, edited)
    space_run = _outside_has_space_run(edited, mapped_marks)
    text, shown = _align_outside(edited, mapped_marks) if fullwidth else (edited, mapped_marks)
    return EditedCard(text, shown, filled, resolved_names(base, marks, edited), space_run)


def _utf16(text: str, offset: int) -> int:
    return len(text[:offset].encode("utf-16-le")) // 2


def utf16_marks(text: str, marks: "tuple[CardMark, ...]") -> "list[dict]":
    """표식 → 웹 좌표(UTF-16 코드 단위). JS 문자열 오프셋과 같은 단위로 번역해 넘긴다."""
    return [
        {"kind": m.kind, "name": m.name, "start": _utf16(text, m.start), "end": _utf16(text, m.end)}
        for m in marks
    ]


@dataclass(frozen=True)
class CardView:
    """작업점 한 행의 본문 판정 — 표시·복사·게이트·린트가 **한 번의 판정**을 나눠 쓴다."""

    #: 표시 = 복사 텍스트(편집본이 있으면 그것, 전각 정렬까지 끝난 글자).
    text: str
    #: 편집 전 원문(전각 정렬까지 건 렌더) — 봉인 물질화 대조의 대상.
    base: str
    marks: "tuple[CardMark, ...]"
    missing_fields: "list[str]"
    #: 게이트 결손 — 확정-비움과 편집본에서 채운 빈 자리를 뺀다.
    empty_fields: "list[str]"
    space_run: bool
    #: 정렬 전 글 — 편집본(있으면) 아니면 원문. 표면이 보낸 글은 이 축으로 되돌려 보관한다.
    plain: str
    #: 정렬 전 원문 — 편집본이 이것과 같아지면 편집이 없는 것으로 접는다.
    plain_base: str


def card_view(
    rendered, declared: "frozenset[str]", gate_empty: "list[str]", edit: "str | None",
    *, fullwidth: bool,
) -> CardView:
    """렌더 1건(:class:`~hwpxfiller.viewmodel.txt_card.CardRender`) 위에 그 행의 편집본을 얹는다.

    ``rendered`` 는 **정렬 전** 렌더다(``fullwidth=False``) — 정렬은 여기서 표시 글자에만 건다.
    ``gate_empty`` 는 확정-비움을 뺀 게이트 결손이다(:func:`~hwpxfiller.viewmodel.txt_card.
    gate_empty_fields` — 판정 단일 출처를 여기서 다시 세우지 않는다).
    """
    assert not rendered.fullwidth  # 정렬된 렌더 위에서 편집을 판정하면 되돌리기가 깨진다
    plain = "".join(seg.text for seg in rendered.segments)
    marks = base_marks(rendered.segments, declared)
    base, base_shown = _align_outside(plain, marks) if fullwidth else (plain, marks)
    missing = list(rendered.report.missing_fields)
    if edit is None:
        return CardView(
            base, base, base_shown, missing, list(gate_empty), rendered.space_run, plain, plain,
        )
    edited = edit_card(plain, marks, edit, fullwidth=fullwidth)
    return CardView(
        edited.text, base, edited.marks,
        [name for name in missing if name not in edited.resolved],
        [name for name in gate_empty if name not in edited.filled],
        edited.space_run, edit, plain,
    )


def raw_card(template_text: str) -> "tuple[str, tuple[CardMark, ...]]":
    """원문 보기 — 토큰을 채우지 않고 ``{{이름}}`` 그대로(미치환 표식), 읽기 전용이다."""
    segments, _ = render_segments(template_text, {})
    return "".join(seg.text for seg in segments), base_marks(segments, frozenset())


class CardEdits:
    """행별 임시 편집의 보관 — 작업대 세션과 함께 살고 함께 사라진다.

    ``epoch`` 는 표면이 들고 있는 문서를 **갈아 끼워야** 하는 전이(되돌리기)에서만 오른다 —
    편집 왕복의 메아리로는 오르지 않는다(캐럿이 튄다).

    :meth:`text_rev` 는 편집이 없는 행의 원문이 **바깥 사정으로** 바뀐 것(「오늘 날짜」 분 경계 등)을
    세대로 낸다 — 같은 행·보기·정렬이어도 새 원문이면 표면이 문서를 갈아 끼워야 한다. 편집이 있는
    행은 표면의 문서가 정본이라 세대가 오르지 않는다.
    """

    def __init__(self) -> None:
        self._texts: "dict[int, str]" = {}
        self.epoch = 0
        #: 행 → (표면에 마지막으로 낸 정렬 전 원문, 그 세대).
        self._seen: "dict[int, tuple[str, int]]" = {}
        self._generation = 0

    def get(self, index: "int | None") -> "str | None":
        return None if index is None else self._texts.get(index)

    def put(self, index: int, text: str, unedited: str) -> None:
        """편집본을 받는다. 원문과 같아지면 편집이 없는 것으로 접는다.

        접힐 때는 표면의 문서가 **지금 원문 그대로**다 — 그 원문을 본 것으로 적어 두어, 그사이
        원문이 바뀌었다고 세대를 올려 문서를 다시 갈아 끼우지 않게 한다(친 글자가 튄다).
        """
        self._texts.pop(index, None)
        if text != unedited:
            self._texts[index] = text
        elif index in self._seen:
            self._seen[index] = (unedited, self._seen[index][1])

    def text_rev(self, index: "int | None", unedited: str) -> int:
        """그 행 문서의 세대 — 편집이 없는 행의 원문이 지난번에 낸 것과 다르면 오른다."""
        if index is None:
            return 0
        seen = self._seen.get(index)
        if seen is None or (index not in self._texts and seen[0] != unedited):
            self._generation += 1
            seen = self._seen[index] = (unedited, self._generation)
        return seen[1]

    def revert(self, index: int) -> None:
        if self._texts.pop(index, None) is not None:
            self.epoch += 1

    def __contains__(self, index: object) -> bool:
        return index in self._texts

    def __len__(self) -> int:
        return len(self._texts)

    def signature(self, index: int, rules: str) -> str:
        """그 행이 지금 복사될 글자의 지문 — 규칙 지문 + 그 행의 편집본(편집도 복사되는 글자다)."""
        payload = repr((rules, self._texts.get(index)))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
