"""실행 보고서 조립과 **판정**(N-11A · #423).

판정을 순수 함수로 떼어 놓는 이유는 하나다 — 이 층의 음성 대조를 **앱 없이** 세울 수 있어야
하기 때문이다. "생성 결과가 0건이면 PNG 가 14장 있어도 실패한다"는 완료 조건은 조작한 보고서
하나로 재현되고, 그 재현은 WebView2 도 Windows 도 요구하지 않는다.

보고서에는 **무엇으로 잰 실행인지**가 실린다(commit·artifact id·창 크기·DPI·파일 목록·소요).
스크린샷은 눈검증 증거이므로 그것이 어느 산출물에서 나왔는지 적히지 않으면 나중에 대조할
좌표가 없다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from hwpxfiller.gui.tutorial_state import (
    COMPLETION_TITLE_ALL,
    COMPLETION_TITLE_STANDARD,
    STEPS as TUTORIAL_STEPS,
)

from .scenario import (
    CAPTURE_POINTS,
    DATA_ASSETS,
    EXPECTED_HWPX,
    HWPX_ASSETS,
    ONBOARDING_ROWS,
    TXT_ASSETS,
)

#: 온보딩 설치가 세워야 하는 수 — 이름 목록의 정본은 ``external/example_pack`` 이다.
EXPECTED_EXAMPLE_TEMPLATES = len(HWPX_ASSETS) + len(TXT_ASSETS)
EXPECTED_EXAMPLE_DATA = len(DATA_ASSETS)
#: 기본 티어가 만들어야 하는 문서 수(``계약목록.csv`` 3행).
EXPECTED_ONBOARDING_HWPX = ONBOARDING_ROWS


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: "str | None" = None
    failures: "tuple[str, ...]" = ()

    def as_dict(self) -> dict:
        return {"ok": self.ok, "reason": self.reason, "failures": list(self.failures)}


def build(
    *,
    phase: str,
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
        "phase": phase,
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


def environment_verdict(reason: str) -> Verdict:
    """환경 실패의 판정 — **판정하지 않았다는 판정**(#460).

    실패 목록이 비는 것이 이 함수의 요점이다. 창이 뜨지 못한 실행에는 제품에 대해 말할 수 있는
    것이 없고, 그런데도 :func:`judge` 를 돌리면 빈 관측이 「HWPX 생성 0건」·「미리보기 미승인」
    같은 **제품 언어 7줄**로 번역돼 나온다. 그 7줄은 전부 참이지만 전부 파생이라, 로그를 읽는
    쪽(특히 무인 판정)은 환경 사고를 제품 회귀로 읽는다.

    한 줄로 말한다: 무엇이 환경이었는지만.
    """
    return Verdict(False, reason, ())


def judge(report: dict, *, mode: str) -> Verdict:
    """보고서만 보고 성패를 가른다 — 픽셀이 아니라 **실물**이 판정 근거다."""
    failures: "list[str]" = []
    observed = report.get("observations") or {}

    phase = report.get("phase")
    if phase == "restart":
        restart = observed.get("sx05_restart") or {}
        durable = restart.get("durable") or {}
        absent = restart.get("session_absent") or {}
        if durable.get("job") != "발주요청서":
            failures.append("restart 뒤 명시 재선택한 durable Work가 복원되지 않았습니다")
        binding = durable.get("binding") or {}
        # U3-03(#876): 수리된 Binding 의 current meaning 은 「활성 누름틀로 남되 조치 목록에는
        # 없다」로 관찰된다 — 「입력이 필요한 항목」이 조치 필요만 싣게 됐기 때문이다.
        if (
            not durable.get("selections")
            or binding.get("active_field") is not True
            or binding.get("pending_action") is not False
        ):
            failures.append("restart 뒤 S4 intent/Binding current meaning이 복원되지 않았습니다")
        if not absent or not all(absent.values()):
            failures.append("restart 뒤 session-only 상태가 거짓 복원됐습니다")
        # U3-07(#880): 마지막 사용 데이터는 첫 화면에 이미 서 있다. 선택 0건·사유 문구 부재가
        # 「손으로 마운트한 것과 같은 세션 상태로 성사됐다」를 함께 말한다.
        if restart.get("data_restored") != {
            "has_data": True, "selected_count": 0, "notice": None
        }:
            failures.append("restart 뒤 마지막 사용 데이터가 자동 마운트되지 않았습니다")
        if restart.get("filesystem_before") != restart.get("filesystem_after"):
            failures.append("restart 관찰 중 filesystem이 바뀌었습니다")
        if report.get("shots") != []:
            failures.append("restart phase가 legacy capture 대본을 다시 실행했습니다")
        if failures:
            return Verdict(False, f"{len(failures)}건이 restart 계약과 어긋났습니다", tuple(failures))
        return Verdict(True)
    if phase == "onboarding":
        return _judge_onboarding(report)
    if phase not in ("legacy", "journey"):
        return Verdict(False, f"알 수 없거나 빠진 live phase: {phase!r}", ("phase 계약 위반",))

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

    if phase == "journey":
        sx = observed.get("sx05") or {}
        for hypothesis in ("H1", "H2", "H3", "H4", "H5", "H6", "H7"):
            if not sx.get(hypothesis):
                failures.append(f"SX-05 {hypothesis} actual-shell evidence가 없습니다")
        pixel = (sx.get("H1") or {}).get("pixel") or {}
        if not pixel.get("sha256") or pixel.get("unstable") is not False:
            failures.append("H1 actual pixel evidence가 없거나 불안정합니다")
        # S6-05(#812) H6 극성 전환: managed create 가 실제로 문서를 앉힌다 — before==after 는
        # 이제 「클릭이 조용히 무반응」이라는 결함의 신호다(계획된 문서 실존은 시나리오가 잰다).
        h6 = sx.get("H6") or {}
        if h6.get("filesystem_before") == h6.get("filesystem_after"):
            failures.append("H6 managed create가 filesystem을 바꾸지 못했습니다")
        if (sx.get("H7") or {}).get("work_race") != "B_WON":
            failures.append("H7 Work A/B race에서 latest Work B가 이기지 않았습니다")

    if failures:
        return Verdict(False, f"{len(failures)}건이 계약과 다릅니다", tuple(failures))
    return Verdict(True)


def _judge_onboarding(report: dict) -> Verdict:
    """온보딩 여정(#895)의 판정 — 대본이 돌려준 **수치**를 다시 센다.

    대본이 이미 단언한 것을 여기서 또 보는 이유는 층이 다르기 때문이다: 대본의 단언은 실행
    중에만 살아 있고, 이 함수는 **보고서만 보고** 판정하므로 앱 없이 음성 대조를 세울 수 있다
    (모듈 머리말). 「관측이 통째로 비었는데 초록」은 그 대조가 없으면 잡히지 않는다.
    """
    failures: "list[str]" = []
    facts = (report.get("observations") or {}).get("onboarding") or {}
    if not facts:
        return Verdict(False, "온보딩 관측이 비었습니다", ("온보딩 대본이 아무것도 남기지 않았습니다",))

    expected_steps = [str(step.milestone) for step in TUTORIAL_STEPS]
    if facts.get("achieved") != expected_steps:
        failures.append(
            f"체크리스트 완주가 아닙니다: {facts.get('achieved')} (기대 {expected_steps})"
        )
    if facts.get("all_complete") is not True:
        failures.append("튜토리얼 스냅샷이 전체 완주를 말하지 않습니다")
    tiers = facts.get("tiers") or {}
    unfinished = sorted(tier for tier in ("basic", "applied", "advanced", "deep") if not tiers.get(tier))
    if unfinished:
        failures.append(f"졸업하지 못한 티어: {unfinished}")

    install = facts.get("install") or {}
    if install.get("templates") != EXPECTED_EXAMPLE_TEMPLATES:
        failures.append(
            f"설치된 예제 템플릿 {install.get('templates')!r}건"
            f" (기대 {EXPECTED_EXAMPLE_TEMPLATES}건)"
        )
    if install.get("pinned") != EXPECTED_EXAMPLE_DATA:
        failures.append(
            f"고정된 예제 데이터 {install.get('pinned')!r}건 (기대 {EXPECTED_EXAMPLE_DATA}건)"
        )
    if install.get("grouped") is not True:
        failures.append("설치한 템플릿이 예제 그룹으로 묶이지 않았습니다")
    # D1: 누르기 전에는 홈에 아무것도 쓰지 않는다 — 대본이 census 를 실었는지까지 본다.
    if not isinstance(facts.get("home_before_install"), list):
        failures.append("설치 전 홈 census 가 보고서에 없습니다")
    if not facts.get("moment_visible"):
        failures.append("순간 카드가 가시 상태로 관측되지 않았습니다")

    basic = facts.get("basic") or {}
    if basic.get("documents") != EXPECTED_ONBOARDING_HWPX:
        failures.append(
            f"기본 티어 생성 {basic.get('documents')!r}건 (기대 {EXPECTED_ONBOARDING_HWPX}건)"
        )
    if basic.get("approval_rearmed") is not False:
        failures.append("두 번째 바퀴에 규칙축 승인이 다시 섰습니다(작업당 1회 계약 위반)")
    if not (basic.get("second_run") or {}).get("overwrite_confirmed"):
        failures.append("같은 이름 파일을 덮어쓰는데 확인 왕복이 없었습니다")

    applied = facts.get("applied") or {}
    if not str(applied.get("copied") or "").startswith("1 /"):
        failures.append(f"TXT 복사 카운터가 서지 않았습니다: {applied.get('copied')!r}")
    if applied.get("selected_after_swap") != 0:
        failures.append("데이터 교체 뒤 선택이 0건에서 재시작하지 않았습니다")
    if not applied.get("blank_marker"):
        failures.append("빈 값 표식이 확인 면에서 관측되지 않았습니다")
    # T14 는 「단계가 체크됐다」로 재지 않는다(#908): 퍼지 제안 임계가 다시 낮아지면
    # `계약보증금` 이 `계약금액` 에 자동 결속돼 게이트가 **서지 않은 채** 저장이 성립한다.
    # 그 갈래가 조용히 초록이면 이 게이트는 잘못된 열이 결속되는 것을 못 본다.
    if applied.get("empty_confirm_gate") is not True:
        failures.append("저작측 결핍(비움 확정) 게이트가 서지 않았습니다")

    deep = facts.get("deep") or {}
    if not deep.get("fresh_digests"):
        failures.append("갈래를 바꾼 생성이 앞선 산출과 다른 문서를 내지 않았습니다")

    # 수명주기(#918 D5) — 완주가 「다음 걸음」을 계속 가리키지 않고, 심화가 **명시 초점**으로만
    # 열리며, 초점을 놓으면 전체 완주가 표준 완주와 다른 말을 하는가. 대본은 이 국면들을
    # 관측만 하므로, 그것이 계약이 되는 자리는 여기다(관측만 하고 안 보면 계약이 아니다).
    lifecycle = facts.get("lifecycle") or {}
    for label, key, expected in (
        ("표준 완주", "standard_phase", "complete"),
        ("고급 되짚기", "advanced_focus_phase", "focus"),
        ("초점 해제 뒤 완주 자리", "refocus_phase", "complete"),
        ("심화 진입", "deep_focus_phase", "focus"),
        ("전체 완주", "final_phase", "complete"),
    ):
        if lifecycle.get(key) != expected:
            failures.append(
                f"{label} 국면이 {expected!r} 가 아닙니다: {lifecycle.get(key)!r}"
            )
    if lifecycle.get("deep_entry") != "focus_picker":
        failures.append(
            f"심화 진입이 명시 초점 선택이 아닙니다: {lifecycle.get('deep_entry')!r}"
        )
    # 문안 둘은 서로 달라야 한다 — 표준 완주가 「모든 단계」를 말하면 남은 선택 과정이 없다고
    # 거짓말하는 것이고, 전체 완주가 표준 문안을 말하면 심화를 걸은 사실이 사라진다.
    if lifecycle.get("standard_title") != COMPLETION_TITLE_STANDARD:
        failures.append(
            f"완주 자리가 표준 완주 문안을 말하지 않습니다 — {lifecycle.get('standard_title')!r}"
        )
    if lifecycle.get("final_title") != COMPLETION_TITLE_ALL:
        failures.append(
            f"초점 해제 뒤 전체 완주 문안이 서지 않았습니다 — {lifecycle.get('final_title')!r}"
        )

    removal = facts.get("removal") or {}
    if removal.get("templates_left") != 0 or removal.get("pinned_left") != 0:
        failures.append(
            f"제거 뒤 잔존 — 템플릿 {removal.get('templates_left')!r}건 ·"
            f" 고정 {removal.get('pinned_left')!r}건"
        )
    if removal.get("files_left"):
        failures.append(f"제거 뒤 예제 자산 파일이 남았습니다: {removal['files_left']}")
    if int(removal.get("missing_template_jobs") or 0) < 1:
        failures.append("제거 뒤 끊긴 작업 경보가 서지 않았습니다(정직성 표면 부재)")

    if report.get("shots") != []:
        failures.append("onboarding phase 가 legacy capture 대본을 다시 실행했습니다")

    if failures:
        return Verdict(False, f"{len(failures)}건이 온보딩 계약과 어긋났습니다", tuple(failures))
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
        seal = json.loads((artifact.root / "web-artifact-seal.json").read_text(encoding="utf-8"))
        identity["seal_source_commit"] = seal["source"]["commit"]
    except Exception as exc:  # noqa: BLE001 — 정체 부재도 사실이다
        identity["artifact_error"] = repr(exc)
    return identity
