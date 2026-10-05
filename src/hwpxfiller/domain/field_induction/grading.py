"""묶음(같은 값의 자리들) 하나의 등급 — 제안·보류·짧은 값, 그리고 사람에게 보일 문장.

규칙(계약 「등급과 판정」):

1. **제안** — (a) 라벨 자리가 있다: 자리 앞 라벨이 후보 열 하나만 부르고, 낱말 가운데가 아니고, 고정 문구
   단서가 없다. 라벨 자리 밖 출현이 3곳 이상이면 「한 값 한 자리」로 보류한다.
   (b) 라벨이 없다: 구체성 ≥ 0.75, 출현 ≤ 2, 고정 문구 단서 없음, 열 하나, 그리고 문장 속이 아닌 자리가
   있거나(줄·칸에 값만) 전화번호·직함 앞 이름 같은 자료 단서가 있다.
2. **보류** — 제안이 아닌 묶음. 이유 한 문장이 늘 붙는다.
3. **짧은 값**(구체성 < 0.75) — 라벨 옆 자리만 제안하고 나머지 출현은 어디에도 넣지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .candidates import specificity
from .evidence import SpotEvidence

SPECIFIC = 0.75
ONE_SLOT_OUTSIDE = 3
NO_LABEL_MAX = 2

KIND_PROPOSAL = "proposal"
KIND_HELD = "held"


def reason_one_slot(outside: int) -> str:
    return f"문장 속에도 {outside}번 나옵니다. 표 칸 1곳만 고를 수 있습니다."


def reason_prose_repeats(count: int) -> str:
    return f"문장 속 낱말과 같습니다. 같은 값 {count}곳이 모두 문장 속에 있습니다."


REASON_PROSE_ONCE = ("문장 속 자리입니다. 문서마다 바뀌는 값인지 데이터 행 하나로는 알 수 없습니다. "
                     "같은 양식 문서를 하나 더 넣으면 판단할 수 있습니다.")
REASON_FIXED = "고정 문구 안의 낱말로 보입니다."
REASON_GENERIC = "모든 문서에 같은 규정 문장 안에 있습니다."
REASON_BAD_NAME = "열 이름을 필드 이름으로 쓸 수 없습니다."


def reason_tie(first: str, second: str) -> str:
    return f"‘{first}’ 열과 ‘{second}’ 열의 값이 같아 어느 열인지 정할 수 없습니다."


def reason_many(count: int) -> str:
    """계약 밖 추가 문장 — 라벨 없이 3곳 이상, 그중 문장 밖 자리도 있을 때(보고서에 전문·사유)."""
    return f"같은 값이 {count}곳에 나옵니다. 문서마다 바뀌는 값인지 데이터 행 하나로는 알 수 없습니다."


def note_short(label: str, chosen: int, others: int, numeric: bool) -> str:
    inside = "다른 숫자 속입니다." if numeric else "다른 낱말 속입니다."
    return f"라벨 ‘{label}’ 옆 {chosen}곳만 골랐습니다. 다른 {others}곳은 {inside}"


def count_short(chosen: int) -> str:
    return f"라벨 옆 {chosen}곳만"


def count_spots(count: int) -> str:
    return f"{count}곳"


def note_same_value(column: str) -> str:
    return f"{column} 열도 같은 값입니다."


@dataclass
class Grade:
    """묶음 하나의 판정. ``spots`` 는 제안·보류에 실을 자리의 증거(만들 수 없는 자리 포함)다."""

    kind: str
    column: str
    others: list[str] = field(default_factory=list)
    spots: list[SpotEvidence] = field(default_factory=list)
    reason: str = ""
    note: str = ""
    count_text: str = ""
    only: SpotEvidence | None = None


def _resolve_column(columns: Sequence[str], spots: Sequence[SpotEvidence]) -> tuple[str | None, list[SpotEvidence]]:
    """라벨이 부르는 열 하나와 그 라벨 자리 — 라벨이 둘 이상의 열을 부르거나 없으면 (None, [])."""
    labelled = [spot for spot in spots if spot.labelled]
    named = {column for spot in labelled for column in spot.matched}
    if len(columns) == 1:
        return columns[0], labelled
    if len(named) != 1:
        return None, []
    column = next(iter(named))
    return column, [spot for spot in labelled if spot.matched == (column,)]


def grade(columns: Sequence[str], spots: Sequence[SpotEvidence]) -> Grade | None:
    """후보 열(차례대로)과 자리 증거로 묶음 판정. 짧은 값에 라벨 자리가 없으면 None(묶음을 내지 않는다)."""
    column, labelled = _resolve_column(columns, spots)
    short = specificity(spots[0].text) < SPECIFIC
    if column is None:
        # 열 하나는 늘 정해진다 — 여기는 같은 값의 열이 둘 이상이고 라벨이 하나를 가리키지 않을 때다.
        return None if short else Grade(KIND_HELD, columns[0], list(columns[1:]), list(spots),
                                        reason=reason_tie(columns[0], columns[1]))
    others = [other for other in columns if other != column]
    if short:
        return _grade_short(column, others, labelled, spots)
    if labelled:
        return _grade_labelled(column, others, labelled, spots)
    return _grade_unlabelled(column, others, spots)


def _grade_short(column: str, others: list[str], labelled: list[SpotEvidence],
                 spots: Sequence[SpotEvidence]) -> Grade | None:
    if not labelled:
        return None
    outside = len(spots) - len(labelled)
    numeric = any(ch.isdigit() for ch in spots[0].text)
    note = note_short(labelled[0].label, len(labelled), outside, numeric) if outside else ""
    count = count_short(len(labelled)) if outside else count_spots(len(labelled))
    return Grade(KIND_PROPOSAL, column, others, list(labelled), note=note, count_text=count)


def _grade_labelled(column: str, others: list[str], labelled: list[SpotEvidence],
                    spots: Sequence[SpotEvidence]) -> Grade:
    outside = len(spots) - len(labelled)
    if outside >= ONE_SLOT_OUTSIDE:
        return Grade(KIND_HELD, column, others, list(spots), reason=reason_one_slot(outside),
                     only=labelled[0])
    # 라벨 자리 밖의 출현 중 고정 문구 단서가 있는 자리(규정 문장·따옴표 제목 안)는 싣지 않는다(엔진 G1).
    kept = [spot for spot in spots if spot in labelled or spot.cue is None]
    return Grade(KIND_PROPOSAL, column, others, kept)


def _unlabelled_reason(spots: Sequence[SpotEvidence]) -> str:
    """라벨 없는 묶음의 보류 이유 — 빈 문자열이면 보류할 까닭이 없다(제안)."""
    if any(spot.generic for spot in spots):
        return REASON_GENERIC
    if any(spot.cue for spot in spots):
        return REASON_FIXED
    if len(spots) <= NO_LABEL_MAX and any(spot.standalone or spot.data for spot in spots):
        return ""
    return _prose_reason(spots)


def _prose_reason(spots: Sequence[SpotEvidence]) -> str:
    if any(spot.standalone for spot in spots):
        return reason_many(len(spots))
    return REASON_PROSE_ONCE if len(spots) == 1 else reason_prose_repeats(len(spots))


def _grade_unlabelled(column: str, others: list[str], spots: Sequence[SpotEvidence]) -> Grade:
    reason = _unlabelled_reason(spots)
    return Grade(KIND_HELD if reason else KIND_PROPOSAL, column, others, list(spots), reason=reason)
