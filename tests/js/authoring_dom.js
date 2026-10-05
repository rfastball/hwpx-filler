/* 저작 작업대의 실제 react-dom 커밋 하니스 — 작은 가짜 DOM 위에 AuthoringScreen 을 올리고(rhwp 마운트는 바꿔 끼운다)
   React 위임 차례대로 사건을 흘린다. `authoring_render.test.js` 와 `authoring_proposal_dom.test.js` 가 함께 쓴다. */

export const ELEMENT = 1, TEXT = 3, DOCUMENT = 9;

export class FakeNode {
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

export class FakeText extends FakeNode {
  constructor(text, ownerDocument) { super(TEXT, "#text", ownerDocument); this.nodeValue = text; }
  get textContent() { return this.nodeValue; }
  set textContent(text) { this.nodeValue = text; }
}

/* UX-04: 키보드 모델을 실제 커밋 위에서 재려고 작은 선택자 엔진을 둔다 — 태그·#id·.class·[attr]·[attr="v"]·:not(…)
   복합 선택자와 자손 결합자(공백), 쉼표 목록. 제품 코드가 쓰는 만큼만이다. focus() 는 activeElement 를 옮긴다. */
export function splitTop(text, separator) {
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
/** `:not(` 뒤의 괄호 짝이 닫히는 다음 자리. */
function notEnd(rest, start) {
  let depth = 1; let index = start;
  for (; index < rest.length && depth; index++) { if (rest[index] === "(") depth++; else if (rest[index] === ")") depth--; }
  return index;
}
export function matchesCompound(el, compound) {
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
      const index = notEnd(rest, m[0].length);
      if (el.matches(rest.slice(m[0].length, index - 1))) return false;
      rest = rest.slice(index); continue;
    } else throw new Error(`fake DOM: unsupported selector ${compound}`);
    rest = rest.slice(m[0].length);
  }
  return true;
}

export class FakeElement extends FakeNode {
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
  /* 입력칸 전체 선택(P-06) — 선택 범위만 옮긴다. */
  select() { this.selectionStart = 0; this.selectionEnd = String(this.value ?? "").length; }
  get offsetParent() { return this.ownerDocument.body; }
  *walk() { yield this; for (const child of this.childNodes) if (child instanceof FakeElement) yield* child.walk(); }
}

export class FakeOption extends FakeElement {
  get value() { return this.getAttribute("value") ?? this.textContent; }
}

export function installDom() {
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

export const settle = async () => { for (let turn = 0; turn < 8; turn++) await new Promise(setImmediate); };

export async function boot(tab, more = [], respond = () => ({})) {
  const document = installDom();
  const { createElement } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { flushSync } = await import("react-dom");
  const { createAuthoringController } = await import("../../frontend/src/screens/authoring_controller.ts");
  const screen = await import("../../frontend/src/screens/authoring.ts");
  let snapshot = { active_id: tab.id, tabs: [tab, ...more] };
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
    return { content: async () => spec.content, flushChanges: async () => {}, applySnapshot: async () => {}, focus: async (target) => { (record.focused ||= []).push(target); spec.host.focus(); },
      scrollTo: async (target) => { (record.scrolled ||= []).push(target); return true; },
      undo: async () => {}, redo: async () => {}, setReadOnly: async () => {}, setZoom: async (zoom) => { (record.zooms ||= []).push(zoom); },
      rangePick: async (state) => { (record.picks ||= []).push(state); },
      setDecorations: async (projection) => { record.decorations += 1; record.projection = projection; (record.highlights ||= []).push(projection.highlight); }, dispose: () => { record.disposed = true; } };
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

export const hwpxTab = () => ({ id: "a", name: "a.hwpx", media: "hwpx", path: "a.hwpx", revision: 0, values: {}, selected: {},
  rhwp_editable: true, compatibility: { state: "editable" }, problems: [], cases: [],
  analysis: { revision: 3, fields: [{ name: "이름", count: 2, occurrences: [{ entry: "Contents/section0.xml", paragraph: 0, context: "첫째" }, { entry: "Contents/section0.xml", paragraph: 1 }] }], slots: [] },
  trial_state: "current", trial_result: { revision: 7, content: "cmVzdWx0", section_entries: ["Contents/section0.xml"], occurrences: [], source_revision: 0 } });

/* ---------- UX-04 키보드 모델 — 실제 커밋 위에서 핸들러를 React 위임 차례(대상 → 조상)대로 부른다 ---------- */
export const propsOf = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))] || {};
/** 사건 하나를 대상에서 조상 쪽으로 흘린다. 멈추면 선다. 초점이 옮겨지면 새 초점 원소에서 onFocus 를 흘린다(React 의 focusin).
 *  `focusEvents: false` 는 창이 OS 초점을 쥐지 않은 때다 — 브라우저는 activeElement 만 옮기고 focus 사건은 창이 초점을 받을 때로 미룬다. */
export function fire(env, target, type, init = {}, { focusEvents = true } = {}) {
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
  if (focusEvents && type !== "focus" && after !== before && after?.parentNode) fire(env, after, "focus");
  return { prevented, stopped };
}
export const press = (env, key, init = {}) => fire(env, env.document.activeElement, "keydown", { key, ...init });
export const nodes = (env) => [...env.container.walk()];
export const byRole = (env, role) => nodes(env).filter((node) => node.getAttribute?.("role") === role);
export const named = (env, role, prefix) => byRole(env, role).find((node) => String(node.getAttribute("aria-label") ?? node.textContent).startsWith(prefix));
export const focusOn = (env, node) => { node.focus(); fire(env, node, "focus"); };
/** 구조 패널의 「필드」 보기를 연다(UX-09) — 필드 목록은 그 탭 안의 tree 다. */
export const showFields = (env) => fire(env, env.container.querySelector("#authoring-outline-fields"), "click");
export const inPanel = (env, panel, role, prefix) => byRole(env, role).find((node) => node.closest(`#authoring-outline-${panel}-panel`)
  && String(node.getAttribute("aria-label") ?? node.textContent).startsWith(prefix));
export const fieldRow = (env, prefix) => inPanel(env, "fields", "treeitem", prefix);
