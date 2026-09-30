"""텍스트 가공 — 데이터 칸의 글자 중 **일부만** 쓰거나 글자를 고친다(기초 가공, field-binding/v5).

실데이터가 드러낸 요구다: 계약 목록의 ``입찰공고번호`` 는 ``R26BK09017075-000`` 인데 문서에는
``R26BK09017075`` 가 들어가야 하고, ``조달요구번호`` 는 ``MPKPLA26910290, MPKPLA26910291``
처럼 쉼표로 여럿이 붙어 오며, 금액 칸에는 ``(VAT 포함)`` 같은 설명이 붙는다. 열을 새로 만들 수
없는 사용자에게 필요한 것은 「이 칸의 어느 부분」을 고르거나 몇 글자를 고치는 한 단계다.

한 연결에 가공은 **하나**다(잇지 않는다). 방식은 문장 하나로 읽힌다:

- ``before`` {delimiter} — ``‘x’ 앞까지``: 처음 나오는 ``x`` 앞의 글자.
- ``after`` {delimiter} — ``‘x’ 뒤부터``: 처음 나오는 ``x`` 뒤의 글자.
- ``between`` {open, close} — ``‘x’ 뒤부터 ‘y’ 앞까지``: 처음 ``x`` 뒤, 그 뒤 처음 ``y`` 앞.
- ``split`` {delimiter, index} — ``‘x’로 나눈 조각 중 첫째``: 조각은 앞뒤 공백을 걷고, 번째는
  1부터 센다(음수는 끝에서, ``-1`` = 마지막, 0 은 없다).
- ``head`` {count} / ``tail`` {count} — 앞에서·뒤에서 N글자(짧은 값은 그대로, 빠짐이 아니다).
- ``chars`` {start, length?} — ``start`` 번째 글자부터 ``length`` 글자(없으면 끝까지).
- ``replace`` {find, replace} — ``‘x’ 대신 ‘y’``: 모든 ``x`` 를 ``y`` 로, 앞뒤 공백을 걷는다.
- ``remove`` {find} — ``‘x’ 지우기``: 모든 ``x`` 를 지우고 앞뒤 공백을 걷는다.

글자는 전부 **글자 그대로**다(정규식이 아니다). ``before``·``after``·``between`` 의 결과는 앞뒤
공백을 걷는다. ``chars``·``head``·``tail`` 은 자리로 고르므로 걷지 않는다(v4 ``chars`` 와 같은 뜻).

**빠짐**(기준 글자·조각·범위가 없다)은 ``before``·``after``·``between``·``split``·``chars`` 에만
있고, 그때 무엇을 낼지가 ``on_missing`` 이다: ``"empty"`` 는 빈 값(→ 생성의 빈 값 표식),
``"keep"`` 은 원본 그대로. **키가 없으면 ``"empty"``** 다 — v0.10.0(field-binding/v4)이 저장한
명세는 이 키가 없고 그 뜻이 빈 값이었다. 새로 만드는 명세의 기본값(원본 그대로)은 편집 표면이
명시로 싣는다(:data:`ON_MISSING_KEEP`). ``head``·``tail``·``replace``·``remove`` 에는 빠짐이 없다.

가공은 원본 칸 텍스트(공백 정책 적용 뒤)에 걸리고 **표시형보다 먼저** 온다:
``170,309,180원 (VAT 포함)`` 의 ``‘원’ 앞까지`` 인 ``170,309,180`` 에 금액 표시형이 걸려
``170,309,180원`` 이 된다. 고정값·오늘 날짜에는 걸리지 않는다(원본 칸이 없다).

명세의 모양은 여기 한 곳이 판정한다 — 편집 시점(링1 편집 동사)과 규칙 구성 시점(바인딩 규칙·
실행 계획 해독)이 같은 판정기를 부르므로 잘못된 명세는 어느 쪽에서도 조용히 고쳐지지 않고
시끄럽게 거절된다. 이 모듈은 순수하다(Domain).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TEXT_SLICE_BEFORE = "before"
TEXT_SLICE_AFTER = "after"
TEXT_SLICE_BETWEEN = "between"
TEXT_SLICE_SPLIT = "split"
TEXT_SLICE_HEAD = "head"
TEXT_SLICE_TAIL = "tail"
TEXT_SLICE_CHARS = "chars"
TEXT_SLICE_REPLACE = "replace"
TEXT_SLICE_REMOVE = "remove"
TEXT_SLICE_MODES = (
    TEXT_SLICE_BEFORE,
    TEXT_SLICE_AFTER,
    TEXT_SLICE_BETWEEN,
    TEXT_SLICE_SPLIT,
    TEXT_SLICE_HEAD,
    TEXT_SLICE_TAIL,
    TEXT_SLICE_CHARS,
    TEXT_SLICE_REPLACE,
    TEXT_SLICE_REMOVE,
)
#: field-binding/v4 가 적을 수 있던 방식 — 그 판의 framing 은 동결이다(이 둘, 빠짐은 빈 값만).
TEXT_SLICE_V4_MODES = (TEXT_SLICE_CHARS, TEXT_SLICE_SPLIT)

#: 빠짐 처리 — 빈 값(키 없음과 같다) / 원본 그대로.
ON_MISSING_EMPTY = "empty"
ON_MISSING_KEEP = "keep"
ON_MISSING_POLICIES = (ON_MISSING_EMPTY, ON_MISSING_KEEP)
#: 빠짐이 있는 방식 — 나머지(앞에서·뒤에서 N글자, 바꾸기·지우기)는 언제나 값을 낸다.
MISSABLE_MODES = frozenset(
    {TEXT_SLICE_BEFORE, TEXT_SLICE_AFTER, TEXT_SLICE_BETWEEN, TEXT_SLICE_SPLIT, TEXT_SLICE_CHARS}
)

#: 방식별 직렬화 키(``mode``·``on_missing`` 제외), 정본 순서. 모르는 키는 거절한다.
SLICE_KEYS_BY_MODE: dict[str, tuple[str, ...]] = {
    TEXT_SLICE_BEFORE: ("delimiter",),
    TEXT_SLICE_AFTER: ("delimiter",),
    TEXT_SLICE_BETWEEN: ("open", "close"),
    TEXT_SLICE_SPLIT: ("delimiter", "index"),
    TEXT_SLICE_HEAD: ("count",),
    TEXT_SLICE_TAIL: ("count",),
    TEXT_SLICE_CHARS: ("start", "length"),
    TEXT_SLICE_REPLACE: ("find", "replace"),
    TEXT_SLICE_REMOVE: ("find",),
}
#: 비워 둘 수 있는 키(없으면 끝까지).
_OPTIONAL_KEYS = frozenset({"length"})
_ALL_KEYS = frozenset(key for keys in SLICE_KEYS_BY_MODE.values() for key in keys)
#: 글자 수 칸(앞에서·뒤에서 N글자, 글자 범위의 글자 수)이 같은 말로 거절한다.
_MIN_COUNT_MESSAGE = "글자 수는 1 이상이어야 합니다"


class TextSliceError(ValueError):
    """가공 명세가 이 계약이 아는 모양이 아니다 — 원문으로 조용히 풀지 않는다.

    메시지는 편집 동사가 사용자에게 그대로 세운다(사용자가 고칠 수 있는 자리의 문장만 문장형).
    """

    code = "UNSUPPORTED_TEXT_SLICE"


def _require_int(value: object, what: str) -> int:
    # bool 은 int 의 하위형이라 True 가 1 로 조용히 통과한다 — 명시로 막는다.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TextSliceError(f"가공 {what} 값이 정수가 아님: {value!r}")
    return value


def _require_text(value: object, what: str, empty_message: str) -> str:
    if value is not None and not isinstance(value, str):
        raise TextSliceError(f"가공 {what} 값이 문자열이 아님: {value!r}")
    if not value:
        raise TextSliceError(empty_message)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:  # lone surrogate — canonical framing 불가
        raise TextSliceError(f"가공 {what}에 유효하지 않은 Unicode scalar") from exc
    return value


def _tight(text: str, begin: int, end: int) -> tuple[int, int]:
    """``[begin, end)`` 의 앞뒤 공백을 걷은 자리 — ``str.strip`` 과 같은 공백 정의."""
    while begin < end and text[begin].isspace():
        begin += 1
    while end > begin and text[end - 1].isspace():
        end -= 1
    return begin, end


@dataclass(frozen=True)
class SliceOutcome:
    """한 값에 명세를 건 결과 — 낸 글자, 원본에서 고른 자리, 빠졌는가.

    ``span`` 은 원본(코드 포인트 좌표)에서 **남긴** 범위다. 바꾸기·지우기(자리가 아니라 글자를
    고친다)와 빠짐은 ``None`` 이다. 편집 표면의 미리보기가 이 사실을 그대로 쓴다.
    """

    text: str
    span: tuple[int, int] | None
    missed: bool


@dataclass(frozen=True)
class TextSlice:
    """가공 명세 한 벌 — 방식별로 쓰는 칸만 차고 나머지는 ``None`` 이다(모양 불변식)."""

    mode: str
    start: int | None = None
    length: int | None = None
    delimiter: str | None = None
    index: int | None = None
    open: str | None = None
    close: str | None = None
    count: int | None = None
    find: str | None = None
    replace: str | None = None
    on_missing: str = ON_MISSING_EMPTY

    def __post_init__(self) -> None:
        keys = SLICE_KEYS_BY_MODE.get(self.mode) if isinstance(self.mode, str) else None
        if keys is None:
            raise TextSliceError(f"알 수 없는 가공 방식: {self.mode!r} (지원: {TEXT_SLICE_MODES})")
        mixed = sorted(key for key in _ALL_KEYS - set(keys) if getattr(self, key) is not None)
        if mixed:
            raise TextSliceError(f"{self.mode} 가공에 다른 방식의 칸이 섞였음: {mixed}")
        if self.on_missing not in ON_MISSING_POLICIES:
            raise TextSliceError(f"알 수 없는 빠짐 처리: {self.on_missing!r}")
        if self.on_missing != ON_MISSING_EMPTY and self.mode not in MISSABLE_MODES:
            raise TextSliceError(f"{self.mode} 가공에는 빠짐 처리가 없음")
        mode = self.mode
        if mode in (TEXT_SLICE_BEFORE, TEXT_SLICE_AFTER, TEXT_SLICE_SPLIT):
            _require_text(self.delimiter, "구분자", "구분자를 비울 수 없습니다")
        if mode == TEXT_SLICE_SPLIT:
            # 번째가 빠진 명세는 0 과 같은 자리다(몇 번째인지 말하지 않았다) — 한 문장으로 거절한다.
            if (0 if self.index is None else _require_int(self.index, "번째")) == 0:
                raise TextSliceError("번째는 0이 될 수 없습니다")
        elif mode == TEXT_SLICE_BETWEEN:
            _require_text(self.open, "여는 기준 글자", "가공 기준 글자가 비었음")
            _require_text(self.close, "닫는 기준 글자", "가공 기준 글자가 비었음")
        elif mode in (TEXT_SLICE_HEAD, TEXT_SLICE_TAIL):
            if self.count is None or _require_int(self.count, "글자 수") < 1:
                raise TextSliceError(_MIN_COUNT_MESSAGE)
        elif mode == TEXT_SLICE_CHARS:
            if self.start is None or _require_int(self.start, "시작") < 1:
                raise TextSliceError("시작은 1 이상이어야 합니다")
            if self.length is not None and _require_int(self.length, "글자 수") < 1:
                raise TextSliceError(_MIN_COUNT_MESSAGE)
        elif mode in (TEXT_SLICE_REPLACE, TEXT_SLICE_REMOVE):
            _require_text(self.find, "찾을 글자", "찾을 글자가 비었음")
            if mode == TEXT_SLICE_REPLACE:
                # 빈 「바꿀 글자」는 곧 지우기다 — 같은 뜻이 두 모양을 갖지 않게 거절한다.
                _require_text(self.replace, "바꿀 글자", "바꿀 글자가 비었음")

    # ── 성질 ────────────────────────────────────────────────────────────────────
    @property
    def missable(self) -> bool:
        """빠짐이 있는 방식인가(``on_missing`` 이 뜻을 갖는가)."""
        return self.mode in MISSABLE_MODES

    @property
    def is_v4_expressible(self) -> bool:
        """field-binding/v4 framing 이 적을 수 있는 명세인가 — 두 방식, 빠짐은 빈 값."""
        return self.mode in TEXT_SLICE_V4_MODES and self.on_missing == ON_MISSING_EMPTY

    # ── 적용 ────────────────────────────────────────────────────────────────────
    def locate(self, text: str) -> tuple[int, int] | None:
        """고르는 방식의 자리 ``[s, e)`` — 빠지면 ``None``. 바꾸기·지우기는 자리가 없다(``None``)."""
        mode = self.mode
        if mode in (TEXT_SLICE_BEFORE, TEXT_SLICE_AFTER):
            assert self.delimiter is not None
            at = text.find(self.delimiter)
            if at < 0:
                return None
            if mode == TEXT_SLICE_BEFORE:
                return _tight(text, 0, at)
            return _tight(text, at + len(self.delimiter), len(text))
        if mode == TEXT_SLICE_BETWEEN:
            assert self.open is not None and self.close is not None
            at = text.find(self.open)
            if at < 0:
                return None
            begin = at + len(self.open)
            end = text.find(self.close, begin)
            if end < 0:
                return None
            return _tight(text, begin, end)
        if mode == TEXT_SLICE_SPLIT:
            assert self.delimiter is not None and self.index is not None
            pieces: list[tuple[int, int]] = []
            cursor = 0
            while True:
                at = text.find(self.delimiter, cursor)
                if at < 0:
                    pieces.append((cursor, len(text)))
                    break
                pieces.append((cursor, at))
                cursor = at + len(self.delimiter)
            position = self.index - 1 if self.index > 0 else len(pieces) + self.index
            if not 0 <= position < len(pieces):
                return None
            return _tight(text, *pieces[position])
        if mode == TEXT_SLICE_HEAD:
            assert self.count is not None
            return 0, min(self.count, len(text))
        if mode == TEXT_SLICE_TAIL:
            assert self.count is not None
            return max(0, len(text) - self.count), len(text)
        if mode == TEXT_SLICE_CHARS:
            assert self.start is not None
            begin = self.start - 1
            if begin >= len(text):
                return None
            end = len(text) if self.length is None else min(len(text), begin + self.length)
            return begin, end
        return None

    def evaluate(self, text: str) -> SliceOutcome:
        """``text`` 에 이 명세를 건 결과 — 글자·고른 자리·빠짐(렌더와 미리보기의 같은 출처)."""
        if self.mode == TEXT_SLICE_REPLACE:
            assert self.find is not None and self.replace is not None
            return SliceOutcome(text.replace(self.find, self.replace).strip(), None, False)
        if self.mode == TEXT_SLICE_REMOVE:
            assert self.find is not None
            return SliceOutcome(text.replace(self.find, "").strip(), None, False)
        span = self.locate(text)
        if span is None:
            return SliceOutcome(text if self.on_missing == ON_MISSING_KEEP else "", None, True)
        return SliceOutcome(text[span[0]:span[1]], span, False)

    def apply(self, text: str) -> str:
        """``text`` 에서 이 명세가 가리키는 글자. 빠지면 ``on_missing`` 이 정한다(오류 아님)."""
        return self.evaluate(text).text

    # ── 직렬화 ──────────────────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        """저장·브리지 표현 — 쓰지 않는 칸은 적지 않는다(같은 뜻이 두 모양을 갖지 않게).

        ``on_missing`` 은 원본 그대로(``keep``)일 때만 적는다: 키 없음이 빈 값이라 v4 모양의 명세는
        byte 그대로 남는다.
        """
        out: dict[str, Any] = {"mode": self.mode}
        for key in SLICE_KEYS_BY_MODE[self.mode]:
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        if self.on_missing != ON_MISSING_EMPTY:
            out["on_missing"] = self.on_missing
        return out

    @classmethod
    def from_dict(cls, data: object) -> "TextSlice":
        """저장·브리지 표현 → 명세. 모르는 방식·모르는 키·틀린 타입은 시끄럽게 거절한다.

        봉인된 실행 계획은 사전을 얼려(읽기 전용 Mapping) 들고 오므로 ``dict`` 가 아니라
        :class:`~collections.abc.Mapping` 을 받는다. ``on_missing`` 은 빠짐이 있는 방식에만 설 수
        있고, 없으면 빈 값이다.
        """
        if not isinstance(data, Mapping):
            raise TextSliceError(f"가공 명세가 사전이 아님: {type(data).__name__}")
        mode = data.get("mode")
        keys = SLICE_KEYS_BY_MODE.get(mode) if isinstance(mode, str) else None
        if keys is None or not isinstance(mode, str):
            raise TextSliceError(f"알 수 없는 가공 방식: {mode!r} (지원: {TEXT_SLICE_MODES})")
        allowed = set(keys) | {"mode"}
        if mode in MISSABLE_MODES:
            allowed.add("on_missing")
        unknown = set(data) - allowed
        if unknown:
            raise TextSliceError(f"가공 명세에 모르는 키: {sorted(unknown)}")
        on_missing = data.get("on_missing", ON_MISSING_EMPTY)
        if not isinstance(on_missing, str):
            raise TextSliceError(f"알 수 없는 빠짐 처리: {on_missing!r}")
        fields = {key: data.get(key) for key in keys}
        return cls(mode=mode, on_missing=on_missing, **fields)


def text_slice_from_payload(data: object) -> TextSlice | None:
    """``None`` 또는 직렬화 사전 → 명세. 이미 :class:`TextSlice` 면 그대로(재검증은 생성자가 했다)."""
    if data is None or isinstance(data, TextSlice):
        return data
    return TextSlice.from_dict(data)


def apply_text_slice(spec: TextSlice | None, text: str) -> str:
    """가공이 없으면 ``text`` 그대로, 있으면 그 결과 — 모든 생성 경로의 단일 출처."""
    return text if spec is None else spec.apply(text)


__all__ = [
    "MISSABLE_MODES",
    "ON_MISSING_EMPTY",
    "ON_MISSING_KEEP",
    "ON_MISSING_POLICIES",
    "SLICE_KEYS_BY_MODE",
    "SliceOutcome",
    "TEXT_SLICE_AFTER",
    "TEXT_SLICE_BEFORE",
    "TEXT_SLICE_BETWEEN",
    "TEXT_SLICE_CHARS",
    "TEXT_SLICE_HEAD",
    "TEXT_SLICE_MODES",
    "TEXT_SLICE_REMOVE",
    "TEXT_SLICE_REPLACE",
    "TEXT_SLICE_SPLIT",
    "TEXT_SLICE_TAIL",
    "TEXT_SLICE_V4_MODES",
    "TextSlice",
    "TextSliceError",
    "apply_text_slice",
    "text_slice_from_payload",
]
