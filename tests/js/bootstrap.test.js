/* Product composition: one public global, one push path, and correctly wired services. */
import test from "node:test";
import assert from "node:assert/strict";

const BOOTSTRAP = "../../frontend/src/bootstrap.js";

const LEAVES = ["guard.js"];

/* 합성 루트가 **모듈 export 와 같은 객체**로 배선해야 하는 이름들. 평범한 named export 라
   동일성으로 잰다 — 여기서 사본을 만들면 프로브의 프로퍼티 교체가 우회된다. */
const PLAIN_SERVICES = {
  Guard: ["guard.js", "Guard"],
  Popover: ["popover.js", "Popover"],
  Intent: ["intent.js", "Intent"],
  UndoToast: ["undo_toast.js", "UndoToast"],
};

/* factory 산물 — 합성 루트가 구성한 인스턴스라 동일성 비교가 안 된다. 표면(키)으로 센다. */
const FACTORY_SERVICES = {
  Client: ["hostReady", "whenReady", "invoke", "initial", "dispatch"],
  Theme: ["set", "toggle", "current", "apply"],
  Personalization: [
    "apply", "currentFontScale", "toggleFontScale", "setFontScale",
    "setMasterWidth", "saveMasterWidth", "masterMin", "masterMax",
  ],
  Modal: ["open", "close", "confirm", "prompt", "choose", "restoreFocus"],
  SurfaceSheet: ["open", "close", "closeAndRestore", "closeAllAndRestore", "isOpen", "restore"],
  SheetPicker: ["choose"],
  DataPicker: ["init", "open"],
  EditorEntry: [
    "openGuarded", "land", "confirmDiscard", "newDraft",
    "newDraftFromData", "restoreEntryFocus",
  ],
  JobRun: [
    'recoverRecordIssue',
    "model", "client", "notify", "subscribe", "getRun", "getUi", "getTemplateChange",
    "overwriteBody", "guardBody", "resultExitLine", "selectionLine",
    "confirmDestructiveIfArmed", "log", "renderResult", "markResultStale",
    "openBindingRequirement", "resolveExecution",
    "startGenerate", "cancelGeneration", "closeResult", "selectFailed",
    "openRenameRules", "pickOutputFolder", "setDeliveryCollision", "refreshDelivery", "relinkActive",
    "templateCheck", "templateApply", "openPreviewFrom",
    "closePreview", "previewMove", "previewBlankOnly", "previewApprove", "previewEdit",
    "previewFixField", "previewFixFilename", "openRepair", "toggleLog", "init", "dispose",
  ],
  Nav: ["go", "refresh", "currentScreen"],
  AppCloseGuard: ["prompt"],
  /* 표면 25 = 호스트 메서드 23 + `onPush` + `hostReady`. selftest 프로브가
     `Bridge.call = stub` 으로 프로퍼티를 교체하므로 **객체째**여야 한다. */
  Bridge: [
    "onPush", "hostReady", "initial", "call", "pickDataFile", "loadDataSheet",
    "importTemplateFile", "importTemplatesFolder", "copyClipboard", "pickOutputFolder",
    "generate", "editorHasUnsavedWork", "openJobInEditor", "newJobFromData",
    "revealCorruptJob", "pickPoolDataFile", "pickTemplatePath", "openPath", "revealPath",
    "copyPath", "setTheme", "setFontScale", "setMasterWidth",
    "confirmWindowClose", "cancelWindowClose",
  ],
};

const SERVICE_NAMES = [
  ...Object.keys(PLAIN_SERVICES),
  ...Object.keys(FACTORY_SERVICES),
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
  const stage = new FakeEl("stage");
  stage.scrollTop = 0;
  stage.scrollLeft = 0;
  globalThis.document = {
    addEventListener: (type, fn, opts) => listeners.push({ type, fn, opts }),
    removeEventListener: () => {},
    /* 앱 셸 구성이 `scr-*` 요소를 만진다 — id 별 1개를 만들어 캐시한다(없음=null 이 아니라
       존재하는 화면 대역: `el && el.classList.contains("on")` 가드가 실제로 평가되게). */
    getElementById: (id) => {
      if (!byId.has(id)) byId.set(id, new FakeEl(id));
      return byId.get(id);
    },
    querySelector: (selector) => selector === "main.stage" ? stage : null,
    /* 앱 셸의 라우팅은 `.scr`·`.navbtn` **집합**에 걸린다. 전신의 대역은 여기서 빈 배열을
       돌려줬고, 그래서 부팅 랜딩이 아무 요소에도 찍히지 않아 "조립이 돌았다"를 실제로 볼 수
       없었다(전신의 랜딩 테스트가 사실상 공허했던 진짜 이유). 두 선택자만 채워 랜딩을
       관측 가능하게 만든다 — 나머지는 종전대로 빈 집합이라 거동 판정은 여전히 하지 않는다. */
    querySelectorAll: (selector) => {
      if (selector === ".scr") {
        return ["library", "editor", "job", "workbench"].map((id) =>
          byId.has(`scr-${id}`)
            ? byId.get(`scr-${id}`)
            : byId.set(`scr-${id}`, new FakeEl(`scr-${id}`)).get(`scr-${id}`));
      }
      if (selector === ".navbtn") {
        return ["job", "library"].map((scr) => {
          const el = new FakeEl("");
          el.dataset.scr = scr;
          return el;
        });
      }
      return [];
    },
    createElement: () => new FakeEl(""),
    body: new FakeEl("body"),
    documentElement: new FakeEl("html"),
  };
  globalThis.window = {
    addEventListener: (type, fn, opts) => listeners.push({ type, fn, opts }),
    removeEventListener: () => {},
    alert: () => {},
    /* 대역은 제품 전역을 **하나도** 심지 않는다. 미리 깔면 "합성 루트가 생산자다"라는
       사실이 before 집합 뒤에 숨어 설치 목록에서 사라진다 — 그 침묵이 정확히 이 게이트가
       막아야 할 회귀다. */
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
  return { window: globalThis.window, document: globalThis.document, byId, listeners };
}

/** 대역을 세우고 그 위에서 제품 하나를 조립한다 — 설치된 전역 이름과 구성 산물을 함께 준다.
 *
 *  ESM 캐시 우회가 필요 없다: 부팅이 모듈 평가가 아니라 **호출**이라 같은 모듈로 몇 번이든
 *  새 대역 위에 세울 수 있다. 전신이 `?probe=N` 질의로 캐시를 우회하던 자리가 사라졌다. */
async function boot(t) {
  const host = useHostStub(t);
  const before = new Set(Object.keys(host.window));

  const { bootProduct } = await import(BOOTSTRAP);
  const composed = bootProduct();

  const installed = Object.keys(host.window)
    .filter((key) => !before.has(key))
    .sort();

  return { host, composed, installed };
}

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

test("부팅이 심는 제품 전역은 `__hwpx` 하나뿐이다", async (t) => {
  const { host, installed } = await boot(t);

  assert.deepEqual(installed, ["__hwpx"],
    `제품이 심은 전역: ${JSON.stringify(installed)} — __hwpx 하나여야 합니다.`);
  assert.equal(typeof host.window.__hwpx, "object");
  assert.deepEqual(Object.keys(host.window.__hwpx).sort(), ["deliver", "describe"]);

  /* 시험 능력은 호스트가 대지 않았으므로 서지 않는다 — own 프로퍼티로 **부재**여야 한다
     (D-07). 만들었다 지우는 경로는 없다: 지우기가 한 번 실패하면 그 잔존은 아무도 못 듣는다. */
  assert.equal(Object.hasOwn(host.window, "__hwpxTest"), false);
  assert.equal(typeof host.window.__hwpxTest, "undefined");
});

test("서비스 객체는 전역 별칭으로 노출되지 않는다", async (t) => {
  const { host } = await boot(t);

  /* 양성 대조는 위 「전역 프로브가 실제 쓰기를 잡는다」가 진다 — 이 대역에서 쓰기가
     관측된다는 사실이 먼저 서야 아래 부재가 의미를 가진다. */
  const revived = SERVICE_NAMES.filter((name) => name in host.window);
  assert.deepEqual(revived, [],
    `은퇴한 임시 전역이 되살아났습니다: ${revived.join(", ")}`);
  assert.equal("__push" in host.window, false);
});

test("합성 루트가 잎·서비스를 **모듈 export 와 같은 객체**로 배선한다", async (t) => {
  const { composed } = await boot(t);

  assert.deepEqual(Object.keys(composed.services).sort(), SERVICE_NAMES,
    "selftest 에 넘기는 구성 산물 전수가 계약과 다릅니다 — 빠진 이름은 실엔진에서만 죽습니다.");

  for (const [name, [file, exported]] of Object.entries(PLAIN_SERVICES)) {
    const source = await import(`../../frontend/js/${file}`);
    assert.equal(composed.services[name], source[exported],
      `${name} 이 ${file} 의 export 와 다른 객체입니다 — 사본은 프로퍼티 교체를 우회시킵니다.`);
  }

  for (const [name, keys] of Object.entries(FACTORY_SERVICES)) {
    assert.equal(typeof composed.services[name], "object",
      `${name} 가 구성된 서비스 객체가 아닙니다`);
    assert.deepEqual(Object.keys(composed.services[name]).sort(), [...keys].sort(),
      `${name} 의 표면이 계약과 다릅니다`);
  }

  /* 브리지는 **객체째** 넘어간다 — 주입된 것과 반환된 것이 같은 참조여야 selftest 의
     `Bridge.call = stub` 교체가 소비자에게 보인다. */
  assert.equal(composed.services.Bridge, composed.bridge);
  assert.equal(composed.services.Client, composed.client,
    "React 화면과 selftest가 서로 다른 typed client 사본을 봅니다.");
});

test("앱 셸 구성이 부팅 랜딩(job)을 상태 정본에 실제로 찍었다", async (t) => {
  const { composed } = await boot(t);

  /* 화면 class는 ProductScreens가 React commit으로 소유한다. 이 단위 대역은 React DOM을
     만들지 않으므로 셸 판정 정본에서 랜딩을 관측하고, 실제 class/ARIA는 전용 React·live
     게이트가 잰다. */
  assert.equal(composed.services.Nav.currentScreen(), "job",
    "부팅 랜딩이 셸 상태 정본을 job으로 옮기지 않았습니다.");
});

test("합성 루트의 공개 표면은 `bootProduct` 하나다", async (t) => {
  useHostStub(t);

  const module = await import(BOOTSTRAP);

  assert.deepEqual(Object.keys(module), ["bootProduct"],
    "합성 루트가 조립 말고 다른 표면을 냅니다 — 그 자리가 다음 전역의 거처가 됩니다.");
  assert.equal(typeof module.bootProduct, "function");
});

/* 제품 파사드와 store는 단일 활성 push 포트의 하류에 있어야 한다. */

test("제품 파사드와 푸시 포트는 **같은 하나의 통로**로 모인다", async (t) => {
  const { composed } = await boot(t);

  const api = composed.productApi;
  assert.equal(typeof api.deliver, "function");
  assert.equal(typeof composed.pushPort.dispatch, "function");

  /* 도착 지점을 브리지 구독으로 잡는다 — 통로 **끝**에서 세면 중간을 어떻게 배선했든
     "실제로 렌더러까지 갔는가"가 답이 된다. */
  const seen = [];
  composed.bridge.onPush("job", (snapshot) => { seen.push(snapshot); });

  const result = api.deliver({
    version: 1,
    event: "snapshot",
    payload: { screen: "job", snapshot: { rows: 1 } },
  });
  assert.equal(result.ok, true, `deliver 가 실패했습니다: ${JSON.stringify(result)}`);

  composed.pushPort.dispatch("job", { rows: 2 });

  assert.deepEqual(seen, [{ rows: 1 }, { rows: 2 }],
    "제품 파사드와 푸시 포트가 서로 다른 통로로 갈렸습니다 — 하나를 갈아끼우면 다른 하나가 샙니다.");
});

test("합성 루트는 store 를 계약 유도 채널로 세우고 반환값에 싣는다", async (t) => {
  const { composed } = await boot(t);
  const { SCREEN_ACTIONS } = await import("../../frontend/src/contract/contract.gen.ts");

  assert.equal(typeof composed.store, "object", "store 가 구성 산물에 없습니다.");
  assert.deepEqual([...composed.store.channels], Object.keys(SCREEN_ACTIONS),
    "store 채널이 생성 계약과 갈렸습니다 — 어딘가 손 목록이 생겼습니다.");
  /* store 는 selftest에서 교체할 전송 표면이 아니라 services에 싣지 않는다. */
  assert.equal(Object.hasOwn(composed.services, "store"), false);
});

test("파사드 snapshot 은 legacy 렌더러와 store 에 **같은 세계**로 착지한다", async (t) => {
  const { composed } = await boot(t);

  const seen = [];
  composed.bridge.onPush("job", (snapshot) => { seen.push(snapshot); });
  const snapshot = { rows: 7 };

  const result = composed.productApi.deliver({
    version: 1,
    event: "snapshot",
    payload: { screen: "job", snapshot },
  });

  assert.equal(result.ok, true);
  assert.deepEqual(seen, [snapshot], "legacy 렌더러가 push 를 받지 못했습니다.");
  assert.equal(composed.store.get("job"), snapshot,
    "store 가 legacy 와 다른 참조를 들었습니다 — 두 소비자가 다른 세계를 봅니다.");
  assert.equal(composed.store.revision("job"), 1);
});

test("프로브가 포트를 갈아끼우면 store 도 legacy 처럼 조용해진다(관측자 오염 음성 대조)", async (t) => {
  const { composed } = await boot(t);

  /* reject_pushes 형상 — 갈아끼운 통로가 기반 푸시를 부르지 않는다. 탭이 파사드 옆에
     잘못 서 있으면 이 대조가 빨갛다: reject 중에도 store 만 갱신돼 두 소비자가 갈린다. */
  const rejected = [];
  composed.pushPort.override((screen, snapshot) => { rejected.push([screen, snapshot]); });

  composed.productApi.deliver({
    version: 1,
    event: "snapshot",
    payload: { screen: "job", snapshot: { rows: 1 } },
  });

  assert.equal(rejected.length, 1, "override 가 push 를 받지 못했습니다.");
  assert.equal(composed.store.revision("job"), 0,
    "reject 중에 store 가 갱신됐습니다 — 탭이 포트 상류(파사드 옆)에 서 있습니다.");

  composed.pushPort.restore();
  composed.productApi.deliver({
    version: 1,
    event: "snapshot",
    payload: { screen: "job", snapshot: { rows: 2 } },
  });
  assert.equal(composed.store.revision("job"), 1, "restore 뒤에도 store 에 닿지 않습니다.");
  assert.deepEqual(composed.store.get("job"), { rows: 2 });
});
