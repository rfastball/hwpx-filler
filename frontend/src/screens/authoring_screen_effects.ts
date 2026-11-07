/** 저작 셸의 효과 훅 — 초점 복귀·문맥 메뉴·live region·독 경보·선택 옆 막대의 DOM 동기화.
 *  AuthoringScreen 이 원래 순서대로 부른다(효과는 선언 순서대로 돈다). */
import { useEffect, useLayoutEffect } from "react";
import { FOCUSABLE, clampMenu, focusFirst, liveStep } from "./authoring_a11y.ts";
import { DOCK_PANELS, selectionBarPlace } from "./authoring_commands.ts";
import type { LineRect } from "./authoring_editor.ts";
import type { Obj, Props } from "./authoring_primitives.ts";

type Controller = Props["controller"];
type Ref<T> = { current: T };
type BarAnchor = { id: string; rect: LineRect } | null;

/** 떠 있는 표면(메뉴·선택 옆 막대)을 창 좌표의 자리에서 셸 좌표로 옮겨 놓는다 — 셸의 테두리·스크롤만큼 보정한다. */
function placeInShell(element: HTMLElement, shell: HTMLElement, place: { left: number; top: number }) {
  const base = shell.getBoundingClientRect();
  element.style.left = `${place.left - base.left - (shell.clientLeft || 0) + (shell.scrollLeft || 0)}px`;
  element.style.top = `${place.top - base.top - (shell.clientTop || 0) + (shell.scrollTop || 0)}px`;
}

/** 패널을 연 자리 — 요청자가 먼저 넘긴 것(pendingOpener)이 있으면 그것, 아니면 초점을 옮기기 직전에 패널 밖에서 초점을 쥔 원소다. */
function panelOpener(shell: HTMLElement, panel: HTMLElement | null, pending: unknown) {
  const active = shell.ownerDocument?.activeElement;
  return pending ?? (active && active !== shell.ownerDocument?.body && !panel?.contains(active) ? active : null);
}

/** 열린 패널의 첫 초점 자리 — 독은 패널의 첫 제어(없으면 패널), 속성은 이름 칸. */
function focusPanelTarget(shell: HTMLElement, slot: "dock" | "properties", panel: HTMLElement | null) {
  const target = slot === "dock" ? panel?.querySelector<HTMLElement>(FOCUSABLE) || panel : shell.querySelector<HTMLElement>(".authoring-properties input");
  target?.focus();
  // 이름 칸은 전체 선택된 채 받는다(P-06) — 제안값이든 적용값이든 치면 바로 바뀐다.
  if (slot === "properties") (target as HTMLInputElement | null | undefined)?.select?.();
}

// 초점 요청(focusRequest)만 초점을 옮긴다 — 패널 값·명령 종류·판정 도착은 옮기지 않는다(WCAG 3.2.2).
// 문맥 메뉴가 열려 있으면 메뉴가 초점을 쥔다.
export function usePanelFocus(view: Obj, root: Ref<HTMLDivElement | null>, pendingOpener: Ref<unknown>, openers: Ref<Record<string, unknown>>) {
  useEffect(() => {
    const shell = root.current;
    if (!view.focusPanel || !shell || view.contextMenu) return;
    const slot = view.focusTarget === "dock" ? "dock" : "properties";
    const panel = shell.querySelector<HTMLElement>(slot === "dock" ? "#authoring-dock-panel" : ".authoring-properties");
    const opener = panelOpener(shell, panel, pendingOpener.current);
    pendingOpener.current = null;
    if (opener) openers.current[slot] = opener;
    focusPanelTarget(shell, slot, panel);
  }, [view.focusPanel]);
}

/** 창이 초점을 되찾으면 열린 문서의 외부 변경을 확인한다. */
export function useExternalCheck(controller: Controller) {
  useEffect(() => {
    const focus = () => { void controller.guarded(controller.checkExternal, "external"); };
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, [controller]);
}

// 문맥 메뉴(§6.1): 열리면 첫 사용 가능 항목(없으면 첫 항목)에 초점, 바깥 클릭이면 닫는다. Escape 는 셸 단축키가 처리한다.
// 「더보기」·「파일」 메뉴는 여는 버튼 자체의 누름을 바깥으로 치지 않는다 — 그 버튼이 여닫기를 맡는다.
export function useContextMenuFocus(controller: Controller, view: Obj, menuRef: Ref<HTMLDivElement | null>) {
  useEffect(() => {
    if (!view.contextMenu) return;
    const items = [...(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') || [])];
    (items.find((entry) => entry.getAttribute("aria-disabled") !== "true") || items[0])?.focus();
    const trigger = view.contextMenu.kind ? view.contextMenu.trigger as Element | null : null;
    const outside = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (!target?.closest?.(".authoring-context-menu") && !(target && trigger?.contains?.(target))) controller.update({ contextMenu: null });
    };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [view.contextMenu]);
}

// 메뉴는 그린 뒤 실제 크기로 창 안에 든다 — 아래가 모자라면 위로 뒤집고, 그래도 넘치면 가장자리에 붙인다(UX-04).
export function useMenuPlacement(view: Obj, menuRef: Ref<HTMLDivElement | null>, root: Ref<HTMLDivElement | null>) {
  useLayoutEffect(() => {
    const menu = menuRef.current;
    const shell = root.current;
    const anchor = view.contextMenu?.anchor;
    const win = shell?.ownerDocument?.defaultView;
    if (!menu || !shell || !anchor || !win?.innerWidth || typeof menu.getBoundingClientRect !== "function") return;
    const size = menu.getBoundingClientRect();
    placeInShell(menu, shell, clampMenu(anchor, { width: size.width, height: size.height }, { width: win.innerWidth, height: win.innerHeight }));
  }, [view.contextMenu]);
}

// 문서 탭을 닫은 뒤에는 이웃 탭에 초점(APG tabs). 탭이 하나도 남지 않으면 빈 작업대의 첫 행동으로.
export function useTabFocusRestore(root: Ref<HTMLDivElement | null>, pendingTabFocus: Ref<string>) {
  useEffect(() => {
    const wanted = pendingTabFocus.current;
    const shell = root.current;
    if (!wanted || !shell) return;
    const all = [...shell.querySelectorAll<HTMLElement>('[role="tab"][data-tab]')];
    const next = all.find((tab) => tab.getAttribute("data-tab") === wanted) || all.find((tab) => tab.getAttribute("aria-selected") === "true");
    pendingTabFocus.current = "";
    if (next) next.focus();
    else focusFirst([shell.querySelector(".authoring-empty-actions button"), shell.querySelector(".authoring-head button")]);
  });
}

// 단일 live region(UX-04): 전이 때만 한 번 쓴다 — 키 입력마다 바뀌는 상태 막대는 읽지 않는다.
export function useLiveAnnounce(controller: Controller, liveRef: Ref<ReturnType<typeof liveStep>["state"] | null>, liveNow: Parameters<typeof liveStep>[1]) {
  useEffect(() => {
    const { state, message } = liveStep(liveRef.current, liveNow);
    liveRef.current = state;
    if (message) controller.announce(message);
  });
}

// 경보(외부 파일 변경)는 새로 서는 순간 독의 제 탭을 펼친다 — 닫아 둔 독도 다시 연다. 초점은 옮기지 않는다(경보가 읽힌다).
export function useForcedDock(controller: Controller, dock: { tabs: [string, ...unknown[]][] }, itemId: unknown) {
  const forced = dock.tabs.some(([key]) => key === "external_changed") ? "external_changed" : "";
  useEffect(() => {
    if (!forced) return;
    const current = controller.viewModel.getSnapshot();
    controller.update({ dock: forced, dockClosed: false, ...(DOCK_PANELS.includes(current.panel) && current.panel !== "comparison" ? { panel: "" } : {}) });
  }, [forced, itemId]);
}

export function useSelectionBarDismiss(view: Obj, barAnchor: BarAnchor, setBarAnchor: (anchor: BarAnchor) => void, root: Ref<HTMLDivElement | null>) {
  // 메뉴·팔레트가 열리면 막대는 걷힌다 — 떠 있는 표면은 한 번에 하나다.
  useEffect(() => { if (view.contextMenu || view.palette) setBarAnchor(null); }, [view.contextMenu, view.palette]);
  // 스크롤(편집면·셸 어디서든)과 창 크기 변화에 걷힌다 — 막대가 선택 자리에서 떨어진다.
  useEffect(() => {
    const doc = root.current?.ownerDocument;
    const win = doc?.defaultView;
    if (!barAnchor || !doc) return;
    const hide = () => setBarAnchor(null);
    doc.addEventListener("scroll", hide, true);
    win?.addEventListener("resize", hide);
    return () => { doc.removeEventListener("scroll", hide, true); win?.removeEventListener("resize", hide); };
  }, [barAnchor]);
}

// 막대는 그린 뒤 실제 크기로 선택 끝 줄 아래(모자라면 위)에 창 안으로 든다 — 셸 층이라 편집면 확대의 영향을 받지 않는다.
export function useSelectionBarPlacement(barShown: boolean, barAnchor: BarAnchor, barItems: { key: string }[], barRef: Ref<HTMLDivElement | null>, root: Ref<HTMLDivElement | null>) {
  const barKey = barItems.map((entry) => entry.key).join(" ");
  useLayoutEffect(() => {
    const bar = barRef.current;
    const shell = root.current;
    const win = shell?.ownerDocument?.defaultView;
    if (!barShown || !bar || !shell || !barAnchor || !win?.innerWidth || typeof bar.getBoundingClientRect !== "function") return;
    const size = bar.getBoundingClientRect();
    placeInShell(bar, shell, selectionBarPlace(barAnchor.rect, { width: size.width, height: size.height }, { width: win.innerWidth, height: win.innerHeight }));
  }, [barShown, barAnchor, barKey]);
}
