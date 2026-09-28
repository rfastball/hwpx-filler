import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createAuthoringController, coordinates } from "../../frontend/src/screens/authoring_controller.ts";
import { AuthoringScreen, shellShortcut, forwardedShellKey, appliedProperties, escapeStage, submitProperties, externalDocumentSpec, openContextMenu, escapeShell, problemAction, compatibilityReporter, outlineLabel, dockTabs, sharedReason, commandAvailability, focusRequest, saveLabel, liveState, outlineSpine, outlineCurrent, outlineKey, crumbs, menuReasonGroups, sameFieldMeta, highlightRanges, problemSeverities, fieldsInFirstUse, filterMatch, dockBadge, renameChoice, renameShortcut } from "../../frontend/src/screens/authoring.ts";
import { rovingIndex, treeKey, clampMenu, errorParts, errorText, isCurrentTarget, liveStep } from "../../frontend/src/screens/authoring_a11y.ts";
import { TPL_STATUS_COPY } from "../../frontend/src/screens/job_run.ts";

// New owner: asynchronous authoring revision fences and close preservation.
// Headless Node only; Python tests own semantic edits and durable storage.
function harness(handler = () => ({}), modal = {}, invoked = () => null) {
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
    async invoke(method, ...args) { calls.push({ method, args }); return { ok: true, value: await invoked(method, args, snapshot) }; },
  };
  const controller = createAuthoringController({ client,
    runtime: { model: () => ({ getSnapshot: () => snapshot, subscribe: () => () => {} }), loadInitial: async () => {} },
    modal: { choose: async () => "save", prompt: async () => null, confirm: async () => true, ...modal },
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

test("#1021: an outline target is located by identity and survives the editor echo its own focus causes", async () => {
  const TARGET_COMMANDS = [{ type: "rename_field", enabled: true, reason: null, alternative: null },
    { type: "relink_field", enabled: false, reason: "필드 사용 위치를 하나 선택하세요.", alternative: null }];
  const occurrence = { entry: "Contents/section0.xml", paragraph: 0, occurrence: 0, pairing_id: "7" };
  const field = { kind: "field", name: "진행상태", count: 1, occurrences: [occurrence] };
  const caret = [];
  const { controller, calls } = harness((action, payload) => {
    if (action !== "locate") return {};
    if (payload.target) return { selected: { ...field }, matches: [], context: { slot_id: null }, commands: TARGET_COMMANDS };
    caret.push(payload.selection);
    // 좌표 locate 는 문단 단위 근사 후보만 안다 — 되울림이 이 결과로 명시 선택을 덮으면 대상이 사라진다.
    return { matches: [{ kind: "field", name: "진행상태", location: occurrence, approximate: true }], context: {}, commands: [] };
  });
  await controller.activate("a");
  const echo = { entry: "Contents/section0.xml", paragraph: 0, start_paragraph: 0, end_paragraph: 0, start: 0, end: 6 };
  let focused = 0;
  controller.attach("a", { decorate() {}, focus: async (place) => {
    focused++;
    controller.selection("a", { ...echo, end: 0 });   // 초점 이동 중의 중간 보고(TXT 는 동기로 온다)
    // rhwp 는 초점이 끝난 뒤 300ms 주기로 보고한다 — 초점 해소 뒤에 되울림을 보낸다.
    setTimeout(() => controller.selection("a", echo), 0);
    assert.equal(place.start, undefined, "좌표 없는 사용 위치는 편집기가 문단으로 옮긴다");
  } });
  controller.update({ matches: [{ kind: "field", name: "진행상태", location: occurrence, approximate: true }] });
  await controller.select({ source_revision: 0, ...field });
  await new Promise((resolve) => setTimeout(resolve, 5));
  const asked = calls.find((call) => call.action === "locate");
  assert.deepEqual(asked.target, { kind: "field", name: "진행상태" }, "필드 전체는 좌표가 아니라 대상으로 묻는다");
  let view = controller.viewModel.getSnapshot();
  assert.equal(focused, 1);
  assert.deepEqual(caret, [], "되울림은 좌표 locate 를 다시 부르지 않는다");
  assert.equal(view.selected.name, "진행상태");
  assert.ok(Array.isArray(view.selected.occurrences), "필드 전체 선택이 남는다");
  assert.deepEqual(view.commands, TARGET_COMMANDS);
  assert.equal(view.commandType, "rename_field");
  assert.equal(view.selection.end, 6, "편집기 좌표는 위치 기억용으로 받아 둔다");
  assert.deepEqual(view.matches, [], "일치 후보 줄은 이 선택에 대해 Python 이 준 것이다 — 앞선 캐럿의 문단 내 후보가 남지 않는다");
  // 사용자가 다른 자리로 캐럿을 옮기면 그 판정이 이긴다.
  controller.selection("a", { ...echo, paragraph: 2, start_paragraph: 2, end_paragraph: 2, start: 1, end: 1 });
  await new Promise(setImmediate);
  view = controller.viewModel.getSnapshot();
  assert.equal(caret.length, 1);
  assert.equal(view.selected, null);
  assert.deepEqual(view.commands, []);
  // 사용 위치 한 곳은 occurrence 로, 항목·선택은 식별자로 묻는다.
  await controller.select({ source_revision: 0, ...occurrence, name: "진행상태", kind: "field" });
  await controller.select({ source_revision: 0, kind: "option", slot_id: "s", option_id: "o", entry: "Contents/section0.xml", start_paragraph: 1, end_paragraph: 1 });
  assert.deepEqual(calls.filter((call) => call.action === "locate" && call.target).map((call) => call.target), [
    { kind: "field", name: "진행상태" }, { kind: "occurrence", name: "진행상태" }, { kind: "option", slot_id: "s", option_id: "o" }]);
});

test("#1021: a caret locate that left before an explicit selection cannot replace it", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { controller } = harness(async (action, payload) => {
    if (action !== "locate") return {};
    if (payload.target || payload.selection.start !== 1) return { selected: { kind: "slot", slot_id: "s", label: "항목" }, context: { slot_id: "s" }, commands: [] };
    await gate;
    return { matches: [{ kind: "field", name: "캐럿", location: payload.selection }], context: {}, commands: [] };
  });
  await controller.activate("a");
  controller.selection("a", { start: 1, end: 1 });
  await new Promise(setImmediate);
  await controller.select({ source_revision: 0, kind: "slot", slot_id: "s", start: 10, end: 20 });
  release();
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(controller.viewModel.getSnapshot().selected.slot_id, "s");
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


test("choosing another target retires the shown preview and any preview still in flight", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { controller } = harness(async (action, payload) => {
    if (action === "preview" && payload.command.name === "late") { await gate; return { affected: 1, original: "입찰개요" }; }
    if (action === "preview") return { affected: 1, original: "입찰개요" };
    if (action === "locate") return { context: {}, commands: [] };
    return {};
  });
  await controller.activate("a");
  await controller.preview({ type: "create_field", name: "shown" });
  assert.equal(controller.viewModel.getSnapshot().preview.original, "입찰개요");
  const pending = controller.preview({ type: "create_field", name: "late" });
  await new Promise(setImmediate);
  await controller.select({ kind: "field", name: "수요기관", occurrences: [{ entry: "e", paragraph: 1 }], source_revision: 0 });
  release();
  await pending;
  const view = controller.viewModel.getSnapshot();
  assert.equal(view.preview, null);
  assert.equal(view.command, null);
  assert.equal(view.selected.name, "수요기관");
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
  assert.match(render(controller), /<button type="button" class="btn icon" aria-label="문서 실행 취소" title="문서 실행 취소" disabled="" data-rove="undo" tabindex="-1">/);
  await controller.preview({ type: "create_field", name: "name" });
  await controller.applyPreview();
  assert.equal(controller.viewModel.getSnapshot().lastCommandLabel, "필드로 만들기");
  const armed = render(controller);
  assert.ok(armed.includes('aria-label="문서 실행 취소: 필드로 만들기" title="문서 실행 취소: 필드로 만들기"'));
  assert.match(armed, /<button type="button" class="btn icon" aria-label="문서 다시 실행" title="문서 다시 실행" disabled="" data-rove="redo" tabindex="-1">/);
  await controller.command("undo");
  assert.deepEqual(commands, ["undo"]);
  assert.equal(controller.viewModel.getSnapshot().lastCommandLabel, "");
  const undone = render(controller);
  assert.match(undone, /<button type="button" class="btn icon" aria-label="문서 실행 취소" title="문서 실행 취소" disabled="" data-rove="undo" tabindex="-1">/);
  // 도구 막대의 roving 대기 항목은 첫 **활성** 제어다 — 실행 취소가 꺼지면 다시 실행이 Tab 의 입구가 된다.
  assert.ok(undone.includes('aria-label="문서 다시 실행" title="문서 다시 실행" data-rove="redo" tabindex="0">'));
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
  // 보이는 줄로만 선다 — 화면 읽기는 셸의 단일 live region 이 전이 때만 한다(UX-04).
  assert.ok(render(controller).includes('<p>갱신 중 · 이전 결과</p>'));
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

// ---- Python 의 판정을 그리는 표면(F40·P07·§6.1·U07·AC10·F24·P09·F38·F26). 프런트는 뜻을 다시 판정하지 않는다. ----
const COMMAND_VERDICTS = [
  { type: "create_field", enabled: true, reason: null, alternative: null },
  { type: "create_option", enabled: false, reason: "먼저 항목 안의 내용을 선택하세요.", alternative: { label: "먼저 항목 만들기", command_type: "create_slot" } },
  { type: "relink_field", enabled: false, reason: "전체 이름 변경과 다릅니다.", alternative: null },
];

test("F40: locate 가 실어 온 commands 가 도구 막대·팔레트·속성 select 의 비활성·사유·대안을 결정한다", async () => {
  const { controller, calls } = harness((action) => action === "locate" ? { matches: [], context: {}, commands: COMMAND_VERDICTS } : {});
  await controller.activate("a");
  controller.selection("a", { start: 1, end: 2 });
  await new Promise(setImmediate);
  assert.deepEqual(controller.viewModel.getSnapshot().commands, COMMAND_VERDICTS);
  assert.equal(calls.some((call) => call.action === "commands"), false, "locate 가 판정을 실어 오면 독립 액션을 다시 묻지 않는다");
  controller.update({ panel: "commands" });
  const palette = render(controller);
  assert.match(palette, /<button type="button" class="authoring-menu-item" disabled="" aria-disabled="true" title="먼저 항목 안의 내용을 선택하세요\.">선택으로 만들기<\/button><p class="authoring-reason">먼저 항목 안의 내용을 선택하세요\.<\/p><button type="button" class="authoring-menu-item alternative">먼저 항목 만들기<\/button>/);
  assert.ok(palette.includes('title="먼저 항목 안의 내용을 선택하세요."'), "도구 막대 버튼도 같은 사유를 단다");
  assert.ok(palette.includes('class="authoring-menu-item">필드로 만들기</button>'), "판정이 사용 가능이면 그대로 켜 둔다");
  controller.update({ panel: "properties", commandType: "create_option" });
  const properties = render(controller);
  assert.match(properties, /<option value="create_option" disabled="" title="먼저 항목 안의 내용을 선택하세요\."( selected="")?>선택으로 만들기<\/option>/);
  assert.ok(properties.includes('<p class="authoring-reason" id="authoring-properties-reason">먼저 항목 안의 내용을 선택하세요.</p>'), "사유는 보이는 줄이고 live region 이 아니다");
  assert.ok(properties.includes('aria-describedby="authoring-properties-reason"'), "명령 select 가 사유를 설명으로 가리킨다");
  assert.ok(properties.includes(">먼저 항목 만들기</button>"));
  assert.match(properties, /<button class="btn" type="submit" disabled="" aria-disabled="true" title="[^"]+">변경 미리보기<\/button>/);
});

test("F40: locate 가 commands 를 싣지 않으면 독립 액션 commands 로 같은 fence 안에서 묻는다", async () => {
  const { controller, calls } = harness((action) => action === "locate" ? { matches: [], context: { slot_id: "doc" } } : action === "commands" ? { commands: COMMAND_VERDICTS.slice(0, 1) } : {});
  await controller.activate("a");
  controller.selection("a", { start: 1, end: 2 });
  await new Promise(setImmediate);
  const asked = calls.find((call) => call.action === "commands");
  assert.deepEqual([asked.session_id, asked.revision, asked.selection, asked.context], ["a", 0, { start: 1, end: 2 }, { slot_id: "doc" }]);
  assert.deepEqual(controller.viewModel.getSnapshot().commands, COMMAND_VERDICTS.slice(0, 1));
});

test("§6.1: the context menu is a role=menu popover at the event coordinates, and Escape closes it first and returns focus", async () => {
  const { controller } = harness();
  await controller.activate("a");
  controller.update({ commands: COMMAND_VERDICTS, panel: "search" });
  let focused = 0;
  openContextMenu(controller, { clientX: 112, clientY: 234, target: { focus: () => { focused++; } }, preventDefault() {} }, { getBoundingClientRect: () => ({ left: 100, top: 200 }) });
  const markup = render(controller);
  assert.ok(markup.includes('<div class="authoring-context-menu" style="left:12px;top:34px"><div class="authoring-menu" id="authoring-menu" role="menu" aria-label="문맥 명령">'));
  assert.ok(markup.includes('<button type="button" class="authoring-menu-item" role="menuitem" tabindex="-1" aria-label="필드로 만들기">필드로 만들기</button>'));
  // APG menu: 불가 항목도 초점을 받는다(aria-disabled) — 사유는 항목 안의 윗줄 설명이고(UX-10 R5), 대안은 곁의 menuitem 이다.
  assert.ok(markup.includes('role="menuitem" tabindex="-1" aria-label="선택으로 만들기" aria-disabled="true" aria-describedby="authoring-menu-reason-create_option"><span id="authoring-menu-reason-create_option" class="authoring-reason group-reason">먼저 항목 안의 내용을 선택하세요.</span>선택으로 만들기</button><button type="button" class="authoring-menu-item alternative" role="menuitem" tabindex="-1">먼저 항목 만들기</button>'));
  const menu = markup.slice(markup.indexOf('<div class="authoring-menu"'));
  assert.ok(!/<button[^>]* disabled=""/.test(menu.slice(0, menu.indexOf("</div>"))), "메뉴 항목은 native disabled 가 아니다");
  assert.ok(!menu.slice(0, menu.indexOf("</div>")).includes("<p"), "메뉴의 자식은 menuitem 뿐이다");
  assert.equal(escapeShell(controller), "menu");
  assert.equal(controller.viewModel.getSnapshot().contextMenu, null);
  assert.equal(focused, 1);
  assert.equal(controller.viewModel.getSnapshot().panel, "search", "메뉴를 닫는 Escape 는 패널을 건드리지 않는다");
  assert.equal(escapeShell(controller), "panel");
  assert.equal(controller.viewModel.getSnapshot().panel, "");
  assert.equal(shellShortcut({ key: "F10", shiftKey: true, target: inside([".authoring-outline"]) }), "context-menu");
  assert.equal(shellShortcut({ key: "ContextMenu", target: inside([".authoring-canvas"]) }), "context-menu");
});

test("U07/AC08: a name_conflict refusal shows Python's sentence with 취소·다른 이름 입력, and 기존 필드에 연결 only for a single occurrence", async () => {
  const refusal = { code: "name_conflict", name: "사업명", existing_count: 2, message: "‘사업명’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요." };
  const { controller } = harness((action) => action === "preview" ? { ok: false, refusal } : {});
  await controller.activate("a");
  controller.update({ panel: "properties", commandType: "rename_field", selected: { kind: "field", name: "공고명", start: 0, end: 3 } });
  await controller.preview({ type: "rename_field", name: "사업명", old_name: "공고명" });
  const view = controller.viewModel.getSnapshot();
  assert.equal(view.preview, null);
  assert.deepEqual(view.refusal, refusal);
  const single = render(controller);
  assert.ok(single.includes('<section class="authoring-preview authoring-refusal" role="alert" aria-label="변경 불가"><p>‘사업명’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요.</p>'));
  for (const verb of ["다른 이름 입력", "기존 필드에 연결", "취소"]) assert.ok(single.includes(`>${verb}</button>`), verb);
  controller.update({ selected: { kind: "field", name: "공고명", occurrences: [{ start: 0, end: 3 }, { start: 9, end: 12 }] } });
  const whole = render(controller);
  assert.ok(whole.includes(">다른 이름 입력</button>"));
  assert.ok(!whole.includes(">기존 필드에 연결</button>"), "필드 전체 선택에서는 개별 연결 경로를 내지 않는다");
});

test("U08/AC10: a cascade_required refusal lists the children by kind·label·count and offers 하위 의미 함께 해제", async () => {
  const refusal = { code: "cascade_required", children: [{ kind: "option", id: "quote", label: "견적서", count: 2 }, { kind: "field", id: "amount", label: "금액", count: 1 }], message: "이 항목을 해제하면 선택 2개도 확인이 필요합니다." };
  const { controller } = harness((action) => action === "preview" ? { ok: false, refusal } : {});
  await controller.activate("a");
  controller.update({ panel: "properties", commandType: "unwrap", selected: { kind: "slot", id: "doc", label: "문서" } });
  await controller.preview({ type: "unwrap", id: "doc" });
  const markup = render(controller);
  assert.ok(markup.includes('<ul aria-label="함께 해제될 하위 의미"><li>선택 · 견적서 · 2</li><li>필드 · 금액 · 1</li></ul>'));
  assert.ok(markup.includes('<button type="button" class="btn primary">하위 의미 함께 해제</button>'));
  assert.ok(markup.includes(">취소</button>"));
});

test("U04/U07: preview detail renders counts·included·children·candidates·links_existing and the rename sentence", async () => {
  const { controller, snapshot } = harness((action, payload) => action === "preview" ? (payload.command.type === "rename_field"
    ? { affected: 4, before: "공고명", after: "사업명", message: "현재 문서의 사용 위치 4곳이 ‘사업명’으로 변경됩니다." }
    : { affected: 1, before: "특약", after: "[특약]", counts: { paragraphs: 3, fields: 2, options: 1, tables: 0 }, included: ["특약 사항", "세부 조건"], children: [{ kind: "option", id: "a", label: "갑", count: 1 }],
      candidates: [{ name: "공고명", count: 3 }], links_existing: true, existing_count: 3, structure_delta: { added_slots: [], removed_slots: [], added_options: [], removed_options: [], renamed: [] }, body_changed: true }) : {});
  snapshot.tabs[0].analysis = { fields: [{ name: "구", count: 1, occurrences: [] }], slots: [] };
  await controller.activate("a");
  controller.update({ panel: "properties", commandType: "create_field", selected: null });
  await controller.preview({ type: "create_field", name: "공고명" });
  const create = render(controller);
  assert.ok(create.includes("<p>문단 3 · 필드 2 · 선택 1 · 표 0</p>"));
  assert.ok(create.includes('<ul aria-label="포함될 내용"><li>특약 사항</li><li>세부 조건</li></ul>'));
  assert.ok(create.includes('<ul aria-label="하위 의미"><li>선택 · 갑 · 1</li></ul>'));
  assert.ok(create.includes('<option value="공고명" label="공고명 · 사용 위치 3곳"></option>'), "후보 목록은 Python 의 candidates 와 사용 위치 수를 쓴다");
  assert.ok(create.includes("<p>기존 필드에 연결 · 사용 위치 3곳</p>"));
  assert.ok(create.includes("<p>본문 변경 있음</p>"));
  controller.update({ commandType: "rename_field", selected: { kind: "field", name: "공고명", occurrences: [] } });
  await controller.preview({ type: "rename_field", name: "사업명" });
  // 문장은 조사까지 Python 이 지은 preview.message 그대로다(§13) — 표면은 새로 짓지 않는다.
  assert.match(render(controller), /<p>현재 문서의 사용 위치 4곳이 ‘사업명’으로 변경됩니다\.<\/p>/);
});

test("F24/F12/F13: problems drive the outline badges, the panel's text-only severity·category, and the action wiring", async () => {
  const { controller, snapshot } = harness();
  snapshot.tabs[0].analysis = { slots: [{ id: "doc", label: "문서", options: [{ id: "quote", label: "견적서" }] }], fields: [{ name: "공고명", count: 2, occurrences: [] }] };
  snapshot.tabs[0].problems = [
    { severity: "error", category: "structure", message: "선택 ‘견적서’의 범위가 항목 밖으로 나갑니다.", target: "quote", location: { start: 4, end: 9 }, actions: [{ label: "위치로 이동", kind: "navigate" }, { label: "구조 표기 수정", kind: "command", command: { type: "repair_marker", id: "quote" } }] },
    { severity: "warning", category: "compatibility", message: "변경 후 보존을 확인할 수 없습니다.", target: "공고명", location: null, actions: [] },
  ];
  snapshot.tabs[0].readiness = { state: "draft", errors: 1, warnings: 1, message: "" };
  await controller.activate("a");
  controller.update({ panel: "problems" });
  const markup = render(controller);
  assert.ok(markup.includes('<span class="authoring-tree-name" title="견적서">견적서</span><span class="authoring-tree-meta">문제 1</span>'));
  assert.ok(markup.includes('<span class="authoring-tree-name" title="공고명">공고명</span><span class="authoring-tree-meta">사용 위치 2곳 · 문제 1</span>'), "사용 위치 수는 글로 선다");
  assert.ok(markup.includes('<span class="authoring-tree-name" title="문서">문서</span></span><ul role="group">'), "문제가 없는 항목에는 메타 표시가 없다");
  assert.ok(markup.includes('<span class="authoring-problem-category">구조</span> 선택 ‘견적서’의 범위가 항목 밖으로 나갑니다.'));
  assert.ok(markup.includes('<span class="authoring-badge" data-severity="error">오류</span>'));
  assert.ok(markup.includes('<span class="authoring-problem-category">호환성</span> 변경 후 보존을 확인할 수 없습니다.'));
  assert.ok(markup.includes('<span class="authoring-badge" data-severity="warning">경고</span>'));
  assert.ok(markup.includes('<span class="authoring-row-context">quote</span>'));
  assert.ok(markup.includes('title="위치로 이동" aria-label="위치로 이동 · 오류 · 구조 · quote · 선택 ‘견적서’의 범위가 항목 밖으로 나갑니다."') && markup.includes(">구조 표기 수정</button>"));
  // 상태 막대의 수는 문제 탭 배지와 같은 problems 에서 온다 — 문제가 있으면 문제 탭으로 가는 글 링크 모양 단추다(IDE-01).
  assert.ok(markup.includes('<button type="button" class="authoring-status-link">구조 오류 1개 · 경고 1개</button>') && markup.includes("<span>저장됨 · 초안</span>"));
  assert.ok(markup.includes('id="authoring-dock-tab-problems" class="authoring-dock-tab" tabindex="0" aria-selected="true" aria-controls="authoring-dock-panel">문제 <span class="authoring-badge">2</span></button>'));
  const recorded = [];
  const stub = { select: async (target) => { recorded.push(["select", target]); }, preview: async (command) => { recorded.push(["preview", command]); } };
  const [problem] = snapshot.tabs[0].problems;
  await problemAction(stub, snapshot.tabs[0], problem, problem.actions[0]);
  await problemAction(stub, snapshot.tabs[0], problem, problem.actions[1]);
  assert.deepEqual(recorded, [["select", { source_revision: 0, start: 4, end: 9, target: "quote" }], ["preview", { type: "repair_marker", id: "quote" }]]);
});

test("P09/AC14: the footer separates save state from readiness, and a save notice appears inline until the next edit", async () => {
  const { controller, snapshot } = harness((action) => action === "save" ? { notice: "초안은 저장되었습니다. 사용 전에 구조 오류 1개를 확인하세요." } : action === "update" ? { revision: 1 } : {});
  snapshot.tabs[0].readiness = { state: "ready", errors: 0, warnings: 0, message: "" };
  await controller.activate("a");
  assert.ok(render(controller).includes("<span>저장됨 · 사용 준비</span>"));
  await controller.save("a");
  const saved = render(controller);
  assert.ok(saved.includes('<p class="authoring-notice">초안은 저장되었습니다. 사용 전에 구조 오류 1개를 확인하세요.</p>'), "알림은 보이는 줄이고, 읽기는 단일 live region 이 한다");
  controller.changed("a", "edited");
  assert.equal(controller.viewModel.getSnapshot().notice, "");
  await controller.flush("a");
  snapshot.tabs[0].readiness = undefined;
  snapshot.tabs[0].dirty = true;
  assert.ok(render(controller).includes("<span>저장하지 않은 변경</span>"));
});

test("F38/F19/U11: the impact panel renders structure_delta·identifier changes·unverified count·per-job status, and usable=false disables 적용 영향 확인 with the reason", async () => {
  const { controller } = harness((action) => action === "impact" ? { available: true, usable: false, save_required: false, content_changed_since_save: true, unverified_jobs: ["옛 작업"],
    structure_delta: { added_slots: ["특약"], removed_slots: [], added_options: [{ id: "q", label: "견적서" }], removed_options: [], renamed: [{ kind: "slot", from: "doc", to: "document" }] },
    identifier_changes: [{ kind: "slot", from: "doc", to: "document" }],
    jobs: [{ name: "월간 공고", added_fields: ["사업명"], removed_fields: ["공고명"], change_status: "ready", blocked_reason: "템플릿을 저장한 뒤 확인할 수 있습니다." }] } : {});
  await controller.activate("a");
  await controller.impact();
  const markup = render(controller);
  assert.ok(markup.includes("<p>추가 항목: 특약</p><p>추가 선택: 견적서</p>"));
  assert.ok(markup.includes('<ul aria-label="식별자 변경"><li>항목 · doc → document</li></ul>'));
  assert.ok(markup.includes("<p>식별자 변경은 기존 작업 연결에 영향을 줄 수 있습니다.</p>"));
  assert.ok(markup.includes("<p>저장 이후 본문 변경 있음</p>"));
  assert.ok(markup.includes("<p>연결된 작업의 영향은 확인하지 않았습니다.</p><p>확인하지 않은 작업 1개</p>"));
  assert.ok(markup.includes(`<p>${TPL_STATUS_COPY.ready}</p>`));
  assert.ok(markup.includes('<button type="button" class="btn" disabled="" aria-disabled="true" title="템플릿을 저장한 뒤 확인할 수 있습니다.">적용 영향 확인</button><p class="authoring-reason">템플릿을 저장한 뒤 확인할 수 있습니다.</p>'));
});

test("F26: 원문 표기 asks Python's syntax action and renders read-only sections with a copy button", async () => {
  const { controller, calls } = harness((action) => action === "syntax" ? { sections: [{ entry: "Contents/section0.xml", text: "{{공고명}}\n{{#특약}}…{{/특약}}" }], note: "HWPX 원문 표기는 읽기 전용" } : {});
  await controller.activate("a");
  await controller.raw();
  assert.deepEqual(calls.filter((call) => ["syntax", "content"].includes(call.action)).map((call) => call.action), ["syntax"]);
  const markup = render(controller);
  assert.ok(markup.includes('<section class="authoring-bottom" aria-label="원문 표기"><h2>원문 표기</h2><p>HWPX 원문 표기는 읽기 전용</p>'));
  assert.ok(markup.includes('<h3>Contents/section0.xml</h3><pre tabindex="0" role="group" aria-label="Contents/section0.xml 원문 표기">{{공고명}}'));
  assert.ok(markup.includes('class="btn quiet">복사</button>'));
  assert.ok(!markup.includes("<textarea"), "JSON 덤프 textarea 는 없다");
});

test("U03 keeping the captured text asks keep/replace when a trial value already exists", async () => {
  const runs = [];
  const make = (answer) => harness((action, payload) => { if (action === "trial_input") runs.push([answer, payload.values]); return {}; }, { choose: async () => answer });
  const kept = make("keep");
  kept.controller.update({ values: { 공고명: "old" }, selectedOptions: {} });
  assert.equal(await kept.controller.keepTrialValue("공고명", "new"), false, "유지를 고르면 시험값이 바뀌지 않는다");
  const replaced = make("replace");
  replaced.controller.update({ values: { 공고명: "old" }, selectedOptions: {} });
  assert.equal(await replaced.controller.keepTrialValue("공고명", "new"), true);
  const fresh = make("keep");
  fresh.controller.update({ values: {}, selectedOptions: {} });
  assert.equal(await fresh.controller.keepTrialValue("공고명", "new"), true, "값이 없으면 묻지 않고 보관한다");
  assert.deepEqual(runs, [["replace", { 공고명: "new" }], ["keep", { 공고명: "new" }]]);
});

// ---- U02 재열기 복원 · U01 호환성 안내 시점 · §10 화면 읽기·색 비의존 ----
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("U02: Python's restore projection seeds the new view once — mode into the view, coordinates into the editor when it attaches", async () => {
  const { controller, snapshot } = harness();
  const selection = { start: 3, end: 9 };
  snapshot.tabs[0].restore = { state: "restored", mode: "structure", selection, message: null };
  snapshot.tabs[0].analysis = { fields: [] };
  await controller.activate("a");
  assert.equal(controller.viewModel.getSnapshot().mode, "structure");
  assert.deepEqual(controller.viewModel.getSnapshot().selection, selection);
  const seen = [];
  controller.attach("a", { decorate: (_analysis, mode) => seen.push(["decorate", mode]), focus: async (target) => { seen.push(["focus", target]); } });
  await new Promise(setImmediate);
  assert.deepEqual(seen, [["decorate", "structure"], ["focus", selection]]);
  // 한 번만 소비한다 — 다시 붙거나 다시 활성화해도 커서를 옮기지 않는다.
  controller.attach("a", { decorate: () => seen.push(["again"]), focus: async () => { seen.push(["again"]); } });
  await controller.activate("b");
  await controller.activate("a");
  await new Promise(setImmediate);
  assert.equal(seen.filter(([kind]) => kind === "again").length, 0);
});

test("U02: an editor attached before activation still receives the restore (the race is the controller's, not the user's)", async () => {
  const { controller, snapshot } = harness((action) => action === "activate" ? { restore: { state: "restored", mode: "document", selection: { start: 1, end: 1 }, message: null } } : {});
  const seen = [];
  controller.attach("a", { decorate: (_analysis, mode) => seen.push(mode), focus: async (target) => { seen.push(target); } });
  await new Promise(setImmediate);
  assert.deepEqual(seen, [], "복원 판정이 오기 전에는 아무것도 하지 않는다");
  await controller.activate("a");
  assert.deepEqual(seen, ["document", { start: 1, end: 1 }]);
  assert.equal(snapshot.tabs[0].restore, undefined);
});

test("U02: a stale restore keeps the mode but never moves the caret, and its message stands in the footer", async () => {
  const { controller, snapshot } = harness();
  snapshot.tabs[0].restore = { state: "stale", mode: "structure", selection: null, message: "마지막 작업 이후 문서가 바뀌어 작업 위치를 복원하지 않았습니다." };
  await controller.activate("a");
  let focused = 0;
  controller.attach("a", { decorate() {}, focus: async () => { focused++; } });
  await new Promise(setImmediate);
  assert.equal(focused, 0);
  assert.equal(controller.viewModel.getSnapshot().mode, "structure");
  assert.ok(render(controller).includes('<span data-restore="stale">마지막 작업 이후 문서가 바뀌어 작업 위치를 복원하지 않았습니다.</span>'));
});

test("U02: position and mode changes reach Python as editor coordinates only, debounced, and a close sends the pending one first", async () => {
  const { controller, calls } = harness((action) => action === "locate" ? { matches: [], context: {} } : {});
  await controller.activate("a");
  // 한글 조합 중이면 편집기 flush 는 던진다 — 위치 기록은 그 경로를 타지 않으므로 경보가 서지 않는다.
  controller.attach("a", { flush: async () => { throw new Error("한글 조합을 마친 뒤 다시 실행하세요."); }, decorate() {}, focus: async () => {} });
  controller.selection("a", { start: 1, end: 2 });
  controller.selection("a", { start: 4, end: 6 });
  assert.equal(calls.filter((call) => call.action === "remember_view").length, 0, "모아서 보낸다");
  await sleep(450);
  assert.deepEqual(calls.filter((call) => call.action === "remember_view").map(({ selection, mode, revision }) => ({ selection, mode, revision })),
    [{ selection: { start: 4, end: 6 }, mode: "template", revision: 0 }]);
  // 이 대역 편집기는 캐럿 locate 의 flush 도 거절한다(그 오류는 locate 의 것으로 남는다 — UX-04 오류 수명). 위치 기록은 flush 를 타지 않으므로 제 경보를 세우지 않는다.
  assert.notEqual(controller.viewModel.getSnapshot().errorKind, "remember");
  // 조합이 끝난 편집기로 닫는다(닫기 자체의 flush 는 조합 중 거절이 맞다).
  controller.attach("a", { decorate() {}, focus: async () => {} });
  controller.setMode("structure");
  controller.update({ selection: { start: 4, end: 6, kind: "field", name: "이름", occurrences: [] } });
  await controller.close("a");
  const sent = calls.filter((call) => call.action === "remember_view" || call.action === "close").map((call) => call.action === "close" ? "close" : call.selection);
  assert.deepEqual(sent.slice(1), [{ start: 4, end: 6 }, "close"], "선택 대상 객체의 이름·종류는 보내지 않는다");
  assert.equal(calls.filter((call) => call.action === "remember_view").at(-1).mode, "structure");
});

test("§10: coordinates() keeps only editor coordinates and drops incomplete ones", () => {
  assert.deepEqual(coordinates({ entry: "s0", paragraph: 2, start_paragraph: 2, end_paragraph: 3, start: 0, end: 4, cell_path: [{ parent_paragraph: 0, control: 0, cell: 1, paragraph: 0 }], name: "x" }),
    { start: 0, end: 4, entry: "s0", paragraph: 2, start_paragraph: 2, end_paragraph: 3, cell_path: [{ parent_paragraph: 0, control: 0, cell: 1, paragraph: 0 }] });
  assert.deepEqual(coordinates({ start: 1 }), {});
  assert.deepEqual(coordinates(null), {});
});

test("U01: the compatibility reporter tells Python only what Python has not judged, once", async () => {
  const sent = [];
  const controller = {
    preflight: async () => ({ editable: false, diagnostics: [{ message: "문서 구조가 가져오기와 내보내기 사이에 변경되었습니다." }] }),
    unverified: async (id, revision, detail) => { sent.push([id, revision, detail]); return {}; },
  };
  const judged = compatibilityReporter(controller, "a", 3);
  assert.deepEqual(await judged.preflight("B64"), { editable: false, diagnostics: [{ message: "문서 구조가 가져오기와 내보내기 사이에 변경되었습니다." }] });
  await judged.onCompatibility({ editable: false, diagnostics: ["…"] });
  assert.deepEqual(sent, [], "Python 이 이미 판정한 차단은 다시 알리지 않는다");
  await judged.onMountError(new Error("studio 적재 실패"));
  await judged.onMountError(new Error("두 번째"));
  assert.deepEqual(sent, [["a", 3, "studio 적재 실패"]], "판정 뒤에 무너진 마운트도 알린다 — 한 번만");

  const failing = compatibilityReporter({ ...controller, preflight: async () => { throw new Error("bridge down"); } }, "b", 0);
  await assert.rejects(failing.preflight("B64"), /bridge down/);
  await failing.onCompatibility({ editable: false, diagnostics: ["Error: bridge down"] });
  assert.deepEqual(sent.at(-1), ["b", 0, "Error: bridge down"]);
});

test("U01/§7.1: Python's compatibility verdict renders at shell level — banner, preserve-the-original verbs and the footer chip — with no editor mounted", async () => {
  const { controller, snapshot } = harness();
  snapshot.tabs[0].media = "hwpx";
  snapshot.tabs[0].compatibility = { state: "checking", editable: false, message: null, diagnostics: [] };
  await controller.activate("a");
  let markup = render(controller);
  assert.ok(markup.includes('<span data-compat="checking">보존 확인 중</span>'));
  assert.ok(!markup.includes("authoring-compat"));
  snapshot.tabs[0].compatibility = { state: "limited", editable: false, message: "이 요소는 표시할 수 있지만 변경 후 보존을 확인할 수 없습니다. 원본을 유지한 채 확인하세요.",
    diagnostics: [{ kind: "preflight_unavailable", message: "HWPX 보존 검사를 실행할 수 없습니다.", detail: "Error: studio 적재 실패" }, { entry: "Contents/header.xml", message: "문서 구조가 가져오기와 내보내기 사이에 변경되었습니다." }] };
  markup = render(controller);
  const banner = markup.slice(markup.indexOf('<section class="authoring-compat" role="alert" aria-label="호환성 경고">'));
  assert.ok(banner.length < markup.length, "호환성 경고 구획이 선다");
  assert.ok(banner.startsWith('<section class="authoring-compat" role="alert" aria-label="호환성 경고"><strong>읽기 전용 · 보존 확인 필요</strong><p>이 요소는 표시할 수 있지만 변경 후 보존을 확인할 수 없습니다. 원본을 유지한 채 확인하세요.</p>'));
  assert.ok(banner.includes('<p>HWPX 보존 검사를 실행할 수 없습니다.</p><p class="authoring-reason">Error: studio 적재 실패</p>'));
  assert.ok(banner.includes(">다른 이름으로 저장</button>") && banner.includes(">원문 표기</button>"));
  assert.ok(markup.includes('<span data-compat="limited">읽기 전용 · 보존 확인 필요</span>'));
  assert.ok(markup.indexOf("authoring-compat") < markup.indexOf("authoring-editor-host"), "안내는 문서 편집면보다 먼저 읽힌다");
});

test("§10: screen readers get the field name, use count, parent item and problem count; the properties name input is described by target and context", async () => {
  const { controller, snapshot } = harness();
  snapshot.tabs[0].analysis = { slots: [{ id: "doc", label: "문서", options: [{ id: "quote", label: "견적서" }] }],
    fields: [{ name: "공고명", count: 2, occurrences: [{ start: 0, end: 7, context: "공고명: 2026" }, { start: 20, end: 27 }] }] };
  snapshot.tabs[0].problems = [{ severity: "error", category: "structure", message: "m", target: "quote", location: null, actions: [] },
    { severity: "warning", category: "compatibility", message: "m", target: "공고명", location: null, actions: [] }];
  await controller.activate("a");
  let markup = render(controller);
  assert.ok(markup.includes('aria-label="필드 · 공고명 · 사용 위치 2곳 · 문제 1"'));
  assert.ok(markup.includes('aria-label="항목 · 문서"'));
  assert.ok(markup.includes('aria-label="선택 · 견적서 · 상위 항목 문서 · 문제 1"'));
  // 사용 위치 줄은 필드 줄을 펼친 뒤에 선다(UX-05) — 펼친 뒤의 이름은 authoring_render.test.js 가 실제 커밋으로 잰다.
  assert.ok(!markup.includes("사용 위치 1/2"), "접힌 필드 줄은 사용 위치 줄을 짓지 않는다");
  assert.equal(outlineLabel("occurrence", { name: "공고명", index: 1, total: 2, context: "공고명: 2026" }), "공고명 · 사용 위치 1/2 · 공고명: 2026");
  assert.equal(outlineLabel("occurrence", { name: "공고명", index: 2, total: 2 }), "공고명 · 사용 위치 2/2");
  controller.update({ panel: "properties", selected: { kind: "field", name: "공고명", count: 2, occurrences: [{ start: 0, end: 7 }] }, selection: { start: 0, end: 7 }, commandType: "rename_field",
    context: { slot_id: null, option_id: null, location_label: "문단 1" } });
  markup = render(controller);
  assert.ok(markup.includes('<form class="authoring-properties" aria-labelledby="authoring-properties-title">'));
  // 보이는 것은 굵은 이름, 종류·사용 위치 수·문제 수는 화면 읽기용 글로 이름에 붙는다 — 이름 칸이 읽는 글은 그대로다.
  const target = /<p id="authoring-properties-target" class="authoring-target-name">(.*?)<\/p>/.exec(markup)[1];
  assert.equal(target.replace(/<[^>]+>/g, ""), "필드 · 공고명 · 사용 위치 2곳 · 문제 1");
  assert.ok(target.includes('<span class="authoring-sr">필드 · </span>공고명<span class="authoring-sr"> · 사용 위치 2곳 · 문제 1</span>'));
  assert.ok(markup.includes('<p class="authoring-target-meta" aria-hidden="true">사용 위치 2곳 · 문제 1</p>'), "보이는 메타 줄은 이름과 두 번 읽히지 않는다");
  // UX-10 R2: 문맥 줄은 Python 의 location_label 그대로다 — 원시 글자 offset(「문서 · 0–7」)은 보이지 않는다.
  assert.ok(markup.includes('<p class="authoring-context" id="authoring-properties-context">문단 1</p>'));
  assert.ok(!markup.includes("0–7"));
  assert.match(markup, /<input class="field" list="authoring-existing-fields" aria-describedby="authoring-properties-target authoring-properties-context"/);
  assert.equal(outlineLabel("option", { id: "q" }, 0, "doc"), "선택 · q · 상위 항목 doc");
});

// ---- UX-09: 문서 척추(구조 보기) 순수 판정 — 소속·차례·경로는 Python 의 order·slot_id·option_id 그대로다 ----
test("UX-09: outlineSpine places slots in order, options under their slot, and uses under their option/slot — unknown or null owners land on the spine", () => {
  const analysis = {
    slots: [
      { id: "s2", order: 1, options: [{ id: "o1", order: 0 }] },
      { id: "s1", order: 0, options: [] },
    ],
    fields: [{ name: "f", occurrences: [
      { slot_id: "s1", option_id: null, order: 2 },
      { slot_id: "s2", option_id: "o1", order: 3 },
      { slot_id: null, option_id: null, order: 5 },
      { slot_id: "gone", option_id: null, order: 4 },
    ] }],
  };
  const spine = outlineSpine(analysis);
  assert.deepEqual(spine.map((node) => node.kind === "use" ? "use" : node.slot.id), ["s1", "s2", "use", "use"]);
  assert.deepEqual(spine.slice(2).map((node) => node.order), [4, 5], "소속 없는(null) 필드와 못 찾은(gone) 항목의 사용 위치 모두 척추 위, order 차례대로");
  const s1 = spine[0], s2 = spine[1];
  assert.equal(s1.kind, "slot"); assert.equal(s1.children.length, 1); assert.equal(s1.children[0].kind, "use");
  assert.equal(s2.children[0].kind, "option"); assert.equal(s2.children[0].option.id, "o1");
  assert.equal(s2.children[0].children[0].kind, "use");
});

test("UX-09: outlineSpine keeps insertion order for nodes with no order (stable sort, oldest projections)", () => {
  const analysis = { slots: [{ id: "b" }, { id: "a" }], fields: [] };
  assert.deepEqual(outlineSpine(analysis).map((node) => node.slot.id), ["b", "a"], "차례가 없으면 받은 차례를 지킨다");
});

test("UX-09: outlineCurrent resolves the whole-field path, an occurrence's slot/option/use path, prefers the explicit selection over a caret match, and an option beats a bare slot", () => {
  const analysis = { slots: [{ id: "s1", options: [{ id: "o1" }] }],
    fields: [{ name: "f", occurrences: [{ entry: "e", paragraph: 0, slot_id: "s1", option_id: "o1" }, { entry: "e", paragraph: 1, slot_id: null, option_id: null }] }] };
  assert.deepEqual(outlineCurrent(analysis, { kind: "field", name: "f", occurrences: [{}] }), { structure: [], fields: [outlineKey.field("f")] },
    "필드 전체 선택은 필드 탭 경로만 짓는다");
  const selected = { kind: "field", name: "f", entry: "e", paragraph: 0 };
  const caretMatch = { kind: "field", name: "f", location: { entry: "e", paragraph: 1 } };
  assert.deepEqual(outlineCurrent(analysis, selected, [caretMatch]),
    { structure: [outlineKey.slot("s1"), outlineKey.option("s1", "o1"), outlineKey.use("f", 1)], fields: [outlineKey.field("f"), outlineKey.occurrence("f", 1)] },
    "명시 선택이 캐럿의 일치 후보를 이긴다");
  assert.deepEqual(outlineCurrent(analysis, null, [{ kind: "slot", slot_id: "s1" }, { kind: "option", slot_id: "s1", option_id: "o1" }]),
    { structure: [outlineKey.slot("s1"), outlineKey.option("s1", "o1")], fields: [] }, "선택이 있으면 항목보다 선택이 이긴다");
  assert.deepEqual(outlineCurrent(analysis, null, [{ kind: "slot", slot_id: "s1" }]), { structure: [outlineKey.slot("s1")], fields: [] });
  assert.deepEqual(outlineCurrent(analysis, null, []), { structure: [], fields: [] });
});

test("UX-09: crumbs orders matches slot › option › field regardless of arrival order, stably", () => {
  const field = { kind: "field", name: "f" };
  const slot = { kind: "slot", slot_id: "s" };
  const option = { kind: "option", slot_id: "s", option_id: "o" };
  assert.deepEqual(crumbs([field, slot, option]), [slot, option, field]);
  assert.deepEqual(crumbs([slot, option, field]), [slot, option, field], "이미 바른 차례면 그대로다");
  assert.deepEqual(crumbs(undefined), []);
});

test("UX-09: sameFieldMeta reads 사용 위치 N곳 alone, or 같은 필드, i/n once more than one use shares the field", () => {
  assert.equal(sameFieldMeta(1, 1), "사용 위치 1곳");
  assert.equal(sameFieldMeta(1, 2), "같은 필드, 1/2");
  assert.equal(sameFieldMeta(2, 2), "같은 필드, 2/2");
});

test("UX-09: highlightRanges returns a slot/option's own range, a field's every use or just one by index, and [] for an unknown target", () => {
  const analysis = { slots: [{ id: "s1", location: { start: 5, end: 9 },
    options: [{ id: "o1", location: { start: 6, end: 8 } }] }],
    fields: [{ name: "f", occurrences: [{ start: 1, end: 2 }, { start: 3, end: 4 }] }] };
  assert.deepEqual(highlightRanges(analysis, { kind: "slot", id: "s1" }), [{ start: 5, end: 9 }]);
  assert.deepEqual(highlightRanges(analysis, { kind: "option", slot_id: "s1", id: "o1" }), [{ start: 6, end: 8 }]);
  assert.deepEqual(highlightRanges(analysis, { kind: "field", id: "f" }), [{ start: 1, end: 2 }, { start: 3, end: 4 }]);
  assert.deepEqual(highlightRanges(analysis, { kind: "field", id: "f", index: 2 }), [{ start: 3, end: 4 }]);
  assert.deepEqual(highlightRanges(analysis, { kind: "field", id: "missing" }), []);
  assert.deepEqual(highlightRanges(analysis, { kind: "slot", id: "missing" }), []);
  assert.deepEqual(highlightRanges(analysis, null), []);
});

test("UX-09: problemSeverities keeps the heaviest severity per target — an error is never downgraded by a later warning", () => {
  const problems = [
    { target: "a", severity: "warning" },
    { target: "a", severity: "error" },
    { target: "b", severity: "warning" },
    { target: "a", severity: "warning" },
    { target: null, severity: "error" },
  ];
  const severities = problemSeverities(problems);
  assert.equal(severities.get("a"), "error");
  assert.equal(severities.get("b"), "warning");
  assert.equal(severities.size, 2, "target 이 없는 문제는 세지 않는다");
});

test("UX-09: fieldsInFirstUse orders fields by their earliest occurrence's order, and keeps array order for ties or missing order", () => {
  const analysis = { fields: [
    { name: "z", occurrences: [{ order: 5 }] },
    { name: "a", occurrences: [{ order: 1 }, { order: 0 }] },
    { name: "m", occurrences: [] },
  ] };
  assert.deepEqual(fieldsInFirstUse(analysis).map((field) => field.name), ["a", "z", "m"]);
});

test("UX-09: filterMatch is case-insensitive over every given text, and an empty query matches everything", () => {
  assert.equal(filterMatch("", "아무거나"), true);
  assert.equal(filterMatch("ABC", "xABCy"), true);
  assert.equal(filterMatch("abc", "xABCy"), true);
  assert.equal(filterMatch("공고", "제목", "설명"), false);
  assert.equal(filterMatch("공고", "제목", "공고 안내"), true);
});

test("§10: items and options, errors and warnings stay distinguishable without color", async () => {
  const { controller, snapshot } = harness();
  snapshot.tabs[0].analysis = { slots: [{ id: "doc", label: "문서", options: [{ id: "quote", label: "견적서" }] }], fields: [] };
  snapshot.tabs[0].problems = [
    { severity: "error", category: "structure", message: "오류 설명", target: "quote", location: null, actions: [] },
    { severity: "warning", category: "compatibility", message: "경고 설명", target: null, location: null, actions: [] },
  ];
  await controller.activate("a");
  controller.update({ panel: "problems" });
  const markup = render(controller);
  // 항목·선택: 글자 표지가 이름 앞에 선다(들여쓰기·색이 유일한 구별이 아니다).
  assert.ok(markup.includes('<span class="authoring-kind">항목</span><span class="authoring-tree-name" title="문서">문서</span>'));
  assert.ok(markup.includes('<span class="authoring-kind">선택</span><span class="authoring-tree-name" title="견적서">견적서</span><span class="authoring-tree-meta">문제 1</span>'));
  // 오류·경고: 심각도와 종류가 글자로 선다.
  assert.ok(markup.includes('<span class="authoring-badge" data-severity="error">오류</span><span class="authoring-row-text"><span class="authoring-problem-category">구조</span> 오류 설명</span>'));
  assert.ok(markup.includes('<span class="authoring-badge" data-severity="warning">경고</span><span class="authoring-row-text"><span class="authoring-problem-category">호환성</span> 경고 설명</span>'));
  // 문제 배지는 수를 글로 센다.
  assert.ok(!/class="authoring-badge"[^>]*>\s*<\/span>/.test(markup));
});

// ---- §3.1 셸 배치(UX-01): 도구 막대 한 줄 · 하단 독 한 탭 · 사유 한 번 · 속성 닫기 · 더보기 ----
const toolbarOf = (markup) => { const start = markup.indexOf('<div class="authoring-toolbar"'); return markup.slice(start, markup.indexOf('<div class="authoring-body', start)); };
const dockOf = (markup) => { const start = markup.indexOf('<section class="authoring-dock'); if (start < 0) return ""; const end = markup.indexOf("<footer", start); return markup.slice(start, end < 0 ? undefined : end); };
const count = (text, needle) => text.split(needle).length - 1;

test("§3.1: the toolbar is one labelled row of document commands; panels, copy/paste, the palette, zoom and back moved out of it", async () => {
  const { controller } = harness();
  await controller.activate("a");
  const toolbar = toolbarOf(render(controller));
  assert.ok(toolbar.startsWith('<div class="authoring-toolbar" role="toolbar" aria-label="문서 명령">'));
  for (const label of ["필드로 만들기", "항목으로 만들기", "선택으로 만들기", "결과 시험"]) assert.ok(toolbar.includes(`>${label}</button>`), label);
  // 만들기 셋은 테두리 없는 글 단추다 — 막대에서 테두리 단추는 실행 단추 「결과 시험」 하나뿐이다.
  for (const label of ["필드로 만들기", "항목으로 만들기", "선택으로 만들기"]) assert.match(toolbar, new RegExp(`<button type="button" class="btn quiet"[^>]*>${label}</button>`), label);
  assert.equal(count(toolbar, 'class="btn"'), 1, "테두리 단추는 결과 시험 하나");
  // 실행 취소·다시 실행·더보기는 아이콘 단추다 — 보이는 글자 대신 aria-label·title 로 이름을 낸다.
  for (const label of ["문서 실행 취소", "문서 다시 실행", "더보기"]) assert.ok(toolbar.includes(`aria-label="${label}" title="${label}"`), label);
  // 표시 방식은 세 갈래 버튼 — 같은 setMode 로 간다.
  assert.ok(toolbar.includes('<div class="authoring-mode" role="group" aria-label="표시"><button type="button" value="document" aria-pressed="false" data-rove="mode-document" tabindex="-1">문서</button><button type="button" value="template" aria-pressed="true" data-rove="mode-template" tabindex="-1">템플릿</button><button type="button" value="structure" aria-pressed="false" data-rove="mode-structure" tabindex="-1">구조</button></div>'));
  assert.ok(!toolbar.includes("<select") && !toolbar.includes('aria-label="확대"'), "확대는 상태 막대로 옮겼다");
  assert.equal(count(toolbar, 'tabindex="0"'), 1, "APG toolbar: Tab 순서에는 한 제어만 선다(roving)");
  assert.ok(!toolbar.includes("<label"), "도구 막대 안에 줄을 늘리는 라벨이 없다");
  for (const moved of ["문제", "검색", "원문 표기", "변경 영향·작업 적용", "의미 복사", "붙여넣기", "이전 위치로", "명령"]) assert.ok(!toolbar.includes(`>${moved}</button>`), moved);
  assert.ok(toolbar.includes('aria-label="더보기" title="더보기" aria-haspopup="menu" aria-expanded="false" data-rove="more" tabindex="-1">'));
  assert.ok(toolbar.includes('aria-pressed="false" data-rove="trial" tabindex="-1">결과 시험</button>'));
  assert.ok(!toolbar.includes('data-rove="commands"') && !toolbar.includes('data-rove="zoom"'));
});

test("§3.1 head band: back icon, title, 파일 menu, the open-document tabs and 저장 share one band; 저장 fills only when there is something to save", async () => {
  const { controller, snapshot } = harness();
  await controller.activate("a");
  let markup = render(controller);
  const head = markup.slice(markup.indexOf('<header class="authoring-head">'), markup.indexOf("</header>") + 9);
  assert.ok(head.startsWith('<header class="authoring-head"><button type="button" class="btn icon" aria-label="돌아가기" title="돌아가기">'), "돌아가기는 그림 단추(이름은 aria-label·title)");
  assert.ok(head.includes('</button><h1>템플릿 저작</h1><button type="button" class="btn quiet" aria-haspopup="menu" aria-expanded="false">파일</button><div class="authoring-tabs" role="tablist" aria-label="열린 문서">'));
  assert.ok(head.endsWith('</div><button type="button" class="btn quiet">저장</button></header>'), "띠 끝의 저장 — 저장할 것이 없으면 물러선 단추");
  for (const moved of ["문서 열기", "새 TXT", "다른 이름으로 저장", ">돌아가기<"]) assert.ok(!head.includes(moved.startsWith(">") ? moved : `>${moved}</button>`), moved);
  assert.ok(!markup.slice(markup.indexOf("</header>")).includes('class="authoring-tabs"'), "탭 줄은 머리 띠 밖에 따로 서지 않는다");
  snapshot.tabs[0].dirty = true;
  markup = render(controller);
  assert.ok(markup.includes('<button type="button" class="btn primary">저장</button></header>'), "저장할 변경이 있으면 채움");
});

test("§3.1 파일 menu: 문서 열기·새 TXT·저장(Ctrl+S)·다른 이름으로 저장 as an APG menu; with no document the two save items are aria-disabled", async () => {
  const { controller, snapshot } = harness();
  await controller.activate("a");
  openContextMenu(controller, { clientX: 40, clientY: 30, target: null }, { getBoundingClientRect: () => ({ left: 10, top: 20 }) }, "file");
  let markup = render(controller);
  let menu = markup.slice(markup.indexOf('<div class="authoring-context-menu"'));
  assert.ok(menu.startsWith('<div class="authoring-context-menu" style="left:30px;top:10px"><div class="authoring-menu" id="authoring-menu" role="menu" aria-label="파일"><button type="button" class="authoring-menu-item" role="menuitem" tabindex="-1">문서 열기</button><button type="button" class="authoring-menu-item" role="menuitem" tabindex="-1">새 TXT</button><button type="button" class="authoring-menu-item with-key" role="menuitem" tabindex="-1" aria-keyshortcuts="Control+S">저장<kbd class="authoring-key" aria-hidden="true">Ctrl+S</kbd></button><button type="button" class="authoring-menu-item" role="menuitem" tabindex="-1">다른 이름으로 저장</button></div></div>'));
  assert.ok(markup.includes('aria-haspopup="menu" aria-expanded="true" aria-controls="authoring-menu">파일</button>'), "여는 단추가 펼침 상태를 싣는다");
  assert.ok(!menu.includes("authoring-reason"), "파일 메뉴에는 명령 사유 머리 줄이 서지 않는다");
  // 문서가 없는 빈 작업대에서도 파일 메뉴는 선다 — 저장 둘은 불가(초점은 받는다).
  snapshot.tabs = [];
  snapshot.active_id = "";
  markup = render(controller);
  menu = markup.slice(markup.indexOf('<div class="authoring-context-menu"'));
  assert.equal(count(menu, 'role="menuitem"'), 4);
  assert.ok(menu.includes('role="menuitem" tabindex="-1">문서 열기</button>') && menu.includes('role="menuitem" tabindex="-1">새 TXT</button>'));
  assert.ok(menu.includes('role="menuitem" tabindex="-1" aria-disabled="true" aria-keyshortcuts="Control+S">저장<kbd'));
  assert.ok(menu.includes('role="menuitem" tabindex="-1" aria-disabled="true">다른 이름으로 저장</button>'));
  assert.ok(markup.includes('<header class="authoring-head">') && markup.includes('<button type="button" class="btn quiet" disabled="">저장</button></header>'), "문서가 없으면 띠의 저장은 꺼진다");
  assert.equal(escapeShell(controller), "menu");
  assert.equal(controller.viewModel.getSnapshot().contextMenu, null);
});

test("§3.1: the bottom dock keeps its tab strip, counts problems as text and shows exactly one tab panel", async () => {
  const { controller, snapshot } = harness();
  snapshot.tabs[0].problems = [{ severity: "error", category: "structure", message: "m", target: "x", location: null, actions: [] }, { severity: "warning", category: "structure", message: "n", target: "y", location: null, actions: [] }];
  await controller.activate("a");
  let dock = dockOf(render(controller));
  assert.ok(dock.startsWith('<section class="authoring-dock" role="region" aria-label="보조 패널">'), "닫힌 독도 탭 줄로 남는다");
  assert.ok(dock.includes('<div class="authoring-dock-tabs" role="tablist" aria-label="보조 패널">'));
  assert.ok(dock.includes('id="authoring-dock-tab-problems" class="authoring-dock-tab" tabindex="0" aria-selected="false">문제 <span class="authoring-badge">2</span></button>'), "펼친 탭이 없으면 첫 탭이 Tab 의 입구다");
  for (const label of ["검색", "원문 표기", "변경 영향·작업 적용", "결과 시험"]) assert.ok(dock.includes(`aria-selected="false">${label}</button>`), label);
  assert.equal(count(dock, 'role="tabpanel"'), 0);
  assert.ok(!dock.includes('aria-label="최대화"') && !dock.includes('aria-label="닫기"'), "펼친 탭이 없으면 크기·닫기 동작도 없다");
  // 시험과 문제가 함께 열려 있어도 보이는 것은 하나 — 방금 연 패널(문제)이다.
  controller.update({ trial: true, panel: "problems" });
  let markup = render(controller);
  dock = dockOf(markup);
  assert.equal(count(dock, 'role="tabpanel"'), 1);
  assert.ok(dock.includes('<div class="authoring-dock-panel" id="authoring-dock-panel" role="tabpanel" tabindex="-1" aria-labelledby="authoring-dock-tab-problems"><section class="authoring-bottom" aria-label="문제">'));
  assert.ok(dock.includes('id="authoring-dock-tab-problems" class="authoring-dock-tab" tabindex="0" aria-selected="true" aria-controls="authoring-dock-panel">'));
  assert.equal(count(dock, 'tabindex="0"'), 1, "APG tabs: 펼친 탭 하나만 Tab 순서에 선다");
  assert.ok(!markup.includes('class="authoring-trial"'));
  assert.ok(dock.includes('class="btn icon" aria-label="최대화" title="최대화"') && dock.includes('class="btn icon" aria-label="닫기" title="닫기"'));
  // 패널을 닫으면(Escape 와 같은 경로) 열려 있던 시험이 제 탭으로 선다. 도구 막대의 「결과 시험」은 눌림으로 보인다.
  escapeShell(controller);
  markup = render(controller);
  assert.ok(dockOf(markup).includes('aria-labelledby="authoring-dock-tab-trial"><section class="authoring-trial" aria-label="결과 시험">'));
  assert.ok(toolbarOf(markup).includes('aria-pressed="true" data-rove="trial" tabindex="-1">결과 시험</button>'));
  controller.update({ dockMax: true });
  markup = render(controller);
  assert.ok(markup.includes('<div class="authoring-shell dock-max">') && dockOf(markup).includes('aria-label="복원" title="복원"'));
});

test("§3.1: dockTabs resolves one tab — open panel, then the chosen tab, then alerts; a closed dock does not reopen for an old alert", () => {
  const item = { id: "a", recovery: true, external_changed: true };
  assert.deepEqual(dockTabs(item, { panel: "" }).tabs.map(([key]) => key), ["problems", "search", "raw", "impact", "trial", "external_changed", "recovery"]);
  assert.equal(dockTabs(item, { panel: "" }).active, "recovery");
  assert.equal(dockTabs(item, { panel: "search" }).active, "search");
  assert.equal(dockTabs(item, { panel: "", dock: "external_changed" }).active, "external_changed");
  assert.equal(dockTabs(item, { panel: "", dock: "trial" }).active, "recovery", "시험 탭은 시험이 열려 있을 때만 선다");
  assert.equal(dockTabs(item, { panel: "", dockClosed: true }).active, "");
  assert.equal(dockTabs(item, { panel: "", dockClosed: true, trial: true }).active, "trial", "사용자가 연 시험은 닫힌 독 표지와 무관하다");
  assert.equal(dockTabs(item, { panel: "properties", recoveryPreview: { key: "k" } }).active, "recovery_preview");
  // 저장 실패는 다른 탭을 보는 동안에도 탭으로 남아 복구 동사로 돌아갈 길이 된다. 외부 변경 탭은 그와 겹치지 않는다.
  const failed = dockTabs(item, { panel: "problems", saveFailed: true });
  assert.ok(failed.tabs.some(([key, label]) => key === "external" && label === "저장 실패"));
  assert.ok(!failed.tabs.some(([key]) => key === "external_changed"));
  assert.equal(failed.active, "problems");
  // 문서가 없으면 복구 초안 비교만 설 수 있다.
  assert.deepEqual(dockTabs(undefined, { panel: "", recoveryPreview: { key: "k" } }), { tabs: [["recovery_preview", "초안과 원본 비교"]], active: "recovery_preview" });
  assert.deepEqual(dockTabs(undefined, { panel: "" }), { tabs: [], active: "" });
});

test("§3.1/AC24: alert content keeps role=alert inside the dock", async () => {
  const { controller, snapshot } = harness();
  snapshot.tabs[0].recovery = true;
  await controller.activate("a");
  let dock = dockOf(render(controller));
  assert.ok(dock.includes('aria-labelledby="authoring-dock-tab-recovery"><section class="authoring-bottom" role="alert" aria-label="중단 전 복구 초안"><h2>중단 전 복구 초안</h2>'));
  for (const verb of ["초안과 원본 비교", "복구", "폐기"]) assert.ok(dock.includes(`>${verb}</button>`), verb);
  snapshot.tabs[0].recovery = false;
  snapshot.tabs[0].external_changed = true;
  dock = dockOf(render(controller));
  assert.ok(dock.includes('<section class="authoring-bottom" role="alert" aria-label="외부 파일 변경"><h2>외부 파일 변경</h2>'));
  for (const verb of ["양쪽 내용 확인", "현재 작업을 다른 이름으로 저장", "외부 파일 다시 열기"]) assert.ok(dock.includes(`>${verb}</button>`), verb);
});

const SHARED_VERDICTS = [
  { type: "create_field", enabled: false, reason: "먼저 문서에서 내용을 선택하세요.", alternative: null },
  { type: "create_slot", enabled: false, reason: "먼저 문서에서 내용을 선택하세요.", alternative: null },
  { type: "create_option", enabled: false, reason: "먼저 문서에서 내용을 선택하세요.", alternative: { label: "먼저 항목 만들기", command_type: "create_slot" } },
];

test("§3.1: a reason shared by every unavailable command is shown once, at the top; alternatives stay per item", async () => {
  assert.equal(sharedReason(SHARED_VERDICTS), "먼저 문서에서 내용을 선택하세요.");
  assert.equal(sharedReason(COMMAND_VERDICTS), null, "사유가 갈리면 항목마다 남긴다");
  assert.equal(sharedReason([SHARED_VERDICTS[0]]), null, "불가 명령이 하나면 그 곁에 둔다");
  assert.equal(sharedReason([{ type: "create_field", enabled: false, reason: null }, { type: "create_slot", enabled: false, reason: null }]), null);
  const { controller } = harness();
  await controller.activate("a");
  controller.update({ commands: SHARED_VERDICTS, panel: "commands" });
  const palette = render(controller);
  assert.equal(count(palette, "먼저 문서에서 내용을 선택하세요.</p>"), 1);
  assert.ok(palette.includes('<h2>명령</h2><p id="authoring-command-reason-palette" class="authoring-reason">먼저 문서에서 내용을 선택하세요.</p><div class="authoring-palette"><div class="authoring-command">'));
  assert.ok(palette.includes('disabled="" aria-disabled="true" title="먼저 문서에서 내용을 선택하세요." aria-describedby="authoring-command-reason-palette">선택으로 만들기</button><button type="button" class="authoring-menu-item alternative">먼저 항목 만들기</button>'));
  // 판정이 없는 명령은 세 번째 상태 — 표면이 추측으로 켜 두지 않고, 사유 문장 없이 꺼 둔다(UX-04).
  assert.ok(palette.includes('<div class="authoring-command group-start"><button type="button" class="authoring-menu-item" disabled="" aria-disabled="true" aria-keyshortcuts="F2">필드 이름 변경<kbd class="authoring-key" aria-hidden="true">F2</kbd></button></div>'), "판정이 없는 명령은 사유 없이 꺼 둔다");
  // 팔레트는 도구 막대에서 빠진 세 동작도 싣는다 — 자기 자신을 여는 「명령」은 싣지 않는다.
  for (const label of ["의미 복사", "이전 위치로"]) assert.ok(palette.includes(`class="authoring-menu-item">${label}</button>`), label);
  assert.ok(!palette.includes('class="authoring-menu-item">명령</button>'), "팔레트는 자기를 여는 단추를 싣지 않는다");
  assert.ok(palette.includes('class="authoring-menu-item" disabled="">붙여넣기</button>'), "복사한 의미가 없으면 붙여넣기는 꺼진다");
  openContextMenu(controller, { clientX: 5, clientY: 6, target: null }, null);
  const menu = render(controller);
  const context = menu.slice(menu.indexOf('<div class="authoring-context-menu"'));
  // 공유 사유는 메뉴의 자식이 아니다 — 메뉴 머리 줄로 서고 불가 항목이 설명으로 가리킨다.
  assert.ok(context.startsWith('<div class="authoring-context-menu" style="left:5px;top:6px"><p id="authoring-command-reason-menu" class="authoring-reason">먼저 문서에서 내용을 선택하세요.</p><div class="authoring-menu" id="authoring-menu" role="menu" aria-label="문맥 명령">'));
  assert.ok(context.includes('aria-label="선택으로 만들기" aria-disabled="true" aria-describedby="authoring-command-reason-menu">선택으로 만들기</button>'));
  assert.equal(count(context, "먼저 문서에서 내용을 선택하세요.</p>"), 1);
});

test("§3.1: the properties panel has a visible 닫기 in its header", async () => {
  const { controller } = harness();
  await controller.activate("a");
  controller.update({ panel: "properties", commandType: "create_field", selected: null, selection: { start: 0, end: 2 } });
  const markup = render(controller);
  assert.ok(markup.includes('<form class="authoring-properties" aria-labelledby="authoring-properties-title"><div class="authoring-properties-head"><h2 class="authoring-section-label" id="authoring-properties-title">속성</h2><button type="button" class="btn icon" aria-label="닫기" title="닫기">'));
});

test("§3.1: 더보기 opens a small menu of 명령·의미 복사·붙여넣기·이전 위치로, and Escape closes it before any panel", async () => {
  const { controller } = harness();
  await controller.activate("a");
  controller.update({ panel: "search" });
  let focused = 0;
  openContextMenu(controller, { clientX: 40, clientY: 90, target: { focus: () => { focused++; } } }, { getBoundingClientRect: () => ({ left: 10, top: 20 }) }, "more");
  const markup = render(controller);
  const menu = markup.slice(markup.indexOf('<div class="authoring-context-menu"'));
  assert.ok(menu.startsWith('<div class="authoring-context-menu" style="left:30px;top:70px"><div class="authoring-menu" id="authoring-menu" role="menu" aria-label="더보기"><button type="button" class="authoring-menu-item" role="menuitem" tabindex="-1">명령</button><button type="button" class="authoring-menu-item" role="menuitem" tabindex="-1">의미 복사</button>'), "첫 항목은 명령 팔레트");
  assert.ok(menu.includes('role="menuitem" tabindex="-1" aria-disabled="true">붙여넣기</button>') && menu.includes('role="menuitem" tabindex="-1">이전 위치로</button>'));
  assert.ok(toolbarOf(markup).includes('aria-label="더보기" title="더보기" aria-haspopup="menu" aria-expanded="true" aria-controls="authoring-menu" data-rove="more" tabindex="-1">'));
  assert.equal(escapeShell(controller), "menu");
  assert.equal(focused, 1);
  assert.equal(controller.viewModel.getSnapshot().panel, "search");
});

test("§3.1: the location breadcrumb sits in the centre column right above the canvas, rooted at the document name", async () => {
  const { controller } = harness();
  await controller.activate("a");
  let markup = render(controller);
  // 일치가 없어도 뿌리(문서 이름)가 선다 — 줄이 비어 보이지 않는다. 이름은 navigation 의 aria-label 이 싣는다.
  assert.ok(markup.includes('<div class="authoring-selection" role="navigation" aria-label="현재 위치의 의미"><span class="authoring-crumb root" title="a.txt">a.txt</span></div>'));
  assert.ok(!markup.includes("authoring-selection-label"), "보이는 이름표는 없다");
  controller.update({ matches: [{ kind: "slot", label: "문서", slot_id: "doc" }] });
  markup = render(controller);
  // 위치 경로는 이름 붙은 navigation 이고, 편집면은 앱 셸의 main 안에 겹치지 않는 이름 붙은 구획이다(UX-04).
  assert.ok(markup.includes('<div class="authoring-center"><div class="authoring-selection" role="navigation" aria-label="현재 위치의 의미"><span class="authoring-crumb root" title="a.txt">a.txt</span><span class="authoring-crumb-sep"><svg class="icon"'));
  assert.ok(markup.includes('</svg></span><button type="button" class="authoring-crumb" aria-current="location">항목 · 문서</button></div><section class="authoring-canvas" id="authoring-canvas" aria-label="원문 편집"'));
  assert.ok(!markup.includes("<main"), "화면 안에 main 이 없다");
});

test("P09/§3.1: the status bar splits save·checks from preservation·trial·recovery", async () => {
  const { controller, snapshot } = harness();
  snapshot.tabs[0].readiness = { state: "draft", errors: 1, warnings: 0 };
  snapshot.tabs[0].compatibility = { state: "checking" };
  Object.assign(snapshot.tabs[0], { trial_state: "untried", trial_state_label: "시험 전" });
  await controller.activate("a");
  const markup = render(controller);
  // 시험 전이고 보관한 시험 자료가 없으면 상태 막대에 시험 관련 표지가 없다(IDE-01) — 해당 없는 상태는 빼고,
  // 문제가 없으면 준비 표현은 글이다(문제 탭으로 갈 곳이 없다).
  assert.ok(markup.includes('<footer class="authoring-status" role="group"><div class="authoring-status-group"><span>저장됨 · 초안</span><span>구조 오류 1개 · 경고 0개</span></div><div class="authoring-status-group authoring-status-end"><span data-compat="checking">보존 확인 중</span><select class="field authoring-zoom" aria-label="확대">'));
  const footer = markup.slice(markup.indexOf('<footer class="authoring-status"'));
  assert.ok(!footer.includes("시험") && !footer.includes("authoring-status-link"), "시험 전·케이스 0 이면 시험 표지 0개");
  Object.assign(snapshot.tabs[0], { cases: [{ name: "검토" }] });
  assert.ok(render(controller).includes("<span>시험 자료: 로컬 보관</span>"));
  Object.assign(snapshot.tabs[0], { cases: [], cases_dirty: true });
  assert.ok(render(controller).includes("<span>시험 자료: 저장하지 않은 변경</span>"));
  // 확대는 상태 막대 끝의 작은 선택이다 — roving 묶음 밖의 보통 Tab 순서(data-rove 없음).
  assert.ok(markup.includes('<option value="200">200%</option></select></div></footer>'));
  assert.ok(!markup.includes('data-rove="zoom"'));
});

test("#1025 P09/§9.1: the footer chip and the trial panel show Python's one expression per trial state — untried and failed no longer read alike", async () => {
  const { controller, snapshot } = harness();
  await controller.activate("a");
  const states = {
    untried: ["시험 전", "아직 시험하지 않았습니다."],
    failed: ["시험 실패", "필드 ‘사업명’의 값이 없습니다."],
    stale: ["마지막 시험 이후 변경됨", "마지막 시험 이후 문서 또는 입력이 바뀌었습니다."],
    current: ["현재 구성 통과", "현재 시험 구성 통과"],
  };
  const footers = [];
  for (const [state, [label, message]] of Object.entries(states)) {
    Object.assign(snapshot.tabs[0], { trial_state: state, trial_state_label: label, trial_state_message: message });
    controller.update({ dock: "trial", trial: true });
    const markup = render(controller);
    const footer = markup.slice(markup.indexOf('<footer class="authoring-status"'));
    // 시험 전은 상태 막대에 서지 않는다(IDE-01) — 시험 뒤의 상태는 결과 시험 탭으로 가는 글 링크 모양 단추다.
    if (state === "untried") assert.ok(!footer.includes(label), state);
    else assert.ok(footer.includes(`<button type="button" class="authoring-status-link" data-trial="${state}">${label}</button>`), state);
    assert.ok(markup.includes(`<p>${message}</p>`), state);
    footers.push(label);
  }
  assert.equal(new Set(footers).size, 4, "상태마다 다른 표현");
  const markup = render(controller);
  assert.ok(!markup.includes("다시 시험 필요</span>") && !markup.includes("현재 시험 구성 확인됨</span>"), "표면이 짓던 옛 상태 막대 문구는 사라진다");
});

test("#1025 P09: the footer shows Python's readiness.message when it is sent, and the counts otherwise", async () => {
  const { controller, snapshot } = harness();
  snapshot.tabs[0].readiness = { state: "draft", errors: 2, warnings: 1, message: "사용 전에 구조 오류 2개를 확인하세요." };
  await controller.activate("a");
  let markup = render(controller);
  assert.ok(markup.includes("<span>저장됨 · 초안</span><span>사용 전에 구조 오류 2개를 확인하세요.</span>"));
  snapshot.tabs[0].readiness = { state: "ready", errors: 0, warnings: 1, message: null };
  markup = render(controller);
  assert.ok(markup.includes("<span>저장됨 · 사용 준비</span><span>구조 오류 0개 · 경고 1개</span>"));
});

test("#1025 §6.3: search shows Python's summary above the hits and tags each hit with its kind; several documents get one summary line each", async () => {
  const summaries = { a: "총 3건 · 본문 1 · 필드 1 · 항목·선택 1", b: "총 1건 · 본문 1 · 필드 0 · 항목·선택 0" };
  const { controller } = harness((action, payload) => action === "search" ? { summary: summaries[payload.session_id], hits: payload.session_id === "a"
    ? [{ kind: "text", context: "…수요기관: 공고 안내" }, { kind: "field", name: "공고명", context: "[공고명] 공고" }, { kind: "slot", label: "공고 구분" }]
    : [{ kind: "text", context: "공고" }] } : {});
  await controller.activate("a");
  await controller.search("공고", "all");
  let markup = render(controller);
  assert.ok(markup.includes('<p class="authoring-search-summary">총 3건 · 본문 1 · 필드 1 · 항목·선택 1</p>'));
  assert.ok(markup.includes('<span class="authoring-kind">본문</span><span class="authoring-row-text">…수요기관: 공고 안내</span><span class="authoring-row-context">a.txt</span>'));
  assert.ok(markup.includes('<span class="authoring-kind">필드</span><span class="authoring-row-text">[공고명] 공고</span><span class="authoring-row-context">a.txt</span>'));
  assert.ok(markup.includes('<span class="authoring-kind">항목</span><span class="authoring-row-text">공고 구분</span><span class="authoring-row-context">a.txt</span>'));
  assert.ok(markup.indexOf("authoring-search-summary") < markup.indexOf("…수요기관"), "요약이 결과 위에 선다");
  await controller.search("공고", "all", true);
  markup = render(controller);
  assert.ok(markup.includes('<p class="authoring-search-summary">a.txt · 총 3건 · 본문 1 · 필드 1 · 항목·선택 1</p>'));
  assert.ok(markup.includes('<p class="authoring-search-summary">b.txt · 총 1건 · 본문 1 · 필드 0 · 항목·선택 0</p>'));
});

test("#1025 §13: the empty workbench has one sentence, the 파일 menu's two actions and the recoverable drafts as a list", async () => {
  const { controller, calls, snapshot } = harness();
  snapshot.tabs = [];
  snapshot.active_id = "";
  snapshot.recoverable = [{ key: "k1", name: "공고문.hwpx", updated_at: "2026-09-28T01:02:03Z" }, { key: "k2", path: "C:/x/깨짐.txt", error: "초안을 읽을 수 없습니다." }];
  const markup = render(controller);
  const empty = markup.slice(markup.indexOf('<div class="authoring-empty">'));
  assert.ok(empty.startsWith('<div class="authoring-empty"><p>HWPX·TXT 문서를 열거나 새 TXT를 만드세요.</p><div class="authoring-empty-actions"><button type="button" class="btn primary">문서 열기</button><button type="button" class="btn">새 TXT</button></div>'));
  assert.ok(empty.includes('<ul class="authoring-drafts" aria-label="복구 가능한 작업"><li><strong>공고문.hwpx</strong><time dateTime="2026-09-28T01:02:03Z">') || empty.includes('<ul class="authoring-drafts" aria-label="복구 가능한 작업"><li><strong>공고문.hwpx</strong><time datetime="2026-09-28T01:02:03Z">'));
  assert.ok(empty.includes('<strong>C:/x/깨짐.txt</strong><p role="alert">초안을 읽을 수 없습니다.</p>'));
  assert.ok(empty.includes('>초안과 원본 비교</button>') && empty.includes('>복구</button>') && empty.includes('>폐기</button>'));
  assert.ok(!markup.includes("변경할 문구를 선택해 필드로 만들어 보세요."), "첫 필드 안내는 빈 작업대의 문장이 아니다");
  assert.ok(!markup.includes("authoring-body"), "문서가 없으면 빈 편집면을 세우지 않는다");
  await controller.openFile();
  assert.deepEqual(calls.at(-1), { method: "open_authoring_document", args: ["", false] }, "「파일」 메뉴의 「문서 열기」와 같은 실행 경로");
});

test("#1025 §13: opening a general document shows Python's first-field notice once, and the next edit clears it", async () => {
  const hint = "변경할 문구를 선택해 필드로 만들어 보세요.";
  const { controller } = harness((action) => action === "update" ? { revision: 1 } : {}, {},
    (method) => method === "open_authoring_document" ? { session_id: "b", revision: 0, notice: hint } : null);
  await controller.activate("a");
  await controller.openFile();
  assert.equal(controller.viewModel.getSnapshot().notice, hint);
  controller.changed("b", "edited");
  assert.equal(controller.viewModel.getSnapshot().notice, "");
  await controller.flush("b");
});

// ---- UX-04 접근성: 키보드 모델·초점·live region·오류 수명·가용성 3상태의 순수 판정 ----
test("UX-04: rovingIndex wraps arrows along its axis and jumps with Home/End; other keys are not its business", () => {
  assert.equal(rovingIndex("ArrowRight", 0, 3, "horizontal"), 1);
  assert.equal(rovingIndex("ArrowRight", 2, 3, "horizontal"), 0, "감싸 돈다");
  assert.equal(rovingIndex("ArrowLeft", 0, 3, "horizontal"), 2);
  assert.equal(rovingIndex("Home", 2, 3, "horizontal"), 0);
  assert.equal(rovingIndex("End", 0, 3, "vertical"), 2);
  assert.equal(rovingIndex("ArrowDown", 1, 3, "vertical"), 2);
  assert.equal(rovingIndex("ArrowDown", 1, 3, "horizontal"), null, "가로 묶음의 ↓ 는 제 것이 아니다(select 의 값 변경으로 남는다)");
  assert.equal(rovingIndex("ArrowUp", 0, 3, "vertical"), 2);
  assert.equal(rovingIndex("Enter", 0, 3, "vertical"), null);
  assert.equal(rovingIndex("ArrowRight", 0, 0, "horizontal"), null);
});

test("UX-04: treeKey follows APG treeview — ↑↓ over visible rows, → expands then enters, ← collapses then climbs, Enter/Space select", () => {
  const rows = [
    { key: "slot", parent: null, expandable: true, expanded: true },
    { key: "option", parent: "slot", expandable: false, expanded: false },
    { key: "field", parent: null, expandable: true, expanded: false },
  ];
  assert.deepEqual(treeKey("ArrowDown", rows, "slot"), { focus: "option" });
  assert.deepEqual(treeKey("ArrowDown", rows, "field"), {}, "끝에서 멈춘다(감싸지 않는다)");
  assert.deepEqual(treeKey("ArrowUp", rows, "slot"), {});
  assert.deepEqual(treeKey("End", rows, "slot"), { focus: "field" });
  assert.deepEqual(treeKey("Home", rows, "field"), { focus: "slot" });
  assert.deepEqual(treeKey("ArrowRight", rows, "field"), { expand: "field" });
  assert.deepEqual(treeKey("ArrowRight", rows, "slot"), { focus: "option" });
  assert.deepEqual(treeKey("ArrowRight", rows, "option"), {}, "잎은 → 에 반응하지 않는다");
  assert.deepEqual(treeKey("ArrowLeft", rows, "option"), { focus: "slot" });
  assert.deepEqual(treeKey("ArrowLeft", rows, "slot"), { collapse: "slot" });
  assert.deepEqual(treeKey("ArrowLeft", rows, "field"), {});
  assert.deepEqual(treeKey("Enter", rows, "option"), { select: "option" });
  assert.deepEqual(treeKey(" ", rows, "field"), { select: "field" });
  assert.equal(treeKey("a", rows, "field"), null);
  assert.deepEqual(treeKey("ArrowDown", rows, "gone"), { focus: "slot" }, "초점 줄이 사라졌으면 처음으로");
});

test("UX-04: isCurrentTarget marks exactly the outline row Python located — whole field vs one occurrence vs slot vs option", () => {
  const occurrence = { entry: "s0", paragraph: 2, start: 4, end: 7 };
  const field = { name: "공고명", count: 2, occurrences: [occurrence, { entry: "s0", paragraph: 5, start: 0, end: 3 }] };
  assert.equal(isCurrentTarget("field", field, { ...field, kind: "field" }), true);
  assert.equal(isCurrentTarget("occurrence", { ...occurrence, name: "공고명" }, { ...field, kind: "field" }), false, "필드 전체 선택은 사용 위치 줄이 아니다");
  assert.equal(isCurrentTarget("occurrence", { ...occurrence, name: "공고명" }, { ...occurrence, name: "공고명", kind: "field" }), true);
  assert.equal(isCurrentTarget("field", field, { ...occurrence, name: "공고명", kind: "field" }), false);
  assert.equal(isCurrentTarget("occurrence", { ...field.occurrences[1], name: "공고명" }, { ...occurrence, name: "공고명", kind: "field" }), false);
  assert.equal(isCurrentTarget("slot", { id: "doc" }, { kind: "slot", slot_id: "doc" }), true);
  assert.equal(isCurrentTarget("slot", { id: "doc" }, { kind: "option", slot_id: "doc", option_id: "q" }), false);
  assert.equal(isCurrentTarget("option", { id: "q", slot_id: "doc" }, { kind: "option", slot_id: "doc", option_id: "q" }), true);
  assert.equal(isCurrentTarget("option", { id: "q", slot_id: "other" }, { kind: "option", slot_id: "doc", option_id: "q" }), false);
  assert.equal(isCurrentTarget("slot", { id: "doc" }, null), false);
});

test("UX-04: clampMenu keeps the context menu inside the window — flips above when the bottom is short, pins to the edges otherwise", () => {
  const viewport = { width: 800, height: 600 };
  assert.deepEqual(clampMenu({ x: 100, y: 100 }, { width: 200, height: 300 }, viewport), { left: 100, top: 100 });
  assert.deepEqual(clampMenu({ x: 100, y: 560 }, { width: 200, height: 300 }, viewport), { left: 100, top: 260 }, "아래가 모자라면 위로 뒤집는다");
  assert.deepEqual(clampMenu({ x: 700, y: 100 }, { width: 200, height: 100 }, viewport), { left: 596, top: 100 }, "오른쪽 끝에 붙는다");
  assert.deepEqual(clampMenu({ x: 10, y: 590 }, { width: 200, height: 700 }, viewport), { left: 10, top: 4 }, "창보다 크면 위 가장자리에서 시작한다");
  assert.deepEqual(clampMenu({ x: 100, y: 560, top: 535 }, { width: 200, height: 300 }, viewport), { left: 100, top: 235 }, "키보드로 연 메뉴는 그 줄의 윗변 위로 뒤집어 줄을 가리지 않는다");
});

test("UX-04: errors show their first sentence; the host label, later lines and a Hangul-free tail go under 자세히", () => {
  assert.deepEqual(errorParts("authoring/save: 파일을 쓸 수 없습니다. [Errno 13] Permission denied: 'C:/x.hwpx'"),
    { summary: "파일을 쓸 수 없습니다.", detail: "authoring/save\n[Errno 13] Permission denied: 'C:/x.hwpx'" });
  assert.deepEqual(errorParts("저장할 파일이 변경되었거나 이미 존재합니다. 다른 이름으로 저장하세요."),
    { summary: "저장할 파일이 변경되었거나 이미 존재합니다. 다른 이름으로 저장하세요.", detail: "" }, "사용자 안내 문장이 이어지면 그대로 보인다");
  assert.deepEqual(errorParts("편집기를 열 수 없습니다.\nTypeError: x is undefined\n    at mount (rhwp.js:1:2)"),
    { summary: "편집기를 열 수 없습니다.", detail: "TypeError: x is undefined\n    at mount (rhwp.js:1:2)" });
  assert.equal(errorText(new Error("문서가 변경되었습니다.")), "문서가 변경되었습니다.", "Error: 접두는 붙지 않는다");
  assert.equal(errorText("그대로"), "그대로");
});

test("UX-04: the error band keeps an error until it is dismissed or the same kind of work succeeds; errors raised inside the work stay", async () => {
  const { controller } = harness((action) => action === "save" ? { conflict: true } : {});
  await controller.activate("a");
  await controller.guarded(() => { throw new Error("authoring/impact: 영향을 확인할 수 없습니다. timeout"); });
  assert.equal(controller.viewModel.getSnapshot().error, "authoring/impact: 영향을 확인할 수 없습니다. timeout");
  await controller.guarded(async () => {}, "edit");
  await controller.guarded(async () => {}, "locate");
  assert.notEqual(controller.viewModel.getSnapshot().error, "", "키 입력·캐럿 이동이 읽히기 전의 경보를 지우지 않는다");
  const markup = render(controller);
  const band = markup.slice(markup.indexOf('<div class="authoring-error">'));
  assert.ok(band.startsWith('<div class="authoring-error"><p role="alert">영향을 확인할 수 없습니다.</p><details><summary>자세히</summary><pre>authoring/impact\ntimeout</pre></details><button type="button" class="btn">닫기</button></div>'));
  await controller.guarded(async () => {});
  assert.equal(controller.viewModel.getSnapshot().error, "", "같은 종류의 작업이 성공하면 걷힌다");
  // 작업 안에서 선 오류(저장 충돌)는 그 작업의 성공으로 지워지지 않는다.
  await controller.guarded(() => controller.save("a"), "save");
  assert.match(controller.viewModel.getSnapshot().error, /다른 이름으로 저장하세요/);
  await controller.guarded(async () => {}, "save");
  assert.equal(controller.viewModel.getSnapshot().error, "", "같은 종류(저장)의 재시도 성공");
  controller.fail(new Error("편집기 오류"), "editor");
  controller.dismissError();
  assert.equal(controller.viewModel.getSnapshot().error, "", "「닫기」로 걷힌다");
});

test("UX-10 R3: a trial-input validation failure shows only in the trial panel; the error band is for failed calls", async () => {
  const message = "'조건' 항목의 시험 선택을 지정하세요.";
  let hostFails = false;
  const { controller, snapshot } = harness((action, _payload, snap) => {
    if (action !== "trial") return {};
    if (hostFails) throw new Error("authoring/trial: 호출 실패");
    Object.assign(snap.tabs[0], { trial_state: "failed", trial_state_label: "시험 실패", trial_state_message: message });
    return { ok: false, message };
  });
  await controller.activate("a");
  controller.fail(new Error("이전 시험 오류"), "trial");
  await controller.guarded(() => controller.runTrial("a"), "trial");
  assert.equal(controller.viewModel.getSnapshot().error, "", "검증 실패는 오류 띠에 서지 않고, 이전 시험 오류 띠도 걷힌다");
  const markup = render(controller);
  const shown = message.replaceAll("'", "&#x27;");
  assert.ok(!markup.includes('<div class="authoring-error">'), "오류 띠 없음");
  assert.equal(markup.split(shown).length - 1, 1, "문장은 시험 패널 한 곳에만");
  assert.ok(markup.includes(`<p>${shown}</p>`), "시험 패널의 상태 문장(Python trial_state_message)");
  assert.ok(markup.includes('data-trial="failed">시험 실패</span>'), "상태 칩");
  assert.equal(snapshot.tabs[0].trial_state, "failed");
  hostFails = true;
  await controller.guarded(() => controller.runTrial("a"), "trial");
  assert.match(controller.viewModel.getSnapshot().error, /호출 실패/, "호출 실패만 오류 띠에 선다");
});

test("UX-10 R5: neighbouring unavailable menu items with the same reason show it once above the group; each keeps aria-describedby", async () => {
  const outside = "먼저 필드를 선택하세요.";
  const region = "먼저 항목이나 선택을 고르세요.";
  const verdicts = [
    { type: "create_field", enabled: true, reason: null, alternative: null },
    { type: "create_slot", enabled: true, reason: null, alternative: null },
    { type: "create_option", enabled: false, reason: "먼저 항목 안의 내용을 선택하세요.", alternative: { label: "먼저 항목 만들기", command_type: "create_slot" } },
    ...["rename_field", "relink_field", "unset_field"].map((type) => ({ type, enabled: false, reason: outside, alternative: null })),
    ...["rename_slot", "rename_option", "adjust_range", "unwrap", "delete", "duplicate", "move"].map((type) => ({ type, enabled: false, reason: region, alternative: null })),
  ];
  const groups = menuReasonGroups(verdicts);
  assert.deepEqual(groups.get("rename_field"), { id: "authoring-menu-reason-rename_field", reason: outside, lead: true, size: 3 });
  assert.deepEqual(groups.get("unset_field"), { id: "authoring-menu-reason-rename_field", reason: outside, lead: false, size: 3 });
  assert.equal(groups.get("move").id, "authoring-menu-reason-rename_slot");
  assert.equal(groups.get("create_option").size, 1, "대안이 곁에 선 항목은 혼자다");
  assert.equal(groups.has("create_field"), false);
  const { controller } = harness();
  await controller.activate("a");
  controller.update({ commands: verdicts });
  openContextMenu(controller, { clientX: 1, clientY: 1, target: { focus() {} }, preventDefault() {} }, null);
  const markup = render(controller);
  const menu = markup.slice(markup.indexOf('role="menu"'), markup.indexOf("</div>", markup.indexOf('role="menu"')));
  assert.equal(menu.split(outside).length - 1, 1, "무리의 사유는 한 번");
  assert.equal(menu.split(region).length - 1, 1);
  assert.ok(menu.includes('aria-label="필드 이름 변경" aria-disabled="true" aria-describedby="authoring-menu-reason-rename_field"><span id="authoring-menu-reason-rename_field" class="authoring-reason group-reason">먼저 필드를 선택하세요.</span>필드 이름 변경</button>'), "무리의 첫 항목 위");
  assert.ok(menu.includes('aria-label="필드 의미 해제" aria-disabled="true" aria-describedby="authoring-menu-reason-rename_field">필드 의미 해제</button>'), "나머지는 같은 줄을 가리킨다");
  assert.ok(menu.includes('aria-describedby="authoring-menu-reason-create_option"><span id="authoring-menu-reason-create_option" class="authoring-reason group-reason">먼저 항목 안의 내용을 선택하세요.</span>선택으로 만들기</button>'), "혼자인 사유도 같은 자리(윗줄)");
  assert.ok(!menu.includes("<p"), "메뉴의 자식은 menuitem 뿐이다");
});

test("UX-10 R2: a text-range selection opens a 선택한 문구 target card; the context line is Python's location label or nothing", async () => {
  const { controller } = harness();
  await controller.activate("a");
  controller.update({ panel: "properties", selected: null, selection: { entry: "s0", paragraph: 4, start_paragraph: 4, end_paragraph: 4, start: 6, end: 14 }, commandType: "create_field",
    context: { slot_id: "구분", option_id: null, location_label: "공고 구분 · 문단 5", selected_text: "{{수요기관}}" } });
  let markup = render(controller);
  assert.ok(markup.includes('<div class="authoring-target" id="authoring-properties-target"><span class="authoring-target-kind"><span class="authoring-kind">선택한 문구</span></span><p class="authoring-target-name quote" title="{{수요기관}}">{{수요기관}}</p></div>'));
  assert.ok(markup.includes('<p class="authoring-context" id="authoring-properties-context">공고 구분 · 문단 5</p>'));
  assert.match(markup, /<input class="field" list="authoring-existing-fields" aria-describedby="authoring-properties-target authoring-properties-context"/);
  assert.ok(!markup.includes("6–14"), "원시 offset 은 보이지 않는다");
  // 글자를 확정할 수 없는 범위는 종류만, 위치 라벨이 없으면 문맥 줄을 세우지 않고 설명도 가리키지 않는다.
  controller.update({ context: { slot_id: null, option_id: null, location_label: null, selected_text: null } });
  markup = render(controller);
  assert.ok(markup.includes('<div class="authoring-target" id="authoring-properties-target"><span class="authoring-target-kind"><span class="authoring-kind">선택한 문구</span></span></div>'));
  assert.ok(!markup.includes('id="authoring-properties-context"'));
  assert.match(markup, /<input class="field" list="authoring-existing-fields" aria-describedby="authoring-properties-target"/);
  // 캐럿(빈 범위)은 대상 카드가 없다.
  controller.update({ selection: { entry: "s0", paragraph: 4, start: 6, end: 6 } });
  assert.ok(!render(controller).includes("선택한 문구"));
});

test("UX-04: missing Python judgement is a third state — disabled with no reason, not enabled by guess", async () => {
  assert.deepEqual(commandAvailability([], "create_field"), { type: "create_field", enabled: false, pending: true, reason: null, alternative: null });
  assert.equal(commandAvailability(COMMAND_VERDICTS, "create_field").enabled, true);
  assert.equal(sharedReason([...SHARED_VERDICTS]), "먼저 문서에서 내용을 선택하세요.", "판정 없는 명령은 공유 사유를 깨지 않는다");
  const { controller } = harness();
  await controller.activate("a");
  const markup = render(controller);
  for (const label of ["필드로 만들기", "항목으로 만들기", "선택으로 만들기"])
    assert.match(markup, new RegExp(`<button type="button" class="btn quiet" disabled="" aria-disabled="true" data-rove="[a-z_]+" tabindex="-1">${label}</button>`), label);
  assert.ok(!markup.includes("확인 중</"), "판정 대기에 새 문구를 세우지 않는다");
  assert.ok(!markup.includes("authoring-reason"), "사유 문장이 없다");
});

test("UX-04: focusRequest numbers each request and names its panel; the context menu remembers the nearest focusable trigger", async () => {
  assert.deepEqual(focusRequest({}, "dock"), { focusTarget: "dock", focusPanel: 1 });
  assert.deepEqual(focusRequest({ focusPanel: 4 }, "properties"), { focusTarget: "properties", focusPanel: 5 });
  const { controller } = harness();
  await controller.activate("a");
  const row = { focus() {} };
  const span = { closest: (selector) => selector.includes('[role="treeitem"]') ? row : null };
  openContextMenu(controller, { clientX: 3, clientY: 4, target: span }, null);
  assert.equal(controller.viewModel.getSnapshot().contextMenu.trigger, row, "글자 span 이 아니라 그 줄이 trigger 다");
  assert.deepEqual(controller.viewModel.getSnapshot().contextMenu.anchor, { x: 3, y: 4 });
});

test("UX-04: liveStep speaks on transitions only — saves, readiness, trial results, commands, searches — and never repeats an alert", () => {
  const base = { id: "a", save: "저장하지 않은 변경", error: false, readiness: "ready", readinessText: "구조 오류 0개 · 경고 0개", trial: "untried", trialLabel: "시험 전",
    notice: "", command: 0, commandText: "", search: undefined, searchText: "" };
  let step = liveStep(null, base);
  assert.equal(step.message, "", "처음은 기준만 잡는다");
  const at = (patch) => { const next = liveStep(step.state, { ...base, ...step.state, ...patch }); step = next; return next.message; };
  assert.equal(at({ save: "편집 내용 반영 중" }), "", "키 입력의 반영 중 깜빡임은 읽지 않는다");
  assert.equal(at({ save: "저장하지 않은 변경" }), "");
  assert.equal(at({ save: "저장됨 · 사용 준비" }), "저장됨 · 사용 준비", "저장됨으로 바뀐 순간");
  assert.equal(at({ save: "저장하지 않은 변경", notice: "" }), "");
  assert.equal(at({ save: "저장됨 · 초안", notice: "초안은 저장되었습니다. 사용 전에 구조 오류 1개를 확인하세요." }), "초안은 저장되었습니다. 사용 전에 구조 오류 1개를 확인하세요.", "Python 의 알림이 있으면 그것");
  assert.equal(at({ save: "저장 실패", error: true }), "", "오류 띠(alert)가 읽는 실패는 되풀이하지 않는다");
  assert.equal(at({ save: "저장하지 않은 변경", error: false }), "");
  assert.equal(at({ save: "저장 실패", error: false }), "저장 실패");
  assert.equal(at({ readiness: "draft", readinessText: "사용 전에 구조 오류 1개를 확인하세요." }), "사용 전에 구조 오류 1개를 확인하세요.");
  assert.equal(at({ readinessText: "사용 전에 구조 오류 2개를 확인하세요." }), "", "상태가 같으면 수가 바뀌어도 읽지 않는다");
  assert.equal(at({ trial: "current", trialLabel: "현재 구성 통과" }), "현재 구성 통과");
  assert.equal(at({ trial: "stale", trialLabel: "마지막 시험 이후 변경됨" }), "");
  assert.equal(at({ trial: "current", trialLabel: "현재 구성 통과" }), "", "같은 결과의 자동 재시험");
  assert.equal(at({ trial: "failed", trialLabel: "시험 실패" }), "시험 실패");
  assert.equal(at({ command: 1, commandText: "필드로 만들기" }), "필드로 만들기");
  assert.equal(at({ command: 2, commandText: "필드로 만들기" }), "필드로 만들기", "같은 명령의 두 번째 적용도 읽는다");
  const summaries = [{ summary: "총 1건" }];
  assert.equal(at({ search: summaries, searchText: "총 1건" }), "총 1건");
  assert.equal(at({ search: summaries, searchText: "총 1건" }), "", "같은 검색 결과는 다시 읽지 않는다");
  assert.equal(liveStep(step.state, { ...base, id: "b", save: "저장됨" }).message, "", "문서를 바꾸면 기준만 다시 잡는다");
});

test("UX-04: the live text reuses Python's and the surface's existing words — undo names what it undid", async () => {
  const { controller } = harness();
  await controller.activate("a");
  const item = { id: "a", readiness: { state: "draft", errors: 1, warnings: 0, message: null } };
  assert.equal(saveLabel(item, {}, false), "저장됨 · 초안");
  assert.equal(liveState(item, { commandNote: { seq: 3, kind: "undo", label: "필드로 만들기" } }, false).commandText, "문서 실행 취소: 필드로 만들기");
  assert.equal(liveState(item, { commandNote: { seq: 4, kind: "redo", label: "" } }, false).commandText, "문서 다시 실행");
  assert.equal(liveState(item, {}, false).readinessText, "구조 오류 1개 · 경고 0개");
  assert.equal(liveState(item, { searchSummaries: [{ document: "a.txt", summary: "총 1건" }, { document: "b.txt", summary: "총 0건" }] }, false).searchText, "a.txt · 총 1건 · b.txt · 총 0건");
  controller.attach("a", { command: async () => {}, decorate() {} });
  controller.update({ lastCommandLabel: "항목으로 만들기" });
  await controller.command("undo");
  assert.deepEqual(controller.viewModel.getSnapshot().commandNote, { seq: 1, kind: "undo", label: "항목으로 만들기" });
});

test("UX-07/§10: an Escape forwarded from the editor iframe is a shell Escape (closes the properties panel); F6/Shift+F6 cycle panels", async () => {
  const { controller } = harness();
  await controller.activate("a");
  controller.update({ panel: "properties" });
  const iframe = inside(["iframe", ".authoring-editor-host", ".authoring-canvas"]);
  const escape = forwardedShellKey("Escape", iframe);
  assert.equal(shellShortcut(escape), "escape");
  assert.equal(escapeShell(controller), "panel");
  assert.equal(controller.viewModel.getSnapshot().panel, "", "편집면에서 온 Escape 도 셸 Escape 처럼 속성 패널을 닫는다");
  assert.equal(shellShortcut(forwardedShellKey("F6", iframe)), "cycle");
  assert.equal(forwardedShellKey("ShiftF6", iframe).shiftKey, true, "Shift+F6 은 거꾸로 돈다");
  assert.equal(forwardedShellKey("F2", iframe), null, "나머지 편집면 단축키는 기존 경로를 쓴다");
  const event = forwardedShellKey("Escape", iframe);
  assert.equal(event.target, iframe, "메뉴·패널이 초점을 돌려줄 자리는 편집면이다");
  assert.equal(event.nativeEvent.isComposing, undefined);
  event.preventDefault();
});

test("UX-04 × UX-08: F6 cycles the document tabs too and enters a roving group at its waiting item, not its first (tabindex=-1) control", async () => {
  const { cyclePanels, PANEL_CYCLE } = await import("../../frontend/src/screens/authoring_layout.ts");
  assert.equal(PANEL_CYCLE.split(",")[0], ".authoring-tabs", "문서 탭 줄이 순환의 첫 자리다");
  const focused = [];
  const panel = (name, entry) => ({
    name, contains: (node) => node === name, matches: () => false, getClientRects: () => ({ length: 1 }), focus() {},
    querySelector: (selector) => selector.includes('[tabindex="0"]') && !selector.includes(":not(")
      ? (entry ? { focus: () => focused.push(`${name}:${entry}`) } : null)
      : { focus: () => focused.push(`${name}:first`) },
  });
  const panels = [panel("tabs", "selected-tab"), panel("toolbar", "last-focused"), panel("outline", "current-row"), panel("canvas", null)];
  assert.equal(cyclePanels(panels, "tabs", false).name, "toolbar");
  assert.equal(cyclePanels(panels, "toolbar", false).name, "outline");
  assert.equal(cyclePanels(panels, "outline", false).name, "canvas");
  assert.equal(cyclePanels(panels, "canvas", false).name, "tabs");
  assert.deepEqual(focused, ["toolbar:last-focused", "outline:current-row", "canvas:first", "tabs:selected-tab"]);
});

/* ---------- IDE-01: 시험 공백 분리 · 상태 막대 입구 · F2 제자리 사유 · 비교 안 결정 ---------- */

test("IDE-01 P-03: the 결과 시험 tab badge counts Python's trial_missing, the 문제 badge counts problems; untouched inputs are aria-invalid", async () => {
  const { controller, snapshot } = harness();
  Object.assign(snapshot.tabs[0], { media: "txt", analysis: { fields: [{ name: "공고명", occurrences: [] }, { name: "기관", occurrences: [] }],
    slots: [{ id: "조건", label: "조건", options: [{ id: "국내", label: "국내" }] }] },
  problems: [], trial_missing: { fields: ["공고명"], slots: ["조건"] }, values: { 기관: "조달청" } });
  assert.equal(dockBadge(snapshot.tabs[0], "trial"), 2);
  assert.equal(dockBadge(snapshot.tabs[0], "problems"), 0);
  assert.equal(dockBadge({ problems: [{}, {}], trial_missing: { fields: [], slots: [] } }, "problems"), 2);
  assert.equal(dockBadge(snapshot.tabs[0], "search"), 0);
  await controller.activate("a");
  controller.update({ dock: "trial", trial: true });
  const markup = render(controller);
  assert.ok(markup.includes('aria-controls="authoring-dock-panel">결과 시험 <span class="authoring-badge">2</span></button>'), "시험 탭 배지 = 필드+선택 공백 수");
  assert.ok(markup.includes('id="authoring-dock-tab-problems" class="authoring-dock-tab" tabindex="-1" aria-selected="false">문제</button>'), "문제 0 이면 배지 없음");
  assert.ok(markup.includes('공고명<input class="field" aria-invalid="true" value=""/>'), "손대지 않은 필드 입력칸");
  assert.ok(markup.includes('기관<input class="field" value="조달청"/>'), "값이 있는 입력칸은 표지가 없다");
  assert.ok(markup.includes('<select class="field" aria-invalid="true">'), "시험 선택이 없는 항목");
  assert.ok(!markup.includes("미입력"), "폐기 어휘를 넓히지 않는다");
  assert.ok(markup.includes('<div class="authoring-actions start"><button type="button" class="btn">필드 이름 사용</button></div>'));
  Object.assign(snapshot.tabs[0], { trial_missing: { fields: [], slots: [] } });
  assert.ok(render(controller).includes('<button type="button" class="btn" disabled="">필드 이름 사용</button>'), "채울 필드가 없으면 비활성");
});

test("IDE-01 P-03: 필드 이름 사용 dispatches trial_fill_names behind the pending input, adopts Python's values and re-runs the automatic trial", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { controller, calls } = harness(async (action) => {
    if (action === "trial_input") { await gate; return {}; }
    if (action === "trial_fill_names") return { values: { 공고명: "공고명", 기관: "조달청" }, selected: {}, input_revision: 2 };
    return {};
  });
  await controller.activate("a");
  controller.update({ trial: true, autoTrial: true });
  const typing = controller.trialInput({ 기관: "조달청" }, {});
  const filling = controller.fillTrialNames();
  release();
  await Promise.all([typing, filling]);
  const order = calls.filter((call) => call.action === "trial_input" || call.action === "trial_fill_names").map((call) => call.action);
  assert.deepEqual(order, ["trial_input", "trial_fill_names"], "앞선 입력 전이 뒤에 선다");
  assert.deepEqual(calls.find((call) => call.action === "trial_fill_names"), { action: "trial_fill_names", session_id: "a", revision: 0 });
  assert.deepEqual(controller.viewModel.getSnapshot().values, { 공고명: "공고명", 기관: "조달청" });
  await new Promise((resolve) => setTimeout(resolve, 400));
  assert.ok(calls.some((call) => call.action === "trial"), "자동 갱신이 켜져 있으면 다시 시험한다");
});

test("IDE-01 P-15: F2 opens only a rename command Python enabled — the selection's kind first — and does nothing while pending", () => {
  const entry = (type, enabled, reason = null) => ({ type, enabled, reason, alternative: null });
  const refused = [entry("rename_field", false, "필드를 선택하세요."), entry("rename_option", false, "선택 영역을 선택하세요."), entry("rename_slot", false, "항목이나 선택 영역을 선택하세요.")];
  assert.equal(renameChoice([], "field"), null, "판정 전(pending)이면 아무것도 하지 않는다");
  assert.deepEqual(renameChoice(refused, undefined), { reason: "필드를 선택하세요." }, "종류가 없으면 필드 이름 변경의 사유");
  assert.deepEqual(renameChoice(refused, "option"), { reason: "선택 영역을 선택하세요." }, "선택 종류에 맞는 명령의 사유");
  const optionOpen = [entry("rename_field", false, "필드를 선택하세요."), entry("rename_option", true), entry("rename_slot", true)];
  assert.deepEqual(renameChoice(optionOpen, "option"), { open: "rename_option" }, "선택이 option 이고 rename_option 이 되면 그것");
  assert.deepEqual(renameChoice(optionOpen, "slot"), { open: "rename_slot" });
  assert.deepEqual(renameChoice(optionOpen, "field"), { open: "rename_option" }, "종류가 맞는 명령이 안 되면 되는 것 중 안쪽부터");
  assert.deepEqual(renameChoice([entry("rename_field", true), ...refused.slice(1)], undefined), { open: "rename_field" });
});

test("IDE-01 P-15: a refused F2 leaves the panel shut, sets the location-row note, announces it once, and the next caret move clears it", async () => {
  const commands = [{ type: "rename_field", enabled: false, reason: "필드를 선택하세요.", alternative: null },
    { type: "rename_option", enabled: false, reason: "선택 영역을 선택하세요.", alternative: null },
    { type: "rename_slot", enabled: false, reason: "항목이나 선택 영역을 선택하세요.", alternative: null }];
  const { controller } = harness((action) => action === "locate" ? { matches: [], commands } : action === "commands" ? { commands } : {});
  await controller.activate("a");
  controller.update({ commands, panel: "" });
  renameShortcut(controller);
  let view = controller.viewModel.getSnapshot();
  assert.equal(view.panel, "", "패널을 열지 않는다");
  assert.deepEqual(view.selectionNote, { message: "필드를 선택하세요." });
  assert.equal(view.live.text, "필드를 선택하세요.");
  const seq = view.live.seq;
  const markup = render(controller);
  assert.ok(markup.includes('<span class="authoring-selection-note" title="필드를 선택하세요.">필드를 선택하세요.</span></div><section class="authoring-canvas"'), "위치 줄 오른쪽 끝의 한 줄");
  controller.selection("a", { start: 0, end: 0 });
  await new Promise(setImmediate);
  view = controller.viewModel.getSnapshot();
  assert.equal(view.selectionNote, null, "다음 캐럿 이동에서 걷힌다");
  assert.equal(view.live.seq, seq, "걷을 때는 읽지 않는다");
  controller.update({ commands: [{ ...commands[0], enabled: true, reason: null }, commands[1], commands[2]], selected: { kind: "field", name: "공고명" } });
  renameShortcut(controller);
  view = controller.viewModel.getSnapshot();
  assert.equal(view.panel, "properties");
  assert.equal(view.commandType, "rename_field");
  assert.equal(view.focusTarget, "properties");
});

test("IDE-01 P-21: the 외부 파일 내용 comparison carries the alert's decision verbs — 다시 저장 is its primary only after a failed save", async () => {
  const { controller, snapshot } = harness();
  Object.assign(snapshot.tabs[0], { media: "txt", external_changed: true });
  await controller.activate("a");
  controller.update({ panel: "comparison", comparison: { content: "외부", current_content: "현재" } });
  const section = (text) => { const at = text.indexOf('aria-label="외부 파일 내용"'); return text.slice(at, text.indexOf("</section>", at)); };
  let markup = render(controller);
  assert.ok(section(markup).includes('<div class="authoring-actions"><button type="button" class="btn quiet">비교 닫기</button><button type="button" class="btn">현재 작업을 다른 이름으로 저장</button><button type="button" class="btn">외부 파일 다시 열기</button></div>'));
  assert.ok(!section(markup).includes("다시 저장</button>"));
  controller.update({ saveFailed: true });
  markup = render(controller);
  assert.ok(section(markup).includes('<button type="button" class="btn">외부 파일 다시 열기</button><button type="button" class="btn primary">다시 저장</button></div>'), "저장 실패면 다시 저장이 주 행동");
  Object.assign(snapshot.tabs[0], { external_changed: false });
  controller.update({ saveFailed: false });
  markup = render(controller);
  assert.ok(section(markup).includes('<div class="authoring-actions"><button type="button" class="btn quiet">비교 닫기</button></div>'), "결정할 일이 없으면 닫기만");
});

test("IDE-01: the location-row note is a generic in-place reason slot — severity chip, one announcement, cleared by Escape and by a caret move", async () => {
  const { controller } = harness((action) => action === "locate" ? { matches: [], commands: [] } : action === "commands" ? { commands: [] } : {});
  await controller.activate("a");
  controller.note("끝 표지가 없습니다.", "error");
  let view = controller.viewModel.getSnapshot();
  assert.deepEqual(view.selectionNote, { message: "끝 표지가 없습니다.", severity: "error" });
  assert.equal(view.live.text, "끝 표지가 없습니다.");
  const seq = view.live.seq;
  let markup = render(controller);
  assert.ok(markup.includes('<span class="authoring-selection-note" title="끝 표지가 없습니다." data-severity="error"><span class="authoring-badge" data-severity="error">오류</span> 끝 표지가 없습니다.</span>'), "심각도는 글자 칩으로도 선다");
  controller.update({});
  assert.equal(controller.viewModel.getSnapshot().live.seq, seq, "다시 그려도 다시 읽지 않는다");
  assert.equal(escapeShell(controller), "panel");
  assert.equal(controller.viewModel.getSnapshot().selectionNote, null, "Escape 가 걷는다");
  controller.note("다른 이름을 입력하세요.", "info");
  markup = render(controller);
  assert.ok(markup.includes('<span class="authoring-selection-note" title="다른 이름을 입력하세요." data-severity="info">다른 이름을 입력하세요.</span>'), "안내는 칩 없이 한 줄");
  controller.note("");
  assert.equal(controller.viewModel.getSnapshot().selectionNote.message, "다른 이름을 입력하세요.", "빈 문장은 세우지 않는다");
  controller.selection("a", { start: 3, end: 3 });
  await new Promise(setImmediate);
  assert.equal(controller.viewModel.getSnapshot().selectionNote, null, "캐럿 이동이 걷는다");
});
