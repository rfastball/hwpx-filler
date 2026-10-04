"""Native HWPX authoring: availability responsibilities."""

from __future__ import annotations

from collections.abc import Mapping

import lxml.etree as etree  # pyright: ignore[reportMissingImports]

from hwpxcore.text_extract import HP_NS, require_package

from ..domain.structure_scan import PLACEMENT_OPTION, PLACEMENT_SLOT
from ..domain.template_authoring import (
    ALTERNATIVE_CREATE_SLOT,
    COMMAND_TYPES,
    REASON_FIELD_OVERLAP,
    REASON_INVALID_SELECTION,
    REASON_MULTI_REGION,
    REASON_OPTION_OUTSIDE_SLOT,
    REASON_REGION_IN_CELL,
    REASON_REGION_OVERLAP,
    REASON_STRUCTURE_FIRST,
    availability_entries,
    shared_reasons,
    target_availability,
)
from .hwpx_product_inspection import (
    inspect_slot_regions,
)

_HP = f"{{{HP_NS}}}"
from .hwpx_authoring_reading import (
    field_range_refusal as _field_range_refusal,
    paragraph_sites as _paragraph_sites,
    selected_paragraph as _selected_paragraph,
)
from .hwpx_authoring_analysis import (
    analyze_hwpx,
)
from .hwpx_authoring_fields import (
    MULTI_PARAGRAPH_FIELD as _MULTI_PARAGRAPH_FIELD,
)

def _selection_values(package, selection: Mapping[str, object]) -> tuple[str, int, int, int, int] | None:
    entry = selection.get("entry")
    first = selection.get("start_paragraph", selection.get("paragraph"))
    last = selection.get("end_paragraph", first)
    start, end = selection.get("start", 0), selection.get("end", selection.get("start", 0))
    values = (first, last, start, end)
    if not _valid_selection_values(package, entry, values):
        return None
    assert isinstance(entry, str) and isinstance(first, int) and isinstance(last, int) and isinstance(start, int) and isinstance(end, int)
    if first > last or (first == last and start > end):
        return None
    return entry, first, last, start, end


def _valid_selection_values(package, entry: object, values: tuple[object, ...]) -> bool:
    return (isinstance(entry, str) and entry in package.entries
            and not any(type(value) is not int or value < 0 for value in values))


def _selection_frame(package, selection: Mapping[str, object]) -> tuple[str, int, int, int, int, object] | None:
    """선택의 (구역, 첫·끝 문단, 글자 범위, 첫 문단 요소). 셀 안 선택은 문단 번호가 셀 문단이다 — 요소도 그 셀 문단이다."""
    values = _selection_values(package, selection)
    if values is None:
        return None
    entry, first, last, start, end = values
    root = etree.fromstring(package.entries[entry], parser=etree.XMLParser(resolve_entities=False))
    cell_path = selection.get("cell_path")
    if cell_path is not None:
        try:
            return entry, first, last, start, end, _selected_paragraph(root, first, cell_path)
        except ValueError:
            return None
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    if last >= len(paragraphs):
        return None
    return entry, first, last, start, end, paragraphs[first]


def _overlaps_field(occurrence: dict, paragraph: int, first: int, last: int,
                    start: int, end: int) -> bool:
    low, high = occurrence.get("start"), occurrence.get("end")
    if not isinstance(low, int) or not isinstance(high, int):
        return True
    if first < paragraph < last:
        return True
    if first == last:
        return low <= start <= high if start == end else low < end and start < high
    return start <= high if paragraph == first else low <= end


def _field_hit(occurrence: dict, entry: str, cell_path: object, first: int, last: int,
               start: int, end: int) -> bool:
    paragraph = occurrence.get("paragraph")
    # 셀 문단과 본문 문단은 번호 공간이 다르다 — 같은 셀 경로의 사용 위치만 겹친다.
    if (occurrence.get("entry") != entry or occurrence.get("cell_path") != cell_path
            or not isinstance(paragraph, int) or not first <= paragraph <= last):
        return False
    return _overlaps_field(occurrence, paragraph, first, last, start, end)


def _field_hits(analysis: dict, entry: str, cell_path: object, first: int, last: int,
                start: int, end: int) -> list[str]:
    return [field["name"] for field in analysis["fields"]
            for occurrence in field["occurrences"]
            if _field_hit(occurrence, entry, cell_path, first, last, start, end)]


def _regions(analysis: dict, entry: str) -> list[tuple]:
    return [(item["kind"], item.get("slot_id", item["id"]),
             item["id"] if item["kind"] == PLACEMENT_OPTION else None, item["location"])
            for slot in analysis["slots"] for item in [slot, *slot["options"]]
            if item["location"] is not None and item["location"]["entry"] == entry]


def _region_hits(regions: list[tuple], cell_path: object, first: int, last: int) -> tuple[list[tuple], list[tuple], bool]:
    # 항목·선택 영역은 본문 문단 단위다 — 셀 안 선택은 어떤 영역과도 겹치거나 담기지 않는다(locate 와 같다).
    hit = [region for region in regions
           if cell_path is None and region[3]["start_paragraph"] <= last and first <= region[3]["end_paragraph"]]
    containing = [region for region in hit
                  if region[3]["start_paragraph"] <= first and last <= region[3]["end_paragraph"]]
    return hit, containing, any(region not in containing for region in hit)


def _target_ids(context: Mapping[str, object], containing: list[tuple], snapshot) -> tuple[object, object]:
    slot_id = context["slot_id"] if "slot_id" in context else next(
        (region[1] for region in containing if region[0] == PLACEMENT_SLOT), None)
    option_id = context["option_id"] if "option_id" in context else next(
        (region[2] for region in containing if region[0] == PLACEMENT_OPTION), None)
    if slot_id is not None and slot_id not in snapshot.slot_regions:
        slot_id = option_id = None
    return slot_id, option_id


def _create_field_reason(first: int, last: int, start: int, end: int,
                         first_paragraph: object, crossing: bool, field_hits: list[str]) -> str | None:
    if crossing:
        return REASON_MULTI_REGION
    if first != last:
        return _MULTI_PARAGRAPH_FIELD
    sites, hazards, text = _paragraph_sites(first_paragraph)
    return _field_range_refusal(sites, hazards, text, start, end) or (
        REASON_FIELD_OVERLAP if field_hits and start != end else None)


def _create_region_reasons(reasons: dict, alternatives: dict[str, dict], *,
                           broken: bool, cell_path: object, hit: list[tuple], containing: list[tuple]) -> None:
    if broken:
        reasons["create_slot"] = reasons["create_option"] = REASON_STRUCTURE_FIRST
        return
    if cell_path is not None:
        reasons["create_slot"] = reasons["create_option"] = REASON_REGION_IN_CELL
        return
    reasons["create_slot"] = REASON_REGION_OVERLAP if hit else None
    reasons["create_option"], offer_slot = _create_option_reason(hit, containing)
    if offer_slot:
        alternatives["create_option"] = dict(ALTERNATIVE_CREATE_SLOT)


def _create_option_reason(hit: list[tuple], containing: list[tuple]) -> tuple[str | None, bool]:
    owners = [region for region in containing if region[0] == PLACEMENT_SLOT]
    if len(owners) == 1:
        return REASON_REGION_OVERLAP if any(region[0] == PLACEMENT_OPTION for region in hit) else None, False
    if any(region[0] == PLACEMENT_SLOT for region in hit):
        return REASON_MULTI_REGION, False
    return REASON_OPTION_OUTSIDE_SLOT, True


def available_commands_hwpx(content: object, selection: Mapping[str, object],
                            context: Mapping[str, object] | None = None) -> list[dict]:
    """Decide which commands the current HWPX selection allows and why not (F40, §6.1)."""
    package = require_package(content)
    context = context or {}
    frame = _selection_frame(package, selection)
    if frame is None:
        return availability_entries(dict.fromkeys(COMMAND_TYPES, REASON_INVALID_SELECTION))
    entry, first, last, start, end, first_paragraph = frame
    cell_path = selection.get("cell_path")
    analysis = analyze_hwpx(package)
    snapshot = inspect_slot_regions(package)

    field_hits = _field_hits(analysis, entry, cell_path, first, last, start, end)
    hit, containing, crossing = _region_hits(_regions(analysis, entry), cell_path, first, last)
    slot_id, option_id = _target_ids(context, containing, snapshot)
    target_kind = (PLACEMENT_OPTION if option_id is not None and slot_id is not None
                   else PLACEMENT_SLOT if slot_id else None)
    broken = bool(snapshot.diagnostics)
    reasons = shared_reasons(field_hits=field_hits, target_kind=target_kind, has_slot=slot_id is not None,
                             structure_broken=broken)
    alternatives: dict[str, dict] = {}
    reasons["create_field"] = _create_field_reason(first, last, start, end, first_paragraph, crossing, field_hits)
    _create_region_reasons(reasons, alternatives, broken=broken, cell_path=cell_path, hit=hit, containing=containing)
    return availability_entries(reasons, alternatives)


def available_target_commands_hwpx(content: object, kind: str, name: str | None = None) -> list[dict]:
    """HWPX availability for an identity-chosen target; structure errors come from the same snapshot."""
    package = require_package(content)
    return target_availability(kind, name=name,
                               structure_broken=bool(inspect_slot_regions(package).diagnostics))
