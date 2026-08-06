/* TXT 검토·복사 작업대의 화면 계약 — N-06 lane B 가 `frontend/js/screens/workbench.js` 에
 * 세운 다섯 경계를 R4-02 에서 React 후계 `frontend/src/screens/workbench.ts` 로 **제자리
 * 번역**했다.
 *
 * 지키는 것 다섯은 그대로다:
 *  ① 공개 표면 — 셸(상태기계 IMMERSIVE_SURFACES 판정 → adapter 위임 집행, R3-02)이 몰입
 *     이탈에 쓰는 `leaveTo` 의 시그니처·의미가 불변인가. 셸이 보는 facade 는 `{init, leaveTo}`
 *     둘로 좁아졌다 — legacy 의 `render` 는 명령형 렌더러의 손잡이였고 React 에선 구독이
 *     그 일을 한다. 그 축소가 이 슬라이스의 실물이다.
 *  ② init 멱등 — initial 당김이 없는 화면이라 「재호출해도 구독이 안 늘어난다」가 계약이다.
 *     legacy 는 `wired` 가드로, React 는 **구성 시 한 번 구독**으로 같은 성질을 세운다.
 *  ③ 이탈 단일 관문 — leaveTo 는 **정산(chain.settle) → leave_guard → (확인) → close →
 *     navigation.go** 순서를 지킨다. 가드가 서면 확인 없이는 나가지 않고, dirty 스냅샷이
 *     있으면 3택(choose)으로 묻는다.
 *  ④ 통로는 객체째·항행은 late-bound — 구성 뒤 프로퍼티 교체가 다음 호출에 보인다.
 *     legacy 는 `Bridge.call`, 후계는 `client.dispatch` 다.
 *  ⑤ 음성 — IIFE 0, 제품 전역 27종 조회 0, 화면 간 import 0, 판정 E(작업대는 편집기 진입이
 *     없다 — EditorEntry 부재) 유지.
 *
 * 대역이 가벼워졌다: legacy 는 `modal → popover` 그래프가 평가 시점에 document 를 만져서
 * 전역 DOM 대역을 깔고 동적 import 로 열어야 했다. React controller 의 의존은 전부 주입
 * 인자라 그 대역이 통째로 사라졌다 — 남은 `doc` 은 겨눔(`aimAt`)이 쓰는 한 칸뿐이다.
 *
 * `Intent` 는 대역이 아니라 **실물**을 쓴다. 정산 계약(`settle` 이 큐에 든 발신을 기다린다)이
 * 이 화면 계약의 일부이고, 대역으로 갈면 「정산했다」가 대역의 성질이 돼 버린다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createWorkbenchController } from "../../frontend/src/screens/workbench.ts";
import { Intent } from "../../frontend/js/intent.js";

const SRC_URL = new URL("../../frontend/src/screens/workbench.ts", import.meta.url);
const src = readFileSync(SRC_URL, "utf8");

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

/* ================= 5. 음성 — 구조 계약 ================= */

const PRODUCT_GLOBALS = [
  "Bridge", "__push", "Nav", "AppCloseGuard",
  "JobScreen", "LibraryScreen", "EditorScreen", "WorkbenchScreen",
  "Copy", "escHtml", "Guard", "SegView", "Popover", "Preserve", "Intent",
  "UndoToast", "Modal", "SurfaceSheet", "GroupList", "Theme", "Personalization",
  "SheetPicker", "PathTrack", "DataPicker", "Relink", "DataZone", "EditorEntry",
];

test("음성 — IIFE 0 · 제품 전역 27종 조회 0(주석 포함) · 자기 전역 생산 0", () => {
  assert.equal(src.includes("(function () {"), false, "top-level IIFE 금지");
  assert.equal(/^\}\)\(\);/m.test(src), false, "IIFE 꼬리 금지");
  assert.equal(PRODUCT_GLOBALS.length, 27, "제품 전역 목록은 27종");
  for (const name of PRODUCT_GLOBALS) {
    assert.equal(new RegExp(`(window|globalThis)\\.${name}\\b`).test(src), false,
      `window.${name} 조회·대입 0 (주석 포함 — 게이트 정규식이 주석도 본다)`);
  }
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.equal(/(window|globalThis)\.[A-Za-z_$][\w$]*\s*=[^=]/.test(code), false, "자기 전역 생산 금지");
  /* loud 실패 통로가 `window.alert` 에서 주입 `notify` 로 옮겨졌다 — 이 화면은 전역 window 를
     아예 만지지 않는다. 통로가 사라진 것이 아니라 소유가 합성 루트로 올라간 것이다. */
  assert.equal(/\bwindow\./.test(code), false, "화면이 전역 window 를 만지지 않는다");
  assert.ok(/deps\.notify\(/.test(code), "loud 실패 통로(주입 notify) 보존");
});

test("음성 — export 는 controller 팩토리와 React 화면 producer 둘뿐(named)", () => {
  assert.equal(/export\s+default/.test(src), false, "export default 금지");
  const names = [...src.matchAll(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  assert.deepEqual(names, ["createWorkbenchController", "WorkbenchScreen"]);
  assert.ok(src.includes("export function createWorkbenchController(deps: WorkbenchControllerDeps) {"),
    "주입 deps 는 이름 있는 형 하나로 받는다");
});

test("음성 — import 는 공용 잎·상태 간선뿐, 화면 간·app·bridge import 0, 판정 E 유지", () => {
  const targets = [...src.matchAll(/from "([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual([...new Set(targets)], [
    "react", "../runtime/client.ts", "./runtime.ts", "./segment_view.ts",
    "./workbench_state.ts", "./editor_state.ts",
  ]);
  /* `editor_state.ts` 는 편집기 **화면**이 아니라 두 화면이 공유하는 draft reducer 다
     (`workbench_state.ts` 머리말: 두 벌 쓰면 한쪽만 늙는다). 금지되는 것은 다른 화면의
     producer·controller 를 직접 부르는 간선이다. */
  for (const forbidden of ["./editor.ts", "./job_read.ts", "./library.ts", "./data_picker.ts"]) {
    assert.equal(targets.includes(forbidden), false, `화면 간 import 금지: ${forbidden}`);
  }
  assert.equal(targets.some((target) => /app\.js|bridge\.js/.test(target)), false,
    "셸·브리지 직접 import 금지");
  // 판정 E(계약 §10.15.2) — 작업대는 편집기로 나가는 deep-link 를 갖지 않는다.
  assert.equal(src.includes("EditorEntry"), false);
  assert.equal(src.includes("openJobInEditor"), false);
  assert.equal(src.includes("open_job_in_editor"), false);
});

test("음성 — 커밋 3종의 정산 관문(chain.settle)과 메서드 사전 추출 금지", () => {
  assert.equal((src.match(/await deps\.chain\.settle\(WB_CHAIN\);/g) || []).length, 3,
    "copyCard·saveRules·leaveTo 세 커밋이 전부 정산을 앞세운다");
  /* 팩토리 스코프(들여쓰기 2)에서 통로 메서드를 값으로 뽑으면 프로퍼티 교체가 우회된다.
     헬퍼 **안**의 지역 별칭은 호출마다 다시 읽으므로 계약 위반이 아니고, 실제로 보이는지는
     위 「포트 교체」 가 실행으로 잰다. */
  assert.equal(/^ {2}const\s+\w+\s*=\s*deps\.client\.\w+/m.test(src), false,
    "`const x = deps.client.dispatch` 류 팩토리 스코프 캡처 금지");
});

test("음성 — 상태 변이는 전부 한 체인(WB_CHAIN)을 지난다", () => {
  assert.equal((src.match(/deps\.chain\.chained\(/g) || []).length, 1,
    "체인 진입점은 sendWb 하나 — 축별로 가르면 서로를 추월한다");
  assert.match(src, /return deps\.chain\.chained\(WB_CHAIN,/);
});
