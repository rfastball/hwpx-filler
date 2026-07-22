"""필터 선언 상태 모델 — Qt·웹 비의존 순수 파이썬(R-flow 블록 4, 결정 23~25).

「작업」 세션 패널 데이터 존의 **화면 편집 주체 = 필터 상태 하나**(결정 23)의 그 상태다.
사양 정본은 시안 ``docs/r-flow-mockups/block4-filter-crystallize-demo.html`` 의 상태 기계
(``colC``/``grp``/``colPass``/``grpPass``/``recomputeBranches``/``colValues``/``fullDesc``) —
충실 이식 + 라운드에서 미결이던 3항의 확정(2026-07-19 사용자 택일)을 반영한다.

## 계약(확정 결정의 사상)

- **열-조건 = 열 머리 소유**(결정 23·25): 값 체크리스트(같은 열 OR) + 자모 부분일치
  텍스트 + 범위 조건(일자·금액 열만)이 열마다 동거. 열 간은 AND — 엑셀 동형.
- **(빈값)은 일급 값**(결정 23): 빈 문자열 ``""`` 이 체크리스트의 정식 값이다 — 없으면
  여집합("비고가 빈 행")을 표현할 수 없다. "조용한 빈칸 금지"의 필터 판.
- **전열 검색 = 재현 OR 그룹**(결정 23): 검색어는 "실제 매치가 있는 열"에만 가지를 세운
  OR 그룹으로 번역된다(전체를 찾고, 전체를 재현하는 조건을 적용). 검색창 = 그룹 편집기.
  가지 후보에서 일자·금액 열은 제외(범위 문법 소관 — 시안 동형). **마지막 가지를 쳐내면
  그룹이 해산된다**(시안 동형 — 전 가지 프루닝 = 검색 해제 의사, 빈 화면 함정 아님).
- **자모 부분일치**(결정 23): 열 텍스트·전열 검색 모두 :mod:`~hwpxfiller.core.jamo` 소비
  (「행복도ㅅ」 단계 매치). 입력은 양끝 공백 트리밍(시안 동형 — 보이지 않는 문자로 행이
  사라지지 않게). 하이라이트는 :meth:`FilterView.segments` 가 **파이썬에서 원문을 잘라
  세그먼트로** 준다 — 매치 인덱스를 웹으로 건네지 않는다(jamo PR-1 리뷰 계약: 코드포인트/
  UTF-16 파생경계 번역오류의 상류 차단). 색칠 우선순위 = 전열 검색 → 열 텍스트(시안
  ``mark`` 동형 — 검색어가 먼저).
- **범위 조건 = 엑셀 사용자 지정 자동 필터 동형**(2026-07-19 확정): 비교 연산자 6종
  (=·≠·>·≥·<·≤) + 최대 2절 AND/OR 결합. **동적 날짜 프리셋(오늘·지난주 등)은 제외**
  (벽시계 상대 정의는 재현 재진술과 마찰 — 같은 정의가 날마다 다른 행을 매치).
- **필터는 보기만 바꾼다**(결정 3): 이 모델은 선택(:class:`~hwpxfiller.gui.selection_state.
  SelectionModel`)을 모른다 — 선택은 필터를 관통하고, 필터 밖 선택의 스트립 표현은 표면
  소관이다.

## 값 해석 — 표시 파서 재사용 + 선언 지점만 엄격(고효율 리뷰 반영)

셀 해석은 표시형과 같은 관대 파서(:func:`~hwpxfiller.core.format_engine.parse_number`/
``parse_dt``) — 표시가 읽는 대로 비교한다(값 해석 단일 출처, 파싱 불가 셀=불매치=엑셀
동형). 단 **사용자 선언 지점은 관대하면 안 된다** — 관대 파서는 「1억」을 1로, 「제2026-15호」
를 날짜로 조용히 오독한다(정의줄은 원문을 재진술하므로 선언과 술어의 어긋남이 안 보인다):

- **범위 피연산자 = 설정 시점 엄격 검증 + 시끄러운 거절**(엑셀은 조용히 문자열 비교로
  강등하지만 그건 조용한 추측이다). 금액은 숫자·콤마·소수점(·원)만, 날짜는 형태 검사(선두 y-m-d·압축 8자리).
- **날짜 비교 입도 = 피연산자가 선언한 만큼**: 시각 없는 피연산자(「2026-07-15」)는 날짜
  입도로 비교한다 — 시각 포함 셀(``2026-07-15 14:00``)이 「≤ 당일」에서 자정 비교로
  조용히 탈락하는 오류의 차단(엑셀 원시 직렬값 비교와의 의도적 편차). 시각을 쓴
  피연산자는 분 입도 그대로.
- **금액 스니핑도 같은 엄격 판정**: 관대 파서로 승격하면 「1차」·「A-1」·「3층」 열이 금액
  열이 되어 전열 검색에서 침묵 배제된다 — 유형 오판의 안전 방향은 text 뿐이다.

## 라운드 미결 3항의 확정(2026-07-19 택일 — 시안 §3 "경합과 미결"의 닫힘)

- **프루닝 지속성 = 텍스트 수명**: 쳐낸 가지는 검색 텍스트를 고칠 때(=그룹 재정의)만
  복귀한다. 가지 집합 자체는 평가 시점 라이브 산출(저장 안 함)이라 열-조건 편집으로 매치
  지형이 변해도 stale 가지가 없고, 프루닝만 텍스트 수명으로 기억한다. (시안 데모는 열
  편집에도 재계산으로 프루닝이 풀렸으나 확정 문언이 텍스트 수명 — 의도적 정밀화.)
- **연속 검색 = 그룹 교체**: 그룹은 항상 최대 1개, 새 검색어는 재정의다. 첫 검색을
  보존하려면 열-조건으로 선언하고 새로 검색한다(AND 결합).
- **가지 1 정규화 안 함**: 가지 1개짜리 그룹은 열-조건과 동치지만 편집 주체가 다르다
  (그룹=검색창, 열-조건=열 머리) — 자동 강등은 편집 주체를 조용히 갈아치운다. 그룹으로
  잔존하고 정의줄이 동치를 자연 표현한다.

## 시안과의 선언된 문안 편차 1건

매치 없는 검색이 활성일 때 정의줄에 ``검색 「X」 — 매치 없음`` 을 남긴다(시안 fullDesc 는
그룹을 통째 생략). 빈 화면의 이유를 정의줄이 재진술해야 막다른 침묵이 아니다(confirm-or-
alarm) — 칩 줄·게이트가 같은 문안을 나른다.

## 스코프(세션 생존, 결정 24)와 소비 형태

인스턴스는 세션(작업×데이터) 수명 — 행 재방문·레일 이동에 생존, 작업 전환·데이터 교체
시 컨트롤러가 새로 만든다(전환 시점 인계는 블록 4 본안 결정 28 = PR-4 소관). 정의줄
문안은 칩 줄·게이트 재진술·「전체 선택」 담보가 공유하는 **단일 출처**다(결정 4). 층화
표본(결정 5)은 :meth:`FilterView.stratified_sample`.

**렌더 경로는 반드시 :meth:`FilterModel.view` 로 평가한다** — 뷰가 가지 집합을 1회
산출·캐시해 셀마다 전 코퍼스를 재주사하는 비용(행×열×자모 분해가 셀 수만큼 곱해지는
준제곱 렌더)을 차단한다(고효율 리뷰 반영). 모델의 동명 메서드는 단발 질의용 위임이다.

회귀 = ``tests/test_filter_state.py``. 표면 배선(열 테이블·아이콘 패널·스트립)은 PR-2b.
"""
from __future__ import annotations

import operator
import re
from dataclasses import dataclass
from typing import Iterable

from ..core.format_engine import parse_dt, parse_number
from ..core.jamo import jamo_contains, jamo_find

__all__ = [
    "KIND_TEXT",
    "KIND_AMOUNT",
    "KIND_DATE",
    "RANGE_OP_LABELS",
    "RangeClause",
    "RangeCondition",
    "cell_text",
    "sniff_column_kinds",
    "FilterModel",
    "FilterView",
]

# 열 유형 — 범위 문법 자격(일자·금액)과 전열 검색 가지 후보(텍스트만)를 가른다.
KIND_TEXT = "text"
KIND_AMOUNT = "amount"
KIND_DATE = "date"

# 비교 연산자(엑셀 사용자 지정 동형 6종) — 정의줄 표시 기호의 단일 출처.
RANGE_OP_LABELS = {"eq": "=", "ne": "≠", "gt": ">", "ge": "≥", "lt": "<", "le": "≤"}

# 결합자 표시 — 정의줄 재진술(∧/∨)용.
_JOINER_LABELS = {"and": "∧", "or": "∨"}

# 비교 연산자 실행 함수 — operator 모듈 재사용(6종 전부 계산하는 dict 리터럴 대신
# 해당 연산 하나만 평가, 타입도 정합).
_RANGE_OPS = {
    "eq": operator.eq, "ne": operator.ne, "gt": operator.gt,
    "ge": operator.ge, "lt": operator.lt, "le": operator.le,
}

# 날짜 선언(스니핑·피연산자) 판정용 형태 — 값 선두부터 「YYYY 구분 M 구분 D」(구분자 2개
# 필수, 한글 연월일 포함) 또는 8자리 압축(YYYYMMDD)일 것 + parse_dt 성공. parse_dt 는
# 관대해서 「20260715623-00」(공고번호류 연속 숫자런)의 앞 8자리, 「제2026-15호」의
# "2026-15"(→2026-1-5)까지 날짜로 읽는다 — 선언 판정은 형태가 날짜를 주장하는 값만
# 받는다(오판의 안전 방향은 text 뿐이다).
_DATE_FORMS = (
    re.compile(r"^\d{4}\D+\d{1,2}\D+\d{1,2}(\D.*)?$"),
    re.compile(r"^\d{8}(\D.*)?$"),
)

# 금액 선언(스니핑·피연산자)용 엄격 형태 — 숫자·천단위 콤마·소수점·부호·(원) 만.
# 관대 파서(parse_number)는 「1억」→1·「1차」→1 로 조용히 오독하므로 선언 판정엔 못 쓴다.
_AMOUNTISH_RE = re.compile(
    r"^[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*원?$"
)

# 피연산자에 시각이 실렸는가 — 날짜 비교 입도 판정(시각 없으면 날짜 입도).
_TIME_RE = re.compile(r"\d{1,2}:\d{2}")


def cell_text(record: "dict", column: str) -> str:
    """레코드 셀 텍스트 — 부재·None 만 빈 문자열, 그 외 str 화(시안 ``r[key]||""`` 동형).

    **값 읽기 단일 출처** — 매칭·값 목록·하이라이트·표면 테이블 렌더가 전부 이걸 쓴다.
    ``or ""`` 류(0·False 도 빈칸으로 붕괴)를 쓰면 필터는 남긴 행의 셀이 표면에서 비어
    보이는 어긋남이 생긴다(고효율 리뷰 PR-2b #8).
    """
    v = record.get(column)
    return "" if v is None else str(v)


def _is_dateish(value: str) -> bool:
    """날짜 선언 판정 — 형태가 선두부터 날짜를 주장 + 파싱 성공일 때만."""
    s = value.strip()
    return any(p.match(s) for p in _DATE_FORMS) and parse_dt(s) is not None


def _is_amountish(value: str) -> bool:
    """금액 선언 판정 — 엄격 형태만(「1차」·「A-1」·「1억」은 금액 선언이 아니다)."""
    return bool(_AMOUNTISH_RE.match(value.strip()))


def sniff_column_kinds(
    records: "list[dict]", hints: "dict[str, str] | None" = None
) -> "dict[str, str]":
    """열 유형 판정(범위 문법 자격) — 매핑 확정 유형이 우선, 나머지는 값 스니핑.

    ``hints`` 는 컨트롤러가 매핑에서 아는 소스 열 유형(text/amount/date) — 사용자가
    확정한 유형이므로 스니핑보다 우선한다. 힌트 없는 열은 비어 있지 않은 값 **전부**가
    엄격 금액 형태(→amount) 또는 날짜 형태(→date)일 때만 승격하고, 하나라도
    어긋나면 text 로 남는다. 승격의 대가는 전열 검색 가지 제외라 오판의 안전 방향은
    text 뿐이다(고효율 리뷰: 「1차」·「A-1」류가 관대 파서로 금액 승격되면 검색에서 침묵
    배제). 전부 빈 열도 text. 열 순서는 첫 레코드의 키 순서(데이터 소스 열 순서 보존).
    """
    hints = hints or {}
    columns = list(records[0].keys()) if records else []
    kinds: "dict[str, str]" = {}
    for col in columns:
        hint = hints.get(col)
        if hint in (KIND_TEXT, KIND_AMOUNT, KIND_DATE):
            kinds[col] = hint
            continue
        values = [v for r in records if (v := cell_text(r, col).strip())]
        if values and all(_is_amountish(v) for v in values):
            kinds[col] = KIND_AMOUNT
        elif values and all(_is_dateish(v) for v in values):
            kinds[col] = KIND_DATE
        else:
            kinds[col] = KIND_TEXT
    return kinds


@dataclass(frozen=True)
class RangeClause:
    """범위 조건 한 절 — 연산자(eq/ne/gt/ge/lt/le) + 피연산자 원문 문자열.

    피연산자는 원문으로 보존한다(정의줄이 사용자가 친 그대로 재진술) — 해석은 평가
    시점에 열 유형 파서로 한다(:meth:`FilterModel.set_range` 가 해석 가능성을 담보).
    """

    op: str
    operand: str


@dataclass(frozen=True)
class RangeCondition:
    """열 하나의 범위 조건 — 최대 2절 + AND/OR 결합(엑셀 사용자 지정 동형)."""

    first: RangeClause
    second: "RangeClause | None" = None
    joiner: str = "and"  # second 있을 때만 의미


class _ColumnCondition:
    """열 하나의 조건 묶음(값 체크리스트·텍스트·범위) — FilterModel 내부 전용."""

    __slots__ = ("values", "text", "range_")

    def __init__(self) -> None:
        # values: None=무조건, 리스트=체크된 값만(OR). **순서 보존** — 정의줄이 사용자가
        # 패널에서 본/체크한 순서로 재진술한다(시안 colDesc 동형, 고효율 리뷰 반영).
        self.values: "list[str] | None" = None
        self.text = ""  # 자모 부분일치
        self.range_: "RangeCondition | None" = None

    def is_active(self) -> bool:
        return self.values is not None or bool(self.text) or self.range_ is not None


class FilterModel:
    """데이터 존 필터 상태 — 열 조건(AND) × 전열 OR 그룹. 뷰는 이 API 만 호출한다.

    레코드를 소유하지 않는다 — 평가는 ``records`` 를 받는 :meth:`view` 가 한다(데이터
    소유는 링1 VM, 이 모델은 술어만). 가지 집합은 저장하지 않고 뷰가 산출한다(stale
    없음), 프루닝만 텍스트 수명으로 기억한다(미결 확정 1).
    """

    def __init__(self, columns: "list[str]", kinds: "dict[str, str] | None" = None) -> None:
        self._columns = list(columns)
        self._kinds = dict(kinds) if kinds else {c: KIND_TEXT for c in columns}
        self._cols: "dict[str, _ColumnCondition]" = {c: _ColumnCondition() for c in columns}
        self._search = ""  # 전열 검색어(그룹 텍스트) — 그룹은 항상 최대 1개(미결 확정 2)
        self._pruned: "set[str]" = set()  # 쳐낸 가지 — 텍스트 수명(set_search 가 비움)

    # ------------------------------------------------------------- 조회(정체)
    @property
    def columns(self) -> "list[str]":
        return list(self._columns)

    def kind(self, column: str) -> str:
        self._require(column)
        return self._kinds.get(column, KIND_TEXT)

    def is_active(self) -> bool:
        """조건이 하나라도 서 있는가 — 칩 줄·「필터 없음」 판정."""
        return bool(self._search) or any(c.is_active() for c in self._cols.values())

    def has_condition(self, column: str) -> bool:
        self._require(column)
        return self._cols[column].is_active()

    def column_state(self, column: str) -> dict:
        """열 조건의 직렬 상태 — 표면 패널 프리필용(내부 표현 비공개 유지).

        ``values`` 는 체크 목록(None=(전체)), ``range`` 는 절/결합자 dict(None=없음).
        """
        self._require(column)
        cond = self._cols[column]
        rng = None
        if cond.range_ is not None:
            r = cond.range_
            rng = {
                "first": {"op": r.first.op, "operand": r.first.operand},
                "second": (
                    {"op": r.second.op, "operand": r.second.operand}
                    if r.second is not None else None
                ),
                "joiner": r.joiner,
            }
        return {
            "text": cond.text,
            "values": list(cond.values) if cond.values is not None else None,
            "range": rng,
        }

    @property
    def search_text(self) -> str:
        return self._search

    def _require(self, column: str) -> None:
        if column not in self._cols:  # confirm-or-alarm: 미지 열은 시끄럽게(오배선 검출)
            raise ValueError(f"알 수 없는 열: {column!r}")

    # ------------------------------------------------------------- 변경(선언)
    def set_values(self, column: str, values: "Iterable[str] | None") -> None:
        """값 체크리스트(같은 열 OR) — ``None``=무조건, 반복자=체크된 값만. ``""``=(빈값) 일급.

        **순서가 의미다** — 정의줄이 이 순서로 재진술하므로 표면은 패널 표시(체크) 순서로
        넘긴다. 중복은 첫 등장만 남는다.
        """
        self._require(column)
        self._cols[column].values = (
            None if values is None else list(dict.fromkeys(values))
        )

    def set_text(self, column: str, text: str) -> None:
        """열 텍스트 조건(자모 부분일치) — 양끝 공백 트리밍(시안 동형), 빈 결과=조건 해제."""
        self._require(column)
        self._cols[column].text = text.strip()

    def set_range(self, column: str, cond: "RangeCondition | None") -> None:
        """범위 조건 — 일자·금액 열 전용, 피연산자는 설정 시점에 엄격 검증(시끄러운 거절).

        엑셀은 파싱 불가 피연산자를 조용히 문자열 비교로 강등하지만 그건 조용한 추측이다.
        여기서 더 나아가 **관대 파싱의 조용한 오독도 거절한다**(고효율 리뷰): 「1억」은
        parse_number 로 1이 되어 "검증 통과·술어 오독"이 된다 — 정의줄이 원문 「1억」을
        재진술하므로 어긋남이 안 보인다. 금액은 엄격 형태(숫자·콤마·소수점·원)만, 날짜는
        형태 검사(선두 y-m-d·압축 8자리)를 통과해야 설정된다.
        """
        self._require(column)
        if cond is None:
            self._cols[column].range_ = None
            return
        kind = self.kind(column)
        if kind not in (KIND_AMOUNT, KIND_DATE):
            raise ValueError(f"범위 조건은 일자·금액 열 전용입니다: {column!r} 은(는) 텍스트 열")
        if not isinstance(cond.first, RangeClause):  # 평가 시점 지연 폭발 방지(리뷰)
            raise ValueError("범위 조건의 첫 절이 비어 있습니다.")
        if cond.second is not None and not isinstance(cond.second, RangeClause):
            raise ValueError("범위 조건의 둘째 절 형식이 잘못됐습니다.")
        for clause in (cond.first, cond.second):
            if clause is None:
                continue
            if clause.op not in RANGE_OP_LABELS:
                raise ValueError(f"알 수 없는 비교 연산자: {clause.op!r}")
            ok = (
                _is_amountish(clause.operand) if kind == KIND_AMOUNT
                else _is_dateish(clause.operand)
            )
            if not ok:
                noun, ex = (
                    ("금액", "예: 100,000,000") if kind == KIND_AMOUNT
                    else ("날짜", "예: 2026-07-15")
                )
                raise ValueError(
                    f"'{clause.operand}' 을(를) {noun}(으)로 읽을 수 없습니다. "
                    f"숫자 형태로 입력하세요({ex})."
                )
        if cond.joiner not in _JOINER_LABELS:
            raise ValueError(f"조건 연결 방식을 알 수 없습니다: {cond.joiner!r}")
        self._cols[column].range_ = cond

    def set_search(self, text: str) -> None:
        """전열 검색 = 그룹 재정의(교체, 미결 확정 2) — 프루닝도 함께 걷힌다(텍스트 수명).

        양끝 공백은 트리밍(시안 동형) — 공백 하나가 살아있는 조건이 되어 보이지 않는
        문자로 행이 사라지는 함정을 막는다.
        """
        self._search = text.strip()
        self._pruned = set()

    def prune_branch(self, column: str, records: "list[dict]") -> None:
        """가지 쳐내기 — 검색 텍스트를 고칠 때까지 그 열은 그룹에서 빠진다.

        **마지막 가지를 쳐내면 그룹이 해산된다**(시안 동형, 고효율 리뷰): 전 가지 프루닝은
        검색 해제 의사다 — 검색어만 남기면 전 행이 사라진 빈 화면 + 거짓 「매치 없음」
        정의줄이 된다(매치는 있었고 쳐냈을 뿐이니 거짓말).
        """
        self._require(column)
        self._pruned.add(column)
        if self._search and not self.view(records).branches:
            self._search = ""
            self._pruned = set()

    def clear_column(self, column: str) -> None:
        self._require(column)
        self._cols[column] = _ColumnCondition()

    # ------------------------------------------- 정의 이송(직전 필터 슬롯, 결정 28)
    def export_state(self) -> dict:
        """필터 정의의 직렬 상태 — 직전 필터 슬롯이 세션 사이로 나른다(결정 28).

        검색·프루닝 포함(프루닝 소실 창의 복원은 재적용의 소관 — 결정 27 명문). 활성
        조건이 있는 열만 담는다. **저장이 아니라 전달**이다 — 슬롯은 세션 메모리(앱
        수명)이고 디스크에 남지 않는다(필터 영속 뒷문 금지, 결정 8·24).
        """
        return {
            "search": self._search,
            "pruned": sorted(self._pruned),
            "columns": {
                col: self.column_state(col)
                for col in self._columns if self._cols[col].is_active()
            },
        }

    def apply_state(self, state: dict) -> "tuple[list[str], list[str]]":
        """직전 정의를 현 열 지형에 설치 — ``(설치 열, 탈락 항목)`` 반환(결정 28 백스톱).

        열 결손 강등: 현재 데이터에 없는 열의 조건은 조용히 버리지 않고 탈락 목록으로
        돌려준다(부분 설치 + 고지 — 호출부가 재진술). 유형이 변해 범위 조건이 더는
        성립하지 않는 열도 그 조건만 탈락으로 돌린다(``열명(범위)``). 검색은 열
        불가지(가지는 라이브 산출)라 항상 설치되고, 프루닝은 실재 열만 복원한다.
        전탈락 거부는 호출부 소관 — 이 메서드는 기존 조건을 지우지 않으므로 호출부가
        깨끗한 모델(또는 :meth:`clear` 후)에 적용해야 정의가 섞이지 않는다.
        """
        installed: "list[str]" = []
        dropped: "list[str]" = []
        for col, cond in (state.get("columns") or {}).items():
            if col not in self._cols:
                dropped.append(col)
                continue
            got_any = False
            if cond.get("values") is not None:
                self.set_values(col, cond["values"])
                got_any = True
            if cond.get("text"):
                self.set_text(col, cond["text"])
                got_any = True  # export 는 트리밍된 비공백 텍스트만 담는다(리뷰 — 재검사 불요)
            rng = cond.get("range")
            if rng:
                try:
                    second = rng.get("second")
                    self.set_range(col, RangeCondition(
                        first=RangeClause(rng["first"]["op"], rng["first"]["operand"]),
                        second=(
                            RangeClause(second["op"], second["operand"])
                            if second else None
                        ),
                        joiner=rng.get("joiner", "and"),
                    ))
                    got_any = True
                except ValueError:
                    dropped.append(f"{col}(범위)")  # 열 유형 변경 등 — 그 조건만 탈락
            if got_any:
                installed.append(col)
        search = str(state.get("search") or "").strip()
        if search:
            self._search = search
            self._pruned = {p for p in state.get("pruned") or () if p in self._cols}
        return installed, dropped

    def clear(self) -> None:
        """전체 해제 — 열 조건·그룹·프루닝 전부."""
        self._cols = {c: _ColumnCondition() for c in self._columns}
        self._search = ""
        self._pruned = set()

    # ------------------------------------------------------------- 평가(술어)
    def _clause_pass(self, kind: str, clause: RangeClause, cell: str) -> bool:
        """절 평가 — 셀이 파싱 불가면 불매치(엑셀 동형: 빈칸·텍스트 셀은 수 필터 밖).

        날짜 입도(고효율 리뷰): 피연산자에 시각이 없으면 **날짜 입도로 비교**한다 —
        「≤ 2026-07-15」 가 당일 14:00 셀을 자정 비교로 조용히 탈락시키지 않게. 시각을
        쓴 피연산자는 분 입도 그대로(선언한 만큼 정밀하게).

        피연산자 파싱은 :meth:`set_range` 가 담보했다 — 그래도 실패하면 계약 위반이므로
        시끄럽게(도달 불가 방어 재확인). 유형별 분기는 타입 정합(수↔날짜 비교 배제)도 겸한다.
        """
        op = _RANGE_OPS[clause.op]
        if kind == KIND_AMOUNT:
            cell_n = parse_number(cell)
            if cell_n is None:
                return False
            op_n = parse_number(clause.operand)
            if op_n is None:
                raise ValueError(f"범위 값 {clause.operand!r} 을(를) 해석할 수 없습니다")
            return op(cell_n, op_n)
        cell_d = parse_dt(cell)
        if cell_d is None:
            return False
        op_d = parse_dt(clause.operand)
        if op_d is None:
            raise ValueError(f"범위 값 {clause.operand!r} 을(를) 해석할 수 없습니다")
        if not _TIME_RE.search(clause.operand):
            return op(cell_d.date(), op_d.date())
        return op(cell_d, op_d)

    def _range_pass(self, kind: str, cond: RangeCondition, cell: str) -> bool:
        first = self._clause_pass(kind, cond.first, cell)
        if cond.second is None:
            return first
        second = self._clause_pass(kind, cond.second, cell)
        return (first and second) if cond.joiner == "and" else (first or second)

    def col_pass(self, record: "dict", *, except_column: "str | None" = None) -> bool:
        """열 조건 전부(AND) — ``except_column`` 은 값 목록 산출용 자기 제외(엑셀 동형)."""
        for col, cond in self._cols.items():
            if col == except_column or not cond.is_active():
                continue
            cell = cell_text(record, col)
            if cond.values is not None and cell not in cond.values:
                return False
            if cond.text and not jamo_contains(cell, cond.text):
                return False
            if cond.range_ is not None and not self._range_pass(
                self.kind(col), cond.range_, cell
            ):
                return False
        return True

    # ------------------------------------------------------------- 평가 뷰
    def view(self, records: "list[dict]") -> "FilterView":
        """평가 뷰 — 가지 집합을 1회 산출·캐시. **렌더 루프는 반드시 이걸 쓴다**(리뷰:
        셀마다 가지 재산출은 행×열×자모 분해가 셀 수만큼 곱해지는 준제곱 렌더)."""
        return FilterView(self, records)

    # ---- 단발 질의용 위임(테스트·비렌더 경로) — 렌더는 view() 경유가 계약 ----
    def group_branches(self, records: "list[dict]") -> "list[str]":
        return self.view(records).branches

    def visible_indices(self, records: "list[dict]") -> "list[int]":
        return self.view(records).visible_indices()

    def column_values(self, column: str, records: "list[dict]") -> "list[str]":
        return self.view(records).column_values(column)

    def describe_parts(self, records: "list[dict]") -> "list[str]":
        return self.view(records).describe_parts()

    def describe(self, records: "list[dict]") -> str:
        return self.view(records).describe()

    def stratified_sample(
        self, indices: "list[int]", records: "list[dict]", limit: int
    ) -> "list[int]":
        return self.view(records).stratified_sample(indices, limit)

    def segments(
        self, column: str, value: str, records: "list[dict]"
    ) -> "list[tuple[str, bool]]":
        return self.view(records).segments(column, value)


class FilterView:
    """모델×레코드의 평가 스냅샷 — 가지 집합을 생성 시 1회 산출·캐시.

    한 렌더 패스(스냅샷 합성) 동안만 쓰고 버린다 — 모델이나 레코드가 변하면 새로 만든다
    (컨트롤러는 push 마다 새 뷰를 만드므로 자연 충족). 캐시는 가지 하나뿐이라 stale 창이
    없다(나머지는 매 호출 산출).
    """

    def __init__(self, model: FilterModel, records: "list[dict]") -> None:
        self._m = model
        self._records = records
        self.branches: "list[str]" = self._compute_branches()

    # ------------------------------------------------------------- 가지 산출
    def _compute_branches(self) -> "list[str]":
        """전열 그룹의 가지 — 실매치 있는 텍스트 열만, 프루닝 반영(시안 동형).

        가지 설치 판정은 열 조건을 통과한 행 기준 — 조건이 이미 배제한 행에서만 맞는
        열에 가지를 세우면 재현이 거짓말이 된다.
        """
        m, records = self._m, self._records
        if not m._search:
            return []
        passing = [r for r in records if m.col_pass(r)]
        return [
            col for col in m._columns
            if m._kinds.get(col, KIND_TEXT) == KIND_TEXT
            and col not in m._pruned
            and any(jamo_contains(cell_text(r, col), m._search) for r in passing)
        ]

    def _group_pass(self, record: "dict") -> bool:
        m = self._m
        if not m._search:
            return True
        if not self.branches:  # 어느 열에도 매치 없음 = 전멸(빈 화면 + 정의줄 재진술)
            return False
        return any(jamo_contains(cell_text(record, b), m._search) for b in self.branches)

    # ------------------------------------------------------------- 가시 집합
    def visible_indices(self) -> "list[int]":
        """필터를 통과한 행 인덱스(원본 순서) — 보기만 바꾼다, 선택은 관통(결정 3)."""
        return [
            i for i, r in enumerate(self._records)
            if self._m.col_pass(r) and self._group_pass(r)
        ]

    # ------------------------------------------------- 값 목록(체크리스트 소재)
    def column_values(self, column: str) -> "list[str]":
        """열 체크리스트 값 목록 — 다른 열 조건+그룹 통과 행 기준, 등장 순서, (빈값) 말미.

        자기 열 조건은 제외하고 본다(엑셀 동형 — 체크를 풀 수 있어야 하므로). 빈 문자열이
        하나라도 있으면 정식 값으로 말미에 포함한다((빈값) 일급, 결정 23).
        """
        self._m._require(column)
        seen: "dict[str, None]" = {}
        has_empty = False
        for r in self._records:
            if not (self._m.col_pass(r, except_column=column) and self._group_pass(r)):
                continue
            v = cell_text(r, column)
            if v == "":
                has_empty = True
            else:
                seen.setdefault(v, None)
        values = list(seen)
        if has_empty:
            values.append("")
        return values

    # ------------------------------------------------- 정의줄(재진술 단일 출처)
    @staticmethod
    def _value_label(value: str) -> str:
        return "(빈값)" if value == "" else value

    def _describe_column(self, column: str) -> "list[str]":
        cond = self._m._cols[column]
        parts: "list[str]" = []
        if cond.values is not None:
            vals = cond.values  # 저장 순서 그대로 — 사용자가 체크한 순서(시안 동형)
            if len(vals) == 1:
                parts.append(f"{column} = {self._value_label(vals[0])}")
            else:
                inner = ", ".join(self._value_label(v) for v in vals)
                parts.append(f"{column} ∈ {{{inner}}}")
        if cond.text:
            parts.append(f"{column} 포함 '{cond.text}'")
        if cond.range_ is not None:
            r = cond.range_
            head = f"{column} {RANGE_OP_LABELS[r.first.op]} '{r.first.operand}'"
            if r.second is not None:
                head += (
                    f" {_JOINER_LABELS[r.joiner]} "
                    f"{RANGE_OP_LABELS[r.second.op]} '{r.second.operand}'"
                )
            parts.append(head)
        return parts

    def describe_parts(self) -> "list[str]":
        """조건별 문안 목록 — 칩 줄이 한 칩씩, 게이트 정의줄이 이어붙여 소비(결정 4 담보)."""
        parts: "list[str]" = []
        for col in self._m._columns:
            parts.extend(self._describe_column(col))
        if self._m._search:
            if self.branches:
                parts.append(f"({' ∨ '.join(self.branches)}) 포함 '{self._m._search}'")
            else:
                # 선언된 문안 편차 — 시안은 생략하지만 빈 화면의 이유는 재진술해야 한다.
                parts.append(f"검색 '{self._m._search}' (매치 없음)")
        return parts

    def describe(self) -> str:
        """정의줄 전체 — 「전체 선택」·게이트 재진술이 그대로 나른다(문안 단일 출처)."""
        return " · ".join(self.describe_parts())

    # ------------------------------------------------- 층화 표본(결정 5 소재)
    def stratified_sample(self, indices: "list[int]", limit: int) -> "list[int]":
        """가지별 층화 표본 — 광의 OR 정의에서 소수 가지의 매치가 반드시 표본에 등장.

        ``indices``(선택 집합 등) 중에서 뽑는다: 각 가지마다 그 가지에 맞는 첫 행을 먼저
        확보하고, 남는 자리를 앞에서부터 채운 뒤 원본 순서로 돌려준다. 가지 수가
        ``limit`` 를 넘으면 가지 대표가 우선이라 표본이 ``limit`` 를 넘을 수 있다(표본
        뒤에 숨는 오버매치의 구조적 소멸이 상한보다 우선 — 결정 5). 그룹이 없으면 앞
        ``limit`` 개(단순 표본).
        """
        if limit <= 0:
            return []
        m, records = self._m, self._records
        if not m._search or not self.branches:
            return indices[:limit]
        picked: "list[int]" = []
        for branch in self.branches:
            for i in indices:
                if i in picked:
                    continue
                if jamo_contains(cell_text(records[i], branch), m._search):
                    picked.append(i)
                    break
        for i in indices:
            if len(picked) >= limit:  # 가지 대표가 이미 상한 초과면 채움 없이 그대로
                break
            if i not in picked:
                picked.append(i)
        return sorted(picked)

    # ------------------------------------------------- 하이라이트(세그먼트 계약)
    def segments(self, column: str, value: str) -> "list[tuple[str, bool]]":
        """셀 하이라이트 세그먼트 ``[(조각, 매치여부), …]`` — 웹은 받은 조각을 그리기만.

        매치 인덱스를 건네지 않는다(jamo 모듈 경계: 코드포인트/UTF-16 파생경계 번역오류의
        상류 차단). 적용 순서 = **전열 검색(그 열이 가지일 때) → 열 텍스트**(시안 ``mark``
        동형 — 검색어 우선, 고효율 리뷰 반영) — 첫 매치 하나만 칠한다. 매치 없으면 통짜
        한 조각.
        """
        m = self._m
        m._require(column)
        terms: "list[str]" = []
        if m._search and column in self.branches:
            terms.append(m._search)
        if m._cols[column].text:
            terms.append(m._cols[column].text)
        for term in terms:
            found = jamo_find(value, term)
            if found is None:
                continue
            start, end = found
            return [
                (piece, hit)
                for piece, hit in (
                    (value[:start], False), (value[start:end], True), (value[end:], False),
                )
                if piece
            ]
        return [(value, False)] if value else []
