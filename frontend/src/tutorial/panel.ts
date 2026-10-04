/* Eight task lessons. The host owns lesson state; this surface owns only geometry and controls. */
import { Fragment, createElement as h, useCallback, useEffect, useLayoutEffect, useState, useSyncExternalStore } from "react";
import type { CSSProperties, ReactNode } from "react";
import { createPortal } from "react-dom";
import { icon } from "../screens/icons.ts";

export type Lesson = {
  id: string; title: string; description: string; recommended: boolean;
  completed: boolean; checkpoint: number; step_count: number;
};
export type TutorialBeat = {
  id: string; title: string; body: string; mode: "explain" | "action" | "finish";
  screen: string | null; entry_screen?: string | null; target: string | null;
  placement: "top" | "right" | "bottom" | "left" | "center"; can_next: boolean;
  primary?: GuideAction;
  guidance?: Record<string, { body: string; target: string | null; primary?: GuideAction }>;
};
type GuideAction = { action: "prepare_examples" | "navigate"; label: string; screen?: string };
export type TutorialSnapshot = {
  kind: "tutorial-lessons/v1";
  invitation: { visible: boolean; title: string; body: string };
  active: boolean; paused: boolean; scenario_id: string | null; checkpoint: number;
  practice?: { active: boolean; return_screen: string | null };
  scenarios: readonly Lesson[];
  stages?: readonly { id: string; title: string; status: "done" | "current" | "pending" }[];
  beat: TutorialBeat | null;
  show_result?: boolean;
  result?: null | { title: string; body: string; count: number; screen: string; target: string; documents: readonly { name: string; path: string; kind: string }[]; actions: readonly { label: string; target: string }[]; next_scenario_id?: string; next_scenario_label?: string };
  recovery: { title: string; body: string } | null;
  resources: { ready: boolean; summary: string; files?: readonly { name: string; path: string; kind: string }[] };
  copy: {
    start: string; later: string; pause: string; resume: string; skip: string;
    restart: string; next: string; prepare: string; cleanup: string; reset: string;
    open_tutorial: string; close: string; choose_scenario: string; reset_confirm: string; cleanup_confirm: string;
    practice: string; exit: string; return: string;
  };
};
export type TutorialPorts = {
  model: { getSnapshot(): unknown; subscribe(listener: () => void): () => void };
  loadInitial(): Promise<unknown>;
  dispatch(action: string, payload?: Record<string, unknown>): Promise<unknown>;
  nav: { subscribe(listener: () => void): () => void; currentScreen(): string | null; go(screen: string): void };
  overlay: { subscribe(listener: () => void): () => void; isBusy(): boolean; currentHost?(): Element | null };
  confirm(options: { title: string; body: string; confirmLabel: string; cancelLabel: string; danger: boolean }): Promise<boolean>;
  alarm(message: string): void;
  doc: Document;
  portal?: (children: ReactNode, container: Element) => ReactNode;
};

const ANCHORS: Readonly<Record<string, string>> = Object.freeze({
  "new-job": "#jobCandNewWork, #libraryNewWork, #jobPickInLibrary",
  "template-list": "#editorTplList",
  "data-picker": "#jobBtnPickData, #editorPoolBrowse, #dataPickerBrowse",
  mapping: "#editorPairZone, #wbMapPanel",
  "filename-pattern": "#editor-body input[data-act='pattern']",
  "save-job": "#editor-foot button[data-act='save']",
  "job-list": "#jobBrowseRows, #jobBrowseOpen, #jobCandidates, #libraryList",
  "library-jobs": "#libraryDetail [data-use], #libraryList",
  "edit-job": "#libraryDetail [data-edit], #libraryList",
  "open-workbench": "#jobGenBtn",
  "row-filter": "#jobTableHead .fico[data-col='메모']",
  "row-selection": "#jobSelAll, #jobTableBody",
  "content-options": "#jobContentSelectionZone",
  generate: "#jobManagedCreate, #jobGenBtn",
  results: "#jobResult",
  "txt-review": "#wbCard",
  "txt-copy": "#wbCopy",
  "prepare-examples": "#tutorialPrepare",
  "authoring-canvas": "#authoring-canvas, #authoring-outline-title",
  "authoring-open": "#authoring-menu[aria-label='파일'] [role='menuitem']:first-child, .authoring-empty-actions button:first-child, .authoring-head button[aria-haspopup='menu']",
  trial: ".authoring-dock.trial #authoring-dock-panel, .authoring-toolbar-end button[aria-pressed]",
  "save-template": "[data-guide='save-template']",
  "apply-change": "[data-guide='apply-change'], #authoring-dock-tab-impact",
});

export function anchorSelector(key: string | null): string | null {
  return key ? ANCHORS[key] ?? null : null;
}

function visibleElement(doc: ParentNode, selector: string | null): HTMLElement | null {
  if (!selector) return null;
  for (const preferred of selector.split(",")) {
    for (const candidate of doc.querySelectorAll<HTMLElement>(preferred.trim())) {
      const rect = candidate.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0 && !candidate.closest("[hidden], [inert], .hidden")) return candidate;
    }
  }
  return null;
}

const noHost = () => null;

/** Finale result action. On another screen the card is dismissed only after navigation succeeds — a cancelled leave
 *  guard or a failed dispatch keeps the result summary on screen. On the result's own screen it reveals the target. */
export async function runResultAction(resultScreen: string, screen: string | null,
  steps: { navigate(): Promise<boolean>; reveal(): void; dismiss(): void }): Promise<void> {
  if (resultScreen !== screen) {
    if (await steps.navigate()) steps.dismiss();
    return;
  }
  steps.dismiss();
  steps.reveal();
}

export function lessonAction(item: Lesson, snapshot: TutorialSnapshot): string {
  if (item.completed) return "restart";
  return item.id === snapshot.scenario_id && snapshot.paused ? "resume" : "select";
}

/** The one lesson the open panel features: the current lesson while it is in progress (a re-run of a completed
 *  lesson included), else the next unfinished one to start. */
export function featuredLesson(snapshot: TutorialSnapshot): Lesson | null {
  const current = snapshot.scenarios.find((item) => item.id === snapshot.scenario_id);
  if (current && (snapshot.active || snapshot.paused)) return current;
  const open = snapshot.scenarios.filter((item) => !item.completed);
  return open.find((item) => item.id === snapshot.scenario_id)
    ?? open.find((item) => item.recommended) ?? open[0] ?? null;
}

/** Featured primary: a running current lesson continues behind the panel ("close"), a paused current lesson resumes
 *  even when it was completed before; any other lesson follows the row action. */
export function featuredAction(item: Lesson, snapshot: TutorialSnapshot): string {
  if (item.id === snapshot.scenario_id && snapshot.active) return "close";
  if (item.id === snapshot.scenario_id && snapshot.paused) return "resume";
  return lessonAction(item, snapshot);
}

type Geometry = { x: number; y: number; width: number; height: number; side: TutorialBeat["placement"] };
export function placeCoach(target: DOMRect, viewport: { width: number; height: number }, preferred: TutorialBeat["placement"], coachHeight = 162): Geometry {
  const gap = 18, pad = 12, coachW = Math.min(320, viewport.width - 2 * pad), coachH = coachHeight;
  const space = { top: target.top, bottom: viewport.height - target.bottom, left: target.left, right: viewport.width - target.right };
  const fit = (side: Exclude<TutorialBeat["placement"], "center">) => space[side] >= (side === "top" || side === "bottom" ? coachH : coachW) + gap;
  let side = preferred;
  if (side !== "center" && !fit(side)) {
    const ordered: Array<Exclude<TutorialBeat["placement"], "center">> = ["bottom", "top", "right", "left"];
    ordered.sort((a, b) => space[b] - space[a]);
    side = ordered[0];
  }
  const centerX = target.left + target.width / 2;
  const centerY = target.top + target.height / 2;
  const rawX = side === "right" ? target.right + gap : side === "left" ? target.left - coachW - gap : centerX - coachW / 2;
  const rawY = side === "bottom" ? target.bottom + gap : side === "top" ? target.top - coachH - gap : centerY - coachH / 2;
  return {
    x: Math.max(pad, Math.min(rawX, viewport.width - coachW - pad)),
    y: Math.max(pad, Math.min(rawY, viewport.height - coachH - pad)),
    width: coachW, height: coachH, side,
  };
}

function readSnapshot(value: unknown): TutorialSnapshot | null {
  if (!value || typeof value !== "object" || (value as { kind?: unknown }).kind !== "tutorial-lessons/v1") return null;
  return value as TutorialSnapshot;
}

function Ring(props: { fraction: number }): ReactNode {
  const offset = 63 * (1 - props.fraction);
  return h("svg", { className: "tutorial-ring", viewBox: "0 0 24 24", "aria-hidden": true },
    h("circle", { className: "tutorial-ring-bg", cx: 12, cy: 12, r: 10 }),
    h("circle", { className: "tutorial-ring-fg", cx: 12, cy: 12, r: 10, strokeDasharray: 63, strokeDashoffset: offset }));
}

type LessonControls = {
  snapshot: TutorialSnapshot; pending: boolean; practice: boolean;
  run(item: Lesson, action: string): void; close(): void;
  act(action: "pause" | "skip" | "prepare_examples"): void; confirm(action: "reset_progress" | "cleanup"): void;
};

/** Open panel body. One featured lesson owns the only primary action; other lessons are quiet whole-row choices,
 *  practice copies sit behind one disclosure, and maintenance stays a quiet text row at the bottom. */
export function TutorialLessons(props: LessonControls): ReactNode {
  const { snapshot, pending, practice } = props;
  const count = snapshot.scenarios.filter((item) => item.completed).length;
  const featured = featuredLesson(snapshot);
  const current = !!featured && featured.id === snapshot.scenario_id;
  const running = current && snapshot.active;
  const started = !!featured && (featured.checkpoint > 0 || current && (snapshot.active || snapshot.paused));
  const primary = featured ? featuredAction(featured, snapshot) : null;
  const quiet = (label: string, onClick: () => void, extra?: Record<string, unknown>) =>
    h("button", { className: "btn quiet sm", type: "button", disabled: pending, onClick, ...extra }, label);

  const featuredBlock = featured ? h("section", { className: "tutorial-featured", "aria-labelledby": "tutorialFeaturedTitle" },
    h("header", { className: "tutorial-featured-head" },
      h("h3", { id: "tutorialFeaturedTitle" }, featured.title),
      started ? h("span", { className: "tutorial-progress" }, `${featured.checkpoint}/${featured.step_count}`) : null),
    featured.description ? h("p", null, featured.description) : null,
    h("div", { className: "tutorial-featured-actions" },
      // A running lesson continues behind the panel: closing returns to it without a host transition.
      h("button", { id: "tutorialContinue", className: "btn primary sm", type: "button", disabled: pending,
        onClick: () => primary === "close" ? props.close() : props.run(featured, primary!) },
        primary === "restart" ? snapshot.copy.restart : started ? snapshot.copy.resume : snapshot.copy.start),
      started && featured.checkpoint > 0 && primary !== "restart" ? quiet(snapshot.copy.restart, () => props.run(featured, "restart")) : null,
      running ? quiet(snapshot.copy.pause, () => props.act("pause")) : null,
      running ? quiet(snapshot.copy.skip, () => props.act("skip")) : null)) : null;

  const rows = snapshot.scenarios.filter((item) => item.id !== featured?.id).map((item) => h("li", { key: item.id, className: item.completed ? "done" : undefined },
    h("button", { type: "button", className: "tutorial-row", disabled: pending,
      "aria-label": item.completed ? undefined : `${item.title}, ${snapshot.copy.choose_scenario}`,
      onClick: () => props.run(item, lessonAction(item, snapshot)) },
      h("span", { className: "tutorial-check", "aria-hidden": true }, item.completed ? icon("check") : null),
      h("span", { className: "tutorial-row-title" }, item.title),
      !item.completed && item.checkpoint > 0 ? h("span", { className: "tutorial-progress" }, `${item.checkpoint}/${item.step_count}`) : null,
      item.completed ? h("span", { className: "tutorial-row-action" }, snapshot.copy.restart)
        : h("span", { className: "tutorial-row-go", "aria-hidden": true }, icon("chevron-right")))));

  const files = snapshot.resources.files ?? [];
  const fileList = files.length ? h("ul", { className: "tutorial-files" }, ...files.map((file) => h("li", { key: file.path, title: file.path },
    h("span", { className: "tutorial-file-name" }, file.name), h("span", { className: "tutorial-file-path" }, file.path)))) : null;
  const summary = snapshot.resources.summary;
  const recovery = snapshot.recovery?.body && snapshot.recovery.body !== summary ? snapshot.recovery.body : null;

  return h(Fragment, null,
    h("header", null, h("h2", null, "튜토리얼"), h("span", null, `${count}/${snapshot.scenarios.length}`)),
    featuredBlock,
    rows.length ? h("ol", { className: "tutorial-list" }, ...rows) : null,
    recovery || summary || fileList ? h("div", { className: "tutorial-resource" },
      recovery ? h("p", { className: "tutorial-recovery" }, recovery) : null,
      // Practice copies stay one disclosure away; the summary alone carries readiness.
      fileList && summary ? h("details", { className: "tutorial-disclosure" },
        h("summary", null, h("span", { className: "tutorial-disclosure-mark", "aria-hidden": true }, icon("chevron-right")), summary), fileList)
        : summary ? h("p", null, summary) : fileList) : null,
    h("div", { className: "tutorial-maintenance" },
      quiet(snapshot.copy.prepare, () => props.act("prepare_examples"), { id: "tutorialPrepare" }),
      !practice ? quiet(snapshot.copy.cleanup, () => props.confirm("cleanup"), { className: "btn quiet sm tutorial-destructive" }) : null,
      !practice ? quiet(snapshot.copy.reset, () => props.confirm("reset_progress"), { className: "btn quiet sm tutorial-destructive" }) : null));
}

export function TutorialPanel(ports: TutorialPorts): ReactNode {
  const raw = useSyncExternalStore(ports.model.subscribe, ports.model.getSnapshot, ports.model.getSnapshot);
  const snapshot = readSnapshot(raw);
  const screen = useSyncExternalStore(ports.nav.subscribe, ports.nav.currentScreen, ports.nav.currentScreen);
  const overlayBusy = useSyncExternalStore(ports.overlay.subscribe, ports.overlay.isBusy, ports.overlay.isBusy);
  const overlayHost = useSyncExternalStore(ports.overlay.subscribe, ports.overlay.currentHost ?? noHost, ports.overlay.currentHost ?? noHost);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [coachHeight, setCoachHeight] = useState(162);
  const [resultHeight, setResultHeight] = useState(330);
  const [resultDismissed, setResultDismissed] = useState(false);

  useEffect(() => { void ports.loadInitial().catch((error) => ports.alarm(String(error))); }, [ports]);

  const act = useCallback(async (action: string, payload?: Record<string, unknown>) => {
    if (pending) return false;
    setPending(true);
    try {
      const result = await ports.dispatch(action, payload) as { cancelled?: boolean } | null;
      if (action === "exit" && result?.cancelled !== true) setOpen(false);
      return result?.cancelled !== true;
    }
    catch (error) { ports.alarm(String(error)); return false; }
    finally { setPending(false); }
  }, [pending, ports]);

  const baseBeat = snapshot?.active && !snapshot.paused ? snapshot.beat : null;
  const guidance = screen ? baseBeat?.guidance?.[screen] : undefined;
  const beat = baseBeat && guidance ? { ...baseBeat, ...guidance, screen } : baseBeat;
  const practice = snapshot?.practice?.active === true;
  // Put help in the existing focus boundary; never create a second modal or intercept Escape.
  const dialogRelevant = !!overlayHost && !!beat && (
    !!overlayHost.querySelector(anchorSelector(beat.target) ?? "[data-tutorial-no-target]")
    || beat.target === "data-picker" && overlayHost.matches("#dataPickerModal, #poolRegModal, #sheetModal")
    || ["row-filter", "row-selection"].includes(beat.target ?? "") && overlayHost.matches("#dataSheet")
    || beat.target === "job-list" && overlayHost.matches("#jobBrowseSheet"));
  const dialogHost = dialogRelevant ? overlayHost!.querySelector(".modal-card, .sheet-card, [role='dialog']") ?? overlayHost : null;
  const canGuide = !overlayBusy || !!dialogHost;
  const result = snapshot?.show_result && !snapshot.active && !overlayBusy ? snapshot.result : null;
  useEffect(() => setResultDismissed(false), [result?.title]);
  const target = beat && (beat.screen === null || beat.screen === screen) && canGuide ? beat.target
    : result && result.screen === screen ? result.target : null;
  useLayoutEffect(() => {
    if (!target) { setRect(null); return; }
    let frame = 0;
    const measure = () => {
      const element = visibleElement(dialogHost ?? ports.doc, anchorSelector(target));
      const next = element?.getBoundingClientRect() ?? null;
      const shown = next && next.right > 0 && next.bottom > 0 && next.left < window.innerWidth && next.top < window.innerHeight ? next : null;
      setRect((before) => before?.x === shown?.x && before?.y === shown?.y && before?.width === shown?.width && before?.height === shown?.height ? before : shown);
    };
    const update = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(measure); };
    measure();
    const observer = new MutationObserver((mutations) => {
      if (mutations.some((change) => !(change.target as Element).closest?.("#tutorialPanelRoot, #tutorialCoach"))) update();
    });
    observer.observe(ports.doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "class", "style", "inert"] });
    ports.doc.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      cancelAnimationFrame(frame); observer.disconnect();
      ports.doc.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [target, ports.doc, screen, open, dialogHost]);

  useLayoutEffect(() => {
    const coach = ports.doc.getElementById("tutorialCoach");
    if (!coach) return;
    const observer = new ResizeObserver(() => setCoachHeight(coach.getBoundingClientRect().height));
    observer.observe(coach);
    return () => observer.disconnect();
  }, [beat?.id, rect, ports.doc]);

  useLayoutEffect(() => {
    const card = ports.doc.getElementById("tutorialFinale");
    if (!card) return;
    const observer = new ResizeObserver(() => setResultHeight(card.getBoundingClientRect().height));
    observer.observe(card);
    return () => observer.disconnect();
  }, [result?.title, rect, ports.doc]);

  const selected = snapshot?.scenarios.find((item) => item.id === snapshot.scenario_id);
  const nextLesson = snapshot?.scenarios.find((item) => item.id === result?.next_scenario_id);
  const stages = snapshot?.stages ?? [];
  const stageDone = stages.filter((stage) => stage.status === "done").length;
  const fraction = stages.length ? stageDone / stages.length : selected?.step_count ? selected.checkpoint / selected.step_count : 0;
  const shown = Boolean(beat && canGuide);
  const resultShown = Boolean(result && !resultDismissed);
  const position = rect && beat ? placeCoach(rect, { width: window.innerWidth, height: window.innerHeight }, beat.placement, coachHeight) : null;
  const resultPosition = rect && result ? placeCoach(rect, { width: window.innerWidth, height: window.innerHeight }, "right", resultHeight) : null;
  const spotStyle: CSSProperties | undefined = rect ? {
    left: Math.max(0, rect.left - 6), top: Math.max(0, rect.top - 6),
    width: rect.width + 12, height: rect.height + 12,
  } : undefined;
  const coachStyle: CSSProperties | undefined = position ? { left: position.x, top: position.y, width: position.width } : undefined;

  const recover = async () => {
    const element = visibleElement(dialogHost ?? ports.doc, anchorSelector(beat?.target ?? null));
    if (element) {
      element.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
      element.focus({ preventScroll: true });
    } else if (beat?.screen === null || beat?.screen === screen || beat?.entry_screen === screen) setOpen(true);
    else if (beat) await act("return_to_step", { screen: beat.entry_screen ?? beat.screen });
  };
  const runLesson = async (item: Lesson, action: string) => {
    if (await act(action, action === "resume" ? {} : { scenario_id: item.id })) setOpen(false);
  };
  const chooseLesson = async (item: Lesson) => {
    if (snapshot) await runLesson(item, lessonAction(item, snapshot));
  };

  const confirmAction = async (action: "reset_progress" | "cleanup") => {
    if (!snapshot) return;
    if (action === "cleanup") {
      try {
        const preview = await ports.dispatch("cleanup_preview", {}) as { token: string; rows: readonly { name: string; path: string; delete: boolean; reason: string }[]; delete_count: number };
        const details = preview.rows.map((entry) => `${entry.delete ? "삭제" : "보존"} · ${entry.name} — ${entry.path}\n${entry.reason}`).join("\n\n");
        const ok = await ports.confirm({ title: snapshot.copy.cleanup, body: `${snapshot.copy.cleanup_confirm}\n\n${details}`, confirmLabel: snapshot.copy.cleanup, cancelLabel: snapshot.copy.close, danger: true });
        if (ok) await act("cleanup", { token: preview.token });
      } catch (error) { ports.alarm(String(error)); }
      return;
    }
    const ok = await ports.confirm({ title: snapshot.copy.reset, body: snapshot.copy.reset_confirm,
      confirmLabel: snapshot.copy.reset, cancelLabel: snapshot.copy.close, danger: true });
    if (ok) await act(action, { confirm: true });
  };

  const entry = ports.doc.getElementById("tutorialEntrySlot");
  if (!entry) return null;
  const label = snapshot?.copy.open_tutorial ?? "튜토리얼";
  const exitButton = (id?: string) => practice ? h("button", { id, className: "btn sm tutorial-exit", type: "button", disabled: pending,
    onClick: () => void act("exit") }, snapshot!.copy.exit) : null;
  const hud = h("div", { className: "tutorial-hud" },
    h("button", { id: "tutorialOpen", className: "tutorial-hud-pill", type: "button", "aria-label": label,
      "aria-expanded": open, "aria-controls": "tutorialPanel", onClick: () => setOpen(!open) },
      h(Ring, { fraction: practice ? fraction : 0 }), h("span", { className: "tutorial-hud-label" }, practice ? snapshot!.copy.practice : "튜토리얼"),
      practice ? h("span", { className: "tutorial-hud-dots", "aria-hidden": true }, ...stages.map((stage) => h("i", {
        key: stage.id, className: stage.status, title: stage.title,
      }))) : null, practice && snapshot?.paused ? h("span", { className: "tutorial-paused" }, snapshot.copy.pause) : null), exitButton("tutorialExit"));

  const coach = shown && beat ? h("section", { id: "tutorialCoach", className: `tutorial-coach${dialogHost ? " tutorial-coach-inline" : ""}`,
    style: dialogHost ? undefined : coachStyle, role: "region", "aria-labelledby": "tutorialBeatTitle", "aria-describedby": "tutorialBeatBody",
    "data-side": dialogHost ? "inline" : position?.side ?? "center" },
    h("header", { className: "tutorial-coach-heading" }, h("h2", { id: "tutorialBeatTitle" }, beat.title),
      h("span", { className: "tutorial-step" }, selected ? `${Math.min(snapshot!.checkpoint + 1, selected.step_count)} / ${selected.step_count}` : "")),
    h("p", { id: "tutorialBeatBody", "aria-live": "polite" }, beat.body),
    h("div", { className: "tutorial-coach-foot" },
      beat.primary && !overlayBusy ? h("button", { id: "tutorialPrimary", className: "btn primary sm", type: "button", disabled: pending,
        onClick: () => void act(beat.primary!.action, beat.primary!.screen ? { screen: beat.primary!.screen } : {}) }, beat.primary.label) : null,
      !beat.primary && !rect && beat.target && !overlayBusy ? h("button", { id: "tutorialReturn", className: "btn primary sm", type: "button", disabled: pending,
        onClick: () => void recover() }, snapshot!.copy.return) : null,
      beat.mode === "explain" && beat.can_next ? h("button", { className: "btn primary sm", type: "button", disabled: pending,
        onClick: () => void act("next") }, snapshot!.copy.next) : null,
      dialogHost ? exitButton("tutorialDialogExit") : null)) : null;

  return h("div", { id: "tutorialPanelRoot", className: "tutorial-root", "data-screen": screen ?? "", "data-practice": practice },
    (ports.portal ?? createPortal)(hud, entry),
    open && snapshot && !snapshot.invitation.visible && !overlayBusy ? h("section", { id: "tutorialPanel", className: "tutorial-panel", "aria-label": "튜토리얼",
      onKeyDown: (event: { key: string; nativeEvent: { isComposing?: boolean }; stopPropagation(): void }) => {
        if (event.key === "Escape" && !event.nativeEvent.isComposing) { event.stopPropagation(); setOpen(false); ports.doc.getElementById("tutorialOpen")?.focus(); }
      } },
      h(TutorialLessons, { snapshot, pending, practice,
        run: (item, action) => void runLesson(item, action),
        close: () => { setOpen(false); ports.doc.getElementById("tutorialOpen")?.focus(); },
        act: (action) => void act(action), confirm: (action) => void confirmAction(action) })) : null,
    snapshot?.invitation.visible && !overlayBusy ? h("section", { className: "tutorial-invite", role: "region", "aria-labelledby": "tutorialInviteTitle" },
      h("h2", { id: "tutorialInviteTitle" }, snapshot.invitation.title), h("p", null, snapshot.invitation.body),
      h("div", { className: "tutorial-actions" },
        h("button", { type: "button", className: "btn", disabled: pending, onClick: () => void act("later") }, snapshot.copy.later),
        h("button", { type: "button", className: "btn primary", disabled: pending,
          onClick: () => void act("start", { scenario_id: snapshot.scenarios.find((item) => item.recommended)?.id ?? "first_hwpx" }) }, snapshot.copy.start))) : null,
    practice && snapshot?.paused && !overlayBusy ? h("section", { className: "tutorial-paused-card", role: "region", "aria-label": snapshot.copy.pause },
      h("p", null, snapshot.recovery?.body ?? selected?.title),
      h("button", { id: "tutorialResume", className: "btn primary sm", type: "button", disabled: pending,
        onClick: () => void act("resume") }, snapshot.copy.resume)) : null,
    resultShown && result ? h("section", { id: "tutorialFinale", className: "tutorial-finale", role: "region", "aria-label": result.title,
      style: resultPosition ? { left: resultPosition.x, top: resultPosition.y } : undefined },
      h("div", { className: "tutorial-fin-fan", "aria-hidden": true }, ...result.documents.slice(0, 3).map((document, index) =>
        h("div", { key: document.path, className: `tutorial-fin-doc tutorial-fin-doc-${index}` },
          h("span", { className: "tutorial-fin-lines" }), h("span", null, document.kind)))),
      h("div", { className: "tutorial-fin-count" }, h("strong", null, String(result.count)), h("span", null, result.documents.length ? "문서" : "완료")),
      h("h2", null, result.title), h("p", null, result.body),
      result.documents.length ? h("ul", { className: "tutorial-fin-files" }, ...result.documents.map((document) => h("li", { key: document.path, title: document.path }, document.name))) : null,
      h("div", { className: "tutorial-actions" }, ...result.actions.map((action) => h("button", { key: action.target,
        type: "button", className: "btn sm", onClick: () => void runResultAction(result.screen, screen, {
          navigate: () => act("navigate", { screen: result.screen }),
          reveal: () => {
            const element = visibleElement(ports.doc, anchorSelector(action.target));
            element?.scrollIntoView({ block: "center", behavior: "instant" });
            element?.focus({ preventScroll: true });
          },
          dismiss: () => setResultDismissed(true),
        }) }, action.label)), nextLesson ? h("button", { id: "tutorialNextCourse", type: "button", className: "btn primary sm", disabled: pending,
          onClick: () => void chooseLesson(nextLesson) }, result.next_scenario_label ?? nextLesson.title) : null,
        h("button", { type: "button", className: nextLesson ? "btn sm" : "btn primary sm", onClick: () => { setResultDismissed(true); setOpen(true); } }, snapshot!.copy.choose_scenario),
        exitButton())) : null,
    dialogHost && coach ? (ports.portal ?? createPortal)(coach, dialogHost)
      : coach ? h("div", { className: "tutorial-guide", "data-mode": beat!.mode },
        rect ? h("div", { className: "tutorial-spot", style: spotStyle, "aria-hidden": true }) : null, coach) : null);
}
