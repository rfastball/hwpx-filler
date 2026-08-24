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

**execution structure 는 내지 않는다**(``None``). composition fact 를 낼 수 있는 profile 만
그것을 싣고(#773), TXT 물질화는 S10-04 소관이다. 그래서 이 profile 의 projection schema 는
composition-ready 집합(:func:`~hwpxfiller.application.execution_structure.
is_supported_execution_projection`)에 **등록되지 않은** 독립 이름이고, 그 결과
``run_qualification_stage`` 는 product-only projection 을 쓴다(pin 과 정합).

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
TXT_STRUCTURE_PROJECTION_SCHEMA = "txt-structure-projection-v1"

#: 규칙·projection 이 바뀌면 profile id 와 manifest 버전 문자열을 함께 올린다(HWPX 동형).
TXT_QUALIFICATION_PROFILE_ID = "txt-template-qualification-v1"


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
    return QualificationInspection(_structure_from_text(text, scan), ())


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
