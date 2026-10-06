/* Test delta brief
 * Unique risk: a failed follow of a Python-activated document suppresses every later activation of that document.
 * Existing owner: none at unit level (live authoring probes cover the healthy follow path only).
 * Selected layer: Node — authoringHost over a fake view and client; no renderer, no bridge.
 * Expected cost delta: one small Node case, zero resource launches.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { authoringHost } from "../../frontend/src/screens/authoring_host.ts";

function fakeView() {
  const state = { active: "", view: "", listeners: [], activations: [], failures: [], failNext: new Set() };
  const view = {
    activeId: () => state.active,
    viewId: () => state.view,
    async activate(id) {
      state.activations.push(id);
      if (state.failNext.has(id)) { state.failNext.delete(id); throw new Error(`activate ${id}`); }
      state.view = id;
    },
    fail: (error) => { state.failures.push(String(error?.message ?? error)); },
    subscribe: (listener) => { state.listeners.push(listener); },
  };
  const push = async (active) => {
    state.active = active;
    state.listeners.forEach((listener) => listener());
    await new Promise((resolve) => setTimeout(resolve, 0));
  };
  return { state, view, push };
}

test("a failed follow is not retried while that document stays active, and clears once another is active (#1149 review)", async () => {
  const { state, view, push } = fakeView();
  authoringHost({ dispatch: async () => ({ ok: true, value: {} }), invoke: async () => ({ ok: true, value: null }) }, view);

  state.failNext.add("X");
  await push("X");
  assert.deepEqual(state.activations, ["X"]);
  assert.deepEqual(state.failures, ["activate X"]);

  await push("X");  // another push while X is still the (unfollowed) active document: no error loop
  assert.deepEqual(state.activations, ["X"]);

  await push("Y");
  assert.equal(state.view, "Y");
  await push("X");  // Python activates X again later (e.g. the practice-exit restore): a new activation
  assert.deepEqual(state.activations, ["X", "Y", "X"]);
  assert.equal(state.view, "X", "the view follows the document Python activated again");
});
