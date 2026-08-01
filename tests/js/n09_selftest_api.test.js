/* N-09 레인 A — 시험 능력 프로토콜(`frontend/src/selftest/api.js`) 단위 계약.
 *
 * 이 파일이 겨누는 것은 프로브가 무엇을 재는가가 **아니다**(그건 N-08 러너 테스트의 몫).
 * 여기서 세는 것은 셋이다:
 *
 *  ① **누가 이 표면을 켤 수 있는가.** 쿼리스트링·해시·빌드 플래그처럼 페이지가 스스로
 *     만들 수 있는 조건으로는 아무것도 서지 않는다. 호스트 프로세스 메모리 토큰의
 *     일회 클레임만이 설치 조건이고, 실패한 핸드셰이크는 **아무것도 남기지 않는다**.
 *  ② **일회성이 진짜 일회인가.** runId 하나, 실행 하나, 종결 회수 한 번. 재시작·재조회는
 *     조용한 성공이 아니라 구조화된 거절이다.
 *  ③ **시한이 죽은 선언이 아닌가.** 레거시 `_probe_late` 는 만료에 `else` 가 없어 낡은 값을
 *     정상 모양으로 회수했다(runner.js 머리말 (가)). 그래서 여기서는 "시한 뒤에 도착한
 *     완주" 까지 실패로 확정되는지를 양성으로 세운다 — 시한을 지나서도 초록인 경로가 하나라도
 *     있으면 그 시한은 선언만 살아 있는 것이다.
 *
 * 시계는 주입한다(가상 시각). 러너는 두 벌을 쓴다: 상태 기계 타이밍은 **가짜 러너**로 손에
 * 쥐고, 증거 통과는 **진짜 러너**(`createSelftestRunner`)로 센다 — 증거의 모양을 여기서 다시
 * 구현하면 같은 판정을 두 곳이 지게 되고, 그 둘은 반드시 갈라진다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  DEFAULT_DEADLINE_MS,
  MIN_TOKEN_LENGTH,
  SELFTEST_ACTIONS,
  SELFTEST_ERROR_CODES,
  SELFTEST_GLOBAL,
  SELFTEST_STATES,
  SELFTEST_VERSION,
  installSelftestApi,
} from "../../frontend/src/selftest/api.js";
import { createSelftestRunner } from "../../frontend/src/selftest/runner.js";

const SRC = readFileSync(
  new URL("../../frontend/src/selftest/api.js", import.meta.url),
  "utf8",
);

const CODES = SELFTEST_ERROR_CODES;
const STATES = SELFTEST_STATES;

/** 호스트가 낸 것과 같은 급의 토큰(45자). 깊은 훑기의 바늘이므로 다른 문자열과 겹치지 않는다. */
const TOKEN = "hwpxselftest-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6";

/* ────────────────────────── 대역 ────────────────────────── */

/** 손으로 지은 창. 제품 창의 표면을 흉내 내지 않는다 — 이 모듈이 만지는 것은
 *  `crypto.getRandomValues` 하나뿐이고, 그 좁음 자체가 계약이다. */
function createWin(extra) {
  let seed = 7;
  return {
    crypto: {
      getRandomValues(bytes) {
        for (let i = 0; i < bytes.length; i += 1) {
          seed = (seed * 31 + 17) % 251;
          bytes[i] = seed;
        }
        return bytes;
      },
    },
    ...(extra || {}),
  };
}

function createClock() {
  let clock = 0;
  return {
    now: () => clock,
    advance(ms) { clock += ms; },
  };
}

/** 손으로 해소하는 러너. `run` 은 우리가 풀어 줄 때까지 매달려 있다. */
function createFakeRunner(overrides) {
  const calls = [];
  let settle = null;
  const runner = {
    calls,
    run(mode, options) {
      calls.push({ mode, options });
      return new Promise((resolve, reject) => { settle = { resolve, reject }; });
    },
    toEvidence(report) {
      return { ...(report.results || {}) };
    },
    finish(report) { settle.resolve(report); },
    explode(error) { settle.reject(error); },
    ...(overrides || {}),
  };
  return runner;
}

/** 아무것도 재지 않은 완주 보고서 — 프로브 내용이 판정에 안 걸리는 자리에서 쓴다. */
function emptyReport() {
  return {
    ok: true, mode: "full", order: [], results: {},
    errors: [], skipped: [], timings: {},
  };
}

/** 마이크로태스크를 충분히 흘린다. 이 프로토콜은 타이머를 걸지 않으므로 이것으로 족하다. */
async function flush() {
  for (let step = 0; step < 60; step += 1) await Promise.resolve();
}

/** 설치까지 마친 표준 대역. */
function band(overrides) {
  const win = createWin();
  const clock = createClock();
  const runner = createFakeRunner();
  const conf = {
    win,
    claimToken: () => TOKEN,
    createRunner: () => runner,
    now: clock.now,
    ...(overrides || {}),
  };
  const outcome = installSelftestApi(conf);
  return { win, clock, runner, outcome, api: win[SELFTEST_GLOBAL] };
}

function startRequest(extra) {
  return { version: SELFTEST_VERSION, action: "start", mode: "full", ...(extra || {}) };
}

/* ────────────────────────── 양성 — 표면 ────────────────────────── */

test("동결 표면 — `{version, run}` 딱 둘이고 되쓸 수 없다", () => {
  const { win, outcome } = band();

  assert.deepEqual(outcome, { ok: true, action: null, installed: true, state: STATES.READY });
  const api = win[SELFTEST_GLOBAL];
  assert.equal(api.version, 1);
  assert.equal(typeof api.run, "function");
  assert.deepEqual(Object.keys(api).sort(), ["run", "version"]);
  assert.equal(Object.isFrozen(api), true);

  const descriptor = Object.getOwnPropertyDescriptor(win, SELFTEST_GLOBAL);
  assert.equal(descriptor.writable, false);
  assert.equal(descriptor.configurable, false);
  assert.equal(descriptor.enumerable, false);
});

test("상수 표면 — 액션 둘·버전 1·코드 열둘", () => {
  assert.equal(SELFTEST_VERSION, 1);
  assert.equal(SELFTEST_GLOBAL, "__hwpxTest");
  assert.deepEqual(SELFTEST_ACTIONS.slice(), ["start", "poll"]);
  assert.equal(Object.isFrozen(SELFTEST_ACTIONS), true);
  assert.equal(Object.isFrozen(SELFTEST_ERROR_CODES), true);
  assert.deepEqual(Object.values(CODES).sort(), [
    "already_claimed", "already_consumed", "already_running", "deadline_exceeded",
    "internal", "malformed_request", "run_failed", "unauthorized", "unknown_action",
    "unknown_run", "unsupported_version",
  ]);
  /* 시한 기본값은 러너 최악(68000)과 프로세스 시한(90000) **사이**여야 발화한다. */
  assert.ok(DEFAULT_DEADLINE_MS > 68000 && DEFAULT_DEADLINE_MS < 90000);
  assert.equal(MIN_TOKEN_LENGTH, 32);
});

/* ────────────────────────── 양성 — 상태 기계 ────────────────────────── */

test("start — 동기 확인과 신선한 runId 를 즉시 돌려준다(Promise 가 아니다)", () => {
  const { api, runner } = band();

  const ack = api.run(startRequest({ input: { theme: "dark" }, flags: { packaged: true } }));

  assert.equal(typeof ack.then, "undefined", "run 은 Promise 를 돌려주지 않는다.");
  assert.equal(ack.ok, true);
  assert.equal(ack.action, "start");
  assert.equal(ack.state, STATES.RUNNING);
  assert.equal(ack.mode, "full");
  assert.equal(ack.deadlineMs, DEFAULT_DEADLINE_MS);
  assert.match(ack.runId, /^[0-9a-f]{32}$/);
  /* 러너 구성·실행은 발사 후 망각이라 동기 확인 시점엔 아직 불리지 않았다. */
  assert.equal(runner.calls.length, 0);
});

test("start 는 러너를 다음 태스크에서 몬다 — mode·input·flags 가 그대로 간다", async () => {
  const { api, runner } = band();
  api.run(startRequest({ mode: "packaged", input: "dark", flags: { offline: true } }));
  await flush();
  assert.deepEqual(runner.calls, [
    { mode: "packaged", options: { input: "dark", flags: { offline: true } } },
  ]);
});

test("poll — 도는 중은 도는 중이라고 말한다", async () => {
  const { api, clock } = band();
  const runId = api.run(startRequest()).runId;
  await flush();
  clock.advance(1200);

  const polled = api.run({ version: 1, action: "poll", runId });

  assert.deepEqual(polled, {
    ok: true, action: "poll", runId, state: STATES.RUNNING,
    elapsedMs: 1200, deadlineMs: DEFAULT_DEADLINE_MS,
  });
});

test("poll — 종결 결과는 정확히 한 번 회수된다", async () => {
  const { api, runner, clock } = band();
  const runId = api.run(startRequest()).runId;
  await flush();
  clock.advance(3000);
  runner.finish({
    ok: true, mode: "full", order: ["a", "b"],
    results: { a: 1, b: 2 }, errors: [], skipped: [], timings: { a: 10, b: 20 },
  });
  await flush();

  const first = api.run({ version: 1, action: "poll", runId });
  assert.equal(first.ok, true);
  assert.equal(first.state, STATES.SUCCEEDED);
  assert.equal(first.mode, "full");
  assert.deepEqual(first.evidence, { a: 1, b: 2 });
  assert.deepEqual(first.order, ["a", "b"]);
  assert.deepEqual(first.timings, { a: 10, b: 20 });
  assert.equal(first.elapsedMs, 3000);

  const replay = api.run({ version: 1, action: "poll", runId });
  assert.deepEqual(replay, {
    ok: false, code: CODES.ALREADY_CONSUMED, action: "poll",
    runId, state: STATES.CONSUMED,
  });
});

test("증거 통과 — 실패한 프로브의 키는 없고 `error` 가 선다(진짜 러너)", async () => {
  const { api, runner } = realRunnerBand();
  const runId = api.run(startRequest()).runId;
  await flush();

  const polled = api.run({ version: 1, action: "poll", runId });

  assert.equal(polled.ok, false, "프로브가 실패한 실행은 ok:true 로 접히지 않는다.");
  assert.equal(polled.code, CODES.RUN_FAILED);
  assert.equal(polled.state, STATES.FAILED);
  /* 성공한 프로브의 키만 남고, 실패한 프로브의 키는 증거에 **없다**. */
  assert.deepEqual(Object.keys(polled.evidence).sort(), ["error", "probe_ok"]);
  assert.equal(polled.evidence.probe_ok, "ok");
  assert.match(polled.evidence.error, /probe_bad/);
  /* 문자열로 접히기 전의 구조화 원형도 함께 온다 — 파이썬이 코드로 가른다. */
  assert.equal(polled.errors.length, 1);
  assert.equal(polled.errors[0].probe, "probe_bad");
  assert.equal(typeof polled.errors[0].code, "string");
  assert.deepEqual(polled.skipped, []);
  assert.ok(runner.probes().length === 2);

  const replay = api.run({ version: 1, action: "poll", runId });
  assert.equal(replay.code, CODES.ALREADY_CONSUMED);
});

/** 진짜 러너를 문 대역 — 프로브 둘 중 하나는 던진다. */
function realRunnerBand() {
  const win = createWin();
  const clock = createClock();
  const runner = createSelftestRunner({
    doc: {}, win: {}, push: () => {},
    host: { provides: [], request: () => null },
    now: clock.now,
    sleep: () => Promise.resolve(),
  });
  const common = {
    cluster: "T", owner: "frontend", modes: ["full"], deadlineMs: 0,
    deadlineRationale: "테스트 대역 — 동기 측정.",
  };
  runner.register({
    ...common, name: "probe_ok", keys: ["probe_ok"], legacySite: 1000,
    run: () => ({ probe_ok: "ok" }),
  });
  runner.register({
    ...common, name: "probe_bad", keys: ["probe_bad"], legacySite: 1001,
    run: () => { throw new Error("일부러 실패"); },
  });
  installSelftestApi({
    win, claimToken: () => TOKEN, createRunner: () => runner, now: clock.now,
  });
  return { win, clock, runner, api: win[SELFTEST_GLOBAL] };
}

test("구조화 오류 모양 — 모든 거절이 `{ok:false, code, action}` 이고 직렬화된다", () => {
  const { api } = band();
  const rejections = [
    api.run(null),
    api.run({ version: 2, action: "start", mode: "full" }),
    api.run({ version: 1, action: "  " }),
    api.run({ version: 1, action: "restart" }),
    api.run({ version: 1, action: "start" }),
    api.run({ version: 1, action: "poll" }),
    api.run({ version: 1, action: "poll", runId: "deadbeef" }),
  ];
  for (const rejection of rejections) {
    assert.equal(rejection.ok, false);
    assert.equal(typeof rejection.code, "string");
    assert.ok(Object.values(CODES).includes(rejection.code), `미등록 코드: ${rejection.code}`);
    assert.ok(Object.hasOwn(rejection, "action"));
    assert.equal(typeof JSON.stringify(rejection), "string");
  }
});

/* ────────────────────────── 음성 — 핸드셰이크 ────────────────────────── */

test("핸드셰이크가 없으면 아무것도 서지 않는다 — 만들었다 지우지도 않는다", () => {
  const win = createWin();
  const outcome = installSelftestApi({
    win, claimToken: () => null, createRunner: () => createFakeRunner(),
  });

  assert.deepEqual(outcome, {
    ok: false, code: CODES.UNAUTHORIZED, action: null,
    field: "token", state: STATES.UNCLAIMED,
  });
  assert.equal(Object.hasOwn(win, SELFTEST_GLOBAL), false);
  assert.equal(typeof win[SELFTEST_GLOBAL], "undefined");
  assert.deepEqual(Object.getOwnPropertyNames(win).filter((n) => n.startsWith("__")), []);
});

test("쿼리스트링만으로는 설치되지 않는다", () => {
  const win = createWin({
    location: {
      href: "https://app/?selftest=1&mode=full", search: "?selftest=1&mode=full", hash: "",
    },
  });
  const outcome = installSelftestApi({
    win, claimToken: () => null, createRunner: () => createFakeRunner(),
  });
  assert.equal(outcome.code, CODES.UNAUTHORIZED);
  assert.equal(Object.hasOwn(win, SELFTEST_GLOBAL), false);
});

test("해시만으로는 설치되지 않는다", () => {
  const win = createWin({
    location: { href: "https://app/#selftest", search: "", hash: "#selftest" },
  });
  const outcome = installSelftestApi({
    win, claimToken: () => null, createRunner: () => createFakeRunner(),
  });
  assert.equal(outcome.code, CODES.UNAUTHORIZED);
  assert.equal(Object.hasOwn(win, SELFTEST_GLOBAL), false);
});

test("토큰 자격 — 짧은 문자열·비문자열·던지는 클레임은 전부 거절이다", () => {
  const cases = [
    ["a".repeat(MIN_TOKEN_LENGTH - 1), "token"],
    ["", "token"],
    [42, "token"],
    [{ token: TOKEN }, "token"],
  ];
  for (const [value, field] of cases) {
    const win = createWin();
    const outcome = installSelftestApi({
      win, claimToken: () => value, createRunner: () => createFakeRunner(),
    });
    assert.equal(outcome.code, CODES.UNAUTHORIZED, `거절해야 한다: ${String(value)}`);
    assert.equal(outcome.field, field);
    assert.equal(Object.hasOwn(win, SELFTEST_GLOBAL), false);
  }

  const thrower = createWin();
  const outcome = installSelftestApi({
    win: thrower,
    claimToken: () => { throw new Error("호스트가 거절했다: /내부/경로/토큰"); },
    createRunner: () => createFakeRunner(),
  });
  assert.equal(outcome.code, CODES.UNAUTHORIZED);
  assert.equal(Object.hasOwn(thrower, SELFTEST_GLOBAL), false);
  assert.equal(JSON.stringify(outcome).includes("내부"), false, "호스트 문안을 되뿜지 않는다.");
});

test("비동기 클레임은 인증 실패가 아니라 배선 실패다", () => {
  const win = createWin();
  const outcome = installSelftestApi({
    win, claimToken: () => Promise.resolve(TOKEN), createRunner: () => createFakeRunner(),
  });
  assert.equal(outcome.code, CODES.INTERNAL);
  assert.equal(outcome.reason, "async");
  assert.equal(Object.hasOwn(win, SELFTEST_GLOBAL), false);
});

test("두 번째 설치는 already_claimed — 클레임은 일회용이다", () => {
  const { win } = band();
  const again = installSelftestApi({
    win, claimToken: () => TOKEN, createRunner: () => createFakeRunner(),
  });
  assert.deepEqual(again, {
    ok: false, code: CODES.ALREADY_CLAIMED, action: null, state: STATES.READY,
  });
});

test("그 이름이 이미 점유돼 있으면 덮어쓰지 않고 거절한다", () => {
  const win = createWin();
  win[SELFTEST_GLOBAL] = { version: 1, run: () => ({ ok: true }) };
  let claimed = 0;
  const outcome = installSelftestApi({
    win,
    claimToken: () => { claimed += 1; return TOKEN; },
    createRunner: () => createFakeRunner(),
  });
  assert.equal(outcome.code, CODES.ALREADY_CLAIMED);
  assert.equal(claimed, 0, "일회용 클레임은 태우지 않는다.");
});

test("주입이 어긋나면 클레임을 태우기 전에 멈춘다", () => {
  const bad = [
    [{ createRunner: () => createFakeRunner() }, "claimToken"],
    [{ claimToken: () => TOKEN }, "createRunner"],
    [{ claimToken: () => TOKEN, createRunner: () => null, now: 5 }, "now"],
    [{ claimToken: () => TOKEN, createRunner: () => null, deadlineMs: 0 }, "deadlineMs"],
    [{ claimToken: () => TOKEN, createRunner: () => null, deadlineMs: 1.5 }, "deadlineMs"],
  ];
  for (const [ports, field] of bad) {
    const win = createWin();
    let claimed = 0;
    const wrapped = ports.claimToken
      ? { ...ports, claimToken: () => { claimed += 1; return ports.claimToken(); } }
      : ports;
    const outcome = installSelftestApi({ win, ...wrapped });
    assert.equal(outcome.code, CODES.INTERNAL, `주입 누락을 잡아야 한다: ${field}`);
    assert.equal(outcome.field, field);
    assert.equal(claimed, 0);
    assert.equal(Object.hasOwn(win, SELFTEST_GLOBAL), false);
  }
  assert.equal(installSelftestApi(null).code, CODES.INTERNAL);
  assert.equal(installSelftestApi({ win: null }).field, "win");
});

test("CSPRNG 가 없으면 설치하지 않는다 — 약한 난수로 내려가지 않는다", () => {
  const win = {};
  const outcome = installSelftestApi({
    win, claimToken: () => TOKEN, createRunner: () => createFakeRunner(),
  });
  assert.equal(outcome.code, CODES.INTERNAL);
  assert.equal(outcome.field, "randomBytes");
  assert.equal(Object.hasOwn(win, SELFTEST_GLOBAL), false);
});

/* ────────────────────────── 음성 — 봉투 검증 ────────────────────────── */

test("버전이 액션보다 앞이다 — 미지 버전의 액션은 해석하지 않는다", () => {
  const { api } = band();
  for (const version of [undefined, null, 0, 2, "1", 1.5, true]) {
    const rejected = api.run({ version, action: "start", mode: "full" });
    assert.deepEqual(rejected, {
      ok: false, code: CODES.UNSUPPORTED_VERSION, action: null, supported: [1],
    }, `버전 ${String(version)} 은 거절이다.`);
  }
  /* 액션 이름이 계약 밖이어도 버전이 먼저다 — 코드가 unknown_action 이면 해석한 것이다. */
  assert.equal(api.run({ version: 9, action: "nope" }).code, CODES.UNSUPPORTED_VERSION);
});

test("요청 형태 — 객체가 아니거나 액션이 비면 malformed_request", () => {
  const { api } = band();
  for (const request of [null, undefined, 1, "start", [], true]) {
    const rejected = api.run(request);
    assert.equal(rejected.code, CODES.MALFORMED_REQUEST);
    assert.equal(rejected.field, "request");
  }
  for (const action of [undefined, null, "", 7, {}]) {
    const rejected = api.run({ version: 1, action });
    assert.equal(rejected.code, CODES.MALFORMED_REQUEST);
    assert.equal(rejected.field, "action");
  }
});

test("계약 밖 액션은 unknown_action 이고 아는 액션을 되짚어 준다", () => {
  const { api } = band();
  const rejected = api.run({ version: 1, action: "stop" });
  assert.deepEqual(rejected, {
    ok: false, code: CODES.UNKNOWN_ACTION, action: "stop", actions: ["start", "poll"],
  });
});

test("start 인자 — mode 는 비어 있을 수 없고 flags 는 평범한 객체다", () => {
  const { api, runner } = band();
  for (const mode of [undefined, "", 3, null]) {
    const rejected = api.run({ version: 1, action: "start", mode });
    assert.equal(rejected.code, CODES.MALFORMED_REQUEST);
    assert.equal(rejected.field, "mode");
  }
  const rejected = api.run(startRequest({ flags: ["packaged"] }));
  assert.equal(rejected.field, "flags");
  assert.equal(runner.calls.length, 0, "형태가 틀린 요청은 러너를 몰지 않는다.");
  /* 거절한 뒤에도 슬롯은 비어 있다 — 정상 start 가 여전히 통한다. */
  assert.equal(api.run(startRequest()).ok, true);
});

test("두 번째 start 는 조용히 재시작하지 않는다", async () => {
  const { api, runner, clock } = band();
  const runId = api.run(startRequest()).runId;
  await flush();

  const second = api.run(startRequest({ mode: "packaged" }));
  assert.deepEqual(second, {
    ok: false, code: CODES.ALREADY_RUNNING, action: "start", state: STATES.RUNNING,
  });
  assert.equal(runner.calls.length, 1, "러너가 두 번 돌지 않는다.");

  /* 종결 뒤의 재시작도 마찬가지다 — 일회용 슬롯은 소진된다. */
  clock.advance(10);
  runner.finish(emptyReport());
  await flush();
  const afterTerminal = api.run(startRequest());
  assert.equal(afterTerminal.code, CODES.ALREADY_CONSUMED);
  assert.equal(afterTerminal.state, STATES.SUCCEEDED);

  api.run({ version: 1, action: "poll", runId });
  const afterConsumed = api.run(startRequest());
  assert.equal(afterConsumed.code, CODES.ALREADY_CONSUMED);
  assert.equal(afterConsumed.state, STATES.CONSUMED);
});

test("poll 인자 — runId 부재·오타·미지 슬롯은 전부 시끄럽다", async () => {
  const { api } = band();
  for (const runId of [undefined, null, "", 5]) {
    const rejected = api.run({ version: 1, action: "poll", runId });
    assert.equal(rejected.code, CODES.MALFORMED_REQUEST);
    assert.equal(rejected.field, "runId");
  }
  const before = api.run({ version: 1, action: "poll", runId: "0".repeat(32) });
  assert.deepEqual(before, {
    ok: false, code: CODES.UNKNOWN_RUN, action: "poll", state: STATES.READY,
  });

  const runId = api.run(startRequest()).runId;
  await flush();
  const wrong = api.run({ version: 1, action: "poll", runId: "f".repeat(32) });
  assert.deepEqual(wrong, {
    ok: false, code: CODES.UNKNOWN_RUN, action: "poll", state: STATES.RUNNING,
  });
  assert.equal(JSON.stringify(wrong).includes(runId), false, "맞는 id 를 되짚어 주지 않는다.");
});

/* ────────────────────────── 음성 — 시한 ────────────────────────── */

test("시한 초과는 종결 실패다 — 부분 결과가 아니라", async () => {
  const { api, clock } = band();
  const runId = api.run(startRequest()).runId;
  await flush();
  clock.advance(DEFAULT_DEADLINE_MS);

  const polled = api.run({ version: 1, action: "poll", runId });

  assert.equal(polled.ok, false);
  assert.equal(polled.code, CODES.DEADLINE_EXCEEDED);
  assert.equal(polled.state, STATES.FAILED);
  assert.equal(polled.deadlineMs, DEFAULT_DEADLINE_MS);
  assert.equal(Object.hasOwn(polled, "evidence"), false, "만료에는 증거가 없다.");
  assert.deepEqual(polled.errors, []);

  const replay = api.run({ version: 1, action: "poll", runId });
  assert.equal(replay.code, CODES.ALREADY_CONSUMED);
});

test("시한 **뒤에** 도착한 완주는 완주가 아니다 — 레거시 결함 (가) 의 정면", async () => {
  const { api, runner, clock } = band();
  const runId = api.run(startRequest()).runId;
  await flush();
  clock.advance(DEFAULT_DEADLINE_MS + 1);
  runner.finish({
    ok: true, mode: "full", order: ["late"], results: { late: "stale" },
    errors: [], skipped: [], timings: {},
  });
  await flush();

  const polled = api.run({ version: 1, action: "poll", runId });
  assert.equal(polled.code, CODES.DEADLINE_EXCEEDED);
  assert.equal(JSON.stringify(polled).includes("stale"), false, "낡은 값은 나가지 않는다.");
});

test("만료로 확정된 뒤 러너가 던져도 판정은 바뀌지 않는다", async () => {
  const { api, runner, clock } = band();
  const runId = api.run(startRequest()).runId;
  await flush();
  clock.advance(DEFAULT_DEADLINE_MS);
  api.run({ version: 1, action: "poll", runId }); // 여기서 만료 확정 + 소진
  runner.explode(new Error("늦은 폭발"));
  await flush();
  const replay = api.run({ version: 1, action: "poll", runId });
  assert.equal(replay.code, CODES.ALREADY_CONSUMED);
});

test("시한은 주입한 값을 쓴다 — 경계 직전은 아직 도는 중이다", async () => {
  const { api, clock } = band({ deadlineMs: 500 });
  const runId = api.run(startRequest()).runId;
  await flush();
  clock.advance(499);
  assert.equal(api.run({ version: 1, action: "poll", runId }).state, STATES.RUNNING);
  clock.advance(1);
  assert.equal(api.run({ version: 1, action: "poll", runId }).code, CODES.DEADLINE_EXCEEDED);
});

/* ────────────────────────── 음성 — 러너 배선 ────────────────────────── */

test("러너 구성 실패는 start 를 깨뜨리지 않고 poll 에서 보인다", async () => {
  const { api } = band({
    createRunner: () => { throw new Error("주입 누락: host"); },
  });
  const ack = api.run(startRequest());
  assert.equal(ack.ok, true, "시작 자체가 던지면 파이썬은 runId 없이 아무것도 못 묻는다.");
  await flush();

  const polled = api.run({ version: 1, action: "poll", runId: ack.runId });
  assert.equal(polled.code, CODES.INTERNAL);
  assert.equal(polled.state, STATES.FAILED);
  assert.equal(polled.errors.length, 1);
  assert.match(polled.errors[0].message, /주입 누락/);
});

test("표면이 모자란 러너는 시끄럽게 거절된다", async () => {
  const { api } = band({ createRunner: () => ({ run: () => Promise.resolve({ ok: true }) }) });
  const ack = api.run(startRequest());
  await flush();
  const polled = api.run({ version: 1, action: "poll", runId: ack.runId });
  assert.equal(polled.code, CODES.INTERNAL);
  assert.match(polled.errors[0].message, /toEvidence/);
});

test("러너가 구조화 오류를 던지면 그 기록을 그대로 싣는다(클래스는 import 하지 않는다)", async () => {
  const runner = createFakeRunner();
  const { api } = band({ createRunner: () => runner });
  const ack = api.run(startRequest());
  await flush();
  const structured = new Error("[probe/run/deadline_exceeded] 시한 초과");
  structured.toRecord = () => ({
    probe: "probe_x", phase: "run", code: "deadline_exceeded", message: "시한 초과",
  });
  runner.explode(structured);
  await flush();

  const polled = api.run({ version: 1, action: "poll", runId: ack.runId });
  assert.equal(polled.code, CODES.INTERNAL);
  assert.deepEqual(polled.errors, [
    { probe: "probe_x", phase: "run", code: "deadline_exceeded", message: "시한 초과" },
  ]);
});

test("보고서가 보고서 모양이 아니면 성공으로 접지 않는다", async () => {
  const runner = createFakeRunner();
  const { api } = band({ createRunner: () => runner });
  const ack = api.run(startRequest());
  await flush();
  runner.finish("완주했음");
  await flush();
  const polled = api.run({ version: 1, action: "poll", runId: ack.runId });
  assert.equal(polled.code, CODES.INTERNAL);
  assert.equal(polled.field, "report");
});

/* ────────────────────────── 음성 — 토큰 ────────────────────────── */

/** 값 트리를 훑어 바늘 문자열을 찾는다. 봉투는 JSON 으로 실려 나가므로 JSON 훑기로 족하지만,
 *  창은 함수·비열거 프로퍼티까지 있으므로 손으로 걷는다. */
function findNeedle(value, needle, seen) {
  const visited = seen || new Set();
  if (typeof value === "string") return value.includes(needle);
  if (typeof value === "function") return String(value).includes(needle);
  if (value === null || typeof value !== "object") return false;
  if (visited.has(value)) return false;
  visited.add(value);
  for (const key of Object.getOwnPropertyNames(value)) {
    if (key.includes(needle)) return true;
    let inner;
    try {
      inner = value[key];
    } catch {
      continue;
    }
    if (findNeedle(inner, needle, visited)) return true;
  }
  return false;
}

test("토큰은 어떤 봉투에도, 창 어디에도 없다", async () => {
  const { api, win, runner, clock } = band();
  const envelopes = [];
  envelopes.push(api.run(startRequest({ input: "dark", flags: { packaged: true } })));
  const runId = envelopes[0].runId;
  await flush();
  envelopes.push(api.run({ version: 1, action: "poll", runId }));
  envelopes.push(api.run(startRequest()));
  envelopes.push(api.run({ version: 1, action: "poll", runId: "0".repeat(32) }));
  envelopes.push(api.run({ version: 2, action: "start" }));
  clock.advance(5);
  runner.finish({
    ok: true, mode: "full", order: ["a"], results: { a: "ok" },
    errors: [], skipped: [], timings: { a: 1 },
  });
  await flush();
  envelopes.push(api.run({ version: 1, action: "poll", runId }));
  envelopes.push(api.run({ version: 1, action: "poll", runId }));

  for (const envelope of envelopes) {
    const serialized = JSON.stringify(envelope);
    assert.equal(serialized.includes(TOKEN), false, `봉투에 토큰이 실렸다: ${serialized}`);
  }
  assert.equal(findNeedle(win, TOKEN, new Set()), false, "창에서 토큰이 발견됐다.");
  assert.equal(findNeedle(win[SELFTEST_GLOBAL], TOKEN, new Set()), false);
  assert.equal(SRC.includes(TOKEN), false);
});

test("증거에 토큰이 섞이면 그 실행 전체를 거절한다", async () => {
  const runner = createFakeRunner({
    toEvidence: (report) => ({ ...report.results, leaked: TOKEN }),
  });
  const { api } = band({ createRunner: () => runner });
  const ack = api.run(startRequest());
  await flush();
  runner.finish({
    ok: true, mode: "full", order: ["a"], results: { a: "ok" },
    errors: [], skipped: [], timings: {},
  });
  await flush();

  const polled = api.run({ version: 1, action: "poll", runId: ack.runId });
  assert.deepEqual(polled, {
    ok: false, code: CODES.INTERNAL, action: "poll",
    runId: ack.runId, state: STATES.CONSUMED, field: "token_leak",
  });
  assert.equal(JSON.stringify(polled).includes(TOKEN), false);
});

test("직렬화할 수 없는 증거도 같은 문에서 막힌다", async () => {
  const cyclic = { name: "순환" };
  cyclic.self = cyclic;
  const runner = createFakeRunner({ toEvidence: () => cyclic });
  const { api } = band({ createRunner: () => runner });
  const ack = api.run(startRequest());
  await flush();
  runner.finish(emptyReport());
  await flush();

  const polled = api.run({ version: 1, action: "poll", runId: ack.runId });
  assert.equal(polled.code, CODES.INTERNAL);
  assert.equal(polled.field, "serialization");
});

/* ────────────────────────── 음성 — 표면 불변 ────────────────────────── */

test("재대입도 재정의도 실패한다 — 생산자는 하나다", () => {
  const { win } = band();
  const original = win[SELFTEST_GLOBAL];

  assert.throws(() => { win[SELFTEST_GLOBAL] = { version: 1, run: () => ({}) }; }, TypeError);
  assert.throws(() => {
    Object.defineProperty(win, SELFTEST_GLOBAL, { value: 1, configurable: true });
  }, TypeError);
  assert.throws(() => { delete win[SELFTEST_GLOBAL]; }, TypeError);
  assert.throws(() => { original.run = () => ({ ok: true }); }, TypeError);
  assert.throws(() => { original.version = 2; }, TypeError);

  assert.equal(win[SELFTEST_GLOBAL], original);
  assert.equal(win[SELFTEST_GLOBAL].version, 1);
});

test("bare import 는 순수하다 — 전역·DOM·러너를 만들지 않는다", async () => {
  const before = Object.keys(globalThis).length;
  const again = await import(`../../frontend/src/selftest/api.js?pure=${Date.now()}`);
  assert.equal(typeof again.installSelftestApi, "function");
  assert.equal(Object.keys(globalThis).length, before);
  assert.equal(typeof globalThis.window, "undefined");
  assert.equal(typeof globalThis.document, "undefined");
  assert.equal(typeof globalThis.__hwpxTest, "undefined");
  assert.equal(typeof globalThis[SELFTEST_GLOBAL], "undefined");
});

/** 주석은 이관 근거와 **하면 안 되는 것들의 이름**(location·hash 등)을 일부러 보존하므로,
 *  산문을 코드로 세면 거짓 실패가 난다. 코드만 남겨 센다. */
function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");
}

test("음성 — 설치 조건에 페이지가 만들 수 있는 것이 하나도 없다", () => {
  const code = stripComments(SRC);
  for (const forbidden of [
    "location", "URLSearchParams", "searchParams", "document",
    "import.meta", "process.env", "localStorage", "sessionStorage",
    "navigator", "Math.random", "pywebview",
  ]) {
    assert.equal(code.includes(forbidden), false, `설치 경로가 ${forbidden} 를 읽습니다.`);
  }
  assert.equal(/\bhash\b/.test(code), false, "해시 판독이 코드에 있습니다.");
});

test("음성 — 전역 쓰기·IIFE·default export 부재", () => {
  /* 저장소 게이트가 frontend 전체를 **주석 포함** 정규식으로 훑으므로 날것으로 센다. */
  assert.equal(/(?:^|\s)window\.[A-Za-z_$][A-Za-z0-9_$]*\s*=/m.test(SRC), false);
  assert.equal(/(?:^|\s)globalThis\.[A-Za-z_$][A-Za-z0-9_$]*\s*=/m.test(SRC), false);
  assert.equal(/^\(function \(\) \{/m.test(SRC), false);
  assert.equal(SRC.includes("export default"), false);
  /* 러너·프로브를 import 하지 않는다 — 프로토콜은 엔진을 모른다(주입만 받는다). */
  const code = stripComments(SRC);
  assert.equal(/^\s*import\s/m.test(code), false, "이 모듈은 아무것도 import 하지 않습니다.");
});
