"""H-15 팝오버 시스템의 공용 수명주기·입력·배치·표면 계약 가드."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
POPOVER = WEB / "js" / "popover.js"
GROUPLIST = WEB / "js" / "grouplist.js"
DATAZONE = WEB / "js" / "datazone.js"
CSS = WEB / "css" / "app.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    match = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]+)\}", css)
    assert match, f"CSS selector missing: {selector}"
    return re.sub(r"\s+", "", match.group(1))


def test_public_registry_and_close_all_contract():
    src = _read(POPOVER)
    assert "const entries = new Set()" in src
    assert "function register(cfg)" in src and "function unregister()" in src
    assert "entries.add(cfg)" in src and "entries.delete(cfg)" in src
    assert "function closeAll()" in src and "Array.from(entries).forEach(close)" in src
    assert re.search(
        r"window\.Popover\s*=\s*\{[^}]*register[^}]*wireDismiss[^}]*closeAll[^}]*place[^}]*\}",
        src,
    ), "H-16이 사용할 closeAll을 포함한 공개 Popover API가 끊겼습니다."


def test_only_corresponding_primary_click_is_consumed():
    src = _read(POPOVER)
    assert "e.button === 0" in src and "e.isPrimary !== false" in src
    assert "sameTarget(pending.target, e.target)" in src
    assert 'addEventListener("pointerup"' in src and "setTimeout" in src
    assert 'addEventListener("pointercancel"' in src
    assert re.search(r'addEventListener\("pointerdown"[\s\S]+?suppressNextClick\s*=\s*null', src)


def test_focusout_and_capture_scroll_share_registry():
    src = _read(POPOVER)
    assert re.search(r'addEventListener\("focusout"[\s\S]+?e\.relatedTarget', src)
    assert re.search(r'addEventListener\("scroll"[\s\S]+?\},\s*true\)', src)
    # 화면별 임시 scroll-close는 공용 capture 계약으로 대체되어야 한다.
    for name in ("job.js", "draft.js", "home.js", "template.js"):
        screen = _read(WEB / "js" / "screens" / name)
        assert not re.search(r'addEventListener\("scroll"', screen), name


def test_rendered_size_drives_clamp_flip_and_origin():
    pop = _read(POPOVER)
    group = _read(GROUPLIST)
    data = _read(DATAZONE)
    assert "const measured = el.getBoundingClientRect()" in pop
    assert "belowSpace" in pop and "aboveSpace" in pop
    assert "window.innerWidth - margin - width" in pop
    assert "window.innerHeight - margin - height" in pop
    assert "el.style.transformOrigin" in pop
    assert "window.Popover.place(m, btn)" in group
    assert "window.Popover.place(p, anchor)" in data
    assert "offsetParent: $(ids.tableHost)" not in data
    assert "host.width - 260" not in data


def test_ctx_menu_and_colpanel_share_overlay_surface():
    css = _read(CSS)
    for selector in (".ctx-menu", ".colpanel"):
        rule = _rule(css, selector)
        assert "border-radius:var(--rad-overlay)" in rule, selector
        assert "box-shadow:08px24pxvar(--a-shadow)" in rule, selector
