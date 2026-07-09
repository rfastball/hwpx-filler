"""표시형 서식 엔진 + 어댑터 층 — 값(문자열) → 표시 문자열.

**교체 가능한 이음새.** 나머지 코드(`mapping`·위저드)는 이 층의 :func:`render`/:func:`presets`
만 부르고, 실제 서식 해석기는 :data:`ENGINE` 한 곳에서 갈아끼운다. 지금은 stdlib
(금액=``str.format`` 스펙, 날짜=``strftime``); 후일 babel(CLDR/엑셀 패턴) 등으로 바꾸려면
이 모듈의 ``ENGINE`` 만 교체하면 된다 — 호출부는 무변경.

원칙(Excel 셀서식의 열화판):
  - 표시형은 값을 **파싱→서식→실패 시 원본(degrade)**. 타입 *주장*이 아니라 관대한 *시도*.
  - 서식 코드는 변환(kind)이 해석기를 고른다: amount→``str.format`` 스펙, datetime→strftime.
  - 자주 쓰는 코드는 **프리셋**(분류해 클릭), 고급 사용자는 **코드 직접 입력**. 빈 코드("")는
    각 kind 의 기본 표시(원 붙임 / 한글 날짜).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Protocol


class FormatEngine(Protocol):
    """표시형 서식 해석기. babel 등으로 교체하려면 이 프로토콜을 구현해 ``ENGINE`` 에 꽂는다."""

    def render(self, kind: str, code: str, value: str) -> str:
        """``kind`` 해석기로 ``code`` 를 ``value`` 에 적용. 실패 시 ``value`` 그대로(degrade)."""
        ...

    def presets(self, kind: str) -> "list[tuple[str, str]]":
        """이 ``kind`` 의 프리셋 목록 ``[(라벨, 코드)]``. 표시형이 없는 kind 는 빈 목록."""
        ...


# ------------------------------------------------------------------ 파싱 헬퍼
def _parse_number(value: str) -> "int | float | None":
    """문자열에서 수를 관대하게 추출('150,000,000원'→150000000). 실패 시 None."""
    s = re.sub(r"[^\d.\-]", "", value)
    if not s or s.strip("-.") == "":
        return None
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None


def _parse_dt(value: str) -> "datetime | None":
    """문자열에서 날짜(+선택 시각)를 관대하게 파싱. 실패 시 None."""
    m = re.search(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})", value)
    if not m:
        return None
    y, mo, d = (int(g) for g in m.groups())
    hh = mm = 0
    t = re.search(r"(\d{1,2}):(\d{2})", value)
    if t:
        hh, mm = int(t.group(1)), int(t.group(2))
    try:
        return datetime(y, mo, d, hh, mm)
    except ValueError:
        return None


def _korean_dt(value: str) -> str:
    """기본 날짜 표시(코드 없음) — ``2026년 6월 15일 [09:00]``(월/일 비패딩)."""
    dt = _parse_dt(value)
    if dt is None:
        return value
    out = f"{dt.year}년 {dt.month}월 {dt.day}일"
    t = re.search(r"\d{1,2}:\d{2}", value)
    if t:
        out += f" {t.group(0)}"
    return out


# ---- 마스크(자릿수 그룹) — stdlib 서식 스펙으로 안 되는 전화/사업자번호 등 ----
def _mask_phone(value: str) -> str:
    """전화번호 자릿수 마스크. 자릿수가 안 맞으면 원본(degrade)."""
    d = re.sub(r"\D", "", value)
    n = len(d)
    if n == 11:
        return f"{d[:3]}-{d[3:7]}-{d[7:]}"      # 010-1234-5678
    if n == 10:
        if d.startswith("02"):
            return f"{d[:2]}-{d[2:6]}-{d[6:]}"   # 02-1234-5678
        return f"{d[:3]}-{d[3:6]}-{d[6:]}"       # 031-123-4567
    if n == 9 and d.startswith("02"):
        return f"{d[:2]}-{d[2:5]}-{d[5:]}"       # 02-123-4567
    return value


def _mask_biz(value: str) -> str:
    """사업자등록번호 10자리 → ``123-45-67890``. 아니면 원본(degrade)."""
    d = re.sub(r"\D", "", value)
    if len(d) == 10:
        return f"{d[:3]}-{d[3:5]}-{d[5:]}"
    return value


_MASKS = {"phone": _mask_phone, "biz": _mask_biz}


class StdlibFormatEngine:
    """stdlib 서식 엔진 — 금액=``str.format`` 스펙, 날짜=``strftime``. 의존성 0."""

    # 자주 쓰는 코드(분류 클릭용). 빈 코드("")=기본. 고급 사용자는 여기 밖의 코드도 직접 입력.
    _PRESETS: "dict[str, list[tuple[str, str]]]" = {
        "amount": [
            ("원", ""),                # 150,000,000원 (기본)
            ("숫자", "{:,}"),           # 150,000,000
            ("소수 2자리", "{:,.2f}"),   # 150,000,000.00
            ("백분율", "{:.1%}"),        # (0.05 → 5.0%)
        ],
        "datetime": [
            ("한글", ""),               # 2026년 6월 15일 (기본)
            ("ISO", "%Y-%m-%d"),        # 2026-06-15
            ("점", "%Y.%m.%d"),         # 2026.06.15
            ("연-월", "%Y-%m"),         # 2026-06
        ],
        "join": [                       # 평문(그대로) 변환의 표시형 = 마스크
            ("원문", ""),               # 값 그대로
            ("전화", "phone"),          # 010-1234-5678
            ("사업자번호", "biz"),       # 123-45-67890
        ],
    }

    def render(self, kind: str, code: str, value: str) -> str:
        if kind == "amount":
            return self._amount(code, value)
        if kind == "datetime":
            return self._datetime(code, value)
        if kind == "join":
            return self._text(code, value)
        return value  # 표시형 없는 kind(const)

    def presets(self, kind: str) -> "list[tuple[str, str]]":
        return list(self._PRESETS.get(kind, []))

    def _amount(self, code: str, value: str) -> str:
        num = _parse_number(value)
        if num is None:
            return value  # 수가 아니면 원본(degrade)
        try:
            return (code or "{:,}원").format(num)
        except (ValueError, KeyError, IndexError):
            return value  # 잘못된 서식 코드도 degrade

    def _datetime(self, code: str, value: str) -> str:
        if not code:
            return _korean_dt(value)  # 기본 한글 표시(비패딩)
        dt = _parse_dt(value)
        if dt is None:
            return value
        try:
            return dt.strftime(code)
        except (ValueError, TypeError):
            return value

    def _text(self, code: str, value: str) -> str:
        if not code:
            return value  # 원문 그대로
        fn = _MASKS.get(code)
        return fn(value) if fn else value  # 미지 마스크 코드 → 원본(degrade)


# ---------------------------------------------------- 어댑터 (교체 지점) --
# babel 등으로 바꾸려면 이 한 줄만 다른 FormatEngine 구현으로 교체한다.
ENGINE: FormatEngine = StdlibFormatEngine()


def render(kind: str, code: str, value: str) -> str:
    """활성 엔진으로 표시형 적용(어댑터). 표시형 없는 kind 는 값 그대로."""
    return ENGINE.render(kind, code, value)


def presets(kind: str) -> "list[tuple[str, str]]":
    """활성 엔진의 kind 별 프리셋 ``[(라벨, 코드)]``."""
    return ENGINE.presets(kind)
