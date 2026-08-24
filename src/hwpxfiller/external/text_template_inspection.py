"""TXT 템플릿 qualification inspector — HWPX 대칭물(S10-02 #859).

:mod:`~hwpxfiller.external.template_inspection` 의 ``inspect_hwpx_qualification`` 과 **같은
자리**를 TXT 매체에서 채운다: immutable Candidate bytes 하나를 읽어
:class:`~hwpxfiller.application.template_qualification.QualificationInspection` 을 낸다.
그래서 S2 Qualification·S3 Preparation/Application 기계는 한 줄도 바뀌지 않는다 —
:data:`TemplateInspectorPort` 는 이름에 매체가 없고 Candidate 캡처
(:class:`~hwpxfiller.external.template_source_reader.FileTemplateSourceReader`)도 zip 을
모른다. 새로 서는 것은 **자격 하나**뿐이다.

**structure XOR diagnostics.** 계약은 S2 가 진다(진단이 있으면 structure 는 없다). 이
inspector 가 지키는 것은 그 계약의 TXT 쪽 얼굴이다:

- UTF-8 로 못 읽으면 structure 없이 진단 1건(:data:`TXT_ENCODING_DIAGNOSTIC_KIND`)이다 —
  「읽을 수 없었다」를 빈 구조로 조용히 통과시키지 않는다. 읽기 인코딩은 작업대가 실제로
  쓰는 것과 같은 **엄격 UTF-8** 이다(:meth:`~hwpxfiller.webapp.screen_workbench.
  WorkbenchController.open`) — 여기서만 관대하면 확인은 통과하고 작업대는 터진다.
- 구간 표기 진단(:class:`~hwpxfiller.domain.structure_scan.StructureDiagnosticKind`)이
  하나라도 있으면 그 진단들을 그대로 옮기고 structure 는 내지 않는다. ``kind`` 는 코어의
  안정 식별자 문자열을 **그대로** 쓴다 — 여기서 다시 이름 지으면 같은 결함이 매체마다
  다른 이름으로 보고된다.

**execution structure 를 낸다(S10-04 · #861).** S10-02 에서는 ``None`` 이었다 — 물질화가 없으니
composition fact 를 낼 이유도 없었다. 이제 TXT materializer 가 서므로 이 inspector 가
composition-ready :class:`~hwpxfiller.application.execution_structure.ExecutionTemplateStructure`
를 함께 낸다. profile id·projection schema 이름은 **그대로**다(S10-03 의 selection binding key 와
structure decoder 가 그 이름에 걸려 있고, TXT 는 미출하라 되읽을 durable payload 가 없다).

좌표는 **문자 오프셋**이다 — 줄 번호가 아니다. ``structural_order`` 는 occurrence 마다 유일해야
하는데(:func:`~hwpxfiller.application.execution_structure.build_execution_structure` 가 강제)
한 줄에 토큰이 둘이면 줄 번호는 같은 값이 된다. 문자 오프셋은 문서 순서를 그대로 보존하면서
유일하고, 범위 span 도 같은 축에서 재므로 「occurrence 가 자기 region 안에 있는가」가 그대로
성립한다. 범위 span 은 **마커 줄을 포함**한다(여는 마커 줄의 첫 문자 … 닫는 마커 줄의 끝 문자) —
HWPX region 이 경계 문단을 포함하는 것과 같은 뜻이고, 그래서 서로 다른 Option 의 span 이
언제나 DISJOINT 다(마커 줄이 다르므로 오프셋 구간이 겹치지 않는다).

**필드 소유권은 줄 좌표에서 유도한다.** HWPX 는 문단 트리를 걸으며 열린 Slot/Option 범위를
문맥으로 들고 다니지만, TXT 에는 그 트리가 없다. 대신 스캐너가 이미 확정한 범위의 **내용 줄
좌표**(:class:`~hwpxfiller.domain.text_structure.TextStructurePlacement`)와 필드 토큰의 줄
위치를 대조한다 — 선택 범위 안이면 그 선택, 항목 범위 안이면 그 항목의 공유, 어느 항목 밖이면
root 다. 토큰은 **시작 줄**로 귀속한다(줄을 걸친 토큰도 한 소유자만 갖는다).

목록 안의 중복은 접는다(등장순 1회). HWPX 는 누름틀 **하나마다** 항목을 쌓지만 그쪽 항목은
각자 다른 native 컨트롤이고, TXT 의 ``{{공고명}}`` 두 번은 같은 필드를 두 번 그리는 것이다 —
그리고 TXT 의 「누름틀 k」를 세는 단일 출처
(:func:`~hwpxfiller.domain.text_render.template_fields`)가 이미 중복을 접는다. 한 매체 안에서
두 수가 갈리지 않는 쪽을 고른다.
"""

from __future__ import annotations

from bisect import bisect_right

from ..application.execution_composition import TXT_LINE_PRIMITIVE_CONTRACT_V1
from ..application.execution_structure import (
    OWNER_OPTION,
    OWNER_ROOT,
    OWNER_SLOT_SHARED,
    TXT_EXECUTION_QUALIFICATION_PROFILE_ID,
    TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
    ContentEntry,
    ExecutionTemplateStructure,
    FieldOccurrence,
    OptionRegionObservation,
    SlotRegionObservation,
    build_execution_structure,
)
from ..application.qualification_evidence import (
    QualificationProfileManifest,
    build_manifest,
)
from ..application.template_qualification import (
    QualificationInspection,
    QualificationProfile,
    TemplateDiagnostic,
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from ..domain.structure_scan import PLACEMENT_OPTION, PLACEMENT_SLOT
from ..domain.text_render import iter_field_token_matches
from ..domain.text_structure import scan_text_structure

#: 인코딩 진단의 안정 식별자 — 구간 표기 진단 어휘와 같은 snake_case 축에 선다.
TXT_ENCODING_DIAGNOSTIC_KIND = "txt_encoding"

#: TXT structure projection 의 schema identity. HWPX 이름을 재사용하지 않는다 — 좌표계도
#: 자격 규칙도 다른 구조를 같은 이름으로 부르면 저장된 projection 이 조용히 오독된다.
#: 정본은 :mod:`~hwpxfiller.application.execution_structure` 의 pair 표다(여기서 다시 쓰면
#: composition-ready 등록과 이 profile 이 따로 늙는다) — 이름은 그 상수를 그대로 잇는다.
TXT_STRUCTURE_PROJECTION_SCHEMA = TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA

#: 규칙·projection 이 바뀌면 profile id 와 manifest 버전 문자열을 함께 올린다(HWPX 동형).
TXT_QUALIFICATION_PROFILE_ID = TXT_EXECUTION_QUALIFICATION_PROFILE_ID

#: TXT 파일은 content entry 가 하나다(HWPX 의 section XML 여럿과 대비) — 그 하나의 이름.
TXT_CONTENT_ENTRY_ID = "text"

#: 그 entry 의 봉투 종류 — 「줄의 나열」. 문단 트리도 표도 없다.
TXT_LINE_SEQUENCE_ENVELOPE_CLASS = "txt-line-sequence"

#: Active Field 가 앉는 native 자리의 종류 — 줄 안의 ``{{필드}}`` 토큰 하나.
TXT_FIELD_TOKEN_TARGET_CLASS = "txt-line-token"

#: 이 projection 이 admit 하는 relation 프로파일 — 마커 줄이 서로 다르므로 Option span 은
#: 언제나 DISJOINT 다(겹침·접함이 구조적으로 불가능).
TXT_ADMITTED_RELATION_PROFILE = "txt-line-disjoint-removal/v1"


def _line_starts(text: str) -> "list[int]":
    """``text.splitlines()`` 와 **같은 분할**의 줄 시작 오프셋.

    스캐너가 ``splitlines()`` 인덱스로 좌표를 내므로 토큰 위치도 그 분할로 세야 한다 —
    ``\\n`` 만 세면 ``\\r``·``\\u2028`` 같은 경계에서 좌표가 어긋난다. ``keepends=True``
    조각의 길이 누적이 그 분할의 정의 그대로다.
    """
    starts: "list[int]" = []
    offset = 0
    for piece in text.splitlines(keepends=True):
        starts.append(offset)
        offset += len(piece)
    return starts


def _owner_at(
    line: int,
    slot_ranges: "list[tuple[int, int, str]]",
    option_ranges: "list[tuple[int, int, str, str]]",
) -> "tuple[str | None, str | None]":
    """줄 하나의 소유자 — (항목 id, 선택 id). 어느 항목 밖이면 (None, None)."""
    for start, end, slot_id, option_id in option_ranges:
        if start <= line <= end:
            return slot_id, option_id
    for start, end, slot_id in slot_ranges:
        if start <= line <= end:
            return slot_id, None
    return None, None


def _structure_from_text(text: str, scan) -> TemplateStructure:
    """진단 0 인 스캔 결과에 필드 소유권을 붙여 제품 구조를 세운다."""
    slot_ranges = [
        (p.content_start, p.content_end, p.slot_id)
        for p in scan.placements
        if p.kind == PLACEMENT_SLOT
    ]
    option_ranges = [
        (p.content_start, p.content_end, p.slot_id, str(p.option_id))
        for p in scan.placements
        if p.kind == PLACEMENT_OPTION
    ]
    # 선언된 항목·선택은 필드가 0 건이어도 자리를 갖는다(키 부재 분기 금지).
    root: "dict[str, None]" = {}
    shared: "dict[str, dict[str, None]]" = {slot.id: {} for slot in scan.slots}
    per_option: "dict[tuple[str, str], dict[str, None]]" = {
        (slot.id, option.id): {} for slot in scan.slots for option in slot.options
    }

    starts = _line_starts(text)
    for match in iter_field_token_matches(text):
        line = bisect_right(starts, match.start()) - 1
        slot_id, option_id = _owner_at(line, slot_ranges, option_ranges)
        name = match.group(1).strip()
        if slot_id is None:
            root.setdefault(name, None)
        elif option_id is None:
            shared[slot_id].setdefault(name, None)
        else:
            per_option[(slot_id, option_id)].setdefault(name, None)

    return TemplateStructure(
        tuple(root),
        tuple(
            TemplateSlot(
                slot.id,
                tuple(shared[slot.id]),
                tuple(
                    TemplateOption(
                        option.id,
                        tuple(per_option[(slot.id, option.id)]),
                        label=option.label,
                    )
                    for option in slot.options
                ),
                label=slot.label,
            )
            for slot in scan.slots
        ),
    )


def _line_bounds(text: str) -> "list[tuple[int, int]]":
    """줄마다 (첫 문자 오프셋, 마지막 문자 오프셋) — ``splitlines()`` 와 **같은 분할**.

    끝 오프셋은 줄 끝 문자(``\\n``·``\\r\\n``)를 포함한 마지막 문자다. 범위 span 이 마커 줄을
    통째로 덮어야 서로 다른 마커 줄의 span 이 겹치지 않는다(DISJOINT 의 구조적 근거).
    """
    bounds: "list[tuple[int, int]]" = []
    offset = 0
    for piece in text.splitlines(keepends=True):
        bounds.append((offset, offset + len(piece) - 1))
        offset += len(piece)
    return bounds


def _execution_structure_from_text(
    text: str, scan, product: TemplateStructure
) -> ExecutionTemplateStructure:
    """진단 0 인 스캔 결과 + 제품 구조 → composition-ready execution structure(S10-04 · #861).

    좌표는 문자 오프셋이다(모듈 도크스트링). occurrence 는 **토큰 등장마다 1건**이라 제품
    구조의 이름 중복 접기(S10-02)와 다른 축에 산다 — 제품은 「어떤 필드가 있는가」, occurrence 는
    「그 필드가 문서 어디에 몇 번 앉아 있는가」다.
    """
    bounds = _line_bounds(text)

    def _span(begin_line: int, end_line: int) -> "tuple[int, int]":
        return bounds[begin_line][0], bounds[end_line][1]

    slot_ranges = [
        (p.content_start, p.content_end, p.slot_id)
        for p in scan.placements
        if p.kind == PLACEMENT_SLOT
    ]
    option_ranges = [
        (p.content_start, p.content_end, p.slot_id, str(p.option_id))
        for p in scan.placements
        if p.kind == PLACEMENT_OPTION
    ]
    slot_regions = [
        SlotRegionObservation(
            slot_id=p.slot_id,
            content_entry_id=TXT_CONTENT_ENTRY_ID,
            begin_order=_span(p.begin_marker_line, p.end_marker_line)[0],
            end_order=_span(p.begin_marker_line, p.end_marker_line)[1],
        )
        for p in scan.placements
        if p.kind == PLACEMENT_SLOT
    ]
    option_regions = [
        OptionRegionObservation(
            slot_id=p.slot_id,
            option_id=str(p.option_id),
            content_entry_id=TXT_CONTENT_ENTRY_ID,
            begin_order=_span(p.begin_marker_line, p.end_marker_line)[0],
            end_order=_span(p.begin_marker_line, p.end_marker_line)[1],
            removal_capability_ref=TXT_LINE_PRIMITIVE_CONTRACT_V1.option_removal_contract_id,
        )
        for p in scan.placements
        if p.kind == PLACEMENT_OPTION
    ]

    starts = [b[0] for b in bounds]
    ordinals: "dict[str, int]" = {}
    occurrences: "list[FieldOccurrence]" = []
    for match in iter_field_token_matches(text):
        line = bisect_right(starts, match.start()) - 1
        slot_id, option_id = _owner_at(line, slot_ranges, option_ranges)
        name = match.group(1).strip()
        if slot_id is None:
            owner_kind = OWNER_ROOT
        elif option_id is None:
            owner_kind = OWNER_SLOT_SHARED
        else:
            owner_kind = OWNER_OPTION
        ordinal = ordinals.get(name, 0)
        ordinals[name] = ordinal + 1
        occurrences.append(
            FieldOccurrence(
                field_id=name,
                occurrence_ordinal=ordinal,
                owner_kind=owner_kind,
                owner_slot_id=slot_id,
                owner_option_id=option_id,
                content_entry_id=TXT_CONTENT_ENTRY_ID,
                structural_order=match.start(),
                native_value_target_class=TXT_FIELD_TOKEN_TARGET_CLASS,
                resolver_contract_id=(
                    TXT_LINE_PRIMITIVE_CONTRACT_V1.field_resolver_contract_id
                ),
            )
        )

    return build_execution_structure(
        product_structure=product,
        occurrences=occurrences,
        slot_regions=slot_regions,
        option_regions=option_regions,
        content_entries=(
            ContentEntry(
                content_entry_id=TXT_CONTENT_ENTRY_ID,
                envelope_class=TXT_LINE_SEQUENCE_ENVELOPE_CLASS,
                envelope_capability_facts={
                    # 줄을 지워도 남는 것은 여전히 줄의 나열이다 — 평문에 깨질 봉투가 없다.
                    "retains_admissible_envelope": True,
                    # 빈 줄은 TXT 의 정당한 내용이고 파일 끝의 빈 범위도 성립한다.
                    "handles_empty_edges": True,
                    # 항목 마커 줄은 선택 줄 제거의 대상이 아니다(2단계가 따로 소거한다).
                    "preserves_owner_marker": True,
                    # 마커 줄이 서로 달라 경계가 겹치는 경우 자체가 없다.
                    "coincident_boundary_admissible": True,
                },
            ),
        ),
        resolver_stability_facts={
            # 줄 제거는 남은 줄의 **내용**을 바꾸지 않는다 — 다시 스캔하면 그대로 찾힌다.
            "remaining_target_resolvable_after_removal": True,
            "active_field_resolvable_after_removal": True,
            # 토큰 치환은 다른 토큰의 텍스트를 건드리지 않는다(등장별 독립 치환).
            "field_write_preserves_identity": True,
        },
        admitted_relation_profile=TXT_ADMITTED_RELATION_PROFILE,
        projection_schema_version=TXT_STRUCTURE_PROJECTION_SCHEMA,
    )


def inspect_txt_qualification(canonical_bytes: bytes) -> QualificationInspection:
    """immutable canonical TXT bytes 를 읽어 제품 구조 또는 진단을 낸다(무변형)."""
    if not isinstance(canonical_bytes, bytes):
        raise TypeError("canonical_bytes must be bytes")
    try:
        text = canonical_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return QualificationInspection(
            None,
            (
                TemplateDiagnostic(
                    TXT_ENCODING_DIAGNOSTIC_KIND,
                    f"템플릿을 UTF-8 로 읽을 수 없습니다({exc.reason}, 위치 {exc.start}) — "
                    "파일을 UTF-8 로 다시 저장한 뒤 확인하세요.",
                ),
            ),
        )
    scan = scan_text_structure(text)
    if scan.diagnostics:
        # 부분 구조를 추측해 싣지 않는다 — 스캔 계약이 「진단 1건 이상 = 변환 불가」다.
        return QualificationInspection(
            None,
            tuple(
                TemplateDiagnostic(str(d.kind), d.message) for d in scan.diagnostics
            ),
        )
    product = _structure_from_text(text, scan)
    return QualificationInspection(
        product, (), _execution_structure_from_text(text, scan, product)
    )


TXT_QUALIFICATION_PROFILE = QualificationProfile(
    TXT_QUALIFICATION_PROFILE_ID,
    inspect_txt_qualification,
)


def txt_qualification_manifest(created_at: str) -> "QualificationProfileManifest":
    """제품 TXT profile 의 durable semantic manifest — profile identity 와 같은 곳에서 소유.

    :func:`~hwpxfiller.external.template_inspection.hwpx_qualification_manifest` 와 대칭이고
    같은 규율을 진다: manifest 는 immutable 이라 같은 id 로 다른 의미를 다시 쓰는 경로가
    없으므로, 규칙·projection 이 바뀌면 버전 문자열을 profile id 와 **함께** 올린다.
    """
    return build_manifest(
        qualification_profile_id=TXT_QUALIFICATION_PROFILE.id,
        media="txt",
        adapter_contract_version="txt-inspection-v1",
        product_rule_version="txt-qualification-rules-v1",
        operation_alphabet_version="txt-operations-v1",
        projection_schema_version=TXT_STRUCTURE_PROJECTION_SCHEMA,
        manifest_payload={},
        created_at=created_at,
    )
