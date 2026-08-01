/* 음성 대조 ⑦ — 함수 **안**의 IIFE. 즉시 실행 자체가 금지가 아니다. 금지는 "모듈 평가가
   곧 실행" 이라는 최상단의 경우뿐이고, 함수 안의 것은 호출자가 시점을 쥔다. */
export function boot() {
  const once = (function () {
    return 1;
  })();
  const twice = (() => 2)();
  return once + twice;
}

export const lazy = () => (() => 3)();
