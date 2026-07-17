/* 테마 전환 헬퍼 — esc.js·preserve.js·modal.js 와 같은 결의 window 스코프 IIFE.

   System → Light → Dark 3상태 순환. documentElement 의 data-theme 속성이 tokens.css 의
   :root[data-theme="dark"] / :not([data-theme="light"]) override 를 켠다:
     - "system"(속성 없음) → @media(prefers-color-scheme) 가 OS 를 따른다.
     - "light"/"dark"        → 앱 토글이 OS 를 양방향으로 덮는다.
   선택은 오리진 비의존 Python 설정(app.py set_theme → settings.json)에 영속(#74). 부팅 시 Python 이
   창을 숨긴 채 loaded 에서 저장 테마를 data-theme 로 주입하고 show 하므로(FOUC 은닉), localStorage
   없이도 콜드부트를 넘어 유지된다. 이 파일은 토글·라벨 동기와 선택의 영속 왕복만 담당한다. */
(function () {
  var ORDER = ["system", "light", "dark"];

  function current() {
    var v = document.documentElement.getAttribute("data-theme");
    return v === "light" || v === "dark" ? v : "system";
  }

  function apply(mode) {
    if (mode === "light" || mode === "dark") {
      document.documentElement.setAttribute("data-theme", mode);
    } else {
      // system: 속성 제거 → @media 지배로 되돌린다.
      document.documentElement.removeAttribute("data-theme");
    }
  }

  function set(mode) {
    apply(mode);
    // 브리지 부재(브라우저 단독 프리뷰)면 영속 생략 — 셸 상태만 갱신, 무해 통과.
    if (window.pywebview && window.pywebview.api) {
      try { window.Bridge.setTheme(current()); } catch (e) { /* 무시 */ }
    }
    return current();
  }

  function toggle() {
    return set(ORDER[(ORDER.indexOf(current()) + 1) % ORDER.length]);
  }

  window.Theme = { set: set, toggle: toggle, current: current };
})();
