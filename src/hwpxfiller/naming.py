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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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


_FIELD_TOKEN = re.compile(r"\{\{([^{}]+)\}\}")
_RESERVED_TOKENS = ("date", "seq")


def pattern_field_tokens(pattern: str) -> "list[str]":
    """패턴이 요구하는 **데이터 필드** 토큰 이름(문서순·중복 제거). 예약 토큰 제외.

    파일명 계약 사전검증용 — 여기 나온 키가 레코드에 없으면 미치환 ``{{토큰}}`` 이
    실파일명에 그대로 남는다. 조용한 통과 대신 호출부(CLI/GUI)가 시끄럽게 다룰 수
    있게 요구 키를 노출한다(RC-20).
    """
    out: "dict[str, None]" = {}
    for m in _FIELD_TOKEN.finditer(pattern):
        name = m.group(1)
        if name.split(":", 1)[0] in _RESERVED_TOKENS:
            continue
        out.setdefault(name, None)
    return list(out)


def pattern_uses_seq(pattern: str) -> bool:
    """패턴이 ``{{seq}}`` 계열 토큰을 쓰는가 — **표시순서와 파일명의 연동 여부** 판정.

    표시순서(재작성 F3, 지도 §10.11 판정 I)를 사용자 축으로 열면 순번이 표시 순서를 따라
    바뀐다. 그 사실을 문안이 말해야 하는데, 순번을 안 쓰는 패턴에도 말하면 문안이 거짓이
    된다 — 어느 쪽인지는 토큰 판정기 단일 출처(:data:`_SEQ_TOKEN`)가 답한다.
    """
    return _SEQ_TOKEN.search(pattern) is not None


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
        return self.next_detail(data)[0]

    def next_detail(self, data: "dict[str, object]") -> "tuple[str, bool]":
        """``(발급한 이름, 꼬리표가 붙었는가)`` — 수렴 집계(C-01)의 원천.

        꼬리표 자체는 파일 소실을 막는 올바른 처분이지만, **몇 건이 수렴했는지**를 아무도
        세지 않으면 사용자는 왜 ``_1`` 이 붙었는지 모른다. 세는 자리를 여기 둔다: 규칙을
        아는 유일한 지점이라 밖에서 재구현하면 그 순간 판정이 두 벌이 된다.
        """
        self._seq += 1
        name = make_output_filename(self.pattern, data, seq=self._seq, now=self.now)
        deduped = self._dedupe(name)
        return deduped, deduped != name

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


# ------------------------------------------------------- 디스크 충돌 검출(RC-02)
def plan_output_names(
    pattern: str, records: "list[dict[str, object]]", *, now: "datetime | None" = None
) -> "list[str]":
    """배치가 발급할 파일명 전체를 미리 계산한다(:class:`OutputNamer` 와 동일 규칙·순서).

    ``_seen`` 은 배치 **내** 유일성만 보장한다 — 디스크의 기존 파일과의 충돌은
    :func:`existing_outputs` 로 생성 **전에** 검출해 정책(GUI 확인·CLI ``--overwrite``)
    이 분기한다. 조용한 접미사 회피는 하지 않는다(확인-또는-경보).
    """
    namer = OutputNamer(pattern, now=now)
    return [namer.next(r) for r in records]


#: Windows 기본 경로 길이 한계(끝 NUL 포함). 확장 경로(``\\?\``)·`longPathsEnabled` 에서는
#: 더 길어도 성공하므로 **경고이지 차단이 아니다**(단정하면 문안이 거짓이 된다).
MAX_PATH_CHARS = 260


@dataclass(frozen=True)
class OutputNameAudit:
    """배치가 발급할 이름의 **집합 단위** 감사 — 보고서 C-01 의 자리(지도 §10.12 판정 K).

    master 가 이미 권위 있게 막는 것(미해소 토큰 danger 게이트·디스크 충돌 확인·배치 내
    유일성)은 그대로 두고, **세지 않던 둘**만 센다:

    - ``converged`` — 서로 다른 레코드가 같은 이름으로 수렴해 꼬리표가 붙은 자리. 표
      「문서」 열이 실이름을 이미 보여주므로 경보로 승격하지 않는다(전면 가시성 완화 조항).
      규모만 미리보기 증거가 말한다.
    - ``too_long`` — 저장 경로가 한계를 넘는 자리. 이건 **보이지 않는다**: 실행하면 확실히
      실패하는데 지금은 생성 중 OSError 로만 드러난다. 실행해서 알게 하는 건 확인-또는-경보
      위반이라 사전 경고로 올린다.
    """

    names: "tuple[str, ...]" = ()
    converged: "tuple[int, ...]" = ()   # 이름 목록 안의 자리(0-based)
    too_long: "tuple[int, ...]" = ()

    @property
    def has_warning(self) -> bool:
        return bool(self.too_long)


def audit_output_names(
    pattern: str, records: "list[dict[str, object]]", out_dir: "str | Path" = "",
    *, now: "datetime | None" = None,
) -> OutputNameAudit:
    """:func:`plan_output_names` 와 **같은 규칙·순서**로 계산하며 집합 성질을 함께 센다.

    이름 자체는 계획과 한 글자도 다르면 안 된다(미리보기가 실행과 다른 이름을 말하는 순간
    「보이는 것 = 실행되는 것」이 이 자리에서만 깨진다) — 그래서 별도 구현이 아니라 같은
    :class:`OutputNamer` 를 돈다.
    """
    namer = OutputNamer(pattern, now=now)
    names: "list[str]" = []
    converged: "list[int]" = []
    too_long: "list[int]" = []
    base = Path(out_dir) if out_dir else None
    for i, rec in enumerate(records):
        name, dedup = namer.next_detail(rec)
        names.append(name)
        if dedup:
            converged.append(i)
        if base is not None and len(str(base / name)) >= MAX_PATH_CHARS:
            too_long.append(i)
    return OutputNameAudit(tuple(names), tuple(converged), tuple(too_long))


def existing_outputs(out_dir: "str | Path", names: "list[str]") -> "list[str]":
    """``out_dir`` 에 이미 존재하는 대상 파일 경로 목록 — 덮어쓰기 정책 분기의 원천.

    검출만 한다(무변형·무결정). 덮을지 말지는 호출측이 확정한다: GUI 는 실행 전
    사용자 확인, CLI 는 기본 차단 + ``--overwrite`` 옵트인.
    """
    out = Path(out_dir)
    return [str(out / n) for n in names if (out / n).exists()]
