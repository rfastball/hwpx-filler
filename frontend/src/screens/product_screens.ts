/* R4-04 제품 화면 합성 — static stage 하나에 네 화면 wrapper를 한 portal로 그린다.

   네 화면은 같은 React tree에서 계속 mounted다. visibility store 하나가 `.on`·hidden·inert·
   aria-hidden을 함께 내려 숨은 subtree의 tab stop과 별도 DOM 판정을 없앤다. */
import { Fragment, createElement, useMemo, useSyncExternalStore } from "react";
import type { ComponentType, ReactNode } from "react";
import { createPortal } from "react-dom";

import { DataPickerDialog, PoolRegistrationDialog } from "./data_picker.ts";
import type { DataPickerController } from "./data_picker.ts";
import { EditorScreen, TxtEditDialog } from "./editor.ts";
import type { EditorController } from "./editor.ts";
import {
  JobBrowseDialog, JobCandidates, JobDataBody, JobDataHeader, JobNoDataExit,
  JobReadEffects,
} from "./job_read.ts";
import type { JobReadController } from "./job_read.ts";
import { JobContentSelection } from "./job_content_selection.ts";
import type { JobContentSelectionController } from "./job_content_selection.ts";
import { JobArtifactSheet } from "./job_artifact.ts";
import { JobResultZone } from "./job_result.ts";
import {
  JobActionBar, JobMirrorZone, JobOutRow, JobPreflight, JobRestate, JobRunCap,
  JobTemplateChange, JobWorkbenchStatus,
  JobStatusPill,
} from "./job_run.ts";
import type { JobRunController } from "./job_run.ts";
import { LibraryScreen } from "./library.ts";
import type { LibraryController } from "./library.ts";
import { SettingsSheet } from "./settings_sheet.ts";
import { SheetPickerDialog } from "./sheet_picker.ts";
import type { SheetPickerController } from "./sheet_picker.ts";
import { WorkbenchScreen } from "./workbench.ts";
import type { WorkbenchController } from "./workbench.ts";

type Obj = Record<string, unknown>;
const h = (tag: string | ((props: any) => ReactNode), props: Obj | null, ...children: ReactNode[]) =>
  createElement(tag as any, props, ...children);

export const PRODUCT_SCREEN_IDS = Object.freeze([
  "library", "job", "editor", "workbench",
] as const);
export type ProductScreenId = typeof PRODUCT_SCREEN_IDS[number];

export function createProductScreenVisibility(initial: ProductScreenId = "job") {
  let current = initial;
  const listeners = new Set<() => void>();
  const allowed = new Set<string>(PRODUCT_SCREEN_IDS);
  return {
    activate(id: string): void {
      if (!allowed.has(id)) throw new Error(`알 수 없는 제품 화면입니다: ${id}`);
      if (id === current) return;
      current = id as ProductScreenId;
      for (const listener of [...listeners]) listener();
    },
    getSnapshot: (): ProductScreenId => current,
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
}

export type ProductScreenVisibility = ReturnType<typeof createProductScreenVisibility>;
export type ProductOverlayPortal = { targetId: string; content: ReactNode };

export function productOverlay(targetId: string, content: ReactNode): ProductOverlayPortal {
  return { targetId, content };
}

export function productOverlayComponent<P extends object>(
  targetId: string,
  component: ComponentType<P>,
  props: P,
): ProductOverlayPortal {
  return productOverlay(targetId, createElement(component, props));
}

export type ProductScreensPorts = {
  doc: Document;
  visibility: ProductScreenVisibility;
  library: LibraryController;
  editor: EditorController;
  workbench: WorkbenchController;
  jobRead: JobReadController;
  jobRun: JobRunController;
  slotContent: JobContentSelectionController;
  dataPicker: DataPickerController;
  sheetPicker: SheetPickerController;
  dataSheetClose: HTMLElement;
  overlays: readonly ProductOverlayPortal[];
};

function requireEmptyTarget(doc: Document, id: string, seen: Set<string>): Element {
  if (seen.has(id)) throw new Error(`React portal target이 중복됐습니다: #${id}`);
  seen.add(id);
  const target = doc.getElementById(id);
  if (target === null) throw new Error(`React portal target이 없습니다: #${id}`);
  if (target.childNodes.length !== 0) {
    throw new Error(`React portal target에 static child가 남았습니다: #${id}`);
  }
  return target;
}

function screenProps(id: ProductScreenId, active: ProductScreenId): Obj {
  const on = id === active;
  return {
    id: `scr-${id}`,
    className: `scr${on ? " on" : ""}`,
    hidden: !on,
    inert: !on,
    "aria-hidden": on ? "false" : "true",
    tabIndex: -1,
  };
}

function JobScreen(
  props: Pick<ProductScreensPorts, "jobRead" | "jobRun" | "slotContent" | "dataSheetClose"> & {
    active: ProductScreenId;
  },
): ReactNode {
  const { jobRead, jobRun } = props;
  return h("section", screenProps("job", props.active),
    h(JobReadEffects as any, { controller: jobRead, closeButton: props.dataSheetClose }),
    h("header", { className: "scr-head" },
      h("div", null,
        h("h1", null, "문서 만들기"),
        h("p", { className: "sub" }, "데이터를 고르고, 그 데이터로 쓸 문서 작업을 실행합니다.")),
      h("div", { className: "scr-head-actions" }, h(JobStatusPill as any, { controller: jobRun }))),
    h("div", { className: "job-layout" },
      h("div", { className: "job-panel", id: "jobPanel" },
        h("div", { className: "job-zones", id: "jobZones" },
          h("div", { className: "data-grid", id: "jobDataGrid" },
            h("section", { className: "dg-main" },
              h("div", { className: "zone job-data-zone" },
                h(JobDataHeader as any, { controller: jobRead }),
                h("div", { id: "jobPreflight" }, h(JobPreflight as any, { controller: jobRun })),
                h(JobDataBody as any, { controller: jobRead, location: "inline" })),
              h("div", { className: "zone job-mirror-zone", id: "jobMirrorZone" },
                h(JobMirrorZone as any, { controller: jobRun })),
              h("div", { className: "zone job-result-zone", id: "jobResultZone", tabIndex: -1 },
                h(JobResultZone as any, { controller: jobRun }))),
            h("aside", { className: "dg-side", id: "jobSideCard", "aria-label": "이 데이터에 사용할 문서" },
              h("div", { className: "zone", id: "jobNoDataExit" },
                h(JobNoDataExit as any, { controller: jobRead })),
              h("div", { className: "zone job-cands-row", id: "jobCandsRow" },
                h(JobCandidates as any, { controller: jobRead })),
              h("div", { className: "zone", id: "jobTplChangeZone" },
                h(JobTemplateChange as any, { controller: jobRun })),
              h("div", { className: "zone", id: "jobContentSelectionZone" },
                h(JobContentSelection as any, { controller: props.slotContent })),
              h("div", { className: "zone", id: "jobWorkbenchStatusZone" },
                h(JobWorkbenchStatus as any, { controller: jobRun })),
              h("div", { className: "zone" },
                h("div", { className: "zone-cap", id: "jobRunCap" },
                  h(JobRunCap as any, { controller: jobRun })),
                h("div", { className: "run-row", id: "jobOutRow" },
                  h(JobOutRow as any, { controller: jobRun })),
                h("div", { className: "defblk", id: "jobRestate" },
                  h(JobRestate as any, { controller: jobRun })))))),
        h("div", { className: "session-actionbar", id: "jobActionBar" },
          h(JobActionBar as any, { controller: jobRun })))));
}

export function ProductScreens(ports: ProductScreensPorts): ReactNode {
  const active = useSyncExternalStore(
    ports.visibility.subscribe,
    ports.visibility.getSnapshot,
    ports.visibility.getSnapshot,
  );
  const targets = useMemo(() => {
    const seen = new Set<string>();
    const stage = requireEmptyTarget(ports.doc, "reactScreenStage", seen);
    const overlays = ports.overlays.map((entry) => ({
      ...entry, target: requireEmptyTarget(ports.doc, entry.targetId, seen),
    }));
    return { stage, overlays };
  }, [ports.doc, ports.overlays]);

  const screens = createElement(Fragment, null,
    h("section", screenProps("library", active),
      h(LibraryScreen as any, { controller: ports.library })),
    h(JobScreen as any, {
      active, jobRead: ports.jobRead, jobRun: ports.jobRun,
      slotContent: ports.slotContent,
      dataSheetClose: ports.dataSheetClose,
    }),
    h("section", screenProps("editor", active),
      h(EditorScreen as any, { controller: ports.editor })),
    h("section", screenProps("workbench", active),
      h(WorkbenchScreen as any, { controller: ports.workbench })),
  );
  return createElement(Fragment, null,
    createPortal(screens, targets.stage, "product-screens"),
    ...targets.overlays.map((entry) =>
      createPortal(entry.content, entry.target, `overlay-${entry.targetId}`)),
  );
}

/* overlay component imports are kept here so bootstrap only describes controller wiring and portal targets. */
export const PRODUCT_OVERLAY_COMPONENTS = Object.freeze({
  PoolRegistrationDialog,
  DataPickerDialog,
  JobDataBody,
  JobBrowseDialog,
  TxtEditDialog,
  SheetPickerDialog,
  JobArtifactSheet,
  /* 셸 설정 모달 — 화면 컨트롤러가 아니라 셸 서비스(Theme·Personalization·Modal)를 받는
     유일한 overlay 다. 화면 스냅샷을 안 쓰므로 화면 넷 어디에서 열어도 같은 면이다. */
  SettingsSheet,
});
