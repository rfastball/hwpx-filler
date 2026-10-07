"""Native HWPX authoring: reading responsibilities."""

from __future__ import annotations


import lxml.etree as etree  # pyright: ignore[reportMissingImports]

from hwpxcore.field_occurrence import resolve_field_occurrences
from hwpxcore.text_extract import HP_NS

from ..domain.fields import is_fill_target_field_type
from ..domain.structure_scan import normalize_field_id
from ..domain.template_authoring import (
    occurrence_context,
    occurrence_context_parts,
)
from ..domain.template_authoring_primitives import REASON_CONTROL_BEFORE, REASON_FIELD_OVERLAP

_HP = f"{{{HP_NS}}}"


_CELL_PATH_KEYS = frozenset({"parent_paragraph", "control", "cell", "paragraph"})
_CONTROL_TAGS = frozenset(f"{_HP}{name}" for name in (
    "tbl", "pic", "container", "rect", "ellipse", "line", "connectLine", "arc", "polygon",
    "curve", "compose", "dutmal", "equation", "btn", "checkBtn", "radioBtn", "comboBox",
    "edit", "chart", "ole"))
_CTRL_CHILD_TAGS = frozenset(f"{_HP}{name}" for name in (
    "colPr", "header", "footer", "footNote", "endNote", "autoNum", "indexmark", "fieldBegin",
    "pageHiding", "pageNumCtrl", "pageNum", "bookmark", "newNum"))
_PARAGRAPH_UNRESOLVED = "고른 문단의 위치를 확정할 수 없습니다."

def _roots(package):
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    for entry in package.content_xml_names():
        yield entry, etree.fromstring(package.entries[entry], parser=parser)


def _simple_field_span(occurrence) -> dict:
    """Project codepoint offsets only when native text has no ambiguous controls."""
    paragraph = occurrence.paragraph
    if not _simple_field_content(paragraph):
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


def _simple_field_content(paragraph) -> bool:
    for run in paragraph:
        if run.tag != f"{_HP}run":
            continue
        if any(child.tag not in {f"{_HP}t", f"{_HP}ctrl"} for child in run):
            return False
    for control in paragraph.iter(f"{_HP}ctrl"):
        if any(child.tag not in {f"{_HP}fieldBegin", f"{_HP}fieldEnd"} for child in control):
            return False
    return True


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
    steps: list[dict] = []
    node = paragraph
    while True:
        if node.getparent() is root:
            break
        step = _cell_step(node)
        if step is None:
            return None
        owner, values = step
        steps.append(values)
        node = owner
    if not steps:
        return None
    steps.reverse()
    steps[0]["parent_paragraph"] = [item for item in root if item.tag == f"{_HP}p"].index(node)
    for previous, step in zip(steps, steps[1:], strict=False):
        step["parent_paragraph"] = previous["paragraph"]
    return steps


def _control_count(node) -> int:
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


def _control_index(owner, table) -> int:
    control = None
    counted = 0
    for owner_run in owner:
        if owner_run.tag != f"{_HP}run":
            continue
        for child in owner_run:
            if child is table:
                control = counted
            counted += _control_count(child)
    assert control is not None
    return control


def _cell_step(node):
    chain = [node]
    for tag in ("subList", "tc", "tr", "tbl", "run", "p"):
        parent = chain[-1].getparent()
        if parent is None or parent.tag != f"{_HP}{tag}":
            return None
        chain.append(parent)
    sub_list, cell, table, owner = chain[1], chain[2], chain[4], chain[6]
    cells = [item for item in table.iter(f"{_HP}tc")
             if next(item.iterancestors(f"{_HP}tbl"), None) is table]
    values = {"parent_paragraph": -1, "control": _control_index(owner, table), "cell": cells.index(cell),
              "paragraph": [item for item in sub_list if item.tag == f"{_HP}p"].index(node)}
    return owner, values


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
            piece = _direct_text_piece(node, paragraph, current)
            if piece is not None:
                pieces.append(piece)
    return pieces


def _direct_text_piece(node, paragraph, current):
    run = node.getparent()
    if run is None or run.tag != f"{_HP}run" or run.getparent() is not paragraph:
        return None
    key, name = current if current is not None else (None, None)
    return node.text or "", key, name


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
    spans = _piece_spans(pieces)
    hit = {id(piece[1]) for lo, hi, piece in spans if piece[1] is not None and lo < end and start < hi}
    # 찾은 글자가 필드 값에 걸치면 그 필드(들) 전체가 가운데 표지가 된다.
    inside = [(lo, hi) for lo, hi, piece in spans if piece[1] is not None and id(piece[1]) in hit]
    if inside:
        start, end = min(start, inside[0][0]), max(end, inside[-1][1])
    before: list[tuple[str, object, str | None]] = []
    focus: list[tuple[str, object, str | None]] = []
    after: list[tuple[str, object, str | None]] = []
    for lo, hi, (text, key, name) in spans:
        _partition_piece(lo, hi, text, key, name, start, end, hit, before, focus, after)
    return occurrence_context_parts(_render_pieces(before), _render_pieces(focus), _render_pieces(after))


def _piece_spans(pieces):
    spans = []
    offset = 0
    for piece in pieces:
        spans.append((offset, offset + len(piece[0]), piece))
        offset += len(piece[0])
    return spans


def _partition_piece(lo, hi, text, key, name, start, end, hit, before, focus, after) -> None:
    if key is not None:
        # 필드 조각은 자르지 않는다 — 통째로 앞·가운데·뒤 중 한 곳에 선다.
        side = (focus if id(key) in hit else before if hi <= start else after if lo >= end else focus)
        side.append((text, key, name))
        return
    before.append((text[:max(0, min(hi, start) - lo)], None, None))
    focus.append((text[max(0, start - lo):max(0, min(hi, end) - lo)], None, None))
    after.append((text[max(0, end - lo):], None, None))


def _root_anchor(paragraphs: list, paragraph) -> int | None:
    """가장 가까운 본문 문단(``paragraphs`` 의 원소) 조상 — 문단이 그 자체로 본문이 아닐 때만 쓴다."""
    for ancestor in paragraph.iterancestors(f"{_HP}p"):
        if ancestor in paragraphs:
            return paragraphs.index(ancestor)
    return None


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


def _editable_fields(paragraph) -> list:
    """Only paired, plain-text fill fields have zero-width, unambiguous boundaries."""
    if paragraph.find(f".//{_HP}fieldBegin") is None or not _simple_field_content(paragraph):
        return []
    resolution = resolve_field_occurrences("", paragraph.getroottree().getroot())
    if not resolution.pairing_usable:
        return []
    return [item for item in resolution.occurrences
            if item.paragraph is paragraph and is_fill_target_field_type(item.field_type)]


def _editable_field_boundaries(paragraph) -> set:
    return {control for item in _editable_fields(paragraph)
            for control in (item.begin_ctrl, item.end_ctrl) if len(control) == 1}


def _paragraph_sites(paragraph) -> tuple[list[tuple[etree._Element, int, int]], list[int], str]:
    """Plain text sites of one paragraph, control hazards by offset, and the joined text."""
    sites: list[tuple[etree._Element, int, int]] = []
    hazards: list[int] = []
    boundaries = _editable_field_boundaries(paragraph)
    length = 0
    for run in paragraph.iterchildren(f"{_HP}run"):
        for child in run:
            if child.tag == f"{_HP}t" and not len(child):
                next_length = length + len(child.text or "")
                sites.append((child, length, next_length))
                length = next_length
            elif child not in boundaries:
                hazards.append(length)
    return sites, hazards, "".join(node.text or "" for node, _, _ in sites)


def _field_range_refusal(sites: list, hazards: list[int], text: str, start: int, end: int) -> str | None:
    if not 0 <= start <= end <= len(text):
        return "고른 문자 범위가 문단 밖에 있습니다."
    if not sites:
        return "이 문단에는 편집 가능한 텍스트가 없습니다."
    if any(position <= end for position in hazards):
        return REASON_CONTROL_BEFORE
    paragraph = sites[0][0].getparent().getparent()
    for field in _editable_fields(paragraph):
        span = _simple_field_span(field)
        low, high = span["start"], span["end"]
        if (low <= start <= high if start == end else low < end and start < high):
            return REASON_FIELD_OVERLAP
    return None


def _selected_paragraph(root, paragraph_index: object, cell_path: object):
    """본문 문단 번호, 또는 rhwp 커서 경로(cell_path)로 가리킨 셀 문단 하나."""
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    if isinstance(cell_path, list):
        return _selected_cell_paragraph(root, paragraphs, paragraph_index, cell_path)
    if not isinstance(paragraph_index, int) or not 0 <= paragraph_index < len(paragraphs):
        raise ValueError("고른 문단이 문서 영역 밖에 있습니다.")
    return paragraphs[paragraph_index]


def _selected_cell_paragraph(root, paragraphs, paragraph_index: object, cell_path: list):
    # rhwp 커서 경로로 셀 문단을 확정한다 — 같은 규칙(_cell_path)으로 되읽어 일치하는
    # 문단만 인정하므로 analyze_hwpx 가 보고하는 좌표와 어긋날 수 없다.
    if not cell_path or not all(_valid_cell_step(step) for step in cell_path) or paragraph_index != cell_path[-1]["paragraph"]:
        raise ValueError(_PARAGRAPH_UNRESOLVED)
    owner_index = cell_path[0]["parent_paragraph"]
    candidates = ([node for node in paragraphs[owner_index].iter(f"{_HP}p")
                   if _cell_path(root, node) == cell_path]
                  if owner_index < len(paragraphs) else [])
    if len(candidates) != 1:
        raise ValueError(_PARAGRAPH_UNRESOLVED)
    return candidates[0]


def _valid_cell_step(step) -> bool:
    return isinstance(step, dict) and set(step) == _CELL_PATH_KEYS and all(
        type(value) is int and value >= 0 for value in step.values())


PARAGRAPH_UNRESOLVED = _PARAGRAPH_UNRESOLVED
body_hit_context = _body_hit_context
body_hit_parts = _body_hit_parts
cell_path = _cell_path
field_marks = _field_marks
field_range_refusal = _field_range_refusal
native_occurrence_context = _occurrence_context
paragraph_body = _paragraph_body
paragraph_pieces = _paragraph_pieces
paragraph_position = _paragraph_position
paragraph_sites = _paragraph_sites
root_anchor = _root_anchor
roots = _roots
selected_paragraph = _selected_paragraph
simple_field_span = _simple_field_span
