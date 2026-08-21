"""라이브 실행 호출 계약(N-11A · #423) — 이 파일이 막는 결함은 실제로 일어났다.

#375 가 pywebview 로 넘기는 위치 인자를 ``window`` 에서 ``(window, artifact)`` 로 늘렸을 때
제품 드라이버는 같이 늘었지만 ``scripts/capture_101_screenshots.py`` 의 ``drive(window)`` 는
그대로였다. 결과는 워커 스레드 안의 ``TypeError`` — 드라이버 본문이 한 줄도 안 돌아 증거도,
정식 종료도, 워치독도 없이 GUI 루프가 무한 대기했다. 그동안
``tests/test_web_runtime_artifact.py`` 는 초록이었다. **이름이 callable 인지**만 물었기
때문이다(선언은 살고 결과는 죽는다).

그래서 여기서는 이름이 아니라 **부르는 방식**을 센다: 진입점의 인자가 0개인가, 드라이버가
봉투 하나를 받는가, 어긋난 드라이버가 **등록 시점에** 죽는가.
"""
from __future__ import annotations

import inspect
import sys
from types import SimpleNamespace

import pytest

from hwpxfiller.webapp import app as app_mod
from hwpxfiller.webapp import live_run


def _ctx(run: live_run.LiveRun, window: object = None) -> live_run.LiveContext:
    return live_run.context_for(
        run, window=window or object(), artifact=object(), finish=lambda _result: None
    )


def _run(drive=lambda _ctx: None, **kwargs) -> live_run.LiveRun:
    return live_run.LiveRun(
        name=kwargs.pop("name", "probe"),
        drive=drive,
        write_output=kwargs.pop("write_output", lambda _result: None),
        **kwargs,
    )


# --------------------------------------------------------------- 0-arity 진입점


def test_entrypoint_takes_no_positional_arguments() -> None:
    """진입점의 인자는 **0개**다 — 위치 인자가 없으면 어긋날 자리도 없다.

    ``webview.start(fn)`` 은 ``args`` 가 없을 때 ``Thread(target=fn)`` 을 만든다. 봉투에
    필드를 더해도 이 수는 영원히 0이라, #375 가 낸 결함류가 구조적으로 재발할 수 없다.
    """
    run = _run()
    entry = live_run.entrypoint(run, _ctx(run))

    assert list(inspect.signature(entry).parameters) == []
    entry()  # 실제로 부를 수 있다 — 서명만 맞고 못 부르는 것을 통과시키지 않는다


def test_driver_receives_exactly_one_envelope() -> None:
    """드라이버가 받는 것은 :class:`~hwpxfiller.webapp.live_run.LiveContext` 하나다."""
    seen: "list[object]" = []
    run = _run(drive=seen.append)
    context = _ctx(run)

    live_run.entrypoint(run, context)()

    assert seen == [context]
    assert isinstance(seen[0], live_run.LiveContext)
    assert seen[0].run_name == "probe"


def test_main_hands_the_window_over_with_no_positional_arguments(monkeypatch, tmp_path) -> None:
    """``main()`` 이 실제로 ``webview.start`` 를 부르는 모양까지 잰다.

    계약 객체만 시험하면 "제품이 그 계약을 쓰는가"는 여전히 아무도 안 본다 — 그 침묵이
    이번 결함의 절반이었다. 그래서 가짜 ``webview`` 로 호출 인자를 실측한다.
    """
    started: "list[tuple[tuple, dict]]" = []

    def fake_start(*args, **kwargs):
        started.append((args, kwargs))

    window = _FakeWindow()
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(
            create_window=lambda *a, **k: window,
            start=fake_start,
        ),
    )
    _stub_app_boot(monkeypatch, tmp_path)

    order: "list[str]" = []
    client = SimpleNamespace(
        describe=lambda _events: order.append("theme:describe"),
        preferences=lambda *_args: order.append("theme:preferences")
        or SimpleNamespace(ok=True, failure_text=None),
    )
    monkeypatch.setattr(
        app_mod.product_api,
        "ProductApiClient",
        SimpleNamespace(for_window=lambda _window: client),
    )
    assert app_mod.main(
        argv=[],
        live=_run(
            drive=lambda _ctx: order.append("drive"),
            name="harness",
            host_event=lambda event: order.append(f"host:{event}"),
            host_wait_grace_s=15.0,
        ),
    ) == 0

    (positional, keywords) = started[0]
    assert len(positional) == 1, f"위치 인자가 하나(진입점)여야 한다: {positional!r}"
    assert "args" not in keywords, "pywebview 에 인자 튜플을 넘기면 arity 드리프트가 돌아온다"
    assert list(inspect.signature(positional[0]).parameters) == []

    positional[0]()
    assert window.events.loaded.timeouts == [16.0]
    assert window.events.loaded.handlers == [], "live 에 비동기 loaded 핸들러를 함께 달았습니다"
    assert order == [
        "host:loaded",
        "theme:describe",
        "theme:preferences",
        "host:ready",
        "drive",
    ]


def test_live_host_timeout_reaches_the_driver_without_touching_the_bridge(
    monkeypatch, tmp_path
) -> None:
    """loaded 미도달만 구조화된 boot-hang 사건으로 넘기며 theme bridge 는 열지 않는다."""
    started: list = []
    window = _FakeWindow(loaded=False)
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(
            create_window=lambda *a, **k: window,
            start=lambda entry, **kwargs: started.append(entry),
        ),
    )
    _stub_app_boot(monkeypatch, tmp_path)
    order: "list[str]" = []
    fallback: "list[object]" = []
    alerts: "list[str]" = []
    notices: "list[str]" = []

    class _Timer:
        daemon = False

        def __init__(self, _seconds, callback) -> None:
            fallback.append(callback)

        def start(self) -> None:
            pass

        def cancel(self) -> None:
            pass

    monkeypatch.setattr(app_mod.threading, "Timer", _Timer)
    monkeypatch.setattr(app_mod.settings, "alert", alerts.append)
    monkeypatch.setattr(
        app_mod.product_api,
        "ProductApiClient",
        SimpleNamespace(
            for_window=lambda _window: SimpleNamespace(notice=notices.append)
        ),
    )

    run = _run(
        drive=lambda _ctx: order.append("drive"),
        host_event=lambda event: order.append(f"host:{event}"),
        host_wait_grace_s=15.0,
    )
    assert app_mod.main(argv=[], live=run) == 0
    fallback[0]()
    started[0]()

    assert window.events.loaded.timeouts == [16.0]
    assert order == ["host:timeout", "drive"]
    assert len(alerts) == 1 and notices == [], "live fallback이 WebView bridge를 다시 열었습니다"


# ------------------------------------------------------------ 등록 시점 음성 대조


@pytest.mark.parametrize(
    ("drive", "fragment"),
    [
        (lambda window, artifact: None, "LiveContext 하나만"),  # 이번 결함 그 자체
        (lambda: None, "LiveContext 하나만"),
        (lambda *args: None, "*args"),
        (lambda ctx, *, out: None, "필수 키워드"),
    ],
)
def test_a_mismatched_driver_dies_at_registration(drive, fragment) -> None:
    """어긋난 드라이버는 **워커 스레드가 아니라 여기서** 죽는다.

    스레드 안에서 죽으면 예외는 ``threading.excepthook`` 으로만 새고 호출자는 "창이 안
    닫힌다"만 본다 — #423 이 몇 달 동안 보이지 않은 이유다.
    """
    with pytest.raises(live_run.LiveRunContractError) as excinfo:
        live_run.validate(_run(drive=drive))

    assert fragment in str(excinfo.value)


def test_main_refuses_a_mismatched_run_before_touching_the_window(monkeypatch, tmp_path) -> None:
    """계약 위반이면 창을 **만들기도 전에** 죽는다 — 반쯤 뜬 창을 남기지 않는다."""
    created: "list[object]" = []
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(
            create_window=lambda *a, **k: created.append(a) or _FakeWindow(),
            start=lambda *a, **k: None,
        ),
    )
    _stub_app_boot(monkeypatch, tmp_path)

    with pytest.raises(live_run.LiveRunContractError):
        app_mod.main(argv=[], live=_run(drive=lambda window, artifact: None))

    assert created == []


def test_contract_rejects_unknown_versions_and_foreign_envelopes() -> None:
    """미지 버전과 남의 봉투는 해석하지 않는다 — 조용한 강등 경로를 두지 않는다."""
    with pytest.raises(live_run.LiveRunContractError):
        live_run.validate(_run(version=99))
    with pytest.raises(live_run.LiveRunContractError):
        live_run.validate(SimpleNamespace(name="x", drive=lambda ctx: None))

    run = _run(name="a")
    other = live_run.context_for(
        _run(name="b"), window=object(), artifact=object(), finish=lambda _r: None
    )
    with pytest.raises(live_run.LiveRunContractError):
        live_run.entrypoint(run, other)

    stale = live_run.LiveContext(
        version=99, run_name="a", window=object(), artifact=object(), finish=lambda _r: None
    )
    with pytest.raises(live_run.LiveRunContractError, match="컨텍스트 버전"):
        live_run.entrypoint(run, stale)

    without_terminator = live_run.LiveContext(
        version=live_run.LIVE_RUN_VERSION,
        run_name="a",
        window=object(),
        artifact=object(),
        finish=None,  # type: ignore[arg-type]
    )
    with pytest.raises(live_run.LiveRunContractError, match="종결자"):
        live_run.entrypoint(run, without_terminator)


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"name": "  "}, "실행 이름"),
        ({"drive": "not-callable"}, "콜러블이 아닙니다"),
        ({"write_output": "not-callable"}, "증거 기록기"),
        ({"host_event": "not-callable"}, "host_event"),
        ({"host_wait_grace_s": -1.0}, "음수"),
        ({"file_dialogs": ("open", "folder")}, "FileDialogs"),
        # 형태만 보면 통과해 **첫 파일 선택에서** 죽는다 — 창이 이미 뜬 뒤의 늦은 진단이다.
        (
            {"file_dialogs": live_run.FileDialogs(open_file=None, open_folder=lambda *a: None)},
            r"file_dialogs\.open_file",
        ),
        (
            {"file_dialogs": live_run.FileDialogs(open_file=lambda *a: None, open_folder=None)},
            r"file_dialogs\.open_folder",
        ),
    ],
)
def test_contract_names_the_malformed_field(kwargs, fragment) -> None:
    """무엇이 틀렸는지 **이름을 대며** 거절한다 — 조립 실수가 한 줄로 읽혀야 한다."""
    with pytest.raises(live_run.LiveRunContractError, match=fragment):
        live_run.validate(_run(**kwargs))


def test_an_unreadable_signature_is_refused_not_assumed() -> None:
    """서명을 못 읽는 콜러블은 "아마 맞겠지"로 통과시키지 않는다.

    확인할 수 없는 계약을 통과시키면 그 실행은 워커 스레드에서만 진실을 말한다 — 이 파일이
    막으려는 바로 그 자리다.
    """

    def opaque(ctx) -> None:  # pragma: no cover — 서명 판독 단계에서 거절된다
        pass

    opaque.__signature__ = "서명이 아니다"  # type: ignore[attr-defined]

    with pytest.raises(live_run.LiveRunContractError, match="서명을 읽을 수 없습니다"):
        live_run.validate(_run(drive=opaque))


# ------------------------------------------------------------------ 종결자


def test_terminator_writes_then_destroys_exactly_once() -> None:
    """증거 쓰기 **다음** 종료, 그리고 **거래 전체가** 한 번.

    op 각각의 가드에 기대면 두 번째 호출이 쓰기를 먼저 통과해 첫 증거를 **덮어쓴 뒤** 종료
    거절 로그만 남긴다 — 실행의 결론이 조용히 바뀌고, 남는 진단은 "종료를 두 번 불렀다"는
    엉뚱한 것이 된다(#425 리뷰 P2). 종결은 실행 하나의 결론을 확정하는 사건이라 그 결론은
    처음 것이어야 한다.
    """
    order: "list[str]" = []
    window = _FakeWindow(on_destroy=lambda: order.append("destroy"))

    finish = app_mod._live_terminator(window, lambda result: order.append(f"write:{result}"))
    finish({"ok": True})

    assert order == ["write:{'ok': True}", "destroy"]
    assert window.destroyed == 1

    finish({"ok": False, "error": "늦게 도착한 결론"})

    assert order == ["write:{'ok': True}", "destroy"], "두 번째 결론이 증거를 덮어쓰면 안 된다"
    assert window.destroyed == 1


def test_a_refused_second_finish_names_what_it_dropped(capsys) -> None:
    """두 번째 종결 요청은 조용한 no-op 이 아니다 — 무엇을 버렸는지 이름을 댄다.

    채널은 **내구성 경보**(stderr + 홈 로그)여야 한다. 종전 두 실패가 쓰던
    ``hwpxfiller.host.native.debug.log`` 는 ``HWPX_WEBAPP_LOG`` 없이는 no-op 이라, 사유를 남긴다고
    적힌 주석이 실제로는 아무 데도 남기지 않았다(선언은 살고 결과는 죽는다).
    """
    finish = app_mod._live_terminator(_FakeWindow(), lambda _result: None)
    finish({"captured": []})
    finish({"error": "두 번째"})

    logged = capsys.readouterr().err
    assert "already_consumed" in logged
    assert "['captured']" in logged, "확정된 결론이 무엇이었는지"
    assert "['error']" in logged, "버려진 것이 무엇인지"


def test_a_failed_evidence_write_is_alarmed_not_swallowed(capsys) -> None:
    """증거를 못 쓰면 하니스는 파일 부재만 본다 — 사유가 없으면 원인이 한 겹 가려진다."""

    def refuse(_result):
        raise OSError("디스크가 가득 찼다")

    app_mod._live_terminator(_FakeWindow(), refuse)({"ok": True})

    logged = capsys.readouterr().err
    assert "output_write 실패" in logged
    assert "디스크가 가득 찼다" in logged


def test_selftest_context_is_the_same_assembly_main_uses() -> None:
    """단위 시험과 ``main()`` 이 **같은 조립**을 쓴다 — 봉투가 한쪽만 낡지 않게."""
    assert "live_run.context_for(" in inspect.getsource(app_mod._selftest_context)
    assert "live_run.context_for(" in inspect.getsource(app_mod.main)

    context = app_mod._selftest_context(_FakeWindow())
    assert context.run_name == "selftest"
    assert callable(context.finish)


# ---------------------------------------------------- 능력·프로세스 상태 불변


def test_a_window_borrowing_run_does_not_install_the_test_surface(monkeypatch, tmp_path) -> None:
    """창만 빌리는 실행에는 ``window.__hwpxTest`` 가 서지 않는다(#372 D-07).

    파사드가 ``js_api`` 에 붙지 않으면 프런트의 ``testHost.available()`` 이 거짓이 되어
    전역이 아예 서지 않는다. 101 하니스는 그래서 **정상 런타임**을 찍는다.
    """
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(create_window=lambda *a, **k: _FakeWindow(), start=lambda *a, **k: None),
    )
    frontends = _stub_app_boot(monkeypatch, tmp_path)

    assert app_mod.main(argv=[], live=_run(name="quickstart-101")) == 0
    assert not hasattr(frontends[-1], "selftest_claim")

    assert app_mod.main(argv=["app", "--selftest"]) == 0
    assert hasattr(frontends[-1], "selftest_claim")


def test_a_live_run_never_mutates_process_state(monkeypatch, tmp_path) -> None:
    """``sys.argv`` 도 대화상자 대체도 실행 뒤에 남지 않는다.

    종전 하니스는 ``sys.argv`` 를 통째로 덮어썼다(프로세스 전역이라 그 뒤 어떤 코드도 원래
    인자를 볼 수 없었다). 대체 대화상자가 남으면 같은 프로세스의 다음 실행이 실물 대신
    답변 큐를 본다 — 조용히 틀린다.
    """
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(create_window=lambda *a, **k: _FakeWindow(), start=lambda *a, **k: None),
    )
    _stub_app_boot(monkeypatch, tmp_path)
    before = list(sys.argv)

    dialogs = live_run.FileDialogs(open_file=lambda *a, **k: None, open_folder=lambda *a, **k: None)
    assert app_mod.main(argv=[], live=_run(file_dialogs=dialogs)) == 0

    assert sys.argv == before
    assert app_mod._live_file_dialogs is None


def test_native_dialogs_have_a_single_entrance(monkeypatch) -> None:
    """대체가 붙으면 **모든** native 대화상자가 그것을 지난다.

    종전 하니스는 ``open_file_dialog`` 만 갈아끼웠고, 그래서 폴더 피커에 닿는 순간 실
    네이티브 창에 매달렸다(그 경로를 밟는 대본이 아직 없었을 뿐이다).
    """
    answered: "list[str]" = []
    monkeypatch.setattr(
        app_mod,
        "_live_file_dialogs",
        live_run.FileDialogs(
            open_file=lambda filters, owner_title=None: answered.append("file") or "F",
            open_folder=lambda title, owner_title=None: answered.append("folder") or "D",
        ),
    )

    assert app_mod._file_dialog([("x", "*.x")]) == "F"
    assert app_mod._folder_dialog("고르세요") == "D"
    assert answered == ["file", "folder"]


# ------------------------------------------------------------------ 대역


class _Event:
    """pywebview 이벤트 슬롯 대역 — ``window.events.X += handler`` 를 받는다."""

    def __init__(self, fired: bool = True) -> None:
        self.handlers: "list[object]" = []
        self.fired = fired
        self.timeouts: "list[float | None]" = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def wait(self, timeout=None) -> bool:  # noqa: ARG002 — pywebview Event 계약 대역
        self.timeouts.append(timeout)
        return self.fired


class _FakeWindow:
    def __init__(self, on_destroy=None, *, loaded: bool = True) -> None:
        self.destroyed = 0
        self.events = SimpleNamespace(
            loaded=_Event(loaded),
            resized=_Event(),
            moved=_Event(),
            maximized=_Event(),
            restored=_Event(),
            closing=_Event(),
            closed=_Event(),
        )
        self._on_destroy = on_destroy

    def destroy(self) -> None:
        self.destroyed += 1
        if self._on_destroy is not None:
            self._on_destroy()

    def show(self) -> None:  # pragma: no cover — 폴백 표시 경로
        pass

    def evaluate_js(self, _script):  # pragma: no cover — 이 파일은 문서 안을 재지 않는다
        return None


def _stub_app_boot(monkeypatch, tmp_path) -> "list[object]":
    """창 부팅의 바깥 세계(산출물·홈·타이머)를 대역으로 세운다.

    ``WebFrontend`` 인스턴스를 모아 돌려준다 — 시험 능력이 **어느 인스턴스에** 붙었는지가
    능력 판정의 실물이기 때문이다.
    """
    frontends: "list[object]" = []
    real_frontend = app_mod.WebFrontend

    def record(*args, **kwargs):
        made = real_frontend(*args, **kwargs)
        frontends.append(made)
        return made

    monkeypatch.setattr(app_mod, "WebFrontend", record)
    monkeypatch.setattr(
        app_mod,
        "web_artifact",
        lambda: SimpleNamespace(
            artifact_id="a", tree_sha256="t", root=tmp_path, index_path=tmp_path / "index.html"
        ),
    )
    monkeypatch.setattr(app_mod.settings, "load_window_geometry", lambda: None)
    monkeypatch.setattr(app_mod, "_prepare_webview_profile", lambda root: tmp_path / "profile")
    monkeypatch.setattr(app_mod.boot_budget, "decide", lambda *a, **k: (1.0, "test"))
    return frontends
