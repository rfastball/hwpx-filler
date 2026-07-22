"""WebView dispatch contract: screen/action allow-list and payload-key schemas.

The browser bridge is an untyped boundary.  Keep its complete vocabulary here so
that a caller cannot accidentally reach an arbitrary ``_do_*`` method and a
misspelled/stale payload cannot be ignored silently by ``dict.get``.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class PayloadSchema:
    """Allowed keys for one action; values remain domain-controller owned."""

    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()

    @property
    def allowed(self) -> frozenset[str]:
        return self.required | self.optional


def _schema(required: str = "", optional: str = "") -> PayloadSchema:
    return PayloadSchema(frozenset(required.split()), frozenset(optional.split()))


_DATA_ZONE = {
    "toggle_record": _schema("index value"),
    "select_range": _schema("indices value"),
    "set_all": _schema(),
    "set_none": _schema(),
    "filter_search": _schema(optional="text"),
    "filter_col_text": _schema("column", "text"),
    "filter_col_values": _schema("column", "values"),
    "filter_col_range": _schema("column", "first second joiner"),
    "filter_prune": _schema("column"),
    "filter_clear": _schema(),
    "filter_clear_col": _schema("column"),
    "filter_panel": _schema("column"),
    "filter_reapply": _schema(),
}

_POOL_TARGETING = {
    "pool_sources": _schema(),
    "load_pool": _schema("name"),
}

_DRAFT_SESSION = {
    "fork_to_volatile": _schema(optional="confirm"),
    "leave_for_template_guard": _schema(),
    "select_template": _schema("name", "confirm"),
    "new_draft": _schema(),
    "copy_precheck": _schema(),
    "set_template_text": _schema("text"),
    "edit_source": _schema("text"),
    "set_source": _schema("name", "col confirm"),
    "set_map_value": _schema("name", "text"),
    "set_map_fmt": _schema("name", "code"),
    "set_map_type": _schema("name type"),
    "set_confirmed": _schema("name", "value"),
    "revert_map": _schema("name"),
    "step": _schema("delta"),
    "set_current": _schema(optional="index"),
    "toggle_advance": _schema("value"),
    "set_target_font": _schema("font"),
    "set_fullwidth": _schema("value"),
    "clear_data": _schema(),
    "guard_state": _schema(),
    "leave_guard": _schema(),
}

_REGISTRY: dict[str, dict[str, PayloadSchema]] = {
    "home": {
        "set_group_by": _schema(optional="axis"),
        "toggle_facet": _schema("axis value"),
        "clear_facets": _schema(),
        "delete_job": _schema("name"),
        "clone_job": _schema("name"),
        "relink_template": _schema("name", "path confirm"),
        "refresh": _schema(),
        "set_tags": _schema("name", "tags"),
        "delete_corrupt": _schema("path", "confirm"),
    },
    "editor": {
        "use_library_template": _schema("path"),
        "toggle_library_group": _schema("group"),
        "new_session": _schema(),
        "discard_session": _schema(),
        "goto_step": _schema("step"),
        "ack_gate": _schema(),
        "skip_data": _schema(),
        "use_all_headers": _schema(),
        "use_none": _schema(),
        "toggle_source_active": _schema("field"),
        "mapping_reset_stakes": _schema(),
        "set_source": _schema("index source"),
        "revert_source": _schema("index"),
        "set_type": _schema("index type"),
        "set_fmt": _schema("index fmt"),
        "set_const": _schema("index const"),
        "set_confirmed": _schema("index confirmed"),
        "confirm_all": _schema(),
        "confirm_blanks": _schema(optional="fields"),
        "unconfirm_all": _schema(),
        "step_preview": _schema("delta"),
        "set_name": _schema("name"),
        "set_pattern": _schema("pattern"),
        "set_dataset_name": _schema("name"),
        "save": _schema(optional="confirm_dataset confirm_overwrite confirmed_overwrite_text"),
    },
    "job": {
        **_DATA_ZONE,
        **_POOL_TARGETING,
        "guard_state": _schema(),
        "refresh": _schema(),
        "select_job": _schema("name", "confirm"),
        "relink_template": _schema("name", "path confirm"),
        "toggle_group": _schema("group"),
        "rename_job": _schema("name", "new"),
        "clone_job": _schema("name"),
        "delete_job": _schema("name", "confirm"),
        "set_group": _schema("name", "group"),
        "rename_group": _schema("name", "new confirm seen"),
        "disband_group": _schema("name", "confirm seen"),
        "ack_field": _schema("field"),
        "unack_field": _schema("field"),
    },
    "draft": {
        **_DATA_ZONE,
        **_POOL_TARGETING,
        **_DRAFT_SESSION,
        "refresh": _schema(),
        "select_job": _schema("name", "confirm"),
        "save_job": _schema("name", "confirm confirmed_text"),
        "promote_info": _schema(),
        "save_template": _schema("name", "group confirm confirmed_text"),
        "toggle_group": _schema("group"),
        "rename_job": _schema("name", "new"),
        "clone_job": _schema("name"),
        "delete_job": _schema("name", "confirm"),
        "set_group": _schema("name", "group"),
        "rename_group": _schema("name", "new confirm seen"),
        "disband_group": _schema("name", "confirm seen"),
    },
    "pool": {
        "refresh": _schema(),
        "archive": _schema("name"),
        "activate": _schema("name"),
        "delete": _schema("name", "confirm"),
        "register_excel": _schema("name path", "sheet note confirm"),
    },
    "tpl": {
        "refresh": _schema(),
        "compile": _schema("path", "confirm"),
        "review": _schema("path"),
        "set_group": _schema("media key", "group"),
        "toggle_group": _schema("media group"),
        "rename_group": _schema("media group", "new confirm"),
        "disband_group": _schema("media group", "confirm"),
        "delete": _schema("media path", "confirm"),
        "txt_new": _schema("name content"),
        "txt_edit": _schema("path content"),
        "txt_content": _schema("path"),
    },
}

ACTION_REGISTRY: Mapping[str, Mapping[str, PayloadSchema]] = MappingProxyType(
    {screen: MappingProxyType(actions) for screen, actions in _REGISTRY.items()}
)


def validate_dispatch(screen: str, action: str, payload: object) -> dict:
    """Validate one browser dispatch and return the original payload as a dict."""

    actions = ACTION_REGISTRY.get(screen)
    if actions is None:
        raise ValueError(f"등록되지 않은 화면: {screen!r}")
    schema = actions.get(action)
    if schema is None:
        raise ValueError(f"등록되지 않은 {screen!r} 액션: {action!r}")
    if not isinstance(payload, dict):
        raise ValueError(
            f"{screen!r}/{action!r} payload는 객체여야 합니다: {type(payload).__name__}"
        )
    keys = set(payload)
    missing = schema.required - keys
    unexpected = keys - schema.allowed
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"필수 키 누락={sorted(missing)!r}")
        if unexpected:
            details.append(f"미등록 키={sorted(unexpected)!r}")
        raise ValueError(f"{screen!r}/{action!r} payload 스키마 불일치: " + ", ".join(details))
    return payload
