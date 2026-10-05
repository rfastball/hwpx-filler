"""묶음(같은 값의 자리들) 하나의 등급 — 제안·보류·짧은 값, 그리고 사람에게 보일 문장.

규칙(계약 「등급과 판정」 v2). 자리는 넷으로 가른다 — **라벨 자리**(자리 앞 라벨이 열을 부르고, 낱말
가운데가 아니고, 고정 문구 단서가 없다), **값만 있는 자리**(줄·칸에 값만 있거나 — 같은 문단의 다른 후보
값은 가리고 본다 — 전화번호·직함 앞 이름·「제…호」 번호 틀·다른 값 뒤 괄호 풀이 같은 자료 단서),
**고정 문구 자리**(따옴표 제목·인용 법령·일반·당위 문장 안), **문장 속 자리**(그 밖).
다른 곳의 라벨 자리를 산문에서 되풀이하는 「한 값 한 자리」는 약한 단서라 자리를 보류하지 않는다.

1. **제안** — (a) 라벨 자리가 있으면(열이 정해진다) 늘 제안한다. 라벨 자리와 값만 있는 자리를 싣고
   문장 속·고정 문구 자리는 뺀다. 열 이름을 글자 그대로 담은 라벨이 있으면 동의어·글자쌍으로만 열을 부르는
   다른 라벨의 자리(「입찰방법:」이 있는 문서의 「입찰방식:」)는 다른 항목이라 뺀다.
   (b) 라벨이 없고 열이 하나면: 고정 문구 단서가 있으면 보류, 아니면 값만
   있는 자리가 하나라도 있을 때 그 자리만 싣는다(문장 속 자리는 뺀다).
   어느 쪽이든 뺀 자리가 있으면 몇 곳을 왜 뺐는지 한 문장을 단다.
2. **보류** — 제안이 아닌 묶음(같은 값의 열이 여럿인데 라벨이 하나를 가리키지 않음, 고정 문구, 문장 속
   자리뿐). 이유 한 문장이 늘 붙는다.
3. **짧은 값**(구체성 < 0.75) — 라벨 자리가 없으면 묶음을 내지 않는다. 있으면 라벨 자리와, 값만 있고
   양쪽이 한글이 아닌 자리(「대표」의 「대」가 아닌 「40 대」의 「대」)를 싣는다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .candidates import SPECIFIC, specificity
from .evidence import SpotEvidence

KIND_PROPOSAL = "proposal"
KIND_HELD = "held"


def reason_prose_repeats(count: int) -> str:
    return f"같은 값 {count}곳이 모두 문장 속에 있어 일반 낱말로 보입니다."


REASON_PROSE_ONCE = "문장 속 자리입니다. 문서마다 바뀌는 값인지 데이터 행 하나로는 알 수 없습니다."
REASON_FIXED = "고정 문구 안의 낱말로 보입니다."
REASON_GENERIC = "규정·안내 문장 안의 낱말로 보입니다."
REASON_BAD_NAME = "열 이름을 필드 이름으로 쓸 수 없습니다. 문구를 고르고 직접 필드로 만드세요."


#: 같은 값의 열이 둘 이상인데 라벨이 하나를 가리키지 않을 때 — 열 이름은 팝오버의 출처 줄·다른 열 주석이 이미 말한다.
REASON_TIE = "값이 같은 열이 여럿입니다. 연결할 열을 고르세요."


def note_short(label: str, chosen: int, others: int) -> str:
    """싣는 자리가 라벨 자리뿐이고 뺀 자리가 있을 때."""
    return f"라벨 ‘{label}’ 옆 {chosen}곳만 골랐습니다. 다른 {others}곳은 라벨이 없어 고르지 않았습니다."


def note_prose(chosen: int, others: int) -> str:
    """값만 있는 자리를 (라벨 자리와 함께) 싣고 문장 속 자리를 뺐을 때."""
    return f"값만 있는 자리 {chosen}곳을 골랐습니다. 문장 속 {others}곳은 고르지 않았습니다."


def count_short(chosen: int) -> str:
    return f"라벨 옆 {chosen}곳만"


def count_spots(count: int) -> str:
    return f"{count}곳"


def note_same_value(column: str) -> str:
    return f"‘{column}’ 열도 같은 값입니다."


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


def _resolve_column(columns: Sequence[str], spots: Sequence[SpotEvidence],
                    pick: str | None = None) -> tuple[str | None, list[SpotEvidence]]:
    """라벨이 부르는 열 하나와 그 라벨 자리 — 라벨이 둘 이상의 열을 부르거나 없으면 (None, []).

    사람이 같은 값의 열 가운데 하나를 골랐으면(``pick``) 그 열이고, 라벨 자리는 라벨이 있는 자리 전부다.
    """
    labelled = [spot for spot in spots if spot.labelled]
    fixed = _fixed_column(columns, pick)
    if fixed is not None:
        return fixed, labelled
    named = {column for spot in labelled for column in spot.matched}
    if len(named) != 1:
        return None, []
    column = next(iter(named))
    return column, [spot for spot in labelled if spot.matched == (column,)]


def _fixed_column(columns: Sequence[str], pick: str | None) -> str | None:
    """라벨 없이도 정해진 열 — 사람이 고른 열, 아니면 후보 열이 하나뿐일 때 그 열."""
    if pick in columns:
        return pick
    return columns[0] if len(columns) == 1 else None


def grade(columns: Sequence[str], spots: Sequence[SpotEvidence], pick: str | None = None) -> Grade | None:
    """후보 열(차례대로)과 자리 증거로 묶음 판정. 짧은 값에 라벨 자리가 없으면 None(묶음을 내지 않는다)."""
    column, labelled = _resolve_column(columns, spots, pick)
    short = specificity(spots[0].text) < SPECIFIC
    if column is None:
        # 열 하나는 늘 정해진다 — 여기는 같은 값의 열이 둘 이상이고 라벨이 하나를 가리키지 않을 때다.
        return None if short else Grade(KIND_HELD, columns[0], list(columns[1:]), list(spots),
                                        reason=REASON_TIE)
    others = [other for other in columns if other != column]
    if short:
        return _offer(column, others, labelled, spots, _short_alone) if labelled else None
    if labelled:
        return _offer(column, others, labelled, spots, _alone)
    return _grade_unlabelled(column, others, spots)


def _foreign(column: str, labelled: Sequence[SpotEvidence]) -> Callable[[SpotEvidence], bool]:
    """다른 항목의 라벨 자리 — 열 이름을 글자 그대로 담은 라벨 자리가 있으면, 동의어·글자쌍으로만 이 열을
    부르는 라벨(「입찰방법:」이 있는 문서의 「입찰방식: 전자입찰(국내입찰)」)은 다른 항목의 것이다."""
    if not any(column in spot.literal for spot in labelled):
        return lambda _spot: False
    return lambda spot: column in spot.matched and column not in spot.literal


def _alone(spot: SpotEvidence) -> bool:
    """라벨 자리 밖에서 실을 자리 — 값만 있는 자리(고정 문구 단서 없음)."""
    return spot.anchored and not (spot.fixed or spot.generic)


def _short_alone(spot: SpotEvidence) -> bool:
    """짧은 값이 라벨 자리 밖에서 실을 자리 — 줄·칸에 값만 있고 양쪽이 한글이 아니다."""
    return spot.standalone and spot.bounded and not spot.glued and not (spot.fixed or spot.generic)


def _offer(column: str, others: list[str], labelled: Sequence[SpotEvidence], spots: Sequence[SpotEvidence],
           alone: Callable[[SpotEvidence], bool]) -> Grade:
    """제안 — 라벨 자리와 ``alone`` 자리를 문서 차례로 싣고, 뺀 자리가 있으면 그 문장을 단다.

    자리 수 문구는 라벨 자리만 실었을 때만 여기서 짓는다(「라벨 옆 n곳만」) — 그 밖은 만들 수 있는 자리 수다.
    """
    foreign = _foreign(column, labelled)
    labelled = [spot for spot in labelled if not foreign(spot)]
    kept = [spot for spot in spots if not foreign(spot) and (spot in labelled or alone(spot))]
    left_out = len(spots) - len(kept)
    if not left_out:
        return Grade(KIND_PROPOSAL, column, others, kept)
    if all(spot in labelled for spot in kept):
        return Grade(KIND_PROPOSAL, column, others, kept, note=note_short(labelled[0].label, len(kept), left_out),
                     count_text=count_short(len(kept)))
    return Grade(KIND_PROPOSAL, column, others, kept, note=note_prose(len(kept), left_out))


def _grade_unlabelled(column: str, others: list[str], spots: Sequence[SpotEvidence]) -> Grade:
    """라벨 없는 묶음 — 고정 문구면 보류, 값만 있는 자리가 있으면 그 자리만 제안, 아니면 문장 속이라 보류."""
    if any(spot.generic for spot in spots):
        return Grade(KIND_HELD, column, others, list(spots), reason=REASON_GENERIC)
    if any(spot.fixed for spot in spots):
        return Grade(KIND_HELD, column, others, list(spots), reason=REASON_FIXED)
    if any(spot.anchored for spot in spots):
        return _offer(column, others, (), spots, _alone)
    reason = REASON_PROSE_ONCE if len(spots) == 1 else reason_prose_repeats(len(spots))
    return Grade(KIND_HELD, column, others, list(spots), reason=reason)
