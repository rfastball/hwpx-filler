/* copy.js ESM 계약 — 공유 카피 단일 출처(N-04, #376).

   ESM 전환의 불변식 세 가지를 잡는다: ①문자열이 바이트 동일한가 ②공개 표면이 넓어지지
   않았는가(named export 하나·키 하나) ③import 만으로 전역을 건드리지 않는가.
   ③은 제품 전역이 합성 루트(frontend/src/bootstrap.js)의 `__hwpx` 하나뿐이라는 경계의
   테스트다 — 리프가 몰래 전역을 쓰면 두 곳이 같은 전역을 판정하게 된다. N-10 이전에는
   같은 경계를 중앙 compat 층이 임시 별칭 스물일곱의 단독 생산자로서 졌다. */
import { after, test } from "node:test";
import assert from "node:assert/strict";

import { Copy } from "../../frontend/js/copy.js";

const MODULE = "../../frontend/js/copy.js";

after(() => {
  // 테스트 전용 전역 픽스처는 반드시 회수한다 — 남기면 제품 전역으로 오인된다.
  delete globalThis.window;
});

test("Copy.TXT_NOTE 는 승격된 문자열 그대로다", () => {
  assert.equal(
    Copy.TXT_NOTE,
    "복사하면 완료됩니다. 항목 없는 토큰은 그대로 남습니다.",
  );
});

test("Copy 의 own-key 집합은 TXT_NOTE 하나뿐이다", () => {
  assert.deepEqual(Object.keys(Copy), ["TXT_NOTE"]);
});

test("모듈 공개 표면은 named export Copy 하나뿐이다(default 없음)", async () => {
  const ns = await import(MODULE);
  assert.deepEqual(Object.keys(ns), ["Copy"]);
  assert.equal(ns.default, undefined);
});

test("import 만으로는 전역이 변하지 않는다", async () => {
  globalThis.window = {};
  // 캐시된 인스턴스가 아니라 실제 재평가를 관측해야 단언이 공허해지지 않는다.
  await import(`${MODULE}?fresh=global-probe`);
  assert.equal(Object.keys(globalThis.window).length, 0);
  delete globalThis.window;
});
