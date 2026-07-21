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
     버튼은 유지된다(명시적 재스캔 경로). 「작업」 화면도 레지스트리 파생 작업 목록(좌 master
     목록)을 스냅샷으로 그리므로 포함한다 — 빼면 에디터에서 막 저장한 작업이 좌 목록에 안
     보인다. 실행 화면(run)은 사망(슬라이스 3)이라 목록에서 제거. */
  const REFRESH_ON_NAV = ["home", "pool", "tpl", "job", "draft"];

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
    // 「작업」 복귀 시 편집 호스트의 에디터도 재렌더(#138 리뷰 F12) — job refresh 는 좌 목록만
    // 갱신하고 편집 모드 1단계 피커는 놔둬, 관리 화면에서 바뀐 공유 그룹 접힘이 stale 로 남는다.
    if (id === "job" && window.EditorScreen && window.EditorScreen.rerender) {
      window.EditorScreen.rerender();
    }
    // txt 템플릿 드롭다운은 스냅샷이 아니라 initial 1회로 채워지므로, 다른 화면이 라이브러리에
    // 더한 템플릿(빠른 기안 승격 #135·관리 화면 신규/가져오기)이 진입해도 안 보인다 — 진입
    // 시 다시 읽는다(refresh 디스패치로는 못 고친다: 목록이 스냅샷 소유가 아니다).
    if (id === "txt" && window.TxtScreen && window.TxtScreen.refreshTemplates) {
      window.TxtScreen.refreshTemplates().catch((err) =>
        window.alert(String((err && err.message) || err)));
    }
  }
  // 레일 「작업 에디터」 과도기 심은 항목 사망(슬라이스 5 삭제 PR)과 함께 제거 — 편집
  // 진입은 EditorEntry.land 소비처(홈·템플릿 관리·작업 ⋮)가 담당한다.
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
    themeToggle.addEventListener("click", () => { window.Theme.toggle(); });
    // 라벨 동기는 themechange 단일 경로 — 토글이든 부팅 주입(app.py loaded→Theme.apply)이든
    // 같은 신호로 반영된다. 이 스크립트는 주입 **전**(body 말미)에 돌므로 직접 호출은 기본
    // system 라벨만 세우고, 저장 테마는 주입 시 이벤트로 재동기된다(#74 라벨 어긋남 방지).
    window.addEventListener("hwpx:themechange", syncThemeLabel);
    syncThemeLabel();
  }

  // pywebview.api 준비 후 실화면 초기화(브라우저 단독 미리보기에선 안 뜸 — 정상).
  window.addEventListener("pywebviewready", () => {
    if (window.HomeScreen) window.HomeScreen.init();
    if (window.TxtScreen) window.TxtScreen.init();
    if (window.QuickDraftScreen) window.QuickDraftScreen.init();  // 빠른 기안(#90 슬라이스 7)
    if (window.EditorScreen) window.EditorScreen.init();
    if (window.JobScreen) window.JobScreen.init();  // 「작업」 화면(#90) — 유일 생성 표면
    if (window.DraftScreen) window.DraftScreen.init();  // 「기안」 화면(#148 슬라이스 2b) — TXT 작업-앵커
    if (window.TemplateScreen) window.TemplateScreen.init();
    if (window.PoolScreen) window.PoolScreen.init();  // 데이터 관리(#26 #4)
  });
})();
