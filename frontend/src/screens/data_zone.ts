/* R4-01 DataZone React producer. job read support와 파일 경계를 갈라
   producer path × semantic data-* 소유권이 겹치지 않게 한다. */
import {
  createElement,
  Fragment,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { ReactNode } from "react";

import { icon } from "./icons.ts";
import { ColumnValues, useColumnPanel } from "./job_column_panel.ts";
import { FilterChipRow, isMenuKey, PresetMenu } from "./data_zone_filter_chips.ts";
import type { MenuSpec } from "./data_zone_filter_chips.ts";
import { FilterBuilder } from "./data_zone_filter_builder.ts";
import {
  blankRow, builderKeyAction, builderPlacement, createCountRequester,
  FOLD_ROW, focusFinder, focusReturnTarget, formatAmount, kindOf, pickerOptions,
  rangeFromWords, RANGE_WORDS, SEARCH_ROW,
} from "./data_zone_filter_state.ts";
import type { BuilderColumn, BuilderFocus, BuilderRow, BuilderSpec } from "./data_zone_filter_state.ts";
import { resolveHeadSelection, useOptimisticSelection } from "./data_zone_selection.ts";
import {
  renderHiddenSelectionStrip, renderRecsHead, renderTableBodyRows, renderTableHeadRow,
} from "./data_zone_table.ts";

export {
  FilterBuilder, FilterChipRow, isMenuKey,
  blankRow, builderKeyAction, builderPlacement, createCountRequester, FOLD_ROW,
  focusFinder, focusReturnTarget, formatAmount, pickerOptions, rangeFromWords, RANGE_WORDS,
  SEARCH_ROW,
};

type Obj = Record<string, any>;

export type JobReadController = {
  doc: Document;
  notify(message: string): void;
  prompt(spec: Obj): Promise<string | null>;
  confirm(spec: Obj): Promise<boolean>;
  uiModel: {
    subscribe(listener: () => void): () => void;
    getSnapshot(): Obj;
  };
  zone(action: string, payload?: Obj, returnValue?: boolean): Promise<Obj>;
  call(screen: string, action: string, payload?: Obj): Promise<Obj>;
  scheduleColumnText(column: string, value: string): void;
  scheduleSearch(value: string): void;
  /** 표를 펼침 면으로 여는 동사(U4 10번에서 이 존의 머리로 왔다 — 진입점만 이동). */
  openDataSheet(trigger: HTMLElement | null): Promise<void>;
  closeDataSheet(): void;
  discardRange(): Promise<void>;
  applyRange(): Promise<void>;
  placePopover(el: HTMLElement, anchor: HTMLElement): void;
};

export function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

function useUi(controller: JobReadController) {
  // 셋째 인자는 서버 렌더(단위 테스트의 정적 마크업)용 — 앱에서는 쓰이지 않고 같은 스냅샷을 읽는다.
  return useSyncExternalStore(
    controller.uiModel.subscribe, controller.uiModel.getSnapshot, controller.uiModel.getSnapshot,
  );
}

function asObject(value: unknown, label: string): Obj {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label}: 객체가 아닙니다.`);
  }
  return value as Obj;
}
export function columnMeta(column: unknown): Obj {
  return typeof column === "string"
    ? { name: column, kind: "text", visible: true }
    : asObject(column, "job table column");
}

/** 비교 연산자 — 열 머리 범위 편집기와 필터 빌더가 **같은 목록·같은 순서**를 쓴다. */
export const RANGE_OPS: ReadonlyArray<readonly [string, string]> = [
  ["ge", "≥"], ["gt", ">"], ["le", "≤"], ["lt", "<"], ["eq", "="], ["ne", "≠"],
];

export function Segments({ value }: { value: unknown }): ReactNode {
  if (!Array.isArray(value)) return null;
  return createElement(Fragment, null, ...value.map((segment, index) => {
    if (!Array.isArray(segment)) throw new Error("job table segment 형식이 손상됐습니다.");
    return segment[1]
      ? h("mark", { key: index }, String(segment[0] ?? ""))
      : String(segment[0] ?? "");
  }));
}

function ColumnPanel(props: {
  controller: JobReadController;
  column: string;
  data: Obj | null;
  close(): void;
  onEdit(): void;
  rootRef: { current: HTMLElement | null };
}): ReactNode {
  const { controller, column, data, close, onEdit, rootRef } = props;
  if (data === null) return h("div", { className: "colpanel react-colpanel", "aria-busy": "true", ref: rootRef },
    h("div", { className: "cp-head" }, h("span", null, `'${column}' 필터`),
      h("button", { "data-act": "panel-close", onClick: close, "aria-label": "닫기" }, "✕")),
    h("div", { className: "cp-sec cp-loading", role: "status" }, "불러오는 중…"));
  const isRange = data.kind === "amount" || data.kind === "date";
  return h("div", { className: "colpanel react-colpanel", ref: rootRef },
    h("div", { className: "cp-head" }, h("span", null, `'${column}' 필터`),
      h("button", { "data-act": "panel-close", onClick: close, "aria-label": "닫기" }, "✕")),
    isRange ? h("div", { className: "cp-sec" },
      h("span", { className: "cp-cap" }, `범위 조건(${data.kind === "amount" ? "금액" : "날짜"})`),
      ...[1, 2].map((slot) => h("div", { className: "cp-range-row", key: slot },
        h("select", { className: "field", "data-rop": slot, "data-busy-lock": true, defaultValue: slot === 1 ? data.range?.first?.op || "ge" : data.range?.second?.op || "ge" },
          ...RANGE_OPS.map(([key, label]) => h("option", { value: key, key }, label))),
        h("input", { className: "field", "data-rval": slot, "data-busy-lock": true, defaultValue: slot === 1 ? data.range?.first?.operand || "" : data.range?.second?.operand || "" }))),
      h("select", { className: "field", "data-rjoin": true, "data-busy-lock": true, defaultValue: data.range?.joiner || "and" },
        h("option", { value: "and" }, "그리고"), h("option", { value: "or" }, "또는")),
      h("div", { className: "cp-err", "data-rerr": true }),
      h("button", { className: "btn sm", "data-act": "range-apply", "data-busy-lock": true,
        onClick: (event: Obj) => {
          const root = event.currentTarget.parentElement as HTMLElement;
          const clause = (slot: number) => {
            const op = (root.querySelector(`[data-rop="${slot}"]`) as HTMLSelectElement)?.value;
            const operand = (root.querySelector(`[data-rval="${slot}"]`) as HTMLInputElement)?.value || "";
            return operand.trim() ? { op, operand } : null;
          };
          const joiner = (root.querySelector("[data-rjoin]") as HTMLSelectElement)?.value || "and";
          void controller.zone("filter_col_range", { column, first: clause(1), second: clause(2), joiner });
        } }, "범위 적용"))
      : h("div", { className: "cp-sec" }, h("span", { className: "cp-cap" }, "부분일치 검색(자모)"),
        h("input", { className: "field", "data-ctext": true, "data-busy-lock": true,
          defaultValue: data.text || "", onInput: (event: Obj) => controller.scheduleColumnText(column, event.currentTarget.value) })),
    // 「값 선택」 — 목록·체크는 Python 답 그대로, 열린 채 필터가 바뀌면 다시 물은 답으로 맞춘다(#1137).
    h(ColumnValues as any, { controller, column, data, onEdit }),
    h("div", { className: "cp-acts" },
      h("button", { className: "btn sm", "data-act": "col-clear", "data-busy-lock": true,
        onClick: () => { void controller.zone("filter_clear_col", { column }); } }, "이 열 조건 지우기"),
      data.can_hide ? h("button", { className: "btn sm", "data-act": "col-hide", "data-busy-lock": true,
        title: "보기에서만 숨깁니다. 생성에는 그대로 쓰입니다.",
        onClick: () => { close(); void controller.zone("hide_column", { column }); } }, "이 열 숨기기") : null));
}

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

/** 저장한 필터 삭제 확인 — 칩 메뉴와 빌더 「삭제」가 같은 모달을 쓴다(손실 집합 = 그 저장본 하나).
 *  지금 조건·다른 칩은 그대로라 손실로 적지 않는다. 확인하면 삭제 동사의 결과를, 취소면 null 을 준다. */
export async function deletePreset(
  controller: JobReadController, name: string, returnFocus: HTMLElement | null,
): Promise<Obj | null> {
  const accepted = await controller.confirm({
    title: "저장한 필터 삭제", body: `사라지는 것: 저장한 필터 '${name}'`,
    confirmLabel: "삭제", cancelLabel: "취소", danger: true, returnFocus,
  });
  if (!accepted) return null;
  return controller.zone("delete_filter_preset", { name });
}

export function PresetChip(props: {
  preset: Obj;
  controller: JobReadController;
  menu: MenuSpec | null;
  openMenu(name: string, trigger: HTMLElement): void;
  closeMenu(focusTrigger: boolean): void;
  onEdit(name: string, trigger: HTMLElement): void;
}): ReactNode {
  const { preset, controller, menu, openMenu, closeMenu, onEdit } = props;
  const name = String(preset.name);
  const active = !!preset.active;
  const open = menu?.name === name;
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  async function toggle(): Promise<void> {
    const result = await controller.zone("toggle_filter_preset", { name });
    if (result.stale) return;
    if (result.ok === false) controller.notify(`확인 필요: ${result.error}`);
  }
  return h("span", {
    className: `fchip preset${active ? " on" : ""}${preset.usable ? "" : " warn"}`,
    "data-preset-chip": name,
  },
  h("button", {
    className: "preset-toggle", type: "button", "data-preset": name, "data-busy-lock": true, ref: toggleRef,
    "aria-pressed": active ? "true" : "false",
    "aria-disabled": preset.usable ? undefined : "true",
    // 툴팁 = `이름: 설명`(긴 이름은 칩에서 말줄임된다). 쓸 수 없는 칩은 사유 한 문장이 진다.
    title: preset.usable ? `${name}: ${String(preset.description || "")}` : String(preset.reason || ""),
    onClick: () => { void toggle(); },
    onContextMenu: (event: Obj) => { event.preventDefault(); openMenu(name, event.currentTarget as HTMLElement); },
    onKeyDown: (event: Obj) => {
      if (!isMenuKey({ key: event.key, shiftKey: event.shiftKey, isComposing: event.nativeEvent?.isComposing })) return;
      event.preventDefault();
      openMenu(name, event.currentTarget as HTMLElement);
    },
  }, h("span", { className: "preset-name" }, name)),
  active ? h("button", {
    className: "preset-menu", type: "button", "data-preset-menu": name, "data-busy-lock": true,
    "aria-label": `${name} 필터 메뉴`, title: `${name} 필터 메뉴`, "aria-haspopup": "menu",
    "aria-expanded": open ? "true" : "false",
    onClick: (event: Obj) => {
      if (open) closeMenu(true);
      else openMenu(name, event.currentTarget as HTMLElement);
    },
  }, icon("chevron-down")) : null,
  open ? h(PresetMenu as any, {
    name,
    close: closeMenu,
    onEdit: () => {
      closeMenu(false);
      const trigger = toggleRef.current;
      if (trigger) onEdit(name, trigger);
    },
    onDelete: () => {
      const trigger = menu?.trigger || toggleRef.current;
      closeMenu(false);
      void deletePreset(controller, name, trigger).then((result) => {
        if (!result || result.stale) return;
        if (result.ok === false) { controller.notify(`확인 필요: ${result.error}`); return; }
        // 지운 칩은 사라진다 — 초점은 늘 서 있는 「+ 필터」로(빌더 「삭제」와 같은 착지).
        controller.doc.querySelector<HTMLElement>('[data-act="filter-new"]')?.focus();
      });
    },
  }) : null);
}

/* ---------------------------------------------------------------- 필터 빌더(「+ 필터」·칩 메뉴 「고치기」)
   FilterChipRow(저장한 필터 칩 줄)·FilterBuilder(「+ 필터」 면)와 그 타입·순수 헬퍼는
   data_zone_filter_chips.ts·data_zone_filter_builder.ts·data_zone_filter_state.ts가 진다.
   여기는 저장 범위·상태와 카드 행을 오가는 변환(`wordsFromRange`·`rowsFromState`·`stateFromRows`)을 둔다. */

/** 저장 범위 → 비교 말. 1절이면 그 연산자, `≥ a 그리고 < b` 면 「사이」, 그 밖은 null(기호 2절로 선다). */
export function wordsFromRange(range: Obj | null | undefined): { op: string; a: string; b: string } | null {
  if (!range || !range.first) return null;
  const first = range.first as Obj;
  const second = range.second as Obj | null | undefined;
  if (!second) return { op: String(first.op || "lt"), a: String(first.operand ?? ""), b: "" };
  if (first.op === "ge" && second.op === "lt" && (range.joiner || "and") === "and") {
    return { op: "between", a: String(first.operand ?? ""), b: String(second.operand ?? "") };
  }
  return null;
}

/** 저장본(또는 지금 조건) → 빌더 카드. 한 열에 범위·값 목록·글자가 겹쳐 있으면 카드를 나눠 전부
 *  싣는다 — 빌더가 그릴 수 없는 조건을 조용히 버리면 저장이 정의를 바꾼다. */
export function rowsFromState(state: Obj | null | undefined, columns: BuilderColumn[]): BuilderRow[] {
  const rows: BuilderRow[] = [];
  let id = 0;
  const conditions = state && state.columns && typeof state.columns === "object" ? state.columns as Obj : {};
  for (const [column, raw] of Object.entries(conditions)) {
    const cond = (raw || {}) as Obj;
    const base = (): BuilderRow => blankRow(++id, column, kindOf(columns, column));
    if (cond.range) {
      const range = cond.range as Obj;
      const words = wordsFromRange(range);
      rows.push(words
        ? { ...base(), mode: "range", ...words }
        : {
          ...base(), mode: "range",
          legacy: {
            first: { op: String(range.first?.op || "ge"), operand: String(range.first?.operand ?? "") },
            second: { op: String(range.second?.op || "ge"), operand: String(range.second?.operand ?? "") },
            joiner: String(range.joiner || "and"),
          },
        });
    }
    if (Array.isArray(cond.values)) rows.push({ ...base(), mode: "values", values: cond.values.map(String) });
    if (typeof cond.text === "string" && cond.text.trim()) rows.push({ ...base(), mode: "text", text: cond.text });
  }
  const search = typeof state?.search === "string" ? state.search : "";
  if (search.trim()) rows.push({ ...blankRow(++id, SEARCH_ROW, ""), text: search });
  return rows;
}

/** 빌더 카드 → 상태(`export_state` 의 지금 조건 모양). 빈 카드(값 없음·고른 값 없음·빈 글자)는
 *  조건이 아니다. `pruned` 는 프리필한 검색어가 그대로일 때만 잇는다(쳐낸 가지 = 검색 텍스트 수명). */
export function stateFromRows(rows: BuilderRow[], pruned: string[] = []): Obj {
  const columns: Obj = {};
  let search = "";
  for (const row of rows) {
    if (row.mode === "search") { search = row.text.trim(); continue; }
    if (!row.column) continue;
    const cond = (columns[row.column] ||= { text: "", values: null, range: null }) as Obj;
    if (row.mode === "range") {
      if (row.legacy) {
        if (!row.legacy.first.operand.trim()) continue;
        cond.range = {
          first: { ...row.legacy.first },
          second: row.legacy.second.operand.trim() ? { ...row.legacy.second } : null,
          joiner: row.legacy.joiner,
        };
      } else {
        const range = rangeFromWords(row.op, row.a, row.b);
        if (range) cond.range = range;
      }
    } else if (row.mode === "values") {
      if (row.values.length) cond.values = [...row.values];
    } else if (row.text.trim()) {
      cond.text = row.text;
    }
  }
  for (const [column, cond] of Object.entries(columns)) {
    if ((cond as Obj).values === null && !(cond as Obj).text && !(cond as Obj).range) delete columns[column];
  }
  return { columns, search, pruned: search ? [...pruned] : [] };
}

/** 콤보박스 키 하나 — ↑↓ 는 고른 줄을 돌리고, Enter 는 고른 줄(없으면 첫 줄)을 택하고, Escape 는
 *  목록이 열려 있으면 목록만 닫는다(빌더는 닫지 않는다). 한글 조합 중에는 아무 뜻도 없다. */
export function pickerKey(
  event: { key: string; isComposing?: boolean; keyCode?: number },
  state: { open: boolean; active: number; count: number },
): { active: number; open: boolean; choose: number | null; handled: boolean } {
  const none = { active: state.active, open: state.open, choose: null, handled: false };
  if (event.isComposing || event.keyCode === 229) return none;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    if (!state.count) return { ...none, open: true, handled: true };
    const step = event.key === "ArrowDown" ? 1 : -1;
    const from = state.open ? state.active : (step > 0 ? -1 : state.count);
    return { active: (from + step + state.count) % state.count, open: true, choose: null, handled: true };
  }
  if (event.key === "Enter") {
    if (!state.open || !state.count) return none;
    return { active: state.active, open: false, choose: state.active >= 0 ? state.active : 0, handled: true };
  }
  if (event.key === "Escape" && state.open) return { active: -1, open: false, choose: null, handled: true };
  return none;
}

type PendingFocus = { find(): HTMLElement | null; until: number };

/** 필터 빌더(「+ 필터」·칩 메뉴 「고치기」) 슬롯 — 열 머리 패널과 같은 배치·같은 트리거 ref
 *  규칙이다. 여는 순간 패널을 닫는다(`closePanel`); 패널이 열리면 이 빌더를 닫는 쪽은
 *  `closeSilently`(판정 없는 생 setter — `closeBuilder`의 포커스 예약 없이). 닫은 뒤의 초점
 *  옮기기는 `usePendingBuilderFocus`가 한다. */
function useFilterBuilderSlot(
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
function usePendingBuilderFocus(pendingFocus: { current: PendingFocus | null }): void {
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
function useSyncSearchQuery(controller: JobReadController, filterSearch: unknown, setQuery: (text: string) => void): void {
  useEffect(() => {
    if (controller.doc.activeElement?.id !== "jobFilterSearch") setQuery(String(filterSearch || ""));
  }, [filterSearch, controller]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** 표 틀을 시트로 열고 닫아도 스크롤 자리를 되돌린다. */
function useRestoreScrollTop(wrapRef: { current: HTMLDivElement | null }, ui: Obj): void {
  useEffect(() => {
    if (wrapRef.current) wrapRef.current.scrollTop = ui.tableScrollTop;
  }, [ui.sheetOpen, ui.tableScrollTop]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** 열 머리 패널을 **그린 뒤** 잰다 — `Popover.place` 는 실제 렌더 크기로 viewport clamp·
 *  flip 을 하므로 측정 전에는 답을 낼 수 없다. */
function usePanelPlacement(
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

/** 표가 빈 자리에 서는 안내 — 데이터 없음·필터 불일치·행 없음 셋을 가른다. */
function emptyTableMessage(snapshot: Obj, filter: Obj): string {
  if (!snapshot.has_data) return "데이터를 선택하면 생성 대상 문서가 여기에 표시됩니다.";
  if (filter.active) return "필터와 일치하는 행이 없습니다. 위 칩의 정의를 확인하세요.";
  return "데이터에 행이 없습니다.";
}

/** 스냅샷의 필터·표 존 — 둘 다 없으면 빈 기본값(아직 데이터가 없는 작업). */
function resolveZoneData(snapshot: Obj): { filter: Obj; table: Obj } {
  const filter = snapshot.filter || { active: false, search: "", columns: [] };
  const table = snapshot.table || { columns: [], rows: [], visible_count: 0, hidden_selected: [], hidden_columns: [] };
  return { filter, table };
}

/** 「표 크게 열기」 — 표 오른쪽 위 모서리의 그림 단추(U4 10번의 표를 여는 동사). 스크롤하는 표 안이
 *  아니라 표 틀(`.jobtb-host`)에 붙어 가로 스크롤에도 제자리다. **시트 안에서는 그리지 않는다** —
 *  자기 자신을 여는 단추는 무동작이고, 닫는 동사는 면 footer 의 취소·적용이 이미 진다. */
function renderExpandButton(sheetOpen: boolean, snapshot: Obj, controller: JobReadController): ReactNode {
  return !sheetOpen ? h("button", {
    className: "jobtb-expand", id: "jobDataExpand", type: "button", hidden: !snapshot.has_data,
    "aria-label": "표 크게 열기", title: "표 크게 열기",
    onClick: (event: Obj) => { void controller.openDataSheet(event.currentTarget); },
  }, icon("expand")) : null;
}

/** 열 머리 패널 — 열려 있을 때만 선다. */
function renderColumnPanelOverlay(props: {
  panel: Obj | null; controller: JobReadController; closePanel(): void; markPanelEdit(): void;
  panelRoot: { current: HTMLElement | null };
}): ReactNode {
  const { panel, controller, closePanel, markPanelEdit, panelRoot } = props;
  return panel
    ? h(ColumnPanel as any, {
      controller, column: panel.column, data: panel.data, close: closePanel,
      onEdit: markPanelEdit, rootRef: panelRoot,
    })
    : null;
}

/** 필터 빌더 — 열 머리 패널과 같은 자리(`position:fixed` 부유 면)라 스크롤 표·칩 줄의 overflow 에
 *  잘리지 않는다. 열린 명세마다 새로 마운트해(key) 프리필이 이전 빌더의 입력을 잇지 않는다. */
function renderFilterBuilderOverlay(props: {
  snapshot: Obj; builder: BuilderSpec | null; controller: JobReadController; filter: Obj;
  builderTrigger: { current: HTMLElement | null }; builderRoot: { current: HTMLElement | null };
  closeBuilder(focus: BuilderFocus): void;
}): ReactNode {
  const { snapshot, builder, controller, filter, builderTrigger, builderRoot, closeBuilder } = props;
  return snapshot.has_data && builder
    ? h(FilterBuilder as any, {
      key: `${builder.mode}:${builder.name}`, controller, filter, spec: builder,
      trigger: builderTrigger, rootRef: builderRoot, close: closeBuilder,
    })
    : null;
}

/** 문서 만들기의 데이터 존 — 머리 줄·저장한 필터 칩 줄·표·필터 밖 선택·범위 바닥. 효과 훅은
 *  선언 순서대로 돌므로(검색 되맞춤 → 스크롤 복원 → 낙관 선택 정리 → 빌더 초점) 부르는 순서를 지킨다. */
export function JobDataZone(props: {
  snapshot: Obj;
  controller: JobReadController;
  scroll: any;
  tabs?: ReactNode;
}): ReactNode {
  const { snapshot, controller, scroll: Scroll } = props;
  const { filter, table } = resolveZoneData(snapshot);
  const [query, setQuery] = useState(String(filter.search || ""));
  // 팝오버는 **누른 자리** 아래에 선다(U4 계열1-9). 트리거는 ref 로 든다 — 상태에 넣으면
  // 배치 한 번에 재렌더가 한 번 더 붙는다.
  const panelRoot = useRef<HTMLElement | null>(null);
  const panelTrigger = useRef<HTMLElement | null>(null);
  // 열 머리 패널 — 열기·열린 채 다시 묻기·값 누름 표지(job_column_panel.ts). 여는 순간 빌더를 닫는다.
  // (패널·빌더는 서로를 닫아야 해 상호 참조한다 — `closeBuilderRef`가 그 순환을 느슨하게 묶는다.)
  const closeBuilderRef = useRef<() => void>(() => {});
  const { panel, setPanel, open: openPanel, edited: markPanelEdit } = useColumnPanel(
    controller, snapshot, panelTrigger, () => closeBuilderRef.current(),
  );
  // 필터 빌더(「+ 필터」·칩 메뉴 「고치기」) — 열 머리 패널과 같은 배치·같은 트리거 ref 규칙.
  const { builder, builderRoot, builderTrigger, pendingFocus, openBuilder, closeBuilder, closeSilently } =
    useFilterBuilderSlot(controller, () => setPanel(null));
  closeBuilderRef.current = closeSilently;
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const ui = useUi(controller);
  useSyncSearchQuery(controller, filter.search, setQuery);
  useRestoreScrollTop(wrapRef, ui);
  const { selectedFor, toggleRow } = useOptimisticSelection(controller, table.rows);
  usePanelPlacement(controller, panel, panelRoot, panelTrigger);
  usePendingBuilderFocus(pendingFocus);

  const hidden = table.hidden_selected || [];
  const hiddenColumns = table.hidden_columns || [];
  const visibleRows = (table.rows || []) as Obj[];
  const { headChecked, headPartial, headSelectLabel } = resolveHeadSelection(visibleRows, hidden, filter, selectedFor);
  return createElement(Fragment, null,
    renderRecsHead({
      snapshot, filter, table, query, controller,
      onQueryChange: (text) => { setQuery(text); controller.scheduleSearch(text); },
    }),
    // (구 `#jobOrderBar` 의 상시 재진술은 간소화 라운드에서 걷혔다 — 표가 그리는 순서가
    // 곧 생성 순서라는 사실은 스위치 자신의 title 이 말한다.)
    // 칩 줄은 데이터가 있으면 늘 선다 — 「+ 필터」가 여기 산다(필터가 없어도 만들 수 있어야 한다).
    h(FilterChipRow as any, {
      filter, hasData: !!snapshot.has_data, hiddenColumns, controller, builder,
      onNew: (trigger: HTMLElement) => openBuilder({ mode: "create", name: "" }, trigger),
      onEdit: (name: string, trigger: HTMLElement) => openBuilder({ mode: "edit", name }, trigger),
    }),
    h("div", { className: "jobtb-host", id: "jobTableHost" },
      h(Scroll, { wrapRef, hidden: !snapshot.has_data },
        h("table", { className: "tb jobtb" },
          h("thead", { id: "jobTableHead" },
            renderTableHeadRow({
              table, filter, headChecked, headPartial, headSelectLabel,
              panelColumn: panel?.column, controller, openPanel,
            })),
          h("tbody", { id: "jobTableBody" },
            ...renderTableBodyRows({ table, selectedFor, toggleRow })))),
      props.tabs,
      h("div", {
        className: "job-empty muted",
        id: "jobTableEmpty",
        hidden: snapshot.has_data && (table.rows || []).length > 0,
      }, emptyTableMessage(snapshot, filter)),
      // 「표 크게 열기」는 데이터가 없으면 표처럼 숨는다(노드는 선다 — 범위 편집기 거절 경로의 겨눔 좌표다).
      renderExpandButton(ui.sheetOpen, snapshot, controller),
      renderColumnPanelOverlay({
        panel, controller, closePanel: () => setPanel(null), markPanelEdit, panelRoot,
      }),
      renderFilterBuilderOverlay({ snapshot, builder, controller, filter, builderTrigger, builderRoot, closeBuilder })),
    renderHiddenSelectionStrip({ snapshot, hidden, controller }),
    h(RangeFooter as any, { snapshot, controller }));
}

function RangeFooter(props: { snapshot: Obj; controller: JobReadController }): ReactNode {
  const draft = props.snapshot.range_draft || {};
  // (구 `#jobRangeNote` 범위 안내문은 간소화 라운드에서 걷혔다 — 「선택된 항목만 보기」의
  // 눌림 상태가 보기 범위를 말하고, 적용 전임은 「선택 적용」 단추 자신이 말한다.)
  return h("div", { className: "range-foot", id: "jobRangeFoot" },
    h("button", { className: "btn", id: "jobRangeSelectedOnly", type: "button", "aria-pressed": draft.selected_only ? "true" : "false",
      "data-busy-lock": true, onClick: () => { void props.controller.call("job", "set_selected_only", { value: !draft.selected_only }); } }, "선택된 항목만 보기"),
    h("button", { className: "btn", id: "jobRangeCancel", type: "button", "data-busy-lock": true,
      onClick: () => { props.controller.closeDataSheet(); } }, "취소"),
    h("button", { className: "btn primary", id: "jobRangeApply", type: "button", "data-busy-lock": true,
      onClick: () => { void props.controller.applyRange(); } }, `선택 적용: ${draft.sel_count || 0}건`));
}
