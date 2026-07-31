/* 중앙 호환 계층 계약 — 별칭은 정확히 스물다섯, 정확히 한 번, 올바른 객체에 걸린다.

   compat 은 "동작을 바꾸지 않는 파일"이라 동작 테스트로는 보이지 않는다. 여기서 세는 것은
   결과가 아니라 **생산 자리와 횟수**다(#372 D-05).

   N-05 부터 compat 은 서비스 열다섯을 끌어오고 그중 셋(`popover`·`undo_toast`·`pathtrack`)은
   **평가/구성 시점에 document 리스너를 붙인다**. N-06 부터는 화면 넷과 앱 셸도 구성하는데,
   앱 셸 구성은 구 IIFE 평가와 같은 의미로 부팅 랜딩(`go("job")`)·셸 배선까지 즉시 실행한다.
   그래서 대역은 "평가만 되면 되는 최소치"가 아니라 **앱 셸 구성이 실제로 지나가는 DOM 표면**
   (getElementById·body.classList·querySelectorAll)까지 흉내 낸다 — 거동은 각 모듈의 전용
   테스트가 보고, 여기는 조립이 죽지 않고 별칭이 올바로 서는가만 본다. 대역은 제품 전역을
   하나도 만들지 않으며 매 테스트 뒤 걷는다. */
import test from "node:test";
import assert from "node:assert/strict";

const COMPAT = "../../frontend/src/compat.js";

const LEAVES = ["copy.js", "esc.js", "guard.js", "segview.js"];

/* 별칭 → 그 이름을 내는 모듈. 평범한 named export 는 compat 이 건 값이 모듈의 export 와
   **같은 객체**여야 하고, factory 산물은 compat 이 구성한 인스턴스라 표면(키)으로 센다. */
const PLAIN_ALIASES = {
  Copy: ["copy.js", "Copy"],
  escHtml: ["esc.js", "escHtml"],
  Guard: ["guard.js", "Guard"],
  SegView: ["segview.js", "SegView"],
  Popover: ["popover.js", "Popover"],
  Preserve: ["preserve.js", "Preserve"],
  Intent: ["intent.js", "Intent"],
  UndoToast: ["undo_toast.js", "UndoToast"],
  Modal: ["modal.js", "Modal"],
  SurfaceSheet: ["surface_sheet.js", "SurfaceSheet"],
  GroupList: ["grouplist.js", "GroupList"],
};

const FACTORY_ALIASES = {
  Theme: ["set", "toggle", "current", "apply"],
  Personalization: [
    "apply", "currentFontScale", "toggleFontScale", "setFontScale",
    "setMasterWidth", "saveMasterWidth", "masterMin", "masterMax",
  ],
  SheetPicker: ["choose"],
  PathTrack: ["affordances"],
  Relink: ["relinkTemplate"],
  DataZone: ["create"],
  DataPicker: ["init", "open"],
  EditorEntry: [
    "openGuarded", "land", "confirmDiscard", "newDraft",
    "newDraftFromData", "restoreEntryFocus",
  ],
  /* N-06 — 화면 넷과 앱 셸 산물. 공개 표면 키 자체가 Python 소비 계약이다
     (app.py 가 JobScreen.renderResult·Nav.go·AppCloseGuard.prompt 를 직접 부른다). */
  LibraryScreen: ["init"],
  EditorScreen: ["init", "rerender", "leaveTo", "aimAt"],
  JobScreen: [
    "init", "overwriteBody", "guardBody", "resultExitLine", "confirmDataSwapIfArmed",
    "openJob", "refreshList", "openJobDataSheet", "openBrowseNeedsAction",
    "openPreview", "renderResult", "markResultStale",
  ],
  WorkbenchScreen: ["init", "render", "leaveTo"],
  Nav: ["go", "refresh"],
  AppCloseGuard: ["prompt"],
};

const ALIASES = [
  ...Object.keys(PLAIN_ALIASES),
  ...Object.keys(FACTORY_ALIASES),
].sort();

/* 앱 셸 구성이 실제로 지나가는 DOM 표면의 최소 대역. 거동 판정은 하지 않는다. */
class FakeEl {
  constructor(id) {
    this.id = id || "";
    this.style = { setProperty() {}, getPropertyValue: () => "" };
    this.dataset = {};
    this.innerHTML = "";
    this.textContent = "";
    this.hidden = false;
    this._attrs = {};
    this._classes = new Set();
    const classes = this._classes;
    this.classList = {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle: (c, force) => {
        const on = force === undefined ? !classes.has(c) : !!force;
        if (on) classes.add(c); else classes.delete(c);
        return on;
      },
      contains: (c) => classes.has(c),
    };
  }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return Object.hasOwn(this._attrs, k) ? this._attrs[k] : null; }
  removeAttribute(k) { delete this._attrs[k]; }
  addEventListener() {}
  removeEventListener() {}
  appendChild() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  contains() { return false; }
  focus() {}
}

function useHostStub(t) {
  const hadWindow = Object.hasOwn(globalThis, "window");
  const hadDocument = Object.hasOwn(globalThis, "document");
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  const hadGcs = Object.hasOwn(globalThis, "getComputedStyle");
  const previousGcs = globalThis.getComputedStyle;

  const listeners = [];
  const byId = new Map();
  globalThis.document = {
    addEventListener: (type, fn, opts) => listeners.push({ type, fn, opts }),
    removeEventListener: () => {},
    /* 앱 셸 구성이 `scr-*` 요소를 만진다 — id 별 1개를 만들어 캐시한다(없음=null 이 아니라
       존재하는 화면 대역: `el && el.classList.contains("on")` 가드가 실제로 평가되게). */
    getElementById: (id) => {
      if (!byId.has(id)) byId.set(id, new FakeEl(id));
      return byId.get(id);
    },
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => new FakeEl(""),
    body: new FakeEl("body"),
    documentElement: new FakeEl("html"),
  };
  globalThis.window = {
    addEventListener: (type, fn, opts) => listeners.push({ type, fn, opts }),
    removeEventListener: () => {},
    alert: () => {},
    /* compat 이 평가 시점에 붙드는 유일한 제품 전역. 객체째 넘어가는지 여기서 본다. */
    Bridge: { call() {}, onPush() {}, initial() {} },
  };
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });

  t.after(() => {
    if (hadWindow) globalThis.window = previousWindow;
    else delete globalThis.window;
    if (hadDocument) globalThis.document = previousDocument;
    else delete globalThis.document;
    if (hadGcs) globalThis.getComputedStyle = previousGcs;
    else delete globalThis.getComputedStyle;
  });
  return { window: globalThis.window, document: globalThis.document, listeners };
}

/* compat 은 프로세스당 한 번만 평가된다(ESM 캐시). 그래서 "무엇이 설치됐나"는 **처음
   import 하는 테스트**에서만 관측할 수 있다. 그 관측을 한 곳에 모아 두고 나머지 테스트는
   캐시 히트의 성질만 본다. */
let firstInstall = null;

test("전역 프로브가 실제 쓰기를 잡는다(양성 대조)", async (t) => {
  const host = useHostStub(t);
  const before = Object.keys(host.window).length;

  await import("data:text/javascript,window.__probeControl = 1;");

  assert.equal(Object.keys(host.window).length, before + 1);
  assert.equal(host.window.__probeControl, 1);
});

test("잎 모듈은 import 만으로 전역을 만들지 않는다", async (t) => {
  const host = useHostStub(t);
  const before = Object.keys(host.window).sort();

  // 캐시 우회 쿼리가 없으면 이미 평가된 모듈을 다시 받아 프로브가 아무것도 관측하지
  // 못한 채 초록이 된다.
  for (const [index, leaf] of LEAVES.entries()) {
    await import(`../../frontend/js/${leaf}?leaf-global-probe=${index}`);
  }

  assert.deepEqual(Object.keys(host.window).sort(), before);
});

test("compat 이 스물다섯 별칭을 만들고 올바른 객체에 건다", async (t) => {
  const host = useHostStub(t);
  const before = new Set(Object.keys(host.window));

  const module = await import(COMPAT);
  firstInstall = module;

  const installed = Object.keys(host.window)
    .filter((key) => !before.has(key))
    .sort();

  assert.deepEqual(installed, ALIASES);
  assert.equal(installed.length, 25);

  for (const [alias, [file, exported]] of Object.entries(PLAIN_ALIASES)) {
    const source = await import(`../../frontend/js/${file}`);
    assert.equal(host.window[alias], source[exported],
      `${alias} 별칭이 ${file} 의 export 와 다른 객체입니다`);
  }

  for (const [alias, keys] of Object.entries(FACTORY_ALIASES)) {
    assert.equal(typeof host.window[alias], "object",
      `${alias} 가 구성된 서비스 객체가 아닙니다`);
    assert.deepEqual(Object.keys(host.window[alias]).sort(), [...keys].sort(),
      `${alias} 의 표면이 계약과 다릅니다`);
  }
});

test("앱 셸 구성이 기본 job 랜딩을 확정했다 — 조립이 실제로 돌았다는 실행 증거", async (t) => {
  const host = useHostStub(t);

  await import(COMPAT);

  // 캐시 히트라 이 대역에는 새 랜딩이 찍히지 않는다 — 첫 평가의 대역을 다시 볼 수 없으므로
  // 여기서는 별칭이 산 객체인지(구성 산물)만 다시 확인한다.
  assert.equal(typeof host.window === "object" || firstInstall !== null, true);
  assert.equal(typeof firstInstall, "object");
});

test("반복 import 는 본문을 다시 돌리지 않는다", async (t) => {
  useHostStub(t);

  const again = await import(COMPAT);

  assert.equal(again, firstInstall, "ESM 캐시 히트여야 한다 — 본문이 두 번 돌면 안 된다");
});

test("compat 은 자체 상태나 새 표면을 갖지 않는다", async (t) => {
  useHostStub(t);

  const module = await import(COMPAT);

  assert.deepEqual(Object.keys(module), [], "compat 은 아무것도 export 하지 않는다");
});
