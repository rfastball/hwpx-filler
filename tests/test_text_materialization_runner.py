"""TXT materialization runner(S10-04 · #861) — 조달 gate 와 산출 자격.

HWPX 러너와 **같은 규율**을 TXT 에서 확인한다: 조달은 전부 digest fail-closed 이고,
postcondition PASS 전건일 때만 :class:`MaterializedDocumentBytes` 가 선다. 조달 실패(loud 예외)와
postcondition 실패(:class:`ConformanceFailure`)는 **다른 층**이라 섞이지 않는다.

Plan/VDR/store 는 얇은 대역이다 — 실 봉인 왕복은 ``tests/test_txt_materialization.py`` 가 진다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hwpxfiller.application.candidate_revision import blob_digest
from hwpxfiller.application.execution_composition import (
    TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
    UnsupportedNativePrimitiveContract,
)
from hwpxfiller.application.execution_structure import template_structure_digest
from hwpxfiller.domain.field_binding import (
    DOCUMENT_CONTENT_VALUE_POLICY_TXT_V1,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
)
from hwpxfiller.external.materialization_conformance_vocabulary import (
    ConformanceFailure,
    MaterializedDocumentBytes,
)
from hwpxfiller.external.materialization_runner import (
    EscapingResponsibilityError,
    MaterializationProcurementError,
)
from hwpxfiller.external.text_materialization_runner import TxtMaterializationRunner
from hwpxfiller.external.text_template_inspection import inspect_txt_qualification

BODY = "\n".join(
    [
        "수신: {{수신}}",
        "{{#항목 첨부 첨부}}",
        "{{#선택 가 가}}",
        "가 본문",
        "{{/선택}}",
        "{{#선택 나 나}}",
        "나 본문",
        "{{/선택}}",
        "{{/항목}}",
        "",
    ]
)
CANDIDATE = BODY.encode("utf-8")


def _structure(body: str = BODY):
    execution = inspect_txt_qualification(body.encode("utf-8")).execution_structure
    assert execution is not None
    return execution


def _plan(
    *,
    native: str = TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
    policy_id: str = DOCUMENT_CONTENT_VALUE_POLICY_TXT_V1.policy_id,
    blob: str | None = None,
    structure_digest: str | None = None,
    structure=None,
):
    structure = structure if structure is not None else _structure()
    return SimpleNamespace(
        ordered_operations=(
            {"op": "REMOVE_OPTION", "slot_id": "첨부", "option_id": "나"},
            {"op": "APPLY_FIELD_BINDING", "field_id": "수신"},
        ),
        active_field_requirements=(
            {
                "field_id": "수신",
                "expected_active_occurrence_count": 1,
                "value_expression": {
                    "kind": "FROM_SOURCE",
                    "source_key": "부서",
                    "document_content_value_policy_id": policy_id,
                },
            },
        ),
        execution_basis=SimpleNamespace(
            contracts=SimpleNamespace(native_primitive_contract_id=native),
            template=SimpleNamespace(
                exact_content_digest=blob or blob_digest(CANDIDATE)
            ),
            selection=SimpleNamespace(
                template_structure_digest=(
                    structure_digest or template_structure_digest(structure)
                )
            ),
        ),
    )


def _vdr(values=(("수신", "회계과"),)):
    return SimpleNamespace(document_values_in_order=lambda: values)


def _runner(plan=None, *, candidate: bytes = CANDIDATE, structure=None):
    plan = plan or _plan()
    structure = structure if structure is not None else _structure()
    return TxtMaterializationRunner(
        input_port=SimpleNamespace(resolve=lambda _input: (plan, _vdr())),  # type: ignore[arg-type]
        candidate_blob_resolver=lambda _digest: candidate,
        structure_resolver=lambda _plan: structure,
    )


_INPUT = SimpleNamespace(
    sealed_execution_plan_ref="plan-ref", validated_record_ref="vdr-ref"
)


def test_pass_yields_document_bytes_with_its_evidence() -> None:
    outcome = _runner().materialize(_INPUT)  # type: ignore[arg-type]
    assert isinstance(outcome, MaterializedDocumentBytes)
    assert outcome.output_bytes.decode("utf-8") == "수신: 회계과\n가 본문\n"
    assert outcome.plan_semantic_digest == "plan-ref"
    assert outcome.validated_record_ref == "vdr-ref"
    assert outcome.output_digest == blob_digest(outcome.output_bytes)
    # 평문 치환에는 완화(inline strip·slot 합성)가 없다 — 낼 note 가 구조적으로 0 이다.
    assert outcome.execution_notes == ()


def test_other_media_plan_is_refused_before_any_procurement() -> None:
    """HWPX Plan 을 평문 치환으로 실행하면 zip 도 문서도 아닌 무엇이 나온다 — 먼저 닫는다."""
    with pytest.raises(UnsupportedNativePrimitiveContract):
        _runner(_plan(native="hwpx-native-primitive/v1")).materialize(_INPUT)  # type: ignore[arg-type]


def test_escaping_responsibility_of_another_materializer_is_refused() -> None:
    """XML escaping 책임을 선언한 값이 평문에 literal 로 꽂히면 escape 가 0번 또는 2번 된다."""
    with pytest.raises(EscapingResponsibilityError):
        _runner(_plan(policy_id=DOCUMENT_CONTENT_VALUE_POLICY_V1.policy_id)).materialize(
            _INPUT  # type: ignore[arg-type]
        )


def test_intentional_blank_skips_the_escaping_gate() -> None:
    """빈칸 정책에는 값 정책이 없다(``exact_blank_policy`` 소관) — gate 를 건너뛴다."""
    plan = _plan()
    plan.active_field_requirements = (
        {
            "field_id": "수신",
            "expected_active_occurrence_count": 1,
            "value_expression": {"kind": "INTENTIONAL_BLANK"},
        },
    )
    outcome = _runner(plan).materialize(_INPUT)  # type: ignore[arg-type]
    assert isinstance(outcome, MaterializedDocumentBytes)


def test_missing_value_expression_is_loud() -> None:
    plan = _plan()
    plan.active_field_requirements = ({"field_id": "수신"},)
    with pytest.raises(EscapingResponsibilityError):
        _runner(plan).materialize(_INPUT)  # type: ignore[arg-type]


def test_candidate_digest_mismatch_is_a_procurement_error() -> None:
    """resolver 가 무엇을 주든 Plan 의 digest 와 대조 없이는 쓰지 않는다."""
    with pytest.raises(MaterializationProcurementError):
        _runner(_plan(blob="sha256:다른것")).materialize(_INPUT)  # type: ignore[arg-type]


def test_structure_digest_mismatch_is_a_procurement_error() -> None:
    with pytest.raises(MaterializationProcurementError):
        _runner(_plan(structure_digest="sha256:다른것")).materialize(_INPUT)  # type: ignore[arg-type]


def test_structure_that_lies_about_the_bytes_is_caught_by_the_precheck() -> None:
    """digest 는 각자 자신만 증명한다 — structure↔bytes 대응을 잇는 것은 precheck 뿐이다."""
    other = _structure("수신: {{수신}}\n")
    runner = _runner(
        _plan(structure=other, structure_digest=template_structure_digest(other)),
        structure=other,
    )
    outcome = runner.materialize(_INPUT)  # type: ignore[arg-type]
    assert isinstance(outcome, ConformanceFailure)
    assert outcome.code == "STRUCTURE_BYTES_INCONSISTENT"


def test_execution_failure_is_returned_as_a_conformance_failure(monkeypatch) -> None:
    """postcondition 실패는 조달 실패와 **다른 층**이다 — 예외가 아니라 코드로 닫힌다."""
    from hwpxfiller.external import text_materialization_conformance as tmc

    monkeypatch.setattr(tmc, "marker_lines", lambda scan: frozenset())
    outcome = _runner().materialize(_INPUT)  # type: ignore[arg-type]
    assert isinstance(outcome, ConformanceFailure)
    assert outcome.code == "MARKER_CLEANUP_VIOLATION"


def test_final_verifier_failure_is_returned_as_a_conformance_failure(monkeypatch) -> None:
    """executor 를 최종으로 신뢰하지 않는다 — output 재검사가 빨강이면 bytes 를 내지 않는다."""
    from hwpxfiller.external import text_materialization_runner as runner_module

    monkeypatch.setattr(
        runner_module,
        "verify_txt_materialization_postconditions",
        lambda **_kw: ConformanceFailure("REPARSE_FAILED", "주입"),
    )
    outcome = _runner().materialize(_INPUT)  # type: ignore[arg-type]
    assert isinstance(outcome, ConformanceFailure)
    assert outcome.code == "REPARSE_FAILED"


def test_store_backed_assembly_wires_the_shared_authority_root(tmp_path) -> None:
    """조립 편의 함수는 HWPX 와 같은 subdir 규약을 쓴다(별도 스토어 조립 없음)."""
    from hwpxfiller.application.record_validation import ImmutableVdrStore
    from hwpxfiller.external.text_materialization_runner import txt_materialization_runner

    runner = txt_materialization_runner(
        tmp_path, plan_resolver=lambda _ref: _plan(), vdr_store=ImmutableVdrStore()
    )
    assert isinstance(runner, TxtMaterializationRunner)
