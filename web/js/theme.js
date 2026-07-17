/* 테마 전환 헬퍼 — esc.js·preserve.js·modal.js 와 같은 결의 window 스코프 IIFE.

   System → Light → Dark 3상태 순환. documentElement 의 data-theme 속성이 tokens.css 의
   :root[data-theme="dark"] / :not([data-theme="light"]) override 를 켠다:
     - "system"(속성 없음) → @media(prefers-color-scheme) 가 OS 를 따른다.
     - "light"/"dark"        → 앱 토글이 OS 를 양방향으로 덮는다.
   선택은 localStorage 에 영속(app.py 가 private_mode=False+storage_path 로 세션 간 지속화).
   FOUC 방지 인라인 스크립트(index.html <head>)가 첫 페인트 전 같은 키를 동기 되읽어 적용하므로,
   이 파일은 body 말미 로드로 충분하다(토글·라벨 동기화 담당). 브리지 무관 — 순수 프론트 셸 상태. */
(function () {
  var KEY = "hwpxfiller.theme";
  var ORDER = ["system", "light", "dark"];

  function current() {
    var v = document.documentElement.getAttribute("data-theme");
    return v === "light" || v === "dark" ? v : "system";
  }

  function set(mode) {
    if (mode === "light" || mode === "dark") {
      document.documentElement.setAttribute("data-theme", mode);
      try { localStorage.setItem(KEY, mode); } catch (e) { /* private/미지원 — 무시 */ }
    } else {
      // system: 속성 제거 → @media 지배로 되돌린다.
      document.documentElement.removeAttribute("data-theme");
      try { localStorage.removeItem(KEY); } catch (e) { /* 무시 */ }
    }
    return current();
  }

  function toggle() {
    return set(ORDER[(ORDER.indexOf(current()) + 1) % ORDER.length]);
  }

  window.Theme = { set: set, toggle: toggle, current: current };
})();
