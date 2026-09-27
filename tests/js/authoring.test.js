import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createAuthoringController } from "../../frontend/src/screens/authoring_controller.ts";
import { AuthoringScreen, shellShortcut, appliedProperties, escapeStage, submitProperties, externalDocumentSpec, openContextMenu, escapeShell, problemAction } from "../../frontend/src/screens/authoring.ts";
import { TPL_STATUS_COPY } from "../../frontend/src/screens/job_run.ts";

// New owner: asynchronous authoring revision fences and close preservation.
// Headless Node only; Python tests own semantic edits and durable storage.
function harness(handler = () => ({}), modal = {}) {
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
  assert.match(palette, /<button type="button" class="btn sm" disabled="" aria-disabled="true" title="먼저 항목 안의 내용을 선택하세요\.">선택으로 만들기<\/button><p class="authoring-reason">먼저 항목 안의 내용을 선택하세요\.<\/p><button type="button" class="btn sm">먼저 항목 만들기<\/button>/);
  assert.ok(palette.includes('title="먼저 항목 안의 내용을 선택하세요."'), "도구 막대 버튼도 같은 사유를 단다");
  assert.ok(palette.includes('class="btn sm">필드로 만들기</button>'), "판정이 사용 가능이면 그대로 켜 둔다");
  controller.update({ panel: "properties", commandType: "create_option" });
  const properties = render(controller);
  assert.match(properties, /<option value="create_option" disabled="" title="먼저 항목 안의 내용을 선택하세요\."( selected="")?>선택으로 만들기<\/option>/);
  assert.ok(properties.includes('<p class="authoring-reason" role="status">먼저 항목 안의 내용을 선택하세요.</p>'));
  assert.ok(properties.includes(">먼저 항목 만들기</button>"));
  assert.match(properties, /<button class="btn sm" type="submit" disabled="" aria-disabled="true" title="[^"]+">변경 미리보기<\/button>/);
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
  assert.match(markup, /<div class="authoring-context-menu" role="menu" aria-label="문맥 명령" style="left:12px;top:34px">/);
  assert.ok(markup.includes('<button type="button" class="btn sm" role="menuitem">필드로 만들기</button>'));
  assert.ok(markup.includes('role="menuitem" disabled="" aria-disabled="true" title="먼저 항목 안의 내용을 선택하세요.">선택으로 만들기</button>'));
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
  assert.ok(markup.includes('<button type="button" class="btn sm primary">하위 의미 함께 해제</button>'));
  assert.ok(markup.includes(">취소</button>"));
});

test("U04/U07: preview detail renders counts·included·children·candidates·links_existing and the rename sentence", async () => {
  const { controller, snapshot } = harness((action, payload) => action === "preview" ? (payload.command.type === "rename_field"
    ? { affected: 4, before: "공고명", after: "사업명" }
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
  // 새 이름은 보낸 명령(view.command)에서 읽는다 — 문장 형식은 §13 그대로다.
  assert.match(render(controller), /<p>현재 문서의 사용 위치 4곳이 ‘사업명’으로 변경됩니다\.<\/p>/);
});

test("F24/F12/F13: problems drive the outline badges, the panel's text-only severity·category, and the action wiring", async () => {
  const { controller, snapshot } = harness();
  snapshot.tabs[0].analysis = { slots: [{ id: "doc", label: "문서", options: [{ id: "quote", label: "견적서" }] }], fields: [{ name: "공고명", count: 2, occurrences: [] }] };
  snapshot.tabs[0].problems = [
    { severity: "error", category: "structure", message: "선택 ‘견적서’의 범위가 항목 밖으로 나갑니다.", target: "quote", location: { start: 4, end: 9 }, actions: [{ label: "위치로 이동", kind: "navigate" }, { label: "구조 표기 수정", kind: "command", command: { type: "repair_marker", id: "quote" } }] },
    { severity: "warning", category: "trial_input", message: "시험값이 없습니다.", target: "공고명", location: null, actions: [] },
  ];
  snapshot.tabs[0].readiness = { state: "draft", errors: 1, warnings: 1, message: "" };
  await controller.activate("a");
  controller.update({ panel: "problems" });
  const markup = render(controller);
  assert.ok(markup.includes('견적서<span class="authoring-badge">문제 1</span></button>'));
  assert.ok(markup.includes('공고명 · 2<span class="authoring-badge">문제 1</span></button>'));
  assert.ok(!markup.includes('문서<span class="authoring-badge">'), "문제가 없는 항목에는 배지가 없다");
  assert.ok(markup.includes("<p><strong>오류</strong> · 구조 · quote</p><p>선택 ‘견적서’의 범위가 항목 밖으로 나갑니다.</p>"));
  assert.ok(markup.includes("<p><strong>경고</strong> · 시험 입력 · 공고명</p>"));
  assert.ok(markup.includes(">위치로 이동</button>") && markup.includes(">구조 표기 수정</button>"));
  assert.ok(markup.includes("<span>구조 오류 1개 · 경고 1개</span>") && markup.includes("<span>저장됨 · 초안</span>"));
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
  assert.ok(saved.includes('<p role="status" class="authoring-notice">초안은 저장되었습니다. 사용 전에 구조 오류 1개를 확인하세요.</p>'));
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
  assert.ok(markup.includes('<button type="button" class="btn sm" disabled="" aria-disabled="true" title="템플릿을 저장한 뒤 확인할 수 있습니다.">적용 영향 확인</button><p class="authoring-reason">템플릿을 저장한 뒤 확인할 수 있습니다.</p>'));
});

test("F26: 원문 표기 asks Python's syntax action and renders read-only sections with a copy button", async () => {
  const { controller, calls } = harness((action) => action === "syntax" ? { sections: [{ entry: "Contents/section0.xml", text: "{{공고명}}\n{{#특약}}…{{/특약}}" }], note: "HWPX 원문 표기는 읽기 전용" } : {});
  await controller.activate("a");
  await controller.raw();
  assert.deepEqual(calls.filter((call) => ["syntax", "content"].includes(call.action)).map((call) => call.action), ["syntax"]);
  const markup = render(controller);
  assert.ok(markup.includes('<section class="authoring-bottom" aria-label="원문 표기"><h2>원문 표기</h2><p>HWPX 원문 표기는 읽기 전용</p>'));
  assert.ok(markup.includes('<h3>Contents/section0.xml</h3><pre tabindex="0" aria-label="Contents/section0.xml 원문 표기">{{공고명}}'));
  assert.ok(markup.includes('class="btn sm">복사</button>'));
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
