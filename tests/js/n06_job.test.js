/* 「문서 만들기」 controller와 실행 정체 reducer의 장기 행동 계약. */
import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { createJobRunController } from "../../frontend/src/screens/job_run.ts";
import {
  JobActionBar, JobStatusPill, JobWorkbenchStatus,
} from "../../frontend/src/screens/job_run.ts";
import { JobPreviewSheet } from "../../frontend/src/screens/job_preview.ts";
import {
  acceptDirect,
  acceptFull,
  acceptProgress,
  beginRun,
  createTokenFactory,
  initialRunState,
  isForeignResult,
} from "../../frontend/src/screens/job_run_state.ts";
import { JobDataHeader, createJobRunAdapter } from "../../frontend/src/screens/job_read.ts";

/* 실앱 프로브와 셸이 부르는 이름 — 이 집합이 곧 소비 계약이다. */
const SURFACE = [
  'recoverRecordIssue', 'recoverContext',
  "model", "subscribe", "getRun", "getUi", "getTemplateChange", "client", "notify",
  "overwriteBody", "guardBody", "resultExitLine", "selectionLine",
  "confirmDestructiveIfArmed", "log",
  "renderResult", "markResultStale",
  "openBindingRequirement", "resolveExecution",
  "startGenerate", "cancelGeneration", "closeResult", "selectFailed", "openRenameRules",
  "pickOutputFolder",
  "relinkActive", "templateCheck", "templateApply",
  "openPreviewFrom", "closePreview",
  "previewMove", "previewBlankOnly", "previewApprove", "previewEdit",
  "previewFixField", "previewFixFilename",
  // 산출물 관찰(S7-03 · #825) — 미리보기와 **별도 표면**이라 이름도 갈린다.
  "openArtifactFrom", "closeArtifact", "saveArtifactAs",
  "openRepair", "toggleLog",
  "init", "dispose",
];

/* ---------------------------------------------------------------- 대역 -- */

function harness(options = {}) {
  const calls = [];
  const notes = [];
  const confirmSpecs = [];
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
    modal: {
      confirm: (spec) => {
        confirmSpecs.push(spec);
        return Promise.resolve(options.confirmResult ?? true);
      },
      open() {}, close() {},
    },
    navigation: { go() {}, currentScreen: () => "job" },
    doc: options.doc ?? {
      getElementById: () => null, querySelector: () => null,
      querySelectorAll: () => [], activeElement: null,
    },
    selectionLine: (n) => `${n}행 선택`,
    notify(message) { notes.push(message); },
  });
  const push = (value) => {
    snapshot = value;
    for (const listener of [...subscribers]) listener();
  };
  return {
    controller, calls, notes, confirmSpecs, editorEntry, client, push,
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

/* ================= ④ 진입 문맥이 겨눌 자리를 나른다 ================= */

// 조준은 editor 가 **자기 진입 문맥으로** 한다(#789). 종전 이 자리의 증거는 port 너머
// `aimAt` 호출을 셌는데, 그 메서드는 `EditorEntryPort` 표면에 **없다** — 대역이 진짜 port 보다
// 능력이 많아서 초록이었고, 실제 앱에서는 `typeof` 확인에 걸려 조용히 지나갔다. 그래서 여기서
// 세는 것을 「무엇을 불렀는가」에서 **「무엇을 넘겼는가」** 로 옮긴다.

test("#789 미리보기 수정은 exact target 을 진입 문맥으로 넘긴다", async () => {
  const h = harness({ openGuardedResult: true, snapshot: SNAP });
  await h.controller.init();
  h.push(SNAP);
  await h.controller.previewFixField("공고명");
  const [, context] = h.editorCalls.at(-1);
  assert.equal(context.target, "binding/공고명");
  assert.equal(context.entry_reason, "preview_result");
});

test("#789 exact Binding 수정도 같은 문맥을 넘긴다", async () => {
  const h = harness({ openGuardedResult: true, snapshot: SNAP });
  await h.controller.init();
  h.push(SNAP);
  await h.controller.openBindingRequirement("binding/추가확인", "추가 확인");
  const [, context] = h.editorCalls.at(-1);
  assert.equal(context.target, "binding/추가확인");
  assert.equal(context.entry_reason, "document_browser_repair");
});

test("#789 target 없는 일반 수리 진입은 겨눌 자리를 넘기지 않는다", async () => {
  // 음성 대조 — 겨눌 자리가 없는 진입까지 조준 문맥을 실으면 엉뚱한 행에 초점이 선다.
  const h = harness({ openGuardedResult: true, snapshot: SNAP });
  await h.controller.init();
  h.push(SNAP);
  h.controller.openRepair("fix-mapping");
  await Promise.resolve();
  const [, context] = h.editorCalls.at(-1);
  assert.equal(context.target, undefined);
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

test("managed HWPX create는 legacy와 같은 generate 왕복을 탄다 — 조용한 로그 분기 철거(S6-05 #812)", async () => {
  // 옛 조기 return(#729 잔여위험 2: reason 로그 후 무반응)은 철거됐다 — 판정은 전부
  // 백엔드가 지고, 거절도 generate 왕복의 결과 dict 로 시끄럽게 돌아온다.
  const snap = { ...SNAP, managed_hwpx: true, gate: { enabled: true }, run_action: { key: "generate" }, workbench_observation: { create_action: { label: "문서 만들기", enabled: true, disabled_reason: null } } };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);
  await h.controller.startGenerate();

  const generateCalls = h.calls.filter((call) => call.method === "generate");
  assert.equal(generateCalls.length, 1);
  // run_token 왕복 계약: 표면이 발급한 토큰이 세 번째 인자로 실린다(bridge.js 경로 아님).
  assert.equal(typeof generateCalls[0].args[2], "string");
  assert.ok(generateCalls[0].args[2].length > 0);
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
      // U3-03(#876): backend 가 조치 필요만 실어 준다 — 분류표 전건이 오지 않는다.
      input_requirements: [
        { field_id: "깨짐", display_label: "깨짐", binding_state: "BROKEN", action_required: true, exact_target: "binding/깨짐" },
        { field_id: "신규", display_label: "신규", binding_state: "NEW_ACTIVE_FIELD", action_required: true, exact_target: "binding/신규" },
      ],
      create_action: { label: "문서 만들기", enabled: false, disabled_reason: reason },
    },
  };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);
  const requirements = renderToStaticMarkup(createElement(JobWorkbenchStatus, { controller: h.controller }));
  assert.ok(requirements.includes("입력이 필요한 항목"));
  for (const label of ["깨짐", "신규"]) assert.ok(requirements.includes(label));
  assert.equal((requirements.match(/data-exact-target=/g) || []).length, 2);
  assert.ok(requirements.includes("binding/깨짐"));
  assert.ok(requirements.includes("binding/신규"));

  const action = renderToStaticMarkup(createElement(JobActionBar, { controller: h.controller }));
  assert.match(action, /id="jobManagedCreate"[^>]*disabled=""/);
  assert.ok(action.includes("문서 만들기"));
  assert.ok(action.includes(reason));
});

test("입력이 필요한 항목 0건이면 라벨까지 포함해 구획을 안 세운다 (#876)", async () => {
  const snap = {
    ...SNAP, managed_hwpx: true,
    workbench_observation: {
      supported: true, input_requirements: [], input_requirements_label: "입력이 필요한 항목",
      execution_status_code: "CURRENT", execution_status_phrase: "현재 설정이 반영됐습니다",
      record_validation: { validated_count: 2, blocked_count: 0, issue_count: 0, issues: [] },
    },
  };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);

  const markup = renderToStaticMarkup(createElement(JobWorkbenchStatus, { controller: h.controller }));
  assert.equal(markup.includes("입력이 필요한 항목"), false);
  assert.equal(markup.includes("jobInputRequirements"), false);
  // 나머지 구획은 그대로 선다 — 확인 대상 정보·미지정 조치 요구를 숨기지 않는다.
  for (const text of ["현재 실행 상태", "현재 설정이 반영됐습니다", "데이터 확인",
    "2건의 데이터를 확인했습니다.", "저장 폴더", "생성 예정 문서"]) {
    assert.ok(markup.includes(text), text);
  }
});

test("managed 생성 내용 확인은 backend DTO만 그리고 token만 왕복한다", async () => {
  const preview = {
    preview_token: "opaque-current-token",
    requirement: { kind: "REQUIRED", reason: "DESTRUCTIVE_OVERWRITE" },
    included_content_summary: "데이터 1건 · 항목 2개",
    ordered_records: [{
      record_identity: "record-7",
      record_display_locator: "데이터 8행",
      logical_field_values: [
        { field_id: "f_name", display_label: "이름", value: "홍길동" },
        { field_id: "f_note", display_label: "f_note", value: "원문 값" },
      ],
      planned_document_relative_path: "backend-exact.hwpx",
      collision_disposition: "WRITE_OVERWRITE",
    }],
  };
  const snap = {
    ...SNAP, managed_hwpx: true, preview: { ...SNAP.preview, open: true },
    workbench_observation: {
      supported: true, primary_action: "REVIEW_PREVIEW", preview_satisfied: false,
      preview_requirement: preview.requirement,
      semantic_preview: preview,
      create_action: { label: "문서 만들기", enabled: false, disabled_reason: "S6 부재" },
    },
  };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);

  const sheet = renderToStaticMarkup(
    createElement(JobPreviewSheet, { controller: h.controller }),
  );
  for (const text of [
    "생성 내용 확인", "포함할 내용", "데이터 1건 · 항목 2개", "데이터 8행",
    "이름", "홍길동", "f_note", "원문 값", "backend-exact.hwpx",
    "기존 파일 덮어쓰기", "기존 파일을 덮어쓸 예정입니다.", "확인 완료",
  ]) assert.ok(sheet.includes(text), text);
  for (const forbidden of ["SEMANTIC", "VALUE", "current_plan_ref", "representative_vdr_ref"])
    assert.equal(sheet.includes(forbidden), false, forbidden);

  const action = renderToStaticMarkup(
    createElement(JobActionBar, { controller: h.controller }),
  );
  assert.match(action, /id="jobManagedPreviewOpen"[^>]*class="btn primary"|class="btn primary"[^>]*id="jobManagedPreviewOpen"/);
  h.controller.previewApprove(preview.preview_token);
  await Promise.resolve();
  assert.deepEqual(h.calls.at(-1), {
    screen: "job", action: "preview_approve",
    payload: { preview_token: "opaque-current-token" },
  });

  const optional = {
    ...snap,
    workbench_observation: {
      ...snap.workbench_observation,
      primary_action: "RESOLVE_RUNTIME_POLICY",
      preview_satisfied: true,
      semantic_preview: { ...preview, requirement: { kind: "OPTIONAL" } },
    },
  };
  h.push(optional);
  const optionalSheet = renderToStaticMarkup(
    createElement(JobPreviewSheet, { controller: h.controller }),
  );
  assert.equal(optionalSheet.includes('id="previewApprove"'), false);
  assert.ok(optionalSheet.includes("필요할 때 생성 내용을 확인할 수 있습니다."));

  const source = String(JobPreviewSheet);
  for (const forbidden of ["existsSync", "OVERWRITE_EXPLICIT", "planned_document_relative_path =", ".sort("])
    assert.equal(source.includes(forbidden), false, forbidden);

  h.push({
    ...snap,
    preview: { ...snap.preview, open: false },
    workbench_observation: { ...snap.workbench_observation, semantic_preview: null },
  });
  const closedAction = renderToStaticMarkup(
    createElement(JobActionBar, { controller: h.controller }),
  );
  assert.ok(closedAction.includes('id="jobManagedPreviewOpen"'));

  const closedPreview = { ...preview };
  Object.defineProperty(closedPreview, "ordered_records", {
    get() { throw new Error("closed preview rendered records"); },
  });
  h.push({
    ...snap,
    preview: { ...snap.preview, open: false },
    workbench_observation: { ...snap.workbench_observation, semantic_preview: closedPreview },
  });
  assert.doesNotThrow(() => renderToStaticMarkup(
    createElement(JobPreviewSheet, { controller: h.controller }),
  ));
});

test('managed delivery는 backend intent와 exact path만 그리고 command 뒤 push를 기다린다', async () => {
  const snap = {
    ...SNAP, managed_hwpx: true,
    workbench_observation: {
      supported: true, input_requirements: [], input_requirements_label: '입력이 필요한 항목',
      execution_status_code: 'CURRENT', execution_status_phrase: '현재 설정이 반영됐습니다',
      run_delivery_intent: {
        output_directory: 'C:\\문서', collision_policy: 'OVERWRITE_EXPLICIT',
      },
      delivery: {
        resolvable: true, blockers: [],
        planned_documents: [{
          record_identity: 'opaque-record', item_ordinal: 0,
          relative_path: '백엔드-그대로_7.hwpx',
          collision_disposition: 'WRITE_OVERWRITE',
        }],
      },
    },
  };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);

  const markup = renderToStaticMarkup(
    createElement(JobWorkbenchStatus, { controller: h.controller }),
  );
  for (const text of [
    '저장 폴더', '생성 예정 문서', 'C:\\문서',
    '백엔드-그대로_7.hwpx',
    // 덮어쓴다는 사실은 정책 라벨이 아니라 **파일마다** 선다(U4 계열2-27).
    '기존 파일 덮어쓰기',
    '실제 파일 생성을 예약한 것은 아닙니다.',
    // U3-06(#879): 계획도 어디에 떨어지는지 같은 자리에서 진술한다.
    '저장 폴더: C:\\문서',
  ]) assert.ok(markup.includes(text), text);

  // 고르는 자리도 새로고침 동사도 없다(U4 계열2-27 · 2-28) — 정책은 기본값 하나이고
  // 계획은 그것을 바꾸는 전이에서 Python 이 다시 센다.
  for (const gone of ['충돌 처리', '목록 새로 확인', 'jobDeliveryCollision', 'jobRefreshDelivery'])
    assert.equal(markup.includes(gone), false, gone);

  const source = String(JobWorkbenchStatus);
  for (const forbidden of ['new Date', '{{date', '{{seq', 'existsSync', 'casefold', '.sort(']) {
    assert.equal(source.includes(forbidden), false, forbidden);
  }
});

test('저장 폴더는 backend가 도출한 경로·출처·사유를 그대로 그린다', async () => {
  const snap = {
    ...SNAP, managed_hwpx: true,
    workbench_observation: {
      supported: true, input_requirements: [], input_requirements_label: '입력이 필요한 항목',
      execution_status_code: 'CURRENT', execution_status_phrase: '현재 설정이 반영됐습니다',
      output_folder: {
        directory: 'C:\\서고\\Results',
        source: 'template_default',
        source_label: '기본값',
        notice: '지난번에 지정한 저장 폴더를 찾을 수 없습니다. 기본 폴더로 되돌렸습니다.',
      },
      run_delivery_intent: {
        output_directory: 'C:\\서고\\Results', collision_policy: 'OVERWRITE_EXPLICIT',
      },
      delivery: {
        resolvable: true, blockers: [],
        planned_documents: [{
          record_identity: 'opaque-record', item_ordinal: 0,
          relative_path: '공고서-001.hwpx', collision_disposition: 'WRITE_NEW',
        }],
      },
    },
  };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);

  const markup = renderToStaticMarkup(
    createElement(JobWorkbenchStatus, { controller: h.controller }),
  );
  // 표시된 기본값이지 빈칸이 아니다 — 경로·출처·사유가 전부 backend 문안이다.
  assert.ok(markup.includes('value="C:\\서고\\Results"'));
  assert.ok(markup.includes('기본값'));
  assert.ok(markup.includes('지난번에 지정한 저장 폴더를 찾을 수 없습니다.'));
  assert.ok(markup.includes('저장 폴더: C:\\서고\\Results'));
  // 라벨을 프런트가 다시 만들지 않는다.
  const source = String(JobWorkbenchStatus);
  for (const forbidden of ['기억한 폴더', '직접 지정', 'template_default', 'Results']) {
    assert.equal(source.includes(forbidden), false, forbidden);
  }
});

test('delivery blocker는 backend exact 충돌 경로를 추론 없이 구분해 표시한다', async () => {
  const blockers = ['발주요청서-2026-001.hwpx', '발주요청서-2026-002.hwpx'].map(
    (conflicting_relative_path, item_ordinal) => ({
      code: 'OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED',
      message: '같은 이름의 파일이 있습니다:',
      item_ordinal,
      field_id: null,
      conflicting_relative_path,
    }),
  );
  const snap = {
    ...SNAP, managed_hwpx: true,
    workbench_observation: {
      supported: true, input_requirements: [], input_requirements_label: '입력이 필요한 항목',
      execution_status_code: 'CURRENT', execution_status_phrase: '현재 설정이 반영됐습니다',
      run_delivery_intent: {
        output_directory: 'C:\\문서', collision_policy: 'FAIL',
      },
      delivery: { resolvable: false, planned_documents: [], blockers },
    },
  };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);

  const markup = renderToStaticMarkup(
    createElement(JobWorkbenchStatus, { controller: h.controller }),
  );
  for (const blocker of blockers) assert.ok(markup.includes(blocker.conflicting_relative_path));
  assert.equal(String(JobWorkbenchStatus).includes('blocker.item_ordinal'), false);
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
  const scrolled = [];
  const focusOpts = [];
  const classes = new Set();
  const staleCleared = [];
  const stale = { classList: { remove: (name) => { staleCleared.push(name); } } };
  const element = {
    focus: (opts) => { focused = true; focusOpts.push(opts); },
    scrollIntoView: (opts) => { scrolled.push(opts); },
    classList: { add: (name) => { classes.add(name); }, remove: (name) => { classes.delete(name); } },
  };
  const doc = {
    getElementById: (id) => id === 'backend-cell' ? element : null,
    querySelector: () => null,
    querySelectorAll: () => [stale],
    get activeElement() { return focused ? element : null; },
  };
  const h = harness({
    snapshot: snap,
    dispatchValue: { element_id: 'backend-cell', fallback_element_id: 'backend-row' },
    doc,
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
  // 겨눔은 **보이는 것**이어야 한다(#945 F1): 지난 표지를 걷고, 성공한 focus 수명에만 표지를
  // 붙이고, 중첩 스크롤러를 페이지째 끌어올리지 않는다.
  assert.deepEqual(staleCleared, ['jb-aimed']);
  assert.deepEqual(focusOpts, [{ preventScroll: true }]);
  assert.equal(classes.has('jb-aimed'), true);
  assert.deepEqual(scrolled, [{ block: 'nearest' }]);
  assert.deepEqual(h.notes, []);
});

test('문제 위치를 못 찾으면 접힌 로그가 아니라 가시 채널로 말한다', async () => {
  const h = harness({
    snapshot: { ...SNAP, managed_hwpx: true },
    dispatchValue: { element_id: 'gone-cell', fallback_element_id: 'gone-row' },
  });
  await h.controller.init();

  await h.controller.recoverRecordIssue({ model_index: 1 });
  assert.equal(h.notes.length, 1, '실패는 조용한 무동작으로 두지 않는다');
  assert.ok(h.notes[0].includes('문제 위치가 현재 표에 없습니다.'));
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

test('context error는 복구 동사를 활성으로 세우고 refresh_observation을 보낸다', async () => {
  /* #912 D4 — 종전에는 이 자리에 danger 문안만 섰고 그것을 지울 동사가 없었다.
     `refresh_observation` 은 registry·핸들러 양쪽에 있었는데 프런트 호출자가 0 이었다.
     문안·활성은 backend 가 실은 `recover_action` 을 그대로 쓴다(링2 재조립 0). */
  const snap = {
    ...SNAP, managed_hwpx: true,
    workbench_observation: {
      supported: true,
      kind: 'context_error',
      code: 'EXECUTION_ADMISSION_CONTEXT_ERROR',
      detail: '현재 실행 맥락을 복원하지 못했습니다',
      input_requirements: [],
      input_requirements_label: '입력이 필요한 항목',
      execution_status_code: 'CONTEXT_ERROR',
      execution_status_phrase: '현재 실행 상태를 확인할 수 없습니다',
      recover_action: { label: '다시 확인', enabled: true, disabled_reason: null },
    },
  };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);

  const markup = renderToStaticMarkup(
    createElement(JobWorkbenchStatus, { controller: h.controller }),
  );
  assert.ok(markup.includes('id="jobRecoverContext"'));
  assert.ok(markup.includes('다시 확인'));
  /* 비활성으로 서면 「눌러 보라」는 지시가 거짓이 된다 — 그 갈래를 명시로 배제한다. */
  assert.equal(/id="jobRecoverContext"[^>]*disabled/.test(markup), false);

  await h.controller.recoverContext();
  assert.equal(h.calls.at(-1).action, 'refresh_observation');
  assert.deepEqual(h.calls.at(-1).payload, {});
});

test('관찰이 정상이면 복구 동사를 세우지 않는다', async () => {
  /* 음성 대조 — backend 가 `recover_action` 을 싣지 않은 자리에 버튼이 서면 표면이
     스스로 판정한 것이다. 그 갈래는 이 게이트가 막는다. */
  const snap = {
    ...SNAP, managed_hwpx: true,
    workbench_observation: {
      supported: true,
      kind: 'observation',
      primary_action: 'CREATE_DOCUMENTS',
      input_requirements: [],
      input_requirements_label: '입력이 필요한 항목',
      execution_status_code: 'CURRENT',
      execution_status_phrase: '현재 설정이 반영됐습니다',
    },
  };
  const h = harness({ snapshot: snap });
  await h.controller.init();
  h.push(snap);

  const markup = renderToStaticMarkup(
    createElement(JobWorkbenchStatus, { controller: h.controller }),
  );
  assert.equal(markup.includes('jobRecoverContext'), false);
});

/* ============ 데이터 통지의 닫기 문법(U4 §2.12 · #945 F4) ============ */

/* `data_notice` 는 매 변이 자동 소멸이 아니라 사유가 해소될 때까지 남는 채널인데 끄는
   동사가 없었다(#874 `saveMessage`·#933 편집기 `notice` 에 이은 3세대 같은 결함류).
   렌더만 재는 이유는 닫기의 결과가 Python 소유라서다 — 그 전이는 `tests/test_webapp_job.py`
   의 `dismiss_data_notice` 가 진다. */
function dataHeaderStub(snapshot) {
  return {
    model: { getSnapshot: () => ({ full: snapshot, progress: null }), subscribe: () => () => {} },
    openDataPicker() {}, remountData() {}, connectJobData() {},
    dismissDataNotice: async () => ({}),
  };
}

test('#945 F4 데이터 통지에는 닫기 단추가 선다', () => {
  const markup = renderToStaticMarkup(createElement(JobDataHeader, {
    controller: dataHeaderStub({
      has_job: true, has_data: false, job_name: 'A',
      data_notice: { level: 'warn', text: '연결된 데이터가 없습니다.' },
    }),
  }));
  assert.ok(markup.includes('id="jobDataNotice"'));
  assert.ok(markup.includes('id="jobDataNoticeClose"'),
    '닫을 수 없는 통지는 사유가 지나간 뒤에도 화면 위에 영구히 남는다');
  assert.ok(markup.includes('aria-label="알림 닫기"'));
  // 문안 조립(접두)은 NoticeBox 가 아니라 이 렌더러가 그대로 진다.
  assert.ok(markup.includes('확인 필요: 연결된 데이터가 없습니다.'));
});

test('#945 F4 통지가 없으면 닫기도 없다', () => {
  const markup = renderToStaticMarkup(createElement(JobDataHeader, {
    controller: dataHeaderStub({
      has_job: true, has_data: true, job_name: 'A', data_notice: null,
    }),
  }));
  assert.equal(markup.includes('jobDataNoticeClose'), false);
});
