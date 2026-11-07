/* R4-01 job 읽기 표면의 「문서 작업 찾기」 탐색 흐름 — job_read.ts의 module_statements
   상한 분리. `browse(...)` 디스패처 자체(브리지 호출 세대·꼬리 체인)는 job_read.ts가
   그대로 쥐고, 여기는 그 디스패처가 내주는 세대 접근자(`session`)로만 말을 건다. 순수
   이동, 로직 불변 — 세대 증가 지점·꼬리 대기 지점은 원래와 같다. */
import type { ModalPort, Obj, UiState } from "./job_read.ts";

/** `browse(...)` 디스패처가 쥔 세대·꼬리를 밖에서 쓰는 접근자 — 디스패처 자체는 옮기지
 *  않는다(브리지 호출은 job_read.ts 소유로 둔다). */
export type BrowseSession = {
  bumpGeneration(): void;
  generation(): number;
  afterTail<T>(fn: () => T | Promise<T>): Promise<T>;
};

export type JobReadBrowseDeps = {
  modal: ModalPort;
  doc: Document;
  browse: (action: string, payload: Obj) => Promise<Obj>;
  session: BrowseSession;
  getUi: () => UiState;
  selectJob: (name: string) => Promise<boolean>;
  newWorkFromData: (extraEvidence?: Obj) => unknown;
};

export function createJobReadBrowse(ctx: JobReadBrowseDeps) {
  const { modal, doc, browse, session, getUi, selectJob, newWorkFromData } = ctx;
  let browseAfterClose: (() => void) | null = null;

  async function openBrowse(returnFocus: HTMLElement | null = null): Promise<void> {
    if (getUi().switchingData) return;
    session.bumpGeneration();
    browseAfterClose = null;
    modal.open("jobBrowseSheet", {
      initialFocus: doc.getElementById("jobBrowseQuery"),
      returnFocus,
      onClose: () => {
        session.bumpGeneration();
        const next = browseAfterClose;
        browseAfterClose = null;
        if (next !== null) next();
      },
    });
  }

  function newWorkAfterBrowseClose(extraEvidence: Obj): void {
    if (browseAfterClose !== null) {
      throw new Error("JobReadPort: 탐색 닫힘 뒤 흐름이 이미 예약돼 있습니다.");
    }
    browseAfterClose = () => { void newWorkFromData(extraEvidence); };
    modal.close("jobBrowseSheet");
  }

  async function openBrowseNeedsAction(name: string): Promise<void> {
    if (name.trim() === "") throw new Error("JobReadPort: 확인할 작업 이름이 비었습니다.");
    await browse("browse_tab", { tab: "needs_action" });
    await browse("browse_query", { text: name });
    await openBrowse();
  }

  function setBrowseQuery(text: string): void {
    const generation = session.generation();
    doc.defaultView?.setTimeout(() => {
      if (generation === session.generation()) void browse("browse_query", { text });
    }, 180);
  }

  async function pickBrowse(name: string): Promise<void> {
    if (await session.afterTail(() => selectJob(name))) {
      browseAfterClose = () => {
        doc.getElementById(`jobCand-${encodeURIComponent(name)}`)?.focus();
      };
      modal.close("jobBrowseSheet");
    }
  }

  return {
    openBrowse,
    newWorkAfterBrowseClose,
    openBrowseNeedsAction,
    setBrowseQuery,
    pickBrowse,
  };
}

export type JobReadBrowse = ReturnType<typeof createJobReadBrowse>;
