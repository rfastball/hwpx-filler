"""안착 문서의 검증된 관찰 커널 (S7-01 · #823).

delivery coordinator 가 disk 에 앉힌 문서를 **다시 파일에서 읽어** 기록된 digest 와 대조하고,
그 bytes 를 OCF package 로 재파싱해서야 「관찰됐다」고 부른다(#820 D1). 성립 경로는 그 하나뿐
이다 — in-memory bytes 대체·조용한 재생성·Projection 대체는 만들지 않는다. 관찰이 서지 않는
경우는 결함이 아니라 **검출해야 할 실세계 사건**(다른 프로그램이 지웠다·동기화 클라이언트가
덮었다·저장 매체가 썩었다)이라, 사유를 재진술한 거절 하나로 낸다.

입력은 :class:`~hwpxfiller.external.delivery_coordinator.DeliveredDocument` 의 사실 둘
(``absolute_path``·``output_digest``)이다 — 그 타입 자체를 import 하지 않아 원장·이력 등 같은
사실을 들고 있는 다른 호출자도 이 커널을 쓸 수 있다.

거절 어휘는 셋뿐이고 서로 겹치지 않는다(#820 §3): 파일이 없다 / 있으나 내용이 기록과 다르다 /
내용은 기록 그대로인데 HWPX 로 열리지 않는다. 파일은 있는데 읽지 못하는 경우(권한·잠금)는
거절이 아니라 예외로 시끄럽게 전파한다 — delivery coordinator 의 IO 실패 처리와 같은 결이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hwpxcore.package import HwpxPackage

from .content_digest import blob_digest

# 안착 기록이 가리키는 경로에 파일이 없다 — 안착 이후 누군가 지웠거나 옮겼다.
ARTIFACT_FILE_MISSING = "ARTIFACT_FILE_MISSING"
# 파일은 있으나 내용이 안착 기록의 digest 와 다르다 — 안착 이후 내용이 바뀌었다.
ARTIFACT_DIGEST_MISMATCH = "ARTIFACT_DIGEST_MISMATCH"
# 내용은 기록 그대로인데 HWPX(OCF ZIP)로 열리지 않는다 — 기록 시점부터 깨져 있었다.
ARTIFACT_REPARSE_FAILED = "ARTIFACT_REPARSE_FAILED"


@dataclass(frozen=True)
class ObservedArtifact:
    """파일에서 읽어 digest 로 확인하고 재파싱까지 통과한 문서 하나.

    ``exact_bytes`` 는 「다른 이름으로 저장」·「복사」(S7-03)의 **유일한 원료**다(#820 D2) —
    그 표면들은 문서를 다시 물질화하거나 재생성하지 않고 이 bytes 를 그대로 옮긴다. 여기 실린
    bytes 는 디스크에서 읽은 것 자체이고 ``output_digest`` 대조를 이미 통과했다.
    """

    absolute_path: str
    output_digest: str
    exact_bytes: bytes
    package: HwpxPackage


@dataclass(frozen=True)
class ArtifactObservationRefused:
    """관찰이 서지 않았다 — 사유는 실측의 재진술이고, 대체 성립 경로는 없다."""

    code: str
    detail: str


def observe_delivered_artifact(
    *, absolute_path: str, recorded_digest: str
) -> "ObservedArtifact | ArtifactObservationRefused":
    """안착 파일을 되읽어 기록 digest 와 대조하고 package 로 재파싱한다."""
    try:
        exact_bytes = Path(absolute_path).read_bytes()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        # 그 밖의 OSError(권한·잠금·디스크 오류)는 잡지 않는다 — 「없다」로 뭉개면 사용자가
        # 원인을 못 고친다. 시끄럽게 전파해 호출자 층이 실패로 드러내게 둔다.
        return ArtifactObservationRefused(
            ARTIFACT_FILE_MISSING, f"안착 기록의 경로에 파일이 없다: {absolute_path}"
        )

    observed_digest = blob_digest(exact_bytes)
    if observed_digest != recorded_digest:
        return ArtifactObservationRefused(
            ARTIFACT_DIGEST_MISMATCH,
            f"{absolute_path} 의 내용이 안착 기록과 다르다: "
            f"기대 {recorded_digest}, 실측 {observed_digest}",
        )

    try:
        package = HwpxPackage.from_bytes(exact_bytes)
    except Exception as exc:  # noqa: BLE001 — 재파싱 실패는 종류를 가리지 않고 한 거절이다.
        return ArtifactObservationRefused(
            ARTIFACT_REPARSE_FAILED,
            f"{absolute_path} 를 HWPX 로 다시 열지 못했다: {type(exc).__name__}: {exc}",
        )

    return ObservedArtifact(
        absolute_path=absolute_path,
        output_digest=recorded_digest,
        exact_bytes=exact_bytes,
        package=package,
    )


__all__ = [
    "ARTIFACT_DIGEST_MISMATCH",
    "ARTIFACT_FILE_MISSING",
    "ARTIFACT_REPARSE_FAILED",
    "ArtifactObservationRefused",
    "ObservedArtifact",
    "observe_delivered_artifact",
]
