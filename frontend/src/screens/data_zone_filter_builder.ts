/* R4-01 DataZone 필터 빌더(「+ 필터」·칩 메뉴 「고치기」). 저장·개수 세기는
   `controller.zone("update_filter_preset"/"create_filter_preset"/"count_filter_state", …)`·
   `deletePreset`(`"delete_filter_preset"`)이 한다.

   조건 = 열 하나당 카드 하나(상태 문법이 열마다 조건 하나를 든다). 카드는 세로로 쌓이고 사이에
   가운데 「그리고」 줄이 선다. 맨 아래에는 늘 점선 「새 조건」 카드가 있고, 그 안의 콤보박스가 열을
   고른다(40–60열 계약 목록에서 select 는 못 쓴다). 열 이름 거르기는 Python `list_filter_columns`
   가 한다 — 전체 열 검색과 같은 자모 부분일치를 브라우저에 다시 짓지 않는다. 「+ 필터」는 지금 열 조건
   (검색 포함)으로 채워 열고, 「비우고 시작」이 그 초안을 비운다.
   카드 편집기는 열 유형(Python 판정)을 따른다: 금액·날짜 = 한국어 비교 말 7개(「사이」 = ≥ a 그리고
   < b), 텍스트 = 값 고르기(태그) | 포함 글자. 열 머리 메뉴에서 건 2절 AND/OR 범위처럼 7개 말로
   옮길 수 없는 조건은 그 편집기(기호 2절) 그대로 보인다 — 옮기다 조용히 바꾸지 않는다.
   검증·수·요약·저장은 전부 Python 동사다. */
import { createElement, Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { deletePreset, rowsFromState, stateFromRows } from "./data_zone.ts";
import type { JobReadController } from "./data_zone.ts";
import {
  blankRow, builderKeyAction, builderPlacement, createCountRequester, kindOf,
} from "./data_zone_filter_state.ts";
import type { BuilderColumn, BuilderFocus, BuilderRow, BuilderSpec } from "./data_zone_filter_state.ts";
import { CardEditor, ColumnPicker } from "./data_zone_card_editor.ts";

type Obj = Record<string, any>;

function h(tag: any, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/** `builderPlacement` 를 DOM 에 적용한다 — 최대 높이를 먼저 걸고 잘린 실제 높이로 위치를 정한다. */
function placeBuilder(root: HTMLElement, anchor: HTMLElement, view: Window | null): void {
  if (!view) return;
  const rect = anchor.getBoundingClientRect();
  const plan = builderPlacement(rect, { width: view.innerWidth, height: view.innerHeight },
    root.getBoundingClientRect().width);
  const cap = `${Math.floor(plan.maxHeight)}px`;
  if (root.style.maxHeight !== cap) root.style.maxHeight = cap;
  const height = root.getBoundingClientRect().height;
  const top = plan.placement === "below" ? rect.bottom + 4 : rect.top - 4 - height;
  root.style.left = `${plan.left}px`;
  root.style.top = `${top}px`;
  root.style.transformOrigin = `${Math.max(8, rect.left + rect.width / 2 - plan.left)}px ${plan.placement === "below" ? "top" : "bottom"}`;
  root.dataset.placement = plan.placement === "below" ? "bottom" : "top";
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

/** 트리거에 **그린 뒤** 붙인다(`builderPlacement` — 넘치면 트리거를 가리지 않고 높이를 자른다).
 *  카드·오류·수가 바뀌면 높이가 바뀌므로 그릴 때마다 다시 재고, 자식(열 콤보박스 목록·태그)이
 *  스스로 자라도 같은 규칙으로 다시 잰다(빌더의 렌더를 거치지 않는 높이 변화). */
function useFilterBuilderPlacement(
  controller: JobReadController,
  rootRef: { current: HTMLElement | null },
  trigger: { current: HTMLElement | null },
): void {
  useLayoutEffect(() => {
    const root = rootRef.current;
    const anchor = trigger.current;
    if (root && anchor && anchor.isConnected) placeBuilder(root, anchor, controller.doc.defaultView);
  });
  useEffect(() => {
    const root = rootRef.current;
    const Observer = controller.doc.defaultView?.ResizeObserver;
    if (!root || !Observer) return;
    const observer = new Observer(() => {
      const anchor = trigger.current;
      if (anchor && anchor.isConnected) placeBuilder(root, anchor, controller.doc.defaultView);
    });
    observer.observe(root);
    return () => observer.disconnect();
  }, [controller, rootRef, trigger]);
}

/** 바깥 누름·Escape 로 닫는다 — 삭제 확인(공용 모달)이 떠 있는 동안은 `suspended`가 막는다. */
function useFilterBuilderDismiss(
  controller: JobReadController,
  rootRef: { current: HTMLElement | null },
  trigger: { current: HTMLElement | null },
  suspended: { current: boolean },
  closeRef: { current: (focus: BuilderFocus) => void },
): void {
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
}

/** 살아 있는 수 — 커밋된 상태가 바뀔 때마다 다시 묻고, 언마운트에서 발신기를 닫는다. */
function useFilterCount(
  controller: JobReadController, stateKey: string,
  setCount: (count: Obj | null) => void,
  setCountError: (error: { error: string; column: string }) => void,
): void {
  const requester = useRef<ReturnType<typeof createCountRequester> | null>(null);
  if (requester.current === null) {
    const view = controller.doc.defaultView;
    requester.current = createCountRequester({
      setTimer: (fn, ms) => view?.setTimeout(fn, ms),
      clearTimer: (handle) => view?.clearTimeout(handle as number),
      send: (candidate) => controller.zone("count_filter_state", { state: candidate }, true),
      apply: (result) => {
        if (result.stale) return;
        if (result.ok === false) {
          setCountError({ error: String(result.error || ""), column: String(result.column || "") });
          return;
        }
        setCountError({ error: "", column: "" });
        setCount(result);
      },
    });
  }
  useEffect(() => { requester.current?.request(JSON.parse(stateKey)); }, [stateKey]);
  useEffect(() => () => requester.current?.cancel(), []);
}

/** 고른 열의 카드가 선 뒤 그 카드의 첫 컨트롤로 초점을 옮긴다. */
function useFocusNewRow(focusRow: { current: number | null }, rootRef: { current: HTMLElement | null }): void {
  useEffect(() => {
    if (focusRow.current === null) return;
    const card = rootRef.current?.querySelector(`[data-fb-row="${focusRow.current}"]`);
    focusRow.current = null;
    card?.querySelector<HTMLElement>("[data-fb-first]")?.focus();
  });
}

/** 검색 카드가 프리필과 같은 글자로 그대로면 쳐낸 가지를 잇고, 고쳤으면 잃는다(쳐낸 가지 =
 *  검색 텍스트 수명). */
function resolvePrunedSearch(rows: BuilderRow[], initSearch: string, initPruned: string[]): string[] {
  const searchRow = rows.find((row) => row.mode === "search");
  return searchRow && searchRow.text.trim() === initSearch ? initPruned : [];
}

/** 오류는 가리키는 열의 카드 아래에, 열을 모르는 오류는 카드 목록 아래에 선다 — 저장 오류가
 *  수 오류보다 먼저다(둘 다 서면 저장 거절이 더 급하다). */
function resolveFailureCard(
  rows: BuilderRow[], saveError: { error: string; column: string }, countError: { error: string; column: string },
): { failure: { error: string; column: string }; cardOf: BuilderRow | undefined } {
  const failure = saveError.error ? saveError : countError;
  const cardOf = failure.column ? rows.find((row) => row.column === failure.column && row.mode === "range")
    || rows.find((row) => row.column === failure.column) : undefined;
  return { failure, cardOf };
}

/** 카드 목록 — 사이사이 「그리고」 줄, 맨 아래 늘 점선 「새 조건」 카드. */
function buildCardList(
  props: {
    rows: BuilderRow[]; columns: BuilderColumn[]; patch: (id: number, change: Partial<BuilderRow>) => void;
    remove: (id: number) => void; cardOf: BuilderRow | undefined; failure: { error: string; column: string };
    controller: JobReadController; choose: (column: string) => void; pickerRef: { current: HTMLInputElement | null };
  },
): ReactNode[] {
  const { rows, columns, patch, remove, cardOf, failure, controller, choose, pickerRef } = props;
  const listed: ReactNode[] = [];
  rows.forEach((row, index) => {
    if (index) listed.push(h("div", { className: "fb-and", key: `and-${row.id}`, "aria-hidden": "true" }, "그리고"));
    listed.push(h(CardEditor as any, {
      key: `row-${row.id}`, row, columns, patch, remove,
      error: cardOf && cardOf.id === row.id ? failure.error : "",
    }));
  });
  if (rows.length) listed.push(h("div", { className: "fb-and", key: "and-new", "aria-hidden": "true" }, "그리고"));
  listed.push(h(ColumnPicker as any, { key: "picker", controller, rows, choose, inputRef: pickerRef }));
  return listed;
}

/** 저장 왕복 — 고치기는 기존 이름·새 이름·상태를, 새로 만들기는 이름·상태·
 *  (열 머리에서 채웠으면) `from_adhoc` 표지를 싣는다. */
function savePreset(
  controller: JobReadController, spec: BuilderSpec, name: string, state: Obj, fromAdhoc: boolean,
): Promise<Obj> {
  return spec.mode === "edit"
    ? controller.zone("update_filter_preset", { name: spec.name, new_name: name, state })
    : controller.zone("create_filter_preset", {
      name, state, ...(fromAdhoc ? { from_adhoc: true } : {}),
    });
}

type SubmitOutcome =
  | { kind: "stale" }
  | { kind: "error"; error: string; column: string }
  | { kind: "ok"; focus: BuilderFocus };

/** 저장 응답의 뜻 — stale(세션이 그사이 갈림)·거절(사유·열)·성사(닫힌 뒤 초점) 셋. */
function resolveSubmitOutcome(result: Obj, spec: BuilderSpec, name: string): SubmitOutcome {
  if (result.stale) return { kind: "stale" };
  if (result.ok === false) {
    return { kind: "error", error: String(result.error || ""), column: String(result.column || "") };
  }
  return { kind: "ok", focus: spec.mode === "edit" ? { edit: String(result.name || name) } : "trigger" };
}

/** 수 상태 요약 — 아직 못 받았으면(count===null) 막대·행 수 어느 것도 그리지 않는다
 *  (`renderFbFoot`가 `count`로 그 여부를 판정한다). */
function resolveCountSummary(count: Obj | null, source: Obj): { total: number; matchedCount: number; ratio: number } {
  const total = Number(count?.total ?? source.total ?? 0);
  const matchedCount = Number(count?.count ?? 0);
  const ratio = total > 0 ? Math.min(1, matchedCount / total) : 0;
  return { total, matchedCount, ratio };
}

/** 열을 모르는 오류 — 가리키는 카드가 있으면 그 카드 아래가 이미 말하므로 여기 또 세우지 않는다. */
function renderUnplacedError(failure: { error: string }, cardOf: BuilderRow | undefined): ReactNode {
  if (!failure.error || cardOf) return null;
  return h("div", { className: "cp-err", role: "alert", "data-fb-error": true }, failure.error);
}

/** 머리 — 제목·열 머리 조건에서 채웠다는 표지·「비우고 시작」(새로 만들기이고 카드가 있을 때만). */
function renderFbHead(spec: BuilderSpec, fromAdhoc: boolean, rows: BuilderRow[], resetDraft: () => void): ReactNode {
  const title = spec.mode === "edit" ? "필터 고치기" : "필터 만들기";
  return h("div", { className: "cp-head fb-head" },
    h("span", { id: "jobFilterBuilderTitle" }, title),
    fromAdhoc ? h("span", { className: "fb-note", "data-fb-from-adhoc": true }, "열 머리 조건에서 채움") : null,
    spec.mode === "create" && rows.length ? h("button", {
      className: "btn sm quiet fb-reset", type: "button", "data-act": "fb-reset", "data-busy-lock": true,
      onClick: resetDraft,
    }, "비우고 시작") : null);
}

/** 발 — 삭제(고치기일 때만)·수 상태(진행률 막대)·취소·저장. */
function renderFbFoot(
  props: {
    spec: BuilderSpec; count: Obj | null; total: number; matchedCount: number; ratio: number; saving: boolean;
    removePreset: (button: HTMLElement) => void; close: (focus: BuilderFocus) => void; submit: () => void;
  },
): ReactNode {
  const { spec, count, total, matchedCount, ratio, saving, removePreset, close, submit } = props;
  return h("div", { className: "fb-foot" },
    spec.mode === "edit" ? h("button", {
      className: "btn sm quiet fb-delete", type: "button", "data-act": "fb-delete", "data-busy-lock": true,
      onClick: (event: Obj) => { void removePreset(event.currentTarget as HTMLElement); },
    }, "삭제") : null,
    h("div", { className: "fb-status", role: "status", "aria-live": "polite", "data-fb-count": true },
      count ? createElement(Fragment, null,
        h("span", { className: "fb-status-text" }, h("b", null, `${matchedCount}`), `행 / ${total}행`),
        h("span", { className: "fb-meter", "aria-hidden": "true" },
          h("span", { className: "fb-meter-fill", style: { transform: `scaleX(${Math.round(ratio * 1000) / 1000})` } })))
        : null),
    h("button", {
      className: "btn sm", type: "button", "data-act": "fb-cancel", onClick: () => close("trigger"),
    }, "취소"),
    h("button", {
      className: "btn sm primary", type: "button", "data-act": "fb-save", "data-busy-lock": true,
      disabled: saving, onClick: () => { void submit(); },
    }, "저장"));
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

  const clearSaveError = () => setSaveError({ error: "", column: "" });
  function patch(id: number, change: Partial<BuilderRow>): void {
    clearSaveError();
    setRows((current) => current.map((row) => (row.id === id ? { ...row, ...change } : row)));
  }
  function remove(id: number): void {
    clearSaveError();
    setRows((current) => current.filter((row) => row.id !== id));
    pickerRef.current?.focus();
  }
  function choose(column: string): void {
    clearSaveError();
    const id = nextId.current++;
    focusRow.current = id;
    setRows((current) => [...current, blankRow(id, column, kindOf(columns, column))]);
  }

  async function submit(): Promise<void> {
    if (saving) return;
    setSaving(true);
    clearSaveError();
    try {
      const result = await savePreset(controller, spec, name, state, fromAdhoc);
      const outcome = resolveSubmitOutcome(result, spec, name);
      if (outcome.kind === "stale") { close("trigger"); return; }
      if (outcome.kind === "error") { setSaveError({ error: outcome.error, column: outcome.column }); return; }
      close(outcome.focus);
    } catch (error) {
      setSaveError({ error: String(error), column: "" });
    } finally {
      setSaving(false);
    }
  }

  async function removePreset(button: HTMLElement): Promise<void> {
    suspended.current = true;
    try {
      const result = await deletePreset(controller, spec.name, button);
      if (result === null) return;
      if (result.stale) { close("trigger"); return; }
      if (result.ok === false) { setSaveError({ error: String(result.error || ""), column: "" }); return; }
      close("new"); // 지운 칩은 사라진다
    } finally {
      suspended.current = false;
    }
  }

  function resetDraft(): void {
    // 「비우고 시작」 — 지금 조건으로 채운 초안을 비운다(저장 전이라 잃는 것이 없다). 초안이 지금
    // 조건에서 오지 않았으므로 저장이 지금 조건을 접지도 않는다.
    clearSaveError();
    setRows([]);
    setFromAdhoc(false);
    pickerRef.current?.focus();
  }

  // 오류는 가리키는 열의 카드 아래에, 열을 모르는 오류는 카드 목록 아래에 선다.
  const { failure, cardOf } = resolveFailureCard(rows, saveError, countError);
  const listed = buildCardList({ rows, columns, patch, remove, cardOf, failure, controller, choose, pickerRef });
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
