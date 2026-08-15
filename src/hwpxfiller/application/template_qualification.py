"""Native-free values crossing the HWPX qualification port."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


INSPECTION_CONTRACT_ERROR_CODE = "inspection-contract-error"
INSPECTION_ERROR_CODE = "inspection-error"


class TemplateInspectionContractError(RuntimeError):
    """External inspection evidence contradicts its pair-local contract."""


@dataclass(frozen=True)
class CandidateRevisionSnapshot:
    revision_id: str
    canonical_bytes: bytes


@dataclass(frozen=True)
class TemplateOption:
    id: str
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemplateSlot:
    id: str
    shared_fields: tuple[str, ...] = ()
    options: tuple[TemplateOption, ...] = ()


@dataclass(frozen=True)
class TemplateStructure:
    root_fields: tuple[str, ...] = ()
    slots: tuple[TemplateSlot, ...] = ()


@dataclass(frozen=True)
class TemplateDiagnostic:
    kind: str
    message: str


@dataclass(frozen=True)
class QualificationInspection:
    structure: TemplateStructure | None
    diagnostics: tuple[TemplateDiagnostic, ...]


TemplateInspectorPort = Callable[[bytes], QualificationInspection]


@dataclass(frozen=True)
class QualificationProfile:
    id: str
    inspect: TemplateInspectorPort


@dataclass(frozen=True)
class TemplateQualificationPassed:
    revision_id: str
    qualification_profile_id: str
    structure: TemplateStructure


@dataclass(frozen=True)
class TemplateQualificationFailed:
    revision_id: str
    qualification_profile_id: str
    diagnostics: tuple[TemplateDiagnostic, ...]


@dataclass(frozen=True)
class TemplateQualificationAttemptErrored:
    revision_id: str
    qualification_profile_id: str
    error_code: str


TemplateQualificationResult = (
    TemplateQualificationPassed
    | TemplateQualificationFailed
    | TemplateQualificationAttemptErrored
)


def qualify_template(
    snapshot: CandidateRevisionSnapshot,
    profile: QualificationProfile,
) -> TemplateQualificationResult:
    """Bind one read-only inspection outcome to its Candidate revision and profile."""
    try:
        inspection = profile.inspect(snapshot.canonical_bytes)
        structure = inspection.structure
        diagnostics = inspection.diagnostics
    except TemplateInspectionContractError:
        return TemplateQualificationAttemptErrored(
            snapshot.revision_id,
            profile.id,
            INSPECTION_CONTRACT_ERROR_CODE,
        )
    except Exception:
        return TemplateQualificationAttemptErrored(
            snapshot.revision_id,
            profile.id,
            INSPECTION_ERROR_CODE,
        )

    if (structure is None and not diagnostics) or (
        structure is not None and bool(diagnostics)
    ):
        return TemplateQualificationAttemptErrored(
            snapshot.revision_id,
            profile.id,
            INSPECTION_CONTRACT_ERROR_CODE,
        )
    if structure is None:
        return TemplateQualificationFailed(
            snapshot.revision_id,
            profile.id,
            diagnostics,
        )
    return TemplateQualificationPassed(
        snapshot.revision_id,
        profile.id,
        structure,
    )
