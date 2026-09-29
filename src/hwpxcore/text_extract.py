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
    실제 파일에서 ``<hp:t>글자<hp:tab width="1668" leader="0" type="1"/></hp:t>`` 형태로
    탭이 ``hp:t`` 안에 박힌다. ``hp:t`` 자식의 글자 투영은 :func:`read_inline_text` 한 곳이
    정한다(아래 「``hp:t`` 인라인 자식 정책」) — 본문 추출·누름틀 값 읽기·같은 값 판정·사후
    검증이 모두 이 판독기를 쓴다.
  - 표는 런 안에 중첩된다: ``hp:tbl`` > ``hp:tr`` > ``hp:tc`` > ``hp:subList`` > ``hp:p``.
    셀은 자체 문단을 가지며 표 중첩이 가능하다. 셀은 ``cellSpan``(colSpan/rowSpan)·
    ``cellAddr``(colAddr/rowAddr) 메타를 보존한다(그리드 기하는 해석하지 않음).
  - 누름틀: ``hp:ctrl`` 안의 ``hp:fieldBegin``/``hp:fieldEnd``. 사이의 텍스트는 일반
    ``hp:t`` 다. 추출 시 값은 그대로 잡되 어느 필드 소속인지 선택적으로 기록한다.
  - 표 캡션 ``hp:caption`` 은 ``hp:tr`` 들의 형제로 ``hp:tbl`` 밑에 오며, 셀과 같은
    ``subList`` > ``hp:p`` 구조로 본문 텍스트(예: ``<표 1> …주요제원``)를 담는다 —
    표 앞 문단으로 복원한다. 그림 객체 ``hp:pic`` 은 런 안의 이미지로 본문 텍스트가 없다.

출력은 랜덤 ID(id, fieldid, charPrIDRef 등)를 전혀 담지 않아 골든 스냅샷이 실행 간
안정적이고 문서 버전 간 의미를 갖는다.

``hp:t`` 인라인 자식 정책(#1080):
  - **값 글자 요소**(:data:`VALUE_INLINE_TEXT`): ``hp:tab`` → ``\t``, ``hp:lineBreak`` →
    ``\n``, ``hp:fwSpace`` → ``U+2007``(FIGURE SPACE). 고정폭 빈칸은 한글이 빈칸 한 칸으로
    그리지만 폭이 글꼴 공백과 달라, 일반 공백(U+0020)으로 접으면 왕복이 닫히지 않는다 —
    그래서 전용 코드포인트 U+2007 로 투영한다(rhwp 파서·직렬화기와 같은 대응이고, 한컴이
    저장한 HWPX 에서 U+2007 은 늘 ``hp:fwSpace`` 요소로 나타난다). 쓰기 쪽
    (:mod:`hwpxcore.native_admission`)은 이 대응의 역으로 요소를 합성해 쓰기→읽기가
    항등이다.
  - **글자 없는 서식 표지**(:data:`TEXTLESS_INLINE_MARKERS`): 형광펜 ``markpenBegin``/
    ``markpenEnd`` 는 글자를 더하지 않는다.
  - 위 두 부류도 **빈 요소일 때만** 모델링된 것으로 친다. 그 밖의 모든 요소 자식(변경 추적
    ``insertBegin``/``deleteBegin`` 류, ``nbSpace``·``hyphen``·``titleMark``, 비-hp 요소,
    내용을 품은 탭 등)은 **미모델링**이다: 그 요소 자신의 내용은 투영에서 빠지고(``tail``
    은 이어 붙인다) 이름이 :attr:`InlineText.unmodelled` 에 남는다. 본문 추출은 그것을
    커버리지 원장에 기록하고, 누름틀 같은 값 판정·사후 검증은 ``exact`` 가 아닌 값을
    어떤 목표값과도 같다고 보지 않는다(조용한 무연산·거짓 통과 금지).
  - 주석·처리 지시(PI)는 글자가 없어 투영에서 빠진다(다른 결정 지점과 같은 규칙).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

import lxml.etree as etree

from .lineseg import LINESEG_LOCAL

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"


class PackageLike(Protocol):
    """파서 의미론 층이 아는 열린 package 의 형상 — 타입 지식만, IO 개시 없음(P2-19R).

    이 층은 ``entries`` 를 읽고(필요 시 갱신) 열린 package를 호출자에게 되돌릴 뿐이다.
    """

    entries: "dict[str, bytes]"

    def content_xml_names(self) -> "list[str]": ...


def local_name(tag: object) -> str:
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
        local = local_name(tag)
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
_IGNORE_P = frozenset({LINESEG_LOCAL})  # 줄 배치 레이아웃 정보, 본문 텍스트 없음

# hp:run 직속 자식.
_HANDLED_RUN = frozenset({"t", "ctrl", "tbl", "lineBreak", "tab"})
# secPr: 섹션 속성 메타데이터 / pic: 이미지 객체 — 본문 텍스트 없음(캡션 없는 그림).
# 실제 코퍼스의 pic 는 캡션을 품지 않는다. 만약 캡션 있는 그림이 나타나면
# test_no_silent_text_drop(모든 hp:t 를 독립 순회) 가 소리 나게 실패해 의식적 처리를 강제한다.
_IGNORE_RUN = frozenset({"secPr", "pic"})

# hp:tbl 직속 자식. caption 은 표/그림 캡션으로 본문 텍스트를 갖는다 — 별도 결정 지점 처리.
_HANDLED_TBL = frozenset({"tr", "caption"})
_IGNORE_TBL = frozenset({"sz", "pos", "outMargin", "inMargin"})  # 표 크기/위치/여백 메타

# hp:caption 직속 자식. 캡션 텍스트는 subList 밑 문단에 담긴다(표 셀과 동형 구조).
_HANDLED_CAPTION = frozenset({"subList"})
_IGNORE_CAPTION: "frozenset[str]" = frozenset()

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
    (의미론적 이름이므로 랜덤 ID 가 아니다). BOOKMARK 는 Field 가 아니라 구간 경계라 넣지
    않고, 그 밖의 ``type`` 거름은 :func:`extract_document` 의 ``field_filter`` 가 정한다.
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

    blocks: "list[Paragraph | Table]" = field(default_factory=list)
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

    blocks: "list[Paragraph | Table]" = field(default_factory=list)

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


def section_xml_names(pkg: PackageLike) -> "list[str]":
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


def _headerfooter_xml_names(pkg: PackageLike, prefix: str) -> "list[str]":
    """basename 이 ``prefix`` 로 시작하는 ``.xml`` 엔트리를 이름 정렬로 반환."""
    out = []
    for name in pkg.entries:
        base = name.rsplit("/", 1)[-1].lower()
        if base.startswith(prefix) and base.endswith(".xml"):
            out.append(name)
    return sorted(out)


def _has_body_text(root: etree._Element) -> bool:
    """루트가 본문 문단(텍스트 있는 ``hp:t``)을 실제로 담는지."""
    if local_name(root.tag) == "head":
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
#: 값 글자를 이루는 ``hp:t`` 인라인 요소 → 글자 투영(모듈 docstring 「인라인 자식 정책」).
VALUE_INLINE_TEXT: "dict[str, str]" = {
    "tab": "\t",
    "lineBreak": "\n",
    "fwSpace": "\u2007",
}
#: 글자를 더하지 않는 ``hp:t`` 안 서식 표지(빈 요소일 때만 모델링된 것으로 친다).
TEXTLESS_INLINE_MARKERS = frozenset({"markpenBegin", "markpenEnd"})


@dataclass(frozen=True)
class InlineText:
    """``hp:t`` 파편(들)의 정본 글자 투영.

    ``unmodelled`` 는 투영이 의미를 정하지 못한 자식 요소 이름(문서 순서, 비-hp 요소는
    ``{ns}local``)이다. 비어 있어야 ``text`` 가 파편의 글자를 **정확히** 나타낸다.
    """

    text: str
    unmodelled: "tuple[str, ...]" = ()

    @property
    def exact(self) -> bool:
        return not self.unmodelled


def _inline_child_text(child: etree._Element) -> "str | None":
    """모델링된 인라인 자식의 글자 투영. 미모델링이면 ``None``."""
    tag = child.tag
    if not isinstance(tag, str):  # 주석·PI — 글자 없음
        return ""
    if _ns(tag) != HP_NS or len(child) or child.text:
        return None
    ln = local_name(tag)
    if ln in VALUE_INLINE_TEXT:
        return VALUE_INLINE_TEXT[ln]
    if ln in TEXTLESS_INLINE_MARKERS:
        return ""
    return None


def _unmodelled_name(child: etree._Element) -> str:
    ns = _ns(child.tag)
    local = local_name(child.tag)
    return local if ns == HP_NS else f"{{{ns}}}{local}"


def read_inline_text(t_el: etree._Element) -> InlineText:
    """``hp:t`` 한 파편의 정본 판독 — 인라인 자식 정책의 단일 출처."""
    parts: "list[str]" = [t_el.text or ""]
    unmodelled: "list[str]" = []
    for ch in t_el:
        projected = _inline_child_text(ch)
        if projected is None:
            unmodelled.append(_unmodelled_name(ch))
        else:
            parts.append(projected)
        if ch.tail:
            parts.append(ch.tail)
    return InlineText("".join(parts), tuple(unmodelled))


def read_field_text(texts: "Iterable[etree._Element]") -> InlineText:
    """누름틀 값 ``hp:t`` 파편들을 문서 순서로 이어 붙인 정본 판독.

    파편 사이에는 아무것도 넣지 않는다(한 값의 조각). 값 읽기·같은 값 판정·사후 검증이
    모두 이 함수를 쓴다 — 경로마다 같은 문서를 다르게 읽지 않게 한다(#1080).
    """
    reads = [read_inline_text(t) for t in texts]
    return InlineText(
        "".join(r.text for r in reads),
        tuple(name for r in reads for name in r.unmodelled),
    )


def text_of_t(t_el: etree._Element) -> str:
    """``hp:t`` 혼합 콘텐츠를 문자열로 복원(:func:`read_inline_text` 의 글자 투영)."""
    return read_inline_text(t_el).text


def _field_label(
    begin: etree._Element, field_filter: "Callable[[str | None], bool] | None"
) -> str:
    """``Paragraph.fields`` 에 실을 누름틀 이름. 싣지 않을 경계는 빈 문자열.

    BOOKMARK ``fieldBegin`` 은 Field 가 아니라 구간 경계다(형식 사실 — 공용 Field
    resolver 와 같은 구분). 어느 ``type`` 이 채울 누름틀인지는 제품 층이 ``field_filter``
    로 정한다(#931) — 이 커널은 그 규칙을 소유하지 않는다.
    """
    field_type = begin.get("type")
    if field_type == "BOOKMARK":
        return ""
    if field_filter is not None and not field_filter(field_type):
        return ""
    return (begin.get("name") or "").strip()


def _close_field(
    field_stack: "list[tuple[str | None, str]]", begin_ref: "str | None"
) -> None:
    """``fieldEnd`` 가 닫는 경계를 스택에서 뗀다.

    ``beginIDRef`` 가 있으면 그 ``id`` 의 경계를 닫는다 — 다른 문단에서 열린 BOOKMARK 의
    끝이 이 문단의 누름틀을 잘못 닫지 않게. 짝 id 가 이 문단에 없으면 아무것도 닫지
    않는다. 참조가 없는 형상만 가장 안쪽을 닫는다.
    """
    if begin_ref is None:
        if field_stack:
            field_stack.pop()
        return
    for index in range(len(field_stack) - 1, -1, -1):
        if field_stack[index][0] == begin_ref:
            del field_stack[index]
            return


def _blocks_from_paragraph(
    p_el: etree._Element,
    ledger: CoverageLedger,
    path: str,
    field_filter: "Callable[[str | None], bool] | None" = None,
) -> "list[Paragraph | Table]":
    """단일 ``hp:p`` 를 블록 목록으로 변환.

    문단 안에 표가 끼어들면 앞 텍스트를 Paragraph 로 flush 한 뒤 Table 을 넣어 문서
    순서를 보존한다. 텍스트도 표도 없는 문단은 빈 Paragraph 로 보존한다.
    """
    blocks: "list[Paragraph | Table]" = []
    buf: "list[str]" = []
    field_names: "list[str]" = []
    # (fieldBegin@id, 실을 이름 또는 "") — fieldEnd@beginIDRef 로 짝을 찾는다.
    field_stack: "list[tuple[str | None, str]]" = []

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
                inline = read_inline_text(ch)
                # hp:t 도 결정 지점이다 — 미모델링 인라인 자식은 원장에 소리 나게 남긴다.
                for name in inline.unmodelled:
                    ledger.record(name, f"{run_path}/t/{local_name(name)}")
                txt = inline.text
                if txt:
                    buf.append(txt)
                    nm = next((label for _, label in reversed(field_stack) if label), "")
                    if nm and txt.strip() and nm not in field_names:
                        field_names.append(nm)
            elif ln == "ctrl":
                # ctrl 내부는 별도 결정 지점으로 원장에 넣지 않는다(제어 객체 세부).
                # 누름틀 경계만 관찰한다.
                for c in ch:
                    cl = local_name(c.tag)
                    if cl == "fieldBegin":
                        field_stack.append((c.get("id"), _field_label(c, field_filter)))
                    elif cl == "fieldEnd":
                        _close_field(field_stack, c.get("beginIDRef"))
            elif ln == "tbl":
                flush()
                cap_blocks, table = _table_from_el(
                    ch, ledger, f"{run_path}/tbl", field_filter
                )
                blocks.extend(cap_blocks)  # 캡션 문단을 표 앞(문서 순서)에 배치
                blocks.append(table)
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
    container: etree._Element,
    ledger: CoverageLedger,
    path: str,
    field_filter: "Callable[[str | None], bool] | None" = None,
) -> "list[Paragraph | Table]":
    """컨테이너(섹션 루트 또는 셀 subList)의 직속 ``hp:p`` 를 순서대로 블록화."""
    blocks: "list[Paragraph | Table]" = []
    for child in container:
        if (
            ledger.classify(child, _HANDLED_CONTAINER, _IGNORE_CONTAINER, path) == "p"
        ):
            blocks.extend(
                _blocks_from_paragraph(child, ledger, f"{path}/p", field_filter)
            )
    return blocks


def _cell_span_addr(tc: etree._Element) -> "tuple[dict, dict]":
    """``hp:tc`` 에서 cellSpan(colSpan/rowSpan)·cellAddr(colAddr/rowAddr) 숫자 추출."""
    span: "dict[str, int]" = {}
    addr: "dict[str, int]" = {}
    for c in tc:
        ln = local_name(c.tag)
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


def _caption_blocks(
    cap_el: etree._Element,
    ledger: CoverageLedger,
    path: str,
    field_filter: "Callable[[str | None], bool] | None" = None,
) -> "list[Paragraph | Table]":
    """``hp:caption`` -> 캡션 문단 블록 목록. 텍스트는 ``hp:subList`` 밑 문단에 담긴다.

    캡션은 표/그림에 붙는 제목·설명(예: ``<표 1> 유압식 잭(30톤) 주요제원``)으로 본문
    텍스트다. 셀 subList 와 동형이라 같은 컨테이너 헬퍼로 문단을 복원한다.
    """
    blocks: "list[Paragraph | Table]" = []
    for sub in cap_el:
        if ledger.classify(sub, _HANDLED_CAPTION, _IGNORE_CAPTION, path) == "subList":
            blocks.extend(
                _blocks_from_container(sub, ledger, f"{path}/subList", field_filter)
            )
    return blocks


def _table_from_el(
    tbl_el: etree._Element,
    ledger: CoverageLedger,
    path: str,
    field_filter: "Callable[[str | None], bool] | None" = None,
) -> "tuple[list[Paragraph | Table], Table]":
    """``hp:tbl`` -> (캡션 블록, Table). 셀 내용은 ``hp:subList`` 밑 문단에서 추출(중첩 재귀).

    캡션 ``hp:caption`` 은 ``hp:tr`` 들의 형제로 표 앞에 온다. 문서 순서를 지키도록 캡션
    문단을 별도 블록으로 돌려주고, 호출부가 Table 앞에 배치한다.
    """
    rows: "list[list[Cell]]" = []
    caption_blocks: "list[Paragraph | Table]" = []
    for child in tbl_el:
        ln = ledger.classify(child, _HANDLED_TBL, _IGNORE_TBL, path)
        if ln == "caption":
            caption_blocks.extend(
                _caption_blocks(child, ledger, f"{path}/caption", field_filter)
            )
            continue
        if ln != "tr":
            continue
        tr_path = f"{path}/tr"
        cells: "list[Cell]" = []
        for tc in child:
            if ledger.classify(tc, _HANDLED_TR, _IGNORE_TR, tr_path) != "tc":
                continue
            tc_path = f"{tr_path}/tc"
            span, addr = _cell_span_addr(tc)
            cell_blocks: "list[Paragraph | Table]" = []
            for sub in tc:
                if (
                    ledger.classify(sub, _HANDLED_TC, _IGNORE_TC, tc_path)
                    == "subList"
                ):
                    cell_blocks.extend(
                        _blocks_from_container(
                            sub, ledger, f"{tc_path}/subList", field_filter
                        )
                    )
            cells.append(Cell(cell_blocks, span=span, addr=addr))
        rows.append(cells)
    return caption_blocks, Table(rows)


# ------------------------------------------------------------------ 공개 API
def require_package(obj: object) -> PackageLike:
    """열린 package 만 통과하는 덕타이핑 관문 — 경로/바이트 수용 뒷문 없음(P2-19R, #576).

    파서 의미론 층은 파일 IO 를 개시하지 않는다. isinstance(HwpxPackage) 검사는
    import 자체가 EXTERNAL edge 라 쓰지 않고, ``entries`` 보유 여부로만 판별한다.
    """
    if hasattr(obj, "entries"):
        return obj  # type: ignore[return-value] — 덕타이핑 관문(구조 검사는 entries 하나)
    raise TypeError(
        "열린 HWPX package 가 필요합니다 — 호출자가 경로/바이트를 먼저 "
        f"package로 변환해 넘기세요: {type(obj)!r}"
    )


def extract_document(
    pkg: object,
    *,
    field_filter: "Callable[[str | None], bool] | None" = None,
) -> Document:
    """열린 HWPX package 에서 본문·머리말·꼬리말을 추출해 Document 반환.

    **package-only**(P2-19R): 호출자가 경로/바이트를 열린 package로 변환해 넘긴다.
    섹션은 section0, section1, ... 순으로 결정적이다. 머리말/꼬리말은 본문 문단을
    실제로 담은 ``header*``/``footer*`` XML 만 별도 영역으로 포함하며, 스타일 전용
    ``hp:head`` (``Contents/header.xml``)는 제외한다. 미처리 구조는 원장에 남는다.

    ``field_filter`` 는 ``fieldBegin@type`` 을 받아 그 경계 이름을 ``Paragraph.fields``
    에 실을지 정한다(제품 층의 채움 대상 규칙, #931). ``None`` 이면 BOOKMARK 가 아닌
    모든 Field 를 싣는다.
    """
    pkg = require_package(pkg)
    doc = Document()
    ledger = CoverageLedger()
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)

    def _label(name: str) -> str:
        return name.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    for name in section_xml_names(pkg):
        root = etree.fromstring(pkg.entries[name], parser=parser)
        doc.sections.append(
            Section(
                blocks=_blocks_from_container(
                    root, ledger, _label(name), field_filter
                )
            )
        )

    for name in _headerfooter_xml_names(pkg, "header"):
        root = etree.fromstring(pkg.entries[name], parser=parser)
        if _has_body_text(root):
            doc.headers.append(
                Section(
                    blocks=_blocks_from_container(
                        root, ledger, _label(name), field_filter
                    )
                )
            )
    for name in _headerfooter_xml_names(pkg, "footer"):
        root = etree.fromstring(pkg.entries[name], parser=parser)
        if _has_body_text(root):
            doc.footers.append(
                Section(
                    blocks=_blocks_from_container(
                        root, ledger, _label(name), field_filter
                    )
                )
            )

    doc.unhandled = dict(ledger.counts)
    doc.unhandled_examples = dict(ledger.examples)
    return doc


def _iter_blocks(blocks: "list[Paragraph | Table]"):
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
