/* Eight task lessons. The host owns lesson state; this surface owns only geometry and controls. */
import { createElement as h, useCallback, useEffect, useLayoutEffect, useState, useSyncExternalStore } from "react";
import type { CSSProperties, ReactNode } from "react";
import { createPortal } from "react-dom";

export type Lesson = {
  id: string; title: string; description: string; recommended: boolean;
  completed: boolean; checkpoint: number; step_count: number;
};
export type TutorialBeat = {
  id: string; title: string; body: string; mode: "explain" | "action" | "finish";
  screen: string | null; target: string | null;
  placement: "top" | "right" | "bottom" | "left" | "center"; can_next: boolean;
};
export type TutorialSnapshot = {
  kind: "tutorial-lessons/v1";
  invitation: { visible: boolean; title: string; body: string };
  active: boolean; paused: boolean; scenario_id: string | null; checkpoint: number;
  scenarios: readonly Lesson[];
  stages?: readonly { id: string; title: string; status: "done" | "current" | "pending" }[];
  beat: TutorialBeat | null;
  show_result?: boolean;
  result?: null | { title: string; body: string; count: number; screen: string; target: string; documents: readonly { name: string; path: string; kind: string }[]; actions: readonly { label: string; target: string }[] };
  recovery: { title: string; body: string } | null;
  resources: { ready: boolean; summary: string; files?: readonly { name: string; path: string; kind: string }[] };
  copy: {
    start: string; later: string; pause: string; resume: string; skip: string;
    restart: string; next: string; prepare: string; cleanup: string; reset: string;
    open_tutorial: string; close: string; choose_scenario: string; reset_confirm: string; cleanup_confirm: string;
  };
};
export type TutorialPorts = {
  model: { getSnapshot(): unknown; subscribe(listener: () => void): () => void };
  loadInitial(): Promise<unknown>;
  dispatch(action: string, payload?: Record<string, unknown>): Promise<unknown>;
  nav: { subscribe(listener: () => void): () => void; currentScreen(): string | null; go(screen: string): void };
  overlay: { subscribe(listener: () => void): () => void; isBusy(): boolean };
  confirm(options: { title: string; body: string; confirmLabel: string; cancelLabel: string; danger: boolean }): Promise<boolean>;
  alarm(message: string): void;
  doc: Document;
  portal?: (children: ReactNode, container: Element) => ReactNode;
};

const ANCHORS: Readonly<Record<string, string>> = Object.freeze({
  "new-job": "#jobCandNewWork, #libraryNewWork",
  "template-list": "#editorTplList",
  "data-picker": "#jobBtnPickData, #editorPoolBrowse, #dataPickerBrowse",
  mapping: "#editorPairZone, #wbMapPanel",
  "filename-pattern": "#editor-body input[data-act='pattern']",
  "save-job": "#editor-foot button[data-act='save']",
  "job-list": "#jobBrowseOpen, #jobCandidates",
  "row-filter": "#jobFilterSearch",
  "row-selection": "#jobSelAll, #jobTableBody",
  "content-options": "#jobContentSelectionZone",
  generate: "#jobManagedCreate, #jobGenBtn",
  results: "#jobResult",
  "txt-review": "#wbCard",
  "txt-copy": "#wbCopy",
  "prepare-examples": "#tutorialPrepare",
  "authoring-canvas": "#authoring-canvas, #authoring-outline-title",
  trial: "#authoring-dock-tab-trial, .authoring-trial-input .btn.primary",
  "save-template": "[data-guide='save-template']",
  "apply-change": "[data-guide='apply-change'], #authoring-dock-tab-impact",
});

export function anchorSelector(key: string | null): string | null {
  return key ? ANCHORS[key] ?? null : null;
}

function visibleElement(doc: Document, selector: string | null): HTMLElement | null {
  if (!selector) return null;
  for (const candidate of doc.querySelectorAll<HTMLElement>(selector)) {
    const rect = candidate.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0 && !candidate.closest("[hidden], [inert], .hidden")) return candidate;
  }
  return null;
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

export function TutorialPanel(ports: TutorialPorts): ReactNode {
  const raw = useSyncExternalStore(ports.model.subscribe, ports.model.getSnapshot, ports.model.getSnapshot);
  const snapshot = readSnapshot(raw);
  const screen = useSyncExternalStore(ports.nav.subscribe, ports.nav.currentScreen, ports.nav.currentScreen);
  const overlayBusy = useSyncExternalStore(ports.overlay.subscribe, ports.overlay.isBusy, ports.overlay.isBusy);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [coachHeight, setCoachHeight] = useState(162);
  const [resultHeight, setResultHeight] = useState(330);
  const [resultDismissed, setResultDismissed] = useState(false);

  useEffect(() => { void ports.loadInitial().catch((error) => ports.alarm(String(error))); }, [ports]);

  const act = useCallback(async (action: string, payload?: Record<string, unknown>) => {
    if (pending) return;
    setPending(true);
    try { await ports.dispatch(action, payload); }
    catch (error) { ports.alarm(String(error)); }
    finally { setPending(false); }
  }, [pending, ports]);

  const beat = snapshot?.active && !snapshot.paused ? snapshot.beat : null;
  const result = snapshot?.show_result && !snapshot.active && !overlayBusy ? snapshot.result : null;
  useEffect(() => setResultDismissed(false), [result?.title]);
  const target = beat && (beat.screen === null || beat.screen === screen) && !overlayBusy ? beat.target
    : result && result.screen === screen ? result.target : null;
  useLayoutEffect(() => {
    if (!target) { setRect(null); return; }
    let frame = 0;
    const measure = () => {
      const element = visibleElement(ports.doc, anchorSelector(target));
      const next = element?.getBoundingClientRect() ?? null;
      const shown = next && next.right > 0 && next.bottom > 0 && next.left < window.innerWidth && next.top < window.innerHeight ? next : null;
      setRect((before) => before?.x === shown?.x && before?.y === shown?.y && before?.width === shown?.width && before?.height === shown?.height ? before : shown);
    };
    const update = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(measure); };
    measure();
    const observer = new MutationObserver((mutations) => {
      if (mutations.some((change) => !(change.target as Element).closest?.("#tutorialPanelRoot"))) update();
    });
    observer.observe(ports.doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "class", "style", "inert"] });
    ports.doc.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      cancelAnimationFrame(frame); observer.disconnect();
      ports.doc.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [target, ports.doc, screen, open]);

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
  const count = snapshot?.scenarios.filter((item) => item.completed).length ?? 0;
  const total = snapshot?.scenarios.length ?? 0;
  const stages = snapshot?.stages ?? [];
  const stageDone = stages.filter((stage) => stage.status === "done").length;
  const fraction = stages.length ? stageDone / stages.length : selected?.step_count ? selected.checkpoint / selected.step_count : 0;
  const shown = Boolean(beat && !overlayBusy && (rect || beat.placement === "center" || beat.target === null));
  const resultShown = Boolean(result && !resultDismissed && result.screen === screen && rect);
  const position = rect && beat ? placeCoach(rect, { width: window.innerWidth, height: window.innerHeight }, beat.placement, coachHeight) : null;
  const resultPosition = rect && result ? placeCoach(rect, { width: window.innerWidth, height: window.innerHeight }, "right", resultHeight) : null;
  const spotStyle: CSSProperties | undefined = rect ? {
    left: Math.max(0, rect.left - 6), top: Math.max(0, rect.top - 6),
    width: rect.width + 12, height: rect.height + 12,
  } : undefined;
  const coachStyle: CSSProperties | undefined = position ? { left: position.x, top: position.y, width: position.width } : undefined;

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
  const hud = h("div", { className: "tutorial-hud" },
    h("button", { id: "tutorialOpen", className: "tutorial-hud-pill", type: "button", "aria-label": label,
      "aria-expanded": open, "aria-controls": "tutorialPanel", onClick: () => setOpen(!open) },
      h(Ring, { fraction }), h("span", { className: "tutorial-hud-label" }, snapshot?.active ? stages.find((stage) => stage.status === "current")?.title ?? selected?.title ?? "튜토리얼" : "튜토리얼"),
      h("span", { className: "tutorial-hud-dots", "aria-hidden": true }, ...stages.map((stage) => h("i", {
        key: stage.id, className: stage.status, title: stage.title,
      }))), snapshot?.paused ? h("span", { className: "tutorial-paused" }, snapshot.copy.pause) : null));

  const list = snapshot?.scenarios.map((item) => h("li", { key: item.id, className: item.id === selected?.id ? "current" : item.completed ? "done" : "" },
    h("span", { className: "tutorial-check", "aria-hidden": true }, item.completed ? "✓" : ""),
    h("span", null, item.title), item.recommended ? h("span", { className: "tutorial-recommended" }, "★") : null,
    h("button", { type: "button", className: "btn sm", disabled: pending,
      onClick: () => { void act(item.id === snapshot.scenario_id && snapshot.paused ? "resume" : "select", item.id === snapshot.scenario_id && snapshot.paused ? {} : { scenario_id: item.id }); setOpen(false); } },
      item.id === snapshot.scenario_id && snapshot.paused ? snapshot.copy.resume : snapshot.copy.choose_scenario)));

  return h("div", { id: "tutorialPanelRoot", className: "tutorial-root", "data-screen": screen ?? "" },
    (ports.portal ?? createPortal)(hud, entry),
    open && snapshot && !snapshot.invitation.visible ? h("section", { id: "tutorialPanel", className: "tutorial-panel", "aria-label": "튜토리얼",
      onKeyDown: (event: { key: string; nativeEvent: { isComposing?: boolean }; stopPropagation(): void }) => {
        if (event.key === "Escape" && !event.nativeEvent.isComposing) { event.stopPropagation(); setOpen(false); ports.doc.getElementById("tutorialOpen")?.focus(); }
      } },
      h("header", null, h("h2", null, "튜토리얼"), h("span", null, `${count}/${total}`)),
      h("ol", { className: "tutorial-list" }, ...list ?? []),
      snapshot.resources.summary ? h("p", { className: "tutorial-resource" }, snapshot.resources.summary) : null,
      snapshot.recovery?.body && snapshot.recovery.body !== snapshot.resources.summary
        ? h("p", { className: "tutorial-resource" }, snapshot.recovery.body) : null,
      snapshot.resources.files?.length ? h("ul", { className: "tutorial-resources" }, ...snapshot.resources.files.map((file) => h("li", { key: file.path },
        h("strong", null, file.name), h("code", null, file.path)))) : null,
      h("div", { className: "tutorial-actions" },
        snapshot.active ? h("button", { className: "btn sm", type: "button", disabled: pending, onClick: () => void act(snapshot.paused ? "resume" : "pause") }, snapshot.paused ? snapshot.copy.resume : snapshot.copy.pause) : null,
        snapshot.active ? h("button", { className: "btn sm", type: "button", disabled: pending, onClick: () => void act("skip") }, snapshot.copy.skip) : null,
        selected ? h("button", { className: "btn sm", type: "button", disabled: pending, onClick: () => void act("restart", { scenario_id: snapshot.scenario_id }) }, snapshot.copy.restart) : null,
        h("button", { id: "tutorialPrepare", className: "btn sm", type: "button", disabled: pending, onClick: () => void act("prepare_examples") }, snapshot.copy.prepare),
        h("button", { className: "btn sm", type: "button", disabled: pending, onClick: () => void confirmAction("cleanup") }, snapshot.copy.cleanup),
        h("button", { className: "btn sm", type: "button", disabled: pending, onClick: () => void confirmAction("reset_progress") }, snapshot.copy.reset))) : null,
    snapshot?.invitation.visible ? h("section", { className: "tutorial-invite", role: "dialog", "aria-modal": false, "aria-labelledby": "tutorialInviteTitle" },
      h("h2", { id: "tutorialInviteTitle" }, snapshot.invitation.title), h("p", null, snapshot.invitation.body),
      h("div", { className: "tutorial-actions" },
        h("button", { type: "button", className: "btn", disabled: pending, onClick: () => void act("later") }, snapshot.copy.later),
        h("button", { type: "button", className: "btn primary", disabled: pending,
          onClick: () => void act("start", { scenario_id: snapshot.scenarios.find((item) => item.recommended)?.id ?? "first_hwpx" }) }, snapshot.copy.start))) : null,
    beat && !overlayBusy && !shown ? h("button", { className: "tutorial-recover", type: "button", onClick: () => {
      if (beat.screen && beat.screen !== screen) ports.nav.go(beat.screen);
      else if (beat.target === "prepare-examples") setOpen(true);
      else visibleElement(ports.doc, anchorSelector(beat.target))?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, title: snapshot?.recovery?.body ?? beat.body }, h("span", { className: "tutorial-recover-dot", "aria-hidden": true }), snapshot?.recovery?.title ?? beat.title) : null,
    result && !resultShown && !resultDismissed ? h("button", { className: "tutorial-recover", type: "button", onClick: () => {
      if (result.screen !== screen) ports.nav.go(result.screen);
      else visibleElement(ports.doc, anchorSelector(result.target))?.scrollIntoView({ block: "center", behavior: "smooth" });
    } }, h("span", { className: "tutorial-recover-dot", "aria-hidden": true }), result.title) : null,
    resultShown && result && resultPosition ? h("section", { id: "tutorialFinale", className: "tutorial-finale", role: "region", "aria-label": result.title,
      style: { left: resultPosition.x, top: resultPosition.y } },
      h("div", { className: "tutorial-fin-fan", "aria-hidden": true }, ...result.documents.slice(0, 3).map((document, index) =>
        h("div", { key: document.path, className: `tutorial-fin-doc tutorial-fin-doc-${index}` },
          h("span", { className: "tutorial-fin-lines" }), h("span", null, document.kind)))),
      h("div", { className: "tutorial-fin-count" }, h("strong", null, String(result.count)), h("span", null, result.documents.length ? "문서" : "완료")),
      h("h2", null, result.title), h("p", null, result.body),
      result.documents.length ? h("ul", { className: "tutorial-fin-files" }, ...result.documents.map((document) => h("li", { key: document.path, title: document.path }, document.name))) : null,
      h("div", { className: "tutorial-actions" }, ...result.actions.map((action) => h("button", { key: action.target,
        type: "button", className: "btn sm", onClick: () => {
          const element = visibleElement(ports.doc, anchorSelector(action.target));
          element?.scrollIntoView({ block: "center", behavior: "smooth" });
          element?.focus({ preventScroll: true });
        } }, action.label)), h("button", { type: "button", className: "btn sm", onClick: () => setResultDismissed(true) }, snapshot!.copy.close))) : null,
    shown && beat ? h("div", { className: "tutorial-guide" },
      rect ? h("div", { className: "tutorial-spot", style: spotStyle, "aria-hidden": true }) : h("div", { className: "tutorial-scrim", "aria-hidden": true }),
      rect ? h("div", { className: "tutorial-shield", style: { top: 0, left: 0, right: 0, height: Math.max(0, rect.top - 6) } }) : null,
      rect ? h("div", { className: "tutorial-shield", style: { top: rect.bottom + 6, left: 0, right: 0, bottom: 0 } }) : null,
      rect ? h("div", { className: "tutorial-shield", style: { top: rect.top - 6, left: 0, width: Math.max(0, rect.left - 6), height: rect.height + 12 } }) : null,
      rect ? h("div", { className: "tutorial-shield", style: { top: rect.top - 6, left: rect.right + 6, right: 0, height: rect.height + 12 } }) : null,
      h("section", { id: "tutorialCoach", className: "tutorial-coach", style: coachStyle,
        role: "dialog", "aria-modal": false, "aria-labelledby": "tutorialBeatTitle", "aria-describedby": "tutorialBeatBody",
        "data-side": position?.side ?? "center" },
        position ? h("span", { className: "tutorial-arrow", "aria-hidden": true }) : null,
        h("span", { className: "tutorial-eyebrow" }, selected?.title ?? "튜토리얼", selected ? `${Math.min(snapshot!.checkpoint + 1, selected.step_count)} / ${selected.step_count}` : ""),
        h("h2", { id: "tutorialBeatTitle" }, beat.title), h("p", { id: "tutorialBeatBody", "aria-live": "polite" }, beat.body),
        beat.mode === "explain" && beat.can_next ? h("div", { className: "tutorial-coach-foot" },
          h("button", { className: "btn primary sm", type: "button", disabled: pending, onClick: () => void act("next") }, snapshot!.copy.next)) : null)) : null);
}
