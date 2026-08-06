import test from "node:test";
import assert from "node:assert/strict";

import { createScreenRuntime } from "../../frontend/src/screens/runtime.ts";
import { createSnapshotStore } from "../../frontend/src/state/store.ts";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((ok, no) => { resolve = ok; reject = no; });
  return { promise, resolve, reject };
}

test("job model은 full을 보존한 채 progress delta만 갱신한다", () => {
  const store = createSnapshotStore({ alarm: assert.fail });
  const runtime = createScreenRuntime({ client: { initial: assert.fail }, store });
  const model = runtime.model("job");
  const full = { has_job: true, has_data: true };
  store.ingest("job", full);
  assert.deepEqual(model.getSnapshot(), { full, progress: null });
  store.ingest("job", { progress: { done: 2, total: 5 } });
  assert.deepEqual(model.getSnapshot(), { full, progress: { done: 2, total: 5 } });
  const next = { has_job: false, has_data: true };
  store.ingest("job", next);
  assert.deepEqual(model.getSnapshot(), { full: next, progress: null });
  runtime.dispose();
  assert.equal(store.listenerCount("job"), 0);
});

test("initial보다 늦게 시작해 먼저 도착한 push를 낡은 pull이 덮지 않는다", async () => {
  const gate = deferred();
  const store = createSnapshotStore({ alarm: assert.fail });
  const runtime = createScreenRuntime({
    client: { initial: () => gate.promise },
    store,
  });
  const loading = runtime.loadInitial("job");
  const pushed = { has_job: true, has_data: true, tag: "push" };
  store.ingest("job", pushed);
  gate.resolve({ ok: true, value: { has_job: false, has_data: false, tag: "pull" } });
  await loading;
  assert.equal(runtime.model("job").getSnapshot().full, pushed);
});

test("동시 initial은 하나를 공유하고 실패 뒤 다음 명시 호출은 재시도한다", async () => {
  let calls = 0;
  const store = createSnapshotStore({ alarm: assert.fail });
  const runtime = createScreenRuntime({
    client: {
      initial: async () => {
        calls += 1;
        if (calls === 1) throw new Error("첫 당김 실패");
        return { ok: true, value: { rows: [] } };
      },
    },
    store,
  });
  const first = runtime.loadInitial("library");
  assert.equal(runtime.loadInitial("library"), first);
  await assert.rejects(first, /첫 당김 실패/);
  await runtime.loadInitial("library");
  assert.equal(calls, 2);
});
