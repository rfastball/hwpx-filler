"""Post-R2 current preview requirement and user projection (SX-04C)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from hwpxfiller.application.document_creation_vocabulary import (
    PREVIEW_REQUIREMENT_KINDS,
    SEMANTIC_PREVIEW_LABEL,
)
from hwpxfiller.application.execution_semantic_kernel import SealedExecutionPlanValue
from hwpxfiller.application.generation_delivery import (
    WRITE_OVERWRITE,
    CurrentResolvedDelivery,
)
from hwpxfiller.application.record_validation import CurrentValidatedDataRecord
from hwpxfiller.domain.raw_data_record import RawDataRecordSnapshot

NOT_REQUIRED, OPTIONAL, REQUIRED = PREVIEW_REQUIREMENT_KINDS
DESTRUCTIVE_OVERWRITE = "DESTRUCTIVE_OVERWRITE"


@dataclass(frozen=True)
class PreviewNotRequired:
    kind: ClassVar[str] = NOT_REQUIRED


@dataclass(frozen=True)
class PreviewOptional:
    kind: ClassVar[str] = OPTIONAL


@dataclass(frozen=True)
class PreviewRequired:
    reason: str
    kind: ClassVar[str] = REQUIRED

    def __post_init__(self) -> None:
        if self.reason != DESTRUCTIVE_OVERWRITE:
            raise ValueError(f"unsupported required preview reason: {self.reason!r}")


PreviewRequirement = PreviewNotRequired | PreviewOptional | PreviewRequired


def evaluate_current_preview_requirement(
    delivery: CurrentResolvedDelivery | None,
) -> PreviewRequirement:
    """Judge only the currently resolved delivery; policy intent alone is insufficient."""
    if delivery is None:
        return PreviewNotRequired()
    if any(
        item.collision_disposition == WRITE_OVERWRITE
        for item in delivery.ordered_items
    ):
        return PreviewRequired(reason=DESTRUCTIVE_OVERWRITE)
    return PreviewOptional()


@dataclass(frozen=True)
class PreviewFieldValue:
    field_id: str
    display_label: str
    value: str


@dataclass(frozen=True)
class PreviewRecord:
    record_identity: str
    record_display_locator: str
    logical_field_values: tuple[PreviewFieldValue, ...]
    planned_document_relative_path: str
    collision_disposition: str


@dataclass(frozen=True)
class SemanticValuePreviewProjection:
    """User-facing values and planned delivery; never HWPX bytes or native layout."""

    preview_token: str
    requirement: PreviewRequirement
    included_content_summary: str
    ordered_records: tuple[PreviewRecord, ...]
    label: ClassVar[str] = SEMANTIC_PREVIEW_LABEL
    is_artifact: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if not self.preview_token:
            raise ValueError("preview_token must be non-empty")
        if not self.included_content_summary:
            raise ValueError("included_content_summary must be non-empty")


class CurrentPreviewPreparationError(ValueError):
    """The current record/value/delivery projections do not describe one exact batch."""


def build_current_preview_projection(
    *,
    preview_token: str,
    requirement: PreviewRequirement,
    plan: SealedExecutionPlanValue,
    raw_records: Sequence[RawDataRecordSnapshot],
    validated_records: Sequence[CurrentValidatedDataRecord],
    delivery: CurrentResolvedDelivery,
    record_display_locators: Sequence[str],
) -> SemanticValuePreviewProjection:
    """Zip already-prepared A/B values and fail closed on any ordinal mismatch.

    This approval is not a filesystem reservation or publication guarantee. S6 must
    re-observe occupancy immediately before publication; changed paths/dispositions,
    especially a new overwrite target, require fresh delivery, token, and approval.
    """
    lengths = {
        len(raw_records),
        len(validated_records),
        len(delivery.ordered_items),
        len(record_display_locators),
    }
    if len(lengths) != 1:
        raise CurrentPreviewPreparationError(
            "current record/value/delivery counts do not match"
        )

    labels = {
        field_id: (
            display_label
            if isinstance(display_label, str) and display_label
            else field_id
        )
        for item in plan.active_field_requirements
        if isinstance((field_id := item.get("field_id")), str) and field_id
        for display_label in (item.get("display_label"),)
    }
    records: list[PreviewRecord] = []
    for ordinal, (raw, validated, item, locator) in enumerate(
        zip(
            raw_records,
            validated_records,
            delivery.ordered_items,
            record_display_locators,
            strict=True,
        )
    ):
        if (
            raw.record_identity != validated.record_identity
            or validated.record_identity != item.record_identity
            or item.item_ordinal != ordinal
        ):
            raise CurrentPreviewPreparationError(
                f"current preview ordinal {ordinal} record identity/order mismatch"
            )
        values = tuple(
            PreviewFieldValue(
                field_id=field_id,
                display_label=labels.get(field_id, field_id),
                value=value,
            )
            for field_id, value in validated.document_values_in_order()
        )
        records.append(
            PreviewRecord(
                record_identity=validated.record_identity,
                record_display_locator=locator,
                logical_field_values=values,
                planned_document_relative_path=item.resolved_output_relative_path,
                collision_disposition=item.collision_disposition,
            )
        )

    field_count = len(records[0].logical_field_values) if records else 0
    return SemanticValuePreviewProjection(
        preview_token=preview_token,
        requirement=requirement,
        included_content_summary=f"데이터 {len(records)}건 · 항목 {field_count}개",
        ordered_records=tuple(records),
    )


__all__ = [
    "CurrentPreviewPreparationError",
    "DESTRUCTIVE_OVERWRITE",
    "NOT_REQUIRED",
    "OPTIONAL",
    "REQUIRED",
    "PreviewFieldValue",
    "PreviewNotRequired",
    "PreviewOptional",
    "PreviewRecord",
    "PreviewRequired",
    "PreviewRequirement",
    "SemanticValuePreviewProjection",
    "build_current_preview_projection",
    "evaluate_current_preview_requirement",
]
