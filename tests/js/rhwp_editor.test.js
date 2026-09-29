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
      assert.equal(url.searchParams.get("autosave"), "off", "#1068: every mount turns the Studio's own autosave recovery off");
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

test("IDE-06: every mount states its Studio zoom after the load — fixed view:zoom-N by default, fit width when asked", () => withDom(async () => {
  // The Studio keeps its fit mode in the iframe origin's settings and restores it on the next load: an
  // unstated mode would inherit whatever the last mount left there.
  const zoomed = fakeStudio([]);
  const viewer = await mountRhwp({ host: {}, content: b64("result"), fileName: "시험 결과.hwpx", readOnly: true, zoom: 75,
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, studio: zoomed.studio, trackSelection: "never" });
  assert.deepEqual(zoomed.calls.filter(([name]) => name === "execute"), [["execute", "view:zoom-75"]], "한 번, 고정 배율 명령");
  viewer.dispose();
  const plain = fakeStudio([]);
  const compare = await mountRhwp({ host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: true,
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, studio: plain.studio, trackSelection: "never" });
  assert.deepEqual(plain.calls.filter(([name]) => name === "execute"), [["execute", "view:zoom-100"]], "배율을 말하지 않은 마운트는 고정 100%");
  compare.dispose();
  const fitted = fakeStudio([]);
  const editor = await mountRhwp({ host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false, zoom: "fit",
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, preflight: async () => ({ editable: true }), studio: fitted.studio });
  assert.deepEqual(fitted.calls.filter(([name]) => name === "execute"), [["execute", "view:zoom-fit-width"]], "폭 맞춤은 Studio 의 폭 맞춤 명령");
  await editor.setZoom(100);
  await editor.setZoom("fit");
  assert.deepEqual(fitted.calls.filter(([name]) => name === "execute").slice(1), [["execute", "view:zoom-100"], ["execute", "view:zoom-fit-width"]],
    "숫자 배율로 돌아가면 Studio 는 고정 100% — 셸 CSS 배율과 곱하지 않는다");
  editor.dispose();
}));

test("IDE-06: fit width re-fits after the host is resized (debounced), never while fixed or hidden", () => {
  const timers = fakeTimers();
  const observers = [];
  const prior = globalThis.ResizeObserver;
  globalThis.ResizeObserver = class { constructor(callback) { this.callback = callback; this.observed = []; observers.push(this); }
    observe(target) { this.observed.push(target); } disconnect() { this.disconnected = true; } };
  return withDom(async () => {
    const fake = fakeStudio([]);
    const host = {};
    const handle = await mountRhwp({ host, content: b64("disk"), fileName: "a.hwpx", readOnly: false, zoom: "fit",
      onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, preflight: async () => ({ editable: true }), studio: fake.studio, trackSelection: "never" });
    const executes = () => fake.calls.filter(([name]) => name === "execute").map(([, id]) => id);
    assert.equal(observers.length, 1);
    assert.equal(observers[0].observed[0], host, "편집기 host 의 크기를 본다(속성 패널·분할선·창 크기)");
    const resize = (width) => observers[0].callback([{ contentRect: { width } }]);
    assert.equal(fake.options().width, "round(down, 100%, 1px)",
      "iframe 폭은 host 폭을 정수 CSS px 로 내린 값이다 — 소수 폭이면 Studio 의 정수 clientWidth 가 내용보다 모자라 빈 가로 스크롤이 선다");
    resize(900); resize(835.43);
    assert.deepEqual(executes(), ["view:zoom-fit-width"], "크기 변화가 몰려오는 동안에는 기다린다");
    timers.fireTimeouts();
    await settle();
    assert.deepEqual(executes(), ["view:zoom-fit-width", "view:zoom-fit-width"], "멈추면 한 번 다시 맞춘다");
    resize(0);
    timers.fireTimeouts();
    assert.equal(executes().length, 2, "숨은 탭(폭 0)은 맞추지 않는다 — 다시 보일 때 맞춘다");
    await handle.setZoom(100);
    resize(800);
    timers.fireTimeouts();
    assert.deepEqual(executes().slice(2), ["view:zoom-100"], "고정 배율 중에는 다시 맞추지 않는다");
    handle.dispose();
    assert.equal(observers[0].disconnected, true);
  }, timers).finally(() => { globalThis.ResizeObserver = prior; });
});

test("IDE-06 P-16: a preview range is one label-less synthetic marker, labels come down, and it yields to the Studio's 500 cap", () => withDom(async () => {
  const fake = fakeStudio([]);
  const markers = [];
  const studio = async (host, created) => { const editor = await fake.studio(host, created);
    const original = editor.setDecorations; editor.setDecorations = async (list, options) => { markers.push(list); return original(list, options); }; return editor; };
  const handle = await mountRhwp({ host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false, sectionEntries: ["Contents/section0.xml"],
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, preflight: async () => ({ editable: true }), studio, trackSelection: "never" });
  const slot = { id: "s", label: "특약", location: { entry: "Contents/section0.xml", start_paragraph: 0, end_paragraph: 2 }, options: [] };
  const range = { kind: "range", marker: "slot", location: { entry: "Contents/section0.xml", start_paragraph: 4, end_paragraph: 4 } };
  await handle.setDecorations({ fields: [], slots: [slot], mode: "structure", highlight: range });
  const drawn = markers.at(-1);
  assert.equal(drawn.length, 2);
  assert.deepEqual(drawn[1], { kind: "slot", label: "", emphasis: "strong", section: 0, startParagraph: 4, startOffset: 0, endParagraph: 4, endOffset: null },
    "합성 표지: 이름표 없음, 강하게, 문단 전체");
  assert.equal(drawn[0].emphasis, "subtle", "실제 경계는 옅게 물러선다");
  assert.deepEqual(fake.calls.filter(([name]) => name === "setDecorations").at(-1)[2], { labels: "none" }, "이름표 모드에서도 미리보기 중에는 이름표를 걷는다");
  await handle.setDecorations({ fields: [], slots: [slot], mode: "document", highlight: range });
  assert.deepEqual(markers.at(-1).map((marker) => marker.label), [""], "문서 모드에서는 미리보기 범위만 선다");
  const crowded = { name: "F", occurrences: Array.from({ length: 500 }, (_, index) => ({ entry: "Contents/section0.xml", paragraph: index })) };
  await handle.setDecorations({ fields: [crowded], slots: [], mode: "template", highlight: range });
  assert.equal(markers.at(-1).length, 500, "상한에 닿으면 합성 표지를 뺀다 — 장식 호출 전체가 던지지 않는다");
  assert.ok(markers.at(-1).every((marker) => marker.kind === "field"));
  handle.dispose();
}));

// ---- IDE-08: 선택 사각형(H3)·초점 없는 스크롤(H4)·문제 표지(H2) ----

test("IDE-08 H3: the vendored SDK accepts the selection end rect and rejects malformed ones; scrollToRange sends the range only", async () => {
  const context = { schemaVersion: 1, documentEpoch: 1, changeSeq: 0, page: 1, editable: true, collapsed: false, target: null,
    selectedTextSha256: null, range: null, rect: { x: 12.5, y: 40, width: 1, height: 18.75 } };
  const requests = [];
  const editorWith = (result) => new RhwpEditor({}, { supports: () => true, on: () => () => {},
    request: (method, params) => { requests.push([method, params]); return Promise.resolve(result); } });
  assert.deepEqual(await editorWith(context).getSelectionContext(), context);
  assert.equal((await editorWith({ ...context, rect: null }).getSelectionContext()).rect, null);
  const { rect: _rect, ...missing } = context;
  for (const bad of [missing, { ...context, rect: { x: 1, y: 2, width: 1 } }, { ...context, rect: { ...context.rect, y: Number.NaN } },
    { ...context, rect: { ...context.rect, height: -1 } }, { ...context, rect: { ...context.rect, extra: 0 } }]) {
    await assert.rejects(() => editorWith(bad).getSelectionContext(), (error) => error.code === "INVALID_RESPONSE");
  }
  const range = { section: 0, startParagraph: 2, startOffset: 1, endParagraph: 2, endOffset: 4 };
  assert.deepEqual(await editorWith({ scrolled: true }).scrollToRange(range), { scrolled: true });
  assert.deepEqual(requests.at(-1), ["scrollToRange", { range }]);
});

/** Studio stand-in whose selection context the test sets; polls fire on `timers.tick()`. */
function selectingStudio(hooks = {}) {
  const fake = fakeStudio([], { frame: { left: 10, top: 20, width: 300 }, frameWindow: { innerWidth: 200, innerHeight: 400 }, ...hooks });
  const state = { context: { range: null, rect: null } };
  const calls = [];
  const studio = async (host, created) => {
    const editor = await fake.studio(host, created);
    editor.getSelectionContext = async () => state.context;
    editor.focusRange = async (range) => { calls.push(["focusRange", range]); return { focused: true }; };
    editor.scrollToRange = async (range) => { calls.push(["scrollToRange", range]); return { scrolled: state.scrolled ?? true }; };
    return editor;
  };
  return { fake, state, calls, studio };
}
const at = (paragraph, start, end = start) => ({ start: { section: 0, paragraph, charOffset: start }, end: { section: 0, paragraph, charOffset: end } });

test("IDE-08 H3: the host gets the selection end line once a non-empty selection settles, and loses it on collapse, move or edit", () => {
  const timers = fakeTimers();
  return withDom(async () => {
    globalThis.document.hidden = false;
    const { fake, state, studio } = selectingStudio();
    const rects = [], selections = [];
    const handle = await mountRhwp({ host: { closest: () => null, offsetParent: {} }, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
      sectionEntries: ["Contents/section0.xml"], onChanged() {}, onSelectionChanged: (selection) => selections.push(selection),
      onSelectionRect: (rect) => rects.push(rect), onError: (error) => { throw error; }, preflight: async () => ({ editable: true }), studio });
    const poll = async (range, rect) => { state.context = { range, rect }; timers.tick(); await settle(); };
    const line = { x: 40, y: 60, width: 1, height: 20 };
    await poll(at(1, 3), line);
    assert.deepEqual(rects, [], "a caret (collapsed selection) has no selection-side UI");
    await poll(at(1, 3, 8), null);
    assert.deepEqual(rects, [], "mid-drag the Studio reports no rect — nothing may appear under the pointer");
    await poll(at(1, 3, 8), line);
    assert.deepEqual(rects, [{ left: 70, top: 110, bottom: 140 }], "once settled: iframe px scaled by the frame (150%) into host px");
    await poll(at(1, 3, 8), line);
    assert.equal(rects.length, 1, "an unchanged selection is not re-reported");
    await poll(at(1, 3, 8), { ...line, y: 30 });
    assert.deepEqual(rects.at(-1), null, "the line moved under the same selection (scroll) — hide");
    await poll(at(1, 3, 8), { ...line, y: 10 });
    assert.equal(rects.length, 2, "and it does not come back for that selection");
    await poll(at(1, 3, 9), { ...line, y: 100 });
    assert.deepEqual(rects.at(-1), { left: 70, top: 170, bottom: 200 }, "a new selection reports again");
    fake.userType("x");
    assert.deepEqual(rects.at(-1), null, "an edit takes it down");
    await poll(at(1, 3, 9), { ...line, y: 100 });
    assert.equal(rects.length, 4, "the edited selection is not re-reported");
    await poll(at(1, 0, 9), { ...line, y: 500 });
    assert.equal(rects.length, 4, "a selection end outside the frame is not reported");
    await poll(at(1, 0, 2), line);
    await poll(at(1, 2), line);
    assert.deepEqual(rects.slice(-2), [{ left: 70, top: 110, bottom: 140 }, null], "a collapse takes it down");
    assert.ok(selections.length >= 5, "selection reports still flow to the host");
    handle.dispose();
  }, timers);
});

test("IDE-08 H3: a selection the host set follows its own centring scroll instead of being hidden as a user scroll; later moves hide it", () => {
  const timers = fakeTimers();
  return withDom(async () => {
    globalThis.document.hidden = false;
    const realNow = performance.now.bind(performance);
    let clock = 1000;
    performance.now = () => clock;
    try {
      const { state, studio } = selectingStudio();
      const rects = [];
      const handle = await mountRhwp({ host: { closest: () => null, offsetParent: {} }, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
        sectionEntries: ["Contents/section0.xml"], onChanged() {}, onSelectionChanged() {},
        onSelectionRect: (rect) => rects.push(rect), onError: (error) => { throw error; }, preflight: async () => ({ editable: true }), studio });
      const poll = async (range, rect) => { state.context = { range, rect }; timers.tick(); await settle(); };
      const line = { x: 40, y: 60, width: 1, height: 20 };
      await handle.focus({ entry: "Contents/section0.xml", start_paragraph: 1, end_paragraph: 9, start: 0 });
      await poll(at(1, 0, 9), line);
      await poll(at(1, 0, 9), { ...line, y: 30 });
      assert.deepEqual(rects, [{ left: 70, top: 110, bottom: 140 }, { left: 70, top: 65, bottom: 95 }],
        "the Studio's centring scroll after a host-set selection moves the bar with the line — it is not a user scroll");
      clock += 2000;
      await poll(at(1, 0, 9), { ...line, y: 10 });
      assert.deepEqual(rects.at(-1), null, "once settled, a moved line is the user scrolling — hide as before");
      handle.dispose();
    } finally { performance.now = realNow; }
  }, timers);
});

test("IDE-08 H4: scrollTo moves only the Studio viewport to the target's range — never focusRange", () => withDom(async () => {
  const { state, calls, studio } = selectingStudio();
  const handle = await mountRhwp({ host: {}, content: b64("disk"), fileName: "r.hwpx", readOnly: true, sectionEntries: ["Contents/section0.xml"],
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, studio, trackSelection: "never" });
  assert.equal(await handle.scrollTo({ entry: "Contents/section0.xml", paragraph: 2, start: 1, end: 4 }), true);
  const cell = [{ parent_paragraph: 1, control: 0, cell: 2, paragraph: 3 }];
  state.scrolled = false;
  assert.equal(await handle.scrollTo({ entry: "Contents/section0.xml", paragraph: 3, cell_path: cell }), false, "not placeable: the view stays");
  assert.deepEqual(calls, [
    ["scrollToRange", { section: 0, startParagraph: 2, startOffset: 1, endParagraph: 2, endOffset: 4 }],
    ["scrollToRange", { section: 0, startParagraph: 3, startOffset: 0, endParagraph: 3, endOffset: null,
      cellPath: [{ parentParagraph: 1, control: 0, cell: 2, paragraph: 3 }] }]]);
  await assert.rejects(() => handle.scrollTo({ entry: "Contents/other.xml", paragraph: 0 }), /HWPX 본문 위치를 찾을 수 없습니다/);
  handle.dispose();
}));

test("IDE-08 H2: problems become problem markers (error strong, warning subtle) in every mode and give way first to the 500 cap", () => withDom(async () => {
  const fake = fakeStudio([]);
  const markers = [];
  const studio = async (host, created) => { const editor = await fake.studio(host, created);
    const original = editor.setDecorations; editor.setDecorations = async (list, options) => { markers.push([list, options]); return original(list, options); }; return editor; };
  const handle = await mountRhwp({ host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false, sectionEntries: ["Contents/section0.xml"],
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; }, preflight: async () => ({ editable: true }), studio, trackSelection: "never" });
  const entry = "Contents/section0.xml";
  const long = "가".repeat(200);
  const problems = [
    { severity: "error", message: "끝 표지가 없습니다.", location: { entry, paragraph: 4 } },
    { severity: "warning", message: "평문으로 남은 필드 표기입니다.", location: { entry, paragraph: 1, start: 2, end: 8 } },
    { severity: "warning", message: long, location: { entry, paragraph: 2, start: 0, end: 1, cell_path: [{ parent_paragraph: 0, control: 0, cell: 1, paragraph: 2 }] } },
    { severity: "info", message: "모르는 심각도", location: { entry, paragraph: 3 } },
    { severity: "error", message: "위치 없음", location: null },
    { severity: "error", message: "다른 구역", location: { entry: "Contents/other.xml", paragraph: 0 } },
  ];
  const field = { name: "이름", occurrences: [{ entry, paragraph: 1, start: 2, end: 8 }] };
  await handle.setDecorations({ fields: [field], slots: [], mode: "template", highlight: null, problems });
  const [drawn, options] = markers.at(-1);
  assert.deepEqual(options, { labels: "selected" });
  assert.deepEqual(drawn.map((marker) => [marker.kind, marker.emphasis]), [["field", "strong"], ["problem", "strong"], ["problem", "subtle"], ["problem", "subtle"]],
    "필드 뒤에 문제 표지 — 모르는 심각도·위치 없는 문제·모르는 구역은 칠하지 않는다");
  assert.deepEqual(drawn[1], { kind: "problem", label: "끝 표지가 없습니다.", emphasis: "strong", section: 0, startParagraph: 4, startOffset: 0, endParagraph: 4, endOffset: null },
    "글자 위치가 없으면 문단 전체");
  assert.equal(Array.from(drawn[3].label).length, 160, "Studio 이름표 한도 안으로 자른다");
  assert.ok(drawn[3].label.endsWith("…"));
  assert.deepEqual(drawn[3].cellPath, [{ parentParagraph: 0, control: 0, cell: 1, paragraph: 2 }]);

  await handle.setDecorations({ fields: [field], slots: [], mode: "document", highlight: null, problems });
  assert.deepEqual(markers.at(-1)[0].map((marker) => marker.kind), ["problem", "problem", "problem"], "문서 모드에서도 문제는 선다(표시가 아니라 경보)");
  assert.deepEqual(markers.at(-1)[1], { labels: "none" });

  const debug = console.debug;
  const notes = [];
  console.debug = (...args) => notes.push(args.join(" "));
  try {
    const crowded = { name: "F", occurrences: Array.from({ length: 498 }, (_, index) => ({ entry, paragraph: index })) };
    await handle.setDecorations({ fields: [crowded], slots: [], mode: "template", highlight: null, problems });
    assert.equal(markers.at(-1)[0].length, 500, "합계가 상한을 넘지 않는다");
    assert.deepEqual(markers.at(-1)[0].slice(-2).map((marker) => marker.kind), ["problem", "problem"], "넘치는 몫은 문제 표지에서 덜어 낸다");
    await handle.setDecorations({ fields: [crowded], slots: [], mode: "template", highlight: null, problems });
    assert.equal(notes.length, 1, "덜어 냈다는 기록은 콘솔 debug 에 마운트당 한 번");
    assert.match(notes[0], /1 problem markers dropped/);
  } finally { console.debug = debug; }
  handle.dispose();
}));
