/* Test delta brief
 * Unique risk: paused/completed lessons strand users; guidance disappears at route/modal boundaries.
 * Existing owner: this file and react_runtime's same-window tutorial surface probe.
 * Selected layer: Node render/action projection; modal focus and CSS stay in the existing WebView2 window.
 * Expected cost delta: three small Node cases, zero new resource launches.
 * Evidence to retire: constant lesson-count assertion and impossible active+paused fixture.
 * Open panel body: one featured lesson owns the only primary action; rows, files and maintenance stay quiet.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { TutorialCoach, TutorialLessons, TutorialPanel, TutorialSpot, featuredAction, featuredLesson, lessonAction, pressFact } from "../../frontend/src/tutorial/panel.ts";
import { ANCHORS, SPAN_ANCHORS, anchorSelector } from "../../frontend/src/tutorial/anchors.ts";
import { createRevealer, measureTarget, placeCoach, pressMissesTarget, spotFrame, visibleRect, watchBoxedPress, watchMissedPress } from "../../frontend/src/tutorial/spotlight.ts";

const ids = ["first_hwpx", "change_apply", "contract_txt", "purchase_txt", "replace_data", "blank_values", "field_trial", "option_apply"];
const copy = Object.fromEntries(["start", "later", "pause", "resume", "skip", "restart", "next", "next_lesson", "cleanup", "cleanup_confirm", "reset", "reset_confirm", "open_tutorial", "close", "choose_scenario", "practice", "exit", "return"].map((key) => [key, `COPY:${key}`]));

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
});

test("the finale card offers only the next practice and leaving practice; the last lesson only leaves", () => {
  // #1136: no '결과 확인', no '과정 고르기', and the next lesson is not named on its button.
  const result = { title: "첫 문서 완료", body: "결과를 확인하세요.", count: 3, screen: "job", target: "results", documents: [] };
  const practice = { active: true, return_screen: "job" };
  const buttons = (html) => [...html.matchAll(/<section id="tutorialFinale".*?<\/section>/gs)].flatMap((card) =>
    [...card[0].matchAll(/<button[^>]*>([^<]*)<\/button>/g)].map((match) => match[1]));
  const next = render(snapshot({ practice, show_result: true, result: { ...result, next_scenario_id: "change_apply" } }));
  assert.deepEqual(buttons(next), ["COPY:next_lesson", "COPY:exit"]);
  assert.match(next, /id="tutorialNextCourse" type="button" class="btn primary sm"/);
  assert.doesNotMatch(next, /과정 2|COPY:choose_scenario/);
  const last = render(snapshot({ practice, show_result: true, result }));
  assert.deepEqual(buttons(last), ["COPY:exit"]);
  assert.match(last, /class="btn primary sm tutorial-exit"[^>]*>COPY:exit/);
  // Outside practice there is nothing to leave: the card only closes.
  assert.deepEqual(buttons(render(snapshot({ show_result: true, result }))), ["COPY:close"]);
});

test("a beat keeps its own words on another screen and offers only the way back to its screen", () => {
  // #1127 C3: no per-screen substitute text or box — the beat's text always describes the beat's own control.
  const beat = { id: "b", title: "서식 고르기", body: "편집기에서 서식을 고르세요.", mode: "action",
    screen: "editor", target: "template-row", arg: "a.hwpx", placement: "right", can_next: false };
  for (const screen of ["library", "authoring"]) {
    const html = render(snapshot({ active: true, beat }), { screen });
    assert.match(html, /id="tutorialReturn"/);
    assert.match(html, /편집기에서 서식을 고르세요/);
    assert.doesNotMatch(html, /tutorialPrimary/);
  }
});

test("relevant modal contains the guide and exit without another modal or click shield", () => {
  // The dialog is relevant exactly when the beat's boxed control is inside it.
  const host = { querySelector: (selector) => selector === "#sheetList input[data-sheet='공고']" ? {} : null, matches: () => false };
  const html = render(snapshot({ active: true, practice: { active: true, return_screen: "library" },
    beat: { id: "sheet", title: "공고 시트 체크", body: "연습 사본의 공고 시트를 고르세요.", mode: "action", screen: "editor", target: "sheet-check", arg: "공고", press: true, placement: "right", can_next: false } }), { host });
  assert.match(html, /tutorial-coach-inline/);
  assert.match(html, /id="tutorialDialogExit"/);
  assert.match(html, /연습 사본의 공고 시트를 고르세요/);
  assert.doesNotMatch(html, /role="dialog"|tutorial-shield|tutorial-scrim/);
});

test("semantic anchors resolve to real controls and coach flips/clamps to viewport", () => {
  assert.equal(anchorSelector("new-job"), "#libraryNewWork");
  assert.equal(anchorSelector("row-selection"), "#jobSelAll", "C7: never the first of a wider list");
  assert.equal(anchorSelector("filter-chip", "소상공인"), "#jobFilterChips button[data-preset='소상공인']");
  assert.equal(anchorSelector("authoring-range"), "#authoring-canvas .cm-tutorial-range");
  assert.deepEqual([...SPAN_ANCHORS], ["authoring-range"]);
  assert.equal(anchorSelector("map-confirm", "담당자 전화번호"),
    "#editor-body table.map tr[data-field='담당자 전화번호'] button[data-act='row-confirm']");
  assert.equal(anchorSelector("library-row", "it's"), "#libraryList button[data-work='it\\'s']");
  assert.equal(anchorSelector("map-confirm"), null, "a parameterised anchor without its parameter boxes nothing");
  assert.equal(anchorSelector("unknown"), null);
  for (const [key, selector] of Object.entries(ANCHORS)) {
    assert.ok(!selector.includes(","), `${key}: one selector, one control`);
  }
  const bottom = placeCoach({ left: 480, right: 600, top: 610, bottom: 650, width: 120, height: 40 },
    { width: 900, height: 700 }, "bottom", 180);
  assert.equal(bottom.side, "top");
  assert.ok(bottom.y >= 12 && bottom.y + 180 <= 700 - 12);
  const left = placeCoach({ left: 4, right: 40, top: 200, bottom: 230, width: 36, height: 30 },
    { width: 420, height: 600 }, "left", 180);
  assert.ok(left.x >= 12 && left.x + left.width <= 420 - 12);
});

function lessons(snap, options = {}) {
  const noop = () => {};
  return renderToStaticMarkup(createElement(TutorialLessons, { snapshot: snap, pending: false, practice: !!options.practice,
    run: noop, close: noop, act: noop, confirm: noop }));
}
// TutorialLessons is hook-free, so its element tree can be walked and a button's handler invoked directly.
function buttonById(node, id) {
  if (!node || typeof node !== "object") return null;
  if (Array.isArray(node)) { for (const child of node) { const hit = buttonById(child, id); if (hit) return hit; } return null; }
  if (node.props?.id === id) return node;
  return buttonById(node.props?.children, id);
}
function press(snap, id) {
  const calls = [];
  const tree = TutorialLessons({ snapshot: snap, pending: false, practice: false,
    run: (item, action) => calls.push([action, item.id]), close: () => calls.push(["close"]),
    act: (action) => calls.push([action]), confirm: (action) => calls.push([action]) });
  buttonById(tree, id).props.onClick();
  return calls;
}
const count = (html, pattern) => (html.match(pattern) || []).length;

test("open panel features the recommended lesson with the only primary action and quiet whole-row choices", () => {
  const html = lessons(snapshot());
  assert.match(html, /<h3 id="tutorialFeaturedTitle">과정 1<\/h3>/);
  assert.match(html, /설명 1/);
  assert.equal(count(html, /btn primary/g), 1);
  assert.match(html, /id="tutorialContinue"[^>]*>COPY:start</);
  assert.equal(count(html, /class="tutorial-row"/g), 7);
  assert.equal(count(html, /aria-label="과정 \d, COPY:choose_scenario"/g), 7);
  assert.doesNotMatch(html, />COPY:choose_scenario</);
  assert.equal(count(html, /과정 1</g), 1);
  assert.doesNotMatch(html, /★|✓|›|tutorial-recommended|COPY:resume|COPY:restart|COPY:pause|COPY:skip/);
  assert.match(html, /<svg[^>]*aria-hidden="true"/);
});

test("paused current lesson resumes from its step; completed rows reveal restart", () => {
  const snap = snapshot({ paused: true, scenario_id: "change_apply" });
  snap.scenarios[0] = { ...snap.scenarios[0], completed: true, checkpoint: 3 };
  snap.scenarios[1] = { ...snap.scenarios[1], checkpoint: 2 };
  snap.scenarios[3] = { ...snap.scenarios[3], checkpoint: 1 };
  assert.equal(featuredLesson(snap)?.id, "change_apply");
  const html = lessons(snap);
  assert.match(html, /tutorialFeaturedTitle">과정 2</);
  assert.match(html, /tutorial-progress">2\/3</);
  assert.match(html, /id="tutorialContinue"[^>]*>COPY:resume</);
  assert.equal(count(html, /btn primary/g), 1);
  assert.equal(count(html, />COPY:restart</g), 2);
  assert.doesNotMatch(html, /COPY:pause|COPY:skip/);
  const done = html.slice(html.indexOf('<li class="done"'));
  assert.match(done.slice(0, done.indexOf("</li>")), /<button type="button" class="tutorial-row">.*<svg.*과정 1.*tutorial-row-action">COPY:restart/);
  assert.match(html, /aria-label="과정 4, COPY:choose_scenario".*tutorial-progress">1\/3</);
  assert.equal(count(html, /1\/8</g), 1);
});

test("running lesson keeps pause and skip beside its featured continue, not in maintenance", () => {
  const snap = snapshot({ active: true, scenario_id: "contract_txt", checkpoint: 0 });
  const html = lessons(snap);
  const featured = html.slice(html.indexOf("tutorial-featured"), html.indexOf("</section>"));
  assert.match(featured, /tutorialFeaturedTitle">과정 3</);
  assert.match(featured, /tutorial-progress">0\/3</);
  assert.match(featured, />COPY:resume<.*>COPY:pause<.*>COPY:skip</);
  assert.doesNotMatch(featured, /COPY:restart/);
  const maintenance = html.slice(html.indexOf("tutorial-maintenance"));
  assert.doesNotMatch(maintenance, /COPY:pause|COPY:skip|COPY:resume/);
});

test("practice files sit behind a closed disclosure with names, paths stay copyable, no prepare control remains", () => {
  const files = [{ name: "물품 구매입찰 공고.hwpx", path: "C:\연습\물품 구매입찰 공고.hwpx", kind: "template" },
    { name: "공고목록.xlsx", path: "C:\연습\공고목록.xlsx", kind: "data" }];
  const snap = snapshot({ scenario_id: "first_hwpx", paused: true, resources: { ready: true, summary: "연습 파일 2건", files },
    recovery: { title: "확인", body: "연습 파일을 다시 확인하세요." } });
  const html = lessons(snap);
  assert.match(html, /<details class="tutorial-disclosure"><summary>/);
  assert.doesNotMatch(html, /<details[^>]*open/);
  assert.match(html, /<summary>.*연습 파일 2건<\/summary>/);
  assert.match(html, /<li title="C:\연습\공고목록\.xlsx"><span class="tutorial-file-name">공고목록\.xlsx<\/span><span class="tutorial-file-path">C:\연습\공고목록\.xlsx<\/span>/);
  assert.doesNotMatch(html, /<code|<strong/);
  assert.match(html, /tutorial-recovery">연습 파일을 다시 확인하세요\./);
  assert.doesNotMatch(html, /tutorialPrepare/);
  assert.match(html, /COPY:cleanup.*COPY:reset/);
  assert.equal(count(html, /tutorial-destructive/g), 2);
  const practice = lessons(snap, { practice: true });
  assert.doesNotMatch(practice, /tutorialPrepare/);
  assert.doesNotMatch(practice, /COPY:cleanup|COPY:reset/);
  const same = lessons(snapshot({ resources: { ready: false, summary: "예제 준비 필요" }, recovery: { title: "확인", body: "예제 준비 필요" } }));
  assert.equal(count(same, /예제 준비 필요/g), 1);
  assert.doesNotMatch(same, /<details/);
});

test("finished curriculum lists every lesson as a restart row without a featured action", () => {
  const snap = snapshot({ scenario_id: "option_apply" });
  snap.scenarios = snap.scenarios.map((item) => ({ ...item, completed: true, checkpoint: item.step_count }));
  assert.equal(featuredLesson(snap), null);
  const html = lessons(snap);
  assert.doesNotMatch(html, /tutorial-featured|btn primary/);
  assert.equal(count(html, />COPY:restart</g), 8);
  assert.match(html, /8\/8</);
});

test("re-running a completed lesson keeps it featured with pause and skip while it runs", () => {
  const snap = snapshot({ active: true, scenario_id: "contract_txt", checkpoint: 2 });
  snap.scenarios[2] = { ...snap.scenarios[2], completed: true, checkpoint: 2 };
  assert.equal(featuredLesson(snap)?.id, "contract_txt");
  assert.equal(featuredAction(snap.scenarios[2], snap), "close");
  const html = lessons(snap);
  const featured = html.slice(html.indexOf("tutorial-featured"), html.indexOf("</section>"));
  assert.match(featured, /tutorialFeaturedTitle">과정 3<.*tutorial-progress">2\/3</);
  assert.match(featured, /id="tutorialContinue"[^>]*>COPY:resume<.*>COPY:restart<.*>COPY:pause<.*>COPY:skip</);
  assert.equal(count(html, /과정 3</g), 1);
  assert.deepEqual(press(snap, "tutorialContinue"), [["close"]]);
});

test("a paused re-run of a completed lesson resumes from the featured block instead of restarting", () => {
  const snap = snapshot({ paused: true, scenario_id: "contract_txt", checkpoint: 2 });
  snap.scenarios[2] = { ...snap.scenarios[2], completed: true, checkpoint: 2 };
  assert.equal(lessonAction(snap.scenarios[2], snap), "restart");
  assert.equal(featuredAction(snap.scenarios[2], snap), "resume");
  const html = lessons(snap);
  assert.match(html, /tutorialFeaturedTitle">과정 3</);
  assert.match(html, /id="tutorialContinue"[^>]*>COPY:resume</);
  assert.doesNotMatch(html, /COPY:pause|COPY:skip/);
  assert.equal(count(html, /과정 3</g), 1);
  assert.deepEqual(press(snap, "tutorialContinue"), [["resume", "contract_txt"]]);
});

const box = (left, top, width, height) => ({ left, top, width, height, right: left + width, bottom: top + height });
const pickBeat = { id: "b", title: "고르기", body: "누르세요.", mode: "action", screen: "job", target: "row-selection", placement: "right", can_next: false };
const coachHtml = (overrides) => renderToStaticMarkup(createElement(TutorialCoach, { beat: pickBeat, copy, step: "", placement: null,
  inline: false, lost: false, overlayBusy: false, pending: false, swap: 0, missed: 0, exit: null, act: () => {}, recover: () => {}, ...overrides }));

test("spotlight hugs the control: small pad and the control's own radius grown by the same pad", () => {
  assert.deepEqual(spotFrame({ rect: box(100, 50, 120, 40), radius: 6 }), { x: 96, y: 46, width: 128, height: 48, radius: 10 });
  assert.equal(spotFrame({ rect: box(100, 50, 120, 40), radius: 0 }).radius, 4, "square control keeps a barely rounded ring");
  assert.equal(spotFrame({ rect: box(100, 50, 120, 40), radius: 999 }).radius, 24, "pill control stays a pill, never rounder");
  const html = renderToStaticMarkup(createElement(TutorialSpot, { target: { rect: box(100, 50, 120, 40), radius: 6 }, motionKey: "b1|row-selection", missed: 0, ring: false }));
  assert.match(html, /class="tutorial-spot" aria-hidden="true" data-dim="scrim"/);
  assert.match(html, /style="transform:translate\(96px, 46px\);width:128px;height:48px;border-radius:10px"/);
  assert.match(html, /class="tutorial-spot-pulse"/);
  assert.doesNotMatch(html, /data-glide|animation-delay/, "first appearance neither glides nor waits for a glide");
  const ring = renderToStaticMarkup(createElement(TutorialSpot, { target: { rect: box(10, 10, 40, 20), radius: 0 }, motionKey: "k", missed: 0, ring: true }));
  assert.match(ring, /data-dim="ring"/, "a dialog already dims the page; the spot adds only its ring");
});

test("coach takes the preferred side when it fits and its arrow points at the target's center", () => {
  const target = box(400, 200, 100, 40);
  const below = placeCoach(target, { width: 900, height: 700 }, "bottom", 160);
  assert.equal(below.side, "bottom");
  assert.equal(below.y, 258);
  assert.deepEqual(below.arrow, { left: 450 - below.x - 6 });
  const beside = placeCoach(target, { width: 900, height: 700 }, "right", 160);
  assert.equal(beside.side, "right");
  assert.equal(beside.x, 518);
  assert.deepEqual(beside.arrow, { top: 220 - beside.y - 6 });
  const edge = placeCoach(box(860, 20, 30, 30), { width: 900, height: 700 }, "bottom", 160);
  assert.deepEqual(edge.arrow, { left: edge.width - 28 }, "arrow clamps inside the card's rounded corner");
  const covered = placeCoach(box(0, 0, 900, 700), { width: 900, height: 700 }, "bottom", 160);
  assert.equal(covered.arrow, null, "a card clamped onto its target points nowhere rather than at the wrong place");
  const html = coachHtml({ step: "1 / 3", placement: beside });
  assert.match(html, new RegExp(`style="left:518px;top:${beside.y}px;width:320px".*data-side="right" data-swap="a"`));
  assert.match(html, new RegExp(`<i class="tutorial-coach-arrow" style="top:${beside.arrow.top}px" aria-hidden="true">`));
  assert.doesNotMatch(html, /data-nudge/);
  const inline = coachHtml({ inline: true, overlayBusy: true, swap: 1 });
  assert.match(inline, /class="tutorial-coach tutorial-coach-inline"[^>]*data-side="inline" data-swap="b"/);
  assert.doesNotMatch(inline, /tutorial-coach-arrow|style=/);
});

test("a press is a reportable fact only for the live press beat on its own screen", () => {
  const beat = { id: "sheet", title: "t", body: "b", mode: "action", screen: "editor", target: "sheet-check", arg: "공고",
    press: true, placement: "right", can_next: false };
  const live = { kind: "tutorial-lessons/v1", active: true, paused: false, scenario_id: "replace_data", checkpoint: 5, beat };
  assert.deepEqual(pressFact(live, "editor"), { scenario_id: "replace_data", checkpoint: 5, anchor: "sheet-check" });
  assert.equal(pressFact(live, "job"), null, "another screen");
  assert.equal(pressFact({ ...live, paused: true }, "editor"), null, "paused guidance");
  assert.equal(pressFact({ ...live, beat: { ...beat, press: false } }, "editor"), null, "a product-command beat");
  assert.equal(pressFact({ ...live, beat: { ...beat, mode: "explain" } }, "editor"), null);
  assert.equal(pressFact(null, "editor"), null);
});

test("only an activation of the boxed control is reported, never intercepted", () => {
  // #1127: a UI-only beat reports the fact "this beat's control was pressed"; the host decides the beat.
  const inner = {};
  const control = { disabled: false, getAttribute: (name) => name === "aria-disabled" ? control.dimmed : null,
    dimmed: null, getBoundingClientRect: () => box(0, 0, 40, 20), closest: () => null,
    contains: (node) => node === control || node === inner };
  const listeners = [];
  const doc = { querySelectorAll: (selector) => selector === "#boxed" ? [control] : [],
    addEventListener: (type, fn, capture) => listeners.push({ type, fn, capture }),
    removeEventListener: (type, fn) => listeners.splice(listeners.findIndex((entry) => entry.fn === fn), 1) };
  let presses = 0;
  const stop = watchBoxedPress(doc, "#boxed", () => { presses += 1; });
  assert.deepEqual(listeners.map(({ type, capture }) => [type, capture]), [["click", true]]);
  listeners[0].fn({ target: inner });
  listeners[0].fn({ target: {} });
  control.dimmed = "true";
  listeners[0].fn({ target: control });
  control.dimmed = null;
  control.disabled = true;
  listeners[0].fn({ target: control });
  assert.equal(presses, 1, "elsewhere, dimmed and disabled presses are not presses of the boxed control");
  stop();
  assert.equal(listeners.length, 0);
});

test("a press outside the ring nudges the coach without intercepting the press", () => {
  const frame = spotFrame({ rect: box(100, 50, 120, 40), radius: 6 });
  assert.equal(pressMissesTarget({ x: 150, y: 60 }, frame, false), false);
  assert.equal(pressMissesTarget({ x: 97, y: 47 }, frame, false), false, "the pad belongs to the target");
  assert.equal(pressMissesTarget({ x: 20, y: 300 }, frame, false), true);
  assert.equal(pressMissesTarget({ x: 20, y: 300 }, frame, true), false, "the coach, HUD and panel are never a miss");
  assert.equal(pressMissesTarget({ x: 20, y: 300 }, null, false), false);
  const listeners = [];
  const doc = { addEventListener: (type, fn, capture) => listeners.push({ type, fn, capture }),
    removeEventListener: (type, fn) => listeners.splice(listeners.findIndex((entry) => entry.fn === fn), 1) };
  let misses = 0;
  const stop = watchMissedPress(doc, frame, () => { misses += 1; });
  assert.deepEqual(listeners.map(({ type, capture }) => [type, capture]), [["pointerdown", true]]);
  const press = (x, y, extra = {}) => {
    let stopped = false;
    const halt = () => { stopped = true; };
    listeners[0].fn({ button: 0, clientX: x, clientY: y, target: { closest: () => null }, preventDefault: halt, stopPropagation: halt, ...extra });
    return stopped;
  };
  assert.equal(press(20, 300), false, "the product still receives the press");
  press(150, 60);
  press(20, 300, { button: 2 });
  press(20, 300, { target: { closest: (selector) => selector.includes("#tutorialCoach") ? {} : null } });
  assert.equal(misses, 1);
  const html = coachHtml({ missed: 1 });
  assert.match(html, /data-nudge="b"/);
  assert.match(coachHtml({ missed: 2 }), /data-nudge="a"/, "each further miss restarts the shake");
  assert.doesNotMatch(html, /role="alert"|aria-live="assertive"/, "no new announcement copy is invented for a nudge");
  stop();
  assert.equal(listeners.length, 0);
});

test("reduced motion keeps the guide opacity-only: no glide, pulse or shake", () => {
  const css = readFileSync(new URL("../../frontend/css/tutorial.css", import.meta.url), "utf8");
  const start = css.indexOf("@media(prefers-reduced-motion:reduce){");
  assert.ok(start > 0);
  const reduced = css.slice(start, css.indexOf("\n}", start));
  assert.match(reduced, /\.tutorial-spot,\.tutorial-spot\[data-glide\][^{]*\{transition:none\}/);
  assert.match(reduced, /\.tutorial-spot-pulse\{animation:none\}/);
  assert.match(reduced, /\.tutorial-coach\[data-nudge="a"\]\{animation-name:tutorialBlinkA\}/);
  assert.match(reduced, /\.tutorial-coach\[data-swap="a"\]\{animation-name:tutorialFadeA\}/);
  for (const name of ["tutorialBlinkA", "tutorialBlinkB", "tutorialFadeA", "tutorialFadeB"]) {
    const frames = css.match(new RegExp(`@keyframes ${name}\\{(.*)\\}`))[1];
    assert.doesNotMatch(frames, /translate|transform|outline|scale/, `${name} animates opacity only`);
  }
  const spot = css.match(/\.tutorial-spot\{[^}]*\}/)[0];
  assert.match(spot, /pointer-events:none/, "the scrim never takes the click");
  assert.match(spot, /var\(--a-scrim\)/);
  assert.doesNotMatch(spot, /outline-offset|transition/, "no detached outline; glide only between anchors");
});

/* A target and its ancestors, innermost first; the last ancestor's parent is <body>, where clipping stops. */
function anchorIn(targetRect, ancestors, { position = "static" } = {}) {
  const body = { parentElement: null };
  const doc = { body, defaultView: { getComputedStyle: (node) => node.style } };
  const node = (rect, style, client) => ({ ownerDocument: doc, style, getBoundingClientRect: () => rect, closest: () => null,
    clientLeft: client?.left ?? 0, clientTop: client?.top ?? 0, clientWidth: client?.width ?? rect.width, clientHeight: client?.height ?? rect.height });
  const element = node(targetRect, { position, overflowX: "visible", overflowY: "visible" });
  let child = element;
  for (const ancestor of ancestors) {
    const parent = node(ancestor.rect, { position: "static", overflowX: "visible", overflowY: "visible", ...ancestor.style }, ancestor.client);
    child.parentElement = parent;
    child = parent;
  }
  child.parentElement = body;
  return { element, root: { querySelectorAll: () => [element] } };
}
const scroller = (rect, style = { overflowY: "auto", overflowX: "hidden" }) => ({ rect, style, client: { width: rect.width - 12, height: rect.height } });
const screenSize = { width: 1200, height: 800 };

test("a target inside a scroll container is measured as its visible part, and as nothing once scrolled out", () => {
  assert.deepEqual(visibleRect(box(100, 380, 60, 40), [box(80, 100, 300, 300)], screenSize), box(100, 380, 60, 20));
  assert.equal(visibleRect(box(100, 520, 60, 24), [box(80, 100, 300, 300)], screenSize), null, "below the fold of the table");
  assert.deepEqual(visibleRect(box(-10, 790, 40, 30), [], screenSize), box(0, 790, 30, 10), "the viewport clips too");
  // The mapping table scrolls; the badge row sits below its fold, over the data preview drawn underneath.
  const table = scroller(box(40, 120, 500, 300));
  const hidden = anchorIn(box(300, 470, 40, 22), [{ rect: box(280, 460, 200, 40) }, table, { rect: box(0, 60, 1200, 740) }]);
  assert.equal(measureTarget(hidden.root, "#badge", screenSize), null, "no ring over unrelated content");
  const partial = anchorIn(box(300, 410, 40, 22), [table]);
  assert.deepEqual(measureTarget(partial.root, "#badge", screenSize).rect, box(300, 410, 40, 10));
  const scrollbar = anchorIn(box(520, 200, 40, 22), [table]);
  assert.deepEqual(measureTarget(scrollbar.root, "#badge", screenSize).rect, box(520, 200, 8, 22), "the scrollbar gutter is not visible content");
  const modal = anchorIn(box(300, 700, 80, 30), [scroller(box(250, 150, 600, 500)), { rect: box(0, 0, 1200, 800), style: { position: "fixed" } }]);
  assert.equal(measureTarget(modal.root, "#browse", screenSize), null, "a dialog card clips its own scrolled-away controls");
  const popover = anchorIn(box(300, 470, 40, 22), [table], { position: "fixed" });
  assert.deepEqual(measureTarget(popover.root, "#pop", screenSize).rect, box(300, 470, 40, 22), "a fixed popover escapes the scroller");
  const absolute = anchorIn(box(300, 470, 40, 22), [table, { rect: box(0, 60, 1200, 740), style: { position: "relative", overflowY: "hidden" } }], { position: "absolute" });
  assert.deepEqual(measureTarget(absolute.root, "#abs", screenSize).rect, box(300, 470, 40, 22), "a static scroller is not an absolute box's container");
});

test("a painted text range is boxed as the union of its lines, clipped like any anchor (#1136)", () => {
  const table = scroller(box(40, 120, 500, 300));
  const lines = [box(60, 300, 400, 20), box(60, 320, 400, 20), box(60, 340, 400, 20)].map((rect) => anchorIn(rect, [table]).element);
  const root = { querySelectorAll: () => lines };
  assert.deepEqual(measureTarget(root, ".cm-tutorial-range", screenSize, undefined, true).rect, box(60, 300, 400, 60));
  assert.deepEqual(measureTarget(root, ".cm-tutorial-range", screenSize).rect, box(60, 300, 400, 20), "a control is still its first match");
  const lower = [box(60, 400, 400, 20), box(60, 420, 400, 20)].map((rect) => anchorIn(rect, [table]).element);
  assert.deepEqual(measureTarget({ querySelectorAll: () => lower }, ".r", screenSize, undefined, true).rect, box(60, 400, 400, 20),
    "the part below the scroller's fold is not boxed");
});

test("a changed anchor is scrolled into view once; re-measures never scroll against the user", () => {
  const scrolled = [];
  const reveal = createRevealer((element) => scrolled.push(element));
  const first = anchorIn(box(300, 470, 40, 22), []);
  const replaced = anchorIn(box(300, 470, 40, 22), []);
  measureTarget(first.root, "#badge", screenSize, reveal("b6|mapping"));
  measureTarget(first.root, "#badge", screenSize, reveal("b6|mapping"));
  measureTarget(first.root, "#badge", screenSize, reveal("b6|mapping"));
  assert.deepEqual(scrolled, [first.element], "one scroll per target change, none per re-measure");
  measureTarget(replaced.root, "#badge", screenSize, reveal("b6|mapping"));
  assert.deepEqual(scrolled, [first.element, replaced.element], "a re-rendered (replaced) element is revealed again");
  measureTarget(replaced.root, "#badge", screenSize, reveal("b7|mapping"));
  assert.equal(scrolled.length, 3, "the next beat reveals its anchor even when the element is the same");
  let order = "";
  const probe = anchorIn(box(1, 1, 1, 1), []);
  probe.element.getBoundingClientRect = () => { order += "measure"; return box(1, 1, 1, 1); };
  measureTarget(probe.root, "#x", screenSize, () => { order += "reveal,"; });
  assert.match(order, /reveal,measure$/, "the ring's box is read after the reveal scrolled it");
});

test("a target scrolled out of sight leaves the existing way back, inside a dialog as well", () => {
  assert.match(coachHtml({ lost: true }), new RegExp(`id="tutorialReturn"[^>]*>${copy.return}<`));
  assert.match(coachHtml({ lost: true, inline: true, overlayBusy: true }), /id="tutorialReturn"/);
  assert.doesNotMatch(coachHtml({ lost: true, overlayBusy: true }), /id="tutorialReturn"/, "an unrelated dialog keeps the guide quiet");
});
