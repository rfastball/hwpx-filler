/* N-08 레인 D — 클러스터 D(`frontend/src/selftest/probes/editor_workbench_data.js`) 계약.
 *
 * 기준 이식본(클러스터 E)의 테스트와 같은 두 축을 본다:
 *  ⓐ 이식이 **충실**한가 — 소비 pytest(`tests/test_web_selftest_gate.py`)가 이름으로 단언하는
 *     필드가 그대로 나오고, 양성/음성 대조가 하나도 사라지지 않았는가.
 *  ⓑ 규약이 **지켜졌는가** — 등록 메타데이터(시한·순서·대기·정리)가 러너 계약을 통과하고,
 *     모듈이 import 만으로는 아무 일도 하지 않는가.
 *
 * DOM 은 손으로 세운 최소 대역이다. 제품 전역은 하나도 세우지 않는다 — 프로브가 전역을 읽지
 * 않는다는 것이 이 이식의 요점이기 때문이다(읽으면 대역이 없어 즉시 터진다).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createSelftestRunner, HOST_OPS, LEGACY_DEADLINES_MS } from "../../frontend/src/selftest/runner.js";
import { keysForCluster } from "../../frontend/src/selftest/schema.js";
import {
  D_CLUSTER,
  D_KEYS,
  createEditorWorkbenchDataProbes,
  registerEditorWorkbenchDataProbes,
} from "../../frontend/src/selftest/probes/editor_workbench_data.js";

const SRC = readFileSync(
  new URL("../../frontend/src/selftest/probes/editor_workbench_data.js", import.meta.url),
  "utf8",
);

/* ────────────────────────── 가상 시계 ────────────────────────── */
/* 기준 이식본 테스트(n08_persistence_geometry.test.js)의 시계를 그대로 쓴다. */

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

class El {
  constructor(stage, tag, props) {
    this.stage = stage;
    this.tagName = String(tag || "div").toUpperCase();
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.readOnly = false;
    this.isConnected = true;
    this.offsetParent = {};
    this.dataset = {};
    this.attrs = {};
    this.style = {};
    this.computed = { display: "block" };
    this.options = [];
    this.cells = [];
    this.clicks = 0;
    this.parentNode = null;
    this.rect = { top: 0, height: 24 };
    this.on = {};
    const conf = props || {};
    const classes = new Set(conf.classes || []);
    delete conf.classes;
    Object.assign(this, conf);
    this.classList = {
      contains: (c) => classes.has(c),
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
    };
  }

  getAttribute(name) {
    return name in this.attrs ? this.attrs[name] : null;
  }

  setAttribute(name, value) { this.attrs[name] = value; }

  getBoundingClientRect() { return this.rect; }

  focus() { this.stage.doc.activeElement = this; }

  blur() { if (this.stage.doc.activeElement === this) this.stage.doc.activeElement = this.stage.body; }

  contains(node) { return (this.holds || []).indexOf(node) !== -1; }

  click() {
    this.clicks += 1;
    if (this.on.click) this.on.click(this);
  }

  dispatchEvent(ev) {
    this.stage.events.push({ target: this, type: ev.type });
    if (this.on[ev.type]) this.on[ev.type](this, ev);
    return true;
  }

  querySelector(sel) { return this.stage.doc.querySelector(sel); }

  querySelectorAll(sel) { return this.stage.doc.querySelectorAll(sel); }
}

function createStage() {
  const stage = { events: [], map: new Map() };
  const body = new El(stage, "body");
  stage.body = body;
  body.click = function () { stage.events.push({ target: body, type: "click" }); };
  const doc = {
    body,
    activeElement: body,
    getElementById(id) {
      const list = stage.map.get(`#${id}`);
      return list && list.length > 0 ? list[0] : null;
    },
    querySelector(sel) {
      const list = stage.map.get(sel);
      return list && list.length > 0 ? list[0] : null;
    },
    querySelectorAll(sel) { return stage.map.get(sel) || []; },
    dispatchEvent(ev) {
      stage.events.push({ target: "document", type: ev.type, key: ev.key });
      if (stage.onDocEvent) stage.onDocEvent(ev);
      return true;
    },
  };
  stage.doc = doc;
  stage.set = (sel, els) => { stage.map.set(sel, Array.isArray(els) ? els : [els]); return els; };
  stage.drop = (sel) => { stage.map.delete(sel); };
  stage.mk = (sel, props) => {
    const el = new El(stage, (props || {}).tag || "div", props);
    stage.set(sel, [el]);
    return el;
  };
  return stage;
}

function makeEventCtor(type) {
  return class {
    constructor(name, opts) {
      this.type = name;
      this.kind = type;
      Object.assign(this, opts || {});
    }
  };
}

function createCaps(stage, services, overrides) {
  const clock = createClock();
  const pushes = [];
  const conf = overrides || {};
  const win = {
    getComputedStyle(el) { return (el && el.computed) || { display: "block" }; },
    Event: makeEventCtor("event"),
    MouseEvent: makeEventCtor("mouse"),
    KeyboardEvent: makeEventCtor("keyboard"),
  };
  const caps = {
    doc: stage.doc,
    win,
    push(screen, snapshot) {
      pushes.push({ screen, snapshot });
      if (stage.onPush) stage.onPush(screen, snapshot);
    },
    services: services || {},
    host: {
      provides: HOST_OPS.slice(),
      request(op, payload) { return conf.host ? conf.host(op, payload) : null; },
    },
    now: clock.now,
    sleep: clock.sleep,
  };
  return { caps, clock, pushes };
}

/** `after` 사슬을 걷어 프로브 하나만 몬다(순서 계약은 별도 테스트가 전수로 본다). */
function soloRunner(caps, name) {
  const runner = createSelftestRunner(caps);
  const def = createEditorWorkbenchDataProbes().find((p) => p.name === name);
  assert.ok(def, `프로브 정의 없음: ${name}`);
  runner.register(Object.assign({}, def, { after: [] }));
  return runner;
}

async function runSolo(stage, name, services, overrides) {
  const { caps, clock, pushes } = createCaps(stage, services, overrides);
  stage.sleep = caps.sleep;                    // 대역 앱도 같은 가상 시계를 쓴다
  const runner = soloRunner(caps, name);
  const report = await settle(clock, runner.run("full", {}));
  return { report, pushes, value: report.results[name] };
}

/* ────────────────────────── 표면 ────────────────────────── */

test("공개 표면 — 네 이름 전수와 export default 부재", () => {
  assert.equal(D_CLUSTER, "D");
  assert.ok(Array.isArray(D_KEYS));
  assert.equal(typeof createEditorWorkbenchDataProbes, "function");
  assert.equal(typeof registerEditorWorkbenchDataProbes, "function");
  assert.equal(/export\s+default/.test(SRC), false);
  /* 정확히 넷 — 넓히지 않는다. */
  const exported = (SRC.match(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm) || [])
    .map((line) => line.replace(/^export\s+(?:const|function)\s+/, ""));
  assert.deepEqual(exported.sort(), [
    "D_CLUSTER", "D_KEYS", "createEditorWorkbenchDataProbes", "registerEditorWorkbenchDataProbes",
  ].sort());
});

test("키 전수가 스키마의 클러스터 D 와 정확히 같다", () => {
  assert.deepEqual(D_KEYS.slice().sort(), keysForCluster("D"));
  assert.equal(D_KEYS.length, 15);
  for (const k of [
    "view_order", "data_sheet", "range_draft", "preview_drawer", "editor_guard",
    "editor_discard_cancel", "editor_txt_band", "workbench", "sheet_gate", "job_editmode",
    "data_picker", "editor_chip", "editor_save_gate", "editor_lib_manage", "editor_lib",
  ]) {
    assert.ok(D_KEYS.includes(k), k);
  }
  /* 프로브가 내는 키의 합집합도 같다 — 정의와 목록이 갈라지면 여기서 보인다. */
  const produced = createEditorWorkbenchDataProbes()
    .reduce((acc, p) => acc.concat(p.keys), []).sort();
  assert.deepEqual(produced, keysForCluster("D"));
});

test("등록 — 러너 계약을 전수 통과하고 full 모드 계획이 15개로 선다", () => {
  const stage = createStage();
  const { caps } = createCaps(stage, {});
  const runner = createSelftestRunner(caps);
  registerEditorWorkbenchDataProbes(runner);
  assert.equal(runner.probes().length, 15);
  assert.equal(runner.plan("full").length, 15);
  for (const p of runner.describe()) {
    assert.equal(p.cluster, "D");
    assert.deepEqual(p.modes, ["full"]);
    assert.equal(p.hostOp, null, `${p.name}: 이 클러스터에 호스트 소유 프로브는 없다`);
    assert.deepEqual(p.requiresHost, [], p.name);
  }
});

/* ────────────────────── 순서 제약 ────────────────────── */

test("plan('full') 순서가 레거시 드라이버 실행 순서 그대로다", () => {
  const stage = createStage();
  const { caps } = createCaps(stage, {});
  const runner = createSelftestRunner(caps);
  registerEditorWorkbenchDataProbes(runner);
  assert.deepEqual(runner.plan("full").map((p) => p.name), [
    "view_order", "data_sheet", "range_draft", "preview_drawer", "editor_guard",
    "editor_discard_cancel", "editor_txt_band", "workbench", "sheet_gate",
    "job_editmode", "data_picker", "editor_chip", "editor_save_gate",
    "editor_lib_manage", "editor_lib",
  ]);
  /* legacySite 는 app.py 의 실제 호출 자리 — 클러스터를 넘는 순서를 이 숫자가 잇는다. */
  const site = new Map(runner.describe().map((p) => [p.name, p.legacySite]));
  assert.deepEqual(Array.from(site.entries()), [
    ["view_order", 3754], ["data_sheet", 3764], ["range_draft", 3774],
    ["preview_drawer", 3786], ["editor_guard", 3794], ["editor_discard_cancel", 3802],
    ["editor_txt_band", 3808], ["workbench", 3814], ["sheet_gate", 3863],
    ["job_editmode", 3948], ["data_picker", 3952], ["editor_chip", 3959],
    ["editor_save_gate", 3961], ["editor_lib_manage", 3966], ["editor_lib", 3985],
  ]);
  /* 계획 순서는 legacySite 오름차순과 어긋나지 않는다(after 가 순서를 뒤집지 않는다). */
  const planned = runner.plan("full").map((p) => p.legacySite);
  assert.deepEqual(planned, planned.slice().sort((a, b) => a - b));
});

test("모든 after 에 afterReason 이 붙어 있다 — 이유 없는 순서는 다음 이식에서 사라진다", () => {
  const stage = createStage();
  const { caps } = createCaps(stage, {});
  const runner = createSelftestRunner(caps);
  registerEditorWorkbenchDataProbes(runner);
  const described = runner.describe();
  const withAfter = described.filter((p) => p.after.length > 0);
  assert.equal(withAfter.length, 14, "view_order 하나만 선행이 없다");
  for (const p of withAfter) {
    assert.equal(typeof p.afterReason, "string", p.name);
    assert.ok(p.afterReason.length > 0, p.name);
  }
});

test("data_picker — 「작업」 활성 지점 + 폭 측정 프로브 **앞**(app.py:3949-3951)", () => {
  const stage = createStage();
  const { caps } = createCaps(stage, {});
  const runner = createSelftestRunner(caps);
  registerEditorWorkbenchDataProbes(runner);
  const byName = new Map(runner.describe().map((p) => [p.name, p]));
  const picker = byName.get("data_picker");

  /* ① 「작업」이 활성인 지점 — 바로 앞 job_editmode 가 셸을 job 으로 되돌린다. */
  assert.deepEqual(picker.after, ["job_editmode"]);
  assert.match(picker.afterReason, /활성/);
  assert.match(picker.afterReason, /폭 측정/);
  /* ② 폭 측정 프로브(클러스터 B: milestone_h_wave1 3969 · overlay resize 3974)보다 앞.
        `after` 로는 남의 클러스터를 가리킬 수 없으므로 legacySite 가 그 순서를 잇는다. */
  assert.ok(picker.legacySite < 3969, `${picker.legacySite} < 3969`);
  assert.ok(picker.legacySite < 3974, `${picker.legacySite} < 3974`);
  /* 계획 안에서도 폭 측정 자리보다 뒤에 놓이지 않는다. */
  const order = runner.plan("full").map((p) => p.name);
  assert.ok(order.indexOf("data_picker") > order.indexOf("job_editmode"));
});

test("0.4초 냉각(app.py:3957)이 data_picker 뒤에 이유와 함께 남아 있다", () => {
  const stage = createStage();
  const { caps } = createCaps(stage, {});
  const runner = createSelftestRunner(caps);
  registerEditorWorkbenchDataProbes(runner);
  const byName = new Map(runner.describe().map((p) => [p.name, p]));

  assert.equal(byName.get("data_picker").cooldownAfterMs, 400);
  assert.match(byName.get("data_picker").cooldownReason, /백드롭/);
  assert.match(byName.get("data_picker").cooldownReason, /160/);
  /* 그 대기가 겨누는 **다음 프로브**가 실제로 뒤에 온다 — 아니면 대기가 허공에 걸린다. */
  assert.deepEqual(byName.get("editor_chip").after, ["data_picker"]);
  /* 다른 프로브에는 냉각이 없다(레거시에도 이 자리 하나뿐이다). */
  for (const p of runner.describe()) {
    if (p.name !== "data_picker") assert.equal(p.cooldownAfterMs, 0, p.name);
  }
  /* 고정 대기는 data_sheet 의 0.3초 quiesce 하나뿐이고 이유가 붙어 있다. */
  assert.equal(byName.get("data_sheet").settleBeforeMs, 300);
  assert.match(byName.get("data_sheet").settleReason, /quiesce|늦은 push/);
  for (const p of runner.describe()) {
    if (p.name !== "data_sheet") assert.equal(p.settleBeforeMs, 0, p.name);
  }
});

test("range_draft ↔ data_sheet 교차 대조가 순서로 못 박혀 있다", () => {
  const stage = createStage();
  const { caps } = createCaps(stage, {});
  const runner = createSelftestRunner(caps);
  registerEditorWorkbenchDataProbes(runner);
  const byName = new Map(runner.describe().map((p) => [p.name, p]));
  assert.deepEqual(byName.get("range_draft").after, ["data_sheet"]);
  assert.match(byName.get("range_draft").afterReason, /foot_hidden_in_screen/);
  assert.match(byName.get("range_draft").afterReason, /foot_shown_in_sheet/);
});

/* ────────────────────── 시간 예산 ────────────────────── */

test("시한은 레거시 예산을 넘지 않는다(old → new 전수)", () => {
  const stage = createStage();
  const { caps } = createCaps(stage, {});
  const runner = createSelftestRunner(caps);
  registerEditorWorkbenchDataProbes(runner);
  const byName = new Map(runner.describe().map((p) => [p.name, p]));

  /* 레거시 예산: 표에 있는 셋은 6.0초, `_probe_late` 로 회수하는 것들은 2.5초,
     동기 evaluate_js 는 0, sheet_gate 는 app.py:3864 의 0.8초 고정 대기. */
  const legacy = {
    view_order: 6000, data_sheet: 6000, range_draft: 6000,
    preview_drawer: 2500, editor_guard: 2500, editor_discard_cancel: 2500,
    editor_txt_band: 2500, workbench: 2500, data_picker: 2500,
    sheet_gate: 800,
    job_editmode: 0, editor_chip: 0, editor_save_gate: 0,
    editor_lib_manage: 0, editor_lib: 0,
  };
  assert.equal(LEGACY_DEADLINES_MS.__probe_late__, 2500);
  for (const [name, budget] of Object.entries(legacy)) {
    const probe = byName.get(name);
    assert.ok(probe, name);
    assert.ok(probe.deadlineMs <= budget, `${name}: ${probe.deadlineMs} <= ${budget}`);
    assert.equal(probe.deadlineMs, budget, `${name} 은 예산을 그대로 쓴다`);
  }
  /* 표에 있는 셋은 표의 값과 같고, 없는 것들은 사유를 적었다. */
  for (const name of ["view_order", "data_sheet", "range_draft"]) {
    assert.equal(byName.get(name).deadlineMs, LEGACY_DEADLINES_MS[name]);
  }
  /* 표에 없는 프로브는 사유를 적어야 등록이 통과한다(러너가 강제) — 그 사유를 정의에서 직접 본다. */
  for (const def of createEditorWorkbenchDataProbes()) {
    if (LEGACY_DEADLINES_MS[def.name] === undefined) {
      assert.equal(typeof def.deadlineRationale, "string", def.name);
      assert.ok(def.deadlineRationale.length > 0, def.name);
    }
  }
  /* 시한을 스스로 처리한다고 선언한 프로브는 없다(이 클러스터엔 표식 값 분기가 없다). */
  for (const p of runner.describe()) assert.equal(p.handlesOwnDeadline, false, p.name);
});

test("완주 표지(pending)를 러너가 센다 — 낡은 부분 결과가 성공인 척 못 한다", () => {
  const stage = createStage();
  const { caps } = createCaps(stage, {});
  const runner = createSelftestRunner(caps);
  registerEditorWorkbenchDataProbes(runner);
  const byName = new Map(runner.describe().map((p) => [p.name, p]));
  for (const name of [
    "view_order", "data_sheet", "range_draft", "preview_drawer", "editor_guard",
    "editor_discard_cancel", "editor_txt_band", "workbench", "data_picker",
  ]) {
    assert.equal(byName.get(name).completionField, "pending", name);
  }
  /* 동기 프로브와 sheet_gate 는 레거시에도 pending 표지가 없다(status 가 그 몫). */
  for (const name of [
    "sheet_gate", "job_editmode", "editor_chip", "editor_save_gate",
    "editor_lib_manage", "editor_lib",
  ]) {
    assert.equal(byName.get(name).completionField, null, name);
  }
});

/* ────────────────────── view_order ────────────────────── */

function viewOrderStage(conf) {
  const stage = createStage();
  const opt = (v) => ({ value: v });
  const sel = stage.mk("#jobOrderSel", { tag: "select" });
  sel.options = [opt("sourceDesc"), opt("sourceAsc")];
  sel.value = "sourceDesc";
  sel.on.change = () => { if (conf.revertOnChange) sel.value = "sourceDesc"; };
  const note = stage.mk("#jobOrderNote");
  note.textContent = "보이는 순서대로 생성됩니다.";
  stage.sel = sel;
  return stage;
}

test("view_order — 양성대조 선행 + 왕복 뒤 유지 + 복원", async () => {
  const stage = viewOrderStage({});
  const Bridge = {
    initial: () => Promise.resolve({ view_order: "sourceDesc" }),
    call: (screen, action, payload) => {
      if (action === "set_view_order") stage.sel.value = payload.value;
      return Promise.resolve({});
    },
  };
  const { value, report } = await runSolo(stage, "view_order", { Bridge });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.pending, false);
  assert.equal(value.present, true);
  assert.deepEqual(value.options, ["sourceDesc", "sourceAsc"]);
  assert.equal(value.control_before, true, "양성대조 — 렌더가 선택기 값을 실제로 쓴다");
  assert.ok(value.note_before.length > 0);
  assert.equal(value.after_roundtrip, "sourceAsc");
  assert.equal(value.restored, "sourceDesc");
});

test("view_order — 왕복이 옛 값으로 되돌리면 대조가 깨진다(음성)", async () => {
  const stage = viewOrderStage({ revertOnChange: true });
  const Bridge = {
    initial: () => Promise.resolve({ view_order: "sourceDesc" }),
    call: () => Promise.resolve({}),
  };
  const { value } = await runSolo(stage, "view_order", { Bridge });
  assert.equal(value.after_roundtrip, "sourceDesc", "되돌아온 값이 그대로 잡힌다");
});

test("view_order — 렌더가 선택기를 안 쓰면 control_before 가 먼저 깨진다(무동작 프로브 차단)", async () => {
  const stage = viewOrderStage({});
  stage.sel.value = "sourceAsc";               // 스냅샷과 어긋난 초기값 = 렌더 미사용
  const Bridge = {
    initial: () => Promise.resolve({ view_order: "sourceDesc" }),
    call: () => Promise.resolve({}),
  };
  const { value } = await runSolo(stage, "view_order", { Bridge });
  assert.equal(value.control_before, false);
});

test("view_order — 선택기가 없으면 조용히 넘어가지 않고 present:false 로 남는다", async () => {
  const stage = createStage();
  const { value } = await runSolo(stage, "view_order", { Bridge: {} });
  assert.equal(value.present, false);
  assert.equal(value.pending, false);
});

/* ────────────────────── data_sheet ────────────────────── */

function dataSheetStage(conf) {
  const stage = createStage();
  const options = conf || {};
  const ids = ["jobRecsHead", "jobOrderBar", "jobFilterChips", "jobTableHost",
    "jobSelStrip", "jobColPanel", "jobRangeFoot"];
  const screenHost = new El(stage, "div");
  const slot = stage.mk("#dataSheetSlot");
  slot.holds = [];
  const nodes = ids.map((id) => {
    const el = stage.mk(`#${id}`);
    el.parentNode = screenHost;
    return el;
  });
  const foot = stage.doc.getElementById("jobRangeFoot");
  foot.computed = { display: "none" };
  const th = stage.mk("#jobTableHead th:first-child");
  th.computed = { position: options.sticky === false ? "static" : "sticky" };
  const trigger = stage.mk("#jobDataExpand");
  const close = stage.mk("#dataSheetClose");
  stage.mk("#dataSheet .modal-card");
  trigger.on.click = () => {
    nodes.forEach((el) => { el.parentNode = slot; });
    slot.holds = nodes.slice();
    foot.computed = { display: "flex" };
  };
  let ticks = 0;
  close.on.click = () => { ticks = 0; stage.closing = true; };
  stage.step = () => {
    if (!stage.closing) return;
    ticks += 1;
    if (ticks >= (options.restoreAfter === undefined ? 2 : options.restoreAfter)) {
      nodes.forEach((el) => { el.parentNode = screenHost; });
      slot.holds = [];
      stage.doc.activeElement = trigger;
      stage.closing = false;
    }
  };
  /* 정착 전이(transitionend)가 폴링마다 오는 것을 흉내 낸다. */
  stage.map.get("#dataSheet .modal-card")[0].on.transitionend = () => stage.step();
  stage.nodes = nodes;
  stage.trigger = trigger;
  return stage;
}

test("data_sheet — 이동·헤더 고정·footer 자리·복귀가 전부 산다", async () => {
  const stage = dataSheetStage();
  const Bridge = { call: () => Promise.resolve({}) };
  const { value, report } = await runSolo(stage, "data_sheet", { Bridge });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.present, true);
  assert.equal(value.moved, true);
  assert.deepEqual(value.not_moved, []);
  assert.equal(value.first_sticky, true);
  assert.equal(value.foot_shown_in_sheet, true, "footer 는 면 안에서만 선다");
  assert.equal(value.restored, true);
  assert.equal(value.pending, false);
});

test("data_sheet — 면이 안 닫히면 정리가 시끄럽다(뒤 프로브 오염 차단)", async () => {
  const stage = dataSheetStage({ restoreAfter: 9999 });
  const SurfaceSheet = { calls: [], closeAndRestore(id) { this.calls.push(id); } };
  const Bridge = { call: () => Promise.resolve({}) };
  const { report, value } = await runSolo(stage, "data_sheet", { Bridge, SurfaceSheet });
  assert.equal(value.restored, false);
  const teardown = report.errors.find((e) => e.phase === "teardown");
  assert.ok(teardown, "정리 실패가 보고되지 않았습니다.");
  assert.equal(teardown.code, "teardown_failed");
  assert.match(teardown.message, /열린 채 남았습니다/);
  assert.deepEqual(SurfaceSheet.calls, ["dataSheet"], "구제(closeAndRestore)는 그대로 시도한다");
  assert.equal(report.ok, false);
  assert.match(runner_evidence_error(report), /teardown_failed/);
});

function runner_evidence_error(report) {
  const lines = report.errors.map((e) => `[${e.probe}/${e.phase}/${e.code}] ${e.message}`);
  return lines.join(" | ");
}

test("data_sheet — 스텁은 자기 액션만 가로채고 되돌려 놓는다", async () => {
  const stage = dataSheetStage();
  const seen = [];
  const Bridge = {
    call: (screen, action) => { seen.push(`real:${action}`); return Promise.resolve({}); },
  };
  const realCall = Bridge.call;
  await runSolo(stage, "data_sheet", { Bridge });
  assert.equal(Bridge.call, realCall, "복원은 「내 스텁일 때만」이지만 반드시 일어난다");
});

/* ────────────────────── range_draft ────────────────────── */

test("range_draft — 데이터 없이 여는 초안은 거절이고 footer 는 화면 안에서 숨는다", async () => {
  const stage = createStage();
  stage.mk("#jobDataExpand");
  const foot = stage.mk("#jobRangeFoot");
  foot.computed = { display: "none" };
  const Bridge = {
    call: () => Promise.reject(new Error("데이터가 없습니다")),
    initial: () => Promise.resolve({ range_draft: { open: false } }),
  };
  const { value, report } = await runSolo(stage, "range_draft", { Bridge });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.present, true);
  assert.equal(value.foot_hidden_in_screen, true);
  assert.equal(value.opened_without_data, false, "거절이 계약이다");
  assert.deepEqual(value.draft_state, { open: false });
  assert.equal(value.pending, false);
});

test("range_draft — 거절이 사라지면 값이 뒤집힌다(양성 극)", async () => {
  const stage = createStage();
  stage.mk("#jobDataExpand");
  const foot = stage.mk("#jobRangeFoot");
  foot.computed = { display: "none" };
  const Bridge = {
    call: () => Promise.resolve({ ok: true }),
    initial: () => Promise.resolve({ range_draft: { open: true } }),
  };
  const { value } = await runSolo(stage, "range_draft", { Bridge });
  assert.equal(value.opened_without_data, true, "두 극이 서로 다른 값을 낸다");
});

/* ────────────────────── preview_drawer ────────────────────── */

function previewStage() {
  const stage = createStage();
  const btn = stage.mk("#jobPreviewOpen");
  const modal = stage.mk("#previewSheet", { classes: ["hidden"] });
  const card = new El(stage, "div");
  modal.querySelector = (sel) => (sel === ".modal-card" ? card : stage.doc.querySelector(sel));
  stage.mk("#jobReviewFlag").computed = { display: "flex" };
  stage.mk("#previewPos").textContent = "2 / 2";
  stage.mk("#previewPrev").disabled = false;
  stage.mk("#previewNext").disabled = true;
  stage.set("#previewRows .mir-row", [new El(stage), new El(stage)]);
  stage.set("#previewEvidenceRows .mir-row", [new El(stage)]);
  stage.mk("#previewFilename").textContent = "doc-002.hwpx";
  const blank = stage.mk("#previewBlankOnly");
  blank.attrs["aria-pressed"] = "false";
  blank.disabled = false;
  stage.mk("#previewNamePlan").textContent = "doc-002.hwpx 외 1건";
  stage.mk("#previewApprove").computed = { display: "inline-flex" };
  btn.on.click = () => { modal.classList.remove("hidden"); stage.doc.activeElement = btn; };
  card.on.transitionend = () => { if (stage.stateClosed) modal.classList.add("hidden"); };
  stage.onPush = (screen, snap) => {
    if (screen === "job" && snap.preview && snap.preview.open === false) stage.stateClosed = true;
  };
  stage.btn = btn;
  stage.modal = modal;
  return stage;
}

test("preview_drawer — 거절 ↔ 성사, 경계 두 극, 상태가 면을 닫고 초점이 돌아온다", async () => {
  const stage = previewStage();
  let stubbed = 0;
  const Bridge = {
    call(screen, action) {
      stubbed += 1;
      if (action === "preview_open" && stubbed === 1) return Promise.reject(new Error("데이터 없음"));
      return Promise.resolve({ ok: true });
    },
  };
  const { value, report } = await runSolo(stage, "preview_drawer", { Bridge });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.present, true);
  assert.equal(value.hidden_before, true);
  assert.equal(value.opened_without_data, false, "양성대조 — 거절이 먼저 선다");
  assert.equal(value.opened, true, "성사 경로는 다른 값을 낸다");
  assert.equal(value.pos_text, "2 / 2");
  assert.equal(value.prev_disabled, false);
  assert.equal(value.next_disabled, true);
  assert.equal(value.value_rows, 2);
  assert.equal(value.evidence_rows, 1);
  assert.equal(value.filename, "doc-002.hwpx");
  assert.equal(value.scope_axis, false, "「적용 범위」 축은 실렌더에도 없다");
  assert.equal(value.approve_shown, true);
  assert.equal(value.closed_by_state, true, "상태가 면을 닫는다");
  assert.equal(value.focus_returned, true);
  assert.equal(value.focus_on_body, false, "초점이 문서 맨 앞으로 떨어지지 않는다");
  assert.equal(value.pending, false);
});

test("preview_drawer — 초점이 body 로 떨어지면 그 사실이 따로 잡힌다", async () => {
  const stage = previewStage();
  stage.btn.on.click = () => {
    stage.modal.classList.remove("hidden");
    stage.doc.activeElement = stage.body;      // focus() 가 조용한 no-op 이 되는 경로
  };
  const Bridge = { call: () => Promise.reject(new Error("거절")) };
  const { value } = await runSolo(stage, "preview_drawer", { Bridge });
  assert.equal(value.focus_returned, false);
  assert.equal(value.focus_on_body, true);
});

/* ────────────────────── editor_guard ────────────────────── */

function editorShellStage() {
  const stage = createStage();
  const nav = stage.mk(".nav");
  nav.computed = { display: "none" };
  const home = stage.mk('.navbtn[data-scr="job"]');
  stage.nav = nav;
  stage.home = home;
  return stage;
}

function guardStage(conf) {
  const options = conf || {};
  const stage = editorShellStage();
  const tab = stage.mk('#editor-steps button[data-section="filename"]');
  const modal = stage.mk("#chooseModal", { classes: ["hidden"] });
  const ok = stage.mk("#chooseModalOk");
  ok.textContent = "저장하고 이동";
  stage.services = null;
  tab.on.click = () => {
    stage.services.Bridge.call("editor", "goto_section", { section: "filename" })
      .then((res) => { if (res && res.needs_section_guard) modal.classList.remove("hidden"); });
  };
  ok.on.click = () => {
    modal.classList.add("hidden");
    const chain = stage.services.Bridge.call("editor", "save", {});
    if (options.stopAfterSave) return;
    chain.then(() => stage.services.Bridge.call(
      "editor", "goto_section", { section: "filename", disposition: "save" }));
  };
  return stage;
}

test("editor_guard — 저장하고 이동은 저장 **뒤 이동까지** 재발신한다", async () => {
  const stage = guardStage();
  const Nav = { go: () => { stage.nav.computed = { display: "flex" }; } };
  const Bridge = { call: () => Promise.resolve({}) };
  const services = { Nav, Bridge };
  stage.services = services;
  const { value, report } = await runSolo(stage, "editor_guard", services);
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.why, "완료");
  assert.equal(value.modal_label, "저장하고 이동");
  assert.deepEqual(value.calls, ["goto_section", "save", "goto_section:save"]);
  assert.equal(value.pending, false);
  assert.equal(Object.prototype.hasOwnProperty.call(value, "teardown_error"), false);
});

test("editor_guard — 저장에서 멈추면 재발신 한 건이 사라진다(음성)", async () => {
  const stage = guardStage({ stopAfterSave: true });
  const Nav = { go: () => { stage.nav.computed = { display: "flex" }; } };
  const services = { Nav, Bridge: { call: () => Promise.resolve({}) } };
  stage.services = services;
  const { value } = await runSolo(stage, "editor_guard", services);
  assert.deepEqual(value.calls, ["goto_section", "save"], "처분이 절반만 일어난 상태");
});

test("editor_guard — 셸이 안 돌아오면 정리가 시끄럽고 teardown_error 도 남는다", async () => {
  const stage = guardStage();
  const Nav = { go: () => {} };                 // 몰입 표면이 걷히지 않는다
  const services = { Nav, Bridge: { call: () => Promise.resolve({}) } };
  stage.services = services;
  const { report, value } = await runSolo(stage, "editor_guard", services);
  const teardown = report.errors.find((e) => e.phase === "teardown");
  assert.ok(teardown, "정리 실패가 보고되지 않았습니다.");
  assert.equal(teardown.code, "teardown_failed");
  assert.match(teardown.message, /상단 2탭/);
  /* 배선 호환 필드도 그대로 채워진다 — 레거시 증거 모양을 잃지 않는다. */
  assert.match(value.teardown_error, /몰입 표면/);
  assert.equal(report.ok, false);
});

test("editor_guard — 정리 실패는 뒤따르는 프로브를 건너뛰게 한다", async () => {
  const stage = guardStage();
  const services = { Nav: { go: () => {} }, Bridge: { call: () => Promise.resolve({}) } };
  stage.services = services;
  const { caps, clock } = createCaps(stage, services);
  const runner = createSelftestRunner(caps);
  const defs = createEditorWorkbenchDataProbes()
    .filter((p) => ["editor_guard", "editor_txt_band"].includes(p.name))
    .map((p) => Object.assign({}, p, { after: [] }));
  runner.registerAll(defs);
  const report = await settle(clock, runner.run("full", {}));
  assert.equal(report.skipped.length, 1);
  assert.equal(report.skipped[0].probe, "editor_txt_band");
  assert.equal(report.skipped[0].code, "skipped_after_teardown_failure");
});

/* ────────────────────── editor_discard_cancel ────────────────────── */

function discardStage(conf) {
  const options = conf || {};
  const stage = editorShellStage();
  const scr = stage.mk("#scr-editor");
  scr.id = "scr-editor";
  const nameEl = stage.mk("#editorName");
  const modal = stage.mk("#confirmModal", { classes: ["hidden"] });
  const cancel = stage.mk("#confirmModalCancel");
  const save = stage.mk('#editor-foot [data-act="save"]');
  let discard = stage.mk('#editor-foot [data-act="discard-patch"]');
  stage.services = null;
  let queued = false;
  let captured = null;

  /* blur→change 는 **큐에 넣기만** 한다(실 앱의 배치 발신). 그것을 언제 비우고 확인을 여는지가
     이 프로브가 겨누는 축이다. */
  const drain = () => {
    if (!queued) return Promise.resolve();
    queued = false;
    return stage.services.Bridge.call("editor", "set_name", {});
  };
  const openConfirm = () => { captured = discard; modal.classList.remove("hidden"); };
  /* dirty push 는 `#editor-foot` 을 통째로 갈아 끼운다 — 옛 트리거가 분리되는 실제 조건. */
  const rebuildFoot = (detached) => {
    discard.isConnected = false;
    const fresh = new El(stage, "button");
    fresh.disabled = false;
    fresh.isConnected = !detached;
    wireDiscard(fresh);
    stage.set('#editor-foot [data-act="discard-patch"]', [fresh]);
    discard = fresh;
    save.disabled = false;
  };
  function wireDiscard(el) {
    el.dataset.act = "discard-patch";
    el.on.click = () => {
      if (options.unflushed) {         // 확인이 먼저 열리고 큐는 **나중에** 비워진다
        openConfirm();
        stage.sleep(60).then(drain);
        return;
      }
      if (options.detachedTrigger) {   // 재구성이 먼저 끝나 확인이 **분리된** 트리거를 든다
        drain();
        rebuildFoot(true);
        openConfirm();
        return;
      }
      drain().then(openConfirm);       // 정산 뒤에 연다(계약)
    };
  }
  wireDiscard(discard);

  nameEl.on.input = () => { discard.disabled = false; save.disabled = false; };
  nameEl.on.change = () => { queued = true; };

  stage.onPush = (screen, snap) => {
    if (screen !== "editor" || !snap.dirty) return;
    rebuildFoot(false);
    nameEl.value = snap.name;
  };
  cancel.on.click = () => {
    modal.classList.add("hidden");
    /* 취소는 **저장해 둔** 트리거로 돌아간다. 분리돼 있으면 화면 루트로 떨어진다
       (모달의 대안 착지 — 키보드 사용자는 화면 처음에서 다시 걸어온다). */
    stage.doc.activeElement = captured && captured.isConnected ? captured : scr;
  };
  return stage;
}

test("editor_discard_cancel — 정산 뒤 확인이 열리고 취소는 아무것도 버리지 않는다", async () => {
  const stage = discardStage();
  const Nav = { go: () => { stage.nav.computed = { display: "flex" }; } };
  const services = { Nav, Bridge: { call: () => Promise.resolve({}) } };
  stage.services = services;
  const { value, report } = await runSolo(stage, "editor_discard_cancel", services);
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.why, "완료");
  assert.equal(value.discard_enabled_on_typing, true);
  assert.equal(value.flushed_before_open, true, "큐의 set_name 이 모달 전에 도착했다");
  assert.equal(value.trigger_connected_at_open, true, "모달이 든 트리거가 살아 있다");
  assert.equal(value.focus_back_on_discard, true);
  assert.equal(value.focus_fell_to_screen_root, false, "취소가 화면 루트로 떨어지지 않는다");
  assert.equal(value.name_value_after_cancel, "공고서 수정", "취소는 친 값을 지우지 않는다");
  assert.equal(value.discard_enabled_after_cancel, true);
  assert.equal(value.save_enabled_after_cancel, true);
  assert.equal(value.discarded, false, "취소 ≠ 버림");
  assert.deepEqual(value.calls, ["set_name"]);
});

test("editor_discard_cancel — 정산 전에 열면 flushed_before_open 이 뒤집힌다(음성 ①)", async () => {
  const stage = discardStage({ unflushed: true });
  const Nav = { go: () => { stage.nav.computed = { display: "flex" }; } };
  const services = { Nav, Bridge: { call: () => Promise.resolve({}) } };
  stage.services = services;
  const { value } = await runSolo(stage, "editor_discard_cancel", services);
  assert.equal(value.flushed_before_open, false, "확인이 대기 편집 정산 **전에** 열렸다");
  /* 이 시점의 트리거는 아직 붙어 있다 — 분리는 뒤늦게 도착하는 push 가 한다. 그래서 세 단언은
     한 벌이다: 하나만 두면 같은 결함이 다른 타이밍에서 조용히 빠져나간다. */
  assert.equal(value.trigger_connected_at_open, true);
});

test("editor_discard_cancel — 분리된 트리거로 열면 취소가 화면 루트로 떨어진다(음성 ②)", async () => {
  const stage = discardStage({ detachedTrigger: true });
  const Nav = { go: () => { stage.nav.computed = { display: "flex" }; } };
  const services = { Nav, Bridge: { call: () => Promise.resolve({}) } };
  stage.services = services;
  const { value } = await runSolo(stage, "editor_discard_cancel", services);
  assert.equal(value.trigger_connected_at_open, false, "되돌릴 자리가 이미 분리됐다");
  assert.equal(value.focus_fell_to_screen_root, true, "모달의 대안 착지");
  assert.equal(value.focus_back_on_discard, false);
  assert.equal(value.discarded, false, "그래도 취소는 아무것도 버리지 않는다");
});

/* ────────────────────── editor_txt_band ────────────────────── */

function txtBandStage() {
  const stage = editorShellStage();
  stage.onPush = (screen, snap) => {
    if (screen !== "editor") return;
    if (snap.template_media === "txt") {
      stage.set("#editor-steps .wstep-tab", [new El(stage), new El(stage)]);
      return;
    }
    const hwpx = new El(stage);
    hwpx.textContent = "HWPX 서식";
    const txt = new El(stage);
    txt.textContent = "TXT 기안";
    const other = new El(stage);
    other.textContent = "기타";
    stage.set("#editor-body .grp .cap", [hwpx, txt, other]);
    stage.set('#editor-body [data-act="use-library"][data-path="C:/t/기안.txt"]', [new El(stage)]);
    stage.set("#editor-steps .wstep-tab", [new El(stage), new El(stage), new El(stage)]);
  };
  return stage;
}

test("editor_txt_band — 2밴드·TXT 선택 버튼·TXT 세션 탭 2개", async () => {
  const stage = txtBandStage();
  const Nav = { go: (screen) => { stage.nav.computed = { display: screen === "job" ? "flex" : "none" }; } };
  const { value, report } = await runSolo(stage, "editor_txt_band", { Nav });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.deepEqual(value.bands.slice().sort(), ["HWPX 서식", "TXT 기안"]);
  assert.equal(value.txt_pick, true);
  assert.equal(value.txt_tabs, 2, "파일 이름 탭은 HWPX 속성이라 TXT 세션엔 없다");
  assert.equal(value.why, "완료");
  assert.equal(value.pending, false);
});

test("editor_txt_band — teardown_error 는 남되 실패는 러너가 세운다(레거시 감도 공백 봉합)", async () => {
  const stage = txtBandStage();
  const Nav = { go() { throw new Error("Nav 가 죽었습니다"); } };
  const { value, report } = await runSolo(stage, "editor_txt_band", { Nav });
  /* Nav.go 가 첫 줄에서 죽으므로 run 이 먼저 실패하고, 정리도 같은 이유로 실패한다.
     레거시라면 `teardown_error` 만 남고 아무도 읽지 않았다. */
  assert.equal(report.ok, false);
  assert.ok(report.errors.some((e) => e.phase === "teardown" && e.code === "teardown_failed"));
  assert.equal(Object.prototype.hasOwnProperty.call(report.results, "editor_txt_band"), false);
  assert.equal(value, undefined);
});

/* ────────────────────── workbench ────────────────────── */

function workbenchStage() {
  const stage = createStage();
  const nav = stage.mk(".nav");
  nav.computed = { display: "none" };
  stage.mk("#scr-workbench.on");
  stage.mk("#wbTitle").textContent = "발주요청_기안";
  stage.mk("#wbPosition").textContent = "1 / 3";
  stage.mk("#wbCopied").textContent = "1 / 3";
  stage.mk("#wbRevision").textContent = "서식 r1 · 연결 r4";
  stage.mk("#wbDirtyNote").textContent = "저장하지 않은 변경 1건";
  stage.mk("#wbReview").textContent = "다시 확인 필요";
  stage.set("#wbMapPanel tbody tr", [new El(stage, "tr"), new El(stage, "tr")]);
  stage.set("#wbMapPanel .mapval-declared", [new El(stage)]);
  stage.set("#wbCard .seg-fill", [new El(stage)]);
  stage.set("#wbCard .seg-blank", [new El(stage)]);
  const lint = stage.mk("#wbLint");
  lint.style = { display: "block" };
  const lintBtn = stage.mk("#wbLint [data-fullwidth]");
  lintBtn.attrs["data-fullwidth"] = "on";
  lintBtn.textContent = "전각으로 바꾸기";
  const dot = (title) => { const d = new El(stage); d.attrs.title = title; return d; };
  stage.set("#wbDots .wc-dot", [dot("7행 · 작업 중 · 다시 확인 필요"), dot("4행 · 대기")]);
  stage.mk("#wbTargetFont").value = "malgun";
  stage.mk("#wbPrev").disabled = false;
  stage.mk("#wbNext").disabled = true;
  stage.mk("#wbSaveRules").disabled = false;
  const cell = new El(stage, "td");
  cell.computed = { boxShadow: "inset 3px 0 0 0 rgb(37, 110, 244)" };
  const owner = new El(stage, "tr");
  owner.attrs["data-name"] = "수신";
  owner.cells = [cell];
  const token = new El(stage);
  token.on.click = () => { stage.doc.activeElement = owner; };
  stage.set("#wbCard [data-token]", [token, new El(stage)]);
  stage.set('#wbCard [data-token="수신"]', [token]);
  const prevBtn = stage.doc.getElementById("wbPrev");
  const adv = stage.mk(".wb-adv");
  stage.onPush = (screen, snap) => {
    if (screen !== "workbench") return;
    if (snap.card && snap.card.queue_degenerate) {
      prevBtn.computed = { display: "none" };
      adv.computed = { display: "none" };
    }
  };
  stage.mk("#scr-job.on");
  stage.drop("#scr-job.on");
  stage.landJob = () => { stage.mk("#scr-job.on"); nav.computed = { display: "flex" }; };
  return stage;
}

test("workbench — 몰입 셸·경계 두 극·큐 퇴화·이탈 발신 순서", async () => {
  const stage = workbenchStage();
  const services = {};
  services.Bridge = { call: () => Promise.resolve({}) };
  services.Nav = {
    go(screen) {
      if (screen !== "job") return;
      services.Bridge.call("workbench", "leave_guard", {})
        .then(() => services.Bridge.call("workbench", "close", {}))
        .then(() => stage.landJob());
    },
  };
  const { value, report } = await runSolo(stage, "workbench", services);
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.screen_on, true);
  assert.equal(value.nav_hidden, true, "몰입 셸이 상단 2탭을 덮는다");
  assert.equal(value.title, "발주요청_기안");
  assert.equal(value.position, "1 / 3");
  assert.equal(value.map_rows, 2);
  assert.equal(value.declared, 1);
  assert.equal(value.card_fill, 1);
  assert.equal(value.card_blank, 1);
  assert.equal(value.lint_action, "on:전각으로 바꾸기");
  assert.deepEqual(value.dots, ["7행 · 작업 중 · 다시 확인 필요", "4행 · 대기"]);
  assert.equal(value.font_value, "malgun");
  /* 순회 경계는 Python 이 낸 값 그대로 — 서수로 계산하면 정반대가 된다. */
  assert.equal(value.prev_disabled, false);
  assert.equal(value.next_disabled, true);
  assert.equal(value.card_tokens, 2);
  assert.equal(value.aim_row, "수신");
  assert.notEqual(value.aim_marked, "");
  assert.notEqual(value.aim_marked, "none");
  /* 큐 퇴화 — 1건이면 순회 장치가 실제로 숨는다. */
  assert.equal(value.degen_prev, "none");
  assert.equal(value.degen_adv, "none");
  /* 이탈: 가드를 먼저 묻고 세션을 닫은 뒤에야 화면이 바뀐다. */
  assert.deepEqual(value.leave_calls, ["leave_guard", "close"]);
  assert.equal(value.landed, true);
  assert.equal(value.pending, false);
});

test("workbench — 이탈이 가드를 건너뛰면 발신 순서로 잡힌다(음성)", async () => {
  const stage = workbenchStage();
  const services = {};
  services.Bridge = { call: () => Promise.resolve({}) };
  services.Nav = {
    go(screen) {
      if (screen !== "job") return;
      services.Bridge.call("workbench", "close", {}).then(() => stage.landJob());
    },
  };
  const { value } = await runSolo(stage, "workbench", services);
  assert.deepEqual(value.leave_calls, ["close"], "가드를 안 지난 이탈");
});

/* ────────────────────── sheet_gate ────────────────────── */

function sheetStage() {
  const stage = createStage();
  const modal = stage.mk("#sheetModal", { classes: ["hidden"] });
  stage.mk("#sheetModal .modal-card");
  const opts = [new El(stage, "button"), new El(stage, "button")];
  stage.set("#sheetList .sheet-opt", opts);
  stage.modal = modal;
  stage.opts = opts;
  return stage;
}

function sheetPicker(stage, services) {
  return {
    choose(screen, payload) {
      stage.modal.classList.remove("hidden");
      stage.doc.activeElement = stage.opts[0];
      return new Promise((resolve) => {
        stage.opts.forEach((btn, i) => {
          btn.on.click = () => {
            services.Bridge.loadDataSheet(screen, payload.path, payload.sheets[i].name)
              .then((v) => { stage.modal.classList.add("hidden"); resolve(v); });
          };
        });
        stage.onDocEvent = (ev) => {
          if (ev.type === "keydown" && ev.key === "Escape") {
            stage.modal.classList.add("hidden");
            resolve(null);
          }
        };
      });
    },
  };
}

test("sheet_gate — 확정은 고른 시트로 로드되고 취소는 null 중단이다", async () => {
  const stage = sheetStage();
  const services = {};
  services.Bridge = { loadDataSheet: () => Promise.reject(new Error("실 다이얼로그 금지")) };
  services.SheetPicker = sheetPicker(stage, services);
  const realLoad = services.Bridge.loadDataSheet;
  const { value, report } = await runSolo(stage, "sheet_gate", services);
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.status, "done", "status=='done' 이 나머지를 유의미하게 만든다");
  assert.equal(value.opened, true);
  assert.equal(value.btn_count, 2);
  assert.equal(value.focus_first, true);
  assert.equal(value.picked, "확정됨:낙찰현황", "확정 시트로 로드된다(첫 시트 강등 아님)");
  assert.equal(value.cancelled, null, "취소는 중단이다");
  assert.equal(value.closed_after, true);
  assert.equal(services.Bridge.loadDataSheet, realLoad, "스텁은 반드시 되돌려진다");
});

test("sheet_gate — 취소가 첫 시트로 강등되면 값이 갈린다(음성)", async () => {
  const stage = sheetStage();
  const services = {};
  services.Bridge = { loadDataSheet: () => Promise.resolve("x") };
  const base = sheetPicker(stage, services);
  let round = 0;
  services.SheetPicker = {
    choose(screen, payload) {
      round += 1;
      if (round === 1) return base.choose(screen, payload);
      stage.modal.classList.remove("hidden");
      /* 조용한 첫 시트 강등 — 계약 위반이 값으로 드러난다. */
      return services.Bridge.loadDataSheet(screen, payload.path, payload.sheets[0].name)
        .then((v) => { stage.modal.classList.add("hidden"); return v; });
    },
  };
  const { value } = await runSolo(stage, "sheet_gate", services);
  assert.equal(value.cancelled, "확정됨:공고목록");
  assert.notEqual(value.cancelled, null);
});

/* ────────────────────── job_editmode ────────────────────── */

function editmodeStage() {
  const stage = createStage();
  const nav = stage.mk(".nav");
  nav.computed = { display: "none" };
  const scrEditor = stage.mk("#scr-editor", { classes: ["on"] });
  stage.mk("#scr-job");
  stage.mk("#editorBack").computed = { display: "inline-flex" };
  const foot = stage.mk("#editor-foot");
  foot.computed = { display: "flex" };
  const saveState = stage.mk("#editorSaveState");
  const nameInput = stage.mk("#editorName");
  const ctxBanner = stage.mk("#editorContext");
  ctxBanner.computed = { display: "none" };
  const discard = stage.mk('#editor-foot [data-act="discard-patch"]');
  const save = stage.mk('#editor-foot [data-act="save"]');
  discard.disabled = true;
  save.disabled = true;
  stage.set("#editor-steps .wstep-tab .k", [new El(stage), new El(stage), new El(stage)]);
  stage.set("#editor-steps button.wstep-tab.as-tab", []);
  stage.set("#editor-steps button.wstep-tab.dirty", []);
  stage.onPush = (screen, snap) => {
    if (screen !== "editor") return;
    stage.set("#editor-steps button.wstep-tab.as-tab",
      snap.is_draft ? [] : [new El(stage), new El(stage), new El(stage)]);
    stage.set("#editor-steps button.wstep-tab.dirty",
      (snap.dirty_sections || []).map(() => new El(stage)));
    discard.disabled = !snap.dirty;
    save.disabled = !snap.dirty;
    saveState.textContent = snap.dirty ? "저장하지 않은 변경 1건" : "저장됨";
    nameInput.value = snap.name || "";
    const reason = snap.context && snap.context.entry_reason;
    ctxBanner.computed = { display: reason && reason !== "voluntary" ? "flex" : "none" };
    ctxBanner.textContent = reason === "preview_result" ? "미리보기에서 왔습니다 · 보고 있던 행 4 / 12" : "";
    stage.set('#editorContext [data-act="context-return"]',
      reason && reason !== "voluntary" ? [new El(stage)] : []);
  };
  stage.scrEditor = scrEditor;
  stage.nav = nav;
  return stage;
}

test("job_editmode — 몰입 편집기 셸과 clean/dirty · 문맥 두 극", async () => {
  const stage = editmodeStage();
  const Nav = {
    go(screen) {
      stage.nav.computed = { display: screen === "job" ? "flex" : "none" };
      if (screen === "job") stage.scrEditor.classList.remove("on");
    },
  };
  const { value, report } = await runSolo(stage, "job_editmode", { Nav });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.editor_screen_on, true);
  assert.equal(value.job_screen_off, true);
  assert.equal(value.nav_hidden, true);
  assert.equal(value.back_shown, true);
  assert.equal(value.wizard_steps, 3);
  assert.equal(value.foot_shown_new, true);
  assert.equal(value.edit_tabs, 3);
  assert.equal(value.foot_shown_edit, true);
  /* clean ↔ dirty 두 값을 각각 재고, 저장이 같은 술어를 쓰는지도 본다. */
  assert.equal(value.discard_shown_clean, true);
  assert.equal(value.discard_disabled_clean, true);
  assert.equal(value.save_disabled_clean, true);
  assert.equal(value.edit_dirty_tab_marked, 1);
  assert.match(value.dirty_head, /저장하지 않은 변경/);
  assert.equal(value.discard_enabled_dirty, true);
  assert.equal(value.save_enabled_dirty, true);
  /* 문맥 배너 — 자발적 진입이면 침묵하고 사유가 있으면 선다. */
  assert.equal(value.ctx_hidden_when_voluntary, true);
  assert.equal(value.ctx_shown, true);
  assert.ok(value.ctx_text.length > 0);
  assert.equal(value.ctx_return_btn, true);
  assert.equal(value.nav_back_after_leave, true, "몰입이 영구 은닉이 되지 않는다");
});

/* ────────────────────── data_picker ────────────────────── */

function pickerStage(conf) {
  const options = conf || {};
  const stage = createStage();
  const modal = stage.mk("#dataPickerModal", { classes: ["hidden"] });
  const pin = stage.mk("#dataPickerPin");
  if (options.registerAlive) stage.mk("#dataPickerRegister");
  const host = stage.mk("#dataPickerPinned");
  const corrupt = stage.mk("#dataPickerCorrupt");
  const dupes = stage.mk("#dataPickerDupes");
  const current = stage.mk("#dataPickerCurrent");
  const note = stage.mk("#dataPickerNote");
  const browse = stage.mk("#dataPickerBrowse");
  const regTitle = stage.mk("#poolRegTitle");
  const regOk = stage.mk("#poolRegOk");
  const regPath = stage.mk("#poolRegPath");
  const regSheet = stage.mk("#poolRegSheet");
  const regBrowse = stage.mk("#poolRegBrowse");
  regBrowse.computed = { display: "block" };
  stage.services = null;
  stage.onPush = (screen, snap) => {
    if (screen !== "pool") return;
    stage.set(".tplcard", snap.rows.map(() => new El(stage)));
    const uses = snap.rows.map((r) => {
      const b = new El(stage, "button");
      b.dataset.key = r.key;
      b.disabled = r.status === "archived";
      return b;
    });
    stage.set('[data-act="use"]', uses);
    stage.set('[data-act="activate"]', [new El(stage)]);
    stage.set('[data-act="relink"]', [new El(stage)]);
    corrupt.textContent = `손상된 등록 ${snap.corrupted.length}건`;
    dupes.textContent = "같은 데이터 등록 2건";
    stage.set("[data-dup-keep]", [new El(stage), new El(stage)]);
  };
  pin.on.click = () => {
    regTitle.textContent = "이 데이터 고정";
    regOk.textContent = "고정";
    regPath.value = "C:/d/대장.xlsx";
    regSheet.value = "물품";
    regPath.readOnly = true;
    regSheet.readOnly = true;
    regBrowse.computed = { display: "none" };
  };
  browse.on.click = () => {
    stage.services.Bridge.pickDataFile().then((d) => {
      note.textContent = `마운트: ${d.path.split("/").pop()}`;
      current.textContent = d.label;
      if (options.pinHiddenAfterBrowse) pin.computed = { display: "none" };
      if (options.closeAfterBrowse) modal.classList.add("hidden");
    });
  };
  stage.modal = modal;
  stage.host = host;
  return stage;
}

function pickerServices(stage) {
  const services = {
    Nav: { go: () => {} },
    Bridge: { pickDataFile: () => Promise.reject(new Error("실 파일 피커 금지")) },
    Modal: { closed: [], close(id) { this.closed.push(id); } },
    DataPicker: { open: () => { stage.modal.classList.remove("hidden"); } },
  };
  stage.services = services;
  return services;
}

test("data_picker — 보관은 숨기지 않고 정직하게 비활성 · 고정 프리필 · 병합 loud", async () => {
  const stage = pickerStage();
  const services = pickerServices(stage);
  const { value, report } = await runSolo(stage, "data_picker", services);
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.opened, true);
  assert.equal(value.pin_offered, true);
  assert.equal(value.register_gone, true, "「＋ 직접 등록…」은 DOM 자체가 없어야 한다");
  assert.equal(value.rows, 2);
  /* 활성 ↔ 보관 두 극 — 보관을 숨기면 활성화 동사가 도달 불가가 된다. */
  assert.equal(value.use_active_enabled, true);
  assert.equal(value.use_archived_disabled, true);
  assert.equal(value.activate_reachable, true);
  assert.equal(value.relink_reachable, true);
  assert.equal(value.use_targets_key, true, "행동 버튼이 슬롯 키를 겨눈다");
  assert.equal(value.corrupt_shown, true);
  assert.equal(value.dupes_shown, true);
  assert.equal(value.pin_title, "이 데이터 고정");
  assert.equal(value.pin_ok, "고정");
  assert.equal(value.pin_path, "C:/d/대장.xlsx");
  assert.equal(value.pin_sheet, "물품");
  assert.equal(value.pin_path_readonly, true);
  assert.equal(value.pin_sheet_readonly, true);
  assert.equal(value.pin_browse_hidden, true);
  assert.equal(value.browse_kept_open, true, "찾아보기 성사는 면을 유지한다");
  assert.equal(value.browse_restated, true);
  assert.equal(value.browse_pin_visible, true);
  assert.equal(value.error, null);
  assert.equal(value.pending, false);
  assert.deepEqual(services.Modal.closed, ["poolRegModal", "dataPickerModal"]);
});

test("data_picker — 고정 버튼이 배선만 되고 안 보이면 잡힌다(실가시성 단언)", async () => {
  const stage = pickerStage({ pinHiddenAfterBrowse: true });
  const services = pickerServices(stage);
  const { value } = await runSolo(stage, "data_picker", services);
  assert.equal(value.browse_pin_visible, false, "존재가 아니라 계산 스타일로 잰다");
});

test("data_picker — offsetParent 가 끊긴 고정 버튼도 불가시로 잡힌다", async () => {
  const stage = pickerStage();
  const services = pickerServices(stage);
  const pin = stage.doc.getElementById("dataPickerPin");
  pin.offsetParent = null;
  const { value } = await runSolo(stage, "data_picker", services);
  assert.equal(value.browse_pin_visible, false);
});

test("data_picker — 죽은 「＋ 직접 등록…」이 살아 있으면 register_gone 이 뒤집힌다(음성)", async () => {
  const stage = pickerStage({ registerAlive: true });
  const services = pickerServices(stage);
  const { value } = await runSolo(stage, "data_picker", services);
  assert.equal(value.register_gone, false);
});

/* ────────────────────── editor_chip ────────────────────── */

function chipStage(conf) {
  const options = conf || {};
  const stage = createStage();
  const root = stage.mk("#scr-editor");
  stage.onPush = () => {
    stage.set(".hchip.on[data-act=\"toggle-header\"]", [new El(stage), new El(stage), new El(stage)]);
    stage.set(".hbx", options.checkboxStaging ? [new El(stage)] : []);
    stage.set('.hchip.ign[data-act="toggle-header"]', [new El(stage)]);
    stage.set("details.hidden-hdrs[open]", [new El(stage)]);
    stage.set('[data-act="use-none"]', [new El(stage)]);
    stage.set("table.map .tag", ["확정", "수동", "제안", "후보 없음"].map((t) => {
      const el = new El(stage);
      el.textContent = ` ${t} `;
      return el;
    }));
    stage.set('table.map [data-act="revert-source"]', [new El(stage)]);
    const cell = (h) => { const c = new El(stage, "td"); c.rect = { top: 0, height: h }; return c; };
    const manual = cell(options.wrapped ? 56 : 28);
    const suggested = cell(28);
    stage.set("table.map tbody tr td:nth-child(3)", [cell(28), manual, suggested, cell(28)]);
    const wrap = new El(stage);
    const sel = new El(stage);
    sel.rect = { top: 4, height: 24 };
    const btn = new El(stage);
    btn.rect = { top: options.wrapped ? 32 : 4, height: 24 };
    manual.querySelector = (s) => (s === ".srcwrap" ? wrap : null);
    wrap.querySelector = (s) => (s === ".sel" ? sel : btn);
  };
  stage.root = root;
  return stage;
}

test("editor_chip — 체크박스 스테이징 소거·소유권 태그 4종·같은 줄 기하", async () => {
  const stage = chipStage();
  const { value, report } = await runSolo(stage, "editor_chip", { Nav: { go: () => {} } });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.active_chips, 3);
  assert.equal(value.has_checkbox_staging, false, "스테이징 소거의 음성 단언");
  assert.equal(value.ignored_chip, true);
  assert.equal(value.ignored_fold_open, true);
  assert.equal(value.use_none_btn, true);
  assert.deepEqual(value.tags, ["확정", "수동", "제안", "후보 없음"]);
  assert.equal(value.auto_revert_option, true);
  assert.equal(value.src_cell_h_manual, value.src_cell_h_suggested, "재제안 버튼이 안 밀렸다");
  assert.equal(value.revert_same_line, true);
  assert.equal(value.error, null);
});

test("editor_chip — 버튼이 둘째 줄로 밀리면 칸 높이와 세로 중심이 갈린다(음성)", async () => {
  const stage = chipStage({ wrapped: true, checkboxStaging: true });
  const { value } = await runSolo(stage, "editor_chip", { Nav: { go: () => {} } });
  assert.notEqual(value.src_cell_h_manual, value.src_cell_h_suggested);
  assert.equal(value.revert_same_line, false);
  assert.equal(value.has_checkbox_staging, true);
});

/* ────────────────────── editor_save_gate ────────────────────── */

function saveGateStage(conf) {
  const options = conf || {};
  const stage = createStage();
  const save = stage.mk('#editor-foot [data-act="save"]');
  const discard = stage.mk('#editor-foot [data-act="discard-patch"]');
  const nameEl = stage.mk("#editorName");
  const patEl = stage.mk('#editor-body input[data-act="pattern"]');
  save.disabled = true;
  discard.disabled = true;
  /* 「아직 도착하지 않은 입력이 있는가」를 DOM 사실로 합성하는 실제 판정을 흉내 낸다. */
  const baseline = new Map();
  const pending = new Set();
  const sync = () => {
    save.disabled = pending.size === 0;
    discard.disabled = pending.size === 0;
  };
  const wire = (el, key) => {
    el.on.input = () => {
      if (el.value === baseline.get(key)) pending.delete(key);
      else pending.add(key);
      sync();
    };
  };
  baseline.set("name", "공고서");
  baseline.set("pattern", "공고서-{{공고번호}}");
  wire(nameEl, "name");
  wire(patEl, "pattern");
  nameEl.value = "공고서";
  patEl.value = "공고서-{{공고번호}}";
  let constEl = null;
  stage.onPush = (screen, snap) => {
    if (screen !== "editor") return;
    if (snap.section === "binding" && snap.rows && snap.rows.length > 0) {
      const typed = constEl && options.dropValueOnPush !== true ? constEl.value : null;
      constEl = new El(stage, "input");
      constEl.value = typed === null ? snap.rows[0].const : typed;
      baseline.set("row", snap.rows[0].const);
      wire(constEl, "row");
      stage.set('#editor-body [data-act="row-const"]', [constEl]);
      if (constEl.value === baseline.get("row")) pending.delete("row"); else pending.add("row");
    } else {
      /* 되돌릴 자리가 사라지면 그 대기도 버린다 — 남은 편집이 없는데 열린 버튼은 거짓말이다. */
      stage.set('#editor-body [data-act="row-const"]', []);
      constEl = null;
      if (!options.keepGoneControl) pending.delete("row");
    }
    sync();
  };
  return stage;
}

test("editor_save_gate — clean → typing → reverted 3단이 머리·패턴·행에서 모두 산다", async () => {
  const stage = saveGateStage();
  const { value, report } = await runSolo(stage, "editor_save_gate", { Nav: { go: () => {} } });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.save_present, true);
  assert.equal(value.clean_disabled, true);
  assert.equal(value.typing_enabled, true, "타이핑 시점에 열린다(첫 클릭이 삼켜지지 않는다)");
  assert.equal(value.typing_discard_enabled, true, "버리기도 같은 술어");
  assert.equal(value.rerender_keeps_enabled, true);
  assert.equal(value.reverted_disabled, true);
  assert.equal(value.reverted_discard_disabled, true);
  assert.equal(value.pattern_present, true);
  assert.equal(value.pattern_typing_enabled, true);
  /* 행 거울 — 머리·꼬리만 세면 이 자리에서만 첫 클릭이 삼켜진다. */
  assert.equal(value.row_const_present, true);
  assert.equal(value.row_clean_disabled, true);
  assert.equal(value.row_typing_enabled, true);
  assert.equal(value.row_reverted_disabled, true);
  assert.equal(value.row_value_survives_push, true, "재구성이 친 값을 지우지 않는다");
  assert.equal(value.row_enabled_after_push, true);
  assert.equal(value.gone_control_disables, true, "없는 편집을 있다고 말하지 않는다");
  assert.equal(value.error, null);
});

test("editor_save_gate — 재구성이 친 값을 지우면 잡힌다(조용한 소실)", async () => {
  const stage = saveGateStage({ dropValueOnPush: true });
  const { value } = await runSolo(stage, "editor_save_gate", { Nav: { go: () => {} } });
  assert.equal(value.row_value_survives_push, false);
});

test("editor_save_gate — 사라진 자리의 대기가 남으면 gone_control_disables 가 뒤집힌다(음성)", async () => {
  const stage = saveGateStage({ keepGoneControl: true });
  const { value } = await runSolo(stage, "editor_save_gate", { Nav: { go: () => {} } });
  assert.equal(value.gone_control_disables, false);
});

/* ────────────────────── editor_lib_manage · editor_lib ────────────────────── */

function libStage(kind) {
  const stage = createStage();
  const host = stage.mk("#scr-editor");
  const menu = stage.mk("#tplRowMenu");
  menu.computed = { display: "none" };
  const move = stage.mk("#tplMoveModal", { classes: ["hidden"] });
  stage.mk("#tplMoveModal .modal-card");
  const menuItems = (names) => stage.set("button[data-menu]", names.map((n) => {
    const b = new El(stage, "button");
    b.dataset.menu = n;
    return b;
  }));
  const rowMore = (key, items) => {
    const b = new El(stage, "button");
    b.on.click = () => { menu.computed = { display: "block" }; menuItems(items); };
    stage.set(`[data-act="lib-more"][data-key="${key}"]`, [b]);
    return b;
  };
  stage.body.dispatchEvent = (ev) => {
    stage.events.push({ target: "body", type: ev.type });
    if (ev.type === "pointerdown") menu.computed = { display: "none" };
  };

  stage.onPush = (screen, snap) => {
    if (screen !== "editor") return;
    const lib = snap.library;
    const flat = lib.hwpx.flat;
    if (kind === "manage") {
      for (const a of ["import-template", "import-folder", "lib-new-txt", "lib-refresh"]) {
        stage.set(`button[data-act="${a}"]`, [new El(stage)]);
      }
      stage.set(".job-grp-head", flat ? [] : [new El(stage), new El(stage), new El(stage)]);
      stage.set(".libselrow", flat
        ? [new El(stage)]
        : [new El(stage), new El(stage), new El(stage), new El(stage)]);
      stage.set('[data-act="lib-more"]', flat ? [new El(stage)] : new Array(4).fill(0).map(() => new El(stage)));
      const grpMore = new El(stage, "button");
      grpMore.on.click = () => { menu.computed = { display: "block" }; menuItems(["grp-rename", "grp-disband"]); };
      stage.set(".grp-more", flat ? [] : [grpMore, new El(stage, "button")]);
      const assign = new El(stage, "button");
      assign.on.click = () => { move.classList.remove("hidden"); };
      stage.set('[data-act="lib-assign"]', flat ? [] : [assign, new El(stage)]);
      rowMore("b.hwpx", ["act:compile", "act:review", "move", "delete"]);
      rowMore("메모.txt", ["edit", "delete"]);
      const res = new El(stage);
      res.textContent = "검토: 문제 없음";
      res.className = "run-result ok";
      stage.set(".run-result", [res]);
      host.textContent = "빈 값 2건은 공란으로 채워집니다 · 4개 · C:/lib";
      return;
    }
    stage.set(".job-grp-head", flat ? [] : [new El(stage), new El(stage), new El(stage)]);
    stage.set(".libselrow", flat
      ? [new El(stage)]
      : [new El(stage), new El(stage), new El(stage)]);
    stage.set('.libselrow button[data-act="use-library"]', flat ? [new El(stage)] : [new El(stage), new El(stage)]);
    stage.set(".libselrow.cur", flat ? [] : [new El(stage)]);
    stage.set('button[data-act="import-template"]', [new El(stage)]);
    host.textContent = ".hwpx 문서 파일을 만드는 서식 · 복사해 쓰는 작업";
    const caret = new El(stage);
    caret.computed = { visibility: "visible" };
    stage.set('.job-grp-head[aria-expanded="false"] .grp-caret', flat ? [] : [caret]);
    const head0 = new El(stage);
    head0.id = "grp-입찰";
    if (!flat) stage.set(".job-grp-head", [head0, new El(stage), new El(stage)]);
    const fname = new El(stage);
    fname.computed = { textOverflow: "ellipsis", minWidth: "0px" };
    stage.set(".libselrow .fname", [fname]);
  };
  stage.move = move;
  stage.menu = menu;
  return stage;
}

test("editor_lib_manage — 그룹 구획·⋮ 3종·이동 다이얼로그·퇴화 평면", async () => {
  const stage = libStage("manage");
  const Modal = { close: (id) => { stage.move.classList.add("hidden"); stage.closed = id; } };
  const { value, report } = await runSolo(stage, "editor_lib_manage", { Nav: { go: () => {} }, Modal });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.deepEqual(value.toolbar, [true, true, true, true]);
  assert.equal(value.grp_heads, 3);
  assert.equal(value.rows_visible, 4, "접힌 그룹 행은 뷰에서 빠진다");
  assert.equal(value.row_more, 4);
  assert.equal(value.grp_more, 2, "그룹 ⋮ 는 이름 그룹에만");
  assert.equal(value.assign_chips, 2);
  assert.equal(value.fill_warn, true);
  assert.equal(value.result_line, true);
  assert.equal(value.band_caption, true);
  assert.equal(value.menu_shown, true);
  assert.deepEqual(value.hwpx_menu_items, ["act:compile", "act:review", "move", "delete"]);
  assert.equal(value.menu_closed, true);
  assert.deepEqual(value.txt_menu_items, ["edit", "delete"]);
  assert.deepEqual(value.group_menu_items, ["grp-rename", "grp-disband"]);
  /* 칩 → 이동 다이얼로그 두 극. */
  assert.equal(value.move_hidden_before, true);
  assert.equal(value.move_shown_after_chip, true);
  /* 퇴화 불변식 — 그룹 0개면 헤더 없는 평면. */
  assert.equal(value.flat_heads, 0);
  assert.equal(value.flat_rows, 1);
  assert.equal(value.error, null);
});

test("editor_lib — 선택 전용 그룹 구획과 퇴화 평면", async () => {
  const stage = libStage("pick");
  const { value, report } = await runSolo(stage, "editor_lib", { Nav: { go: () => {} } });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(value.grp_heads, 3);
  assert.equal(value.rows_visible, 3);
  assert.equal(value.pick_btns, 2, "현 선택은 버튼이 아니다");
  assert.equal(value.current_marked, 1);
  assert.equal(value.import_btn, true);
  assert.equal(value.filter_notice, true);
  assert.equal(value.caret_collapsed, "visible");
  assert.equal(value.grp_head_has_id, true);
  assert.equal(value.fname_ellipsis, "ellipsis");
  assert.equal(value.fname_minwidth, "0px");
  assert.equal(value.flat_heads, 0);
  assert.equal(value.flat_rows, 1);
  assert.equal(value.error, null);
});

/* ────────────────────── 실패는 조용하지 않다 ────────────────────── */

test("서비스 주입이 없으면 조용히 넘어가지 않는다", async () => {
  const cases = [
    ["view_order", /Bridge/],
    ["editor_guard", /Nav/],
    ["sheet_gate", /Bridge/],
    ["data_picker", /Nav/],
    ["workbench", /Nav/],
  ];
  for (const [name, pattern] of cases) {
    const stage = createStage();
    const { report } = await runSolo(stage, name, {});
    assert.equal(report.ok, false, name);
    const failure = report.errors.find((e) => e.probe === name);
    assert.match(failure.message, pattern, name);
    assert.equal(Object.prototype.hasOwnProperty.call(report.results, name), false, name);
  }
});

test("실패한 프로브의 키는 결과에 실리지 않는다 — 모양만 맞는 낡은 값 차단", async () => {
  const stage = createStage();                 // DOM 이 아예 없다
  const { report } = await runSolo(stage, "job_editmode", { Nav: { go: () => {} } });
  assert.equal(report.ok, false);
  assert.deepEqual(report.results, {});
  assert.equal(report.errors[0].probe, "job_editmode");
});

/* ────────────────────────── 음성 ────────────────────────── */

test("음성 — 전역 쓰기·전역 스태시·전역 조회·__hwpxTest 부재", () => {
  assert.equal(/(?:^|\s)window\.[A-Za-z_$][A-Za-z0-9_$]*\s*=/m.test(SRC), false);
  assert.equal(/globalThis\s*\.\s*[A-Za-z_$][A-Za-z0-9_$]*\s*=/.test(SRC), false);
  assert.equal(SRC.includes("__hwpxTest"), false);
  assert.equal(/window\.__/.test(SRC), false, "창 객체 위 스태시가 주석에도 남지 않는다");
  /* 제품 전역을 **읽지도** 않는다 — 전부 ctx 주입이다. */
  for (const name of [
    "Nav", "Bridge", "Modal", "SheetPicker", "DataPicker", "SurfaceSheet",
    "Intent", "Theme", "Personalization", "Popover",
  ]) {
    assert.equal(new RegExp(`(?<![.\\w])window\\.${name}\\b`).test(SRC), false, name);
    assert.equal(new RegExp(`(?<![.\\w])globalThis\\.${name}\\b`).test(SRC), false, name);
  }
  /* 유일한 import 는 형제 러너 하나다(제품 그래프에 닿지 않는다). */
  const imports = SRC.match(/^import\s[^\n]*from\s+"[^"]+"/gm) || [];
  assert.equal(imports.length, 1);
  assert.match(imports[0], /"\.\.\/runner\.js"/);
  /* 실렌더는 배포된 푸시 진입점(주입)으로만 몬다 — 전역 `__push` 조회가 아니다. */
  assert.ok(SRC.includes("ctx.push("));
});

test("bare import 는 순수하다 — DOM·리스너·전역을 만들지 않는다", async () => {
  const before = Object.keys(globalThis).length;
  const again = await import(
    `../../frontend/src/selftest/probes/editor_workbench_data.js?pure=${Date.now()}`
  );
  assert.equal(typeof again.createEditorWorkbenchDataProbes, "function");
  assert.equal(Object.keys(globalThis).length, before);
  assert.equal(typeof globalThis.document, "undefined");
  assert.equal(typeof globalThis.window, "undefined");
  /* factory 를 불러도 DOM 은 안 만진다 — 정의 데이터만 나온다. */
  const defs = again.createEditorWorkbenchDataProbes();
  assert.equal(defs.length, 15);
  for (const def of defs) {
    assert.equal(typeof def.name, "string");
    assert.equal(typeof def.run, "function");
    assert.equal(def.cluster, "D");
  }
});
