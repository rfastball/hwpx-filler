"""출력 파일명 생성 — VBA ``Make_Output_FileName`` / ``CleanFileName`` 포트.

패턴 문자열의 ``{{키}}`` 를 레코드 값으로 치환하고 파일시스템 금지문자를 정리한다.
추가로 두 종류의 **예약 토큰**을 지원한다(한글 필드명과 불충돌):

- ``{{date}}`` / ``{{date:YYYY-MM-DD}}`` — 생성 시각 서식. 기본 ``YYYYMMDD``.
- ``{{seq}}`` / ``{{seq:001}}`` — 배치당 1-based 일련번호. pad 리터럴 길이가 폭.

배치 전체의 상태(한 번 캡처한 시각·증가하는 연번·같은 이름 충돌 회피)는 :class:`OutputNamer`
가 담는다 — 순수 함수 :func:`make_output_filename` 에는 상태를 두지 않는다.
"""

from __future__ import annotations

import re
from datetime import datetime

_INVALID = re.compile(r'[\\/:*?"<>|\r\n\t]')
_DATE_TOKEN = re.compile(r"\{\{date(?::([^}]*))?\}\}")
_SEQ_TOKEN = re.compile(r"\{\{seq(?::([^}]*))?\}\}")

# 사용자 서식 토큰 → strftime 지시자. 순서·대소문자가 하중이다(월 ``MM`` vs 분 ``mm``).
_DATE_MAP = [
    ("YYYY", "%Y"),
    ("YY", "%y"),
    ("MM", "%m"),
    ("DD", "%d"),
    ("HH", "%H"),
    ("mm", "%M"),
    ("SS", "%S"),
]


def clean_filename(name: str) -> str:
    return _INVALID.sub("_", name)


def _fmt_date(spec: "str | None", now: datetime) -> str:
    fmt = spec or "YYYYMMDD"
    for tok, strf in _DATE_MAP:
        fmt = fmt.replace(tok, strf)
    return clean_filename(now.strftime(fmt))


def _fmt_seq(spec: "str | None", seq: int) -> str:
    width = len(spec) if spec else 0  # ``{{seq:001}}`` → 폭 3
    return f"{seq:0{width}d}" if width else str(seq)


def make_output_filename(
    pattern: str,
    data: "dict[str, object]",
    *,
    seq: "int | None" = None,
    now: "datetime | None" = None,
) -> str:
    """``pattern`` 의 토큰을 치환. 확장자 ``.hwpx`` 를 보장한다.

    ``{{date}}``·``{{seq}}`` 예약 토큰을 데이터-키 치환 **前에** 해석한다. ``seq``/``now``
    를 주입하면 결정적(테스트용). 특수 토큰이 없는 패턴은 이전과 동일하게 동작한다.
    """
    now = now or datetime.now()
    out = _DATE_TOKEN.sub(lambda m: _fmt_date(m.group(1), now), pattern)
    out = _SEQ_TOKEN.sub(lambda m: _fmt_seq(m.group(1), seq if seq is not None else 1), out)
    # 데이터 필드 토큰 — 평문 치환(표시형은 여기서 안 함; 값은 이미 프로파일이 서식했음).
    for key, val in data.items():
        token = "{{" + str(key) + "}}"
        if token in out:
            out = out.replace(token, clean_filename(str(val)))
    if not out.lower().endswith(".hwpx"):
        out += ".hwpx"
    return out


class OutputNamer:
    """배치 단위 파일명 할당기 — 시각 1회 캡처 · 연번 증가 · 충돌 접미사.

    ``next(record)`` 를 레코드 순서대로 호출한다. 같은 이름이 다시 나오면 ``_1``·``_2`` …
    를 붙여 유일하게 만든다(패턴에 명시된 ``_1`` 도 덮어쓰지 않는다). 시각은 인스턴스
    생성 시 1회 캡처하므로 한 배치의 모든 파일이 같은 날짜 토큰을 공유한다.
    """

    def __init__(self, pattern: str, now: "datetime | None" = None):
        self.pattern = pattern
        self.now = now or datetime.now()
        self._seq = 0
        self._seen: "set[str]" = set()

    def next(self, data: "dict[str, object]") -> str:
        self._seq += 1
        name = make_output_filename(self.pattern, data, seq=self._seq, now=self.now)
        return self._dedupe(name)

    def _dedupe(self, name: str) -> str:
        if name not in self._seen:
            self._seen.add(name)
            return name
        stem, ext = name[:-5], name[-5:]  # ``.hwpx`` 보장됨
        i = 1
        cand = f"{stem}_{i}{ext}"
        while cand in self._seen:
            i += 1
            cand = f"{stem}_{i}{ext}"
        self._seen.add(cand)
        return cand
