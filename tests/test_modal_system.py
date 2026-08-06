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
# R3-01(#410) — 판정(스택·직렬화·Escape/Tab/복귀)의 거처는 트리-불가지 엔진이고, 문서
# keydown 부착/해제는 엔진 배선이 진다. modal.js 는 파사드 + legacy 집행자로 남는다.
ENGINE_TS = SOURCE_JS_DIR.parent / "src" / "overlay" / "engine.ts"
INSTANCE_TS = SOURCE_JS_DIR.parent / "src" / "overlay" / "instance.ts"


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
    # R3-01(#410) 뒤 이 정적 핀의 관측 의미는 **legacy 전용**으로 좁아졌다 — promise
    # 다이얼로그 3종·토스트는 React host(#reactOverlayHost) 렌더 소유라 index.html 에 없다.
    # 런타임 전수 판(두 지정 호스트)은 쌍둥이 프로브 `overlay_children_owned`
    # (frontend/src/selftest/probes/boot_routing_overlay.js)가 잰다.
    tree = _OverlayTree()
    tree.feed(INDEX.read_text(encoding="utf-8"))
    assert tree.overlay_parent == "body"
    assert tree.modal_parents, "모달 골격을 찾지 못했습니다."
    assert set(tree.modal_parents.values()) == {"overlayRoot"}, tree.modal_parents
    assert tree.popover_parents, "팝오버 골격을 찾지 못했습니다."
    assert set(tree.popover_parents.values()) == {"overlayRoot"}, tree.popover_parents


def test_open_order_and_escape_contract_are_explicit() -> None:
    src = MODAL_JS.read_text(encoding="utf-8")
    # H-16 개방 순서는 파사드 소유 그대로: 복귀점 포착 → 경량층 닫기 → 엔진 등록(스택·초점).
    open_body = src[src.index("function open(") : src.index("function close(")]
    order = [
        open_body.index("const returnFocus ="),
        open_body.index("Popover.closeAll()"),
        open_body.index("overlayEngine.open("),
    ]
    assert order == sorted(order), "returnFocus→Popover.closeAll→engine.open 순서가 깨졌습니다."

    # Escape/IME 판정은 엔진이 소유한다(R3-01) — IME 조합 통과가 Escape 판정보다 먼저.
    engine = ENGINE_TS.read_text(encoding="utf-8")
    key_body = engine[engine.index("handleKeydown(") : engine.index("trapTab(host")]
    assert key_body.index("event.isComposing || event.keyCode === 229") < key_body.index(
        'event.key === "Escape"'
    )
    # 스택 등록 → 개방 집행 → 초점 순서는 엔진 open 본문이 진다.
    engine_open = engine[engine.index("open(entry: OverlayEntry)") : engine.index("requestClose(")]
    assert engine_open.index("stack.push(") < engine_open.index("executor.show(")
    assert engine_open.index("executor.show(") < engine_open.index("executor.focusInitial()")
    # 부착·소비 집행은 엔진 배선(instance.ts) — Escape 는 최상위 닫기 요청으로 잇고 한 겹 소비.
    wiring = INSTANCE_TS.read_text(encoding="utf-8")
    assert "stopImmediatePropagation" in wiring
    assert "overlayEngine.requestClose(decision.host)" in wiring


def test_close_keeps_blocking_layer_until_symmetric_transition_finishes() -> None:
    css = _compact(CSS)
    assert ".modal.is-closing{background-color:transparent;backdrop-filter:blur(0);pointer-events:auto}" in css
    assert ".modal.is-closing.modal-card{opacity:0;transform:scale(.95);pointer-events:none}" in css
    assert "transition:background-colorvar(--dur-modal)var(--ease-in-out),backdrop-filtervar(--dur-modal)var(--ease-in-out)" in css
    assert "transition:opacityvar(--dur-modal)var(--ease-in-out),transformvar(--dur-modal)var(--ease-in-out)" in css

    # 전이 집행(is-closing·transitionend·안전망)은 legacy 집행자가 소유한다(R3-01).
    src = MODAL_JS.read_text(encoding="utf-8")
    executor_body = src[src.index("function legacyExecutor(") : src.index("function open(")]
    assert 'el.classList.add("is-closing")' in executor_body
    assert "transitionend" in executor_body and "CLOSE_FALLBACK_MS" in executor_body
    assert 'el.classList.add("hidden")' in executor_body
    # 정착 순서(집행 정리 → 스택 제거 → 복귀 → 통지)는 엔진 settleClose 가 진다.
    engine = ENGINE_TS.read_text(encoding="utf-8")
    settle_body = engine[engine.index("settleClose(") : engine.index("acquireDialog(")]
    assert settle_body.index("executor.finishClose()") < settle_body.index("onClose()")


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
    # R4-02 — 그룹 이동 다이얼로그가 `GroupList.createMoveDialog` 에서 React
    # `screens/group_move_dialog.ts` 로 옮겼다. 묻는 것은 그대로다: 원 트리거를 들고 가고,
    # **확정은 초점이 돌아간 뒤에** 콜백을 부른다(먼저 보내면 push 재렌더가 트리거를 파괴한다).
    group = (SOURCE_JS_DIR.parent / "src" / "screens" / "group_move_dialog.ts").read_text(
        encoding="utf-8")
    assert "returnFocus: next.returnFocus || null" in group
    assert "if (accepted !== null && pending !== null) void pending.onConfirm(accepted.group);" in group
    # (screens/draft.js 는 「기안」 화면 사망(F6 PR-B), screens/template.js 는 「템플릿
    #  관리」 사망(F8)으로 제외 — 메뉴발 모달의 새 소비자는 편집기 「템플릿」 탭이다.)
    sources = {
        "src/screens/library.ts": SOURCE_JS_DIR.parent / "src" / "screens" / "library.ts",
        "js/screens/job.js": SOURCE_JS_DIR / "screens" / "job.js",
        "src/screens/editor.ts": SOURCE_JS_DIR.parent / "src" / "screens" / "editor.ts",
    }
    for rel, path in sources.items():
        src = path.read_text(encoding="utf-8")
        assert "trigger" in src and "returnFocus" in src, rel
