/* 양성 대조 ② — `window` 를 피해 `globalThis` 로 쓰는 우회. 같은 전역, 다른 이름. */
export const marker = "pos/global_this";

globalThis.Leak = 1;
