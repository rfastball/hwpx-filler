/* React 셸 구성 — 판정은 shell/nav, 리스너 수명은 ShellHost, 화면 집행은 executor가 진다. */
import { DEFAULT_SCREEN } from "./nav.ts";
import type { createShellNav } from "./nav.ts";
import type { ShellAttachment, ShellHostPorts } from "./host.ts";
import type { PersonalizationService } from "./preferences.ts";

type BridgePort = {
  hostReady(): boolean;
  confirmWindowClose(): Promise<unknown>;
  cancelWindowClose(): Promise<unknown>;
};

type ShellModalPort = {
  confirm(options: {
    title: string;
    body: string;
    confirmLabel: string;
    cancelLabel: string;
    danger: boolean;
  }): Promise<boolean>;
  /** 셸 설정 모달을 여는 자리 — 내용은 React portal(SettingsSheet)이 대고 여기는 개폐만 안다. */
  open(id: string, options?: { returnFocus?: EventTarget | null }): void;
};

type AppShellArgs = {
  Bridge: BridgePort;
  modal: ShellModalPort;
  /* Theme 는 더 이상 셸의 인자가 아니다 — 테마를 읽고 쓰는 유일한 표면이 설정 모달로
     옮겨갔고, 그 컴포넌트는 bootstrap 이 직접 서비스를 주입한다(셸을 경유하지 않는다). */
  Personalization: PersonalizationService;
  shellNav: ReturnType<typeof createShellNav>;
  initSequence: ReadonlyArray<() => unknown>;
  /** 현재 화면 재당김 — 포커스 복귀가 부른다(#932 B5). 실패는 삼킨다: 갱신은 편의이지
   *  계약이 아니고, 못 얻으면 다음 동작의 push 가 같은 값을 싣는다. */
  refreshScreen: (screen: string) => Promise<unknown>;
};

export function createAppShell(args: AppShellArgs) {
  const {
    Bridge, modal, Personalization, shellNav, initSequence, refreshScreen,
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

  /* 셸 전역 설정의 유일한 문 — ⚙ 하나가 설정 모달을 연다(#957 계열 단순화 슬라이스 D).
     종전에는 순환 토글 둘(`#themeToggle`·`#fontScaleToggle`)이 여기 서서 클릭마다 값을 한 칸
     돌리고 라벨 span 을 손으로 동기했다. 그 라벨 동기가 셸 `catchUp` 의 유일한 소비자이기도
     했다 — 지금은 값 표시가 React 세그먼트의 `aria-pressed` 이고 그 값은 서비스 사건 구독에서
     파생되므로, 놓침 창을 셸이 따라잡을 이유가 사라졌다. */
  const settingsOpen = document.getElementById("settingsOpen");

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
  /* 복귀점은 **트리거 자신**이다 — 닫으면 초점이 ⚙ 로 돌아온다(모달 파사드의 기본값은
     `document.activeElement` 라 대개 같지만, 명시로 넘겨 클릭 경로 밖에서도 같게 만든다). */
  if (settingsOpen !== null) {
    attach(settingsOpen, "click", () => { modal.open("settingsModal", { returnFocus: settingsOpen }); });
  }
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
    /* 따라잡기 소비자 0 — 셸이 손으로 동기하던 라벨 둘이 설정 모달의 파생 표시로 옮겨갔다.
       포트는 남긴다: 「부착 전에 지나간 사건」이라는 결함류는 그대로 있고, 다음 셸 표시가
       생기면 그 자리에서 다시 등록한다. */
    catchUp: [],
    boot: {
      win: window,
      hostReady: () => Bridge.hostReady(),
      initSequence: initSequence.map((step) => () => { void step(); }),
    },
  };
  return { Nav, AppCloseGuard, shellHost };
}
