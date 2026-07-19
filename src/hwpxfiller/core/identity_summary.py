"""식별 요약 휴리스틱 v2 — 레코드 집합에서 '어느 데이터의 문서인지' 보조 병기 산출.

R-flow 합의문 결정 37 + 부록 A-1-15·B-4 의 이행. 대표 이름은 **실파일명 정준**이고
식별 요약은 그 옆에 붙는 **보조 병기**다(F33) — 파일명만으로 레코드가 안 갈리는 패턴
(예약 토큰만·상수 패턴·중복 ID 무리)에서도 사용자가 데이터에서 본 그 어휘로 행을
재인·구별하게 한다.

**소비처가 다섯이라(게이트 재진술 블록·충돌 모달·완료 기록·일화 툴팁·블록 3 큐 색인)
링1 단일 함수로 신설**하고 표면 재구현을 금지한다(부록 A-1-15). 표현(잘라내기·색·표)만
링2/웹이 입히고, '어느 열을 쓰는가'라는 판정은 오직 여기서 한 번 내린다.

## 2층 구조(자격 문턱 없음)

- **인지층** — 왼쪽 스캔 비결격 **2열 고정**. 사용자가 데이터 표에서 가장 먼저 읽는
  왼쪽 열을 그대로 병기해 "내가 본 그 데이터"라는 재인을 준다.
- **구별층** — **조건부**. 남는 충돌을 최대 이득(추가 시 충돌이 가장 많이 주는) 1열씩
  붙여 해소한다. 총 **상한 3열**. 이득 0이면 **첫 픽부터** 조용히 정지하고 잔여 충돌은
  파일명 접미사(-001/-002)가 최후 담보한다(완화 조항 자리 — 시끄러울 이유 없음).

**자격 문턱 폐기**(v1 문턱형은 실데이터 반증 3건으로 폐기 — 문턱 널뜀·최소 식별의 재인
빈곤·유일 키 이후 직교성 붕괴). MITM·최적 부분집합도 기각(공간 소멸·안정성·가독성).
고정 체인·가변 깊이다.

## 결격 5종

빈 열 / 상수 열 / 순번 열(**값=행 서수** — 1..N 또는 0..N-1 이 행 위치와 일치) /
**파일명 내용 토큰**(파일명이 이미 나르는 열 — ``filename_tokens``) / **중복 열**(이미
고른 열과 행별 값이 모두 같은 열).

## 토큰 모드

파일명 패턴이 내용 토큰을 나르면(예 ``공고서-{{품명}}-{{seq}}`` → ``filename_tokens=["품명"]``)
그 열은 파일명이 재인을 담당하므로 **인지층을 생략**하고 구별층만 돌린다 — 요약은
순수 구분자가 된다. 쌍(파일명·요약)이 재인과 구별을 나눠 진다.

## 시연 JS(케이스 정본)와의 의도적 편차 2건 — 정합성 우선(PR #91 리뷰)

정본 시연(``docs/r-flow-mockups/block6-d1-d2-compare-demo.html`` 부록 ``iPick``)과 4장면
결과가 일치하되, 시연 스크립트의 잠재 결함 2건은 **고쳐서** 이식했다(4장면 결과는 불변):

1. **충돌 키 구분자** — 시연 ``iColl`` 은 값을 구분자 없이 이어붙여(``join("")``)
   ``'1'+'23'`` 과 ``'12'+'3'`` 이 같은 키가 된다(유령 충돌 → 유령 잔여·불필요한 열
   첨부). 여기선 셀 값에 나타날 수 없는 구분자(U+001F)로 조인해 판정과 표시(``' · '``)가
   갈라지지 않게 한다.
2. **순번 판정** — 시연 ``iOrd`` 는 임의 시작 +1 등차(예 1001,1002,…)도 기각하지만,
   결정 37 문언은 "값=**행 서수**"다. 자동증가 ID(1001 시작)는 행 서수가 아니므로 유일
   식별자로 살린다 — 유일 구별 열의 조용한 소실 방지.

이 모듈은 순수 코어다(Qt·웹·소스 어휘 불가지) — 나라장터 등 특정 API 어휘를 담지
않는다. 회귀 = ``tests/test_identity_summary.py``(4장면 정본 + 리뷰 회귀).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

__all__ = [
    "COGNITION_WIDTH",
    "MAX_COLUMNS",
    "DisqualifierStats",
    "SummaryStep",
    "IdentitySummary",
    "identity_summary",
]

# 인지층 고정 폭(왼쪽 스캔 비결격) + 요약 총 상한(인지 + 구별).
COGNITION_WIDTH = 2
MAX_COLUMNS = 3

# 충돌 키 구분자 — 셀 값에 나타날 수 없는 제어문자(U+001F)로 값 연쇄 모호성을 차단한다.
# 표시 구분자 ' · ' 는 값 안에 나올 수 있어 키로는 못 쓴다(리뷰 #1).
_KEY_SEP = "\x1f"

_DIGITS = re.compile(r"\d+")


def _norm(value: object) -> str:
    """정규화 — None 은 빈 문자열, 그 외는 문자열화 후 좌우 공백 제거(시연 ``inorm`` 동형)."""
    return "" if value is None else str(value).strip()


def _record_key(record: Mapping, cols: Sequence[str]) -> str:
    """레코드의 충돌 키 — 정규화 값들을 모호성 없는 구분자로 조인(판정·표시 정합)."""
    return _KEY_SEP.join(_norm(record.get(c)) for c in cols)


def _is_row_ordinal(vals: Sequence[str]) -> bool:
    """값이 **행 서수**와 일치하는 순번 열인가(1..N 또는 0..N-1) — 결정 37 '값=행 서수'.

    임의 등차수열(예 1001,1002,…)은 순번이 아니다 — 자동증가 ID 는 유일 식별자로
    산다(리뷰 #2). 1행뿐이면 서수 판정 근거가 없어 순번 아님.
    """
    if len(vals) < 2 or any(not _DIGITS.fullmatch(v) for v in vals):
        return False
    nums = [int(v) for v in vals]
    return nums == list(range(1, len(vals) + 1)) or nums == list(range(len(vals)))


def _static_disqualifier(vals: Sequence[str]) -> "str | None":
    """chosen-비의존 결격 판정의 **단일 지점**: ``'empty'|'constant'|'ordinal'|None``.

    선택 루프(``_eligible``)와 결격 집계(``_disqualifier_stats``)가 이 판정 결과를
    공유한다 — 정책이 두 곳으로 갈라져 조용히 어긋나는 것을 막는다(리뷰 #6).
    """
    if all(not v for v in vals):
        return "empty"
    if len(set(vals)) <= 1:
        return "constant"
    if _is_row_ordinal(vals):
        return "ordinal"
    return None


def _is_duplicate(
    vals: Mapping[str, list[str]], col: str, chosen: Sequence[str]
) -> bool:
    """이미 고른 어느 열과 행별 값이 전부 같은 중복 열인가(직교성 0 → 결격)."""
    return any(vals[col] == vals[d] for d in chosen)


def _eligible(
    col: str,
    chosen: Sequence[str],
    given: Sequence[str],
    static: Mapping[str, "str | None"],
    vals: Mapping[str, list[str]],
) -> bool:
    if col in given or col in chosen:
        return False
    if static[col] is not None:
        return False
    return not _is_duplicate(vals, col, chosen)


def _collisions(
    vals: Mapping[str, list[str]], cols: Sequence[str], n_rows: int
) -> int:
    """cols 조합의 키가 겹치는(2행 이상 동일) 행의 총수 — 잔여 충돌 규모.

    빈 cols 는 전 행이 같은 키("") — 2행 이상이면 전부 충돌, 1행이면 0(리뷰 #4:
    충돌 상대가 없는 단일 행을 과대집계하지 않는다).
    """
    keys = [_KEY_SEP.join(vals[c][i] for c in cols) for i in range(n_rows)]
    counts = Counter(keys)
    return sum(n for n in counts.values() if n > 1)


@dataclass(frozen=True)
class DisqualifierStats:
    """결격 요약(일화 툴팁·진단용) — 왜 어떤 열이 빠졌는지 재진술."""

    empty: int = 0
    constant: int = 0
    ordinal: tuple[str, ...] = ()
    duplicate: tuple[str, ...] = ()


@dataclass(frozen=True)
class SummaryStep:
    """체인 한 단계의 구조적 흔적(툴팁이 문장으로 렌더 — 코어는 어휘 불가지).

    ``layer`` = ``"cognition"``(인지층) · ``"token-mode"``(토큰 모드 진입) ·
    ``"discrimination"``(구별층) · ``"stop"``(이득 없어 정지). ``residual`` 은 그 단계
    직후의 잔여 충돌 행 수(정지 단계는 정지 시점의 잔여).
    """

    layer: str
    column: "str | None" = None
    residual: "int | None" = None


@dataclass(frozen=True)
class IdentitySummary:
    """식별 요약 판정 결과 — 어느 열로 요약할지의 단일 출처.

    소비처는 ``columns`` 로 표를 강조하고 :meth:`summary_for` 로 행별 병기 문자열을,
    :meth:`collision_flags` 로 행별 겹침 표기를 얻는다. 잘라내기·색·중복 문구는 표현
    계층 몫이다(코어는 원값 그대로 이어붙인다).
    """

    columns: tuple[str, ...]
    residual_collisions: int
    token_mode: bool
    steps: tuple[SummaryStep, ...]
    disqualified: DisqualifierStats

    def summary_for(self, record: Mapping) -> str:
        """한 레코드의 식별 요약 한 줄 — 고른 열들의 정규화 값을 ``' · '`` 로 병기.

        빈 값도 건너뛰지 않는다(고른 열은 전열 빈칸이 아니지만 개별 셀은 빌 수 있다) —
        시연 ``iOut`` 과 동형. 고른 열이 없으면 빈 문자열.
        """
        return " · ".join(_norm(record.get(c)) for c in self.columns)

    def collision_flags(self, rows: Sequence[Mapping]) -> tuple[bool, ...]:
        """행별 '요약이 집합 안 다른 행과 겹치는가' 일괄 판정(정직 병기 — 파일명이 가름).

        Counter 를 **1회** 구성해 전 행에 재사용한다(시연 ``keyCount`` 동형) — 행마다
        전 행 키를 재구성하는 O(N²) 경로를 소비처에 노출하지 않는 단일 관문이다(리뷰
        #5). 고른 열이 없으면 2행 이상 집합 전체가 겹침(요약이 아무도 못 가름), 1행은
        겹칠 상대가 없어 False.
        """
        keys = [_record_key(r, self.columns) for r in rows]
        counts = Counter(keys)
        return tuple(counts[k] > 1 for k in keys)


def identity_summary(
    rows: Sequence[Mapping],
    columns: "Sequence[str] | None" = None,
    *,
    filename_tokens: Sequence[str] = (),
) -> IdentitySummary:
    """레코드 집합의 식별 요약 판정(결정 37 · 링1 단일 함수).

    :param rows: 원본 레코드(매핑 전 값) 목록 — 사용자가 데이터에서 본 어휘.
    :param columns: 고려할 열 순서(왼쪽=먼저 스캔). 생략 시 첫 행의 키 순서.
    :param filename_tokens: 파일명이 이미 나르는 내용 토큰 열 이름들(토큰 모드 유발).
    :returns: 어느 열로 요약할지 + 잔여 충돌 + 흔적을 담은 :class:`IdentitySummary`.

    빈 집합·모든 열 결격이면 빈 ``columns`` 를 돌려준다(요약 없이 파일명만).
    """
    rows = list(rows)
    given = list(filename_tokens)
    if columns is None:
        cols = list(rows[0].keys()) if rows else []
    else:
        cols = list(columns)

    if not rows or not cols:
        return IdentitySummary((), 0, bool(given), (), DisqualifierStats())

    n = len(rows)
    # 열별 정규화 값·정적 결격을 1회 계산해 선택 루프와 결격 집계가 공유한다(리뷰 #6).
    vals: dict[str, list[str]] = {c: [_norm(r.get(c)) for r in rows] for c in cols}
    static: dict[str, "str | None"] = {c: _static_disqualifier(vals[c]) for c in cols}

    chosen: list[str] = []
    steps: list[SummaryStep] = []

    # 인지층 — 토큰 모드가 아닐 때만: 왼쪽 스캔 비결격 2열 고정.
    if not given:
        for col in cols:
            if len(chosen) >= COGNITION_WIDTH:
                break
            if _eligible(col, chosen, given, static, vals):
                chosen.append(col)
                steps.append(
                    SummaryStep("cognition", col, _collisions(vals, chosen, n))
                )
    else:
        steps.append(SummaryStep("token-mode"))

    # 구별층 — 조건부: 남는 충돌을 최대 이득 1열씩(상한 3). 이득 0이면 **첫 픽부터**
    # 조용히 정지한다(리뷰 #3 — 비구별 열을 구별자인 양 제시하지 않는다).
    while len(chosen) < MAX_COLUMNS:
        current = _collisions(vals, chosen, n)
        if current == 0:
            break  # 완전 해소(또는 가를 상대 없음) — 더 붙일 이유 없음
        best: "int | None" = None
        best_col: "str | None" = None
        for col in cols:
            if not _eligible(col, chosen, given, static, vals):
                continue
            score = _collisions(vals, chosen + [col], n)
            if best is None or score < best:  # 동률=왼쪽(첫 최소가 이긴다)
                best = score
                best_col = col
        if best_col is None or (best is not None and best >= current):
            steps.append(SummaryStep("stop", None, current))
            break
        chosen.append(best_col)
        steps.append(SummaryStep("discrimination", best_col, best))

    return IdentitySummary(
        columns=tuple(chosen),
        residual_collisions=_collisions(vals, chosen, n),
        token_mode=bool(given),
        steps=tuple(steps),
        disqualified=_disqualifier_stats(cols, static, vals, chosen, given),
    )


def _disqualifier_stats(
    cols: Sequence[str],
    static: Mapping[str, "str | None"],
    vals: Mapping[str, list[str]],
    chosen: Sequence[str],
    given: Sequence[str],
) -> DisqualifierStats:
    """결격 열 집계(시연 ``iRejStats`` 동형) — 정적 결격은 선택 루프와 같은 판정을 공유.

    중복 열만 최종 ``chosen`` 기준으로 재판정한다(chosen 의존 술어라 재판정이 필요 —
    정책 자체는 :func:`_is_duplicate` 단일 정의, 리뷰 #6).
    """
    empty = constant = 0
    ordinal: list[str] = []
    duplicate: list[str] = []
    for col in cols:
        if col in given:
            continue
        kind = static[col]
        if kind == "empty":
            empty += 1
        elif kind == "constant":
            constant += 1
        elif kind == "ordinal":
            ordinal.append(col)
        elif col not in chosen and _is_duplicate(vals, col, chosen):
            duplicate.append(col)
    return DisqualifierStats(empty, constant, tuple(ordinal), tuple(duplicate))
