/* Nine task lessons. The host owns lesson state; this surface owns only geometry and controls. */
import { Fragment, createElement as h, useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode, RefObject } from "react";
import { createPortal } from "react-dom";
import { icon } from "../screens/icons.ts";
import { anchorSelector } from "./anchors.ts";
import { FLY_SCALE, clockOf, countShown, createCoachSwap, createSpotHold, flyFrom, freshIds, playFinale, prefersReducedMotion } from "./motion.ts";
import type { FinaleState, HeldSpot } from "./motion.ts";
import { GLIDE_WINDOW, createRevealer, measureTarget, parity, scrollAnchor, placeCoach, sameTarget, spotFrame, visibleElement, watchLayout, watchMissedPress } from "./spotlight.ts";
import { beatReports, watchReport } from "./reports.ts";
import type { CoachPlacement, SpotFrame, Target } from "./spotlight.ts";
import { beatAnchor, coachHiddenProps, continueLabel, dialogHostFor, featuredLesson, featuredState, finalePosition, guideIdentity, guideTarget,
  hudVisible, lessonAction, lessonFraction, lessonsPanelOpen, liveBeat, noHost, readSnapshot, shownResult, spansLines, viewportOf } from "./panel_state.ts";
export { featuredAction, featuredLesson, hudVisible, lessonAction } from "./panel_state.ts";

export type Lesson = {
  id: string; title: string; description: string; recommended: boolean;
  completed: boolean; checkpoint: number; step_count: number;
};
/** One beat = one boxed control (`target` with its parameter `arg`) on one screen. `press` marks a beat whose
 *  control runs no product command: the surface reports the press and the host decides the beat (#1127). */
export type TutorialBeat = {
  id: string; title: string; body: string; mode: "explain" | "action" | "finish";
  screen: string | null; entry_screen?: string | null; target: string | null; arg?: string; press?: boolean;
  /** The boxed control lives in a transient menu: the surface reports it vanishing unpressed (#1149 review). */
  transient?: boolean;
  placement: "top" | "right" | "bottom" | "left" | "center"; can_next: boolean;
  /** Range beats (`authoring-range`): the text range the host resolved; the template editor paints it. */
  range?: { session_id: string; start: number; end: number } | null;
};
export type TutorialSnapshot = {
  kind: "tutorial-lessons/v1";
  invitation: { visible: boolean; title: string; body: string };
  /** 설정의 「튜토리얼 버튼 표시」 토글(#1147) — **최종값**(꺼져 있어도 연습 중이면 true).
   *  판정은 백엔드가 지고 이 면은 그대로 따른다(다시 판정하지 않는다). */
  entry?: { visible: boolean };
  active: boolean; paused: boolean; scenario_id: string | null; checkpoint: number;
  practice?: { active: boolean; return_screen: string | null };
  scenarios: readonly Lesson[];
  stages?: readonly { id: string; title: string; status: "done" | "current" | "pending" }[];
  beat: TutorialBeat | null;
  show_result?: boolean;
  result?: null | { title: string; body: string; count: number; screen: string; target: string; documents: readonly { name: string; path: string; kind: string }[]; next_scenario_id?: string };
  recovery: { title: string; body: string } | null;
  resources: { ready: boolean; summary: string; files?: readonly { name: string; path: string; kind: string }[] };
  copy: {
    start: string; later: string; pause: string; resume: string; skip: string;
    restart: string; next: string; next_lesson: string; cleanup: string; reset: string;
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

function Ring(props: { fraction: number }): ReactNode {
  const offset = 63 * (1 - props.fraction);
  return h("svg", { className: "tutorial-ring", viewBox: "0 0 24 24", "aria-hidden": true },
    h("circle", { className: "tutorial-ring-bg", cx: 12, cy: 12, r: 10 }),
    h("circle", { className: "tutorial-ring-fg", cx: 12, cy: 12, r: 10, strokeDasharray: 63, strokeDashoffset: offset }));
}

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

type SpotProps = { target: Target; motionKey: string; missed: number; ring: boolean; faded?: boolean };

/** Snug ring around the real control with the page dimmed around it. It glides between anchors, pulses once on
 *  arrival or on a missed press, and never takes pointer events. `ring` drops the scrim where a dialog already dims.
 *  `faded` keeps the last frame invisible in place while the anchor is missing, so the next one glides from it. */
export function TutorialSpot(props: SpotProps): ReactNode {
  const change = useChangeCount(props.motionKey);
  const frame = spotFrame(props.target);
  const gliding = change.count > 0 && Date.now() - change.at < GLIDE_WINDOW;
  const afterGlide = change.count > 0 && props.missed === 0;
  return h("div", { className: "tutorial-spot", "aria-hidden": true, "data-dim": props.ring ? "ring" : "scrim",
    "data-glide": gliding ? "" : undefined, "data-fade": props.faded ? "" : undefined, "data-swap": parity(change.count),
    style: { transform: `translate(${frame.x}px, ${frame.y}px)`, width: frame.width, height: frame.height, borderRadius: frame.radius } },
  h("i", { key: `${props.motionKey}:${props.missed}`, className: "tutorial-spot-pulse",
    style: afterGlide ? { animationDelay: "var(--tutorial-glide)" } : undefined }));
}

/** What the coach card shows: frozen on the old beat while it fades out (motion.ts createCoachSwap). */
type CoachView = { beat: TutorialBeat; step: string; placement: CoachPlacement | null; lost: boolean; missed: number };

type CoachProps = CoachView & {
  copy: TutorialSnapshot["copy"]; inline: boolean; overlayBusy: boolean; pending: boolean; exit: ReactNode;
  /** `hidden`: faded out between beats. `stale`: still the old beat's card, whose buttons must not act on the new beat. */
  hidden?: boolean; stale?: boolean;
  act(action: string, payload?: Record<string, unknown>): void; recover(): void;
};

function CoachFoot(props: CoachProps): ReactNode {
  const { beat, copy, pending } = props;
  const button = (id: string | undefined, label: string, onClick: () => void) =>
    h("button", { id, className: "btn primary sm", type: "button", disabled: pending, onClick: props.stale ? undefined : onClick }, label);
  return h("div", { className: "tutorial-coach-foot" },
    props.lost && (props.inline || !props.overlayBusy) ? button("tutorialReturn", copy.return, props.recover) : null,
    beat.mode === "explain" && beat.can_next ? button(undefined, copy.next, () => props.act("next")) : null,
    props.inline ? props.exit : null);
}

/** Coach card. Its arrow points at the anchor from the chosen side; between beats it fades out in place and fades
 *  in with the new words at the new place (`hidden`), and it shakes on a missed press (`missed`). Inside a dialog
 *  it is an inline section of that dialog instead. */
export function TutorialCoach(props: CoachProps): ReactNode {
  const { beat, placement, inline } = props;
  const style = !inline && placement ? { left: placement.x, top: placement.y, width: placement.width } : undefined;
  const hidden = coachHiddenProps(props.hidden);
  return h("section", { id: "tutorialCoach", className: inline ? "tutorial-coach tutorial-coach-inline" : "tutorial-coach", style,
    role: "region", "aria-labelledby": "tutorialBeatTitle", "aria-describedby": "tutorialBeatBody",
    "data-side": inline ? "inline" : placement?.side ?? "center", "data-shown": String(!props.hidden),
    ...hidden,
    // The boxed control's key: a control the product shows only on hover is revealed while it is the one boxed (CSS).
    "data-target": beat.target ?? undefined,
    "data-nudge": props.missed ? parity(props.missed) : undefined },
  placement?.arrow ? h("i", { className: "tutorial-coach-arrow", style: placement.arrow, "aria-hidden": true }) : null,
  h("div", { className: "tutorial-coach-scroll" },
    h("header", { className: "tutorial-coach-heading" }, h("h2", { id: "tutorialBeatTitle" }, beat.title),
      h("span", { className: "tutorial-step" }, props.step)),
    h("p", { id: "tutorialBeatBody", "aria-live": "polite" }, beat.body),
    h(CoachFoot, props)));
}

type GuideProps = Omit<CoachProps, keyof CoachView | "inline" | "hidden" | "stale"> & {
  beat: TutorialBeat; identity: string; step: string; found: Target | null; dialogHost: Element | null; doc: Document;
  portal: (children: ReactNode, container: Element) => ReactNode;
};

/** The ring's shown frame: it holds and then fades in place while the anchor is missing, and glides from there to
 *  the next anchor (motion.ts createSpotHold). The page and a dialog are separate places to glide in. */
function useHeldSpot(doc: Document, found: Target | null, key: string, zone: Element | null): HeldSpot<Target> {
  const [hold] = useState(() => createSpotHold<Target>(clockOf(doc), found, key));
  useLayoutEffect(() => hold.feed(found, key, prefersReducedMotion(doc), zone), [doc, hold, found, key, zone]);
  useEffect(() => hold.dispose, [hold]);
  return useSyncExternalStore(hold.subscribe, hold.get, hold.get);
}

/** The coach for the live beat, paced by createCoachSwap: the old beat's card stays as it was while it fades out,
 *  the new card shows once its anchor is found; a re-measure within one beat applies at once. */
function useCoachSwap(doc: Document, view: CoachView, found: Target | null, key: string): { view: CoachView; hidden: boolean; stale: boolean } {
  const anchored = !view.beat.target || !!found;
  const [swap] = useState(() => createCoachSwap(clockOf(doc), key, anchored));
  const state = useSyncExternalStore(swap.subscribe, swap.get, swap.get);
  const last = useRef(view);
  const current = state.key === key;
  useLayoutEffect(() => { if (current) last.current = view; });
  useLayoutEffect(() => swap.feed(key, anchored, prefersReducedMotion(doc)), [doc, swap, key, anchored]);
  useEffect(() => swap.dispose, [swap]);
  return { view: current ? view : { ...last.current, missed: 0 }, hidden: state.hidden, stale: !current };
}

/** Spotlight and coach for the live beat. In a relevant dialog both join that dialog's focus boundary and the ring
 *  keeps no scrim (the dialog already dims the page); elsewhere the scrim dims everything but the anchor. */
function TutorialGuide(props: GuideProps): ReactNode {
  const { beat, found, dialogHost, doc } = props;
  const coachHeight = useElementHeight(doc, "tutorialCoach", 162, [props.identity, found]);
  const frame = found ? spotFrame(found) : null;
  const missed = useMissedPresses(doc, beat.mode === "action" ? frame : null, props.identity);
  const placement = found && !dialogHost ? placeCoach(found.rect, viewportOf(doc), beat.placement, coachHeight) : null;
  const swap = useCoachSwap(doc, { beat, step: props.step, placement, lost: !found && !!beat.target, missed }, found, props.identity);
  const held = useHeldSpot(doc, found, `${props.identity}|${beat.target}|${beat.arg ?? ""}`, dialogHost);
  const coach = h(TutorialCoach, { ...props, ...swap.view, inline: !!dialogHost, hidden: swap.hidden, stale: swap.stale });
  const spot = held.target ? h(TutorialSpot, { target: held.target, motionKey: `${held.key}#${held.epoch}`, faded: held.faded, missed, ring: !!dialogHost }) : null;
  if (dialogHost) return props.portal(h(Fragment, null, coach, spot), dialogHost);
  return h("div", { className: "tutorial-guide", "data-mode": beat.mode }, spot, coach);
}

type LessonControls = {
  snapshot: TutorialSnapshot; pending: boolean; practice: boolean;
  /** Lessons completed since the panel last showed them: their check draws once. */
  fresh?: ReadonlySet<string>;
  run(item: Lesson, action: string): void; close(): void;
  act(action: "pause" | "skip"): void; confirm(action: "reset_progress" | "cleanup"): void;
};

function LessonCheck(props: { done: boolean; fresh: boolean }): ReactNode {
  return h("span", { className: "tutorial-check", "aria-hidden": true, "data-fresh": props.fresh ? "" : undefined },
    props.done ? icon("check") : null);
}

function featuredBlock(props: LessonControls, featured: Lesson | null,
  quiet: (label: string, onClick: () => void) => ReactNode): ReactNode {
  const { snapshot, pending } = props;
  const { running, started, primary } = featuredState(snapshot, featured);
  if (!featured) return null;
  return h("section", { className: "tutorial-featured", "aria-labelledby": "tutorialFeaturedTitle" },
    h("header", { className: "tutorial-featured-head" },
      h("h3", { id: "tutorialFeaturedTitle" }, featured.title),
      started ? h("span", { className: "tutorial-progress" }, `${featured.checkpoint}/${featured.step_count}`) : null),
    featured.description ? h("p", null, featured.description) : null,
    h("div", { className: "tutorial-featured-actions" },
      // A running lesson continues behind the panel: closing returns to it without a host transition.
      h("button", { id: "tutorialContinue", className: "btn primary sm", type: "button", disabled: pending,
        onClick: () => primary === "close" ? props.close() : props.run(featured, primary!) },
        continueLabel(primary, started, snapshot.copy)),
      started && featured.checkpoint > 0 && primary !== "restart" ? quiet(snapshot.copy.restart, () => props.run(featured, "restart")) : null,
      running ? quiet(snapshot.copy.pause, () => props.act("pause")) : null,
      running ? quiet(snapshot.copy.skip, () => props.act("skip")) : null));
}

function lessonRow(props: LessonControls, item: Lesson): ReactNode {
  const { snapshot } = props;
  return h("li", { key: item.id, className: item.completed ? "done" : undefined },
    h("button", { type: "button", className: "tutorial-row", disabled: props.pending,
      "aria-label": item.completed ? undefined : `${item.title}, ${snapshot.copy.choose_scenario}`,
      onClick: () => props.run(item, lessonAction(item, snapshot)) },
      h(LessonCheck, { done: item.completed, fresh: props.fresh?.has(item.id) === true }),
      h("span", { className: "tutorial-row-title" }, item.title),
      !item.completed && item.checkpoint > 0 ? h("span", { className: "tutorial-progress" }, `${item.checkpoint}/${item.step_count}`) : null,
      item.completed ? h("span", { className: "tutorial-row-action" }, snapshot.copy.restart)
        : h("span", { className: "tutorial-row-go", "aria-hidden": true }, icon("chevron-right"))));
}

function fileListOf(snapshot: TutorialSnapshot): ReactNode {
  const files = snapshot.resources.files ?? [];
  return files.length ? h("ul", { className: "tutorial-files" }, ...files.map((file) => h("li", { key: file.path, title: file.path },
    h("span", { className: "tutorial-file-name" }, file.name), h("span", { className: "tutorial-file-path" }, file.path)))) : null;
}

/** Practice copies stay one disclosure away; the summary alone carries readiness. */
function resourceBlock(snapshot: TutorialSnapshot): ReactNode {
  const fileList = fileListOf(snapshot);
  const summary = snapshot.resources.summary;
  const recovery = snapshot.recovery?.body && snapshot.recovery.body !== summary ? snapshot.recovery.body : null;
  return recovery || summary || fileList ? h("div", { className: "tutorial-resource" },
    recovery ? h("p", { className: "tutorial-recovery" }, recovery) : null,
    fileList && summary ? h("details", { className: "tutorial-disclosure" },
      h("summary", null, h("span", { className: "tutorial-disclosure-mark", "aria-hidden": true }, icon("chevron-right")), summary), fileList)
      : summary ? h("p", null, summary) : fileList) : null;
}

/** Open panel body. One featured lesson owns the only primary action; other lessons are quiet whole-row choices,
 *  practice copies sit behind one disclosure, and maintenance stays a quiet text row at the bottom. */
export function TutorialLessons(props: LessonControls): ReactNode {
  const { snapshot, pending, practice } = props;
  const count = snapshot.scenarios.filter((item) => item.completed).length;
  const featured = featuredLesson(snapshot);
  const quiet = (label: string, onClick: () => void, extra?: Record<string, unknown>) =>
    h("button", { className: "btn quiet sm", type: "button", disabled: pending, onClick, ...extra }, label);
  const featuredView = featuredBlock(props, featured, quiet);
  const rows = snapshot.scenarios.filter((item) => item.id !== featured?.id).map((item) => lessonRow(props, item));
  return h(Fragment, null,
    h("header", null, h("h2", null, "튜토리얼"), h("span", null, `${count}/${snapshot.scenarios.length}`)),
    featuredView,
    rows.length ? h("ol", { className: "tutorial-list" }, ...rows) : null,
    resourceBlock(snapshot),
    h("div", { className: "tutorial-maintenance" },
      !practice ? quiet(snapshot.copy.cleanup, () => props.confirm("cleanup"), { className: "btn quiet sm tutorial-destructive" }) : null,
      !practice ? quiet(snapshot.copy.reset, () => props.confirm("reset_progress"), { className: "btn quiet sm tutorial-destructive" }) : null));
}

/** Visible box of the current anchor inside `root` (a dialog) or the document. A changed anchor — a new beat key or
 *  a replaced element — is scrolled into view once; later re-measures only follow the layout and never scroll
 *  against the user. A box scrolled wholly out of sight measures null, which offers the existing way back. */
function useAnchorBox(doc: Document, root: Element | null, selector: string | null, key: string, span: boolean, deps: readonly unknown[]): Target | null {
  const [found, setFound] = useState<Target | null>(null);
  const [reveal] = useState(() => createRevealer(scrollAnchor));
  useLayoutEffect(() => {
    if (!selector) { setFound(null); return undefined; }
    const measure = () => {
      const next = measureTarget(root ?? doc, selector, viewportOf(doc), reveal(key), span);
      setFound((before) => sameTarget(before, next) ? before : next);
    };
    measure();
    return watchLayout(doc, measure);
  }, [doc, root, selector, key, reveal, span, ...deps]);
  return found;
}

/** Report the current beat's UI facts — a press that runs no product command, or its menu closing unpressed. A
 *  report carries only lesson, position and anchor; the host decides what it means (`reports.ts`). */
function usePressReport(ports: TutorialPorts, snapshot: TutorialSnapshot | null, screen: string | null, beatSelector: string | null): void {
  const reports = beatReports(snapshot, screen);
  const key = reports.map(([action, fact]) => fact && beatSelector ? `${action}|${fact.scenario_id}|${fact.checkpoint}|${beatSelector}` : "").join(",");
  useEffect(() => {
    if (!beatSelector) return undefined;
    const stops = reports.flatMap(([action, fact, watch]) => fact ? [watchReport(ports, beatSelector, action, fact, watch)] : []);
    return () => stops.forEach((stop) => stop());
  }, [ports, key]);
}

type FinaleProps = {
  result: NonNullable<TutorialSnapshot["result"]>; copy: TutorialSnapshot["copy"]; pending: boolean; doc: Document;
  position: CoachPlacement | null; next: (() => void) | null; exit: ReactNode; close(): void;
};

type Flight = FinaleState & { from: Record<string, string | number> };

/** Fan documents leave the result panel (the result anchor) small and land one by one; the count follows each
 *  landing (playFinale). The start is re-aimed whenever the card moves (`place`), so a card placed after its first
 *  frame still sends them from the panel. A first render already shows the end state, so nothing depends on the
 *  timers to tell the truth. */
function useFinaleFlight(doc: Document, fan: RefObject<HTMLDivElement | null>, origin: string | null, docs: number, key: string, place: string): Flight {
  const [flight, setFlight] = useState<FinaleState>({ arrived: docs, counted: docs });
  const [from, setFrom] = useState<Flight["from"]>({});
  useLayoutEffect(() => {
    const offset = flyFrom(visibleElement(doc, origin)?.getBoundingClientRect() ?? null, fan.current?.getBoundingClientRect() ?? null);
    setFrom({ opacity: 0, "--fly-x": `${offset.x}px`, "--fly-y": `${offset.y}px`, "--fly-s": FLY_SCALE });
  }, [doc, origin, key, place]);
  useLayoutEffect(() => {
    setFlight({ arrived: 0, counted: 0 });
    return playFinale(clockOf(doc), docs, prefersReducedMotion(doc), setFlight);
  }, [doc, docs, key]);
  return { ...flight, from };
}

/** Lesson-complete card. Two ways on (#1136): the next lesson (never named on the button) or leaving practice; the
 *  last lesson only leaves. Outside practice there is nothing to leave, so the card only closes. */
function TutorialFinale(props: FinaleProps): ReactNode {
  const { result, copy } = props;
  const fan = useRef<HTMLDivElement>(null);
  const documents = result.documents.slice(0, 3);
  const flight = useFinaleFlight(props.doc, fan, anchorSelector(result.target), documents.length, `${result.title}|${result.count}`,
    `${props.position?.x},${props.position?.y}`);
  return h("section", { id: "tutorialFinale", className: "tutorial-finale", role: "region", "aria-label": result.title,
    style: props.position ? { left: props.position.x, top: props.position.y } : undefined },
  h("div", { ref: fan, className: "tutorial-fin-fan", "aria-hidden": true }, ...documents.map((document, index) =>
    h("div", { key: document.path, className: `tutorial-fin-doc tutorial-fin-doc-${index}`,
      "data-arrived": index < flight.arrived ? "" : undefined, style: index < flight.arrived ? undefined : flight.from },
      h("span", { className: "tutorial-fin-lines" }), h("span", null, document.kind)))),
  h("div", { className: "tutorial-fin-count" }, h("strong", null, String(countShown(result.count, flight.counted, documents.length))),
    h("span", null, result.documents.length ? "문서" : "완료")),
  h("h2", null, result.title), h("p", null, result.body),
  result.documents.length ? h("ul", { className: "tutorial-fin-files" }, ...result.documents.map((document) => h("li", { key: document.path, title: document.path }, document.name))) : null,
  h("div", { className: "tutorial-actions" },
    props.next ? h("button", { id: "tutorialNextCourse", type: "button", className: "btn primary sm", disabled: props.pending,
      onClick: props.next }, copy.next_lesson) : null,
    props.exit ?? h("button", { type: "button", className: "btn sm", onClick: props.close }, copy.close)));
}

const NONE: ReadonlySet<string> = new Set();

/** Ids that turned up since they were last shown; they stay fresh until the ids change again. Nothing is seen while
 *  `shown` is false, and the first sight has nothing fresh. */
function useFreshIds(ids: readonly string[] | null | undefined, shown = true): ReadonlySet<string> {
  const key = `${shown}|${ids?.join("\n")}`;
  const [memo, setMemo] = useState<{ key: string; base: ReadonlySet<string> | null; fresh: ReadonlySet<string> }>({ key: "", base: null, fresh: NONE });
  if (memo.key === key) return memo.fresh;
  const base = memo.base ?? (ids ? new Set(ids) : null);
  const next = !shown || !ids ? { key, base, fresh: NONE } : { key, base: new Set(ids), fresh: freshIds(base ?? new Set(ids), ids) };
  setMemo(next);
  return next.fresh;
}

type HudProps = { snapshot: TutorialSnapshot | null; selected: Lesson | undefined; practice: boolean; open: boolean; exit: ReactNode; toggle(): void };

/** Practice HUD: progress ring, stage dots and the exit. A stage dot that turns done pops once. */
function TutorialHud(props: HudProps): ReactNode {
  const { snapshot, selected, practice } = props;
  const stages = snapshot?.stages ?? [];
  const done = stages.filter((stage) => stage.status === "done").map((stage) => stage.id);
  const popped = useFreshIds(done);
  const fraction = stages.length ? done.length / stages.length : lessonFraction(selected);
  return h("div", { className: "tutorial-hud" },
    h("button", { id: "tutorialOpen", className: "tutorial-hud-pill", type: "button", "aria-label": snapshot?.copy.open_tutorial ?? "튜토리얼",
      "aria-expanded": props.open, "aria-controls": "tutorialPanel", onClick: props.toggle },
      h(Ring, { fraction: practice ? fraction : 0 }), h("span", { className: "tutorial-hud-label" }, practice ? snapshot!.copy.practice : "튜토리얼"),
      practice ? h("span", { className: "tutorial-hud-dots", "aria-hidden": true }, ...stages.map((stage) => h("i", {
        key: stage.id, className: stage.status, title: stage.title, "data-pop": popped.has(stage.id) ? "" : undefined,
      }))) : null, practice && snapshot?.paused ? h("span", { className: "tutorial-paused" }, snapshot.copy.pause) : null), props.exit);
}

function useHudVisible(snapshot: TutorialSnapshot | null, initialFailed: boolean, close: () => void): boolean {
  const visible = hudVisible(snapshot, initialFailed);
  useEffect(() => { if (!visible) close(); }, [visible]);
  return visible;
}

/** The first pull of the tutorial snapshot; true once it failed (the failure itself is alarmed). */
function useInitialFailed(ports: TutorialPorts): boolean {
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    void ports.loadInitial().catch((error) => { setFailed(true); ports.alarm(String(error)); });
  }, [ports]);
  return failed;
}

/** The host's tutorial snapshot, the current screen and the overlay state, each followed as an external store. */
function useTutorialStores(ports: TutorialPorts) {
  const raw = useSyncExternalStore(ports.model.subscribe, ports.model.getSnapshot, ports.model.getSnapshot);
  const snapshot = readSnapshot(raw);
  const screen = useSyncExternalStore(ports.nav.subscribe, ports.nav.currentScreen, ports.nav.currentScreen);
  const overlayBusy = useSyncExternalStore(ports.overlay.subscribe, ports.overlay.isBusy, ports.overlay.isBusy);
  const overlayHost = useSyncExternalStore(ports.overlay.subscribe, ports.overlay.currentHost ?? noHost, ports.overlay.currentHost ?? noHost);
  return { snapshot, screen, overlayBusy, overlayHost };
}

/** One host action at a time: true when the host carried it out (not cancelled); errors are alarmed. A confirmed
 *  exit closes the panel. */
function useTutorialAct(ports: TutorialPorts, pending: boolean, setPending: (value: boolean) => void, setOpen: (value: boolean) => void) {
  return useCallback(async (action: string, payload?: Record<string, unknown>) => {
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
}

/** What the panel's layers read: the ports, the snapshot and overlay state, the pending lock and the act/exit controls. */
type PanelView = {
  ports: TutorialPorts; snapshot: TutorialSnapshot | null; overlayBusy: boolean; pending: boolean; practice: boolean;
  selected: Lesson | undefined; act(action: string, payload?: Record<string, unknown>): Promise<boolean>;
  exitButton(id?: string, primary?: boolean): ReactNode;
};

function hudLayer(view: PanelView, hudShown: boolean, open: boolean, setOpen: (value: boolean) => void, entry: Element): ReactNode {
  const { ports, snapshot, selected, practice } = view;
  return hudShown
    ? (ports.portal ?? createPortal)(h(TutorialHud, { snapshot, selected, practice, open, exit: view.exitButton("tutorialExit"), toggle: () => setOpen(!open) }), entry)
    : null;
}

function lessonsLayer(view: PanelView, layer: {
  open: boolean; hudShown: boolean; setOpen(value: boolean): void; fresh: ReadonlySet<string>;
  runLesson(item: Lesson, action: string): Promise<void>; confirmAction(action: "reset_progress" | "cleanup"): Promise<void>;
}): ReactNode {
  const { ports, snapshot, pending, practice, act } = view;
  const { setOpen, runLesson, confirmAction } = layer;
  return lessonsPanelOpen(layer.hudShown, layer.open, snapshot, view.overlayBusy) ? h("section", { id: "tutorialPanel", className: "tutorial-panel", "aria-label": "튜토리얼",
    onKeyDown: (event: { key: string; nativeEvent: { isComposing?: boolean }; stopPropagation(): void }) => {
      if (event.key === "Escape" && !event.nativeEvent.isComposing) { event.stopPropagation(); setOpen(false); ports.doc.getElementById("tutorialOpen")?.focus(); }
    } },
    h(TutorialLessons, { snapshot: snapshot!, pending, practice, fresh: layer.fresh,
      run: (item, action) => void runLesson(item, action),
      close: () => { setOpen(false); ports.doc.getElementById("tutorialOpen")?.focus(); },
      act: (action) => void act(action), confirm: (action) => void confirmAction(action) })) : null;
}

function inviteLayer(view: PanelView): ReactNode {
  const { snapshot, pending, act } = view;
  return snapshot?.invitation.visible && !view.overlayBusy ? h("section", { className: "tutorial-invite", role: "region", "aria-labelledby": "tutorialInviteTitle" },
    h("h2", { id: "tutorialInviteTitle" }, snapshot.invitation.title), h("p", null, snapshot.invitation.body),
    h("div", { className: "tutorial-actions" },
      h("button", { type: "button", className: "btn", disabled: pending, onClick: () => void act("later") }, snapshot.copy.later),
      h("button", { type: "button", className: "btn primary", disabled: pending,
        onClick: () => void act("start", { scenario_id: snapshot.scenarios.find((item) => item.recommended)?.id ?? "first_hwpx" }) }, snapshot.copy.start))) : null;
}

function pausedLayer(view: PanelView): ReactNode {
  const { snapshot, pending, act } = view;
  return view.practice && snapshot?.paused && !view.overlayBusy ? h("section", { className: "tutorial-paused-card", role: "region", "aria-label": snapshot.copy.pause },
    h("p", null, snapshot.recovery?.body ?? view.selected?.title),
    h("button", { id: "tutorialResume", className: "btn primary sm", type: "button", disabled: pending,
      onClick: () => void act("resume") }, snapshot.copy.resume)) : null;
}

function finaleLayer(view: PanelView, layer: {
  shown: boolean; result: TutorialSnapshot["result"] | null; position: CoachPlacement | null; nextLesson: Lesson | undefined;
  chooseLesson(item: Lesson): Promise<void>; dismiss(): void;
}): ReactNode {
  const { result, nextLesson, chooseLesson } = layer;
  return layer.shown && result ? h(TutorialFinale, { result, copy: view.snapshot!.copy, pending: view.pending, doc: view.ports.doc, position: layer.position,
    next: nextLesson ? () => void chooseLesson(nextLesson) : null, exit: view.exitButton(undefined, !nextLesson),
    close: () => layer.dismiss() }) : null;
}

function guideLayer(view: PanelView, layer: {
  shown: boolean; beat: TutorialBeat | null; identity: string; found: Target | null; dialogHost: Element | null;
  recover(): Promise<void>;
}): ReactNode {
  const { ports, snapshot, selected, act } = view;
  const { beat, recover } = layer;
  return layer.shown && beat ? h(TutorialGuide, { beat, identity: layer.identity,
    copy: snapshot!.copy, found: layer.found, dialogHost: layer.dialogHost, doc: ports.doc, portal: ports.portal ?? createPortal,
    step: selected ? `${Math.min(snapshot!.checkpoint + 1, selected.step_count)} / ${selected.step_count}` : "",
    overlayBusy: view.overlayBusy, pending: view.pending, exit: view.exitButton("tutorialDialogExit"),
    act: (action, payload) => void act(action, payload), recover: () => void recover() }) : null;
}

export function TutorialPanel(ports: TutorialPorts): ReactNode {
  const { snapshot, screen, overlayBusy, overlayHost } = useTutorialStores(ports);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [resultDismissed, setResultDismissed] = useState(false);

  const initialFailed = useInitialFailed(ports);

  const act = useTutorialAct(ports, pending, setPending, setOpen);

  const hudShown = useHudVisible(snapshot, initialFailed, () => setOpen(false));

  const beat = liveBeat(snapshot);
  const identity = guideIdentity(snapshot, beat);
  const beatSelector = beatAnchor(beat);
  const practice = snapshot?.practice?.active === true;
  const dialogHost = dialogHostFor(overlayHost, beatSelector);
  const canGuide = !overlayBusy || !!dialogHost;
  const result = shownResult(snapshot, overlayBusy);
  useEffect(() => setResultDismissed(false), [result?.title]);
  const target = guideTarget(beat, beatSelector, canGuide, result, screen);
  usePressReport(ports, snapshot, screen, beatSelector);
  const found = useAnchorBox(ports.doc, dialogHost, target, `${identity}|${target}`, spansLines(beat, target, beatSelector), [screen, open]);
  const resultHeight = useElementHeight(ports.doc, "tutorialFinale", 330, [result?.title, found]);

  const selected = snapshot?.scenarios.find((item) => item.id === snapshot.scenario_id);
  const nextLesson = snapshot?.scenarios.find((item) => item.id === result?.next_scenario_id);
  const fresh = useFreshIds(snapshot?.scenarios.filter((item) => item.completed).map((item) => item.id), open);
  const shown = Boolean(beat && canGuide);
  const resultShown = Boolean(result && !resultDismissed);
  const resultPosition = finalePosition(found, result, ports.doc, resultHeight);

  const recover = async () => {
    const element = visibleElement(dialogHost ?? ports.doc, beatSelector);
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
  const exitButton = (id?: string, primary = false) => practice ? h("button", { id, className: primary ? "btn primary sm tutorial-exit" : "btn sm tutorial-exit", type: "button", disabled: pending,
    onClick: () => void act("exit") }, snapshot!.copy.exit) : null;

  const view: PanelView = { ports, snapshot, overlayBusy, pending, practice, selected, act, exitButton };
  return h("div", { id: "tutorialPanelRoot", className: "tutorial-root", "data-screen": screen ?? "", "data-practice": practice },
    hudLayer(view, hudShown, open, setOpen, entry),
    lessonsLayer(view, { open, hudShown, setOpen, fresh, runLesson, confirmAction }),
    inviteLayer(view),
    pausedLayer(view),
    finaleLayer(view, { shown: resultShown, result, position: resultPosition, nextLesson, chooseLesson,
      dismiss: () => setResultDismissed(true) }),
    guideLayer(view, { shown, beat, identity, found, dialogHost, recover }));
}
