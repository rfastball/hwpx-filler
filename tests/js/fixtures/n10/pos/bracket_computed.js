/* 양성 대조 ③-나 — 계산된 이름. 어떤 전역이 서는지 **정적으로 알 수 없다**.
   이때 조용히 넘기면 게이트가 자기 눈먼 자리를 스스로 만든다. 그래서 스캐너는 이 자리를
   "모르는 전역 쓰기" 로 시끄럽게 신고하고, 소비 게이트는 그것을 위반으로 센다. */
export const marker = "pos/bracket_computed";

const NAMES = ["Leak"];
let key = NAMES[0];

window[key] = 1;
globalThis[`Leak${key}`] = 2;
