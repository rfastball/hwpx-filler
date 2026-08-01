/* 양성 대조 ⑦-가 — 모듈 최상단 IIFE. ESM 전환의 요지가 "평가가 곧 부팅" 을 끝내는 것이라
   최상단 즉시 실행은 그 자체로 회귀다(부팅 지점이 다시 import 순서에 매달린다).
   단항 연산자로 감싼 `!function(){}()` 변형도 같은 것이므로 함께 둔다. */
export const marker = "pos/top_iife";

(function () {
  const local = 1;
  return local;
})();

!function () {
  return 2;
}();
