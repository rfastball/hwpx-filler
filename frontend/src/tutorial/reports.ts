/* UI facts the guide reports to the host (#1127 · #1149 review). The web reports only what happened to the current
 * beat's own boxed control — pressed, or gone unpressed from its menu — and the host decides what that means. */
import { useEffect } from "react";
import { watchBoxedPress, watchTransientClose } from "./spotlight.ts";
import type { TutorialPorts, TutorialSnapshot } from "./panel.ts";

type Fact = Record<string, unknown>;

/** The fact a live action beat on its own screen reports when the host marked it with `flag`; null otherwise. */
function beatFact(snapshot: TutorialSnapshot | null, screen: string | null, flag: "press" | "transient"): Fact | null {
  const beat = snapshot?.active && !snapshot.paused ? snapshot.beat : null;
  if (!beat || beat.mode !== "action" || beat[flag] !== true || !beat.target) return null;
  if (beat.screen !== null && beat.screen !== screen) return null;
  return { scenario_id: snapshot!.scenario_id, checkpoint: snapshot!.checkpoint, anchor: beat.target };
}

/** The fact a press beat reports, or null: only a live action beat marked `press`, on its own screen. */
export function pressFact(snapshot: TutorialSnapshot | null, screen: string | null): Fact | null {
  return beatFact(snapshot, screen, "press");
}

/** The fact a menu-item beat reports once its menu closes unpressed, or null: only a live beat marked `transient`. */
export function closedFact(snapshot: TutorialSnapshot | null, screen: string | null): Fact | null {
  return beatFact(snapshot, screen, "transient");
}

type BeatWatch = (doc: Document, selector: string, report: () => void) => () => void;

function useBeatReport(ports: TutorialPorts, fact: Fact | null, beatSelector: string | null, action: string, watch: BeatWatch): void {
  const key = fact && beatSelector ? `${fact.scenario_id}|${fact.checkpoint}|${beatSelector}` : "";
  useEffect(() => {
    if (!fact || !beatSelector) return undefined;
    return watch(ports.doc, beatSelector, () => {
      void Promise.resolve(ports.dispatch(action, fact)).catch((error) => ports.alarm(String(error)));
    });
  }, [ports, key]);
}

/** Report a press on the current beat's own boxed control (a press that runs no product command), or its menu
 *  closing unpressed. A report carries only the fact — lesson, position and anchor — and the host decides. */
export function usePressReport(ports: TutorialPorts, snapshot: TutorialSnapshot | null, screen: string | null, beatSelector: string | null): void {
  useBeatReport(ports, pressFact(snapshot, screen), beatSelector, "observe_ui", watchBoxedPress);
  useBeatReport(ports, closedFact(snapshot, screen), beatSelector, "observe_ui_closed", watchTransientClose);
}
