/*
 * pywebview가 숨은 창에 테마·개인화를 주입한 뒤 보여 주는 부팅 계약만 만족한다.
 * editor/job initial·dispatch를 호출하지 않는 것이 이 백지 랩의 핵심 불변식이다.
 */
(function () {
  const THEMES = new Set(["system", "light", "dark"]);

  function applyTheme(mode) {
    const next = THEMES.has(mode) ? mode : "system";
    if (next === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", next);
    return next;
  }

  function applyPersonalization(state) {
    const scale = state && state.font_scale;
    document.documentElement.setAttribute(
      "data-font-scale",
      scale === "large" || scale === "larger" ? scale : "normal",
    );
    return true;
  }

  window.Theme = {
    apply: applyTheme,
    current: () => document.documentElement.getAttribute("data-theme") || "system",
  };

  window.Personalization = {
    apply: applyPersonalization,
    setFontScale(scale) {
      applyPersonalization({ font_scale: scale });
      return document.documentElement.getAttribute("data-font-scale");
    },
  };

  // Python 관측 푸시는 구현 전 단계에서 의도적으로 버린다.
  window.__push = function () {};

  window.addEventListener("pywebviewready", () => {
    document.documentElement.setAttribute("data-bridge", "ready");
  });
})();
