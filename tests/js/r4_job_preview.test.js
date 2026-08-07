/* R4-03 — 확인 면(생성 값 미리보기)의 컨트롤러 계약.
 *
 * 이 면의 결함은 전부 **순서**다. 세 자리가 그렇다:
 *
 *  ① 열기는 대기 중인 존 변이 **뒤에** 선다 — 안 그러면 방금 고친 값이 아닌 옛 값을 보여 준다.
 *  ② 왕복 중 화면을 떠났으면 열지 않고 **상태를 되돌린다** — 남는 「열림」이 다음 복귀에서
 *     아무 트리거 없이 면을 띄운다.
 *  ③ 「수정」의 `at` 은 `Modal.close` 가 `preview_close` 를 발화하기 **전에** 읽는다 —
 *     pos 는 닫힘에 0 으로 리셋되므로 순서를 바꾸면 복귀가 늘 첫 행으로 선다.
 *
 * 값은 하나도 여기서 만들지 않는다: 행·파일 이름·이름 계획은 실행 입력과 **같은 산출**의
 * 투영이라 표면이 다시 계산하면 미리보기가 실행과 다른 이름을 말한다. 그래서 이 파일이
 * 재는 것은 **무엇을 언제 누구에게 보내는가** 뿐이다.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { createJobRunController } from "../../frontend/src/screens/job_run.ts";

function snap(overrides = {}) {
  return {
    has_job: true, job_name: "공고서", data_mount: "m1", out_dir: "C:\\out",
    selection_key: "s1", rules_key: "r1", last_run_job: "공고서",
    preview: { pos: 2, rows: [{ name: "공고명", value: "가나다" }] },
    ...overrides,
  };
}

function textNode(text) {
  return { textContent: text };
}

function harness(options = {}) {
  const events = [];
  const openIds = new Set();          // 열린 면 스택 — 닫기의 no-op 조건이 여기서 산다
  let snapshot = options.snapshot ?? snap();
  const subscribers = new Set();
  const notify = () => { for (const listener of [...subscribers]) listener(); };
  const model = {
    getSnapshot: () => ({ full: snapshot, progress: null }),
    subscribe(listener) {
      subscribers.add(listener);
      return () => subscribers.delete(listener);
    },
  };
  const client = {
    invoke: () => Promise.resolve({ ok: true, value: null }),
    dispatch(screen, action, payload) {
      events.push({ kind: "dispatch", action, payload });
      const canned = (options.dispatch ?? {})[action];
      if (canned instanceof Error) return Promise.reject(canned);
      return Promise.resolve({ ok: true, value: canned ?? {} });
    },
  };
  const port = (impl) => {
    let bound = impl ?? null;
    return { bindReact(v) { if (bound !== null) throw new Error("두 번째 결속"); bound = v; }, current: () => bound };
  };
  const editor = {
    openGuarded(name, context) {
      events.push({ kind: "openGuarded", name, context });
      return options.openGuardedResult ?? true;
    },
    aimAt(target) { events.push({ kind: "aimAt", target }); },
  };
  const controller = createJobRunController({
    runtime: { model: () => model, loadInitial: () => Promise.resolve({}) },
    client,
    ports: {
      jobRun: port(), jobRunCoordination: port(),
      jobData: port({
        flushPendingEdits() {
          events.push({ kind: "flush" });
          return Promise.resolve();
        },
      }),
      jobRelinkFlow: port({ relinkTemplateFor: () => Promise.resolve() }),
      editorEntry: port(editor),
    },
    services: { relink: port({ relinkTemplate: () => Promise.resolve(true) }) },
    modal: {
      confirm: () => Promise.resolve(true),
      open(id, spec) { openIds.add(id); events.push({ kind: "modal.open", id, spec }); },
      close(id) {
        /* 스택에 없는 면의 닫기는 **아무 일도 하지 않는다**. 상태 구동 닫힘
           (`syncPreviewOpen`)이 무한루프를 안 도는 근거가 정확히 이 불변식이라, 대역이
           이걸 모델링하지 않으면 제품이 실물에서 도는 것과 다른 세계에서 재게 된다. */
        if (!openIds.has(id)) return;
        openIds.delete(id);
        events.push({ kind: "modal.close", id });
        // 실물의 `Modal.close` 는 onClose 를 태워 `preview_close` 를 발화하고, Python 이
        // pos 0 인 새 full 을 **push** 한다. 대역도 거기까지 해야 한다: 지역 변수만 바꾸면
        // 컨트롤러가 읽는 `run.lastFull` 은 그대로라 순서를 뒤집어도 초록이다(첫 판이
        // 실제로 그랬고, 음성 대조가 안 물어서 잡혔다).
        snapshot = { ...snapshot, preview: { ...snapshot.preview, open: false, pos: 0 } };
        notify();
      },
    },
    navigation: {
      go() {},
      // 「지금 어느 화면인가」는 셸 상태기계가 답한다 — 화면이 DOM 으로 되묻지 않는다.
      currentScreen: () => (options.currentScreen === undefined ? "job" : options.currentScreen),
    },
    doc: {
      getElementById: (id) => (options.elements ?? {})[id] ?? null,
      querySelector: () => null,
    },
    selectionLine: (n) => `${n}행 선택`,
    notify() {},
  });
  return {
    controller, events, editor,
    log: () => controller.getUi().log,
    order: () => events.map((e) => (e.kind === "dispatch" ? `dispatch:${e.action}` : e.kind)),
    only: (kind) => events.filter((e) => e.kind === kind),
    dispatched: () => events.filter((e) => e.kind === "dispatch"),
    push(value) {
      snapshot = value;
      notify();
    },
  };
}

async function booted(options = {}) {
  const h = harness(options);
  await h.controller.init();
  h.events.length = 0;
  return h;
}

/** 이벤트 루프를 한 바퀴 — `openPreviewFrom` 은 void 라 완료를 기다릴 손잡이가 없다. */
const settle = () => new Promise((resolve) => setImmediate(resolve));

/** 면이 **실제로 서 있는** 상태. `booted` 는 init 까지만 한다 — 실물의 `Modal.close` 는
 *  스택에 없는 면에서 아무 일도 하지 않으므로, 안 열고 닫으면 「닫혔다」가 아니라 「아무 일도
 *  없었다」를 재게 된다. 닫힘·복귀 좌표를 재는 자리는 전부 이걸 쓴다. */
async function standing(options = {}) {
  const h = await booted(options);
  h.controller.openPreviewFrom(null);
  await settle();
  assert.equal(h.only("modal.open").length, 1, "면이 서지 않으면 이후 단언이 공허하다");
  h.events.length = 0;
  return h;
}

/* ================= ① 열기 순서 ================= */

test("확인 면 열기는 flush → preview_open → modal.open 순서다", async () => {
  const h = await booted();
  h.controller.openPreviewFrom(null);
  await settle();

  assert.deepEqual(h.order(), ["flush", "dispatch:preview_open", "modal.open"],
    "커밋이 대기 변이보다 먼저 서면 방금 고친 값이 아닌 옛 값을 보여 준다");
});

test("열기는 요청한 행 번호를 그대로 싣는다 — 표면이 다시 계산하지 않는다", async () => {
  const h = await booted();
  h.controller.openPreviewFrom(null);
  await settle();
  const [open] = h.dispatched();
  assert.equal(open.action, "preview_open");
  assert.deepEqual(open.payload, { at: 0 });
});

test("열기 왕복이 실패하면 면을 열지 않고 사유를 남긴다", async () => {
  const h = await booted({ dispatch: { preview_open: new Error("브리지 끊김") } });
  h.controller.openPreviewFrom(null);
  await settle();

  assert.deepEqual(h.only("modal.open"), [], "실패했는데 빈 면을 띄우지 않는다");
  assert.ok(h.log().some((line) => line.includes("브리지 끊김")), "조용히 삼키지 않는다");
});

/* ================= ② 왕복 중 이탈 ================= */

test("왕복 중 화면을 떠났으면 열지 않고 preview_close 로 상태를 되돌린다", async () => {
  const h = await booted({ currentScreen: "library" });
  h.controller.openPreviewFrom(null);
  await settle();

  assert.deepEqual(h.only("modal.open"), [], "떠난 화면에 면을 띄우지 않는다");
  assert.deepEqual(h.dispatched().map((e) => e.action), ["preview_open", "preview_close"],
    "남는 「열림」이 다음 복귀에서 아무 트리거 없이 면을 띄운다");
});

test("화면을 아직 못 정했어도(null) 같은 갈래로 간다 — 부재를 「열려 있음」으로 읽지 않는다", async () => {
  const h = await booted({ currentScreen: null });
  h.controller.openPreviewFrom(null);
  await settle();
  assert.deepEqual(h.only("modal.open"), []);
  assert.deepEqual(h.dispatched().map((e) => e.action), ["preview_open", "preview_close"]);
});

/* ================= ③ 「수정」의 순서 계약 ================= */

test("행 수정의 복귀 좌표는 modal.close **전에** 읽은 pos 다", async () => {
  const h = await standing({
    elements: { previewPos: textNode("3 / 10") },
  });
  await h.controller.previewFixField("공고명");

  const closed = h.order().indexOf("modal.close");
  const guarded = h.order().indexOf("openGuarded");
  assert.ok(closed >= 0 && guarded > closed, "닫고 나서 편집기로 간다");

  const [entry] = h.only("openGuarded");
  assert.equal(entry.context.return_context.preview_index, 2,
    "닫힘이 pos 를 0 으로 리셋하므로, 순서를 바꾸면 복귀가 늘 첫 행으로 선다");
  assert.equal(entry.context.return_context.reopen_drawer, true);
  assert.equal(entry.context.target, "binding/공고명");
});

test("행 수정은 본 값을 증거로 싣는다 — 편집기가 무엇을 보고 왔는지 안다", async () => {
  const h = await booted({
    elements: { previewPos: textNode("3 / 10") },
  });
  await h.controller.previewFixField("공고명");
  const [entry] = h.only("openGuarded");
  assert.equal(entry.context.evidence["필드"], "공고명");
  assert.equal(entry.context.evidence["본 값"], "가나다");
  assert.equal(entry.context.evidence["보고 있던 행"], "3 / 10");
});

test("빈 값 행의 증거는 빈칸으로 새지 않고 표식으로 남는다", async () => {
  const h = await booted({
    snapshot: snap({ preview: { pos: 0, rows: [{ name: "공고명", value: "" }] } }),
  });
  await h.controller.previewFixField("공고명");
  assert.equal(h.only("openGuarded")[0].context.evidence["본 값"], "(빈 값)");
});

test("파일 이름 수정도 같은 단일 경로를 지난다", async () => {
  const h = await booted({
    elements: {
      previewPos: textNode("1 / 10"),
      previewFilename: textNode("공고서_가나다.hwpx"),
    },
  });
  await h.controller.previewFixFilename();
  const [entry] = h.only("openGuarded");
  assert.equal(entry.context.target, "filename/filenamePattern");
  assert.equal(entry.context.evidence["파일 이름"], "공고서_가나다.hwpx");
});

test("진입이 성사돼야 겨눔이 나간다", async () => {
  const h = await booted();
  await h.controller.previewFixField("공고명");
  assert.deepEqual(h.only("aimAt").map((e) => e.target), ["binding/공고명"]);
});

test("진입이 거절되면 겨눔은 나가지 않는다", async () => {
  const h = await booted({ openGuardedResult: false });
  await h.controller.previewFixField("공고명");
  assert.deepEqual(h.only("aimAt"), [], "안 열린 편집기를 겨누면 다음 진입이 엉뚱한 곳에 선다");
});

test("작업이 없으면 편집 진입 자체가 성립하지 않는다", async () => {
  const h = await booted({ snapshot: { has_job: false } });
  await h.controller.previewFixField("공고명");
  assert.deepEqual(h.only("openGuarded"), []);
  assert.deepEqual(h.only("aimAt"), []);
});

/* ================= 나머지 발신 ================= */

test("행 이동·빈 값 필터·승인은 판정을 안 하고 그대로 보낸다", async () => {
  const h = await booted();
  h.controller.previewMove(-1);
  h.controller.previewBlankOnly(true);
  h.controller.previewApprove();
  await settle();

  assert.deepEqual(h.dispatched(), [
    { kind: "dispatch", action: "preview_move", payload: { delta: -1 } },
    { kind: "dispatch", action: "preview_blank_only", payload: { value: true } },
    { kind: "dispatch", action: "preview_approve", payload: {} },
  ]);
});

test("승인·필터 실패는 조용히 사라지지 않는다", async () => {
  const h = await booted({
    dispatch: { preview_approve: new Error("저장 실패"), preview_blank_only: new Error("필터 실패") },
  });
  h.controller.previewApprove();
  h.controller.previewBlankOnly(true);
  await settle();

  const log = h.log().join("\n");
  assert.match(log, /저장 실패/);
  assert.match(log, /필터 실패/);
});

test("닫기는 같은 면 id 하나만 겨눈다", async () => {
  const h = await standing();
  h.controller.closePreview();
  assert.deepEqual(h.only("modal.close").map((e) => e.id), ["previewSheet"]);
});

/* ================= ⑥ 원격 닫힘 — 개폐 주인은 Python ================= */

test("Python 이 닫았다고 말하면 면도 닫힌다", async () => {
  const h = await standing();
  h.push(snap({ preview: { ...snap().preview, open: false } }));
  /* legacy `closePreviewIfOpen` 동등. 안 닫으면 그 면은 **남의 값**을 그린 채 남는다 —
     작업 전환·데이터 교체를 백엔드가 닫는 원격 닫힘이 정확히 이 경로다. */
  assert.deepEqual(h.only("modal.close").map((e) => e.id), ["previewSheet"]);
});

test("Python 이 열려 있다고 말하는 동안은 닫지 않는다", async () => {
  const h = await standing();
  h.push(snap({ preview: { ...snap().preview, open: true }, selection_key: "s9" }));
  /* 음성 극 — 매 푸시마다 닫으면 위 단언은 **무엇을 해도 초록**이다(닫힘 계약이 아니라
     「닫기를 부르는가」만 재게 된다). 두 값을 함께 세워야 개폐가 상태에 결속된다. */
  assert.deepEqual(h.only("modal.close"), []);
});
