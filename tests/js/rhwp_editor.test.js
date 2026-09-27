import test from "node:test";
import assert from "node:assert/strict";
import { mountRhwp } from "../../frontend/src/editorview/rhwp_editor.ts";

const b64 = (text) => Buffer.from(text, "utf8").toString("base64");

/** Pinned-Studio stand-in that models the vendored embedded read-only gate: while read-only,
 *  every mutation — host plugin transactions included — is dropped and the plugin host rejects
 *  it (`host.ts` "현재 편집 모드에서 거절된 작업입니다"). */
function fakeStudio(log) {
  let readOnly = false;
  let bytes = new TextEncoder().encode("mounted");
  const changed = new Set();
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
        if (readOnly) throw new Error(`현재 편집 모드에서 거절된 작업입니다: replace:${args[1]}`);
        log.push("replace");
        bytes = args[0];
        for (const listener of changed) listener({});
      },
    },
    destroy() {},
  };
  return async () => editor;
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

test("applySnapshot lifts the input lock for the replace so the embedded gate accepts it", () => withDom(async () => {
  const log = [];
  const emitted = [];
  const handle = await mountRhwp({
    host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
    onChanged: (content) => emitted.push(content), onSelectionChanged() {}, onError: (error) => { throw error; },
    preflight: async () => ({ editable: true }), studio: fakeStudio(log),
  });
  log.length = 0;
  await handle.applySnapshot(b64("created"), "create_field", b64("mounted"));
  // The flush/compare runs under the lock; the replace itself runs unlocked; the lock is released after.
  assert.deepEqual(log, [
    "readOnly:true", "export:mounted", "readOnly:false", "replace", "export:created", "readOnly:false",
  ]);
  assert.deepEqual(emitted, [b64("created")]);
  handle.dispose();
}));

test("applySnapshot still refuses a document whose editor content moved under the preview", () => withDom(async () => {
  const log = [];
  const handle = await mountRhwp({
    host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
    onChanged() {}, onSelectionChanged() {}, onError: (error) => { throw error; },
    preflight: async () => ({ editable: true }), studio: fakeStudio(log),
  });
  await assert.rejects(handle.applySnapshot(b64("created"), "create_field", b64("stale")),
    /편집 중 문서가 변경되었습니다/);
  assert.ok(!log.includes("replace"));
  handle.dispose();
}));

test("applySnapshot never mutates a compatibility-blocked (read-only) document", () => withDom(async () => {
  const log = [];
  const handle = await mountRhwp({
    host: {}, content: b64("disk"), fileName: "a.hwpx", readOnly: false,
    onChanged() {}, onSelectionChanged() {}, onError() {}, onCompatibility() {},
    preflight: async () => ({ editable: false, diagnostics: ["xml_changed"] }), studio: fakeStudio(log),
  });
  await assert.rejects(handle.applySnapshot(b64("created"), "create_field"), /읽기 전용/);
  assert.ok(!log.includes("replace"));
  handle.dispose();
}));
