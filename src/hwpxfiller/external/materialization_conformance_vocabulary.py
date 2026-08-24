"""materialization postcondition 실패 어휘와 결과 합타입 — **매체 중립**(S10-04 · #861).

SG-02(#734)가 HWPX 위에 세운 9 실패 코드와 PASS/FAIL 합타입은 실은 매체의 사실이 아니라
**후행조건의 종류**다: 되읽지 못했다 · 지울 것이 남았다 · 지키기로 한 것이 사라졌다 · 값이
다르다 · 등장 수가 다르다 · 마커가 남았다 · 보호 구조가 깨졌다 · 원본이 변했다 · 선언 구조가
bytes 와 어긋난다. TXT materializer 가 같은 질문을 같은 이름으로 묻게 이 어휘를 여기로 옮겼다.

값은 **한 글자도 바뀌지 않았다** — :mod:`hwpxfiller.external.materialization_conformance` 가
그대로 re-export 하므로 기존 import 경로·문자열·타입 identity 가 전부 유지된다. 특히
:class:`ConformanceFailure` 가 한 클래스로 남는 것이 계약이다: delivery coordinator 가 이
concrete 타입으로 실패를 가르므로, 매체마다 다른 클래스를 세우면 안착 층이 매체를 알게 된다.

이 모듈은 lxml·hwpxcore·zipfile 을 모른다(그래서 평문 materializer 가 XML kernel 을 끌고 오지
않는다).
"""

from __future__ import annotations

from dataclasses import dataclass

from hwpxfiller.domain.fields import FillNote

# ─── distinct failure code(층 구분 유지 — serialize/reparse/postcondition 분리) ─────────
STRUCTURE_BYTES_INCONSISTENT = "STRUCTURE_BYTES_INCONSISTENT"  # P7 precheck
REPARSE_FAILED = "REPARSE_FAILED"  # P0
REMOVAL_INCOMPLETE = "REMOVAL_INCOMPLETE"  # P1
PRESERVED_CONTENT_LOST = "PRESERVED_CONTENT_LOST"  # P2
FIELD_TEXT_MISMATCH = "FIELD_TEXT_MISMATCH"  # P3
OCCURRENCE_COUNT_MISMATCH = "OCCURRENCE_COUNT_MISMATCH"  # P3
MARKER_CLEANUP_VIOLATION = "MARKER_CLEANUP_VIOLATION"  # P4
PROTECTED_STRUCTURE_LOSS = "PROTECTED_STRUCTURE_LOSS"  # P5
SOURCE_CANDIDATE_MUTATED = "SOURCE_CANDIDATE_MUTATED"  # P6


class ConformanceExecutionError(Exception):
    """executor 가 Plan/VDR 로 시퀀싱할 수 없는 상태 — 조용히 넘기지 않는다."""


@dataclass(frozen=True)
class ConformancePass:
    """모든 postcondition 이 actual reopened output 에서 충족됨."""

    output_digest: str
    notes: tuple[FillNote, ...] = ()


@dataclass(frozen=True)
class ConformanceFailure:
    """actual mutation 결과가 postcondition 을 위반 — distinct code 로 재진술."""

    code: str
    detail: str


ConformanceResult = ConformancePass | ConformanceFailure


@dataclass(frozen=True)
class MaterializedDocumentBytes:
    """postcondition PASS 를 통과한 materialization 산출 — bytes 와 그 증거.

    ``execution_notes`` 는 채움이 「경고 후 진행」으로 처리한 완화 사실(FillNote)로, 삼키지
    않고 상위(delivery·원장)가 record/warn 하게 나른다(confirm-or-alarm).

    **매체마다 다른 클래스를 세우지 않는다**(S10-04 · #861): delivery coordinator 가 이
    concrete 타입으로 성공/실패를 가르므로, 타입을 가르면 안착 층이 매체를 알게 된다.
    """

    plan_semantic_digest: str
    validated_record_ref: str
    output_bytes: bytes
    output_digest: str
    execution_notes: tuple[FillNote, ...]


MaterializationOutcome = MaterializedDocumentBytes | ConformanceFailure


__all__ = [
    "FIELD_TEXT_MISMATCH",
    "MARKER_CLEANUP_VIOLATION",
    "OCCURRENCE_COUNT_MISMATCH",
    "PRESERVED_CONTENT_LOST",
    "PROTECTED_STRUCTURE_LOSS",
    "REMOVAL_INCOMPLETE",
    "REPARSE_FAILED",
    "SOURCE_CANDIDATE_MUTATED",
    "STRUCTURE_BYTES_INCONSISTENT",
    "ConformanceExecutionError",
    "ConformanceFailure",
    "ConformancePass",
    "ConformanceResult",
    "MaterializationOutcome",
    "MaterializedDocumentBytes",
]
