/* N-08 레인 S — selftest 결과 계약(`frontend/src/selftest/schema.js`) 단위 계약.
 *
 * 이 파일이 실측하는 것:
 *  ① 공개 표면 — 이름·개수가 계약 표와 같고 `export default` 가 없다.
 *  ② **산술을 구조로 확인한다** — 48 을 손으로 적어 비교하지 않는다. 모드 행렬에서
 *     합집합을 계산하고, 그 결과가 44 ∪ {window_geometry, theme_write, font_scale_write,
 *     set_result} 와 같은지를 **집합 연산으로** 본다. 하드코딩한 48 을 하드코딩한 48 과
 *     비교하는 테스트는 아무것도 못 본다.
 *  ③ 값-수준 모드 — `offline_probe` 는 키를 더하지 않는다(full 과 키 집합 동일).
 *  ④ `error` 는 성공 합집합 **밖**에 있다(부재 계약).
 *  ⑤ build.ps1 불변식 둘이 기계로 검사된다(43 · boolean false 금지).
 *  ⑥ `tpl_options` 는 소비 0건이 **명시로** 적혀 있다 — 조용히 사라지지도, 없던 단언이
 *     붙지도 않는다.
 *  ⑦ 음성 — 소스에 `window.X =` 0 · `__hwpxTest` 0 · `export default` 0, 그리고 bare import
 *     만으로 DOM·전역을 만지지 않는다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  BUILD_INVARIANTS,
  CLUSTERS,
  ERROR_CONTRACT,
  MODE_MODIFIERS,
  MODE_PRECEDENCE,
  NON_PYTEST_OWNERS,
  OWNERS,
  SELFTEST_KEYS,
  SELFTEST_MODES,
  VALUE_KINDS,
  checkBuildInvariants,
  checkErrorAbsence,
  keysForCluster,
  keysForMode,
  modesForKey,
  responsibilityKeys,
  successUnion,
  unassignedClusterKeys,
  unconsumedKeys,
} from "../../frontend/src/selftest/schema.js";

const SRC = readFileSync(
  new URL("../../frontend/src/selftest/schema.js", import.meta.url),
  "utf8",
);

/* 실측 기준(base SHA ae1b689, 실 WebView2 5모드 구동) + R2-04 신설 축 1(react_runtime).
   이 셋만 리터럴로 둔다 — 나머지는 전부 이 값들에서 **계산**한다. */
const FULL_MODE_KEY_COUNT = 44;
const MODE_ONLY_KEYS = ["font_scale_write", "set_result", "theme_write", "window_geometry"];

test("공개 표면 — 이름 전수와 export default 부재", () => {
  const exported = [
    BUILD_INVARIANTS, CLUSTERS, ERROR_CONTRACT, MODE_MODIFIERS, MODE_PRECEDENCE,
    NON_PYTEST_OWNERS, OWNERS, SELFTEST_KEYS, SELFTEST_MODES, VALUE_KINDS,
  ];
  for (const value of exported) assert.notEqual(value, undefined);
  for (const fn of [
    checkBuildInvariants, checkErrorAbsence, keysForCluster, keysForMode, modesForKey,
    responsibilityKeys, successUnion, unassignedClusterKeys, unconsumedKeys,
  ]) {
    assert.equal(typeof fn, "function");
  }
  assert.equal(/export\s+default/.test(SRC), false, "export default 는 금지입니다.");
});

test("모드 다섯 — 이름·환경변수·종류", () => {
  assert.deepEqual(Object.keys(SELFTEST_MODES).sort(), [
    "font_scale_write", "full", "geometry_only", "offline_probe", "theme_write",
  ]);
  assert.equal(SELFTEST_MODES.full.env, null);
  assert.equal(SELFTEST_MODES.offline_probe.env, "HWPX_SELFTEST_OFFLINE_PROBE");
  assert.equal(SELFTEST_MODES.geometry_only.env, "HWPX_SELFTEST_GEOMETRY_ONLY");
  assert.equal(SELFTEST_MODES.font_scale_write.env, "HWPX_SELFTEST_SET_FONT_SCALE");
  assert.equal(SELFTEST_MODES.theme_write.env, "HWPX_SELFTEST_SET_THEME");
  /* 배타 모드의 선택 순서 — geometry > font-scale > theme > full. */
  assert.deepEqual(MODE_PRECEDENCE, ["geometry_only", "font_scale_write", "theme_write", "full"]);
  /* 값-수준 변조기는 그 축에 없다. */
  assert.deepEqual(MODE_MODIFIERS, ["offline_probe"]);
  assert.equal(MODE_PRECEDENCE.includes("offline_probe"), false);
});

test("offline_probe 는 값-수준 모드다 — 키를 하나도 더하지 않는다", () => {
  assert.equal(SELFTEST_MODES.offline_probe.kind, "value-level");
  assert.equal(SELFTEST_MODES.offline_probe.baseMode, "full");
  assert.equal(SELFTEST_MODES.offline_probe.keys, null, "값-수준 모드는 자기 키 목록을 갖지 않는다.");
  assert.deepEqual(keysForMode("offline_probe"), keysForMode("full"));

  /* 달라지는 것은 `runtime` 안의 값뿐이고, 중첩 필드가 하나 는다. */
  const [delta] = SELFTEST_MODES.offline_probe.valueDeltas;
  assert.equal(delta.key, "runtime");
  assert.deepEqual(delta.addedFields, ["external_fetch_error"]);
  assert.deepEqual(delta.changedFields, [
    "external_fetch_completed", "external_fetch_succeeded", "external_fetch_blocked",
  ]);
  /* 그 필드들은 **최상위 키가 아니다** — 합집합에 새면 47 이 깨진다. */
  for (const field of [...delta.addedFields, ...delta.changedFields]) {
    assert.equal(Object.prototype.hasOwnProperty.call(SELFTEST_KEYS, field), false);
  }
});

test("합집합 산술 — 모드 행렬에서 **계산**해 48 이 나온다", () => {
  const full = keysForMode("full");
  assert.equal(full.length, FULL_MODE_KEY_COUNT);
  assert.equal(new Set(full).size, FULL_MODE_KEY_COUNT, "full 모드 키에 중복이 없다.");

  const union = successUnion();
  /* 합집합 = full ∪ 모드-한정 4. 손으로 적은 48 과 48 을 비교하지 않는다. */
  const computed = Array.from(new Set([...full, ...MODE_ONLY_KEYS])).sort();
  assert.deepEqual(union, computed);
  assert.equal(union.length, FULL_MODE_KEY_COUNT + MODE_ONLY_KEYS.length);
  assert.equal(union.length, 48);

  /* 모드-한정 키는 full 에 없다(그래야 4가 더해진다). */
  for (const k of MODE_ONLY_KEYS) assert.equal(full.includes(k), false, k);

  /* 서술표와 합집합이 정확히 같은 집합이다 — 한쪽만 자라는 드리프트 차단. */
  assert.deepEqual(Object.keys(SELFTEST_KEYS).sort(), union);
});

test("모드-한정 키의 모드 귀속", () => {
  assert.deepEqual(modesForKey("window_geometry"), ["geometry_only"]);
  assert.deepEqual(modesForKey("theme_write"), ["theme_write"]);
  assert.deepEqual(modesForKey("font_scale_write"), ["font_scale_write"]);
  assert.deepEqual(modesForKey("set_result"), ["font_scale_write", "theme_write"]);
  /* full 키는 값-수준 모드에서도 나온다 — 두 모드로 보인다. */
  assert.deepEqual(modesForKey("chain_recovery"), ["full", "offline_probe"]);
});

test("`error` 는 성공 합집합 밖의 **부재 계약**이다", () => {
  assert.equal(ERROR_CONTRACT.key, "error");
  assert.equal(ERROR_CONTRACT.kind, "absence");
  assert.equal(successUnion().includes("error"), false);
  assert.equal(Object.prototype.hasOwnProperty.call(SELFTEST_KEYS, "error"), false);
  /* 48 + error = 49. 폐기된 설계 수치 44 가 아니다. */
  assert.equal(ERROR_CONTRACT.unionWithError, successUnion().length + 1);
  assert.equal(ERROR_CONTRACT.unionWithError, 49);
  assert.ok(ERROR_CONTRACT.assertedAbsentBy.some((s) => s.includes("test_no_probe_error")));
  assert.ok(ERROR_CONTRACT.assertedAbsentBy.some((s) => s.includes("build.ps1")));
  /* 실패 경로에서 **있어야** 하는 자리도 적혀 있다 — 부재만 적으면 반쪽이다. */
  assert.ok(ERROR_CONTRACT.assertedPresentBy.length >= 2);
});

test("`error` 부재 검사는 사유를 재진술한다", () => {
  assert.equal(checkErrorAbsence({ job_on: true }), null);
  const violation = checkErrorAbsence({ job_on: true, error: "RuntimeError('bridge failed')" });
  assert.equal(violation.invariant, "errorAbsence");
  assert.match(violation.message, /bridge failed/);
});

test("build.ps1 불변식 ① — runtime 을 뺀 책임 수가 43", () => {
  assert.equal(BUILD_INVARIANTS.responsibilityCount.expected, 43);
  assert.deepEqual(BUILD_INVARIANTS.responsibilityCount.excludes, ["runtime"]);
  assert.match(BUILD_INVARIANTS.responsibilityCount.source, /build\.ps1:436-437/);

  /* 44키 실행 증거를 흉내 내 세어 본다 — 44 - runtime = 43. */
  const evidence = {};
  for (const k of keysForMode("full")) evidence[k] = k === "runtime" ? {} : "value";
  assert.equal(responsibilityKeys(evidence).length, 43);
  assert.deepEqual(checkBuildInvariants(evidence), []);

  /* 키 하나를 더하면 릴리스가 죽는다 — 그 사실이 여기서 보인다. */
  const grown = { ...evidence, brand_new_key: true };
  const violations = checkBuildInvariants(grown);
  assert.equal(violations.length, 1);
  assert.equal(violations[0].invariant, "responsibilityCount");
  assert.match(violations[0].message, /44 != 43/);
});

test("build.ps1 불변식 ② — 최상위 boolean false 금지", () => {
  const evidence = {};
  for (const k of keysForMode("full")) evidence[k] = k === "runtime" ? {} : "value";
  evidence.job_on = false;
  const violations = checkBuildInvariants(evidence);
  assert.equal(violations.length, 1);
  assert.equal(violations[0].invariant, "noTopLevelBooleanFalse");
  assert.match(violations[0].message, /job_on/);

  /* boolean 키 넷은 전부 성공 경로에서 true 여야 하는 것들이다. */
  for (const k of BUILD_INVARIANTS.noTopLevelBooleanFalse.booleanKeys) {
    assert.equal(SELFTEST_KEYS[k].kind, "boolean", k);
  }
  const booleans = Object.keys(SELFTEST_KEYS).filter((k) => SELFTEST_KEYS[k].kind === "boolean");
  assert.deepEqual(
    booleans.sort(),
    BUILD_INVARIANTS.noTopLevelBooleanFalse.booleanKeys.slice().sort(),
  );
});

test("외부 fetch 대조 쌍은 패키지 전용이고 양·음 두 극을 다 적는다", () => {
  const pair = BUILD_INVARIANTS.externalFetchControlPair;
  assert.equal(pair.packagedOnly, true);
  assert.equal(pair.positive.external_fetch_succeeded, true);
  assert.equal(pair.positive.external_fetch_blocked, false);
  assert.equal(pair.negative.external_fetch_succeeded, false);
  assert.equal(pair.negative.external_fetch_blocked, true);
  assert.ok(pair.source.some((s) => s.includes("243-246")));
  assert.ok(pair.source.some((s) => s.includes("348-350")));
});

test("비-pytest 소유자 넷이 적혀 있다", () => {
  const sites = NON_PYTEST_OWNERS.map((o) => o.site);
  assert.equal(sites.length, 4);
  assert.ok(sites.some((s) => s.includes("build.ps1:436-437")));
  assert.ok(sites.some((s) => s.includes("build.ps1:439-450")));
  assert.ok(sites.some((s) => s.includes("build.ps1:451-468")));
  assert.ok(sites.some((s) => s.includes("test_web_runtime_artifact.py:55")));
  /* 넷째(캡처 하니스의 `_selftest_drive` 치환)는 N-11A 에서 pytest 소유로 옮겨갔다 —
     `tests/test_live_run_contract.py`. 원장에 남아 있으면 이미 없는 계약을 가리킨다. */
  assert.ok(!sites.some((s) => s.includes("capture_101_screenshots.py")));
  for (const owner of NON_PYTEST_OWNERS) {
    assert.equal(typeof owner.owns, "string");
    assert.equal(typeof owner.breaksIf, "string");
  }
});

test("tpl_options — 소비 0건이 **명시**로 남아 있다", () => {
  const entry = SELFTEST_KEYS.tpl_options;
  assert.deepEqual(entry.consumedBy, []);
  assert.equal(typeof entry.unconsumedReason, "string");
  assert.match(entry.unconsumedReason, /소비 테스트 0건/);
  assert.match(entry.unconsumedReason, /3718/);
  /* 그래도 합집합에는 **있다** — 조용히 지우지 않는다. */
  assert.equal(successUnion().includes("tpl_options"), true);
  /* 감도 공백이 이름으로 적혀 있다. */
  assert.match(entry.note, /감도 공백/);

  const unconsumed = unconsumedKeys().map((e) => e.key);
  assert.equal(unconsumed.includes("tpl_options"), true);
  /* 소비 0건인 키 전수 — 늘어나면 여기서 보인다(현재 tpl_options·theme_write 둘). */
  assert.deepEqual(unconsumed, ["theme_write", "tpl_options"]);
  for (const entry2 of unconsumedKeys()) {
    assert.equal(typeof entry2.reason, "string", `${entry2.key} 에 사유가 없습니다.`);
  }
});

test("키 서술표 — 값 종류·소유·모드가 전부 알려진 어휘 안이다", () => {
  for (const [name, desc] of Object.entries(SELFTEST_KEYS)) {
    assert.ok(VALUE_KINDS.includes(desc.kind), `${name}: 알 수 없는 값 종류 ${desc.kind}`);
    assert.ok(OWNERS.includes(desc.owner), `${name}: 알 수 없는 소유 ${desc.owner}`);
    assert.ok(Array.isArray(desc.modes) && desc.modes.length > 0, name);
    for (const mode of desc.modes) {
      assert.ok(Object.prototype.hasOwnProperty.call(SELFTEST_MODES, mode), `${name}: ${mode}`);
      assert.ok(keysForMode(mode).includes(name), `${name} 이 ${mode} 의 키 목록에 없습니다.`);
    }
    assert.ok(Array.isArray(desc.consumedBy));
    if (desc.consumedBy.length === 0) assert.equal(typeof desc.unconsumedReason, "string", name);
  }
  /* mixed 소유 키는 어느 필드가 호스트 것인지 적는다. */
  assert.equal(SELFTEST_KEYS.runtime.owner, "mixed");
  assert.deepEqual(SELFTEST_KEYS.runtime.hostFields, ["artifact_id", "tree_sha256"]);
});

test("클러스터 — 다섯 묶음이 48키를 **겹침 0·고아 0** 으로 나눈다", () => {
  assert.deepEqual(Object.keys(CLUSTERS).sort(), ["B", "C", "D", "E", "R"]);
  for (const id of ["B", "C", "D", "E", "R"]) {
    assert.equal(CLUSTERS[id].assigned, true, `${id} 가 아직 미할당입니다.`);
    assert.match(CLUSTERS[id].module, /^frontend\/src\/selftest\/probes\/[a-z_]+\.js$/);
  }
  assert.match(CLUSTERS.E.module, /probes\/persistence_geometry\.js$/);
  assert.match(CLUSTERS.R.module, /probes\/react_runtime\.js$/);

  /* 모듈 경로는 묶음마다 **다르다** — 둘이 같으면 한 파일이 두 묶음을 진다. */
  const modules = ["B", "C", "D", "E", "R"].map((id) => CLUSTERS[id].module);
  assert.equal(new Set(modules).size, 5);

  assert.deepEqual(keysForCluster("E"), [
    "chain_recovery", "font_scale_write", "grid_narrow", "grid_wide",
    "personalization_persist", "runtime", "set_result", "theme_persist", "theme_write",
    "url", "window_geometry",
  ]);

  /* 분할의 산술을 **구조로** 센다 — 손으로 적은 수를 다시 적으면 둘 다 같이 낡는다. */
  const perCluster = ["B", "C", "D", "E", "R"].map((id) => keysForCluster(id));
  assert.deepEqual(perCluster.map((keys) => keys.length), [15, 6, 15, 11, 1]);

  const union = successUnion();
  const flat = perCluster.flat();
  assert.equal(flat.length, union.length, "묶음 합계가 48 과 다릅니다(겹침 또는 고아).");
  assert.equal(new Set(flat).size, flat.length, "한 키가 두 묶음에 들어 있습니다.");
  assert.deepEqual([...flat].sort(), [...union].sort(), "묶음 합집합이 48키와 다릅니다.");

  /* 고아 0 — 미할당이 남으면 그 키는 아무도 이관하지 않은 채 조용히 사라진다. */
  assert.deepEqual(unassignedClusterKeys(), []);

  /* 소비자 없는 키는 사라지지 않는다: 주인은 생겼고 **감도 공백은 그대로 보인다**. */
  assert.equal(keysForCluster("B").includes("tpl_options"), true);
  assert.equal(typeof SELFTEST_KEYS.tpl_options.unconsumedReason, "string");
  assert.deepEqual(SELFTEST_KEYS.tpl_options.consumedBy, []);
});

test("음성 — 전역 쓰기·__hwpxTest·상대 import 부재", () => {
  assert.equal(/(?:^|\s)window\.[A-Za-z_$][A-Za-z0-9_$]*\s*=/m.test(SRC), false);
  assert.equal(/globalThis\s*\.\s*[A-Za-z_$][A-Za-z0-9_$]*\s*=/.test(SRC), false);
  assert.equal(SRC.includes("__hwpxTest"), false);
  /* 스키마는 잎이다 — 아무것도 import 하지 않는다. */
  assert.equal(/^\s*import\s/m.test(SRC), false);
});

test("bare import 는 순수하다 — DOM·전역을 만들지 않는다", async () => {
  /* 제품 전역이 하나도 없는 상태에서 다시 열어도 던지지 않고, 열고 나서도 전역이 안 생긴다. */
  const before = Object.keys(globalThis).length;
  const again = await import(
    `../../frontend/src/selftest/schema.js?pure=${Date.now()}`
  );
  assert.equal(typeof again.successUnion, "function");
  assert.equal(Object.keys(globalThis).length, before);
  assert.equal(typeof globalThis.document, "undefined");
  assert.equal(typeof globalThis.window, "undefined");
});
