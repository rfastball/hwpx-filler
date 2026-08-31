/* R4-02 편집기 진입 seam 의 React 구현(legacy `frontend/js/editor_entry.js`).

   공개 표면 5키가 그 계약이고(`EditorEntryPort`), 호출자(라이브러리·작업 화면)는 구현이
   바뀌어도 고치지 않는다. 지키는 것:

   - **앞선 편집 세션의 미저장 변경은 묻지 않고 버린다**(자동 버리기 계약). 편집기 한 세션에서
     하는 작업량은 확인을 요구할 만큼 크지 않아, 진입마다 서던 폐기 확인은 마찰만 남겼다.
     걷힌 것은 **확인뿐**이다 — 실패는 여전히 시끄럽게 재진술하고 그 자리에 멈춘다.
   - **진입 문맥은 보낸 표면이 싣는다**(계약 §5.1). 이 seam 이 인자를 흘리면 모든 진입이
     자발적 진입으로 떨어져 배너·복귀처가 통째로 사라진다.
   - **편집기를 띄운 자리 1슬롯**을 기억한다. 이탈이 초점을 그리로 되돌린다 — 편집기로
     들어오는 문이 이 파일 하나라 여기서 한 번 기억하면 모든 이탈이 따라온다.

   `land()` 가 `force` 인 이유도 그대로다: 나가는 길의 이탈 위임을 들어오는 길에서 태울 것이
   없다. */
import type { BridgeClient } from "../runtime/client.ts";
import type { EditorEntryPort } from "./ports.ts";
import { expectHostValue } from "./runtime.ts";

type Obj = Record<string, any>;

type ModalPort = {
  restoreFocus(target: unknown): void;
};

export type EditorEntryDeps = {
  doc: Document;
  client: BridgeClient;
  modal: ModalPort;
  navigate(screen: string, options?: Obj): void;
  notify(message: string): void;
};

export function createEditorEntry(deps: EditorEntryDeps): EditorEntryPort {
  /** 1슬롯 — 다음 진입이 다시 채운다(옛 자리로 두 번 되돌리지 않는다). */
  let entryFocus: Element | null = null;

  const invoke = async (
    method: Parameters<BridgeClient["invoke"]>[0], ...args: unknown[]
  ): Promise<unknown> => expectHostValue(await deps.client.invoke(method, ...args), method);

  function rememberEntryFocus(): void {
    entryFocus = deps.doc.activeElement;
  }

  function restoreEntryFocus(): void {
    const target = entryFocus;
    entryFocus = null;
    deps.modal.restoreFocus(target);
  }

  function land(): void {
    deps.navigate("editor", { force: true });
  }

  async function newDraft(): Promise<boolean> {
    rememberEntryFocus();   // 이탈이 초점을 되돌릴 자리 — 진입 전에 한 번만 잡는다
    /* `dispatch` 는 실패를 **던지지 않고** `{ok:false, failure}` 로 해소한다 — 그대로 두면
       폐기가 실패했는데도 착지해 「새 작업을 시작했다」고 보고하고, 사용자는 옛 세션을 새
       것으로 안다. 다른 두 진입이 `ERROR:` 로 하는 것과 같은 모양으로 재진술하고 멈춘다. */
    try {
      expectHostValue(
        await deps.client.dispatch("editor", "new_session", {}), "editor/new_session");
    } catch (error) {
      deps.notify(String((error as Obj)?.message || error));
      return false;
    }
    land();
    return true;
  }

  async function newDraftFromData(context?: Obj): Promise<boolean> {
    rememberEntryFocus();
    const result = await invoke("new_job_from_data", context || {});
    if (typeof result === "string" && result.startsWith("ERROR:")) {
      deps.notify(result.slice(6).trim());   // 데이터 부재·재적재 실패 → loud(조용한 무이동 금지)
      return false;
    }
    land();
    return true;
  }

  async function openGuarded(name: string, context?: Obj): Promise<boolean> {
    rememberEntryFocus();
    const result = await invoke("open_job_in_editor", name, context || {});
    if (typeof result === "string" && result.startsWith("ERROR:")) {
      deps.notify(result.slice(6).trim());   // 손상·템플릿 부재 → loud(조용한 무시 금지)
      return false;
    }
    land();
    return true;
  }

  return {
    openGuarded: (...args: unknown[]) => openGuarded(String(args[0]), args[1] as Obj | undefined),
    newDraft: () => newDraft(),
    newDraftFromData: (...args: unknown[]) => newDraftFromData(args[0] as Obj | undefined),
    land: () => land(),
    restoreEntryFocus: () => restoreEntryFocus(),
  };
}
