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
  querySelector() { return null; }
  querySelectorAll() { return []; }
  getBoundingClientRect() { return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
  focus() {}
  closest() { return null; }
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

async function boot(tab) {
  const document = installDom();
  const { createElement } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { flushSync } = await import("react-dom");
  const { createAuthoringController } = await import("../../frontend/src/screens/authoring_controller.ts");
  const screen = await import("../../frontend/src/screens/authoring.ts");
  let snapshot = { active_id: tab.id, tabs: [tab], recoverable: [] };
  const listeners = new Set();
  const client = {
    async dispatch(_screen, action, payload) {
      if (action === "content") return { ok: true, value: { session_id: payload.session_id, revision: 0, content: "ZG9j", section_entries: ["Contents/section0.xml"] } };
      return { ok: true, value: {} };
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
    return { content: async () => spec.content, flushChanges: async () => {}, applySnapshot: async () => {}, focus: async () => {},
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
  return { controller, mounts, push, snapshot: () => snapshot, container, root };
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

test("UX-05: field occurrences inside a closed outline <details> are built only after it opens", async () => {
  const { container, root } = await boot({ ...hwpxTab(), trial_result: null, trial_state: "untried" });
  const all = () => [...container.walk()];
  const occurrenceButtons = () => all().filter((node) => String(node.getAttribute?.("aria-label") || "").startsWith("이름 · 사용 위치"));
  const details = all().find((node) => node.nodeName === "DETAILS");
  assert.ok(details, "필드 줄은 접힌 details 다");
  assert.equal(occurrenceButtons().length, 0, "접힌 동안 사용 위치 줄을 짓지 않는다");
  details.open = true;
  const { flushSync } = await import("react-dom");
  flushSync(() => { for (const listener of details.listeners.get("toggle") || []) listener({ type: "toggle", target: details, currentTarget: details, timeStamp: 0 }); });
  await settle();
  assert.deepEqual(occurrenceButtons().map((node) => node.getAttribute("aria-label")), ["이름 · 사용 위치 1/2 · 첫째", "이름 · 사용 위치 2/2"]);
  details.open = false;
  flushSync(() => { for (const listener of details.listeners.get("toggle") || []) listener({ type: "toggle", target: details, currentTarget: details, timeStamp: 0 }); });
  await settle();
  assert.equal(occurrenceButtons().length, 0);
  root.unmount();
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
  root.unmount();
});

test("#1025 §7.2: an opened outline field shows Python's normalized occurrence context in the label and accessible name, never the raw field command", async () => {
  const tab = { ...hwpxTab(), trial_result: null, trial_state: "untried",
    analysis: { revision: 3, slots: [], fields: [{ name: "진행상태", count: 1, occurrences: [{ entry: "Contents/section0.xml", paragraph: 0, context: "[진행상태] - 누름틀",
      raw: { text: "9Clickhere:set:50:Direction:wstring:8:{{진행상태}} HelpState:wstring:0:  {{진행상태}}{{진행상태}} - 누름틀" } }] }] } };
  const { container, root } = await boot(tab);
  const all = () => [...container.walk()];
  const details = all().find((node) => node.nodeName === "DETAILS");
  details.open = true;
  const { flushSync } = await import("react-dom");
  flushSync(() => { for (const listener of details.listeners.get("toggle") || []) listener({ type: "toggle", target: details, currentTarget: details, timeStamp: 0 }); });
  await settle();
  const occurrence = all().find((node) => String(node.getAttribute?.("aria-label") || "").startsWith("진행상태 · 사용 위치"));
  assert.ok(occurrence, "펼친 필드 줄에 사용 위치 줄이 선다");
  assert.equal(occurrence.textContent, "1. [진행상태] - 누름틀");
  assert.equal(occurrence.getAttribute("aria-label"), "진행상태 · 사용 위치 1/1 · [진행상태] - 누름틀");
  assert.ok(!container.textContent.includes("Clickhere"), "원문 명령 표기는 구조 목록에 서지 않는다");
  assert.ok(!all().some((node) => String(node.getAttribute?.("aria-label") || "").includes("Clickhere")));
  root.unmount();
});
