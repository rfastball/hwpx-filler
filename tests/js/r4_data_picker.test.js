import test from "node:test";
import assert from "node:assert/strict";

import { createDataPickerController } from "../../frontend/src/screens/data_picker.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";

function build(overrides = {}) {
  const services = createServiceHandoffPorts();
  const chosen = [];
  services.sheetPicker.bind({
    async choose(screen, request) {
      chosen.push([screen, request]);
      return { label: "목록.xlsx / Sheet2", rows: 3, path: "C:/목록.xlsx", sheet: "Sheet2" };
    },
  });
  const modal = [];
  const loaded = [];
  const controller = createDataPickerController({
    doc: { getElementById: () => null },
    runtime: {
      model: () => ({ getSnapshot: () => ({ rows: [] }), subscribe: () => () => {} }),
      loadInitial: async () => ({}),
    },
    client: {
      dispatch: overrides.dispatch || (async () => ({ ok: true, value: { ok: true } })),
      invoke: async (method) => method === "pick_data_file"
        ? { ok: true, value: { needs_sheet: true, sheets: ["Sheet1", "Sheet2"] } }
        : { ok: true, value: null },
    },
    services,
    modal: {
      confirm: async () => true,
      open: (id, spec) => modal.push(["open", id, spec]),
      close: (id) => modal.push(["close", id]),
    },
    notify: assert.fail,
  });
  return { controller, chosen, modal, loaded };
}

test("다중 시트 선택 뒤 session은 close에서 정확히 한 번 settle된다", async () => {
  const { controller, chosen, modal } = build();
  const loaded = [];
  const result = controller.open({ screen: "job", onLoaded: (label) => loaded.push(label) });
  await controller.browseFile();
  assert.equal(chosen.length, 1);
  assert.deepEqual(loaded, ["목록.xlsx / Sheet2"]);
  controller.close();
  assert.equal(await result, "목록.xlsx / Sheet2");
  controller.close();
  assert.equal(modal.filter((row) => row[0] === "close" && row[1] === "dataPickerModal").length, 1);
});

test("열린 picker 위의 둘째 open은 조용히 겹치지 않는다", async () => {
  const { controller } = build();
  const first = controller.open({ screen: "job" });
  await assert.rejects(controller.open({ screen: "job" }), /이미 열려/);
  controller.close();
  await first;
});

test("Escape·scrim 닫힘은 session을 정산하고 loading 중에는 beforeClose가 소비한다", async () => {
  let finishLoad;
  const { controller, modal } = build({
    dispatch: async (_screen, action) => action === "load_pool"
      ? new Promise((resolve) => { finishLoad = resolve; })
      : { ok: true, value: { ok: true } },
  });
  const settled = controller.open({ screen: "job" });
  const spec = modal.find((row) => row[0] === "open" && row[1] === "dataPickerModal")[2];
  assert.equal(spec.beforeClose(), true);

  const pending = controller.poolAction("use", { key: "slot", name: "자료" });
  await Promise.resolve();
  assert.equal(spec.beforeClose(), false);
  assert.match(controller.model.getSnapshot().status, /닫을 수 없습니다/);

  finishLoad({ ok: true, value: { ok: false, error: "읽기 실패" } });
  await pending;
  spec.onClose();
  assert.equal(await settled, null);
});
