"""filename-pattern/v1 출력 이름 kernel — 해석·조립·안전 판정·배치 충돌을 한 곳이 진다(#798).

VBA ``CleanFileName`` 포트의 파일시스템 금지문자 치환과 ``{{date}}``·``{{seq}}`` 예약 토큰 서식에
더해, 패턴 해석(:func:`parse_filename_pattern`), 한 문서 이름 조립(:func:`render_output_name`),
최종 이름의 안전 판정(:func:`guard_output_name`), 배치 안 충돌 접미사(:func:`dedupe_output_names`)
를 담는다. managed 배달(:mod:`hwpxfiller.application.generation_delivery`)과 표시·legacy 표면
(:mod:`hwpxfiller.naming` → 실행 화면 「문서」 열·편집기 예시·CLI)이 **같은 함수**를 불러, 미리
보인 이름과 실제로 쓰는 이름이 한 판정에서 나온다(같은 상태를 두 곳이 판정하지 않는다).

규칙(#798 완료 조건):

- 닫히지 않은 ``{{``·빈 ``{{}}``·중첩 brace 는 조용히 리터럴이 되지 않고
  :data:`OUTPUT_NAME_PATTERN_INVALID` 로 거절한다.
- 최종 이름은 출력 폴더 안의 **평평한 파일 이름**이어야 한다 — 경로 구분자·drive/ADS 의 ``:``·
  Windows 금지문자·제어문자·``.``/``..``·빈 stem·끝 점/공백·Windows 예약 장치 이름(``CON``·
  ``PRN``·``AUX``·``NUL``·``COM1``~``COM9``·``LPT1``~``LPT9``, 확장자 유무·대소문자 무관)은
  :data:`OUTPUT_PATH_ESCAPE_DETECTED` 로 거절한다.
- 배치 안 충돌 판정은 Windows 파일 시스템처럼 대소문자를 구분하지 않는다(casefold). 표시 철자는
  원본을 둔다.

PURE domain: 저장소·native·application·상위 링을 import 하지 않는다(시계는 호출자가 넘긴다).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

# 진단 코드 — 배달 계획의 blocker/context 어휘와 같은 문자열이다(표면 문장은 소비자가 고른다).
OUTPUT_NAME_PATTERN_INVALID = "OUTPUT_NAME_PATTERN_INVALID"
OUTPUT_PATH_ESCAPE_DETECTED = "OUTPUT_PATH_ESCAPE_DETECTED"

#: 산출 확장자 — 조립이 보장하고 충돌 접미사가 그 앞에 들어간다.
OUTPUT_EXTENSION = ".hwpx"

# 파일시스템 금지문자(경로 구분자·Windows 예약 문자·제어문자). '_' 로 치환한다.
_INVALID = re.compile(r'[\\/:*?"<>|\r\n\t]')
# 최종 이름 판정용 — 치환 대상 밖의 제어문자(NUL 포함)까지 거절한다.
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# Windows 예약 장치 이름 — 첫 점 앞 이름(끝 공백·점 제거)을 대소문자 무관으로 대조한다.
_RESERVED_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

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

_RESERVED_DATE = "date"
_RESERVED_SEQ = "seq"

# 편집 중 패턴(아직 완성되지 않았을 수 있다)을 **나열**하는 관대한 판독기 — 유효성 판정은
# :func:`parse_filename_pattern` 이 한다. 둘은 잘 짜인 패턴에서 같은 토큰을 본다.
_FIELD_TOKEN = re.compile(r"\{\{([^{}]+)\}\}")
_SEQ_TOKEN = re.compile(r"\{\{seq(?::([^}]*))?\}\}")


class OutputNameError(ValueError):
    """출력 이름을 만들 수 없다 — ``code`` 는 배달 계획과 같은 진단 코드다."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# ─── sanitation · 예약 토큰 서식 ─────────────────────────────────────────────────
def clean_filename(name: str) -> str:
    """파일시스템 금지문자를 ``_`` 로 치환한다(filename-pattern/v1 sanitation)."""
    return _INVALID.sub("_", name)


def has_forbidden_filename_char(name: str) -> bool:
    """Windows 금지 filename 문자(``\\ / : * ? " < > |`` + 제어문자)가 하나라도 있으면 True.

    drive prefix(``C:``)·alternate-data-stream(``name:stream``)의 ``:`` 도 여기 걸린다.
    """
    return bool(_UNSAFE.search(name))


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


# ─── PatternToken 합타입 ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LiteralSegment:
    text: str


@dataclass(frozen=True)
class ReservedDateToken:
    date_spec: str | None  # None = 기본 YYYYMMDD


@dataclass(frozen=True)
class ReservedSequenceToken:
    pad: str | None  # None = 무 pad. ``{{seq:001}}`` → pad "001"(폭 3)


@dataclass(frozen=True)
class FieldValueToken:
    field_id: str  # target logical Field ID(raw source key 아님)


PatternToken = LiteralSegment | ReservedDateToken | ReservedSequenceToken | FieldValueToken


# ─── 패턴 해석 ───────────────────────────────────────────────────────────────────
def parse_filename_pattern(pattern: object) -> tuple[PatternToken, ...]:
    """pattern text → PatternToken 열(문서 순서 = 이름 조립 순서).

    빈 패턴·닫히지 않은 ``{{``·빈 ``{{}}``·inner brace 는 :data:`OUTPUT_NAME_PATTERN_INVALID`.
    잘 짜인 패턴(``{{date}}``·``{{seq:001}}``·``{{필드}}``·리터럴)의 의미는 v1 그대로다 — 종전
    legacy 조립이 조용히 파일 이름에 흘리던 malformed brace 만 시끄럽게 거절한다. 단일 ``{``·짝
    없는 ``}`` 는 리터럴이다(과잉 거절 금지).
    """
    if not isinstance(pattern, str) or pattern == "":
        raise OutputNameError(OUTPUT_NAME_PATTERN_INVALID, "filename pattern 이 비어 있다")
    tokens: list[PatternToken] = []
    buf: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        if pattern[i : i + 2] == "{{":
            close = pattern.find("}}", i + 2)
            if close == -1:
                raise OutputNameError(OUTPUT_NAME_PATTERN_INVALID, "닫히지 않은 '{{' token")
            inner = pattern[i + 2 : close]
            if inner == "" or "{" in inner or "}" in inner:
                raise OutputNameError(
                    OUTPUT_NAME_PATTERN_INVALID,
                    f"malformed token: {pattern[i : close + 2]!r}",
                )
            if buf:
                tokens.append(LiteralSegment("".join(buf)))
                buf = []
            head, _, spec = inner.partition(":")
            has_spec = ":" in inner
            if head == _RESERVED_DATE:
                tokens.append(ReservedDateToken(spec if has_spec else None))
            elif head == _RESERVED_SEQ:
                tokens.append(ReservedSequenceToken(spec if has_spec else None))
            else:
                tokens.append(FieldValueToken(inner))
            i = close + 2
        else:
            buf.append(pattern[i])
            i += 1
    if buf:
        tokens.append(LiteralSegment("".join(buf)))
    return tuple(tokens)


def pattern_field_token_ids(tokens: Iterable[PatternToken]) -> tuple[str, ...]:
    """해석된 패턴의 필드 토큰 id(문서순·중복 제거)."""
    out: dict[str, None] = {}
    for tok in tokens:
        if isinstance(tok, FieldValueToken):
            out.setdefault(tok.field_id, None)
    return tuple(out)


def pattern_field_tokens(pattern: str) -> list[str]:
    """패턴이 요구하는 **데이터 필드** 토큰 이름(문서순·중복 제거). 예약 토큰 제외.

    편집 중인(아직 유효하지 않을 수 있는) 패턴에서도 부를 수 있는 **나열**이다 — 미해소 토큰
    경고·식별 열 해석이 쓴다. 패턴이 유효한지는 :func:`parse_filename_pattern` 이 판정한다.
    """
    out: dict[str, None] = {}
    for m in _FIELD_TOKEN.finditer(pattern):
        name = m.group(1)
        if name.split(":", 1)[0] in (_RESERVED_DATE, _RESERVED_SEQ):
            continue
        out.setdefault(name, None)
    return list(out)


def pattern_uses_seq(pattern: str) -> bool:
    """패턴이 ``{{seq}}`` 계열 토큰을 쓰는가 — 표시순서와 파일 이름의 연동 여부."""
    return _SEQ_TOKEN.search(pattern) is not None


def seq_token_pads(pattern: str) -> list[str | None]:
    """패턴의 ``{{seq}}`` 토큰들이 선언한 자릿수 리터럴(문서순). ``{{seq}}`` 는 ``None``."""
    return [match.group(1) for match in _SEQ_TOKEN.finditer(pattern)]


# ─── 한 문서 이름 조립 ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RenderedNamePart:
    """조립에 들어간 토큰 값 하나 — ``kind`` 는 ``FIELD``·``DATE``·``SEQ``."""

    kind: str
    field_id: str | None
    text: str


def render_output_name(
    tokens: Iterable[PatternToken],
    field_values: Mapping[str, object],
    *,
    seq: int,
    now: datetime | None,
    keep_unresolved: bool = False,
) -> tuple[str, tuple[RenderedNamePart, ...]]:
    """토큰 열 + 값 → 파일 이름(확장자 보장)과 조립에 쓴 토큰 값들.

    필드 값·날짜는 :func:`clean_filename` 으로 청소하고, 리터럴은 청소하지 않는다(리터럴이 만든
    위험은 :func:`guard_output_name` 이 최종 이름에서 거절한다). ``seq`` 는 1-based 배치 순번,
    ``now`` 는 배치 기준 시각이다. 값이 없는 필드 토큰은 기본으로 ``KeyError`` 다(배달은 미리
    blocker 로 닫는다) — ``keep_unresolved`` 면 ``{{id}}`` 를 그대로 둔다(표시 표면: 미해소
    토큰 경고가 따로 선다).
    """
    parts: list[str] = []
    resolved: list[RenderedNamePart] = []
    for tok in tokens:
        if isinstance(tok, LiteralSegment):
            parts.append(tok.text)
        elif isinstance(tok, ReservedDateToken):
            if now is None:
                raise ValueError("날짜 토큰에는 기준 시각이 필요합니다.")
            text = format_date_token(tok.date_spec, now)
            parts.append(text)
            resolved.append(RenderedNamePart("DATE", None, text))
        elif isinstance(tok, ReservedSequenceToken):
            text = format_seq_token(tok.pad, seq)
            parts.append(text)
            resolved.append(RenderedNamePart("SEQ", None, text))
        else:  # FieldValueToken
            if tok.field_id not in field_values:
                if not keep_unresolved:
                    raise KeyError(tok.field_id)
                parts.append("{{" + tok.field_id + "}}")
                continue
            cleaned = clean_filename(str(field_values[tok.field_id]))
            parts.append(cleaned)
            resolved.append(RenderedNamePart("FIELD", tok.field_id, cleaned))
    stem = "".join(parts)
    name = stem if stem.lower().endswith(OUTPUT_EXTENSION) else stem + OUTPUT_EXTENSION
    return name, tuple(resolved)


# ─── 최종 이름 안전 판정 ─────────────────────────────────────────────────────────
def guard_output_name(name: str) -> None:
    """최종 이름이 출력 폴더 안의 평평한 Windows 파일 이름인지 판정한다(위반은 거절).

    field·date 값은 이미 청소됐지만 리터럴은 청소하지 않으므로 여기가 최종 방어다. ``:`` 는
    drive-relative(``C:x``)·ADS(``name:stream``)를 만들어 다른 드라이브·스트림에 쓸 수 있고,
    예약 장치 이름(``CON.hwpx`` 등)은 파일이 아니라 장치를 연다. Windows 는 이름 끝의 점·공백을
    지워 저장하므로 끝 점·공백은 다른 이름으로 조용히 바뀌는 자리다.
    """
    if has_forbidden_filename_char(name):
        raise OutputNameError(
            OUTPUT_PATH_ESCAPE_DETECTED,
            f"resolved path 에 경로 구분자/drive/금지문자: {name!r}",
        )
    if name in (".", "..") or name.startswith(".."):
        raise OutputNameError(
            OUTPUT_PATH_ESCAPE_DETECTED, f"resolved path 가 상위 경로 참조: {name!r}"
        )
    if name.endswith((".", " ")):
        raise OutputNameError(
            OUTPUT_PATH_ESCAPE_DETECTED, f"resolved path 가 점·공백으로 끝난다: {name!r}"
        )
    stem = name[: -len(OUTPUT_EXTENSION)] if name.lower().endswith(OUTPUT_EXTENSION) else name
    if stem == "":
        # 확장자만 남는(빈 stem) 이름은 조용한 빈 파일명이라 막는다.
        raise OutputNameError(OUTPUT_PATH_ESCAPE_DETECTED, "resolved path 의 stem 이 비어 있다")
    device = name.split(".", 1)[0].rstrip(" .").upper()
    if device in _RESERVED_DEVICE_NAMES:
        raise OutputNameError(
            OUTPUT_PATH_ESCAPE_DETECTED,
            f"resolved path 가 Windows 예약 장치 이름이다: {name!r}",
        )


# ─── 배치 안 충돌 ────────────────────────────────────────────────────────────────
def collision_key(name: str) -> str:
    """두 이름이 같은 파일을 가리키는가의 판정 키 — Windows 처럼 대소문자 무관(casefold)."""
    return name.casefold()


def dedupe_output_names(
    base_names: Iterable[str], *, occupied_names: Iterable[str] = ()
) -> list[str]:
    """배치 안 같은 이름(대소문자 무관)에 결정적 접미사(_1·_2…)를 확장자 앞에 붙인다.

    배치 순서로 한 번 계산한다. ``occupied_names`` 는 이미 점유된 이름(접미사 회피 정책일 때)이고
    같은 키 규칙으로 대조한다. 표시 철자는 원본 그대로 둔다.
    """
    seen = {collision_key(name) for name in occupied_names}
    out: list[str] = []
    ext_len = len(OUTPUT_EXTENSION)
    for name in base_names:
        if collision_key(name) not in seen:
            seen.add(collision_key(name))
            out.append(name)
            continue
        stem, ext = name[:-ext_len], name[-ext_len:]
        i = 1
        cand = f"{stem}_{i}{ext}"
        while collision_key(cand) in seen:
            i += 1
            cand = f"{stem}_{i}{ext}"
        seen.add(collision_key(cand))
        out.append(cand)
    return out
