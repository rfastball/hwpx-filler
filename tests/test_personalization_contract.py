"""마일스톤 I 설정 존중·개인화 정적/순수 계약(#221)."""
from __future__ import annotations

from pathlib import Path

from hwpxfiller.webapp import app as app_mod
from hwpxfiller.webapp.app import _geometry_is_visible


ROOT = Path(__file__).resolve().parents[1]


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
    monkeypatch.setattr(app_mod.settings, "save_rail_collapsed", lambda value: calls.append(("rail", value)))
    monkeypatch.setattr(app_mod.settings, "save_master_width", lambda value: calls.append(("width", value)))
    frontend = object.__new__(app_mod.WebFrontend)
    assert frontend.set_font_scale("large") == "large"
    assert frontend.set_rail_collapsed(True) is True
    assert frontend.set_master_width(333) == 333
    assert calls == [("scale", "large"), ("rail", True), ("width", 333)]


def _capture_selftest(monkeypatch) -> list[dict]:
    captured: list[dict] = []
    monkeypatch.setattr(app_mod, "_finish_selftest", lambda _window, result: captured.append(result))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.delenv("HWPX_SELFTEST_SET_THEME", raising=False)
    return captured


def test_geometry_only_selftest_shapes_maximized_probe(monkeypatch) -> None:
    captured = _capture_selftest(monkeypatch)
    monkeypatch.setenv("HWPX_SELFTEST_GEOMETRY_ONLY", "1")

    class Window:
        def evaluate_js(self, script):
            if "readyState" in script:
                return True
            return {
                "x": 0, "y": 0, "width": 1920, "height": 1080,
                "avail_x": 0, "avail_y": 0, "avail_width": 1920, "avail_height": 1080,
            }

    app_mod._selftest_drive(Window())
    geometry = captured[0]["window_geometry"]
    assert geometry["maximized_like"] is True


def test_geometry_only_selftest_waits_for_document_readiness(monkeypatch) -> None:
    captured = _capture_selftest(monkeypatch)
    monkeypatch.setenv("HWPX_SELFTEST_GEOMETRY_ONLY", "1")
    ticks = iter((0.0, 1.0, 20.0))
    monkeypatch.setattr("time.monotonic", lambda: next(ticks))

    class Window:
        def evaluate_js(self, script):
            if "readyState" in script:
                return False
            return {
                "x": 100, "y": 100, "width": 1000, "height": 700,
                "avail_x": 0, "avail_y": 0, "avail_width": 1920, "avail_height": 1080,
            }

    app_mod._selftest_drive(Window())
    assert captured[0]["window_geometry"]["maximized_like"] is False


def test_font_scale_selftest_success_uses_real_bridge_expression(monkeypatch) -> None:
    captured = _capture_selftest(monkeypatch)
    monkeypatch.delenv("HWPX_SELFTEST_GEOMETRY_ONLY", raising=False)
    monkeypatch.setenv("HWPX_SELFTEST_SET_FONT_SCALE", "large")
    scripts: list[str] = []

    class Window:
        def evaluate_js(self, script):
            scripts.append(script)
            return True

    monkeypatch.setattr(app_mod.settings, "load_font_scale", lambda: "large")
    app_mod._selftest_drive(Window())
    assert captured == [{"font_scale_write": "large", "set_result": "large"}]
    assert any("Personalization.setFontScale" in script for script in scripts)


def test_font_scale_selftest_waits_for_bridge_and_persistence(monkeypatch) -> None:
    captured = _capture_selftest(monkeypatch)
    monkeypatch.delenv("HWPX_SELFTEST_GEOMETRY_ONLY", raising=False)
    monkeypatch.setenv("HWPX_SELFTEST_SET_FONT_SCALE", "large")
    ready_calls = 0

    class Window:
        def evaluate_js(self, script):
            nonlocal ready_calls
            if "pywebview" in script:
                ready_calls += 1
                return ready_calls > 1
            return True

    scales = iter(("normal", "large", "large"))
    monkeypatch.setattr(app_mod.settings, "load_font_scale", lambda: next(scales))
    monkeypatch.setattr("time.monotonic", lambda: 0.0)
    app_mod._selftest_drive(Window())
    assert captured[0]["set_result"] == "large"


def test_font_scale_selftest_reports_bridge_timeout(monkeypatch) -> None:
    captured = _capture_selftest(monkeypatch)
    monkeypatch.delenv("HWPX_SELFTEST_GEOMETRY_ONLY", raising=False)
    monkeypatch.setenv("HWPX_SELFTEST_SET_FONT_SCALE", "larger")
    ticks = iter((0.0, 20.0))
    monkeypatch.setattr("time.monotonic", lambda: next(ticks))

    class Window:
        def evaluate_js(self, _script):
            return False

    app_mod._selftest_drive(Window())
    assert "브리지 준비 시한 초과" in captured[0]["error"]


def test_font_scale_selftest_reports_evaluation_error(monkeypatch) -> None:
    captured = _capture_selftest(monkeypatch)
    monkeypatch.delenv("HWPX_SELFTEST_GEOMETRY_ONLY", raising=False)
    monkeypatch.setenv("HWPX_SELFTEST_SET_FONT_SCALE", "large")
    calls = 0

    class Window:
        def evaluate_js(self, _script):
            nonlocal calls
            calls += 1
            if calls == 1:
                return True
            raise RuntimeError("bridge failed")

    app_mod._selftest_drive(Window())
    assert "bridge failed" in captured[0]["error"]


def test_theme_selftest_waits_for_bridge_and_persistence(monkeypatch) -> None:
    captured = _capture_selftest(monkeypatch)
    monkeypatch.delenv("HWPX_SELFTEST_GEOMETRY_ONLY", raising=False)
    monkeypatch.delenv("HWPX_SELFTEST_SET_FONT_SCALE", raising=False)
    monkeypatch.setenv("HWPX_SELFTEST_SET_THEME", "dark")
    ready_calls = 0

    class Window:
        def evaluate_js(self, script):
            nonlocal ready_calls
            if "pywebview" in script:
                ready_calls += 1
                return ready_calls > 1
            return True

    themes = iter(("system", "dark", "dark"))
    monkeypatch.setattr(app_mod.settings, "load_theme", lambda: next(themes))
    monkeypatch.setattr("time.monotonic", lambda: 0.0)
    app_mod._selftest_drive(Window())
    assert captured[0] == {"theme_write": "dark", "set_result": "dark"}


def test_pywebview_selection_and_zoom_decision_are_explicit() -> None:
    source = (ROOT / "src" / "hwpxfiller" / "webapp" / "app.py").read_text(encoding="utf-8")
    create = source[source.index("window = webview.create_window("):source.index("frontend._window = window")]
    assert "text_select=True" in create
    assert "zoomable=False" in create


def test_personalization_shell_and_splitters_are_wired() -> None:
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
    assert 'src="js/personalization.js"' in index
    assert index.count('class="master-splitter"') == 2
    assert "saveMasterWidth" in app_js and "setRailCollapsed" in app_js
    compact = "".join(css.split())
    assert ".jobtbtbodytr" in compact and "user-select:none" in compact
    assert "@media(max-width:820px){.app.rail-collapsed{grid-template-columns:1fr}}" in compact


def test_forced_colors_preserves_three_owner_signals() -> None:
    css = "".join((ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8").split())
    block = css.split("@media(forced-colors:active){", 1)[1]
    for selector, color in (
        (".wc-render.seg-fill.own-auto", "Highlight"),
        (".wc-render.seg-fill.own-hand", "Mark"),
        (".wc-render.seg-fill.own-man", "LinkText"),
    ):
        assert selector in block and color in block.split(selector, 1)[1].split("}", 1)[0]
