"""txt 즉시 기안 ViewModel — 템플릿 + 데이터 → 실시간 렌더(Qt 비의존, 링1).

트랙 이원성(DECISIONS §): txt 트랙은 외부 권위 렌더러가 없어 **실시간 인앱 view 가 곧 진실이자
산출물**이고, 클립보드 복사가 사용자의 완료 동작이다(ADR C 트랙 분기). 누락 토큰은 조용히 지우지 않고
``{{토큰}}`` 을 남겨 시끄럽게 신고한다(ADR E, txt 가 그 레퍼런스 구현).

코어 :func:`~hwpxfiller.core.text_render.render_record` 를 그대로 쓴다(순수 값 치환, 서식 안 함).
필드명=데이터 열명 직접 매칭(경량). PySide6 임포트 금지 — 위젯(txt_view)이 렌더만 한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.text_registry import TextTemplateRegistry
from ..core.text_render import RenderReport, render_record, template_fields
from ..data import source_for_path


@dataclass
class TokenState:
    """토큰 1개의 채움 상태(좌측 패널 배지) — 채움/빈 값/미입력."""

    name: str
    state: str  # "fill" | "blank" | "missing"


class TxtDraftViewModel:
    """즉시 기안 상태 — 선택 템플릿·데이터·레코드 + 렌더. 위젯은 이 API 만 호출한다."""

    def __init__(self, registry: TextTemplateRegistry):
        self.registry = registry
        self.template_name: "str | None" = None
        self.template_text: str = ""
        self.datasource = None
        self.records: "list[dict]" = []
        self.record_index: int = 0

    # ---------------------------------------------------------- 템플릿
    def template_names(self) -> "list[str]":
        return self.registry.names()

    def select_template(self, name: str) -> None:
        self.template_name = name
        self.template_text = self.registry.load(name).content()

    def set_template_text(self, text: str) -> None:
        """루트 밖 임의 텍스트(붙여넣기) — 이름 없는 세션 템플릿."""
        self.template_name = None
        self.template_text = text

    # ---------------------------------------------------------- 데이터
    def load_data(self, path: str) -> "list[dict]":
        source = source_for_path(path)
        records = source.records()
        if records:
            self.datasource = source
            self.records = records
            self.record_index = 0
        return records

    def record_count(self) -> int:
        return len(self.records)

    def current_record(self) -> "dict":
        if not self.records:
            return {}
        return self.records[self.record_index % len(self.records)]

    def step(self, delta: int) -> None:
        if self.records:
            self.record_index = (self.record_index + delta) % len(self.records)

    # ---------------------------------------------------------- 렌더
    def render(self) -> "tuple[str, RenderReport]":
        """현재 템플릿+레코드의 렌더 텍스트와 리포트(누락/빈값). view 가 곧 산출물."""
        return render_record(self.template_text, self.current_record())

    def token_states(self) -> "list[TokenState]":
        """템플릿 토큰별 상태 — 좌측 패널용. 데이터에 없으면 missing, 빈 값이면 blank."""
        rec = self.current_record()
        states: "list[TokenState]" = []
        for name in template_fields(self.template_text):
            if name not in rec:
                st = "missing"
            elif str(rec.get(name) or "").strip() == "":
                st = "blank"
            else:
                st = "fill"
            states.append(TokenState(name, st))
        return states
