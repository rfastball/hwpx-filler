/* Motion pacing for the tutorial guide: when the ring, the coach and the finale documents move. Timers only — no
 * React (panel.ts owns the hooks), no geometry and no lesson meaning: the host decides beats and results, these
 * only pace what is already decided. Every controller cancels its own timers on `dispose`. */
import type { Box } from "./spotlight.ts";

export type Clock = {
  setTimeout(run: () => void, ms: number): number;
  clearTimeout(id: number): void;
  requestAnimationFrame(run: () => void): number;
  cancelAnimationFrame(id: number): void;
};

/** A missing anchor keeps its last ring this long (a screen change or a late render) before the ring fades. */
export const SPOT_HOLD = 300;
/** Reduced motion: the ring fades out this long in place before it jumps to a new anchor. */
export const SPOT_JUMP_FADE = 140;
/** The coach stays hidden this long between beats while the ring glides; reduced motion has no glide to wait for. */
export const COACH_SWAP = 260;
export const COACH_SWAP_REDUCED = 150;
/** Longest the next coach then waits for its anchor before it shows without one (with the way back). */
export const COACH_ANCHOR_WAIT = 500;
/** Finale documents: the first lands after the lead, each next one a stagger later; the count follows a landing. */
export const FINALE_LEAD = 80;
export const FINALE_STAGGER = 120;
export const FINALE_STAGGER_REDUCED = 50;
export const FINALE_COUNT_LAG = 300;
export const FINALE_COUNT_LAG_REDUCED = 60;
/** A finale document leaves the result panel at this scale. */
export const FLY_SCALE = 0.16;

/** Timers of the document's own window, resolved at call time (a server render never calls them). */
export function clockOf(doc: Document): Clock {
  const view = () => doc.defaultView ?? (globalThis as unknown as Window);
  return {
    setTimeout: (run, ms) => view().setTimeout(run, ms),
    clearTimeout: (id) => view().clearTimeout(id),
    requestAnimationFrame: (run) => view().requestAnimationFrame(run),
    cancelAnimationFrame: (id) => view().cancelAnimationFrame(id),
  };
}

export function prefersReducedMotion(doc: Document): boolean {
  return doc.defaultView?.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

/** Named pending timers and frames: re-arming a name cancels its previous one; `clear` cancels them all. */
function slots(clock: Clock) {
  const live = new Map<string, { id: number; frame: boolean }>();
  const cancel = (name: string) => {
    const slot = live.get(name);
    if (!slot) return;
    live.delete(name);
    if (slot.frame) clock.cancelAnimationFrame(slot.id);
    else clock.clearTimeout(slot.id);
  };
  const arm = (name: string, frame: boolean, start: (run: () => void) => number, run: () => void) => {
    cancel(name);
    live.set(name, { id: start(() => { live.delete(name); run(); }), frame });
  };
  return {
    after: (name: string, ms: number, run: () => void) => arm(name, false, (go) => clock.setTimeout(go, ms), run),
    frame: (name: string, run: () => void) => arm(name, true, (go) => clock.requestAnimationFrame(go), run),
    has: (name: string) => live.has(name),
    busy: () => live.size > 0,
    cancel,
    clear() { for (const name of [...live.keys()]) cancel(name); },
  };
}

/** A tiny external store: React reads it with useSyncExternalStore. */
function store<S>(initial: S) {
  let state = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set(next: S) { state = next; for (const listener of listeners) listener(); },
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  };
}

/** The ring's shown frame. `epoch` counts arrivals: each one glides from the last frame. `faded` keeps that frame
 *  invisible in place, so the next anchor still glides from where the ring was. */
export type HeldSpot<T> = { target: T | null; key: string; epoch: number; faded: boolean };

/** Ring continuity across a beat change, a screen change or a late render. A missing anchor holds the last frame
 *  for SPOT_HOLD, then fades it out in place; the next anchor (a new key, or the same one coming back) glides from
 *  there. Reduced motion fades the old frame out first, then jumps. Another container (`zone`, the page or a
 *  dialog) has nothing to glide from and starts fresh. */
export function createSpotHold<T>(clock: Clock, first: T | null, firstKey: string) {
  const shown = store<HeldSpot<T>>({ target: first, key: firstKey, epoch: 0, faded: false });
  const timers = slots(clock);
  let away = false, zone: unknown = null, jump: { target: T; key: string } | null = null;
  const land = (target: T, key: string) => shown.set({ target, key, epoch: shown.get().epoch + 1, faded: false });
  const fade = () => shown.set({ ...shown.get(), faded: true });
  const drop = () => {
    timers.clear(); jump = null; away = false;
    if (shown.get().target) shown.set({ ...shown.get(), target: null, faded: false });
  };
  const lose = () => {
    if (jump) { timers.cancel("jump"); jump = null; }
    if (!shown.get().target) return;
    away = true;
    if (!shown.get().faded && !timers.has("hold")) timers.after("hold", SPOT_HOLD, fade);
  };
  const reach = (target: T, key: string, reduced: boolean) => {
    const before = shown.get();
    const moved = !!before.target && (key !== before.key || away);
    timers.cancel("hold"); away = false;
    if (!moved) {
      if (target !== before.target || key !== before.key) shown.set({ ...before, target, key, faded: false });
      return;
    }
    if (!reduced || before.faded) { land(target, key); return; }
    jump = { target, key };
    fade();
    timers.after("jump", SPOT_JUMP_FADE, () => { const to = jump!; jump = null; land(to.target, to.key); });
  };
  return {
    get: shown.get,
    subscribe: shown.subscribe,
    feed(target: T | null, key: string, reduced: boolean, place: unknown = null) {
      if (place !== zone) { zone = place; drop(); }
      if (!target) lose();
      else if (jump) jump = { target, key };
      else reach(target, key, reduced);
    },
    dispose() {
      timers.clear();
      if (jump) { jump = null; away = true; }
    },
  };
}

/** Which beat the coach shows, and whether it is hidden. */
export type CoachSwap = { key: string; hidden: boolean };

/** Coach swap between beats: the old card fades out where it stands, stays hidden while the ring glides, then the
 *  new words take the new place and fade in. The new card waits for its anchor (COACH_ANCHOR_WAIT at most) so it
 *  does not show in a fallback corner and then jump. Reveal is two frames after the new words, once their size is
 *  measured. A first sight without an anchor waits the same way. */
export function createCoachSwap(clock: Clock, firstKey: string, anchored: boolean) {
  const shown = store<CoachSwap>({ key: firstKey, hidden: !anchored });
  const timers = slots(clock);
  let want = firstKey, ready = anchored, waiting = false;
  const set = (next: CoachSwap) => {
    const before = shown.get();
    if (next.key !== before.key || next.hidden !== before.hidden) shown.set(next);
  };
  const reveal = () => {
    timers.clear(); waiting = false;
    set({ key: want, hidden: true });
    timers.frame("reveal", () => timers.frame("reveal", () => set({ key: want, hidden: false })));
  };
  const settle = () => {
    if (ready) { reveal(); return; }
    waiting = true;
    timers.after("wait", COACH_ANCHOR_WAIT, reveal);
  };
  const begin = (reduced: boolean) => {
    timers.clear(); waiting = false;
    set({ key: shown.get().key, hidden: true });
    timers.after("swap", reduced ? COACH_SWAP_REDUCED : COACH_SWAP, settle);
  };
  return {
    get: shown.get,
    subscribe: shown.subscribe,
    feed(key: string, anchored: boolean, reduced: boolean) {
      ready = anchored;
      if (key !== want) { want = key; begin(reduced); return; }
      if (waiting && anchored) reveal();
      else if (shown.get().hidden && !timers.busy()) settle();
    },
    dispose() { timers.clear(); waiting = false; },
  };
}

/** Finale progress: documents landed, and landings the count has followed. */
export type FinaleState = { arrived: number; counted: number };

/** Land `docs` finale documents one by one and let the count follow each landing. Returns the cancel. */
export function playFinale(clock: Clock, docs: number, reduced: boolean, onChange: (state: FinaleState) => void): () => void {
  let state: FinaleState = { arrived: 0, counted: 0 };
  const ids: number[] = [];
  const step = reduced ? FINALE_STAGGER_REDUCED : FINALE_STAGGER;
  const lag = reduced ? FINALE_COUNT_LAG_REDUCED : FINALE_COUNT_LAG;
  const reach = (patch: Partial<FinaleState>) => { state = { ...state, ...patch }; onChange(state); };
  for (let index = 0; index < docs; index += 1) {
    const at = FINALE_LEAD + step * index;
    ids.push(clock.setTimeout(() => reach({ arrived: Math.max(state.arrived, index + 1) }), at));
    ids.push(clock.setTimeout(() => reach({ counted: Math.max(state.counted, index + 1) }), at + lag));
  }
  return () => { for (const id of ids) clock.clearTimeout(id); };
}

/** The count shown after `counted` of `docs` landings: it reaches the real count on the last landing. */
export function countShown(count: number, counted: number, docs: number): number {
  return docs > 0 ? Math.round(count * Math.min(counted, docs) / docs) : count;
}

/** Where a fan document starts: its centre on the result panel's centre (offset from its place in the fan). */
export function flyFrom(origin: Box | null, fan: Box | null, docTop = 16, docHeight = 108): { x: number; y: number } {
  if (!origin || !fan) return { x: 0, y: 0 };
  return {
    x: Math.round(origin.left + origin.width / 2 - (fan.left + fan.width / 2)),
    y: Math.round(origin.top + origin.height / 2 - (fan.top + docTop + docHeight / 2)),
  };
}

/** Ids now present that were not in `before`: what turned done since it was last shown. */
export function freshIds(before: ReadonlySet<string>, now: readonly string[]): ReadonlySet<string> {
  return new Set(now.filter((id) => !before.has(id)));
}
