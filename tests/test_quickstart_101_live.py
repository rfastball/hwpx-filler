"""Quickstart 101 라이브 게이트 — 실주행과 그 판정의 음성 대조(N-11A · #423).

`scripts/live101/` 하니스는 #426 에서 섰지만 **그것을 돌리는 테스트는 0** 이었다. 그 침묵이
바로 이 이슈의 출발점이다: 캡처 하니스가 몇 달 동안 깨진 채 살아 있었고, 이름을 보는 정적
단언들은 그동안 초록이었다.

층을 둘로 나눈다(`test_web_press_geometry.py` 와 같은 형태).

- **실주행**은 게이트 뒤다(`HWPX_SKIP_GUI_TESTS` 명시 옵트아웃). 실 WebView2 창을 띄워
  101 을 완주하고 **실물**을 판정한다 — 생성된 HWPX 파일 수·복사 카운터·〈빈 값〉 표면.
- **판정과 계약의 음성 대조는 게이트 밖**이다. 창 없이 도는 순수 검사라 옵트아웃 환경에서도
  「생성 0건인데 통과」·「없는 selector 를 timeout 으로 뭉갬」·「dirty 홈 파괴」가 잡힌다.

게이트 밖 층이 있는 이유가 요점이다: 실주행만 두면 GUI 없는 러너에서 이 파일 전체가 조용히
사라지고, 그때 하니스의 판정이 옳은지 아무도 묻지 않는다.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from live101 import driver, report as report_mod  # noqa: E402
from live101.scenario import CAPTURE_POINTS, EXPECTED_HWPX  # noqa: E402
from live101.surface import (  # noqa: E402
    Deadline,
    JS_HELPERS,
    MissingSurface,
    StepTimeout,
    Surface,
    UnexpectedNativeAlert,
)

from hwpxfiller.webapp import boot_budget  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "capture_101_screenshots.py"
EXAMPLE_HOME = REPO_ROOT / "examples" / "quickstart-101"
IMG_DIR = EXAMPLE_HOME / "img"
README = EXAMPLE_HOME / "README.md"

_GUI_GATE = sys.platform != "win32" or bool(os.environ.get("HWPX_SKIP_GUI_TESTS"))
_GATE_REASON = (
    "101 실주행 게이트 — Windows 데스크톱 세션 전용(HWPX_SKIP_GUI_TESTS=1 로 명시 옵트아웃)"
)
# 예산 둘의 **순서가 계약이다**(#430 리뷰). 바깥 시한(`subprocess.run`)이 안쪽 하드 스톱보다
# 촘촘하면 CLI 가 먼저 죽어 드라이버의 구조화된 착지가 통째로 사라지고, 남는 것은 맨
# `TimeoutExpired` 하나다 — 보고서도, 실패 항목도, 매달림 스택도 없다. #427 이 하니스 층에서
# 고친 것과 **같은 형상**이라 여기서도 안쪽이 먼저 물게 파생시킨다.
#
# 안쪽 예산은 **매달림 전용**이다(#477). 종전 300초는 "로컬 실측 9초의 30배면 느린 러너를
# 안 문다"는 계산이었는데, 공유 러너가 그 30배를 실제로 넘었다 — PR #476 CI 에서 정상 여정이
# 하드 스톱(360초)까지 밀렸고 코드 무변경 재실행이 초록이었다. 느린 러너를 잡는 값은 제품에
# 대해 아무것도 말하지 않으므로, 이 값은 「명백히 멈춘 것」만 잡게 벌린다: 관측 최악 완주
# 360초를 훨씬 웃돌고(약 1.7배·로컬 실측의 60배), driver.RUN_BUDGET_S 관대한 천장(900초)
# 아래다. 성능(정상 실행이 얼마나 빠른가)은 아래 양성 대조가 **보고**한다 — 차단하지 않는다.
#
# 추정치로 잡지 않는 이유가 있다 — 종전 driver 주석의 "2~4분"은 측정 전 추정이었고, 그 낡은
# 값을 믿고 계산하면 예산이 통째로 어긋난다(#430 리뷰). 그래서 아래 양성 대조가 **실제 소요**를
# 예산과 견줘, 정상 실행이 예산에 가까워지면 시끄럽게 알린다.
_LIVE_BUDGET_S = 600.0
_OUTER_TIMEOUT_S = _LIVE_BUDGET_S + driver.RUN_HARD_STOP_MARGIN_S + 60.0


# ───────────────────────────────── 실주행 ─────────────────────────────────


def _evidence_dir(tmp_path_factory) -> Path:
    """이 실행의 증거가 떨어질 자리.

    기본은 pytest 임시 폴더다 — 로컬에서 저장소를 어지럽히지 않는다. CI 는
    ``HWPX_LIVE_EVIDENCE_DIR`` 로 **회수 가능한** 자리를 준다: 종전에는 보고서가 러너의
    임시 폴더로 가서 잡과 함께 사라졌고, 실패한 실주행이 무엇을 봤는지 남는 것이 없었다
    (N-11B). 증거는 실패했을 때 가장 필요하므로 그 자리를 밖에서 정할 수 있어야 한다.
    """
    given = os.environ.get("HWPX_LIVE_EVIDENCE_DIR")
    if not given:
        return tmp_path_factory.mktemp("live101")
    target = Path(given)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _keep_output(evidence: Path, stdout, stderr) -> None:
    """하니스가 무엇을 말하며 끝났는지 회수 가능한 자리에 통째로 남긴다.

    단언 문자열은 2000자로 잘리고 러너 로그는 접혀 있다. 시한 초과 경로에서는 잡힌 출력이
    ``bytes`` 이거나 아예 ``None`` 일 수 있어(:class:`subprocess.TimeoutExpired`) 있는 그대로
    받아 적는다 — 증거를 남기다 다른 예외를 내면 남는 것이 또 없다.
    """
    for name, captured in (("check-stdout.txt", stdout), ("check-stderr.txt", stderr)):
        if captured is None:
            text = "(캡처 없음)"
        elif isinstance(captured, bytes):
            text = captured.decode("utf-8", errors="backslashreplace")
        else:
            text = captured
        (evidence / name).write_text(text, encoding="utf-8")


def _retryable_boot_hang(proc: subprocess.CompletedProcess, report: object) -> bool:
    """구조화된 loaded 전 매달림만 fresh-process 재시도 자격을 준다."""
    if not isinstance(report, dict):
        return False
    verdict = report.get("verdict")
    if not isinstance(verdict, dict):
        return False
    return (
        proc.returncode == driver.ExitCode.ENVIRONMENT
        and report.get("infrastructure_event") == "boot_hung"
        and report.get("environment") is True
        and report.get("shots") == []
        and report.get("observations") == {}
        and report.get("documents") == []
        and report.get("hwpx_generated") == 0
        and verdict.get("ok") is False
        and verdict.get("failures") == []
    )


@pytest.fixture(scope="module")
def live_check_run(tmp_path_factory) -> dict:
    """101 `check` 를 정상 경로에서 **모듈당 한 번** 돌리고 그 사실을 모아 준다.

    실 WebView2 완주는 비싸다(실측 9초 + 창 부팅). 종전에는 두 테스트가 각자 한 번씩 돌아
    CI 잡이 같은 여정을 두 번 태웠다(#430 리뷰). 한 번 돌려 그 결과에 여러 단언을 거는 것은
    이 저장소의 실앱 게이트가 이미 쓰는 관용이다(`test_web_selftest_gate.py` 의 모듈 픽스처).
    구조화된 loaded 전 매달림만 fresh process 한 번을 더 허용하며, 두 시도의 증거는 분리한다.

    예제 홈 스냅샷을 **이 실행을 감싸서** 뜬다 — 그래야 「이 실행이 바꿨는가」가 정확한 질문이
    된다(다른 테스트가 사이에 끼면 귀속이 흐려진다).
    """
    evidence = _evidence_dir(tmp_path_factory)
    evidence_names = ("check-report.json", "check-stdout.txt", "check-stderr.txt")
    for directory in (evidence, evidence / "attempt-1", evidence / "attempt-2"):
        for name in evidence_names:
            (directory / name).unlink(missing_ok=True)
    before = _tree_manifest(EXAMPLE_HOME)
    assert before, f"예제 홈이 비어 있습니다 — 무오염 대조가 아무것도 안 지킵니다: {EXAMPLE_HOME}"

    attempts: "list[dict]" = []
    for number in (1, 2):
        attempt_dir = evidence / f"attempt-{number}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        report_path = attempt_dir / "check-report.json"
        command = [
            sys.executable,
            str(CLI),
            "check",
            "--home",
            "temp",
            "--no-build",
            "--budget-s",
            str(_LIVE_BUDGET_S),
            "--report",
            str(report_path),
        ]
        try:
            proc = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=_OUTER_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as expired:
            _keep_output(attempt_dir, expired.stdout, expired.stderr)
            raise AssertionError(
                f"101 check 가 바깥 시한 {_OUTER_TIMEOUT_S:.0f}s 를 넘겼습니다 — 드라이버의 "
                f"하드 스톱({_LIVE_BUDGET_S + driver.RUN_HARD_STOP_MARGIN_S:.0f}s)조차 착지하지 "
                f"못했습니다. 남긴 증거: {attempt_dir}"
            ) from expired

        _keep_output(attempt_dir, proc.stdout, proc.stderr)
        assert report_path.exists(), (
            f"보고서 미생성 — attempt={number}, rc={proc.returncode}\n"
            f"stdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        attempts.append({"proc": proc, "report": report, "evidence": attempt_dir})
        if number == 1 and _retryable_boot_hang(proc, report):
            warnings.warn(
                f"webview_boot_flake: loaded 전 매달림, fresh process 1회 재시도; 증거={attempt_dir}",
                RuntimeWarning,
                stacklevel=1,
            )
            continue
        break

    selected = attempts[-1]
    proc, report = selected["proc"], selected["report"]
    after = _tree_manifest(EXAMPLE_HOME)
    _keep_output(evidence, proc.stdout, proc.stderr)
    (evidence / "check-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "proc": proc,
        "report": report,
        "before": before,
        "after": after,
        "attempts": attempts,
    }


def test_the_outer_timeout_lets_the_driver_hard_stop_first() -> None:
    """바깥 시한은 안쪽 하드 스톱보다 **성겨야** 한다 — 아니면 진단이 통째로 사라진다.

    게이트 밖이다: 창 없이 수치만 본다. 이 순서가 뒤집히면 GUI 없는 러너에서도 잡혀야 한다.
    """
    inner = _LIVE_BUDGET_S + driver.RUN_HARD_STOP_MARGIN_S
    assert inner < _OUTER_TIMEOUT_S, (
        f"바깥 시한 {_OUTER_TIMEOUT_S}s 가 드라이버 하드 스톱 {inner}s 보다 촘촘합니다 — "
        "CLI 가 먼저 죽어 보고서도 실패 항목도 매달림 스택도 남지 않습니다."
    )
    # 음성 대조 — 뒤집힌 형상을 실제로 거절하는가(항상 참인 산술이 아니다).
    assert not (300.0 + 60.0 < 120.0)


def test_the_evidence_writer_survives_what_a_timeout_hands_it(tmp_path) -> None:
    """시한 초과가 건네는 출력은 `str` 이 아닐 수 있다 — `bytes` 도 `None` 도 받아 적는다.

    이 경로가 예외를 내면 매달림 진단이 **그 시나리오에서만** 사라진다. 증거를 남기려다
    증거를 잃는 형상이라 게이트 밖에서 따로 센다(창 없이 도는 순수 검사).
    """
    _keep_output(tmp_path, "한글 stdout".encode("utf-8"), None)

    assert (tmp_path / "check-stdout.txt").read_text(encoding="utf-8") == "한글 stdout"
    assert "캡처 없음" in (tmp_path / "check-stderr.txt").read_text(encoding="utf-8")


def test_only_a_structured_preloaded_hang_gets_one_loud_fresh_attempt(
    monkeypatch, tmp_path
) -> None:
    """제품 중간 사망은 재시도하지 않고, qualified boot hang 두 실행은 따로 남긴다."""

    class _Factory:
        def mktemp(self, name: str) -> Path:
            target = tmp_path / name
            target.mkdir(exist_ok=True)
            return target

    reports = [
        {
            "infrastructure_event": "boot_hung",
            "environment": True,
            "shots": [],
            "observations": {},
            "documents": [],
            "hwpx_generated": 0,
            "verdict": {"ok": False, "failures": []},
        },
        {
            "environment": False,
            "shots": [],
            "observations": {},
            "documents": [],
            "hwpx_generated": EXPECTED_HWPX,
            "verdict": {"ok": True, "failures": []},
        },
    ]
    calls: "list[Path]" = []

    def fake_run(command, **_kwargs):
        report_path = Path(command[command.index("--report") + 1])
        assert not report_path.exists(), "이전 실행의 보고서를 현재 증거로 읽습니다"
        calls.append(report_path)
        report_path.write_text(
            json.dumps(reports[len(calls) - 1], ensure_ascii=False), encoding="utf-8"
        )
        return subprocess.CompletedProcess(
            command,
            driver.ExitCode.ENVIRONMENT if len(calls) == 1 else driver.ExitCode.OK,
            stdout=f"attempt {len(calls)}",
            stderr="",
        )

    monkeypatch.delenv("HWPX_LIVE_EVIDENCE_DIR", raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys.modules[__name__], "_tree_manifest", lambda _root: {"x": "y"})
    stale = tmp_path / "live101" / "attempt-1" / "check-report.json"
    stale.parent.mkdir(parents=True)
    stale.write_text('{"stale": true}', encoding="utf-8")
    stale_second = tmp_path / "live101" / "attempt-2" / "check-report.json"
    stale_second.parent.mkdir(parents=True)
    stale_second.write_text('{"stale": true}', encoding="utf-8")
    (tmp_path / "live101" / "check-report.json").write_text(
        '{"stale": true}', encoding="utf-8"
    )

    with pytest.warns(RuntimeWarning, match="webview_boot_flake"):
        result = live_check_run.__wrapped__(_Factory())

    assert result["proc"].returncode == driver.ExitCode.OK
    assert len(result["attempts"]) == 2
    assert calls[0].parent.name == "attempt-1" and calls[1].parent.name == "attempt-2"
    assert (calls[0].parent / "check-stdout.txt").read_text(encoding="utf-8") == "attempt 1"
    assert (calls[1].parent / "check-stdout.txt").read_text(encoding="utf-8") == "attempt 2"
    assert json.loads(calls[0].read_text(encoding="utf-8"))["infrastructure_event"] == "boot_hung"
    assert json.loads(calls[1].read_text(encoding="utf-8"))["verdict"]["ok"] is True
    canonical = json.loads(
        (tmp_path / "live101" / "check-report.json").read_text(encoding="utf-8")
    )
    assert canonical["verdict"]["ok"] is True

    product_death = dict(reports[0], shots=["job-landing"])
    assert not _retryable_boot_hang(
        subprocess.CompletedProcess([], driver.ExitCode.ENVIRONMENT), product_death
    )
    assert not _retryable_boot_hang(
        subprocess.CompletedProcess([], driver.ExitCode.SCENARIO_FAILED), reports[0]
    )
    contradictory = {**reports[0], "verdict": {"ok": True, "failures": []}}
    assert not _retryable_boot_hang(
        subprocess.CompletedProcess([], driver.ExitCode.ENVIRONMENT), contradictory
    )


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_check_mode_completes_the_101_journey_on_a_clean_home(live_check_run) -> None:
    """`check` 가 깨끗한 임시 홈에서 완주하고 **실물**을 판정한다.

    보고서의 수치를 그대로 다시 단언하는 것이 요점이다 — 하니스가 스스로 초록이라고 말하는
    것과, 그 초록이 무엇을 근거로 하는지를 밖에서 확인하는 것은 다른 질문이다.
    """
    proc = live_check_run["proc"]
    assert proc.returncode == driver.ExitCode.OK, (
        f"101 check 가 exit {proc.returncode} 로 끝났습니다\n"
        f"stdout={proc.stdout[-3000:]}\nstderr={proc.stderr[-3000:]}"
    )

    report = live_check_run["report"]
    assert report["verdict"]["ok"] is True, report["verdict"]
    assert report["hwpx_generated"] == EXPECTED_HWPX, report["documents"]
    assert tuple(report["shots"]) == CAPTURE_POINTS
    observed = report["observations"]
    assert observed["hwpx_result_state"] == "completed"
    assert observed["preview_approved"] is True
    assert observed["active_work_absent_after_mount"] is True
    assert observed["work_candidate_actionable"] == "발주요청서"
    assert observed["preferred_notice_requires_selection"] is True
    assert observed["explicit_work_selected"] == "발주요청서"
    assert str(observed["txt_copied"]).startswith("1 /"), observed["txt_copied"]
    assert observed["empty_value_gate_asked"] is True
    assert observed["empty_value_surfaced"] is True
    # 무엇으로 잰 실행인지가 남는다 — 스크린샷은 눈검증 증거라 좌표 없이는 대조가 안 된다.
    assert report["source"]["artifact_id"]
    assert report["source"]["commit"]


def _budget_health_note(elapsed: float, budget_s: float) -> "str | None":
    """예산 대비 실제 소요의 건강 소견 — **보고**용이고 게이트가 아니다(#477).

    종전에는 이 문턱(예산의 3분의 1)이 단언이라 quality-gate 를 막았고, 공유 러너의 감속만으로
    빨개진 뒤 코드 무변경 재실행에 초록이 됐다. 「정상 실행이 N초 아래인가」는 공유 CI 에서
    제품이 아니라 인프라를 재므로, 넘으면 시끄럽게 적되 차단하지 않는다. 문턱 자체는 유지한다
    — 정상 실행이 여기 가까워지면 예산은 「상한」이 아니라 「가끔 터지는 것」이고(#430 리뷰),
    그 소견이 예산 재조정의 신호다.
    """
    if elapsed >= budget_s / 3:
        return (
            f"정상 실행이 {elapsed:.1f}s 를 썼습니다 — 예산 {budget_s:.0f}s 의 3분의 1을 "
            "넘습니다. 이 거리면 예산은 매달림이 아니라 러너 속도를 재기 시작합니다"
            " (#477 보고 축 — 차단하지 않습니다)."
        )
    return None


def test_the_budget_health_note_fires_and_stays_quiet_on_the_right_sides() -> None:
    """보고 술어의 양·음성 — 경보로 강등한 문턱이 실제로 무는지 합성 수치로 고정한다.

    단언을 경보로 바꾸면 「선언은 살고 결과는 죽는」 길이 하나 더 생긴다 — 문턱 술어가 아무
    값에도 안 물면 보고 축이 통째로 침묵하고, 그 침묵은 초록과 구별되지 않는다. 게이트 밖
    층이다: 창 없이 돈다.
    """
    fired = _budget_health_note(_LIVE_BUDGET_S / 3, _LIVE_BUDGET_S)
    assert fired is not None and "차단하지 않습니다" in fired
    assert _budget_health_note(_LIVE_BUDGET_S / 3 - 1.0, _LIVE_BUDGET_S) is None


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_a_healthy_run_reports_when_it_nears_the_live_budget(live_check_run) -> None:
    """양성 대조 — 예산이 **매달림**을 잡는가, 아니면 그냥 느린 러너를 잡는가. 답은 보고한다.

    소요 0 단언은 남는다 — 그것은 성능이 아니라 「이 대조가 무언가를 쟀는가」(계측 실패)라
    차단이 정당하다. 성능 소견은 경보로 낸다(#477): 실제 소요를 예산과 견줘 시끄럽게 적되,
    공유 러너에서 제품이 아니라 인프라를 재는 축으로는 머지를 막지 않는다.
    """
    proc = live_check_run["proc"]
    report = live_check_run["report"]
    assert proc.returncode == driver.ExitCode.OK
    assert report["verdict"]["ok"] is True
    assert "infrastructure_event" not in report
    elapsed = float(report["elapsed_s"])

    assert elapsed > 0, "소요가 0이면 이 대조가 아무것도 안 지킨다"
    note = _budget_health_note(elapsed, _LIVE_BUDGET_S)
    if note is not None:
        warnings.warn(note, stacklevel=1)


def _tree_manifest(root: Path) -> "dict[str, str]":
    """트리 전체의 ``상대경로 → sha256``.

    존재 여부만 세면 **덮어쓰기·잘림·내용 변경을 통째로 놓친다** — 부모 폴더가 남아 있는 한
    `before == after` 가 참이기 때문이다(#430 리뷰). "한 글자도 안 건드린다"를 이름으로 말할
    거면 그 한 글자를 실제로 세야 한다.

    ``__pycache__`` 만 뺀다 — 파이썬이 임의로 만들고 지우는 것이라 이 주장의 대상이 아니다.
    """
    manifest: "dict[str, str]" = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest[str(path.relative_to(root)).replace("\\", "/")] = digest
    return manifest


@pytest.mark.live
@pytest.mark.skipif(_GUI_GATE, reason=_GATE_REASON)
def test_check_mode_leaves_the_example_home_untouched(live_check_run) -> None:
    """임시 홈 실행은 사용자의 실습 폴더를 **한 글자도** 건드리지 않는다.

    트리 전체를 해시로 뜬다: 새 파일이 생기는 것뿐 아니라 커밋된 자산이 덮어써지거나 잘리는
    것까지 잡아야 「무오염」이라는 이 모드의 약속이 실제 계약이 된다.
    """
    before, after = live_check_run["before"], live_check_run["after"]
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])

    assert not (added or removed or changed), (
        f"임시 홈 실행이 예제 홈을 바꿨습니다 — 생김 {added} · 사라짐 {removed} · 내용 변경 {changed}"
    )


def test_the_untouched_check_would_notice_a_content_change(tmp_path) -> None:
    """음성 대조 — 내용만 바뀌어도 잡는가(존재 여부만 보던 종전 형태는 못 잡았다)."""
    (tmp_path / "asset.txt").write_text("원본", encoding="utf-8")
    before = _tree_manifest(tmp_path)

    (tmp_path / "asset.txt").write_text("덮어씀", encoding="utf-8")
    after = _tree_manifest(tmp_path)

    assert set(before) == set(after), "이 대조는 파일 목록이 같은 경우를 겨눈다"
    assert before != after, "내용 변경을 못 보면 「한 글자도」라는 말이 거짓이 된다"


# ─────────────────────── 캡처 지점 3자 대조(게이트 밖) ───────────────────────


def _readme_image_references() -> "list[str]":
    return re.findall(r"img/(\d{2}-[a-z-]+\.png)", README.read_text(encoding="utf-8"))


def _expected_filenames(points=CAPTURE_POINTS) -> "list[str]":
    return [f"{index:02d}-{name}.png" for index, name in enumerate(points, 1)]


def _cross_check(
    expected: "list[str]", committed: "list[str]", referenced: "list[str]"
) -> "list[str]":
    """세 목록의 어긋남을 모은다 — 순수 함수라 음성 대조를 조작한 값으로 세울 수 있다."""
    problems: "list[str]" = []
    if sorted(committed) != sorted(expected):
        problems.append(
            f"커밋된 그림 어긋남 — 없는 것 {sorted(set(expected) - set(committed))} · "
            f"남는 것 {sorted(set(committed) - set(expected))}"
        )
    if referenced != expected:
        problems.append(f"README 참조 어긋남(순서 포함) — {referenced}")
    return problems


def test_capture_points_readme_and_committed_images_are_one_set() -> None:
    """대본이 찍기로 한 것 · 커밋된 그림 · README 가 가리키는 것이 **같은 목록**이다.

    셋이 각자 살면 하나만 어긋나도 아무도 모른다 — 대본이 컷 이름을 바꿔도 README 는 옛
    파일을 가리키고 그 파일은 여전히 저장소에 있으니 기존 게이트가 초록이다. 이름의 단일
    출처(:data:`CAPTURE_POINTS`)를 세운 이유가 이 대조다.
    """
    problems = _cross_check(
        _expected_filenames(),
        sorted(p.name for p in IMG_DIR.glob("*.png")),
        _readme_image_references(),
    )

    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    ("committed", "referenced", "fragment"),
    [
        (_expected_filenames()[:-1], _expected_filenames(), "커밋된 그림"),
        (_expected_filenames(), _expected_filenames()[:-1], "README 참조"),
        (_expected_filenames(), list(reversed(_expected_filenames())), "순서"),
    ],
)
def test_the_cross_check_notices_each_way_it_can_drift(committed, referenced, fragment) -> None:
    """음성 대조 — 세 방향의 어긋남을 실제로 잡는가(그림 결손·참조 결손·순서 뒤바뀜).

    저장소 파일을 지웠다 되돌리는 시험은 그 자체가 다음 사람의 작업트리를 위협하므로 **목록을
    조작해** 잰다.
    """
    problems = _cross_check(_expected_filenames(), committed, referenced)

    assert problems, "어긋남을 만들었는데 대조가 조용합니다"
    assert any(fragment in problem for problem in problems), problems


# ───────────────────── 판정의 음성 대조(게이트 밖) ─────────────────────


def _healthy_report(**overrides) -> dict:
    base = {
        "hwpx_generated": EXPECTED_HWPX,
        "shots": list(CAPTURE_POINTS),
        "unstable_shots": [],
        "observations": {
            "hwpx_result_state": "completed",
            "preview_approved": True,
            "txt_copied": "1 / 3",
            "empty_value_gate_asked": True,
            "empty_value_surfaced": True,
        },
    }
    base.update(overrides)
    return base


def test_a_healthy_report_passes_so_the_negative_controls_mean_something() -> None:
    """양성 대조 — 아래 음성들이 「언제나 실패」가 아님을 먼저 보인다."""
    assert report_mod.judge(_healthy_report(), mode="capture").ok is True


def test_zero_documents_fails_even_with_every_screenshot_present() -> None:
    """**생성 0건이면 PNG 가 14장 있어도 실패한다** — 판정 근거는 픽셀이 아니라 실물이다."""
    verdict = report_mod.judge(_healthy_report(hwpx_generated=0), mode="capture")

    assert verdict.ok is False
    assert any("HWPX 생성 0건" in failure for failure in verdict.failures), verdict.failures


def test_a_torn_frame_fails_the_capture_verdict() -> None:
    """정착하지 못한 컷은 찢겨 있을 수 있다 — 조용히 문서에 넣지 않는다(#425 실측)."""
    verdict = report_mod.judge(_healthy_report(unstable_shots=["range-editor"]), mode="capture")

    assert verdict.ok is False
    assert any("정착하지 못한 컷" in failure for failure in verdict.failures), verdict.failures


@pytest.mark.parametrize(
    ("observation", "fragment"),
    [
        ({"hwpx_result_state": "failed"}, "결과 태"),
        ({"preview_approved": False}, "승인"),
        ({"txt_copied": ""}, "복사 카운터"),
        ({"empty_value_gate_asked": False}, "이름게이트"),
        ({"empty_value_surfaced": False}, "〈빈 값〉"),
    ],
)
def test_each_journey_fact_is_actually_judged(observation, fragment) -> None:
    """여정의 사실 하나하나가 **실제로 판정에 걸리는가** — 관측만 하고 안 보면 계약이 아니다."""
    report = _healthy_report()
    report["observations"].update(observation)
    verdict = report_mod.judge(report, mode="capture")

    assert verdict.ok is False
    assert any(fragment in failure for failure in verdict.failures), verdict.failures


# ─────────────── 창 부팅 = 환경 축의 음성 대조(게이트 밖 · #460) ───────────────
#
# 실측이 이 층을 요구했다. `live-webview2` 57표본에서 실패 1건(1.8%)의 `elapsed_s` 는 21.7초 =
# 앱 준비 1.7초 + pywebview `_api_call` 의 하드코딩 20.0초였고, 정상 완주는 p90 21.8초·최대
# 27.3초였다. 즉 우리가 선언한 300초 예산은 발화할 기회가 없었고, 천장은 **남의 상수**였다.
#
# 그런데 그 실패는 제품 언어 7줄(「HWPX 생성 0건」…)로 나왔다. 아래 셋이 그 둘을 각각 잡는다.


class _NeverFires:
    """서지 않는 이벤트 — 부팅이 예산 안에 못 끝나는 상황."""

    def wait(self, timeout=None) -> bool:  # noqa: ARG002 — 시그니처 계약 유지
        return False


class _AlreadyFired:
    def wait(self, timeout=None) -> bool:  # noqa: ARG002 — 시그니처 계약 유지
        return True


class _FakeWindow:
    def __init__(self, **events) -> None:
        self.events = type("Events", (), events)()


def test_a_window_that_never_loads_is_named_environment_not_product() -> None:
    """창이 안 뜨면 **그 단계를 대며** 환경 실패로 죽는다 — 제품 문장으로 번역되지 않는다."""
    window = _FakeWindow(loaded=_NeverFires(), shown=_NeverFires())

    with pytest.raises(driver.WindowBootFailure) as excinfo:
        driver._await_window(window, 0.05, "첫 실행")

    assert excinfo.value.stage == "loaded"
    assert "예산 근거: 첫 실행" in str(excinfo.value)


def test_a_window_that_loads_but_never_shows_names_the_later_stage() -> None:
    """음성 대조 — 두 단계를 한 덩어리로 기다리지 않는다(어디서 멎었는지가 진단이다)."""
    window = _FakeWindow(loaded=_AlreadyFired(), shown=_NeverFires())

    with pytest.raises(driver.WindowBootFailure) as excinfo:
        driver._await_window(window, 0.05, "웜")

    assert excinfo.value.stage == "shown"


def test_a_booted_window_passes_so_the_negative_controls_mean_something() -> None:
    """양성 대조 — 정상 부팅까지 막으면 이 대기는 쓸 수 없다."""
    driver._await_window(_FakeWindow(loaded=_AlreadyFired(), shown=_AlreadyFired()), 0.05, "웜")


def test_an_environment_failure_produces_no_product_failures(monkeypatch, tmp_path) -> None:
    """**이 파일의 존재 이유**(#460) — 환경 실패는 제품 판정을 낳지 않는다.

    종전에는 창이 안 뜬 실행도 :func:`report_mod.judge` 를 그대로 타 「HWPX 생성 0건」·
    「미리보기 미승인」·「〈빈 값〉 미표면」 7줄을 냈다. 전부 참이지만 전부 파생이라, 무인
    판정은 그것을 제품 회귀로 읽고 있지도 않은 결함을 고치러 간다.
    """
    verdict = report_mod.environment_verdict("WebView2 창이 75s 안에 뜨지 않았습니다")

    assert verdict.ok is False
    assert verdict.failures == (), "환경 실패가 제품 언어를 낳았습니다"
    assert "창이" in (verdict.reason or "")
    # 음성 대조 — 같은 빈 보고서를 제품 판정에 넣으면 **7줄이 나온다**(그것이 종전 형상이다).
    product = report_mod.judge({"hwpx_generated": 0, "shots": [], "observations": {}}, mode="check")
    assert len(product.failures) == 7, product.failures

    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "main", lambda **_kwargs: 9)
    landed: "list[driver.LiveRunResult]" = []
    landing = driver._Landing(
        lambda result: landed.append(result) or result.exit_code()
    )
    no_driver = driver._run_with_home(
        mode="check",
        home=tmp_path,
        out_dir=None,
        budget_s=1.0,
        landing=landing,
    )
    assert no_driver.environment is True
    assert no_driver.report["verdict"]["failures"] == []
    assert "app rc=9" in (no_driver.error or "")
    assert "infrastructure_event" not in no_driver.report, "조기 반환은 retry 자격이 아닙니다"
    assert landing.claim_timeout(lambda: no_driver) is None
    assert landing.once(no_driver) == driver.ExitCode.ENVIRONMENT
    assert landed == [no_driver]


@pytest.mark.parametrize(
    ("environment", "expected"),
    [(True, driver.ExitCode.ENVIRONMENT), (False, driver.ExitCode.SCENARIO_FAILED)],
)
def test_the_exit_code_splits_environment_from_product(environment, expected) -> None:
    """부른 쪽이 **분기할 수 있어야** 한다 — 그것이 ``ExitCode`` 의 존재 이유다.

    종전에는 실행 시작 뒤의 환경 실패가 전부 ``SCENARIO_FAILED`` 로 접혔고, 그래서 CI 도
    사람도 「환경이었나」를 종료 코드로 물을 수 없었다.
    """
    result = driver.LiveRunResult(mode="check", ok=False, environment=environment)

    assert result.exit_code() == expected


def test_hard_stops_land_on_their_own_unhealthy_axis(monkeypatch, capsys, tmp_path) -> None:
    """run/teardown 매달림은 성공 표본도 제품 실패도 아닌 인프라 하드스톱이다."""
    landed: "list[driver.LiveRunResult]" = []
    exits: "list[int]" = []

    class _Finished:
        def __init__(self) -> None:
            self.set_calls = 0

        def wait(self, timeout=None) -> bool:  # noqa: ARG002 — 즉시 발화시키는 시계 대역
            return False

        def set(self) -> None:
            self.set_calls += 1

    class _Thread:
        def __init__(self, *, target, daemon=True) -> None:  # noqa: ARG002
            self.target = target

        def start(self) -> None:
            self.target()

    def settle(_observations, _sink, error, *, environment=False):
        return driver.LiveRunResult(
            mode="check",
            ok=False,
            report={"verdict": {"ok": True, "reason": None, "failures": []}},
            error=error,
            environment=environment,
        )

    monkeypatch.setattr(driver.threading, "Thread", _Thread)
    monkeypatch.setattr(driver, "_dump_stacks", lambda _home: "stack")
    monkeypatch.setattr(driver, "_say", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(driver, "_hard_exit", exits.append)

    phases = ("host-loading", "host-loaded", "host-ready", "window", "bridge", "scenario")
    for phase in phases:
        driver._arm_run_watchdog(
            home=tmp_path,
            finished=_Finished(),
            budget_s=1.0,
            mode="check",
            landing=driver._Landing(
                lambda result: landed.append(result) or result.exit_code()
            ),
            settle=settle,
            state={"phase": phase},
        )
    healthy = driver.LiveRunResult(
        mode="check",
        ok=True,
        report={
            "documents": ["kept.hwpx"],
            "verdict": {"ok": True, "reason": None, "failures": []},
        },
    )
    driver._arm_teardown_watchdog(
        healthy,
        tmp_path,
        _Finished(),
        driver._Landing(lambda result: landed.append(result) or result.exit_code()),
    )

    assert exits == [
        driver.ExitCode.RUN_HUNG,
        driver.ExitCode.RUN_HUNG,
        driver.ExitCode.RUN_HUNG,
        driver.ExitCode.RUN_HUNG,
        driver.ExitCode.RUN_HUNG,
        driver.ExitCode.RUN_HUNG,
        driver.ExitCode.TEARDOWN_HUNG,
    ]
    assert [result.report["infrastructure_event"] for result in landed] == [
        "run_hung",
        "run_hung",
        "run_hung",
        "run_hung",
        "run_hung",
        "run_hung",
        "teardown_hung",
    ]
    assert all(result.report["verdict"]["ok"] is False for result in landed)
    assert [result.environment for result in landed[:6]] == [True, True, True, True, True, False]
    assert landed[6].ok is False

    import capture_101_screenshots as cli

    cli._land(landed[6], home=tmp_path, temp_root=None, use_example_home=False, report_path=None)
    assert "실패[인프라]" in capsys.readouterr().err

    shared_landed: "list[driver.LiveRunResult]" = []
    shared = driver._Landing(
        lambda result: shared_landed.append(result) or result.exit_code()
    )
    driver._arm_run_watchdog(
        home=tmp_path,
        finished=_Finished(),
        budget_s=1.0,
        mode="check",
        landing=shared,
        settle=settle,
        state={"phase": "scenario", "result": healthy},
    )
    driver._arm_teardown_watchdog(healthy, tmp_path, _Finished(), shared)
    assert exits[-1:] == [driver.ExitCode.RUN_HUNG]
    assert len(shared_landed) == 1
    assert shared_landed[0].report["infrastructure_event"] == "run_hung"
    assert shared_landed[0].report["documents"] == ["kept.hwpx"]

    def assert_normal_finish_cannot_steal_timeout(event: str) -> None:
        race_landed: "list[driver.LiveRunResult]" = []
        normal_codes: "list[int]" = []
        race = driver._Landing(
            lambda result: race_landed.append(result) or result.exit_code()
        )
        race_finished = _Finished()

        def finish_during_stack_dump(_home) -> str:
            race.mark_finished(race_finished)
            normal_codes.append(race.once(healthy))
            return "stack"

        monkeypatch.setattr(driver, "_dump_stacks", finish_during_stack_dump)
        exit_count = len(exits)
        if event == "run_hung":
            driver._arm_run_watchdog(
                home=tmp_path,
                finished=race_finished,
                budget_s=1.0,
                mode="check",
                landing=race,
                settle=settle,
                state={"phase": "scenario"},
            )
            expected = driver.ExitCode.RUN_HUNG
        else:
            driver._arm_teardown_watchdog(healthy, tmp_path, race_finished, race)
            expected = driver.ExitCode.TEARDOWN_HUNG
        assert exits[exit_count:] == [expected]
        assert [result.report["infrastructure_event"] for result in race_landed] == [event]
        assert normal_codes == [expected]
        assert race_finished.set_calls == 1

    for event in ("run_hung", "teardown_hung"):
        assert_normal_finish_cannot_steal_timeout(event)

    normal_first_landed: "list[driver.LiveRunResult]" = []
    normal_first = driver._Landing(
        lambda result: normal_first_landed.append(result) or result.exit_code()
    )
    normal_first.mark_finished(_Finished())
    assert normal_first.claim_timeout(lambda: healthy) is None
    assert normal_first_landed == []

    wiring = inspect.getsource(driver._run_with_home)
    assert wiring.index("_arm_teardown_watchdog(") < wiring.index("ctx.finish(result.report)")


def _landing_stderr(capsys, tmp_path, *, environment: bool, failures: "list[str]") -> "list[str]":
    """실패 하나를 착지시키고 stderr 줄만 돌려준다 — 사람이 실제로 읽는 것이 그것이다."""
    import capture_101_screenshots as cli

    result = driver.LiveRunResult(
        mode="check",
        ok=False,
        report={"verdict": {"ok": False, "reason": "사유", "failures": failures}},
        error="WebView2 창이 75s 안에 뜨지 않았습니다" if environment else "시나리오가 깨졌습니다",
        environment=environment,
    )
    cli._land(result, home=tmp_path, temp_root=None, use_example_home=False, report_path=None)
    return [line for line in capsys.readouterr().err.splitlines() if line.strip()]


def test_a_boot_failure_no_longer_prints_eight_product_lines(capsys, tmp_path) -> None:
    """#460 그 자체 — 환경 실패의 로그에 **제품 실패 줄이 없다**.

    관측(run 30753937057)은 첫 줄 「Main window failed to start」 아래 파생 7줄이었다. 사람은
    첫 줄을 읽지만 무인 판정은 7줄을 읽고 「내 변경이 101 여정을 깼다」로 오독한다.
    """
    lines = _landing_stderr(capsys, tmp_path, environment=True, failures=[])

    assert not [line for line in lines if line.lstrip().startswith("·")], lines
    assert "실패[환경]" in lines[0], lines[0]
    assert any("제품 판정을 돌리지 않았습니다" in line for line in lines), lines


def test_a_real_product_failure_still_prints_every_line(capsys, tmp_path) -> None:
    """양성 대조 — 제품 실패의 진단까지 접으면 이 조치가 새 침묵을 만든다."""
    lines = _landing_stderr(
        capsys, tmp_path, environment=False, failures=["HWPX 생성 0건 (기대 3건)", "승인 미착지"]
    )

    assert "실패[제품]" in lines[0], lines[0]
    assert len([line for line in lines if line.lstrip().startswith("·")]) == 2, lines


class _Ctx:
    def __init__(self, boot_budget_s=0.0, boot_budget_reason="") -> None:
        self.boot_budget_s = boot_budget_s
        self.boot_budget_reason = boot_budget_reason


def test_the_harness_waits_longer_than_the_budget_this_boot_actually_armed() -> None:
    """순서가 계약이다 — 하니스는 **이 부팅이 무장한** 폴백보다 성겨야 한다.

    반대로 서면 하니스가 제품이 살려내려던 부팅을 먼저 죽이고, 제품이 남겼을 강제 show + 경보는
    영영 나오지 않는다.

    종전 이 테스트는 ``product + GRACE > product`` 라는 **산술**을 쟀다(#460 리뷰 P1). 그것은
    상수가 무엇이든 참이라, 하니스가 콜드로 무장한 부팅에 웜 값을 쓰는 실제 결함 앞에서 초록인
    채였다. 이제 무장값을 넣고 **나온 대기 시간**을 견준다.
    """
    for armed in (boot_budget.COLD_BUDGET_SECONDS, boot_budget.WARM_BUDGET_SECONDS):
        waited, _ = driver.boot_wait_budget(_Ctx(armed, "사유"), Deadline(9999.0))
        assert waited > armed, f"무장 {armed}s 인데 하니스가 {waited}s 만 기다린다"

    # 음성 대조 — 뒤집힌 형상을 실제로 거절하는가.
    assert not (
        boot_budget.WARM_BUDGET_SECONDS + driver.BOOT_GRACE_S
        > boot_budget.COLD_BUDGET_SECONDS + driver.BOOT_GRACE_S
    )


def test_a_cold_armed_boot_is_never_measured_with_the_warm_budget() -> None:
    """#460 리뷰 P1 — 재계산 금지가 **구조로** 지켜지는가.

    ``loaded`` 콜백이 완주 스탬프를 먼저 쓰므로, 이 자리에서 ``decide()`` 를 다시 부르면 콜드로
    무장한 부팅이 웜 예산으로 재진다. 값을 건네받는 한 홈 상태가 어떻든 그 일이 없다.
    """
    armed = boot_budget.COLD_BUDGET_SECONDS
    # 스탬프가 이미 쓰인 홈을 흉내 낸다 — 재계산했다면 여기서 웜으로 접혔을 것이다.
    from hwpxfiller.external import settings

    settings.save_boot_completed(boot_budget.detect_runtime_version())

    waited, _ = driver.boot_wait_budget(_Ctx(armed, "첫 실행"), Deadline(9999.0))

    assert waited == armed + driver.BOOT_GRACE_S
    assert waited > boot_budget.WARM_BUDGET_SECONDS + driver.BOOT_GRACE_S


def test_the_boot_wait_expires_before_the_hard_stop(tmp_path) -> None:
    """#460 리뷰 P2 — 부팅 대기가 :class:`Deadline` **안에** 있는가.

    밖에 서면 작은 ``--budget-s`` 에서 하드 스톱(``budget_s + RUN_HARD_STOP_MARGIN_S``)이 먼저
    물어 ``drive()`` 가 ``finally`` 를 건너뛴다 — 그러면 워치독의 착지가 환경 분류 없이 돌아
    이 변경이 없앤 제품 실패 7줄이 되돌아온다.
    """
    run_budget = 10.0
    hard_stop = run_budget + driver.RUN_HARD_STOP_MARGIN_S
    waited, _ = driver.boot_wait_budget(
        _Ctx(boot_budget.COLD_BUDGET_SECONDS, "첫 실행"), Deadline(run_budget)
    )

    assert waited <= run_budget, f"부팅 대기 {waited}s 가 실행 예산 {run_budget}s 를 넘습니다"
    assert waited < hard_stop, "하드 스톱이 먼저 물면 구조화된 환경 착지가 통째로 사라진다"
    # 음성 대조 — 예산이 넉넉하면 클램프가 아니라 무장값이 이긴다(항상 자르지 않는다).
    generous, _ = driver.boot_wait_budget(
        _Ctx(boot_budget.COLD_BUDGET_SECONDS, "첫 실행"), Deadline(9999.0)
    )
    assert generous == boot_budget.COLD_BUDGET_SECONDS + driver.BOOT_GRACE_S


def test_a_context_without_a_budget_is_named_not_silently_generous() -> None:
    """예산이 안 실려 오면 **사유가 그렇게 말한다** — 조용한 기본값으로 접지 않는다."""
    waited, reason = driver.boot_wait_budget(_Ctx(), Deadline(9999.0))

    assert waited == driver.BOOT_GRACE_S
    assert "미전달" in reason


# ─────────────────── 부재/미성립 구분의 음성 대조(게이트 밖) ───────────────────


class _BlindWindow:
    """모든 술어가 거짓인 창 — 무엇이 없는지는 ``present`` 가 정한다."""

    def __init__(self, present: "set[str]", alerts: "tuple[str, ...]" = ()) -> None:
        self.present = present
        self.alerts = list(alerts)
        self.poll_count = 0

    def evaluate_js(self, expression: str):
        if expression.startswith("window.__cap.poll("):
            self.poll_count += 1
            alert = self.alerts.pop(0) if self.alerts else None
            return {"ready": False, "alert": alert}
        match = re.search(r"document\.querySelector\(\"(.+?)\"\) !== null", expression)
        if match:
            return match.group(1) in self.present
        return False


class _CommitMissingWindow:
    """입력은 받지만 다음 host 왕복에서 노드가 사라진 창."""

    def __init__(self) -> None:
        self.calls: "list[str]" = []

    def evaluate_js(self, expression: str) -> bool:
        self.calls.append(expression)
        return expression.startswith("window.__cap.setValue(")


def test_set_value_commits_once_and_names_a_missing_control() -> None:
    """React 입력은 최신 노드에서 한 번만 커밋하고, 2차 부재도 자리를 대며 죽는다."""
    window = _CommitMissingWindow()
    surface = Surface(window, Deadline(30.0))

    with pytest.raises(MissingSurface) as excinfo:
        surface.set_value("#editorName", "발주요청 기안")

    assert window.calls == [
        'window.__cap.setValue("#editorName", "발주요청 기안")',
        'window.__cap.commitValue("#editorName")',
    ]
    native = "el.addEventListener('focusout', markLeft);"
    fallback = "if (!left && el.tagName !== 'SELECT')"
    synthetic = "el.dispatchEvent(new view.FocusEvent('focusout', { bubbles: true }));"
    assert JS_HELPERS.count(native) == 1
    assert JS_HELPERS.count(fallback) == 1
    assert JS_HELPERS.count(synthetic) == 1
    assert (
        JS_HELPERS.index(native)
        < JS_HELPERS.index("el.blur();")
        < JS_HELPERS.index(fallback)
        < JS_HELPERS.index(synthetic)
    )
    assert excinfo.value.selector == "#editorName"
    assert "커밋" in str(excinfo.value)


def test_a_missing_selector_is_named_not_timed_out() -> None:
    """필수 selector 가 없으면 **그 이름을 대며** 죽는다 — timeout 으로 뭉개지 않는다."""
    surface = Surface(_BlindWindow(present={"#present"}), Deadline(30.0))

    with pytest.raises(MissingSurface) as excinfo:
        surface.wait("false", "어떤 화면", timeout=0.3, requires=["#present", "#gone"])

    assert excinfo.value.selector == "#gone"
    assert "#gone" in str(excinfo.value)


def test_a_present_but_unsatisfied_predicate_stays_a_step_timeout() -> None:
    """음성 대조 — 요소가 다 있으면 여전히 걸음 미성립이다(둘을 뭉개지 않는다)."""
    surface = Surface(_BlindWindow(present={"#present"}), Deadline(30.0))

    with pytest.raises(StepTimeout):
        surface.wait("false", "어떤 화면", timeout=0.3, requires=["#present"])


def test_a_native_alert_fails_the_current_wait_on_its_first_poll() -> None:
    """native modal 대신 포획한 경보는 전체 예산이 아니라 **첫 폴링**에서 문안째 실패한다."""
    window = _BlindWindow(present={"#present"}, alerts=("작업 이름을 입력하세요.",))
    surface = Surface(window, Deadline(600.0))

    with pytest.raises(UnexpectedNativeAlert) as excinfo:
        surface.wait("false", "TXT 작업 저장 착지", timeout=30.0, requires=["#present"])

    assert window.poll_count == 1, "경보를 본 뒤 timeout 폴링을 계속했습니다"
    assert excinfo.value.message == "작업 이름을 입력하세요."
    assert "TXT 작업 저장 착지" in str(excinfo.value)


# ─────────────────────── 실습 홈 보호(게이트 밖) ───────────────────────


def test_a_dirty_home_is_refused_and_preserved(tmp_path) -> None:
    """실습 잔재가 있으면 **지우지 않고 거절**한다 — 사용자 상태를 말없이 파괴하지 않는다."""
    (tmp_path / "jobs").mkdir()
    keepsake = tmp_path / "jobs" / "내작업.job.json"
    keepsake.write_text("{}", encoding="utf-8")

    with pytest.raises(driver.DirtyHome) as excinfo:
        driver.refuse_if_dirty(tmp_path)

    assert "jobs" in str(excinfo.value)
    assert "reset-101.cmd" in str(excinfo.value), "정리하는 길을 함께 일러야 한다"
    assert keepsake.exists(), "거절이 사용자 파일을 지웠습니다"


def test_a_clean_home_is_not_refused(tmp_path) -> None:
    """양성 대조 — 깨끗한 홈까지 거절하면 이 가드는 쓸 수 없다."""
    driver.refuse_if_dirty(tmp_path)


def test_seeding_copies_committed_assets_without_practice_output(tmp_path) -> None:
    """시딩은 **커밋된 자산만** 옮긴다 — 실습 산출물이 따라오면 check 의 판정이 틀린다."""
    home = driver.seed_temp_home(tmp_path / "home")

    for name in driver.SEED_ASSETS:
        assert (home / name).is_dir(), f"시딩 누락: {name}"
    assert driver.generated_documents(home) == [], "시딩 직후 생성물이 있으면 안 됩니다"
    assert not (home / driver.RESULTS_REL).exists()
