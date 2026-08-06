/* 편집 진입 seam 계약 테스트 — N-05 가 `frontend/js/editor_entry.js` 에 세운 경계 넷을
 * R4-02 에서 React 후계 `frontend/src/screens/editor_entry.ts` 로 **제자리 번역**했다.
 *
 * 묻는 것은 하나도 안 바뀐다. 바뀐 것은 **관측면**뿐이다:
 *
 *  ① 공개 표면 6키(§1-B 표) — 진입문은 하나이고 그 문의 손잡이 수는 계약이다. 이제 그
 *     6키는 `EditorEntryPort` 의 형이기도 하다(`screens/ports.ts`).
 *  ② 의존이 드러나 있는가 — legacy 는 `Modal` 을 **import 간선**으로 들었다. React 후계는
 *     `modal` 포트를 **주입**받는다: 확인 UI 의 구현이 어느 쪽이든 이 seam 은 판정만 쥔다.
 *     `navigate` 가 late-bound 콜백이어야 하는 이유는 그대로다 — 착지처 `Nav` 를 만드는 앱
 *     셸은 이 모듈보다 나중에 서고 셸 자신이 이 seam 을 소비하므로, 값으로 캡처하면 모듈
 *     순환과 평가 순서 함정이 동시에 선다. 소스에 전역이 없다는 정적 단언만으로는 값 캡처를
 *     못 보므로 실행으로 못박는다.
 *  ③ 포트가 **객체째** 살아 있는가 — selftest 프로브는 통로 객체의 프로퍼티를 갈아끼운다.
 *     legacy 에선 `bridge.call`, 지금은 `client.invoke`·`client.dispatch` 다. 메서드를 팩토리
 *     스코프 값으로 뽑으면 스텁이 우회돼 프로브가 실물 백엔드로 샌다 — 초록불인 채로.
 *  ④ 제품 규칙(가드 → 확인 → 이동 순서 · 미저장 가드 · 초점 되돌림 1슬롯 · loud 실패)이
 *     전환으로 흔들리지 않았는가. 이건 "번들이 뜬다"로는 못 보는 층이라 흔적을 기록해 센다.
 *
 * 대역이 가벼워졌다: legacy 는 `modal.js → popover.js` 그래프가 **평가 시점에 document 를
 * 만져서** 전역 DOM 대역을 깔고 동적 import 로 열어야 했다. React 후계의 의존은 전부 주입
 * 인자라 `doc` 도 `{ activeElement }` 한 칸이면 된다 — 그 축소 자체가 ② 의 증거다.
 *
 * loud 실패의 통로도 옮겨졌다: legacy 는 `window.alert` 를 직접 불렀고, 후계는 주입된
 * `notify` 를 부른다(합성 루트가 `window.alert` 로 잇는다). 사유를 재진술한다는 계약은 같다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createEditorEntry } from "../../frontend/src/screens/editor_entry.ts";

const SRC_URL = new URL("../../frontend/src/screens/editor_entry.ts", import.meta.url);
const src = readFileSync(SRC_URL, "utf8");

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

test("파일당 값 export 는 하나 — export default 없음", () => {
  assert.equal(/export\s+default/.test(src), false, "export default 금지");
  const names = [...src.matchAll(/^export\s+(?:const|function)\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);
  assert.deepEqual(names, ["createEditorEntry"]);
  assert.ok(src.includes("export function createEditorEntry(deps: EditorEntryDeps): EditorEntryPort {"),
    "포트는 이름 있는 deps 형으로 받고 반환형이 곧 6키 계약이다");
});

/* ================= 2. 의존이 드러나 있다 ================= */

test("의존은 주입뿐 — 값 import 간선은 호스트 결과 판독 하나다", () => {
  const found = [...src.matchAll(/^import .*$/gm)].map((m) => m[0]);
  assert.deepEqual(found, [
    'import type { BridgeClient } from "../runtime/client.ts";',
    'import type { EditorEntryPort } from "./ports.ts";',
    'import { expectHostValue } from "./runtime.ts";',
  ], "import 목록이 계약과 동일 — 확인 UI·항행·통지는 전부 주입이라 간선이 없다");
  assert.ok(src.includes("deps.modal.confirm({"), "파괴 확인은 주입된 modal 포트가 진다");
  assert.ok(src.includes("deps.modal.restoreFocus("), "초점 되돌림 규칙은 모달 것을 재사용한다");
});

test("음성 조건 — IIFE·자기 전역·제품 전역 조회·Object.assign(window) 전부 0", () => {
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const PRODUCT = /window\.(Modal|Popover|Bridge|Nav|escHtml|SheetPicker|PathTrack|Preserve|Intent|DataPicker|EditorEntry|[A-Za-z]*Screen|__push|AppCloseGuard)\b/;
  assert.equal(/^\(function\s*\(/m.test(code), false, "top-level IIFE 금지");
  assert.equal(/^\}\)\(\);/m.test(code), false, "top-level IIFE 금지");
  assert.equal(/(window|globalThis)\.[A-Za-z_$][\w$]*\s*=[^=]/.test(code), false, "자기 전역 생산 금지");
  assert.equal(PRODUCT.test(code), false, "제품 전역 조회 금지");
  assert.equal(code.includes("Object.assign(window"), false, "Object.assign(window) 금지");
  // 개별 이름으로도 센다 — 위 정규식이 언젠가 느슨해져도 이 셋은 남는다.
  for (const global of ["window.Modal", "window.Nav", "window.Bridge"]) {
    assert.equal(code.includes(global), false, `${global} 조회 0`);
  }
  /* loud 실패 통로는 legacy 의 `window.alert` 2곳에서 주입 `notify` 2곳으로 옮겨졌다 —
     전역을 아예 안 만지므로 이 파일에는 `window.` 가 하나도 없다. */
  assert.equal(/\bwindow\./.test(code), false, "이 seam 은 전역 window 를 만지지 않는다");
  /* 진입 셋이 각자 자기 실패를 재진술한다 — `open_job_in_editor`·`new_job_from_data` 는
     `ERROR:` 반환으로, `new_session` 은 dispatch 의 `{ok:false}` 봉투로 온다(형태가 달라도
     「조용히 착지하지 않는다」는 같다). */
  assert.equal((code.match(/deps\.notify\(/g) || []).length, 3, "loud 실패 통로 3곳 보존");
});

test("client 는 객체로만 쓴다 — 모듈/팩토리 스코프에 메서드를 뽑지 않는다", () => {
  assert.equal(/^\s*const\s+\w+\s*=\s*deps\.client\.\w+\s*;/m.test(src), false,
    "메서드 값 캡처 금지(프로브의 프로퍼티 교체가 우회된다)");
  const uses = [...src.matchAll(/\bdeps\.client\.(\w+)/g)].map((m) => m[1]);
  assert.deepEqual([...new Set(uses)].sort(), ["dispatch", "invoke"]);
});

test("모듈 상태는 entryFocus 1슬롯뿐 — 팩토리 밖에 가변 상태 0", () => {
  const head = src.slice(0, src.indexOf("export function createEditorEntry"));
  assert.equal(/^\s*(let|var)\s/m.test(head), false, "모듈 스코프 가변 상태 0");
  const body = src.slice(src.indexOf("export function createEditorEntry"));
  const mutables = [...body.matchAll(/^\s{2}(?:let|var)\s+(\w+)/gm)].map((m) => m[1]);
  assert.deepEqual(mutables, ["entryFocus"], "진입 슬롯은 하나뿐(늘리지 않는다)");
});

/* ================= 3. navigate 는 late-bound ================= */

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
  // 착지 호출점은 land() 하나 — 축자 복붙이 생기면 착지 변경이 드리프트한다.
  assert.equal((src.match(/deps\.navigate\(/g) || []).length, 1);
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

test("초점 — 진입 셋 모두 확인 **앞에서** 자리를 기억한다", () => {
  // 정적 계측: 정의 1 + 진입 3. 진입이 늘면 이 수도 함께 늘어야 한다.
  assert.equal((src.match(/rememberEntryFocus\(\)/g) || []).length, 4);
  for (const fn of [
    "async function newDraft()",
    "async function newDraftFromData(context?: Obj)",
    "async function openGuarded(name: string, context?: Obj)",
  ]) {
    const body = src.slice(src.indexOf(fn));
    const remember = body.indexOf("rememberEntryFocus()");
    const confirm = body.indexOf("confirmDiscard(");
    assert.ok(remember >= 0 && remember < confirm, `${fn}: 확인 앞에서 기억한다`);
  }
});

/* ================= 9. native 확인 재도입 금지 ================= */

test("확인은 주입된 modal 이 진다 — native confirm/prompt 재도입 0", () => {
  const code = src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    /* 형 선언의 메서드 시그니처(`confirm(spec: Obj): Promise<boolean>`)는 **호출이 아니다**.
       legacy 에는 형이 없어 이 절제가 필요 없었다 — 남기면 맨손 호출 금지가 자기 계약
       선언 때문에 영영 빨강이라 아무것도 못 본다. */
    .replace(/^(?:export\s+)?type\s+\w+\s*=\s*\{[\s\S]*?^\};$/gm, "");
  assert.ok(code.includes("deps.modal.confirm({"), "절제가 실제 호출까지 지우지 않았다");
  assert.equal(/\bwindow\.(confirm|prompt)\s*\(/.test(code), false, "native 확인 금지");
  assert.equal(/(^|[^.\w])(confirm|prompt)\s*\(/.test(code.replace(/deps\.modal\.confirm\(/g, "")), false,
    "맨손 confirm/prompt 금지");
});

/* ================= 10. 팩토리 독립성 ================= */

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
