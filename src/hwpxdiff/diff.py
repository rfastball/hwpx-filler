"""HWPX 규격서 개정 diff — 두 판본의 의미 기반(semantic) 변경점 추출.

규격서·표준서식은 해마다 개정된다. 이 모듈은 ``text_extract.extract_document`` 가
복원한 결정적 문서 트리 두 개를 받아 **무엇이 어떻게 바뀌었는지**를 사람이 훑기 쉬운
구조로 산출한다. HWPX 엔 안정적 ID 가 없으므로 위치가 아니라 **내용 기반 정렬**이
핵심이다.

설계 원칙:
  - 순수·결정적. 표준 라이브러리 ``difflib`` + 추출 타입만 쓰고 새 의존성을 두지 않는다.
    같은 입력이면 ``to_dict()`` 가 항상 동일(랜덤 없음, 정렬 안정).
  - 렌더링과 분리. 이 모듈은 diff *데이터* 만 만든다. HTML/텍스트 렌더는 별도 함수.
  - 노이즈 억제. 빈 문단끼리의 정렬 흔들림은 변경으로 보고하지 않는다.

핵심 알고리즘:
  1. **평탄화(flatten)**: 각 Document 를 문서 순서의 비교 단위로 편다. 표 밖 문단은
     문단 단위, 표는 표 인덱스 + 셀 ``addr`` 로 키가 매겨진 셀 단위로 다룬다.
  2. **문단 정렬**: 문단 텍스트 시퀀스에 ``SequenceMatcher`` 를 태워 equal/replace/
     delete/insert opcode 를 얻는다(위치가 아니라 내용으로 정렬 — 한 조항이 삽입돼도
     뒤가 통째로 어긋나지 않는다).
  3. **문단 내부 낱말 diff**: replace 쌍은 토큰화해 미세 변경(요율 3%→3.5%, 1억→2억)을
     인라인으로 강조할 수 있게 낱말 op 를 남긴다.
  4. **표 diff**: 표는 순서로 매칭하고, 셀은 ``addr`` 로 정렬(행 인덱스만으로는 rowSpan
     아래 colAddr 가 불연속이라 부족)해 셀 텍스트를 비교한다.
  5. **변경 항목 추출**: diff 위에서 리뷰어가 실제로 찾는 것 — 숫자/통화/퍼센트/날짜
     변경, 조항 추가·삭제 — 을 우선순위로 정렬한 사람용 목록으로 뽑는다.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from hwpxcore.text_extract import (
    Document,
    Paragraph,
    Section,
    Table,
    extract_document,
)

# ------------------------------------------------------------------ 토큰/패턴
# 낱말 diff 토큰: 공백 덩어리 | 숫자(자릿수 구분·소수 포함) | 그 외 비공백-비숫자 덩어리.
# 숫자를 독립 토큰으로 떼어 "기준금액1억" 도 ["기준금액","1","억"] 로 갈라 미세 비교한다.
_TOKEN_RE = re.compile(r"\s+|\d[\d,]*(?:\.\d+)?|[^\s\d]+")

# 숫자 변경 감지: 숫자 코어(자릿수 구분/소수) + 바로 뒤 단위(선택).
# 통화·퍼센트·수량·날짜 조각을 포괄한다. 범위는 단순·문서화 우선(법조문 번호도 잡힘).
_NUMBER_RE = re.compile(
    r"\d[\d,]*(?:\.\d+)?"
    r"(?:\s?(?:%|퍼센트|원|억|만|천|개|명|점|년|월|일|시간|배|건|호))?"
)

# 조항 헤더로 보이는 문단(우선 노출 대상).
_CLAUSE_RES = (
    re.compile(r"^\s*제\s*\d+\s*조"),
    re.compile(r"^\s*제\s*\d+\s*장"),
    re.compile(r"^\s*별\s*표\s*\d*"),
    re.compile(r"^\s*\d+(?:-\d+)?\s*\.\s*\S"),  # "1. 입찰개요", "3-1. 제출서류"
)

# 선두 조항/목록 서수(ordinal) 접두 — 정렬 키 정규화에 쓴다.
# 조항이 하나 삽입돼 뒤 번호가 통째로 밀리면(3.2.8→3.2.9) 본문이 같아도 원문이 달라
# equal 로 안 잡히고 replace 로 흘러 엉뚱한 조항끼리 1:1 짝지어진다. 이를 막으려
# **정렬 키를 만들 때만** 선두 서수를 벗겨 본문으로 맞춘다(원문은 표시·변경 감지에 보존).
# 보수적으로: 산문 속 숫자("납기 180일")는 절대 건드리지 않도록 서수 표식만 벗긴다.
#   · 제N조/제N장/… (제 3 조)
#   · 점 구분 다단계 번호 3.2.8 / 3.2.8.  (점이 하나 이상 — "180"은 안 걸림)
#   · 하이픈 번호 3-1 / 3-1.
#   · 마침표 붙은 단일 번호 3.  ("1.5" 는 뒤가 공백이 아니라 안 걸림)
# 뒤에 공백(또는 끝)이 와야만 서수로 인정해 "180일"·"1.5배" 같은 산문을 지킨다.
_ORDINAL_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"제\s*\d+\s*[조장절관항호목]\s*"       # 제3조 / 제 3 장
    r"|\d+(?:\.\d+)+\.?(?=\s|$)\s*"        # 3.2.8 / 3.2.8. (점 ≥1)
    r"|\d+(?:-\d+)+\.?(?=\s|$)\s*"         # 3-1 / 3-1.
    r"|\d+\.(?=\s|$)\s*"                   # 3.  (마침표 필수)
    r")"
)

# 변경 항목 우선순위(작을수록 먼저). 리뷰어가 가장 찾는 순.
_PRI_NUMBER = 0
_PRI_CLAUSE = 1
_PRI_CHANGED = 2
_PRI_ADDREMOVE = 3
_PRI_RENUMBER = 4  # 번호만 바뀐 재번호 — 실질 변경 아래에 데모트(숨기진 않음)

# replace 구간에서 old↔new 문단을 짝지을 최소 정규화-본문 유사도.
# 0.6 이상이면 재작성(180일→300일 유형)으로 보고 페어링, 미만은 서로 다른 조항으로
# 간주해 add/remove 로 분리(거짓 changed 방지).
_REPLACE_PAIR_THRESHOLD = 0.6


def _ordinal_prefix(text: str) -> str:
    """선두 서수 접두를 반환(없으면 빈 문자열). 트림된 원문 조각."""
    m = _ORDINAL_PREFIX_RE.match(text)
    return m.group(0).strip() if m else ""


def _norm_key(text: str) -> str:
    """정렬용 정규화 키 — 선두 서수 접두를 벗긴 본문.

    벗긴 결과가 비면(문단이 서수 그 자체뿐: "3.") 원문을 그대로 키로 쓴다 —
    빈 키끼리 뭉쳐 서로 다른 서수 문단이 거짓 정렬되는 것을 막는다.
    """
    stripped = _ORDINAL_PREFIX_RE.sub("", text, count=1)
    return stripped if stripped.strip() else text


def _is_blank(s: str) -> bool:
    return not s.strip()


def _looks_like_clause(text: str) -> bool:
    """문단이 조항 헤더(제N조·제N장·별표·N.)로 보이면 True."""
    return any(rx.match(text) for rx in _CLAUSE_RES)


# ---------------------------------------------------------------- 데이터 모델
@dataclass
class WordOp:
    """낱말 수준 diff 조각. ``op`` 는 equal/insert/delete/replace."""

    op: str
    old: str = ""
    new: str = ""

    def to_dict(self) -> dict:
        return {"op": self.op, "old": self.old, "new": self.new}


@dataclass
class Change:
    """단일 변경. 문서 순서로 수집되며 ``seq`` 로 안정 정렬한다.

    ``unit`` 는 paragraph/cell/table, ``kind`` 는 added/removed/changed.
    ``location`` 은 기계용 위치 dict, ``location_label`` 은 사람용 라벨.
    ``word_ops`` 는 changed 일 때만 채운다.
    """

    seq: int
    kind: str
    unit: str
    location: dict
    location_label: str
    old_text: str = ""
    new_text: str = ""
    word_ops: "list[WordOp] | None" = None

    def to_dict(self) -> dict:
        d = {
            "seq": self.seq,
            "kind": self.kind,
            "unit": self.unit,
            "location": self.location,
            "location_label": self.location_label,
            "old_text": self.old_text,
            "new_text": self.new_text,
        }
        if self.word_ops is not None:
            d["word_ops"] = [w.to_dict() for w in self.word_ops]
        return d


@dataclass
class ChangeItem:
    """리뷰어용 변경 항목. 숫자·조항 변경을 앞세워 정렬한다."""

    category: str  # number/clause_added/clause_removed/text_changed/text_added/...
    priority: int
    order: int  # 원 Change 의 seq — 동순위 안정 정렬용
    location_label: str
    detail: str
    old: str = ""
    new: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "priority": self.priority,
            "order": self.order,
            "location_label": self.location_label,
            "detail": self.detail,
            "old": self.old,
            "new": self.new,
        }


@dataclass
class DocRow:
    """전문(全文) 대조 행 — 두 문서를 나란히 펼친 정렬 스트림의 한 줄.

    변경만 담는 :class:`Change` 와 달리 **equal 행을 포함**해 원문 전체가 보존된다
    (신구대비표 뷰의 데이터). ``seq`` 는 변경 행이면 대응 ``Change.seq``, equal 이면
    None — 변경 목록과 전문 뷰를 같은 번호로 잇는 앵커 키다.
    """

    kind: str  # equal/added/removed/changed/renumber
    unit: str  # paragraph/cell/table
    label: str
    old_text: str = ""
    new_text: str = ""
    word_ops: "list[WordOp] | None" = None
    seq: "int | None" = None


@dataclass
class ChangeGroup:
    """변경 리스트 1행 = **문서상 인접**한 같은 종류 변경 묶음(파편화 완화).

    인접성은 ``seq``(변경 방출 서수 — equal 을 소모하지 않아 문서 간격 정보가 없다)가
    아니라 rows 스트림에서의 연속으로 판정한다: 사이에 equal 행이 있으면 별개 그룹이다.
    점프 표적은 첫 변경의 seq.
    """

    kind: str
    label: str
    detail: str
    seqs: "list[int]" = field(default_factory=list)


@dataclass
class DiffResult:
    """구조화·직렬화 가능한 diff 결과.

    ``changes`` 는 문서 순서의 원 변경 목록, ``change_items`` 는 우선순위 정렬된 사람용
    목록, ``summary`` 는 개수 요약. 모두 결정적이다.

    ``rows`` 는 equal 을 포함한 전문 대조 스트림(뷰 데이터)이다 — ``to_dict()`` 에는
    넣지 않는다(골든은 변경만 고정; 전문은 원문 파일에서 항상 재생 가능한 파생물).
    주의: 행 순서는 섹션마다 문단 전부 → 표 전부다(diff 가 그 순서로 정렬한다) —
    문단·표가 섞인 원문 배치와 다를 수 있다.

    ``change_groups`` 는 rows 기반 인접 묶음(변경 리스트 뷰 데이터) — rows 와 같은
    이유로 ``to_dict()`` 밖의 파생물이다. GUI·CLI 가 같은 그룹화를 공유한다.
    """

    changes: "list[Change]" = field(default_factory=list)
    change_items: "list[ChangeItem]" = field(default_factory=list)
    summary: "dict[str, int]" = field(default_factory=dict)
    rows: "list[DocRow]" = field(default_factory=list)
    change_groups: "list[ChangeGroup]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "summary": {k: self.summary[k] for k in sorted(self.summary)},
            "changes": [c.to_dict() for c in self.changes],
            "change_items": [i.to_dict() for i in self.change_items],
        }


# ------------------------------------------------------------------ 평탄화
@dataclass
class _ParaUnit:
    """문단 비교 단위: 텍스트 + 위치 메타."""

    text: str
    location: dict
    label: str


def _region_iter(doc: Document) -> "list[tuple[str, list[Section]]]":
    """(영역 라벨, 섹션 목록) 을 머리말->본문->꼬리말 순으로."""
    return [("머리말", doc.headers), ("본문", doc.sections), ("꼬리말", doc.footers)]


def _cell_text(cell) -> str:
    """셀 전체 텍스트(중첩 표 포함) — 문단 텍스트를 문서 순서로 개행 결합."""
    parts: "list[str]" = []
    for b in cell.blocks:
        if isinstance(b, Paragraph):
            parts.append(b.text)
        elif isinstance(b, Table):
            for row in b.rows:
                for c in row:
                    parts.append(_cell_text(c))
    return "\n".join(p for p in parts if p != "").strip()


def _direct_cell_text(cell) -> str:
    """셀의 직접 문단만 결합한다(중첩 표는 별도 비교 단위)."""
    return "\n".join(
        block.text
        for block in cell.blocks
        if isinstance(block, Paragraph) and block.text != ""
    ).strip()


def _nested_tables(cell) -> "list[Table]":
    """셀에 직접 포함된 중첩 표를 문서 순서로 반환한다."""
    return [block for block in cell.blocks if isinstance(block, Table)]


def _cell_key(cell, row_i: int, col_i: int) -> tuple:
    """셀 정렬 키. addr(rowAddr,colAddr) 우선, 없으면 위치 폴백."""
    ra = cell.addr.get("rowAddr")
    ca = cell.addr.get("colAddr")
    if ra is not None and ca is not None:
        return ("addr", ra, ca)
    return ("pos", row_i, col_i)


# ------------------------------------------------------------------ 낱말 diff
def _tokenize(text: str) -> "list[str]":
    """낱말 diff 용 토큰 목록(공백/숫자/그 외를 분리, 원문 복원 가능)."""
    return _TOKEN_RE.findall(text)


def _word_ops(old: str, new: str) -> "list[WordOp]":
    """두 문자열의 낱말 수준 op 목록(인라인 add/del 렌더용)."""
    a, b = _tokenize(old), _tokenize(new)
    sm = SequenceMatcher(a=a, b=b, autojunk=False)
    ops: "list[WordOp]" = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            ops.append(WordOp("equal", old="".join(a[i1:i2])))
        elif tag == "delete":
            ops.append(WordOp("delete", old="".join(a[i1:i2])))
        elif tag == "insert":
            ops.append(WordOp("insert", new="".join(b[j1:j2])))
        else:  # replace
            ops.append(
                WordOp("replace", old="".join(a[i1:i2]), new="".join(b[j1:j2]))
            )
    return ops


# ------------------------------------------------------------------ 숫자 감지
def _extract_numbers(text: str) -> "list[str]":
    """텍스트에서 숫자(+선택 단위) 조각을 문서 순서로 추출."""
    out: "list[str]" = []
    for m in _NUMBER_RE.finditer(text):
        tok = m.group(0).strip()
        if tok and any(ch.isdigit() for ch in tok):
            out.append(tok)
    return out


def _minus(seq: "list[str]", counter: "Counter") -> "list[str]":
    """seq 에서 counter(공통 다중집합) 만큼을 순서 보존하며 제거한 나머지."""
    left = dict(counter)
    out: "list[str]" = []
    for t in seq:
        if left.get(t, 0) > 0:
            left[t] -= 1
        else:
            out.append(t)
    return out


def _number_changes(old: str, new: str) -> "list[tuple[str, str]]":
    """old->new 로 바뀐 숫자 쌍 목록. 공통 숫자는 제외, 순서 보존 페어링."""
    o, n = _extract_numbers(old), _extract_numbers(new)
    common = Counter(o) & Counter(n)
    old_only, new_only = _minus(o, common), _minus(n, common)
    if not old_only and not new_only:
        return []
    pairs: "list[tuple[str, str]]" = []
    for i in range(max(len(old_only), len(new_only))):
        pairs.append(
            (old_only[i] if i < len(old_only) else "",
             new_only[i] if i < len(new_only) else "")
        )
    return pairs


# ------------------------------------------------------------------ 코어 diff
class _Differ:
    """단일 diff 실행의 가변 상태(변경 수집 + seq 카운터)."""

    def __init__(self) -> None:
        self.changes: "list[Change]" = []
        self.rows: "list[DocRow]" = []  # equal 포함 전문 대조 스트림
        self._seq = 0

    def _emit(self, kind: str, unit: str, location: dict, label: str,
              old_text: str = "", new_text: str = "",
              word_ops: "list[WordOp] | None" = None) -> None:
        self.changes.append(
            Change(self._seq, kind, unit, location, label,
                   old_text, new_text, word_ops)
        )
        self.rows.append(
            DocRow(kind, unit, label, old_text, new_text, word_ops, self._seq)
        )
        self._seq += 1

    def _note_equal(self, unit: str, label: str, text: str) -> None:
        """변경 없는 단위도 전문 스트림에 남긴다(빈 것은 제외 — 표시 노이즈)."""
        if not _is_blank(text):
            self.rows.append(DocRow("equal", unit, label, text, text))

    def _emit_renumber(self, uo: "_ParaUnit", un: "_ParaUnit") -> None:
        """선두 서수만 바뀐 문단을 renumber 변경으로 기록(원문 보존)."""
        self._emit("renumber", "paragraph", un.location, un.label,
                   old_text=uo.text, new_text=un.text,
                   word_ops=_word_ops(uo.text, un.text))

    # ---------------------------------------------------- 문단 스트림 정렬
    def _diff_paragraphs(self, olds: "list[_ParaUnit]",
                         news: "list[_ParaUnit]") -> None:
        # 정렬은 **정규화 키**(선두 서수 제거)로 태운다 — 재번호된 조항이 본문 기준으로
        # 맞물리게 해 엉뚱한 조항끼리의 거짓 1:1 짝을 없앤다. 원문은 표시·감지에 보존.
        sm = SequenceMatcher(
            a=[_norm_key(u.text) for u in olds],
            b=[_norm_key(u.text) for u in news],
            autojunk=False,
        )
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                # 키(본문)는 같지만 원문이 다르면 = 선두 서수만 바뀐 재번호. 조용히
                # 버리지 않고 renumber 로 표면화(위치는 1:1 대응).
                for k in range(i2 - i1):
                    uo, un = olds[i1 + k], news[j1 + k]
                    if uo.text != un.text:
                        self._emit_renumber(uo, un)
                    else:
                        self._note_equal("paragraph", un.label, un.text)
                continue
            if tag == "delete":
                for u in olds[i1:i2]:
                    if not _is_blank(u.text):
                        self._emit("removed", "paragraph", u.location, u.label,
                                   old_text=u.text)
            elif tag == "insert":
                for u in news[j1:j2]:
                    if not _is_blank(u.text):
                        self._emit("added", "paragraph", u.location, u.label,
                                   new_text=u.text)
            else:  # replace — 유사도 기반 짝짓기(위치 슬립 교정), 나머지는 add/remove
                self._pair_replace_block(olds[i1:i2], news[j1:j2])

    def _pair_replace_block(self, blk_o: "list[_ParaUnit]",
                            blk_n: "list[_ParaUnit]") -> None:
        """replace 구간의 old/new 문단을 **정규화 본문 유사도**로 짝짓는다.

        위치 1:1 은 조항 삽입/삭제로 뒤가 밀리면(착지발판 ↔ 유압계통) 엉뚱한 조항끼리
        짝지어 거짓 changed 를 쏟아낸다. 대신 유사도 임계 이상인 쌍만 맺고, 짝 없는
        old 는 removed, new 는 added 로 흘려 재번호+삽입 캐스케이드를 붕괴시킨다.

        짝지어진 쌍: 원문 동일→무시, 정규화 본문 동일(서수만 변경)→renumber, 그 외→changed.
        결정적: 유사도 내림차순, 동률은 (old_idx, new_idx) 로 안정 정렬해 그리디 할당.
        """
        no = [_norm_key(u.text) for u in blk_o]
        nn = [_norm_key(u.text) for u in blk_n]
        cands: "list[tuple[float, int, int]]" = []
        # O(N²) ratio 완화: quick_ratio/real_quick_ratio 는 ratio 의 **상한**을 싸게
        # 계산한다(difflib 표준 관용구) — 상한이 임계 미만인 쌍은 실제 ratio 없이 조기
        # 기각한다. 상한이므로 통과 집합은 동일(결과 불변, 대개정 문서의 동결 완화).
        # 루프는 new(b) 바깥·old(a) 안쪽 — SequenceMatcher 가 seq2(b) 통계를 캐싱한다.
        for nj, b in enumerate(nn):
            if _is_blank(blk_n[nj].text):
                continue
            sm = SequenceMatcher(b=b, autojunk=False)
            for oi, a in enumerate(no):
                if _is_blank(blk_o[oi].text):
                    continue
                sm.set_seq1(a)
                if sm.real_quick_ratio() < _REPLACE_PAIR_THRESHOLD:
                    continue
                if sm.quick_ratio() < _REPLACE_PAIR_THRESHOLD:
                    continue
                r = sm.ratio()
                if r >= _REPLACE_PAIR_THRESHOLD:
                    cands.append((r, oi, nj))
        # 수집 순서와 무관한 완전 결정 정렬(동률은 (old_idx, new_idx)) — 그리디 할당 안정.
        cands.sort(key=lambda c: (-c[0], c[1], c[2]))
        o_match: "dict[int, int]" = {}
        n_used: "set[int]" = set()
        for _r, oi, nj in cands:
            if oi in o_match or nj in n_used:
                continue
            o_match[oi] = nj
            n_used.add(nj)
        # 순서 보존: old 순서로 pair/remove, 이어서 남은 new 를 add.
        for oi, uo in enumerate(blk_o):
            if oi in o_match:
                un = blk_n[o_match[oi]]
                if _is_blank(uo.text) and _is_blank(un.text):
                    continue
                if uo.text == un.text:
                    self._note_equal("paragraph", un.label, un.text)
                    continue
                if _norm_key(uo.text) == _norm_key(un.text):
                    self._emit_renumber(uo, un)
                    continue
                self._emit("changed", "paragraph", un.location, un.label,
                           old_text=uo.text, new_text=un.text,
                           word_ops=_word_ops(uo.text, un.text))
            elif not _is_blank(uo.text):
                self._emit("removed", "paragraph", uo.location, uo.label,
                           old_text=uo.text)
        for nj, un in enumerate(blk_n):
            if nj not in n_used and not _is_blank(un.text):
                self._emit("added", "paragraph", un.location, un.label,
                           new_text=un.text)

    # ---------------------------------------------------------- 표 diff
    def _diff_tables(self, region: str, region_idx: int,
                     olds: "list[tuple[int, Table]]",
                     news: "list[tuple[int, Table]]") -> None:
        for t_ord in range(max(len(olds), len(news))):
            o = olds[t_ord] if t_ord < len(olds) else None
            n = news[t_ord] if t_ord < len(news) else None
            base = {"region": region, "region_index": region_idx,
                    "table_index": t_ord}
            if o is not None and n is not None:
                self._diff_table_cells(
                    region, region_idx, (t_ord,), (), o[1], n[1]
                )
            elif o is not None:
                txt = _table_flat_text(o[1])
                if txt:
                    self._emit("removed", "table",
                               {**base, "unit": "table"},
                               f"{region} {region_idx + 1} · 표 {t_ord + 1}",
                               old_text=txt)
            elif n is not None:
                txt = _table_flat_text(n[1])
                if txt:
                    self._emit("added", "table",
                               {**base, "unit": "table"},
                               f"{region} {region_idx + 1} · 표 {t_ord + 1}",
                               new_text=txt)

    def _diff_table_cells(
        self,
        region: str,
        region_idx: int,
        table_path: "tuple[int, ...]",
        parent_cells: "tuple[dict, ...]",
        old_t: Table,
        new_t: Table,
    ) -> None:
        old_cells = _index_cells(old_t)
        new_cells = _index_cells(new_t)
        for key in sorted(set(old_cells) | set(new_cells), key=_key_sort):
            oc = old_cells.get(key)
            nc = new_cells.get(key)
            addr = _addr_of(key)
            loc = _table_location(
                region, region_idx, table_path, parent_cells, "cell"
            )
            loc.update(addr)
            label = (
                f"{_table_label(region, region_idx, table_path, parent_cells)} · "
                f"셀({_addr_label(addr)})"
            )
            # 통째로 추가/삭제된 셀은 중첩 표까지 한 건으로 요약한다. 양쪽 셀이
            # 존재하면 직접 문단과 중첩 표를 분리해 부모 셀 오귀속을 막는다.
            # **평탄화 동일 조기 반환 금지(#254 리뷰)**: 양쪽 셀의 평탄화 전문이 같아도
            # 같은 값이 중첩 좌표·구조 사이를 이동했을 수 있다 — 평탄화 비교로 먼저
            # 반환하면 중첩 재귀(_diff_nested_tables)가 안 돌아 이동·중복 내용의
            # table_path/실셀 귀속이 변경 0건으로 조용히 사라진다. 직접 문단 비교와
            # 중첩 재귀가 등호 판정까지 소유한다(각 층이 자기 층만 판정).
            o_txt = _cell_text(oc) if oc else ""
            n_txt = _cell_text(nc) if nc else ""
            if oc and not nc:
                if not _is_blank(o_txt):
                    self._emit("removed", "cell", loc, label, old_text=o_txt)
            elif nc and not oc:
                if not _is_blank(n_txt):
                    self._emit("added", "cell", loc, label, new_text=n_txt)
            else:
                direct_old = _direct_cell_text(oc)
                direct_new = _direct_cell_text(nc)
                if direct_old == direct_new:
                    self._note_equal("cell", label, direct_new)
                elif not (_is_blank(direct_old) and _is_blank(direct_new)):
                    self._emit(
                        "changed",
                        "cell",
                        loc,
                        label,
                        old_text=direct_old,
                        new_text=direct_new,
                        word_ops=_word_ops(direct_old, direct_new),
                    )
                self._diff_nested_tables(
                    region,
                    region_idx,
                    table_path,
                    parent_cells + (addr,),
                    _nested_tables(oc),
                    _nested_tables(nc),
                )

    def _diff_nested_tables(
        self,
        region: str,
        region_idx: int,
        table_path: "tuple[int, ...]",
        parent_cells: "tuple[dict, ...]",
        olds: "list[Table]",
        news: "list[Table]",
    ) -> None:
        for table_index in range(max(len(olds), len(news))):
            old = olds[table_index] if table_index < len(olds) else None
            new = news[table_index] if table_index < len(news) else None
            nested_path = table_path + (table_index,)
            if old is not None and new is not None:
                self._diff_table_cells(
                    region, region_idx, nested_path, parent_cells, old, new
                )
                continue
            table = old if old is not None else new
            assert table is not None
            text = _table_flat_text(table)
            if not text:
                continue
            loc = _table_location(
                region, region_idx, nested_path, parent_cells, "table"
            )
            label = _table_label(region, region_idx, nested_path, parent_cells)
            if old is not None:
                self._emit("removed", "table", loc, label, old_text=text)
            else:
                self._emit("added", "table", loc, label, new_text=text)

    # ---------------------------------------------------------- 영역 순회
    def run(self, old: Document, new: Document) -> None:
        old_regions = {lbl: secs for lbl, secs in _region_iter(old)}
        new_regions = {lbl: secs for lbl, secs in _region_iter(new)}
        for lbl in ("머리말", "본문", "꼬리말"):
            o_secs, n_secs = old_regions[lbl], new_regions[lbl]
            for ridx in range(max(len(o_secs), len(n_secs))):
                o_sec = o_secs[ridx] if ridx < len(o_secs) else Section([])
                n_sec = n_secs[ridx] if ridx < len(n_secs) else Section([])
                o_paras, o_tables = _split_blocks(lbl, ridx, o_sec)
                n_paras, n_tables = _split_blocks(lbl, ridx, n_sec)
                self._diff_paragraphs(o_paras, n_paras)
                self._diff_tables(lbl, ridx, o_tables, n_tables)


def _key_sort(key: tuple):
    """셀 키 정렬: addr 는 (rowAddr,colAddr), pos 는 (row,col). 종류별 그룹."""
    if key[0] == "addr":
        return (0, key[1], key[2])
    return (1, key[1], key[2])


def _addr_of(key: tuple) -> dict:
    if key[0] == "addr":
        return {"rowAddr": key[1], "colAddr": key[2]}
    return {"row": key[1], "col": key[2]}


def _addr_label(addr: dict) -> str:
    """주소 메타를 사람이 읽는 ``행,열`` 표기로 변환한다."""
    return (
        f"{addr.get('rowAddr', addr.get('row', '?'))},"
        f"{addr.get('colAddr', addr.get('col', '?'))}"
    )


def _table_location(
    region: str,
    region_idx: int,
    table_path: "tuple[int, ...]",
    parent_cells: "tuple[dict, ...]",
    unit: str,
) -> dict:
    """표 비교 단위 위치. 최상위 계약은 그대로, 중첩 경로만 확장한다."""
    location = {
        "region": region,
        "region_index": region_idx,
        "unit": unit,
        "table_index": table_path[0],
    }
    if len(table_path) > 1:
        location["table_path"] = list(table_path)
        location["parent_cells"] = [dict(addr) for addr in parent_cells]
    return location


def _table_label(
    region: str,
    region_idx: int,
    table_path: "tuple[int, ...]",
    parent_cells: "tuple[dict, ...]",
) -> str:
    """최상위 표부터 중첩 표까지 결정적인 사람이 읽는 위치 라벨."""
    label = f"{region} {region_idx + 1} · 표 {table_path[0] + 1}"
    for parent_addr, nested_index in zip(
        parent_cells, table_path[1:], strict=True
    ):
        label += (
            f" · 셀({_addr_label(parent_addr)})"
            f" · 중첩 표 {nested_index + 1}"
        )
    return label


def _index_cells(tbl: Table) -> "dict[tuple, object]":
    """표 셀을 정렬 키로 색인."""
    out: "dict[tuple, object]" = {}
    for ri, row in enumerate(tbl.rows):
        for ci, cell in enumerate(row):
            out[_cell_key(cell, ri, ci)] = cell
    return out


def _table_flat_text(tbl: Table) -> str:
    """표 전체를 개행 결합 텍스트로(추가/삭제 표 요약용)."""
    parts: "list[str]" = []
    for row in tbl.rows:
        for cell in row:
            t = _cell_text(cell)
            if t:
                parts.append(t)
    return "\n".join(parts)


def _split_blocks(region: str, ridx: int,
                  sec: Section) -> "tuple[list[_ParaUnit], list[tuple[int, Table]]]":
    """섹션 블록을 (문단 단위 목록, (순서,표) 목록) 으로 분리."""
    paras: "list[_ParaUnit]" = []
    tables: "list[tuple[int, Table]]" = []
    p_ord = 0
    for b in sec.blocks:
        if isinstance(b, Paragraph):
            loc = {"region": region, "region_index": ridx,
                   "unit": "paragraph", "index": p_ord}
            label = f"{region} {ridx + 1} · 문단 {p_ord + 1}"
            paras.append(_ParaUnit(b.text, loc, label))
            p_ord += 1
        elif isinstance(b, Table):
            tables.append((len(tables), b))
    return paras, tables


def row_group_key(label: str) -> str:
    """행 라벨 → 소속 그룹 헤더(마지막 단위 조각 제거) — 라벨 생산자(이 모듈) 소유.

    "본문 1 · 문단 12" → "본문 1", "본문 1 · 표 2 · 셀(3,4)" → "본문 1 · 표 2".
    구분자 ``' · '`` 는 위 라벨 생산 f-string 들과 한 몸이다 — 뷰가 라벨 문자열을
    준-API 로 재파싱하지 않도록 여기서 함께 관리한다.
    """
    parts = label.split(" · ")
    return " · ".join(parts[:-1]) if len(parts) > 1 else label


# --------------------------------------------------- 변경 항목(리뷰어 킬러기능)
def _build_change_items(changes: "list[Change]") -> "list[ChangeItem]":
    """changes 에서 우선순위 정렬된 사람용 변경 항목을 파생.

    규칙(단순·문서화):
      - 숫자/통화/퍼센트/날짜 토큰이 바뀐 changed -> ``number`` (최우선).
      - 조항 헤더(제N조·N.·별표) 추가/삭제 -> ``clause_added``/``clause_removed``.
      - 그 외 changed -> ``text_changed``.
      - 그 외 added/removed(표 포함) -> ``text_added``/``text_removed``/``table_*``.
    """
    items: "list[ChangeItem]" = []
    for c in changes:
        if c.kind == "renumber":
            op = _ordinal_prefix(c.old_text) or "(없음)"
            np = _ordinal_prefix(c.new_text) or "(없음)"
            items.append(ChangeItem(
                "renumber", _PRI_RENUMBER, c.seq, c.location_label,
                f"{op} → {np}  {_snippet(c.new_text)}",
                old=c.old_text, new=c.new_text))
        elif c.kind == "changed":
            pairs = _number_changes(c.old_text, c.new_text)
            if pairs:
                detail = "; ".join(
                    f"{o or '(없음)'} → {n or '(없음)'}" for o, n in pairs
                )
                items.append(ChangeItem(
                    "number", _PRI_NUMBER, c.seq, c.location_label,
                    detail, old=c.old_text, new=c.new_text))
            else:
                items.append(ChangeItem(
                    "text_changed", _PRI_CHANGED, c.seq, c.location_label,
                    _snippet(c.new_text), old=c.old_text, new=c.new_text))
        elif c.kind == "added":
            if c.unit == "paragraph" and _looks_like_clause(c.new_text):
                items.append(ChangeItem(
                    "clause_added", _PRI_CLAUSE, c.seq, c.location_label,
                    _snippet(c.new_text), new=c.new_text))
            else:
                cat = "table_added" if c.unit == "table" else "text_added"
                items.append(ChangeItem(
                    cat, _PRI_ADDREMOVE, c.seq, c.location_label,
                    _snippet(c.new_text), new=c.new_text))
        elif c.kind == "removed":
            if c.unit == "paragraph" and _looks_like_clause(c.old_text):
                items.append(ChangeItem(
                    "clause_removed", _PRI_CLAUSE, c.seq, c.location_label,
                    _snippet(c.old_text), old=c.old_text))
            else:
                cat = "table_removed" if c.unit == "table" else "text_removed"
                items.append(ChangeItem(
                    cat, _PRI_ADDREMOVE, c.seq, c.location_label,
                    _snippet(c.old_text), old=c.old_text))
    items.sort(key=lambda it: (it.priority, it.order))
    return items


def _snippet(text: str, limit: int = 60) -> str:
    """한 줄 요약용 발췌(개행 압축 + 길이 제한)."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def group_changes(rows: "list[DocRow]") -> "list[ChangeGroup]":
    """rows 스트림에서 문서상 인접·같은 종류의 변경을 한 그룹으로 묶는다(순수 함수).

    인접 판정은 rows 스트림 연속이다 — 사이에 equal 행(=변경 없는 원문)이 하나라도
    있으면 별개 그룹으로 남긴다. ``Change.seq`` 는 변경 방출 서수라 equal 을 소모하지
    않아(연속 seq ≠ 문서 인접) 떨어진 독립 변경을 거짓 병합한다.
    """
    groups: "list[ChangeGroup]" = []
    open_group: "ChangeGroup | None" = None
    for row in rows:
        if row.seq is None:  # equal 행 = 문서상 간격 → 인접성 단절
            open_group = None
            continue
        if open_group is not None and row.kind == open_group.kind:
            open_group.seqs.append(row.seq)
            continue
        open_group = ChangeGroup(row.kind, row.label,
                                 _snippet(row.new_text or row.old_text), [row.seq])
        groups.append(open_group)
    for g in groups:
        if len(g.seqs) > 1:
            g.detail += f"  (연속 {len(g.seqs)}건)"
    return groups


# ------------------------------------------------------------------ 공개 API
class EmptyExtractionError(ValueError):
    """두 판본 **모두** 추출 본문이 0 — '변경 없음' 단언 금지(빈 컨테이너 완전성 게이트).

    추출이 조용히 빈 결과를 내는 컨테이너(섹션 0개·본문 0)를 물리면 '두 판본이
    동일합니다'라는 최악 방향의 거짓 음성이 된다. 확인-또는-경보: 시끄럽게 실패한다.
    """


def _has_extracted_content(doc: Document) -> bool:
    """추출된 본문(비공백 문단 또는 내용 있는 표)이 하나라도 있으면 True."""
    for _lbl, secs in _region_iter(doc):
        for sec in secs:
            for b in sec.blocks:
                if isinstance(b, Paragraph) and b.text.strip():
                    return True
                if isinstance(b, Table) and _table_flat_text(b):
                    return True
    return False


def diff_documents(old: Document, new: Document) -> DiffResult:
    """두 Document 를 비교해 결정적 DiffResult 반환. 동일 문서면 변경 0.

    완전성 게이트: 양쪽 다 추출 본문이 0이면 :class:`EmptyExtractionError` —
    판본을 분리 로드하는 경로(CLI RC-16)도 게이트를 우회하지 못한다.
    """
    if not _has_extracted_content(old) and not _has_extracted_content(new):
        raise EmptyExtractionError(
            "두 판본 모두에서 본문을 추출하지 못했습니다 — '변경 없음'이 아니라 "
            "읽기 실패일 수 있습니다. 파일이 올바른 HWPX 인지 확인하세요."
        )
    differ = _Differ()
    differ.run(old, new)
    items = _build_change_items(differ.changes)
    summary = {
        "added": sum(1 for c in differ.changes if c.kind == "added"),
        "removed": sum(1 for c in differ.changes if c.kind == "removed"),
        "changed": sum(1 for c in differ.changes if c.kind == "changed"),
        "renumber": sum(1 for c in differ.changes if c.kind == "renumber"),
        "change_items": len(items),
    }
    return DiffResult(changes=differ.changes, change_items=items, summary=summary,
                      rows=differ.rows, change_groups=group_changes(differ.rows))


def diff_files(old_path: str, new_path: str) -> DiffResult:
    """두 HWPX 파일 경로를 추출·비교해 DiffResult 반환(편의 함수).

    완전성 게이트: 양쪽 다 추출 본문이 0이면 '변경 없음'을 단언할 근거가 없으므로
    :class:`EmptyExtractionError` 를 던진다(GUI 모달·CLI 오류 종료로 표면화).
    """
    old_doc = extract_document(old_path)
    new_doc = extract_document(new_path)
    if not _has_extracted_content(old_doc) and not _has_extracted_content(new_doc):
        raise EmptyExtractionError(
            "두 판본 모두에서 본문을 추출하지 못했습니다 — '변경 없음'이 아니라 "
            "읽기 실패일 수 있습니다. 파일이 올바른 HWPX 인지 확인하세요: "
            f"{old_path} ↔ {new_path}"
        )
    return diff_documents(old_doc, new_doc)


# ------------------------------------------------------------------ 렌더링
# 변경 종류(kind)의 표시 어휘·색 — 단일 출처(공개). GUI 신구대비표 뷰·변경 리스트가
# 여기서 당겨 쓴다. 색은 CATEGORY_COLORS 와 같은 계열(추가 초록/삭제 빨강/변경 파랑).
KIND_LABELS = {"added": "추가", "removed": "삭제", "changed": "변경",
               "renumber": "번호변경"}
KIND_COLORS = {"added": "#1e8449", "removed": "#c0392b", "changed": "#2874a6",
               "renumber": "#7a7f87"}
# del/ins 인라인 강조·행 배경 틴트 — 단일 출처(공개). GUI 전문 뷰 CSS 와 CLI HTML
# CSS 가 모두 여기서 당겨 쓴다(표면별 하드코딩은 같은 변경을 다른 색으로 보이게 한다).
KIND_TINTS = {"added": "#e5f2ea", "removed": "#fdecec"}
_KIND_LABEL = KIND_LABELS  # 하위호환 별칭

# 변경 0건의 빈 상태 카피 — 세 표면(GUI 요약 라벨·CLI 텍스트 요약·HTML 리포트) 공유.
NO_CHANGES_MESSAGE = "변경 없음."

# 변경항목 범주의 표시 어휘·배지색 — 단일 출처(공개). HTML 리포트의 `.b-{category}` 와
# GUI(diff_app) 리스트 배지가 모두 여기서 당겨 쓴다(사본을 두면 범주 추가가 조용히 어긋난다).
CATEGORY_LABELS = {
    "number": "숫자",
    "clause_added": "조항추가",
    "clause_removed": "조항삭제",
    "text_changed": "문구변경",
    "text_added": "추가",
    "text_removed": "삭제",
    "table_added": "표추가",
    "table_removed": "표삭제",
    "renumber": "번호변경",
}
CATEGORY_COLORS = {
    "number": "#c0392b",
    "clause_added": "#1e8449",
    "clause_removed": "#8e44ad",
    "text_changed": "#2874a6",
    "text_added": "#1e8449",
    "text_removed": "#7b241c",
    "table_added": "#1e8449",
    "table_removed": "#7b241c",
    "renumber": "#7a7f87",
}
_CAT_LABEL = CATEGORY_LABELS  # 하위호환 별칭


def render_summary(result: DiffResult) -> str:
    """터미널/PR 용 텍스트(마크다운) 요약."""
    s = result.summary
    substantive = [it for it in result.change_items if it.category != "renumber"]
    renumbers = [it for it in result.change_items if it.category == "renumber"]
    lines = [
        "# HWPX 규격서 개정 비교",
        "",
        "## 변경 요약",
        f"- 추가: {s.get('added', 0)}",
        f"- 삭제: {s.get('removed', 0)}",
        f"- 변경: {s.get('changed', 0)}",
        f"- 번호 변경: {s.get('renumber', 0)}",
        f"- 주요 변경 항목: {len(substantive)}",
        "",
    ]
    if substantive:
        lines.append("## 주요 변경 항목")
        for i, it in enumerate(substantive, 1):
            tag = _CAT_LABEL.get(it.category, it.category)
            lines.append(f"{i}. [{tag}] {it.location_label}: {it.detail}")
        lines.append("")
    if renumbers:
        # 낮은 우선순위 별도 항목 — 조용히 버리지 않되 실질 변경과 섞지 않는다.
        lines.append(f"## 번호 변경 ({len(renumbers)}건)")
        for i, it in enumerate(renumbers, 1):
            lines.append(f"{i}. {it.location_label}: {it.detail}")
        lines.append("")
    if not result.changes:
        lines.append(NO_CHANGES_MESSAGE)
    return "\n".join(lines).rstrip() + "\n"


# 낱말 diff 파편화 완화 — 변경 사이에 낀 이 길이 미만의 equal 조각은 양옆 변경에
# 흡수한다("제3조→제4조"의 '조' 같은 한두 글자가 del/ins 를 잘게 쪼개 붙이는 문제).
_COALESCE_MIN_EQUAL = 3


def coalesce_word_ops(ops: "list[WordOp] | None") -> "list[WordOp]":
    """변경 사이의 짧은 equal 조각을 replace 로 흡수 — 인라인 강조 가독성(순수 함수).

    공백뿐인 equal 은 낱말 경계라 남긴다(흡수하면 별개 낱말 변경이 한 덩어리로 뭉개짐).
    GUI 전문 뷰와 CLI HTML 리포트가 **같은 성형**을 공유한다 — 같은 DiffResult 가
    표면마다 다른 낱말 강조로 렌더되지 않도록. 빈 입력(None 포함)은 빈 리스트.
    """
    if not ops:
        return []
    out: "list[WordOp]" = []
    i = 0
    while i < len(ops):
        op = ops[i]
        if (op.op == "equal" and op.old.strip()
                and len(op.old) < _COALESCE_MIN_EQUAL
                and out and out[-1].op != "equal"
                and i + 1 < len(ops) and ops[i + 1].op != "equal"):
            prev = out.pop()
            nxt = ops[i + 1]
            out.append(WordOp(
                "replace",
                old=prev.old + op.old + nxt.old,
                new=prev.new + op.old + nxt.new,
            ))
            i += 2
            continue
        out.append(op)
        i += 1
    return out


def _render_inline(word_ops: "list[WordOp] | None", old: str, new: str) -> str:
    """낱말 op 를 인라인 del/ins HTML 로(coalesce 성형 공유). op 없으면 통째 교체 표시."""
    if not word_ops:
        return (f"<del>{html.escape(old)}</del>"
                f"<ins>{html.escape(new)}</ins>")
    out: "list[str]" = []
    for w in coalesce_word_ops(word_ops):
        if w.op == "equal":
            out.append(html.escape(w.old))
        elif w.op == "delete":
            out.append(f"<del>{html.escape(w.old)}</del>")
        elif w.op == "insert":
            out.append(f"<ins>{html.escape(w.new)}</ins>")
        else:
            out.append(f"<del>{html.escape(w.old)}</del>"
                       f"<ins>{html.escape(w.new)}</ins>")
    return "".join(out)


_HTML_CSS = """
body{font-family:'Malgun Gothic','맑은 고딕',sans-serif;margin:0;padding:24px;
background:#f6f7f9;color:#1b1b1b;line-height:1.6}
h1{font-size:20px;margin:0 0 16px}
h2{font-size:15px;margin:24px 0 8px;color:#333}
.summary{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.card{background:#fff;border:1px solid #e2e4e8;border-radius:8px;padding:10px 16px;
min-width:96px}
.card .n{font-size:22px;font-weight:700}
.card .l{font-size:12px;color:#666}
.items{background:#fff;border:1px solid #e2e4e8;border-radius:8px;padding:8px 4px}
.items table{width:100%;border-collapse:collapse;font-size:13px}
.items td,.items th{padding:6px 10px;border-bottom:1px solid #eef0f2;text-align:left;
vertical-align:top}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;
font-weight:700;color:#fff;white-space:nowrap}
.renumber-group{opacity:.72}
details{background:#fff;border:1px solid #e2e4e8;border-radius:8px;margin:8px 0;
padding:4px 12px}
summary{cursor:pointer;font-weight:600;font-size:13px;padding:6px 0}
.chg{padding:8px 0;border-top:1px solid #f0f1f3;font-size:13px}
.loc{color:#888;font-size:12px;margin-bottom:2px}
.empty{color:#888;font-style:italic}
""" + (
    # del/ins 강조·경계선은 KIND_TINTS/KIND_COLORS 에서 생성 — 팔레트 단일 출처
    # (GUI 전문 뷰 CSS 와 공유; 표면별 리터럴 이원화 방지).
    f"del{{background:{KIND_TINTS['removed']};color:{KIND_COLORS['removed']};"
    "text-decoration:line-through}\n"
    f"ins{{background:{KIND_TINTS['added']};color:{KIND_COLORS['added']};"
    "text-decoration:none}\n"
    f".added{{border-left:3px solid {KIND_COLORS['added']};padding-left:10px}}\n"
    f".removed{{border-left:3px solid {KIND_COLORS['removed']};padding-left:10px}}\n"
    f".changed{{border-left:3px solid {KIND_COLORS['changed']};padding-left:10px}}\n"
    f".renumber{{border-left:3px solid {KIND_COLORS['renumber']};padding-left:10px;"
    "opacity:.72}\n"
) + "\n".join(
    # 배지색은 CATEGORY_COLORS 에서 생성 — 팔레트 단일 출처(GUI 리스트 배지와 공유).
    f".b-{cat}{{background:{color}}}" for cat, color in CATEGORY_COLORS.items()
)


def render_html(result: DiffResult) -> str:
    """색상 구분·인라인 낱말 강조·접이식 섹션을 갖춘 자체 완결 HTML 리포트."""
    s = result.summary
    out: "list[str]" = []
    out.append("<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>")
    out.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    out.append("<title>HWPX 규격서 개정 비교</title>")
    out.append(f"<style>{_HTML_CSS}</style></head><body>")
    out.append("<h1>HWPX 규격서 개정 비교</h1>")

    # 변경 요약 — 종류 카드는 GUI KPI 타일과 같은 집합(번호변경 포함, RC-32).
    out.append("<div class='summary'>")
    for label, key in (("추가", "added"), ("삭제", "removed"),
                       ("변경", "changed"), ("번호변경", "renumber"),
                       ("주요 항목", "change_items")):
        out.append(f"<div class='card'><div class='n'>{s.get(key, 0)}</div>"
                   f"<div class='l'>{label}</div></div>")
    out.append("</div>")

    # 주요 변경 항목(재번호는 제외 — 아래 접이식 그룹으로 데모트)
    substantive = [it for it in result.change_items if it.category != "renumber"]
    renumbers = [it for it in result.change_items if it.category == "renumber"]
    if substantive:
        out.append("<h2>주요 변경 항목</h2><div class='items'><table>")
        out.append("<tr><th>#</th><th>구분</th><th>위치</th><th>내용</th></tr>")
        for i, it in enumerate(substantive, 1):
            tag = _CAT_LABEL.get(it.category, it.category)
            out.append(
                f"<tr><td>{i}</td>"
                f"<td><span class='badge b-{it.category}'>{tag}</span></td>"
                f"<td>{html.escape(it.location_label)}</td>"
                f"<td>{html.escape(it.detail)}</td></tr>"
            )
        out.append("</table></div>")

    # 번호 변경 — 기본 접힘·흐리게(loud omission: 보이되 눈에 덜 띄게)
    if renumbers:
        out.append("<details class='renumber-group'>")
        out.append(f"<summary>번호 변경 {len(renumbers)}건 "
                   "(본문 동일, 서수만 변경)</summary>")
        out.append("<div class='items'><table>")
        out.append("<tr><th>#</th><th>위치</th><th>내용</th></tr>")
        for i, it in enumerate(renumbers, 1):
            out.append(
                f"<tr><td>{i}</td>"
                f"<td>{html.escape(it.location_label)}</td>"
                f"<td>{html.escape(it.detail)}</td></tr>"
            )
        out.append("</table></div></details>")

    # 전체 변경 내역(접이식)
    out.append("<h2>전체 변경 내역</h2>")
    if not result.changes:
        out.append(f"<p class='empty'>{NO_CHANGES_MESSAGE}</p>")
    else:
        out.append(f"<details open><summary>{len(result.changes)}건</summary>")
        for c in result.changes:
            # 앵커: 변경항목 리스트(ChangeItem.order == Change.seq)에서 클릭 이동의 표적.
            # 브라우저 기준 id 만 — Qt 뷰용 <a name> 은 gui/diff_app 이 뷰 측에서 주입.
            out.append(f"<div class='chg {c.kind}' id='chg-{c.seq}'>")
            out.append(f"<div class='loc'>[{_KIND_LABEL.get(c.kind, c.kind)}] "
                       f"{html.escape(c.location_label)}</div>")
            if c.kind in ("changed", "renumber"):
                out.append(f"<div>{_render_inline(c.word_ops, c.old_text, c.new_text)}</div>")
            elif c.kind == "added":
                out.append(f"<div><ins>{html.escape(c.new_text)}</ins></div>")
            else:
                out.append(f"<div><del>{html.escape(c.old_text)}</del></div>")
            out.append("</div>")
        out.append("</details>")

    out.append("</body></html>")
    return "".join(out)
