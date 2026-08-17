"""SG-02(#734) in-memory native materialization conformance harness.

theorem PASS 는 static admission 일 뿐 actual HWPX materialization 성공이 아님을, 실제 production
native primitive(remove_slot_option·FieldDocument·HwpxPackage codec)를 exact Candidate bytes 에
적용해 반증 가능하게 검증한다. 모든 fixture 는 REAL compiler(``qualify_and_compile_execution`` →
``compile_candidate``)와 REAL validator(``validate_data_record_against_plan``)로 세운다 —
ordered_operations 를 손으로 위조하지 않는다. 순수 lxml+zipfile → deterministic contract suite(무marker).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import json

import pytest
from lxml import etree

from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.application.execution_capture import (
    APPLIED_TEMPLATE_CANDIDATE,
    MATERIALIZATION_BASE_CONTRACT_ID,
    CapturedFieldBinding,
    CapturedSelection,
    CapturedTemplateExecutionInput,
    ExactTemplateQualificationContext,
    QualificationProfileSemanticPayload,
    ResolvedSealPolicy,
    judge_captured_execution,
)
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
    theorem_evidence_digest,
    verify_execution_composition_premises,
)
from hwpxfiller.application.execution_structure import (
    ENVELOPE_CAPABILITY_KEYS,
    EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
    OWNER_OPTION,
    OWNER_ROOT,
    OWNER_SLOT_SHARED,
    RESOLVER_STABILITY_KEYS,
    ContentEntry,
    FieldOccurrence,
    OptionRegionObservation,
    SlotRegionObservation,
    build_execution_structure,
    template_structure_digest,
)
from hwpxfiller.application.record_validation import (
    ValidatedDataRecord,
    validate_data_record_against_plan,
)
from hwpxfiller.application.seal_execution_plan import PlanCandidate, compile_candidate
from hwpxfiller.application.slot_configuration_context import ExactAppliedTemplateInput
from hwpxfiller.application.slot_selection_input import (
    SlotConfigurationSnapshot,
    SlotlessSelectionContext,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.domain.canonical_execution_encoding import CANONICAL_ENCODING_VERSION
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    EXACT_TEXT,
    INTENTIONAL_BLANK,
    SOURCE,
    ExactText,
    FieldBindingRule,
)
from hwpxfiller.domain.raw_data_record import (
    RawRecordCaptureProvenance,
    SourceText,
    build_raw_record_snapshot,
)
from hwpxfiller.domain.slot_selection import (
    SlotSelection,
    SlotSelectionSet,
    digest_selection_set,
)
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

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
SECTION = "Contents/section0.xml"
HEADER = "Contents/header0.xml"
WS, WORK, APP, AT = "ws-1", "work-1", "app-1", "2026-08-17T00:00:00Z"
CONTRACT = "slot-selection/v1"
RC = "hwpx-field-resolver/v1"
REMOVE = "remove-option/v1"
VTC = "hwpx-field-value/v1"
PROFILE = "hwpx-template-qualification-v2"
_PROV = RawRecordCaptureProvenance(
    source_adapter_contract_id="excel-adapter/v1", captured_at=AT
)


# ══ 선언적 case spec ══════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Opt:
    id: str
    fields: tuple[str, ...]  # ordinary Field 이름
    nested: tuple[str | None, ...] = ()  # Option 안에 중첩된 field-less BOOKMARK(None=무명)


@dataclass(frozen=True)
class SlotS:
    id: str
    shared: tuple[str, ...]
    opts: tuple[Opt, ...]
    selected: str
    touching: bool = False


@dataclass(frozen=True)
class CaseSpec:
    root_fields: tuple[str, ...] = ()  # 순서·중복 허용(occurrence count)
    empty_root_fields: tuple[str, ...] = ()  # 값 hp:t 없는 빈 root Field(slot synthesize 유발)
    slots: tuple[SlotS, ...] = ()
    bindings: dict[str, tuple] = field(default_factory=dict)  # fid -> ("SOURCE",key)/("CONST",txt)/("BLANK",)
    source_values: dict[str, str] = field(default_factory=dict)
    extra_bookmarks: tuple[str, ...] = ()  # 보호 대상 plain BOOKMARK(안에 {name}_f Field 보유)
    guard_bookmarks: tuple[str | None, ...] = ()  # field-less 보호 BOOKMARK(None=무명)
    header_fields: tuple[str, ...] = ()  # header0.xml 의 root Field


@dataclass(frozen=True)
class Case:
    bytes: bytes
    structure: object
    plan: object
    vdr: ValidatedDataRecord
    values: dict[str, str]


# ── byte 문법 ─────────────────────────────────────────────────────────────────────────
def _p(content: str) -> str:
    return f"<hp:p><hp:run>{content}</hp:run></hp:p>"


def _bm_begin(pid: str, name: str) -> str:
    return f'<hp:ctrl><hp:fieldBegin id="{pid}" type="BOOKMARK" name="{name}"/></hp:ctrl>'


def _bm_end(pid: str) -> str:
    return f'<hp:ctrl><hp:fieldEnd beginIDRef="{pid}"/></hp:ctrl>'


def _click(name: str, value: str = "값") -> str:
    return (
        f'<hp:ctrl><hp:fieldBegin type="CLICK_HERE" name="{name}"/></hp:ctrl>'
        f"<hp:t>{value}</hp:t>"
        "<hp:ctrl><hp:fieldEnd/></hp:ctrl>"
    )


def _click_empty(name: str) -> str:
    # 값 hp:t 가 전혀 없는 빈 누름틀 — set_field 가 slot 합성(slot_synthesized)으로 채운다.
    return (
        f'<hp:ctrl><hp:fieldBegin type="CLICK_HERE" name="{name}"/></hp:ctrl>'
        "<hp:ctrl><hp:fieldEnd/></hp:ctrl>"
    )


def _bm_begin_unnamed(pid: str) -> str:
    return f'<hp:ctrl><hp:fieldBegin id="{pid}" type="BOOKMARK"/></hp:ctrl>'


def _guard_markup(pid_iter, name: str | None) -> str:
    # field-less BOOKMARK region(begin+end, 내용 없음). name=None 이면 무명.
    i = str(next(pid_iter))
    begin = _bm_begin_unnamed(i) if name is None else _bm_begin(i, name)
    return begin + _bm_end(i)


def _meta(kind: str, ident: str) -> str:
    return json.dumps(
        {"hwpxFiller": {"kind": kind, "id": ident}, "name": "#hf"}, ensure_ascii=False
    )


def _sec(body: str) -> bytes:
    return f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{body}</hs:sec>'.encode()


def _write_metatags(root: etree._Element, tags: dict[str, str]) -> None:
    begins = [n for n in root.iter(f"{{{HP}}}fieldBegin") if n.get("type") == "BOOKMARK"]
    for name, payload in tags.items():
        node = next(n for n in begins if n.get("name") == name)
        etree.SubElement(node, f"{{{HP}}}metaTag").text = payload


def _build_bytes(spec: CaseSpec) -> bytes:
    paras: list[str] = []
    tags: dict[str, str] = {}
    pid = iter(range(1, 1000))
    bm_name = iter(range(1, 1000))

    for fname in spec.root_fields:
        paras.append(_p(_click(fname)))
    for fname in spec.empty_root_fields:
        paras.append(_p(_click_empty(fname)))
    for name in spec.extra_bookmarks:
        i = str(next(pid))
        paras.append(_p(_bm_begin(i, name) + _click(f"{name}_f") + _bm_end(i)))
    for gb in spec.guard_bookmarks:
        paras.append(_p(_guard_markup(pid, gb)))
    for slot in spec.slots:
        sid = str(next(pid))
        sname = f"SLOT_{next(bm_name)}"
        paras.append(_p(_bm_begin(sid, sname)))
        tags[sname] = _meta("slot", slot.id)
        for shared in slot.shared:
            paras.append(_p(_click(shared)))
        for opt in slot.opts:
            oid = str(next(pid))
            oname = f"OPT_{next(bm_name)}"
            nested = "".join(_guard_markup(pid, n) for n in opt.nested)
            inner = "".join(_click(f) for f in opt.fields)
            paras.append(_p(_bm_begin(oid, oname) + nested + inner + _bm_end(oid)))
            tags[oname] = _meta("slot_option", opt.id)
        paras.append(_p(_bm_end(sid)))

    root = etree.fromstring(_sec("".join(paras)))
    _write_metatags(root, tags)
    entries = {MIMETYPE_NAME: MIMETYPE_VALUE, SECTION: serialize_modified_section(root)}
    if spec.header_fields:
        entries[HEADER] = _sec("".join(_p(_click(f)) for f in spec.header_fields))
    return HwpxPackage(entries=entries, stored={MIMETYPE_NAME}).to_bytes()


# ── structure(bytes 와 id 일치, span 은 abstract) ─────────────────────────────────────
def _entry(eid: str) -> ContentEntry:
    return ContentEntry(eid, "section-body/v1", {k: True for k in ENVELOPE_CAPABILITY_KEYS})


def _build_structure(spec: CaseSpec) -> object:
    occ: list[FieldOccurrence] = []
    slot_obs: list[SlotRegionObservation] = []
    opt_obs: list[OptionRegionObservation] = []
    counts: dict[str, int] = {}
    order = [0]

    def nxt() -> int:
        order[0] += 4
        return order[0]

    def add(fid: str, kind: str, at: int, slot=None, option=None, entry="c0") -> None:
        ordinal = counts.get(fid, 0)
        counts[fid] = ordinal + 1
        occ.append(FieldOccurrence(fid, ordinal, kind, slot, option, entry, at, VTC, RC))

    root_names: list[str] = []
    for fname in spec.root_fields:
        add(fname, OWNER_ROOT, nxt())
        root_names.append(fname)
    for fname in spec.empty_root_fields:
        add(fname, OWNER_ROOT, nxt())
        root_names.append(fname)
    # extra_bookmarks 안의 {name}_f 는 bytes 에 실재하는 root ordinary Field 다 — structure 도
    # 정직하게 선언해야 P7 완전-일치 precheck 를 통과한다(subset 구멍 봉인).
    for name in spec.extra_bookmarks:
        add(f"{name}_f", OWNER_ROOT, nxt())
        root_names.append(f"{name}_f")
    for fname in spec.header_fields:
        add(fname, OWNER_ROOT, nxt(), entry="c1")

    slots: list[TemplateSlot] = []
    for slot in spec.slots:
        s_begin = nxt()
        for shared in slot.shared:
            add(shared, OWNER_SLOT_SHARED, nxt(), slot=slot.id)
        template_opts: list[TemplateOption] = []
        prev_end: int | None = None
        for opt in slot.opts:
            o_begin = prev_end if (slot.touching and prev_end is not None) else nxt()
            for f in opt.fields:
                add(f, OWNER_OPTION, nxt(), slot=slot.id, option=opt.id)
            o_end = nxt()
            opt_obs.append(OptionRegionObservation(slot.id, opt.id, "c0", o_begin, o_end, REMOVE))
            template_opts.append(TemplateOption(opt.id, opt.fields))
            prev_end = o_end
        s_end = nxt()
        slot_obs.append(SlotRegionObservation(slot.id, "c0", s_begin, s_end))
        slots.append(TemplateSlot(id=slot.id, shared_fields=slot.shared, options=tuple(template_opts)))

    product = TemplateStructure(root_fields=tuple(dict.fromkeys(root_names + list(spec.header_fields))), slots=tuple(slots))
    entries = [_entry("c0")] + ([_entry("c1")] if spec.header_fields else [])
    return build_execution_structure(
        product_structure=product,
        occurrences=tuple(occ),
        slot_regions=tuple(slot_obs),
        option_regions=tuple(opt_obs),
        content_entries=tuple(entries),
        resolver_stability_facts={k: True for k in RESOLVER_STABILITY_KEYS},
        admitted_relation_profile="unadmitted",
    )


# ── capture scaffolding(REAL compiler·validator) ──────────────────────────────────────
def _policy(**over) -> ResolvedSealPolicy:
    kw = dict(
        policy_resolution_version="pol/1",
        execution_base_kind=APPLIED_TEMPLATE_CANDIDATE,
        execution_semantic_contract_id="execution-semantics/v1",
        binding_value_contract_id="binding-value/v1",
        raw_record_contract_id="raw-record/v1",
        document_value_resolution_contract_id="document-content-value/v1",
        record_validation_contract_id="record-validation/v1",
        record_review_contract_id="record-review/v1",
        composition_contract_id=COMPOSITION_CONTRACT_ID,
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        composition_theorem_evidence_manifest_digest=theorem_evidence_digest(THEOREM_EVIDENCE_V1),
        materialization_contract_id="materialization/v1",
        plan_schema_version="hwpx-execution-plan/v1",
        canonical_encoding_version=CANONICAL_ENCODING_VERSION,
    )
    kw.update(over)
    return ResolvedSealPolicy(**kw)


def _rule(fid: str, spec_binding: tuple) -> FieldBindingRule:
    kind = spec_binding[0]
    if kind == "SOURCE":
        return FieldBindingRule(
            field_id=fid, binding_kind=SOURCE, document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
            source_key=spec_binding[1], value_type=EXACT_TEXT, format_code="",
        )
    if kind == "CONST":
        return FieldBindingRule(
            field_id=fid, binding_kind=CONSTANT, document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
            canonical_constant_value=ExactText(spec_binding[1]),
        )
    return FieldBindingRule(
        field_id=fid, binding_kind=INTENTIONAL_BLANK, document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1
    )


def _selection(spec: CaseSpec, sdig: str):
    if not spec.slots:
        return SlotlessSelectionContext(
            work_id=WORK, template_application_id=APP, selection_semantic_contract_id=CONTRACT,
            structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
            template_structure_digest=sdig, source_configuration_version=None,
            declared_selection_digest=None, captured_at=AT,
        )
    eff = SlotSelectionSet(tuple(SlotSelection(s.id, (s.selected,)) for s in spec.slots))
    return SlotConfigurationSnapshot(
        work_id=WORK, template_application_id=APP, source_configuration_version=3,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        effective_selections=eff, effective_selection_digest=digest_selection_set(CONTRACT, eff),
        declared_selection_digest=digest_selection_set(CONTRACT, eff),
        template_structure_digest=sdig, captured_at=AT,
    )


def _build_case(spec: CaseSpec) -> Case:
    blob = _build_bytes(spec)
    struct = _build_structure(spec)
    sdig = template_structure_digest(struct)
    payload = QualificationProfileSemanticPayload(
        qualification_profile_id=PROFILE, media="hwpx", adapter_contract_version="a/1",
        product_rule_version="p/1", operation_alphabet_version="o/1",
        projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA, manifest_payload={"k": "v"},
    )
    applied = ExactAppliedTemplateInput(
        work_id=WORK, template_application_id=APP, revision_id="rev-1", media="hwpx",
        template_lineage_id="lin-1", exact_content_digest="sha256:cccc", canonical_blob_reference="blob://x",
    )
    qual = ExactTemplateQualificationContext(
        pass_evidence_id="ev-1", qualification_profile_id=PROFILE,
        qualification_profile_semantic_payload=payload,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        template_structure_digest=sdig, execution_structure=struct,
        composition_profile_state="SEALED", revision_id="rev-1",
    )
    template = CapturedTemplateExecutionInput(WS, WORK, applied, qual, AT)
    rules = tuple(_rule(fid, b) for fid, b in spec.bindings.items())
    schema_keys = tuple(b[1] for b in spec.bindings.values() if b[0] == "SOURCE")

    from hwpxfiller.application.field_binding_input import build_field_binding_input

    binding = build_field_binding_input(
        workspace_instance_id=WS, work_authority_id=WORK, base_template_application_id=APP,
        binding_rules=rules, source_schema_keys=schema_keys,
        raw_record_contract_id="raw-record/v1", captured_at=AT,
    )
    selection = _selection(spec, sdig)
    captured = judge_captured_execution(
        workspace_instance_id=WS, work_authority_id=WORK, expected_template_application_id=APP,
        expected_profile_id=PROFILE, resolved_seal_policy=_policy(), template=template,
        selection_observation=CapturedSelection(selection),
        field_binding_observation=CapturedFieldBinding(binding), captured_at=AT,
    )
    candidate = compile_candidate(captured)
    assert isinstance(candidate, PlanCandidate), candidate
    plan = candidate.plan_payload
    source_pairs = [(k, SourceText(v)) for k, v in spec.source_values.items()]
    snapshot = build_raw_record_snapshot(
        source_schema_keys=list(spec.source_values), source_values=source_pairs,
        record_identity="rec-1", capture_provenance=_PROV,
    )
    vdr = validate_data_record_against_plan(plan=plan, snapshot=snapshot, validated_at=AT)
    assert isinstance(vdr, ValidatedDataRecord), vdr
    return Case(blob, struct, plan, vdr, dict(vdr.document_values_in_order()))


def _materialize(case: Case):
    return apply_execution_plan_in_memory(
        candidate_bytes=case.bytes, ordered_operations=case.plan.ordered_operations,
        document_values=case.values,
    )


def _run(case: Case) -> bytes:
    return _materialize(case).output_bytes


# ══ positive corpus(7 cases) ═════════════════════════════════════════════════════════
def _slotless_case() -> CaseSpec:
    # slotless ordinary Field fill + header entry(다중 content entry 로 write False 분기도 침).
    return CaseSpec(
        root_fields=("성명",),
        bindings={"성명": ("SOURCE", "이름"), "머리말": ("CONST", "문서")},
        source_values={"이름": "홍길동"},
        header_fields=("머리말",),
    )


def _one_of_two() -> CaseSpec:
    # PLAIN 은 안에 PLAIN_f Field 를 갖는 보호 BOOKMARK — structure 가 PLAIN_f 를 정직하게 선언하고
    # 실제 write op(CONST)+VDR value 로 채운다(P7 subset 구멍 봉인). GUARD/무명은 field-less 보호
    # region 으로 P5 topology 검사를 위해 존재한다.
    return CaseSpec(
        root_fields=("성명", "성명"),
        slots=(SlotS("s1", ("주소",), (Opt("o1", ("항목",)), Opt("o2", ("금액",))), selected="o1"),),
        bindings={"성명": ("SOURCE", "이름"), "주소": ("CONST", "서울"),
                  "항목": ("BLANK",), "금액": ("SOURCE", "금액열"),
                  "PLAIN_f": ("CONST", "책갈피")},
        source_values={"이름": "홍길동", "금액열": "1000"},
        extra_bookmarks=("PLAIN",),
        guard_bookmarks=("GUARD", None),
    )


def _disjoint_slots() -> CaseSpec:
    return CaseSpec(
        slots=(
            SlotS("sA", (), (Opt("a1", ("가",)), Opt("a2", ("나",))), selected="a1"),
            SlotS("sB", (), (Opt("b1", ("다",)), Opt("b2", ("라",))), selected="b2"),
        ),
        bindings={"가": ("SOURCE", "k가"), "라": ("CONST", "고정")},
        source_values={"k가": "AA"},
    )


def _touching() -> CaseSpec:
    return CaseSpec(
        slots=(SlotS("s1", (), (Opt("o1", ("항목",)), Opt("o2", ("금액",))), selected="o1", touching=True),),
        bindings={"항목": ("SOURCE", "k항목")},
        source_values={"k항목": "TT"},
    )


def _empty_selected() -> CaseSpec:
    return CaseSpec(
        slots=(SlotS("s1", (), (Opt("o1", ()), Opt("o2", ("금액",))), selected="o1"),),
        bindings={},
        source_values={},
    )


def _field_in_selected() -> CaseSpec:
    return CaseSpec(
        slots=(SlotS("s1", (), (Opt("o1", ("항목",)), Opt("o2", ("금액",))), selected="o1"),),
        bindings={"항목": ("CONST", "선택값")},
        source_values={},
    )


def _mixed_owner() -> CaseSpec:
    return CaseSpec(
        root_fields=("성명",),
        slots=(SlotS("s1", ("주소",), (Opt("o1", ("항목",)), Opt("o2", ("금액",))), selected="o2"),),
        bindings={"성명": ("SOURCE", "이름"), "주소": ("CONST", "서울"),
                  "항목": ("SOURCE", "k항목"), "금액": ("BLANK",)},
        source_values={"이름": "김철수"},
    )


POSITIVE = {
    "slotless_ordinary_fill": _slotless_case,
    "option_one_of_two": _one_of_two,
    "disjoint_slots": _disjoint_slots,
    "touching_boundary": _touching,
    "empty_selected_option": _empty_selected,
    "field_in_selected_option": _field_in_selected,
    "root_shared_option_mix": _mixed_owner,
}


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
            plan_schema_version="hwpx-execution-plan/v1",
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


# ── fix #3: 채움 완화(FillNote)는 삼키지 않고 표면화한다 ────────────────────────────────
def _synth_case() -> CaseSpec:
    # 값 hp:t 가 없는 빈 root Field — set_field 가 slot 을 합성(slot_synthesized)한다.
    return CaseSpec(
        empty_root_fields=("빈칸",),
        bindings={"빈칸": ("CONST", "채움")},
    )


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
