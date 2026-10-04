"""Validated HWPX semantic block transfer between disposable packages."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping

import lxml.etree as etree  # pyright: ignore[reportMissingImports]

from hwpxcore.bookmark_region import resolve_bookmark_topology
from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.package import HwpxPackage
from hwpxcore.text_extract import HP_NS

from .hwpx_authoring import analyze_hwpx

_HP = f"{{{HP_NS}}}"


def section_root(package: HwpxPackage, entry: str):
    if entry not in package.entries:
        raise ValueError("붙여넣을 문서 영역을 찾을 수 없습니다.")
    return etree.fromstring(package.entries[entry], parser=etree.XMLParser(resolve_entities=False))


def next_id(package: HwpxPackage) -> int:
    maximum = 0
    for entry, raw in package.entries.items():
        if not entry.endswith(".xml"):
            continue
        root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False))
        for element in root.iter():
            for attribute in ("id", "fieldid"):
                value = element.get(attribute)
                if value and value.isdecimal():
                    maximum = max(maximum, int(value))
    return maximum + 1


def _selected_semantic(package: HwpxPackage, selector: Mapping[str, object]):
    kind = selector.get("kind")
    for slot in analyze_hwpx(package)["slots"]:
        candidates = [slot] if kind == "slot" else slot["options"]
        for item in candidates:
            if slot["id"] == selector.get("slot_id") and (kind == "slot" or item["id"] == selector.get("option_id")):
                return item
    return None


def _region_from_selector(package: HwpxPackage, selector: Mapping[str, object]):
    selected = _selected_semantic(package, selector)
    if selected is None or selected["location"] is None or selected["raw"] is None:
        raise ValueError("복사할 영역을 찾을 수 없습니다.")
    loc, raw = selected["location"], selected["raw"]
    region = next((item for item in resolve_bookmark_topology(package)
                   if item.section == loc["entry"] and item.name == raw["bookmark_name"]
                   and item.start_paragraph == loc["start_paragraph"]
                   and item.end_paragraph == loc["end_paragraph"]), None)
    assert region is not None
    return region, selected


def _destination(target: HwpxPackage, destination: Mapping[str, object]):
    entry = destination.get("entry")
    index = destination.get("destination_paragraph")
    if not isinstance(entry, str) or not isinstance(index, int) or destination.get("start", 0) != 0:
        raise ValueError("붙여넣을 문단 시작 위치를 고르세요.")
    root = section_root(target, entry)
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    if not paragraphs:
        raise ValueError("붙여넣을 문단이 없습니다.")
    if not 0 <= index <= len(paragraphs):
        raise ValueError("붙여넣을 문단 경계가 올바르지 않습니다.")
    return entry, index, root, paragraphs


def _has_text(nodes) -> bool:
    return any(node.tag == f"{_HP}t" and (node.text or "") for node in nodes)


def _assert_complete_boundary(block, region) -> None:
    first_boundary = next((node for node in block[0].iter(f"{_HP}fieldBegin")
                           if node.get("id") == region._pairing_id), None)
    last_boundary = next((node for node in block[-1].iter(f"{_HP}fieldEnd")
                          if node.get("beginIDRef") == region._pairing_id), None)
    if first_boundary is None or last_boundary is None:
        raise ValueError("영역 경계를 문단 단위로 복사할 수 없습니다.")
    first_nodes, last_nodes = list(block[0].iter()), list(block[-1].iter())
    if (_has_text(first_nodes[:first_nodes.index(first_boundary)])
            or _has_text(last_nodes[last_nodes.index(last_boundary) + 1:])):
        raise ValueError("문단 일부만 포함한 의미 영역은 내용 손실 없이 복사할 수 없습니다.")


def _assert_supported_paragraph(paragraph) -> None:
    for child in paragraph:
        if child.tag == f"{_HP}lineSegArray":
            continue
        if child.tag != f"{_HP}run" or any(item.tag not in {f"{_HP}t", f"{_HP}ctrl"} for item in child):
            raise ValueError("복합 문서 요소는 의미째 붙여넣을 수 없습니다.")
        for control in child.iter(f"{_HP}ctrl"):
            if len(control) != 1 or control[0].tag not in {f"{_HP}fieldBegin", f"{_HP}fieldEnd"}:
                raise ValueError("지원하지 않는 제어 요소가 포함되어 있습니다.")


def _source_block(source: HwpxPackage, region):
    source_root = section_root(source, region.section)
    source_paragraphs = [node for node in source_root if node.tag == f"{_HP}p"]
    block = source_paragraphs[region.start_paragraph:region.end_paragraph + 1]
    _assert_complete_boundary(block, region)
    for paragraph in block:
        _assert_supported_paragraph(paragraph)
    return block


def _internal_pairings(block) -> set[str | None]:
    begins = {node.get("id") for paragraph in block for node in paragraph.iter(f"{_HP}fieldBegin")}
    ends = {node.get("beginIDRef") for paragraph in block for node in paragraph.iter(f"{_HP}fieldEnd")}
    return begins & ends


def _clone_content(block, with_meaning: bool):
    internal = _internal_pairings(block)
    clones = [copy.deepcopy(paragraph) for paragraph in block]
    for paragraph in clones:
        for control in list(paragraph.iter(f"{_HP}ctrl")):
            field = control[0]
            pairing = field.get("id") if field.tag == f"{_HP}fieldBegin" else field.get("beginIDRef")
            if not with_meaning or pairing not in internal:
                control.getparent().remove(control)
    return clones


def _assert_field_links(source: HwpxPackage, target_detail: dict, region, destination: Mapping[str, object]) -> None:
    copied_names = {field["name"] for field in analyze_hwpx(source)["fields"]
                    for occurrence in field["occurrences"]
                    if occurrence["entry"] == region.section
                    and isinstance(occurrence["paragraph"], int)
                    and region.start_paragraph <= occurrence["paragraph"] <= region.end_paragraph}
    if copied_names & {field["name"] for field in target_detail["fields"]} and destination.get("link_existing") is not True:
        raise ValueError("같은 이름의 필드가 있습니다. 기존 필드 연결을 확인하세요.")


def _assert_slot_destination(target: HwpxPackage, detail: dict, entry: str, index: int, new_id: str) -> None:
    if any(slot["id"] == new_id for slot in detail["slots"]):
        raise ValueError("같은 항목 식별자가 있습니다. 새 식별자를 입력하세요.")
    if any(item.section == entry and item.start_paragraph < index <= item.end_paragraph
           for item in resolve_bookmark_topology(target)):
        raise ValueError("항목을 다른 의미 영역 안에 넣을 수 없습니다.")


def _option_owner(detail: dict, entry: str, index: int, new_id: str, destination: Mapping[str, object]):
    owner_id = destination.get("slot_id")
    owner = next((slot for slot in detail["slots"] if slot["id"] == owner_id), None)
    if owner is None or owner["location"]["entry"] != entry or any(
        option["id"] == new_id for option in owner["options"]
    ):
        raise ValueError("상위 항목이나 선택 식별자를 확인하세요.")
    if not owner["location"]["start_paragraph"] < index <= owner["location"]["end_paragraph"]:
        raise ValueError("선택은 상위 항목 안의 문단 경계에 붙여넣으세요.")
    return owner_id


def _meaning_name(source: HwpxPackage, target: HwpxPackage, selector: Mapping[str, object],
                  destination: Mapping[str, object], region, selected: dict, entry: str, index: int):
    new_id = destination.get("new_id") or selected["id"]
    if not isinstance(new_id, str) or not new_id.strip():
        raise ValueError("새 식별자를 입력하세요.")
    detail = analyze_hwpx(target)
    _assert_field_links(source, detail, region, destination)
    if selector["kind"] == "slot":
        _assert_slot_destination(target, detail, entry, index, new_id)
        return new_id, None
    return new_id, _option_owner(detail, entry, index, new_id, destination)


def _id_map(target: HwpxPackage, clones) -> dict[str, str]:
    result: dict[str, str] = {}
    next_native_id = next_id(target)
    for paragraph in clones:
        for element in paragraph.iter():
            for attribute in ("id", "fieldid"):
                old = element.get(attribute)
                if old is not None and old not in result:
                    result[old] = str(next_native_id)
                    next_native_id += 1
    return result


def _rename_bookmark(element, original: str | None, region, selector: Mapping[str, object],
                     new_id: str, owner_id: object) -> None:
    if original == region._pairing_id:
        element.set("name", new_id if selector["kind"] == "slot" else f"{owner_id}/{new_id}")
        for tag in element.iter(f"{_HP}metaTag"):
            if tag.text and '"hwpxFiller"' in tag.text:
                payload = json.loads(tag.text)
                payload["hwpxFiller"]["id"] = new_id
                tag.text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    elif selector["kind"] == "slot":
        old_prefix = str(selector["slot_id"]) + "/"
        if (element.get("name") or "").startswith(old_prefix):
            element.set("name", f"{new_id}/{(element.get('name') or '')[len(old_prefix):]}")


def _remap_element(element, id_map: dict[str, str], originals: dict[str, str], region,
                   selector: Mapping[str, object], new_id: str, owner_id: object) -> None:
    for attribute in ("id", "fieldid", "beginIDRef", "endIDRef"):
        old = element.get(attribute)
        if old in id_map:
            element.set(attribute, id_map[old])
    if element.tag == f"{_HP}fieldBegin" and element.get("type") == "BOOKMARK":
        _rename_bookmark(element, originals.get(element.get("id")), region, selector, new_id, owner_id)


def _remap_clones(target: HwpxPackage, clones, region, selector: Mapping[str, object],
                  new_id: str, owner_id: object) -> None:
    id_map = _id_map(target, clones)
    originals = {mapped: old for old, mapped in id_map.items()}
    for paragraph in clones:
        for element in paragraph.iter():
            _remap_element(element, id_map, originals, region, selector, new_id, owner_id)


def _insert(target: HwpxPackage, entry: str, index: int, root, paragraphs, clones) -> None:
    insertion = root.index(paragraphs[index]) if index < len(paragraphs) else root.index(paragraphs[-1]) + 1
    for offset, paragraph in enumerate(clones):
        root.insert(insertion + offset, paragraph)
    target.entries[entry] = serialize_modified_section(root)
    resolve_bookmark_topology(target)


def block_paste(source: HwpxPackage, target: HwpxPackage, selector: Mapping[str, object],
                destination: Mapping[str, object], with_meaning: bool) -> tuple[str, str]:
    region, selected = _region_from_selector(source, selector)
    entry, index, root, paragraphs = _destination(target, destination)
    block = _source_block(source, region)
    clones = _clone_content(block, with_meaning)
    if with_meaning:
        new_id, owner_id = _meaning_name(source, target, selector, destination, region, selected, entry, index)
        _remap_clones(target, clones, region, selector, new_id, owner_id)
    _insert(target, entry, index, root, paragraphs, clones)
    plain = "\n".join("".join(node.text or "" for node in paragraph.iter(f"{_HP}t")) for paragraph in block)
    return "", plain
