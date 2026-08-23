"""In-memory native materialization conformance port (SG-02 · #734).

이 모듈은 S5 composition theorem 이 **actual HWPX native mutation** 을 함의하지 않음을 반증
가능하게 하는, 실제 production native primitive 위의 얇은 **sequencer + checker** 다. production
소유자는 S6-01(#809)의 :class:`hwpxfiller.external.materialization_runner
.ProductionMaterializationRunner` **하나**다 — executor/verifier 를 ref+store 조달로 감싸
재사용하고, S6-02 start gate·S6-04 atomic delivery 가 그 러너를 다시 감싼다. 다른 production
모듈은 이 함수들을 직접 부르지 않는다(repo-contract 가 강제).

경계(issue #734):
- **새 의미(semantic) 파생 0**. 어떤 Option 을 제거할지는 오직 Plan 의 ``REMOVE_OPTION`` op 에서,
  어떤 text 를 쓸지는 오직 VDR 의 logical document value 에서 온다. selection/qualification 을
  이 포트 안에서 다시 계산하지 않는다(= "두 번째 materializer" 금지).
- **실제 production native primitive 를 호출한다**: :func:`remove_slot_option`(Option 제거),
  :class:`FieldDocument` ``set_field``/``apply_field_fill``(Active Field write),
  :meth:`HwpxPackage.to_bytes`/``from_bytes``(serialize/reparse). legacy ``HwpxEngine.generate`` 를
  oracle 로 쓰지 않는다 — 그 blank-skip 은 INTENTIONAL_BLANK 의 write-empty 의미를 위반한다.
- **bytes 에서 멈춘다**. production ``StartMaterialization``·Artifact identity·filesystem write 를
  하지 않는다.
- **source Candidate bytes 불변**. executor 는 ``from_bytes`` clone 위에서만 작동한다 — source
  entries 를 절대 건드리지 않는다.
- **fail-closed**. unknown native primitive contract → 거절(``UnsupportedNativePrimitiveContract``),
  v1 으로 조용히 해석하지 않는다. theorem PASS + actual FAIL 은 재현 가능하게 fail-closed 이고
  serialize/reparse/postcondition 실패는 서로 **distinct failure code** 로 구분된다.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from lxml import etree

from hwpxcore.bookmark_region import resolve_bookmark_topology
from hwpxcore.field_occurrence import resolve_field_occurrences
from hwpxcore.package import HwpxPackage
from hwpxcore.text_extract import require_package
from hwpxfiller.application.execution_composition import (
    NATIVE_PRIMITIVE_CONTRACT_ID,
    UnsupportedNativePrimitiveContract,
)
from hwpxfiller.application.execution_contract_set import (
    PLAN_APPLY_FIELD_BINDING,
    PLAN_REMOVE_OPTION,
    SealedExecutionPlanSemanticPayload,
)
from hwpxfiller.application.execution_structure import (
    OWNER_OPTION,
    ExecutionTemplateStructure,
)
from hwpxfiller.domain.fields import (
    FieldDocument,
    FillNote,
    field_xml_names,
    normalize_field_id,
)
from hwpxfiller.external.template_inspection import inspect_slots, remove_slot_option

CONFORMANCE_CONTRACT_ID = "hwpx-materialization-conformance/v1"

# reopen/reparse 실패로 취급하는 오류 집합(bad zip·bad mimetype·malformed XML).
_REOPEN_ERRORS = (ValueError, etree.XMLSyntaxError, zipfile.BadZipFile)

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
class InMemoryMaterialization:
    """executor 결과 — output bytes 와, 채움이 "경고 후 진행"으로 처리한 완화 사실(FillNote).

    ``FieldDocument.set_field`` 은 inline range 를 벗기거나(``inline_stripped``) 값 슬롯을
    합성할 때(``slot_synthesized``) native content 를 제거·합성하는 완화를 기록한다. 이
    사실을 삼키면 relaxation 이 조용히 통과하므로(confirm-or-alarm 위반) bytes 와 함께
    돌려주고, 상위(포트·미래 S6 wrapper)가 record/warn 하게 표면화한다.
    """

    output_bytes: bytes
    notes: tuple[FillNote, ...]


@dataclass(frozen=True)
class ConformancePass:
    """모든 postcondition 이 actual reopened output 에서 충족됨."""

    output_digest: str
    notes: tuple[FillNote, ...] = ()


@dataclass(frozen=True)
class ConformanceFailure:
    """actual native mutation 결과가 postcondition 을 위반 — distinct code 로 재진술."""

    code: str
    detail: str


ConformanceResult = ConformancePass | ConformanceFailure


# ─── op / vdr projection(포트가 새 의미를 파생하지 않는 두 입력) ─────────────────────────
def _op_code(op: Mapping[str, Any]) -> str:
    code = op.get("op")
    if not isinstance(code, str):
        raise ConformanceExecutionError(f"operation 에 op code 가 없다: {op!r}")
    return code


def _op_field(op: Mapping[str, Any]) -> str:
    value = op.get("field_id")
    if not isinstance(value, str) or value == "":
        raise ConformanceExecutionError(f"APPLY_FIELD_BINDING 에 field_id 가 없다: {op!r}")
    return value


# ═══ executor: exact Candidate bytes → clone → RemoveOption → ApplyFieldBinding → bytes ═══
def apply_execution_plan_in_memory(
    *,
    candidate_bytes: bytes,
    ordered_operations: Iterable[Mapping[str, Any]],
    document_values: Mapping[str, str],
) -> InMemoryMaterialization:
    """exact Candidate bytes 에 Plan 의 ordered operation 을 in-memory 로 적용해 output 을 낸다.

    순수 sequencer: ``ordered_operations`` 를 **선언 순서 그대로** 적용한다. ``REMOVE_OPTION`` 은
    :func:`remove_slot_option` 로, ``APPLY_FIELD_BINDING`` 은 VDR 이 낸 ``document_values`` 의 exact
    logical text 를 모든 content entry 의 해당 Active Field 에 쓴다. source ``candidate_bytes`` 는
    ``from_bytes`` clone 위에서만 다뤄 절대 변형되지 않는다(P6). 새 의미를 파생하지 않는다 —
    무엇을 제거/기입할지는 op·VDR 이 이미 정한다.

    반환은 output bytes 와 함께 채움이 남긴 완화 사실(:class:`FillNote`)이다 — inline strip·slot
    synthesize 같은 native content 완화를 삼키지 않고 표면화한다(confirm-or-alarm).
    """
    pkg = HwpxPackage.from_bytes(candidate_bytes)  # clone — source blob 불변
    notes: list[FillNote] = []
    for op in ordered_operations:
        code = _op_code(op)
        if code == PLAN_REMOVE_OPTION:
            slot_id, option_id = op.get("slot_id"), op.get("option_id")
            if not isinstance(slot_id, str) or not isinstance(option_id, str):
                raise ConformanceExecutionError(f"REMOVE_OPTION operand 형식 불량: {op!r}")
            remove_slot_option(pkg, slot_id, option_id)
        elif code == PLAN_APPLY_FIELD_BINDING:
            field_id = _op_field(op)
            if field_id not in document_values:
                raise ConformanceExecutionError(
                    f"Active Field {field_id!r} 에 대응하는 VDR document value 가 없다"
                )
            notes.extend(_write_active_field(pkg, field_id, document_values[field_id]))
        else:
            # unknown op 를 v1 으로 조용히 해석하지 않는다(fail-closed).
            raise UnsupportedNativePrimitiveContract(f"미지원 operation code: {code!r}")
    return InMemoryMaterialization(pkg.to_bytes(), tuple(dict.fromkeys(notes)))


def _write_active_field(pkg: HwpxPackage, field_id: str, text: str) -> list[FillNote]:
    """모든 field-target content entry 에 exact logical text 를 쓰고 완화 사실을 모아 돌려준다.

    한 entry 라도 기입 가능한 자리가 있으면 성공. 어느 entry 에서도 못 쓰면(=Active Field 가 bytes 에
    없음) 조용히 넘기지 않고 시끄럽게 닫는다. ``set_field`` 가 남긴 ``inline_stripped``/
    ``slot_synthesized`` 노트(native content 완화)는 삼키지 않고 호출측으로 올린다.
    """
    wrote = False
    notes: list[FillNote] = []
    for name in field_xml_names(pkg):
        doc = FieldDocument(pkg.entries[name], entry=name)
        if doc.set_field(field_id, text):
            pkg.entries[name] = doc.to_bytes()
            wrote = True
        notes.extend(doc.notes)
    if not wrote:
        raise ConformanceExecutionError(
            f"Active Field {field_id!r} 를 candidate 의 어느 content entry 에도 쓸 수 없다"
        )
    return notes


# ═══ P7 precheck: authored structure 가 exact Candidate bytes 와 id 일관 ═══════════════
def verify_structure_bytes_consistency(
    *, candidate_bytes: bytes, structure: ExecutionTemplateStructure
) -> ConformanceResult:
    """authored structure 의 slot/option/field id 가 실제 Candidate bytes 관찰과 일치하는지 교차검증.

    production 에는 bytes→structure extractor 가 없어 harness 가 structure 를 authoring 하므로, 그
    authored structure 가 bytes 를 조용히 거짓말하지 못하게 이 precheck 로 닫는다(fail-closed).
    """
    try:
        pkg = HwpxPackage.from_bytes(candidate_bytes)
        slots, diagnostics = inspect_slots(pkg)
    except _REOPEN_ERRORS as exc:
        return ConformanceFailure(STRUCTURE_BYTES_INCONSISTENT, f"candidate 재파싱 실패: {exc}")
    if diagnostics:
        return ConformanceFailure(
            STRUCTURE_BYTES_INCONSISTENT,
            "candidate inspect 가 blocking diagnostics 를 낸다: "
            + "; ".join(d.message for d in diagnostics),
        )
    bytes_options = {(slot.id, opt.id) for slot in slots for opt in slot.options}
    struct_options = {(r.slot_id, r.option_id) for r in structure.option_regions}
    if bytes_options != struct_options:
        return ConformanceFailure(
            STRUCTURE_BYTES_INCONSISTENT,
            f"structure Option id {sorted(struct_options)} 가 bytes {sorted(bytes_options)} 와 불일치",
        )
    bytes_fields = {fid for fid, _ in _read_field_values(pkg)}
    struct_fields = {occ.field_id for occ in structure.field_occurrences}
    # 완전 일치를 요구한다(subset 금지). subset 이면 candidate bytes 에 있는 ordinary Field 를
    # structure 가 누락해도 통과 → 컴파일러가 그 Field 에 write op 를 내지 않아 verifier 가 그대로
    # 두는 조용한 under-fill 을 인증하게 된다. 양방향(structure⊇bytes·structure⊆bytes)을 다 본다.
    if struct_fields != bytes_fields:
        return ConformanceFailure(
            STRUCTURE_BYTES_INCONSISTENT,
            f"structure Field 투영이 bytes 와 불일치: "
            f"structure-only={sorted(struct_fields - bytes_fields)}, "
            f"bytes-only={sorted(bytes_fields - struct_fields)}",
        )
    return ConformancePass(output_digest="")


# ═══ postcondition verifier: reopened OUTPUT 대상 defense-in-depth ═════════════════════
def verify_materialization_postconditions(
    *,
    source_bytes: bytes,
    output_bytes: bytes,
    plan: SealedExecutionPlanSemanticPayload,
    structure: ExecutionTemplateStructure,
    vdr: Any,
    execution_notes: Iterable[FillNote] = (),
) -> ConformanceResult:
    """actual applied output bytes 를 reopen 해 issue §3 의 최소 postcondition 을 전건 재검증한다.

    각 실패는 distinct code 로 재진술한다: P0 REPARSE_FAILED · P1 REMOVAL_INCOMPLETE · P2
    PRESERVED_CONTENT_LOST · P3 FIELD_TEXT_MISMATCH/OCCURRENCE_COUNT_MISMATCH · P4
    MARKER_CLEANUP_VIOLATION · P5 PROTECTED_STRUCTURE_LOSS · P6 SOURCE_CANDIDATE_MUTATED.
    primitive 내부 postcondition 을 최종으로 신뢰하지 않고 reopened output 위에서 다시 센다.

    ``structure`` 는 owner fact(ROOT/SLOT_SHARED/OPTION 귀속)를 제공해 P2 가 제거 대상이 아닌
    retained content 의 소실을 잡게 한다 — 새 의미를 파생하지 않고 이미 검증된 structure 의
    fact 만 읽는다. ``execution_notes`` 는 executor 가 올린 완화 사실로, PASS 결과에 그대로
    실려 상위가 record/warn 하게 한다.
    """
    contracts = plan.execution_basis.contracts
    if contracts.native_primitive_contract_id != NATIVE_PRIMITIVE_CONTRACT_ID:
        raise UnsupportedNativePrimitiveContract(
            f"미지원 native primitive contract(latest fallback 없음): "
            f"{contracts.native_primitive_contract_id!r}"
        )

    remove_ops = [
        op for op in plan.ordered_operations if op.get("op") == PLAN_REMOVE_OPTION
    ]
    removal_targets = {(op["slot_id"], op["option_id"]) for op in remove_ops}

    # P6 — source Candidate bytes 불변: executor 가 source 에서 target 을 제거하지 않았다.
    try:
        source_pkg = HwpxPackage.from_bytes(source_bytes)
        source_slots, source_diags = inspect_slots(source_pkg)
    except _REOPEN_ERRORS as exc:
        return ConformanceFailure(SOURCE_CANDIDATE_MUTATED, f"source 재파싱 실패: {exc}")
    if source_diags:
        return ConformanceFailure(
            SOURCE_CANDIDATE_MUTATED, "source inspect 가 blocking diagnostics 를 낸다"
        )
    source_options = {(slot.id, opt.id) for slot in source_slots for opt in slot.options}
    if not removal_targets <= source_options:
        return ConformanceFailure(
            SOURCE_CANDIDATE_MUTATED,
            f"removal target {sorted(removal_targets - source_options)} 가 source 에 없다(source 변형)",
        )

    # P0 — reopen/reparse: output zip·section XML 을 다시 읽을 수 있는가(pure serialize/reparse).
    try:
        reopen = HwpxPackage.from_bytes(output_bytes)
        entries = _parse_content_entries(reopen)
        out_slots, out_diags = inspect_slots(reopen)
    except _REOPEN_ERRORS as exc:
        return ConformanceFailure(REPARSE_FAILED, f"output 재파싱 실패: {exc}")

    # P4 — marker cleanup: 제거·기입 뒤 orphan/broken marker 가 남지 않았다(reparse 는 됐다).
    if out_diags:
        return ConformanceFailure(
            MARKER_CLEANUP_VIOLATION,
            "output inspect 가 blocking marker diagnostics 를 낸다: "
            + "; ".join(d.message for d in out_diags),
        )
    # inspect_slots 가 모든 content entry 의 bookmark/field marker topology 를 이미 gate 하므로
    # 여기 도달하면 pairing 은 usable 하다 — occurrence 를 그대로 읽는다.
    field_values: list[tuple[str, str]] = []
    for name, root in entries:
        for occ in resolve_field_occurrences(name, root).occurrences:
            field_id = normalize_field_id(occ.raw_name)
            if field_id is not None:
                field_values.append((field_id, _occurrence_text(occ)))

    out_options = {(slot.id, opt.id) for slot in out_slots for opt in slot.options}

    # P1 — 모든 unselected removal target 이 제거됐다.
    still_present = removal_targets & out_options
    if still_present:
        return ConformanceFailure(
            REMOVAL_INCOMPLETE, f"removal target 이 output 에 잔존: {sorted(still_present)}"
        )

    # P2 — selected/root/shared content 보존.
    # (a) target 아닌 Option marker 자체가 사라지지 않았다. 모든 Slot 은 최소 1 Option 을 갖고
    #     selection 은 non-target Option 을 남기므로, 통째 Slot 소실도 그 non-target Option 소실로
    #     여기서 함께 잡힌다(별도 slot-id 검사 불요).
    expected_remaining = source_options - removal_targets
    lost = expected_remaining - out_options
    if lost:
        return ConformanceFailure(
            PRESERVED_CONTENT_LOST, f"target 아닌 Option 이 output 에서 소실: {sorted(lost)}"
        )
    # (b) 제거 대상 Option 이 소유하지 않은 모든 Field occurrence 는 output 에 남아야 한다.
    #     owner fact 는 (이미 검증된) structure 에서, 제거 대상은 plan 에서 온다 — metatag 로
    #     product 의미를 재유도하지 않는다. option marker 만 남긴 채 root/shared/selected-option
    #     content 를 잃는 조용한 부패를 이 검사가 시끄럽게 닫는다(P2 가 option id 만 보던 구멍).
    #     정확한 active count/text 는 P3 소관이라 여기서는 '완전 소실'(presence)만 판정해 층을 가른다.
    retained_field_ids = {
        occ.field_id
        for occ in structure.field_occurrences
        if not (
            occ.owner_kind == OWNER_OPTION
            and (occ.owner_slot_id, occ.owner_option_id) in removal_targets
        )
    }
    present_field_ids = {field_id for field_id, _ in field_values}
    missing_content = retained_field_ids - present_field_ids
    if missing_content:
        return ConformanceFailure(
            PRESERVED_CONTENT_LOST,
            f"제거 대상이 아닌 retained content 가 output 에서 소실: {sorted(missing_content)}",
        )

    # P3 — 모든 Active Field occurrence 가 exact VDR logical text(+expected count).
    expected_text = dict(vdr.document_values_in_order())
    occ_by_field: dict[str, list[str]] = {}
    for field_id, value in field_values:
        occ_by_field.setdefault(field_id, []).append(value)
    for requirement in plan.active_field_requirements:
        field_id = str(requirement["field_id"])
        expected_count = int(requirement["expected_active_occurrence_count"])
        occurrences = occ_by_field.get(field_id, [])
        if len(occurrences) != expected_count:
            return ConformanceFailure(
                OCCURRENCE_COUNT_MISMATCH,
                f"Active Field {field_id!r} occurrence {len(occurrences)} != 기대 {expected_count}",
            )
        want = expected_text[field_id]
        for value in occurrences:
            if value != want:
                return ConformanceFailure(
                    FIELD_TEXT_MISMATCH,
                    f"Active Field {field_id!r} text {value!r} != 기대 {want!r}",
                )

    # P5 — protected structure: removed Option(및 그 안에 중첩된 region) 밖의 모든 BOOKMARK region 이
    # per-region topology(이름·부모·metatag) 그대로 output 에 보존됐다.
    protected = _protected_structure_loss(source_bytes, reopen, remove_ops)
    if protected is not None:
        return ConformanceFailure(PROTECTED_STRUCTURE_LOSS, protected)

    return ConformancePass(
        output_digest=_blob_digest(output_bytes), notes=tuple(execution_notes)
    )


# ─── P5 per-region topology helpers ───────────────────────────────────────────────────
def _region_topo_key(region: Any) -> tuple[str, str]:
    """removal 로 다른 region 을 지워도 안정한 per-region key(production ``_region_key`` 와 동형).

    ``name`` 은 None·중복 가능이라 identity 로 못 쓴다. section + native pairing id 는 다른 region
    제거·field write 로 재번호되지 않아 source↔output 을 잇는 안정 key 다.
    """
    return (region.section, region._pairing_id)


def _region_parent_key(region: Any) -> tuple[str, str] | None:
    parent = region.parent
    return None if parent is None else _region_topo_key(parent)


def _region_shape(region: Any) -> tuple[Any, ...]:
    """topology 값(위치 제외) — 이름·부모·metatag. 여기 하나라도 바뀌면 구조 변형이다."""
    return (
        region.name,
        _region_parent_key(region),
        region.meta_tags,
        region.meta_tag_attribute,
    )


def _protected_structure_loss(
    source_bytes: bytes,
    output_pkg: HwpxPackage,
    remove_ops: list[Mapping[str, Any]],
) -> str | None:
    """removed Option(및 그 안에 중첩된 region) 밖의 모든 BOOKMARK region 이 per-region topology 로
    보존됐는지 검사한다.

    count-기준(이전) 대신 stable per-region key 로 대조한다: (1) ``name is None`` region 도 세고,
    (2) 같은 이름 중복을 뭉개지 않으며, (3) removed Option 의 후손은 정당하게 사라진 것으로 다룬다.
    기대 topology 는 metatag 재파싱이 아니라 **실제 production 제거 primitive** 로 얻는다: source
    clone 에 plan 의 REMOVE_OPTION 만 적용한 reference 를 만든다(field write 는 BOOKMARK topology 에
    무영향). 그 reference 가 남긴 모든 region 은 output 에도 같은 key·shape 로 남아야 한다 — 제거
    Option 과 그 안에 중첩된 region 은 reference 에서도 함께 사라지므로 거짓 거절이 없다.

    stable key 는 (section, native pairing id) 로 production ``_region_key`` 와 동형이다 — 다른
    region 제거·field write 로 재번호되지 않아 reference↔output 을 잇는다.
    """
    reference = HwpxPackage.from_bytes(source_bytes)  # fresh clone — source 불변
    for op in remove_ops:
        remove_slot_option(reference, op["slot_id"], op["option_id"])

    expected = {
        _region_topo_key(r): _region_shape(r)
        for r in resolve_bookmark_topology(reference)
    }
    actual = {
        _region_topo_key(r): _region_shape(r)
        for r in resolve_bookmark_topology(output_pkg)
    }
    for key, want in expected.items():
        got = actual.get(key)
        if got is None:
            return f"보호 BOOKMARK region 이 output 에서 소실: key={key} shape={want}"
        if got != want:
            return f"보호 BOOKMARK region topology 변형: key={key} {want} != {got}"
    return None


# ─── 공용 native read helper ──────────────────────────────────────────────────────────
def _parse_content_entries(pkg: HwpxPackage) -> list[tuple[str, etree._Element]]:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    return [
        (name, etree.fromstring(pkg.entries[name], parser=parser))
        for name in field_xml_names(pkg)
    ]


def _occurrence_text(occ: Any) -> str:
    return "".join("".join(t.itertext()) for t in occ.texts)


def _read_field_values(pkg: object) -> list[tuple[str, str]]:
    package = require_package(pkg)
    values: list[tuple[str, str]] = []
    for name in field_xml_names(package):
        doc = FieldDocument(package.entries[name], entry=name)
        values.extend(doc.field_values())
    return values


def _blob_digest(blob: bytes) -> str:
    from hashlib import sha256

    return "sha256:" + sha256(blob).hexdigest()
