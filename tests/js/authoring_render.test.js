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
  getClientRects() { return { length: this.isConnected ? 1 : 0 }; }
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
  document.createElementNS = (namespace, tag) => { const element = new FakeElement(tag, document); element.namespaceURI = namespace; return element; };
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
    async invoke(method, ...args) { calls.push({ invoke: method, args }); return { ok: true, value: null }; },
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
      setDecorations: async (projection) => { record.decorations += 1; record.projection = projection; }, dispose: () => { record.disposed = true; } };
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
  const handler = { keydown: "onKeyDown", click: "onClick", contextmenu: "onContextMenu", focus: "onFocus", mouseenter: "onMouseEnter", mouseleave: "onMouseLeave" }[type];
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
/** 구조 패널의 「필드」 보기를 연다(UX-09) — 필드 목록은 그 탭 안의 tree 다. */
const showFields = (env) => fire(env, env.container.querySelector("#authoring-outline-fields"), "click");
const inPanel = (env, panel, role, prefix) => byRole(env, role).find((node) => node.closest(`#authoring-outline-${panel}-panel`)
  && String(node.getAttribute("aria-label") ?? node.textContent).startsWith(prefix));
const fieldRow = (env, prefix) => inPanel(env, "fields", "treeitem", prefix);

test("UX-04/UX-05: the field outline is an APG tree — occurrence rows are built only when expanded; → expands then enters, ← returns then collapses", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  showFields(env);
  await settle();
  const field = () => fieldRow(env, "필드 · 이름");
  const occurrences = () => byRole(env, "treeitem").filter((node) => String(node.getAttribute("aria-label")).startsWith("이름 · 사용 위치"));
  const tree = env.container.querySelector('#authoring-outline-fields-panel [role="tree"]');
  assert.equal(tree.getAttribute("aria-labelledby"), "authoring-outline-fields", "목록 이름은 보이는 제목(필드 탭)이다");
  assert.equal(field().getAttribute("aria-expanded"), "false");
  assert.equal(field().getAttribute("tabindex"), "0", "tree 는 한 항목만 Tab 순서에 둔다");
  assert.equal(field().querySelector(".authoring-tree-name").textContent, "이름");
  assert.equal(field().querySelector(".authoring-tree-meta").textContent, "사용 위치 2곳", "사용 위치 수는 글로 선다");
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

test("UX-07: keys and right-clicks forwarded from the editor iframe take the shell's own Escape and menu paths; iframes are named", async () => {
  const { controller, mounts, root } = await boot(hwpxTab());
  const editor = mounts.find((record) => record.spec.fileName === "a.hwpx");
  const trial = mounts.find((record) => record.spec.fileName === "시험 결과.hwpx");
  assert.equal(editor.spec.title, "a.hwpx", "편집면 iframe 은 문서 이름으로 읽힌다");
  assert.equal(trial.spec.title, "시험 결과");
  const view = () => controller.viewModel.getSnapshot();
  controller.update({ panel: "properties" });
  await settle();
  editor.spec.onShortcut("Escape");
  await settle();
  assert.equal(view().panel, "", "편집면 안의 Escape 도 셸 Escape 처럼 속성 패널을 닫는다");
  editor.spec.onContextMenu({ x: 40, y: 60 });
  await settle();
  assert.deepEqual([view().contextMenu?.x, view().contextMenu?.y], [40, 60], "편집면 우클릭은 셸 문맥 메뉴를 그 자리에 연다");
  controller.update({ panel: "search" });
  editor.spec.onShortcut("Escape");
  await settle();
  assert.equal(view().contextMenu, null, "Escape 는 메뉴부터 닫는다");
  assert.equal(view().panel, "search", "메뉴를 닫는 Escape 는 패널을 건드리지 않는다");
  editor.spec.onShortcut("CtrlShiftP");
  await settle();
  assert.ok(view().palette > 0, "편집면 안의 Ctrl+Shift+P 는 셸의 명령 팔레트를 연다(IDE-02)");
  assert.equal(view().panel, "search", "팔레트는 독 패널을 바꾸지 않는다");
  root.unmount();
});

test("#1025 §7.2: an opened outline field shows Python's normalized occurrence context in the label and accessible name, never the raw field command", async () => {
  const tab = { ...hwpxTab(), trial_result: null, trial_state: "untried",
    analysis: { revision: 3, slots: [], fields: [{ name: "진행상태", count: 1, occurrences: [{ entry: "Contents/section0.xml", paragraph: 0, context: "[진행상태] - 누름틀",
      raw: { text: "9Clickhere:set:50:Direction:wstring:8:{{진행상태}} HelpState:wstring:0:  {{진행상태}}{{진행상태}} - 누름틀" } }] }] } };
  const env = await boot(tab);
  showFields(env);
  await settle();
  focusOn(env, fieldRow(env, "필드 · 진행상태"));
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
  showFields(env);
  await settle();
  const field = () => fieldRow(env, "필드 · 이름");
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
  showFields(env);
  await settle();
  focusOn(env, fieldRow(env, "필드 · 이름"));
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
  assert.equal(tab("b").querySelector(".authoring-tab-name").textContent, "b.hwpx", "이름 칸은 이름뿐이다");
  assert.equal(tab("b").querySelector(".authoring-dirty").getAttribute("aria-hidden"), "true", "미저장은 보이는 점 원소로 선다(뜻은 이름이 싣는다)");
  assert.equal(tab("a").querySelector(".authoring-dirty"), null);
  assert.equal(tab("a").getAttribute("aria-controls"), "authoring-canvas");
  assert.ok(env.container.querySelector("#authoring-canvas"), "탭이 가리키는 편집면 구획이 있다");
  assert.equal(tab("a").querySelector("button").getAttribute("tabindex"), "-1", "닫기 단추는 Tab 순서에 없다");
  assert.equal(tab("a").querySelector("button").getAttribute("aria-label"), "a.hwpx 닫기", "그림 단추의 이름은 기존 문구 그대로다");
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

test("UX-04 APG toolbar: one tab stop, ←/→ wrap, Home/End; the last control is 결과 시험 and zoom lives in the status bar", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  const toolbar = env.container.querySelector('[role="toolbar"]');
  const stops = () => toolbar.querySelectorAll('[tabindex="0"]');
  assert.equal(stops().length, 1);
  const first = stops()[0];
  assert.equal(first.getAttribute("aria-label"), "문서 실행 취소");
  assert.equal(first.getAttribute("title"), "문서 실행 취소", "그림 단추의 이름은 툴팁으로도 선다");
  focusOn(env, first);
  press(env, "ArrowRight");
  assert.equal(env.document.activeElement.getAttribute("aria-label"), "문서 다시 실행");
  await settle();
  assert.equal(stops()[0], env.document.activeElement, "roving: 마지막 초점이 Tab 의 입구");
  press(env, "End");
  const trial = toolbar.querySelector('[data-rove="trial"]');
  assert.equal(env.document.activeElement, trial, "마지막 제어는 실행 단추 「결과 시험」");
  assert.equal(trial.textContent, "결과 시험");
  assert.equal(press(env, "ArrowRight").prevented, true, "→ 는 이동이다");
  assert.equal(env.document.activeElement, first, "끝에서 감싸 돈다");
  press(env, "ArrowLeft");
  assert.equal(env.document.activeElement, trial);
  assert.equal(toolbar.querySelector("select"), null, "도구 막대에 확대 선택이 없다");
  const zoom = env.container.querySelector('.authoring-status select[aria-label="확대"]');
  assert.ok(zoom && !zoom.hasAttribute("data-rove"), "확대는 상태 막대의 보통 Tab 제어다");
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
  // 연결 작업이 없는 문서라 「변경 영향·작업 적용」 문맥 탭이 없다(NG-09) — 시험 앞은 원문 표기다.
  assert.equal(dockTab("impact"), null);
  assert.equal(env.document.activeElement, dockTab("raw"));
  press(env, "Home");
  assert.equal(env.document.activeElement, dockTab("problems"));
  fire(env, dockTab("problems"), "click");                // Enter·Space 는 button 의 click 이다
  await settle();
  const panel = env.container.querySelector("#authoring-dock-panel");
  assert.equal(panel.getAttribute("aria-labelledby"), "authoring-dock-tab-problems");
  assert.equal(env.document.activeElement, panel, "제어가 없는 패널은 패널 자체(tabindex=-1)로 들어간다");
  fire(env, [...env.container.querySelectorAll(".authoring-dock-actions button")].find((node) => node.getAttribute("aria-label") === "닫기"), "click");
  await settle();
  assert.equal(env.container.querySelector("#authoring-dock-panel"), null);
  assert.equal(env.document.activeElement, dockTab("problems"), "닫으면 연 자리로 돌아간다");
  env.root.unmount();
});

test("UX-04/IDE-02 APG menu: Shift+F10 on an outline item selects it and opens a menu of runnable commands only; ↑↓/Home/End rove; Tab and Escape close back to the item", async () => {
  const commands = [{ type: "create_field", enabled: false, reason: "이미 필드입니다.", alternative: null },
    { type: "rename_field", enabled: true, reason: null, alternative: null }, { type: "relink_field", enabled: true, reason: null, alternative: null }];
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" }, [], (action) => action === "locate" ? { commands } : {});
  showFields(env);
  await settle();
  const field = () => fieldRow(env, "필드 · 이름");
  const items = () => byRole(env, "menuitem");
  focusOn(env, field());
  assert.equal(press(env, "F10", { shiftKey: true }).stopped, true, "구조 목록이 제 문맥 메뉴를 연다");
  await settle();
  assert.ok(env.calls.some((call) => call.action === "locate"), "메뉴를 열기 전에 그 줄을 고른다");
  const menu = env.container.querySelector('[role="menu"]');
  assert.ok(menu, "메뉴가 선다");
  assert.ok([...menu.childNodes].every((node) => node.getAttribute("role") === "menuitem"), "메뉴의 자식은 menuitem 뿐이다");
  // IDE-02(P-04): 판정이 서면 되는 명령만 싣는다 — 불가 항목(필드로 만들기)과 판정 없는 명령은 숨는다(UX-04 R5 되돌림).
  assert.deepEqual(items().map((node) => node.textContent), ["필드 이름 변경", "필드 연결 변경"]);
  assert.ok(items().every((node) => node.getAttribute("aria-disabled") === null && node.getAttribute("aria-describedby") === null), "불가 항목·사유 설명이 없다");
  assert.equal(env.document.activeElement, items()[0], "첫 항목에 초점");
  press(env, "ArrowDown");
  assert.equal(env.document.activeElement, items()[1]);
  press(env, "ArrowDown");
  assert.equal(env.document.activeElement, items()[0], "감싸 돈다");
  press(env, "End");
  assert.equal(env.document.activeElement, items().at(-1));
  press(env, "Home");
  assert.equal(env.document.activeElement, items()[0]);
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

test("IDE-02 (P-04): with verdicts the context menu carries runnable items and alternatives only; with nothing runnable it is one 명령 that opens the palette", async () => {
  const types = ["create_field", "create_slot", "create_option", "rename_field", "relink_field", "unset_field", "rename_slot", "rename_option", "adjust_range", "unwrap", "delete", "duplicate", "move"];
  const blocked = types.map((type) => ({ type, enabled: false, reason: "먼저 문서에서 내용을 고르세요.", alternative: null }));
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  const view = () => env.controller.viewModel.getSnapshot();
  const canvas = env.container.querySelector(".authoring-canvas");
  const open = async () => { fire(env, canvas, "contextmenu", { clientX: 30, clientY: 40 }); await settle(); };
  env.controller.update({ commands: blocked.map((entry) => entry.type === "create_field" ? { ...entry, enabled: true, reason: null }
    : entry.type === "create_option" ? { ...entry, alternative: { label: "먼저 항목 만들기", command_type: "create_slot" } } : entry) });
  await open();
  let items = byRole(env, "menuitem");
  assert.deepEqual(items.map((node) => node.textContent), ["필드로 만들기", "먼저 항목 만들기"], "13 판정 중 되는 1 + 대안 1");
  assert.equal(items.filter((node) => node.getAttribute("aria-disabled") === "true").length, 0);
  fire(env, items[1], "click");
  await settle();
  assert.deepEqual([view().panel, view().commandType, view().contextMenu], ["properties", "create_slot", null], "대안은 Python 이 준 명령으로 같은 pick 경로를 탄다");
  env.controller.update({ commands: blocked, panel: "" });
  await open();
  items = byRole(env, "menuitem");
  // 결정 C: 편집면에서 연 메뉴는 「필드로 만들기」를 늘 첫 항목으로 싣는다 — 불가이면 흐리게, Python 사유를 설명 줄로.
  // 그 밖에 되는 것이 없으니 팔레트를 여는 「명령」이 뒤따른다(사유가 항목에 서므로 공유 머리 줄은 없다).
  assert.deepEqual(items.map((node) => node.getAttribute("aria-label") || node.textContent), ["필드로 만들기", "명령"]);
  assert.equal(items[0].getAttribute("aria-disabled"), "true");
  assert.equal(env.container.querySelector(`#${items[0].getAttribute("aria-describedby")}`).textContent, "먼저 문서에서 내용을 고르세요.");
  assert.equal(env.container.querySelector("#authoring-command-reason-menu"), null);
  assert.equal(env.document.activeElement, items[1], "초점은 첫 사용 가능 항목(「명령」)");
  fire(env, items[0], "click");
  await settle();
  assert.ok(env.container.querySelector('[role="menu"]'), "불가 항목의 누름은 실행하지 않는다");
  fire(env, items[1], "click");
  await settle();
  assert.equal(env.container.querySelector('[role="menu"]'), null);
  const input = env.container.querySelector('.authoring-command-palette input[role="combobox"]');
  assert.ok(input, "팔레트가 선다");
  assert.equal(env.document.activeElement, input, "입력칸에 초점");
  const group = byRole(env, "group").find((node) => node.closest(".authoring-command-palette"));
  assert.equal(group.getAttribute("aria-label"), "먼저 문서에서 내용을 고르세요.", "사유는 팔레트의 무리 이름으로 읽힌다");
  assert.equal(byRole(env, "group").filter((node) => node.closest(".authoring-command-palette")).length, 1, "사유당 한 무리");
  env.root.unmount();
});

test("IDE-02 (P-10): Ctrl+Shift+P opens a non-modal palette without touching the dock; typing filters, ↑↓ reach disabled items, Enter runs only runnable ones, Escape stays inside and returns focus", async () => {
  const types = ["create_field", "create_slot", "create_option", "rename_field", "relink_field", "unset_field", "rename_slot", "rename_option", "adjust_range", "unwrap", "delete", "duplicate", "move"];
  const env = await boot(hwpxTab());
  const view = () => env.controller.viewModel.getSnapshot();
  env.controller.update({ commands: types.map((type) => type === "create_field" || type === "rename_field" ? { type, enabled: true, reason: null, alternative: null }
    : { type, enabled: false, reason: type.startsWith("create") ? "먼저 항목 안의 내용을 고르세요." : "먼저 필드를 고르세요.", alternative: null }) });
  await settle();
  const trialTab = () => env.container.querySelector("#authoring-dock-tab-trial");
  assert.equal(trialTab().getAttribute("aria-selected"), "true", "시험 탭이 열려 있다");
  const more = env.container.querySelector('.authoring-toolbar [data-rove="more"]');
  focusOn(env, more);
  press(env, "P", { ctrlKey: true, shiftKey: true });
  await settle();
  const palette = () => env.container.querySelector('.authoring-command-palette[role="dialog"]');
  const input = () => palette()?.querySelector('input[role="combobox"]');
  assert.ok(palette() && palette().getAttribute("aria-label") === "명령 팔레트" && !palette().closest(".authoring-dock"), "독이 아니라 오버레이다");
  assert.equal(input().getAttribute("aria-label"), "명령");
  assert.equal(env.document.activeElement, input(), "입력칸에 초점");
  assert.equal(view().panel, "", "view.panel 이 바뀌지 않는다");
  assert.equal(trialTab().getAttribute("aria-selected"), "true", "팔레트를 열어도 시험 탭이 그대로다");
  assert.ok(!byRole(env, "tab").some((node) => node.textContent === "명령"), "독에 「명령」 탭이 없다");
  const active = () => palette().querySelector(`#${input().getAttribute("aria-activedescendant")}`);
  const options = () => byRole(env, "option").filter((node) => node.closest(".authoring-command-palette"));
  assert.equal(active().textContent, "필드로 만들기", "첫 되는 항목이 활성");
  // 걸러내기(부분 일치). 일치가 없으면 문장 하나.
  env.flushSync(() => propsOf(input()).onChange({ target: { value: "필드 이름" } }));
  await settle();
  assert.deepEqual(options().map((node) => node.textContent), ["필드 이름 변경F2"]);
  env.flushSync(() => propsOf(input()).onChange({ target: { value: "없는 명령" } }));
  await settle();
  assert.equal(options().length, 0);
  assert.equal(palette().querySelector('[role="listbox"]'), null);
  assert.equal(palette().querySelector("p").textContent, "일치하는 명령이 없습니다.");
  assert.equal(input().getAttribute("aria-expanded"), "false");
  assert.equal(input().getAttribute("aria-activedescendant"), null);
  env.flushSync(() => propsOf(input()).onChange({ target: { value: "" } }));
  await settle();
  // ↑ 는 감싸 돌아 마지막(흐린) 항목으로 — 흐린 항목도 활성이 되어 무리 이름(사유)이 읽힌다. Enter 는 아무것도 하지 않는다.
  press(env, "ArrowUp");
  assert.equal(active().getAttribute("aria-disabled"), "true");
  assert.equal(active().closest('[role="group"]').getAttribute("aria-label"), "먼저 필드를 고르세요.");
  assert.equal(active().getAttribute("aria-selected"), "true");
  assert.equal(press(env, "Enter", { nativeEvent: { isComposing: true } }).prevented, false, "조합 중 Enter 는 팔레트의 것이 아니다");
  press(env, "Enter");
  await settle();
  assert.ok(palette(), "흐린 항목의 Enter 는 실행하지 않고 닫지도 않는다");
  assert.equal(view().panel, "");
  assert.equal(byRole(env, "group").filter((node) => node.closest(".authoring-command-palette")).length, 2, "사유 무리는 서로 다른 사유 수만큼");
  // Escape 는 팔레트 안에서 멈춘다 — 셸 Escape(속성 패널 닫기)로 새지 않고 연 자리로 초점을 돌린다.
  env.controller.update({ panel: "properties", commandType: "create_field" });
  await settle();
  focusOn(env, input());
  const escape = press(env, "Escape");
  await settle();
  assert.equal(escape.stopped, true, "Escape 전파를 막는다");
  assert.equal(palette(), null, "닫힌다");
  assert.equal(view().panel, "properties", "속성 패널은 그대로다");
  assert.equal(env.document.activeElement, more, "연 자리로 초점이 돌아간다");
  // 다시 열어 ↓ 로 되는 명령을 고르고 Enter — 같은 pick 경로로 속성 패널이 그 명령으로 열린다.
  env.controller.update({ panel: "" });
  focusOn(env, more);
  press(env, "P", { ctrlKey: true, shiftKey: true });
  await settle();
  press(env, "ArrowDown");
  assert.equal(active().textContent, "필드 이름 변경F2");
  press(env, "Enter");
  await settle();
  assert.equal(palette(), null, "실행하면 닫힌다");
  assert.deepEqual([view().panel, view().commandType], ["properties", "rename_field"]);
  env.root.unmount();
});

test("IDE-02 (P-10): the palette's 문맥 메뉴 and 이전 영역으로 act at the place that opened it", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" }, [], (action) => action === "locate" ? { commands: [{ type: "rename_field", enabled: true, reason: null, alternative: null }] } : {});
  showFields(env);
  await settle();
  const field = fieldRow(env, "필드 · 이름");
  focusOn(env, field);
  press(env, "P", { ctrlKey: true, shiftKey: true });
  await settle();
  const input = () => env.container.querySelector('.authoring-command-palette input[role="combobox"]');
  env.flushSync(() => propsOf(input()).onChange({ target: { value: "문맥" } }));
  await settle();
  press(env, "Enter");
  await settle();
  assert.equal(env.container.querySelector(".authoring-command-palette"), null);
  const menu = env.container.querySelector('[role="menu"][aria-label="문맥 명령"]');
  assert.ok(menu, "연 자리(그 줄)에서 Shift+F10 을 누른 것과 같다");
  assert.equal(env.controller.viewModel.getSnapshot().contextMenu.trigger, field);
  press(env, "Escape");
  await settle();
  assert.equal(env.document.activeElement, field);
  // 「이전 영역으로」(Shift+F6)는 연 자리에서 한 영역 뒤로 — 구조 패널 앞은 좁은 폭의 구조 레일 단추다.
  press(env, "P", { ctrlKey: true, shiftKey: true });
  await settle();
  env.flushSync(() => propsOf(input()).onChange({ target: { value: "이전 영역" } }));
  await settle();
  press(env, "Enter");
  await settle();
  assert.equal(env.container.querySelector(".authoring-command-palette"), null);
  assert.ok(env.document.activeElement.matches(".authoring-rail-toggle"), "셸 F6 순환과 같은 길");
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

/* ---------- UX-09 문서 척추: 소속·차례는 Python 투영 그대로, 안내선 종류·시험 점·같은 필드·현재 위치·강조 ---------- */
const SECTION = "Contents/section0.xml";
const spineTab = () => ({ ...hwpxTab(), trial_result: null, trial_state: "current",
  trial_coverage: [{ slot_id: "조건", option_id: "국내", state: "current" }, { slot_id: "조건", option_id: "해외", state: "untried" }],
  analysis: { revision: 5,
    slots: [{ id: "조건", label: "견적 조건", order: 1, location_label: "문단 3–7", location: { entry: SECTION, start_paragraph: 2, end_paragraph: 6 },
      options: [{ id: "국내", label: "국내 조달", order: 2, location_label: "문단 3–4", location: { entry: SECTION, start_paragraph: 2, end_paragraph: 3 } },
        { id: "해외", label: "해외 조달", order: 4, location_label: "문단 5–7", location: { entry: SECTION, start_paragraph: 4, end_paragraph: 6 } }] }],
    fields: [
      { name: "수요기관", count: 1, occurrences: [{ entry: SECTION, occurrence: 0, paragraph: 0, order: 0, slot_id: null, option_id: null, context: "[수요기관] 귀하" }] },
      { name: "단가", count: 2, occurrences: [{ entry: SECTION, occurrence: 1, paragraph: 3, order: 3, slot_id: "조건", option_id: "국내", context: "단가 [단가]" },
        { entry: SECTION, occurrence: 3, paragraph: 5, order: 6, slot_id: "조건", option_id: "해외", context: "단가 [단가]" }] },
      { name: "환율", count: 1, occurrences: [{ entry: SECTION, occurrence: 2, paragraph: 5, order: 5, slot_id: "조건", option_id: "해외", context: "환율 [환율]" }] },
      { name: "담당자", count: 1, occurrences: [{ entry: SECTION, occurrence: 4, paragraph: 9, order: 7, slot_id: null, option_id: null, context: "[담당자]" }] }] } });
const labelOf = (node) => node.getAttribute("aria-label");
const childItems = (node) => [...(node.querySelector('[role="group"]')?.childNodes || [])].filter((child) => child.getAttribute?.("role") === "treeitem");

test("UX-09: the structure view is a document spine — slots hold options, uses stand where they are, in Python's order", async () => {
  const env = await boot(spineTab());
  const tree = env.container.querySelector('#authoring-outline-structure-panel [role="tree"]');
  assert.equal(tree.getAttribute("aria-labelledby"), "authoring-outline-structure");
  const top = [...tree.childNodes];
  assert.deepEqual(top.map(labelOf), ["필드 · 수요기관 · 사용 위치 1곳", "항목 · 견적 조건 · 문단 3–7", "필드 · 담당자 · 사용 위치 1곳"], "척추 위의 필드는 문서 순서로 항목 사이에 선다");
  const slot = top[1];
  assert.equal(slot.getAttribute("data-kind"), "slot", "항목의 자식 구간은 실선 안내선(CSS 가 data-kind 로 그린다)");
  assert.equal(slot.querySelector(".authoring-tree-meta").textContent, "문단 3–7", "위치 표시는 Python 의 문자열 그대로다");
  const [domestic, overseas] = childItems(slot);
  assert.deepEqual([domestic, overseas].map((node) => node.getAttribute("data-kind")), ["option", "option"], "선택들은 같은 들여쓰기의 형제(점선 안내선 공유)");
  assert.equal(labelOf(domestic), "선택 · 국내 조달 · 상위 항목 견적 조건 · 문단 3–4 · 현재 시험 구성 확인됨");
  assert.equal(labelOf(overseas), "선택 · 해외 조달 · 상위 항목 견적 조건 · 문단 5–7 · 시험하지 않음");
  assert.equal(domestic.querySelector(".authoring-coverage-dot").getAttribute("data-state"), "current", "시험 상태는 점의 채움 모양으로도 선다");
  assert.equal(overseas.querySelector(".authoring-coverage-dot").getAttribute("title"), "시험하지 않음");
  assert.deepEqual(childItems(domestic).map(labelOf), ["필드 · 단가 · 같은 필드, 1/2"]);
  assert.deepEqual(childItems(overseas).map(labelOf), ["필드 · 환율 · 사용 위치 1곳", "필드 · 단가 · 같은 필드, 2/2"], "갈래 안의 사용 위치도 문서 순서다");
  assert.equal(env.container.querySelector("#authoring-outline-fields").textContent, "필드 4", "필드 탭은 필드 수를 싣는다");
  assert.ok(env.container.querySelector("#authoring-outline-fields-panel").hasAttribute("hidden"), "고르지 않은 보기는 숨는다");
  assert.equal(env.container.querySelector("#authoring-outline-structure-panel .authoring-outline-empty"), null, "항목이 있으면 빈 상태 안내가 없다");
  env.root.unmount();
});

test("UX-09: the caret's place marks exactly one row current — the innermost the breadcrumb names", async () => {
  const env = await boot(spineTab());
  const current = () => byRole(env, "treeitem").filter((node) => node.closest("#authoring-outline-structure-panel") && node.getAttribute("aria-current") === "true").map(labelOf);
  assert.deepEqual(current(), []);
  const exchange = spineTab().analysis.fields[2].occurrences[0];
  env.flushSync(() => env.controller.update({ selected: null, matches: [{ kind: "slot", slot_id: "조건" }, { kind: "option", slot_id: "조건", option_id: "해외" }, { kind: "field", name: "환율", location: exchange }] }));
  await settle();
  assert.deepEqual(current(), ["필드 · 환율 · 사용 위치 1곳"], "가장 안쪽(사용 위치) 줄 하나만 현재다");
  assert.equal(inPanel(env, "fields", "treeitem", "필드 · 환율").getAttribute("aria-current"), "true", "필드 보기에서는 접힌 필드 줄이 대신 선다");
  env.flushSync(() => env.controller.update({ matches: [{ kind: "slot", slot_id: "조건" }, { kind: "option", slot_id: "조건", option_id: "해외" }] }));
  await settle();
  assert.deepEqual(current(), ["선택 · 해외 조달 · 상위 항목 견적 조건 · 문단 5–7 · 시험하지 않음"]);
  env.root.unmount();
});

test("UX-09: resting on a row asks the editor to emphasize that range; leaving the tree clears it", async () => {
  const env = await boot(spineTab());
  const editor = env.mounts.find((record) => record.spec.fileName === "a.hwpx");
  const overseas = inPanel(env, "structure", "treeitem", "선택 · 해외 조달");
  fire(env, overseas.querySelector(".authoring-tree-row"), "mouseenter");
  await new Promise((resolve) => setTimeout(resolve, 90));
  await settle();
  assert.deepEqual(editor.projection.highlight, { kind: "option", id: "해외", slot_id: "조건" }, "선택은 소속 항목과 함께 가리킨다");
  assert.equal(editor.projection.mode, "template", "표시 모드는 그대로다");
  fire(env, inPanel(env, "structure", "treeitem", "필드 · 단가 · 같은 필드, 2/2").querySelector(".authoring-tree-row"), "mouseenter");
  await new Promise((resolve) => setTimeout(resolve, 90));
  await settle();
  assert.deepEqual(editor.projection.highlight, { kind: "field", id: "단가", index: 2 }, "사용 위치 한 곳만 가리킨다");
  fire(env, env.container.querySelector('#authoring-outline-structure-panel [role="tree"]'), "mouseleave");
  await new Promise((resolve) => setTimeout(resolve, 90));
  await settle();
  assert.equal(editor.projection.highlight, null, "목록을 떠나면 강조를 걷는다");
  env.root.unmount();
});

test("UX-09: the filter narrows both views to matching rows and keeps their ancestors", async () => {
  const env = await boot(spineTab());
  const input = env.container.querySelector('input[aria-label="구조 필터"]');
  env.flushSync(() => propsOf(input).onChange({ target: { value: "환율" } }));
  await settle();
  const structure = () => byRole(env, "treeitem").filter((node) => node.closest("#authoring-outline-structure-panel")).map(labelOf);
  assert.deepEqual(structure(), ["항목 · 견적 조건 · 문단 3–7", "선택 · 해외 조달 · 상위 항목 견적 조건 · 문단 5–7 · 시험하지 않음", "필드 · 환율 · 사용 위치 1곳"],
    "일치하는 줄과 그 조상만 남는다");
  const fields = () => byRole(env, "treeitem").filter((node) => node.closest("#authoring-outline-fields-panel")).map(labelOf);
  assert.deepEqual(fields(), ["필드 · 환율 · 사용 위치 1곳"]);
  env.flushSync(() => propsOf(input).onChange({ target: { value: "귀하" } }));
  await settle();
  assert.deepEqual(fields(), ["필드 · 수요기관 · 사용 위치 1곳", "수요기관 · 사용 위치 1/1 · [수요기관] 귀하"], "문맥으로 찾은 필드는 그 사용 위치를 펼쳐 보인다");
  const result = propsOf(input).onKeyDown;
  let stopped = false;
  env.flushSync(() => result({ key: "Escape", nativeEvent: {}, preventDefault() {}, stopPropagation() { stopped = true; } }));
  await settle();
  assert.ok(stopped && input.value === "", "필터의 Escape 는 입력만 비우고 패널을 닫지 않는다");
  assert.equal(structure().length, 8, "필터를 비우면 모든 줄이 돌아온다(척추 3 · 선택 2 · 사용 위치 3)");
  env.root.unmount();
});

test("NG-01: without slots or fields both views point at 필드로 만들기; the 항목 sentence is gone everywhere", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried", analysis: { revision: 1, slots: [], fields: [] } });
  const fields = "필드가 없습니다. 문구를 고르고 「필드로 만들기」를 누르세요.";
  // 기본 탭(구조)이 첫 행동인 필드 만들기를 가리킨다 — 필드 탭도 같은 문장이다.
  assert.equal(env.container.querySelector("#authoring-outline-structure").getAttribute("aria-selected"), "true", "구조가 기본 탭이다");
  assert.equal(env.container.querySelector("#authoring-outline-structure-panel .authoring-outline-empty").textContent, fields);
  assert.equal(env.container.querySelector("#authoring-outline-fields-panel .authoring-outline-empty").textContent, fields);
  assert.equal(env.container.querySelector('[role="tree"]'), null, "빈 목록은 tree 를 세우지 않는다");
  assert.ok(!env.container.textContent.includes("항목·선택이 없습니다"), "항목 안내 문장은 어디에도 그려지지 않는다");
  env.root.unmount();
});

test("NG-01: fields without slots put no sentence in the 구조 view — the spine shows the field uses; with slots the tree stands", async () => {
  // hwpxTab 은 필드 1개(사용 위치 2곳)·항목 0개다.
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  const structure = env.container.querySelector("#authoring-outline-structure-panel");
  assert.equal(structure.querySelector(".authoring-outline-empty"), null, "필드가 있고 항목이 없으면 구조 탭의 안내 문장이 0개다");
  assert.ok(structure.querySelector('[role="tree"]'), "척추는 필드 사용 위치를 그린다");
  assert.equal(env.container.querySelector("#authoring-outline-fields-panel .authoring-outline-empty"), null, "필드가 있으면 필드 탭도 문장이 없다");
  assert.ok(!env.container.textContent.includes("항목·선택이 없습니다"));
  env.root.unmount();
});

test("head band 파일 menu (APG menu): the trigger toggles it, it opens on 문서 열기, ↓ roves, picking 새 TXT returns focus to 파일 and runs new; 문서 열기 runs the open picker", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" }, [], (action) => action === "new" ? { session_id: "a", revision: 0 } : {});
  const head = env.container.querySelector(".authoring-head");
  assert.ok(head.querySelector('.authoring-tabs[role="tablist"]'), "문서 탭 줄은 머리 띠 안에 선다");
  const file = head.querySelectorAll("button").find((node) => node.textContent === "파일");
  const menu = () => env.container.querySelector('[role="menu"]');
  const items = () => menu().querySelectorAll('[role="menuitem"]');
  const label = (node) => node.childNodes[0].textContent;
  assert.equal(file.getAttribute("aria-haspopup"), "menu");
  focusOn(env, file);
  fire(env, file, "click");
  await settle();
  assert.equal(menu().getAttribute("aria-label"), "파일");
  assert.equal(file.getAttribute("aria-expanded"), "true");
  assert.deepEqual(items().map(label), ["문서 열기", "새 TXT", "저장", "다른 이름으로 저장"]);
  assert.equal(env.document.activeElement, items()[0], "열리면 첫 사용 가능 항목에 초점");
  fire(env, file, "click");
  await settle();
  assert.equal(menu(), null, "여는 단추를 다시 누르면 닫힌다");
  fire(env, file, "click");
  await settle();
  press(env, "ArrowDown");
  assert.equal(label(env.document.activeElement), "새 TXT");
  fire(env, env.document.activeElement, "click");
  await settle();
  assert.equal(menu(), null, "고르면 닫힌다");
  assert.equal(env.document.activeElement, file, "초점은 연 단추로 돌아간다");
  assert.ok(env.calls.some((call) => call.action === "new" && call.media === "txt"), "새 TXT 는 controller.create 와 같은 실행 경로");
  fire(env, file, "click");
  await settle();
  fire(env, items().find((node) => label(node) === "문서 열기"), "click");
  await settle();
  assert.ok(env.calls.some((call) => call.invoke === "open_authoring_document"), "문서 열기는 controller.openFile 과 같은 실행 경로");
  env.root.unmount();
});

test("더보기 menu: its first item 명령 opens the command palette overlay (not a dock tab), and the palette does not offer itself", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  const more = env.container.querySelector('.authoring-toolbar [data-rove="more"]');
  focusOn(env, more);
  fire(env, more, "click");
  await settle();
  const menu = env.container.querySelector('[role="menu"][aria-label="더보기"]');
  const first = menu.querySelectorAll('[role="menuitem"]')[0];
  assert.equal(first.textContent, "명령Ctrl+Shift+P", "팔레트로 가는 유일한 마우스 길이 키를 가르친다");
  assert.equal(first.getAttribute("aria-keyshortcuts"), "Control+Shift+P");
  assert.equal(env.document.activeElement, first, "열리면 첫 항목(명령)에 초점");
  fire(env, first, "click");
  await settle();
  assert.equal(env.container.querySelector('[role="menu"]'), null);
  const palette = env.container.querySelector('[role="dialog"][aria-label="명령 팔레트"]');
  assert.ok(palette && !palette.closest("#authoring-dock-panel"), "명령 팔레트는 독이 아니라 오버레이다");
  assert.equal(env.document.activeElement, palette.querySelector('input[role="combobox"]'));
  assert.ok(!palette.querySelectorAll('[role="option"]').some((node) => node.textContent === "명령"), "팔레트는 자기를 여는 항목을 싣지 않는다");
  press(env, "Escape");
  await settle();
  assert.equal(env.container.querySelector('[role="dialog"][aria-label="명령 팔레트"]'), null);
  assert.equal(env.document.activeElement, more, "Escape 는 연 단추로 돌아간다");
});

/* ---------- IDE-01: 상태 막대 입구 · F2 제자리 사유 · 비교 안 결정(실제 커밋 위의 누름) ---------- */

test("IDE-01 P-12: the status bar's problem count opens the 문제 tab and moves into it; the trial state opens 결과 시험", async () => {
  const problem = { severity: "error", category: "structure", message: "끝 표지가 없습니다.", target: "s", location: null, actions: [] };
  const env = await boot({ ...hwpxTab(), problems: [problem], readiness: { state: "draft", errors: 1, warnings: 0, message: "사용 전에 구조 오류 1개를 확인하세요." },
    trial_state: "failed", trial_state_label: "시험 실패", trial_state_message: "시험 실패" });
  env.flushSync(() => env.controller.update({ dock: "", trial: false }));
  await settle();
  const links = () => env.container.querySelectorAll(".authoring-status .authoring-status-link");
  assert.deepEqual(links().map((node) => node.textContent), ["사용 전에 구조 오류 1개를 확인하세요.", "시험 실패"]);
  assert.ok(links().every((node) => node.tagName === "BUTTON" && node.getAttribute("type") === "button"));
  focusOn(env, links()[0]);
  fire(env, links()[0], "click");
  await settle();
  const panel = env.container.querySelector("#authoring-dock-panel");
  assert.equal(panel.getAttribute("aria-labelledby"), "authoring-dock-tab-problems");
  assert.ok(panel.contains(env.document.activeElement), "문제 탭의 첫 제어로 초점이 옮겨 간다");
  fire(env, links()[1], "click");
  await settle();
  assert.equal(env.container.querySelector("#authoring-dock-panel").getAttribute("aria-labelledby"), "authoring-dock-tab-trial");
  env.root.unmount();
});

test("IDE-01 P-15: F2 where no rename is possible leaves the properties panel shut and puts Python's reason on the location row", async () => {
  const commands = [{ type: "rename_field", enabled: false, reason: "필드를 고르세요.", alternative: null },
    { type: "rename_option", enabled: false, reason: "선택 영역을 고르세요.", alternative: null },
    { type: "rename_slot", enabled: false, reason: "항목이나 선택 영역을 고르세요.", alternative: null }];
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  env.flushSync(() => env.controller.update({ commands }));
  const toolbar = env.container.querySelector('.authoring-toolbar [data-rove][tabindex="0"]');
  focusOn(env, toolbar);
  press(env, "F2");
  await settle();
  assert.equal(env.container.querySelector(".authoring-properties"), null, "속성 패널을 열지 않는다");
  const note = env.container.querySelector(".authoring-selection .authoring-selection-note");
  assert.equal(note.textContent, "필드를 고르세요.");
  assert.equal(note.getAttribute("title"), "필드를 고르세요.");
  assert.equal(env.container.querySelector(".authoring-live").textContent, "필드를 고르세요.", "단일 live region 이 한 번 읽는다");
  assert.equal(env.document.activeElement, toolbar, "초점은 그대로다");
  env.root.unmount();
});

test("NG-11: a dimmed create button takes focus and a press, runs nothing and puts Python's reason on the location row; the dock stays; the next caret move clears it", async () => {
  const commands = [{ type: "create_field", enabled: false, reason: "고른 범위에 기존 필드가 포함되어 있습니다.", alternative: null },
    { type: "create_slot", enabled: true, reason: null, alternative: null },
    { type: "create_option", enabled: false, reason: "구조 오류를 먼저 수정한 뒤 영역 명령을 실행하세요.", alternative: null }];
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  env.flushSync(() => env.controller.update({ commands, panel: "problems", dock: "", trial: false }));
  await settle();
  const toolbar = env.container.querySelector('[role="toolbar"]');
  const create = (label) => [...toolbar.querySelectorAll("button")].find((node) => node.textContent === label);
  const dimmed = create("필드로 만들기");
  assert.equal(dimmed.getAttribute("aria-disabled"), "true", "흐린 단추는 aria-disabled 다");
  assert.ok(!dimmed.hasAttribute("disabled"), "disabled 속성이 없어 초점과 누름을 받는다");
  assert.equal(dimmed.getAttribute("title"), "고른 범위에 기존 필드가 포함되어 있습니다.", "hover 사유는 그대로다");
  assert.equal(create("항목으로 만들기").getAttribute("aria-disabled"), null, "켜진 단추는 표지가 없다");
  // 도구 막대 roving 이 흐린 단추에도 초점을 준다 — 앞 단추(모드 「이름표」)에서 → 한 번이면 그 단추다.
  focusOn(env, toolbar.querySelector('[data-rove="mode-structure"]'));
  press(env, "ArrowRight");
  assert.equal(env.document.activeElement, dimmed, "→ 가 흐린 「필드로 만들기」에 선다");
  fire(env, dimmed, "click");
  await settle();
  const view = env.controller.viewModel.getSnapshot();
  assert.equal(view.panel, "problems", "view.panel 은 그대로다 — 명령을 실행하지 않았다");
  assert.equal(view.commandType, undefined, "명령을 고르지 않았다");
  assert.equal(env.container.querySelector(".authoring-properties"), null, "속성 패널을 열지 않는다");
  assert.equal(env.container.querySelector("#authoring-dock-panel").getAttribute("aria-labelledby"), "authoring-dock-tab-problems", "펼친 독 탭이 남는다");
  const note = env.container.querySelector(".authoring-selection .authoring-selection-note");
  assert.equal(note.textContent, "고른 범위에 기존 필드가 포함되어 있습니다.", "Python 의 사유 문장 그대로다");
  assert.equal(env.container.querySelector(".authoring-live").textContent, "고른 범위에 기존 필드가 포함되어 있습니다.", "단일 live region 이 한 번 읽는다");
  assert.equal(env.document.activeElement, dimmed, "초점은 누른 단추에 남는다");
  // 다음 캐럿 이동에서 걷힌다(IDE-01 규칙).
  await env.controller.selection("a", { entry: "Contents/section0.xml", paragraph: 1, start: 0, end: 0 });
  await settle();
  assert.equal(env.container.querySelector(".authoring-selection-note"), null, "캐럿이 움직이면 메모가 걷힌다");
  // 켜진 단추는 지금처럼 속성 패널을 그 명령으로 연다.
  env.flushSync(() => env.controller.update({ commands }));
  fire(env, create("항목으로 만들기"), "click");
  await settle();
  assert.equal(env.controller.viewModel.getSnapshot().panel, "properties");
  assert.equal(env.controller.viewModel.getSnapshot().commandType, "create_slot");
  env.root.unmount();
});

test("NG-11: while verdicts are pending the create buttons stay disabled with no reason and out of the roving order", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  env.flushSync(() => env.controller.update({ commands: [] }));
  await settle();
  const toolbar = env.container.querySelector('[role="toolbar"]');
  for (const label of ["필드로 만들기", "항목으로 만들기", "선택으로 만들기"]) {
    const node = [...toolbar.querySelectorAll("button")].find((entry) => entry.textContent === label);
    assert.ok(node.hasAttribute("disabled"), `${label}: 판정 전에는 disabled`);
    assert.equal(node.getAttribute("title"), null, `${label}: 판정 전에는 사유가 없다`);
    fire(env, node, "click");
  }
  await settle();
  assert.equal(env.container.querySelector(".authoring-selection-note"), null, "판정 전 누름은 무동작이다");
  assert.equal(env.container.querySelector(".authoring-properties"), null);
  focusOn(env, toolbar.querySelector('[data-rove="mode-structure"]'));
  press(env, "ArrowRight");
  assert.equal(env.document.activeElement.getAttribute("data-rove"), "more", "판정 전 만들기 단추는 roving 이 건너뛴다");
  env.root.unmount();
});

test("NG-06: rows picked inside the dock (문제·검색·결과 시험) keep that dock tab and never open properties; an outline row still does", async () => {
  const place = { entry: "Contents/section0.xml", paragraph: 1, start: 0, end: 2 };
  const problem = { severity: "error", category: "structure", message: "끝 표지가 없습니다.", target: "s", location: place, actions: [{ kind: "navigate", label: "원문으로 이동" }] };
  const tab = { ...hwpxTab(), problems: [problem],
    trial_result: { ...hwpxTab().trial_result, occurrences: [{ name: "이름", value: "홍길동", source: { entry: "Contents/section0.xml", paragraph: 0, start: 0, end: 2 } }] } };
  const env = await boot(tab, [], (action) => action === "locate" ? { selected: null, matches: [{ kind: "field", name: "이름", location: place }], context: {} } : {});
  const dockPanel = () => env.container.querySelector("#authoring-dock-panel")?.getAttribute("aria-labelledby");
  // 문제 행
  env.flushSync(() => env.controller.update({ panel: "problems" }));
  await settle();
  fire(env, env.container.querySelector('.authoring-bottom[aria-label="문제"] .authoring-row'), "click");
  await settle();
  let view = env.controller.viewModel.getSnapshot();
  assert.equal(view.panel, "problems", "문제 행을 누른 뒤에도 독 활성 탭이 「문제」다");
  assert.equal(dockPanel(), "authoring-dock-tab-problems");
  assert.equal(env.container.querySelector(".authoring-properties"), null, "속성 패널을 열지 않는다");
  assert.deepEqual({ entry: view.selection.entry, paragraph: view.selection.paragraph }, { entry: place.entry, paragraph: place.paragraph }, "편집면 선택은 문제 위치로 옮겨 간다");
  assert.ok(env.container.querySelector(".authoring-selection .authoring-crumb[aria-current]"), "위치 줄(브레드크럼)은 새 자리를 가리킨다");
  // 검색 적중
  env.flushSync(() => env.controller.update({ panel: "search", hits: [{ kind: "text", context: "첫째", document: "a.hwpx", ...place }] }));
  await settle();
  fire(env, env.container.querySelector('.authoring-bottom[aria-label="검색"] .authoring-row'), "click");
  await settle();
  view = env.controller.viewModel.getSnapshot();
  assert.equal(view.panel, "search", "검색 적중을 누른 뒤에도 검색 탭이 남는다");
  assert.equal(dockPanel(), "authoring-dock-tab-search");
  assert.equal(env.container.querySelector(".authoring-properties"), null);
  // 결과 시험 추적 행
  env.flushSync(() => env.controller.update({ panel: "", trial: true, dock: "trial" }));
  await settle();
  fire(env, env.container.querySelector('.authoring-trial ul[aria-label="출력·제외 이유"] .authoring-row'), "click");
  await settle();
  view = env.controller.viewModel.getSnapshot();
  assert.equal(view.panel, "", "시험 추적 행은 속성 패널을 열지 않는다");
  assert.equal(dockPanel(), "authoring-dock-tab-trial", "결과 시험 탭이 남는다");
  assert.deepEqual({ entry: view.selection.entry, paragraph: view.selection.paragraph }, { entry: "Contents/section0.xml", paragraph: 0 });
  // 구조 목록 줄은 지금처럼 속성 패널을 연다.
  fire(env, inPanel(env, "structure", "treeitem", "필드 · 이름").querySelector(".authoring-tree-row"), "click");
  await settle();
  assert.equal(env.controller.viewModel.getSnapshot().panel, "properties", "구조 행 누름은 속성 패널을 연다");
  env.root.unmount();
});

test("IDE-01 P-21: after a failed save the comparison's own 다시 저장 runs the same save path", async () => {
  const env = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried", external_changed: true });
  env.flushSync(() => env.controller.update({ saveFailed: true, panel: "comparison", comparison: { content: "ZG9j", current_content: "ZG9j" } }));
  await settle();
  const section = env.container.querySelector('#authoring-dock-panel [aria-label="외부 파일 내용"]');
  const labels = section.querySelectorAll(".authoring-actions button").map((node) => node.textContent);
  assert.deepEqual(labels, ["비교 닫기", "현재 작업을 다른 이름으로 저장", "외부 파일 다시 열기", "다시 저장"]);
  const again = section.querySelectorAll(".authoring-actions button").find((node) => node.textContent === "다시 저장");
  assert.ok(String(again.getAttribute("class")).includes("primary"), "구획의 주 행동");
  fire(env, again, "click");
  await settle();
  assert.ok(env.calls.some((call) => call.action === "save" && call.session_id === "a"), "경보 구획과 같은 저장 경로");
  env.root.unmount();
});
