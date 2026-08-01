/* 음성 대조 ①·②·③ — **지역 이름 `window`**. 텍스트로는 양성 대조 ①과 글자까지 같지만
   가리키는 것이 다르다. 스코프를 안 보는 스캐너는 여기서 거짓 양성을 내고, 거짓 양성을
   내는 게이트는 곧 꺼진다 — 그래서 이 near-miss 가 중요하다.

   selftest 프로브가 실제로 이 모양의 가짜 창을 만든다(`{ ... }` 를 창처럼 넘긴다). */
export function makeFrame() {
  const window = {};
  window.Leak = 1;
  globalThis: {
    /* 라벨은 전역이 아니다 — `globalThis.` 와 헷갈리라고 둔다. */
    break globalThis;
  }
  return window;
}

export function makeFrameFromParam(window) {
  window.Leak = 2;
  return window;
}
