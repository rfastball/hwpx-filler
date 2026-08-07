/* R4-04 화면 집행자 — shellNav 판정은 그대로 두고 React visibility 효과만 인수한다. */
import { flushSync } from "react-dom";

import { IMMERSIVE_SURFACES } from "../shell/nav.ts";
import type { ShellExecutor } from "../shell/nav.ts";
import type { ProductScreenId, ProductScreenVisibility } from "./product_screens.ts";
import type { ScreenLifecycleRegistry } from "./screen_lifecycle_registry.ts";

type ScrollPoint = { top: number; left: number };
type ScreenMemory = {
  stage: ScrollPoint;
  internal: ReadonlyMap<string, ScrollPoint>;
  focusKey: string;
};

type BridgePort = {
  hostReady(): boolean;
  call(screen: string, action: string, payload: object): Promise<unknown>;
};

export type ProductScreenExecutorDeps = {
  doc: Document;
  bridge: BridgePort;
  visibility: ProductScreenVisibility;
  lifecycle: ScreenLifecycleRegistry;
  reclaimSurfaces(): void;
  notify(message: string): void;
};

function screenRoot(doc: Document, id: string): HTMLElement | null {
  return doc.getElementById(`scr-${id}`);
}

function focusKeyOf(element: Element): string {
  if (element.id !== "") return `#${element.id}`;
  const key = (element as HTMLElement).dataset?.focusKey;
  return key === undefined || key === "" ? "" : `[data-focus-key="${CSS.escape(key)}"]`;
}

function stageOf(doc: Document): HTMLElement {
  const stage = doc.querySelector<HTMLElement>("main.stage");
  if (stage === null) throw new Error("제품 화면 stage(main.stage)가 없습니다.");
  return stage;
}

function captureMemory(doc: Document, id: ProductScreenId): { memory: ScreenMemory; ownedFocus: boolean } {
  const stage = stageOf(doc);
  const root = screenRoot(doc, id);
  const active = doc.activeElement;
  const ownedFocus = root !== null && active !== null && root.contains(active);
  const focusKey = ownedFocus && active !== null ? focusKeyOf(active) : "";
  const internal = new Map<string, ScrollPoint>();
  root?.querySelectorAll<HTMLElement>("[id][data-preserve-scroll]").forEach((element) => {
    internal.set(element.id, { top: element.scrollTop, left: element.scrollLeft });
  });
  return {
    ownedFocus,
    memory: {
      stage: { top: stage.scrollTop, left: stage.scrollLeft },
      internal,
      focusKey,
    },
  };
}

function isUsableFocusTarget(target: HTMLElement, root: HTMLElement): boolean {
  if (!target.isConnected || !root.contains(target)) return false;
  return target.closest('[hidden],[inert],[aria-hidden="true"]') === null;
}

function restoreMemory(
  doc: Document,
  id: ProductScreenId,
  memory: ScreenMemory | undefined,
  outgoingOwnedFocus: boolean,
): void {
  const stage = stageOf(doc);
  const point = memory?.stage ?? { top: 0, left: 0 };
  stage.scrollTop = point.top;
  stage.scrollLeft = point.left;
  for (const [elementId, scroll] of memory?.internal ?? []) {
    const element = doc.getElementById(elementId);
    if (element !== null) {
      element.scrollTop = scroll.top;
      element.scrollLeft = scroll.left;
    }
  }

  const root = screenRoot(doc, id);
  if (root === null) throw new Error(`활성 제품 화면 root가 없습니다: ${id}`);
  const active = doc.activeElement as HTMLElement | null;
  const focusInHiddenScreen = active?.closest?.('.scr[hidden],.scr[inert],[aria-hidden="true"]') !== null
    && active?.closest?.('.scr[hidden],.scr[inert],[aria-hidden="true"]') !== undefined;
  if (!outgoingOwnedFocus && !focusInHiddenScreen) return;

  const remembered = memory?.focusKey === "" || memory?.focusKey === undefined
    ? null : root.querySelector<HTMLElement>(memory.focusKey);
  const target = remembered !== null && isUsableFocusTarget(remembered, root) ? remembered : root;
  target.focus({ preventScroll: true });
}

function applyShellMarkers(doc: Document, id: ProductScreenId): void {
  doc.querySelectorAll<HTMLElement>(".navbtn").forEach((button) => {
    button.setAttribute("aria-current", button.dataset.scr === id ? "true" : "false");
  });
  IMMERSIVE_SURFACES.forEach((surface) => {
    doc.body.classList.toggle(surface.cls, surface.id === id);
  });
}

export function createProductScreenExecutor(deps: ProductScreenExecutorDeps): ShellExecutor {
  const memories = new Map<ProductScreenId, ScreenMemory>();

  return {
    delegateLeave(from: string, to: string): boolean {
      return deps.lifecycle.delegateLeave(from, to);
    },

    reclaimSurfaces(): void {
      deps.reclaimSurfaces();
    },

    applyScreen(id: string): void {
      const outgoing = deps.visibility.getSnapshot();
      const captured = captureMemory(deps.doc, outgoing);
      memories.set(outgoing, captured.memory);
      flushSync(() => {
        deps.visibility.activate(id);
        applyShellMarkers(deps.doc, id as ProductScreenId);
      });
      restoreMemory(deps.doc, id as ProductScreenId, memories.get(id as ProductScreenId), captured.ownedFocus);
    },

    dispatchRefresh(id: string): Promise<unknown> {
      if (!deps.bridge.hostReady()) return Promise.resolve(null);
      return deps.bridge.call(id, "refresh", {}).then((result: any) => {
        if (result?.notice) deps.notify(String(result.notice));
        return result;
      });
    },

    notifyRefreshFailure(error: unknown): void {
      const message = error instanceof Error ? error.message : String(error);
      deps.notify(message);
    },

    rerenderEditor(): void {
      deps.lifecycle.rerender("editor");
    },
  };
}
