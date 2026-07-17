/* 테마 전환 헬퍼 — esc.js·preserve.js·modal.js 와 같은 결의 window 스코프 IIFE.

   System → Light → Dark 3상태 순환. documentElement 의 data-theme 속성이 tokens.css 의
   :root[data-theme="dark"] / :not([data-theme="light"]) override 를 켠다:
     - "system"(속성 없음) → @media(prefers-color-scheme) 가 OS 를 따른다.
     - "light"/"dark"        → 앱 토글이 OS 를 양방향으로 덮는다.
   앱(pywebview)에서 선택은 오리진 비의존 Python 설정(app.py set_theme → settings.json)에 영속(#74):
   부팅 시 Python 이 창을 숨긴 채 loaded 에서 저장 테마를 data-theme 로 주입하고 show 하므로(FOUC
   은닉) localStorage 없이도 콜드부트를 넘어 유지된다. 브리지가 없는 **브라우저 단독 프리뷰** 에선
   Python 이 없으므로 localStorage 로 대체 영속·부팅 복원한다(#75 리뷰 #4) — 앱은 이 분기 미도달.
   이 파일은 토글·라벨 동기와 선택의 영속 왕복만 담당한다. */
(function () {
  var ORDER = ["system", "light", "dark"];
  var STORAGE_KEY = "hwpxfiller.theme";  // 브라우저 단독 프리뷰 전용 영속 키(앱은 미사용, 아래)

  function current() {
    var v = document.documentElement.getAttribute("data-theme");
    return v === "light" || v === "dark" ? v : "system";
  }

  function hasBridge() {
    return !!(window.pywebview && window.pywebview.api);
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
    if (hasBridge()) {
      // 앱(pywebview): 영속은 오리진 비의존 Python 설정(settings.json)에 — set_theme 왕복.
      // 동기 throw(Bridge 부재 등)도 삼키지 않는다(confirm-or-alarm) — 비동기 rejection 은
      // app.js 의 unhandledrejection 백스톱이 받는다.
      try { window.Bridge.setTheme(current()); }
      catch (e) { window.alert(String((e && e.message) || e)); }
    } else {
      // 브라우저 단독 프리뷰(Python 없음): localStorage 로 대체 영속 — 프리뷰가 새로고침을
      // 넘어 선택을 기억한다(#75 리뷰 #4 회귀 복원). 오리진 결합은 프리뷰 한정이라 무해하고,
      // 앱은 hasBridge()=true 라 이 분기에 절대 도달하지 않는다(#74 오리진 비의존 유지).
      try { window.localStorage.setItem(STORAGE_KEY, current()); } catch (e) { /* 프리뷰 무해 통과 */ }
    }
    return current();
  }

  function toggle() {
    return set(ORDER[(ORDER.indexOf(current()) + 1) % ORDER.length]);
  }

  // apply 는 부팅 주입 경로(app.py _apply_theme_then_show)가 영속 없이 쓴다 — set 은 영속 포함.
  window.Theme = { set: set, toggle: toggle, current: current, apply: apply };

  // 프리뷰 부팅 복원: 브리지가 없으면(브라우저 단독) 저장 선택을 적용한다. 앱은 Python 이
  // loaded 에서 Theme.apply 로 주입하므로 이 경로에 의존하지 않고, 앱의 localStorage 는 늘
  // 비어 있어(이 파일이 브리지 있을 땐 안 씀) 여기 도달해도 무해한 no-op 이다.
  if (!hasBridge()) {
    try {
      var saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved === "light" || saved === "dark") apply(saved);
    } catch (e) { /* localStorage 접근 불가(프라이버시 모드 등) — 프리뷰 무해 통과 */ }
  }
})();
