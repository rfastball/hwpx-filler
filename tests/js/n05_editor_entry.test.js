/* Editor-entry behavior: late-bound ports, guarded ordering, and focus lifetime. */
import test from "node:test";
import assert from "node:assert/strict";

import { createEditorEntry } from "../../frontend/src/screens/editor_entry.ts";

const SURFACE = [
  "confirmDiscard", "land", "newDraft", "newDraftFromData", "openGuarded", "restoreEntryFocus",
];

/** 진입 지점 대역 — 되돌림 대상을 id 로만 식별한다(초점 자체는 modal 포트가 진다). */
function focusTarget(id) {
  return { id };
}

/* 한 시나리오의 관측 하니스 — 통로는 **객체**로 넘기고, 흔적은 한 배열에 순서대로 쌓는다
   (순서가 계약이므로 호출별 카운터로는 부족하다). */
function harness(cfg) {
  const opts = cfg || {};
  const log = [];
  const notices = [];
  const doc = { activeElement: null };
  const client = {
    async invoke(method, ...args) {
      log.push([`client.${method}`, ...args]);
      if (method === "editor_has_unsaved_work") return { ok: true, value: opts.unsaved === true };
      if (method === "new_job_from_data") return { ok: true, value: opts.newJobResult ?? null };
      if (method === "open_job_in_editor") return { ok: true, value: opts.openResult ?? null };
      return { ok: true, value: null };
    },
    async dispatch(screen, action, payload) {
      log.push(["client.dispatch", screen, action, payload]);
      return { ok: true, value: {} };
    },
  };
  const modal = {
    async confirm(spec) {
      log.push(["modal.confirm", spec]);
      return Object.hasOwn(opts, "confirmResult") ? opts.confirmResult : true;
    },
    restoreFocus(target) { log.push(["modal.restoreFocus", target ? target.id : null]); },
  };
  const entry = createEditorEntry({
    doc, client, modal,
    navigate: (...args) => log.push(["navigate", ...args]),
    notify: (message) => notices.push(String(message)),
  });
  return { log, notices, doc, client, modal, entry, names: () => log.map((r) => r[0]) };
}

/* ================= 1. 공개 표면 ================= */

test("공개 표면 — createEditorEntry 는 계약 6키를 정확히 낸다", () => {
  assert.equal(typeof createEditorEntry, "function");
  const { entry } = harness();
  assert.deepEqual(Object.keys(entry).sort(), SURFACE);
  for (const key of Object.keys(entry)) assert.equal(typeof entry[key], "function", key);
});

/* ================= 2. navigate 는 late-bound ================= */

test("navigate — 생성 시점에 없던 대상도 호출 시점에 잡힌다(모듈 순환 절단의 근거)", () => {
  let Nav = null;                                   // 앱 셸은 아직 평가되지 않았다
  const seen = [];
  const entry = createEditorEntry({
    doc: { activeElement: null }, client: {}, modal: {},
    navigate: (...args) => Nav.go(...args), notify: () => {},
  });
  assert.throws(() => entry.land(), TypeError, "대상이 없으면 조용히 넘어가지 않는다");

  Nav = { go: (...args) => seen.push(["A", ...args]) };   // 셸이 뒤늦게 선다
  entry.land();
  Nav = { go: (...args) => seen.push(["B", ...args]) };   // 재배선도 다음 호출부터 보인다
  entry.land();
  assert.deepEqual(seen, [["A", "editor", { force: true }], ["B", "editor", { force: true }]]);
});

test("navigate — 착지 인자는 종전 Nav.go 그대로다(화면 · force)", () => {
  const h = harness();
  h.entry.land();
  assert.deepEqual(h.log, [["navigate", "editor", { force: true }]]);
});

/* ================= 4. 포트 프로퍼티 교체가 보인다(프로브 경로 생존) ================= */

test("포트 교체 — client 메서드를 갈아끼우면 seam 이 새 함수를 본다", async () => {
  const seen = [];
  const client = {
    async invoke(method, ...args) {
      if (method === "editor_has_unsaved_work") return { ok: true, value: false };
      seen.push(["A", ...args]);
      return { ok: true, value: null };
    },
  };
  const entry = createEditorEntry({
    doc: { activeElement: null }, client, modal: { restoreFocus() {} },
    navigate: () => {}, notify: () => {},
  });
  assert.equal(await entry.openGuarded("작업1", { entry_reason: "library" }), true);
  client.invoke = async (method, ...args) => {     // 프로브가 하는 일
    if (method === "editor_has_unsaved_work") return { ok: true, value: false };
    seen.push(["B", ...args]);
    return { ok: true, value: null };
  };
  assert.equal(await entry.openGuarded("작업2", { entry_reason: "library" }), true);
  assert.deepEqual(seen, [
    ["A", "작업1", { entry_reason: "library" }],
    ["B", "작업2", { entry_reason: "library" }],
  ]);
});

test("포트 교체 — 미저장 판정도 갈아끼운 client.invoke 를 본다(stale 금지)", async () => {
  const log = [];
  const client = { async invoke() { return { ok: true, value: false }; } };
  const entry = createEditorEntry({
    doc: { activeElement: null }, client,
    modal: { async confirm(spec) { log.push(spec); return false; }, restoreFocus() {} },
    navigate: () => {}, notify: () => {},
  });
  assert.equal(await entry.confirmDiscard("본문"), true, "미저장 없으면 조용히 통과");
  client.invoke = async () => ({ ok: true, value: true });
  assert.equal(await entry.confirmDiscard("본문"), false, "미저장이 생기면 다음 질의가 본다");
  assert.equal(log.length, 1);
});

test("음성 — new_session 폐기가 실패하면 착지하지 않고 사유를 재진술한다", async () => {
  const log = [];
  const notices = [];
  const entry = createEditorEntry({
    doc: { activeElement: null },
    client: {
      async invoke() { return { ok: true, value: false }; },
      async dispatch(...args) {
        log.push(args);
        return { ok: false, failure: { message: "세션을 비우지 못했습니다" } };
      },
    },
    modal: { async confirm() { return true; }, restoreFocus() {} },
    navigate: (...args) => log.push(["navigate", ...args]),
    notify: (message) => notices.push(String(message)),
  });
  assert.equal(await entry.newDraft(), false, "폐기 실패는 성공으로 보고하지 않는다");
  assert.equal(log.some((row) => row[0] === "navigate"), false, "실패 뒤 착지 0");
  assert.deepEqual(notices, ["editor/new_session: 세션을 비우지 못했습니다"]);
});

test("포트 실패는 삼키지 않는다 — 손상된 호스트 결과는 throw 로 올라온다", async () => {
  const entry = createEditorEntry({
    doc: { activeElement: null },
    client: { async invoke() { return { ok: false, failure: { message: "브리지 끊김" } }; } },
    modal: { restoreFocus() {} }, navigate: () => {}, notify: () => {},
  });
  await assert.rejects(() => entry.confirmDiscard("본문"), /브리지 끊김/,
    "미저장 질의 실패를 「미저장 없음」으로 강등하지 않는다");
});

/* ================= 5. 미저장 가드 — 확인을 거치고, 취소하면 안 움직인다 ================= */

test("가드 — 미저장이 없으면 확인 없이 통과한다(진입 셋 전부)", async () => {
  for (const [name, run] of [
    ["newDraft", (e) => e.newDraft()],
    ["newDraftFromData", (e) => e.newDraftFromData({ entry_reason: "x" })],
    ["openGuarded", (e) => e.openGuarded("작업", { entry_reason: "library" })],
  ]) {
    const h = harness({ unsaved: false });
    assert.equal(await run(h.entry), true, name);
    assert.equal(h.names().includes("modal.confirm"), false, `${name}: 미저장 없으면 안 묻는다`);
    assert.equal(h.names().at(-1), "navigate", `${name}: 착지한다`);
  }
});

test("가드 — 미저장이 있으면 확인을 거치고, 취소는 이동을 막는다(진입 셋 전부)", async () => {
  const CASES = [
    ["newDraft", (e) => e.newDraft(), "새 작업을 시작하면"],
    ["newDraftFromData", (e) => e.newDraftFromData({ entry_reason: "x" }), "이 데이터로 새 작업을 시작하면"],
    ["openGuarded", (e) => e.openGuarded("작업A", { entry_reason: "library" }), "'작업A' 편집을 열면"],
  ];
  for (const [name, run, lead] of CASES) {
    const h = harness({ unsaved: true, confirmResult: false });
    assert.equal(await run(h.entry), false, `${name}: 취소는 false 를 낸다`);
    const confirm = h.log.find((row) => row[0] === "modal.confirm")[1];
    assert.ok(confirm.body.startsWith(lead), `${name}: 문안이 그 흐름의 것이다`);
    assert.ok(confirm.body.includes("사라지는 것: 이름 · 데이터 · 매핑"), `${name}: 잃는 것을 말한다`);
    assert.equal(confirm.confirmLabel, "버리고 계속");
    assert.equal(confirm.cancelLabel, "취소");
    assert.equal(h.names().includes("navigate"), false, `${name}: 취소 뒤 이동 0`);
    assert.deepEqual(
      h.names().filter((n) => n.startsWith("client.") && n !== "client.editor_has_unsaved_work"),
      [], `${name}: 취소 뒤 백엔드 변이 0`);
    assert.deepEqual(h.notices, [], "취소는 실패가 아니다 — 통지 0");
  }
});

test("가드 — 수리 진입의 손실 목록은 데이터를 말하지 않는다(#878)", async () => {
  /* 문안이 실동작보다 넓게 파기를 말하면 사람은 지금 잃지 않을 것까지 저울질한다.
     데이터를 든 화면에서 온 수리 진입은 편집기의 데이터 칸을 비우지 않고 그 화면이 든
     것으로 갈아 끼운다 — 무엇이 실제로 인계되는지의 판정은 Python 몫이고, 여기서는 이
     seam 이 자기가 실어 보낼 진입 사유만 본다. */
  const h = harness({ unsaved: true, confirmResult: false });
  await h.entry.openGuarded("작업A", { entry_reason: "document_browser_repair" });
  const { body } = h.log.find((row) => row[0] === "modal.confirm")[1];
  assert.ok(body.startsWith("'작업A' 편집을 열면"), "흐름의 문안은 그대로다");
  assert.ok(body.includes("사라지는 것: 이름 · 매핑"), body);
  assert.ok(!body.includes("사라지는 것: 이름 · 데이터 · 매핑"), body);
  assert.ok(body.includes("데이터는 문서 만들기 화면에서 고른 것으로 바뀝니다."), body);

  // 음성 대조 — 다른 진입은 종전 목록 그대로다(데이터는 실제로 사라진다).
  const other = harness({ unsaved: true, confirmResult: false });
  await other.entry.openGuarded("작업A", { entry_reason: "library" });
  assert.ok(other.log.find((row) => row[0] === "modal.confirm")[1].body
    .includes("사라지는 것: 이름 · 데이터 · 매핑"));
});

test("가드 — 확인하면 백엔드가 돌고 착지한다", async () => {
  const h = harness({ unsaved: true, confirmResult: true });
  assert.equal(await h.entry.newDraft(), true);
  assert.deepEqual(h.log, [
    ["client.editor_has_unsaved_work"],
    ["modal.confirm", h.log[1][1]],
    ["client.dispatch", "editor", "new_session", {}],
    ["navigate", "editor", { force: true }],
  ]);
});

/* ================= 6. 이동 순서 — 가드 → 확인 → 이동 ================= */

test("순서 — openGuarded 는 가드 → 확인 → 로드 → 이동을 이 순서로 지난다", async () => {
  const h = harness({ unsaved: true, confirmResult: true });
  assert.equal(
    await h.entry.openGuarded("작업A", { entry_reason: "library", section: "filename" }), true);
  assert.deepEqual(h.names(),
    ["client.editor_has_unsaved_work", "modal.confirm", "client.open_job_in_editor", "navigate"]);
  // 단일 정의 seam 은 **인자까지 단일**이다 — 문맥이 여기서 새면 모든 진입이 자발적 진입으로
  // 떨어져 배너·복귀처가 통째로 사라진다.
  assert.deepEqual(h.log.find((row) => row[0] === "client.open_job_in_editor").slice(1),
    ["작업A", { entry_reason: "library", section: "filename" }]);
});

test("순서 — newDraftFromData 는 가드 → 확인 → 새 작업 → 이동, 문맥 부재는 {} 로", async () => {
  const h = harness({ unsaved: true, confirmResult: true });
  assert.equal(await h.entry.newDraftFromData(), true);
  assert.deepEqual(h.names(),
    ["client.editor_has_unsaved_work", "modal.confirm", "client.new_job_from_data", "navigate"]);
  assert.deepEqual(h.log.find((row) => row[0] === "client.new_job_from_data").slice(1), [{}]);
});

/* ================= 7. loud 실패 — 사유를 재진술한다 ================= */

test("loud — 진입 실패는 사유를 재진술하고 이동하지 않는다(조용한 삼킴 0)", async () => {
  for (const [name, run] of [
    ["openGuarded", (e) => e.openGuarded("작업A", { entry_reason: "library" })],
    ["newDraftFromData", (e) => e.newDraftFromData({ entry_reason: "x" })],
  ]) {
    const key = name === "openGuarded" ? "openResult" : "newJobResult";
    const h = harness({ unsaved: false, [key]: "ERROR: 템플릿 파일을 찾지 못했습니다.  " });
    assert.equal(await run(h.entry), false, `${name}: 실패는 false`);
    assert.deepEqual(h.notices, ["템플릿 파일을 찾지 못했습니다."],
      `${name}: 접두어를 벗기고 사유를 그대로 재진술한다`);
    assert.equal(h.names().includes("navigate"), false, `${name}: 실패 뒤 이동 0`);
  }
});

test("loud — ERROR 접두어가 없는 반환은 성공이다(정상 경로를 실패로 읽지 않는다)", async () => {
  const h = harness({ unsaved: false, openResult: { ok: true } });
  assert.equal(await h.entry.openGuarded("작업A", {}), true);
  assert.deepEqual(h.notices, []);
  assert.equal(h.names().at(-1), "navigate");
});

/* ================= 8. 초점 되돌림 — 1슬롯 왕복 ================= */

test("초점 — 취소 뒤 restoreEntryFocus 가 진입 지점으로 되돌린다", async () => {
  const h = harness({ unsaved: true, confirmResult: false });
  h.doc.activeElement = focusTarget("btn-entry");
  assert.equal(await h.entry.openGuarded("작업A", {}), false);
  h.doc.activeElement = focusTarget("elsewhere");   // 모달이 자리를 옮겨 놓은 뒤
  h.entry.restoreEntryFocus();
  assert.deepEqual(h.log.filter((row) => row[0] === "modal.restoreFocus"),
    [["modal.restoreFocus", "btn-entry"]]);
});

test("초점 — 실패 뒤에도 되돌릴 자리가 남아 있다", async () => {
  const h = harness({ unsaved: false, openResult: "ERROR: 손상" });
  h.doc.activeElement = focusTarget("btn-repair");
  assert.equal(await h.entry.openGuarded("작업A", {}), false);
  h.entry.restoreEntryFocus();
  assert.deepEqual(h.log.filter((row) => row[0] === "modal.restoreFocus"),
    [["modal.restoreFocus", "btn-repair"]]);
});

test("초점 — 1슬롯이라 두 번 되돌리면 두 번째는 빈손이다(옛 자리 재사용 금지)", async () => {
  const h = harness({ unsaved: false });
  h.doc.activeElement = focusTarget("btn-A");
  await h.entry.newDraft();
  h.entry.restoreEntryFocus();
  h.entry.restoreEntryFocus();
  assert.deepEqual(h.log.filter((row) => row[0] === "modal.restoreFocus"),
    [["modal.restoreFocus", "btn-A"], ["modal.restoreFocus", null]]);
});

test("초점 — 새 진입이 슬롯을 덮어쓴다(마지막 문 하나만 기억)", async () => {
  const h = harness({ unsaved: false });
  h.doc.activeElement = focusTarget("btn-A");
  await h.entry.openGuarded("A", {});
  h.doc.activeElement = focusTarget("btn-B");
  await h.entry.openGuarded("B", {});
  h.entry.restoreEntryFocus();
  assert.deepEqual(h.log.filter((row) => row[0] === "modal.restoreFocus"),
    [["modal.restoreFocus", "btn-B"]]);
});

/* ================= 9. 팩토리 독립성 ================= */

test("팩토리를 두 번 부르면 진입 슬롯도 따로 산다(중앙은 1회만 부른다)", async () => {
  const log = [];
  const doc = { activeElement: null };
  const deps = {
    doc,
    client: { async invoke() { return { ok: true, value: false }; }, async dispatch() { return { ok: true, value: {} }; } },
    modal: {
      async confirm() { return true; },
      restoreFocus(target) { log.push(target ? target.id : null); },
    },
    navigate: () => {}, notify: () => {},
  };
  const a = createEditorEntry(deps);
  const b = createEditorEntry(deps);
  assert.notEqual(a, b);
  doc.activeElement = focusTarget("btn-A");
  await a.newDraft();
  b.restoreEntryFocus();                       // b 는 자기 슬롯이 비어 있다
  a.restoreEntryFocus();
  assert.deepEqual(log, [null, "btn-A"]);
});
