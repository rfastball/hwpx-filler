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
  /** 현재 화면 재당김 — 포커스 복귀가 부른다(#932 B5). 실패는 삼킨다: 갱신은 편의이지
   *  계약이 아니고, 못 얻으면 다음 동작의 push 가 같은 값을 싣는다. */
  refreshScreen: (screen: string) => Promise<unknown>;
};

export function createAppShell(args: AppShellArgs) {
  const {
    Bridge, modal, Theme, Personalization, shellNav, initSequence, refreshScreen,
  } = args;
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
  /* **창으로 돌아오면 현재 화면을 다시 묻는다**(#932 B5). 앱 밖에서 일어난 변화 —
     한글에서 템플릿을 고치는 것이 정확히 그것이다 — 는 push 를 내지 않으므로, 조치가
     있을 때만 서는 구획(「템플릿 조치 필요」)이 다음 상호작용까지 침묵할 창이 생겼다.
     주기 검사가 아니라 **사용자가 돌아온 순간** 한 번이라 유휴 비용이 0 이고, 그 갱신을
     놓쳐도 실행 게이트가 드리프트를 blocker 로 잡는다(두 층이 같은 사실을 진다). */
  attach(window, "focus", () => {
    const screen = shellNav.currentScreen();
    if (screen === null) return;  // 아직 아무 화면도 안 선 부팅 창 — 물을 대상이 없다
    void Promise.resolve(refreshScreen(screen)).catch(() => {});
  });

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
