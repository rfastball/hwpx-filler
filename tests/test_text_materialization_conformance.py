"""TXT materialization conformance(S10-04 #861) — 2단계 실행과 **단계별** 후행조건.

여기서 재는 것은 하나다: **postcondition 이 자격이다.** 제거·소거·치환이 호출됐다는 사실로
bytes 를 내지 않고, 각 단계 직후 재스캔이 그 단계의 술어를 닫아야만 산출이 선다.

그래서 위반을 **주입**한다. 도메인 primitive(줄 집합 계산)를 고장 낸 채 executor 를 돌려,
각 단계가 자기 코드로 시끄럽게 닫히는지 본다 — 「검사는 있는데 결과를 못 본다」(U2 §2.11
표본)를 피하는 유일한 방법이 실제로 틀린 것을 통과시켜 보는 것이다.

Plan/VDR 은 얇은 대역이다(이 층은 그 둘에서 **읽기만** 한다 — 새 의미 파생 0이 계약이라
진짜 봉인 기계를 여기 끌어오면 무엇이 깨졌는지 실패가 말해 주지 않는다). 실 봉인 왕복은
``tests/test_txt_materialization.py`` 가 진다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hwpxfiller.application.execution_composition import (
    TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
    UnsupportedNativePrimitiveContract,
)
from hwpxfiller.domain.structure_scan import PLACEMENT_OPTION
from hwpxfiller.external import text_materialization_conformance as tmc
from hwpxfiller.external.materialization_conformance_vocabulary import (
    FIELD_TEXT_MISMATCH,
    MARKER_CLEANUP_VIOLATION,
    OCCURRENCE_COUNT_MISMATCH,
    PRESERVED_CONTENT_LOST,
    REMOVAL_INCOMPLETE,
    REPARSE_FAILED,
    SOURCE_CANDIDATE_MUTATED,
    STRUCTURE_BYTES_INCONSISTENT,
    ConformanceFailure,
    ConformancePass,
)
from hwpxfiller.external.text_template_inspection import inspect_txt_qualification

BODY = "\n".join(
    [
        "수신: {{수신}}",
        "{{#항목 첨부 첨부 서류}}",
        "담당자: {{담당자}}",
        "{{#선택 계약서 계약서}}",
        "계약서를 첨부합니다. {{건명}}",
        "{{/선택}}",
        "{{#선택 견적서 견적서}}",
        "견적서를 첨부합니다.",
        "{{/선택}}",
        "{{/항목}}",
        "끝.",
        "",
    ]
)

VALUES = {"수신": "○○청", "담당자": "홍길동", "건명": "무언가"}


def _structure(body: str = BODY):
    execution = inspect_txt_qualification(body.encode("utf-8")).execution_structure
    assert execution is not None
    return execution


def _plan(
    *,
    removals=(("첨부", "계약서"),),
    applies=("수신", "담당자"),
    native: str = TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
    counts=None,
):
    """얇은 Plan 대역 — 이 층이 실제로 읽는 세 축(op·requirement·native contract)만 담는다."""
    counts = counts or {name: 1 for name in applies}
    return SimpleNamespace(
        ordered_operations=tuple(
            {"op": "REMOVE_OPTION", "slot_id": slot, "option_id": option}
            for slot, option in removals
        )
        + tuple({"op": "APPLY_FIELD_BINDING", "field_id": name} for name in applies),
        active_field_requirements=tuple(
            {"field_id": name, "expected_active_occurrence_count": counts[name]}
            for name in applies
        ),
        execution_basis=SimpleNamespace(
            contracts=SimpleNamespace(native_primitive_contract_id=native)
        ),
    )


def _vdr(values=None):
    items = tuple((values or VALUES).items())
    return SimpleNamespace(document_values_in_order=lambda: items)


def _apply(plan=None, structure=None, values=None, body: str = BODY):
    return tmc.apply_txt_execution_plan_in_memory(
        candidate_bytes=body.encode("utf-8"),
        plan=plan or _plan(),
        structure=structure or _structure(body),
        document_values=values or VALUES,
    )


# ── 정상 왕복 ────────────────────────────────────────────────────────────────
def test_two_stages_leave_only_the_authorized_option_and_zero_markers() -> None:
    result = _apply()
    assert isinstance(result, tmc.InMemoryTxtMaterialization)
    text = result.output_bytes.decode("utf-8")
    assert text == "수신: ○○청\n담당자: 홍길동\n견적서를 첨부합니다.\n끝.\n"
    # 마커도, 고르지 않은 선택지 내용도 남지 않는다.
    assert "{{#" not in text and "{{/" not in text
    assert "계약서를 첨부합니다." not in text
    assert result.stage_facts["removed_options"] == 1
    assert result.stage_facts["cleaned_marker_lines"] == 4  # 항목 2 + 남은 선택 2


def test_postconditions_pass_on_the_actual_output() -> None:
    executed = _apply()
    assert isinstance(executed, tmc.InMemoryTxtMaterialization)
    verdict = tmc.verify_txt_materialization_postconditions(
        source_bytes=BODY.encode("utf-8"),
        output_bytes=executed.output_bytes,
        plan=_plan(),
        structure=_structure(),
        vdr=_vdr(),
        stage_facts=executed.stage_facts,
    )
    assert isinstance(verdict, ConformancePass)
    assert verdict.output_digest.startswith("sha256:")


# ── 단계별 위반 주입(산출물 불인정) ───────────────────────────────────────────
def test_stage_one_catches_a_removal_that_did_not_happen(monkeypatch) -> None:
    """1단계가 complement 를 못 지웠으면 REMOVAL_INCOMPLETE — 마커가 남아 있어 물을 수 있다."""
    monkeypatch.setattr(tmc, "unselected_option_lines", lambda scan, selected: frozenset())
    result = _apply()
    assert isinstance(result, ConformanceFailure)
    assert result.code == REMOVAL_INCOMPLETE
    assert "계약서" in result.detail


def test_stage_one_catches_an_authorized_option_that_was_swept_away(monkeypatch) -> None:
    """지키기로 한 선택까지 지웠으면 PRESERVED_CONTENT_LOST — 제거 초과와 다른 이름이다."""

    def _sweep_everything(scan, selected):
        lines: set[int] = set()
        for placement in scan.placements:
            if placement.kind == PLACEMENT_OPTION:
                lines.update(
                    range(placement.begin_marker_line, placement.end_marker_line + 1)
                )
        return frozenset(lines)

    monkeypatch.setattr(tmc, "unselected_option_lines", _sweep_everything)
    result = _apply()
    assert isinstance(result, ConformanceFailure)
    assert result.code == PRESERVED_CONTENT_LOST
    assert "견적서" in result.detail


def test_stage_two_catches_markers_that_survived(monkeypatch) -> None:
    """2단계가 마커를 못 지웠으면 MARKER_CLEANUP_VIOLATION — 저작 표기가 산출물로 샌다."""
    monkeypatch.setattr(tmc, "marker_lines", lambda scan: frozenset())
    result = _apply()
    assert isinstance(result, ConformanceFailure)
    assert result.code == MARKER_CLEANUP_VIOLATION


def test_final_verifier_catches_leftover_tokens() -> None:
    """치환이 새어 남긴 토큰은 FIELD_TEXT_MISMATCH — 산출물이 「빈칸으로 새지」 않는다."""
    verdict = tmc.verify_txt_materialization_postconditions(
        source_bytes=BODY.encode("utf-8"),
        output_bytes="수신: {{수신}}\n".encode("utf-8"),
        plan=_plan(),
        structure=_structure(),
        vdr=_vdr(),
    )
    assert isinstance(verdict, ConformanceFailure)
    assert verdict.code == FIELD_TEXT_MISMATCH


def test_final_verifier_catches_markers_in_the_output() -> None:
    verdict = tmc.verify_txt_materialization_postconditions(
        source_bytes=BODY.encode("utf-8"),
        output_bytes="{{#항목 첨부 첨부}}\n내용\n{{/항목}}\n".encode("utf-8"),
        plan=_plan(),
        structure=_structure(),
        vdr=_vdr(),
    )
    assert isinstance(verdict, ConformanceFailure)
    assert verdict.code == MARKER_CLEANUP_VIOLATION


def test_final_verifier_catches_a_mutated_source() -> None:
    """제거 대상이 원본에 없으면 SOURCE_CANDIDATE_MUTATED — executor 가 source 를 만졌다."""
    verdict = tmc.verify_txt_materialization_postconditions(
        source_bytes="수신: 값\n".encode("utf-8"),
        output_bytes="수신: 값\n".encode("utf-8"),
        plan=_plan(),
        structure=_structure(),
        vdr=_vdr(),
    )
    assert isinstance(verdict, ConformanceFailure)
    assert verdict.code == SOURCE_CANDIDATE_MUTATED


# ── 매체·구조 검문 ────────────────────────────────────────────────────────────
def test_other_media_plan_is_refused_before_any_work() -> None:
    with pytest.raises(UnsupportedNativePrimitiveContract):
        tmc.verify_txt_materialization_postconditions(
            source_bytes=BODY.encode("utf-8"),
            output_bytes=b"",
            plan=_plan(native="hwpx-native-primitive/v1"),
            structure=_structure(),
            vdr=_vdr(),
        )


def test_precheck_binds_the_declared_structure_to_the_actual_text() -> None:
    ok = tmc.verify_txt_structure_bytes_consistency(
        candidate_bytes=BODY.encode("utf-8"), structure=_structure()
    )
    assert isinstance(ok, ConformancePass)

    # 다른 템플릿의 structure 로는 통과하지 못한다(id 가 어긋난다).
    other = _structure("수신: {{수신}}\n")
    mismatch = tmc.verify_txt_structure_bytes_consistency(
        candidate_bytes=BODY.encode("utf-8"), structure=other
    )
    assert isinstance(mismatch, ConformanceFailure)
    assert mismatch.code == STRUCTURE_BYTES_INCONSISTENT


def test_non_utf8_candidate_is_a_loud_structure_inconsistency() -> None:
    bad = tmc.verify_txt_structure_bytes_consistency(
        candidate_bytes="수신".encode("cp949"), structure=_structure()
    )
    assert isinstance(bad, ConformanceFailure)
    assert bad.code == STRUCTURE_BYTES_INCONSISTENT


def test_missing_vdr_value_for_an_apply_operation_is_loud() -> None:
    with pytest.raises(tmc.ConformanceExecutionError):
        _apply(values={"수신": "○○청"})


# ── 조달·형식 경계(전부 loud, 조용한 통과 0) ──────────────────────────────────
_BROKEN = "수신: {{수신}}\n{{#항목 첨부 첨부}}\n내용\n"  # 닫는 마커 없음


def test_precheck_refuses_a_candidate_whose_notation_is_broken() -> None:
    """진단 있는 스캔은 좌표를 믿을 수 없다 — 부분 구조로 진행하지 않는다."""
    verdict = tmc.verify_txt_structure_bytes_consistency(
        candidate_bytes=_BROKEN.encode("utf-8"), structure=_structure()
    )
    assert isinstance(verdict, ConformanceFailure)
    assert verdict.code == STRUCTURE_BYTES_INCONSISTENT


def test_precheck_refuses_when_the_structure_misses_a_field_in_the_bytes() -> None:
    """Field 집합은 **완전 일치**를 요구한다 — subset 이면 미치환 토큰이 산출로 샌다."""
    extra = BODY + "추가 {{추가필드}}\n"
    verdict = tmc.verify_txt_structure_bytes_consistency(
        candidate_bytes=extra.encode("utf-8"), structure=_structure()
    )
    assert isinstance(verdict, ConformanceFailure)
    assert "추가필드" in verdict.detail


def test_executor_refuses_a_candidate_whose_notation_is_broken() -> None:
    result = _apply(body=_BROKEN, structure=_structure(), values=VALUES)
    assert isinstance(result, ConformanceFailure)
    assert result.code == REPARSE_FAILED


def test_executor_refuses_an_unknown_operation_code() -> None:
    plan = _plan()
    plan.ordered_operations = ({"op": "REWRITE_EVERYTHING"},)
    with pytest.raises(UnsupportedNativePrimitiveContract):
        _apply(plan=plan)


def test_executor_refuses_an_operation_without_a_code() -> None:
    plan = _plan()
    plan.ordered_operations = ({"slot_id": "첨부"},)
    with pytest.raises(tmc.ConformanceExecutionError):
        _apply(plan=plan)


def test_non_utf8_source_and_output_are_distinct_failures() -> None:
    """조달 층을 섞지 않는다 — 원본이 안 읽히는 것과 산출이 안 읽히는 것은 다른 코드다."""
    bad = "수신".encode("cp949")
    mutated = tmc.verify_txt_materialization_postconditions(
        source_bytes=bad, output_bytes=b"", plan=_plan(), structure=_structure(),
        vdr=_vdr(),
    )
    assert isinstance(mutated, ConformanceFailure)
    assert mutated.code == SOURCE_CANDIDATE_MUTATED

    reparse = tmc.verify_txt_materialization_postconditions(
        source_bytes=BODY.encode("utf-8"), output_bytes=bad, plan=_plan(),
        structure=_structure(), vdr=_vdr(),
    )
    assert isinstance(reparse, ConformanceFailure)
    assert reparse.code == REPARSE_FAILED


def test_broken_notation_in_source_or_output_is_restated_per_layer() -> None:
    broken = _BROKEN.encode("utf-8")
    mutated = tmc.verify_txt_materialization_postconditions(
        source_bytes=broken, output_bytes=b"", plan=_plan(), structure=_structure(),
        vdr=_vdr(),
    )
    assert isinstance(mutated, ConformanceFailure)
    assert mutated.code == SOURCE_CANDIDATE_MUTATED


def test_occurrence_count_mismatch_is_its_own_code() -> None:
    """등장 수는 값 불일치와 다른 이름이다 — 무엇이 틀렸는지 실패가 말해야 한다."""
    executed = _apply()
    assert isinstance(executed, tmc.InMemoryTxtMaterialization)
    verdict = tmc.verify_txt_materialization_postconditions(
        source_bytes=BODY.encode("utf-8"),
        output_bytes=executed.output_bytes,
        plan=_plan(counts={"수신": 3, "담당자": 1}),
        structure=_structure(),
        vdr=_vdr(),
        stage_facts=executed.stage_facts,
    )
    assert isinstance(verdict, ConformanceFailure)
    assert verdict.code == OCCURRENCE_COUNT_MISMATCH


def test_value_that_never_reached_the_output_is_a_text_mismatch() -> None:
    executed = _apply()
    assert isinstance(executed, tmc.InMemoryTxtMaterialization)
    verdict = tmc.verify_txt_materialization_postconditions(
        source_bytes=BODY.encode("utf-8"),
        output_bytes=executed.output_bytes,
        plan=_plan(),
        structure=_structure(),
        vdr=_vdr({"수신": "다른 값", "담당자": "홍길동"}),
        stage_facts=executed.stage_facts,
    )
    assert isinstance(verdict, ConformanceFailure)
    assert verdict.code == FIELD_TEXT_MISMATCH


def test_stage_one_rescan_diagnostics_are_a_reparse_failure(monkeypatch) -> None:
    """제거가 표기를 깨뜨렸으면(예: 여는 마커만 지움) 1단계 재스캔이 시끄럽게 닫는다.

    구조 술어를 물을 수 없는 상태를 「초과 잔존」이나 「소실」로 부르지 않는다 — 좌표 자체가
    신뢰 대상이 아니므로 층을 가른다(P0).
    """
    monkeypatch.setattr(
        tmc, "unselected_option_lines", lambda scan, selected: frozenset({3})
    )
    result = _apply()
    assert isinstance(result, ConformanceFailure)
    assert result.code == REPARSE_FAILED
    assert "제거 뒤 재스캔" in result.detail


def test_final_verifier_reports_broken_notation_in_the_output() -> None:
    """산출에 깨진 표기가 남았으면 REPARSE_FAILED — 마커 cleanup 위반과 다른 층이다."""
    verdict = tmc.verify_txt_materialization_postconditions(
        source_bytes=BODY.encode("utf-8"),
        output_bytes="{{#항목 첨부 첨부}}\n내용\n".encode("utf-8"),  # 닫는 마커 없음
        plan=_plan(),
        structure=_structure(),
        vdr=_vdr(),
    )
    assert isinstance(verdict, ConformanceFailure)
    assert verdict.code == REPARSE_FAILED
    assert "output 재스캔" in verdict.detail
