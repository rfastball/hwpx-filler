"""S6-05(#812) managed 생성 파이프라인 — payload→VDR→gate→delivery 수직(실 store).

이 모듈은 판정을 만들지 않고 이어 붙인다: 검증·시작 자격·안착의 실패가 각자의 어휘로
전파되고, 어느 갈래도 write 를 남기지 않거나(사전·취소) 항목별 원자임을 실측한다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.application.candidate_revision import blob_digest
from hwpxfiller.application.execution_contract_set import execution_basis_digest
from hwpxfiller.application.generation_delivery import (
    WRITE_NEW,
    CurrentResolvedDelivery,
    CurrentResolvedDeliveryItem,
)
from hwpxfiller.domain.raw_data_record import (
    RawRecordCaptureProvenance,
    SourceText,
    build_raw_record_snapshot,
)
from hwpxfiller.external.delivery_coordinator import DeliveryCompleted, DeliveryRefused
from hwpxfiller.external.runtime_capability import admitted_runtime_conformance_registry
from hwpxfiller.webapp.managed_generation import (
    RECORD_VALIDATION_BLOCKED,
    ManagedReadBackFailed,
    ManagedRunCancelled,
    ManagedRunRefused,
    run_managed_generation,
)

from tests._materialization_case import AT, WORK, WS, _build_case, _one_of_two
from tests.test_materialization_runner import _seed_authority

_PROV = RawRecordCaptureProvenance(
    source_adapter_contract_id="excel-adapter/v1", captured_at=AT
)


def _snapshot(identity: str, 이름: str, 금액열: str):
    return build_raw_record_snapshot(
        source_schema_keys=["이름", "금액열"],
        source_values=[("이름", SourceText(이름)), ("금액열", SourceText(금액열))],
        record_identity=identity,
        capture_provenance=_PROV,
    )


def _resolved(out, *names: str) -> CurrentResolvedDelivery:
    return CurrentResolvedDelivery(
        exact_pattern="공고서",
        captured_delivery_clock=AT,
        output_directory=str(out),
        collision_policy="ADD_SUFFIX",
        ordered_items=tuple(
            CurrentResolvedDeliveryItem(
                record_identity=f"rec-{ordinal}", item_ordinal=ordinal,
                resolved_output_relative_path=name, collision_disposition=WRITE_NEW,
            )
            for ordinal, name in enumerate(names)
        ),
    )


def _kit(tmp_path):
    case = _build_case(_one_of_two())
    _seed_authority(tmp_path, case)
    registry, manifest = admitted_runtime_conformance_registry()
    basis = execution_basis_digest(case.plan.execution_basis)
    out = tmp_path / "delivery"
    out.mkdir()
    return case, registry, manifest, basis, out


def _run(case, registry, manifest, basis, out, tmp_path, snapshots, names, **over):
    kw = dict(
        root=tmp_path,
        workspace_instance_id=WS,
        work_authority_id=WORK,
        plan_payload=case.plan,
        ordered_raw_snapshots=snapshots,
        resolved_delivery=_resolved(out, *names),
        validated_at=AT,
        runtime_registry=registry,
        runtime_capability_manifest_digest=manifest.runtime_capability_manifest_digest,
        current_basis_digest_reader=lambda: basis,
    )
    kw.update(over)
    return run_managed_generation(**kw)


# ═══ 수직: record 2건이 실제 HWPX 파일 2개로 앉는다 ═══════════════════════════════════
def test_two_records_deliver_two_distinct_documents(tmp_path) -> None:
    case, registry, manifest, basis, out = _kit(tmp_path)
    progress: list[tuple[int, int]] = []
    result = _run(
        case, registry, manifest, basis, out, tmp_path,
        [_snapshot("r1", "홍길동", "1000"), _snapshot("r2", "김철수", "2000")],
        ["공고서-001.hwpx", "공고서-002.hwpx"],
        on_progress=lambda done, total: progress.append((done, total)),
    )
    assert isinstance(result, DeliveryCompleted), result
    first = (out / "공고서-001.hwpx").read_bytes()
    second = (out / "공고서-002.hwpx").read_bytes()
    assert first != second  # record 값이 실제로 각 문서에 들어갔다
    # 앉은 문서를 다시 열어 각 record 의 logical 값이 실제 필드에 들어갔는지 되읽는다.
    from hwpxcore.package import HwpxPackage
    from hwpxfiller.external.materialization_conformance import _read_field_values

    assert dict(_read_field_values(HwpxPackage.from_bytes(first)))["성명"] == "홍길동"
    assert dict(_read_field_values(HwpxPackage.from_bytes(second)))["성명"] == "김철수"
    assert blob_digest(first) == result.delivered[0].output_digest
    assert blob_digest(second) == result.delivered[1].output_digest
    assert progress == [(1, 2), (2, 2)]


# ═══ 되읽기 검증(S7-01 · #823 — #818 회수) ═══════════════════════════════════════════════
def test_read_back_failure_is_a_distinct_state_that_keeps_delivered_facts(
    tmp_path, monkeypatch
) -> None:
    """되읽기 거절은 완주·중단 어느 쪽도 아니다 — 안착 사실은 그대로 실려 온다.

    관찰 커널 자체의 진실은 ``test_artifact_observation`` 이 실 파일로 소유한다. 여기는
    배선을 잰다: 완주 뒤 delivered 순서로 관찰이 돌고, 첫 거절에서 그 항목의 ordinal 과
    사유가 재조립 없이 실려 나온다.
    """
    import hwpxfiller.webapp.managed_generation as mg
    from hwpxfiller.external.artifact_observation import (
        ARTIFACT_DIGEST_MISMATCH,
        ArtifactObservationRefused,
        ObservedArtifact,
    )

    case, registry, manifest, basis, out = _kit(tmp_path)
    seen: list[str] = []

    def fake_observe(*, absolute_path: str, recorded_digest: str):
        seen.append(absolute_path)
        if len(seen) == 1:  # 첫 문서는 관찰이 서고, 둘째에서 사건이 난다
            from pathlib import Path

            from hwpxcore.package import HwpxPackage

            data = Path(absolute_path).read_bytes()
            return ObservedArtifact(
                absolute_path=absolute_path, output_digest=recorded_digest,
                exact_bytes=data, package=HwpxPackage.from_bytes(data),
            )
        return ArtifactObservationRefused(
            ARTIFACT_DIGEST_MISMATCH, f"{absolute_path} 의 내용이 안착 기록과 다르다"
        )

    monkeypatch.setattr(mg, "observe_delivered_artifact", fake_observe)
    result = _run(
        case, registry, manifest, basis, out, tmp_path,
        [_snapshot("r1", "홍길동", "1000"), _snapshot("r2", "김철수", "2000")],
        ["공고서-001.hwpx", "공고서-002.hwpx"],
    )

    assert isinstance(result, ManagedReadBackFailed), result
    assert result.code == ARTIFACT_DIGEST_MISMATCH  # 커널 사유의 재진술(재조립 0)
    assert result.failed_item_ordinal == 1
    assert [doc.relative_path for doc in result.delivered] == [
        "공고서-001.hwpx", "공고서-002.hwpx"
    ]
    # 안착 사실은 유효하다 — 파일 둘 다 disk 에 남아 있고 아무것도 되돌리지 않았다.
    assert sorted(p.name for p in out.iterdir()) == ["공고서-001.hwpx", "공고서-002.hwpx"]
    assert seen == [str(out / "공고서-001.hwpx"), str(out / "공고서-002.hwpx")]


# ═══ 거절 갈래 — 전부 write 0 ═════════════════════════════════════════════════════════
def test_record_validation_blocked_refuses_before_any_write(tmp_path) -> None:
    case, registry, manifest, basis, out = _kit(tmp_path)
    bad = build_raw_record_snapshot(
        source_schema_keys=["금액열"],  # 필수 source 「이름」 누락 — 준비↔실행 사이 이동의 재현
        source_values=[("금액열", SourceText("1000"))],
        record_identity="r1",
        capture_provenance=_PROV,
    )
    result = _run(case, registry, manifest, basis, out, tmp_path, [bad], ["a.hwpx"])
    assert isinstance(result, ManagedRunRefused)
    assert result.code == RECORD_VALIDATION_BLOCKED
    assert list(out.iterdir()) == []


def test_stale_basis_refusal_reaches_delivery_as_write_zero(tmp_path) -> None:
    case, registry, manifest, basis, out = _kit(tmp_path)
    result = _run(
        case, registry, manifest, basis, out, tmp_path,
        [_snapshot("r1", "홍길동", "1000")], ["a.hwpx"],
        current_basis_digest_reader=lambda: "sha256:" + "f" * 64,
    )
    assert isinstance(result, DeliveryRefused)
    assert result.code == "DIGEST_MISMATCH"  # gate 거절의 재진술(재조립 0)
    assert list(out.iterdir()) == []


def test_cancel_at_record_boundary_writes_nothing(tmp_path) -> None:
    case, registry, manifest, basis, out = _kit(tmp_path)
    cancels = iter([False, True])  # record 1 뒤에 취소
    result = _run(
        case, registry, manifest, basis, out, tmp_path,
        [_snapshot("r1", "홍길동", "1000"), _snapshot("r2", "김철수", "2000")],
        ["a.hwpx", "b.hwpx"],
        cancel_requested=lambda: next(cancels),
    )
    assert isinstance(result, ManagedRunCancelled)
    assert (result.attempted, result.total) == (1, 2)
    assert list(out.iterdir()) == []  # delivery 전 취소 — write 0(legacy 와 다름을 명시)


# ═══ 잔존 구간 표기 검문(S8-F1 · #852 — S8-99 감사 F-1) ══════════════════════════════
def test_uncompiled_structure_notation_refuses_the_managed_run(tmp_path) -> None:
    """slot-bearing managed 실행도 미변환 구간 표기를 통과시키지 않는다 — write 0.

    감사 재현: 컴파일된 슬롯을 가진 문서에 새 표기(마커 2)가 남은 상태. qualification 은
    이 bytes 를 통과시키므로(진단 0 · execution_structure 성립) 검문이 없으면 모든 선택지와
    마커 텍스트가 그대로 실린 문서가 만들어진다. 다중 슬롯 문서에서 한 슬롯만 「표기로
    풀기」 하면 제품이 스스로 이 상태를 만든다.
    """
    from dataclasses import replace

    from hwpxfiller.application.slotless_run_bridge import STRUCTURE_NOTATION_UNCOMPILED
    from hwpxfiller.gui.mapping_state import STRUCTURE_NOTATION_BLOCK_MESSAGE
    from hwpxfiller.webapp.screen_job import _ADMISSION_REJECT_TEXT

    spec = replace(
        _one_of_two(), notation_lines=("{{#항목 특약 특약 사항}}", "{{/항목}}")
    )
    case = _build_case(spec)
    _seed_authority(tmp_path, case)
    registry, manifest = admitted_runtime_conformance_registry()
    out = tmp_path / "delivery"
    out.mkdir()

    result = _run(
        case, registry, manifest,
        execution_basis_digest(case.plan.execution_basis), out, tmp_path,
        [_snapshot("r1", "홍길동", "1000")], ["공고서-001.hwpx"],
    )

    assert isinstance(result, ManagedRunRefused), result
    assert result.code == STRUCTURE_NOTATION_UNCOMPILED
    assert "2건" in result.detail  # 스캐너 단일 출처 수치의 재진술
    assert list(out.iterdir()) == []  # 검문은 안착 전이다 — write 0
    # 같은 차단을 같은 문장으로: legacy admission 과 managed 거절이 한 맵을 탄다.
    assert _ADMISSION_REJECT_TEXT[result.code] == STRUCTURE_NOTATION_BLOCK_MESSAGE


def test_marker_free_slot_bearing_run_passes_the_notation_gate(tmp_path) -> None:
    """양성 대조 — 마커 0 slot-bearing 은 검문에 걸리지 않는다(항상 빨강 금지)."""
    case, registry, manifest, basis, out = _kit(tmp_path)
    result = _run(
        case, registry, manifest, basis, out, tmp_path,
        [_snapshot("r1", "홍길동", "1000")], ["공고서-001.hwpx"],
    )
    assert isinstance(result, DeliveryCompleted), result


def test_foreign_plan_against_this_authority_fails_closed(tmp_path) -> None:
    # 다른 작업에서 봉인된 payload 를 이 authority root 에 대고 실행하면 조달이 loud 하게
    # 닫힌다(candidate blob 부재) — write 0. 조용한 혼선 경로가 없음을 실측한다.
    from hwpxfiller.external.candidate_store import ObjectNotFound

    from tests._materialization_case import _slotless_case

    case, registry, manifest, basis, out = _kit(tmp_path)
    foreign = _build_case(_slotless_case())
    snapshot = build_raw_record_snapshot(
        source_schema_keys=["이름"],
        source_values=[("이름", SourceText("홍길동"))],
        record_identity="r1",
        capture_provenance=_PROV,
    )
    with pytest.raises(ObjectNotFound):  # candidate blob 조달 실패 — loud
        _run(
            case, registry, manifest, basis, out, tmp_path,
            [snapshot], ["a.hwpx"],
            plan_payload=foreign.plan,
            current_basis_digest_reader=lambda: execution_basis_digest(
                foreign.plan.execution_basis
            ),
        )
    assert list(out.iterdir()) == []
