/* Persistence/geometry probes: recovery, host ordering, writes, and deadlines. */
import test from "node:test";
import assert from "node:assert/strict";

import { createSelftestRunner, HOST_OPS } from "../../frontend/src/selftest/runner.js";
import {
  registerPersistenceGeometryProbes,
} from "../../frontend/src/selftest/probes/persistence_geometry.js";

/* ────────────────────────── 가상 시계 ────────────────────────── */

function createClock() {
  let clock = 0;
  let seq = 0;
  const timers = [];
  return {
    now: () => clock,
    sleep(ms) {
      return new Promise((resolve) => {
        timers.push({ at: clock + ms, seq: (seq += 1), resolve });
      });
    },
    fireNext() {
      if (timers.length === 0) return false;
      timers.sort((a, b) => (a.at - b.at) || (a.seq - b.seq));
      const timer = timers.shift();
      clock = Math.max(clock, timer.at);
      timer.resolve();
      return true;
    },
  };
}

async function settle(clock, promise) {
  let done = false;
  const tracked = promise.then(
    (value) => { done = true; return value; },
    (error) => { done = true; throw error; },
  );
  tracked.catch(() => {});
  for (let step = 0; step < 20000; step += 1) {
    for (let flush = 0; flush < 40; flush += 1) await Promise.resolve();
    if (done) break;
    if (!clock.fireNext()) break;
  }
  return tracked;
}

/* ────────────────────────── DOM 대역 ────────────────────────── */

class FakeEl {
  constructor(tag) {
    this.tagName = String(tag || "div").toUpperCase();
    this.textContent = "";
    this.children = [];
    this.parentNode = null;
    this.offsetParent = {};
    this.scrollWidth = 1000;
    this.clientWidth = 1000;
    this.removed = 0;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  remove() {
    this.removed += 1;
    if (this.parentNode) {
      this.parentNode.children = this.parentNode.children.filter((c) => c !== this);
      this.parentNode = null;
    }
  }

  getBoundingClientRect() {
    return { height: this.rectHeight === undefined ? 64 : this.rectHeight };
  }

  getAttribute(name) {
    return this.attributes && name in this.attributes ? this.attributes[name] : null;
  }
}

function createDom(options) {
  const conf = options || {};
  const app = new FakeEl("div");
  const topbar = new FakeEl("header");
  const body = new FakeEl("body");
  const root = new FakeEl("html");
  root.attributes = {
    "data-theme": conf.dataTheme === undefined ? null : conf.dataTheme,
    "data-font-scale": conf.fontScale === undefined ? "normal" : conf.fontScale,
  };
  const brand = new FakeEl("span");
  if (conf.brandVisible === false) brand.offsetParent = null;
  const tabs = [new FakeEl("button"), new FakeEl("button")];
  if (conf.hiddenTabs) tabs[1].offsetParent = null;
  body.scrollWidth = conf.bodyScrollWidth === undefined ? 1000 : conf.bodyScrollWidth;
  body.clientWidth = 1000;

  const styles = new Map([
    [app, {
      gridTemplateRows: conf.gridTemplateRows || "64px 1fr",
      props: { "--master-width": conf.masterWidth === undefined ? " 240px " : conf.masterWidth },
    }],
    [root, {
      fontSize: conf.rootPx || "16px",
      props: { "--a-card": conf.aCard === undefined ? " #ffffff " : conf.aCard },
    }],
  ]);

  const created = [];
  const doc = {
    readyState: conf.readyState || "complete",
    documentElement: root,
    body,
    createElement(tag) {
      const el = new FakeEl(tag);
      created.push(el);
      return el;
    },
    createRange() {
      return { selectNodeContents(node) { this.node = node; } };
    },
    querySelector(sel) {
      if (sel === ".app") return app;
      if (sel === ".brand-name") return brand;
      if (sel === ".topbar") return topbar;
      return null;
    },
    querySelectorAll(sel) {
      if (sel === ".navbtn") return tabs;
      if (sel === ".master-splitter") return conf.splitters || [];
      return [];
    },
  };

  const win = {
    getComputedStyle(el) {
      const entry = styles.get(el) || { props: {} };
      return {
        gridTemplateRows: entry.gridTemplateRows,
        fontSize: entry.fontSize,
        getPropertyValue(name) {
          return entry.props && name in entry.props ? entry.props[name] : "";
        },
      };
    },
    getSelection() {
      return {
        ranges: [],
        removeAllRanges() { this.ranges = []; },
        addRange(range) { this.ranges.push(range); },
        toString() {
          return this.ranges.length > 0 ? this.ranges[0].node.textContent : "";
        },
      };
    },
  };

  return { doc, win, app, body, root, brand, tabs, topbar, created };
}

function createCaps(overrides) {
  const clock = createClock();
  const dom = createDom((overrides || {}).dom);
  const requests = [];
  const conf = overrides || {};
  const caps = {
    doc: dom.doc,
    win: { ...dom.win, ...(conf.win || {}) },
    push: () => {},
    services: conf.services || {},
    host: {
      provides: HOST_OPS.slice(),
      request(op, payload) {
        requests.push({ op, payload });
        if (conf.host) return conf.host(op, payload);
        return null;
      },
    },
    now: clock.now,
    sleep: clock.sleep,
  };
  return { caps, clock, dom, requests };
}

/** 실 `Intent.chained` 와 같은 몸통 — 저장되는 링은 절대 reject 하지 않는다. */
function createIntent() {
  const chains = new Map();
  return {
    chained(key, send) {
      const result = (chains.get(key) || Promise.resolve()).then(send);
      const tail = result.catch(() => {}).then(() => {
        if (chains.get(key) === tail) chains.delete(key);
      });
      chains.set(key, tail);
      return result;
    },
  };
}

/* ────────────────────── 양성/음성 대조 보존 ────────────────────── */

test("chain_recovery — 거절이 전해지고 그 뒤 호출이 실제로 돈다", async () => {
  const { caps, clock } = createCaps({ services: { Intent: createIntent() } });
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("full", {}));

  const value = report.results.chain_recovery;
  /* 기준 실행과 **필드·값이 같다**. */
  assert.deepEqual(value, {
    pending: false, rejected_surfaced: true, after_value: "ok", after_ran: true,
  });
  assert.deepEqual(Object.keys(value), ["pending", "rejected_surfaced", "after_value", "after_ran"]);
  assert.equal(Object.prototype.hasOwnProperty.call(value, "error"), false);
});

test("chain_recovery — 체인이 죽으면 시끄럽게 실패한다(음성 대조)", async () => {
  /* 저장되는 링이 reject 를 그대로 물면 뒤 호출이 영영 안 돈다 — 그 회귀가 이 프로브의 표적. */
  const brokenIntent = {
    chains: new Map(),
    chained(key, send) {
      const chain = (this.chains.get(key) || Promise.resolve()).then(send);
      this.chains.set(key, chain); // 실패한 링을 그대로 저장 = 오늘 고쳐 둔 결함
      return chain;
    },
  };
  const { caps, clock } = createCaps({ services: { Intent: brokenIntent } });
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("full", {}));

  assert.equal(report.ok, false);
  const failure = report.errors.find((e) => e.probe === "chain_recovery");
  assert.equal(failure.code, "probe_threw");
  assert.match(failure.message, /의도된 실패/);
  /* 실패한 프로브의 키는 결과에 없다 — 모양만 맞는 값이 성공인 척하지 않는다. */
  assert.equal(Object.prototype.hasOwnProperty.call(report.results, "chain_recovery"), false);
});

test("chain_recovery — Intent 주입이 없으면 조용히 넘어가지 않는다", async () => {
  const { caps, clock } = createCaps({ services: {} });
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("full", {}));
  const failure = report.errors.find((e) => e.probe === "chain_recovery");
  assert.match(failure.message, /Intent\.chained 가 주입되지 않았습니다/);
});

test("grid_narrow / grid_wide — resize 는 호스트가 하고 읽기는 프런트가 한다", async () => {
  let width = 1440;
  const { caps, clock, requests, dom } = createCaps({
    host(op) {
      if (op === "window_resize") return null;
      return null;
    },
  });
  /* 폭에 따라 브랜드가 접히는 것을 대역이 흉내 낸다. */
  const originalQuery = dom.doc.querySelector.bind(dom.doc);
  dom.doc.querySelector = (sel) => {
    const el = originalQuery(sel);
    if (sel === ".brand-name") el.offsetParent = width >= 820 ? {} : null;
    return el;
  };
  caps.host.request = (op, payload) => {
    requests.push({ op, payload });
    if (op === "window_resize") width = payload.width;
    return null;
  };

  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("full", {}));

  const resizes = requests.filter((r) => r.op === "window_resize").map((r) => r.payload);
  assert.deepEqual(resizes, [
    { width: 760, height: 600 },
    { width: 1440, height: 900 },
  ]);
  /* 좁게 = 브랜드 접힘, 넓게 = 브랜드 전개. 대조 두 극이 살아 있다. */
  assert.equal(report.results.grid_narrow.brand_visible, false);
  assert.equal(report.results.grid_wide.brand_visible, true);
  for (const key of ["grid_narrow", "grid_wide"]) {
    assert.deepEqual(Object.keys(report.results[key]), [
      "rows", "tabs", "brand_visible", "overflow",
    ]);
    assert.equal(report.results[key].rows, 2);
    assert.equal(report.results[key].tabs, 2);
    assert.equal(report.results[key].overflow, false);
  }
});

test("theme_persist — 미저장 콜드부트 ↔ 쓰기 뒤 다크 두 극", async () => {
  const unpersisted = createCaps({ dom: { dataTheme: null, aCard: " #ffffff " } });
  const runnerA = createSelftestRunner(unpersisted.caps);
  registerPersistenceGeometryProbes(runnerA);
  const reportA = await settle(unpersisted.clock, runnerA.run("full", {}));
  assert.deepEqual(reportA.results.theme_persist, { data_theme: null, a_card: "#ffffff" });

  const persisted = createCaps({ dom: { dataTheme: "dark", aCard: " #14171a " } });
  const runnerB = createSelftestRunner(persisted.caps);
  registerPersistenceGeometryProbes(runnerB);
  const reportB = await settle(persisted.clock, runnerB.run("full", {}));
  assert.deepEqual(reportB.results.theme_persist, { data_theme: "dark", a_card: "#14171a" });
});

test("personalization_persist — 기본 ↔ large/larger 대조와 본문 선택", async () => {
  const base = createCaps({ dom: { fontScale: "normal", rootPx: "16px", masterWidth: " 240px " } });
  const runnerA = createSelftestRunner(base.caps);
  registerPersistenceGeometryProbes(runnerA);
  const reportA = await settle(base.clock, runnerA.run("full", {}));
  assert.deepEqual(reportA.results.personalization_persist, {
    font_scale: "normal",
    root_px: "16px",
    topbar_h: 64,
    master_width: 240,
    splitters: 0,
    body_overflow: false,
    selected_text: "선택 가능한 본문",
  });
  /* 필드 순서까지 레거시 그대로. */
  assert.deepEqual(Object.keys(reportA.results.personalization_persist), [
    "font_scale", "root_px", "topbar_h", "master_width",
    "splitters", "body_overflow", "selected_text",
  ]);

  for (const [scale, px] of [["large", "20px"], ["larger", "24px"]]) {
    const big = createCaps({ dom: { fontScale: scale, rootPx: px, masterWidth: " 333px " } });
    const runnerB = createSelftestRunner(big.caps);
    registerPersistenceGeometryProbes(runnerB);
    const reportB = await settle(big.clock, runnerB.run("full", {}));
    const value = reportB.results.personalization_persist;
    assert.equal(value.font_scale, scale);
    assert.equal(value.root_px, px);
    assert.equal(value.master_width, 333);
    assert.equal(value.body_overflow, false);
  }
});

test("personalization_persist — 프로브가 심은 <p> 는 문서에 남지 않는다", async () => {
  const { caps, clock, dom } = createCaps();
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  await settle(clock, runner.run("full", {}));
  assert.equal(dom.body.children.length, 0, "선택 프로브의 <p> 가 남으면 다음 측정을 오염시킵니다.");
  assert.equal(dom.created.length, 1);
  assert.equal(dom.created[0].removed, 1);
});

test("정리 실패는 시끄럽다 — <p> 가 남으면 뒤 프로브를 멈춘다", async () => {
  const { caps, clock, dom } = createCaps();
  /* 제거가 실패하는 대역: remove() 가 아무 일도 안 한다. */
  const realCreate = dom.doc.createElement.bind(dom.doc);
  dom.doc.createElement = (tag) => {
    const el = realCreate(tag);
    el.remove = () => {};
    return el;
  };
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("full", {}));
  const teardownError = report.errors.find((e) => e.phase === "teardown");
  assert.ok(teardownError, "정리 실패가 보고되지 않았습니다.");
  assert.match(teardownError.message, /문서에 남았습니다/);
  assert.equal(report.ok, false);
  assert.match(runner.toEvidence(report).error, /teardown_failed/);
});

/* ────────────────────── runtime — 값-수준 모드 ────────────────────── */

function runtimeWin(resources) {
  return {
    location: { href: "http://127.0.0.1:12960/index.html" },
    URL: globalThis.URL,
    performance: {
      getEntriesByType: () => (resources || []).map((name) => ({ name })),
    },
  };
}

test("runtime — full 모드는 external_fetch_* 가 null 이고 error 필드가 없다", async () => {
  const { caps, clock } = createCaps({
    win: runtimeWin(["http://127.0.0.1:12960/assets/index.js"]),
    host: (op) => (op === "artifact_identity"
      ? { artifact_id: "aid", tree_sha256: "tsha" }
      : "http://127.0.0.1:12960/index.html"),
  });
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("full", {}));

  const runtime = report.results.runtime;
  assert.deepEqual(Object.keys(runtime), [
    "page_url", "origin", "resource_urls", "resources_same_origin", "forbidden_resources",
    "artifact_id", "tree_sha256",
    "external_fetch_completed", "external_fetch_succeeded", "external_fetch_blocked",
  ]);
  assert.equal(runtime.resources_same_origin, true);
  assert.deepEqual(runtime.forbidden_resources, []);
  assert.equal(runtime.artifact_id, "aid");
  assert.equal(runtime.external_fetch_completed, null);
  /* full 모드에는 이 중첩 필드가 **없다** — 값-수준 모드에서만 붙는다. */
  assert.equal(Object.prototype.hasOwnProperty.call(runtime, "external_fetch_error"), false);
  assert.equal(report.results.url, "http://127.0.0.1:12960/index.html");
});

test("runtime — 외부 오리진·file:·@vite/client 는 금지 자원으로 잡힌다", async () => {
  const { caps, clock } = createCaps({
    win: runtimeWin([
      "http://127.0.0.1:12960/assets/index.js",
      "https://cdn.example.com/x.js",
      "file:///C:/x.js",
      "http://127.0.0.1:12960/@vite/client",
    ]),
    host: (op) => (op === "artifact_identity" ? { artifact_id: "a", tree_sha256: "t" } : "u"),
  });
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("full", {}));
  assert.equal(report.results.runtime.resources_same_origin, false);
  assert.equal(report.results.runtime.forbidden_resources.length, 3);
});

test("runtime — 오프라인 모드 양성/음성 대조 쌍", async () => {
  for (const [label, fetchImpl, expected] of [
    [
      "살아있는 프록시",
      () => Promise.resolve({}),
      { succeeded: true, blocked: false, error: "external fetch succeeded" },
    ],
    [
      "죽은 프록시",
      () => Promise.reject(new Error("net blocked")),
      { succeeded: false, blocked: true, error: "Error: net blocked" },
    ],
  ]) {
    const { caps, clock } = createCaps({
      win: {
        ...runtimeWin([]),
        AbortController: class { constructor() { this.signal = {}; } abort() {} },
        setTimeout: () => 1,
        clearTimeout: () => {},
        fetch: fetchImpl,
      },
      host: (op) => (op === "artifact_identity" ? { artifact_id: "a", tree_sha256: "t" } : "u"),
    });
    const runner = createSelftestRunner(caps);
    registerPersistenceGeometryProbes(runner);
    const report = await settle(clock, runner.run("full", { flags: { offlineProbe: true } }));
    const runtime = report.results.runtime;
    assert.equal(runtime.external_fetch_completed, true, label);
    assert.equal(runtime.external_fetch_succeeded, expected.succeeded, label);
    assert.equal(runtime.external_fetch_blocked, expected.blocked, label);
    assert.equal(runtime.external_fetch_error, expected.error, label);
  }
});

test("runtime — 오프라인 정착 시한 초과는 표식 값으로 확정된다(러너가 가로채지 않는다)", async () => {
  const { caps, clock } = createCaps({
    win: {
      ...runtimeWin([]),
      AbortController: class { constructor() { this.signal = {}; } abort() {} },
      setTimeout: () => 1,
      clearTimeout: () => {},
      fetch: () => new Promise(() => {}),
    },
    host: (op) => (op === "artifact_identity" ? { artifact_id: "a", tree_sha256: "t" } : "u"),
  });
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("full", { flags: { offlineProbe: true } }));
  const runtime = report.results.runtime;
  assert.equal(runtime.external_fetch_completed, false);
  assert.equal(runtime.external_fetch_succeeded, false);
  assert.equal(runtime.external_fetch_blocked, null);
  /* build.ps1:348-350 이 이 문자열을 실패로 읽는다 — 이미 시끄러운 자리다. */
  assert.equal(runtime.external_fetch_error, "offline probe timed out");
});

/* ────────────────────── 쓰기 모드 ────────────────────── */

test("theme_write — 실사용 홉을 지나고 디스크 반영을 확정한다", async () => {
  let saved = "system";
  const setCalls = [];
  const { caps, clock } = createCaps({
    win: { pywebview: { api: {} } },
    services: {
      Bridge: {},
      Theme: { set(value) { setCalls.push(value); saved = value; } },
    },
    host(op, payload) {
      if (op === "input_select") return "dark";
      if (op === "settings_readback") return payload.setting === "theme" ? saved : null;
      return null;
    },
  });
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("theme_write", {}));
  assert.equal(report.ok, true);
  assert.deepEqual(setCalls, ["dark"], "api 직접 호출이 아니라 Theme.set 홉을 지나야 합니다.");
  assert.deepEqual(report.results, { set_result: "dark" });
  /* 호스트가 심는 에코와 합쳐 증거가 완성된다. */
  assert.deepEqual(runner.toEvidence(report, { theme_write: "dark" }), {
    theme_write: "dark", set_result: "dark",
  });
});

test("theme_write — 브리지 준비 시한 초과는 조용한 통과가 아니다", async () => {
  const { caps, clock } = createCaps({
    win: {}, // pywebview 없음 = Theme.set 이 조용히 no-op 되는 조건
    services: { Bridge: {}, Theme: { set() { throw new Error("불려선 안 됩니다"); } } },
    host: (op) => (op === "input_select" ? "dark" : null),
  });
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("theme_write", {}));
  assert.equal(report.ok, false);
  assert.equal(report.errors[0].code, "deadline_exceeded");
  assert.match(report.errors[0].message, /브리지\(pywebview\.api\) 준비/);
  assert.deepEqual(report.results, {});
  /* 에코는 남고 error 가 함께 선다 — 레거시 실패 증거와 같은 모양. */
  const evidence = runner.toEvidence(report, { theme_write: "dark" });
  assert.equal(evidence.theme_write, "dark");
  assert.match(evidence.error, /deadline_exceeded/);
});

test("font_scale_write — 배율을 실 브리지로 심고 디스크 값을 되읽는다", async () => {
  let saved = "normal";
  const { caps, clock } = createCaps({
    win: { pywebview: { api: {} } },
    services: { Personalization: { setFontScale(value) { saved = value; } } },
    host(op, payload) {
      if (op === "input_select") return "large";
      if (op === "settings_readback") return payload.setting === "font_scale" ? saved : null;
      return null;
    },
  });
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("font_scale_write", {}));
  assert.deepEqual(report.results, { set_result: "large" });
  assert.deepEqual(runner.toEvidence(report, { font_scale_write: "large" }), {
    font_scale_write: "large", set_result: "large",
  });
});

/* ────────────────────── window_geometry ────────────────────── */

test("window_geometry — readyState 전제 뒤 호스트에 측정을 요청한다", async () => {
  const measured = {
    x: 32, y: 55, width: 1427, height: 865,
    avail_x: 0, avail_y: 0, avail_width: 2195, avail_height: 1183, maximized_like: false,
  };
  const { caps, clock, requests, dom } = createCaps({
    host: (op) => (op === "window_geometry" ? measured : null),
  });
  /* 처음 두 번은 loading, 그 뒤 complete — 전제 폴링이 실제로 돈다는 것을 실행으로 본다. */
  let reads = 0;
  Object.defineProperty(dom.doc, "readyState", {
    get() { reads += 1; return reads > 2 ? "complete" : "loading"; },
  });
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("geometry_only", {}));
  assert.deepEqual(report.results.window_geometry, measured);
  assert.deepEqual(requests.map((r) => r.op), ["window_geometry"]);
  assert.ok(reads > 2, "readyState 폴링이 실제로 돌아야 합니다.");
});

test("window_geometry — readyState 가 영영 안 오면 시끄럽게 실패한다", async () => {
  const { caps, clock } = createCaps({
    dom: { readyState: "loading" },
    host: (op) => (op === "window_geometry" ? {} : null),
  });
  const runner = createSelftestRunner(caps);
  registerPersistenceGeometryProbes(runner);
  const report = await settle(clock, runner.run("geometry_only", {}));
  assert.equal(report.ok, false);
  assert.equal(report.errors[0].phase, "precondition");
  assert.equal(report.errors[0].code, "deadline_exceeded");
  assert.deepEqual(report.results, {});
});
