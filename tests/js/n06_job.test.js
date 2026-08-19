/* 「문서 만들기」 controller와 실행 정체 reducer의 장기 행동 계약. */
import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { createJobRunController } from "../../frontend/src/screens/job_run.ts";
import {
  JobActionBar, JobStatusPill, JobWorkbenchStatus,
} from "../../frontend/src/screens/job_run.ts";
import {
  acceptDirect,
  acceptFull,
  acceptProgress,
  beginRun,
  createTokenFactory,
  initialRunState,
  isForeignResult,
} from "../../frontend/src/screens/job_run_state.ts";
import { createJobRunAdapter } from "../../frontend/src/screens/job_read.ts";

/* 실앱 프로브와 셸이 부르는 이름 — 이 집합이 곧 소비 계약이다. */
const SURFACE = [
  'recoverRecordIssue',
  "model", "subscribe", "getRun", "getUi", "getTemplateChange", "client", "notify",
  "overwriteBody", "guardBody", "resultExitLine", "selectionLine",
  "confirmDestructiveIfArmed", "log",
  "renderResult", "markResultStale",
  "openBindingRequirement", "resolveExecution",
  "startGenerate", "cancelGeneration", "closeResult", "selectFailed", "openRenameRules",
  "pickOutputFolder", "relinkActive", "templateCheck", "templateApply",
  "openPreviewFrom", "closePreview",
  "previewMove", "previewBlankOnly", "previewApprove", "previewEdit",
  "previewFixField", "previewFixFilename", "openRepair", "toggleLog",
  "init", "dispose",
];

/* ---------------------------------------------------------------- 대역 -- */

function harness(options = {}) {
  const calls = [];
  let listeners = 0;
  let initialCalls = 0;
  let snapshot = options.snapshot ?? null;
  const subscribers = new Set();

  const model = {
    getSnapshot: () => ({ full: snapshot, progress: null }),
    subscribe(listener) {
      listeners += 1;
      subscribers.add(listener);
      return () => { listeners -= 1; subscribers.delete(listener); };
    },
  };
  const runtime = {
    model: () => model,
    loadInitial: () => {
      initialCalls += 1;
      return options.initialRejects && initialCalls === 1
        ? Promise.reject(new Error("initial 거절"))
        : Promise.resolve({});
    },
  };
  const client = {
    invoke: (method, ...args) => {
      calls.push({ method, args });
      return Promise.resolve({ ok: true, value: options.invokeValue ?? null });
    },
    dispatch: (screen, action, payload) => {
      calls.push({ screen, action, payload });
      return Promise.resolve({ ok: true, value: options.dispatchValue ?? {} });
    },
  };
  const port = (impl) => {
    let bound = impl ?? null;
    return {
      bind(value) {
        if (bound !== null) throw new Error("두 번째 결속");
        bound = value;
      },
      current: () => bound,
    };
  };
  const editorEntry = { openGuarded: () => options.openGuardedResult ?? true, aimAt: undefined };
  const editorCalls = [];
  editorEntry.openGuarded = (...args) => { editorCalls.push(args); return options.openGuardedResult ?? true; };
  const ports = {
    jobRun: port(), jobRunCoordination: port(),
    jobData: port({ flushPendingEdits: () => Promise.resolve() }),
    jobRelinkFlow: port({ relinkTemplateFor: () => Promise.resolve() }),
    editorEntry: port(editorEntry),
  };
  const controller = createJobRunController({
    runtime, client, ports,
    services: { relink: port({ relinkTemplate: () => Promise.resolve(true) }) },
    modal: { confirm: () => Promise.resolve(true), open() {}, close() {} },
    navigation: { go() {} },
    doc: options.doc ?? { getElementById: () => null, querySelector: () => null },
    selectionLine: (n) => `${n}행 선택`,
    notify() {},
  });
  const push = (value) => {
    snapshot = value;
    for (const listener of [...subscribers]) listener();
  };
  return {
    controller, calls, editorEntry, client, push,
    editorCalls,
    listeners: () => listeners,
    initialCalls: () => initialCalls,
  };
}

const SNAP = { has_job: true, job_name: "A", preview: { pos: 0, rows: [] } };

/* ================= ① 공개 표면 ================= */

test("공개 표면 — 프로브·셸이 부르는 이름 집합이 계약 표와 정확히 같다", () => {
  const { controller } = harness();
  assert.deepEqual(Object.keys(controller).sort(), [...SURFACE].sort());
  for (const key of ["overwriteBody", "guardBody", "resultExitLine", "renderResult",
    "markResultStale", "confirmDestructiveIfArmed", "log", "init"]) {
    assert.equal(typeof controller[key], "function", key + " 는 함수다");
  }
});

/* ================= ②③ 수명주기 ================= */

test("init 멱등 — 성공한 재호출에서 model 구독 delta 가 0 이다", async () => {
  const h = harness();
  await h.controller.init();
  assert.equal(h.listeners(), 1, "구독은 한 벌");
  await h.controller.init();
  await h.controller.init();
  assert.equal(h.listeners(), 1, "재호출은 구독을 늘리지 않는다");
});

test("동시 init 2회 — 구독은 한 벌이다", async () => {
  const h = harness();
  await Promise.all([h.controller.init(), h.controller.init()]);
  assert.equal(h.listeners(), 1);
});

test("첫 initial 거절은 호출자에게 전파되고 구독은 그대로 한 벌이다", async () => {
  const h = harness({ initialRejects: true });
  await assert.rejects(() => h.controller.init(), /initial 거절/,
    "rejection 을 조용히 삼키지 않는다");
  assert.equal(h.listeners(), 1);
  await h.controller.init();
  assert.equal(h.listeners(), 1, "회복이 구독을 두 벌로 만들지 않는다");
});

test("dispose 는 구독을 걷고 세대를 올려 앞선 실행의 응답을 남으로 만든다", async () => {
  const h = harness();
  await h.controller.init();
  h.controller.dispose();
  assert.equal(h.listeners(), 0);
  assert.equal(h.controller.getRun().screenEpoch, 1);
});

/* ================= ④ 교차 콜백 late-binding ================= */

test("교차 콜백 aimAt — 진입 성사 뒤에만 호출되고 late-binding 으로 잡힌다", async () => {
  const h = harness({ openGuardedResult: true, snapshot: SNAP });
  await h.controller.init();
  h.push(SNAP);
  const aimed = [];
  // 구성 **뒤에** 갈아끼운 콜백이 호출 시점에 잡힌다.
  h.editorEntry.aimAt = (target) => aimed.push(target);
  await h.controller.previewFixField("공고명");
  assert.deepEqual(aimed, ["binding/공고명"]);
});

test("진입이 거절되면 겨눔은 나가지 않는다", async () => {
  const h = harness({ openGuardedResult: false, snapshot: SNAP });
  await h.controller.init();
  h.push(SNAP);
  const aimed = [];
  h.editorEntry.aimAt = (target) => aimed.push(target);
  await h.controller.previewFixField("공고명");
  assert.deepEqual(aimed, [], "성사 없이 겨누면 남의 화면을 조준한다");
});

/* ================= ⑥ 포트는 객체째 ================= */

test("client 는 객체째 — 발신이 교체한 dispatch 프로퍼티를 본다", async () => {
  const h = harness();
  await h.controller.init();
  const seen = [];
  h.client.dispatch = (screen, action) => {
    seen.push(["A", action]);
    return Promise.resolve({ ok: true, value: {} });
  };
  h.controller.previewMove(1);
  h.client.dispatch = (screen, action) => {
    seen.push(["B", action]);
    return Promise.resolve({ ok: true, value: {} });
  };
  h.controller.previewMove(-1);
  assert.deepEqual(seen, [["A", "preview_move"], ["B", "preview_move"]],
    "메서드를 사전 추출하면 프로브의 스텁이 우회된다");
});

test("job run adapter는 full/progress 순서와 preview 전 정산을 보존한다", async () => {
  let value = { full: { id: 1 }, progress: null };
  const listeners = new Set();
  const events = [];
  const adapter = createJobRunAdapter({
    model: {
      getSnapshot: () => value,
      subscribe: (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
    },
    beforePreview: async () => { events.push("flush"); },
    openPreview: async (request) => { events.push(["preview", request]); },
  });
  const release = adapter.attach({
    onFull: (full) => events.push(["full", full]),
    onProgress: (progress) => events.push(["progress", progress]),
  });
  value = { full: value.full, progress: { done: 1 } };
  for (const listener of listeners) listener();
  await adapter.openPreview({ at: 2 });
  assert.deepEqual(events, [
    ["full", { id: 1 }],
    ["progress", { done: 1 }],
    "flush",
    ["preview", { at: 2 }],
  ]);
  release();
  assert.equal(listeners.size, 0);
  assert.throws(release, /정확히 한 번/);
});

/* ================= 실행 정체 reducer ================= */

function runSnapshot(overrides = {}) {
  return {
    has_job: true,
    job_name: "공고서",
    data_mount: "m1",
    out_dir: "C:\\out",
    selection_key: "s1",
    rules_key: "r1",
    last_run_job: "공고서",
    ...overrides,
  };
}

function runState(overrides = {}) {
  return acceptFull(initialRunState(), runSnapshot(overrides));
}

function completedRun(state = runState(), token = "t1") {
  return acceptDirect(beginRun(state, token), {
    ok: true,
    status: "ok",
    title: "완료",
    run_token: token,
  });
}

test("실행 토큰은 충돌하지 않고 덮어쓰기 왕복 동안 같은 op를 유지한다", () => {
  const nextToken = createTokenFactory();
  assert.equal(new Set(Array.from({ length: 100 }, nextToken)).size, 100);

  const running = beginRun(runState(), "t1");
  const awaitingOverwrite = acceptDirect(running, {
    ok: false,
    needs_overwrite: true,
    run_token: "t1",
  });
  assert.equal(awaitingOverwrite.running, true);
  assert.equal(awaitingOverwrite.active.runToken, "t1");
  assert.equal(awaitingOverwrite.result, null);
});

test("옛 direct/progress와 완료 뒤 progress는 현재 실행을 되돌리지 않는다", () => {
  const current = beginRun(beginRun(runState(), "old"), "new");
  const withProgress = acceptProgress(current, { done: 3, total: 3, run_token: "new" });

  for (const stale of [
    acceptDirect(withProgress, { ok: true, title: "옛 결과", run_token: "old" }),
    acceptProgress(withProgress, { done: 1, total: 9, run_token: "old" }),
  ]) {
    assert.equal(stale.result, null);
    assert.deepEqual(stale.progress, { done: 3, total: 3, run_token: "new" });
    assert.match(stale.discarded.at(-1).reason, /다른 실행/);
  }

  const done = completedRun(runState(), "done");
  const late = acceptProgress(done, { done: 2, total: 3, run_token: "done" });
  assert.equal(late.running, false);
  assert.equal(late.progress, null);
  assert.match(late.discarded.at(-1).reason, /종료된/);
});

test("결과 수명은 세션 교체면 reset, 규칙·선택·폴더 변경이면 stale이다", () => {
  const done = completedRun();
  assert.equal(isForeignResult(done), false);
  for (const next of [
    runSnapshot({ job_name: "다른 작업", last_run_job: "공고서" }),
    runSnapshot({ data_mount: "m2" }),
  ]) {
    assert.equal(acceptFull(done, next).result, null);
  }
  for (const next of [
    runSnapshot({ selection_key: "s2" }),
    runSnapshot({ rules_key: "r2" }),
    runSnapshot({ out_dir: "D:\\other" }),
  ]) {
    assert.equal(acceptFull(done, next).result.stale, true);
  }
  assert.notEqual(acceptFull(done, runSnapshot()).result.stale, true);

  const moved = acceptFull(done, runSnapshot({ job_name: "다른 작업", last_run_job: "다른 작업" }));
  const otherResult = completedRun(moved, "t2");
  const foreign = {
    ...otherResult,
    lastFull: runSnapshot({ job_name: "제3 작업", last_run_job: "다른 작업" }),
  };
  assert.equal(isForeignResult(foreign), true);
});

test("Python 결과 판정 필드는 reducer를 무가공 통과한다", () => {
  const payload = {
    ok: false,
    status: "failed",
    level: "danger",
    title: "실패",
    failures: [{ index: 3, reason: "사유" }],
    failed_selectable: 1,
    run_token: "t1",
  };
  const result = acceptDirect(beginRun(runState(), "t1"), payload).result;
  for (const [key, value] of Object.entries(payload)) assert.deepEqual(result[key], value, key);
});

test("Binding review는 backend exact target과 ReturnContext를 EditorEntry에 그대로 넘긴다", async () => {
  const h = harness({ snapshot: SNAP });
  await h.controller.init();
  h.push(SNAP);
  await h.controller.openBindingRequirement("binding/공고명", "공고명");

  assert.deepEqual(h.editorCalls, [[
    "A",
    { entry_reason: "document_browser_repair", target: "binding/공고명", evidence: { "입력이 필요한 항목": "공고명" }, return_context: { surface: "data" } },
  ]]);
});

test("backend execution action dispatches resolve_execution without frontend priority logic", async () => {
  const snap = {
    ...SNAP, managed_hwpx: true,
    workbench_observation: {
      supported: true, input_requirements: [], input_requirements_label: "",
      execution_status_code: "STALE", execution_status_phrase: "needs check",
      execution_action: { label: "check current settings", enabled: true, disabled_reason: null },
    },
  };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);

  const markup = renderToStaticMarkup(createElement(JobWorkbenchStatus, { controller: h.controller }));
  assert.ok(markup.includes("jobResolveExecution"));
  assert.ok(markup.includes("check current settings"));

  await h.controller.resolveExecution();
  assert.deepEqual(h.calls.at(-1), { screen: "job", action: "resolve_execution", payload: {} });
});

test("managed HWPX는 CURRENT여도 S6 disabled reason을 내고 legacy generate를 호출하지 않는다", async () => {
  const reason = "현재 환경에서는 문서를 만들 수 없습니다";
  const snap = { ...SNAP, managed_hwpx: true, gate: { enabled: true }, run_action: { key: "generate" }, workbench_observation: { create_action: { label: "문서 만들기", enabled: false, disabled_reason: reason } } };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);
  await h.controller.startGenerate();

  assert.equal(h.calls.filter((call) => call.method === "generate").length, 0);
  assert.ok(h.controller.getUi().log.at(-1).endsWith(reason));
});

test("managed HWPX 상태 pill은 backend 7상태 phrase를 무가공 소비한다", async () => {
  const states = [
    ["NO_EVIDENCE", "현재 설정을 확인해야 합니다"],
    ["CHECKING", "현재 설정을 확인하고 있습니다"],
    ["CURRENT", "현재 설정이 반영됐습니다"],
    ["STALE", "설정이 바뀌어 다시 확인해야 합니다"],
    ["DOMAIN_BLOCKED", "확인할 항목이 있습니다"],
    ["POLICY_BLOCKED", "현재 이 구성으로 실행을 준비할 수 없습니다"],
    ["CONTEXT_ERROR", "현재 실행 상태를 확인할 수 없습니다"],
  ];
  const h = harness();
  await h.controller.init();
  for (const [code, phrase] of states) {
    const snap = { ...SNAP, managed_hwpx: true, workbench_observation: { execution_status_code: code, execution_status_phrase: phrase } };
    h.push(snap);
    const markup = renderToStaticMarkup(createElement(JobStatusPill, { controller: h.controller }));
    assert.ok(markup.includes(String(phrase)), code);
    assert.ok(markup.includes(`data-status-code="${code}"`), code);
  }
});

test("Workbench surface는 review projection과 S6 Create action을 backend 그대로 그린다", async () => {
  const reason = "현재 환경에서는 문서를 만들 수 없습니다";
  const snap = {
    ...SNAP, managed_hwpx: true, gate: { enabled: true, text: "legacy ready" },
    workbench_observation: {
      supported: true, input_requirements_label: "입력이 필요한 항목",
      execution_status_code: "CURRENT", execution_status_phrase: "현재 설정이 반영됐습니다",
      input_requirements: [
        { field_id: "보존", display_label: "보존", binding_state: "PRESERVED", action_required: false, exact_target: "binding/보존" },
        { field_id: "깨짐", display_label: "깨짐", binding_state: "BROKEN", action_required: true, exact_target: "binding/깨짐" },
        { field_id: "신규", display_label: "신규", binding_state: "NEW_ACTIVE_FIELD", action_required: true, exact_target: "binding/신규" },
        { field_id: "비활성", display_label: "비활성", binding_state: "INACTIVE_ONLY", action_required: false, exact_target: "binding/비활성" },
      ],
      create_action: { label: "문서 만들기", enabled: false, disabled_reason: reason },
    },
  };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);
  const requirements = renderToStaticMarkup(createElement(JobWorkbenchStatus, { controller: h.controller }));
  for (const label of ["보존", "깨짐", "신규", "비활성"]) assert.ok(requirements.includes(label));
  assert.equal((requirements.match(/data-exact-target=/g) || []).length, 2);
  assert.ok(requirements.includes("binding/깨짐"));
  assert.ok(requirements.includes("binding/신규"));

  const action = renderToStaticMarkup(createElement(JobActionBar, { controller: h.controller }));
  assert.match(action, /id="jobManagedCreate"[^>]*disabled=""/);
  assert.ok(action.includes("문서 만들기"));
  assert.ok(action.includes(reason));
});

test('데이터 확인은 backend 문안과 recovery target만 소비한다', async () => {
  const target = {
    snapshot_generation: 3,
    record_identity: 'current-record/3/7',
    model_index: 7,
    field_id: 'name',
  };
  const snap = {
    ...SNAP, managed_hwpx: true,
    workbench_observation: {
      supported: true, input_requirements: [], input_requirements_label: '입력이 필요한 항목',
      execution_status_code: 'CURRENT', execution_status_phrase: '현재 설정이 반영됐습니다',
      record_validation: {
        validated_count: 1, blocked_count: 1, issue_count: 1,
        issues: [{
          record_identity: target.record_identity,
          record_display_locator: '데이터 8행',
          field_id: 'f_name',
          field_display_label: '이름',
          message: '빈 값이나 공백만 있는 값은 사용할 수 없습니다.',
          recovery_target: target,
        }],
      },
    },
  };
  let focused = false;
  const element = {
    focus: () => { focused = true; },
    scrollIntoView: () => {},
  };
  const h = harness({
    snapshot: snap,
    dispatchValue: { element_id: 'backend-cell', fallback_element_id: 'backend-row' },
    doc: {
      getElementById: (id) => id === 'backend-cell' ? element : null,
      querySelector: () => null,
    },
  });
  await h.controller.init();
  h.push(snap);

  const markup = renderToStaticMarkup(
    createElement(JobWorkbenchStatus, { controller: h.controller }),
  );
  for (const text of ['데이터 확인', '데이터 8행', '이름',
    '빈 값이나 공백만 있는 값은 사용할 수 없습니다.', '문제 위치 보기']) {
    assert.ok(markup.includes(text));
  }
  assert.equal(markup.includes('RECORD_BLANK_POLICY_VIOLATION'), false);

  await h.controller.recoverRecordIssue(target);
  assert.equal(h.calls.at(-1).payload.target, target);
  assert.equal(focused, true);
});

test('데이터 확인은 backend context error detail을 숨기지 않는다', async () => {
  const detail = '현재 데이터 검증을 완료할 수 없습니다.';
  const snap = {
    ...SNAP, managed_hwpx: true,
    workbench_observation: {
      supported: true,
      kind: 'context_error',
      code: 'INTERNAL_RECORD_CONTEXT',
      detail,
      input_requirements: [],
      input_requirements_label: '입력이 필요한 항목',
      execution_status_code: 'CONTEXT_ERROR',
      execution_status_phrase: '현재 실행 상태를 확인할 수 없습니다',
    },
  };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);

  const markup = renderToStaticMarkup(
    createElement(JobWorkbenchStatus, { controller: h.controller }),
  );
  assert.ok(markup.includes(detail));
  assert.equal(markup.includes('확인할 데이터가 없습니다.'), false);
  assert.equal(markup.includes('INTERNAL_RECORD_CONTEXT'), false);
});
