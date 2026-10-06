"""작업대 본문 편집본의 **사상과 판정**(링1, #1148 PR B 후속).

표면은 편집 범위를 보내지 않고 편집본 전문만 보낸다. 그래서 표식의 자리는 원문(렌더)→편집본
차이로 **추정**한다. 추정은 하나로 정해지지 않을 수 있다 — 되풀이되는 글자(``AAA`` → ``ABAA``),
붙어 있는 표식(``{{x}}{{y}}``), 표식 옆 원문을 바꾼 편집. 그래서 판정은 보수 쪽에 선다:

- 빈 자리(빈 값·비워 둠)는 **그 자리에 끼어든 글자만** 채움으로 본다. 표식 밖 원문 글자를 걸쳐
  바꾼 편집, 옆 원문 글자 쪽으로 미끄러질 수 있는 삽입, 다른 표식과 같은 자리의 삽입은 어느
  쪽 것인지 말할 수 없으므로 채우지 않은 것으로 남는다. 같은 이름의 빈 자리가 여럿이면 **전부**
  채워야 그 이름이 채워진다.
- 미치환 토큰은 **그 토큰 글자가 편집본에서 사라졌을 때만** 고친 것이다 — 자리 추정과 무관하게
  센다(옆에 친 글자로는 해소되지 않는다).

갈래가 둘 이상이면 복사 전 확인이 계속 묻는다: 과경고의 값은 확인 한 번이고, 과소경고의 값은
빈 칸이 박힌 문서다.

전각 정렬(결정 17)은 표시 축이다. 표면이 보낸 글은 정렬된 표시본을 고친 것이므로
:func:`plain_edit` 가 앱이 넣은 전각 공백만 반각 둘로 되돌려 정렬 전 글로 보관하게 한다.
"""

from __future__ import annotations

from dataclasses import replace
from difflib import SequenceMatcher

from ..domain.text_render import SEG_BLANK, SEG_MISSING

__all__ = ["MARK_DECLARED", "HOLE_KINDS", "alignment", "map_marks", "plain_edit", "resolved_names"]

#: 확정-비움(「비워 둠」 선언) 자리 — 렌더는 빈 값과 같지만 복사 전 확인에서 빠진다.
MARK_DECLARED = "declared"
#: 글자를 쳐서 채우는 자리(길이 0 이거나 공백뿐인 값).
HOLE_KINDS = (SEG_BLANK, MARK_DECLARED)


def _opcodes(a: str, b: str) -> "list[tuple[str, int, int, int, int]]":
    ops: "list[tuple[str, int, int, int, int]]" = list(
        SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    )
    return ops or [("equal", 0, 0, 0, 0)]


def _cost(ops) -> int:
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in ops if tag != "equal")


def alignment(base: str, edited: str) -> "list[tuple[str, int, int, int, int]]":
    """원문→편집본 차이 — 앞에서 맞춘 것과 뒤에서 맞춘 것 중 **덜 고친** 쪽(같으면 앞쪽).

    SequenceMatcher 는 가장 긴 일치를 먼저 잡으므로 되풀이 글자에서 최소 편집이 아닌 정렬을
    낼 수 있다(``AAA`` → ``ABAA`` 를 「AB 삽입 + A 삭제」로 본다). 뒤집어 한 번 더 맞추면 다른
    쪽 끝을 먼저 잡는다.
    """
    n, m = len(base), len(edited)
    backward = [
        (tag, n - i2, n - i1, m - j2, m - j1)
        for tag, i1, i2, j1, j2 in reversed(_opcodes(base[::-1], edited[::-1]))
    ]
    return min(_opcodes(base, edited), backward, key=_cost)


def _left(pos: int, ops) -> int:
    """원문 자리 → 편집본 자리, 그 자리에 끼어든 글자 **앞**. 그 자리에서 끝난 편집은 넘는다."""
    for tag, i1, i2, j1, _j2 in ops:
        if i2 > pos or i1 == pos:
            return j1 + (pos - i1) if tag == "equal" and i1 < pos else j1
    return ops[-1][4]


def _right(pos: int, ops) -> int:
    """원문 자리 → 편집본 자리, 그 자리에 끼어든 글자 **뒤**. 그 자리에서 시작한 편집은 넘지 않는다."""
    for tag, i1, i2, j1, j2 in reversed(ops):
        if i1 < pos or i2 == pos:
            return j1 + (pos - i1) if tag == "equal" and i2 > pos else j2
    return ops[0][3]


def _inward(mark, ops):
    """표식 경계에 끼어든 글자는 **밖**에 둔다(미치환·채우지 않은 빈 자리)."""
    start = _right(mark.start, ops)
    return replace(mark, start=start, end=max(start, _left(mark.end, ops)))


def _outward(mark, ops):
    """표식 경계에 끼어든 글자는 **안**에 둔다(값·채운 빈 자리)."""
    start = _left(mark.start, ops)
    return replace(mark, start=start, end=max(start, _right(mark.end, ops)))


def _ambiguous_insert(mark, others, base: str, pos: int, text: str) -> bool:
    """경계 ``pos`` 의 삽입 ``text`` 가 이 빈 자리의 것이라고 단정할 수 없는가."""
    if any(other.start <= pos <= other.end for other in others):
        return True   # 붙어 있는 다른 표식의 것일 수도 있다
    if pos == mark.start and pos > 0 and base[pos - 1] == text[-1]:
        return True   # 왼쪽 원문 글자 쪽으로 미끄러진 같은 편집이 있다
    return pos == mark.end and pos < len(base) and base[pos] == text[0]


def _attributable(mark, others, ops, base: str, edited: str) -> bool:
    """이 빈 자리에 닿은 편집이 전부 **이 자리의 것**인가."""
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        if i1 < mark.start < i2 or i1 < mark.end < i2:
            return False  # 표식 밖 원문 글자를 걸쳐 바꿨다
        if i1 == i2 and i1 in (mark.start, mark.end) and _ambiguous_insert(
            mark, others, base, i1, edited[j1:j2]
        ):
            return False
    return True


def _hole(mark, others, ops, base: str, edited: str):
    """빈 자리 1건 → (편집본 위 표식, 채웠는가)."""
    wide = _outward(mark, ops)
    if edited[wide.start:wide.end].strip() and _attributable(mark, others, ops, base, edited):
        return wide, True
    return _inward(mark, ops), False


def map_marks(base: str, marks, edited: str):
    """원문 표식 → (편집본 위 표식, 채운 빈 자리 이름). 판정 규칙은 모듈 docstring."""
    ops = alignment(base, edited)
    mapped, unfilled = [], set()
    for k, mark in enumerate(marks):
        if mark.kind in HOLE_KINDS:
            moved, filled = _hole(mark, marks[:k] + marks[k + 1:], ops, base, edited)
            if not filled:
                unfilled.add(mark.name)
        else:
            moved = _inward(mark, ops) if mark.kind == SEG_MISSING else _outward(mark, ops)
        mapped.append(moved)
    holes = {m.name for m in marks if m.kind in HOLE_KINDS}
    return tuple(mapped), frozenset(holes - unfilled)


def resolved_names(base: str, marks, edited: str) -> frozenset[str]:
    """미치환 이름 중 **고친** 것 — 그 토큰 글자가 편집본에서 사라졌을 때만이다.

    원문에서 표식 밖(값 안 등)에 이미 있던 같은 글자는 빼고 센다. 토큰 하나를 지우고 같은
    글자를 다른 자리에 다시 쳤으면 복사본엔 여전히 그 토큰이 있으므로 해소가 아니다.
    """
    counts: "dict[tuple[str, str], int]" = {}
    for mark in marks:
        if mark.kind == SEG_MISSING:
            key = (mark.name, base[mark.start:mark.end])
            counts[key] = counts.get(key, 0) + 1
    kept = {
        name for (name, token), n in counts.items()
        if edited.count(token) > base.count(token) - n
    }
    return frozenset({name for name, _ in counts} - kept)


def _plain_offsets(shown: str, plain: str) -> "list[int]":
    """표시본 글자 → 정렬 전 글 자리. 전각 공백 하나는 정렬 전 반각 둘이다."""
    offsets, i = [], 0
    for ch in shown:
        offsets.append(i)
        i += 1 if plain[i:i + 1] == ch else 2
    offsets.append(i)
    assert i == len(plain)  # 표시본은 언제나 정렬 전 글의 정렬이다(card_view 가 짓는다)
    return offsets


def plain_edit(shown: str, plain: str, edited: str) -> str:
    """표시본 ``shown`` 을 고친 ``edited`` → 정렬 전 글.

    고치지 않은 자리는 정렬 전 글자(``plain``)를 그대로 가져오고, 사용자가 친 글자는 친 그대로
    둔다. 정렬이 꺼져 있으면 ``shown == plain`` 이라 ``edited`` 가 그대로 나온다.
    """
    offsets = _plain_offsets(shown, plain)
    return "".join(
        plain[offsets[i1]:offsets[i2]] if tag == "equal" else edited[j1:j2]
        for tag, i1, i2, j1, j2 in _opcodes(shown, edited)
    )
