/* R4-03 — 실행 표면 컨트롤러(`frontend/src/screens/job_run.ts`)의 **배선**.
 *
 * 형제 둘과 겨눔이 갈린다. `r4_job_run_state` 는 reducer 의 귀속 판정을 순수하게 재고,
 * `n06_job` 은 수명주기(구독 delta·거절 전파·late-binding)를 잰다. 이 파일은 그 사이 —
 * **컨트롤러가 결정을 어떤 순서로, 누구에게 시키는가** — 를 든다.
 *
 *  ① 상관 토큰 계약 위반은 시끄럽다 — 토큰 없는 응답에 결과를 그리지 않는다.
 *  ② 덮어쓰기 왕복은 **같은 토큰**으로 이어지고, 취소는 직전 결과를 지우지 않는다.
 *  ③ 실행 전 거절은 결과 자리를 비워 두지 않는다(누른 뒤 아무 일도 없는 것으로 안 읽힌다).
 *  ④ 커밋은 대기 중인 존 변이 **뒤에** 선다(8R P1 발신 순서 규약).
 *  ⑤ 작업대 갈래는 생성이 아니다 — 토큰을 내지 않고 항행으로 끝난다.
 *  ⑥ 예외는 삼켜지지 않는다 — op 를 끝내고 사유를 실행 기록에 남긴다.
 *  ⑦ 파괴 전이 가드는 **실시간 질의**다(스냅샷 캐시가 아니다).
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createJobRunController } from "../../frontend/src/screens/job_run.ts";

/** 최소 세션 스냅샷 — 값의 출처는 전부 Python 이다. */
function snap(overrides = {}) {
  return {
    has_job: true, job_name: "공고서", data_mount: "m1", out_dir: "C:\\out",
    selection_key: "s1", rules_key: "r1", last_run_job: "공고서",
    preview: { pos: 0, rows: [] },
    ...overrides,
  };
}

/* ------------------------------------------------------------------ 대역 -- */

function harness(options = {}) {
  const events = [];
  let snapshot = options.snapshot ?? null;
  const subscribers = new Set();

  const model = {
    getSnapshot: () => ({ full: snapshot, progress: options.progress ?? null }),
    subscribe(listener) {
      subscribers.add(listener);
      return () => subscribers.delete(listener);
    },
  };
  // `generate` 응답을 큐로 준다 — 덮어쓰기 왕복이 **호출 둘**임을 대역이 흉내내야
  // 「같은 토큰으로 재호출」을 실제로 관측할 수 있다.
  const generateQueue = [...(options.generate ?? [])];
  const client = {
    invoke(method, ...args) {
      events.push({ kind: "invoke", method, args });
      if (method === "generate") {
        const next = generateQueue.shift();
        if (next === undefined) return Promise.resolve({ ok: true, value: {} });
        if (next instanceof Error) return Promise.reject(next);
        // 토큰 반향은 Python 계약이다 — 대역도 **받은 토큰을 되돌린다**.
        const echo = next.echoToken === false ? {} : { run_token: args[2] };
        return Promise.resolve({ ok: true, value: { ...echo, ...next } });
      }
      if (method === "pick_output_folder") {
        return Promise.resolve({ ok: true, value: options.pickedFolder ?? null });
      }
      return Promise.resolve({ ok: true, value: null });
    },
    dispatch(screen, action, payload) {
      events.push({ kind: "dispatch", screen, action, payload });
      const canned = (options.dispatch ?? {})[action];
      if (canned instanceof Error) return Promise.reject(canned);
      return Promise.resolve({ ok: true, value: canned ?? {} });
    },
  };
  const port = (impl) => {
    let bound = impl ?? null;
    return {
      bindReact(value) {
        if (bound !== null) throw new Error("두 번째 결속");
        bound = value;
      },
      current: () => bound,
    };
  };
  const ports = {
    jobRun: port(), jobRunCoordination: port(),
    jobData: port({
      flushPendingEdits() {
        events.push({ kind: "flush" });
        return Promise.resolve();
      },
    }),
    jobRelinkFlow: port({
      relinkTemplateFor(name) {
        events.push({ kind: "relink", name });
        return Promise.resolve();
      },
    }),
    editorEntry: port({
      openGuarded(name, context) {
        events.push({ kind: "openGuarded", name, context });
        return options.openGuardedResult ?? true;
      },
    }),
  };
  const confirms = [];
  const controller = createJobRunController({
    runtime: { model: () => model, loadInitial: () => Promise.resolve({}) },
    client, ports,
    services: { relink: port({ relinkTemplate: () => Promise.resolve(true) }) },
    modal: {
      confirm(spec) {
        confirms.push(spec);
        events.push({ kind: "confirm", title: spec.title });
        return Promise.resolve(options.confirmAnswer ?? true);
      },
      open(id) { events.push({ kind: "modal.open", id }); },
      close(id) { events.push({ kind: "modal.close", id }); },
    },
    navigation: { go: (target) => events.push({ kind: "go", target }) },
    doc: {
      getElementById: (id) => (options.elements ?? {})[id] ?? null,
      querySelector: () => null,
    },
    selectionLine: (n) => `${n}행 선택`,
    notify: (message) => events.push({ kind: "notify", message }),
  });

  return {
    controller, events, confirms,
    push(value) {
      snapshot = value;
      for (const listener of [...subscribers]) listener();
    },
    log: () => controller.getUi().log,
    generateCalls: () => events.filter((e) => e.method === "generate"),
    only: (kind) => events.filter((e) => e.kind === kind),
  };
}

/** init 까지 마친 컨트롤러 — 첫 full 이 들어온 상태가 대부분 전이의 출발점이다. */
async function seeded(options = {}) {
  const h = harness({ snapshot: snap(options.snapshotOverrides), ...options });
  await h.controller.init();
  return h;
}

/* ================= ① 상관 토큰 계약 ================= */

test("토큰 반향이 없는 generate 응답은 결과를 그리지 않고 시끄럽게 선다", async () => {
  const h = await seeded({ generate: [{ echoToken: false, ok: true, status: "ok" }] });
  await h.controller.startGenerate();

  assert.equal(h.controller.getRun().result, null, "토큰 없는 응답으로 결과를 그리지 않는다");
  assert.equal(h.controller.getRun().running, false, "op 는 끝난다 — 영영 진행 중으로 두지 않는다");
  const notified = h.only("notify");
  assert.equal(notified.length, 1, "조용히 넘기지 않는다");
  assert.match(notified[0].message, /상관 토큰/);
  assert.ok(h.log().some((line) => /상관 토큰/.test(line)), "실행 기록에도 남는다");
});

test("빈 문자열 토큰도 계약 위반이다 — 있음/없음이 아니라 쓸모로 가른다", async () => {
  const h = await seeded({ generate: [{ echoToken: false, run_token: "", ok: true }] });
  await h.controller.startGenerate();
  assert.equal(h.controller.getRun().result, null);
  assert.equal(h.only("notify").length, 1);
});

/* ================= ② 덮어쓰기 왕복 ================= */

test("덮어쓰기 확인은 같은 토큰으로 재호출한다 — 두 실행으로 세지 않는다", async () => {
  const h = await seeded({
    confirmAnswer: true,
    generate: [{ needs_overwrite: true, existing: 3 }, { ok: true, status: "ok", title: "완료" }],
  });
  await h.controller.startGenerate();

  const calls = h.generateCalls();
  assert.equal(calls.length, 2, "확인 뒤 재호출까지 두 번");
  assert.equal(calls[0].args[2], calls[1].args[2], "재호출은 **같은 토큰**이다");
  assert.equal(calls[0].args[1], false, "첫 호출은 확인 전");
  assert.equal(calls[1].args[1], true, "재호출만 confirmOverwrite=true");
  assert.equal(h.controller.getRun().result.title, "완료");
});

test("덮어쓰기 확인은 danger 이고 수치를 재진술한다 — 조용한 덮어쓰기가 없다", async () => {
  const h = await seeded({
    confirmAnswer: true,
    generate: [{ needs_overwrite: true, existing: 3 }, { ok: true, status: "ok" }],
  });
  await h.controller.startGenerate();
  const [spec] = h.confirms;
  assert.equal(spec.danger, true, "파괴 전이는 danger 로 선다");
  assert.equal(spec.cancelLabel, "취소");
  assert.ok(spec.body.length > 0, "본문이 비어 있으면 재진술이 아니다");
});

test("덮어쓰기 취소는 op 만 끝내고 직전 결과를 지우지 않는다", async () => {
  const h = await seeded({
    confirmAnswer: false,
    generate: [{ ok: true, status: "ok", title: "1차" }, { needs_overwrite: true, existing: 1 }],
  });
  await h.controller.startGenerate();
  assert.equal(h.controller.getRun().result.title, "1차");

  await h.controller.startGenerate();
  const run = h.controller.getRun();
  assert.equal(run.running, false, "op 는 끝난다");
  assert.equal(run.result.title, "1차", "사용자가 치우라고 한 적 없는 결과를 지우지 않는다");
  assert.equal(h.generateCalls().length, 2, "취소는 재호출하지 않는다");
  assert.ok(h.log().some((line) => /취소/.test(line)));
});

/* ================= ③ 실행 전 거절 ================= */

test("실행 전 거절은 결과 자리를 비워 두지 않는다", async () => {
  const h = await seeded({
    generate: [{ ok: false, error: "저장 폴더가 없습니다", level: "danger" }],
  });
  await h.controller.startGenerate();

  const result = h.controller.getRun().result;
  assert.ok(result, "누른 뒤 아무 일도 없는 것으로 읽히면 안 된다");
  assert.equal(result.rejected, true);
  assert.equal(result.level, "danger");
  assert.equal(result.summary, "저장 폴더가 없습니다");
  assert.ok(h.log().some((line) => line.includes("저장 폴더가 없습니다")));
});

test("거절의 level 은 danger 아니면 warn 으로 좁혀진다 — 임의 값이 태로 새지 않는다", async () => {
  const h = await seeded({ generate: [{ ok: false, error: "x", level: "우주" }] });
  await h.controller.startGenerate();
  assert.equal(h.controller.getRun().result.level, "warn");
});

/* ================= ④ 발신 순서 ================= */

test("커밋은 대기 중인 존 변이 뒤에 선다 — flush 가 generate 보다 먼저다", async () => {
  const h = await seeded({ generate: [{ ok: true, status: "ok" }] });
  h.events.length = 0;
  await h.controller.startGenerate();

  const order = h.events
    .filter((e) => e.kind === "flush" || e.method === "generate")
    .map((e) => (e.kind === "flush" ? "flush" : "generate"));
  assert.equal(order[0], "flush", "첫 사건이 flush 가 아니면 커밋이 옛 값을 싣는다");
  assert.ok(order.includes("generate"));
});

/* ================= ⑤ 작업대 갈래 ================= */

test("작업대 갈래는 토큰을 내지 않고 항행으로 끝난다", async () => {
  const h = await seeded({
    snapshotOverrides: { run_action: { key: "workbench" } },
    // `ok` 는 host **payload** 의 필드다 — 봉투(`{ok, value}`)의 것이 아니다. 둘을 섞으면
    // 대역이 실제와 다른 계약을 흉내내고 그 초록은 아무것도 증명하지 않는다.
    dispatch: { open_workbench: { ok: true } },
  });
  h.events.length = 0;
  await h.controller.startGenerate();

  assert.equal(h.generateCalls().length, 0, "생성이 아니다");
  assert.deepEqual(h.only("go").map((e) => e.target), ["workbench"]);
  assert.equal(h.controller.getRun().active, null, "실행 정체가 서지 않는다");
});

test("작업대를 못 열면 조용히 끝나지 않고 사유가 기록에 남는다", async () => {
  const h = harness({
    snapshot: snap({ run_action: { key: "workbench" } }),
    dispatch: { open_workbench: { ok: false, error: "작업대 없음" } },
  });
  await h.controller.init();
  h.push(snap({ run_action: { key: "workbench" } }));
  await h.controller.startGenerate();
  assert.deepEqual(h.only("go"), [], "실패했는데 항행하지 않는다");
  assert.ok(h.log().length > 0, "사유가 남는다");
});

/* ================= ⑥ 예외 ================= */

test("generate 예외는 삼켜지지 않는다 — op 를 끝내고 사유를 남긴다", async () => {
  const h = await seeded({ generate: [new Error("브리지 끊김")] });
  await h.controller.startGenerate();

  assert.equal(h.controller.getRun().running, false, "영영 진행 중으로 남지 않는다");
  assert.ok(h.log().some((line) => line.includes("브리지 끊김")), "사유가 재진술된다");
});

/* ================= ⑦ 파괴 전이 가드 ================= */

test("파괴 전이 가드는 실시간 질의다 — 스냅샷 캐시를 읽지 않는다", async () => {
  const h = await seeded({ dispatch: { guard_state: { armed: false } } });
  h.events.length = 0;
  const ok = await h.controller.confirmDestructiveIfArmed("제목", "지웁니다", "지우기");

  assert.equal(ok, true, "무장 아니면 확인 없이 진행");
  assert.deepEqual(
    h.only("dispatch").map((e) => e.action), ["guard_state"],
    "판정은 매번 물어본다 — 스냅샷에 캐시된 값을 쓰면 무푸시 경로에서 stale 이다",
  );
  assert.deepEqual(h.only("confirm"), []);
});

test("무장 상태에서는 확인을 거치고 그 답이 곧 진행 여부다", async () => {
  const h = await seeded({
    dispatch: { guard_state: { armed: true, count: 2 } }, confirmAnswer: false,
  });
  const ok = await h.controller.confirmDestructiveIfArmed("제목", "지웁니다", "지우기");
  assert.equal(ok, false, "머무르기가 곧 false 다");
  assert.equal(h.confirms.length, 1);
});

/* ================= 부수 배선 ================= */

test("저장 폴더 오류는 폴더 값으로 새지 않고 오류로 읽힌다", async () => {
  const h = await seeded({ pickedFolder: "ERROR: 권한 없음" });
  await h.controller.pickOutputFolder();
  const line = h.log().at(-1);
  assert.match(line, /폴더 오류/);
  assert.ok(!/^저장 폴더:/.test(line.replace(/^\[[^\]]+\]\s*/, "")));
});

test("재연결은 열린 작업 이름으로만 나간다", async () => {
  const h = await seeded();
  h.push(snap());
  h.controller.relinkActive();
  assert.deepEqual(h.only("relink").map((e) => e.name), ["공고서"]);
});

test("남의 결과에서는 파일 이름 규칙을 열지 않고 이유를 말한다", async () => {
  const h = await seeded({ snapshotOverrides: { last_run_job: "다른 작업" } });
  h.push(snap({ last_run_job: "다른 작업" }));
  h.controller.openRenameRules();
  assert.deepEqual(h.only("openGuarded"), [], "남의 실행 규칙을 열지 않는다");
  assert.ok(h.log().some((line) => line.includes("다른 작업")), "왜 안 열렸는지 말한다");
});
