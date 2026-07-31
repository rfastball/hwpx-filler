/* 프로브 묶음 레지스트리(N-08 중앙) — 네 묶음을 한 러너에 모으는 유일한 자리.

   각 묶음은 자기 파일 안에서만 완결이고, **묶음을 가로지르는 사실**은 어디에도 적힐 곳이
   없었다. 그 자리가 여기다.

   ## 왜 레인이 이걸 못 했나

   `runner.plan()` 은 `after` 가 등록되지 않은 이름을 가리키면 던진다. 그래서 B 의
   `milestone_h_wave1 → job_data_first`(C) 같은 간선은 레인 안에서 선언할 수 없다 — 선언하는
   순간 그 레인의 단독 테스트가 죽는다. 두 레인이 각각 "이건 중앙이 져야 한다"고 반환했고,
   실제로 그렇다: 간선의 양 끝이 다 서는 곳은 여기뿐이다.

   그 간선들을 **적지 않으면** 순서는 `legacySite` 숫자에만 기대게 된다. 숫자는 정렬을
   맞춰 주지만 *이유*를 잃는다 — 누군가 probe 를 옮기면 숫자는 조용히 따라오고, 왜 그
   순서였는지는 아무 데도 남지 않는다. 이 저장소가 `#137` 에서 겪은 것이 정확히 그것이다.

   ## 이 파일은 실행 경로가 아니다

   제품 entry(`main.js` → `compat.js`)는 이 파일에 닿지 않는다. N-08 은 **준비**이고 살아
   있는 엔진은 여전히 `app.py` 의 레거시 프로브다. 여기 모인 것을 실제로 돌리는 것은
   N-09 의 `__hwpxTest` capability 다. 그때까지 이 파일의 소비자는 단위 테스트뿐이다. */

import {
  B_CLUSTER,
  B_KEYS,
  createBootRoutingOverlayProbes,
} from "./boot_routing_overlay.js";
import { C_CLUSTER, C_KEYS, createJobProbes } from "./job.js";
import {
  D_CLUSTER,
  D_KEYS,
  createEditorWorkbenchDataProbes,
} from "./editor_workbench_data.js";
import {
  PERSISTENCE_GEOMETRY_CLUSTER,
  PERSISTENCE_GEOMETRY_KEYS,
  createPersistenceGeometryProbes,
} from "./persistence_geometry.js";

/* 묶음 표 — 참조 레인(E)과 뒤따른 셋의 export 이름이 갈렸다(E 는 슬러그, B·C·D 는 글자).
   여기서 별칭으로 맞추고 파일 셋을 건드리지 않는다: 이름을 통일하려고 세 파일을 다시
   여는 것은 계약이 아니라 취향이고, 그 편집이 레인 경계를 넘는 순간 되돌리기 단위가
   흐려진다. 이 표가 정본이므로 다음 소비자는 여기만 보면 된다. */
export const PROBE_CLUSTERS = Object.freeze({
  [B_CLUSTER]: Object.freeze({
    id: B_CLUSTER,
    keys: B_KEYS,
    create: createBootRoutingOverlayProbes,
    module: "frontend/src/selftest/probes/boot_routing_overlay.js",
  }),
  [C_CLUSTER]: Object.freeze({
    id: C_CLUSTER,
    keys: C_KEYS,
    create: createJobProbes,
    module: "frontend/src/selftest/probes/job.js",
  }),
  [D_CLUSTER]: Object.freeze({
    id: D_CLUSTER,
    keys: D_KEYS,
    create: createEditorWorkbenchDataProbes,
    module: "frontend/src/selftest/probes/editor_workbench_data.js",
  }),
  [PERSISTENCE_GEOMETRY_CLUSTER]: Object.freeze({
    id: PERSISTENCE_GEOMETRY_CLUSTER,
    keys: PERSISTENCE_GEOMETRY_KEYS,
    create: createPersistenceGeometryProbes,
    module: "frontend/src/selftest/probes/persistence_geometry.js",
  }),
});

/** 묶음 순서 — 레거시 드라이버가 도는 순서와 같다(B 의 부팅 확인이 먼저). */
export const CLUSTER_ORDER = Object.freeze(["B", "C", "D", "E"]);

/* 묶음을 가로지르는 순서 간선. **양 끝이 다른 파일에 있어** 레인이 선언할 수 없던 것들이다.
   `legacySite` 숫자가 이미 같은 정렬을 만들지만, 숫자는 *왜*를 잃는다 — 여기 적힌 이유가
   그 자리를 진다. 새 간선을 추가할 때는 근거가 되는 app.py 줄을 함께 적는다. */
export const CROSS_CLUSTER_EDGES = Object.freeze([
  Object.freeze({
    probe: "milestone_h_wave1",
    cluster: "B",
    after: "job_data_first",
    afterCluster: "C",
    reason:
      "app.py:3872-3876 — job_data_first 는 **빈 경로 스냅샷**을 남긴다. 먼저 job_mirror 가 "
      + "돌면 경로를 실은 스냅샷이 남고, 뒤따르는 milestone_h 계열이 그것을 읽어 다른 화면을 "
      + "잰다(#137 교차 오염). 숫자로는 3877 < 3969 라 지금도 맞지만, 이유가 여기 없으면 "
      + "probe 를 옮긴 사람이 그 사실을 알 길이 없다.",
  }),
  Object.freeze({
    probe: "data_picker",
    cluster: "D",
    after: "milestone_h_wave1",
    afterCluster: "B",
    reason:
      "app.py:3949-3951 — 데이터 선택 대화상자는 `Nav` 를 옮긴다. 그래서 폭을 재는 프로브"
      + "(milestone_h 계열, 클러스터 B)보다 **뒤에** 서야 한다. D 는 B 의 이름을 부를 수 "
      + "없어 legacySite 숫자로만 지고 있었다.",
  }),
]);

/** 네 묶음의 프로브 정의 전체 — 등록 없이 정의만 본다(순수). */
export function createAllProbes() {
  return CLUSTER_ORDER.flatMap((id) => PROBE_CLUSTERS[id].create());
}

/** 네 묶음의 키 전체 — 합집합이 아니라 **이어붙임**이다(겹침이 있으면 여기서 드러나야 한다). */
export function allClusterKeys() {
  return CLUSTER_ORDER.flatMap((id) => [...PROBE_CLUSTERS[id].keys]);
}

/** 한 러너에 네 묶음을 모두 등록한다 — 묶음 간 간선도 여기서 얹는다. */
export function registerAllProbes(runner) {
  const defs = createAllProbes();
  const names = new Set(defs.map((def) => def.name));

  /* 간선을 얹기 전에 **양 끝이 실재하는지** 먼저 본다. 이름이 어긋나면 조용히 무시하는
     대신 시끄럽게 죽는다 — 조용히 넘기면 그 간선은 있지도 없지도 않은 상태가 된다. */
  const applied = [];
  for (const edge of CROSS_CLUSTER_EDGES) {
    if (!names.has(edge.probe) || !names.has(edge.after)) {
      throw new Error(
        `묶음 간 순서 간선의 끝이 없습니다: ${edge.probe} after ${edge.after}`,
      );
    }
    const def = defs.find((candidate) => candidate.name === edge.probe);
    const after = [...(def.after || [])];
    if (!after.includes(edge.after)) after.push(edge.after);
    const merged = {
      ...def,
      after,
      afterReason: def.afterReason
        ? `${def.afterReason} / [묶음 간] ${edge.reason}`
        : `[묶음 간] ${edge.reason}`,
    };
    defs[defs.indexOf(def)] = merged;
    applied.push(edge);
  }

  runner.registerAll(defs);
  return { registered: defs.length, crossClusterEdges: applied.length };
}
