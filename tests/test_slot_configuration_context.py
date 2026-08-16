"""S4-04(#674) exact Application Context 조립·cross-reference 무결성·decoder registry.

fake read Port 와 개별-유효하되 상호 불일치인 object 로 각 cross-reference 위반을 fail-closed
로 세운다. 실 aggregate 의 validate_aggregate 가 dangling 을 생성 시점에 막으므로 aggregate
는 가벼운 stub 으로 조립한다(모듈은 .work·.applications 만 읽는다).
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from hwpxfiller.application.candidate_revision import TemplateRevision
from hwpxfiller.application.qualification_evidence import (
    QualificationEvidence,
    StructureProjection,
    build_manifest,
    content_digest,
    project_structure,
)
from hwpxfiller.application.slot_configuration_context import (
    AppliedTemplateContentIntegrityError,
    CrossWorkContext,
    StaleTemplateApplication,
    StructureProjectionDecoderRegistry,
    TemplateInitializationRequired,
    TemplateStructureIntegrityError,
    UnsupportedTemplateStructureProjection,
    resolve_exact_applied_template_input,
    resolve_slot_configuration_context,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.application.work_template_state import (
    INITIALIZATION,
    DocumentWork,
    WorkTemplateApplication,
)
from hwpxfiller.domain.slot_selection import (
    UnsupportedSelectionSemanticContractError,
)

NOW = "2026-08-16T00:00:00Z"
SCHEMA = "hwpx-structure-projection-v1"
PROFILE = "hwpx-template-qualification-v1"
WS = "ws-1"

_STRUCTURE = TemplateStructure(
    root_fields=("title",),
    slots=(TemplateSlot(id="s1", shared_fields=(), options=(TemplateOption("o1"),)),),
)


def _work(work_id: str = "w1", lineage: str = "L1", current: str = "A1") -> DocumentWork:
    return DocumentWork(work_id, lineage, current, None, 0)


def _app(app_id: str = "A1", work_id: str = "w1", evidence: str = "E1", epoch: int = 1):
    return WorkTemplateApplication(
        application_id=app_id, work_id=work_id, application_epoch=epoch,
        pass_evidence_id=evidence, previous_application_id=None,
        origin=INITIALIZATION, prepared_change_id=None, actor="tester", applied_at=NOW,
    )


def _evidence(
    evidence_id: str = "E1", revision: str = "R1", profile: str = PROFILE, schema: str = SCHEMA
) -> QualificationEvidence:
    return QualificationEvidence(
        evidence_id=evidence_id, attempt_id="AT1", revision_id=revision,
        qualification_profile_id=profile, result="PASS",
        structure_projection=project_structure(_STRUCTURE, schema),
        diagnostics=(), engine_metadata={}, qualified_at=NOW,
    )


def _revision(revision: str = "R1", lineage: str = "L1", media: str = "hwpx", digest: str = "sha256:blob1"):
    return TemplateRevision(revision, lineage, media, digest, "OBS1", NOW)


def _manifest(profile: str = PROFILE, media: str = "hwpx", schema: str = SCHEMA):
    return build_manifest(
        qualification_profile_id=profile, media=media, adapter_contract_version="a",
        product_rule_version="p", operation_alphabet_version="op",
        projection_schema_version=schema, manifest_payload={"x": 1}, created_at=NOW,
    )


class _WorkState:
    def __init__(self, aggregate: object | None) -> None:
        self._aggregate = aggregate

    def load(self, work_id: str) -> object | None:
        return self._aggregate


class _Qual:
    def __init__(self, evidence: QualificationEvidence, manifest: object) -> None:
        self._evidence = evidence
        self._manifest = manifest

    def get_evidence(self, evidence_id: str) -> QualificationEvidence:
        return self._evidence

    def get_manifest(self, qualification_profile_id: str) -> object:
        return self._manifest


class _Candidate:
    def __init__(self, revision: TemplateRevision, blobs: set[str]) -> None:
        self._revision = revision
        self._blobs = blobs

    def get_revision(self, revision_id: str) -> TemplateRevision:
        return self._revision

    def has_blob(self, digest: str) -> bool:
        return digest in self._blobs


def _agg(work: DocumentWork, apps: tuple) -> object:
    return SimpleNamespace(work=work, applications=apps)


def _ports(*, work=None, apps=None, evidence=None, revision=None, manifest=None, blobs=None):
    work = work or _work()
    apps = apps if apps is not None else (_app(),)
    evidence = evidence or _evidence()
    revision = revision or _revision()
    manifest = manifest or _manifest()
    blobs = blobs if blobs is not None else {"sha256:blob1"}
    return (
        _WorkState(_agg(work, apps)),
        _Qual(evidence, manifest),
        _Candidate(revision, blobs),
    )


def _resolve(ports, **kw):
    return resolve_slot_configuration_context(*ports, WS, "w1", **kw)


# ── happy path ────────────────────────────────────────────────────────────────
def test_resolves_exact_context() -> None:
    ctx = _resolve(_ports())
    assert ctx.work_id == "w1"
    assert ctx.template_application_id == "A1"
    assert ctx.template_lineage_id == "L1"
    assert ctx.pass_evidence_id == "E1"
    assert ctx.revision_id == "R1"
    assert ctx.structure_projection_schema_version == SCHEMA
    assert ctx.template_structure == _STRUCTURE
    assert ctx.selection_semantic_contract_id == "slot-selection/v1"
    # template_structure_digest 는 Evidence projection 의 payload_digest 를 그대로 싣는다.
    assert ctx.template_structure_digest == project_structure(_STRUCTURE, SCHEMA).payload_digest


def test_applied_input_references_candidate_blob() -> None:
    inp = resolve_exact_applied_template_input(*_ports(), "w1", "A1")
    assert inp.canonical_blob_reference == "sha256:blob1"
    assert inp.exact_content_digest == "sha256:blob1"
    assert inp.media == "hwpx"


# ── cross-reference violations ──────────────────────────────────────────────────
def test_missing_aggregate_requires_initialization() -> None:
    ports = (_WorkState(None), _Qual(_evidence(), _manifest()), _Candidate(_revision(), set()))
    with pytest.raises(TemplateInitializationRequired):
        _resolve(ports)


def test_work_id_mismatch_is_cross_work() -> None:
    ports = _ports(work=_work(work_id="other"))
    with pytest.raises(CrossWorkContext):
        _resolve(ports)


def test_expected_application_not_current_is_stale() -> None:
    with pytest.raises(StaleTemplateApplication):
        resolve_slot_configuration_context(*_ports(), WS, "w1", "A_OLD")


def test_dangling_current_pointer_rejected() -> None:
    ports = _ports(apps=(_app(app_id="A_OTHER"),))  # current=A1 없음
    with pytest.raises(TemplateStructureIntegrityError):
        _resolve(ports)


def test_application_work_id_mismatch_is_cross_work() -> None:
    ports = _ports(apps=(_app(work_id="w2"),))
    with pytest.raises(CrossWorkContext):
        _resolve(ports)


def test_empty_current_pointer_requires_initialization() -> None:
    ports = _ports(work=_work(current=""))
    with pytest.raises(TemplateInitializationRequired):
        _resolve(ports)


def test_revision_id_mismatch_rejected() -> None:
    ports = _ports(revision=_revision(revision="R_WRONG"))  # evidence.revision_id=R1
    with pytest.raises(TemplateStructureIntegrityError):
        _resolve(ports)


def test_manifest_profile_mismatch_rejected() -> None:
    ports = _ports(manifest=_manifest(profile="P_WRONG"))  # evidence profile=PROFILE
    with pytest.raises(TemplateStructureIntegrityError):
        _resolve(ports)


def test_non_pass_evidence_rejected() -> None:
    fail = QualificationEvidence(
        evidence_id="E1", attempt_id="AT1", revision_id="R1",
        qualification_profile_id=PROFILE, result="FAIL", structure_projection=None,
        diagnostics=({"code": "x"},), engine_metadata={}, qualified_at=NOW,
    )
    ports = _ports(evidence=fail)
    with pytest.raises(TemplateStructureIntegrityError):
        _resolve(ports)


def test_evidence_id_mismatch_rejected() -> None:
    ports = _ports(evidence=_evidence(evidence_id="E_WRONG"))
    with pytest.raises(TemplateStructureIntegrityError):
        _resolve(ports)


def test_revision_lineage_mismatch_rejected() -> None:
    ports = _ports(revision=_revision(lineage="L_OTHER"))
    with pytest.raises(TemplateStructureIntegrityError):
        _resolve(ports)


def test_manifest_media_mismatch_rejected() -> None:
    ports = _ports(revision=_revision(media="pdf"))  # manifest media=hwpx
    with pytest.raises(TemplateStructureIntegrityError):
        _resolve(ports)


def test_manifest_projection_schema_mismatch_rejected() -> None:
    ports = _ports(manifest=_manifest(schema="hwpx-structure-projection-v2"))
    with pytest.raises(TemplateStructureIntegrityError):
        _resolve(ports)


def test_applied_blob_absent_is_content_integrity() -> None:
    ports = _ports(blobs=set())  # revision 이 가리키는 blob 없음
    with pytest.raises(AppliedTemplateContentIntegrityError):
        resolve_exact_applied_template_input(*ports, "w1", "A1")


# ── registry ────────────────────────────────────────────────────────────────────
def test_unknown_projection_schema_unsupported() -> None:
    ports = _ports(
        evidence=_evidence(schema="unknown-v9"),
        manifest=_manifest(schema="unknown-v9"),
    )
    with pytest.raises(UnsupportedTemplateStructureProjection):
        _resolve(ports)


def test_unknown_selection_binding_unsupported() -> None:
    # 알려진 projection schema 지만 profile 이 selection registry 에 없는 조합.
    ports = _ports(
        evidence=_evidence(profile="unknown-profile"),
        manifest=_manifest(profile="unknown-profile"),
    )
    with pytest.raises(UnsupportedSelectionSemanticContractError):
        _resolve(ports)


def test_decoder_registry_rejects_duplicate_schema() -> None:
    with pytest.raises(TemplateStructureIntegrityError):
        StructureProjectionDecoderRegistry(
            [("s", lambda p: _STRUCTURE), ("s", lambda p: _STRUCTURE)]
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"root_fields": "title", "slots": []},  # 스칼라 문자열을 char 로 쪼개면 안 된다
        {"root_fields": [1], "slots": []},  # 비문자열 항목
        {"root_fields": [], "slots": "x"},  # slots 스칼라
        {"root_fields": [], "slots": [{"id": 1, "shared_fields": [], "options": []}]},
        {"root_fields": [], "slots": [{"id": "s", "shared_fields": [], "options": "x"}]},
        {"root_fields": [], "slots": ["not-a-mapping"]},  # slot 항목 비매핑
        {  # option 항목 비매핑
            "root_fields": [],
            "slots": [{"id": "s", "shared_fields": [], "options": ["not-a-mapping"]}],
        },
    ],
)
def test_decoder_rejects_mistyped_projection_fields(payload: dict) -> None:
    from hwpxfiller.application.slot_configuration_context import (
        DEFAULT_STRUCTURE_DECODER_REGISTRY,
    )

    decoder = DEFAULT_STRUCTURE_DECODER_REGISTRY.resolve(SCHEMA)
    with pytest.raises(TemplateStructureIntegrityError):
        decoder(payload)


def test_malformed_projection_payload_is_integrity_error() -> None:
    # digest 는 유효하지만 v1 구조가 아닌 payload(slots 키 없음) → decoder fail-closed.
    bad_payload = {"root_fields": ["t"]}
    broken = replace(
        _evidence(),
        structure_projection=StructureProjection(
            SCHEMA, bad_payload, content_digest(bad_payload)
        ),
    )
    ports = _ports(evidence=broken)
    with pytest.raises(TemplateStructureIntegrityError):
        _resolve(ports)


# ── no-latest-fallback / no side-effects ────────────────────────────────────────
def test_past_application_restores_with_same_decoder_and_contract() -> None:
    # 앱 업데이트 뒤에도 과거 schema 로 태어난 Evidence 가 같은 decoder·contract 로 복원된다.
    ctx = _resolve(_ports())
    again = _resolve(_ports())
    assert ctx.template_structure == again.template_structure
    assert ctx.selection_semantic_contract_id == again.selection_semantic_contract_id
