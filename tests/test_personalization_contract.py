"""마일스톤 I 설정 존중·개인화 정적/순수 계약(#221)."""
from __future__ import annotations

from pathlib import Path

from hwpxfiller.webapp.app import _geometry_is_visible


ROOT = Path(__file__).resolve().parents[1]


def test_saved_window_geometry_rejects_offscreen_titlebar() -> None:
    screen = (0, 0, 1920, 1080)
    visible = {"x": 1840, "y": 20, "width": 1180, "height": 820, "maximized": False}
    offscreen = {"x": 2200, "y": 20, "width": 1180, "height": 820, "maximized": False}
    assert _geometry_is_visible(visible, screen) is True
    assert _geometry_is_visible(offscreen, screen) is False


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
