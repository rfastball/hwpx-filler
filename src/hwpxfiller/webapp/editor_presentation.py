"""Editor snapshot projections (pure, webview-free).

편집기 스냅샷의 조각들 — 세션 상태(``EditSession``)를 읽어 표면 모양으로 성형한다. 재료 쪽
조회는 :mod:`~hwpxfiller.webapp.editor_sources` 가 지고, 조립은
:class:`~hwpxfiller.webapp.editor_session.EditorProjection` 이 한다.

**단계 관문**(어떤 탭이 있고, 다음 탭으로 갈 수 있는가, 왜 못 가는가)도 여기 순수 함수로
산다. 세 물음은 한 판정의 세 얼굴이다: 단계 표지(``reachable``)·「다음」 단추의 가부·막힌
사유 문장이 각자 상태를 다시 읽으면 화면은 「갈 수 있다」고 말하고 이동은 거절하는 어긋남이
생긴다 — 투영(스냅샷)과 로더(탭 이동)가 같은 함수를 부른다.
"""

from __future__ import annotations

from datetime import datetime

from ..domain.job import template_media
from ..domain.output_name import format_seq_token
from ..viewmodel.edit_session import (
    SECTION_BINDING,
    SECTION_FILENAME,
    SECTION_TEMPLATE,
    EditSession,
    sections_for,
)
from ..viewmodel.mapping_state import (
    NO_SOURCE_LABEL,
    RAW_BLOCK_MESSAGE,
    SPECIAL_SOURCE_LABEL,
    pairing_preview,
    row_projection,
)
from ..naming import make_output_filename, pattern_uses_seq, seq_token_pads

PROVENANCE_DRIFT_TEXT = "작성 당시와 템릿 필드 구성이 다릅니다. 매핑 재검토가 필요할 수 있습니다."


def editor_sections(edit: EditSession) -> "tuple[str, ...]":
    """이 세션의 탭 구성 — 템플릿을 아직 고르지 않았으면 HWPX 구성으로 선다."""
    return sections_for(template_media(edit.template_path) if edit.template_path else "hwpx")


def template_ready(edit: EditSession) -> bool:
    """고른 템플릿으로 다음 단계에 설 수 있는가 — 필드가 있고 부분 채움 관문이 열렸다."""
    return (
        edit.schema is not None
        and bool(edit.schema.fields)
        and (not edit.gate_error)
        and (edit.gate is None or edit.gate.can_proceed())
    )


def can_advance(edit: EditSession, from_section: str) -> bool:
    """``from_section`` 에서 다음 탭으로 갈 수 있는가."""
    if from_section == SECTION_TEMPLATE:
        return template_ready(edit) and bool(edit.data_path)
    if from_section == SECTION_BINDING:
        return edit.model is not None and edit.model.is_complete()
    return False


def advance_block_reason(edit: EditSession) -> str:
    """고르기 단계에서 다음으로 못 가는 사유 — 갈 수 있으면 ``""``."""
    if edit.raw_block:
        return edit.raw_block
    if edit.gate_error:
        return "템플릿 상태를 확인할 수 없습니다."
    if not edit.template_path:
        return "왼쪽에서 템플릿을 고르세요."
    if edit.schema is None or not edit.schema.fields:
        return RAW_BLOCK_MESSAGE
    if not template_ready(edit):
        return "이 템플릿은 아직 진행할 수 없습니다. 미해결 토큰을 확인하세요."
    if not edit.data_path:
        return "오른쪽에서 데이터를 고르세요."
    return ""


def gate_snapshot(gate) -> "dict | None":
    """부분 채움 관문의 표면 투영 — 확인할 것이 없으면 ``None``."""
    if gate is None or not gate.needs_gate():
        return None
    return {"message": gate.message(), "unmet": list(gate.unmet_tokens), "acked": gate.is_acked()}


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


def template_shape(edit) -> dict:
    """세션 템플릿의 매체·필드 수·필드 목록 — 고르지 않았거나 RAW 면 빈 값."""
    schema = edit.schema
    return {
        "template_media": template_media(edit.template_path) if edit.template_path else "",
        "field_count": len(schema.fields) if schema else 0,
        "fields": [f.to_dict() for f in schema.fields] if schema else [],
    }


def provenance_drift(loaded_provenance: dict, schema) -> str:
    """저장본을 쓸 당시와 지금 템플릿의 필드 구성이 다르면 그 경고 — 같거나 모르면 ``""``."""
    recorded = loaded_provenance.get("template_fields", "")
    if not recorded or schema is None or (not schema.fields):
        return ""
    if recorded == " · ".join(schema.field_names()):
        return ""
    return PROVENANCE_DRIFT_TEXT


def filename_preview(edit, now: datetime) -> str:
    """「이름·저장」 단계의 파일 이름 예시 — 그 단계·HWPX·규칙이 있을 때만 선다."""
    if (
        edit.section != SECTION_FILENAME
        or template_media(edit.template_path) == "txt"
        or not edit.pattern
    ):
        return ""
    return pattern_preview(edit.pattern, edit.model, edit.records, now)


def pairing_counts(edit, field_names: "list[str]", ready: bool) -> "tuple[int, int, str]":
    """고르기 단계 조합 카드의 ``(자동, 확인 필요, 근거)`` — 그 단계가 아니면 0·0·빈 근거.

    모델이 지금 조합과 같으면 모델의 확정 수를, 아니면 제안 미리보기를 센다(조합 키로 캐시).
    """
    if not ready or edit.section != SECTION_TEMPLATE:
        return 0, 0, ""
    if edit.model is not None and edit.model_key == edit.model_key_now():
        auto = sum((1 for r in edit.model.rows if r.confirmed))
        return auto, len(edit.model.rows) - auto, "model"
    key = edit.model_key_now()
    cached = edit.pairing_cache
    if cached is not None and cached[0] == key:
        counts = cached[1]
    else:
        counts = pairing_preview(field_names, edit.source_fields)
        edit.pairing_cache = (key, counts)
    auto, confirm = counts
    return auto, confirm, "preview"


def binding_snapshot(edit, now: datetime) -> dict:
    """「연결 확인」 표의 행·수치 — 매핑 모델이 없으면 빈 표와 미완료."""
    model = edit.model
    if model is None:
        return {"rows": [], "is_complete": False, "binding_head": binding_head(model)}
    schema_only = model.is_schema_only()
    record = edit.current_record()
    rows = [
        row_projection(
            row,
            record,
            index=i,
            source_fields=edit.source_fields,
            has_records=bool(edit.records),
            now=now,
        )
        for i, row in enumerate(model.rows)
    ]
    filled, empty, unmapped = model.preview_counts(record, now=now)
    return {
        "rows": rows,
        "counts": {"filled": filled, "empty": empty, "unmapped": unmapped},
        "preview_empties": model.preview_empties(record, now=now),
        "preview_index": edit.preview_index % len(edit.records) + 1 if edit.records else 0,
        "preview_count": len(edit.records),
        "is_complete": model.is_complete(),
        "schema_only": schema_only,
        "binding_head": binding_head(model),
    }
