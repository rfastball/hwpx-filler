/* 구조 투영 → HWPX 편집면 의미 표지 — `rhwp_editor.ts` 의 `setDecorations` 가 쓴다.
 *
 * 구조 트리 줄의 강조(UX-09): 가리킨 항목·선택은 강하게, 나머지 경계는 옅게 선다. 필드를 가리키면 그 필드의
 * 표지만 남긴다(필드 표지는 강약이 없어 다른 필드와 갈리지 않는다). 문서 모드에서는 가리킨 것만 선다.
 * 미리보기 범위(IDE-06 P-16, kind "range")는 Python 이 준 실제 포함 범위에 이름표 없는 합성 표지 하나로 선다 —
 * Studio 는 표지의 실체를 검사하지 않는다. 이름표가 있으면 실제 항목처럼 보이므로 이름표를 모두 걷는다.
 * 문제 표지(IDE-08 P-08)는 Python 의 problems[].location 에 선다 — 오류는 물결(strong), 경고는 점선(subtle) 밑줄이고
 * 문장은 포인터 설명이다. 문제는 표시가 아니라 경보라 문서 모드에서도 선다(TXT 와 같다). 표지 상한은 필드·항목 표지와
 * 나눠 쓰므로 넘치면 문제 표지부터 덜어 낸다(상한을 넘기면 장식 호출 전체가 던진다). */
import { DECORATION_LIMIT, markerAt } from "./rhwp_marks.ts";
import type { Marker } from "./rhwp_marks.ts";

type Obj = Record<string, unknown>;
type Emphasis = 'subtle' | 'strong';
type Labels = "none" | "all" | "selected";
type MarkKind = "field" | "slot" | "option";

type MarkContext = {
  sectionEntries: readonly string[]; highlight: Obj | null; region: boolean; documentMode: boolean;
  mode: unknown; markers: Marker[];
};

const isObj = (value: unknown): value is Obj => !!value && typeof value === "object";

/** The tree row the projection points at (or selected), if any. */
function highlightOf(projection: Obj): Obj | null {
  return projection.highlight && typeof projection.highlight === "object" ? projection.highlight as Obj : null;
}

/** The preview range's real extent, when the highlight is a range preview. */
function previewRange(highlight: Obj | null): Obj | null {
  return highlight?.kind === "range" && highlight.location && typeof highlight.location === "object" ? highlight.location as Obj : null;
}

/** The highlight points at this field occurrence, slot or option. */
function lit(highlight: Obj | null, kind: string, id: unknown, slotId?: unknown, index?: number): boolean {
  return !!highlight && highlight.kind === kind && highlight.id === id
    && (kind !== "option" || highlight.slot_id === slotId) && (kind !== "field" || highlight.index == null || highlight.index === index);
}

function emphasisOf(kind: MarkKind, on: boolean, region: boolean, mode: unknown): Emphasis {
  return on ? 'strong' : region && kind !== "field" ? 'subtle' : kind === 'field' || mode === 'structure' ? 'strong' : 'subtle';
}

function add(ctx: MarkContext, kind: MarkKind, label: string, place: Obj, shown = true): void {
  if (!shown) return;
  const on = kind === "field" ? ctx.highlight?.kind === "field" : ctx.region && lit(ctx.highlight, kind, place.__id, place.__slot);
  const made = markerAt(ctx.sectionEntries, kind, label, emphasisOf(kind, on, ctx.region, ctx.mode), place);
  if (made) ctx.markers.push(made);
}

function addFieldMarkers(ctx: MarkContext, field: Obj): void {
  const addOccurrence = (occurrence: unknown, at: number) => {
    const shown = ctx.highlight?.kind === "field" ? lit(ctx.highlight, "field", field.name, undefined, at + 1) : !ctx.documentMode;
    if (isObj(occurrence)) add(ctx, "field", String(field.name ?? ""), occurrence, shown);
  };
  (Array.isArray(field.occurrences) ? field.occurrences : []).forEach(addOccurrence);
}

function addOptionMarker(ctx: MarkContext, slot: Obj, option: Obj): void {
  if (option.location && typeof option.location === "object")
    add(ctx, "option", String(option.label ?? option.id ?? ""), { ...option.location as Obj, __id: option.id, __slot: slot.id },
      !ctx.documentMode || lit(ctx.highlight, "option", option.id, slot.id));
}

function addSlotMarkers(ctx: MarkContext, slot: Obj): void {
  if (slot.location && typeof slot.location === "object")
    add(ctx, "slot", String(slot.label ?? slot.id ?? ""), { ...slot.location as Obj, __id: slot.id },
      !ctx.documentMode || lit(ctx.highlight, "slot", slot.id, slot.id));
  for (const option of Array.isArray(slot.options) ? slot.options : []) {
    if (isObj(option)) addOptionMarker(ctx, slot, option);
  }
}

function addPreviewRange(ctx: MarkContext, range: Obj | null): void {
  // The preview range is one more marker only while the Studio's cap leaves room for it.
  const synthetic = range && markerAt(ctx.sectionEntries, ctx.highlight?.marker === "option" ? "option" : "slot", "", 'strong', range);
  if (synthetic && ctx.markers.length < DECORATION_LIMIT) ctx.markers.push(synthetic);
}

function labelsOf(documentMode: boolean, range: Obj | null, mode: unknown): Labels {
  // Template mode labels only the field under the caret or pointer (§3.2: labels never hide text);
  // structure mode labels every boundary. A preview range takes every label down.
  return documentMode || range ? "none" : mode === "structure" ? "all" : "selected";
}

/** The field/slot/option markers (and the preview range's synthetic marker) of a projection, before the shared cap
 *  fits proposals and problems in, and the label mode they are sent with. */
export function projectionMarkers(projection: Obj, sectionEntries: readonly string[]): { markers: Marker[]; labels: Labels } {
  const highlight = highlightOf(projection);
  const range = previewRange(highlight);
  const documentMode = projection.mode === "document";
  const ctx: MarkContext = { sectionEntries, highlight, documentMode, mode: projection.mode, markers: [],
    region: highlight?.kind === "slot" || highlight?.kind === "option" || !!range };
  for (const item of Array.isArray(projection.fields) ? projection.fields : []) {
    if (isObj(item)) addFieldMarkers(ctx, item);
  }
  for (const item of Array.isArray(projection.slots) ? projection.slots : []) {
    if (isObj(item)) addSlotMarkers(ctx, item);
  }
  addPreviewRange(ctx, range);
  return { markers: ctx.markers, labels: labelsOf(documentMode, range, projection.mode) };
}
