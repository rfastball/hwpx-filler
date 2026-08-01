/* 양성 대조 ③-다 — 갱신 표현식도 쓰기다. 부재한 프로퍼티를 `++`하면
   `undefined` → `NaN` 변환 뒤 own 프로퍼티가 새로 생긴다. 대입 표현식만 세는
   스캐너는 이 쓰기를 단순 판독으로 잘못 분류한다. */
export const marker = "pos/window_update";

window.Leak++;
globalThis["LeakBracket"]--;
