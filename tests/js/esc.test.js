/* esc.js ESM 계약 — 공유 HTML 이스케이퍼(N-04, #376).

   escape 초집합(& < > ")의 **경계 양쪽**을 다 세운다: 다루는 넉 자와, 일부러 다루지 않는
   ' · ` 다. 경계를 한쪽만 세우면 "더 escape 하면 더 안전하다"는 조용한 확장이 회귀로
   들어와도 초록이다. 이미 escape 된 문자열의 이중 escape 와 null·undefined 의 String()
   강제도 **오늘의 동작**으로 못박는다 — ESM 전환은 이관이지 수리가 아니다. */
import { after, test } from "node:test";
import assert from "node:assert/strict";

import { escHtml } from "../../frontend/js/esc.js";

const MODULE = "../../frontend/js/esc.js";

after(() => {
  delete globalThis.window;
});

test("네 글자를 개별적으로 정확한 엔티티로 바꾼다", () => {
  assert.equal(escHtml("&"), "&amp;");
  assert.equal(escHtml("<"), "&lt;");
  assert.equal(escHtml(">"), "&gt;");
  assert.equal(escHtml('"'), "&quot;");
});

test("네 글자가 섞여도 전부 치환한다", () => {
  assert.equal(escHtml('&<>"'), "&amp;&lt;&gt;&quot;");
  assert.equal(
    escHtml('<a href="x">Tom & Jerry</a>'),
    "&lt;a href=&quot;x&quot;&gt;Tom &amp; Jerry&lt;/a&gt;",
  );
});

test("평문·빈 문자열은 그대로 통과한다", () => {
  assert.equal(escHtml("hello world"), "hello world");
  assert.equal(escHtml(""), "");
});

test("숫자는 String() 로 강제된다", () => {
  assert.equal(escHtml(42), "42");
  assert.equal(escHtml(0), "0");
});

test("한글·유니코드는 손대지 않는다", () => {
  assert.equal(escHtml("복사하면 완료됩니다"), "복사하면 완료됩니다");
  assert.equal(escHtml("표 · 거울 — ⤢"), "표 · 거울 — ⤢");
  assert.equal(escHtml("정의 밖 <3건>"), "정의 밖 &lt;3건&gt;");
});

test("이미 escape 된 문자열은 이중 escape 된다(오늘의 동작)", () => {
  // 멱등이 아니다 — 호출부가 두 번 태우지 않는 것이 계약이다.
  assert.equal(escHtml("&amp;"), "&amp;amp;");
  assert.equal(escHtml("&lt;b&gt;"), "&amp;lt;b&amp;gt;");
});

test("null·undefined 는 String() 결과가 된다", () => {
  assert.equal(escHtml(null), "null");
  assert.equal(escHtml(undefined), "undefined");
});

test("작은따옴표·백틱은 escape 대상이 아니다(초집합 경계)", () => {
  assert.equal(escHtml("it's"), "it's");
  assert.equal(escHtml("`tick`"), "`tick`");
  assert.equal(escHtml("'\"'"), "'&quot;'");
});

test("모듈 공개 표면은 named export escHtml 하나뿐이다(default 없음)", async () => {
  const ns = await import(MODULE);
  assert.deepEqual(Object.keys(ns), ["escHtml"]);
  assert.equal(ns.default, undefined);
  assert.equal(typeof ns.escHtml, "function");
});

test("import 만으로는 전역이 변하지 않는다", async () => {
  globalThis.window = {};
  await import(`${MODULE}?fresh=global-probe`);
  assert.equal(Object.keys(globalThis.window).length, 0);
  delete globalThis.window;
});
