"""H-08 WebView2 전역 스크롤바 시각 계약 가드."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
TOKENS = (ROOT / "web" / "css" / "tokens.css").read_text(encoding="utf-8")


def _declarations(selector: str) -> str:
    bodies: list[str] = []
    css = re.sub(r"/\*[\s\S]*?\*/", "", CSS)
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in {part.strip() for part in selectors.split(",")}:
            bodies.append(re.sub(r"\s+", "", body))
    assert bodies, f"missing scrollbar selector: {selector}"
    return ";".join(bodies)


def test_global_webview2_scrollbar_is_eight_pixels():
    rule = _declarations("*::-webkit-scrollbar")
    assert "width:8px" in rule and "height:8px" in rule


def test_track_is_transparent_and_native_buttons_are_removed():
    assert "background:transparent" in _declarations("*::-webkit-scrollbar-track")
    button = _declarations("*::-webkit-scrollbar-button")
    assert "display:none" in button
    assert "width:0" in button and "height:0" in button


def test_thumb_uses_rounded_theme_tokens_with_stronger_hover():
    thumb = _declarations("*::-webkit-scrollbar-thumb")
    hover = _declarations("*::-webkit-scrollbar-thumb:hover")
    assert "background-color:var(--n-border-strong)" in thumb
    assert "border-radius:var(--rad-pill)" in thumb
    assert "background-clip:padding-box" in thumb
    assert "background-color:var(--n-ink-soft)" in hover
    # 두 토큰 모두 생성된 light root와 dark override에 존재해야 테마 전환 시 UA 색으로 새지 않는다.
    assert TOKENS.count("--n-border-strong:") >= 3
    assert TOKENS.count("--n-ink-soft:") >= 3

