/* Library controller behavior: lifecycle, late binding, and serialized intents. */
import test from "node:test";
import assert from "node:assert/strict";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { LibraryScreen, createLibraryController } from "../../frontend/src/screens/library.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";

const tick = () => new Promise((resolve) => setImmediate(resolve));

const SURFACE = [
  "init", "model", "moveModel", "setMove", "closeMove", "confirmMove", "axis",
  "toggleFavorite", "runPrimary", "installExamples", "newWork", "editWork", "renameJob", "openMove",
  "editTags", "cloneJob", "removeJob", "relink", "revealCorrupt", "deleteCorrupt",
  "showGroupMenu", "closeGroupMenu", "handleGroupMenu", "doc", "client",
  "groupContextMenu", "popover", "notify",
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

/* ---------------- 동봉 예제 진입점 — #891 ---------------- */

const EXAMPLES = { installed: false, label: "예제로 시작하기…", hint: "동봉 예제 7건" };

function markupOf(snapshot) {
  const h = build({ snapshot });
  return renderToStaticMarkup(createElement(LibraryScreen, { controller: h.controller }));
}

test("#891 빈 상태의 출구는 둘 — 첫 작업 만들기와 동봉 예제", () => {
  const markup = markupOf({
    is_empty: true, detail: null, sections: [], examples: EXAMPLES,
  });
  assert.ok(markup.includes("data-new-work"), "직접 만들기 출구는 그대로다");
  assert.ok(markup.includes("data-install-examples"), "예제 출구가 없다");
  assert.ok(markup.includes("예제로 시작하기…"), "라벨은 스냅샷이 낸 값이다");
});

test("#891 필터가 비운 갈래에는 예제 버튼을 두지 않는다", () => {
  const markup = markupOf({
    is_empty: false, detail: null, examples: EXAMPLES,
    sections: [{ value: "", label: "그룹 없음", count: 0, headed: false, rows: [] }],
  });
  assert.ok(markup.includes("data-clear-filters"), "여기서 할 일은 필터를 지우는 것이다");
  assert.equal(markup.includes("data-install-examples"), false,
    "라이브러리를 채우는 출구는 이 갈래의 답이 아니다");
});

test("#891 설치는 tpl 채널의 확인 왕복이고 성공 뒤 이 화면을 재당긴다", async () => {
  const h = build({
    confirm: true,
    dispatch: async (screen, action, payload) => (
      screen === "tpl" && action === "install_examples" && !payload.confirm
        ? { needs_confirm: true, confirm_text: "7건을 씁니다" }
        : { ok: true }
    ),
  });
  await h.controller.installExamples();
  assert.deepEqual(
    h.dispatchCalls.map((row) => [row[0], row[1]]),
    [["tpl", "install_examples"], ["tpl", "install_examples"], ["library", "refresh"]],
    "실행은 tpl, 재당김은 자기 화면이다",
  );
  assert.ok(h.modalCalls[0][1].body.includes("7건을 씁니다"),
    "확인 본문은 Python 재진술을 싣는다");
});

test("#891 취소하면 아무것도 실행되지 않는다", async () => {
  const h = build({
    confirm: false,
    dispatch: async () => ({ needs_confirm: true, confirm_text: "7건을 씁니다" }),
  });
  await h.controller.installExamples();
  assert.deepEqual(h.dispatchCalls.map((row) => row[2]), [{}]);
});
