"""텍스트 가공 — 데이터 칸의 글자 중 **일부만** 취한다(기초 가공, field-binding/v4).

실데이터가 드러낸 요구다: 계약 목록의 ``입찰공고번호`` 는 ``R26BK09017075-000`` 인데 문서에는
``R26BK09017075`` 가 들어가야 하고, ``조달요구번호`` 는 ``MPKPLA26910290, MPKPLA26910291``
처럼 쉼표로 여럿이 붙어 온다. 열을 새로 만들 수 없는 사용자에게 필요한 것은 「이 칸의 어느
부분」을 고르는 한 단계다.

**직관성이 표현력보다 앞선다**(저작 UX 채점 축은 직관성·진입장벽이다). 그래서 방식은 둘뿐이다:

- ``chars`` — 글자 범위: ``start`` 번째 글자부터(1부터 센다) ``length`` 글자. ``length`` 가
  없으면 끝까지. 범위를 벗어나면 빈 문자열이다(렌더 시점 오류가 아니다 — 미리보기가 보여 준다).
- ``split`` — 구분자로 나누기: ``delimiter`` 로 나눈 조각(각 조각은 앞뒤 공백을 걷는다) 중
  ``index`` 번째(1부터 센다; 음수는 끝에서, ``-1`` = 마지막). 범위 밖이면 빈 문자열이다.
  구분자는 **글자 그대로**다(정규식이 아니다).

가공은 원본 칸 텍스트(공백 정책 적용 뒤)에 걸리고 **표시형보다 먼저** 온다:
``170,309,180원 (VAT 포함)`` 을 ``원`` 으로 나눈 첫 조각 ``170,309,180`` 에 금액 표시형이
걸려 ``170,309,180원`` 이 된다. 고정값·오늘 날짜에는 걸리지 않는다(원본 칸이 없다).

명세의 모양은 여기 한 곳이 판정한다 — 편집 시점(링1 편집 동사)과 규칙 구성 시점(바인딩 규칙·
실행 계획 해독)이 같은 판정기를 부르므로 잘못된 명세는 어느 쪽에서도 조용히 고쳐지지 않고
시끄럽게 거절된다. 이 모듈은 순수하다(Domain).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TEXT_SLICE_CHARS = "chars"
TEXT_SLICE_SPLIT = "split"
TEXT_SLICE_MODES = (TEXT_SLICE_CHARS, TEXT_SLICE_SPLIT)

#: 방식별 직렬화 키(``mode`` 제외). 모르는 키는 조용히 버리지 않고 거절한다.
_KEYS_BY_MODE = {
    TEXT_SLICE_CHARS: frozenset({"start", "length"}),
    TEXT_SLICE_SPLIT: frozenset({"delimiter", "index"}),
}


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


@dataclass(frozen=True)
class TextSlice:
    """가공 명세 한 벌 — 방식별로 쓰는 칸만 차고 나머지는 ``None`` 이다(모양 불변식)."""

    mode: str
    start: int | None = None
    length: int | None = None
    delimiter: str | None = None
    index: int | None = None

    def __post_init__(self) -> None:
        if self.mode == TEXT_SLICE_CHARS:
            if self.delimiter is not None or self.index is not None:
                raise TextSliceError("글자 범위 가공에 구분자 칸이 섞였음")
            if self.start is None or _require_int(self.start, "시작") < 1:
                raise TextSliceError("시작은 1 이상이어야 합니다")
            if self.length is not None and _require_int(self.length, "글자 수") < 1:
                raise TextSliceError("글자 수는 1 이상이어야 합니다")
            return
        if self.mode == TEXT_SLICE_SPLIT:
            if self.start is not None or self.length is not None:
                raise TextSliceError("구분자 가공에 글자 범위 칸이 섞였음")
            if self.delimiter is not None and not isinstance(self.delimiter, str):
                raise TextSliceError(f"가공 구분자 값이 문자열이 아님: {self.delimiter!r}")
            if not self.delimiter:
                raise TextSliceError("구분자를 비울 수 없습니다")
            try:
                self.delimiter.encode("utf-8")
            except UnicodeEncodeError as exc:  # lone surrogate — canonical framing 불가
                raise TextSliceError("가공 구분자에 유효하지 않은 Unicode scalar") from exc
            # 번째가 빠진 명세는 0 과 같은 자리다(몇 번째인지 말하지 않았다) — 한 문장으로 거절한다.
            if (0 if self.index is None else _require_int(self.index, "번째")) == 0:
                raise TextSliceError("번째는 0이 될 수 없습니다")
            return
        raise TextSliceError(f"알 수 없는 가공 방식: {self.mode!r} (지원: {TEXT_SLICE_MODES})")

    # ── 적용 ────────────────────────────────────────────────────────────────────
    def apply(self, text: str) -> str:
        """``text`` 에서 이 명세가 가리키는 부분을 낸다. 범위 밖은 빈 문자열(오류 아님)."""
        if self.mode == TEXT_SLICE_CHARS:
            assert self.start is not None  # __post_init__ 이 강제
            begin = self.start - 1
            end = None if self.length is None else begin + self.length
            return text[begin:end]
        assert self.delimiter is not None and self.index is not None
        pieces = [piece.strip() for piece in text.split(self.delimiter)]
        position = self.index - 1 if self.index > 0 else len(pieces) + self.index
        if 0 <= position < len(pieces):
            return pieces[position]
        return ""

    # ── 직렬화 ──────────────────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        """저장·브리지 표현 — 쓰지 않는 칸은 적지 않는다(같은 뜻이 두 모양을 갖지 않게)."""
        if self.mode == TEXT_SLICE_CHARS:
            out: dict[str, Any] = {"mode": self.mode, "start": self.start}
            if self.length is not None:
                out["length"] = self.length
            return out
        return {"mode": self.mode, "delimiter": self.delimiter, "index": self.index}

    @classmethod
    def from_dict(cls, data: object) -> "TextSlice":
        """저장·브리지 표현 → 명세. 모르는 방식·모르는 키·틀린 타입은 시끄럽게 거절한다.

        봉인된 실행 계획은 사전을 얼려(읽기 전용 Mapping) 들고 오므로 ``dict`` 가 아니라
        :class:`~collections.abc.Mapping` 을 받는다.
        """
        if not isinstance(data, Mapping):
            raise TextSliceError(f"가공 명세가 사전이 아님: {type(data).__name__}")
        mode = data.get("mode")
        allowed = _KEYS_BY_MODE.get(mode) if isinstance(mode, str) else None
        if allowed is None or not isinstance(mode, str):
            raise TextSliceError(f"알 수 없는 가공 방식: {mode!r} (지원: {TEXT_SLICE_MODES})")
        unknown = set(data) - allowed - {"mode"}
        if unknown:
            raise TextSliceError(f"가공 명세에 모르는 키: {sorted(unknown)}")
        return cls(
            mode=mode,
            start=data.get("start"),
            length=data.get("length"),
            delimiter=data.get("delimiter"),
            index=data.get("index"),
        )


def text_slice_from_payload(data: object) -> TextSlice | None:
    """``None`` 또는 직렬화 사전 → 명세. 이미 :class:`TextSlice` 면 그대로(재검증은 생성자가 했다)."""
    if data is None or isinstance(data, TextSlice):
        return data
    return TextSlice.from_dict(data)


def apply_text_slice(spec: TextSlice | None, text: str) -> str:
    """가공이 없으면 ``text`` 그대로, 있으면 그 부분 — 모든 생성 경로의 단일 출처."""
    return text if spec is None else spec.apply(text)


__all__ = [
    "TEXT_SLICE_CHARS",
    "TEXT_SLICE_MODES",
    "TEXT_SLICE_SPLIT",
    "TextSlice",
    "TextSliceError",
    "apply_text_slice",
    "text_slice_from_payload",
]
