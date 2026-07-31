/* N-05 Packet E — 편집 진입 seam(`editor_entry.js`)의 ESM 전환 계약 테스트.
 *
 * 이 파일이 지키는 것은 진입 seam 의 **경계 넷**이다:
 *
 *  ① 공개 표면 6키(§1-B 표) — 진입문은 하나이고 그 문의 손잡이 수는 계약이다.
 *  ② 의존이 드러나 있는가 — `Modal` 은 명시 import 간선, `bridge`·`navigate` 는 명시 주입.
 *     특히 `navigate` 는 **late-bound 콜백**이어야 한다: 착지처 `Nav` 를 만드는 앱 셸은 이
 *     모듈보다 나중에 평가되고 셸 자신이 이 seam 을 소비하므로, 값으로 캡처하면 모듈 순환과
 *     평가 순서 함정이 동시에 선다. 그래서 "생성 시점에 없던 대상도 호출 시점에 잡힌다"를
 *     실행으로 못박는다 — 소스에 `window.Nav` 가 없다는 정적 단언만으로는 값 캡처를 못 본다.
 *  ③ 포트가 **객체째** 살아 있는가 — Python selftest 프로브는 `window.Bridge.call = stub`
 *     처럼 프로퍼티를 갈아끼운다(app.py 10곳). 메서드를 모듈 스코프 값으로 뽑으면 스텁이
 *     우회돼 프로브가 실물 백엔드로 샌다 — 초록불인 채로.
 *  ④ 제품 규칙(가드 → 확인 → 이동 순서 · 미저장 가드 · 초점 되돌림 1슬롯 · loud 실패)이
 *     전환으로 흔들리지 않았는가. 이건 "번들이 뜬다"로는 못 보는 층이라 흔적을 기록해 센다.
 *
 * 임포트 그래프(modal → popover)는 **평가 시점에 document 를 만진다**(부작용을 init 으로
 * 옮기지 않는 것이 N-05 계약). 정적 import 보다 먼저 대역을 세울 수 없어 전역 대역을 깔고
 * 동적 import 로 연다. 대역은 표준 Web API 만 흉내 내며 제품 전역은 세우지 않는다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

/* ---------------- 최소 DOM 대역 ---------------- */

class FakeEl {
  constructor(id) {
    this.id = id || "";
    this.style = { setProperty() {}, getPropertyValue: () => "" };
    this.dataset = {};
    this.innerHTML = "";
    this.textContent = "";
    this.hidden = false;
    this.isConnected = true;
    this._attrs = {};
    this._listeners = new Map();
    this.classList = { toggle() {}, add() {}, remove() {}, contains: () => false };
    this.focused = 0;
  }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return Object.hasOwn(this._attrs, k) ? this._attrs[k] : null; }
  removeAttribute(k) { delete this._attrs[k]; }
  addEventListener(type, fn, opts) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push({ fn, opts });
  }
  removeEventListener() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  contains() { return false; }
  matches() { return false; }
  focus() { this.focused += 1; }
  blur() {}
  getBoundingClientRect() { return { top: 0, left: 0, width: 10, height: 10, bottom: 10, right: 10 }; }
}

function makeDom() {
  const alerts = [];
  const document = {
    documentElement: new FakeEl("html"),
    body: new FakeEl("body"),
    activeElement: null,
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
    removeEventListener() {},
    createElement: () => new FakeEl(),
  };
  const window = {
    pywebview: { api: {} },
    alert: (m) => alerts.push(String(m)),
    dispatchEvent: () => true,
    addEventListener() {},
    removeEventListener() {},
    innerWidth: 1200,
    innerHeight: 800,
  };
  return { window, document, alerts };
}

function installDom(dom) {
  globalThis.window = dom.window;
  globalThis.document = dom.document;
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });
  globalThis.CSS = { escape: (s) => String(s).replace(/["\\]/g, "\\$&") };
  return dom;
}

const BASELINE = installDom(makeDom());

function freshDom(t) {
  const dom = installDom(makeDom());
  t.after(() => installDom(BASELINE));
  return dom;
}

/* ---------------- 그래프 열기 ---------------- */

const SRC = new URL("../../frontend/js/editor_entry.js", import.meta.url);
const src = fs.readFileSync(SRC, "utf8");

const { createEditorEntry } = await import("../../frontend/js/editor_entry.js");
const { Modal } = await import("../../frontend/js/modal.js");

/* Modal 은 실 DOM 을 만지는 표면이라 **같은 객체의 메서드만** 갈아끼워 호출을 관측한다
   (살아 있는 export 객체 — 서비스가 보는 것과 동일 참조). */
function patchModal(t, log, confirmResult) {
  const saved = { confirm: Modal.confirm, restoreFocus: Modal.restoreFocus };
  Modal.confirm = (opts) => { log.push(["Modal.confirm", opts]); return confirmResult; };
  Modal.restoreFocus = (el) => { log.push(["Modal.restoreFocus", el ? el.id : null]); };
  t.after(() => { Modal.confirm = saved.confirm; Modal.restoreFocus = saved.restoreFocus; });
  return log;
}

/* 한 시나리오의 관측 하니스 — bridge 는 **객체**로 넘기고, 흔적은 한 배열에 순서대로 쌓는다
   (순서가 계약이므로 호출별 카운터로는 부족하다). */
function harness(t, cfg) {
  const opts = cfg || {};
  const log = [];
  const bridge = {
    editorHasUnsavedWork() { log.push(["bridge.editorHasUnsavedWork"]); return opts.unsaved === true; },
    call(...a) { log.push(["bridge.call", ...a]); return opts.callResult; },
    newJobFromData(...a) { log.push(["bridge.newJobFromData", ...a]); return opts.newJobResult; },
    openJobInEditor(...a) { log.push(["bridge.openJobInEditor", ...a]); return opts.openResult; },
  };
  patchModal(t, log, Object.hasOwn(opts, "confirmResult") ? opts.confirmResult : true);
  const entry = createEditorEntry({
    bridge,
    navigate: (...a) => log.push(["navigate", ...a]),
  });
  return { log, bridge, entry, names: () => log.map((r) => r[0]) };
}

/* ================= 1. 공개 표면 ================= */

test("공개 표면 — createEditorEntry 는 계약 6키를 정확히 낸다", (t) => {
  freshDom(t);
  assert.equal(typeof createEditorEntry, "function");
  const entry = createEditorEntry({ bridge: {}, navigate: () => {} });
  assert.deepEqual(Object.keys(entry).sort(),
    ["confirmDiscard", "land", "newDraft", "newDraftFromData", "openGuarded", "restoreEntryFocus"]);
  for (const k of Object.keys(entry)) assert.equal(typeof entry[k], "function", k);
});

test("파일당 export 는 하나 — export default 없음", () => {
  assert.equal(/export\s+default/.test(src), false, "export default 금지");
  const names = [...src.matchAll(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  assert.deepEqual(names, ["createEditorEntry"]);
  assert.ok(src.includes("export function createEditorEntry({ bridge, navigate }) {"),
    "포트는 구조분해 인자로 받는다");
});

/* ================= 2. 의존이 드러나 있다 ================= */

test("Modal 은 명시 import 간선이고 별칭이 없다", () => {
  const found = [...src.matchAll(/^import .*$/gm)].map((m) => m[0]);
  assert.deepEqual(found, ['import { Modal } from "./modal.js";'],
    "import 목록이 계약과 동일(별칭 금지 — Modal.confirm( 문자열 감사가 별칭에 침묵한다)");
  assert.ok(src.includes("Modal.confirm({"), "파괴 확인은 Modal.confirm 이 진다");
  assert.ok(src.includes("Modal.restoreFocus("), "초점 되돌림 규칙은 모달 것을 재사용한다");
});

test("음성 조건 — IIFE·자기 전역·제품 전역 조회·Object.assign(window) 전부 0", () => {
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const PRODUCT = /window\.(Modal|Popover|Bridge|Nav|escHtml|SheetPicker|PathTrack|Preserve|Intent|DataPicker|EditorEntry|[A-Za-z]*Screen|__push|AppCloseGuard)\b/;
  assert.equal(/^\(function\s*\(/m.test(code), false, "top-level IIFE 금지");
  assert.equal(/^\}\)\(\);/m.test(code), false, "top-level IIFE 금지");
  assert.equal(/(window|globalThis)\.[A-Za-z_$][\w$]*\s*=[^=]/.test(code), false, "자기 전역 생산 금지");
  assert.equal(PRODUCT.test(code), false, "제품 전역 조회 금지");
  assert.equal(code.includes("Object.assign(window"), false, "Object.assign(window) 금지");
  // 개별 이름으로도 센다 — 위 정규식이 언젠가 느슨해져도 이 셋은 남는다.
  for (const g of ["window.Modal", "window.Nav", "window.Bridge"]) {
    assert.equal(code.includes(g), false, `${g} 조회 0`);
  }
  // 표준 Web API 는 그대로 — loud 실패의 통로다.
  assert.equal((code.match(/window\.alert\(/g) || []).length, 2, "loud 실패 통로 2곳 보존");
});

test("bridge 는 객체로만 쓴다 — 모듈/팩토리 스코프에 메서드를 뽑지 않는다", () => {
  assert.equal(/^\s*const\s+\w+\s*=\s*bridge\.\w+\s*;/m.test(src), false,
    "메서드 값 캡처 금지(프로브의 프로퍼티 교체가 우회된다)");
  const uses = [...src.matchAll(/\bbridge\.(\w+)/g)].map((m) => m[1]).sort();
  assert.deepEqual([...new Set(uses)],
    ["call", "editorHasUnsavedWork", "newJobFromData", "openJobInEditor"]);
});

test("모듈 상태는 entryFocus 1슬롯뿐 — 팩토리 밖에 가변 상태 0", () => {
  const head = src.slice(0, src.indexOf("export function createEditorEntry"));
  assert.equal(/^\s*(let|var)\s/m.test(head), false, "모듈 스코프 가변 상태 0");
  const body = src.slice(src.indexOf("export function createEditorEntry"));
  const mutables = [...body.matchAll(/^\s{2}(?:let|var)\s+(\w+)/gm)].map((m) => m[1]);
  assert.deepEqual(mutables, ["entryFocus"], "진입 슬롯은 하나뿐(늘리지 않는다)");
});

/* ================= 3. navigate 는 late-bound ================= */

test("navigate — 생성 시점에 없던 대상도 호출 시점에 잡힌다(모듈 순환 절단의 근거)", (t) => {
  freshDom(t);
  let Nav = null;                                   // 앱 셸은 아직 평가되지 않았다
  const seen = [];
  const entry = createEditorEntry({ bridge: {}, navigate: (...a) => Nav.go(...a) });
  assert.throws(() => entry.land(), TypeError, "대상이 없으면 조용히 넘어가지 않는다");

  Nav = { go: (...a) => seen.push(["A", ...a]) };    // 셸이 뒤늦게 선다
  entry.land();
  Nav = { go: (...a) => seen.push(["B", ...a]) };    // 재배선도 다음 호출부터 보인다
  entry.land();
  assert.deepEqual(seen, [["A", "editor", { force: true }], ["B", "editor", { force: true }]]);
});

test("navigate — 착지 인자는 종전 Nav.go 그대로다(화면 · force)", (t) => {
  freshDom(t);
  const h = harness(t);
  h.entry.land();
  assert.deepEqual(h.log, [["navigate", "editor", { force: true }]]);
  // 착지 호출점은 land() 하나 — 축자 복붙이 생기면 착지 변경이 드리프트한다.
  assert.equal((src.match(/navigate\(/g) || []).length, 1);
});

/* ================= 4. 포트 프로퍼티 교체가 보인다(프로브 경로 생존) ================= */

test("포트 교체 — bridge 메서드를 갈아끼우면 seam 이 새 함수를 본다", async (t) => {
  freshDom(t);
  const seen = [];
  const bridge = {
    editorHasUnsavedWork: () => false,
    openJobInEditor: (...a) => { seen.push(["A", ...a]); },
  };
  const entry = createEditorEntry({ bridge, navigate: () => {} });
  assert.equal(await entry.openGuarded("작업1", { entry_reason: "library" }), true);
  bridge.openJobInEditor = (...a) => { seen.push(["B", ...a]); };   // 프로브가 하는 일
  assert.equal(await entry.openGuarded("작업2", { entry_reason: "library" }), true);
  assert.deepEqual(seen, [
    ["A", "작업1", { entry_reason: "library" }],
    ["B", "작업2", { entry_reason: "library" }],
  ]);
});

test("포트 교체 — 미저장 판정도 갈아끼운 bridge.editorHasUnsavedWork 를 본다(stale 금지)", async (t) => {
  freshDom(t);
  const log = [];
  patchModal(t, log, false);
  const bridge = { editorHasUnsavedWork: () => false };
  const entry = createEditorEntry({ bridge, navigate: () => {} });
  assert.equal(await entry.confirmDiscard("본문"), true, "미저장 없으면 조용히 통과");
  bridge.editorHasUnsavedWork = () => true;
  assert.equal(await entry.confirmDiscard("본문"), false, "미저장이 생기면 다음 질의가 본다");
  assert.deepEqual(log.map((r) => r[0]), ["Modal.confirm"]);
});

/* ================= 5. 미저장 가드 — 확인을 거치고, 취소하면 안 움직인다 ================= */

test("가드 — 미저장이 없으면 확인 없이 통과한다(진입 셋 전부)", async (t) => {
  freshDom(t);
  for (const [name, run] of [
    ["newDraft", (e) => e.newDraft()],
    ["newDraftFromData", (e) => e.newDraftFromData({ entry_reason: "x" })],
    ["openGuarded", (e) => e.openGuarded("작업", { entry_reason: "library" })],
  ]) {
    const h = harness(t, { unsaved: false });
    assert.equal(await run(h.entry), true, name);
    assert.equal(h.names().includes("Modal.confirm"), false, `${name}: 미저장 없으면 안 묻는다`);
    assert.equal(h.names().at(-1), "navigate", `${name}: 착지한다`);
  }
});

test("가드 — 미저장이 있으면 확인을 거치고, 취소는 이동을 막는다(진입 셋 전부)", async (t) => {
  const dom = freshDom(t);
  const CASES = [
    ["newDraft", (e) => e.newDraft(), "새 작업을 시작하면"],
    ["newDraftFromData", (e) => e.newDraftFromData({ entry_reason: "x" }), "이 데이터로 새 작업을 시작하면"],
    ["openGuarded", (e) => e.openGuarded("작업A", { entry_reason: "library" }), "'작업A' 편집을 열면"],
  ];
  for (const [name, run, lead] of CASES) {
    const h = harness(t, { unsaved: true, confirmResult: false });
    assert.equal(await run(h.entry), false, `${name}: 취소는 false 를 낸다`);
    const confirm = h.log.find((r) => r[0] === "Modal.confirm")[1];
    assert.ok(confirm.body.startsWith(lead), `${name}: 문안이 그 흐름의 것이다`);
    assert.ok(confirm.body.includes("사라지는 것: 이름 · 데이터 · 매핑"), `${name}: 잃는 것을 말한다`);
    assert.equal(confirm.confirmLabel, "버리고 계속");
    assert.equal(confirm.cancelLabel, "취소");
    assert.equal(h.names().includes("navigate"), false, `${name}: 취소 뒤 이동 0`);
    assert.deepEqual(h.names().filter((n) => n.startsWith("bridge.") && n !== "bridge.editorHasUnsavedWork"),
      [], `${name}: 취소 뒤 백엔드 변이 0`);
  }
  assert.deepEqual(dom.alerts, [], "취소는 실패가 아니다 — alert 0");
});

test("가드 — 확인하면 백엔드가 돌고 착지한다", async (t) => {
  freshDom(t);
  const h = harness(t, { unsaved: true, confirmResult: true });
  assert.equal(await h.entry.newDraft(), true);
  assert.deepEqual(h.log, [
    ["bridge.editorHasUnsavedWork"],
    ["Modal.confirm", h.log[1][1]],
    ["bridge.call", "editor", "new_session", {}],
    ["navigate", "editor", { force: true }],
  ]);
});

/* ================= 6. 이동 순서 — 가드 → 확인 → 이동 ================= */

test("순서 — openGuarded 는 가드 → 확인 → 로드 → 이동을 이 순서로 지난다", async (t) => {
  freshDom(t);
  const h = harness(t, { unsaved: true, confirmResult: true });
  assert.equal(await h.entry.openGuarded("작업A", { entry_reason: "library", section: "filename" }), true);
  assert.deepEqual(h.names(),
    ["bridge.editorHasUnsavedWork", "Modal.confirm", "bridge.openJobInEditor", "navigate"]);
  // 단일 정의 seam 은 **인자까지 단일**이다 — 문맥이 여기서 새면 모든 진입이 자발적 진입으로
  // 떨어져 배너·복귀처가 통째로 사라진다.
  assert.deepEqual(h.log.find((r) => r[0] === "bridge.openJobInEditor").slice(1),
    ["작업A", { entry_reason: "library", section: "filename" }]);
});

test("순서 — newDraftFromData 는 가드 → 확인 → 새 작업 → 이동, 문맥 부재는 {} 로", async (t) => {
  freshDom(t);
  const h = harness(t, { unsaved: true, confirmResult: true });
  assert.equal(await h.entry.newDraftFromData(), true);
  assert.deepEqual(h.names(),
    ["bridge.editorHasUnsavedWork", "Modal.confirm", "bridge.newJobFromData", "navigate"]);
  assert.deepEqual(h.log.find((r) => r[0] === "bridge.newJobFromData").slice(1), [{}]);
});

/* ================= 7. loud 실패 — 사유를 재진술한다 ================= */

test("loud — 진입 실패는 사유를 재진술하고 이동하지 않는다(조용한 삼킴 0)", async (t) => {
  for (const [name, run] of [
    ["openGuarded", (e) => e.openGuarded("작업A", { entry_reason: "library" })],
    ["newDraftFromData", (e) => e.newDraftFromData({ entry_reason: "x" })],
  ]) {
    const dom = freshDom(t);
    const key = name === "openGuarded" ? "openResult" : "newJobResult";
    const h = harness(t, { unsaved: false, [key]: "ERROR: 템플릿 파일을 찾지 못했습니다.  " });
    assert.equal(await run(h.entry), false, `${name}: 실패는 false`);
    assert.deepEqual(dom.alerts, ["템플릿 파일을 찾지 못했습니다."],
      `${name}: 접두어를 벗기고 사유를 그대로 재진술한다`);
    assert.equal(h.names().includes("navigate"), false, `${name}: 실패 뒤 이동 0`);
    installDom(BASELINE);
  }
});

test("loud — ERROR 접두어가 없는 반환은 성공이다(정상 경로를 실패로 읽지 않는다)", async (t) => {
  const dom = freshDom(t);
  const h = harness(t, { unsaved: false, openResult: { ok: true } });
  assert.equal(await h.entry.openGuarded("작업A", {}), true);
  assert.deepEqual(dom.alerts, []);
  assert.equal(h.names().at(-1), "navigate");
});

/* ================= 8. 초점 되돌림 — 1슬롯 왕복 ================= */

test("초점 — 취소 뒤 restoreEntryFocus 가 진입 지점으로 되돌린다", async (t) => {
  const dom = freshDom(t);
  const btn = new FakeEl("btn-entry");
  dom.document.activeElement = btn;
  const h = harness(t, { unsaved: true, confirmResult: false });
  assert.equal(await h.entry.openGuarded("작업A", {}), false);
  dom.document.activeElement = new FakeEl("elsewhere");   // 모달이 자리를 옮겨 놓은 뒤
  h.entry.restoreEntryFocus();
  assert.deepEqual(h.log.filter((r) => r[0] === "Modal.restoreFocus"), [["Modal.restoreFocus", "btn-entry"]]);
});

test("초점 — 실패 뒤에도 되돌릴 자리가 남아 있다", async (t) => {
  const dom = freshDom(t);
  dom.document.activeElement = new FakeEl("btn-repair");
  const h = harness(t, { unsaved: false, openResult: "ERROR: 손상" });
  assert.equal(await h.entry.openGuarded("작업A", {}), false);
  h.entry.restoreEntryFocus();
  assert.deepEqual(h.log.filter((r) => r[0] === "Modal.restoreFocus"), [["Modal.restoreFocus", "btn-repair"]]);
});

test("초점 — 1슬롯이라 두 번 되돌리면 두 번째는 빈손이다(옛 자리 재사용 금지)", async (t) => {
  const dom = freshDom(t);
  dom.document.activeElement = new FakeEl("btn-A");
  const h = harness(t, { unsaved: false });
  await h.entry.newDraft();
  h.entry.restoreEntryFocus();
  h.entry.restoreEntryFocus();
  assert.deepEqual(h.log.filter((r) => r[0] === "Modal.restoreFocus"),
    [["Modal.restoreFocus", "btn-A"], ["Modal.restoreFocus", null]]);
});

test("초점 — 새 진입이 슬롯을 덮어쓴다(마지막 문 하나만 기억)", async (t) => {
  const dom = freshDom(t);
  const h = harness(t, { unsaved: false });
  dom.document.activeElement = new FakeEl("btn-A");
  await h.entry.openGuarded("A", {});
  dom.document.activeElement = new FakeEl("btn-B");
  await h.entry.openGuarded("B", {});
  h.entry.restoreEntryFocus();
  assert.deepEqual(h.log.filter((r) => r[0] === "Modal.restoreFocus"), [["Modal.restoreFocus", "btn-B"]]);
});

test("초점 — 진입 셋 모두 확인 **앞에서** 자리를 기억한다", () => {
  // 정적 계측: 정의 1 + 진입 3. 진입이 늘면 이 수도 함께 늘어야 한다.
  assert.equal((src.match(/rememberEntryFocus\(\)/g) || []).length, 4);
  for (const fn of ["async function newDraft()", "async function newDraftFromData(context)",
    "async function openGuarded(name, context)"]) {
    const body = src.slice(src.indexOf(fn));
    const remember = body.indexOf("rememberEntryFocus()");
    const confirm = body.indexOf("confirmDiscard(");
    assert.ok(remember >= 0 && remember < confirm, `${fn}: 확인 앞에서 기억한다`);
  }
});

/* ================= 9. native 확인 재도입 금지 ================= */

test("확인은 Modal 이 진다 — native confirm/prompt 재도입 0", () => {
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.equal(/\bwindow\.(confirm|prompt)\s*\(/.test(code), false, "native 확인 금지");
  assert.equal(/(^|[^.\w])(confirm|prompt)\s*\(/.test(code.replace(/Modal\.confirm\(/g, "")), false,
    "맨손 confirm/prompt 금지");
});

/* ================= 10. 팩토리 독립성 ================= */

test("팩토리를 두 번 부르면 진입 슬롯도 따로 산다(중앙은 1회만 부른다)", async (t) => {
  const dom = freshDom(t);
  const log = [];
  patchModal(t, log, true);
  const bridge = { editorHasUnsavedWork: () => false, call: () => {} };
  const a = createEditorEntry({ bridge, navigate: () => {} });
  const b = createEditorEntry({ bridge, navigate: () => {} });
  assert.notEqual(a, b);
  dom.document.activeElement = new FakeEl("btn-A");
  await a.newDraft();
  b.restoreEntryFocus();                       // b 는 자기 슬롯이 비어 있다
  a.restoreEntryFocus();
  assert.deepEqual(log.filter((r) => r[0] === "Modal.restoreFocus"),
    [["Modal.restoreFocus", null], ["Modal.restoreFocus", "btn-A"]]);
});
