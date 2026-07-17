/* 라우터 + 부팅 — 레일 나비로 화면 전환, pywebview 준비 시 실화면 초기화.
   화면별 로직은 js/screens/*.js 가 소유(TxtScreen.init 등). 여기선 배선만. */
(function () {
  /* 비동기 실패 최종 백스톱 — 지역 가드(디스패처 try/catch·.catch)를 빠뜨린 브리지
     rejection 이 조용한 무반응으로 증발하는 결함류(F8·F9·#45 profile_*·P2 onClick)가
     파일마다 반복 재발했다. 사이트별 규율 대신 셸에서 구조적으로 받는다: 여기 도달한
     rejection 은 "가드를 잊은 곳"뿐이며(지역에서 잡힌 실패는 오지 않는다) alert 로
     시끄럽게 재진술한다(confirm-or-alarm). 개별 화면의 맞춤 가드는 계속 1차 방어선. */
  window.addEventListener("unhandledrejection", (e) => {
    e.preventDefault();
    const r = e.reason;
    window.alert(String((r && r.message) || r));
  });

  const navs = document.querySelectorAll(".navbtn");
  const scrs = document.querySelectorAll(".scr");

  /* 전환 시 자동 새로고침 대상(C6) — 다른 화면의 변경(에디터 자동등록·삭제 등)이 부팅
     스냅샷에 가려지는 고착 방지. 백엔드에 _do_refresh 가 있는 컨트롤러만 화이트리스트로
     보낸다(미지 액션은 백엔드가 loud 거절하므로 무차별 dispatch 금지). 수동 새로고침
     버튼은 유지된다(명시적 재스캔 경로). run/matrix 도 레지스트리 파생 작업 목록을
     스냅샷으로 그리므로 포함한다 — 빼면 에디터에서 막 저장한 작업이 주 실행 표면에
     안 보인다(r4). */
  const REFRESH_ON_NAV = ["home", "pool", "tpl", "run", "matrix"];

  /* 화면 전환 — 레일 클릭과 허브(홈) 카드의 프로그램적 이동이 공유하는 단일 경로. */
  function go(id) {
    navs.forEach((x) => x.setAttribute("aria-current", x.dataset.scr === id ? "true" : "false"));
    scrs.forEach((s) => s.classList.toggle("on", s.id === "scr-" + id));
    // pywebview 미준비(브라우저 단독 미리보기·부팅 직전)면 새로고칠 백엔드 자체가 없다.
    if (REFRESH_ON_NAV.includes(id) && window.pywebview && window.Bridge) {
      // 실패는 조용히 삼키지 않는다(confirm-or-alarm) — 화면은 이미 전환됐고 스냅샷만 낡음.
      Bridge.call(id, "refresh", {}).catch((err) =>
        window.alert(String((err && err.message) || err)));
    }
  }
  navs.forEach((b) => b.addEventListener("click", () => go(b.dataset.scr)));
  // 홈(허브)이 카드/버튼에서 워크플로 화면으로 보내는 진입점(home.js 가 소비).
  window.Nav = { go };

  // 사이드 패널 접기(#18/9B2AB35D-A) — 좁은 창에서 작업 영역 확장(반응형). 셸 전역.
  const railToggle = document.getElementById("railToggle");
  if (railToggle) {
    railToggle.addEventListener("click", () =>
      document.querySelector(".app").classList.toggle("rail-collapsed"));
  }

  // 테마 전환(System→Light→Dark) — 셸 전역. Theme(theme.js)가 data-theme 를 소유하고
  // 브리지로 Python 설정에 영속(#74), 여기선 배선 + 레일 라벨을 현재 모드로 동기화만 한다.
  const themeToggle = document.getElementById("themeToggle");
  const themeLabel = document.getElementById("themeLabel");
  const THEME_TEXT = { system: "시스템", light: "라이트", dark: "다크" };
  function syncThemeLabel() {
    if (themeLabel && window.Theme) themeLabel.textContent = THEME_TEXT[window.Theme.current()];
  }
  if (themeToggle && window.Theme) {
    themeToggle.addEventListener("click", () => { window.Theme.toggle(); syncThemeLabel(); });
    syncThemeLabel();  // 부팅 시 loaded 핸들러(app.py)가 주입한 초기 모드를 라벨에 반영.
  }

  // pywebview.api 준비 후 실화면 초기화(브라우저 단독 미리보기에선 안 뜸 — 정상).
  window.addEventListener("pywebviewready", () => {
    if (window.HomeScreen) window.HomeScreen.init();
    if (window.TxtScreen) window.TxtScreen.init();
    if (window.EditorScreen) window.EditorScreen.init();
    if (window.RunScreen) window.RunScreen.init();
    if (window.MatrixScreen) window.MatrixScreen.init();
    if (window.TemplateScreen) window.TemplateScreen.init();
    if (window.PoolScreen) window.PoolScreen.init();  // 데이터 관리(#26 #4)
  });
})();
