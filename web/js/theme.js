/* 테마 전환 헬퍼 — esc.js·preserve.js·modal.js 와 같은 결의 window 스코프 IIFE.

   System → Light → Dark 3상태 순환. documentElement 의 data-theme 속성이 tokens.css 의
   :root[data-theme="dark"] / :not([data-theme="light"]) override 를 켠다:
     - "system"(속성 없음) → @media(prefers-color-scheme) 가 OS 를 따른다.
     - "light"/"dark"        → 앱 토글이 OS 를 양방향으로 덮는다.
   앱(pywebview)에서 선택은 오리진 비의존 Python 설정(app.py set_theme → settings.json)에 영속(#74):
   부팅 시 Python 이 창을 숨긴 채 loaded 에서 저장 테마를 data-theme 로 주입하고 show 하므로(FOUC
   은닉) localStorage 없이도 콜드부트를 넘어 유지된다.

   브라우저 단독 프리뷰(브리지 부재)는 **의도적으로 미영속**이다(#75 리뷰4 #4/#7 결정): 프리뷰를
   pre-paint 로 영속하려면 head 동기 인라인의 localStorage 판독이 필요한데, 그것이 바로 #74 가
   없앤 오리진 결합 경로다(앱에선 무해한 no-op이라도 test_theme_persistence_is_origin_independent
   가 index.html 의 그 판독을 금한다). 프리뷰는 개발 전용이므로 새로고침 간 테마 기억을 포기하고
   오리진 비의존 불변식을 지킨다. 이 파일은 토글·라벨 동기와 앱 영속 왕복만 담당한다. */
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
    // 관심자(app.js 레일 라벨 등)에게 재진술 — 토글이든 부팅 주입(app.py loaded)이든 같은 신호.
    window.dispatchEvent(new CustomEvent("hwpx:themechange"));
  }

  function set(mode) {
    apply(mode);
    // 브리지 부재(브라우저 단독 프리뷰)면 영속 생략 — 셸 상태만 갱신, 무해 통과(위 파일 주석 참조).
    if (window.pywebview && window.pywebview.api) {
      // 동기 throw(Bridge 부재 등)도 삼키지 않는다(confirm-or-alarm) — 비동기 rejection 은
      // app.js 의 unhandledrejection 백스톱이 받는다.
      try { window.Bridge.setTheme(current()); }
      catch (e) { window.alert(String((e && e.message) || e)); }
    }
    return current();
  }

  function toggle() {
    return set(ORDER[(ORDER.indexOf(current()) + 1) % ORDER.length]);
  }

  // apply 는 부팅 주입 경로(app.py _apply_theme_then_show)가 영속 없이 쓴다 — set 은 영속 포함.
  window.Theme = { set: set, toggle: toggle, current: current, apply: apply };
})();
