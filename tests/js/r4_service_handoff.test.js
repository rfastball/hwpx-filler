import test from "node:test";
import assert from "node:assert/strict";

import { createHandoffPort } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";

test("handoff port는 미결속 호출과 중복 결속을 시끄럽게 거절한다", () => {
  const port = createHandoffPort("probe");
  assert.throws(() => port.current(), /결속되지/);
  const legacy = { run: () => "legacy" };
  port.bindLegacy(legacy);
  assert.equal(port.current(), legacy);
  assert.throws(() => port.bindLegacy(legacy), /정확히 한 번/);
  const react = { run: () => "react" };
  port.handoff("legacy", "react", react);
  assert.equal(port.owner(), "react");
  assert.equal(port.current(), react);
  assert.throws(() => port.handoff("legacy", "react", react), /상태가 어긋/);
});

test("service handoff는 SheetPicker와 Relink를 서로 독립적으로 결속한다", () => {
  const services = createServiceHandoffPorts();
  const picker = { choose: async () => null };
  const relink = { relinkTemplate: async () => true };
  services.sheetPicker.bindLegacy(picker);
  services.relink.bindReact(relink);
  assert.equal(services.sheetPicker.current(), picker);
  assert.equal(services.relink.current(), relink);
  assert.equal(services.sheetPicker.owner(), "legacy");
  assert.equal(services.relink.owner(), "react");
});
