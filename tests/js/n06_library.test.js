/* Library controller behavior: lifecycle, late binding, and serialized intents. */
import test from "node:test";
import assert from "node:assert/strict";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { LibraryScreen, createLibraryController } from "../../frontend/src/screens/library.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";

const tick = () => new Promise((resolve) => setImmediate(resolve));

/* 그룹·태그 동사(moveModel·setMove·closeMove·confirmMove·openMove·editTags·
   showGroupMenu·closeGroupMenu·handleGroupMenu·groupContextMenu)는 U4 §2-30 에서
   표면과 함께 사라졌다 — 판정·영속은 링1·모델에 동결로 남는다.
   `installExamples`(#891 빈 상태의 두 번째 출구)도 같은 처분이다 — 튜토리얼 진입 표면과
   함께 배포본에서 걷혔고(#941) `tpl` 채널의 액션·스냅샷 축은 동결로 남는다. */
const SURFACE = [
  "init", "model", "axis",
  "toggleFavorite", "runPrimary", "newWork", "editWork", "renameJob",
  "cloneJob", "removeJob", "relink", "revealCorrupt", "deleteCorrupt",
  "doc", "client", "popover", "notify",
];

function build(options = {}) {
  let snapshot = options.snapshot ?? { detail: null, sections: [] };
  const runtimeCalls = [];
  const dispatchCalls = [];
  const invokes = [];
  const notifications = [];
  const navigation = [];
  const browse = [];
  const editor = [];
  const modalCalls = [];
  const menuCalls = [];
  const ports = createScreenPorts();
  const jobReadImpl = {
    refreshList() {},
    async openBrowseNeedsAction(name) { browse.push(name); },
  };
  ports.jobRead.bind(jobReadImpl);
  ports.editorEntry.bind({
    openGuarded(...args) { editor.push(["openGuarded", ...args]); return true; },
    newDraft(...args) { editor.push(["newDraft", ...args]); return true; },
    newDraftFromData(...args) { editor.push(["newDraftFromData", ...args]); return true; },
    land(...args) { editor.push(["land", ...args]); },
    confirmDiscard(...args) { editor.push(["confirmDiscard", ...args]); return true; },
    restoreEntryFocus(...args) { editor.push(["restoreEntryFocus", ...args]); },
  });
  const services = createServiceHandoffPorts();
  services.relink.bind({ relinkTemplate: async (...args) => { menuCalls.push(["relink", ...args]); return true; } });
  const runtime = {
    model: () => ({ getSnapshot: () => snapshot, subscribe: () => () => {} }),
    loadInitial: async (screen) => {
      runtimeCalls.push(screen);
      if (options.initialError) throw options.initialError;
      return snapshot;
    },
  };
  const client = {
    dispatch: async (screen, action, payload) => {
      dispatchCalls.push([screen, action, payload]);
      const value = options.dispatch ? await options.dispatch(screen, action, payload) : {};
      return { ok: true, value };
    },
    invoke: async (method, ...args) => {
      invokes.push([method, ...args]);
      return { ok: true, value: options.invoke ? await options.invoke(method, ...args) : null };
    },
  };
  const modal = {
    confirm: async (spec) => { modalCalls.push(["confirm", spec]); return options.confirm ?? false; },
    prompt: async (spec) => { modalCalls.push(["prompt", spec]); return options.prompt ?? null; },
    open: (id, spec) => modalCalls.push(["open", id, spec]),
    close: (id) => modalCalls.push(["close", id]),
  };
  const controller = createLibraryController({
    doc: { activeElement: null, getElementById: () => null }, runtime, client, ports, services, modal,
    undo: { show: (...args) => menuCalls.push(["undo", ...args]) },
    popover: { place() {}, wireDismiss: () => () => {} },
    groupMenu: { show: (...args) => menuCalls.push(["show", ...args]), hide: () => menuCalls.push(["hide"]) },
    navigation: { go: (screen) => navigation.push(screen) },
    notify: (message) => notifications.push(String(message)),
  });
  return {
    controller, client, ports, jobReadImpl, runtimeCalls, dispatchCalls, invokes,
    notifications, navigation, browse, editor, modalCalls, menuCalls,
    setSnapshot(value) { snapshot = value; },
  };
}

test("공개 표면 — React library controller 키가 정확하다", () => {
  assert.deepEqual(Object.keys(build().controller), SURFACE);
});

test("init — initial pull은 screen runtime 한 곳에 위임한다", async () => {
  const h = build();
  await h.controller.init();
  assert.deepEqual(h.runtimeCalls, ["library"]);
});

test("첫 initial 실패 — controller가 조용히 삼키지 않는다", async () => {
  const h = build({ initialError: new Error("initial down") });
  await assert.rejects(h.controller.init(), /initial down/);
});

test("축 액션 — 호출 순서를 한 체인으로 직렬화한다", async () => {
  let active = 0;
  let peak = 0;
  const h = build({ dispatch: async () => {
    active += 1; peak = Math.max(peak, active); await tick(); active -= 1; return {};
  } });
  await Promise.all([
    h.controller.axis("set_view", { view: "recent" }),
    h.controller.axis("set_mode", { mode: "txt" }),
  ]);
  assert.equal(peak, 1);
  assert.deepEqual(h.dispatchCalls.map((row) => row[1]), ["set_view", "set_mode"]);
});

test("문서 만들기에서 사용 — incompatible이면 job 착지 뒤 확인 필요 탐색", async () => {
  const h = build({
    snapshot: { detail: { name: "작업A", primary: { target: "job" } } },
    dispatch: async (_screen, action) => action === "prefer_work" ? { reason: "incompatible" } : {},
  });
  await h.controller.runPrimary("작업A");
  assert.deepEqual(h.dispatchCalls[0], ["job", "prefer_work", { name: "작업A" }]);
  assert.deepEqual(h.navigation, ["job"]);
  assert.deepEqual(h.browse, ["작업A"]);
});

test("문서 만들기에서 사용 — compatible이면 명시 선택 뒤 job 착지", async () => {
  const h = build({
    snapshot: { detail: { name: "작업A", primary: { target: "job" } } },
    dispatch: async (_screen, action) => action === "prefer_work" ? { promoted: true } : {},
  });
  await h.controller.runPrimary("작업A");
  assert.deepEqual(h.dispatchCalls[0], ["job", "prefer_work", { name: "작업A" }]);
  assert.deepEqual(h.navigation, ["job"]);
  assert.deepEqual(h.browse, []);
});

test("편집 대상 primary — EditorEntry 6-key port로 위임한다", async () => {
  const h = build({ snapshot: { detail: { name: "작업A", primary: { target: "editor" } } } });
  await h.controller.runPrimary("작업A");
  assert.equal(h.editor[0][0], "openGuarded");
  assert.equal(h.editor[0][1], "작업A");
  assert.equal(h.editor[0][2].entry_reason, "library");
  assert.deepEqual(h.navigation, []);
});

test("JobReadPort late binding — 구성 뒤 교체한 메서드가 다음 호출에 잡힌다", async () => {
  const h = build({
    snapshot: { detail: { name: "작업A", primary: { target: "job" } } },
    dispatch: async () => ({ reason: "incompatible" }),
  });
  const late = [];
  h.jobReadImpl.openBrowseNeedsAction = async (name) => late.push(name);
  await h.controller.runPrimary("작업A");
  assert.deepEqual(late, ["작업A"]);
  assert.deepEqual(h.browse, []);
});

test("BridgeClient late binding — 교체한 dispatch가 다음 발신을 받는다", async () => {
  const h = build();
  const swapped = [];
  h.client.dispatch = async (...args) => { swapped.push(args); return { ok: true, value: {} }; };
  await h.controller.cloneJob("작업A");
  assert.deepEqual(swapped, [["library", "clone_job", { name: "작업A" }]]);
});

test("즐겨찾기 연타 — 같은 작업의 최신 intent를 직렬화한다", async () => {
  const h = build();
  await Promise.all([h.controller.toggleFavorite("작업A", false), h.controller.toggleFavorite("작업A", false)]);
  assert.deepEqual(h.dispatchCalls.map((row) => row[2].value), [true, false]);
});
