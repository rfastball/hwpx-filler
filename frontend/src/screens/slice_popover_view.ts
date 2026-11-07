/* 「가공」 팝오버의 순수 렌더 — 상태를 받아 그리기만 하는 `SlicePopoverView`와 그 하위 조각(방식 줄·
   입력 파트·머리·예시·미리보기·바닥), 팝오버 안 키 하나의 뜻(`sliceKeyAction`). 상태·동작(`SlicePopover`)과 명세 조립(`composeSliceSpec`)은
   slice_popover.ts 가 진다. 조각은 React 컴포넌트가 아니라 일반 렌더 함수(`renderMethodRow`·
   `renderSlicePart` 등)로 부른다 — 팝오버의 자식 자리와 재마운트 동작이 그대로 남는다. */
import { createElement } from "react";
import type { ReactNode } from "react";

import { icon } from "./icons.ts";
import type { Obj } from "./slice_popover.ts";

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

type Inputs = Record<string, Record<string, string>>;

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

/** 몇째 선택 칸 — 값은 Python 이 낸 옵션 목록이고 기본은 그 첫 값이다. */
function renderOrdinalPart(
  method: Obj, part: Obj, mode: string, key: string, value: string, index: number, on: ViewHandlers,
): ReactNode {
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

/** 글자/수 칸의 type·min·inputMode·칸 폭 보조 class — 네 속성을 "number" 여부 하나로
 *  같은 판정으로 정한다. */
function numberPartAttrs(
  part: Obj,
): { type: string; min: number | undefined; inputMode: string | undefined; numClass: string } {
  const isNumber = part.kind === "number";
  return {
    type: isNumber ? "number" : "text",
    min: isNumber ? 1 : undefined,
    inputMode: isNumber ? "numeric" : undefined,
    numClass: isNumber ? " num" : "",
  };
}

/** 방식 줄의 파트 하나 — 글자(장식 텍스트) · 몇째 선택 · 글자/수 입력 셋 중 하나를 그린다.
 *  `isFirstEmpty`는 소유 줄(`renderMethodRow`)이 파트 전체를 한 번 훑어 미리 고른 값이다
 *  (파트마다 흐르는 mutable 플래그를 없애 이 함수를 순수하게 둔다). */
function renderSlicePart(
  method: Obj, part: Obj, index: number, value: string, isFirstEmpty: boolean, on: ViewHandlers,
): ReactNode {
  if (!part.input) {
    return h("span", {
      key: `t${index}`, className: `slice-word${part.attach ? " attach" : ""}`,
    }, String(part.text));
  }
  const mode = String(method.mode);
  const key = String(part.input);
  if (part.kind === "ordinal") {
    return renderOrdinalPart(method, part, mode, key, value, index, on);
  }
  const { type, min, inputMode, numClass } = numberPartAttrs(part);
  return h("input", {
    key: `i${index}`,
    className: `field sm slice-in${part.wide ? " wide" : ""}${numClass}`,
    type, min, inputMode,
    "aria-label": String(part.label), "data-slice-input": `${mode}.${key}`,
    "data-slice-empty": isFirstEmpty ? mode : undefined,
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
}

/** 글자/수 입력 중 **처음** 빈 필수 칸의 input 키 — 「빈 칸이 남아 보내지 않았다」일 때
 *  그 칸으로 초점을 옮기는 자리를 고른다(몇째 선택·선택 칸은 빈 적이 없어 대상이 아니다). */
function firstEmptyInputKey(method: Obj, values: Record<string, string>): string | null {
  for (const part of (method.parts || []) as Obj[]) {
    if (!part.input || part.kind === "ordinal" || part.optional) continue;
    const key = String(part.input);
    if ((values[key] ?? "") === "") return key;
  }
  return null;
}

/** 후보 꼬리표 — 채점 결과(완전 일치 여부)에 따른 두 칠. */
function renderMethodTag(tag: Obj): ReactNode {
  return h("span", {
    className: `slice-tag ${tag.full ? "good" : "bad"}`, title: String(tag.tip || ""),
  }, String(tag.tag || ""));
}

/** 방식 하나의 줄 — 라디오 + 문장 파트들 + (있으면) 채점 꼬리표. */
function renderMethodRow(
  method: Obj,
  ctx: { inputs: Inputs; tags: Record<string, Obj>; selected: string | null; methodName: string; on: ViewHandlers },
): ReactNode {
  const { inputs, tags, selected, methodName, on } = ctx;
  const mode = String(method.mode);
  const values = inputs[mode] || {};
  const tag = tags[mode];
  const checked = selected === mode;
  const emptyKey = firstEmptyInputKey(method, values);
  const parts = ((method.parts || []) as Obj[]).map((part, index) => {
    const key = part.input ? String(part.input) : null;
    const value = key !== null ? (values[key] ?? "") : "";
    return renderSlicePart(method, part, index, value, key !== null && key === emptyKey, on);
  });
  return h("label", {
    key: mode, className: `slice-method${checked ? " on" : ""}`, "data-slice-method": mode,
  },
  h("input", {
    type: "radio", name: methodName, checked, value: mode,
    onChange: () => on.choose(method),
  }),
  ...parts,
  tag ? renderMethodTag(tag) : null);
}

/** 팝오버 머리 — 제목·열 이름·닫기 단추. */
function renderPopoverHead(field: string, column: string, titleId: string, on: ViewHandlers): ReactNode {
  return h("div", { className: "slicepop-head" },
    h("div", { className: "slicepop-title" },
      h("span", { id: titleId, className: "slicepop-name" }, `${field} 가공`),
      column ? h("span", { className: "slicepop-sub" }, `데이터 열 ${column}`) : null),
    h("button", {
      type: "button", className: "slicepop-x", "aria-label": "닫기", title: "닫기",
      "data-act": "slice-close", onClick: () => on.close(),
    }, icon("close")));
}

/** 예시 값 띠 — 고를 행 단추 줄 + 끌어 고르는 입력 칸 + 상태 한 줄. */
function renderSampleStrip(
  props: { preview: Obj | null; sampleBlock: Obj; sampleValue: string; hint: string; message: string;
    underRef?: { current: HTMLDivElement | null }; valueRef?: { current: HTMLInputElement | null };
    on: ViewHandlers },
): ReactNode {
  const { preview, sampleBlock, sampleValue, hint, message, underRef, valueRef, on } = props;
  return h("div", { className: "slicepop-strip" },
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
      h("div", { className: "slicepop-under", ref: underRef, "aria-hidden": "true" },
        String(sampleBlock.pre || ""),
        h("span", { className: "slicepop-keep" }, String(sampleBlock.keep || "")),
        String(sampleBlock.post || "")),
      h("input", {
        className: "slicepop-value", ref: valueRef, readOnly: true, value: sampleValue,
        "aria-label": "예시 값", title: "예시 값: 쓸 부분을 끌어 고르면 방식이 맞춰집니다",
        "data-slice-value": true, spellCheck: false,
        onMouseUp: () => on.selectEnd(),
        onKeyUp: (event: Obj) => on.selectKey(event),
        onScroll: () => on.scroll(),
      })),
    h("div", { className: "slicepop-status", role: "status", "aria-live": "polite" },
      hint ? h("span", { className: message ? "slicepop-none" : "slicepop-hint" }, hint) : null,
      sampleBlock.miss_tag
        ? h("span", { className: "slice-warn" }, String(sampleBlock.miss_tag)) : null));
}

/** 방식 목록 — 무리마다 캡션 + 그 무리의 방식 줄들. */
function renderMethodsGroup(
  groups: Obj[], titleId: string,
  methodRowCtx: { inputs: Inputs; tags: Record<string, Obj>; selected: string | null; methodName: string; on: ViewHandlers },
): ReactNode {
  return h("div", { className: "slicepop-methods", role: "radiogroup", "aria-labelledby": titleId },
    ...groups.flatMap((group) => [
      h("div", { key: `g-${String(group.label)}`, className: "slicepop-cap slicepop-group" },
        String(group.label)),
      ...((group.methods || []) as Obj[]).map((method) => renderMethodRow(method, methodRowCtx)),
    ]));
}

/** 원본 칸 — 남긴 자리(`keep`)를 앞뒤 글자 사이에 강조해 보인다. */
function renderPreviewOrig(item: Obj): ReactNode {
  return h("span", {
    key: `o${item.index}`, className: "slicepop-orig",
    title: `${item.pre || ""}${item.keep || ""}${item.post || ""}`,
  }, String(item.pre || ""),
  h("span", { className: "slicepop-keep" }, String(item.keep || "")),
  String(item.post || ""));
}

/** 결과 칸 — 채점 표지(marker)·홀로 다른 결과(odd) 칠 + 거절·경고 꼬리표들. */
function renderPreviewResult(item: Obj): ReactNode {
  const resultClass = `slicepop-res${item.marker ? " marker" : ""}${item.status === "odd" ? " odd" : ""}`;
  return h("span", { key: `r${item.index}`, className: "slicepop-out", "data-slice-status": item.status },
    h("span", { className: resultClass, title: String(item.result || "") }, String(item.result || "")),
    ...((item.tags || []) as string[]).map((text, index) =>
      h("span", { key: `t${index}`, className: "slice-warn" }, text)));
}

/** 미리보기 표의 한 행 — 원본(남긴 자리 강조) → 화살표 → 결과(채점 꼬리표 포함). */
function renderPreviewRow(item: Obj): ReactNode[] {
  return [
    h("span", { key: `n${item.index}`, className: "slicepop-rn" }, String(item.label)),
    renderPreviewOrig(item),
    h("span", { key: `a${item.index}`, className: "slicepop-arrow", "aria-hidden": "true" }, "→"),
    renderPreviewResult(item),
  ];
}

/** 빠짐 처리 단추 줄 — 서지 않으면(선택기 없음 계약) 아무 자리도 차지하지 않는다. */
function renderMissChoice(missChoice: Obj | null | undefined, pressed: string, on: ViewHandlers): ReactNode {
  if (!missChoice) return null;
  return h("div", { className: "slicepop-miss" },
    h("span", null, String(missChoice.label || "")),
    h("div", { className: "slicepop-seg", role: "group", "aria-label": String(missChoice.label || "") },
      ...((missChoice.choices || []) as Obj[]).map((choice) => h("button", {
        key: String(choice.value), type: "button",
        "aria-pressed": pressed === String(choice.value),
        "data-slice-miss": String(choice.value),
        onClick: () => on.miss(String(choice.value)),
      }, String(choice.label)))));
}

/** 미리보기 존 — 제목줄 + 표(불러온 행마다 원본·결과) + 빠짐 처리 단추. */
function renderPreviewZone(
  props: { preview: Obj | null; rows: Obj[]; missChoice: Obj | null | undefined; pressed: string; on: ViewHandlers },
): ReactNode {
  const { preview, rows, missChoice, pressed, on } = props;
  return h("div", { className: "slicepop-preview" },
    h("div", { className: "slicepop-preview-head" },
      h("span", { className: "slicepop-cap" }, String(preview?.rows_label || "")),
      h("span", { className: "slicepop-summary" }, String(preview?.summary || ""))),
    h("div", { className: "slicepop-grid" }, ...rows.flatMap(renderPreviewRow)),
    renderMissChoice(missChoice, pressed, on));
}

/** 팝오버 발 — 지우기·완료 두 동사. */
function renderPopoverFoot(spec: Obj | null, on: ViewHandlers): ReactNode {
  return h("div", { className: "slicepop-foot" },
    h("button", {
      type: "button", className: "btn sm quiet", "data-act": "slice-clear",
      disabled: !spec, onClick: () => on.clear(),
    }, "가공 지우기"),
    h("button", {
      type: "button", className: "btn sm primary", "data-act": "slice-done",
      onClick: () => on.close(),
    }, "완료"));
}

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
  const methodRowCtx = { inputs, tags, selected, methodName: "slice-method", on };
  const rows = (preview?.rows || []) as Obj[];
  const missChoice = preview?.miss_choice as Obj | null | undefined;
  const pressed = spec ? String(spec.on_missing || "empty") : "";
  return h("div", {
    className: "slicepop", ref: props.rootRef, role: "dialog", "aria-modal": "false",
    "aria-labelledby": titleId,
  },
  renderPopoverHead(field, column, titleId, on),
  renderSampleStrip({
    preview, sampleBlock, sampleValue, hint, message, underRef: props.underRef, valueRef: props.valueRef, on,
  }),
  h("div", { className: "slicepop-body" },
    renderMethodsGroup(groups, titleId, methodRowCtx),
    renderPreviewZone({ preview, rows, missChoice, pressed, on })),
  renderPopoverFoot(spec, on));
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
