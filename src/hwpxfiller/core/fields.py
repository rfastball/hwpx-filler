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

from lxml import etree

from hwpxcore.lineseg import strip_line_layout
from hwpxcore.text_extract import _to_package

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_NSMAP = {"hp": HP_NS}


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

    @property
    def modified(self) -> bool:
        """실제 텍스트가 바뀌었는가 — 값이 기존과 동일한 재채움은 변형이 아니다.

        스트립 게이트(#95)가 이 플래그를 소비하므로, 동일 값 재생성이 여전히 유효한
        줄배치 캐시를 잃지 않는다.
        """
        return self._modified

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
        거짓말하지 않게). 실제 텍스트 변경 여부는 ``modified`` 가 따로 추적한다.
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

        updated = 0
        for begin in begins:
            if self._fill_one(begin, new_value):
                updated += 1
        return updated > 0

    def _fill_one(self, begin: etree._Element, new_value: str) -> bool:
        """단일 fieldBegin 에 대해 fieldEnd 까지 텍스트를 채운다."""
        ctrl = begin.getparent()  # hp:ctrl
        run = ctrl.getparent() if ctrl is not None and _local(ctrl.tag) == "ctrl" else ctrl
        if run is None or _local(run.tag) != "run":
            return False

        touched = False
        first_text = True
        found_begin = False
        current = run

        while current is not None and _local(current.tag) == "run":
            stop = False
            for inner in current:
                if not found_begin:
                    # fieldBegin(또는 그 부모 ctrl)을 지나야 이후 hp:t 가 대상
                    if inner is ctrl or inner is begin:
                        found_begin = True
                if found_begin:
                    name = _local(inner.tag)
                    if name == "t":
                        if first_text:
                            if (inner.text or "") != new_value:
                                inner.text = new_value
                                self._modified = True  # 실제 변경만 변형으로 계상
                            first_text = False
                            touched = True
                        else:
                            if inner.text:
                                self._modified = True
                            inner.text = ""  # 파편 텍스트 제거
                    elif name == "ctrl":
                        # fieldEnd 를 품은 ctrl 이면 종료
                        if any(_local(c.tag) == "fieldEnd" for c in inner):
                            stop = True
                            break
            if stop:
                break
            current = current.getnext()
        return touched

    # -------------------------------------------------------------- output
    def to_bytes(self) -> bytes:
        # 변형된 문서만 stale 줄배치 캐시를 스트립(#95) — 미변경 문서의 캐시는
        # 여전히 유효하므로 보존한다.
        if self._modified:
            strip_line_layout(self._tree)
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
