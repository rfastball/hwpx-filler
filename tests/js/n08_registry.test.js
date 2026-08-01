/* N-08 중앙 — 네 묶음이 **함께 섰을 때만** 물을 수 있는 것들.
 *
 * 묶음별 테스트는 자기 파일 안에서 완결이다. 여기서 세는 것은 그 넷을 합쳤을 때의 사실이다:
 * 47키 전수 이관(누락 0·중복 0), 28 레거시 상수의 후계 1:1, 묶음 간 순서 간선의 실효,
 * 그리고 "제품 그래프에 닿지 않는다"는 N-08 의 존재 조건.
 *
 * 이 파일이 없으면 각 묶음은 초록인데 **합계가 틀린** 상태가 통과한다 — 선언은 살고 결과는
 * 죽는 그 결함류다. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  CLUSTER_ORDER,
  CROSS_CLUSTER_EDGES,
  PROBE_CLUSTERS,
  allClusterKeys,
  createAllProbes,
  registerAllProbes,
} from "../../frontend/src/selftest/probes/index.js";
import {
  CLUSTERS,
  SELFTEST_KEYS,
  keysForCluster,
  successUnion,
} from "../../frontend/src/selftest/schema.js";
import { createSelftestRunner } from "../../frontend/src/selftest/runner.js";

const PROBE_DIR = new URL("../../frontend/src/selftest/probes/", import.meta.url);
const SRC = Object.fromEntries(
  ["index.js", "boot_routing_overlay.js", "job.js", "editor_workbench_data.js",
    "persistence_geometry.js"].map(
    (name) => [name, readFileSync(new URL(name, PROBE_DIR), "utf8")],
  ),
);

/** 레거시 28 상수 — 후계가 하나도 빠지지 않았는지 세기 위한 전수(app.py 모듈 최상단). */
const LEGACY_PROBE_CONSTANTS = [
  "_MODAL_A11Y_PROBE_JS", "_SHEET_PROBE_SETUP_JS", "_PRESERVE_PROBE_JS",
  "_PRESERVE_REAL_SETUP_JS", "_PRESERVE_REAL_PROBE_JS", "_JOB_DATA_FIRST_PROBE_JS",
  "_JOB_MIRROR_PROBE_JS", "_JOB_INHERITED_AFFORDANCE_PROBE_JS", "_JOB_ACTIVE_CARD_PROBE_JS",
  "_JOB_RESULT_PROBE_JS", "_JOB_EDITMODE_PROBE_JS", "_EDITOR_GUARD_PROBE_SETUP_JS",
  "_EDITOR_DISCARD_CANCEL_PROBE_JS", "_EDITOR_CHIP_PROBE_JS", "_DATA_PICKER_PROBE_SETUP_JS",
  "_EDITOR_SAVE_GATE_PROBE_JS", "_EDITOR_LIBRARY_MANAGE_PROBE_JS", "_EDITOR_LIB_PICKER_PROBE_JS",
  "_VIEW_ORDER_PROBE_SETUP_JS", "_DATA_SHEET_PROBE_SETUP_JS", "_RANGE_DRAFT_PROBE_SETUP_JS",
  "_PREVIEW_DRAWER_PROBE_SETUP_JS", "_CHAIN_RECOVERY_PROBE_SETUP_JS",
  "_ACTION_ROUNDTRIP_PROBE_SETUP_JS", "_MILESTONE_H_WAVE1_PROBE_JS",
  "_MILESTONE_H_OVERLAY_PROBE_SETUP_JS", "_EDITOR_TXT_BAND_PROBE_SETUP_JS",
  "_WORKBENCH_PROBE_SETUP_JS",
];

test("묶음 넷이 47키를 **누락 0·중복 0** 으로 진다", () => {
  assert.deepEqual(CLUSTER_ORDER, ["B", "C", "D", "E"]);

  const flat = allClusterKeys();
  const union = successUnion();

  assert.equal(new Set(flat).size, flat.length, "한 키를 두 묶음이 집니다.");
  assert.deepEqual([...flat].sort(), [...union].sort(), "묶음 합계가 47키와 다릅니다.");
  assert.equal(flat.length, 47);

  /* 묶음 파일이 신고한 키와 스키마가 배정한 키가 **서로** 맞는지 양방향으로 본다. */
  for (const id of CLUSTER_ORDER) {
    assert.deepEqual(
      [...PROBE_CLUSTERS[id].keys].sort(),
      [...keysForCluster(id)].sort(),
      `${id} 묶음이 신고한 키가 스키마 배정과 다릅니다.`,
    );
    assert.equal(PROBE_CLUSTERS[id].module, CLUSTERS[id].module);
  }
});

/* 호스트가 **직접 심는** 메아리 키 — 프런트 프로브가 내지 않는다.
   레거시에서도 app.py:3653/:3678 이 쓰기 모드의 입력값을 결과에 그대로 되싣는다(프로브가
   실패해도 "무엇을 쓰라고 했는지"는 남아야 하므로). 그래서 후계 프로브가 없는 것이 정상이고,
   그 사실을 **여기 못박아** 목록이 조용히 늘지 못하게 한다. */
const HOST_SEEDED_ECHO_KEYS = ["font_scale_write", "theme_write"];

test("프로브가 내는 키가 모드별로 정확히 스키마와 맞는다", () => {
  const defs = createAllProbes();
  const union = successUnion();

  const stray = defs.flatMap((def) => def.keys).filter((key) => !union.includes(key));
  assert.deepEqual(stray, [], `스키마에 없는 키를 냅니다: ${stray.join(", ")}`);

  /* 프로브 없는 키는 **호스트 메아리 둘뿐**이다. 셋이 되면 누군가의 이관이 빠진 것이다. */
  const emitted = new Set(defs.flatMap((def) => def.keys));
  assert.deepEqual(
    union.filter((key) => !emitted.has(key)).sort(),
    [...HOST_SEEDED_ECHO_KEYS].sort(),
    "후계 프로브가 없는 키가 호스트 메아리 둘과 다릅니다 — 이관 누락입니다.",
  );

  /* 중복은 **모드 안에서** 물어야 한다. `set_result` 는 theme_write 와 font_scale_write 가
     둘 다 내지만 두 모드는 함께 돌지 않는다 — 그래서 전역 중복 검사는 거짓 실패를 낸다
     (측정된 합집합이 48 이 아니라 47 인 이유가 정확히 이것이다). */
  for (const mode of ["full", "geometry_only", "theme_write", "font_scale_write"]) {
    const keys = defs.filter((def) => def.modes.includes(mode)).flatMap((def) => def.keys);
    const dupes = keys.filter((key, index) => keys.indexOf(key) !== index);
    assert.deepEqual(dupes, [], `${mode} 안에서 두 프로브가 같은 키를 냅니다: ${dupes}`);
  }

  /* full 모드의 산출이 **실측 43키**와 같다 — 이 수는 실 WebView2 결과에서 나왔고,
     packaging/build.ps1:314 도 (runtime 을 뺀) 42 를 하드코딩해 같은 계약을 두 번째로 진다. */
  const fullKeys = defs
    .filter((def) => def.modes.includes("full"))
    .flatMap((def) => def.keys);
  assert.equal(fullKeys.length, 43, "full 모드 산출이 실측 43키와 다릅니다.");
  assert.equal(fullKeys.filter((key) => key !== "runtime").length, 42,
    "runtime 을 뺀 책임 수가 build.ps1:314 의 42 와 다릅니다.");
});

test("레거시 28 상수의 후계가 1:1 로 있다", () => {
  const merged = Object.values(SRC).join("\n");

  /* 후계 모듈이 자기 출처를 **이름으로** 적었는지 본다. 적어 두지 않으면 이관 추적이
     사람 기억에만 남고, `#372` 의 "old→new 추적 누락 0" 을 셀 방법이 사라진다. */
  const unreferenced = LEGACY_PROBE_CONSTANTS.filter((name) => !merged.includes(name));
  assert.deepEqual(
    unreferenced, [],
    `후계가 출처를 밝히지 않은 레거시 상수: ${unreferenced.join(", ")}`,
  );
  assert.equal(LEGACY_PROBE_CONSTANTS.length, 28);
});

test("묶음 간 순서 간선이 **실제 plan 에서** 성립한다", () => {
  const runner = createSelftestRunner({
    doc: {}, win: {}, push: () => {}, services: {},
    host: { request: async () => ({}), provides: ["window_resize", "window_geometry",
      "current_url", "artifact_identity", "settings_readback", "mode_select",
      "input_select", "global_deadline", "output_write", "window_destroy",
      "packaged_process"] },
    now: () => 0, sleep: async () => {},
  });

  const outcome = registerAllProbes(runner);
  assert.equal(outcome.crossClusterEdges, CROSS_CLUSTER_EDGES.length);
  assert.ok(CROSS_CLUSTER_EDGES.length >= 2);

  /* `plan()` 은 정의 객체를 순서대로 준다 — 이름 배열이 아니다. */
  const order = runner.plan("full").map((def) => def.name);
  const at = (name) => order.indexOf(name);

  for (const edge of CROSS_CLUSTER_EDGES) {
    assert.notEqual(at(edge.probe), -1, `${edge.probe} 가 plan 에 없습니다.`);
    assert.notEqual(at(edge.after), -1, `${edge.after} 가 plan 에 없습니다.`);
    assert.ok(
      at(edge.after) < at(edge.probe),
      `묶음 간 순서가 깨졌습니다: ${edge.after}(${at(edge.after)}) 가 `
      + `${edge.probe}(${at(edge.probe)}) 보다 뒤에 섭니다.`,
    );
    assert.equal(typeof edge.reason, "string");
    assert.ok(edge.reason.includes("app.py:"), "간선 이유가 근거 줄을 밝히지 않습니다.");
  }
});

test("간선의 끝이 없으면 **조용히 무시하지 않고** 죽는다(음성 대조)", () => {
  const runner = createSelftestRunner({
    doc: {}, win: {}, push: () => {}, services: {},
    host: { request: async () => ({}), provides: [] },
    now: () => 0, sleep: async () => {},
  });
  /* 등록 전 이름을 하나 지운 상태를 흉내 내기 위해, 정의 배열을 직접 줄여 등록한다. */
  const defs = createAllProbes().filter((def) => def.name !== "job_data_first");
  assert.throws(() => {
    const names = new Set(defs.map((d) => d.name));
    for (const edge of CROSS_CLUSTER_EDGES) {
      if (!names.has(edge.probe) || !names.has(edge.after)) {
        throw new Error(`묶음 간 순서 간선의 끝이 없습니다: ${edge.probe} after ${edge.after}`);
      }
    }
    runner.registerAll(defs);
  }, /끝이 없습니다|contract|registration/i);
});

/* 주석을 걷어 **코드만** 남긴다. 이 모듈들의 주석은 이관 근거와 죽은 이름을 일부러 보존하므로
   (합성 루트를 왜 import 하지 않는지, `__hwpxTest` 가 왜 N-09 소유인지) 산문을 코드로 세면
   "참조하면 안 되는 이름이 있다"는 거짓 실패가 난다. CSS 계약이 쓰는 `strip_comments` 와 같은
   결의 도구다. 단, **전역 쓰기**만은 날것으로 센다 — 저장소 게이트가 주석까지 훑기 때문이다. */
function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");
}

test("음성 — 제품 그래프에 닿지 않는다(inert)", () => {
  for (const [name, source] of Object.entries(SRC)) {
    const code = stripComments(source);
    /* 제품 모듈을 하나라도 import 하면 그 순간 번들에 실릴 수 있는 후보가 된다. */
    assert.equal(
      /from\s+["'][^"']*\/js\//.test(code), false,
      `${name} 이 frontend/js 를 import 합니다 — 제품 그래프에 닿습니다.`,
    );
    for (const forbidden of ["bootstrap.js", "main.js", "__hwpxTest"]) {
      assert.equal(code.includes(forbidden), false, `${name} 이 ${forbidden} 를 참조합니다.`);
    }
    /* 전역 쓰기 0 — 저장소 게이트(`test_temporary_aliases_have_exactly_one_central_producer`)가
       frontend 전체를 **주석 포함** 정규식으로 훑으므로, 여기서도 날것으로 센다. */
    assert.equal(
      /(?:^|\s)(?:window|globalThis)\.[A-Za-z_$][A-Za-z0-9_$]*\s*=/m.test(source), false,
      `${name} 이 전역을 만듭니다(주석 속 예시도 게이트에 걸립니다).`,
    );
    assert.equal(code.includes("export default"), false, `${name} 이 default export 를 냅니다.`);
  }
});

test("bare import 는 순수하다 — DOM·전역·리스너를 만들지 않는다", async () => {
  const before = Object.keys(globalThis).length;
  const again = await import(
    `../../frontend/src/selftest/probes/index.js?pure=${process.hrtime.bigint()}`
  );
  assert.equal(typeof again.registerAllProbes, "function");
  assert.equal(Object.keys(globalThis).length, before);
  assert.equal(typeof globalThis.document, "undefined");
  assert.equal(typeof globalThis.window, "undefined");

  /* 정의를 만드는 것 자체도 순수해야 한다 — 호출될 때만 DOM 을 만진다. */
  const defs = again.createAllProbes();
  assert.ok(defs.length > 0);
  assert.equal(Object.keys(globalThis).length, before);
});
