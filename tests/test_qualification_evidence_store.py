from __future__ import annotations

import json

import pytest

from hwpxfiller.application.qualification_evidence import (
    ProfileIdentityMismatch,
    QualificationAttempt,
    QualificationEvidence,
    QualificationEvidenceError,
    QualificationProfileRevocation,
    StructureProjection,
    build_manifest,
    build_records,
    project_structure,
    verify_runtime_profile,
)
from hwpxfiller.application.template_qualification import (
    TemplateDiagnostic,
    TemplateOption,
    TemplateQualificationAttemptErrored,
    TemplateQualificationFailed,
    TemplateQualificationPassed,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.external.qualification_store import (
    ObjectAlreadyExists,
    ObjectCorrupt,
    ObjectNotFound,
    QualificationObjectStore,
)

STRUCTURE = TemplateStructure(
    root_fields=("title",),
    slots=(TemplateSlot("notice", ("date",), (TemplateOption("A", ("amount",)),)),),
)
DIAGS = (TemplateDiagnostic("invalid-field-id", "field id empty"),)
META = {"engine": "hwpx-v1"}


def _record_args(**over):
    args = dict(
        attempt_id="AT1",
        preparation_id="P1",
        evidence_id="EV1",
        projection_schema_version="proj-v1",
        engine_metadata=META,
        started_at="t0",
        completed_at="t1",
        qualified_at="t1",
    )
    args.update(over)
    return args


def _manifest(profile_id="prof-v1", payload=None):
    return build_manifest(
        qualification_profile_id=profile_id,
        media="hwpx",
        adapter_contract_version="a1",
        product_rule_version="r1",
        operation_alphabet_version="o1",
        projection_schema_version="proj-v1",
        manifest_payload=payload or {"rules": ["x"]},
        created_at="t0",
    )


def test_build_records_maps_pass_fail_error() -> None:
    passed = TemplateQualificationPassed("R8", "prof-v1", STRUCTURE)
    attempt, evidence = build_records(passed, **_record_args())
    assert (attempt.outcome, attempt.evidence_id, attempt.error_code) == ("PASS", "EV1", None)
    assert evidence.result == "PASS"
    assert evidence.structure_projection == project_structure(STRUCTURE, "proj-v1")
    assert evidence.diagnostics == ()

    failed = TemplateQualificationFailed("R8", "prof-v1", DIAGS)
    attempt, evidence = build_records(failed, **_record_args())
    assert attempt.outcome == "FAIL"
    assert evidence.result == "FAIL" and evidence.structure_projection is None
    assert evidence.diagnostics == ({"kind": "invalid-field-id", "message": "field id empty"},)

    errored = TemplateQualificationAttemptErrored("R8", "prof-v1", "inspection-error")
    attempt, evidence = build_records(errored, **_record_args())
    assert evidence is None
    assert (attempt.outcome, attempt.evidence_id, attempt.error_code) == (
        "ERROR",
        None,
        "inspection-error",
    )


def test_store_round_trips_and_binds_evidence_to_attempt(tmp_path) -> None:
    store = QualificationObjectStore(tmp_path)
    manifest = _manifest()
    store.put_manifest(manifest)
    assert store.get_manifest("prof-v1") == manifest

    attempt, evidence = build_records(
        TemplateQualificationPassed("R8", "prof-v1", STRUCTURE), **_record_args()
    )
    store.put_attempt(attempt)
    store.put_evidence(evidence)
    assert store.get_attempt("AT1") == attempt
    assert store.get_evidence("EV1") == evidence

    store.put_manifest(manifest)  # same payload → idempotent
    with pytest.raises(ObjectNotFound):
        store.get_evidence("missing")


def test_store_revocation_is_separate_immutable_record(tmp_path) -> None:
    store = QualificationObjectStore(tmp_path)
    store.put_manifest(_manifest())
    assert store.get_revocation("prof-v1") is None and not store.is_revoked("prof-v1")
    store.put_revocation(
        QualificationProfileRevocation("prof-v1", "superseded", "owner", "t2")
    )
    assert store.is_revoked("prof-v1")
    assert store.get_manifest("prof-v1") == _manifest()  # manifest 무수정


def test_store_rejects_divergent_manifest_payload(tmp_path) -> None:
    store = QualificationObjectStore(tmp_path)
    store.put_manifest(_manifest(payload={"rules": ["x"]}))
    with pytest.raises(ObjectAlreadyExists):
        store.put_manifest(_manifest(payload={"rules": ["y"]}))


def test_store_rejects_evidence_bound_to_wrong_revision(tmp_path) -> None:
    store = QualificationObjectStore(tmp_path)
    attempt, evidence = build_records(
        TemplateQualificationPassed("R8", "prof-v1", STRUCTURE), **_record_args()
    )
    store.put_attempt(attempt)
    mismatched = QualificationEvidence(
        evidence_id="EV1",
        attempt_id="AT1",
        revision_id="R9",  # attempt 은 R8
        qualification_profile_id="prof-v1",
        result="PASS",
        structure_projection=evidence.structure_projection,
        diagnostics=(),
        engine_metadata=META,
        qualified_at="t1",
    )
    with pytest.raises(QualificationEvidenceError):
        store.put_evidence(mismatched)


def test_read_detects_corrupted_evidence(tmp_path) -> None:
    store = QualificationObjectStore(tmp_path)
    attempt, evidence = build_records(
        TemplateQualificationPassed("R8", "prof-v1", STRUCTURE), **_record_args()
    )
    store.put_attempt(attempt)
    store.put_evidence(evidence)
    path = tmp_path / "evidence" / "EV1.json"
    tampered = json.loads(path.read_text("utf-8"))
    tampered["content"]["revision_id"] = "R-tampered"
    path.write_text(json.dumps(tampered), "utf-8")
    with pytest.raises(ObjectCorrupt):
        store.get_evidence("EV1")


def test_verify_runtime_profile_mismatch_is_loud() -> None:
    with pytest.raises(ProfileIdentityMismatch):
        verify_runtime_profile(_manifest("prof-v1"), "prof-v2")


@pytest.mark.parametrize(
    "kwargs",
    (
        dict(result="PASS", structure_projection=None, diagnostics=()),
        dict(
            result="PASS",
            structure_projection=project_structure(STRUCTURE, "proj-v1"),
            diagnostics=({"kind": "k", "message": "m"},),
        ),
        dict(
            result="FAIL",
            structure_projection=project_structure(STRUCTURE, "proj-v1"),
            diagnostics=({"kind": "k", "message": "m"},),
        ),
        dict(result="FAIL", structure_projection=None, diagnostics=()),
    ),
)
def test_evidence_invariants_reject_broken_shape(kwargs) -> None:
    with pytest.raises(QualificationEvidenceError):
        QualificationEvidence(
            evidence_id="EV1",
            attempt_id="AT1",
            revision_id="R8",
            qualification_profile_id="prof-v1",
            engine_metadata=META,
            qualified_at="t1",
            **kwargs,
        )


@pytest.mark.parametrize(
    "kwargs",
    (
        dict(outcome="ERROR", evidence_id="EV1", error_code="e"),  # ERROR 는 Evidence 없음
        dict(outcome="ERROR", evidence_id=None, error_code=None),  # ERROR 는 code 필수
        dict(outcome="PASS", evidence_id=None, error_code=None),  # PASS 는 Evidence 필수
        dict(outcome="PASS", evidence_id="EV1", error_code="e"),  # PASS 에 code 금지
    ),
)
def test_attempt_invariants_reject_broken_shape(kwargs) -> None:
    with pytest.raises(QualificationEvidenceError):
        QualificationAttempt(
            attempt_id="AT1",
            preparation_id="P1",
            revision_id="R8",
            qualification_profile_id="prof-v1",
            started_at="t0",
            completed_at="t1",
            **kwargs,
        )


def test_structure_projection_digest_guards_payload() -> None:
    good = project_structure(STRUCTURE, "proj-v1")
    with pytest.raises(QualificationEvidenceError):
        StructureProjection("proj-v1", {"root_fields": ["x"]}, good.payload_digest)
