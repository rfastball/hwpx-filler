import { createStudio } from "../../vendor/rhwp/editor/index.js";
import { DECORATION_LIMIT, markerAt, studioCellPath, wireSelection } from "./rhwp_marks.ts";
import type { HostLineRect, Marker, WireSelection } from "./rhwp_marks.ts";
export type { HostLineRect } from "./rhwp_marks.ts";
import { decorationLedger } from "./rhwp_decorations.ts";
import type { SpotClick } from "./rhwp_decorations.ts";
export { DECORATION_LIMIT } from "./rhwp_marks.ts";

type Obj = Record<string, unknown>;

const isIndex = (n: unknown): n is number => Number.isSafeInteger(n) && (n as number) >= 0;

export type RhwpMountSpec = {
  host: HTMLElement; content: string; fileName: string; sectionEntries?: string[];
  /** The caret/selection the Studio reports, with the caret line in host client coordinates when it is visible
   *  (a proposal popover stands beside it, #1156). An empty object = no usable selection. */
  onChanged: (content: string) => void; onSelectionChanged: (selection: WireSelection | Obj, caret?: HostLineRect | null) => void;
  /** The selection end (caret) line in host client coordinates, for UI placed beside the selection (IDE-08).
   *  Reported once a new non-empty selection settles (never while a pointer drag still extends it); null
   *  when the selection collapses or changes, the document is edited, or the reported line moves (scroll,
   *  zoom). The same selection is not re-reported after an edit or a move. */
  onSelectionRect?: (rect: HostLineRect | null) => void;
  /** The caret (selection end) line moved under an unchanged selection (scroll, zoom, relayout): its new line in
   *  host client coordinates, or null when it left the frame. A UI anchored to the caret or to a clicked spot (#1156
   *  proposal popover) follows it or hides; the selection itself is not re-reported. */
  onCaretRect?: (caret: HostLineRect | null) => void;
  /** A click on a link-like decoration (a #1156 proposal or held spot): the Studio has already selected the spot's
   *  whole range. `token` is the spot id the decoration was sent with (`setDecorations` proposals), `rect` the clicked
   *  line in host client coordinates (null when it is outside the frame). */
  onDecorationClick?: (click: SpotClick) => void;
  onError: (error: unknown) => void; onShortcut?: (shortcut: RhwpShortcut) => void;
  /** Document right-click or keyboard menu key (Shift+F10, ContextMenu) inside the editor, in
   *  host client coordinates (the keyboard menu opens under the caret). Given = the host's menu
   *  replaces the Studio's own. */
  onContextMenu?: (point: { x: number; y: number }) => void;
  /** Range pick clicks (see `RhwpHandle.rangePick`): the body point under each click, a table cell folded to its
   *  table's anchor paragraph (`cell`). Never raised by caret moves or key presses. */
  onRangePick?: (point: PickPoint) => void;
  /** Accessible name of the editor iframe. */
  title?: string;
  preflight?: (exported: string) => Promise<{ editable: boolean; diagnostics?: unknown[] }>;
  onCompatibility?: (result: { editable: boolean; diagnostics?: unknown[] }) => void;
  readOnly: boolean;
  /** Studio zoom set explicitly after every document load (IDE-06): `"fit"` = the Studio's own
   *  `view:zoom-fit-width` (re-applied when the host is resized), a number = the fixed `view:zoom-N`.
   *  The Studio persists its fit mode in the iframe origin's shared settings and restores it on the next
   *  load, so every mount states its mode — default fixed 100 (the comparison viewers).
   *  The main editor passes "fit" or 100 (the shell's CSS zoom scales a fixed page); the trial viewer 75. */
  zoom?: RhwpZoom;
  /** Who needs caret reports: "visible" polls only while the host is rendered (not inside a
   *  `hidden`/`inert` ancestor); "never" skips polling (viewers nobody reads the selection of).
   *  Default "visible". */
  trackSelection?: "visible" | "always" | "never";
  /** Test seam only: the product always mounts the pinned SDK's `createStudio`. */
  studio?: typeof createStudio;
};
/** One range-pick point on the Python wire: a body paragraph of a section entry and a character offset. */
export type PickPoint = { entry: string; paragraph: number; offset: number; cell: boolean };
/** One text line in host client coordinates (the line's top and bottom at a horizontal position). */
/** Studio zoom mode: fit the page width to the editor, or a fixed percent. */
export type RhwpZoom = "fit" | 50 | 75 | 100;
const zoomCommand = (zoom: RhwpZoom) => zoom === "fit" ? "view:zoom-fit-width" : `view:zoom-${zoom}`;
/** The iframe's width: the host's width rounded down to a whole CSS pixel. At fractional device-pixel
 *  ratios (175%) a host can be 835.43px wide; the Studio then sizes its page area to the integer
 *  clientWidth and the sub-pixel remainder becomes a horizontal scroll range with a visible scrollbar
 *  and nothing to scroll. CSS does the rounding at layout time, so a percentage stays a percentage
 *  (no observer writes, no intrinsic-size feedback); a WebView without CSS `round()` drops the value
 *  and the stylesheet's `width: 100%` applies. */
export const FRAME_WIDTH = "round(down, 100%, 1px)";
/** Refit delay after the host stops resizing (panel drags and window resizes arrive in bursts). */
export const REFIT_DEBOUNCE_MS = 120;

/** Keys the Studio forwards to the host shell (spec §10). Escape comes only when no Studio UI claimed it. */
export type RhwpShortcut = 'F2' | 'CtrlShiftP' | 'CtrlS' | 'CtrlF' | 'Escape' | 'F6' | 'ShiftF6';
type Appearance = { theme: 'light' | 'dark' | 'system'; fontScale: 1 | 1.25 | 1.5 };

/** The app's theme and font scale (`html[data-theme]`, `html[data-font-scale]`) as the Studio takes them. */
export function hostAppearance(root: { getAttribute(name: string): string | null } | null | undefined): Appearance {
  const theme = root?.getAttribute("data-theme");
  const scale = root?.getAttribute("data-font-scale");
  return { theme: theme === "light" || theme === "dark" ? theme : "system",
    fontScale: scale === "larger" ? 1.5 : scale === "large" ? 1.25 : 1 };
}

export type RhwpHandle = {
  content(): Promise<string>; applySnapshot(content: string, label: string, expectedContent?: string): Promise<void>;
  flushChanges(): Promise<void>;
  focus(target: Obj): Promise<void>; undo(): Promise<void>; redo(): Promise<void>;
  /** Scroll the viewport to the target's range (same targets as `focus`) without moving the caret or DOM
   *  focus (IDE-08 H4). False = the Studio could not place the range; the view stays where it was. */
  scrollTo(target: Obj): Promise<boolean>;
  setDecorations(projection: Obj): Promise<void>; setReadOnly(readOnly: boolean): Promise<void>;
  /** Switch the Studio zoom mode (see `RhwpMountSpec.zoom`). */
  setZoom(zoom: RhwpZoom): Promise<void>;
  /** The host's range pick: `false` off; `null` on (presses report `onRangePick` and never move the caret); a point
   *  on with that start (the Studio draws the band from it to the point under the pointer, following scrolls). */
  rangePick(state: PickPoint | null | false): Promise<void>;
  dispose(): void;
};

/** Trailing debounce for HWPX export after edits: a burst of change events costs one export. */
export const EXPORT_DEBOUNCE_MS = 200;
const SELECTION_POLL_MS = 300;
/** How long after a host-set selection its centring scroll may still move the reported line (two polls and a frame). */
export const HOST_MOVE_SETTLE_MS = 900;

/** The host is rendered: no `hidden`/`inert` ancestor (inactive document tabs) and laid out. */
function hostRendered(host: HTMLElement): boolean {
  if (typeof host.closest === "function" && host.closest("[hidden],[inert]")) return false;
  return !("offsetParent" in host) || host.offsetParent !== null;
}

function decodeBase64(value: string): Uint8Array {
  return Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
}
function encodeBase64(bytes: Uint8Array): string {
  let result = "";
  for (let offset = 0; offset < bytes.length; offset += 32768)
    result += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  return btoa(result);
}

/** The pinned SDK owns the iframe and MessageChannel; this module owns its lifetime. */
export async function mountRhwp(spec: RhwpMountSpec): Promise<RhwpHandle> {
  const root = document.documentElement;
  let appearance = hostAppearance(root);
  // The Studio applies the host theme before its first paint (theme-init.js); later changes go by message.
  const studioUrl = new URL("/rhwp/studio/index.html", document.baseURI);
  studioUrl.searchParams.set("hostTheme", appearance.theme);
  studioUrl.searchParams.set("hostFontScale", String(appearance.fontScale));
  // The product keeps no recovery drafts (#1068): every mount (editor, trial result, comparison) turns the Studio's
  // own autosave off — no interval or idle draft is written and no 「문서 복구」 dialog offers another document's body.
  studioUrl.searchParams.set("autosave", "off");
  const editor = await (spec.studio ?? createStudio)(spec.host, { studioUrl: studioUrl.href, plugins: ["hwpctrl"], width: FRAME_WIDTH,
    chrome: { menu: false, toolbar: !spec.readOnly, statusbar: false }, ...(spec.title ? { title: spec.title } : {}) });
  let disposed = false, readOnly = spec.readOnly, compatibilityBlocked = false, replacing = false, lastSelection = "", caretLine = "";
  let changeGeneration = 0, lastEmittedContent = spec.content;
  let pendingChange: Promise<void> | null = null;
  // Debounced export: `scheduled` means a change arrived that no export has started for yet.
  let scheduled = false, exportTimer: number | undefined;
  const sectionEntries = spec.sectionEntries ?? [];
  let zoom: RhwpZoom = spec.zoom ?? 100;
  try {
    await editor.setAppearance(appearance);
    if (spec.onContextMenu) await editor.setContextMenuForwarding(true);
    await editor.loadFile(decodeBase64(spec.content), spec.fileName, { skipUnsavedGuard: true });
    if (!readOnly) {
      let result: { editable: boolean; diagnostics?: unknown[] };
      try {
        const exported = encodeBase64(await editor.exportHwpx());
        result = spec.preflight
          ? await spec.preflight(exported)
          : { editable: false, diagnostics: ['HWPX 보존 검사를 실행할 수 없습니다.'] };
        if (result.editable) lastEmittedContent = exported;
      } catch (error) {
        result = { editable: false, diagnostics: [String(error)] };
      }
      if (!result.editable) {
        readOnly = true; compatibilityBlocked = true;
        await editor.chrome.set({ toolbar: false });
        spec.onCompatibility?.(result);
        if (!spec.onCompatibility) spec.onError(new Error(String(result.diagnostics?.[0] ?? 'HWPX 보존 검사를 통과하지 못했습니다.')));
      }
    }
    await editor.setReadOnly(readOnly);
    await editor.commands.execute(zoomCommand(zoom));
  } catch (error) { editor.destroy(); throw error; }
  const content = async () => encodeBase64(await editor.exportHwpx());
  const publish = async (generation: number) => {
    const bytes = await content();
    if (disposed || generation !== changeGeneration || bytes === lastEmittedContent) return;
    lastEmittedContent = bytes;
    spec.onChanged(bytes);
  };
  // Selection-side rect (IDE-08 H3): the selection key the rect belongs to, the last rect seen for it ("" =
  // none yet, e.g. mid-drag), whether the host is showing it, and whether it may not come back (edited or moved).
  let rectKey = "", rectSeen = "", rectShown = false, rectSpent = false;
  // A selection the host set (`focus`) is followed by the Studio's own centring scroll, which lands after the first
  // report: until this time a moved line is that scroll settling, not the user scrolling — the rect follows it.
  let hostMoveUntil = 0;
  const hideRect = (spent: boolean) => {
    if (spent) rectSpent = true;
    if (rectShown) { rectShown = false; spec.onSelectionRect?.(null); }
  };
  /** A reported Studio rect in host coordinates, or null when it is not visible inside the frame. */
  const visibleRect = (rect: { x: number; y: number; width: number; height: number } | null): HostLineRect | null => {
    if (!rect) return null;
    let height = 0;
    try { height = editor.element.contentWindow?.innerHeight ?? 0; } catch { height = 0; }
    if (height && (rect.y + rect.height <= 0 || rect.y >= height)) return null;
    const top = hostPoint(rect.x, rect.y), bottom = hostPoint(rect.x, rect.y + rect.height);
    return { left: top.x, top: top.y, bottom: bottom.y };
  };
  const reportRect = (key: string, rect: { x: number; y: number; width: number; height: number } | null) => {
    if (!spec.onSelectionRect) return;
    const seen = rect ? JSON.stringify(rect) : "";
    if (!key) { rectKey = ""; rectSeen = ""; rectSpent = false; hideRect(false); return; }
    if (key !== rectKey) { rectKey = key; rectSeen = ""; rectSpent = false; hideRect(false); }
    if (seen === rectSeen) return;
    const first = rectSeen === "";
    rectSeen = seen;
    // The line moved under an unchanged selection (scroll, zoom, relayout): hide and wait for a new selection —
    // except while a host-set selection's own scroll settles (the rect then follows the line).
    if (!first && !rectSpent && performance.now() < hostMoveUntil) {
      const place = visibleRect(rect);
      if (place) { rectShown = true; spec.onSelectionRect(place); } else hideRect(false);
      return;
    }
    if (!first || rectSpent) { hideRect(true); return; }
    const place = visibleRect(rect);
    if (place) { rectShown = true; spec.onSelectionRect(place); }
  };
  const selection = async () => {
    if (disposed) return;
    const context = await editor.getSelectionContext();
    const next = wireSelection(context.range, sectionEntries);
    if (!next) { reportRect("", null); if (lastSelection) { lastSelection = ""; spec.onSelectionChanged({}); } return; }
    const key = JSON.stringify(next);
    const collapsed = next.start_paragraph === next.end_paragraph && next.start === next.end;
    // A caret polled mid-press has no line yet; the same caret is reported once more when its line is known (#1156).
    const reported = `${key}${collapsed && !context.rect}`;
    const line = JSON.stringify(context.rect ?? null);
    if (reported !== lastSelection) { lastSelection = reported; caretLine = line; spec.onSelectionChanged(next, visibleRect(context.rect)); }
    else if (line !== caretLine) { caretLine = line; spec.onCaretRect?.(visibleRect(context.rect)); }
    reportRect(collapsed || disposed ? "" : key, context.rect);
  };
  // Selection occurs inside the iframe; host-element pointer/key events cannot observe it.
  // Hidden tabs and viewers whose selection nobody reads skip the cross-frame query.
  const track = spec.trackSelection ?? "visible";
  const timer = track === "never" ? undefined : window.setInterval(() => {
    if (disposed || document.hidden || (track === "visible" && !hostRendered(spec.host))) return;
    void selection().catch(spec.onError);
  }, SELECTION_POLL_MS);
  const cancelScheduled = () => { scheduled = false; window.clearTimeout(exportTimer); exportTimer = undefined; };
  /** Start the export for the latest change now (timer fired or a flush asked for it). */
  const exportScheduled = () => {
    if (!scheduled) return;
    cancelScheduled();
    pendingChange = publish(changeGeneration);
    void pendingChange.catch(spec.onError);
  };
  const off = editor.onDocumentChanged(() => {
    // An edit takes the selection-side UI down; the same selection does not bring it back.
    hideRect(true);
    if (!readOnly && !replacing && !disposed) {
      ++changeGeneration;
      scheduled = true;
      window.clearTimeout(exportTimer);
      exportTimer = window.setTimeout(exportScheduled, EXPORT_DEBOUNCE_MS);
    }
  });
  /** Iframe client coordinates → host client coordinates. The canvas may be CSS-zoomed (편집면 확대),
   *  so iframe px are scaled by the frame's rendered width over its own viewport width. */
  const hostPoint = (x: number, y: number) => {
    const frame = editor.element.getBoundingClientRect();
    const inner = editor.element.contentWindow?.innerWidth;
    const scale = inner && frame.width ? frame.width / inner : 1;
    return { x: frame.left + x * scale, y: frame.top + y * scale };
  };
  /** The host menu reads the shell's selection, so the caret the menu was opened at goes first. */
  const openMenu = (point: { x: number; y: number }) => {
    void selection().catch(spec.onError).then(() => { if (!disposed) spec.onContextMenu?.(point); });
  };
  const offShortcut = editor.onShortcut((shortcut, detail) => {
    if (shortcut === "ShiftF10" || shortcut === "ContextMenu") {
      const caret = detail?.caret;
      openMenu(caret ? hostPoint(caret.x, caret.y + caret.height) : hostPoint(0, 0));
    } else spec.onShortcut?.(shortcut);
  });
  const offMenu = spec.onContextMenu ? editor.onContextMenuRequest((point) => openMenu(hostPoint(point.x, point.y))) : () => {};
  const offPick = spec.onRangePick ? editor.onRangePick((point) => {
    const entry = sectionEntries[point.section];
    if (!disposed && entry) spec.onRangePick!({ entry, paragraph: point.paragraph, offset: point.charOffset, cell: point.cell });
  }) : () => {};
  // Dropped-marker notes and the spot ids of the decorations last sent; a click on a proposal/held spot comes back
  // as its spot id (an older pinned SDK has no decoration clicks: spots then open from the caret alone).
  const decorations = decorationLedger(editor, spec.onDecorationClick, () => disposed, visibleRect);
  // All mounts (editor, trial, comparison) follow the app's theme and font scale.
  const observer = typeof MutationObserver === "function" && root ? new MutationObserver(() => {
    const next = hostAppearance(root);
    if (next.theme === appearance.theme && next.fontScale === appearance.fontScale) return;
    appearance = next;
    if (!disposed) void editor.setAppearance(next).catch(spec.onError);
  }) : null;
  observer?.observe(root, { attributes: true, attributeFilter: ["data-theme", "data-font-scale"] });
  // 폭 맞춤(IDE-06): the Studio computes the fit once per command and does not refit when its
  // container is resized (properties panel, splitter, window), so the host's size changes re-run it.
  // A hidden tab reports width 0 — it refits when it is shown again.
  let refitTimer: number | undefined;
  const refit = () => {
    refitTimer = undefined;
    if (disposed || zoom !== "fit" || !hostRendered(spec.host)) return;
    void editor.commands.execute(zoomCommand("fit")).catch(spec.onError);
  };
  const resized = typeof ResizeObserver === "function" ? new ResizeObserver((entries) => {
    if (zoom !== "fit" || !entries.some((entry) => entry.contentRect.width > 0)) return;
    window.clearTimeout(refitTimer);
    refitTimer = window.setTimeout(refit, REFIT_DEBOUNCE_MS);
  }) : null;
  resized?.observe(spec.host);

  /** The Studio range of a target: its first occurrence, its location, its source, or the target itself. */
  const rangeOf = (target: Obj) => {
    const first = Array.isArray(target.occurrences) ? target.occurrences[0] : null;
    const source = (first && typeof first === "object" ? first : target.location && typeof target.location === "object"
      ? target.location : target.source && typeof target.source === "object" ? target.source : target) as Obj;
    const section = sectionEntries.indexOf(String(source.entry));
    const paragraph = source.paragraph ?? source.start_paragraph;
    const cellPath = studioCellPath(source);
    if (section < 0 || !isIndex(paragraph) || cellPath === null)
      throw new Error("HWPX 본문 위치를 찾을 수 없습니다.");
    const endParagraph = source.end_paragraph ?? paragraph;
    const startOffset = source.start ?? 0;
    const endOffset = typeof source.end === "number" ? source.end : null;
    if (!Number.isSafeInteger(endParagraph) || !Number.isSafeInteger(startOffset))
      throw new Error("HWPX 본문 범위가 유효하지 않습니다.");
    return { section, startParagraph: paragraph, startOffset: startOffset as number, endParagraph: endParagraph as number,
      endOffset, ...(cellPath ? { cellPath } : {}) };
  };
  const focus = async (target: Obj) => {
    hostMoveUntil = performance.now() + HOST_MOVE_SETTLE_MS;
    const result = await editor.focusRange(rangeOf(target));
    hostMoveUntil = performance.now() + HOST_MOVE_SETTLE_MS;
    if (!result.focused) throw new Error("HWPX 위치를 에디터에서 찾을 수 없습니다.");
  };
  const flushChanges = async () => {
    for (;;) {
      exportScheduled();
      const current = pendingChange;
      if (!current) return;
      await current;
      if (!scheduled && current === pendingChange) return;
    }
  };
  return {
    content,
    flushChanges,
    async applySnapshot(next, label, expectedContent) {
      if (readOnly) throw new Error("읽기 전용 문서는 수정할 수 없습니다.");
      await editor.setReadOnly(true);
      try {
        await flushChanges();
        const actual = await content();
        if ((expectedContent !== undefined && actual !== expectedContent) || actual !== lastEmittedContent)
          throw new Error("편집 중 문서가 변경되었습니다. 다시 시도해 주세요.");
        replacing = true;
        const generation = ++changeGeneration;
        // The vendored embedded read-only gate rejects user input only; host transactions
        // (hwpctrl plugin) still run, so the lock stays held through the replace itself.
        await editor.plugins.invoke("hwpctrl", "replaceSnapshot", [decodeBase64(next), label]);
        await publish(generation);
        await selection();
      } finally { replacing = false; await editor.setReadOnly(readOnly); }
    },
    focus,
    async scrollTo(target) {
      if (disposed) return false;
      return (await editor.scrollToRange(rangeOf(target))).scrolled === true;
    },
    async undo() {
      if (readOnly) return;
      const r = await editor.hwpctrl.undo();
      if (!r.ok) throw new Error(r.message || r.reason);
      cancelScheduled();
      await publish(++changeGeneration);
    },
    async redo() {
      if (readOnly) return;
      const r = await editor.hwpctrl.redo();
      if (!r.ok) throw new Error(r.message || r.reason);
      cancelScheduled();
      await publish(++changeGeneration);
    },
    async setDecorations(projection) {
      // 구조 트리 줄의 강조(UX-09): 가리킨 항목·선택은 강하게, 나머지 경계는 옅게 선다. 필드를 가리키면 그 필드의
      // 표지만 남긴다(필드 표지는 강약이 없어 다른 필드와 갈리지 않는다). 문서 모드에서는 가리킨 것만 선다.
      // 미리보기 범위(IDE-06 P-16, kind "range")는 Python 이 준 실제 포함 범위에 이름표 없는 합성 표지 하나로 선다 —
      // Studio 는 표지의 실체를 검사하지 않는다. 이름표가 있으면 실제 항목처럼 보이므로 이름표를 모두 걷는다.
      const highlight = projection.highlight && typeof projection.highlight === "object" ? projection.highlight as Obj : null;
      const range = highlight?.kind === "range" && highlight.location && typeof highlight.location === "object" ? highlight.location as Obj : null;
      // 문제 표지(IDE-08 P-08)는 Python 의 problems[].location 에 선다 — 오류는 물결(strong), 경고는 점선(subtle) 밑줄이고
      // 문장은 포인터 설명이다. 문제는 표시가 아니라 경보라 문서 모드에서도 선다(TXT 와 같다). 표지 상한은 필드·항목 표지와
      // 나눠 쓰므로 넘치면 문제 표지부터 덜어 낸다(상한을 넘기면 장식 호출 전체가 던진다).
      const documentMode = projection.mode === "document";
      const fields = Array.isArray(projection.fields) ? projection.fields : [];
      const slots = Array.isArray(projection.slots) ? projection.slots : [];
      const markers: Marker[] = [];
      const region = highlight?.kind === "slot" || highlight?.kind === "option" || !!range;
      const lit = (kind: string, id: unknown, slotId?: unknown, index?: number) => !!highlight && highlight.kind === kind && highlight.id === id
        && (kind !== "option" || highlight.slot_id === slotId) && (kind !== "field" || highlight.index == null || highlight.index === index);
      const marker = (kind: Marker["kind"], label: string, emphasis: 'subtle' | 'strong', place: Obj) => markerAt(sectionEntries, kind, label, emphasis, place);
      const add = (kind: "field" | "slot" | "option", label: string, place: Obj, shown = true) => {
        if (!shown) return;
        const on = kind === "field" ? highlight?.kind === "field" : region && lit(kind, place.__id, place.__slot);
        const emphasis = on ? 'strong' : region && kind !== "field" ? 'subtle' : kind === 'field' || projection.mode === 'structure' ? 'strong' : 'subtle';
        const made = marker(kind, label, emphasis, place);
        if (made) markers.push(made);
      };
      for (const item of fields) {
        if (!item || typeof item !== "object") continue;
        const field = item as Obj;
        (Array.isArray(field.occurrences) ? field.occurrences : []).forEach((occurrence: unknown, at: number) => {
          const shown = highlight?.kind === "field" ? lit("field", field.name, undefined, at + 1) : !documentMode;
          if (occurrence && typeof occurrence === "object") add("field", String(field.name ?? ""), occurrence as Obj, shown);
        });
      }
      for (const item of slots) {
        if (!item || typeof item !== "object") continue;
        const slot = item as Obj;
        const shown = (kind: string, id: unknown) => !documentMode || lit(kind, id, slot.id);
        if (slot.location && typeof slot.location === "object")
          add("slot", String(slot.label ?? slot.id ?? ""), { ...slot.location as Obj, __id: slot.id }, shown("slot", slot.id));
        for (const option of Array.isArray(slot.options) ? slot.options : []) {
          if (!option || typeof option !== "object") continue;
          const child = option as Obj;
          if (child.location && typeof child.location === "object")
            add("option", String(child.label ?? child.id ?? ""), { ...child.location as Obj, __id: child.id, __slot: slot.id }, shown("option", child.id));
        }
      }
      // The preview range is one more marker only while the Studio's cap leaves room for it.
      const synthetic = range && marker(highlight?.marker === "option" ? "option" : "slot", "", 'strong', range);
      if (synthetic && markers.length < DECORATION_LIMIT) markers.push(synthetic);
      // 「데이터로 필드 찾기」 제안(#1156)은 띠가 켜진 동안 모든 표시 방식에서 선다 — 넘치면 보류·제안·문제 차례로 덜어 낸다.
      const fitted = decorations.fit(markers, sectionEntries, projection);
      // Template mode labels only the field under the caret or pointer (§3.2: labels never hide text);
      // structure mode labels every boundary. A preview range takes every label down.
      await editor.setDecorations(fitted, { labels: documentMode || range ? "none" : projection.mode === "structure" ? "all" : "selected" });
    },
    async setReadOnly(value) {
      const next = value || compatibilityBlocked;
      await editor.setReadOnly(next); readOnly = next;
    },
    async rangePick(state) {
      if (disposed) return;
      if (state === false || state === null) { await editor.setRangePick({ enabled: state === null, start: null }); return; }
      const section = sectionEntries.indexOf(state.entry);
      await editor.setRangePick({ enabled: true, start: section < 0 ? null
        : { section, paragraph: state.paragraph, charOffset: state.offset, cell: state.cell } });
    },
    async setZoom(next) {
      if (disposed) return;
      zoom = next;
      window.clearTimeout(refitTimer);
      await editor.commands.execute(zoomCommand(next));
    },
    dispose() {
      if (disposed) return;
      disposed = true; window.clearInterval(timer); window.clearTimeout(refitTimer); cancelScheduled(); off(); offShortcut(); offMenu(); offPick(); decorations.off();
      observer?.disconnect(); resized?.disconnect();
      editor.destroy();
    },
  };
}
