"""라이브 실행 seam — 사람 대신 제품 창을 모는 **실행 하나의 호출 계약**(N-11A · #423).

제품 창을 띄워 끝까지 몰아 보는 소비자는 둘이다: 부팅 자가검증(``--selftest``)과 Quickstart
101 하니스(``scripts/capture_101_screenshots.py``). 종전에는 계약이라 부를 것이 없었다 —
하니스가 ``app._selftest_drive`` 라는 **모듈 전역을 통째로 갈아끼우고** ``sys.argv`` 를 바꿔
제품 ``main()`` 을 다시 불렀다. 그 관용이 실제로 무엇을 낳았는지가 이 파일의 존재 이유다.

## 왜 인자가 0개인가 — 위치 인자 튜플은 조용히 어긋난다

pywebview 는 ``webview.start(func, args)`` 를 ``Thread(target=func, args=args)`` 로 푼다.
그래서 드라이버의 인자 수는 **호출부의 튜플 길이**가 정한다. #375 가 그 튜플을 ``window`` 에서
``(window, artifact)`` 로 늘렸을 때 제품 드라이버는 같이 늘었지만 캡처 하니스의
``drive(window)`` 는 그대로였다. 결과는 워커 스레드 안의 ``TypeError`` 다 — 드라이버 본문이
한 줄도 안 돌아 ``try/finally`` 도, 증거 쓰기도, 워치독도 실행되지 않고 ``webview.start()`` 가
GUI 루프에서 무한 대기했다. 그 몇 달 동안 ``tests/test_web_runtime_artifact.py`` 는 초록이었다.
**이름이 callable 인지**만 물었기 때문이다(선언은 살고 결과는 죽는다).

그래서 이 파일이 내는 것은 인자를 잘 맞춘 콜러블이 아니라 **인자가 아예 없는** 콜러블이다.
:func:`entrypoint` 의 반환은 0-arity 이고 ``webview.start(fn)`` 은 ``args=None`` 분기로 들어간다.
드라이버가 알아야 할 것은 전부 :class:`LiveContext` 봉투 하나에 실린다 — 봉투에 필드를 더해도
호출부의 arity 는 영원히 0이라, 이번 결함류가 **구조적으로 재발할 수 없다**.

## 왜 등록 시점에 검사하는가

드라이버는 워커 스레드에서 처음 불린다. 계약 위반을 그때 만나면 예외는 ``threading.excepthook``
으로만 새고 호출자는 "창이 안 닫힌다"만 본다. :func:`validate` 는 그 검사를 **조립 시점**으로
당겨 사유를 부른 사람의 스택에 세운다.

## 무엇을 대체할 수 있는가 — native 파일 선택 하나뿐

라이브 실행이 실물 대신 세울 수 있는 표면은 :class:`FileDialogs` 가 전부다. 그 아래 실 로드·
검증·생성 경로는 전부 실물이 돈다. 대화상자를 예외로 둔 이유는 하나다 — OS 모달은 프로그램이
지나갈 방법이 없다. 나머지 확인은 전부 in-page 모달이라 실 클릭으로 지난다.
"""
from __future__ import annotations

import inspect
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import isfinite

#: 이 seam 이 말할 줄 아는 유일한 버전. 다른 값은 협상이 아니라 거절이다.
LIVE_RUN_VERSION = 1
#: live 실행의 안정적인 인프라 종료 축. 호출자가 제품 실패와 분리해 판정한다.
TEARDOWN_HUNG_EXIT_CODE = 7
RUN_HUNG_EXIT_CODE = 8
#: 하위의 구조화된 시한이 먼저 결론을 낼 기회. selftest와 101 hard stop이 함께 쓴다.
RUN_HARD_STOP_MARGIN_S = 60.0


def hard_exit(code: int) -> None:
    """Flush live-run diagnostics before terminating a stuck process."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001 -- 진단 flush 실패로 hard stop을 막지 않는다
            pass
    os._exit(code)


class LiveRunContractError(RuntimeError):
    """라이브 실행 계약 위반 — 워커 스레드가 아니라 **등록 시점**에 난다."""


@dataclass(frozen=True)
class FileDialogs:
    """native 파일·폴더 선택의 대체 — 실물 대신 설 수 있는 **유일한** 표면.

    둘을 함께 요구한다. 종전 하니스는 ``open_file_dialog`` 만 스텁해서 폴더 피커에 닿는 순간
    실 네이티브 창에 매달렸다(그 경로를 밟는 대본이 아직 없었을 뿐이다). 반쪽 대체는 "언젠가
    조용히 멈춘다"를 예약해 두는 것과 같다.
    """

    open_file: "Callable[..., str | None]"
    open_folder: "Callable[..., str | None]"


@dataclass(frozen=True)
class LiveContext:
    """드라이버가 받는 **유일한** 인자. 필드를 더해도 호출부의 arity 는 0으로 남는다."""

    version: int
    run_name: str
    window: object
    artifact: object
    #: 증거 쓰기 → 정식 종료를 이 순서로 정확히 한 번. 두 번째 호출은 시끄럽게 거절된다.
    finish: "Callable[[Mapping[str, object]], None]"
    #: **이 부팅이 실제로 무장한** 폴백 예산(초)과 그 사유(#460 리뷰 P1).
    #:
    #: 값으로 건네는 것이 계약이다 — 드라이버가 같은 판정을 **다시 계산하면 안 된다**. 판정의
    #: 입력(완주 스탬프)을 이 실행 자신이 ``loaded`` 콜백에서 바꾸기 때문이다: 스탬프가 먼저
    #: 쓰이고 그 뒤 두 번의 동기 왕복을 거쳐 show 하므로, 그 사이에 재계산하면 콜드로 무장한
    #: 부팅을 웜 예산으로 재는 창이 열린다. 재계산은 「제품의 판정을 받는다」가 아니라 **두
    #: 번째 판정자**다.
    boot_budget_s: float = 0.0
    boot_budget_reason: str = ""


@dataclass(frozen=True)
class LiveRun:
    """제품 창 하나를 끝까지 모는 실행 한 건의 선언.

    ``capability`` 는 ``window.__hwpxTest`` 부착 여부다. 종전에는 그 판정이
    ``"--selftest" in sys.argv`` 라는 **문자열**이었고, 그래서 창을 빌리려는 다른 소비자가
    같은 플래그를 흉내 내는 순간 시험 능력까지 딸려 왔다 — 101 하니스가 정확히 그랬다.
    이제 두 질문이 갈린다: "이 프로세스가 창을 빌려 도는가"(``run is not None``)와 "이 실행이
    시험 표면을 필요로 하는가"(``run.capability``). 101 은 앞만 참이라 **정상 런타임을 잰다**.
    """

    name: str
    drive: "Callable[[LiveContext], None]"
    #: 이 실행의 증거가 어디로 가는가. 실행마다 다르므로 실행이 들고 온다.
    write_output: "Callable[[Mapping[str, object]], object]"
    capability: bool = False
    file_dialogs: "FileDialogs | None" = None
    #: 앱 host 가 loaded 전/후 경계를 하니스에 알리는 비내구성 관측. 제품 실행에는 없다.
    host_event: "Callable[[str], None] | None" = None
    #: host loaded 대기에 기존 제품 부팅 예산 위로 얹는 하니스 여유.
    host_wait_grace_s: float = 0.0
    version: int = LIVE_RUN_VERSION


def validate(run: object) -> LiveRun:
    """조립 시점 계약 검사. 통과하면 같은 객체를 돌려준다.

    ``*args`` 를 명시적으로 거절하는 이유는 그것이 바로 이 파일이 없애려는 관용이기 때문이다 —
    "몇 개가 오든 받는다"는 드라이버는 계약이 어긋난 사실을 **영원히 숨긴다**.
    """
    if not isinstance(run, LiveRun):
        raise LiveRunContractError(f"LiveRun 이 아닙니다: {type(run).__name__}")
    if run.version != LIVE_RUN_VERSION:
        raise LiveRunContractError(
            f"모르는 live-run 버전입니다: {run.version!r} (아는 것은 {LIVE_RUN_VERSION})"
        )
    if not isinstance(run.name, str) or not run.name.strip():
        raise LiveRunContractError("실행 이름이 비어 있습니다 — 증거가 무엇의 것인지 잃습니다.")
    if not callable(run.drive):
        raise LiveRunContractError(f"드라이버가 콜러블이 아닙니다: {run.drive!r}")
    if not callable(run.write_output):
        raise LiveRunContractError(f"증거 기록기가 콜러블이 아닙니다: {run.write_output!r}")
    if run.host_event is not None and not callable(run.host_event):
        raise LiveRunContractError(f"host_event 가 콜러블이 아닙니다: {run.host_event!r}")
    if not isinstance(run.host_wait_grace_s, (int, float)) or (
        not isfinite(run.host_wait_grace_s) or run.host_wait_grace_s < 0
    ):
        raise LiveRunContractError("host_wait_grace_s 는 0 이상의 유한한 수여야 합니다")
    if run.file_dialogs is not None:
        if not isinstance(run.file_dialogs, FileDialogs):
            raise LiveRunContractError(
                f"file_dialogs 는 FileDialogs 여야 합니다: {type(run.file_dialogs).__name__}"
            )
        # 형태만 보면 `FileDialogs(open_file=None, …)` 가 통과해 **첫 파일 선택에서** 죽는다.
        # 그 시점은 창이 이미 떠 있고 대본이 절반쯤 지난 뒤라, 이 seam 이 등록 시점 실패로
        # 옮겨 오려던 바로 그 늦은 진단이 된다(#425 리뷰 P2).
        for member, answer in (
            ("open_file", run.file_dialogs.open_file),
            ("open_folder", run.file_dialogs.open_folder),
        ):
            if not callable(answer):
                raise LiveRunContractError(
                    f"file_dialogs.{member} 가 콜러블이 아닙니다: {answer!r}"
                )
    _check_drive_arity(run)
    return run


def _check_drive_arity(run: LiveRun) -> None:
    """드라이버가 ``LiveContext`` **하나**만 받는지 본다."""
    try:
        signature = inspect.signature(run.drive)
    except (TypeError, ValueError) as exc:  # 내장·C 콜러블은 서명을 못 준다
        raise LiveRunContractError(
            f"드라이버 서명을 읽을 수 없습니다({exc}) — 계약을 확인할 수 없는 것은 통과시키지 않습니다."
        ) from exc

    parameters = list(signature.parameters.values())
    if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in parameters):
        raise LiveRunContractError(
            f"드라이버가 *args 를 받습니다: {run.name}{signature} — 위치 인자 튜플 관용의 재발입니다."
        )
    required_keyword = [
        p.name
        for p in parameters
        if p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is inspect.Parameter.empty
    ]
    if required_keyword:
        raise LiveRunContractError(
            f"드라이버가 필수 키워드 인자를 요구합니다: {required_keyword} — 봉투는 하나입니다."
        )
    positional = [
        p
        for p in parameters
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    required = [p for p in positional if p.default is inspect.Parameter.empty]
    if len(positional) != 1 or len(required) != 1:
        raise LiveRunContractError(
            f"드라이버는 LiveContext 하나만 받아야 합니다: {run.name}{signature}"
            f" (위치 인자 {len(positional)}개, 필수 {len(required)}개)"
        )


def context_for(
    run: LiveRun,
    *,
    window: object,
    artifact: object,
    finish: "Callable[[Mapping[str, object]], None]",
    boot_budget_s: float = 0.0,
    boot_budget_reason: str = "",
) -> LiveContext:
    """실행 하나의 봉투를 짓는다 — 조립을 한 곳에 모아 필드 누락을 없앤다."""
    return LiveContext(
        version=LIVE_RUN_VERSION,
        run_name=run.name,
        window=window,
        artifact=artifact,
        finish=finish,
        boot_budget_s=boot_budget_s,
        boot_budget_reason=boot_budget_reason,
    )


def entrypoint(run: LiveRun, context: LiveContext) -> "Callable[[], None]":
    """pywebview 에 넘길 **인자 0개** 콜러블.

    ``webview.start(fn)`` 은 ``args`` 가 없으면 ``Thread(target=fn)`` 을 만든다 — 넘길 위치
    인자가 없으므로 호출부와 드라이버가 어긋날 자리가 없다.
    """
    validate(run)
    if context.version != LIVE_RUN_VERSION:
        raise LiveRunContractError(
            f"모르는 컨텍스트 버전입니다: {context.version!r} (아는 것은 {LIVE_RUN_VERSION})"
        )
    if context.run_name != run.name:
        raise LiveRunContractError(
            f"컨텍스트가 다른 실행의 것입니다: {context.run_name!r} != {run.name!r}"
        )
    if not callable(context.finish):
        raise LiveRunContractError("컨텍스트에 종결자가 없습니다 — 증거도 종료도 잃습니다.")

    def _live_entry() -> None:
        run.drive(context)

    _live_entry.__name__ = f"live_run_{run.name.replace('-', '_')}"
    _live_entry.__qualname__ = _live_entry.__name__
    _live_entry.__doc__ = f"live run {run.name!r} 진입점(인자 0개)"
    return _live_entry
