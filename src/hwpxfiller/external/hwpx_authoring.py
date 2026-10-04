"""Native HWPX authoring: facade responsibilities."""

from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Mapping


from hwpxcore.field_occurrence import resolve_field_occurrences
from hwpxcore.text_extract import HP_NS, require_package

from ..domain import authoring as _authoring
from ..application.execution_contract_set import PLAN_APPLY_FIELD_BINDING, PLAN_REMOVE_OPTION
from ..domain.fields import FieldDocument as FieldDocument, is_fill_target_field_type
from ..domain.structure_scan import PLACEMENT_OPTION, PLACEMENT_SLOT, normalize_field_id
from ..domain.template_authoring import (
    trial_document_values,
)
from .hwpx_product_inspection import (
    inspect_slot_regions,
)
from .hwpx_structure_ops import (
    remove_slot_option,
)
from .hwpx_qualification import inspect_hwpx_qualification
from .materialization_conformance_vocabulary import ConformanceFailure
from .materialization_runner import materialize_authoring_trial

_HP = f"{{{HP_NS}}}"
from .hwpx_authoring_reading import (
    roots as _roots,
)
from .hwpx_authoring_analysis import (
    fields as _fields,
    region_location as _region_location,
)
from .hwpx_authoring_regions import region_kind

_region_kind = region_kind

_NOTE_TABLE = "표 안의 문단은 소속된 본문 문단 줄에 이어서 표시됩니다."
_NOTE_BROKEN = "구조 오류가 있어 항목·선택 경계를 표기하지 않았습니다."
_NOTE_UNWRITABLE_ID = "구간 표기로 되쓸 수 없는 식별자가 있어 해당 경계를 생략했습니다."

def syntax_view_hwpx(content: object) -> dict:
    """Render the current HWPX meaning in the TXT template grammar. Read-only (F26, §3.2)."""
    package = require_package(content)
    snapshot = inspect_slot_regions(package)
    begins: dict[tuple[str, int], list[str]] = defaultdict(list)
    ends: dict[tuple[str, int], list[str]] = defaultdict(list)
    notes: list[str] = []
    if snapshot.diagnostics:
        notes.append(_NOTE_BROKEN)
    else:
        _syntax_markers(snapshot, begins, ends, notes)
    sections = [_syntax_section(entry, root, begins, ends, notes) for entry, root in _roots(package)]
    return {"sections": sections, "note": " ".join(notes) or None}


def _syntax_markers(snapshot, begins, ends, notes) -> None:
    for slot in snapshot.slots:
        members = [(PLACEMENT_SLOT, slot.id, slot.label, snapshot.slot_regions[slot.id])]
        members += [(PLACEMENT_OPTION, option.id, option.label, snapshot.option_regions[(slot.id, option.id)])
                    for option in slot.options]
        for kind, identifier, label, region in members:
            try:
                opening = _authoring.begin_marker_text(kind, identifier, label)
            except ValueError:
                if _NOTE_UNWRITABLE_ID not in notes:
                    notes.append(_NOTE_UNWRITABLE_ID)
                continue
            begins[(region.section, region.start_paragraph)].append(opening)
            ends[(region.section, region.end_paragraph)].insert(0, _authoring.end_marker_text(kind))


def _syntax_section(entry, root, begins, ends, notes) -> dict:
    named, hidden = _syntax_fields(entry, root)
    lines: list[str] = []
    for index, paragraph in enumerate(node for node in root if node.tag == f"{_HP}p"):
        if any(True for _ in paragraph.iter(f"{_HP}tbl")) and _NOTE_TABLE not in notes:
            notes.append(_NOTE_TABLE)
        lines.extend(begins.get((entry, index), ()))
        lines.append(_syntax_paragraph(paragraph, named, hidden))
        lines.extend(ends.get((entry, index), ()))
    return {"entry": entry, "text": "\n".join(lines)}


def _syntax_fields(entry, root):
    occurrences = resolve_field_occurrences(entry, root).occurrences
    named = {occurrence.begin: name for occurrence in occurrences
             if is_fill_target_field_type(occurrence.field_type)
             for name in (normalize_field_id(occurrence.raw_name),) if name is not None}
    hidden = {node for occurrence in occurrences if occurrence.begin in named for node in occurrence.texts}
    return named, hidden


def _syntax_paragraph(paragraph, named, hidden) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node in named:
            parts.append("{{" + named[node] + "}}")
        elif node.tag == f"{_HP}t" and node not in hidden:
            parts.append(node.text or "")
    return "".join(parts)


def trial_hwpx(content: object, values: Mapping[str, object], selected: Mapping[str, str]) -> dict:
    from hwpxcore.package import HwpxPackage

    package = copy.deepcopy(require_package(content))
    assert isinstance(package, HwpxPackage)
    source_bytes = package.to_bytes()
    source_fields = _fields(package)
    snapshot = inspect_slot_regions(package)
    if snapshot.diagnostics:
        raise ValueError("문서 구조 오류를 수정한 뒤 결과를 시험하세요.")
    excluded = _trial_exclusions(snapshot, selected)
    for item in reversed(excluded):
        remove_slot_option(package, item["slot_id"], item["option_id"])
    selected_fields = _fields(package)
    # 값이 없는 필드는 거절하지 않는다 — 생성 경로와 같은 빈 값 표식을 받고 보고의 empty_fields 에 선다(#957).
    logical_values, empty_fields = trial_document_values((field["name"] for field in selected_fields), values)
    materialized = _trial_materialize(source_bytes, selected_fields, excluded, logical_values)
    assert isinstance(package, HwpxPackage)
    output_fields = _fields(HwpxPackage.from_bytes(materialized.output_bytes))
    provenance = _trial_provenance(source_fields, output_fields, values)
    return {"bytes": materialized.output_bytes, "excluded": excluded,
            "occurrences": provenance,
            "report": {"missing_fields": [], "empty_fields": empty_fields}}


def _trial_exclusions(snapshot, selected) -> list[dict]:
    excluded = []
    for slot in snapshot.slots:
        choice, chosen_option = _trial_choice(slot, selected)
        excluded.extend(_trial_slot_exclusions(snapshot, slot, choice, chosen_option))
    if set(selected) - {slot.id for slot in snapshot.slots}:
        raise ValueError("존재하지 않는 항목 선택이 있습니다.")
    return excluded


def _trial_choice(slot, selected):
    choice = selected.get(slot.id)
    if slot.options and choice not in {option.id for option in slot.options}:
        raise ValueError(f"'{slot.id}' 항목의 시험 선택을 지정하세요.")
    chosen_option = next((option for option in slot.options if option.id == choice), None)
    if slot.options:
        assert chosen_option is not None
    return choice, chosen_option


def _trial_slot_exclusions(snapshot, slot, choice, chosen_option) -> list[dict]:
    excluded = []
    for option in slot.options:
        if option.id == choice:
            continue
        assert chosen_option is not None
        region = snapshot.option_regions[(slot.id, option.id)]
        excluded.append({"slot_id": slot.id, "option_id": option.id,
                         "selected_option_id": choice,
                         "label": option.label or option.id,
                         "reason": (f"현재 시험에서 '{chosen_option.label or chosen_option.id}'을 골라 "
                                    f"'{option.label or option.id}'은 제외되었습니다."),
                         "source": _region_location(region)})
    return excluded


def _trial_materialize(source_bytes, selected_fields, excluded, logical_values):
    qualification = inspect_hwpx_qualification(source_bytes)
    structure = qualification.execution_structure
    if structure is None:
        raise ValueError("문서 구조 오류를 수정한 뒤 결과를 시험하세요.")
    operations = tuple(
        {"op": PLAN_REMOVE_OPTION, "slot_id": item["slot_id"], "option_id": item["option_id"]}
        for item in excluded
    ) + tuple(
        {"op": PLAN_APPLY_FIELD_BINDING, "field_id": field["name"]}
        for field in selected_fields
    )
    materialized = materialize_authoring_trial(
        source_bytes=source_bytes, structure=structure, ordered_operations=operations,
        active_field_requirements=tuple(
            {"field_id": field["name"], "expected_active_occurrence_count": field["count"]}
            for field in selected_fields
        ),
        document_values=logical_values,
    )
    if isinstance(materialized, ConformanceFailure):
        raise ValueError(f"결과 시험 검증에 실패했습니다: {materialized.detail}")
    return materialized


def _trial_provenance(source_fields, output_fields, values) -> list[dict]:
    sources = {(occurrence["entry"], occurrence["pairing_id"]): occurrence
               for field in source_fields for occurrence in field["occurrences"]}
    output_values, _ = trial_document_values((field["name"] for field in output_fields), values)
    return [{"name": field["name"], "value": output_values[field["name"]],
             "source": sources.get((occurrence["entry"], occurrence["pairing_id"]), occurrence),
             "output": occurrence}
            for field in output_fields for occurrence in field["occurrences"]]



from .hwpx_authoring_analysis import analyze_hwpx as analyze_hwpx

from .hwpx_authoring_search import stray_token_problems as stray_token_problems

from .hwpx_authoring_search import search_hwpx as search_hwpx

from .hwpx_authoring_search import same_text_hwpx as same_text_hwpx

from .hwpx_authoring_search import selected_context_hwpx as selected_context_hwpx

from .hwpx_authoring_commands import apply_hwpx as apply_hwpx

from .hwpx_authoring_commands import preview_hwpx as preview_hwpx

from .hwpx_authoring_availability import available_commands_hwpx as available_commands_hwpx

from .hwpx_authoring_availability import available_target_commands_hwpx as available_target_commands_hwpx
