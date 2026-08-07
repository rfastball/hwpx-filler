/* R4-04 — 네 제품 화면의 mounted-hidden visibility와 lifecycle owner registry.
 *
 * React DOM 자체의 commit은 기존 live gate가 잰다. 여기서는 그 commit을 만드는 순수 상태와
 * owner 호출 계약을 직접 실행하고, 속성 projection은 소스/합성 음성 표본으로 fail-closed하게
 * 고정한다. 소스만 보는 단언은 반드시 같은 술어가 깨진 표본을 물어 판별력을 증명한다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  PRODUCT_SCREEN_IDS,
  createProductScreenVisibility,
} from "../../frontend/src/screens/product_screens.ts";
import {
  SCREEN_LIFECYCLE_OWNER_IDS,
  createScreenLifecycleRegistry,
} from "../../frontend/src/screens/screen_lifecycle_registry.ts";

const PRODUCT_SCREENS_SOURCE = readFileSync(
  new URL("../../frontend/src/screens/product_screens.ts", import.meta.url),
  "utf8",
);

const EXACT_SCREENS = ["library", "job", "editor", "workbench"];

function projectionGaps(source) {
  const match = source.match(
    /function\s+screenProps\b[\s\S]*?\n\s*}\s*\n\s*function\s+JobScreen/,
  );
  if (!match) return new Set(["screenProps"]);
  const body = match[0];
  const required = new Map([
    ["class", 'className: `scr${on ? " on" : ""}`'],
    ["hidden", "hidden: !on"],
    ["inert", "inert: !on"],
    ["aria-hidden", '"aria-hidden": on ? "false" : "true"'],
  ]);
  return new Set([...required].filter(([, needle]) => !body.includes(needle)).map(([name]) => name));
}

test("제품 화면 집합은 library/job/editor/workbench 정확히 넷이며 동결돼 있다", () => {
  assert.deepEqual([...PRODUCT_SCREEN_IDS], EXACT_SCREENS);
  assert.equal(Object.isFrozen(PRODUCT_SCREEN_IDS), true);
});

test("visibility는 한 활성 화면을 구독자에게 동기 발행하고 동일 화면은 무변이다", () => {
  const visibility = createProductScreenVisibility("job");
  const seen = [];
  const release = visibility.subscribe(() => seen.push(visibility.getSnapshot()));

  assert.equal(visibility.getSnapshot(), "job");
  visibility.activate("library");
  visibility.activate("library");
  visibility.activate("editor");
  assert.deepEqual(seen, ["library", "editor"]);
  assert.equal(visibility.getSnapshot(), "editor");

  release();
  visibility.activate("workbench");
  assert.deepEqual(seen, ["library", "editor"], "해제 뒤 구독자가 다시 불리면 안 된다");
});

test("visibility는 계약 밖 화면을 조용히 만들지 않는다", () => {
  const visibility = createProductScreenVisibility("job");
  assert.throws(() => visibility.activate("settings"), /알 수 없는 제품 화면/);
  assert.equal(visibility.getSnapshot(), "job");
});

test("네 화면 wrapper는 mounted-hidden 네 축을 같은 on 판정에서 투영한다", () => {
  assert.deepEqual([...projectionGaps(PRODUCT_SCREENS_SOURCE)], []);
  const wrappers = [...PRODUCT_SCREENS_SOURCE.matchAll(
    /h\("section",\s*screenProps\("(library|job|editor|workbench)"/g,
  )].map((match) => match[1]);
  // job은 별도 JobScreen component 안에서 같은 helper를 쓴다.
  assert.deepEqual([...new Set(wrappers)].sort(), EXACT_SCREENS.toSorted());
});

test("visibility projection 술어는 합성 회귀의 각 독립 축을 문다", () => {
  const good = `function screenProps(id, active) {
    const on = id === active;
    return { className: \`scr\${on ? " on" : ""}\`, hidden: !on, inert: !on,
      "aria-hidden": on ? "false" : "true" };
  }
  function JobScreen() {}`;
  assert.deepEqual([...projectionGaps(good)], []);
  for (const [needle, expected] of [
    ["hidden: !on", "hidden"],
    ["inert: !on", "inert"],
    ['"aria-hidden": on ? "false" : "true"', "aria-hidden"],
    ['className: `scr${on ? " on" : ""}`', "class"],
  ]) {
    assert.deepEqual([...projectionGaps(good.replace(needle, "/* removed */"))], [expected]);
  }
});

test("lifecycle owner 집합은 editor/workbench 정확히 둘이다", () => {
  assert.deepEqual([...SCREEN_LIFECYCLE_OWNER_IDS], ["editor", "workbench"]);
  assert.equal(Object.isFrozen(SCREEN_LIFECYCLE_OWNER_IDS), true);
});

test("registry는 owner 호출을 전달하고 일반 화면은 false로 fallthrough한다", () => {
  const registry = createScreenLifecycleRegistry();
  const calls = [];
  registry.register("editor", {
    leaveTo: (to) => calls.push(["leave", to]),
    rerender: () => calls.push(["rerender"]),
  });
  registry.register("workbench", { leaveTo: (to) => calls.push(["workbench", to]) });

  assert.equal(registry.delegateLeave("library", "job"), false);
  assert.equal(registry.rerender("library"), false);
  assert.equal(registry.delegateLeave("editor", "job"), true);
  assert.equal(registry.rerender("editor"), true);
  assert.equal(registry.rerender("workbench"), false, "선택적 rerender 부재는 fallthrough다");
  assert.deepEqual(calls, [["leave", "job"], ["rerender"]]);
  assert.deepEqual(registry.ownerIds(), ["editor", "workbench"]);
});

test("registry는 중복·집합 밖 등록과 release 뒤 호출을 시끄럽게 거절한다", () => {
  const registry = createScreenLifecycleRegistry();
  const release = registry.register("editor", { leaveTo: assert.fail });
  assert.throws(
    () => registry.register("editor", { leaveTo: assert.fail }),
    /중복 등록/,
  );
  assert.throws(
    () => registry.register("settings", { leaveTo: assert.fail }),
    /집합 밖 등록/,
  );
  release();
  assert.throws(() => registry.delegateLeave("editor", "job"), /해제된 뒤 호출/);
  assert.throws(() => registry.rerender("editor"), /해제된 뒤 호출/);
  assert.throws(release, /두 번 해제/);
});
