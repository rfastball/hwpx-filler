"""텍스트 템플릿 렌더링 — 데이터 → 텍스트(순수 값 치환).

데이터 레코드를 평문 템플릿의 ``{{필드}}`` 에 치환한다. `core/text_extract.py`
(HWPX→텍스트)의 거울이며, lxml·OCF 없이 순수 문자열이라 가볍다(온나라 기안 등 즉각 복사).

**서식/표시형은 여기서 하지 않는다.** 표시형(`150,000,000원`, `2026. 6. 15.`)은 매핑
프로파일이 데이터 옆에서 WYSIWYG로 확정해 **이미 적용된 값**으로 들어온다(HWPX 생성 경로와
동일 — `profile.apply(record)`). 그래서 토큰은 순수 ``{{필드}}`` 뿐이고, 인라인 포매터
(``{{필드|amount}}``)는 두지 않는다: 맥락 없는 템플릿에서의 서식 선언은 폐기했다(D-6).

데이터에 없는 필드는 토큰을 그대로 남기고 신고한다(조용히 빈칸 처리 안 함 — 누락은 시끄럽게).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ``{{필드}}`` — 내부 공백 허용. 파이프(``|``)는 배제한다: 인라인 포매터 문법을 두지 않으므로
# ``{{x|amount}}`` 같은 옛 토큰은 매칭되지 않고 원문에 그대로 남아(눈에 보이는) 신호가 된다.
_TOKEN = re.compile(r"\{\{\s*([^{}|]+?)\s*\}\}")

# 채움 표지 삼분 종류(R-flow 블록 3 결정 22·블록 5 결정 33) — 원문/채움/미채움 + 빈값.
# 앱 렌더 전용 표지이며 클립보드 평문은 불변이다(:func:`render_record` 결과와 세그먼트
# 텍스트 연결이 항상 일치 — 아래 불변식). 웹(txt.js·빠른 기안)은 이 세그먼트를 받아
# 그리기만 한다 — 토큰 정규식을 웹에서 재구현하지 않는다(파생경계 번역오류의 상류 차단,
# jamo :meth:`FilterView.segments` 계약과 동형).
SEG_LITERAL = "literal"  # 템플릿 원문(토큰 밖)
SEG_FILL = "fill"        # 값이 채워진 토큰(음영)
SEG_BLANK = "blank"      # 필드는 있으나 값이 빈 토큰(빈 값 마커)
SEG_MISSING = "missing"  # 레코드에 없는 토큰(빨강 {{토큰}})


@dataclass
class RenderReport:
    """렌더 중 발견한 문제 — 표현 계층(CLI/GUI)이 사용자에게 알린다."""

    missing_fields: "list[str]" = field(default_factory=list)  # 토큰이 참조하나 레코드에 없음(치명)
    empty_fields: "list[str]" = field(default_factory=list)    # 필드는 있으나 값이 빈 문자열(경고)

    @property
    def has_issues(self) -> bool:
        return bool(self.missing_fields)


@dataclass(frozen=True)
class RenderSegment:
    """렌더 텍스트의 한 조각 — 표지 삼분(결정 22)의 링1 단위.

    ``text`` 는 클립보드로 나가는 **원문 그대로**다(fill=값, literal=템플릿 원문,
    missing=``{{토큰}}`` 원문, blank=``""``). 그래서 세그먼트 텍스트를 이어붙이면 항상
    :func:`render_record` 의 텍스트와 같다(불변식 — 표지는 앱 렌더 전용, 평문 불변).
    ``name`` 은 토큰 세그먼트의 필드명(빈 값 마커·경보 병기용), literal 은 ``""``.
    """

    text: str
    kind: str
    name: str = ""


def template_fields(template: str) -> "list[str]":
    """템플릿이 참조하는 필드 이름 목록(중복 제거, 등장 순)."""
    seen: "dict[str, None]" = {}
    for m in _TOKEN.finditer(template):
        seen.setdefault(m.group(1).strip(), None)
    return list(seen)


def render_segments(
    template: str, record: "dict[str, object]"
) -> "tuple[list[RenderSegment], RenderReport]":
    """``template`` 을 표지 삼분 세그먼트 목록 + 리포트로 낸다 — 토큰 순회의 단일 출처.

    :func:`render_record` 가 이 위임체다(토큰 의미론을 두 번 걷지 않는다). 연속 literal
    조각은 하나로 합치고, 빈 조각은 내지 않는다. ``record`` 는 원본이거나 프로파일이
    표시형까지 적용한 결과(``profile.apply``) — 어느 쪽이든 값을 그대로 꽂을 뿐 서식하지 않는다.
    """
    report = RenderReport()
    missing: "dict[str, None]" = {}
    empty: "dict[str, None]" = {}
    segments: "list[RenderSegment]" = []
    last = 0

    def _literal(chunk: str) -> None:
        if not chunk:
            return
        if segments and segments[-1].kind == SEG_LITERAL:  # 연속 literal 병합
            segments[-1] = RenderSegment(segments[-1].text + chunk, SEG_LITERAL)
        else:
            segments.append(RenderSegment(chunk, SEG_LITERAL))

    for m in _TOKEN.finditer(template):
        _literal(template[last:m.start()])
        last = m.end()
        name = m.group(1).strip()
        if name not in record:
            missing.setdefault(name, None)
            segments.append(RenderSegment(m.group(0), SEG_MISSING, name))
            continue
        raw = record[name]
        value = "" if raw is None else str(raw)
        if value.strip() == "":
            empty.setdefault(name, None)
            segments.append(RenderSegment(value, SEG_BLANK, name))
        else:
            segments.append(RenderSegment(value, SEG_FILL, name))
    _literal(template[last:])

    report.missing_fields = list(missing)
    report.empty_fields = list(empty)
    return segments, report


# 연속 ASCII 공백(2칸 이상) — 표 흉내 정렬("건    명")의 문자적 흔적. 1칸은 낱말 사이라
# 정렬 의도가 아니므로 제외한다(경보 남발 차단).
_SPACE_RUN = re.compile(r" {2,}")

# 전각 공백 — 한글·전각과 같은 폭이라 **모든 글꼴에서 균일**(고정폭·비례폭 불문). 반각 2칸
# 폭과 같으므로 아래 치환은 고정폭 선언에서의 열 위치도 보존한다.
FULLWIDTH_SPACE = "　"


def has_space_run(text: str) -> bool:
    """연속 공백 정렬이 있는가 — 선언-조건부 정렬 린트(R-flow 블록 3 결정 17)의 술어.

    비례폭 글꼴을 대상으로 선언했을 때만 표면이 이 경보를 낸다: 고정폭(굴림체·돋움체)에서
    연속 공백 정렬은 정당한 저작이므로 경보하면 소음이다.
    """
    return _SPACE_RUN.search(text) is not None


def align_fullwidth(text: str) -> str:
    """연속 ASCII 공백을 전각 공백으로 치환 — 폭 보존(반각 2칸 = 전각 1칸), 홀수 잔여 1칸 유지.

    치환 후에는 :func:`has_space_run` 이 거짓이 된다(잔여는 1칸뿐) — 술어와 처방이 서로를
    닫는다(경보가 조치 후에도 남는 무한 잔소리 방지).
    """
    return _SPACE_RUN.sub(
        lambda m: FULLWIDTH_SPACE * (len(m.group(0)) // 2) + " " * (len(m.group(0)) % 2),
        text,
    )


def segments_have_space_run(segments: "list[RenderSegment]") -> bool:
    """**템플릿 원문 조각**에 연속 공백 정렬이 있는가 — 카드 린트 술어.

    literal 만 본다: 정렬 런은 사용자가 템플릿에 저작한 것이고, 값(fill) 안의 연속 공백은
    데이터의 사실이다(규격·코드 표기 등). 값까지 술어에 넣으면 저작하지도 않은 정렬을
    고치라고 경보하게 된다.
    """
    return any(s.kind == SEG_LITERAL and has_space_run(s.text) for s in segments)


def align_segments(segments: "list[RenderSegment]") -> "list[RenderSegment]":
    """**템플릿 원문 조각만** 전각 치환 — 데이터 값은 원본 그대로 복사된다.

    값(fill)을 건드리지 않는 이유: 복사되는 데이터가 원본과 글자 단위로 같아야 한다는 것이
    이 도구의 텔로스다. 정렬은 사용자가 템플릿에 저작한 배치이므로 처방의 대상이지만, 값
    안의 ``12  345`` 는 데이터의 사실이라 앱이 고쳐 쓸 자격이 없다.

    조각을 이어붙인 뒤가 아니라 **조각마다** 치환하므로 카드 렌더(세그먼트)와 클립보드
    (세그먼트 이어붙임)가 같은 함수를 통과한다 — "보이는 것이 복사되는 것". 대가로 세그먼트
    경계를 걸친 공백(리터럴 끝 1칸 + 값 앞 1칸)은 잡지 않는다: 각 조각 1칸씩이라 저작된
    정렬 런이 아니므로 수용한다.
    """
    return [
        RenderSegment(align_fullwidth(s.text), s.kind, s.name)
        if (s.kind == SEG_LITERAL and s.text) else s
        for s in segments
    ]


def render_record(template: str, record: "dict[str, object]") -> "tuple[str, RenderReport]":
    """``template`` 의 ``{{필드}}`` 를 ``record`` 값으로 순수 치환한 텍스트와 리포트를 반환한다.

    ``record`` 는 원본 레코드이거나, 프로파일이 표시형까지 적용한 결과(``profile.apply``)다 —
    이 함수는 어느 쪽이든 값을 그대로 꽂을 뿐 서식하지 않는다. :func:`render_segments` 에
    위임하고 세그먼트 텍스트를 이어붙인다(불변식: 결과 == 세그먼트 연결).
    """
    segments, report = render_segments(template, record)
    return "".join(s.text for s in segments), report
