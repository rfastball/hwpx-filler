"""「데이터로 필드 찾기」(#1156)의 문서 어댑터 — 문서를 문단 평문으로 읽고, 제안 자리를 필드 명령으로 되돌린다.

**좌표 계약.** 자리의 ``start/end`` 는 필드 만들기(``create_field``)·편집기 선택과 같은 계산법이다.
HWPX 는 문단 바로 아래 ``hp:run`` 의 ``hp:t`` 평문만 센다(탭·줄바꿈·제어 요소는 글자가 아니다).
첫 제어 요소 뒤의 자리는 두 계산법이 갈릴 수 있어 필드로 만들 수 없다 — ``editable_end`` 가 그 경계이고,
판정은 :func:`~hwpxfiller.external.hwpx_authoring_reading.paragraph_sites` 의 제어 요소 위치를 그대로 쓴다.
TXT 는 줄 단위로 읽고 좌표는 문서 전체의 UTF-16 단위다(편집기 좌표).

여러 묶음을 한 번에 만드는 ``create_fields`` 명령의 결과는 한 문서다(HWPX 는 명령 적용이 한 패키지 변형으로,
TXT 는 여기서 자리마다 문서 뒤에서부터 적용한다). 미리보기→적용 사슬이 그 한 문서를 편집기에 한 번 넣으므로
실행 취소도 한 단위다.
"""

from __future__ import annotations

from collections.abc import Mapping

from hwpxcore.text_extract import HP_NS, require_package

from ..domain import template_authoring as semantics
from ..domain.template_authoring_primitives import CREATE_FIELDS
from ..domain.field_induction.candidates import CellRef, ParagraphText
from .hwpx_authoring_commands import apply_hwpx
from .hwpx_authoring_reading import field_marks, paragraph_position, paragraph_sites, roots

_HP = f"{{{HP_NS}}}"
_INLINE = {f"{_HP}tab": "\t", f"{_HP}lineBreak": "\n"}


def _t_text(node) -> str:
    parts = [node.text or ""]
    for child in node:
        parts.append(_INLINE.get(child.tag, ""))
        parts.append(child.tail or "")
    return "".join(parts)


def _edges(control, marks: dict) -> list[bool]:
    """``hp:ctrl`` 안의 필드 경계 — 시작이면 True, 끝이면 False(채움 대상 필드만)."""
    return [mark[1] is not None for mark in (marks.get(node) for node in control.iter()) if mark is not None]


def _walk(paragraph, marks: dict) -> tuple[str, tuple[tuple[int, int], ...]]:
    """문단 본문 글자와 그 안의 필드 값 구간 — 표·그림 안의 문단은 따로 읽힌다."""
    text: list[str] = []
    edges: list[tuple[int, bool]] = []
    length = 0
    for child in (child for run in paragraph if run.tag == f"{_HP}run" for child in run):
        if child.tag == f"{_HP}t":
            text.append(_t_text(child))
            length += len(text[-1])
        elif child.tag == f"{_HP}ctrl":
            edges.extend((length, begins) for begins in _edges(child, marks))
    return "".join(text), _spans(edges)


def _spans(edges: list[tuple[int, bool]]) -> tuple[tuple[int, int], ...]:
    """필드 경계 위치들 → 필드 값 구간. 해석기는 한 문단 안에서 짝지은 경계만 내므로 시작마다 끝이 있다."""
    spans: list[tuple[int, int]] = []
    inside: int | None = None
    for position, begins in edges:
        if not begins and inside is not None:
            spans.append((inside, position))
        inside = position if begins else None
    return tuple(spans)


def _cell(entry: str, root, paragraph) -> CellRef | None:
    sub_list = paragraph.getparent()
    cell = sub_list.getparent() if sub_list is not None else None
    if cell is None or cell.tag != f"{_HP}tc":
        return None
    table = next(cell.iterancestors(f"{_HP}tbl"))
    address = cell.find(f"{_HP}cellAddr")
    span = cell.find(f"{_HP}cellSpan")
    table_key = f"{entry}|{root.getroottree().getpath(table)}"
    if address is None:
        return CellRef(table_key, -1, -1)
    return CellRef(table_key, int(address.get("rowAddr", "0")), int(address.get("colAddr", "0")),
                   int(span.get("rowSpan", "1")) if span is not None else 1,
                   int(span.get("colSpan", "1")) if span is not None else 1)


def read_hwpx(content: object) -> tuple[list[ParagraphText], list[dict]]:
    """문단 평문(문서 차례)과 문단마다 편집기 좌표(``entry``·``paragraph``·``cell_path``)."""
    package = require_package(content)
    paragraphs: list[ParagraphText] = []
    places: list[dict] = []
    for entry, root in roots(package):
        body = [node for node in root if node.tag == f"{_HP}p"]
        marks = field_marks(entry, root)
        for paragraph in root.iter(f"{_HP}p"):
            position = paragraph_position(root, body, paragraph)
            text, spans = _walk(paragraph, marks)
            _sites, hazards, _plain = paragraph_sites(paragraph)
            editable = (0 if position["paragraph"] is None
                        else min(hazards) if hazards else len(text) + 1)
            key = f"{entry}|{root.getroottree().getpath(paragraph)}"
            paragraphs.append(ParagraphText(key, text, editable, spans, _cell(entry, root, paragraph)))
            places.append({"entry": entry, **position})
    return paragraphs, places


def read_txt(text: str) -> tuple[list[ParagraphText], list[dict]]:
    """TXT 줄 평문과 줄마다 문서 안 시작 위치(코드 포인트). 필드 토큰·구간 표기는 필드 값처럼 뺀다."""
    from ..domain.text_structure import scan_text_token_spans

    tokens = [(span.start, span.end) for span in scan_text_token_spans(text)]
    paragraphs: list[ParagraphText] = []
    places: list[dict] = []
    offset = 0
    for index, line in enumerate(text.split("\n")):
        end = offset + len(line)
        spans = tuple((max(lo, offset) - offset, min(hi, end) - offset)
                      for lo, hi in tokens if lo < end and offset < hi)
        paragraphs.append(ParagraphText(f"L{index}", line, len(line) + 1, spans))
        places.append({"offset": offset})
        offset = end + 1
    return paragraphs, places


def _utf16(text: str, index: int) -> int:
    return len(text[:index].encode("utf-16-le")) // 2


def spot_location(media: str, source: object, place: Mapping[str, object], start: int, end: int) -> dict:
    """문단 안 구간 → 편집기 선택 좌표(HWPX: entry·paragraph·cell_path·start·end, TXT: UTF-16 start·end)."""
    if media == "txt":
        assert isinstance(source, str)
        base = place["offset"]
        assert isinstance(base, int)
        return {"start": _utf16(source, base + start), "end": _utf16(source, base + end)}
    location = {"entry": place["entry"], "paragraph": place["paragraph"], "start": start, "end": end}
    if place.get("cell_path") is not None:
        location["cell_path"] = place["cell_path"]
    return location


# ------------------------------------------------------------------ commands
def _valid_field(item: object) -> bool:
    ranges = item.get("ranges") if isinstance(item, Mapping) else None
    return isinstance(ranges, list) and bool(ranges) and all(isinstance(site, Mapping) for site in ranges)


def _txt_fields(text: str, command: Mapping[str, object]) -> tuple[str, dict]:
    """TXT 는 자리마다 ``create_field`` 를 문서 뒤에서부터 적용한다 — 앞 자리의 UTF-16 좌표가 그대로 남는다."""
    fields = command.get("fields")
    if not isinstance(fields, list) or not fields or not all(_valid_field(item) for item in fields):
        raise ValueError(semantics.REASON_INVALID_SELECTION)
    sites = [{"type": "create_field", "name": item["name"], **site} for item in fields for site in item["ranges"]]
    existing = {item["name"] for item in semantics.analyze("txt", text).get("fields", [])}
    changed = text
    for site in sorted(sites, key=lambda item: -int(item.get("start", 0))):
        changed, _ = semantics.apply("txt", changed, site)
    return changed, {
        "affected": len(sites), "result": semantics.analyze("txt", changed), "original": None,
        "before": None, "after": None, "included": None, "expanded": False, "requires_cascade": False,
        "label": semantics.COMMAND_NAMES["create_field"], "edits": [],
        "links_existing": any(item["name"] in existing for item in fields),
    }


def apply_authoring_command(media: str, document: object, command: Mapping[str, object]) -> tuple[object, dict]:
    """저작 명령 하나를 적용한다 — TXT 의 ``create_fields`` 는 여기서 풀고(HWPX 는 명령 적용이 한 변형으로 푼다),
    나머지는 매체의 명령 적용으로 넘긴다."""
    if media == "txt" and command.get("type") == CREATE_FIELDS:
        assert isinstance(document, str)
        return _txt_fields(document, command)
    if media == "txt":
        return semantics.apply(media, document, command)
    return apply_hwpx(document, command)
