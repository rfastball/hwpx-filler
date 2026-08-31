"""SG-02(#734) in-memory native materialization conformance harness.

theorem PASS 는 static admission 일 뿐 actual HWPX materialization 성공이 아님을, 실제 production
native primitive(remove_slot_option·FieldDocument·HwpxPackage codec)를 exact Candidate bytes 에
적용해 반증 가능하게 검증한다. 사례 조립기(REAL compiler·validator)는
:mod:`tests._materialization_case` 공유 fixture 다 — production port 층
(``test_materialization_runner``)과 같은 조립기를 쓴다. 순수 lxml+zipfile → deterministic
contract suite(무marker).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from lxml import etree

from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.package import HwpxPackage
from hwpxfiller.application.execution_capture import MATERIALIZATION_BASE_CONTRACT_ID
from hwpxfiller.application.execution_composition import (
    COMPOSITION_CONTRACT_ID,
    DEFAULT_RUNTIME_CONFORMANCE_REGISTRY,
    NATIVE_PRIMITIVE_CONTRACT_ID,
    NATIVE_PRIMITIVE_CONTRACT_V1,
    THEOREM_EVIDENCE_V1,
    CompositionPremiseContextError,
    CompositionPremisesPassed,
    NativePrimitiveContractManifest,
    RuntimeMaterializerConformanceNotAdmitted,
    UnsupportedNativePrimitiveContract as CompositionUnsupportedNativePrimitiveContract,
    verify_execution_composition_premises,
)
from hwpxfiller.domain.canonical_execution_encoding import CANONICAL_ENCODING_VERSION
from hwpxfiller.external.materialization_conformance import (
    FIELD_TEXT_MISMATCH,
    MARKER_CLEANUP_VIOLATION,
    OCCURRENCE_COUNT_MISMATCH,
    PRESERVED_CONTENT_LOST,
    PROTECTED_STRUCTURE_LOSS,
    REMOVAL_INCOMPLETE,
    REPARSE_FAILED,
    SOURCE_CANDIDATE_MUTATED,
    STRUCTURE_BYTES_INCONSISTENT,
    ConformanceExecutionError,
    ConformanceFailure,
    ConformancePass,
    apply_execution_plan_in_memory,
    verify_materialization_postconditions,
    verify_structure_bytes_consistency,
)

from tests._materialization_case import (
    HEADER,
    HP,
    POSITIVE,
    SECTION,
    CaseSpec,
    Opt,
    SlotS,
    _build_case,
    _build_structure,
    _escaping_case,
    _materialize,
    _one_of_two,
    _run,
    _slotless_case,
    _synth_case,
)


@pytest.mark.parametrize("name", sorted(POSITIVE))
def test_positive_corpus_actual_pass(name: str) -> None:
    case = _build_case(POSITIVE[name]())
    # P7 precheck: authored structure ↔ bytes id 일관.
    assert isinstance(
        verify_structure_bytes_consistency(candidate_bytes=case.bytes, structure=case.structure),
        ConformancePass,
    )
    output = _run(case)
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=output, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformancePass), result


def test_intentional_blank_writes_empty_not_skipped() -> None:
    # legacy generator 의 blank-skip 과 달리 INTENTIONAL_BLANK 는 write-empty 여야 한다.
    case = _build_case(_one_of_two())
    assert case.values["항목"] == ""
    output = _run(case)
    reopen = HwpxPackage.from_bytes(output)
    from hwpxfiller.external.materialization_conformance import _read_field_values

    values = dict(_read_field_values(reopen))
    assert values["항목"] == ""  # 필드는 보존, 값만 비었다
    assert values["성명"] == "홍길동"


def test_unselected_option_field_removed_from_bytes() -> None:
    case = _build_case(_one_of_two())
    output = _run(case)
    from hwpxfiller.external.materialization_conformance import _read_field_values

    fields = {fid for fid, _ in _read_field_values(HwpxPackage.from_bytes(output))}
    assert "금액" not in fields  # o2 제거 → 금액 소멸
    assert {"성명", "주소", "항목"} <= fields


def test_source_candidate_bytes_unchanged_after_execution() -> None:
    from hashlib import sha256

    case = _build_case(_one_of_two())
    before = sha256(case.bytes).digest()
    _run(case)
    assert sha256(case.bytes).digest() == before  # bytes 불변(P6 in-vivo)
    # source 를 fresh 하게 다시 열어도 제거 target 이 그대로 있다(executor 가 clone 에서만 작동).
    slots, _ = __import__(
        "hwpxfiller.external.template_inspection", fromlist=["inspect_slots"]
    ).inspect_slots(HwpxPackage.from_bytes(case.bytes))
    assert {"o1", "o2"} == {o.id for s in slots for o in s.options}


# ══ negative / differential corpus(각 distinct failure code) ══════════════════════════
def _corrupt_section(blob: bytes, transform) -> bytes:
    pkg = HwpxPackage.from_bytes(blob)
    pkg.entries[SECTION] = transform(pkg.entries[SECTION])
    return pkg.to_bytes()


def _drop_field_paragraph(xml: bytes, name: str) -> bytes:
    # 해당 ordinary Field(begin+end 한 문단) 를 담은 최상위 문단을 통째로 제거한다 — orphan marker
    # 없이 retained content 만 사라져 P2(보존) 계층을 겨눈다.
    root = etree.fromstring(xml)
    for para in list(root.findall(f"{{{HP}}}p")):
        if any(fb.get("name") == name for fb in para.iter(f"{{{HP}}}fieldBegin")):
            root.remove(para)
    return serialize_modified_section(root)


def test_theorem_pass_but_actual_removal_fail_stays_independent() -> None:
    # 유효 plan(theorem PASS)인데 output 이 unselected option 을 제거하지 못한 경우.
    case = _build_case(_one_of_two())
    # theorem evidence 는 여전히 PASS 다(static admission).
    comp = verify_execution_composition_premises(
        structure=case.structure, native_primitive_contract=NATIVE_PRIMITIVE_CONTRACT_V1,
        theorem_evidence=THEOREM_EVIDENCE_V1,
    )
    assert isinstance(comp, CompositionPremisesPassed)
    # 그런데 actual output(=source, 아무것도 제거 안 함)은 conformance FAIL.
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=case.bytes, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == REMOVAL_INCOMPLETE


def test_runtime_conformance_manifest_missing_is_fail_closed() -> None:
    # S6-empty registry 는 runtime conformance 를 admit 하지 않는다(ready 아님, fail-closed).
    with pytest.raises(RuntimeMaterializerConformanceNotAdmitted):
        DEFAULT_RUNTIME_CONFORMANCE_REGISTRY.require_admitted(
            runtime_capability_manifest_digest="sha256:x",
            materialization_contract_id="materialization/v1",
            materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
            native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
            composition_contract_id=COMPOSITION_CONTRACT_ID,
            plan_schema_version="hwpx-execution-plan/v2",
            canonical_encoding_version=CANONICAL_ENCODING_VERSION,
        )


def test_wrong_native_primitive_contract_rejected_at_compile_boundary() -> None:
    case = _build_case(_one_of_two())
    bad = NativePrimitiveContractManifest(
        native_primitive_contract_id="hwpx-native-primitive/v999",
        option_resolver_contract_id="x", option_removal_contract_id="x",
        field_resolver_contract_id="x", field_write_contract_id="x",
        envelope_postcondition_contract_id="x", intentional_blank_write_contract_id="x",
        primitive_semantics_version="1",
    )
    result = verify_execution_composition_premises(
        structure=case.structure, native_primitive_contract=bad, theorem_evidence=THEOREM_EVIDENCE_V1
    )
    assert isinstance(result, CompositionPremiseContextError)
    assert result.code == CompositionUnsupportedNativePrimitiveContract.code


def test_wrong_native_primitive_contract_rejected_by_verifier() -> None:
    from types import SimpleNamespace

    case = _build_case(_one_of_two())
    output = _run(case)
    bad_plan = SimpleNamespace(
        execution_basis=SimpleNamespace(
            contracts=SimpleNamespace(native_primitive_contract_id="hwpx-native-primitive/v999")
        ),
        ordered_operations=case.plan.ordered_operations,
        active_field_requirements=case.plan.active_field_requirements,
    )
    with pytest.raises(CompositionUnsupportedNativePrimitiveContract):
        verify_materialization_postconditions(
            source_bytes=case.bytes, output_bytes=output, plan=bad_plan, structure=case.structure, vdr=case.vdr
        )


def test_serialize_ok_reparse_fail_is_distinct() -> None:
    case = _build_case(_one_of_two())
    output = _run(case)
    broken = _corrupt_section(output, lambda x: x.replace(b"</hs:sec>", b"<hp:p></hs:sec>"))
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=broken, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == REPARSE_FAILED


def test_reparse_ok_but_field_text_mismatch_is_distinct() -> None:
    case = _build_case(_one_of_two())
    output = _run(case)
    tampered = _corrupt_section(output, lambda x: x.replace("홍길동".encode(), "위조".encode()))
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=tampered, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == FIELD_TEXT_MISMATCH


def test_occurrence_count_mismatch_is_distinct() -> None:
    case = _build_case(_one_of_two())  # 성명 occurrence 2
    output = _run(case)

    def drop_one_seongmyeong(xml: bytes) -> bytes:
        root = etree.fromstring(xml)
        # 마지막 성명 필드가 든 최상위 문단을 제거한다.
        target = None
        for para in root.findall(f"{{{HP}}}p"):
            if any(fb.get("name") == "성명" for fb in para.iter(f"{{{HP}}}fieldBegin")):
                target = para
        root.remove(target)
        return serialize_modified_section(root)

    corrupted = _corrupt_section(output, drop_one_seongmyeong)
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=corrupted, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == OCCURRENCE_COUNT_MISMATCH


def test_marker_cleanup_violation_is_distinct() -> None:
    case = _build_case(_one_of_two())
    output = _run(case)
    # orphan ordinary fieldEnd 주입(XML 은 well-formed 이나 field pairing 이 깨진다).
    orphan = _corrupt_section(
        output,
        lambda x: x.replace(
            b"</hs:sec>", b'<hp:p><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p></hs:sec>'
        ),
    )
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=orphan, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == MARKER_CLEANUP_VIOLATION


def test_marker_cleanup_violation_in_secondary_entry() -> None:
    # header0.xml 의 orphan field marker 는 inspect(section 전용)를 통과하지만 per-entry field
    # pairing 검사(P4)에서 걸린다 — resolver 진단 경로를 별도로 침.
    case = _build_case(_slotless_case())  # header 머리말 보유
    output = _run(case)
    pkg = HwpxPackage.from_bytes(output)
    pkg.entries[HEADER] = pkg.entries[HEADER].replace(
        b"</hs:sec>", b"<hp:p><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p></hs:sec>"
    )
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=pkg.to_bytes(), plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == MARKER_CLEANUP_VIOLATION


def test_preserved_content_lost_is_distinct() -> None:
    case = _build_case(_one_of_two())
    output = _run(case)
    # 유효 output 에서 selected option o1 까지 제거해 보존 위반을 만든다.
    from hwpxfiller.external.template_inspection import remove_slot_option

    pkg = HwpxPackage.from_bytes(output)
    remove_slot_option(pkg, "s1", "o1")
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=pkg.to_bytes(), plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == PRESERVED_CONTENT_LOST


def test_protected_bookmark_loss_is_distinct() -> None:
    case = _build_case(_one_of_two())  # GUARD field-less 보호 BOOKMARK 포함
    output = _run(case)
    # 유효 output 에서 제거 대상이 아닌 field-less 보호 region(GUARD)을 제거한다 — 이름 있는
    # non-target region 소실이 per-region topology 대조에서 걸린다(count 기준이 아님).
    from hwpxcore.bookmark_region import remove_bookmark_region, resolve_bookmark_regions

    pkg = HwpxPackage.from_bytes(output)
    region = next(r for r in resolve_bookmark_regions(pkg) if r.name == "GUARD")
    remove_bookmark_region(pkg, region)
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=pkg.to_bytes(), plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == PROTECTED_STRUCTURE_LOSS


def test_protected_region_topology_mutation_is_distinct() -> None:
    # region 이 output 에 남아 있어도(같은 pairing id) per-region shape(이름)가 바뀌면 구조 변형이다 —
    # count 기준으로는 소실 0 이라 보이지 않던 부패를 per-region topology 대조가 잡는다.
    case = _build_case(_one_of_two())
    output = _run(case)
    renamed = _corrupt_section(output, lambda x: x.replace(b'name="GUARD"', b'name="RENAMED"'))
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=renamed, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == PROTECTED_STRUCTURE_LOSS


def test_unnamed_protected_region_loss_is_distinct() -> None:
    # SG-02 fix #2 (a): 이름 없는(name=None) 보호 region 이 제거 대상 밖에서 사라지면, name-set 이
    # name is None 을 버리던 이전 구현은 눈멀었다. per-region topology 는 무명 region 소실도 잡는다.
    case = _build_case(_one_of_two())  # guard_bookmarks 에 무명 region 하나
    output = _run(case)
    from hwpxcore.bookmark_region import remove_bookmark_region, resolve_bookmark_regions

    pkg = HwpxPackage.from_bytes(output)
    region = next(r for r in resolve_bookmark_regions(pkg) if r.name is None)
    remove_bookmark_region(pkg, region)
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=pkg.to_bytes(), plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == PROTECTED_STRUCTURE_LOSS


def test_bookmark_nested_in_removed_option_is_not_false_reject() -> None:
    # SG-02 fix #2 (b): 제거되는 Option 안에 중첩된 BOOKMARK 는 Option 과 함께 정당하게 사라진다 —
    # 이전 count 기준 구현은 소실 수가 제거 Option 수를 초과해 거짓 PROTECTED_STRUCTURE_LOSS 를 냈다.
    spec = CaseSpec(
        slots=(
            SlotS(
                "s1",
                (),
                (Opt("o1", ("항목",)), Opt("o2", ("금액",), nested=("NESTED", None))),
                selected="o1",
            ),
        ),
        bindings={"항목": ("CONST", "선택값")},
    )
    case = _build_case(spec)
    output = _run(case)
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=output, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformancePass), result


def test_retained_shared_content_loss_is_preserved_content_lost() -> None:
    # SG-02 fix #1: option marker 는 그대로 두고 제거 대상이 아닌 SLOT_SHARED Field(주소) 내용을
    # 통째로 잃으면, option id 만 보던 이전 P2 는 조용히 PASS 했다. owner fact 기반 검사는 잡는다.
    case = _build_case(_one_of_two())
    output = _run(case)
    corrupted = _corrupt_section(output, lambda x: _drop_field_paragraph(x, "주소"))
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=corrupted, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == PRESERVED_CONTENT_LOST


def test_source_candidate_mutation_detected() -> None:
    case = _build_case(_one_of_two())
    output = _run(case)
    # output(=제거된 상태)을 source 로 넘기면 removal target 이 source 에 없다 → 변형 감지.
    result = verify_materialization_postconditions(
        source_bytes=output, output_bytes=output, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == SOURCE_CANDIDATE_MUTATED


def test_structure_bytes_inconsistent_precheck() -> None:
    spec = _one_of_two()
    case = _build_case(spec)
    # bytes 에 없는 Option 을 선언한 structure 는 precheck 에서 거절.
    mutant = _build_structure(
        replace(spec, slots=(SlotS("s1", ("주소",),
                (Opt("o1", ("항목",)), Opt("o2", ("금액",)), Opt("o3", ("추가",))), selected="o1"),))
    )
    result = verify_structure_bytes_consistency(candidate_bytes=case.bytes, structure=mutant)
    assert isinstance(result, ConformanceFailure)
    assert result.code == STRUCTURE_BYTES_INCONSISTENT


def test_structure_bytes_precheck_rejects_malformed_candidate() -> None:
    case = _build_case(_one_of_two())
    broken = _corrupt_section(case.bytes, lambda x: x.replace(b"</hs:sec>", b"<hp:p></hs:sec>"))
    result = verify_structure_bytes_consistency(candidate_bytes=broken, structure=case.structure)
    assert isinstance(result, ConformanceFailure)
    assert result.code == STRUCTURE_BYTES_INCONSISTENT


def test_structure_bytes_precheck_rejects_unreadable_candidate() -> None:
    case = _build_case(_one_of_two())
    result = verify_structure_bytes_consistency(candidate_bytes=b"not a zip", structure=case.structure)
    assert isinstance(result, ConformanceFailure)
    assert result.code == STRUCTURE_BYTES_INCONSISTENT


def test_structure_bytes_precheck_rejects_field_not_in_bytes() -> None:
    spec = _one_of_two()
    case = _build_case(spec)
    # structure 는 bytes 에 없는 root Field 를 선언 → subset 위반.
    mutant = _build_structure(replace(spec, root_fields=("성명", "성명", "유령")))
    result = verify_structure_bytes_consistency(candidate_bytes=case.bytes, structure=mutant)
    assert isinstance(result, ConformanceFailure)
    assert result.code == STRUCTURE_BYTES_INCONSISTENT


def test_source_unreadable_is_mutation_signal() -> None:
    case = _build_case(_one_of_two())
    output = _run(case)
    result = verify_materialization_postconditions(
        source_bytes=b"not a zip", output_bytes=output, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == SOURCE_CANDIDATE_MUTATED


def test_source_with_blocking_diagnostics_is_mutation_signal() -> None:
    case = _build_case(_one_of_two())
    output = _run(case)
    # section 은 well-formed 이나 orphan marker 로 inspect 가 blocking diagnostics 를 낸다.
    bad_source = _corrupt_section(
        case.bytes,
        lambda x: x.replace(
            b"</hs:sec>", b"<hp:p><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p></hs:sec>"
        ),
    )
    result = verify_materialization_postconditions(
        source_bytes=bad_source, output_bytes=output, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == SOURCE_CANDIDATE_MUTATED


def test_whole_slot_loss_is_preserved_content_lost() -> None:
    case = _build_case(_one_of_two())
    output = _run(case)
    from hwpxfiller.external.template_inspection import remove_slot

    pkg = HwpxPackage.from_bytes(output)
    remove_slot(pkg, "s1")  # 통째 Slot 소실
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=pkg.to_bytes(), plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == PRESERVED_CONTENT_LOST


def test_unnormalizable_field_name_is_ignored() -> None:
    # normalize_field_id 가 None 을 내는 occurrence(공백 이름)는 값 검사에서 건너뛴다(포트가 죽지 않는다).
    case = _build_case(_one_of_two())
    output = _run(case)
    ghost = _corrupt_section(
        output,
        lambda x: x.replace(
            b"</hs:sec>",
            b'<hp:p><hp:run><hp:ctrl><hp:fieldBegin type="CLICK_HERE" name="   "/></hp:ctrl>'
            b"<hp:t>x</hp:t><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p></hs:sec>",
        ),
    )
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=ghost, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformancePass)


# ── executor fail-closed 분기 ─────────────────────────────────────────────────────────
def test_executor_rejects_unknown_operation() -> None:
    case = _build_case(_one_of_two())
    with pytest.raises(CompositionUnsupportedNativePrimitiveContract):
        apply_execution_plan_in_memory(
            candidate_bytes=case.bytes, ordered_operations=[{"op": "NOPE"}], document_values={}
        )


def test_executor_rejects_operation_without_code() -> None:
    case = _build_case(_one_of_two())
    with pytest.raises(ConformanceExecutionError):
        apply_execution_plan_in_memory(
            candidate_bytes=case.bytes, ordered_operations=[{"slot_id": "s1"}], document_values={}
        )


def test_executor_rejects_apply_without_field_id() -> None:
    case = _build_case(_one_of_two())
    with pytest.raises(ConformanceExecutionError):
        apply_execution_plan_in_memory(
            candidate_bytes=case.bytes,
            ordered_operations=[{"op": "APPLY_FIELD_BINDING", "field_id": ""}],
            document_values={},
        )


def test_executor_rejects_missing_document_value() -> None:
    case = _build_case(_one_of_two())
    with pytest.raises(ConformanceExecutionError):
        apply_execution_plan_in_memory(
            candidate_bytes=case.bytes,
            ordered_operations=[{"op": "APPLY_FIELD_BINDING", "field_id": "성명"}],
            document_values={},
        )


def test_executor_rejects_field_absent_in_bytes() -> None:
    case = _build_case(_one_of_two())
    with pytest.raises(ConformanceExecutionError):
        apply_execution_plan_in_memory(
            candidate_bytes=case.bytes,
            ordered_operations=[{"op": "APPLY_FIELD_BINDING", "field_id": "없는필드"}],
            document_values={"없는필드": "x"},
        )


def test_executor_rejects_malformed_remove_operand() -> None:
    case = _build_case(_one_of_two())
    with pytest.raises(ConformanceExecutionError):
        apply_execution_plan_in_memory(
            candidate_bytes=case.bytes,
            ordered_operations=[{"op": "REMOVE_OPTION", "slot_id": "s1", "option_id": None}],
            document_values={},
        )


# ── S6-06(#809): escaping 소유의 양성·음성 증거 ──────────────────────────────────────
def test_escaping_logical_text_roundtrip_and_bytes_escaped() -> None:
    # 양성: logical text 는 exact 로 보존되고(P3), bytes 층에서는 native serialization 이
    # escape 했다. pre-escaped 처럼 보이는 리터럴("&amp;")은 이중 표기로 정직하게 남는다 —
    # 즉 escaping 은 정확히 한 번, VDR 값 그대로 위에서 일어난다.
    case = _build_case(_escaping_case())
    output = _run(case)
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=output, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformancePass), result
    from hwpxfiller.external.materialization_conformance import _read_field_values

    values = dict(_read_field_values(HwpxPackage.from_bytes(output)))
    assert values["특수"] == 'A&B<C>D"E\'F'
    assert values["리터럴"] == "&amp;"
    assert values["여러줄"] == "한글\n두줄"
    assert values["꼬리"] == "]]>"
    section = HwpxPackage.from_bytes(output).entries[SECTION]
    assert b"A&amp;B&lt;C&gt;D" in section  # 특수문자가 실제로 escape 됐다
    assert "&amp;amp;".encode() in section  # "&amp;" 리터럴의 & 도 escape 됐다(double-escape 아님)
    assert b"]]&gt;" in section  # CDATA 꼬리의 > 도 escape 됐다


def test_double_escape_regression_is_field_text_mismatch() -> None:
    # 음성: escaping 층의 부패(리터럴 "&amp;" 가 "&" 로 강등)는 reopened logical text 대조(P3)가
    # FIELD_TEXT_MISMATCH 로 잡는다 — escaping 정확성이 postcondition 재검사 범위임을 증명한다.
    case = _build_case(_escaping_case())
    output = _run(case)
    tampered = _corrupt_section(output, lambda x: x.replace(b"&amp;amp;", b"&amp;"))
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=tampered, plan=case.plan, structure=case.structure, vdr=case.vdr
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == FIELD_TEXT_MISMATCH


# ── fix #3: 채움 완화(FillNote)는 삼키지 않고 표면화한다 ────────────────────────────────
def test_fill_note_is_surfaced_not_swallowed() -> None:
    from hwpxfiller.domain.fields import FillNote

    case = _build_case(_synth_case())
    materialized = _materialize(case)
    # executor 가 완화 사실을 삼키지 않고 돌려준다.
    assert FillNote("빈칸", "slot_synthesized") in materialized.notes
    # 그리고 그 사실이 ConformanceResult(PASS)에 실려 상위가 record/warn 할 수 있다.
    result = verify_materialization_postconditions(
        source_bytes=case.bytes,
        output_bytes=materialized.output_bytes,
        plan=case.plan,
        structure=case.structure,
        vdr=case.vdr,
        execution_notes=materialized.notes,
    )
    assert isinstance(result, ConformancePass), result
    assert FillNote("빈칸", "slot_synthesized") in result.notes
