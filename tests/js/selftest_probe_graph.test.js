/* 커밋된 프로브 그래프 스냅샷이 레지스트리와 어긋나지 않는지 — 어긋나면 재생성 명령을 말한다. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join, dirname } from "node:path";

import { buildProbeGraph } from "../../scripts/selftest_probe_graph.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const SNAPSHOT_PATH = join(HERE, "..", "contracts", "selftest-probe-graph.json");

test("커밋된 스냅샷이 buildProbeGraph() 와 깊게 같다", () => {
  const graph = buildProbeGraph();
  let snapshot;
  try {
    snapshot = JSON.parse(readFileSync(SNAPSHOT_PATH, "utf8"));
  } catch (thrown) {
    assert.fail(
      `${SNAPSHOT_PATH} 를 읽지 못했습니다 — `
      + `node scripts/selftest_probe_graph.mjs --write 를 실행하십시오: ${thrown.message}`,
    );
  }
  assert.deepEqual(
    snapshot, graph,
    "스냅샷이 레지스트리와 어긋납니다 — "
    + "node scripts/selftest_probe_graph.mjs --write 를 실행해 다시 쓴 뒤 커밋하십시오.",
  );
});

test("모든 after 이름은 실재하는 프로브다", () => {
  const graph = buildProbeGraph();
  const names = new Set(graph.probes.map((p) => p.name));
  for (const probe of graph.probes) {
    for (const dep of probe.after) {
      assert.ok(names.has(dep), `${probe.name} 의 after 가 가리키는 ${dep} 가 없습니다.`);
    }
  }
});
