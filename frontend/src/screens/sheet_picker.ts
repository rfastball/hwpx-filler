/* R4-02 시트 선택 확정 게이트의 React 후계(legacy `frontend/js/sheet_picker.js`).

   계약은 한 줄로 안 바뀐다(#33 · confirm-or-alarm): **조용한 첫 시트 로드 금지**.
   `pick_data_file` 이 `{needs_sheet, …}` 를 돌려주면 사용자가 시트를 명시로 고른 뒤에만
   `load_data_sheet` 가 나간다. 취소·Escape·배경 닫기는 겨눔 전체를 중단한다(첫 시트로
   강등하지 않는다) — 로드가 **아예 일어나지 않는 것**이 취소의 의미다.

   반환도 그대로다: 마운트 descriptor · `ERROR:…` · `null`(취소). 호출자(`data_picker`·편집기)는
   `SheetPickerPort` 하나만 알고, 이 구현은 #414 가 legacy 로 bind 해 둔 그 포트를 정확히
   한 번 handoff 받는다(패킷 rev4).

   settle-once 는 여기 산다: 확정 즉시 추가 클릭이 두 번째 로드를 태우지 않고, 닫힘 통지가
   다시 와도 이미 정산된 약속은 다시 해소되지 않는다. */
import { createElement, useEffect, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import type { BridgeClient } from "../runtime/client.ts";
import type {
  DataMountDescriptor, NeedsSheetPayload, SheetPickerPort,
} from "../ports/service_handoff.ts";
import { expectHostValue } from "./runtime.ts";

type Obj = Record<string, any>;
type Listener = () => void;

type ModalPort = { open(id: string, spec?: Obj): void; close(id: string): void };

export type SheetPickerDeps = {
  doc: Document;
  client: BridgeClient;
  modal: ModalPort;
};

type Session = {
  id: number;
  screen: string;
  name: string;
  path: string;
  sheets: Obj[];
  /** 확정·취소 어느 쪽이든 **정확히 한 번** 해소한다. */
  settle(value: DataMountDescriptor | `ERROR:${string}` | null): void;
  /** 로드가 나간 뒤의 추가 클릭을 막는다(이중 로드 금지). */
  picking: boolean;
};

export function createSheetPickerController(deps: SheetPickerDeps) {
  let session: Session | null = null;
  let sequence = 0;
  const listeners = new Set<Listener>();

  function emit(): void {
    for (const listener of [...listeners]) listener();
  }

  function choose(
    screen: string, payload: NeedsSheetPayload,
  ): Promise<DataMountDescriptor | `ERROR:${string}` | null> {
    if (session !== null) {
      return Promise.reject(new Error("시트 선택 창이 이미 열려 있습니다."));
    }
    return new Promise((resolve) => {
      sequence += 1;
      let settled = false;
      const body = payload as Obj;
      session = {
        id: sequence,
        screen,
        name: String(body.name || ""),
        path: String(body.path || ""),
        sheets: (body.sheets || []) as Obj[],
        picking: false,
        settle(value) {
          if (settled) return;
          settled = true;
          session = null;
          emit();
          deps.modal.close("sheetModal");
          resolve(value);
        },
      };
      emit();
      /* 닫힘은 경로를 가리지 않고 취소로 귀결된다 — 취소 버튼·Escape·배경 모두 같은 통지다. */
      deps.modal.open("sheetModal", { onClose: () => { session?.settle(null); } });
    });
  }

  async function pick(sheet: string): Promise<void> {
    const current = session;
    if (current === null || current.picking) return;
    current.picking = true;
    emit();
    try {
      const result = expectHostValue(
        await deps.client.invoke("load_data_sheet", current.screen, current.path, sheet),
        "load_data_sheet",
      );
      current.settle(result as DataMountDescriptor | `ERROR:${string}`);
    } catch (error) {
      current.settle(`ERROR:${String((error as Obj)?.message || error)}`);
    }
  }

  return {
    /** 포트 구현 — 이 객체가 그대로 `SheetPickerPort` 다(상태는 controller 가 든다). */
    port: { choose } satisfies SheetPickerPort,
    model: {
      getSnapshot: (): Session | null => session,
      subscribe(listener: Listener): () => void {
        listeners.add(listener);
        return () => { listeners.delete(listener); };
      },
    },
    pick,
    cancel(): void { deps.modal.close("sheetModal"); },
    doc: deps.doc,
  };
}

export type SheetPickerController = ReturnType<typeof createSheetPickerController>;

function h(tag: string, props: Obj | null, ...children: ReactNode[]): ReactNode {
  return createElement(tag, props, ...children);
}

export function SheetPickerDialog(props: { controller: SheetPickerController }): ReactNode {
  const { controller } = props;
  const session = useSyncExternalStore(controller.model.subscribe, controller.model.getSnapshot);
  /* 초기 포커스 = 첫 옵션(`data-first`). 모달 executor 의 기본 포커스는 열림 **시점**의 DOM 을
     보는데 옵션은 이 커밋에서 생기므로, 커밋 뒤 이 자리가 겨눈다 — 선택은 여전히 명시
     클릭이다(포커스는 강등이 아니다). */
  useEffect(() => {
    if (session === null) return;
    const first = controller.doc.querySelector<HTMLElement>('#sheetList [data-first="1"]');
    first?.focus();
  }, [session?.id]);
  const sheets = session?.sheets || [];
  return h("div", { className: "modal-card" },
    h("h3", { id: "sheetTitle" }, "시트 선택"),
    h("p", { className: "modal-sub" },
      h("span", { className: "mono", id: "sheetModalFile" }, session?.name || ""),
      " 에 시트가 여러 개입니다. 채울 시트를 선택하세요."),
    h("div", { id: "sheetList", className: "sheet-list" },
      ...sheets.map((sheet: Obj, index: number) => h("button", {
        type: "button", className: "btn sheet-opt", key: String(sheet.name),
        "data-sheet": String(sheet.name),
        /* 리터럴로 쓴다 — 조건부 전개는 소유권 추출기가 못 보는 자리라 이 축이 분모에서
           조용히 빠진다. `undefined` 는 React 가 속성을 생략한다(산출 동일). */
        "data-first": index === 0 ? "1" : undefined,
        disabled: !!session?.picking,
        onClick: () => { void controller.pick(String(sheet.name)); },
      },
      h("span", { className: "mono sheet-name" }, String(sheet.name)),
      h("span", { className: "muted sheet-dim" }, `${sheet.rows}행 × ${sheet.cols}열`)))),
    h("div", { className: "modal-actions" },
      h("button", { className: "btn", id: "sheetCancel", onClick: controller.cancel }, "취소")));
}
