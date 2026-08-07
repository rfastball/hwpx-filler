/* R4-03 — 결과 3태 구획의 **수명**을 컨트롤러 층에서 잰다.
 *
 * `r4_job_run_state` 는 같은 규칙을 순수 reducer 로 잰다. 여기서 한 번 더 재는 것은
 * 중복이 아니다: reducer 가 옳아도 컨트롤러가 **그것을 안 부르거나 순서를 틀리면** 사용자는
 * 틀린 것을 본다. 실제로 이 슬라이스에서 그 자리가 하나 있었다 — 퇴장 한 줄은 리셋이
 * 실행 기록을 비운 **뒤에** 적어야 살아남는다(순서를 바꾸면 곧바로 지워진다).
 *
 *  ① 초기화(작업 전환·데이터 교체) — 결과가 사라지고 퇴장 한 줄이 **남는다**.
 *  ② 강등(선택·규칙·저장 폴더) — 결과는 살고 stale 만 선다.
 *  ③ 유지(탭 복귀·개명) — 아무 일도 안 일어난다.
 *  ④ 명시 파기 — 흔적을 남기지 않는다(치우라는 행동을 반만 들으면 안 된다).
 *  ⑤ 실행 중 full push 는 자기 결과를 강등시키지 않는다.
 *  ⑥ 렌더 입구(`renderResult`)는 귀속 판정을 지나지 않는다 — 그것이 그 입구의 요지다.
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
  const events = [];
  let snapshot = options.snapshot ?? null;
  const subscribers = new Set();
  const model = {
    getSnapshot: () => ({ full: snapshot, progress: null }),
    subscribe(listener) {
      subscribers.add(listener);
      return () => subscribers.delete(listener);
    },
  };
  const generateQueue = [...(options.generate ?? [])];
  const client = {
    invoke(method, ...args) {
      if (method !== "generate") return Promise.resolve({ ok: true, value: null });
      const next = generateQueue.shift() ?? { ok: true, status: "ok" };
      return Promise.resolve({ ok: true, value: { run_token: args[2], ...next } });
    },
    dispatch: (screen, action, payload) => {
      events.push({ action, payload });
      return Promise.resolve({ ok: true, value: {} });
    },
  };
  const port = (impl) => {
    let bound = impl ?? null;
    return { bindReact(v) { if (bound !== null) throw new Error("두 번째 결속"); bound = v; }, current: () => bound };
  };
  const controller = createJobRunController({
    runtime: { model: () => model, loadInitial: () => Promise.resolve({}) },
    client,
    ports: {
      jobRun: port(), jobRunCoordination: port(),
      jobData: port({ flushPendingEdits: () => Promise.resolve() }),
      jobRelinkFlow: port({ relinkTemplateFor: () => Promise.resolve() }),
      editorEntry: port({ openGuarded: () => true }),
    },
    services: { relink: port({ relinkTemplate: () => Promise.resolve(true) }) },
    modal: { confirm: () => Promise.resolve(true), open() {}, close() {} },
    navigation: { go() {} },
    doc: { getElementById: () => null, querySelector: () => null },
    selectionLine: (n) => `${n}행 선택`,
    notify() {},
  });
  return {
    controller,
    push(value) {
      snapshot = value;
      for (const listener of [...subscribers]) listener();
    },
    log: () => controller.getUi().log,
    /** 타임스탬프 접두를 걷은 실행 기록 — 문안만 본다. */
    lines: () => controller.getUi().log.map((line) => line.replace(/^\[[^\]]+\]\s*/, "")),
  };
}

/** 한 번 완주해 결과가 선 컨트롤러. */
async function withResult(options = {}) {
  const h = harness({ snapshot: snap(), generate: [{ ok: true, status: "ok", title: "완료" }], ...options });
  await h.controller.init();
  await h.controller.startGenerate();
  assert.ok(h.controller.getRun().result, "출발 상태가 성립하지 않으면 이후 단언이 공허하다");
  return h;
}

/* ================= ① 초기화 ================= */

test("작업 전환은 결과를 초기화한다", async () => {
  const h = await withResult();
  h.push(snap({ job_name: "다른 공고", last_run_job: "공고서" }));
  const run = h.controller.getRun();
  assert.equal(run.result, null);
  assert.equal(run.resultFingerprint, null);
});

test("데이터 교체는 이름이 같아도 결과를 초기화한다", async () => {
  const h = await withResult();
  h.push(snap({ data_mount: "m2" }));
  assert.equal(h.controller.getRun().result, null);
});

test("초기화 갈래는 기록을 비운 뒤 퇴장 한 줄만 남긴다", async () => {
  const h = await withResult();
  // 죽은 세션의 줄을 실제로 세워 둔다 — 없으면 「비웠는가」가 공허하다.
  await h.controller.cancelGeneration();
  h.controller.toggleLog();
  assert.ok(h.lines().length >= 1, "치울 줄이 없으면 이 단언은 아무것도 재지 않는다");

  h.push(snap({ job_name: "다른 공고", last_run_job: "공고서" }));
  const lines = h.lines();
  /* 「줄이 있는가」가 아니라 「**그 줄만** 있는가」를 잰다 — 비우지 않으면 죽은 세션의
     줄이 밑에 쌓여 다음 실행과 한 세션으로 읽히는데, 마지막 줄만 보는 단언은 그걸 통과시킨다
     (legacy `resetGenResult` 는 두 호출자 모두에서 기록을 비웠다). */
  assert.equal(lines.length, 1, `리셋이 기록을 안 비웠습니다: ${JSON.stringify(lines)}`);
  assert.ok(lines[0].includes("공고서"), "어느 작업의 결과가 나갔는지 이름을 댄다");
  assert.equal(h.controller.getUi().logOpen, false, "죽은 세션의 펼침은 승계되지 않는다");
});

test("퇴장 한 줄은 초기화 갈래에서만 난다 — 강등에는 없다", async () => {
  const h = await withResult();
  const before = h.log().length;
  h.push(snap({ selection_key: "s2" }));
  assert.equal(h.log().length, before, "강등은 퇴장이 아니다");
});

/* ================= ② 강등 ================= */

test("선택 변경은 결과를 남기고 강등만 한다", async () => {
  const h = await withResult();
  h.push(snap({ selection_key: "s2" }));
  const result = h.controller.getRun().result;
  assert.ok(result, "강등은 삭제가 아니다");
  assert.equal(result.stale, true);
  assert.equal(result.title, "완료", "Python 이 낸 판정 필드는 그대로 산다");
});

test("규칙·저장 폴더 변경도 같은 강등 갈래다", async () => {
  for (const patch of [{ rules_key: "r2" }, { out_dir: "D:\\other" }]) {
    const h = await withResult();
    h.push(snap(patch));
    assert.equal(h.controller.getRun().result.stale, true, JSON.stringify(patch));
  }
});

test("markResultStale 은 결과가 없으면 아무것도 만들지 않는다", async () => {
  const h = harness({ snapshot: snap() });
  await h.controller.init();
  h.controller.markResultStale();
  assert.equal(h.controller.getRun().result, null, "없는 결과를 강등으로 되살리지 않는다");
});

/* ================= ③ 유지 ================= */

test("작업·데이터 불변 재푸시(탭 복귀)는 결과를 그대로 둔다", async () => {
  const h = await withResult();
  h.push(snap());
  const result = h.controller.getRun().result;
  assert.equal(result.title, "완료");
  assert.notEqual(result.stale, true, "같은 세션 재푸시는 강등이 아니다");
});

test("개명은 전환이 아니다 — 주체가 이름을 따라가면 결과가 산다", async () => {
  const h = await withResult();
  // 이름만 바뀌고 주체(`last_run_job`)가 그 새 이름을 가리킨다 = 같은 작업이다.
  h.push(snap({ job_name: "공고서(개정)", last_run_job: "공고서(개정)" }));
  assert.ok(h.controller.getRun().result, "이름만 바꿔도 결과가 사라지면 안 된다");
});

/* ================= ④ 명시 파기 ================= */

test("명시 파기는 결과와 그 실행의 기록을 함께 치운다", async () => {
  const h = await withResult();
  h.controller.toggleLog();                       // 이 세션의 펼침 의사표시
  assert.ok(h.log().length > 0, "치울 기록이 없으면 이 단언은 공허하다");
  assert.equal(h.controller.getUi().logOpen, true);

  h.controller.closeResult();
  const run = h.controller.getRun();
  assert.equal(run.result, null);
  assert.equal(run.progress, null);
  /* 「줄이 늘지 않았는가」가 아니라 「치워졌는가」를 잰다 — 종전 이 자리는 전자였고,
     그래서 로그가 통째로 남는 결함(legacy `resetGenResult` 동등성 누락)을 통과시켰다.
     남으면 다음 실행의 첫 줄이 남의 끝줄 밑에 붙어 한 세션으로 읽힌다. */
  assert.deepEqual(h.log(), [], "치우라는 행동을 반만 들으면 안 된다");
  assert.equal(h.controller.getUi().logOpen, false, "세션이 죽으면 기록도 다시 접힌다");
});

/* ================= ⑤ 실행 중 ================= */

test("실행이 스스로 만든 세션 변화가 자기 결과를 강등시키지 않는다", async () => {
  const h = harness({
    snapshot: snap(),
    // 완주 응답이 오기 전에 full push 가 먼저 도착하는 실제 순서를 만든다.
    generate: [{ ok: true, status: "ok", title: "완료" }],
  });
  await h.controller.init();
  const first = await withResult();
  // 앞선 결과가 선 상태에서 실행을 다시 시작하고, 그 사이 런이 낸 full 이 도착한다.
  const started = first.controller.startGenerate();
  first.push(snap({ last_run_job: "공고서" }));
  await started;
  const result = first.controller.getRun().result;
  assert.notEqual(result.stale, true, "자기 런이 만든 스탬프로 자기 결과를 강등시키지 않는다");
});

/* ================= ⑥ 렌더 입구 ================= */

test("renderResult 는 귀속 판정을 지나지 않는다 — 토큰 없는 dict 가 그대로 선다", async () => {
  const h = harness({ snapshot: snap() });
  await h.controller.init();
  h.controller.renderResult({ status: "partial", title: "일부 완료", summary: "3/5" });
  const run = h.controller.getRun();
  assert.equal(run.result.title, "일부 완료", "이 입구는 실행이 아니라 렌더를 겨눈다");
  assert.equal(run.running, false);
  assert.deepEqual(run.discarded, [], "프로브 입구는 폐기 진단을 남기지 않는다");
});

test("renderResult 로 선 결과도 세션 지문을 갖는다 — 이후 강등 판정이 성립한다", async () => {
  const h = harness({ snapshot: snap() });
  await h.controller.init();
  h.controller.renderResult({ status: "ok", title: "완료" });
  assert.ok(h.controller.getRun().resultFingerprint, "지문이 없으면 이후 강등이 조용히 안 일어난다");
  h.push(snap({ selection_key: "s9" }));
  assert.equal(h.controller.getRun().result.stale, true);
});
