"""텍스트 템플릿 렌더링 — 데이터 → 텍스트(값 치환의 확장, 문서 조립 아님).

`core/text_extract.py`(HWPX→텍스트)의 거울: 데이터 레코드를 평문 템플릿의 ``{{토큰}}``
에 꽂아 '즉각 복사'용 텍스트를 만든다. lxml·OCF 없이 순수 문자열 치환이라 HWPX 주입
경로와 독립이고 가볍다(온나라 기안 등).

토큰 문법·포매터 어휘·치환 엔진은 공용 리프 `core/formatters.py` 가 소유한다(파일명
`naming`·매핑 `mapping` 과 같은 어휘를 공유). 이 모듈은 그 엔진을 텍스트 렌더 관점의
얇은 표면(:class:`RenderReport`)으로 감싼다.

**제어흐름 없음.** 표(가변 반복 행)는 동결(D-2). 항목 + 고정 레이아웃 표는 순수 치환으로
커버된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .formatters import referenced_fields, render_tokens

# 하위호환 재노출 — 기존 참조가 이 이름을 쓴다.
template_fields = referenced_fields


@dataclass
class RenderReport:
    """렌더 중 발견한 문제 — 표현 계층(CLI/GUI)이 사용자에게 알린다."""

    missing_fields: "list[str]" = field(default_factory=list)   # 토큰이 참조하나 레코드에 없음(치명)
    empty_fields: "list[str]" = field(default_factory=list)     # 필드는 있으나 값이 빈 문자열(경고)
    unknown_formatters: "list[str]" = field(default_factory=list)  # 미지/미지원 포매터

    @property
    def has_issues(self) -> bool:
        return bool(self.missing_fields or self.unknown_formatters)


def render_record(template: str, record: "dict[str, object]") -> "tuple[str, RenderReport]":
    """``template`` 의 토큰을 ``record`` 값으로 치환한 텍스트와 리포트를 반환한다."""
    text, missing, empty, unknown = render_tokens(template, record)
    return text, RenderReport(missing_fields=missing, empty_fields=empty, unknown_formatters=unknown)
