/* 음성 대조 — 창 **판독**은 위반이 아니다. 플랫폼 API(`addEventListener`·`matchMedia`)와
   pywebview 주입 표면은 제품이 정상적으로 읽는다. 쓰기 축은 여기서 조용해야 하고, 대신
   판독 축은 이 파일에서 시끄러워야 한다 — 별칭 27 의 "판독 0" 계약이 그 축을 쓴다. */
export function wire(handler) {
  window.addEventListener("resize", handler);
  const dark = window.matchMedia("(prefers-color-scheme: dark)");
  if (window.Leak === 1) return dark;
  return window.pywebview;
}
