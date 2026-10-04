"""Native HWPX authoring: analysis responsibilities."""

from __future__ import annotations

import re
from collections import defaultdict

import lxml.etree as etree  # pyright: ignore[reportMissingImports]

from hwpxcore.field_occurrence import resolve_field_occurrences
from hwpxcore.text_extract import HP_NS, require_package

from ..domain import authoring as _authoring
from ..domain.fields import is_fill_target_field_type
from ..domain.structure_scan import CONTEXT_MAX, PLACEMENT_OPTION, PLACEMENT_SLOT, normalize_field_id
from ..domain.template_authoring import (
    CATEGORY_COMPATIBILITY,
    CATEGORY_STRUCTURE,
    SEVERITY_ERROR,
    command_action,
    marker_target,
    navigate_action,
)
from .hwpx_product_inspection import (
    inspect_slot_regions,
    inspect_slots,
)

_HP = f"{{{HP_NS}}}"
from .hwpx_authoring_reading import (
    cell_path as _cell_path,
    field_marks as _field_marks,
    native_occurrence_context as _occurrence_context,
    root_anchor as _root_anchor,
    roots as _roots,
    simple_field_span as _simple_field_span,
)

_BOOKMARK_MESSAGE = re.compile(r"^(?P<entry>[^:]+): BOOKMARK (?P<name>'[^']*'|None)")

def _fields(package) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for entry, root in _roots(package):
        paragraphs = [node for node in root if node.tag == f"{_HP}p"]
        resolution = resolve_field_occurrences(entry, root)
        marks = _field_marks(entry, root)
        for ordinal, occurrence in enumerate(resolution.occurrences):
            if not is_fill_target_field_type(occurrence.field_type):
                continue
            name = normalize_field_id(occurrence.raw_name)
            if name is None:
                continue
            grouped[name].append(_field_row(root, entry, paragraphs, resolution, ordinal, occurrence, name, marks))
    return [{"name": name, "count": len(items), "occurrences": items}
            for name, items in grouped.items()]


def _field_position(root, paragraphs, occurrence):
    if occurrence.paragraph in paragraphs:
        anchor = paragraphs.index(occurrence.paragraph)
        return anchor, {"paragraph": anchor, **_simple_field_span(occurrence)}
    cell_path = _cell_path(root, occurrence.paragraph)
    if cell_path is None:
        return _root_anchor(paragraphs, occurrence.paragraph), {"paragraph": None}
    return cell_path[0]["parent_paragraph"], {
        "paragraph": cell_path[-1]["paragraph"], "cell_path": cell_path, **_simple_field_span(occurrence)}


def _field_row(root, entry, paragraphs, resolution, ordinal, occurrence, name, marks):
    anchor_paragraph, position = _field_position(root, paragraphs, occurrence)
    return {
                "entry": entry,
                "occurrence": ordinal,
                "pairing_id": occurrence.begin.get("id"),
                **position,
                "anchor_paragraph": anchor_paragraph,
                "paragraph_path": root.getroottree().getpath(occurrence.paragraph),
                "reliable": not resolution.diagnostics,
                "context": _occurrence_context(occurrence, name, marks),
                "raw": {
                    "begin_xml": etree.tostring(occurrence.begin, encoding="unicode", with_tail=False),
                    "end_xml": etree.tostring(occurrence.end, encoding="unicode", with_tail=False),
                    "value": "".join("".join(node.itertext()) for node in occurrence.texts),
                    # 문단의 원문 글자(필드 명령 매개변수 포함) — 원문 표기에만 쓴다(§7.2).
                    "text": "".join(occurrence.paragraph.itertext())[:120],
                },
            }


def _field_diagnostic_location(node, entry: str, paragraphs: list) -> dict | None:
    if node is None:
        return None
    paragraph = next((ancestor for ancestor in node.iterancestors(f"{_HP}p")), None)
    if paragraph is None:
        return None
    if paragraph in paragraphs:
        return {"entry": entry, "paragraph": paragraphs.index(paragraph)}
    cell_path = _cell_path(paragraph.getroottree().getroot(), paragraph)
    if cell_path is None:
        return None
    return {"entry": entry, "paragraph": cell_path[-1]["paragraph"], "cell_path": cell_path}


def _field_diagnostics(package) -> list[dict]:
    messages = {
        "unmatched-begin": "닫는 필드 경계가 없습니다.",
        "orphan-end": "여는 필드 경계가 없습니다.",
        "ambiguous-end": "어느 필드의 닫는 경계인지 확정할 수 없습니다.",
        "nested-field": "필드가 다른 필드 안에 겹쳐 있습니다.",
        "non-native-field-control": "지원하지 않는 필드 제어 요소가 있습니다.",
        "unsupported-control-shape": "필드 제어 요소의 구조를 확인할 수 없습니다.",
        "unsupported-traversal-lane": "필드가 편집 가능한 본문 위치에 있지 않습니다.",
        "paragraph-crossing": "필드 경계가 여러 문단에 걸쳐 있습니다.",
        "unsupported-container-crossing": "필드 경계가 서로 다른 문서 영역에 걸쳐 있습니다.",
    }
    compatibility = {"non-native-field-control", "unsupported-control-shape",
                     "unsupported-traversal-lane", "unsupported-container-crossing"}
    diagnostics = []
    for entry, root in _roots(package):
        paragraphs = [node for node in root if node.tag == f"{_HP}p"]
        nodes = [node for node in root.iter() if isinstance(node.tag, str)]

        resolution = resolve_field_occurrences(entry, root)
        diagnostics.extend(_resolution_diagnostics(resolution, nodes, entry, paragraphs, messages, compatibility))
        diagnostics.extend(_invalid_field_ids(resolution, entry, paragraphs))
    return diagnostics


def _resolution_diagnostics(resolution, nodes, entry, paragraphs, messages, compatibility) -> list[dict]:
    return [{"kind": str(item.kind), "message": messages.get(str(item.kind), "필드 구조를 확인하세요."),
                            "detail": str(item), "entry": entry, "order": item.order,
                            "severity": SEVERITY_ERROR,
                            "category": (CATEGORY_COMPATIBILITY if str(item.kind) in compatibility
                                         else CATEGORY_STRUCTURE),
                            "target": None, "location": loc, "actions": [navigate_action(loc)]}
                           for item in resolution.diagnostics
            for loc in (_field_diagnostic_location(
                nodes[item.order] if 0 <= item.order < len(nodes) else None, entry, paragraphs),)]


def _invalid_field_ids(resolution, entry, paragraphs) -> list[dict]:
    return [{"kind": "invalid-field-id", "message": "필드 이름이 비어 있습니다.",
                            "entry": entry, "order": occurrence.begin_order,
                            "severity": SEVERITY_ERROR, "category": CATEGORY_STRUCTURE,
                            "target": None, "location": loc,
                            "actions": [navigate_action(loc), command_action({
                                "type": "unset_field", "entry": entry, "occurrence": ordinal,
                                "pairing_id": occurrence.begin.get("id"),
                                "text": "".join("".join(node.itertext()) for node in occurrence.texts)})]}
                           for ordinal, occurrence in enumerate(resolution.occurrences)
                           if is_fill_target_field_type(occurrence.field_type)
                           and normalize_field_id(occurrence.raw_name) is None
            for loc in (_field_diagnostic_location(occurrence.begin, entry, paragraphs),)]


def _structure_diagnostic_location(package, context: str) -> dict | None:
    if not context:
        return None
    matches = []
    for entry, root in _roots(package):
        paragraphs = [node for node in root if node.tag == f"{_HP}p"]
        for paragraph in root.iter(f"{_HP}p"):
            location = _context_paragraph(root, entry, paragraphs, paragraph, context)
            if location is not None:
                matches.append(location)
    return matches[0] if len(matches) == 1 else None


def _context_paragraph(root, entry, paragraphs, paragraph, context):
    # 직속 텍스트만 — 표를 감싼 본문 문단이 셀 문단의 문맥까지 흡수하지 않게 한다.
    body = "".join(child.text or "" for run in paragraph if run.tag == f"{_HP}run"
                   for child in run if child.tag == f"{_HP}t")
    if body.strip()[:CONTEXT_MAX] != context:
        return None
    if paragraph in paragraphs:
        return {"entry": entry, "paragraph": paragraphs.index(paragraph)}
    cell_path = _cell_path(root, paragraph)
    if cell_path is not None:
        return {"entry": entry, "paragraph": cell_path[-1]["paragraph"], "cell_path": cell_path}
    return None


def _structure_diagnostic_position(package, item) -> dict | None:
    """구조 진단의 자리 — 읽기가 적은 본문 문단 좌표가 먼저다. 없으면(셀·글상자 안) 문맥 글로 되짚는다.

    같은 문맥의 문단이 여럿이면(예: 같은 닫는 마커 여러 개) 글로는 자리를 정할 수 없다 — 좌표가 그 자리다.
    """
    if item.entry and isinstance(item.index, int) and item.index >= 0:
        return {"entry": item.entry, "paragraph": item.index}
    return _structure_diagnostic_location(package, item.context)


def analyze_hwpx(content: object) -> dict:
    package = require_package(content)
    slots, diagnostics = inspect_slots(package)
    structure = _authoring.scan_structure(package)
    fields = _fields(package)
    snapshot = inspect_slot_regions(package)
    return {
        "fields": fields,
        "slots": [_slot_row(slot, snapshot) for slot in slots],
        "diagnostics": (_bookmark_diagnostics(package, diagnostics) +
                        _structure_diagnostics(package, structure) + _field_diagnostics(package)),
        "summary": {"slots": len(slots),
                    "options": sum(len(slot.options) for slot in slots),
                    "fields": sum(field["count"] for field in fields)},
    }


def _slot_row(slot, snapshot) -> dict:
    return {"id": slot.id, "label": slot.label or "", "kind": PLACEMENT_SLOT,
            "location": _region_location(snapshot.slot_regions.get(slot.id)),
            "raw": _region_raw(snapshot.slot_regions.get(slot.id)),
            "options": [{"id": option.id, "label": option.label or "", "kind": PLACEMENT_OPTION,
                         "slot_id": slot.id,
                         "location": _region_location(snapshot.option_regions.get((slot.id, option.id))),
                         "raw": _region_raw(snapshot.option_regions.get((slot.id, option.id)))}
                        for option in slot.options]}


def _bookmark_diagnostics(package, diagnostics) -> list[dict]:
    return [{"kind": item.kind, "message": item.message,
                          "severity": SEVERITY_ERROR, "category": CATEGORY_STRUCTURE,
                          "target": _bookmark_target(item.message), "location": location,
                          "actions": [navigate_action(location)]}
                         for item in diagnostics
                         for location in (_bookmark_location(package, item.message),)]


def _structure_diagnostics(package, structure) -> list[dict]:
    return [item.to_dict() | {"severity": SEVERITY_ERROR, "category": CATEGORY_STRUCTURE,
                                           "target": marker_target(item.context), "location": location,
                                           "actions": [navigate_action(location)]}
                         for item in structure.diagnostics
                         for location in (_structure_diagnostic_position(package, item),)]


def _bookmark_target(message: str) -> str | None:
    match = _BOOKMARK_MESSAGE.match(message)
    if match is None or match.group("name") == "None":
        return None
    return match.group("name")[1:-1]


def _bookmark_location(package, message: str) -> dict | None:
    """Paragraph of the one BOOKMARK begin a product diagnostic names, when unique."""
    match = _BOOKMARK_MESSAGE.match(message)
    name = _bookmark_target(message)
    if match is None or name is None or match.group("entry") not in package.entries:
        return None
    entry = match.group("entry")
    root = etree.fromstring(package.entries[entry], parser=etree.XMLParser(resolve_entities=False))
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    begin = _unique_bookmark_begin(root, name)
    if begin is None:
        return None
    paragraph = next(begin.iterancestors(f"{_HP}p"), None)
    if paragraph is None or paragraph not in paragraphs:
        return None
    return {"entry": entry, "paragraph": paragraphs.index(paragraph)}


def _unique_bookmark_begin(root, name):
    begins = [node for node in root.iter(f"{_HP}fieldBegin")
              if node.get("type") == "BOOKMARK" and node.get("name") == name]
    return begins[0] if len(begins) == 1 else None


def _region_location(region) -> dict | None:
    if region is None:
        return None
    return {"entry": region.section, "start_paragraph": region.start_paragraph,
            "end_paragraph": region.end_paragraph}


def _region_raw(region) -> dict | None:
    if region is None:
        return None
    return {"bookmark_name": region.name, "meta_tags": list(region.meta_tags)}


fields = _fields
region_location = _region_location
