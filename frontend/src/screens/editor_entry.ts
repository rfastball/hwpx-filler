/* R4-02 편집기 진입 seam 의 React 구현(legacy `frontend/js/editor_entry.js`).

   공개 표면 6키는 그대로다 — `EditorEntryPort` 가 그 계약이고, 호출자(라이브러리·작업 화면)는
   구현이 바뀌어도 고치지 않는다. 지키는 것:

   - **미저장 정의 세션은 조용히 버리지 않는다**: 판정은 브리지 즉시 질의(stale 스냅샷 금지),
     문구만 호출측이 준다. 미저장이 없으면 조용히 통과한다.
   - **진입 문맥은 보낸 표면이 싣는다**(계약 §5.1). 이 seam 이 인자를 흘리면 모든 진입이
     자발적 진입으로 떨어져 배너·복귀처가 통째로 사라진다.
   - **편집기를 띄운 자리 1슬롯**을 기억한다. 이탈이 초점을 그리로 되돌린다 — 편집기로
     들어오는 문이 이 파일 하나라 여기서 한 번 기억하면 모든 이탈이 따라온다.

   `land()` 가 `force` 인 이유도 그대로다: 진입은 **이미 확인을 마친 뒤**라 이탈 가드를 다시
   태울 것이 없다(그 가드는 나가는 길의 것이다). */
import type { BridgeClient } from "../runtime/client.ts";
import type { EditorEntryPort } from "./ports.ts";
import { expectHostValue } from "./runtime.ts";

type Obj = Record<string, any>;

type ModalPort = {
  confirm(spec: Obj): Promise<boolean>;
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

  /** 미저장 정의 세션 폐기 확인의 **단일 출처** — 판정은 브리지, 문구는 호출측. */
  async function confirmDiscard(body: string, returnFocus?: unknown): Promise<boolean> {
    if (!(await invoke("editor_has_unsaved_work"))) return true;
    return deps.modal.confirm({
      body, returnFocus, confirmLabel: "버리고 계속", cancelLabel: "취소",
    });
  }

  async function newDraft(): Promise<boolean> {
    rememberEntryFocus();   // 확인 모달 앞에서 — 모달은 자기 되돌림으로 이 자리를 복원한다
    if (!(await confirmDiscard(
      "새 작업을 시작하면 저장하지 않은 편집 세션이 사라집니다.\n" +
      "사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?"))) return false;
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
    if (!(await confirmDiscard(
      "이 데이터로 새 작업을 시작하면 저장하지 않은 편집 세션이 사라집니다.\n" +
      "사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?"))) return false;
    const result = await invoke("new_job_from_data", context || {});
    if (typeof result === "string" && result.startsWith("ERROR:")) {
      deps.notify(result.slice(6).trim());   // 데이터 부재·재적재 실패 → loud(조용한 무이동 금지)
      return false;
    }
    land();
    return true;
  }

  /* 손실 집합은 **진입마다 다르다**(#878). 데이터를 든 화면에서 온 수리 진입은 편집기의
     데이터 칸을 비우지 않고 그 화면이 든 것으로 갈아 끼우므로, 데이터를 손실 목록에 두면
     문안이 실동작보다 넓게 파기를 말한다. 여기서 보는 것은 이 seam 이 **자기가 실어 보낼**
     진입 사유뿐이고(라우팅 사실), 그 사유로 실제 무엇이 인계되는지의 판정은 Python 이
     그 자리에서 「문서 만들기」에 되묻는다(`WebFrontend._mounted_data_handoff`). */
  function openLossCopy(name: string, context?: Obj): string {
    const lead = `'${name}' 편집을 열면 저장하지 않은 편집 세션이 사라집니다.\n`;
    if (String(context?.entry_reason || "") === "document_browser_repair") {
      return lead + "사라지는 것: 이름 · 매핑\n"
        + "데이터는 문서 만들기 화면에서 고른 것으로 바뀝니다.\n\n계속할까요?";
    }
    return lead + "사라지는 것: 이름 · 데이터 · 매핑\n\n계속할까요?";
  }

  async function openGuarded(name: string, context?: Obj): Promise<boolean> {
    rememberEntryFocus();
    if (!(await confirmDiscard(openLossCopy(name, context)))) {
      return false;
    }
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
    confirmDiscard: (...args: unknown[]) => confirmDiscard(String(args[0]), args[1]),
    restoreEntryFocus: () => restoreEntryFocus(),
  };
}
