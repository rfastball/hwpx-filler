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

type Obj = Record<string, any>;

type JobReadController = {
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

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

function useUi(controller: JobReadController) {
  return useSyncExternalStore(controller.uiModel.subscribe, controller.uiModel.getSnapshot);
}

function asObject(value: unknown, label: string): Obj {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label}: 객체가 아닙니다.`);
  }
  return value as Obj;
}
function columnMeta(column: unknown): Obj {
  return typeof column === "string"
    ? { name: column, kind: "text", visible: true }
    : asObject(column, "job table column");
}

/** 비교 연산자 — 열 머리 범위 편집기와 필터 빌더가 **같은 목록·같은 순서**를 쓴다. */
export const RANGE_OPS: ReadonlyArray<readonly [string, string]> = [
  ["ge", "≥"], ["gt", ">"], ["le", "≤"], ["lt", "<"], ["eq", "="], ["ne", "≠"],
];

function Segments({ value }: { value: unknown }): ReactNode {
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
  rootRef: { current: HTMLElement | null };
}): ReactNode {
  const { controller, column, data, close, rootRef } = props;
  if (data === null) return h("div", { className: "colpanel react-colpanel", "aria-busy": "true", ref: rootRef },
    h("div", { className: "cp-head" }, h("span", null, `'${column}' 필터`),
      h("button", { "data-act": "panel-close", onClick: close, "aria-label": "닫기" }, "✕")),
    h("div", { className: "cp-sec cp-loading", role: "status" }, "불러오는 중…"));
  const checked = data.checked as string[] | null;
  const allOn = checked === null;
  const isRange = data.kind === "amount" || data.kind === "date";
  const values = data.options || [];
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
    h("div", { className: "cp-sec" }, h("span", { className: "cp-cap" }, "값 선택(같은 열 안은 OR)"),
      h("div", { className: "cp-vals" },
        h("label", null, h("input", { type: "checkbox", "data-val-all": true, defaultChecked: allOn,
          onChange: (event: Obj) => { void controller.zone("filter_col_values", { column, values: event.currentTarget.checked ? null : [] }); } }), h("b", null, "(전체)")),
        ...values.map((value: string) => h("label", { key: value },
          h("input", { type: "checkbox", "data-val": value, "data-busy-lock": true,
            defaultChecked: allOn || checked?.includes(value),
            onChange: (event: Obj) => {
              const root = event.currentTarget.closest(".cp-vals") as HTMLElement;
              const boxes = [...root.querySelectorAll<HTMLInputElement>("input[data-val]")];
              const on = boxes.filter((box) => box.checked).map((box) => box.dataset.val || "");
              void controller.zone("filter_col_values", { column, values: on.length === boxes.length ? null : on });
            } }), value === "" ? "(빈값)" : value)))),
    h("div", { className: "cp-acts" },
      h("button", { className: "btn sm", "data-act": "col-clear", "data-busy-lock": true,
        onClick: () => { void controller.zone("filter_clear_col", { column }); } }, "이 열 조건 지우기"),
      data.can_hide ? h("button", { className: "btn sm", "data-act": "col-hide", "data-busy-lock": true,
        title: "보기에서만 숨깁니다. 생성에는 그대로 쓰입니다.",
        onClick: () => { close(); void controller.zone("hide_column", { column }); } }, "이 열 숨기기") : null));
}

/* 저장한 필터 칩 줄(2026-09-30 재설계 — 슬라이서 관례) — 판정(켜짐·사용 가부·사유·차원·무리·
   조건 문안·저장 가부)은 전부 Python 이 싣고, 여기는 그리기와 동사 호출만 한다.

   - 같은 차원(같은 열)을 보는 칩이 둘 이상이면 **무리**(알약 묶음 + 열 이름 표지)로 선다 —
     무리 안은 「또는」, 무리 사이는 「그리고」라는 합성 규칙을 모양이 말한다. 홀로 선 칩은
     묶지 않는다(표지 하나에 칩 하나는 소음이다).
   - 칩은 이름 하나를 든 `<button aria-pressed>` 이고, 조건 문안은 Python 이 지은 `description`
     을 `title` 로 싣는다(정의줄과 같은 생산자). ⋯ 은 칩에 머물거나 초점이 들 때만 보이지만
     탭 순서에는 늘 있다(`opacity` — `display:none` 이 아니다).
   - 쓸 수 없는 칩도 눌리게 두고(aria-disabled) 거절은 백엔드 사유를 그대로 알린다 — 비활성
     단추는 사유를 말할 자리가 없다. */
function PresetChip(props: {
  preset: Obj;
  controller: JobReadController;
  editing: boolean;
  onEdit(name: string, trigger: HTMLElement): void;
}): ReactNode {
  const { preset, controller, editing, onEdit } = props;
  const name = String(preset.name);
  async function toggle(): Promise<void> {
    const result = await controller.zone("toggle_filter_preset", { name });
    if (result.stale) return;
    if (result.ok === false) controller.notify(`확인 필요: ${result.error}`);
  }
  return h("span", {
    className: `fchip preset${preset.active ? " on" : ""}${preset.usable ? "" : " warn"}`,
    "data-preset-chip": name,
  },
  h("button", {
    className: "preset-toggle", type: "button", "data-preset": name, "data-busy-lock": true,
    "aria-pressed": preset.active ? "true" : "false",
    "aria-disabled": preset.usable ? undefined : "true",
    title: String((preset.usable ? preset.description : preset.reason) || ""),
    onClick: () => { void toggle(); },
  }, name),
  h("button", {
    className: "preset-edit", type: "button", "data-preset-edit": name, "data-busy-lock": true,
    "aria-label": `${name} 필터 고치기`, title: `${name} 필터 고치기`, "aria-haspopup": "dialog",
    "aria-expanded": editing ? "true" : "false",
    onClick: (event: Obj) => onEdit(name, event.currentTarget as HTMLElement),
  }, icon("more")));
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
  const presets = (filter.presets || []) as Obj[];
  const byName = new Map(presets.map((preset) => [String(preset.name), preset]));
  const groups = (filter.preset_groups || []) as Obj[];
  const source = (filter.builder || {}) as Obj;
  const chips = filter.active ? (filter.chips || []) as string[] : [];
  const branches = filter.active ? (filter.branches || []) as string[] : [];
  const tail = chips.length + branches.length + (filter.active ? 1 : 0) + (hiddenColumns.length ? 1 : 0);
  const chip = (preset: Obj) => h(PresetChip as any, {
    key: `p-${preset.name}`, preset, controller, onEdit,
    editing: builder?.mode === "edit" && builder.name === preset.name,
  });
  return h("div", { className: "fchips", id: "jobFilterChips", hidden: !hasData },
    presets.length ? h("span", { className: "fchips-cap", key: "preset-cap" }, "저장한 필터") : null,
    ...groups.map((group: Obj) => {
      const members = ((group.names || []) as string[])
        .map((name) => byName.get(String(name))).filter(Boolean) as Obj[];
      if (members.length < 2) return members.length ? chip(members[0]) : null;
      return h("span", {
        className: "fcluster", role: "group", key: `g-${group.key}`,
        "data-dimension": String(group.key), "aria-label": String(group.label),
      },
      h("span", { className: "fcluster-label", "aria-hidden": "true" }, String(group.label)),
      ...members.map(chip));
    }),
    // 「+ 필터」 — 저장할 곳(등록 데이터)이 없으면 눌러도 사유를 알린다(판정·사유는 Python).
    h("button", {
      className: "btn sm fnew", type: "button", "data-act": "filter-new", "data-busy-lock": true,
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
    }, "+ 필터"),
    tail ? h("span", { className: "fchips-sep", "aria-hidden": "true" }) : null,
    // 열 머리에서 세운 지금 조건 — 저장한 필터와 갈라 읽히게 「열 조건」으로 부른다.
    ...chips.map((text: string, index: number) => h("span", { className: "fchip definition", key: `c-${index}` },
      h("span", { className: "chip-role" }, "열 조건"), text)),
    ...branches.map((branch: string) => h("span", { className: "fchip branch", key: `b-${branch}` },
      h("span", { className: "chip-role" }, "가지"), branch,
      h("button", { "data-prune": branch, "data-busy-lock": true, "aria-label": `${branch} 가지 제거`,
        onClick: () => { void controller.zone("filter_prune", { column: branch }); } }, "×"))),
    filter.active ? h("button", { className: "btn sm", "data-act": "filter-clear", "data-busy-lock": true,
      onClick: () => { void controller.zone("filter_clear", {}); } }, "필터 지우기") : null,
    hiddenColumns.length ? h("span", { className: "fchip hidecols", title: hiddenColumns.join(", ") },
      h("span", { className: "chip-role" }, "보기"), `열 ${hiddenColumns.length}개 숨김 — 생성에는 그대로 쓰입니다`,
      h("button", { "data-act": "unhide-cols", "data-busy-lock": true, "aria-label": "숨긴 열 모두 표시",
        onClick: () => { void controller.zone("unhide_columns", {}); } }, "×")) : null);
}

/* ---------------------------------------------------------------- 필터 빌더(「+ 필터」·⋯)
   조건 한 줄 = 열 하나(상태 문법이 열마다 조건 하나를 든다). 줄 사이는 「그리고」이고, 열마다의
   편집기는 열 유형(Python 판정)을 따른다: 금액·날짜 = 열 머리 범위 편집기와 같은 연산자·결합자,
   텍스트 = 값 고르기(체크리스트) | 포함 글자. 검증·수·저장은 전부 Python 동사다 — 여기서는
   줄을 상태 모양으로 옮기기만 한다. */
export type BuilderSpec = { mode: "create" | "edit"; name: string };
/** 닫힌 뒤 초점이 갈 자리 — 연 단추(`trigger`) · 누른 자리 그대로(`none`) · 「+ 필터」(`new`) ·
 *  고친 칩의 ⋯(`{ edit: 새 이름 }` — 이름이 바뀌면 칩이 다시 그려지므로 이름으로 찾는다). */
export type BuilderFocus = "trigger" | "none" | "new" | { edit: string };
export type BuilderColumn = { name: string; kind: string; values: string[] };
type Clause = { op: string; operand: string };
export type BuilderRow = {
  id: number;
  column: string;
  mode: "range" | "values" | "text" | "search";
  values: string[];
  text: string;
  first: Clause;
  second: Clause;
  joiner: string;
};

/** 「전체 열 검색」 줄의 열 자리 — 열 이름과 겹치지 않는 예약 값. */
export const SEARCH_ROW = "\u0000search";

const isRangeKind = (kind: string): boolean => kind === "amount" || kind === "date";

function kindOf(columns: BuilderColumn[], name: string): string {
  return columns.find((column) => column.name === name)?.kind || "";
}

export function blankRow(id: number, column: string, kind: string): BuilderRow {
  return {
    id, column,
    mode: column === SEARCH_ROW ? "search" : isRangeKind(kind) ? "range" : "values",
    values: [], text: "",
    first: { op: "ge", operand: "" }, second: { op: "lt", operand: "" }, joiner: "and",
  };
}

/** 다음 새 줄이 겨눌 열 — 아직 줄이 없는 첫 열, 다 쓰였으면 「전체 열 검색」, 그것도 있으면 "". */
export function freeColumn(columns: BuilderColumn[], rows: BuilderRow[]): string {
  const used = new Set(rows.map((row) => row.column));
  const open = columns.find((column) => !used.has(column.name));
  if (open) return open.name;
  return used.has(SEARCH_ROW) ? "" : SEARCH_ROW;
}

/** 저장본(또는 지금 조건) → 빌더 줄. 한 열에 범위·값 목록·글자가 겹쳐 있으면 줄을 나눠 전부
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
      rows.push({
        ...base(), mode: "range",
        first: { op: String(range.first?.op || "ge"), operand: String(range.first?.operand ?? "") },
        second: { op: String(range.second?.op || "lt"), operand: String(range.second?.operand ?? "") },
        joiner: String(range.joiner || "and"),
      });
    }
    if (Array.isArray(cond.values)) rows.push({ ...base(), mode: "values", values: cond.values.map(String) });
    if (typeof cond.text === "string" && cond.text.trim()) rows.push({ ...base(), mode: "text", text: cond.text });
  }
  const search = typeof state?.search === "string" ? state.search : "";
  if (search.trim()) rows.push({ ...blankRow(++id, SEARCH_ROW, ""), text: search });
  return rows;
}

/** 빌더 줄 → 상태(`export_state` 의 지금 조건 모양). 빈 줄(피연산자 없음·고른 값 없음·빈 글자)은
 *  조건이 아니다. `pruned` 는 프리필한 검색어가 그대로일 때만 잇는다(쳐낸 가지 = 검색 텍스트 수명). */
export function stateFromRows(rows: BuilderRow[], pruned: string[] = []): Obj {
  const columns: Obj = {};
  let search = "";
  for (const row of rows) {
    if (row.mode === "search") { search = row.text.trim(); continue; }
    if (!row.column) continue;
    const cond = (columns[row.column] ||= { text: "", values: null, range: null }) as Obj;
    if (row.mode === "range") {
      if (!row.first.operand.trim()) continue;
      cond.range = {
        first: { op: row.first.op, operand: row.first.operand },
        second: row.second.operand.trim() ? { op: row.second.op, operand: row.second.operand } : null,
        joiner: row.joiner,
      };
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

/** 살아 있는 수의 발신기 — 마지막 입력 뒤 `delay`(150ms) 에 한 번 보내고, 늦게 도착한 옛 응답은
 *  버린다(순서가 뒤집혀도 화면은 마지막 조건의 수만 말한다). */
export function createCountRequester(deps: {
  setTimer(fn: () => void, ms: number): unknown;
  clearTimer(handle: unknown): void;
  send(state: Obj): Promise<Obj>;
  apply(result: Obj): void;
  delay?: number;
}) {
  let timer: unknown = null;
  let seq = 0;
  return {
    request(state: Obj): void {
      if (timer !== null) deps.clearTimer(timer);
      const mine = ++seq;
      timer = deps.setTimer(() => {
        timer = null;
        deps.send(state).then(
          (result) => { if (mine === seq) deps.apply(result); },
          (error) => { if (mine === seq) deps.apply({ ok: false, error: String(error) }); },
        );
      }, deps.delay ?? 150);
    },
    cancel(): void {
      if (timer !== null) deps.clearTimer(timer);
      timer = null;
      seq += 1;
    },
  };
}

/** 빌더 안 키 하나의 뜻 — 한글 조합 중(Enter·Escape 가 조합 확정)은 아무 뜻도 없다. */
export function builderKeyAction(
  event: { key: string; isComposing?: boolean; keyCode?: number },
  inName: boolean,
): "close" | "submit" | null {
  if (event.isComposing || event.keyCode === 229) return null;
  if (event.key === "Escape") return "close";
  if (event.key === "Enter" && inName) return "submit";
  return null;
}

/** 닫힌 뒤 초점이 돌아갈 자리 — 연 단추, 사라졌으면(삭제한 칩의 ⋯) 「+ 필터」. */
export function focusReturnTarget(trigger: HTMLElement | null, doc: Document): HTMLElement | null {
  if (trigger && trigger.isConnected) return trigger;
  return doc.querySelector<HTMLElement>('[data-act="filter-new"]');
}

/** `BuilderFocus` → 찾을 자리. 칩 ⋯ 은 이름으로 찾는다(선택자 이스케이프 없이 속성값 비교). */
export function focusFinder(
  focus: BuilderFocus, trigger: HTMLElement | null, doc: Document,
): (() => HTMLElement | null) | null {
  if (focus === "none") return null;
  if (focus === "trigger") return () => focusReturnTarget(trigger, doc);
  if (focus === "new") return () => doc.querySelector<HTMLElement>('[data-act="filter-new"]');
  return () => Array.from(doc.querySelectorAll<HTMLElement>("[data-preset-edit]"))
    .find((element) => element.getAttribute("data-preset-edit") === focus.edit) || null;
}

function RowEditor(props: {
  row: BuilderRow;
  columns: BuilderColumn[];
  rows: BuilderRow[];
  patch(id: number, patch: Partial<BuilderRow>): void;
  remove(id: number): void;
}): ReactNode {
  const { row, columns, rows, patch, remove } = props;
  const others = rows.filter((other) => other.id !== row.id);
  const used = new Set(others.map((other) => other.column));
  const options = columns.filter((column) => !used.has(column.name) || column.name === row.column)
    .map((column) => column.name);
  // 고칠 저장본이 지금 데이터에 없는 열을 가리키면 그 이름을 그대로 보인다 — 저장이 사유와 함께 거절한다.
  if (row.column && row.column !== SEARCH_ROW && !options.includes(row.column)) options.unshift(row.column);
  const searchFree = row.mode === "search" || !used.has(SEARCH_ROW);
  const kind = kindOf(columns, row.column);
  const label = row.mode === "search" ? "전체 열 검색" : row.column;
  const listed = columns.find((column) => column.name === row.column)?.values || [];
  const choices = [...row.values.filter((value) => !listed.includes(value)), ...listed];
  const clause = (slot: 1 | 2) => {
    const current = slot === 1 ? row.first : row.second;
    const key = slot === 1 ? "first" : "second";
    return [
      h("select", {
        className: "field", key: `op${slot}`, "data-rop": slot, "data-busy-lock": true, value: current.op,
        onChange: (event: Obj) => patch(row.id, { [key]: { ...current, op: event.currentTarget.value } }),
      }, ...RANGE_OPS.map(([value, text]) => h("option", { value, key: value }, text))),
      h("input", {
        className: "field", key: `val${slot}`, "data-rval": slot, "data-busy-lock": true, value: current.operand,
        onChange: (event: Obj) => patch(row.id, { [key]: { ...current, operand: event.currentTarget.value } }),
      }),
    ];
  };
  return h("div", { className: "fb-row", "data-fb-row": row.id, "data-fb-mode": row.mode },
    h("div", { className: "fb-row-head" },
      h("select", {
        className: "field fb-col", "data-fb-col": true, "data-busy-lock": true, "aria-label": "열",
        value: row.column,
        onChange: (event: Obj) => {
          const column = String(event.currentTarget.value);
          const next = blankRow(row.id, column, kindOf(columns, column));
          patch(row.id, { column, mode: next.mode, values: [], text: "" });
        },
      },
      ...options.map((name) => h("option", { value: name, key: name }, name)),
      searchFree ? h("option", { value: SEARCH_ROW, key: "search" }, "전체 열 검색") : null),
      (row.mode === "values" || row.mode === "text") && !isRangeKind(kind)
        ? h("select", {
          className: "field fb-mode", "data-fb-mode-select": true, "data-busy-lock": true, "aria-label": "조건",
          value: row.mode,
          onChange: (event: Obj) => patch(row.id, { mode: event.currentTarget.value }),
        }, h("option", { value: "values" }, "값 고르기"), h("option", { value: "text" }, "포함 글자"))
        : null,
      h("button", {
        className: "fb-remove", type: "button", "data-fb-remove": row.id, "data-busy-lock": true,
        "aria-label": `${label} 조건 지우기`, title: `${label} 조건 지우기`, onClick: () => remove(row.id),
      }, icon("close"))),
    row.mode === "range"
      ? h("div", { className: "fb-range" },
        h("div", { className: "cp-range-row" }, ...clause(1)),
        h("div", { className: "cp-range-row" },
          h("select", {
            className: "field", "data-rjoin": true, "data-busy-lock": true, value: row.joiner,
            onChange: (event: Obj) => patch(row.id, { joiner: event.currentTarget.value }),
          }, h("option", { value: "and" }, "그리고"), h("option", { value: "or" }, "또는")),
          ...clause(2)))
      : row.mode === "values"
        ? h("div", { className: "cp-vals" },
          ...choices.map((value) => h("label", { key: `v-${value}` },
            h("input", {
              type: "checkbox", "data-fb-val": value, "data-busy-lock": true,
              checked: row.values.includes(value),
              onChange: (event: Obj) => {
                const on = !!event.currentTarget.checked;
                // 순서가 의미다(정의줄이 이 순서로 재진술) — 목록에 보이는 순서로 모은다.
                const picked = new Set(row.values.filter((item) => item !== value));
                if (on) picked.add(value);
                patch(row.id, { values: choices.filter((item) => picked.has(item)) });
              },
            }), value === "" ? "(빈값)" : value)))
        : h("input", {
          className: "field", "data-fb-text": row.mode, "data-busy-lock": true, value: row.text,
          "aria-label": label,
          onChange: (event: Obj) => patch(row.id, { text: event.currentTarget.value }),
        }));
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
  const [init] = useState(() => {
    const preset = spec.mode === "edit"
      ? ((filter.presets || []) as Obj[]).find((item) => item.name === spec.name) : null;
    const prefill = (spec.mode === "edit" ? preset?.state : source.adhoc) as Obj | null | undefined;
    const rows = rowsFromState(prefill, columns);
    const column = freeColumn(columns, []);
    return {
      rows: rows.length ? rows : [blankRow(1, column, kindOf(columns, column))],
      search: typeof prefill?.search === "string" ? prefill.search.trim() : "",
      pruned: Array.isArray(prefill?.pruned) ? (prefill.pruned as string[]) : [],
      fromAdhoc: spec.mode === "create" && !!source.adhoc,
    };
  });
  const [name, setName] = useState(spec.mode === "edit" ? spec.name : "");
  const [rows, setRows] = useState<BuilderRow[]>(init.rows);
  const [count, setCount] = useState<Obj | null>(null);
  const [countError, setCountError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const nextId = useRef(Math.max(0, ...init.rows.map((row) => row.id)) + 1);
  const nameRef = useRef<HTMLInputElement | null>(null);
  // 삭제 확인(공용 모달)이 떠 있는 동안은 바깥 누름·Escape 가 모달의 몫이다.
  const suspended = useRef(false);
  const closeRef = useRef(close);
  closeRef.current = close;

  const searchRow = rows.find((row) => row.mode === "search");
  const pruned = searchRow && searchRow.text.trim() === init.search ? init.pruned : [];
  const state = stateFromRows(rows, pruned);
  const stateKey = JSON.stringify(state);

  const requester = useRef<ReturnType<typeof createCountRequester> | null>(null);
  if (requester.current === null) {
    const view = controller.doc.defaultView;
    requester.current = createCountRequester({
      setTimer: (fn, ms) => view?.setTimeout(fn, ms),
      clearTimer: (handle) => view?.clearTimeout(handle as number),
      send: (candidate) => controller.zone("count_filter_state", { state: candidate }, true),
      apply: (result) => {
        if (result.stale) return;
        if (result.ok === false) { setCountError(String(result.error || "")); return; }
        setCountError("");
        setCount(result);
      },
    });
  }
  useEffect(() => { requester.current?.request(JSON.parse(stateKey)); }, [stateKey]);
  useEffect(() => () => requester.current?.cancel(), []);
  useEffect(() => { nameRef.current?.focus(); }, []);
  // 트리거 아래에 **그린 뒤** 붙인다(열 머리 패널과 같은 `Popover.place`). 줄·오류·수가 바뀌면
  // 높이가 바뀌므로 그릴 때마다 다시 잰다 — 아래가 모자라면 위로 뒤집힌다.
  useLayoutEffect(() => {
    const root = rootRef.current;
    const anchor = trigger.current;
    if (root && anchor && anchor.isConnected) controller.placePopover(root, anchor);
  });
  useEffect(() => {
    const doc = controller.doc;
    function onKey(event: KeyboardEvent): void {
      if (suspended.current || builderKeyAction(event, false) !== "close") return;
      event.preventDefault();
      closeRef.current("trigger");
    }
    function onDown(event: MouseEvent): void {
      if (suspended.current) return;
      const target = event.target as Node | null;
      if (!target || rootRef.current?.contains(target) || trigger.current?.contains(target)) return;
      closeRef.current("none"); // 바깥 누름은 누른 자리가 초점을 가진다 — 되돌리지 않는다
    }
    doc.addEventListener("keydown", onKey);
    doc.addEventListener("mousedown", onDown, true);
    return () => {
      doc.removeEventListener("keydown", onKey);
      doc.removeEventListener("mousedown", onDown, true);
    };
  }, [controller, rootRef, trigger]);

  function patch(id: number, change: Partial<BuilderRow>): void {
    setSaveError("");
    setRows((current) => current.map((row) => (row.id === id ? { ...row, ...change } : row)));
  }
  function remove(id: number): void {
    setSaveError("");
    setRows((current) => current.filter((row) => row.id !== id));
  }
  const nextColumn = freeColumn(columns, rows);
  function add(): void {
    if (!nextColumn) return;
    setSaveError("");
    setRows((current) => [...current, blankRow(nextId.current++, nextColumn, kindOf(columns, nextColumn))]);
  }

  async function submit(): Promise<void> {
    if (saving) return;
    setSaving(true);
    setSaveError("");
    try {
      const result = spec.mode === "edit"
        ? await controller.zone("update_filter_preset", { name: spec.name, new_name: name, state })
        : await controller.zone("create_filter_preset", {
          name, state, ...(init.fromAdhoc ? { from_adhoc: true } : {}),
        });
      if (result.stale) { close("trigger"); return; }
      if (result.ok === false) { setSaveError(String(result.error || "")); return; }
      close(spec.mode === "edit" ? { edit: String(result.name || name) } : "trigger");
    } catch (error) {
      setSaveError(String(error));
    } finally {
      setSaving(false);
    }
  }

  async function removePreset(button: HTMLElement): Promise<void> {
    suspended.current = true;
    try {
      const accepted = await controller.confirm({
        title: "저장한 필터 삭제", body: `사라지는 것: 저장한 필터 '${spec.name}'`,
        confirmLabel: "삭제", cancelLabel: "취소", danger: true, returnFocus: button,
      });
      if (!accepted) return;
      const result = await controller.zone("delete_filter_preset", { name: spec.name });
      if (result.stale) { close("trigger"); return; }
      if (result.ok === false) { setSaveError(String(result.error || "")); return; }
      close("new"); // 지운 칩의 ⋯ 은 사라진다
    } finally {
      suspended.current = false;
    }
  }

  const error = saveError || countError;
  const title = spec.mode === "edit" ? "필터 고치기" : "필터 만들기";
  const listed: ReactNode[] = [];
  rows.forEach((row, index) => {
    if (index) listed.push(h("div", { className: "fb-and", key: `and-${row.id}`, "aria-hidden": "true" }, "그리고"));
    listed.push(h(RowEditor as any, { key: `row-${row.id}`, row, columns, rows, patch, remove }));
  });
  return h("div", {
    className: "colpanel fbuilder", id: "jobFilterBuilder", ref: rootRef,
    role: "dialog", "aria-modal": "false", "aria-labelledby": "jobFilterBuilderTitle",
    "data-fb-spec": spec.mode,
  },
  h("div", { className: "cp-head" }, h("span", { id: "jobFilterBuilderTitle" }, title)),
  h("label", { className: "cp-sec fb-name" },
    h("span", { className: "cp-cap" }, "이름"),
    h("input", {
      className: "field", "data-fb-name": true, "data-busy-lock": true, value: name, ref: nameRef,
      autoComplete: "off",
      onChange: (event: Obj) => { setSaveError(""); setName(event.currentTarget.value); },
      onKeyDown: (event: Obj) => {
        if (builderKeyAction({
          key: event.key, isComposing: event.nativeEvent?.isComposing, keyCode: event.keyCode,
        }, true) !== "submit" || !name.trim()) return;
        event.preventDefault();
        void submit();
      },
    })),
  h("div", { className: "cp-sec" },
    h("span", { className: "cp-cap" }, "조건"),
    h("div", { className: "fb-rows" }, ...listed),
    h("button", {
      className: "btn sm quiet fb-add", type: "button", "data-act": "fb-add", "data-busy-lock": true,
      disabled: !nextColumn, onClick: add,
    }, "+ 조건")),
  h("div", { className: "fb-count", role: "status", "aria-live": "polite", "data-fb-count": true },
    count ? `지금 데이터 ${count.total}행 중 ${count.count}행` : ""),
  error ? h("div", { className: "cp-err", role: "alert", "data-fb-error": true }, error) : null,
  h("div", { className: "fb-foot" },
    spec.mode === "edit" ? h("button", {
      className: "btn sm quiet fb-delete", type: "button", "data-act": "fb-delete", "data-busy-lock": true,
      onClick: (event: Obj) => { void removePreset(event.currentTarget as HTMLElement); },
    }, "삭제") : null,
    h("button", {
      className: "btn sm", type: "button", "data-act": "fb-cancel", onClick: () => close("trigger"),
    }, "취소"),
    h("button", {
      className: "btn sm primary", type: "button", "data-act": "fb-save", "data-busy-lock": true,
      disabled: saving, onClick: () => { void submit(); },
    }, "저장")));
}

export function JobDataZone(props: {
  snapshot: Obj;
  controller: JobReadController;
  scroll: any;
}): ReactNode {
  const { snapshot, controller, scroll: Scroll } = props;
  const filter = snapshot.filter || { active: false, search: "", columns: [] };
  const table = snapshot.table || { columns: [], rows: [], visible_count: 0, hidden_selected: [], hidden_columns: [] };
  const [query, setQuery] = useState(String(filter.search || ""));
  const [panel, setPanel] = useState<{ column: string; data: Obj | null } | null>(null);
  // 팝오버는 **누른 자리** 아래에 선다(U4 계열1-9). 트리거는 ref 로 든다 — 상태에 넣으면
  // 배치 한 번에 재렌더가 한 번 더 붙는다.
  const panelRoot = useRef<HTMLElement | null>(null);
  const panelTrigger = useRef<HTMLElement | null>(null);
  // 필터 빌더(「+ 필터」·칩 ⋯) — 열 머리 패널과 같은 배치·같은 트리거 ref 규칙.
  const [builder, setBuilder] = useState<BuilderSpec | null>(null);
  const builderRoot = useRef<HTMLElement | null>(null);
  const builderTrigger = useRef<HTMLElement | null>(null);
  const pendingFocus = useRef<{ find(): HTMLElement | null; until: number } | null>(null);
  const anchor = useRef<{ index: number; value: boolean } | null>(null);
  const optimisticSelection = useRef(new Map<number, boolean>());
  const [, setSelectionRevision] = useState(0);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const ui = useUi(controller);
  useEffect(() => { if (controller.doc.activeElement?.id !== "jobFilterSearch") setQuery(String(filter.search || "")); }, [filter.search, controller]);
  useEffect(() => { if (wrapRef.current) wrapRef.current.scrollTop = ui.tableScrollTop; }, [ui.sheetOpen, ui.tableScrollTop]);
  useEffect(() => {
    let changed = false;
    const live = new Map<number, boolean>((table.rows || []).map((row: Obj) => [row.index, !!row.selected]));
    for (const [index, intended] of optimisticSelection.current) {
      if (!live.has(index) || live.get(index) === intended) {
        optimisticSelection.current.delete(index);
        changed = true;
      }
    }
    if (changed) setSelectionRevision((revision) => revision + 1);
  }, [table.rows]);

  function selectedFor(row: Obj): boolean {
    return optimisticSelection.current.get(row.index) ?? !!row.selected;
  }

  function showSelection(index: number, value: boolean): void {
    optimisticSelection.current.set(index, value);
    setSelectionRevision((revision) => revision + 1);
  }

  function sendSelection(action: string, payload: Obj, intended: Array<[number, boolean]>): void {
    void controller.zone(action, payload).catch((error) => {
      let changed = false;
      for (const [index, value] of intended) {
        if (optimisticSelection.current.get(index) === value) {
          optimisticSelection.current.delete(index);
          changed = true;
        }
      }
      if (changed) setSelectionRevision((revision) => revision + 1);
      controller.notify(`선택을 바꾸지 못했습니다: ${String(error)}`);
    });
  }

  async function openPanel(column: string, trigger: HTMLElement | null): Promise<void> {
    if (panel?.column === column) { setPanel(null); return; }
    setBuilder(null);
    panelTrigger.current = trigger;
    setPanel({ column, data: null });
    try {
      const data = await controller.zone("filter_panel", { column }, true);
      setPanel((current) => current?.column === column ? { column, data } : current);
    } catch (error) {
      controller.notify(`필터를 불러오지 못했습니다: ${String(error)}`);
      setPanel(null);
    }
  }

  // 그린 **뒤** 재는 것이 계약이다 — `Popover.place` 는 실제 렌더 크기로 viewport clamp·
  // flip 을 하므로 측정 전에는 답을 낼 수 없다. `panel` 은 열림과 도착에서 각각 새 객체라
  // 「불러오는 중…」과 실내용의 높이 차이도 이 한 훅이 흡수한다.
  useLayoutEffect(() => {
    const root = panelRoot.current;
    const trigger = panelTrigger.current;
    if (!panel || !root || !trigger) return;
    controller.placePopover(root, trigger);
  }, [controller, panel]);

  function openBuilder(spec: BuilderSpec, trigger: HTMLElement): void {
    const same = builder && builder.mode === spec.mode && builder.name === spec.name;
    if (same) { closeBuilder("trigger"); return; }
    setPanel(null);
    pendingFocus.current = null;
    builderTrigger.current = trigger;
    setBuilder(spec);
  }

  function closeBuilder(focus: BuilderFocus): void {
    const find = focusFinder(focus, builderTrigger.current, controller.doc);
    setBuilder(null);
    // 칩 줄은 저장 뒤의 push 로 다시 그려진다 — 고친 칩(새 이름)·「+ 필터」가 **선 뒤에** 초점을
    // 옮기도록 찾을 자리를 걸어 두고 렌더마다 찾는다(잠깐 뒤엔 포기 — 늦게 나타난 요소가 초점을 훔치지 않게).
    pendingFocus.current = find ? { find, until: Date.now() + 2000 } : null;
  }

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

  function toggleRow(row: Obj, shift: boolean): void {
    if (shift && anchor.current !== null) {
      const visible = (table.rows || []).map((item: Obj) => item.index);
      const left = visible.indexOf(anchor.current.index);
      const right = visible.indexOf(row.index);
      if (left >= 0 && right >= 0) {
        const indices = visible.slice(Math.min(left, right), Math.max(left, right) + 1);
        const intended = indices.map((index: number) => [index, anchor.current!.value] as [number, boolean]);
        for (const [index, value] of intended) showSelection(index, value);
        sendSelection("select_range", { indices, value: anchor.current.value }, intended);
        return;
      }
    }
    const value = !selectedFor(row);
    anchor.current = { index: row.index, value };
    showSelection(row.index, value);
    sendSelection("toggle_record", { index: row.index, value }, [[row.index, value]]);
  }

  const selected = snapshot.zone_selected_count ?? snapshot.selected_count ?? 0;
  const hidden = table.hidden_selected || [];
  const hiddenColumns = table.hidden_columns || [];
  // 표시순서 축은 초안이 열려 있으면 초안의 것이다(§18.11-21 — 적용 전 메인 범위 불변).
  const viewOrder = String(
    snapshot.range_draft?.open
      ? snapshot.range_draft.view_order || "sourceDesc"
      : snapshot.view_order || "sourceDesc",
  );
  // 머리 체크박스의 3상태는 **보이는 행** 기준이다(U4 11번). 백엔드가 필터 활성 시 매치만
  // 가산하므로(`data_zone.py` `_do_set_all`), 전건 판정을 전체 레코드로 재면 필터를 켠 채
  // 다 골라도 영영 「일부」로 남는다 — 술어가 동사의 실제 결과를 따라가야 한다.
  const visibleRows = (table.rows || []) as Obj[];
  const visibleSelected = visibleRows.filter((row) => selectedFor(row)).length;
  const headChecked = visibleRows.length > 0 && visibleSelected === visibleRows.length;
  const headPartial = visibleSelected > 0 && !headChecked;
  // 해제는 **필터 밖 선택까지** 지운다(`set_none` 은 집합 전체를 비운다). 문안이 그 범위를
  // 말하지 않으면 사용자는 보이지 않는 곳에서 잃은 것을 모른다 — 종전 「전체 해제」 버튼과
  // 같은 동사이지만, 어포던스가 체크박스가 된 만큼 사유를 이름이 진다.
  const headSelectLabel = headChecked
    ? (hidden.length ? `전체 해제 (필터 밖 선택 ${hidden.length}행도 함께)` : "전체 해제")
    : (filter.active ? "보이는 행 모두 선택" : "전체 선택");
  return createElement(Fragment, null,
    h("div", { className: "run-row run-recs-head", id: "jobRecsHead", hidden: !snapshot.has_data },
      h("span", { className: "lbl", style: { fontWeight: 600 } }, "생성 대상 문서"),
      // 검색은 이 줄에서 **가장 자주 쓰이는 입력**인데 종전에는 라벨도 표지도 없는 좁은
      // 상자라 어디에 무엇을 넣는 자리인지 형태가 말하지 않았다. 돋보기는 장식이 아니라
      // 그 형태의 이름이다(`aria-hidden` — 이름은 placeholder 가 이미 진다).
      h("span", { className: "jobsearch-wrap" },
        h("svg", { className: "jobsearch-ico", "aria-hidden": "true", viewBox: "0 0 16 16",
          width: 14, height: 14, fill: "none", stroke: "currentColor", strokeWidth: 1.6,
          strokeLinecap: "round" },
          h("circle", { cx: 7, cy: 7, r: 4.5 }),
          h("path", { d: "M10.4 10.4 L14 14" })),
        h("input", { className: "field jobsearch", id: "jobFilterSearch", type: "search", value: query,
          placeholder: "전체 열 검색", autoComplete: "off", "data-busy-lock": true,
          onChange: (event: Obj) => { setQuery(event.currentTarget.value); controller.scheduleSearch(event.currentTarget.value); } })),
      h("button", { className: "btn sm filter-reapply", id: "jobFilterReapply", hidden: !snapshot.has_data || !filter.reapply_available,
        title: filter.reapply_hint ? `직전 필터 재적용: ${filter.reapply_hint}` : "직전 필터 재적용", "data-busy-lock": true,
        onClick: async () => {
          const result = await controller.zone("filter_reapply", {});
          if (result.stale) return;
          if (!result.ok) controller.notify(`확인 필요: ${result.error}`);
        } }, "직전 필터 재적용"),
      h("div", { className: "acts" }, h("span", { className: "muted capnote", id: "jobSelCount" },
        `선택 ${selected}/${snapshot.record_count || 0}${filter.active ? ` · 표시 ${table.visible_count || 0}` : ""}`),
      // 「전체 선택/해제」 두 버튼은 표 머리 체크박스로 갔다(U4 11번). 그 자리가 곧 그 동사가
      // 겨누는 열이라, 표와 무관한 줄에서 표를 조작하던 어긋남이 사라진다.
      //
      // 표시순서도 여기서 `<select>` 를 버린다(U4 7번). 2값 고정 축이라(F3 계약) 스위치가
      // 정확한 형태이고, 기본값(`sourceDesc` — 최신 행 먼저)에서 **벗어난 상태만** 눌린 것으로
      // 표현한다. 기본값 자체는 그대로다: 요구는 기본값이 아니라 컨트롤의 시각 비중이었다.
      h("button", { className: "btn sm", id: "jobOrderToggle", type: "button", "data-busy-lock": true,
        "aria-pressed": viewOrder === "sourceAsc" ? "true" : "false",
        // 이 컨트롤이 무슨 축을 모는지 DOM 이 **선언**한다 — `<select>` 시절 `options` 가
        // 지던 「2값 고정」(F3)을 스위치에서도 게이트가 되읽을 수 있어야 한다.
        "data-order-values": "sourceDesc,sourceAsc",
        title: "표의 정렬 순서를 바꿉니다. 생성 순서와 파일 이름 순번이 함께 따라갑니다.",
        onClick: () => {
          void controller.zone("set_view_order", {
            value: viewOrder === "sourceAsc" ? "sourceDesc" : "sourceAsc",
          });
        } }, `⇅ ${viewOrder === "sourceAsc" ? "원본 순서" : "원본 역순"}`),
      // 「펼쳐서 행 고르기」도 표를 여는 동사라 표 머리에 선다(U4 10번). **시트 안에서는
      // 그리지 않는다** — 자기 자신을 여는 단추는 무동작이고, 닫는 동사는 면 footer 의
      // 취소·적용이 이미 진다.
      ui.sheetOpen ? null : h("button", {
        className: "btn sm", id: "jobDataExpand", type: "button",
        onClick: (event: Obj) => { void controller.openDataSheet(event.currentTarget); },
      }, "펼쳐서 행 고르기 ⤢"))),
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
            h("tr", null,
              // 선택 동사가 그 열의 머리로 온다(U4 11번). **id 는 유지한다** — 자리는 바뀌어도
              // 동사는 같고(`SELECT_RECORDS` 의 복구 동사 선언이 이 좌표를 든다), 대본의
              // 클릭들도 전부 0건 상태에서 한 번 누르는 걸음이라 그대로 산다.
              //
              // `indeterminate` 는 속성이 아니라 DOM 프로퍼티라 ref 로만 세울 수 있다.
              h("th", { className: "doccol" },
                h("input", {
                  type: "checkbox", id: "jobSelAll", className: "selall", "data-busy-lock": true,
                  checked: headChecked,
                  ref: (element: any) => { if (element) element.indeterminate = headPartial; },
                  "aria-label": headSelectLabel, title: headSelectLabel,
                  onChange: () => { void controller.zone(headChecked ? "set_none" : "set_all", {}); },
                })),
              ...(table.columns || []).map((raw: unknown, index: number) => {
                const column = columnMeta(raw);
                if (column.visible === false) return null;
                return h("th", { className: `col-${column.kind || "text"}`, key: column.name },
                  h("span", null, column.name),
                  h("button", {
                    className: `fico${filter.columns?.[index]?.active ? " on" : ""}`,
                    "data-col": column.name,
                    "data-busy-lock": true,
                    "aria-label": `${column.name} 열 필터`,
                    "aria-expanded": panel?.column === column.name,
                    onClick: (event: Obj) => { void openPanel(column.name, event.currentTarget); },
                  }, "▾"));
              }))),
          h("tbody", { id: "jobTableBody" },
            ...(table.rows || []).map((row: Obj) => h("tr", {
              key: row.index,
              id: `jobRow-${row.index}`,
              "data-i": row.index,
              className: selectedFor(row) ? "on" : "",
              "aria-selected": selectedFor(row) ? "true" : "false",
              tabIndex: 0,
              onClick: (event: Obj) => toggleRow(row, !!event.shiftKey),
              onKeyDown: (event: Obj) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  toggleRow(row, !!event.shiftKey);
                }
              },
            },
            // 「문서」 열의 **이름·요약은 걷혔다**(U4 8번 · 사용자 확정: 「문서 이름은 생각처럼
            // 쓸모있는 정보가 아니다」). 남는 것은 선택 표지 하나이고, 생성될 이름을 확인하는
            // 자리는 「생성 예정 문서」 존이 진다. `row.name`·`row.summary` payload 는 **그대로**
            // 다 — 필터 밖 선택 스트립이 그 값으로 칩 이름을 짓는다(생산자 0 아님).
            h("td", { className: "doccol" },
              h("div", { className: "doccell" },
                h("input", {
                  type: "checkbox", tabIndex: -1, checked: selectedFor(row), readOnly: true,
                  "aria-label": `${row.index + 1}행 선택`,
                }))),
            ...(row.cells || []).map((cell: unknown, index: number) => {
              const column = columnMeta(table.columns[index]);
              return column.visible === false
                ? null
                : h("td", { className: `col-${column.kind || "text"}`, key: index,
                  title: Array.isArray(cell)
                    ? cell.map((part: unknown) => String(Array.isArray(part) ? part[0] ?? "" : "")).join("")
                    : undefined },
                  h('span', {
                    id: `jobCell-${row.index}-${index}`, tabIndex: -1,
                  }, h(Segments as any, { value: cell })));
            })))))),
      h("div", {
        className: "job-empty muted",
        id: "jobTableEmpty",
        hidden: snapshot.has_data && (table.rows || []).length > 0,
      }, !snapshot.has_data
        ? "데이터를 선택하면 생성 대상 문서가 여기에 표시됩니다."
        : filter.active
          ? "필터와 일치하는 행이 없습니다. 위 칩의 정의를 확인하세요."
          : "데이터에 행이 없습니다."),
      panel
        ? h(ColumnPanel as any, {
          controller, column: panel.column, data: panel.data, close: () => setPanel(null),
          rootRef: panelRoot,
        })
        : null,
      // 열 머리 패널과 같은 자리(`position:fixed` 부유 면) — 스크롤 표·칩 줄의 overflow 에 잘리지 않는다.
      // 열린 명세마다 새로 마운트해(key) 프리필이 이전 빌더의 입력을 잇지 않는다.
      snapshot.has_data && builder
        ? h(FilterBuilder as any, {
          key: `${builder.mode}:${builder.name}`, controller, filter, spec: builder,
          trigger: builderTrigger, rootRef: builderRoot, close: closeBuilder,
        })
        : null),
    h("div", { className: "fstrip", id: "jobSelStrip", hidden: !snapshot.has_data || !hidden.length },
      hidden.length ? `필터 밖 선택 ${hidden.length}행도 생성에 포함됩니다: ` : "",
      ...hidden.map((row: Obj) => h("span", { className: "fchip selection", key: row.index },
        h("span", { className: "chip-role" }, "선택"), row.name || row.summary || `${row.index + 1}행`,
        h("button", { "data-unsel": row.index, "data-busy-lock": true, "aria-label": `${row.index + 1}행 선택 해제`,
          onClick: () => { void controller.zone("toggle_record", { index: row.index, value: false }); } }, "×")))),
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
