import budget from './run_budget.json' with { type: 'json' };

for (const [name, value] of Object.entries(budget)) {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`invalid live101 budget ${name}`);
}

export const BOOT_MS = budget.boot_ms;
export const SURFACE_MS = budget.surface_ms;
export const HARD_STOP_MS = BOOT_MS + SURFACE_MS + budget.hard_stop_margin_ms;
export const OUTER_MS = HARD_STOP_MS + budget.cleanup_ms + budget.parent_slack_ms;

export function hardStopReport({ phase, mode, home, previous, shots, elapsedMs }) {
  const reason = `native live101 driver hard stop after ${HARD_STOP_MS} ms`;
  return {
    phase, mode, home,
    observations: previous?.observations ?? {},
    documents: previous?.documents ?? [],
    hwpx_generated: previous?.hwpx_generated ?? 0,
    shots,
    elapsed_s: Math.round(elapsedMs / 100) / 10,
    deadline_ms: HARD_STOP_MS,
    verdict: { ok: false, failures: [reason] },
    error: reason,
  };
}
