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

type Obj = Record<string, any>;

type JobReadController = {
  doc: Document;
  notify(message: string): void;
  uiModel: {
    subscribe(listener: () => void): () => void;
    getSnapshot(): Obj;
  };
  zone(action: string, payload?: Obj, returnValue?: boolean): Promise<Obj>;
  call(screen: string, action: string, payload?: Obj): Promise<Obj>;
  scheduleColumnText(column: string, value: string): void;
  scheduleSearch(value: string): void;
  closeDataSheet(): void;
  discardRange(): Promise<void>;
  applyRange(): Promise<void>;
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
}): ReactNode {
  const { controller, column, data, close } = props;
  if (data === null) return h("div", { className: "colpanel react-colpanel", "aria-busy": "true" },
    h("div", { className: "cp-head" }, h("span", null, `'${column}' 필터`),
      h("button", { "data-act": "panel-close", onClick: close, "aria-label": "닫기" }, "✕")),
    h("div", { className: "cp-sec cp-loading", role: "status" }, "불러오는 중…"));
  const checked = data.checked as string[] | null;
  const allOn = checked === null;
  const isRange = data.kind === "amount" || data.kind === "date";
  const values = data.options || [];
  return h("div", { className: "colpanel react-colpanel" },
    h("div", { className: "cp-head" }, h("span", null, `'${column}' 필터`),
      h("button", { "data-act": "panel-close", onClick: close, "aria-label": "닫기" }, "✕")),
    isRange ? h("div", { className: "cp-sec" },
      h("span", { className: "cp-cap" }, `범위 조건(${data.kind === "amount" ? "금액" : "날짜"})`),
      ...[1, 2].map((slot) => h("div", { className: "cp-range-row", key: slot },
        h("select", { className: "field", "data-rop": slot, "data-busy-lock": true, defaultValue: slot === 1 ? data.range?.first?.op || "ge" : data.range?.second?.op || "ge" },
          ...[["ge", "≥"], ["gt", ">"], ["le", "≤"], ["lt", "<"], ["eq", "="], ["ne", "≠"]].map(([key, label]) => h("option", { value: key, key }, label))),
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

  async function openPanel(column: string): Promise<void> {
    if (panel?.column === column) { setPanel(null); return; }
    setPanel({ column, data: null });
    try {
      const data = await controller.zone("filter_panel", { column }, true);
      setPanel((current) => current?.column === column ? { column, data } : current);
    } catch (error) {
      controller.notify(`필터를 불러오지 못했습니다: ${String(error)}`);
      setPanel(null);
    }
  }

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
  const showChips = snapshot.has_data && (filter.active || hiddenColumns.length);
  return createElement(Fragment, null,
    h("div", { className: "run-row run-recs-head", id: "jobRecsHead" },
      h("span", { className: "lbl", style: { fontWeight: 600 } }, "생성 대상 문서"),
      h("input", { className: "field jobsearch", id: "jobFilterSearch", type: "search", value: query,
        placeholder: "전체 열 검색", autoComplete: "off", "data-busy-lock": true,
        onChange: (event: Obj) => { setQuery(event.currentTarget.value); controller.scheduleSearch(event.currentTarget.value); } }),
      h("button", { className: "btn sm filter-reapply", id: "jobFilterReapply", hidden: !snapshot.has_data || !filter.reapply_available,
        title: filter.reapply_hint ? `직전 필터 재적용: ${filter.reapply_hint}` : "직전 필터 재적용", "data-busy-lock": true,
        onClick: async () => {
          const result = await controller.zone("filter_reapply", {});
          if (result.stale) return;
          if (!result.ok) controller.notify(`확인 필요: ${result.error}`);
        } }, "직전 필터 재적용"),
      h("div", { className: "acts" }, h("span", { className: "muted capnote", id: "jobSelCount" },
        `선택 ${selected}/${snapshot.record_count || 0}${filter.active ? ` · 표시 ${table.visible_count || 0}` : ""}`),
      h("button", { className: "btn sm", id: "jobSelAll", "data-busy-lock": true,
        onClick: () => { void controller.zone("set_all", {}); } }, "전체 선택"),
      h("button", { className: "btn sm", id: "jobSelNone", "data-busy-lock": true,
        onClick: () => { void controller.zone("set_none", {}); } }, "전체 해제"))),
    h("div", { className: "run-row job-orderbar", id: "jobOrderBar" },
      h("label", { className: "lbl", htmlFor: "jobOrderSel" }, "표시순서"),
      h("select", { className: "field sm", id: "jobOrderSel", "data-busy-lock": true,
        value: snapshot.range_draft?.open ? snapshot.range_draft.view_order || "sourceDesc" : snapshot.view_order || "sourceDesc",
        onChange: (event: Obj) => { void controller.zone("set_view_order", { value: event.currentTarget.value }); } },
      h("option", { value: "sourceDesc" }, "최신 행 먼저"), h("option", { value: "sourceAsc" }, "원본 순서")),
      h("span", { className: "muted capnote", id: "jobOrderNote" }, snapshot.order_note || "")),
    h("div", { className: "fchips", id: "jobFilterChips", hidden: !showChips },
      ...(filter.active ? (filter.chips || []).map((chip: string, index: number) => h("span", { className: "fchip definition", key: `c-${index}` },
        h("span", { className: "chip-role" }, "필터"), chip)) : []),
      ...(filter.active ? (filter.branches || []).map((branch: string) => h("span", { className: "fchip branch", key: branch },
        h("span", { className: "chip-role" }, "가지"), branch,
        h("button", { "data-prune": branch, "data-busy-lock": true, "aria-label": `${branch} 가지 제거`,
          onClick: () => { void controller.zone("filter_prune", { column: branch }); } }, "×"))) : []),
      filter.active ? h("button", { className: "btn sm", "data-act": "filter-clear", "data-busy-lock": true,
        onClick: () => { void controller.zone("filter_clear", {}); } }, "필터 지우기") : null,
      hiddenColumns.length ? h("span", { className: "fchip hidecols", title: hiddenColumns.join(", ") },
        h("span", { className: "chip-role" }, "보기"), `열 ${hiddenColumns.length}개 숨김 — 생성에는 그대로 쓰입니다`,
        h("button", { "data-act": "unhide-cols", "data-busy-lock": true, "aria-label": "숨긴 열 모두 표시",
          onClick: () => { void controller.zone("unhide_columns", {}); } }, "×")) : null),
    h("div", { className: "jobtb-host", id: "jobTableHost" },
      h(Scroll, { wrapRef },
        h("table", { className: "tb jobtb" },
          h("thead", { id: "jobTableHead" },
            h("tr", null,
              h("th", { className: "doccol" }, "문서",
                h("span", { className: "col-hint" }, "선택하면 파일명이 정해집니다")),
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
                    onClick: () => { void openPanel(column.name); },
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
            h("td", { className: "doccol" },
              h("div", { className: "doccell" },
                h("input", {
                  type: "checkbox", tabIndex: -1, checked: selectedFor(row), readOnly: true,
                  "aria-label": `${row.index + 1}행 선택`,
                }),
                h("span", { className: "doc-body" },
                  row.name
                    ? h("span", { className: "doc-name" }, row.name)
                    : h("span", { className: "doc-off", "aria-hidden": "true" }, "—"),
                  row.summary ? h("span", { className: "doc-sum" }, row.summary) : null))),
            ...(row.cells || []).map((cell: unknown, index: number) => {
              const column = columnMeta(table.columns[index]);
              return column.visible === false
                ? null
                : h("td", { className: `col-${column.kind || "text"}`, key: index },
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
  return h("div", { className: "range-foot", id: "jobRangeFoot" },
    h("p", { className: "muted", id: "jobRangeNote" }, draft.selected_only
      ? "선택된 항목만 보고 있습니다. 적용 전에는 문서 만들기 범위가 바뀌지 않습니다."
      : "전체 항목을 보고 있습니다. 적용 전에는 문서 만들기 범위가 바뀌지 않습니다."),
    h("button", { className: "btn", id: "jobRangeSelectedOnly", type: "button", "aria-pressed": draft.selected_only ? "true" : "false",
      "data-busy-lock": true, onClick: () => { void props.controller.call("job", "set_selected_only", { value: !draft.selected_only }); } }, "선택된 항목만 보기"),
    h("button", { className: "btn", id: "jobRangeCancel", type: "button", "data-busy-lock": true,
      onClick: () => { props.controller.closeDataSheet(); } }, "취소"),
    h("button", { className: "btn primary", id: "jobRangeApply", type: "button", "data-busy-lock": true,
      onClick: () => { void props.controller.applyRange(); } }, `선택 적용: ${draft.sel_count || 0}건`));
}
