/* 셸 theme·personalization — React ShellHost가 수명주기를 소유하고 이 서비스는
   documentElement/.app에 현재 설정을 집행한다. Python settings 왕복 의미는 기존과 같다. */

type SettingsBridge = {
  hostReady(): boolean;
  setTheme(mode: string): unknown;
  setFontScale(scale: string): unknown;
  setMasterWidth(width: number): unknown;
  setAuthoringWidth(panel: string, width: number): unknown;
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

/** 저작 작업대 패널 폭의 범위(기준 px = 뿌리 글자 16px 기준). Python
 *  `settings.AUTHORING_WIDTH_BOUNDS` 와 같은 값이다 — 저장 거절이 곧 드리프트 경보다. */
export const AUTHORING_WIDTH_BOUNDS = {
  outline: { min: 176, max: 384 },
  properties: { min: 224, max: 448 },
} as const;
export type AuthoringPanel = keyof typeof AUTHORING_WIDTH_BOUNDS;

/** 기준 px → 화면 값. rem 이라 글자 배율(125%·150%)을 따라 함께 자란다. */
export function authoringWidthCss(width: number): string {
  return `${width / 16}rem`;
}

export function clampAuthoringWidth(panel: AuthoringPanel, value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  const { min, max } = AUTHORING_WIDTH_BOUNDS[panel];
  return Math.max(min, Math.min(max, Math.round(number)));
}

export function createPersonalization({ bridge }: FactoryArgs) {
  const fontOrder = ["normal", "large", "larger"] as const;
  type FontScale = typeof fontOrder[number];
  const masterMin = 180;
  const masterMax = 420;
  /* 저작 패널 폭 — null 은 「저장값 없음」이라 CSS 의 창 폭 비례 기본값이 선다. */
  const authoringWidths: Record<AuthoringPanel, number | null> = { outline: null, properties: null };

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

  /** 저작 패널 폭을 화면에 싣는다(영속하지 않는다 — 끌기 중 왕복 금지). */
  function setAuthoringWidth(panel: AuthoringPanel, width: unknown): number | null {
    const value = clampAuthoringWidth(panel, width);
    authoringWidths[panel] = value;
    const app = appElement();
    if (value === null) app.style.removeProperty(`--authoring-${panel}-w`);
    else app.style.setProperty(`--authoring-${panel}-w`, authoringWidthCss(value));
    return value;
  }

  function authoringWidth(panel: AuthoringPanel): number | null {
    return authoringWidths[panel];
  }

  function apply(state: {
    font_scale?: unknown; master_width?: unknown; authoring_widths?: unknown;
  } | null | undefined): void {
    const requested = state?.font_scale;
    const scale = fontOrder.includes(requested as FontScale) ? requested as FontScale : "normal";
    document.documentElement.setAttribute("data-font-scale", scale);
    setMasterWidth(state?.master_width);
    /* 저작 폭은 **실려 온 때만** 다시 쓴다 — 배율 동사(setFontScale)는 이 키 없이 apply 를
       부르므로, 여기서 비우면 배율을 바꿀 때마다 사용자가 맞춘 폭이 사라진다. */
    if (state && "authoring_widths" in state) {
      const widths = state.authoring_widths as Record<string, unknown> | null | undefined;
      for (const panel of Object.keys(AUTHORING_WIDTH_BOUNDS) as AuthoringPanel[]) {
        setAuthoringWidth(panel, widths?.[panel]);
      }
    }
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

  /** 분할선을 놓았을 때 — 화면에 싣고 Python 설정에 남긴다. */
  function saveAuthoringWidth(panel: AuthoringPanel, width: unknown): number | null {
    const value = setAuthoringWidth(panel, width);
    if (value === null || !bridge.hostReady()) return value;
    const alarm = (error: unknown) => window.alert(String((error as { message?: unknown })?.message || error));
    /* 브리지는 Promise 를 돌려준다 — 저장 거절(범위 밖)이 삼켜지지 않게 거절도 경보로 올린다. */
    try {
      void Promise.resolve(bridge.setAuthoringWidth(panel, value)).catch(alarm);
    } catch (error) {
      alarm(error);
    }
    return value;
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
    masterMin, masterMax, authoringWidth, setAuthoringWidth, saveAuthoringWidth,
  };
}

export type ThemeService = ReturnType<typeof createTheme>;
export type PersonalizationService = ReturnType<typeof createPersonalization>;
