/* R4-01 DataZone 의 효과 훅 — 필터 빌더 슬롯(열기·닫기·닫은 뒤 초점), 검색창 되맞춤, 표 스크롤
   복원, 열 머리 패널 배치. `JobDataZone`이 선언 순서대로 부른다(효과는 그 순서로 돈다). */
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import type { JobReadController } from "./data_zone.ts";
import { focusFinder } from "./data_zone_filter_state.ts";
import type { BuilderFocus, BuilderSpec } from "./data_zone_filter_state.ts";

type Obj = Record<string, any>;

export type PendingFocus = { find(): HTMLElement | null; until: number };

/** 필터 빌더(「+ 필터」·칩 메뉴 「고치기」) 슬롯 — 열 머리 패널과 같은 배치·같은 트리거 ref
 *  규칙이다. 여는 순간 패널을 닫는다(`closePanel`); 패널이 열리면 이 빌더를 닫는 쪽은
 *  `closeSilently`(판정 없는 생 setter — `closeBuilder`의 포커스 예약 없이). 닫은 뒤의 초점
 *  옮기기는 `usePendingBuilderFocus`가 한다. */
export function useFilterBuilderSlot(
  controller: JobReadController, closePanel: () => void,
): {
  builder: BuilderSpec | null;
  builderRoot: { current: HTMLElement | null };
  builderTrigger: { current: HTMLElement | null };
  pendingFocus: { current: PendingFocus | null };
  openBuilder(spec: BuilderSpec, trigger: HTMLElement): void;
  closeBuilder(focus: BuilderFocus): void;
  closeSilently(): void;
} {
  const [builder, setBuilder] = useState<BuilderSpec | null>(null);
  const builderRoot = useRef<HTMLElement | null>(null);
  const builderTrigger = useRef<HTMLElement | null>(null);
  const pendingFocus = useRef<PendingFocus | null>(null);

  function closeBuilder(focus: BuilderFocus): void {
    const find = focusFinder(focus, builderTrigger.current, controller.doc);
    setBuilder(null);
    // 칩 줄은 저장 뒤의 push 로 다시 그려진다 — 고친 칩(새 이름)·「+ 필터」가 **선 뒤에** 초점을
    // 옮기도록 찾을 자리를 걸어 두고 렌더마다 찾는다(잠깐 뒤엔 포기 — 늦게 나타난 요소가 초점을 훔치지 않게).
    pendingFocus.current = find ? { find, until: Date.now() + 2000 } : null;
  }

  function openBuilder(spec: BuilderSpec, trigger: HTMLElement): void {
    const same = builder && builder.mode === spec.mode && builder.name === spec.name;
    if (same) { closeBuilder("trigger"); return; }
    closePanel();
    pendingFocus.current = null;
    builderTrigger.current = trigger;
    setBuilder(spec);
  }

  return {
    builder, builderRoot, builderTrigger, pendingFocus, openBuilder, closeBuilder,
    closeSilently: () => setBuilder(null),
  };
}

/** 빌더를 닫으며 걸어 둔 초점 자리를 렌더마다 찾아 옮긴다 — 존의 다른 효과가 모두 돈 뒤 마지막에 돈다. */
export function usePendingBuilderFocus(pendingFocus: { current: PendingFocus | null }): void {
  useEffect(() => {
    const pending = pendingFocus.current;
    if (pending === null) return;
    if (Date.now() > pending.until) { pendingFocus.current = null; return; }
    const target = pending.find();
    if (target) {
      pendingFocus.current = null;
      target.focus();
    }
  });
}

/** 검색창에 초점이 없을 때만 필터 값으로 되맞춘다 — 치는 중에 덮어쓰지 않는다. */
export function useSyncSearchQuery(controller: JobReadController, filterSearch: unknown, setQuery: (text: string) => void): void {
  useEffect(() => {
    if (controller.doc.activeElement?.id !== "jobFilterSearch") setQuery(String(filterSearch || ""));
  }, [filterSearch, controller]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** 표 틀을 시트로 열고 닫아도 스크롤 자리를 되돌린다. */
export function useRestoreScrollTop(wrapRef: { current: HTMLDivElement | null }, ui: Obj): void {
  useEffect(() => {
    if (wrapRef.current) wrapRef.current.scrollTop = ui.tableScrollTop;
  }, [ui.sheetOpen, ui.tableScrollTop]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** 열 머리 패널을 **그린 뒤** 잰다 — `Popover.place` 는 실제 렌더 크기로 viewport clamp·
 *  flip 을 하므로 측정 전에는 답을 낼 수 없다. */
export function usePanelPlacement(
  controller: JobReadController, panel: Obj | null,
  panelRoot: { current: HTMLElement | null }, panelTrigger: { current: HTMLElement | null },
): void {
  useLayoutEffect(() => {
    const root = panelRoot.current;
    const trigger = panelTrigger.current;
    if (!panel || !root || !trigger) return;
    controller.placePopover(root, trigger);
  }, [controller, panel]); // eslint-disable-line react-hooks/exhaustive-deps
}
