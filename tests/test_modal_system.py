"""H-16 모달 lifecycle의 정적 회귀 가드.

실 WebView2 상호작용 프로브는 통합 레인이 소유한다. 이 파일은 모든 플랫폼에서 거처·개방
순서·IME·퇴장·세로 도달성·메뉴 복귀 seam이 조용히 풀리지 않도록 production 계약을 읽는다.
"""

from html.parser import HTMLParser

from _web_source import SOURCE_INDEX, SOURCE_JS_DIR, app_css


INDEX = SOURCE_INDEX
# 분할된 앱 스타일시트를 링크 순서대로 이어붙인 **문자열**(구 app.css 등가) — 이 파일의
# 단언은 119-128·838·894-900·932-933 이 한 문자열 안에 함께 있어야 성립한다.
CSS = app_css()
MODAL_JS = SOURCE_JS_DIR / "modal.js"


class _OverlayTree(HTMLParser):
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, str | None]] = []
        self.overlay_parent: str | None = None
        self.modal_parents: dict[str, str | None] = {}
        self.popover_parents: dict[str, str | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        parent_id = self.stack[-1][1] if self.stack else None
        element_id = attr.get("id")
        if element_id == "overlayRoot":
            self.overlay_parent = self.stack[-1][0] if self.stack else None
        if "modal" in (attr.get("class") or "").split():
            self.modal_parents[element_id or "<missing-id>"] = parent_id
        if {"ctx-menu", "colpanel"}.intersection((attr.get("class") or "").split()):
            self.popover_parents[element_id or "<missing-id>"] = parent_id
        if tag not in self._VOID:
            self.stack.append((tag, element_id))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


def _compact(text: str) -> str:
    return "".join(text.split())


def test_overlay_root_is_body_direct_and_owns_every_modal() -> None:
    tree = _OverlayTree()
    tree.feed(INDEX.read_text(encoding="utf-8"))
    assert tree.overlay_parent == "body"
    assert tree.modal_parents, "모달 골격을 찾지 못했습니다."
    assert set(tree.modal_parents.values()) == {"overlayRoot"}, tree.modal_parents
    assert tree.popover_parents, "팝오버 골격을 찾지 못했습니다."
    assert set(tree.popover_parents.values()) == {"overlayRoot"}, tree.popover_parents


def test_open_order_and_escape_contract_are_explicit() -> None:
    src = MODAL_JS.read_text(encoding="utf-8")
    open_body = src[src.index("function open(") : src.index("function finishClose(")]
    order = [
        open_body.index("const returnFocus ="),
        open_body.index("Popover.closeAll()"),
        open_body.index("stack.push("),
        open_body.index("focusTo.focus()"),
    ]
    assert order == sorted(order), "returnFocus→Popover.closeAll→stack→initialFocus 순서가 깨졌습니다."

    key_body = src[src.index("function onKeydown(") : src.index("function open(")]
    assert key_body.index("e.isComposing || e.keyCode === 229") < key_body.index('e.key === "Escape"')
    assert "const t = top()" in key_body and "close(t.el.id)" in key_body
    assert "stopImmediatePropagation" in key_body


def test_close_keeps_blocking_layer_until_symmetric_transition_finishes() -> None:
    css = _compact(CSS)
    assert ".modal.is-closing{background-color:transparent;backdrop-filter:blur(0);pointer-events:auto}" in css
    assert ".modal.is-closing.modal-card{opacity:0;transform:scale(.95);pointer-events:none}" in css
    assert "transition:background-colorvar(--dur-modal)var(--ease-in-out),backdrop-filtervar(--dur-modal)var(--ease-in-out)" in css
    assert "transition:opacityvar(--dur-modal)var(--ease-in-out),transformvar(--dur-modal)var(--ease-in-out)" in css

    src = MODAL_JS.read_text(encoding="utf-8")
    close_body = src[src.index("function close(") : src.index("function _setText(")]
    assert 'el.classList.add("is-closing")' in close_body
    assert "transitionend" in close_body and "CLOSE_FALLBACK_MS" in close_body
    finish_body = src[src.index("function finishClose(") : src.index("function close(")]
    assert finish_body.index('classList.add("hidden")') < finish_body.index("onCloseCb")


def test_modal_surface_reaches_actions_in_short_viewports_and_has_accessible_scrim() -> None:
    css = _compact(CSS)
    assert "#overlayRoot{position:fixed;inset:0;z-index:var(--z-overlay-root);pointer-events:none}" in css
    assert ".ctx-menu{position:fixed;z-index:var(--z-popover);pointer-events:auto" in css
    assert ".colpanel{position:fixed;z-index:var(--z-popover);pointer-events:auto" in css
    assert "z-index:calc(var(--z-modal)+var(--modal-depth,0))" in css
    assert "max-height:calc(100dvh-2*var(--sp-16))" in css
    assert "overflow:auto" in css and "overscroll-behavior:contain" in css
    assert "border-radius:var(--rad-overlay)" in css
    assert "background:var(--a-scrim)" in css and "backdrop-filter:blur(6px)" in css
    assert "@media(prefers-reduced-transparency:reduce)" in css
    assert "background:var(--a-scrim-reduced);backdrop-filter:none" in css


def test_menu_spawned_modals_carry_original_trigger_through_close_all() -> None:
    group = (SOURCE_JS_DIR / "grouplist.js").read_text(encoding="utf-8")
    assert "returnFocus: opts.returnFocus" in group
    assert "if (confirmed && cb) cb(confirmedGroup)" in group and "cb(group)" not in group
    # (screens/draft.js 는 「기안」 화면 사망(F6 PR-B), screens/template.js 는 「템플릿
    #  관리」 사망(F8)으로 제외 — 메뉴발 모달의 새 소비자는 편집기 「템플릿」 탭이다.)
    for rel in ("screens/library.js", "screens/job.js", "screens/editor.js"):
        src = (SOURCE_JS_DIR / rel).read_text(encoding="utf-8")
        assert "trigger" in src and "returnFocus" in src, rel
