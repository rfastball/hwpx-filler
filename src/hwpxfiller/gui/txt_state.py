"""txt 즉시 기안 ViewModel — 템플릿 + 데이터 소스 보유(Qt 비의존, 링1).

트랙 이원성(DECISIONS §): txt 트랙은 외부 권위 렌더러가 없어 **실시간 인앱 view 가 곧 진실이자
산출물**이고, 클립보드 복사가 사용자의 완료 동작이다(ADR C 트랙 분기). 누락 토큰은 조용히 지우지 않고
``{{토큰}}`` 을 남겨 시끄럽게 신고한다(ADR E, txt 가 그 레퍼런스 구현).

이 VM 은 템플릿 선택·데이터 소스 겨눔·레코드 목록만 소유한다. 렌더·레코드 커서(자유 순회)는
:class:`~hwpxfiller.webapp.draft_session.DraftSessionMixin` 가 전-선언 큐(작업점 카드, R-flow 블록 3)로
대체했으므로 여기서 들고 있지 않는다 — 렌더는 컨트롤러가 :func:`~hwpxfiller.core.text_render.
render_record`/``render_segments`` 를 작업점 레코드에 직접 적용한다.
"""
from __future__ import annotations

from ..core.text_registry import TextTemplateRegistry
from ..core.text_render import template_fields
from ..data import source_for_path, source_from_pool_item


class TxtDraftViewModel:
    """즉시 기안 상태 — 선택 템플릿·데이터 소스·레코드 목록. 컨트롤러는 이 API 만 호출한다."""

    def __init__(self, registry: TextTemplateRegistry):
        self.registry = registry
        self.template_name: "str | None" = None
        self.template_text: str = ""
        self.datasource = None
        self.records: "list[dict]" = []

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
        return records

    def set_acquired(self, datasource, records: "list[dict]") -> None:
        """이미 만들어진 소스·레코드를 직접 겨눈다 — 수기 1건(인라인) 등.

        run VM 의 ``set_acquired`` 와 같은 seam(RC-22) — datasource/records 직접 대입을
        원자 진입점으로 봉합한다(부분 대입 방지).
        """
        self.datasource = datasource
        self.records = list(records)

    def record_count(self) -> int:
        return len(self.records)
