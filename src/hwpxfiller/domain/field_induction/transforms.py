"""값 → 문서 글자 프로그램 11종과 제품 표시 형식(FieldMapping type/fmt) 대응.

``render(값) == 문서 구간`` 이 추론하는 관계다. 여기 적힌 프로그램만 있다 — 그 밖의 모양은 찾지 않는다.
실험 엔진 ``core/transforms.py`` 의 이식이며, 제품 값은 언제나 타입 없는 텍스트라 문자열 입력만 다룬다.

제품 대응(``binding``)은 :mod:`hwpxfiller.domain.format_engine` 이 **같은 글자**를 내는 경우에만 쓴다
(:func:`renderings` 가 렌더 결과를 제품 엔진으로 다시 대조한다). 날짜 전용 형식은 시각이 든 값에 쓰지 않는다.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Callable
from dataclasses import dataclass

from ..format_engine import presets as product_presets
from ..format_engine import render as product_render

_CANON_INT = re.compile(r"-?(0|[1-9]\d*)")
_CANON_DEC = re.compile(r"-?(0|[1-9]\d*)\.\d+")
# 원천 값은 2026/09/15·2026.09.15 로도 온다(데이터베이스 내보내기) — 한 값에 구분자는 한 종류다.
_DATE_ANY = re.compile(r"(\d{4})([-/.])(\d{2})\2(\d{2})")
_DATETIME_ANY = re.compile(r"(\d{4})([-/.])(\d{2})\2(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?")

def as_datetime(value: str) -> _dt.datetime | None:
    """날짜·시각 값 — ``YYYY-MM-DD HH:MM[:SS]``(구분자 ``-``·``/``·``.``)."""
    found = _DATETIME_ANY.fullmatch(value.strip())
    if found is None:
        return None
    try:
        return _dt.datetime(int(found[1]), int(found[3]), int(found[4]), int(found[5]), int(found[6]))
    except ValueError:
        return None


def as_date(value: str) -> _dt.date | None:
    """날짜 값 — 날짜만 든 값과 날짜·시각 값의 날짜 부분."""
    found = _DATE_ANY.fullmatch(value.strip())
    if found is not None:
        try:
            return _dt.date(int(found[1]), int(found[3]), int(found[4]))
        except ValueError:
            return None
    moment = as_datetime(value)
    return None if moment is None else moment.date()


def _number_text(value: str) -> str | None:
    """정규형 십진수 글자만 수다 — 앞자리 0 이 있는 식별자(``00123``)는 수가 아니다."""
    text = value.strip()
    return text if _CANON_INT.fullmatch(text) or _CANON_DEC.fullmatch(text) else None


def _identity(value: str) -> str | None:
    return value


def _grouping(value: str) -> str | None:
    text = _number_text(value)
    if text is None:
        return None
    sign = "-" if text.startswith("-") else ""
    whole, _, frac = text.lstrip("-").partition(".")
    return sign + f"{int(whole):,}" + (f".{frac}" if frac else "")


def _date(fmt: Callable[[_dt.date], str]) -> Callable[[str], str | None]:
    def render(value: str) -> str | None:
        # 날짜 전용 형식은 시각이 든 값에 쓰지 않는다 — 제품 날짜 표시는 시각을 붙인다(엔진 G절 주의).
        if as_datetime(value) is not None:
            return None
        day = as_date(value)
        return None if day is None else fmt(day)

    return render


def _datetime(fmt: Callable[[_dt.datetime], str]) -> Callable[[str], str | None]:
    def render(value: str) -> str | None:
        moment = as_datetime(value)
        return None if moment is None else fmt(moment)

    return render


@dataclass(frozen=True)
class Transform:
    id: str
    family: str  # identity | number | date | datetime
    complexity: float  # 설명 길이 사전 — 동률 정렬에만 쓴다
    kind: str  # 제품 FieldMapping.type
    fmt: str  # 제품 FieldMapping.fmt
    _render: Callable[[str], str | None]

    def render(self, value: str) -> str | None:
        return self._render(value)

    @property
    def label(self) -> str:
        """표시 형식의 사람이 읽는 이름(계약 「binding.label」) — 제품 프리셋 표에서 찾는다.

        원문(identity)은 화면이 형식 줄을 숨기도록 빈 문자열이다. 그 밖은 ``(kind, fmt)`` 가 가리키는
        프리셋 라벨이고, 프리셋 표에 없는 코드(예: ``%Y년 %m월 %d일``)는 코드 자체가 이름이다.
        """
        if self.family == "identity":
            return ""
        for label, code in product_presets(self.kind):
            if code == self.fmt:
                return label
        return self.fmt

    def binding(self) -> dict:
        """제품 연결 초안의 표시 형식 — ``{"type", "fmt", "label"}``."""
        return {"type": self.kind, "fmt": self.fmt, "label": self.label}


TRANSFORMS: dict[str, Transform] = {
    t.id: t
    for t in [
        Transform("identity", "identity", 0.0, "text", "", _identity),
        Transform("number_grouping", "number", 1.0, "amount", "{:,}", _grouping),
        Transform("date_iso", "date", 1.0, "date", "%Y-%m-%d", _date(lambda d: d.isoformat())),
        Transform("date_dot", "date", 1.0, "date", "%Y.%m.%d",
                  _date(lambda d: f"{d.year:04d}.{d.month:02d}.{d.day:02d}")),
        Transform("date_dot_spaced", "date", 1.2, "date", "",
                  _date(lambda d: f"{d.year}. {d.month}. {d.day}.")),
        Transform("date_korean", "date", 1.2, "date", "kor",
                  _date(lambda d: f"{d.year}년 {d.month}월 {d.day}일")),
        Transform("date_korean_padded", "date", 1.3, "date", "%Y년 %m월 %d일",
                  _date(lambda d: f"{d.year}년 {d.month:02d}월 {d.day:02d}일")),
        Transform("date_slash", "date", 1.0, "date", "%Y/%m/%d",
                  _date(lambda d: f"{d.year:04d}/{d.month:02d}/{d.day:02d}")),
        Transform("datetime_iso", "datetime", 1.0, "date", "%Y-%m-%d %H:%M",
                  _datetime(lambda d: f"{d:%Y-%m-%d %H:%M}")),
        Transform("datetime_dot_spaced", "datetime", 1.3, "date", "",
                  _datetime(lambda d: f"{d.year}. {d.month}. {d.day}. {d:%H:%M}")),
        Transform("datetime_korean", "datetime", 1.3, "date", "kor",
                  _datetime(lambda d: f"{d.year}년 {d.month}월 {d.day}일 {d:%H:%M}")),
    ]
}


def domain_equivalent(a: str, b: str, value: str) -> bool:
    """두 프로그램이 이 값의 모든 같은 모양 값에서 같은 글자를 내는가.

    원문과 날짜 형식은 그 형식 그대로 적힌 날짜 글자에서 늘 같다 — 관찰로 가를 수 없으니 한 프로그램이다.
    원문과 숫자(천 단위 쉼표) 형식은 ``500`` 에서 같아도 1000 에서 갈린다 — 같은 프로그램이 아니다.
    """
    if "identity" not in {a, b}:
        return False
    other = TRANSFORMS[b if a == "identity" else a]
    return other.family in ("date", "datetime") and other.render(value) == value


def renderings(value: str) -> list[tuple[Transform, str]]:
    """이 값에 쓸 수 있는 프로그램과 그 글자 — 단순한 것부터, 같은 프로그램은 하나로 접는다.

    제품 표시 엔진이 같은 글자를 내지 않는 프로그램은 뺀다(결과 시험이 문서와 같은 글자를 내야 한다).
    """
    out: list[tuple[Transform, str]] = []
    for transform in sorted(TRANSFORMS.values(), key=lambda item: item.complexity):
        rendered = transform.render(value)
        if not rendered or not rendered.strip():
            continue
        if any(domain_equivalent(kept.id, transform.id, value) for kept, _ in out):
            continue
        if product_render(transform.kind, transform.fmt, value) != rendered:
            continue
        out.append((transform, rendered))
    return out
