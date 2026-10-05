import { createElement as h, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { COMMANDS, DOCUMENT_COMMANDS } from "./authoring_controller.ts";
import { PANEL_CYCLE, cyclePanels } from "./authoring_layout.ts";
import type { AuthoringLayout } from "./authoring_layout.ts";
import { FOCUSABLE, clampMenu, errorParts, focusFirst, focusable, liveStep, roveFocus } from "./authoring_a11y.ts";
import { menuLines } from "./command_palette.ts";
import type { PaletteAction } from "./command_palette.ts";
import { button, primary, iconButton } from "./authoring_primitives.ts";
import type { Obj, Props } from "./authoring_primitives.ts";
import { renderAuthoringHeader } from "./authoring_header.ts";
import { renderAuthoringToolbar } from "./authoring_toolbar.ts";
import { renderAuthoringBody } from "./authoring_body.ts";
import { renderAuthoringFooter } from "./authoring_footer.ts";
import { renderAuthoringOverlays } from "./authoring_overlays.ts";
import { shellMenuActions } from "./authoring_shell_actions.ts";
import { MODES, liveState, menuAnchor } from "./authoring_shell_state.ts";
import { ProposalBand, ProposalPopover } from "./authoring_proposal_view.ts";
export { saveLabel, readinessText, liveState } from "./authoring_shell_state.ts";

export { crumbs, problemSeverities } from "./authoring_outline.ts";

import { renderDockContent, dockControls } from "./authoring_dock.ts";
export { trialAnchorName, hwpxTrialAnchor, centeredScrollTop, TRIAL_VIEW_ZOOM, keepFocusOutside } from "./authoring_trial.ts";

export { appliedProperties, escapeStage, sameCommand, submitProperties } from "./authoring_properties.ts";

import { shellShortcut, zoomChoice } from "./authoring_editor.ts";
import type { ShellInput, LineRect } from "./authoring_editor.ts";
export { rhwpMount, trialViewerKey, externalDocumentSpec, forwardedShellKey, shellShortcut,
  compatibilityReporter, ZOOM_STEPS, zoomChoice, highlightRanges } from "./authoring_editor.ts";

import { CREATE_TYPES, openContextMenu, focusRequest, dockBadge, renameShortcut,
  DOCK_PANELS, dockTabs, sharedReason, escapeShell, commandEntries,
  selectionBarItems, selectionBarPlace, selectionBarShown, PALETTE_SELF } from "./authoring_commands.ts";
import type { MenuAction } from "./authoring_commands.ts";
export { openContextMenu, focusRequest, dockBadge, renameChoice, renameShortcut, selectionNoteView,
  DOCK_PANELS, dockTabs, sharedReason, escapeShell, copyText, commandEntries, selectionBarItems,
  SELECTION_BAR_GAP, selectionBarPlace } from "./authoring_commands.ts";

import { problemCounts, commandAvailability } from "./authoring_outline_model.ts";
export { COVERAGE_LABEL, sameFieldMeta, outlineSpine, groupedPath, fieldsInFirstUse, outlineKey, outlineCurrent,
  filterMatch, problemCount, problemCounts, outlineLabel, problemFix, txtProblemMarks, markerPairs, problemAction,
  commandAvailability } from "./authoring_outline_model.ts";
export type { SpineUse, SpineNode } from "./authoring_outline_model.ts";

/** 셸 Escape 한 단계 뒤의 초점 — 패널을 닫았으면 연 자리로, 메뉴의 연 자리가 없으면 도구 막대로. 제안 팝오버만 걷었으면(#1156)
 *  초점은 이미 편집면에 있으므로 옮기지 않는다. */
function escapeFocus(controller: Props["controller"], view: Obj, returnFocus: (slot: "properties" | "dock") => void, focusToolbar: () => void) {
  const closing = view.panel;
  const stage = escapeShell(controller);
  if (stage === "panel") returnFocus(closing && closing !== "properties" ? "dock" : "properties");
  else if (stage === "menu" && !focusable(view.contextMenu?.trigger)) focusToolbar();
}

/** IME 조합 중에는 문서 명령을 보내지 않는다 — 조합이 끝난 뒤 같은 명령을 다시 받는다. */

export function AuthoringScreen({ controller, layout }: Props & { layout?: AuthoringLayout | null }): ReactNode {
  const snapshot = useSyncExternalStore(controller.model.subscribe, controller.model.getSnapshot, controller.model.getSnapshot) || {};
  const view = useSyncExternalStore(controller.viewModel.subscribe, controller.viewModel.getSnapshot, controller.viewModel.getSnapshot);
  const tabs: Obj[] = snapshot.tabs || [];
  const item = tabs.find((tab) => tab.id === snapshot.active_id);
  const root = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  // 패널·독을 연 자리(초점 복귀 대상, UX-04). 요청자가 먼저 알면 pendingOpener 로 넘기고, 아니면 초점을 옮기기 직전의 원소다.
  const openers = useRef<Record<string, unknown>>({});
  const pendingOpener = useRef<unknown>(null);
  // 명령 팔레트를 연 자리(IDE-02) — 닫으면 그리로 초점을 돌린다.
  const paletteOpener = useRef<unknown>(null);
  const pendingTabFocus = useRef("");
  const liveRef = useRef<ReturnType<typeof liveStep>["state"] | null>(null);
  const [toolbarKey, setToolbarKey] = useState("");
  // 좁은 폭(컨테이너 64rem 이하)에서만 쓰이는 구조 레일의 펼침 — 넓은 폭에서는 CSS 가 무시한다.
  const [outlineOpen, setOutlineOpen] = useState(false);
  const shellInput: ShellInput = useRef<ShellInput["current"]>({});
  // 선택 옆 막대(IDE-08 P-05)의 자리 — 편집기가 보고한 선택 끝 줄(호스트 좌표)이다. 선택이 바뀌거나 비거나 문서가 편집되면
  // 편집기가 걷고(같은 선택을 다시 보고하지 않는다), Escape·스크롤·창 크기·메뉴·팔레트·막대 누름은 셸이 걷는다.
  const [barAnchor, setBarAnchor] = useState<{ id: string; rect: LineRect } | null>(null);
  const barRef = useRef<HTMLDivElement>(null);
  shellInput.current.selectionRect = (id, rect) => setBarAnchor(rect ? { id, rect } : null);
  const dock = dockTabs(item, view);
  const counts = useMemo(() => problemCounts(item?.problems), [item?.problems]);
  const act = (work: () => unknown, kind?: string) => () => { void controller.guarded(work, kind); };
  const toolbarEntry = () => root.current?.querySelector<HTMLElement>('.authoring-toolbar [data-rove][tabindex="0"]');
  /** 닫힌 패널에서 초점을 돌린다: 속성은 §10 대로 선택 자리 먼저, 독·메뉴·오류는 연 자리 먼저. 마지막은 도구 막대. */
  const returnFocus = (slot: "properties" | "dock" | "error") => act(async () => {
    const opener = openers.current[slot];
    openers.current[slot] = null;
    if (slot === "properties" && await controller.focusSelection()) return;
    if (focusFirst([opener])) return;
    if (slot !== "properties" && await controller.focusSelection()) return;
    focusFirst([toolbarEntry(), root.current?.querySelector(".authoring-head button")]);
  }, "focus")();
  // 초점 요청(focusRequest)만 초점을 옮긴다 — 패널 값·명령 종류·판정 도착은 옮기지 않는다(WCAG 3.2.2).
  // 문맥 메뉴가 열려 있으면 메뉴가 초점을 쥔다.
  useEffect(() => {
    const shell = root.current;
    if (!view.focusPanel || !shell || view.contextMenu) return;
    const slot = view.focusTarget === "dock" ? "dock" : "properties";
    const panel = shell.querySelector<HTMLElement>(slot === "dock" ? "#authoring-dock-panel" : ".authoring-properties");
    const active = shell.ownerDocument?.activeElement;
    const opener = pendingOpener.current ?? (active && active !== shell.ownerDocument?.body && !panel?.contains(active) ? active : null);
    pendingOpener.current = null;
    if (opener) openers.current[slot] = opener;
    const target = slot === "dock" ? panel?.querySelector<HTMLElement>(FOCUSABLE) || panel : shell.querySelector<HTMLElement>(".authoring-properties input");
    target?.focus();
    // 이름 칸은 전체 선택된 채 받는다(P-06) — 제안값이든 적용값이든 치면 바로 바뀐다.
    if (slot === "properties") (target as HTMLInputElement | null | undefined)?.select?.();
  }, [view.focusPanel]);
  useEffect(() => {
    const focus = () => { void controller.guarded(controller.checkExternal, "external"); };
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, [controller]);
  // 문맥 메뉴(§6.1): 열리면 첫 사용 가능 항목(없으면 첫 항목)에 초점, 바깥 클릭이면 닫는다. Escape 는 셸 단축키가 처리한다.
  // 「더보기」·「파일」 메뉴는 여는 버튼 자체의 누름을 바깥으로 치지 않는다 — 그 버튼이 여닫기를 맡는다.
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
  // 메뉴는 그린 뒤 실제 크기로 창 안에 든다 — 아래가 모자라면 위로 뒤집고, 그래도 넘치면 가장자리에 붙인다(UX-04).
  useLayoutEffect(() => {
    const menu = menuRef.current;
    const shell = root.current;
    const anchor = view.contextMenu?.anchor;
    const win = shell?.ownerDocument?.defaultView;
    if (!menu || !shell || !anchor || !win?.innerWidth || typeof menu.getBoundingClientRect !== "function") return;
    const size = menu.getBoundingClientRect();
    const place = clampMenu(anchor, { width: size.width, height: size.height }, { width: win.innerWidth, height: win.innerHeight });
    const base = shell.getBoundingClientRect();
    menu.style.left = `${place.left - base.left - (shell.clientLeft || 0) + (shell.scrollLeft || 0)}px`;
    menu.style.top = `${place.top - base.top - (shell.clientTop || 0) + (shell.scrollTop || 0)}px`;
  }, [view.contextMenu]);
  // 문서 탭을 닫은 뒤에는 이웃 탭에 초점(APG tabs). 탭이 하나도 남지 않으면 빈 작업대의 첫 행동으로.
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
  // 단일 live region(UX-04): 전이 때만 한 번 쓴다 — 키 입력마다 바뀌는 상태 막대는 읽지 않는다.
  const liveNow = liveState(item, view, item ? controller.pending(item.id) : false);
  useEffect(() => {
    const { state, message } = liveStep(liveRef.current, liveNow);
    liveRef.current = state;
    if (message) controller.announce(message);
  });
  // 경보(외부 파일 변경)는 새로 서는 순간 독의 제 탭을 펼친다 — 닫아 둔 독도 다시 연다. 초점은 옮기지 않는다(경보가 읽힌다).
  const forced = dock.tabs.some(([key]) => key === "external_changed") ? "external_changed" : "";
  useEffect(() => {
    if (!forced) return;
    const current = controller.viewModel.getSnapshot();
    controller.update({ dock: forced, dockClosed: false, ...(DOCK_PANELS.includes(current.panel) && current.panel !== "comparison" ? { panel: "" } : {}) });
  }, [forced, item?.id]);
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
  const editorState = item ? controller.editorState(item.id) : null;
  const readOnly = !!item && item.media === "hwpx" && item.rhwp_editable !== true;
  // F2(§10): 패널이 이미 열려 있어도 이름 칸으로 초점을 옮긴다 — focusPanel 은 그 요청의 차례 번호다.
  // 되는 이름 변경이 없으면 패널 대신 위치 줄에 사유가 선다(IDE-01) — 편집면이 넘긴 F2 와 같은 함수다.
  const rename = () => renameShortcut(controller);
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
  const commandTable = commandEntries(view.commands, readOnly);
  // 명령 팔레트는 선택 명령 뒤에 문서 명령을 싣는다 — 판정은 선택이 아니라 문서(탭 투영)의 것이다.
  const paletteTable = [...commandTable, ...commandEntries(item?.document_commands, readOnly, DOCUMENT_COMMANDS)];
  // 막대는 지금 선택에 대한 Python 판정이 도착했을 때만 선다(commandsSelection) — 판정 전·다른 선택의 판정으로는 서지 않는다.
  // 초점은 옮기지 않는다: 단추는 Tab 순서 밖이고 누름이 초점을 먼저 가져가지 않는다. 키보드 입구는 Shift+F10 문맥 메뉴다.
  const barItems = selectionBarItems(commandTable, readOnly);
  const barShown = selectionBarShown(item?.id, barAnchor?.id, view, barItems.length);
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
  // 막대는 그린 뒤 실제 크기로 선택 끝 줄 아래(모자라면 위)에 창 안으로 든다 — 셸 층이라 편집면 확대의 영향을 받지 않는다.
  const barKey = barItems.map((entry) => entry.key).join(" ");
  useLayoutEffect(() => {
    const bar = barRef.current;
    const shell = root.current;
    const win = shell?.ownerDocument?.defaultView;
    if (!barShown || !bar || !shell || !barAnchor || !win?.innerWidth || typeof bar.getBoundingClientRect !== "function") return;
    const size = bar.getBoundingClientRect();
    const place = selectionBarPlace(barAnchor.rect, { width: size.width, height: size.height }, { width: win.innerWidth, height: win.innerHeight });
    const base = shell.getBoundingClientRect();
    bar.style.left = `${place.left - base.left - (shell.clientLeft || 0) + (shell.scrollLeft || 0)}px`;
    bar.style.top = `${place.top - base.top - (shell.clientTop || 0) + (shell.scrollTop || 0)}px`;
  }, [barShown, barAnchor, barKey]);
  // 판정이 섰는데 되는 명령도 대안도 없어 문맥 메뉴가 「명령」 한 줄뿐이면 그 위에 공유 사유를 한 줄 세운다(읽기 전용 제외).
  // 편집면 메뉴는 「필드로 만들기」가 제 사유를 싣고 서므로(결정 C) 그 한 줄뿐인 경우가 없다.
  const menuEditor = !!view.contextMenu?.editor;
  const menuReason = !readOnly && !menuLines(commandTable, readOnly, menuEditor) ? sharedReason(view.commands) : null;
  shellInput.current.palette = () => openPalette();
  const { moreActions, fileActions } = shellMenuActions({ controller, item, act, openPalette, openPanel });
  /** 「더보기」·「파일」을 여닫는 단추의 누름 — 열린 제 메뉴면 닫고, 아니면 단추 아래에 연다. */
  const menuToggle = (kind: "more" | "file") => (event: any) => {
    if (view.contextMenu?.kind === kind) { controller.update({ contextMenu: null }); return; }
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    openContextMenu(controller, { clientX: rect.left, clientY: rect.bottom, target: event.currentTarget }, root.current, kind);
  };
  const menuButton = (kind: "more" | "file") => ({ "aria-haspopup": "menu", "aria-expanded": view.contextMenu?.kind === kind, "aria-controls": view.contextMenu?.kind === kind ? "authoring-menu" : undefined });
  const { openDock, closeDock, closePanel } = dockControls({ controller, view, dock, act, openPanel, returnFocus });
  const closeTab = (id: string) => act(async () => {
    const ids = tabs.map((tab) => tab.id);
    const at = ids.indexOf(id);
    const neighbour = ids[at + 1] ?? ids[at - 1] ?? "";
    if (!(await controller.close(id))) return;
    pendingTabFocus.current = neighbour || "-";
    controller.update({});
  })();
  // 팔레트의 셸 동작(1부) — 키 학습 표면이다(L-50): 셸 키가 있는 동작은 그 키를 곁에 싣는다. 실행 경로는 「파일」·「더보기」·
  // 셸 키와 같다. 영역 이동·문맥 메뉴는 팔레트가 연 자리로 초점을 돌린 뒤 그 자리에서 누른 키와 같다.
  const pressHere = (key: string, shiftKey: boolean) => {
    const target = root.current?.ownerDocument?.activeElement as HTMLElement | null | undefined;
    const KeyboardEvent = (target?.ownerDocument?.defaultView as Obj | null | undefined)?.KeyboardEvent;
    // 진짜 키 사건을 그 자리에 쏘면 구조 목록처럼 제 키를 먼저 받는 곳(줄을 고른 뒤 메뉴)도 사람이 누른 것과 같게 간다.
    if (target && KeyboardEvent && typeof target.dispatchEvent === "function") target.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true, cancelable: true }));
    else shellInput.current.key?.({ key, shiftKey, target, nativeEvent: {}, preventDefault() {} });
  };
  const paletteActions: PaletteAction[] = ([
    ...fileActions.filter(([label]) => label === "저장" || label === "다른 이름으로 저장"),
    ["찾기", () => openPanel("search"), false, "Ctrl+F"],
    ["결과 시험", () => openDock("trial"), false],
    ...moreActions.filter(([label]) => label !== PALETTE_SELF),
    ["다음 영역으로", () => pressHere("F6", false), false, "F6"],
    ["이전 영역으로", () => pressHere("F6", true), false, "Shift+F6"],
    ["문맥 메뉴", () => pressHere("F10", true), false, "Shift+F10"],
  ] as MenuAction[]).map(([label, run, disabled, keys]) => ({ label, run, disabled, keys }));
  const trialShown = dock.active === "trial";
  const zoom = zoomChoice(item?.media, view.zoom);
  /** 외부 변경·저장 실패의 결정 동사(AC24·§9.2) — 경보 구획과 비교 구획이 같은 배열·같은 실행 경로를 쓴다(IDE-01).
   *  저장 실패면 「다시 저장」이 더해지고 그것이 그 구획의 주 행동이다. */
  const externalVerbs = (saveFailed: boolean): ReactNode[] => !item ? [] : [
    button("현재 작업을 다른 이름으로 저장", act(() => controller.save(item.id, true), "save"), { key: "save-as" }),
    button("외부 파일 다시 열기", act(controller.reload), { key: "reload" }),
    ...(saveFailed ? [primary("다시 저장", act(() => controller.save(item.id), "save"), { key: "save" })] : [])];
  const dockContent = (key: string): ReactNode => renderDockContent(key, { controller, item, view, act, selectInDock, externalVerbs, closePanel });
  // 도구 막대(§3.1·APG toolbar): 한 번의 Tab 으로 들어오고 ←→·Home·End 로 옮긴다(roving tabindex). 비활성(disabled) 단추는 건너뛰고
  // 흐린(aria-disabled) 만들기 단추는 초점을 받는다 — 눌러서 사유를 듣는 길이다(APG: 초점 가능한 비활성 허용).
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
  const dockEntry = dock.active || dock.tabs[0]?.[0];
  const errorView = view.error ? errorParts(view.error) : null;
  return h("div", { className: `authoring-shell${dock.active && view.dockMax ? " dock-max" : ""}${dock.active === "trial" ? " trial-open" : ""}`, ref: root, onKeyDown: shellInput.current.key = (event: any) => {
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    const shortcut = shellShortcut(event);
    if (!shortcut) return;
    if (shortcut === "context-menu") {
      const target = event.target as HTMLElement;
      if (!item || !target.closest?.(".authoring-outline,.authoring-canvas")) return;
      const rect = menuAnchor(target);
      event.preventDefault();
      openContextMenu(controller, { clientX: rect.left, clientY: rect.bottom, anchorTop: rect.top, target }, root.current);
      return;
    }
    // 범위 고르기(두 번 누름) 중의 Escape 는 고르기만 접는다 — 패널·막대는 그대로다.
    if (shortcut === "escape" && view.rangePick) { controller.cancelRangePick(); return; }
    // 떠 있는 선택 옆 막대가 가장 위의 일시 표면이다 — Escape 한 번은 막대만 걷는다.
    if (shortcut === "escape" && barShown) { setBarAnchor(null); return; }
    if (shortcut !== "escape") event.preventDefault();
    if (shortcut === "save") act(() => controller.save(), "save")();
    else if (shortcut === "search") openPanel("search");
    else if (shortcut === "editor-search") act(() => controller.command("search"))();
    else if (shortcut === "commands") openPalette();
    else if (shortcut === "rename") rename();
    else if (shortcut === "undo" || shortcut === "redo") act(() => controller.command(shortcut))();
    else if (shortcut === "escape") escapeFocus(controller, view, returnFocus, () => focusFirst([toolbarEntry()]));
    else if (shortcut === "cycle") {
      // 패널 간 초점 이동(§10): 그려진 패널만 돌고, 접힌 구조는 레일 버튼이 대신 선다(authoring_layout.ts).
      // roving 묶음(탭·도구 막대·구조 목록)은 제 대기 항목(tabindex=0)으로 들어간다(UX-04).
      cyclePanels([...(root.current?.querySelectorAll<HTMLElement>(PANEL_CYCLE) || [])], document.activeElement, !!event.shiftKey);
    }
  } },
    // 단일 live region(UX-04) — 보이지 않고, 전이 때만 한 줄이 선다. 차례 번호가 바뀌면 같은 문장도 다시 읽힌다.
    h("p", { className: "authoring-live", role: "status" }, view.live?.text ? h("span", { key: view.live.seq }, view.live.text) : null),
    // 머리 띠(편집기 제목 줄): 돌아가기 그림 · 제목 · 「파일」 메뉴 · 열린 문서 탭(가운데, 넘치면 가로 스크롤) · 저장.
    // 파일 동사(열기·새 TXT·다른 이름으로 저장)는 「파일」 메뉴 안에 선다 — 띠에 보이는 행동은 저장 하나다.
    renderAuthoringHeader({ controller, tabs, snapshot, act, menuToggle, menuButton, closeTab, item }),
    // 오류 띠(§10·UX-04): 첫 문장만 보이고 기술 세부는 「자세히」 안에 둔다. 사용자가 닫거나 같은 종류의 작업이 성공해야 걷힌다.
    errorView && h("div", { className: "authoring-error" },
      h("p", { key: view.errorSeq, role: "alert" }, errorView.summary),
      errorView.detail && h("details", null, h("summary", null, "자세히"), h("pre", null, errorView.detail)),
      button("닫기", () => { controller.dismissError(); returnFocus("error"); })),
    // 저장 결과의 알림(AC14·P09) — Python 이 준 문장만 보이고, 다음 편집에서 사라진다. 읽기는 live region 이 한다.
    view.notice && h("p", { className: "authoring-notice" }, view.notice),
    // 호환성 경고(U01·§7.1·P16): Python 판정이 서는 즉시 편집기 마운트와 무관하게 보이고, 마운트가 무너져도 남는다.
    // 원본은 그대로 둔 채 확인(원문 표기)하거나 다른 이름으로 사본을 남기는 길을 함께 세운다.
    item?.compatibility?.state === "limited" && h("section", { className: "authoring-compat", role: "alert", "aria-label": "호환성 경고" },
      h("strong", null, "읽기 전용 · 보존 확인 필요"),
      item.compatibility.message && h("p", null, item.compatibility.message),
      ...(item.compatibility.diagnostics || []).map((diagnostic: Obj | string, index: number) => typeof diagnostic === "string" ? h("p", { key: index }, diagnostic)
        : h("div", { key: index }, h("p", null, diagnostic.message), diagnostic.detail && h("p", { className: "authoring-reason" }, diagnostic.detail))),
      h("div", null, button("다른 이름으로 저장", act(() => controller.save(item.id, true), "save")), button("원문 표기", act(controller.raw)))),
    // 빈 작업대: 지금 할 수 있는 두 행동(머리의 것과 같은 실행 경로)만 둔다.
    // 「변경할 문구를 선택해…」는 처음 여는 일반 문서의 안내라 Python 의 notice 로 선다(§13).
    !item && h("div", { className: "authoring-empty" }, h("p", null, "HWPX·TXT 문서를 열거나 새 TXT를 만드세요."),
      h("div", { className: "authoring-empty-actions" }, button("문서 열기", act(controller.openFile), { className: "btn primary" }), button("새 TXT", act(controller.create), { className: "btn" }))),
    // 도구 막대(§3.1): 한 줄, 줄바꿈 없음 — 넘치면 가로 스크롤. 보조 패널을 여는 동사는 하단 독의 탭으로 옮겼다.
    renderAuthoringToolbar({ controller, item, view, act, toolbarKey, setToolbarKey, undoDisabled, redoDisabled, readOnly, creates, rove, pick, menuToggle, menuButton, trialShown, openDock }),
    // 「데이터로 필드 찾기」 띠(#1156) — 도구 막대 아래 이름 붙은 구획. 꺼져 있으면 서지 않는다.
    h(ProposalBand, { controller, item, view }),
    renderAuthoringBody({ tabs, item, view, snapshot, outlineOpen, setOutlineOpen, controller, counts, chooseFromOutline, outlineMenu, contextMenu, layout, zoom, select, shellInput, returnFocus }),
    // 하단 독(§3.1·APG tabs): 보조 패널은 한 번에 한 탭만 보인다. 탭 줄은 늘 남아 닫은 뒤에도 다시 열 길이 된다.
    // ←→·Home·End 로 탭을 옮기고 Enter·Space 로 펼치면 그 패널의 첫 제어로 간다.
    item && h("section", { className: `authoring-dock${dock.active ? " open" : ""}${dock.active === "trial" ? " trial" : ""}`, role: "region", "aria-label": "보조 패널" },
      h("div", { className: "authoring-dock-bar" },
        h("div", { className: "authoring-dock-tabs", role: "tablist", "aria-label": "보조 패널", onKeyDown: (event: any) => { roveFocus(event, event.currentTarget, '[role="tab"]', "horizontal"); } }, ...dock.tabs.map(([key, label]) => {
          const count = dockBadge(item, key, view);
          return h("button", { key, type: "button", role: "tab", id: `authoring-dock-tab-${key}`, className: "authoring-dock-tab", tabIndex: key === dockEntry ? 0 : -1, "aria-selected": key === dock.active,
            "aria-controls": key === dock.active ? "authoring-dock-panel" : undefined, onClick: () => openDock(key) },
            label, count ? " " : null, count ? h("span", { className: "authoring-badge" }, String(count)) : null);
        })),
        dock.active && h("div", { className: "authoring-dock-actions" },
          iconButton(view.dockMax ? "restore" : "maximize", view.dockMax ? "복원" : "최대화", () => controller.update({ dockMax: !view.dockMax })),
          iconButton("close", "닫기", closeDock))),
      dock.active && h("div", { className: "authoring-dock-panel", id: "authoring-dock-panel", role: "tabpanel", tabIndex: -1, "aria-labelledby": `authoring-dock-tab-${dock.active}` }, dockContent(dock.active))),
    // 제안 팝오버(#1156) — 셸 층의 비모달 대화상자. 문서 자리·구조 패널 줄 곁에 선다.
    h(ProposalPopover, { controller, item, view }),
    ...renderAuthoringOverlays({ controller, item, view, menuRef, menuReason, fileActions, moreActions, commandTable, readOnly, menuEditor, pick, openPalette, barShown, barRef, barItems, setBarAnchor, paletteTable, paletteActions, closePalette }),
    // 상태 막대: 줄마다 바뀌는 상태라 live region 이 아니다(읽기는 위의 단일 live region 이 전이 때만 한다).
    renderAuthoringFooter({ item, controller, liveNow, openDock, zoom }),
  );
}
