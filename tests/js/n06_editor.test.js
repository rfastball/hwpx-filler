/* Editor controller behavior: retries, late-bound ports, ordering, and draft races. */
import test from "node:test";
import assert from "node:assert/strict";

import { createEditorController } from "../../frontend/src/screens/editor.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";
import { createScreenRuntime } from "../../frontend/src/screens/runtime.ts";
import { createSnapshotStore } from "../../frontend/src/state/store.ts";
import {
  NAME_FIELD,
  PATTERN_FIELD,
  emptyDraft,
  fieldError,
  hasInFlight,
  ingestSnapshot,
  issueToken,
  markField,
  settle,
  typeInto,
  valueOf,
} from "../../frontend/src/screens/editor_state.ts";
import { Intent } from "../../frontend/js/intent.js";

/** 셸이 직접 쓰는 controller 핵심 4키. */
const SHELL_FACADE = ["init", "rerender", "leaveTo", "aimAt"];

/* 렌더가 통과할 최소 스냅샷 — 신규 초안 1단계(라이브러리 빈 밴드). */
function snap(extra) {
  return Object.assign({
    section: "template",
    sections: ["template", "binding", "filename"],
    name: "테스트 작업",
    library: {},
    rows: [],
  }, extra || {});
}

function harness(cfg) {
  const opts = cfg || {};
  const trace = [];
  const notices = [];
  const counts = { initial: 0 };
  const client = {
    async initial(screen) {
      counts.initial += 1;
      trace.push(["initial", screen]);
      const value = await (opts.initial || (async () => snap()))(screen);
      return { ok: true, value };
    },
    async dispatch(screen, action, payload) {
      trace.push(["dispatch", screen, action, payload]);
      const value = opts.call ? await opts.call(screen, action, payload) : {};
      return { ok: true, value };
    },
    async invoke(method, ...args) {
      trace.push(["invoke", method, ...args]);
      const value = opts.invoke ? await opts.invoke(method, ...args) : null;
      return { ok: true, value };
    },
  };
  const store = createSnapshotStore({ alarm: assert.fail });
  const runtime = createScreenRuntime({ client, store });
  const ports = createScreenPorts();
  const services = createServiceHandoffPorts();
  services.sheetPicker.bind({ choose: async () => null });
  const navigation = {
    refresh: async (target) => {
      trace.push(["navigation.refresh", target]);
      if (opts.refreshFails) throw new Error("stale disk");
    },
    go: (target, options) => { trace.push(["navigation.go", target, options]); },
  };
  const controller = createEditorController({
    doc: opts.doc || { getElementById: () => null, querySelector: () => null },
    runtime, client, ports, services,
    modal: {
      confirm: async (spec) => { trace.push(["modal.confirm", spec]); return opts.confirm?.(spec) ?? false; },
      prompt: async () => null,
      choose: async (spec) => { trace.push(["modal.choose", spec]); return opts.choose?.(spec) ?? null; },
      open() {}, close() {},
    },
    undo: { show() {} },
    popover: { wireDismiss: () => () => {} },
    rowMenu: { show() {}, hide() {} },
    groupMove: { open() {} },
    chain: Intent,
    navigation,
    notify: (message) => notices.push(String(message)),
  });
  return {
    controller, client, store, runtime, ports, services, navigation, trace, notices, counts,
    names: () => trace.map((row) => row[0]),
  };
}

/* ---------------- ① 공개 표면 ---------------- */

test("controller 는 핵심 4키(init·rerender·leaveTo·aimAt)를 전부 낸다", () => {
  assert.equal(typeof createEditorController, "function");
  const { controller } = harness();
  for (const key of SHELL_FACADE) {
    assert.equal(typeof controller[key], "function", `${key} 는 함수여야 한다`);
  }
  /* 셸이 부르는 이름이 controller 표면 안에 실재하는지까지 본다 — facade 조립은
     `bootstrap.test.js` 가 별도로 재고, 여기서는 그 조립이 가리킬 자리가 있는지를 잰다. */
  const keys = Object.keys(controller);
  assert.deepEqual(SHELL_FACADE.filter((key) => keys.includes(key)), SHELL_FACADE);
});

/* ---------------- ② init 멱등 — 등록 delta 실측 ---------------- */

test("init 2회 — initial 추가 등록 0, 같은 promise 공유", async () => {
  const h = harness();
  const first = h.controller.init();
  await first;
  assert.equal(h.counts.initial, 1, "initial 당김 1회");
  assert.equal(h.store.listenerCount("tpl"), 0, "tpl 교차 구독 0");

  const second = h.controller.init();
  assert.equal(second, first, "성공한 init 재호출은 같은 promise 를 공유한다");
  await second;
  await h.controller.init();
  assert.equal(h.counts.initial, 1, "initial 추가 당김 0");
  assert.equal(h.store.listenerCount("tpl"), 0, "tpl 구독 재유입 0");
});

test("tpl 관리 동사 완료가 editor 재당김을 정확히 한 번 태운다", async () => {
  const h = harness();
  await h.controller.init();
  await h.controller.init();               // 셸 ready 재발화 형상
  const before = h.counts.initial;
  await h.controller.refreshLibrary();
  assert.equal(h.counts.initial - before, 1,
    "교차 push 구독 없이 원인 동사 완료가 재당김 하나를 소유한다");
  assert.equal(h.store.listenerCount("tpl"), 0);
});

test("동시 2회 init — 같은 초기화 promise, initial 1회", async () => {
  const h = harness();
  const first = h.controller.init();
  const second = h.controller.init();
  assert.equal(first, second);
  await Promise.all([first, second]);
  assert.equal(h.counts.initial, 1);
  assert.equal(h.store.listenerCount("tpl"), 0);
});

test("첫 initial reject — 실패는 전파되고, 명시적 재-init 이 initial 만 다시 당긴다", async () => {
  let fail = true;
  const h = harness({
    initial: async () => {
      if (fail) throw new Error("boot fail");
      return snap();
    },
  });

  await assert.rejects(h.controller.init(), /boot fail/, "rejection 은 호출자에게 전파된다");
  assert.equal(h.counts.initial, 1);
  const afterFail = h.store.listenerCount("tpl");

  fail = false;
  await h.controller.init();   // 회복 — 스스로 재시도하지 않고 명시적 호출이 다시 당긴다
  assert.equal(h.counts.initial, 2, "재-init 이 initial 을 다시 당겼다");
  assert.equal(h.store.listenerCount("tpl"), afterFail, "tpl 구독 중복 설치 0");
});

test("rerender — 재당김 하나를 태우고 tpl 구독을 만들지 않는다", async () => {
  const h = harness();
  await h.controller.init();
  await h.controller.rerender();
  assert.equal(h.counts.initial, 2, "rerender 는 스냅샷을 다시 묻는다");
  assert.equal(h.store.listenerCount("tpl"), 0, "rerender 는 교차 구독을 만들지 않는다");
});

test("저장은 blur 없는 이름 draft를 set_name 뒤에 정산한다", async () => {
  const h = harness({
    initial: async () => snap({
      section: "binding", sections: ["template", "binding"], name: "", is_draft: true,
    }),
    call: async (_screen, action) => (
      action === "save" ? { ok: false, block_reason: "저장 게이트 대역" } : {}
    ),
  });
  await h.controller.init();

  h.controller.type(NAME_FIELD, "발주요청 기안");
  await h.controller.doSave({});

  const edits = h.trace
    .filter((row) => row[0] === "dispatch" && row[1] === "editor")
    .map((row) => [row[2], row[3]]);
  assert.deepEqual(edits, [
    ["set_name", { name: "발주요청 기안" }],
    ["save", {}],
  ], "버튼이 blur보다 먼저 와도 이름 변경이 저장 판정보다 먼저 착지해야 한다");
});

/* ---------------- ③④ 교차 포트·landOn 순서 ---------------- */

test("저장하고 나가기 — refreshList 관측, refresh→go(refreshed:true), openPreview 복귀, late-binding", async () => {
  const h = harness({
    initial: async () => snap({
      dirty: true,
      context: {
        entry_reason: "preview_result",
        target: "binding/납품기한",
        return_context: { surface: "preview", reopen_drawer: true, preview_index: 2 },
      },
    }),
    call: async (_screen, action) => (action === "save" ? { ok: true } : {}),
    choose: () => "save",
  });
  await h.controller.init();

  /* late-binding: 구성·init **뒤에** 포트를 채운다 — 호출 시점에 잡혀야 한다. */
  h.ports.jobRead.bind({
    refreshList: () => { h.trace.push(["ports.refreshList"]); },
    openBrowseNeedsAction: async () => {},
  });
  h.ports.jobRun.bind({
    openPreview: async (request) => { h.trace.push(["ports.openPreview", request]); },
    attach: () => () => {},
  });
  h.ports.editorEntry.bind({
    openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {}, confirmDiscard: async () => true,
    restoreEntryFocus: () => { h.trace.push(["ports.restoreEntryFocus"]); },
  });

  await h.controller.leaveTo("job");

  const names = h.names();
  const iSave = h.trace.findIndex((row) => row[0] === "dispatch" && row[2] === "save");
  assert.ok(iSave >= 0, "save 발신이 있었다");
  assert.ok(names.includes("ports.refreshList"), "저장 성공 시 refreshList 호출");
  assert.ok(names.indexOf("ports.refreshList") > iSave, "refreshList 는 저장 성공 뒤에 온다");

  const iRefresh = names.indexOf("navigation.refresh");
  const iGo = names.indexOf("navigation.go");
  assert.ok(iRefresh >= 0 && iGo >= 0, "refresh·go 둘 다 발화");
  assert.ok(iRefresh < iGo, "landOn 순서: refresh 가 go 보다 먼저(8R P1)");
  assert.equal(h.trace[iGo][1], "job");
  assert.deepEqual(h.trace[iGo][2], { force: true, refreshed: true });

  assert.ok(names.indexOf("ports.restoreEntryFocus") > iGo, "착지 뒤 진입 초점 복원");

  const iPreview = names.indexOf("ports.openPreview");
  assert.ok(iPreview > iGo, "미리보기 복귀는 착지 뒤");
  assert.deepEqual(h.trace[iPreview][1], { at: 2, focusTarget: "binding/납품기한" },
    "같은 previewIndex·행 정체성(context.target)을 나른다");
});

test("navigation.refresh 실패 — 나가지 않는다(loud 통지, go 0회)", async () => {
  const h = harness({
    initial: async () => snap({ dirty: false, is_draft: false }),
    refreshFails: true,
  });
  h.ports.editorEntry.bind({
    openGuarded() {}, newDraft() {}, newDraftFromData() {}, land() {},
    confirmDiscard: async () => true, restoreEntryFocus() {},
  });
  await h.controller.init();

  await h.controller.leaveTo("job");
  assert.equal(h.names().includes("navigation.go"), false, "재적재 실패 시 전환하지 않는다");
  assert.ok(h.notices.some((message) => message.includes("머무릅니다")),
    "실패를 시끄럽게 재진술한다");
});

test("이탈 3택의 stay 는 draft 를 파기하지 않고 붙잡는다(확인 전 파기 금지 음성)", async () => {
  const h = harness({
    initial: async () => snap({ dirty: true, is_draft: false }),
    choose: () => "stay",
  });
  await h.controller.init();
  await h.controller.leaveTo("job");
  const actions = h.trace.filter((row) => row[0] === "dispatch").map((row) => row[2]);
  assert.equal(actions.includes("discard_patch"), false, "머무르기가 patch 를 버리지 않는다");
  assert.equal(actions.includes("save"), false);
  assert.equal(h.names().includes("navigation.go"), false, "stay 는 이동 0");
});

/* ---------------- ⑤ 통로는 객체째 ---------------- */

test("client.dispatch 프로퍼티 교체가 관측된다 — 메서드 사전 추출 없음", async () => {
  const h = harness();
  await h.controller.init();

  const seen = [];
  h.client.dispatch = async (screen, action, payload) => {
    seen.push([screen, action, payload]);
    return { ok: true, value: {} };
  };
  await h.controller.refreshLibrary();   // Bridge.call("tpl","refresh",{}) 직행의 후계
  assert.deepEqual(seen, [["tpl", "refresh", {}]], "교체된 client.dispatch 가 호출을 받았다");
});

/* ---------------- local draft reducer ---------------- */

const DRAFT_SESSION = "job:작업A";

function draft(values, revision = 1) {
  return ingestSnapshot(emptyDraft(), { session: DRAFT_SESSION, revision, values });
}

test("push는 편집 중인 field를 보존하고 손대지 않은 이웃만 갱신한다", () => {
  const protect = [
    (state) => typeInto(state, NAME_FIELD, "내 값"),
    (state) => markField(state, NAME_FIELD, { focused: true }),
    (state) => markField(state, NAME_FIELD, { composing: true }),
  ];
  for (const prepare of protect) {
    let state = prepare(draft({ [NAME_FIELD]: "옛 값", [PATTERN_FIELD]: "옛 규칙" }));
    const held = valueOf(state, NAME_FIELD);
    state = ingestSnapshot(state, {
      session: DRAFT_SESSION,
      revision: 2,
      values: { [NAME_FIELD]: "서버 값", [PATTERN_FIELD]: "새 규칙" },
    });
    assert.equal(valueOf(state, NAME_FIELD), held);
    assert.equal(valueOf(state, PATTERN_FIELD), "새 규칙");
  }
});

test("token/session이 낡은 응답은 draft를 바꾸지 않고 stale로 관측된다", () => {
  let state = typeInto(draft({ [NAME_FIELD]: "서버" }), NAME_FIELD, "첫 편집");
  const first = issueToken(state, NAME_FIELD);
  state = typeInto(first.state, NAME_FIELD, "둘째 편집");
  const second = issueToken(state, NAME_FIELD);
  const late = settle(second.state, {
    ok: true,
    session: DRAFT_SESSION,
    token: first.token,
    key: NAME_FIELD,
    serverValue: "첫 편집",
  });
  assert.equal(valueOf(late, NAME_FIELD), "둘째 편집");
  assert.equal(late.fields[NAME_FIELD].pendingToken, second.token);
  assert.equal(late.staleResponses, 1);

  const moved = ingestSnapshot(late, {
    session: "job:작업B",
    revision: 1,
    values: { [NAME_FIELD]: "B" },
  });
  assert.equal(valueOf(moved, NAME_FIELD), "B");
  assert.equal(moved.staleResponses, 0);
});

test("성공은 Python 확인값이 draft와 같을 때만 clean으로 승격한다", () => {
  let state = typeInto(draft({ [NAME_FIELD]: "서버" }), NAME_FIELD, "새 이름");
  const issued = issueToken(state, NAME_FIELD);
  assert.equal(hasInFlight(issued.state), true);

  const unconfirmed = settle(issued.state, {
    ok: true,
    session: DRAFT_SESSION,
    token: issued.token,
    key: NAME_FIELD,
  });
  assert.equal(unconfirmed.fields[NAME_FIELD].dirty, true);

  const confirmed = settle(issued.state, {
    ok: true,
    session: DRAFT_SESSION,
    token: issued.token,
    key: NAME_FIELD,
    serverValue: "새 이름",
  });
  assert.equal(confirmed.fields[NAME_FIELD].dirty, false);
  assert.equal(valueOf(confirmed, NAME_FIELD), "새 이름");
  assert.equal(hasInFlight(confirmed), false);

  const failed = settle(issued.state, {
    ok: false,
    session: DRAFT_SESSION,
    token: issued.token,
    key: NAME_FIELD,
    error: "이름 중복",
  });
  assert.equal(fieldError(failed, NAME_FIELD), "이름 중복");
  assert.equal(valueOf(failed, NAME_FIELD), "새 이름");
});

/* ---------------- 겨눔은 행이 설 때까지 살아 있는다 ---------------- */

test("겨눔 요청은 그 행이 실제로 렌더될 때까지 살아 있는다", async () => {
  // 진입 성사 직후에는 매핑 표가 아직 DOM 에 없다(렌더는 다음 틱이다). 그 순간 한 번 겨누고
  // 요청을 버리면 초점은 **영영** 서지 않는다 — 행은 나중에 생기는데 아무도 다시 겨누지 않는다.
  // 실측으로 SX-05 actual shell 이 여기서 20s 시한으로 죽었다: 행은 있고 초점만 없었다.
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const focused = [];
    let row = null; // 아직 렌더 전
    const rowSelector = '#editor-body table.map tr[data-field="추가확인"]';
    const doc = {
      getElementById: () => null,
      querySelector: (selector) => (selector === rowSelector ? row : null),
      activeElement: null,
    };
    const h = harness({
      initial: async () => snap({ context: { target: "binding/추가확인" } }),
      doc,
    });
    await h.controller.init();

    h.controller.aimAt("binding/추가확인");
    assert.deepEqual(focused, [], "없는 행에 가짜 초점을 세우지 않는다");

    const select = { focus() { focused.push("row-source"); doc.activeElement = select; } };
    row = { scrollIntoView() {}, querySelector: () => select };
    h.controller.consumeAim(); // 행이 선 렌더

    assert.deepEqual(focused, ["row-source"], "행이 선 뒤에도 겨누지 않으면 초점은 영영 안 선다");
  } finally {
    globalThis.CSS = previous;
  }
});

test("겨눔은 성사되면 소비된다 — 나중 렌더가 남의 행을 다시 낚아채지 않는다", async () => {
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const focused = [];
    const doc = { getElementById: () => null, querySelector: () => null, activeElement: null };
    const select = { focus() { focused.push("row-source"); doc.activeElement = select; } };
    const row = { scrollIntoView() {}, querySelector: () => select };
    doc.querySelector = () => row;
    const h = harness({
      initial: async () => snap({ context: { target: "binding/추가확인" } }),
      doc,
    });
    await h.controller.init();

    h.controller.aimAt("binding/추가확인");
    assert.deepEqual(focused, ["row-source"]);
    h.controller.consumeAim();
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source"], "한 번 선 초점을 매 렌더 다시 빼앗지 않는다");
  } finally {
    globalThis.CSS = previous;
  }
});

test("#789 진입 문맥이 지목한 자리를 보낸 화면의 호출 없이 스스로 겨눈다", async () => {
  // 종전에는 보낸 화면이 port 너머로 `aimAt` 을 불러 주기를 기다렸는데, 그 메서드는
  // `EditorEntryPort` 표면에 **없었다**. `typeof` 확인에 걸려 조용히 지나갔고, 그래서
  // deep-link 초점은 한 번도 선 적이 없다. 문맥은 이미 목표를 담아 여기 도착한다.
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const focused = [];
    const doc = { getElementById: () => null, querySelector: () => row, activeElement: null };
    const select = { focus() { focused.push("row-source"); doc.activeElement = select; } };
    const row = { scrollIntoView() {}, querySelector: () => select };
    doc.querySelector = () => row;
    const h = harness({
      initial: async () => snap({ context: { target: "binding/추가확인" } }),
      doc,
    });
    await h.controller.init();

    h.controller.consumeAim(); // 렌더 훅 — 바깥에서 aimAt 을 부른 적이 없다

    assert.deepEqual(focused, ["row-source"]);
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source"], "문맥당 한 번만 겨눈다");
  } finally {
    globalThis.CSS = previous;
  }
});

test("#789 문맥이 없으면 겨누지 않고, 떠났다 다시 들어오면 또 겨눈다", async () => {
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const focused = [];
    const doc = { getElementById: () => null, querySelector: () => null, activeElement: null };
    const select = { focus() { focused.push("row-source"); doc.activeElement = select; } };
    const row = { scrollIntoView() {}, querySelector: () => select };
    doc.querySelector = () => row;
    let context = {};
    const h = harness({ initial: async () => snap({ context }), doc });
    await h.controller.init();
    h.controller.consumeAim();
    assert.deepEqual(focused, [], "겨눌 자리를 안 지목한 진입은 초점을 옮기지 않는다");

    // 같은 자리로 **다시** 들어오면 그때도 겨눠야 한다. 문맥이 사라진 렌더가 기억을 비우므로
    // 두 번째 진입이 조용히 안 서는 일이 없다.
    context = { target: "binding/추가확인" };
    h.store.ingest("editor", snap({ context }));
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source"]);

    context = {};
    h.store.ingest("editor", snap({ context }));
    h.controller.consumeAim(); // 편집기를 떠났다 — 기억이 비워진다

    context = { target: "binding/추가확인" };
    h.store.ingest("editor", snap({ context }));
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source", "row-source"], "두 번째 진입부터 조용히 안 섭니다");
  } finally {
    globalThis.CSS = previous;
  }
});

test("#791 초점이 실제로 안 옮겨졌으면 성사로 치지 않고 다음 렌더가 다시 시도한다", async () => {
  // 요소가 **있다**는 것과 초점이 **섰다**는 것은 다르다. 비활성·숨김·전이 중이면 `focus()` 는
  // 조용한 no-op 다. 존재만 보고 성사했다고 답하면 조준은 「했다」고 말하면서 초점은 아무 데도
  // 안 서고, 그 거짓 성공이 재시도까지 막는다 — 실측으로 SX-05 가 정확히 그 상태였다.
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const attempts = [];
    let focusable = false;
    const doc = { getElementById: () => null, querySelector: () => null, activeElement: null };
    const select = {
      focus() {
        attempts.push("try");
        if (focusable) doc.activeElement = select; // 비활성 요소의 focus() 는 조용한 no-op
      },
    };
    const row = { scrollIntoView() {}, querySelector: () => select };
    doc.querySelector = () => row;
    const h = harness({
      initial: async () => snap({ context: { target: "binding/추가확인" } }),
      doc,
    });
    await h.controller.init();

    h.controller.consumeAim(); // 아직 초점을 못 받는 상태
    assert.equal(attempts.length, 1);
    assert.equal(doc.activeElement, null);

    focusable = true; // 다음 렌더에서 활성화됐다
    h.controller.consumeAim();
    assert.equal(doc.activeElement, select, "거짓 성공이 재시도를 막았습니다");
    assert.equal(attempts.length, 2);

    h.controller.consumeAim();
    assert.equal(attempts.length, 2, "성사한 뒤에는 매 렌더 다시 겨누지 않는다");
  } finally {
    globalThis.CSS = previous;
  }
});

test("#793 리렌더가 초점을 떨어뜨리면 지목한 자리를 다시 세운다", async () => {
  // 조준이 성사한 뒤에도 리렌더가 그 노드를 갈아 끼우면 초점이 조용히 `body` 로 떨어지고,
  // 그 틈을 면 닫힘의 대안 착지가 화면 루트로 채운다 — 그러면 사용자가 지목한 자리는 영영
  // 비어 있다. 실측으로 SX-05 의 focus 사건이 정확히 ['SELECT', 'SECTION#scr-editor'] 였다.
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const focused = [];
    const screenRoot = { id: "scr-editor" };
    const doc = {
      getElementById: () => null,
      body: { id: "body" },
      activeElement: null,
      querySelector: (selector) => (String(selector) === ".scr.on" ? screenRoot : row),
    };
    const select = { focus() { focused.push("row-source"); doc.activeElement = select; } };
    const row = { scrollIntoView() {}, querySelector: () => select };
    const h = harness({
      initial: async () => snap({ context: { target: "binding/추가확인" } }),
      doc,
    });
    await h.controller.init();

    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source"]);

    // 면 닫힘의 대안 착지가 화면 루트를 잡았다(사용자가 고른 자리가 아니다).
    doc.activeElement = screenRoot;
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source", "row-source"], "지목한 자리가 비어 있는 채 끝났습니다");

    // 이제는 우리 자리가 잡고 있으므로 매 렌더 다시 겨누지 않는다.
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source", "row-source"]);
  } finally {
    globalThis.CSS = previous;
  }
});

test("#793 사용자가 스스로 옮긴 초점은 빼앗지 않는다", async () => {
  const previous = globalThis.CSS;
  globalThis.CSS = { escape: (value) => value };
  try {
    const focused = [];
    const screenRoot = { id: "scr-editor" };
    const doc = {
      getElementById: () => null,
      body: { id: "body" },
      activeElement: null,
      querySelector: (selector) => (String(selector) === ".scr.on" ? screenRoot : row),
    };
    const select = { focus() { focused.push("row-source"); doc.activeElement = select; } };
    const row = { scrollIntoView() {}, querySelector: () => select };
    const h = harness({
      initial: async () => snap({ context: { target: "binding/추가확인" } }),
      doc,
    });
    await h.controller.init();
    h.controller.consumeAim();

    // 사용자가 다른 입력칸으로 갔다 — 여기서 되돌리면 남의 손을 잡아채는 것이다.
    doc.activeElement = { id: "editorName" };
    h.controller.consumeAim();
    assert.deepEqual(focused, ["row-source"]);
  } finally {
    globalThis.CSS = previous;
  }
});
