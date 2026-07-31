/* N-06 lane B — TXT 검토·복사 작업대(screens/workbench.js)의 true ESM factory 전환 계약.
 *
 * 지키는 것 다섯:
 *  ① 공개 표면 — `createWorkbenchScreen({ Bridge, Nav })` 가 `{ init, render, leaveTo }` 를
 *     낸다. `leaveTo` 는 앱 셸(IMMERSIVE 목록)이 몰입 이탈에 쓰는 공개 API — 시그니처·의미 불변.
 *  ② init 멱등 — initial 당김이 없는 화면이라 wired 가드만: 재호출 시 listener·onPush
 *     추가 등록 0(계측 stub 로 실측). onPush 에 등록된 렌더러는 공개 render 그 함수다.
 *  ③ 이탈 단일 관문 — leaveTo 는 **정산(Intent.settle) → leave_guard → (확인) → close →
 *     Nav.go** 순서를 지킨다. 가드가 서면 확인 없이는 나가지 않고, dirty 스냅샷이 있으면
 *     3택(choose)으로 묻는다.
 *  ④ Bridge 는 객체째·Nav 는 late-bound 테이블 — 구성 뒤 프로퍼티 교체가 다음 호출에 보인다.
 *  ⑤ 음성 — IIFE 0, 제품 전역 27종 조회 0, export 정확히 1(named), 화면 간 import 0,
 *     판정 E(작업대는 편집기 진입이 없다 — EditorEntry 부재) 유지.
 *
 * 임포트 그래프(modal → popover)는 평가 시점에 document 를 만진다 — 전역 대역을 먼저 깔고
 * 동적 import 로 연다(n05 관례).
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

/* ---------------- 최소 DOM 대역(계측 포함) ---------------- */

class FakeEl {
  constructor(id, stats) {
    this.id = id || "";
    this._stats = stats;
    this.style = {};
    this.dataset = {};
    this.innerHTML = "";
    this.textContent = "";
    this.hidden = false;
    this.isConnected = true;
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this._attrs = {};
    this._listeners = new Map();
    this.classList = { toggle() {}, add() {}, remove() {}, contains: () => false };
  }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return Object.hasOwn(this._attrs, k) ? this._attrs[k] : null; }
  removeAttribute(k) { delete this._attrs[k]; }
  addEventListener(type, fn, opts) {
    this._stats.listeners += 1;
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push({ fn, opts });
  }
  removeEventListener() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  contains() { return false; }
  matches() { return false; }
  focus() {}
  blur() {}
  scrollIntoView() {}
  getBoundingClientRect() { return { top: 0, left: 0, width: 10, height: 10, bottom: 10, right: 10 }; }
}

function makeDom() {
  const alerts = [];
  const stats = { listeners: 0 };
  const els = new Map();
  const byId = (id) => {
    if (!els.has(id)) els.set(id, new FakeEl(id, stats));
    return els.get(id);
  };
  const document = {
    documentElement: new FakeEl("html", stats),
    body: new FakeEl("body", stats),
    activeElement: null,
    getElementById: byId,
    // renderFoot 가 document.querySelector(".wb-adv") 의 style 을 만진다 — 항상 요소를 돌려준다.
    querySelector: (sel) => byId("sel:" + sel),
    querySelectorAll: () => [],
    addEventListener() { stats.listeners += 1; },
    removeEventListener() {},
    createElement: () => new FakeEl("", stats),
  };
  const window = {
    pywebview: { api: {} },
    alert: (m) => alerts.push(String(m)),
    dispatchEvent: () => true,
    addEventListener() { stats.listeners += 1; },
    removeEventListener() {},
    innerWidth: 1200,
    innerHeight: 800,
  };
  return { window, document, alerts, stats, byId };
}

function installDom(dom) {
  globalThis.window = dom.window;
  globalThis.document = dom.document;
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });
  globalThis.CSS = { escape: (s) => String(s).replace(/["\\]/g, "\\$&") };
  return dom;
}

const BASELINE = installDom(makeDom());

function freshDom(t) {
  const dom = installDom(makeDom());
  t.after(() => installDom(BASELINE));
  return dom;
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

/* ---------------- 그래프 열기 ---------------- */

const SRC = new URL("../../frontend/js/screens/workbench.js", import.meta.url);
const src = fs.readFileSync(SRC, "utf8");

const { createWorkbenchScreen } = await import("../../frontend/js/screens/workbench.js");
const { Intent } = await import("../../frontend/js/intent.js");
const { Modal } = await import("../../frontend/js/modal.js");

const WB_CHAIN = "workbench:session";   // 화면 내부 상수와 같은 값 — 정산 계약의 키

/* Modal 은 살아 있는 export 객체 — 같은 객체의 메서드만 갈아끼워 호출을 관측한다(n05 관례). */
function patchModal(t, impls) {
  const saved = { confirm: Modal.confirm, choose: Modal.choose };
  if (impls.confirm) Modal.confirm = impls.confirm;
  if (impls.choose) Modal.choose = impls.choose;
  t.after(() => { Modal.confirm = saved.confirm; Modal.choose = saved.choose; });
}

function makeBridge(opts) {
  const o = opts || {};
  const log = [];
  const counts = { onPush: 0 };
  const bridge = {
    onPush(screen, fn) { counts.onPush += 1; log.push(["onPush", screen, fn]); },
    call: async (...a) => { log.push(["call", ...a]); return o.onCall ? o.onCall(...a) : {}; },
    copyClipboard: async (...a) => { log.push(["copyClipboard", ...a]); return {}; },
  };
  return { bridge, log, counts, actions: () => log.filter((r) => r[0] === "call").map((r) => r[2]) };
}

/* dirty 경로용 최소 open 스냅샷 — render 가 LAST 를 세우는 seam 을 실측하기 위한 값. */
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

/* ================= 1. 공개 표면 ================= */

test("공개 표면 — { init, render, leaveTo } 를 정확히 낸다(leaveTo 는 셸 이탈 API)", (t) => {
  freshDom(t);
  assert.equal(typeof createWorkbenchScreen, "function");
  const wb = createWorkbenchScreen({ Bridge: makeBridge().bridge, Nav: { go() {} } });
  assert.deepEqual(Object.keys(wb).sort(), ["init", "leaveTo", "render"]);
  for (const k of Object.keys(wb)) assert.equal(typeof wb[k], "function", k);
});

/* ================= 2. init 멱등(wired 가드) ================= */

test("init 재호출 — listener·onPush 추가 등록 0, onPush 렌더러는 공개 render 그 함수", async (t) => {
  const dom = freshDom(t);
  const b = makeBridge();
  const wb = createWorkbenchScreen({ Bridge: b.bridge, Nav: { go() {} } });
  wb.init();
  const first = { onPush: b.counts.onPush, listeners: dom.stats.listeners };
  assert.equal(first.onPush, 1);
  assert.ok(first.listeners > 0, "wire 가 실제로 리스너를 달았다");
  wb.init();
  wb.init();
  assert.deepEqual({ onPush: b.counts.onPush, listeners: dom.stats.listeners }, first, "재호출 delta 0");
  const reg = b.log.find((r) => r[0] === "onPush");
  assert.equal(reg[1], "workbench");
  assert.equal(reg[2], wb.render, "등록 렌더러 === 공개 render (push 와 직접 호출이 한 몸)");
  const back = dom.byId("wbBack")._listeners.get("click");
  assert.equal(back.length, 1, "wbBack 클릭 리스너 1개(중복 배선 아님)");
});

/* ================= 3. 이탈 단일 관문 — 정산 → 가드 → close → Nav.go ================= */

test("leaveTo — 대기 중 발신을 정산한 **뒤에** leave_guard 를 읽는다(8R P1)", async (t) => {
  freshDom(t);
  const b = makeBridge({ onCall: (s, a) => (a === "leave_guard" ? { armed: false } : {}) });
  const calls = [];
  const wb = createWorkbenchScreen({ Bridge: b.bridge, Nav: { go: (...a) => calls.push(["Nav.go", ...a]) } });
  wb.init();
  let release;
  const landed = [];
  Intent.chained(WB_CHAIN, () => new Promise((resolve) => {
    release = () => { landed.push("landed"); resolve(); };
  }));
  const leaving = wb.leaveTo("job");
  await tick();
  assert.deepEqual(b.actions(), [], "정산 전에는 발신 0 — 가드가 옛 상태를 읽지 않는다");
  release();
  await leaving;
  assert.deepEqual(landed, ["landed"]);
  assert.deepEqual(b.actions(), ["leave_guard", "close"], "가드 → close 순서");
  assert.deepEqual(calls, [["Nav.go", "job", { force: true }]], "이탈은 force 이동(시그니처 불변)");
});

test("leaveTo — 가드가 서면(armed·무변경) 확인을 거치고, 취소는 나가지 않는다", async (t) => {
  freshDom(t);
  const seen = [];
  let confirmResult = false;
  patchModal(t, { confirm: async (opts) => { seen.push(opts); return confirmResult; } });
  const b = makeBridge({ onCall: (s, a) => (a === "leave_guard" ? { armed: true, lines: ["줄1", "줄2"] } : {}) });
  const calls = [];
  const wb = createWorkbenchScreen({ Bridge: b.bridge, Nav: { go: (...a) => calls.push(a) } });
  wb.init();
  await wb.leaveTo("job");
  assert.deepEqual(b.actions(), ["leave_guard"], "취소 뒤 close 발신 0");
  assert.deepEqual(calls, [], "취소 뒤 이동 0");
  assert.equal(seen[0].body, "줄1\n줄2", "가드 문안은 Python 이 낸 lines 그대로");
  assert.equal(seen[0].confirmLabel, "나가기");
  assert.equal(seen[0].cancelLabel, "계속 검토");

  confirmResult = true;
  await wb.leaveTo("job");
  assert.deepEqual(b.actions(), ["leave_guard", "leave_guard", "close"], "확인하면 close");
  assert.deepEqual(calls, [["job", { force: true }]]);
});

test("leaveTo — dirty 스냅샷이 있으면 3택으로 묻는다: stay 는 붙잡고 discard 는 나간다", async (t) => {
  freshDom(t);
  const chooseSeen = [];
  let answer = "stay";
  patchModal(t, { choose: async (opts) => { chooseSeen.push(opts); return answer; } });
  const b = makeBridge({ onCall: (s, a) => (a === "leave_guard" ? { armed: true, lines: ["미저장 2건"] } : {}) });
  const calls = [];
  const wb = createWorkbenchScreen({ Bridge: b.bridge, Nav: { go: (...a) => calls.push(a) } });
  wb.init();
  wb.render(OPEN_DIRTY);            // LAST.dirty.count = 2 — render→가드 seam 실측
  await wb.leaveTo("job");
  assert.equal(chooseSeen.length, 1, "dirty 면 confirm 이 아니라 choose 로 묻는다");
  assert.deepEqual(chooseSeen[0].choices.map((c) => c.value), ["save", "discard", "stay"]);
  assert.deepEqual(b.actions(), ["leave_guard"], "stay 는 close 발신 0");
  assert.deepEqual(calls, [], "stay 는 이동 0");

  answer = "discard";
  await wb.leaveTo("job");
  assert.deepEqual(b.actions(), ["leave_guard", "leave_guard", "close"], "discard 는 close 뒤 이동");
  assert.deepEqual(calls, [["job", { force: true }]]);
});

/* ================= 4. Bridge 객체째 · Nav late-bound ================= */

test("포트 교체 — Bridge.call 프로퍼티 교체·Nav.go 재배선이 다음 이탈에 보인다", async (t) => {
  freshDom(t);
  const b = makeBridge({ onCall: (s, a) => (a === "leave_guard" ? { armed: false } : {}) });
  const nav = { go: () => { throw new Error("옛 콜백이 불렸다"); } };
  const wb = createWorkbenchScreen({ Bridge: b.bridge, Nav: nav });
  wb.init();
  const swapped = [];
  b.bridge.call = async (...a) => { swapped.push(a[1]); return a[1] === "leave_guard" ? { armed: false } : {}; };
  nav.go = (...a) => swapped.push(["Nav.go", ...a]);           // 구성 뒤 재배선
  await wb.leaveTo("job");
  assert.deepEqual(swapped, ["leave_guard", "close", ["Nav.go", "job", { force: true }]],
    "갈아끼운 call·go 가 그 순서대로 불린다(값 캡처 0)");
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
  for (const g of PRODUCT_GLOBALS) {
    assert.equal(new RegExp(`(window|globalThis)\\.${g}\\b`).test(src), false,
      `window.${g} 조회·대입 0 (주석 포함 — 게이트 정규식이 주석도 본다)`);
  }
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.equal(/(window|globalThis)\.[A-Za-z_$][\w$]*\s*=[^=]/.test(code), false, "자기 전역 생산 금지");
  assert.ok(/window\.alert\(/.test(code), "loud 실패 통로(window.alert) 보존");
});

test("음성 — export 는 createWorkbenchScreen 하나(named)뿐, deps 는 { Bridge, Nav }", () => {
  assert.equal(/export\s+default/.test(src), false, "export default 금지");
  const names = [...src.matchAll(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  assert.deepEqual(names, ["createWorkbenchScreen"]);
  assert.ok(src.includes("export function createWorkbenchScreen({ Bridge, Nav }) {"),
    "주입 deps 는 Bridge·Nav 둘뿐(교차 화면 테이블 없음)");
});

test("음성 — import 는 공용 잎·서비스 직접 간선뿐, 화면 간·app·bridge import 0, 판정 E 유지", () => {
  const found = [...src.matchAll(/^import .*$/gm)].map((m) => m[0]);
  assert.deepEqual(found, [
    'import { escHtml } from "../esc.js";',
    'import { Intent } from "../intent.js";',
    'import { Modal } from "../modal.js";',
    'import { Preserve } from "../preserve.js";',
    'import { SegView } from "../segview.js";',
  ]);
  for (const line of found) {
    assert.equal(/screens\/|app\.js|bridge\.js/.test(line), false, "화면 간·셸·브리지 import 금지");
  }
  // 판정 E(계약 §10.15.2) — 작업대는 편집기로 나가는 deep-link 를 갖지 않는다.
  assert.equal(src.includes("EditorEntry"), false);
  assert.equal(src.includes("openJobInEditor"), false);
});

test("음성 — 커밋 3종의 정산 관문(Intent.settle)과 메서드 사전 추출 금지", () => {
  assert.equal((src.match(/await Intent\.settle\(WB_CHAIN\);/g) || []).length, 3,
    "copyCard·saveRules·leaveTo 세 커밋이 전부 정산을 앞세운다");
  assert.equal(/^\s*const\s+\w+\s*=\s*Bridge\.\w+\s*;/m.test(src), false,
    "`const x = Bridge.call` 류 캡처는 프로퍼티 교체를 우회한다");
});
