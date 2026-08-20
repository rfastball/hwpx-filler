"""Post-R2 current PreviewRequirement and actual user projection."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import hwpxfiller.application.preview_requirement as preview_module
from hwpxfiller.application.document_creation_vocabulary import (
    PREVIEW_REQUIREMENT_KINDS,
    SEMANTIC_PREVIEW_LABEL,
)
from hwpxfiller.application.execution_semantic_kernel import SealedExecutionPlanValue
from hwpxfiller.application.generation_delivery import (
    WRITE_NEW,
    WRITE_OVERWRITE,
    CurrentResolvedDelivery,
    CurrentResolvedDeliveryItem,
)
from hwpxfiller.application.preview_requirement import (
    DESTRUCTIVE_OVERWRITE,
    NOT_REQUIRED,
    OPTIONAL,
    REQUIRED,
    CurrentPreviewPreparationError,
    PreviewNotRequired,
    PreviewOptional,
    PreviewRequired,
    SemanticValuePreviewProjection,
    build_current_preview_projection,
    evaluate_current_preview_requirement,
)
from hwpxfiller.application.record_validation import CurrentValidatedDataRecord
from hwpxfiller.domain.raw_data_record import RawDataRecordSnapshot


def _delivery(
    *dispositions: str, policy: str = "ADD_SUFFIX"
) -> CurrentResolvedDelivery:
    return CurrentResolvedDelivery(
        exact_pattern="{{f_name}}",
        captured_delivery_clock="2026-08-20T09:00:00",
        output_directory="C:/out",
        collision_policy=policy,
        ordered_items=tuple(
            CurrentResolvedDeliveryItem(
                record_identity=f"record-{ordinal}",
                item_ordinal=ordinal,
                resolved_output_relative_path=f"문서-{ordinal}.hwpx",
                collision_disposition=disposition,
            )
            for ordinal, disposition in enumerate(dispositions)
        ),
    )


def test_current_policy_uses_actual_resolved_overwrite_only() -> None:
    assert evaluate_current_preview_requirement(None).kind == NOT_REQUIRED
    assert evaluate_current_preview_requirement(_delivery(WRITE_NEW)).kind == OPTIONAL
    assert (
        evaluate_current_preview_requirement(
            _delivery(WRITE_NEW, policy="OVERWRITE_EXPLICIT")
        ).kind
        == OPTIONAL
    )
    required = evaluate_current_preview_requirement(
        _delivery(WRITE_NEW, WRITE_OVERWRITE, policy="OVERWRITE_EXPLICIT")
    )
    assert isinstance(required, PreviewRequired)
    assert required.kind == REQUIRED
    assert required.reason == DESTRUCTIVE_OVERWRITE


def test_requirement_types_are_the_canonical_three() -> None:
    assert (NOT_REQUIRED, OPTIONAL, REQUIRED) == PREVIEW_REQUIREMENT_KINDS
    assert isinstance(evaluate_current_preview_requirement(None), PreviewNotRequired)
    assert isinstance(evaluate_current_preview_requirement(_delivery()), PreviewOptional)
    with pytest.raises(ValueError):
        PreviewRequired(reason="OVERWRITE_EXPLICIT")


def _plan() -> SealedExecutionPlanValue:
    return cast(
        SealedExecutionPlanValue,
        SimpleNamespace(
            active_field_requirements=(
                {"field_id": "f_name", "display_label": "이름"},
                {"field_id": "f_note"},
            )
        ),
    )


def _raw(identity: str) -> RawDataRecordSnapshot:
    return cast(RawDataRecordSnapshot, SimpleNamespace(record_identity=identity))


def _validated(identity: str, name: str, note: str) -> CurrentValidatedDataRecord:
    return cast(
        CurrentValidatedDataRecord,
        SimpleNamespace(
            record_identity=identity,
            document_values_in_order=lambda: (("f_name", name), ("f_note", note)),
        ),
    )


def test_projection_zips_exact_values_paths_and_dispositions() -> None:
    requirement = PreviewRequired(reason=DESTRUCTIVE_OVERWRITE)
    projection = build_current_preview_projection(
        preview_token="opaque-token",
        requirement=requirement,
        plan=_plan(),
        raw_records=(_raw("record-0"), _raw("record-1")),
        validated_records=(
            _validated("record-0", "홍길동", "원문 그대로"),
            _validated("record-1", "김영희", ""),
        ),
        delivery=_delivery(WRITE_NEW, WRITE_OVERWRITE),
        record_display_locators=("데이터 3행", "데이터 7행"),
    )

    assert projection.label == SEMANTIC_PREVIEW_LABEL
    assert projection.preview_token == "opaque-token"
    assert projection.requirement is requirement
    assert projection.included_content_summary == "데이터 2건 · 항목 2개"
    assert projection.is_artifact is False
    first, second = projection.ordered_records
    assert first.record_identity == "record-0"
    assert first.record_display_locator == "데이터 3행"
    assert [(v.field_id, v.display_label, v.value) for v in first.logical_field_values] == [
        ("f_name", "이름", "홍길동"),
        ("f_note", "f_note", "원문 그대로"),
    ]
    assert first.planned_document_relative_path == "문서-0.hwpx"
    assert first.collision_disposition == WRITE_NEW
    assert second.planned_document_relative_path == "문서-1.hwpx"
    assert second.collision_disposition == WRITE_OVERWRITE


@pytest.mark.parametrize("mismatch", ["count", "identity", "ordinal"])
def test_projection_fails_closed_on_record_delivery_mismatch(mismatch: str) -> None:
    raw = (_raw("record-0"),)
    validated = (_validated("record-0", "값", ""),)
    delivery = _delivery(WRITE_NEW)
    locators = ("데이터 1행",)
    if mismatch == "count":
        locators = ()
    elif mismatch == "identity":
        validated = (_validated("other", "값", ""),)
    else:
        delivery = dataclasses.replace(
            delivery,
            ordered_items=(dataclasses.replace(delivery.ordered_items[0], item_ordinal=4),),
        )

    with pytest.raises(CurrentPreviewPreparationError):
        build_current_preview_projection(
            preview_token="opaque-token",
            requirement=PreviewOptional(),
            plan=_plan(),
            raw_records=raw,
            validated_records=validated,
            delivery=delivery,
            record_display_locators=locators,
        )


def test_projection_has_no_historical_refs_or_artifact_payload() -> None:
    fields = {field.name for field in dataclasses.fields(SemanticValuePreviewProjection)}
    assert fields == {
        "preview_token",
        "requirement",
        "included_content_summary",
        "ordered_records",
    }
    assert not fields & {
        "exact_basis_ref",
        "current_plan_ref",
        "representative_vdr_ref",
        "hwpx_bytes",
        "xml",
        "artifact",
    }


def test_current_preview_module_has_no_historical_policy_or_opaque_refs() -> None:
    source = Path(preview_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "NEW_WORK_FIRST_RUN",
        "TEMPLATE_APPLICATION_CHANGED_FIRST_RUN",
        "ACTIVE_BINDING_OUTPUT_IMPACT_CHANGE",
        "exact_basis_ref",
        "WorkLevelPreviewApproval",
        "work_level_approval_still_valid",
        "current_plan_ref",
        "representative_vdr_ref",
    ):
        assert forbidden not in source
