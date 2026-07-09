"""HWPX 본문 텍스트 추출 — 결정적(deterministic) 문서 트리 생성.

HWPX 본문(``Contents/section*.xml``)을 파싱해 문단/표 구조를 담은 직렬화 가능한
데이터클래스 트리로 복원한다. diff 도구와 문서 생성기가 함께 소비할 수 있도록
설계했으며, 의존성은 ``lxml`` + 표준 라이브러리로 한정한다.

핵심 구조 사실(실제 코퍼스 검증 완료):
  - 섹션 루트 ``hs:sec`` 밑에 문단 ``hp:p`` 가 직접 온다.
  - 문단 ``hp:p`` > 런 ``hp:run`` > (``hp:t`` | ``hp:ctrl`` | ``hp:tbl`` | ``hp:secPr``).
  - **한 문단의 텍스트는 여러 런의 여러 ``hp:t`` 파편으로 쪼개진다** — 문서 순서로
    이어붙여야 문단 문자열이 복원된다.
  - ``hp:t`` 는 혼합 콘텐츠다: ``.text`` + 자식(``hp:tab`` 등) + 자식의 ``.tail``.
    실제 파일에서 ``<hp:t>글자<hp:tab/></hp:t>`` 형태로 탭이 ``hp:t`` 안에 박힌다.
  - 표는 런 안에 중첩된다: ``hp:tbl`` > ``hp:tr`` > ``hp:tc`` > ``hp:subList`` > ``hp:p``.
    셀은 자체 문단을 가지며 표 중첩이 가능하다.
  - 누름틀: ``hp:ctrl`` 안의 ``hp:fieldBegin``/``hp:fieldEnd``. 사이의 텍스트는 일반
    ``hp:t`` 다. 추출 시 값은 그대로 잡되 어느 필드 소속인지 선택적으로 기록한다.

출력은 랜덤 ID(id, fieldid, charPrIDRef 등)를 전혀 담지 않아 골든 스냅샷이 실행 간
안정적이고 문서 버전 간 의미를 갖는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .package import HwpxPackage

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def _local(tag: object) -> str:
    """요소의 로컬 태그명(네임스페이스 제거). 주석/PI 등 비문자 태그는 빈 문자열."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


# ----------------------------------------------------------------- data model
@dataclass
class Paragraph:
    """복원된 문단. ``text`` 는 파편을 이어붙인 최종 문자열(탭/줄바꿈 보존).

    ``fields`` 는 이 문단 안에서 텍스트를 담은 누름틀 이름의 순서 있는 중복 없는 목록
    (의미론적 이름이므로 랜덤 ID 가 아니다).
    """

    text: str
    fields: "list[str]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"type": "paragraph", "text": self.text, "fields": list(self.fields)}


@dataclass
class Cell:
    """표 셀. 자체 문단/표 블록을 갖는다(표 중첩 지원)."""

    blocks: "list[object]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"blocks": [b.to_dict() for b in self.blocks]}


@dataclass
class Table:
    """표. ``rows`` 는 행 목록, 각 행은 셀 목록."""

    rows: "list[list[Cell]]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": "table",
            "rows": [[c.to_dict() for c in row] for row in self.rows],
        }


@dataclass
class Section:
    """섹션 본문. ``blocks`` 는 문서 순서의 Paragraph/Table 목록."""

    blocks: "list[object]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"blocks": [b.to_dict() for b in self.blocks]}


@dataclass
class Document:
    """추출된 문서 전체. ``sections`` 는 섹션 목록(section0, section1, ... 순)."""

    sections: "list[Section]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"sections": [s.to_dict() for s in self.sections]}


# ------------------------------------------------------------- section 선택
_SECTION_RE = re.compile(r"section(\d+)\.xml$", re.IGNORECASE)


def section_xml_names(pkg: HwpxPackage) -> "list[str]":
    """패키지에서 본문 섹션 XML 이름을 번호 오름차순으로 반환.

    ``Contents/header.xml``(스타일 정의 head)·footer 는 본문 텍스트가 아니므로 제외.
    section10 이 section2 앞에 오지 않도록 접미 숫자로 자연 정렬한다.
    """
    hits = []
    for name in pkg.entries:
        base = name.rsplit("/", 1)[-1].lower()
        m = _SECTION_RE.search(base)
        if base.startswith("section") and m:
            hits.append((int(m.group(1)), name))
    hits.sort(key=lambda x: (x[0], x[1]))
    return [name for _, name in hits]


# ------------------------------------------------------------- 텍스트 복원
def _text_of_t(t_el: etree._Element) -> str:
    """``hp:t`` 혼합 콘텐츠를 문자열로 복원. ``hp:tab`` -> \\t, ``hp:lineBreak`` -> \\n."""
    parts: "list[str]" = []
    if t_el.text:
        parts.append(t_el.text)
    for ch in t_el:
        ln = _local(ch.tag)
        if ln == "tab":
            parts.append("\t")
        elif ln == "lineBreak":
            parts.append("\n")
        # 그 외 인라인 마크업(markpen 등)은 텍스트 없음 — tail 만 이어붙인다.
        if ch.tail:
            parts.append(ch.tail)
    return "".join(parts)


def _blocks_from_paragraph(p_el: etree._Element) -> "list[object]":
    """단일 ``hp:p`` 를 블록 목록으로 변환.

    문단 안에 표가 끼어들면 앞 텍스트를 Paragraph 로 flush 한 뒤 Table 을 넣어 문서
    순서를 보존한다. 텍스트도 표도 없는 문단은 빈 Paragraph 로 보존한다.
    """
    blocks: "list[object]" = []
    buf: "list[str]" = []
    field_names: "list[str]" = []
    field_stack: "list[str]" = []

    def flush() -> None:
        if buf:
            blocks.append(Paragraph("".join(buf), list(field_names)))
            buf.clear()
            field_names.clear()

    for run in p_el:
        if _local(run.tag) != "run":
            # linesegarray 등 레이아웃 요소는 무시.
            continue
        for ch in run:
            ln = _local(ch.tag)
            if ln == "t":
                txt = _text_of_t(ch)
                if txt:
                    buf.append(txt)
                    if field_stack and txt.strip():
                        nm = field_stack[-1]
                        if nm and nm not in field_names:
                            field_names.append(nm)
            elif ln == "ctrl":
                for c in ch:
                    cl = _local(c.tag)
                    if cl == "fieldBegin":
                        field_stack.append((c.get("name") or "").strip())
                    elif cl == "fieldEnd":
                        if field_stack:
                            field_stack.pop()
            elif ln == "tbl":
                flush()
                blocks.append(_table_from_el(ch))
            elif ln == "lineBreak":
                buf.append("\n")
            elif ln == "tab":
                buf.append("\t")
            # secPr 등은 텍스트 없음 — 무시.

    if buf:
        blocks.append(Paragraph("".join(buf), list(field_names)))
    elif not blocks:
        # 완전히 빈 문단도 구조상 보존.
        blocks.append(Paragraph("", []))
    return blocks


def _blocks_from_container(container: etree._Element) -> "list[object]":
    """컨테이너(섹션 루트 또는 셀 subList)의 직속 ``hp:p`` 를 순서대로 블록화."""
    blocks: "list[object]" = []
    for child in container:
        if _local(child.tag) == "p":
            blocks.extend(_blocks_from_paragraph(child))
    return blocks


def _table_from_el(tbl_el: etree._Element) -> Table:
    """``hp:tbl`` -> Table. 셀 내용은 ``hp:subList`` 밑 문단에서 추출(표 중첩 재귀)."""
    rows: "list[list[Cell]]" = []
    for tr in tbl_el:
        if _local(tr.tag) != "tr":
            continue
        cells: "list[Cell]" = []
        for tc in tr:
            if _local(tc.tag) != "tc":
                continue
            cell_blocks: "list[object]" = []
            for sub in tc:
                if _local(sub.tag) == "subList":
                    cell_blocks.extend(_blocks_from_container(sub))
            cells.append(Cell(cell_blocks))
        rows.append(cells)
    return Table(rows)


# ------------------------------------------------------------------ 공개 API
def _to_package(pkg_or_path: object) -> HwpxPackage:
    if isinstance(pkg_or_path, HwpxPackage):
        return pkg_or_path
    if isinstance(pkg_or_path, (bytes, bytearray)):
        return HwpxPackage.from_bytes(bytes(pkg_or_path))
    if isinstance(pkg_or_path, (str, Path)):
        return HwpxPackage.open(str(pkg_or_path))
    raise TypeError(f"지원하지 않는 입력 타입: {type(pkg_or_path)!r}")


def extract_document(pkg_or_path: object) -> Document:
    """HWPX(경로/바이트/HwpxPackage)에서 본문을 추출해 Document 반환.

    본문이 없으면 빈 섹션 목록. 섹션은 section0, section1, ... 순으로 결정적이다.
    """
    pkg = _to_package(pkg_or_path)
    doc = Document(sections=[])
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    for name in section_xml_names(pkg):
        root = etree.fromstring(pkg.entries[name], parser=parser)
        doc.sections.append(Section(blocks=_blocks_from_container(root)))
    return doc


def _iter_blocks(blocks: "list[object]"):
    """블록 트리를 문서 순서로 깊이 우선 순회하며 Paragraph 를 yield."""
    for b in blocks:
        if isinstance(b, Paragraph):
            yield b
        elif isinstance(b, Table):
            for row in b.rows:
                for cell in row:
                    yield from _iter_blocks(cell.blocks)


def iter_paragraph_texts(doc: Document) -> "list[str]":
    """문서 순서(표 셀 내부 포함)로 모든 문단 텍스트를 반환."""
    out: "list[str]" = []
    for section in doc.sections:
        for para in _iter_blocks(section.blocks):
            out.append(para.text)
    return out


def full_text(doc: Document) -> str:
    """모든 문단 텍스트를 줄바꿈으로 이어붙인 전체 텍스트."""
    return "\n".join(iter_paragraph_texts(doc))
