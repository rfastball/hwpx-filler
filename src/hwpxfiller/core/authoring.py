"""저작 보조 — 텍스트 토큰 → 누름틀 컴파일. ``fields.set_field`` 의 역연산.

작성자는 한글에서 평문 ``{{계약명}}`` 을 그냥 타이핑한다(누구나 즉시·눈에 보이게·리뷰
가능). 이 모듈이 그 텍스트 토큰을 진짜 누름틀(``hp:fieldBegin``/``fieldEnd``)로
컴파일한다 — 한글에서 누름틀을 수동 삽입·명명하던 최대 병목을 없앤다.

**명시성 원칙.** 파서 철학("충실도 완전·누락은 시끄럽게")의 저작 확장:
- ``scan_tokens`` 는 읽기 전용 미리보기(무엇을 바꿀지 먼저 보여준다).
- ``compile_document`` 만 워크북을 변형하고, 못 바꾸는 토큰(파편에 걸침·복합 런)은
  조용히 넘기지 않고 skipped 로 소리 나게 신고한다.
- **멱등**: 이미 누름틀 안에 든 토큰(field 영역 depth>0)은 재컴파일하지 않는다.

**충실도.** 생성 누름틀은 실제 코퍼스 속성을 미러링한다:
``fieldBegin@type=CLICK_HERE, editable=1, dirty=1, zorder=-1, metaTag=""`` +
``fieldEnd@beginIDRef=<begin id>`` + 공유 ``fieldid``. id/fieldid 는 해당 XML 의 기존
정수 id 최댓값 위에서 결정적으로 할당(입력 같으면 출력 같다). 값 런 텍스트는 원본
토큰 ``{{X}}`` 리터럴을 유지한다(코퍼스 관례 — 채우기 전까지 placeholder 가 보인다).

**MVP 경계.** 토큰이 단일 ``hp:t`` 의 ``.text`` 안에 온전히 있고 그 런이 단순할
(hp:t 하나, 인라인 자식 없음) 때만 컴파일한다. 파편에 걸친 토큰·복합 런은 skipped 로
신고(작성자가 손봐야 할 소수 케이스). 갓 타이핑한 토큰은 대개 단일 런에 온다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from .text_extract import HP_NS, _local, _to_package

_TOKEN_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_ID_ATTRS = ("id", "fieldid", "beginIDRef", "instId", "endIDRef")
_CONTEXT_MAX = 120


def _hp(tag: str) -> str:
    return f"{{{HP_NS}}}{tag}"


# ------------------------------------------------------------------ 리포트 모델
@dataclass
class TokenSite:
    """토큰 1개 등장 지점 — 미리보기·리포트용.

    ``compilable`` 이 False 면 ``reason`` 에 이유(파편·복합 런). ``name`` 은 ``{{}}`` 벗긴
    필드명(부분 토큰이라 알 수 없으면 원문 조각).
    """

    name: str
    context: str
    compilable: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "context": self.context,
            "compilable": self.compilable,
            "reason": self.reason,
        }


@dataclass
class CompileReport:
    """컴파일 결과 요약.

    ``compilable`` 은 미리보기(scan)용 — 바꿀 수 있는 토큰 사이트(context 포함).
    ``compiled`` 는 apply 시 실제로 변환된 필드명. ``skipped`` 는 두 모드 공통.
    """

    compiled: "list[str]" = field(default_factory=list)  # 실제 변환된 필드명(순서)
    compilable: "list[TokenSite]" = field(default_factory=list)  # 미리보기 사이트
    skipped: "list[TokenSite]" = field(default_factory=list)  # 못 바꾼 토큰
    modified: bool = False

    def to_dict(self) -> dict:
        return {
            "compiled": list(self.compiled),
            "skipped": [s.to_dict() for s in self.skipped],
            "modified": self.modified,
        }


# ------------------------------------------------------------ 순회 헬퍼
def _iter_paragraphs(root: etree._Element):
    """content XML 안의 모든 ``hp:p`` 를 yield(표 셀 중첩 포함)."""
    for el in root.iter(_hp("p")):
        yield el


def _paragraph_text(p_el: etree._Element) -> str:
    """문단의 직속 텍스트(라벨 힌트) — 중첩 표는 내려가지 않는다."""
    parts: "list[str]" = []
    for run in p_el:
        if _local(run.tag) != "run":
            continue
        for ch in run:
            ln = _local(ch.tag)
            if ln == "t":
                if ch.text:
                    parts.append(ch.text)
            elif ln == "tbl":
                return "".join(parts)  # 표 전까지만
    return "".join(parts)


def _clean_name(raw: str) -> str:
    return raw.strip()


def _simple_t(run: etree._Element) -> "etree._Element | None":
    """런이 '단순'하면(hp:t 하나 + 인라인 자식 없음) 그 hp:t 반환, 아니면 None."""
    ts = [c for c in run if _local(c.tag) == "t"]
    non_t = [c for c in run if isinstance(c.tag, str) and _local(c.tag) != "t"]
    if len(ts) != 1 or non_t:
        return None
    t = ts[0]
    if len(t):  # hp:tab/lineBreak 등 인라인 자식 → 단순하지 않음
        return None
    return t


# ------------------------------------------------------------- id 결정적 할당
def _make_id_allocator(root: etree._Element):
    """XML 의 기존 정수 id 최댓값 위에서 (begin_id, field_id) 쌍을 결정적 발급."""
    max_id = 0
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for a in _ID_ATTRS:
            v = el.get(a)
            if v and v.lstrip("-").isdigit():
                max_id = max(max_id, abs(int(v)))
    counter = [max_id]

    def alloc() -> "tuple[int, int]":
        counter[0] += 1
        begin_id = counter[0]
        counter[0] += 1
        field_id = counter[0]
        return begin_id, field_id

    return alloc


# ------------------------------------------------------------- 런 팩토리
def _text_run(attrs: "dict[str, str]", text: str) -> etree._Element:
    run = etree.Element(_hp("run"), attrs)
    t = etree.SubElement(run, _hp("t"))
    t.text = text
    return run


def _begin_run(attrs: "dict[str, str]", name: str, begin_id: int, field_id: int) -> etree._Element:
    run = etree.Element(_hp("run"), attrs)
    ctrl = etree.SubElement(run, _hp("ctrl"))
    fb = etree.SubElement(ctrl, _hp("fieldBegin"))
    fb.set("id", str(begin_id))
    fb.set("type", "CLICK_HERE")
    fb.set("name", name)
    fb.set("editable", "1")
    fb.set("dirty", "1")
    fb.set("zorder", "-1")
    fb.set("fieldid", str(field_id))
    fb.set("metaTag", "")
    return run


def _end_run(attrs: "dict[str, str]", begin_id: int, field_id: int) -> etree._Element:
    run = etree.Element(_hp("run"), attrs)
    ctrl = etree.SubElement(run, _hp("ctrl"))
    fe = etree.SubElement(ctrl, _hp("fieldEnd"))
    fe.set("beginIDRef", str(begin_id))
    fe.set("fieldid", str(field_id))
    return run


# ------------------------------------------------------------- 문단 처리
def _process_paragraph(
    p_el: etree._Element, alloc, apply: bool, report: CompileReport
) -> None:
    """한 문단의 depth-0 토큰을 스캔(+ apply 면 컴파일). field 영역 안 토큰은 건너뛴다."""
    context = _paragraph_text(p_el).strip()[:_CONTEXT_MAX]
    depth = 0
    # 런을 스냅샷(자식 수정 중 순회 안정성). 문단 직속 런만.
    runs = [c for c in p_el if _local(c.tag) == "run"]
    for run in runs:
        # 이 런이 field 경계(ctrl>fieldBegin/End)를 품는지 먼저 반영.
        opens = 0
        closes = 0
        for ch in run:
            if _local(ch.tag) == "ctrl":
                for c in ch:
                    cl = _local(c.tag)
                    if cl == "fieldBegin":
                        opens += 1
                    elif cl == "fieldEnd":
                        closes += 1

        run_depth = depth  # 이 런의 텍스트가 놓인 시작 depth
        depth += opens - closes

        if run_depth > 0:
            continue  # 이미 누름틀 안 — 멱등성 위해 건너뜀

        t = _simple_t(run)
        if t is None:
            # 복합 런에 토큰이 있으면 신고.
            joined = "".join((c.text or "") for c in run if _local(c.tag) == "t")
            if "{{" in joined:
                report.skipped.append(
                    TokenSite(joined.strip()[:40], context, False, "복합 런(수동 처리)")
                )
            continue

        text = t.text or ""
        matches = list(_TOKEN_RE.finditer(text))
        if not matches:
            if "{{" in text:  # 열림만 있고 닫힘 없음 → 파편에 걸친 토큰
                report.skipped.append(
                    TokenSite(text.strip()[:40], context, False, "토큰이 파편에 걸침")
                )
            continue

        if not apply:
            for m in matches:
                report.compilable.append(
                    TokenSite(_clean_name(m.group(1)), context, True)
                )
            continue

        # ---- 실제 컴파일: 런을 begin/value/end + 전후 텍스트 런으로 치환 ----
        attrs = dict(run.attrib)
        new_runs: "list[etree._Element]" = []
        pos = 0
        for m in matches:
            before = text[pos:m.start()]
            if before:
                new_runs.append(_text_run(attrs, before))
            name = _clean_name(m.group(1))
            begin_id, field_id = alloc()
            new_runs.append(_begin_run(attrs, name, begin_id, field_id))
            new_runs.append(_text_run(attrs, m.group(0)))  # placeholder 유지
            new_runs.append(_end_run(attrs, begin_id, field_id))
            report.compiled.append(name)
            pos = m.end()
        after = text[pos:]
        if after:
            new_runs.append(_text_run(attrs, after))

        idx = p_el.index(run)
        p_el.remove(run)
        for offset, nr in enumerate(new_runs):
            p_el.insert(idx + offset, nr)


# ------------------------------------------------------------------ 공개 API
def scan_tokens(pkg_or_path: object) -> "list[TokenSite]":
    """읽기 전용 미리보기 — 컴파일 가능한 토큰과 못 바꾸는 토큰을 모두 나열.

    이미 누름틀 안에 든 토큰(field 값)은 제외한다. 워크북을 전혀 변형하지 않는다.
    """
    pkg = _to_package(pkg_or_path)
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    sites: "list[TokenSite]" = []
    for name in pkg.content_xml_names():
        root = etree.fromstring(pkg.entries[name], parser=parser)
        report = CompileReport()
        for p in _iter_paragraphs(root):
            _process_paragraph(p, alloc=None, apply=False, report=report)
        sites.extend(report.compilable)
        sites.extend(report.skipped)
    return sites


def compile_document(pkg_or_path: object) -> "tuple[object, CompileReport]":
    """토큰을 누름틀로 컴파일. (변형된 HwpxPackage, 리포트) 반환.

    ``apply`` 는 항상 참 — 미리보기는 ``scan_tokens`` 를 쓴다. 컴파일된 XML 만 교체하고,
    바뀐 게 없으면 ``modified=False``.
    """
    pkg = _to_package(pkg_or_path)
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    report = CompileReport()
    for name in pkg.content_xml_names():
        root = etree.fromstring(pkg.entries[name], parser=parser)
        alloc = _make_id_allocator(root)
        before = len(report.compiled)
        for p in _iter_paragraphs(root):
            _process_paragraph(p, alloc=alloc, apply=True, report=report)
        if len(report.compiled) > before:
            pkg.entries[name] = etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
    report.modified = bool(report.compiled)
    return pkg, report
