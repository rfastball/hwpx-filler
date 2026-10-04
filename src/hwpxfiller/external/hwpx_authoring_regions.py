"""Native HWPX authoring: regions responsibilities."""

from __future__ import annotations

import json
from collections.abc import Mapping

import lxml.etree as etree  # pyright: ignore[reportMissingImports]

from hwpxcore.bookmark_region import (
    append_bookmark_metatag,
    create_bookmark_region,
    resolve_bookmark_topology,
)
from hwpxcore.lineseg import serialize_modified_section
from hwpxcore.text_extract import HP_NS

from ..domain.slot import Slot, SlotOption
from ..domain.structure_scan import PLACEMENT_OPTION, PLACEMENT_SLOT
from ..domain.template_authoring import (
    REASON_REGION_IN_CELL,
    REASON_NEED_IDENTIFIER,
    REASON_NEED_NEW_IDENTIFIER,
    InvalidName,
)
from .hwpx_product_inspection import (
    inspect_slot_regions,
    serialize_slot_metatag,
    serialize_slot_option_metatag,
)
from .hwpx_structure_ops import (
    structure_region_name,
)

_HP = f"{{{HP_NS}}}"
from .hwpx_authoring_fields import (
    require_clean as _require_clean,
)

def _rename_region(package, command: Mapping[str, object]) -> None:
    snapshot, kind, slot_id, option_id, region = _rename_target(package, command)
    identifier, payload, previous_slot = _rename_payload(snapshot, kind, slot_id, option_id, command)
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    root = etree.fromstring(package.entries[region.section], parser=parser)
    _replace_region_metadata(root, region, payload, kind, slot_id, identifier)
    if previous_slot is not None and identifier != slot_id:
        _rename_child_bookmarks(root, previous_slot, slot_id, identifier)
    package.entries[region.section] = serialize_modified_section(root)
    resolve_bookmark_topology(package)


def _rename_target(package, command):
    snapshot = inspect_slot_regions(package)
    if snapshot.diagnostics:
        raise ValueError("문서 구조 오류를 먼저 수정하세요.")
    kind = PLACEMENT_OPTION if command.get("type") == "rename_option" else PLACEMENT_SLOT
    slot_id = command.get("slot_id")
    option_id = command.get("option_id")
    if not isinstance(slot_id, str) or (kind == PLACEMENT_OPTION and not isinstance(option_id, str)):
        raise ValueError("항목이나 선택의 식별자가 필요합니다.")
    if kind == PLACEMENT_OPTION:
        assert isinstance(option_id, str)
        region = snapshot.option_regions.get((slot_id, option_id))
    else:
        region = snapshot.slot_regions.get(slot_id)
    if region is None:
        raise ValueError("항목이나 선택 영역을 찾을 수 없습니다.")
    return snapshot, kind, slot_id, option_id, region


def _rename_payload(snapshot, kind, slot_id, option_id, command):
    identifier = command.get("id", option_id if kind == PLACEMENT_OPTION else slot_id)
    label = command.get("label")
    if not isinstance(identifier, str) or not identifier.strip():
        # 식별자 칸의 거절(P-06) — 원문 표기로 되쓸 수 없는 식별자는 책갈피 메타가 정본이라 받는다(구문 보기가 생략).
        raise InvalidName("identifier", REASON_NEED_NEW_IDENTIFIER)
    if label is not None and not isinstance(label, str):
        raise ValueError("표시 이름은 텍스트여야 합니다.")
    if kind == PLACEMENT_SLOT:
        return identifier, _slot_rename_payload(snapshot, slot_id, identifier, label, command), next(
            slot for slot in snapshot.slots if slot.id == slot_id)
    return identifier, _option_rename_payload(snapshot, slot_id, option_id, identifier, label, command), None


def _slot_rename_payload(snapshot, slot_id, identifier, label, command):
    if identifier != slot_id and identifier in snapshot.slot_regions:
        raise ValueError("항목 식별자가 이미 있습니다.")
    previous = next(slot for slot in snapshot.slots if slot.id == slot_id)
    return serialize_slot_metatag(Slot(identifier, previous.options,
                                       previous.label if "label" not in command else label))


def _option_rename_payload(snapshot, slot_id, option_id, identifier, label, command):
    if identifier != option_id and (slot_id, identifier) in snapshot.option_regions:
        raise ValueError("같은 항목에 해당 선택 식별자가 이미 있습니다.")
    previous = next(option for slot in snapshot.slots if slot.id == slot_id
                    for option in slot.options if option.id == option_id)
    return serialize_slot_option_metatag(SlotOption(identifier, previous.order,
                                                    previous.label if "label" not in command else label))


def _replace_region_metadata(root, region, payload, kind, slot_id, identifier) -> None:
    begin = _region_bookmark_begin(root, region)
    _product_metatag(begin).text = payload
    begin.set("name", structure_region_name(identifier if kind == PLACEMENT_SLOT else str(slot_id),
                                            identifier if kind == PLACEMENT_OPTION else None))


def _region_bookmark_begin(root, region):
    begins = [node for node in root.iter(f"{_HP}fieldBegin")
              if node.get("id") == region._pairing_id and node.get("type") == "BOOKMARK"]
    assert len(begins) == 1
    return begins[0]


def _product_metatag(begin):
    tags = [node for node in begin if node.tag == f"{_HP}metaTag"]
    product = [node for node in tags if isinstance(node.text, str)
               and _is_product_tag(node.text)]
    if len(product) != 1:
        raise ValueError("템플릿 메타데이터를 하나로 확정할 수 없습니다.")
    return product[0]


def _rename_child_bookmarks(root, previous_slot, slot_id, identifier) -> None:
    for option in previous_slot.options:
        old_name = structure_region_name(str(slot_id), option.id)
        option_begins = [node for node in root.iter(f"{_HP}fieldBegin")
                         if node.get("type") == "BOOKMARK" and node.get("name") == old_name]
        if len(option_begins) != 1:
            raise ValueError("하위 선택 책갈피를 하나로 확정할 수 없습니다.")
        option_begins[0].set("name", structure_region_name(identifier, option.id))


def _is_product_tag(raw: str) -> bool:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and "hwpxFiller" in payload


def _region_kind(command: Mapping[str, object]) -> object:
    """영역 명령이 가리키는 요소의 저작 어휘 ``kind`` — 명시가 없으면 항목이다(L-5: 기본값은 이 한 곳)."""
    return command.get("kind", PLACEMENT_SLOT)


def _adjust_region(package, command: Mapping[str, object]) -> None:
    snapshot, kind, slot_id, region = _adjust_target(package, command)
    start, end, root, paragraphs, owner = _adjust_bounds(package, command, snapshot, kind, slot_id, region)
    begin_ctrl, end_ctrl = _detach_region_controls(root, region)
    start_runs = [node for node in paragraphs[start] if node.tag == f"{_HP}run"]
    end_runs = [node for node in paragraphs[end] if node.tag == f"{_HP}run"]
    if not start_runs or not end_runs:
        raise ValueError("경계 문단에 편집 가능한 텍스트 런이 없습니다.")
    _place_region_begin(root, start_runs, start, kind, owner, begin_ctrl)
    _place_region_end(root, end_runs, end, kind, owner, end_ctrl)
    package.entries[region.section] = serialize_modified_section(root)
    resolve_bookmark_topology(package)


def _adjust_target(package, command):
    snapshot = inspect_slot_regions(package)
    if snapshot.diagnostics:
        raise ValueError("문서 구조 오류를 먼저 수정하세요.")
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
        raise ValueError("항목이나 선택 영역을 찾을 수 없습니다.")
    return snapshot, kind, slot_id, region


def _adjust_bounds(package, command, snapshot, kind, slot_id, region):
    start, end = command.get("start_paragraph"), command.get("end_paragraph")
    if not isinstance(start, int) or not isinstance(end, int) or start > end:
        raise ValueError("문단 범위를 정확히 고르세요.")
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    root = etree.fromstring(package.entries[region.section], parser=parser)
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    if start < 0 or end >= len(paragraphs):
        raise ValueError("고른 문단 범위가 문서 영역 밖에 있습니다.")
    owner = _adjust_owner(snapshot, kind, slot_id, start, end)
    return start, end, root, paragraphs, owner


def _adjust_owner(snapshot, kind, slot_id, start, end):
    if kind == PLACEMENT_OPTION:
        owner = snapshot.slot_regions[slot_id]
        if not owner.start_paragraph <= start <= end <= owner.end_paragraph:
            raise ValueError("고른 범위는 상위 항목 안에 있어야 합니다.")
        return owner
    children = [item for (owner_id, _), item in snapshot.option_regions.items()
                if owner_id == slot_id]
    if any(not start <= item.start_paragraph <= item.end_paragraph <= end
           for item in children):
        raise ValueError("조정한 항목 범위에서 하위 선택이 벗어납니다.")
    return None


def _detach_region_controls(root, region):
    begin = [node for node in root.iter(f"{_HP}fieldBegin")
             if node.get("id") == region._pairing_id and node.get("type") == "BOOKMARK"]
    finish = [node for node in root.iter(f"{_HP}fieldEnd")
              if node.get("beginIDRef") == region._pairing_id]
    assert len(begin) == 1 and len(finish) == 1
    begin_ctrl, end_ctrl = begin[0].getparent(), finish[0].getparent()
    assert begin_ctrl is not None and end_ctrl is not None
    begin_ctrl.getparent().remove(begin_ctrl)
    end_ctrl.getparent().remove(end_ctrl)
    return begin_ctrl, end_ctrl


def _place_region_begin(root, start_runs, start, kind, owner, begin_ctrl) -> None:
    if kind == PLACEMENT_OPTION and start == owner.start_paragraph:
        parent_begin = next(node for node in root.iter(f"{_HP}fieldBegin")
                            if node.get("id") == owner._pairing_id)
        parent_ctrl = parent_begin.getparent()
        assert parent_ctrl is not None
        parent_ctrl.getparent().insert(parent_ctrl.getparent().index(parent_ctrl) + 1, begin_ctrl)
    else:
        start_runs[0].insert(0, begin_ctrl)


def _place_region_end(root, end_runs, end, kind, owner, end_ctrl) -> None:
    if kind == PLACEMENT_OPTION and end == owner.end_paragraph:
        parent_end = next(node for node in root.iter(f"{_HP}fieldEnd")
                          if node.get("beginIDRef") == owner._pairing_id)
        parent_ctrl = parent_end.getparent()
        assert parent_ctrl is not None
        parent_ctrl.getparent().insert(parent_ctrl.getparent().index(parent_ctrl), end_ctrl)
    else:
        end_runs[-1].append(end_ctrl)


def _create_region(package, command: Mapping[str, object]) -> None:
    _require_clean(package)
    kind = PLACEMENT_OPTION if command["type"] == "create_option" else PLACEMENT_SLOT
    identifier, label = _creation_identity(command)
    entry = command.get("entry")
    start, end = command.get("start_paragraph"), command.get("end_paragraph")
    if command.get("cell_path") is not None:
        # 셀 문단 번호를 본문 문단 번호로 읽으면 엉뚱한 문단을 감싼다 — 판정(가용성)과 같은 거절이다.
        raise ValueError(REASON_REGION_IN_CELL)
    if not isinstance(entry, str) or not isinstance(start, int) or not isinstance(end, int):
        raise ValueError("문단 범위를 정확히 고르세요.")
    snapshot = inspect_slot_regions(package)
    parent, payload, region_name = _creation_metadata(snapshot, kind, identifier, label, command)
    region = create_bookmark_region(package, entry, start, end, name=region_name, parent=parent)
    append_bookmark_metatag(package, region, payload)


def _creation_identity(command):
    identifier = command.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise InvalidName("identifier", REASON_NEED_IDENTIFIER)
    label = command.get("label")
    if label is not None and not isinstance(label, str):
        raise ValueError("표시 이름은 텍스트여야 합니다.")
    return identifier, label


def _creation_metadata(snapshot, kind, identifier, label, command):
    owner = command.get("slot_id")
    if kind == PLACEMENT_SLOT:
        if identifier in snapshot.slot_regions:
            raise ValueError("항목 식별자가 이미 있습니다.")
        return None, serialize_slot_metatag(Slot(identifier, (), label)), structure_region_name(identifier)
    if not isinstance(owner, str) or owner not in snapshot.slot_regions:
        raise ValueError("선택을 만들 상위 항목이 필요합니다.")
    if (owner, identifier) in snapshot.option_regions:
        raise ValueError("같은 항목에 해당 선택 식별자가 이미 있습니다.")
    parent = snapshot.slot_regions[owner]
    order = len(next(slot.options for slot in snapshot.slots if slot.id == owner))
    payload = serialize_slot_option_metatag(SlotOption(identifier, order, label))
    return parent, payload, structure_region_name(owner, identifier)


adjust_region = _adjust_region
create_region = _create_region
is_product_tag = _is_product_tag
region_kind = _region_kind
rename_region = _rename_region
