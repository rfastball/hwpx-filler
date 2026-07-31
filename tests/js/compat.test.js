/* 중앙 호환 계층 계약 — 별칭은 정확히 열아홉, 정확히 한 번, 올바른 객체에 걸린다.

   compat 은 "동작을 바꾸지 않는 파일"이라 동작 테스트로는 보이지 않는다. 여기서 세는 것은
   결과가 아니라 **생산 자리와 횟수**다(#372 D-05).

   N-05 부터 compat 은 서비스 열다섯을 끌어오는데 그중 셋(`popover`·`undo_toast`·`pathtrack`)은
   **평가/구성 시점에 document 리스너를 붙인다**. 그래서 정적 import 로는 대역을 먼저 세울 수
   없고, 전역 대역을 깐 뒤 동적 import 를 쓴다. 대역은 제품 전역을 하나도 만들지 않으며 매
   테스트 뒤 걷는다 — 남겨두면 다음 테스트의 "전역 0" 관측을 오염시킨다. */
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
};

const ALIASES = [
  ...Object.keys(PLAIN_ALIASES),
  ...Object.keys(FACTORY_ALIASES),
].sort();

/* Node 에는 window·document 가 없다. 이 대역은 compat 이 끌어오는 모듈이 **평가되기만** 하면
   되는 최소치다 — 거동은 각 서비스의 전용 테스트가 본다. */
function useHostStub(t) {
  const hadWindow = Object.hasOwn(globalThis, "window");
  const hadDocument = Object.hasOwn(globalThis, "document");
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;

  const listeners = [];
  globalThis.document = {
    addEventListener: (type, fn, opts) => listeners.push({ type, fn, opts }),
    removeEventListener: () => {},
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => ({ style: {}, classList: { add() {}, remove() {} } }),
    body: { appendChild() {} },
    documentElement: { style: {}, setAttribute() {}, getAttribute: () => null },
  };
  globalThis.window = {
    addEventListener: (type, fn, opts) => listeners.push({ type, fn, opts }),
    removeEventListener: () => {},
    /* compat 이 평가 시점에 붙드는 유일한 제품 전역. 객체째 넘어가는지 여기서 본다. */
    Bridge: { call() {}, onPush() {} },
  };

  t.after(() => {
    if (hadWindow) globalThis.window = previousWindow;
    else delete globalThis.window;
    if (hadDocument) globalThis.document = previousDocument;
    else delete globalThis.document;
  });
  return { window: globalThis.window, listeners };
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

test("compat 이 열아홉 별칭을 만들고 올바른 객체에 건다", async (t) => {
  const host = useHostStub(t);

  const module = await import(COMPAT);
  firstInstall = module;

  const installed = Object.keys(host.window)
    .filter((key) => key !== "addEventListener" && key !== "removeEventListener"
      && key !== "Bridge")
    .sort();

  assert.deepEqual(installed, ALIASES);
  assert.equal(installed.length, 19);

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
