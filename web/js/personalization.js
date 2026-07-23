/* 셸 개인화 — 앱 글자 배율·레일 접힘·master 폭을 settings.json과 왕복한다.
   apply()는 app.py loaded 핸들러가 숨은 창에 먼저 호출하고, set*()은 사용자 조작을 즉시
   반영한 뒤 Python 설정에 영속한다. 브라우저 단독 프리뷰는 의도적으로 미영속이다. */
(function () {
  const FONT_ORDER = ["normal", "large", "larger"];
  const MASTER_MIN = 180;
  const MASTER_MAX = 420;

  function clampWidth(value) {
    return Math.max(MASTER_MIN, Math.min(MASTER_MAX, Math.round(Number(value) || 240)));
  }

  function apply(state) {
    const root = document.documentElement;
    const app = document.querySelector(".app");
    const scale = FONT_ORDER.includes(state && state.font_scale) ? state.font_scale : "normal";
    root.setAttribute("data-font-scale", scale);
    if (app) {
      app.classList.toggle("rail-collapsed", !!(state && state.rail_collapsed));
      setMasterWidth(state && state.master_width);
    }
    window.dispatchEvent(new CustomEvent("hwpx:personalizationchange"));
  }

  function currentFontScale() {
    const value = document.documentElement.getAttribute("data-font-scale");
    return FONT_ORDER.includes(value) ? value : "normal";
  }

  function persist(method, value) {
    if (window.pywebview && window.pywebview.api && window.Bridge) {
      try { window.Bridge[method](value); }
      catch (err) { window.alert(String((err && err.message) || err)); }
    }
  }

  function setFontScale(scale) {
    apply({
      font_scale: scale,
      rail_collapsed: document.querySelector(".app").classList.contains("rail-collapsed"),
      master_width: parseFloat(getComputedStyle(document.querySelector(".app")).getPropertyValue("--master-width")),
    });
    persist("setFontScale", currentFontScale());
    return currentFontScale();
  }

  function toggleFontScale() {
    return setFontScale(FONT_ORDER[(FONT_ORDER.indexOf(currentFontScale()) + 1) % FONT_ORDER.length]);
  }

  function setRailCollapsed(collapsed) {
    const app = document.querySelector(".app");
    app.classList.toggle("rail-collapsed", !!collapsed);
    window.dispatchEvent(new CustomEvent("hwpx:personalizationchange"));
    persist("setRailCollapsed", !!collapsed);
  }

  function setMasterWidth(width) {
    const value = clampWidth(width);
    document.querySelector(".app").style.setProperty("--master-width", value + "px");
    document.querySelectorAll(".master-splitter").forEach((el) =>
      el.setAttribute("aria-valuenow", String(value)));
    return value;
  }

  function saveMasterWidth(width) {
    const value = setMasterWidth(width);
    persist("setMasterWidth", value);
    return value;
  }

  window.Personalization = {
    apply, currentFontScale, toggleFontScale, setFontScale,
    setRailCollapsed, setMasterWidth, saveMasterWidth,
    masterMin: MASTER_MIN, masterMax: MASTER_MAX,
  };
})();
