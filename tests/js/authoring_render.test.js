/* UX-05: 실제 react-dom 커밋·effect 를 돌려 push 가 무엇을 다시 띄우는지 잰다.

   renderToStaticMarkup 은 effect 를 돌리지 않는다. 여기서는 react-dom/client 가 쓰는 만큼의
   작은 가짜 DOM 위에 AuthoringScreen 을 올리고, rhwp 마운트(rhwpMount.mount)를 바꿔 끼워
   시험 결과 뷰어 마운트·문서 장식 재전송 횟수를 센다. WASM iframe 은 Node 에서 띄울 수 없다. */
import test from "node:test";
import assert from "node:assert/strict";

const ELEMENT = 1, TEXT = 3, DOCUMENT = 9;

class FakeNode {
  constructor(nodeType, nodeName, ownerDocument) {
    this.nodeType = nodeType; this.nodeName = nodeName; this.ownerDocument = ownerDocument;
    this.childNodes = []; this.parentNode = null; this.listeners = new Map();
  }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get nextSibling() {
    const siblings = this.parentNode?.childNodes || [];
    return siblings[siblings.indexOf(this) + 1] || null;
  }
  appendChild(child) { child.parentNode?.removeChild(child); this.childNodes.push(child); child.parentNode = this; return child; }
  insertBefore(child, before) {
    if (!before) return this.appendChild(child);
    child.parentNode?.removeChild(child);
    this.childNodes.splice(this.childNodes.indexOf(before), 0, child); child.parentNode = this; return child;
  }
  removeChild(child) { this.childNodes.splice(this.childNodes.indexOf(child), 1); child.parentNode = null; return child; }
  addEventListener(type, listener) { if (!this.listeners.has(type)) this.listeners.set(type, new Set()); this.listeners.get(type).add(listener); }
  removeEventListener(type, listener) { this.listeners.get(type)?.delete(listener); }
  get textContent() { return this.childNodes.map((child) => child.textContent).join(""); }
  set textContent(text) {
    for (const child of [...this.childNodes]) this.removeChild(child);
    if (text) this.appendChild(this.ownerDocument.createTextNode(String(text)));
  }
}

class FakeText extends FakeNode {
  constructor(text, ownerDocument) { super(TEXT, "#text", ownerDocument); this.nodeValue = text; }
  get textContent() { return this.nodeValue; }
  set textContent(text) { this.nodeValue = text; }
}

/* UX-04: 키보드 모델을 실제 커밋 위에서 재려고 작은 선택자 엔진을 둔다 — 태그·#id·.class·[attr]·[attr="v"]·:not(…)
   복합 선택자와 자손 결합자(공백), 쉼표 목록. 제품 코드가 쓰는 만큼만이다. focus() 는 activeElement 를 옮긴다. */
function splitTop(text, separator) {
  const parts = []; let depth = 0; let quote = ""; let start = 0;
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (quote) { if (char === quote) quote = ""; continue; }
    if (char === '"' || char === "'") quote = char;
    else if (char === "[" || char === "(") depth++;
    else if (char === "]" || char === ")") depth--;
    else if (depth === 0 && (separator === " " ? /\s/.test(char) : char === separator)) { parts.push(text.slice(start, index)); start = index + 1; }
  }
  parts.push(text.slice(start));
  return parts.map((part) => part.trim()).filter(Boolean);
}
function matchesCompound(el, compound) {
  let rest = compound;
  const tag = /^[a-zA-Z][\w-]*/.exec(rest);
  if (tag) { if (el.tagName !== tag[0].toUpperCase()) return false; rest = rest.slice(tag[0].length); }
  while (rest) {
    let m;
    if ((m = /^#([\w-]+)/.exec(rest))) { if (el.getAttribute("id") !== m[1]) return false; }
    else if ((m = /^\.([\w-]+)/.exec(rest))) { if (!String(el.getAttribute("class") || "").split(/\s+/).includes(m[1])) return false; }
    else if ((m = /^\[([\w-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\]/.exec(rest))) {
      const value = m[2] ?? m[3] ?? m[4];
      if (!el.hasAttribute(m[1]) || (value !== undefined && el.getAttribute(m[1]) !== value)) return false;
    } else if ((m = /^:not\(/.exec(rest))) {
      let depth = 1; let index = m[0].length;
      for (; index < rest.length && depth; index++) { if (rest[index] === "(") depth++; else if (rest[index] === ")") depth--; }
      if (el.matches(rest.slice(m[0].length, index - 1))) return false;
      rest = rest.slice(index); continue;
    } else throw new Error(`fake DOM: unsupported selector ${compound}`);
    rest = rest.slice(m[0].length);
  }
  return true;
}

class FakeElement extends FakeNode {
  constructor(tag, ownerDocument) {
    super(ELEMENT, tag.toUpperCase(), ownerDocument);
    this.tagName = this.nodeName; this.namespaceURI = "http://www.w3.org/1999/xhtml";
    this.attributes = new Map(); this.style = { setProperty() {}, removeProperty() {} };
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  removeAttribute(name) { this.attributes.delete(name); }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  hasAttribute(name) { return this.attributes.has(name); }
  get options() { return this.childNodes.filter((child) => child.nodeName === "OPTION"); }
  get disabled() { return this.hasAttribute("disabled"); }
  get isConnected() { let node = this; while (node.parentNode) node = node.parentNode; return node === this.ownerDocument; }
  matches(selector) {
    return splitTop(selector, ",").some((complex) => {
      const parts = splitTop(complex, " ");
      if (!matchesCompound(this, parts.at(-1))) return false;
      let node = this.parentNode;
      for (let index = parts.length - 2; index >= 0; index--) {
        while (node instanceof FakeElement && !matchesCompound(node, parts[index])) node = node.parentNode;
        if (!(node instanceof FakeElement)) return false;
        node = node.parentNode;
      }
      return true;
    });
  }
  querySelectorAll(selector) { return [...this.walk()].slice(1).filter((el) => el.matches(selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { for (let node = this; node instanceof FakeElement; node = node.parentNode) if (node.matches(selector)) return node; return null; }
  contains(node) { for (let at = node; at; at = at.parentNode) if (at === this) return true; return false; }
  getBoundingClientRect() { return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
  focus() { if (!this.disabled && this.isConnected) this.ownerDocument.activeElement = this; }
  get offsetParent() { return this.ownerDocument.body; }
  *walk() { yield this; for (const child of this.childNodes) if (child instanceof FakeElement) yield* child.walk(); }
}

class FakeOption extends FakeElement {
  get value() { return this.getAttribute("value") ?? this.textContent; }
}

function installDom() {
  class HTMLIFrameElement {}
  const document = new FakeNode(DOCUMENT, "#document", null);
  document.createElement = (tag) => tag === "option" ? new FakeOption(tag, document) : new FakeElement(tag, document);
  document.createTextNode = (text) => new FakeText(text, document);
  document.documentElement = document.createElement("html");
  document.body = document.createElement("body");
  document.documentElement.appendChild(document.body);
  document.appendChild(document.documentElement);
  document.activeElement = document.body;
  document.baseURI = "http://127.0.0.1/index.html";
  document.hidden = false;
  const window = { document, HTMLIFrameElement, navigator: { userAgent: "node" },
    addEventListener() {}, removeEventListener() {}, setTimeout, clearTimeout, setInterval, clearInterval };
  document.defaultView = window;
  Object.assign(globalThis, { window, document, HTMLIFrameElement, IS_REACT_ACT_ENVIRONMENT: false });
  return document;
}

const settle = async () => { for (let turn = 0; turn < 8; turn++) await new Promise(setImmediate); };

async function boot(tab, more = [], respond = () => ({})) {
  const document = installDom();
  const { createElement } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { flushSync } = await import("react-dom");
  const { createAuthoringController } = await import("../../frontend/src/screens/authoring_controller.ts");
  const screen = await import("../../frontend/src/screens/authoring.ts");
  let snapshot = { active_id: tab.id, tabs: [tab, ...more], recoverable: [] };
  const listeners = new Set();
  const calls = [];
  const notify = () => flushSync(() => { for (const listener of [...listeners]) listener(); });
  const client = {
    async dispatch(_screen, action, payload) {
      calls.push({ action, ...payload });
      if (action === "content") return { ok: true, value: { session_id: payload.session_id, revision: 0, content: "ZG9j", section_entries: ["Contents/section0.xml"] } };
      if (action === "activate") { snapshot = { ...snapshot, active_id: payload.session_id }; notify(); }
      if (action === "close") { const tabs = snapshot.tabs.filter((item) => item.id !== payload.session_id); snapshot = { ...snapshot, tabs, active_id: tabs.at(-1)?.id || "" }; notify(); }
      return { ok: true, value: await respond(action, payload) };
    },
    async invoke() { return { ok: true, value: null }; },
  };
  const controller = createAuthoringController({ client,
    runtime: { model: () => ({ getSnapshot: () => snapshot, subscribe: (listener) => { listeners.add(listener); return () => listeners.delete(listener); } }), loadInitial: async () => {} },
    modal: { choose: async () => null, prompt: async () => null, confirm: async () => false },
    navigation: { go() {}, refresh: async () => {} },
  });
  const mounts = [];
  screen.rhwpMount.mount = async (spec) => {
    const record = { spec, disposed: false, decorations: 0 };
    mounts.push(record);
    // 편집면 초점은 편집기 host 로 선다 — 실제 rhwp 는 그 안의 iframe 이 초점을 받는다.
    return { content: async () => spec.content, flushChanges: async () => {}, applySnapshot: async () => {}, focus: async () => { spec.host.focus(); },
      undo: async () => {}, redo: async () => {}, setReadOnly: async () => {},
      setDecorations: async () => { record.decorations += 1; }, dispose: () => { record.disposed = true; } };
  };
  await controller.activate(tab.id);
  controller.update({ trial: true, dock: "trial" });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  flushSync(() => root.render(createElement(screen.AuthoringScreen, { controller })));
  await settle();
  /** 한 번의 push — 같은 내용이라도 JSON 왕복처럼 모든 객체가 새것이다. */
  const push = async (next = snapshot) => {
    snapshot = JSON.parse(JSON.stringify(next));
    flushSync(() => { for (const listener of [...listeners]) listener(); });
    await settle();
  };
  return { controller, mounts, push, snapshot: () => snapshot, container, root, document, calls, flushSync };
}

const hwpxTab = () => ({ id: "a", name: "a.hwpx", media: "hwpx", path: "a.hwpx", revision: 0, values: {}, selected: {},
  rhwp_editable: true, compatibility: { state: "editable" }, problems: [], cases: [],
  analysis: { revision: 3, fields: [{ name: "이름", count: 2, occurrences: [{ entry: "Contents/section0.xml", paragraph: 0, context: "첫째" }, { entry: "Contents/section0.xml", paragraph: 1 }] }], slots: [] },
  trial_state: "current", trial_result: { revision: 7, content: "cmVzdWx0", section_entries: ["Contents/section0.xml"], occurrences: [], source_revision: 0 } });

test("UX-05: a push that repeats the same trial revision keeps the trial viewer mounted; a new revision remounts once", async () => {
  const { mounts, push, snapshot, root } = await boot(hwpxTab());
  const trial = () => mounts.filter((record) => record.spec.fileName === "시험 결과.hwpx");
  const document = () => mounts.filter((record) => record.spec.fileName === "a.hwpx");
  assert.equal(trial().length, 1, "시험 결과 뷰어가 한 번 선다");
  assert.equal(document().length, 1, "문서 편집면이 한 번 선다");
  assert.equal(trial()[0].spec.trackSelection, "visible", "시험 뷰어는 보일 때만 선택을 읽는다(원본 위치 대응)");
  assert.equal(document()[0].spec.trackSelection, "visible", "숨은 문서 탭은 선택을 읽지 않는다");
  const decorations = document()[0].decorations;
  assert.ok(decorations >= 1, "처음 장식은 보낸다");

  for (let index = 0; index < 10; index++) await push();
  assert.equal(trial().length, 1, "같은 revision 의 재전송은 뷰어를 다시 띄우지 않는다");
  assert.equal(trial()[0].disposed, false);
  assert.equal(document()[0].decorations, decorations, "같은 분석 revision 은 장식을 다시 보내지 않는다");

  const next = snapshot();
  next.tabs[0].trial_result = { ...next.tabs[0].trial_result, revision: 8, content: "bmV3" };
  await push(next);
  assert.equal(trial().length, 2, "새 시험 결과는 한 번 다시 띄운다");
  assert.equal(trial()[0].disposed, true, "옛 뷰어는 해제된다");
  assert.equal(trial()[1].spec.content, "bmV3");

  const analysed = snapshot();
  analysed.tabs[0].analysis = { ...analysed.tabs[0].analysis, revision: 4 };
  await push(analysed);
  assert.equal(document()[0].decorations, decorations + 1, "새 분석은 장식을 한 번 다시 보낸다");
  assert.equal(document().length, 1, "문서 편집면은 다시 서지 않는다");
  root.unmount();
});

/* ---------- UX-04 키보드 모델 — 실제 커밋 위에서 핸들러를 React 위임 차례(대상 → 조상)대로 부른다 ---------- */
const propsOf = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))] || {};
/** 사건 하나를 대상에서 조상 쪽으로 흘린다. 멈추면 선다. 초점이 옮겨지면 새 초점 원소에서 onFocus 를 흘린다(React 의 focusin). */
function fire(env, target, type, init = {}) {
  const handler = { keydown: "onKeyDown", click: "onClick", contextmenu: "onContextMenu", focus: "onFocus" }[type];
  let stopped = false;
  let prevented = false;
  const before = env.document.activeElement;
  for (let node = target; node && !stopped; node = node.parentNode) {
    const run = propsOf(node)[handler];
    if (run) env.flushSync(() => run({ type, target, currentTarget: node, key: "", shiftKey: false, ctrlKey: false, altKey: false, metaKey: false, keyCode: 0,
      clientX: 0, clientY: 0, nativeEvent: { isComposing: false }, preventDefault() { prevented = true; }, stopPropagation() { stopped = true; }, ...init }));
  }
  const after = env.document.activeElement;
  if (type !== "focus" && after !== before && after?.parentNode) fire(env, after, "focus");
  return { prevented, stopped };
}
const press = (env, key, init = {}) => fire(env, env.document.activeElement, "keydown", { key, ...init });
const nodes = (env) => [...env.container.walk()];
const byRole = (env, role) => nodes(env).filter((node) => node.getAttribute?.("role") === role);
const named = (env, role, prefix) => byRole(env, role).find((node) => String(node.getAttribute("aria-label") ?? node.textContent).startsWith(prefix));
const focusOn = (env, node) => { node.focus(); fire(env, node, "focus"); };

test("UX-04/UX-05: the field outline is an APG tree — occurrence rows are built only when expanded; → expands then enters, ← returns then collapses", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  const field = () => named(env, "treeitem", "필드 · 이름");
  const occurrences = () => byRole(env, "treeitem").filter((node) => String(node.getAttribute("aria-label")).startsWith("이름 · 사용 위치"));
  const tree = env.container.querySelector('[role="tree"]');
  assert.equal(tree.getAttribute("aria-labelledby"), "authoring-outline-fields", "목록 이름은 보이는 제목이다");
  assert.equal(field().getAttribute("aria-expanded"), "false");
  assert.equal(field().getAttribute("tabindex"), "0", "tree 는 한 항목만 Tab 순서에 둔다");
  assert.ok(field().textContent.includes("이름 · 사용 위치 2곳"), "사용 위치 수는 글로 선다");
  assert.equal(occurrences().length, 0, "접힌 동안 사용 위치 줄을 짓지 않는다(UX-05)");
  focusOn(env, field());
  press(env, "ArrowRight");
  await settle();
  assert.equal(field().getAttribute("aria-expanded"), "true");
  assert.deepEqual(occurrences().map((node) => node.getAttribute("aria-label")), ["이름 · 사용 위치 1/2 · 첫째", "이름 · 사용 위치 2/2"]);
  assert.equal(occurrences()[0].parentNode.getAttribute("role"), "group");
  assert.equal(env.document.activeElement, field(), "→ 한 번은 펼치기만 한다");
  press(env, "ArrowRight");
  assert.equal(env.document.activeElement, occurrences()[0], "펼친 줄의 → 는 첫 자식으로");
  await settle();
  assert.equal(occurrences()[0].getAttribute("tabindex"), "0");
  assert.equal(field().getAttribute("tabindex"), "-1", "roving: 초점을 받은 줄이 Tab 의 입구가 된다");
  press(env, "ArrowDown");
  assert.equal(env.document.activeElement, occurrences()[1]);
  press(env, "Home");
  assert.equal(env.document.activeElement, field());
  press(env, "End");
  assert.equal(env.document.activeElement, occurrences()[1]);
  press(env, "ArrowLeft");
  assert.equal(env.document.activeElement, field(), "자식의 ← 는 부모로");
  press(env, "ArrowLeft");
  await settle();
  assert.equal(field().getAttribute("aria-expanded"), "false");
  assert.equal(occurrences().length, 0, "접으면 사용 위치 줄도 걷힌다");
  env.root.unmount();
});

test("#1025 §7.2: an opened outline field shows Python's normalized occurrence context in the label and accessible name, never the raw field command", async () => {
  const tab = { ...hwpxTab(), trial_result: null, trial_state: "untried",
    analysis: { revision: 3, slots: [], fields: [{ name: "진행상태", count: 1, occurrences: [{ entry: "Contents/section0.xml", paragraph: 0, context: "[진행상태] - 누름틀",
      raw: { text: "9Clickhere:set:50:Direction:wstring:8:{{진행상태}} HelpState:wstring:0:  {{진행상태}}{{진행상태}} - 누름틀" } }] }] } };
  const env = await boot(tab);
  focusOn(env, named(env, "treeitem", "필드 · 진행상태"));
  press(env, "ArrowRight");
  await settle();
  const occurrence = named(env, "treeitem", "진행상태 · 사용 위치");
  assert.ok(occurrence, "펼친 필드 줄에 사용 위치 줄이 선다");
  assert.equal(occurrence.textContent, "1. [진행상태] - 누름틀");
  assert.equal(occurrence.getAttribute("aria-label"), "진행상태 · 사용 위치 1/1 · [진행상태] - 누름틀");
  assert.ok(!env.container.textContent.includes("Clickhere"), "원문 명령 표기는 구조 목록에 서지 않는다");
  assert.ok(!nodes(env).some((node) => String(node.getAttribute?.("aria-label") || "").includes("Clickhere")));
  env.root.unmount();
});

test("UX-04 §10: Enter on an outline item selects it, marks it aria-current and moves to the name input; Escape returns to the selection", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  const field = () => named(env, "treeitem", "필드 · 이름");
  focusOn(env, field());
  assert.equal(field().getAttribute("aria-current"), null);
  press(env, "Enter");
  await settle();
  const input = env.container.querySelector(".authoring-properties input");
  assert.ok(input, "속성 패널이 열린다");
  assert.equal(env.document.activeElement, input, "구조 목록에서 고르면 이름 칸으로 간다");
  assert.equal(field().getAttribute("aria-current"), "true", "지금 대상은 aria-current 로 선다");
  press(env, "Escape");
  await settle();
  assert.equal(env.container.querySelector(".authoring-properties"), null);
  assert.ok(env.document.activeElement.closest(".authoring-canvas"), "Escape 는 선택 자리(편집면)로 돌아간다(§10)");
  env.root.unmount();
});

test("UX-04 WCAG 3.2.2: changing the properties command select keeps focus on the select", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  focusOn(env, named(env, "treeitem", "필드 · 이름"));
  press(env, "Enter");
  await settle();
  const select = env.container.querySelector(".authoring-properties select");
  focusOn(env, select);
  for (const value of ["relink_field", "unset_field", "rename_slot"]) {
    env.flushSync(() => propsOf(select).onChange({ target: { value }, currentTarget: select }));
    await settle();
    assert.equal(env.controller.viewModel.getSnapshot().commandType, value);
    assert.equal(env.document.activeElement, select, `${value}: 초점이 이름 칸으로 끌려가지 않는다`);
  }
  env.root.unmount();
});

test("UX-04 APG tabs: document tabs rove with ←/→/Home/End, activate on Enter, name the dirty state, and Delete closes to the neighbouring tab", async () => {
  const second = { ...hwpxTab(), id: "b", name: "b.hwpx", path: "b.hwpx", dirty: true, trial_result: null, trial_state: "untried" };
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" }, [second]);
  const tab = (id) => env.container.querySelector(`[role="tab"][data-tab="${id}"]`);
  assert.equal(tab("a").parentNode.getAttribute("role"), "tablist");
  assert.equal(tab("a").getAttribute("tabindex"), "0");
  assert.equal(tab("b").getAttribute("tabindex"), "-1");
  assert.equal(tab("b").getAttribute("aria-label"), "b.hwpx, 저장하지 않은 변경", "미저장 상태는 이름에 실린다");
  assert.equal(tab("b").querySelector(".authoring-tab-name").textContent, "b.hwpx ·", "보이는 기호는 그대로");
  assert.equal(tab("a").getAttribute("aria-controls"), "authoring-canvas");
  assert.ok(env.container.querySelector("#authoring-canvas"), "탭이 가리키는 편집면 구획이 있다");
  assert.equal(tab("a").querySelector("button").getAttribute("tabindex"), "-1", "닫기 단추는 Tab 순서에 없다");
  focusOn(env, tab("a"));
  press(env, "ArrowRight");
  assert.equal(env.document.activeElement, tab("b"));
  assert.equal(tab("b").getAttribute("aria-selected"), "false", "수동 활성화: 옮기기만 한다");
  press(env, "Home");
  assert.equal(env.document.activeElement, tab("a"));
  press(env, "ArrowLeft");
  assert.equal(env.document.activeElement, tab("b"), "끝에서 감싸 돈다");
  press(env, "Enter");
  await settle();
  assert.equal(tab("b").getAttribute("aria-selected"), "true");
  assert.equal(tab("b").getAttribute("tabindex"), "0");
  press(env, "Delete");
  await settle();
  assert.equal(tab("b"), null, "Delete 는 닫기(닫기 보호를 지난 뒤)");
  assert.ok(env.calls.some((call) => call.action === "close" && call.session_id === "b"));
  assert.equal(env.document.activeElement, tab("a"), "닫은 뒤에는 이웃 탭에 초점");
  env.root.unmount();
});

test("UX-04 APG toolbar: one tab stop, ←/→ wrap, Home/End, and the zoom select's arrows move between controls", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  const toolbar = env.container.querySelector('[role="toolbar"]');
  const stops = () => toolbar.querySelectorAll('[tabindex="0"]');
  assert.equal(stops().length, 1);
  const first = stops()[0];
  assert.equal(first.textContent, "문서 실행 취소");
  focusOn(env, first);
  press(env, "ArrowRight");
  assert.equal(env.document.activeElement.textContent, "문서 다시 실행");
  await settle();
  assert.equal(stops()[0], env.document.activeElement, "roving: 마지막 초점이 Tab 의 입구");
  press(env, "End");
  assert.equal(env.document.activeElement.getAttribute("aria-label"), "확대");
  assert.equal(press(env, "ArrowRight").prevented, true, "select 의 → 는 값 변경이 아니라 이동이다");
  assert.equal(env.document.activeElement, first, "끝에서 감싸 돈다");
  press(env, "ArrowLeft");
  assert.equal(env.document.activeElement.getAttribute("aria-label"), "확대");
  press(env, "Home");
  assert.equal(env.document.activeElement, first);
  assert.ok(![...toolbar.querySelectorAll("[data-rove]")].some((node) => node.disabled && node.getAttribute("tabindex") === "0"), "비활성 제어는 입구가 되지 않는다");
  env.root.unmount();
});

test("UX-04 APG tabs (dock): arrows rove the dock tabs, Enter opens a panel and moves into it, 닫기 returns focus to the tab that opened it", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  const dockTab = (key) => env.container.querySelector(`#authoring-dock-tab-${key}`);
  assert.equal(dockTab("trial").getAttribute("tabindex"), "0", "펼친 탭이 입구");
  focusOn(env, dockTab("trial"));
  press(env, "ArrowLeft");
  assert.equal(env.document.activeElement, dockTab("impact"));
  press(env, "Home");
  assert.equal(env.document.activeElement, dockTab("problems"));
  fire(env, dockTab("problems"), "click");                // Enter·Space 는 button 의 click 이다
  await settle();
  const panel = env.container.querySelector("#authoring-dock-panel");
  assert.equal(panel.getAttribute("aria-labelledby"), "authoring-dock-tab-problems");
  assert.equal(env.document.activeElement, panel, "제어가 없는 패널은 패널 자체(tabindex=-1)로 들어간다");
  fire(env, [...env.container.querySelectorAll(".authoring-dock-actions button")].find((node) => node.textContent === "닫기"), "click");
  await settle();
  assert.equal(env.container.querySelector("#authoring-dock-panel"), null);
  assert.equal(env.document.activeElement, dockTab("problems"), "닫으면 연 자리로 돌아간다");
  env.root.unmount();
});

test("UX-04 APG menu: Shift+F10 on an outline item selects it and opens the menu on the first usable item; ↑↓/Home/End rove incl. aria-disabled items; Tab and Escape close back to the item", async () => {
  const commands = [{ type: "create_field", enabled: false, reason: "이미 필드입니다.", alternative: null }, { type: "rename_field", enabled: true, reason: null, alternative: null }];
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" }, [], (action) => action === "locate" ? { commands } : {});
  const field = () => named(env, "treeitem", "필드 · 이름");
  const items = () => byRole(env, "menuitem");
  focusOn(env, field());
  assert.equal(press(env, "F10", { shiftKey: true }).stopped, true, "구조 목록이 제 문맥 메뉴를 연다");
  await settle();
  assert.ok(env.calls.some((call) => call.action === "locate"), "메뉴를 열기 전에 그 줄을 고른다");
  const menu = env.container.querySelector('[role="menu"]');
  assert.ok(menu, "메뉴가 선다");
  assert.ok([...menu.childNodes].every((node) => node.getAttribute("role") === "menuitem"), "메뉴의 자식은 menuitem 뿐이다");
  assert.equal(env.document.activeElement.textContent, "필드 이름 변경", "첫 **사용 가능** 항목에 초점");
  press(env, "ArrowUp");
  assert.equal(env.document.activeElement.getAttribute("aria-label"), "선택으로 만들기", "판정이 없는 항목도 초점을 받는다");
  assert.equal(env.document.activeElement.getAttribute("aria-disabled"), "true");
  assert.equal(env.document.activeElement.getAttribute("aria-describedby"), null, "판정이 없으면 사유 문장도 없다");
  press(env, "Home");
  assert.equal(env.document.activeElement.getAttribute("aria-label"), "필드로 만들기", "불가 항목도 초점을 받는다");
  assert.equal(env.document.activeElement.getAttribute("aria-disabled"), "true");
  const described = env.document.activeElement.getAttribute("aria-describedby");
  assert.equal(env.container.querySelector(`#${described}`).textContent, "이미 필드입니다.", "사유를 설명으로 읽힌다");
  press(env, "End");
  assert.equal(env.document.activeElement, items().at(-1));
  press(env, "ArrowDown");
  assert.equal(env.document.activeElement, items()[0], "감싸 돈다");
  fire(env, env.document.activeElement, "click");       // 불가 항목의 click 은 아무것도 하지 않는다
  assert.ok(env.container.querySelector('[role="menu"]'), "불가 항목은 실행되지 않는다");
  press(env, "Tab");
  await settle();
  assert.equal(env.container.querySelector('[role="menu"]'), null, "Tab 은 메뉴를 닫는다");
  assert.equal(env.document.activeElement, field(), "연 자리(그 줄)로 돌아간 뒤 Tab 이 이어진다");
  press(env, "F10", { shiftKey: true });
  await settle();
  assert.ok(env.container.querySelector('[role="menu"]'));
  press(env, "Escape");
  await settle();
  assert.equal(env.container.querySelector('[role="menu"]'), null);
  assert.equal(env.document.activeElement, field(), "Escape 도 그 줄로");
  env.root.unmount();
});

test("UX-04 live region: one polite status that speaks on transitions only — not on repeated pushes or stale trials", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried", trial_state_label: "시험 전", readiness: { state: "ready", errors: 0, warnings: 0, message: null } });
  const live = () => env.container.querySelector(".authoring-live");
  assert.equal(byRole(env, "status").length, 1, "status 는 하나뿐이다");
  assert.equal(live().getAttribute("role"), "status");
  assert.equal(live().textContent, "");
  const next = (patch) => { const snap = env.snapshot(); snap.tabs[0] = { ...snap.tabs[0], ...patch }; return snap; };
  for (let index = 0; index < 3; index++) await env.push();
  assert.equal(live().textContent, "", "같은 상태의 재전송은 읽지 않는다");
  await env.push(next({ trial_state: "stale", trial_state_label: "마지막 시험 이후 변경됨" }));
  assert.equal(live().textContent, "", "오래됨은 결과가 아니다 — 입력마다 읽지 않는다");
  await env.push(next({ trial_state: "failed", trial_state_label: "시험 실패" }));
  assert.equal(live().textContent, "시험 실패");
  const seq = env.controller.viewModel.getSnapshot().live.seq;
  await env.push(next({ trial_state: "stale", trial_state_label: "마지막 시험 이후 변경됨" }));
  await env.push(next({ trial_state: "failed", trial_state_label: "시험 실패" }));
  assert.equal(env.controller.viewModel.getSnapshot().live.seq, seq, "같은 결과의 자동 재시험은 다시 읽지 않는다");
  await env.push(next({ readiness: { state: "draft", errors: 1, warnings: 0, message: "사용 전에 구조 오류 1개를 확인하세요." } }));
  assert.equal(live().textContent, "사용 전에 구조 오류 1개를 확인하세요.");
  env.flushSync(() => env.controller.update({ notice: "초안은 저장되었습니다. 사용 전에 구조 오류 1개를 확인하세요." }));
  await settle();
  assert.equal(live().textContent, "초안은 저장되었습니다. 사용 전에 구조 오류 1개를 확인하세요.");
  assert.ok(!env.container.querySelector(".authoring-notice").hasAttribute("role"), "보이는 알림 줄은 live region 이 아니다");
  assert.ok(!env.container.querySelector("footer").matches('[role="status"]'), "상태 막대는 live region 이 아니다");
  env.root.unmount();
});
