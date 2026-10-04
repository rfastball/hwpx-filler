"""Native HWPX authoring: region blocks responsibilities."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping

import lxml.etree as etree  # pyright: ignore[reportMissingImports]

from hwpxcore.bookmark_region import (
    BookmarkRegion,
    resolve_bookmark_topology,
)
from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.text_extract import HP_NS

from ..domain.structure_scan import PLACEMENT_OPTION, PLACEMENT_SLOT
from .hwpx_product_inspection import (
    inspect_slot_regions,
)
from .hwpx_structure_ops import (
    structure_region_name,
)

_HP = f"{{{HP_NS}}}"
from .hwpx_authoring_regions import (
    is_product_tag as _is_product_tag,
    region_kind as _region_kind,
)

def _block_region(
    package, command: Mapping[str, object]
) -> tuple[BookmarkRegion, etree._Element, list[etree._Element], list[etree._Element]]:
    snapshot = inspect_slot_regions(package)
    if snapshot.diagnostics:
        raise ValueError("구조 오류가 있어 영역을 변경할 수 없습니다.")
    kind = _region_kind(command)
    slot_id = command.get("slot_id")
    option_id = command.get("option_id")
    if not isinstance(slot_id, str):
        raise ValueError("항목 식별자가 필요합니다.")
    if kind == PLACEMENT_OPTION:
        if not isinstance(option_id, str):
            raise ValueError("선택 식별자가 필요합니다.")
        region = snapshot.option_regions.get((slot_id, option_id))
    else:
        region = snapshot.slot_regions.get(slot_id)
    if region is None:
        raise ValueError("영역을 찾을 수 없습니다.")
    root = etree.fromstring(package.entries[region.section],
                            parser=etree.XMLParser(remove_blank_text=False, resolve_entities=False))
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    return region, root, paragraphs, paragraphs[region.start_paragraph:region.end_paragraph + 1]


def _boundary_ids(paragraphs: list) -> tuple[set[str], set[str]]:
    begins = {node.get("id") for paragraph in paragraphs
              for node in paragraph.iter(f"{_HP}fieldBegin") if node.get("id")}
    ends = {node.get("beginIDRef") for paragraph in paragraphs
            for node in paragraph.iter(f"{_HP}fieldEnd") if node.get("beginIDRef")}
    return begins, ends


def _native_identity(package) -> dict:
    return {(region.section, region._pairing_id):
            (region.name, region.meta_tags,
             None if region.parent is None else region.parent._pairing_id)
            for region in resolve_bookmark_topology(package)}


def _insertion_index(root, paragraphs: list, destination: int) -> int:
    if destination < len(paragraphs):
        return root.index(paragraphs[destination])
    return root.index(paragraphs[-1]) + 1


def _move_region(package, command: Mapping[str, object]) -> None:
    region, root, paragraphs, block = _block_region(package, command)
    destination = _move_destination(command, region, paragraphs, block)
    before_identity = _native_identity(package)
    for paragraph in block:
        root.remove(paragraph)
    remaining = [node for node in root if node.tag == f"{_HP}p"]
    adjusted = destination if destination < region.start_paragraph else destination - len(block)
    insertion = _insertion_index(root, remaining, adjusted)
    for index, paragraph in enumerate(block):
        root.insert(insertion + index, paragraph)
    package.entries[region.section] = serialize_modified_section(root)
    if _native_identity(package) != before_identity:
        raise ValueError("이동하면 기존 책갈피 소속이 달라집니다.")


def _move_destination(command, region, paragraphs, block) -> int:
    if command.get("destination_entry", region.section) != region.section:
        raise ValueError("다른 문서 영역으로는 이동할 수 없습니다.")
    if command.get("start", 0) != 0:
        raise ValueError("이동할 위치를 문단 시작에 놓으세요.")
    destination = command.get("destination_paragraph")
    if not isinstance(destination, int) or not 0 <= destination <= len(paragraphs):
        raise ValueError("이동할 문단 경계가 올바르지 않습니다.")
    lo, hi = region.start_paragraph, region.end_paragraph + 1
    if lo <= destination <= hi:
        raise ValueError("현재 영역 안으로 이동할 수 없습니다.")
    begins, ends = _boundary_ids(block)
    if begins != ends:
        raise ValueError("다른 영역이나 필드 경계가 걸친 문단은 이동할 수 없습니다.")
    return destination


def _cloneable_paragraphs(block: list) -> None:
    for paragraph in block:
        for child in paragraph:
            if child.tag == f"{_HP}lineSegArray":
                continue
            if child.tag != f"{_HP}run":
                raise ValueError("이 영역에 복제할 수 없는 문서 요소가 있습니다.")
            for item in child:
                _assert_cloneable_control(item)


def _assert_cloneable_control(item) -> None:
    if item.tag == f"{_HP}t" and not len(item):
        return
    if item.tag != f"{_HP}ctrl" or len(item) != 1:
        raise ValueError("이 영역에 복제할 수 없는 제어 요소가 있습니다.")
    field = item[0]
    if field.tag not in {f"{_HP}fieldBegin", f"{_HP}fieldEnd"}:
        raise ValueError("이 영역에 복제할 수 없는 제어 요소가 있습니다.")
    if field.tag == f"{_HP}fieldBegin" and any(node.tag != f"{_HP}metaTag" for node in field):
        raise ValueError("알 수 없는 필드 메타데이터는 복제할 수 없습니다.")


def _next_native_id(package) -> int:
    maximum = 0
    for entry, raw in package.entries.items():
        if not entry.lower().endswith(".xml"):
            continue
        root = etree.fromstring(raw, parser=etree.XMLParser(remove_blank_text=False,
                                                           resolve_entities=False))
        for element in root.iter():
            for attribute in ("id", "fieldid"):
                value = element.get(attribute)
                if value and value.isdecimal():
                    maximum = max(maximum, int(value))
    return maximum + 1


def _duplicate_region(package, command: Mapping[str, object]) -> None:
    region, root, paragraphs, block = _block_region(package, command)
    kind = _region_kind(command)
    new_id, destination, owner = _duplicate_destination(package, command, region, paragraphs, kind)
    _cloneable_paragraphs(block)
    internal = _clone_pairings(package, block, region)
    clones = _clone_without_external(block, internal)
    _remap_clones(package, clones, region, kind, command, new_id)
    _place_option_parent(root, clones, kind, owner, destination)
    insertion = _insertion_index(root, paragraphs, destination)
    for index, paragraph in enumerate(clones):
        root.insert(insertion + index, paragraph)
    package.entries[region.section] = serialize_modified_section(root)
    resolve_bookmark_topology(package)


def _duplicate_destination(package, command, region, paragraphs, kind):
    if command.get("destination_entry", region.section) != region.section:
        raise ValueError("다른 문서 영역으로는 복제할 수 없습니다.")
    if command.get("start", 0) != 0:
        raise ValueError("복제할 위치를 문단 시작에 놓으세요.")
    new_id = command.get("new_id")
    destination = command.get("destination_paragraph", region.end_paragraph + 1)
    if not isinstance(new_id, str) or not new_id.strip():
        raise ValueError("복제할 영역의 새 식별자가 필요합니다.")
    if not isinstance(destination, int) or not 0 <= destination <= len(paragraphs):
        raise ValueError("복제할 문단 경계가 올바르지 않습니다.")
    snapshot = inspect_slot_regions(package)
    owner = None
    if kind == PLACEMENT_OPTION:
        owner = _duplicate_option_owner(snapshot, command, destination, new_id)
    elif new_id in snapshot.slot_regions:
        raise ValueError("같은 이름의 항목이 이미 있습니다.")
    return new_id, destination, owner


def _duplicate_option_owner(snapshot, command, destination, new_id):
    slot_id = command.get("slot_id")
    assert isinstance(slot_id, str)
    owner = snapshot.slot_regions[slot_id]
    if not owner.start_paragraph <= destination <= owner.end_paragraph + 1:
        raise ValueError("복제한 선택은 같은 항목 안에 놓아야 합니다.")
    if (slot_id, new_id) in snapshot.option_regions:
        raise ValueError("같은 이름의 선택이 이미 있습니다.")
    return owner


def _clone_pairings(package, block, region) -> set[str]:
    begins, ends = _boundary_ids(block)
    internal = begins & ends
    if region._pairing_id not in internal:
        raise ValueError("영역 경계를 문단 단위로 복제할 수 없습니다.")
    for paragraph in block:
        for node in paragraph.iter(f"{_HP}fieldBegin"):
            if node.get("id") not in internal and node.get("type") != "BOOKMARK":
                raise ValueError("문단을 가로지르는 필드는 복제할 수 없습니다.")
        for node in paragraph.iter(f"{_HP}fieldEnd"):
            if node.get("beginIDRef") not in internal:
                # 외부 BOOKMARK 경계는 clone에서만 제거한다. 그 외는 짝이 없는 필드다.
                if not any(item._pairing_id == node.get("beginIDRef")
                           for item in resolve_bookmark_topology(package)):
                    raise ValueError("문단을 가로지르는 필드는 복제할 수 없습니다.")
    return internal


def _clone_without_external(block, internal):
    clones = [copy.deepcopy(paragraph) for paragraph in block]
    for paragraph in clones:
        for field in list(paragraph.iter(f"{_HP}fieldBegin")) + list(paragraph.iter(f"{_HP}fieldEnd")):
            key = field.get("id") if field.tag == f"{_HP}fieldBegin" else field.get("beginIDRef")
            if key in internal:
                continue
            ctrl = field.getparent()
            assert ctrl is not None
            ctrl.getparent().remove(ctrl)
    return clones


def _remap_clones(package, clones, region, kind, command, new_id) -> None:
    id_map = _clone_id_map(package, clones)
    originals = {new: old for old, new in id_map.items()}
    for paragraph in clones:
        for element in paragraph.iter():
            _remap_clone_element(element, id_map, originals, region, kind, command, new_id)


def _clone_id_map(package, clones) -> dict[str, str]:
    id_map: dict[str, str] = {}
    next_id = _next_native_id(package)
    for paragraph in clones:
        for element in paragraph.iter():
            for attribute in ("id", "fieldid"):
                old = element.get(attribute)
                if old is not None and old not in id_map:
                    id_map[old] = str(next_id)
                    next_id += 1
    return id_map


def _remap_clone_element(element, id_map, originals, region, kind, command, new_id) -> None:
    for attribute in ("id", "fieldid", "beginIDRef", "endIDRef"):
        old = element.get(attribute)
        if old in id_map:
            element.set(attribute, id_map[old])
    if element.tag == f"{_HP}fieldBegin" and element.get("type") == "BOOKMARK":
        _rename_clone_bookmark(element, originals.get(element.get("id")), region, kind, command, new_id)


def _rename_clone_bookmark(element, original_pairing, region, kind, command, new_id) -> None:
    if original_pairing == region._pairing_id:
        element.set("name", structure_region_name(
            new_id if kind == PLACEMENT_SLOT else str(command.get("slot_id")),
            new_id if kind == PLACEMENT_OPTION else None))
        _rename_clone_product_tags(element, new_id)
    elif kind == PLACEMENT_SLOT:
        prefix = str(command.get("slot_id")) + "/"
        if (element.get("name") or "").startswith(prefix):
            element.set("name", structure_region_name(new_id, (element.get("name") or "")[len(prefix):]))


def _rename_clone_product_tags(element, new_id) -> None:
    for tag in element.iter(f"{_HP}metaTag"):
        if tag.text and _is_product_tag(tag.text):
            payload = json.loads(tag.text)
            payload["hwpxFiller"]["id"] = new_id
            tag.text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _place_option_parent(root, clones, kind, owner, destination) -> None:
    if kind == PLACEMENT_OPTION and destination == owner.end_paragraph + 1:
        _move_parent_end(root, clones, owner)
    elif kind == PLACEMENT_OPTION and destination == owner.start_paragraph:
        _move_parent_begin(root, clones, owner)


def _move_parent_end(root, clones, owner) -> None:
    parent_end = next(node for node in root.iter(f"{_HP}fieldEnd")
                      if node.get("beginIDRef") == owner._pairing_id)
    parent_ctrl = parent_end.getparent()
    assert parent_ctrl is not None
    parent_ctrl.getparent().remove(parent_ctrl)
    last_runs = [node for node in clones[-1] if node.tag == f"{_HP}run"]
    last_runs[-1].append(parent_ctrl)


def _move_parent_begin(root, clones, owner) -> None:
    parent_begin = next(node for node in root.iter(f"{_HP}fieldBegin")
                        if node.get("id") == owner._pairing_id)
    parent_ctrl = parent_begin.getparent()
    assert parent_ctrl is not None
    parent_ctrl.getparent().remove(parent_ctrl)
    first_runs = [node for node in clones[0] if node.tag == f"{_HP}run"]
    first_runs[0].insert(0, parent_ctrl)


duplicate_region = _duplicate_region
move_region = _move_region
