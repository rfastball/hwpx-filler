"""shipping Qualification → composition-ready PASS Evidence → S5 capture (SX-BLOCKER #773).

이 파일이 지는 것은 **경로 하나**다: 실 HWPX bytes 가 production Apply 를 지나 immutable
Evidence 가 되고, 그 Evidence 만으로 S5 가 current Active Field 와 Binding review 를 낸다.

그래서 여기서는 store 를 직접 seed 하지 않는다(`_seed_v2_work` 계열 0). Evidence 는 반드시
:class:`TemplateChangeCoordinator` 가 쓴 것이어야 하고, 그게 이 슬라이스의 요점이다 —
"테스트가 만들어 준 v2 Evidence" 로는 shipping 경로가 증명되지 않는다는 것이 #773 의 진단이었다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

import pytest

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.application.execution_compilation import project_active_fields
from hwpxfiller.application.execution_structure import (
    LABELED_EXECUTION_QUALIFICATION_PROFILE_ID,
    LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
    ExecutionStructureError,
    UnsupportedExecutionStructureProjection,
    decode_execution_structure,
    encode_execution_structure,
)
from hwpxfiller.application.qualification_evidence import (
    PASS,
    content_digest,
)
from hwpxfiller.domain.job import Job
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.qualification_store import QualificationObjectStore
from hwpxfiller.external.work_template_store import AtomicWorkTemplateStateStore
from hwpxfiller.webapp.seal_execution_plan_service import SealExecutionPlanService
from hwpxfiller.webapp.slot_configuration_product import SlotConfigurationProduct
from hwpxfiller.webapp.template_change import TemplateChangeCoordinator

_NOW = datetime(2026, 8, 22, 9, 0, 0)
_HS = "http://www.hancom.co.kr/hwpml/2011/section"
_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_SECTION = "Contents/section0.xml"

SLOT_ID = "s-notice"
OPTION_A = "o-price"
OPTION_B = "o-contact"
FIELD_ROOT = "공고명"
FIELD_A = "추정가격"
FIELD_B = "담당자"


def _clock():
    current = _NOW

    def tick():
        nonlocal current
        value = current
        current += timedelta(seconds=1)
        return value

    return tick


def _metatag(kind: str, identifier: str, label: str) -> str:
    return json.dumps(
        {"hwpxFiller": {"kind": kind, "id": identifier, "label": label}, "name": "#hf"},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _p(content: str) -> str:
    return f"<hp:p><hp:run>{content}</hp:run></hp:p>"


def _bookmark_begin(identifier: str, metatag: str) -> str:
    """product metatag 는 BOOKMARK fieldBegin 의 자식 ``hp:metaTag`` 로 실린다(name 속성 아님)."""
    return (
        f'<hp:ctrl><hp:fieldBegin id="{identifier}" type="BOOKMARK" name="bm{identifier}">'
        f"<hp:metaTag>{escape(metatag)}</hp:metaTag>"
        "</hp:fieldBegin></hp:ctrl>"
    )


def _bookmark_end(identifier: str) -> str:
    return f'<hp:ctrl><hp:fieldEnd beginIDRef="{identifier}"/></hp:ctrl>'


def _field(name: str) -> str:
    return (
        f'<hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl>'
        f"<hp:t>{{{{{name}}}}}</hp:t>"
        "<hp:ctrl><hp:fieldEnd/></hp:ctrl>"
    )


def _slotted_events(*, successor: bool = False) -> str:
    """root Field 하나 + Option 둘이 **서로 다른 Field** 를 갖는 Slot 하나.

    Option A/B 의 Field 가 달라야 A↔B 전환이 Active Field 를 실제로 움직인다 — 이게 H3 의
    구조적 전제다. successor 는 Option B 를 걷어내 reconciliation 을 만든다.
    """
    body = _p(_field(FIELD_ROOT)) + _p(
        _bookmark_begin("1", _metatag("slot", SLOT_ID, "공고 상세"))
        + "<hp:t>S</hp:t>"
    )
    body += _p(
        _bookmark_begin("2", _metatag("slot_option", OPTION_A, "추정가격 표시"))
        + "<hp:t>A</hp:t>"
    )
    body += _p(_field(FIELD_A))
    body += _p("<hp:t>AE</hp:t>" + _bookmark_end("2"))
    if not successor:
        body += _p(
            _bookmark_begin("3", _metatag("slot_option", OPTION_B, "담당자 표시"))
            + "<hp:t>B</hp:t>"
        )
        body += _p(_field(FIELD_B))
        body += _p("<hp:t>BE</hp:t>" + _bookmark_end("3"))
    body += _p("<hp:t>SE</hp:t>" + _bookmark_end("1"))
    return body


def _write_slotted_template(path, *, successor: bool = False) -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<hs:sec xmlns:hs="{_HS}" xmlns:hp="{_HP}">'
        + _slotted_events(successor=successor)
        + "</hs:sec>"
    ).encode()
    write_hwpx_package(
        path,
        HwpxPackage(
            entries={MIMETYPE_NAME: MIMETYPE_VALUE, _SECTION: xml},
            stored={MIMETYPE_NAME},
        ),
    )


@pytest.fixture
def product(tmp_path):
    """production Apply 로 세운 Work + 그 위의 실제 Product 서비스 둘(S4 · S5).

    같은 authority root 를 공유한다 — 앱이 그렇게 붙인다(`webapp/app.py`).
    """
    template = tmp_path / "공고서.hwpx"
    _write_slotted_template(template)
    registry = JobRegistry(tmp_path / "jobs")
    registry.save(Job(name="공고서", template_path=str(template)))
    root = tmp_path / "authority"
    assert (
        TemplateChangeCoordinator(registry, root=root, clock=_clock()).check("공고서", "k1")[
            "preparation"
        ]["status"]
        == "no_change"
    )
    return (
        SlotConfigurationProduct(registry, root=root, clock=_clock()),
        SealExecutionPlanService(registry, root=root, clock=_clock()),
    )


@pytest.fixture
def applied(tmp_path):
    """production Apply 만으로 세운 Work — store 직접 seed 0.

    반환: (authority root, work_id, evidence). Evidence 는 coordinator 가 쓴 그것을 **되읽은**
    값이다(우리가 만든 게 아니라 저장된 것을 본다).
    """
    template = tmp_path / "공고서.hwpx"
    _write_slotted_template(template)
    registry = JobRegistry(tmp_path / "jobs")
    registry.save(Job(name="공고서", template_path=str(template)))
    root = tmp_path / "authority"
    coordinator = TemplateChangeCoordinator(registry, root=root, clock=_clock())

    prepared = coordinator.check("공고서", "k1")
    assert prepared["preparation"]["status"] == "no_change"

    work_id = registry.load("공고서").authority_id
    assert work_id
    aggregate = AtomicWorkTemplateStateStore(root / "works").load(work_id)
    application = next(
        app
        for app in aggregate.applications
        if app.application_id == aggregate.work.current_template_application_id
    )
    evidence = QualificationObjectStore(root / "qualification").get_evidence(
        application.pass_evidence_id
    )
    return root, work_id, evidence


# ─── 발행: shipping Apply 가 실제로 composition-ready Evidence 를 쓴다 ──────────────────


def test_shipping_apply_emits_labeled_composition_evidence(applied) -> None:
    _, _, evidence = applied

    assert evidence.result == PASS
    assert evidence.qualification_profile_id == LABELED_EXECUTION_QUALIFICATION_PROFILE_ID
    projection = evidence.structure_projection
    assert projection is not None
    assert (
        projection.projection_schema_version
        == LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA
    )
    # digest 는 payload 의 content address 다 — 저장된 값이 payload 와 정합해야 한다.
    assert projection.payload_digest == content_digest(projection.payload)

    # composition fact 가 실제로 들어 있다(schema 문자열만 붙은 게 아니다).
    structure = decode_execution_structure(projection.payload)
    assert {occ.field_id for occ in structure.field_occurrences} == {
        FIELD_ROOT,
        FIELD_A,
        FIELD_B,
    }
    assert {(r.slot_id, r.option_id) for r in structure.option_regions} == {
        (SLOT_ID, OPTION_A),
        (SLOT_ID, OPTION_B),
    }
    assert structure.content_entries and structure.global_composition_facts.crossing_free

    # S4 가 보는 canonical label 과 opaque identity 가 같은 payload 안에 산다.
    slot = structure.product_structure.slots[0]
    assert (slot.id, slot.label) == (SLOT_ID, "공고 상세")
    assert [(o.id, o.label) for o in slot.options] == [
        (OPTION_A, "추정가격 표시"),
        (OPTION_B, "담당자 표시"),
    ]


def test_same_candidate_bytes_produce_identical_payload(tmp_path) -> None:
    """같은 bytes → 같은 payload·digest(결정적). order model 이 실행마다 흔들리지 않는다."""
    from hwpxfiller.external.template_inspection import inspect_hwpx_qualification

    template = tmp_path / "t.hwpx"
    _write_slotted_template(template)
    blob = template.read_bytes()

    first = inspect_hwpx_qualification(blob).execution_structure
    second = inspect_hwpx_qualification(blob).execution_structure
    assert first is not None and second is not None
    assert encode_execution_structure(first) == encode_execution_structure(second)
    assert content_digest(encode_execution_structure(first)) == content_digest(
        encode_execution_structure(second)
    )


# ─── 소비: Option A↔B 가 backend-owned Active Field 를 실제로 바꾼다 ────────────────────


def test_option_switch_changes_active_fields_from_shipping_evidence(applied) -> None:
    """H3 의 엔진 사실 — 같은 Evidence, 다른 selection, 다른 Active Field 집합."""
    _, _, evidence = applied
    projection = evidence.structure_projection
    assert projection is not None
    structure = decode_execution_structure(projection.payload)

    active_a, _ = project_active_fields(structure, frozenset({(SLOT_ID, OPTION_A)}))
    active_b, _ = project_active_fields(structure, frozenset({(SLOT_ID, OPTION_B)}))

    assert active_a.active_logical_field_order == (FIELD_ROOT, FIELD_A)
    assert active_b.active_logical_field_order == (FIELD_ROOT, FIELD_B)
    assert active_a.active_logical_field_order != active_b.active_logical_field_order


def test_no_selection_activates_no_option_field(applied) -> None:
    """선택 0 이면 Option Field 는 하나도 active 가 아니다(자동 선택 없음)."""
    _, _, evidence = applied
    projection = evidence.structure_projection
    assert projection is not None
    structure = decode_execution_structure(projection.payload)

    active, _ = project_active_fields(structure, frozenset())
    assert active.active_logical_field_order == (FIELD_ROOT,)


def test_production_option_command_moves_backend_owned_binding_review(product) -> None:
    """#773 완료조건 6~9 — 제품 S4 command 로 A↔B 를 바꾸면 S5 Binding review 가 따라 움직인다.

    fixture seed 없이 production Apply 가 쓴 Evidence 만으로 `current_binding_review()` 가
    성공해야 하고(예전엔 여기서 `UnsupportedExecutionStructureProjection` 로 넘어졌다),
    Active Field 는 backend 가 낸 값이어야 한다 — 프런트 추론 0.
    """
    slots, seal = product

    opened = slots.open_slot_configuration("공고서")
    token = opened.current_view.new_configuration_token
    projection = opened.current_view.projection
    assert projection is not None
    # 마운트 직후 선택 0 — Option 이 있어도 자동 선택하지 않는다.
    assert all(not option.selected for slot in projection.slots for option in slot.options)
    # 선택이 덜 끝난 동안에는 Binding review 를 **추측해서 내지 않는다**(None, 빈 목록 아님).
    assert seal.current_binding_review("공고서") is None

    chosen_a = slots.select_slot_option("공고서", token, SLOT_ID, OPTION_A, "r1")
    review_a = seal.current_binding_review("공고서")
    assert review_a is not None
    assert set(review_a.active_field_ids) == {FIELD_ROOT, FIELD_A}

    chosen_b = slots.select_slot_option(
        "공고서", chosen_a.current_view.new_configuration_token, SLOT_ID, OPTION_B, "r2"
    )
    review_b = seal.current_binding_review("공고서")
    assert review_b is not None
    assert set(review_b.active_field_ids) == {FIELD_ROOT, FIELD_B}

    # 실제로 **달라졌다** — 이게 H3 가 요구하는 사실이고, #773 이전에는 여기까지 오지도 못했다.
    assert set(review_a.active_field_ids) != set(review_b.active_field_ids)
    # backend 가 낸 requirement 도 같은 basis 를 따른다(프런트가 조립하지 않는다).
    assert {item.field_id for item in review_b.input_requirements} == set(
        review_b.active_field_ids
    )
    # S4 는 여전히 opaque identity 를 낸다(label 은 표시용이지 선택 identity 가 아니다).
    slot_view = chosen_b.current_view.projection.slots[0]
    assert slot_view.slot_id == SLOT_ID
    assert [option.option_id for option in slot_view.options] == [OPTION_A, OPTION_B]
    assert slot_view.display_text == "공고 상세"


def test_shipping_structure_is_admissible_by_composition_premises(applied) -> None:
    """capture 만 고치고 admission 을 두면 반쪽이다 — 같은 v4 structure 가 premise 도 통과해야 한다.

    회귀 근거: 첫 구현은 `execution_composition.admit_composition_premises` 의 schema gate 를
    v2 상수로 둔 채 shipping 만 v4 로 올렸다. 그러면 S5 capture 는 살아나고 seal/compile 이
    `UNSUPPORTED_EXECUTION_STRUCTURE_PROJECTION` 로 영구 차단된다 — 내용은 멀쩡한데 schema
    문자열 하나 때문에.
    """
    from hwpxfiller.application.execution_composition import (
        NATIVE_PRIMITIVE_CONTRACT_V1,
        CompositionPremiseContextError,
        admit_composition_premises,
    )

    _, _, evidence = applied
    projection = evidence.structure_projection
    assert projection is not None
    structure = decode_execution_structure(projection.payload)

    result = admit_composition_premises(
        structure=structure,
        native_primitive_contract=NATIVE_PRIMITIVE_CONTRACT_V1,
        theorem_evidence_manifest_digest="d",
    )
    assert not isinstance(result, CompositionPremiseContextError), result


def test_seal_attests_the_schema_it_verified(applied) -> None:
    """seal 은 방금 검증한 pair 의 schema 를 적는다 — v4 payload 에 v2 라고 서명하지 않는다."""
    from hwpxfiller.application.execution_structure import (
        LABELED_EXECUTION_QUALIFICATION_PROFILE_ID as V4_PROFILE,
        build_execution_manifest,
        seal_execution_profile,
    )

    _, _, evidence = applied
    projection = evidence.structure_projection
    assert projection is not None
    manifest = build_execution_manifest(
        qualification_profile_id=V4_PROFILE,
        media="hwpx",
        adapter_contract_version="hwpx-inspection-v4",
        product_rule_version="hwpx-qualification-rules-v4",
        operation_alphabet_version="hwpx-operations-v1",
        created_at="2026-08-22T00:00:00",
    )
    sealed = seal_execution_profile(manifest, projection)
    assert sealed.qualification_profile_id == V4_PROFILE
    assert (
        sealed.projection_schema_version
        == LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA
    )


# ─── 거절: 부재·불일치는 조용히 빈 값이 되지 않는다 ──────────────────────────────────


def test_historical_v3_projection_is_refused_not_emptied() -> None:
    """historical v3-only Evidence 는 fail-loud 다 — 빈 Active Field 로 낮추지 않는다."""
    from hwpxfiller.application.qualification_evidence import project_structure
    from hwpxfiller.application.template_qualification import (
        TemplateOption,
        TemplateSlot,
        TemplateStructure,
    )

    v3 = project_structure(
        TemplateStructure(
            (FIELD_ROOT,),
            (
                TemplateSlot(
                    SLOT_ID,
                    (),
                    (TemplateOption(OPTION_A, (FIELD_A,), "추정가격 표시"),),
                    "공고 상세",
                ),
            ),
        ),
        "hwpx-structure-projection-v3",
    )
    with pytest.raises(UnsupportedExecutionStructureProjection):
        decode_execution_structure(v3.payload)


def test_unknown_future_schema_has_no_latest_fallback(applied) -> None:
    _, _, evidence = applied
    projection = evidence.structure_projection
    assert projection is not None
    payload = dict(projection.payload)
    payload["projection_schema_version"] = "hwpx-structure-projection-v99"
    with pytest.raises(UnsupportedExecutionStructureProjection):
        decode_execution_structure(payload)


@pytest.mark.parametrize(
    "section",
    [
        "field_occurrences",
        "option_regions",
        "removal_target_relations",
        "content_entries",
        "global_composition_facts",
    ],
)
def test_missing_composition_section_is_refused(applied, section: str) -> None:
    """composition fact 가 빠진 payload 는 빈 observation 이 아니라 오류다."""
    _, _, evidence = applied
    projection = evidence.structure_projection
    assert projection is not None
    payload = dict(projection.payload)
    del payload[section]
    with pytest.raises(ExecutionStructureError):
        decode_execution_structure(payload)


def test_v2_cannot_be_built_from_label_bearing_structure(applied) -> None:
    """생산 쪽 guard — label 있는 product structure 를 v2 로 조립하면 loud 거절이다.

    v2 encoder 는 label 을 안 싣는다(frozen). 막지 않으면 label 이 조용히 떨어진 채 digest 만
    맞는 반쪽 사실이 남는다.
    """
    from hwpxfiller.application.execution_structure import (
        EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        ExecutionStructureProjectionIntegrityError,
        build_execution_structure,
    )

    _, _, evidence = applied
    projection = evidence.structure_projection
    assert projection is not None
    labeled = decode_execution_structure(projection.payload)
    assert labeled.product_structure.slots[0].label == "공고 상세"

    with pytest.raises(ExecutionStructureProjectionIntegrityError):
        build_execution_structure(
            product_structure=labeled.product_structure,
            occurrences=labeled.field_occurrences,
            slot_regions=(),
            option_regions=(),
            content_entries=labeled.content_entries,
            resolver_stability_facts=dict(
                labeled.global_composition_facts.resolver_stability_facts
            ),
            admitted_relation_profile="unadmitted",
            projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        )


def test_relabeling_schema_breaks_the_evidence_digest(applied) -> None:
    """저장 경계 guard — payload 의 schema 를 갈아끼우면 content address 가 깨진다.

    schema 문자열은 payload 안에 있고 digest 가 그것까지 덮으므로, v4 Evidence 를 v2 인 척
    바꾼 payload 는 :class:`StructureProjection` 생성 시점에 거절된다.
    """
    from hwpxfiller.application.execution_structure import (
        EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
    )
    from hwpxfiller.application.qualification_evidence import (
        QualificationEvidenceError,
        StructureProjection,
    )

    _, _, evidence = applied
    projection = evidence.structure_projection
    assert projection is not None
    tampered = dict(projection.payload)
    tampered["projection_schema_version"] = EXECUTION_STRUCTURE_PROJECTION_SCHEMA

    with pytest.raises(QualificationEvidenceError):
        StructureProjection(
            EXECUTION_STRUCTURE_PROJECTION_SCHEMA, tampered, projection.payload_digest
        )
