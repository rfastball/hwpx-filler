/* guard.js ESM 계약 — 세션 가드 재진술 합성기(N-04, #376).

   문안은 Python 판정을 사람 문장으로 옮기는 마지막 한 줄이라 **자릿수 뒤바뀜이 조용한
   거짓말**이 된다(정의 매치와 정의 밖이 서로 자리를 바꿔도 문장은 멀쩡해 보인다).
   그래서 세 수치를 전부 다른 값으로 넣어 슬롯이 어긋나면 반드시 깨지게 세운다. */
import { after, test } from "node:test";
import assert from "node:assert/strict";

import { Guard } from "../../frontend/js/guard.js";

const MODULE = "../../frontend/js/guard.js";

after(() => {
  delete globalThis.window;
});

test("필터가 서 있지 않으면 선택 건수만 말한다", () => {
  assert.equal(Guard.selectionLine(7, false, 3, 4), "직접 선택 7행");
  assert.equal(Guard.selectionLine(0, false, 0, 0), "직접 선택 0행");
});

test("필터가 서 있으면 정의 안팎을 나눠 말한다(세 수치 슬롯 고정)", () => {
  assert.equal(
    Guard.selectionLine(12, true, 5, 7),
    "직접 선택 12행 (정의 매치 5 · 정의 밖 7)",
  );
  assert.equal(
    Guard.selectionLine(1, true, 2, 3),
    "직접 선택 1행 (정의 매치 2 · 정의 밖 3)",
  );
});

test("filterActive 는 truthiness 분기다", () => {
  // 오늘의 동작 그대로 — 불리언 강제 없이 참값이면 분기한다.
  assert.equal(Guard.selectionLine(1, 1, 2, 3), "직접 선택 1행 (정의 매치 2 · 정의 밖 3)");
  assert.equal(Guard.selectionLine(1, "y", 2, 3), "직접 선택 1행 (정의 매치 2 · 정의 밖 3)");
  assert.equal(Guard.selectionLine(1, 0, 2, 3), "직접 선택 1행");
  assert.equal(Guard.selectionLine(1, "", 2, 3), "직접 선택 1행");
  assert.equal(Guard.selectionLine(1, null, 2, 3), "직접 선택 1행");
  assert.equal(Guard.selectionLine(1, undefined, 2, 3), "직접 선택 1행");
});

test("Guard 의 own-key 집합은 selectionLine 하나뿐이고 호출 가능하다", () => {
  assert.deepEqual(Object.keys(Guard), ["selectionLine"]);
  assert.equal(typeof Guard.selectionLine, "function");
});

test("모듈 공개 표면은 named export Guard 하나뿐이다(default 없음)", async () => {
  const ns = await import(MODULE);
  assert.deepEqual(Object.keys(ns), ["Guard"]);
  assert.equal(ns.default, undefined);
});

test("import 만으로는 전역이 변하지 않는다", async () => {
  globalThis.window = {};
  await import(`${MODULE}?fresh=global-probe`);
  assert.equal(Object.keys(globalThis.window).length, 0);
  delete globalThis.window;
});
