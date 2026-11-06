"""Shared durable seed; remove with the remaining job binding review tests."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from hwpxfiller.application.candidate_revision import (
    ContentBlob,
    SourceCaptureObservation,
    TemplateRevision,
    blob_digest,
)
from hwpxfiller.application.execution_structure import (
    LABELED_EXECUTION_QUALIFICATION_PROFILE_ID,
    LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
    build_execution_manifest,
    decode_execution_structure,
    execution_pass_projection,
)
from hwpxfiller.application.qualification_evidence import (
    QualificationAttempt,
    QualificationEvidence,
    QualificationProfileRevocation,
)
from hwpxfiller.application.stored_work_configuration import (
    STORE_SCHEMA_VERSION as CFG_STORE_SCHEMA,
    StoredWorkConfiguration,
)
from hwpxfiller.application.work_slot_configuration import (
    EMPTY,
    SCHEMA_VERSION as CFG_AGG_SCHEMA,
    WorkSlotConfigurationAggregate,
    WorkSlotConfigurationDraft,
)
from hwpxfiller.application.work_template_state import (
    INITIALIZATION,
    SCHEMA_VERSION as WORK_SCHEMA,
    DocumentWork,
    WorkTemplateApplication,
    WorkTemplateStateAggregate,
)
from hwpxfiller.domain.slot_selection import SlotSelection, SlotSelectionSet
from hwpxfiller.external.candidate_store import CandidateObjectStore
from hwpxfiller.external.qualification_store import QualificationObjectStore
from hwpxfiller.external.work_configuration_store import WorkSlotConfigurationStore
from hwpxfiller.external.work_template_store import AtomicWorkTemplateStateStore

APP = "app-1"
AT = "2026-08-16T00:00:00Z"
MEDIA = "hwpx"
WORK = "work-1"
WS = "ws-1"
LINEAGE = "lin-1"
EVIDENCE_ID = "ev-1"
REVISION_ID = "rev-1"
OBSERVATION_ID = "obs-1"
BLOB_BYTES = b"exact-template-bytes"
CONTRACT = "slot-selection/v1"
PROFILE = LABELED_EXECUTION_QUALIFICATION_PROFILE_ID


# ─── 실 store seed ────────────────────────────────────────────────────────────────────
def _seed_v2_work(root, *, with_config: bool = True, revoked: bool = False) -> None:
    works = AtomicWorkTemplateStateStore(root / "works")
    qual = QualificationObjectStore(root / "qualification")
    cand = CandidateObjectStore(root / "candidates")
    configs = WorkSlotConfigurationStore(root / "slot_configs")

    # candidate: blob → observation → revision(참조 무결성).
    digest = blob_digest(BLOB_BYTES)
    cand.put_blob(
        ContentBlob(digest=digest, media=MEDIA, exact_bytes=BLOB_BYTES, byte_length=len(BLOB_BYTES))
    )
    cand.put_observation(
        SourceCaptureObservation(
            observation_id=OBSERVATION_ID, preparation_id="prep-1", source_binding_id="sb-1",
            source_binding_generation=1, capture_method="zip", observed_metadata={},
            captured_content_digest=digest, captured_at=AT,
        )
    )
    cand.put_revision(
        TemplateRevision(
            revision_id=REVISION_ID, template_lineage_id=LINEAGE, media=MEDIA,
            exact_content_digest=digest, origin_capture_observation_id=OBSERVATION_ID,
            created_at=AT,
        )
    )

    # qualification: v2 manifest + v2 execution PASS Evidence(+ optional revocation).
    qual.put_manifest(
        build_execution_manifest(
            qualification_profile_id=PROFILE,
            media=MEDIA, adapter_contract_version="a/1", product_rule_version="p/1",
            operation_alphabet_version="o/1", created_at=AT,
        )
    )
    qual.put_attempt(
        QualificationAttempt(
            attempt_id="at-1", preparation_id="prep-1", revision_id=REVISION_ID,
            qualification_profile_id=PROFILE, outcome="PASS", evidence_id=EVIDENCE_ID,
            error_code=None, started_at=AT, completed_at=AT,
        )
    )
    qual.put_evidence(
        QualificationEvidence(
            evidence_id=EVIDENCE_ID, attempt_id="at-1", revision_id=REVISION_ID,
            qualification_profile_id=PROFILE, result="PASS",
            structure_projection=execution_pass_projection(replace(
                decode_execution_structure(json.loads(
                    (Path(__file__).parent / "fixtures" / "execution_compilation.json").read_text(encoding="utf-8")
                )["structures"]["normal"]),
                projection_schema_version=LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
            )),
            diagnostics=(), engine_metadata={}, qualified_at=AT,
        )
    )
    if revoked:
        qual.put_revocation(
            QualificationProfileRevocation(
                qualification_profile_id=PROFILE, reason="policy", authority="admin",
                revoked_at=AT,
            )
        )

    # work aggregate: current Application 이 그 PASS Evidence 를 가리킨다.
    works.create(
        WorkTemplateStateAggregate(
            schema_version=WORK_SCHEMA, aggregate_version=1,
            work=DocumentWork(
                work_id=WORK, template_lineage_id=LINEAGE,
                current_template_application_id=APP,
                current_template_preparation_id=None, prepare_seq=0,
            ),
            applications=(
                WorkTemplateApplication(
                    application_id=APP, work_id=WORK, application_epoch=1,
                    pass_evidence_id=EVIDENCE_ID, previous_application_id=None,
                    origin=INITIALIZATION, prepared_change_id=None, actor="t", applied_at=AT,
                ),
            ),
            preparations=(), prepared_changes=(),
        )
    )

    if with_config:
        draft = WorkSlotConfigurationDraft(
            work_id=WORK, base_template_application_id=APP, version=1,
            selections=SlotSelectionSet((SlotSelection("s1", ("o1",)),)),
            origin=EMPTY, reconciled_from_application_id=None, reconciled_from_version=None,
            reconciled_from_declared_selection_digest=None, created_at=AT, updated_at=AT,
        )
        configs.create(
            StoredWorkConfiguration(
                schema_version=CFG_STORE_SCHEMA, aggregate_version=1, workspace_instance_id=WS,
                configurations=WorkSlotConfigurationAggregate(
                    schema_version=CFG_AGG_SCHEMA, work_id=WORK, configurations=(draft,)
                ),
                processed_requests=(),
            )
        )
