"""Native HWPX authoring on an opened, disposable package snapshot."""

from __future__ import annotations

import copy
import json
import re
from collections import defaultdict
from collections.abc import Mapping

import lxml.etree as etree  # pyright: ignore[reportMissingImports]

from hwpxcore.bookmark_region import (
    BookmarkRegion,
    append_bookmark_metatag,
    create_bookmark_region,
    resolve_bookmark_topology,
    unwrap_bookmark_region,
)
from hwpxcore.field_occurrence import resolve_field_occurrences
from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.text_extract import HP_NS, require_package

from ..domain import authoring as _authoring
from ..application.execution_contract_set import PLAN_APPLY_FIELD_BINDING, PLAN_REMOVE_OPTION
from ..domain.fields import is_fill_target_field_type
from ..domain.schema import extract_schema
from ..domain.slot import Slot, SlotOption
from ..domain.structure_scan import CONTEXT_MAX, normalize_field_id
from ..domain.template_authoring import (
    ALTERNATIVE_CREATE_SLOT,
    CATEGORY_AUTHORING,
    CATEGORY_COMPATIBILITY,
    CATEGORY_STRUCTURE,
    COMMAND_TYPES,
    COMPILE_TOKEN,
    COMPILE_TOKEN_LABEL,
    KIND_STRAY_TOKEN,
    MESSAGE_STRAY_TOKEN,
    REASON_FIX_STALE,
    REASON_FIELD_OVERLAP,
    REASON_INVALID_SELECTION,
    REASON_MULTI_REGION,
    REASON_OPTION_OUTSIDE_SLOT,
    REASON_REGION_OVERLAP,
    REASON_STRUCTURE_FIRST,
    SEVERITY_ERROR,
    INVALID_FIELD_NAME,
    REASON_NEED_IDENTIFIER,
    REASON_NEED_NEW_IDENTIFIER,
    SEVERITY_WARNING,
    CascadeRequired,
    InvalidName,
    NameConflict,
    availability_entries,
    command_action,
    command_label,
    field_candidates,
    marker_target,
    navigate_action,
    context_focus,
    occurrence_context,
    occurrence_context_parts,
    shared_reasons,
    target_availability,
    trial_document_values,
    whole_field_unset,
)
from .hwpx_product_inspection import (
    inspect_slot_regions,
    inspect_slots,
    serialize_slot_metatag,
    serialize_slot_option_metatag,
)
from .hwpx_structure_ops import (
    remove_slot,
    remove_slot_option,
    structure_region_name,
)
from .hwpx_qualification import inspect_hwpx_qualification
from .materialization_conformance_vocabulary import ConformanceFailure
from .materialization_runner import materialize_authoring_trial

_HP = f"{{{HP_NS}}}"


def _roots(package):
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    for entry in package.content_xml_names():
        yield entry, etree.fromstring(package.entries[entry], parser=parser)


def _simple_field_span(occurrence) -> dict:
    """Project codepoint offsets only when native text has no ambiguous controls."""
    paragraph = occurrence.paragraph
    for run in paragraph:
        if run.tag != f"{_HP}run":
            continue
        if any(child.tag not in {f"{_HP}t", f"{_HP}ctrl"} for child in run):
            return {}
    for control in paragraph.iter(f"{_HP}ctrl"):
        if any(child.tag not in {f"{_HP}fieldBegin", f"{_HP}fieldEnd"} for child in control):
            return {}
    offset = 0
    start = end = None
    for node in paragraph.iter():
        if node is occurrence.begin:
            start = offset
        elif node is occurrence.end:
            end = offset
        elif node.tag == f"{_HP}t":
            offset += len(node.text or "")
    assert start is not None and end is not None and start <= end
    return {"start": start, "end": end}


_CELL_PATH_KEYS = frozenset({"parent_paragraph", "control", "cell", "paragraph"})
_CONTROL_TAGS = frozenset(f"{_HP}{name}" for name in (
    "tbl", "pic", "container", "rect", "ellipse", "line", "connectLine", "arc", "polygon",
    "curve", "compose", "dutmal", "equation", "btn", "checkBtn", "radioBtn", "comboBox",
    "edit", "chart", "ole"))
_CTRL_CHILD_TAGS = frozenset(f"{_HP}{name}" for name in (
    "colPr", "header", "footer", "footNote", "endNote", "autoNum", "indexmark", "fieldBegin",
    "pageHiding", "pageNumCtrl", "pageNum", "bookmark", "newNum"))


def _cell_path(root, paragraph) -> list[dict] | None:
    """Project a table-cell paragraph onto the rhwp cursor path, outermost table first.

    Each step is ``{"parent_paragraph", "control", "cell", "paragraph"}``:

    - ``parent_paragraph`` is the body ``hp:p`` index (root-level children of
      ``hs:sec``) for the first step and the previous step's ``paragraph`` afterwards.
    - ``control`` is the position of the ``hp:tbl`` in the owner paragraph's control
      list, built in document order from the *direct* children of each ``hp:run`` the
      way rhwp's ``parse_paragraph_body`` / ``parse_ctrl`` do: the shape/object tags in
      ``_CONTROL_TAGS`` count 1; ``hp:switch`` counts 1 only with a ``chart``/``ole``
      descendant; ``hp:secPr`` counts 1 plus 1 for a ``colPr`` child; ``hp:ctrl``
      counts one per child in ``_CTRL_CHILD_TAGS`` plus a non-empty ``hiddenComment``
      (``fieldEnd`` and unknown children count 0); ``hp:t`` and the rest count 0.
    - ``cell`` is the ``hp:tc`` ordinal in document order within that table (merged
      cells are one ``tc``; nested tables' cells excluded).
    - ``paragraph`` is the ``hp:p`` ordinal among the ``hp:subList`` children — the
      coordinate rhwp's ``resolve_paragraph_by_path`` walks into.

    Returns ``None`` for a body paragraph and for any paragraph whose ancestor chain is
    not strictly ``hp:p → hp:run → hp:tbl → hp:tr → hp:tc → hp:subList → hp:p`` (text
    boxes, captions, headers, ...), so callers omit ``cell_path`` there.
    """
    def control_count(node) -> int:
        if node.tag in _CONTROL_TAGS:
            return 1
        if node.tag == f"{_HP}switch":
            return int(next(node.iter(f"{_HP}chart", f"{_HP}ole"), None) is not None)
        if node.tag == f"{_HP}secPr":
            return 1 + int(node.find(f"{_HP}colPr") is not None)
        if node.tag == f"{_HP}ctrl":
            return sum(1 for child in node if child.tag in _CTRL_CHILD_TAGS
                       or (child.tag == f"{_HP}hiddenComment" and len(child)))
        return 0

    steps: list[dict] = []
    node = paragraph
    while True:
        sub_list = node.getparent()
        if sub_list is root:
            break
        if sub_list is None or sub_list.tag != f"{_HP}subList":
            return None
        cell = sub_list.getparent()
        row = cell.getparent() if cell is not None and cell.tag == f"{_HP}tc" else None
        table = row.getparent() if row is not None and row.tag == f"{_HP}tr" else None
        run = table.getparent() if table is not None and table.tag == f"{_HP}tbl" else None
        owner = run.getparent() if run is not None and run.tag == f"{_HP}run" else None
        if table is None or owner is None or owner.tag != f"{_HP}p":
            return None
        control = None
        counted = 0
        for owner_run in owner:
            if owner_run.tag != f"{_HP}run":
                continue
            for child in owner_run:
                if child is table:
                    control = counted
                counted += control_count(child)
        assert control is not None
        cells = [item for item in table.iter(f"{_HP}tc")
                 if next(item.iterancestors(f"{_HP}tbl"), None) is table]
        steps.append({"parent_paragraph": -1, "control": control, "cell": cells.index(cell),
                      "paragraph": [item for item in sub_list if item.tag == f"{_HP}p"].index(node)})
        node = owner
    if not steps:
        return None
    steps.reverse()
    steps[0]["parent_paragraph"] = [item for item in root if item.tag == f"{_HP}p"].index(node)
    for previous, step in zip(steps, steps[1:], strict=False):
        step["parent_paragraph"] = previous["paragraph"]
    return steps


def _field_marks(entry: str, root) -> dict:
    """필드 경계 노드 → (사용 위치 열쇠, 이름). 문맥 조각에서 필드 값 자리를 ``[이름]`` 으로 접는 데 쓴다."""
    marks: dict = {}
    for occurrence in resolve_field_occurrences(entry, root).occurrences:
        name = normalize_field_id(occurrence.raw_name)
        if name is None or not is_fill_target_field_type(occurrence.field_type):
            continue
        marks[occurrence.begin] = (occurrence.begin, name)
        marks[occurrence.end] = (occurrence.begin, None)
    return marks


def _paragraph_pieces(paragraph, marks: dict) -> list[tuple[str, object, str | None]]:
    """문단 본문의 조각 ``(글자, 필드 열쇠, 필드 이름)`` — 글자 offset 은 본문 검색의 ``body`` 와 같다.

    본문은 문단 바로 아래 ``hp:run`` 의 ``hp:t`` 뿐이다. 필드 명령의 매개변수 문자열(``Clickhere:set:…``)은
    ``hp:t`` 가 아니라 들어오지 않는다. 필드 시작마다 빈 조각을 두어 값이 빈 필드도 자리를 남긴다.
    """
    pieces: list[tuple[str, object, str | None]] = []
    current: tuple[object, str] | None = None
    for node in paragraph.iter():
        mark = marks.get(node)
        if mark is not None:
            key, name = mark
            current = (key, name) if name is not None else None
            if current is not None:
                pieces.append(("", key, name))
        elif node.tag == f"{_HP}t":
            run = node.getparent()
            if run is not None and run.tag == f"{_HP}run" and run.getparent() is paragraph:
                key, name = current if current is not None else (None, None)
                pieces.append((node.text or "", key, name))
    return pieces


def _render_pieces(pieces: list[tuple[str, object, str | None]]) -> str:
    out: list[str] = []
    last: object = None
    for text, key, name in pieces:
        if key is None:
            out.append(text)
        elif key is not last:
            out.append(f"[{name}]")
        last = key
    return "".join(out)


def _occurrence_context(occurrence, name: str, marks: dict) -> str:
    """사용 위치 한 곳의 문맥 — 그 문단의 **본문 글자**만 앞뒤로 싣고 필드 자리는 ``[이름]`` 이다(§7.2·P10)."""
    pieces = _paragraph_pieces(occurrence.paragraph, marks)
    own = [index for index, piece in enumerate(pieces) if piece[1] is occurrence.begin]
    if not own:
        return f"[{name}]"
    return occurrence_context(_render_pieces(pieces[:own[0]]), f"[{name}]",
                              _render_pieces(pieces[own[-1] + 1:]))


def _body_hit_context(pieces: list[tuple[str, object, str | None]], start: int, end: int) -> str:
    """본문 검색 한 건의 문맥 — 찾은 글자가 필드 값 안이면 그 필드 전체를 표지로 보인다(§6.3)."""
    return "".join(_body_hit_parts(pieces, start, end))


def _body_hit_parts(pieces: list[tuple[str, object, str | None]], start: int,
                    end: int) -> tuple[str, str, str]:
    """:func:`_body_hit_context` 의 세 조각(앞·찾은 글자·뒤)."""
    spans: list[tuple[int, int, tuple[str, object, str | None]]] = []
    offset = 0
    for piece in pieces:
        spans.append((offset, offset + len(piece[0]), piece))
        offset += len(piece[0])
    hit = {id(piece[1]) for lo, hi, piece in spans if piece[1] is not None and lo < end and start < hi}
    # 찾은 글자가 필드 값에 걸치면 그 필드(들) 전체가 가운데 표지가 된다.
    inside = [(lo, hi) for lo, hi, piece in spans if piece[1] is not None and id(piece[1]) in hit]
    if inside:
        start, end = min(start, inside[0][0]), max(end, inside[-1][1])
    before: list[tuple[str, object, str | None]] = []
    focus: list[tuple[str, object, str | None]] = []
    after: list[tuple[str, object, str | None]] = []
    for lo, hi, (text, key, name) in spans:
        if key is not None:
            # 필드 조각은 자르지 않는다 — 통째로 앞·가운데·뒤 중 한 곳에 선다.
            side = (focus if id(key) in hit else before if hi <= start else after if lo >= end else focus)
            side.append((text, key, name))
            continue
        before.append((text[:max(0, min(hi, start) - lo)], None, None))
        focus.append((text[max(0, start - lo):max(0, min(hi, end) - lo)], None, None))
        after.append((text[max(0, end - lo):], None, None))
    return occurrence_context_parts(_render_pieces(before), _render_pieces(focus), _render_pieces(after))


def _root_anchor(paragraphs: list, paragraph) -> int | None:
    """가장 가까운 본문 문단(``paragraphs`` 의 원소) 조상 — 문단이 그 자체로 본문이 아닐 때만 쓴다."""
    for ancestor in paragraph.iterancestors(f"{_HP}p"):
        if ancestor in paragraphs:
            return paragraphs.index(ancestor)
    return None


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
            if occurrence.paragraph in paragraphs:
                anchor_paragraph = paragraphs.index(occurrence.paragraph)
                position = {"paragraph": anchor_paragraph, **_simple_field_span(occurrence)}
            else:
                cell_path = _cell_path(root, occurrence.paragraph)
                if cell_path is None:
                    anchor_paragraph = _root_anchor(paragraphs, occurrence.paragraph)
                    position = {"paragraph": None}
                else:
                    anchor_paragraph = cell_path[0]["parent_paragraph"]
                    position = {"paragraph": cell_path[-1]["paragraph"], "cell_path": cell_path,
                                **_simple_field_span(occurrence)}
            grouped[name].append({
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
            })
    return [{"name": name, "count": len(items), "occurrences": items}
            for name, items in grouped.items()]


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
        diagnostics.extend({"kind": str(item.kind), "message": messages.get(str(item.kind), "필드 구조를 확인하세요."),
                            "detail": str(item), "entry": entry, "order": item.order,
                            "severity": SEVERITY_ERROR,
                            "category": (CATEGORY_COMPATIBILITY if str(item.kind) in compatibility
                                         else CATEGORY_STRUCTURE),
                            "target": None, "location": loc, "actions": [navigate_action(loc)]}
                           for item in resolution.diagnostics
                           for loc in (_field_diagnostic_location(
                               nodes[item.order] if 0 <= item.order < len(nodes) else None,
                               entry, paragraphs),))
        diagnostics.extend({"kind": "invalid-field-id", "message": "필드 이름이 비어 있습니다.",
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
                           for loc in (_field_diagnostic_location(occurrence.begin, entry, paragraphs),))
    return diagnostics


def _structure_diagnostic_location(package, context: str) -> dict | None:
    if not context:
        return None
    matches = []
    for entry, root in _roots(package):
        paragraphs = [node for node in root if node.tag == f"{_HP}p"]
        for paragraph in root.iter(f"{_HP}p"):
            # 직속 텍스트만 — 표를 감싼 본문 문단이 셀 문단의 문맥까지 흡수하지 않게 한다.
            body = "".join(child.text or "" for run in paragraph if run.tag == f"{_HP}run"
                           for child in run if child.tag == f"{_HP}t")
            if body.strip()[:CONTEXT_MAX] != context:
                continue
            if paragraph in paragraphs:
                matches.append({"entry": entry, "paragraph": paragraphs.index(paragraph)})
                continue
            cell_path = _cell_path(root, paragraph)
            if cell_path is not None:
                matches.append({"entry": entry, "paragraph": cell_path[-1]["paragraph"],
                                "cell_path": cell_path})
    return matches[0] if len(matches) == 1 else None


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
        "slots": [{"id": slot.id, "label": slot.label or "", "kind": "slot",
                   "location": _region_location(snapshot.slot_regions.get(slot.id)),
                   "raw": _region_raw(snapshot.slot_regions.get(slot.id)),
                   "options": [{"id": option.id, "label": option.label or "",
                                "kind": "option", "slot_id": slot.id,
                                "location": _region_location(snapshot.option_regions.get((slot.id, option.id))),
                                "raw": _region_raw(snapshot.option_regions.get((slot.id, option.id)))}
                               for option in slot.options]} for slot in slots],
        "diagnostics": ([{"kind": item.kind, "message": item.message,
                          "severity": SEVERITY_ERROR, "category": CATEGORY_STRUCTURE,
                          "target": _bookmark_target(item.message), "location": location,
                          "actions": [navigate_action(location)]}
                         for item in diagnostics
                         for location in (_bookmark_location(package, item.message),)] +
                        [item.to_dict() | {"severity": SEVERITY_ERROR, "category": CATEGORY_STRUCTURE,
                                           "target": marker_target(item.context), "location": location,
                                           "actions": [navigate_action(location)]}
                         for item in structure.diagnostics
                         for location in (_structure_diagnostic_position(package, item),)] +
                        _field_diagnostics(package)),
        "summary": {"slots": len(slots),
                    "options": sum(len(slot.options) for slot in slots),
                    "fields": sum(field["count"] for field in fields)},
    }


def _namespaces(root) -> dict:
    return {prefix: uri for prefix, uri in root.nsmap.items() if prefix}


def _token_location(root, entry: str, paragraph, start: int, end: int) -> dict | None:
    """Where one plain-text token sits, in the coordinates the editor navigates with (IDE-05 #1051).

    The token offsets are depth-0 body offsets (``authoring._build_paragraph_model``); they are carried as
    editor offsets only when nothing before the token's end could make them differ (no control, tab or field
    before it, same text). Otherwise the location is the paragraph alone — the position is not guessed.
    """
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    if paragraph in paragraphs:
        location: dict = {"entry": entry, "paragraph": paragraphs.index(paragraph)}
    else:
        cell_path = _cell_path(root, paragraph)
        if cell_path is None:
            anchor = _root_anchor(paragraphs, paragraph)
            return {"entry": entry, "paragraph": anchor} if anchor is not None else None
        location = {"entry": entry, "paragraph": cell_path[-1]["paragraph"], "cell_path": cell_path}
    sites, hazards, text = _paragraph_sites(paragraph)
    model = _authoring._build_paragraph_model(paragraph)[0]
    if (0 <= start < end <= len(text) and sites and not any(position <= end for position in hazards)
            and text[:end] == model[:end]):
        location.update(start=start, end=end)
    return location


def stray_token_problems(content: object) -> list[dict]:
    """Plain-text ``{{이름}}`` that is not a field, one warning per token (IDE-05 #1051).

    The judgment is ``schema.stray_tokens``; its coordinates (``stray_sites``) are the 누름틀 변환 scanner's
    own sites, so the action converts exactly that token through ``authoring.compile_document``. Split
    tokens (``split_token``) are out of scope — they have a name but no convertible site.
    """
    package = require_package(content)
    roots: dict[str, etree._Element] = {}
    problems: list[dict] = []
    for site in extract_schema(package).stray_sites:
        # 자리는 같은 package 를 훑은 스캐너의 것이다 — 구역·문단 경로·offset·이름이 늘 선다(스캐너가 보증).
        root = roots.get(site.entry)
        if root is None:
            root = roots[site.entry] = etree.fromstring(
                package.entries[site.entry], parser=etree.XMLParser(resolve_entities=False))
        found = root.xpath(site.paragraph_path, namespaces=_namespaces(root))
        assert isinstance(found, list) and len(found) == 1 and site.start >= 0
        name = normalize_field_id(site.name) or site.name
        location = _token_location(root, site.entry, found[0], site.start, site.end)
        command = {"type": COMPILE_TOKEN, "entry": site.entry, "paragraph_path": site.paragraph_path,
                   "token_start": site.start, "name": name}
        problems.append({"kind": KIND_STRAY_TOKEN, "severity": SEVERITY_WARNING,
                         "category": CATEGORY_AUTHORING, "message": MESSAGE_STRAY_TOKEN,
                         "target": name, "location": location,
                         "actions": [navigate_action(location), command_action(command, COMPILE_TOKEN_LABEL)]})
    return problems


def _compile_token(package, command: Mapping[str, object]) -> str:
    """One token through the same 누름틀 변환 as the whole document — nothing else changes."""
    entry, path, start = command.get("entry"), command.get("paragraph_path"), command.get("token_start")
    name = normalize_field_id(command.get("name"))
    if not isinstance(entry, str) or not isinstance(path, str) or type(start) is not int or name is None:
        raise ValueError(REASON_FIX_STALE)
    assert isinstance(start, int)
    _, report = _authoring.compile_document(package, only=(entry, path, start))
    if len(report.compiled) != 1 or normalize_field_id(report.compiled[0]) != name:
        raise ValueError(REASON_FIX_STALE)
    return "{{" + report.compiled[0] + "}}"


_BOOKMARK_MESSAGE = re.compile(r"^(?P<entry>[^:]+): BOOKMARK (?P<name>'[^']*'|None)")


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
    begins = [node for node in root.iter(f"{_HP}fieldBegin")
              if node.get("type") == "BOOKMARK" and node.get("name") == name]
    if len(begins) != 1:
        return None
    paragraph = next(begins[0].iterancestors(f"{_HP}p"), None)
    if paragraph is None or paragraph not in paragraphs:
        return None
    return {"entry": entry, "paragraph": paragraphs.index(paragraph)}


def _region_location(region) -> dict | None:
    if region is None:
        return None
    return {"entry": region.section, "start_paragraph": region.start_paragraph,
            "end_paragraph": region.end_paragraph}


def _region_raw(region) -> dict | None:
    if region is None:
        return None
    return {"bookmark_name": region.name, "meta_tags": list(region.meta_tags)}


def search_hwpx(content: object, query: str, kind: str = "text") -> dict:
    """Find body text or field names with native entry/paragraph coordinates."""
    if not isinstance(query, str) or not query:
        raise ValueError("검색어를 입력하세요.")
    if kind not in {"text", "field", "structure"}:
        raise ValueError("검색 종류를 확인하세요.")
    if kind == "field":
        return {"hits": [occurrence | {"kind": "field", "name": field["name"]}
                         for field in analyze_hwpx(content)["fields"]
                         if query.casefold() in field["name"].casefold()
                         for occurrence in field["occurrences"]]}
    if kind == "structure":
        snapshot = inspect_slot_regions(require_package(content))
        hits = []
        for slot in snapshot.slots:
            region = snapshot.slot_regions[slot.id]
            if query.casefold() in (slot.id + " " + (slot.label or "")).casefold():
                hits.append({"kind": "slot", "slot_id": slot.id, "label": slot.label or slot.id,
                             "entry": region.section, "start_paragraph": region.start_paragraph,
                             "end_paragraph": region.end_paragraph})
            for option in slot.options:
                region = snapshot.option_regions[(slot.id, option.id)]
                if query.casefold() in (option.id + " " + (option.label or "")).casefold():
                    hits.append({"kind": "option", "slot_id": slot.id, "option_id": option.id,
                                 "label": option.label or option.id, "entry": region.section,
                                 "start_paragraph": region.start_paragraph,
                                 "end_paragraph": region.end_paragraph})
        return {"hits": hits}
    hits = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    for entry, root in _roots(require_package(content)):
        paragraphs = [node for node in root if node.tag == f"{_HP}p"]
        marks = _field_marks(entry, root)
        for paragraph in root.iter(f"{_HP}p"):
            position = _paragraph_position(root, paragraphs, paragraph)
            body = _paragraph_body(paragraph)
            path = root.getroottree().getpath(paragraph)
            seen: set[str] = set()
            for match in pattern.finditer(body):
                context = _body_hit_context(_paragraph_pieces(paragraph, marks), match.start(), match.end())
                # 같은 문단에서 보이는 줄이 같은 결과(예: 「수요기관:」 글자와 필드 값 「{{수요기관}}」 — 필드 값 안의
                # 일치는 필드 전체를 표지로 보인다)는 사용자가 구별할 수 없는 한 자리다. 첫 일치 하나로 합친다(UX-10 R4).
                if context in seen:
                    continue
                seen.add(context)
                hits.append({"entry": entry, **position,
                             "paragraph_path": path,
                             "start": match.start(), "end": match.end(),
                             "kind": "text",
                             "context": context})
    return {"hits": hits}


def _paragraph_position(root, paragraphs: list, paragraph) -> dict:
    """검색 결과의 문단 좌표 — 본문 문단 번호, 셀 문단이면 셀 안 번호와 셀 경로, 그 밖은 번호 없음."""
    if paragraph in paragraphs:
        return {"paragraph": paragraphs.index(paragraph)}
    cell_path = _cell_path(root, paragraph)
    return ({"paragraph": None} if cell_path is None
            else {"paragraph": cell_path[-1]["paragraph"], "cell_path": cell_path})


def _paragraph_body(paragraph) -> str:
    """본문 검색의 글자 — 문단 바로 아래 ``hp:run`` 의 ``hp:t`` 글자."""
    return "".join(child.text or "" for run in paragraph if run.tag == f"{_HP}run"
                   for child in run if child.tag == f"{_HP}t")


def same_text_hwpx(content: object, selection: Mapping[str, object]) -> list[dict]:
    """고른 문구와 같은 본문 자리 전부(IDE-07 P-07) — 검색의 「같은 문맥은 한 건」 병합 없이 원시 자리다.

    자리 좌표는 검색 결과와 같은 모양(``entry``·문단·셀 경로·``paragraph_path``·``start/end``)이고, 고른 자리와 겹치는
    자리는 뺀다. 자리마다 ``enabled/reason`` 은 그 자리를 범위로 한 ``create_field`` 판정(``_paragraph_sites`` ·
    ``_field_range_refusal``)이다 — 필드 값·제어 요소 뒤의 자리는 흐린 채 사유와 함께 남는다. ``anchor`` 는 위치 줄의
    본문 문단 번호(셀이면 표를 품은 문단)다. 고른 문구가 없거나 공백뿐이면 빈 목록이다.
    """
    package = require_package(content)
    found = selected_context_hwpx(package, selection)
    if found is None or not found[1].strip():
        return []
    phrase = found[1]
    first = selection.get("start_paragraph", selection.get("paragraph"))
    chosen_start, chosen_end = selection["start"], selection["end"]
    assert isinstance(chosen_start, int) and isinstance(chosen_end, int)
    hits: list[dict] = []
    for entry, root in _roots(package):
        chosen = (_selected_paragraph(root, first, selection.get("cell_path"))
                  if entry == selection.get("entry") else None)
        paragraphs = [node for node in root if node.tag == f"{_HP}p"]
        marks = _field_marks(entry, root)
        for paragraph in root.iter(f"{_HP}p"):
            position = _paragraph_position(root, paragraphs, paragraph)
            path = root.getroottree().getpath(paragraph)
            anchor = (paragraphs.index(paragraph) if paragraph in paragraphs
                      else _root_anchor(paragraphs, paragraph))
            for match in re.finditer(re.escape(phrase), _paragraph_body(paragraph)):
                start, end = match.span()
                if paragraph is chosen and start < chosen_end and chosen_start < end:
                    continue
                parts = _body_hit_parts(_paragraph_pieces(paragraph, marks), start, end)
                # 편집기가 가리킬 수 없는 문단(글상자 등 — 번호 없음)의 자리는 흐린 채 그 사유로 남는다.
                reason = (_PARAGRAPH_UNRESOLVED if position["paragraph"] is None
                          else _field_range_refusal(*_paragraph_sites(paragraph), start, end))
                hits.append({"location": {"entry": entry, **position, "paragraph_path": path,
                                          "start": start, "end": end},
                             "anchor": anchor, "context": "".join(parts), "focus": context_focus(parts),
                             "enabled": reason is None, "reason": reason})
    return hits


def _require_clean(package) -> None:
    _slots, diagnostics = inspect_slots(package)
    if diagnostics:
        raise ValueError("문서 구조 오류를 먼저 수정하세요.")


def _field_name(raw: object) -> str:
    name = normalize_field_id(raw)
    if name is None or "{{" in name or "}}" in name or name.startswith(("#", "/")):
        raise InvalidName("name", INVALID_FIELD_NAME)
    return name


_MULTI_PARAGRAPH_FIELD = "여러 문단에 걸친 필드는 HWPX 누름틀 경계로 만들 수 없습니다."
_COMPLEX_FIELD = "이 필드에는 복합 요소가 있어 내용 보존을 확인할 수 없습니다."
#: 편집기 좌표로 가리킬 수 없는 문단(글상자 등) — 셀 경로도 본문 번호도 없다.
_PARAGRAPH_UNRESOLVED = "고른 문단의 위치를 확정할 수 없습니다."


def _paragraph_sites(paragraph) -> tuple[list[tuple[etree._Element, int, int]], list[int], str]:
    """Plain text sites of one paragraph, control hazards by offset, and the joined text."""
    sites: list[tuple[etree._Element, int, int]] = []
    hazards: list[int] = []
    length = 0
    for run in (node for node in paragraph if node.tag == f"{_HP}run"):
        for child in run:
            if child.tag == f"{_HP}t" and not len(child):
                next_length = length + len(child.text or "")
                sites.append((child, length, next_length))
                length = next_length
            else:
                hazards.append(length)
    return sites, hazards, "".join(node.text or "" for node, _, _ in sites)


def _field_range_refusal(sites: list, hazards: list[int], text: str, start: int, end: int) -> str | None:
    if not 0 <= start <= end <= len(text):
        return "고른 문자 범위가 문단 밖에 있습니다."
    if not sites:
        return "이 문단에는 편집 가능한 텍스트가 없습니다."
    if any(position <= end for position in hazards):
        return "고른 범위 앞이나 안에 제어 요소가 있어 문자 위치를 확정할 수 없습니다."
    return None


def _selected_paragraph(root, paragraph_index: object, cell_path: object):
    """본문 문단 번호, 또는 rhwp 커서 경로(cell_path)로 가리킨 셀 문단 하나."""
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    if isinstance(cell_path, list):
        # rhwp 커서 경로로 셀 문단을 확정한다 — 같은 규칙(_cell_path)으로 되읽어 일치하는
        # 문단만 인정하므로 analyze_hwpx 가 보고하는 좌표와 어긋날 수 없다.
        if not cell_path or not all(
            isinstance(step, dict) and set(step) == _CELL_PATH_KEYS
            and all(type(value) is int and value >= 0 for value in step.values())
            for step in cell_path
        ) or paragraph_index != cell_path[-1]["paragraph"]:
            raise ValueError(_PARAGRAPH_UNRESOLVED)
        owner_index = cell_path[0]["parent_paragraph"]
        candidates = ([node for node in paragraphs[owner_index].iter(f"{_HP}p")
                       if _cell_path(root, node) == cell_path]
                      if owner_index < len(paragraphs) else [])
        if len(candidates) != 1:
            raise ValueError(_PARAGRAPH_UNRESOLVED)
        return candidates[0]
    if not isinstance(paragraph_index, int) or not 0 <= paragraph_index < len(paragraphs):
        raise ValueError("고른 문단이 문서 영역 밖에 있습니다.")
    return paragraphs[paragraph_index]


def selected_context_hwpx(content: object, selection: Mapping[str, object]) -> tuple[str, str] | None:
    """선택 앞 글자와 선택한 문구(UX-10 R2·P-06) — 같은 문단(셀)의 결합 텍스트(``_paragraph_sites``)에서 자른다.

    한 문단 안의 문자 범위를 필드 만들기와 같은 규칙으로 읽는다. 문단을 넘거나, 빈 범위이거나, 제어 요소가
    끼어 문자 위치를 확정할 수 없으면 None 이다(짐작하지 않는다).
    """
    package = require_package(content)
    entry = selection.get("entry")
    first = selection.get("start_paragraph", selection.get("paragraph"))
    last = selection.get("end_paragraph", first)
    start, end = selection.get("start"), selection.get("end")
    if (not isinstance(entry, str) or entry not in package.entries
            or any(type(value) is not int or value < 0 for value in (first, last, start, end))
            or first != last):
        return None
    assert isinstance(start, int) and isinstance(end, int)
    if end <= start:
        return None
    root = etree.fromstring(package.entries[entry], parser=etree.XMLParser(resolve_entities=False))
    try:
        paragraph = _selected_paragraph(root, first, selection.get("cell_path"))
    except ValueError:
        return None
    sites, hazards, text = _paragraph_sites(paragraph)
    if _field_range_refusal(sites, hazards, text, start, end) is not None:
        return None
    return text[:start], text[start:end]


def _field_paragraph(package, roots: dict, site: Mapping[str, object]) -> tuple[str, etree._Element, int, int]:
    """한 필드 자리의 문단 — 문단 경로(``paragraph_path``), 또는 본문 문단 번호와 셀 경로(``cell_path``)."""
    entry = site.get("entry")
    if not isinstance(entry, str) or entry not in package.entries:
        raise ValueError("HWPX 문서 영역을 찾을 수 없습니다.")
    start, end = site.get("start"), site.get("end")
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in (start, end)):
        raise ValueError("문단 안의 정확한 문자 범위를 고르세요.")
    assert isinstance(start, int) and isinstance(end, int)
    if entry not in roots:
        roots[entry] = etree.fromstring(package.entries[entry])
    root = roots[entry]
    paragraph_index = site.get("paragraph")
    paragraph_path = site.get("paragraph_path")
    if isinstance(paragraph_path, str):
        paragraphs = root.xpath(paragraph_path, namespaces=root.nsmap)
        if len(paragraphs) != 1 or paragraphs[0].tag != f"{_HP}p":
            raise ValueError(_PARAGRAPH_UNRESOLVED)
        paragraph = paragraphs[0]
    else:
        paragraph = _selected_paragraph(root, paragraph_index, site.get("cell_path"))
    if site.get("end_paragraph", paragraph_index) != paragraph_index:
        raise ValueError(_MULTI_PARAGRAPH_FIELD)
    return entry, paragraph, start, end


def _field_ranges(command: Mapping[str, object]) -> list[Mapping[str, object]]:
    """``create_field`` 의 자리 목록 — ``ranges`` 가 없으면 고른 자리 하나다."""
    ranges = command.get("ranges")
    if ranges is None:
        return [command]
    if not isinstance(ranges, list) or not all(isinstance(item, Mapping) for item in ranges):
        raise ValueError(REASON_INVALID_SELECTION)
    return ranges


def _create_field(package, command: Mapping[str, object]) -> str:
    """고른 자리(와 ``ranges`` 의 자리들, IDE-07 P-07)에 같은 이름의 누름틀을 한 패키지 변형으로 끼운다.

    ``ranges`` 는 고른 자리를 포함한 자리 전부다. 자리마다 판정(제어 요소·문단 밖)은 **바꾸기 전** 문서에서 하고,
    같은 문단의 자리는 뒤에서부터 끼우며 끼울 때마다 문단 글자 자리를 다시 센다(앞 자리의 offset 은 밀리지 않는다).
    """
    roots: dict = {}
    primary = _field_paragraph(package, roots, command)
    sites = [_field_paragraph(package, roots, item) for item in _field_ranges(command)]
    if primary not in sites:
        raise ValueError(REASON_INVALID_SELECTION)
    captured = _paragraph_sites(primary[1])[2][primary[2]:primary[3]]
    for index, (_entry, paragraph, start, end) in enumerate(sites):
        text_sites, hazards, text = _paragraph_sites(paragraph)
        refusal = _field_range_refusal(text_sites, hazards, text, start, end)
        if refusal is not None:
            raise ValueError(refusal)
        # 같은 문구 N곳이다 — 다른 글자의 자리(옛 좌표)는 짐작해 끼우지 않는다.
        if text[start:end] != captured:
            raise ValueError(REASON_INVALID_SELECTION)
        if any(other is paragraph and (lo < end and start < hi or (lo, hi) == (start, end))
               for _e, other, lo, hi in sites[index + 1:]):
            raise ValueError(REASON_FIELD_OVERLAP)
    name = _field_name(command.get("name"))
    allocators = {entry: _authoring._make_id_allocator(root) for entry, root in roots.items()}
    for entry, paragraph, start, end in sorted(sites, key=lambda site: -site[2]):
        sites_now = _paragraph_sites(paragraph)[0]
        begin_id, field_id = allocators[entry]()
        begin_site = next((node for node, lo, hi in sites_now if lo <= start < hi), sites_now[-1][0])
        end_site = next((node for node, lo, hi in sites_now if lo < end <= hi), sites_now[0][0])
        begin_ctrl = _authoring._begin_run(dict(begin_site.getparent().attrib), name,
                                           begin_id, field_id)[0]
        end_ctrl = _authoring._end_run(dict(end_site.getparent().attrib), begin_id,
                                       field_id)[0]
        if start == end == 0:
            _insert_field_boundary(sites_now, start, begin_ctrl, beginning=True)
            _insert_field_boundary(sites_now, end, end_ctrl, beginning=False)
        else:
            _insert_field_boundary(sites_now, end, end_ctrl, beginning=False)
            _insert_field_boundary(sites_now, start, begin_ctrl, beginning=True)
    for entry, root in roots.items():
        resolve_field_occurrences(entry, root).require_usable()
        package.entries[entry] = serialize_modified_section(root)
    return captured


def _insert_field_boundary(
    sites: list[tuple[etree._Element, int, int]],
    offset: int,
    control: etree._Element,
    *,
    beginning: bool,
) -> None:
    if beginning:
        site = next(((node, lo, hi) for node, lo, hi in sites if lo <= offset < hi), sites[-1])
    else:
        site = next(((node, lo, hi) for node, lo, hi in sites if lo < offset <= hi), sites[0])
    node, lo, _hi = site
    run = node.getparent()
    assert run is not None
    index = run.index(node)
    inner = offset - lo
    value = node.text or ""
    if inner == 0:
        run.insert(index, control)
    elif inner == len(value):
        run.insert(index + 1, control)
    else:
        suffix = copy.deepcopy(node)
        suffix.text = value[inner:]
        suffix.tail = node.tail
        node.text = value[:inner]
        node.tail = None
        run.insert(index + 1, control)
        run.insert(index + 2, suffix)


def _field_occurrence(root, entry: str, ordinal: object, pairing_id: object = None):
    if not isinstance(ordinal, int) or ordinal < 0:
        raise ValueError("필드 사용 위치가 올바르지 않습니다.")
    occurrences = resolve_field_occurrences(entry, root).require_usable()
    if ordinal >= len(occurrences):
        raise ValueError("필드 사용 위치를 찾을 수 없습니다.")
    target = occurrences[ordinal]
    if pairing_id is not None and target.begin.get("id") != pairing_id:
        raise ValueError("고른 필드 사용 위치가 바뀌었습니다. 다시 고르세요.")
    if not is_fill_target_field_type(target.field_type):
        raise ValueError("고른 요소는 채울 수 있는 필드가 아닙니다.")
    return target


def _change_field(package, command: Mapping[str, object]) -> int:
    action = command["type"]
    whole = whole_field_unset(command)
    old = _field_name(command.get("old_name")) if action == "rename_field" or whole else None
    new = _field_name(command.get("name")) if action in {"rename_field", "relink_field"} else None
    if action == "rename_field" and new != old:
        taken = next((item["count"] for item in _fields(package) if item["name"] == new), 0)
        if taken:
            assert isinstance(new, str)
            raise NameConflict(new, taken)
    if whole:
        # 필드 전체의 의미 해제(P-20)는 전부 아니면 전무다 — 한 자리라도 복합 요소면 아무 자리도 고치지 않는다.
        for entry, root in _roots(package):
            for item in resolve_field_occurrences(entry, root).require_usable():
                if (is_fill_target_field_type(item.field_type) and normalize_field_id(item.raw_name) == old
                        and (not item.texts or any(len(node) for node in item.texts))):
                    raise ValueError(_COMPLEX_FIELD)
    count = 0
    for entry, root in _roots(package):
        if action == "rename_field" or whole:
            targets = [item for item in resolve_field_occurrences(entry, root).require_usable()
                       if is_fill_target_field_type(item.field_type)
                       and normalize_field_id(item.raw_name) == old]
        elif entry == command.get("entry"):
            targets = [_field_occurrence(root, entry, command.get("occurrence"), command.get("pairing_id"))]
        else:
            targets = []
        for target in targets:
            if action == "unset_field":
                replacement = command.get("text")
                if not isinstance(replacement, str):
                    raise ValueError("의미를 해제한 뒤 남길 본문을 입력하세요.")
                if not target.texts or any(len(node) for node in target.texts):
                    raise ValueError(_COMPLEX_FIELD)
                target.texts[0].text = replacement
                for node in target.texts[1:]:
                    node.text = ""
                target.begin_ctrl.getparent().remove(target.begin_ctrl)
                target.end_ctrl.getparent().remove(target.end_ctrl)
            else:
                target.begin.set("name", new)
            count += 1
        if targets:
            resolve_field_occurrences(entry, root).require_usable()
            package.entries[entry] = serialize_modified_section(root)
    if not count:
        raise ValueError("필드를 찾을 수 없습니다.")
    return count


def _rename_region(package, command: Mapping[str, object]) -> None:
    snapshot = inspect_slot_regions(package)
    if snapshot.diagnostics:
        raise ValueError("문서 구조 오류를 먼저 수정하세요.")
    kind = "option" if command.get("type") == "rename_option" else "slot"
    slot_id = command.get("slot_id")
    option_id = command.get("option_id")
    if not isinstance(slot_id, str) or (kind == "option" and not isinstance(option_id, str)):
        raise ValueError("항목이나 선택의 식별자가 필요합니다.")
    if kind == "option":
        assert isinstance(option_id, str)
        region = snapshot.option_regions.get((slot_id, option_id))
    else:
        region = snapshot.slot_regions.get(slot_id)
    if region is None:
        raise ValueError("항목이나 선택 영역을 찾을 수 없습니다.")
    identifier = command.get("id", option_id if kind == "option" else slot_id)
    label = command.get("label")
    if not isinstance(identifier, str) or not identifier.strip():
        # 식별자 칸의 거절(P-06) — 원문 표기로 되쓸 수 없는 식별자는 책갈피 메타가 정본이라 받는다(구문 보기가 생략).
        raise InvalidName("identifier", REASON_NEED_NEW_IDENTIFIER)
    if label is not None and not isinstance(label, str):
        raise ValueError("표시 이름은 텍스트여야 합니다.")
    if kind == "slot":
        if identifier != slot_id and identifier in snapshot.slot_regions:
            raise ValueError("항목 식별자가 이미 있습니다.")
        previous_slot = next(slot for slot in snapshot.slots if slot.id == slot_id)
        payload = serialize_slot_metatag(Slot(identifier, previous_slot.options,
                                               previous_slot.label if "label" not in command else label))
    else:
        if identifier != option_id and (slot_id, identifier) in snapshot.option_regions:
            raise ValueError("같은 항목에 해당 선택 식별자가 이미 있습니다.")
        previous_option = next(option for slot in snapshot.slots if slot.id == slot_id
                               for option in slot.options if option.id == option_id)
        payload = serialize_slot_option_metatag(SlotOption(identifier, previous_option.order,
                                                          previous_option.label if "label" not in command else label))
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    root = etree.fromstring(package.entries[region.section], parser=parser)
    begins = [node for node in root.iter(f"{_HP}fieldBegin")
              if node.get("id") == region._pairing_id and node.get("type") == "BOOKMARK"]
    assert len(begins) == 1
    begin = begins[0]
    tags = [node for node in begin if node.tag == f"{_HP}metaTag"]
    product = [node for node in tags if isinstance(node.text, str)
               and _is_product_tag(node.text)]
    if len(product) != 1:
        raise ValueError("템플릿 메타데이터를 하나로 확정할 수 없습니다.")
    product[0].text = payload
    begin.set("name", structure_region_name(identifier if kind == "slot" else str(slot_id),
                                            identifier if kind == "option" else None))
    if kind == "slot" and identifier != slot_id:
        for option in previous_slot.options:
            old_name = structure_region_name(str(slot_id), option.id)
            option_begins = [node for node in root.iter(f"{_HP}fieldBegin")
                             if node.get("type") == "BOOKMARK" and node.get("name") == old_name]
            if len(option_begins) != 1:
                raise ValueError("하위 선택 책갈피를 하나로 확정할 수 없습니다.")
            option_begins[0].set("name", structure_region_name(identifier, option.id))
    package.entries[region.section] = serialize_modified_section(root)
    resolve_bookmark_topology(package)


def _is_product_tag(raw: str) -> bool:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and "hwpxFiller" in payload


def _adjust_region(package, command: Mapping[str, object]) -> None:
    snapshot = inspect_slot_regions(package)
    if snapshot.diagnostics:
        raise ValueError("문서 구조 오류를 먼저 수정하세요.")
    kind = command.get("kind", "slot")
    slot_id = command.get("slot_id")
    option_id = command.get("option_id")
    if not isinstance(slot_id, str):
        raise ValueError("항목 식별자가 필요합니다.")
    if kind == "option":
        if not isinstance(option_id, str):
            raise ValueError("선택 식별자가 필요합니다.")
        region = snapshot.option_regions.get((slot_id, option_id))
    else:
        region = snapshot.slot_regions.get(slot_id)
    if region is None:
        raise ValueError("항목이나 선택 영역을 찾을 수 없습니다.")
    start, end = command.get("start_paragraph"), command.get("end_paragraph")
    if not isinstance(start, int) or not isinstance(end, int) or start > end:
        raise ValueError("문단 범위를 정확히 고르세요.")
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    root = etree.fromstring(package.entries[region.section], parser=parser)
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    if start < 0 or end >= len(paragraphs):
        raise ValueError("고른 문단 범위가 문서 영역 밖에 있습니다.")
    if kind == "option":
        owner = snapshot.slot_regions[slot_id]
        if not owner.start_paragraph <= start <= end <= owner.end_paragraph:
            raise ValueError("고른 범위는 상위 항목 안에 있어야 합니다.")
    else:
        children = [item for (owner_id, _), item in snapshot.option_regions.items()
                    if owner_id == slot_id]
        if any(not start <= item.start_paragraph <= item.end_paragraph <= end
               for item in children):
            raise ValueError("조정한 항목 범위에서 하위 선택이 벗어납니다.")
    begin = [node for node in root.iter(f"{_HP}fieldBegin")
             if node.get("id") == region._pairing_id and node.get("type") == "BOOKMARK"]
    finish = [node for node in root.iter(f"{_HP}fieldEnd")
              if node.get("beginIDRef") == region._pairing_id]
    assert len(begin) == 1 and len(finish) == 1
    begin_ctrl, end_ctrl = begin[0].getparent(), finish[0].getparent()
    assert begin_ctrl is not None and end_ctrl is not None
    begin_ctrl.getparent().remove(begin_ctrl)
    end_ctrl.getparent().remove(end_ctrl)
    start_runs = [node for node in paragraphs[start] if node.tag == f"{_HP}run"]
    end_runs = [node for node in paragraphs[end] if node.tag == f"{_HP}run"]
    if not start_runs or not end_runs:
        raise ValueError("경계 문단에 편집 가능한 텍스트 런이 없습니다.")
    if kind == "option" and start == owner.start_paragraph:
        parent_begin = next(node for node in root.iter(f"{_HP}fieldBegin")
                            if node.get("id") == owner._pairing_id)
        parent_ctrl = parent_begin.getparent()
        assert parent_ctrl is not None
        parent_ctrl.getparent().insert(parent_ctrl.getparent().index(parent_ctrl) + 1, begin_ctrl)
    else:
        start_runs[0].insert(0, begin_ctrl)
    if kind == "option" and end == owner.end_paragraph:
        parent_end = next(node for node in root.iter(f"{_HP}fieldEnd")
                          if node.get("beginIDRef") == owner._pairing_id)
        parent_ctrl = parent_end.getparent()
        assert parent_ctrl is not None
        parent_ctrl.getparent().insert(parent_ctrl.getparent().index(parent_ctrl), end_ctrl)
    else:
        end_runs[-1].append(end_ctrl)
    package.entries[region.section] = serialize_modified_section(root)
    resolve_bookmark_topology(package)


def _block_region(
    package, command: Mapping[str, object]
) -> tuple[BookmarkRegion, etree._Element, list[etree._Element], list[etree._Element]]:
    snapshot = inspect_slot_regions(package)
    if snapshot.diagnostics:
        raise ValueError("구조 오류가 있어 영역을 변경할 수 없습니다.")
    kind = command.get("kind", "slot")
    slot_id = command.get("slot_id")
    option_id = command.get("option_id")
    if not isinstance(slot_id, str):
        raise ValueError("항목 식별자가 필요합니다.")
    if kind == "option":
        if not isinstance(option_id, str):
            raise ValueError("선택 식별자가 필요합니다.")
        region = snapshot.option_regions.get((slot_id, option_id))
    else:
        region = snapshot.slot_regions.get(slot_id)
    if region is None:
        raise ValueError("영역을 찾을 수 없습니다.")
    root = etree.fromstring(package.entries[region.section],
                            parser=etree.XMLParser(remove_blank_text=False, resolve_entities=False))
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    return region, root, paragraphs, paragraphs[region.start_paragraph:region.end_paragraph + 1]


def _boundary_ids(paragraphs: list) -> tuple[set[str], set[str]]:
    begins = {node.get("id") for paragraph in paragraphs
              for node in paragraph.iter(f"{_HP}fieldBegin") if node.get("id")}
    ends = {node.get("beginIDRef") for paragraph in paragraphs
            for node in paragraph.iter(f"{_HP}fieldEnd") if node.get("beginIDRef")}
    return begins, ends


def _native_identity(package) -> dict:
    return {(region.section, region._pairing_id):
            (region.name, region.meta_tags,
             None if region.parent is None else region.parent._pairing_id)
            for region in resolve_bookmark_topology(package)}


def _insertion_index(root, paragraphs: list, destination: int) -> int:
    if destination < len(paragraphs):
        return root.index(paragraphs[destination])
    return root.index(paragraphs[-1]) + 1


def _move_region(package, command: Mapping[str, object]) -> None:
    region, root, paragraphs, block = _block_region(package, command)
    if command.get("destination_entry", region.section) != region.section:
        raise ValueError("다른 문서 영역으로는 이동할 수 없습니다.")
    if command.get("start", 0) != 0:
        raise ValueError("이동할 위치를 문단 시작에 놓으세요.")
    destination = command.get("destination_paragraph")
    if not isinstance(destination, int) or not 0 <= destination <= len(paragraphs):
        raise ValueError("이동할 문단 경계가 올바르지 않습니다.")
    lo, hi = region.start_paragraph, region.end_paragraph + 1
    if lo <= destination <= hi:
        raise ValueError("현재 영역 안으로 이동할 수 없습니다.")
    begins, ends = _boundary_ids(block)
    if begins != ends:
        raise ValueError("다른 영역이나 필드 경계가 걸친 문단은 이동할 수 없습니다.")
    before_identity = _native_identity(package)
    for paragraph in block:
        root.remove(paragraph)
    remaining = [node for node in root if node.tag == f"{_HP}p"]
    adjusted = destination if destination < lo else destination - len(block)
    insertion = _insertion_index(root, remaining, adjusted)
    for index, paragraph in enumerate(block):
        root.insert(insertion + index, paragraph)
    package.entries[region.section] = serialize_modified_section(root)
    if _native_identity(package) != before_identity:
        raise ValueError("이동하면 기존 책갈피 소속이 달라집니다.")


def _cloneable_paragraphs(block: list) -> None:
    for paragraph in block:
        for child in paragraph:
            if child.tag == f"{_HP}lineSegArray":
                continue
            if child.tag != f"{_HP}run":
                raise ValueError("이 영역에 복제할 수 없는 문서 요소가 있습니다.")
            for item in child:
                if item.tag == f"{_HP}t" and not len(item):
                    continue
                if item.tag != f"{_HP}ctrl" or len(item) != 1:
                    raise ValueError("이 영역에 복제할 수 없는 제어 요소가 있습니다.")
                field = item[0]
                if field.tag not in {f"{_HP}fieldBegin", f"{_HP}fieldEnd"}:
                    raise ValueError("이 영역에 복제할 수 없는 제어 요소가 있습니다.")
                if field.tag == f"{_HP}fieldBegin" and any(
                    node.tag != f"{_HP}metaTag" for node in field
                ):
                    raise ValueError("알 수 없는 필드 메타데이터는 복제할 수 없습니다.")


def _next_native_id(package) -> int:
    maximum = 0
    for entry, raw in package.entries.items():
        if not entry.lower().endswith(".xml"):
            continue
        root = etree.fromstring(raw, parser=etree.XMLParser(remove_blank_text=False,
                                                           resolve_entities=False))
        for element in root.iter():
            for attribute in ("id", "fieldid"):
                value = element.get(attribute)
                if value and value.isdecimal():
                    maximum = max(maximum, int(value))
    return maximum + 1


def _duplicate_region(package, command: Mapping[str, object]) -> None:
    region, root, paragraphs, block = _block_region(package, command)
    if command.get("destination_entry", region.section) != region.section:
        raise ValueError("다른 문서 영역으로는 복제할 수 없습니다.")
    if command.get("start", 0) != 0:
        raise ValueError("복제할 위치를 문단 시작에 놓으세요.")
    new_id = command.get("new_id")
    destination = command.get("destination_paragraph", region.end_paragraph + 1)
    if not isinstance(new_id, str) or not new_id.strip():
        raise ValueError("복제할 영역의 새 식별자가 필요합니다.")
    if not isinstance(destination, int) or not 0 <= destination <= len(paragraphs):
        raise ValueError("복제할 문단 경계가 올바르지 않습니다.")
    snapshot = inspect_slot_regions(package)
    if command.get("kind", "slot") == "option":
        slot_id = command.get("slot_id")
        assert isinstance(slot_id, str)
        owner = snapshot.slot_regions[slot_id]
        if not owner.start_paragraph <= destination <= owner.end_paragraph + 1:
            raise ValueError("복제한 선택은 같은 항목 안에 놓아야 합니다.")
        if (slot_id, new_id) in snapshot.option_regions:
            raise ValueError("같은 이름의 선택이 이미 있습니다.")
    elif new_id in snapshot.slot_regions:
        raise ValueError("같은 이름의 항목이 이미 있습니다.")
    _cloneable_paragraphs(block)
    begins, ends = _boundary_ids(block)
    internal = begins & ends
    if region._pairing_id not in internal:
        raise ValueError("영역 경계를 문단 단위로 복제할 수 없습니다.")
    for paragraph in block:
        for node in paragraph.iter(f"{_HP}fieldBegin"):
            if node.get("id") not in internal and node.get("type") != "BOOKMARK":
                raise ValueError("문단을 가로지르는 필드는 복제할 수 없습니다.")
        for node in paragraph.iter(f"{_HP}fieldEnd"):
            if node.get("beginIDRef") not in internal:
                # 외부 BOOKMARK 경계는 clone에서만 제거한다. 그 외는 짝이 없는 필드다.
                if not any(item._pairing_id == node.get("beginIDRef")
                           for item in resolve_bookmark_topology(package)):
                    raise ValueError("문단을 가로지르는 필드는 복제할 수 없습니다.")
    clones = [copy.deepcopy(paragraph) for paragraph in block]
    for paragraph in clones:
        for field in list(paragraph.iter(f"{_HP}fieldBegin")) + list(paragraph.iter(f"{_HP}fieldEnd")):
            key = field.get("id") if field.tag == f"{_HP}fieldBegin" else field.get("beginIDRef")
            if key in internal:
                continue
            ctrl = field.getparent()
            assert ctrl is not None
            ctrl.getparent().remove(ctrl)
    id_map: dict[str, str] = {}
    next_id = _next_native_id(package)
    for paragraph in clones:
        for element in paragraph.iter():
            for attribute in ("id", "fieldid"):
                old = element.get(attribute)
                if old is not None and old not in id_map:
                    id_map[old] = str(next_id)
                    next_id += 1
    for paragraph in clones:
        for element in paragraph.iter():
            for attribute in ("id", "fieldid", "beginIDRef", "endIDRef"):
                old = element.get(attribute)
                if old in id_map:
                    element.set(attribute, id_map[old])
            if element.tag != f"{_HP}fieldBegin" or element.get("type") != "BOOKMARK":
                continue
            original_pairing = next((old for old, new in id_map.items()
                                     if new == element.get("id")), None)
            if original_pairing == region._pairing_id:
                element.set("name", structure_region_name(
                    new_id if command.get("kind", "slot") == "slot" else str(command.get("slot_id")),
                    new_id if command.get("kind", "slot") == "option" else None))
                for tag in element.iter(f"{_HP}metaTag"):
                    if tag.text and _is_product_tag(tag.text):
                        payload = json.loads(tag.text)
                        payload["hwpxFiller"]["id"] = new_id
                        tag.text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            elif command.get("kind", "slot") == "slot":
                prefix = str(command.get("slot_id")) + "/"
                if (element.get("name") or "").startswith(prefix):
                    element.set("name", structure_region_name(new_id, (element.get("name") or "")[len(prefix):]))
    if command.get("kind", "slot") == "option" and destination == owner.end_paragraph + 1:
        parent_end = next(node for node in root.iter(f"{_HP}fieldEnd")
                          if node.get("beginIDRef") == owner._pairing_id)
        parent_ctrl = parent_end.getparent()
        assert parent_ctrl is not None
        parent_ctrl.getparent().remove(parent_ctrl)
        last_runs = [node for node in clones[-1] if node.tag == f"{_HP}run"]
        last_runs[-1].append(parent_ctrl)
    elif command.get("kind", "slot") == "option" and destination == owner.start_paragraph:
        parent_begin = next(node for node in root.iter(f"{_HP}fieldBegin")
                            if node.get("id") == owner._pairing_id)
        parent_ctrl = parent_begin.getparent()
        assert parent_ctrl is not None
        parent_ctrl.getparent().remove(parent_ctrl)
        first_runs = [node for node in clones[0] if node.tag == f"{_HP}run"]
        first_runs[0].insert(0, parent_ctrl)
    insertion = _insertion_index(root, paragraphs, destination)
    for index, paragraph in enumerate(clones):
        root.insert(insertion + index, paragraph)
    package.entries[region.section] = serialize_modified_section(root)
    resolve_bookmark_topology(package)


def _create_region(package, command: Mapping[str, object]) -> None:
    _require_clean(package)
    kind = "option" if command["type"] == "create_option" else "slot"
    identifier = command.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise InvalidName("identifier", REASON_NEED_IDENTIFIER)
    label = command.get("label")
    if label is not None and not isinstance(label, str):
        raise ValueError("표시 이름은 텍스트여야 합니다.")
    entry = command.get("entry")
    start, end = command.get("start_paragraph"), command.get("end_paragraph")
    if not isinstance(entry, str) or not isinstance(start, int) or not isinstance(end, int):
        raise ValueError("문단 범위를 정확히 고르세요.")
    snapshot = inspect_slot_regions(package)
    owner = command.get("slot_id")
    if kind == "slot":
        if identifier in snapshot.slot_regions:
            raise ValueError("항목 식별자가 이미 있습니다.")
        parent = None
        payload = serialize_slot_metatag(Slot(identifier, (), label))
    else:
        if not isinstance(owner, str) or owner not in snapshot.slot_regions:
            raise ValueError("선택을 만들 상위 항목이 필요합니다.")
        if (owner, identifier) in snapshot.option_regions:
            raise ValueError("같은 항목에 해당 선택 식별자가 이미 있습니다.")
        parent = snapshot.slot_regions[owner]
        order = len(next(slot.options for slot in snapshot.slots if slot.id == owner))
        payload = serialize_slot_option_metatag(SlotOption(identifier, order, label))
    if kind == "slot":
        region_name = structure_region_name(identifier)
    else:
        assert isinstance(owner, str)
        region_name = structure_region_name(owner, identifier)
    region = create_bookmark_region(
        package, entry, start, end,
        name=region_name,
        parent=parent,
    )
    append_bookmark_metatag(package, region, payload)


def apply_hwpx(content: object, command: Mapping[str, object]) -> tuple[object, dict]:
    """Mutate an opened disposable package atomically; return an impact projection."""
    return _execute(require_package(content), command, projecting=False)


def _unwrap_slot_options(package, slot_id: str) -> None:
    """Unwrap every option of ``slot_id`` innermost-first, re-reading regions after each step."""
    while True:
        snapshot = inspect_slot_regions(package)
        remaining = sorted((region for (owner, _), region in snapshot.option_regions.items()
                            if owner == slot_id), key=lambda region: -region.start_paragraph)
        if not remaining:
            return
        unwrap_bookmark_region(package, remaining[0])


def _prior_field_name(fields: list[dict], command: Mapping[str, object]) -> str | None:
    return next((field["name"] for field in fields for occurrence in field["occurrences"]
                 if occurrence["entry"] == command.get("entry")
                 and occurrence["occurrence"] == command.get("occurrence")), None)


def _execute(package, command: Mapping[str, object], *, projecting: bool) -> tuple[object, dict]:
    before = dict(package.entries)
    action = command.get("type")
    before_label = _command_preview_label(command)
    impact_context = _preview_content_context(package, command)
    prior_fields = _fields(package) if action in {"create_field", "rename_field", "relink_field",
                                                   "unset_field"} else []
    requires_cascade = False
    extra: dict = {}
    label = command_label(command, impact_context.get("target_name"))
    if action in {"rename_slot", "rename_option"}:
        label = command_label(command, _region_display_name(
            inspect_slot_regions(package), str(command.get("slot_id")),
            command.get("option_id") if action == "rename_option" else None))
    try:
        if action == "create_field":
            sites = _field_site_contexts(package, command) if command.get("ranges") is not None else None
            captured = _create_field(package, command)
            existing = next((item["count"] for item in prior_fields
                             if item["name"] == normalize_field_id(command.get("name"))), 0)
            extra = {"links_existing": existing > 0, "existing_count": existing,
                     "candidates": field_candidates(prior_fields)}
            if sites is not None:
                # 같은 문구 N곳(P-07): 포함될 자리마다 검색 결과와 같은 문맥 한 줄, 영향은 자리 수다.
                impact_context = {**impact_context, "included": sites}
                extra["affected"] = len(sites)
        elif action == COMPILE_TOKEN:
            captured = _compile_token(package, command)
        elif action in {"rename_field", "relink_field", "unset_field"}:
            captured = _change_field(package, command)
            whole = whole_field_unset(command)
            label = command_label(command, command.get("old_name") if action == "rename_field" or whole
                                  else _prior_field_name(prior_fields, command))
            if whole:
                # 필드 전체 해제의 포함 내용은 모든 사용 위치의 문맥이다(P-20) — 구조 목록의 사용 위치 행과 같다.
                name = normalize_field_id(command.get("old_name"))
                impact_context = {**impact_context, "included": [
                    occurrence["context"] for field in prior_fields if field["name"] == name
                    for occurrence in field["occurrences"]]}
        elif action in {"create_slot", "create_option"}:
            _create_region(package, command)
            captured = None
        elif action in {"rename_slot", "rename_option"}:
            _rename_region(package, command)
            captured = None
        elif action == "adjust_range":
            _adjust_region(package, command)
            captured = None
        elif action == "move":
            _move_region(package, command)
            captured = None
        elif action == "duplicate":
            _duplicate_region(package, command)
            captured = None
        elif action in {"unwrap", "delete"}:
            kind = command.get("kind", "slot")
            slot_id = str(command.get("slot_id"))
            option_id = command.get("option_id")
            if action == "delete":
                if kind == "option":
                    remove_slot_option(package, slot_id, str(option_id))
                else:
                    remove_slot(package, slot_id)
            else:
                snapshot = inspect_slot_regions(package)
                if snapshot.diagnostics:
                    raise ValueError("문서 구조 오류를 먼저 수정하세요.")
                region = (snapshot.option_regions.get((slot_id, str(option_id))) if kind == "option"
                          else snapshot.slot_regions.get(slot_id))
                if region is None:
                    raise ValueError("항목이나 선택 영역을 찾을 수 없습니다.")
                if kind == "slot" and any(slot.options for slot in snapshot.slots if slot.id == slot_id):
                    if not command.get("cascade"):
                        if not projecting:
                            raise CascadeRequired([child for child in impact_context.get("children", [])
                                                   if child["kind"] == "option"])
                        requires_cascade = True
                    _unwrap_slot_options(package, slot_id)
                    region = inspect_slot_regions(package).slot_regions[slot_id]
                unwrap_bookmark_region(package, region)
            captured = None
        else:
            raise ValueError(f"지원하지 않는 HWPX 저작 명령입니다: {action!r}")
        result = analyze_hwpx(package)
        if result["diagnostics"] and not analyze_hwpx(_snapshot(before))["diagnostics"]:
            raise ValueError("명령을 적용하면 문서 구조가 깨집니다.")
        changed = [entry for entry in package.entries if package.entries[entry] != before.get(entry)]
        after_label = (_command_preview_label(command, after=True, captured=captured))
        before_text = impact_context.get("before")
        after_text = impact_context.get("after")
        captured_text = captured if isinstance(captured, str) else None
        return package, {"changed_entries": changed,
                         "affected": captured if isinstance(captured, int) else len(changed),
                         "result": result,
                         "captured_text": captured_text, "original": captured_text,
                         "before": (before_text if before_text is not None
                                    else captured_text if captured_text is not None else before_label),
                         "after": after_text if after_text is not None else after_label,
                         "included": impact_context.get("included"),
                         "included_location": impact_context.get("included_location"),
                         "expanded": impact_context.get("expanded", False),
                         "children": impact_context.get("children", []),
                         "counts": impact_context.get("counts"),
                         "label": label, "requires_cascade": requires_cascade, **extra}
    except Exception as exc:
        package.entries.clear()
        package.entries.update(before)
        if isinstance(exc, ValueError) and not re.search("[가-힣]", str(exc)):
            raise ValueError("이 문서의 구조나 고른 범위 때문에 명령을 적용할 수 없습니다.") from exc
        raise


def _field_site_contexts(package, command: Mapping[str, object]) -> list[str]:
    """``ranges`` 자리마다 바꾸기 전 문맥 한 줄(문서 차례) — 좌표가 틀리면 ``_create_field`` 와 같은 거절이다."""
    roots: dict = {}
    sites = [_field_paragraph(package, roots, item) for item in _field_ranges(command)]
    order = {entry: {id(node): index for index, node in enumerate(root.iter(f"{_HP}p"))}
             for entry, root in roots.items()}
    marks = {entry: _field_marks(entry, root) for entry, root in roots.items()}
    return [_body_hit_context(_paragraph_pieces(paragraph, marks[entry]), start, end)
            for entry, paragraph, start, end in sorted(
                sites, key=lambda site: (site[0], order[site[0]][id(site[1])], site[2]))]


def _command_preview_label(command: Mapping[str, object], *, after: bool = False,
                           captured: object = None) -> str:
    action = command.get("type")
    if action in {"create_field", COMPILE_TOKEN}:
        return f"[ {command.get('name', '')} ]" if after else str(captured or "")
    if action in {"rename_field", "relink_field"}:
        return str(command.get("name" if after else "old_name", ""))
    if action == "unset_field":
        return str(command.get("text", "")) if after else f"[ {command.get('old_name', '')} ]"
    if action in {"create_slot", "rename_slot", "create_option", "rename_option"}:
        noun = "항목" if str(action).endswith("slot") else "선택"
        return f"{noun} {command.get('id' if after else 'slot_id', '')}"
    if action == "delete":
        return "삭제됨" if after else "영역 내용과 의미"
    if action == "unwrap":
        return "본문 유지" if after else "의미 경계"
    return str(command.get("type", ""))


def _preview_content_context(package, command: Mapping[str, object]) -> dict:
    """Show the actual native paragraph body touched by a structure command."""
    action = command.get("type")
    if action not in {"create_slot", "create_option", "adjust_range", "unwrap", "delete", "duplicate", "move"}:
        return {}
    slot_id = str(command.get("slot_id") or "")
    option_id = command.get("option_id")
    prior_region = None
    target_name = None
    snapshot = inspect_slot_regions(package)
    if action in {"create_slot", "create_option", "adjust_range"}:
        entry = command.get("entry")
        start = command.get("start_paragraph")
        end = command.get("end_paragraph")
        if action == "adjust_range":
            region = (snapshot.option_regions.get((slot_id, option_id))
                      if isinstance(option_id, str) and command.get("kind") == "option"
                      else snapshot.slot_regions.get(slot_id))
            prior_region = region
            target_name = _region_display_name(snapshot, slot_id, option_id if command.get("kind") == "option" else None)
            if region is not None and entry is None:
                entry = region.section
    else:
        region = (snapshot.option_regions.get((slot_id, option_id))
                  if isinstance(option_id, str) and command.get("kind") == "option"
                  else snapshot.slot_regions.get(slot_id))
        target_name = _region_display_name(snapshot, slot_id, option_id if command.get("kind") == "option" else None)
        if region is None:
            return {"target_name": target_name}
        entry, start, end = region.section, region.start_paragraph, region.end_paragraph
    if not isinstance(entry, str) or entry not in package.entries or not isinstance(start, int) or not isinstance(end, int):
        return {"target_name": target_name}
    root = etree.fromstring(package.entries[entry], parser=etree.XMLParser(resolve_entities=False))
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    if not (0 <= start <= end < len(paragraphs)):
        return {"target_name": target_name}
    lines = ["".join(node.text or "" for node in paragraph.iter(f"{_HP}t"))
             for paragraph in paragraphs[start:end + 1]]
    included = "\n".join(lines)
    previous = ("\n".join("".join(node.text or "" for node in paragraph.iter(f"{_HP}t"))
                          for paragraph in paragraphs[prior_region.start_paragraph:prior_region.end_paragraph + 1])
                if prior_region is not None else included)
    target_key = ((slot_id, option_id) if command.get("kind") == "option"
                  and action not in {"create_slot", "create_option"} else None)
    children, counts = _block_children(package, snapshot, entry, paragraphs, start, end, exclude=target_key)
    detail = (f"\n\n포함: 문단 {counts['paragraphs']}개 · 필드 {counts['fields']}곳 · "
              f"하위 영역 {counts['options']}곳")
    start_offset, end_offset = command.get("start"), command.get("end")
    expanded = (action in {"create_slot", "create_option"}
                and ((isinstance(start_offset, int) and start_offset > 0)
                     or (isinstance(end_offset, int) and end_offset < len(lines[-1]))))
    return {"before": previous + detail,
            "after": ("본문과 의미가 삭제됩니다." if action == "delete"
                      else included + "\n\n" + _command_preview_label(command, after=True)),
            "included": included[:500], "expanded": expanded,
            # 편집면이 미리보기 동안 칠할 실제 범위(P-16) — 넓힌 문단 전체 또는 대상 영역의 문단.
            "included_location": {"entry": entry, "start_paragraph": start, "end_paragraph": end},
            "children": children, "counts": counts, "target_name": target_name}


def _region_display_name(snapshot, slot_id: str, option_id: object) -> str | None:
    slot = next((item for item in snapshot.slots if item.id == slot_id), None)
    if slot is None:
        return None
    if option_id is not None:
        option = next((item for item in slot.options if item.id == option_id), None)
        return (option.label or option.id) if option is not None else None
    return slot.label or slot.id


def _block_children(package, snapshot, entry: str, paragraphs: list, start: int, end: int,
                    *, exclude: tuple[str, object] | None = None) -> tuple[list[dict], dict]:
    """Options, field occurrences and tables inside paragraphs ``start..end`` of ``entry``.

    ``exclude`` names the option region being acted on so it is not listed as its own child.
    """
    children: list[dict] = []
    options = [(owner, option_id, region) for (owner, option_id), region in snapshot.option_regions.items()
               if region.section == entry and start <= region.start_paragraph and region.end_paragraph <= end
               and (owner, option_id) != exclude]
    for owner, option_id, region in options:
        children.append({"kind": "option", "id": option_id,
                         "label": _region_display_name(snapshot, owner, option_id) or option_id,
                         "count": region.end_paragraph - region.start_paragraph + 1})
    grouped: dict[str, int] = defaultdict(int)
    for field in _fields(package):
        for occurrence in field["occurrences"]:
            if (occurrence["entry"] == entry and isinstance(occurrence["paragraph"], int)
                    and start <= occurrence["paragraph"] <= end):
                grouped[field["name"]] += 1
    children.extend({"kind": "field", "id": name, "label": name, "count": count}
                    for name, count in grouped.items())
    tables = sum(1 for paragraph in paragraphs[start:end + 1] for _ in paragraph.iter(f"{_HP}tbl"))
    counts = {"paragraphs": end - start + 1, "fields": sum(grouped.values()),
              "options": len(options), "tables": tables}
    return children, counts


def _snapshot(entries: dict[str, bytes]):
    from hwpxcore.package import HwpxPackage

    package = HwpxPackage()
    package.entries.update(entries)
    return package


def preview_hwpx(content: object, command: Mapping[str, object]) -> dict:
    """Project a command on a throwaway copy; an unconfirmed cascade is flagged, not refused."""
    disposable = copy.deepcopy(require_package(content))
    _, impact = _execute(disposable, command, projecting=True)
    return impact


def _selection_frame(package, selection: Mapping[str, object]) -> tuple[str, int, int, int, int, list] | None:
    entry = selection.get("entry")
    first = selection.get("start_paragraph", selection.get("paragraph"))
    last = selection.get("end_paragraph", first)
    start, end = selection.get("start", 0), selection.get("end", selection.get("start", 0))
    values = (first, last, start, end)
    if (not isinstance(entry, str) or entry not in package.entries
            or any(type(value) is not int or value < 0 for value in values)):
        return None
    assert isinstance(first, int) and isinstance(last, int) and isinstance(start, int) and isinstance(end, int)
    if first > last or (first == last and start > end):
        return None
    root = etree.fromstring(package.entries[entry], parser=etree.XMLParser(resolve_entities=False))
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    if last >= len(paragraphs):
        return None
    return entry, first, last, start, end, paragraphs


def available_commands_hwpx(content: object, selection: Mapping[str, object],
                            context: Mapping[str, object] | None = None) -> list[dict]:
    """Decide which commands the current HWPX selection allows and why not (F40, §6.1)."""
    package = require_package(content)
    context = context or {}
    frame = _selection_frame(package, selection)
    if frame is None:
        return availability_entries(dict.fromkeys(COMMAND_TYPES, REASON_INVALID_SELECTION))
    entry, first, last, start, end, paragraphs = frame
    analysis = analyze_hwpx(package)
    snapshot = inspect_slot_regions(package)

    def field_hit(occurrence: dict) -> bool:
        paragraph = occurrence.get("paragraph")
        if occurrence.get("entry") != entry or not isinstance(paragraph, int) or not first <= paragraph <= last:
            return False
        low, high = occurrence.get("start"), occurrence.get("end")
        if not isinstance(low, int) or not isinstance(high, int):
            return True
        if first < paragraph < last:
            return True
        if first == last:
            return low <= start <= high if start == end else low < end and start < high
        return start <= high if paragraph == first else low <= end

    field_hits = [field["name"] for field in analysis["fields"]
                  for occurrence in field["occurrences"] if field_hit(occurrence)]
    regions = [(item["kind"], item.get("slot_id", item["id"]), item["id"] if item["kind"] == "option" else None,
                item["location"])
               for slot in analysis["slots"] for item in [slot, *slot["options"]]
               if item["location"] is not None and item["location"]["entry"] == entry]
    hit = [region for region in regions
           if region[3]["start_paragraph"] <= last and first <= region[3]["end_paragraph"]]
    containing = [region for region in hit
                  if region[3]["start_paragraph"] <= first and last <= region[3]["end_paragraph"]]
    crossing = any(region not in containing for region in hit)
    slot_id = context["slot_id"] if "slot_id" in context else next(
        (region[1] for region in containing if region[0] == "slot"), None)
    option_id = context["option_id"] if "option_id" in context else next(
        (region[2] for region in containing if region[0] == "option"), None)
    if slot_id is not None and slot_id not in snapshot.slot_regions:
        slot_id = option_id = None
    target_kind = "option" if option_id is not None and slot_id is not None else "slot" if slot_id else None
    broken = bool(snapshot.diagnostics)
    reasons = shared_reasons(field_hits=field_hits, target_kind=target_kind, has_slot=slot_id is not None,
                             structure_broken=broken)
    alternatives: dict[str, dict] = {}
    if crossing:
        reasons["create_field"] = REASON_MULTI_REGION
    elif first != last:
        reasons["create_field"] = _MULTI_PARAGRAPH_FIELD
    else:
        sites, hazards, text = _paragraph_sites(paragraphs[first])
        reasons["create_field"] = _field_range_refusal(sites, hazards, text, start, end) or (
            REASON_FIELD_OVERLAP if field_hits and start != end else None)
    if broken:
        reasons["create_slot"] = reasons["create_option"] = REASON_STRUCTURE_FIRST
        return availability_entries(reasons, alternatives)
    reasons["create_slot"] = REASON_REGION_OVERLAP if hit else None
    owners = [region for region in containing if region[0] == "slot"]
    if len(owners) == 1:
        reasons["create_option"] = (REASON_REGION_OVERLAP if any(region[0] == "option" for region in hit)
                                    else None)
    elif any(region[0] == "slot" for region in hit):
        reasons["create_option"] = REASON_MULTI_REGION
    else:
        reasons["create_option"] = REASON_OPTION_OUTSIDE_SLOT
        alternatives["create_option"] = dict(ALTERNATIVE_CREATE_SLOT)
    return availability_entries(reasons, alternatives)


def available_target_commands_hwpx(content: object, kind: str, name: str | None = None) -> list[dict]:
    """HWPX availability for an identity-chosen target; structure errors come from the same snapshot."""
    package = require_package(content)
    return target_availability(kind, name=name,
                               structure_broken=bool(inspect_slot_regions(package).diagnostics))


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
        for slot in snapshot.slots:
            members = [("slot", slot.id, slot.label, snapshot.slot_regions[slot.id])]
            members += [("option", option.id, option.label, snapshot.option_regions[(slot.id, option.id)])
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
    sections = []
    for entry, root in _roots(package):
        occurrences = resolve_field_occurrences(entry, root).occurrences
        named = {occurrence.begin: name for occurrence in occurrences
                 if is_fill_target_field_type(occurrence.field_type)
                 for name in (normalize_field_id(occurrence.raw_name),) if name is not None}
        hidden = {node for occurrence in occurrences if occurrence.begin in named for node in occurrence.texts}
        lines: list[str] = []
        for index, paragraph in enumerate(node for node in root if node.tag == f"{_HP}p"):
            if any(True for _ in paragraph.iter(f"{_HP}tbl")) and _NOTE_TABLE not in notes:
                notes.append(_NOTE_TABLE)
            lines.extend(begins.get((entry, index), ()))
            parts: list[str] = []
            for node in paragraph.iter():
                if node in named:
                    parts.append("{{" + named[node] + "}}")
                elif node.tag == f"{_HP}t" and node not in hidden:
                    parts.append(node.text or "")
            lines.append("".join(parts))
            lines.extend(ends.get((entry, index), ()))
        sections.append({"entry": entry, "text": "\n".join(lines)})
    return {"sections": sections, "note": " ".join(notes) or None}


def trial_hwpx(content: object, values: Mapping[str, object], selected: Mapping[str, str]) -> dict:
    from hwpxcore.package import HwpxPackage

    package = copy.deepcopy(require_package(content))
    assert isinstance(package, HwpxPackage)
    source_bytes = package.to_bytes()
    source_fields = _fields(package)
    snapshot = inspect_slot_regions(package)
    if snapshot.diagnostics:
        raise ValueError("문서 구조 오류를 수정한 뒤 결과를 시험하세요.")
    excluded = []
    for slot in snapshot.slots:
        choice = selected.get(slot.id)
        if slot.options and choice not in {option.id for option in slot.options}:
            raise ValueError(f"'{slot.id}' 항목의 시험 선택을 지정하세요.")
        chosen_option = next((option for option in slot.options if option.id == choice), None)
        if slot.options:
            assert chosen_option is not None
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
    if set(selected) - {slot.id for slot in snapshot.slots}:
        raise ValueError("존재하지 않는 항목 선택이 있습니다.")
    for item in reversed(excluded):
        remove_slot_option(package, item["slot_id"], item["option_id"])
    selected_fields = _fields(package)
    # 값이 없는 필드는 거절하지 않는다 — 생성 경로와 같은 빈 값 표식을 받고 보고의 empty_fields 에 선다(#957).
    logical_values, empty_fields = trial_document_values((field["name"] for field in selected_fields), values)
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
    assert isinstance(package, HwpxPackage)
    output_fields = _fields(HwpxPackage.from_bytes(materialized.output_bytes))
    sources = {(occurrence["entry"], occurrence["pairing_id"]): occurrence
               for field in source_fields for occurrence in field["occurrences"]}
    output_values, _ = trial_document_values((field["name"] for field in output_fields), values)
    provenance = [{"name": field["name"], "value": output_values[field["name"]],
                   "source": sources.get((occurrence["entry"], occurrence["pairing_id"]), occurrence),
                   "output": occurrence}
                  for field in output_fields for occurrence in field["occurrences"]]
    return {"bytes": materialized.output_bytes, "excluded": excluded,
            "occurrences": provenance,
            "report": {"missing_fields": [], "empty_fields": empty_fields}}

