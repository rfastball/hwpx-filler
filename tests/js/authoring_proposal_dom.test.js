/* 「데이터로 필드 찾기」(#1156) — 실제 커밋 위에서 띠·구조 패널 줄·팝오버의 초점과 편집면 장식을 잰다. */
import test from "node:test";
import assert from "node:assert/strict";
import { settle, boot, hwpxTab, fire, press, named, focusOn, propsOf, installDom } from "./authoring_dom.js";

const proposalTab = () => ({ ...hwpxTab(), trial_result: null, trial_state: "untried", analysis: { revision: 3, fields: [], slots: [] },
  proposal: { state: "ready", error: "", revision: 0, datasets: [{ key: "p1", name: "공고 목록" }],
    data: { pool_key: "p1", name: "공고 목록", sheet: null, row: 3, rows: [{ index: 3, label: "3행", hint: "찾은 값이 가장 많은 행 · 2개" }], rows_truncated: false, rows_note: "" },
    counts: { proposal: 1, held: 1 },
    groups: [
      { id: "g_price", kind: "proposal", name: "추정가격", column: "추정가격", columns: [], value: "170,309,180원", raw: "170309180",
        binding: { type: "amount", fmt: "{:,}", label: "숫자" }, reason: "", note: "", only: null, links_existing: false, count_text: "1곳",
        spots: [{ id: "s1", entry: "Contents/section0.xml", paragraph: 4, cell_path: null, start: 7, end: 18, where: "" }] },
      { id: "g_way", kind: "held", name: "입찰방식", column: "입찰방식", columns: [], value: "전자입찰", raw: "전자입찰",
        binding: { type: "text", fmt: "", label: "" }, reason: "같은 값 2곳이 모두 문장 속에 있어 일반 낱말로 보입니다.", note: "", only: null, only_label: "이 자리만 필드로",
        links_existing: false, count_text: "2곳",
        spots: [{ id: "s2", entry: "Contents/section0.xml", paragraph: 6, cell_path: null, start: 0, end: 4, where: "" },
          { id: "s3", entry: "Contents/section0.xml", paragraph: 8, cell_path: null, start: 2, end: 6, where: "" }] }],
    missing: [] } });
const proposalRow = (env, name) => env.container.querySelectorAll("button[data-proposal-row]").find((row) => row.textContent.startsWith(name));

test("#1156 keyboard: a proposal row opens the popover and focuses its first action; Escape closes it back to the row; ↓ roves the rows", async () => {
  const env = await boot(proposalTab());
  const editorMount = env.mounts.find((record) => record.spec.fileName === "a.hwpx");
  assert.deepEqual(editorMount.projection.proposals.map((spot) => [spot.label, spot.held, typeof spot.token]),
    [["추정가격", false, "string"], ["입찰방식", true, "string"], ["입찰방식", true, "string"]], "편집면 장식에 제안 자리가 이름표(필드 이름)·자리 신원과 함께 실린다");
  const price = proposalRow(env, "추정가격");
  assert.equal(price.getAttribute("tabindex"), "0", "제안 줄 묶음은 한 번의 Tab 입구다");
  assert.equal(proposalRow(env, "입찰방식").getAttribute("tabindex"), "-1");
  focusOn(env, price);
  press(env, "ArrowDown");
  assert.equal(env.document.activeElement, proposalRow(env, "입찰방식"), "↓ 로 다음 줄");
  fire(env, proposalRow(env, "입찰방식"), "click");
  await settle();
  assert.deepEqual(editorMount.scrolled.map((target) => target.id), ["s2"], "그 묶음의 첫 자리로 편집면만 옮긴다");
  const dialog = named(env, "dialog", "입찰방식 보류");
  assert.ok(dialog, "팝오버가 선다");
  assert.equal(env.document.activeElement.textContent, "이 자리만 필드로", "보류의 첫 행동이 초점을 받는다(만들기 단추 없음)");
  assert.equal(proposalRow(env, "입찰방식").getAttribute("aria-expanded"), "true");
  assert.ok(dialog.textContent.includes("같은 값 2곳이 모두 문장 속에 있어 일반 낱말로 보입니다."), "보류 이유는 Python 문장 그대로");
  assert.deepEqual(editorMount.projection.proposals.filter((spot) => spot.open).map((spot) => spot.label), ["입찰방식"], "연 자리 하나가 강한 표지로 선다");
  press(env, "Escape");
  await settle();
  assert.equal(named(env, "dialog", "입찰방식 보류"), undefined);
  assert.equal(env.document.activeElement, proposalRow(env, "입찰방식"), "닫으면 초점은 연 줄로 돌아온다");
  assert.ok(!editorMount.projection.proposals.some((spot) => spot.open), "닫으면 이름표 표지도 걷힌다");
  env.root.unmount();
});

test("#1156 document: the caret entering a spot opens the popover beside it without taking focus; 그대로 두기 sends propose_dismiss", async () => {
  const env = await boot(proposalTab(), [], (action) => action === "locate" ? { matches: [], commands: [] } : {});
  const editorMount = env.mounts.find((record) => record.spec.fileName === "a.hwpx");
  const before = env.document.activeElement;
  env.flushSync(() => editorMount.spec.onSelectionChanged({ entry: "Contents/section0.xml", paragraph: 4, start_paragraph: 4, end_paragraph: 4, start: 9, end: 9 }, { left: 40, top: 50, bottom: 66 }));
  await settle();
  const dialog = named(env, "dialog", "추정가격 제안");
  assert.ok(dialog, "캐럿이 자리에 서면 팝오버가 선다");
  assert.equal(env.document.activeElement, before, "타자 중의 초점은 옮기지 않는다");
  fire(env, dialog.querySelector(".authoring-proposal-keep"), "click");
  await settle();
  assert.deepEqual(env.calls.filter((call) => call.action === "propose_dismiss").map((call) => call.group_id), ["g_price"]);
  assert.equal(named(env, "dialog", "추정가격 제안"), undefined, "행동 뒤 팝오버는 걷힌다");
  env.root.unmount();
});

test("#1156 band: 끄기 sends propose_off and returns focus to the toolbar; the band's region is named by its title", async () => {
  const env = await boot(proposalTab());
  const band = env.container.querySelector(".authoring-proposal-band");
  assert.equal(band.getAttribute("aria-labelledby"), "authoring-proposal-title");
  assert.equal(env.container.querySelector("#authoring-proposal-title").textContent, "데이터로 필드 찾기");
  const off = band.querySelector('[aria-label="데이터로 필드 찾기 끄기"]');
  focusOn(env, off);
  fire(env, off, "click");
  await settle();
  assert.deepEqual(env.calls.filter((call) => call.action === "propose_off").map((call) => call.session_id), ["a"]);
  assert.ok(env.document.activeElement.closest(".authoring-toolbar"), "띠가 걷히면 초점은 도구 막대로");
  env.root.unmount();
});

test("#1156 busy: the band's selects and make-all are aria-disabled (never disabled, so focus stays) and ignore input while working", async () => {
  const env = await boot(proposalTab());
  const row = env.container.querySelector("#authoring-proposal-row");
  focusOn(env, row);
  env.flushSync(() => env.controller.update({ proposalBusy: true }));
  await settle();
  const busyRow = env.container.querySelector("#authoring-proposal-row");
  assert.deepEqual([busyRow.getAttribute("aria-disabled"), busyRow.hasAttribute("disabled")], ["true", false]);
  assert.equal(env.document.activeElement, busyRow, "초점을 쥔 칸이 그대로 초점을 쥔다");
  env.flushSync(() => propsOf(busyRow).onChange({ target: { value: "3" } }));
  propsOf(env.container.querySelector("#authoring-proposal-data")).onChange({ target: { value: "p1" } });
  const primary = env.container.querySelector(".authoring-proposal-band .btn.primary");
  assert.deepEqual([primary.getAttribute("aria-disabled"), primary.hasAttribute("disabled")], ["true", false]);
  fire(env, primary, "click");
  await settle();
  assert.deepEqual(env.calls.filter((call) => call.action === "propose_fields" || call.action === "propose_make_all"), [], "맞춰 보는 동안 입력은 무시된다");
  env.root.unmount();
});

test("#1156 focus: 그대로 두기 inside a document popover moves focus to the next panel row once Python drops the group; with no rows left it goes to the band title", async () => {
  const env = await boot(proposalTab(), [], (action) => action === "locate" ? { matches: [], commands: [] } : {});
  const editorMount = env.mounts.find((record) => record.spec.fileName === "a.hwpx");
  env.flushSync(() => editorMount.spec.onSelectionChanged({ entry: "Contents/section0.xml", paragraph: 4, start_paragraph: 4, end_paragraph: 4, start: 9, end: 9 }, { left: 40, top: 50, bottom: 66 }));
  await settle();
  const keep = named(env, "dialog", "추정가격 제안").querySelector(".authoring-proposal-keep");
  focusOn(env, keep);
  fire(env, keep, "click");
  await settle();
  const next = JSON.parse(JSON.stringify(env.snapshot()));
  next.tabs[0].proposal.groups = next.tabs[0].proposal.groups.slice(1);
  next.tabs[0].proposal.counts = { proposal: 0, held: 1 };
  await env.push(next);
  assert.equal(env.document.activeElement, proposalRow(env, "입찰방식"), "걷힌 줄의 차례에 선 다음 줄로");
  fire(env, proposalRow(env, "입찰방식"), "click");
  await settle();
  const only = named(env, "dialog", "입찰방식 보류").querySelector(".authoring-proposal-actions .btn");
  assert.equal(env.document.activeElement, only);
  fire(env, named(env, "dialog", "입찰방식 보류").querySelector(".authoring-proposal-keep"), "click");
  await settle();
  const empty = JSON.parse(JSON.stringify(env.snapshot()));
  empty.tabs[0].proposal.groups = [];
  empty.tabs[0].proposal.counts = { proposal: 0, held: 0 };
  await env.push(empty);
  assert.equal(env.document.activeElement, env.container.querySelector("#authoring-proposal-title"), "남은 줄이 없으면 띠 제목으로(몸통으로 떨어지지 않는다)");
  env.root.unmount();
});

test("#1156 focus: make-all moves focus to the band title when no proposal remains; the entry link hands focus to the band title", async () => {
  const command = { type: "create_fields", fields: [] };
  const env = await boot({ ...proposalTab(), proposal: null }, [], (action) => action === "propose_make_all" ? { content: "QUxM", edits: [], command, toast: "" }
    : action === "preview" ? { content: "QUxM", edits: [] } : action === "update" ? { revision: 1 } : {});
  const link = env.container.querySelector(".authoring-proposal-link");
  focusOn(env, link);
  fire(env, link, "click");
  await settle();
  await env.push({ ...env.snapshot(), tabs: [{ ...env.snapshot().tabs[0], proposal: proposalTab().proposal }] });
  assert.equal(env.document.activeElement, env.container.querySelector("#authoring-proposal-title"), "링크가 걷히면 초점은 띠 제목으로");
  const primary = env.container.querySelector(".authoring-proposal-band .btn.primary");
  focusOn(env, primary);
  fire(env, primary, "click");
  await settle();
  const done = JSON.parse(JSON.stringify(env.snapshot()));
  Object.assign(done.tabs[0].proposal, { revision: 1, counts: { proposal: 0, held: 1 }, groups: done.tabs[0].proposal.groups.slice(1) });
  await env.push(done);
  const title = env.container.querySelector("#authoring-proposal-title");
  assert.equal(env.container.querySelector(".authoring-proposal-band .btn.primary").textContent, "남은 제안 없음");
  assert.equal(env.document.activeElement, title, "주 행동이 「남은 제안 없음」으로 흐려지면 초점은 띠 제목으로");
  env.root.unmount();
});

test("#1156 popover anchor: a document popover hides while its caret line is out of view and returns beside it", async () => {
  const env = await boot(proposalTab(), [], (action) => action === "locate" ? { matches: [], commands: [] } : {});
  env.document.querySelector = (selector) => env.document.documentElement.querySelector(selector);
  env.document.defaultView.innerWidth = 1000;
  env.document.defaultView.innerHeight = 800;
  const editorMount = env.mounts.find((record) => record.spec.fileName === "a.hwpx");
  const caret = { entry: "Contents/section0.xml", paragraph: 4, start_paragraph: 4, end_paragraph: 4, start: 9, end: 9 };
  env.flushSync(() => editorMount.spec.onSelectionChanged(caret, null));
  await settle();
  const box = () => named(env, "dialog", "추정가격 제안");
  assert.equal(box().style.visibility, "hidden", "캐럿 줄을 아직 모르면(누르는 중) 엉뚱한 자리에 서지 않는다");
  const sent = editorMount.decorations;
  env.flushSync(() => editorMount.spec.onSelectionChanged(caret, { left: 40, top: 50, bottom: 66 }));
  await settle();
  assert.equal(box().style.visibility, "", "줄이 알려지면 그 곁에 선다");
  env.flushSync(() => editorMount.spec.onCaretRect(null));
  await settle();
  assert.equal(box().style.visibility, "hidden", "편집면 스크롤로 줄이 틀 밖에 나가면 숨는다");
  env.flushSync(() => editorMount.spec.onCaretRect({ left: 40, top: 90, bottom: 106 }));
  await settle();
  assert.equal(box().style.visibility, "");
  assert.equal(editorMount.decorations, sent, "같은 자리의 줄 이동은 장식을 다시 보내지 않는다");
  env.root.unmount();
});

test("#1156 TXT ghost tag: a decorative hole tag is aria-hidden; the #1148 labels keep being read", async () => {
  installDom();
  const { EditorState } = await import("@codemirror/state");
  const { markField, markEffects } = await import("../../frontend/src/editorview/txt_card_marks.ts");
  const tags = (marks) => {
    const state = EditorState.create({ doc: "추정가격", extensions: [markField] }).update({ effects: markEffects(marks) }).state;
    const out = [];
    state.field(markField).deco.between(0, state.doc.length, (_from, _to, value) => { out.push(value.spec.widget.toDOM()); });
    return out.map((element) => [element.textContent, element.getAttribute("aria-hidden")]);
  };
  assert.deepEqual(tags([{ start: 0, end: 0, className: "cm-authoring-proposal-tag", label: "추정가격", decorative: true }]), [["추정가격", "true"]]);
  assert.deepEqual(tags([{ start: 0, end: 0, className: "cm-txtHole", label: "이름" }]), [["이름", null]]);
});
