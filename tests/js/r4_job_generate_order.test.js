/* R4-03 — 발신·유입 **우선순위**의 컨트롤러 판.
 *
 * reducer 는 「이 응답이 내 것인가」를 재고(`r4_job_run_state`), 이 파일은 그 판정을
 * 컨트롤러가 **어느 채널에서 어떤 순서로** 먹이는지를 잰다. 셋이 서로 다른 채널이라
 * 순서 보장이 없다는 것이 이 슬라이스 설계의 출발점이다:
 *
 *   full  = push(성공에만 온다)   progress = push 델타   direct = 브리지 반환
 *
 * 그래서 이 층의 계약은 넷이다.
 *  ① 같은 객체 재통지는 이중 유입이 아니다(구독 재발화는 흔하다).
 *  ② 새 full 은 progress 기억을 함께 리셋한다 — 안 그러면 새 실행의 첫 델타가 「본 것」이 된다.
 *  ③ 진행 델타는 `lastFull` 을 절대 덮지 않는다.
 *  ④ port 는 정확히 한 번 attach 한다(dual-dispatch 창이 애초에 안 생긴다).
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createJobRunController } from "../../frontend/src/screens/job_run.ts";

function snap(overrides = {}) {
  return {
    has_job: true, job_name: "공고서", data_mount: "m1", out_dir: "C:\\out",
    selection_key: "s1", rules_key: "r1", last_run_job: "공고서",
    ...overrides,
  };
}

function harness(options = {}) {
  let full = options.full ?? null;
  let progress = null;
  const subscribers = new Set();
  const model = {
    getSnapshot: () => ({ full, progress }),
    subscribe(listener) {
      subscribers.add(listener);
      return () => subscribers.delete(listener);
    },
  };
  const generateQueue = [...(options.generate ?? [])];
  const tokens = [];
  // `generate` 를 **붙잡아 둔다**. startGenerate 는 flush 를 await 한 뒤에야 토큰을 내므로,
  // 호출 직후 동기적으로 읽으면 늘 빈 문자열이다 — 실행 **중**을 관측하려면 반환을 우리가
  // 쥐고 있어야 한다. (그 사실을 모르고 쓴 첫 판이 빈 토큰으로 초록을 낼 뻔했다.)
  /* 붙잡힌 발신은 **여럿일 수 있다**. 슬롯 하나로 두면 둘째 발신이 첫째를 고아로
     만들어, 「발신이 둘 났다」를 재는 음성 대조가 이름 있는 빨강 대신 **매달림**으로
     끝난다(실제로 그랬다 — 매달림은 정보가 0 이고 재주행 비용만 남긴다). */
  const pending = [];
  const client = {
    invoke(method, ...args) {
      if (method !== "generate") return Promise.resolve({ ok: true, value: null });
      tokens.push(args[2]);
      const next = generateQueue.shift() ?? { ok: true, status: "ok" };
      const value = { run_token: args[2], ...next };
      if (!options.defer) return Promise.resolve({ ok: true, value });
      return new Promise((resolve) => { pending.push(() => resolve({ ok: true, value })); });
    },
    dispatch: () => Promise.resolve({ ok: true, value: {} }),
  };
  const port = (impl) => {
    let bound = impl ?? null;
    return { bindReact(v) { if (bound !== null) throw new Error("두 번째 결속"); bound = v; }, current: () => bound };
  };
  const ports = {
    jobRun: port(), jobRunCoordination: port(),
    /* 커밋 관문. 기본은 즉시 통과지만 **붙잡을 수** 있어야 한다 — 진입 직렬화를 재는
       자리는 두 클릭이 같은 창 안에 서야 하고, 그 창은 이 관문이 연다. */
    jobData: port({ flushPendingEdits: options.flush ?? (() => Promise.resolve()) }),
    jobRelinkFlow: port({ relinkTemplateFor: () => Promise.resolve() }),
    editorEntry: port({ openGuarded: () => true }),
  };
  const controller = createJobRunController({
    runtime: { model: () => model, loadInitial: () => Promise.resolve({}) },
    client, ports,
    services: { relink: port({ relinkTemplate: () => Promise.resolve(true) }) },
    modal: { confirm: () => Promise.resolve(true), open() {}, close() {} },
    navigation: { go() {} },
    doc: { getElementById: () => null, querySelector: () => null },
    selectionLine: (n) => `${n}행 선택`,
    notify() {},
  });
  const notify = () => { for (const listener of [...subscribers]) listener(); };
  return {
    controller, ports, tokens: () => tokens.slice(),
    runPort: () => ports.jobRun.current(),
    pushFull(value) { full = value; notify(); },
    pushProgress(value) { progress = value; notify(); },
    /** 값을 안 바꾸고 구독만 재발화 — 「같은 것을 또 봤다」의 실물. */
    renotify: notify,
    token: () => controller.getRun().active?.runToken ?? "",
    /** 붙잡아 둔 generate 반환을 놓아 준다. */
    settleGenerate() {
      assert.ok(pending.length, "붙잡힌 generate 가 없다 — 대역이 실행 중을 만들지 못했다");
      for (const release of pending.splice(0)) release();
    },
  };
}

/** 마이크로태스크를 비운다 — `startGenerate` 의 flush await 뒤 상태를 읽기 위한 최소 대기. */
const tick = () => new Promise((resolve) => setImmediate(resolve));

/** 실행 **중**인 컨트롤러 — 토큰이 서 있고 반환은 아직 붙잡혀 있다. */
async function running(options = {}) {
  const h = harness({ full: snap(), defer: true, ...options });
  await h.controller.init();
  const done = h.controller.startGenerate();
  await tick();
  assert.ok(h.token(), "실행 토큰이 서지 않았다 — 이후 단언이 공허하다");
  return { ...h, done };
}

/* ================= ① 같은 객체 재통지 ================= */

test("같은 full 객체의 재통지는 이중 유입이 아니다", async () => {
  const first = snap();
  const h = harness({ full: first });
  await h.controller.init();
  assert.equal(h.controller.getRun().lastFull, first);

  h.renotify();
  h.renotify();
  assert.equal(h.controller.getRun().lastFull, first, "같은 것을 다시 들이지 않는다");
  assert.deepEqual(h.controller.getRun().discarded, [], "재통지가 폐기 진단을 만들지도 않는다");
});

test("같은 progress 객체의 재통지도 한 번만 반영된다", async () => {
  const h = await running();
  const delta = { done: 1, total: 4, run_token: h.token() };
  h.pushProgress(delta);
  assert.deepEqual(h.controller.getRun().progress, delta);

  h.settleGenerate();
  await h.done;
  assert.equal(h.controller.getRun().progress, null, "완주가 진행을 비운다");

  // 완주 뒤 **같은 객체**로 재통지한다. 다시 들였다면 terminal barrier 가 그것을 버리며
  // 진단 하나를 남길 것이다 — 진단이 0 이라는 것이 곧 「두 번 안 들였다」의 증거다.
  h.renotify();
  assert.deepEqual(h.controller.getRun().discarded, [], "본 델타를 다시 들이지 않는다");
});

/* ================= ② full 은 progress 기억을 리셋한다 ================= */

test("새 full 은 progress 기억을 함께 리셋한다 — 다음 실행의 첫 델타가 「본 것」이 되지 않는다", async () => {
  const h = await running();
  const t1 = h.token();
  const delta = { done: 1, total: 2, run_token: t1 };
  h.pushProgress(delta);
  h.settleGenerate();
  await h.done;

  assert.deepEqual(h.controller.getRun().discarded, [],
    "완주까지는 아무것도 버려지지 않았다 — 다음 단언의 출발점이 0 이어야 한다");

  // 새 세션 사실이 온다. 기억이 리셋되면 **아직 model 에 걸려 있는 그 델타**가 같은 pump
  // 안에서 다시 검사되고, 옛 토큰이라 진단 하나를 남긴다. 리셋이 없으면 조용하다 —
  // 두 사건의 관측 결과가 다르므로 이 단언이 실제로 그 한 줄을 겨눈다.
  h.pushFull(snap({ selection_key: "s2" }));
  const discarded = h.controller.getRun().discarded;
  assert.equal(discarded.length, 1, "새 full 은 progress 기억을 함께 리셋한다");
  assert.equal(discarded.at(-1).token, t1, "다시 검사된 것이 바로 그 옛 델타다");

  // 그리고 리셋 뒤 재검사는 **한 번뿐**이다 — 같은 객체가 계속 걸려 있어도 누적되지 않는다.
  h.renotify();
  assert.equal(h.controller.getRun().discarded.length, 1);
});

/* ================= ③ 채널 분리 ================= */

test("진행 델타는 lastFull 을 덮지 않는다", async () => {
  const base = snap();
  const h = await running({ full: base });
  h.pushProgress({ done: 2, total: 5, run_token: h.token() });
  assert.equal(h.controller.getRun().lastFull, base, "세션 사실은 full 채널만 바꾼다");
  h.settleGenerate();
  await h.done;
});

test("옛 토큰의 델타는 버려지되 사유와 함께 진단으로 남는다", async () => {
  const h = await running();
  h.pushProgress({ done: 9, total: 9, run_token: "옛-토큰" });
  h.settleGenerate();
  await h.done;

  const discarded = h.controller.getRun().discarded;
  assert.equal(discarded.length, 1, "조용히 버리면 「아무 일도 안 일어남」과 구분되지 않는다");
  assert.equal(discarded[0].kind, "progress");
  assert.equal(discarded[0].token, "옛-토큰");
  assert.ok(discarded[0].reason.length > 0, "사유 없는 폐기는 진단이 아니다");
});

test("terminal barrier — 완료 뒤 같은 토큰의 늦은 델타는 자기 이름을 대며 버려진다", async () => {
  const h = harness({ full: snap() });
  await h.controller.init();
  await h.controller.startGenerate();
  const token = h.controller.getRun().finishedToken;
  assert.ok(token, "완료 토큰이 남아야 barrier 가 자기 이름을 댈 수 있다");

  h.pushProgress({ done: 1, total: 9, run_token: token });
  const run = h.controller.getRun();
  assert.ok(run.result, "완료를 진행 중으로 되돌리지 않는다");
  assert.equal(run.progress, null);
  const last = run.discarded.at(-1);
  assert.equal(last.reason, "이미 종료된 실행입니다",
    "양성 경합(정상)과 미배선(결함)이 같은 문장을 내면 진단이 죽는다");
});

/* ================= ④ port 결속 ================= */

test("JobRunPort 는 정확히 한 번 attach 한다", async () => {
  const h = harness({ full: snap() });
  await h.controller.init();
  const release = h.runPort().attach({ onFull() {}, onProgress() {} });
  assert.throws(() => h.runPort().attach({ onFull() {}, onProgress() {} }), /한 번 attach/);
  release();
  h.runPort().attach({ onFull() {}, onProgress() {} });
});

test("port 는 bindReact 로 한 번만 결속된다 — dual-dispatch 창이 안 생긴다", () => {
  const h = harness({ full: snap() });
  assert.throws(() => h.ports.jobRun.bindReact({}), /두 번째 결속/);
  assert.throws(() => h.ports.jobRunCoordination.bindReact({}), /두 번째 결속/);
});

test("attach 한 콜백은 유입 순서대로 full·progress 를 받는다", async () => {
  const h = harness({ full: snap(), defer: true });
  await h.controller.init();
  const seen = [];
  h.runPort().attach({
    onFull: () => seen.push("full"),
    onProgress: () => seen.push("progress"),
  });
  const done = h.controller.startGenerate();
  await tick();
  const token = h.token();
  h.pushFull(snap({ selection_key: "s2" }));
  h.pushProgress({ done: 1, total: 2, run_token: token });
  h.settleGenerate();
  await done;
  assert.deepEqual(seen, ["full", "progress"], "한 pump 안에서도 full 이 먼저다");
});

/* ================= 세대 ================= */

test("dispose 는 세대를 올려 앞선 실행의 응답을 한 번에 남으로 만든다", async () => {
  const h = await running();
  const token = h.token();
  h.controller.dispose();
  h.settleGenerate();
  await h.done;

  h.pushProgress({ done: 1, total: 2, run_token: token });
  assert.equal(h.controller.getRun().progress, null, "폐기한 화면의 응답은 남이다");
  assert.equal(h.controller.getRun().screenEpoch, 1);
});

/* ================= ⑦ 진입 직렬화 — 커밋 관문 창의 둘째 클릭 ================= */

test("커밋 관문이 도는 동안 들어온 둘째 실행은 첫 런의 정체를 못 덮는다", async () => {
  /* legacy 는 `flushPendingEdits` **뒤에** `generating` 을 세웠고 그 창에 둘째 클릭이
     들어올 수 있었다. 토큰이 없던 때는 백엔드 자물쇠가 둘째를 거절하고 첫 런의 결과가
     그대로 그려져 무해했다 — **귀속이 생기면서 대가가 바뀐다**: 둘째의 `beginRun` 이
     첫 런의 `active` 를 덮어써, 실제로 만들어진 문서의 결과가 남의 것으로 폐기되고
     화면엔 「이미 생성 중」만 남는다. */
  /* 붙잡는 자리는 **여럿**이다. 슬롯 하나로 두면 둘째 호출이 첫째의 resolve 를 덮어써
     첫 실행이 고아가 되고, 이 대조는 이름 있는 빨강 대신 매달림으로 끝난다(하니스에서
     같은 실수를 하고 여기서 한 번 더 했다 — 「붙잡는 대역은 큐다」가 규칙이다). */
  const releases = [];
  const h = harness({
    full: snap(), defer: true,
    // 커밋 관문을 붙잡아 두 클릭이 같은 창 안에 서게 한다(실물에서 이 관문은 대기 중인
    // 존 변이가 있을 때 호스트 왕복이라 실제로 열린다).
    flush: () => new Promise((resolve) => { releases.push(resolve); }),
  });
  await h.controller.init();

  const first = h.controller.startGenerate();
  const second = h.controller.startGenerate();   // 창 안의 둘째 클릭
  // 둘째가 커밋 관문에 **닿지도 않는다**는 것이 잠금의 직접 관측이다 — 잠금이 없으면 2 다.
  assert.equal(releases.length, 1,
    "둘째 클릭이 커밋 관문까지 갔습니다 — 진입이 직렬화되지 않았습니다");
  for (const release of releases.splice(0)) release();
  await tick();

  assert.equal(h.tokens().length, 1, `실행 발신이 둘 났습니다: ${JSON.stringify(h.tokens())}`);
  assert.equal(h.controller.getRun().active.runToken, h.token(),
    "둘째가 첫 런의 정체를 덮었습니다 — 첫 런의 결과가 남의 것으로 폐기됩니다");
  h.settleGenerate();
  await Promise.all([first, second]);
});

test("실행이 끝나면 다시 시작할 수 있다 — 잠금은 창이지 영구 봉인이 아니다", async () => {
  const h = await running();
  h.settleGenerate();
  await h.done;

  // 대역이 `defer` 라 둘째 실행도 붙잡힌다 — 여기서 그냥 await 하면 테스트가 매달린다
  // (첫 판이 실제로 그랬다). 발신이 났는지를 보고 놓아 준다.
  const again = h.controller.startGenerate();
  await tick();
  assert.equal(h.tokens().length, 2, "끝난 뒤에도 못 누르면 잠금이 상태를 놓친 것이다");
  h.settleGenerate();
  await again;
});
