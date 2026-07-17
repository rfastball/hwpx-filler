"""표시형 서식 엔진 + 어댑터 층 — 값(문자열) → 표시 문자열.

**교체 가능한 이음새.** 나머지 코드(`mapping`·위저드)는 이 층의 :func:`render`/:func:`presets`
만 부르고, 실제 서식 해석기는 :data:`ENGINE` 한 곳에서 갈아끼운다. 지금은 stdlib
(금액=``str.format`` 스펙, 날짜=``strftime``); 후일 babel(CLDR/엑셀 패턴) 등으로 바꾸려면
이 모듈의 ``ENGINE`` 만 교체하면 된다 — 호출부는 무변경.

원칙(Excel 셀서식의 열화판):
  - 표시형은 값을 **파싱→서식→실패 시 원본(degrade)**. 타입 *주장*이 아니라 관대한 *시도*.
  - 서식 코드는 유형(kind)이 해석기를 고른다: amount→``str.format`` 스펙, date→strftime.
  - 자주 쓰는 코드는 **프리셋**(분류해 클릭), 고급 사용자는 **코드 직접 입력**. 빈 코드("")는
    각 kind 의 기본 표시(원 붙임 / 공문서 표준 날짜 ``2026. 7. 17.``).
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


def _parse_time(value: str) -> "tuple[int, int] | None":
    """날짜 없는 **시각 단독값**을 관대하게 파싱('1400'→(14,0), '18:00'→(18,0)).

    소스가 시각만 담은 키(나라장터 ``opengTm`` 등)를 date 유형·시각 서식으로 렌더할 때
    쓴다. ``HH:MM``·``HHMM`` 만 인식하고 범위를 벗어나면 None(원본 degrade)."""
    s = value.strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s) or re.fullmatch(r"(\d{2})(\d{2})", s)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if 0 <= hh < 24 and 0 <= mm < 60:
        return hh, mm
    return None


def _korean_dt(value: str) -> str:
    """한글 날짜 표시(예약코드 ``kor``) — ``2026년 6월 15일 [09:00]``(월/일 비패딩)."""
    dt = _parse_dt(value)
    if dt is None:
        return value
    out = f"{dt.year}년 {dt.month}월 {dt.day}일"
    t = re.search(r"\d{1,2}:\d{2}", value)
    if t:
        out += f" {t.group(0)}"
    return out


def _dot_dt(value: str, *, short: bool = False) -> str:
    """공문서 표준 날짜 표시 — ``2026. 7. 17. [09:00]``(월/일 비패딩·끝점·점 뒤 공백).

    ``short=True`` → ``'26.7.17.``(2자리 연도·공백 없는 축약형). 둘 다 strftime 으로는
    이식 가능하게 못 내므로(``%-d``=glibc·``%#d``=Windows 전용) f-string 으로 수동 조립.
    """
    dt = _parse_dt(value)
    if dt is None:
        return value
    if short:
        out = f"'{dt.year % 100:02d}.{dt.month}.{dt.day}."
    else:
        out = f"{dt.year}. {dt.month}. {dt.day}."
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
        "date": [
            ("표준", ""),                      # 2026. 7. 17. (공문서 표준·기본)
            ("표준(약식)", "y2"),               # '26.7.17. (2자리 연도 축약·추천 2순위)
            ("한글", "kor"),                    # 2026년 6월 15일
            ("ISO", "%Y-%m-%d"),               # 2026-06-15
            ("점", "%Y.%m.%d"),                # 2026.06.15
            ("연-월", "%Y-%m"),                # 2026-06
            ("시각", "%H:%M"),                 # 18:00 (시각 단독값도 파싱)
            ("날짜+시각", "%Y-%m-%d %H:%M"),    # 2026-06-15 18:00
            ("한글일시", "%Y년 %m월 %d일 %H:%M"),  # 2026년 06월 15일 18:00
        ],
        "text": [                       # 평문(그대로) 유형의 표시형 = 마스크
            ("원문", ""),               # 값 그대로
            ("전화", "phone"),          # 010-1234-5678
            ("사업자번호", "biz"),       # 123-45-67890
        ],
    }

    def render(self, kind: str, code: str, value: str) -> str:
        if kind == "amount":
            return self._amount(code, value)
        if kind == "date":
            return self._date(code, value)
        if kind == "text":
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

    def _date(self, code: str, value: str) -> str:
        if not code:
            return _dot_dt(value)  # 공문서 표준 기본(2026. 7. 17.)
        if code == "y2":
            return _dot_dt(value, short=True)  # 예약코드: 축약형('26.7.17.)
        if code == "kor":
            return _korean_dt(value)  # 예약코드: 한글 표기(비패딩)
        dt = _parse_dt(value)
        if dt is None:
            # 날짜가 없으면 시각 단독값('1400'·'18:00')으로 재시도 — 시각 서식용.
            t = _parse_time(value)
            if t is None:
                return value
            dt = datetime(1900, 1, 1, t[0], t[1])
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
