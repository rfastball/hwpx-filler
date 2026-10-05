/* 「데이터로 필드 찾기」(#1156) — 실제 커밋 위에서 띠·구조 패널 줄·팝오버의 초점과 편집면 장식을 잰다. */
import test from "node:test";
import assert from "node:assert/strict";
import { settle, boot, hwpxTab, fire, press, named, focusOn } from "./authoring_dom.js";

const proposalTab = () => ({ ...hwpxTab(), trial_result: null, trial_state: "untried", analysis: { revision: 3, fields: [], slots: [] },
  proposal: { state: "ready", error: "", revision: 0, datasets: [{ key: "p1", name: "공고 목록" }],
    data: { pool_key: "p1", name: "공고 목록", sheet: null, row: 3, rows: [{ index: 3, label: "3행", hint: "값이 가장 많이 맞는 행 · 2개" }], rows_truncated: false },
    counts: { proposal: 1, held: 1 },
    groups: [
      { id: "g_price", kind: "proposal", name: "추정가격", column: "추정가격", columns: [], value: "170,309,180원", raw: "170309180",
        binding: { type: "amount", fmt: "{:,}", label: "천 단위 쉼표" }, reason: "", note: "", only: null, links_existing: false, count_text: "1곳",
        spots: [{ id: "s1", entry: "Contents/section0.xml", paragraph: 4, cell_path: null, start: 7, end: 18, where: "" }] },
      { id: "g_way", kind: "held", name: "입찰방식", column: "입찰방식", columns: [], value: "전자입찰", raw: "전자입찰",
        binding: { type: "text", fmt: "", label: "원문" }, reason: "문장 속 낱말과 같습니다. 같은 값 2곳이 모두 문장 속에 있습니다.", note: "", only: null,
        links_existing: false, count_text: "2곳",
        spots: [{ id: "s2", entry: "Contents/section0.xml", paragraph: 6, cell_path: null, start: 0, end: 4, where: "" },
          { id: "s3", entry: "Contents/section0.xml", paragraph: 8, cell_path: null, start: 2, end: 6, where: "" }] }],
    missing: [] } });
const proposalRow = (env, name) => env.container.querySelectorAll("button[data-proposal-row]").find((row) => row.textContent.startsWith(name));

test("#1156 keyboard: a proposal row opens the popover and focuses its first action; Escape closes it back to the row; ↓ roves the rows", async () => {
  const env = await boot(proposalTab());
  const editorMount = env.mounts.find((record) => record.spec.fileName === "a.hwpx");
  assert.deepEqual(editorMount.projection.proposals.map((spot) => [spot.label, spot.held]),
    [["필드 제안 추정가격: 170,309,180원", false], ["보류된 제안 입찰방식: 전자입찰", true], ["보류된 제안 입찰방식: 전자입찰", true]], "편집면 장식에 제안 자리가 실린다");
  const price = proposalRow(env, "추정가격");
  assert.equal(price.getAttribute("tabindex"), "0", "제안 줄 묶음은 한 번의 Tab 입구다");
  assert.equal(proposalRow(env, "입찰방식").getAttribute("tabindex"), "-1");
  focusOn(env, price);
  press(env, "ArrowDown");
  assert.equal(env.document.activeElement, proposalRow(env, "입찰방식"), "↓ 로 다음 줄");
  fire(env, proposalRow(env, "입찰방식"), "click");
  await settle();
  assert.deepEqual(editorMount.scrolled.map((target) => target.id), ["s2"], "그 묶음의 첫 자리로 편집면만 옮긴다");
  const dialog = named(env, "dialog", "입찰방식 제안");
  assert.ok(dialog, "팝오버가 선다");
  assert.equal(env.document.activeElement.textContent, "이 자리만 필드로", "보류의 첫 행동이 초점을 받는다(만들기 단추 없음)");
  assert.equal(proposalRow(env, "입찰방식").getAttribute("aria-pressed"), "true");
  assert.ok(dialog.textContent.includes("문장 속 낱말과 같습니다."), "보류 이유는 Python 문장 그대로");
  assert.ok(editorMount.projection.proposals.some((spot) => spot.open === "입찰방식"), "연 자리는 이름표 표지를 하나 더 싣는다");
  press(env, "Escape");
  await settle();
  assert.equal(named(env, "dialog", "입찰방식 제안"), undefined);
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
