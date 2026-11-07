/* Editor edit-chain probe helpers: step timeline, in-deadline waits, and teardown leak isolation. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { ERROR_CODES, HOST_OPS, createSelftestRunner } from "../../frontend/src/selftest/runner.js";
import {
  DISCARD_SETTLE_MS, DISCARD_WAIT_MARGIN_MS, EDITOR_EDIT_CHAIN, EDIT_QUIESCE_MS,
  awaitDiscardSteps, createStepClock, observePreChain, teardownStubbedEditor,
} from "../../frontend/src/selftest/probes/editor_edit_chain.js";
import { Intent } from "../../frontend/js/intent.js";

/* ────────────────────────── 가상 시계 (n08_runner 와 같은 꼴) ────────────────────────── */

function createClock() {
  let clock = 0;
  let seq = 0;
  const timers = [];
  return {
    now: () => clock,
    sleep(ms) {
      return new Promise((resolve) => {
        timers.push({ at: clock + ms, seq: (seq += 1), resolve });
      });
    },
    fireNext() {
      if (timers.length === 0) return false;
      timers.sort((a, b) => (a.at - b.at) || (a.seq - b.seq));
      const timer = timers.shift();
      clock = Math.max(clock, timer.at);
      timer.resolve();
      return true;
    },
  };
}

async function flush() {
  for (let i = 0; i < 200; i += 1) await Promise.resolve();
}

async function settle(clock, promise) {
  let done = false;
  const tracked = promise.then(
    (value) => { done = true; return value; },
    (error) => { done = true; throw error; },
  );
  tracked.catch(() => {});
  for (let step = 0; step < 20000; step += 1) {
    await flush();
    if (done) break;
    if (!clock.fireNext()) break;
  }
  return tracked;
}

/** 남은 가상 타이머를 전부 깨운다 — 모듈 전역 체인(`Intent`)을 다음 테스트로 넘기지 않는다. */
async function drain(clock) {
  await flush();
  while (clock.fireNext()) await flush();
}

/* ────────────────────────── 제품 대역 ────────────────────────── */

const REAL_REFUSAL = "아직 저장하지 않은 새 작업이라 되돌릴 이전 상태가 없습니다.";

/** 편집기 표면 하나 — 스텁이 서 있으면 스텁이, 아니면 「실 컨트롤러」가 받는다.
 *  실 컨트롤러는 실제 CI 처럼 저장 전 새 작업이라 `discard_patch` 를 거절하고, 제품의
 *  `guarded` 가 그러듯 `window.alert` 로 재진술한다. */
function createEditorSurface(clock, win) {
  const surface = { stubActive: false, stubbed: [], real: [] };
  surface.call = (action, steps) => {
    if (!surface.stubActive) {
      surface.real.push(action);
      return action === "discard_patch"
        ? Promise.reject(new Error(REAL_REFUSAL)) : Promise.resolve({});
    }
    surface.stubbed.push(action);
    if (action === "set_name") {
      steps.mark("set_name_arrived");
      return clock.sleep(120).then(() => { steps.mark("set_name_resolved"); return {}; });
    }
    if (action === "discard_patch") steps.mark("discard_patch_arrived");
    return Promise.resolve({});
  };
  /* `editor_controller.ts` 의 순서 그대로: blur 커밋(`set_name`)이 체인에 서고, 클릭의
     `discardPatch` 가 `flushPendingEdits`(→ settleChain) 뒤 `discard_patch` 를 체인에 세운다. */
  surface.clickDiscard = (steps) => {
    Intent.chained(EDITOR_EDIT_CHAIN, () => surface.call("set_name", steps)).catch(() => {});
    (async () => {
      await Intent.chained(EDITOR_EDIT_CHAIN, () => Promise.resolve());
      await Intent.chained(EDITOR_EDIT_CHAIN, () => surface.call("discard_patch", steps));
    })().catch((error) => win.alert(String(error.message)));
  };
  return surface;
}

function createHarness() {
  const clock = createClock();
  const win = { alert() {} };
  const caps = {
    doc: { body: {}, readyState: "complete" },
    win,
    push: () => {},
    services: { Intent },
    host: { provides: HOST_OPS.slice(), request: (op, payload) => ({ op, payload }) },
    now: clock.now,
    sleep: clock.sleep,
  };
  return { clock, win, caps, surface: createEditorSurface(clock, win) };
}

const lib = {
  service: (ctx, name) => ctx.services[name],
  restoreShell: () => {},
};

/** 실 `editor_discard_immediate` 의 발신·대기·정리 골격을 DOM 없이 옮긴 대역 프로브.
 *  `teardownMode: "legacy"` 는 고치기 전 정리(곧바로 스텁 복원)로, 하네스가 누수를 실제로
 *  볼 수 있음을 보이는 양성대조다. */
function discardProbe(surface, { teardownMode = "guarded" } = {}) {
  return {
    name: "discard_like",
    keys: ["discard_like"],
    cluster: "T",
    owner: "frontend",
    modes: ["full"],
    legacySite: 1000,
    deadlineMs: 2500,
    deadlineRationale: "테스트 대역 — editor_discard_immediate 와 같은 2.5초.",
    completionField: "pending",
    async run(ctx) {
      const steps = createStepClock(ctx.now);
      ctx.state.steps = steps;
      surface.stubActive = true;
      ctx.state.stub = { restore() { surface.stubActive = false; } };
      observePreChain(ctx, lib, steps);
      steps.start();
      surface.clickDiscard(steps);
      await awaitDiscardSteps(ctx, steps);
      await ctx.sleep(DISCARD_SETTLE_MS);
      return { discard_like: { pending: false, timeline_ms: steps.timeline() } };
    },
    teardown(ctx) {
      if (teardownMode === "legacy") {
        ctx.state.stub.restore();
        return undefined;
      }
      const steps = ctx.state.steps;
      return teardownStubbedEditor(
        ctx, lib,
        () => steps.started && !steps.has("discard_patch_arrived"),
        `discard_patch (클릭 기준: ${steps.describe()})`,
      );
    },
  };
}

/** 뒤따르는 프로브 — 실 CI 의 `editor_txt_band` 자리. 시간을 조금 쓰는 동안 새는 발신이
 *  있으면 그 경보가 이 프로브 이름으로 선다. */
function nextProbe() {
  return {
    name: "next_probe",
    keys: ["next_probe"],
    cluster: "T",
    owner: "frontend",
    modes: ["full"],
    legacySite: 1001,
    deadlineMs: 6000,
    deadlineRationale: "테스트 대역 — 늦은 발신이 닿을 시간을 준다.",
    async run(ctx) {
      await ctx.sleep(5000);
      return { next_probe: "ok" };
    },
  };
}

/** 프로브 앞에서 편집 체인을 `ms` 동안 붙드는 선행 발신 — CI 실측의 「느린 고리」 대역. */
function holdChain(clock, ms) {
  Intent.chained(EDITOR_EDIT_CHAIN, () => clock.sleep(ms)).catch(() => {});
}

/* ────────────────────────── 테스트 ────────────────────────── */

test("편집 체인 키는 제품 컨트롤러의 EDIT_CHAIN 과 같은 문자열이다", () => {
  const source = readFileSync(new URL("../../frontend/src/screens/editor_controller.ts", import.meta.url), "utf8");
  const match = /const EDIT_CHAIN = "([^"]+)";/.exec(source);
  assert.ok(match, "editor_controller.ts 에서 EDIT_CHAIN 을 찾지 못했습니다.");
  assert.equal(EDITOR_EDIT_CHAIN, match[1]);
});

test("정상 경로 — 단계 시각이 클릭 기준으로 증거에 실린다", async () => {
  const { clock, caps, surface } = createHarness();
  const runner = createSelftestRunner(caps);
  runner.register(discardProbe(surface));
  const report = await settle(clock, runner.run("full", {}));
  await drain(clock);

  assert.equal(report.ok, true, JSON.stringify(report.errors));
  const timeline = report.results.discard_like.timeline_ms;
  assert.ok(timeline.pre_chain_idle <= 0, "선행 체인은 클릭 전에 비어 있었다.");
  assert.equal(timeline.set_name_arrived, 0);
  assert.equal(timeline.set_name_resolved, 120);
  assert.equal(timeline.discard_patch_arrived, 120);
  assert.deepEqual(surface.stubbed, ["set_name", "discard_patch"]);
  assert.deepEqual(surface.real, []);
});

test("늦은 고리는 시한 안에서 이 프로브의 문안으로 서고, 도착한 단계를 이름으로 남긴다", async () => {
  const { clock, caps, surface } = createHarness();
  const runner = createSelftestRunner(caps);
  runner.register(discardProbe(surface));
  runner.register(nextProbe());
  holdChain(clock, 2600);
  const report = await settle(clock, runner.run("full", {}));
  await drain(clock);

  assert.equal(report.ok, false);
  assert.equal(report.errors.length, 1, JSON.stringify(report.errors));
  const [error] = report.errors;
  assert.equal(error.probe, "discard_like");
  assert.equal(error.phase, "run");
  assert.equal(error.code, ERROR_CODES.DEADLINE_EXCEEDED);
  /* 감시견의 이름 없는 문안이 아니라 단계 대기의 문안이다. */
  assert.doesNotMatch(error.message, /부분 상태를 결과로 내지 않습니다/);
  assert.match(error.message, /set_name_arrived 대기 \d+ms 초과/);
  assert.match(error.message, /pre_chain_idle 미도착/);
  assert.match(error.message, /discard_patch_arrived 미도착/);
  /* 내부 대기 + 정착 + 여유가 시한 안에 엄격히 든다. */
  const waited = Number(/대기 (\d+)ms 초과/.exec(error.message)[1]);
  assert.ok(waited + DISCARD_SETTLE_MS + DISCARD_WAIT_MARGIN_MS <= 2500, `waited=${waited}`);
  /* 실패는 성공으로 바뀌지 않는다 — 키가 없다. */
  assert.equal(Object.prototype.hasOwnProperty.call(report.results, "discard_like"), false);
  /* 격리: 늦은 발신은 정리가 기다린 스텁에 닿았고 실 컨트롤러·다음 프로브로 새지 않았다. */
  assert.deepEqual(surface.stubbed, ["set_name", "discard_patch"]);
  assert.deepEqual(surface.real, []);
  assert.equal(report.results.next_probe, "ok");
  assert.equal(surface.stubActive, false, "정리 뒤 스텁은 되돌려진다.");
});

test("양성대조 — 곧바로 스텁을 되돌리던 정리는 늦은 발신을 다음 프로브의 경보로 흘린다", async () => {
  const { clock, caps, surface } = createHarness();
  const runner = createSelftestRunner(caps);
  runner.register(discardProbe(surface, { teardownMode: "legacy" }));
  runner.register(nextProbe());
  holdChain(clock, 2600);
  const report = await settle(clock, runner.run("full", {}));
  await drain(clock);

  const leaked = report.errors.find((e) => e.code === ERROR_CODES.ALERT_RAISED);
  assert.ok(leaked, JSON.stringify(report.errors));
  assert.equal(leaked.probe, "next_probe");
  assert.match(leaked.message, /되돌릴 이전 상태가 없습니다/);
  assert.ok(surface.real.includes("discard_patch"));
});

test("정리 상한 안에 체인이 비지 않으면 이 프로브의 teardown_failed 로 서고 뒤 국면을 멈춘다", async () => {
  const { clock, caps, surface } = createHarness();
  const runner = createSelftestRunner(caps);
  runner.register(discardProbe(surface));
  runner.register(nextProbe());
  holdChain(clock, 2500 + EDIT_QUIESCE_MS + 1000);
  const report = await settle(clock, runner.run("full", {}));

  const codes = report.errors.map((e) => `${e.probe}/${e.phase}/${e.code}`);
  assert.deepEqual(codes, [
    `discard_like/run/${ERROR_CODES.DEADLINE_EXCEEDED}`,
    `discard_like/teardown/${ERROR_CODES.TEARDOWN_FAILED}`,
  ]);
  assert.match(report.errors[1].message, /discard_patch \(클릭 기준: .*\) 착지/);
  assert.match(report.errors[1].message, new RegExp(`시한 ${EDIT_QUIESCE_MS}ms 초과`));
  assert.equal(report.skipped[0].probe, "next_probe");
  /* 정산이 실패해도 스텁은 되돌린다 — 실패를 숨기지 않을 뿐 남겨 두지도 않는다. */
  assert.equal(surface.stubActive, false);
  await drain(clock);
});
