"""「가공」 편집 보조 — 요약 문장·방식 목록·끌어 고르기 제안·불러온 행 미리보기 (링1).

연결 표의 「가공」 칸은 문장 하나(``‘-’ 앞까지``)를 칩으로 보이고, 열면 예시 값을 끌어 고르거나
방식 문장의 빈칸을 채워 명세를 짓는다. 그 화면이 보이는 **뜻**은 전부 여기서 낸다:

- :func:`slice_label` — 칩·후보가 말하는 문장. 웹이 명세를 읽어 문장을 다시 짓지 않는다.
- :func:`slice_methods` — 방식 문장의 조각(글자·입력 칸·몇째 선택지)과 새 명세의 빠짐 처리 기본값.
- :func:`propose_slices` — 예시 값에서 고른 부분을 재현하는 방식 후보, 불러온 행의 같은 모양 수로 정렬.
- :func:`preview_slice` — 불러온 행마다 원본·남긴 자리·결과·상태(맞음/형식 다름/확인 필요/빈 값).

판정 자체(명세의 모양·적용)는 도메인 :mod:`hwpxfiller.domain.text_slice` 한 곳이다. 여기는 그
판정기를 불러 사람이 읽을 모양으로 옮길 뿐이다. 새 명세가 빠짐에서 무엇을 낼지의 기본값(원본
그대로)도 여기 하나가 정한다 — 키 없는 저장 명세의 뜻(빈 값)과는 다른 축이다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from ..domain.job import MISSING_MARKER
from ..domain.text_slice import (
    MISSABLE_MODES,
    ON_MISSING_EMPTY,
    ON_MISSING_KEEP,
    TEXT_SLICE_AFTER,
    TEXT_SLICE_BEFORE,
    TEXT_SLICE_BETWEEN,
    TEXT_SLICE_CHARS,
    TEXT_SLICE_HEAD,
    TEXT_SLICE_REMOVE,
    TEXT_SLICE_REPLACE,
    TEXT_SLICE_SPLIT,
    TEXT_SLICE_TAIL,
    TextSlice,
)

#: 가공이 없는 칸의 칩 문안(점선 칩).
SLICE_ADD_LABEL = "+ 가공"
#: 편집 칸이 보이는 불러온 행 수의 상한 — 예시 행 칩·미리보기 격자·후보 채점이 같은 창을 본다.
SLICE_PREVIEW_ROWS = 10
#: 끌어 고른 부분이 나누기 후보가 되는 흔한 구분자(글자 그대로).
SPLIT_CANDIDATE_DELIMITERS = (",", "-", "/", " ", "·")
#: 새 명세가 빠짐(기준 글자·조각·범위 없음)에서 낼 것 — 원본 그대로(사용자 확정).
NEW_SLICE_ON_MISSING = ON_MISSING_KEEP
#: 빠짐 처리를 사람이 고르는 방식 — 기준 글자로 고르는 셋.
MISS_CHOICE_MODES = frozenset({TEXT_SLICE_BEFORE, TEXT_SLICE_AFTER, TEXT_SLICE_BETWEEN})

GROUP_PART_LABEL = "일부만 쓰기"
GROUP_EDIT_LABEL = "글자 고치기"
NO_SLICE_HINT = "쓸 부분을 끌어 고르거나 방식을 고르세요."
NO_CANDIDATE_MESSAGE = "고른 부분에 맞는 방식이 없습니다. 방식을 직접 고르세요."
MISS_CHOICE_LABELS = ({"value": ON_MISSING_KEEP, "label": "원본 그대로"},
                      {"value": ON_MISSING_EMPTY, "label": "빈 값"})

STATUS_HIT = "hit"
STATUS_ODD = "odd"
STATUS_MISS = "miss"
STATUS_EMPTY = "empty"
STATUS_PLAIN = "plain"
_STATUS_WORD = {
    STATUS_HIT: "맞음",
    STATUS_ODD: "형식 다름",
    STATUS_MISS: "확인 필요",
    STATUS_EMPTY: "빈 값",
}

_NATIVE_ORDINALS = (
    "첫째", "둘째", "셋째", "넷째", "다섯째", "여섯째", "일곱째", "여덟째", "아홉째", "열째",
)
#: 몇째 선택지의 기본 목록 — 저장 명세의 번째가 여기 없으면 그 값도 선택지에 선다.
_DEFAULT_INDEXES = (1, 2, 3, -1)

_SHAPE_RE = re.compile(r"[0-9]+|[A-Za-z]+|[가-힣]+")


def _q(text: str) -> str:
    return f"‘{text}’"


def ordinal_label(index: int) -> str:
    """조각 번째의 사람 말 — ``1`` 첫째, ``-1`` 마지막, ``-2`` 끝에서 둘째."""
    if index == -1:
        return "마지막"
    if index < 0:
        return f"끝에서 {ordinal_label(-index)}"
    if 1 <= index <= len(_NATIVE_ORDINALS):
        return _NATIVE_ORDINALS[index - 1]
    return f"{index}번째"


def slice_label(spec: TextSlice | None) -> str:
    """가공 명세 → 칩·후보가 말하는 문장. 없으면 ``+ 가공``."""
    if spec is None:
        return SLICE_ADD_LABEL
    mode = spec.mode
    if mode == TEXT_SLICE_BEFORE:
        return f"{_q(str(spec.delimiter))} 앞까지"
    if mode == TEXT_SLICE_AFTER:
        return f"{_q(str(spec.delimiter))} 뒤부터"
    if mode == TEXT_SLICE_BETWEEN:
        return f"{_q(str(spec.open))} 뒤부터 {_q(str(spec.close))} 앞까지"
    if mode == TEXT_SLICE_SPLIT:
        assert spec.index is not None
        return f"{_q(str(spec.delimiter))}로 나눈 조각 중 {ordinal_label(spec.index)}"
    if mode == TEXT_SLICE_HEAD:
        return f"앞에서 {spec.count}글자"
    if mode == TEXT_SLICE_TAIL:
        return f"뒤에서 {spec.count}글자"
    if mode == TEXT_SLICE_CHARS:
        if spec.length is None:
            return f"{spec.start}번째 글자부터"
        return f"{spec.start}번째 글자부터 {spec.length}글자"
    if mode == TEXT_SLICE_REPLACE:
        return f"{_q(str(spec.find))} 대신 {_q(str(spec.replace))}"
    return f"{_q(str(spec.find))} 지우기"


def split_index_options(spec: TextSlice | None) -> list[dict]:
    """「몇째 조각」 선택지 — 기본 넷에 저장 명세의 번째를 더한다(흔치 않은 값도 사라지지 않게)."""
    indexes: list[int] = list(_DEFAULT_INDEXES)
    if spec is not None and spec.mode == TEXT_SLICE_SPLIT and spec.index not in indexes:
        assert spec.index is not None
        indexes.append(spec.index)
    positive = sorted(i for i in indexes if i > 0)
    negative = sorted((i for i in indexes if i < 0), reverse=True)
    return [{"value": i, "label": ordinal_label(i)} for i in positive + negative]


def _text_input(key: str, label: str, *, wide: bool = False) -> dict:
    return {"input": key, "kind": "text", "label": label, "wide": wide}


def _number_input(key: str, label: str, *, optional: bool = False) -> dict:
    return {"input": key, "kind": "number", "label": label, "optional": optional}


def _method(mode: str, *parts: dict) -> dict:
    return {
        "mode": mode,
        "parts": list(parts),
        # 빠짐 처리 칸(원본 그대로/빈 값)이 서는가, 그리고 새 명세가 싣는 빠짐 처리.
        "miss_choice": mode in MISS_CHOICE_MODES,
        "on_missing": NEW_SLICE_ON_MISSING if mode in MISSABLE_MODES else None,
    }


def slice_methods(spec: TextSlice | None) -> list[dict]:
    """방식 목록 — 무리 둘(일부만 쓰기·글자 고치기)과 방식마다 문장 조각.

    조각은 글자(``{"text"}``, 앞 칸에 붙는 조사·단위면 ``attach``)이거나 입력 칸(``{"input", "kind", "label"}``)이다. ``kind`` 는
    ``text``·``number``·``ordinal``(몇째 선택지, ``options`` 동봉)이고 ``label`` 은 칸의 접근 이름이다.
    웹은 이 순서대로 그리고, 칸 값으로 ``{"mode", 키: 값}`` 을 모아 편집 동사에 보낸다.
    """
    ordinal = {
        "input": "index", "kind": "ordinal", "label": "몇째 조각",
        "options": split_index_options(spec),
    }
    part = [
        _method(TEXT_SLICE_BEFORE, _text_input("delimiter", "앞까지의 기준 글자"), {"text": "앞까지"}),
        _method(TEXT_SLICE_AFTER, _text_input("delimiter", "뒤부터의 기준 글자"), {"text": "뒤부터"}),
        _method(
            TEXT_SLICE_BETWEEN,
            _text_input("open", "뒤부터의 기준 글자"), {"text": "뒤부터"},
            _text_input("close", "앞까지의 기준 글자"), {"text": "앞까지"},
        ),
        _method(
            TEXT_SLICE_SPLIT,
            _text_input("delimiter", "나누는 글자"), {"text": "로 나눈 조각 중", "attach": True}, ordinal,
        ),
        _method(TEXT_SLICE_HEAD, {"text": "앞에서"}, _number_input("count", "앞에서 글자 수"),
                {"text": "글자", "attach": True}),
        _method(TEXT_SLICE_TAIL, {"text": "뒤에서"}, _number_input("count", "뒤에서 글자 수"),
                {"text": "글자", "attach": True}),
        _method(
            TEXT_SLICE_CHARS,
            _number_input("start", "몇 번째 글자부터"), {"text": "번째 글자부터", "attach": True},
            _number_input("length", "글자 수", optional=True), {"text": "글자", "attach": True},
        ),
    ]
    edit = [
        _method(
            TEXT_SLICE_REPLACE,
            _text_input("find", "찾을 글자", wide=True), {"text": "대신"},
            _text_input("replace", "바꿀 글자", wide=True),
        ),
        _method(TEXT_SLICE_REMOVE, _text_input("find", "지울 글자", wide=True), {"text": "지우기"}),
    ]
    return [
        {"label": GROUP_PART_LABEL, "methods": part},
        {"label": GROUP_EDIT_LABEL, "methods": edit},
    ]


# ─── 모양·좌표 ──────────────────────────────────────────────────────────────────
def value_shape(text: str) -> str:
    """값의 모양 — 숫자 묶음은 ``9``, 라틴 글자 묶음은 ``a``, 한글 묶음은 ``가``, 나머지는 그대로."""

    def shape(match: re.Match[str]) -> str:
        head = match.group(0)[0]
        if head.isdigit():
            return "9"
        return "a" if head.isascii() else "가"

    return _SHAPE_RE.sub(shape, text.strip())


def code_point_offset(text: str, utf16_offset: int) -> int:
    """브라우저 선택 좌표(UTF-16 코드 단위) → 파이썬 글자 좌표. 대리 쌍 한가운데는 거절한다."""
    if isinstance(utf16_offset, bool) or not isinstance(utf16_offset, int) or utf16_offset < 0:
        raise ValueError(f"선택 좌표가 올바르지 않음: {utf16_offset!r}")
    units = 0
    for index, char in enumerate(text):
        if units == utf16_offset:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
        if units > utf16_offset:
            raise ValueError(f"선택 좌표가 글자 가운데를 가리킴: {utf16_offset!r}")
    if units == utf16_offset:
        return len(text)
    raise ValueError(f"선택 좌표가 값 밖을 가리킴: {utf16_offset!r}")


def slice_values(records: Iterable[Mapping[str, object]], source: str) -> list[str]:
    """편집 칸이 보는 불러온 행의 값 — 앞 :data:`SLICE_PREVIEW_ROWS` 행, 앞뒤 공백을 걷은 칸 글자.

    공백 정리 → 가공 순서의 첫 단계다 — 값을 읽는 모양까지 legacy
    :meth:`~hwpxfiller.domain.mapping.FieldMapping.value_for` 와 같다(``str(...).strip()``).
    """
    out: list[str] = []
    for record in records:
        if len(out) >= SLICE_PREVIEW_ROWS:
            break
        out.append(str(record.get(source, "")).strip())
    return out


def _default_sample(values: Sequence[str], requested: object) -> int | None:
    """예시 행 — 요청한 행이 값이 있으면 그 행, 아니면 값이 있는 첫 행(없으면 없음)."""
    if (
        isinstance(requested, int)
        and not isinstance(requested, bool)
        and 0 <= requested < len(values)
        and values[requested] != ""
    ):
        return requested
    return next((i for i, value in enumerate(values) if value != ""), None)


def _miss_tag(spec: TextSlice) -> str:
    if spec.mode in (TEXT_SLICE_BEFORE, TEXT_SLICE_AFTER):
        return f"{_q(str(spec.delimiter))} 없음"
    if spec.mode == TEXT_SLICE_BETWEEN:
        return f"{_q(str(spec.open))} 또는 {_q(str(spec.close))} 없음"
    if spec.mode == TEXT_SLICE_SPLIT:
        return "조각 없음"
    return _STATUS_WORD[STATUS_MISS]


def _segments(value: str, span: tuple[int, int] | None) -> dict:
    """원본을 남긴 자리 앞·가운데·뒤로 — 자리가 없으면 전부 앞(흐리게)."""
    if span is None:
        return {"pre": value, "keep": "", "post": ""}
    return {"pre": value[: span[0]], "keep": value[span[0]:span[1]], "post": value[span[1]:]}


# ─── 제안 ────────────────────────────────────────────────────────────────────────
def _candidate_specs(value: str, start: int, end: int) -> list[TextSlice]:
    """고른 ``[start, end)`` 를 낼 수 있는 방식 후보(생성 순서) — 재현 여부는 부르는 쪽이 본다."""
    tries: list[TextSlice] = []
    want = value[start:end]

    def next_char(index: int) -> str:
        while index < len(value) and value[index].isspace():
            index += 1
        return value[index] if index < len(value) else ""

    def prev_char(index: int) -> str:
        while index > 0 and value[index - 1].isspace():
            index -= 1
        return value[index - 1] if index > 0 else ""

    after = next_char(end) if end < len(value) else ""
    before = prev_char(start) if start > 0 else ""
    keep = NEW_SLICE_ON_MISSING
    if start == 0 and after:
        tries.append(TextSlice(TEXT_SLICE_BEFORE, delimiter=after, on_missing=keep))
    if end == len(value) and before:
        tries.append(TextSlice(TEXT_SLICE_AFTER, delimiter=before, on_missing=keep))
    if start > 0 and end < len(value) and before and after:
        tries.append(TextSlice(TEXT_SLICE_BETWEEN, open=before, close=after, on_missing=keep))
    for delimiter in SPLIT_CANDIDATE_DELIMITERS:
        if delimiter not in value:
            continue
        pieces = [piece.strip() for piece in value.split(delimiter)]
        if want not in pieces:
            continue
        at = pieces.index(want)
        index = -1 if at == len(pieces) - 1 and at > 0 else at + 1
        tries.append(TextSlice(TEXT_SLICE_SPLIT, delimiter=delimiter, index=index, on_missing=keep))
    if start == 0:
        tries.append(TextSlice(TEXT_SLICE_HEAD, count=end))
    elif end == len(value):
        tries.append(TextSlice(TEXT_SLICE_TAIL, count=len(value) - start))
    else:
        tries.append(
            TextSlice(TEXT_SLICE_CHARS, start=start + 1, length=end - start, on_missing=keep)
        )
    return tries


def _match_count(spec: TextSlice, values: Sequence[str], target: str) -> int:
    matched = 0
    for value in values:
        if value == "":
            continue
        outcome = spec.evaluate(value)
        if not outcome.missed and value_shape(outcome.text) == target:
            matched += 1
    return matched


def propose_slices(values: Sequence[str], sample: int, start: int, end: int) -> dict:
    """예시 값에서 고른 부분(UTF-16 ``[start, end)``)을 재현하는 방식 후보 — 좋은 것부터.

    후보는 예시 값에서 **그 글자를 그대로 내는 것만** 남기고 방식마다 하나다. 불러온 행 중 값이
    있는 행에서 결과가 고른 부분과 같은 모양인 수로 정렬하고, 같으면 생성 순서(기준 글자 → 나누기
    → 자리)다. 후보가 없으면 ``message`` 가 다음 행동을 말한다.
    """
    if not (0 <= sample < len(values)) or values[sample] == "":
        raise ValueError(f"예시 행이 올바르지 않음: {sample!r}")
    value = values[sample]
    begin, finish = code_point_offset(value, start), code_point_offset(value, end)
    if finish < begin:
        raise ValueError(f"선택 범위가 거꾸로임: {start!r}~{end!r}")
    while begin < finish and value[begin].isspace():
        begin += 1
    while finish > begin and value[finish - 1].isspace():
        finish -= 1
    want = value[begin:finish]
    candidates: list[dict] = []
    if want:
        target = value_shape(want)
        total = sum(1 for item in values if item != "")
        seen: set[str] = set()
        scored: list[tuple[int, int, TextSlice]] = []
        for order, spec in enumerate(_candidate_specs(value, begin, finish)):
            outcome = spec.evaluate(value)
            if outcome.missed or outcome.text.strip() != want or spec.mode in seen:
                continue
            seen.add(spec.mode)
            scored.append((_match_count(spec, values, target), order, spec))
        scored.sort(key=lambda item: (-item[0], item[1]))
        candidates = [
            {
                "mode": spec.mode,
                "slice": spec.to_dict(),
                "label": slice_label(spec),
                "matched": matched,
                "total": total,
                "tag": f"{matched}/{total}행 맞음",
                "tip": f"맞는 행: 값 있는 {total}행 중 {matched}행",
                "full": matched == total,
            }
            for matched, _order, spec in scored
        ]
    return {
        "ok": True,
        "candidates": candidates,
        "message": "" if candidates else NO_CANDIDATE_MESSAGE,
    }


# ─── 미리보기 ─────────────────────────────────────────────────────────────────────
def preview_slice(
    field: str, spec: TextSlice | None, values: Sequence[str], *, sample: object = None
) -> dict:
    """불러온 행마다 원본·남긴 자리·결과·상태, 그리고 예시 값과 요약.

    상태는 넷이다: 맞음(예시 결과와 같은 모양) · 형식 다름(모양이 다르다) · 확인 필요(기준 글자·조각·
    범위가 없거나 결과가 비었다) · 빈 값(칸이 비었다). 바꾸기·지우기는 자리가 아니라 글자를 고치므로
    형식 다름을 재지 않는다. 결과가 비면 생성이 넣는 빈 값 표식을 그대로 싣는다.
    """
    marker = MISSING_MARKER.format(field=field)
    sample_index = _default_sample(values, sample)
    sample_value = "" if sample_index is None else values[sample_index]
    edits = spec is not None and spec.mode in (TEXT_SLICE_REPLACE, TEXT_SLICE_REMOVE)
    sample_outcome = None if spec is None or sample_index is None else spec.evaluate(sample_value)
    target = (
        value_shape(sample_outcome.text)
        if sample_outcome is not None and not sample_outcome.missed and not edits
        and sample_outcome.text.strip()
        else None
    )
    counts = {STATUS_HIT: 0, STATUS_ODD: 0, STATUS_MISS: 0, STATUS_EMPTY: 0}
    rows: list[dict] = []
    for position, value in enumerate(values):
        tags: list[str] = []
        if value == "":
            status, result, segments = STATUS_EMPTY, "", _segments("", None)
        elif spec is None:
            status, result, segments = STATUS_PLAIN, value, _segments(value, None)
        else:
            outcome = spec.evaluate(value)
            result, segments = outcome.text, _segments(value, outcome.span)
            if outcome.missed:
                status = STATUS_MISS
                tags.append(_miss_tag(spec))
            elif result.strip() == "":
                status = STATUS_MISS
            elif target is not None and value_shape(result) != target:
                status = STATUS_ODD
                tags.append(_STATUS_WORD[STATUS_ODD])
            else:
                status = STATUS_HIT
        if status in counts:
            counts[status] += 1
        empty_result = result.strip() == ""
        rows.append({
            "index": position,
            "label": f"{position + 1}행",
            **segments,
            "result": marker if empty_result else result,
            "marker": empty_result,
            "status": status,
            "tags": tags,
        })
    summary = " · ".join(
        f"{_STATUS_WORD[status]} {counts[status]}행"
        for status in (STATUS_HIT, STATUS_ODD, STATUS_MISS, STATUS_EMPTY)
        if counts[status]
    )
    sample_block: dict = {"index": sample_index, "value": sample_value, "miss_tag": ""}
    sample_block.update(
        _segments(sample_value, None if sample_outcome is None else sample_outcome.span)
    )
    if spec is not None and sample_outcome is not None and sample_outcome.missed:
        sample_block["miss_tag"] = _miss_tag(spec)
    miss_choice = None
    if spec is not None and spec.mode in MISS_CHOICE_MODES:
        subject = (
            f"{_q(str(spec.open))} 또는 {_q(str(spec.close))}"
            if spec.mode == TEXT_SLICE_BETWEEN
            else _q(str(spec.delimiter))
        )
        miss_choice = {
            "label": f"{subject} 없는 행",
            "value": spec.on_missing,
            "choices": [dict(choice) for choice in MISS_CHOICE_LABELS],
        }
    return {
        "ok": True,
        "slice": None if spec is None else spec.to_dict(),
        "rows": rows,
        "rows_label": f"불러온 {len(values)}행 미리보기",
        "summary": summary,
        "hint": NO_SLICE_HINT if spec is None else "",
        "sample": sample_block,
        "samples": [
            {
                "index": position,
                "label": str(position + 1),
                "aria": f"{position + 1}행" + (", 빈 값" if value == "" else ""),
                "disabled": value == "",
                "pressed": position == sample_index,
            }
            for position, value in enumerate(values)
        ],
        "miss_choice": miss_choice,
    }


def _payload_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} 값이 정수가 아님: {value!r}")
    return value


def slice_query(
    kind: str,
    *,
    field: str,
    source: str,
    spec: TextSlice | None,
    enabled: bool,
    records: Iterable[Mapping[str, object]],
    payload: Mapping[str, object],
) -> dict:
    """편집 칸의 무변이 질의 한 건 — ``preview``(불러온 행 미리보기) 또는 ``propose``(끌어 고르기 후보).

    편집기(`preview_slice`·`propose_slice`)와 작업대(`preview_map_slice`·`propose_map_slice`)가 같은
    몸통을 부른다. 원본 칸이 없는 행(고정값·오늘 날짜·무결속)은 가공이 설 수 없어 거절한다.
    """
    if not enabled:
        raise ValueError(f"가공은 데이터 열 값에만 둘 수 있음: {field!r}")
    values = slice_values(records, source)
    if kind == "preview":
        return preview_slice(field, spec, values, sample=payload.get("sample"))
    if kind == "propose":
        return propose_slices(
            values,
            _payload_int(payload, "sample"),
            _payload_int(payload, "start"),
            _payload_int(payload, "end"),
        )
    raise ValueError(f"알 수 없는 가공 질의: {kind!r}")


__all__ = [
    "NEW_SLICE_ON_MISSING",
    "NO_CANDIDATE_MESSAGE",
    "NO_SLICE_HINT",
    "SLICE_ADD_LABEL",
    "SLICE_PREVIEW_ROWS",
    "code_point_offset",
    "ordinal_label",
    "preview_slice",
    "propose_slices",
    "slice_label",
    "slice_methods",
    "slice_query",
    "slice_values",
    "split_index_options",
    "value_shape",
]
