/* 양성 대조 ① — 가장 평범한 전역 누수. `window.<이름> = …` 한 줄. */
export const marker = "pos/window_dot";

window.Leak = 1;
