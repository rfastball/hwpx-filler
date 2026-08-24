"""S4-11(#681) slotless run bridge — provenance gate·exact bytes staging·admission.

핵심 음성 대조: 정상 경로가 mutable source 를 읽거나 parse 하지 않고 exact applied Candidate
bytes 만 쓴다(drift·spy-0), provenance UNKNOWN/old·slot-bearing 은 fail-closed.
"""

from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from hwpxfiller.application.candidate_revision import ContentBlob, blob_digest
from hwpxfiller.application.slot_configuration_context import ExactAppliedTemplateInput
from hwpxfiller.application.slot_selection_input import (
    SlotConfigurationSnapshot,
    SlotlessSelectionContext,
)
from hwpxfiller.application.slotless_run_bridge import (
    STRUCTURE_NOTATION_UNCOMPILED,
    AdmittedSlotlessRun,
    SlotlessRunAdmissionError,
    admit_slotless_run,
)
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.host.staged_template import clear_run_staging, stage_exact_applied_bytes

NOW = "2026-08-16T00:00:00Z"
CONTRACT = "slot-selection/v1"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"


def _slotless(app: str = "A1", work: str = "w1") -> SlotlessSelectionContext:
    return SlotlessSelectionContext(
        work_id=work, template_application_id=app, selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version="hwpx-structure-projection-v1",
        template_structure_digest="sha256:struct", source_configuration_version=None,
        declared_selection_digest=None, captured_at=NOW,
    )


def _applied(app: str = "A1", work: str = "w1", digest: str = "sha256:bytes") -> ExactAppliedTemplateInput:
    return ExactAppliedTemplateInput(
        work_id=work, template_application_id=app, revision_id="R1", media="hwpx",
        template_lineage_id="L1", exact_content_digest=digest, canonical_blob_reference="blob:R1",
    )


def _stager(seen: list[str]):
    def _stage(digest: str) -> str:
        seen.append(digest)
        return f"/staged/{digest.replace(':', '_')}.hwpx"
    return _stage


def _no_markers(_path: str) -> int:
    """구간 표기 0 — 순수 게이트 테스트가 겨누는 축이 아닌 입력의 중립값."""
    return 0


# ── pure admission gate ───────────────────────────────────────────────────────
def test_slot_bearing_snapshot_is_not_executable() -> None:
    snap = SlotConfigurationSnapshot(
        work_id="w1", template_application_id="A1", source_configuration_version=1,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version="hwpx-structure-projection-v1",
        effective_selections=None, effective_selection_digest="sha256:eff",
        declared_selection_digest="sha256:dec", template_structure_digest="sha256:s", captured_at=NOW,
    )
    with pytest.raises(SlotlessRunAdmissionError) as e:
        admit_slotless_run(snap, _applied(), "A1", _stager([]), count_structure_markers=_no_markers)
    assert e.value.code == "SLOT_CONFIGURATION_EXECUTION_NOT_AVAILABLE"


def test_unknown_provenance_needs_review() -> None:
    with pytest.raises(SlotlessRunAdmissionError) as e:
        admit_slotless_run(
            _slotless(), _applied(), None, _stager([]),  # None = UNKNOWN
            count_structure_markers=_no_markers,
        )
    assert e.value.code == "NEEDS_CONFIGURATION_REVIEW"


def test_old_application_provenance_needs_configuration() -> None:
    with pytest.raises(SlotlessRunAdmissionError) as e:
        admit_slotless_run(
            _slotless(app="A2"), _applied(app="A2"), "A1", _stager([]),
            count_structure_markers=_no_markers,
        )
    assert e.value.code == "NEEDS_CONFIGURATION"


def test_applied_bytes_from_other_application_rejected() -> None:
    # slotless context 는 A1 인데 applied input 이 A2 를 가리키면 무결성 오류(다른 bytes 실행 금지).
    with pytest.raises(SlotlessRunAdmissionError) as e:
        admit_slotless_run(
            _slotless(app="A1"), _applied(app="A2"), "A1", _stager([]),
            count_structure_markers=_no_markers,
        )
    assert e.value.code == "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR"


def test_non_variant_input_requires_slotless_context() -> None:
    with pytest.raises(SlotlessRunAdmissionError) as e:
        admit_slotless_run(
            object(), _applied(), "A1", _stager([]),  # type: ignore[arg-type]
            count_structure_markers=_no_markers,
        )
    assert e.value.code == "SLOTLESS_SELECTION_CONTEXT_REQUIRED"


def test_allowed_stages_exact_bytes() -> None:
    seen: list[str] = []
    admitted = admit_slotless_run(
        _slotless(), _applied(digest="sha256:exact"), "A1", _stager(seen),
        count_structure_markers=_no_markers,
    )
    assert isinstance(admitted, AdmittedSlotlessRun)
    assert seen == ["sha256:exact"]  # exact applied digest 만 staging (source read 없음)
    assert admitted.template_application_id == "A1"
    assert admitted.exact_content_digest == "sha256:exact"


# ── staging (host) ────────────────────────────────────────────────────────────
class _BlobStore:
    def __init__(self, blob: ContentBlob) -> None:
        self._blob = blob

    def get_blob(self, digest: str) -> ContentBlob:
        assert digest == self._blob.digest
        return self._blob


def test_staging_is_byte_exact_readonly_and_content_addressed(tmp_path: Path) -> None:
    data = b"HWPX-exact-applied-bytes"
    digest = blob_digest(data)
    store = _BlobStore(ContentBlob(digest, "hwpx", data, len(data)))
    path = stage_exact_applied_bytes(store, tmp_path, digest)
    p = Path(path)
    assert p.read_bytes() == data  # byte-exact
    assert blob_digest(p.read_bytes()) == digest  # staged digest == exact_content_digest
    assert digest.replace(":", "_") in p.name and p.suffix == ".hwpx"  # content-addressed
    assert not (p.stat().st_mode & stat.S_IWRITE)  # read-only
    # 두 번째 호출은 같은 경로 재사용(content-addressed).
    assert stage_exact_applied_bytes(store, tmp_path, digest) == path
    clear_run_staging(tmp_path)
    assert not p.exists()


def test_staging_restores_readonly_on_reused_writable_entry(tmp_path: Path) -> None:
    # clear 가 writable 로 두고 unlink 에 실패한 잔존 entry(디지스트는 맞음) 재사용 시
    # read-only 를 다시 걸어야 run-lifetime 불변이 유지된다.
    data = b"correct-bytes"
    digest = blob_digest(data)
    store = _BlobStore(ContentBlob(digest, "hwpx", data, len(data)))
    path = Path(stage_exact_applied_bytes(store, tmp_path, digest))
    import os

    os.chmod(path, path.stat().st_mode | stat.S_IWRITE)  # 실패한 clear 를 흉내
    assert path.stat().st_mode & stat.S_IWRITE  # writable 잔존 확인
    reused = stage_exact_applied_bytes(store, tmp_path, digest)
    assert reused == str(path)
    assert not (path.stat().st_mode & stat.S_IWRITE)  # 재사용도 read-only 로 복원


def test_staging_rewrites_stale_content_addressed_file(tmp_path: Path) -> None:
    data = b"correct-bytes"
    digest = blob_digest(data)
    store = _BlobStore(ContentBlob(digest, "hwpx", data, len(data)))
    staging = tmp_path / "run_staging"
    staging.mkdir()
    stale = staging / f"{digest.replace(':', '_')}.hwpx"
    stale.write_bytes(b"stale-wrong")  # 같은 이름·틀린 bytes
    path = stage_exact_applied_bytes(store, tmp_path, digest)
    assert Path(path).read_bytes() == data  # 재작성됨


def test_clear_run_staging_when_absent_is_noop(tmp_path: Path) -> None:
    clear_run_staging(tmp_path / "nope")  # 부재 → 조용히 반환


def test_staging_rejects_store_returning_wrong_digest(tmp_path: Path) -> None:
    # store 가 요청과 다른 content 의 blob 을 돌려주면 fail-closed(다른 bytes staging 금지).
    other = b"unrelated-content"
    blob = ContentBlob(blob_digest(other), "hwpx", other, len(other))
    wrong = SimpleNamespace(get_blob=lambda d: blob)  # 요청 digest 를 무시하고 다른 blob 반환
    with pytest.raises(ValueError, match="다르다"):
        stage_exact_applied_bytes(wrong, tmp_path, "sha256:requested-but-absent")


# ── fence-first admission (end-to-end wiring) ─────────────────────────────────
def _hwpx_bytes(*paragraphs: str) -> bytes:
    """실 HWPX bytes — staged 사본을 **열어서** 검문하는 admission 이 파싱할 수 있어야 한다.

    S8-04 전에는 이 픽스처가 아무 bytes 나 써도 됐다(admission 이 bytes 를 열지 않았다).
    구간 표기 검문이 들어온 지금은 열리지 않는 bytes 자체가 무결성 거절 사유다.
    """
    body = "".join(
        f'<hp:p><hp:run charPrIDRef="0"><hp:t>{text}</hp:t></hp:run></hp:p>'
        for text in paragraphs
    )
    xml = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{body}</hs:sec>'
    ).encode("utf-8")
    return HwpxPackage(
        entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}
    ).to_bytes()


_BYTES = _hwpx_bytes("applied-A17-exact-bytes")
_DIGEST = blob_digest(_BYTES)
#: 필드 없이 구간 표기만 남은 실행 bytes(S8-04 음성 대조) — 통과하면 마커가 산출물에 샌다.
_MARKER_BYTES = _hwpx_bytes("{{#항목 특약 특약 사항}}", "특약 본문", "{{/항목}}")
_MARKER_DIGEST = blob_digest(_MARKER_BYTES)


def _fence_fixture(structure, current="A1", *, data: bytes = _BYTES):
    """capture 계열 fake 를 실 digest 로 세운 fence-first 픽스처."""
    from hwpxfiller.application.candidate_revision import TemplateRevision
    from hwpxfiller.application.qualification_evidence import (
        QualificationEvidence,
        build_manifest,
        project_structure,
    )
    from hwpxfiller.application.work_template_state import (
        INITIALIZATION,
        DocumentWork,
        WorkTemplateApplication,
    )

    schema, profile = "hwpx-structure-projection-v1", "hwpx-template-qualification-v1"
    work = DocumentWork("w1", "L1", current, None, 0)
    app = WorkTemplateApplication(
        application_id="A1", work_id="w1", application_epoch=1, pass_evidence_id="E1",
        previous_application_id=None, origin=INITIALIZATION, prepared_change_id=None,
        actor="t", applied_at=NOW,
    )
    evidence = QualificationEvidence(
        evidence_id="E1", attempt_id="AT1", revision_id="R1", qualification_profile_id=profile,
        result="PASS", structure_projection=project_structure(structure, schema),
        diagnostics=(), engine_metadata={}, qualified_at=NOW,
    )
    manifest = build_manifest(
        qualification_profile_id=profile, media="hwpx", adapter_contract_version="a",
        product_rule_version="p", operation_alphabet_version="op",
        projection_schema_version=schema, manifest_payload={"x": 1}, created_at=NOW,
    )
    digest = blob_digest(data)
    revision = TemplateRevision("R1", "L1", "hwpx", digest, "OBS1", NOW)
    blob = ContentBlob(digest, "hwpx", data, len(data))

    work_state = SimpleNamespace(load=lambda w: SimpleNamespace(work=work, applications=(app,)))
    qual = SimpleNamespace(
        get_evidence=lambda e: evidence, get_manifest=lambda p: manifest
    )
    candidate = SimpleNamespace(
        get_revision=lambda r: revision, has_blob=lambda d: d == digest
    )
    candidate_bytes = _BlobStore(blob)
    return work_state, qual, candidate, candidate_bytes


def _structures():
    from hwpxfiller.application.template_qualification import (
        TemplateOption,
        TemplateSlot,
        TemplateStructure,
    )
    slotless = TemplateStructure(slots=())
    slotted = TemplateStructure(slots=(TemplateSlot("s", options=(TemplateOption("o"),)),))
    return slotless, slotted


def test_managed_admission_slotless_allowed_stages_candidate_bytes(tmp_path: Path) -> None:
    from hwpxfiller.external.slot_command_runner import admit_managed_slotless_run
    from hwpxfiller.external.work_configuration_store import WorkSlotConfigurationStore

    slotless, _ = _structures()
    ws, qual, cand, cand_bytes = _fence_fixture(slotless)
    store = WorkSlotConfigurationStore(tmp_path / "cfg")
    provenance = SimpleNamespace(resolve_base_template_application_id=lambda w: "A1")  # current
    admitted = admit_managed_slotless_run(
        store, ws, qual, cand, cand_bytes, provenance, str(tmp_path),
        workspace_instance_id="ws-1", expected_work_authority_id="w1",
        expected_template_application_id="A1", captured_at=NOW,
    )
    # staged bytes 는 Candidate blob 에서 온다(mutable source read 0) — drift 대조.
    assert Path(admitted.staged_template_path).read_bytes() == _BYTES
    assert admitted.exact_content_digest == _DIGEST


def test_managed_admission_blocks_residual_structure_notation(tmp_path: Path) -> None:
    """S8-04 음성 대조 — 실행할 bytes 에 구간 표기가 남았으면 생성 자체가 서지 않는다.

    provenance·무결성·context 는 전부 통과하는 정상 실행이다. 막는 것은 오직 「표기가
    아직 변환되지 않았다」 하나이고, 통과시키면 산출물에 모든 선택지 + 마커 텍스트가 실린다.
    """
    from hwpxfiller.external.slot_command_runner import admit_managed_slotless_run
    from hwpxfiller.external.work_configuration_store import WorkSlotConfigurationStore

    slotless, _ = _structures()
    ws, qual, cand, cand_bytes = _fence_fixture(slotless, data=_MARKER_BYTES)
    store = WorkSlotConfigurationStore(tmp_path / "cfg")
    provenance = SimpleNamespace(resolve_base_template_application_id=lambda w: "A1")
    with pytest.raises(SlotlessRunAdmissionError) as e:
        admit_managed_slotless_run(
            store, ws, qual, cand, cand_bytes, provenance, str(tmp_path),
            workspace_instance_id="ws-1", expected_work_authority_id="w1",
            expected_template_application_id="A1", captured_at=NOW,
        )
    assert e.value.code == STRUCTURE_NOTATION_UNCOMPILED
    assert "2건" in str(e.value)  # 사유를 수치로 재진술한다(여는·닫는 마커 2개)


def test_managed_admission_rejects_unreadable_staged_bytes(tmp_path: Path) -> None:
    """열리지 않는 staged bytes 는 「마커 0」으로 접히지 않고 무결성 오류다(fail-closed)."""
    from hwpxfiller.external.slot_command_runner import admit_managed_slotless_run
    from hwpxfiller.external.work_configuration_store import WorkSlotConfigurationStore

    slotless, _ = _structures()
    ws, qual, cand, cand_bytes = _fence_fixture(slotless, data=b"not-a-hwpx-zip")
    store = WorkSlotConfigurationStore(tmp_path / "cfg")
    provenance = SimpleNamespace(resolve_base_template_application_id=lambda w: "A1")
    with pytest.raises(SlotlessRunAdmissionError) as e:
        admit_managed_slotless_run(
            store, ws, qual, cand, cand_bytes, provenance, str(tmp_path),
            workspace_instance_id="ws-1", expected_work_authority_id="w1",
            expected_template_application_id="A1", captured_at=NOW,
        )
    assert e.value.code == "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR"


def test_managed_admission_unknown_provenance_blocks(tmp_path: Path) -> None:
    from hwpxfiller.external.slot_command_runner import admit_managed_slotless_run
    from hwpxfiller.external.work_configuration_store import WorkSlotConfigurationStore

    slotless, _ = _structures()
    ws, qual, cand, cand_bytes = _fence_fixture(slotless)
    store = WorkSlotConfigurationStore(tmp_path / "cfg")
    provenance = SimpleNamespace(resolve_base_template_application_id=lambda w: None)  # UNKNOWN
    with pytest.raises(SlotlessRunAdmissionError) as e:
        admit_managed_slotless_run(
            store, ws, qual, cand, cand_bytes, provenance, str(tmp_path),
            workspace_instance_id="ws-1", expected_work_authority_id="w1",
            expected_template_application_id="A1", captured_at=NOW,
        )
    assert e.value.code == "NEEDS_CONFIGURATION_REVIEW"


def test_managed_admission_slot_bearing_not_available(tmp_path: Path) -> None:
    # complete 한 Slot 선택이 있어도 S5/S6 전에는 legacy 실행 불가(NOT_AVAILABLE).
    from dataclasses import replace

    from hwpxfiller.application.stored_work_configuration import empty_stored
    from hwpxfiller.application.work_slot_configuration import apply_selections, create_empty
    from hwpxfiller.domain.slot_selection import SlotSelection, SlotSelectionSet
    from hwpxfiller.external.slot_command_runner import admit_managed_slotless_run
    from hwpxfiller.external.work_configuration_store import WorkSlotConfigurationStore

    _, slotted = _structures()
    ws, qual, cand, cand_bytes = _fence_fixture(slotted)
    store = WorkSlotConfigurationStore(tmp_path / "cfg")
    draft = apply_selections(
        create_empty("w1", "A1", NOW), SlotSelectionSet((SlotSelection("s", ("o",)),)), NOW
    )
    base = empty_stored("ws-1", "w1")
    store.create(replace(base, configurations=replace(base.configurations, configurations=(draft,))))
    provenance = SimpleNamespace(resolve_base_template_application_id=lambda w: "A1")
    with pytest.raises(SlotlessRunAdmissionError) as e:
        admit_managed_slotless_run(
            store, ws, qual, cand, cand_bytes, provenance, str(tmp_path),
            workspace_instance_id="ws-1", expected_work_authority_id="w1",
            expected_template_application_id="A1",
            expected_configuration_presence=True, expected_configuration_version=draft.version,
            captured_at=NOW,
        )
    assert e.value.code == "SLOT_CONFIGURATION_EXECUTION_NOT_AVAILABLE"
