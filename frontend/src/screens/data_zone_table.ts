/* R4-01 DataZone 표 렌더 조각 — 머리 줄·표 머리·표 본문·필터 밖 선택 띠. 재적용·지우기·
   표시순서·선택 동작은 `controller.zone("filter_reapply"/"filter_clear"/"set_view_order"/
   "set_none"/"set_all"/"toggle_record", …)`이 한다. React 컴포넌트가 아니라 `JobDataZone`이
   부르는 일반 렌더 함수다(스크롤 복원·낙관적 선택은 `JobDataZone`이 쥔다). */
import type { ReactNode } from "react";

import { icon } from "./icons.ts";
import { columnMeta, h, Segments } from "./data_zone.ts";
import type { JobReadController } from "./data_zone.ts";

type Obj = Record<string, any>;

/** 표시순서 축 — 초안이 열려 있으면 초안의 것이다(§18.11-21 — 적용 전 메인 범위 불변). */
function resolveViewOrder(snapshot: Obj): string {
  return String(
    snapshot.range_draft?.open
      ? snapshot.range_draft.view_order || "sourceDesc"
      : snapshot.view_order || "sourceDesc",
  );
}

/** 표시순서 스위치 — 이름표는 **지금 방향**을 말한다(기본값 `sourceDesc`=「↓ 아래 행부터」).
 *  표시순서는 2값 고정 축이라(F3 계약) select 가 아니라 스위치다. */
function renderOrderToggle(viewOrder: string, controller: JobReadController): ReactNode {
  const isAsc = viewOrder === "sourceAsc";
  return h("button", { className: "btn sm order-toggle", id: "jobOrderToggle", type: "button", "data-busy-lock": true,
    "aria-pressed": isAsc ? "true" : "false",
    // 이 컨트롤이 무슨 축을 모는지 DOM 이 **선언**한다 — `<select>` 시절 `options` 가
    // 지던 「2값 고정」(F3)을 스위치에서도 게이트가 되읽을 수 있어야 한다.
    "data-order-values": "sourceDesc,sourceAsc",
    title: "표의 정렬 순서를 바꿉니다. 생성 순서와 파일 이름 순번이 함께 따라갑니다.",
    onClick: () => {
      void controller.zone("set_view_order", { value: isAsc ? "sourceDesc" : "sourceAsc" });
    } },
  icon(isAsc ? "arrow-up" : "arrow-down"),
  h("span", null, isAsc ? "위 행부터" : "아래 행부터"));
}

export function renderRecsHead(
  props: {
    snapshot: Obj; filter: Obj; table: Obj; query: string; controller: JobReadController;
    onQueryChange(text: string): void;
  },
): ReactNode {
  const { snapshot, filter, table, query, controller, onQueryChange } = props;
  const selected = snapshot.zone_selected_count ?? snapshot.selected_count ?? 0;
  const total = snapshot.record_count || 0;
  const viewOrder = resolveViewOrder(snapshot);
  return h("div", { className: "run-row run-recs-head", id: "jobRecsHead", hidden: !snapshot.has_data },
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
        onChange: (event: Obj) => onQueryChange(event.currentTarget.value) })),
    h("button", { className: "btn sm filter-reapply", id: "jobFilterReapply", hidden: !snapshot.has_data || !filter.reapply_available,
      title: filter.reapply_hint ? `직전 필터 재적용: ${filter.reapply_hint}` : "직전 필터 재적용", "data-busy-lock": true,
      onClick: async () => {
        const result = await controller.zone("filter_reapply", {});
        if (result.stale) return;
        if (!result.ok) controller.notify(`확인 필요: ${result.error}`);
      } }, "직전 필터 재적용"),
    h("div", { className: "acts" }, h("span", { className: "muted capnote", id: "jobSelCount" },
      `선택 ${selected}/${total}${filter.active ? ` · 표시 ${table.visible_count || 0}/${total}` : ""}`),
    // 「모두 보기」 — 필터·검색이 서 있을 때만, 표시 수 바로 뒤의 조용한 글 링크다. 열 조건·검색·켜진
    // 저장한 필터를 전부 푼다(저장한 필터 정의는 남는다 — `FilterModel.clear`).
    filter.active ? h("button", {
      className: "btn showall", id: "jobShowAll", type: "button", "data-act": "filter-show-all",
      "data-busy-lock": true,
      onClick: () => { void controller.zone("filter_clear", {}); },
    }, "모두 보기") : null,
    // 「전체 선택/해제」 두 버튼은 표 머리 체크박스로 갔다(U4 11번). 그 자리가 곧 그 동사가
    // 겨누는 열이라, 표와 무관한 줄에서 표를 조작하던 어긋남이 사라진다.
    renderOrderToggle(viewOrder, controller)));
}

/** 표 머리 — 선택 체크박스(3상태, 보이는 행 기준) + 열마다 필터 단추. */
export function renderTableHeadRow(
  props: {
    table: Obj; filter: Obj; headChecked: boolean; headPartial: boolean; headSelectLabel: string;
    panelColumn: string | undefined; controller: JobReadController; openPanel: (column: string, trigger: HTMLElement) => void;
  },
): ReactNode {
  const { table, filter, headChecked, headPartial, headSelectLabel, panelColumn, controller, openPanel } = props;
  return h("tr", null,
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
      // 표지는 이 열을 조이는 모든 것(열 머리 조건 + 켜진 저장한 필터 무리)을 따른다 — 판정과
      // 문안(`constraints`)은 Python 이 싣고, title 이 무엇이 조이는지 이름으로 말한다.
      const meta = (filter.columns?.[index] || {}) as Obj;
      const constraints = Array.isArray(meta.constraints) ? meta.constraints as string[] : [];
      return h("th", { className: `col-${column.kind || "text"}`, key: column.name },
        h("span", null, column.name),
        h("button", {
          className: `fico${meta.filtered ? " on" : ""}`,
          "data-col": column.name,
          "data-busy-lock": true,
          "aria-label": `${column.name} 열 필터`,
          title: constraints.length ? constraints.join(" · ") : undefined,
          "aria-expanded": panelColumn === column.name,
          onClick: (event: Obj) => { void openPanel(column.name, event.currentTarget); },
        }, "▾"));
    }));
}

/** 표 몸 — 행마다 선택 표지·셀. 「문서」 열의 이름·요약은 걷혔고(U4 8번) 남는 것은 선택 표지
 *  하나다. */
export function renderTableBodyRows(
  props: { table: Obj; selectedFor(row: Obj): boolean; toggleRow(row: Obj, shift: boolean): void },
): ReactNode[] {
  const { table, selectedFor, toggleRow } = props;
  return (table.rows || []).map((row: Obj) => h("tr", {
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
  })));
}

/** 필터 밖 선택 스트립 — 「필터 밖 선택 N행도 생성에 포함됩니다」 + 행마다 해제. */
export function renderHiddenSelectionStrip(
  props: { snapshot: Obj; hidden: Obj[]; controller: JobReadController },
): ReactNode {
  const { snapshot, hidden, controller } = props;
  return h("div", { className: "fstrip", id: "jobSelStrip", hidden: !snapshot.has_data || !hidden.length },
    hidden.length ? `필터 밖 선택 ${hidden.length}행도 생성에 포함됩니다: ` : "",
    ...hidden.map((row: Obj) => h("span", { className: "fchip selection", key: row.index },
      h("span", { className: "chip-role" }, "선택"), row.name || row.summary || `${row.index + 1}행`,
      h("button", { "data-unsel": row.index, "data-busy-lock": true, "aria-label": `${row.index + 1}행 선택 해제`,
        onClick: () => { void controller.zone("toggle_record", { index: row.index, value: false }); } }, "×"))));
}
