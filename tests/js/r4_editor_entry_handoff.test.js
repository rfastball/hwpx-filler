/* R4-02 편집기 진입 seam의 단일 결속 계약 — R5-01에서 migration API를 걷은 후계.
 *
 * legacy 구현은 이미 파일째 사라졌으므로 port는 owner 상태 없이 구현 하나만 정확히 한 번
 * 받는다. 호출자는 port 하나만 알고 둘째 결속은 loud failure다.
 *
 * D5 — `aimAt` 은 이 port 의 7번째 키가 **아니다**. 이 port 의 정체는 진입/복귀 초점이고,
 * `EditorController.aimAt`은 화면 콜백 표의 late-bound 간선이다. 그 간선이 끊기면 결과에서
 * 규칙 행을 겨누는 길이 조용히 사라지므로 여기 음성 대조를 둔다.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

import { createScreenPorts } from "../../frontend/src/screens/ports.ts";
import { createServiceHandoffPorts } from "../../frontend/src/ports/service_handoff.ts";
import { createEditorEntry } from "../../frontend/src/screens/editor_entry.ts";

const BOOTSTRAP = readFileSync(
  new URL("../../frontend/src/bootstrap.js", import.meta.url), "utf8");

const ENTRY_KEYS = [
  "confirmDiscard", "land", "newDraft", "newDraftFromData", "openGuarded", "restoreEntryFocus",
];

function reactEntry() {
  return createEditorEntry({
    doc: { activeElement: null },
    client: {
      async invoke() { return { ok: true, value: false }; },
      async dispatch() { return { ok: true, value: {} }; },
    },
    modal: { async confirm() { return true; }, restoreFocus() {} },
    navigate: () => {},
    notify: () => {},
  });
}

test("React 구현은 빈 port에 정확히 한 번 결속한다", () => {
  const ports = createScreenPorts();
  assert.throws(() => ports.editorEntry.current(), /결속되지/,
    "미결속 호출은 조용한 무동작이 아니라 loud 다");

  const entry = reactEntry();
  ports.editorEntry.bind(entry);
  assert.equal(ports.editorEntry.current(), entry);
});

test("음성 — 둘째 결속은 throw 하고 첫 구현이 그대로 남는다", () => {
  const ports = createScreenPorts();
  const first = reactEntry();
  ports.editorEntry.bind(first);
  assert.throws(() => ports.editorEntry.bind(reactEntry()), /정확히 한 번/);
  assert.equal(ports.editorEntry.current(), first, "실패한 둘째 결속이 구현을 흔들지 않는다");
  assert.deepEqual(Object.keys(ports.editorEntry).sort(), ["bind", "current"],
    "legacy owner/handoff API가 되살아나면 안 된다");
});

test("포트 형은 6키 그대로 — 진입 seam 에 aimAt 을 얹지 않는다(D5)", () => {
  const ports = createScreenPorts();
  ports.editorEntry.bind(reactEntry());
  assert.deepEqual(Object.keys(ports.editorEntry.current()).sort(), ENTRY_KEYS);
  assert.equal(Object.hasOwn(ports.editorEntry.current(), "aimAt"), false,
    "이 port 의 정체는 진입/복귀 초점이다 — 겨눔은 화면 콜백 표가 진다");
});

test("호출자는 port 만 안다 — owner 가 React 여도 호출부가 그대로 왕복한다", async () => {
  const ports = createScreenPorts();
  const seen = [];
  ports.editorEntry.bind(createEditorEntry({
    doc: { activeElement: null },
    client: {
      async invoke(method, ...args) { seen.push([method, ...args]); return { ok: true, value: false }; },
      async dispatch() { return { ok: true, value: {} }; },
    },
    modal: { async confirm() { return true; }, restoreFocus() {} },
    navigate: (...args) => seen.push(["navigate", ...args]),
    notify: () => {},
  }));

  /* 라이브러리·작업 화면이 쓰는 그 호출 형태 그대로. */
  assert.equal(await ports.editorEntry.current().openGuarded("작업A", { entry_reason: "library" }), true);
  assert.deepEqual(seen, [
    ["editor_has_unsaved_work"],
    ["open_job_in_editor", "작업A", { entry_reason: "library" }],
    ["navigate", "editor", { force: true }],
  ]);
});

/* ================= 시트 선택 port 도 같은 형태다(rev4 → D10) ================= */

test("SheetPickerPort도 빈 port 결속 한 번 — 둘째 결속은 loud다", () => {
  const services = createServiceHandoffPorts();
  const picker = { choose: async () => null };
  services.sheetPicker.bind(picker);
  assert.throws(() => services.sheetPicker.bind({ choose: async () => null }), /정확히 한 번/);
  assert.equal(services.sheetPicker.current(), picker);
});

/* ================= 합성 루트의 결속 자리(정적 핀) ================= */

test("합성 루트는 두 port를 단일 bind로 잇고 migration API를 남기지 않는다", () => {
  assert.match(BOOTSTRAP, /servicePorts\.sheetPicker\.bind\(SheetPicker\);/);
  assert.match(BOOTSTRAP, /screenPorts\.editorEntry\.bind\(EditorEntry\);/);
  for (const retired of ["bindLegacy", "bindReact", ".handoff(", ".owner("]) {
    assert.equal(BOOTSTRAP.includes(retired), false, `${retired} migration API 잔존`);
  }
});

test("음성 — aimAt 간선이 끊기면 결과에서 규칙 행을 겨눌 길이 사라진다(D5)", () => {
  /* R4-03 이 실행 remainder 를 절단하며 이 소비자도 React 로 옮겼다 — 겨눔을 부르는
     자리는 사라진 것이 아니라 이사했고, 양성 대조는 그 새 자리를 겨눈다. */
  const job = readFileSync(new URL("../../frontend/src/screens/job_run.ts", import.meta.url), "utf8");
  assert.ok(job.includes("editor.aimAt(target)"),
    "작업 실행 표면이 여전히 겨눔을 부른다(소비자 양성 대조)");
  assert.match(BOOTSTRAP, /aimAt: \(\.\.\.args\) => EditorController\.aimAt\(\.\.\.args\),/);
});

test("R4-04 — ContextMenu 후계가 두 소비자를 받고 grouplist.js 는 파일째 은퇴한다(D4)", () => {
  const consumers = [...BOOTSTRAP.matchAll(/GroupList\.createMenu\(/g)].length;
  assert.equal(consumers, 0, "문자열 메뉴 팩토리 소비자는 0이어야 한다");
  assert.equal(existsSync(new URL("../../frontend/js/grouplist.js", import.meta.url)), false,
    "마지막 소비자가 React로 옮겨간 뒤 grouplist.js 자체도 남기지 않는다");

  const successor = readFileSync(
    new URL("../../frontend/src/screens/context_menu.ts", import.meta.url), "utf8");
  assert.match(successor, /export function createContextMenu\(/);
  assert.match(successor, /export function ContextMenu\(/);
  assert.ok(successor.includes("popover.place(menu, state.trigger)"));
  assert.ok(successor.includes("popover.wireDismiss({"));
  for (const consumer of ["library.ts", "editor.ts"]) {
    const src = readFileSync(
      new URL(`../../frontend/src/screens/${consumer}`, import.meta.url), "utf8");
    const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    assert.ok(src.includes('from "./context_menu.ts"'), `${consumer} ContextMenu 후계 배선`);
    assert.equal(code.includes("innerHTML"), false, `${consumer} 문자열 menu host 재도입 금지`);
  }
});
