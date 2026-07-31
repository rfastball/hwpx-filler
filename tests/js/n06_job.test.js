/* N-06 lane D — 「문서 만들기」 화면(job.js)의 ESM factory 전환 계약 테스트.
 *
 * 이 파일이 실측하는 것(중앙 계약 「전용 테스트」 6항):
 *
 *  ① 공개 표면 12키 — factory 반환 객체의 키 집합·순서·타입이 계약 표와 정확히 같다.
 *  ② init 멱등 — 성공한 init 재호출에서 DOM listener·Bridge.onPush·initial 당김의
 *     추가 등록이 **실측 delta 0** 이다(소스 call-site 수를 기대값으로 쓰지 않는다).
 *  ③ 동시 init 공유 + 첫 initial reject 후 명시적 재-init 회복(listener 중복 0,
 *     rejection 은 호출자에게 전파 — 조용히 삼키지 않는다).
 *  ④ 교차 화면 콜백 `EditorScreen.aimAt` — 미리보기 수선 진입 성사 뒤에만 호출되고,
 *     **late-binding**(factory 구성 뒤에 갈아끼운 콜백이 호출 시점에 잡힌다)이다.
 *     Nav 도 주입 콜백 테이블로 산다(openJob → Nav.go).
 *  ⑤ 음성 — 소스에 IIFE 래퍼 0 · 제품 전역 27종의 window./globalThis. 참조 0(주석 포함) ·
 *     export 정확히 1개 · export default 0 · 화면 간/app/bridge import 0.
 *  ⑥ Bridge 는 객체째 — `Bridge.call = stub` 프로퍼티 교체가 다음 호출에서 관측된다
 *     (메서드 사전 추출이 없다는 것을 실행으로 확인 — Python selftest 의 스텁 계약).
 *
 * 임포트 그래프(modal → popover)는 평가 시점에 document 를 만진다(N-05 계약: 부작용을
 * init 으로 옮기지 않는다). 그래서 정적 import 대신 전역 DOM 대역을 먼저 깔고 동적
 * import 로 연다. 대역은 표준 Web API 만 흉내 내고 제품 전역은 세우지 않는다. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC_URL = new URL("../../frontend/js/screens/job.js", import.meta.url);
const SRC = readFileSync(SRC_URL, "utf8");

/* 계약 §1 표 — 공개 표면 12키, 리터럴 배치 순서 그대로. */
const SURFACE = [
  "init", "overwriteBody", "guardBody", "resultExitLine", "confirmDataSwapIfArmed",
  "openJob", "refreshList", "openJobDataSheet", "openBrowseNeedsAction", "openPreview",
  "renderResult", "markResultStale",
];

/* 제품 전역 27종(Bridge __push Nav AppCloseGuard + 4화면 + compat 19종) — 게이트 정규식은
   주석도 보므로 여기서도 소스 전체를 훑는다. */
const PRODUCT_GLOBALS = [
  "Bridge", "__push", "Nav", "AppCloseGuard",
  "JobScreen", "LibraryScreen", "EditorScreen", "WorkbenchScreen",
  "Modal", "Popover", "Preserve", "Intent", "UndoToast", "SurfaceSheet", "GroupList",
  "Guard", "SegView", "escHtml", "Copy", "EditorEntry", "PathTrack", "Relink",
  "DataZone", "SheetPicker", "Theme", "Personalization", "DataPicker",
];

// ---------------------------------------------------------------- DOM 대역 --

const COUNTERS = { el: 0, doc: 0, win: 0 };
const ALERTS = [];

function listenerTotal() { return COUNTERS.el + COUNTERS.doc + COUNTERS.win; }

class FakeEl {
  constructor(id) {
    this.id = id || "";
    this.style = {};
    this.dataset = {};
    this.innerHTML = "";
    this.textContent = "";
    this.value = "";
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.isConnected = true;
    this.focusCount = 0;
    this._attrs = {};
    this._listeners = new Map();
    // "modal" 만 true: Modal.close 의 비열림 대상 경로가 loud 거절 없이 조용한 no-op 이
    // 되게 한다(스택에 없으니 실동작 없음 — 실앱과 같은 결과). "on" 등은 false.
    this.classList = {
      add() {}, remove() {}, toggle() {},
      contains: (cls) => cls === "modal",
    };
  }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return Object.hasOwn(this._attrs, k) ? this._attrs[k] : null; }
  removeAttribute(k) { delete this._attrs[k]; }
  hasAttribute(k) { return Object.hasOwn(this._attrs, k); }
  addEventListener(type, fn) {
    COUNTERS.el += 1;
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(fn);
  }
  removeEventListener() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  contains() { return false; }
  matches() { return false; }
  appendChild(c) { return c; }
  focus() { this.focusCount += 1; }
  dispatchClick(event) {
    (this._listeners.get("click") || []).slice()
      .forEach((fn) => fn(event || { target: this }));
  }
}

const REGISTRY = new Map();

globalThis.document = {
  documentElement: new FakeEl("html"),
  body: new FakeEl("body"),
  activeElement: null,
  getElementById(id) {
    if (!REGISTRY.has(id)) REGISTRY.set(id, new FakeEl(id));
    return REGISTRY.get(id);
  },
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() { COUNTERS.doc += 1; },
  removeEventListener() {},
  createElement: () => new FakeEl(""),
};

globalThis.window = {
  pywebview: { api: {} },
  alert: (m) => ALERTS.push(String(m)),
  addEventListener() { COUNTERS.win += 1; },
  removeEventListener() {},
  setTimeout: (...a) => globalThis.setTimeout(...a),
  clearTimeout: (...a) => globalThis.clearTimeout(...a),
  innerWidth: 1200,
  innerHeight: 800,
};

function resetDom() { REGISTRY.clear(); ALERTS.length = 0; }

// ------------------------------------------------------------- deps 대역 --

const SNAP = {
  has_job: true, job_name: "발주요청서", has_data: true,
  data_source_label: "파일: 명단.xlsx", data_mount: "m1",
  out_dir: "C:/out", selection_key: "", rules_key: "", last_run_job: "",
  records: [], selected_count: 0, zone_epoch: 1,
};

/* Bridge 대역 — onPush·initial 을 계측한다. initial 의 응답은 `respond` 프로퍼티로
   갈아끼울 수 있다(reject → 회복 시나리오). */
function makeBridge(snapshot) {
  const bridge = {
    onPushCount: 0, initialCount: 0, calls: [],
    pushHandlers: {},
    respond: async () => snapshot,
    onPush(screen, fn) { bridge.onPushCount += 1; bridge.pushHandlers[screen] = fn; },
    initial(screen) { bridge.initialCount += 1; return bridge.respond(screen); },
    call(screen, action, payload) {
      bridge.calls.push([screen, action, payload]);
      return Promise.resolve({});
    },
    generate: () => Promise.resolve({ ok: true }),
    pickOutputFolder: () => Promise.resolve(null),
  };
  return bridge;
}

function makeDeps(bridge) {
  const trace = { nav: [], entry: [], aim: [] };
  const dz = {
    wire() {}, render() {}, sync() {},
    flushPendingSearch: () => Promise.resolve(),
    flushPendingEdits: () => Promise.resolve(),
    dropPendingEdits() {},
  };
  const deps = {
    Bridge: bridge,
    Nav: { go: (s) => trace.nav.push(s), refresh() {} },
    EditorScreen: {},   // 교차 화면 콜백 테이블 — aimAt 은 테스트가 나중에 심는다(late-binding)
    DataZone: { create: () => dz },
    PathTrack: { affordances: () => "" },
    Relink: { relinkTemplate: () => Promise.resolve(false) },
    EditorEntry: {
      openGuarded: (name, ctx) => { trace.entry.push([name, ctx]); return Promise.resolve(true); },
      newDraftFromData: () => Promise.resolve(true),
    },
    DataPicker: { open() {} },
  };
  return { deps, trace };
}

const tick = () => new Promise((r) => setImmediate(r));

const { createJobScreen } = await import(SRC_URL);

// ------------------------------------------------------------------ 테스트 --

test("음성: IIFE 래퍼 0 · 제품 전역 27종 참조 0 · export 1개 · 화면 간 import 0", () => {
  assert.ok(!SRC.includes("(function () {"), "IIFE 래퍼가 남아 있다");
  // 본문 안 (async () => {...})(); 은 정당한 지역 즉시실행이다 — 모듈 **종결**만 본다.
  assert.ok(!SRC.trimEnd().endsWith("})();"), "IIFE 종결이 남아 있다");
  const re = new RegExp("(?:window|globalThis)\\s*\\.\\s*(" + PRODUCT_GLOBALS.join("|") + ")\\b", "g");
  const hits = SRC.match(re) || [];
  assert.deepEqual(hits, [], "제품 전역 참조가 남아 있다: " + hits.join(", "));
  const exports = SRC.match(/^export\s/gm) || [];
  assert.equal(exports.length, 1, "export 는 정확히 1개여야 한다");
  assert.ok(!/export\s+default/.test(SRC), "export default 금지");
  assert.ok(/export function createJobScreen\(/.test(SRC), "named factory export 부재");
  const imports = [...SRC.matchAll(/^import\s.*?from\s+"([^"]+)"/gm)].map((m) => m[1]);
  assert.ok(imports.length > 0, "직접 import 가 하나도 없다");
  for (const p of imports) {
    assert.match(p, /^\.\.\/(esc|modal|popover|preserve|intent|surface_sheet|grouplist|guard)\.js$/,
      "허용 밖 import: " + p + " (화면 간·app·bridge import 금지)");
  }
});

test("공개 표면 12키 — 키 집합·순서·타입 정확 일치", async () => {
  resetDom();
  const bridge = makeBridge(SNAP);
  const { deps } = makeDeps(bridge);
  const api = createJobScreen(deps);
  assert.deepEqual(Object.keys(api), SURFACE);
  for (const k of SURFACE) assert.equal(typeof api[k], "function", k + " 는 함수여야 한다");
});

test("init 멱등 — 2회째 listener·onPush·initial 등록 delta 0 (실측)", async () => {
  resetDom();
  const bridge = makeBridge(SNAP);
  const { deps } = makeDeps(bridge);
  const api = createJobScreen(deps);

  const before = listenerTotal();
  await api.init();
  const afterFirst = listenerTotal();
  const wired = afterFirst - before;
  assert.ok(wired > 0, "첫 init 이 listener 를 하나도 달지 않았다(계측 무효)");
  assert.equal(bridge.onPushCount, 1);
  assert.equal(bridge.initialCount, 1);
  // 렌더가 실제로 돌았다(스냅샷 값이 DOM 대역에 착지).
  assert.equal(REGISTRY.get("jobDataLabel").value, SNAP.data_source_label);

  await api.init();
  assert.equal(listenerTotal() - afterFirst, 0, "재-init 이 listener 를 추가 등록했다");
  assert.equal(bridge.onPushCount, 1, "재-init 이 onPush 를 중복 등록했다");
  assert.equal(bridge.initialCount, 1, "재-init 이 initial 을 다시 당겼다");
});

test("동시 init 2회 — 같은 초기화 공유(initial 1회)", async () => {
  resetDom();
  const bridge = makeBridge(SNAP);
  const { deps } = makeDeps(bridge);
  const api = createJobScreen(deps);
  const p1 = api.init();
  const p2 = api.init();
  await Promise.all([p1, p2]);
  assert.equal(bridge.initialCount, 1, "동시 init 이 initial 을 두 번 당겼다");
  assert.equal(bridge.onPushCount, 1);
});

test("첫 initial reject → 전파 + 명시적 재-init 회복(listener 중복 0)", async () => {
  resetDom();
  const bridge = makeBridge(SNAP);
  const { deps } = makeDeps(bridge);
  const api = createJobScreen(deps);

  bridge.respond = () => Promise.reject(new Error("initial down"));
  const before = listenerTotal();
  await assert.rejects(api.init(), /initial down/);   // 조용히 삼키지 않는다
  const afterFail = listenerTotal();
  assert.ok(afterFail - before > 0);
  assert.equal(bridge.onPushCount, 1);
  assert.equal(bridge.initialCount, 1);

  // 스스로 재시도하지 않는다 — 회복은 다음 **명시적** init 이 initial 만 다시 당긴다.
  bridge.respond = () => Promise.resolve(SNAP);
  await api.init();
  assert.equal(bridge.initialCount, 2, "재-init 이 initial 을 다시 당기지 않았다(실패 고착)");
  assert.equal(bridge.onPushCount, 1, "재-init 이 onPush 를 중복 등록했다");
  assert.equal(listenerTotal() - afterFail, 0, "재-init 이 listener 를 중복 설치했다");
  assert.equal(REGISTRY.get("jobDataLabel").value, SNAP.data_source_label);

  // 성공 뒤 재호출은 다시 멱등(initial 그대로).
  await api.init();
  assert.equal(bridge.initialCount, 2);
});

test("교차 콜백 EditorScreen.aimAt — 진입 성사 뒤 호출 + late-binding", async () => {
  resetDom();
  const bridge = makeBridge(SNAP);
  const { deps, trace } = makeDeps(bridge);
  const api = createJobScreen(deps);
  await api.init();

  // 파일 이름 「수정」 → previewFix("filename/filenamePattern") → EditorEntry.openGuarded
  // 성사 → aimAt. 구성 시점의 테이블에는 aimAt 이 없다 — 없으면 호출 없이 조용히 지나간다.
  const fixBtn = REGISTRY.get("previewFixFilename");
  fixBtn.dispatchClick();
  await tick();
  assert.equal(trace.entry.length, 1, "수선 진입(openGuarded)이 발화하지 않았다");
  assert.equal(trace.entry[0][0], SNAP.job_name);
  assert.equal(trace.entry[0][1].target, "filename/filenamePattern");
  assert.equal(trace.aim.length, 0, "aimAt 부재인데 호출이 기록됐다");

  // late-binding: factory 구성 **뒤에** 심은 콜백이 호출 시점에 잡힌다.
  deps.EditorScreen.aimAt = (target) => trace.aim.push(target);
  fixBtn.dispatchClick();
  await tick();
  assert.equal(trace.entry.length, 2);
  assert.deepEqual(trace.aim, ["filename/filenamePattern"]);

  // Nav 도 주입 테이블 — openJob 은 Nav.go("job") 으로 착지한다(활성 작업 재진입 = 무전환).
  api.openJob(SNAP.job_name);
  assert.deepEqual(trace.nav, ["job"]);
});

test("Bridge 는 객체째 — call 프로퍼티 교체가 다음 발신에서 관측된다", async () => {
  resetDom();
  const bridge = makeBridge(SNAP);
  const { deps } = makeDeps(bridge);
  const api = createJobScreen(deps);
  await api.init();

  const swapped = [];
  bridge.call = (screen, action, payload) => {   // Python selftest 의 스텁 계약과 같은 형태
    swapped.push([screen, action, payload]);
    return Promise.resolve({});
  };
  api.refreshList();
  await tick();
  assert.deepEqual(swapped, [["job", "refresh", {}]],
    "교체한 Bridge.call 이 관측되지 않았다 — 메서드가 사전 추출됐다");
  assert.deepEqual(ALERTS, [], "refreshList 성공 경로에서 alert 가 떴다");
});
