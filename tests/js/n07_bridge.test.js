/* bridge.js 의 ESM factory 전환(N-07 lane F) 특성화 테스트.
 *
 * 기대값은 **전환 이전 동작**이다: IIFE 껍질을 벗기고 두 전역 생산을 factory 반환으로 바꾼
 * 기계적 작업이므로, 이 파일이 초록이면 "껍질만 바뀌고 왕복은 그대로"가 참이다. 브리지는
 * 인자 강제(`|| {}`·`!!`·`Math.round`)와 반환 무가공이 곧 계약이라 23개 통로를 표로 전수한다.
 *
 * N-07 에서 백엔드 판독이 이 파일 하나로 좁혀졌다 — 창 닫기 확인 두 호출과 준비 술어
 * (`hostReady`)가 합류해 21 → 23 이 됐다. 그 둘도 같은 표에서 함께 센다.
 *
 * DOM 대역은 없다. 브리지는 화면-불가지라 `window.pywebview` 하나면 충분하고, 그 최소성이
 * 이 모듈이 화면 로직을 모른다는 것의 실행 증거다.
 */
import { after, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC_URL = new URL("../../frontend/js/bridge.js", import.meta.url);
const SRC = readFileSync(SRC_URL, "utf8");

const WIN = { pywebview: null };
globalThis.window = WIN;
after(() => { delete globalThis.window; });

const mod = await import("../../frontend/js/bridge.js");
const { createBridge } = mod;

/* ────────────────────── 호스트 대역 ────────────────────── */

/** 파이썬 쪽 이름 전수 — 브리지가 부르는 `pywebview.api.*` 의 실제 표면. */
const API_NAMES = [
  "initial", "dispatch", "pick_data_file", "load_data_sheet", "import_template_file",
  "import_templates_folder", "copy_clipboard", "pick_output_folder", "generate",
  "editor_has_unsaved_work", "open_job_in_editor", "new_job_from_data", "reveal_corrupt_job",
  "pick_pool_data_file", "pick_template_path", "open_path", "reveal_path", "copy_path",
  "set_theme", "set_font_scale", "set_master_width",
  "confirm_window_close", "cancel_window_close",
];

let CALLS = [];
let RETURNS = null;

function installHost() {
  CALLS = [];
  RETURNS = { sentinel: true };
  const api = {};
  for (const name of API_NAMES) {
    api[name] = (...args) => { CALLS.push([name, args]); return RETURNS; };
  }
  WIN.pywebview = { api };
}

beforeEach(installHost);

/** [브리지 메서드, 백엔드 메서드, 호출 인자, 백엔드가 받아야 할 인자] — 23 전수. */
const DELEGATIONS = [
  ["initial", "initial", ["job"], ["job"]],
  ["call", "dispatch", ["job", "refresh", { q: 1 }], ["job", "refresh", { q: 1 }]],
  ["pickDataFile", "pick_data_file", ["job"], ["job"]],
  ["loadDataSheet", "load_data_sheet", ["job", "C:\\a.xlsx", "Sheet2"],
    ["job", "C:\\a.xlsx", "Sheet2"]],
  ["importTemplateFile", "import_template_file", ["editor"], ["editor"]],
  ["importTemplatesFolder", "import_templates_folder", ["C:\\t", true, ["a.hwpx"]],
    ["C:\\t", true, ["a.hwpx"]]],
  ["copyClipboard", "copy_clipboard", ["workbench", "tok-1"], ["workbench", "tok-1"]],
  ["pickOutputFolder", "pick_output_folder", ["job"], ["job"]],
  ["generate", "generate", ["job", true], ["job", true]],
  ["editorHasUnsavedWork", "editor_has_unsaved_work", [], []],
  ["openJobInEditor", "open_job_in_editor", ["갑근세", { entry_reason: "detail" }],
    ["갑근세", { entry_reason: "detail" }]],
  ["newJobFromData", "new_job_from_data", [{ from: "job" }], [{ from: "job" }]],
  ["revealCorruptJob", "reveal_corrupt_job", ["C:\\x.json"], ["C:\\x.json"]],
  ["pickPoolDataFile", "pick_pool_data_file", [], []],
  ["pickTemplatePath", "pick_template_path", [], []],
  ["openPath", "open_path", ["C:\\o"], ["C:\\o"]],
  ["revealPath", "reveal_path", ["C:\\r"], ["C:\\r"]],
  ["copyPath", "copy_path", ["C:\\c"], ["C:\\c"]],
  ["setTheme", "set_theme", ["dark"], ["dark"]],
  ["setFontScale", "set_font_scale", ["large"], ["large"]],
  ["setMasterWidth", "set_master_width", [240], [240]],
  ["confirmWindowClose", "confirm_window_close", [], []],
  ["cancelWindowClose", "cancel_window_close", [], []],
];

const HOST_METHODS = DELEGATIONS.map(([name]) => name);
const NON_HOST_MEMBERS = ["onPush", "hostReady"];

/* ══════════════ 1. 공개 표면 ══════════════ */

test("공개 표면 — createBridge() → { bridge, push }, named export 정확히 하나", () => {
  assert.deepEqual(Object.keys(mod), ["createBridge"], "export 는 정확히 하나(named)");
  assert.equal(mod.default, undefined, "export default 금지");
  assert.equal(typeof createBridge, "function");

  const made = createBridge();
  assert.deepEqual(Object.keys(made), ["bridge", "push"]);
  assert.equal(typeof made.push, "function");
  assert.equal(typeof made.bridge, "object");
});

test("bridge 표면은 호스트 메서드 23 + onPush + hostReady 로 정확히 25 다", () => {
  const { bridge } = createBridge();
  const keys = Object.keys(bridge);

  assert.deepEqual([...keys].sort(), [...HOST_METHODS, ...NON_HOST_MEMBERS].sort());
  assert.equal(HOST_METHODS.length, 23, "호스트 메서드는 21 + 창 닫기 2 = 23");
  assert.equal(keys.length, 25);
  for (const key of keys) assert.equal(typeof bridge[key], "function", `${key} 가 함수가 아니다`);
});

/* ══════════════ 2. 위임 전수 — 이름·인자·반환 ══════════════ */

for (const [method, apiName, args, expected] of DELEGATIONS) {
  test(`${method} → pywebview.api.${apiName} 로 인자를 그대로 넘긴다`, () => {
    const { bridge } = createBridge();

    const out = bridge[method](...args);

    assert.deepEqual(CALLS, [[apiName, expected]]);
    assert.equal(out, RETURNS, "반환은 감싸지 않고 그대로 통과한다");
  });
}

test("인자 강제 — call 의 payload 는 || {}, importTemplatesFolder 는 || null 과 !!", () => {
  const { bridge } = createBridge();

  bridge.call("job", "refresh");
  assert.deepEqual(CALLS, [["dispatch", ["job", "refresh", {}]]]);

  CALLS = [];
  bridge.importTemplatesFolder(null, 0, null);
  assert.deepEqual(CALLS, [["import_templates_folder", [null, false, null]]]);

  CALLS = [];
  bridge.importTemplatesFolder("", undefined, undefined);
  assert.deepEqual(CALLS, [["import_templates_folder", [null, false, null]]],
    "빈 문자열도 || 로 null 이 된다(종전 동작)");

  CALLS = [];
  const files = ["a.hwpx"];
  bridge.importTemplatesFolder("C:\\t", 1, files);
  assert.deepEqual(CALLS, [["import_templates_folder", ["C:\\t", true, files]]]);
  assert.equal(CALLS[0][1][2], files, "후보 목록은 사본이 아니라 그 배열이다");
});

test("인자 강제 — generate 는 !!, openJobInEditor·newJobFromData 는 || {}", () => {
  const { bridge } = createBridge();

  bridge.generate("job", 0);
  assert.deepEqual(CALLS, [["generate", ["job", false]]]);

  CALLS = [];
  bridge.generate("job", "yes");
  assert.deepEqual(CALLS, [["generate", ["job", true]]]);

  CALLS = [];
  bridge.openJobInEditor("갑근세");
  assert.deepEqual(CALLS, [["open_job_in_editor", ["갑근세", {}]]]);

  CALLS = [];
  bridge.newJobFromData();
  assert.deepEqual(CALLS, [["new_job_from_data", [{}]]]);
});

test("인자 강제 — setMasterWidth 는 Math.round 로 정수를 보낸다", () => {
  const { bridge } = createBridge();

  bridge.setMasterWidth(10.4);
  bridge.setMasterWidth(10.6);
  bridge.setMasterWidth(239.5);

  assert.deepEqual(CALLS, [
    ["set_master_width", [10]],
    ["set_master_width", [11]],
    ["set_master_width", [240]],
  ]);
});

test("반환 무가공 — 값도 promise 도, 거절도 그대로 통과한다(삼키지 않는다)", async () => {
  const { bridge } = createBridge();

  RETURNS = "ERROR: 파일을 열 수 없습니다";
  assert.equal(bridge.openPath("C:\\x"), "ERROR: 파일을 열 수 없습니다");

  const boom = new Error("백엔드 거절");
  RETURNS = Promise.reject(boom);
  const returned = bridge.generate("job", true);
  assert.equal(returned instanceof Promise, true);
  await assert.rejects(() => returned, (err) => err === boom);
});

/* ══════════════ 3. 살아 있는 객체 — 프로퍼티 교체가 관측된다 ══════════════ */

test("구성 뒤 프로퍼티를 교체하면 소비자가 스텁을 본다(selftest 프로브 계약)", () => {
  const { bridge } = createBridge();
  // 소비자는 객체 참조만 들고 호출 시점에 메서드를 찾는다 — 값으로 뽑으면 스텁이 우회된다.
  const consumer = (host) => host.call("job", "refresh", {});

  assert.deepEqual(consumer(bridge), RETURNS);
  assert.deepEqual(CALLS, [["dispatch", ["job", "refresh", {}]]]);

  const seen = [];
  bridge.call = (...args) => { seen.push(args); return "stubbed"; };
  CALLS = [];

  assert.equal(consumer(bridge), "stubbed");
  assert.deepEqual(seen, [["job", "refresh", {}]]);
  assert.deepEqual(CALLS, [], "교체 뒤 실물 백엔드로 새면 안 된다");
});

test("소스가 백엔드 핸들을 미리 뽑아 두지 않는다 — 매 호출 새로 조회한다", () => {
  assert.equal(/(?:const|let|var)\s+[^=\n]*=\s*window\.pywebview/.test(SRC), false,
    "pywebview 핸들을 변수로 캡처하면 호스트 교체가 관측되지 않는다");
  assert.equal(/\{[^}\n]*\}\s*=\s*window\.pywebview/.test(SRC), false,
    "구조분해로 메서드를 미리 뽑으면 프로퍼티 교체가 우회된다");
  assert.equal((SRC.match(/window\.pywebview\.api\./g) || []).length, 23,
    "백엔드 호출은 23개, 전부 호출 시점 조회여야 한다");
});

/* ══════════════ 4. push — 관측 푸시 디스패치 ══════════════ */

test("push 는 등록 순서대로 그 화면의 모든 렌더러를 부른다", () => {
  const { bridge, push } = createBridge();
  const order = [];
  bridge.onPush("job", (snap) => order.push(["a", snap]));
  bridge.onPush("job", (snap) => order.push(["b", snap]));
  bridge.onPush("editor", (snap) => order.push(["c", snap]));

  const snapshot = { rows: 3 };
  push("job", snapshot);

  assert.deepEqual(order, [["a", snapshot], ["b", snapshot]]);
  assert.equal(order[0][1], snapshot, "스냅샷은 사본이 아니라 그 객체다");
});

test("미구독 화면 push 는 조용한 무동작이다(던지지 않는다)", () => {
  const { bridge, push } = createBridge();
  const seen = [];
  bridge.onPush("job", (snap) => seen.push(snap));

  push("pool", { any: 1 });
  push("job", { n: 1 });

  assert.deepEqual(seen, [{ n: 1 }]);
});

test("factory 는 매번 독립된 구독 표를 만든다", () => {
  const first = createBridge();
  const second = createBridge();
  const seen = [];
  first.bridge.onPush("job", (snap) => seen.push(snap));

  second.push("job", { from: "second" });
  assert.deepEqual(seen, [], "다른 인스턴스의 구독을 보면 안 된다");

  first.push("job", { from: "first" });
  assert.deepEqual(seen, [{ from: "first" }]);
});

/* ══════════════ 5. hostReady — 준비 술어 ══════════════ */

test("hostReady() 는 window.pywebview.api 존재의 순간 판정이다", () => {
  const { bridge } = createBridge();
  assert.equal(bridge.hostReady(), true);

  WIN.pywebview = null;
  assert.equal(bridge.hostReady(), false, "브라우저 단독 프리뷰");

  WIN.pywebview = {};
  assert.equal(bridge.hostReady(), false, "창은 있지만 api 가 아직 없다");

  WIN.pywebview = { api: {} };
  assert.equal(bridge.hostReady(), true);

  delete WIN.pywebview;
  assert.equal(bridge.hostReady(), false);
  assert.equal(typeof bridge.hostReady(), "boolean", "맨 boolean — 캐시·재시도 없음");
});

test("hostReady 는 캐시하지 않는다 — 같은 인스턴스가 부재→존재 전이를 본다", () => {
  WIN.pywebview = null;
  const { bridge } = createBridge();
  assert.equal(bridge.hostReady(), false);

  installHost();
  assert.equal(bridge.hostReady(), true);
});

/* ══════════════ 6. 소스 음성 계약 ══════════════ */

test("소스 — IIFE 0, 자기 전역 0, export 정확히 하나, default 없음", () => {
  assert.equal(SRC.match(/^\(function \(\) \{/m), null, "IIFE 껍질이 남아 있다");
  assert.deepEqual(SRC.match(/^\s*(?:window|globalThis)\.[A-Za-z_$][A-Za-z0-9_$]*\s*=/gm) || [],
    [], "자기 전역을 만든다 — 별칭 생산은 중앙 compat 하나뿐이다");
  assert.equal((SRC.match(/^export\s/gm) || []).length, 1);
  assert.equal(SRC.includes("export default"), false);
  assert.match(SRC, /^export function createBridge\(\) \{/m);
});

test("소스 — 제품 전역 판독 0, 테스트 훅 0", () => {
  for (const name of ["window.Bridge", "window.__push", "globalThis.Bridge",
    "window.Nav", "window.AppCloseGuard", "window.Theme", "window.Personalization"]) {
    assert.equal(SRC.includes(name), false, `${name} 판독이 남아 있다`);
  }
  assert.equal(SRC.includes("__hwpxTest"), false, "테스트 훅은 N-09 소관이다");
});

test("소스 — 제품 결정을 담은 JSDoc 이 살아남았다", () => {
  assert.equal((SRC.match(/\/\*\*/g) || []).length >= 20, true,
    "메서드 주석은 제품 결정을 담는다 — 전환에서 잃으면 안 된다");
  for (const phrase of [
    "확인 대상 = 복사 대상",
    "한 채널 복수 구독",
    "데이터의 정체는 **보내지 않는다**",
    "오리진 비의존",
    "미구독 화면은",
  ]) {
    assert.equal(SRC.includes(phrase), true, `사라진 주석: ${phrase}`);
  }
});
