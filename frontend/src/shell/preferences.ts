/* 셸 theme·personalization — React ShellHost가 수명주기를 소유하고 이 서비스는
   documentElement/.app에 현재 설정을 집행한다. Python settings 왕복 의미는 기존과 같다. */

type SettingsBridge = {
  hostReady(): boolean;
  setTheme(mode: string): unknown;
  setFontScale(scale: string): unknown;
  setMasterWidth(width: number): unknown;
};

type FactoryArgs = { bridge: SettingsBridge };

export function createTheme({ bridge }: FactoryArgs) {
  const order = ["system", "light", "dark"] as const;
  type ThemeMode = typeof order[number];

  function current(): ThemeMode {
    const value = document.documentElement.getAttribute("data-theme");
    return value === "light" || value === "dark" ? value : "system";
  }

  function apply(mode: string): void {
    if (mode === "light" || mode === "dark") {
      document.documentElement.setAttribute("data-theme", mode);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
    window.dispatchEvent(new CustomEvent("hwpx:themechange"));
  }

  function set(mode: string): ThemeMode {
    apply(mode);
    if (bridge.hostReady()) {
      try { bridge.setTheme(current()); }
      catch (error) { window.alert(String((error as { message?: unknown })?.message || error)); }
    }
    return current();
  }

  function toggle(): ThemeMode {
    return set(order[(order.indexOf(current()) + 1) % order.length]);
  }

  return { set, toggle, current, apply };
}

export function createPersonalization({ bridge }: FactoryArgs) {
  const fontOrder = ["normal", "large", "larger"] as const;
  type FontScale = typeof fontOrder[number];
  const masterMin = 180;
  const masterMax = 420;

  function appElement(): HTMLElement {
    const app = document.querySelector<HTMLElement>(".app");
    if (app === null) throw new Error("셸 개인화 대상(.app)이 없습니다.");
    return app;
  }

  function clampWidth(value: unknown): number {
    return Math.max(masterMin, Math.min(masterMax, Math.round(Number(value) || 240)));
  }

  function currentFontScale(): FontScale {
    const value = document.documentElement.getAttribute("data-font-scale");
    return fontOrder.includes(value as FontScale) ? value as FontScale : "normal";
  }

  function setMasterWidth(width: unknown): number {
    const value = clampWidth(width);
    appElement().style.setProperty("--master-width", `${value}px`);
    document.querySelectorAll<HTMLElement>(".master-splitter").forEach((element) =>
      element.setAttribute("aria-valuenow", String(value)));
    return value;
  }

  function apply(state: { font_scale?: unknown; master_width?: unknown } | null | undefined): void {
    const requested = state?.font_scale;
    const scale = fontOrder.includes(requested as FontScale) ? requested as FontScale : "normal";
    document.documentElement.setAttribute("data-font-scale", scale);
    setMasterWidth(state?.master_width);
    window.dispatchEvent(new CustomEvent("hwpx:personalizationchange"));
  }

  function persist(method: "setFontScale" | "setMasterWidth", value: string | number): void {
    if (!bridge.hostReady()) return;
    try {
      if (method === "setFontScale") bridge.setFontScale(String(value));
      else bridge.setMasterWidth(Number(value));
    } catch (error) {
      window.alert(String((error as { message?: unknown })?.message || error));
    }
  }

  function setFontScale(scale: string): FontScale {
    apply({
      font_scale: scale,
      master_width: parseFloat(getComputedStyle(appElement()).getPropertyValue("--master-width")),
    });
    persist("setFontScale", currentFontScale());
    return currentFontScale();
  }

  function toggleFontScale(): FontScale {
    return setFontScale(fontOrder[(fontOrder.indexOf(currentFontScale()) + 1) % fontOrder.length]);
  }

  function saveMasterWidth(width: unknown): number {
    const value = setMasterWidth(width);
    persist("setMasterWidth", value);
    return value;
  }

  return {
    apply, currentFontScale, toggleFontScale, setFontScale, setMasterWidth, saveMasterWidth,
    masterMin, masterMax,
  };
}

export type ThemeService = ReturnType<typeof createTheme>;
export type PersonalizationService = ReturnType<typeof createPersonalization>;
