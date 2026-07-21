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

from dataclasses import dataclass

from lxml import etree

from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.text_extract import _to_package

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_NSMAP = {"hp": HP_NS}


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


def _local(tag: object) -> str:
    """요소의 로컬 태그명(네임스페이스 제거). 주석/PI 등은 빈 문자열."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _clean_field_name(raw: object) -> str:
    """누름틀 이름의 공백과 선택적 ``{{..}}`` 표기를 정규화한다."""
    if not isinstance(raw, str):
        return ""
    name = raw.strip()
    if name.startswith("{{") and name.endswith("}}"):
        name = name[2:-2].strip()
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
        ctrl = begin.getparent()
        run = ctrl.getparent() if ctrl is not None and _local(ctrl.tag) == "ctrl" else ctrl
        if run is None or _local(run.tag) != "run":
            return ""

        parts: "list[str]" = []
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
                    parts.append("".join(inner.itertext()))
                elif name == "ctrl" and any(
                    _local(child.tag) == "fieldEnd" for child in inner
                ):
                    stop = True
                    break
            if stop:
                break
            current = current.getnext()
        return "".join(parts)

    # ------------------------------------------------------------- inject
    def set_field(self, field_name: str, new_value: str) -> bool:
        """``field_name`` 누름틀에 값 주입. 누름틀을 찾아 기입했으면 True.

        반환값은 매칭 보고용(값이 기존과 같아도 True — 호출측 unmatched 판정이
        거짓말하지 않게). 빈 누름틀(값 ``hp:t`` 부재)은 값 런을 합성해 기입한다
        (#154 — 과거의 unmatched 오보 소멸). False 는 begin 이 run 구조 밖일 때뿐.

        **읽기-쓰기 대칭 계약**: 성공한 ``set_field(f, V)`` 뒤 ``read_field(f) == V``.
        값 런의 인라인 자식 요소는 구값 소속이라 값과 함께 제거된다(#154 확정 —
        제거 사실은 ``notes`` 로 시끄럽게). 실제 변경 여부는 ``modified`` 가 추적한다.
        VBA SetField 와 동일하게 ``name`` 이 ``NAME`` 또는 ``{{NAME}}`` 인 모든
        누름틀을 처리한다.
        """
        clean = field_name.strip()
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
        for begin in begins:
            if self._fill_one(begin, new_value, note_name):
                updated += 1
        return updated > 0

    def _fill_one(self, begin: etree._Element, new_value: str, note_name: str) -> bool:
        """단일 fieldBegin 에 대해 fieldEnd 까지 텍스트를 채운다.

        1) begin~end 구간의 ``hp:t`` 슬롯을 수집하고, 2) 슬롯이 없으면 값 런을
        합성하며(#154), 3) 슬롯들의 인라인 자식을 제거한 뒤 첫 슬롯에 값을 기입,
        파편 슬롯은 비운다. 완화 처리(합성·자식 제거)는 ``_note`` 로 기록한다.
        """
        ctrl = begin.getparent()  # hp:ctrl
        run = ctrl.getparent() if ctrl is not None and _local(ctrl.tag) == "ctrl" else ctrl
        if run is None or _local(run.tag) != "run":
            return False

        # ---- 1) 수집: begin~end 구간의 hp:t 와 종료 지점
        ts: "list[etree._Element]" = []
        end_ctrl: "etree._Element | None" = None
        end_run: "etree._Element | None" = None
        found_begin = False
        current = run
        while current is not None and _local(current.tag) == "run":
            stop = False
            for inner in current:
                if not found_begin:
                    # fieldBegin(또는 그 부모 ctrl)을 지나야 이후 hp:t 가 대상
                    if inner is ctrl or inner is begin:
                        found_begin = True
                if not found_begin:
                    continue
                name = _local(inner.tag)
                if name == "t":
                    ts.append(inner)
                elif name == "ctrl" and any(
                    _local(c.tag) == "fieldEnd" for c in inner
                ):
                    end_ctrl = inner
                    end_run = current
                    stop = True
                    break
            if stop:
                break
            current = current.getnext()

        # ---- 2) 빈 누름틀: 값 런 합성(#154 — 기입 불가 대신 경고 후 진행)
        if not ts:
            if end_ctrl is ctrl:
                # 퇴화 형상: begin 과 end 가 한 ctrl 안 — 값 슬롯이 놓일 자리가
                # 구조적으로 없다. 조용한 오배치 대신 기입 불가로 시끄럽게.
                return False
            slot = etree.Element(f"{{{HP_NS}}}t")
            if end_ctrl is not None and end_run is run:
                # begin 과 end 가 같은 런 — end ctrl 바로 앞에 슬롯 삽입
                run.insert(run.index(end_ctrl), slot)
            else:
                # begin 런의 속성(charPrIDRef 등)을 통째로 승계 — authoring 의
                # 런 팩토리 관례(dict(run.attrib) 승계)와 동일.
                new_run = etree.Element(f"{{{HP_NS}}}run", dict(run.attrib))
                new_run.append(slot)
                if end_run is not None:
                    end_run.addprevious(new_run)
                else:
                    run.addnext(new_run)
            ts = [slot]
            self._modified = True  # 요소 삽입 자체가 변형
            self._note(note_name, "slot_synthesized")

        # ---- 3) 인라인 자식 제거 + 기입
        # 자식 요소(형광펜 마커 등)와 그 tail 텍스트는 구값 소속 — 값 교체와 함께
        # 제거한다(#154 확정: 읽기-쓰기 대칭이 계약. read_field 는 itertext 로 읽으므로
        # 자식 tail 이 남으면 기입값 ≠ 읽은값).
        stripped: "set[str]" = set()
        for t in ts:
            for child in list(t):
                stripped.add(_local(child.tag) or "#comment")
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


def read_fields(pkg_or_path: object) -> "dict[str, str]":
    """HWPX 패키지(경로/바이트/객체)의 모든 누름틀 현재 값을 반환한다.

    같은 이름이 여러 번 등장하면 문서 순서상 첫 값을 사용한다. ``set_field`` 는 같은
    이름의 모든 누름틀을 함께 갱신하므로 정상 템플릿에서는 값이 동일하다.
    """
    pkg = _to_package(pkg_or_path)
    values: "dict[str, str]" = {}
    for xml_name in pkg.content_xml_names():
        doc = FieldDocument(pkg.entries[xml_name])
        for field_name in doc.required_fields():
            value = doc.read_field(field_name)
            if value is not None:
                values.setdefault(field_name, value)
    return values
