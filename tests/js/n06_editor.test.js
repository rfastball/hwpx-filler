/* N-06 lane C — 편집기 화면(`screens/editor.js`)의 ESM factory 전환 계약 테스트.
 *
 * 지키는 경계:
 *  ① 공개 표면 4키(init·rerender·leaveTo·aimAt) — 몰입 표면의 문 손잡이 수는 계약이다.
 *  ② init 멱등·재시도(§7) — 재호출 시 listener·onPush·initial 등록 delta 0 을 **실측**한다
 *     (소스 call-site 수를 기대값으로 쓰지 않는다). 첫 initial reject 후 명시적 재-init 이
 *     initial 만 다시 당기고 배선은 중복 설치하지 않는다.
 *  ③ 교차 화면 콜백(JobScreen { refreshList, openPreview })이 **late-bound 테이블**인가 —
 *     구성 뒤에 갈아끼운 콜백이 호출 시점에 잡혀야 한다(app 셸이 화면들을 순서대로 조립하므로
 *     값 캡처는 평가 순서 함정이다).
 *  ④ landOn 발신 순서 — `Nav.refresh` 가 `Nav.go` 보다 먼저 서고 `refreshed: true` 를 싣는다
 *     (재적재 전에 전환하면 사용자는 편집 전 규칙을 든 화면을 손에 쥔다 — 8R P1).
 *  ⑤ Bridge 는 **객체째** — Python selftest 가 `Bridge.call = stub` 으로 프로퍼티를 교체하므로
 *     메서드 사전 추출이 없는지 실행으로 확인한다.
 *  ⑥ 음성: IIFE 래퍼 0 · 제품 전역 27종 `window.X` 0 · export 정확히 1(named) · 화면 간 import 0.
 *
 * 임포트 그래프(modal → popover 등)는 평가 시점에 document 를 만지므로(n05 계약 유지)
 * 정적 import 전에 전역 대역을 깔고 동적 import 로 연다. 대역은 표준 Web API 만 흉내 낸다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

/* ---------------- 최소 DOM 대역 ---------------- */

class FakeEl {
  constructor(id, counters) {
    this.id = id || "";
    this._counters = counters || { listeners: 0 };
    this.style = { setProperty() {}, getPropertyValue: () => "" };
    this.dataset = {};
    this.innerHTML = "";
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.open = false;
    this.isConnected = true;
    this._attrs = {};
    this._listeners = new Map();
    this.classList = { toggle() {}, add() {}, remove() {}, contains: () => false };
    this.focused = 0;
  }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return Object.hasOwn(this._attrs, k) ? this._attrs[k] : null; }
  removeAttribute(k) { delete this._attrs[k]; }
  addEventListener(type, fn, opts) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push({ fn, opts });
    this._counters.listeners += 1;
  }
  removeEventListener() {}
  listeners(type) { return (this._listeners.get(type) || []).map((l) => l.fn); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  contains() { return false; }
  matches() { return false; }
  focus() { this.focused += 1; }
  blur() {}
  scrollIntoView() {}
  getBoundingClientRect() { return { top: 0, left: 0, width: 10, height: 10, bottom: 10, right: 10 }; }
}

function makeDom() {
  const alerts = [];
  const counters = { listeners: 0 };
  const els = new Map();
  const byId = (id) => {
    if (!els.has(id)) els.set(id, new FakeEl(id, counters));
    return els.get(id);
  };
  const document = {
    documentElement: new FakeEl("html", counters),
    body: new FakeEl("body", counters),
    activeElement: null,
    getElementById: byId,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() { counters.listeners += 1; },
    removeEventListener() {},
    createElement: () => new FakeEl("", counters),
  };
  const window = {
    pywebview: { api: {} },
    alert: (m) => alerts.push(String(m)),
    dispatchEvent: () => true,
    addEventListener() { counters.listeners += 1; },
    removeEventListener() {},
    innerWidth: 1200,
    innerHeight: 800,
  };
  return { window, document, alerts, counters, byId };
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

/* ---------------- 그래프 열기 ---------------- */

const SRC = new URL("../../frontend/js/screens/editor.js", import.meta.url);
const src = fs.readFileSync(SRC, "utf8");

const { createEditorScreen } = await import("../../frontend/js/screens/editor.js");
const { Modal } = await import("../../frontend/js/modal.js");
const { Popover } = await import("../../frontend/js/popover.js");

/* Modal·Popover 는 살아 있는 export 객체 — 화면이 보는 것과 동일 참조의 메서드만 갈아끼워
   호출을 관측한다(n05 관례). */
function patchModal(t, overrides) {
  const saved = {};
  for (const k of Object.keys(overrides)) {
    saved[k] = Modal[k];
    Modal[k] = overrides[k];
  }
  t.after(() => { for (const k of Object.keys(saved)) Modal[k] = saved[k]; });
}

function patchWireDismiss(t, counter) {
  const saved = Popover.wireDismiss;
  Popover.wireDismiss = (cfg) => { counter.n += 1; return () => {}; };
  t.after(() => { Popover.wireDismiss = saved; });
}

/* ---------------- 계측 스텁 ---------------- */

function makeBridge(cfg) {
  cfg = cfg || {};
  const trace = [];
  const pushHandlers = new Map();  // screen -> [fn]
  const bridge = {
    counts: { onPush: 0, initial: 0 },
    trace,
    push(screen, snap) { (pushHandlers.get(screen) || []).forEach((fn) => fn(snap)); },
    onPush(screen, fn) {
      bridge.counts.onPush += 1;
      if (!pushHandlers.has(screen)) pushHandlers.set(screen, []);
      pushHandlers.get(screen).push(fn);
      trace.push(["onPush", screen]);
    },
    initial(screen) {
      bridge.counts.initial += 1;
      trace.push(["initial", screen]);
      return (cfg.initial || (async () => ({})))(screen);
    },
    call(screen, action, payload) {
      trace.push(["call", screen, action, payload]);
      return (cfg.call || (async () => ({})))(screen, action, payload);
    },
    editorHasUnsavedWork: cfg.editorHasUnsavedWork || (async () => false),
  };
  return bridge;
}

function makeDeps(t, cfg) {
  cfg = cfg || {};
  const trace = [];
  const bridge = makeBridge({
    initial: cfg.initial,
    call: (screen, action, payload) => {
      trace.push([`Bridge.call`, screen, action]);
      return (cfg.call || (async () => ({})))(screen, action, payload);
    },
    editorHasUnsavedWork: cfg.editorHasUnsavedWork,
  });
  const Nav = {
    refresh: async (target) => { trace.push(["Nav.refresh", target]); },
    go: (target, opts) => { trace.push(["Nav.go", target, opts]); },
  };
  const JobScreen = {};  // 의도적으로 빈 테이블 — late-binding 을 실측하기 위해 뒤에 채운다.
  const EditorEntry = {
    confirmDiscard: async () => true,
    restoreEntryFocus: () => { trace.push(["EditorEntry.restoreEntryFocus"]); },
  };
  const PathTrack = { affordances: () => "" };
  const SheetPicker = { choose: async () => null };
  return { trace, bridge, deps: { Bridge: bridge, Nav, JobScreen, EditorEntry, PathTrack, SheetPicker } };
}

/* 렌더가 통과할 최소 스냅샷 — 신규 초안 1단계(라이브러리 빈 밴드). */
function snap(extra) {
  return Object.assign({
    section: "template",
    sections: ["template", "binding", "filename"],
    name: "테스트 작업",
    library: {},
    rows: [],
  }, extra || {});
}

/* ---------------- ① 공개 표면 ---------------- */

test("factory 는 정확히 {init, rerender, leaveTo, aimAt} 를 돌려준다", (t) => {
  freshDom(t);
  const { deps } = makeDeps(t);
  const screen = createEditorScreen(deps);
  assert.deepEqual(Object.keys(screen).sort(), ["aimAt", "init", "leaveTo", "rerender"]);
  for (const k of ["init", "rerender", "leaveTo", "aimAt"]) {
    assert.equal(typeof screen[k], "function", `${k} 는 함수여야 한다`);
  }
});

/* ---------------- ② init 멱등 — 등록 delta 실측 ---------------- */

test("init 2회 — listener·onPush·initial 추가 등록 0, 같은 promise 공유", async (t) => {
  const dom = freshDom(t);
  const wireCount = { n: 0 };
  patchWireDismiss(t, wireCount);
  const { bridge, deps } = makeDeps(t, { initial: async () => snap() });
  const screen = createEditorScreen(deps);

  const p1 = screen.init();
  await p1;
  const after1 = {
    listeners: dom.counters.listeners,
    onPush: bridge.counts.onPush,
    initial: bridge.counts.initial,
    wire: wireCount.n,
  };
  assert.equal(after1.onPush, 2, "editor + tpl 두 채널 구독");
  assert.equal(after1.initial, 1, "initial 당김 1회");
  assert.ok(after1.listeners > 0, "배선이 실제로 일어났다(양성 대조)");
  assert.equal(after1.wire, 1, "Popover.wireDismiss 1회");

  const p2 = screen.init();
  await p2;
  assert.equal(p2, p1, "성공한 init 재호출은 같은 promise 를 공유한다");
  assert.equal(dom.counters.listeners, after1.listeners, "listener 추가 등록 0");
  assert.equal(bridge.counts.onPush, after1.onPush, "onPush 추가 등록 0");
  assert.equal(bridge.counts.initial, after1.initial, "initial 추가 당김 0");
  assert.equal(wireCount.n, after1.wire, "wireDismiss 추가 등록 0");
});

test("동시 2회 init — 같은 초기화 promise, initial 1회", async (t) => {
  freshDom(t);
  const wireCount = { n: 0 };
  patchWireDismiss(t, wireCount);
  const { bridge, deps } = makeDeps(t, { initial: async () => snap() });
  const screen = createEditorScreen(deps);
  const p1 = screen.init();
  const p2 = screen.init();
  assert.equal(p1, p2);
  await Promise.all([p1, p2]);
  assert.equal(bridge.counts.initial, 1);
  assert.equal(bridge.counts.onPush, 2);
});

test("첫 initial reject — 실패는 전파되고, 명시적 재-init 이 initial 만 다시 당긴다", async (t) => {
  const dom = freshDom(t);
  const wireCount = { n: 0 };
  patchWireDismiss(t, wireCount);
  let fail = true;
  const { bridge, deps } = makeDeps(t, {
    initial: async () => {
      if (fail) throw new Error("boot fail");
      return snap();
    },
  });
  const screen = createEditorScreen(deps);

  await assert.rejects(screen.init(), /boot fail/, "rejection 은 호출자에게 전파된다");
  const afterFail = { listeners: dom.counters.listeners, onPush: bridge.counts.onPush, wire: wireCount.n };
  assert.equal(bridge.counts.initial, 1);

  fail = false;
  await screen.init();  // 회복 — 스스로 재시도하지 않고 명시적 호출이 다시 당긴다
  assert.equal(bridge.counts.initial, 2, "재-init 이 initial 을 다시 당겼다");
  assert.equal(bridge.counts.onPush, afterFail.onPush, "onPush 중복 설치 0");
  assert.equal(dom.counters.listeners, afterFail.listeners, "listener 중복 설치 0");
  assert.equal(wireCount.n, afterFail.wire, "wireDismiss 중복 설치 0");
});

/* ---------------- ③④ 교차 콜백·landOn 순서 ---------------- */

test("저장하고 나가기 — refreshList 관측, Nav.refresh→Nav.go(refreshed:true), openPreview 복귀, late-binding", async (t) => {
  freshDom(t);
  patchModal(t, { choose: async () => "save" });
  const { trace, deps } = makeDeps(t, {
    initial: async () => snap({
      dirty: true,
      context: {
        entry_reason: "preview_result",
        target: "binding/납품기한",
        return_context: { surface: "preview", reopen_drawer: true, preview_index: 2 },
      },
    }),
    call: async (screenName, action) => (action === "save" ? { ok: true } : {}),
  });
  const screen = createEditorScreen(deps);
  await screen.init();

  // late-binding: factory 구성·init **뒤에** 콜백 테이블을 채운다 — 호출 시점에 잡혀야 한다.
  deps.JobScreen.refreshList = () => { trace.push(["JobScreen.refreshList"]); };
  deps.JobScreen.openPreview = async (job, opts) => { trace.push(["JobScreen.openPreview", opts]); };

  await screen.leaveTo("job");

  const names = trace.map((e) => e[0]);
  const iSave = trace.findIndex((e) => e[0] === "Bridge.call" && e[2] === "save");
  assert.ok(iSave >= 0, "save 발신이 있었다");
  assert.ok(names.includes("JobScreen.refreshList"), "저장 성공 시 refreshList 호출(1289행 seam)");
  assert.ok(names.indexOf("JobScreen.refreshList") > iSave, "refreshList 는 저장 성공 뒤에 온다");

  const iRefresh = names.indexOf("Nav.refresh");
  const iGo = names.indexOf("Nav.go");
  assert.ok(iRefresh >= 0 && iGo >= 0, "Nav.refresh·Nav.go 둘 다 발화");
  assert.ok(iRefresh < iGo, "landOn 순서: refresh 가 go 보다 먼저(8R P1)");
  const goEntry = trace[iGo];
  assert.equal(goEntry[1], "job");
  assert.deepEqual(goEntry[2], { force: true, refreshed: true });

  const iFocus = names.indexOf("EditorEntry.restoreEntryFocus");
  assert.ok(iFocus > iGo, "착지 뒤 진입 초점 복원");

  const iPrev = names.indexOf("JobScreen.openPreview");
  assert.ok(iPrev > iGo, "미리보기 복귀는 착지 뒤");
  assert.deepEqual(trace[iPrev][1], { at: 2, focusTarget: "binding/납품기한" },
    "같은 previewIndex·행 정체성(context.target)을 나른다");
});

test("Nav.refresh 실패 — 나가지 않는다(loud alert, Nav.go 0회)", async (t) => {
  const dom = freshDom(t);
  const { trace, deps } = makeDeps(t, { initial: async () => snap({ dirty: false, is_draft: false }) });
  deps.Nav.refresh = async () => { throw new Error("stale disk"); };
  const screen = createEditorScreen(deps);
  await screen.init();

  await screen.leaveTo("job");
  assert.ok(!trace.some((e) => e[0] === "Nav.go"), "재적재 실패 시 전환하지 않는다");
  assert.ok(dom.alerts.some((m) => m.includes("머무릅니다")), "실패를 시끄럽게 재진술한다");
});

/* ---------------- ⑤ Bridge 는 객체째 ---------------- */

test("Bridge.call 프로퍼티 교체가 관측된다 — 메서드 사전 추출 없음", async (t) => {
  const dom = freshDom(t);
  const { bridge, deps } = makeDeps(t, { initial: async () => snap() });
  const screen = createEditorScreen(deps);
  await screen.init();

  const seen = [];
  bridge.call = async (screenName, action, payload) => {
    seen.push([screenName, action, payload]);
    return {};
  };
  // 위임 click 경로로 실행 유도: lib-refresh 는 Bridge.call("tpl","refresh",{}) 직행이다.
  const root = dom.byId("scr-editor");
  const clickFns = root.listeners("click");
  assert.equal(clickFns.length, 1, "root click 위임 1개");
  const fakeBtn = { dataset: { act: "lib-refresh" } };
  await clickFns[0]({ target: { closest: (sel) => (sel === "[data-act]" ? fakeBtn : null) } });
  assert.deepEqual(seen, [["tpl", "refresh", {}]], "교체된 Bridge.call 이 호출을 받았다");
});

/* ---------------- rerender — window.pywebview 가드 + 주입 Bridge ---------------- */

test("rerender — pywebview 존재 시 initial 재당김, 부재 시 무발신", async (t) => {
  const dom = freshDom(t);
  const { bridge, deps } = makeDeps(t, { initial: async () => snap() });
  const screen = createEditorScreen(deps);
  await screen.init();
  assert.equal(bridge.counts.initial, 1);

  screen.rerender();
  await Promise.resolve();
  assert.equal(bridge.counts.initial, 2, "rerender 가 주입 Bridge 로 재당김");

  dom.window.pywebview = null;
  screen.rerender();
  assert.equal(bridge.counts.initial, 2, "pywebview 부재 시 발신하지 않는다");
});

/* ---------------- ⑥ 음성 — 소스 텍스트 계약 ---------------- */

test("소스 음성: IIFE 0 · 제품 전역 27종 0 · export 1 · 화면 간 import 0", () => {
  assert.ok(!src.includes("(function () {"), "IIFE 래퍼가 남아 있지 않다");
  assert.ok(!src.includes("})();"), "IIFE 닫힘이 남아 있지 않다");

  const GLOBALS = [
    "Bridge", "__push", "Nav", "AppCloseGuard",
    "JobScreen", "LibraryScreen", "EditorScreen", "WorkbenchScreen",
    "Copy", "escHtml", "Guard", "SegView", "Popover", "Preserve", "Intent",
    "UndoToast", "Modal", "SurfaceSheet", "GroupList", "Theme", "Personalization",
    "SheetPicker", "PathTrack", "Relink", "DataZone", "DataPicker", "EditorEntry",
  ];
  assert.equal(GLOBALS.length, 27, "제품 전역 목록은 27종");
  for (const g of GLOBALS) {
    const re = new RegExp(`(?:window|globalThis)\\.${g}\\b`);
    assert.ok(!re.test(src), `window.${g} / globalThis.${g} 판독·대입 0`);
  }

  const exports = src.match(/^export\s/gm) || [];
  assert.equal(exports.length, 1, "export 는 정확히 1개");
  assert.ok(!/export\s+default/.test(src), "export default 금지");
  assert.ok(/export function createEditorScreen\(/.test(src), "named factory export");

  const imports = [...src.matchAll(/^import\s+.*?from\s+"([^"]+)"/gm)].map((m) => m[1]);
  assert.ok(imports.length > 0, "직접 ESM import 가 있다(양성 대조)");
  for (const spec of imports) {
    assert.ok(/^\.\.\/[a-z_]+\.js$/.test(spec), `잎 모듈만 import 한다: ${spec}`);
    assert.ok(!/screens\//.test(spec) && !/app\.js|bridge\.js/.test(spec),
      `화면·셸·브리지 import 금지: ${spec}`);
  }
});
