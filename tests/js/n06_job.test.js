/* N-06 lane D — 「문서 만들기」 실행 표면의 소유·수명주기 계약.
 *
 * ## 겨눈 자리를 옮긴 이유(R4-03)
 *
 * 이 파일의 주어는 `frontend/js/screens/job.js` 의 ESM factory 였다. R4-03 이 그 파일을
 * 절단하면서 주어가 `frontend/src/screens/job_run.ts` 의 React 컨트롤러로 옮겼다.
 * **묻는 것은 그대로다** — 답하는 구현만 바뀌었으므로 질문을 지우지 않고 새 구현에 다시 묻는다.
 *
 *  ① 공개 표면 — 파사드 키 집합·타입이 계약 표와 정확히 같다(프로브가 이 이름을 부른다).
 *  ② init 멱등 — 성공한 init 재호출에서 model 구독의 **실측 delta 0**.
 *  ③ 동시 init·첫 거절 회복 — 구독 중복 0, rejection 은 호출자에게 전파(조용히 삼키지 않는다).
 *  ④ 교차 화면 콜백 `aimAt` — 진입 성사 뒤에만, late-binding 으로 잡힌다.
 *  ⑤ 음성 — IIFE 0 · 제품 전역 판독 0 · legacy `.js` 그래프 직접 import 0.
 *  ⑥ client 는 객체째 — `dispatch` 프로퍼티 교체가 다음 호출에서 관측된다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createJobRunController } from "../../frontend/src/screens/job_run.ts";

const SRC_URL = new URL("../../frontend/src/screens/job_run.ts", import.meta.url);
const SRC = readFileSync(SRC_URL, "utf8");

/* 실앱 프로브와 셸이 부르는 이름 — 이 집합이 곧 소비 계약이다. */
const SURFACE = [
  "model", "subscribe", "getRun", "getUi", "client", "notify",
  "overwriteBody", "guardBody", "resultExitLine", "selectionLine",
  "confirmDestructiveIfArmed", "log",
  "renderResult", "markResultStale",
  "startGenerate", "cancelGeneration", "closeResult", "selectFailed", "openRenameRules",
  "pickOutputFolder", "relinkActive", "openPreviewFrom", "closePreview",
  "previewMove", "previewBlankOnly", "previewApprove", "previewEdit",
  "previewFixField", "previewFixFilename", "openRepair", "toggleLog",
  "init", "dispose",
];

/* N-10 에서 은퇴한 제품 전역 — 별칭이 죽은 뒤 **판독**이 되살아나면 이 화면은 영영
   undefined 를 읽고 조용히 아무것도 안 한다. 이름을 그대로 겨눈 채로 둔다. */
const PRODUCT_GLOBALS = [
  "Bridge", "__push", "Nav", "AppCloseGuard",
  "JobScreen", "LibraryScreen", "EditorScreen", "WorkbenchScreen",
  "Modal", "Popover", "Preserve", "Intent", "UndoToast", "SurfaceSheet", "GroupList",
  "Guard", "escHtml", "Copy", "EditorEntry", "PathTrack", "Relink",
  "DataZone", "SheetPicker", "Theme", "Personalization", "DataPicker",
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
    doc: { getElementById: () => null, querySelector: () => null },
    selectionLine: (n) => `${n}행 선택`,
    notify() {},
  });
  const push = (value) => {
    snapshot = value;
    for (const listener of [...subscribers]) listener();
  };
  return {
    controller, calls, editorEntry, client, push,
    listeners: () => listeners,
    initialCalls: () => initialCalls,
  };
}

const SNAP = { has_job: true, job_name: "A", preview: { pos: 0, rows: [] } };

/* ================= ⑤ 음성 조건 ================= */

test("음성: IIFE 0 · 제품 전역 판독 0 · legacy .js 그래프 직접 import 0", () => {
  assert.ok(!SRC.includes("(function () {"), "IIFE 래퍼가 남아 있다");
  assert.ok(!SRC.trimEnd().endsWith("})();"), "IIFE 종결이 남아 있다");
  const re = new RegExp("(?:window|globalThis)\\s*\\.\\s*(" + PRODUCT_GLOBALS.join("|") + ")\\b", "g");
  const hits = SRC.match(re) || [];
  assert.deepEqual(hits, [], "제품 전역 참조가 남아 있다: " + hits.join(", "));
  assert.ok(!/export\s+default/.test(SRC), "export default 금지");
  // 이 층은 legacy `.js` 그래프를 직접 import 하지 않는다 — 공유 합성기는 주입으로 온다.
  // 그래야 `.ts` 소유 경계가 `.js` 파일의 수명에 묶이지 않는다(R4-03 이 relink.js 를
  // 지우면서 실제로 물린 자리다).
  const imports = [...SRC.matchAll(/^import\s.*?from\s+"([^"]+)"/gm)].map((m) => m[1]);
  assert.ok(imports.length > 0, "직접 import 가 하나도 없다");
  for (const p of imports) {
    assert.ok(!p.includes("../../js/"), "legacy .js 직접 import: " + p);
    assert.ok(!/screens\/(editor|library|workbench|job_read)\b/.test(p), "화면 간 import: " + p);
  }
  assert.ok(SRC.includes("selectionLine(count: number"), "공유 합성기는 주입 계약이다(양성 대조)");
});

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
