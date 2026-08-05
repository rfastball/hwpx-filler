"""마일스톤 I 설정 존중·개인화 정적/순수 계약(#221)."""
from __future__ import annotations

from types import SimpleNamespace

from _web_source import (
    REPO_ROOT,
    SOURCE_INDEX,
    SOURCE_JS_DIR,
    app_css,
    reaches_product_graph,
    source_text,
)
from hwpxfiller.webapp import app as app_mod
from hwpxfiller.webapp import live_run
from hwpxfiller.webapp.app import _geometry_is_visible


def test_saved_window_geometry_rejects_offscreen_titlebar() -> None:
    screen = (0, 0, 1920, 1080)
    visible = {"x": 1840, "y": 20, "width": 1180, "height": 820, "maximized": False}
    offscreen = {"x": 2200, "y": 20, "width": 1180, "height": 820, "maximized": False}
    assert _geometry_is_visible(visible, screen) is True
    assert _geometry_is_visible(offscreen, screen) is False


def test_saved_window_geometry_handles_unavailable_and_invalid_screens(monkeypatch) -> None:
    geometry = {"x": 20, "y": 20, "width": 1180, "height": 820, "maximized": False}
    monkeypatch.setattr(app_mod, "_virtual_screen_bounds", lambda: None)
    assert _geometry_is_visible(geometry) is True
    assert _geometry_is_visible(geometry, (0, 0, 0, 1080)) is False
    assert _geometry_is_visible(geometry, (0, 0, 1920, -1)) is False


def test_saved_window_geometry_checks_every_titlebar_edge() -> None:
    screen = (0, 0, 1920, 1080)
    base = {"x": 20, "y": 20, "width": 1180, "height": 820, "maximized": False}
    assert _geometry_is_visible({**base, "x": -1200}, screen) is False
    assert _geometry_is_visible({**base, "x": 1920}, screen) is False
    assert _geometry_is_visible({**base, "y": -32}, screen) is False
    assert _geometry_is_visible({**base, "y": 1080}, screen) is False


def test_saved_window_geometry_keeps_partially_offscreen_but_usable_position() -> None:
    """#276 리뷰 — 판정은 제목줄 **전체 폭**과 화면의 겹침: 왼쪽 64px 조각만 보면
    왼쪽 모서리가 64px 넘게 밖인(그러나 제목줄 대부분이 보이는) 창을 미가시로 오판해
    쓸 만한 저장 위치를 버리고 다음 부팅이 창을 예고 없이 리셋한다."""
    screen = (0, 0, 1920, 1080)
    base = {"y": 20, "width": 1180, "height": 820, "maximized": False}
    # 왼쪽으로 100px 밀림 — 제목줄 1080px 이 화면 안(잡을 수 있음) → 보존.
    assert _geometry_is_visible({**base, "x": -100}, screen) is True
    # 오른쪽 가장자리 걸침 — 겹침 60px(<64) → 리셋(잡기엔 부족).
    assert _geometry_is_visible({**base, "x": 1860}, screen) is False
    # 겹침이 정확히 64px 이면 보존(경계 포함).
    assert _geometry_is_visible({**base, "x": 1856}, screen) is True


def test_virtual_screen_bounds_handles_platform_metrics_and_api_failure(monkeypatch) -> None:
    import ctypes
    from types import SimpleNamespace

    monkeypatch.setattr(app_mod.sys, "platform", "linux")
    assert app_mod._virtual_screen_bounds() is None

    values = {76: -1920, 77: 0, 78: 3840, 79: 1080}

    class User32:
        def GetSystemMetrics(self, metric):
            return values[metric]

    monkeypatch.setattr(app_mod.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=User32()), raising=False)
    assert app_mod._virtual_screen_bounds() == (-1920, 0, 3840, 1080)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(), raising=False)
    assert app_mod._virtual_screen_bounds() is None


def test_personalization_bridge_setters_delegate_and_return_values(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(app_mod.settings, "save_font_scale", lambda value: calls.append(("scale", value)))
    monkeypatch.setattr(app_mod.settings, "save_master_width", lambda value: calls.append(("width", value)))
    frontend = object.__new__(app_mod.WebFrontend)
    assert frontend.set_font_scale("large") == "large"
    assert frontend.set_master_width(333) == 333
    assert calls == [("scale", "large"), ("width", 333)]
    # 레일 접기는 셸 교체와 함께 사망(F2 PR-B) — 브리지 표면에 남으면 표면 없는 설정을 쓰는
    # 통로가 되고, 그 통로가 다음 세션에 레일을 되살린다(지도 §10.9 판정 F 와 같은 규율).
    assert not hasattr(app_mod.WebFrontend, "set_rail_collapsed")


#: 프로토콜 대역이 돌려주는 성공 시작 봉투 — 실제 `api.js` 가 내는 모양 그대로.
_START_OK = {
    "ok": True, "action": "start", "runId": "r-1",
    "state": "running", "mode": "?", "deadlineMs": 75000,
}


class _ProtocolWindow:
    """``window.__hwpxTest`` 프로토콜을 말하는 최소 창 대역.

    종전 이 파일의 대역들은 **프로브 표현식**에 반응했다(``"pywebview" in script`` 로 준비
    폴링을 흉내내는 식). N-09 이후 파이썬이 보내는 표현식은 셋뿐이므로 대역도 그 셋만 안다:
    준비 확인 · ``start`` · ``poll``. 그 밖의 표현식이 오면 **시끄럽게 실패**한다 — 조용히
    ``True`` 를 돌려주면 파이썬이 몰래 새 통로를 열어도 이 대역이 눈감아 준다.
    """

    def __init__(self, *, poll, readiness=1, raise_on=None):
        self.scripts: "list[str]" = []
        self.destroyed = 0
        self._poll = poll
        self._readiness = readiness
        self._raise_on = raise_on

    def evaluate_js(self, script):
        self.scripts.append(script)
        if self._raise_on is not None and self._raise_on in script:
            raise RuntimeError("bridge failed")
        if '"action": "start"' in script:
            return dict(_START_OK)
        if '"action": "poll"' in script:
            return self._poll
        if "window.__hwpxTest.version" in script:
            return self._readiness
        raise AssertionError(f"계약 밖 표현식: {script[:120]!r}")

    def destroy(self):
        self.destroyed += 1


def _drive_selftest(window: object) -> None:
    """드라이버를 **제품과 같은 조립**으로 부른다(N-11A · #423).

    종전에는 ``app_mod._selftest_drive(window)`` 였다. 그때 드라이버의 인자는 pywebview 가
    넘기는 위치 인자 튜플이었고, 그 튜플이 길어진 #375 에서 캡처 하니스와 조용히 어긋났다.
    이제 인자는 봉투 하나이고, 이 헬퍼가 ``main()`` 과 같은 :func:`app_mod._selftest_context`
    를 쓴다 — 두 곳이 각자 봉투를 지으면 필드가 늘 때 한쪽만 낡는다.
    """
    app_mod._selftest_drive(app_mod._selftest_context(window))


def _capture_selftest(monkeypatch) -> "list[dict]":
    """드라이버가 쓰려 한 증거를 가로챈다.

    가로채는 자리가 ``_finish_selftest`` 에서 ``_write_selftest_output`` 으로 바뀌었다 —
    N-09 에서 쓰기와 종료가 두 책임으로 갈렸고, 드라이버는 그 둘을 호스트 연산 허용목록으로
    각각 부른다. 합친 이름(``_finish_selftest``)은 N-11A 에서 사라졌다 — 101 하니스가
    직접 부르던 seam 이었고, 이제 두 실행이 같은 종결자(:func:`app_mod._live_terminator`)를
    지난다.
    """
    captured: "list[dict]" = []
    monkeypatch.setattr(
        app_mod, "_write_selftest_output", lambda result: captured.append(dict(result))
    )
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    for name in (
        "HWPX_SELFTEST_SET_THEME",
        "HWPX_SELFTEST_SET_FONT_SCALE",
        "HWPX_SELFTEST_GEOMETRY_ONLY",
        "HWPX_SELFTEST_NO_CAPABILITY",
        "HWPX_SELFTEST_OFFLINE_PROBE",
    ):
        monkeypatch.delenv(name, raising=False)
    return captured


def _poll_ok(evidence: dict) -> dict:
    return {
        "ok": True, "action": "poll", "runId": "r-1", "state": "succeeded",
        "mode": "?", "evidence": evidence, "order": [], "timings": {},
        "elapsedMs": 10, "deadlineMs": 75000,
    }


def test_font_scale_selftest_echoes_the_request_and_carries_the_readback(monkeypatch) -> None:
    """쓰기 모드 증거는 **에코 키 + 디스크 되읽기** 정확히 둘이다.

    에코(``font_scale_write``)는 파이썬 드라이버가 세우고 되읽기(``set_result``)는 프런트
    프로브가 ``settings_readback`` 호스트 연산으로 얻는다. 정확한 dict 동치를 유지하는
    이유는 종전과 같다 — 키가 하나 늘거나 줄면 ``packaging/build.ps1`` 의 책임 수 게이트가
    릴리스에서 터진다.
    """
    captured = _capture_selftest(monkeypatch)
    monkeypatch.setenv("HWPX_SELFTEST_SET_FONT_SCALE", "large")
    window = _ProtocolWindow(poll=_poll_ok({"set_result": "large"}))

    _drive_selftest(window)

    assert captured == [{"font_scale_write": "large", "set_result": "large"}]
    assert window.destroyed == 1, "정식 종료가 정확히 한 번이어야 한다"


def test_theme_selftest_echoes_the_request_and_carries_the_readback(monkeypatch) -> None:
    """테마 쓰기도 같은 모양이다 — 종전 정확한 dict 동치를 그대로 잇는다."""
    captured = _capture_selftest(monkeypatch)
    monkeypatch.setenv("HWPX_SELFTEST_SET_THEME", "dark")
    window = _ProtocolWindow(poll=_poll_ok({"set_result": "dark"}))

    _drive_selftest(window)

    assert captured == [{"theme_write": "dark", "set_result": "dark"}]


def test_selftest_reports_a_missing_facade_as_a_loud_error(monkeypatch) -> None:
    """능력이 없으면 **조용히 빈 증거**가 아니라 ``error`` 다.

    종전 "브리지 준비 시한 초과" 단언의 후계다. 그때는 파이썬이 직접 폴링했고 지금은 준비
    확인이 ``null`` 을 받는다 — 사건은 같다("구동할 것이 거기 없다"). 이 테스트와 아래
    평가 실패 테스트는 ``error`` 키의 **유일한 양성 대조**라, 없어지면 실앱 게이트의
    ``"error" not in result`` 가 무엇을 지키는지 아무도 확인하지 못한다.
    """
    captured = _capture_selftest(monkeypatch)
    monkeypatch.setenv("HWPX_SELFTEST_SET_FONT_SCALE", "larger")
    window = _ProtocolWindow(poll=None, readiness=None)

    _drive_selftest(window)

    assert "error" in captured[0]
    assert "facade-absent" in captured[0]["error"]
    # 에코는 실패해도 남는다 — 무엇을 시도했는지 잃으면 실패를 읽을 수 없다.
    assert captured[0]["font_scale_write"] == "larger"


def test_selftest_reports_an_evaluation_failure_as_a_loud_error(monkeypatch) -> None:
    """평가기가 던지면 그 사유가 증거의 ``error`` 로 재진술된다(종전 repr 통과 계약)."""
    captured = _capture_selftest(monkeypatch)
    monkeypatch.setenv("HWPX_SELFTEST_SET_FONT_SCALE", "large")
    window = _ProtocolWindow(poll=None, raise_on='"action": "start"')

    _drive_selftest(window)

    assert "bridge failed" in captured[0]["error"]


def test_failed_run_keeps_the_evidence_and_its_error(monkeypatch) -> None:
    """프로브가 실패한 실행도 **증거를 들고** 돌아온다.

    러너의 ``toEvidence`` 가 실패한 프로브의 키를 빼고 ``error`` 를 세운 그 객체다. 여기서
    증거를 버리면 실앱 게이트는 파일 부재만 보고 "창이 안 떴다"로 읽는다 — 원인이 한 겹
    가려진다. 실패는 **증거와 함께** 시끄러워야 한다.
    """
    captured = _capture_selftest(monkeypatch)
    window = _ProtocolWindow(poll={
        "ok": False, "code": "run_failed", "action": "poll", "runId": "r-1",
        "state": "failed", "mode": "full",
        "evidence": {"job_on": True, "error": "[preserve/run/probe_threw] 계약 위반"},
        "errors": [{"probe": "preserve", "phase": "run", "code": "probe_threw"}],
        "skipped": [], "order": [], "timings": {}, "elapsedMs": 12, "deadlineMs": 75000,
    })

    _drive_selftest(window)

    assert captured[0]["job_on"] is True, "성공한 프로브의 키는 살아 있어야 한다"
    assert "probe_threw" in captured[0]["error"]


def test_window_geometry_host_op_derives_maximized_like_from_the_real_expression() -> None:
    """``maximized_like`` 판정은 **호스트가** 진다 — 주입된 실 표현식으로 잰다.

    종전 ``_selftest_drive`` 안에 있던 수치가 ``window_geometry`` 호스트 연산으로 옮겨갔다.
    프런트가 다시 조립하면 같은 상태를 두 곳이 판정하게 되므로 자리를 옮기되 소유는 그대로다.
    양성·음성 두 값으로 세워 "언제나 참"이 통과하지 못하게 한다.
    """
    maximized = {
        "x": 0, "y": 0, "width": 1920, "height": 1080,
        "avail_x": 0, "avail_y": 0, "avail_width": 1920, "avail_height": 1080,
    }
    windowed = {
        "x": 100, "y": 100, "width": 1000, "height": 700,
        "avail_x": 0, "avail_y": 0, "avail_width": 1920, "avail_height": 1080,
    }

    def geometry_window(measured: dict, seen: "list[str]") -> object:
        """루프 변수를 **인자로 묶는다** — 클로저로 잡으면 두 회차가 같은 값을 본다."""

        class Window:
            def evaluate_js(self, script):
                seen.append(script)
                return measured

        return Window()

    for measured, expected in ((maximized, True), (windowed, False)):
        seen: "list[str]" = []
        window = geometry_window(measured, seen)
        operations = app_mod._selftest_host_operations(
            lambda bound=window: bound,
            lambda: SimpleNamespace(artifact_id="a" * 64, tree_sha256="b" * 64),
        )
        result = operations.dispatch("window_geometry", {})

        assert result.ok, result.detail
        assert result.value["maximized_like"] is expected
        # 주입된 표현식이 곧 계약이다 — 문서 밖(네이티브 프레임)만 읽는다.
        assert seen == [app_mod._WINDOW_GEOMETRY_JS]
        assert "screen.avail" in seen[0]


def test_host_surface_offers_exactly_what_the_probes_may_request() -> None:
    """프런트에 대는 연산은 여섯이고, **출력 쓰기·창 종료는 거기 없다**.

    페이지 쪽에 증거 파일 쓰기나 창 종료를 대주면 그것이 곧 통로가 된다. 능력을 주지 않는
    것이 "요청은 거절된다"보다 강하다.
    """
    operations = app_mod._selftest_host_operations(
        lambda: None, lambda: SimpleNamespace(artifact_id="a" * 64, tree_sha256="b" * 64)
    )

    assert set(operations.provides()) == {
        "input_select", "window_resize", "window_geometry",
        "current_url", "artifact_identity", "settings_readback",
    }
    assert "output_write" not in operations.provides()
    assert "window_destroy" not in operations.provides()


def test_write_mode_bridge_expressions_moved_to_the_frontend_probe() -> None:
    """실사용 경로(``Theme.set``·``Personalization.setFontScale``)를 그대로 구동하는가.

    종전 이 파일이 파이썬 표현식 문자열에서 확인하던 계약이다. API 직접 호출로 바꾸면
    ``theme.js``/``personalization.js`` 의 결함이 무커버가 되므로, 자리가 옮겨간 뒤에도
    **같은 홉을 지나는지**를 후계 소스에서 센다.
    """
    probe_js = source_text("src", "selftest", "probes", "persistence_geometry.js")

    assert "Personalization.setFontScale" in probe_js
    assert "Theme.set" in probe_js
    # 준비 폴링도 함께 옮겨갔다 — 브리지가 아직 없을 때 조용한 no-op 이 되던 자리(#75 리뷰 #5).
    assert "pywebview" in probe_js


def test_capability_is_attached_only_when_the_run_asks_for_it() -> None:
    """시험 파사드는 **실행이 명시로 요구할 때만** 붙는다 — URL·빌드 플래그는 조건이 아니다.

    종전 조건은 ``"--selftest" in argv`` 라는 문자열이었고, 그래서 창만 빌리려는 실행(101
    하니스)이 같은 플래그를 흉내 내는 순간 시험 능력까지 딸려 왔다. 이제 두 질문이 갈린다 —
    "창을 빌려 도는가"와 "시험 표면이 필요한가"(#423 · D-07).
    """
    selftest = app_mod._selftest_live_run()
    harness = live_run.LiveRun(  # 101 처럼 창만 빌리는 실행
        name="quickstart-101", drive=lambda _ctx: None, write_output=lambda _r: None
    )

    assert app_mod._selftest_capability_wanted(selftest, {}) is True
    assert app_mod._selftest_capability_wanted(None, {}) is False
    assert app_mod._selftest_capability_wanted(None, {"HWPX_SELFTEST_SET_THEME": "dark"}) is False
    # 창을 빌리는 것과 시험 능력을 켜는 것은 다른 질문이다.
    assert app_mod._selftest_capability_wanted(harness, {}) is False
    # 음성 대조 모드는 드라이버는 빌리되 능력은 일부러 뺀다.
    assert app_mod._selftest_capability_wanted(
        selftest, {"HWPX_SELFTEST_NO_CAPABILITY": "1"}
    ) is False


def test_non_capability_mode_measures_absence_with_a_positive_control(monkeypatch) -> None:
    """음성 대조 모드는 부재와 **함께 양성 대조**를 잰다.

    부재만 재면 "능력이 없다"와 "페이지가 안 떴다"가 구별되지 않는다(계측 층의 부재판별력).
    실 창에서의 값 판정은 ``tests/test_web_selftest_gate.py`` 가 지고, 여기서는 드라이버가
    그 질문을 **실제로 던지는지**를 센다.
    """
    captured = _capture_selftest(monkeypatch)
    monkeypatch.setenv("HWPX_SELFTEST_NO_CAPABILITY", "1")
    probed = {
        "selftest_own": False, "selftest_typeof": "undefined",
        "product_typeof": "object", "host_claim_typeof": "undefined",
        "url_after": "http://127.0.0.1:1/index.html?selftest=1&hwpxTest=on#selftest",
        "selftest_own_after_query_hash": False,
        "selftest_typeof_after_query_hash": "undefined",
    }

    class Window:
        def __init__(self):
            self.scripts = []

        def evaluate_js(self, script):
            self.scripts.append(script)
            return probed

        def destroy(self):
            pass

    window = Window()
    _drive_selftest(window)

    assert captured[0]["mode"] == "no_capability"
    assert captured[0]["non_exposure"] == probed
    assert "error" not in captured[0]
    # 질문에 **호출**이 없어야 한다 — 부재를 묻는 질문이 대상을 깨우면 안 된다.
    script = window.scripts[0]
    assert "typeof window.__hwpxTest" in script
    assert "typeof window.__hwpx;" in script or "typeof window.__hwpx," in script
    assert ".run(" not in script

def test_pywebview_selection_and_zoom_decision_are_explicit() -> None:
    source = (REPO_ROOT / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(
        encoding="utf-8"
    )
    create = source[source.index("window = webview.create_window("):source.index("frontend._window = window")]
    assert "text_select=True" in create
    assert "zoomable=False" in create


def test_personalization_shell_and_splitters_are_wired() -> None:
    index = SOURCE_INDEX.read_text(encoding="utf-8")
    app_js = (SOURCE_JS_DIR / "app.js").read_text(encoding="utf-8")
    css = app_css()
    assert reaches_product_graph("personalization.js")
    # 좌 목록 폭 스플리터의 마지막 DOM 소비처(「기안」)가 화면과 함께 사망(F6 PR-B) —
    # 소비 0. 설정 키(master_width)·배선(공유 계약)은 남아 다음 master-detail 표면이
    # 그대로 쓴다. DOM 이 되살아나면(>0) 이 계약을 다시 세우면 된다.
    assert index.count('class="master-splitter"') == 0
    assert "saveMasterWidth" in app_js and "setRailCollapsed" not in app_js
    compact = "".join(css.split())
    assert ".jobtbtbodytr" in compact and "user-select:none" in compact
    # 셸은 상단 토바 2행 그리드(F2 PR-B) — 좁은 창의 여유는 접기가 아니라 브랜드 워드마크·
    # 도구 값 라벨 접힘이 번다(레일 접기 사망의 승계분, 지도 §10.9 4계약면 4행).
    assert ".app{display:grid;grid-template-rows:var(--shell-topbar-h)1fr;height:100vh}" in compact
    narrow = compact.split("@media(max-width:820px){.topbar{", 1)[1].split("}}", 1)[0]
    assert ".brand-name{display:none}" in narrow and ".shell-tool.d{display:none" in narrow


def test_forced_colors_preserves_three_owner_signals() -> None:
    css = "".join(app_css().split())
    block = css.split("@media(forced-colors:active){", 1)[1]
    for selector, color in (
        (".wc-render.seg-fill.own-auto", "Highlight"),
        (".wc-render.seg-fill.own-hand", "Mark"),
        (".wc-render.seg-fill.own-man", "LinkText"),
    ):
        rule = block.split(selector, 1)[1].split("}", 1)[0]
        assert selector in block and f"border-bottom:3pxsolid{color}" in rule
        assert "box-shadow" not in rule, (
            "forced-colors는 box-shadow를 계산값 none으로 제거합니다 — 실렌더가 보존하는 "
            "border-bottom 시스템색 표지를 써야 합니다."
        )
