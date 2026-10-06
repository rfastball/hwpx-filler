/* UI facts the guide reports to the host (#1127 · #1149 review). The web reports only what happened to the current
 * beat's own boxed control — pressed, or gone unpressed from its menu — and the host decides what that means.
 * React-free on purpose: the shell tutorial surface (`panel.ts`) owns the effect that runs these watchers. */
import { watchBoxedPress, watchTransientClose } from "./spotlight.ts";

export type BeatFact = Record<string, unknown>;

/** The snapshot fields a report reads — structural, so this module does not import the panel back. */
type ReportSnapshot = {
  active: boolean; paused: boolean; scenario_id: string | null; checkpoint: number;
  beat: { mode: string; screen: string | null; target: string | null; press?: boolean; transient?: boolean } | null;
};
type ReportPorts = {
  doc: Document;
  dispatch(action: string, payload?: Record<string, unknown>): Promise<unknown>;
  alarm(message: string): void;
};
type BeatWatch = (doc: Document, selector: string, report: () => void) => () => void;

/** The fact a live action beat on its own screen reports when the host marked it with `flag`; null otherwise. */
function beatFact(snapshot: ReportSnapshot | null, screen: string | null, flag: "press" | "transient"): BeatFact | null {
  const beat = snapshot?.active && !snapshot.paused ? snapshot.beat : null;
  if (!beat || beat.mode !== "action" || beat[flag] !== true || !beat.target) return null;
  if (beat.screen !== null && beat.screen !== screen) return null;
  return { scenario_id: snapshot!.scenario_id, checkpoint: snapshot!.checkpoint, anchor: beat.target };
}

/** The fact a press beat reports, or null: only a live action beat marked `press`, on its own screen. */
export function pressFact(snapshot: ReportSnapshot | null, screen: string | null): BeatFact | null {
  return beatFact(snapshot, screen, "press");
}

/** The fact a menu-item beat reports once its menu closes unpressed, or null: only a live beat marked `transient`. */
export function closedFact(snapshot: ReportSnapshot | null, screen: string | null): BeatFact | null {
  return beatFact(snapshot, screen, "transient");
}

/** Both reports a beat can make: a press of its boxed control that runs no product command, and its menu closing
 *  unpressed. Each is `[action, fact, watcher]`; a null fact means that report does not apply to this beat. */
export function beatReports(snapshot: ReportSnapshot | null, screen: string | null): readonly [string, BeatFact | null, BeatWatch][] {
  return [["observe_ui", pressFact(snapshot, screen), watchBoxedPress],
    ["observe_ui_closed", closedFact(snapshot, screen), watchTransientClose]];
}

/** Watch `selector` for one report and send the fact when it happens; the returned function stops watching. */
export function watchReport(ports: ReportPorts, selector: string, action: string, fact: BeatFact, watch: BeatWatch): () => void {
  return watch(ports.doc, selector, () => {
    void Promise.resolve(ports.dispatch(action, fact)).catch((error) => ports.alarm(String(error)));
  });
}
