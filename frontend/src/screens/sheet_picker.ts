/* 명시적으로 고른 시트를 등록 하나에 선언하고 활성 데이터의 descriptor를 반환한다.
   등록 전 취소는 로드 0건이다. 처리 중 닫기를 막고 실패는 창 안에서 재진술한다.
   호출자는 SheetPickerPort 하나만 사용하며 확정·닫힘은 정확히 한 번 정산한다. */
import { createElement, useEffect, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import type { BridgeClient } from "../runtime/client.ts";
import type {
  DataMountDescriptor, NeedsSheetPayload, SheetPickerPort,
} from "../ports/service_handoff.ts";
import { expectHostValue } from "./runtime.ts";

type Obj = Record<string, any>;
type Listener = () => void;

type ModalPort = { open(id: string, spec?: Obj): void; close(id: string): void; confirm(spec: Obj): Promise<boolean> };

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
  selected: string[];
  result: Obj | null;
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
        selected: [],
        result: null,
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
      /* 취소·Escape·배경 닫기는 같은 가드와 결과를 사용한다. */
      deps.modal.open("sheetModal", {
        beforeClose: () => !session?.picking,
        onClose: () => { session?.settle(session.result?.mount || null); },
      });
    });
  }

  async function pick(): Promise<void> {
    const current = session;
    if (current === null || current.picking) return;
    const selected = current.selected;
    if (!selected.length) return;
    session = { ...current, picking: true };
    emit();
    try {
      let result = expectHostValue(
        await deps.client.invoke("load_data_sheet", current.screen, current.path, selected),
        "load_data_sheet",
      );
      if (result && typeof result === "object" && (result as Obj).needs_confirm) {
        const confirmation = result as Obj;
        if (!(await deps.modal.confirm({ body: confirmation.confirm_text,
          confirmLabel: "등록", cancelLabel: "취소", danger: true }))) {
          session = { ...current, picking: false };
          emit();
          return;
        }
        result = expectHostValue(await deps.client.invoke("load_data_sheet",
          current.screen, current.path, selected, { basis: confirmation.basis }), "load_data_sheet");
      }
      if (result && typeof result === "object" && Array.isArray((result as Obj).sheets)) {
        const batch = result as Obj;
        const failed = batch.sheets.filter((row: Obj) => row.error);
        if (!failed.length && batch.mount && !batch.error) {
          current.settle(batch.mount);
        } else {
          session = { ...current, picking: false, result: batch };
          emit();
        }
      } else {
        current.settle(result as DataMountDescriptor | `ERROR:${string}`);
      }
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
    toggle(name: string): void {
      if (!session || session.picking) return;
      const selected = session.selected.includes(name)
        ? session.selected.filter((value) => value !== name) : [...session.selected, name];
      session = { ...session, selected };
      emit();
    },
    selectAll(): void {
      if (!session || session.picking) return;
      session = { ...session, selected: session.selected.length === session.sheets.length
        ? [] : session.sheets.map((row) => String(row.name)) };
      emit();
    },
    cancel(): void { if (!session?.picking) deps.modal.close("sheetModal"); },
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
    h("h3", { id: "sheetTitle" }, "가져올 시트 선택"),
    h("p", { className: "modal-sub" },
      h("span", { className: "mono", id: "sheetModalFile" }, session?.name || ""),
      ),
    h("label", { className: "sheet-opt" },
      h("input", { type: "checkbox", checked: !!sheets.length && session?.selected.length === sheets.length,
        ref: (el: HTMLInputElement | null) => { if (el) el.indeterminate = !!session?.selected.length && session.selected.length < sheets.length; },
        disabled: !!session?.picking, onChange: controller.selectAll }), "전체 선택"),
    h("div", { id: "sheetList", className: "sheet-list" },
      ...sheets.map((sheet: Obj, index: number) => h("label", {
        className: "sheet-opt", key: String(sheet.name),
      }, h("input", {
        type: "checkbox", checked: session?.selected.includes(String(sheet.name)) || false,
        "data-sheet": String(sheet.name),
        /* 리터럴로 쓴다 — 조건부 전개는 소유권 추출기가 못 보는 자리라 이 축이 분모에서
           조용히 빠진다. `undefined` 는 React 가 속성을 생략한다(산출 동일). */
        "data-first": index === 0 ? "1" : undefined,
        disabled: !!session?.picking,
        onChange: () => controller.toggle(String(sheet.name)),
      }),
      h("span", { className: "mono sheet-name" }, String(sheet.name)),
      h("span", { className: "muted sheet-dim" }, `약 ${sheet.rows}행 × ${sheet.cols}열`)))),
    session?.result ? h("div", { role: "status", className: "note" },
      ...session.result.sheets.map((row: Obj) => h("div", { key: row.name },
        row.error || row.key ? `${row.name}: ${row.error || "등록됨"}` : null)),
      session.result.error ? h("div", { className: "danger" }, session.result.error) : null) : null,
    h("div", { className: "modal-actions" },
      h("button", { className: "btn", id: "sheetCancel", disabled: !!session?.picking,
        onClick: controller.cancel }, session?.result ? "닫기" : "취소"),
      h("button", { className: "btn primary", id: "sheetImport", disabled: !!session?.picking || !session?.selected.length,
        onClick: () => { void controller.pick(); } }, session?.picking ? "가져오는 중…" : `선택한 ${session?.selected.length || 0}개 시트 가져오기`)));
}
