/* R4-02 — 이탈 거래의 양/음성 대조. **확인 전에는 draft 를 파기하지 않는다.**
 *
 * 편집기와 작업대는 서로 다른 절차를 쓰지만 같은 규율 위에 선다: 나가는 길에 잃을 것이
 * 있으면 사용자가 처분을 고르고, 그 처분이 실제로 성사된 뒤에만 화면을 뜬다. 이 파일은
 * 그 절차의 **순서**와, 각 갈림길에서 「안 나간다」가 실제로 안 나가는가를 잰다.
 *
 * 패킷 rev2 §4.1(편집기) · §4.2(작업대)의 단계가 그대로 목차다. 음성 fixture 는 §9 목록:
 * save 취소 · save 실패 · dirty 질의 실패 · discard 취소 · refresh 실패.
 *
 * 이 성질들이 여기 모인 이유는 하나다 — 화면별 파일에 흩으면 「편집기는 지키는데 작업대는
 * 안 지킨다」가 두 초록 사이에 숨는다. 잃을 것을 다루는 규율은 화면 수만큼 있지 않다.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createEditorController } from "../../frontend/src/screens/editor.ts";
import { createWorkbenchController } from "../../frontend/src/screens/workbench.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";
import { createScreenRuntime } from "../../frontend/src/screens/runtime.ts";
import { createSnapshotStore } from "../../frontend/src/state/store.ts";
import { Intent } from "../../frontend/js/intent.js";

/* ================= 편집기 하니스 ================= */

function editorHarness(options = {}) {
  const trace = [];
  const notices = [];
  const client = {
    async initial() { return { ok: true, value: options.snapshot ?? {} }; },
    async dispatch(screen, action, payload) {
      trace.push(["dispatch", screen, action, payload]);
      if (options.dispatch) return { ok: true, value: await options.dispatch(screen, action, payload) };
      return { ok: true, value: {} };
    },
    async invoke(method) {
      trace.push(["invoke", method]);
      if (method === "editor_has_unsaved_work") {
        if (options.unsavedQueryFails) return { ok: false, failure: { message: "브리지 끊김" } };
        return { ok: true, value: options.unsaved === true };
      }
      return { ok: true, value: null };
    },
  };
  const store = createSnapshotStore({ alarm: assert.fail });
  const runtime = createScreenRuntime({ client, store });
  const ports = createScreenPorts();
  ports.jobRead.bind({
    refreshList: () => { trace.push(["refreshList"]); }, openBrowseNeedsAction: async () => {},
  });
  ports.editorEntry.bind({
    openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {},
    confirmDiscard: async (body) => {
      trace.push(["entry.confirmDiscard", body]);
      return options.confirmDiscard ?? false;
    },
    restoreEntryFocus: () => { trace.push(["restoreEntryFocus"]); },
  });
  const services = createServiceHandoffPorts();
  services.sheetPicker.bind({ choose: async () => null });
  const controller = createEditorController({
    doc: { getElementById: () => null, querySelector: () => null },
    runtime, client, ports, services,
    modal: {
      confirm: async (spec) => { trace.push(["modal.confirm", spec]); return options.confirm ?? false; },
      prompt: async () => null,
      choose: async (spec) => { trace.push(["modal.choose", spec]); return options.choose ?? null; },
      open() {}, close() {},
    },
    undo: { show() {} },
    popover: { wireDismiss: () => () => {} },
    rowMenu: { show() {}, hide() {} },
    groupMove: { open() {} },
    chain: Intent,
    navigation: {
      refresh: async (target) => {
        trace.push(["refresh", target]);
        if (options.refreshFails) throw new Error("stale disk");
      },
      go: (target, opts) => { trace.push(["go", target, opts]); },
    },
    notify: (message) => notices.push(String(message)),
  });
  return {
    controller, trace, notices,
    names: () => trace.map((row) => row[0]),
    actions: () => trace.filter((row) => row[0] === "dispatch").map((row) => row[2]),
    async ready() { await controller.init(); },
  };
}

const DIRTY_JOB = { section: "binding", sections: ["binding"], dirty: true, is_draft: false, rows: [] };
const CLEAN_JOB = { section: "binding", sections: ["binding"], dirty: false, is_draft: false, rows: [] };
const DRAFT = { section: "template", sections: ["template"], dirty: false, is_draft: true, rows: [] };

/* ---------------- 편집기 §4.1 ---------------- */

test("편집기 양성 — dirty 저장 이탈은 save → refresh → go → 초점 복원 순서를 지킨다", async () => {
  const h = editorHarness({
    snapshot: DIRTY_JOB, choose: "save",
    dispatch: (_s, action) => (action === "save" ? { ok: true } : {}),
  });
  await h.ready();
  await h.controller.leaveTo("job");
  assert.deepEqual(h.names(), [
    "modal.choose", "dispatch", "refreshList", "refresh", "go", "restoreEntryFocus",
  ]);
  assert.deepEqual(h.actions(), ["save"]);
  assert.deepEqual(h.trace.find((row) => row[0] === "go").slice(1),
    ["job", { force: true, refreshed: true }]);
});

test("편집기 양성 — discard 는 **고른 뒤에야** discard_patch 를 부른다", async () => {
  const h = editorHarness({ snapshot: DIRTY_JOB, choose: "discard" });
  await h.ready();
  await h.controller.leaveTo("job");
  const chooseAt = h.names().indexOf("modal.choose");
  const discardAt = h.trace.findIndex((row) => row[2] === "discard_patch");
  assert.ok(chooseAt >= 0 && discardAt > chooseAt, "확인이 폐기보다 먼저 선다");
  assert.deepEqual(h.actions(), ["discard_patch"]);
  assert.ok(h.names().includes("go"));
});

test("편집기 음성 — stay 는 아무것도 버리지 않고 나가지도 않는다(discard 취소)", async () => {
  const h = editorHarness({ snapshot: DIRTY_JOB, choose: "stay" });
  await h.ready();
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), [], "머무르기는 백엔드 변이 0");
  assert.equal(h.names().includes("go"), false);
  assert.equal(h.names().includes("refresh"), false, "재적재도 시작하지 않는다");
});

test("편집기 음성 — 3택을 닫아 버려도(Escape=null) 머무른다", async () => {
  const h = editorHarness({ snapshot: DIRTY_JOB, choose: null });
  await h.ready();
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), []);
  assert.equal(h.names().includes("go"), false);
});

test("편집기 음성 — save 가 막히면(block_reason) 나가지 않는다(save 실패)", async () => {
  const h = editorHarness({
    snapshot: DIRTY_JOB, choose: "save",
    dispatch: (_s, action) => (action === "save"
      ? { ok: false, block_reason: "이름이 비었습니다", blocked_field: "name" } : {}),
  });
  await h.ready();
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), ["save"]);
  assert.equal(h.names().includes("go"), false, "저장이 막혔으면 문맥을 보존한 채 머문다");
  assert.equal(h.names().includes("refreshList"), false, "실패한 저장은 목록을 건드리지 않는다");
});

test("편집기 음성 — 덮어쓰기 확인을 취소하면 나가지 않는다(save 취소)", async () => {
  const h = editorHarness({
    snapshot: DIRTY_JOB, choose: "save", confirm: false,
    dispatch: (_s, action) => (action === "save"
      ? { ok: false, needs_overwrite: true, overwrite_text: "같은 이름이 있습니다" } : {}),
  });
  await h.ready();
  await h.controller.leaveTo("job");
  assert.equal(h.names().includes("go"), false);
  assert.deepEqual(h.actions(), ["save"], "취소는 둘째 save 를 태우지 않는다");
});

test("편집기 음성 — dirty 질의가 실패하면 dirty 로 보고 묻는다(모르면 묻는다)", async () => {
  const h = editorHarness({ snapshot: CLEAN_JOB, unsavedQueryFails: true, choose: "stay" });
  await h.ready();
  await h.controller.leaveTo("job");
  assert.ok(h.names().includes("invoke"), "스냅샷이 clean 이어도 지금 다시 묻는다");
  assert.ok(h.names().includes("modal.choose"), "질의 실패를 「잃을 것 없음」으로 강등하지 않는다");
  assert.equal(h.names().includes("go"), false);
});

test("편집기 양성 — 정말 clean 이면 묻지 않고 곧장 착지한다(강등의 반대 극)", async () => {
  const h = editorHarness({ snapshot: CLEAN_JOB, unsaved: false });
  await h.ready();
  await h.controller.leaveTo("job");
  assert.equal(h.names().includes("modal.choose"), false);
  assert.deepEqual(h.names().slice(-3), ["refresh", "go", "restoreEntryFocus"]);
});

test("편집기 음성 — 초안은 확인을 거절하면 new_session 이 나가지 않는다", async () => {
  const h = editorHarness({ snapshot: DRAFT, confirmDiscard: false });
  await h.ready();
  await h.controller.leaveTo("job");
  assert.ok(h.names().includes("entry.confirmDiscard"));
  assert.deepEqual(h.actions(), [], "확인 전 폐기 0");
  assert.equal(h.names().includes("go"), false);
});

test("편집기 양성 — 초안 확인을 승인해야 new_session 이 나간다", async () => {
  const h = editorHarness({ snapshot: DRAFT, confirmDiscard: true });
  await h.ready();
  await h.controller.leaveTo("job");
  const confirmAt = h.names().indexOf("entry.confirmDiscard");
  const sessionAt = h.trace.findIndex((row) => row[2] === "new_session");
  assert.ok(confirmAt >= 0 && sessionAt > confirmAt);
  assert.ok(h.names().includes("go"));
});

test("편집기 음성 — 재적재 실패는 loud 로 재진술하고 편집기에 머문다(refresh 실패)", async () => {
  const h = editorHarness({ snapshot: CLEAN_JOB, refreshFails: true });
  await h.ready();
  await h.controller.leaveTo("job");
  assert.ok(h.names().includes("refresh"));
  assert.equal(h.names().includes("go"), false, "재적재 실패 뒤 전환 0");
  assert.equal(h.names().includes("restoreEntryFocus"), false, "착지하지 않았으니 초점도 안 옮긴다");
  assert.ok(h.notices.some((message) => message.includes("머무릅니다")));
});

test("편집기 — 이탈은 대기 중 편집을 먼저 정산한다(가드가 옛 상태를 읽지 않는다)", async () => {
  const h = editorHarness({ snapshot: CLEAN_JOB, unsaved: false });
  await h.ready();
  let release;
  const landed = [];
  Intent.chained("editor:mutate", () => new Promise((resolve) => {
    release = () => { landed.push("landed"); resolve(); };
  }));
  const leaving = h.controller.leaveTo("job");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(h.names().includes("invoke"), false, "정산 전에는 가드 질의도 나가지 않는다");
  release();
  await leaving;
  assert.deepEqual(landed, ["landed"]);
  assert.ok(h.names().includes("go"));
});

/* ================= 작업대 하니스 ================= */

const WB_OPEN = {
  open: true, job_name: "작업A", revision: {}, rows: [], target_font: "gulimche",
  card: {}, dirty: { count: 0 },
};

function workbenchHarness(options = {}) {
  const trace = [];
  const notices = [];
  let snapshot = options.snapshot ?? WB_OPEN;
  const model = { getSnapshot: () => snapshot, subscribe: () => () => {} };
  const client = {
    async dispatch(screen, action, payload) {
      trace.push(["dispatch", screen, action, payload]);
      if (options.dispatch) return { ok: true, value: await options.dispatch(screen, action, payload) };
      return { ok: true, value: {} };
    },
    async invoke() { return { ok: true, value: {} }; },
  };
  const controller = createWorkbenchController({
    doc: { getElementById: () => null },
    runtime: {
      model: () => model, loadInitial: async () => snapshot,
      refresh: async () => snapshot,
      /* no-push 동사의 반환 스냅샷 착지 — 이 파일은 이탈 거래만 재므로 구독 통지가 없다.
         값만 갈아 두면 뒤이은 `snapshot()` 판독이 새 판을 본다(실 runtime 은 store 에 넣는다). */
      land: (_screen, value) => { snapshot = value; },
    },
    client,
    modal: {
      confirm: async (spec) => { trace.push(["modal.confirm", spec]); return options.confirm ?? false; },
      choose: async (spec) => { trace.push(["modal.choose", spec]); return options.choose ?? null; },
    },
    chain: Intent,
    navigation: { go: (target, opts) => { trace.push(["go", target, opts]); } },
    notify: (message) => notices.push(String(message)),
  });
  return {
    controller, trace, notices,
    names: () => trace.map((row) => row[0]),
    actions: () => trace.filter((row) => row[0] === "dispatch").map((row) => row[2]),
    setSnapshot(next) { snapshot = next; },
  };
}

/* ---------------- 작업대 §4.2 ---------------- */

test("작업대 양성 — 가드가 서지 않으면 확인 없이 close → go", async () => {
  const h = workbenchHarness({ dispatch: (_s, a) => (a === "leave_guard" ? { armed: false } : {}) });
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), ["leave_guard", "close"]);
  assert.deepEqual(h.trace.find((row) => row[0] === "go").slice(1), ["job", { force: true }]);
  assert.equal(h.names().includes("modal.confirm"), false);
});

test("작업대 음성 — armed·clean 의 확인을 취소하면 close 도 이동도 없다", async () => {
  const h = workbenchHarness({
    dispatch: (_s, a) => (a === "leave_guard" ? { armed: true, lines: ["복사 안 한 항목 3건"] } : {}),
    confirm: false,
  });
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), ["leave_guard"]);
  assert.equal(h.names().includes("go"), false);
});

test("작업대 음성 — dirty 3택의 stay 는 붙잡는다", async () => {
  const h = workbenchHarness({
    snapshot: { ...WB_OPEN, dirty: { count: 2 } },
    dispatch: (_s, a) => (a === "leave_guard" ? { armed: true, lines: ["미저장 2건"] } : {}),
    choose: "stay",
  });
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), ["leave_guard"]);
  assert.equal(h.names().includes("go"), false);
});

test("작업대 음성 — save 를 골랐는데 저장 확인이 취소되면 가드를 다시 읽고 머문다(save 취소)", async () => {
  const h = workbenchHarness({
    snapshot: { ...WB_OPEN, dirty: { count: 2 } },
    dispatch: (_s, action) => {
      if (action === "leave_guard") return { armed: true, lines: ["미저장 2건"] };
      if (action === "save_rules") return { needs_confirm: true, confirm_text: "기본 규칙을 덮어씁니다" };
      return {};
    },
    choose: "save", confirm: false,
  });
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), ["leave_guard", "save_rules", "leave_guard"],
    "저장이 성사되지 않았으면 가드를 **다시** 읽는다 — 첫 판정으로 나가지 않는다");
  assert.equal(h.names().includes("go"), false);
});

test("작업대 양성 — save 가 성사되고 가드가 풀리면 close 뒤 나간다", async () => {
  /* 첫 가드는 armed 여야 3택이 뜬다 — 저장 뒤 두 번째 가드에서 풀린다. */
  let first = true;
  const h = workbenchHarness({
    snapshot: { ...WB_OPEN, dirty: { count: 2 } },
    dispatch: (_s, action) => {
      if (action === "leave_guard") {
        const value = first ? { armed: true, lines: ["미저장 2건"] } : { armed: false };
        first = false;
        return value;
      }
      return { ok: true };
    },
    choose: "save",
  });
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), ["leave_guard", "save_rules", "leave_guard", "close"]);
  assert.deepEqual(h.trace.find((row) => row[0] === "go").slice(1), ["job", { force: true }]);
});

test("작업대 양성 — discard 는 확인 뒤 close 로 끝난다(새 refresh 의미를 발명하지 않는다)", async () => {
  const h = workbenchHarness({
    snapshot: { ...WB_OPEN, dirty: { count: 1 } },
    dispatch: (_s, a) => (a === "leave_guard" ? { armed: true, lines: ["미저장 1건"] } : {}),
    choose: "discard",
  });
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), ["leave_guard", "close"]);
  assert.deepEqual(h.trace.find((row) => row[0] === "go").slice(1), ["job", { force: true }],
    "현행 작업대에는 target refresh 가 없다 — 이탈은 force 이동 하나다");
});

test("작업대 — 이탈은 대기 중 발신을 먼저 정산한다", async () => {
  const h = workbenchHarness({ dispatch: (_s, a) => (a === "leave_guard" ? { armed: false } : {}) });
  let release;
  Intent.chained("workbench:session", () => new Promise((resolve) => { release = resolve; }));
  const leaving = h.controller.leaveTo("job");
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(h.actions(), []);
  release();
  await leaving;
  assert.deepEqual(h.actions(), ["leave_guard", "close"]);
});

/* ================= 두 화면이 같은 규율 위에 선다 ================= */

test("두 화면 모두 — 「안 나간다」 갈림길에서 이동 발신이 정확히 0 이다", async () => {
  const editorStay = editorHarness({ snapshot: DIRTY_JOB, choose: "stay" });
  await editorStay.ready();
  await editorStay.controller.leaveTo("job");

  const workbenchStay = workbenchHarness({
    snapshot: { ...WB_OPEN, dirty: { count: 2 } },
    dispatch: (_s, a) => (a === "leave_guard" ? { armed: true, lines: ["x"] } : {}),
    choose: "stay",
  });
  await workbenchStay.controller.leaveTo("job");

  for (const [label, harness] of [["편집기", editorStay], ["작업대", workbenchStay]]) {
    assert.equal(harness.names().filter((name) => name === "go").length, 0,
      `${label}: 머무르기가 화면을 뜨지 않는다`);
  }
});
