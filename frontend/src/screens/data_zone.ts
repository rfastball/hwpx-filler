/* R4-01 DataZone React producer. job read support와 파일 경계를 갈라
   producer path × semantic data-* 소유권이 겹치지 않게 한다. */
import {
  createElement,
  Fragment,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { ReactNode } from "react";

import { icon } from "./icons.ts";
import { ColumnValues, useColumnPanel } from "./job_column_panel.ts";
import { renderPickerOption, useFilterColumnQuery } from "./data_zone_card_editor.ts";
import {
  isMenuKey, PresetMenu, readFilterView, renderBranchChips, renderColumnConditionChips,
  renderHiddenColumnsChip, renderNewFilterButton, renderPresetGroups,
} from "./data_zone_filter_chips.ts";
import type { MenuSpec } from "./data_zone_filter_chips.ts";
import {
  buildCardList, createBuilderEdits, deletePreset, renderFbFoot, renderFbHead, renderUnplacedError,
  resolveCountSummary, resolveFailureCard, resolvePrunedSearch, useFilterBuilderDismiss,
  useFilterBuilderPlacement, useFilterCount, useFocusNewRow,
} from "./data_zone_filter_builder.ts";
import {
  blankRow, builderKeyAction, builderPlacement, createCountRequester,
  FOLD_ROW, focusFinder, focusReturnTarget, formatAmount, kindOf, pickerOptions,
  rangeFromWords, RANGE_OPS, RANGE_WORDS, SEARCH_ROW,
} from "./data_zone_filter_state.ts";
import type { BuilderColumn, BuilderFocus, BuilderRow, BuilderSpec } from "./data_zone_filter_state.ts";
import {
  usePanelPlacement, usePendingBuilderFocus, useFilterBuilderSlot, useRestoreScrollTop, useSyncSearchQuery,
} from "./data_zone_hooks.ts";
import { resolveHeadSelection, useOptimisticSelection } from "./data_zone_selection.ts";
import {
  emptyTableMessage, renderExpandButton, renderHiddenSelectionStrip, renderRecsHead, renderTableBodyRows,
  renderTableHeadRow,
} from "./data_zone_table.ts";

export {
  deletePreset, isMenuKey, RANGE_OPS,
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
   저장 범위·상태와 카드 행을 오가는 변환(`wordsFromRange`·`rowsFromState`·`stateFromRows`)과 열 고르기
   키 판정(`pickerKey`), 그 변환·판정을 쓰는 칩 줄(`FilterChipRow`)·열 고르기(`ColumnPicker`)·빌더 본체
   (`FilterBuilder`)를 둔다. 그 조각·효과 훅·순수 상태는 data_zone_filter_chips.ts·data_zone_card_editor.ts·
   data_zone_filter_builder.ts·data_zone_filter_state.ts가 진다. */

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








/** 스냅샷의 필터·표 존 — 둘 다 없으면 빈 기본값(아직 데이터가 없는 작업). */
function resolveZoneData(snapshot: Obj): { filter: Obj; table: Obj } {
  const filter = snapshot.filter || { active: false, search: "", columns: [] };
  const table = snapshot.table || { columns: [], rows: [], visible_count: 0, hidden_selected: [], hidden_columns: [] };
  return { filter, table };
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

/** 맨 아래 점선 「새 조건」 카드 — 열 이름을 적으면 Python 이 자모 부분일치로 거른 목록이 선다. */
export function ColumnPicker(props: {
  controller: JobReadController;
  rows: BuilderRow[];
  choose(column: string): void;
  inputRef: { current: HTMLInputElement | null };
}): ReactNode {
  const { controller, rows, choose, inputRef } = props;
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [matched, setMatched] = useState<Obj[]>([]);
  const [expanded, setExpanded] = useState(false);
  useFilterColumnQuery(controller, open, query, setMatched);
  const options = pickerOptions(matched, rows, { query, expanded });
  const pick = (index: number): void => {
    const option = options[index];
    if (!option) return;
    if (option.fold) { setExpanded(!expanded); setOpen(true); setActive(index); return; } // 접기 줄은 목록을 펼칠 뿐
    setQuery("");
    setOpen(false);
    setActive(-1);
    choose(option.value);
  };
  const optionId = (index: number) => `jobFilterColumnOption-${index}`;
  return h("div", { className: "fb-card fb-new" },
    h("label", { className: "fb-new-cap", id: "jobFilterColumnPickerLabel", htmlFor: "jobFilterColumnPicker" },
      "조건 더하기"),
    h("input", {
      className: "field", id: "jobFilterColumnPicker", ref: inputRef, "data-busy-lock": true,
      role: "combobox", "aria-expanded": open ? "true" : "false", "aria-controls": "jobFilterColumnList",
      "aria-autocomplete": "list", "aria-activedescendant": open && active >= 0 ? optionId(active) : undefined,
      placeholder: "열 이름을 적어 고르세요", autoComplete: "off", value: query,
      onChange: (event: Obj) => { setQuery(event.currentTarget.value); setOpen(true); setActive(0); },
      onClick: () => setOpen(true),
      onBlur: () => setOpen(false),
      onKeyDown: (event: Obj) => {
        const next = pickerKey({
          key: event.key, isComposing: event.nativeEvent?.isComposing, keyCode: event.keyCode,
        }, { open, active, count: options.length });
        if (!next.handled) return;
        event.preventDefault();
        event.stopPropagation(); // 목록만 닫는 Escape 가 빌더까지 닫지 않게
        if (next.choose !== null) { pick(next.choose); return; }
        setOpen(next.open);
        setActive(next.active);
      },
    }),
    open ? h("ul", { className: "fb-options", id: "jobFilterColumnList", role: "listbox" },
      ...options.map((option, index) => renderPickerOption(option, index, active, optionId, pick, setActive))) : null);
}

/** 초안의 처음 값 — 고치기는 그 저장본(또는 열 머리 adhoc 조건)에서, 새로 만들기는 adhoc
 *  조건(있으면)에서 채운다. */
function buildInitialDraft(
  filter: Obj, spec: BuilderSpec, columns: BuilderColumn[], source: Obj,
): { rows: BuilderRow[]; search: string; pruned: string[]; fromAdhoc: boolean } {
  const preset = spec.mode === "edit"
    ? ((filter.presets || []) as Obj[]).find((item) => item.name === spec.name) : null;
  const prefill = (spec.mode === "edit" ? preset?.state : source.adhoc) as Obj | null | undefined;
  return {
    rows: rowsFromState(prefill, columns),
    search: typeof prefill?.search === "string" ? prefill.search.trim() : "",
    pruned: Array.isArray(prefill?.pruned) ? (prefill.pruned as string[]) : [],
    fromAdhoc: spec.mode === "create" && !!source.adhoc,
  };
}

export function FilterBuilder(props: {
  controller: JobReadController;
  filter: Obj;
  spec: BuilderSpec;
  trigger: { current: HTMLElement | null };
  rootRef: { current: HTMLElement | null };
  close(focus: BuilderFocus): void;
}): ReactNode {
  const { controller, filter, spec, trigger, rootRef, close } = props;
  const source = (filter.builder || {}) as Obj;
  const columns = (source.columns || []) as BuilderColumn[];
  const [init] = useState(() => buildInitialDraft(filter, spec, columns, source));
  const [name, setName] = useState(spec.mode === "edit" ? spec.name : "");
  const [rows, setRows] = useState<BuilderRow[]>(init.rows);
  const [fromAdhoc, setFromAdhoc] = useState(init.fromAdhoc);
  const [count, setCount] = useState<Obj | null>(null);
  const [countError, setCountError] = useState<{ error: string; column: string }>({ error: "", column: "" });
  const [saveError, setSaveError] = useState<{ error: string; column: string }>({ error: "", column: "" });
  const [saving, setSaving] = useState(false);
  const nextId = useRef(Math.max(0, ...init.rows.map((row) => row.id)) + 1);
  const pickerRef = useRef<HTMLInputElement | null>(null);
  const focusRow = useRef<number | null>(null);
  // 삭제 확인(공용 모달)이 떠 있는 동안은 바깥 누름·Escape 가 모달의 몫이다.
  const suspended = useRef(false);
  const closeRef = useRef(close);
  closeRef.current = close;

  const pruned = resolvePrunedSearch(rows, init.search, init.pruned);
  const state = stateFromRows(rows, pruned);
  const stateKey = JSON.stringify(state);

  useFilterCount(controller, stateKey, setCount, setCountError);
  useEffect(() => { pickerRef.current?.focus(); }, []);
  useFocusNewRow(focusRow, rootRef);
  useFilterBuilderPlacement(controller, rootRef, trigger);
  useFilterBuilderDismiss(controller, rootRef, trigger, suspended, closeRef);

  const { clearSaveError, patch, remove, choose, submit, removePreset, resetDraft } = createBuilderEdits({
    controller, spec, columns, name, state, fromAdhoc, saving,
    setRows, setSaveError, setSaving, setFromAdhoc, close, pickerRef, nextId, focusRow, suspended,
  });

  // 오류는 가리키는 열의 카드 아래에, 열을 모르는 오류는 카드 목록 아래에 선다.
  const { failure, cardOf } = resolveFailureCard(rows, saveError, countError);
  const listed = buildCardList({
    rows, columns, patch, remove, cardOf, failure,
    picker: h(ColumnPicker as any, { key: "picker", controller, rows, choose, inputRef: pickerRef }),
  });
  const { total, matchedCount, ratio } = resolveCountSummary(count, source);
  return h("div", {
    className: "colpanel fbuilder", id: "jobFilterBuilder", ref: rootRef,
    role: "dialog", "aria-modal": "false", "aria-labelledby": "jobFilterBuilderTitle",
    "data-fb-spec": spec.mode,
  },
  renderFbHead(spec, fromAdhoc, rows, resetDraft),
  h("div", { className: "fb-rows" }, ...listed),
  renderUnplacedError(failure, cardOf),
  h("label", { className: "cp-sec fb-name" },
    h("span", { className: "cp-cap" }, "이름 ", h("span", { className: "fb-hint" }, "(비우면 조건이 이름이 됩니다)")),
    h("input", {
      className: "field", "data-fb-name": true, "data-busy-lock": true, value: name, autoComplete: "off",
      placeholder: String(count?.summary || ""),
      onChange: (event: Obj) => { clearSaveError(); setName(event.currentTarget.value); },
      onKeyDown: (event: Obj) => {
        if (builderKeyAction({
          key: event.key, isComposing: event.nativeEvent?.isComposing, keyCode: event.keyCode,
        }, true) !== "submit") return;
        event.preventDefault();
        void submit();
      },
    })),
  renderFbFoot({ spec, count, total, matchedCount, ratio, saving, removePreset, close, submit }));
}
