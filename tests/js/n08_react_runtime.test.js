/* 클러스터 R(React 실런타임 마커) 단위 계약 — R2-04 · #408.
 *
 * 이 파일이 실측하는 것:
 *  ① 공개 표면 — 클러스터 id·키·프로브 정의가 러너 등록 계약(REQUIRED_FIELDS·신설 축의
 *     deadlineRationale 의무)을 지킨다. 레거시 후계가 아니므로 출처 상수 대응의 정의역
 *     밖이라는 사실도 여기 못박는다.
 *  ② 판정 술어 — 프로브와 이 테스트가 **같은 하나**(`judgeReactRuntime`)를 쓴다. 양성 2 ·
 *     음성 7 을 창 없이 세운다(실창 값 단언은 live 게이트 소유).
 *  ③ 실행 경로 — **실 러너**에 등록해 full 모드로 몰았을 때: 정상 마커 문서에서 증거 키가
 *     실리고, 위반 문서에서는 러너의 `report.errors` 에 계약 위반이 서고 키가 빠진다.
 *     판정기를 테스트-지역으로 재구현하지 않는다 — 제품 경로 실물이 던지는 것을 본다.
 *  ④ 모드 경계 — full 밖(geometry_only 등)의 plan 에 이 프로브가 없다.
 *  ⑤ 순수성 — bare import 는 DOM·전역을 만들지 않는다.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
  REACT_RUNTIME_CLUSTER,
  REACT_RUNTIME_KEYS,
  createReactRuntimeProbes,
  judgeReactRuntime,
} from "../../frontend/src/selftest/probes/react_runtime.js";
import { createSelftestRunner } from "../../frontend/src/selftest/runner.js";

/* ────────────────────────── 가짜 시계 (n08 공용 패턴) ────────────────────────── */

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

/* ────────────────────────── DOM 대역 ────────────────────────── */

/** `#reactRoot` 하나와 마커 속성만 아는 최소 문서. 프로브가 쓰는 판독 두 문장
 *  (getElementById · querySelectorAll)만 구현한다 — 가짜 React 를 만들지 않는다. */
function fakeDoc({ mounted, storeRev, extraMarked = 0, rootPresent = true }) {
  const attrs = {};
  if (mounted !== undefined) attrs["data-react-mounted"] = mounted;
  if (storeRev !== undefined) attrs["data-react-store-rev"] = storeRev;
  const root = {
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null;
    },
  };
  return {
    getElementById(id) {
      return id === "reactRoot" && rootPresent ? root : null;
    },
    querySelectorAll(selector) {
      assert.equal(selector, "[data-react-mounted]");
      const marked = [];
      if (rootPresent && attrs["data-react-mounted"] !== undefined) marked.push(root);
      for (let i = 0; i < extraMarked; i += 1) marked.push({});
      return marked;
    },
  };
}

function buildRunner(doc) {
  const clock = createClock();
  const runner = createSelftestRunner({
    doc,
    win: {},
    push: () => {},
    services: {},
    host: { request: async () => ({}), provides: [] },
    now: clock.now,
    sleep: clock.sleep,
  });
  runner.registerAll(createReactRuntimeProbes());
  return { runner, clock };
}

/* ────────────────────────── ① 공개 표면 ────────────────────────── */

test("클러스터 표면 — id R · 키 하나 · 등록 계약 충족", () => {
  assert.equal(REACT_RUNTIME_CLUSTER, "R");
  assert.deepEqual([...REACT_RUNTIME_KEYS], ["react_runtime"]);

  const defs = createReactRuntimeProbes();
  assert.equal(defs.length, 1);
  const [def] = defs;
  assert.equal(def.name, "react_runtime");
  assert.deepEqual(def.keys, ["react_runtime"]);
  assert.equal(def.cluster, "R");
  assert.equal(def.owner, "frontend");
  assert.deepEqual(def.modes, ["full"]);
  /* 레거시 부재 신설 축 — 자리 번호는 전 레거시 구간(최대 3993)을 넘는 관례값이고,
     예산은 rationale 의무가 진다(러너 계약). */
  assert.ok(def.legacySite > 3993);
  assert.ok(Number.isInteger(def.deadlineMs) && def.deadlineMs > 0);
  assert.equal(typeof def.deadlineRationale, "string");
  assert.ok(def.deadlineRationale.length > 0);
  assert.equal(typeof def.precondition, "function");
  assert.equal(typeof def.run, "function");
});

test("정의 생성은 순수하다 — DOM·전역을 만지지 않는다", () => {
  const before = Object.keys(globalThis).length;
  createReactRuntimeProbes();
  assert.equal(Object.keys(globalThis).length, before);
  assert.equal(typeof globalThis.document, "undefined");
  assert.equal(typeof globalThis.window, "undefined");
});

/* ────────────────────────── ② 판정 술어 (양성·음성) ────────────────────────── */

test("판정 술어 — 양성: 커밋 마커·십진 rev·마커 1", () => {
  assert.equal(judgeReactRuntime({ mounted: "1", store_rev: "0", roots: 1 }), null);
  assert.equal(judgeReactRuntime({ mounted: "1", store_rev: "12", roots: 1 }), null);
});

test("판정 술어 — 음성 7: 각각 겨눈 사유로만 문다", () => {
  const cases = [
    [{ mounted: null, store_rev: "0", roots: 1 }, /data-react-mounted/],
    [{ mounted: "0", store_rev: "0", roots: 1 }, /data-react-mounted/],
    [{ mounted: "1", store_rev: null, roots: 1 }, /data-react-store-rev/],
    [{ mounted: "1", store_rev: "abc", roots: 1 }, /data-react-store-rev/],
    [{ mounted: "1", store_rev: "1.5", roots: 1 }, /data-react-store-rev/],
    [{ mounted: "1", store_rev: "0", roots: 0 }, /정확히 1/],
    [{ mounted: "1", store_rev: "0", roots: 2 }, /정확히 1/],
  ];
  for (const [value, pattern] of cases) {
    const verdict = judgeReactRuntime(value);
    assert.equal(typeof verdict, "string", JSON.stringify(value));
    assert.match(verdict, pattern, JSON.stringify(value));
  }
});

/* ────────────────────────── ③ 실행 경로 (실 러너) ────────────────────────── */

test("실 러너 full — 정상 마커 문서에서 증거 키가 실린다", async () => {
  const { runner, clock } = buildRunner(fakeDoc({ mounted: "1", storeRev: "0" }));
  const report = await settle(clock, runner.run("full", {}));
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.deepEqual(report.results.react_runtime, {
    mounted: "1", store_rev: "0", roots: 1,
  });
});

test("실 러너 full — 위반 문서에서 **제품 경로가** 던지고 키가 빠진다", async () => {
  /* 마커는 있되(사전 조건 통과) rev 가 비십진 — 본판독의 판정이 문다. */
  const { runner, clock } = buildRunner(fakeDoc({ mounted: "1", storeRev: "stale" }));
  const report = await settle(clock, runner.run("full", {}));
  assert.equal(report.ok, false);
  assert.equal(Object.prototype.hasOwnProperty.call(report.results, "react_runtime"), false);
  const [error] = report.errors;
  assert.equal(error.probe, "react_runtime");
  assert.equal(error.code, "contract_violation");
  assert.match(error.message, /data-react-store-rev/);
});

test("실 러너 full — 마커 규율 census: 마커 단 요소가 둘이면 문다", async () => {
  const { runner, clock } = buildRunner(
    fakeDoc({ mounted: "1", storeRev: "3", extraMarked: 1 }),
  );
  const report = await settle(clock, runner.run("full", {}));
  assert.equal(report.ok, false);
  assert.match(report.errors[0].message, /정확히 1/);
});

test("사전 조건 — 마커가 서기 전에는 거짓, 선 뒤에는 참(본판독으로 넘어간다)", () => {
  const [def] = createReactRuntimeProbes();
  const notYet = { doc: fakeDoc({}) };
  assert.equal(def.precondition(notYet), false);
  const rootless = { doc: fakeDoc({ mounted: "1", storeRev: "0", rootPresent: false }) };
  assert.equal(def.precondition(rootless), false);
  const ready = { doc: fakeDoc({ mounted: "1", storeRev: "0" }) };
  assert.equal(def.precondition(ready), true);
});

/* ────────────────────────── ④ 모드 경계 ────────────────────────── */

test("full 밖의 plan 에는 이 프로브가 없다", () => {
  const { runner } = buildRunner(fakeDoc({ mounted: "1", storeRev: "0" }));
  assert.deepEqual(runner.plan("full").map((p) => p.name), ["react_runtime"]);
  assert.deepEqual(runner.plan("geometry_only").map((p) => p.name), []);
  assert.deepEqual(runner.plan("theme_write").map((p) => p.name), []);
});

/* ────────────────────────── ⑤ 순수성 ────────────────────────── */

test("bare import 는 순수하다 — DOM·전역을 만들지 않는다", async () => {
  const before = Object.keys(globalThis).length;
  const again = await import(
    `../../frontend/src/selftest/probes/react_runtime.js?pure=${process.hrtime.bigint()}`
  );
  assert.equal(typeof again.createReactRuntimeProbes, "function");
  assert.equal(Object.keys(globalThis).length, before);
});
