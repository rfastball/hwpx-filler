import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createAuthoringController } from "../../frontend/src/screens/authoring_controller.ts";
import { AuthoringScreen, shellShortcut, appliedProperties, escapeStage, submitProperties, externalDocumentSpec } from "../../frontend/src/screens/authoring.ts";

// New owner: asynchronous authoring revision fences and close preservation.
// Headless Node only; Python tests own semantic edits and durable storage.
function harness(handler = () => ({})) {
  const snapshot = { active_id: "a", tabs: [
    { id: "a", name: "a.txt", path: "a.txt", revision: 0, values: {}, selected: {} },
    { id: "b", name: "b.txt", path: "b.txt", revision: 0, values: {}, selected: {} },
  ] };
  const calls = [];
  const client = {
    async dispatch(_screen, action, payload) {
      calls.push({ action, ...payload });
      if (action === "activate") snapshot.active_id = payload.session_id;
      const value = await handler(action, payload, snapshot);
      return { ok: true, value };
    },
    async invoke(method, ...args) { calls.push({ method, args }); return { ok: true, value: null }; },
  };
  const controller = createAuthoringController({ client,
    runtime: { model: () => ({ getSnapshot: () => snapshot, subscribe: () => () => {} }), loadInitial: async () => {} },
    modal: { choose: async () => "save", prompt: async () => null, confirm: async () => true },
    navigation: { go() {}, refresh: async () => {} },
  });
  return { controller, calls, snapshot };
}

test("typing during an in-flight update drains the newest content with the returned revision", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let updates = 0;
  const { controller, calls } = harness(async (action, payload) => {
    if (action !== "update") return {};
    if (++updates === 1) await gate;
    return { revision: payload.revision + 1 };
  });
  controller.changed("a", "first");
  controller.changed("a", "last");
  release();
  await controller.flush("a");
  assert.deepEqual(calls.filter((call) => call.action === "update").map(({ revision, content }) => [revision, content]), [[0, "first"], [1, "last"]]);
});

test("a stale semantic preview never mutates the editor", async () => {
  let revision = 0;
  let applications = 0;
  const { controller } = harness((action, payload) => {
    if (action === "update") return { revision: ++revision };
    if (action === "preview") {
      if (payload.revision !== revision) throw new Error("stale revision");
      return { content: "{{name}}", edits: [] };
    }
    return {};
  });
  await controller.activate("a");
  controller.attach("a", { apply: async () => { applications++; }, content: async () => "", decorate() {} });
  await controller.preview({ type: "create_field", name: "name" });
  // Another actor changes the backend revision after this exact preview.
  revision++;
  await assert.rejects(controller.applyPreview(), /stale revision/);
  assert.equal(applications, 0);
});

test("canceling the name of unsaved trial inputs keeps the document open", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { controller, calls } = harness(async (action) => {
    if (action === "trial_input") await gate;
    if (action === "close") return { needs_confirm: true, cases_dirty: true, dirty: false };
    if (action === "save_cases") return { needs_case_name: true };
    return {};
  });
  const input = controller.trialInput({ name: "pending" }, {});
  const closing = controller.close("a");
  await Promise.resolve();
  assert.equal(calls.some((call) => call.action === "close"), false);
  release();
  await input;
  assert.equal(await closing, false);
  assert.equal(calls.some((call) => call.action === "close" && call.force), false);
});

test("tabs retain their display mode and selection without editing documents", async () => {
  const { controller, calls } = harness();
  await controller.activate("a");
  controller.setMode("structure");
  controller.selection("a", { start: 4, end: 9 });
  await controller.activate("b");
  assert.equal(controller.viewModel.getSnapshot().mode, "template");
  await controller.activate("a");
  assert.equal(controller.viewModel.getSnapshot().mode, "structure");
  assert.deepEqual(controller.viewModel.getSnapshot().selection, { start: 4, end: 9 });
  assert.equal(calls.some((call) => call.action === "update"), false);
});

test("late semantic location results cannot replace the newer canvas selection", async () => {
  let first;
  const gate = new Promise((resolve) => { first = resolve; });
  const { controller } = harness(async (action, payload) => {
    if (action !== "locate") return {};
    if (payload.selection.start === 1) await gate;
    return { matches: [{ kind: "field", name: String(payload.selection.start), location: payload.selection }], context: {} };
  });
  await controller.activate("a");
  controller.selection("a", { start: 1, end: 2 });
  await new Promise(setImmediate);
  controller.selection("a", { start: 3, end: 4 });
  await new Promise(setImmediate);
  first();
  await new Promise(setImmediate);
  assert.equal(controller.viewModel.getSnapshot().selected.name, "3");
  controller.update({ commandType: "move" });
  controller.selection("a", { start: 5, end: 5 });
  await new Promise(setImmediate);
  assert.equal(controller.viewModel.getSnapshot().selected.name, "3");
  assert.equal(controller.viewModel.getSnapshot().selection.start, 5);
});

test("save drains the native editor export before sending the fenced save", async () => {
  const { controller, calls } = harness((action) => action === "update" ? { revision: 1 } : {});
  controller.attach("a", {
    flush: async () => controller.changed("a", "latest native export"),
  });
  await controller.save("a");
  assert.deepEqual(calls.filter((call) => ["update", "save"].includes(call.action)).map(({ action, revision }) => [action, revision]), [["update", 0], ["save", 1]]);
});

test("a preview returned after a tab switch cannot populate the other document", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { controller } = harness(async (action) => {
    if (action === "preview") { await gate; return { content: "{{name}}" }; }
    return {};
  });
  await controller.activate("a");
  const pending = controller.preview({ type: "create_field", name: "name" });
  await new Promise(setImmediate);
  await controller.activate("b");
  release();
  await pending;
  assert.equal(controller.viewModel.getSnapshot().preview, null);
});


test("stale search and trial coordinates are rejected before moving the caret", async () => {
  let focused = 0;
  const { controller } = harness((action, payload) => {
    if (action === "locate" && payload.revision === 0) throw new Error("stale source");
    return {};
  });
  await controller.activate("a");
  controller.attach("a", { focus: async () => { focused++; } });
  await assert.rejects(controller.select({ start: 1, end: 2, source_revision: 0 }), /stale source/);
  assert.equal(focused, 0);
});

// ---- 작업대 표면(authoring.ts) — 렌더는 react-dom/server 로, 키 판독·Escape 단계는 순수 함수로 잰다. ----
const render = (controller) => renderToStaticMarkup(createElement(AuthoringScreen, { controller }));
const inside = (selectors) => ({ closest: (selector) => selector.split(",").some((part) => selectors.includes(part.trim())) ? {} : null });

test("AC24: a save conflict opens the recovery panel with the three verbs plus 다시 저장, and the footer says 저장 실패", async () => {
  let conflict = true;
  const { controller } = harness((action) => action === "save" ? (conflict ? { conflict: true } : {}) : {});
  await controller.activate("a");
  assert.equal(await controller.save("a"), false);
  const view = controller.viewModel.getSnapshot();
  assert.equal(view.panel, "external");
  assert.equal(view.saveFailed, true);
  const markup = render(controller);
  assert.match(markup, /<section class="authoring-bottom" role="alert" aria-label="저장 실패">/);
  for (const verb of ["양쪽 내용 확인", "현재 작업을 다른 이름으로 저장", "외부 파일 다시 열기", "다시 저장"]) assert.ok(markup.includes(`>${verb}</button>`), verb);
  assert.ok(markup.includes("<footer") && markup.includes("<span>저장 실패</span>"));
  conflict = false;
  assert.equal(await controller.save("a"), true);
  assert.equal(controller.viewModel.getSnapshot().saveFailed, false);
  assert.equal(controller.viewModel.getSnapshot().panel, "");
  assert.ok(!render(controller).includes("<span>저장 실패</span>"));
});

test("F34: Ctrl+Z/Ctrl+Y route to the document undo only outside the editor host and text inputs", () => {
  const outline = inside([".authoring-outline"]);
  assert.equal(shellShortcut({ key: "z", ctrlKey: true, target: outline }), "undo");
  assert.equal(shellShortcut({ key: "z", ctrlKey: true, shiftKey: true, target: outline }), "redo");
  assert.equal(shellShortcut({ key: "y", ctrlKey: true, target: outline }), "redo");
  assert.equal(shellShortcut({ key: "Z", metaKey: true, target: outline }), "undo");
  // 편집면(CodeMirror·rhwp iframe)과 시험 입력창은 자기 실행 취소를 가진다(§9.3).
  for (const target of [inside([".authoring-editor-host"]), inside([".cm-editor"]), inside(["iframe"]), inside(["input"]), inside(["textarea"]), inside(["select"])]) {
    assert.equal(shellShortcut({ key: "z", ctrlKey: true, target }), "");
    assert.equal(shellShortcut({ key: "y", ctrlKey: true, target }), "");
  }
  assert.equal(shellShortcut({ key: "z", target: outline }), "", "modifier 없는 z 는 셸 단축키가 아니다");
  // Ctrl+F: TXT 편집면 안이면 CodeMirror 검색, 밖이면 작업대 검색 패널.
  assert.equal(shellShortcut({ key: "f", ctrlKey: true, target: inside([".authoring-editor-host"]) }), "editor-search");
  assert.equal(shellShortcut({ key: "f", ctrlKey: true, target: inside(["input"]) }), "search");
  assert.equal(shellShortcut({ key: "Escape", target: inside(["input"]) }), "escape");
});

test("F34: the undo button names the applied command and follows the TXT history depth", async () => {
  let revision = 0;
  const { controller } = harness((action) => action === "update" ? { revision: ++revision } : action === "preview" ? { content: "{{name}}", edits: [] } : {});
  await controller.activate("a");
  let depth = { canUndo: false, canRedo: false };
  const commands = [];
  controller.attach("a", { apply: async () => { depth = { canUndo: true, canRedo: false }; }, content: async () => "{{name}}", decorate() {}, state: () => depth,
    command: async (command) => { commands.push(command); depth = { canUndo: false, canRedo: true }; } });
  assert.match(render(controller), /<button type="button" class="btn sm" disabled="">문서 실행 취소<\/button>/);
  await controller.preview({ type: "create_field", name: "name" });
  await controller.applyPreview();
  assert.equal(controller.viewModel.getSnapshot().lastCommandLabel, "필드로 만들기");
  const armed = render(controller);
  assert.ok(armed.includes(">문서 실행 취소: 필드로 만들기</button>"));
  assert.match(armed, /<button type="button" class="btn sm" disabled="">문서 다시 실행<\/button>/);
  await controller.command("undo");
  assert.deepEqual(commands, ["undo"]);
  assert.equal(controller.viewModel.getSnapshot().lastCommandLabel, "");
  const undone = render(controller);
  assert.match(undone, /<button type="button" class="btn sm" disabled="">문서 실행 취소<\/button>/);
  assert.ok(undone.includes('class="btn sm">문서 다시 실행</button>'));
});

test("F14: Escape in a properties input reverts the draft first and closes only when nothing is pending", () => {
  const selected = { kind: "option", label: "견적서", option_id: "quote", slot_id: "doc", raw: { value: "견적서" } };
  const applied = appliedProperties(selected);
  assert.deepEqual(applied, { name: "견적서", identifier: "quote", parent: "doc", text: "견적서" });
  assert.equal(escapeStage(selected, { ...applied, name: "견적" }), "revert");
  assert.equal(escapeStage(selected, { ...applied, identifier: "quote2" }), "revert");
  assert.equal(escapeStage(selected, applied), "close");
  assert.equal(escapeStage(null, appliedProperties(null)), "close");
});

test("§6.2: submitting properties during IME composition sends nothing", async () => {
  const { controller, calls } = harness();
  await controller.activate("a");
  assert.equal(submitProperties(controller, true, () => ({ type: "create_field", name: "이름" })), false);
  await new Promise(setImmediate);
  assert.equal(calls.some((call) => call.action === "preview"), false);
  assert.equal(submitProperties(controller, false, () => ({ type: "create_field", name: "이름" })), true);
  await new Promise(setImmediate);
  assert.equal(calls.filter((call) => call.action === "preview").length, 1);
});

test("U09: the stale label keys off the trial-specific in-flight flag, not the generic busy flag", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { controller } = harness(async (action) => { if (action === "trial") await gate; return {}; });
  await controller.activate("a");
  const running = controller.runTrial("a");
  await new Promise(setImmediate);
  assert.equal(controller.viewModel.getSnapshot().trialBusy, true);
  assert.equal(controller.viewModel.getSnapshot().busy, false);
  assert.ok(render(controller).includes('<p role="status">갱신 중 · 이전 결과</p>'));
  release();
  await running;
  assert.equal(controller.viewModel.getSnapshot().trialBusy, false);
  const settled = render(controller);
  assert.ok(!settled.includes("갱신 중 · 이전 결과"));
  assert.ok(settled.includes("시험 자료는 템플릿 파일에 포함되지 않습니다."));
});

test("§6.3: the search target offers 전체 alongside the three kinds, and kind=all reaches Python unchanged", async () => {
  const { controller, calls } = harness((action) => action === "search" ? { hits: [] } : {});
  await controller.activate("a");
  controller.update({ panel: "search" });
  const markup = render(controller);
  for (const option of ['<option value="body">본문</option>', '<option value="field">필드</option>', '<option value="structure">항목·선택</option>', '<option value="all">전체</option>']) assert.ok(markup.includes(option), option);
  await controller.search("공고", "all");
  assert.equal(calls.find((call) => call.action === "search").kind, "all");
});

test("HWPX comparison views forward Python's section entries into the read-only mount", async () => {
  assert.deepEqual(externalDocumentSpec({ name: "원본" }, "AAA=", ["Contents/section0.xml"]),
    { content: "AAA=", fileName: "원본", readOnly: true, sectionEntries: ["Contents/section0.xml"] });
  const { controller, snapshot } = harness((action) => action === "external_content" ? { content: "ext", section_entries: ["Contents/section1.xml"] }
    : action === "content" ? { content: "cur", section_entries: ["Contents/section0.xml"] } : {});
  snapshot.tabs[0].media = "hwpx";
  await controller.activate("a");
  controller.attach("a", { content: async () => "cur" });
  await controller.compareExternal();
  const { comparison, panel } = controller.viewModel.getSnapshot();
  assert.equal(panel, "comparison");
  assert.deepEqual([comparison.section_entries, comparison.current_section_entries, comparison.current_content], [["Contents/section1.xml"], ["Contents/section0.xml"], "cur"]);
  assert.ok(render(controller).includes(">비교 닫기</button>"), "비교 패널은 키보드로 닿을 버튼을 가진다");
});
