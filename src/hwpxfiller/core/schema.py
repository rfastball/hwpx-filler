"""템플릿 스키마 추출 — 얕은 ``required_fields()`` 를 필드·타입·위치·라벨·표 영역까지
담은 구조화 스키마로 확장한다. 트랙 B(매핑 UI·위저드·반복 표)의 공용 토대.

**왜 별도 순회인가.** ``text_extract`` 의 ``Paragraph.fields`` 는 *값이 있는* 누름틀만
남긴다(값 없는 빈 placeholder 는 누락). 하지만 템플릿은 대개 빈 누름틀이다 —
``required_fields()`` 가 진실이다. 그래서 스키마 추출은 ``fieldBegin`` 경계를 직접
순회해 빈 누름틀까지 빠짐없이 잡되, 문단/셀 텍스트를 라벨 힌트로 함께 수집한다.

주입 대상과 정확히 일치시키려고 순회 표면은 ``pkg.content_xml_names()``
(section*/header*/footer*)로 고정한다 — 엔진이 실제로 값을 넣는 XML 집합.

출력은 랜덤 ID 를 전혀 담지 않아(필드 이름·라벨·타입·표 기하만) 스냅샷이 안정적이다.
설계 원칙: **충실도 완전 · 기능 최소 · 미처리는 시끄럽게**(``unhandled`` 원장 승계).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from .text_extract import (
    HP_NS,
    _local,
    _text_of_t,
    _to_package,
    extract_document,
    iter_paragraph_texts,
)

# -------------------------------------------------------------- 타입 추론 규칙
# 필드 *이름* 의 부분 문자열로 의미 타입을 추정한다(한글 업무 문서 관용어 기반).
# 순서가 우선순위다: 앞 규칙이 먼저 매칭한다. "담당자 전화번호" 는 전화(phone)가
# 번호(number)보다 앞서 이겨야 하므로 phone 을 number 앞에 둔다.
_TYPE_RULES: "tuple[tuple[str, tuple[str, ...]], ...]" = (
    ("date", ("일시", "일자", "날짜", "기한", "기간", "기일", "연월일", "년월일")),
    ("amount", ("금액", "가액", "예산", "가격", "단가", "비용", "요금", "대금", "원가", "공사비")),
    ("phone", ("전화", "연락처", "팩스", "휴대폰", "핸드폰")),
    ("number", ("번호", "수량", "개수", "차수", "횟수", "건수", "인원")),
)

# 라벨 힌트로 보관할 문맥 텍스트 최대 길이(스키마를 정갈하게 유지).
_CONTEXT_MAX = 120

# 본문 평문에 남은 이중중괄호 placeholder(실제 누름틀이 아님) 탐지.
_TOKEN_RE = re.compile(r"\{\{([^{}]+)\}\}")


def _infer_type(name: str) -> str:
    """필드 이름에서 의미 타입 추정. 매칭 없으면 ``"text"``."""
    for type_name, keywords in _TYPE_RULES:
        if any(kw in name for kw in keywords):
            return type_name
    return "text"


# ----------------------------------------------------------------- data model
@dataclass
class FieldSpec:
    """단일 누름틀 필드의 구조화 명세.

    ``context`` 는 필드를 품은 문단/셀의 텍스트(사람이 매핑 UI 에서 볼 라벨 힌트).
    빈 템플릿에선 값이 비어 라벨(예: ``"계약명:"``)만 남는 경우가 흔하다.
    ``in_table`` 은 이 필드가 표 셀 안에 등장하는지 — 반복 영역(메일머지 2.0) 후보 신호.
    """

    name: str
    inferred_type: str
    occurrences: int
    in_table: bool
    context: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "inferred_type": self.inferred_type,
            "occurrences": self.occurrences,
            "in_table": self.in_table,
            "context": self.context,
        }


@dataclass
class TableRegion:
    """필드를 담은 표 하나 — 행 수 가변 반복 채우기(3-①)의 후보 영역.

    ``rows``/``cols`` 는 직속 ``hp:tr``/``hp:tc`` 기하(중첩 표는 자체 영역으로 분리).
    ``field_names`` 는 이 표(가장 가까운 표) 안에 등장하는 필드의 순서 있는 중복 없는 목록.
    """

    field_names: "list[str]" = field(default_factory=list)
    rows: int = 0
    cols: int = 0

    def to_dict(self) -> dict:
        return {
            "field_names": list(self.field_names),
            "rows": self.rows,
            "cols": self.cols,
        }


@dataclass
class TemplateSchema:
    """템플릿 스키마 전체.

    ``fields`` 는 문서 등장 순서의 필드 명세. ``table_regions`` 는 필드를 품은 표 목록.
    ``stray_tokens`` 는 본문 평문에 남은 미치환 ``{{...}}``(실제 누름틀이 아닌 잔존물 —
    검증 경고용). ``unhandled`` 는 text_extract 커버리지 원장 승계(정상 문서에선 빈 dict).
    """

    fields: "list[FieldSpec]" = field(default_factory=list)
    table_regions: "list[TableRegion]" = field(default_factory=list)
    stray_tokens: "list[str]" = field(default_factory=list)
    unhandled: "dict[str, int]" = field(default_factory=dict)

    def field_names(self) -> "list[str]":
        """등장 순서의 필드 이름 목록(``required_fields()`` 상위호환)."""
        return [f.name for f in self.fields]

    def to_dict(self) -> dict:
        return {
            "fields": [f.to_dict() for f in self.fields],
            "table_regions": [t.to_dict() for t in self.table_regions],
            "stray_tokens": list(self.stray_tokens),
            "unhandled": {k: self.unhandled[k] for k in sorted(self.unhandled)},
        }


# ------------------------------------------------------------- 필드 직속 추출
def _clean_field_name(raw: object) -> str:
    """``fieldBegin@name`` 정규화 — 공백 제거 + ``{{ }}`` 벗기기."""
    if not isinstance(raw, str):
        return ""
    return raw.strip().replace("{{", "").replace("}}", "")


def _paragraph_direct(p_el: etree._Element) -> "tuple[str, list[str]]":
    """``hp:p`` 의 *직속* 텍스트와 필드명을 반환(중첩 ``hp:tbl`` 로 내려가지 않음).

    중첩 표 셀의 텍스트·필드는 셀 자신의 ``hp:p`` 소관이므로 여기서 제외한다 —
    바깥 문단 라벨이 셀 내용을 삼키지 않고, 필드가 이중 집계되지 않게 한다.
    """
    parts: "list[str]" = []
    names: "list[str]" = []
    seen: "set[str]" = set()
    for run in p_el:
        if _local(run.tag) != "run":
            continue
        for ch in run:
            ln = _local(ch.tag)
            if ln == "t":
                parts.append(_text_of_t(ch))
            elif ln == "ctrl":
                for c in ch:
                    if _local(c.tag) == "fieldBegin":
                        nm = _clean_field_name(c.get("name"))
                        if nm and nm not in seen:
                            seen.add(nm)
                            names.append(nm)
            elif ln == "tab":
                parts.append("\t")
            elif ln == "lineBreak":
                parts.append("\n")
            # tbl: 중첩 표는 건너뛴다(바깥 재귀가 셀 문단을 따로 방문).
    return "".join(parts), names


@dataclass
class _Occ:
    """필드 1회 등장 — 이름 + 라벨 문맥 + 소속 표 id(없으면 None)."""

    name: str
    context: str
    table_id: "int | None"


def _walk_content(root: etree._Element) -> "tuple[list[_Occ], dict[int, TableRegion]]":
    """단일 content XML 을 순회해 (필드 등장 목록, 표 id->TableRegion) 반환.

    표에 들어가면 ``table_id`` 가 갱신돼 필드가 *가장 가까운* 표에 귀속된다. 중첩 표는
    각자 별개 id 를 받는다. 문단 텍스트는 직속만 문맥으로 삼는다(_paragraph_direct).
    """
    occ: "list[_Occ]" = []
    regions: "dict[int, TableRegion]" = {}
    counter = [0]

    def walk(el: etree._Element, table_id: "int | None") -> None:
        local = _local(el.tag)
        if local == "p":
            text, fnames = _paragraph_direct(el)
            label = text.strip()[:_CONTEXT_MAX]
            for fn in fnames:
                occ.append(_Occ(fn, label, table_id))
                if table_id is not None:
                    reg = regions[table_id]
                    if fn not in reg.field_names:
                        reg.field_names.append(fn)

        current = table_id
        if local == "tbl":
            counter[0] += 1
            current = counter[0]
            trs = [c for c in el if _local(c.tag) == "tr"]
            cols = max(
                (sum(1 for tc in tr if _local(tc.tag) == "tc") for tr in trs),
                default=0,
            )
            regions[current] = TableRegion(rows=len(trs), cols=cols)

        for ch in el:
            if isinstance(ch.tag, str):
                walk(ch, current)

    walk(root, None)
    return occ, regions


# ------------------------------------------------------------------ 공개 API
def extract_schema(pkg_or_path: object) -> TemplateSchema:
    """HWPX(경로/바이트/HwpxPackage)에서 템플릿 스키마를 추출.

    필드는 주입 대상(``content_xml_names``)을 직접 순회해 빈 누름틀까지 잡고, 이름별로
    등장 횟수·표 소속·라벨 문맥을 병합한다. ``stray_tokens``·``unhandled`` 는
    text_extract 문서 모델에서 파생한다(본문 평문 스캔 + 커버리지 원장).
    """
    pkg = _to_package(pkg_or_path)
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)

    order: "list[str]" = []
    merged: "dict[str, FieldSpec]" = {}
    table_regions: "list[TableRegion]" = []

    for name in pkg.content_xml_names():
        root = etree.fromstring(pkg.entries[name], parser=parser)
        occ, regions = _walk_content(root)
        for o in occ:
            spec = merged.get(o.name)
            if spec is None:
                spec = FieldSpec(
                    name=o.name,
                    inferred_type=_infer_type(o.name),
                    occurrences=0,
                    in_table=False,
                    context="",
                )
                merged[o.name] = spec
                order.append(o.name)
            spec.occurrences += 1
            if o.table_id is not None:
                spec.in_table = True
            if not spec.context and o.context:
                spec.context = o.context
        # 필드를 실제로 담은 표만 반복 후보로 신고(빈 표는 잡음).
        for tid in sorted(regions):
            reg = regions[tid]
            if reg.field_names:
                table_regions.append(reg)

    # 미치환 {{}} 잔존 + 커버리지 원장은 문서 모델에서 파생.
    doc = extract_document(pkg)
    real_names = set(order)
    stray: "list[str]" = []
    stray_seen: "set[str]" = set()
    for text in iter_paragraph_texts(doc):
        for m in _TOKEN_RE.finditer(text):
            tok = m.group(1).strip()
            if tok and tok not in real_names and tok not in stray_seen:
                stray_seen.add(tok)
                stray.append(tok)

    return TemplateSchema(
        fields=[merged[n] for n in order],
        table_regions=table_regions,
        stray_tokens=stray,
        unhandled=dict(doc.unhandled),
    )
