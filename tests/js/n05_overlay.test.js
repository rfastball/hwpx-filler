/* 오버레이 스택(modal · surface_sheet)의 특성화 테스트 — N-05 패킷 B, R3-01(#410) 제자리 진화.
 *
 * 기대값은 전부 **이관 이전** 동작이다. R3-01 은 판정(스택·직렬화·Escape/Tab/복귀)을
 * 트리-불가지 엔진(src/overlay/engine.ts)으로, promise 다이얼로그·토스트의 DOM 집행을
 * React host 의 컨트롤러(src/overlay/host.ts)로 옮겼다 — 이 파일이 초록이면 "거처만
 * 바뀌고 거동은 그대로"가 참이다. 그래서 하니스는 대역이 아니라 **실물 사슬**을 세운다:
 * 실물 modal.js(파사드) → 실물 엔진 → 실물 컨트롤러(createOverlayDialogController)를
 * 스텁 fixture 위에 그대로 굴린다.
 *
 * 왜 정적 소스 대조로 부족한가: 정적 검사는 **규칙의 존재**를 보고 **결과**를 못 본다.
 * 특히 document capture 리스너의 **등록 순서** — dismissal 계열(popover)은 bootProduct
 * 구성 시 상시, 모달 keydown 은 첫 open 부착(instance.ts)이다. 구성이 언제나 open 보다
 * 앞이므로 Escape 한 번이 열린 팝오버와 최상위 모달을 그 순서로 닫는다(개정 4·10).
 * 하니스가 bootProduct 의 구성 몫(dismissal 부착·host 컨트롤러 기립)을 재현하고,
 * 아래 마지막 테스트가 그 순서의 그물이다.
 *
 * DOM 은 node:test 만으로 돌리려고 손으로 세운 최소 스텁이다. 전역(window/document/
 * Element/Node)은 매 테스트 뒤 걷어낸다 — 다만 **객체 정체성**은 유지한다. 구성 시
 * 부착(dismissal)이 그 document 에 걸려 있기 때문에, 새 객체로 갈아끼우면 검사 대상인
 * 등록 순서 자체가 사라진다.
 */
import { after, afterEach, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

/* ────────────────────────── 최소 DOM 스텁 ────────────────────────── */

const trace = { on: false, log: [] };
function mark(entry) { if (trace.on) trace.log.push(entry); }

class StubNode {}

function makeStyle() {
  const props = Object.create(null);
  return {
    props,
    setProperty(name, value) { props[name] = String(value); },
    removeProperty(name) { delete props[name]; },
    getPropertyValue(name) { return props[name] === undefined ? "" : props[name]; },
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
  return String(selector)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .some((s) => matchesCompound(el, s));
}

class StubElement extends StubNode {
  constructor(tag) {
    super();
    this.tagName = String(tag).toUpperCase();
    this.id = "";
    this.childNodes = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.classSet = new Set();
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.tabIndex = 0;
    this.offsetParent = VISIBLE; // 보이는 것으로 취급(trapTab 의 가시성 필터)
    this.scrollTop = 0;
    this.scrollLeft = 0;
    this.style = makeStyle();
    this.dataset = {};
    this.listeners = new Map();
    const set = this.classSet;
    this.classList = {
      add: (...names) => names.forEach((n) => set.add(n)),
      remove: (...names) => names.forEach((n) => set.delete(n)),
      contains: (name) => set.has(name),
      toggle: (name, force) => {
        const want = force === undefined ? !set.has(name) : !!force;
        if (want) set.add(name); else set.delete(name);
        return want;
      },
    };
  }

  get isConnected() {
    let node = this;
    while (node.parentNode) node = node.parentNode;
    return node === DOC_ROOT;
  }

  get nextSibling() {
    if (!this.parentNode) return null;
    const kids = this.parentNode.childNodes;
    return kids[kids.indexOf(this) + 1] || null;
  }

  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.childNodes.push(child);
    mark("place:" + child.id);
    return child;
  }

  insertBefore(child, ref) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    const at = ref ? this.childNodes.indexOf(ref) : -1;
    if (at === -1) this.childNodes.push(child);
    else this.childNodes.splice(at, 0, child);
    mark("place:" + child.id);
    return child;
  }

  removeChild(child) {
    const at = this.childNodes.indexOf(child);
    if (at !== -1) this.childNodes.splice(at, 1);
    child.parentNode = null;
    return child;
  }

  contains(node) {
    for (let n = node; n; n = n.parentNode) if (n === this) return true;
    return false;
  }

  closest(selector) {
    for (let n = this; n instanceof StubElement; n = n.parentNode) {
      if (matchesSelector(n, selector)) return n;
    }
    return null;
  }

  matches(selector) { return matchesSelector(this, selector); }

  descendants(out = []) {
    for (const child of this.childNodes) {
      out.push(child);
      child.descendants(out);
    }
    return out;
  }

  querySelectorAll(selector) {
    return this.descendants().filter((n) => matchesSelector(n, selector));
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  hasAttribute(name) { return this.attributes.has(name); }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "tabindex") this.tabIndex = Number(value);
  }

  addEventListener(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(fn);
  }

  removeEventListener(type, fn) {
    const list = this.listeners.get(type);
    if (!list) return;
    const at = list.indexOf(fn);
    if (at !== -1) list.splice(at, 1);
  }

  focus() {
    // 비활성·분리·숨김 요소의 focus() 는 브라우저에서도 조용한 no-op 다 — modal.restoreFocus
    // 가 "옮겨 보고 결과를 읽는" 규율이 여기 의존한다. 이 앱의 숨김 규칙은 `.modal.hidden`
    // 하나뿐이라(정적 DOM 계약) 조상에 hidden 이 있으면 초점을 받지 못하는 것으로 본다.
    if (this.disabled || !this.isConnected) return;
    for (let n = this; n instanceof StubElement; n = n.parentNode) {
      if (n.classSet.has("hidden")) return;
    }
    DOC.activeElement = this;
    mark("focus:" + this.id);
  }
}

const VISIBLE = { visible: true };

function createElement(tag, spec = {}) {
  const el = new StubElement(tag);
  if (spec.id) el.id = spec.id;
  for (const cls of spec.cls || []) el.classSet.add(cls);
  for (const [k, v] of Object.entries(spec.attrs || {})) el.setAttribute(k, v);
  for (const child of spec.kids || []) el.appendChild(child);
  return el;
}

const DOC_ROOT = new StubElement("html");
const DOC = {
  documentElement: DOC_ROOT,
  body: null,
  activeElement: null,
  listeners: new Map(),
  createElement: (tag) => new StubElement(tag),
  getElementById(id) {
    return DOC_ROOT.descendants().find((n) => n.id === id) || null;
  },
  querySelector(selector) { return DOC_ROOT.querySelector(selector); },
  querySelectorAll(selector) { return DOC_ROOT.querySelectorAll(selector); },
  addEventListener(type, fn) {
    if (!DOC.listeners.has(type)) DOC.listeners.set(type, []);
    DOC.listeners.get(type).push(fn);
  },
  removeEventListener(type, fn) {
    const list = DOC.listeners.get(type);
    if (!list) return;
    const at = list.indexOf(fn);
    if (at !== -1) list.splice(at, 1);
  },
  listenerCount(type) { return (DOC.listeners.get(type) || []).length; },
};

const alerts = [];
const WIN = {
  alert: (text) => { alerts.push(String(text)); },
  addEventListener() {},
  removeEventListener() {},
  innerWidth: 1280,
  innerHeight: 800,
};

/** document capture → target 순으로 흘린다. 등록 순서가 곧 실행 순서다(검사 대상). */
function dispatch(target, type, props = {}) {
  const e = { type, target, ...props };
  e.defaultPrevented = false;
  let stopped = false;
  let stoppedAll = false;
  e.preventDefault = () => { e.defaultPrevented = true; };
  e.stopPropagation = () => { stopped = true; };
  e.stopImmediatePropagation = () => { stopped = true; stoppedAll = true; };
  for (const fn of (DOC.listeners.get(type) || []).slice()) {
    e.currentTarget = DOC;
    fn(e);
    if (stoppedAll) return e;
  }
  if (stopped) return e;
  if (target instanceof StubElement) {
    for (const fn of (target.listeners.get(type) || []).slice()) {
      e.currentTarget = target;
      fn(e);
      if (stoppedAll) return e;
    }
  }
  return e;
}

function pressKey(key, target) {
  return dispatch(target || DOC.activeElement || DOC.body, "keydown", { key, keyCode: 0 });
}

/** 닫힘 전이를 끝까지 흘린다 — modal.close 는 transitionend(또는 220ms 안전망)로 정착한다. */
function flushClose(id) {
  const el = DOC.getElementById(id);
  if (!el) return;
  const card = el.querySelector(".modal-card");
  if (!card) return;
  dispatch(card, "transitionend", { propertyName: "opacity" });
}

const MODAL_IDS = [
  "modalA", "modalB", "confirmModal", "promptModal", "chooseModal", "sheetModal", "sheet2Modal",
];

function buildFixture() {
  DOC_ROOT.childNodes.length = 0;

  const card = (kids) => createElement("div", { cls: ["modal-card"], kids });
  const modal = (id, kids) => createElement("div", { id, cls: ["modal", "hidden"], kids: [card(kids)] });

  const body = createElement("body", {
    kids: [
      createElement("div", {
        id: "screenRoot",
        cls: ["scr", "on"],
        kids: [
          createElement("button", { id: "pageTrigger" }),
          createElement("button", { id: "sheetOpen" }),
          createElement("div", {
            id: "homeHost",
            kids: [
              createElement("div", { id: "before" }),
              createElement("div", {
                id: "movable",
                kids: [createElement("div", { id: "inner", attrs: { "data-preserve-scroll": "" } })],
              }),
              createElement("div", { id: "after" }),
            ],
          }),
        ],
      }),
      createElement("div", {
        id: "overlayRoot",
        kids: [
          modal("modalA", [createElement("button", { id: "aBtn" }), createElement("button", { id: "aBtn2" })]),
          modal("modalB", [createElement("button", { id: "bBtn" })]),
          modal("confirmModal", [
            createElement("h3", { id: "confirmModalTitle" }),
            createElement("p", { id: "confirmModalBody" }),
            createElement("button", { id: "confirmModalOk" }),
            createElement("button", { id: "confirmModalCancel" }),
          ]),
          modal("promptModal", [
            createElement("h3", { id: "promptModalTitle" }),
            createElement("p", { id: "promptModalBody" }),
            createElement("input", { id: "promptModalInput" }),
            createElement("div", { id: "promptModalError" }),
            createElement("button", { id: "promptModalOk" }),
            createElement("button", { id: "promptModalCancel" }),
          ]),
          modal("chooseModal", [
            createElement("h3", { id: "chooseModalTitle" }),
            createElement("p", { id: "chooseModalBody" }),
            createElement("button", { id: "chooseModalOk" }),
            createElement("button", { id: "chooseModalAlt" }),
            createElement("button", { id: "chooseModalCancel" }),
          ]),
          modal("sheetModal", [createElement("button", { id: "sheetClose" }),
            createElement("div", { id: "dataSheetSlot" })]),
          modal("sheet2Modal", [createElement("button", { id: "sheet2Close" }),
            createElement("div", { id: "sheet2Slot" })]),
          createElement("div", { id: "notAModal", cls: ["hidden"] }),
          // R3-01 — host 컨트롤러의 토스트 골격(제품에선 React 렌더가 소유하는 형상).
          createElement("div", {
            id: "undoToast",
            cls: ["undo-toast"],
            kids: [
              createElement("span", { id: "undoToastText" }),
              createElement("button", { id: "undoToastBtn" }),
            ],
          }),
        ],
      }),
    ],
  });

  DOC_ROOT.appendChild(body);
  DOC.body = body;
  DOC.activeElement = body;
}

function install() {
  globalThis.document = DOC;
  globalThis.window = WIN;
  globalThis.Element = StubElement;
  globalThis.Node = StubNode;
}

function uninstall() {
  delete globalThis.document;
  delete globalThis.window;
  delete globalThis.Element;
  delete globalThis.Node;
}

/* ────────────────────────── 대상 모듈 적재 ──────────────────────────
   모듈 평가는 문서 부작용이 0 이다(개정 10) — 그래도 import 전에 전역을 세우는 것은
   스텁 세계의 일관성을 위해서다. 테스트 사이에는 매번 걷었다 다시 세운다. */

buildFixture();
install();
const { createModal } = await import("../../frontend/src/overlay/modal.js");
const { createSurfaceSheet } = await import("../../frontend/js/surface_sheet.js");
const { Popover } = await import("../../frontend/js/popover.js");
const Modal = createModal({ popover: Popover });
const SurfaceSheet = createSurfaceSheet({ modal: Modal });
const { createOverlayDialogController } = await import("../../frontend/src/overlay/host.ts");
const { overlayEngine, setOverlayDialogHost } = await import("../../frontend/src/overlay/instance.ts");
uninstall();

/* bootProduct 구성 몫의 재현 ① — dismissal 계열 문서 리스너는 구성 시 상시 부착이다
   (개정 10). DOC 은 테스트를 가로질러 정체성이 유지되므로 여기 한 번이면 제품과 같은
   「구성이 먼저, 첫 open 이 나중」 등록 순서가 선다(모달 keydown 은 instance.ts 소유). */
for (const attachment of Popover.documentAttachments) {
  if (attachment.target === "window") WIN.addEventListener(attachment.type, attachment.handler);
  else DOC.addEventListener(attachment.type, attachment.handler);
}

const MODAL_SRC = readFileSync(new URL("../../frontend/src/overlay/modal.js", import.meta.url), "utf8");
const SHEET_SRC = readFileSync(new URL("../../frontend/js/surface_sheet.js", import.meta.url), "utf8");

/* bootProduct 구성 몫의 재현 ② — React host 가 마운트 effect 에서 세우는 다이얼로그·토스트
   컨트롤러의 **실물**을 fixture 골격 위에 세운다(대역이면 파사드~집행자 사슬이 시험되지
   않는다). fixture 가 매 테스트 신품이라 컨트롤러도 매 테스트 세우고 대칭으로 걷는다. */
let hostSession = null;

function standUpHost() {
  const session = createOverlayDialogController({
    doc: DOC,
    notify: (message) => alerts.push(String(message)),
    roots: {
      confirm: DOC.getElementById("confirmModal"),
      choose: DOC.getElementById("chooseModal"),
      prompt: DOC.getElementById("promptModal"),
      toast: DOC.getElementById("undoToast"),
    },
  });
  const release = setOverlayDialogHost(session.controller);
  hostSession = { dispose: session.dispose, release };
}

beforeEach(() => {
  install();
  buildFixture();
  standUpHost();
  alerts.length = 0;
  trace.on = false;
  trace.log.length = 0;
});

afterEach(() => {
  // 다음 테스트로 새는 모듈 상태(모달 스택·pendingDialog)를 여기서 정산한다.
  for (const id of MODAL_IDS) {
    const el = DOC.getElementById(id);
    if (!el || el.classList.contains("hidden")) continue;
    Modal.close(id);
    flushClose(id);
  }
  hostSession.release();
  hostSession.dispose();
  hostSession = null;
  uninstall();
});

after(uninstall);

/** console.error 를 가로채 loud 경로를 **결과로** 확인한다(존재가 아니라 발화를 본다). */
function captureConsole(run) {
  const errors = [];
  const original = console.error;
  console.error = (...args) => { errors.push(args.join(" ")); };
  try { return { errors, value: run() }; }
  finally { console.error = original; }
}

async function captureConsoleAsync(run) {
  const errors = [];
  const original = console.error;
  console.error = (...args) => { errors.push(args.join(" ")); };
  try { return { errors, value: await run() }; }
  finally { console.error = original; }
}

/* ────────────────────────── 1. 공개 표면 ────────────────────────── */

test("1. Modal 의 공개 표면은 계약 표와 정확히 같다", async () => {
  assert.deepEqual(
    Object.keys(Modal).sort(),
    ["choose", "close", "confirm", "open", "prompt", "restoreFocus"],
  );
  for (const key of Object.keys(Modal)) assert.equal(typeof Modal[key], "function");
  const ns = await import("../../frontend/src/overlay/modal.js");
  assert.deepEqual(Object.keys(ns), ["createModal"]);
  assert.equal(ns.default, undefined);
});

test("1. SurfaceSheet 의 공개 표면은 계약 표와 정확히 같다", async () => {
  assert.deepEqual(
    Object.keys(SurfaceSheet).sort(),
    ["close", "closeAllAndRestore", "closeAndRestore", "isOpen", "open", "restore"],
  );
  for (const key of Object.keys(SurfaceSheet)) assert.equal(typeof SurfaceSheet[key], "function");
  const ns = await import("../../frontend/js/surface_sheet.js");
  assert.deepEqual(Object.keys(ns), ["createSurfaceSheet"]);
  assert.equal(ns.default, undefined);
});

/* ────────────────────────── 2. 의존 간선 ────────────────────────── */

test("2. 의존은 factory 주입 간선이다 — 전역 조회·IIFE·자기 전역 write 가 0", () => {
  assert.match(MODAL_SRC, /^import \{ overlayEngine, overlayDialogHost \} from "\.\/instance\.ts";$/m);
  assert.equal(/^import /m.test(SHEET_SRC), false, "SurfaceSheet 의 modal 의존은 factory 주입");
  for (const [name, src] of [["modal.js", MODAL_SRC], ["surface_sheet.js", SHEET_SRC]]) {
    assert.equal(/^\(function \(\) \{/m.test(src), false, `${name}: top-level IIFE 잔존`);
    assert.equal(/^\s*(window|globalThis)\.[A-Za-z_$][\w$]*\s*=/m.test(src), false,
      `${name}: 자기 전역 write 잔존`);
    assert.equal(/window\.(Modal|Popover|Bridge|Nav|escHtml|SurfaceSheet)\b/.test(src), false,
      `${name}: 제품 전역 조회 잔존`);
    assert.equal(/export default/.test(src), false, `${name}: export default 잔존`);
    assert.equal(/Object\.assign\(\s*window/.test(src), false, `${name}: Object.assign(window) 잔존`);
  }
  // 별칭 금지 — `Modal.confirm(` 문자열을 세는 파괴 확인 라벨 감사(test_danger_confirm_contract)
  // 가 별칭에 침묵한다.
  assert.equal(SHEET_SRC.includes("modal.open("), true);
  assert.equal(SHEET_SRC.includes("modal.close(id)"), true);
});

test("2. Modal.open 이 실제로 import 한 Popover 의 closeAll 을 통과한다", () => {
  let open = true;
  const seen = [];
  const unregister = Popover.register({
    isOpen: () => open,
    contains: () => false,
    close: () => { open = false; seen.push("popover-closed"); },
  });
  try {
    Modal.open("modalA");
    assert.deepEqual(seen, ["popover-closed"]);
  } finally {
    unregister();
  }
});

test("2. 열기 순서 — 복귀점 포착 → Popover.closeAll → 스택 → 초점", () => {
  const order = [];
  DOC.getElementById("pageTrigger").focus();
  const unregister = Popover.register({
    isOpen: () => true,
    contains: () => false,
    close: () => { order.push("closeAll@" + (DOC.activeElement ? DOC.activeElement.id : "?")); },
  });
  try {
    Modal.open("modalA");
    // closeAll 시점의 초점이 아직 트리거라는 것이 "복귀점을 먼저 붙잡는다"의 결과다.
    assert.deepEqual(order, ["closeAll@pageTrigger"]);
    assert.equal(DOC.activeElement.id, "aBtn");
  } finally {
    unregister();
  }
});

/* ────────────────────────── 3. 싱글턴 ────────────────────────── */

test("3. factory 인스턴스가 달라도 엔진 스택·pendingDialog는 한 벌이다", async () => {
  const again = createModal({ popover: Popover });
  assert.notEqual(again, Modal, "factory 인스턴스는 명시적으로 구성된다");

  // 스택 공유: SurfaceSheet 가 연 모달을 이쪽 Modal.close 가 닫는다.
  DOC.getElementById("sheetOpen").focus();
  SurfaceSheet.open({ modalId: "sheetModal" });
  assert.equal(DOC.getElementById("sheetModal").classList.contains("hidden"), false);
  Modal.close("sheetModal");
  flushClose("sheetModal");
  assert.equal(DOC.getElementById("sheetModal").classList.contains("hidden"), true);
  assert.equal(SurfaceSheet.isOpen("sheetModal"), false);

  // pendingDialog 공유: 첫 confirm 이 미결인 채 두 번째가 재진입 거절된다.
  const first = Modal.confirm({ body: "첫째" });
  const second = await captureConsoleAsync(() => again.confirm({ body: "둘째" }));
  assert.equal(second.value, false);
  assert.match(second.errors[0], /재진입 거절/);
  assert.equal(DOC.getElementById("confirmModalBody").textContent, "첫째");
  dispatch(DOC.getElementById("confirmModalCancel"), "click");
  flushClose("confirmModal");
  assert.equal(await first, false);
});

/* ────────────────────────── 4·5. Escape 와 스택 ────────────────────────── */

test("4. Escape 는 최상위 모달만 닫는다(중첩 2개)", () => {
  const base = DOC.listenerCount("keydown");
  Modal.open("modalA");
  assert.equal(DOC.listenerCount("keydown"), base + 1);
  Modal.open("modalB");
  // 두 번째 개방은 리스너를 더 걸지 않는다(stack.length === 1 게이트).
  assert.equal(DOC.listenerCount("keydown"), base + 1);
  assert.equal(DOC.getElementById("modalA").style.getPropertyValue("--modal-depth"), "0");
  assert.equal(DOC.getElementById("modalB").style.getPropertyValue("--modal-depth"), "1");

  const e = pressKey("Escape");
  assert.equal(e.defaultPrevented, true);
  assert.equal(DOC.getElementById("modalB").classList.contains("is-closing"), true);
  assert.equal(DOC.getElementById("modalA").classList.contains("is-closing"), false);
  assert.equal(DOC.getElementById("modalA").classList.contains("hidden"), false);
  flushClose("modalB");
  assert.equal(DOC.getElementById("modalB").classList.contains("hidden"), true);
  assert.equal(DOC.listenerCount("keydown"), base + 1); // 아직 modalA 가 남았다

  pressKey("Escape");
  flushClose("modalA");
  assert.equal(DOC.getElementById("modalA").classList.contains("hidden"), true);
  assert.equal(DOC.listenerCount("keydown"), base); // 스택이 비면 해제
  assert.equal(pressKey("Escape").defaultPrevented, false);
});

test("4. 퇴장 중 Escape·Tab 은 소비만 하고 다시 닫지 않는다", () => {
  Modal.open("modalA");
  Modal.close("modalA");
  const card = DOC.getElementById("modalA").querySelector(".modal-card");
  const before = card.listeners.get("transitionend").length;
  const e = pressKey("Escape");
  assert.equal(e.defaultPrevented, true);
  assert.equal(card.listeners.get("transitionend").length, before);
  flushClose("modalA");
});

test("5. 중첩 닫기 — 복귀 초점이 층마다 정확히 승계된다", () => {
  DOC.getElementById("pageTrigger").focus();
  Modal.open("modalA");
  assert.equal(DOC.activeElement.id, "aBtn");
  Modal.open("modalB");
  assert.equal(DOC.activeElement.id, "bBtn");

  pressKey("Escape");
  flushClose("modalB");
  assert.equal(DOC.activeElement.id, "aBtn", "위 층은 자기 복귀점(aBtn)으로 돌아온다");

  pressKey("Escape");
  flushClose("modalA");
  assert.equal(DOC.activeElement.id, "pageTrigger", "아래 층은 원 트리거로 돌아온다");
});

test("5. 아래 층을 프로그램적으로 닫아도 최상위의 초점을 빼앗지 않는다", () => {
  DOC.getElementById("pageTrigger").focus();
  Modal.open("modalA");
  Modal.open("modalB");
  assert.equal(DOC.activeElement.id, "bBtn");
  Modal.close("modalA");
  flushClose("modalA");
  assert.equal(DOC.activeElement.id, "bBtn", "wasTop 이 아니면 복귀를 건너뛴다");
  Modal.close("modalB");
  flushClose("modalB");
  // modalB 의 복귀점은 개방 시점 초점인 aBtn 이고, 그 aBtn 은 이미 닫힌 modalA 안이라
  // 초점을 못 받는다 — restoreFocus 는 판정을 흉내내지 않고 **옮겨 보고 실패를 읽어**
  // 지금 서 있는 화면 루트로 착지한다. pageTrigger(modalA 의 복귀점)로는 가지 않는다.
  assert.equal(DOC.activeElement.id, "screenRoot");
});

test("5. 트리거가 되돌릴 수 없으면 화면 루트로 착지한다(흉내내지 않고 결과를 읽는다)", () => {
  const trigger = DOC.getElementById("pageTrigger");
  trigger.focus();
  Modal.open("modalA");
  trigger.disabled = true; // 닫히는 사이 그 행동이 불가능해지는 정상 경로
  Modal.close("modalA");
  flushClose("modalA");
  assert.equal(DOC.activeElement.id, "screenRoot");
  assert.equal(DOC.getElementById("screenRoot").getAttribute("tabindex"), "-1");
});

test("5. Tab 은 최상위 모달 안에 갇힌다(경계에서만 개입)", () => {
  Modal.open("modalA");
  DOC.getElementById("aBtn2").focus();
  const wrap = pressKey("Tab");
  assert.equal(wrap.defaultPrevented, true);
  assert.equal(DOC.activeElement.id, "aBtn", "마지막에서 Tab → 첫 요소로 순환");

  const inner = pressKey("Tab", DOC.activeElement);
  assert.equal(inner.defaultPrevented, false, "경계가 아니면 브라우저에 맡긴다");
  assert.equal(DOC.activeElement.id, "aBtn");

  const back = dispatch(DOC.activeElement, "keydown", { key: "Tab", shiftKey: true, keyCode: 0 });
  assert.equal(back.defaultPrevented, true);
  assert.equal(DOC.activeElement.id, "aBtn2", "첫 요소에서 Shift+Tab → 마지막으로 순환");

  // 바깥(배경)에 초점이 있으면 안으로 끌어온다 — 배경 버튼에 Tab+Enter 가 닿는 경로 차단.
  DOC.getElementById("pageTrigger").focus();
  const pull = pressKey("Tab");
  assert.equal(pull.defaultPrevented, true);
  assert.equal(DOC.activeElement.id, "aBtn");
});

/* ────────────────────────── 6. 단일 pending 직렬화 ────────────────────────── */

test("6. confirm 이 미결이면 두 번째 confirm 은 loud 하게 거절된다", async () => {
  const first = Modal.confirm({ body: "첫째", confirmLabel: "지웁니다" });
  const { errors, value } = await captureConsoleAsync(() => Modal.confirm({ body: "둘째" }));
  assert.equal(value, false, "안전측 거절값");
  assert.equal(errors.length, 1);
  assert.match(errors[0], /재진입 거절/);
  assert.deepEqual(alerts, ["다른 확인 창이 이미 열려 있습니다. 먼저 끝내세요."]);
  assert.equal(DOC.getElementById("confirmModalBody").textContent, "첫째",
    "두 번째 요청이 첫 번째 문맥을 덮어쓰지 않는다");
  assert.equal(DOC.getElementById("confirmModalOk").textContent, "지웁니다");

  dispatch(DOC.getElementById("confirmModalOk"), "click");
  flushClose("confirmModal");
  assert.equal(await first, true);

  // 정산 뒤에는 다시 열린다 — pendingDialog 가 갇히지 않는다.
  const third = Modal.confirm({ body: "셋째" });
  assert.equal(DOC.getElementById("confirmModalBody").textContent, "셋째");
  dispatch(DOC.getElementById("confirmModalCancel"), "click");
  flushClose("confirmModal");
  assert.equal(await third, false);
});

test("6. 직렬화는 confirm·prompt·choose 를 가로질러 한 벌이다", async () => {
  const pending = Modal.prompt({ body: "이름", value: "가" });
  assert.equal(DOC.activeElement.id, "promptModalInput");
  const chooseValue = await captureConsoleAsync(() =>
    Modal.choose({
      body: "셋",
      choices: [{ value: "keep", label: "유지" }, { value: "patch", label: "덧대기" },
        { value: "stay", label: "머무르기" }],
    }));
  assert.equal(chooseValue.value, "stay", "choose 의 거절값 = choices[2]");
  assert.equal(DOC.getElementById("chooseModal").classList.contains("hidden"), true,
    "거절된 요청은 골격을 열지도 않는다");
  assert.equal(alerts.length, 1);

  DOC.getElementById("promptModalInput").value = "나";
  dispatch(DOC.getElementById("promptModalOk"), "click");
  flushClose("promptModal");
  assert.equal(await pending, "나");
});

test("6. prompt 의 Enter 는 IME 조합 확정 Enter 를 제출로 오인하지 않는다", async () => {
  const pending = Modal.prompt({ body: "이름", value: "" });
  const input = DOC.getElementById("promptModalInput");
  input.value = "한";
  dispatch(input, "keydown", { key: "Enter", isComposing: true, keyCode: 229 });
  assert.equal(DOC.getElementById("promptModal").classList.contains("is-closing"), false);
  input.value = "한글";
  dispatch(input, "keydown", { key: "Enter", isComposing: false, keyCode: 13 });
  flushClose("promptModal");
  assert.equal(await pending, "한글");
});

test("6. Escape 로 해소된 promise 는 거절값이고 pending 이 풀린다", async () => {
  const pending = Modal.confirm({ body: "지울까요" });
  pressKey("Escape");
  flushClose("confirmModal");
  assert.equal(await pending, false);
  const next = Modal.confirm({ body: "다음" });
  assert.equal(DOC.getElementById("confirmModalBody").textContent, "다음");
  dispatch(DOC.getElementById("confirmModalCancel"), "click");
  flushClose("confirmModal");
  assert.equal(await next, false);
});

test("6. host dispose 는 열린 다이얼로그를 거절값으로 정산하고 수명을 전부 걷는다", async () => {
  const keydownBefore = DOC.listenerCount("keydown");
  const pending = Modal.confirm({ body: "열린 채 unmount" });
  assert.equal(overlayEngine.depth(), 1);
  assert.equal(overlayEngine.isDialogPending(), true);
  assert.equal(DOC.listenerCount("keydown"), keydownBefore + 1);

  hostSession.release();
  hostSession.dispose();
  hostSession = null;

  assert.equal(await pending, false);
  assert.equal(overlayEngine.depth(), 0);
  assert.equal(overlayEngine.isDialogPending(), false);
  assert.equal(DOC.listenerCount("keydown"), keydownBefore);
  assert.equal(DOC.getElementById("confirmModal").classList.contains("hidden"), true);
  assert.equal(DOC.getElementById("confirmModalOk").listeners.get("click").length, 0);
  assert.equal(DOC.getElementById("confirmModalCancel").listeners.get("click").length, 0);

  /* afterEach 의 대칭 cleanup 과 다음 테스트를 위해 신품 host 를 다시 세운다. */
  standUpHost();
});

/* ────────────────────────── 7. loud rejection ────────────────────────── */

test("7. .modal 없는 대상은 조용히 삼키지 않고 거절한다(open/close)", () => {
  const target = DOC.getElementById("notAModal");
  const opened = captureConsole(() => Modal.open("notAModal"));
  assert.equal(opened.errors.length, 1);
  assert.match(opened.errors[0], /^Modal\.open: 대상 #notAModal /);
  assert.equal(target.classList.contains("hidden"), true, "열리지 않았다");

  const closed = captureConsole(() => Modal.close("notAModal"));
  assert.equal(closed.errors.length, 1);
  assert.match(closed.errors[0], /^Modal\.close: 대상 #notAModal /);

  // 없는 id 는 거절 대상이 아니라 무해한 no-op 다(오늘의 동작 그대로).
  const missing = captureConsole(() => { Modal.open("없는id"); Modal.close("없는id"); });
  assert.deepEqual(missing.errors, []);
});

test("7. 골격 부재 다이얼로그는 안전측 거절 + loud, 그리고 pending 을 가두지 않는다", async () => {
  const ok = DOC.getElementById("confirmModalOk");
  ok.parentNode.removeChild(ok);
  const { errors, value } = await captureConsoleAsync(() => Modal.confirm({ body: "x" }));
  assert.equal(value, false);
  assert.equal(errors.length, 1);
  assert.match(errors[0], /골격 부재\/불량 — confirmModal/);
  assert.deepEqual(alerts, ["확인 창을 열 수 없어 요청을 실행하지 않았습니다. 다시 시도하세요."]);
  assert.equal(DOC.getElementById("confirmModal").classList.contains("hidden"), true);

  // pendingDialog 가 true 로 갇히면 이후 모든 다이얼로그가 재진입으로 거절된다 — 안 갇힌다.
  alerts.length = 0;
  const next = Modal.prompt({ body: "이름" });
  assert.equal(DOC.getElementById("promptModal").classList.contains("hidden"), false);
  assert.deepEqual(alerts, []);
  dispatch(DOC.getElementById("promptModalCancel"), "click");
  flushClose("promptModal");
  assert.equal(await next, null, "prompt 의 거절값은 null");
});

test("7. root 가 .modal 을 잃어도 다이얼로그는 교착 대신 거절한다", async () => {
  DOC.getElementById("chooseModal").classList.remove("modal");
  const { value, errors } = await captureConsoleAsync(() =>
    Modal.choose({ body: "x", choices: [{ value: "a", label: "A" }, { value: "b", label: "B" },
      { value: "c", label: "C" }] }));
  assert.equal(value, "c");
  assert.match(errors[0], /골격 부재\/불량 — chooseModal/);
  assert.equal(alerts.length, 1);
});

/* ────────────────────────── 8. 멱등·재진입 가드 ────────────────────────── */

test("8. 같은 모달의 이중 open 은 스택을 늘리지 않는다", () => {
  const base = DOC.listenerCount("keydown");
  DOC.getElementById("pageTrigger").focus();
  Modal.open("modalA");
  const el = DOC.getElementById("modalA");
  assert.equal(el.style.getPropertyValue("--modal-depth"), "0");
  DOC.getElementById("aBtn2").focus();
  Modal.open("modalA", { returnFocus: DOC.getElementById("sheetOpen") });
  assert.equal(el.style.getPropertyValue("--modal-depth"), "0", "중복 push 면 1 이 된다");
  assert.equal(DOC.activeElement.id, "aBtn2", "두 번째 open 은 초점도 다시 옮기지 않는다");
  assert.equal(DOC.listenerCount("keydown"), base + 1);

  pressKey("Escape");
  flushClose("modalA");
  assert.equal(DOC.listenerCount("keydown"), base, "엔트리가 하나뿐이라 한 번에 비워진다");
  assert.equal(DOC.activeElement.id, "pageTrigger", "복귀점은 첫 open 것이 이긴다");
});

test("8. 퇴장 중 close 재입력은 한 번만 정착한다", () => {
  let closes = 0;
  Modal.open("modalA", { onClose: () => { closes += 1; } });
  const card = DOC.getElementById("modalA").querySelector(".modal-card");
  Modal.close("modalA");
  assert.equal(card.listeners.get("transitionend").length, 1);
  Modal.close("modalA");
  Modal.close("modalA");
  assert.equal(card.listeners.get("transitionend").length, 1, "리스너가 겹쳐 붙지 않는다");
  flushClose("modalA");
  assert.equal(closes, 1);
  flushClose("modalA");
  assert.equal(closes, 1, "정착 뒤 transitionend 재발화도 한 번을 넘기지 않는다");
});

test("8. beforeClose 가 false 면 닫기 요청을 소비한다", () => {
  let allow = false;
  Modal.open("modalA", { beforeClose: () => allow });
  pressKey("Escape");
  assert.equal(DOC.getElementById("modalA").classList.contains("is-closing"), false);
  assert.equal(DOC.getElementById("modalA").classList.contains("hidden"), false);
  allow = true;
  pressKey("Escape");
  flushClose("modalA");
  assert.equal(DOC.getElementById("modalA").classList.contains("hidden"), true);
});

/* ────────────────────────── 9. SurfaceSheet ────────────────────────── */

/* R5-99 B2 — 실 DOM 이동/복귀 기계는 유일 제품 호출부의 이동 목록이 빈 채
   (`moves: []`) 도달 불능이 되어 `trigger()` 와 함께 은퇴했다. 면 내용은 React 가
   면 안에 직접 그린다(후계 = React reconciliation · r4 화면 계약군). 남는 계약은
   열림/닫힘 정산 한 관문(afterRestore·onClose)·이중 open 무시·전량 회수다. */

function openSheet(extra = {}) {
  const trigger = DOC.getElementById("sheetOpen");
  trigger.focus();
  SurfaceSheet.open({ modalId: "sheetModal", returnFocus: trigger, ...extra });
  return { trigger };
}

test("9. 펼침은 모달을 열고 열림 상태를 기록한다", () => {
  openSheet();
  assert.equal(SurfaceSheet.isOpen("sheetModal"), true);
  assert.equal(DOC.getElementById("sheetModal").classList.contains("hidden"), false);
  assert.equal(DOC.activeElement.id, "sheetClose");
});

test("9. 닫힘 정산은 한 관문이다 — afterRestore 정확히 한 번, trigger 초점 복귀", () => {
  const calls = [];
  openSheet({ afterRestore: () => calls.push("after") });
  SurfaceSheet.closeAndRestore("sheetModal");
  flushClose("sheetModal");
  assert.deepEqual(calls, ["after"]);
  assert.equal(SurfaceSheet.isOpen("sheetModal"), false);
  assert.equal(DOC.activeElement.id, "sheetOpen");
});

test("9. Escape 로 닫아도 같은 정산이 걸린다(onClose 한 관문)", () => {
  const calls = [];
  openSheet({ afterRestore: () => calls.push("after") });
  pressKey("Escape");
  flushClose("sheetModal");
  assert.deepEqual(calls, ["after"]);
  assert.equal(SurfaceSheet.isOpen("sheetModal"), false);
  assert.equal(DOC.activeElement.id, "sheetOpen");
});

test("9. close 는 안 열린 면에 아무 일도 하지 않고, restore 는 멱등이다", () => {
  SurfaceSheet.close("sheetModal");
  assert.equal(DOC.getElementById("sheetModal").classList.contains("hidden"), true);
  const calls = [];
  openSheet({ afterRestore: () => calls.push("after") });
  SurfaceSheet.restore("sheetModal");
  assert.equal(SurfaceSheet.isOpen("sheetModal"), false);
  SurfaceSheet.restore("sheetModal"); // 두 번째는 no-op
  assert.deepEqual(calls, ["after"], "정산은 정확히 한 번");
  Modal.close("sheetModal");
  flushClose("sheetModal");
});

test("9. 이중 open 은 두 번째를 무시한다(열림 기록을 덮어쓰지 않는다)", () => {
  const calls = [];
  openSheet({ afterRestore: () => calls.push("first") });
  SurfaceSheet.open({ modalId: "sheetModal", afterRestore: () => calls.push("second") });
  SurfaceSheet.closeAndRestore("sheetModal");
  flushClose("sheetModal");
  assert.deepEqual(calls, ["first"], "두 번째 open 의 정산이 끼어들지 않는다");
});

test("9. closeAllAndRestore 는 열린 면을 전부 회수한다", () => {
  const calls = [];
  openSheet({ afterRestore: () => calls.push("one") });
  SurfaceSheet.open({ modalId: "sheet2Modal", afterRestore: () => calls.push("two") });
  assert.equal(SurfaceSheet.isOpen("sheetModal"), true);
  assert.equal(SurfaceSheet.isOpen("sheet2Modal"), true);
  SurfaceSheet.closeAllAndRestore();
  assert.equal(SurfaceSheet.isOpen("sheetModal"), false);
  assert.equal(SurfaceSheet.isOpen("sheet2Modal"), false);
  assert.deepEqual(calls.sort(), ["one", "two"], "정산이 면마다 한 번씩 걸린다");
  flushClose("sheetModal");
  flushClose("sheet2Modal");
});

/* ────────────────────────── 10. Escape 3층 순서 ────────────────────────── */

test("10. Escape — 팝오버가 먼저 닫히고 그 다음 최상위 모달이 닫힌다", () => {
  const order = [];
  let popoverOpen = false;
  const unregister = Popover.register({
    isOpen: () => popoverOpen,
    contains: () => false,
    close: () => { popoverOpen = false; order.push("popover"); },
  });
  try {
    Modal.open("modalA", { beforeClose: () => { order.push("modal"); } });
    // 모달 위에서 다시 열린 팝오버(pool 재등록 흐름) — 이 순서가 검사 대상이다.
    popoverOpen = true;
    pressKey("Escape");
    assert.deepEqual(order, ["popover", "modal"],
      "modal 의 stopImmediatePropagation 은 자기 뒤 리스너만 막는다 — popover 는 먼저다");
    flushClose("modalA");
  } finally {
    unregister();
  }
});

test("10. popover 의 keydown 은 modal 보다 먼저 등록된다(구성 시 부착 < 첫 open 부착)", () => {
  // dismissal 계열은 bootProduct 구성 시 상시(개정 10 — 하니스가 재현), 모달 keydown 은
  // instance.ts 가 첫 open 에 부착·스택 빌 때 해제한다(개정 4). 구성이 언제나 open 보다
  // 앞이므로 dismissal 이 항상 앞자리다 — 순서가 import 간선이 아니라 부착 시점 계약에서 선다.
  const before = DOC.listenerCount("keydown");
  assert.ok(before >= 1, "dismissal keydown 이 구성 시(하니스 재현)부터 서 있다");
  Modal.open("modalA");
  const list = DOC.listeners.get("keydown");
  assert.equal(list.length, before + 1);
  assert.equal(list[list.length - 1].name, "onKeydown", "modal 의 리스너가 뒤에 붙는다");
  Modal.close("modalA");
  flushClose("modalA");
  assert.equal(DOC.listenerCount("keydown"), before, "스택이 비면 modal keydown 은 해제된다");
});
