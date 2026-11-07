/* 「가공」 칸 — 칩 하나와, 누르면 칩에 붙어 서는 편집 팝오버(연결 표·작업대 표 공용).

   칩은 지금 걸린 가공을 문장 하나로 말한다(`‘-’ 앞까지`, 없으면 점선 `+ 가공`). 팝오버는
   예시 값에서 **쓸 부분을 끌어 고르면** Python 이 그 글자를 재현하는 방식을 찾아 맞추고,
   왼쪽의 방식 문장(빈칸을 채우는 입력)으로 직접 고를 수도 있다. 오른쪽은 불러온 행마다
   원본·남긴 자리·결과·상태를 보여 준다.

   **뜻은 전부 Python 이 낸다**: 칩 문장(`slice_label`)·방식 문장 조각(`slice_methods`)·후보와
   그 채점(`propose_*`)·미리보기와 상태·요약(`preview_*`). 여기는 그 조각을 그리고, 입력 칸의
   글자를 명세 사전으로 모아(불완전하면 보내지 않는다) 편집 동사로 보낼 뿐이다 — 명세가 맞는지는
   도메인 판정기가 거절로 말한다.

   커밋 규약(연결 표의 다른 칸과 같다): 라디오·몇째 선택·빠짐 처리 단추는 고르는 순간이 곧
   커밋이다. 글자·수 입력은 blur·Enter 에서 커밋하고, 한글 조합 중에는 아무것도 하지 않는다.
   입력에 초점이 가면 그 방식이 **보이기만** 골라진다(Tab 으로 지나가며 가공을 바꾸지 않게) —
   고친 글자가 있을 때만 blur 가 보낸다. */
import { createElement, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { builderPlacement } from "./data_zone.ts";
import { SlicePopoverView } from "./slice_popover_view.ts";

export { SlicePopoverView } from "./slice_popover_view.ts";

export type Obj = Record<string, any>;
type Inputs = Record<string, Record<string, string>>;

/** 표면(편집기·작업대)이 이 칸에 건네는 문 — 정체(index·이름)는 표면이 감싼다. */
export type SlicePort = {
  doc: Document;
  /** 이 행의 팝오버가 열려 있는가(표면의 1슬롯 표지). */
  open: boolean;
  toggle(): void;
  close(): void;
  /** 명세(또는 해제 null)를 편집 동사로 보낸다 — 거절은 표면이 알린다. 성사 여부를 돌려준다. */
  commit(spec: Obj | null): Promise<boolean>;
  /** 불러온 행 미리보기(무변이 질의). `sample` 이 null 이면 Python 이 예시 행을 고른다. */
  preview(sample: number | null): Promise<Obj>;
  /** 예시 값에서 끌어 고른 UTF-16 범위 `[start, end)` 의 방식 후보(무변이 질의). */
  propose(sample: number, start: number, end: number): Promise<Obj>;
};

/** 키보드로 범위를 넓히는 동안(Shift+화살표) 후보를 한 번만 묻는 대기 시간(ms). */
const KEY_PROPOSE_DELAY = 300;

export function h(tag: any, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

/** 방식 목록을 평평하게 — 무리(일부만 쓰기·글자 고치기) 안의 방식 전부. */
export function flatMethods(groups: Obj[]): Obj[] {
  return groups.flatMap((group) => (group.methods || []) as Obj[]);
}

/** 명세 → 입력 칸 글자(방식별). 지금 걸린 방식의 칸만 채운다. */
export function seedInputs(spec: Obj | null): Inputs {
  if (!spec || !spec.mode) return {};
  const values: Record<string, string> = {};
  for (const [key, value] of Object.entries(spec)) {
    if (key === "mode" || key === "on_missing" || value === null || value === undefined) continue;
    values[key] = String(value);
  }
  return { [String(spec.mode)]: values };
}

/** 새 명세가 싣는 빠짐 처리 — 같은 방식을 고치거나, 사람이 고르는 칸이 있는 방식끼리 옮기면
 *  지금 값을 잇고, 아니면 Python 이 준 새 명세의 기본값이다. 키 없음은 빈 값이다. */
export function missPolicyFor(method: Obj, current: Obj | null, currentMethod: Obj | null): string | null {
  if (method.on_missing === null || method.on_missing === undefined) return null;
  if (current && (current.mode === method.mode || (method.miss_choice && currentMethod?.miss_choice))) {
    return String(current.on_missing || "empty");
  }
  return String(method.on_missing);
}

/** 입력 칸 글자로 명세를 모은다 — 필수 칸이 비었거나 수가 정수로 읽히지 않으면 `null`
 *  (보내지 않는다). 글자 칸은 공백 한 칸도 값이다(띄어쓰기로 나누기). 거절 문장은 Python 의 것이다. */
export function composeSliceSpec(
  method: Obj, values: Record<string, string>, current: Obj | null, currentMethod: Obj | null,
): Obj | null {
  const spec: Obj = { mode: String(method.mode) };
  for (const part of (method.parts || []) as Obj[]) {
    if (!part.input) continue;
    const key = String(part.input);
    let raw = values[key] ?? "";
    // 몇째 선택은 빈 적이 없다 — 아직 고르지 않았으면 보이는 첫 선택지(Python 목록의 첫 값)다.
    if (part.kind === "ordinal" && raw === "") raw = String(((part.options || []) as Obj[])[0]?.value ?? "");
    if (part.kind === "text") {
      if (raw === "") return null;
      spec[key] = raw;
      continue;
    }
    const text = raw.trim();
    if (text === "") {
      if (part.optional) continue;
      return null;
    }
    if (!/^-?\d+$/.test(text)) return null;
    spec[key] = Number(text);
  }
  const miss = missPolicyFor(method, current, currentMethod);
  if (miss === "keep") spec.on_missing = "keep";
  return spec;
}

/** 두 명세가 같은 뜻인가 — 키 순서·빈 값의 두 철자(키 없음·`"empty"`)를 접어 비교한다. */
export function sameSpec(a: Obj | null, b: Obj | null): boolean {
  const norm = (spec: Obj | null): string => {
    if (!spec) return "null";
    const out: Obj = {};
    for (const key of Object.keys(spec).sort()) {
      if (key === "on_missing" && (spec[key] === "empty" || spec[key] === undefined)) continue;
      out[key] = spec[key];
    }
    return JSON.stringify(out);
  };
  return norm(a) === norm(b);
}

/** 팝오버 안 키 하나의 뜻 — 한글 조합 중(Enter·Escape 가 조합 확정)은 아무 뜻도 없다. */
export function sliceKeyAction(
  event: { key: string; isComposing?: boolean; keyCode?: number },
): "close" | "commit" | null {
  if (event.isComposing || event.keyCode === 229) return null;
  if (event.key === "Escape") return "close";
  if (event.key === "Enter") return "commit";
  return null;
}

/* ---- 칩 ---- */

/** 「가공」 칸 — 칩과(열렸으면) 팝오버. `field` 는 접근 이름의 필드 이름, `chipProps` 는 표면의
 *  식별 속성(`data-act`·`data-index`·`id` 등)이다. */
export function SliceCell(props: {
  row: Obj; port: SlicePort; field: string; chipProps?: Obj;
}): ReactNode {
  const { row, port, field } = props;
  const chipRef = useRef<HTMLButtonElement | null>(null);
  const label = String(row.slice_label || "");
  const open = port.open && !!row.slice_enabled;
  return h("div", { className: "slicecell" },
    h("button", {
      ...(props.chipProps || {}),
      ref: chipRef, type: "button",
      className: `slicechip ${row.slice ? "set" : "add"}${open ? " open" : ""}`,
      "aria-label": `${field} 가공`, "aria-haspopup": "dialog", "aria-expanded": open,
      title: label, disabled: !row.slice_enabled,
      onClick: () => port.toggle(),
    }, label),
    open ? h(SlicePopover, { row, port, field, chipRef }) : null);
}

/* ---- 팝오버(상태) ---- */

type Draft = { mode: string; edited: boolean };

/** 팝오버를 칩 곁에 붙인다 — 넘치면 칩을 가리지 않고 높이를 자른다(필터 빌더와 같은 배치
 *  규칙). 칩에 **그린 뒤** 자리를 재므로 layout effect 하나, 그 자리가 늙는 사건(크기·스크롤·
 *  창 크기)마다 다시 재는 effect 하나로 선다 — `SlicePopover`가 쥐던 둘을 훅으로 승격했을
 *  뿐 의존성·순서·로직은 그대로다. */
function usePopoverPlacement(
  doc: Document,
  rootRef: { current: HTMLDivElement | null },
  anchorRef: { current: HTMLElement | null },
): void {
  function place(): void {
    const root = rootRef.current;
    const anchor = anchorRef.current;
    const view = doc.defaultView;
    if (!root || !anchor || !anchor.isConnected || !view) return;
    const rect = anchor.getBoundingClientRect();
    const plan = builderPlacement(rect, { width: view.innerWidth, height: view.innerHeight },
      root.getBoundingClientRect().width);
    const cap = `${Math.floor(plan.maxHeight)}px`;
    if (root.style.maxHeight !== cap) root.style.maxHeight = cap;
    const height = root.getBoundingClientRect().height;
    const top = plan.placement === "below" ? rect.bottom + 4 : rect.top - 4 - height;
    root.style.left = `${plan.left}px`;
    root.style.top = `${top}px`;
    root.dataset.placement = plan.placement === "below" ? "bottom" : "top";
  }

  useLayoutEffect(() => { place(); });
  useEffect(() => {
    const view = doc.defaultView;
    const root = rootRef.current;
    if (!view || !root) return undefined;
    const Observer = view.ResizeObserver;
    const observer = Observer ? new Observer(() => place()) : null;
    observer?.observe(root);
    const onScroll = (event: Event): void => {
      if (root.contains(event.target as Node)) return;
      place();
    };
    const onResize = (): void => place();
    doc.addEventListener("scroll", onScroll, true);
    view.addEventListener("resize", onResize);
    return () => {
      observer?.disconnect();
      doc.removeEventListener("scroll", onScroll, true);
      view.removeEventListener("resize", onResize);
    };
  }, [doc]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** 지금 걸린 명세가 가리키는 방식 — 명세가 없으면 없다. */
function resolveCurrentMethod(methods: Obj[], spec: Obj | null): Obj | null {
  if (!spec) return null;
  return methods.find((m) => m.mode === spec.mode) || null;
}

/** 입력 칸의 글자·보이기 선택·커밋 — `SlicePopover`가 쥐던 상태·동작 묶음을 훅으로
 *  승격했을 뿐 로직·순서는 그대로다(최초 state·effect 선언 순서만 바뀐다 — 옮겨진
 *  specKey 리셋 효과는 unmount 효과보다 먼저 서는데, unmount 효과의 설치부가 빈
 *  본문이라 두 효과의 순서는 관찰 가능한 차이를 내지 않는다).
 *
 *  `choose`가 빈 칸으로 초점을 옮기는 자리를 찾느라 `rootRef`를 읽는다 — 팝오버 DOM이지만
 *  이 훅이 함께 받는 이유는 그 조회가 입력 커밋 흐름 자체의 일부이기 때문이다(다른 자리로
 *  빼면 같은 "빈 칸 채우기" 결정이 두 곳에 흩어진다). */
function useSliceDraft(
  spec: Obj | null, currentMethod: Obj | null, methods: Obj[],
  send: (next: Obj | null) => void, rootRef: { current: HTMLDivElement | null },
): {
  inputs: Inputs; inputsRef: { current: Inputs }; pending: string | null;
  setInputs: (updater: (current: Inputs) => Inputs) => void;
  setPending: (mode: string | null) => void;
  clearDraft(): void;
  flushDraft(): void;
  choose(method: Obj): void;
  edit(mode: string, key: string, value: string): void;
  focusInput(mode: string): void;
  blurInput(mode: string): void;
  composingRef: { current: boolean };
} {
  const specKey = JSON.stringify(spec);
  const [pending, setPending] = useState<string | null>(null);
  const [inputs, setInputs] = useState<Inputs>(() => seedInputs(spec));
  const draftRef = useRef<Draft | null>(null);
  const inputsRef = useRef(inputs);
  inputsRef.current = inputs;
  const composingRef = useRef(false);

  // 명세가 바뀌면(커밋 성사·다른 표면의 편집) 그 방식의 칸을 새 값으로 채우고 보이기 선택을 푼다.
  useEffect(() => {
    setInputs((current) => ({ ...current, ...seedInputs(spec) }));
    setPending(null);
    draftRef.current = null;
  }, [specKey]); // eslint-disable-line react-hooks/exhaustive-deps

  function clearDraft(): void { draftRef.current = null; }

  /** 고친 입력이 있으면 그 방식의 명세를 보낸다(불완전하면 보내지 않고 보이기 선택만 남긴다). */
  function flushDraft(): void {
    const draft = draftRef.current;
    if (!draft || !draft.edited || composingRef.current) return;
    const method = methods.find((m) => m.mode === draft.mode);
    if (!method) return;
    const next = composeSliceSpec(method, inputsRef.current[draft.mode] || {}, spec, currentMethod);
    if (next === null) return;
    draftRef.current = { mode: draft.mode, edited: false };
    send(next);
  }

  function choose(method: Obj): void {
    const mode = String(method.mode);
    setPending(mode);
    const next = composeSliceSpec(method, inputsRef.current[mode] || {}, spec, currentMethod);
    if (next === null) {
      // 빈 칸이 남았다 — 첫 빈 칸으로 초점을 옮겨 채우게 한다(보내지 않는다).
      const empty = rootRef.current?.querySelector<HTMLElement>(`[data-slice-empty="${mode}"]`);
      empty?.focus();
      return;
    }
    send(next);
  }

  function edit(mode: string, key: string, value: string): void {
    setInputs((current) => ({ ...current, [mode]: { ...(current[mode] || {}), [key]: value } }));
    draftRef.current = { mode, edited: true };
  }

  function focusInput(mode: string): void {
    const draft = draftRef.current;
    if (draft && draft.mode !== mode && draft.edited) flushDraft();
    if (!draftRef.current || draftRef.current.mode !== mode) draftRef.current = { mode, edited: false };
    setPending(mode);
  }

  function blurInput(mode: string): void {
    if (composingRef.current) return;
    const draft = draftRef.current;
    if (draft && draft.mode === mode && draft.edited) {
      flushDraft();
      return;
    }
    // 고치지 않고 떠났다 — 보이기 선택을 커밋된 방식으로 되돌린다(같은 방식의 다음 칸이면 다시 선다).
    setPending(null);
  }

  return {
    inputs, inputsRef, pending, setInputs, setPending, clearDraft, flushDraft, choose, edit,
    focusInput, blurInput, composingRef,
  };
}

function SlicePopover(props: {
  row: Obj; port: SlicePort; field: string; chipRef: { current: HTMLElement | null };
}): ReactNode {
  const { row, port, field, chipRef } = props;
  const spec = (row.slice || null) as Obj | null;
  const specKey = JSON.stringify(spec);
  const groups = (row.slice_methods || []) as Obj[];
  const methods = flatMethods(groups);
  const currentMethod = resolveCurrentMethod(methods, spec);

  const rootRef = useRef<HTMLDivElement | null>(null);
  const valueRef = useRef<HTMLInputElement | null>(null);
  const underRef = useRef<HTMLDivElement | null>(null);
  const [sample, setSample] = useState<number | null>(null);
  const [preview, setPreview] = useState<Obj | null>(null);
  const [tags, setTags] = useState<Record<string, Obj>>({});
  const [message, setMessage] = useState("");
  const {
    inputs, inputsRef, pending, setInputs, setPending, clearDraft, flushDraft, choose, edit,
    focusInput, blurInput, composingRef,
  } = useSliceDraft(spec, currentMethod, methods, (next) => { void send(next); }, rootRef);
  const lastSelection = useRef("");
  const keyTimer = useRef<number | null>(null);
  const previewSeq = useRef(0);
  const alive = useRef(true);
  /* 표면은 그릴 때마다 새 문(`SlicePort`)을 건넨다 — 효과의 의존으로 두면 그릴 때마다 질의·
     listener 가 다시 선다. 문서는 바뀌지 않으므로 효과는 `doc` 에 걸고, 문·동작은 최신 것을 ref 로
     읽는다(한 번 붙인 listener 가 옛 명세로 커밋하지 않게). */
  const doc = port.doc;
  const portRef = useRef(port);
  portRef.current = port;
  const latest = useRef<{ close(focusChip: boolean): void; flush(): void; propose(): void }>({
    close() {}, flush() {}, propose() {},
  });

  useEffect(() => () => {
    alive.current = false;
    if (keyTimer.current !== null) doc.defaultView?.clearTimeout(keyTimer.current);
  }, [doc]);

  /** 늦게 온 옛 미리보기 응답(다른 명세·예시 행으로 넘어간 뒤 도착)은 세대 대조로 버린다. */
  function applyPreviewResult(result: Obj, seq: number): void {
    if (alive.current && seq === previewSeq.current) setPreview(result);
  }

  // 미리보기는 커밋된 명세·예시 행이 바뀔 때마다 다시 묻는다(늦게 온 옛 응답은 버린다).
  useEffect(() => {
    const seq = ++previewSeq.current;
    portRef.current.preview(sample).then(
      (result) => applyPreviewResult(result, seq),
      () => { /* 거절 문장은 표면이 알렸다 */ },
    );
  }, [specKey, sample]);

  useEffect(() => { valueRef.current?.focus(); }, []);

  usePopoverPlacement(doc, rootRef, chipRef);

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if (sliceKeyAction(event) !== "close" || composingRef.current) return;
      event.preventDefault();
      event.stopPropagation();
      latest.current.close(true);
    }
    function onDown(event: MouseEvent): void {
      const target = event.target as Node | null;
      if (!target || rootRef.current?.contains(target) || chipRef.current?.contains(target)) return;
      latest.current.flush();
      latest.current.close(false); // 바깥 누름은 누른 자리가 초점을 가진다
    }
    doc.addEventListener("keydown", onKey, true);
    doc.addEventListener("mousedown", onDown, true);
    return () => {
      doc.removeEventListener("keydown", onKey, true);
      doc.removeEventListener("mousedown", onDown, true);
    };
  }, [doc]); // eslint-disable-line react-hooks/exhaustive-deps

  function close(focusChip: boolean): void {
    portRef.current.close();
    if (focusChip) chipRef.current?.focus();
  }
  latest.current = { close, flush: () => flushDraft(), propose: () => propose() };

  async function send(next: Obj | null): Promise<void> {
    if (sameSpec(next, spec)) return;
    const ok = await port.commit(next);
    if (ok && alive.current) setMessage("");
  }

  function pickSample(index: number): void {
    lastSelection.current = "";
    setSample(index);
  }

  /** 끌어 고른 범위의 후보 응답을 반영한다 — 늦게 온 옛 응답(다른 범위를 고른 뒤 도착)은
   *  `lastSelection` 대조로 버린다. `propose`의 `.then` 콜백을 이름째 뽑아 그 복잡도를
   *  옮겼을 뿐 순서·판정은 그대로다. */
  function applyProposeResult(result: Obj, key: string): void {
    if (!alive.current || lastSelection.current !== key) return;
    const candidates = (result.candidates || []) as Obj[];
    const nextTags: Record<string, Obj> = {};
    const seeded: Inputs = {};
    for (const candidate of candidates) {
      nextTags[String(candidate.mode)] = candidate;
      Object.assign(seeded, seedInputs(candidate.slice));
    }
    setTags(nextTags);
    setInputs((current) => ({ ...current, ...seeded }));
    setMessage(String(result.message || ""));
    if (candidates.length) void send(candidates[0].slice);
  }

  function propose(): void {
    const input = valueRef.current;
    const sampleIndex = preview?.sample?.index;
    if (!input || typeof sampleIndex !== "number") return;
    const start = input.selectionStart ?? 0;
    const end = input.selectionEnd ?? 0;
    if (end <= start) return;
    const key = `${sampleIndex}:${start}:${end}`;
    if (key === lastSelection.current) return;
    lastSelection.current = key;
    port.propose(sampleIndex, start, end).then(
      (result) => applyProposeResult(result, key),
      () => { /* 거절 문장은 표면이 알렸다 */ },
    );
  }

  function proposeLater(): void {
    const view = doc.defaultView;
    if (!view) return;
    if (keyTimer.current !== null) view.clearTimeout(keyTimer.current);
    keyTimer.current = view.setTimeout(() => {
      keyTimer.current = null;
      latest.current.propose();
    }, KEY_PROPOSE_DELAY);
  }

  return h(SlicePopoverView, {
    field, column: String(row.source || ""), spec, groups, preview, tags, message,
    selected: pending ?? (spec ? String(spec.mode) : null), inputs, rootRef, valueRef, underRef,
    on: {
      close: () => { flushDraft(); close(true); },
      clear: () => { clearDraft(); void send(null); },
      choose, edit, focusInput, blurInput, pickSample,
      compose: (active: boolean) => { composingRef.current = active; },
      enter: () => flushDraft(),
      ordinal: (method: Obj, value: string) => {
        const mode = String(method.mode);
        setInputs((current) => ({ ...current, [mode]: { ...(current[mode] || {}), index: value } }));
        setPending(mode);
        const next = composeSliceSpec(
          method, { ...(inputsRef.current[mode] || {}), index: value }, spec, currentMethod);
        if (next !== null) void send(next);
      },
      miss: (value: string) => { if (spec) void send({ ...spec, on_missing: value }); },
      selectEnd: () => propose(),
      selectKey: (event: Obj) => {
        if (event.shiftKey || event.key === "Shift") proposeLater();
      },
      scroll: () => {
        if (underRef.current && valueRef.current) underRef.current.scrollLeft = valueRef.current.scrollLeft;
      },
    },
  });
}

