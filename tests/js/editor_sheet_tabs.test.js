/* 편집기 「연결 확인」 시트 탭 — 스냅샷 투영(`data_sheet_tabs`)만 그리고, 고른 시트를
   데이터 교체와 같은 문(`usePoolData` → `editor/use_pool_data {key, sheet}`)으로 보낸다. */
import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { BindingSheetTabs, createEditorController } from "../../frontend/src/screens/editor.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";
import { createScreenRuntime } from "../../frontend/src/screens/runtime.ts";
import { createSnapshotStore } from "../../frontend/src/state/store.ts";
import { Intent } from "../../frontend/js/intent.js";

const TABS = [
  { key: "book", sheet: "공고목록", active: true, selectable: true, reason: "" },
  { key: "book", sheet: "낙찰현황", active: false, selectable: true, reason: "" },
  { key: "book", sheet: "보관시트", active: false, selectable: false, reason: "보관됨" },
];

const render = (snapshot, controller) => renderToStaticMarkup(
  createElement(BindingSheetTabs, { snapshot, controller }));

test("시트 탭은 투영된 행·활성·사유만 렌더하고 행이 없으면 서지 않는다", () => {
  const markup = render({ data_sheet_tabs: TABS }, { guarded() {}, usePoolData() {} });
  assert.match(markup, /class="data-tabs" role="group" aria-label="사용할 시트"/);
  assert.match(markup, /aria-pressed="true"[^>]*>공고목록/);
  assert.match(markup, /aria-pressed="false"[^>]*>낙찰현황/);
  assert.match(markup, /disabled="" title="보관됨"[^>]*>보관시트/);
  assert.equal(render({ data_sheet_tabs: [] }, {}), "");
  assert.equal(render({}, {}), "", "선언된 시트가 없으면 띠를 세우지 않는다");
});

function editorHarness() {
  const trace = [];
  const client = {
    whenReady: () => Promise.resolve(),
    async initial() { return { ok: true, value: { section: "binding", data_sheet_tabs: TABS } }; },
    async dispatch(screen, action, payload) {
      trace.push([screen, action, payload]);
      return { ok: true, value: action === "use_pool_data" ? { ok: true, label: "월별" } : {} };
    },
    async invoke() { return { ok: true, value: null }; },
  };
  const store = createSnapshotStore({ alarm: assert.fail });
  const runtime = createScreenRuntime({ client, store });
  const controller = createEditorController({
    doc: { getElementById: () => null, querySelector: () => null },
    runtime, client, ports: createScreenPorts(), services: createServiceHandoffPorts(),
    modal: { confirm: async () => false, prompt: async () => null, open() {}, close() {} },
    popover: { wireDismiss: () => () => {} },
    chain: Intent,
    navigation: { go() {}, refresh: async () => {} },
    poolRegistration: { openRegDialog() {}, openPclm() {}, openDetail: async () => {} },
    notify: (message) => assert.fail(String(message)),
  });
  return { controller, trace };
}

test("고른 시트는 확인 질의 뒤 use_pool_data 에 시트를 실어 보내고 지금 시트는 무동작이다", async () => {
  const { controller, trace } = editorHarness();
  await controller.init();
  const strip = BindingSheetTabs({ snapshot: controller.model.getSnapshot(), controller });
  strip.props.onPick(TABS[0]);
  strip.props.onPick(TABS[1]);
  for (let turn = 0; turn < 5; turn += 1) await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(trace.filter((row) => row[0] === "editor"), [
    ["editor", "mapping_reset_stakes", {}],
    ["editor", "use_pool_data", { key: "book", sheet: "낙찰현황" }],
  ]);
  /* 우 열의 등록 행 고르기는 종전 그대로 키 하나만 싣는다(기본 시트). */
  assert.equal(await controller.usePoolData("book"), true);
  assert.deepEqual(trace.at(-1), ["editor", "use_pool_data", { key: "book" }]);
});
