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
import threading
import time
from collections import deque
from collections.abc import Callable
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

#: 실행 하나의 전체 예산.
#:
#: **실측(2026-08-01, 개발 기기)**: `check` 8.6~9.3초 · `capture` 18.7~19.4초. 종전 이 자리에
#: 적혀 있던 "2~4분"은 측정 **전에** 쓴 설계 추정치였고, 실측이 들어온 뒤에도 고쳐지지 않았다
#: (#430 리뷰가 그 문서를 믿고 예산을 계산하다 드러났다 — 주석이 계약처럼 읽히는 자리에서
#: 낡은 추정치는 거짓말이다).
#:
#: 기본값 900초는 "정상 실행의 상한"이 아니라 **관대한 천장**이다: 느린 러너·콜드스타트를
#: 전부 덮고도 남게 두되 무한 대기는 막는다. 자기 시한을 가진 호출자는 `budget_s` 로 더 작게
#: 준다(그 순서는 `tests/test_quickstart_101_live.py` 가 못박는다).
RUN_BUDGET_S = 900.0
#: 브리지 준비 예산 — **창이 뜬 뒤** 제품 공개 API `__hwpx` 가 설 때까지.
#:
#: 이것은 **제품 축**이다: 페이지가 로드됐는데 합성 루트가 안 서면 그것은 환경이 아니라 제품
#: 결함이므로 촘촘하게 잡는다. 창 부팅 자체는 성질이 달라 :func:`boot_budget_s` 가 따로 진다
#: (#460) — 종전에는 이 상수 하나가 두 축을 겸해, 느린 콜드스타트가 「앱이 서지 않았습니다」로
#: 오분류될 자리에 있었다.
READY_BUDGET_S = 20.0
#: 창 부팅 대기에 **제품 판정 위로** 얹는 여유.
#:
#: 순서가 계약이다: 제품의 FOUC 폴백이 먼저 발화해 자기 진단(강제 show + 경보)을 남길 기회를
#: 준 뒤에야 하니스가 포기한다. 반대로 서면 하니스가 제품이 살려내려던 부팅을 먼저 죽이고,
#: 제품이 남겼을 경보는 영영 나오지 않는다 — :data:`RUN_HARD_STOP_MARGIN_S` 와 같은 형상이다.
BOOT_GRACE_S = 15.0
#: `window.destroy()` 뒤 pywebview teardown 에 주는 유예. 넘기면 진단을 남기고 하드 종료.
TEARDOWN_GRACE_S = 10.0
#: 실행 예산을 넘긴 뒤 **하드 스톱**까지의 여유. 부드러운 시한(:class:`Deadline`)이 먼저
#: 발화해 구조화된 실패로 착지할 기회를 주고, 그마저 못 도달할 때만 이 백스톱이 문다.
RUN_HARD_STOP_MARGIN_S = 60.0

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
    #: **2 는 쓰지 않는다** — argparse 가 사용법 오류에 쓰는 값이다. 겹쳐 두면 "인자를 잘못
    #: 줬다"와 "실습 잔재가 있다"가 같은 코드로 나와, 스크립트가 분기할 수 없다(실측으로
    #: 걸렸다: `check --report` 가 없던 시절 그 오류가 dirty 홈 거절로 읽혔다).
    USAGE = 2
    ENVIRONMENT = 3
    DIRTY_HOME = 4
    #: 창은 내려가라는 말을 들었는데 GUI 루프가 안 내려온다.
    TEARDOWN_HUNG = 7
    #: 실행이 자기 끝에 **도달조차 못 했다** — 브리지가 멎어 시한을 되짚을 기회가 없었다.
    RUN_HUNG = 8


class DirtyHome(RuntimeError):
    """실습 잔재가 있는 홈 — 지우지 않고 거절한다(사용자 상태를 말없이 파괴하지 않는다)."""


class WindowBootFailure(RuntimeError):
    """창이 뜨지 못했다 — **환경 실패**다(#460).

    제품 실패와 **타입으로** 갈린다. 문자열 대조가 아닌 이유는 이 저장소가 이미 그 함정을
    만났기 때문이다(부분열 검사가 구조를 흉내 내면 산문이 구조의 삭제를 가린다): 실패 문안은
    고쳐 쓰이지만 축은 그대로여야 한다.

    이 예외가 나면 시나리오는 **한 걸음도 돌지 않았다**. 그래서 그때의 빈 관측은 제품의
    증거가 아니고, 판정을 돌리면 「HWPX 생성 0건」 같은 제품 언어가 환경 사고 위에 덧씌워진다.
    """

    def __init__(self, stage: str, budget_s: float, reason: str) -> None:
        self.stage = stage
        self.budget_s = budget_s
        self.reason = reason
        super().__init__(
            f"WebView2 창이 {budget_s:.0f}s 안에 뜨지 않았습니다"
            f" (`{stage}` 미발화 · 예산 근거: {reason})"
        )


@dataclass
class LiveRunResult:
    mode: str
    ok: bool
    report: dict = field(default_factory=dict)
    error: "str | None" = None
    #: 환경 실패인가 — 제품에 **닿지도 못한** 실행. 판정을 돌리지 않았으므로 파생 실패가 없고,
    #: 종료 코드도 제품 실패와 갈린다(부른 쪽이 분기할 수 있어야 한다는 ExitCode 의 존재 이유).
    environment: bool = False

    def exit_code(self) -> int:
        if self.ok:
            return ExitCode.OK
        return ExitCode.ENVIRONMENT if self.environment else ExitCode.SCENARIO_FAILED


# ------------------------------------------------------------------ 홈 수명주기


def refuse_if_dirty(home: Path) -> None:
    stale = [rel for rel in REFUSE_STATE if (home / rel).exists()]
    if stale:
        raise DirtyHome(
            f"{home} 에 실습 잔재가 있어 실행을 거부합니다(비결정 화면·로컬 상태 보호): "
            f"{stale}\n→ reset-101.cmd 로 정리한 뒤 다시 실행하세요."
        )


def seed_temp_home(destination: Path) -> Path:
    """**커밋된** 101 자산만 임시 홈에 복사한다 — 예제 홈은 한 글자도 건드리지 않는다.

    실습 산출물은 자산이 아니다(#426 리뷰 라운드 6). ``templates/`` 아래에는 생성 결과가
    떨어지는 ``Results/`` 가 함께 사는데, 사용자가 실습한 뒤라면 그것까지 통째로 복사된다.
    그러면 임시 홈이 **이미 HWPX 를 가진 채** 시작하고 :func:`generated_documents` 가 그것을
    세어 「3건 생성」을 거짓으로 만족시키거나, 이름 충돌로 엉뚱한 실패를 낸다 — 「커밋된
    자산만으로 격리한다」는 이 모드의 약속이 정확히 거기서 깨진다.
    """
    ignored = {Path(rel).name for rel in PRACTICE_STATE}

    def _skip_practice_state(directory: str, names: "list[str]") -> "set[str]":
        return {name for name in names if name in ignored}

    destination.mkdir(parents=True, exist_ok=True)
    for name in SEED_ASSETS:
        source = EXAMPLE_HOME / name
        if not source.is_dir():
            raise FileNotFoundError(f"101 자산이 없습니다: {source}")
        shutil.copytree(
            source, destination / name, dirs_exist_ok=True, ignore=_skip_practice_state
        )
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
    land: "Callable[[LiveRunResult], int]",
    out_dir: "Path | None" = None,
    budget_s: float = RUN_BUDGET_S,
) -> int:
    """제품 창을 띄워 101 을 완주하고 **착지 코드**를 돌려준다.

    ## 왜 착지가 콜백인가 — 착지 경로는 하나여야 한다 (#426 리뷰 라운드 3)

    이 하니스에는 강제 종료가 필요하다: pywebview teardown 이 매달리거나 브리지가 멎으면
    ``main()`` 이 영영 반환하지 않는다. 그런데 그 강제 종료가 ``os._exit`` 로 **두 번째 착지
    경로**가 되면, 착지 책임이 하나 생길 때마다 그쪽에 복제해야 한다. 실제로 그렇게 됐다 —
    리뷰 세 라운드가 각각 다른 누락을 짚었다: 판정(라운드 1) · 요청된 보고서(라운드 3) ·
    임시 홈 정리(라운드 3). 점별로 메우면 다음 라운드에 또 하나가 나온다.

    그래서 경로를 하나로 만든다. 부른 쪽이 "착지란 무엇인가"를 :func:`land` 하나에 적고,
    드라이버는 **정상 반환이든 강제 종료든 반드시 그것을 정확히 한 번 지나게** 보장한다.
    앞으로 착지 책임이 늘어도 자동으로 두 경로에 다 걸린다.

    앱 홈은 이 실행의 것이고 **프로세스에 남지 않는다**(리뷰 라운드 2). ``home_dir()`` 은
    환경변수를 호출 시점에 읽으므로, 남겨 두면 이 함수를 부른 장수 프로세스(pytest 게이트)의
    이후 코드가 전부 하니스 홈을 가리킨다 — 그리고 착지는 성공한 임시 홈을 지운다.
    """
    if mode not in ("check", "capture"):
        raise ValueError(f"모르는 실행 모드: {mode!r}")

    landing = _Landing(land)
    previous_home = os.environ.get("HWPXFILLER_HOME")
    os.environ["HWPXFILLER_HOME"] = str(home)
    try:
        result = _run_with_home(
            mode=mode, home=home, out_dir=out_dir, budget_s=budget_s, landing=landing
        )
        return landing.once(result)
    finally:
        if previous_home is None:
            os.environ.pop("HWPXFILLER_HOME", None)
        else:
            os.environ["HWPXFILLER_HOME"] = previous_home


class _Landing:
    """착지를 **정확히 한 번** 지나게 하는 문지기.

    두 스레드(정상 반환 · 워치독)가 동시에 닿을 수 있으므로 잠금이 필요하다. 두 번째
    호출은 조용한 no-op 이 아니라 첫 코드를 그대로 돌려준다 — 착지의 결론도 처음 것이다.
    """

    def __init__(self, land: "Callable[[LiveRunResult], int]") -> None:
        self._land = land
        self._lock = threading.Lock()
        self._code: "int | None" = None

    def once(self, result: LiveRunResult) -> int:
        with self._lock:
            if self._code is None:
                self._code = self._land(result)
            return self._code


def _run_with_home(
    *,
    mode: str,
    home: Path,
    out_dir: "Path | None",
    budget_s: float,
    landing: "_Landing",
) -> LiveRunResult:
    from hwpxfiller.webapp import app as webapp_app
    from hwpxfiller.webapp import live_run

    answers: "deque[str]" = deque()
    state: dict = {"result": None, "error": None, "environment": False}
    deadline = Deadline(budget_s)
    #: `main()` 이 정상 반환하면 선다 — 워치독을 **해제**하는 신호(#426 리뷰 P1).
    finished = threading.Event()

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

    def settle(
        observations: dict, sink, error: "str | None", *, environment: bool = False
    ) -> LiveRunResult:
        """사실을 모아 **판정까지 끝낸다**.

        판정이 드라이브 스레드 안에서 끝나야 하는 이유는 워치독 때문이다(#426 리뷰 P1):
        teardown 이 매달리면 ``main()`` 이 영영 반환하지 않고, 판정을 그 뒤에 두면 워치독이
        **판정 없이** 종료 코드를 정한다. 그러면 생성 0건이나 찢긴 컷이 exit 0 으로 지나간다 —
        이 하니스가 막으려는 바로 그 침묵이다.

        ``environment`` 면 사실은 그대로 모으되 **판정을 돌리지 않는다**(#460). 제품에 닿지
        못한 실행의 빈 관측은 제품의 증거가 아니기 때문이다 — 종전에는 여기서도 ``judge()`` 가
        돌아 「HWPX 생성 0건」·「미리보기 미승인」·「〈빈 값〉 미표면」 같은 **제품 언어 7줄**이
        나왔고, 「창이 안 떴다」는 한 줄이 그 밑에 묻혔다. 사람은 첫 줄을 읽지만 무인 판정은
        7줄을 읽고 있지도 않은 제품 결함을 고치러 간다.
        """
        built = report_mod.build(
            mode=mode,
            home=home,
            observations=observations,
            documents=generated_documents(home),
            shots=list(sink.shots) if sink is not None else [],
            unstable=list(sink.unstable) if sink is not None else [],
            geometry=sink.geometry() if sink is not None else {},
            window_size=(WINDOW_W, WINDOW_H),
            elapsed_s=deadline.elapsed_s(),
        )
        verdict = (
            report_mod.environment_verdict(error or "환경 실패")
            if environment
            else report_mod.judge(built, mode=mode)
        )
        report = {**built, "verdict": verdict.as_dict(), "environment": environment}
        if error:
            report["error"] = error
        return LiveRunResult(
            mode=mode,
            ok=verdict.ok and error is None,
            report=report,
            error=error or verdict.reason,
            environment=environment,
        )

    def drive(ctx) -> None:
        window = ctx.window
        observations: dict = {}
        sink = None
        try:
            # 창 부팅은 **제품 단언이 아니라 전제**다 — 우리 예산으로 기다린 뒤에야 창을
            # 만진다. 이 줄이 없으면 아래 첫 호출이 pywebview 의 20초 상수를 먼저 문다(#460).
            _await_window(window, *boot_wait_budget(ctx, deadline))
            _await_bridge(window, deadline)
            window.resize(WINDOW_W, WINDOW_H)
            time.sleep(0.6)
            surface = Surface(window, deadline)
            surface.install_helpers()
            sink = _make_sink(mode, out_dir, webapp_app.WINDOW_TITLE)
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
        except WindowBootFailure as exc:
            # 환경 축 — 제품에 닿지 못했다. settle 이 판정을 건너뛰어 파생 실패를 만들지 않는다.
            state["error"] = str(exc)
            state["environment"] = True
        except Exception as exc:  # noqa: BLE001 — 드라이브 스레드 조용한 증발 금지
            state["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            result = settle(
                observations, sink, state["error"], environment=state["environment"]
            )
            state["result"] = result
            ctx.finish(result.report)  # 증거 파일 = 판정까지 담긴 보고서
            _arm_teardown_watchdog(result, home, finished, landing)

    _arm_run_watchdog(
        home=home,
        finished=finished,
        budget_s=budget_s + RUN_HARD_STOP_MARGIN_S,
        mode=mode,
        landing=landing,
        settle=settle,
    )
    try:
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
    finally:
        # 정상 teardown 이면 워치독을 **해제**한다. 안 그러면 이 함수를 부른 장수 프로세스
        # (pytest 게이트 등)를 10초 뒤 `os._exit` 가 통째로 죽인다(#426 리뷰 P1).
        finished.set()

    result = state["result"]
    if result is None:
        # 드라이버가 아예 돌지 않았다(창 생성 실패 등). 판정 없는 성공은 없다.
        return settle(
            {},
            None,
            state["error"] or "드라이버가 실행되지 않았습니다",
            environment=state["environment"],
        )
    if rc != 0:
        return LiveRunResult(
            mode=result.mode,
            ok=False,
            report=result.report,
            error=f"앱이 rc={rc} 로 끝났습니다 ({result.error or '시나리오는 통과'})",
            environment=result.environment,
        )
    return result


def boot_wait_budget(ctx: object, deadline: Deadline) -> "tuple[float, str]":
    """창 부팅 대기 예산 ``(초, 사유)`` — **이 부팅이 무장한 값을 받아** 여유를 얹고 클램프한다.

    ## 왜 재계산하지 않는가 (#460 리뷰 P1)

    처음에는 이 자리에서 :func:`~hwpxfiller.webapp.boot_budget.decide` 를 다시 불렀다. "제품의
    판정을 받는다"고 적었지만 실제로는 **두 번째 판정자**였고, 판정의 입력을 이 실행 자신이
    바꾼다: ``loaded`` 콜백이 완주 스탬프를 **먼저** 쓰고 그 뒤 두 번의 동기 왕복을 거쳐 show
    하므로(``app.py`` 의 ``_apply_theme_then_show``), 그 사이에 재계산하면 콜드(60s)로 무장한
    부팅을 웜(20s) 예산으로 재게 된다 — 제품 폴백이 살려낼 부팅을 하니스가 먼저 죽인다.

    그래서 값은 :class:`~hwpxfiller.webapp.live_run.LiveContext` 로 **건네받는다**. 판정자는
    하나고, 그 판정이 실제로 무장한 타이머와 같은 수임이 구조로 보장된다.

    ## 왜 클램프하는가 (#460 리뷰 P2)

    부팅 대기가 :class:`Deadline` 밖에 서면 예산 계층 옆에 시계가 하나 더 생긴다 — 이 변경이
    없애려던 형상 그대로다. ``--budget-s`` 를 작게 준 호출자에게는 하드 스톱
    (``budget_s + RUN_HARD_STOP_MARGIN_S``)이 부팅 대기보다 먼저 물어, 워치독이 ``drive()`` 의
    ``finally`` 를 건너뛰고 **환경 분류 없이** 착지한다. :func:`_await_bridge` 가 이미 쓰는
    관용(남은 예산과의 최솟값)을 그대로 따른다.
    """
    armed = float(getattr(ctx, "boot_budget_s", 0.0) or 0.0)
    reason = str(getattr(ctx, "boot_budget_reason", "") or "제품 예산 미전달")
    remaining = max(deadline.remaining_s(), 0.0)
    return min(armed + BOOT_GRACE_S, remaining), reason


def _await_window(window: object, budget_s: float, reason: str) -> None:
    """pywebview 부팅 이벤트를 **우리 예산으로** 먼저 기다린다(#460).

    이것이 없으면 창을 만지는 첫 호출이 pywebview 안에서 **남의 시계**를 문다:
    ``@_api_call`` 의 ``event.wait(20)`` 은 라이브러리 상수라 우리 예산 계층
    (300s → 360s → 420s)에 속하지 않고, 넘기면 ``WebViewException`` 이다.

    실측이 그것을 확정했다(#460): 실패한 CI 실행의 ``elapsed_s`` 21.7초 = 앱 준비 1.7초 +
    정확히 그 20.0초였고, 같은 잡 57표본의 정상 완주는 p90 21.8초 · 최대 27.3초였다. 우리가
    선언한 300초는 발화할 기회조차 없었다 — 천장은 우리 것이 아니었다.

    ``loaded`` 를 먼저 기다린다: 제품은 창을 ``hidden=True`` 로 만들고 ``loaded`` 에서 테마를
    주입한 뒤 show 하므로(FOUC 은닉, #74) 인과 순서가 그렇다. 순서대로 기다려야 **어느 단계에서
    멎었는지**가 진단에 남는다 — 둘을 한 덩어리로 기다리면 "안 떴다"만 남는다.
    """
    end = time.monotonic() + budget_s
    events = getattr(window, "events", None)
    for stage in ("loaded", "shown"):
        event = getattr(events, stage, None)
        if event is None:
            continue  # 이 이벤트를 갖지 않는 대역품 — 기다릴 것이 없다
        if not event.wait(max(end - time.monotonic(), 0.0)):
            raise WindowBootFailure(stage, budget_s, reason)


def _await_bridge(window: object, deadline: Deadline) -> None:
    """준비 신호는 제품 공개 API 다(#372 D-06).

    종전에는 내부 이름 ``window.Nav`` 를 봤는데 그 임시 전역은 N-10 에서 사라졌다.
    ``__hwpx`` 는 합성 루트가 서비스·화면·앱 셸을 **전부 구성한 뒤** 마지막에 거는 이름이라
    준비 신호로 더 정확하다.

    여기까지 왔다는 것은 :func:`_await_window` 가 이미 통과했다는 뜻이므로 — 즉 창은 **실제로**
    떴다 — 아래 실패 문안의 "창은 떴으나"가 비로소 참이다(#460). 종전에는 이 함수가 부팅과
    브리지 두 축을 겸해, 느린 콜드스타트도 「앱이 서지 않았습니다」라는 제품 문장으로 나올
    자리에 있었다.
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


def _dump_stacks(home: Path) -> str:
    """매달림의 유일한 진단 — **로그가 정본**이고 파일은 곁사본이다.

    파일만 남기면 그 파일이 사라지는 경로가 있다(#426 리뷰 라운드 5): 임시 홈에서 도는
    ``check`` 가 시나리오를 완주한 뒤 teardown 만 매달리면, 워치독이 여기 스택을 쓰고 그
    경로를 출력한 다음 **성공 착지가 임시 홈을 통째로 지운다**. 출력된 진단 경로가 존재하지
    않는 상태로 프로세스가 끝나므로, 워치독이 낸 유일한 실행 가능한 증거가 사라진다.

    그래서 stderr 로 먼저 쏟는다 — :func:`_hard_exit` 가 비우고 나가므로 CI 로그에 반드시
    남는다. 파일은 로컬에서 읽기 편하라고 함께 쓰되, 없어질 수 있음을 문안이 밝힌다.
    """
    import faulthandler

    faulthandler.dump_traceback(file=sys.stderr)
    stacks = home / "_live101_hang_stacks.txt"
    try:
        with stacks.open("w", encoding="utf-8") as fh:
            faulthandler.dump_traceback(file=fh)
    except OSError:
        return "위 stderr 스택이 전부입니다(파일로 남기지 못했습니다)"
    return f"위 stderr 스택 · 곁사본 {stacks}(임시 홈이면 정리와 함께 사라질 수 있습니다)"


def _arm_run_watchdog(
    *,
    home: Path,
    finished: "threading.Event",
    budget_s: float,
    mode: str,
    landing: "_Landing",
    settle: "Callable[[dict, object, str], LiveRunResult]",
) -> None:
    """실행 예산의 **하드 백스톱** — 브리지가 멎어도 무는 유일한 이빨(#426 리뷰 라운드 2).

    :class:`~.surface.Deadline` 은 걸음 사이에서만 되짚어진다. 그런데 ``evaluate_js`` 는
    **동기** 호출이라, WebView2 가 멎으면 그 한 번의 호출이 영영 돌아오지 않는다. 그러면
    시한을 다시 볼 기회 자체가 없고, ``drive()`` 는 ``finally`` 에 닿지 못해 증거도 못 쓰고
    teardown 워치독도 무장하지 못한다 — 「조용한 무한 대기 금지」가 정확히 여기서 뚫린다.

    그래서 이 백스톱은 브리지와 **무관한** 스레드에서 시계만 본다. 부드러운 시한이 먼저
    발화할 여유(:data:`RUN_HARD_STOP_MARGIN_S`)를 준 뒤에만 물므로, 구조화된 실패로 착지할
    수 있는 실행은 이쪽까지 오지 않는다.

    종료 전에 :class:`_Landing` 을 지난다 — 강제 종료도 **착지 경로 하나**를 공유한다.
    """

    def _watchdog() -> None:
        if finished.wait(budget_s):
            return  # 실행이 자기 끝에 닿았다 — 물러난다
        where = _dump_stacks(home)
        _say(
            f"101 {mode} 하드 스톱: 실행 예산 {budget_s:.0f}s 안에 끝에 닿지 못했습니다"
            f" (브리지 무응답 의심). 스택 — {where}",
            stream=2,
        )
        landing.once(
            settle({}, None, f"실행 예산 {budget_s:.0f}s 안에 끝에 닿지 못했습니다(브리지 무응답)")
        )
        _hard_exit(ExitCode.RUN_HUNG)

    threading.Thread(target=_watchdog, daemon=True).start()


def _arm_teardown_watchdog(
    result: LiveRunResult, home: Path, finished: "threading.Event", landing: "_Landing"
) -> None:
    """``window.destroy()`` 뒤에도 WinForms 루프가 안 내려오는 pywebview teardown 매달림 대비.

    유예·진단 산출물·exit code 를 **계약으로 적는다**(#423 B). 조용한 무한 대기는 없다.

    셋이 계약의 핵심이다.

    ① **해제 가능하다**(리뷰 라운드 1). ``finished`` 가 서면 조용히 물러난다. 안 그러면
       정상 teardown 뒤에도 ``os._exit`` 가 호출자 프로세스(pytest 게이트)를 통째로 죽인다.
    ② **판정으로 나간다**(리뷰 라운드 1). 종료 코드의 근거는 "시나리오가 예외를 안 냈다"가
       아니라 이미 끝난 판정이다.
    ③ **착지를 지나서 나간다**(리뷰 라운드 3). 요청된 보고서 쓰기·임시 홈 정리 같은 착지
       책임을 여기 복제하지 않는다 — 복제는 매 라운드 하나씩 빠뜨렸다.
    """

    def _watchdog() -> None:
        if finished.wait(TEARDOWN_GRACE_S):
            return  # 정상 teardown — 물러난다
        where = _dump_stacks(home)
        _say(
            f"101 {result.mode}: teardown 이 {TEARDOWN_GRACE_S:.0f}s 안에 안 내려왔습니다"
            f" → 워치독 종료. 스택 — {where}",
            stream=2,
        )
        _hard_exit(landing.once(result))

    threading.Thread(target=_watchdog, daemon=True).start()


def _say(message: str, *, stream: int = 1) -> None:
    """강제 종료 직전의 출력 — 즉시 흘려보낸다."""
    print(message, file=sys.stderr if stream == 2 else sys.stdout, flush=True)


def _hard_exit(code: int) -> None:
    """강제 종료 — **버퍼를 비우고** 나간다. 강제 종료의 **유일한 문**이다.

    ``os._exit`` 는 인터프리터를 그 자리에서 끝내므로 파이썬 스트림 버퍼를 비우지 않는다.
    CI 처럼 stdout 이 파이프로 리다이렉트되면 블록 버퍼링이라, 착지가 낸 요약과 보고서 JSON 이
    **한 글자도 나가지 못한 채** 사라진다(#426 리뷰 라운드 4). 강제 종료를 하는 이유가 진단을
    남기기 위해서인데, 그 진단을 종료가 삼키고 있었다.

    문을 하나로 두면 앞으로 착지가 무엇을 더 출력하든 함께 살아남는다 — 라운드 3 이 착지
    경로를 하나로 접은 것과 같은 이유다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001 — 비우기 실패로 종료를 막지 않는다
            pass
    os._exit(code)
