/* Shared service behavior: late-bound ports, persistence, queues, and settle-once. */
import test from "node:test";
import assert from "node:assert/strict";

/* ---------------- 최소 DOM 대역 ---------------- */

class FakeStyle {
  constructor() { this.display = ""; this._props = {}; }
  setProperty(k, v) { this._props[k] = v; }
  getPropertyValue(k) { return this._props[k] || ""; }
}

class FakeEl {
  constructor(id) {
    this.id = id || "";
    this.style = new FakeStyle();
    this.dataset = {};
    this.innerHTML = "";
    this.textContent = "";
    this.value = "";
    this.title = "";
    this.hidden = false;
    this.checked = false;
    this.isConnected = true;
    this.nextElementSibling = null;
    this._attrs = {};
    this._listeners = new Map();
    this.classList = { toggle() {}, add() {}, remove() {}, contains: () => false };
  }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return Object.hasOwn(this._attrs, k) ? this._attrs[k] : null; }
  removeAttribute(k) { delete this._attrs[k]; }
  addEventListener(type, fn, opts) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push({ fn, opts });
  }
  removeEventListener(type, fn) {
    const a = this._listeners.get(type) || [];
    const i = a.findIndex((r) => r.fn === fn);
    if (i >= 0) a.splice(i, 1);
  }
  listeners(type) { return this._listeners.get(type) || []; }
  fire(type, ev) { this.listeners(type).slice().forEach((r) => r.fn(ev)); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  contains() { return false; }
  matches() { return false; }
  focus() {}
  blur() {}
  getBoundingClientRect() { return { top: 0, left: 0, width: 10, height: 10, bottom: 10, right: 10 }; }
}

function makeDom() {
  const byId = new Map();
  const docListeners = new Map();
  const app = new FakeEl("app");
  const alerts = [];
  const events = [];
  const document = {
    documentElement: new FakeEl("html"),
    body: new FakeEl("body"),
    activeElement: null,
    getElementById: (id) => byId.get(id) || null,
    querySelector: (sel) => (sel === ".app" ? app : null),
    querySelectorAll: () => [],
    addEventListener(type, fn, opts) {
      if (!docListeners.has(type)) docListeners.set(type, []);
      docListeners.get(type).push({ fn, opts });
    },
    removeEventListener() {},
    createElement: () => new FakeEl(),
  };
  const window = {
    pywebview: { api: {} },
    alert: (m) => alerts.push(String(m)),
    dispatchEvent: (e) => { events.push(e && e.type); return true; },
    addEventListener() {},
    removeEventListener() {},
    innerWidth: 1200,
    innerHeight: 800,
  };
  return {
    window, document, app, alerts, events, docListeners,
    ensure(id) { if (!byId.has(id)) byId.set(id, new FakeEl(id)); return byId.get(id); },
    get: (id) => byId.get(id) || null,
    clicks: () => docListeners.get("click") || [],
  };
}

const GLOBALS = ["window", "document", "getComputedStyle", "CSS"];

function installDom(dom) {
  globalThis.window = dom.window;
  globalThis.document = dom.document;
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => "240px" });
  globalThis.CSS = { escape: (s) => String(s).replace(/["\\]/g, "\\$&") };
  return dom;
}

/* 기준선: 임포트 그래프 평가에만 쓰인다. 각 테스트는 자기 DOM 을 깔고 t.after 로 되돌린다. */
const BASELINE = installDom(makeDom());

function freshDom(t) {
  const dom = installDom(makeDom());
  t.after(() => installDom(BASELINE));
  return dom;
}

/* ---------------- 그래프 열기 ---------------- */

const { createTheme, createPersonalization } = await import(
  "../../frontend/src/shell/preferences.ts");
const { createJobReadController } = await import("../../frontend/src/screens/job_read.ts");
const { createPort, createScreenPorts } = await import("../../frontend/src/screens/ports.ts");
const { createServiceHandoffPorts } = await import("../../frontend/src/ports/service_handoff.ts");
const { createSheetPickerController } = await import("../../frontend/src/screens/sheet_picker.ts");
const { Popover } = await import("../../frontend/js/popover.js");
const { Intent } = await import("../../frontend/js/intent.js");

/* Popover 는 실 DOM 을 만지는 표면이라, 이 파일에서는 **같은 객체의 메서드만** 갈아
   끼워 호출을 관측한다(살아 있는 export 객체 — 서비스가 보는 것과 동일 참조). */
function patch(obj, keys, t) {
  const log = [];
  const saved = {};
  for (const k of keys) {
    saved[k] = obj[k];
    obj[k] = (...args) => { log.push([k, ...args]); return log[`ret_${k}`]; };
  }
  t.after(() => { for (const k of keys) obj[k] = saved[k]; });
  return log;
}

function reactZoneHarness(onDispatch) {
  const calls = [];
  const snapshot = { has_job: true, has_data: true, filter: { search: "" }, zone_epoch: 7 };
  const ports = createScreenPorts();
  ports.jobRunCoordination.bind({ confirmDestructiveIfArmed: async () => true, log() {} });
  ports.editorEntry.bind({
    openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {},
    confirmDiscard() {}, restoreEntryFocus() {},
  });
  const services = createServiceHandoffPorts();
  services.relink.bind({ relinkTemplate: async () => true });
  const client = {
    dispatch: async (screen, action, payload) => {
      calls.push([screen, action, payload]);
      const value = onDispatch ? await onDispatch(screen, action, payload) : {};
      return { ok: true, value };
    },
  };
  const timers = new Map();
  let timerId = 0;
  const controller = createJobReadController({
    runtime: { model: () => ({ getSnapshot: () => ({ full: snapshot, progress: null }), subscribe: () => () => {} }) },
    client, ports, services,
    modal: { confirm: async () => false, open() {}, close() {} },
    surfaceSheet: { open() {}, close() {} }, dataPicker: { open: async () => null },
    navigation: { go() {} }, notify() {},
    doc: {
      activeElement: null, getElementById: () => null,
      defaultView: {
        setTimeout(fn) { timerId += 1; timers.set(timerId, fn); return timerId; },
        clearTimeout(id) { timers.delete(id); },
      },
    },
  });
  return { controller, client, ports, calls, timers };
}

/* ================= 1. 공개 표면이 §1 표와 정확히 일치 ================= */

test("공개 표면 — 팩토리/named export 와 반환 키가 계약 표 그대로", (t) => {
  freshDom(t);
  const bridge = {};

  assert.equal(typeof createTheme, "function");
  assert.deepEqual(Object.keys(createTheme({ bridge })).sort(),
    ["apply", "current", "set", "toggle"]);

  assert.equal(typeof createPersonalization, "function");
  assert.deepEqual(Object.keys(createPersonalization({ bridge })).sort(),
    ["apply", "currentFontScale", "masterMax", "masterMin", "saveMasterWidth",
      "setFontScale", "setMasterWidth", "toggleFontScale"]);

  assert.equal(typeof createJobReadController, "function");
  const rz = reactZoneHarness();
  assert.equal(typeof rz.controller.zone, "function");
  assert.equal(typeof rz.ports.jobData.current().flushPendingEdits, "function");
});

test("공개 표면 — React JobDataCoordinator는 flushPendingEdits 하나만 낸다", (t) => {
  freshDom(t);
  const rz = reactZoneHarness();
  assert.deepEqual(Object.keys(rz.ports.jobData.current()), ["flushPendingEdits"]);
  assert.equal(rz.ports.jobData.current().flushPendingEdits, rz.controller.flushPendingEdits);
});

/* ================= 2. 포트 프로퍼티 교체가 보인다 ================= */

test("포트 교체 — Theme 은 갈아끼운 bridge.setTheme 를 본다", (t) => {
  freshDom(t);
  const seen = [];
  const bridge = { hostReady: () => true, setTheme: (v) => seen.push(["A", v]) };
  const theme = createTheme({ bridge });
  theme.set("dark");
  bridge.setTheme = (v) => seen.push(["B", v]);   // 프로브가 하는 일
  theme.set("light");
  assert.deepEqual(seen, [["A", "dark"], ["B", "light"]]);
});

test("포트 교체 — Personalization 은 갈아끼운 bridge.setFontScale 를 본다", (t) => {
  freshDom(t);
  const seen = [];
  const bridge = {
    hostReady: () => true,
    setFontScale: (v) => seen.push(["A", v]),
    setMasterWidth: () => {},
  };
  const pers = createPersonalization({ bridge });
  pers.setFontScale("large");
  bridge.setFontScale = (v) => seen.push(["B", v]);
  pers.setFontScale("larger");
  assert.deepEqual(seen, [["A", "large"], ["B", "larger"]]);
});

test("포트 교체 — React DataZone의 새 요청은 갈아끼운 client.dispatch를 본다", async (t) => {
  freshDom(t);
  const seen = [];
  const rz = reactZoneHarness();
  rz.client.dispatch = async (...args) => { seen.push(["A", ...args]); return { ok: true, value: {} }; };
  await rz.controller.zone("filter_search", { text: "가" });
  rz.client.dispatch = async (...args) => { seen.push(["B", ...args]); return { ok: true, value: {} }; };
  await rz.controller.zone("filter_search", { text: "나" });
  assert.deepEqual(seen.map((r) => [r[0], r[2], r[3]]), [
    ["A", "filter_search", { text: "가", epoch: 7 }],
    ["B", "filter_search", { text: "나", epoch: 7 }],
  ]);
});

/* ================= 4. React DataZone queue/host envelope ================= */

test("DataZone — queue 대기 중 교체한 client port가 다음 발신에 적용된다", async (t) => {
  freshDom(t);
  const seen = [];
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  const rz = reactZoneHarness();
  rz.client.dispatch = async (...args) => { seen.push(["first", ...args]); await held; return { ok: true, value: {} }; };
  const first = rz.controller.zone("set_all", {});
  await Promise.resolve();
  const second = rz.controller.zone("set_none", {});
  rz.client.dispatch = async (...args) => { seen.push(["late", ...args]); return { ok: true, value: {} }; };
  release();
  await Promise.all([first, second]);
  assert.deepEqual(seen.map((r) => [r[0], r[2]]), [["first", "set_all"], ["late", "set_none"]]);
});

test("DataZone — 손상된 HostResult envelope는 loud failure다", async (t) => {
  freshDom(t);
  const rz = reactZoneHarness();
  rz.client.dispatch = async () => ({ value: {} });
  await assert.rejects(rz.controller.zone("set_all", {}), /호스트 결과가 손상/);
});

/* ================= 5. Theme/Personalization 영속 호출 인자 전수 ================= */

test("Theme — 영속은 bridge.setTheme 로, 정규화된 현재 값으로 나간다", (t) => {
  const dom = freshDom(t);
  const calls = [];
  const theme = createTheme({
    bridge: { hostReady: () => true, setTheme: (v) => calls.push(v) },
  });
  assert.equal(theme.set("dark"), "dark");
  assert.equal(theme.set("light"), "light");
  assert.equal(theme.set("bogus"), "system");      // 미상은 system 으로 강등
  assert.equal(theme.toggle(), "light");           // system → light
  assert.deepEqual(calls, ["dark", "light", "system", "light"]);
  assert.deepEqual(dom.events, ["hwpx:themechange", "hwpx:themechange",
    "hwpx:themechange", "hwpx:themechange"]);
  // apply 는 영속 없이 셸만 — 부팅 주입 경로(app.py _apply_theme_then_show)의 계약.
  theme.apply("dark");
  assert.deepEqual(calls, ["dark", "light", "system", "light"]);
});

test("Theme — 브리지 부재 프리뷰는 의도적 미영속(조용한 실패 아님)", (t) => {
  const dom = freshDom(t);
  dom.window.pywebview = undefined;
  const calls = [];
  // 호스트 준비 판정은 bridge 포트가 소유한다.
  const theme = createTheme({
    bridge: { hostReady: () => false, setTheme: (v) => calls.push(v) },
  });
  assert.equal(theme.set("dark"), "dark");
  assert.deepEqual(calls, []);
  assert.deepEqual(dom.alerts, []);
});

test("Theme — 영속 throw 는 삼키지 않고 loud(window.alert)", (t) => {
  const dom = freshDom(t);
  const theme = createTheme({
    bridge: {
      hostReady: () => true,
      setTheme: () => { throw new Error("브리지 사망"); },
    },
  });
  theme.set("dark");
  assert.deepEqual(dom.alerts, ["브리지 사망"]);
});

test("Personalization — 영속 호출 인자 전수(클램프된 값이 나간다)", (t) => {
  freshDom(t);
  const calls = [];
  const pers = createPersonalization({
    bridge: {
      hostReady: () => true,
      setFontScale: (v) => calls.push(["setFontScale", v]),
      setMasterWidth: (v) => calls.push(["setMasterWidth", v]),
    },
  });
  assert.equal(pers.setFontScale("large"), "large");
  assert.equal(pers.setFontScale("헛것"), "normal");
  assert.equal(pers.toggleFontScale(), "large");
  assert.equal(pers.saveMasterWidth(1000), pers.masterMax);
  assert.equal(pers.saveMasterWidth(1), pers.masterMin);
  assert.equal(pers.saveMasterWidth(250.4), 250);
  assert.deepEqual(calls, [
    ["setFontScale", "large"], ["setFontScale", "normal"], ["setFontScale", "large"],
    ["setMasterWidth", 420], ["setMasterWidth", 180], ["setMasterWidth", 250],
  ]);
  // setMasterWidth 단독은 영속하지 않는다(드래그 중 왕복 금지) — save 만 나간다.
  assert.equal(pers.setMasterWidth(300), 300);
  assert.equal(calls.length, 6);
});

test("Personalization — apply 는 영속 없이 셸만(app.py loaded 경로)", (t) => {
  const dom = freshDom(t);
  const calls = [];
  const pers = createPersonalization({
    bridge: { setFontScale: (v) => calls.push(v), setMasterWidth: (v) => calls.push(v) },
  });
  pers.apply({ font_scale: "larger", master_width: 300 });
  assert.equal(pers.currentFontScale(), "larger");
  assert.equal(dom.app.style.getPropertyValue("--master-width"), "300px");
  assert.deepEqual(calls, []);
  assert.deepEqual(dom.events, ["hwpx:personalizationchange"]);
});

/* ================= 9. 팩토리 2회 호출 = 독립 인스턴스 ================= */

test("팩토리를 두 번 부르면 독립 인스턴스가 나온다(중앙은 1회만 부른다)", async (t) => {
  const dom = freshDom(t);
  const seenA = [], seenB = [];
  const themeA = createTheme({
    bridge: { hostReady: () => true, setTheme: (v) => seenA.push(v) },
  });
  const themeB = createTheme({
    bridge: { hostReady: () => true, setTheme: (v) => seenB.push(v) },
  });
  assert.notEqual(themeA, themeB);
  themeA.set("dark");
  themeB.set("light");
  assert.deepEqual(seenA, ["dark"]);
  assert.deepEqual(seenB, ["light"]);

  // React DataZone: controller의 queue와 pending state는 인스턴스별로 격리된다.
  const sentA = [], sentB = [];
  const zoneA = reactZoneHarness((...args) => { sentA.push(args); return {}; });
  const zoneB = reactZoneHarness((...args) => { sentB.push(args); return {}; });
  zoneA.controller.scheduleSearch("가");
  await zoneA.controller.flushPendingEdits();
  await zoneB.controller.flushPendingEdits();
  assert.equal(sentA.length, 1);
  assert.deepEqual(sentB, []);
});

/* ---------------- 화면 간 서비스 포트·시트 확정 게이트 ---------------- */

const SHEET_PAYLOAD = {
  name: "d.xlsx",
  path: "D:\\d.xlsx",
  sheets: [{ name: "S1" }, { name: "S2" }],
};

function sheetPickerHarness(invoke) {
  const loads = [];
  let openSpec = null;
  const controller = createSheetPickerController({
    doc: { querySelector: () => null },
    client: {
      async invoke(method, ...args) {
        loads.push([method, ...args]);
        return invoke ? invoke(method, ...args) : { ok: true, value: { label: "선택" } };
      },
    },
    modal: {
      open: (_id, spec) => { openSpec = spec; },
      close() {},
    },
  });
  return { controller, loads, close: () => openSpec.onClose() };
}

test("service port는 미결속·중복 결속을 거절하고 각 구현을 독립 보존한다", () => {
  const probe = createPort("probe");
  assert.throws(() => probe.current(), /결속되지/);
  const impl = { run: () => true };
  probe.bind(impl);
  assert.equal(probe.current(), impl);
  assert.throws(() => probe.bind(impl), /정확히 한 번/);

  const services = createServiceHandoffPorts();
  const picker = { choose: async () => null };
  const relink = { relinkTemplate: async () => true };
  services.sheetPicker.bind(picker);
  services.relink.bind(relink);
  assert.equal(services.sheetPicker.current(), picker);
  assert.equal(services.relink.current(), relink);
});

test("시트는 명시 선택 뒤에만 로드되고 취소는 null·발신 0이다", async () => {
  const selected = sheetPickerHarness();
  const selection = selected.controller.port.choose("job", SHEET_PAYLOAD);
  assert.deepEqual(selected.loads, []);
  await selected.controller.pick("S2");
  assert.deepEqual(selected.loads, [["load_data_sheet", "job", "D:\\d.xlsx", "S2"]]);
  assert.deepEqual(await selection, { label: "선택" });

  const cancelled = sheetPickerHarness();
  const cancellation = cancelled.controller.port.choose("job", SHEET_PAYLOAD);
  cancelled.close();
  assert.equal(await cancellation, null);
  assert.deepEqual(cancelled.loads, []);
});

test("시트 선택은 동시 클릭과 늦은 close에도 정확히 한 번만 settle된다", async () => {
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  const h = sheetPickerHarness(async () => {
    await held;
    return { ok: true, value: { label: "선택" } };
  });
  const selection = h.controller.port.choose("job", SHEET_PAYLOAD);
  await assert.rejects(() => h.controller.port.choose("editor", SHEET_PAYLOAD), /이미 열려 있습니다/);
  const first = h.controller.pick("S1");
  await h.controller.pick("S2");
  assert.equal(h.loads.length, 1);
  release();
  await first;
  assert.deepEqual(await selection, { label: "선택" });
  h.close();
  h.close();
  assert.equal(h.loads.length, 1);
});

/* ---------------- 공용 cfg ---------------- */

function zoneCfg(dom, suffix) {
  const s = suffix || "";
  const ids = {};
  for (const k of ["selCount", "search", "reapply", "chips", "strip", "tableHost", "tableWrap",
    "tableEmpty", "tableHead", "tableBody", "colPanel", "selAll", "selNone"]) {
    ids[k] = "dz" + k[0].toUpperCase() + k.slice(1) + s;
  }
  ids.search = "dzSearch" + s;
  for (const id of Object.values(ids)) dom.ensure(id);
  return {
    screen: "job", ids, rowIdPrefix: "jobRow-",
    lead: { header: "문서", bodyHtml: (r) => String(r.index) },
    copy: { emptyNoData: "데이터 없음", emptyNoRows: "행 없음", emptyFiltered: "필터 결과 없음", stripLead: (n) => `${n}건` },
    tableKey: (x) => String(x.record_count),
    log: () => {},
  };
}
