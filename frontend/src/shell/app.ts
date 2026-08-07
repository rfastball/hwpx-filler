/* React 셸 구성 — 판정은 shell/nav, 리스너 수명은 ShellHost, 화면 집행은 executor가 진다. */
import { DEFAULT_SCREEN } from "./nav.ts";
import type { createShellNav } from "./nav.ts";
import type { ShellAttachment, ShellHostPorts } from "./host.ts";
import type { PersonalizationService, ThemeService } from "./preferences.ts";

type BridgePort = {
  hostReady(): boolean;
  confirmWindowClose(): Promise<unknown>;
  cancelWindowClose(): Promise<unknown>;
};

type CloseModalPort = {
  confirm(options: {
    title: string;
    body: string;
    confirmLabel: string;
    cancelLabel: string;
    danger: boolean;
  }): Promise<boolean>;
};

type AppShellArgs = {
  Bridge: BridgePort;
  modal: CloseModalPort;
  Theme: ThemeService;
  Personalization: PersonalizationService;
  shellNav: ReturnType<typeof createShellNav>;
  initSequence: ReadonlyArray<() => unknown>;
};

export function createAppShell(args: AppShellArgs) {
  const { Bridge, modal, Theme, Personalization, shellNav, initSequence } = args;
  const AppCloseGuard = {
    async prompt(state: { reasons?: unknown[] } | null | undefined): Promise<void> {
      if (!shellNav.beginClosePrompt()) return;
      const reasons = state?.reasons || [];
      try {
        const ok = await modal.confirm({
          title: "앱 종료 확인",
          body: `앱을 닫으면 다음 진행 상태가 사라집니다:\n\n• ${reasons.join("\n• ")}`
            + "\n\n그래도 종료할까요?",
          confirmLabel: "종료", cancelLabel: "계속 작업", danger: true,
        });
        if (ok) await Bridge.confirmWindowClose();
        else await Bridge.cancelWindowClose();
      } catch (error) {
        await Bridge.cancelWindowClose();
        window.alert(`종료 확인을 처리하지 못해 창을 유지합니다: ${String(
          (error as { message?: unknown })?.message || error)}`);
      } finally {
        shellNav.endClosePrompt();
      }
    },
  };

  const go = (id: string, options?: { force?: boolean; refreshed?: boolean }): void => {
    shellNav.go(id, options);
  };
  const Nav = {
    go,
    refresh: (id: string) => shellNav.refresh(id),
    currentScreen: () => shellNav.currentScreen(),
  };
  go(DEFAULT_SCREEN);

  const fontLabel = document.getElementById("fontScaleLabel");
  const fontScaleToggle = document.getElementById("fontScaleToggle");
  const themeToggle = document.getElementById("themeToggle");
  const themeLabel = document.getElementById("themeLabel");
  const fontText = { normal: "기본", large: "크게 (125%)", larger: "더 크게 (150%)" };
  const themeText = { system: "시스템", light: "라이트", dark: "다크" };

  function syncPersonalizationLabels(): void {
    if (fontLabel !== null) fontLabel.textContent = fontText[Personalization.currentFontScale()];
  }
  function syncThemeLabel(): void {
    if (themeLabel !== null) themeLabel.textContent = themeText[Theme.current()];
  }
  syncPersonalizationLabels();
  syncThemeLabel();

  const attachments: ShellAttachment[] = [];
  const attach = (target: ShellAttachment["target"], type: string, run: (event: Event) => void): void => {
    attachments.push({
      target, type,
      handler: (event: Event) => run(event),
    });
  };
  attach(window, "unhandledrejection", (event) => {
    const rejection = event as PromiseRejectionEvent;
    rejection.preventDefault();
    window.alert(String((rejection.reason as { message?: unknown })?.message || rejection.reason));
  });
  document.querySelectorAll<HTMLElement>(".navbtn").forEach((button) =>
    attach(button, "click", () => go(String(button.dataset.scr || ""))));
  if (fontScaleToggle !== null) attach(fontScaleToggle, "click", () => { Personalization.toggleFontScale(); });
  attach(window, "hwpx:personalizationchange", syncPersonalizationLabels);
  if (themeToggle !== null) attach(themeToggle, "click", () => { Theme.toggle(); });
  attach(window, "hwpx:themechange", syncThemeLabel);

  document.querySelectorAll<HTMLElement>(".master-splitter").forEach((splitter) => {
    attach(splitter, "pointerdown", (rawEvent) => {
      const event = rawEvent as PointerEvent;
      if (event.button !== 0) return;
      const app = document.querySelector<HTMLElement>(".app");
      if (app === null) throw new Error("master splitter 대상(.app)이 없습니다.");
      const startX = event.clientX;
      const startWidth = parseFloat(getComputedStyle(app).getPropertyValue("--master-width")) || 240;
      splitter.setPointerCapture(event.pointerId);
      document.body.classList.add("resizing-master");
      const move = (next: PointerEvent): void => {
        Personalization.setMasterWidth(startWidth + next.clientX - startX);
      };
      const finish = (next: PointerEvent): void => {
        splitter.removeEventListener("pointermove", move);
        splitter.removeEventListener("pointerup", finish);
        splitter.removeEventListener("pointercancel", finish);
        document.body.classList.remove("resizing-master");
        if (splitter.hasPointerCapture(next.pointerId)) splitter.releasePointerCapture(next.pointerId);
        Personalization.saveMasterWidth(
          parseFloat(getComputedStyle(app).getPropertyValue("--master-width")));
      };
      splitter.addEventListener("pointermove", move);
      splitter.addEventListener("pointerup", finish);
      splitter.addEventListener("pointercancel", finish);
    });
    attach(splitter, "keydown", (rawEvent) => {
      const event = rawEvent as KeyboardEvent;
      const app = document.querySelector<HTMLElement>(".app");
      if (app === null) throw new Error("master splitter 대상(.app)이 없습니다.");
      const current = parseFloat(getComputedStyle(app).getPropertyValue("--master-width")) || 240;
      let next = current;
      if (event.key === "ArrowLeft") next -= 10;
      else if (event.key === "ArrowRight") next += 10;
      else if (event.key === "Home") next = Personalization.masterMin;
      else if (event.key === "End") next = Personalization.masterMax;
      else return;
      event.preventDefault();
      Personalization.saveMasterWidth(next);
    });
  });

  const shellHost: ShellHostPorts = {
    nav: shellNav,
    attachments,
    catchUp: [syncPersonalizationLabels, syncThemeLabel],
    boot: {
      win: window,
      hostReady: () => Bridge.hostReady(),
      initSequence: initSequence.map((step) => () => { void step(); }),
    },
  };
  return { Nav, AppCloseGuard, shellHost };
}
