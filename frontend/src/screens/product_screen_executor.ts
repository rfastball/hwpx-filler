/* R4-04 화면 집행자 — shellNav 판정은 그대로 두고 React visibility 효과만 인수한다. */
import { flushSync } from "react-dom";

import { IMMERSIVE_SURFACES } from "../shell/nav.ts";
import type { ShellExecutor } from "../shell/nav.ts";
import { PRODUCT_SCREEN_IDS } from "./product_screens.ts";
import type { ProductScreenId, ProductScreenVisibility } from "./product_screens.ts";
import type { ScreenLifecycleRegistry } from "./screen_lifecycle_registry.ts";

type ScrollPoint = { top: number; left: number };
type FocusMemory = { kind: "id" | "data-focus-key"; value: string } | null;
type ScreenMemory = {
  stage: ScrollPoint;
  internal: ReadonlyMap<string, ScrollPoint>;
  focus: FocusMemory;
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

function focusMemoryOf(element: Element): FocusMemory {
  if (element.id !== "") return { kind: "id", value: element.id };
  const key = (element as HTMLElement).dataset?.focusKey;
  return key === undefined || key === "" ? null : { kind: "data-focus-key", value: key };
}

function rememberedFocus(root: HTMLElement, doc: Document, focus: FocusMemory): HTMLElement | null {
  if (focus === null) return null;
  if (focus.kind === "id") return doc.getElementById(focus.value) as HTMLElement | null;
  for (const element of root.querySelectorAll<HTMLElement>("[data-focus-key]")) {
    if (element.dataset.focusKey === focus.value) return element;
  }
  return null;
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
  const focus = ownedFocus && active !== null ? focusMemoryOf(active) : null;
  const internal = new Map<string, ScrollPoint>();
  root?.querySelectorAll<HTMLElement>("[id][data-preserve-scroll]").forEach((element) => {
    internal.set(element.id, { top: element.scrollTop, left: element.scrollLeft });
  });
  return {
    ownedFocus,
    memory: {
      stage: { top: stage.scrollTop, left: stage.scrollLeft },
      internal,
      focus,
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
  if (root === null) {
    /* app shell은 React root에 ShellHost를 넘기기 위해 먼저 구성되고, 그 구성 중 기본 화면을
       한 번 적용한다. 이때 stage는 아직 첫 commit 전이라 네 root가 모두 없는 것이 정상이다.
       visibility/셸 marker는 위에서 기록해 첫 render가 같은 판정을 읽게 하고 focus만 미룬다.
       하나라도 mounted된 뒤 목적 root만 없으면 부분 트리이므로 계속 fail-closed한다. */
    const beforeFirstCommit = PRODUCT_SCREEN_IDS.every((screen) => screenRoot(doc, screen) === null);
    if (beforeFirstCommit) return;
    throw new Error(`활성 제품 화면 root가 없습니다: ${id}`);
  }
  const active = doc.activeElement as HTMLElement | null;
  const focusInHiddenScreen = active?.closest?.('.scr[hidden],.scr[inert],[aria-hidden="true"]') !== null
    && active?.closest?.('.scr[hidden],.scr[inert],[aria-hidden="true"]') !== undefined;
  if (!outgoingOwnedFocus && !focusInHiddenScreen) return;
  /* 목적 화면이 **이미 자기 안에** 초점을 세웠으면 되돌릴 것이 없다.

     이 복원의 근거는 「나가는 화면이 초점을 들고 있었으니 들어오는 화면에 시작점을 준다」다.
     그런데 들어오는 화면이 스스로 자리를 잡았다면 초점은 고아가 아니고, 여기서 덮으면 그
     화면이 방금 지목한 자리를 빼앗는다 — deep-link 조준이 정확히 그 형상이다(#795). */
  if (active !== null && active !== doc.body && root.contains(active)) return;

  const remembered = rememberedFocus(root, doc, memory?.focus ?? null);
  const target = remembered !== null && isUsableFocusTarget(remembered, root) ? remembered : root;
  target.focus({ preventScroll: true });
}

function applyShellMarkers(doc: Document, id: ProductScreenId): void {
  doc.querySelectorAll<HTMLElement>(".navbtn").forEach((button) => {
    button.setAttribute("aria-current", button.dataset.scr === id ? "true" : "false");
  });
  IMMERSIVE_SURFACES.forEach((surface) => {
    if (surface.id === "editor" && surface.cls === "editor-open") {
      doc.body.classList.toggle("editor-open", id === surface.id);
      return;
    }
    if (surface.id === "workbench" && surface.cls === "workbench-open") {
      doc.body.classList.toggle("workbench-open", id === surface.id);
      return;
    }
    throw new Error(`지원하지 않는 몰입 화면 표지입니다: ${surface.id}/${surface.cls}`);
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
