/* R4-04 — shell 판정과 ProductScreens visibility를 잇는 동기 집행자.
 *
 * 가짜 DOM은 의도적으로 ``main.stage``의 scrollTop을 활성 화면 높이에 맞춰 clamp한다.
 * 이 대조가 없으면 잘못된 `.scr` 저장 구현도 평범한 숫자 객체에서는 초록이 된다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createProductScreenExecutor } from "../../frontend/src/screens/product_screen_executor.ts";
import { createProductScreenVisibility } from "../../frontend/src/screens/product_screens.ts";
import { createScreenLifecycleRegistry } from "../../frontend/src/screens/screen_lifecycle_registry.ts";

const EXECUTOR_SOURCE = readFileSync(
  new URL("../../frontend/src/screens/product_screen_executor.ts", import.meta.url),
  "utf8",
);

class FakeClassList {
  values = new Set();
  toggle(name, force) {
    if (force) this.values.add(name);
    else this.values.delete(name);
  }
  contains(name) { return this.values.has(name); }
}

class FakeElement {
  constructor(doc, id = "", parent = null) {
    this.doc = doc;
    this.id = id;
    this.parent = parent;
    this.children = [];
    this.dataset = {};
    this.attrs = new Map();
    this.hidden = false;
    this.inert = false;
    this.isConnected = true;
    this.scrollTop = 0;
    this.scrollLeft = 0;
    this.classList = new FakeClassList();
    if (parent) parent.children.push(this);
  }
  contains(candidate) {
    for (let node = candidate; node; node = node.parent) if (node === this) return true;
    return false;
  }
  setAttribute(name, value) { this.attrs.set(name, String(value)); }
  getAttribute(name) { return this.attrs.get(name) ?? null; }
  closest(selector) {
    if (selector !== '[hidden],[inert],[aria-hidden="true"]'
        && selector !== '.scr[hidden],.scr[inert],[aria-hidden="true"]') return null;
    for (let node = this; node; node = node.parent) {
      if (node.hidden || node.inert || node.getAttribute("aria-hidden") === "true") return node;
    }
    return null;
  }
  querySelector(selector) {
    if (!selector.startsWith("#")) return null;
    const id = selector.slice(1);
    return this.children.find((child) => child.id === id) ?? null;
  }
  querySelectorAll(selector) {
    if (selector !== "[id][data-preserve-scroll]") return [];
    return this.children.filter((child) => child.id && child.dataset.preserveScroll !== undefined);
  }
  focus(options) {
    this.focusOptions = options;
    this.doc.activeElement = this;
  }
}

function harness(initial = "library") {
  const doc = {
    activeElement: null,
    defaultView: { pywebview: {} },
    body: { classList: new FakeClassList() },
  };
  const stage = new FakeElement(doc, "stage");
  stage.maxScrollTop = 1000;
  let stageTop = 0;
  Object.defineProperty(stage, "scrollTop", {
    get: () => stageTop,
    set: (value) => { stageTop = Math.max(0, Math.min(Number(value), stage.maxScrollTop)); },
    configurable: true,
  });

  const roots = Object.fromEntries(
    ["library", "job", "editor", "workbench"].map((id) => [id, new FakeElement(doc, `scr-${id}`)]),
  );
  for (const root of Object.values(roots)) root.classList.values.add("scr");
  const libraryInput = new FakeElement(doc, "library-search", roots.library);
  const libraryInner = new FakeElement(doc, "library-list", roots.library);
  libraryInner.dataset.preserveScroll = "";
  const external = new FakeElement(doc, "top-nav");
  const navs = ["job", "library"].map((id) => {
    const button = new FakeElement(doc, `nav-${id}`);
    button.dataset.scr = id;
    return button;
  });
  const byId = new Map([
    [stage.id, stage], [external.id, external], [libraryInput.id, libraryInput],
    [libraryInner.id, libraryInner], ...Object.values(roots).map((root) => [root.id, root]),
    ...navs.map((button) => [button.id, button]),
  ]);
  doc.getElementById = (id) => byId.get(id) ?? null;
  doc.querySelector = (selector) => selector === "main.stage" ? stage : null;
  doc.querySelectorAll = (selector) => selector === ".navbtn" ? navs : [];

  const visibility = createProductScreenVisibility(initial);
  const heights = { library: 1000, job: 100, editor: 700, workbench: 700 };
  function project(id) {
    stage.maxScrollTop = heights[id];
    for (const [name, root] of Object.entries(roots)) {
      const on = name === id;
      root.hidden = !on;
      root.inert = !on;
      root.setAttribute("aria-hidden", on ? "false" : "true");
      root.classList.toggle("on", on);
    }
  }
  project(initial);
  visibility.subscribe(() => project(visibility.getSnapshot()));

  const events = [];
  const lifecycle = createScreenLifecycleRegistry();
  lifecycle.register("editor", { leaveTo: (to) => events.push(["leave", to]), rerender: () => events.push(["rerender"]) });
  lifecycle.register("workbench", { leaveTo: (to) => events.push(["workbench", to]) });
  const bridge = {
    hostReady() { return !!doc.defaultView?.pywebview; },
    async call(screen, action, payload) {
      events.push(["bridge", screen, action, payload]);
      return { notice: "새로고침 완료" };
    },
  };
  const executor = createProductScreenExecutor({
    doc,
    bridge,
    visibility,
    lifecycle,
    reclaimSurfaces: () => events.push(["reclaim"]),
    notify: (message) => events.push(["notify", message]),
  });
  return {
    doc, stage, roots, libraryInput, libraryInner, external, navs, visibility,
    lifecycle, events, executor, byId,
  };
}

test("applyScreen은 visibility.activate와 셸 marker를 한 flushSync 안에서 집행한다", () => {
  const apply = EXECUTOR_SOURCE.match(/applyScreen\(id:[\s\S]*?\n\s*},\n\n\s*dispatchRefresh/);
  assert.ok(apply, "applyScreen 구현을 찾지 못했습니다");
  assert.match(
    apply[0],
    /flushSync\s*\(\s*\(\)\s*=>\s*{[\s\S]*?visibility\.activate\(id\)[\s\S]*?applyShellMarkers/,
  );
});

test("React 첫 commit 전 기본 화면 적용은 marker를 기록하고 focus 복원만 미룬다", () => {
  const h = harness("library");
  for (const id of ["library", "job", "editor", "workbench"]) {
    h.byId.delete(`scr-${id}`);
  }

  assert.doesNotThrow(() => h.executor.applyScreen("job"));
  assert.equal(h.visibility.getSnapshot(), "job");
  assert.equal(
    h.navs.find((button) => button.dataset.scr === "job").getAttribute("aria-current"),
    "true",
  );
});

test("첫 commit 뒤 목적 화면 root 하나만 없으면 부분 트리를 시끄럽게 거절한다", () => {
  const h = harness("library");
  h.byId.delete("scr-job");
  assert.throws(() => h.executor.applyScreen("job"), /활성 제품 화면 root가 없습니다: job/);
});

test("main.stage 위치는 화면별로 500 → 짧은 화면 clamp → 500 왕복한다", () => {
  const h = harness("library");
  h.stage.scrollTop = 500;
  h.libraryInner.scrollTop = 73;
  h.doc.activeElement = h.external;

  h.executor.applyScreen("job");
  assert.equal(h.stage.scrollTop, 0, "첫 job 기억은 0이고 짧은 화면 범위 안이어야 한다");
  h.stage.scrollTop = 500;
  assert.equal(h.stage.scrollTop, 100, "가짜 DOM도 실제 짧은 화면처럼 clamp해야 한다");

  h.executor.applyScreen("library");
  assert.equal(h.stage.scrollTop, 500, "화면 공용 stage 좌표를 library별로 복원한다");
  assert.equal(h.libraryInner.scrollTop, 73, "id 내부 스크롤도 같은 화면 기억에서 복원한다");
});

test("외부 포커스는 보존하고 숨은 outgoing 포커스는 destination root로 내린다", () => {
  const h = harness("library");
  h.doc.activeElement = h.external;
  h.executor.applyScreen("job");
  assert.equal(h.doc.activeElement, h.external, "상단 nav/overlay 포커스를 화면 전환이 훔치지 않는다");

  h.executor.applyScreen("library");
  h.libraryInput.focus();
  h.executor.applyScreen("job");
  assert.equal(h.doc.activeElement, h.roots.job, "숨은 화면 안 포커스는 활성 root로 fallback한다");
  assert.deepEqual(h.roots.job.focusOptions, { preventScroll: true });

  h.executor.applyScreen("library");
  assert.equal(h.doc.activeElement, h.libraryInput, "안전한 stable id 포커스는 화면별로 복원한다");
});

test("화면 적용은 on/hidden/inert/aria-hidden과 nav/body를 함께 바꾼다", () => {
  const h = harness("library");
  h.doc.activeElement = h.external;
  h.executor.applyScreen("editor");

  assert.equal(h.visibility.getSnapshot(), "editor");
  for (const [id, root] of Object.entries(h.roots)) {
    const on = id === "editor";
    assert.equal(root.classList.contains("on"), on, id);
    assert.equal(root.hidden, !on, id);
    assert.equal(root.inert, !on, id);
    assert.equal(root.getAttribute("aria-hidden"), on ? "false" : "true", id);
  }
  assert.equal(h.doc.body.classList.contains("editor-open"), true);
  assert.equal(h.doc.body.classList.contains("workbench-open"), false);
  assert.equal(h.navs.find((button) => button.dataset.scr === "job").getAttribute("aria-current"), "false");
});

test("lifecycle/reclaim/refresh 효과는 shell executor 포트로 그대로 이어진다", async () => {
  const h = harness("editor");
  assert.equal(h.executor.delegateLeave("library", "job"), false);
  assert.equal(h.executor.delegateLeave("editor", "job"), true);
  h.executor.reclaimSurfaces();
  h.executor.rerenderEditor();
  await h.executor.dispatchRefresh("library");
  assert.deepEqual(h.events, [
    ["leave", "job"],
    ["reclaim"],
    ["rerender"],
    ["bridge", "library", "refresh", {}],
    ["notify", "새로고침 완료"],
  ]);
});

test("호스트 없는 refresh는 발신 없이 무동작 이행 약속을 돌려준다", async () => {
  const h = harness();
  h.doc.defaultView = {};
  assert.equal(await h.executor.dispatchRefresh("library"), null);
  assert.deepEqual(h.events, []);
});
