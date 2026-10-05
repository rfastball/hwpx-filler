/* Test delta brief
 * Unique risk: a range beat (#1136) asks for a text range the user cannot see, or the editor paints a range the
 * host did not resolve (another tab, a paused lesson, a stale projection).
 * Existing owner: tests/test_tutorial_walk.py proves the host's range and its tolerant completion check; this file
 * proves the shell carries it unchanged and the template editor paints exactly it.
 * Selected layer: Node, pure functions and the authoring controller harness shape; no resource launches.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { beatRange, followBeatRange } from "../../frontend/src/tutorial/range.ts";
import { guideFeed, guideSpans } from "../../frontend/src/screens/authoring_guide.ts";
import { guidePainted } from "../../frontend/src/editorview/txt_ranges.ts";

const range = { session_id: "s1", start: 10, end: 20 };
const live = (beat) => ({ active: true, paused: false, beat });

test("only a live range beat hands the template editor a range, exactly as the host resolved it", () => {
  const beat = { id: "item_range", target: "authoring-range", range };
  assert.deepEqual(beatRange(live(beat)), range);
  assert.equal(beatRange({ active: false, paused: true, beat }), null, "a paused lesson paints nothing");
  assert.equal(beatRange(live({ ...beat, target: "authoring-canvas" })), null);
  assert.equal(beatRange(live({ ...beat, range: null })), null, "an unresolved range paints nothing");
  assert.equal(beatRange(live({ ...beat, range: { ...range, start: "10" } })), null);
  assert.equal(beatRange(null), null);
});

test("the shell follows every tutorial projection into the editor and keeps the editor it wires", () => {
  let listener = () => {};
  let snapshot = live({ target: "authoring-range", range });
  const model = { getSnapshot: () => snapshot, subscribe: (next) => { listener = next; } };
  const seen = [];
  const editor = { guide: (value) => seen.push(value) };
  assert.equal(followBeatRange(model, editor), editor);
  listener();
  snapshot = live({ target: "new-job" });
  listener();
  assert.deepEqual(seen, [range, null]);
});

test("the guide repaints only the tab it names, ignores a resend, and clearing repaints that tab once", () => {
  const painted = [];
  const feed = guideFeed((id) => painted.push(id));
  feed.guide({ session_id: "b", start: 3, end: 9 });
  assert.deepEqual(feed.guideOf("b"), { session_id: "b", start: 3, end: 9 });
  assert.equal(feed.guideOf("a"), null, "다른 탭에는 칠하지 않는다");
  feed.guide({ session_id: "b", start: 3, end: 9 });
  assert.deepEqual(painted, ["b"], "같은 범위의 재전송은 다시 칠하지 않는다");
  feed.guide({ session_id: "a", start: 1, end: 2 });
  assert.deepEqual(painted, ["b", "b", "a"], "옮기면 떠난 탭과 새 탭을 칠한다");
  feed.guide(null);
  assert.equal(feed.guideOf("a"), null);
  assert.deepEqual(painted, ["b", "b", "a", "a"]);
});

test("a range within one line paints those characters in order; any other range paints its lines to the end's line", () => {
  const text = "가\n3. 수요기관은 10일 이내\n\n\n붙임";
  const field = { kind: "field", start: text.indexOf("수요기관"), end: text.indexOf("수요기관") + 4 };
  const tail = { kind: "field", start: text.indexOf("붙임"), end: text.length };
  const at = text.indexOf("10일");
  assert.deepEqual(guideSpans([field, tail], text, { start: at, end: at + 3 }),
    [field, { kind: "guide", start: at, end: at + 3 }, tail], "글자 칠은 분석 조각 순서대로 끼운다");
  const begin = text.indexOf("3."), finish = text.indexOf("\n", begin);
  // Paragraph to the start of the second empty line: the editor's line highlight ends on the end's own line.
  assert.deepEqual(guideSpans([field], text, { start: begin, end: finish + 2 }).at(-1),
    { kind: "highlight", className: "cm-tutorial-range", start: begin, end: finish + 3 });
  // A whole line, an empty range and a word over a token are line paint too (a token is never cut by a mark).
  assert.equal(guideSpans([], text, { start: begin, end: finish }).at(-1).kind, "highlight");
  assert.equal(guideSpans([], text, { start: finish + 1, end: finish + 1 }).at(-1).kind, "highlight");
  assert.equal(guideSpans([field], text, { start: field.start, end: field.end + 1 }).at(-1).kind, "highlight");
});

test("while a guide range is painted the editor refuses text drags, so a press inside a selection starts a new range (#1146)", () => {
  // After '항목으로 만들기' the new item stays selected over the next beat's paragraph; a drag started inside it was a text
  // move (nothing chosen, the document changed). Only the guide's own paint switches that off — never the structure highlight.
  const text = "가\n3. 수요기관은 10일 이내\n\n\n붙임";
  const at = text.indexOf("10일");
  assert.equal(guidePainted(guideSpans([], text, { start: at, end: at + 3 })), true, "한 줄 글자 칠");
  assert.equal(guidePainted(guideSpans([], text, { start: 2, end: text.indexOf("\n", 2) })), true, "줄 칠");
  assert.equal(guidePainted([{ kind: "highlight", start: 0, end: 3 }, { kind: "field", start: 4, end: 8 }]), false, "구조 강조·필드는 끌기를 막지 않는다");
});
