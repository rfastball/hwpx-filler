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

**복합 런.** 토큰이 걸친 런이 단순하지 않아도(여러 ``hp:t``·인라인 탭/줄바꿈·제어
요소를 함께 지님) **토큰 구간 자체가 깨끗하면**(구간 안에 구조 경계 없음 + 단일
확정 ``charPrIDRef``) 컴파일한다. 런을 오프셋으로 잘라 토큰 바깥의 구조(제어·탭 등)와
속성을 원형대로 보존하고 토큰 구간만 누름틀로 치환한다. 토큰 **안**에 구조가 끼거나
서식이 섞이면 여전히 추측하지 않고 skipped 로 신고한다(명시성 유지).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from hwpxcore.lineseg import serialize_modified_section
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


def _t_length(t_el: etree._Element) -> int:
    """depth-0 텍스트 좌표에서 ``hp:t`` 하나가 차지하는 문자 길이(탭/줄바꿈 = 1자)."""
    return len(_text_with_inline_events(t_el)[0])


def _zero_width_in_slice(
    pos: int, lo: int, hi: int, keep_lo: bool, keep_hi: bool
) -> bool:
    """폭-0 요소(속성만 있는 hp:t·구조 자식)를 구간 ``[lo, hi)`` 에 배정할지 판정.

    폭-0 요소는 오프셋만으론 시작 경계에서 인접 토큰과 동률이 돼(예: 토큰 바로
    앞의 ``<hp:t marker/>`` 는 토큰 첫 글자와 시작 오프셋이 같다) 순수 ``lo <= pos``
    규칙으론 값 구간으로 빨려 들어간다. 그래서 경계 지점 배정을 호출자가 형제 순서
    기준으로 지정하게 한다 — ``keep_lo`` 는 하단(``pos==lo``), ``keep_hi`` 는 상단
    (``pos==hi``) 경계 포함 여부. 토큰 앞/뒤 슬라이스는 자기 쪽 경계만 포함(True),
    값 슬라이스는 양 경계 모두 제외(False)해, 경계의 폭-0 요소가 필드 값 밖에
    남도록 한다. 구간 내부(``lo < pos < hi``)는 언제나 포함.
    """
    if lo < pos < hi:
        return True
    if pos == lo:
        return keep_lo
    if pos == hi:
        return keep_hi
    return False


def _clip_t(
    t_el: etree._Element,
    base: int,
    lo: int,
    hi: int,
    *,
    keep_zero_lo: bool,
    keep_zero_hi: bool,
) -> "etree._Element | None":
    """``hp:t`` 의 혼합 콘텐츠를 depth-0 오프셋 ``[lo, hi)`` 로 잘라 새 ``hp:t`` 로 복원.

    텍스트는 문자 단위로, 인라인 요소(탭/줄바꿈=1자·기타=0자)는 위치로 취사한다.
    구간에 남는 게 없으면 ``None``. 요소·꼬리텍스트·속성을 원형 보존한다.

    ``t_el`` 자체가 텍스트·자식 없이 속성만 있으면(예: ``<hp:t marker="KEEP"/>``)
    위치 폭이 0 이라 문자/자식 단위로는 어느 구간에도 걸리지 않는다 — 그대로 두면
    세 구간 호출 모두 ``None`` 을 반환해 요소가 통째로 소실된다. 폭-0 지점으로
    취급하되, 경계 배정은 ``keep_zero_lo``/``keep_zero_hi`` 로 형제 순서를 반영해
    (토큰 앞의 마커가 값 구간으로 빨려 들어가지 않도록) 정확히 한 구간에만 보존한다.
    """
    if not t_el.text and len(t_el) == 0:
        if _zero_width_in_slice(base, lo, hi, keep_zero_lo, keep_zero_hi):
            return etree.Element(t_el.tag, dict(t_el.attrib))
        return None
    items: "list[tuple[int, str, object, int]]" = []  # (pos, kind, payload, width)
    pos = base
    for ch in t_el.text or "":
        items.append((pos, "char", ch, 1))
        pos += 1
    for child in t_el:
        width = 1 if _local(child.tag) in ("tab", "lineBreak") else 0
        items.append((pos, "elem", child, width))
        pos += width
        for ch in child.tail or "":
            items.append((pos, "char", ch, 1))
            pos += 1

    lead: "list[str]" = []
    kids: "list[list]" = []  # [clone, tail_chars]
    for item_pos, kind, payload, width in items:
        if width == 0:
            if not _zero_width_in_slice(item_pos, lo, hi, keep_zero_lo, keep_zero_hi):
                continue
        elif not (lo <= item_pos < hi):
            continue
        if kind == "char":
            if kids:
                kids[-1][1].append(payload)
            else:
                lead.append(payload)
        else:
            clone = copy.deepcopy(payload)
            clone.tail = None
            kids.append([clone, []])

    if not lead and not kids:
        return None
    new_t = etree.Element(t_el.tag, dict(t_el.attrib))
    new_t.text = "".join(lead) or None
    for clone, tail in kids:
        clone.tail = "".join(tail) or None
        new_t.append(clone)
    return new_t


def _clip_run(
    run: etree._Element,
    base: int,
    lo: int,
    hi: int,
    *,
    keep_zero_lo: bool,
    keep_zero_hi: bool,
) -> "etree._Element | None":
    """런을 depth-0 오프셋 ``[lo, hi)`` 로 잘라 속성·구조를 보존한 새 런으로 복원.

    토큰 구간이 깨끗한(구조 경계 없는) 런에만 쓴다 — 그래서 이 런의 모든 자식이
    depth-0 이고 pos 추적이 depth-0 좌표와 일치한다. 폭-0 자식의 경계 배정은
    ``keep_zero_lo``/``keep_zero_hi`` 로 형제 순서를 반영한다(``_zero_width_in_slice``).
    """
    new_run = etree.Element(run.tag, dict(run.attrib))
    pos = base
    for child in run:
        local = _local(child.tag)
        if local == "t":
            clipped = _clip_t(
                child, pos, lo, hi, keep_zero_lo=keep_zero_lo, keep_zero_hi=keep_zero_hi
            )
            if clipped is not None:
                new_run.append(clipped)
            pos += _t_length(child)
        else:
            width = 1 if local in ("tab", "lineBreak") else 0
            keep = (
                _zero_width_in_slice(pos, lo, hi, keep_zero_lo, keep_zero_hi)
                if width == 0
                else lo <= pos < hi
            )
            if keep:
                new_run.append(copy.deepcopy(child))
            pos += width
    return new_run if len(new_run) else None


@dataclass
class _TokenSpan:
    """한 토큰 매치의 분류 결과 — 신고·복합 컴파일 공용."""

    match: "re.Match[str]"
    name: str
    covered: "list[etree._Element]"  # 토큰이 걸친 런(중복 제거·문서 순)
    run_base: "dict"  # run -> depth-0 시작 오프셋
    clean: bool  # 토큰 구간이 컴파일 가능(구조 없음·단일 확정 서식·연속)
    all_simple: bool  # 걸친 조각이 전부 단순 런(단순 경로가 이미 처리)
    reason: str  # clean=False 일 때 병리 사유


def _build_paragraph_model(p_el: etree._Element):
    """depth-0 문단 텍스트와 조각(pieces)·구조 이벤트·런 시작오프셋을 복원."""
    text_parts: "list[str]" = []
    # (start, end, run, simple, paragraph-child-index)
    pieces: "list[tuple[int, int, etree._Element, bool, int]]" = []
    events: "list[tuple[int, str]]" = []
    run_base: "dict" = {}
    depth = 0
    length = 0

    for child_index, run in enumerate(p_el):
        if _local(run.tag) != "run":
            continue
        simple, _ = _run_shape(run)
        # _clip_run 은 이 런의 자식을 처음부터 순회하며 pos=base 로 시작하므로,
        # base 는 런의 첫 자식(탭/제어일 수도 있음) 위치여야 한다 — 첫 hp:t 위치로
        # 잡으면 선행 런-레벨 탭/줄바꿈이 이중 계산돼 오프셋이 밀린다.
        run_base.setdefault(run, length)
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
            elif depth == 0:
                # t/ctrl/tab/lineBreak 가 아닌 다른 런 직계 자식(hp:tbl·hp:pic·hp:secPr 등).
                # 폭 0 이라 텍스트 좌표엔 영향 없지만, 토큰 조각 사이에 끼면 그 구조
                # 요소가 컴파일 시 필드 값 안으로 잘못 들어갈 수 있으므로 구조 경계로
                # 기록해 clean 판정에서 걸러지게 한다(_clip_run 은 이미 이런 요소를
                # 폭-0 지점으로 정확히 배치하므로 클리핑 자체는 손대지 않는다).
                events.append((length, "struct"))

    return "".join(text_parts), pieces, events, run_base


def _run_has_field_ctrl(run: etree._Element) -> bool:
    """런 안에 누름틀 경계(fieldBegin/End) 제어가 있는지 — 있으면 복합 컴파일 제외."""
    return (
        run.find(f".//{_hp('fieldBegin')}") is not None
        or run.find(f".//{_hp('fieldEnd')}") is not None
    )


def _classify_paragraph_tokens(p_el: etree._Element) -> "list[_TokenSpan]":
    """문단의 각 완전 토큰을 (컴파일 가능·단순여부·병리 사유)로 분류."""
    text, pieces, events, run_base = _build_paragraph_model(p_el)
    spans: "list[_TokenSpan]" = []
    for match in _TOKEN_RE.finditer(text):
        covered_pieces = [
            piece for piece in pieces if piece[0] < match.end() and piece[1] > match.start()
        ]
        if not covered_pieces:
            continue
        inside_events = [kind for pos, kind in events if match.start() <= pos < match.end()]
        runs = list(dict.fromkeys(piece[2] for piece in covered_pieces))
        char_prs = {run.get("charPrIDRef") for run in runs}
        child_indexes = list(dict.fromkeys(piece[4] for piece in covered_pieces))
        contiguous = child_indexes == list(range(child_indexes[0], child_indexes[-1] + 1))
        same_proven_format = len(runs) == 1 or (len(char_prs) == 1 and None not in char_prs)
        all_simple = all(piece[3] for piece in covered_pieces)
        has_field = any(_run_has_field_ctrl(run) for run in runs)
        clean = (
            not inside_events
            and same_proven_format
            and contiguous
            and not has_field
        )
        reason = ""
        if not clean:
            if any(kind in ("tab", "lineBreak") for kind in inside_events):
                reason = "탭/줄바꿈이 토큰 안에 삽입됨"
            elif "ctrl" in inside_events:
                reason = "제어 요소가 토큰 사이에 끼임"
            elif "struct" in inside_events:
                reason = "비텍스트 구조 요소(표·그림 등)가 토큰 사이에 끼임"
            elif len(char_prs) > 1:
                reason = "혼합 서식(charPrIDRef 상이)"
            elif len(runs) > 1 and None in char_prs:
                reason = "토큰이 파편에 걸침(charPrIDRef 없음)"
            elif not contiguous:
                reason = "런 경계가 비연속"
            else:
                reason = "복합 런(수동 처리)"
        spans.append(
            _TokenSpan(
                match=match,
                name=_clean_name(match.group(1)),
                covered=runs,
                run_base=run_base,
                clean=clean,
                all_simple=all_simple,
                reason=reason,
            )
        )
    return spans


def _compile_one_composite(
    p_el: etree._Element, alloc, report: CompileReport
) -> bool:
    """깨끗한 복합-런 토큰 **하나**를 누름틀로 치환. 치환했으면 True.

    치환은 트리를 바꿔 오프셋을 무효화하므로 호출자가 한 번에 하나씩, 매번 새로
    분석하며 돌린다(정지: 남은 깨끗한 복합 토큰이 없으면 False). 단순 런 토큰은
    이미 단순 경로가 처리했으므로(apply 후 depth>0) 여기 걸리지 않는다.
    """
    for span in _classify_paragraph_tokens(p_el):
        if not span.clean or span.all_simple:
            continue  # 병리 토큰·단순 경로 소관은 건드리지 않는다
        _replace_composite_token(p_el, span, alloc, report)
        return True
    return False


def _replace_composite_token(
    p_el: etree._Element, span: "_TokenSpan", alloc, report: CompileReport
) -> None:
    """복합 런 묶음에서 토큰 구간만 누름틀로 치환하고 바깥 구조·속성을 보존."""
    match = span.match
    tstart, tend = match.start(), match.end()
    covered = span.covered
    run_base = span.run_base
    begin_id, field_id = alloc()

    new_runs: "list[etree._Element]" = []
    # 토큰 앞: 첫 걸친 런의 토큰 이전 부분(제어·탭 등 구조 원형 보존).
    # 경계(pos==tstart)의 폭-0 요소(토큰 앞 마커)는 이 앞 슬라이스가 가져간다 →
    # keep_zero_hi=True. 그래야 값 슬라이스로 새지 않고 필드 밖에 남는다.
    for run in covered:
        left = _clip_run(run, run_base[run], 0, tstart, keep_zero_lo=True, keep_zero_hi=True)
        if left is not None:
            new_runs.append(left)
    # 누름틀 여는 경계 — 토큰 시작 런 속성 승계.
    new_runs.append(_begin_run(dict(covered[0].attrib), span.name, begin_id, field_id))
    # 값: 토큰 구간을 각 걸친 런에서 잘라 조각별 속성 보존(구간은 깨끗한 텍스트뿐).
    # 양 경계의 폭-0 요소는 앞/뒤 슬라이스 소관 → 값에선 제외(keep_zero_*=False).
    for run in covered:
        value = _clip_run(run, run_base[run], tstart, tend, keep_zero_lo=False, keep_zero_hi=False)
        if value is not None:
            new_runs.append(value)
    # 닫는 경계 — 토큰 끝 런 속성 승계.
    new_runs.append(_end_run(dict(covered[-1].attrib), begin_id, field_id))
    # 토큰 뒤: 마지막 걸친 런의 토큰 이후 부분.
    # 경계(pos==tend)의 폭-0 요소(토큰 뒤 마커)는 이 뒤 슬라이스가 가져간다 → keep_zero_lo=True.
    for run in covered:
        right = _clip_run(run, run_base[run], tend, 1 << 30, keep_zero_lo=True, keep_zero_hi=True)
        if right is not None:
            new_runs.append(right)

    idx = p_el.index(covered[0])
    for run in covered:
        p_el.remove(run)
    for offset, new_run in enumerate(new_runs):
        p_el.insert(idx + offset, new_run)
    report.compiled.append(span.name)


def _report_uncompilable_tokens(
    p_el: etree._Element, context: str, report: CompileReport, apply: bool
) -> None:
    """구조/서식 경계를 가로지른 토큰을 신고. scan 모드면 깨끗한 복합 토큰은 미리보기 등록.

    apply 모드에서는 깨끗한 복합 토큰이 이미 치환돼 사라졌으므로 병리 토큰만 남는다.
    """
    text, _, _, _ = _build_paragraph_model(p_el)
    for span in _classify_paragraph_tokens(p_el):
        if span.clean:
            if span.all_simple:
                continue  # 단순 경로가 이미 처리(scan=미리보기 등록, apply=컴파일)
            if not apply:
                report.compilable.append(TokenSite(span.name, context, True))
            continue  # apply 면 이미 _compile_one_composite 가 치환함
        report.skipped.append(TokenSite(span.name, context, False, span.reason))

    # 미완결 여는 괄호({{ 만 있고 닫는 }} 없음)는 완전 매치가 없어 위 루프가 못 잡는다.
    # 조용히 흘리지 않고 파편에 걸친 토큰으로 시끄럽게 신고(master 동작 복원).
    match_starts = {match.start() for match in _TOKEN_RE.finditer(text)}
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

    # 단순 경로가 못 접은 **복합 런**이라도 토큰 구간이 깨끗하면 여기서 컴파일한다.
    # 매 치환이 오프셋을 무효화하므로 한 번에 하나씩 재분석하며 소진한다.
    if apply:
        while _compile_one_composite(p_el, alloc, report):
            pass

    # apply 뒤에는 새 누름틀 영역이 depth>0 으로 제외되므로 미처리 토큰만 남는다.
    _report_uncompilable_tokens(p_el, context, report, apply)


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
            # 런 재편으로 stale 이 된 줄배치 캐시를 재직렬화 직전 스트립(#95).
            # 미변경 섹션(compiled 증가 없음)은 재직렬화 자체를 안 하므로 보존.
            pkg.entries[name] = serialize_modified_section(root)
    report.modified = bool(report.compiled)
    return pkg, report


def compile_to_sibling(path: str, *, overwrite: bool = False) -> "tuple[str | None, CompileReport]":
    """토큰을 컴파일해 **원본 옆** ``<이름>.compiled.hwpx`` 로 저장(원본 무변형).

    저작 화면의 [여기서 누름틀 변환] 경로가 쓰는 코어 프리미티브 — 출력 경로 파생·저장·충돌
    정책을 뷰가 하드코딩하지 않는다(RC-28). 정책:

    - 바꿀 토큰이 없으면(``modified=False``) 아무것도 쓰지 않고 ``(None, report)``.
    - 컴파일본이 이미 있으면 ``overwrite=True`` 없이는 :class:`FileExistsError`
      (메시지 = 충돌 경로)로 시끄럽게 차단 — 조용한 덮어쓰기 금지(RC-02). 호출측이
      사용자 확정을 받은 뒤 ``overwrite=True`` 로 재호출한다.
    - 컴파일·저장 실패는 그대로 raise(호출측이 시끄럽게 표시).
    """
    pkg, report = compile_document(path)
    if not report.modified:
        return None, report
    compiled_path = str(Path(path).with_suffix(".compiled.hwpx"))
    if Path(compiled_path).exists() and not overwrite:
        raise FileExistsError(compiled_path)
    pkg.save(compiled_path)  # _to_package 가 HwpxPackage 를 반환한다(save 보유)
    return compiled_path, report
