/* Eight task lessons. The host owns lesson state; this surface owns only geometry and controls. */
import { Fragment, createElement as h, useCallback, useEffect, useLayoutEffect, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { icon } from "../screens/icons.ts";
import { GLIDE_WINDOW, measureTarget, parity, placeCoach, sameTarget, spotFrame, visibleElement, watchLayout, watchMissedPress } from "./spotlight.ts";
import type { CoachPlacement, SpotFrame, Target } from "./spotlight.ts";

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

const viewportOf = (doc: Document) => {
  const view = doc.defaultView ?? window;
  return { width: view.innerWidth, height: view.innerHeight };
};

/** Height of the element with `id`, followed while it resizes; `fallback` until measured. `deps` name what recreates it. */
function useElementHeight(doc: Document, id: string, fallback: number, deps: readonly unknown[]): number {
  const [height, setHeight] = useState(fallback);
  useLayoutEffect(() => {
    const element = doc.getElementById(id);
    if (!element) return undefined;
    const observer = new ResizeObserver(() => setHeight(element.getBoundingClientRect().height));
    observer.observe(element);
    return () => observer.disconnect();
  }, [doc, id, ...deps]);
  return height;
}

/** Counts changes of `value`; `at` stamps the latest change so a glide is told apart from a plain re-measure. */
function useChangeCount(value: string): { count: number; at: number } {
  const [seen, setSeen] = useState({ value, count: 0, at: 0 });
  if (seen.value === value) return seen;
  const next = { value, count: seen.count + 1, at: Date.now() };
  setSeen(next);
  return next;
}

/** Presses that miss the ring, counted per beat (a new beat starts from zero). Observed, never intercepted. */
function useMissedPresses(doc: Document, frame: SpotFrame | null, key: string): number {
  const [missed, setMissed] = useState({ key, count: 0 });
  const box = frame ? `${frame.x},${frame.y},${frame.width},${frame.height}` : "";
  useEffect(() => {
    if (!frame) return undefined;
    return watchMissedPress(doc, frame, () => setMissed((before) => ({ key, count: before.key === key ? before.count + 1 : 1 })));
  }, [doc, box, key]);
  return missed.key === key ? missed.count : 0;
}

type SpotProps = { target: Target; motionKey: string; missed: number; ring: boolean };

/** Snug ring around the real control with the page dimmed around it. It glides between anchors, pulses once on
 *  arrival or on a missed press, and never takes pointer events. `ring` drops the scrim where a dialog already dims. */
export function TutorialSpot(props: SpotProps): ReactNode {
  const change = useChangeCount(props.motionKey);
  const frame = spotFrame(props.target);
  const gliding = change.count > 0 && Date.now() - change.at < GLIDE_WINDOW;
  const afterGlide = change.count > 0 && props.missed === 0;
  return h("div", { className: "tutorial-spot", "aria-hidden": true, "data-dim": props.ring ? "ring" : "scrim",
    "data-glide": gliding ? "" : undefined, "data-swap": parity(change.count),
    style: { transform: `translate(${frame.x}px, ${frame.y}px)`, width: frame.width, height: frame.height, borderRadius: frame.radius } },
  h("i", { key: `${props.motionKey}:${props.missed}`, className: "tutorial-spot-pulse",
    style: afterGlide ? { animationDelay: "var(--tutorial-glide)" } : undefined }));
}

type CoachProps = {
  beat: TutorialBeat; copy: TutorialSnapshot["copy"]; step: string; placement: CoachPlacement | null; inline: boolean;
  lost: boolean; overlayBusy: boolean; pending: boolean; swap: number; missed: number; exit: ReactNode;
  act(action: string, payload?: Record<string, unknown>): void; recover(): void;
};

const primaryPayload = (primary: GuideAction) => primary.screen ? { screen: primary.screen } : {};

function CoachFoot(props: CoachProps): ReactNode {
  const { beat, copy, pending } = props;
  const button = (id: string | undefined, label: string, onClick: () => void) =>
    h("button", { id, className: "btn primary sm", type: "button", disabled: pending, onClick }, label);
  const guide = beat.primary && !props.overlayBusy ? beat.primary : null;
  return h("div", { className: "tutorial-coach-foot" },
    guide ? button("tutorialPrimary", guide.label, () => props.act(guide.action, primaryPayload(guide))) : null,
    !beat.primary && props.lost && !props.overlayBusy ? button("tutorialReturn", copy.return, props.recover) : null,
    beat.mode === "explain" && beat.can_next ? button(undefined, copy.next, () => props.act("next")) : null,
    props.inline ? props.exit : null);
}

/** Coach card. Its arrow points at the anchor from the chosen side; it fades in on each beat (`swap`) and shakes
 *  on a missed press (`missed`). Inside a dialog it is an inline section of that dialog instead. */
export function TutorialCoach(props: CoachProps): ReactNode {
  const { beat, placement, inline } = props;
  const style = !inline && placement ? { left: placement.x, top: placement.y, width: placement.width } : undefined;
  return h("section", { id: "tutorialCoach", className: inline ? "tutorial-coach tutorial-coach-inline" : "tutorial-coach", style,
    role: "region", "aria-labelledby": "tutorialBeatTitle", "aria-describedby": "tutorialBeatBody",
    "data-side": inline ? "inline" : placement?.side ?? "center", "data-swap": parity(props.swap),
    "data-nudge": props.missed ? parity(props.missed) : undefined },
  placement?.arrow ? h("i", { className: "tutorial-coach-arrow", style: placement.arrow, "aria-hidden": true }) : null,
  h("div", { className: "tutorial-coach-scroll" },
    h("header", { className: "tutorial-coach-heading" }, h("h2", { id: "tutorialBeatTitle" }, beat.title),
      h("span", { className: "tutorial-step" }, props.step)),
    h("p", { id: "tutorialBeatBody", "aria-live": "polite" }, beat.body),
    h(CoachFoot, props)));
}

type GuideProps = Omit<CoachProps, "placement" | "inline" | "lost" | "swap" | "missed"> & {
  found: Target | null; dialogHost: Element | null; doc: Document;
  portal: (children: ReactNode, container: Element) => ReactNode;
};

/** Spotlight and coach for the live beat. In a relevant dialog both join that dialog's focus boundary and the ring
 *  keeps no scrim (the dialog already dims the page); elsewhere the scrim dims everything but the anchor. */
function TutorialGuide(props: GuideProps): ReactNode {
  const { beat, found, dialogHost, doc } = props;
  const swap = useChangeCount(beat.id).count;
  const coachHeight = useElementHeight(doc, "tutorialCoach", 162, [beat.id, found]);
  const frame = found ? spotFrame(found) : null;
  const missed = useMissedPresses(doc, beat.mode === "action" ? frame : null, beat.id);
  const placement = found && !dialogHost ? placeCoach(found.rect, viewportOf(doc), beat.placement, coachHeight) : null;
  const coach = h(TutorialCoach, { ...props, placement, inline: !!dialogHost, lost: !found && !!beat.target, swap, missed });
  const spot = found ? h(TutorialSpot, { target: found, motionKey: `${beat.id}|${beat.target}`, missed, ring: !!dialogHost }) : null;
  if (dialogHost) return props.portal(h(Fragment, null, coach, spot), dialogHost);
  return h("div", { className: "tutorial-guide", "data-mode": beat.mode }, spot, coach);
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
  const [found, setFound] = useState<Target | null>(null);
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
    if (!target) { setFound(null); return undefined; }
    const measure = () => {
      const next = measureTarget(dialogHost ?? ports.doc, anchorSelector(target), viewportOf(ports.doc));
      setFound((before) => sameTarget(before, next) ? before : next);
    };
    measure();
    return watchLayout(ports.doc, measure);
  }, [target, ports.doc, screen, open, dialogHost]);
  const resultHeight = useElementHeight(ports.doc, "tutorialFinale", 330, [result?.title, found]);

  const selected = snapshot?.scenarios.find((item) => item.id === snapshot.scenario_id);
  const nextLesson = snapshot?.scenarios.find((item) => item.id === result?.next_scenario_id);
  const stages = snapshot?.stages ?? [];
  const stageDone = stages.filter((stage) => stage.status === "done").length;
  const fraction = stages.length ? stageDone / stages.length : selected?.step_count ? selected.checkpoint / selected.step_count : 0;
  const shown = Boolean(beat && canGuide);
  const resultShown = Boolean(result && !resultDismissed);
  const resultPosition = found && result ? placeCoach(found.rect, viewportOf(ports.doc), "right", resultHeight) : null;

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
    shown && beat ? h(TutorialGuide, { beat, copy: snapshot!.copy, found, dialogHost, doc: ports.doc, portal: ports.portal ?? createPortal,
      step: selected ? `${Math.min(snapshot!.checkpoint + 1, selected.step_count)} / ${selected.step_count}` : "",
      overlayBusy, pending, exit: exitButton("tutorialDialogExit"),
      act: (action, payload) => void act(action, payload), recover: () => void recover() }) : null);
}
