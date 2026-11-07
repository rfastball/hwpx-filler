/* 문서 열기·활성화·저장·닫기·복원 수명주기 — `authoring_controller.ts` 책임 분리(복잡도
 * 예산 — module_statements/function_statements 상한). 공유 가변 상태(뷰·viewId·호버·
 * 각종 Map)는 get/set 또는 Map 참조 그대로 deps 로 받는다. 이 모듈은 선택(select/adopt/
 * caretSelection) 쪽 상태를 몰라도 된다 — `select` 가 `activate` 를 부르는 한 방향뿐이다. */
import type { AuthoringEditor } from "./authoring_controller.ts";

type Obj = Record<string, any>;

type ModalPort = { confirm(spec: Obj): Promise<boolean>; choose(spec: Obj): Promise<string | null>; prompt(spec: Obj): Promise<string | null> };

export type LifecycleDeps = {
  runtime: { loadInitial(screen: string): Promise<unknown> };
  navigation: { go(screen: string, options?: Obj): void; refresh(screen: string): Promise<unknown> };
  modal: ModalPort;
  editors: Map<string, AuthoringEditor>;
  buffers: Map<string, string>;
  revisions: Map<string, number>;
  views: Map<string, Obj>;
  generations: Map<string, number>;
  inputPumps: Map<string, Promise<void>>;
  pendingRestore: Map<string, Obj>;
  rememberTimers: Map<string, ReturnType<typeof setTimeout>>;
  snapshot(): Obj;
  tab(id?: string): Obj;
  getView(): Obj;
  setView(view: Obj): void;
  getViewId(): string;
  setViewId(id: string): void;
  getHovered(): Obj | null;
  setHovered(value: Obj | null): void;
  getTrialTimer(): ReturnType<typeof setTimeout> | undefined;
  setTrialTimer(timer: ReturnType<typeof setTimeout> | undefined): void;
  getReturnScreen(): string;
  setReturnScreen(value: string): void;
  update(patch: Obj): void;
  guarded(work: () => unknown | Promise<unknown>, kind?: string): Promise<void>;
  fail(error: unknown, kind?: string): void;
  dispatch(action: string, payload?: Obj, verdict?: boolean): Promise<Obj>;
  invoke(method: string, ...args: unknown[]): Promise<Obj | null>;
  flush(id: string): Promise<void>;
  /** 편집기 자신의 flush 는 부르지 않는 발신열 비우기(`remember` 전용) — 한글 조합 중에도
   *  경보가 서지 않는다. */
  drain(id: string): Promise<void>;
  revision(id: string): number;
  fenced(id: string, payload?: Obj): Obj;
  currentHighlight(id?: string): Obj | null;
  /** 초기 뷰(순수) — `restoredView` 가 그 위에 복원 표시 방식·선택만 얹는다. */
  initialView(): Obj;
  /** 시험 케이스 저장 왕복(§9.2 저장 실패 복구 동사 중 하나) — 시험 클러스터 소유, 여기선
   *  `close` 의 「저장하고 닫기」 갈래가 부른다. */
  persistCases(id: string): Promise<boolean>;
};

export function createLifecycleController(deps: LifecycleDeps) {
  /** 복원 대상이 있는 새 뷰 — 표시 방식과 선택 좌표만 옮긴다. 좌표 없는 복원(stale·unreadable)은
   *  방식만 또는 아무것도. */
  function restoredView(restore: Obj | null | undefined): Obj {
    return { ...deps.initialView(), ...(restore?.mode ? { mode: restore.mode } : {}), ...(restore?.selection ? { selection: restore.selection } : {}) };
  }

  async function flushAll(): Promise<void> {
    for (const item of deps.snapshot().tabs || []) { await deps.flush(item.id); await deps.inputPumps.get(item.id); }
    for (const id of [...deps.rememberTimers.keys()]) await remember(id);
  }

  function scheduleRemember(id: string): void {
    clearTimeout(deps.rememberTimers.get(id));
    deps.rememberTimers.set(id, setTimeout(() => { void deps.guarded(() => remember(id), "remember"); }, 400));
  }

  /** 최근 작업 위치·표시 방식을 Python 에 보낸다. 편집기 flush 는 부르지 않는다 — 한글 조합
   *  중에도 경보가 서지 않는다. */
  async function remember(id: string): Promise<void> {
    clearTimeout(deps.rememberTimers.get(id));
    deps.rememberTimers.delete(id);
    const state = deps.views.get(id);
    if (!state || !deps.tab(id).id) return;
    await deps.drain(id);
    await deps.dispatch("remember_view", deps.fenced(id, {
      selection: coordinatesOf(state.selection), mode: state.mode || "template",
    }));
  }

  /** 편집기 선택 좌표만 남긴다 — `coordinates`(authoring_controller.ts)와 같은 열쇠를 쓰지만
   *  순환 import 를 피하려 여기서 같은 모양으로 다시 짓는다(값은 같다, 상태 없음). */
  const COORDINATE_KEYS = ["start", "end", "entry", "paragraph", "start_paragraph", "end_paragraph", "cell_path"];
  function coordinatesOf(selection: Obj | null | undefined): Obj {
    const picked: Obj = {};
    for (const key of COORDINATE_KEYS) if (selection?.[key] !== undefined && selection?.[key] !== null) picked[key] = selection[key];
    return picked.start === undefined || picked.end === undefined ? {} : picked;
  }

  /** 편집기가 붙어 있으면 복원을 적용한다 — 활성화와 편집기 부착 중 늦게 오는 쪽이 적용한다
   *  (순서는 경쟁이다). */
  async function applyRestore(id: string): Promise<void> {
    const editor = deps.editors.get(id);
    const pending = deps.pendingRestore.get(id);
    if (!editor || !pending) return;
    deps.pendingRestore.delete(id);
    editor.decorate(deps.tab(id).analysis || {}, deps.views.get(id)?.mode || "template", deps.currentHighlight(id));
    // 좌표는 Python 이 이 bytes 에 대해 유효하다고 판정한 것이다. 그래도 편집기가 거절하면 알리되 문서 열기는 막지 않는다.
    if (pending.selection) await editor.focus(pending.selection).catch((error) => deps.fail(error, "restore"));
  }

  /** 활성화 전 범위 고르기 종료 — 떠나는 편집면의 고르기를 끈다(복잡도 예산 — `activate`
   *  분리의 추출 대상). 이 자리는 **`viewId` 를 새 문서로 옮긴 뒤, `view` 는 아직 옛 탭일 때**다
   *  — 끄는 대상은 방금 떠난 편집면이다. */
  function endOutgoingRangePick(): void {
    const viewId = deps.getViewId();
    if (viewId && deps.getView().rangePick) {
      void Promise.resolve(deps.editors.get(viewId)?.rangePick?.(false)).catch(() => undefined);
    }
  }

  /** 활성화할 뷰 계산 — 알던 뷰가 있으면 그것, 없으면 복원 대상으로 지은 새 뷰(복잡도 예산 —
   *  `activate` 분리의 추출 대상). 좌표 있는 복원은 **새 뷰에 한 번** 소비하도록 표지를 남긴다. */
  function activatedView(id: string, activated: Obj, current: Obj): Obj {
    const known = deps.views.get(id);
    const restore = activated.restore ?? current.restore;
    if (!known && (restore?.mode || restore?.selection)) deps.pendingRestore.set(id, { selection: restore.selection || null });
    return { ...(known || restoredView(restore)), rangePick: null, proposalOpen: null };
  }

  async function activate(id: string): Promise<void> {
    clearTimeout(deps.getTrialTimer());
    const activeId = deps.snapshot().active_id;
    if (activeId) { await deps.flush(activeId); await deps.inputPumps.get(activeId); }
    const activated = await deps.dispatch("activate", { session_id: id });
    const current = deps.tab(id);
    deps.setViewId(id);
    deps.setHovered(null);
    endOutgoingRangePick();
    deps.setView(activatedView(id, activated, current));
    deps.update({
      values: { ...(current.values || {}) }, selectedOptions: { ...(current.selected || {}) },
    });
    await applyRestore(id);
  }

  // 돌아갈 곳은 연 쪽이 정한다 — 편집기 목록이 기본이고, 작업대의 「템플릿 편집」은 「문서 만들기」로 돌아온다(#1148).
  async function open(path?: string, returnTo = "editor"): Promise<void> {
    await deps.runtime.loadInitial("authoring");
    deps.setReturnScreen(returnTo);
    if (path) {
      const result = await deps.invoke("open_authoring_document", path, true);
      if (!result) return;
      deps.revisions.set(result.session_id, result.revision);
      await activate(result.session_id);
    }
    deps.navigation.go("authoring", { force: true });
  }

  async function openFile(): Promise<void> {
    const result = await deps.invoke("open_authoring_document", "", false);
    if (!result) return;
    deps.revisions.set(result.session_id, result.revision);
    await activate(result.session_id);
    // 여는 응답의 알림 칸 — Python 이 준 문장만, 다음 편집에서 사라진다. 처음 여는 일반 문서의 첫 안내는 퇴역했다(NG-01):
    // 필드 만들기 안내는 구조 패널의 빈 상태가 늘 보이는 자리에서 맡는다.
    if (result.notice && deps.getViewId() === result.session_id) deps.update({ notice: result.notice });
  }

  /** `save` 발신 — 다른 이름·첫 저장·필요 저장은 피커 왕복(`invoke`), 그 외는 제자리 저장
   *  (`dispatch`)이다(복잡도 예산 — `save` 분리의 추출 대상). */
  function saveRequest(id: string, saveAs: boolean): Promise<Obj | null> {
    return saveAs || !deps.tab(id).path || deps.tab(id).save_as_required
      ? deps.invoke("save_authoring_document", id, deps.revision(id))
      : deps.dispatch("save", deps.fenced(id));
  }

  /** 저장 응답의 충돌·외부 변경 판정 — 복구 동사(비교·다른 이름·다시 열기·다시 저장, §9.2)를
   *  남기고 거절한다(복잡도 예산 — `save` 분리의 추출 대상). */
  function settleSaveConflict(result: Obj | null): boolean {
    if (!(result?.external_changed || result?.conflict)) return false;
    deps.update({ panel: "external", saveFailed: true });
    deps.fail(result?.message || "저장할 파일이 변경되었거나 이미 존재합니다. 다른 이름으로 저장하세요.", "save");
    return true;
  }

  async function save(id = deps.snapshot().active_id, saveAs = false): Promise<boolean> {
    await deps.flush(id);
    let result: Obj | null;
    try {
      result = await saveRequest(id, saveAs);
    } catch (error) { deps.update({ saveFailed: true }); throw error; }
    if (result?.needs_save_as) return save(id, true);
    if (settleSaveConflict(result)) return false;
    if (!result || result.cancelled) return false;
    const view = deps.getView();
    deps.update({
      saveFailed: false, notice: result.notice || "", panel: view.panel === "external" ? "" : view.panel,
      ...(view.errorKind === "save" ? { error: "", errorKind: "" } : {}),
    });
    await deps.navigation.refresh("tpl");
    return true;
  }

  /** 「저장하고 닫기」 전 저장 — 템플릿·시험 자료 중 손댄 것만 저장한다(복잡도 예산 —
   *  `close` 분리의 추출 대상). */
  async function saveBeforeClose(id: string, result: Obj): Promise<boolean> {
    if (result.dirty && !(await save(id))) return false;
    if (result.cases_dirty && !(await deps.persistCases(id))) return false;
    return true;
  }

  /** 닫기 전 확인 왕복 — 「계속 편집」·「저장하지 않고 닫기」·「저장하고 닫기」 선택을 받는다.
   *  거절(취소)이면 `null`, 그 외에는 다음에 보낼 force 재시도의 결과다(복잡도 예산 — `close`
   *  분리의 추출 대상). */
  async function confirmCloseIfDirty(id: string, result: Obj): Promise<Obj | null> {
    if (!result.needs_confirm) return result;
    const answer = await deps.modal.choose({
      title: deps.tab(id).name || "문서 닫기",
      body: result.cases_dirty ? "템플릿과 시험 자료의 미저장 변경을 확인하세요." : "템플릿에 저장하지 않은 변경이 있습니다.",
      choices: [{ value: "save", label: "저장하고 닫기" }, { value: "discard", label: "저장하지 않고 닫기", danger: true },
        { value: "cancel", label: "계속 편집" }],
    });
    if (!answer || answer === "cancel") return null;
    if (answer === "save" && !(await saveBeforeClose(id, result))) return null;
    return deps.dispatch("close", { session_id: id, force: true });
  }

  /** 세션 정리 — 문서 하나의 흔적을 전부 걷는다(복잡도 예산 — `close` 분리의 추출 대상,
   *  분기 없는 정리 5종을 한 자리로). */
  function clearSession(id: string): void {
    deps.revisions.delete(id);
    deps.buffers.delete(id);
    deps.views.delete(id);
    deps.generations.delete(id);
    deps.pendingRestore.delete(id);
    clearTimeout(deps.rememberTimers.get(id));
    deps.rememberTimers.delete(id);
  }

  async function close(id: string): Promise<boolean> {
    await deps.flush(id);
    await deps.inputPumps.get(id);
    // 남은 작업 위치를 먼저 보낸다. 실패는 알리되 문서 닫기를 막지 않는다(잃는 것은 위치 기록뿐이다).
    if (deps.rememberTimers.has(id)) await remember(id).catch((error) => deps.fail(error, "remember"));
    const initial = await deps.dispatch("close", { session_id: id, force: false });
    const result = await confirmCloseIfDirty(id, initial);
    if (result === null) return false;
    clearSession(id);
    if (deps.snapshot().active_id) await activate(deps.snapshot().active_id);
    return !result.needs_confirm;
  }

  async function leaveTo(to: string): Promise<void> {
    await flushAll();
    // 화면 이동은 문서를 닫지 않는다. 탭과 각 편집기 history는 마운트된 채 유지한다.
    deps.navigation.go(to, { force: true });
  }

  async function restored(result: Obj): Promise<void> {
    const id = result.session_id;
    deps.buffers.delete(id);
    deps.revisions.set(id, result.revision);
    deps.generations.set(id, (deps.generations.get(id) || 0) + 1);
    await activate(id);
    deps.update({ preview: null, comparison: null });
  }

  return {
    flushAll, activate, open, openFile, save, close, leaveTo, restored, applyRestore,
    scheduleRemember, remember,
  };
}

export type LifecycleController = ReturnType<typeof createLifecycleController>;
