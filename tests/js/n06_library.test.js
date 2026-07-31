/* N-06 lane B — 「문서 작업」 화면(screens/library.js)의 true ESM factory 전환 계약.
 *
 * 지키는 것 다섯:
 *  ① 공개 표면 — `createLibraryScreen({...})` 이 정확히 `{ init }` 을 낸다.
 *  ② init 멱등·재시도(§7) — 성공 재호출은 listener/onPush/initial 추가 등록 0, 동시 2회는
 *     initial 1회 공유, 첫 initial 실패는 고착 없이 다음 명시적 init() 이 다시 당긴다.
 *     소스 call-site 수가 아니라 계측된 stub DOM/Bridge 로 **실측**한다.
 *  ③ 교차 화면 콜백(Nav·JobScreen)은 **late-bound 콜백 테이블**이다 — 구성 뒤에 갈아끼운
 *     콜백이 호출 시점에 잡힌다(값 캡처면 셸보다 먼저 평가되는 이 모듈이 undefined 를 붙든다).
 *  ④ Bridge 는 **객체째** 산다 — Python selftest 가 `window.Bridge.call = stub` 프로퍼티
 *     교체로 통로를 갈아끼우므로, 교체가 다음 발신에 보여야 한다(메서드 사전 추출 금지).
 *  ⑤ 음성 — IIFE 0, 제품 전역 27종 조회 0, export 정확히 1(named), 화면 간 import 0,
 *     Python 계약 테스트가 자르는 앵커(`Bridge.call(JOB, "prefer_work"` → `Nav.go(JOB);`) 보존.
 *
 * 임포트 그래프(modal → popover, undo_toast)는 평가 시점에 document 를 만진다 — 전역 대역을
 * 먼저 깔고 동적 import 로 연다(n05 관례). 대역은 표준 Web API 만 흉내 내고 제품 전역은
 * 세우지 않는다.
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
  const stats = { listeners: 0 };   // 요소+document+window addEventListener 총계(실측)
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

const SRC = new URL("../../frontend/js/screens/library.js", import.meta.url);
const src = fs.readFileSync(SRC, "utf8");

const { createLibraryScreen } = await import("../../frontend/js/screens/library.js");

/* ---------------- 계측 하니스 ---------------- */

function snap(extra) {
  return Object.assign({
    alerts: { missing_template_count: 0, pool_corrupted: 0 },
    corrupt_rows: [],
    view: "all", counts: {}, mode: "all", facets: [], query: "",
    is_empty: true, sections: [], selected: null, detail: null, group_names: [],
  }, extra || {});
}

const DETAIL = {
  name: "작업A", mode_label: "HWPX", group: "", last_run_display: "방금",
  health_causes: [], template_missing: false,
  primary: { target: "job", label: "문서 만들기에서 사용", hint: "" },
  tags: {}, template_name: "t.hwpx", template_path: "C:/t.hwpx",
  filename_pattern: "", run_note: "", bindings: [],
};

/* Bridge 대역 — 등록·당김·발신을 전부 한 로그에 실측으로 쌓는다. */
function makeBridge(opts) {
  const o = opts || {};
  const log = [];
  const counts = { onPush: 0, initial: 0 };
  const bridge = {
    onPush(screen, fn) { counts.onPush += 1; log.push(["onPush", screen, fn]); },
    initial: async (screen) => {
      counts.initial += 1;
      log.push(["initial", screen]);
      if (o.rejectFirstInitial && counts.initial === 1) throw new Error("initial 실패");
      return o.snapshot ? o.snapshot() : snap();
    },
    call: async (...a) => { log.push(["call", ...a]); return o.onCall ? o.onCall(...a) : {}; },
    revealCorruptJob: async () => null,
  };
  return { bridge, log, counts };
}

function makeDeps(bridge, calls) {
  return {
    Bridge: bridge,
    Nav: { go: (...a) => calls.push(["Nav.go", ...a]) },
    JobScreen: { openBrowseNeedsAction: async (...a) => calls.push(["JobScreen.openBrowseNeedsAction", ...a]) },
    EditorEntry: {
      newDraft: async () => calls.push(["EditorEntry.newDraft"]),
      openGuarded: (...a) => calls.push(["EditorEntry.openGuarded", ...a]),
    },
    PathTrack: { affordances: () => "" },
    Relink: { relinkTemplate: (...a) => calls.push(["Relink.relinkTemplate", ...a]) },
  };
}

/* 배선된 실 핸들러를 꺼낸다 — 하나뿐이어야 한다(중복 배선이면 멱등 계약 위반). */
function wiredHandler(dom, id, type) {
  const list = dom.byId(id)._listeners.get(type) || [];
  assert.equal(list.length, 1, `${id} ${type} 리스너는 정확히 1개`);
  return list[0].fn;
}

/* 위임 클릭 이벤트 대역 — closest 가 딱 그 data-속성에만 명중한다. */
function evtFor(attr, value) {
  const hit = { dataset: { [attr]: value }, getAttribute: () => null };
  return { target: { closest: (sel) => (sel === `[data-${attr}]` ? hit : null) } };
}

/* ================= 1. 공개 표면 ================= */

test("공개 표면 — createLibraryScreen 은 { init } 만 낸다", (t) => {
  freshDom(t);
  assert.equal(typeof createLibraryScreen, "function");
  const screen = createLibraryScreen(makeDeps(makeBridge().bridge, []));
  assert.deepEqual(Object.keys(screen), ["init"]);
  assert.equal(typeof screen.init, "function");
});

/* ================= 2. init 멱등·재시도(§7) — 전부 실측 ================= */

test("init 재호출 — listener·onPush·initial 추가 등록이 전부 0", async (t) => {
  const dom = freshDom(t);
  const b = makeBridge();
  const screen = createLibraryScreen(makeDeps(b.bridge, []));
  await screen.init();
  const first = { onPush: b.counts.onPush, initial: b.counts.initial, listeners: dom.stats.listeners };
  assert.equal(first.onPush, 1, "onPush 1회");
  assert.equal(first.initial, 1, "initial 1회");
  assert.ok(first.listeners > 0, "wire 가 실제로 리스너를 달았다");
  await screen.init();
  assert.deepEqual(
    { onPush: b.counts.onPush, initial: b.counts.initial, listeners: dom.stats.listeners },
    first, "2회째 delta 0");
  wiredHandler(dom, "libraryList", "click");     // 중복 배선 아님을 요소 단위로도 확인
  wiredHandler(dom, "libraryDetail", "click");
});

test("동시 init 2회 — 같은 초기화를 공유해 initial 은 1회만 나간다", async (t) => {
  freshDom(t);
  const b = makeBridge();
  const screen = createLibraryScreen(makeDeps(b.bridge, []));
  await Promise.all([screen.init(), screen.init()]);
  assert.equal(b.counts.initial, 1);
  assert.equal(b.counts.onPush, 1);
});

test("첫 initial 실패 — 호출자에게 전파되고, 다음 명시적 init 이 initial 만 다시 당긴다", async (t) => {
  const dom = freshDom(t);
  const b = makeBridge({ rejectFirstInitial: true });
  const screen = createLibraryScreen(makeDeps(b.bridge, []));
  await assert.rejects(screen.init(), /initial 실패/, "실패는 조용히 삼키지 않는다");
  const wiredAt = dom.stats.listeners;
  assert.equal(b.counts.onPush, 1, "실패해도 배선은 이미 섰다");
  await screen.init();                            // 회복 — initial 만 다시
  assert.equal(b.counts.initial, 2, "initial 재당김 1회");
  assert.equal(b.counts.onPush, 1, "onPush 재등록 0");
  assert.equal(dom.stats.listeners, wiredAt, "listener 재등록 0");
  assert.equal(dom.byId("libraryCount").textContent, "저장된 작업이 없습니다.",
    "회복한 스냅샷이 실제로 그려졌다");
});

/* ================= 3. 교차 화면 콜백 — late-bound 테이블 ================= */

test("「문서 만들기에서 사용」 — 겨눔(prefer_work) 뒤 Nav.go, incompatible 이면 JobScreen 위임", async (t) => {
  const dom = freshDom(t);
  const calls = [];
  const b = makeBridge({
    snapshot: () => snap({ detail: DETAIL, selected: "작업A", is_empty: false }),
    onCall: (s, action) => (action === "prefer_work" ? { reason: "incompatible" } : {}),
  });
  const deps = makeDeps(b.bridge, calls);
  const screen = createLibraryScreen(deps);
  await screen.init();
  const fire = wiredHandler(dom, "libraryDetail", "click");

  fire(evtFor("use", "작업A"));
  await tick();
  assert.deepEqual(
    b.log.filter((r) => r[0] === "call").map((r) => r.slice(1)),
    [["job", "prefer_work", { name: "작업A" }]],
    "판정은 Python(job/prefer_work)이 낸다");
  assert.deepEqual(calls, [
    ["Nav.go", "job"],
    ["JobScreen.openBrowseNeedsAction", "작업A"],
  ], "겨눔 성공 뒤에만 이동하고, incompatible 은 확인 필요 탭으로 위임한다");

  // late-binding — 구성 **뒤에** 갈아끼운 콜백이 다음 호출에 잡힌다(값 캡처 금지의 실측).
  calls.length = 0;
  deps.Nav.go = (...a) => calls.push(["Nav.go#2", ...a]);
  deps.JobScreen.openBrowseNeedsAction = async (...a) => calls.push(["open#2", ...a]);
  fire(evtFor("use", "작업A"));
  await tick();
  assert.deepEqual(calls, [["Nav.go#2", "job"], ["open#2", "작업A"]]);
});

/* ================= 4. Bridge 는 객체째 — 프로퍼티 교체가 보인다 ================= */

test("포트 교체 — Bridge.call 을 갈아끼우면 다음 발신이 새 함수로 나간다(프로브 경로 생존)", async (t) => {
  const dom = freshDom(t);
  const b = makeBridge({ snapshot: () => snap({ detail: DETAIL, selected: "작업A", is_empty: false }) });
  const screen = createLibraryScreen(makeDeps(b.bridge, []));
  await screen.init();
  const swapped = [];
  b.bridge.call = async (...a) => { swapped.push(a); return {}; };   // selftest 가 하는 일
  wiredHandler(dom, "libraryDetail", "click")(evtFor("clone", "작업A"));
  await tick();
  assert.deepEqual(swapped, [["library", "clone_job", { name: "작업A" }]]);
});

test("메서드 사전 추출 금지 — 소스에 Bridge 메서드 값 캡처가 없다", () => {
  assert.equal(/^\s*const\s+\w+\s*=\s*Bridge\.\w+\s*;/m.test(src), false,
    "`const x = Bridge.call` 류 캡처는 프로퍼티 교체를 우회한다");
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
  // 표준 Web API 는 그대로 — loud 실패 통로.
  assert.ok(/window\.alert\(/.test(code), "loud 실패 통로(window.alert) 보존");
});

test("음성 — export 는 createLibraryScreen 하나(named)뿐, deps 는 구조분해 인자", () => {
  assert.equal(/export\s+default/.test(src), false, "export default 금지");
  const names = [...src.matchAll(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  assert.deepEqual(names, ["createLibraryScreen"]);
  assert.ok(src.includes(
    "export function createLibraryScreen({ Bridge, Nav, JobScreen, EditorEntry, PathTrack, Relink }) {"),
    "주입 deps = Bridge·Nav·JobScreen·EditorEntry·PathTrack·Relink (교차 화면·compat 산물)");
});

test("음성 — import 는 공용 잎·서비스 직접 간선뿐, 화면 간·app·bridge import 0", () => {
  const found = [...src.matchAll(/^import .*$/gm)].map((m) => m[0]);
  assert.deepEqual(found, [
    'import { escHtml } from "../esc.js";',
    'import { GroupList } from "../grouplist.js";',
    'import { Intent } from "../intent.js";',
    'import { Modal } from "../modal.js";',
    'import { Popover } from "../popover.js";',
    'import { Preserve } from "../preserve.js";',
    'import { UndoToast } from "../undo_toast.js";',
  ]);
  for (const line of found) {
    assert.equal(/screens\/|app\.js|bridge\.js/.test(line), false, "화면 간·셸·브리지 import 금지");
  }
});

test("앵커 보존 — Python 계약 테스트가 자르는 prefer_work…Nav.go(JOB); 구간이 산다", () => {
  const at = src.indexOf('Bridge.call(JOB, "prefer_work"');
  assert.ok(at >= 0, "prefer_work 발신 리터럴 보존");
  assert.ok(src.indexOf("Nav.go(JOB);", at) > at, "겨눔 뒤 Nav.go(JOB); 보존");
  assert.equal(src.includes("window.Nav.go(JOB);"), false, "전역 조회판 앵커는 은퇴");
});
