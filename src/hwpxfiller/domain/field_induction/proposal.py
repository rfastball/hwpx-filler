"""문서 한 부 + 데이터 행 하나 → 필드 제안(묶음·자리·찾지 못한 열).

순수 함수다 — 문단 평문(:class:`~.candidates.ParagraphText`)과 행(열 → 문자열|None)만 받는다.
좌표 변환·파일 형식은 어댑터가, 데이터 풀·세션은 응용 층이 진다.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

from ..structure_scan import collapse_field_id
from ..template_authoring_primitives import REASON_CONTROL_BEFORE, InvalidName, field_identifier
from .candidates import Candidate, ParagraphText, Slot, find_candidates, mask, occurrences
from .evidence import DocumentView, SpotEvidence, spot_evidence
from .grading import KIND_HELD, KIND_PROPOSAL, REASON_BAD_NAME, Grade, count_spots, grade, note_same_value
from .transforms import TRANSFORMS, renderings

REASON_EMPTY = "이 행에서 값이 비어 있습니다."
REASON_NOT_FOUND = "문서에서 같은 값을 찾지 못했습니다."
_UNIT_WON = "원"


@dataclass(frozen=True)
class Spot:
    id: str
    paragraph: int  # 어댑터가 준 문단 차례(좌표 변환은 어댑터가 한다)
    start: int
    end: int
    text: str
    where: str


@dataclass
class Group:
    id: str
    kind: str
    name: str
    column: str
    others: list[str]
    value: str
    raw: str
    transform: str
    reason: str = ""
    note: str = ""
    only: str | None = None
    links_existing: bool = False
    count_text: str = ""
    spots: list[Spot] = field(default_factory=list)


@dataclass(frozen=True)
class Missing:
    column: str
    reason: str


@dataclass
class Proposal:
    groups: list[Group]
    missing: list[Missing]

    def count(self, kind: str) -> int:
        return sum(group.kind == kind for group in self.groups)


def field_name(column: str) -> str | None:
    """열 이름 → 제품 필드 이름. 허용되지 않는 기호를 걷고, 그래도 쓸 수 없으면 None."""
    cleaned = collapse_field_id(re.sub(r"[{}|]", " ", column).lstrip("#/ "))
    try:
        return field_identifier(cleaned)
    except InvalidName:
        return None


def _rank(group: Group) -> tuple:
    first = group.spots[0] if group.spots else None
    return (group.kind != KIND_PROPOSAL, -len(group.spots),
            (first.paragraph, first.start) if first else (1 << 30, 0))


def _slot_columns(slots: Sequence[Slot], columns: Sequence[str]) -> tuple[list[str], dict[str, str]]:
    """같은 글자의 자리들을 낸 열(행 차례)과 열마다 가장 단순한 프로그램."""
    best: dict[str, Candidate] = {}
    for candidate in (item for slot in slots for item in slot.candidates):
        kept = best.get(candidate.column)
        if kept is None or TRANSFORMS[candidate.transform].complexity < TRANSFORMS[kept.transform].complexity:
            best[candidate.column] = candidate
    ordered = [column for column in columns if column in best]
    return ordered, {column: best[column].transform for column in ordered}


def _display_value(rendered: str, transform: str, spots: Sequence[SpotEvidence], view: DocumentView) -> str:
    """보일 값 — 천 단위 쉼표 값 뒤에 「원」이 붙어 있으면 그 단위까지(자리에는 넣지 않는다)."""
    if TRANSFORMS[transform].family != "number":
        return rendered
    texts = [view.paragraphs[spot.slot.paragraph].text for spot in spots]
    if all(text[spot.slot.end:spot.slot.end + 1] == _UNIT_WON for spot, text in zip(spots, texts, strict=True)):
        return rendered + _UNIT_WON
    return rendered


def _spot(view: DocumentView, evidence: SpotEvidence) -> Spot:
    slot = evidence.slot
    return Spot(f"s{slot.paragraph}_{slot.start}", slot.paragraph, slot.start, slot.end, evidence.text,
                view.where(slot.paragraph))


def _only(view: DocumentView, verdict: Grade) -> str | None:
    only = verdict.only
    return _spot(view, only).id if only is not None and only.creatable else None


def _count_text(verdict: Grade, spots: Sequence[Spot]) -> str:
    if verdict.count_text:
        return verdict.count_text
    return count_spots(len(spots) if verdict.kind == KIND_PROPOSAL else len(verdict.spots))


def _hold_unmakeable(group: Group, named: bool) -> None:
    """만들 수 없는 제안은 보류로 — 열 이름이 필드 이름이 될 수 없거나, 자리가 모두 제어 요소 뒤일 때."""
    if not named:
        group.kind, group.reason, group.note, group.only = KIND_HELD, REASON_BAD_NAME, "", None
    elif group.kind == KIND_PROPOSAL and not group.spots:
        # 앞서 만든 필드 등 제어 요소 뒤의 자리는 편집기 좌표로 가리킬 수 없어 만들 수 없다.
        group.kind, group.reason, group.note = KIND_HELD, REASON_CONTROL_BEFORE, ""


def group_id(columns: Sequence[str]) -> str:
    """묶음 열쇠 — 같은 값을 낸 열(행 차례)로 짓는다. 사람이 열을 골라도 바뀌지 않는다."""
    return "g_" + "|".join(columns)


def _group(view: DocumentView, verdict: Grade, key: str, transform: str, raw: str,
           existing: Collection[str]) -> Group:
    name = field_name(verdict.column)
    spots = [_spot(view, item) for item in verdict.spots if item.creatable]
    group = Group(
        id=key, kind=verdict.kind, name=name or verdict.column, column=verdict.column,
        others=list(verdict.others), value=_display_value(verdict.spots[0].text, transform, verdict.spots, view),
        raw=raw, transform=transform, reason=verdict.reason, note=verdict.note, only=_only(view, verdict),
        links_existing=name in existing, count_text=_count_text(verdict, spots), spots=spots,
    )
    _hold_unmakeable(group, name is not None)
    return group


def _groups(view: DocumentView, slots: Sequence[Slot], row: Mapping[str, str | None],
            columns: Sequence[str], existing: Collection[str], picks: Mapping[str, str]) -> list[Group]:
    by_text: dict[str, list[Slot]] = {}
    for slot in slots:
        by_text.setdefault(view.paragraphs[slot.paragraph].text[slot.start:slot.end], []).append(slot)
    out: list[Group] = []
    for same in by_text.values():
        ordered, transforms = _slot_columns(same, columns)
        evidence = [spot_evidence(view, slot, ordered) for slot in same]
        key = group_id(ordered)
        verdict = grade(ordered, evidence, picks.get(key))
        if verdict is not None:
            out.append(_group(view, verdict, key, transforms[verdict.column], row[verdict.column] or "", existing))
    return out


def _one_per_column(groups: Sequence[Group]) -> list[Group]:
    """열 하나에 묶음 하나 — 같은 열의 다른 글자 묶음(다른 표시 형식)은 가장 나은 하나만 남긴다."""
    best: dict[str, Group] = {}
    for group in sorted(groups, key=_rank):
        best.setdefault(group.column, group)
    return sorted(best.values(), key=lambda group: _rank(group)[2])


def _in_fields(paragraphs: Sequence[ParagraphText], value: str) -> bool:
    """값이 이미 필드 값 안에만 있는가 — 그 열은 찾지 못한 열이 아니다."""
    for _, rendered in renderings(value):
        for paragraph in paragraphs:
            inside = ParagraphText(paragraph.key, paragraph.text, 0)
            if any(lo < hi2 and lo2 < hi for lo, hi in occurrences(inside, rendered)
                   for lo2, hi2 in paragraph.field_spans):
                return True
    return False


def _missing(paragraphs: Sequence[ParagraphText], row: Mapping[str, str | None], columns: Sequence[str],
             groups: Sequence[Group]) -> list[Missing]:
    covered = {column for group in groups for column in (group.column, *group.others)}
    out: list[Missing] = []
    for column in columns:
        value = row.get(column)
        if not value:
            out.append(Missing(column, REASON_EMPTY))
        elif column not in covered and not _in_fields(paragraphs, value):
            out.append(Missing(column, REASON_NOT_FOUND))
    return out


def propose(paragraphs: Sequence[ParagraphText], row: Mapping[str, str | None], columns: Sequence[str], *,
            existing_fields: Collection[str] = (), dismissed: Collection[tuple[str, str]] = (),
            picks: Mapping[str, str] | None = None) -> Proposal:
    """문서 문단과 행 하나로 제안을 짓는다. ``dismissed`` 는 「그대로 두기」 한 (열, 원시 값) 집합이고,
    ``picks`` 는 사람이 같은 값의 열 가운데 고른 열(묶음 열쇠 → 열)이다."""
    view = DocumentView(paragraphs)
    ordered = {column: row.get(column) for column in columns}
    slots = mask(find_candidates(paragraphs, ordered))
    existing = set(existing_fields)
    groups = _one_per_column(_groups(view, slots, ordered, columns, existing, picks or {}))
    # 「그대로 두기」 한 묶음과, 이미 필드가 된 이름의 남은 보류(필드 밖 산문 반복)는 싣지 않는다.
    kept = [group for group in groups if (group.column, group.raw) not in set(dismissed)
            and not (group.kind == KIND_HELD and group.links_existing)]
    return Proposal(kept, _missing(paragraphs, ordered, columns, groups))


def note_for(group: Group) -> list[dict]:
    """다른 열도 같은 값일 때의 열 목록(계약 「columns」)."""
    return [{"name": other, "note": note_same_value(other)} for other in group.others]
