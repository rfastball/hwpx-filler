from __future__ import annotations

import hashlib
from unittest.mock import Mock, call

import pytest

from hwpxfiller.application.template_qualification import (
    INSPECTION_CONTRACT_ERROR_CODE,
    INSPECTION_ERROR_CODE,
    CandidateRevisionSnapshot,
    QualificationProfile,
    QualificationInspection,
    TemplateDiagnostic,
    TemplateInspectionContractError,
    TemplateQualificationAttemptErrored,
    TemplateQualificationFailed,
    TemplateQualificationPassed,
    TemplateSlot,
    TemplateStructure,
    qualify_template,
)


def test_qualify_template_maps_outcomes_and_binds_revision_profile() -> None:
    canonical_bytes = b"immutable candidate"
    snapshot = CandidateRevisionSnapshot("R8", canonical_bytes)
    structure = TemplateStructure(slots=(TemplateSlot("notice"),))
    diagnostics = (TemplateDiagnostic("invalid-field-id", "field id is empty"),)
    before = hashlib.sha256(canonical_bytes).digest()

    cases = (
        (
            QualificationInspection(structure, ()),
            TemplateQualificationPassed("R8", "profile-v1", structure),
        ),
        (
            QualificationInspection(None, diagnostics),
            TemplateQualificationFailed("R8", "profile-v1", diagnostics),
        ),
    )
    for inspection, expected in cases:
        inspect = Mock(return_value=inspection)
        profile = QualificationProfile("profile-v1", inspect)
        assert qualify_template(snapshot, profile) == expected
        assert qualify_template(snapshot, profile) == expected
        assert inspect.call_args_list == [call(canonical_bytes), call(canonical_bytes)]

    rebound = qualify_template(
        CandidateRevisionSnapshot("R9", canonical_bytes),
        QualificationProfile(
            "profile-v2",
            lambda _candidate: QualificationInspection(structure, ()),
        ),
    )
    assert rebound == TemplateQualificationPassed("R9", "profile-v2", structure)
    assert hashlib.sha256(canonical_bytes).digest() == before


@pytest.mark.parametrize(
    "inspection",
    (
        QualificationInspection(
            TemplateStructure(),
            (TemplateDiagnostic("impossible", "contradictory evidence"),),
        ),
        QualificationInspection(None, ()),
    ),
)
def test_qualify_template_rejects_broken_inspection_invariant(
    inspection: QualificationInspection,
) -> None:
    result = qualify_template(
        CandidateRevisionSnapshot("R8", b"candidate"),
        QualificationProfile("profile-v1", lambda _candidate: inspection),
    )

    assert result == TemplateQualificationAttemptErrored(
        "R8", "profile-v1", INSPECTION_CONTRACT_ERROR_CODE
    )


@pytest.mark.parametrize(
    ("error", "error_code"),
    (
        (
            TemplateInspectionContractError("pair contract broke"),
            INSPECTION_CONTRACT_ERROR_CODE,
        ),
        (RuntimeError("implementation bug"), INSPECTION_ERROR_CODE),
        (OSError("resource unavailable"), INSPECTION_ERROR_CODE),
    ),
)
def test_qualify_template_keeps_attempt_errors_out_of_candidate_evidence(
    error: Exception,
    error_code: str,
) -> None:
    def inspect(_candidate: bytes) -> QualificationInspection:
        raise error

    result = qualify_template(
        CandidateRevisionSnapshot("R8", b"candidate"),
        QualificationProfile("profile-v1", inspect),
    )

    assert result == TemplateQualificationAttemptErrored("R8", "profile-v1", error_code)
