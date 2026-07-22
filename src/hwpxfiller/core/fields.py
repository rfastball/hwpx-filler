"""HWPX 누름틀(Field) 주입 — VBA ``clsHWPXParser`` 의 lxml 포트.

누름틀은 다음과 같은 구조를 갖는다::

    <hp:run>
      <hp:ctrl><hp:fieldBegin name="계약명" .../></hp:ctrl>
    </hp:run>
    <hp:run><hp:t>여기에 값</hp:t></hp:run>
    ...
    <hp:run><hp:ctrl><hp:fieldEnd .../></hp:ctrl></hp:run>

``fieldBegin`` 과 ``fieldEnd`` 사이의 첫 ``hp:t`` 에 값을 넣고, 뒤따르는 파편
``hp:t`` 는 비운다. 원본 VBA 의 run-형제 순회 의미를 그대로 유지한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.package import HwpxPackage
from hwpxcore.text_extract import _to_package

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_NSMAP = {"hp": HP_NS}
_FIELD_PART_PATTERNS = (
    (0, re.compile(r"section(\d+)\.xml$", re.IGNORECASE)),
    (1, re.compile(r"header(\d+)\.xml$", re.IGNORECASE)),
    (2, re.compile(r"footer(\d+)\.xml$", re.IGNORECASE)),
)


@dataclass(frozen=True)
class FillNote:
    """채움이 "경고 후 진행"으로 처리한 사실의 기록(#154, confirm-or-alarm 완화).

    문안은 표면(CLI·웹) 소관 — 코어는 사실만 담는다.

    - ``kind="inline_stripped"``: 값 런의 인라인 자식 요소(형광펜 마커 등)를 제거하고
      기입했다. ``detail`` = 제거된 요소 로컬명(정렬·중복 제거). 짝 요소가 필드 경계를
      걸치면 한쪽만 제거될 수 있다 — 종류 명명이 그 검토 신호다.
    - ``kind="slot_synthesized"``: 값 ``hp:t`` 가 전혀 없는 빈 누름틀에 값 런을
      합성해 기입했다(과거엔 조용히 기입 불가 → unmatched 오보).
    """

    field: str
    kind: str
    detail: "tuple[str, ...]" = ()


@dataclass
class _FieldSpan:
    """누름틀 한 자리의 걸음 결과 — 읽기·쓰기가 공유하는 구간 사실."""

    run: etree._Element                       # begin 이 속한 런
    ctrl: "etree._Element | None"             # begin 을 품은 hp:ctrl
    ts: "list[etree._Element]"                # begin~end 사이 값 hp:t 들(문서 순서)
    end_ctrl: "etree._Element | None"         # fieldEnd 를 품은 ctrl(미확인이면 None)
    end_run: "etree._Element | None"          # end_ctrl 이 속한 런


def _local(tag: object) -> str:
    """요소의 로컬 태그명(네임스페이스 제거). 주석/PI 등은 빈 문자열."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _subtree_names(child: etree._Element) -> "set[str]":
    """제거 대상 하위트리의 노드 이름 전체 — 최상위만 대면 손실 집합 과소 고지."""
    names: "set[str]" = set()
    for node in child.iter():
        if isinstance(node, etree._Comment):
            names.add("#comment")
        elif isinstance(node, etree._ProcessingInstruction):
            names.add("#pi")
        else:
            names.add(_local(node.tag) or "#node")
    return names


def _strip_candidates(ts: "list[etree._Element]") -> "set[str]":
    """값 슬롯들의 인라인 자식 이름 집합 — 사전 판정과 사후 제거가 같은 집계를 쓴다."""
    names: "set[str]" = set()
    for t in ts:
        for child in t:
            names |= _subtree_names(child)
    return names


def _clean_field_name(raw: object) -> str:
    """누름틀 이름의 공백과 선택적 ``{{..}}`` 표기를 정규화한다.

    내부 연속 공백(탭·개행 포함)은 한 칸으로 접는다 — :meth:`FieldDocument.set_field`
    의 XPath 가 ``normalize-space(@name)`` 로 비교하므로, 읽기·나열·사전 판정이 다른
    정규화를 쓰면 "나열은 되는데 기입은 안 되는" 이름이 생긴다(리뷰 F4).
    """
    if not isinstance(raw, str):
        return ""
    name = " ".join(raw.split())
    if name.startswith("{{") and name.endswith("}}"):
        name = " ".join(name[2:-2].split())
    return name


class FieldDocument:
    """단일 XML(section/header/footer) 문서에 대한 누름틀 편집기."""

    def __init__(self, xml_bytes: bytes):
        # 공백 보존(remove_blank_text=False 기본). 원본 선언/인코딩 정보 확보.
        parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
        self._tree = etree.fromstring(xml_bytes, parser=parser)
        self._modified = False
        self._notes: "list[FillNote]" = []

    @property
    def modified(self) -> bool:
        """실제 텍스트가 바뀌었는가 — 값이 기존과 동일한 재채움은 변형이 아니다.

        스트립 게이트(#95)가 이 플래그를 소비하므로, 동일 값 재생성이 여전히 유효한
        줄배치 캐시를 잃지 않는다.
        """
        return self._modified

    @property
    def notes(self) -> "list[FillNote]":
        """채움이 "경고 후 진행"으로 처리한 사실들(#154). 호출측이 표면화할 것."""
        return list(self._notes)

    def _note(self, field: str, kind: str, detail: "tuple[str, ...]" = ()) -> None:
        note = FillNote(field, kind, detail)
        if note not in self._notes:
            self._notes.append(note)

    # ---------------------------------------------------------- required
    def required_fields(self) -> "list[str]":
        """문서 내 모든 누름틀 이름을 중복 없이 반환. ``{{..}}`` 는 벗겨서."""
        seen: dict[str, None] = {}
        for node in self._tree.iterfind(f".//{{{HP_NS}}}fieldBegin"):
            name = _clean_field_name(node.get("name"))
            if name and name not in seen:
                seen[name] = None
        return list(seen)

    # --------------------------------------------------------------- read
    def read_field(self, field_name: str) -> "str | None":
        """첫 ``field_name`` 누름틀의 현재 값을 반환한다.

        값은 ``fieldBegin`` 뒤부터 ``fieldEnd`` 앞까지 등장하는 모든 ``hp:t``
        파편을 문서 순서대로 이어 붙인다. 이름은 ``NAME`` 과 ``{{NAME}}`` 표기를
        동일하게 취급하며, 해당 필드가 없을 때만 ``None`` 을 반환한다.
        """
        clean = _clean_field_name(field_name)
        for begin in self._tree.iterfind(f".//{{{HP_NS}}}fieldBegin"):
            if _clean_field_name(begin.get("name")) == clean:
                return self._read_one(begin)
        return None

    def _read_one(self, begin: etree._Element) -> str:
        """단일 ``fieldBegin`` 과 짝을 이루는 종료 지점 사이의 텍스트를 읽는다."""
        span = self._field_span(begin)
        if span is None:
            return ""
        return "".join("".join(t.itertext()) for t in span.ts)

    # ---------------------------------------------------------------- span
    def _field_span(self, begin: etree._Element) -> "_FieldSpan | None":
        """begin 이 속한 런부터 짝 ``fieldEnd`` 까지 걷는 단일 걸음.

        읽기(:meth:`_read_one`)와 쓰기(:meth:`_fill_one`)가 이 걸음 하나를 공유한다 —
        두 순회가 갈라지면 읽기-쓰기 대칭 계약이 조용히 깨진다. ``begin`` 이 run 구조
        밖이면 None. ``end_ctrl`` 이 None 이면 걸음이 닫힘(fieldEnd)을 확인하지 못한
        구간이다(문단 경계 걸침 등).
        """
        ctrl = begin.getparent()
        run = ctrl.getparent() if ctrl is not None and _local(ctrl.tag) == "ctrl" else ctrl
        if run is None or _local(run.tag) != "run":
            return None

        ts: "list[etree._Element]" = []
        end_ctrl: "etree._Element | None" = None
        end_run: "etree._Element | None" = None
        found_begin = False
        current = run
        while current is not None and _local(current.tag) == "run":
            stop = False
            for inner in current:
                if not found_begin and (inner is ctrl or inner is begin):
                    found_begin = True
                if not found_begin:
                    continue
                name = _local(inner.tag)
                if name == "t":
                    ts.append(inner)
                elif name == "ctrl" and any(
                    _local(child.tag) == "fieldEnd" for child in inner
                ):
                    end_ctrl = inner
                    end_run = current
                    stop = True
                    break
            if stop:
                break
            current = current.getnext()
        return _FieldSpan(run, ctrl, ts, end_ctrl, end_run)

    # ----------------------------------------------------------- precheck
    def precheck(self) -> "list[FillNote]":
        """채움이 완화 처리(#154)를 일으킬 자리를 **변형 없이** 사전 열거한다.

        :meth:`set_field` 와 같은 걸음(:meth:`_field_span`)·같은 어휘(FillNote)로
        판정한다 — 사전 고지와 사후 노트가 같은 사실을 가리키게(표면 문안만 시제가
        다르다). 값 비교가 없는 사전 판정이라 ``inline_stripped`` 는 "다른 값을
        채우면 제거된다"는 조건부 사실이다.
        """
        notes: "list[FillNote]" = []
        for begin in self._tree.iterfind(f".//{{{HP_NS}}}fieldBegin"):
            name = _clean_field_name(begin.get("name"))
            if not name:
                continue
            span = self._field_span(begin)
            if span is None:
                # run 구조 밖 begin — set_field 도 기입 불가로 세는 자리.
                # 사전이 침묵하면 사후 노트와 어긋난다(2라운드 리뷰 F2).
                notes.append(FillNote(name, "occurrence_unfillable"))
                continue
            if span.ts:
                stripped = _strip_candidates(span.ts)
                if stripped:
                    notes.append(
                        FillNote(name, "inline_stripped", tuple(sorted(stripped)))
                    )
            elif span.end_ctrl is None or span.end_ctrl is span.ctrl:
                notes.append(FillNote(name, "occurrence_unfillable"))
            else:
                notes.append(FillNote(name, "slot_synthesized"))
        return list(dict.fromkeys(notes))

    # ------------------------------------------------------------- inject
    def set_field(self, field_name: str, new_value: str) -> bool:
        """``field_name`` 누름틀에 값 주입. 기입 가능한 자리가 하나라도 있으면 True.

        반환값은 매칭 보고용(값이 기존과 같아도 True — 호출측 unmatched 판정이
        거짓말하지 않게). 빈 누름틀(값 ``hp:t`` 부재)은 짝 ``fieldEnd`` 로 닫힘이
        확인된 경우에만 값 런을 합성해 기입한다(#154). False = 기입 가능한 자리가
        전무할 때(begin 이 run 구조 밖·짝 미확인·퇴화 형상) — 호출측 unmatched 로
        시끄럽게. 일부 자리만 기입되면 True 이되 ``occurrence_unfillable`` 노트를
        남긴다(조용한 부분 기입 금지).

        **읽기-쓰기 대칭 계약**: 성공한 ``set_field(f, V)`` 뒤 ``read_field(f) == V``.
        이미 그 상태면 무연산(자식 요소·바이트 불변 — #95 동일 값 재채움 안정).
        값을 실제로 바꿀 때 값 런의 인라인 자식 요소는 구값 소속이라 값과 함께
        제거된다(#154 확정 — 제거 사실은 ``notes`` 로 시끄럽게). 실제 변경 여부는
        ``modified`` 가 추적한다. VBA SetField 와 동일하게 ``name`` 이 ``NAME`` 또는
        ``{{NAME}}`` 인 모든 누름틀을 처리한다.
        """
        # 내부 공백까지 normalize-space 와 같은 규칙으로 접는다 — @name 쪽만 접고
        # 리터럴 쪽을 안 접으면 공백 변주 이름이 영원히 못 맞는다(리뷰 F4).
        clean = " ".join(field_name.split())
        # normalize-space + {{}} 대응 XPath (원본과 동일 의미)
        xpath = (
            f".//hp:fieldBegin["
            f"normalize-space(@name)='{clean}' or "
            f"normalize-space(@name)='{{{{{clean}}}}}']"
        )
        begins = self._tree.xpath(xpath, namespaces=_NSMAP)
        if not begins:
            return False

        note_name = _clean_field_name(field_name)
        updated = 0
        skipped = 0
        for begin in begins:
            if self._fill_one(begin, new_value, note_name):
                updated += 1
            else:
                skipped += 1
        if skipped:
            # 기입 불가 자리가 하나라도 있으면 노트 — updated>0 조건을 걸면 다른
            # 섹션이 같은 이름을 채우는 경우(엔진이 applied 로 집계) 이 문서의 빈
            # 자리가 어디에도 안 나오는 조용한 소실이 된다(2라운드 리뷰 F1).
            # 전 자리 불가(updated=0)면 unmatched 와 겹치지만, unmatched 의 "매칭
            # 실패" 오진을 이 노트가 바로잡는다 — 과경고가 조용한 소실보다 낫다.
            self._note(note_name, "occurrence_unfillable")
        return updated > 0

    def _fill_one(self, begin: etree._Element, new_value: str, note_name: str) -> bool:
        """단일 fieldBegin 에 대해 fieldEnd 까지 텍스트를 채운다.

        1) 공유 걸음(:meth:`_field_span`)으로 구간을 수집하고, 2) 이미 목표 상태면
        무연산, 3) 슬롯이 없으면 닫힘 확인된 구간에 한해 값 런을 합성하며(#154),
        4) 슬롯들의 인라인 자식을 제거한 뒤 첫 슬롯에 값을 기입, 파편 슬롯은
        비운다. 완화 처리(합성·자식 제거)는 ``_note`` 로 기록한다.
        """
        span = self._field_span(begin)
        if span is None:
            return False
        ts = span.ts

        # ---- 2) 목표 상태 선판정 — 이미 read_field == new_value 면 아무것도 안
        # 건드린다(#95 동일 값 재채움 바이트 안정: 무해한 자식 요소·캐시 보존).
        if ts and "".join("".join(t.itertext()) for t in ts) == new_value:
            return True

        # ---- 3) 빈 누름틀: 값 런 합성(#154 — 기입 불가 대신 경고 후 진행)
        if not ts:
            if span.end_ctrl is None or span.end_ctrl is span.ctrl:
                # 닫힘(fieldEnd) 미확인 구간(문단 경계 걸침 등)엔 합성하지 않는다 —
                # 걸음 밖에 남은 구값과 중복 출력된다(리뷰 F3). begin·end 가 한
                # ctrl 안인 퇴화 형상은 슬롯 자리가 없다. 둘 다 기입 불가로 시끄럽게.
                return False
            slot = etree.Element(f"{{{HP_NS}}}t")
            if span.end_run is span.run:
                # begin 과 end 가 같은 런 — end ctrl 바로 앞에 슬롯 삽입
                span.run.insert(span.run.index(span.end_ctrl), slot)
            else:
                # begin 런의 속성(charPrIDRef 등)을 통째로 승계 — authoring 의
                # 런 팩토리 관례(dict(run.attrib) 승계)와 동일.
                new_run = etree.Element(f"{{{HP_NS}}}run", dict(span.run.attrib))
                new_run.append(slot)
                assert span.end_run is not None  # end_ctrl 확인됨 → end_run 존재
                span.end_run.addprevious(new_run)
            ts = [slot]
            self._modified = True  # 요소 삽입 자체가 변형
            self._note(note_name, "slot_synthesized")

        # ---- 4) 인라인 자식 제거 + 기입
        # 자식 요소(형광펜 마커 등)와 그 tail 텍스트는 구값 소속 — 값 교체와 함께
        # 제거한다(#154 확정: 읽기-쓰기 대칭이 계약. read_field 는 itertext 로 읽으므로
        # 자식 tail 이 남으면 기입값 ≠ 읽은값). detail 은 하위트리 전체를 열거한다 —
        # 최상위 이름만 대면 실제 손실 집합을 과소 고지한다(문안 정직성).
        stripped = _strip_candidates(ts)
        for t in ts:
            for child in list(t):
                t.remove(child)
                self._modified = True
        if stripped:
            self._note(note_name, "inline_stripped", tuple(sorted(stripped)))

        first = ts[0]
        if (first.text or "") != new_value:
            first.text = new_value
            self._modified = True  # 실제 변경만 변형으로 계상
        for frag in ts[1:]:
            if frag.text:
                # 파편 텍스트 제거 — 실제로 지울 텍스트가 있을 때만 대입한다
                # (무조건 "" 대입은 <hp:t/> 를 무플래그로 바이트 변이시킴)
                frag.text = ""
                self._modified = True
        return True

    # -------------------------------------------------------------- output
    def to_bytes(self) -> bytes:
        # 변형된 문서만 stale 줄배치 캐시를 스트립(#95) — 미변경 문서의 캐시는
        # 여전히 유효하므로 보존한다.
        if self._modified:
            return serialize_modified_section(self._tree)
        return etree.tostring(
            self._tree,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )


def field_xml_names(pkg: HwpxPackage) -> "list[str]":
    """필드 대상 XML을 본문→머리말→꼬리말, 각 번호순으로 반환한다.

    동일 필드명이 여러 파트에 있어도 이 목록의 모든 파트를 채운다. 읽기에서 중복
    이름의 첫 값을 고를 때도 같은 순서를 사용해 package ZIP 엔트리 순서에 의미가
    새지 않게 한다. 숫자 접미사가 없는 ``header.xml`` 같은 스타일 파트는 필드가
    없을 때만 제외한다. 미지원 이름에 ``fieldBegin``이 있으면 조용히 누락하지 않고
    loud failure로 남긴다.
    """
    supported: "list[tuple[int, int, str]]" = []
    unsupported: "list[str]" = []
    for name in pkg.content_xml_names():
        base = name.rsplit("/", 1)[-1]
        for region_order, pattern in _FIELD_PART_PATTERNS:
            match = pattern.fullmatch(base)
            if match:
                supported.append((region_order, int(match.group(1)), name))
                break
        else:
            if FieldDocument(pkg.entries[name]).required_fields():
                unsupported.append(name)

    if unsupported:
        joined = ", ".join(sorted(unsupported))
        raise ValueError(f"지원하지 않는 필드 XML 파트: {joined}")

    supported.sort(key=lambda item: (item[0], item[1], item[2]))
    return [name for _, _, name in supported]


def fill_precheck(pkg_or_path: object) -> "list[FillNote]":
    """HWPX 패키지 전체의 채움 완화 사전 판정(#154) — 변형 없음, 중복 없이.

    템플릿 점검 표면(라이브러리 등)이 "채우면 무슨 일이 생기는가"를 실행 전에
    고지하는 데 쓴다. 사후 노트(:attr:`FieldDocument.notes`)와 같은 어휘.
    """
    pkg = _to_package(pkg_or_path)
    notes: "list[FillNote]" = []
    for xml_name in field_xml_names(pkg):
        notes.extend(FieldDocument(pkg.entries[xml_name]).precheck())
    return list(dict.fromkeys(notes))


def read_fields(pkg_or_path: object) -> "dict[str, str]":
    """HWPX 패키지(경로/바이트/객체)의 모든 누름틀 현재 값을 반환한다.

    같은 이름이 여러 번 등장하면 문서 순서상 첫 값을 사용한다. ``set_field`` 는 같은
    이름의 모든 누름틀을 함께 갱신하므로 정상 템플릿에서는 값이 동일하다.
    """
    pkg = _to_package(pkg_or_path)
    values: "dict[str, str]" = {}
    for xml_name in field_xml_names(pkg):
        doc = FieldDocument(pkg.entries[xml_name])
        for field_name in doc.required_fields():
            value = doc.read_field(field_name)
            if value is not None:
                values.setdefault(field_name, value)
    return values
