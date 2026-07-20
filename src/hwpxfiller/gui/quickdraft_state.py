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

from dataclasses import dataclass

from ..core.text_registry import TextTemplateRegistry
from ..core.text_render import template_fields


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

    # ---------------------------------------------------------- 템플릿 소스(PR-2)
    def apply_library(self, name: str) -> None:
        """라이브러리 템플릿을 세션에 적용 — **참조가 아니라 사본**이다(결정 34).

        라이브러리 유래도 세션 사본이라 원문 편집이 자유롭고, 편집 순간 modified 로 강등된다
        (역반영은 명시 승격 「템플릿으로 저장」만 — 후속 PR). 여기선 사본을 깔기만 한다.
        """
        self._set_template("lib", name, self.registry.load(name).content())

    def apply_paste(self, text: str) -> None:
        """붙여넣은 서식을 세션에 적용 — 이름 없는 세션 사본(라이브러리 비저장, 결정 34)."""
        self._set_template("paste", None, text)

    def edit_source(self, text: str) -> None:
        """원문 편집 탭의 라이브 편집(결정 34) — 타이핑이 토큰 폼을 즉시 재구성한다.

        라이브러리 유래를 처음 고치는 순간 modified 로 정직 강등한다(칩-라이브 소유권 강등
        동형). 붙여넣기 유래는 이미 이름이 없어 강등 대상이 아니다(라이브러리 원본이 없음).
        """
        if self.origin == "lib" and not self.modified:
            self.modified = True
        self.template_text = text
        self._retokenize()

    def _set_template(self, origin: str, name: "str | None", text: str) -> None:
        self.origin = origin
        self.template_name = name
        self.template_text = text
        self.modified = False
        self._retokenize()

    def _retokenize(self) -> None:
        """토큰 목록 재구성 — **동명 토큰의 결속·값을 승계**하고 새 토큰만 초기화한다.

        원문 라이브 편집·템플릿 전환이 같은 경로를 탄다(결정 34): 이름이 같은 토큰은 사람이
        채운 값·결속을 잃지 않고, 사라진 토큰만 버려진다. 데이터 자동 결속(autoBind)은 PR-3
        이 이 뒤에 얹는다 — 지금은 순수 토큰 파싱·승계뿐이다.
        """
        prev = {t.name: t for t in self.tokens}
        self.tokens = [
            prev.get(name, QuickToken(name=name))
            for name in template_fields(self.template_text)
        ]

    # ---------------------------------------------------------- 토큰 값(PR-2)
    def set_token_text(self, name: str, text: str) -> None:
        """토큰 값 직접 입력(무결속 수기) — 결속된 토큰의 직접 수정 강등은 PR-3 이 얹는다."""
        for t in self.tokens:
            if t.name == name:
                t.text = text
                return

    def token_value(self, t: QuickToken) -> str:
        """토큰의 현재 값 — 무결속이면 수기 텍스트. 결속 값(데이터+표현형)은 PR-3 이 얹는다."""
        return t.text

    def values_record(self) -> "dict[str, str]":
        """미리보기·복사용 값 레코드 — :func:`~hwpxfiller.core.text_render.render_segments`
        에 그대로 넘긴다(토큰 정규식 재구현 금지, 파생경계 번역오류 상류 차단).

        **빈 수기 값은 레코드에서 뺀다** = 그 토큰은 missing 으로 렌더돼 ``{{토큰}}`` 원문이
        빨강으로 남고 복사에도 토큰 그대로 나간다(방향 A 미채움 의미론 = 아직 안 채운 자리).
        결속 토큰은 빈 값이어도 실어 blank(〈빈 값〉 = 데이터의 빈칸)로 가른다 — 이 갈림은
        PR-3 의 결속이 생겨야 유효하므로 지금은 무결속 경로만 탄다.
        """
        rec: "dict[str, str]" = {}
        for t in self.tokens:
            if t.col:  # 결속(PR-3) — 빈 값도 실어 blank 로 가른다
                rec[t.name] = self.token_value(t)
            else:  # 무결속 수기 — 빈 값이면 빼서 missing({{토큰}})으로
                v = t.text
                if v.strip() != "":
                    rec[t.name] = v
        return rec
