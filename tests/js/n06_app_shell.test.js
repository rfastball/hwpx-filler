/* 앱 셸 집행 adapter 의 특성화 테스트 — N-06 lane E, R3-02(#411)에서 제자리 진화.
 *
 * 기대값은 **셸 이관 이전 동작**이다. R3-02 는 판정(상태기계)·수명주기(React ShellHost)·
 * 집행(이 adapter)을 갈랐지만 파사드(`Nav.go`·`Nav.refresh`·`AppCloseGuard.prompt`)와 그
 * 거동은 그대로여야 한다 — 이 파일이 초록이면 "절취선만 생기고 거동은 그대로"가 참이다.
 * 판정층 자체의 전수는 shell_nav.test.js 가 지고, 여기는 adapter 결합(집행·서술·파사드)을
 * 진다. 리스너 부착은 이제 서술(`shellHost.attachments`)이라, React effect 와 **같은 실물**
 * (`attachShell`)로 부착해 종전 거동을 계측한다 — 부착/해제 대칭이 새 계약이다.
 *
 * DOM 은 node:test 만으로 돌리려고 손으로 세운 최소 스텁(FakeEl)이다. app.js 의 정적
 * import 간선(modal.js → popover.js)이 **모듈 평가 시점**에 document/window 리스너를 걸므로
 * 전역 대역을 먼저 설치한 뒤 동적 import 한다(n05 관례). 제품 전역(window.Bridge 등)은
 * 한 번도 세우지 않는다.
 */
import { after, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

/* ────────────────────────── 최소 DOM 대역 ────────────────────────── */

class FakeEl {
  constructor(tag = "div", id = "") {
    this.tagName = String(tag).toUpperCase();
    this.id = id;
    this.dataset = {};
    this.textContent = "";
    this.attributes = new Map();
    this.listeners = new Map();
    this.style = {};
    const set = new Set();
    this.classSet = set;
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
  setAttribute(n, v) { this.attributes.set(n, String(v)); }
  getAttribute(n) { return this.attributes.has(n) ? this.attributes.get(n) : null; }
  addEventListener(t, fn) {
    if (!this.listeners.has(t)) this.listeners.set(t, []);
    this.listeners.get(t).push(fn);
  }
  removeEventListener(t, fn) {
    const l = this.listeners.get(t);
    if (!l) return;
    const at = l.indexOf(fn);
    if (at !== -1) l.splice(at, 1);
  }
  listenerCount(t) { return (this.listeners.get(t) || []).length; }
  fire(t, e = {}) { for (const fn of (this.listeners.get(t) || []).slice()) fn(e); }
}

const BY_ID = new Map();
const NAVS = [];       // .navbtn — 상단 토바 2탭
const SCRS = [];       // .scr — 화면 루트 4개
const SPLITTERS = [];  // .master-splitter — 현 index.html 은 0개(F6 PR-B 사망)
let APP_EL = null;

const DOC = {
  body: null,
  activeElement: null,
  listeners: new Map(),
  createElement: (t) => new FakeEl(t),
  getElementById(id) { return BY_ID.get(id) || null; },
  querySelectorAll(sel) {
    if (sel === ".navbtn") return NAVS.slice();
    if (sel === ".scr") return SCRS.slice();
    if (sel === ".master-splitter") return SPLITTERS.slice();
    return [];
  },
  querySelector(sel) { return sel === ".app" ? APP_EL : (DOC.querySelectorAll(sel)[0] || null); },
  addEventListener(t, fn) {
    if (!DOC.listeners.has(t)) DOC.listeners.set(t, []);
    DOC.listeners.get(t).push(fn);
  },
  removeEventListener(t, fn) {
    const l = DOC.listeners.get(t);
    if (!l) return;
    const at = l.indexOf(fn);
    if (at !== -1) l.splice(at, 1);
  },
};

const ALERTS = [];
const CLOSE_CALLS = [];
const WIN = {
  listeners: new Map(),
  addEventListener(t, fn) {
    if (!WIN.listeners.has(t)) WIN.listeners.set(t, []);
    WIN.listeners.get(t).push(fn);
  },
  removeEventListener(t, fn) {
    const l = WIN.listeners.get(t);
    if (!l) return;
    const at = l.indexOf(fn);
    if (at !== -1) l.splice(at, 1);
  },
  alert: (t) => { ALERTS.push(String(t)); },
  fire(t, e = {}) { for (const fn of (WIN.listeners.get(t) || []).slice()) fn(e); },
  listenerCount(t) { return (WIN.listeners.get(t) || []).length; },
  innerWidth: 1280,
  innerHeight: 800,
  pywebview: null,
};

function reg(el) { if (el.id) BY_ID.set(el.id, el); return el; }

function buildFixture() {
  BY_ID.clear();
  NAVS.length = 0;
  SCRS.length = 0;
  SPLITTERS.length = 0;
  ALERTS.length = 0;
  CLOSE_CALLS.length = 0;
  WIN.listeners.clear();
  DOC.listeners.clear();
  WIN.pywebview = {
    api: {
      confirm_window_close: async () => { CLOSE_CALLS.push("confirm"); },
      cancel_window_close: async () => { CLOSE_CALLS.push("cancel"); },
    },
  };
  DOC.body = new FakeEl("body");
  for (const scr of ["job", "library"]) {
    const b = new FakeEl("button");
    b.classList.add("navbtn");
    b.dataset.scr = scr;
    NAVS.push(b);
  }
  for (const id of ["job", "library", "editor", "workbench"]) {
    const s = reg(new FakeEl("section", "scr-" + id));
    s.classList.add("scr");
    SCRS.push(s);
  }
  APP_EL = new FakeEl("div");
  APP_EL.classList.add("app");
  reg(new FakeEl("span", "fontScaleLabel"));
  reg(new FakeEl("button", "fontScaleToggle"));
  reg(new FakeEl("button", "themeToggle"));
  reg(new FakeEl("span", "themeLabel"));
}

globalThis.window = WIN;
globalThis.document = DOC;
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });
after(() => {
  delete globalThis.window;
  delete globalThis.document;
  delete globalThis.getComputedStyle;
});

/* ────────────────────── 실물 그래프 열기(전역 대역 설치 후) ────────────────────── */

buildFixture();
const SRC_URL = new URL("../../frontend/js/app.js", import.meta.url);
const SRC = readFileSync(SRC_URL, "utf8");

const mod = await import("../../frontend/js/app.js");
const { Modal } = await import("../../frontend/js/modal.js");
const { createShellNav } = await import("../../frontend/src/shell/nav.ts");
const { attachShell } = await import("../../frontend/src/shell/host.ts");
const { createAppShell } = mod;

/* ────────────────────── 주입 대역 ────────────────────── */

function makeDeps() {
  const bridgeLog = [];
  const initLog = [];
  const leaveLog = [];
  const rerenders = [];
  const deps = {
    Bridge: {
      call(id, action, payload) {
        bridgeLog.push([id, action, payload]);
        return Promise.resolve({});
      },
      /* N-07 — 닫기 두 호출은 셸이 `window.pywebview.api` 를 직접 뒤지는 대신 브리지 표면을
         쓴다. 대역도 실물과 같은 자리로 위임해야 "셸이 브리지를 거친다"는 사실이 검사된다. */
      confirmWindowClose() { return window.pywebview.api.confirm_window_close(); },
      cancelWindowClose() { return window.pywebview.api.cancel_window_close(); },
      /* R3-02 — 부팅 시퀀서의 선판정도 브리지 술어를 거친다(bridge.js hostReady 계약). */
      hostReady() { return !!(window.pywebview && window.pywebview.api); },
    },
    Theme: {
      mode: "system",
      toggles: 0,
      current() { return this.mode; },
      toggle() { this.toggles += 1; },
    },
    Personalization: {
      scale: "normal",
      fontToggles: 0,
      currentFontScale() { return this.scale; },
      toggleFontScale() { this.fontToggles += 1; },
      setMasterWidth() {},
      saveMasterWidth() {},
      masterMin: 160,
      masterMax: 480,
    },
    DataPicker: { init: () => initLog.push("DataPicker") },
    screens: {
      library: { init: () => initLog.push("library") },
      editor: {
        init: () => initLog.push("editor"),
        rerender: () => rerenders.push("editor"),
        leaveTo: (id) => leaveLog.push(["editor", id]),
        aimAt() {},
      },
      job: { init: () => initLog.push("job") },
      workbench: {
        init: () => initLog.push("workbench"),
        render() {},
        leaveTo: (id) => leaveLog.push(["workbench", id]),
      },
    },
  };
  deps.initSequence = [
    () => deps.screens.library.init(),
    () => deps.screens.editor.init(),
    () => deps.screens.job.init(),
    () => deps.screens.workbench.init(),
    () => deps.DataPicker.init(),
  ];
  return { deps, bridgeLog, initLog, leaveLog, rerenders };
}

function makeShell() {
  const bag = makeDeps();
  bag.shellNav = createShellNav();
  bag.deps.shellNav = bag.shellNav;
  /* R4-04 뒤 app.js는 셸 서술만 만들고 executor는 ProductScreens 합성 루트가 먼저 묶는다.
     이 파일은 셸 adapter 계약만 재므로 최소 기록 executor를 주입하고, 실제 flushSync·focus·
     scroll 계약은 r4_product_screen_executor.test.js가 실물로 잰다. */
  bag.shellNav.bindExecutor({
    delegateLeave(from, to) {
      const owner = bag.deps.screens[from];
      if (typeof owner?.leaveTo !== "function") return false;
      owner.leaveTo(to);
      return true;
    },
    reclaimSurfaces() {},
    applyScreen(id) {
      for (const screen of SCRS) screen.classList.toggle("on", screen.id === `scr-${id}`);
      for (const button of NAVS) {
        button.setAttribute("aria-current", button.dataset.scr === id ? "true" : "false");
      }
      DOC.body.classList.toggle("editor-open", id === "editor");
      DOC.body.classList.toggle("workbench-open", id === "workbench");
    },
    dispatchRefresh(id) {
      if (!WIN.pywebview) return Promise.resolve(null);
      return bag.deps.Bridge.call(id, "refresh", {}).then((result) => {
        if (result?.notice) WIN.alert(result.notice);
        return result;
      });
    },
    notifyRefreshFailure(error) { WIN.alert(error?.message || error); },
    rerenderEditor() { bag.deps.screens.editor.rerender(); },
  });
  bag.shell = createAppShell(bag.deps);
  return bag;
}

/** React ShellHost effect 와 같은 실물로 부착한다 — 반환은 대칭 해제 클로저. */
function mount(bag) {
  return attachShell(bag.shell.shellHost);
}

const ready = () => WIN.fire("pywebviewready", {});
const tick = () => new Promise((r) => setTimeout(r, 0));
const scrOn = (id) => DOC.getElementById("scr-" + id).classList.contains("on");
const navFor = (scr) => NAVS.find((b) => b.dataset.scr === scr);

beforeEach(buildFixture);

/* ══════════════ 1. 공개 표면 ══════════════ */

test("공개 표면 — createAppShell({…, shellNav}) → {Nav, AppCloseGuard, shellHost}", () => {
  assert.deepEqual(Object.keys(mod), ["createAppShell"], "export 는 정확히 하나(named)");
  assert.equal(mod.default, undefined, "export default 금지");
  assert.equal(typeof createAppShell, "function");
  const { shell, shellNav } = makeShell();
  assert.deepEqual(Object.keys(shell), ["Nav", "AppCloseGuard", "shellHost"]);
  // R4-03 — `currentScreen` 관측면이 늘었다. 화면이 「지금 어느 화면인가」를 DOM 으로
  // 되물으면 같은 판정이 상태기계와 DOM 두 곳에 살고, React 서브트리가 legacy 화면 루트를
  // 붙드는 간선이 된다. adapter 는 상태기계의 관측면을 **통과**시키기만 한다.
  assert.deepEqual(Object.keys(shell.Nav), ["go", "refresh", "currentScreen"]);
  assert.equal(typeof shell.Nav.go, "function");
  assert.equal(typeof shell.Nav.refresh, "function");
  assert.equal(typeof shell.Nav.currentScreen, "function");
  assert.equal(shell.Nav.currentScreen(), shellNav.currentScreen(),
    "adapter 가 관측값을 자기 사본에서 답하면 두 값이 갈립니다");
  assert.deepEqual(Object.keys(shell.AppCloseGuard), ["prompt"]);
  assert.equal(typeof shell.AppCloseGuard.prompt, "function");
  // ShellHost 주입 서술 — 수명주기(부착/해제·시퀀서)는 React 몫이라 여기는 형태만 계약한다.
  assert.deepEqual(Object.keys(shell.shellHost), ["nav", "attachments", "catchUp", "boot"]);
  assert.equal(shell.shellHost.nav, shellNav, "상태기계 객체째 — 메서드 사전 추출 금지");
  assert.equal(shell.shellHost.catchUp.length, 2, "부착 직후 따라잡기 = 라벨 동기 2");
  assert.deepEqual(Object.keys(shell.shellHost.boot), ["win", "hostReady", "initSequence"]);
  assert.equal(shell.shellHost.boot.win, WIN, "ready 사건의 대상은 window");
  assert.equal(shell.shellHost.boot.initSequence.length, 5, "init 5(화면 넷 + DataPicker)");
});

/* ══════════════ 2. 구성 즉시 기본 랜딩·go 동기성 ══════════════ */

test("구성 즉시 DEFAULT_SCREEN=job 에 랜딩한다(구 IIFE 평가 시점과 동일 의미)", () => {
  const { bridgeLog } = makeShell();
  assert.equal(scrOn("job"), true, "scr-job 에 .on");
  for (const other of ["library", "editor", "workbench"]) assert.equal(scrOn(other), false);
  assert.equal(navFor("job").getAttribute("aria-current"), "true");
  assert.equal(navFor("library").getAttribute("aria-current"), "false");
  assert.deepEqual(bridgeLog, [], "routingReady 전 랜딩은 DOM-only — 브리지 발신 0");
});

test("go 는 synchronous 다 — 반환값 undefined·클래스 토글이 동기 완료", () => {
  const { shell } = makeShell();
  const out = shell.Nav.go("library");
  assert.equal(out, undefined, "go() 를 비동기로 바꾸면 반환값 무시 호출부가 순서를 잃는다");
  assert.equal(scrOn("library"), true, "await 없이 즉시 전환돼 있다");
  assert.equal(scrOn("job"), false);
  assert.equal(navFor("library").getAttribute("aria-current"), "true");
});

/* ══════════════ 3. 몰입 이탈 위임(IMMERSIVE) ══════════════ */

test("editor 가 켜진 채 go(job) → screens.editor.leaveTo('job') 위임·전환 중단, force 는 생략", () => {
  const { shell, leaveLog } = makeShell();
  shell.Nav.go("editor");
  assert.equal(scrOn("editor"), true);
  assert.equal(DOC.body.classList.contains("editor-open"), true, "셸 표지를 body 클래스로 내린다");

  shell.Nav.go("job");
  assert.deepEqual(leaveLog, [["editor", "job"]], "이탈은 소유 화면(주입 객체)에 위임된다");
  assert.equal(scrOn("editor"), true, "전환은 중단 — 처분이 끝나면 force 로 되돌아온다");
  assert.equal(scrOn("job"), false);
  assert.equal(DOC.body.classList.contains("editor-open"), true);

  shell.Nav.go("job", { force: true });
  assert.deepEqual(leaveLog, [["editor", "job"]], "force 재진입은 위임을 생략한다");
  assert.equal(scrOn("job"), true);
  assert.equal(scrOn("editor"), false);
  assert.equal(DOC.body.classList.contains("editor-open"), false);
});

test("workbench 도 동형이다 — 몰입 목록이 위임·은닉을 함께 소유한다(F6)", () => {
  const { shell, leaveLog } = makeShell();
  shell.Nav.go("workbench");
  assert.equal(scrOn("workbench"), true);
  assert.equal(DOC.body.classList.contains("workbench-open"), true);

  shell.Nav.go("library");
  assert.deepEqual(leaveLog, [["workbench", "library"]]);
  assert.equal(scrOn("workbench"), true, "전환 중단");

  shell.Nav.go("library", { force: true });
  assert.equal(scrOn("library"), true);
  assert.equal(DOC.body.classList.contains("workbench-open"), false);
});

/* ══════════════ 4. 전환 자동 새로고침(REFRESH_ON_NAV)·notice ══════════════ */

test("routingReady 후 화이트리스트 화면 전환은 refresh 를 쏘고, refreshed:true 는 쏘지 않는다", async () => {
  const bag = makeShell();
  const { shell, bridgeLog, rerenders } = bag;
  mount(bag);
  ready();
  shell.Nav.go("library");
  await tick();
  assert.deepEqual(bridgeLog, [["library", "refresh", {}]]);

  shell.Nav.go("job", { refreshed: true });
  await tick();
  assert.deepEqual(bridgeLog, [["library", "refresh", {}]],
    "호출자가 전환 전에 이미 기다린 경우(refreshed) 왕복을 두 벌 만들지 않는다");
  assert.deepEqual(rerenders, ["editor"], "refreshed 여도 job 착지 시 editor 재렌더는 돈다");

  shell.Nav.go("library");
  shell.Nav.go("job");
  await tick();
  assert.deepEqual(bridgeLog, [
    ["library", "refresh", {}], ["library", "refresh", {}], ["job", "refresh", {}],
  ]);
});

test("refresh 가 notice 를 돌려주면 alert 로 시끄럽게 알린다", async () => {
  const bag = makeShell();
  const { shell, deps } = bag;
  mount(bag);
  ready();
  deps.Bridge.call = () => Promise.resolve({ notice: "열린 세션이 다른 화면의 삭제로 닫혔습니다" });
  shell.Nav.go("library");
  await tick();
  assert.deepEqual(ALERTS, ["열린 세션이 다른 화면의 삭제로 닫혔습니다"]);
});

test("가드 — routingReady 전·pywebview 부재·비화이트리스트는 무동작 이행 약속(null)", async () => {
  const bag = makeShell();
  const { shell, bridgeLog } = bag;
  assert.equal(await shell.Nav.refresh("job"), null, "routingReady 전");
  mount(bag);
  ready();
  assert.equal(await shell.Nav.refresh("editor"), null, "화이트리스트 밖");
  WIN.pywebview = null;
  assert.equal(await shell.Nav.refresh("job"), null, "pywebview 부재(브라우저 단독 미리보기)");
  assert.deepEqual(bridgeLog, [], "셋 다 브리지 발신 0");
});

/* ══════════════ 5. 부팅 시퀀스 — 선판정·발화 순서·재발화 계측·해제 대칭 ══════════════ */

test("호스트 부재로 mount → init 0, pywebviewready 1회 → init 5개가 정확한 순서로 각 1회", () => {
  const bag = makeShell();
  WIN.pywebview = null;  // 실 부팅 창: effect 부착 시점엔 아직 호스트 주입 전이다.
  mount(bag);
  assert.deepEqual(bag.initLog, [], "사건 전에는 아무 init 도 돌지 않는다");
  ready();
  assert.deepEqual(bag.initLog, ["library", "editor", "job", "workbench", "DataPicker"]);
});

test("선판정 — 호스트가 이미 준비면 mount 즉시 init 5(부착이 비동기라 생기는 놓침 창 폐쇄)", () => {
  const bag = makeShell();
  mount(bag);  // fixture 는 pywebview 를 이미 들고 있다 — 사건을 놓친 형상.
  assert.deepEqual(bag.initLog, ["library", "editor", "job", "workbench", "DataPicker"],
    "adapter.ts whenReady·selftest boot.js 와 같은 선판정+이벤트 규약");
});

test("계측: pywebviewready 2회 발화 → 시퀀서는 가드 없이 init 5개를 한 벌 더 돌린다(현 동작 보존)", () => {
  const bag = makeShell();
  WIN.pywebview = null;
  mount(bag);
  ready();
  ready();
  // 시퀀서 자신은 재발화를 막지 않는다 — 멱등은 각 화면 init 의 wired 가드(N-06 화면 계약)가
  // 진다. 여기서는 스텁이라 원호출 그대로 2벌이 보인다(계측 결과의 정본).
  assert.deepEqual(bag.initLog, [
    "library", "editor", "job", "workbench", "DataPicker",
    "library", "editor", "job", "workbench", "DataPicker",
  ]);
});

test("해제 대칭 — detach 후 ready 사건·셸 리스너가 전부 걷힌다(재초기화 복제 금지의 실물)", () => {
  const bag = makeShell();
  WIN.pywebview = null;
  const detach = mount(bag);
  const attachedWindowTypes = ["unhandledrejection", "pywebviewready",
    "hwpx:personalizationchange", "hwpx:themechange"];
  for (const type of attachedWindowTypes) {
    assert.equal(WIN.listenerCount(type), 1, `${type}: 부착 1`);
  }
  for (const b of NAVS) assert.equal(b.listenerCount("click"), 1);
  detach();
  for (const type of attachedWindowTypes) {
    assert.equal(WIN.listenerCount(type), 0, `${type}: 해제 0`);
  }
  for (const b of NAVS) assert.equal(b.listenerCount("click"), 0);
  ready();
  assert.deepEqual(bag.initLog, [], "해제 뒤 사건은 init 을 돌리지 않는다");
});

/* ══════════════ 6. AppCloseGuard — 직렬화·양 경로·오류 시 안전측 ══════════════ */

test("prompt 는 단일 실행 직렬화 — 미결 중 2차는 no-op, 확인은 confirm_window_close", async () => {
  const { shell } = makeShell();
  const saved = Modal.confirm;
  const seen = [];
  let release;
  Modal.confirm = (opts) => { seen.push(opts); return new Promise((r) => { release = r; }); };
  try {
    const p1 = shell.AppCloseGuard.prompt({ reasons: ["편집 중 문서 1건", "생성 진행 중"] });
    const p2 = shell.AppCloseGuard.prompt({ reasons: ["둘째 요청"] });
    await p2;
    assert.equal(seen.length, 1, "미결 중 2차 prompt 는 모달을 다시 세우지 않는다");
    assert.equal(seen[0].title, "앱 종료 확인");
    assert.ok(seen[0].body.includes("• 편집 중 문서 1건\n• 생성 진행 중"), "사유를 재진술한다");
    assert.equal(seen[0].confirmLabel, "종료");
    assert.equal(seen[0].cancelLabel, "계속 작업");
    assert.equal(seen[0].danger, true);
    release(true);
    await p1;
    assert.deepEqual(CLOSE_CALLS, ["confirm"]);

    // pending 이 걷혔다 — 다음 X 는 새 상태를 다시 판정한다(거절 경로).
    Modal.confirm = () => Promise.resolve(false);
    await shell.AppCloseGuard.prompt({ reasons: [] });
    assert.deepEqual(CLOSE_CALLS, ["confirm", "cancel"]);
    assert.deepEqual(ALERTS, []);
  } finally { Modal.confirm = saved; }
});

test("Modal.confirm 이 죽으면 안전측 — cancel_window_close + alert 재진술, pending 도 걷힌다", async () => {
  const { shell } = makeShell();
  const saved = Modal.confirm;
  Modal.confirm = () => Promise.reject(new Error("모달 사망"));
  try {
    await shell.AppCloseGuard.prompt({ reasons: ["아무거나"] });
    assert.deepEqual(CLOSE_CALLS, ["cancel"], "확인 불능이면 창을 유지한다(안전측)");
    assert.deepEqual(ALERTS, ["종료 확인을 처리하지 못해 창을 유지합니다: 모달 사망"]);

    Modal.confirm = () => Promise.resolve(true);
    await shell.AppCloseGuard.prompt({ reasons: [] });
    assert.deepEqual(CLOSE_CALLS, ["cancel", "confirm"], "실패가 직렬화를 고착시키지 않는다");
  } finally { Modal.confirm = saved; }
});

/* ══════════════ 7. job 착지 시 editor 재렌더 ══════════════ */

test("job 착지 시 screens.editor.rerender 가 돈다(#138 리뷰 F12)", async () => {
  const bag = makeShell();
  const { shell, rerenders } = bag;
  assert.deepEqual(rerenders, [], "구성 랜딩(routingReady 전)은 재렌더하지 않는다");
  mount(bag);
  ready();
  shell.Nav.go("library");
  assert.deepEqual(rerenders, [], "job 외 착지는 재렌더 없음");
  shell.Nav.go("job");
  assert.deepEqual(rerenders, ["editor"]);
  await tick();
});

/* ══════════════ 8. 셸 백스톱(unhandledrejection) ══════════════ */

test("unhandledrejection 백스톱 — preventDefault + alert 재진술(조용한 무반응 차단)", () => {
  const bag = makeShell();
  mount(bag);
  const listeners = WIN.listeners.get("unhandledrejection") || [];
  assert.equal(listeners.length, 1);
  let prevented = false;
  listeners[0]({ reason: new Error("가드를 잊은 rejection"), preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.deepEqual(ALERTS, ["가드를 잊은 rejection"]);
});

/* ══════════════ 9. 테마·개인화 배선(주입 객체 소비) ══════════════ */

test("부착 전에 지나간 hwpx:* 사건은 mount 따라잡기가 만회한다(#74 라벨 어긋남 폐쇄)", () => {
  const bag = makeShell();
  const { deps } = bag;
  // 부팅 preferences 주입이 effect 부착보다 빨랐던 형상 — 사건은 이미 지나갔다.
  deps.Theme.mode = "dark";
  deps.Personalization.scale = "large";
  WIN.fire("hwpx:themechange", {});
  WIN.fire("hwpx:personalizationchange", {});
  assert.equal(DOC.getElementById("themeLabel").textContent, "시스템", "부착 전이라 낡아 있다");
  mount(bag);
  assert.equal(DOC.getElementById("themeLabel").textContent, "다크", "따라잡기가 현재 상태를 재판독");
  assert.equal(DOC.getElementById("fontScaleLabel").textContent, "크게 (125%)");
});

test("테마·글자 크기 라벨은 주입 객체와 hwpx:* 이벤트로 동기화된다", () => {
  const bag = makeShell();
  const { deps } = bag;
  mount(bag);
  assert.equal(DOC.getElementById("themeLabel").textContent, "시스템", "직접 호출은 기본 라벨");
  assert.equal(DOC.getElementById("fontScaleLabel").textContent, "기본");

  deps.Theme.mode = "dark";
  WIN.fire("hwpx:themechange", {});
  assert.equal(DOC.getElementById("themeLabel").textContent, "다크");

  deps.Personalization.scale = "large";
  WIN.fire("hwpx:personalizationchange", {});
  assert.equal(DOC.getElementById("fontScaleLabel").textContent, "크게 (125%)");

  DOC.getElementById("themeToggle").fire("click", {});
  assert.equal(deps.Theme.toggles, 1);
  DOC.getElementById("fontScaleToggle").fire("click", {});
  assert.equal(deps.Personalization.fontToggles, 1);
});

/* ══════════════ 10. Bridge 는 객체째 — 프로퍼티 교체가 보인다 ══════════════ */

test("포트 교체 — Bridge.call = stub 프로퍼티 교체가 refresh 발신에 반영된다", async () => {
  const bag = makeShell();
  const { shell, deps, bridgeLog } = bag;
  mount(bag);
  ready();
  const swapped = [];
  deps.Bridge.call = (id, action, payload) => {
    swapped.push([id, action, payload]);
    return Promise.resolve({});
  };
  shell.Nav.go("library");
  await tick();
  assert.deepEqual(swapped, [["library", "refresh", {}]], "새 함수가 불린다(프로브 경로 생존)");
  assert.deepEqual(bridgeLog, [], "옛 함수로 새지 않는다 — 메서드 사전 추출 금지의 실측");
});

/* ══════════════ 11. 재초기화 — 구조 가드와 계측 ══════════════ */

test("app factory 재구성은 이미 결속된 ProductScreens executor를 다시 묶지 않는다", () => {
  const bag = makeShell();
  assert.doesNotThrow(() => createAppShell(bag.deps));
  assert.equal(bag.shellNav.currentScreen(), "job");
});

test("계측: 기계·factory 를 새로 2벌 구성 + 각각 mount → listener 가 한 벌씩 더 선다", () => {
  const one = makeShell();
  const two = makeShell();
  mount(one);
  mount(two);
  for (const type of ["unhandledrejection", "pywebviewready",
    "hwpx:personalizationchange", "hwpx:themechange"]) {
    assert.equal(WIN.listenerCount(type), 2, `${type}: 2벌`);
  }
  for (const b of NAVS) assert.equal(b.listenerCount("click"), 2, "탭 클릭도 2벌");
  // 두 셸이 같은 DOM 을 공유하고 fixture 는 호스트를 이미 들고 있다 — 각 mount 의 선판정이
  // 자기 init 을 이미 돌렸고, ready 1회에 양쪽 init 이 한 벌씩 더 돈다(가드 없음 보존).
  ready();
  assert.deepEqual(one.initLog, [
    "library", "editor", "job", "workbench", "DataPicker",
    "library", "editor", "job", "workbench", "DataPicker",
  ]);
  assert.deepEqual(two.initLog, one.initLog);
});

/* ══════════════ 12. 음성 — 소스 형상 ══════════════ */

const PRODUCT_GLOBALS = [
  "Bridge", "__push", "Nav", "AppCloseGuard",
  "LibraryScreen", "EditorScreen", "JobScreen", "WorkbenchScreen",
  "Copy", "escHtml", "Guard", "SegView", "Popover", "Preserve", "Intent", "UndoToast",
  "Modal", "SurfaceSheet", "GroupList", "Theme", "Personalization", "SheetPicker",
  "PathTrack", "Relink", "DataZone", "DataPicker", "EditorEntry",
];

test("음성 — IIFE 0·window[ 동적 조회 0·제품 전역 27종 조회 0(주석 포함)", () => {
  assert.equal(PRODUCT_GLOBALS.length, 27, "제품 전역 목록 자체의 자기 검증");
  assert.equal(SRC.includes("(function () {"), false, "top-level IIFE 금지");
  assert.equal(SRC.includes("})();"), false, "IIFE 꼬리 금지");
  assert.equal(SRC.includes("window["), false, "owner 동적 조회 금지 — 구성된 객체 직접 참조");
  const PRODUCT = new RegExp(`\\b(?:window|globalThis)\\.(?:${PRODUCT_GLOBALS.join("|")})\\b`);
  assert.equal(PRODUCT.test(SRC), false, "게이트 정규식은 주석도 본다 — 주석 표기까지 0");
  assert.equal(/(?:window|globalThis)\.[A-Za-z_$][\w$]*\s*=[^=]/.test(SRC), false, "자기 전역 생산 금지");
});

test("음성 — import 는 Modal·기본 화면 정본뿐(화면·executor import 0), export 는 createAppShell 하나", () => {
  const importLines = [...SRC.matchAll(/^import .*$/gm)].map((m) => m[0]);
  assert.deepEqual(importLines, [
    'import { Modal } from "./modal.js";',
    'import { DEFAULT_SCREEN } from "../src/shell/nav.ts";',
  ]);
  assert.equal(/from "\.{1,2}\/screens\//.test(SRC), false, "화면 파일 import 금지 — screens 는 주입");
  assert.equal(/export\s+default/.test(SRC), false);
  const names = [...SRC.matchAll(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  assert.deepEqual(names, ["createAppShell"]);
});

test("음성 — 판정 재조립 잔존 0: adapter 에 화면 판정·목록 정본이 남지 않았다", () => {
  assert.equal(/const DEFAULT_SCREEN\s*=/.test(SRC), false, "랜딩 정본은 상태기계(nav.ts) 하나");
  assert.equal(/const REFRESH_ON_NAV\s*=/.test(SRC), false, "화이트리스트 정본은 상태기계 하나");
  assert.equal(/const IMMERSIVE\s*=/.test(SRC), false, "몰입 목록 정본은 상태기계 하나");
  assert.equal(SRC.includes("REFRESH_ON_NAV.includes"), false, "규약 판정 재조립 금지");
  assert.equal(SRC.includes("routingReady"), false, "ready 게이트 판정 재조립 금지");
  assert.equal(/let\s+closePromptPending/.test(SRC), false, "닫기 직렬화 상태는 상태기계 소유");
});

test("Python 계약 앵커 — Nav 리터럴·go 시그니처·기본 랜딩·닫기 계약 문자열", () => {
  assert.ok(SRC.includes("const Nav = { go, refresh, currentScreen: () => shellNav.currentScreen() };"),
    "window.Nav 의 후계 리터럴 그대로(+R4-03 관측면 — 판정은 상태기계가 답한다)");
  assert.ok(SRC.includes("function go(id, opts) {"), "go 는 synchronous 시그니처 텍스트 보존");
  assert.ok(SRC.includes("go(DEFAULT_SCREEN);"), "구성 즉시 랜딩(정본은 import)");
  assert.equal(SRC.includes("bindExecutor"), false, "app.js가 executor를 다시 묶지 않는다");
  assert.equal(SRC.includes("applyScreen"), false, "화면 DOM 집행은 ProductScreens executor 소유");
  assert.ok(SRC.includes('confirmLabel: "종료"') && SRC.includes("danger: true"),
    "닫기 확인의 호출·문안·danger 잔존(패킷 rev3 개정 5 — danger 감사망의 소재 계약)");
});
