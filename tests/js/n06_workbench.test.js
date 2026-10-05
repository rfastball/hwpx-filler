/* Workbench behavior: settle-before-leave, guarded navigation, exit doors, and late-bound ports. */
import test from "node:test";
import assert from "node:assert/strict";

import { createWorkbenchController } from "../../frontend/src/screens/workbench.ts";
import { Intent } from "../../frontend/js/intent.js";
import { workbenchServerValues } from "../../frontend/src/screens/workbench_state.ts";

const WB_CHAIN = "workbench:session";   // 화면 내부 상수와 같은 값 — 정산 계약의 키
const tick = () => new Promise((resolve) => setImmediate(resolve));

/** 공개 표면 — 셸이 부르는 둘 + React 화면·행동이 쓰는 나머지. 필드 연결 동사·「기본 규칙으로
    저장」·결과 → 규칙 겨눔은 표와 함께 걷혔다(#1148) — 다시 생기면 여기서 붉어진다. */
const SURFACE = [
  "init", "leaveTo", "editBinding", "editTemplate", "model", "draftModel",
  "copyCard", "step", "setCurrent", "setView", "setTargetFont", "toggleAdvance", "setFullwidth",
  "guarded", "doc", "notify",
];

/* 열린 세션의 최소 스냅샷 — 이탈·나가는 문이 읽는 seam 을 실측하기 위한 값. */
const OPEN = {
  open: true, job_name: "작업A", mode_label: "TXT", revision: {},
  target_font: "gulimche", template_path: "C:/tpl/작업A.txt",
  view: "card", notice: null, total: 1, copied_count: 0,
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
  let screen = "workbench";

  const model = {
    getSnapshot: () => snapshot,
    subscribe(listener) {
      counts.subscribe += 1;
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
  const client = {
    async dispatch(screenName, action, payload) {
      log.push(["dispatch", screenName, action, payload]);
      const value = opts.onDispatch ? await opts.onDispatch(screenName, action, payload) : {};
      /* 실 백엔드의 close 는 세션을 비우는 푸시를 낸다 — 닫기 뒤 스냅샷은 빈 골격이다. */
      if (action === "close") {
        snapshot = { open: false };
        for (const listener of [...listeners]) listener();
      }
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
  };
  const navigation = {
    go: (...args) => { navigations.push(args); screen = args[0]; },
    currentScreen: () => screen,
  };
  /* 나가는 문 둘 — 실 포트처럼 성공하면 자기 화면으로 착지한다(`land`·`go("authoring")`). */
  const ports = {
    editorEntry: { current: () => ({
      openGuarded: async (name, context) => {
        log.push(["editorEntry.openGuarded", name, context]);
        if (opts.editorFails) return false;
        screen = "editor";
        return true;
      },
    }) },
    authoring: { current: () => ({
      open: async (path, returnTo) => {
        log.push(["authoring.open", path, returnTo]);
        if (opts.authoringThrows) throw new Error("열 수 없는 템플릿입니다");
        screen = "authoring";
      },
    }) },
  };
  const controller = createWorkbenchController({
    doc: { getElementById: () => null },
    runtime: {
      model: () => model, loadInitial: async () => snapshot,
      refresh: async () => snapshot,
      land: (_screen, value) => { snapshot = value; for (const listener of [...listeners]) listener(); },
    },
    client, modal, chain: Intent, navigation, ports,
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
  for (const key of ["init", "leaveTo", "editBinding", "editTemplate", "copyCard"]) {
    assert.equal(typeof controller[key], "function", key);
  }
  /* 셸 facade 는 이 둘만 뽑아 간다(`bootstrap.js` 의 `WorkbenchScreen`). 표면이 여기서
     좁아지면 셸이 실엔진에서야 죽으므로 두 이름을 못박는다. */
  assert.equal(typeof controller.init, "function");
  assert.equal(typeof controller.leaveTo, "function");
});

/* ================= 2. init 멱등(구성 시 한 번 구독) ================= */

test("init 재호출 — 구독 추가 등록 0, 화면 model 은 runtime 이 준 그 객체", async () => {
  const h = harness({ snapshot: OPEN });
  assert.equal(h.counts.subscribe, 1, "구독은 **구성 시** 한 번(init 이 아니다)");
  h.controller.init();
  h.controller.init();
  h.controller.init();
  assert.equal(h.counts.subscribe, 1, "재호출 delta 0");
  assert.deepEqual(h.actions(), [], "이 화면은 initial 당김이 없다 — init 은 발신 0");

  /* push 는 같은 model 을 지난다 — React 화면과 controller 가 두 세계로 갈리지 않는다. */
  const next = { ...OPEN, copied_count: 3 };
  h.push(next);
  assert.equal(h.controller.model.getSnapshot(), next);
  assert.equal(h.controller.draftModel.getSnapshot().session, "wb:작업A",
    "스냅샷 흡수가 draft 세션까지 세운다");
});

/* ================= 3. 이탈 단일 관문 — 정산 → 가드 → close → navigation.go ================= */

test("leaveTo — 대기 중 발신을 정산한 **뒤에** leave_guard 를 읽는다(8R P1)", async () => {
  const h = harness({
    snapshot: OPEN,
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
    snapshot: OPEN,
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

test("포트 교체 — client.dispatch 프로퍼티 교체·navigation.go 재배선이 다음 이탈에 보인다", async () => {
  const h = harness({
    snapshot: OPEN,
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
  const h = harness({ snapshot: OPEN });
  h.client.dispatch = async () => ({ value: {} });   // ok 필드 없음
  await assert.rejects(() => h.controller.leaveTo("job"), /호스트 결과가 손상/);
  assert.deepEqual(h.navigations, [], "판독 실패 뒤 이동 0");
});

/* ================= 5. 나가는 문 — 「연결 편집」·「템플릿 편집」(#1148) ================= */

test("연결 편집 — 가드 → close **뒤에** 편집기를 workbench_result 로 연다(복귀는 문서 만들기)", async () => {
  const h = harness({
    snapshot: OPEN,
    onDispatch: (_s, action) => (action === "leave_guard" ? { armed: false } : {}),
  });
  await h.controller.editBinding();
  assert.deepEqual(h.actions(), ["leave_guard", "close"], "같은 이탈 관문을 지난다");
  const opened = h.log.filter((row) => row[0] === "editorEntry.openGuarded");
  assert.deepEqual(opened, [["editorEntry.openGuarded", "작업A", {
    entry_reason: "workbench_result", return_context: { surface: "data" },
  }]], "작업 이름은 닫기 **전** 스냅샷에서 읽는다(닫기 푸시가 스냅샷을 비운다)");
  const order = h.log.map((row) => (row[0] === "dispatch" ? row[2] : row[0]));
  assert.ok(order.indexOf("close") < order.indexOf("editorEntry.openGuarded"), "세션을 닫은 뒤에 연다");
  assert.deepEqual(h.navigations, [], "문이 열리면 셸 이동을 따로 하지 않는다(편집기가 착지한다)");
});

test("템플릿 편집 — 스냅샷이 낸 경로를 저작 작업대로 열고, 돌아올 곳은 문서 만들기", async () => {
  const h = harness({
    snapshot: OPEN,
    onDispatch: (_s, action) => (action === "leave_guard" ? { armed: false } : {}),
  });
  await h.controller.editTemplate();
  assert.deepEqual(h.actions(), ["leave_guard", "close"]);
  assert.deepEqual(h.log.filter((row) => row[0] === "authoring.open"),
    [["authoring.open", "C:/tpl/작업A.txt", "job"]]);
  assert.deepEqual(h.navigations, []);
});

test("나가는 문 — 가드가 서면 확인을 거치고, 취소하면 닫지도 열지도 않는다(음성)", async () => {
  const h = harness({
    snapshot: OPEN,
    onDispatch: (_s, action) => (action === "leave_guard"
      ? { armed: true, lines: ["복사 진행 1/3건 — 나가면 이 진행은 사라집니다."] } : {}),
    confirm: () => false,
  });
  await h.controller.editBinding();
  await h.controller.editTemplate();
  assert.deepEqual(h.actions(), ["leave_guard", "leave_guard"], "취소 뒤 close 발신 0");
  assert.equal(h.log.some((row) => row[0] === "editorEntry.openGuarded" || row[0] === "authoring.open"), false);
  const spec = h.log.find((row) => row[0] === "modal.confirm")[1];
  assert.equal(spec.body, "복사 진행 1/3건 — 나가면 이 진행은 사라집니다.", "가드 문안은 Python 이 낸 lines 그대로");
});

test("나가는 문 — 문이 열리지 않으면 빈 작업대에 남기지 않고 문서 만들기로 보낸다", async () => {
  const failed = harness({
    snapshot: OPEN, editorFails: true,
    onDispatch: (_s, action) => (action === "leave_guard" ? { armed: false } : {}),
  });
  await failed.controller.editBinding();
  assert.deepEqual(failed.navigations, [["job", { force: true }]], "거절(false) 뒤 복귀");

  const thrown = harness({
    snapshot: OPEN, authoringThrows: true,
    onDispatch: (_s, action) => (action === "leave_guard" ? { armed: false } : {}),
  });
  await assert.rejects(() => thrown.controller.editTemplate(), /열 수 없는 템플릿/,
    "여는 쪽의 실패는 삼키지 않는다(guarded 가 알린다)");
  assert.deepEqual(thrown.navigations, [["job", { force: true }]], "예외여도 복귀");
});

/* ================= 6. 대상 글꼴 — 남은 초안 칸 하나 ================= */

test("대상 글꼴 — 고른 값이 곧바로 보이고 set_target_font 한 발이 체인에 선다", async () => {
  const h = harness({ snapshot: OPEN });
  const pending = h.controller.setTargetFont("malgun");
  const draft = h.controller.draftModel.getSnapshot();
  assert.equal(draft.fields.targetFont.draftValue, "malgun", "응답 전에 고른 값을 그린다");
  await pending;
  assert.deepEqual(h.log.filter((row) => row[0] === "dispatch").map((row) => [row[2], row[3]]),
    [["set_target_font", { font: "malgun" }]]);
  assert.deepEqual(h.notices, []);
});

test("서버 값 — 작업대 초안의 서버 축은 대상 글꼴 하나다(연결 표 축 없음)", () => {
  assert.deepEqual(workbenchServerValues({ target_font: "dotumche", rows: [{ name: "수신" }] }),
    { targetFont: "dotumche" });
});
