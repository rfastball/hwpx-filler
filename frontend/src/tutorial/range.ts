/* The text range a live range beat (`authoring-range`, #1136) asks the template editor to paint. The host resolves
 * it on the open practice document; the shell only carries it to the editor, which only draws it. */

export type BeatRange = { session_id: string; start: number; end: number };

/** The live range beat's range exactly as the host resolved it; null when no such beat is live. */
export function beatRange(snapshot: unknown): BeatRange | null {
  const snap = snapshot as { active?: boolean; paused?: boolean; beat?: { target?: unknown; range?: unknown } | null } | null;
  const beat = snap?.active && !snap.paused ? snap.beat : null;
  const range = beat?.target === "authoring-range" ? beat.range as { session_id?: unknown; start?: unknown; end?: unknown } | null : null;
  return range && typeof range.session_id === "string" && typeof range.start === "number" && typeof range.end === "number"
    ? { session_id: range.session_id, start: range.start, end: range.end } : null;
}

/** Hand every tutorial projection's range to `editor.guide` (null clears it); returns `editor` for wiring in place. */
export function followBeatRange<T extends { guide(range: BeatRange | null): void }>(
  model: { getSnapshot(): unknown; subscribe(listener: () => void): unknown }, editor: T): T {
  model.subscribe(() => editor.guide(beatRange(model.getSnapshot())));
  return editor;
}
