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
  ports.jobRead.bind({ refreshList() {}, async openBrowseNeedsAction(name) { browse.push(name); } });
  ports.editorEntry.bind({
    openGuarded() {}, newDraft() { drafts.push("new"); }, newDraftFromData() {},
    land() {}, confirmDiscard() {}, restoreEntryFocus() {},
  });
  const services = createServiceHandoffPorts();
  services.relink.bind({ relinkTemplate: async () => true });
  const navigation = [];
  const notices = [];
  const controller = createLibraryController({
    doc: { getElementById: () => null },
    runtime: { model: () => model(snapshot), loadInitial: async () => snapshot },
    client: {
      dispatch,
      invoke: async () => ({ ok: true, value: null }),
    },
    ports, services,
    modal: { confirm: async () => false, prompt: async () => null, open() {}, close() {} },
    undo: { show() {} },
    popover: { place() {}, wireDismiss: () => () => {} },
    navigation: { go: (name) => navigation.push(name) }, notify: (message) => notices.push(message),
  });
  return { controller, browse, drafts, navigation, notices };
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

test("그룹 메뉴 내용·열림 정체는 React ContextMenu 상태가 소유한다", () => {
  const { controller } = build({ detail: null }, async () => ({ ok: true, value: {} }));
  const trigger = { contains: () => false };
  controller.showGroupMenu("사업부", trigger);
  const state = controller.groupContextMenu.model.getSnapshot();
  assert.equal(state.trigger, trigger);
  assert.deepEqual(state.items, [
    { action: "rename", label: "그룹 이름 변경…" },
    { action: "disband", label: "그룹 해산", danger: true, separatorBefore: true },
  ]);
  controller.closeGroupMenu();
  assert.equal(controller.groupContextMenu.model.getSnapshot(), null);
});

test("음성 — 그룹 없음 관리 동작은 메뉴를 닫고 사유를 재진술한다", () => {
  const { controller, notices } = build({ detail: null }, async () => ({ ok: true, value: {} }));
  controller.showGroupMenu("", { contains: () => false });
  controller.handleGroupMenu("disband");
  assert.equal(controller.groupContextMenu.model.getSnapshot(), null);
  assert.deepEqual(notices, ["「그룹 없음」은 이름을 바꾸거나 해산할 수 없습니다."]);
});
