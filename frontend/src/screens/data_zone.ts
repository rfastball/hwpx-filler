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
  // 팝오버는 **누른 자리** 아래에 선다(U4 계열1-9). 트리거는 ref 로 든다 — 상태에 넣으면
  // 배치 한 번에 재렌더가 한 번 더 붙는다.
  const panelRoot = useRef<HTMLElement | null>(null);
  const panelTrigger = useRef<HTMLElement | null>(null);
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
        title: "표를 원본 파일 순서로 봅니다. 생성 순서와 파일 이름 순번이 함께 따라갑니다.",
        onClick: () => {
          void controller.zone("set_view_order", {
            value: viewOrder === "sourceAsc" ? "sourceDesc" : "sourceAsc",
          });
        } }, "⇅ 원본 순서"),
      // 「펼쳐서 행 고르기」도 표를 여는 동사라 표 머리에 선다(U4 10번). **시트 안에서는
      // 그리지 않는다** — 자기 자신을 여는 단추는 무동작이고, 닫는 동사는 면 footer 의
      // 취소·적용이 이미 진다.
      ui.sheetOpen ? null : h("button", {
        className: "btn sm", id: "jobDataExpand", type: "button",
        onClick: (event: Obj) => { void controller.openDataSheet(event.currentTarget); },
      }, "펼쳐서 행 고르기 ⤢"))),
    // `#jobOrderBar` 는 id 를 유지한 채 **상시 재진술만** 든다 — 컨트롤이 표 머리로 갔어도
    // 「보이는 순서대로 생성되고 파일 이름 순번도 그 순서를 따른다」를 말하는 자리는 그대로다
    // (F3 판정 I: 확인 왕복 대신 문안이 진다).
    h("div", { className: "run-row job-orderbar", id: "jobOrderBar" },
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
          rootRef: panelRoot,
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
