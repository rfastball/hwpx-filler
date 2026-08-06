/* R4 교차 화면 port — 상태가 아니라 현재 구현 포인터만 보관한다.

   legacy→React 교체는 owner identity를 명시한 handoff 정확 1회로만 가능하다. 미바인드 호출,
   현재 owner 불일치, 둘째 handoff는 모두 loud failure다. */

type Owner = "legacy" | "react";

export function createHandoffPort<T extends object>(label: string) {
  let owner: Owner | null = null;
  let implementation: T | null = null;
  let handedOff = false;

  return {
    bindLegacy(value: T): void {
      if (owner !== null || implementation !== null) {
        throw new Error(`${label}: legacy 구현은 정확히 한 번만 결속할 수 있습니다.`);
      }
      owner = "legacy";
      implementation = value;
    },
    bindReact(value: T): void {
      if (owner !== null || implementation !== null) {
        throw new Error(`${label}: React 구현은 빈 port에만 결속할 수 있습니다.`);
      }
      owner = "react";
      implementation = value;
    },
    handoff(from: Owner, to: Owner, value: T): void {
      if (handedOff || owner !== from || implementation === null || from === to) {
        throw new Error(`${label}: ${from}→${to} handoff 상태가 어긋났습니다.`);
      }
      handedOff = true;
      owner = to;
      implementation = value;
    },
    current(): T {
      if (implementation === null || owner === null) {
        throw new Error(`${label}: 구현이 결속되지 않았습니다.`);
      }
      return implementation;
    },
    owner(): Owner | null {
      return owner;
    },
  };
}

export type JobReadPort = {
  refreshList(): void | Promise<void>;
  openBrowseNeedsAction(name: string): Promise<void>;
};

export type PreviewRequest = { at?: number; focusTarget?: string };

export type JobRunCallbacks = {
  onFull(snapshot: unknown): void;
  onProgress(progress: unknown): void;
};

export type JobRunPort = {
  attach(callbacks: JobRunCallbacks): () => void;
  acceptFull(snapshot: unknown): void;
  acceptProgress(progress: unknown): void;
  openPreview(request?: PreviewRequest): Promise<void>;
  dispose(): void;
};

export type JobDataCoordinator = { flushPendingEdits(): Promise<void> };

export type JobRunCoordinationPort = {
  confirmDestructiveIfArmed(title: string, verb: string, confirmLabel: string): Promise<boolean>;
  log(message: string): void;
};

export type JobRelinkFlowPort = { relinkTemplateFor(name: string): Promise<void> };

export type EditorEntryPort = {
  openGuarded(...args: unknown[]): unknown;
  newDraft(...args: unknown[]): unknown;
  newDraftFromData(...args: unknown[]): unknown;
  land(...args: unknown[]): unknown;
  confirmDiscard(...args: unknown[]): unknown;
  restoreEntryFocus(...args: unknown[]): unknown;
};

export function createScreenPorts() {
  return {
    jobRead: createHandoffPort<JobReadPort>("JobReadPort"),
    jobRun: createHandoffPort<JobRunPort>("JobRunPort"),
    jobData: createHandoffPort<JobDataCoordinator>("JobDataCoordinator"),
    jobRunCoordination: createHandoffPort<JobRunCoordinationPort>("JobRunCoordinationPort"),
    jobRelinkFlow: createHandoffPort<JobRelinkFlowPort>("JobRelinkFlowPort"),
    editorEntry: createHandoffPort<EditorEntryPort>("EditorEntryPort"),
  };
}

export type ScreenPorts = ReturnType<typeof createScreenPorts>;
