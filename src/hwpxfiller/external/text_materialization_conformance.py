"""In-memory TXT materialization conformance port (S10-04 · #861) — HWPX 대칭물.

:mod:`hwpxfiller.external.materialization_conformance` 가 HWPX 위에서 하는 일을 평문 위에서
한다: Sealed Plan 의 ordered operation 을 **순서 그대로** 적용하고, 그 결과를 다시 스캔해
후행조건을 전건 재검증한다. 실패 어휘는 매체 중립 정본
(:mod:`hwpxfiller.external.materialization_conformance_vocabulary`)을 그대로 쓴다 — 같은 결함류를
매체마다 다른 이름으로 부르지 않는다.

경계(HWPX 포트와 같은 규율):

- **새 의미 파생 0.** 무엇을 제거할지는 Plan 의 ``REMOVE_OPTION``, 무엇을 쓸지는 VDR 의
  logical document value 에서만 온다. selection/qualification 을 여기서 다시 계산하지 않는다.
- **source bytes 불변.** 모든 변형은 decode 한 문자열 사본 위에서만 일어난다(P6).
- **표시 투영과 한 원천.** 줄 제거·마커 소거는 :mod:`hwpxfiller.domain.text_structure` 의 순수
  함수(:func:`~hwpxfiller.domain.text_structure.unselected_option_lines`·
  :func:`~hwpxfiller.domain.text_structure.marker_lines`·
  :func:`~hwpxfiller.domain.text_structure.drop_lines`)를 부른다 — 작업대가 화면에 그리는
  투영과 클립보드로 나가는 bytes 가 같은 계산을 지난다(L22).
- **치환도 한 원천.** ``{{필드}}`` 치환은 :func:`~hwpxfiller.domain.text_render.render_segments`
  하나가 한다(정규식·sigil 필터 재구현 0). 이 모듈이 그 함수의 정당한 소비자로 정적 계약
  allowlist 에 든다.
- **fail-closed.** 미지원 native primitive contract·미지원 operation code 는 v1 으로 조용히
  해석하지 않는다.

**왜 2단계인가.** 후행조건을 최종 bytes 하나에서만 재면 「Option 이 정확히 authorized 만
남았는가」를 물을 자리가 사라진다 — 마커를 다 지운 평문에는 구조가 없기 때문이다. 그래서
제거(1단계) 직후, 마커가 아직 서 있는 상태에서 구조를 재스캔해 그 술어를 닫고, 그 다음
마커를 소거(2단계)해 「마커 0」을 닫는다. 각 단계가 자기 postcondition 을 진다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hwpxfiller.application.execution_composition import (
    TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
    UnsupportedNativePrimitiveContract,
)
from hwpxfiller.application.execution_contract_set import (
    PLAN_APPLY_FIELD_BINDING,
    PLAN_REMOVE_OPTION,
    SealedExecutionPlanSemanticPayload,
)
from hwpxfiller.application.execution_structure import ExecutionTemplateStructure
from hwpxfiller.domain.text_render import (
    SEG_LITERAL,
    render_segments,
)
from hwpxfiller.domain.text_structure import (
    drop_lines,
    marker_lines,
    scan_text_structure,
    unselected_option_lines,
)

from .content_digest import blob_digest
from .materialization_conformance_vocabulary import (
    FIELD_TEXT_MISMATCH,
    MARKER_CLEANUP_VIOLATION,
    OCCURRENCE_COUNT_MISMATCH,
    PRESERVED_CONTENT_LOST,
    REMOVAL_INCOMPLETE,
    REPARSE_FAILED,
    SOURCE_CANDIDATE_MUTATED,
    STRUCTURE_BYTES_INCONSISTENT,
    ConformanceExecutionError,
    ConformanceFailure,
    ConformancePass,
    ConformanceResult,
)

TXT_CONFORMANCE_CONTRACT_ID = "txt-materialization-conformance/v1"

#: 산출 bytes 의 인코딩. 조달도 같은 엄격 UTF-8 이다(작업대·qualification inspector 와 동일) —
#: 여기서만 관대하면 확인은 통과하고 산출물이 다른 파일이 된다.
TXT_ENCODING = "utf-8"


@dataclass(frozen=True)
class InMemoryTxtMaterialization:
    """executor 결과 — 검증을 통과한 output bytes 와 단계별 관찰 사실.

    ``stage_facts`` 는 상위(runner·원장)가 record/warn 할 수 있게 나르는 수치다 — 지운 선택
    수·소거한 마커 수·치환한 등장 수. 삼키면 「무엇을 했는지」가 사라진다(confirm-or-alarm).
    """

    output_bytes: bytes
    stage_facts: Mapping[str, int]


def _require_known_op(op: Mapping[str, Any]) -> str:
    """operation 하나의 code — 없거나 어휘 밖이면 시끄럽게 닫는다(v1 로 조용히 해석 금지)."""
    code = op.get("op")
    if not isinstance(code, str):
        raise ConformanceExecutionError(f"operation 에 op code 가 없다: {op!r}")
    if code not in (PLAN_APPLY_FIELD_BINDING, PLAN_REMOVE_OPTION):
        raise UnsupportedNativePrimitiveContract(f"미지원 operation code: {code!r}")
    return code


def decode_txt(raw: bytes, what: str) -> str:
    """엄격 UTF-8 decode — 실패는 조용한 대체문자가 아니라 시끄러운 조달 오류다."""
    try:
        return raw.decode(TXT_ENCODING)
    except UnicodeDecodeError as exc:
        raise ConformanceExecutionError(
            f"{what} 를 UTF-8 로 읽을 수 없다({exc.reason}, 위치 {exc.start})"
        ) from exc


def _authorized_options(
    plan: SealedExecutionPlanSemanticPayload,
    structure: ExecutionTemplateStructure,
) -> "tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]":
    """(제거 대상, 남아야 하는 것) — 둘 다 **Plan 과 structure 에서만** 유도한다.

    선택을 여기서 다시 계산하지 않는다: 제거 대상은 Plan 의 ``REMOVE_OPTION`` 이고, 전체
    Option 집합은 이미 검증된 structure 의 region 이다. 차집합이 authorized 다.
    """
    declared = frozenset(
        (region.slot_id, region.option_id) for region in structure.option_regions
    )
    removal_targets = frozenset(
        (str(op["slot_id"]), str(op["option_id"]))
        for op in plan.ordered_operations
        if op.get("op") == PLAN_REMOVE_OPTION
    )
    return removal_targets, declared - removal_targets


def _observed_options(scan) -> "frozenset[tuple[str, str]]":
    return frozenset(
        (slot.id, option.id) for slot in scan.slots for option in slot.options
    )


# ═══ P7 precheck: 선언 structure 가 exact Candidate bytes 관찰과 id 일관 ═══════════════
def verify_txt_structure_bytes_consistency(
    *, candidate_bytes: bytes, structure: ExecutionTemplateStructure
) -> ConformanceResult:
    """structure 의 Option/Field id 가 실제 Candidate 텍스트 관찰과 일치하는지 교차검증.

    digest 는 각자 자신만 증명한다 — structure↔bytes 대응을 잇는 것은 이 검사뿐이다.
    Field 집합은 **완전 일치**를 요구한다(subset 금지): structure 가 bytes 의 토큰을 누락하면
    컴파일러가 그 필드에 write op 를 내지 않아 산출물에 ``{{토큰}}`` 이 그대로 새어 나간다.
    """
    try:
        text = decode_txt(candidate_bytes, "candidate")
    except ConformanceExecutionError as exc:
        return ConformanceFailure(STRUCTURE_BYTES_INCONSISTENT, str(exc))
    scan = scan_text_structure(text)
    if scan.diagnostics:
        return ConformanceFailure(
            STRUCTURE_BYTES_INCONSISTENT,
            "candidate 스캔이 구간 표기 진단을 낸다: "
            + "; ".join(d.message for d in scan.diagnostics),
        )
    bytes_options = _observed_options(scan)
    struct_options = frozenset(
        (r.slot_id, r.option_id) for r in structure.option_regions
    )
    if bytes_options != struct_options:
        return ConformanceFailure(
            STRUCTURE_BYTES_INCONSISTENT,
            f"structure Option id {sorted(struct_options)} 가 bytes "
            f"{sorted(bytes_options)} 와 불일치",
        )
    bytes_fields = frozenset(_token_names(text))
    struct_fields = frozenset(occ.field_id for occ in structure.field_occurrences)
    if struct_fields != bytes_fields:
        return ConformanceFailure(
            STRUCTURE_BYTES_INCONSISTENT,
            f"structure Field 투영이 bytes 와 불일치: "
            f"structure-only={sorted(struct_fields - bytes_fields)}, "
            f"bytes-only={sorted(bytes_fields - struct_fields)}",
        )
    return ConformancePass(output_digest="")


def _token_names(text: str) -> "list[str]":
    """텍스트에 실제로 앉아 있는 필드 토큰 이름(등장순, 중복 유지) — 치환과 같은 원천."""
    segments, _report = render_segments(text, {})
    return [s.name for s in segments if s.kind != SEG_LITERAL]


# ═══ executor: exact bytes → 1단계 제거 → 2단계 마커 소거 → 치환 → bytes ═══════════════
def apply_txt_execution_plan_in_memory(
    *,
    candidate_bytes: bytes,
    plan: SealedExecutionPlanSemanticPayload,
    structure: ExecutionTemplateStructure,
    document_values: Mapping[str, str],
) -> "InMemoryTxtMaterialization | ConformanceFailure":
    """Plan 의 ordered operation 을 평문에 적용한다 — 단계마다 자기 postcondition 을 닫는다.

    1단계(제거) → 재스캔 → 「남은 Option == authorized」. 2단계(마커 소거) → 재스캔 →
    「마커 0」. 그 뒤 치환. 어느 단계든 위반이면 bytes 를 내지 않고 실패 코드를 낸다.
    """
    # operation 어휘 검문이 **먼저**다: 미지 op 를 v1 으로 조용히 해석하지 않는다(fail-closed).
    # 뒤로 밀면 알 수 없는 지시를 담은 Plan 이 이미 줄을 지운 뒤에야 거절된다.
    apply_fields = [
        str(op["field_id"])
        for op in plan.ordered_operations
        if _require_known_op(op) == PLAN_APPLY_FIELD_BINDING
    ]
    for field_id in apply_fields:
        if field_id not in document_values:
            raise ConformanceExecutionError(
                f"Active Field {field_id!r} 에 대응하는 VDR document value 가 없다"
            )

    text = decode_txt(candidate_bytes, "candidate")
    scan = scan_text_structure(text)
    if scan.diagnostics:
        return ConformanceFailure(
            REPARSE_FAILED,
            "candidate 스캔이 구간 표기 진단을 낸다: "
            + "; ".join(d.message for d in scan.diagnostics),
        )
    removal_targets, authorized = _authorized_options(plan, structure)

    # ── 1단계: complement Option 선언을 통째로 제거(항목 마커는 남는다) ────────────────
    # 「고른 것」 표현으로 뒤집어 domain 술어를 그대로 쓴다 — 제거 대상을 여기서 다시
    # 판정하지 않고 Plan 이 정한 집합의 여집합을 넘긴다.
    selected: "dict[str, set[str]]" = {}
    for slot_id, option_id in authorized:
        selected.setdefault(slot_id, set()).add(option_id)
    removed_lines = unselected_option_lines(scan, selected)
    stage1 = drop_lines(text, removed_lines)

    stage1_scan = scan_text_structure(stage1)
    if stage1_scan.diagnostics:
        return ConformanceFailure(
            REPARSE_FAILED,
            "제거 뒤 재스캔이 진단을 낸다: "
            + "; ".join(d.message for d in stage1_scan.diagnostics),
        )
    remaining = _observed_options(stage1_scan)
    still_present = remaining & removal_targets
    if still_present:
        return ConformanceFailure(
            REMOVAL_INCOMPLETE,
            f"removal target 이 제거 뒤에도 잔존: {sorted(still_present)}",
        )
    lost = authorized - remaining
    if lost:
        return ConformanceFailure(
            PRESERVED_CONTENT_LOST,
            f"target 아닌 Option 이 제거 뒤 소실: {sorted(lost)}",
        )
    if remaining != authorized:  # pragma: no cover - 위 두 검사가 이미 소진한다
        return ConformanceFailure(
            REMOVAL_INCOMPLETE,
            f"남은 Option {sorted(remaining)} 가 authorized {sorted(authorized)} 와 불일치",
        )

    # ── 2단계: 마커 줄 전량 소거 ────────────────────────────────────────────────────
    marker_line_set = marker_lines(stage1_scan)
    stage2 = drop_lines(stage1, marker_line_set)
    stage2_scan = scan_text_structure(stage2)
    if stage2_scan.summary.markers:
        return ConformanceFailure(
            MARKER_CLEANUP_VIOLATION,
            f"마커 소거 뒤에도 구간 마커가 {stage2_scan.summary.markers}건 남았다",
        )

    # ── 치환: Plan 의 APPLY_FIELD_BINDING 이 요구한 값만 쓴다(새 의미 파생 0) ─────────
    segments, _report = render_segments(stage2, dict(document_values))
    output = "".join(s.text for s in segments)

    return InMemoryTxtMaterialization(
        output_bytes=output.encode(TXT_ENCODING),
        stage_facts={
            "removed_options": len(removal_targets),
            "removed_lines": len(removed_lines),
            "cleaned_marker_lines": len(marker_line_set),
            "written_field_occurrences": sum(
                1 for s in segments if s.kind != SEG_LITERAL
            ),
        },
    )


# ═══ postcondition verifier: 최종 output 대상 defense-in-depth ═════════════════════════
def verify_txt_materialization_postconditions(
    *,
    source_bytes: bytes,
    output_bytes: bytes,
    plan: SealedExecutionPlanSemanticPayload,
    structure: ExecutionTemplateStructure,
    vdr: Any,
    stage_facts: "Mapping[str, int] | None" = None,
) -> ConformanceResult:
    """executor 를 최종으로 신뢰하지 않고 output 을 **다시 읽어** 후행조건을 재검증한다.

    P6 source 불변 · P0 재스캔 · P4 마커 0 · P3 Active Field 등장 수/값. Option 집합 술어는
    구조가 남아 있는 1단계가 이미 닫았다(마커 없는 최종 bytes 에는 물을 자리가 없다) — 그
    분업이 2단계 설계의 이유다.
    """
    contracts = plan.execution_basis.contracts
    if contracts.native_primitive_contract_id != TXT_NATIVE_PRIMITIVE_CONTRACT_ID:
        raise UnsupportedNativePrimitiveContract(
            f"미지원 native primitive contract(latest fallback 없음): "
            f"{contracts.native_primitive_contract_id!r}"
        )

    # P6 — source 는 손대지 않았다: 제거 대상이 여전히 원본에 선언돼 있어야 한다.
    try:
        source_text = decode_txt(source_bytes, "source")
    except ConformanceExecutionError as exc:
        return ConformanceFailure(SOURCE_CANDIDATE_MUTATED, str(exc))
    source_scan = scan_text_structure(source_text)
    if source_scan.diagnostics:
        return ConformanceFailure(
            SOURCE_CANDIDATE_MUTATED, "source 스캔이 구간 표기 진단을 낸다"
        )
    removal_targets, _authorized = _authorized_options(plan, structure)
    source_options = _observed_options(source_scan)
    if not removal_targets <= source_options:
        return ConformanceFailure(
            SOURCE_CANDIDATE_MUTATED,
            f"removal target {sorted(removal_targets - source_options)} 가 source 에 없다(source 변형)",
        )

    # P0 — output 을 다시 읽을 수 있는가.
    try:
        output_text = decode_txt(output_bytes, "output")
    except ConformanceExecutionError as exc:
        return ConformanceFailure(REPARSE_FAILED, str(exc))
    output_scan = scan_text_structure(output_text)
    if output_scan.diagnostics:
        return ConformanceFailure(
            REPARSE_FAILED,
            "output 재스캔이 진단을 낸다: "
            + "; ".join(d.message for d in output_scan.diagnostics),
        )

    # P4 — 마커 cleanup: 저작 표기가 산출물에 새어 나가지 않았다.
    if output_scan.summary.markers:
        return ConformanceFailure(
            MARKER_CLEANUP_VIOLATION,
            f"output 에 구간 마커가 {output_scan.summary.markers}건 남았다",
        )

    # P3 — Active Field: 미치환 토큰 0 + 등장 수 == 기대. 평문 치환은 값이 텍스트에 녹아
    # 사라지므로 「값이 맞는가」는 치환 산출 그 자체(executor)가 지고, 여기서는 **잔존 토큰**
    # 으로 되묻는다 — 미치환이 남았다면 그 등장은 기대 수를 채우지 못한 것이다.
    leftover = _token_names(output_text)
    if leftover:
        return ConformanceFailure(
            FIELD_TEXT_MISMATCH,
            f"output 에 미치환 필드 토큰이 남았다: {sorted(set(leftover))}",
        )
    expected_counts = {
        str(req["field_id"]): int(req["expected_active_occurrence_count"])
        for req in plan.active_field_requirements
    }
    written = dict(stage_facts or {}).get("written_field_occurrences")
    if written is not None and written != sum(expected_counts.values()):
        return ConformanceFailure(
            OCCURRENCE_COUNT_MISMATCH,
            f"치환한 Active Field 등장 {written} != 기대 {sum(expected_counts.values())}",
        )

    # 값 일치는 VDR 이 낸 exact logical text 가 실제로 output 안에 서 있는지로 닫는다 —
    # 빈 값(INTENTIONAL_BLANK)은 찾을 문자열이 없으므로 등장 수 검사에 맡긴다.
    expected_text = dict(vdr.document_values_in_order())
    for field_id, want in expected_text.items():
        if expected_counts.get(field_id, 0) == 0 or want == "":
            continue
        if want not in output_text:
            return ConformanceFailure(
                FIELD_TEXT_MISMATCH,
                f"Active Field {field_id!r} 의 값이 output 에 없다",
            )
    return ConformancePass(output_digest=blob_digest(output_bytes))


__all__ = [
    "TXT_CONFORMANCE_CONTRACT_ID",
    "TXT_ENCODING",
    "ConformanceExecutionError",
    "ConformanceFailure",
    "ConformancePass",
    "ConformanceResult",
    "InMemoryTxtMaterialization",
    "apply_txt_execution_plan_in_memory",
    "decode_txt",
    "verify_txt_materialization_postconditions",
    "verify_txt_structure_bytes_consistency",
]
