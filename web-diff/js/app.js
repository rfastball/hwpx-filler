/* 부팅 — pywebview 준비 시 diff 화면 초기화. diff 는 단일 화면이라 라우터가 없다.
   화면 로직은 js/screens/diff.js 가 소유(DiffScreen.init). 여기선 배선만. */
(function () {
  // pywebview.api 준비 후 실화면 초기화(브라우저 단독 미리보기에선 안 뜸 — 정상).
  window.addEventListener("pywebviewready", () => {
    if (window.DiffScreen) window.DiffScreen.init();
  });
})();
