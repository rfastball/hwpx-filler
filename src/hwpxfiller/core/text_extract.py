"""HWPX 본문 텍스트 추출 — 결정적(deterministic) 문서 트리 생성.

HWPX 본문(``Contents/section*.xml``)을 파싱해 문단/표 구조를 담은 직렬화 가능한
데이터클래스 트리로 복원한다. diff 도구와 문서 생성기가 함께 소비할 수 있도록
설계했으며, 의존성은 ``lxml`` + 표준 라이브러리로 한정한다.

설계 원칙: **충실도(fidelity)는 완전하게, 기능(feature)은 최소로.** 문서에 있는 것을
조용히 버리거나 어긋나게 두지 않는다. 대신 모델링하지 않은 구조는 커버리지 원장
(``Document.unhandled``)에 소리 나게 기록해, 새 HWPX 요소가 나타나면 침묵 누락이
아니라 테스트 실패로 드러나게 한다.

핵심 구조 사실(실제 코퍼스 검증 완료):
  - 섹션 루트 ``hs:sec`` 밑에 문단 ``hp:p`` 가 직접 온다.
  - 문단 ``hp:p`` > 런 ``hp:run`` > (``hp:t`` | ``hp:ctrl`` | ``hp:tbl`` | ``hp:secPr``).
  - **한 문단의 텍스트는 여러 런의 여러 ``hp:t`` 파편으로 쪼개진다** — 문서 순서로
    이어붙여야 문단 문자열이 복원된다.
  - ``hp:t`` 는 혼합 콘텐츠다: ``.text`` + 자식(``hp:tab`` 등) + 자식의 ``.tail``.
    실제 파일에서 ``<hp:t>글자<hp:tab/></hp:t>`` 형태로 탭이 ``hp:t`` 안에 박힌다.
  - 표는 런 안에 중첩된다: ``hp:tbl`` > ``hp:tr`` > ``hp:tc`` > ``hp:subList`` > ``hp:p``.
    셀은 자체 문단을 가지며 표 중첩이 가능하다. 셀은 ``cellSpan``(colSpan/rowSpan)·
    ``cellAddr``(colAddr/rowAddr) 메타를 보존한다(그리드 기하는 해석하지 않음).
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


def _ns(tag: object) -> str:
    """요소 태그의 네임스페이스 URI. 없으면 빈 문자열."""
    if not isinstance(tag, str) or not tag.startswith("{"):
        return ""
    return tag[1:].split("}", 1)[0]


# ---------------------------------------------------------------- 커버리지 원장
@dataclass
class CoverageLedger:
    """모델링하지 않은 구조를 소리 나게 남기는 원장.

    각 순회 결정 지점(섹션/문단/런/표/행/셀 직속 자식)에서 HANDLED 도 KNOWN_IGNORED 도
    아닌 태그를 만나면 여기에 태그->횟수, 태그->첫 등장 경로로 기록한다. 원장이 비어야
    '모든 자식을 의식적으로 처리 또는 허용했다'는 뜻이다.
    """

    counts: "dict[str, int]" = field(default_factory=dict)
    examples: "dict[str, str]" = field(default_factory=dict)

    def record(self, tag: str, path: str) -> None:
        self.counts[tag] = self.counts.get(tag, 0) + 1
        self.examples.setdefault(tag, path)

    def classify(
        self,
        child: etree._Element,
        handled: "frozenset[str]",
        known_ignored: "frozenset[str]",
        path: str,
    ) -> str:
        """자식 요소를 분류하고, 미처리면 기록. 로컬 태그명을 반환(비-요소는 '')."""
        tag = child.tag
        if not isinstance(tag, str):  # 주석/PI 등
            return ""
        local = _local(tag)
        ns = _ns(tag)
        if ns and ns != HP_NS:
            # 본문 결정 지점에 나타난 비-hp 요소도 침묵 누락 방지 위해 기록.
            self.record(f"{{{ns}}}{local}", f"{path}/{local}")
            return local
        if local in handled or local in known_ignored:
            return local
        self.record(local, f"{path}/{local}")
        return local

    def to_dict(self) -> dict:
        return {
            "counts": {k: self.counts[k] for k in sorted(self.counts)},
            "examples": {k: self.examples[k] for k in sorted(self.examples)},
        }


# ----------------------------------- 결정 지점별 허용 태그 (작고 명시적으로 유지)
# 문단/셀 컨테이너의 직속 자식.
_HANDLED_CONTAINER = frozenset({"p"})
_IGNORE_CONTAINER: "frozenset[str]" = frozenset()

# hp:p 직속 자식.
_HANDLED_P = frozenset({"run"})
_IGNORE_P = frozenset({"linesegarray"})  # 줄 배치 레이아웃 정보, 본문 텍스트 없음

# hp:run 직속 자식.
_HANDLED_RUN = frozenset({"t", "ctrl", "tbl", "lineBreak", "tab"})
_IGNORE_RUN = frozenset({"secPr"})  # 섹션 속성 메타데이터, 본문 텍스트 아님

# hp:tbl 직속 자식.
_HANDLED_TBL = frozenset({"tr"})
_IGNORE_TBL = frozenset({"sz", "pos", "outMargin", "inMargin"})  # 표 크기/위치/여백 메타

# hp:tr 직속 자식.
_HANDLED_TR = frozenset({"tc"})
_IGNORE_TR: "frozenset[str]" = frozenset()

# hp:tc 직속 자식. cellSpan/cellAddr 는 메타로 읽으므로 HANDLED.
_HANDLED_TC = frozenset({"subList", "cellSpan", "cellAddr"})
_IGNORE_TC = frozenset({"cellSz", "cellMargin"})  # 셀 크기/여백 렌더 메타


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
    """표 셀. 자체 문단/표 블록(표 중첩 지원)과 병합 메타를 갖는다.

    ``span``/``addr`` 은 원문 ``cellSpan``/``cellAddr`` 숫자를 그대로 보존한다(그리드
    기하는 해석하지 않음 — diff/생성기가 정렬에 쓰도록).
    """

    blocks: "list[object]" = field(default_factory=list)
    span: "dict[str, int]" = field(default_factory=dict)  # {"colSpan":n,"rowSpan":n}
    addr: "dict[str, int]" = field(default_factory=dict)  # {"colAddr":n,"rowAddr":n}

    def to_dict(self) -> dict:
        return {
            "blocks": [b.to_dict() for b in self.blocks],
            "span": {k: self.span[k] for k in sorted(self.span)},
            "addr": {k: self.addr[k] for k in sorted(self.addr)},
        }


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
    """섹션/머리말/꼬리말 본문. ``blocks`` 는 문서 순서의 Paragraph/Table 목록."""

    blocks: "list[object]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"blocks": [b.to_dict() for b in self.blocks]}


@dataclass
class Document:
    """추출된 문서 전체.

    ``sections`` 는 본문 섹션(section0, section1, ...). ``headers``/``footers`` 는 본문
    문단을 실제로 담은 머리말/꼬리말 영역(스타일 전용 ``hp:head`` 파일은 제외). 본문에
    섞지 않고 종류별로 분리해 라벨링한다. ``unhandled``/``unhandled_examples`` 는 미처리
    구조 원장이다(정상 문서에서는 비어 있어야 한다).
    """

    sections: "list[Section]" = field(default_factory=list)
    headers: "list[Section]" = field(default_factory=list)
    footers: "list[Section]" = field(default_factory=list)
    unhandled: "dict[str, int]" = field(default_factory=dict)
    unhandled_examples: "dict[str, str]" = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "sections": [s.to_dict() for s in self.sections],
            "headers": [s.to_dict() for s in self.headers],
            "footers": [s.to_dict() for s in self.footers],
            "unhandled": {k: self.unhandled[k] for k in sorted(self.unhandled)},
            "unhandled_examples": {
                k: self.unhandled_examples[k] for k in sorted(self.unhandled_examples)
            },
        }


# ------------------------------------------------------------- 엔트리 선택
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


def _headerfooter_xml_names(pkg: HwpxPackage, prefix: str) -> "list[str]":
    """basename 이 ``prefix`` 로 시작하는 ``.xml`` 엔트리를 이름 정렬로 반환."""
    out = []
    for name in pkg.entries:
        base = name.rsplit("/", 1)[-1].lower()
        if base.startswith(prefix) and base.endswith(".xml"):
            out.append(name)
    return sorted(out)


def _has_body_text(root: etree._Element) -> bool:
    """루트가 본문 문단(텍스트 있는 ``hp:t``)을 실제로 담는지."""
    if _local(root.tag) == "head":
        # hp:head 는 스타일/정의 컨테이너 — 본문 아님.
        return False
    for t in root.iter(f"{{{HP_NS}}}t"):
        if (t.text or "").strip():
            return True
        for c in t:
            if (c.tail or "").strip():
                return True
    return False


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


def _blocks_from_paragraph(
    p_el: etree._Element, ledger: CoverageLedger, path: str
) -> "list[object]":
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
        if ledger.classify(run, _HANDLED_P, _IGNORE_P, path) != "run":
            continue
        run_path = f"{path}/run"
        for ch in run:
            ln = ledger.classify(ch, _HANDLED_RUN, _IGNORE_RUN, run_path)
            if ln == "t":
                txt = _text_of_t(ch)
                if txt:
                    buf.append(txt)
                    if field_stack and txt.strip():
                        nm = field_stack[-1]
                        if nm and nm not in field_names:
                            field_names.append(nm)
            elif ln == "ctrl":
                # ctrl 내부는 별도 결정 지점으로 원장에 넣지 않는다(제어 객체 세부).
                # 누름틀 경계만 관찰한다.
                for c in ch:
                    cl = _local(c.tag)
                    if cl == "fieldBegin":
                        field_stack.append((c.get("name") or "").strip())
                    elif cl == "fieldEnd":
                        if field_stack:
                            field_stack.pop()
            elif ln == "tbl":
                flush()
                blocks.append(_table_from_el(ch, ledger, f"{run_path}/tbl"))
            elif ln == "lineBreak":
                buf.append("\n")
            elif ln == "tab":
                buf.append("\t")
            # secPr 등 KNOWN_IGNORED 는 텍스트 없음 — 무시.

    if buf:
        blocks.append(Paragraph("".join(buf), list(field_names)))
    elif not blocks:
        # 완전히 빈 문단도 구조상 보존.
        blocks.append(Paragraph("", []))
    return blocks


def _blocks_from_container(
    container: etree._Element, ledger: CoverageLedger, path: str
) -> "list[object]":
    """컨테이너(섹션 루트 또는 셀 subList)의 직속 ``hp:p`` 를 순서대로 블록화."""
    blocks: "list[object]" = []
    for child in container:
        if (
            ledger.classify(child, _HANDLED_CONTAINER, _IGNORE_CONTAINER, path) == "p"
        ):
            blocks.extend(_blocks_from_paragraph(child, ledger, f"{path}/p"))
    return blocks


def _cell_span_addr(tc: etree._Element) -> "tuple[dict, dict]":
    """``hp:tc`` 에서 cellSpan(colSpan/rowSpan)·cellAddr(colAddr/rowAddr) 숫자 추출."""
    span: "dict[str, int]" = {}
    addr: "dict[str, int]" = {}
    for c in tc:
        ln = _local(c.tag)
        if ln == "cellSpan":
            for k in ("colSpan", "rowSpan"):
                v = c.get(k)
                if v is not None and v.lstrip("-").isdigit():
                    span[k] = int(v)
        elif ln == "cellAddr":
            for k in ("colAddr", "rowAddr"):
                v = c.get(k)
                if v is not None and v.lstrip("-").isdigit():
                    addr[k] = int(v)
    return span, addr


def _table_from_el(
    tbl_el: etree._Element, ledger: CoverageLedger, path: str
) -> Table:
    """``hp:tbl`` -> Table. 셀 내용은 ``hp:subList`` 밑 문단에서 추출(표 중첩 재귀)."""
    rows: "list[list[Cell]]" = []
    for tr in tbl_el:
        if ledger.classify(tr, _HANDLED_TBL, _IGNORE_TBL, path) != "tr":
            continue
        tr_path = f"{path}/tr"
        cells: "list[Cell]" = []
        for tc in tr:
            if ledger.classify(tc, _HANDLED_TR, _IGNORE_TR, tr_path) != "tc":
                continue
            tc_path = f"{tr_path}/tc"
            span, addr = _cell_span_addr(tc)
            cell_blocks: "list[object]" = []
            for sub in tc:
                if (
                    ledger.classify(sub, _HANDLED_TC, _IGNORE_TC, tc_path)
                    == "subList"
                ):
                    cell_blocks.extend(
                        _blocks_from_container(sub, ledger, f"{tc_path}/subList")
                    )
            cells.append(Cell(cell_blocks, span=span, addr=addr))
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
    """HWPX(경로/바이트/HwpxPackage)에서 본문·머리말·꼬리말을 추출해 Document 반환.

    섹션은 section0, section1, ... 순으로 결정적이다. 머리말/꼬리말은 본문 문단을 실제로
    담은 ``header*``/``footer*`` XML 만 별도 영역으로 포함하며, 스타일 전용 ``hp:head``
    (``Contents/header.xml``)는 제외한다. 미처리 구조는 원장에 남는다.
    """
    pkg = _to_package(pkg_or_path)
    doc = Document()
    ledger = CoverageLedger()
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)

    def _label(name: str) -> str:
        return name.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    for name in section_xml_names(pkg):
        root = etree.fromstring(pkg.entries[name], parser=parser)
        doc.sections.append(
            Section(blocks=_blocks_from_container(root, ledger, _label(name)))
        )

    for name in _headerfooter_xml_names(pkg, "header"):
        root = etree.fromstring(pkg.entries[name], parser=parser)
        if _has_body_text(root):
            doc.headers.append(
                Section(blocks=_blocks_from_container(root, ledger, _label(name)))
            )
    for name in _headerfooter_xml_names(pkg, "footer"):
        root = etree.fromstring(pkg.entries[name], parser=parser)
        if _has_body_text(root):
            doc.footers.append(
                Section(blocks=_blocks_from_container(root, ledger, _label(name)))
            )

    doc.unhandled = dict(ledger.counts)
    doc.unhandled_examples = dict(ledger.examples)
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
    """문서 순서(머리말->본문->꼬리말, 표 셀 내부 포함)로 모든 문단 텍스트를 반환."""
    out: "list[str]" = []
    for region in (*doc.headers, *doc.sections, *doc.footers):
        for para in _iter_blocks(region.blocks):
            out.append(para.text)
    return out


def full_text(doc: Document) -> str:
    """모든 문단 텍스트를 줄바꿈으로 이어붙인 전체 텍스트."""
    return "\n".join(iter_paragraph_texts(doc))
