"""실행 보고서 조립과 **판정**(N-11A · #423).

판정을 순수 함수로 떼어 놓는 이유는 하나다 — 이 층의 음성 대조를 **앱 없이** 세울 수 있어야
하기 때문이다. "생성 결과가 0건이면 PNG 가 14장 있어도 실패한다"는 완료 조건은 조작한 보고서
하나로 재현되고, 그 재현은 WebView2 도 Windows 도 요구하지 않는다.

보고서에는 **무엇으로 잰 실행인지**가 실린다(commit·artifact id·창 크기·DPI·파일 목록·소요).
스크린샷은 눈검증 증거이므로 그것이 어느 산출물에서 나왔는지 적히지 않으면 나중에 대조할
좌표가 없다.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .scenario import CAPTURE_POINTS, EXPECTED_HWPX


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: "str | None" = None
    failures: "tuple[str, ...]" = ()

    def as_dict(self) -> dict:
        return {"ok": self.ok, "reason": self.reason, "failures": list(self.failures)}


def build(
    *,
    mode: str,
    home: Path,
    observations: dict,
    documents: "list[str]",
    shots: "list[str]",
    unstable: "list[str]",
    geometry: "dict[str, int]",
    window_size: "tuple[int, int]",
    elapsed_s: float,
) -> dict:
    """실행 하나의 사실을 한 봉투로 모은다 — 판정은 하지 않는다."""
    return {
        "mode": mode,
        "home": str(home),
        "source": _source_identity(),
        "window": {"logical_width": window_size[0], "logical_height": window_size[1], **geometry},
        "observations": dict(observations),
        "documents": list(documents),
        "hwpx_generated": len(documents),
        "shots": list(shots),
        "unstable_shots": list(unstable),
        "elapsed_s": round(elapsed_s, 1),
    }


def judge(report: dict, *, mode: str) -> Verdict:
    """보고서만 보고 성패를 가른다 — 픽셀이 아니라 **실물**이 판정 근거다."""
    failures: "list[str]" = []
    observed = report.get("observations") or {}

    generated = report.get("hwpx_generated")
    if generated != EXPECTED_HWPX:
        failures.append(f"HWPX 생성 {generated}건 (기대 {EXPECTED_HWPX}건)")
    if observed.get("hwpx_result_state") != "completed":
        failures.append(f"생성 결과 태가 completed 가 아닙니다: {observed.get('hwpx_result_state')!r}")
    if observed.get("preview_approved") is not True:
        failures.append("생성 값 미리보기 승인이 착지하지 않았습니다")
    copied = str(observed.get("txt_copied") or "")
    if not copied.startswith("1 /"):
        failures.append(f"TXT 복사 카운터가 서지 않았습니다: {copied!r}")
    if observed.get("empty_value_gate_asked") is not True:
        failures.append("빈 값 확정 이름게이트가 묻지 않았습니다")
    if observed.get("empty_value_surfaced") is not True:
        failures.append("작업대에 〈빈 값〉 표면이 서지 않았습니다")

    shots = tuple(report.get("shots") or ())
    if shots != CAPTURE_POINTS:
        failures.append(
            f"캡처 지점이 계약과 다릅니다: {list(shots)} (기대 {list(CAPTURE_POINTS)})"
        )
    if mode == "capture" and report.get("unstable_shots"):
        # 정착하지 못한 프레임은 찢겨 있을 수 있다 — 조용히 문서에 넣지 않는다.
        failures.append(f"정착하지 못한 컷: {report['unstable_shots']}")

    if failures:
        return Verdict(False, f"{len(failures)}건이 계약과 다릅니다", tuple(failures))
    return Verdict(True)


def _source_identity() -> dict:
    """무엇으로 잰 실행인가 — commit 과 봉인된 산출물 정체."""
    identity: dict = {"python": sys.version.split()[0]}
    try:
        identity["commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        identity["commit"] = None
    try:
        from hwpxfiller.webapp import app as webapp_app

        artifact = webapp_app.web_artifact()
        identity["artifact_id"] = artifact.artifact_id
        identity["tree_sha256"] = artifact.tree_sha256
    except Exception as exc:  # noqa: BLE001 — 정체 부재도 사실이다
        identity["artifact_error"] = repr(exc)
    return identity
