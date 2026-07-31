/* N-08 레인 S — 프로브 하니스(`frontend/src/selftest/runner.js`) 단위 계약.
 *
 * 이 러너가 대신하는 것은 `app.py` 의 `_probe_late` 와 `window.__*` 스태시 규약이다.
 * 그래서 이 파일이 겨누는 것도 **그 규약의 두 결함**이다:
 *
 *  ① 폴링 만료에 `else` 가 없어 낡은 부분 결과가 정상 모양으로 회수된다(app.py:3502-3506).
 *     → 시한 초과는 **시끄러운 실패**이고 그 프로브의 키는 결과에 실리지 않는다.
 *  ② 넓은 catch 가 실패를 정상값으로 바꾼다(catch 40곳 / 상수 24개).
 *     → 오류는 `{probe, phase, code, message}` 구조체이고 국면이 갈린다.
 *
 * 시계는 주입한다. 아래 가상 시계는 **가상 시각 순서**로 타이머를 하나씩 발화하므로
 * 시한·폴링·정착 대기가 실시간 없이 결정적으로 돈다(게이트는 flaky 금지).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  ERROR_CODES,
  HOST_OPS,
  LEGACY_BUDGET,
  LEGACY_DEADLINES_MS,
  LEGACY_FIXED_SLEEPS_MS,
  PROBE_PHASES,
  SelftestProbeError,
  createSelftestRunner,
} from "../../frontend/src/selftest/runner.js";

const SRC = readFileSync(
  new URL("../../frontend/src/selftest/runner.js", import.meta.url),
  "utf8",
);

/* ────────────────────────── 가상 시계 ────────────────────────── */

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

/** 마이크로태스크를 충분히 흘린 뒤 가장 이른 타이머를 하나 깨우기를 반복한다. */
async function settle(clock, promise) {
  let done = false;
  const tracked = promise.then(
    (value) => { done = true; return value; },
    (error) => { done = true; throw error; },
  );
  tracked.catch(() => {});
  for (let step = 0; step < 20000; step += 1) {
    for (let flush = 0; flush < 40; flush += 1) await Promise.resolve();
    if (done) break;
    if (!clock.fireNext()) break;
  }
  return tracked;
}

/* ────────────────────────── 최소 대역 ────────────────────────── */

function createCaps(overrides) {
  const clock = createClock();
  const requests = [];
  const caps = {
    doc: { body: {}, readyState: "complete" },
    win: {},
    push: () => {},
    services: {},
    host: {
      provides: HOST_OPS.slice(),
      request(op, payload) {
        requests.push({ op, payload });
        return { op, payload };
      },
    },
    now: clock.now,
    sleep: clock.sleep,
    ...(overrides || {}),
  };
  return { caps, clock, requests };
}

function baseProbe(extra) {
  return {
    name: "probe_a",
    keys: ["probe_a"],
    cluster: "T",
    owner: "frontend",
    modes: ["full"],
    legacySite: 1000,
    deadlineMs: 0,
    deadlineRationale: "테스트 대역 — 동기 측정.",
    run: () => ({ probe_a: "ok" }),
    ...(extra || {}),
  };
}

/* ────────────────────────── 표면 ────────────────────────── */

test("공개 표면 — 이름 전수와 export default 부재", () => {
  assert.equal(typeof createSelftestRunner, "function");
  assert.equal(typeof SelftestProbeError, "function");
  assert.ok(Array.isArray(PROBE_PHASES) && PROBE_PHASES.length === 7);
  assert.ok(Array.isArray(HOST_OPS) && HOST_OPS.length === 11);
  assert.equal(typeof ERROR_CODES.DEADLINE_EXCEEDED, "string");
  assert.equal(typeof LEGACY_DEADLINES_MS, "object");
  assert.equal(typeof LEGACY_FIXED_SLEEPS_MS, "object");
  assert.equal(typeof LEGACY_BUDGET, "object");
  assert.equal(/export\s+default/.test(SRC), false);

  const runner = createSelftestRunner(createCaps().caps);
  assert.deepEqual(Object.keys(runner).sort(), [
    "budgetMs", "describe", "plan", "probes", "register", "registerAll", "run", "toEvidence",
  ]);
});

test("능력은 주입이다 — 전역에서 줍지 않는다", () => {
  assert.throws(() => createSelftestRunner({}), (err) => {
    assert.ok(err instanceof SelftestProbeError);
    assert.equal(err.phase, "registration");
    assert.match(err.detail, /주입 누락/);
    /* push 도 주입 목록 안이다 — window.__push 를 읽지 않는다. */
    assert.match(err.detail, /push/);
    return true;
  });
  assert.equal(SRC.includes("window.__push"), false);
});

test("시간 예산은 데이터다 — 레거시 시한 표가 그대로 적혀 있다", () => {
  assert.equal(LEGACY_DEADLINES_MS.__probe_late__, 2500);
  assert.equal(LEGACY_DEADLINES_MS.action_roundtrip, 10000);
  assert.equal(LEGACY_DEADLINES_MS.view_order, 6000);
  assert.equal(LEGACY_DEADLINES_MS.data_sheet, 6000);
  assert.equal(LEGACY_DEADLINES_MS.range_draft, 6000);
  assert.equal(LEGACY_DEADLINES_MS.chain_recovery, 5000);
  assert.equal(LEGACY_DEADLINES_MS.runtime, 8000);
  assert.equal(LEGACY_DEADLINES_MS.window_geometry, 10000);
  assert.equal(LEGACY_BUDGET.processTimeoutMs, 90000);
  assert.equal(LEGACY_BUDGET.worstCaseMs, 68000);
  assert.equal(
    LEGACY_BUDGET.headroomMs,
    LEGACY_BUDGET.processTimeoutMs - LEGACY_BUDGET.worstCaseMs,
  );
  assert.ok(LEGACY_BUDGET.worstCaseMs < LEGACY_BUDGET.processTimeoutMs);
});

test("예산은 늘지 않는다 — 레거시 시한 초과 등록은 거절", () => {
  const runner = createSelftestRunner(createCaps().caps);
  assert.throws(
    () => runner.register(baseProbe({ name: "chain_recovery", keys: ["chain_recovery"], deadlineMs: 5001 })),
    /레거시 예산 5000 를 넘습니다/,
  );
  /* 같은 값·더 작은 값은 통과한다. */
  runner.register(baseProbe({ name: "chain_recovery", keys: ["chain_recovery"], deadlineMs: 5000 }));
  assert.equal(runner.probes().length, 1);
});

test("레거시 표에 없는 프로브는 시한 사유를 적어야 한다", () => {
  const runner = createSelftestRunner(createCaps().caps);
  const def = baseProbe({ name: "brand_new", keys: ["brand_new"], deadlineMs: 1000 });
  delete def.deadlineRationale;
  assert.throws(() => runner.register(def), /deadlineRationale/);
});

test("이유 없는 대기는 등록되지 않는다", () => {
  const runner = createSelftestRunner(createCaps().caps);
  assert.throws(() => runner.register(baseProbe({ settleBeforeMs: 600 })), /settleReason/);
  assert.throws(() => runner.register(baseProbe({ cooldownAfterMs: 400 })), /cooldownReason/);
  runner.register(baseProbe({
    cooldownAfterMs: 400,
    cooldownReason: "닫히는 모달 백드롭이 다음 프로브의 클릭을 막지 않게.",
  }));
  assert.equal(runner.describe()[0].cooldownAfterMs, 400);
  assert.match(runner.describe()[0].cooldownReason, /백드롭/);
});

/* ────────────────────────── 순서 ────────────────────────── */

test("순서 제약은 일급 데이터다 — after 위상 정렬 + legacySite 동률 처리", () => {
  const runner = createSelftestRunner(createCaps().caps);
  runner.register(baseProbe({
    name: "job_mirror", keys: ["job_mirror"], legacySite: 3880,
    after: ["job_data_first"],
    afterReason: "job_data_first 가 빈 경로 스냅샷을 남긴다(app.py:3872-3876).",
  }));
  runner.register(baseProbe({ name: "job_data_first", keys: ["job_data_first"], legacySite: 3877 }));
  runner.register(baseProbe({ name: "data_picker", keys: ["data_picker"], legacySite: 3800 }));

  assert.deepEqual(runner.plan("full").map((p) => p.name), [
    "data_picker", "job_data_first", "job_mirror",
  ]);
  /* 제약이 서술에도 남는다 — 이식하는 쪽이 이유를 본다. */
  const mirror = runner.describe().find((p) => p.name === "job_mirror");
  assert.deepEqual(mirror.after, ["job_data_first"]);
  assert.match(mirror.afterReason, /빈 경로 스냅샷/);
});

test("legacySite 가 클러스터를 넘어 한 순서를 잇는다", () => {
  const runner = createSelftestRunner(createCaps().caps);
  runner.register(baseProbe({ name: "late_e", keys: ["late_e"], cluster: "E", legacySite: 3990 }));
  runner.register(baseProbe({ name: "early_b", keys: ["early_b"], cluster: "B", legacySite: 3718 }));
  runner.register(baseProbe({ name: "mid_c", keys: ["mid_c"], cluster: "C", legacySite: 3860 }));
  assert.deepEqual(runner.plan("full").map((p) => p.name), ["early_b", "mid_c", "late_e"]);
});

test("순서 제약의 결손·순환은 시끄럽게 거절된다", () => {
  const runner = createSelftestRunner(createCaps().caps);
  runner.register(baseProbe({ name: "a", keys: ["a"], after: ["ghost"] }));
  assert.throws(() => runner.plan("full"), /ghost 가 모드 full 의 계획에 없습니다/);

  const cyclic = createSelftestRunner(createCaps().caps);
  cyclic.register(baseProbe({ name: "x", keys: ["x"], after: ["y"] }));
  cyclic.register(baseProbe({ name: "y", keys: ["y"], after: ["x"], legacySite: 1001 }));
  assert.throws(() => cyclic.plan("full"), /순환이 있습니다/);
});

test("한 모드 안에서 키 생산자는 하나뿐이고, 모드가 다르면 같은 키를 나눠 쓴다", () => {
  const clash = createSelftestRunner(createCaps().caps);
  clash.register(baseProbe({ name: "p1", keys: ["set_result"] }));
  clash.register(baseProbe({ name: "p2", keys: ["set_result"], legacySite: 1001 }));
  assert.throws(() => clash.plan("full"), /한 키의 생산자는 하나입니다/);

  const split = createSelftestRunner(createCaps().caps);
  split.register(baseProbe({ name: "theme_write2", keys: ["set_result"], modes: ["theme_write"] }));
  split.register(baseProbe({
    name: "font_scale_write2", keys: ["set_result"], modes: ["font_scale_write"], legacySite: 1001,
  }));
  assert.deepEqual(split.plan("theme_write").map((p) => p.name), ["theme_write2"]);
  assert.deepEqual(split.plan("font_scale_write").map((p) => p.name), ["font_scale_write2"]);
});

/* ────────────────────────── 호스트 소유 ────────────────────────── */

test("호스트 소유 연산은 **요청**이지 수행이 아니다", async () => {
  const { caps, clock, requests } = createCaps();
  caps.host.request = (op, payload) => {
    requests.push({ op, payload });
    if (op === "window_geometry") return { x: 32, y: 55, width: 1427, height: 865 };
    return null;
  };
  const runner = createSelftestRunner(caps);
  runner.register(baseProbe({
    name: "window_geometry",
    keys: ["window_geometry"],
    owner: "host",
    hostOp: "window_geometry",
    requiresHost: ["window_geometry"],
    modes: ["geometry_only"],
    legacySite: 3634,
    deadlineMs: 10000,
    run: undefined,
  }));
  const report = await settle(clock, runner.run("geometry_only", {}));
  assert.equal(report.ok, true);
  assert.deepEqual(report.results.window_geometry, { x: 32, y: 55, width: 1427, height: 865 });
  assert.deepEqual(requests.map((r) => r.op), ["window_geometry"]);
});

test("선언하지 않은 호스트 연산 요청과 호스트가 못 대는 op 는 거절", async () => {
  const { caps, clock } = createCaps();
  caps.host.provides = ["current_url"];
  const runner = createSelftestRunner(caps);
  runner.register(baseProbe({ name: "needs", keys: ["needs"], requiresHost: ["window_resize"] }));
  assert.throws(() => runner.plan("full"), /호스트가 window_resize 를 대지 않습니다/);

  const { caps: caps2, clock: clock2 } = createCaps();
  const runner2 = createSelftestRunner(caps2);
  runner2.register(baseProbe({
    name: "sneaky",
    keys: ["sneaky"],
    run: (ctx) => ctx.host("window_resize", { width: 1 }).then(() => ({ sneaky: 1 })),
  }));
  const report = await settle(clock2, runner2.run("full", {}));
  assert.equal(report.ok, false);
  assert.equal(report.errors[0].phase, "host");
  assert.match(report.errors[0].message, /선언하지 않은 호스트 연산/);
  assert.equal(Object.prototype.hasOwnProperty.call(report.results, "sneaky"), false);
  assert.ok(clock2);
});

test("hostSetup 은 측정 전에 요청되고 정착 대기가 그 뒤에 온다", async () => {
  const { caps, clock, requests } = createCaps();
  const runner = createSelftestRunner(caps);
  const seen = [];
  runner.register(baseProbe({
    name: "grid_narrow",
    keys: ["grid_narrow"],
    requiresHost: ["window_resize"],
    hostSetup: { op: "window_resize", payload: { width: 760, height: 600 } },
    settleBeforeMs: 600,
    settleReason: "resize 는 OS 이벤트라 relayout 안정까지 기다린다.",
    run: (ctx) => { seen.push(ctx.now()); return { grid_narrow: { tabs: 2 } }; },
  }));
  const report = await settle(clock, runner.run("full", {}));
  assert.equal(report.ok, true);
  assert.deepEqual(requests[0], { op: "window_resize", payload: { width: 760, height: 600 } });
  assert.equal(seen[0], 600, "정착 대기 600ms 뒤에 측정해야 합니다.");
});

/* ────────────────────── 시한 — 조용한 부분 결과 금지 ────────────────────── */

test("시한 초과는 **시끄럽게** 실패하고 부분 결과를 내지 않는다", async () => {
  const { caps, clock } = createCaps();
  const runner = createSelftestRunner(caps);
  /* 오늘의 결함 재현: 프로브가 부분 객체를 들고 있는데 끝나지 않는다.
     레거시는 폴링이 만료돼도 else 없이 흘러가 그 부분 객체를 그대로 회수했다. */
  const stale = { pending: true, rejected_surfaced: true };
  runner.register(baseProbe({
    name: "chain_recovery",
    keys: ["chain_recovery"],
    deadlineMs: 5000,
    run: () => new Promise(() => { stale.after_ran = false; }),
  }));
  const report = await settle(clock, runner.run("full", {}));

  assert.equal(report.ok, false);
  assert.equal(report.errors.length, 1);
  assert.deepEqual(Object.keys(report.errors[0]).sort(), ["code", "message", "phase", "probe"]);
  assert.equal(report.errors[0].probe, "chain_recovery");
  assert.equal(report.errors[0].phase, "run");
  assert.equal(report.errors[0].code, ERROR_CODES.DEADLINE_EXCEEDED);
  assert.match(report.errors[0].message, /부분 상태를 결과로 내지 않습니다/);
  /* **핵심**: 키가 결과에 없다. 모양만 맞는 낡은 값이 성공인 척 실리지 않는다. */
  assert.deepEqual(report.results, {});
  const evidence = runner.toEvidence(report);
  assert.equal(Object.prototype.hasOwnProperty.call(evidence, "chain_recovery"), false);
  assert.match(evidence.error, /deadline_exceeded/);
});

test("waitFor 만료도 같은 규약이다 — else 없는 폴백이 없다", async () => {
  const { caps, clock } = createCaps();
  const runner = createSelftestRunner(caps);
  let polls = 0;
  runner.register(baseProbe({
    name: "view_order",
    keys: ["view_order"],
    deadlineMs: 6000,
    run: async (ctx) => {
      /* 안쪽 시한은 바깥 프로브 시한보다 **엄격히 작게** 잡는다 — 그래야 구체적인 경보가
         이기고 감시견은 마지막 안전망으로 남는다. */
      await ctx.waitFor(() => { polls += 1; return false; }, {
        what: "표시순서 왕복 완주", timeoutMs: 5000,
      });
      return { view_order: { pending: false } };
    },
  }));
  const report = await settle(clock, runner.run("full", {}));
  assert.equal(report.ok, false);
  assert.equal(report.errors[0].code, ERROR_CODES.DEADLINE_EXCEEDED);
  assert.match(report.errors[0].message, /표시순서 왕복 완주 시한 5000ms 초과/);
  assert.match(report.errors[0].message, /낡은 부분 결과를 내보내지 않고/);
  assert.ok(polls > 1, "폴링은 실제로 돌아야 합니다.");
  assert.deepEqual(report.results, {});
});

test("감시견이 이겨도 **무엇을 기다리다 죽었는지**는 남는다", async () => {
  const { caps, clock } = createCaps();
  const runner = createSelftestRunner(caps);
  runner.register(baseProbe({
    name: "data_sheet",
    keys: ["data_sheet"],
    deadlineMs: 6000,
    run: async (ctx) => {
      /* 안팎 시한이 같으면 바깥이 이긴다 — 그래도 진단은 잃지 않는다. */
      await ctx.waitFor(() => false, { what: "⤢ 데이터 면 열림", timeoutMs: 6000 });
      return { data_sheet: {} };
    },
  }));
  const report = await settle(clock, runner.run("full", {}));
  assert.equal(report.errors[0].code, ERROR_CODES.DEADLINE_EXCEEDED);
  assert.match(report.errors[0].message, /대기 중: ⤢ 데이터 면 열림/);
  assert.deepEqual(report.results, {});
});

test("완주는 구조다 — completionField 가 pending 을 강제한다", async () => {
  const { caps, clock } = createCaps();
  const runner = createSelftestRunner(caps);
  runner.register(baseProbe({
    name: "data_sheet",
    keys: ["data_sheet"],
    deadlineMs: 6000,
    completionField: "pending",
    run: () => ({ data_sheet: { pending: true, present: true } }),
  }));
  const report = await settle(clock, runner.run("full", {}));
  assert.equal(report.ok, false);
  assert.equal(report.errors[0].phase, "emit");
  assert.equal(report.errors[0].code, ERROR_CODES.INCOMPLETE);
  assert.match(report.errors[0].message, /data_sheet\.pending/);
  assert.deepEqual(report.results, {});
});

test("handlesOwnDeadline 은 사유를 적어야 하고 감시견을 비켜 간다", async () => {
  const runner = createSelftestRunner(createCaps().caps);
  assert.throws(
    () => runner.register(baseProbe({ deadlineMs: 100, handlesOwnDeadline: true })),
    /deadlineHandling/,
  );

  const { caps, clock } = createCaps();
  const other = createSelftestRunner(caps);
  other.register(baseProbe({
    name: "runtime",
    keys: ["runtime"],
    deadlineMs: 8000,
    handlesOwnDeadline: true,
    deadlineHandling: "시한 초과를 표식 값으로 확정한다 — build.ps1 이 그 문자열을 읽는다.",
    run: async (ctx) => {
      try {
        await ctx.waitFor(() => false, { what: "외부 fetch 정착", timeoutMs: 8000 });
      } catch (_) {
        return { runtime: { external_fetch_error: "offline probe timed out" } };
      }
      return { runtime: {} };
    },
  }));
  const report = await settle(clock, other.run("full", {}));
  assert.equal(report.ok, true, "자기 경보를 가진 프로브는 감시견에 가로채이지 않습니다.");
  assert.equal(report.results.runtime.external_fetch_error, "offline probe timed out");
});

/* ────────────────────────── 오류 모양 ────────────────────────── */

test("오류는 국면이 갈린 구조체다 — 실패와 '거짓을 쟀다' 를 섞지 않는다", async () => {
  const { caps, clock } = createCaps();
  const runner = createSelftestRunner(caps);
  runner.register(baseProbe({
    name: "measured_false",
    keys: ["measured_false"],
    run: () => ({ measured_false: { overflow: false } }),
  }));
  runner.register(baseProbe({
    name: "threw",
    keys: ["threw"],
    legacySite: 1001,
    run: () => { throw new Error("브리지 없음"); },
  }));
  runner.register(baseProbe({
    name: "setup_threw",
    keys: ["setup_threw"],
    legacySite: 1002,
    setup: () => { throw new Error("준비 실패"); },
    run: () => ({ setup_threw: 1 }),
  }));
  const report = await settle(clock, runner.run("full", {}));

  /* false 를 잰 프로브는 성공이고 값이 그대로 실린다. */
  assert.deepEqual(report.results.measured_false, { overflow: false });
  /* 던진 프로브는 실패고 키가 없다. */
  assert.equal(Object.prototype.hasOwnProperty.call(report.results, "threw"), false);
  assert.equal(report.errors.length, 2);
  for (const err of report.errors) {
    assert.deepEqual(Object.keys(err).sort(), ["code", "message", "phase", "probe"]);
    assert.ok(PROBE_PHASES.includes(err.phase), err.phase);
  }
  assert.match(report.errors[0].message, /브리지 없음/);
  assert.match(report.errors[1].message, /준비 실패/);
});

test("반환 모양이 선언 키와 다르면 거절", async () => {
  const { caps, clock } = createCaps();
  const runner = createSelftestRunner(caps);
  runner.register(baseProbe({ name: "shape", keys: ["shape"], run: () => ({ wrong: 1 }) }));
  runner.register(baseProbe({
    name: "scalar", keys: ["scalar"], legacySite: 1001, run: () => "not an object",
  }));
  const report = await settle(clock, runner.run("full", {}));
  assert.equal(report.errors.length, 2);
  for (const err of report.errors) {
    assert.equal(err.phase, "emit");
    assert.equal(err.code, ERROR_CODES.SHAPE_MISMATCH);
  }
});

/* ────────────────────────── 정리 ────────────────────────── */

test("정리 실패는 시끄럽고, 뒤 국면을 오염시키지 않게 실행을 멈춘다", async () => {
  const { caps, clock } = createCaps();
  const runner = createSelftestRunner(caps);
  runner.register(baseProbe({
    name: "editor_txt_band",
    keys: ["editor_txt_band"],
    run: () => ({ editor_txt_band: { pending: false } }),
    /* 오늘은 이 실패가 out.teardown_error 로만 남고 **아무도 읽지 않는다**. */
    teardown: () => { throw new Error("복원 호출이 남았습니다"); },
  }));
  runner.register(baseProbe({ name: "next_probe", keys: ["next_probe"], legacySite: 1001 }));

  const report = await settle(clock, runner.run("full", {}));
  assert.equal(report.ok, false);
  const teardownError = report.errors.find((e) => e.phase === "teardown");
  assert.equal(teardownError.code, ERROR_CODES.TEARDOWN_FAILED);
  assert.match(teardownError.message, /복원 호출이 남았습니다/);
  /* 측정 자체는 성공했으므로 값은 남지만, 뒤 프로브는 오염을 피해 건너뛴다. */
  assert.deepEqual(report.results.editor_txt_band, { pending: false });
  assert.equal(Object.prototype.hasOwnProperty.call(report.results, "next_probe"), false);
  assert.equal(report.skipped[0].probe, "next_probe");
  assert.match(report.skipped[0].message, /editor_txt_band 의 정리가 실패/);
  assert.match(runner.toEvidence(report).error, /teardown_failed/);
});

test("측정이 실패해도 정리는 돈다", async () => {
  const { caps, clock } = createCaps();
  const runner = createSelftestRunner(caps);
  let cleaned = 0;
  runner.register(baseProbe({
    name: "fails",
    keys: ["fails"],
    run: () => { throw new Error("측정 실패"); },
    teardown: () => { cleaned += 1; },
  }));
  const report = await settle(clock, runner.run("full", {}));
  assert.equal(cleaned, 1);
  assert.equal(report.ok, false);
});

/* ────────────────────────── 증거 ────────────────────────── */

test("증거 — 성공은 에코와 결과만, 실패는 error 가 선다", async () => {
  const { caps, clock } = createCaps();
  const runner = createSelftestRunner(caps);
  runner.register(baseProbe({ name: "set_result", keys: ["set_result"], run: () => ({ set_result: "dark" }) }));
  const report = await settle(clock, runner.run("full", {}));
  const evidence = runner.toEvidence(report, { theme_write: "dark" });
  assert.deepEqual(evidence, { theme_write: "dark", set_result: "dark" });
  assert.equal(Object.prototype.hasOwnProperty.call(evidence, "error"), false);
});

test("예산 합산 — 모드별 최악 시간이 데이터로 나온다", () => {
  const runner = createSelftestRunner(createCaps().caps);
  runner.register(baseProbe({
    name: "chain_recovery", keys: ["chain_recovery"], deadlineMs: 5000,
  }));
  runner.register(baseProbe({
    name: "grid_narrow", keys: ["grid_narrow"], legacySite: 1001,
    settleBeforeMs: 600, settleReason: "relayout 안정.",
  }));
  assert.equal(runner.budgetMs("full"), 5600);
  assert.ok(runner.budgetMs("full") < LEGACY_BUDGET.processTimeoutMs);
});

/* ────────────────────────── 음성 ────────────────────────── */

test("음성 — 전역 쓰기·window.__ 스태시·__hwpxTest 부재", () => {
  assert.equal(/(?:^|\s)window\.[A-Za-z_$][A-Za-z0-9_$]*\s*=/m.test(SRC), false);
  assert.equal(/globalThis\s*\.\s*[A-Za-z_$][A-Za-z0-9_$]*\s*=/.test(SRC), false);
  assert.equal(SRC.includes("__hwpxTest"), false);
  assert.equal(/window\.__/.test(SRC), false, "window.__* 스태시 규약은 옮겨 오지 않는다.");
});

test("bare import 는 순수하다 — DOM·리스너·전역을 만들지 않는다", async () => {
  const before = Object.keys(globalThis).length;
  const again = await import(`../../frontend/src/selftest/runner.js?pure=${Date.now()}`);
  assert.equal(typeof again.createSelftestRunner, "function");
  assert.equal(Object.keys(globalThis).length, before);
  assert.equal(typeof globalThis.document, "undefined");
  assert.equal(typeof globalThis.window, "undefined");
});
