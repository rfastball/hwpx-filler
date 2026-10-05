// 「데이터로 필드 찾기」(#1156) — 저작 작업대의 띠·표식·팝오버·구조 패널 묶음. 판정(등급·이유·이름·연결 열·표시 형식·자리)은
// Python 의 탭 투영 `proposal` 이 준다. 여기서는 받은 투영을 그대로 그리는지, 다섯 액션을 계약 모양으로 보내는지,
// 만든 결과를 편집기의 기존 한 단위로 얹는지만 잰다.
import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createAuthoringController } from "../../frontend/src/screens/authoring_controller.ts";
import { AuthoringScreen } from "../../frontend/src/screens/authoring.ts";
import { PROPOSAL_COPY, bandView, missingLines, outlineGroups, popoverView, proposalMarks, proposalSpots, spotAt } from "../../frontend/src/screens/authoring_proposal.ts";
import { proposalPlace } from "../../frontend/src/screens/authoring_proposal_view.ts";
import { DECORATION_LIMIT, fitMarkers, proposalMarkers } from "../../frontend/src/editorview/rhwp_marks.ts";

const SECTION = "Contents/section0.xml";
const CELL = [{ parent_paragraph: 9, control: 0, cell: 1, paragraph: 0 }];
const proposal = (patch = {}) => ({
  state: "ready", error: "", revision: 0,
  datasets: [{ key: "p1", name: "26년 하반기 공고 목록" }, { key: "p2", name: "계약 목록" }],
  data: { pool_key: "p1", name: "26년 하반기 공고 목록", sheet: null, row: 3,
    rows: [{ index: 3, label: "3행", hint: "값이 가장 많이 맞는 행 · 2개" }, { index: 7, label: "7행", hint: "맞는 값 1개" }], rows_truncated: false },
  counts: { proposal: 2, held: 1 },
  groups: [
    { id: "g_price", kind: "proposal", name: "추정가격", column: "추정가격", columns: [{ name: "현행가격", note: "‘현행가격’ 열도 같은 값입니다." }],
      value: "170,309,180원", raw: "170309180", binding: { type: "amount", fmt: "{:,}", label: "천 단위 쉼표" }, reason: "", note: "", only: null,
      source_text: "3행 ‘추정가격’ 열과 같은 값입니다.", links_note: "", only_label: null, links_existing: false, count_text: "1곳", spots: [{ id: "s1", entry: SECTION, paragraph: 4, cell_path: null, start: 7, end: 18, text: "170,309,180", where: "1. 나" }] },
    { id: "g_title", kind: "proposal", name: "공고명", column: "공고명", columns: [], value: "청사 보안", raw: "청사 보안",
      binding: { type: "text", fmt: "", label: "원문" }, reason: "", note: "", only: null, links_existing: true, count_text: "2곳",
      source_text: "3행 ‘공고명’ 열과 같은 값입니다.", links_note: "같은 이름 필드에 자리를 더합니다.", only_label: null,
      spots: [{ id: "s2", entry: SECTION, paragraph: 1, cell_path: null, start: 0, end: 5, where: "첫 문장" },
        { id: "s3", entry: SECTION, paragraph: 3, cell_path: null, start: 6, end: 11, where: "1. 가" }] },
    { id: "g_judge", kind: "held", name: "낙찰자결정방법", column: "낙찰자결정방법", columns: [], value: "적격심사", raw: "적격심사",
      binding: { type: "text", fmt: "", label: "원문" }, reason: "같은 값이 다른 곳에도 3번 나옵니다. 라벨 옆 1곳만 고를 수 있습니다.", note: "", only: "s4",
      source_text: "3행 ‘낙찰자결정방법’ 열과 같은 값입니다.", links_note: "", only_label: "표 칸 1곳만 필드로",
      links_existing: false, count_text: "4곳",
      spots: [{ id: "s5", entry: SECTION, paragraph: 12, cell_path: null, start: 3, end: 7, where: "" },
        { id: "s4", entry: SECTION, paragraph: 0, cell_path: CELL, start: 0, end: 4, where: "표 칸" }] },
  ],
  missing: [{ column: "품명", reason: "이 행에서 값이 비어 있습니다." }, { column: "비고", reason: "이 행에서 값이 비어 있습니다." },
    { column: "담당", reason: "문서에서 같은 값을 찾지 못했습니다." }],
  ...patch,
});

function harness(handler = () => ({}), tab = {}) {
  const snapshot = { active_id: "a", tabs: [
    { id: "a", name: "a.hwpx", path: "a.hwpx", media: "hwpx", rhwp_editable: true, revision: 0, values: {}, selected: {}, analysis: { fields: [], slots: [] }, ...tab },
  ] };
  const calls = [];
  const toasts = [];
  const picks = [];
  let pick = null;
  const client = {
    async dispatch(_screen, action, payload) {
      calls.push({ action, ...payload });
      return { ok: true, value: await handler(action, payload, snapshot) };
    },
    async invoke() { return { ok: true, value: null }; },
  };
  const controller = createAuthoringController({ client,
    runtime: { model: () => ({ getSnapshot: () => snapshot, subscribe: () => () => {} }), loadInitial: async () => {} },
    modal: { choose: async () => null, prompt: async () => null, confirm: async () => true },
    navigation: { go() {}, refresh: async () => {} },
    dataPicker: { open: async (options) => { picks.push(options); return pick; } },
    undo: { show: (message, undo, label) => toasts.push({ message, undo, label }) },
  });
  return { controller, calls, snapshot, toasts, picks, setPick: (value) => { pick = value; } };
}
const render = (controller) => renderToStaticMarkup(createElement(AuthoringScreen, { controller }));
const settle = () => new Promise(setImmediate);

function editor(log, body = { text: "원본" }) {
  return { decorate() {}, flush: async () => {}, content: async () => body.text, focus: async (target) => { log.push(["focus", target]); },
    scrollTo: async (target) => { log.push(["scroll", target.id]); return true; },
    apply: async (content, edits, label, expected) => { log.push(["apply", content, edits, label, expected]); body.text = content; },
    command: async (command) => { log.push(["command", command]); } };
}

test("#1156 band: ready shows Python's counts and the make-all verb; zero proposals dims it as 남은 제안 없음; working dims it with the working line", () => {
  const ready = bandView(proposal(), false);
  assert.equal(ready.message, "제안 2 · 보류 1");
  assert.deepEqual(ready.primary, { label: "제안 2개 모두 필드로", disabled: false });
  assert.deepEqual([ready.dataKey, ready.row, ready.hint], ["p1", "3", "값이 가장 많이 맞는 행 · 2개"]);
  assert.equal(ready.rows.length, 2);
  const none = bandView(proposal({ counts: { proposal: 0, held: 1 } }), false);
  assert.deepEqual(none.primary, { label: PROPOSAL_COPY.noneLeft, disabled: true });
  const working = bandView(proposal(), true);
  assert.equal(working.state, "working");
  assert.equal(working.message, "문서와 데이터를 맞춰 보는 중…");
  assert.equal(working.primary.disabled, true, "맞춰 보는 동안 주 행동은 흐리다");
  const empty = bandView(proposal({ state: "needs_data" }), false);
  assert.deepEqual([empty.message, empty.primary, empty.rows.length], ["먼저 데이터를 고르세요.", null, 0]);
  const failed = bandView(proposal({ state: "failed", error: "데이터를 읽을 수 없습니다." }), false);
  assert.deepEqual([failed.message, failed.failed, failed.primary], ["데이터를 읽을 수 없습니다.", true, null], "실패는 Python 문장 그대로이고 성공으로 낮추지 않는다");
});

test("#1156 outline: proposal and held rows carry Python's count text and the contract access names; missing columns group by reason", () => {
  const groups = outlineGroups(proposal());
  assert.deepEqual(groups.proposals.map((row) => [row.name, row.count, row.label]),
    [["추정가격", "1곳", "필드 제안 추정가격: 170,309,180원"], ["공고명", "2곳", "필드 제안 공고명: 청사 보안"]]);
  assert.deepEqual(groups.held.map((row) => [row.name, row.count, row.label]), [["낙찰자결정방법", "4곳", "보류된 제안 낙찰자결정방법: 적격심사"]]);
  assert.deepEqual(missingLines(proposal()), [
    { columns: "찾지 못한 열 · 품명, 비고", reason: "이 행에서 값이 비어 있습니다." },
    { columns: "찾지 못한 열 · 담당", reason: "문서에서 같은 값을 찾지 못했습니다." }]);
});

test("#1156 popover: Python's source line; format shows only when not 원문; equal-value columns make the head a column pick", () => {
  const price = popoverView(proposal(), { group: "g_price", spot: "s1" });
  assert.equal(price.source, "3행 ‘추정가격’ 열과 같은 값입니다.");
  assert.deepEqual([price.column, price.choices], ["추정가격", ["추정가격", "현행가격"]], "같은 값의 열이 있으면 머리가 열 고르기다");
  assert.equal(price.dialogLabel, "추정가격 제안");
  assert.deepEqual(price.format, { label: "천 단위 쉼표", raw: "170309180" });
  assert.deepEqual(price.columns, ["‘현행가격’ 열도 같은 값입니다."]);
  assert.deepEqual([price.make, price.only, price.same, price.reason], [true, null, null, ""], "한 자리 제안에는 「이 자리만」이 없다");
  const title = popoverView(proposal(), { group: "g_title", spot: "s3" });
  assert.equal(title.format, null, "원문은 표시형 줄을 세우지 않는다");
  assert.deepEqual(title.same, { text: "같은 값 2곳", where: "첫 문장, 1. 가" });
  assert.deepEqual(title.only, { label: "이 자리만", spot: "s3" });
  assert.equal(title.links, "같은 이름 필드에 자리를 더합니다.", "같은 이름 필드 주석은 Python 문장이다");
  assert.deepEqual(title.choices, [], "다른 열이 없으면 이름만 선다");
});

test("#1156 popover (held): no make verb, Python's reason, and the one allowed place — a table cell reads 표 칸 1곳만 필드로", () => {
  const held = popoverView(proposal(), { group: "g_judge", spot: "s5" });
  assert.deepEqual([held.held, held.make, held.reason], [true, false, "같은 값이 다른 곳에도 3번 나옵니다. 라벨 옆 1곳만 고를 수 있습니다."]);
  assert.deepEqual(held.only, { label: "표 칸 1곳만 필드로", spot: "s4" }, "고를 수 있는 자리는 Python 의 only 다");
  const loose = proposal();
  loose.groups[2] = { ...loose.groups[2], only: null, only_label: "이 자리만 필드로", reason: "문장 속 자리입니다." };
  assert.deepEqual(popoverView(loose, { group: "g_judge", spot: "s5" }).only, { label: "이 자리만 필드로", spot: "s5" }, "only 가 없으면 연 자리 하나");
  loose.groups[2] = { ...loose.groups[2], only_label: null };
  assert.equal(popoverView(loose, { group: "g_judge", spot: "s5" }).only, null, "Python 이 단추 이름을 주지 않으면 단추가 없다");
  assert.equal(popoverView(proposal(), { group: "gone", spot: "s1" }), null, "다시 계산되어 사라진 묶음은 그리지 않는다");
});

test("#1156 caret: only a collapsed caret inside a spot (same section, paragraph and cell) hits it; TXT compares offsets only", () => {
  const at = (start, end = start, extra = {}) => ({ entry: SECTION, paragraph: 4, start_paragraph: 4, end_paragraph: 4, start, end, ...extra });
  assert.deepEqual(spotAt(proposal(), at(9), "hwpx"), { group: "g_price", spot: "s1" });
  assert.deepEqual(spotAt(proposal(), at(18), "hwpx"), { group: "g_price", spot: "s1" }, "끝 경계도 그 자리다");
  assert.equal(spotAt(proposal(), at(9, 12), "hwpx"), null, "범위를 고르면 팝오버가 아니라 선택 옆 막대다");
  assert.equal(spotAt(proposal(), at(19), "hwpx"), null);
  assert.equal(spotAt(proposal(), { ...at(2), paragraph: 0, start_paragraph: 0, end_paragraph: 0 }, "hwpx"), null, "표 칸 밖 같은 문단 번호는 다른 자리다");
  assert.deepEqual(spotAt(proposal(), { ...at(2), paragraph: 0, start_paragraph: 0, end_paragraph: 0, cell_path: CELL }, "hwpx"), { group: "g_judge", spot: "s4" });
  assert.deepEqual(spotAt(proposal(), { start: 3, end: 3 }, "txt"), { group: "g_title", spot: "s2" });
  assert.equal(spotAt(proposal({ state: "working" }), at(9), "hwpx"), null, "준비 상태가 아니면 자리가 없다");
});

test("#1156 TXT marks: green and grey dotted spots carry the anchor token; only the open spot gets the face and the faint name tag", () => {
  const marks = proposalMarks(proposal(), { group: "g_title", spot: "s2" });
  assert.deepEqual(marks.slice(0, 3), [
    { start: 0, end: 0, className: "cm-authoring-proposal-tag", label: "공고명" },
    { start: 0, end: 4, className: "cm-authoring-proposal cm-authoring-proposal-held", token: "proposal:s4" },
    { start: 0, end: 5, className: "cm-authoring-proposal cm-authoring-proposal-open", token: "proposal:s2" }]);
  assert.equal(marks.filter((mark) => mark.label).length, 1, "이름표는 연 자리에만");
  assert.deepEqual(proposalMarks(proposal({ state: "needs_data" }), null), []);
});

test("#1156 HWPX marks: proposals and held are dotted underlines named by the access name; the open spot adds a field mark; the cap drops held, then proposals, then problems", () => {
  const spots = proposalSpots(proposal(), { group: "g_price", spot: "s1" });
  const marks = proposalMarkers([SECTION], spots);
  assert.deepEqual(marks.proposals.map((mark) => [mark.kind, mark.emphasis, mark.label]),
    [["problem", "subtle", "필드 제안 추정가격: 170,309,180원"], ["problem", "subtle", "필드 제안 공고명: 청사 보안"], ["problem", "subtle", "필드 제안 공고명: 청사 보안"]]);
  assert.deepEqual(marks.held.map((mark) => mark.label), ["보류된 제안 낙찰자결정방법: 적격심사", "보류된 제안 낙찰자결정방법: 적격심사"]);
  assert.deepEqual(marks.held[1].cellPath, [{ parentParagraph: 9, control: 0, cell: 1, paragraph: 0 }]);
  assert.deepEqual(marks.open.map((mark) => [mark.kind, mark.label, mark.startOffset, mark.endOffset]), [["field", "추정가격", 7, 18]]);
  const one = marks.proposals[0];
  const dropped = [];
  const base = Array.from({ length: DECORATION_LIMIT - 3 }, () => ({ ...one, kind: "field" }));
  const fitted = fitMarkers(base, { open: [], problems: [{ ...one, label: "문제" }], proposals: [one, one], held: [one] }, (kind, count) => dropped.push([kind, count]));
  assert.equal(fitted.length, DECORATION_LIMIT);
  assert.deepEqual(fitted.slice(-3).map((mark) => mark.label), ["문제", one.label, one.label], "문제가 먼저 들고 남은 자리를 제안이 쓴다");
  assert.deepEqual(dropped, [["held", 1]], "넘치면 보류부터 덜어 낸다");
  const crowded = [];
  fitMarkers(Array.from({ length: DECORATION_LIMIT }, () => one), { problems: [one], proposals: [one] }, (kind, count) => crowded.push([kind, count]));
  assert.deepEqual(crowded, [["problem", 1], ["proposals", 1]]);
});

test("#1156 popover place: below the spot's line (flipping above when short), beside the panel row, always inside the window", () => {
  const viewport = { width: 1000, height: 800 };
  assert.deepEqual(proposalPlace({ rect: { left: 100, top: 200, bottom: 220 }, side: "below" }, { width: 340, height: 200 }, viewport), { left: 100, top: 228 });
  assert.deepEqual(proposalPlace({ rect: { left: 100, top: 700, bottom: 720 }, side: "below" }, { width: 340, height: 200 }, viewport), { left: 100, top: 492 });
  assert.deepEqual(proposalPlace({ rect: { left: 240, top: 300, bottom: 328 }, side: "right" }, { width: 340, height: 200 }, viewport), { left: 248, top: 300 });
  assert.deepEqual(proposalPlace({ rect: { left: 900, top: 300, bottom: 328 }, side: "right" }, { width: 340, height: 200 }, viewport), { left: 656, top: 300 });
});

test("#1156 propose_fields: the entry dispatches fenced; picking a data set or a row re-dispatches with pool_key and row", async () => {
  const { controller, calls } = harness((action) => action === "propose_fields" ? { state: "ready" } : {});
  await controller.activate("a");
  await controller.proposal.find();
  await controller.proposal.chooseData("p2");
  const proposals = calls.filter((call) => call.action === "propose_fields");
  assert.deepEqual(proposals.map(({ action: _action, ...payload }) => payload), [{ session_id: "a", revision: 0 }, { session_id: "a", revision: 0, pool_key: "p2" }]);
  assert.equal(controller.viewModel.getSnapshot().proposalBusy, false);
});

test("#1156 propose_fields: a row pick keeps the data set; needs_data leads to the existing data picker once and asks again", async () => {
  const states = ["needs_data", "ready"];
  const env = harness((action) => action === "propose_fields" ? { state: states.shift() } : {});
  env.snapshot.tabs[0].proposal = proposal();
  await env.controller.activate("a");
  await env.controller.proposal.chooseRow(7);
  assert.deepEqual(env.calls.at(-1), { action: "propose_fields", session_id: "a", revision: 0, pool_key: "p1", row: 7 }, "시트가 없으면 싣지 않는다");
  assert.deepEqual(env.picks, [], "데이터가 있으면 고르기 창을 열지 않는다");
  states.splice(0, states.length, "needs_data", "ready");
  env.setPick("26년 하반기 공고 목록");
  await env.controller.proposal.find();
  assert.deepEqual(env.picks, [{ screen: "job" }], "「문서 작업」의 데이터 선택 창");
  assert.deepEqual(env.calls.filter((call) => call.action === "propose_fields").slice(-2).map(({ action: _action, ...payload }) => payload),
    [{ session_id: "a", revision: 0 }, { session_id: "a", revision: 0 }], "골랐으면 같은 길로 다시 묻는다");
  states.splice(0, states.length, "needs_data");
  env.setPick(null);
  await env.controller.proposal.find();
  assert.equal(env.picks.length, 2);
  assert.equal(env.calls.filter((call) => call.action === "propose_fields").length, 4, "취소하면 다시 묻지 않는다 — 띠가 다음 행동을 말한다");
});

test("#1156 caret: entering a spot opens its popover without moving focus; leaving or selecting a range closes it", async () => {
  const { controller, snapshot } = harness((action) => action === "locate" ? { matches: [], commands: [] } : {});
  snapshot.tabs[0].proposal = proposal();
  await controller.activate("a");
  const log = [];
  controller.attach("a", editor(log));
  const caret = (start, end = start) => controller.proposal.caret("a", { entry: SECTION, paragraph: 4, start_paragraph: 4, end_paragraph: 4, start, end }, { left: 10, top: 20, bottom: 36 });
  caret(9);
  assert.deepEqual(controller.viewModel.getSnapshot().proposalOpen, { group: "g_price", spot: "s1", origin: "spot", rect: { left: 10, top: 20, bottom: 36 }, focus: 0 });
  const markup = render(controller);
  assert.ok(markup.includes('role="dialog" aria-label="추정가격 제안"'), "비모달 대화상자 「이름 제안」");
  assert.ok(markup.includes('<p class="authoring-proposal-source">3행 ‘추정가격’ 열과 같은 값입니다.</p>'));
  assert.ok(markup.includes('<span>표시형</span><span class="authoring-proposal-fmt">천 단위 쉼표</span><span class="authoring-proposal-raw">데이터 값 <span class="mono">170309180</span></span>'));
  assert.ok(markup.includes('<button type="button" class="btn primary">필드로 만들기</button><button type="button" class="btn quiet authoring-proposal-keep">그대로 두기</button>'));
  assert.ok(markup.includes('aria-label="필드 제안 추정가격: 170,309,180원" aria-pressed="true" aria-haspopup="dialog" aria-expanded="true"'), "열린 묶음의 줄은 눌린 상태다");
  caret(10, 14);
  assert.equal(controller.viewModel.getSnapshot().proposalOpen, null, "범위 선택은 팝오버를 걷는다");
  caret(9);
  caret(30);
  assert.equal(controller.viewModel.getSnapshot().proposalOpen, null, "자리를 떠나면 걷힌다");
  assert.deepEqual(log, [], "문서에서 연 팝오버는 편집면 초점·선택을 건드리지 않는다");
});

test("#1156 panel row: opening scrolls the editor to the group's first spot (held → its allowed place) and asks for focus; the same row closes it", async () => {
  const { controller, snapshot } = harness();
  snapshot.tabs[0].proposal = proposal();
  await controller.activate("a");
  const log = [];
  controller.attach("a", editor(log));
  const row = { focused: 0, isConnected: true, focus() { this.focused += 1; } };
  await controller.proposal.openRow("g_judge", row);
  assert.deepEqual(log, [["scroll", "s4"]]);
  const open = controller.viewModel.getSnapshot().proposalOpen;
  assert.deepEqual([open.group, open.spot, open.origin, open.focus > 0], ["g_judge", "s4", "row", true]);
  await controller.proposal.openRow("g_judge", row);
  assert.equal(controller.viewModel.getSnapshot().proposalOpen, null, "같은 줄을 다시 누르면 닫는다");
  await controller.proposal.openRow("g_price", row);
  controller.proposal.close(true);
  assert.equal(row.focused, 1, "닫으면 초점이 그 줄로 돌아간다");
});

test("#1156 make: propose_make's result lands in the editor as one apply, then the content update; the toast carries Python's sentence and 실행 취소", async () => {
  let revision = 0;
  const command = { type: "create_field", name: "추정가격", entry: SECTION, paragraph: 4, start: 7, end: 18 };
  const { controller, snapshot, calls, toasts } = harness((action) => action === "propose_make"
    ? { content: "TkVX", edits: [], command, confirm: "none", toast: "‘추정가격’ 필드를 만들고 연결 초안에 열과 표시형을 넣었습니다." }
    : action === "preview" ? { content: "TkVX", edits: [] }
    : action === "update" ? { revision: ++revision } : {});
  snapshot.tabs[0].proposal = proposal();
  await controller.activate("a");
  const log = [];
  controller.attach("a", editor(log));
  controller.update({ proposalOpen: { group: "g_price", spot: "s1", origin: "spot", rect: null, focus: 0 } });
  await controller.proposal.make("g_price");
  assert.deepEqual(calls.find((call) => call.action === "propose_make"), { action: "propose_make", session_id: "a", revision: 0, group_id: "g_price" });
  assert.deepEqual(calls.find((call) => call.action === "preview"), { action: "preview", session_id: "a", revision: 0, command },
    "적용 사슬이 확정 직전에 같은 명령을 다시 미리 본다");
  assert.deepEqual(log, [["apply", "TkVX", [], "create_field", "원본"]], "편집기의 기존 한 단위(apply)에 기대 본문과 함께");
  assert.deepEqual(calls.filter((call) => call.action === "update").map((call) => call.content), ["TkVX"], "만든 본문이 Python 에 돌아간다");
  const view = controller.viewModel.getSnapshot();
  assert.deepEqual([view.proposalOpen, view.lastCommandLabel], [null, "필드로 만들기"]);
  assert.deepEqual(toasts.map(({ message, label }) => [message, label]), [["‘추정가격’ 필드를 만들고 연결 초안에 열과 표시형을 넣었습니다.", "실행 취소"]]);
  await toasts[0].undo();
  assert.deepEqual(log.at(-1), ["command", "undo"], "알림의 실행 취소는 편집기 실행 취소다");
  await controller.proposal.make("g_title", "s3");
  assert.deepEqual(calls.filter((call) => call.action === "propose_make").at(-1), { action: "propose_make", session_id: "a", revision: 1, group_id: "g_title", spot_id: "s3" });
  controller.changed("a", "사용자가 친 글");
  await settle(); await settle();
  const undos = log.filter((entry) => entry[0] === "command").length;
  await toasts[1].undo();
  assert.equal(log.filter((entry) => entry[0] === "command").length, undos, "그 뒤 문서가 바뀌었으면 알림은 아무것도 되돌리지 않는다");
});

test("#1156 make-all and dismiss: make-all is one apply with the contract sentence when Python sends none; dismiss and off are their own actions", async () => {
  const all = { type: "create_fields", fields: [] };
  const { controller, snapshot, calls, toasts } = harness((action) => action === "propose_make_all"
    ? { content: "QUxM", edits: [], command: all, label: "필드로 만들기", toast: "필드 2개를 만들고 연결 초안에 열과 표시형을 넣었습니다." }
    : action === "preview" ? { content: "QUxM", edits: [], label: "필드로 만들기" }
    : action === "update" ? { revision: 1 } : action === "propose_make" ? { refusal: { message: "문서가 바뀌었습니다." } } : {});
  snapshot.tabs[0].proposal = proposal();
  await controller.activate("a");
  const log = [];
  controller.attach("a", editor(log));
  await controller.proposal.makeAll();
  assert.deepEqual(calls.find((call) => call.action === "propose_make_all"), { action: "propose_make_all", session_id: "a", revision: 0 });
  assert.deepEqual(log, [["apply", "QUxM", [], "create_fields", "원본"]], "모두 필드로도 편집기 한 단위다");
  assert.equal(controller.viewModel.getSnapshot().lastCommandLabel, "필드로 만들기");
  assert.equal(toasts[0].message, "필드 2개를 만들고 연결 초안에 열과 표시형을 넣었습니다.");
  await assert.rejects(controller.proposal.make("g_price"), /문서가 바뀌었습니다/, "거절은 Python 문장 그대로 오류다");
  await controller.proposal.dismiss("g_judge");
  assert.deepEqual(calls.find((call) => call.action === "propose_dismiss"), { action: "propose_dismiss", session_id: "a", revision: 1, group_id: "g_judge" });
  await controller.proposal.off();
  assert.deepEqual(calls.find((call) => call.action === "propose_off"), { action: "propose_off", session_id: "a" });
});

test("#1156 surfaces: the band under the toolbar, the outline groups above the field list, and the entry link only while the band is off", async () => {
  const { controller, snapshot } = harness();
  await controller.activate("a");
  let markup = render(controller);
  assert.ok(markup.includes('<button type="button" class="authoring-proposal-link">데이터로 필드 찾기</button>'), "빈 필드 목록의 링크");
  assert.ok(!markup.includes("authoring-proposal-band"));
  snapshot.tabs[0].proposal = proposal();
  markup = render(controller);
  assert.ok(!markup.includes('class="authoring-proposal-link"'), "띠가 켜지면 링크는 걷힌다");
  assert.ok(markup.includes('<section class="authoring-proposal-band" role="region" aria-labelledby="authoring-proposal-title">'));
  assert.ok(markup.includes('<label for="authoring-proposal-data">데이터</label>'));
  assert.ok(markup.includes('<option value="7">7행</option>'));
  assert.ok(markup.includes('<span class="authoring-proposal-hint">값이 가장 많이 맞는 행 · 2개</span>'));
  assert.ok(markup.includes('<span class="authoring-proposal-status">제안 <b>2</b> · 보류 <b>1</b></span>'));
  assert.ok(markup.includes('<button type="button" class="btn primary">제안 2개 모두 필드로</button>'));
  assert.ok(markup.includes('aria-label="데이터로 필드 찾기 끄기"'));
  assert.ok(markup.indexOf("authoring-proposal-band") < markup.indexOf("authoring-outline"), "띠는 몸통 위(도구 막대 아래)다");
  assert.ok(markup.includes('<div class="authoring-proposal-group" id="authoring-proposal-group-held"><span>보류</span><span>1</span></div>'));
  assert.ok(markup.includes('<p class="authoring-proposal-missing">찾지 못한 열 · 품명, 비고<br/>이 행에서 값이 비어 있습니다.</p>'));
  assert.ok(markup.indexOf("authoring-proposal-list") < markup.indexOf("id=\"authoring-outline-structure-panel\""), "제안 묶음은 두 보기 위에 선다");
  snapshot.tabs[0].proposal = proposal({ counts: { proposal: 0, held: 1 }, groups: [proposal().groups[2]] });
  markup = render(controller);
  assert.ok(markup.includes('<p class="authoring-outline-empty">남은 제안이 없습니다.</p>'));
  assert.ok(markup.includes('<button type="button" class="btn primary" disabled="">남은 제안 없음</button>'));
  snapshot.tabs[0].proposal = proposal({ state: "needs_data" });
  markup = render(controller);
  assert.ok(markup.includes('<span class="authoring-proposal-status">먼저 데이터를 고르세요.</span>'));
  assert.ok(!markup.includes("authoring-proposal-list"), "준비 전에는 묶음이 서지 않는다");
});

test("#1156 entry: 데이터로 필드 찾기… sits in 더보기 and the palette, and is dimmed where the HWPX source cannot be edited", async () => {
  const { shellMenuActions } = await import("../../frontend/src/screens/authoring_shell_actions.ts");
  const { controller } = harness();
  const act = (work) => work;
  const entry = (item) => shellMenuActions({ controller, item, act, openPalette() {}, openPanel() {} }).moreActions.find(([label]) => label === "데이터로 필드 찾기…");
  assert.equal(entry({ media: "txt" })[2], false);
  assert.equal(entry({ media: "hwpx", rhwp_editable: true })[2], false);
  assert.equal(entry({ media: "hwpx", rhwp_editable: false })[2], true);
  assert.equal(entry(undefined)[2], true);
});

test("#1156 column pick: equal-value columns turn the popover head into a named select; choosing one sends propose_pick_column", async () => {
  const { controller, snapshot, calls } = harness((action) => action === "locate" ? { matches: [], commands: [] } : {});
  snapshot.tabs[0].proposal = proposal();
  await controller.activate("a");
  controller.attach("a", editor([]));
  controller.update({ proposalOpen: { group: "g_price", spot: "s1", origin: "spot", rect: null, focus: 0 } });
  const markup = render(controller);
  assert.ok(markup.includes('<select class="field authoring-proposal-field authoring-proposal-column" aria-label="필드 이름과 연결 열">'), "머리가 열 고르기다");
  assert.ok(markup.includes('<option value="추정가격" selected="">추정가격</option><option value="현행가격">현행가격</option>'));
  await controller.proposal.pickColumn("g_price", "현행가격");
  assert.deepEqual(calls.find((call) => call.action === "propose_pick_column"),
    { action: "propose_pick_column", session_id: "a", revision: 0, group_id: "g_price", column: "현행가격" });
  controller.update({ proposalOpen: { group: "g_title", spot: "s3", origin: "spot", rect: null, focus: 0 } });
  assert.ok(render(controller).includes('<span class="authoring-proposal-field">공고명</span>'), "다른 열이 없으면 이름만 선다");
});
