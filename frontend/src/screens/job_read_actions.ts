/* R4-01 job 읽기 표면의 컨트롤러 헬퍼 — job_read.ts의 module_statements 상한 분리.
   `zone(...)` 존 변이 호출은 job_read.ts가 단독 소유하므로(bridge_contract 계약), 여기
   옮긴 함수는 전부 그 호출을 쓰지 않는 쪽(선택·즐겨찾기·새 작업·재연결·데이터 연결)만이다.
   `switching` 가드는 selectJob과 함께 여기로 옮겨 `isSwitchingJob()` 접근자로 내보낸다
   (job_read.ts의 switchData가 그 값만 읽는다). 순수 이동, 로직 불변. */
import type { PickerSessionRead } from "./data_picker.ts";
import type { JobReadControllerDeps, Obj, UiState } from "./job_read.ts";

export type JobReadActionsDeps = {
  deps: JobReadControllerDeps;
  call: (screen: string, action: string, payload?: Obj) => Promise<Obj>;
  snapshot: () => Obj | null;
  patchUi: (patch: Partial<UiState>) => void;
  getUi: () => UiState;
  flushPendingEdits: () => Promise<void>;
};

export function createJobReadActions(ctx: JobReadActionsDeps) {
  const { deps, call, snapshot, patchUi, getUi, flushPendingEdits } = ctx;
  let switching = false;
  const favoriteTail = new Map<string, Promise<void>>();
  const favoriteIntent = new Map<string, boolean>();
  const favoriteRevision = new Map<string, number>();

  function isSwitchingJob(): boolean {
    return switching;
  }

  async function selectJob(name: string): Promise<boolean> {
    if (name.trim() === "") throw new Error("JobReadPort: 빈 작업 이름은 열 수 없습니다.");
    if (switching || getUi().switchingData) return false;
    switching = true;
    patchUi({ openingName: name });
    try {
      await flushPendingEdits();
      await call("job", "select_job", { name });
      return true;
    } finally {
      switching = false;
      if (getUi().openingName === name) patchUi({ openingName: "" });
    }
  }

  /** 데이터 선택 면이 「지금 쓰는 데이터」로 읽는 **Python 값 셋**(고르기 열 공용 ③b).
   *
   *  종전에는 이 함수가 라벨·부제·경로·시트·종류를 조립해 카드 값을 지었다 — 그 카드가
   *  목록 첫 행으로 접히면서(스냅샷 `data_row`) 조립이 통째로 Python 으로 갔다. 여기 남은
   *  일은 **옮기기**뿐이다.
   *
   *  값이 아니라 **함수로** 건넨다: 면 안에서 파일을 새로 열면 마운트가 바뀌고 스냅샷이
   *  다시 오는데, 여는 순간의 값을 얼려 두면 그 행이 이제는 쓰지 않는 데이터를 「사용
   *  중」이라 말한다. */
  const currentData: PickerSessionRead = () => {
    const current = snapshot();
    return {
      data_row: current?.data_row || null,
      data_pool_key: current?.data_pool_key || "",
      /* 「이 데이터 고정…」 프리필의 시트 자리 — 그 값이 무엇을 뜻하는지(엑셀=시트 /
         계약 목록=뷰)는 마운트가 이미 안다(#937). 표면이 경로 모양으로 되추측하지 않는다. */
      sheet: (current?.data_target || {}).sheet || "",
    };
  };

  async function confirmDataSwap(): Promise<boolean> {
    return deps.ports.jobRunCoordination.current().confirmDestructiveIfArmed(
      "데이터 변경 확인", "데이터를 바꾸면", "데이터 바꾸고 버리기",
    );
  }

  /* 현재 데이터를 **다시 읽는다**(U4 항목 5 · #932 U4-C). 판정·수치·문안은 전부 Python
     이 내고 여기서는 확인 UI 만 짓는다 — 선택이 있으면 백엔드가 needs_confirm 과 함께
     사라지는 집합을 수치로 재진술하고, 없으면 곧바로 돈다(없는 위험에 확인을 물리면
     그 확인이 다음 진짜 확인의 무게를 깎는다). 겨눔 성분은 보내지 않는다: 재료는 세션이
     마운트 시점에 포획한 한 벌이라 웹이 실어 보내면 그사이 갈린 화면과 다른 데이터를
     새로고침한다. */
  /* 결속 없는 작업을 고치러 간다 — 쓰는 자리가 편집기 저장 하나이므로 복구도 거기다
     (#932 U4-C). 이탈 가드·미저장 확인은 편집기 진입 seam 이 이미 진다. */
  async function connectJobData(): Promise<void> {
    const name = snapshot()?.job_name;
    if (!name) return;
    await deps.ports.editorEntry.current().openGuarded(String(name), {
      entry_reason: "library",
      evidence: {},
      return_context: { surface: "data" },
    });
  }

  async function toggleFavorite(name: string, shown: boolean): Promise<void> {
    const intended = !(favoriteIntent.get(name) ?? shown);
    favoriteIntent.set(name, intended);
    const revision = (favoriteRevision.get(name) ?? 0) + 1;
    favoriteRevision.set(name, revision);
    const previous = favoriteTail.get(name) ?? Promise.resolve();
    const next = previous.then(async () => {
      const result = await call("job", "toggle_favorite", { name, value: intended });
      if (result.ok === false) deps.notify(result.error || "즐겨찾기를 바꾸지 못했습니다.");
      if (favoriteRevision.get(name) === revision) {
        favoriteIntent.delete(name);
        favoriteRevision.delete(name);
      }
    });
    favoriteTail.set(name, next.catch((error) => deps.notify(String(error))));
    await next;
  }

  function newWorkFromData(extraEvidence: Obj = {}): unknown {
    if (getUi().switchingData) return false;
    const current = snapshot();
    const gate = current?.new_work || { can: true, reason: "" };
    if (gate.can === false) {
      deps.notify(gate.reason || "이 데이터로 새 작업을 만들 수 없습니다.");
      return false;
    }
    return deps.ports.editorEntry.current().newDraftFromData({
      entry_reason: "document_browser_new_work",
      /* 고른 데이터의 이름은 편집기 1단계 우 열이 선택 상태로 이미 보인다 — 배너에
         한 번 더 쓰지 않는다(2026-09-03). */
      evidence: { ...extraEvidence },
      return_context: { surface: "data" },
    });
  }

  async function relinkTemplateFor(name: string): Promise<void> {
    const active = snapshot()?.job_name === name;
    const accepted = await deps.modal.confirm({
      title: "템플릿 다시 연결",
      body: active
        ? `'${name}' 작업의 템플릿 파일을 찾을 수 없어 문서를 만들 수 없습니다.\n템플릿을 다시 연결하면 작업을 다시 불러옵니다.`
        : `'${name}' 작업은 템플릿 파일을 찾을 수 없어 바로 선택할 수 없습니다.\n템플릿을 다시 연결하면 이어서 이 작업을 선택합니다. 실패하면 선택하지 않습니다.`,
      confirmLabel: "템플릿 다시 연결…",
      cancelLabel: "취소",
    });
    if (!accepted) return;
    if (active && !(await deps.ports.jobRunCoordination.current().confirmDestructiveIfArmed(
      "템플릿 다시 연결 확인", "템플릿을 다시 연결하면", "다시 연결하고 버리기",
    ))) return;
    /* 재연결 메시지의 착지 = 알림 채널(library 소비자와 같은 규율). 실패(`error`)는 서비스
       자신의 loud 채널이 이미 세우므로 여기서 두 번 말하지 않고, 능동 취소(`cancel`)는
       방금 취소를 고른 사람에게 되돌려 주지 않는다 — 남는 것은 백엔드가 실은 재진술이다. */
    const committed = await deps.services.relink.current().relinkTemplate(
      "job", name, (message, kind) => { if (kind === "ok") deps.notify(message); },
    );
    if (!committed || active) return;
    try {
      await selectJob(name);
    } catch (error) {
      deps.notify(`작업 열기 실패: ${String(error)}`);
    }
  }

  return {
    isSwitchingJob,
    selectJob,
    currentData,
    confirmDataSwap,
    connectJobData,
    toggleFavorite,
    newWorkFromData,
    relinkTemplateFor,
  };
}

export type JobReadActions = ReturnType<typeof createJobReadActions>;
