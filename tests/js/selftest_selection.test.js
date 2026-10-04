/* N-08 확장 — plan()/run() 의 부분 선택(프로브·클러스터 + after 전이 폐포). */
import test from "node:test";
import assert from "node:assert/strict";

import {
  ERROR_CODES,
  HOST_OPS,
  SELECTION_EVIDENCE_KEY,
  SelftestProbeError,
  createSelftestRunner,
} from "../../frontend/src/selftest/runner.js";
import { registerAllProbes } from "../../frontend/src/selftest/probes/index.js";

function createCaps(overrides) {
  let clock = 0;
  return {
    doc: { body: {}, readyState: "complete" },
    win: {},
    push: () => {},
    services: {},
    host: {
      provides: HOST_OPS.slice(),
      request: (op, payload) => ({ op, payload }),
    },
    now: () => clock,
    sleep: () => Promise.resolve(),
    ...(overrides || {}),
  };
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

/* ────────────────────────── 수공 레지스트리 — 전이 폐포 ────────────────────────── */

function smallRunner() {
  const runner = createSelftestRunner(createCaps());
  runner.register(baseProbe({ name: "root", keys: ["root"], legacySite: 1000 }));
  runner.register(baseProbe({
    name: "mid", keys: ["mid"], legacySite: 1001, after: ["root"],
  }));
  runner.register(baseProbe({
    name: "leaf", keys: ["leaf"], legacySite: 1002, after: ["mid"],
  }));
  runner.register(baseProbe({ name: "unrelated", keys: ["unrelated"], legacySite: 1003 }));
  return runner;
}

test("프로브 이름 선택 — after 전이 폐포만 돌고, 전체 순서의 부분 수열이다", () => {
  const runner = smallRunner();
  const full = runner.plan("full").map((p) => p.name);
  const selected = runner.plan("full", { probes: ["leaf"] }).map((p) => p.name);
  assert.deepEqual(selected, ["root", "mid", "leaf"]);
  assert.equal(selected.includes("unrelated"), false);
  /* 부분 수열 — 전체 순서에서 같은 상대 순서로 나타난다. */
  let cursor = 0;
  for (const name of selected) {
    const idx = full.indexOf(name, cursor);
    assert.ok(idx >= cursor, `${name} 이 전체 순서의 부분 수열이 아닙니다.`);
    cursor = idx + 1;
  }
});

test("선택이 없으면 오늘과 똑같다", () => {
  const runner = smallRunner();
  assert.deepEqual(runner.plan("full", undefined).map((p) => p.name), runner.plan("full").map((p) => p.name));
  assert.deepEqual(runner.plan("full", null).map((p) => p.name), runner.plan("full").map((p) => p.name));
  assert.deepEqual(runner.plan("full", {}).map((p) => p.name), runner.plan("full").map((p) => p.name));
});

test("알 수 없는 선택 이름은 시끄럽게 거절된다", () => {
  const runner = smallRunner();
  assert.throws(() => runner.plan("full", { probes: ["ghost"] }), (err) => {
    assert.ok(err instanceof SelftestProbeError);
    assert.equal(err.code, ERROR_CODES.CONTRACT);
    assert.match(err.detail, /ghost/);
    assert.match(err.detail, /full/);
    return true;
  });
});

test("빈 배열·비문자열 선택은 계약 위반이다", () => {
  const runner = smallRunner();
  assert.throws(() => runner.plan("full", { probes: [] }), (err) => {
    assert.equal(err.code, ERROR_CODES.CONTRACT);
    return true;
  });
  assert.throws(() => runner.plan("full", { probes: "root" }), /문자열 배열/);
  assert.throws(() => runner.plan("full", { probes: [""] }), /문자열 배열/);
  assert.throws(() => runner.plan("full", { probes: [1] }), /문자열 배열/);
});

test("이름이 클러스터 id 와 동시에 걸리면 모호함으로 거절된다", () => {
  const runner = createSelftestRunner(createCaps());
  runner.register(baseProbe({ name: "T", keys: ["T"], cluster: "T", legacySite: 1000 }));
  assert.throws(() => runner.plan("full", { probes: ["T"] }), /양쪽에 걸립니다/);
});

/* ────────────────────────── 클러스터 선택 + 묶음 간 간선(진짜 레지스트리) ────────────────────────── */

function fullRegistryRunner() {
  const runner = createSelftestRunner(createCaps());
  registerAllProbes(runner);
  return runner;
}

test("클러스터 선택은 그 클러스터의 프로브 + 전이 폐포를 돈다(교차 묶음 간선 포함)", () => {
  const runner = fullRegistryRunner();
  const names = new Set(runner.plan("full", { probes: ["data_picker"] }).map((p) => p.name));
  assert.ok(names.has("data_picker"));
  /* CROSS_CLUSTER_EDGES: data_picker after milestone_h_wave1(B), milestone_h_wave1 after
     job_data_first(C). 둘 다 전이 폐포에 들어와야 한다. */
  assert.ok(names.has("milestone_h_wave1"), "교차 묶음 간선(B)이 폐포에 없습니다.");
  assert.ok(names.has("job_data_first"), "교차 묶음 간선(C)이 폐포에 없습니다.");
});

test("클러스터 id 선택 — 그 클러스터가 모드에 낸 프로브 전체가 들어온다", () => {
  const runner = fullRegistryRunner();
  const full = runner.plan("full");
  const byCluster = full.filter((p) => p.cluster === "D").map((p) => p.name);
  const selected = new Set(runner.plan("full", { probes: ["D"] }).map((p) => p.name));
  for (const name of byCluster) assert.ok(selected.has(name), `${name} 이 D 선택에 없습니다.`);
});

/* ────────────────────────── run()/toEvidence() — selection 보고 ────────────────────────── */

async function settleSoon(promise) {
  let result;
  let threw = false;
  promise.then((v) => { result = v; }, (e) => { threw = true; result = e; });
  for (let i = 0; i < 100; i += 1) await Promise.resolve();
  if (threw) throw result;
  return result;
}

test("선택 없는 run — evidence 에 selftest_selection 키가 없고 순서는 전체와 같다", async () => {
  const runner = smallRunner();
  const report = await settleSoon(runner.run("full", {}));
  assert.equal(report.selection, null);
  assert.deepEqual(report.order, runner.plan("full").map((p) => p.name));
  const evidence = runner.toEvidence(report);
  assert.equal(Object.prototype.hasOwnProperty.call(evidence, SELECTION_EVIDENCE_KEY), false);
});

test("선택 있는 run — report.selection 과 evidence 가 requested/planned/partial 을 싣는다", async () => {
  const runner = smallRunner();
  const report = await settleSoon(runner.run("full", { probes: ["leaf"] }));
  assert.deepEqual(report.selection, {
    requested: ["leaf"],
    planned: ["root", "mid", "leaf"],
    partial: true,
  });
  assert.deepEqual(report.order, ["root", "mid", "leaf"]);
  const evidence = runner.toEvidence(report);
  assert.deepEqual(evidence[SELECTION_EVIDENCE_KEY], {
    requested: ["leaf"],
    planned: ["root", "mid", "leaf"],
    partial: true,
  });
});
