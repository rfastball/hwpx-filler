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

type Payload = Record<string, unknown>;
type Prepared = {
  ok: boolean; error?: string; needs_confirm: boolean; confirm_text: string;
  target_screen: string; transition_token?: string;
};

const RETRY = "튜토리얼 전환을 다시 시도하세요.";
const HOST_TRANSITIONS = ["start", "select", "restart", "resume", "exit"];

/** The host preflight request: guided moves (navigate, return_to_step) ask as `navigate` with their destination. */
function preflightRequest(screen: string, action: string, payload: Payload, guided: boolean, destination: unknown) {
  return { screen, action: guided ? "navigate" : action,
    ...(typeof payload.scenario_id === "string" ? { scenario_id: payload.scenario_id } : {}),
    ...(guided ? { destination_screen: destination } : {}) };
}

/** The host preflight answer, or the retry error when it refused or does not match the asked transition. */
function preparedTransition(prepared: Prepared | null, guided: boolean, destination: unknown): Prepared {
  if (!prepared?.ok) throw new Error(prepared?.error || RETRY);
  if (typeof prepared.target_screen !== "string" || (!guided && typeof prepared.transition_token !== "string")
      || (guided && prepared.target_screen !== destination)) throw new Error(RETRY);
  return prepared;
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

  /** Confirm (when asked), close the overlays, then leave for the target screen; false = the user or a screen stopped it. */
  async function enterTarget(prepared: Prepared): Promise<boolean> {
    if (prepared.needs_confirm && !(await deps.confirm({
      title: "연습 중", body: prepared.confirm_text, confirmLabel: "확인", cancelLabel: "취소", danger: false,
    }))) return false;
    if (!(await deps.closeOverlays())) return false;
    return moveTo(prepared.target_screen);
  }

  /** The host commits the prepared transition; the shell follows to the screen it names. */
  async function commit(action: string, payload: Payload, prepared: Prepared): Promise<unknown> {
    const result = await deps.dispatch(action, { ...payload, transition_token: prepared.transition_token }) as {
      ok?: boolean; error?: string; screen?: string; notice?: string;
    } | null;
    if (!result?.ok || typeof result.screen !== "string") throw new Error(result?.error || RETRY);
    deps.go(result.screen);
    if (result.notice) deps.notice(result.notice);
    return result;
  }

  async function transition(action: string, payload: Payload, guided: boolean): Promise<unknown> {
    const screen = deps.currentScreen();
    if (!screen) throw new Error(RETRY);
    const destination = guided ? payload.screen : undefined;
    if (guided && typeof destination !== "string") throw new Error(RETRY);
    if (guided && screen === destination) return { ok: true };
    await deps.flush(screen);
    const prepared = preparedTransition(await deps.dispatch("preflight",
      preflightRequest(screen, action, payload, guided, destination)) as Prepared | null, guided, destination);
    if (!(await enterTarget(prepared))) return { cancelled: true };
    if (guided) return { ok: true };
    return commit(action, payload, prepared);
  }

  const session = async (action: string, payload: Record<string, unknown> = {}): Promise<unknown> => {
    const guided = action === "navigate" || action === "return_to_step";
    if (!guided && !HOST_TRANSITIONS.includes(action)) {
      return deps.dispatch(action, payload);
    }
    return transition(action, payload, guided);
  };
  return session;
}
