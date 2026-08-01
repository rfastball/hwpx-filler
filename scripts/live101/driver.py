"""공용 live driver — 앱 시작·준비·시한·증거·종료와 실습 홈 수명주기(N-11A · #423).

시나리오는 "무엇을 누르는가"만 안다. 창을 어떻게 띄우고 언제 포기하고 무엇을 남기고 어떻게
내려오는가는 전부 여기가 진다. 종전에는 이 여섯이 캡처 스크립트 한 파일에 시나리오와 섞여
있었고, 그래서 하나를 고치려면 나머지 다섯을 읽어야 했다.

## 실행 모드 둘

- ``check`` — PNG 를 만들지 않는다. **임시 홈**에 커밋된 101 자산을 시딩해 돌므로 CI·병렬
  실행이 저장소 작업트리를 건드리지 않는다. 판정은 실물이다: 실제 생성된 HWPX 파일 수,
  결과 태, 복사 카운터, 〈빈 값〉 표면.
- ``capture`` — 같은 시나리오, **예제 홈**. 화면에 뜨는 저장 폴더 경로가 문서와 같아야
  하므로 홈을 옮기지 않는다. 대신 dirty 홈은 파괴하지 않고 loud 거절한다.

## 왜 홈이 갈리는가

101 실습 홈은 사용자의 것이다. ``capture`` 는 문서 충실도 때문에 그 자리에서 돌아야 하지만,
``check`` 는 문서가 아니라 **동작**을 재므로 그럴 이유가 없다. CI 가 저장소 작업트리에
실행 산출물을 남기지 않으려면 갈라야 하고, 갈라 두면 두 사람이 동시에 돌려도 안전하다.

## 정리·보존 정책

성공하면 **자기 잔재만** 치워 재실행 가능 상태로 돌려놓는다. 실패하면 아무것도 지우지
않는다 — 실패한 실행의 홈이 곧 진단 증거다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from . import capture as capture_mod
from . import report as report_mod
from . import scenario as scenario_mod
from .surface import Deadline, ScenarioFailure, Surface

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_HOME = REPO_ROOT / "examples" / "quickstart-101"
IMG_DIR = EXAMPLE_HOME / "img"

#: 캡처 창 크기(논리 px) — 문서 스크린샷 고정 규격(리사이즈로 강제, 저장 기하 무시).
WINDOW_W, WINDOW_H = 1180, 760

#: 실행 하나의 전체 예산. 101 완주는 실측 2~4분이라 넉넉히 잡되 **상한이 있다**.
RUN_BUDGET_S = 900.0
#: 브리지 준비(제품 공개 API `__hwpx` 가 설 때까지) 예산.
READY_BUDGET_S = 20.0
#: `window.destroy()` 뒤 pywebview teardown 에 주는 유예. 넘기면 진단을 남기고 하드 종료.
TEARDOWN_GRACE_S = 10.0

#: 101 이 만드는 것들 — 성공 시 정리 대상(``reset-101.cmd`` 와 같은 집합).
PRACTICE_STATE = [
    "jobs", "datasets", "mapping_bases", "webview", "out", "Results",
    "templates/Results", "ui_settings.ini", "settings.json", "webapp-alerts.log",
]
#: dirty 판별에서 ``webview`` 는 뺀다 — 앱이 부팅마다 스스로 통청소하는 프로필이라
#: 잔존해도 화면 결정성에 영향이 없고, 워치독 종료 직후엔 잠겨 있어 남는 것이 정상이다.
REFUSE_STATE = [p for p in PRACTICE_STATE if p != "webview"]

#: 임시 홈에 시딩하는 커밋된 자산 — 사용자가 받는 것과 **같은 파일**이라야 검사가 의미를 갖는다.
SEED_ASSETS = ["data", "templates", "text_templates"]

#: 생성물이 떨어지는 자리(README 「기본 저장 폴더」).
RESULTS_REL = Path("templates") / "Results"


class ExitCode:
    """실행 결과의 안정 코드 — 부른 쪽이 분기할 수 있어야 한다."""

    OK = 0
    SCENARIO_FAILED = 1
    DIRTY_HOME = 2
    ENVIRONMENT = 3
    TEARDOWN_HUNG = 7


class DirtyHome(RuntimeError):
    """실습 잔재가 있는 홈 — 지우지 않고 거절한다(사용자 상태를 말없이 파괴하지 않는다)."""


@dataclass
class LiveRunResult:
    mode: str
    ok: bool
    report: dict = field(default_factory=dict)
    error: "str | None" = None

    def exit_code(self) -> int:
        return ExitCode.OK if self.ok else ExitCode.SCENARIO_FAILED


# ------------------------------------------------------------------ 홈 수명주기


def refuse_if_dirty(home: Path) -> None:
    stale = [rel for rel in REFUSE_STATE if (home / rel).exists()]
    if stale:
        raise DirtyHome(
            f"{home} 에 실습 잔재가 있어 실행을 거부합니다(비결정 화면·로컬 상태 보호): "
            f"{stale}\n→ reset-101.cmd 로 정리한 뒤 다시 실행하세요."
        )


def seed_temp_home(destination: Path) -> Path:
    """커밋된 101 자산을 임시 홈에 복사한다 — 예제 홈은 한 글자도 건드리지 않는다."""
    destination.mkdir(parents=True, exist_ok=True)
    for name in SEED_ASSETS:
        source = EXAMPLE_HOME / name
        if not source.is_dir():
            raise FileNotFoundError(f"101 자산이 없습니다: {source}")
        shutil.copytree(source, destination / name, dirs_exist_ok=True)
    return destination


def clean_practice_state(home: Path) -> None:
    """성공 완주 뒤 자기 잔재만 치운다. 잠긴 파일(실행 중 프로필)은 남긴다."""
    for rel in PRACTICE_STATE:
        target = home / rel
        try:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink(missing_ok=True)
        except OSError:
            pass  # 다음 부팅/reset 이 치운다


def generated_documents(home: Path) -> "list[str]":
    results = home / RESULTS_REL
    if not results.is_dir():
        return []
    return sorted(p.name for p in results.glob("*.hwpx"))


# ------------------------------------------------------------------ 선행 조건


def build_web_artifact() -> None:
    """제품이 소비할 sealed ``build/web/`` 을 먼저 만든다 — 산출물을 갈아엎기 **전에**.

    순서가 계약이다: 빌드가 실패한 뒤에 스크린샷 폴더를 비우면 문서가 그림 없이 남는다.
    """
    subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(REPO_ROOT / "build-web.ps1"),
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def preflight(mode: str) -> "list[str]":
    """실행 없이 **전제만** 센다 — CI 가 "돌 수 있는 환경인가"를 시끄럽게 증명하는 자리.

    실주행(2~4분)을 CI 단계에서 두 번 돌리지 않으려는 것이다. 실제 완주는 pytest 게이트가
    한 번 돌고, 이 단계는 그 게이트가 조용히 스킵될 수 없음을 앞에서 보인다.
    """
    problems: "list[str]" = []
    if sys.platform != "win32":
        problems.append("Windows 데스크톱 세션이 아닙니다(WebView2 실창 필요)")
    for name in SEED_ASSETS:
        if not (EXAMPLE_HOME / name).is_dir():
            problems.append(f"101 자산 없음: {EXAMPLE_HOME / name}")
    if not (EXAMPLE_HOME / "data" / "발주목록.csv").is_file():
        problems.append("101 데이터 없음: data/발주목록.csv")
    if mode == "capture":
        try:
            import PIL  # noqa: F401
        except ImportError:
            problems.append("Pillow 없음 — capture 모드는 PNG 저장에 필요합니다")
    try:
        from hwpxfiller.webapp import app as webapp_app

        webapp_app.web_artifact()
    except Exception as exc:  # noqa: BLE001 — 부재를 성공으로 접지 않는다
        problems.append(f"봉인된 웹 산출물 검증 실패: {exc}")
    return problems


# ------------------------------------------------------------------ 실행


def run(
    *,
    mode: str,
    home: Path,
    out_dir: "Path | None" = None,
    budget_s: float = RUN_BUDGET_S,
) -> LiveRunResult:
    """제품 창을 띄워 101 을 완주한다. ``mode`` 는 ``"check"`` 또는 ``"capture"``."""
    if mode not in ("check", "capture"):
        raise ValueError(f"모르는 실행 모드: {mode!r}")

    os.environ["HWPXFILLER_HOME"] = str(home)

    from hwpxfiller.webapp import app as webapp_app
    from hwpxfiller.webapp import live_run

    answers: "deque[str]" = deque()
    state: dict = {"ok": False, "error": None, "observations": {}, "sink": None}
    deadline = Deadline(budget_s)

    def answer_file_dialog(filters, owner_title=None):  # noqa: ARG001 — 시그니처 계약 유지
        return answers.popleft() if answers else None

    def answer_folder_dialog(title, owner_title=None):  # noqa: ARG001 — 시그니처 계약 유지
        # 대본이 폴더 피커를 밟지 않는다. 밟는 순간 조용히 취소로 접지 않고 시끄럽게 죽는다 —
        # 답이 없는 대화상자를 None 으로 넘기면 그 뒤의 화면이 "사용자가 취소했다"가 된다.
        raise RuntimeError(f"대본에 없는 폴더 대화상자 요청: {title!r}")

    def write_evidence(result) -> Path:
        out = home / "_live101_result.json"
        out.write_text(json.dumps(dict(result), ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    def drive(ctx) -> None:
        window = ctx.window
        evidence: dict = {"mode": mode}
        try:
            _await_bridge(window, deadline)
            window.resize(WINDOW_W, WINDOW_H)
            time.sleep(0.6)
            surface = Surface(window, deadline)
            surface.install_helpers()
            sink = _make_sink(mode, out_dir, webapp_app.WINDOW_TITLE)
            state["sink"] = sink
            observations = scenario_mod.run(
                scenario_mod.ScenarioContext(
                    surface=surface,
                    shoot=sink.shoot,
                    csv_path=str(home / "data" / "발주목록.csv"),
                    queue_file_answer=answers.append,
                )
            )
            if answers:
                raise ScenarioFailure(
                    f"대화상자 답변 잔량 {len(answers)} — 대본이 화면과 어긋났습니다"
                )
            state["observations"] = observations
            state["ok"] = True
            evidence.update(observations)
            evidence["shots"] = list(sink.shots)
        except Exception as exc:  # noqa: BLE001 — 드라이브 스레드 조용한 증발 금지
            state["error"] = f"{type(exc).__name__}: {exc}"
            evidence["error"] = state["error"]
        finally:
            ctx.finish(evidence)
            _arm_teardown_watchdog(state, home)

    rc = webapp_app.main(
        argv=[],
        live=live_run.LiveRun(
            name="quickstart-101",
            drive=drive,
            write_output=write_evidence,
            file_dialogs=live_run.FileDialogs(
                open_file=answer_file_dialog, open_folder=answer_folder_dialog
            ),
        ),
    )

    (home / "_live101_result.json").unlink(missing_ok=True)
    sink = state["sink"]
    built = report_mod.build(
        mode=mode,
        home=home,
        observations=state["observations"],
        documents=generated_documents(home),
        shots=list(sink.shots) if sink is not None else [],
        unstable=list(sink.unstable) if sink is not None else [],
        geometry=sink.geometry() if sink is not None else {},
        window_size=(WINDOW_W, WINDOW_H),
        elapsed_s=deadline.elapsed_s(),
    )
    verdict = report_mod.judge(built, mode=mode)
    ok = bool(state["ok"]) and verdict.ok and rc == 0
    return LiveRunResult(
        mode=mode,
        ok=ok,
        report={**built, "verdict": verdict.as_dict()},
        error=state["error"] or verdict.reason,
    )


def _await_bridge(window: object, deadline: Deadline) -> None:
    """준비 신호는 제품 공개 API 다(#372 D-06).

    종전에는 내부 이름 ``window.Nav`` 를 봤는데 그 임시 전역은 N-10 에서 사라졌다.
    ``__hwpx`` 는 합성 루트가 서비스·화면·앱 셸을 **전부 구성한 뒤** 마지막에 거는 이름이라
    준비 신호로 더 정확하다.
    """
    budget = min(READY_BUDGET_S, max(deadline.remaining_s(), 0.0))
    end = time.monotonic() + budget
    while time.monotonic() < end:
        if window.evaluate_js(  # type: ignore[attr-defined]
            "!!(window.pywebview && window.pywebview.api && window.__hwpx)"
        ):
            return
        time.sleep(0.15)
    raise ScenarioFailure(f"브리지 준비 시한 초과({budget:.0f}s) — 창은 떴으나 앱이 서지 않았습니다")


def _make_sink(mode: str, out_dir: "Path | None", window_title: str):
    if mode == "check":
        return capture_mod.NullSink()
    if out_dir is None:
        raise ValueError("capture 모드에는 출력 폴더가 필요합니다")
    hwnd = capture_mod.find_window(window_title)
    return capture_mod.Win32Sink(hwnd, out_dir)


def _arm_teardown_watchdog(state: dict, home: Path) -> None:
    """``window.destroy()`` 뒤에도 WinForms 루프가 안 내려오는 pywebview teardown 매달림 대비.

    유예·진단 산출물·exit code 를 **계약으로 적는다**(#423 B). 조용한 무한 대기는 없다:
    성공이면 정리하고 0으로, 실패면 스택을 남기고 :data:`ExitCode.TEARDOWN_HUNG` 로 나간다.
    """
    import faulthandler
    import threading

    def _watchdog() -> None:
        time.sleep(TEARDOWN_GRACE_S)
        if state["ok"]:
            clean_practice_state(home)
            os.write(
                1,
                (
                    "완료(teardown 매달림 → 워치독 종료; 잠긴 webview/ 는 다음 부팅이 청소)\n"
                ).encode("utf-8", "replace"),
            )
            os._exit(ExitCode.OK)
        with (home / "_live101_hang_stacks.txt").open("w", encoding="utf-8") as fh:
            faulthandler.dump_traceback(file=fh)
        os._exit(ExitCode.TEARDOWN_HUNG)

    threading.Thread(target=_watchdog, daemon=True).start()
