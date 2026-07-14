/* 라우터 + 부팅 — 레일 나비로 화면 전환, pywebview 준비 시 실화면 초기화.
   화면별 로직은 js/screens/*.js 가 소유(TxtScreen.init 등). 여기선 배선만. */
(function () {
  const navs = document.querySelectorAll(".navbtn");
  const scrs = document.querySelectorAll(".scr");

  navs.forEach((b) => b.addEventListener("click", () => {
    navs.forEach((x) => x.setAttribute("aria-current", "false"));
    b.setAttribute("aria-current", "true");
    const id = b.dataset.scr;
    scrs.forEach((s) => s.classList.toggle("on", s.id === "scr-" + id));
  }));

  // 사이드 패널 접기(#18/9B2AB35D-A) — 좁은 창에서 작업 영역 확장(반응형). 셸 전역.
  const railToggle = document.getElementById("railToggle");
  if (railToggle) {
    railToggle.addEventListener("click", () =>
      document.querySelector(".app").classList.toggle("rail-collapsed"));
  }

  // pywebview.api 준비 후 실화면 초기화(브라우저 단독 미리보기에선 안 뜸 — 정상).
  window.addEventListener("pywebviewready", () => {
    if (window.TxtScreen) window.TxtScreen.init();
    if (window.EditorScreen) window.EditorScreen.init();
    if (window.RunScreen) window.RunScreen.init();
    if (window.MatrixScreen) window.MatrixScreen.init();
    if (window.TemplateScreen) window.TemplateScreen.init();
  });
})();
