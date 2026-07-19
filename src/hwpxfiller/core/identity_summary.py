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
- **구별층** — **조건부**. 인지층만으로 남는 충돌을 최대 이득(추가 시 충돌이 가장 많이
  주는) 1열씩 붙여 해소한다. 총 **상한 3열**. 이득 0이면 조용히 정지하고 잔여 충돌은
  파일명 접미사(-001/-002)가 최후 담보한다(완화 조항 자리 — 시끄러울 이유 없음).

**자격 문턱 폐기**(v1 문턱형은 실데이터 반증 3건으로 폐기 — 문턱 널뜀·최소 식별의 재인
빈곤·유일 키 이후 직교성 붕괴). MITM·최적 부분집합도 기각(공간 소멸·안정성·가독성).
고정 체인·가변 깊이다.

## 결격 5종

빈 열 / 상수 열 / 순번 열(값=행 서수, 1씩 증가) / **파일명 내용 토큰**(파일명이 이미
나르는 열 — ``filename_tokens``) / **중복 열**(이미 고른 열과 행별 값이 모두 같은 열).

## 토큰 모드

파일명 패턴이 내용 토큰을 나르면(예 ``공고서-{{품명}}-{{seq}}`` → ``filename_tokens=["품명"]``)
그 열은 파일명이 재인을 담당하므로 **인지층을 생략**하고 구별층만 돌린다 — 요약은
순수 구분자가 된다. 쌍(파일명·요약)이 재인과 구별을 나눠 진다.

이 모듈은 순수 코어다(Qt·웹·소스 어휘 불가지) — 나라장터 등 특정 API 어휘를 담지
않는다. 정본 회귀 케이스 = ``docs/r-flow-mockups/block6-d1-d2-compare-demo.html`` 부록
4장면(나라 53열·합성 함정·토큰 모드·진성 중복 백스톱), 이식은 ``tests/test_identity_summary.py``.
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

_DIGITS = re.compile(r"\d+")


def _norm(value: object) -> str:
    """정규화 — None 은 빈 문자열, 그 외는 문자열화 후 좌우 공백 제거.

    JS 시연의 ``inorm`` 과 동형이라 라이브 계산과 결과가 일치한다.
    """
    return "" if value is None else str(value).strip()


def _column(rows: Sequence[Mapping], col: str) -> list[str]:
    return [_norm(r.get(col)) for r in rows]


def _is_empty(rows: Sequence[Mapping], col: str) -> bool:
    return all(not v for v in _column(rows, col))


def _is_constant(rows: Sequence[Mapping], col: str) -> bool:
    return len(set(_column(rows, col))) <= 1


def _is_ordinal(rows: Sequence[Mapping], col: str) -> bool:
    """값이 행 서수처럼 1씩 증가하는 순번 열인가(연번·행번호 결격)."""
    vals = _column(rows, col)
    if len(vals) < 2 or any(not _DIGITS.fullmatch(v) for v in vals):
        return False
    return all(int(vals[i]) - int(vals[i - 1]) == 1 for i in range(1, len(vals)))


def _is_duplicate(rows: Sequence[Mapping], col: str, chosen: Sequence[str]) -> bool:
    """이미 고른 어느 열과 행별 값이 전부 같은 중복 열인가(직교성 0 → 결격)."""
    return any(
        all(_norm(r.get(col)) == _norm(r.get(d)) for r in rows) for d in chosen
    )


def _eligible(
    rows: Sequence[Mapping], col: str, chosen: Sequence[str], given: Sequence[str]
) -> bool:
    if col in given or col in chosen:
        return False
    if _is_empty(rows, col) or _is_constant(rows, col) or _is_ordinal(rows, col):
        return False
    return not _is_duplicate(rows, col, chosen)


def _collisions(rows: Sequence[Mapping], cols: Sequence[str]) -> int:
    """cols 조합의 값 키가 겹치는(2행 이상 동일) 행의 총수 — 잔여 충돌 규모."""
    keys = ["".join(_norm(r.get(c)) for c in cols) for r in rows]
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

    소비처는 ``columns`` 로 표를 강조하고 :meth:`summary_for` 로 행별 병기 문자열을
    얻는다. 잘라내기·색·중복 표기는 표현 계층 몫이다(코어는 원값 그대로 이어붙인다).
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

    def is_collision(self, rows: Sequence[Mapping], record: Mapping) -> bool:
        """이 레코드의 요약이 집합 안 다른 행과 겹치는가(정직 병기 — 파일명이 가름)."""
        if not self.columns:
            return len(rows) > 1
        key = "".join(_norm(record.get(c)) for c in self.columns)
        same = sum(
            1 for r in rows
            if "".join(_norm(r.get(c)) for c in self.columns) == key
        )
        return same > 1


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

    chosen: list[str] = []
    steps: list[SummaryStep] = []

    # 인지층 — 토큰 모드가 아닐 때만: 왼쪽 스캔 비결격 2열 고정.
    if not given:
        for col in cols:
            if len(chosen) >= COGNITION_WIDTH:
                break
            if _eligible(rows, col, chosen, given):
                chosen.append(col)
                steps.append(SummaryStep("cognition", col, _collisions(rows, chosen)))
    else:
        steps.append(SummaryStep("token-mode"))

    # 구별층 — 조건부: 남는 충돌을 최대 이득 1열씩(상한 3). 이득 0이면 조용히 정지.
    while len(chosen) < MAX_COLUMNS:
        current = _collisions(rows, chosen) if chosen else len(rows)
        if chosen and current == 0:
            break
        best: "int | None" = None
        best_col: "str | None" = None
        for col in cols:
            if not _eligible(rows, col, chosen, given):
                continue
            score = _collisions(rows, chosen + [col])
            if best is None or score < best:  # 동률=왼쪽(첫 최소가 이긴다)
                best = score
                best_col = col
        if best_col is None or (chosen and best is not None and best >= current):
            steps.append(SummaryStep("stop", None, current))
            break
        chosen.append(best_col)
        steps.append(SummaryStep("discrimination", best_col, best))
        if not given and best == 0:  # 완전 해소 → 정지(토큰 모드는 상한까지 계속)
            break

    disq = _disqualifier_stats(rows, cols, chosen, given)
    return IdentitySummary(
        columns=tuple(chosen),
        residual_collisions=_collisions(rows, chosen) if chosen else len(rows),
        token_mode=bool(given),
        steps=tuple(steps),
        disqualified=disq,
    )


def _disqualifier_stats(
    rows: Sequence[Mapping],
    cols: Sequence[str],
    chosen: Sequence[str],
    given: Sequence[str],
) -> DisqualifierStats:
    """결격 열 집계(시연 ``iRejStats`` 동형) — 우선순위 빈>상수>순번>중복."""
    empty = constant = 0
    ordinal: list[str] = []
    duplicate: list[str] = []
    for col in cols:
        if col in given:
            continue
        if _is_empty(rows, col):
            empty += 1
        elif _is_constant(rows, col):
            constant += 1
        elif _is_ordinal(rows, col):
            ordinal.append(col)
        elif col not in chosen and _is_duplicate(rows, col, chosen):
            duplicate.append(col)
    return DisqualifierStats(empty, constant, tuple(ordinal), tuple(duplicate))
