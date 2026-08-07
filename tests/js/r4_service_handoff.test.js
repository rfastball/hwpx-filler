import test from "node:test";
import assert from "node:assert/strict";

import { createPort } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";

test("React port는 미결속 호출과 중복 결속을 시끄럽게 거절한다", () => {
  const port = createPort("probe");
  assert.throws(() => port.current(), /결속되지/);
  const react = { run: () => "react" };
  port.bind(react);
  assert.equal(port.current(), react);
  assert.throws(() => port.bind(react), /정확히 한 번/);
  assert.deepEqual(Object.keys(port).sort(), ["bind", "current"]);
});

test("service port는 SheetPicker와 Relink를 서로 독립적으로 결속한다", () => {
  const services = createServiceHandoffPorts();
  const picker = { choose: async () => null };
  const relink = { relinkTemplate: async () => true };
  services.sheetPicker.bind(picker);
  services.relink.bind(relink);
  assert.equal(services.sheetPicker.current(), picker);
  assert.equal(services.relink.current(), relink);
});
