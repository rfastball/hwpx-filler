"""S5-03(#699) composition-ready Structure Projection v2 + additive Profile.

체크리스트: schema/determinism · relation fixtures · envelope/resolver · additive compat.
모든 fact 는 hand-authored native-free 관찰값으로 세운다(실 HWPX parse 없음 — 이 slice 는
projection·DTO·digest·profile·decoder 를 소유하고 native producer 는 downstream 이 잇는다).
"""

from __future__ import annotations

import json

import pytest

from hwpxfiller.application.execution_structure import (
    CONTAINED,
    CONTAINS,
    CROSSING,
    DISJOINT,
    EXECUTION_QUALIFICATION_PROFILE_ID,
    EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
    SAME_SPAN,
    TOUCHING,
    ContentEntry,
    ExecutionProfileNotSealable,
    ExecutionStructureEnvelopeFactMissing,
    ExecutionStructureOccurrenceIncomplete,
    ExecutionStructureProjectionIntegrityError,
    ExecutionStructureRelationIncomplete,
    ExecutionStructureResolverFactMissing,
    FieldOccurrence,
    OptionRegionObservation,
    QualificationProfileManifestIntegrityError,
    SlotRegionObservation,
    UnsupportedExecutionStructureProjection,
    build_execution_manifest,
    build_execution_structure,
    classify_span_relation,
    encode_execution_structure,
    execution_pass_projection,
    seal_execution_profile,
    template_structure_digest,
)
from hwpxfiller.application.qualification_evidence import (
    StructureProjection,
    content_digest,
    project_structure,
)
from hwpxfiller.application.slot_configuration_context import (
    DEFAULT_STRUCTURE_DECODER_REGISTRY,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.domain.slot_selection import (
    DEFAULT_SELECTION_SEMANTIC_REGISTRY,
    SelectionSemanticBindingKey,
)

# ── 공용 fixture 재료 ──────────────────────────────────────────────────────────────
VTC = "hwpx-field-value/v1"
RC = "hwpx-field-resolver/v1"
RESOLVER_FACTS = {
    "remaining_target_resolvable_after_removal": True,
    "active_field_resolvable_after_removal": True,
    "field_write_preserves_identity": True,
}


def _entry(entry_id: str) -> ContentEntry:
    return ContentEntry(
        content_entry_id=entry_id,
        envelope_class="section-body/v1",
        envelope_capability_facts={
            "retains_admissible_envelope": True,
            "handles_empty_edges": True,
            "preserves_owner_marker": True,
            "coincident_boundary_admissible": True,
        },
    )


def _occ(field_id, ordinal, kind, order, slot=None, option=None, entry="c0"):
    return FieldOccurrence(
        field_id=field_id,
        occurrence_ordinal=ordinal,
        owner_kind=kind,
        owner_slot_id=slot,
        owner_option_id=option,
        content_entry_id=entry,
        structural_order=order,
        native_value_target_class=VTC,
        resolver_contract_id=RC,
    )


def _base_structure():
    """root(반복 Field 포함)+shared+2 Option(disjoint) 표준 fixture."""
    product = TemplateStructure(
        root_fields=("성명",),
        slots=(
            TemplateSlot(
                id="s1",
                shared_fields=("주소",),
                options=(TemplateOption("o1", ("항목",)), TemplateOption("o2", ())),
            ),
        ),
    )
    return build_execution_structure(
        product_structure=product,
        occurrences=(
            _occ("성명", 0, "ROOT", 0),
            _occ("주소", 0, "SLOT_SHARED", 12, slot="s1"),
            _occ("항목", 0, "OPTION", 17, slot="s1", option="o1"),
            _occ("성명", 1, "ROOT", 50),
        ),
        slot_regions=(SlotRegionObservation("s1", "c0", 10, 40),),
        option_regions=(
            OptionRegionObservation("s1", "o1", "c0", 15, 20, "remove-option/v1"),
            OptionRegionObservation("s1", "o2", "c0", 25, 30, "remove-option/v1"),
        ),
        content_entries=(_entry("c0"),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )


def _two_option(a_span, b_span, slot_span=(0, 100)):
    """field 없는 2-Option fixture — span 관계만 본다."""
    product = TemplateStructure(
        slots=(
            TemplateSlot(
                id="s1",
                options=(TemplateOption("o1", ()), TemplateOption("o2", ())),
            ),
        ),
    )
    return build_execution_structure(
        product_structure=product,
        occurrences=(),
        slot_regions=(SlotRegionObservation("s1", "c0", *slot_span),),
        option_regions=(
            OptionRegionObservation("s1", "o1", "c0", a_span[0], a_span[1], "r"),
            OptionRegionObservation("s1", "o2", "c0", b_span[0], b_span[1], "r"),
        ),
        content_entries=(_entry("c0"),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )


def _relation(struct):
    rels = struct.removal_target_relations
    assert len(rels) == 1
    return rels[0].relation


# ── schema / determinism ──────────────────────────────────────────────────────────
def test_product_structure_v1_lossless() -> None:
    struct = _base_structure()
    # v2 product_structure 는 v1 project_structure payload 와 정확히 같은 shape·순서.
    v1_payload = project_structure(struct.product_structure, "hwpx-structure-projection-v1").payload
    v2_product = encode_execution_structure(struct)["product_structure"]
    assert v2_product == dict(v1_payload)


def test_repeated_field_occurrence_ordinal_and_order() -> None:
    struct = _base_structure()
    occ = [o for o in struct.field_occurrences if o.field_id == "성명"]
    assert [o.occurrence_ordinal for o in occ] == [0, 1]
    assert [o.structural_order for o in occ] == [0, 50]  # stable order 순


def test_single_owner_kind_per_occurrence() -> None:
    struct = _base_structure()
    for o in struct.field_occurrences:
        refs = (o.owner_slot_id is not None, o.owner_option_id is not None)
        assert o.owner_kind in {"ROOT", "SLOT_SHARED", "OPTION"}
        assert refs == {
            "ROOT": (False, False),
            "SLOT_SHARED": (True, False),
            "OPTION": (True, True),
        }[o.owner_kind]


def test_option_region_and_content_entry_exact_refs() -> None:
    struct = _base_structure()
    regions = {(r.slot_id, r.option_id): r for r in struct.option_regions}
    assert set(regions) == {("s1", "o1"), ("s1", "o2")}
    assert regions[("s1", "o1")].content_entry_id == "c0"
    assert regions[("s1", "o1")].begin_order == 15


def test_no_native_handle_path_or_object_identity() -> None:
    payload = encode_execution_structure(_base_structure())

    def leaves(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from leaves(v)
        elif isinstance(node, list):
            for v in node:
                yield from leaves(v)
        else:
            yield node

    for leaf in leaves(payload):
        assert isinstance(leaf, (str, int, bool)) or leaf is None
    # JSON round-trip 가능 = 어떤 native/mutable object 도 안 실렸다는 증거.
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


def test_same_input_deterministic_payload() -> None:
    a = _base_structure()
    # 같은 관찰값을 occurrence 순서만 뒤집어 다시 조립.
    product = a.product_structure
    b = build_execution_structure(
        product_structure=product,
        occurrences=(
            _occ("성명", 1, "ROOT", 50),
            _occ("항목", 0, "OPTION", 17, slot="s1", option="o1"),
            _occ("주소", 0, "SLOT_SHARED", 12, slot="s1"),
            _occ("성명", 0, "ROOT", 0),
        ),
        slot_regions=(SlotRegionObservation("s1", "c0", 10, 40),),
        option_regions=(
            OptionRegionObservation("s1", "o2", "c0", 25, 30, "remove-option/v1"),
            OptionRegionObservation("s1", "o1", "c0", 15, 20, "remove-option/v1"),
        ),
        content_entries=(_entry("c0"),),
        resolver_stability_facts=dict(RESOLVER_FACTS),
        admitted_relation_profile="unadmitted",
    )
    assert template_structure_digest(a) == template_structure_digest(b)
    assert encode_execution_structure(a) == encode_execution_structure(b)


def test_unknown_schema_no_latest_fallback() -> None:
    with pytest.raises(UnsupportedExecutionStructureProjection):
        build_execution_structure(
            product_structure=TemplateStructure(),
            occurrences=(),
            slot_regions=(),
            option_regions=(),
            content_entries=(),
            resolver_stability_facts=RESOLVER_FACTS,
            admitted_relation_profile="unadmitted",
            projection_schema_version="hwpx-structure-projection-v99",
        )


# ── relation fixtures (target-target) ──────────────────────────────────────────────
def test_distinct_option_disjoint() -> None:
    assert _relation(_two_option((10, 20), (30, 40))) == DISJOINT


def test_distinct_option_touching() -> None:
    assert _relation(_two_option((10, 20), (20, 40))) == TOUCHING


def test_distinct_option_contains() -> None:
    # o1(left) [10,40] 이 o2 [15,30] 을 담는다 → left 관점 CONTAINS.
    assert _relation(_two_option((10, 40), (15, 30))) == CONTAINS


def test_distinct_option_contained() -> None:
    assert _relation(_two_option((15, 30), (10, 40))) == CONTAINED


def test_distinct_same_span() -> None:
    assert _relation(_two_option((10, 40), (10, 40))) == SAME_SPAN


def test_crossing_makes_not_crossing_free() -> None:
    struct = _two_option((10, 30), (20, 40))
    assert _relation(struct) == CROSSING
    assert struct.global_composition_facts.crossing_free is False


def test_disjoint_is_crossing_free() -> None:
    assert _two_option((10, 20), (30, 40)).global_composition_facts.crossing_free is True


# ── relation fixtures (target-owner) ───────────────────────────────────────────────
def _owner_coincidence(struct, option_id):
    region = next(r for r in struct.option_regions if r.option_id == option_id)
    slot_fact = next(
        f for f in region.owner_relation_facts if f["relation"] == "target_owner_slot"
    )
    return slot_fact["coincidence"]


def test_owner_target_same_start() -> None:
    struct = _two_option((0, 30), (40, 60), slot_span=(0, 100))
    assert _owner_coincidence(struct, "o1") == "SAME_START"


def test_owner_target_same_end() -> None:
    struct = _two_option((10, 30), (40, 100), slot_span=(0, 100))
    assert _owner_coincidence(struct, "o2") == "SAME_END"


def test_owner_target_same_span() -> None:
    struct = _two_option((0, 100), (0, 100), slot_span=(0, 100))
    assert _owner_coincidence(struct, "o1") == "SAME_SPAN"


def test_owner_relation_carries_content_entry() -> None:
    region = _base_structure().option_regions[0]
    entry_fact = next(
        f for f in region.owner_relation_facts if f["relation"] == "target_owner_content_entry"
    )
    assert entry_fact["content_entry_id"] == "c0"


# ── relation fixtures (target-retained) ────────────────────────────────────────────
def test_root_shared_selected_retained_relation_facts() -> None:
    region = next(r for r in _base_structure().option_regions if r.option_id == "o1")
    positions = {
        (f["field_id"], f["occurrence_ordinal"]): f["position"]
        for f in region.retained_content_relation_facts
    }
    # o1 region [15,20]: 성명occ0(0)·주소occ0(12) 앞, 성명occ1(50) 뒤. 항목(자기 소유)은 제외.
    assert positions == {
        ("성명", 0): "BEFORE",
        ("주소", 0): "BEFORE",
        ("성명", 1): "AFTER",
    }
    assert ("항목", 0) not in positions


def test_retained_taxonomy_separate_from_target_target() -> None:
    region = _base_structure().option_regions[0]
    # owner/retained fact 는 target-target relation 과 섞이지 않는다(별 collection).
    for f in region.owner_relation_facts:
        assert f["relation"].startswith("target_owner_")
    for f in region.retained_content_relation_facts:
        assert "position" in f and "relation" not in f


def test_multiple_slots_in_same_content_entry() -> None:
    product = TemplateStructure(
        slots=(
            TemplateSlot("s1", options=(TemplateOption("o1", ()),)),
            TemplateSlot("s2", options=(TemplateOption("o1", ()),)),
        )
    )
    struct = build_execution_structure(
        product_structure=product,
        occurrences=(),
        slot_regions=(
            SlotRegionObservation("s1", "c0", 0, 20),
            SlotRegionObservation("s2", "c0", 30, 50),
        ),
        option_regions=(
            OptionRegionObservation("s1", "o1", "c0", 5, 10, "r"),
            OptionRegionObservation("s2", "o1", "c0", 35, 40, "r"),
        ),
        content_entries=(_entry("c0"),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )
    # 같은 content entry 안 두 Slot 의 Option target 은 서로 disjoint 로 분류된다.
    assert {r.content_entry_id for r in struct.option_regions} == {"c0"}
    assert _relation(struct) == DISJOINT


# ── envelope / resolver ────────────────────────────────────────────────────────────
def test_content_entry_of_options_only() -> None:
    # occurrence 가 하나도 없는(Option 만 있는) content entry 도 조립된다.
    struct = _two_option((10, 20), (30, 40))
    assert struct.field_occurrences == ()
    assert struct.content_entries[0].content_entry_id == "c0"


def test_selected_option_region_can_be_empty() -> None:
    struct = _base_structure()
    o2 = next(r for r in struct.option_regions if r.option_id == "o2")
    # o2 는 field 가 없다 — region 은 있지만 안에 occurrence 가 없다.
    assert o2.begin_order == 25 and o2.end_order == 30
    inside = [f for f in o2.retained_content_relation_facts if f["position"] == "INSIDE"]
    assert inside == []


def test_empty_envelope_capability_fact_missing() -> None:
    bad = ContentEntry("c0", "section-body/v1", {"handles_empty_edges": True})
    with pytest.raises(ExecutionStructureEnvelopeFactMissing):
        _two_option_with_entry(bad)


def _two_option_with_entry(entry: ContentEntry):
    product = TemplateStructure(slots=(TemplateSlot("s1", options=(TemplateOption("o1", ()),)),))
    return build_execution_structure(
        product_structure=product,
        occurrences=(),
        slot_regions=(SlotRegionObservation("s1", entry.content_entry_id, 0, 20),),
        option_regions=(
            OptionRegionObservation("s1", "o1", entry.content_entry_id, 5, 10, "r"),
        ),
        content_entries=(entry,),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )


def test_remove_option_remaining_resolver_fact_carried() -> None:
    facts = _base_structure().global_composition_facts.resolver_stability_facts
    assert facts["remaining_target_resolvable_after_removal"] is True


def test_remove_option_active_field_resolver_fact_carried() -> None:
    facts = _base_structure().global_composition_facts.resolver_stability_facts
    assert facts["active_field_resolvable_after_removal"] is True


def test_repeated_field_fill_stability_fact() -> None:
    struct = _base_structure()
    assert struct.global_composition_facts.resolver_stability_facts[
        "field_write_preserves_identity"
    ] is True
    # 반복 Field 두 occurrence 가 서로 다른 value target class/ resolver contract 에 결속.
    for o in struct.field_occurrences:
        assert o.native_value_target_class == VTC
        assert o.resolver_contract_id == RC


def test_missing_resolver_stability_fact_is_error() -> None:
    with pytest.raises(ExecutionStructureResolverFactMissing):
        build_execution_structure(
            product_structure=TemplateStructure(),
            occurrences=(),
            slot_regions=(),
            option_regions=(),
            content_entries=(),
            resolver_stability_facts={"field_write_preserves_identity": True},
            admitted_relation_profile="unadmitted",
        )


# ── integrity: 정상 pair/occurrence 인데 fact 누락·중복 → attempt/context error ────────
def test_missing_occurrence_is_incomplete_not_fail() -> None:
    product = TemplateStructure(root_fields=("성명",))
    with pytest.raises(ExecutionStructureOccurrenceIncomplete):
        build_execution_structure(
            product_structure=product,
            occurrences=(),  # 성명 occurrence 부재
            slot_regions=(),
            option_regions=(),
            content_entries=(),
            resolver_stability_facts=RESOLVER_FACTS,
            admitted_relation_profile="unadmitted",
        )


def test_duplicate_ordinal_is_integrity_error() -> None:
    product = TemplateStructure(root_fields=("성명",))
    with pytest.raises(ExecutionStructureProjectionIntegrityError):
        build_execution_structure(
            product_structure=product,
            occurrences=(_occ("성명", 0, "ROOT", 0), _occ("성명", 0, "ROOT", 1)),
            slot_regions=(),
            option_regions=(),
            content_entries=(_entry("c0"),),
            resolver_stability_facts=RESOLVER_FACTS,
            admitted_relation_profile="unadmitted",
        )


def test_ordinal_gap_is_incomplete() -> None:
    product = TemplateStructure(root_fields=("성명",))
    with pytest.raises(ExecutionStructureOccurrenceIncomplete):
        build_execution_structure(
            product_structure=product,
            occurrences=(_occ("성명", 0, "ROOT", 0), _occ("성명", 2, "ROOT", 1)),
            slot_regions=(),
            option_regions=(),
            content_entries=(_entry("c0"),),
            resolver_stability_facts=RESOLVER_FACTS,
            admitted_relation_profile="unadmitted",
        )


def test_option_outside_slot_span_is_integrity_error() -> None:
    with pytest.raises(ExecutionStructureProjectionIntegrityError):
        _two_option((5, 30), (40, 60), slot_span=(10, 50))  # o1 begin 5 < slot 10


def test_missing_option_region_is_relation_incomplete() -> None:
    product = TemplateStructure(
        slots=(TemplateSlot("s1", options=(TemplateOption("o1", ()), TemplateOption("o2", ()))),)
    )
    with pytest.raises(ExecutionStructureRelationIncomplete):
        build_execution_structure(
            product_structure=product,
            occurrences=(),
            slot_regions=(SlotRegionObservation("s1", "c0", 0, 100),),
            option_regions=(OptionRegionObservation("s1", "o1", "c0", 5, 10, "r"),),
            content_entries=(_entry("c0"),),
            resolver_stability_facts=RESOLVER_FACTS,
            admitted_relation_profile="unadmitted",
        )


def test_undeclared_content_entry_is_envelope_error() -> None:
    product = TemplateStructure(root_fields=("성명",))
    with pytest.raises(ExecutionStructureEnvelopeFactMissing):
        build_execution_structure(
            product_structure=product,
            occurrences=(_occ("성명", 0, "ROOT", 0, entry="ghost"),),
            slot_regions=(),
            option_regions=(),
            content_entries=(_entry("c0"),),
            resolver_stability_facts=RESOLVER_FACTS,
            admitted_relation_profile="unadmitted",
        )


def test_occurrence_owner_mismatch_is_integrity_error() -> None:
    product = TemplateStructure(root_fields=("성명",))
    with pytest.raises(ExecutionStructureProjectionIntegrityError):
        build_execution_structure(
            product_structure=product,
            occurrences=(_occ("성명", 0, "ROOT", 0, slot="s1"),),  # ROOT 인데 slot ref
            slot_regions=(),
            option_regions=(),
            content_entries=(_entry("c0"),),
            resolver_stability_facts=RESOLVER_FACTS,
            admitted_relation_profile="unadmitted",
        )


def test_classify_span_relation_direct() -> None:
    assert classify_span_relation((0, 10), (0, 10)) == SAME_SPAN
    assert classify_span_relation((0, 10), (20, 30)) == DISJOINT
    assert classify_span_relation((0, 10), (10, 20)) == TOUCHING
    assert classify_span_relation((0, 30), (10, 20)) == CONTAINS
    assert classify_span_relation((10, 20), (0, 30)) == CONTAINED
    assert classify_span_relation((0, 20), (10, 30)) == CROSSING


# ── additive compatibility ─────────────────────────────────────────────────────────
def test_projection_v1_bytes_and_evidence_unchanged() -> None:
    struct = TemplateStructure(root_fields=("성명",), slots=())
    v1 = project_structure(struct, "hwpx-structure-projection-v1")
    # v1 payload 는 v2 키를 얻지 않는다(무변경).
    assert set(v1.payload) == {"root_fields", "slots"}
    assert "product_structure" not in v1.payload
    assert v1.payload_digest == content_digest(v1.payload)
    # v1 selection binding 도 그대로 slot-selection/v1.
    v1_key = SelectionSemanticBindingKey(
        "hwpx-template-qualification-v1", "hwpx-structure-projection-v1"
    )
    assert DEFAULT_SELECTION_SEMANTIC_REGISTRY.resolve(v1_key).contract_id == "slot-selection/v1"


def test_new_profile_emits_v2() -> None:
    manifest = build_execution_manifest(
        media="hwpx",
        adapter_contract_version="hwpx-inspection-v2",
        product_rule_version="hwpx-qualification-rules-v2",
        operation_alphabet_version="hwpx-operations-v2",
        created_at="2026-08-16T00:00:00Z",
    )
    assert manifest.projection_schema_version == EXECUTION_STRUCTURE_PROJECTION_SCHEMA
    assert manifest.qualification_profile_id == EXECUTION_QUALIFICATION_PROFILE_ID


def test_s4_decoder_reads_product_structure_from_v2() -> None:
    struct = _base_structure()
    projection = execution_pass_projection(struct)
    decoder = DEFAULT_STRUCTURE_DECODER_REGISTRY.resolve(EXECUTION_STRUCTURE_PROJECTION_SCHEMA)
    assert decoder(projection.payload) == struct.product_structure


def test_v2_decoder_rejects_missing_product_structure() -> None:
    from hwpxfiller.application.slot_configuration_context import (
        TemplateStructureIntegrityError,
    )

    decoder = DEFAULT_STRUCTURE_DECODER_REGISTRY.resolve(EXECUTION_STRUCTURE_PROJECTION_SCHEMA)
    with pytest.raises(TemplateStructureIntegrityError):
        decoder({"field_occurrences": []})


def test_new_profile_v2_binding_returns_slot_selection_v1() -> None:
    key = SelectionSemanticBindingKey(
        EXECUTION_QUALIFICATION_PROFILE_ID, EXECUTION_STRUCTURE_PROJECTION_SCHEMA
    )
    assert DEFAULT_SELECTION_SEMANTIC_REGISTRY.resolve(key).contract_id == "slot-selection/v1"
    # unknown pair 는 latest 로 풀리지 않는다.
    from hwpxfiller.domain.slot_selection import (
        UnsupportedSelectionSemanticContractError,
    )

    with pytest.raises(UnsupportedSelectionSemanticContractError):
        DEFAULT_SELECTION_SEMANTIC_REGISTRY.resolve(
            SelectionSemanticBindingKey("ghost", EXECUTION_STRUCTURE_PROJECTION_SCHEMA)
        )


def test_v2_binding_reuses_v1_manifest_identity() -> None:
    v1_key = SelectionSemanticBindingKey(
        "hwpx-template-qualification-v1", "hwpx-structure-projection-v1"
    )
    v2_key = SelectionSemanticBindingKey(
        EXECUTION_QUALIFICATION_PROFILE_ID, EXECUTION_STRUCTURE_PROJECTION_SCHEMA
    )
    # 같은 slot-selection/v1 semantic — S4 selection 의미를 그대로 재사용.
    assert DEFAULT_SELECTION_SEMANTIC_REGISTRY.resolve(
        v1_key
    ) == DEFAULT_SELECTION_SEMANTIC_REGISTRY.resolve(v2_key)


def test_new_profile_admission_state_not_auto_created() -> None:
    manifest = build_execution_manifest(
        media="hwpx",
        adapter_contract_version="a",
        product_rule_version="p",
        operation_alphabet_version="o",
        created_at="t",
    )
    sealed = seal_execution_profile(manifest, execution_pass_projection(_base_structure()))
    # publication·seal 만으로 admission 되지 않는다 — admission state 를 담지 않는다.
    assert not hasattr(sealed, "admission")
    assert not hasattr(sealed, "admitted")


# ── seal / manifest integrity ──────────────────────────────────────────────────────
def test_old_profile_v1_is_not_sealable() -> None:
    from hwpxfiller.application.execution_structure import build_execution_manifest  # noqa: F401
    from hwpxfiller.application.qualification_evidence import build_manifest

    v1_manifest = build_manifest(
        qualification_profile_id="hwpx-template-qualification-v1",
        media="hwpx",
        adapter_contract_version="hwpx-inspection-v1",
        product_rule_version="hwpx-qualification-rules-v1",
        operation_alphabet_version="hwpx-operations-v1",
        projection_schema_version="hwpx-structure-projection-v1",
        manifest_payload={},
        created_at="t",
    )
    v2_projection = execution_pass_projection(_base_structure())
    with pytest.raises(ExecutionProfileNotSealable):
        seal_execution_profile(v1_manifest, v2_projection)


def test_v2_manifest_with_v1_projection_not_sealable() -> None:
    manifest = build_execution_manifest(
        media="hwpx",
        adapter_contract_version="a",
        product_rule_version="p",
        operation_alphabet_version="o",
        created_at="t",
    )
    v1_projection = StructureProjection(
        "hwpx-structure-projection-v1", {"x": 1}, content_digest({"x": 1})
    )
    with pytest.raises(ExecutionProfileNotSealable):
        seal_execution_profile(manifest, v1_projection)


def test_seal_v2_pair_succeeds() -> None:
    manifest = build_execution_manifest(
        media="hwpx",
        adapter_contract_version="a",
        product_rule_version="p",
        operation_alphabet_version="o",
        created_at="t",
    )
    struct = _base_structure()
    projection = execution_pass_projection(struct)
    sealed = seal_execution_profile(manifest, projection)
    assert sealed.qualification_profile_id == EXECUTION_QUALIFICATION_PROFILE_ID
    assert sealed.template_structure_digest == template_structure_digest(struct)
    assert sealed.projection_schema_version == EXECUTION_STRUCTURE_PROJECTION_SCHEMA


def test_manifest_integrity_rejects_empty_field() -> None:
    with pytest.raises(QualificationProfileManifestIntegrityError):
        build_execution_manifest(
            media="",
            adapter_contract_version="a",
            product_rule_version="p",
            operation_alphabet_version="o",
            created_at="t",
        )


def test_execution_pass_projection_round_trips_digest() -> None:
    struct = _base_structure()
    projection = execution_pass_projection(struct)
    # PASS Evidence 에 실릴 StructureProjection 은 __post_init__ digest 검증을 통과한다.
    assert projection.projection_schema_version == EXECUTION_STRUCTURE_PROJECTION_SCHEMA
    assert projection.payload_digest == template_structure_digest(struct)
    assert StructureProjection(
        projection.projection_schema_version, projection.payload, projection.payload_digest
    ) == projection
