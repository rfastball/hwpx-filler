"""TXT authoring edit plans, grouped by the command's target."""

from __future__ import annotations

from collections.abc import Mapping

from .authoring import begin_marker_text as _marker
from .authoring import end_marker_text as _end_marker
from .structure_scan import PLACEMENT_OPTION, PLACEMENT_SLOT
from .text_render import iter_field_token_matches
from .text_structure import scan_text_structure
from .template_authoring_primitives import (
    FIELD_COMMANDS,
    REASON_FIELD_OVERLAP,
    REASON_REGION_OVERLAP,
    REASON_STRUCTURE_FIRST,
    NameConflict,
    field_identifier as _identifier,
    field_spans as _field_spans,
    from_utf16 as _from_utf16,
    line_range as _line_range,
    line_starts as _line_starts,
    preferred_eol as _eol,
    region_identifier,
    target_placement as _target,
    validate_region_label as _region_label,
    whole_field_unset,
)

type Edit = tuple[int, int, str]
type EditPlan = tuple[list[Edit], bool, bool]
_FIELD_NOT_FOUND = "필드를 찾을 수 없습니다."


def _create_field(text: str, command: Mapping[str, object], start: int, end: int, matches) -> EditPlan:
    name = _identifier(command.get("name"))
    spans = _field_spans(text, command, start, end)
    if any(match.start() < hi and lo < match.end() for lo, hi in spans for match in matches):
        raise ValueError(REASON_FIELD_OVERLAP)
    return [(lo, hi, "{{" + name + "}}") for lo, hi in spans], False, False


def _rename_field(command: Mapping[str, object], matches) -> EditPlan:
    old = _identifier(command.get("old_name"))
    new = _identifier(command.get("name"))
    existing = [match for match in matches if match.group(1).strip() == old]
    if not existing:
        raise ValueError(_FIELD_NOT_FOUND)
    if old == new:
        return [], False, False
    taken = [match for match in matches if match.group(1).strip() == new]
    if taken:
        raise NameConflict(new, len(taken))
    return [(match.start(), match.end(), "{{" + new + "}}") for match in existing], False, False


def _replace_field(command: Mapping[str, object], start: int, matches) -> EditPlan:
    replacement = ("{{" + _identifier(command.get("name")) + "}}") if command.get("type") == "relink_field" else command.get("text")
    sites = _field_sites(command, start, matches)
    if not isinstance(replacement, str):
        raise ValueError("의미를 해제한 뒤 남길 본문을 입력하세요.")
    return [(match.start(), match.end(), replacement) for match in sites], False, False


def _field_sites(command: Mapping[str, object], start: int, matches):
    if whole_field_unset(command):
        # 필드 전체의 의미 해제(P-20): 이름이 같은 모든 사용 위치를 한 계획으로 치환한다.
        name = _identifier(command.get("old_name"))
        sites = [match for match in matches if match.group(1).strip() == name]
        if not sites:
            raise ValueError(_FIELD_NOT_FOUND)
    else:
        match = next((item for item in matches if item.start() <= start < item.end()), None)
        if match is None:
            raise ValueError("고른 필드 사용 위치를 찾을 수 없습니다.")
        sites = [match]
    return sites


def _validate_option_placement(command: Mapping[str, object], scan, first: int, last: int) -> None:
    owners = [place for place in scan.placements if place.kind == PLACEMENT_SLOT
              and place.begin_marker_line < first <= last < place.end_marker_line]
    if len(owners) != 1 or owners[0].slot_id != command.get("slot_id"):
        raise ValueError("고른 범위는 하나의 항목 안에 있어야 합니다.")
    if any(option.id == command.get("id") for slot in scan.slots
           if slot.id == owners[0].slot_id for option in slot.options):
        raise ValueError("같은 항목에 해당 선택 식별자가 이미 있습니다.")


def _region_marker_edits(text: str, command: Mapping[str, object], kind: str,
                         lo: int, hi: int) -> list[Edit]:
    eol = _eol(text)
    opening = _marker(kind, command.get("id"), command.get("label")) + eol
    if hi == len(text) and not text.endswith(("\r", "\n")):
        return [(lo, lo, opening), (hi, hi, eol + _end_marker(kind))]
    return [(lo, lo, opening), (hi, hi, _end_marker(kind) + eol)]


def _create_region(text: str, command: Mapping[str, object], scan, start: int, end: int) -> EditPlan:
    kind = PLACEMENT_SLOT if command.get("type") == "create_slot" else PLACEMENT_OPTION
    region_identifier(command.get("id"))
    _region_label(command.get("label"))
    first, last, lo, hi = _line_range(text, start, end)
    expanded = lo != start or hi != end
    if any(place.begin_marker_line <= last and first <= place.end_marker_line
           for place in scan.placements if place.kind == kind):
        raise ValueError(REASON_REGION_OVERLAP)
    if kind == PLACEMENT_OPTION:
        _validate_option_placement(command, scan, first, last)
    elif any(slot.id == command.get("id") for slot in scan.slots):
        raise ValueError("항목 식별자가 이미 있습니다.")
    return _region_marker_edits(text, command, kind, lo, hi), expanded, False


def _validate_region_name(command: Mapping[str, object], scan, target, new_id: object) -> None:
    if target.kind == "slot":
        if any(slot.id == new_id and slot.id != target.slot_id for slot in scan.slots):
            raise ValueError("항목 식별자가 이미 있습니다.")
    elif any(opt.id == new_id and opt.id != target.option_id
             for slot in scan.slots if slot.id == target.slot_id for opt in slot.options):
        raise ValueError("같은 항목에 해당 선택 식별자가 이미 있습니다.")


def _existing_region(scan, target):
    return next(
        (slot if target.kind == "slot" else option
         for slot in scan.slots if slot.id == target.slot_id
         for option in (slot.options if target.kind == "option" else (slot,))
         if target.kind == "slot" or option.id == target.option_id),
        None,
    )


def _rename_region(text: str, command: Mapping[str, object], scan, target, starts: list[int]) -> EditPlan:
    current_id = target.option_id if target.kind == "option" else target.slot_id
    new_id = command.get("id", current_id)
    if new_id != current_id:
        region_identifier(new_id, renaming=True)
    _region_label(command.get("label"))
    _validate_region_name(command, scan, target, new_id)
    existing = _existing_region(scan, target)
    label = command.get("label", existing.label if existing else None)
    replacement = _marker(target.kind, new_id, label)
    begin = target.begin_marker_line
    return [(starts[begin], starts[begin + 1], replacement + _eol(text))], False, False


def _unwrap(command: Mapping[str, object], scan, target, starts: list[int]) -> EditPlan:
    begin, finish = target.begin_marker_line, target.end_marker_line
    child_options = [place for place in scan.placements if place.kind == "option"
                     and place.slot_id == target.slot_id]
    requires_cascade = target.kind == "slot" and bool(child_options) and not command.get("cascade")
    child_lines = {begin, finish}
    if target.kind == "slot":
        child_lines |= {line for place in child_options
                        for line in (place.begin_marker_line, place.end_marker_line)}
    return [(starts[line], starts[line + 1], "") for line in sorted(child_lines)], False, requires_cascade


def _move_or_duplicate(text: str, command: Mapping[str, object], target, starts: list[int]) -> EditPlan:
    begin, finish = target.begin_marker_line, target.end_marker_line
    lo, hi = starts[begin], starts[finish + 1]
    destination = _from_utf16(text, command.get("destination", hi))
    if destination not in starts:
        raise ValueError("옮기거나 복제할 위치는 줄 경계여야 합니다.")
    if command.get("type") == "move":
        if lo <= destination <= hi:
            raise ValueError("영역을 자기 안으로 옮길 수 없습니다.")
        return [(lo, hi, ""), (destination, destination, text[lo:hi])], False, False
    new_id = command.get("new_id")
    if not new_id:
        raise ValueError("복제할 영역의 새 식별자를 입력하세요.")
    copied = text[lo:hi]
    old_marker = text[starts[begin]:starts[begin + 1]].strip()
    copied = copied.replace(old_marker, _marker(target.kind, new_id, command.get("label")), 1)
    return [(destination, destination, copied)], False, False


def _block_edit(text: str, command: Mapping[str, object], scan, target,
                starts: list[int]) -> EditPlan:
    action = command.get("type")
    if action == "delete":
        return [(starts[target.begin_marker_line], starts[target.end_marker_line + 1], "")], False, False
    if action == "unwrap":
        return _unwrap(command, scan, target, starts)
    return _move_or_duplicate(text, command, target, starts)


def _adjust_range(text: str, start: int, end: int, target, starts: list[int]) -> EditPlan:
    first, last, _, _ = _line_range(text, start, end)
    if first > last:
        raise ValueError("조정한 범위에 본문이 없습니다.")
    begin, finish = target.begin_marker_line, target.end_marker_line
    begin_text = text[starts[begin]:starts[begin + 1]]
    end_text = text[starts[finish]:starts[finish + 1]]
    return [(starts[begin], starts[begin + 1], ""),
            (starts[finish], starts[finish + 1], ""),
            (starts[first], starts[first], begin_text),
            (starts[last + 1], starts[last + 1], end_text)], True, False


def _field_edits(text: str, command: Mapping[str, object], action: object,
                 start: int, end: int, matches) -> EditPlan:
    if action == "create_field":
        return _create_field(text, command, start, end, matches)
    if action == "rename_field":
        return _rename_field(command, matches)
    return _replace_field(command, start, matches)


def _selection_offsets(text: str, command: Mapping[str, object]) -> tuple[int, int]:
    start = _from_utf16(text, command.get("start", 0))
    end = _from_utf16(text, command.get("end", command.get("start", 0)))
    if start > end:
        raise ValueError("고른 범위의 시작과 끝이 뒤바뀌었습니다.")
    return start, end


def edits(text: str, command: Mapping[str, object]) -> EditPlan:
    """Edit plan, whether the range expanded, and whether a cascade is still unconfirmed."""
    action = command.get("type")
    scan = scan_text_structure(text)
    if scan.diagnostics and action not in FIELD_COMMANDS:
        raise ValueError(REASON_STRUCTURE_FIRST)
    matches = list(iter_field_token_matches(text))
    starts = _line_starts(text)
    start, end = _selection_offsets(text, command)
    if action in FIELD_COMMANDS:
        return _field_edits(text, command, action, start, end, matches)
    if action in {"create_slot", "create_option"}:
        return _create_region(text, command, scan, start, end)
    target = _target(scan, command)
    if target is None:
        raise ValueError("항목이나 선택 영역을 찾을 수 없습니다.")
    if action in {"rename_slot", "rename_option"}:
        return _rename_region(text, command, scan, target, starts)
    if action in {"unwrap", "delete", "duplicate", "move"}:
        return _block_edit(text, command, scan, target, starts)
    if action == "adjust_range":
        return _adjust_range(text, start, end, target, starts)
    raise ValueError(f"알 수 없는 저작 명령입니다: {action!r}")
