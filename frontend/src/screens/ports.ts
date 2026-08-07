/* React 교차 화면 port — 상태가 아니라 현재 구현 포인터만 보관한다.

   R4 이관이 끝났으므로 legacy owner와 handoff 상태는 없다. 미결속 호출과 둘째 결속은
   계속 loud failure다. */

export function createPort<T extends object>(label: string) {
  let implementation: T | null = null;

  return {
    bind(value: T): void {
      if (implementation !== null) {
        throw new Error(`${label}: 구현은 정확히 한 번만 결속할 수 있습니다.`);
      }
      implementation = value;
    },
    current(): T {
      if (implementation === null) {
        throw new Error(`${label}: 구현이 결속되지 않았습니다.`);
      }
      return implementation;
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
    jobRead: createPort<JobReadPort>("JobReadPort"),
    jobRun: createPort<JobRunPort>("JobRunPort"),
    jobData: createPort<JobDataCoordinator>("JobDataCoordinator"),
    jobRunCoordination: createPort<JobRunCoordinationPort>("JobRunCoordinationPort"),
    jobRelinkFlow: createPort<JobRelinkFlowPort>("JobRelinkFlowPort"),
    editorEntry: createPort<EditorEntryPort>("EditorEntryPort"),
  };
}

export type ScreenPorts = ReturnType<typeof createScreenPorts>;
