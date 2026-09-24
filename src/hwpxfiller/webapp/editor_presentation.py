"""Editor snapshot projections (pure, webview-free)."""

from __future__ import annotations

from datetime import datetime

from ..domain.output_name import format_seq_token
from ..viewmodel.mapping_state import NO_SOURCE_LABEL, SPECIAL_SOURCE_LABEL
from ..naming import make_output_filename, pattern_uses_seq, seq_token_pads


def data_column_options(source_fields: list[str]) -> list[dict]:
    options = [
        {"value": "", "label": NO_SOURCE_LABEL, "kind": "none", "field": ""},
    ]
    options.extend(
        {"value": f"col:{name}", "label": name, "kind": "column", "field": name}
        for name in source_fields
    )
    options.extend(
        {
            "value": f"sp:{kind}",
            "label": SPECIAL_SOURCE_LABEL[kind],
            "kind": kind,
            "field": "",
        }
        for kind in ("const", "today")
    )
    return options


def binding_head(model) -> dict:
    if model is None:
        return {
            "suggested": 0,
            "needs_confirm": 0,
            "const": 0,
            "promote_label": "",
            "promoted_label": "",
            "unused_columns": 0,
        }
    suggested = model.suggested_count()
    return {
        "suggested": suggested,
        "needs_confirm": model.needs_confirm_count(),
        "const": model.const_count(),
        "promote_label": f"제안 {suggested}건 모두 확인",
        "promoted_label": (
            "제안을 모두 확인했습니다"
            if any(row.confirmed and not row.auto_confirmed_exact for row in model.rows)
            else "확인할 제안이 없습니다"
        ),
        "unused_columns": len(model.unused_source_fields()),
    }


def sample_rows(
    source_fields: list[str], records: list[dict], limit: int
) -> list[list[str]]:
    return [
        ["" if (value := record.get(field)) is None else str(value) for field in source_fields]
        for record in records[:limit]
    ]


def sequence_example(first: str, pattern: str) -> str:
    if not first or not pattern_uses_seq(pattern):
        return first
    pads = seq_token_pads(pattern)
    pad = pads[0] if pads else None
    return " · ".join(
        [first, *(format_seq_token(pad, number) for number in (2, 3))]
    )


def pattern_preview(
    pattern: str,
    model,
    records: list[dict],
    now: datetime,
) -> str:
    if not pattern:
        return ""
    data: dict[str, object] = {}
    if model is not None:
        data = model.name_token_values(records[0] if records else {}, now=now)
    try:
        first = make_output_filename(pattern, data, seq=1, now=now)
    except Exception:  # noqa: BLE001 - preview validation belongs to the save gate.
        return ""
    return sequence_example(first, pattern)
