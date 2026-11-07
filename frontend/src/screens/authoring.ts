import { createElement as h, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { DOCUMENT_COMMANDS } from "./authoring_controller.ts";
import type { AuthoringLayout } from "./authoring_layout.ts";
import type { liveStep } from "./authoring_a11y.ts";
import type { Obj, Props } from "./authoring_primitives.ts";
import { renderAuthoringHeader } from "./authoring_header.ts";
import { renderAuthoringToolbar } from "./authoring_toolbar.ts";
import { renderAuthoringBody } from "./authoring_body.ts";
import { renderAuthoringFooter } from "./authoring_footer.ts";
import { renderAuthoringOverlays } from "./authoring_overlays.ts";
import { shellMenuActions } from "./authoring_shell_actions.ts";
import { liveState } from "./authoring_shell_state.ts";
import { ProposalBand, ProposalPopover } from "./authoring_proposal_view.ts";
import { useContextMenuFocus, useExternalCheck, useForcedDock, useLiveAnnounce, useMenuPlacement, usePanelFocus,
  useSelectionBarDismiss, useSelectionBarPlacement, useTabFocusRestore } from "./authoring_screen_effects.ts";
import { externalVerbsFor, isReadOnly, menuReasonFor, renderCompatibility, renderDock, renderEmptyShell, renderErrorBand,
  renderLiveRegion, shellClassName, shellKeyHandler, shellNavigation, shellPaletteActions, shellPanels, toolbarModel } from "./authoring_screen_parts.ts";
export { saveLabel, readinessText, liveState } from "./authoring_shell_state.ts";

export { crumbs, problemSeverities } from "./authoring_outline.ts";

import { renderDockContent, dockControls } from "./authoring_dock.ts";
export { trialAnchorName, hwpxTrialAnchor, centeredScrollTop, TRIAL_VIEW_ZOOM, keepFocusOutside } from "./authoring_trial.ts";

export { appliedProperties, escapeStage, sameCommand, submitProperties } from "./authoring_properties.ts";

import { zoomChoice } from "./authoring_editor.ts";
import type { ShellInput, LineRect } from "./authoring_editor.ts";
export { rhwpMount, trialViewerKey, externalDocumentSpec, forwardedShellKey, shellShortcut,
  compatibilityReporter, ZOOM_STEPS, zoomChoice, highlightRanges } from "./authoring_editor.ts";

import { dockTabs, commandEntries, selectionBarItems, selectionBarShown } from "./authoring_commands.ts";
export { openContextMenu, focusRequest, dockBadge, renameChoice, renameShortcut, selectionNoteView,
  DOCK_PANELS, dockTabs, sharedReason, escapeShell, copyText, commandEntries, selectionBarItems,
  SELECTION_BAR_GAP, selectionBarPlace } from "./authoring_commands.ts";

import { problemCounts } from "./authoring_outline_model.ts";
export { COVERAGE_LABEL, sameFieldMeta, outlineSpine, groupedPath, fieldsInFirstUse, outlineKey, outlineCurrent,
  filterMatch, problemCount, problemCounts, outlineLabel, problemFix, txtProblemMarks, markerPairs, problemAction,
  commandAvailability } from "./authoring_outline_model.ts";
export type { SpineUse, SpineNode } from "./authoring_outline_model.ts";

/** 저작 작업대 셸 — 상태 구독과 셸 참조를 쥐고, 동작 묶음(authoring_screen_parts)·효과(authoring_screen_effects)·
 *  구획 렌더러를 지금 상태로 엮는다. 효과 훅은 선언 순서대로 돌므로 부르는 순서가 곧 효과 순서다. */
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
  const { toolbarEntry, returnFocus, select, selectInDock, contextMenu, chooseFromOutline, outlineMenu, closeTab } =
    shellNavigation({ controller, item, tabs, act, root, openers, pendingOpener, pendingTabFocus });
  usePanelFocus(view, root, pendingOpener, openers);
  useExternalCheck(controller);
  useContextMenuFocus(controller, view, menuRef);
  useMenuPlacement(view, menuRef, root);
  useTabFocusRestore(root, pendingTabFocus);
  const liveNow = liveState(item, view, item ? controller.pending(item.id) : false);
  useLiveAnnounce(controller, liveRef, liveNow);
  useForcedDock(controller, dock, item?.id);
  const editorState = item ? controller.editorState(item.id) : null;
  const readOnly = isReadOnly(item);
  const { pick, openPanel, openPalette, closePalette, menuToggle, menuButton } =
    shellPanels({ controller, view, act, root, pendingOpener, paletteOpener, toolbarEntry });
  const commandTable = commandEntries(view.commands, readOnly);
  // 명령 팔레트는 선택 명령 뒤에 문서 명령을 싣는다 — 판정은 선택이 아니라 문서(탭 투영)의 것이다.
  const paletteTable = [...commandTable, ...commandEntries(item?.document_commands, readOnly, DOCUMENT_COMMANDS)];
  // 막대는 지금 선택에 대한 Python 판정이 도착했을 때만 선다(commandsSelection) — 판정 전·다른 선택의 판정으로는 서지 않는다.
  // 초점은 옮기지 않는다: 단추는 Tab 순서 밖이고 누름이 초점을 먼저 가져가지 않는다. 키보드 입구는 Shift+F10 문맥 메뉴다.
  const barItems = selectionBarItems(commandTable, readOnly);
  const barShown = selectionBarShown(item?.id, barAnchor?.id, view, barItems.length);
  useSelectionBarDismiss(view, barAnchor, setBarAnchor, root);
  useSelectionBarPlacement(barShown, barAnchor, barItems, barRef, root);
  const menuEditor = !!view.contextMenu?.editor;
  const menuReason = menuReasonFor(view, commandTable, readOnly, menuEditor);
  shellInput.current.palette = () => openPalette();
  const { moreActions, fileActions } = shellMenuActions({ controller, item, act, openPalette, openPanel });
  const { openDock, closeDock, closePanel } = dockControls({ controller, view, dock, act, openPanel, returnFocus });
  const paletteActions = shellPaletteActions({ fileActions, moreActions, openPanel, openDock, root, shellInput });
  const trialShown = dock.active === "trial";
  const zoom = zoomChoice(item?.media, view.zoom);
  const externalVerbs = externalVerbsFor(controller, item, act);
  const dockContent = (key: string): ReactNode => renderDockContent(key, { controller, item, view, shell: shellInput, act, selectInDock, externalVerbs, closePanel });
  const { undoDisabled, redoDisabled, creates, rove } = toolbarModel(view, editorState, readOnly, toolbarKey);
  return h("div", { className: shellClassName(dock, view), ref: root, onKeyDown: shellInput.current.key = shellKeyHandler({
    controller, item, view, root, act, barShown, setBarAnchor, openPanel, openPalette, returnFocus, toolbarEntry }) },
    renderLiveRegion(view),
    // 머리 띠(편집기 제목 줄): 돌아가기 그림 · 제목 · 「파일」 메뉴 · 열린 문서 탭(가운데, 넘치면 가로 스크롤) · 저장.
    // 파일 동사(열기·새 TXT·다른 이름으로 저장)는 「파일」 메뉴 안에 선다 — 띠에 보이는 행동은 저장 하나다.
    renderAuthoringHeader({ controller, tabs, snapshot, act, menuToggle, menuButton, closeTab, item }),
    renderErrorBand(view, controller, returnFocus),
    // 저장 결과의 알림(AC14·P09) — Python 이 준 문장만 보이고, 다음 편집에서 사라진다. 읽기는 live region 이 한다.
    view.notice && h("p", { className: "authoring-notice" }, view.notice),
    renderCompatibility(item, controller, act),
    renderEmptyShell(item, controller, act),
    // 도구 막대(§3.1): 한 줄, 줄바꿈 없음 — 넘치면 가로 스크롤. 보조 패널을 여는 동사는 하단 독의 탭으로 옮겼다.
    renderAuthoringToolbar({ controller, item, view, act, toolbarKey, setToolbarKey, undoDisabled, redoDisabled, readOnly, creates, rove, pick, menuToggle, menuButton, trialShown, openDock }),
    // 「데이터로 필드 찾기」 띠(#1156) — 도구 막대 아래 이름 붙은 구획. 꺼져 있으면 서지 않는다.
    h(ProposalBand, { controller, item, view }),
    renderAuthoringBody({ tabs, item, view, snapshot, outlineOpen, setOutlineOpen, controller, counts, chooseFromOutline, outlineMenu, contextMenu, layout, zoom, select, shellInput, returnFocus }),
    renderDock({ controller, item, view, dock, openDock, closeDock, dockContent }),
    // 제안 팝오버(#1156) — 셸 층의 비모달 대화상자. 문서 자리·구조 패널 줄 곁에 선다.
    h(ProposalPopover, { controller, item, view }),
    ...renderAuthoringOverlays({ controller, item, view, menuRef, menuReason, fileActions, moreActions, commandTable, readOnly, menuEditor, pick, openPalette, barShown, barRef, barItems, setBarAnchor, paletteTable, paletteActions, closePalette }),
    // 상태 막대: 줄마다 바뀌는 상태라 live region 이 아니다(읽기는 위의 단일 live region 이 전이 때만 한다).
    renderAuthoringFooter({ item, controller, liveNow, openDock, zoom }),
  );
}
