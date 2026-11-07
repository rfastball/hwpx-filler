/* R4-01 DataZone 필터 빌더/칩의 순수 상태 — DOM·브리지 호출 없는 함수·타입·상수다. 상태와
   카드 행을 오가는 변환(`rowsFromState`·`stateFromRows`·`wordsFromRange`·`pickerKey`)은
   data_zone.ts가 쥐고, 그 변환이 쓰는 `blankRow`·`columnOf`·`kindOf`·`SEARCH_ROW` 등은 여기 둔다. */

type Obj = Record<string, any>;

/** 조건 = 열 하나당 카드 하나. 카드 편집기는 열 유형(Python 판정)을 따른다. */
export type BuilderSpec = { mode: "create" | "edit"; name: string };
/** 닫힌 뒤 초점이 갈 자리 — 연 단추(`trigger`) · 누른 자리 그대로(`none`) · 「+ 필터」(`new`) ·
 *  고친 칩(`{ edit: 새 이름 }` — 이름이 바뀌면 칩이 다시 그려지므로 이름으로 찾는다). */
export type BuilderFocus = "trigger" | "none" | "new" | { edit: string };
export type BuilderColumn = { name: string; kind: string; label?: string; values: string[]; more?: number };
type Clause = { op: string; operand: string };
export type BuilderRow = {
  id: number;
  column: string;
  mode: "range" | "values" | "text" | "search";
  values: string[];
  text: string;
  /** 비교 말(lt·le·gt·ge·eq·ne·between) — 범위 카드. */
  op: string;
  a: string;
  b: string;
  /** 7개 말로 옮길 수 없는 저장 범위(열 머리 메뉴의 2절 AND/OR) — 있으면 기호 2절 편집기로 선다. */
  legacy: { first: Clause; second: Clause; joiner: string } | null;
};

/** 「전체 열 검색」 카드의 열 자리 — 열 이름과 겹치지 않는 예약 값. */
export const SEARCH_ROW = "\u0000search";

/** 금액·날짜 비교 말 — 앞 여섯은 기존 연산자 1:1, 「사이」는 반개구간(≥ a 그리고 < b). */
export const RANGE_WORDS: ReadonlyArray<readonly [string, string]> = [
  ["lt", "미만 <"], ["le", "이하 ≤"], ["gt", "초과 >"], ["ge", "이상 ≥"],
  ["eq", "같음 ="], ["ne", "다름 ≠"], ["between", "사이"],
];

export const isRangeKind = (kind: string): boolean => kind === "amount" || kind === "date";

export function columnOf(columns: BuilderColumn[], name: string): BuilderColumn | undefined {
  return columns.find((column) => column.name === name);
}

export function kindOf(columns: BuilderColumn[], name: string): string {
  return columnOf(columns, name)?.kind || "";
}

export function blankRow(id: number, column: string, kind: string): BuilderRow {
  return {
    id, column,
    mode: column === SEARCH_ROW ? "search" : isRangeKind(kind) ? "range" : "values",
    values: [], text: "", op: "lt", a: "", b: "", legacy: null,
  };
}

/** 비교 말 + 피연산자 → 상태의 범위 dict(없으면 null). 「사이」의 빈 둘째 값은 1절 조건이다. */
export function rangeFromWords(op: string, a: string, b: string): Obj | null {
  if (!a.trim()) return null;
  if (op === "between") {
    return {
      first: { op: "ge", operand: a },
      second: b.trim() ? { op: "lt", operand: b } : null,
      joiner: "and",
    };
  }
  return { first: { op, operand: a }, second: null, joiner: "and" };
}

/** 금액 입력의 천 단위 쉼표 — 숫자 모양일 때만 다시 쓴다(「1억」 같은 말은 그대로 두고 Python 이 거절). */
export function formatAmount(raw: string): string {
  const text = raw.trim();
  const match = /^([-+]?)([\d,]+)(\.\d+)?$/.exec(text);
  if (!match || !/\d/.test(match[2])) return raw;
  const digits = match[2].replace(/,/g, "").replace(/^0+(?=\d)/, "");
  return `${match[1]}${digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${match[3] || ""}`;
}

/** 숨긴 열 접기 줄의 자리 — 열 이름과 겹치지 않는 예약 값. */
export const FOLD_ROW = "\u0000fold";

/** 콤보박스 목록 — Python 이 거른 열(자모 부분일치·강조 조각, 보이는 열 → 숨긴 열 순)에서 이미
 *  카드가 있는 열을 뺀다. 표에서 숨긴 열은 질의가 비어 있으면 「숨긴 열 N개」 줄 하나로 접히고
 *  (펼치면 흐리게 선다), 질의가 있으면 흐린 표지를 단 채 결과에 섞인다. 「전체 열 검색」은 늘
 *  마지막 줄이다(이미 카드가 있으면 빠진다). 빌더의 길이는 열 수가 아니라 조건 수를 따른다. */
export type PickerOption = {
  value: string; name: string; label: string; segments: Array<[string, boolean]>;
  muted: boolean; fold?: boolean; expanded?: boolean;
};
export function pickerOptions(
  matched: Obj[], rows: BuilderRow[], view: { query: string; expanded: boolean } = { query: "", expanded: false },
): PickerOption[] {
  const used = new Set(rows.map((row) => row.column));
  const toOption = (column: Obj): PickerOption => ({
    value: String(column.name), name: String(column.name), label: String(column.label || ""),
    segments: Array.isArray(column.segments) ? column.segments as Array<[string, boolean]> : [[String(column.name), false]],
    muted: !!column.hidden,
  });
  const open = matched.filter((column) => !used.has(String(column.name)));
  const shown = open.filter((column) => !column.hidden).map(toOption);
  const hidden = open.filter((column) => column.hidden).map(toOption);
  const options: PickerOption[] = [...shown];
  if (hidden.length && view.query.trim()) {
    options.push(...hidden);
  } else if (hidden.length) {
    options.push({
      value: FOLD_ROW, name: `숨긴 열 ${hidden.length}개`, label: "", segments: [[`숨긴 열 ${hidden.length}개`, false]],
      muted: true, fold: true, expanded: view.expanded,
    });
    if (view.expanded) options.push(...hidden);
  }
  if (!used.has(SEARCH_ROW)) {
    options.push({
      value: SEARCH_ROW, name: "전체 열 검색", label: "모든 열", segments: [["전체 열 검색", false]], muted: false,
    });
  }
  return options;
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

/** 빌더 배치 — **트리거에 붙은 채** 높이를 자른다(공용 `Popover.place` 는 넘치면 트리거 위로
 *  끌어올려 트리거를 가린다). 아래 공간(화면 아래 − 트리거 아래 − 16px)이 `min`(320px) 이상이거나
 *  위보다 넓으면 아래에, 아니면 위로 뒤집고, 어느 쪽이든 그 공간이 최대 높이다 — 카드 목록만
 *  스크롤하고 이름·footer 는 제자리다. 가로는 화면 안으로 민다. */
export function builderPlacement(
  anchor: { top: number; bottom: number; left: number },
  viewport: { width: number; height: number },
  width: number,
  opts: { edge?: number; gap?: number; min?: number } = {},
): { placement: "below" | "above"; maxHeight: number; left: number } {
  const edge = opts.edge ?? 16;
  const gap = opts.gap ?? 4;
  const min = opts.min ?? 320;
  const below = viewport.height - anchor.bottom - edge - gap;
  const above = anchor.top - edge - gap;
  const placeBelow = below >= min || below >= above;
  const left = Math.max(4, Math.min(anchor.left, viewport.width - 4 - width));
  return { placement: placeBelow ? "below" : "above", maxHeight: Math.max(0, placeBelow ? below : above), left };
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

/** 닫힌 뒤 초점이 돌아갈 자리 — 연 단추, 사라졌으면(삭제한 칩) 「+ 필터」. */
export function focusReturnTarget(trigger: HTMLElement | null, doc: Document): HTMLElement | null {
  if (trigger && trigger.isConnected) return trigger;
  return doc.querySelector<HTMLElement>('[data-act="filter-new"]');
}

/** `BuilderFocus` → 찾을 자리. 고친 칩은 이름으로 찾는다(선택자 이스케이프 없이 속성값 비교). */
export function focusFinder(
  focus: BuilderFocus, trigger: HTMLElement | null, doc: Document,
): (() => HTMLElement | null) | null {
  if (focus === "none") return null;
  if (focus === "trigger") return () => focusReturnTarget(trigger, doc);
  if (focus === "new") return () => doc.querySelector<HTMLElement>('[data-act="filter-new"]');
  return () => Array.from(doc.querySelectorAll<HTMLElement>("[data-preset]"))
    .find((element) => element.getAttribute("data-preset") === focus.edit) || null;
}
