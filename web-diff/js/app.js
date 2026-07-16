/* 부팅 — pywebview 준비 시 diff 화면 초기화. diff 는 단일 화면이라 라우터가 없다.
   화면 로직은 js/screens/diff.js 가 소유(DiffScreen.init). 여기선 배선만. */
(function () {
  /* 비동기 실패 최종 백스톱 — filler 셸(web/js/app.js) 미러. 지역 가드를 빠뜨린 브리지
     rejection 이 조용한 무반응으로 증발하지 않게 alert 로 재진술한다(confirm-or-alarm). */
  window.addEventListener("unhandledrejection", (e) => {
    e.preventDefault();
    const r = e.reason;
    window.alert(String((r && r.message) || r));
  });

  // pywebview.api 준비 후 실화면 초기화(브라우저 단독 미리보기에선 안 뜸 — 정상).
  window.addEventListener("pywebviewready", () => {
    if (window.DiffScreen) window.DiffScreen.init();
  });
})();
