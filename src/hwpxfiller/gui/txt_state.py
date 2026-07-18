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
from ..data import source_for_path, source_from_pool_item


@dataclass
class TokenState:
    """토큰 1개의 채움 상태(좌측 패널 배지) — 채움/빈 값/항목 없음(UD-20 어휘 경계).

    'missing'=데이터에 해당 항목(열) 부재 → '항목 없음'(실행 화면 '미입력'과 구분),
    'blank'=항목은 있으나 값이 빔 → '빈 값'.
    """

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

    def template_field_names(self) -> "list[str]":
        """현재 템플릿의 토큰명 목록 — 수기 1건 입력 폼(UD-25)이 소비한다."""
        return template_fields(self.template_text)

    # ---------------------------------------------------------- 데이터
    def load_data(self, path: str, *, sheet: "str | None" = None) -> "list[dict]":
        """파일 소스 겨눔 — ``sheet`` 는 사용자가 확정한 시트명(T2, None=기본 시트)."""
        source = source_for_path(path, sheet=sheet)
        records = source.records()
        if records:
            self.datasource = source
            self.records = records
            self.record_index = 0
        return records

    def load_pool_item(self, item, *, secret_store=None, fetcher=None) -> "list[dict]":
        """데이터셋 풀 항목(참조)을 복원해 겨눈다 — 실행 시점 재읽기가 곧 "싱크"(UD-25).

        실행 표면(run)의 풀 겨눔과 대칭이 되도록 txt 트랙에도 풀 경로를 연다.
        복원·키 주입(나라 항목의 SecretStore 상속)은 공용 팩토리
        :func:`~hwpxfiller.data.factory.source_from_pool_item` 가 관통한다 — txt 는 별도
        복원 로직을 갖지 않는다. 레코드 0건이면 상태 불변(위젯이 경고). ADR-C/H 상 txt 는
        실시간 view 가 진실이라 이 겨눔은 렌더 소스 확장일 뿐 게이트 도입이 아니다.
        """
        source = source_from_pool_item(item, secret_store=secret_store, fetcher=fetcher)
        records = source.records()
        if records:
            self.datasource = source
            self.records = records
            self.record_index = 0
        return records

    def set_acquired(self, datasource, records: "list[dict]") -> None:
        """이미 만들어진 소스·레코드를 직접 겨눈다 — 수기 1건(인라인) 등.

        run VM 의 ``set_acquired`` 와 같은 seam(RC-22) — datasource/records 직접
        대입 + 레코드 인덱스 리셋을 원자 진입점으로 봉합한다(스텝 잔존 인덱스 방지).
        """
        self.datasource = datasource
        self.records = list(records)
        self.record_index = 0

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
