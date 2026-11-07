/** 저작 셸(AuthoringScreen)의 동작 묶음·단축키·렌더 조각 — 셸이 렌더마다 지금 상태로 다시 만든다.
 *  렌더 조각은 컴포넌트가 아니라 일반 함수다(셸의 자식 자리와 재마운트 동작이 그대로 남는다). */
import { createElement as h } from "react";
import type { ReactNode } from "react";
import { COMMANDS, DOCUMENT_COMMANDS } from "./authoring_controller.ts";
import { PANEL_CYCLE, cyclePanels } from "./authoring_layout.ts";
import { errorParts, focusFirst, focusable, roveFocus } from "./authoring_a11y.ts";
import { menuLines } from "./command_palette.ts";
import type { PaletteAction } from "./command_palette.ts";
import { button, primary, iconButton } from "./authoring_primitives.ts";
import type { Obj, Props } from "./authoring_primitives.ts";
import { MODES, menuAnchor } from "./authoring_shell_state.ts";
import { shellShortcut } from "./authoring_editor.ts";
import type { ShellInput } from "./authoring_editor.ts";
import { CREATE_TYPES, openContextMenu, focusRequest, dockBadge, renameShortcut, sharedReason, escapeShell,
  PALETTE_SELF } from "./authoring_commands.ts";
import type { MenuAction } from "./authoring_commands.ts";
import { commandAvailability } from "./authoring_outline_model.ts";

type Controller = Props["controller"];
type Ref<T> = { current: T };
type Act = (work: () => unknown, kind?: string) => () => void;
type FocusSlot = "properties" | "dock" | "error";
type Dock = { active: string; tabs: [string, string][] };

/** 열린 문서가 편집기로 고칠 수 없는 HWPX 인지(읽기 전용). */
export const isReadOnly = (item: Obj | undefined) => !!item && item.media === "hwpx" && item.rhwp_editable !== true;

/** 셸 Escape 한 단계 뒤의 초점 — 패널을 닫았으면 연 자리로, 메뉴의 연 자리가 없으면 도구 막대로. 제안 팝오버만 걷었으면(#1156)
 *  초점은 이미 편집면에 있으므로 옮기지 않는다. */
function escapeFocus(controller: Controller, view: Obj, returnFocus: (slot: "properties" | "dock") => void, focusToolbar: () => void) {
  const closing = view.panel;
  const stage = escapeShell(controller);
  if (stage === "panel") returnFocus(closing && closing !== "properties" ? "dock" : "properties");
  else if (stage === "menu" && !focusable(view.contextMenu?.trigger)) focusToolbar();
}

type NavigationContext = {
  controller: Controller; item: Obj | undefined; tabs: Obj[]; act: Act;
  root: Ref<HTMLDivElement | null>; openers: Ref<Record<string, unknown>>; pendingOpener: Ref<unknown>; pendingTabFocus: Ref<string>;
};

/** 고르기·초점 복귀·탭 닫기 — 셸 안 자리 사이를 오가는 동작. */
export function shellNavigation({ controller, item, tabs, act, root, openers, pendingOpener, pendingTabFocus }: NavigationContext) {
  const toolbarEntry = () => root.current?.querySelector<HTMLElement>('.authoring-toolbar [data-rove][tabindex="0"]');
  /** 닫힌 패널에서 초점을 돌린다: 속성은 §10 대로 선택 자리 먼저, 독·메뉴·오류는 연 자리 먼저. 마지막은 도구 막대. */
  const returnFocus = (slot: FocusSlot) => act(async () => {
    const opener = openers.current[slot];
    openers.current[slot] = null;
    if (slot === "properties" && await controller.focusSelection()) return;
    if (focusFirst([opener])) return;
    if (slot !== "properties" && await controller.focusSelection()) return;
    focusFirst([toolbarEntry(), root.current?.querySelector(".authoring-head button")]);
  }, "focus")();
  const select = (entry: Obj) => act(() => controller.select({ source_revision: item?.revision, ...entry }));
  // 독 안의 행(검색 적중)에서 고르면 그 독 탭이 남는다(NG-06) — 편집면 강조와 위치 줄만 옮기고 속성 패널은 열지 않는다.
  const selectInDock = (entry: Obj) => act(() => controller.select({ source_revision: item?.revision, ...entry }, { keepDock: true }));
  const contextMenu = (event: any) => openContextMenu(controller, event, root.current);
  // 구조 목록에서 고르면 속성 패널이 그 대상으로 열리고 이름 칸으로 간다(§10). 메뉴가 열려 있으면 메뉴가 초점을 쥔다.
  const chooseFromOutline = (entry: Obj, element: HTMLElement) => act(async () => {
    await controller.select({ source_revision: item?.revision, ...entry });
    const current = controller.viewModel.getSnapshot();
    if (current.contextMenu) return;
    pendingOpener.current = element;
    controller.update(focusRequest(current, "properties"));
  })();
  // 구조 목록 줄의 문맥 메뉴(오른쪽 클릭·Shift+F10): 그 줄을 고른 **뒤에** 연다 — 선택이 편집면으로 초점을 옮기므로
  // 먼저 열면 메뉴가 초점을 잃는다. trigger 는 그 줄이다.
  const outlineMenu = (entry: Obj, element: HTMLElement, anchor: { x: number; y: number; top?: number }) => act(async () => {
    await controller.select({ source_revision: item?.revision, ...entry });
    openContextMenu(controller, { clientX: anchor.x, clientY: anchor.y, anchorTop: anchor.top, target: element }, root.current);
  })();
  const closeTab = (id: string) => act(async () => {
    const ids = tabs.map((tab) => tab.id);
    const at = ids.indexOf(id);
    const neighbour = ids[at + 1] ?? ids[at - 1] ?? "";
    if (!(await controller.close(id))) return;
    pendingTabFocus.current = neighbour || "-";
    controller.update({});
  })();
  return { toolbarEntry, returnFocus, select, selectInDock, contextMenu, chooseFromOutline, outlineMenu, closeTab };
}

type PanelContext = {
  controller: Controller; view: Obj; act: Act; root: Ref<HTMLDivElement | null>; pendingOpener: Ref<unknown>;
  paletteOpener: Ref<unknown>; toolbarEntry: () => HTMLElement | null | undefined;
};

/** 속성 패널·독 패널·명령 팔레트·「더보기」/「파일」 메뉴를 여닫는 동작. */
export function shellPanels({ controller, view, act, root, pendingOpener, paletteOpener, toolbarEntry }: PanelContext) {
  // 명령 하나를 고르면 속성 패널이 그 명령으로 열리고 이름 칸으로 간다. 메뉴에서 골랐으면 메뉴를 연 자리가 복귀 대상이다.
  const pick = (commandType: string) => {
    // 문서 명령(#1078)은 속성 패널을 열지 않는다 — 고른 대상이 없고 입력 칸이 없다. 확인은 Python 등급을 따른다.
    if (DOCUMENT_COMMANDS.some(([type]) => type === commandType)) { act(() => controller.documentCommand(commandType))(); return; }
    const current = controller.viewModel.getSnapshot();
    if (current.contextMenu) pendingOpener.current = current.contextMenu.trigger;
    controller.update({ panel: "properties", commandType, formEntry: CREATE_TYPES.includes(commandType) ? "create" : "", contextMenu: null, preview: null, refusal: null, ...focusRequest(current, "properties") });
  };
  const openPanel = (panel: string) => controller.update({ panel, contextMenu: null, ...focusRequest(controller.viewModel.getSnapshot(), "dock") });
  // 명령 팔레트(IDE-02 · P-10): 독 탭이 아니라 머리 띠 아래의 비모달 오버레이다 — 열어도 독(시험·문제)과 view.panel 은
  // 그대로다. 연 자리를 기억해 닫으면 그리로 돌린다. 팔레트 안에서 다시 열면(Ctrl+Shift+P) 연 자리는 바뀌지 않는다.
  const openPalette = (opener?: unknown) => {
    const doc = root.current?.ownerDocument;
    const active = doc?.activeElement as Element | null | undefined;
    if (opener !== undefined) paletteOpener.current = opener;
    else if (!active?.closest?.(".authoring-command-palette")) paletteOpener.current = active && active !== doc?.body ? active : null;
    controller.update({ palette: (controller.viewModel.getSnapshot().palette || 0) + 1, contextMenu: null });
  };
  const closePalette = (restore: boolean) => {
    const opener = paletteOpener.current;
    paletteOpener.current = null;
    controller.update({ palette: 0 });
    if (restore && !focusFirst([opener])) focusFirst([toolbarEntry()]);
  };
  /** 「더보기」·「파일」을 여닫는 단추의 누름 — 열린 제 메뉴면 닫고, 아니면 단추 아래에 연다. */
  const menuToggle = (kind: "more" | "file") => (event: any) => {
    if (view.contextMenu?.kind === kind) { controller.update({ contextMenu: null }); return; }
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    openContextMenu(controller, { clientX: rect.left, clientY: rect.bottom, target: event.currentTarget }, root.current, kind);
  };
  const menuButton = (kind: "more" | "file") => ({ "aria-haspopup": "menu", "aria-expanded": view.contextMenu?.kind === kind, "aria-controls": view.contextMenu?.kind === kind ? "authoring-menu" : undefined });
  return { pick, openPanel, openPalette, closePalette, menuToggle, menuButton };
}

// 판정이 섰는데 되는 명령도 대안도 없어 문맥 메뉴가 「명령」 한 줄뿐이면 그 위에 공유 사유를 한 줄 세운다(읽기 전용 제외).
// 편집면 메뉴는 「필드로 만들기」가 제 사유를 싣고 서므로(결정 C) 그 한 줄뿐인 경우가 없다.
export function menuReasonFor(view: Obj, commandTable: Parameters<typeof menuLines>[0], readOnly: boolean, menuEditor: boolean) {
  return !readOnly && !menuLines(commandTable, readOnly, menuEditor) ? sharedReason(view.commands) : null;
}

type PaletteContext = {
  fileActions: MenuAction[]; moreActions: MenuAction[]; openPanel: (panel: string) => void; openDock: (key: string) => void;
  root: Ref<HTMLDivElement | null>; shellInput: ShellInput;
};

// 팔레트의 셸 동작(1부) — 키 학습 표면이다(L-50): 셸 키가 있는 동작은 그 키를 곁에 싣는다. 실행 경로는 「파일」·「더보기」·
// 셸 키와 같다. 영역 이동·문맥 메뉴는 팔레트가 연 자리로 초점을 돌린 뒤 그 자리에서 누른 키와 같다.
export function shellPaletteActions({ fileActions, moreActions, openPanel, openDock, root, shellInput }: PaletteContext): PaletteAction[] {
  const pressHere = (key: string, shiftKey: boolean) => {
    const target = root.current?.ownerDocument?.activeElement as HTMLElement | null | undefined;
    const KeyboardEvent = (target?.ownerDocument?.defaultView as Obj | null | undefined)?.KeyboardEvent;
    // 진짜 키 사건을 그 자리에 쏘면 구조 목록처럼 제 키를 먼저 받는 곳(줄을 고른 뒤 메뉴)도 사람이 누른 것과 같게 간다.
    if (target && KeyboardEvent && typeof target.dispatchEvent === "function") target.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true, cancelable: true }));
    else shellInput.current.key?.({ key, shiftKey, target, nativeEvent: {}, preventDefault() {} });
  };
  return ([
    ...fileActions.filter(([label]) => label === "저장" || label === "다른 이름으로 저장"),
    ["찾기", () => openPanel("search"), false, "Ctrl+F"],
    ["결과 시험", () => openDock("trial"), false],
    ...moreActions.filter(([label]) => label !== PALETTE_SELF),
    ["다음 영역으로", () => pressHere("F6", false), false, "F6"],
    ["이전 영역으로", () => pressHere("F6", true), false, "Shift+F6"],
    ["문맥 메뉴", () => pressHere("F10", true), false, "Shift+F10"],
  ] as MenuAction[]).map(([label, run, disabled, keys]) => ({ label, run, disabled, keys }));
}

/** 외부 변경·저장 실패의 결정 동사(AC24·§9.2) — 경보 구획과 비교 구획이 같은 배열·같은 실행 경로를 쓴다(IDE-01).
 *  저장 실패면 「다시 저장」이 더해지고 그것이 그 구획의 주 행동이다. */
export function externalVerbsFor(controller: Controller, item: Obj | undefined, act: Act) {
  return (saveFailed: boolean): ReactNode[] => !item ? [] : [
    button("현재 작업을 다른 이름으로 저장", act(() => controller.save(item.id, true), "save"), { key: "save-as" }),
    button("외부 파일 다시 열기", act(controller.reload), { key: "reload" }),
    ...(saveFailed ? [primary("다시 저장", act(() => controller.save(item.id), "save"), { key: "save" })] : [])];
}

/** 도구 막대(§3.1·APG toolbar)의 상태: 한 번의 Tab 으로 들어오고 ←→·Home·End 로 옮긴다(roving tabindex). 비활성(disabled) 단추는
 *  건너뛰고 흐린(aria-disabled) 만들기 단추는 초점을 받는다 — 눌러서 사유를 듣는 길이다(APG: 초점 가능한 비활성 허용). */
export function toolbarModel(view: Obj, editorState: Obj | null, readOnly: boolean, toolbarKey: string) {
  const undoDisabled = editorState ? !editorState.canUndo : false;
  const redoDisabled = editorState ? !editorState.canRedo : false;
  // 만들기 단추(NG-11): Python 판정이 있고 불가이면 흐린 단추(aria-disabled)로 초점과 누름을 받는다 — 누르면 실행하지 않고
  // 위치 줄 메모에 그 판정의 사유를 세운다(F2 불가와 같은 칸). 판정 전(pending)·읽기 전용은 사유가 없어 그대로 비활성이다.
  const creates = COMMANDS.slice(0, 3).map(([commandType, label]) => {
    const available = commandAvailability(view.commands, commandType);
    const disabled = readOnly || !!available.pending;
    return { commandType, label, available, disabled, dimmed: !disabled && !available.enabled };
  });
  const toolbarKeys = [...(undoDisabled ? [] : ["undo"]), ...(redoDisabled ? [] : ["redo"]), ...MODES.map(([value]) => `mode-${value}`),
    ...creates.filter((entry) => !entry.disabled).map((entry) => entry.commandType), "more", "trial"];
  const toolbarActive = toolbarKeys.includes(toolbarKey) ? toolbarKey : toolbarKeys[0];
  const rove = (key: string) => ({ "data-rove": key, tabIndex: key === toolbarActive ? 0 : -1 });
  return { undoDisabled, redoDisabled, creates, rove };
}

type ShellKeyContext = {
  controller: Controller; item: Obj | undefined; view: Obj; root: Ref<HTMLDivElement | null>; act: Act; barShown: boolean;
  setBarAnchor: (anchor: null) => void; openPanel: (panel: string) => void; openPalette: () => void;
  returnFocus: (slot: "properties" | "dock") => void; toolbarEntry: () => HTMLElement | null | undefined;
};

/** 셸 단축키 이름별 실행 — 키 판정은 shellShortcut 이 한다. 없는 이름은 아무것도 하지 않는다. */
const SHORTCUT_RUNS: Record<string, (ctx: ShellKeyContext, event: any) => void> = {
  save: (ctx) => ctx.act(() => ctx.controller.save(), "save")(),
  search: (ctx) => ctx.openPanel("search"),
  "editor-search": (ctx) => ctx.act(() => ctx.controller.command("search"))(),
  commands: (ctx) => ctx.openPalette(),
  rename: (ctx) => renameShortcut(ctx.controller),
  undo: (ctx) => ctx.act(() => ctx.controller.command("undo"))(),
  redo: (ctx) => ctx.act(() => ctx.controller.command("redo"))(),
  escape: (ctx) => escapeFocus(ctx.controller, ctx.view, ctx.returnFocus, () => focusFirst([ctx.toolbarEntry()])),
  // 패널 간 초점 이동(§10): 그려진 패널만 돌고, 접힌 구조는 레일 버튼이 대신 선다(authoring_layout.ts).
  // roving 묶음(탭·도구 막대·구조 목록)은 제 대기 항목(tabindex=0)으로 들어간다(UX-04).
  cycle: (ctx, event) => cyclePanels([...(ctx.root.current?.querySelectorAll<HTMLElement>(PANEL_CYCLE) || [])], document.activeElement, !!event.shiftKey),
};

/** Shift+F10·메뉴 키: 구조 목록·편집면 안에서만 그 자리 아래에 문맥 메뉴를 연다. */
function openShellContextMenu(ctx: ShellKeyContext, event: any) {
  const target = event.target as HTMLElement;
  if (!ctx.item || !target.closest?.(".authoring-outline,.authoring-canvas")) return;
  const rect = menuAnchor(target);
  event.preventDefault();
  openContextMenu(ctx.controller, { clientX: rect.left, clientY: rect.bottom, anchorTop: rect.top, target }, ctx.root.current);
}

/** Escape 가 셸보다 위의 일시 상태만 걷었는지 — 걷었으면 셸 Escape 단계로 가지 않는다. */
function dismissTransient(ctx: ShellKeyContext) {
  // 범위 고르기(두 번 누름) 중의 Escape 는 고르기만 접는다 — 패널·막대는 그대로다.
  if (ctx.view.rangePick) { ctx.controller.cancelRangePick(); return true; }
  // 떠 있는 선택 옆 막대가 가장 위의 일시 표면이다 — Escape 한 번은 막대만 걷는다.
  if (ctx.barShown) { ctx.setBarAnchor(null); return true; }
  return false;
}

/** 셸 키 처리기. IME 조합 중에는 문서 명령을 보내지 않는다 — 조합이 끝난 뒤 같은 명령을 다시 받는다. */
export function shellKeyHandler(ctx: ShellKeyContext) {
  return (event: any) => {
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    const shortcut = shellShortcut(event);
    if (!shortcut) return;
    if (shortcut === "context-menu") { openShellContextMenu(ctx, event); return; }
    if (shortcut === "escape" && dismissTransient(ctx)) return;
    if (shortcut !== "escape") event.preventDefault();
    SHORTCUT_RUNS[shortcut]?.(ctx, event);
  };
}

export const shellClassName = (dock: Dock, view: Obj) =>
  `authoring-shell${dock.active && view.dockMax ? " dock-max" : ""}${dock.active === "trial" ? " trial-open" : ""}`;

// 단일 live region(UX-04) — 보이지 않고, 전이 때만 한 줄이 선다. 차례 번호가 바뀌면 같은 문장도 다시 읽힌다.
export const renderLiveRegion = (view: Obj) =>
  h("p", { className: "authoring-live", role: "status" }, view.live?.text ? h("span", { key: view.live.seq }, view.live.text) : null);

// 오류 띠(§10·UX-04): 첫 문장만 보이고 기술 세부는 「자세히」 안에 둔다. 사용자가 닫거나 같은 종류의 작업이 성공해야 걷힌다.
export function renderErrorBand(view: Obj, controller: Controller, returnFocus: (slot: FocusSlot) => void) {
  const errorView = view.error ? errorParts(view.error) : null;
  return errorView && h("div", { className: "authoring-error" },
    h("p", { key: view.errorSeq, role: "alert" }, errorView.summary),
    errorView.detail && h("details", null, h("summary", null, "자세히"), h("pre", null, errorView.detail)),
    button("닫기", () => { controller.dismissError(); returnFocus("error"); }));
}

// 호환성 경고(U01·§7.1·P16): Python 판정이 서는 즉시 편집기 마운트와 무관하게 보이고, 마운트가 무너져도 남는다.
// 원본은 그대로 둔 채 확인(원문 표기)하거나 다른 이름으로 사본을 남기는 길을 함께 세운다.
export function renderCompatibility(item: Obj | undefined, controller: Controller, act: Act) {
  return item?.compatibility?.state === "limited" && h("section", { className: "authoring-compat", role: "alert", "aria-label": "호환성 경고" },
    h("strong", null, "읽기 전용 · 보존 확인 필요"),
    item.compatibility.message && h("p", null, item.compatibility.message),
    ...(item.compatibility.diagnostics || []).map((diagnostic: Obj | string, index: number) => typeof diagnostic === "string" ? h("p", { key: index }, diagnostic)
      : h("div", { key: index }, h("p", null, diagnostic.message), diagnostic.detail && h("p", { className: "authoring-reason" }, diagnostic.detail))),
    h("div", null, button("다른 이름으로 저장", act(() => controller.save(item.id, true), "save")), button("원문 표기", act(controller.raw))));
}

// 빈 작업대: 지금 할 수 있는 두 행동(머리의 것과 같은 실행 경로)만 둔다.
// 「변경할 문구를 선택해…」는 처음 여는 일반 문서의 안내라 Python 의 notice 로 선다(§13).
export function renderEmptyShell(item: Obj | undefined, controller: Controller, act: Act) {
  return !item && h("div", { className: "authoring-empty" }, h("p", null, "HWPX·TXT 문서를 열거나 새 TXT를 만드세요."),
    h("div", { className: "authoring-empty-actions" }, button("문서 열기", act(controller.openFile), { className: "btn primary" }), button("새 TXT", act(controller.create), { className: "btn" })));
}

type DockShellContext = {
  controller: Controller; item: Obj | undefined; view: Obj; dock: Dock; openDock: (key: string) => void; closeDock: () => void;
  dockContent: (key: string) => ReactNode;
};

/** 독 탭 하나 — 대기 탭(tabindex=0)은 펼친 탭, 없으면 첫 탭이다. 수가 있으면 배지를 단다. */
function dockTab([key, label]: [string, string], item: Obj, { view, dock, openDock }: DockShellContext, dockEntry: string | undefined) {
  const count = dockBadge(item, key, view);
  return h("button", { key, type: "button", role: "tab", id: `authoring-dock-tab-${key}`, className: "authoring-dock-tab", tabIndex: key === dockEntry ? 0 : -1, "aria-selected": key === dock.active,
    "aria-controls": key === dock.active ? "authoring-dock-panel" : undefined, onClick: () => openDock(key) },
    label, count ? " " : null, count ? h("span", { className: "authoring-badge" }, String(count)) : null);
}

// 하단 독(§3.1·APG tabs): 보조 패널은 한 번에 한 탭만 보인다. 탭 줄은 늘 남아 닫은 뒤에도 다시 열 길이 된다.
// ←→·Home·End 로 탭을 옮기고 Enter·Space 로 펼치면 그 패널의 첫 제어로 간다.
export function renderDock(context: DockShellContext) {
  const { controller, item, view, dock, closeDock, dockContent } = context;
  const dockEntry = dock.active || dock.tabs[0]?.[0];
  return item && h("section", { className: `authoring-dock${dock.active ? " open" : ""}${dock.active === "trial" ? " trial" : ""}`, role: "region", "aria-label": "보조 패널" },
    h("div", { className: "authoring-dock-bar" },
      h("div", { className: "authoring-dock-tabs", role: "tablist", "aria-label": "보조 패널", onKeyDown: (event: any) => { roveFocus(event, event.currentTarget, '[role="tab"]', "horizontal"); } },
        ...dock.tabs.map((tab) => dockTab(tab, item, context, dockEntry))),
      dock.active && h("div", { className: "authoring-dock-actions" },
        iconButton(view.dockMax ? "restore" : "maximize", view.dockMax ? "복원" : "최대화", () => controller.update({ dockMax: !view.dockMax })),
        iconButton("close", "닫기", closeDock))),
    dock.active && h("div", { className: "authoring-dock-panel", id: "authoring-dock-panel", role: "tabpanel", tabIndex: -1, "aria-labelledby": `authoring-dock-tab-${dock.active}` }, dockContent(dock.active)));
}
