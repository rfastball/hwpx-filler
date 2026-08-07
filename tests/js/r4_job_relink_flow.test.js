import test from "node:test";
import assert from "node:assert/strict";

import { createJobReadController } from "../../frontend/src/screens/job_read.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";

test("비활성 작업 relink 성공 뒤에만 그 작업을 선택한다", async () => {
  const calls = [];
  const ports = createScreenPorts();
  ports.jobRunCoordination.bind({ confirmDestructiveIfArmed: async () => true, log: (m) => calls.push(["log", m]) });
  ports.editorEntry.bind({ openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {}, confirmDiscard() {}, restoreEntryFocus() {} });
  const services = createServiceHandoffPorts();
  services.relink.bind({ relinkTemplate: async (_screen, name) => { calls.push(["relink", name]); return true; } });
  const controller = createJobReadController({
    runtime: { model: () => ({ getSnapshot: () => ({ full: { has_job: true, has_data: true, job_name: "작업A", filter: {} }, progress: null }), subscribe: () => () => {} }) },
    client: { dispatch: async (_screen, action, payload) => { calls.push([action, payload]); return { ok: true, value: {} }; } },
    ports, services,
    modal: { confirm: async () => true, open() {}, close() {} }, surfaceSheet: { open() {}, close() {} },
    dataPicker: { open: async () => null }, navigation: { go() {} },
    doc: { getElementById: () => null, defaultView: { setTimeout: () => 1, clearTimeout() {} } }, notify: assert.fail,
  });
  await controller.relinkTemplateFor("작업B");
  assert.deepEqual(calls, [["relink", "작업B"], ["select_job", { name: "작업B" }]]);
});

test("활성 작업 relink는 파괴 가드 거절 시 service를 부르지 않는다", async () => {
  const calls = [];
  const ports = createScreenPorts();
  ports.jobRunCoordination.bind({ confirmDestructiveIfArmed: async () => false, log() {} });
  ports.editorEntry.bind({ openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {}, confirmDiscard() {}, restoreEntryFocus() {} });
  const services = createServiceHandoffPorts();
  services.relink.bind({ relinkTemplate: async () => { calls.push("relink"); return true; } });
  const controller = createJobReadController({
    runtime: { model: () => ({ getSnapshot: () => ({ full: { has_job: true, has_data: true, job_name: "작업A", filter: {} }, progress: null }), subscribe: () => () => {} }) },
    client: { dispatch: async () => ({ ok: true, value: {} }) }, ports, services,
    modal: { confirm: async () => true, open() {}, close() {} }, surfaceSheet: { open() {}, close() {} },
    dataPicker: { open: async () => null }, navigation: { go() {} },
    doc: { getElementById: () => null, defaultView: { setTimeout: () => 1, clearTimeout() {} } }, notify: assert.fail,
  });
  await controller.relinkTemplateFor("작업A");
  assert.deepEqual(calls, []);
});
