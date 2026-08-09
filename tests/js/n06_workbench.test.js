/* Workbench behavior: settle-before-leave, guarded navigation, and late-bound ports. */
import test from "node:test";
import assert from "node:assert/strict";

import { createWorkbenchController } from "../../frontend/src/screens/workbench.ts";
import { Intent } from "../../frontend/js/intent.js";

const WB_CHAIN = "workbench:session";   // 화면 내부 상수와 같은 값 — 정산 계약의 키
const tick = () => new Promise((resolve) => setImmediate(resolve));

/** 공개 표면 — 셸이 부르는 둘 + React 화면·행동이 쓰는 나머지. */
const SURFACE = [
  "init", "leaveTo", "aimAt", "model", "draftModel",
  "type", "focus", "compose", "commit", "commitValue", "bindColumn", "saveRules", "copyCard",
  "step", "setCurrent", "setView", "setTargetFont", "toggleAdvance", "setFullwidth",
  "setConfirmed", "setMapType", "setMapFmt", "revertMap", "guarded", "doc", "notify",
];

/* dirty 경로용 최소 open 스냅샷 — 이탈 3택이 읽는 seam 을 실측하기 위한 값. */
const OPEN_DIRTY = {
  open: true, job_name: "작업A", mode_label: "TXT", revision: {},
  dirty: { count: 2 }, target_font: "gulimche", can_save: true, save_block: "",
  view: "card", notice: null, rows: [], source_fields: [], type_options: [], fmt_options: {},
  total: 1, copied_count: 0,
  card: {
    segments: [], review_state: "todo", lint: {}, position: 0, index_map: [],
    queue_degenerate: true, can_prev: false, can_next: false, advance_after: false,
    has_current: true, copy_block: "", last_copy: null, source_row: 1,
  },
};

function harness(cfg) {
  const opts = cfg || {};
  const log = [];
  const notices = [];
  const navigations = [];
  const listeners = new Set();
  const counts = { subscribe: 0 };
  let snapshot = opts.snapshot ?? null;

  const model = {
    getSnapshot: () => snapshot,
    subscribe(listener) {
      counts.subscribe += 1;
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
  const client = {
    async dispatch(screen, action, payload) {
      log.push(["dispatch", screen, action, payload]);
      const value = opts.onDispatch ? await opts.onDispatch(screen, action, payload) : {};
      return { ok: true, value };
    },
    async invoke(method, ...args) {
      log.push(["invoke", method, ...args]);
      const value = opts.onInvoke ? await opts.onInvoke(method, ...args) : {};
      return { ok: true, value };
    },
  };
  const modal = {
    async confirm(spec) { log.push(["modal.confirm", spec]); return opts.confirm?.(spec) ?? false; },
    async choose(spec) { log.push(["modal.choose", spec]); return opts.choose?.(spec) ?? null; },
  };
  const navigation = { go: (...args) => navigations.push(args) };
  const controller = createWorkbenchController({
    doc: { getElementById: () => null },
    runtime: {
      model: () => model, loadInitial: async () => snapshot,
      refresh: async () => snapshot,
      /* no-push 동사의 반환 스냅샷 착지 — 실 runtime 은 store 에 넣는다. */
      land: (_screen, value) => { snapshot = value; for (const listener of [...listeners]) listener(); },
    },
    client, modal, chain: Intent, navigation,
    notify: (message) => notices.push(String(message)),
  });
  return {
    controller, client, modal, navigation, navigations, log, notices, counts,
    actions: () => log.filter((row) => row[0] === "dispatch").map((row) => row[2]),
    push(next) { snapshot = next; for (const listener of [...listeners]) listener(); },
  };
}

/* ================= 1. 공개 표면 ================= */

test("공개 표면 — controller 키가 정확하고 leaveTo 는 셸 이탈 API 다", () => {
  assert.equal(typeof createWorkbenchController, "function");
  const { controller } = harness();
  assert.deepEqual(Object.keys(controller), SURFACE);
  for (const key of ["init", "leaveTo", "aimAt", "saveRules", "copyCard"]) {
    assert.equal(typeof controller[key], "function", key);
  }
  /* 셸 facade 는 이 둘만 뽑아 간다(`bootstrap.js` 의 `WorkbenchScreen`). 표면이 여기서
     좁아지면 셸이 실엔진에서야 죽으므로 두 이름을 못박는다. */
  assert.equal(typeof controller.init, "function");
  assert.equal(typeof controller.leaveTo, "function");
});

/* ================= 2. init 멱등(구성 시 한 번 구독) ================= */

test("init 재호출 — 구독 추가 등록 0, 화면 model 은 runtime 이 준 그 객체", async () => {
  const h = harness({ snapshot: OPEN_DIRTY });
  assert.equal(h.counts.subscribe, 1, "구독은 **구성 시** 한 번(init 이 아니다)");
  h.controller.init();
  h.controller.init();
  h.controller.init();
  assert.equal(h.counts.subscribe, 1, "재호출 delta 0");
  assert.deepEqual(h.actions(), [], "이 화면은 initial 당김이 없다 — init 은 발신 0");

  /* push 는 같은 model 을 지난다 — React 화면과 controller 가 두 세계로 갈리지 않는다. */
  const next = { ...OPEN_DIRTY, copied_count: 3 };
  h.push(next);
  assert.equal(h.controller.model.getSnapshot(), next);
  assert.equal(h.controller.draftModel.getSnapshot().session, "wb:작업A",
    "스냅샷 흡수가 draft 세션까지 세운다");
});

/* ================= 3. 이탈 단일 관문 — 정산 → 가드 → close → navigation.go ================= */

test("leaveTo — 대기 중 발신을 정산한 **뒤에** leave_guard 를 읽는다(8R P1)", async () => {
  const h = harness({
    snapshot: OPEN_DIRTY,
    onDispatch: (_s, action) => (action === "leave_guard" ? { armed: false } : {}),
  });
  let release;
  const landed = [];
  Intent.chained(WB_CHAIN, () => new Promise((resolve) => {
    release = () => { landed.push("landed"); resolve(); };
  }));
  const leaving = h.controller.leaveTo("job");
  await tick();
  assert.deepEqual(h.actions(), [], "정산 전에는 발신 0 — 가드가 옛 상태를 읽지 않는다");
  release();
  await leaving;
  assert.deepEqual(landed, ["landed"]);
  assert.deepEqual(h.actions(), ["leave_guard", "close"], "가드 → close 순서");
  assert.deepEqual(h.navigations, [["job", { force: true }]], "이탈은 force 이동(시그니처 불변)");
});

test("leaveTo — 가드가 서면(armed·무변경) 확인을 거치고, 취소는 나가지 않는다", async () => {
  let confirmResult = false;
  const h = harness({
    snapshot: { ...OPEN_DIRTY, dirty: { count: 0 } },
    onDispatch: (_s, action) => (action === "leave_guard" ? { armed: true, lines: ["줄1", "줄2"] } : {}),
    confirm: () => confirmResult,
  });
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), ["leave_guard"], "취소 뒤 close 발신 0");
  assert.deepEqual(h.navigations, [], "취소 뒤 이동 0");
  const spec = h.log.find((row) => row[0] === "modal.confirm")[1];
  assert.equal(spec.body, "줄1\n줄2", "가드 문안은 Python 이 낸 lines 그대로");
  assert.equal(spec.confirmLabel, "나가기");
  assert.equal(spec.cancelLabel, "계속 검토");

  confirmResult = true;
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), ["leave_guard", "leave_guard", "close"], "확인하면 close");
  assert.deepEqual(h.navigations, [["job", { force: true }]]);
});

test("leaveTo — dirty 스냅샷이 있으면 3택으로 묻는다: stay 는 붙잡고 discard 는 나간다", async () => {
  let answer = "stay";
  const h = harness({
    snapshot: OPEN_DIRTY,                     // dirty.count = 2 — 스냅샷→가드 seam 실측
    onDispatch: (_s, action) => (action === "leave_guard" ? { armed: true, lines: ["미저장 2건"] } : {}),
    choose: () => answer,
  });
  await h.controller.leaveTo("job");
  const chosen = h.log.filter((row) => row[0] === "modal.choose");
  assert.equal(chosen.length, 1, "dirty 면 confirm 이 아니라 choose 로 묻는다");
  assert.deepEqual(chosen[0][1].choices.map((choice) => choice.value), ["save", "discard", "stay"]);
  assert.deepEqual(h.actions(), ["leave_guard"], "stay 는 close 발신 0");
  assert.deepEqual(h.navigations, [], "stay 는 이동 0");

  answer = "discard";
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), ["leave_guard", "leave_guard", "close"], "discard 는 close 뒤 이동");
  assert.deepEqual(h.navigations, [["job", { force: true }]]);
});

test("leaveTo — save 를 골랐는데 저장 확인이 취소되면 여전히 dirty 라 머문다(음성)", async () => {
  const h = harness({
    snapshot: OPEN_DIRTY,
    onDispatch: (_s, action) => {
      if (action === "leave_guard") return { armed: true, lines: ["미저장 2건"] };
      if (action === "save_rules") return { needs_confirm: true, confirm_text: "덮어씁니다" };
      return {};
    },
    choose: () => "save",
    confirm: () => false,                     // 저장 확인 창에서 취소
  });
  await h.controller.leaveTo("job");
  assert.deepEqual(h.actions(), ["leave_guard", "save_rules", "leave_guard"],
    "저장이 취소되면 close 로 넘어가지 않고 가드를 다시 읽는다");
  assert.deepEqual(h.navigations, [], "저장 취소 뒤 이동 0 — 확인 없는 폐기 금지");
});

/* ================= 4. 통로 객체째 · 항행 late-bound ================= */

test("포트 교체 — client.dispatch 프로퍼티 교체·navigation.go 재배선이 다음 이탈에 보인다", async () => {
  const h = harness({
    snapshot: { ...OPEN_DIRTY, dirty: { count: 0 } },
    onDispatch: (_s, action) => (action === "leave_guard" ? { armed: false } : {}),
  });
  const swapped = [];
  h.client.dispatch = async (_screen, action) => {
    swapped.push(action);
    return { ok: true, value: action === "leave_guard" ? { armed: false } : {} };
  };
  h.navigation.go = (...args) => swapped.push(["go", ...args]);   // 구성 뒤 재배선
  await h.controller.leaveTo("job");
  assert.deepEqual(swapped, ["leave_guard", "close", ["go", "job", { force: true }]],
    "갈아끼운 dispatch·go 가 그 순서대로 불린다(값 캡처 0)");
});

test("손상된 HostResult 는 조용히 통과하지 않는다 — 이탈이 loud 로 멈춘다(음성)", async () => {
  const h = harness({ snapshot: OPEN_DIRTY });
  h.client.dispatch = async () => ({ value: {} });   // ok 필드 없음
  await assert.rejects(() => h.controller.leaveTo("job"), /호스트 결과가 손상/);
  assert.deepEqual(h.navigations, [], "판독 실패 뒤 이동 0");
});
