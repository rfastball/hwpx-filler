/* Test delta brief
 * Unique risk (#1146): Python makes a document active on its own (the tutorial opens its practice TXT, a workspace switch,
 * the return after practice) while this screen never called activate(); the editor then shows that tab but the
 * controller has no view of it and drops every selection report — a range beat never passes.
 * Existing owner: tests/js/authoring.test.js owns the controller's revision fences and selection rules with activate()
 * always called first; this file owns only following the snapshot's active document.
 * Selected layer: Node, the authoring controller with a stub client and a pushable model; no resource launches.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createAuthoringController } from "../../frontend/src/screens/authoring_controller.ts";

function harness(invoked = () => null) {
  const snapshot = { active_id: "", tabs: ["a", "b"].map((id) => ({ id, name: `${id}.txt`, path: `${id}.txt`, revision: 0, values: {}, selected: {} })) };
  const calls = [];
  const listeners = new Set();
  const client = {
    async dispatch(_screen, action, payload) {
      calls.push({ action, ...payload });
      if (action === "activate" && payload.session_id === "gone") return { ok: true, value: { ok: false, message: "닫힌 문서" } };
      if (action === "activate") snapshot.active_id = payload.session_id;
      return { ok: true, value: {} };
    },
    async invoke(method, ...args) { calls.push({ method, args }); return { ok: true, value: await invoked(method, snapshot) }; },
  };
  /** Python's observation push: the snapshot changes, then every subscriber hears it. */
  const push = (patch) => { Object.assign(snapshot, patch); listeners.forEach((listener) => listener()); };
  const controller = createAuthoringController({ client,
    runtime: { model: () => ({ getSnapshot: () => snapshot, subscribe: (listener) => { listeners.add(listener); return () => listeners.delete(listener); } }), loadInitial: async () => {} },
    modal: { choose: async () => "save", prompt: async () => null, confirm: async () => true },
    navigation: { go() {}, refresh: async () => {} },
  });
  const activations = () => calls.filter((call) => call.action === "activate").map((call) => call.session_id);
  return { controller, calls, push, activations };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 5));

test("a document Python made active on its own becomes this screen's view, so the editor's selection is located", async () => {
  const { controller, calls, push, activations } = harness();
  push({ active_id: "b" });
  await settle();
  assert.deepEqual(activations(), ["b"]);
  controller.selection("b", { start: 1, end: 3 });
  await settle();
  assert.deepEqual(calls.filter((call) => call.action === "locate").map((call) => [call.session_id, call.selection]),
    [["b", { start: 1, end: 3 }]], "before #1146 this report was dropped: no locate, no range beat");
  push({});
  await settle();
  assert.deepEqual(activations(), ["b"], "an already followed document is not activated again");
});

test("a push answering this screen's own request is left to that request's action, not followed a second time", async () => {
  let pushNow = () => {};
  const { controller, push, activations } = harness((method, snapshot) => {
    if (method !== "open_authoring_document") return null;
    snapshot.tabs.push({ id: "c", name: "c.txt", path: "c.txt", revision: 0, values: {}, selected: {} });
    pushNow();  // arrives before the open request returns
    return { session_id: "c", revision: 0 };
  });
  pushNow = () => push({ active_id: "c" });
  await controller.open("c.txt");
  await settle();
  assert.deepEqual(activations(), ["c"]);
});

test("a document that cannot be followed is not retried after every request", async () => {
  const { controller, push, activations } = harness();
  push({ active_id: "gone" });
  await settle();
  assert.deepEqual(activations(), ["gone"]);
  assert.equal(controller.viewModel.getSnapshot().errorKind, "editor", "the failure is shown once");
  await controller.content("a");
  await settle();
  assert.deepEqual(activations(), ["gone"], "a finished request does not start the same failing follow again");
});
