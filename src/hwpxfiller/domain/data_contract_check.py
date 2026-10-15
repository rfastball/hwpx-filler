"""데이터 계약의 관찰과 판정 — 같은 해석기로 행 전체를 렌더해 세고, 받은 데이터를 계약에 댄다(#1188).

**관찰**(:func:`observe_binding`)은 새 렌더러가 아니다. 미리보기·생성과 같은 단일 출처
:func:`~hwpxfiller.domain.mapping.source_value_outcome`(공백 정리 → 가공 → 표시형)를 행마다 그대로
부르고 그 길의 사실만 센다. 행 하나는 정확히 한 칸에 든다(아래 순서대로 첫 번째로 맞는 칸):

1. **빈 값**(``blanks``) — 칸이 없거나(``None``) 공백뿐이다. 생성은 그 자리에 미입력 표식을 넣는다
   (:func:`~hwpxfiller.application.record_validation._resolve_from_source`). 실패가 아니다.
2. **가공 빠짐**(실패) — 가공의 기준 글자·조각·범위가 값에 없다(``TextSlice.evaluate().missed``).
   ``on_missing`` 이 빈 값이든 원본 그대로든 같다: 가공이 뜻한 부분을 이 값에서 찾지 못했다.
3. **빈 값**(``blanks``) — 가공이 빈 부분을 골랐다. 생성은 이 자리에도 같은 표식을 넣는다.
4. **표시형 실패**(실패) — 표시형 해석기가 값을 읽지 못해 원문을 냈다
   (:class:`~hwpxfiller.domain.format_engine.RenderOutcome` ``readable=False``). 유형별로: 날짜는
   날짜(또는 시각 서식의 시각 단독값)로 읽히지 않는 값, 금액은 수로 읽히지 않는 값, 텍스트는
   마스크(전화·사업자번호) 자릿수가 맞지 않는 값이다. 원문 그대로(텍스트 기본) 표시형은 실패가 없다.
5. **성공** — 표시형에 들어간 글자(가공 뒤)로 값 모양 등급과 글자 수를 잰다.

**값 모양 등급**: 성공한 글자 하나가 ``-1,234.5원`` 꼴(부호·자리 쉼표·소수·끝 「원」)이면 ``number``,
아니고 :func:`~hwpxfiller.domain.format_engine.parse_dt` 가 날짜로 읽으면 ``date``, 그 밖은 ``text``다.
열의 등급은 성공한 글자들의 등급이 모두 같으면 그 등급, 섞이면 ``text``, 하나도 없으면 ``empty``다.
글자 수 범위는 기록만 하고 판정에 쓰지 않는다(같은 모양의 길이 변동은 정상이다).

**판정**(:func:`judge_binding`) — 받은 쪽 연결이 통과하는 것은 넷이 모두 설 때뿐이다:
(a) 지금 연결의 지문이 계약 항목의 지문과 같다(편집한 연결은 계약이 말하지 않는다),
(b) 그 열이 받은 데이터에 있다, (c) 받은 데이터의 실패율(실패 ÷ 빈 값이 아닌 행)이 보낸 쪽 관찰치
이하다(보낸 쪽에 빈 값 아닌 행이 없었으면 실패 0 이어야 한다), (d) 값 모양 등급이 같다.
실패면 사유 문장을 여기서 짓는다 — 화면은 판정을 다시 하지 않는다.

한계: 같은 이름·같은 모양의 다른 의미(부가세 포함/미포함 금액)는 가리지 못한다. 그래서 자동확정
행은 표지로 구별된다. 이 모듈은 순수하다(I/O 없음).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .data_contract import (
    SHAPE_DATE,
    SHAPE_EMPTY,
    SHAPE_NUMBER,
    SHAPE_TEXT,
    DataContract,
    FieldContract,
    binding_fingerprint,
)
from .format_engine import parse_dt
from .mapping import SOURCE_CARRIER_TYPES, FieldMapping, MappingProfile, source_value_outcome
from .text_slice import (
    TEXT_SLICE_AFTER,
    TEXT_SLICE_BEFORE,
    TEXT_SLICE_BETWEEN,
    TEXT_SLICE_SPLIT,
    TextSlice,
)

_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(\.\d+)?\s*원?")

#: 판정 사유 문장 — 화면은 이 문장을 그대로 보인다.
REASON_BINDING_CHANGED = "꾸러미와 연결이 다름"
REASON_COLUMN_MISSING = "데이터에 없음"
REASON_ALL_BLANK = "값이 모두 비어 있음"
REASON_SHAPE_CHANGED = "값 모양이 다름"
_FORMAT_FAILURE_REASON = {
    "date": "날짜로 읽히지 않는 값 {n}행",
    "amount": "금액으로 읽히지 않는 값 {n}행",
    "text": "표시형에 맞지 않는 값 {n}행",
}


def value_shape(text: str) -> str:
    """성공한 글자 하나의 모양 등급 — ``number``·``date``·``text``."""
    if _NUMBER_RE.fullmatch(text):
        return SHAPE_NUMBER
    if parse_dt(text) is not None:
        return SHAPE_DATE
    return SHAPE_TEXT


@dataclass
class BindingObservation:
    """연결 하나를 행 전체에 돌린 관찰 — 값은 남기지 않고 칸별 수와 모양만 남는다."""

    rows: int = 0
    blanks: int = 0
    slice_misses: int = 0
    format_failures: int = 0
    shapes: "set[str]" = field(default_factory=set)
    lengths: "list[int]" = field(default_factory=list)

    @property
    def failures(self) -> int:
        return self.slice_misses + self.format_failures

    @property
    def filled(self) -> int:
        return self.rows - self.blanks

    @property
    def shape(self) -> str:
        if not self.shapes:
            return SHAPE_EMPTY
        return next(iter(self.shapes)) if len(self.shapes) == 1 else SHAPE_TEXT

    @property
    def length(self) -> "tuple[int, int] | None":
        return (min(self.lengths), max(self.lengths)) if self.lengths else None

    def count(self, mapping: FieldMapping, raw: object) -> None:
        """레코드 칸 하나를 모듈 docstring 의 다섯 칸 중 하나에 센다."""
        self.rows += 1
        text = "" if raw is None else str(raw)
        if text.strip() == "":
            self.blanks += 1
            return
        outcome = source_value_outcome(mapping.type, text, mapping.fmt, mapping.slice)
        if outcome.slice_missed:
            self.slice_misses += 1
        elif outcome.sliced.strip() == "":
            self.blanks += 1
        elif not outcome.readable:
            self.format_failures += 1
        else:
            self.shapes.add(value_shape(outcome.sliced))
            self.lengths.append(len(outcome.sliced))


def observe_binding(mapping: FieldMapping, records: "Iterable[Mapping[str, object]]") -> BindingObservation:
    """연결 하나를 레코드 전 행에 돌려 센다(열에서 값을 받는 연결만 뜻이 있다)."""
    seen = BindingObservation()
    for record in records:
        seen.count(mapping, record.get(mapping.source))
    return seen


def contract_target(mapping: FieldMapping) -> bool:
    """계약 항목이 서는 연결인가 — 데이터 열에서 값을 받는 연결만(고정값·오늘 날짜는 없다)."""
    return mapping.type in SOURCE_CARRIER_TYPES and bool(mapping.source)


def profile_data_contract(
    profile: MappingProfile, records: "Sequence[Mapping[str, object]]"
) -> DataContract:
    """보낸 쪽 데이터로 작업의 계약을 짓는다 — 연결마다 행 전체를 관찰한 통계(값 없음)."""
    entries = []
    for mapping in profile.mappings:
        if not contract_target(mapping):
            continue
        seen = observe_binding(mapping, records)
        entries.append(FieldContract(
            field=mapping.template_field,
            column=mapping.source,
            binding=binding_fingerprint(mapping),
            rows=seen.rows,
            blanks=seen.blanks,
            failures=seen.failures,
            shape=seen.shape,
            length=seen.length,
        ))
    return DataContract(fields=tuple(entries))


@dataclass(frozen=True)
class ContractVerdict:
    """연결 하나의 계약 판정 — 판정한 연결 지문·통과·사유(통과면 빈 문장)."""

    binding: str
    passed: bool
    reason: str = ""


def _slice_miss_reason(spec: "TextSlice | None", n: int) -> str:
    if spec is None:
        return ""
    if spec.mode in (TEXT_SLICE_BEFORE, TEXT_SLICE_AFTER):
        return f"기준 글자 ‘{spec.delimiter}’가 없는 행 {n}"
    if spec.mode == TEXT_SLICE_BETWEEN:
        return f"기준 글자 ‘{spec.open}’·‘{spec.close}’가 없는 행 {n}"
    if spec.mode == TEXT_SLICE_SPLIT:
        return f"‘{spec.delimiter}’로 나눈 조각이 모자란 행 {n}"
    return f"글자 범위를 벗어난 행 {n}"


def _failure_reason(mapping: FieldMapping, seen: BindingObservation) -> str:
    parts = []
    if seen.slice_misses:
        parts.append(_slice_miss_reason(mapping.slice, seen.slice_misses))
    if seen.format_failures:
        parts.append(_FORMAT_FAILURE_REASON[mapping.type].format(n=seen.format_failures))
    return " · ".join(parts)


def _worse_than(seen: BindingObservation, entry: FieldContract) -> bool:
    """받은 쪽 실패율이 보낸 쪽 관찰치보다 나쁜가 — 분수 비교(부동소수 없음)."""
    if seen.failures == 0:
        return False
    if entry.filled == 0:
        return True
    return seen.failures * entry.filled > entry.failures * seen.filled


def judge_binding(
    entry: FieldContract,
    mapping: FieldMapping,
    columns: "Collection[str]",
    records: "Sequence[Mapping[str, object]]",
) -> ContractVerdict:
    """받은 데이터에서 연결 하나가 계약을 통과하는가 — 모듈 docstring 의 (a)~(d)."""
    binding = binding_fingerprint(mapping)
    if binding != entry.binding:
        return ContractVerdict(binding, False, REASON_BINDING_CHANGED)
    if mapping.source not in columns:
        return ContractVerdict(binding, False, REASON_COLUMN_MISSING)
    seen = observe_binding(mapping, records)
    if _worse_than(seen, entry):
        return ContractVerdict(binding, False, _failure_reason(mapping, seen))
    if seen.shape != entry.shape:
        reason = REASON_ALL_BLANK if seen.shape == SHAPE_EMPTY else REASON_SHAPE_CHANGED
        return ContractVerdict(binding, False, reason)
    return ContractVerdict(binding, True)


def judge_fixed_binding(mapping: FieldMapping, saved: "FieldMapping | None") -> ContractVerdict:
    """데이터를 읽지 않는 연결(고정값·오늘 날짜) — 저장한 연결과 같으면 데이터가 바뀌어도 뜻이 같다."""
    binding = binding_fingerprint(mapping)
    if saved is None or binding_fingerprint(saved) != binding:
        return ContractVerdict(binding, False, REASON_BINDING_CHANGED)
    return ContractVerdict(binding, True)


def judge_job_binding(
    contract: DataContract,
    saved: MappingProfile,
    mapping: FieldMapping,
    columns: "Collection[str]",
    records: "Sequence[Mapping[str, object]]",
) -> "ContractVerdict | None":
    """계약을 든 작업의 연결 하나 — 판정할 근거가 없으면 ``None``(일반 규칙 그대로)."""
    if not contract_target(mapping):
        saved_by_field = {m.template_field: m for m in saved.mappings}
        return judge_fixed_binding(mapping, saved_by_field.get(mapping.template_field))
    entry = contract.entry_for(mapping.template_field)
    if entry is None:
        return None
    return judge_binding(entry, mapping, columns, records)


__all__ = [
    "BindingObservation",
    "ContractVerdict",
    "REASON_ALL_BLANK",
    "REASON_BINDING_CHANGED",
    "REASON_COLUMN_MISSING",
    "REASON_SHAPE_CHANGED",
    "contract_target",
    "judge_binding",
    "judge_fixed_binding",
    "judge_job_binding",
    "observe_binding",
    "profile_data_contract",
    "value_shape",
]
