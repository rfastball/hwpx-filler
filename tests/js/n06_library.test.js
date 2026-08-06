/* N-06 lane C translated at R4-01: the library read surface is a React controller.
   These eleven cases preserve the former lifecycle, late-binding, and cross-screen
   assertions without importing the retired imperative DOM producer. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createLibraryController } from "../../frontend/src/screens/library.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";

const SRC_URL = new URL("../../frontend/src/screens/library.ts", import.meta.url);
const SRC = readFileSync(SRC_URL, "utf8");
const tick = () => new Promise((resolve) => setImmediate(resolve));

const SURFACE = [
  "init", "model", "moveModel", "setMove", "closeMove", "confirmMove", "axis",
  "toggleFavorite", "runPrimary", "newWork", "editWork", "renameJob", "openMove",
  "editTags", "cloneJob", "removeJob", "relink", "revealCorrupt", "deleteCorrupt",
  "showGroupMenu", "closeGroupMenu", "handleGroupMenu", "doc", "client", "notify",
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
  ports.jobRead.bindReact(jobReadImpl);
  ports.editorEntry.bindLegacy({
    openGuarded(...args) { editor.push(["openGuarded", ...args]); return true; },
    newDraft(...args) { editor.push(["newDraft", ...args]); return true; },
    newDraftFromData(...args) { editor.push(["newDraftFromData", ...args]); return true; },
    land(...args) { editor.push(["land", ...args]); },
    confirmDiscard(...args) { editor.push(["confirmDiscard", ...args]); return true; },
    restoreEntryFocus(...args) { editor.push(["restoreEntryFocus", ...args]); },
  });
  const services = createServiceHandoffPorts();
  services.relink.bindLegacy({ relinkTemplate: async (...args) => { menuCalls.push(["relink", ...args]); return true; } });
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

test("그룹 이동 — 선택 snapshot에서 dialog state를 만들고 확정한다", async () => {
  const h = build({ snapshot: {
    detail: { name: "작업A", group: "기존" }, group_names: ["기존", "새 그룹"], sections: [],
  } });
  h.controller.openMove("작업A", {});
  h.controller.setMove({ choice: "새 그룹" });
  assert.equal(h.controller.moveModel.getSnapshot().choice, "새 그룹");
  await h.controller.confirmMove();
  assert.deepEqual(h.dispatchCalls.map((row) => row.slice(0, 2)), [["job", "set_group"], ["library", "refresh"]]);
  assert.equal(h.controller.moveModel.getSnapshot(), null);
});

test("즐겨찾기 연타 — 같은 작업의 최신 intent를 직렬화한다", async () => {
  const h = build();
  await Promise.all([h.controller.toggleFavorite("작업A", false), h.controller.toggleFavorite("작업A", false)]);
  assert.deepEqual(h.dispatchCalls.map((row) => row[2].value), [true, false]);
});

test("구조 음성 — legacy producer와 제품 전역 없이 React/port 직접 간선만 쓴다", () => {
  assert.equal(SRC.includes("frontend/js/screens/library.js"), false);
  assert.equal(/(?:window|globalThis)\.(?:Bridge|Nav|JobScreen|LibraryScreen)\b/.test(SRC), false);
  assert.equal(/export\s+default/.test(SRC), false);
  assert.ok(SRC.includes('from "./ports.ts"'));
  assert.ok(SRC.includes('from "../ports/service_handoff.ts"'));
  assert.ok(SRC.indexOf('"prefer_work"') < SRC.indexOf('deps.navigation.go("job")'));
});
