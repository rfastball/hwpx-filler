"""텍스트 템플릿 렌더링 — 데이터 → 텍스트(순수 값 치환).

데이터 레코드를 평문 템플릿의 ``{{필드}}`` 에 치환한다. `core/text_extract.py`
(HWPX→텍스트)의 거울이며, lxml·OCF 없이 순수 문자열이라 가볍다(온나라 기안 등 즉각 복사).

**서식/표시형은 여기서 하지 않는다.** 표시형(`150,000,000원`, `2026년 6월 15일`)은 매핑
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


@dataclass
class RenderReport:
    """렌더 중 발견한 문제 — 표현 계층(CLI/GUI)이 사용자에게 알린다."""

    missing_fields: "list[str]" = field(default_factory=list)  # 토큰이 참조하나 레코드에 없음(치명)
    empty_fields: "list[str]" = field(default_factory=list)    # 필드는 있으나 값이 빈 문자열(경고)

    @property
    def has_issues(self) -> bool:
        return bool(self.missing_fields)


def template_fields(template: str) -> "list[str]":
    """템플릿이 참조하는 필드 이름 목록(중복 제거, 등장 순)."""
    seen: "dict[str, None]" = {}
    for m in _TOKEN.finditer(template):
        seen.setdefault(m.group(1).strip(), None)
    return list(seen)


def render_record(template: str, record: "dict[str, object]") -> "tuple[str, RenderReport]":
    """``template`` 의 ``{{필드}}`` 를 ``record`` 값으로 순수 치환한 텍스트와 리포트를 반환한다.

    ``record`` 는 원본 레코드이거나, 프로파일이 표시형까지 적용한 결과(``profile.apply``)다 —
    이 함수는 어느 쪽이든 값을 그대로 꽂을 뿐 서식하지 않는다.
    """
    report = RenderReport()
    missing: "dict[str, None]" = {}
    empty: "dict[str, None]" = {}

    def _sub(m: "re.Match") -> str:
        name = m.group(1).strip()
        if name not in record:
            missing.setdefault(name, None)
            return m.group(0)
        raw = record[name]
        value = "" if raw is None else str(raw)
        if value.strip() == "":
            empty.setdefault(name, None)
        return value

    text = _TOKEN.sub(_sub, template)
    report.missing_fields = list(missing)
    report.empty_fields = list(empty)
    return text, report
