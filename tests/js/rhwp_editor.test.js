import test from "node:test";
import assert from "node:assert/strict";
import { mountRhwp } from "../../frontend/src/editorview/rhwp_editor.ts";

const b64 = (text) => Buffer.from(text, "utf8").toString("base64");

/** Pinned-Studio stand-in that models the vendored embedded read-only gate: while read-only,
 *  user input is rejected (`input-handler.isOperationAllowedInEditMode`) but a host transaction
 *  issued through the hwpctrl plugin (`host.ts` marks it `hostTransaction`) still runs.
 *  `hooks.duringReplace` lets a test play a user keystroke while the replace RPC is in flight. */
function fakeStudio(log, hooks = {}) {
  let readOnly = false;
  let bytes = new TextEncoder().encode("mounted");
  const changed = new Set();
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
    async setDecorations() {},
    onDocumentChanged(listener) { changed.add(listener); return () => changed.delete(listener); },
    onShortcut() { return () => {}; },
    chrome: { async set() {} },
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
  return { studio: async () => editor, userType };
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
