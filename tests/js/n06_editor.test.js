/* 편집기 화면 계약 — N-06 lane C 가 `frontend/js/screens/editor.js` 에 세운 여섯 경계를
 * R4-02 에서 React 후계 `frontend/src/screens/editor.ts` 로 **제자리 번역**했다.
 *
 * 지키는 경계:
 *  ① 공개 표면 4키(init·rerender·leaveTo·aimAt) — 몰입 표면의 문 손잡이 수는 계약이다.
 *     그 넷은 이제 controller 표면의 부분집합이고, 셸이 뽑아 가는 facade 가 딱 그 넷이다
 *     (`bootstrap.js` 의 `EditorScreen`). 넷 중 하나가 사라지면 셸이 실엔진에서야 죽는다.
 *  ② init 멱등·재시도(§7) — 재호출 시 배선 delta 0 을 **실측**한다(소스 call-site 수를
 *     기대값으로 쓰지 않는다). 첫 initial reject 후 명시적 재-init 이 initial 만 다시 당기고
 *     배선은 중복 설치하지 않는다. legacy 는 `wired` 가드였고 후계도 같은 가드다 — 셸의
 *     ready 사건이 재발화하면 init 이 다시 불리기 때문이다(`app.js` 의 주석이 그 계약).
 *  ③ 교차 화면 소비가 **late-bound 포트**인가 — 구성 뒤에 bind 한 구현이 호출 시점에 잡혀야
 *     한다(셸이 화면들을 순서대로 조립하므로 값 캡처는 평가 순서 함정이다). legacy 는
 *     `JobScreen { refreshList, openPreview }` 콜백 테이블이었고, 후계는 `ScreenPorts` 다.
 *  ④ landOn 발신 순서 — `navigation.refresh` 가 `navigation.go` 보다 먼저 서고
 *     `refreshed: true` 를 싣는다(재적재 전에 전환하면 사용자는 편집 전 규칙을 든 화면을
 *     손에 쥔다 — 8R P1).
 *  ⑤ 통로는 **객체째** — selftest 가 프로퍼티를 교체하므로 메서드 사전 추출이 없는지
 *     실행으로 확인한다. legacy 는 `Bridge.call`, 후계는 `client.dispatch` 다.
 *  ⑥ 음성: IIFE 래퍼 0 · 제품 전역 27종 `window.X` 0 · export 집합 · 화면 간 import 0.
 *
 * 런타임은 대역이 아니라 **실물**을 쓴다(`createScreenRuntime` + `createSnapshotStore`).
 * ② 가 재는 「initial 을 몇 번 당겼나」는 화면과 런타임이 함께 만드는 성질이라, 런타임을
 * 대역으로 갈면 그 초록이 대역의 성질이 된다. `Intent` 도 같은 이유로 실물이다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createEditorController } from "../../frontend/src/screens/editor.ts";
import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";
import { createScreenRuntime } from "../../frontend/src/screens/runtime.ts";
import { createSnapshotStore } from "../../frontend/src/state/store.ts";
import { Intent } from "../../frontend/js/intent.js";

const SRC_URL = new URL("../../frontend/src/screens/editor.ts", import.meta.url);
const src = readFileSync(SRC_URL, "utf8");

/** 셸이 뽑아 가는 facade 4키 — `bootstrap.js` 의 `EditorScreen` 과 같은 목록. */
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
  services.sheetPicker.bindReact({ choose: async () => null });
  const navigation = {
    refresh: async (target) => {
      trace.push(["navigation.refresh", target]);
      if (opts.refreshFails) throw new Error("stale disk");
    },
    go: (target, options) => { trace.push(["navigation.go", target, options]); },
  };
  const controller = createEditorController({
    doc: { getElementById: () => null, querySelector: () => null },
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

test("controller 는 셸 facade 4키(init·rerender·leaveTo·aimAt)를 전부 낸다", () => {
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

test("init 2회 — tpl 재당김 배선·initial 추가 등록 0, 같은 promise 공유", async () => {
  const h = harness();
  const first = h.controller.init();
  await first;
  assert.equal(h.counts.initial, 1, "initial 당김 1회");
  assert.equal(h.store.listenerCount("tpl"), 1, "tpl 채널 구독 1개(재당김 배선의 양성 대조)");

  const second = h.controller.init();
  assert.equal(second, first, "성공한 init 재호출은 같은 promise 를 공유한다");
  await second;
  await h.controller.init();
  assert.equal(h.counts.initial, 1, "initial 추가 당김 0");
  assert.equal(h.store.listenerCount("tpl"), 1, "tpl 구독 추가 등록 0");
});

test("tpl push 하나가 editor 재당김을 **한 번만** 태운다(중복 배선 음성 대조)", async () => {
  const h = harness();
  await h.controller.init();
  await h.controller.init();               // 셸 ready 재발화 형상
  const before = h.counts.initial;
  h.store.ingest("tpl", { groups: [] });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(h.counts.initial - before, 1,
    "tpl 구독이 겹치면 관리 동사 하나가 재당김을 여러 번 태운다");
});

test("동시 2회 init — 같은 초기화 promise, initial 1회", async () => {
  const h = harness();
  const first = h.controller.init();
  const second = h.controller.init();
  assert.equal(first, second);
  await Promise.all([first, second]);
  assert.equal(h.counts.initial, 1);
  assert.equal(h.store.listenerCount("tpl"), 1);
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

test("rerender — 재당김 하나를 태우고 tpl 배선을 다시 걸지 않는다", async () => {
  const h = harness();
  await h.controller.init();
  await h.controller.rerender();
  assert.equal(h.counts.initial, 2, "rerender 는 스냅샷을 다시 묻는다");
  assert.equal(h.store.listenerCount("tpl"), 1, "rerender 는 배선 자리가 아니다");
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
  h.ports.jobRead.bindReact({
    refreshList: () => { h.trace.push(["ports.refreshList"]); },
    openBrowseNeedsAction: async () => {},
  });
  h.ports.jobRun.bindReact({
    openPreview: async (request) => { h.trace.push(["ports.openPreview", request]); },
    attach: () => () => {},
  });
  h.ports.editorEntry.bindReact({
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
  h.ports.editorEntry.bindReact({
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

/* ---------------- ⑥ 음성 — 소스 텍스트 계약 ---------------- */

test("소스 음성: IIFE 0 · 제품 전역 27종 0 · export 집합 · 화면 간 import 0", () => {
  assert.ok(!src.includes("(function () {"), "IIFE 래퍼가 남아 있지 않다");
  assert.ok(!src.includes("})();"), "IIFE 닫힘이 남아 있지 않다");

  const GLOBALS = [
    "Bridge", "__push", "Nav", "AppCloseGuard",
    "JobScreen", "LibraryScreen", "EditorScreen", "WorkbenchScreen",
    "Copy", "escHtml", "Guard", "SegView", "Popover", "Preserve", "Intent",
    "UndoToast", "Modal", "SurfaceSheet", "GroupList", "Theme", "Personalization",
    "SheetPicker", "PathTrack", "Relink", "DataZone", "DataPicker", "EditorEntry",
  ];
  assert.equal(GLOBALS.length, 27, "제품 전역 목록은 27종");
  for (const name of GLOBALS) {
    assert.ok(!new RegExp(`(?:window|globalThis)\\.${name}\\b`).test(src),
      `window.${name} / globalThis.${name} 판독·대입 0`);
  }
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.equal(/\bwindow\./.test(code), false, "화면이 전역 window 를 만지지 않는다");
  assert.ok(/deps\.notify\(/.test(code), "loud 실패 통로(주입 notify) 보존");

  assert.ok(!/export\s+default/.test(src), "export default 금지");
  const names = [...src.matchAll(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  assert.deepEqual(names, ["createEditorController", "EditorScreen", "TxtEditDialog"],
    "값 export 는 controller 팩토리와 React producer 둘뿐");

  const targets = [...new Set([...src.matchAll(/from "([^"]+)"/g)].map((m) => m[1]))];
  assert.ok(targets.length > 0, "직접 ESM import 가 있다(양성 대조)");
  assert.deepEqual(targets, [
    "react", "../runtime/client.ts", "../ports/service_handoff.ts", "./ports.ts",
    "./runtime.ts", "./path_actions.ts", "./group_move_dialog.ts", "./editor_state.ts",
  ]);
  /* 화면 간 간선 0 — 다른 화면의 producer·controller 를 직접 부르지 않는다. 교차 소비는
     전부 `ScreenPorts` 를 지난다(③ 이 실행으로 잰다). */
  for (const forbidden of ["./job_read.ts", "./library.ts", "./data_picker.ts", "./workbench.ts"]) {
    assert.equal(targets.includes(forbidden), false, `화면 간 import 금지: ${forbidden}`);
  }
  assert.equal(targets.some((target) => /app\.js|bridge\.js/.test(target)), false,
    "셸·브리지 직접 import 금지");
});

test("음성 — 편집 변이는 전부 한 체인(EDIT_CHAIN)을 지나고 커밋은 먼저 정산한다", () => {
  assert.equal((src.match(/deps\.chain\.chained\(/g) || []).length, 2,
    "체인 진입점은 sendEdit·flushPendingEdits 둘 — 축별로 가르면 서로를 추월한다");
  assert.match(src, /return deps\.chain\.chained\(EDIT_CHAIN,/);
  /* 팩토리 스코프에서 통로 메서드를 값으로 뽑으면 프로퍼티 교체가 우회된다(⑤ 의 정적 짝). */
  assert.equal(/^ {2}const\s+\w+\s*=\s*deps\.client\.\w+/m.test(src), false,
    "`const x = deps.client.dispatch` 류 팩토리 스코프 캡처 금지");
});
