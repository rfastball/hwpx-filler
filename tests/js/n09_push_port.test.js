/* N-09 푸시 포트 — **가로채기가 실제로 성립하는가**를 실제 조각들로 잰다.
 *
 * 이 파일이 지는 것은 저장소가 두 번 겪은 결함류다: 제품 스냅샷 처리기가 푸시를 값으로
 * 붙들면, selftest 프로브가 통로를 갈아끼워도 **호스트 푸시가 그 자리를 우회한다**. 그러면
 * 프로브는 "푸시 0" 을 보고 그 침묵을 배선 부재로 읽는다 — 측정기가 조용히 틀린다.
 *
 *   · N-07 (#379 §5): 파사드가 구성 산물 `push` 를 캡처 → `mirror_pushes` 1→0,
 *     `reject_pushes` 1→0. 실앱 게이트가 잡았고 기준 worktree 대조로 회귀 확정.
 *   · N-08 §9: 프로브를 프런트로 옮기면서 관측이 주입된 `ctx.push` 위에 섰다. 주입만으로는
 *     닫히지 않는다 — 제품 처리기가 자기 사본을 부르면 여전히 우회한다.
 *
 * 그래서 여기서는 **네 조각을 진짜로 이어** 잰다: `push_port` + `product_api`(제품 처리기)
 * + `runner`(ctx.push 접근자) + 프로브가 하는 것과 같은 통로 교체. 그리고 각 단언마다
 * **음성 대조**를 세운다 — 결함을 되살린 배선으로 같은 시나리오를 돌려 빨간불을 확인한다.
 * 양성만 있으면 "이 단언이 초록인데도 사용자가 틀린 걸 보는 경로"가 남는다.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { createPushPort } from "../../frontend/src/push_port.js";
import { createProductApi } from "../../frontend/src/product_api.js";
import { createSelftestRunner } from "../../frontend/src/selftest/runner.js";

/** 배포된 푸시 진입점의 대역 — 도착한 것을 그대로 기록한다(렌더러 자리). */
function makeBasePush() {
  const arrived = [];
  const push = (screen, snapshot) => { arrived.push([screen, snapshot]); };
  return { push, arrived };
}

/** 제품 파사드를 **올바른** 배선(포트 경유)으로 세운다 — `compat.js` 와 같은 모양. */
function productApiOverPort(port) {
  return createProductApi({
    handlers: {
      snapshot: (payload) => port.dispatch(payload.screen, payload.snapshot),
      "close-request": () => undefined,
      preferences: () => [],
      notice: () => undefined,
    },
  });
}

/** 제품 파사드를 **되살린 결함**(기반 푸시를 값으로 캡처)으로 세운다 — 음성 대조용. */
function productApiCapturingBase(basePush) {
  return createProductApi({
    handlers: {
      snapshot: (payload) => basePush(payload.screen, payload.snapshot),
      "close-request": () => undefined,
      preferences: () => [],
      notice: () => undefined,
    },
  });
}

function deliverSnapshot(api, screen, snapshot) {
  return api.deliver({ version: 1, event: "snapshot", payload: { screen, snapshot } });
}

/* ══════════════ 1. 포트 단독 계약 ══════════════ */

test("포트 — dispatch 는 안정된 함수이고 안에서 늦게 결속한다", () => {
  const { push, arrived } = makeBasePush();
  const port = createPushPort(push);

  /* 값으로 붙들어도 안전해야 한다 — `window.__push` 별칭이 이렇게 산다. */
  const held = port.dispatch;

  held("job", { n: 1 });
  assert.deepEqual(arrived, [["job", { n: 1 }]]);

  const seen = [];
  port.override((screen, snapshot) => { seen.push([screen, snapshot]); });

  held("job", { n: 2 });
  assert.deepEqual(seen, [["job", { n: 2 }]], "붙들어 둔 dispatch 가 교체를 못 봤습니다");
  assert.deepEqual(arrived, [["job", { n: 1 }]], "교체 중인데 기반으로 샜습니다");

  port.restore();
  held("job", { n: 3 });
  assert.deepEqual(arrived, [["job", { n: 1 }], ["job", { n: 3 }]]);
});

test("포트 — 기반 함수로 되돌리는 관용이 교체 해제와 같은 뜻이다", () => {
  const { push } = makeBasePush();
  const port = createPushPort(push);

  port.override(() => {});
  assert.equal(port.overridden, true);

  /* 프로브는 `ctx.push = 원본` 으로 복원한다 — 그 원본은 곧 기반 함수다. */
  port.override(port.base);
  assert.equal(port.overridden, false, "기반으로 되돌렸는데 교체가 남아 있습니다");
});

test("포트 — 기반이 함수가 아니면 시끄럽게 거절한다", () => {
  assert.throws(() => createPushPort(null), TypeError);
  assert.throws(() => createPushPort(undefined), TypeError);
});

/* ══════════════ 2. 제품 푸시가 갈아끼운 통로를 지난다 (핵심) ══════════════ */

test("제품 스냅샷 처리기가 **교체된 통로**를 지난다 — mirror_pushes 가 사는 이유", () => {
  const { push, arrived } = makeBasePush();
  const port = createPushPort(push);
  const api = productApiOverPort(port);

  // 프로브가 하는 일 그대로 — 통로를 기록용 래퍼로 갈아끼운다.
  const observed = [];
  port.override((screen, snapshot) => { observed.push([screen, snapshot]); });

  const result = deliverSnapshot(api, "job", { rows: 1 });

  assert.equal(result.ok, true, `deliver 실패: ${JSON.stringify(result)}`);
  assert.deepEqual(observed, [["job", { rows: 1 }]],
    "제품 푸시가 가로채기를 우회했습니다 — 프로브는 이것을 '푸시 0'(배선 부재)으로 읽습니다");
  assert.deepEqual(arrived, [], "교체 중인데 기반으로 샜습니다");
});

test("음성 대조 — 결함을 되살리면(기반을 값으로 캡처) 위 단언이 빨개진다", () => {
  const { push, arrived } = makeBasePush();
  const port = createPushPort(push);
  const api = productApiCapturingBase(push);   // ← N-07 이 겪은 바로 그 배선

  const observed = [];
  port.override((screen, snapshot) => { observed.push([screen, snapshot]); });

  deliverSnapshot(api, "job", { rows: 1 });

  /* 이것이 음성 대조다: 관측은 0 이고 푸시는 기반으로 샌다 = 프로브가 눈이 먼 상태.
     위 양성 테스트가 이 상황에서 실패한다는 것을 여기서 **실행으로** 확인한다. */
  assert.deepEqual(observed, [], "음성 대조가 성립하지 않습니다 — 이 테스트가 결함을 못 만듭니다");
  assert.deepEqual(arrived, [["job", { rows: 1 }]]);
});

/* ══════════════ 3. 러너의 ctx.push 접근자가 포트에 닿는다 ══════════════ */

/** 프로브 하나를 담은 최소 러너 — 프로브가 `ctx.push` 를 갈아끼우고, 그 사이에 도착한
 *  **호스트 푸시**(제품 파사드 경유)를 관측한다. `job_mirror` 가 하는 일의 최소형이다. */
function runnerWithInterceptingProbe(port, api, options) {
  const runner = createSelftestRunner({
    doc: {}, win: {},
    push: port.dispatch,
    pushPort: options && options.withoutPort ? undefined : port,
    host: { provides: [], request: () => undefined },
    now: () => Date.now(),
    sleep: (ms) => new Promise((resolve) => { setTimeout(resolve, ms); }),
  });

  runner.register({
    name: "intercepting", keys: ["observed"], cluster: "T", owner: "frontend",
    modes: ["t"], legacySite: 1, deadlineMs: 1000,
    deadlineRationale: "테스트 전용 프로브 — 레거시 표에 없다.",
    run(ctx) {
      const real = ctx.push;
      const seen = [];
      ctx.push = (screen, snapshot) => { seen.push([screen, snapshot]); };

      // 호스트가 이 창으로 스냅샷을 밀어 넣는다(파이썬 → __hwpx.deliver → 처리기).
      deliverSnapshot(api, "job", { rows: 7 });

      ctx.push = real;                       // 프로브의 복원 관용
      return { observed: seen };
    },
  });
  return runner;
}

test("프로브가 ctx.push 를 갈아끼우면 **호스트 푸시**가 그 통로를 지난다", async () => {
  const { push, arrived } = makeBasePush();
  const port = createPushPort(push);
  const api = productApiOverPort(port);

  const report = await runnerWithInterceptingProbe(port, api).run("t", {});

  assert.equal(report.ok, true, `러너 실패: ${JSON.stringify(report.errors)}`);
  assert.deepEqual(report.results.observed, [["job", { rows: 7 }]],
    "프로브가 도착 푸시를 못 봤습니다 — mirror_pushes/reject_pushes 가 빈 배열이 됩니다");
  assert.deepEqual(arrived, [], "교체 중인데 기반으로 샜습니다");
});

test("음성 대조 — 포트를 주입하지 않으면(지역 사본) 같은 프로브가 눈이 먼다", async () => {
  const { push, arrived } = makeBasePush();
  const port = createPushPort(push);
  const api = productApiOverPort(port);

  /* `pushPort` 없이 = `ctx.push` 가 평범한 데이터 프로퍼티 = 교체가 지역에만 남는다.
     N-08 이 남긴 감도 공백(§9)이 정확히 이 모양이고, 이 대조가 그것을 재현한다. */
  const report = await runnerWithInterceptingProbe(port, api, { withoutPort: true }).run("t", {});

  assert.equal(report.ok, true);
  assert.deepEqual(report.results.observed, [],
    "음성 대조가 성립하지 않습니다 — 포트 없이도 관측된다면 이 테스트는 아무것도 지키지 않습니다");
  assert.deepEqual(arrived, [["job", { rows: 7 }]], "푸시는 기반으로 새어 있어야 한다");
});

test("러너는 프로브마다 통로를 원복한다 — 실패한 프로브가 통로를 들고 죽지 않는다", async () => {
  const { push, arrived } = makeBasePush();
  const port = createPushPort(push);

  const runner = createSelftestRunner({
    doc: {}, win: {},
    push: port.dispatch, pushPort: port,
    host: { provides: [], request: () => undefined },
    now: () => Date.now(),
    sleep: (ms) => new Promise((resolve) => { setTimeout(resolve, ms); }),
  });

  runner.register({
    name: "leaky", keys: ["x"], cluster: "T", owner: "frontend",
    modes: ["t"], legacySite: 1, deadlineMs: 1000,
    deadlineRationale: "테스트 전용.",
    run(ctx) {
      ctx.push = () => {};       // 갈아끼운 채로
      throw new Error("프로브가 통로를 들고 죽는다");
    },
  });

  const report = await runner.run("t", {});
  assert.equal(report.ok, false, "던진 프로브는 실패로 확정돼야 한다");

  /* 레거시에는 이 보장이 없었다 — 전역을 갈아끼운 채 죽으면 그 잔존이 다음 프로브와
     제품 푸시를 전부 오염시켰다. */
  assert.equal(port.overridden, false, "실패한 프로브의 교체가 남았습니다 — 다음 프로브가 오염됩니다");
  port.dispatch("job", { after: true });
  assert.deepEqual(arrived, [["job", { after: true }]], "원복 뒤 기반으로 가야 한다");
});
