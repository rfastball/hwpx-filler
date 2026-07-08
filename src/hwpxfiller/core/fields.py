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

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_NSMAP = {"hp": HP_NS}


def _local(tag: object) -> str:
    """요소의 로컬 태그명(네임스페이스 제거). 주석/PI 등은 빈 문자열."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


class FieldDocument:
    """단일 XML(section/header/footer) 문서에 대한 누름틀 편집기."""

    def __init__(self, xml_bytes: bytes):
        # 공백 보존(remove_blank_text=False 기본). 원본 선언/인코딩 정보 확보.
        parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
        self._tree = etree.fromstring(xml_bytes, parser=parser)
        self._modified = False

    @property
    def modified(self) -> bool:
        return self._modified

    # ---------------------------------------------------------- required
    def required_fields(self) -> "list[str]":
        """문서 내 모든 누름틀 이름을 중복 없이 반환. ``{{..}}`` 는 벗겨서."""
        seen: dict[str, None] = {}
        for node in self._tree.iterfind(f".//{{{HP_NS}}}fieldBegin"):
            name = (node.get("name") or "").strip()
            if not name:
                continue
            name = name.replace("{{", "").replace("}}", "")
            if name and name not in seen:
                seen[name] = None
        return list(seen)

    # ------------------------------------------------------------- inject
    def set_field(self, field_name: str, new_value: str) -> bool:
        """``field_name`` 누름틀에 값 주입. 실제 텍스트를 바꿨으면 True.

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
        if updated:
            self._modified = True
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
                            inner.text = new_value
                            first_text = False
                            touched = True
                        else:
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
        return etree.tostring(
            self._tree,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )
