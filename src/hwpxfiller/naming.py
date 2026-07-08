"""출력 파일명 생성 — VBA ``Make_Output_FileName`` / ``CleanFileName`` 포트.

패턴 문자열의 ``{{키}}`` 를 레코드 값으로 치환하고 파일시스템 금지문자를 정리한다.
"""

from __future__ import annotations

import re

_INVALID = re.compile(r'[\\/:*?"<>|\r\n\t]')


def clean_filename(name: str) -> str:
    return _INVALID.sub("_", name)


def make_output_filename(pattern: str, data: "dict[str, object]") -> str:
    """``pattern`` 의 ``{{키}}`` 를 치환. 확장자 ``.hwpx`` 를 보장한다."""
    out = pattern
    for key, val in data.items():
        token = "{{" + str(key) + "}}"
        if token in out:
            out = out.replace(token, clean_filename(str(val)))
    if not out.lower().endswith(".hwpx"):
        out += ".hwpx"
    return out
