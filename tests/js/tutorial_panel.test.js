/* Test delta brief
 * Unique risk: paused/completed lessons strand users; guidance disappears at route/modal boundaries.
 * Existing owner: this file and react_runtime's same-window tutorial surface probe.
 * Selected layer: Node render/action projection; modal focus and CSS stay in the existing WebView2 window.
 * Expected cost delta: three small Node cases, zero new resource launches.
 * Evidence to retire: constant lesson-count assertion and impossible active+paused fixture.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { TutorialPanel, anchorSelector, lessonAction, placeCoach } from "../../frontend/src/tutorial/panel.ts";

const ids = ["first_hwpx", "repeat_hwpx", "contract_txt", "purchase_txt", "replace_data", "blank_values", "field_trial", "option_apply"];
const copy = Object.fromEntries(["start", "later", "pause", "resume", "skip", "restart", "next", "prepare", "cleanup", "cleanup_confirm", "reset", "reset_confirm", "open_tutorial", "close", "choose_scenario", "practice", "exit", "return"].map((key) => [key, `COPY:${key}`]));

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

function render(snap, options = {}) {
  const ports = {
    doc: { getElementById: () => ({}) },
    model: { getSnapshot: () => snap, subscribe: () => () => {} },
    loadInitial: async () => {}, dispatch: async () => {},
    nav: { currentScreen: () => options.screen ?? "editor", subscribe: () => () => {}, go: () => {} },
    overlay: { isBusy: () => !!options.host, currentHost: () => options.host ?? null, subscribe: () => () => {} },
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
  const common = { active: true, practice: { active: true, return_screen: "job" }, scenario_id: "first_hwpx", stages: [
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

test("host pause retains an immediate resume and exit even though active is false", () => {
  const html = render(snapshot({ active: false, paused: true, practice: { active: true, return_screen: "library" }, scenario_id: "option_apply",
    recovery: { title: "중단", body: "현재 단계로 돌아오세요." },
    beat: { id: "b", title: "검증", body: "진행", mode: "explain", screen: "editor", target: null, placement: "center", can_next: true } }));
  assert.match(html, /COPY:pause/);
  assert.doesNotMatch(html, /tutorialCoach/);
  assert.match(html, /id="tutorialResume"/);
  assert.match(html, /현재 단계로 돌아오세요\./);
  assert.match(html, /id="tutorialExit"/);
  assert.match(html, /COPY:exit/);
  const ended = render(snapshot({ active: false, paused: true, scenario_id: "option_apply",
    practice: { active: false, return_screen: null }, stages: [{ id: "open", title: "열기", status: "done" }] }));
  assert.doesNotMatch(ended, /tutorialResume|tutorialCoach|tutorialExit|tutorial-hud-dots|tutorial-paused|COPY:pause/);
  assert.match(ended, /튜토리얼/);
});

test("completed lessons restart while a paused current lesson resumes", () => {
  const snap = snapshot({ paused: true, scenario_id: "first_hwpx" });
  assert.equal(lessonAction(snap.scenarios[0], snap), "resume");
  assert.equal(lessonAction({ ...snap.scenarios[0], completed: true }, snap), "restart");
  assert.equal(lessonAction(snap.scenarios[1], snap), "select");
  const result = { title: "첫 문서 완료", body: "결과를 확인하세요.", count: 3, screen: "job", target: "results", documents: [], actions: [] };
  const next = render(snapshot({ show_result: true, result: { ...result, next_scenario_id: "repeat_hwpx", next_scenario_label: "저장한 작업 다시 쓰기" } }));
  assert.match(next, /id="tutorialNextCourse"/);
  assert.match(next, /저장한 작업 다시 쓰기/);
  const last = render(snapshot({ show_result: true, result }));
  assert.doesNotMatch(last, /id="tutorialNextCourse"/);
  assert.match(last, /COPY:choose_scenario/);
});

test("host route guidance and preparation stay actionable without an anchor", () => {
  const beat = { id: "b", title: "서식 고르기", body: "편집기에서 서식을 고르세요.", mode: "action",
    screen: "editor", target: "template-list", placement: "right", can_next: false,
    guidance: { library: { body: "새 작업을 여세요.", target: "new-job", primary: { action: "navigate", screen: "editor", label: "새 작업" } } } };
  const html = render(snapshot({ active: true, beat }), { screen: "library" });
  assert.match(html, /새 작업을 여세요\./);
  assert.match(html, /id="tutorialPrimary"/);
  assert.doesNotMatch(html, /편집기에서 서식을 고르세요/);
  const lost = render(snapshot({ active: true, beat }), { screen: "authoring" });
  assert.match(lost, /id="tutorialReturn"/);
  assert.match(lost, /편집기에서 서식을 고르세요/);
  const prepare = render(snapshot({ active: true, beat: { ...beat, screen: null, target: "prepare-examples", primary: { action: "prepare_examples", label: "연습 파일 새로 준비" } } }));
  assert.match(prepare, /id="tutorialPrimary"/);
  assert.match(prepare, /연습 파일 새로 준비/);
});

test("relevant modal contains the guide and exit without another modal or click shield", () => {
  const host = { querySelector: () => null, matches: (selector) => selector.includes("#poolRegModal") };
  const html = render(snapshot({ active: true, practice: { active: true, return_screen: "library" },
    beat: { id: "data", title: "공고 시트", body: "연습 사본의 공고 시트를 고르세요.", mode: "action", screen: "editor", target: "data-picker", placement: "right", can_next: false } }), { host });
  assert.match(html, /tutorial-coach-inline/);
  assert.match(html, /id="tutorialDialogExit"/);
  assert.match(html, /연습 사본의 공고 시트를 고르세요/);
  assert.doesNotMatch(html, /role="dialog"|tutorial-shield|tutorial-scrim/);
});

test("semantic anchors resolve to real controls and coach flips/clamps to viewport", () => {
  assert.equal(anchorSelector("new-job"), "#jobCandNewWork, #libraryNewWork, #jobPickInLibrary");
  assert.equal(anchorSelector("template-list"), "#editorTplList");
  assert.equal(anchorSelector("save-job"), "#editor-foot button[data-act='save']");
  assert.equal(anchorSelector("row-filter"), "#jobTableHead .fico[data-col='메모']");
  assert.equal(anchorSelector("unknown"), null);
  const bottom = placeCoach({ left: 480, right: 600, top: 610, bottom: 650, width: 120, height: 40 },
    { width: 900, height: 700 }, "bottom", 180);
  assert.equal(bottom.side, "top");
  assert.ok(bottom.y >= 12 && bottom.y + 180 <= 700 - 12);
  const left = placeCoach({ left: 4, right: 40, top: 200, bottom: 230, width: 36, height: 30 },
    { width: 420, height: 600 }, "left", 180);
  assert.ok(left.x >= 12 && left.x + left.width <= 420 - 12);
});
