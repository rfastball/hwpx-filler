"""Native HWPX authoring: preview responsibilities."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

import lxml.etree as etree  # pyright: ignore[reportMissingImports]

from hwpxcore.text_extract import HP_NS

from ..domain.structure_scan import PLACEMENT_OPTION
from ..domain.template_authoring import (
    COMPILE_TOKEN,
    REVERT_TEMPLATE,
)
from .hwpx_product_inspection import (
    inspect_slot_regions,
)

_HP = f"{{{HP_NS}}}"
from .hwpx_authoring_analysis import (
    fields as _fields,
)
from .hwpx_authoring_regions import (
    region_kind as _region_kind,
)

def _command_preview_label(command: Mapping[str, object], *, after: bool = False,
                           captured: object = None) -> str:
    action = command.get("type")
    field_label = _field_preview_label(command, action, after, captured)
    if field_label is not None:
        return field_label
    region_label = _region_preview_label(command, action, after)
    if region_label is not None:
        return region_label
    if action == REVERT_TEMPLATE:
        # 되돌리기는 문서 전체의 값이다 — 한 줄 전후 표지가 없고 손실 집합(message)이 영향이다.
        return ""
    return str(command.get("type", ""))


def _field_preview_label(command: Mapping[str, object], action: object,
                         after: bool, captured: object) -> str | None:
    if action in {"create_field", COMPILE_TOKEN}:
        return f"[ {command.get('name', '')} ]" if after else str(captured or "")
    if action in {"rename_field", "relink_field"}:
        return str(command.get("name" if after else "old_name", ""))
    if action == "unset_field":
        return str(command.get("text", "")) if after else f"[ {command.get('old_name', '')} ]"
    return None


def _region_preview_label(command: Mapping[str, object], action: object, after: bool) -> str | None:
    if action in {"create_slot", "rename_slot", "create_option", "rename_option"}:
        noun = "항목" if str(action).endswith("slot") else "선택"
        return f"{noun} {command.get('id' if after else 'slot_id', '')}"
    if action == "delete":
        return "삭제됨" if after else "영역 내용과 의미"
    if action == "unwrap":
        return "본문 유지" if after else "의미 경계"
    return None


def _target_region(snapshot, slot_id: str, option_id: object, on_option: bool):
    return (snapshot.option_regions.get((slot_id, option_id))
            if isinstance(option_id, str) and on_option
            else snapshot.slot_regions.get(slot_id))


def _preview_range(snapshot, command: Mapping[str, object], action: object,
                   slot_id: str, option_id: object, on_option: bool) -> tuple:
    if action in {"create_slot", "create_option", "adjust_range"}:
        entry = command.get("entry")
        start = command.get("start_paragraph")
        end = command.get("end_paragraph")
        if action != "adjust_range":
            return None, entry, start, end, None
        region = _target_region(snapshot, slot_id, option_id, on_option)
        target_name = _region_display_name(snapshot, slot_id, option_id if on_option else None)
        if region is not None and entry is None:
            entry = region.section
        return target_name, entry, start, end, region
    region = _target_region(snapshot, slot_id, option_id, on_option)
    target_name = _region_display_name(snapshot, slot_id, option_id if on_option else None)
    if region is None:
        return target_name, None, None, None, None
    return target_name, region.section, region.start_paragraph, region.end_paragraph, None


def _paragraph_text(paragraph) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{_HP}t"))


def _preview_paragraphs(package, entry: object, start: object, end: object) -> list | None:
    if not isinstance(entry, str) or entry not in package.entries or not isinstance(start, int) or not isinstance(end, int):
        return None
    root = etree.fromstring(package.entries[entry], parser=etree.XMLParser(resolve_entities=False))
    paragraphs = [node for node in root if node.tag == f"{_HP}p"]
    return paragraphs if 0 <= start <= end < len(paragraphs) else None


def _preview_expanded(command: Mapping[str, object], action: object, last_line: str) -> bool:
    start_offset, end_offset = command.get("start"), command.get("end")
    return (action in {"create_slot", "create_option"}
            and ((isinstance(start_offset, int) and start_offset > 0)
                 or (isinstance(end_offset, int) and end_offset < len(last_line))))


def _preview_details(package, snapshot, command: Mapping[str, object], action: object,
                     slot_id: str, option_id: object, on_option: bool, target_name: str | None,
                     entry: str, start: int, end: int, prior_region, paragraphs: list) -> dict:
    lines = [_paragraph_text(paragraph) for paragraph in paragraphs[start:end + 1]]
    included = "\n".join(lines)
    previous = ("\n".join(_paragraph_text(paragraph)
                          for paragraph in paragraphs[prior_region.start_paragraph:prior_region.end_paragraph + 1])
                if prior_region is not None else included)
    target_key = ((slot_id, option_id) if on_option
                  and action not in {"create_slot", "create_option"} else None)
    children, counts = _block_children(package, snapshot, entry, paragraphs, start, end, exclude=target_key)
    detail = (f"\n\n포함: 문단 {counts['paragraphs']}개 · 필드 {counts['fields']}곳 · "
              f"하위 영역 {counts['options']}곳")
    expanded = _preview_expanded(command, action, lines[-1])
    return {"before": previous + detail,
            "after": ("본문과 의미가 삭제됩니다." if action == "delete"
                      else included + "\n\n" + _command_preview_label(command, after=True)),
            "included": included[:500], "expanded": expanded,
            # 편집면이 미리보기 동안 칠할 실제 범위(P-16) — 넓힌 문단 전체 또는 대상 영역의 문단.
            "included_location": {"entry": entry, "start_paragraph": start, "end_paragraph": end},
            "children": children, "counts": counts, "target_name": target_name}


def _preview_content_context(package, command: Mapping[str, object]) -> dict:
    """Show the actual native paragraph body touched by a structure command."""
    action = command.get("type")
    if action not in {"create_slot", "create_option", "adjust_range", "unwrap", "delete", "duplicate", "move"}:
        return {}
    slot_id = str(command.get("slot_id") or "")
    on_option = _region_kind(command) == PLACEMENT_OPTION
    option_id = command.get("option_id")
    snapshot = inspect_slot_regions(package)
    target_name, entry, start, end, prior_region = _preview_range(
        snapshot, command, action, slot_id, option_id, on_option)
    paragraphs = _preview_paragraphs(package, entry, start, end)
    if paragraphs is None:
        return {"target_name": target_name}
    assert isinstance(entry, str) and isinstance(start, int) and isinstance(end, int)
    return _preview_details(package, snapshot, command, action, slot_id, option_id, on_option,
                            target_name, entry, start, end, prior_region, paragraphs)


def _region_display_name(snapshot, slot_id: str, option_id: object) -> str | None:
    slot = next((item for item in snapshot.slots if item.id == slot_id), None)
    if slot is None:
        return None
    if option_id is not None:
        option = next((item for item in slot.options if item.id == option_id), None)
        return (option.label or option.id) if option is not None else None
    return slot.label or slot.id


def _block_children(package, snapshot, entry: str, paragraphs: list, start: int, end: int,
                    *, exclude: tuple[str, object] | None = None) -> tuple[list[dict], dict]:
    """Options, field occurrences and tables inside paragraphs ``start..end`` of ``entry``.

    ``exclude`` names the option region being acted on so it is not listed as its own child.
    """
    children, options = _option_children(snapshot, entry, start, end, exclude)
    fields, grouped = _field_children(package, entry, start, end)
    children.extend(fields)
    tables = sum(1 for paragraph in paragraphs[start:end + 1] for _ in paragraph.iter(f"{_HP}tbl"))
    counts = {"paragraphs": end - start + 1, "fields": sum(grouped.values()),
              "options": len(options), "tables": tables}
    return children, counts


def _option_children(snapshot, entry: str, start: int, end: int,
                     exclude: tuple[str, object] | None) -> tuple[list[dict], list[tuple]]:
    children: list[dict] = []
    options = [(owner, option_id, region) for (owner, option_id), region in snapshot.option_regions.items()
               if region.section == entry and start <= region.start_paragraph and region.end_paragraph <= end
               and (owner, option_id) != exclude]
    for owner, option_id, region in options:
        children.append({"kind": PLACEMENT_OPTION, "id": option_id,
                         "label": _region_display_name(snapshot, owner, option_id) or option_id,
                         "count": region.end_paragraph - region.start_paragraph + 1})
    return children, options


def _field_children(package, entry: str, start: int, end: int) -> tuple[list[dict], dict[str, int]]:
    grouped: dict[str, int] = defaultdict(int)
    for field in _fields(package):
        for occurrence in field["occurrences"]:
            if (occurrence["entry"] == entry and isinstance(occurrence["paragraph"], int)
                    and start <= occurrence["paragraph"] <= end):
                grouped[field["name"]] += 1
    return ([{"kind": "field", "id": name, "label": name, "count": count}
             for name, count in grouped.items()], grouped)


def _snapshot(entries: dict[str, bytes]):
    from hwpxcore.package import HwpxPackage

    package = HwpxPackage()
    package.entries.update(entries)
    return package


command_preview_label = _command_preview_label
preview_content_context = _preview_content_context
region_display_name = _region_display_name
snapshot = _snapshot
