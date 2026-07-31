/* N-05 Packet C — 재사용 서비스/팩토리 7종의 ESM 전환 계약 테스트.
 *
 * 이 파일이 지키는 것은 "무엇을 그리는가"가 아니라 **경계**다: 공개 표면(§1 표), 의존이
 * 명시적 import 인가, Bridge 가 명시적 포트인가, 그리고 **포트가 객체째 살아 있는가**.
 * 마지막 항목이 이 파일의 존재 이유다 — Python selftest 프로브는 `window.Bridge.call = stub`
 * 처럼 **프로퍼티를 갈아끼워** 통로를 바꾼다(app.py 10곳). 서비스가 메서드를 모듈 스코프
 * 값으로 뽑아 두면 스텁이 우회돼 프로브가 실물 백엔드로 샌다 — 초록불인 채로.
 *
 * 임포트 그래프는 **평가 시점에 document 를 만진다**(popover.js 가 위임 리스너 7개를 모듈
 * 평가에 붙인다 — 부작용을 init 으로 옮기지 않는 것이 N-05 계약이다). 정적 import 로는
 * 그보다 먼저 대역을 세울 수 없어, 전역 대역을 깔고 **동적 import** 로 그래프를 연다.
 * 대역은 표준 Web API 만 흉내 내며 제품 전역(window.Bridge·window.Modal…)은 세우지 않는다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

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

const SRC = (n) => new URL(`../../frontend/js/${n}.js`, import.meta.url);
const read = (n) => fs.readFileSync(SRC(n), "utf8");

const { GroupList } = await import("../../frontend/js/grouplist.js");
const { createPathTrack } = await import("../../frontend/js/pathtrack.js");
const { createRelink } = await import("../../frontend/js/relink.js");
const { createTheme } = await import("../../frontend/js/theme.js");
const { createPersonalization } = await import("../../frontend/js/personalization.js");
const { createSheetPicker } = await import("../../frontend/js/sheet_picker.js");
const { createDataZone } = await import("../../frontend/js/datazone.js");
const { Modal } = await import("../../frontend/js/modal.js");
const { Popover } = await import("../../frontend/js/popover.js");
const { Intent } = await import("../../frontend/js/intent.js");

/* Modal·Popover 는 실 DOM 을 만지는 표면이라, 이 파일에서는 **같은 객체의 메서드만** 갈아
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

const FILES = ["grouplist", "datazone", "pathtrack", "relink", "theme", "personalization", "sheet_picker"];

/* ================= 1. 공개 표면이 §1 표와 정확히 일치 ================= */

test("공개 표면 — 팩토리/named export 와 반환 키가 계약 표 그대로", (t) => {
  freshDom(t);
  const bridge = {};

  assert.equal(typeof GroupList, "object");
  assert.deepEqual(Object.keys(GroupList).sort(), ["createMenu", "createMoveDialog", "toggleGroup"]);

  assert.equal(typeof createPathTrack, "function");
  assert.deepEqual(Object.keys(createPathTrack({ bridge })).sort(), ["affordances"]);

  assert.equal(typeof createRelink, "function");
  assert.deepEqual(Object.keys(createRelink({ bridge })).sort(), ["relinkTemplate"]);

  assert.equal(typeof createTheme, "function");
  assert.deepEqual(Object.keys(createTheme({ bridge })).sort(),
    ["apply", "current", "set", "toggle"]);

  assert.equal(typeof createPersonalization, "function");
  assert.deepEqual(Object.keys(createPersonalization({ bridge })).sort(),
    ["apply", "currentFontScale", "masterMax", "masterMin", "saveMasterWidth",
      "setFontScale", "setMasterWidth", "toggleFontScale"]);

  assert.equal(typeof createSheetPicker, "function");
  assert.deepEqual(Object.keys(createSheetPicker({ bridge })).sort(), ["choose"]);

  assert.equal(typeof createDataZone, "function");
  const dz = createDataZone({ bridge });
  assert.deepEqual(Object.keys(dz).sort(), ["create"]);
});

test("공개 표면 — GroupList 하위 팩토리 반환 키", (t) => {
  freshDom(t);
  assert.deepEqual(Object.keys(GroupList.createMenu({ menuId: "m" })).sort(), ["hide", "show"]);
  assert.deepEqual(Object.keys(GroupList.createMoveDialog({ modalId: "d" })).sort(), ["open", "wire"]);
});

test("공개 표면 — DataZone.create 반환 키 6종", (t) => {
  const dom = freshDom(t);
  const zone = createDataZone({ bridge: {} }).create(zoneCfg(dom));
  assert.deepEqual(Object.keys(zone).sort(),
    ["dropPendingEdits", "flushPendingEdits", "flushPendingSearch", "render", "sync", "wire"]);
});

test("파일당 export 는 하나 — export default 없음", () => {
  const EXPECTED = {
    grouplist: ["GroupList"], datazone: ["createDataZone"], pathtrack: ["createPathTrack"],
    relink: ["createRelink"], theme: ["createTheme"], personalization: ["createPersonalization"],
    sheet_picker: ["createSheetPicker"],
  };
  for (const f of FILES) {
    const src = read(f);
    assert.equal(/export\s+default/.test(src), false, `${f}: export default 금지`);
    const names = [...src.matchAll(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
    assert.deepEqual(names, EXPECTED[f], `${f}: export 는 하나뿐`);
  }
});

/* ================= 2. 의존은 명시적 import, Bridge 는 명시적 포트 ================= */

test("N-04 잎·N-05 서비스 의존이 명시적 import 다(별칭 없음)", () => {
  const EXPECTED = {
    grouplist: ['import { escHtml } from "./esc.js";', 'import { Popover } from "./popover.js";',
      'import { Modal } from "./modal.js";'],
    datazone: ['import { escHtml } from "./esc.js";', 'import { Popover } from "./popover.js";',
      'import { Intent } from "./intent.js";'],
    pathtrack: ['import { escHtml } from "./esc.js";'],
    relink: ['import { Modal } from "./modal.js";'],
    sheet_picker: ['import { escHtml } from "./esc.js";', 'import { Modal } from "./modal.js";'],
    theme: [], personalization: [],
  };
  for (const f of FILES) {
    const src = read(f);
    for (const line of EXPECTED[f]) assert.ok(src.includes(line), `${f}: ${line}`);
    const found = [...src.matchAll(/^import .*$/gm)].map((m) => m[0]);
    assert.deepEqual(found, EXPECTED[f], `${f}: import 목록이 계약과 동일`);
  }
});

test("음성 조건 — IIFE·자기 전역·제품 전역 조회·Object.assign(window) 전부 0", () => {
  const PRODUCT = /window\.(Modal|Popover|Bridge|Nav|escHtml|SheetPicker|PathTrack|Preserve|Intent|DataPicker|[A-Za-z]*Screen|__push|AppCloseGuard)\b/;
  for (const f of FILES) {
    const src = read(f);
    const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    assert.equal(/^\(function\s*\(/m.test(code), false, `${f}: top-level IIFE 금지`);
    assert.equal(/^\}\)\(\);/m.test(code), false, `${f}: top-level IIFE 금지`);
    assert.equal(/(window|globalThis)\.[A-Za-z_$][\w$]*\s*=[^=]/.test(code), false,
      `${f}: 자기 전역 생산 금지`);
    assert.equal(PRODUCT.test(code), false, `${f}: 제품 전역 조회 금지`);
    assert.equal(code.includes("Object.assign(window"), false, `${f}: Object.assign(window) 금지`);
  }
});

test("bridge 는 구조분해 인자로 받는 명시 포트 — 모듈 스코프에 메서드를 뽑지 않는다", () => {
  const FACTORY = {
    datazone: "createDataZone", pathtrack: "createPathTrack", relink: "createRelink",
    theme: "createTheme", personalization: "createPersonalization", sheet_picker: "createSheetPicker",
  };
  for (const [f, name] of Object.entries(FACTORY)) {
    const src = read(f);
    assert.ok(src.includes(`export function ${name}({ bridge }) {`), `${f}: ${name}({ bridge })`);
    // 모듈 스코프(들여쓰기 0)에서 bridge 를 만지면 팩토리 인자보다 먼저 평가돼 애초에 못 쓴다 —
    // 그래도 계측으로 못박는다: 프로브가 프로퍼티를 갈아끼우는 통로가 살아 있어야 한다.
    assert.equal(/^const\s+\w+\s*=\s*bridge\./m.test(src), false, `${f}: 모듈 스코프 캡처 금지`);
  }
  // grouplist 는 포트가 없다(§1-A 평범한 named export).
  assert.equal(read("grouplist").includes("bridge"), false);
});

test("datazone 의 요청 시점 캡처는 형태 그대로 포트로만 바뀌었다", () => {
  const src = read("datazone");
  assert.ok(src.includes("const dispatch = bridge.call;"));
  assert.ok(src.includes("const send = () => dispatch.call(bridge, SCREEN, action, body);"));
  assert.ok(src.includes("Intent.chained(cfg.chainKey, send)"));
});

/* ================= 3. 포트 프로퍼티 교체가 보인다(프로브 경로 생존) ================= */

test("포트 교체 — Theme 은 갈아끼운 bridge.setTheme 를 본다", (t) => {
  freshDom(t);
  const seen = [];
  const bridge = { setTheme: (v) => seen.push(["A", v]) };
  const theme = createTheme({ bridge });
  theme.set("dark");
  bridge.setTheme = (v) => seen.push(["B", v]);   // 프로브가 하는 일
  theme.set("light");
  assert.deepEqual(seen, [["A", "dark"], ["B", "light"]]);
});

test("포트 교체 — Personalization 은 갈아끼운 bridge.setFontScale 를 본다", (t) => {
  freshDom(t);
  const seen = [];
  const bridge = { setFontScale: (v) => seen.push(["A", v]), setMasterWidth: () => {} };
  const pers = createPersonalization({ bridge });
  pers.setFontScale("large");
  bridge.setFontScale = (v) => seen.push(["B", v]);
  pers.setFontScale("larger");
  assert.deepEqual(seen, [["A", "large"], ["B", "larger"]]);
});

test("포트 교체 — PathTrack 위임 핸들러는 갈아끼운 bridge.openPath 를 본다", async (t) => {
  const dom = freshDom(t);
  const seen = [];
  const bridge = { openPath: (p) => { seen.push(["A", p]); return ""; } };
  createPathTrack({ bridge });
  const onClick = dom.clicks()[0].fn;
  const el = new FakeEl("b");
  el.dataset.trackAct = "open";
  el.dataset.path = "P:\\a.hwpx";
  await onClick({ target: { closest: () => el } });
  bridge.openPath = (p) => { seen.push(["B", p]); return ""; };
  await onClick({ target: { closest: () => el } });
  assert.deepEqual(seen, [["A", "P:\\a.hwpx"], ["B", "P:\\a.hwpx"]]);
});

test("포트 교체 — Relink 는 갈아끼운 bridge.call/pickTemplatePath 를 본다", async (t) => {
  freshDom(t);
  const seen = [];
  const bridge = {
    pickTemplatePath: () => "T:\\t.hwpx",
    call: (s, a, p) => { seen.push(["A", s, a, p]); return { restated: "ok" }; },
  };
  const relink = createRelink({ bridge });
  assert.equal(await relink.relinkTemplate("job", "작업", () => {}), true);
  bridge.call = (s, a, p) => { seen.push(["B", s, a, p]); return { restated: "ok" }; };
  await relink.relinkTemplate("job", "작업", () => {});
  assert.deepEqual(seen.map((r) => r[0]), ["A", "B"]);
});

test("포트 교체 — SheetPicker 는 갈아끼운 bridge.loadDataSheet 를 본다", async (t) => {
  const dom = freshDom(t);
  const opened = patch(Modal, ["open", "close"], t);
  dom.ensure("sheetList"); dom.ensure("sheetModalFile"); dom.ensure("sheetCancel");
  const seen = [];
  const bridge = { loadDataSheet: (...a) => { seen.push(["A", ...a]); return { label: "L" }; } };
  const sp = createSheetPicker({ bridge });
  const payload = { name: "d.xlsx", path: "D:\\d.xlsx", sheets: [{ name: "S1", rows: 1, cols: 1 }] };

  const pick = (p) => {
    const list = dom.get("sheetList");
    const promise = sp.choose("job", p);
    const btn = new FakeEl("opt");
    btn.dataset.sheet = "S1";
    list.fire("click", { target: { closest: () => btn } });
    return promise;
  };
  assert.deepEqual(await pick(payload), { label: "L" });
  bridge.loadDataSheet = (...a) => { seen.push(["B", ...a]); return { label: "L2" }; };
  assert.deepEqual(await pick(payload), { label: "L2" });
  assert.deepEqual(seen.map((r) => r[0]), ["A", "B"]);
  assert.ok(opened.length >= 2);
});

test("포트 교체 — DataZone 의 **새** 요청은 갈아끼운 bridge.call 을 본다", async (t) => {
  const dom = freshDom(t);
  const seen = [];
  const bridge = { call: (...a) => { seen.push(["A", ...a]); return Promise.resolve({}); } };
  const zone = createDataZone({ bridge }).create(zoneCfg(dom));
  zone.sync({ has_data: true, filter: { search: "" } });
  dom.get("dzSearch").value = "가";
  await zone.flushPendingSearch();
  bridge.call = (...a) => { seen.push(["B", ...a]); return Promise.resolve({}); };
  dom.get("dzSearch").value = "나";
  await zone.flushPendingSearch();
  assert.deepEqual(seen.map((r) => [r[0], r[2], r[3]]),
    [["A", "filter_search", { text: "가" }], ["B", "filter_search", { text: "나" }]]);
});

/* ================= 4. datazone 요청 시점 dispatch 캡처 ================= */

test("DataZone — 요청 뒤 통로를 바꿔도 이미 붙든 통로로 나간다(큐 대기 중 교체 무시)", async (t) => {
  const dom = freshDom(t);
  const seen = [];
  const bridge = { call: (...a) => { seen.push(["captured", ...a]); return Promise.resolve({}); } };
  const zone = createDataZone({ bridge }).create({ ...zoneCfg(dom), chainKey: "n05-c-test" });
  zone.sync({ has_data: true, filter: { search: "" } });
  dom.get("dzSearch").value = "가";

  const inflight = zone.flushPendingSearch();          // 요청 시점에 통로를 붙든다
  bridge.call = (...a) => { seen.push(["late", ...a]); return Promise.resolve({}); };
  await inflight;                                      // 체인에서 풀릴 때 발신

  assert.deepEqual(seen.map((r) => r[0]), ["captured"]);
  // 붙든 통로는 **함수**지만 수신자는 bridge 객체다(dispatch.call(bridge, …)).
  assert.equal(seen[0][1], "job");
});

test("DataZone — 붙든 dispatch 의 this 는 bridge 객체다", async (t) => {
  const dom = freshDom(t);
  let receiver = null;
  const bridge = {
    call(...a) { receiver = this; return Promise.resolve({}); },
  };
  const zone = createDataZone({ bridge }).create({ ...zoneCfg(dom), chainKey: "n05-c-this" });
  zone.sync({ has_data: true, filter: { search: "" } });
  dom.get("dzSearch").value = "가";
  await zone.flushPendingSearch();
  assert.equal(receiver, bridge);
});

/* ================= 5. Theme/Personalization 영속 호출 인자 전수 ================= */

test("Theme — 영속은 bridge.setTheme 로, 정규화된 현재 값으로 나간다", (t) => {
  const dom = freshDom(t);
  const calls = [];
  const theme = createTheme({ bridge: { setTheme: (v) => calls.push(v) } });
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
  const theme = createTheme({ bridge: { setTheme: (v) => calls.push(v) } });
  assert.equal(theme.set("dark"), "dark");
  assert.deepEqual(calls, []);
  assert.deepEqual(dom.alerts, []);
});

test("Theme — 영속 throw 는 삼키지 않고 loud(window.alert)", (t) => {
  const dom = freshDom(t);
  const theme = createTheme({ bridge: { setTheme: () => { throw new Error("브리지 사망"); } } });
  theme.set("dark");
  assert.deepEqual(dom.alerts, ["브리지 사망"]);
});

test("Personalization — 영속 호출 인자 전수(클램프된 값이 나간다)", (t) => {
  freshDom(t);
  const calls = [];
  const pers = createPersonalization({
    bridge: {
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

/* ================= 6. SheetPicker settle-once ================= */

test("SheetPicker — 정산은 한 번뿐(선택 뒤 onClose 가 다시 와도 재해소 없음)", async (t) => {
  const dom = freshDom(t);
  const mlog = patch(Modal, ["open", "close"], t);
  dom.ensure("sheetList"); dom.ensure("sheetModalFile"); dom.ensure("sheetCancel");
  let loads = 0;
  const sp = createSheetPicker({
    bridge: { loadDataSheet: () => { loads += 1; return { label: "L" }; } },
  });
  const list = dom.get("sheetList");
  const promise = sp.choose("job", {
    name: "d.xlsx", path: "D:\\d.xlsx",
    sheets: [{ name: "S1", rows: 1, cols: 1 }, { name: "S2", rows: 2, cols: 2 }],
  });
  assert.equal(list.listeners("click").length, 1);

  const btn = new FakeEl("opt");
  btn.dataset.sheet = "S1";
  list.fire("click", { target: { closest: () => btn } });
  assert.deepEqual(await promise, { label: "L" });

  // 확정 즉시 클릭 통로가 걷혔다(이중 로드 방지) — 다시 때려도 로드가 안 늘어난다.
  assert.equal(list.listeners("click").length, 0);
  list.fire("click", { target: { closest: () => btn } });
  assert.equal(loads, 1);

  // Modal 의 onClose(=취소)가 뒤늦게 와도 settled 라 무시된다 — close 는 정산 때 1회뿐.
  const onClose = mlog.find((r) => r[0] === "open")[2].onClose;
  onClose(); onClose();
  assert.equal(mlog.filter((r) => r[0] === "close").length, 1);
  assert.deepEqual(await promise, { label: "L" });
});

test("SheetPicker — 취소(onClose)는 null 로 중단, 첫 시트 강등 없음", async (t) => {
  const dom = freshDom(t);
  const mlog = patch(Modal, ["open", "close"], t);
  dom.ensure("sheetList"); dom.ensure("sheetModalFile"); dom.ensure("sheetCancel");
  let loads = 0;
  const sp = createSheetPicker({ bridge: { loadDataSheet: () => { loads += 1; return {}; } } });
  const promise = sp.choose("job", { name: "d.xlsx", path: "p", sheets: [{ name: "S1", rows: 1, cols: 1 }] });
  mlog.find((r) => r[0] === "open")[2].onClose();
  assert.equal(await promise, null);
  assert.equal(loads, 0);
});

/* ================= 7. PathTrack 위임 리스너 ================= */

test("PathTrack — 위임 리스너는 1회, bubble phase(capture 인자 없음)", (t) => {
  const dom = freshDom(t);
  createPathTrack({ bridge: {} });
  const clicks = dom.clicks();
  assert.equal(clicks.length, 1);
  assert.equal(clicks[0].opts, undefined, "3번째 인자 없음 = bubble phase");
  assert.equal((dom.docListeners.get("pointerdown") || []).length, 0);
});

test("PathTrack — affordances 산출은 옛 마크업 그대로(속성 순서·이스케이프 포함)", (t) => {
  freshDom(t);
  const pt = createPathTrack({ bridge: {} });
  assert.equal(pt.affordances(""), "");
  assert.equal(pt.affordances(null), "");
  const html = pt.affordances('C:\\a&b<"x>.hwpx');
  assert.ok(html.startsWith('<span class="track-affords" title="C:\\a&amp;b&lt;&quot;x&gt;.hwpx">'));
  assert.equal((html.match(/data-track-act=/g) || []).length, 2, "기본은 열기·폴더보기 2개");
  assert.equal(html.includes('data-track-act="copy"'), false);
  assert.equal(
    (pt.affordances("p", { only: ["copy"] }).match(/data-track-act="copy"/g) || []).length, 1);
});

/* ================= 8. GroupList 팩토리 재사용 ================= */

test("GroupList — createMenu 를 표면마다 다시 불러도 서로 다른 메뉴를 소유한다", (t) => {
  const dom = freshDom(t);
  const plog = patch(Popover, ["place"], t);
  const a = dom.ensure("menuA"), b = dom.ensure("menuB");
  const menuA = GroupList.createMenu({ menuId: "menuA" });
  const menuB = GroupList.createMenu({ menuId: "menuB" });
  menuA.show("<button>A</button>", new FakeEl("btnA"));
  assert.equal(a.innerHTML, "<button>A</button>");
  assert.equal(a.style.display, "block");
  assert.equal(b.innerHTML, "");
  menuB.show("<button>B</button>", new FakeEl("btnB"));
  menuA.hide();
  assert.equal(a.innerHTML, "");
  assert.equal(a.style.display, "none");
  assert.equal(b.innerHTML, "<button>B</button>");
  assert.deepEqual(plog.map((r) => r[0]), ["place", "place"]);
});

test("GroupList — createMoveDialog 인스턴스는 자기 confirm 상태만 든다", (t) => {
  const dom = freshDom(t);
  const mlog = patch(Modal, ["open", "close"], t);
  for (const id of ["listA", "errA", "nameA", "newNameA", "listB", "errB", "nameB", "newNameB"]) dom.ensure(id);
  const cfgA = { modalId: "mA", listId: "listA", radioName: "rA", newRadioId: "nrA", newNameId: "newNameA", errId: "errA", nameId: "nameA" };
  const cfgB = { ...cfgA, modalId: "mB", listId: "listB", radioName: "rB", newRadioId: "nrB", newNameId: "newNameB", errId: "errB", nameId: "nameB" };
  const dlgA = GroupList.createMoveDialog(cfgA);
  const dlgB = GroupList.createMoveDialog(cfgB);
  const seen = [];
  dlgA.open({ groups: ["가"], current: "가", nameText: "작업A", onConfirm: (g) => seen.push(["A", g]) });
  dlgB.open({ groups: ["나"], current: "", nameText: "작업B", onConfirm: (g) => seen.push(["B", g]) });
  assert.ok(dom.get("listA").innerHTML.includes('name="rA"'));
  assert.ok(dom.get("listB").innerHTML.includes('name="rB"'));
  assert.equal(dom.get("nameA").textContent, "작업A");
  assert.equal(dom.get("nameB").textContent, "작업B");
  // 확정 없이 닫히면 onConfirm 은 안 나간다(H-16 순서 규약의 관측점).
  for (const r of mlog.filter((x) => x[0] === "open")) r[2].onClose();
  assert.deepEqual(seen, []);
});

test("GroupList — toggleGroup 은 낙관 반영 뒤 실패에 되돌리고 loud 하다", (t) => {
  const dom = freshDom(t);
  const btn = new FakeEl("g");
  btn.setAttribute("aria-expanded", "true");
  GroupList.toggleGroup(btn, () => { throw new Error("동기 실패"); }, "접힘 저장 실패");
  assert.equal(btn.getAttribute("aria-expanded"), "true", "동기 실패는 즉시 되돌린다");
  assert.deepEqual(dom.alerts, ["접힘 저장 실패\nError: 동기 실패"]);
});

/* ================= 9. 팩토리 2회 호출 = 독립 인스턴스 ================= */

test("팩토리를 두 번 부르면 독립 인스턴스가 나온다(중앙은 1회만 부른다)", async (t) => {
  const dom = freshDom(t);
  const seenA = [], seenB = [];
  const themeA = createTheme({ bridge: { setTheme: (v) => seenA.push(v) } });
  const themeB = createTheme({ bridge: { setTheme: (v) => seenB.push(v) } });
  assert.notEqual(themeA, themeB);
  themeA.set("dark");
  themeB.set("light");
  assert.deepEqual(seenA, ["dark"]);
  assert.deepEqual(seenB, ["light"]);

  // PathTrack: 두 인스턴스는 각각 자기 위임 리스너를 문서에 건다.
  createPathTrack({ bridge: {} });
  createPathTrack({ bridge: {} });
  assert.equal(dom.clicks().length, 2);

  // DataZone: 인스턴스 상태(LAST·앵커·디바운스)는 클로저에 갇혀 서로를 안 본다.
  const sentA = [], sentB = [];
  const zoneA = createDataZone({ bridge: { call: (...a) => { sentA.push(a); return Promise.resolve({}); } } })
    .create(zoneCfg(dom, "A"));
  const zoneB = createDataZone({ bridge: { call: (...a) => { sentB.push(a); return Promise.resolve({}); } } })
    .create(zoneCfg(dom, "B"));
  zoneA.sync({ has_data: true, filter: { search: "" } });
  dom.get("dzSearchA").value = "가";
  await zoneA.flushPendingSearch();
  await zoneB.flushPendingSearch();   // B 는 LAST 가 없어 아무것도 안 보낸다
  assert.equal(sentA.length, 1);
  assert.deepEqual(sentB, []);
});

test("DataZone — 모듈 스코프 가변 상태 0(인스턴스 상태는 create 클로저)", () => {
  const src = read("datazone");
  const head = src.slice(0, src.indexOf("export function createDataZone"));
  assert.equal(/^\s*(let|var)\s/m.test(head), false, "import 위 모듈 스코프에 가변 상태 없음");
  const factoryBody = src.slice(src.indexOf("export function createDataZone"), src.indexOf("  function create(cfg)"));
  assert.equal(/^\s*(let|var)\s/m.test(factoryBody), false, "팩토리 스코프에도 가변 상태 없음");
  for (const name of ["LAST", "panelCol", "panelData", "panelEpoch", "colTextTimer",
    "selAnchor", "selAnchorState", "lastTableKey", "searchTimer", "colTextPending"]) {
    assert.ok(new RegExp(`^\\s{4}let ${name}`, "m").test(src), `${name} 은 create 클로저 안`);
  }
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
