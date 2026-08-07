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
/* R4-02 — 시트 선택은 이 파일의 범위를 떠났다. legacy `sheet_picker.js` 가 삭제되면서
   "재사용 서비스 팩토리" 라는 이 파일의 주어에서 빠졌고, 후계 `src/screens/sheet_picker.ts`
   의 계약(확정 게이트·settle-once·취소의 의미)은 `r4_sheet_picker.test.js` 가 통째로 진다.
   여기 남기면 같은 성질을 두 곳이 재고, 한쪽만 늙는다. */
const { createJobReadController } = await import("../../frontend/src/screens/job_read.ts");
const { createScreenPorts } = await import("../../frontend/src/screens/ports.ts");
const { createServiceHandoffPorts } = await import("../../frontend/src/ports/service_handoff.ts");
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

const FILES = ["grouplist", "pathtrack", "relink", "theme", "personalization"];
const DATA_ZONE_SRC = fs.readFileSync(new URL("../../frontend/src/screens/data_zone.ts", import.meta.url), "utf8");
const JOB_READ_SRC = fs.readFileSync(new URL("../../frontend/src/screens/job_read.ts", import.meta.url), "utf8");

function reactZoneHarness(onDispatch) {
  const calls = [];
  const snapshot = { has_job: true, has_data: true, filter: { search: "" }, zone_epoch: 7 };
  const ports = createScreenPorts();
  ports.jobRunCoordination.bindLegacy({ confirmDestructiveIfArmed: async () => true, log() {} });
  ports.editorEntry.bindLegacy({
    openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {},
    confirmDiscard() {}, restoreEntryFocus() {},
  });
  const services = createServiceHandoffPorts();
  services.relink.bindLegacy({ relinkTemplate: async () => true });
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

  /* R4-02 — GroupList 표면은 `createMenu` 하나로 좁아졌다. `createMoveDialog` 는 React
     `screens/group_move_dialog.ts` 로 옮겨졌고(그 3 listener site 가 retirement 의 실물),
     `toggleGroup`·`setGroupExpanded` 는 #414 가 마지막 소비자를 걷어 간 뒤 죽은 export 라
     함께 절제됐다. 남은 이유는 소비자 둘(`libraryGroupMenu`·`tplRowMenu`)이고, 파일 자체의
     은퇴는 그 둘을 걷는 #417 이 진다. */
  assert.equal(typeof GroupList, "object");
  assert.deepEqual(Object.keys(GroupList).sort(), ["createMenu"]);

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

  assert.equal(typeof createJobReadController, "function");
  const rz = reactZoneHarness();
  assert.equal(typeof rz.controller.zone, "function");
  assert.equal(rz.ports.jobData.owner(), "react");
});

test("공개 표면 — GroupList 하위 팩토리 반환 키", (t) => {
  freshDom(t);
  assert.deepEqual(Object.keys(GroupList.createMenu({ menuId: "m" })).sort(), ["hide", "show"]);
});

test("공개 표면 — React JobDataCoordinator는 flushPendingEdits 하나만 낸다", (t) => {
  freshDom(t);
  const rz = reactZoneHarness();
  assert.deepEqual(Object.keys(rz.ports.jobData.current()), ["flushPendingEdits"]);
  assert.equal(rz.ports.jobData.current().flushPendingEdits, rz.controller.flushPendingEdits);
});

test("파일당 export 는 하나 — export default 없음", () => {
  const EXPECTED = {
    grouplist: ["GroupList"], pathtrack: ["createPathTrack"],
    relink: ["createRelink"], theme: ["createTheme"], personalization: ["createPersonalization"],
  };
  for (const f of FILES) {
    const src = read(f);
    assert.equal(/export\s+default/.test(src), false, `${f}: export default 금지`);
    const names = [...src.matchAll(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
    assert.deepEqual(names, EXPECTED[f], `${f}: export 는 하나뿐`);
  }
  assert.equal(/export\s+default/.test(DATA_ZONE_SRC), false);
  assert.deepEqual(
    [...DATA_ZONE_SRC.matchAll(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]),
    ["JobDataZone"],
  );
});

/* ================= 2. 의존은 명시적 import, Bridge 는 명시적 포트 ================= */

test("N-04 잎·N-05 서비스 의존이 명시적 import 다(별칭 없음)", () => {
  const EXPECTED = {
    /* `createMoveDialog` 절제로 `modal.js`·`esc.js` 두 간선이 함께 죽었다 — 남은
       `createMenu` 는 팝오버 배치만 쓴다(문안 이스케이프는 부르는 화면 몫). 간선이 줄어든
       것 자체가 이관이 실물이라는 증거다. */
    grouplist: ['import { Popover } from "./popover.js";'],
    pathtrack: ['import { escHtml } from "./esc.js";'],
    relink: ['import { Modal } from "./modal.js";'],
    theme: [], personalization: [],
  };
  for (const f of FILES) {
    const src = read(f);
    for (const line of EXPECTED[f]) assert.ok(src.includes(line), `${f}: ${line}`);
    const found = [...src.matchAll(/^import .*$/gm)].map((m) => m[0]);
    assert.deepEqual(found, EXPECTED[f], `${f}: import 목록이 계약과 동일`);
  }
  assert.equal(DATA_ZONE_SRC.includes('from "./job_read.ts"'), false,
    "producer↔controller 런타임 순환을 만들지 않는다");
  assert.ok(DATA_ZONE_SRC.includes("type JobReadController ="));
  assert.ok(DATA_ZONE_SRC.includes('from "react"'));
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
  assert.equal(/(?:window|globalThis)\.(?:Bridge|Modal|DataZone|JobScreen)\b/.test(DATA_ZONE_SRC), false);
});

test("bridge 는 구조분해 인자로 받는 명시 포트 — 모듈 스코프에 메서드를 뽑지 않는다", () => {
  const FACTORY = {
    pathtrack: "createPathTrack", relink: "createRelink",
    theme: "createTheme", personalization: "createPersonalization",
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

test("DataZone 요청은 JobRead controller의 단일 zone tail과 client port를 지난다", () => {
  assert.ok(JOB_READ_SRC.includes("const dispatch = deps.client.dispatch"));
  assert.ok(JOB_READ_SRC.includes("const next = zoneTail.then(send, send);"));
  assert.ok(JOB_READ_SRC.includes("zoneTail = next.then(() => undefined, () => undefined);"));
});

/* ================= 3. 포트 프로퍼티 교체가 보인다(프로브 경로 생존) ================= */

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

/* SheetPicker 의 같은 성질(갈아끼운 통로를 본다)은 `r4_sheet_picker.test.js` 가 잰다 —
   후계는 `bridge.loadDataSheet` 가 아니라 `client.invoke("load_data_sheet", …)` 를 지난다. */

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
  // N-07 — 호스트 준비 판정은 브리지가 진다. 프리뷰(호스트 부재)는 `hostReady()` 가 거짓인
  // 상태이고, 그 판정이 `window.pywebview` 직접 조회를 대신한다.
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

/* ================= 6. (은퇴) SheetPicker settle-once =================

   settle-once·취소의 의미·이중 로드 금지는 R4-02 에서 `r4_sheet_picker.test.js` 로 통째로
   옮겨졌다. 후계에서 「클릭 통로를 걷는다」는 리스너 해제가 아니라 **버튼 disabled +
   settled 플래그**로 서므로, 같은 성질을 재려면 관측점 자체가 달라야 한다. */

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

/* `createMoveDialog` 인스턴스 격리(자기 confirm 상태만 든다)의 후계는 React
   `GroupMoveDialog` 이고 `r4_editor.test.js` 가 잰다 — 그 dialog 는 이제 편집기 controller 가
   주입받는 표면이라 이 파일의 "재사용 서비스" 주어에 들지 않는다.

   `toggleGroup` 은 후계가 없다: #414 가 마지막 소비자(라이브러리 그룹 접힘)를 React 상태로
   번역하면서 「낙관 반영 → 실패 되돌림 → loud」 가 그쪽 controller 판정으로 흡수됐다.
   여기서 죽은 export 를 계속 재면 은퇴가 초록불 뒤에 숨는다. */

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

  // PathTrack: 두 인스턴스는 각각 자기 위임 리스너를 문서에 건다.
  createPathTrack({ bridge: {} });
  createPathTrack({ bridge: {} });
  assert.equal(dom.clicks().length, 2);

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

test("DataZone — 모듈 스코프 가변 상태 0(controller·hooks 안에만 상태)", () => {
  const zoneHead = DATA_ZONE_SRC.slice(0, DATA_ZONE_SRC.indexOf("export function JobDataZone"));
  const readHead = JOB_READ_SRC.slice(0, JOB_READ_SRC.indexOf("export function createJobReadController"));
  assert.equal(/^\s*(let|var)\s/m.test(zoneHead), false);
  assert.equal(/^\s*(let|var)\s/m.test(readHead), false);
  for (const name of ["zoneTail", "searchTimer", "columnTimer", "rangeApplied", "rangeForceClose"]) {
    assert.ok(new RegExp(`^\\s{2}let ${name}`, "m").test(JOB_READ_SRC), `${name}은 controller closure 안`);
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
