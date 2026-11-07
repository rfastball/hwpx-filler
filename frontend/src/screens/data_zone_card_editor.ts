/* R4-01 DataZone 필터 빌더의 조건 카드 편집기(`CardEditor`)와 열 고르기 콤보박스(`ColumnPicker`,
   data_zone.ts)의 목록 줄·질의 훅. 열 이름 거르기는 `controller.zone("list_filter_columns", …)`가 한다. */
import { createElement, useEffect, useRef } from "react";
import type { ReactNode } from "react";

import { icon } from "./icons.ts";
import type { JobReadController } from "./data_zone.ts";
import { Segments } from "./data_zone_cells.ts";
import { columnOf, formatAmount, isRangeKind, RANGE_OPS, RANGE_WORDS } from "./data_zone_filter_state.ts";
import type { BuilderColumn, BuilderRow } from "./data_zone_filter_state.ts";

type Obj = Record<string, any>;

function h(tag: any, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

type PatchFn = (id: number, patch: Partial<BuilderRow>) => void;

/** 열 머리 메뉴에서 건 2절 조건의 편집기(기호·결합자) — 7개 말로 옮기지 않고 그대로 보인다. */
function legacyRangeBody(row: BuilderRow, amount: boolean, name: string, patch: PatchFn): ReactNode {
  const legacy = row.legacy!;
  const clause = (key: "first" | "second") => [
    h("select", {
      className: "field", key: `op-${key}`, "data-busy-lock": true, value: legacy[key].op,
      "data-fb-first": key === "first" ? true : undefined,
      onChange: (event: Obj) => patch(row.id, { legacy: { ...legacy, [key]: { ...legacy[key], op: event.currentTarget.value } } }),
    }, ...RANGE_OPS.map(([value, text]) => h("option", { value, key: value }, text))),
    h("input", {
      className: `field fb-operand${amount ? " num" : ""}`, key: `val-${key}`, "data-busy-lock": true,
      value: legacy[key].operand, "aria-label": `${name} 값`,
      onChange: (event: Obj) => patch(row.id, { legacy: { ...legacy, [key]: { ...legacy[key], operand: event.currentTarget.value } } }),
    }),
  ];
  return h("div", { className: "fb-range" },
    h("div", { className: "cp-range-row" }, ...clause("first")),
    h("div", { className: "cp-range-row" },
      h("select", {
        className: "field", "data-busy-lock": true, value: legacy.joiner,
        onChange: (event: Obj) => patch(row.id, { legacy: { ...legacy, joiner: event.currentTarget.value } }),
      }, h("option", { value: "and" }, "그리고"), h("option", { value: "or" }, "또는")),
      ...clause("second")));
}

/** 한국어 비교 말 7개(범위 카드, 「사이」 = ≥ a 그리고 < b). */
function rangeWordsBody(row: BuilderRow, amount: boolean, name: string, error: string, patch: PatchFn): ReactNode {
  const operand = (key: "a" | "b", first: boolean) => h("input", {
    className: `field fb-operand${amount ? " num" : ""}`, key, "data-fb-operand": key, "data-busy-lock": true,
    "data-fb-first": first ? true : undefined, value: row[key], "aria-label": `${name} 값`,
    "aria-invalid": error ? "true" : undefined,
    onChange: (event: Obj) => patch(row.id, { [key]: event.currentTarget.value }),
    onBlur: amount ? (event: Obj) => {
      const next = formatAmount(event.currentTarget.value);
      if (next !== row[key]) patch(row.id, { [key]: next });
    } : undefined,
  });
  return h("div", { className: "fb-range-words" },
    h("select", {
      className: "field fb-word", "data-fb-word": true, "data-busy-lock": true, "data-fb-first": true,
      value: row.op, "aria-label": `${name} 비교`,
      onChange: (event: Obj) => patch(row.id, { op: event.currentTarget.value }),
    }, ...RANGE_WORDS.map(([value, text]) => h("option", { value, key: value }, text))),
    row.op === "between"
      ? h("div", { className: "fb-between" },
        operand("a", false), h("span", { className: "fb-unit" }, "이상"),
        operand("b", false), h("span", { className: "fb-unit" }, "미만"))
      : operand("a", false));
}

/** 값 고르기(태그) — 보이는 순서로 모은다(정의줄이 이 순서로 재진술하므로 순서가 뜻이다). */
function valuesBody(row: BuilderRow, column: BuilderColumn | undefined, name: string, patch: PatchFn): ReactNode {
  const listed = column?.values || [];
  const choices = [...row.values.filter((value) => !listed.includes(value)), ...listed];
  const more = Number(column?.more || 0);
  return h("div", { className: "fb-tags", role: "group", "aria-label": `${name} 값` },
    ...choices.map((value, index) => h("button", {
      type: "button", className: "fb-tag", key: `v-${value}`, "data-fb-val": value, "data-busy-lock": true,
      "data-fb-first": index === 0 ? true : undefined,
      "aria-pressed": row.values.includes(value) ? "true" : "false",
      onClick: () => {
        const picked = new Set(row.values);
        if (picked.has(value)) picked.delete(value); else picked.add(value);
        patch(row.id, { values: choices.filter((item) => picked.has(item)) });
      },
    }, value === "" ? "(빈값)" : value)),
    more > 0 ? h("span", { className: "fb-more" }, `…외 ${more}개`) : null);
}

/** 포함 글자 — 한 줄 입력. */
function textBody(row: BuilderRow, name: string, patch: PatchFn): ReactNode {
  return h("input", {
    className: "field", "data-fb-text": row.mode, "data-busy-lock": true, "data-fb-first": true,
    value: row.text, "aria-label": name,
    onChange: (event: Obj) => patch(row.id, { text: event.currentTarget.value }),
  });
}

/** 카드 본문 — 범위(2절 기호 · 7개 말) · 값 고르기 · 포함 글자 네 갈래. */
function cardBody(
  row: BuilderRow, column: BuilderColumn | undefined, amount: boolean, name: string, error: string, patch: PatchFn,
): ReactNode {
  if (row.mode === "range" && row.legacy) return legacyRangeBody(row, amount, name, patch);
  if (row.mode === "range") return rangeWordsBody(row, amount, name, error, patch);
  if (row.mode === "values") return valuesBody(row, column, name, patch);
  return textBody(row, name, patch);
}

/** 값 고르기 ↔ 포함 글자 전환 — 금액·날짜는 전환이 없다(그 열은 범위 카드로만 선다). */
function renderModeSegments(row: BuilderRow, name: string, patch: PatchFn): ReactNode {
  return h("div", { className: "fb-seg", role: "group", "aria-label": `${name} 조건 종류` },
    ...([["values", "값 고르기"], ["text", "포함 글자"]] as const).map(([mode, text]) => h("button", {
      type: "button", key: mode, className: "fb-seg-btn", "data-fb-seg": mode, "data-busy-lock": true,
      "aria-pressed": row.mode === mode ? "true" : "false",
      onClick: () => { if (row.mode !== mode) patch(row.id, { mode }); },
    }, text)));
}

export function CardEditor(props: {
  row: BuilderRow;
  columns: BuilderColumn[];
  error: string;
  patch: PatchFn;
  remove(id: number): void;
}): ReactNode {
  const { row, columns, error, patch, remove } = props;
  const column = columnOf(columns, row.column);
  const kind = column?.kind || "";
  const search = row.mode === "search";
  const name = search ? "전체 열 검색" : row.column;
  const kindLabel = search ? "모든 열" : String(column?.label || "");
  const amount = kind === "amount";
  const body = cardBody(row, column, amount, name, error, patch);
  const segmented = (row.mode === "values" || row.mode === "text") && !isRangeKind(kind)
    ? renderModeSegments(row, name, patch)
    : null;
  return h("div", { className: "fb-card", "data-fb-row": row.id, "data-fb-mode": row.mode, "data-fb-column": row.column },
    h("div", { className: "fb-card-head" },
      h("span", { className: "fb-card-name", title: name }, name),
      kindLabel ? h("span", { className: "fb-kind" }, kindLabel) : null,
      segmented,
      h("button", {
        className: "fb-remove", type: "button", "data-fb-remove": row.id, "data-busy-lock": true,
        "aria-label": `${name} 조건 지우기`, title: `${name} 조건 지우기`, onClick: () => remove(row.id),
      }, icon("close"))),
    h("div", { className: "fb-card-body" }, body),
    error ? h("div", { className: "cp-err", role: "alert", "data-fb-card-error": true }, error) : null);
}

/** 콤보박스 목록의 줄 하나 — 숨긴 열 접기 표지는 fold-mark, 그 밖은 유형 라벨을 꼬리에 단다. */
export function renderPickerOption(
  option: Obj, index: number, active: number, optionId: (index: number) => string,
  pick: (index: number) => void, setActive: (index: number) => void,
): ReactNode {
  return h("li", {
    key: option.value, id: optionId(index), role: "option",
    className: `fb-option${option.muted ? " muted" : ""}${option.fold ? " fold" : ""}`,
    "aria-selected": index === active ? "true" : "false",
    "aria-expanded": option.fold ? (option.expanded ? "true" : "false") : undefined,
    "data-fb-option": option.fold ? "fold" : option.value,
    onMouseDown: (event: Obj) => { event.preventDefault(); pick(index); },
    onMouseEnter: () => setActive(index),
  },
  h("span", { className: "fb-option-name", title: option.name }, h(Segments as any, { value: option.segments })),
  option.fold
    ? h("span", { className: "fb-fold-mark", "aria-hidden": "true" }, icon("chevron-right"))
    : h("span", { className: "fb-kind" }, option.label));
}

/** 열 이름 질의 — 목록이 열려 있는 동안 질의마다 80ms 쉼 뒤 한 번 묻고, 늦게 온 옛 응답은
 *  세대 대조로 버린다. */
export function useFilterColumnQuery(
  controller: JobReadController, open: boolean, query: string, setMatched: (columns: Obj[]) => void,
): void {
  const seq = useRef(0);
  useEffect(() => {
    if (!open) return;
    const mine = ++seq.current;
    const view = controller.doc.defaultView;
    const handle = view?.setTimeout(() => {
      void controller.zone("list_filter_columns", { query }, true).then((result) => {
        if (mine === seq.current && result && result.ok !== false) setMatched((result.columns || []) as Obj[]);
      }, () => undefined);
    }, 80);
    return () => { if (handle !== undefined) view?.clearTimeout(handle); };
  }, [controller, open, query]);
}


