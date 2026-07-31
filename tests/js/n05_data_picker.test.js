/* 데이터 선택 다이얼로그(data_picker.js) ESM 전환의 특성화 테스트 — N-05 패킷 D.
 *
 * 기대값은 **전환 이전 동작**이다. 전환은 IIFE 껍질을 벗기고 `window.escHtml`·전역
 * `Bridge`·`SheetPicker`·`PathTrack`·`window.Modal` 조회를 import/주입으로 드러낸 기계적
 * 작업이므로, 이 파일이 초록이면 "껍질만 바뀌고 거동은 그대로"가 참이다. 유일한 의도적
 * 동작 추가는 `init()` 멱등(아래 전용 테스트에서 **차이 자체를 단언**한다).
 *
 * 정적 소스 대조가 못 보는 층이 이 파일의 존재 이유다:
 *
 * 1. **Escape 캡처 선점** — `open()` 은 `Modal.open` 보다 **먼저** document capture keydown 을
 *    건다. 같은 대상의 capture 리스너는 등록 순으로 실행되고 modal 의
 *    `stopImmediatePropagation` 은 자기 뒤만 막으므로, 마운트 진행 중 Escape 를 이 모듈이
 *    먼저 소비해 '가짜 취소'를 막는다(C8). `tests/test_r3_picker.py` 는 두 줄의 **텍스트
 *    순서**만 본다 — 실제로 modal 보다 먼저 서는지는 실행해야 보인다. 그래서 이 파일은
 *    Modal 을 대역으로 바꾸지 않고 **실물 modal.js 를 그대로** 쓴다.
 * 2. **포트 프로퍼티 교체 가시성** — Python selftest 프로브가 `window.Bridge.call = stub`
 *    으로 통로를 갈아끼운다(app.py). 메서드를 모듈 스코프 값으로 뽑으면 프로브가 우회돼
 *    실물 백엔드로 샌다 — 초록불인 채로.
 * 3. **init() 멱등** — `bridge.onPush` 는 채널당 배열 누적이라(bridge.js) 재호출이 덮어쓰기가
 *    아니라 2벌 등록이 된다. 전환 전에는 무가드였고, 전환본은 `wired` 가드를 넓혔다.
 *
 * DOM 은 node:test 만으로 돌리려고 손으로 세운 최소 스텁이다. **객체 정체성은 유지**한다 —
 * popover.js(modal.js 의 import 간선)가 모듈 평가 시점에 그 document 에 리스너를 걸어 두기
 * 때문에 새 객체로 갈아끼우면 검사 대상인 등록 순서 자체가 사라진다. 제품 전역
 * (window.Bridge·window.Modal…)은 한 번도 세우지 않는다.
 */
import { after, afterEach, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

/* ────────────────────────── 최소 DOM 스텁 ────────────────────────── */

function makeStyle() {
  const props = Object.create(null);
  return {
    props,
    setProperty(name, value) { props[name] = String(value); },
    removeProperty(name) { delete props[name]; },
    getPropertyValue(name) { return props[name] === undefined ? "" : props[name]; },
    get display() { return props.display === undefined ? "" : props.display; },
    set display(v) { props.display = String(v); },
  };
}

function selectorParts(compound) {
  return compound.match(/(\[[^\]]+\]|[.#]?[A-Za-z0-9_-]+)/g) || [];
}

function matchesCompound(el, compound) {
  return selectorParts(compound).every((part) => {
    if (part.startsWith("[")) return el.attributes.has(part.slice(1, -1));
    if (part.startsWith(".")) return el.classSet.has(part.slice(1));
    if (part.startsWith("#")) return el.id === part.slice(1);
    return el.tagName === part.toUpperCase();
  });
}

function matchesSelector(el, selector) {
  return String(selector).split(",").map((s) => s.trim()).filter(Boolean)
    .some((s) => matchesCompound(el, s));
}

const VISIBLE = { visible: true };

class StubElement {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.id = "";
    this.childNodes = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.classSet = new Set();
    this.textContent = "";
    this.innerHTML = "";
    this.value = "";
    this.readOnly = false;
    this.disabled = false;
    this.tabIndex = 0;
    this.offsetParent = VISIBLE;
    this.scrollTop = 0;
    this.scrollLeft = 0;
    this.style = makeStyle();
    this.dataset = {};
    this.listeners = new Map();
    const set = this.classSet;
    this.classList = {
      add: (...n) => n.forEach((x) => set.add(x)),
      remove: (...n) => n.forEach((x) => set.delete(x)),
      contains: (n) => set.has(n),
      toggle: (n, force) => {
        const want = force === undefined ? !set.has(n) : !!force;
        if (want) set.add(n); else set.delete(n);
        return want;
      },
    };
  }
  get className() { return [...this.classSet].join(" "); }
  set className(v) {
    this.classSet.clear();
    for (const c of String(v).split(/\s+/)) if (c) this.classSet.add(c);
  }
  get isConnected() {
    let n = this;
    while (n.parentNode) n = n.parentNode;
    return n === DOC_ROOT;
  }
  appendChild(child) {
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }
  contains(node) { for (let n = node; n; n = n.parentNode) if (n === this) return true; return false; }
  closest(sel) {
    for (let n = this; n instanceof StubElement; n = n.parentNode) {
      if (matchesSelector(n, sel)) return n;
    }
    return null;
  }
  matches(sel) { return matchesSelector(this, sel); }
  descendants(out = []) {
    for (const c of this.childNodes) { out.push(c); c.descendants(out); }
    return out;
  }
  querySelectorAll(sel) { return this.descendants().filter((n) => matchesSelector(n, sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  hasAttribute(n) { return this.attributes.has(n); }
  getAttribute(n) { return this.attributes.has(n) ? this.attributes.get(n) : null; }
  setAttribute(n, v) { this.attributes.set(n, String(v)); }
  addEventListener(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(fn);
  }
  removeEventListener(type, fn) {
    const l = this.listeners.get(type);
    if (!l) return;
    const at = l.indexOf(fn);
    if (at !== -1) l.splice(at, 1);
  }
  listenerCount(type) { return (this.listeners.get(type) || []).length; }
  focus() {
    if (this.disabled || !this.isConnected) return;
    for (let n = this; n instanceof StubElement; n = n.parentNode) if (n.classSet.has("hidden")) return;
    DOC.activeElement = this;
  }
}

function el(tag, spec = {}) {
  const node = new StubElement(tag);
  if (spec.id) node.id = spec.id;
  for (const c of spec.cls || []) node.classSet.add(c);
  for (const k of spec.kids || []) node.appendChild(k);
  return node;
}

const DOC_ROOT = new StubElement("html");
const DOC = {
  documentElement: DOC_ROOT,
  body: null,
  activeElement: null,
  listeners: new Map(),
  createElement: (t) => new StubElement(t),
  getElementById(id) { return DOC_ROOT.descendants().find((n) => n.id === id) || null; },
  querySelector(s) { return DOC_ROOT.querySelector(s); },
  querySelectorAll(s) { return DOC_ROOT.querySelectorAll(s); },
  addEventListener(type, fn) {
    if (!DOC.listeners.has(type)) DOC.listeners.set(type, []);
    DOC.listeners.get(type).push(fn);
  },
  removeEventListener(type, fn) {
    const l = DOC.listeners.get(type);
    if (!l) return;
    const at = l.indexOf(fn);
    if (at !== -1) l.splice(at, 1);
  },
  keydownListeners() { return (DOC.listeners.get("keydown") || []).slice(); },
};

const alerts = [];
const WIN = {
  alert: (t) => { alerts.push(String(t)); },
  addEventListener() {}, removeEventListener() {},
  innerWidth: 1280, innerHeight: 800,
};

globalThis.window = WIN;
globalThis.document = DOC;
after(() => { delete globalThis.window; delete globalThis.document; });

/** document capture → target 순으로 흘린다. 등록 순서가 곧 실행 순서다(검사 대상). */
function dispatch(target, type, props = {}) {
  const e = { type, target, ...props };
  e.defaultPrevented = false;
  let stoppedAll = false;
  e.preventDefault = () => { e.defaultPrevented = true; };
  e.stopPropagation = () => {};
  e.stopImmediatePropagation = () => { stoppedAll = true; e.immediateStopped = true; };
  for (const fn of (DOC.listeners.get(type) || []).slice()) {
    fn(e);
    if (stoppedAll) return e;
  }
  if (target instanceof StubElement) {
    for (const fn of (target.listeners.get(type) || []).slice()) {
      fn(e);
      if (stoppedAll) return e;
    }
  }
  return e;
}

const pressEscape = () => dispatch(DOC.activeElement || DOC.body, "keydown", { key: "Escape", keyCode: 0 });

/** modal.close 는 transitionend(또는 220ms 안전망)로 정착한다 — 전이를 즉시 흘린다. */
function flushClose(id) {
  const node = DOC.getElementById(id);
  const card = node && node.querySelector(".modal-card");
  if (card) dispatch(card, "transitionend", { propertyName: "opacity" });
}

const PICK_IDS = ["dataPickerNote", "dataPickerCurrent", "dataPickerPinned", "dataPickerDupes",
  "dataPickerCorrupt", "dataPickerClose", "dataPickerBrowse"];
const REG_IDS = ["poolRegTitle", "poolRegOk", "poolRegName", "poolRegPath", "poolRegSheet",
  "poolRegNote", "poolRegBrowse", "poolRegCancel"];

function buildFixture() {
  DOC_ROOT.childNodes.length = 0;
  DOC.listeners.clear();
  DOC.activeElement = null;
  alerts.length = 0;
  const card = (kids) => el("div", { cls: ["modal-card"], kids });
  const modal = (id, kids) => el("div", { id, cls: ["modal", "hidden"], kids: [card(kids)] });
  const body = el("body", {
    kids: [
      el("div", { id: "overlayRoot", kids: [
        modal("dataPickerModal", PICK_IDS.map((id) => el(id.endsWith("Close") || id.endsWith("Browse") ? "button" : "div", { id }))),
        modal("poolRegModal", REG_IDS.map((id) => el(/Name|Path|Sheet|Note/.test(id) ? "input" : "button", { id }))),
      ] }),
    ],
  });
  DOC_ROOT.appendChild(body);
  DOC.body = body;
}

/* ────────────────────── 실물 그래프 열기 ────────────────────── */

buildFixture();
const SRC_URL = new URL("../../frontend/js/data_picker.js", import.meta.url);
const SRC = readFileSync(SRC_URL, "utf8");

const mod = await import("../../frontend/js/data_picker.js");
const { Modal } = await import("../../frontend/js/modal.js");

/* ────────────────────── 포트 대역(주입) ────────────────────── */

function makePorts() {
  const log = [];
  const q = { call: [], pick: [], poolPick: [], sheet: [] };
  const take = (name) => {
    const v = q[name].length ? q[name].shift() : {};
    return typeof v === "function" ? v() : v;
  };
  const bridge = {
    subs: [],
    onPush(channel, fn) { log.push(["onPush", channel]); bridge.subs.push({ channel, fn }); },
    call(screen, action, payload) {
      log.push(["call", screen, action, payload]);
      return Promise.resolve(take("call"));
    },
    pickDataFile(screen) { log.push(["pickDataFile", screen]); return Promise.resolve(take("pick")); },
    pickPoolDataFile() { log.push(["pickPoolDataFile"]); return Promise.resolve(take("poolPick")); },
  };
  const sheetPicker = {
    choose(screen, payload) { log.push(["sheet", screen, payload.path]); return Promise.resolve(take("sheet")); },
  };
  const pathTrack = { affordances: (p) => { log.push(["affordances", p]); return "<T>"; } };
  const push = (channel, snap) => {
    for (const s of bridge.subs) if (s.channel === channel) s.fn(snap);
  };
  return { log, q, bridge, sheetPicker, pathTrack, push };
}

const ROW = (key, name, over) => Object.assign({
  key, name, kind: "excel", kind_label: "엑셀/CSV", status: "active",
  badge_label: "활성", badge_level: "ok", reference: `C:/d/${name}.xlsx`,
  locate_path: `C:/d/${name}.xlsx`, sheet: "물품", missing: false, note: "", actions: [],
}, over || {});
const SNAP = { rows: [ROW("k1", "가"), ROW("k2", "나")], corrupted: [], duplicates: [], result: {} };
const CUR_FILE = { label: "대장.xlsx", detail: "3건", path: "C:/대장.xlsx", sheet: "물품", origin: "file" };

const tick = () => new Promise((r) => setTimeout(r, 0));
const settle = async () => { for (let i = 0; i < 6; i++) await tick(); };

beforeEach(() => buildFixture());
afterEach(() => {
  // 열린 모달을 걷어 document capture 리스너 누수를 다음 테스트로 넘기지 않는다.
  for (const id of ["poolRegModal", "dataPickerModal"]) { Modal.close(id); flushClose(id); }
});

/* ══════════════ 1. 공개 표면 ══════════════ */

test("공개 표면 — createDataPicker({bridge, sheetPicker, pathTrack}) → {init, open}", () => {
  assert.deepEqual(Object.keys(mod).sort(), ["createDataPicker"]);
  assert.equal(typeof mod.createDataPicker, "function");
  const p = mod.createDataPicker(makePorts());
  assert.deepEqual(Object.keys(p).sort(), ["init", "open"]);
  assert.equal(typeof p.init, "function");
  assert.equal(typeof p.open, "function");
});

test("파일당 export 는 하나 — export default 없음", () => {
  assert.equal(/export\s+default/.test(SRC), false, "export default 금지");
  const names = [...SRC.matchAll(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  assert.deepEqual(names, ["createDataPicker"]);
});

/* ══════════════ 2. 의존이 명시 간선(import)·명시 주입인가 ══════════════ */

test("esc·Modal·Preserve 는 명시 import 간선이다(별칭 없음, 계약 §1-C 그대로)", () => {
  const found = [...SRC.matchAll(/^import .*$/gm)].map((m) => m[0]);
  assert.deepEqual(found, [
    'import { escHtml } from "./esc.js";',
    'import { Modal } from "./modal.js";',
    'import { Preserve } from "./preserve.js";',
  ]);
  // 지역 별칭(esc)은 유지하되 원천은 import 다 — window.escHtml 재조회가 남으면 안 된다.
  assert.ok(SRC.includes("const esc = escHtml;"));
});

test("bridge·sheetPicker·pathTrack 은 구조분해 주입 — 모듈 스코프 캡처 없음", () => {
  assert.ok(SRC.includes("export function createDataPicker({ bridge, sheetPicker, pathTrack }) {"));
  // 프로퍼티 교체 프로브가 살아 있어야 한다: 메서드를 값으로 뽑아 두면 스텁이 우회된다.
  for (const port of ["bridge", "sheetPicker", "pathTrack"]) {
    assert.equal(new RegExp(`^\\s*const\\s+\\w+\\s*=\\s*${port}\\.`, "m").test(SRC), false,
      `${port}: 메서드를 값으로 뽑지 않는다`);
  }
});

test("음성 조건 — IIFE·자기 전역·제품 전역 조회·Object.assign(window) 전부 0", () => {
  const PRODUCT = /window\.(Modal|Popover|Bridge|Nav|escHtml|SheetPicker|PathTrack|Preserve|Intent|DataPicker|[A-Za-z]*Screen|__push|AppCloseGuard)\b/;
  const code = SRC.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.equal(/^\(function\s*\(/m.test(code), false, "top-level IIFE 금지");
  assert.equal(/^\}\)\(\);/m.test(code), false, "top-level IIFE 금지");
  assert.equal(/(window|globalThis)\.[A-Za-z_$][\w$]*\s*=[^=]/.test(code), false, "자기 전역 생산 금지");
  assert.equal(PRODUCT.test(code), false, "제품 전역 조회 금지");
  assert.equal(code.includes("Object.assign(window"), false, "Object.assign(window) 금지");
  // 표준 Web API 는 그대로 산다(전환의 대상이 아니다).
  assert.equal((code.match(/window\.alert\(/g) || []).length, 2, "loud 실패 재진술은 그대로");
});

test("모듈 스코프 가변 상태는 4개 그대로(LAST·session·loading·wired)", () => {
  // test_web_dom_contract 의 MUTABLE_MODULE_STATE_BUDGET["data_picker.js"] == 4 와 같은 계측:
  // 팩토리 본문이 옛 IIFE 본문과 같은 2칸 들여쓰기라 파이썬 쪽 정규식도 그대로 이 넷을 센다.
  const body = SRC.replace(/\/\*[\s\S]*?\*\//g, "");
  const names = [...body.matchAll(/^ {2}(?:let|var)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  assert.deepEqual(names, ["LAST", "session", "loading", "wired"]);
});

/* ══════════════ 3. init() 멱등 — 이번 전환의 유일한 의도적 동작 추가 ══════════════ */

test("init() 을 두 번 불러도 bridge.onPush 는 1회, DOM 배선도 1벌", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  picker.init();
  picker.init();

  assert.deepEqual(ports.log.filter((r) => r[0] === "onPush"), [["onPush", "pool"]]);
  assert.equal(ports.bridge.subs.length, 1);
  for (const id of ["dataPickerClose", "dataPickerBrowse", "dataPickerPinned",
    "dataPickerDupes", "dataPickerCurrent", "poolRegCancel", "poolRegOk", "poolRegBrowse"]) {
    assert.equal(DOC.getElementById(id).listenerCount("click"), 1, `${id}: 리스너 1벌`);
  }
});

test("init() 2회 뒤 푸시 1회에 render 도 1회만 돈다(누적 구독 회귀 그물)", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  ports.push("pool", SNAP);
  // 행 2건 × 렌더 1회 = affordances 2회. 구독이 2벌이면 4회가 된다.
  assert.equal(ports.log.filter((r) => r[0] === "affordances").length, 2);
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

test("open() 이 먼저 와도 배선은 1벌이고 클릭 왕복은 살아 있다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  picker.init();
  await settle();
  assert.equal(DOC.getElementById("dataPickerBrowse").listenerCount("click"), 1);
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

/* ══════════════ 4. Escape 캡처 선점 — 실물 Modal 과 함께 ══════════════ */

test("open() 의 capture keydown 은 Modal 의 것보다 **먼저** 선다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  assert.equal(DOC.keydownListeners().length, 0, "열기 전에는 캡처 리스너가 없다");
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  const listeners = DOC.keydownListeners();
  assert.equal(listeners.length, 2, "data_picker + modal 둘뿐");
  // 첫 리스너가 data_picker 것이라는 사실을 **기능으로** 확인한다(이름 대조가 아니라).
  // Modal 의 onKeydown 은 항상 preventDefault 를 한다. loading 이 아닐 때 첫 리스너만
  // 돌려보면 아무 일도 없어야 한다 — 그것이 onEscCapture 의 현행 의미다.
  const probe = { key: "Escape", keyCode: 0, defaultPrevented: false };
  probe.preventDefault = () => { probe.defaultPrevented = true; };
  probe.stopImmediatePropagation = () => { probe.stopped = true; };
  listeners[0](probe);
  assert.equal(probe.defaultPrevented, false, "첫 리스너는 modal 이 아니다(loading 아님 → no-op)");
  assert.equal(DOC.getElementById("dataPickerModal").classList.contains("hidden"), false);
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

test("마운트 진행 중 Escape 는 preventDefault + stopImmediatePropagation 으로 소비되고 면이 안 닫힌다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();

  let release;
  ports.q.pick.push(() => new Promise((r) => { release = r; }));
  const inflight = DOC.getElementById("dataPickerBrowse").listeners.get("click")[0]();
  await tick();

  const e = pressEscape();
  assert.equal(e.defaultPrevented, true, "Escape 를 소비하지 않았다");
  assert.equal(e.immediateStopped, true, "stopImmediatePropagation 이 없으면 Modal 이 닫아 '가짜 취소'");
  assert.equal(DOC.getElementById("dataPickerModal").classList.contains("is-closing"), false);
  assert.equal(DOC.getElementById("dataPickerNote").textContent,
    "⚠ 불러오는 중입니다. 끝날 때까지 닫을 수 없습니다.");
  assert.equal(DOC.getElementById("dataPickerNote").className, "note dangerbox");

  // 닫기 버튼도 같은 가드를 탄다(닫힘=onClose=취소 경로 봉쇄).
  DOC.getElementById("dataPickerClose").listeners.get("click")[0]();
  assert.equal(DOC.getElementById("dataPickerModal").classList.contains("is-closing"), false);

  release(null);
  await inflight; await settle();

  // 양성 대조 — loading 이 풀리면 같은 Escape 가 실제로 면을 닫는다.
  const e2 = pressEscape();
  assert.equal(e2.defaultPrevented, true);
  assert.equal(DOC.getElementById("dataPickerModal").classList.contains("is-closing"), true);
  flushClose("dataPickerModal");
  assert.equal(await closed, null, "마운트 없는 닫힘 = 중단");
});

/* ══════════════ 5. 마운트·해소·세션 ══════════════ */

test("고정 목록 선택 성사 — 면이 닫히고 라벨로 해소되며 onLoaded 가 그 라벨을 받는다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  const loaded = [];
  ports.q.call.push({ ok: true });
  const closed = picker.open({
    screen: "job", current: CUR_FILE, onLoaded: (l) => loaded.push(l),
  });
  await settle();
  ports.push("pool", SNAP);
  ports.q.call.push({ ok: true, label: "라벨-가" });
  DOC.getElementById("dataPickerPinned").listeners.get("click")[0]({
    target: { closest: () => ({ dataset: { act: "use", key: "k1", name: "가" }, disabled: false }) },
  });
  await settle();
  flushClose("dataPickerModal");
  assert.deepEqual(ports.log.filter((r) => r[0] === "call").at(-1),
    ["call", "job", "load_pool", { key: "k1" }]);
  assert.deepEqual(loaded, ["라벨-가"]);
  assert.equal(await closed, "라벨-가");
  assert.equal(DOC.getElementById("dataPickerModal").classList.contains("hidden"), true);
});

test("마운트 실패는 면을 닫지 않고 상태줄에 재진술한다(계약면 4)", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  ports.push("pool", SNAP);
  ports.q.call.push({ ok: false, error: "나라 소스는 동결입니다" });
  DOC.getElementById("dataPickerPinned").listeners.get("click")[0]({
    target: { closest: () => ({ dataset: { act: "use", key: "k2", name: "나" }, disabled: false }) },
  });
  await settle();
  assert.equal(DOC.getElementById("dataPickerModal").classList.contains("hidden"), false, "면 유지");
  assert.equal(DOC.getElementById("dataPickerNote").textContent, "⚠ 나라 소스는 동결입니다");
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

test("찾아보기 성사는 면을 유지하고, 그 뒤 닫힘이 마운트 라벨로 해소된다(U2 §2.7 1행)", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: {} });
  await settle();
  ports.q.pick.push({ label: "새.xlsx", rows: 12, path: "C:/새.xlsx", sheet: "S1" });
  await DOC.getElementById("dataPickerBrowse").listeners.get("click")[0]();
  await settle();
  assert.equal(DOC.getElementById("dataPickerModal").classList.contains("hidden"), false, "면 유지");
  const cur = DOC.getElementById("dataPickerCurrent").innerHTML;
  assert.ok(cur.includes("새.xlsx") && cur.includes('id="dataPickerPin"'), "현재 데이터 재진술 + 고정 버튼");
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, "새.xlsx");
});

test("다중 시트 게이트 — needs_sheet 는 sheetPicker 로, 취소는 중단(면 유지)", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: {} });
  await settle();
  ports.q.pick.push({ needs_sheet: true, path: "C:/다중.xlsx", name: "다중.xlsx", sheets: [] });
  ports.q.sheet.push(null);
  await DOC.getElementById("dataPickerBrowse").listeners.get("click")[0]();
  await settle();
  assert.deepEqual(ports.log.filter((r) => r[0] === "sheet"), [["sheet", "job", "C:/다중.xlsx"]]);
  assert.equal(DOC.getElementById("dataPickerNote").textContent,
    "시트 선택을 취소했습니다 — 데이터는 그대로입니다.");
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null, "시트 취소는 마운트 없음");
});

test("confirmSwap 거절 — 읽기 자체가 일어나지 않는다(가드 순서 §10.7.2 D)", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({
    screen: "job", current: CUR_FILE, confirmSwap: () => Promise.resolve(false),
  });
  await settle();
  ports.push("pool", SNAP);
  DOC.getElementById("dataPickerPinned").listeners.get("click")[0]({
    target: { closest: () => ({ dataset: { act: "use", key: "k1", name: "가" }, disabled: false }) },
  });
  await settle();
  assert.equal(ports.log.some((r) => r[0] === "call" && r[2] === "load_pool"), false);
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

test("재열기 — 회차가 갈리고 캡처 리스너·해소가 누수 없이 정리된다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();

  ports.q.call.push({ ok: true });
  const first = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  assert.equal(DOC.keydownListeners().length, 2);
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await first, null);
  assert.equal(DOC.keydownListeners().length, 0, "닫힘에서 두 캡처가 모두 걷힌다");

  ports.q.call.push({ ok: true });
  const second = picker.open({ screen: "job", current: {} });
  await settle();
  assert.equal(DOC.keydownListeners().length, 2, "재열기에도 1벌씩만");
  assert.equal(DOC.getElementById("dataPickerClose").listenerCount("click"), 1, "배선은 여전히 1벌");
  assert.equal(DOC.getElementById("dataPickerCurrent").innerHTML,
    '<p class="muted capnote">아직 데이터가 없습니다. 아래에서 고르세요.</p>', "회차 격리");
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await second, null);
});

test("닫힌 채 도착한 푸시는 값만 보관하고 다음 열기에 반영된다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.push("pool", SNAP);          // 닫힌 상태 — 재렌더 없음
  assert.equal(DOC.getElementById("dataPickerPinned").innerHTML, "");
  assert.equal(ports.log.filter((r) => r[0] === "affordances").length, 0);
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  assert.ok(DOC.getElementById("dataPickerPinned").innerHTML.includes('data-act="use"'), "열 때 반영");
  await settle();
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

/* ══════════════ 6. 스택 모달(고정 다이얼로그) ══════════════ */

test("「이 데이터 고정」은 이 면 **위에** 스택으로 뜨고 Escape 는 위쪽만 닫는다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  DOC.getElementById("dataPickerCurrent").listeners.get("click")[0]({
    target: { closest: (sel) => (sel === "#dataPickerPin" ? { id: "dataPickerPin" } : null) },
  });
  assert.equal(DOC.getElementById("poolRegModal").classList.contains("hidden"), false);
  assert.equal(DOC.getElementById("poolRegTitle").textContent, "이 데이터 고정");
  assert.equal(DOC.getElementById("poolRegOk").textContent, "고정");
  assert.equal(DOC.getElementById("poolRegPath").value, "C:/대장.xlsx");
  assert.equal(DOC.getElementById("poolRegPath").readOnly, true, "pin 은 참조를 잠근다");
  assert.equal(DOC.getElementById("poolRegBrowse").style.display, "none");

  pressEscape();
  flushClose("poolRegModal");
  assert.equal(DOC.getElementById("poolRegModal").classList.contains("hidden"), true);
  assert.equal(DOC.getElementById("dataPickerModal").classList.contains("hidden"), false, "아래 면은 산다");

  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

test("등록 확정 — 덮어쓰기 재진술은 Modal.confirm 왕복, 거절은 조용히 덮지 않는다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  DOC.getElementById("dataPickerCurrent").listeners.get("click")[0]({
    target: { closest: (sel) => (sel === "#dataPickerPin" ? { id: "dataPickerPin" } : null) },
  });
  DOC.getElementById("poolRegName").value = "7월 대장";

  const saved = Modal.confirm;
  const seen = [];
  Modal.confirm = (opts) => { seen.push(opts); return Promise.resolve(false); };
  try {
    ports.q.call.push({ needs_confirm: true, confirm_text: "같은 데이터가 이미 있습니다", basis: "B1" });
    await DOC.getElementById("poolRegOk").listeners.get("click")[0]();
    await settle();
  } finally { Modal.confirm = saved; }

  assert.equal(seen.length, 1);
  assert.equal(seen[0].body, "같은 데이터가 이미 있습니다\n\n계속할까요?");
  assert.equal(seen[0].confirmLabel, "덮어쓰기");
  assert.equal(seen[0].danger, true);
  const calls = ports.log.filter((r) => r[0] === "call" && r[2] === "register_excel");
  assert.equal(calls.length, 1, "거절했으므로 2차 확정은 나가지 않는다");
  assert.equal(DOC.getElementById("poolRegModal").classList.contains("hidden"), false, "입력 보존");

  Modal.close("poolRegModal"); flushClose("poolRegModal");
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

test("등록 거절(ok:false)·throw 는 loud 재진술하고 모달을 열어 둔다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  DOC.getElementById("dataPickerCurrent").listeners.get("click")[0]({
    target: { closest: (sel) => (sel === "#dataPickerPin" ? { id: "dataPickerPin" } : null) },
  });
  ports.q.call.push({ ok: false, error: "이름이 비었습니다" });
  await DOC.getElementById("poolRegOk").listeners.get("click")[0]();
  await settle();
  ports.q.call.push(() => Promise.reject(new Error("등록 사망")));
  await DOC.getElementById("poolRegOk").listeners.get("click")[0]();
  await settle();
  assert.deepEqual(alerts, ["이름이 비었습니다", "등록 사망"]);
  assert.equal(DOC.getElementById("poolRegModal").classList.contains("hidden"), false);
  Modal.close("poolRegModal"); flushClose("poolRegModal");
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

test("다시 연결 — 같은 슬롯 참조 교체로 나가고 경로는 편집 가능하다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  ports.push("pool", { rows: [ROW("k1", "가", { missing: true, note: "메모" })], corrupted: [], duplicates: [], result: {} });
  DOC.getElementById("dataPickerPinned").listeners.get("click")[0]({
    target: { closest: () => ({ dataset: { act: "relink", key: "k1", name: "가" }, disabled: false }) },
  });
  await settle();
  assert.equal(DOC.getElementById("poolRegTitle").textContent, "데이터 다시 연결");
  assert.equal(DOC.getElementById("poolRegPath").readOnly, false, "relink 는 경로 편집 유지");
  assert.equal(DOC.getElementById("poolRegBrowse").style.display, "");
  DOC.getElementById("poolRegPath").value = "D:/새.xlsx";
  ports.q.call.push({ ok: true });
  await DOC.getElementById("poolRegOk").listeners.get("click")[0]();
  await settle();
  const last = ports.log.filter((r) => r[0] === "call").at(-1);
  assert.equal(last[2], "relink");
  assert.equal(last[3].key, "k1");
  assert.equal(last[3].path, "D:/새.xlsx");
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

/* ══════════════ 7. 포트 프로퍼티 교체가 보인다(프로브 경로 생존) ══════════════ */

test("포트 교체 — bridge.call 을 갈아끼우면 **새 함수**가 불린다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  const seen = [];
  ports.bridge.call = (s, a, p) => { seen.push(["A", a]); return Promise.resolve({ ok: true }); };
  const first = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  await first;

  ports.bridge.call = (s, a, p) => { seen.push(["B", a]); return Promise.resolve({ ok: true }); };
  const second = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  await second;
  assert.deepEqual(seen, [["A", "refresh"], ["B", "refresh"]]);
});

test("포트 교체 — bridge.pickDataFile·sheetPicker.choose·pathTrack.affordances 전부", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  const seen = [];
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();

  ports.bridge.pickDataFile = () => { seen.push("pick-B"); return Promise.resolve(null); };
  await DOC.getElementById("dataPickerBrowse").listeners.get("click")[0]();
  await settle();

  ports.sheetPicker.choose = () => { seen.push("sheet-B"); return Promise.resolve(null); };
  ports.bridge.pickDataFile = () => Promise.resolve({ needs_sheet: true, path: "p", name: "n", sheets: [] });
  await DOC.getElementById("dataPickerBrowse").listeners.get("click")[0]();
  await settle();

  ports.pathTrack.affordances = (p) => { seen.push("track-B"); return ""; };
  ports.push("pool", { rows: [ROW("k1", "가")], corrupted: [], duplicates: [], result: {} });

  ports.bridge.pickPoolDataFile = () => { seen.push("poolpick-B"); return Promise.resolve("Z:/x.xlsx"); };
  await DOC.getElementById("poolRegBrowse").listeners.get("click")[0]();
  await settle();

  assert.deepEqual(seen, ["pick-B", "sheet-B", "track-B", "poolpick-B"]);
  assert.equal(DOC.getElementById("poolRegPath").value, "Z:/x.xlsx");
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

test("포트 교체 — bridge.onPush 로 등록된 render 는 그 회차의 통로에 매이지 않는다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  // 프로브가 통로를 갈아끼운 뒤에도 이미 등록된 render 는 정상 동작한다(스냅샷 소비).
  ports.bridge.call = () => Promise.resolve({});
  ports.push("pool", { rows: [], corrupted: [{ file: "broken.json", error: "깨짐" }],
    duplicates: [], result: { text: "손상 1건", level: "danger" } });
  assert.ok(DOC.getElementById("dataPickerCorrupt").innerHTML.includes("broken.json"));
  assert.equal(DOC.getElementById("dataPickerCorrupt").style.display, "");
  assert.equal(DOC.getElementById("dataPickerNote").textContent, "손상 1건");
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

/* ══════════════ 8. 수명 관리·중복 정리(파괴 확정 왕복) ══════════════ */

test("삭제는 재진술(needs_confirm) → 확인 뒤에만 2차 확정이 지문(basis)과 함께 나간다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  ports.push("pool", SNAP);

  const saved = Modal.confirm;
  const seen = [];
  Modal.confirm = (opts) => { seen.push(opts); return Promise.resolve(true); };
  try {
    ports.q.call.push({ needs_confirm: true, confirm_text: "3건이 사라집니다", basis: "B7" });
    ports.q.call.push({ ok: true });
    DOC.getElementById("dataPickerPinned").listeners.get("click")[0]({
      target: { closest: () => ({ dataset: { act: "delete", key: "k1", name: "가" }, disabled: false }) },
    });
    await settle();
  } finally { Modal.confirm = saved; }

  assert.equal(seen[0].body, "3건이 사라집니다\n\n삭제할까요?");
  assert.equal(seen[0].confirmLabel, "삭제");
  assert.equal(seen[0].danger, true);
  const dels = ports.log.filter((r) => r[0] === "call" && r[2] === "delete");
  assert.deepEqual(dels.map((r) => r[3]), [{ key: "k1" }, { key: "k1", confirm: true, basis: "B7" }]);
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

test("중복 등록 정리도 같은 2단 왕복이고, 실패는 상태줄로 재진술된다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  ports.push("pool", { rows: [], corrupted: [],
    duplicates: [{ reference: "R", entries: [{ key: "k1", name: "가" }, { key: "k2", name: "나" }] }],
    result: {} });
  assert.ok(DOC.getElementById("dataPickerDupes").innerHTML.includes('data-dup-keep="k1"'));

  ports.q.call.push(() => Promise.reject(new Error("정리 거절")));
  DOC.getElementById("dataPickerDupes").listeners.get("click")[0]({
    target: { closest: () => ({ dataset: { dupKeep: "k1" } }) },
  });
  await settle();
  assert.equal(DOC.getElementById("dataPickerNote").textContent, "⚠ 정리 거절");
  assert.equal(DOC.getElementById("dataPickerModal").classList.contains("hidden"), false);
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

test("비활성 행 버튼·비버튼 클릭은 왕복을 만들지 않는다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  ports.push("pool", SNAP);
  const before = ports.log.filter((r) => r[0] === "call").length;
  const pinned = DOC.getElementById("dataPickerPinned").listeners.get("click")[0];
  pinned({ target: { closest: () => ({ dataset: { act: "use", key: "k1" }, disabled: true }) } });
  pinned({ target: { closest: () => null } });
  await settle();
  assert.equal(ports.log.filter((r) => r[0] === "call").length, before);
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

/* ══════════════ 9. 렌더 — 보관·끊김 항목은 숨기지 않고 비활성 + 사유 ══════════════ */

test("보관·끊김 항목은 목록에 남고 비활성 + 사유 병기(§10.7.2 C)", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  ports.push("pool", {
    rows: [
      ROW("k1", "보관분", { status: "archived", actions: [{ key: "activate", label: "활성화" }] }),
      ROW("k2", "끊긴것", { missing: true }),
      ROW("k3", '이스케이프"&<>'),
    ],
    corrupted: [], duplicates: [], result: {},
  });
  const html = DOC.getElementById("dataPickerPinned").innerHTML;
  assert.ok(html.includes('data-act="activate"'), "활성화 동사에 도달 가능");
  assert.ok(html.includes("보관 항목입니다 — [활성화] 뒤에 쓸 수 있습니다"));
  assert.ok(html.includes("참조가 끊겼습니다 — [다시 연결] 뒤에 쓸 수 있습니다"));
  assert.ok(html.includes("이스케이프&quot;&amp;&lt;&gt;"), "escHtml 이 실제로 물려 있다");
  assert.equal((html.match(/disabled title=/g) || []).length, 2);
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

test("빈 풀·풀 미도착은 서로 다른 문구로 정직하게 말한다", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push({ ok: true });
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  assert.ok(DOC.getElementById("dataPickerPinned").innerHTML.includes("고정한 데이터를 읽는 중…"));
  await settle();
  ports.push("pool", { rows: [], corrupted: [], duplicates: [], result: {} });
  assert.ok(DOC.getElementById("dataPickerPinned").innerHTML.includes("고정한 데이터가 없습니다"));
  assert.equal(DOC.getElementById("dataPickerDupes").style.display, "none");
  assert.equal(DOC.getElementById("dataPickerCorrupt").style.display, "none");
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});

test("풀 재스캔 거절은 삼키지 않고 상태줄로(N1) — 면은 열린 채", async () => {
  const ports = makePorts();
  const picker = mod.createDataPicker(ports);
  picker.init();
  ports.q.call.push(() => Promise.reject(new Error("브리지 사망")));
  const closed = picker.open({ screen: "job", current: CUR_FILE });
  await settle();
  assert.equal(DOC.getElementById("dataPickerNote").textContent,
    "⚠ 고정한 데이터를 읽을 수 없습니다: 브리지 사망");
  assert.equal(DOC.getElementById("dataPickerModal").classList.contains("hidden"), false);
  Modal.close("dataPickerModal"); flushClose("dataPickerModal");
  assert.equal(await closed, null);
});
