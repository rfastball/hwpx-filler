/* R4-02 — 편집기 진입 seam 의 owner 교체 계약.
 *
 * 패킷 rev2 §3 은 `bindLegacy` → `handoff("legacy","react")` 를 그렸다. 착지에서 그 그림은
 * 성립하지 않는다(구현 델타 D10): 이 슬라이스가 legacy `editor_entry.js` 를 **파일째**
 * 삭제하므로 handoff 할 상대가 없다. 빈 port 에 `bindReact` 로 한 번 결속한다.
 *
 * 불변식은 약해지지 않고 **강해진다**:
 *  - 「정확히 한 번」은 그대로다 — 둘째 결속은 throw.
 *  - 「중간 dual-dispatch 금지」는 창 자체가 생기지 않아 **구조적으로** 성립한다.
 *  - 호출자(라이브러리·작업 화면)는 port 하나만 알고, owner 가 바뀌어도 고치지 않는다.
 *
 * `handoff` API 는 죽지 않았다 — 남은 legacy 소비자가 있는 port(job run 계열)에서 #416·#417
 * 이 쓴다. 그래서 이 파일은 그 API 가 이 port 에서 **쓰이지 않았음**까지 함께 못박는다.
 *
 * D5 — `aimAt` 은 이 port 의 7번째 키가 **아니다**. 이 port 의 정체는 진입/복귀 초점이고,
 * `EditorScreen.aimAt` 은 화면 콜백 표의 late-bound 간선이다. 그 간선이 끊기면 결과에서
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

test("React 구현은 **빈 port** 에 정확히 한 번 결속한다(중간 dual-dispatch 창 없음)", () => {
  const ports = createScreenPorts();
  assert.equal(ports.editorEntry.owner(), null);
  assert.throws(() => ports.editorEntry.current(), /결속되지/,
    "미결속 호출은 조용한 무동작이 아니라 loud 다");

  const entry = reactEntry();
  ports.editorEntry.bindReact(entry);
  assert.equal(ports.editorEntry.owner(), "react");
  assert.equal(ports.editorEntry.current(), entry);
});

test("음성 — 둘째 결속은 throw 하고 첫 구현이 그대로 남는다", () => {
  const ports = createScreenPorts();
  const first = reactEntry();
  ports.editorEntry.bindReact(first);
  assert.throws(() => ports.editorEntry.bindReact(reactEntry()), /빈 port에만/);
  assert.throws(() => ports.editorEntry.bindLegacy(reactEntry()), /정확히 한 번/);
  assert.equal(ports.editorEntry.current(), first, "실패한 둘째 결속이 owner 를 흔들지 않는다");
});

test("음성 — legacy 를 거치지 않았으므로 legacy→react handoff 는 성립하지 않는다", () => {
  const ports = createScreenPorts();
  ports.editorEntry.bindReact(reactEntry());
  assert.throws(() => ports.editorEntry.handoff("legacy", "react", reactEntry()), /상태가 어긋/,
    "owner 가 이미 react 인 port 에 legacy 출처를 주장할 수 없다");
});

test("포트 형은 6키 그대로 — 진입 seam 에 aimAt 을 얹지 않는다(D5)", () => {
  const ports = createScreenPorts();
  ports.editorEntry.bindReact(reactEntry());
  assert.deepEqual(Object.keys(ports.editorEntry.current()).sort(), ENTRY_KEYS);
  assert.equal(Object.hasOwn(ports.editorEntry.current(), "aimAt"), false,
    "이 port 의 정체는 진입/복귀 초점이다 — 겨눔은 화면 콜백 표가 진다");
});

test("호출자는 port 만 안다 — owner 가 React 여도 호출부가 그대로 왕복한다", async () => {
  const ports = createScreenPorts();
  const seen = [];
  ports.editorEntry.bindReact(createEditorEntry({
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

test("SheetPickerPort 도 빈 port 결속 한 번 — 둘째 결속·owner 주장이 전부 loud 다", () => {
  const services = createServiceHandoffPorts();
  const picker = { choose: async () => null };
  services.sheetPicker.bindReact(picker);
  assert.equal(services.sheetPicker.owner(), "react");
  assert.throws(() => services.sheetPicker.bindReact({ choose: async () => null }), /빈 port에만/);
  assert.throws(
    () => services.sheetPicker.handoff("legacy", "react", { choose: async () => null }), /상태가 어긋/);
  assert.equal(services.sheetPicker.current(), picker);
});

/* ================= 합성 루트의 결속 자리(정적 핀) ================= */

test("합성 루트는 두 port 를 bindReact 로 잇고 legacy 결속을 남기지 않는다", () => {
  assert.match(BOOTSTRAP, /servicePorts\.sheetPicker\.bindReact\(SheetPicker\);/);
  assert.match(BOOTSTRAP, /screenPorts\.editorEntry\.bindReact\(EditorEntry\);/);
  assert.equal(/screenPorts\.editorEntry\.bind(Legacy|.*handoff)/.test(BOOTSTRAP), false);
  assert.equal(/servicePorts\.sheetPicker\.bindLegacy/.test(BOOTSTRAP), false);
  /* handoff API 는 살아 있다 — 다만 이 두 port 에서는 쓰이지 않는다. */
  assert.equal(BOOTSTRAP.includes(".handoff("), false,
    "R4-02 는 handoff 를 쓰지 않는다 — 쓰는 순간 legacy 구현이 어딘가 남아 있다는 뜻이다");
});

test("음성 — aimAt 간선이 끊기면 결과에서 규칙 행을 겨눌 길이 사라진다(D5)", () => {
  const job = readFileSync(new URL("../../frontend/js/screens/job.js", import.meta.url), "utf8");
  assert.ok(job.includes("EditorScreen.aimAt(target)"),
    "작업 화면 remainder 가 여전히 겨눔을 부른다(소비자 양성 대조)");
  assert.match(BOOTSTRAP, /aimAt: \(\.\.\.args\) => EditorScreen\.aimAt\(\.\.\.args\),/);
  assert.match(BOOTSTRAP, /aimAt: \(\.\.\.args\) => EditorController\.aimAt\(\.\.\.args\),/);
});

test("음성 — createMenu 소비자가 살아 있는 동안 grouplist.js 는 지울 수 없다(D4)", () => {
  const consumers = [...BOOTSTRAP.matchAll(/GroupList\.createMenu\(/g)].length;
  assert.equal(consumers, 2, "libraryGroupMenu·tplRowMenu 두 소비자");
  assert.ok(existsSync(new URL("../../frontend/js/grouplist.js", import.meta.url)),
    "소비자가 남은 채 파일을 지우면 부팅이 죽는다 — 파일 은퇴는 #417 이 진다");
  /* 절제의 실물 — 옮겨간 함수군과 죽은 export 가 되살아나지 않았다. **본문**으로 센다:
     머리말이 「어디로 옮겼는가」를 이름으로 적고 있어, 파일 전체 부분열로 재면 산문이
     코드의 부활을 가려 준다(반대 방향으로도 — 산문 한 줄이 영영 빨강을 만든다). */
  const code = readFileSync(new URL("../../frontend/js/grouplist.js", import.meta.url), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  assert.ok(/function createMenu\(/.test(code), "절제가 남은 함수까지 지우지 않았다(양성 대조)");
  for (const retired of ["createMoveDialog", "toggleGroup", "setGroupExpanded"]) {
    assert.equal(code.includes(retired), false, `${retired} 는 R4-02 에서 절제됐다`);
  }
  assert.match(code, /export const GroupList = \{ createMenu \};/,
    "export 표면도 하나로 좁아졌다 — 죽은 이름이 표면에 남으면 은퇴가 초록불 뒤에 숨는다");
});
