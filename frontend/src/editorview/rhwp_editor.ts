import { createStudio } from "../../vendor/rhwp/editor/index.js";

type Obj = Record<string, unknown>;
/** Table-cell coordinate on the Python wire (outermost table first); rhwp uses camelCase for the same entries. */
type WireCellPath = Array<{ parent_paragraph: number; control: number; cell: number; paragraph: number }>;
type StudioCellPath = Array<{ parentParagraph: number; control: number; cell: number; paragraph: number }>;
type Selection = { entry: string; paragraph: number; start_paragraph: number; end_paragraph: number; start: number; end: number;
  cell_path?: WireCellPath };

const CELL_PATH_LIMIT = 16;
const isIndex = (n: unknown): n is number => Number.isSafeInteger(n) && (n as number) >= 0;

/** `undefined` = body paragraph location; `null` = a cell_path is present but malformed. */
function studioCellPath(place: Obj): StudioCellPath | null | undefined {
  const raw = place.cell_path;
  if (raw === undefined || raw === null) return undefined;
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > CELL_PATH_LIMIT) return null;
  const path: StudioCellPath = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") return null;
    const { parent_paragraph, control, cell, paragraph } = item as Obj;
    if (![parent_paragraph, control, cell, paragraph].every(isIndex)) return null;
    path.push({ parentParagraph: parent_paragraph as number, control: control as number, cell: cell as number, paragraph: paragraph as number });
  }
  return path;
}

function wireCellPath(path: StudioCellPath): WireCellPath {
  return path.map((entry) => ({ parent_paragraph: entry.parentParagraph, control: entry.control, cell: entry.cell, paragraph: entry.paragraph }));
}

export type RhwpMountSpec = {
  host: HTMLElement; content: string; fileName: string; sectionEntries?: string[];
  onChanged: (content: string) => void; onSelectionChanged: (selection: Selection | Obj) => void;
  onError: (error: unknown) => void; onShortcut?: (shortcut: RhwpShortcut) => void;
  /** Document right-click or keyboard menu key (Shift+F10, ContextMenu) inside the editor, in
   *  host client coordinates (the keyboard menu opens under the caret). Given = the host's menu
   *  replaces the Studio's own. */
  onContextMenu?: (point: { x: number; y: number }) => void;
  /** Accessible name of the editor iframe. */
  title?: string;
  preflight?: (exported: string) => Promise<{ editable: boolean; diagnostics?: unknown[] }>;
  onCompatibility?: (result: { editable: boolean; diagnostics?: unknown[] }) => void;
  readOnly: boolean;
  /** Who needs caret reports: "visible" polls only while the host is rendered (not inside a
   *  `hidden`/`inert` ancestor); "never" skips polling (viewers nobody reads the selection of).
   *  Default "visible". */
  trackSelection?: "visible" | "always" | "never";
  /** Test seam only: the product always mounts the pinned SDK's `createStudio`. */
  studio?: typeof createStudio;
};
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
  setDecorations(projection: Obj): Promise<void>; setReadOnly(readOnly: boolean): Promise<void>;
  dispose(): void;
};

/** Trailing debounce for HWPX export after edits: a burst of change events costs one export. */
export const EXPORT_DEBOUNCE_MS = 200;
const SELECTION_POLL_MS = 300;

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
  const editor = await (spec.studio ?? createStudio)(spec.host, { studioUrl: studioUrl.href, plugins: ["hwpctrl"],
    chrome: { menu: false, toolbar: !spec.readOnly, statusbar: false }, ...(spec.title ? { title: spec.title } : {}) });
  let disposed = false, readOnly = spec.readOnly, compatibilityBlocked = false, replacing = false, lastSelection = "";
  let changeGeneration = 0, lastEmittedContent = spec.content;
  let pendingChange: Promise<void> | null = null;
  // Debounced export: `scheduled` means a change arrived that no export has started for yet.
  let scheduled = false, exportTimer: number | undefined;
  const sectionEntries = spec.sectionEntries ?? [];
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
  } catch (error) { editor.destroy(); throw error; }
  const content = async () => encodeBase64(await editor.exportHwpx());
  const publish = async (generation: number) => {
    const bytes = await content();
    if (disposed || generation !== changeGeneration || bytes === lastEmittedContent) return;
    lastEmittedContent = bytes;
    spec.onChanged(bytes);
  };
  const selection = async () => {
    if (disposed) return;
    const range = (await editor.getSelectionContext()).range;
    const clear = () => { if (lastSelection) { lastSelection = ""; spec.onSelectionChanged({}); } };
    if (!range || range.start.section !== range.end.section) { clear(); return; }
    const { start, end } = range;
    const entry = sectionEntries[start.section];
    if (!entry) { clear(); return; }
    const next: Selection = { entry, paragraph: start.paragraph, start_paragraph: start.paragraph,
      end_paragraph: end.paragraph, start: start.charOffset, end: end.charOffset };
    if (![start.paragraph, end.paragraph, next.start, next.end].every(isIndex)) { clear(); return; }
    if (range.cellPath) {
      // Studio reports cellPath only when both edges share one table cell; paragraphs are then cell-level.
      if (range.cellPath.length === 0 || range.cellPath.length > CELL_PATH_LIMIT
        || !range.cellPath.every((e) => [e.parentParagraph, e.control, e.cell, e.paragraph].every(isIndex))) { clear(); return; }
      next.cell_path = wireCellPath(range.cellPath);
    }
    const key = JSON.stringify(next);
    if (key !== lastSelection) { lastSelection = key; spec.onSelectionChanged(next); }
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
  // All mounts (editor, trial, comparison) follow the app's theme and font scale.
  const observer = typeof MutationObserver === "function" && root ? new MutationObserver(() => {
    const next = hostAppearance(root);
    if (next.theme === appearance.theme && next.fontScale === appearance.fontScale) return;
    appearance = next;
    if (!disposed) void editor.setAppearance(next).catch(spec.onError);
  }) : null;
  observer?.observe(root, { attributes: true, attributeFilter: ["data-theme", "data-font-scale"] });

  const focus = async (target: Obj) => {
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
    const result = await editor.focusRange({ section, startParagraph: paragraph,
      startOffset: startOffset as number, endParagraph: endParagraph as number, endOffset, ...(cellPath ? { cellPath } : {}) });
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
      if (projection.mode === "document") { await editor.setDecorations([], { labels: "none" }); return; }
      const fields = Array.isArray(projection.fields) ? projection.fields : [];
      const slots = Array.isArray(projection.slots) ? projection.slots : [];
      const markers: Array<{ kind: string; label: string; emphasis: 'subtle' | 'strong'; section: number; startParagraph: number;
        startOffset: number; endParagraph: number; endOffset: number | null; cellPath?: StudioCellPath }> = [];
      const add = (kind: string, label: string, place: Obj) => {
        const section = sectionEntries.indexOf(String(place.entry));
        const startParagraph = place.paragraph ?? place.start_paragraph;
        const endParagraph = place.end_paragraph ?? startParagraph;
        const cellPath = studioCellPath(place);
        if (section < 0 || !Number.isSafeInteger(startParagraph) || !Number.isSafeInteger(endParagraph) || cellPath === null) return;
        markers.push({ kind, label, emphasis: kind === 'field' || projection.mode === 'structure' ? 'strong' : 'subtle',
          section, startParagraph: startParagraph as number,
          startOffset: typeof place.start === "number" ? place.start : 0,
          endParagraph: endParagraph as number, endOffset: typeof place.end === "number" ? place.end : null,
          ...(cellPath ? { cellPath } : {}) });
      };
      for (const item of fields) {
        if (!item || typeof item !== "object") continue;
        const field = item as Obj;
        for (const occurrence of Array.isArray(field.occurrences) ? field.occurrences : [])
          if (occurrence && typeof occurrence === "object") add("field", String(field.name ?? ""), occurrence as Obj);
      }
      for (const item of slots) {
        if (!item || typeof item !== "object") continue;
        const slot = item as Obj;
        if (slot.location && typeof slot.location === "object") add("slot", String(slot.label ?? slot.id ?? ""), slot.location as Obj);
        for (const option of Array.isArray(slot.options) ? slot.options : []) {
          if (!option || typeof option !== "object") continue;
          const child = option as Obj;
          if (child.location && typeof child.location === "object")
            add("option", String(child.label ?? child.id ?? ""), child.location as Obj);
        }
      }
      // Template mode labels only the field under the caret or pointer (§3.2: labels never hide text);
      // structure mode labels every boundary.
      await editor.setDecorations(markers, { labels: projection.mode === "structure" ? "all" : "selected" });
    },
    async setReadOnly(value) {
      const next = value || compatibilityBlocked;
      await editor.setReadOnly(next); readOnly = next;
    },
    dispose() {
      if (disposed) return;
      disposed = true; window.clearInterval(timer); cancelScheduled(); off(); offShortcut(); offMenu(); observer?.disconnect();
      editor.destroy();
    },
  };
}
