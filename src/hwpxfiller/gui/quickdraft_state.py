"""빠른 기안 ViewModel — 작업의 휘발 쌍둥이(R-flow 블록 5, 결정 29). Qt 비의존(링1).

빠른 기안 = **아무것도 저장하지 않는 작업**: 템플릿(라이브러리 사본 또는 붙여넣기)과 선택적
데이터 소스를 세션 안에서만 결합한다. 영속 거처는 「작업」 세션 패널, 휘발 거처가 이 표면이다
(두 지속성 계급에 두 거처 — F36 지속성 축의 물화).

txt 트랙(:class:`~hwpxfiller.gui.txt_state.TxtDraftViewModel`)과의 차이는 **입도**다: txt 는
N 행 전-선언 큐(블록 3)라 템플릿 하나에 여러 레코드를 태워 걷지만, 빠른 기안은 **단건**이라
값=관계가 붕괴하는 지대(결정 30)에서 토큰마다 결속·표현형 상태를 직접 들고 있다. 그래서 이
VM 은 토큰 목록(:class:`QuickToken`)을 소유한다 — 선언 없는 휘발 매핑의 그릇.

이 슬라이스(PR-1)는 세션 그릇·초기화·템플릿 목록만 세운다. 템플릿 적용·토큰 재구성(PR-2),
데이터 결속·표현형 3층(PR-3)은 뒤 PR 이 이 그릇 위에 얹는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.text_registry import TextTemplateRegistry


@dataclass
class QuickToken:
    """빠른 기안 토큰 한 개의 결속·표현형 상태(선언 없는 휘발 매핑, 결정 30).

    - ``col``: 결속된 데이터 열 이름(``None`` = 무결속 = 수기/빈칸).
    - ``fmt_kind``/``fmt_code``: 표현형(결정 31의 자동 추측·드롭다운 정정). ``format_engine``
      프리셋 키와 1:1 이라 승격 시 그대로 매핑 초안으로 이관된다.
    - ``edited``: 결속된 값을 사람이 직접 고쳤는가(표현형 3층의 최하층 — 사람 소유 강등).
    - ``text``: 무결속(수기) 또는 직접 수정 시의 평문 값. 결속·무수정이면 값은 데이터에서
      매번 사영하므로 여기 담지 않는다(값을 캐시하면 행 교체 시 조용한 stale).
    """

    name: str
    col: "str | None" = None
    fmt_kind: str = "text"
    fmt_code: str = ""
    edited: bool = False
    text: str = ""


class QuickDraftViewModel:
    """빠른 기안 세션 상태 — 템플릿 사본·토큰·데이터 소스. 컨트롤러는 이 API 만 호출한다.

    세션 전체가 휘발이다(결정 29): 남기려면 승격 동사(후속 PR)로만 동결한다. ``fresh`` 는
    생성자와 「새 기안」(결정 32)이 공유하는 단일 초기 상태라 두 경로가 갈라지지 않는다.
    """

    def __init__(self, registry: TextTemplateRegistry) -> None:
        self.registry = registry
        self.fresh()

    def fresh(self) -> None:
        """세션 원자 초기화 — 템플릿·토큰·데이터를 모두 비운다(휘발 그릇 리셋)."""
        # 템플릿 유래: None(빈손) | 'lib'(라이브러리 사본) | 'paste'(붙여넣기). 둘 다 세션
        # 사본이라 원문 편집이 자유롭고, 편집 순간 modified 로 정직 강등한다(결정 34).
        self.origin: "str | None" = None
        self.template_name: "str | None" = None
        self.template_text: str = ""
        self.modified: bool = False
        self.tokens: "list[QuickToken]" = []
        # 데이터 소스 이원(결정 34): 등록 데이터(자산)와 임의 파일(무등록 임시 겨눔). 단건
        # 포커스라 row_idx 하나만 본다(txt 의 N 행 선택·큐와 대비).
        #
        # 겨눔 상태의 **단일 진실은 datasource**(로드된 소스 객체, 미겨눔=None) — has_data 는
        # 이 하나에서 파생한다(별도 bool 저장 금지). data_kind 는 겨눔의 **유래**(등록/파일)일
        # 뿐 존재 여부의 사본이 아니다(이름을 datasource 와 헷갈리지 않게 _kind 로 둔다). 둘의
        # 불변식 `datasource is not None ⟺ data_kind != ''` 는 PR-3 이 겨눔/해제를 **원자
        # 세엄**(txt 의 set_acquired 선례, RC-22 부분 대입 방지) 하나로만 변이해 성립시킨다 —
        # 한쪽만 세팅하는 조용한 드리프트를 구조로 막는다.
        self.datasource = None
        self.columns: "list[str]" = []
        self.records: "list[dict]" = []
        self.data_label: str = ""
        self.data_kind: str = ""  # ''(미겨눔) | 'pool' | 'file' — 겨눔 유래(존재 여부 아님)
        self.row_idx: int = 0

    def template_names(self) -> "list[str]":
        """라이브러리 템플릿 이름 목록 — 슬롯 드롭다운이 소비(txt·템플릿 관리와 공유 레지스트리)."""
        return self.registry.names()
