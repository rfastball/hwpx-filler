import test from "node:test";
import assert from "node:assert/strict";

import { createLibraryController } from "../../frontend/src/screens/library.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";

function model(value) {
  return { getSnapshot: () => value, subscribe: () => () => {} };
}

function build(snapshot, dispatch) {
  const ports = createScreenPorts();
  const browse = [];
  const drafts = [];
  ports.jobRead.bindReact({ refreshList() {}, async openBrowseNeedsAction(name) { browse.push(name); } });
  ports.editorEntry.bindLegacy({
    openGuarded() {}, newDraft() { drafts.push("new"); }, newDraftFromData() {},
    land() {}, confirmDiscard() {}, restoreEntryFocus() {},
  });
  const services = createServiceHandoffPorts();
  services.relink.bindLegacy({ relinkTemplate: async () => true });
  const navigation = [];
  const controller = createLibraryController({
    doc: { getElementById: () => null },
    runtime: { model: () => model(snapshot), loadInitial: async () => snapshot },
    client: {
      dispatch,
      invoke: async () => ({ ok: true, value: null }),
    },
    ports, services,
    modal: { confirm: async () => false, prompt: async () => null, open() {}, close() {} },
    undo: { show() {} }, groupMenu: { show() {}, hide() {} },
    navigation: { go: (name) => navigation.push(name) }, notify: assert.fail,
  });
  return { controller, browse, drafts, navigation };
}

test("library 축 액션은 호출 순서를 직렬화한다", async () => {
  const calls = [];
  let active = 0;
  let peak = 0;
  const { controller } = build({ detail: null }, async (_screen, action) => {
    active += 1; peak = Math.max(peak, active);
    calls.push(action);
    await Promise.resolve();
    active -= 1;
    return { ok: true, value: {} };
  });
  await Promise.all([controller.axis("set_view", { view: "recent" }), controller.axis("set_mode", { mode: "txt" })]);
  assert.deepEqual(calls, ["set_view", "set_mode"]);
  assert.equal(peak, 1);
});

test("incompatible 작업의 사용은 job 착지 뒤 확인 필요 탐색으로 위임한다", async () => {
  const snapshot = { detail: { name: "작업A", primary: { target: "job" } } };
  const calls = [];
  const { controller, browse, navigation } = build(snapshot, async (screen, action, payload) => {
    calls.push([screen, action, payload]);
    return { ok: true, value: { reason: "incompatible" } };
  });
  await controller.runPrimary("작업A");
  assert.deepEqual(calls[0], ["job", "prefer_work", { name: "작업A" }]);
  assert.deepEqual(navigation, ["job"]);
  assert.deepEqual(browse, ["작업A"]);
});
