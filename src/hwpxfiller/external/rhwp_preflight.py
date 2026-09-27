"""Fail-closed comparison of an HWPX document with rhwp's unchanged export."""

from __future__ import annotations

from zipfile import BadZipFile

import lxml.etree as etree  # pyright: ignore[reportMissingImports]

from hwpxcore.package import HwpxPackage

_HP_T = "{http://www.hancom.co.kr/hwpml/2011/paragraph}t"


def _drop_empty_text_elements(root: etree._Element) -> None:
    """Remove ``hp:t`` elements that hold no characters at all.

    rhwp writes ``<hp:t></hp:t>`` into every run that has no content (its run
    splitter does this on purpose so the run survives a re-import) and never
    writes the trailing empty ``hp:t`` Hancom leaves after a control such as a
    table. An ``hp:t`` with no attributes, no children, no text and no tail
    contributes zero characters, so removing it cannot change a run's text,
    its control order or its ``charPrIDRef``. Any ``hp:t`` carrying text,
    whitespace, inline markers or attributes is kept and still compared.
    """
    for element in root.findall(f".//{_HP_T}"):  # descendants only: a parent always exists
        if element.attrib or len(element) or element.text or element.tail:
            continue
        parent = element.getparent()
        assert parent is not None
        parent.remove(element)


def _canonical_xml(data: bytes) -> bytes:
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.fromstring(data, parser)
    _drop_empty_text_elements(root)
    # rhwp emits these false defaults on BOOKMARK fields even when the source
    # omits them. The observed values do not alter bookmark identity or content.
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "fieldBegin" or element.get("type") != "BOOKMARK":
            continue
        for name in ("editable", "dirty"):
            if element.get(name) == "0":
                element.attrib.pop(name)
    return etree.tostring(root, method="c14n")


def compare_rhwp_roundtrip(original: bytes, exported: bytes) -> dict:
    """Only proven serializer defaults are ignored; all other changes block editing."""
    try:
        source = HwpxPackage.from_bytes(original)
        result = HwpxPackage.from_bytes(exported)
    except (OSError, ValueError, TypeError, BadZipFile) as exc:
        return {"editable": False, "diagnostics": [
            {"kind": "invalid_package", "message": f"편집기가 내보낸 문서를 읽을 수 없습니다: {exc}"}
        ]}
    diagnostics: list[dict[str, str]] = []
    for entry in sorted(set(source.entries) | set(result.entries)):
        before = source.entries.get(entry)
        after = result.entries.get(entry)
        if before is None or after is None:
            diagnostics.append({"entry": entry, "kind": "entry_set_changed",
                                "message": "문서 내부 파일 구성이 변경되었습니다."})
            continue
        if before == after:
            continue
        if entry.lower().endswith((".xml", ".hpf")):
            try:
                if _canonical_xml(before) == _canonical_xml(after):
                    continue
            except (etree.XMLSyntaxError, ValueError):
                pass
            diagnostics.append({"entry": entry, "kind": "xml_changed",
                                "message": "문서 구조가 가져오기와 내보내기 사이에 변경되었습니다."})
        else:
            diagnostics.append({"entry": entry, "kind": "binary_changed",
                                "message": "문서 내부 파일이 가져오기와 내보내기 사이에 변경되었습니다."})
    return {"editable": not diagnostics, "diagnostics": diagnostics}
