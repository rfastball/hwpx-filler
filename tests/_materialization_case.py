"""materialization 사례 조립기 — SG-02(#734) harness 에서 추출한 공유 fixture (S6-01 · #809).

REAL compiler(``qualify_and_compile_execution`` → ``compile_candidate``)와 REAL validator
(``validate_data_record_against_plan``)로 bytes·structure·Plan·VDR 를 세운다 — ordered_operations
를 손으로 위조하지 않는다. ``test_materialization_conformance``(conformance 층)와
``test_materialization_runner``(production port 층)가 같은 조립기를 쓴다.

- ``exact_content_digest`` 는 실제 blob bytes 의 content digest 다(위조값 금지) — production
  러너가 이 digest 로 Candidate blob 을 조달·재검증한다.
- ``_build_case(spec, bytes_from=…)`` 는 Plan/structure 는 ``spec`` 으로, candidate bytes 는
  ``bytes_from`` 으로 세운다 — 모든 digest 가 정합인데 structure↔bytes 만 어긋난(봉인 시점에
  structure 가 bytes 를 거짓말한) 사례를 재현하는 seam 이다(P7 이 잡아야 한다).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from lxml import etree

from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.application.candidate_revision import blob_digest
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
    NATIVE_PRIMITIVE_CONTRACT_ID,
    THEOREM_EVIDENCE_V1,
    theorem_evidence_digest,
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
from hwpxfiller.application.field_binding_input import build_field_binding_input
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
from hwpxfiller.external.materialization_conformance import apply_execution_plan_in_memory

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
    #: 본문 끝에 그대로 실릴 평문 문단 — 미변환 구간 표기(``{{#항목 …}}``) 재현용(S8-F1 #852).
    #: 필드도 BOOKMARK 도 만들지 않으므로 structure 선언은 건드리지 않는다.
    notation_lines: tuple[str, ...] = ()


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
    for line in spec.notation_lines:
        paras.append(_p(f"<hp:t>{line}</hp:t>"))

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


def _build_case(spec: CaseSpec, *, bytes_from: CaseSpec | None = None) -> Case:
    """spec 으로 structure·Plan·VDR 를, ``bytes_from``(기본 spec)으로 candidate bytes 를 세운다.

    ``bytes_from`` 을 달리 주면 모든 content digest 는 실제 bytes 에 정합인데 structure↔bytes
    대응만 어긋난 사례가 된다 — 봉인 시점에 structure 가 bytes 를 거짓말한 상황의 재현이며,
    그 대응을 잇는 유일한 검사는 P7 precheck 다(digest 는 각자 자신만 증명한다).
    """
    blob = _build_bytes(spec if bytes_from is None else bytes_from)
    struct = _build_structure(spec)
    sdig = template_structure_digest(struct)
    payload = QualificationProfileSemanticPayload(
        qualification_profile_id=PROFILE, media="hwpx", adapter_contract_version="a/1",
        product_rule_version="p/1", operation_alphabet_version="o/1",
        projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA, manifest_payload={"k": "v"},
    )
    applied = ExactAppliedTemplateInput(
        work_id=WORK, template_application_id=APP, revision_id="rev-1", media="hwpx",
        template_lineage_id="lin-1", exact_content_digest=blob_digest(blob),
        canonical_blob_reference="blob://x",
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


def _escaping_case() -> CaseSpec:
    # S6-06(#809) escaping corpus — XML 특수문자·pre-escaped 처럼 보이는 리터럴·개행·CDATA 꼬리.
    # logical text 는 VDR 가, XML escaping 은 native serialization 이 소유한다는 분업의 양성 증거.
    return CaseSpec(
        root_fields=("특수", "리터럴", "여러줄", "꼬리"),
        bindings={
            "특수": ("SOURCE", "k특수"),
            "리터럴": ("CONST", "&amp;"),
            "여러줄": ("SOURCE", "k여러줄"),
            "꼬리": ("CONST", "]]>"),
        },
        source_values={"k특수": 'A&B<C>D"E\'F', "k여러줄": "한글\n두줄"},
    )


def _synth_case() -> CaseSpec:
    # 값 hp:t 가 없는 빈 root Field — set_field 가 slot 을 합성(slot_synthesized)한다.
    return CaseSpec(
        empty_root_fields=("빈칸",),
        bindings={"빈칸": ("CONST", "채움")},
    )


POSITIVE = {
    "slotless_ordinary_fill": _slotless_case,
    "option_one_of_two": _one_of_two,
    "disjoint_slots": _disjoint_slots,
    "touching_boundary": _touching,
    "empty_selected_option": _empty_selected,
    "field_in_selected_option": _field_in_selected,
    "root_shared_option_mix": _mixed_owner,
    "escaping_special_chars": _escaping_case,
}
