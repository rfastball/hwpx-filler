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

**파편 정규화.** 인접한 단순 텍스트 런의 ``charPrIDRef`` 가 같으면 하나의 논리 런으로
보고 토큰을 찾는다. 적용할 때는 오프셋을 원래 런으로 되돌려 각 조각의 속성과 텍스트를
보존한다. 탭·줄바꿈·제어 요소 또는 서로 다른 ``charPrIDRef`` 를 가로지르는 토큰은
서식을 추측하지 않고 skipped 로 신고한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from hwpxcore.text_extract import HP_NS, _local, _to_package

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


def _run_shape(run: etree._Element):
    """런의 모양을 (단일 hp:t 여부, hp:t 목록, field 경계 opens/closes)로 요약.

    ``simple`` = hp:t 하나뿐 + ctrl/기타 자식 없음 + 그 hp:t 에 인라인 자식 없음
    (컴파일로 통째 치환 가능한 모양). 코퍼스처럼 누름틀이 한 런에 인라인(t·ctrl·t·
    ctrl·t)인 경우는 simple 이 아니다.
    """
    ts = [c for c in run if _local(c.tag) == "t"]
    ctrls = [c for c in run if _local(c.tag) == "ctrl"]
    others = [
        c for c in run if isinstance(c.tag, str) and _local(c.tag) not in ("t", "ctrl")
    ]
    simple = len(ts) == 1 and not ctrls and not others and len(ts[0]) == 0
    return simple, ts


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


def _text_slices(
    runs: "list[etree._Element]", start: int, end: int
) -> "list[etree._Element]":
    """논리 런 ``[start:end]`` 을 원래 런 속성을 보존한 텍스트 런들로 복원."""
    out: "list[etree._Element]" = []
    offset = 0
    for run in runs:
        t = next(c for c in run if _local(c.tag) == "t")
        text = t.text or ""
        lo = max(start - offset, 0)
        hi = min(end - offset, len(text))
        if lo < hi:
            out.append(_text_run(dict(run.attrib), text[lo:hi]))
        offset += len(text)
    return out


def _compile_simple_group(
    p_el: etree._Element,
    runs: "list[etree._Element]",
    matches: "list[re.Match[str]]",
    alloc,
    report: CompileReport,
) -> None:
    """동일 서식 단순 런 묶음을 원본 오프셋/속성을 보존하며 누름틀로 치환."""
    text = "".join(next(c for c in run if _local(c.tag) == "t").text or "" for run in runs)
    new_runs: "list[etree._Element]" = []
    pos = 0
    for match in matches:
        new_runs.extend(_text_slices(runs, pos, match.start()))
        name = _clean_name(match.group(1))
        begin_id, field_id = alloc()

        # 경계 제어 런도 토큰 양 끝의 실제 런 속성을 따른다. 값은 원래 조각별
        # 속성을 그대로 유지하므로 charPrIDRef 외 메타도 버리지 않는다.
        begin_attrs = dict(next(r for r in runs if match.start() < _run_end(runs, r)).attrib)
        end_pos = max(match.end() - 1, match.start())
        end_attrs = dict(next(r for r in runs if end_pos < _run_end(runs, r)).attrib)
        new_runs.append(_begin_run(begin_attrs, name, begin_id, field_id))
        new_runs.extend(_text_slices(runs, match.start(), match.end()))
        new_runs.append(_end_run(end_attrs, begin_id, field_id))
        report.compiled.append(name)
        pos = match.end()
    new_runs.extend(_text_slices(runs, pos, len(text)))

    idx = p_el.index(runs[0])
    for run in runs:
        p_el.remove(run)
    for offset, new_run in enumerate(new_runs):
        p_el.insert(idx + offset, new_run)


def _run_end(runs: "list[etree._Element]", target: etree._Element) -> int:
    """논리 런 묶음에서 ``target`` 런의 끝 오프셋."""
    end = 0
    for run in runs:
        t = next(c for c in run if _local(c.tag) == "t")
        end += len(t.text or "")
        if run is target:
            return end
    raise ValueError("target run is not in the logical group")


def _text_with_inline_events(t_el: etree._Element) -> "tuple[str, list[tuple[int, str]]]":
    """hp:t 혼합 콘텐츠와 토큰 안 구조 경계 위치를 복원."""
    parts = [t_el.text or ""]
    events: "list[tuple[int, str]]" = []
    length = len(parts[0])
    for child in t_el:
        local = _local(child.tag)
        if local == "tab":
            events.append((length, "tab"))
            parts.append("\t")
            length += 1
        elif local == "lineBreak":
            events.append((length, "lineBreak"))
            parts.append("\n")
            length += 1
        else:
            events.append((length, "inline"))
        tail = child.tail or ""
        parts.append(tail)
        length += len(tail)
    return "".join(parts), events


def _report_uncompilable_tokens(
    p_el: etree._Element, context: str, report: CompileReport
) -> None:
    """depth-0 문단 문자열을 복원해 구조/서식 경계를 가로지른 토큰을 신고."""
    text_parts: "list[str]" = []
    # (start, end, run, simple, paragraph-child-index)
    pieces: "list[tuple[int, int, etree._Element, bool, int]]" = []
    events: "list[tuple[int, str]]" = []
    depth = 0
    length = 0

    for child_index, run in enumerate(p_el):
        if _local(run.tag) != "run":
            continue
        simple, _ = _run_shape(run)
        for child in run:
            local = _local(child.tag)
            if local == "ctrl":
                field_boundary = False
                for ctrl_child in child:
                    ctrl_local = _local(ctrl_child.tag)
                    if ctrl_local == "fieldBegin":
                        depth += 1
                        field_boundary = True
                    elif ctrl_local == "fieldEnd":
                        depth = max(depth - 1, 0)
                        field_boundary = True
                if depth == 0 and not field_boundary:
                    events.append((length, "ctrl"))
            elif local == "t" and depth == 0:
                value, inline_events = _text_with_inline_events(child)
                start = length
                text_parts.append(value)
                length += len(value)
                pieces.append((start, length, run, simple, child_index))
                events.extend((start + pos, kind) for pos, kind in inline_events)
            elif local in ("tab", "lineBreak") and depth == 0:
                events.append((length, local))
                text_parts.append("\t" if local == "tab" else "\n")
                length += 1

    text = "".join(text_parts)
    match_starts = {match.start() for match in _TOKEN_RE.finditer(text)}
    for match in _TOKEN_RE.finditer(text):
        covered = [piece for piece in pieces if piece[0] < match.end() and piece[1] > match.start()]
        if not covered:
            continue
        inside_events = [kind for pos, kind in events if match.start() <= pos < match.end()]
        runs = list(dict.fromkeys(piece[2] for piece in covered))
        char_prs = {run.get("charPrIDRef") for run in runs}
        child_indexes = [piece[4] for piece in covered]
        contiguous = child_indexes == list(range(child_indexes[0], child_indexes[-1] + 1))
        same_proven_format = len(runs) == 1 or (len(char_prs) == 1 and None not in char_prs)
        compilable = (
            not inside_events
            and all(piece[3] for piece in covered)
            and same_proven_format
            and contiguous
        )
        if compilable:
            continue
        if any(kind in ("tab", "lineBreak") for kind in inside_events):
            reason = "탭/줄바꿈이 토큰 안에 삽입됨"
        elif "ctrl" in inside_events:
            reason = "제어 요소가 토큰 사이에 끼임"
        elif len(char_prs) > 1:
            reason = "혼합 서식(charPrIDRef 상이)"
        elif len(runs) > 1 and None in char_prs:
            reason = "토큰이 파편에 걸침(charPrIDRef 없음)"
        elif not contiguous:
            reason = "런 경계가 비연속"
        else:
            reason = "복합 런(수동 처리)"
        report.skipped.append(
            TokenSite(_clean_name(match.group(1)), context, False, reason)
        )

    # 미완결 여는 괄호({{ 만 있고 닫는 }} 없음)는 완전 매치가 없어 위 루프가 못 잡는다.
    # 조용히 흘리지 않고 파편에 걸친 토큰으로 시끄럽게 신고(master 동작 복원).
    search_from = 0
    while True:
        opener = text.find("{{", search_from)
        if opener == -1:
            break
        search_from = opener + 2
        if opener in match_starts:
            continue  # 이미 완전 토큰으로 처리됨 → 이중 신고 금지
        report.skipped.append(
            TokenSite(text[opener:].strip()[:40], context, False, "토큰이 파편에 걸침")
        )


# ------------------------------------------------------------- 문단 처리
def _depth0_texts(run: etree._Element, start_depth: int) -> "tuple[list[str], int]":
    """런 자식을 순서대로 훑어 depth-0 에 놓인 hp:t 텍스트만 모으고, 끝 depth 반환.

    누름틀이 한 런에 인라인(t·ctrl>begin·t·ctrl>end·t)인 경우에도, field 영역 안(depth>0)
    의 값 텍스트는 제외하고 바깥(depth 0) 텍스트만 잡는다.
    """
    texts: "list[str]" = []
    d = start_depth
    for ch in run:
        ln = _local(ch.tag)
        if ln == "ctrl":
            for c in ch:
                cl = _local(c.tag)
                if cl == "fieldBegin":
                    d += 1
                elif cl == "fieldEnd":
                    d -= 1
        elif ln == "t":
            if d == 0 and ch.text:
                texts.append(ch.text)
    return texts, d


def _process_paragraph(
    p_el: etree._Element, alloc, apply: bool, report: CompileReport
) -> None:
    """한 문단의 depth-0 토큰을 스캔(+ apply 면 컴파일). field 영역 안 토큰은 건너뛴다.

    depth 는 런 경계가 아니라 **런 내부 자식 수준**으로 추적한다 — 인라인 누름틀
    (한 런 안 begin/end)의 값 텍스트를 미치환 토큰으로 오인하지 않기 위해서다.
    """
    context = _paragraph_text(p_el).strip()[:_CONTEXT_MAX]
    depth = 0
    children = list(p_el)  # 스냅샷(치환 중 순회 안정)
    index = 0
    while index < len(children):
        run = children[index]
        if _local(run.tag) != "run":
            index += 1
            continue
        start_depth = depth
        simple, _ts = _run_shape(run)

        # 컴파일 가능한 논리 런: 인접·동일 charPrIDRef 단순 텍스트 런 묶음.
        # 길이 0 빈 런(속성만 있는 <hp:t></hp:t>)은 접기 대상에서 제외해 원위치·속성을
        # 그대로 보존한다(충실도: 소스 요소·속성을 병합 중 삼키지 않는다).
        if simple and start_depth == 0 and (_ts[0].text or ""):
            group = [run]
            next_index = index + 1
            while run.get("charPrIDRef") is not None and next_index < len(children):
                candidate = children[next_index]
                candidate_simple, candidate_ts = _run_shape(candidate)
                if (
                    _local(candidate.tag) != "run"
                    or not candidate_simple
                    or not (candidate_ts[0].text or "")  # 빈 런은 그룹 종료(원위치 보존)
                    or candidate.get("charPrIDRef") != run.get("charPrIDRef")
                ):
                    break
                group.append(candidate)
                next_index += 1
            text = "".join(
                next(c for c in grouped if _local(c.tag) == "t").text or ""
                for grouped in group
            )
            matches = list(_TOKEN_RE.finditer(text))
            if matches and not apply:
                for m in matches:
                    report.compilable.append(
                        TokenSite(_clean_name(m.group(1)), context, True)
                    )
            elif matches:
                _compile_simple_group(p_el, group, matches, alloc, report)
            index = next_index
            continue

        _, depth = _depth0_texts(run, start_depth)
        index += 1

    # apply 뒤에는 새 누름틀 영역이 depth>0 으로 제외되므로 미처리 토큰만 남는다.
    _report_uncompilable_tokens(p_el, context, report)


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
