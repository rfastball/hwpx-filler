"""필터 선언 상태 모델 — Qt·웹 비의존 순수 파이썬(R-flow 블록 4, 결정 23~25).

「작업」 세션 패널 데이터 존의 **화면 편집 주체 = 필터 상태 하나**(결정 23)의 그 상태다.
사양 정본은 시안 ``https://github.com/rfastball/hwpx-filler/blob/5f51e442dde87891b68fbbdc1519a04e01211b8e/docs/r-flow-mockups/block4-filter-crystallize-demo.html`` 의 상태 기계
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
- **자모 부분일치**(결정 23): 열 텍스트·전열 검색 모두 :mod:`~hwpxfiller.domain.jamo` 소비
  (「행복도ㅅ」 단계 매치). 입력은 양끝 공백 트리밍(시안 동형 — 보이지 않는 문자로 행이
  사라지지 않게). 하이라이트는 :meth:`FilterView.segments` 가 **파이썬에서 원문을 잘라
  세그먼트로** 준다 — 매치 인덱스를 웹으로 건네지 않는다(jamo PR-1 리뷰 계약: 코드포인트/
  UTF-16 파생경계 번역오류의 상류 차단). 색칠 우선순위 = 전열 검색 → 열 텍스트(시안
  ``mark`` 동형 — 검색어가 먼저).
- **범위 조건 = 엑셀 사용자 지정 자동 필터 동형**(2026-07-19 확정): 비교 연산자 6종
  (=·≠·>·≥·<·≤) + 최대 2절 AND/OR 결합. **동적 날짜 프리셋(오늘·지난주 등)은 제외**
  (벽시계 상대 정의는 재현 재진술과 마찰 — 같은 정의가 날마다 다른 행을 매치).
- **필터는 보기만 바꾼다**(결정 3): 이 모델은 선택(:class:`~hwpxfiller.viewmodel.selection_state.
  SelectionModel`)을 모른다 — 선택은 필터를 관통하고, 필터 밖 선택의 스트립 표현은 표면
  소관이다.

## 값 해석 — 표시 파서 재사용 + 선언 지점만 엄격(고효율 리뷰 반영)

셀 해석은 표시형과 같은 관대 파서(:func:`~hwpxfiller.domain.format_engine.parse_number`/
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

## 저장한 필터(이름 붙인 필터 칩, 2026-09-30 사용자 확정)

사용자가 조건(열 조건·검색)을 이름으로 저장하고, 그 이름 칩을 눌러 켜고 끈다(예: 「소기업」 =
추정가격 < 1억, 「중소기업」 = 1억 ≤ 추정가격 < 고시금액). 문법을 새로 짓지 않는다 — 저장본은
:meth:`FilterModel.export_state` 의 지금 조건 부분과 같은 모양이다. 켜진 저장본은 전체 열 검색의
OR 그룹처럼 **이 모델 안의 무리**다(곁 모델을 따로 평가하지 않는다): 정의를 한 번 설치해 조건
묶음(:class:`_ConditionGroup` — 열 조건 AND + 제 검색 OR)으로 들고, 열 조건과 같은 술어로 평가한다.
평가·정의줄·게이트·「전체 선택」 담보·빌더의 수·전체 해제가 모두 이 모델 하나를 지난다.

**합성 규칙 = 슬라이서 관례**(2026-09-30 사용자 확정): 저장본의 **차원**은 그 저장본이 조이는
열 이름 집합(+ 전체 열 검색이면 의사 차원 :data:`SEARCH_DIMENSION`)이다
(:meth:`FilterModel.preset_dimension`). 같은 차원의 켜진 저장본끼리는 **또는**(합집합), 차원
사이는 **그리고**(교집합)다 — 「소기업」과 「중소기업」을 함께 켜면 두 구간이 모두 보인다. 켜진
저장본이 없는 차원은 아무것도 조이지 않는다. 지금 조건(열 머리·검색)은 늘 **그리고**로 얹힌다.
정의줄은 켜진 차원마다 한 조각(``필터 '소기업' 또는 '중소기업'``)으로 재진술해(:data:`PRESET_LABEL`)
게이트·「전체 선택」 담보가 그대로 덮는다. 교집합이 비면 빈 표 + 정의줄이다(조용한 빈칸 아님).
켜진 저장본이 조이는 열은 열 머리도 조건 표지를 세우고 그 무리 문안을 싣는다
(:meth:`FilterModel.column_constraints`). 그 열의 열 머리 편집은 지금 조건(그리고)을 더할 뿐 칩을
끄지 않는다. 「열 조건」 칩은 열 머리에서 건 조건만이다(저장본의 조이기는 제 칩이 말한다).

이름을 비우고 저장하면 짧은 조건 요약(:meth:`FilterModel.name_state` — 값 하나면 ``열 값``, 여럿이면
``열 첫값 외 N개``)이 이름이 된다. 조건 전문은 칩 ``title``(:meth:`FilterModel.preset_description`)이 든다.

저장본은 빌더가 보낸 조건을 :meth:`FilterModel.normalize_preset_state` 로 받는다 — 열 머리 편집기와
같은 엄격 경로(없는 열·읽을 수 없는 피연산자·빈 조건은 시끄럽게 거절)다. 저장본 정의의 영속은 이
모델 밖이다 — 등록 데이터 항목이 들고(:attr:`~hwpxfiller.domain.dataset_reference.
DatasetReference.filters`), 세션이 :meth:`FilterModel.set_presets` 로 심는다. 세션 이송
(:meth:`export_state`)은 켜진 **이름**만 나른다. 지금 데이터에 없는 열·맞지 않는 범위를 가리키는
저장본은 켤 수 없고, 사유는 :meth:`FilterModel.preset_status` 가 짓는다.
이는 결정 24의 「필터 영속 금지」를 **이름 붙인 저장본에 한해** 사용자가 명시로 연 것이다 —
지금 조건·직전 필터 슬롯은 여전히 세션 메모리뿐이다.

회귀 = ``tests/test_filter_state.py``. 표면 배선(열 테이블·아이콘 패널·스트립)은 PR-2b.
"""
from __future__ import annotations

import copy
import operator
import re
from dataclasses import dataclass
from typing import Iterable

from ..domain.format_engine import parse_dt, parse_number
from ..domain.jamo import jamo_contains, jamo_find

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
    "PRESET_LABEL",
    "PresetStateError",
    "SEARCH_DIMENSION",
    "range_condition_from_payload",
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

# 저장한 필터 — 정의줄 재진술 형태(문장 안 낫표 금지 규칙에 따라 작은따옴표).
PRESET_LABEL = "필터 '{name}'"
# 같은 차원의 켜진 저장본을 한 조각으로 잇는 말(합집합) — ``필터 '소기업' 또는 '중소기업'``.
_PRESET_OR = " 또는 "
_PRESET_GROUP_LABEL = "필터 {names}"
# 전체 열 검색을 든 저장본의 의사 차원 — 열 이름과 겹치지 않는 예약 이름.
SEARCH_DIMENSION = "__search__"
# 차원 표지(칩 줄 무리 이름)에서 검색 차원을 부르는 말.
_SEARCH_DIMENSION_LABEL = "검색"

# 저장한 필터 거절 사유(사용자 문안 — 이름 입력창·칩 비활성 사유가 그대로 싣는다).
_PRESET_NAME_EMPTY = "이름을 비울 수 없습니다."
_PRESET_NAME_TAKEN = "같은 이름의 필터가 있습니다."
_PRESET_STATE_EMPTY = "저장할 조건이 없습니다."
_PRESET_COLUMN_MISSING = "이 필터의 열이 지금 데이터에 없습니다: {columns}"
_PRESET_RANGE_UNFIT = "이 필터의 범위 조건을 지금 데이터 열에 적용할 수 없습니다: {columns}"
_PRESET_UNREADABLE = "이 필터의 저장 형식을 읽을 수 없습니다."
_PRESET_UNKNOWN = "저장한 필터를 찾을 수 없습니다: {name}"


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


class PresetStateError(ValueError):
    """저장본 조건 거절 — 문장은 설치 규칙의 것 그대로, ``column`` 은 거절이 가리키는 열("" = 전체).

    빌더가 오류를 그 열의 카드 아래에 세우는 좌표다(판정은 여기서만 — 표면이 문장을 해부하지 않는다).
    """

    def __init__(self, message: str, column: str = "") -> None:
        super().__init__(message)
        self.column = column


def range_condition_from_payload(
    first: "dict | None", second: "dict | None" = None, joiner: "str | None" = "and"
) -> "RangeCondition | None":
    """표면이 보낸 범위 조건 dict → :class:`RangeCondition` — 열 머리 편집기·필터 빌더 공용.

    빈 첫 절(피연산자 공백)은 조건 없음(``None``), 빈 둘째 절은 1절 조건이다. 피연산자는
    양끝 공백을 다듬는다. 형식 손상(절이 dict 가 아님·연산자 누락)은 ``ValueError`` — 해석
    가능성 검증은 :meth:`FilterModel.set_range` 가 한다(이 함수는 모양만 옮긴다).
    """
    def clause(raw: "object") -> "RangeClause | None":
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValueError(_PRESET_UNREADABLE)
        operand = str(raw.get("operand", "") or "").strip()
        if not operand:
            return None
        return RangeClause(str(raw.get("op", "")), operand)

    head = clause(first)
    if head is None:
        return None
    return RangeCondition(first=head, second=clause(second), joiner=str(joiner or "and"))


def _cond_is_active(cond: dict) -> bool:
    """직렬 열 조건 dict 가 무언가를 조이는가 — :meth:`_ColumnCondition.is_active` 의 직렬판."""
    return (
        cond.get("values") is not None
        or bool(str(cond.get("text") or "").strip())
        or bool(cond.get("range"))
    )


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


class _ConditionGroup:
    """저장한 필터 하나의 설치된 조건 묶음 — 모델 안 무리의 구성원(FilterModel 내부 전용).

    열 조건(AND, 무언가를 조이는 열만)과 제 전체 열 검색(OR 가지, 쳐낸 가지는 정의에서 온다)을
    든다. 평가는 소유 모델이 열 조건과 **같은 술어**로 한다 — 곁 모델을 따로 만들지 않는다.
    """

    __slots__ = ("cols", "search", "pruned")

    def __init__(
        self, cols: "dict[str, _ColumnCondition]", search: str, pruned: "frozenset[str]",
    ) -> None:
        self.cols = cols
        self.search = search
        self.pruned = pruned


def _value_label(value: str) -> str:
    return "(빈값)" if value == "" else value


def _describe_condition(column: str, cond: _ColumnCondition) -> "list[str]":
    """열 조건 하나의 정의줄 조각들 — 열 머리 조건·저장본 설명이 함께 쓰는 단일 생산자."""
    parts: "list[str]" = []
    if cond.values is not None:
        vals = cond.values  # 저장 순서 그대로 — 사용자가 체크한 순서(시안 동형)
        if len(vals) == 1:
            parts.append(f"{column} = {_value_label(vals[0])}")
        else:
            inner = ", ".join(_value_label(v) for v in vals)
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


def _search_part(search: str, branches: "list[str]") -> str:
    """전체 열 검색 조각 — 가지가 없으면 「매치 없음」을 재진술한다(선언된 문안 편차)."""
    if branches:
        return f"({' ∨ '.join(branches)}) 포함 '{search}'"
    return f"검색 '{search}' (매치 없음)"


def _short_condition(column: str, cond: _ColumnCondition) -> "list[str]":
    """칩 이름용 짧은 조각 — 값 하나 ``열 값``, 여럿 ``열 첫값 외 N개``, 범위는 기호·피연산자 그대로.

    단위를 줄여 쓰지 않는다(피연산자는 사용자가 쓴 그대로). 「사이」(≥ a 그리고 < b)는 ``a~b`` 다.
    """
    parts: "list[str]" = []
    if cond.values is not None:
        vals = [_value_label(v) for v in cond.values]
        if len(vals) == 1:
            parts.append(f"{column} {vals[0]}")
        elif vals:
            parts.append(f"{column} {vals[0]} 외 {len(vals) - 1}개")
        else:
            parts.append(f"{column} ∈ {{}}")
    if cond.text:
        parts.append(f"{column} 포함 '{cond.text}'")
    if cond.range_ is not None:
        r = cond.range_
        if (
            r.second is not None and r.joiner == "and"
            and r.first.op == "ge" and r.second.op == "lt"
        ):
            parts.append(f"{column} {r.first.operand}~{r.second.operand}")
        else:
            head = f"{column} {RANGE_OP_LABELS[r.first.op]} {r.first.operand}"
            if r.second is not None:
                head += (
                    f" {_JOINER_LABELS[r.joiner]} "
                    f"{RANGE_OP_LABELS[r.second.op]} {r.second.operand}"
                )
            parts.append(head)
    return parts


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
        # 저장한 필터 — 이름 → 지금 조건 직렬 상태(삽입 순서 = 칩 순서). 정의는 세션이 심고
        # (set_presets) 켜짐은 이 모델이 든다. 설치된 조건 묶음은 이름별 지연 캐시다(열 지형 고정).
        self._presets: "dict[str, dict]" = {}
        self._active_presets: "list[str]" = []
        self._groups: "dict[str, _ConditionGroup]" = {}

    # ------------------------------------------------------------- 조회(정체)
    @property
    def columns(self) -> "list[str]":
        return list(self._columns)

    def kind(self, column: str) -> str:
        self._require(column)
        return self._kinds.get(column, KIND_TEXT)

    def is_active(self) -> bool:
        """조건이 하나라도 서 있는가 — 칩 줄·「필터 없음」 판정(켜진 저장한 필터 포함)."""
        return self.has_adhoc() or bool(self._active_presets)

    def has_adhoc(self) -> bool:
        """지금 조건(열 조건·검색)이 서 있는가 — 필터 빌더 프리필의 재료 유무."""
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

    # ------------------------------------------------- 저장한 필터(이름 붙인 칩)
    @property
    def presets(self) -> "list[dict]":
        """저장한 필터 정의 ``[{name, state}]`` — 칩 순서. 영속 writer 에 그대로 넘기는 사본."""
        return [
            {"name": name, "state": copy.deepcopy(state)}
            for name, state in self._presets.items()
        ]

    @property
    def active_presets(self) -> "list[str]":
        """켜진 저장한 필터 이름 — 켠 순서(정의줄 재진술 순서)."""
        return list(self._active_presets)

    def set_presets(
        self, presets: "Iterable[dict]", *, renamed: "dict[str, str] | None" = None
    ) -> "list[str]":
        """저장한 필터 정의를 통째 심는다(세션 시드·재시드) — 꺼진 이름 목록을 돌려준다.

        이름은 양끝 공백을 다듬고 비었거나 겹치면 시끄럽게 거절한다(정의 원천 손상은 조용히
        고치지 않는다). 켜져 있던 이름 중 사라졌거나 지금 데이터에서 쓸 수 없게 된 것은
        끄고 그 이름을 돌려준다 — 호출부가 보기 변화를 재진술한다. ``renamed`` 는 이름
        바꾸기의 켜짐 승계표(옛 이름 → 새 이름)다.
        """
        table: "dict[str, dict]" = {}
        for entry in presets:
            name = str(entry.get("name", "")).strip()
            if not name:
                raise ValueError(_PRESET_NAME_EMPTY)
            if name in table:
                raise ValueError(_PRESET_NAME_TAKEN)
            state = entry.get("state")
            table[name] = copy.deepcopy(state) if isinstance(state, dict) else {}
        renamed = renamed or {}
        self._presets = table
        self._groups = {}
        dropped: "list[str]" = []
        kept: "list[str]" = []
        for name in self._active_presets:
            name = renamed.get(name, name)
            if name in table and self.preset_status(name)[0]:
                kept.append(name)
            else:
                dropped.append(name)
        self._active_presets = kept
        return dropped

    def preset_status(self, name: str) -> "tuple[bool, str]":
        """저장한 필터를 지금 데이터에서 쓸 수 있는가 — ``(가부, 사유)``.

        열 결손·범위 부적합은 :meth:`apply_state` 의 탈락 목록을 그대로 읽는다(설치 규칙의
        단일 출처). 부분 설치는 허용하지 않는다 — 조건 일부만 적용한 칩은 이름과 다른 행을
        보여 준다.
        """
        if name not in self._presets:
            return False, _PRESET_UNKNOWN.format(name=name)
        state = self._presets[name]
        if "active_presets" in state:  # 저장본은 지금 조건만 담는다 — 중첩은 손상이다
            return False, _PRESET_UNREADABLE
        try:
            group, dropped = self._install_group(state)
        except (AttributeError, KeyError, TypeError, ValueError):
            return False, _PRESET_UNREADABLE
        missing = [d for d in dropped if not d.endswith("(범위)")]
        if missing:
            return False, _PRESET_COLUMN_MISSING.format(columns=", ".join(missing))
        if dropped:
            unfit = [d[: -len("(범위)")] for d in dropped]
            return False, _PRESET_RANGE_UNFIT.format(columns=", ".join(unfit))
        if not group.cols and not group.search:
            return False, _PRESET_STATE_EMPTY
        return True, ""

    def _install_group(self, state: dict) -> "tuple[_ConditionGroup, list[str]]":
        """저장본 정의 → 설치된 조건 묶음 + 탈락 목록 — 설치 규칙은 :meth:`apply_state` 하나다.

        빈 초안 모델은 설치 규칙(열 결손·범위 부적합·피연산자 검증)을 빌려 쓰는 자리일 뿐이고,
        평가는 돌려받은 묶음을 이 모델이 한다(곁 모델을 들고 있지 않는다).
        """
        scratch = FilterModel(self._columns, self._kinds)
        _installed, dropped = scratch.apply_state(state)
        cols = {col: cond for col, cond in scratch._cols.items() if cond.is_active()}
        return _ConditionGroup(cols, scratch._search, frozenset(scratch._pruned)), dropped

    def _group(self, name: str) -> _ConditionGroup:
        """저장한 필터의 설치된 조건 묶음(지연 캐시) — 정의가 바뀌면 캐시를 비운다."""
        group = self._groups.get(name)
        if group is None:
            group, _dropped = self._install_group(self._presets[name])
            self._groups[name] = group
        return group

    def activate_preset(self, name: str) -> None:
        """저장한 필터 켜기 — 쓸 수 없으면 사유와 함께 거절(조용한 무시 금지)."""
        usable, reason = self.preset_status(name)
        if not usable:
            raise ValueError(reason)
        if name not in self._active_presets:
            self._active_presets.append(name)

    def deactivate_preset(self, name: str) -> None:
        if name not in self._presets:
            raise ValueError(_PRESET_UNKNOWN.format(name=name))
        if name in self._active_presets:
            self._active_presets.remove(name)

    def toggle_preset(self, name: str) -> bool:
        """켜짐 뒤집기 — 새 켜짐을 돌려준다."""
        if name in self._active_presets:
            self.deactivate_preset(name)
            return False
        self.activate_preset(name)
        return True

    def _check_new_name(self, name: str) -> str:
        name = str(name).strip()
        if not name:
            raise ValueError(_PRESET_NAME_EMPTY)
        if name in self._presets:
            raise ValueError(_PRESET_NAME_TAKEN)
        return name

    def normalize_preset_state(self, state: object, *, allow_empty: bool = False) -> dict:
        """빌더가 보낸 조건 → 저장본 — 열 머리 편집기와 **같은 엄격 경로**로 검증한다.

        모양은 :meth:`export_state` 의 지금 조건 부분(``columns`` → ``{values|text|range}``,
        ``search``, 선택 ``pruned``)이다. 지금 열 지형의 빈 모델에 조건을 하나씩 설치해 보고,
        설치 규칙이 거절하면 그 문장을 그대로 올린다: 없는 열(:data:`_PRESET_COLUMN_MISSING`),
        읽을 수 없는 범위 피연산자(:meth:`set_range`), 조이는 것이 없는 조건
        (:data:`_PRESET_STATE_EMPTY` — ``allow_empty`` 면 통과), 모양 손상
        (:data:`_PRESET_UNREADABLE`). :meth:`apply_state` 처럼 부분 설치 + 탈락 목록으로 강등하지
        않는다 — 저장본은 이름과 다른 행을 보여 주면 안 된다. 반환은 설치 결과를 다시 직렬화한
        정규형이다(트리밍·중복 제거가 반영된다).
        """
        if not isinstance(state, dict) or "active_presets" in state:
            raise ValueError(_PRESET_UNREADABLE)
        columns = state.get("columns") or {}
        search = state.get("search") or ""
        pruned = state.get("pruned") or []
        if not (
            isinstance(columns, dict) and isinstance(search, str) and isinstance(pruned, list)
        ):
            raise ValueError(_PRESET_UNREADABLE)
        missing = [col for col in columns if col not in self._cols]
        if missing:
            raise PresetStateError(
                _PRESET_COLUMN_MISSING.format(columns=", ".join(missing)), column=missing[0],
            )
        scratch = FilterModel(self._columns, self._kinds)
        for col, cond in columns.items():
            if not isinstance(cond, dict):
                raise PresetStateError(_PRESET_UNREADABLE, column=col)
            values, text = cond.get("values"), cond.get("text") or ""
            if (values is not None and not isinstance(values, list)) or not isinstance(text, str):
                raise PresetStateError(_PRESET_UNREADABLE, column=col)
            if values is not None:
                scratch.set_values(col, [str(v) for v in values])
            scratch.set_text(col, text)
            rng = cond.get("range")
            if rng:
                try:
                    if not isinstance(rng, dict):
                        raise ValueError(_PRESET_UNREADABLE)
                    scratch.set_range(col, range_condition_from_payload(
                        rng.get("first"), rng.get("second"), rng.get("joiner", "and"),
                    ))
                except PresetStateError:
                    raise
                except ValueError as exc:  # 피연산자 거절 — 같은 문장, 그 열의 카드로
                    raise PresetStateError(str(exc), column=col) from exc
        scratch.set_search(search)
        if scratch.search_text:  # 쳐낸 가지는 검색 텍스트 수명 — 실재 열만 잇는다
            scratch._pruned = {str(col) for col in pruned if col in self._cols}
        if not allow_empty and not scratch.has_adhoc():
            raise PresetStateError(_PRESET_STATE_EMPTY)
        return scratch.adhoc_state()

    def name_state(self, state: object) -> str:
        """후보 조건의 짧은 이름 — 빌더 이름 칸의 자리표시자이자 이름을 비우고 저장할 때의 이름.

        조각은 열 순서로 ``·`` 로 잇는다(:func:`_short_condition`, 검색은 ``검색 '어'``). 조건 전문은
        칩 title(:meth:`preset_description`)이 든다. 빈 조건이면 ``""``.
        """
        group, _dropped = self._install_group(self.normalize_preset_state(state, allow_empty=True))
        parts: "list[str]" = []
        for col in self._columns:
            if col in group.cols:
                parts.extend(_short_condition(col, group.cols[col]))
        if group.search:
            parts.append(f"검색 '{group.search}'")
        return " · ".join(parts)

    def count_state(self, state: object, records: "list[dict]") -> int:
        """빌더의 후보 조건 **하나만**으로 보이는 행 수 — 지금 조건·켜진 저장본과 무관.

        저장본은 무리로 합성되므로(차원 규칙) 빌더의 수는 그 저장본 자신의 수다 — 무리 구성원을
        평가하는 같은 술어(:meth:`_group_rows`)로 센다. 검증은 :meth:`normalize_preset_state` 와 같고,
        조건이 비었으면 전 행이다(저장 거절은 저장이 말한다 — 빈 빌더를 열자마자 오류를 띄우지 않는다).
        """
        group, _dropped = self._install_group(self.normalize_preset_state(state, allow_empty=True))
        return len(self._group_rows(group, records))

    def create_preset(self, name: str, state: object, *, from_adhoc: bool = False) -> str:
        """빌더의 조건을 이름으로 저장하고 **켠다** — 저장한 이름을 돌려준다.

        이름을 비우면 짧은 조건 요약(:meth:`name_state`)이 이름이 된다. 같은 이름은 덮어쓰지 않고 거절한다(저장본의
        조용한 소실 금지 — 요약 이름도 같다). ``from_adhoc`` 는 빌더가 지금 조건으로 채워져
        열렸다는 표지다 — 저장 뒤 지금 조건을 비워 정의가 칩 하나로 접힌다(같은 차원의 다른
        저장본이 켜져 있지 않으면 보이는 행은 그대로다).
        """
        saved = self.normalize_preset_state(state)
        name = self._check_new_name(str(name).strip() or self.name_state(saved))
        self._presets[name] = saved
        self._groups.pop(name, None)
        if from_adhoc:
            self._clear_adhoc()
        self._active_presets.append(name)
        return name

    def update_preset(self, name: str, new_name: str, state: object) -> str:
        """저장본 고치기(이름·조건) — 칩 순서·켜짐을 그대로 잇는다. 새 이름을 돌려준다.

        검증은 만들기와 같고(빈 이름 = 짧은 조건 요약), 이름이 그대로면 이름 검사는 건너뛴다. 조건이
        바뀌면 차원도 바뀔 수 있다(칩이 다른 무리로 옮겨 간다) — 켜짐은 그대로 잇는다.
        """
        if name not in self._presets:
            raise ValueError(_PRESET_UNKNOWN.format(name=name))
        saved = self.normalize_preset_state(state)
        new_name = str(new_name).strip() or self.name_state(saved)
        if new_name != name:
            new_name = self._check_new_name(new_name)
        self._presets = {
            (new_name if key == name else key): (saved if key == name else value)
            for key, value in self._presets.items()
        }
        self._groups = {}
        self._active_presets = [new_name if n == name else n for n in self._active_presets]
        return new_name

    # ------------------------------------------------ 저장본 차원(합성 규칙의 단위)
    def _preset_state(self, name: str) -> dict:
        if name not in self._presets:
            raise ValueError(_PRESET_UNKNOWN.format(name=name))
        return self._presets[name]

    def preset_columns(self, name: str) -> "frozenset[str]":
        """저장본이 조이는 열 이름 집합(값 목록·텍스트·범위 중 하나라도 선 열).

        손상된 저장본(모양이 틀림)은 빈 집합 — 켤 수 없으므로 합성에 들지 않는다.
        """
        columns = self._preset_state(name).get("columns")
        if not isinstance(columns, dict):
            return frozenset()
        return frozenset(
            col for col, cond in columns.items() if isinstance(cond, dict) and _cond_is_active(cond)
        )

    def preset_dimension(self, name: str) -> "frozenset[str]":
        """저장본의 차원 — 조이는 열 + 전체 열 검색이면 :data:`SEARCH_DIMENSION`.

        같은 차원의 켜진 저장본끼리 「또는」, 차원 사이 「그리고」(슬라이서 관례). 차원은
        저장본 정의에서 나온다(지금 데이터에 그 열이 있는지와 무관 — 쓸 수 없는 저장본도 자기
        무리에 선다).
        """
        search = self._preset_state(name).get("search")
        extra = {SEARCH_DIMENSION} if isinstance(search, str) and search.strip() else set()
        return self.preset_columns(name) | extra

    def _group_key(self, name: str) -> object:
        """무리 짓기 열쇠 — 차원이 빈(손상된) 저장본은 저마다 홀로 선다."""
        return self.preset_dimension(name) or ("", name)

    def preset_groups(self) -> "list[list[str]]":
        """저장본 전부를 차원별로 — 무리는 첫 등장 순, 무리 안은 저장 순(칩 줄 렌더 순서)."""
        groups: "dict[object, list[str]]" = {}
        for name in self._presets:
            groups.setdefault(self._group_key(name), []).append(name)
        return list(groups.values())

    def active_preset_groups(self) -> "list[list[str]]":
        """켜진 저장본의 차원 무리 — 무리는 처음 켠 순, 무리 안은 켠 순(정의줄 재진술 순서)."""
        groups: "dict[object, list[str]]" = {}
        for name in self._active_presets:
            groups.setdefault(self._group_key(name), []).append(name)
        return list(groups.values())

    def dimension_label(self, name: str) -> str:
        """차원의 표지 — 지금 열 순서(없는 열은 뒤에 이름 순)로 열 이름, 검색은 「검색」."""
        dim = self.preset_dimension(name)
        ordered = [col for col in self._columns if col in dim]
        ordered += sorted(col for col in dim if col not in self._cols and col != SEARCH_DIMENSION)
        if SEARCH_DIMENSION in dim:
            ordered.append(_SEARCH_DIMENSION_LABEL)
        return "·".join(ordered)

    def dimension_key(self, name: str) -> str:
        """차원의 안정 열쇠 — 열 이름 정렬 후 「·」 연결, 검색은 「검색」(표면 무리 열쇠)."""
        dim = self.preset_dimension(name)
        parts = sorted(col for col in dim if col != SEARCH_DIMENSION)
        if SEARCH_DIMENSION in dim:
            parts.append(_SEARCH_DIMENSION_LABEL)
        return "·".join(parts)

    def preset_description(self, name: str, records: "list[dict]") -> str:
        """저장본의 조건 문안 — 정의줄 조각과 같은 생산자(:func:`_describe_condition`)로 짓는다.

        쓸 수 있는 저장본만 부른다(쓸 수 없는 칩의 설명 자리는 사유가 진다). 검색 조각의 가지는 그
        저장본 자신의 열 조건을 통과한 행에서 산출한다(무리 구성원의 평가와 같은 기준).
        """
        return " · ".join(self._group_parts(self._group(name), records))

    def delete_preset(self, name: str) -> None:
        """저장한 필터 삭제 — 켜져 있었으면 그 무리 구성원도 함께 빠진다."""
        if name not in self._presets:
            raise ValueError(_PRESET_UNKNOWN.format(name=name))
        del self._presets[name]
        self._groups.pop(name, None)
        if name in self._active_presets:
            self._active_presets.remove(name)

    @staticmethod
    def _group_label(names: "list[str]") -> str:
        """켜진 차원 무리 하나의 재진술 — ``필터 '소기업' 또는 '중소기업'``(정의줄·열 머리 공용)."""
        return _PRESET_GROUP_LABEL.format(names=_PRESET_OR.join(f"'{name}'" for name in names))

    def column_constraints(self, column: str) -> "list[str]":
        """이 열을 조이는 것의 문안 — 켜진 저장본 무리(열 머리 표지 소재) + 열 머리 조건.

        열 머리는 켜진 저장본이 조이는 열에도 조건 표지를 세운다(저장본이 곁 평가가 아니라 이
        모델의 무리라서다). 무리 하나는 한 조각(:meth:`_group_label`)이고, 지금 조건은 정의줄 조각
        그대로다. 전체 열 검색은 열을 특정하지 않으므로 싣지 않는다. 빈 목록 = 조이지 않는 열.
        """
        self._require(column)
        parts = [
            self._group_label(names)
            for names in self.active_preset_groups()
            if column in self.preset_columns(names[0])
        ]
        return parts + _describe_condition(column, self._cols[column])

    # ------------------------------------------------ 무리 구성원 평가(열 조건과 같은 술어)
    def _search_branches(
        self, search: str, pruned: "Iterable[str]", passing: "list[dict]",
    ) -> "list[str]":
        """전열 검색의 가지 — 실매치 있는 텍스트 열만, 쳐낸 열 제외(지금 조건·무리 구성원 공용)."""
        skip = set(pruned)
        return [
            col for col in self._columns
            if self._kinds.get(col, KIND_TEXT) == KIND_TEXT
            and col not in skip
            and any(jamo_contains(cell_text(r, col), search) for r in passing)
        ]

    def _group_rows(self, group: _ConditionGroup, records: "list[dict]") -> "set[int]":
        """무리 구성원 하나를 통과하는 행 — 제 열 조건(AND) 그리고 제 검색 OR 가지.

        가지는 제 열 조건을 통과한 행에서 산출한다(저장본은 이름이 가리키는 행을 늘 같은 기준으로
        보인다 — 지금 조건이나 다른 무리가 그 뜻을 바꾸지 않는다).
        """
        rows = [i for i, r in enumerate(records) if self._conds_pass(group.cols, r)]
        if not group.search:
            return set(rows)
        branches = self._search_branches(group.search, group.pruned, [records[i] for i in rows])
        return {
            i for i in rows
            if any(jamo_contains(cell_text(records[i], b), group.search) for b in branches)
        }

    def _group_parts(self, group: _ConditionGroup, records: "list[dict]") -> "list[str]":
        parts: "list[str]" = []
        for col in self._columns:
            if col in group.cols:
                parts.extend(_describe_condition(col, group.cols[col]))
        if group.search:
            passing = [r for r in records if self._conds_pass(group.cols, r)]
            parts.append(_search_part(
                group.search, self._search_branches(group.search, group.pruned, passing),
            ))
        return parts

    # ------------------------------------------------------------- 복제
    def blank_copy(self) -> "FilterModel":
        """같은 열 지형·유형·저장한 필터 정의를 가진 **조건 없는** 모델(원자 교체 초안용)."""
        twin = FilterModel(self._columns, self._kinds)
        twin._presets = copy.deepcopy(self._presets)
        return twin

    def clone(self) -> "FilterModel":
        """무손실 복제 — 정의는 사본, 조건·켜짐은 직렬 상태로 재설치(라이브 캐시 불복사)."""
        twin = self.blank_copy()
        twin.apply_state(self.export_state())
        return twin

    # ------------------------------------------- 정의 이송(직전 필터 슬롯, 결정 28)
    def adhoc_state(self) -> dict:
        """지금 조건(열 조건·검색·프루닝)의 직렬 상태 — 저장본의 모양이자 빌더 프리필 재료."""
        return self._adhoc_state()

    def _adhoc_state(self) -> dict:
        return {
            "search": self._search,
            "pruned": sorted(self._pruned),
            "columns": {
                col: self.column_state(col)
                for col in self._columns if self._cols[col].is_active()
            },
        }

    def export_state(self) -> dict:
        """필터 정의의 직렬 상태 — 직전 필터 슬롯이 세션 사이로 나른다(결정 28).

        검색·프루닝 포함(프루닝 소실 창의 복원은 재적용의 소관 — 결정 27 명문). 활성
        조건이 있는 열만 담는다. **저장이 아니라 전달**이다 — 슬롯은 세션 메모리(앱
        수명)이고 디스크에 남지 않는다(필터 영속 뒷문 금지, 결정 8·24). 켜진 저장한 필터는
        **이름만** 싣는다(정의는 등록 데이터가 든다).
        """
        state = self._adhoc_state()
        if self._active_presets:
            state["active_presets"] = list(self._active_presets)
        return state

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
        # 켜진 저장한 필터는 이름으로 온다 — 정의가 없거나 지금 데이터에서 쓸 수 없으면
        # 열 결손과 같은 탈락 목록으로 돌려준다(부분 설치 + 고지, 호출부 재진술).
        for name in state.get("active_presets") or ():
            label = PRESET_LABEL.format(name=name)
            try:
                self.activate_preset(str(name))
            except ValueError:
                dropped.append(label)
            else:
                installed.append(label)
        return installed, dropped

    def _clear_adhoc(self) -> None:
        self._cols = {c: _ColumnCondition() for c in self._columns}
        self._search = ""
        self._pruned = set()

    def clear(self) -> None:
        """전체 해제 — 열 조건·그룹·프루닝·켜진 저장한 필터 전부(정의는 남는다)."""
        self._clear_adhoc()
        self._active_presets = []

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
        return self._conds_pass(self._cols, record, except_column=except_column)

    def _conds_pass(
        self, conds: "dict[str, _ColumnCondition]", record: "dict", *,
        except_column: "str | None" = None,
    ) -> bool:
        """열 조건 묶음 하나의 AND 술어 — 지금 조건과 저장본 무리 구성원이 같은 술어를 쓴다."""
        for col, cond in conds.items():
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
        # 켜진 저장한 필터의 통과 행 — 뷰 수명 1회 산출. None = 켜진 저장본 없음.
        self._preset_pass: "set[int] | None" = self._compute_preset_pass()
        self.branches: "list[str]" = self._compute_branches()

    # ------------------------------------------------------------- 저장한 필터
    def _compute_preset_pass(self) -> "set[int] | None":
        """켜진 저장본 무리의 합성 — 차원 무리 안은 합집합(또는), 무리 사이는 교집합(그리고).

        구성원은 이 모델이 든 설치된 조건 묶음이고 열 조건과 같은 술어로 평가된다 — 같은 열을
        조이는 두 저장본이 서로의 조건을 덮지 않는 근거는 구성원마다 제 조건을 들기 때문이다.
        켜진 저장본이 없는 차원은 무리가 없으므로 아무것도 조이지 않는다.
        """
        m = self._m
        groups = m.active_preset_groups()
        if not groups:
            return None
        passing: "set[int] | None" = None
        for names in groups:
            union: "set[int]" = set()
            for name in names:
                union |= m._group_rows(m._group(name), self._records)
            passing = union if passing is None else passing & union
        return passing if passing is not None else set()

    def _preset_ok(self, index: int) -> bool:
        return self._preset_pass is None or index in self._preset_pass

    # ------------------------------------------------------------- 가지 산출
    def _compute_branches(self) -> "list[str]":
        """전열 그룹의 가지 — 실매치 있는 텍스트 열만, 프루닝 반영(시안 동형).

        가지 설치 판정은 열 조건을 통과한 행 기준 — 조건이 이미 배제한 행에서만 맞는
        열에 가지를 세우면 재현이 거짓말이 된다.
        """
        m, records = self._m, self._records
        if not m._search:
            return []
        passing = [r for i, r in enumerate(records) if self._preset_ok(i) and m.col_pass(r)]
        return m._search_branches(m._search, m._pruned, passing)

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
            if self._preset_ok(i) and self._m.col_pass(r) and self._group_pass(r)
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
        for i, r in enumerate(self._records):
            if not (
                self._preset_ok(i)
                and self._m.col_pass(r, except_column=column)
                and self._group_pass(r)
            ):
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
    def preset_parts(self) -> "list[str]":
        """켜진 저장한 필터의 재진술 — 차원 무리마다 한 조각, 무리 안은 「또는」(켠 순서).

        무리 사이의 「그리고」는 열 조건 조각 사이처럼 암묵이다(``·`` 로 이어 붙는다).
        """
        return [FilterModel._group_label(names) for names in self._m.active_preset_groups()]

    def describe_parts(self) -> "list[str]":
        """조건별 문안 목록 — 게이트 정의줄이 이어붙여 소비(결정 4 담보).

        켜진 저장한 필터가 앞에, 지금 조건이 뒤에 선다. 칩 줄은 저장한 필터를 자기 칩으로
        그리므로 지금 조건 부분(:meth:`adhoc_chips`)만 「열 조건」 칩으로 쓴다.
        """
        return self.preset_parts() + self.adhoc_parts()

    def adhoc_parts(self) -> "list[str]":
        """지금 조건(열 조건·검색)의 문안 목록 — 정의줄의 뒷부분."""
        return [part for chip in self.adhoc_chips() for part in chip["parts"]]

    def adhoc_chips(self) -> "list[dict]":
        """「열 조건」 칩 소재 — 열 머리에서 건 조건만, 열마다 한 칩(``{column, text, parts}``).

        ``column`` 은 칩의 × 가 지우는 열이다. 전체 열 검색은 ``column == ""`` 인 칩 하나로 말미에
        서고(검색창이 그 편집기라 × 를 달지 않는다), 켜진 저장본의 조이기는 제 칩이 말하므로 여기
        되풀지 않는다. 문안은 정의줄 조각과 같은 생산자다.
        """
        m = self._m
        chips: "list[dict]" = []
        for col in m._columns:
            parts = _describe_condition(col, m._cols[col])
            if parts:
                chips.append({"column": col, "text": " · ".join(parts), "parts": parts})
        if m._search:
            # 선언된 문안 편차 — 시안은 생략하지만 빈 화면의 이유는 재진술해야 한다.
            part = _search_part(m._search, self.branches)
            chips.append({"column": "", "text": part, "parts": [part]})
        return chips

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
