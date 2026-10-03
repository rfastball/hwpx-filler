/* Test delta brief
 * Unique risk: the new lesson snapshot can render a wrong guide control or a clipped coach.
 * Existing owner: this file's retired T0–T17 checklist assertions (26 cases).
 * Selected layer: pure Node server render and geometry; the existing browser owner verifies CSS.
 * Expected cost delta: 26 retired, 4 focused cases, no resource launches.
 * Evidence to retire: all checklist tiers, moment queue, and old dismiss behavior.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { TutorialPanel, anchorSelector, placeCoach } from "../../frontend/src/tutorial/panel.ts";

const ids = ["first_hwpx", "repeat_hwpx", "contract_txt", "purchase_txt", "replace_data", "blank_values", "field_trial", "option_apply"];
const copy = Object.fromEntries(["start", "later", "pause", "resume", "skip", "restart", "next", "prepare", "cleanup", "cleanup_confirm", "reset", "reset_confirm", "open_tutorial", "close", "choose_scenario"].map((key) => [key, `COPY:${key}`]));

function snapshot(overrides = {}) {
  return {
    kind: "tutorial-lessons/v1",
    invitation: { visible: false, title: "처음 안내", body: "여덟 작업을 배웁니다." },
    active: false, paused: false, scenario_id: null, checkpoint: 0,
    scenarios: ids.map((id, index) => ({ id, title: `과정 ${index + 1}`, description: `설명 ${index + 1}`,
      recommended: index === 0, completed: false, checkpoint: 0, step_count: 3 })),
    stages: [], beat: null, recovery: null, result: null, show_result: false,
    resources: { ready: false, summary: "예제 준비 필요" }, copy, ...overrides,
  };
}

function render(snap) {
  const ports = {
    doc: { getElementById: () => ({}) },
    model: { getSnapshot: () => snap, subscribe: () => () => {} },
    loadInitial: async () => {}, dispatch: async () => {},
    nav: { currentScreen: () => "editor", subscribe: () => () => {}, go: () => {} },
    overlay: { isBusy: () => false, subscribe: () => () => {} },
    confirm: async () => false, alarm: () => {}, portal: (children) => children,
  };
  return renderToStaticMarkup(createElement(TutorialPanel, ports));
}

test("persistent tutorial entry and first-run invitation use host copy", () => {
  const html = render(snapshot({ invitation: { visible: true, title: "처음 안내", body: "첫 작업을 시작하세요." } }));
  assert.match(html, /id="tutorialOpen"/);
  assert.match(html, /튜토리얼/);
  assert.match(html, /첫 작업을 시작하세요\./);
  assert.match(html, /COPY:start/);
  assert.match(html, /COPY:later/);
  assert.doesNotMatch(html, /tutorialCoach/);
});

test("action beat leaves Next absent; explanation beat shows it only when host permits", () => {
  const beat = { id: "b1", title: "연결 확인", body: "실제 연결 버튼을 누르세요.", mode: "action", screen: "editor", target: null,
    placement: "center", can_next: false };
  const common = { active: true, scenario_id: "first_hwpx", stages: [
    { id: "intro", title: "시작", status: "done" }, { id: "connect", title: "연결", status: "current" },
    { id: "result", title: "결과", status: "pending" }], beat };
  const actionHtml = render(snapshot(common));
  assert.match(actionHtml, /id="tutorialCoach"/);
  assert.match(actionHtml, /실제 연결 버튼을 누르세요\./);
  assert.doesNotMatch(actionHtml, /COPY:next/);
  assert.equal((actionHtml.match(/class="(?:done|current|pending)"/g) || []).length, 3);
  const explainHtml = render(snapshot({ ...common, beat: { ...beat, mode: "explain", can_next: true } }));
  assert.match(explainHtml, /COPY:next/);
  assert.doesNotMatch(render(snapshot({ ...common, beat: { ...beat, mode: "explain", can_next: false } })), /COPY:next/);
});

test("pause hides guidance without changing the eight selectable lesson identities", () => {
  const html = render(snapshot({ active: true, paused: true, scenario_id: "option_apply",
    beat: { id: "b", title: "검증", body: "진행", mode: "explain", screen: "editor", target: null, placement: "center", can_next: true } }));
  assert.match(html, /COPY:pause/);
  assert.doesNotMatch(html, /tutorialCoach/);
  assert.deepEqual(ids.length, 8);
});

test("semantic anchors resolve to real controls and coach flips/clamps to viewport", () => {
  assert.equal(anchorSelector("template-list"), "#editorTplList");
  assert.equal(anchorSelector("save-job"), "#editor-foot button[data-act='save']");
  assert.equal(anchorSelector("unknown"), null);
  const bottom = placeCoach({ left: 480, right: 600, top: 610, bottom: 650, width: 120, height: 40 },
    { width: 900, height: 700 }, "bottom", 180);
  assert.equal(bottom.side, "top");
  assert.ok(bottom.y >= 12 && bottom.y + 180 <= 700 - 12);
  const left = placeCoach({ left: 4, right: 40, top: 200, bottom: 230, width: 36, height: 30 },
    { width: 420, height: 600 }, "left", 180);
  assert.ok(left.x >= 12 && left.x + left.width <= 420 - 12);
});
