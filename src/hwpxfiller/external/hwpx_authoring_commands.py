"""Native HWPX authoring: commands responsibilities."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping


from hwpxcore.bookmark_region import (
    unwrap_bookmark_region,
)
from hwpxcore.text_extract import HP_NS, require_package

from ..domain.structure_scan import PLACEMENT_OPTION, PLACEMENT_SLOT, normalize_field_id
from ..domain.template_authoring import (
    COMPILE_TOKEN,
    REVERT_TEMPLATE,
    CascadeRequired,
    command_label,
    field_candidates,
    revert_template_message,
    whole_field_unset,
)
from .hwpx_product_inspection import (
    inspect_slot_regions,
)
from .hwpx_structure_ops import (
    remove_slot,
    remove_slot_option,
)

_HP = f"{{{HP_NS}}}"
from .hwpx_authoring_analysis import (
    fields as _fields,
    analyze_hwpx,
)
from .hwpx_authoring_fields import (
    change_field as _change_field,
    compile_token as _compile_token,
    create_field as _create_field,
    field_site_contexts as _field_site_contexts,
    revert_template as _revert_template,
)
from .hwpx_authoring_regions import (
    adjust_region as _adjust_region,
    create_region as _create_region,
    region_kind as _region_kind,
    rename_region as _rename_region,
)
from .hwpx_authoring_region_blocks import (
    duplicate_region as _duplicate_region,
    move_region as _move_region,
)
from .hwpx_authoring_preview import (
    command_preview_label as _command_preview_label,
    preview_content_context as _preview_content_context,
    region_display_name as _region_display_name,
    snapshot as _snapshot,
)

def apply_hwpx(content: object, command: Mapping[str, object]) -> tuple[object, dict]:
    """Mutate an opened disposable package atomically; return an impact projection."""
    return _execute(require_package(content), command, projecting=False)


def _unwrap_slot_options(package, slot_id: str) -> None:
    """Unwrap every option of ``slot_id`` innermost-first, re-reading regions after each step."""
    while True:
        snapshot = inspect_slot_regions(package)
        remaining = sorted((region for (owner, _), region in snapshot.option_regions.items()
                            if owner == slot_id), key=lambda region: -region.start_paragraph)
        if not remaining:
            return
        unwrap_bookmark_region(package, remaining[0])


def _prior_field_name(fields: list[dict], command: Mapping[str, object]) -> str | None:
    return next((field["name"] for field in fields for occurrence in field["occurrences"]
                 if occurrence["entry"] == command.get("entry")
                 and occurrence["occurrence"] == command.get("occurrence")), None)


def _execute(package, command: Mapping[str, object], *, projecting: bool) -> tuple[object, dict]:
    before = dict(package.entries)
    action = command.get("type")
    before_label = _command_preview_label(command)
    impact_context = _preview_content_context(package, command)
    prior_fields = _fields(package) if action in {"create_field", "rename_field", "relink_field",
                                                   "unset_field"} else []
    label = command_label(command, impact_context.get("target_name"))
    if action in {"rename_slot", "rename_option"}:
        label = command_label(command, _region_display_name(
            inspect_slot_regions(package), str(command.get("slot_id")),
            command.get("option_id") if action == "rename_option" else None))
    try:
        captured, label, impact_context, extra, requires_cascade = _dispatch_command(
            package, command, action, projecting, prior_fields, label, impact_context)
        result = analyze_hwpx(package)
        if result["diagnostics"] and not analyze_hwpx(_snapshot(before))["diagnostics"]:
            raise ValueError("명령을 적용하면 문서 구조가 깨집니다.")
        return package, _impact(package, before, command, captured, before_label, label,
                                impact_context, result, requires_cascade, extra)
    except Exception as exc:
        package.entries.clear()
        package.entries.update(before)
        if isinstance(exc, ValueError) and not re.search("[가-힣]", str(exc)):
            raise ValueError("이 문서의 구조나 고른 범위 때문에 명령을 적용할 수 없습니다.") from exc
        raise



def _dispatch_command(package, command, action, projecting, prior_fields, label, impact_context):
    if action == "create_field":
        return _create_field_command(package, command, prior_fields, label, impact_context)
    if action in {"rename_field", "relink_field", "unset_field"}:
        return _change_field_command(package, command, action, prior_fields, impact_context)
    if action == COMPILE_TOKEN:
        return _compile_token(package, command), label, impact_context, {}, False
    if action == REVERT_TEMPLATE:
        captured = _revert_template(package)
        # 파괴 확인(button)의 본문 — 손실 집합(ui-style: 제목=행동, 본문=결과·손실 집합).
        return captured, label, impact_context, {"message": revert_template_message(captured)}, False
    if action in {"create_slot", "create_option", "rename_slot", "rename_option",
                  "adjust_range", "move", "duplicate"}:
        _region_command(package, command, action)
        return None, label, impact_context, {}, False
    if action in {"unwrap", "delete"}:
        cascade = _remove_region(package, command, action, projecting, impact_context)
        return None, label, impact_context, {}, cascade
    raise ValueError(f"지원하지 않는 HWPX 저작 명령입니다: {action!r}")


def _create_field_command(package, command, prior_fields, label, impact_context):
    sites = _field_site_contexts(package, command) if command.get("ranges") is not None else None
    captured = _create_field(package, command)
    existing = next((item["count"] for item in prior_fields
                     if item["name"] == normalize_field_id(command.get("name"))), 0)
    extra = {"links_existing": existing > 0, "existing_count": existing,
             "candidates": field_candidates(prior_fields)}
    if sites is not None:
        # 같은 문구 N곳(P-07): 포함될 자리마다 검색 결과와 같은 문맥 한 줄, 영향은 자리 수다.
        impact_context = {**impact_context, "included": sites}
        extra["affected"] = len(sites)
    return captured, label, impact_context, extra, False


def _change_field_command(package, command, action, prior_fields, impact_context):
    captured = _change_field(package, command)
    whole = whole_field_unset(command)
    label = command_label(command, command.get("old_name") if action == "rename_field" or whole
                          else _prior_field_name(prior_fields, command))
    if whole:
        # 필드 전체 해제의 포함 내용은 모든 사용 위치의 문맥이다(P-20) — 구조 목록의 사용 위치 행과 같다.
        name = normalize_field_id(command.get("old_name"))
        impact_context = {**impact_context, "included": [
            occurrence["context"] for field in prior_fields if field["name"] == name
            for occurrence in field["occurrences"]]}
    return captured, label, impact_context, {}, False


def _region_command(package, command, action) -> None:
    if action in {"create_slot", "create_option"}:
        _create_region(package, command)
    elif action in {"rename_slot", "rename_option"}:
        _rename_region(package, command)
    elif action == "adjust_range":
        _adjust_region(package, command)
    elif action == "move":
        _move_region(package, command)
    else:
        _duplicate_region(package, command)


def _remove_region(package, command, action, projecting, impact_context) -> bool:
    kind = _region_kind(command)
    slot_id = str(command.get("slot_id"))
    option_id = command.get("option_id")
    if action == "delete":
        if kind == PLACEMENT_OPTION:
            remove_slot_option(package, slot_id, str(option_id))
        else:
            remove_slot(package, slot_id)
        return False
    return _unwrap_region(package, command, kind, slot_id, option_id, projecting, impact_context)


def _unwrap_region(package, command, kind, slot_id, option_id, projecting, impact_context) -> bool:
    snapshot = inspect_slot_regions(package)
    if snapshot.diagnostics:
        raise ValueError("문서 구조 오류를 먼저 수정하세요.")
    region = (snapshot.option_regions.get((slot_id, str(option_id))) if kind == PLACEMENT_OPTION
              else snapshot.slot_regions.get(slot_id))
    if region is None:
        raise ValueError("항목이나 선택 영역을 찾을 수 없습니다.")
    requires_cascade = _cascade_required(snapshot, command, kind, slot_id, projecting, impact_context)
    if kind == PLACEMENT_SLOT and any(slot.options for slot in snapshot.slots if slot.id == slot_id):
        _unwrap_slot_options(package, slot_id)
        region = inspect_slot_regions(package).slot_regions[slot_id]
    unwrap_bookmark_region(package, region)
    return requires_cascade


def _cascade_required(snapshot, command, kind, slot_id, projecting, impact_context) -> bool:
    if kind != PLACEMENT_SLOT or not any(slot.options for slot in snapshot.slots if slot.id == slot_id):
        return False
    if command.get("cascade"):
        return False
    if not projecting:
        raise CascadeRequired([child for child in impact_context.get("children", [])
                               if child["kind"] == PLACEMENT_OPTION])
    return True


def _impact(package, before, command, captured, before_label, label, impact_context, result,
            requires_cascade, extra) -> dict:
    changed = [entry for entry in package.entries if package.entries[entry] != before.get(entry)]
    after_label = _command_preview_label(command, after=True, captured=captured)
    before_text = impact_context.get("before")
    after_text = impact_context.get("after")
    captured_text = captured if isinstance(captured, str) else None
    return {"changed_entries": changed,
            "affected": captured if isinstance(captured, int) else len(changed),
            "result": result,
            "captured_text": captured_text, "original": captured_text,
            "before": (before_text if before_text is not None
                       else captured_text if captured_text is not None else before_label),
            "after": after_text if after_text is not None else after_label,
            "included": impact_context.get("included"),
            "included_location": impact_context.get("included_location"),
            "expanded": impact_context.get("expanded", False),
            "children": impact_context.get("children", []),
            "counts": impact_context.get("counts"),
            "label": label, "requires_cascade": requires_cascade, **extra}

def preview_hwpx(content: object, command: Mapping[str, object]) -> dict:
    """Project a command on a throwaway copy; an unconfirmed cascade is flagged, not refused."""
    disposable = copy.deepcopy(require_package(content))
    _, impact = _execute(disposable, command, projecting=True)
    return impact
