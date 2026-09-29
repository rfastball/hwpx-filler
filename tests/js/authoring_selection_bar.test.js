/* IDE-08 P-05: 선택 옆 막대의 순수 부분 — 실을 것(Python 판정의 되는 만들기·대안), 자리(선택 끝 줄 아래 8px, clampMenu),
   TXT 편집면의 선택 끝 줄 보고(포인터를 놓은 뒤에만, 선택이 바뀌거나 비거나 편집되면 걷는다). 화면 위의 동작은
   authoring_render.test.js 가, 실창 좌표는 실창 밴드가 잰다. */
import test from "node:test";
import assert from "node:assert/strict";
import { SELECTION_BAR_GAP, commandEntries, selectionBarItems, selectionBarPlace } from "../../frontend/src/screens/authoring.ts";
import { selectionRectTracker } from "../../frontend/src/editorview/txt_lintpad.ts";

const judged = (overrides) => [
  { type: "create_field", enabled: false, reason: "선택한 범위에는 필드를 만들 수 없습니다.", alternative: null },
  { type: "create_slot", enabled: false, reason: "항목 불가", alternative: null },
  { type: "create_option", enabled: false, reason: "선택 불가", alternative: null },
  { type: "rename_field", enabled: true },
].map((entry) => ({ ...entry, ...(overrides[entry.type] || {}) }));

test("IDE-08 P-05: the bar carries only the enabled create commands and their alternatives, under the existing names", () => {
  const one = selectionBarItems(commandEntries(judged({ create_field: { enabled: true, reason: null } }), false), false);
  assert.deepEqual(one.map((entry) => [entry.label, entry.command]), [["필드로 만들기", "create_field"]], "되는 만들기 1개 → 단추 1개, 만들기 밖의 명령은 싣지 않는다");

  assert.deepEqual(selectionBarItems(commandEntries(judged({}), false), false), [], "되는 만들기가 없으면 막대가 없다");

  const alternative = selectionBarItems(commandEntries(judged({
    create_field: { alternative: { label: "필드 연결 변경", command_type: "relink_field" } },
    create_slot: { enabled: true, reason: null },
    create_option: { alternative: { label: "항목으로 만들기", command_type: "create_slot" } },
  }), false), false);
  assert.deepEqual(alternative.map((entry) => [entry.label, entry.command, entry.alternative]),
    [["필드 연결 변경", "relink_field", true], ["항목으로 만들기", "create_slot", false]], "대안은 싣고, 같은 명령으로 가는 대안은 한 번만");

  const enabled = judged({ create_field: { enabled: true, reason: null } });
  assert.deepEqual(selectionBarItems(commandEntries(enabled, true), true), [], "읽기 전용이면 없다");
  assert.deepEqual(selectionBarItems(commandEntries([], false), false), [], "판정 전(pending)이면 없다");
});

test("IDE-08 P-05: the bar stands 8px under the selection end line, flips above it when the window runs out, and stays inside", () => {
  const viewport = { width: 1000, height: 700 };
  const size = { width: 180, height: 30 };
  const line = { left: 300, top: 200, bottom: 220 };
  assert.equal(SELECTION_BAR_GAP, 8);
  assert.deepEqual(selectionBarPlace(line, size, viewport), { left: 300, top: 228 });
  assert.deepEqual(selectionBarPlace({ left: 300, top: 660, bottom: 680 }, size, viewport), { left: 300, top: 660 - 8 - 30 }, "아래가 모자라면 줄 위로");
  assert.deepEqual(selectionBarPlace({ left: 950, top: 200, bottom: 220 }, size, viewport), { left: 1000 - 4 - 180, top: 228 }, "오른쪽 끝은 창 안으로");
});

test("IDE-08 P-05: the TXT editor reports the selection end once the pointer is released, and takes it down on change, collapse and edit", () => {
  const reports = [];
  const tracker = selectionRectTracker((rect) => reports.push(rect));
  let measures = 0;
  const measure = (rect) => () => { measures += 1; tracker.measured(rect); };
  const line = { left: 40, top: 100, bottom: 120 };

  tracker.press();
  tracker.selected(false, measure(line));
  tracker.selected(false, measure(line));
  assert.deepEqual([reports, measures], [[], 0], "끄는 동안은 재지 않는다 — 막대가 포인터 아래에 서지 않는다");
  tracker.release(measure(line));
  assert.deepEqual(reports, [line], "놓는 순간 선택 끝 줄을 한 번 보고한다");

  tracker.selected(false, measure({ ...line, left: 80 }));
  assert.deepEqual(reports.slice(1), [null, { ...line, left: 80 }], "선택이 바뀌면 걷고 새 끝 줄을 보고한다(키보드 선택)");
  tracker.edited();
  assert.deepEqual(reports.at(-1), null, "편집하면 걷는다");
  tracker.edited();
  tracker.selected(true, measure(line));
  assert.equal(reports.length, 4, "이미 걷혔으면 null 을 거듭 보내지 않고, 빈 선택은 재지 않는다");
  tracker.selected(false, measure(null));
  assert.equal(reports.length, 4, "잴 수 없으면(보이지 않는 자리) 서지 않는다");
});
