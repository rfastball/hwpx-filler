"""filename-pattern/v1 의 순수 sanitation·예약 토큰 서식 kernel — naming·delivery 단일 출처.

VBA ``CleanFileName`` 포트의 파일시스템 금지문자 치환과 ``{{date}}``·``{{seq}}`` 예약 토큰 서식을
담는다. 제품 파일명 조립(:mod:`hwpxfiller.naming`)과 batch delivery 해석
(:mod:`hwpxfiller.application.generation_delivery`)이 이 kernel 을 공유해 sanitation 의미를 두 벌
두지 않는다(같은 상태를 두 곳이 판정하지 않는다).

PURE domain: 저장소·native·application·상위 링을 import 하지 않는다.
"""

from __future__ import annotations

import re
from datetime import datetime

# 파일시스템 금지문자(경로 구분자·Windows 예약 문자·제어문자). '_' 로 치환한다.
_INVALID = re.compile(r'[\\/:*?"<>|\r\n\t]')

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
    """파일시스템 금지문자를 ``_`` 로 치환한다(filename-pattern/v1 sanitation)."""
    return _INVALID.sub("_", name)


def has_forbidden_filename_char(name: str) -> bool:
    """Windows 금지 filename 문자(``\\ / : * ? " < > |`` + 제어문자)가 하나라도 있으면 True.

    drive prefix(``C:``)·alternate-data-stream(``name:stream``)의 ``:`` 도 여기 걸린다.
    """
    return bool(_INVALID.search(name))


def format_date_token(spec: str | None, now: datetime) -> str:
    """``{{date}}``/``{{date:...}}`` 서식. 기본 ``YYYYMMDD``. 결과도 금지문자를 청소한다."""
    fmt = spec or "YYYYMMDD"
    for tok, strf in _DATE_MAP:
        fmt = fmt.replace(tok, strf)
    return clean_filename(now.strftime(fmt))


def format_seq_token(pad: str | None, seq: int) -> str:
    """``{{seq}}``/``{{seq:001}}`` 서식. pad 리터럴 길이가 폭이다(``001`` → 폭 3)."""
    width = len(pad) if pad else 0
    return f"{seq:0{width}d}" if width else str(seq)
