"""S7-01(#823) 관찰 커널 — 안착 파일 되읽기 + 기록 digest 대조 + 재파싱.

fixture 는 위조하지 않는다: 실제 managed 파이프라인(:mod:`tests.test_managed_generation` 의
kit)을 돌려 진짜 HWPX 를 disk 에 앉히고, 그 ``DeliveredDocument`` 의 사실 둘로 관찰한다.
음성 셋(부재·변조·손상)은 앉은 파일을 실제로 건드려 세운다 — 거절 코드가 서로 구분됨을
같은 층에서 실측한다.
"""

from __future__ import annotations

from pathlib import Path

from hwpxfiller.external import content_digest, materialization_conformance
from hwpxfiller.external.artifact_observation import (
    ARTIFACT_DIGEST_MISMATCH,
    ARTIFACT_FILE_MISSING,
    ARTIFACT_REPARSE_FAILED,
    ArtifactObservationRefused,
    ObservedArtifact,
    observe_delivered_artifact,
)
from hwpxfiller.external.content_digest import blob_digest
from hwpxfiller.external.delivery_coordinator import DeliveredDocument, DeliveryCompleted

from tests.test_managed_generation import _kit, _run, _snapshot


def _delivered_document(tmp_path: Path) -> DeliveredDocument:
    """실 파이프라인으로 문서 하나를 실제로 앉히고 그 안착 사실을 돌려준다."""
    case, registry, manifest, basis, out = _kit(tmp_path)
    result = _run(
        case, registry, manifest, basis, out, tmp_path,
        [_snapshot("r1", "홍길동", "1000")], ["공고서-001.hwpx"],
    )
    assert isinstance(result, DeliveryCompleted), result
    return result.delivered[0]


# ═══ 성립: 파일에서 읽은 bytes 가 기록과 같고 다시 열린다 ═════════════════════════════════
def test_observation_returns_exact_disk_bytes_and_reparsed_package(tmp_path) -> None:
    doc = _delivered_document(tmp_path)

    observed = observe_delivered_artifact(
        absolute_path=doc.absolute_path, recorded_digest=doc.output_digest
    )

    assert isinstance(observed, ObservedArtifact), observed
    assert observed.absolute_path == doc.absolute_path
    assert observed.output_digest == doc.output_digest
    # D2: 저장·복사의 원료는 재물질화가 아니라 **디스크에서 읽은 그 bytes** 다.
    assert observed.exact_bytes == Path(doc.absolute_path).read_bytes()
    assert blob_digest(observed.exact_bytes) == doc.output_digest
    # 재파싱이 형식으로 성립했다 — 실제 HWPX entries 를 들고 있다.
    assert "Contents/section0.xml" in observed.package.entries


def test_digest_formula_is_one_shared_function(tmp_path) -> None:
    # 산식이 두 자리로 갈라지면 대조 자체가 무의미해진다 — 같은 객체여야 한다.
    assert materialization_conformance.blob_digest is content_digest.blob_digest


# ═══ 음성 셋 — 서로 구분되는 거절 코드 ════════════════════════════════════════════════════
def test_deleted_file_refuses_as_missing(tmp_path) -> None:
    doc = _delivered_document(tmp_path)
    Path(doc.absolute_path).unlink()

    refused = observe_delivered_artifact(
        absolute_path=doc.absolute_path, recorded_digest=doc.output_digest
    )

    assert isinstance(refused, ArtifactObservationRefused)
    assert refused.code == ARTIFACT_FILE_MISSING
    assert doc.absolute_path in refused.detail  # 경로 재진술(조용한 실패 금지)


def test_one_byte_tamper_refuses_as_digest_mismatch(tmp_path) -> None:
    doc = _delivered_document(tmp_path)
    path = Path(doc.absolute_path)
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF  # 크기는 그대로 — 길이만 보는 관찰이면 통과했을 변조다
    path.write_bytes(bytes(data))

    refused = observe_delivered_artifact(
        absolute_path=doc.absolute_path, recorded_digest=doc.output_digest
    )

    assert isinstance(refused, ArtifactObservationRefused)
    assert refused.code == ARTIFACT_DIGEST_MISMATCH
    # 기대·실측을 병기한다 — 조용히 재생성하지 않고 사건으로 낸다(D1).
    assert doc.output_digest in refused.detail
    assert blob_digest(bytes(data)) in refused.detail


def test_intact_digest_but_broken_zip_refuses_as_reparse_failed(tmp_path) -> None:
    # digest 층은 통과시키고 재파싱만 실패시킨다 — 두 코드가 실제로 다른 사건을 가른다.
    doc = _delivered_document(tmp_path)
    corrupt = b"PK\x03\x04 not really an OCF package"
    Path(doc.absolute_path).write_bytes(corrupt)

    refused = observe_delivered_artifact(
        absolute_path=doc.absolute_path, recorded_digest=blob_digest(corrupt)
    )

    assert isinstance(refused, ArtifactObservationRefused)
    assert refused.code == ARTIFACT_REPARSE_FAILED
    assert doc.absolute_path in refused.detail
