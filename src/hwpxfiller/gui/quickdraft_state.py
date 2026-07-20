"""빠른 기안 ViewModel — 작업의 휘발 쌍둥이(R-flow 블록 5, 결정 29). Qt 비의존(링1).

빠른 기안 = **아무것도 저장하지 않는 작업**: 템플릿(라이브러리 사본 또는 붙여넣기)과 선택적
데이터 소스를 세션 안에서만 결합한다. 영속 거처는 「작업」 세션 패널, 휘발 거처가 이 표면이다
(두 지속성 계급에 두 거처 — F36 지속성 축의 물화).

txt 트랙(:class:`~hwpxfiller.gui.txt_state.TxtDraftViewModel`)과의 차이는 **입도**다: txt 는
N 행 전-선언 큐(블록 3)라 템플릿 하나에 여러 레코드를 태워 걷지만, 빠른 기안은 **단건**이라
값=관계가 붕괴하는 지대(결정 30)에서 토큰마다 결속·표현형 상태를 직접 들고 있다. 그래서 이
VM 은 토큰 목록(:class:`QuickToken`)을 소유한다 — 선언 없는 휘발 매핑의 그릇.

PR-1 이 세션 그릇·초기화·템플릿 목록을, PR-2 가 템플릿 적용·토큰 재구성을 세웠고, PR-3(이
파일의 데이터 절반)이 **데이터 겨눔·제스처 결속·표현형 3층**을 얹는다. 휘발도 가드·복사는
PR-4 몫이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.identity_summary import identity_summary
from ..core.jamo import jamo_contains
from ..core.lint import similarity
from ..core.mapping import apply_transform
from ..core.text_registry import TextTemplateRegistry
from ..core.text_render import template_fields
from ..data import source_for_path, source_from_pool_item
from .filter_state import cell_text, sniff_column_kinds

#: 근사 제안 하한(결정 30) — :func:`~hwpxfiller.core.mapping.suggest_mappings` 의 자동 조준
#: 문턱과 같은 값을 쓴다. 빠른 기안은 이 문턱을 **자동 결속이 아니라 제안 표시**에만 쓴다:
#: 근사는 자동 금지 + 보이는 제안 원클릭이 규칙이라, 같은 점수대가 에디터에선 초안 매핑을,
#: 여기선 버튼 하나를 낳는다(지속성 축 비대칭 1호 — 결정 35).
SUGGEST_THRESHOLD = 0.6

#: 자모 부분일치를 근사 신호로 인정할 최소 길이. 한 글자(「명」·「일」)는 거의 모든 열에
#: 포함돼 제안이 소음이 된다 — 짧은 이름은 문자 유사도만 본다.
_JAMO_MIN_LEN = 2


@dataclass
class QuickToken:
    """빠른 기안 토큰 한 개의 결속·표현형 상태(선언 없는 휘발 매핑, 결정 30).

    - ``col``: 결속된 데이터 열 이름(``None`` = 무결속 = 수기/빈칸).
    - ``fmt_kind``/``fmt_code``: 표현형(결정 31의 자동 추측·드롭다운 정정). ``format_engine``
      프리셋 키와 1:1 이라 승격 시 그대로 매핑 초안으로 이관된다.
    - ``edited``: 결속된 값을 사람이 직접 고쳤는가(표현형 3층의 최하층 — 사람 소유 강등).
    - ``text``: 무결속(수기) 또는 직접 수정 시의 평문 값. 결속·무수정이면 값은 데이터에서
      매번 사영하므로 여기 담지 않는다(값을 캐시하면 행 교체 시 조용한 stale).
    - ``detached``: 사람이 결속을 **손으로 끊었는가**. 자동 결속·제안은 이 토큰을 건너뛴다 —
      끊자마자 다음 타이핑(원문 편집 → 토큰 재구성)이 같은 열을 도로 붙이면 사람의 명시
      제스처가 조용히 뒤집힌다(고효율 리뷰). 데이터를 갈면 다시 후보가 된다.
    """

    name: str
    col: "str | None" = None
    fmt_kind: str = "text"
    fmt_code: str = ""
    edited: bool = False
    text: str = ""
    detached: bool = False


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
        # 열 유형(표현형 3층의 1층 자동 추측) — 값 스니핑 단일 출처를 필터와 공유한다.
        # 빠른 기안엔 확정 스키마가 없으니 힌트 없는 스니핑뿐이고, 오판의 안전 방향도
        # 거기서 정해진 대로 text 다(관대 파서 승격 금지).
        self.col_kinds: "dict[str, str]" = {}
        # 직전 데이터 교체에서 열이 없어져 평문 동결된 토큰 이름 — 표면이 경보로 재진술한다.
        self.frozen_cols: "list[str]" = []
        # 행 식별 요약 열(#88 결정 37) — 행 스테퍼가 "지금 몇 번째 행인지"를 사람 어휘로
        # 재진술할 때 쓴다. 겨눔 시점에 1회 판정해 들고 있는다(스냅샷마다 재판정 금지).
        self.id_columns: "list[str]" = []

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
        채운 값·결속을 잃지 않고, 사라진 토큰만 버려진다. 데이터를 겨눈 상태라면 **새로
        생긴 토큰만** 정확 일치 자동 결속을 받는다(승계된 토큰은 이미 소유자가 있다) —
        타이핑으로 토큰을 하나 더 쓰는 순간 그 자리가 데이터에서 채워진다.
        """
        prev = {t.name: t for t in self.tokens}
        self.tokens = [
            prev.get(name, QuickToken(name=name))
            for name in template_fields(self.template_text)
        ]
        if self.has_data():
            self.autobind()

    # ------------------------------------------------------ 데이터 겨눔(PR-3)
    def load_data(self, path: str, *, sheet: "str | None" = None) -> "list[dict]":
        """임의 파일 겨눔(결정 34의 비오염 데이터 판) — 무등록 임시 참조, 라이브러리 무관.

        ``sheet`` = 웹에서 확정한 시트명(다중 시트 확정 게이트 #33, None=CSV·단일 시트).
        레코드 0건이면 **상태 불변**(호출측이 시끄럽게 재진술) — 빈 데이터로 세션을 갈아
        엎지 않는다(txt·작업 표면 동형).
        """
        source = source_for_path(path, sheet=sheet)
        records = source.records()
        if records:
            self.install_data(source, records, label=Path(path).name, kind="file")
        return records

    def load_pool_item(self, item, *, secret_store=None, fetcher=None) -> "list[dict]":
        """등록 데이터(풀) 겨눔 — 복원은 공용 팩토리 관통(별도 복원 로직 불설치).

        겨눔 시점 재읽기가 곧 "싱크"다(txt 동형). 0건이면 상태 불변.
        """
        source = source_from_pool_item(item, secret_store=secret_store, fetcher=fetcher)
        records = source.records()
        if records:
            self.install_data(source, records, label=item.name, kind="pool")
        return records

    def install_data(self, datasource, records: "list[dict]", *, label: str, kind: str) -> None:
        """데이터 겨눔의 **원자 세엄**(txt ``set_acquired`` 선례, RC-22 부분 대입 방지).

        불변식 ``datasource is not None ⟺ data_kind != ''`` 은 겨눔 상태를 이 한 진입점
        에서만 변이해 성립시킨다(해제는 :meth:`clear_data`). 파일·등록 데이터 두 유래가
        같은 세엄을 타므로(결정 34의 데이터 소스 이원) 한쪽만 리셋을 빠뜨리는 조용한
        드리프트가 구조로 막힌다.

        직후 :meth:`autobind` 가 **정확 일치만** 자동 결속한다 — 근사는 자동 금지가 규칙이라
        제안으로만 뜬다(결정 30).

        **교체 시 죽은 결속 처분(고효율 리뷰 P1)**: 새 데이터에 없어진 열을 가리키던 결속은
        그대로 두면 값이 조용히 사라지고, 그 자리가 blank(〈빈 값〉 = 데이터의 빈칸)로 렌더돼
        **거짓을 말한다**(열 자체가 없는데 "빈칸"이라 함). 그래서 교체 순간 그 결속들은 해제와
        같은 규율로 **평문 동결**하고, 이름을 :attr:`frozen_cols` 에 남겨 표면이 알린다
        (조용한 소실 금지 — 확인이 불가능한 자리이므로 경보 쪽으로 간다). 살아남은 결속은
        열 유형을 **다시 스니핑**한다(옛 데이터의 amount 가 새 text 열에 눌어붙지 않게).
        """
        rows = list(records)
        columns = list(rows[0].keys()) if rows else []
        # **동결이 먼저다** — 얼릴 값은 옛 데이터에서 사영해야 한다. 새 레코드를 먼저 깔면
        # 없어진 열을 새 행에서 읽어 빈 문자열이 굳는다(동결이 곧 소실이 되는 순서 함정).
        frozen: "list[str]" = []
        for t in self.tokens:
            if t.col and t.col not in columns:
                self._freeze(t)
                frozen.append(t.name)
        self.datasource = datasource
        self.records = rows
        self.columns = columns
        self.col_kinds = sniff_column_kinds(self.records)
        self.id_columns = identity_summary(self.records, self.columns).columns
        self.data_label = label
        self.data_kind = kind
        self.row_idx = 0
        self.frozen_cols = frozen
        for t in self.tokens:
            # 「이 열은 쓰지 않겠다」는 사람의 결정은 옛 데이터에 대한 것이므로 새 데이터에선
            # 다시 자동 결속 후보가 된다(관계가 새로 생겼다).
            t.detached = False
            if t.col:  # 살아남은 결속 — 열 유형은 새 데이터로 다시 스니핑(옛 유형 눌어붙기 차단)
                t.fmt_kind = self.col_kinds.get(t.col, "text")
        self.autobind()

    def clear_data(self) -> None:
        """데이터 해제 — 결속 값은 **평문으로 동결**한다(결정 30).

        해제가 값을 지우면 사람이 보고 있던 문서가 조용히 비는데, 빠른 기안은 "지금 화면이
        곧 산출물"인 표면이라 그 소실이 곧 결과 소실이다. 그래서 결속은 끊되 마지막으로
        보이던 값(표현형 적용 후 평문)을 수기 값으로 승계한다 — 표지는 「직접 입력」으로
        정직하게 바뀐다.
        """
        for t in self.tokens:
            if t.col:
                self._freeze(t)
        self.datasource = None
        self.records = []
        self.columns = []
        self.col_kinds = {}
        self.id_columns = []
        self.data_label = ""
        self.data_kind = ""
        self.row_idx = 0
        self.frozen_cols = []  # 교체 경보는 그 교체에 한한다(해제하면 재진술할 대상도 없다)

    def _freeze(self, t: QuickToken) -> None:
        """결속 해제 1건 — 현재 값을 평문 수기 값으로 동결하고 표현형 상태를 되돌린다."""
        t.text = self.token_value(t)
        t.col = None
        t.edited = False
        t.fmt_kind = "text"
        t.fmt_code = ""

    def has_data(self) -> bool:
        """겨눔 존재 — 단일 진실(``datasource``)에서만 파생한다(별도 bool 저장 금지)."""
        return self.datasource is not None

    def record_count(self) -> int:
        return len(self.records)

    def set_row(self, index: int) -> None:
        """행 재겨눔(결정 32) — 범위 밖은 조용히 자르지 않고 시끄럽게 거절한다.

        결속·무수정 토큰은 값이 관계에서 다시 사영되므로 **조용히 재생성**되고, 직접 수정·
        무결속 수기 값은 그대로 남는다(혼합) — 그 혼합이 보이지 않는 위험이라 표면이
        :meth:`carry_over` 로 사전 고지한다.
        """
        if not self.records:
            raise ValueError("겨눈 데이터가 없습니다 — 행을 고를 수 없습니다.")
        if not 0 <= index < len(self.records):
            raise ValueError(f"행 번호가 범위를 벗어났습니다: {index + 1}")
        self.row_idx = index

    def step_row(self, delta: int) -> None:
        """행 한 칸 이동 — 양끝에서는 제자리(표면의 스테퍼 버튼이 이미 비활성인 자리).

        ``delta`` 를 서버가 현재 행에 더한다: 표면이 계산해 보내면 연타가 옛 번호 위에
        쌓여 클릭이 삼켜진다(판정은 Python 이 지금).
        """
        if not self.records:
            raise ValueError("선택한 데이터가 없습니다 — 행을 옮길 수 없습니다.")
        self.set_row(max(0, min(len(self.records) - 1, self.row_idx + delta)))

    def current_record(self) -> "dict":
        return self.records[self.row_idx] if self.records else {}

    def row_label(self) -> str:
        """현재 행의 사람 어휘 재진술 — 식별 요약 열의 값 병기(없으면 빈 문자열)."""
        rec = self.current_record()
        vals = [v for c in self.id_columns if (v := cell_text(rec, c).strip())]
        return " · ".join(vals)

    # ------------------------------------------------------ 제스처 결속(PR-3)
    def autobind(self) -> None:
        """정확 일치 자동 결속(결정 30) — **수기 텍스트는 존중**한다.

        이름이 토큰과 정확히 같은 열만 자동으로 붙는다. 사람이 이미 값을 쳐 넣은 토큰은
        건드리지 않는다(자동이 사람 입력을 덮으면 그게 바로 조용한 소실). 공백 변이·부분
        일치는 여기서 붙지 않고 :meth:`suggest_for` 의 제안으로 넘어간다.
        """
        for t in self.tokens:
            if t.col or t.detached or t.text.strip() != "":
                continue
            if t.name in self.columns:
                self.bind(t.name, t.name)

    def token(self, name: str) -> "QuickToken | None":
        """이름으로 토큰 1개 — 표면·컨트롤러가 상태를 묻는 단일 접근자."""
        for t in self.tokens:
            if t.name == name:
                return t
        return None

    def bind(self, name: str, col: "str | None") -> None:
        """토큰 결속·해제 — 결속 시 표현형 1층(열 유형 자동 추측)을 함께 깐다.

        ``col=None``(또는 빈 문자열)이면 해제이며, 데이터 해제와 같은 **평문 동결**이다
        (한 토큰만 손으로 떼어내도 값이 증발하지 않는다). 손으로 끊은 사실은 ``detached``
        로 남아 자동 결속·제안이 되붙이지 않는다.

        결속은 그 자리에 있던 **수기 값을 덮는다** — 되돌릴 수 없는 덮어쓰기라 표면이 먼저
        확인을 받는다(:meth:`bind_overwrites`). 여기서 조용히 막으면 사람이 고른 열이 안
        붙는 반대쪽 침묵이 되므로, 판정만 내주고 실행은 확인 뒤에 온다.
        """
        for t in self.tokens:
            if t.name != name:
                continue
            if not col:
                if t.col:
                    self._freeze(t)
                t.detached = True
                return
            if col not in self.columns:
                raise ValueError(f"데이터에 없는 열입니다: {col}")
            t.col = col
            t.detached = False
            t.edited = False
            t.text = ""
            t.fmt_kind = self.col_kinds.get(col, "text")
            t.fmt_code = ""
            return

    def bind_overwrites(self, name: str) -> str:
        """결속이 덮어쓸 수기 값(없으면 빈 문자열) — 확인 문안이 **실제 사라질 값**을 인용한다."""
        t = self.token(name)
        return t.text if (t is not None and not t.col and t.text.strip() != "") else ""

    def set_fmt(self, name: str, code: str) -> None:
        """표현형 2층 — 드롭다운 정정(결정 31). 유형은 열이 정하고 코드만 사람이 고른다.

        유형까지 사람이 바꾸는 층은 두지 않는다: 스니핑이 보수적이라(전 값이 맞아야 승격)
        오판의 방향이 text 한쪽이고, 유형 재선언은 승격 뒤 에디터 매핑의 소관이다
        (승격 = 엄격성 국경, 결정 31). 유보로 남기고 여기선 늘리지 않는다.
        """
        for t in self.tokens:
            if t.name == name:
                t.fmt_code = code
                return

    def revert_token(self, name: str) -> None:
        """직접 수정 → 자동 복귀(3층 강등의 되돌리기) — 결속은 유지, 사람 값만 버린다."""
        for t in self.tokens:
            if t.name == name and t.col:
                t.edited = False
                t.text = ""
                return

    def suggest_for(self, t: QuickToken) -> "str | None":
        """무결속 토큰에 대한 근사 열 제안 1개(없으면 ``None``) — 자동 적용 금지.

        문자 유사도(에디터 자동 조준과 같은 :func:`~hwpxfiller.core.lint.similarity`)를
        기본으로 하고, 자모 부분일치(블록 4 유틸 공유 — 「사업명」 ⊂ 「사업명(발주)」)를
        근사 하한으로 인정한다. 한 글자 토큰은 자모 신호를 쓰지 않는다(소음).
        """
        if t.col or t.detached or not self.columns:
            return None  # 손으로 끊은 자리에 같은 열을 다시 권하지 않는다(제안의 반복 = 소음)
        best, score = None, 0.0
        for col in self.columns:
            s = similarity(t.name, col)
            if s < SUGGEST_THRESHOLD and self._jamo_near(t.name, col):
                s = SUGGEST_THRESHOLD
            if s > score:
                best, score = col, s
        return best if best is not None and score >= SUGGEST_THRESHOLD else None

    @staticmethod
    def _jamo_near(name: str, col: str) -> bool:
        """자모 분해 부분일치(양방향) — 짧은 이름은 제외(한 글자는 어디에나 들어맞는다)."""
        if len(name.strip()) < _JAMO_MIN_LEN or len(col.strip()) < _JAMO_MIN_LEN:
            return False
        return jamo_contains(col, name) or jamo_contains(name, col)

    def carry_over(self) -> "dict[str, list[str]]":
        """행 재겨눔·데이터 교체·해제 시 **재생성되지 않는 값**의 분류(결정 32의 3분류).

        - ``edited``: 결속인데 사람이 직접 고친 값 — 새 행에서도 그대로 남아 **혼합**이 된다.
        - ``manual``: 무결속 수기 값 — 유지되며 고지 대상.

        결속·무수정은 관계에서 조용히 재생성되므로 여기 담기지 않는다. 표면은 이 분류로
        가드 문안을 합성한다(판정은 링1, 문안 합성은 컨트롤러).
        """
        return {
            "edited": [t.name for t in self.tokens if t.col and t.edited],
            "manual": [t.name for t in self.tokens if not t.col and t.text.strip() != ""],
        }

    # ------------------------------------------------- 휘발도 가드(PR-4, 결정 32·34)
    def clear_template(self) -> None:
        """템플릿만 비우고 **데이터 겨눔은 유지**한다 — 빈 붙여넣기 확정의 착지.

        :meth:`fresh` 와 다르다: 빈 붙여넣기를 fresh 로 처리하면 (전환 가드가 "선택한
        데이터는 이어집니다"라 약속한) 겨눔까지 조용히 버려 confirm-or-alarm 을 어긴다(리뷰
        F2). 데이터 슬롯은 헤더라 템플릿 없이도 서므로(빈손 카드 + 데이터 겨눔) 겨눔을 남긴
        상태가 정합하다. 토큰이 없어지니 사람이 넣은 값은 사라진다(빈 템플릿엔 그 자리가 없다).
        """
        self.origin = None
        self.template_name = None
        self.template_text = ""
        self.modified = False
        self.tokens = []
        self.frozen_cols = []

    def session_loss(self) -> "dict":
        """가드 문안 재료 + 무장 판정 성분 — 전환·새 기안이 버리는 것의 분류(**판정만**).

        carry_over(값이 남는 곳)와 대비: 이건 **세션이 사라질 때** 무엇을 잃는지다. 토큰
        순회는 **여기 한 번뿐**이고(리뷰 F6), 컨트롤러 가드는 이 dict 만으로 무장을 연역한다.

        ``paste_body``: 붙여넣기 유래는 라이브러리에 없어 **재선택 복원 경로가 없다** — 빈손이
        아닌 한 그 자체가 버려지는 노동이다(리뷰 F1). ``modified`` 는 라이브러리 유래의 원문
        수정(재선택하면 되살아나지 않는 편집).
        """
        return {
            "origin": self.origin,
            "template_name": self.template_name,
            "modified": self.modified,
            # 붙여넣은 원문은 재선택 복원이 불가하므로 그 존재 자체가 버려지는 노동이다.
            "paste_body": self.origin == "paste" and self.template_text.strip() != "",
            "data_label": self.data_label if self.has_data() else "",
            "manual": [t.name for t in self.tokens if not t.col and t.text.strip() != ""],
            "edited": [t.name for t in self.tokens if t.col and t.edited],
        }

    # ---------------------------------------------------------- 토큰 값(PR-2)
    def set_token_text(self, name: str, text: str) -> None:
        """토큰 값 직접 입력 — 결속 토큰이면 **사람 소유로 강등**한다(표현형 3층 최하층).

        강등은 되돌릴 수 있다(:meth:`revert_token`) — 막다른 강등은 금지(결정 31).
        """
        for t in self.tokens:
            if t.name == name:
                t.text = text
                if t.col:
                    t.edited = True
                return

    def token_value(self, t: QuickToken) -> str:
        """토큰의 현재 값 — 결속·무수정이면 데이터에서 매번 사영(캐시 금지, 행 교체 stale 차단).

        사영 = 현재 행의 열 값에 표현형(유형+프리셋 코드)을 입힌 평문. 서식 적용은 매핑과
        **같은 단일 진입점**(:func:`~hwpxfiller.core.mapping.apply_transform`)이라 승격 시
        값이 달라지지 않는다(인라인 포매터 불설치 — D-6 폐기, 결정 31).
        """
        if t.col and not t.edited:
            return apply_transform(t.fmt_kind, value=cell_text(self.current_record(), t.col), fmt=t.fmt_code)
        return t.text

    def values_record(self) -> "dict[str, str]":
        """미리보기·복사용 값 레코드 — :func:`~hwpxfiller.core.text_render.render_segments`
        에 그대로 넘긴다(토큰 정규식 재구현 금지, 파생경계 번역오류 상류 차단).

        **빈 수기 값은 레코드에서 뺀다** = 그 토큰은 missing 으로 렌더돼 ``{{토큰}}`` 원문이
        빨강으로 남고 복사에도 토큰 그대로 나간다(방향 A 미채움 의미론 = 아직 안 채운 자리).
        결속 토큰은 빈 값이어도 실어 blank(〈빈 값〉 = 데이터의 빈칸)로 가른다 — "아직 안
        채운 자리"와 "데이터가 비어 있는 자리"는 다른 사실이고, 표지 삼분이 그 둘을 다른
        색으로 말한다(결정 22·33).
        """
        rec: "dict[str, str]" = {}
        for t in self.tokens:
            if t.col and not t.edited:  # 결속·무수정 — 빈 값도 실어 blank(데이터의 빈칸)로
                rec[t.name] = self.token_value(t)
            else:
                # 무결속 수기 + **사람이 비운 결속 값**: 빈 값이면 빼서 missing({{토큰}})으로.
                # 사람이 지운 자리를 blank(「데이터가 비어 있다」)로 그리면 표지가 빈칸의
                # 임자를 거짓으로 말한다(표지 삼분은 누가 비웠는지를 색으로 가른다).
                v = t.text
                if v.strip() != "":
                    rec[t.name] = v
        return rec
