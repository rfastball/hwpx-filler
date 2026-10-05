"""만든 문서 「내용 보기」(산출물 관찰 시트)의 열림 상태와 보기 원료를 소유한다(S7-03 · #825, #1138).

면이 그리는 것은 **생성 후** 실물이다. 겨눔의 정체는 이 세션이 배달한 문서의 ``ordinal`` 하나뿐이고
웹은 경로·파일명을 넘기지 못한다 — 어느 파일의 어느 bytes 를 보일지는 여기서 정한다.

열기(``artifact_open``)는 안착 파일을 커널로 다시 관찰해 성립/거절을 스냅샷 상태로 세운다.
보기 원료(``artifact_content``)는 **열린 면의 문서만** 다시 관찰해 그 검증된 bytes 를 보기 전용
렌더러(rhwp)에 넘긴다. 세션은 bytes 를 캐시하지 않으므로 그사이 파일이 바뀌었으면 원료 대신 그
거절을 그대로 낸다 — 검증되지 않은 bytes 는 화면의 원료도 못 된다(「다른 이름으로 저장」과 같은 결).
"""

from __future__ import annotations

import base64
from collections.abc import Callable

from ..external.artifact_observation import (
    ArtifactObservationRefused,
    ObservedArtifact,
    observe_delivered_artifact,
)
from ..external.delivery_coordinator import DeliveredDocument

ARTIFACT_NOT_IN_SESSION = "ARTIFACT_NOT_IN_SESSION"
ARTIFACT_OBSERVED = "observed"

_NOT_IN_SESSION_DETAIL = (
    "이 문서는 지금 세션의 생성 결과에 없습니다. "
    "문서를 다시 만든 뒤에 내용을 볼 수 있습니다."
)


def _closed_view() -> dict:
    return {"open": False, "ordinal": -1, "filename": "", "status": "", "detail": ""}


def _observe(
    ordinal: int, document: DeliveredDocument | None
) -> "tuple[dict, ObservedArtifact | None]":
    """배달 문서 하나를 다시 관찰해 (열린 면 상태, 관찰 결과)를 낸다. 거절이면 관찰 결과는 없다."""
    if document is None:
        view = {"open": True, "ordinal": ordinal, "filename": "",
                "status": ARTIFACT_NOT_IN_SESSION, "detail": _NOT_IN_SESSION_DETAIL}
        return view, None
    observed = observe_delivered_artifact(
        absolute_path=document.absolute_path,
        recorded_digest=document.output_digest,
    )
    view = {"open": True, "ordinal": ordinal, "filename": document.relative_path,
            "status": ARTIFACT_OBSERVED, "detail": ""}
    if isinstance(observed, ArtifactObservationRefused):
        return {**view, "status": observed.code, "detail": observed.detail}, None
    return view, observed


class ArtifactViewSession:
    """관찰 시트 하나의 열림 상태 — 배달 좌표의 수명은 런 조정자가 정하고 여기는 그 좌표만 읽는다."""

    def __init__(self, delivered: Callable[[int], DeliveredDocument | None]) -> None:
        self._delivered = delivered
        self.view: dict | None = None

    def payload(self) -> dict:
        return _closed_view() if self.view is None else dict(self.view)

    def _do_artifact_open(self, p: dict) -> dict:
        """배달 문서를 디스크에서 다시 관찰하고 실패도 열린 시트에서 재진술한다."""
        ordinal = int(p["ordinal"])
        self.view, _ = _observe(ordinal, self._delivered(ordinal))
        return {"ok": True}

    def _do_artifact_close(self, p: dict) -> None:
        self.view = None

    def _do_artifact_content(self, p: dict) -> dict:
        """열린 면의 문서를 다시 관찰해 검증된 bytes(base64)를 보기 원료로 낸다.

        열린 면이 없거나 관찰이 서 있지 않으면 원료 대신 그 상태를 낸다. 질의라 면 상태를 바꾸지
        않는다 — 그사이 파일이 바뀐 거절은 응답으로만 말하고, 다음 열기가 상태를 다시 세운다.
        """
        view = self.payload()
        if not view["open"] or view["status"] != ARTIFACT_OBSERVED:
            status = view["status"] or ARTIFACT_NOT_IN_SESSION
            detail = view["detail"] or _NOT_IN_SESSION_DETAIL
            return {"ok": False, "ordinal": view["ordinal"], "status": status, "detail": detail}
        ordinal = int(view["ordinal"])
        current, observed = _observe(ordinal, self._delivered(ordinal))
        if observed is None:
            return {"ok": False, "ordinal": ordinal, "status": current["status"],
                    "detail": current["detail"]}
        content = base64.b64encode(observed.exact_bytes).decode("ascii")
        return {"ok": True, "ordinal": ordinal, "filename": current["filename"], "content": content}

    _do_artifact_content.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다


__all__ = ["ARTIFACT_NOT_IN_SESSION", "ARTIFACT_OBSERVED", "ArtifactViewSession"]
