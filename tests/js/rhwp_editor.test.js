import test from "node:test";
import assert from "node:assert/strict";
import { mountRhwp, hostAppearance } from "../../frontend/src/editorview/rhwp_editor.ts";
import { RhwpEditor } from "../../frontend/vendor/rhwp/editor/index.js";

const b64 = (text) => Buffer.from(text, "utf8").toString("base64");

/** Pinned-Studio stand-in that models the vendored embedded read-only gate: while read-only,
 *  user input is rejected (`input-handler.isOperationAllowedInEditMode`) but a host transaction
 *  issued through the hwpctrl plugin (`host.ts` marks it `hostTransaction`) still runs.
 *  `hooks.duringReplace` lets a test play a user keystroke while the replace RPC is in flight. */
function fakeStudio(log, hooks = {}) {
  let readOnly = false;
  let bytes = new TextEncoder().encode("mounted");
  const changed = new Set(), shortcuts = new Set(), menus = new Set();
  /** SDK calls other than document I/O, and the options the Studio was created with. */
  const calls = [];
  let options = null;
  const userType = (text) => {
    if (readOnly) { log.push(`user-rejected:${text}`); return false; }
    log.push(`user-typed:${text}`);
    bytes = new TextEncoder().encode(`${new TextDecoder().decode(bytes)}${text}`);
    for (const listener of changed) listener({});
    return true;
  };
  const editor = {
    async loadFile() { return {}; },
    async exportHwpx() {
      const exported = bytes;
      log.push(`export:${new TextDecoder().decode(exported)}`);
      await hooks.exporting?.();
      return exported;
    },
    async setReadOnly(value) { readOnly = value; log.push(`readOnly:${value}`); },
    async getSelectionContext() { hooks.selecting?.(); return { range: null }; },
    async focusRange() { return { focused: true }; },
    async setDecorations(markers, options) { calls.push(["setDecorations", markers.length, options]); },
    async setAppearance(appearance) { calls.push(["setAppearance", appearance]); },
    async setContextMenuForwarding(enabled) { calls.push(["setContextMenuForwarding", enabled]); },
    onDocumentChanged(listener) { changed.add(listener); return () => changed.delete(listener); },
    onShortcut(listener) { shortcuts.add(listener); return () => shortcuts.delete(listener); },
    onContextMenuRequest(listener) { menus.add(listener); return () => menus.delete(listener); },
    element: { getBoundingClientRect: () => hooks.frame ?? { left: 0, top: 0 }, contentWindow: hooks.frameWindow },
    chrome: { async set() {} },
    commands: { async execute(id) { calls.push(["execute", id]); return { ok: true }; } },
    plugins: {
      async invoke(plugin, method, args) {
        assert.equal(plugin, "hwpctrl");
        assert.equal(method, "replaceSnapshot");
        hooks.duringReplace?.(userType);
        // Host transaction: allowed regardless of the embedded read-only lock.
        log.push(`replace:${readOnly ? "locked" : "unlocked"}`);
        bytes = args[0];
        for (const listener of changed) listener({});
      },
    },
    destroy() {},
  };
  return { studio: async (_host, created) => { options = created; return editor; }, userType, calls,
    options: () => options,
    pressShortcut: (shortcut, detail) => { for (const listener of shortcuts) listener(shortcut, detail); },
    rightClick: (point) => { for (const listener of menus) listener(point); },
    listeners: () => ({ shortcuts: shortcuts.size, menus: menus.size }) };
}

/** Manual timers: the test decides when the export debounce and the selection poll fire. */
function fakeTimers() {
  let next = 1;
  const timeouts = new Map(), intervals = new Map();
  return {
    timeouts, intervals,
    setTimeout(fn, ms) { const id = next++; timeouts.set(id, { fn, ms }); return id; },
    clearTimeout(id) { timeouts.delete(id); },
    setInterval(fn, ms) { const id = next++; intervals.set(id, { fn, ms }); return id; },
    clearInterval(id) { intervals.delete(id); },
    fireTimeouts() { for (const [id, { fn }] of [...timeouts]) { timeouts.delete(id); fn(); } },
    tick() { for (const { fn } of [...intervals.values()]) fn(); },
  };
}

async function withDom(run, timers = fakeTimers()) {
  const priorDocument = globalThis.document;
  const priorWindow = globalThis.window;
  globalThis.document = { baseURI: "http://127.0.0.1/index.html", hidden: true };
  globalThis.window = timers;
  try { return await run(); } finally {
    globalThis.document = priorDocument;
    globalThis.window = priorWindow;
  }
}

test("applySnapshot keeps user input locked for the whole replace", () => withDom(async () => {
  const log = [];
  const emitted = [];
  const fake = fakeStudio(log);
  const handle = await mountRhwp({
    host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
    onChanged: (content) => emitted.push(content), onSelectionChanged() {}, onError: (error) => { throw error; },
    preflight: async () => ({ editable: true }), studio: fake.studio,
  });
  log.length = 0;
  await handle.applySnapshot(b64("created"), "create_field", b64("mounted"));
  // One lock spans flush, compare and the host replace; it is released only after publishing.
  assert.deepEqual(log, [
    "readOnly:true", "export:mounted", "replace:locked", "export:created", "readOnly:false",
  ]);
  assert.deepEqual(emitted, [b64("created")]);
  assert.equal(fake.userType("!"), true);
  handle.dispose();
}));

test("a keystroke racing the replace is rejected instead of landing under it", () => withDom(async () => {
  const log = [];
  const emitted = [];
  const fake = fakeStudio(log, { duringReplace: (type) => type("x") });
  const handle = await mountRhwp({
    host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
    onChanged: (content) => emitted.push(content), onSelectionChanged() {}, onError: (error) => { throw error; },
    preflight: async () => ({ editable: true }), studio: fake.studio,
  });
  log.length = 0;
  await handle.applySnapshot(b64("created"), "create_field", b64("mounted"));
  // No unlocked window: the racing keystroke meets the lock, not an unlocked editor.
  assert.deepEqual(log, [
    "readOnly:true", "export:mounted", "user-rejected:x", "replace:locked", "export:created", "readOnly:false",
  ]);
  assert.deepEqual(emitted, [b64("created")]);
  handle.dispose();
}));

test("applySnapshot still refuses a document whose editor content moved under the preview", () => withDom(async () => {
  const log = [];
  const handle = await mountRhwp({
    host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; },
    preflight: async () => ({ editable: true }), studio: fakeStudio(log).studio,
  });
  await assert.rejects(handle.applySnapshot(b64("created"), "create_field", b64("stale")),
    /편집 중 문서가 변경되었습니다/);
  assert.ok(!log.some((entry) => entry.startsWith("replace")));
  handle.dispose();
}));

test("applySnapshot never mutates a compatibility-blocked (read-only) document", () => withDom(async () => {
  const log = [];
  const handle = await mountRhwp({
    host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
    onChanged() {}, onSelectionChanged() {}, onError() {}, onCompatibility() {},
    preflight: async () => ({ editable: false, diagnostics: ["xml_changed"] }), studio: fakeStudio(log).studio,
  });
  await assert.rejects(handle.applySnapshot(b64("created"), "create_field"), /읽기 전용/);
  assert.ok(!log.some((entry) => entry.startsWith("replace")));
  handle.dispose();
}));

const settle = async () => { for (let turn = 0; turn < 6; turn++) await new Promise(setImmediate); };
const mountEditable = (fake, emitted) => mountRhwp({
  host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
  onChanged: (content) => emitted.push(content), onSelectionChanged() {}, onError: (error) => { throw error; },
  preflight: async () => ({ editable: true }), studio: fake.studio,
});
const exportsIn = (log) => log.filter((entry) => entry.startsWith("export"));

test("UX-05: a burst of change events costs one export after the debounce", () => {
  const timers = fakeTimers();
  return withDom(async () => {
    const log = [];
    const emitted = [];
    const fake = fakeStudio(log);
    const handle = await mountEditable(fake, emitted);
    log.length = 0;
    for (const char of "abcde") fake.userType(char);
    assert.deepEqual(exportsIn(log), [], "no export while typing");
    assert.equal(timers.timeouts.size, 1, "one trailing timer, not one per event");
    assert.equal([...timers.timeouts.values()][0].ms, 200);
    timers.fireTimeouts();
    await settle();
    assert.deepEqual(exportsIn(log), ["export:mountedabcde"]);
    assert.deepEqual(emitted, [b64("mountedabcde")]);
    handle.dispose();
  }, timers);
});

test("UX-05: flushChanges during a burst exports immediately and cancels the pending timer", () => {
  const timers = fakeTimers();
  return withDom(async () => {
    const log = [];
    const emitted = [];
    const fake = fakeStudio(log);
    const handle = await mountEditable(fake, emitted);
    log.length = 0;
    for (const char of "xyz") fake.userType(char);
    await handle.flushChanges();
    assert.equal(timers.timeouts.size, 0, "flush consumed the scheduled export");
    assert.deepEqual(exportsIn(log), ["export:mountedxyz"]);
    assert.deepEqual(emitted, [b64("mountedxyz")]);
    timers.fireTimeouts();
    await settle();
    assert.deepEqual(emitted, [b64("mountedxyz")], "nothing left to export");
    handle.dispose();
  }, timers);
});

test("UX-05: an export overtaken by a newer change is dropped; only the latest generation is published", () => {
  const timers = fakeTimers();
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let gated = false;
  return withDom(async () => {
    const log = [];
    const emitted = [];
    const fake = fakeStudio(log, { exporting: () => gated ? gate : undefined });
    const handle = await mountEditable(fake, emitted);
    gated = true;
    fake.userType("1");
    timers.fireTimeouts(); // the export of "mounted1" starts and stalls
    await settle();
    fake.userType("2"); // a newer generation arrives while it runs
    gated = false;
    release();
    await settle();
    assert.deepEqual(emitted, [], "the overtaken export is discarded");
    timers.fireTimeouts();
    await settle();
    assert.deepEqual(emitted, [b64("mounted12")]);
    handle.dispose();
  }, timers);
});

test("UX-05: flushChanges waits for an in-flight export and a change that arrived during it", () => {
  const timers = fakeTimers();
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let gated = false;
  return withDom(async () => {
    const log = [];
    const emitted = [];
    const fake = fakeStudio(log, { exporting: () => gated ? gate : undefined });
    const handle = await mountEditable(fake, emitted);
    gated = true;
    fake.userType("1");
    const flushed = handle.flushChanges(); // starts the export now; it stalls
    await settle();
    fake.userType("2");
    gated = false;
    release();
    await flushed;
    assert.deepEqual(emitted, [b64("mounted12")], "flush returns only once the newest content is published");
    assert.equal(timers.timeouts.size, 0);
    handle.dispose();
  }, timers);
});

test("UX-05: dispose clears a pending export timer", () => {
  const timers = fakeTimers();
  return withDom(async () => {
    const fake = fakeStudio([]);
    const handle = await mountEditable(fake, []);
    fake.userType("q");
    assert.equal(timers.timeouts.size, 1);
    handle.dispose();
    assert.equal(timers.timeouts.size, 0);
    assert.equal(timers.intervals.size, 0);
  }, timers);
});

test("UX-05: selection polling runs only where it matters and resumes when the host is shown again", () => {
  const timers = fakeTimers();
  return withDom(async () => {
    globalThis.document.hidden = false;
    const mountViewer = (host, log, trackSelection) => mountRhwp({ host, content: b64("disk"), fileName: "r.hwpx", readOnly: true,
      onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, studio: fakeStudio(log, { selecting: () => log.push("selection") }).studio,
      ...(trackSelection ? { trackSelection } : {}) });
    const polls = async (trackSelection, host) => {
      const log = [];
      const handle = await mountViewer(host, log, trackSelection);
      const intervals = timers.intervals.size;
      timers.tick();
      await settle();
      handle.dispose();
      return { intervals, polled: log.filter((entry) => entry === "selection").length };
    };
    const shown = { closest: () => null, offsetParent: {} };
    const hiddenTab = { closest: (selector) => selector.includes("[hidden]") ? {} : null, offsetParent: null };
    const collapsed = { closest: () => null, offsetParent: null };
    assert.deepEqual(await polls("never", shown), { intervals: 0, polled: 0 }, "a viewer nobody reads the selection of never polls");
    assert.deepEqual(await polls("visible", shown), { intervals: 1, polled: 1 });
    assert.deepEqual(await polls("visible", hiddenTab), { intervals: 1, polled: 0 }, "an inactive (hidden/inert) tab pauses");
    assert.deepEqual(await polls("visible", collapsed), { intervals: 1, polled: 0 }, "a host that is not laid out pauses");
    assert.deepEqual(await polls(undefined, hiddenTab), { intervals: 1, polled: 0 }, "the default is visible-only");
    assert.deepEqual(await polls("always", hiddenTab), { intervals: 1, polled: 1 });
    const host = { closest: () => ({}), offsetParent: null };
    const log = [];
    const handle = await mountViewer(host, log);
    timers.tick(); await settle();
    assert.equal(log.filter((entry) => entry === "selection").length, 0);
    host.closest = () => null; host.offsetParent = {};
    timers.tick(); await settle();
    assert.equal(log.filter((entry) => entry === "selection").length, 1, "the same instance resumes once visible");
    handle.dispose();
  }, timers);
});

// ---- UX-07: 편집면 iframe 안의 키·우클릭·테마·배율·이름 ----

test("UX-07: Escape and F6 from inside the editor reach the host; the menu keys open the host menu under the caret", () => withDom(async () => {
  const shortcuts = [], menus = [];
  const fake = fakeStudio([], { frame: { left: 100, top: 50 } });
  const handle = await mountRhwp({
    host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; },
    onShortcut: (shortcut) => shortcuts.push(shortcut), onContextMenu: (point) => menus.push(point),
    preflight: async () => ({ editable: true }), studio: fake.studio,
  });
  assert.ok(fake.calls.some(([name, value]) => name === "setContextMenuForwarding" && value === true),
    "a host menu replaces the Studio menu only when the host asks for it");
  for (const key of ["Escape", "F6", "ShiftF6", "F2", "CtrlS"]) fake.pressShortcut(key);
  assert.deepEqual(shortcuts, ["Escape", "F6", "ShiftF6", "F2", "CtrlS"]);
  // Shift+F10 carries the caret rect in iframe coordinates; the host gets its bottom-left in host coordinates.
  fake.pressShortcut("ShiftF10", { caret: { x: 10, y: 20, width: 1, height: 15 } });
  fake.pressShortcut("ContextMenu", { caret: null });
  fake.rightClick({ x: 5, y: 6 });
  await settle();
  assert.deepEqual(menus, [{ x: 110, y: 85 }, { x: 100, y: 50 }, { x: 105, y: 56 }]);
  assert.equal(shortcuts.length, 5, "menu keys are not shell shortcuts");
  handle.dispose();
  assert.deepEqual(fake.listeners(), { shortcuts: 0, menus: 0 }, "dispose releases both subscriptions");
}));

test("UX-07: a mount without a host menu keeps the Studio menu", () => withDom(async () => {
  const fake = fakeStudio([]);
  const handle = await mountRhwp({ host: {}, content: b64("disk"), fileName: "r.hwpx", readOnly: true,
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, studio: fake.studio });
  assert.ok(!fake.calls.some(([name]) => name === "setContextMenuForwarding"));
  assert.equal(fake.listeners().menus, 0);
  handle.dispose();
}));

test("UX-07: the SDK forwards the new shell keys, drops unknown ones and validates the caret and click points", () => {
  const listeners = new Map();
  const transport = { on(event, listener) { listeners.set(event, listener); return () => listeners.delete(event); } };
  const editor = new RhwpEditor({}, transport);
  const seen = [];
  editor.onShortcut((shortcut, detail) => seen.push(detail ? [shortcut, detail] : shortcut));
  const emit = listeners.get("authoringShortcut");
  for (const value of ["Escape", "F6", "ShiftF6", "F2", "Tab", "ShiftF10", { shortcut: "Tab" }]) emit(value);
  emit({ shortcut: "ShiftF10", caret: { x: 1, y: 2, width: 3, height: 4 } });
  emit({ shortcut: "ContextMenu", caret: { x: "1" } });
  assert.deepEqual(seen, ["Escape", "F6", "ShiftF6", "F2",
    ["ShiftF10", { caret: { x: 1, y: 2, width: 3, height: 4 } }], ["ContextMenu", { caret: null }]]);
  const points = [];
  editor.onContextMenuRequest((point) => points.push(point));
  listeners.get("contextMenuRequest")({ x: 3, y: 4 });
  listeners.get("contextMenuRequest")({ x: "3", y: 4 });
  assert.deepEqual(points, [{ x: 3, y: 4 }]);
});

/** A documentElement with the app's theme attributes and a MutationObserver the test fires. */
function appearanceDom(attributes) {
  const root = { attributes: { ...attributes }, getAttribute(name) { return this.attributes[name] ?? null; } };
  const observers = [];
  class FakeObserver {
    constructor(callback) { this.callback = callback; this.target = null; this.options = null; observers.push(this); }
    observe(target, options) { this.target = target; this.options = options; }
    disconnect() { this.target = null; }
  }
  return { root, observers, FakeObserver,
    change(name, value) {
      if (value === null) delete root.attributes[name]; else root.attributes[name] = value;
      for (const observer of observers) if (observer.target) observer.callback([]);
    } };
}

test("UX-07: theme and font scale reach every mount at load and follow html[data-theme]/[data-font-scale]", () => withDom(async () => {
  const dom = appearanceDom({ "data-theme": "dark", "data-font-scale": "large" });
  globalThis.document.documentElement = dom.root;
  const priorObserver = globalThis.MutationObserver;
  globalThis.MutationObserver = dom.FakeObserver;
  try {
    const editorFake = fakeStudio([]), viewerFake = fakeStudio([]);
    const editor = await mountRhwp({ host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
      onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; },
      preflight: async () => ({ editable: true }), studio: editorFake.studio });
    const viewer = await mountRhwp({ host: {}, content: b64("disk"), fileName: "r.hwpx", readOnly: true, trackSelection: "never",
      onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, studio: viewerFake.studio });
    for (const fake of [editorFake, viewerFake]) {
      const url = new URL(fake.options().studioUrl);
      assert.deepEqual([url.pathname, url.searchParams.get("hostTheme"), url.searchParams.get("hostFontScale")],
        ["/rhwp/studio/index.html", "dark", "1.25"], "the first paint already has the app theme");
      assert.deepEqual(fake.calls.filter(([name]) => name === "setAppearance"), [["setAppearance", { theme: "dark", fontScale: 1.25 }]]);
    }
    assert.deepEqual(dom.observers.map((observer) => observer.options.attributeFilter),
      [["data-theme", "data-font-scale"], ["data-theme", "data-font-scale"]]);
    dom.change("data-theme", null);
    dom.change("data-font-scale", "larger");
    dom.change("data-font-scale", "larger");
    for (const fake of [editorFake, viewerFake]) {
      assert.deepEqual(fake.calls.filter(([name]) => name === "setAppearance").map(([, value]) => value),
        [{ theme: "dark", fontScale: 1.25 }, { theme: "system", fontScale: 1.25 }, { theme: "system", fontScale: 1.5 }],
        "each real change is sent once; a repeated value is not");
    }
    editor.dispose(); viewer.dispose();
    assert.ok(dom.observers.every((observer) => observer.target === null), "dispose disconnects the observer");
  } finally {
    globalThis.MutationObserver = priorObserver;
  }
}));

test("UX-07: hostAppearance maps the app attributes; unknown values fall back to system and 1", () => {
  const root = (attributes) => ({ getAttribute: (name) => attributes[name] ?? null });
  assert.deepEqual(hostAppearance(root({ "data-theme": "light", "data-font-scale": "larger" })), { theme: "light", fontScale: 1.5 });
  assert.deepEqual(hostAppearance(root({ "data-theme": "sepia", "data-font-scale": "huge" })), { theme: "system", fontScale: 1 });
  assert.deepEqual(hostAppearance(null), { theme: "system", fontScale: 1 });
});

test("UX-07: the editor iframe is named by the spec title, and labels follow the display mode", () => withDom(async () => {
  const named = fakeStudio([]), unnamed = fakeStudio([]);
  const handle = await mountRhwp({ host: {}, content: b64("disk"), fileName: "a.hwpx", title: "구매요청서.hwpx", readOnly: false,
    sectionEntries: ["Contents/section0.xml"],
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; },
    preflight: async () => ({ editable: true }), studio: named.studio });
  const viewer = await mountRhwp({ host: {}, content: b64("disk"), fileName: "r.hwpx", readOnly: true,
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, studio: unnamed.studio });
  assert.equal(named.options().title, "구매요청서.hwpx");
  assert.ok(!("title" in unnamed.options()));
  const analysis = { fields: [{ name: "수요기관", occurrences: [{ entry: "Contents/section0.xml", paragraph: 0, start: 4, end: 9 }] }], slots: [] };
  await handle.setDecorations({ ...analysis, mode: "template" });
  await handle.setDecorations({ ...analysis, mode: "structure" });
  await handle.setDecorations({ ...analysis, mode: "document" });
  assert.deepEqual(named.calls.filter(([name]) => name === "setDecorations"),
    [["setDecorations", 1, { labels: "selected" }], ["setDecorations", 1, { labels: "all" }], ["setDecorations", 0, { labels: "none" }]],
    "template mode labels only the field under the caret or pointer; structure mode labels all");
  handle.dispose(); viewer.dispose();
}));

test("UX-07: a zoomed canvas scales iframe coordinates into host coordinates", () => withDom(async () => {
  const menus = [];
  // 편집면 150%: the frame renders 300 host px wide over a 200 px iframe viewport.
  const fake = fakeStudio([], { frame: { left: 10, top: 20, width: 300 }, frameWindow: { innerWidth: 200 } });
  const handle = await mountRhwp({ host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, onContextMenu: (point) => menus.push(point),
    preflight: async () => ({ editable: true }), studio: fake.studio });
  fake.rightClick({ x: 40, y: 60 });
  await settle();
  assert.deepEqual(menus, [{ x: 70, y: 110 }]);
  handle.dispose();
}));

test("IDE-04: a fixed zoom is one view:zoom-N command after the load — never a fit mode, and absent unless asked", () => withDom(async () => {
  const zoomed = fakeStudio([]);
  const viewer = await mountRhwp({ host: {}, content: b64("result"), fileName: "시험 결과.hwpx", readOnly: true, zoom: 75,
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, studio: zoomed.studio, trackSelection: "never" });
  assert.deepEqual(zoomed.calls.filter(([name]) => name === "execute"), [["execute", "view:zoom-75"]], "한 번, 고정 배율 명령");
  viewer.dispose();
  const plain = fakeStudio([]);
  const editor = await mountRhwp({ host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, preflight: async () => ({ editable: true }), studio: plain.studio });
  assert.deepEqual(plain.calls.filter(([name]) => name === "execute"), [], "편집면은 배율을 건드리지 않는다");
  editor.dispose();
}));
