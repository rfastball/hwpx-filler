"""Native HWPX authoring: search responsibilities."""

from __future__ import annotations

import re
from collections.abc import Mapping

import lxml.etree as etree  # pyright: ignore[reportMissingImports]

from hwpxcore.text_extract import HP_NS, require_package

from ..domain import authoring as _authoring
from ..domain.schema import extract_schema
from ..domain.structure_scan import PLACEMENT_OPTION, PLACEMENT_SLOT, normalize_field_id
from ..domain.template_authoring import (
    CATEGORY_AUTHORING,
    COMPILE_TOKEN,
    COMPILE_TOKEN_LABEL,
    KIND_STRAY_TOKEN,
    MESSAGE_STRAY_TOKEN,
    SEVERITY_WARNING,
    command_action,
    navigate_action,
    context_focus,
)
from .hwpx_product_inspection import (
    inspect_slot_regions,
)

_HP = f"{{{HP_NS}}}"
from .hwpx_authoring_reading import (
    PARAGRAPH_UNRESOLVED as _PARAGRAPH_UNRESOLVED,
    body_hit_context as _body_hit_context,
    body_hit_parts as _body_hit_parts,
    cell_path as _cell_path,
    field_marks as _field_marks,
    field_range_refusal as _field_range_refusal,
    paragraph_body as _paragraph_body,
    paragraph_pieces as _paragraph_pieces,
    paragraph_position as _paragraph_position,
    paragraph_sites as _paragraph_sites,
    root_anchor as _root_anchor,
    roots as _roots,
    selected_paragraph as _selected_paragraph,
)
from .hwpx_authoring_analysis import (
    analyze_hwpx,
)

def _namespaces(root) -> dict:
    return {prefix: uri for prefix, uri in root.nsmap.items() if prefix}


def _token_location(root, entry: str, paragraph, start: int, end: int) -> dict | None:
    """Where one plain-text token sits, in the coordinates the editor navigates with (IDE-05 #1051).

    The token offsets are depth-0 body offsets (``authoring._build_paragraph_model``); they are carried as
    editor offsets only when nothing before the token's end could make them differ (no control, tab or field
    before it, same text). Otherwise the location is the paragraph alone — the position is not guessed.
    """
    location = _token_paragraph_location(root, entry, paragraph)
    if location is None:
        return None
    if paragraph.getparent() is not root and "cell_path" not in location:
        return location
    sites, hazards, text = _paragraph_sites(paragraph)
    model = _authoring._build_paragraph_model(paragraph)[0]
    if (0 <= start < end <= len(text) and sites and not any(position <= end for position in hazards)
            and text[:end] == model[:end]):
        location.update(start=start, end=end)
    return location


def _token_paragraph_location(root, entry: str, paragraph) -> dict | None:
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    if paragraph in paragraphs:
        location: dict = {"entry": entry, "paragraph": paragraphs.index(paragraph)}
    else:
        cell_path = _cell_path(root, paragraph)
        if cell_path is None:
            anchor = _root_anchor(paragraphs, paragraph)
            return {"entry": entry, "paragraph": anchor} if anchor is not None else None
        location = {"entry": entry, "paragraph": cell_path[-1]["paragraph"], "cell_path": cell_path}
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
        return {"hits": _structure_hits(content, query)}
    return {"hits": _text_hits(content, query)}


def _structure_hits(content: object, query: str) -> list[dict]:
    snapshot = inspect_slot_regions(require_package(content))
    hits = []
    for slot in snapshot.slots:
        region = snapshot.slot_regions[slot.id]
        if query.casefold() in (slot.id + " " + (slot.label or "")).casefold():
            hits.append({"kind": PLACEMENT_SLOT, "slot_id": slot.id, "label": slot.label or slot.id,
                         "entry": region.section, "start_paragraph": region.start_paragraph,
                         "end_paragraph": region.end_paragraph})
        hits.extend(_option_hits(snapshot, slot, query))
    return hits


def _option_hits(snapshot, slot, query: str) -> list[dict]:
    hits = []
    for option in slot.options:
        region = snapshot.option_regions[(slot.id, option.id)]
        if query.casefold() in (option.id + " " + (option.label or "")).casefold():
            hits.append({"kind": PLACEMENT_OPTION, "slot_id": slot.id, "option_id": option.id,
                         "label": option.label or option.id, "entry": region.section,
                         "start_paragraph": region.start_paragraph,
                         "end_paragraph": region.end_paragraph})
    return hits


def _text_hits(content: object, query: str) -> list[dict]:
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
    return hits


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
        hits.extend(_same_text_section(entry, root, phrase, chosen, chosen_start, chosen_end))
    return hits


def _same_text_section(entry, root, phrase, chosen, chosen_start: int, chosen_end: int) -> list[dict]:
    hits: list[dict] = []
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
    if not _usable_selection(entry, package, first, last, start, end):
        return None
    assert isinstance(entry, str)
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


def _usable_selection(entry, package, first, last, start, end) -> bool:
    return (isinstance(entry, str) and entry in package.entries
            and not any(type(value) is not int or value < 0 for value in (first, last, start, end))
            and first == last)
