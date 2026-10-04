/* 프로브 그래프 정적 스냅샷 — 파이썬 도구가 JS 레지스트리를 다시 구현하지 않고 읽는 자리.
 *
 * `frontend/src/selftest/probes/index.js` 의 `registerAllProbes` 가 다섯 묶음을 모으고
 * 묶음 간 `after` 간선(`CROSS_CLUSTER_EDGES`)을 얹는다. 그 병합 로직을 여기서 다시
 * 짜면 두 구현이 반드시 갈라진다 — 그래서 **같은 함수**를 부른다. 러너 대신 `registerAll`
 * 만 흉내 내는 손수 만든 스텁(`{ registerAll(defs) { ... } }`)을 넘겨 정의 배열을
 * 그대로 받는다.
 *
 * 출력은 등록 순서(= `CLUSTER_ORDER` 를 따라간 다섯 묶음의 이어붙임, 묶음 간 간선이 끝에
 * 병합된 뒤의 `after`)를 그대로 담는다. 커밋된 스냅샷(`tests/contracts/
 * selftest-probe-graph.json`)과 이 파일의 `buildProbeGraph()` 가 어긋나면 `--check` 가
 * 조용히 넘기지 않고 실패한다 — 어긋남은 "스냅샷을 깜빡했다"는 뜻이고 그 사유를 기계가
 * 말해야 한다.
 *
 *   node scripts/selftest_probe_graph.mjs --write   # 스냅샷 갱신
 *   node scripts/selftest_probe_graph.mjs --check   # 스냅샷이 최신인지 확인(CI)
 */
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { CLUSTER_ORDER, registerAllProbes } from "../frontend/src/selftest/probes/index.js";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(SCRIPT_DIR, "..");
const SNAPSHOT_PATH = join(REPO_ROOT, "tests", "contracts", "selftest-probe-graph.json");

/** `registerAllProbes` 가 실제로 넘기는 정의 배열을 그대로 받는 스텁 — 등록 계약 검증
 *  (`normalizeDefinition`)을 다시 흉내 내지 않는다. 이 스크립트는 그래프를 **보는** 것이고
 *  등록 자체의 옳음은 러너·단위 테스트의 몫이다. */
function captureDefs() {
  let captured = null;
  registerAllProbes({ registerAll(defs) { captured = defs; return defs; } });
  if (captured === null) {
    throw new Error("registerAllProbes 가 registerAll 을 부르지 않았습니다 — 배선이 바뀌었습니다.");
  }
  return captured;
}

/** 등록 순서대로 다섯 묶음의 프로브를 평평한 그래프로. `after` 는 묶음 간 간선이 이미
 *  병합된 뒤의 값을 그대로 옮긴다(복사본 — 원본 freeze 배열을 공유하지 않는다). */
export function buildProbeGraph() {
  const defs = captureDefs();
  return {
    version: 1,
    clusters: [...CLUSTER_ORDER],
    probes: defs.map((def) => ({
      name: def.name,
      cluster: def.cluster,
      keys: [...def.keys],
      modes: [...def.modes],
      after: [...(def.after || [])],
    })),
  };
}

function serialize(graph) {
  return `${JSON.stringify(graph, null, 2)}\n`;
}

function readSnapshot() {
  try {
    return readFileSync(SNAPSHOT_PATH, "utf8");
  } catch (thrown) {
    if (thrown && thrown.code === "ENOENT") return null;
    throw thrown;
  }
}

function main(argv) {
  const mode = argv[0];
  if (mode !== "--write" && mode !== "--check") {
    throw new Error("인자는 --write 또는 --check 여야 합니다.");
  }

  const graph = buildProbeGraph();
  const serialized = serialize(graph);

  if (mode === "--write") {
    mkdirSync(dirname(SNAPSHOT_PATH), { recursive: true });
    writeFileSync(SNAPSHOT_PATH, serialized, "utf8");
    process.stdout.write(`썼습니다: ${SNAPSHOT_PATH}\n`);
    return;
  }

  const existing = readSnapshot();
  if (existing === null) {
    process.stderr.write(
      `스냅샷이 없습니다: ${SNAPSHOT_PATH} — `
      + "node scripts/selftest_probe_graph.mjs --write 를 실행해 생성하십시오.\n",
    );
    process.exitCode = 1;
    return;
  }
  if (existing !== serialized) {
    process.stderr.write(
      `프로브 그래프 스냅샷이 레지스트리와 어긋납니다: ${SNAPSHOT_PATH} — `
      + "node scripts/selftest_probe_graph.mjs --write 로 다시 쓴 뒤 커밋하십시오.\n",
    );
    process.exitCode = 1;
    return;
  }
  process.stdout.write("프로브 그래프 스냅샷이 최신입니다.\n");
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main(process.argv.slice(2));
}
