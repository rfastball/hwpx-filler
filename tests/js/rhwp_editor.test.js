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
    async exportHwpx() { log.push(`export:${new TextDecoder().decode(bytes)}`); return bytes; },
    async setReadOnly(value) { readOnly = value; log.push(`readOnly:${value}`); },
    async getSelectionContext() { return { range: null }; },
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

async function withDom(run) {
  const priorDocument = globalThis.document;
  const priorWindow = globalThis.window;
  globalThis.document = { baseURI: "http://127.0.0.1/index.html", hidden: true };
  globalThis.window = { setInterval: () => 1, clearInterval() {} };
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
