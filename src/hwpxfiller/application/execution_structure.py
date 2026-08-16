"""composition-ready Structure Projection v2 + additive Qualification Profile (S5-03 · #699).

v1(:mod:`hwpxfiller.application.qualification_evidence`)의 :class:`StructureProjection` 은
root/shared/option Field 와 제품 순서만 보존한다. ordered mutation composition 은 그 위에
occurrence·region·envelope·resolver·relation fact 전체가 필요하다. 이 모듈은 v1 의 의미를
**한 글자도 바꾸지 않고** additive ``hwpx-structure-projection-v2`` 와 이를 발행하는
composition-ready Qualification Profile 을 더한다.

경계:
- 순수·native-free. XML/HwpxPackage/BoundaryPairRef/native handle/mutable resolver/경로/ZIP
  entry 를 저장하지 않는다 — stable structural fact(정수 order, 문자열 id, bool)만 담는다.
- relation taxonomy 는 **분류만** 한다(target-target · target-owner · target-retained). 어떤
  relation 을 admission 할지의 *의미* 는 S5-04 소유. 여기서는 누락 없이 exact fact 를 낸다.
- publication 만으로 admission 되지 않는다 — admission state 를 만들지 않는다(S5-08 소유).

digest seam: :func:`template_structure_digest` 는 schema version·product structure·
occurrence/region/content-entry fact·relation fact·resolver/capability contract id·global
composition fact 를 덮고 created_at/주소/경로/handle/실행 시간은 제외한다. byte framing·
SHA-256 은 S5-06 소유 — 여기서는 semantic payload 와 stable ordering 만 고정한다
(# ponytail: 로컬 canonical dict 인코더 + content_digest, S5-06 이 byte framing 으로 대체).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from hwpxfiller.application.qualification_evidence import (
    StructureProjection,
    build_manifest,
    content_digest,
)
from hwpxfiller.application.template_qualification import TemplateStructure

# ─── schema·profile identity(규칙이 바뀌면 함께 올린다) ─────────────────────────────
EXECUTION_STRUCTURE_PROJECTION_SCHEMA = "hwpx-structure-projection-v2"
EXECUTION_QUALIFICATION_PROFILE_ID = "hwpx-template-qualification-v2"

# owner 귀속(정확히 하나).
OWNER_ROOT = "ROOT"
OWNER_SLOT_SHARED = "SLOT_SHARED"
OWNER_OPTION = "OPTION"
_OWNER_KINDS = frozenset({OWNER_ROOT, OWNER_SLOT_SHARED, OWNER_OPTION})

# geometric relation 어휘(closed 정수 order span).
DISJOINT = "DISJOINT"
TOUCHING = "TOUCHING"
CONTAINS = "CONTAINS"
CONTAINED = "CONTAINED"
SAME_SPAN = "SAME_SPAN"
CROSSING = "CROSSING"

# owner-target 경계 일치.
COINCIDE_SAME_SPAN = "SAME_SPAN"
COINCIDE_SAME_START = "SAME_START"
COINCIDE_SAME_END = "SAME_END"
COINCIDE_INTERIOR = "INTERIOR"

# target-retained 위치.
POSITION_BEFORE = "BEFORE"
POSITION_INSIDE = "INSIDE"
POSITION_AFTER = "AFTER"

# 최소 envelope capability fact(빠지면 fact-missing). 값은 bool.
ENVELOPE_CAPABILITY_KEYS = (
    "retains_admissible_envelope",  # target 제거 뒤 허용 envelope 유지
    "handles_empty_edges",  # 빈 entry/paragraph/section edge 처리
    "preserves_owner_marker",  # owner marker·entry envelope 보존
    "coincident_boundary_admissible",  # coincident boundary primitive admission 근거
)

# 최소 resolver stability fact(빠지면 fact-missing). 값은 bool.
RESOLVER_STABILITY_KEYS = (
    "remaining_target_resolvable_after_removal",  # 앞선 RemoveOption 뒤 뒤 target 재탐색
    "active_field_resolvable_after_removal",  # 모든 제거 뒤 Active Field occurrence 재탐색
    "field_write_preserves_identity",  # Field write 가 다른 marker/value identity 무효화 안 함
)


# ─── 오류(issue 열거 그대로) ──────────────────────────────────────────────────────
class ExecutionStructureError(ValueError):
    """v2 projection 조립·무결성 오류의 뿌리."""

    code = "EXECUTION_STRUCTURE_PROJECTION_INTEGRITY_ERROR"


class UnsupportedExecutionStructureProjection(ExecutionStructureError):
    code = "UNSUPPORTED_EXECUTION_STRUCTURE_PROJECTION"


class ExecutionStructureProjectionIntegrityError(ExecutionStructureError):
    code = "EXECUTION_STRUCTURE_PROJECTION_INTEGRITY_ERROR"


class ExecutionStructureOccurrenceIncomplete(ExecutionStructureError):
    code = "EXECUTION_STRUCTURE_OCCURRENCE_INCOMPLETE"


class ExecutionStructureRelationIncomplete(ExecutionStructureError):
    code = "EXECUTION_STRUCTURE_RELATION_INCOMPLETE"


class ExecutionStructureEnvelopeFactMissing(ExecutionStructureError):
    code = "EXECUTION_STRUCTURE_ENVELOPE_FACT_MISSING"


class ExecutionStructureResolverFactMissing(ExecutionStructureError):
    code = "EXECUTION_STRUCTURE_RESOLVER_FACT_MISSING"


class ExecutionProfileNotSealable(ExecutionStructureError):
    code = "EXECUTION_PROFILE_NOT_SEALABLE"


class QualificationProfileManifestIntegrityError(ExecutionStructureError):
    code = "QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR"


# ─── DTO — 저장되는 stable fact ──────────────────────────────────────────────────
@dataclass(frozen=True)
class FieldOccurrence:
    """logical Field 와 native occurrence 를 분리한 exact fact."""

    field_id: str
    occurrence_ordinal: int
    owner_kind: str  # ROOT | SLOT_SHARED | OPTION 중 정확히 하나
    owner_slot_id: str | None
    owner_option_id: str | None
    content_entry_id: str
    structural_order: int
    native_value_target_class: str
    resolver_contract_id: str


@dataclass(frozen=True)
class OptionRegionRef:
    slot_id: str
    option_id: str


@dataclass(frozen=True)
class OptionRegion:
    """제거 가능한 exact region — begin/end 는 native handle 이 아니라 stable order fact."""

    slot_id: str
    option_id: str
    content_entry_id: str
    begin_order: int
    end_order: int
    owner_relation_facts: tuple[Mapping[str, Any], ...]  # target-owner
    retained_content_relation_facts: tuple[Mapping[str, Any], ...]  # target-retained
    removal_capability_ref: str

    @property
    def ref(self) -> OptionRegionRef:
        return OptionRegionRef(self.slot_id, self.option_id)


@dataclass(frozen=True)
class RemovalTargetRelation:
    """두 distinct Option removal target 사이 관계(target-target)."""

    left_option_ref: OptionRegionRef
    right_option_ref: OptionRegionRef
    relation: str


@dataclass(frozen=True)
class ContentEntry:
    content_entry_id: str
    envelope_class: str
    envelope_capability_facts: Mapping[str, bool]


@dataclass(frozen=True)
class GlobalCompositionFacts:
    crossing_free: bool
    resolver_stability_facts: Mapping[str, bool]
    admitted_relation_profile: str


@dataclass(frozen=True)
class ExecutionTemplateStructure:
    """native-free composition-ready projection(hwpx-structure-projection-v2)."""

    projection_schema_version: str
    product_structure: TemplateStructure
    field_occurrences: tuple[FieldOccurrence, ...]
    option_regions: tuple[OptionRegion, ...]
    removal_target_relations: tuple[RemovalTargetRelation, ...]
    content_entries: tuple[ContentEntry, ...]
    global_composition_facts: GlobalCompositionFacts


# ─── builder 입력(native-free 관찰값 — 최종 DTO 에는 안 실림) ─────────────────────────
@dataclass(frozen=True)
class SlotRegionObservation:
    """owner-target relation 계산에만 쓰는 Slot 의 stable order span."""

    slot_id: str
    content_entry_id: str
    begin_order: int
    end_order: int


@dataclass(frozen=True)
class OptionRegionObservation:
    slot_id: str
    option_id: str
    content_entry_id: str
    begin_order: int
    end_order: int
    removal_capability_ref: str


# ─── geometry ───────────────────────────────────────────────────────────────────
def classify_span_relation(a: tuple[int, int], b: tuple[int, int]) -> str:
    """closed 정수 order span 두 개의 관계를 exact taxonomy 로 분류한다.

    ``a`` 관점: ``a`` 가 ``b`` 를 담으면 CONTAINS, 반대면 CONTAINED.
    """
    ab, ae = a
    bb, be = b
    lo = max(ab, bb)
    hi = min(ae, be)
    if ab == bb and ae == be:
        return SAME_SPAN
    if hi < lo:
        return DISJOINT
    if hi == lo:
        return TOUCHING
    if ab <= bb and be <= ae:
        return CONTAINS
    if bb <= ab and ae <= be:
        return CONTAINED
    return CROSSING


def _owner_coincidence(option: tuple[int, int], slot: tuple[int, int]) -> str:
    same_start = option[0] == slot[0]
    same_end = option[1] == slot[1]
    if same_start and same_end:
        return COINCIDE_SAME_SPAN
    if same_start:
        return COINCIDE_SAME_START
    if same_end:
        return COINCIDE_SAME_END
    return COINCIDE_INTERIOR


def _point_position(order: int, span: tuple[int, int]) -> str:
    if order < span[0]:
        return POSITION_BEFORE
    if order > span[1]:
        return POSITION_AFTER
    return POSITION_INSIDE


# ─── validation helpers ──────────────────────────────────────────────────────────
def _require_text(value: str, what: str) -> None:
    if not isinstance(value, str) or value == "":
        raise ExecutionStructureProjectionIntegrityError(f"{what} 는 비어 있지 않은 문자열이어야 한다")


def _require_span(begin: int, end: int, what: str) -> None:
    if not isinstance(begin, int) or not isinstance(end, int) or begin >= end:
        raise ExecutionStructureProjectionIntegrityError(
            f"{what} 의 order span 이 유효하지 않다: [{begin}, {end}]"
        )


def _product_index(
    structure: TemplateStructure,
) -> tuple[frozenset[str], dict[str, frozenset[str]], dict[tuple[str, str], frozenset[str]]]:
    """product_structure 를 owner 별 Field 집합으로 색인(v1 순서·의미 손실 없음)."""
    root = frozenset(structure.root_fields)
    shared: dict[str, frozenset[str]] = {}
    option: dict[tuple[str, str], frozenset[str]] = {}
    seen_slots: set[str] = set()
    for slot in structure.slots:
        if slot.id in seen_slots:
            raise ExecutionStructureProjectionIntegrityError(f"product Slot id 중복: {slot.id!r}")
        seen_slots.add(slot.id)
        shared[slot.id] = frozenset(slot.shared_fields)
        seen_options: set[str] = set()
        for opt in slot.options:
            if opt.id in seen_options:
                raise ExecutionStructureProjectionIntegrityError(
                    f"Slot {slot.id!r} 안 Option id 중복: {opt.id!r}"
                )
            seen_options.add(opt.id)
            option[(slot.id, opt.id)] = frozenset(opt.fields)
    return root, shared, option


def _validate_content_entries(
    content_entries: tuple[ContentEntry, ...],
) -> frozenset[str]:
    ids: set[str] = set()
    for entry in content_entries:
        _require_text(entry.content_entry_id, "content_entry_id")
        _require_text(entry.envelope_class, "envelope_class")
        if entry.content_entry_id in ids:
            raise ExecutionStructureProjectionIntegrityError(
                f"content_entry_id 중복: {entry.content_entry_id!r}"
            )
        ids.add(entry.content_entry_id)
        for key in ENVELOPE_CAPABILITY_KEYS:
            if not isinstance(entry.envelope_capability_facts.get(key), bool):
                raise ExecutionStructureEnvelopeFactMissing(
                    f"content entry {entry.content_entry_id!r} 에 envelope fact {key!r} 부재"
                )
    return frozenset(ids)


def _validate_occurrences(
    occurrences: tuple[FieldOccurrence, ...],
    root: frozenset[str],
    shared: dict[str, frozenset[str]],
    option: dict[tuple[str, str], frozenset[str]],
    entry_ids: frozenset[str],
) -> None:
    by_field: dict[str, list[int]] = {}
    structural_orders: set[int] = set()
    covered_root: set[str] = set()
    covered_shared: set[tuple[str, str]] = set()
    covered_option: set[tuple[str, str, str]] = set()

    for occ in occurrences:
        _require_text(occ.field_id, "field_id")
        _require_text(occ.content_entry_id, "occurrence.content_entry_id")
        _require_text(occ.native_value_target_class, "native_value_target_class")
        if occ.owner_kind not in _OWNER_KINDS:
            raise ExecutionStructureProjectionIntegrityError(
                f"owner_kind 가 ROOT/SLOT_SHARED/OPTION 밖: {occ.owner_kind!r}"
            )
        if not isinstance(occ.occurrence_ordinal, int) or occ.occurrence_ordinal < 0:
            raise ExecutionStructureProjectionIntegrityError(
                f"occurrence_ordinal 이 음수/비정수: {occ.occurrence_ordinal!r}"
            )
        if not occ.resolver_contract_id:
            raise ExecutionStructureResolverFactMissing(
                f"Field {occ.field_id!r} occurrence 에 resolver_contract_id 부재"
            )
        if occ.content_entry_id not in entry_ids:
            raise ExecutionStructureEnvelopeFactMissing(
                f"occurrence 가 미선언 content entry 참조: {occ.content_entry_id!r}"
            )

        # owner 는 정확히 하나 — 참조 존재/부재가 owner_kind 와 정합해야 한다.
        if occ.owner_kind == OWNER_ROOT:
            if occ.owner_slot_id is not None or occ.owner_option_id is not None:
                raise ExecutionStructureProjectionIntegrityError("ROOT occurrence 는 owner ref 가 없다")
            if occ.field_id not in root:
                raise ExecutionStructureProjectionIntegrityError(
                    f"root Field {occ.field_id!r} 가 product structure 에 없다"
                )
            covered_root.add(occ.field_id)
        elif occ.owner_kind == OWNER_SLOT_SHARED:
            if occ.owner_slot_id is None or occ.owner_option_id is not None:
                raise ExecutionStructureProjectionIntegrityError(
                    "SLOT_SHARED occurrence 는 slot ref 만 갖는다"
                )
            fields = shared.get(occ.owner_slot_id)
            if fields is None or occ.field_id not in fields:
                raise ExecutionStructureProjectionIntegrityError(
                    f"shared Field {occ.field_id!r} 가 Slot {occ.owner_slot_id!r} 에 없다"
                )
            covered_shared.add((occ.owner_slot_id, occ.field_id))
        else:  # OWNER_OPTION
            if occ.owner_slot_id is None or occ.owner_option_id is None:
                raise ExecutionStructureProjectionIntegrityError(
                    "OPTION occurrence 는 slot·option ref 를 모두 갖는다"
                )
            key = (occ.owner_slot_id, occ.owner_option_id)
            fields = option.get(key)
            if fields is None or occ.field_id not in fields:
                raise ExecutionStructureProjectionIntegrityError(
                    f"option Field {occ.field_id!r} 가 {key} 에 없다"
                )
            covered_option.add((occ.owner_slot_id, occ.owner_option_id, occ.field_id))

        if occ.structural_order in structural_orders:
            raise ExecutionStructureProjectionIntegrityError(
                f"structural_order 중복: {occ.structural_order}"
            )
        structural_orders.add(occ.structural_order)
        by_field.setdefault(occ.field_id, []).append(occ.occurrence_ordinal)

    # occurrence ordinal 은 같은 field_id 안에서 0..n-1 contiguous·무중복이어야 한다.
    for field_id, ordinals in by_field.items():
        expected = set(range(len(ordinals)))
        if len(set(ordinals)) != len(ordinals):
            raise ExecutionStructureProjectionIntegrityError(
                f"Field {field_id!r} occurrence ordinal 중복: {sorted(ordinals)}"
            )
        if set(ordinals) != expected:
            raise ExecutionStructureOccurrenceIncomplete(
                f"Field {field_id!r} occurrence ordinal 이 0..n-1 이 아니다: {sorted(ordinals)}"
            )

    # 모든 product Field 는 occurrence 를 하나 이상 가져야 한다.
    missing = (
        [f"root:{fid}" for fid in root - covered_root]
        + [
            f"shared:{sid}/{fid}"
            for sid, fields in shared.items()
            for fid in fields
            if (sid, fid) not in covered_shared
        ]
        + [
            f"option:{sid}/{oid}/{fid}"
            for (sid, oid), fields in option.items()
            for fid in fields
            if (sid, oid, fid) not in covered_option
        ]
    )
    if missing:
        raise ExecutionStructureOccurrenceIncomplete(
            f"occurrence 가 없는 product Field: {sorted(missing)}"
        )


def build_execution_structure(
    *,
    product_structure: TemplateStructure,
    occurrences: Iterable[FieldOccurrence],
    slot_regions: Iterable[SlotRegionObservation],
    option_regions: Iterable[OptionRegionObservation],
    content_entries: Iterable[ContentEntry],
    resolver_stability_facts: Mapping[str, bool],
    admitted_relation_profile: str,
    projection_schema_version: str = EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
) -> ExecutionTemplateStructure:
    """native-free 관찰값에서 exact v2 projection 을 조립·검증한다.

    같은 입력은 같은 semantic payload 를 낸다(deterministic). fact 누락·중복은 추측 FAIL 이
    아니라 issue 가 열거한 integrity/incomplete 오류로 닫힌다.
    """
    if projection_schema_version != EXECUTION_STRUCTURE_PROJECTION_SCHEMA:
        raise UnsupportedExecutionStructureProjection(
            f"미지원 execution structure projection schema: {projection_schema_version}"
        )
    occ_tuple = tuple(occurrences)
    entry_tuple = tuple(content_entries)
    slot_obs = tuple(slot_regions)
    option_obs = tuple(option_regions)

    root, shared, option = _product_index(product_structure)
    entry_ids = _validate_content_entries(entry_tuple)
    _validate_occurrences(occ_tuple, root, shared, option, entry_ids)

    # resolver stability(global) fact 전건.
    for key in RESOLVER_STABILITY_KEYS:
        if not isinstance(resolver_stability_facts.get(key), bool):
            raise ExecutionStructureResolverFactMissing(f"resolver stability fact {key!r} 부재")
    _require_text(admitted_relation_profile, "admitted_relation_profile")

    # Slot span — owner-target relation 계산용. 모든 product Slot 이 정확히 하나.
    slot_spans: dict[str, tuple[int, int]] = {}
    for obs in slot_obs:
        if obs.slot_id not in shared:
            raise ExecutionStructureProjectionIntegrityError(
                f"Slot region 이 product 밖 Slot 참조: {obs.slot_id!r}"
            )
        if obs.slot_id in slot_spans:
            raise ExecutionStructureProjectionIntegrityError(f"Slot region 중복: {obs.slot_id!r}")
        _require_span(obs.begin_order, obs.end_order, f"Slot {obs.slot_id!r} region")
        if obs.content_entry_id not in entry_ids:
            raise ExecutionStructureEnvelopeFactMissing(
                f"Slot region 이 미선언 content entry 참조: {obs.content_entry_id!r}"
            )
        slot_spans[obs.slot_id] = (obs.begin_order, obs.end_order)
    if set(slot_spans) != set(shared):
        raise ExecutionStructureRelationIncomplete(
            f"Slot region 이 없는 Slot: {sorted(set(shared) - set(slot_spans))}"
        )

    # Option region — begin/end·containment·capability 검증.
    option_spans: dict[tuple[str, str], tuple[int, int]] = {}
    region_entry: dict[tuple[str, str], str] = {}
    removal_refs: dict[tuple[str, str], str] = {}
    for obs in option_obs:
        key = (obs.slot_id, obs.option_id)
        if key not in option:
            raise ExecutionStructureProjectionIntegrityError(
                f"Option region 이 product 밖 Option 참조: {key}"
            )
        if key in option_spans:
            raise ExecutionStructureProjectionIntegrityError(f"Option region 중복: {key}")
        _require_span(obs.begin_order, obs.end_order, f"Option {key} region")
        if obs.content_entry_id not in entry_ids:
            raise ExecutionStructureEnvelopeFactMissing(
                f"Option region 이 미선언 content entry 참조: {obs.content_entry_id!r}"
            )
        _require_text(obs.removal_capability_ref, "removal_capability_ref")
        slot_span = slot_spans[obs.slot_id]
        if obs.begin_order < slot_span[0] or obs.end_order > slot_span[1]:
            raise ExecutionStructureProjectionIntegrityError(
                f"Option {key} region 이 owning Slot span 밖으로 벗어난다"
            )
        option_spans[key] = (obs.begin_order, obs.end_order)
        region_entry[key] = obs.content_entry_id
        removal_refs[key] = obs.removal_capability_ref
    if set(option_spans) != set(option):
        raise ExecutionStructureRelationIncomplete(
            f"Option region 이 없는 Option: {sorted(set(option) - set(option_spans))}"
        )

    # ── 계산: target-target / target-owner / target-retained ────────────────────
    sorted_keys = sorted(option_spans)
    removal_relations: list[RemovalTargetRelation] = []
    for i in range(len(sorted_keys)):
        for j in range(i + 1, len(sorted_keys)):
            left, right = sorted_keys[i], sorted_keys[j]
            removal_relations.append(
                RemovalTargetRelation(
                    OptionRegionRef(*left),
                    OptionRegionRef(*right),
                    classify_span_relation(option_spans[left], option_spans[right]),
                )
            )
    crossing_free = all(r.relation != CROSSING for r in removal_relations)

    regions: list[OptionRegion] = []
    for key in sorted_keys:
        slot_id, option_id = key
        span = option_spans[key]
        owner_facts: tuple[Mapping[str, Any], ...] = (
            {
                "relation": "target_owner_slot",
                "slot_id": slot_id,
                "coincidence": _owner_coincidence(span, slot_spans[slot_id]),
            },
            {
                "relation": "target_owner_content_entry",
                "content_entry_id": region_entry[key],
            },
        )
        retained_facts = tuple(
            {
                "field_id": occ.field_id,
                "occurrence_ordinal": occ.occurrence_ordinal,
                "owner_kind": occ.owner_kind,
                "position": _point_position(occ.structural_order, span),
            }
            for occ in sorted(occ_tuple, key=lambda o: o.structural_order)
            if not (occ.owner_kind == OWNER_OPTION
                    and occ.owner_slot_id == slot_id
                    and occ.owner_option_id == option_id)
        )
        regions.append(
            OptionRegion(
                slot_id=slot_id,
                option_id=option_id,
                content_entry_id=region_entry[key],
                begin_order=span[0],
                end_order=span[1],
                owner_relation_facts=owner_facts,
                retained_content_relation_facts=retained_facts,
                removal_capability_ref=removal_refs[key],
            )
        )

    return ExecutionTemplateStructure(
        projection_schema_version=projection_schema_version,
        product_structure=product_structure,
        field_occurrences=tuple(sorted(occ_tuple, key=lambda o: o.structural_order)),
        option_regions=tuple(regions),
        removal_target_relations=tuple(removal_relations),
        content_entries=tuple(sorted(entry_tuple, key=lambda e: e.content_entry_id)),
        global_composition_facts=GlobalCompositionFacts(
            crossing_free=crossing_free,
            resolver_stability_facts=dict(resolver_stability_facts),
            admitted_relation_profile=admitted_relation_profile,
        ),
    )


# ─── canonical semantic payload + digest seam ────────────────────────────────────
def _encode_product_structure(structure: TemplateStructure) -> dict[str, Any]:
    # v1 payload 와 같은 shape·순서(lossless) — S4 v2 decoder 가 이걸 그대로 읽는다.
    return {
        "root_fields": list(structure.root_fields),
        "slots": [
            {
                "id": slot.id,
                "shared_fields": list(slot.shared_fields),
                "options": [{"id": o.id, "fields": list(o.fields)} for o in slot.options],
            }
            for slot in structure.slots
        ],
    }


def encode_execution_structure(structure: ExecutionTemplateStructure) -> dict[str, Any]:
    """v2 semantic payload — stable ordering. content_digest 가 이걸 주소화한다."""
    return {
        "projection_schema_version": structure.projection_schema_version,
        "product_structure": _encode_product_structure(structure.product_structure),
        "field_occurrences": [
            {
                "field_id": o.field_id,
                "occurrence_ordinal": o.occurrence_ordinal,
                "owner_kind": o.owner_kind,
                "owner_slot_id": o.owner_slot_id,
                "owner_option_id": o.owner_option_id,
                "content_entry_id": o.content_entry_id,
                "structural_order": o.structural_order,
                "native_value_target_class": o.native_value_target_class,
                "resolver_contract_id": o.resolver_contract_id,
            }
            for o in sorted(structure.field_occurrences, key=lambda o: o.structural_order)
        ],
        "option_regions": [
            {
                "slot_id": r.slot_id,
                "option_id": r.option_id,
                "content_entry_id": r.content_entry_id,
                "begin_order": r.begin_order,
                "end_order": r.end_order,
                "owner_relation_facts": [dict(f) for f in r.owner_relation_facts],
                "retained_content_relation_facts": [
                    dict(f) for f in r.retained_content_relation_facts
                ],
                "removal_capability_ref": r.removal_capability_ref,
            }
            for r in sorted(structure.option_regions, key=lambda r: (r.slot_id, r.option_id))
        ],
        "removal_target_relations": [
            {
                "left_option_ref": {
                    "slot_id": r.left_option_ref.slot_id,
                    "option_id": r.left_option_ref.option_id,
                },
                "right_option_ref": {
                    "slot_id": r.right_option_ref.slot_id,
                    "option_id": r.right_option_ref.option_id,
                },
                "relation": r.relation,
            }
            for r in sorted(
                structure.removal_target_relations,
                key=lambda r: (
                    r.left_option_ref.slot_id,
                    r.left_option_ref.option_id,
                    r.right_option_ref.slot_id,
                    r.right_option_ref.option_id,
                ),
            )
        ],
        "content_entries": [
            {
                "content_entry_id": e.content_entry_id,
                "envelope_class": e.envelope_class,
                "envelope_capability_facts": dict(e.envelope_capability_facts),
            }
            for e in sorted(structure.content_entries, key=lambda e: e.content_entry_id)
        ],
        "global_composition_facts": {
            "crossing_free": structure.global_composition_facts.crossing_free,
            "resolver_stability_facts": dict(
                structure.global_composition_facts.resolver_stability_facts
            ),
            "admitted_relation_profile": (
                structure.global_composition_facts.admitted_relation_profile
            ),
        },
    }


def template_structure_digest(structure: ExecutionTemplateStructure) -> str:
    """v2 semantic payload 의 content-address.

    포함: schema version·product structure·occurrence/region/content-entry/relation fact·
    resolver/capability contract id·global composition fact. 제외: created_at·object 주소·
    store 경로·native handle·qualification attempt 실행 시간(payload 에 애초에 안 담긴다).
    """
    return content_digest(encode_execution_structure(structure))


def execution_pass_projection(structure: ExecutionTemplateStructure) -> StructureProjection:
    """v2 projection 을 PASS Evidence 에 durable 하게 실을 :class:`StructureProjection` 로 고정.

    기존 Evidence/store 기계를 그대로 재사용한다 — v1 payload 대신 v2 semantic payload 를 담고
    payload_digest 는 :func:`template_structure_digest` 와 같은 seam(content_digest)이다.
    """
    payload = encode_execution_structure(structure)
    return StructureProjection(
        EXECUTION_STRUCTURE_PROJECTION_SCHEMA, payload, content_digest(payload)
    )


# ─── composition-ready Qualification Profile ─────────────────────────────────────
_REQUIRED_MANIFEST_FIELDS = (
    "media",
    "adapter_contract_version",
    "product_rule_version",
    "operation_alphabet_version",
)


def build_execution_manifest(
    *,
    qualification_profile_id: str = EXECUTION_QUALIFICATION_PROFILE_ID,
    media: str,
    adapter_contract_version: str,
    product_rule_version: str,
    operation_alphabet_version: str,
    manifest_payload: Mapping[str, Any] | None = None,
    created_at: str,
):
    """composition-ready Profile 의 immutable manifest(projection_schema_version=v2 고정).

    필수 semantic contract 필드가 비어 있으면 latest 로 보완하지 않고 시끄럽게 거절한다.
    반환형은 :class:`~hwpxfiller.application.qualification_evidence.QualificationProfileManifest`.
    """
    values = {
        "media": media,
        "adapter_contract_version": adapter_contract_version,
        "product_rule_version": product_rule_version,
        "operation_alphabet_version": operation_alphabet_version,
    }
    for name in _REQUIRED_MANIFEST_FIELDS:
        if not isinstance(values[name], str) or not values[name]:
            raise QualificationProfileManifestIntegrityError(
                f"composition-ready manifest 는 {name!r} 가 비어 있을 수 없다"
            )
    if not qualification_profile_id:
        raise QualificationProfileManifestIntegrityError("qualification_profile_id 가 비어 있다")
    return build_manifest(
        qualification_profile_id=qualification_profile_id,
        media=media,
        adapter_contract_version=adapter_contract_version,
        product_rule_version=product_rule_version,
        operation_alphabet_version=operation_alphabet_version,
        projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        manifest_payload=dict(manifest_payload or {}),
        created_at=created_at,
    )


@dataclass(frozen=True)
class SealedExecutionProfile:
    """S5 seal 을 통과한 composition-ready (profile, v2 projection) 쌍.

    admission 을 함의하지 않는다 — admission state(S5-08)를 담지 않는다. publication·seal 만으로
    ADMITTED 가 되지 않는다는 계약을 이 타입의 부재로 강제한다(admission 속성 없음).
    """

    qualification_profile_id: str
    projection_schema_version: str
    template_structure_digest: str


def seal_execution_profile(manifest, projection: StructureProjection) -> SealedExecutionProfile:
    """v2 profile+projection 만 S5-seal 가능. v1 이면 EXECUTION_PROFILE_NOT_SEALABLE.

    ``manifest`` 는 QualificationProfileManifest. old profile+v1 이 이 경로로 들어오면 historical
    evidence 는 그대로 두고 새 seal 만 거절한다(재해석·수정 없음).
    """
    if manifest.projection_schema_version != EXECUTION_STRUCTURE_PROJECTION_SCHEMA:
        raise ExecutionProfileNotSealable(
            f"profile projection schema 가 v2 가 아니다: {manifest.projection_schema_version}"
        )
    if projection.projection_schema_version != EXECUTION_STRUCTURE_PROJECTION_SCHEMA:
        raise ExecutionProfileNotSealable(
            f"projection schema 가 v2 가 아니다: {projection.projection_schema_version}"
        )
    return SealedExecutionProfile(
        qualification_profile_id=manifest.qualification_profile_id,
        projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        template_structure_digest=projection.payload_digest,
    )
