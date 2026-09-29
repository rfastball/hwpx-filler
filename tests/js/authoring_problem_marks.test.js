import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createAuthoringController, problemNote } from "../../frontend/src/screens/authoring_controller.ts";
import { AuthoringScreen, markerPairs, problemAction, problemFix, txtProblemMarks } from "../../frontend/src/screens/authoring.ts";
import { lintpadDecorations, problemMarks, usableSpans } from "../../frontend/src/editorview/txt_lintpad.ts";

// 원인 자리 문제(IDE-05 #1051) — TXT 문제 밑줄의 별도 층, 표지 짝 강조, 위치 줄 메시지(problems_here).
// 판정(겹침·짝·심각도·문장)은 Python 이 준다. 여기서는 받은 것을 그리는지만 잰다.

function harness(handler = () => ({})) {
  const snapshot = { active_id: "a", tabs: [
    { id: "a", name: "a.txt", path: "a.txt", media: "txt", revision: 0, values: {}, selected: {} },
  ] };
  const calls = [];
  const client = {
    async dispatch(_screen, action, payload) {
      calls.push({ action, ...payload });
      return { ok: true, value: await handler(action, payload, snapshot) };
    },
    async invoke() { return { ok: true, value: null }; },
  };
  const controller = createAuthoringController({ client,
    runtime: { model: () => ({ getSnapshot: () => snapshot, subscribe: () => () => {} }), loadInitial: async () => {} },
    modal: { choose: async () => "save", prompt: async () => null, confirm: async () => true },
    navigation: { go() {}, refresh: async () => {} },
  });
  return { controller, calls, snapshot };
}
const render = (controller) => renderToStaticMarkup(createElement(AuthoringScreen, { controller }));
const settle = () => new Promise(setImmediate);

const DOC = "{{공고명}} {{공고 명}}\n{{#항목 a}}\n본문\n{{/항목}}\n";
// 줄 머리: 0(필드 둘) · 17(여는 표지, 줄바꿈 26) · 27(본문) · 30(닫는 표지, 줄바꿈 37) · 문서 길이 38

test("IDE-05: problem marks are their own layer — a problem over a field span keeps both, and the old span rule would have dropped it", () => {
  const spans = [{ kind: "field", start: 0, end: 7 }, { kind: "field", start: 8, end: 16 }, { kind: "marker", start: 17, end: 26 }];
  const problems = [
    { severity: "warning", start: 8, end: 16, message: "공백만 다른 필드 이름이 있습니다." },
    { severity: "error", start: 17, end: 27, message: "끝 표지가 없습니다." },
  ];
  // 전제: 필드 강조 배열에 섞으면 겹친 뒤 조각은 버려진다 — 그래서 별도 층이다.
  assert.equal(usableSpans([...spans, { kind: "field", start: 8, end: 16 }], DOC.length).length, 3);
  const drawn = lintpadDecorations(DOC, { spans, problems });
  assert.deepEqual(drawn.filter((item) => item.layer === "span").map(({ from, to, className }) => [from, to, className]),
    [[0, 7, "cm-txtField"], [8, 16, "cm-txtField"], [17, 26, "cm-txtMarker"]], "필드·표지 강조는 잘리지 않는다");
  assert.deepEqual(drawn.filter((item) => item.layer === "problem"), [
    { layer: "problem", from: 8, to: 16, className: "cm-authoring-problem-warning", title: "공백만 다른 필드 이름이 있습니다." },
    // 줄 전체 자리의 끝 줄바꿈은 밑줄이 설 글자가 아니다.
    { layer: "problem", from: 17, to: 26, className: "cm-authoring-problem-error", title: "끝 표지가 없습니다." },
  ]);
});

test("IDE-05: problemMarks clamps to the document, keeps overlapping problems, and skips unknown severities", () => {
  assert.deepEqual(problemMarks([
    { severity: "error", start: 3, end: 50, message: "b" },
    { severity: "warning", start: 0, end: 5, message: "a" },
    { severity: "미래", start: 0, end: 2, message: "x" },
    { severity: "error", start: 9, end: 12, message: "밖" },
  ], "0123456\n"), [
    { from: 0, to: 5, className: "cm-authoring-problem-warning", title: "a" },
    { from: 3, to: 7, className: "cm-authoring-problem-error", title: "b" },
  ]);
});

test("IDE-05: the paired marker line is lit only while the caret is on one of the pair's lines", () => {
  const pairs = markerPairs({ placements: [{ kind: "slot", start: 17, end: 38 }, { kind: "option" }] });
  assert.deepEqual(pairs, [{ open: 17, close: 37 }], "Python 배치의 여는 줄 머리와 닫는 줄의 마지막 글자 — 좌표가 없는 배치는 버린다");
  const pairLines = (caret) => lintpadDecorations(DOC, { pairs, caret }).filter((item) => item.layer === "pair").map((item) => [item.from, item.className]);
  assert.deepEqual(pairLines(20), [[30, "cm-authoring-pair"]], "여는 표지 줄 → 닫는 표지 줄");
  assert.deepEqual(pairLines(33), [[17, "cm-authoring-pair"]], "닫는 표지 줄 → 여는 표지 줄");
  assert.deepEqual(pairLines(28), [], "본문 줄에서는 서지 않는다");
});

test("IDE-05: TXT decorate hands the problems with a text location to the lintpad, whatever the mode", () => {
  assert.deepEqual(txtProblemMarks([
    { severity: "error", message: "끝 표지가 없습니다.", location: { line: 1, start: 17, end: 27 } },
    { severity: "warning", message: "보존", location: null },
    { severity: "warning", message: "문단", location: { entry: "s", paragraph: 2 } },
  ]), [{ severity: "error", start: 17, end: 27, message: "끝 표지가 없습니다." }]);
});

test("IDE-05: problemNote reads the first problem Python placed under the caret, with its severity", () => {
  const problems = [{ severity: "warning", message: "평문으로 남은 필드 표기입니다." }, { severity: "error", message: "끝 표지가 없습니다." }];
  assert.deepEqual(problemNote(problems, [1, 0]), { message: "끝 표지가 없습니다.", severity: "error", source: "problem" });
  assert.equal(problemNote(problems, []), null);
  assert.equal(problemNote(problems, undefined), null);
  assert.equal(problemNote(problems, [7]), null, "없는 순번은 세우지 않는다");
});

test("IDE-05: the caret entering a problem sets the location-row note (chip + Python sentence) once, moving inside keeps it, and leaving clears it", async () => {
  const at = { 20: [0], 22: [0], 29: [] };
  const { controller, snapshot } = harness((action, payload) => action === "locate" ? { matches: [], commands: [], problems_here: at[payload.selection.start] ?? [] } : action === "commands" ? { commands: [] } : {});
  snapshot.tabs[0].problems = [{ severity: "error", category: "structure", message: "끝 표지가 없습니다.", location: { line: 1, start: 17, end: 27 }, actions: [] }];
  await controller.activate("a");
  controller.selection("a", { start: 20, end: 20 });
  await settle(); await settle();
  let view = controller.viewModel.getSnapshot();
  assert.deepEqual(view.selectionNote, { message: "끝 표지가 없습니다.", severity: "error", source: "problem" });
  assert.equal(view.live.text, "끝 표지가 없습니다.");
  const seq = view.live.seq;
  assert.ok(render(controller).includes('<span class="authoring-selection-note" title="끝 표지가 없습니다." data-severity="error"><span class="authoring-badge" data-severity="error">오류</span> 끝 표지가 없습니다.</span>'));
  controller.selection("a", { start: 22, end: 22 });
  assert.equal(controller.viewModel.getSnapshot().selectionNote?.message, "끝 표지가 없습니다.", "같은 자리 안의 이동은 판정 전에도 깜박이지 않는다");
  await settle(); await settle();
  view = controller.viewModel.getSnapshot();
  assert.equal(view.selectionNote?.message, "끝 표지가 없습니다.");
  assert.equal(view.live.seq, seq, "같은 문제는 다시 읽지 않는다");
  controller.selection("a", { start: 29, end: 29 });
  await settle(); await settle();
  assert.equal(controller.viewModel.getSnapshot().selectionNote, null, "문제 자리를 떠나면 걷힌다");
});

test("IDE-05: a refused-F2 reason is not a problem note — the next caret move still clears it at once", async () => {
  const { controller } = harness((action) => action === "locate" ? { matches: [], commands: [], problems_here: [] } : {});
  await controller.activate("a");
  controller.note("필드를 고르세요.");
  controller.selection("a", { start: 3, end: 3 });
  assert.equal(controller.viewModel.getSnapshot().selectionNote, null);
});

test("IDE-05: choosing a problem row keeps the 문제 tab, moves the editor, and puts that problem in the location row", async () => {
  const problem = { severity: "warning", category: "authoring", message: "공백만 다른 필드 이름이 있습니다.", target: "공고 명",
    location: { line: 0, start: 8, end: 16 },
    actions: [{ label: "원문으로 이동", kind: "navigate", location: { line: 0, start: 8, end: 16 } },
      { label: "필드 연결 변경", kind: "command", command: { type: "relink_field", start: 8, end: 16, name: "공고명" } }] };
  const { controller, snapshot } = harness((action) => action === "locate" ? { matches: [], commands: [], problems_here: [0] }
    : action === "preview" ? { before: "{{공고 명}}", after: "{{공고명}}", content: "x", edits: [] } : {});
  snapshot.tabs[0].problems = [problem];
  await controller.activate("a");
  const focused = [];
  controller.attach("a", { decorate() {}, content: async () => DOC, focus: async (target) => { focused.push(target); } });
  controller.update({ panel: "problems" });
  await controller.select({ source_revision: 0, ...problem.location, target: problem.target }, { keepDock: true });
  let view = controller.viewModel.getSnapshot();
  assert.equal(view.panel, "problems", "독 활성 탭은 그대로 「문제」다");
  assert.deepEqual(focused.map(({ start, end }) => [start, end]), [[8, 16]]);
  assert.deepEqual(view.selectionNote, { message: "공백만 다른 필드 이름이 있습니다.", severity: "warning", source: "problem" });
  let markup = render(controller);
  assert.ok(markup.includes('<span class="authoring-problem-category">필드</span> 공백만 다른 필드 이름이 있습니다.'), "저작 문제의 종류 이름은 기존 「필드」");
  assert.ok(markup.includes('<span class="authoring-row-context">공고 명</span>'));
  // 명령 행동의 미리보기는 문제 탭 안의 「수정 제안」이고 확정 단추는 그 행동 이름이다.
  await controller.preview(problem.actions[1].command);
  view = controller.viewModel.getSnapshot();
  assert.deepEqual(problemFix(snapshot.tabs[0].problems, view.command), problem.actions[1]);
  markup = render(controller);
  assert.ok(markup.includes('<h3>수정 제안</h3><pre role="group" aria-label="변경 전">{{공고 명}}</pre><pre role="group" aria-label="변경 후">{{공고명}}</pre>'));
  assert.ok(markup.includes('<button type="button" class="btn primary">필드 연결 변경</button>'));
  assert.equal(problemFix(snapshot.tabs[0].problems, { type: "relink_field", start: 0, end: 7, name: "x" }), null, "문제 행동이 아닌 미리보기는 여기 서지 않는다");
});

test("IDE-05: a problem's command follows Python's confirm tier — 누름틀 변환 (none) applies at once, an enter-tier fix waits in 수정 제안 under its own name", async () => {
  const command = { type: "compile_token", entry: "Contents/section0.xml", paragraph_path: "/hs:sec/hp:p[5]", token_start: 12, name: "수요기관" };
  let tier = "none";
  const { controller, snapshot, calls } = harness((action) => action === "preview"
    ? { before: "{{수요기관}}", after: "[ 수요기관 ]", content: "변환본", edits: [], confirm: tier, label: "‘수요기관’ 누름틀 변환" } : action === "update" ? { revision: 1 } : {});
  const problem = { severity: "warning", category: "authoring", message: "평문으로 남은 필드 표기입니다.", target: "수요기관",
    location: { entry: "Contents/section0.xml", paragraph: 4, start: 12, end: 20 },
    actions: [{ label: "원문으로 이동", kind: "navigate" }, { label: "누름틀 변환", kind: "command", command }] };
  Object.assign(snapshot.tabs[0], { media: "hwpx", rhwp_editable: true, problems: [problem] });
  await controller.activate("a");
  const applied = [];
  let body = "원본";
  controller.attach("a", { decorate() {}, flush: async () => {}, content: async () => body, focus: async () => {},
    apply: async (content, _edits, label) => { applied.push([content, label]); body = content; } });
  controller.update({ panel: "problems" });
  let markup = render(controller);
  assert.ok(markup.includes('<span class="authoring-problem-category">필드</span> 평문으로 남은 필드 표기입니다.'));
  assert.ok(markup.includes('<button type="button" class="btn">누름틀 변환</button>'), "행 곁의 보조 단추");
  await problemAction(controller, snapshot.tabs[0], problem, problem.actions[1]);
  let view = controller.viewModel.getSnapshot();
  assert.deepEqual(applied, [["변환본", "compile_token"]], "확인 등급 none — 누르면 곧바로 바뀐다(한 번의 실행 취소)");
  assert.equal(view.preview, null, "수정 제안은 서지 않는다");
  assert.equal(view.panel, "problems", "문제 탭에 남는다");
  assert.equal(calls.filter((call) => call.action === "preview").length, 2, "확정 직전에 revision 을 다시 검사한다");
  tier = "enter";
  body = "원본";
  await problemAction(controller, snapshot.tabs[0], problem, problem.actions[1]);
  view = controller.viewModel.getSnapshot();
  assert.equal(applied.length, 1, "enter 등급은 확정 전까지 바꾸지 않는다");
  markup = render(controller);
  assert.ok(markup.includes('<pre role="group" aria-label="변경 후">[ 수요기관 ]</pre>'));
  assert.ok(markup.includes('<button type="button" class="btn primary">누름틀 변환</button>'));
});
