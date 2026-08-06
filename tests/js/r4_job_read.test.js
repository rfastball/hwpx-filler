import test from "node:test";
import assert from "node:assert/strict";

import { createJobReadController, createJobRunAdapter } from "../../frontend/src/screens/job_read.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";

function makeController(options = {}) {
  const snapshot = { has_job: true, has_data: true, job_name: "작업A", filter: { search: "" }, zone_epoch: 7 };
  const calls = [];
  const entries = [];
  const ports = createScreenPorts();
  ports.jobRunCoordination.bindLegacy({ confirmDestructiveIfArmed: async () => true, log() {} });
  ports.editorEntry.bindLegacy({
    openGuarded() {}, newDraft() {}, newDraftFromData(context) { entries.push(context); }, land() {},
    confirmDiscard() {}, restoreEntryFocus() {},
  });
  const services = createServiceHandoffPorts();
  services.relink.bindLegacy({ relinkTemplate: async () => true });
  const timers = new Map();
  let timerId = 0;
  const doc = {
    activeElement: null,
    getElementById: options.getElementById || (() => null),
    defaultView: {
      setTimeout(fn) { timerId += 1; timers.set(timerId, fn); return timerId; },
      clearTimeout(id) { timers.delete(id); },
    },
  };
  let modalSpec = null;
  let pendingClose = null;
  const modal = {
    confirm: async () => true,
    open(_id, spec) { modalSpec = spec; },
    close() { pendingClose = modalSpec; modalSpec = null; },
  };
  const controller = createJobReadController({
    runtime: { model: () => ({ getSnapshot: () => ({ full: snapshot, progress: null }), subscribe: () => () => {} }) },
    client: { dispatch: async (screen, action, payload) => {
      calls.push([screen, action, payload]);
      if (options.dispatch) return options.dispatch(screen, action, payload);
      return { ok: true, value: {} };
    } },
    ports, services,
    modal,
    surfaceSheet: { open() {}, close() {} }, dataPicker: { open: async () => null },
    navigation: { go() {} }, doc, notify: assert.fail,
  });
  return {
    controller, ports, calls, entries,
    getModalSpec: () => modalSpec,
    finishModalClose: () => { const spec = pendingClose; pendingClose = null; spec?.onClose?.(); },
  };
}

test("즐겨찾기 연타는 클릭별 intent를 직렬화하고 같은 값의 옛 완료가 최신 intent를 지우지 않는다", async () => {
  const pending = [];
  const { controller, calls } = makeController({
    dispatch: () => new Promise((resolve) => { pending.push(resolve); }),
  });
  const settle = () => new Promise((resolve) => setImmediate(resolve));

  const toggles = [
    controller.toggleFavorite("작업A", false),
    controller.toggleFavorite("작업A", false),
    controller.toggleFavorite("작업A", false),
  ];
  await settle();
  assert.deepEqual(calls.map((row) => row[2].value), [true]);

  pending.shift()({ ok: true, value: {} });
  await settle();
  toggles.push(controller.toggleFavorite("작업A", false));

  while (pending.length > 0 || calls.length < 4) {
    if (pending.length > 0) pending.shift()({ ok: true, value: {} });
    await settle();
  }
  await Promise.all(toggles);
  assert.deepEqual(calls.map((row) => row[2].value), [true, false, true, false]);
});

test("탐색 행 선택은 모달의 원 복귀 뒤 새 활성 후보 카드에 최종 착지한다", async () => {
  let focused = 0;
  const target = { focus() { focused += 1; } };
  const { controller, finishModalClose } = makeController({
    getElementById: (id) => id === `jobCand-${encodeURIComponent("작업B")}` ? target : null,
  });

  await controller.openBrowse();
  await controller.pickBrowse("작업B");
  assert.equal(focused, 0, "닫힘 전이 중에는 후보 카드로 먼저 뛰지 않는다");
  finishModalClose();
  assert.equal(focused, 1);
});

test("작업 전환 전에 예약 검색을 같은 zone 체인으로 정산한다", async () => {
  const { controller, ports, calls } = makeController();
  controller.scheduleSearch("새 검색");
  await controller.selectJob("작업B");
  assert.deepEqual(calls.map((row) => row[1]), ["filter_search", "select_job"]);
  assert.deepEqual(calls[0][2], { text: "새 검색", epoch: 7 });
  assert.equal(ports.jobRead.owner(), "react");
  assert.equal(ports.jobData.owner(), "react");
  assert.equal(ports.jobRelinkFlow.owner(), "react");
});

test("job run adapter는 full/progress를 순서 보존 fan-out하고 preview 전에 flush한다", async () => {
  let value = { full: { id: 1 }, progress: null };
  const listeners = new Set();
  const events = [];
  const adapter = createJobRunAdapter({
    model: { getSnapshot: () => value, subscribe: (fn) => { listeners.add(fn); return () => listeners.delete(fn); } },
    beforePreview: async () => { events.push("flush"); },
    openPreview: async (request) => { events.push(["preview", request]); },
  });
  const release = adapter.attach({ onFull: (full) => events.push(["full", full]), onProgress: (p) => events.push(["progress", p]) });
  value = { full: value.full, progress: { done: 1 } };
  for (const listener of listeners) listener();
  await adapter.openPreview({ at: 2, focusTarget: "binding/이름" });
  assert.deepEqual(events, [
    ["full", { id: 1 }], ["progress", { done: 1 }], "flush",
    ["preview", { at: 2, focusTarget: "binding/이름" }],
  ]);
  release();
  assert.equal(listeners.size, 0);
  assert.throws(() => release(), /정확히 한 번/);
});

test("확인 필요 새 작업은 탐색 시트 onClose가 끝난 뒤에만 시작한다", async () => {
  const { controller, entries, getModalSpec, finishModalClose } = makeController();
  await controller.openBrowse();
  controller.newWorkAfterBrowseClose({ "확인 필요였던 작업": "작업B" });
  assert.equal(entries.length, 0);
  assert.equal(getModalSpec(), null);
  finishModalClose();
  assert.equal(entries.length, 1, "이미 소비한 닫힘 슬롯은 다음 흐름을 재실행하면 안 됩니다.");
  finishModalClose();
  assert.equal(entries.length, 1);
});

test("zone epoch는 생성 계약이 허용한 변이에만 붙고 범위 초안 명시 사건은 빈 payload다", async () => {
  const { controller, calls } = makeController();
  await controller.openDataSheet(null);
  await controller.applyRange();

  assert.deepEqual(calls.map((row) => [row[1], row[2]]), [
    ["range_draft_open", {}],
    ["range_draft_apply", {}],
  ]);
});
