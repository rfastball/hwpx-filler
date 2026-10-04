/** 연습 전환은 호스트 사전 검사 → 기존 화면 이탈 → 호스트 확정 순서로만 진행한다. */
import type { OverlayEngine } from "../overlay/engine.ts";

export async function closeTutorialOverlays(overlay: Pick<OverlayEngine,
  "depth" | "topHost" | "requestClose" | "isOpen" | "subscribe">): Promise<boolean> {
  const waitFor = (ready: () => boolean) => new Promise<void>((resolve) => {
    if (ready()) { resolve(); return; }
    const unsubscribe = overlay.subscribe(() => {
      if (ready()) { unsubscribe(); resolve(); }
    });
  });
  while (overlay.depth() > 0) {
    const host = overlay.topHost();
    if (host === null) {
      await waitFor(() => overlay.topHost() !== null || overlay.depth() === 0);
      continue;
    }
    if (overlay.requestClose(host) === "consumed") return false;
    await waitFor(() => !overlay.isOpen(host));
  }
  return true;
}

export function createTutorialSession(deps: {
  dispatch(action: string, payload: Record<string, unknown>): Promise<unknown>;
  currentScreen(): string | null;
  go(screen: string): void;
  leave(screen: string, target: string): Promise<void>;
  flush(screen: string): Promise<unknown>;
  closeOverlays(): Promise<boolean>;
  confirm(options: { title: string; body: string; confirmLabel: string; cancelLabel: string; danger: boolean }): Promise<boolean>;
  notice(message: string): void;
}) {
  const retry = "튜토리얼 전환을 다시 시도하세요.";
  async function moveTo(target: string): Promise<boolean> {
    const screen = deps.currentScreen();
    if (screen === target) return true;
    if (screen === "editor" || screen === "workbench" || screen === "authoring") {
      await deps.leave(screen, target);
    } else {
      deps.go(target);
    }
    return deps.currentScreen() === target;
  }

  return async (action: string, payload: Record<string, unknown> = {}): Promise<unknown> => {
    const guided = action === "navigate" || action === "return_to_step";
    if (!guided && !["start", "select", "restart", "resume", "exit"].includes(action)) {
      return deps.dispatch(action, payload);
    }

    const screen = deps.currentScreen();
    if (!screen) throw new Error(retry);
    const destination = guided ? payload.screen : undefined;
    if (guided && typeof destination !== "string") throw new Error(retry);
    if (guided && screen === destination) return { ok: true };
    await deps.flush(screen);
    const request = { screen, action: guided ? "navigate" : action,
      ...(typeof payload.scenario_id === "string" ? { scenario_id: payload.scenario_id } : {}),
      ...(guided ? { destination_screen: destination } : {}) };
    const prepared = await deps.dispatch("preflight", request) as {
      ok: boolean; error?: string; needs_confirm: boolean; confirm_text: string;
      target_screen: string; transition_token?: string;
    } | null;
    if (!prepared?.ok) throw new Error(prepared?.error || retry);
    if (typeof prepared.target_screen !== "string" || (!guided && typeof prepared.transition_token !== "string")
        || (guided && prepared.target_screen !== destination)) throw new Error(retry);
    if (prepared.needs_confirm && !(await deps.confirm({
      title: "연습 중", body: prepared.confirm_text, confirmLabel: "확인", cancelLabel: "취소", danger: false,
    }))) return { cancelled: true };
    if (!(await deps.closeOverlays())) return { cancelled: true };
    if (!(await moveTo(prepared.target_screen))) return { cancelled: true };
    if (guided) return { ok: true };

    const result = await deps.dispatch(action, { ...payload, transition_token: prepared.transition_token }) as {
      ok?: boolean; error?: string; screen?: string; notice?: string;
    } | null;
    if (!result?.ok || typeof result.screen !== "string") throw new Error(result?.error || retry);
    deps.go(result.screen);
    if (result.notice) deps.notice(result.notice);
    return result;
  };
}
