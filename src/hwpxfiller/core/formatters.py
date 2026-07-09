"""공용 포매터 어휘 + 토큰 치환 엔진 — 값 1개 in → 문자열 1개 out(1→1).

세 소비자(텍스트 render · 파일명 `naming` · 매핑 `mapping`)가 흩어져 갖던 값-포맷
로직을 여기 한 곳으로 모은다. **의존 없는 리프 모듈**이라 누구나 당겨 쓴다.

범주 구분(설계의 뼈대):
  - **생성자(generator)** — `{{date}}`·`{{seq}}`: 입력 필드가 없고 문맥/배치 상태를
    낸다. `naming` 고유이며 여기 없다(의미가 다름: '지금 시각' vs '데이터 값').
  - **결합자(combiner, N→1)** — 여러 소스를 하나로: `mapping` 고유(join/일시결합/금액결합).
  - **포매터(formatter, 1→1)** — 여기 레지스트리. 한 값을 받아 포맷. `|` 로 **체이닝**한다.

토큰 문법(L2 = 포매터 + 파이프 체이닝, 제어흐름 없음):
    ``{{필드}}``                      값 그대로
    ``{{필드|amount}}``               150000000 → 150,000,000원
    ``{{필드|datetime}}``             2026-06-15 → 2026년 6월 15일
    ``{{필드|date:YYYY-MM-DD}}``      데이터 날짜값을 패턴으로 재서식
    ``{{필드|default:없음}}``          빈 값이면 대체
    ``{{필드|trim|upper}}``           체인(왼→오 순차 적용)

**제어흐름 없음.** if/반복/산술은 두지 않는다(문서 조립 non-goal). 체이닝은 함수 합성일
뿐 여전히 '한 값의 포맷'이다. 미지의 포매터는 조용히 넘기지 않고 신고한다(누락은 시끄럽게).
"""

from __future__ import annotations

import re

# ``{{필드}}`` / ``{{필드|f1|f2:arg}}`` — 필드(내부 공백 허용) + 선택적 파이프 체인.
TOKEN_RE = re.compile(r"\{\{\s*([^|}]+?)\s*(\|[^}]*)?\}\}")


# ------------------------------------------------------------------ 포매터
def _f_amount(value: str, arg: "str | None") -> str:
    digits = re.sub(r"[^\d-]", "", value)
    if digits and digits.lstrip("-").isdigit():
        return f"{int(digits):,}원"
    return value


def _f_datetime(value: str, arg: "str | None") -> str:
    """``2026-06-15`` 또는 ``2026-06-15 09:00`` → ``2026년 6월 15일 [09:00]``."""
    parts = value.split()
    if not parts:
        return ""
    date_str = parts[0]
    time_str = parts[1].strip() if len(parts) > 1 else ""
    m = re.match(r"(\d{4})[-.]?(\d{2})[-.]?(\d{2})", date_str)
    if m:
        y, mo, d = m.groups()
        out = f"{int(y)}년 {int(mo)}월 {int(d)}일"
        if time_str:
            out += f" {time_str}"
        return out
    return " ".join(p for p in parts if p)


def _f_date(value: str, arg: "str | None") -> str:
    """데이터 날짜값을 ``arg`` 패턴(YYYY/MM/DD…)으로 재서식. 파싱 실패 시 원본."""
    fmt = arg or "YYYY-MM-DD"
    m = re.search(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})", value)
    if not m:
        return value
    y, mo, d = m.groups()
    # 긴 토큰 먼저(YYYY 전에 YY 치환 금지). 순서가 하중이다.
    for tok, v in (
        ("YYYY", y), ("YY", y[2:]),
        ("MM", mo.zfill(2)), ("M", str(int(mo))),
        ("DD", d.zfill(2)), ("D", str(int(d))),
    ):
        fmt = fmt.replace(tok, v)
    return fmt


def _f_default(value: str, arg: "str | None") -> str:
    return (arg or "") if value.strip() == "" else value


FORMATTERS: "dict[str, callable]" = {
    "amount": _f_amount,
    "datetime": _f_datetime,
    "date": _f_date,
    "default": _f_default,
    "upper": lambda v, a: v.upper(),
    "lower": lambda v, a: v.lower(),
    "trim": lambda v, a: v.strip(),
}


def apply_formatter(name: str, value: str, arg: "str | None") -> "str | None":
    """단항 포매터 1개 적용. 미지원이면 ``None`` (호출자가 신고)."""
    fn = FORMATTERS.get(name)
    if fn is None:
        return None
    return fn(value, arg)


def parse_chain(chain: "str | None") -> "list[tuple[str, str | None]]":
    """``"|f1|f2:arg"`` → ``[("f1", None), ("f2", "arg")]``. 빈 세그먼트는 건너뛴다."""
    specs: "list[tuple[str, str | None]]" = []
    if not chain:
        return specs
    for seg in chain.split("|"):
        seg = seg.strip()
        if not seg:
            continue
        if ":" in seg:
            name, arg = seg.split(":", 1)
            specs.append((name.strip(), arg))  # arg 는 트림 안 함(대체값/구분자 공백 보존)
        else:
            specs.append((seg, None))
    return specs


def apply_chain(value: str, specs: "list[tuple[str, str | None]]") -> "tuple[str, list[str]]":
    """포매터 체인을 순차 적용. (결과값, 미지-포매터-이름 목록)."""
    unknown: "list[str]" = []
    for name, arg in specs:
        out = apply_formatter(name, value, arg)
        if out is None:
            unknown.append(name)
            continue  # 미지 포매터는 건너뛰고 신고(값은 유지)
        value = out
    return value, unknown


def render_tokens(
    template: str, record: "dict[str, object]"
) -> "tuple[str, list[str], list[str], list[str]]":
    """``template`` 의 토큰을 ``record`` 로 치환. (텍스트, 누락필드, 빈필드, 미지포매터).

    - 데이터에 없는 필드: 토큰을 그대로 남기고 누락 신고(조용히 빈칸 처리 안 함).
    - 미지 포매터: 체인에 하나라도 있으면 **토큰 전체를 그대로** 남기고 신고(저작 오류가
      출력에서 글라링하게 — 누락은 시끄럽게).
    - 빈 값: 체인 적용 후에도 여전히 비면 빈필드로 신고(``default`` 가 살리면 신고 안 함).
    """
    missing: "dict[str, None]" = {}
    empty: "dict[str, None]" = {}
    unknown: "dict[str, None]" = {}

    def _sub(m: "re.Match") -> str:
        name = m.group(1).strip()
        specs = parse_chain(m.group(2))
        if name not in record:
            missing.setdefault(name, None)
            return m.group(0)
        raw = record[name]
        value = "" if raw is None else str(raw)
        raw_empty = value.strip() == ""
        rendered, unk = apply_chain(value, specs)
        if unk:
            for u in unk:
                unknown.setdefault(u, None)
            return m.group(0)  # 미지 포매터가 있으면 토큰을 그대로(글라링)
        if raw_empty and rendered.strip() == "":
            empty.setdefault(name, None)
        return rendered

    text = TOKEN_RE.sub(_sub, template)
    return text, list(missing), list(empty), list(unknown)


def referenced_fields(template: str) -> "list[str]":
    """템플릿이 참조하는 필드 이름 목록(중복 제거, 등장 순)."""
    seen: "dict[str, None]" = {}
    for m in TOKEN_RE.finditer(template):
        seen.setdefault(m.group(1).strip(), None)
    return list(seen)
