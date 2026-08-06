/* 제품 합성 루트 계약 — 제품 전역은 정확히 하나, 조립은 정확히 한 번, 올바른 객체에.

   ## 이 파일의 전신과 옮겨온 책임 (N-10 old→new)

   전신은 `compat.test.js` 였고 중심 질문은 "**별칭 스물여덟**이 정확히 한 번, 올바른 객체에
   걸리는가" 였다. N-10 이 임시 별칭 스물일곱을 지우면서 그 질문의 **주어**가 사라졌다.
   그렇다고 파일째 지우면 함께 죽는 것이 있다:

   - 어떤 잎이 export 와 **동일 객체**로 배선됐는가 (`Copy` ≡ `copy.js` 의 export)
   - 각 factory 산물의 **공개 표면 키**가 계약대로인가 (`JobScreen` 의 열두 메서드 등)
   - 조립이 실제로 **돌았는가** (앱 셸이 부팅 랜딩을 찍었는가)
   - 제품 파사드와 푸시 통로가 **같은 하나**로 모이는가

   이 넷은 별칭이 아니라 **합성**에 대한 질문이라 별칭과 함께 죽을 이유가 없다. 종전에는
   그것을 물을 수단이 `window` 를 훔쳐보는 것뿐이었고, 전역이 사라지면 수단째 사라진다 —
   "별칭이 없다"는 사실만 남고 "조립이 여전히 옳다"는 사실이 죽는 자리다(선언은 살고 결과는
   죽는다). 그래서 관측면을 **`bootProduct()` 의 반환값**으로 옮겼다.

   | 전신 테스트 | 여기서의 후계 |
   |---|---|
   | 전역 프로브 양성 대조 | 그대로 — 이제 "제품이 심는 전역이 하나뿐"의 양성 대조를 겸한다 |
   | 잎은 import 만으로 전역을 안 만든다 | 그대로 |
   | 별칭 28을 만들고 올바른 객체에 건다 | **둘로 갈림**: ①제품 전역은 `__hwpx` 하나 ②배선 신원·표면은 반환값으로 |
   | 앱 셸 랜딩(캐시 히트라 사실상 공허) | 실제 랜딩을 단언하는 실질 테스트로 승격 |
   | 반복 import 는 본문을 다시 안 돌린다 | **폐기·대체**: 부팅이 평가가 아니라 호출이 됐다. 단일성은 `test_entry_calls_the_composition_root_exactly_once`(Python)가 진다 |
   | compat 은 export 가 없다 | 표면이 `bootProduct` 하나인지로 바뀜 |
   | 파사드와 `window.__push` 가 같은 통로 | **손잡이만 교체**: 전역 대신 반환된 `pushPort`·`bridge` |
   | 기반 푸시를 값으로 안 붙든다(소스 계약) | 그대로, 대상만 `bootstrap.js` |

   전역 **부재** 자체의 정적 음성 게이트(bracket·`globalThis`·`Object.assign`·`defineProperty`
   ·classic script·IIFE·순환)는 `n10_global_hygiene.test.js` 가 AST 로 따로 진다. 여기는
   런타임 조립이 무엇을 세우는가를 본다.

   ## 대역의 성질

   앱 셸 구성은 구 IIFE 평가와 같은 의미로 부팅 랜딩(`go("job")`)·셸 배선까지 즉시 실행하고,
   서비스 셋(`popover`·`undo_toast`·`pathtrack`)은 구성 시점에 document 리스너를 붙인다.
   그래서 대역은 "평가만 되면 되는 최소치"가 아니라 **앱 셸 구성이 실제로 지나가는 DOM 표면**
   까지 흉내 낸다. 거동은 각 모듈의 전용 테스트가 보고, 여기는 조립이 죽지 않고 올바로
   서는가만 본다. 대역은 제품 전역을 하나도 만들지 않으며 매 테스트 뒤 걷는다.

   부팅이 **호출**이 되면서 대역 하나에 조립을 여러 번 세울 수 있게 됐다 — 전신이 ESM 캐시를
   질의 문자열로 우회해야 했던 자리다(`?n09-pushport-probe=1`). 그 우회가 사라졌다. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const BOOTSTRAP = "../../frontend/src/bootstrap.js";

const LEAVES = ["copy.js", "esc.js", "guard.js", "segview.js"];

/* 합성 루트가 **모듈 export 와 같은 객체**로 배선해야 하는 이름들. 평범한 named export 라
   동일성으로 잰다 — 여기서 사본을 만들면 프로브의 프로퍼티 교체가 우회된다. */
const PLAIN_SERVICES = {
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

/* factory 산물 — 합성 루트가 구성한 인스턴스라 동일성 비교가 안 된다. 표면(키)으로 센다.
   이 키 목록은 **소비 계약**이다: 화면 넷의 공개 메서드를 selftest 프로브가 이름으로 부르므로
   (`ctx.services[name]`), 표면이 좁아지면 프로브가 실엔진에서야 죽는다. */
const FACTORY_SERVICES = {
  /* R4 React 화면이 실제로 부르는 typed 전송 객체. selftest는 이 참조의 dispatch/invoke를
     교체해 합성 snapshot과 백엔드 세계가 갈라지지 않게 한다. */
  Client: ["hostReady", "whenReady", "invoke", "initial", "dispatch"],
  Theme: ["set", "toggle", "current", "apply"],
  Personalization: [
    "apply", "currentFontScale", "toggleFontScale", "setFontScale",
    "setMasterWidth", "saveMasterWidth", "masterMin", "masterMax",
  ],
  SheetPicker: ["choose"],
  PathTrack: ["affordances"],
  Relink: ["relinkTemplate"],
  DataPicker: ["init", "open"],
  EditorEntry: [
    "openGuarded", "land", "confirmDiscard", "newDraft",
    "newDraftFromData", "restoreEntryFocus",
  ],
  LibraryScreen: ["init"],
  EditorScreen: ["init", "rerender", "leaveTo", "aimAt"],
  JobScreen: [
    "init", "overwriteBody", "guardBody", "resultExitLine", "confirmDestructiveIfArmed", "log",
    "openPreview", "renderResult", "markResultStale",
  ],
  WorkbenchScreen: ["init", "render", "leaveTo"],
  Nav: ["go", "refresh"],
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

/* selftest 에 넘기는 구성 산물 전수 = 반환 `services` 의 키 전수. R4에서 DataZone은
   React job-read controller로 흡수됐고, 남은 이름만 명시 주입 거처를 유지한다. */
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

test("부팅이 심는 제품 전역은 `__hwpx` **하나**뿐이다(N-10 종착점)", async (t) => {
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

test("은퇴한 별칭은 R4 서비스 축소 뒤에도 전역에 없다(음성 대조)", async (t) => {
  const { host } = await boot(t);

  /* 양성 대조는 위 「전역 프로브가 실제 쓰기를 잡는다」가 진다 — 이 대역에서 쓰기가
     관측된다는 사실이 먼저 서야 아래 부재가 의미를 가진다. */
  const revived = SERVICE_NAMES.filter((name) => name in host.window);
  assert.deepEqual(revived, [],
    `은퇴한 임시 전역이 되살아났습니다: ${revived.join(", ")}`);
  assert.equal("__push" in host.window, false);
  assert.equal(SERVICE_NAMES.length, 26,
    "R4 구성 산물 이름 수가 바뀌었습니다 — typed Client를 포함한 서비스는 26개입니다.");
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

test("앱 셸 구성이 부팅 랜딩(job)을 실제로 찍었다 — 조립이 돌았다는 실행 증거", async (t) => {
  const { host } = await boot(t);

  /* 전신은 ESM 캐시 히트 때문에 이 사실을 다시 볼 수 없어 "firstInstall !== null" 만
     확인했다(사실상 공허했다). 부팅이 호출이 되면서 대역 위에서 실제 랜딩을 잰다. */
  const job = host.byId.get("scr-job");
  assert.ok(job, "앱 셸이 scr-job 을 만지지 않았습니다 — 랜딩이 돌지 않았습니다.");
  assert.equal(job.classList.contains("on"), true,
    "부팅 랜딩이 job 화면을 켜지 않았습니다.");
});

test("합성 루트의 공개 표면은 `bootProduct` 하나다", async (t) => {
  useHostStub(t);

  const module = await import(BOOTSTRAP);

  assert.deepEqual(Object.keys(module), ["bootProduct"],
    "합성 루트가 조립 말고 다른 표면을 냅니다 — 그 자리가 다음 전역의 거처가 됩니다.");
  assert.equal(typeof module.bootProduct, "function");
});

/* ══════════ N-07·N-09 제품 파사드 — 푸시는 **단일 활성 통로**를 지난다 ══════════

   N-07 은 이 자리에서 회귀를 한 번 겪었다: 파사드의 `snapshot` 처리기가 구성 산물 `push` 를
   **값으로 붙들어** 프로브의 가로채기를 우회했고, 프로브는 "푸시 0" 을 보고 그 침묵을 배선
   부재로 읽었다(`mirror_pushes` 1→0, `reject_pushes` 1→0). 당시 수리는 전역 `window.__push`
   지연 판독이었고, N-09 가 만나는 자리를 **포트**로 옮겼다.

   그래서 N-10 의 별칭 삭제는 이 경로를 건드리지 않는다 — 이미 전역에 의존하지 않았다.
   달라진 것은 **손잡이**뿐이다: 전역 대신 반환된 `pushPort`·`bridge` 로 같은 성질을 잰다.
   갈아끼운 통로가 실제로 관측되는지는 `n09_push_port.test.js` 가 실 러너·프로브 경로로
   진다(그쪽에 음성 대조가 있다). */

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

/* ══════════ R2-03 스냅샷 store — 탭은 포트 **하류**에, 채널은 계약 유도로 ══════════ */

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

test("합성 루트는 기반 푸시를 값으로 붙들지 않는다(회귀 되살리기 금지 · 소스 계약)", () => {
  const source = readFileSync(new URL(BOOTSTRAP, import.meta.url), "utf8");
  const body = source.replace(/\/\*[\s\S]*?\*\//g, "");

  /* 되살아나는 모양은 정확히 이것이다: 처리기가 구성 산물 `push` 를 직접 부른다.
     포트를 거치지 않으면 프로브가 갈아끼운 통로를 우회한다. */
  assert.equal(/snapshot:\s*\([^)]*\)\s*=>\s*push\(/.test(body), false,
    "snapshot 처리기가 구성 산물 push 를 값으로 붙들었습니다 — N-07 회귀가 되살아납니다.");
  assert.match(body, /snapshot:\s*\([^)]*\)\s*=>\s*pushPort\.dispatch\(/,
    "snapshot 처리기는 포트로 보내야 합니다.");

  /* 전신은 여기서 `window.__push = pushPort.dispatch` 도 함께 단언했다("두 입구가 갈리지
     않는가"). 입구가 하나가 된 지금 그 단언의 후계는 **전역이 0개**라는 사실 자체다 —
     위 「제품 전역은 __hwpx 하나뿐」 테스트가 진다. */
  assert.equal(/window\.__push/.test(body), false,
    "은퇴한 __push 전역이 되살아났습니다.");
});
