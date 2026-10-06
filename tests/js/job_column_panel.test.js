/* 열 머리 패널의 「값 선택」(`job_column_panel.ts`, #1137) — 목록·체크는 Python 답 그대로다.
 *
 * 재는 것은 넷이다: ①Python 이 좁힌 목록(같은 열 부분일치가 배제한 값은 없다)과 체크를 그대로 그리는가
 * ②「(전체)」를 끄면 값 칸도 함께 꺼져 다음 누름이 뒤집히지 않는가(#1131 회귀) ③열린 패널을 새 답에
 * 맞출 때 입력 중인 부분일치 칸은 건드리지 않는가 ④값을 누른 뒤 도착한 옛 답은 버리는가. */
import test from "node:test";
import assert from "node:assert/strict";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  ColumnValues,
  createPanelRefresher,
  setAllBoxes,
  shouldReportPanelFailure,
  syncColumnPanel,
  valueChecked,
  valuesFromBoxes,
} from "../../frontend/src/screens/job_column_panel.ts";

const MEMO = "포함할 내용: 소기업·소상공인 / 고시 미만";

function controller(ui) {
  return {
    doc: { defaultView: null }, notify() {},
    uiModel: { subscribe: () => () => {}, getSnapshot: () => ui || {} },
    zone: async () => ({ ok: true }),
  };
}

const markup = (data) => renderToStaticMarkup(createElement(ColumnValues, {
  controller: controller(), column: "메모", data, onEdit() {},
}));

const box = (val, checked) => ({ dataset: { val }, checked });

test("값 목록은 Python 답 그대로 — 부분일치가 좁힌 목록에 「(전체)」와 맞는 값만 체크돼 선다", () => {
  // `filter_panel` 은 같은 열 부분일치 「소상공인」이 배제한 값을 싣지 않는다(FilterView.column_values).
  const html = markup({ text: "소상공인", checked: null, options: [MEMO] });
  assert.ok(/data-val-all="true" checked=""/.test(html), "「(전체)」 = 맞는 값 전부");
  assert.equal((html.match(/data-val="/g) || []).length, 1, "맞지 않는 값은 목록에 서지 않는다");
  assert.ok(html.includes(`data-val="${MEMO}" data-busy-lock="true" checked=""`));
  assert.ok(html.includes("값 선택(같은 열 안은 OR)") && html.includes("<b>(전체)</b>"));
});

test("체크 목록이 있으면 그 값만 켜지고 「(전체)」는 꺼진다 — (빈값)은 이름으로 그린다", () => {
  const html = markup({ checked: [""], options: ["가", ""] });
  assert.ok(!/data-val-all="true" checked=""/.test(html));
  assert.ok(/data-val="가" data-busy-lock="true"\/>/.test(html), "체크 안 된 값");
  assert.ok(/data-val="" data-busy-lock="true" checked=""\/>\(빈값\)/.test(html));
  assert.equal(valueChecked({ checked: null }, "x"), true);
  assert.equal(valueChecked({ checked: ["y"] }, "x"), false);
  assert.equal(valueChecked({}, "x"), false, "답이 없으면 켜지 않는다");
});

test("「(전체)」 끄기는 값 칸도 끈다 — 다음 누름은 고른 값 하나다(#1131 회귀)", () => {
  const boxes = [box("가", true), box("나", true), box("다", true)];
  assert.deepEqual(setAllBoxes(boxes, false), []);
  assert.deepEqual(boxes.map((b) => b.checked), [false, false, false]);
  boxes[1].checked = true;
  assert.deepEqual(valuesFromBoxes(boxes), ["나"], "남은 켜진 칸이 고른 값을 뒤집지 않는다");
  assert.equal(setAllBoxes(boxes, true), null);
  assert.equal(valuesFromBoxes(boxes), null, "칸이 모두 켜지면 「(전체)」");
});

function fakePanel(values, text) {
  const doc = { activeElement: null };
  const boxes = values.map(([val, checked]) => box(val, checked));
  const all = { checked: false };
  const input = { value: text, ownerDocument: doc };
  return {
    doc, boxes, all, input,
    querySelectorAll: (sel) => (sel === "input[data-val]" ? boxes : []),
    querySelector: (sel) => ({ "input[data-val-all]": all, "input[data-ctext]": input })[sel] || null,
  };
}

test("열린 패널을 새 답에 맞춘다 — 값 칸·「(전체)」·초점 밖 부분일치 칸", () => {
  const root = fakePanel([["가", true], ["나", true]], "소상");
  syncColumnPanel(root, { text: "", checked: ["나"] }, false);
  assert.deepEqual(root.boxes.map((b) => b.checked), [false, true]);
  assert.equal(root.all.checked, false);
  assert.equal(root.input.value, "", "「이 열 조건 지우기」가 지운 글자는 패널에도 남지 않는다");
  syncColumnPanel(root, { text: "", checked: null }, false);
  assert.deepEqual(root.boxes.map((b) => b.checked), [true, true]);
  assert.equal(root.all.checked, true);
  syncColumnPanel(null, { checked: null }, false);  // 닫힌 패널 — 아무것도 하지 않는다
});

test("입력 중인 부분일치 칸은 건드리지 않는다 — 초점이 있거나 보낼 글자가 대기 중이면", () => {
  const root = fakePanel([["가", false]], "소상공");
  root.doc.activeElement = root.input;
  syncColumnPanel(root, { text: "소상", checked: null }, false);
  assert.equal(root.input.value, "소상공", "초점 칸");
  assert.equal(root.boxes[0].checked, true, "값 칸은 그대로 맞춘다");
  root.doc.activeElement = null;
  syncColumnPanel(root, { text: "소상", checked: null }, true);
  assert.equal(root.input.value, "소상공", "대기 중인 입력");
});

test("다시 묻기: 값 누름 뒤 도착한 옛 답은 버리고, 실패는 숨기지 않는다", async () => {
  const resolvers = [];
  const applied = [];
  const failed = [];
  const refresher = createPanelRefresher({
    fetch: (column) => new Promise((resolve, reject) => resolvers.push({ column, resolve, reject })),
    apply: (column, data) => applied.push([column, data]),
    fail: (column, error) => failed.push([column, String(error)]),
  });
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
  refresher.refresh("메모");
  resolvers[0].resolve({ checked: null });
  await tick();
  assert.deepEqual(applied, [["메모", { checked: null }]]);
  refresher.refresh("메모");
  refresher.edited();                       // 묻는 사이 값 칸을 눌렀다
  resolvers[1].resolve({ checked: [] });
  await tick();
  assert.equal(applied.length, 1, "누름 전 물음의 답은 방금 누른 칸을 되돌리지 않는다");
  refresher.refresh("메모");                 // 그 누름의 push 가 다시 묻는다
  resolvers[2].resolve({ checked: ["가"] });
  await tick();
  assert.deepEqual(applied.at(-1), ["메모", { checked: ["가"] }]);
  refresher.refresh("메모");
  resolvers[3].reject(new Error("알 수 없는 열"));
  await tick();
  assert.deepEqual(failed, [["메모", "Error: 알 수 없는 열"]]);
});

test("늦게 도착한 실패는 그 열이 지금 열린 패널과 같을 때만 통보한다(#1139 회귀)", () => {
  // A 패널의 다시 묻기가 떠 있는 채 사용자가 B 를 열면, A 의 늦은 실패가 B 를 닫아선 안 된다.
  assert.equal(shouldReportPanelFailure({ column: "메모", data: null }, "메모"), true, "같은 열 — 통보·닫기");
  assert.equal(shouldReportPanelFailure({ column: "담당자", data: { options: [] } }, "메모"), false, "B 가 열린 뒤 도착한 A 의 실패");
  assert.equal(shouldReportPanelFailure(null, "메모"), false, "패널을 닫은 뒤 도착한 실패");
});
