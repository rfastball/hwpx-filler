/* R4-01 DataZone 저장한 필터 칩 줄(`FilterChipRow`) — 열 조건 지우기·정리·숨긴 열 되살리기는
   `controller.zone("filter_clear_col"/"filter_prune"/"unhide_columns", …)`가 한다. 칩 하나
   (`PresetChip`)는 data_zone.ts가 그리고, 그 칩이 여는 메뉴(`PresetMenu`)·메뉴 키 판정
   (`isMenuKey`)은 여기 둔다. */
import { createElement, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { roveFocus } from "./authoring_a11y.ts";
import { PresetChip } from "./data_zone.ts";
import type { JobReadController } from "./data_zone.ts";
import type { BuilderSpec } from "./data_zone_filter_state.ts";

type Obj = Record<string, any>;

function h(tag: any, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

export type MenuSpec = { name: string; trigger: HTMLElement | null };

/* 저장한 필터 칩 줄(2026-09-30 재설계) — 판정(켜짐·사용 가부·사유·차원·무리·조건 문안·저장 가부)은
   전부 Python 이 싣고, 여기는 그리기와 동사 호출만 한다.

   - 줄은 세 칸 격자다: 「저장한 필터」 머리표 | 칩 영역 | 「+ 필터」. 칩 영역만 줄을 바꾸고(둘째 줄은
     첫 칩 시작선에 맞는다), 「+ 필터」는 칩 수와 무관하게 첫 줄 오른쪽에 선다.
   - 같은 차원(같은 열)을 보는 칩이 둘 이상이면 **무리**(알약 묶음 + 열 이름 표지)로 선다 — 무리 안은
     「또는」, 무리 사이는 「그리고」라는 합성 규칙을 모양이 말한다. 홀로 선 칩은 묶지 않는다.
   - 칩은 이름 하나를 든 `<button aria-pressed>` 이고, 조건 문안은 Python 이 지은 `description` 을
     `title` 로 싣는다. 켜진 칩에만 ▾ 메뉴 단추(「고치기」·「삭제」)가 선다 — 꺼진 칩은 빈자리를
     남기지 않는다. 어느 칩이든 문맥 메뉴 동작(오른쪽 누름·Shift+F10·메뉴 키)이 같은 메뉴를 연다.
   - 쓸 수 없는 칩도 눌리게 두고(aria-disabled) 거절은 백엔드 사유를 그대로 알린다 — 비활성
     단추는 사유를 말할 자리가 없다. */

/** 칩에서 메뉴를 여는 키인가 — Shift+F10·메뉴 키(APG 문맥 메뉴). 한글 조합 중에는 아니다. */
export function isMenuKey(event: { key: string; shiftKey?: boolean; isComposing?: boolean }): boolean {
  if (event.isComposing) return false;
  return event.key === "ContextMenu" || (event.key === "F10" && !!event.shiftKey);
}

export function PresetMenu(props: {
  name: string;
  close(focusTrigger: boolean): void;
  onEdit(): void;
  onDelete(): void;
}): ReactNode {
  const { name, close, onEdit, onDelete } = props;
  const root = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    root.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    const doc = root.current?.ownerDocument;
    if (!doc) return;
    function onDown(event: MouseEvent): void {
      const target = event.target as Node | null;
      if (target && root.current?.parentElement?.contains(target)) return;
      closeRef.current(false); // 바깥 누름은 누른 자리가 초점을 가진다
    }
    doc.addEventListener("mousedown", onDown, true);
    return () => doc.removeEventListener("mousedown", onDown, true);
  }, []);
  return h("div", {
    className: "ctx-menu preset-pop", role: "menu", ref: root, "aria-label": `${name} 필터 메뉴`,
    "data-preset-pop": name,
    onKeyDown: (event: Obj) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(true); return; }
      if (event.key === "Tab") { close(false); return; }
      roveFocus(event as any, event.currentTarget, '[role="menuitem"]', "vertical");
    },
  },
  h("button", {
    type: "button", role: "menuitem", tabIndex: -1, "data-preset-act": "edit", "data-busy-lock": true,
    onClick: onEdit,
  }, "고치기"),
  h("button", {
    type: "button", role: "menuitem", tabIndex: -1, className: "danger", "data-preset-act": "delete",
    "data-busy-lock": true, onClick: onDelete,
  }, "삭제"));
}

/** 저장한 필터 무리 — 같은 차원(같은 열)을 보는 칩이 둘 이상이면 알약 묶음 + 열 이름 표지로,
 *  홀로 선 칩은 묶지 않는다. */
function renderPresetGroups(groups: Obj[], byName: Map<string, Obj>, chip: (preset: Obj) => ReactNode): ReactNode[] {
  return groups.map((group: Obj) => {
    const members = ((group.names || []) as string[])
      .map((name) => byName.get(String(name))).filter(Boolean) as Obj[];
    if (members.length < 2) return members.length ? chip(members[0]) : null;
    return h("span", {
      className: "fcluster", role: "group", key: `g-${group.key}`,
      "data-dimension": String(group.key), "aria-label": String(group.label),
    },
    h("span", { className: "fcluster-label", "aria-hidden": "true" }, String(group.label)),
    ...members.map(chip));
  });
}

/** 열 머리에서 세운 지금 조건 — 저장한 필터와 갈라 읽히게 「열 조건」으로 부른다. × 는 그 열의
 *  조건만 지운다(검색 칩은 검색창이 편집기라 × 가 없다). 문안은 Python 정의줄 조각 그대로. */
function renderColumnConditionChips(chips: Obj[], controller: JobReadController): ReactNode[] {
  return chips.map((item: Obj, index: number) => h("span", {
    className: "fchip definition", key: `c-${index}`, title: String(item.text || ""),
    "data-chip-column": item.column ? String(item.column) : undefined,
  },
  h("span", { className: "chip-role" }, "열 조건"),
  h("span", { className: "chip-text" }, String(item.text || "")),
  item.column ? h("button", {
    type: "button", "data-clear-col": String(item.column), "data-busy-lock": true,
    "aria-label": `${item.column} 열 조건 지우기`,
    onClick: () => { void controller.zone("filter_clear_col", { column: String(item.column) }); },
  }, "×") : null));
}

function renderBranchChips(branches: string[], controller: JobReadController): ReactNode[] {
  return branches.map((branch: string) => h("span", { className: "fchip branch", key: `b-${branch}` },
    h("span", { className: "chip-role" }, "가지"), branch,
    h("button", { "data-prune": branch, "data-busy-lock": true, "aria-label": `${branch} 가지 제거`,
      onClick: () => { void controller.zone("filter_prune", { column: branch }); } }, "×")));
}

function renderHiddenColumnsChip(hiddenColumns: string[], controller: JobReadController): ReactNode {
  if (!hiddenColumns.length) return null;
  return h("span", { className: "fchip hidecols", title: hiddenColumns.join(", "), key: "hidecols" },
    h("span", { className: "chip-role" }, "보기"), `열 ${hiddenColumns.length}개 숨김 — 생성에는 그대로 쓰입니다`,
    h("button", { "data-act": "unhide-cols", "data-busy-lock": true, "aria-label": "숨긴 열 모두 표시",
      onClick: () => { void controller.zone("unhide_columns", {}); } }, "×"));
}

/** 「+ 필터」 — 저장할 곳(등록 데이터)이 없으면 눌러도 사유를 알린다(판정·사유는 Python). */
function renderNewFilterButton(
  builder: BuilderSpec | null, source: Obj, controller: JobReadController, onNew: (trigger: HTMLElement) => void,
): ReactNode {
  return h("button", {
    className: "btn sm fnew", type: "button", "data-act": "filter-new", "data-busy-lock": true, key: "new",
    "aria-haspopup": "dialog", "aria-expanded": builder?.mode === "create" ? "true" : "false",
    "aria-disabled": source.can_create === false ? "true" : undefined,
    title: source.can_create === false ? String(source.reason || "") : undefined,
    onClick: (event: Obj) => {
      if (source.can_create === false) {
        controller.notify(`확인 필요: ${source.reason}`);
        return;
      }
      onNew(event.currentTarget as HTMLElement);
    },
  }, "+ 필터");
}

/** 칩 줄이 읽는 필터 뷰 — 칩·가지는 필터가 꺼져 있으면 보이지 않는다(열 조건은 필터가 서야
 *  뜻이 있다). 네 `||` 기본값·두 조건부를 한 자리로 모은다. */
function readFilterView(
  filter: Obj,
): { presets: Obj[]; groups: Obj[]; source: Obj; chips: Obj[]; branches: string[] } {
  return {
    presets: (filter.presets || []) as Obj[],
    groups: (filter.preset_groups || []) as Obj[],
    source: (filter.builder || {}) as Obj,
    chips: filter.active ? (filter.chips || []) as Obj[] : [],
    branches: filter.active ? (filter.branches || []) as string[] : [],
  };
}

export function FilterChipRow(props: {
  filter: Obj;
  hasData: boolean;
  hiddenColumns: string[];
  controller: JobReadController;
  builder: BuilderSpec | null;
  onNew(trigger: HTMLElement): void;
  onEdit(name: string, trigger: HTMLElement): void;
}): ReactNode {
  const { filter, hasData, hiddenColumns, controller, builder, onNew, onEdit } = props;
  const [menu, setMenu] = useState<MenuSpec | null>(null);
  const { presets, groups, source, chips, branches } = readFilterView(filter);
  const byName = new Map(presets.map((preset) => [String(preset.name), preset]));
  const tail = chips.length + branches.length + (hiddenColumns.length ? 1 : 0);
  const openMenu = (name: string, trigger: HTMLElement) => setMenu({ name, trigger });
  const closeMenu = (focusTrigger: boolean) => {
    const trigger = menu?.trigger;
    setMenu(null);
    if (focusTrigger && trigger && trigger.isConnected) trigger.focus();
  };
  const chip = (preset: Obj) => h(PresetChip as any, {
    key: `p-${preset.name}`, preset, controller, onEdit, openMenu, closeMenu,
    menu: menu && byName.has(menu.name) ? menu : null,
  });
  return h("div", { className: `fchips${presets.length ? "" : " nocap"}`, id: "jobFilterChips", hidden: !hasData },
    presets.length ? h("span", { className: "fchips-cap", key: "preset-cap" }, "저장한 필터") : null,
    h("div", { className: "fchips-area", key: "area" },
      ...renderPresetGroups(groups, byName, chip),
      presets.length && tail ? h("span", { className: "fchips-sep", "aria-hidden": "true", key: "sep" }) : null,
      ...renderColumnConditionChips(chips, controller),
      ...renderBranchChips(branches, controller),
      renderHiddenColumnsChip(hiddenColumns, controller)),
    renderNewFilterButton(builder, source, controller, onNew));
}
