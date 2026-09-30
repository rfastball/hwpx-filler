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
import { icon } from "./icons.ts";

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

function h(tag: any, props: Obj | null, ...children: ReactNode[]): ReactNode {
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

function SlicePopover(props: {
  row: Obj; port: SlicePort; field: string; chipRef: { current: HTMLElement | null };
}): ReactNode {
  const { row, port, field, chipRef } = props;
  const spec = (row.slice || null) as Obj | null;
  const specKey = JSON.stringify(spec);
  const groups = (row.slice_methods || []) as Obj[];
  const methods = flatMethods(groups);
  const currentMethod = spec ? methods.find((m) => m.mode === spec.mode) || null : null;

  const rootRef = useRef<HTMLDivElement | null>(null);
  const valueRef = useRef<HTMLInputElement | null>(null);
  const underRef = useRef<HTMLDivElement | null>(null);
  const [sample, setSample] = useState<number | null>(null);
  const [preview, setPreview] = useState<Obj | null>(null);
  const [tags, setTags] = useState<Record<string, Obj>>({});
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [inputs, setInputs] = useState<Inputs>(() => seedInputs(spec));
  const draftRef = useRef<Draft | null>(null);
  const inputsRef = useRef(inputs);
  inputsRef.current = inputs;
  const composing = useRef(false);
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

  // 명세가 바뀌면(커밋 성사·다른 표면의 편집) 그 방식의 칸을 새 값으로 채우고 보이기 선택을 푼다.
  useEffect(() => {
    setInputs((current) => ({ ...current, ...seedInputs(spec) }));
    setPending(null);
    draftRef.current = null;
  }, [specKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // 미리보기는 커밋된 명세·예시 행이 바뀔 때마다 다시 묻는다(늦게 온 옛 응답은 버린다).
  useEffect(() => {
    const seq = ++previewSeq.current;
    portRef.current.preview(sample).then(
      (result) => { if (alive.current && seq === previewSeq.current) setPreview(result); },
      () => { /* 거절 문장은 표면이 알렸다 */ },
    );
  }, [specKey, sample]);

  useEffect(() => { valueRef.current?.focus(); }, []);

  // 칩에 **그린 뒤** 붙인다 — 넘치면 칩을 가리지 않고 높이를 자른다(필터 빌더와 같은 배치 규칙).
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
  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if (sliceKeyAction(event) !== "close" || composing.current) return;
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

  function place(): void {
    const root = rootRef.current;
    const anchor = chipRef.current;
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

  /** 고친 입력이 있으면 그 방식의 명세를 보낸다(불완전하면 보내지 않고 보이기 선택만 남긴다). */
  function flushDraft(): void {
    const draft = draftRef.current;
    if (!draft || !draft.edited || composing.current) return;
    const method = methods.find((m) => m.mode === draft.mode);
    if (!method) return;
    const next = composeSliceSpec(method, inputsRef.current[draft.mode] || {}, spec, currentMethod);
    if (next === null) return;
    draftRef.current = { mode: draft.mode, edited: false };
    void send(next);
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
    void send(next);
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
    if (composing.current) return;
    const draft = draftRef.current;
    if (draft && draft.mode === mode && draft.edited) {
      flushDraft();
      return;
    }
    // 고치지 않고 떠났다 — 보이기 선택을 커밋된 방식으로 되돌린다(같은 방식의 다음 칸이면 다시 선다).
    setPending(null);
  }

  function pickSample(index: number): void {
    lastSelection.current = "";
    setSample(index);
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
    port.propose(sampleIndex, start, end).then((result) => {
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
    }, () => { /* 거절 문장은 표면이 알렸다 */ });
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
      clear: () => { draftRef.current = null; void send(null); },
      choose, edit, focusInput, blurInput, pickSample,
      compose: (active: boolean) => { composing.current = active; },
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

/* ---- 팝오버(그리기) — 상태를 받아 그리기만 한다(정적 렌더 테스트의 대상). ---- */

type ViewHandlers = {
  close(): void; clear(): void;
  choose(method: Obj): void;
  edit(mode: string, key: string, value: string): void;
  focusInput(mode: string): void; blurInput(mode: string): void;
  pickSample(index: number): void;
  compose(active: boolean): void; enter(): void;
  ordinal(method: Obj, value: string): void;
  miss(value: string): void;
  selectEnd(): void; selectKey(event: Obj): void; scroll(): void;
};

const NOOP_HANDLERS: ViewHandlers = {
  close() {}, clear() {}, choose() {}, edit() {}, focusInput() {}, blurInput() {},
  pickSample() {}, compose() {}, enter() {}, ordinal() {}, miss() {},
  selectEnd() {}, selectKey() {}, scroll() {},
};

/** 팝오버 그리기 — 열린 명세·방식 목록·미리보기·후보 꼬리표·입력 글자를 받아 그린다. */
export function SlicePopoverView(props: {
  field: string; column: string; spec: Obj | null; groups: Obj[];
  preview: Obj | null; tags: Record<string, Obj>; message: string;
  selected: string | null; inputs: Inputs;
  rootRef?: { current: HTMLDivElement | null };
  valueRef?: { current: HTMLInputElement | null };
  underRef?: { current: HTMLDivElement | null };
  on?: ViewHandlers;
}): ReactNode {
  const { field, column, spec, groups, preview, tags, message, selected, inputs } = props;
  const on = props.on || NOOP_HANDLERS;
  const sampleBlock = (preview?.sample || {}) as Obj;
  const sampleValue = String(sampleBlock.value || "");
  const hint = message || String(preview?.hint || "");
  const titleId = "sliceTitle";
  const methodName = "slice-method";

  const methodRow = (method: Obj): ReactNode => {
    const mode = String(method.mode);
    const values = inputs[mode] || {};
    const tag = tags[mode];
    const checked = selected === mode;
    let firstEmptyMarked = false;
    const parts = ((method.parts || []) as Obj[]).map((part, index) => {
      if (!part.input) {
        return h("span", {
          key: `t${index}`, className: `slice-word${part.attach ? " attach" : ""}`,
        }, String(part.text));
      }
      const key = String(part.input);
      const value = values[key] ?? "";
      if (part.kind === "ordinal") {
        const options = (part.options || []) as Obj[];
        return h("select", {
          key: `i${index}`, className: "sel sm slice-ordinal", "aria-label": String(part.label),
          "data-slice-input": `${mode}.${key}`,
          value: value || String(options[0]?.value ?? ""),
          onFocus: () => on.focusInput(mode),
          onBlur: () => on.blurInput(mode),
          onChange: (event: Obj) => on.ordinal(method, String(event.currentTarget.value)),
        }, ...options.map((option) => h("option", {
          key: String(option.value), value: String(option.value),
        }, String(option.label))));
      }
      const markEmpty = !firstEmptyMarked && value === "" && !part.optional;
      if (markEmpty) firstEmptyMarked = true;
      return h("input", {
        key: `i${index}`,
        className: `field sm slice-in${part.wide ? " wide" : ""}${part.kind === "number" ? " num" : ""}`,
        type: part.kind === "number" ? "number" : "text",
        min: part.kind === "number" ? 1 : undefined,
        inputMode: part.kind === "number" ? "numeric" : undefined,
        "aria-label": String(part.label), "data-slice-input": `${mode}.${key}`,
        "data-slice-empty": markEmpty ? mode : undefined,
        autoComplete: "off", spellCheck: false, value,
        onFocus: () => on.focusInput(mode),
        onBlur: () => on.blurInput(mode),
        onChange: (event: Obj) => on.edit(mode, key, String(event.currentTarget.value)),
        onCompositionStart: () => on.compose(true),
        onCompositionEnd: () => on.compose(false),
        onKeyDown: (event: Obj) => {
          if (sliceKeyAction({
            key: event.key, isComposing: event.nativeEvent?.isComposing, keyCode: event.keyCode,
          }) !== "commit") return;
          event.preventDefault();
          on.enter();
        },
      });
    });
    return h("label", {
      key: mode, className: `slice-method${checked ? " on" : ""}`, "data-slice-method": mode,
    },
    h("input", {
      type: "radio", name: methodName, checked, value: mode,
      onChange: () => on.choose(method),
    }),
    ...parts,
    tag ? h("span", {
      className: `slice-tag ${tag.full ? "good" : "bad"}`, title: String(tag.tip || ""),
    }, String(tag.tag || "")) : null);
  };

  const rows = (preview?.rows || []) as Obj[];
  const missChoice = preview?.miss_choice as Obj | null | undefined;
  const pressed = spec ? String(spec.on_missing || "empty") : "";
  return h("div", {
    className: "slicepop", ref: props.rootRef, role: "dialog", "aria-modal": "false",
    "aria-labelledby": titleId,
  },
  h("div", { className: "slicepop-head" },
    h("div", { className: "slicepop-title" },
      h("span", { id: titleId, className: "slicepop-name" }, `${field} 가공`),
      column ? h("span", { className: "slicepop-sub" }, `데이터 열 ${column}`) : null),
    h("button", {
      type: "button", className: "slicepop-x", "aria-label": "닫기", title: "닫기",
      "data-act": "slice-close", onClick: () => on.close(),
    }, icon("close"))),
  h("div", { className: "slicepop-strip" },
    h("div", { className: "slicepop-strip-head" },
      h("span", { className: "slicepop-cap" }, "예시 값"),
      h("div", { className: "slicepop-samples" },
        ...((preview?.samples || []) as Obj[]).map((item) => h("button", {
          key: String(item.index), type: "button", className: "slicepop-sample",
          "aria-label": String(item.aria), "aria-pressed": !!item.pressed,
          "data-slice-sample": item.index,
          disabled: !!item.disabled, onClick: () => on.pickSample(Number(item.index)),
        }, String(item.label))))),
    h("div", { className: "slicepop-pick" },
      h("div", { className: "slicepop-under", ref: props.underRef, "aria-hidden": "true" },
        String(sampleBlock.pre || ""),
        h("span", { className: "slicepop-keep" }, String(sampleBlock.keep || "")),
        String(sampleBlock.post || "")),
      h("input", {
        className: "slicepop-value", ref: props.valueRef, readOnly: true, value: sampleValue,
        "aria-label": "예시 값", title: "예시 값: 쓸 부분을 끌어 고르면 방식이 맞춰집니다",
        "data-slice-value": true, spellCheck: false,
        onMouseUp: () => on.selectEnd(),
        onKeyUp: (event: Obj) => on.selectKey(event),
        onScroll: () => on.scroll(),
      })),
    h("div", { className: "slicepop-status", role: "status", "aria-live": "polite" },
      hint ? h("span", { className: message ? "slicepop-none" : "slicepop-hint" }, hint) : null,
      sampleBlock.miss_tag
        ? h("span", { className: "slice-warn" }, String(sampleBlock.miss_tag)) : null)),
  h("div", { className: "slicepop-body" },
    h("div", { className: "slicepop-methods", role: "radiogroup", "aria-labelledby": titleId },
      ...groups.flatMap((group) => [
        h("div", { key: `g-${String(group.label)}`, className: "slicepop-cap slicepop-group" },
          String(group.label)),
        ...((group.methods || []) as Obj[]).map(methodRow),
      ])),
    h("div", { className: "slicepop-preview" },
      h("div", { className: "slicepop-preview-head" },
        h("span", { className: "slicepop-cap" }, String(preview?.rows_label || "")),
        h("span", { className: "slicepop-summary" }, String(preview?.summary || ""))),
      h("div", { className: "slicepop-grid" },
        ...rows.flatMap((item) => [
          h("span", { key: `n${item.index}`, className: "slicepop-rn" }, String(item.label)),
          h("span", {
            key: `o${item.index}`, className: "slicepop-orig",
            title: `${item.pre || ""}${item.keep || ""}${item.post || ""}`,
          }, String(item.pre || ""),
          h("span", { className: "slicepop-keep" }, String(item.keep || "")),
          String(item.post || "")),
          h("span", { key: `a${item.index}`, className: "slicepop-arrow", "aria-hidden": "true" }, "→"),
          h("span", { key: `r${item.index}`, className: "slicepop-out", "data-slice-status": item.status },
            h("span", {
              className: `slicepop-res${item.marker ? " marker" : ""}${item.status === "odd" ? " odd" : ""}`,
              title: String(item.result || ""),
            }, String(item.result || "")),
            ...((item.tags || []) as string[]).map((text, index) =>
              h("span", { key: `t${index}`, className: "slice-warn" }, text))),
        ])),
      missChoice ? h("div", { className: "slicepop-miss" },
        h("span", null, String(missChoice.label || "")),
        h("div", { className: "slicepop-seg", role: "group", "aria-label": String(missChoice.label || "") },
          ...((missChoice.choices || []) as Obj[]).map((choice) => h("button", {
            key: String(choice.value), type: "button",
            "aria-pressed": pressed === String(choice.value),
            "data-slice-miss": String(choice.value),
            onClick: () => on.miss(String(choice.value)),
          }, String(choice.label))))) : null)),
  h("div", { className: "slicepop-foot" },
    h("button", {
      type: "button", className: "btn sm quiet", "data-act": "slice-clear",
      disabled: !spec, onClick: () => on.clear(),
    }, "가공 지우기"),
    h("button", {
      type: "button", className: "btn sm primary", "data-act": "slice-done",
      onClick: () => on.close(),
    }, "완료")));
}
